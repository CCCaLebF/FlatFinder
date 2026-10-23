"""Phase H: Compare homes — the compare tray, the Compare Score and the Compare page."""
from decimal import Decimal

import pytest
from django.urls import reverse

from backend.core.models import SearchQuery
from backend.core.services.compare import CompareController, compare_homes, default_weights, parse_weights
from backend.core.services.search import SearchController


def _toggle_url(flat_id):
    return reverse("core:api_toggle_compare", args=[flat_id])


# --- CompareController (session tray) ------------------------------------------------------

class _FakeSession(dict):
    """A dict with the `modified` flag Django's session backend expects."""
    modified = False


def test_tray_toggle_adds_and_removes():
    session = _FakeSession()
    controller = CompareController()
    assert controller.toggle(session, 1) is True
    assert controller.toggle(session, 2) is True
    assert controller.ids(session) == [1, 2]
    assert controller.toggle(session, 1) is False  # now removed
    assert controller.ids(session) == [2]


def test_tray_is_capped_at_three():
    session = _FakeSession()
    controller = CompareController()
    for i in range(1, 5):
        controller.toggle(session, i)
    assert controller.ids(session) == [1, 2, 3]


# --- Compare Score -------------------------------------------------------------------------

@pytest.mark.django_db
def test_compare_winner_and_points_add_up(make_flat):
    cheap = make_flat(block="1A", resale_price=Decimal("300000"), remaining_lease=80, floor_area_sqm=100)
    dear = make_flat(block="2B", resale_price=Decimal("600000"), remaining_lease=60, floor_area_sqm=90)
    result = compare_homes([cheap, dear], weights={"price": 5, "lease": 5, "area": 0})
    assert result["winner"]["flat"].id == cheap.id  # cheaper + longer lease wins
    assert result["winner"]["is_winner"] is True
    for home in result["homes"]:
        total = sum(p for p in home["points"].values() if p is not None)
        assert total == pytest.approx(home["total"], abs=0.1)


@pytest.mark.django_db
def test_compare_with_search_matches_the_fit_score(make_flat):
    a = make_flat(block="1A", resale_price=Decimal("300000"), remaining_lease=80,
                  latitude=1.37, longitude=103.85,
                  proximity={"nearest_mrt_station_m": 200, "nearest_bus_stop_m": 300})
    b = make_flat(block="2B", resale_price=Decimal("600000"), remaining_lease=60,
                  latitude=1.38, longitude=103.86,
                  proximity={"nearest_mrt_station_m": 800, "nearest_bus_stop_m": 900})
    query = SearchQuery(maxBudget=700_000, mrtStationWeight=8, busStopWeight=3)
    controller = SearchController()
    bounds = controller.bounds_for(query)
    result = compare_homes([a, b], query=query, bounds=bounds)
    for home in result["homes"]:
        fit = controller.calculate_fit_score(home["flat"], query, bounds)
        assert home["total"] == pytest.approx(fit.total, abs=0.1)


def test_default_weights_follow_the_fit_score():
    query = SearchQuery(mrtStationWeight=8, busStopWeight=3)
    weights = default_weights(query)
    assert weights["price"] == 5 and weights["lease"] == 5 and weights["area"] == 0
    assert weights["mrt_station"] == 8 and weights["bus_stop"] == 3
    assert weights["child_care_centre"] == 0  # ignored in the search -> ignored here
    assert "anchor" not in weights


def test_parse_weights_overrides_defaults():
    from django.http import QueryDict

    query = SearchQuery(mrtStationWeight=8)
    params = QueryDict("cw_area=5&cw_mrt_station=2")
    weights = parse_weights(params, query)
    assert weights["area"] == 5
    assert weights["mrt_station"] == 2
    assert weights["price"] == 5  # untouched default


def test_parse_weights_off_flag_ignores():
    from django.http import QueryDict

    query = SearchQuery(mrtStationWeight=8)
    params = QueryDict("cw_mrt_station_off=1&cw_area=7")
    weights = parse_weights(params, query)
    assert weights["mrt_station"] == 0  # the ignore flag drops it
    assert weights["area"] == 7


# --- Compare page + toggle endpoint --------------------------------------------------------

@pytest.mark.django_db
def test_compare_page_renders_two_homes(client, make_flat):
    a = make_flat(block="1A", resale_price=Decimal("300000"))
    b = make_flat(block="2B", resale_price=Decimal("500000"))
    session = client.session
    session["compare_ids"] = [a.id, b.id]
    session.save()

    response = client.get(reverse("core:compare"))
    assert response.status_code == 200
    assert len(response.context["result"]["homes"]) == 2
    content = response.content.decode()
    assert "Compare homes" in content and "wins" in content


@pytest.mark.django_db
def test_compare_page_with_one_home_shows_hint(client, make_flat):
    a = make_flat(block="1A", resale_price=Decimal("300000"))
    session = client.session
    session["compare_ids"] = [a.id]
    session.save()

    response = client.get(reverse("core:compare"))
    assert response.context["result"] is None
    assert "Select 2–3 homes to compare" in response.content.decode()


@pytest.mark.django_db
def test_toggle_endpoint_adds_and_caps(client, make_flat):
    flats = [make_flat(block=str(i), resale_price=Decimal(300_000 + i * 1000)) for i in range(4)]
    for flat in flats[:2]:
        response = client.post(_toggle_url(flat.id), HTTP_ACCEPT="application/json")
        assert response.json()["count"] == flats.index(flat) + 1
    # A third and fourth toggle: the fourth is rejected (cap of 3).
    client.post(_toggle_url(flats[2].id), HTTP_ACCEPT="application/json")
    client.post(_toggle_url(flats[3].id), HTTP_ACCEPT="application/json")
    assert len(client.session["compare_ids"]) == 3


@pytest.mark.django_db
def test_active_search_persists_to_saved_compare(client, make_flat):
    make_flat()
    # A search remembers its context for Saved's Compare.
    client.get(reverse("core:results"), {"w_bus_stop": 5})
    assert "from=results" in client.session["active_search"]
    assert "from=results" in client.get(reverse("core:saved")).context["compare_query"]
    # Visiting Results without a search clears it, so Saved falls back to "from=saved".
    client.get(reverse("core:results"))
    assert client.get(reverse("core:saved")).context["compare_query"] == "from=saved"


@pytest.mark.django_db
def test_reset_to_start_clears_active_search(client, make_flat):
    make_flat()
    client.get(reverse("core:results"), {"w_bus_stop": 5})
    assert "from=results" in client.session["active_search"]
    # The Reset button goes to Start, which clears the active search.
    client.get(reverse("core:start"))
    assert "active_search" not in client.session
    assert client.get(reverse("core:saved")).context["compare_query"] == "from=saved"
