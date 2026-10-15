"""Phase 5: UC-02 View Flat Details and UC-11 Find Nearest Amenity."""

from decimal import Decimal

import pytest
from django.http import QueryDict
from django.urls import reverse

from core.boundary.ui.forms import SearchForm
from core.control.amenity import AmenityController
from core.control.distance import StraightLineDistance
from core.control.search import SearchController
from core.entity import BusStop, ChasClinic, HawkerCentre, MrtStation, SearchQuery
from core.templatetags.flatfinder import display_name

FLAT_AT = (1.3700, 103.8500)
METRE_LAT = 1 / 111_195  # degrees of latitude per metre


def north(metres):
    return FLAT_AT[0] + metres * METRE_LAT, FLAT_AT[1]


@pytest.fixture
def located_flat(make_flat):
    return make_flat(latitude=FLAT_AT[0], longitude=FLAT_AT[1], block="1A",
                     proximity={"nearest_bus_stop_m": 100, "nearest_mrt_station_m": 300})


def details_url(flat, query=""):
    url = reverse("core:flat_details", args=[flat.id])
    return f"{url}?{query}" if query else url


# --- AmenityController (UC-11) ------------------------------------------------------

@pytest.mark.django_db
def test_nearest_amenities_within_1km_sorted_by_distance(located_flat):
    for code, metres in (("3", 900), ("1", 120), ("2", 450), ("4", 1100)):
        lat, lng = north(metres)
        BusStop.objects.create(name=f"Bus Stop {code}", stop_code=code, latitude=lat, longitude=lng)
    lat, lng = north(250)
    HawkerCentre.objects.create(name="Nearby Market", address="1 Some Road", latitude=lat, longitude=lng)
    # Far east: outside the bounding box, never fetched.
    ChasClinic.objects.create(name="Far Clinic", latitude=FLAT_AT[0], longitude=FLAT_AT[1] + 0.05)

    nearby = AmenityController().find_nearest_amenities(located_flat)
    assert list(nearby) == ["bus_stop", "mrt_station", "child_care_centre", "hawker_centre", "chas_clinic"]
    assert [a.name for a in nearby["bus_stop"]] == ["Bus Stop 1", "Bus Stop 2", "Bus Stop 3"]  # 1.1 km excluded
    assert [a.distance_m for a in nearby["bus_stop"]] == [120, 450, 900]
    assert nearby["hawker_centre"][0].detail == "1 Some Road"
    assert nearby["chas_clinic"] == [] and nearby["mrt_station"] == []


@pytest.mark.django_db
def test_mrt_exits_collapse_to_nearest_exit_per_station(located_flat):
    for name, exit_code, metres in (("ALPHA MRT STATION", "Exit B", 600), ("ALPHA MRT STATION", "Exit A", 300),
                                    ("BETA MRT STATION", "Exit 1", 500)):
        lat, lng = north(metres)
        MrtStation.objects.create(name=name, exit_code=exit_code, latitude=lat, longitude=lng)
    stations = AmenityController().find_nearest_amenities(located_flat)["mrt_station"]
    assert [(s.name, s.detail, s.distance_m) for s in stations] == [
        ("ALPHA MRT STATION", "Nearest exit: Exit A", 300), ("BETA MRT STATION", "Nearest exit: Exit 1", 500)]


@pytest.mark.django_db
def test_bounding_box_matches_haversine_near_the_edge(located_flat):
    # A point 995 m away diagonally: inside the circle, near the box corner region.
    lat = FLAT_AT[0] + 700 * METRE_LAT
    lng = FLAT_AT[1] + 707 * METRE_LAT / 0.99971
    distance = StraightLineDistance().distance_m(FLAT_AT, (lat, lng))
    BusStop.objects.create(name="Corner", stop_code="9", latitude=lat, longitude=lng)
    found = AmenityController().find_nearest_amenities(located_flat)["bus_stop"]
    assert (len(found) == 1) == (distance <= 1000)


@pytest.mark.django_db
def test_no_coordinates_means_no_amenities(make_flat):
    assert AmenityController().find_nearest_amenities(make_flat()) == {}


# --- Fit Score consistency (UC-02 vs UC-09) ---------------------------------------------

@pytest.mark.django_db
def test_details_score_matches_results_score(make_flat):
    flats = [make_flat(resale_price=Decimal(p), remaining_lease=l, latitude=1.37, longitude=103.85,
                       proximity={"nearest_mrt_station_m": d, "nearest_bus_stop_m": d / 2})
             for p, l, d in (("350000", 60, 200), ("480000", 85, 650), ("610000", 72, 1200))]
    query = SearchQuery(maxBudget=650_000, mrtStationWeight=8, busStopWeight=3)
    query.setAnchor(1.36, 103.84, "Anchor")
    controller = SearchController()
    result = controller.rank_flats(controller.filter_flats(query), query)
    assert controller.bounds_for(query) == result.bounds
    for flat in flats:
        flat.refresh_from_db()
        assert controller.calculate_fit_score(flat, query, controller.bounds_for(query)) == result.fitScores[flat.id]


# --- Details page -----------------------------------------------------------------------

@pytest.mark.django_db
def test_details_page_shows_all_flat_fields(client, located_flat):
    content = client.get(details_url(located_flat, "from=results")).content.decode()
    for text in ("Blk 1A Ang Mo Kio Ave 3", "Ang Mo Kio Ave 3", "4 Room", "92 m²", "07 to 09",
                 "S$520,000", "1980", "54 yrs", "54 years 02 months at sale", "September 2026"):
        assert text in content, text


@pytest.mark.django_db
def test_unknown_flat_is_404(client):
    assert client.get(reverse("core:flat_details", args=[123456])).status_code == 404


@pytest.mark.django_db
def test_fit_score_breakdown_adds_up(client, located_flat, make_flat):
    make_flat(resale_price=Decimal("400000"), remaining_lease=80)  # widens the price/lease range
    response = client.get(details_url(located_flat, "from=results&w_mrt_station=8&ignore_bus_stop=1&w_bus_stop=5"))
    fit, rows = response.context["fit"], response.context["breakdown"]
    assert fit is not None
    assert sum(r["points"] for r in rows if not r["ignored"]) == pytest.approx(fit.total, abs=0.06)
    bus = next(r for r in rows if r["label"] == "Bus Stops")
    assert bus["ignored"] and bus["points"] is None
    mrt = next(r for r in rows if r["label"] == "MRT Stations")
    assert (mrt["weight"], mrt["score"]) == (8, 0.7)
    assert "Ignored" in response.content.decode()


@pytest.mark.django_db
def test_details_score_equals_the_card_score(client, located_flat, make_flat):
    make_flat(resale_price=Decimal("380000"), remaining_lease=90)
    query = "w_mrt_station=8&w_bus_stop=3&min_budget=300000"
    results = client.get(f"{reverse('core:results')}?{query}")
    card = next(c for c in results.context["cards"] if c["flat"].id == located_flat.id)
    shown = f'{card["fit"].total:.1f}'
    assert shown in results.content.decode()
    assert client.get(details_url(located_flat, f"from=results&{query}")).context["fit"].total == card["fit"].total


@pytest.mark.django_db
def test_no_search_means_no_fit_score(client, located_flat):
    response = client.get(details_url(located_flat, "from=saved"))
    assert response.context["fit"] is None
    assert "Start a search" in response.content.decode()


@pytest.mark.django_db
def test_invalid_search_in_link(client, located_flat):
    response = client.get(details_url(located_flat, "from=results&w_bus_stop=99"))
    assert response.status_code == 200
    assert response.context["search_error"] and response.context["fit"] is None


@pytest.mark.django_db
@pytest.mark.parametrize("query, expected", [
    ("from=results&max_budget=500000&sort=price-asc&view=list", "/results?max_budget=500000&sort=price-asc&view=list"),
    ("from=saved&view=list", "/saved/"),
    ("from=start&view=map", "/?view=map"),
    ("from=start", "/"),
    ("from=elsewhere&max_budget=1", "/?max_budget=1"),
    ("", "/"),
])
def test_back_follows_the_from_guard(client, located_flat, query, expected):
    assert client.get(details_url(located_flat, query)).context["back_url"] == expected


@pytest.mark.django_db
def test_details_lists_nearby_amenities(client, located_flat):
    lat, lng = north(300)
    MrtStation.objects.create(name="ANG MO KIO MRT STATION", exit_code="Exit A", latitude=lat, longitude=lng)
    content = client.get(details_url(located_flat)).content.decode()
    assert "Ang Mo Kio MRT Station" in content and "300 m" in content
    assert "None within 1,000 m" in content  # empty categories say so


@pytest.mark.django_db
def test_location_notices(client, make_flat):
    approx = make_flat(latitude=1.37, longitude=103.85, coords_approximate=True)
    assert "Approximate location (town centre)" in client.get(details_url(approx)).content.decode()
    missing = make_flat()
    assert "Location not available" in client.get(details_url(missing)).content.decode()


@pytest.mark.django_db
def test_details_has_bookmark_and_does_not_replace_last_browsing_page(client, located_flat):
    client.get("/results?max_budget=900000")
    content = client.get(details_url(located_flat, "from=results")).content.decode()
    assert f'data-bookmark-form="{located_flat.id}"' in content
    assert client.get(reverse("core:saved")).context["back_url"] == "/results?max_budget=900000"


def test_display_name():
    assert display_name("ANG MO KIO MRT STATION") == "Ang Mo Kio MRT Station"
    assert display_name("STAR LEARNERS PTE. LTD.") == "Star Learners PTE. LTD."
    assert display_name("Bus Stop 54621") == "Bus Stop 54621"
    assert display_name("Acumed Medical Group") == "Acumed Medical Group"
    assert display_name("BLK 628 MARKET") == "Blk 628 Market"
