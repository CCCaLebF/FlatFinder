"""Phase 3: UC-01/08/09 — SearchQuery parsing, filtering, the Fit Score and ranking (PLAN §4)."""
import time

from decimal import Decimal

import pytest
from django.http import QueryDict
from django.urls import reverse

from backend.core.views.forms import SearchForm
from backend.core.services.search import ScoreBounds, SearchController
from backend.core.models import FlatProximity, ResaleFlat, SearchQuery

from .conftest import build_flat

controller = SearchController()
BOUNDS = ScoreBounds(minPrice=400_000, maxPrice=600_000, minLease=60)


def fit(flat, query, bounds=BOUNDS):
    return controller.calculate_fit_score(flat, query, bounds)


# --- The formula ------------------------------------------------------------------

@pytest.mark.django_db
def test_formula_worked_example(make_flat):
    # price (600k−500k)/(600k−400k) = 0.5; lease (79.5−60)/(99−60) = 0.5; MRT 1 − 250/1000 = 0.75
    flat = make_flat(resale_price=Decimal("500000"), remaining_lease=79.5,
                     proximity={"nearest_mrt_station_m": 250, "nearest_bus_stop_m": 100},
                     latitude=1.37, longitude=103.85)
    score = fit(flat, SearchQuery(mrtStationWeight=10))
    assert (score.priceScore, score.leaseScore, score.mrtStationScore) == (0.5, 0.5, 0.75)
    # (5 × 0.5 + 5 × 0.5 + 10 × 0.75) / (5 + 5 + 10) = 0.625
    assert score.total == 62.5


@pytest.mark.django_db
def test_ignored_categories_are_left_out(make_flat):
    flat = make_flat(resale_price=Decimal("500000"), remaining_lease=79.5,
                     proximity={"nearest_bus_stop_m": 0}, latitude=1.37, longitude=103.85)
    score = fit(flat, SearchQuery())
    assert score.busStopScore is None and score.anchorScore is None
    assert score.total == 50.0  # only price and lease count
    assert fit(flat, SearchQuery(busStopWeight=10)).total == 75.0  # (2.5 + 2.5 + 10) / 20


@pytest.mark.django_db
def test_missing_coordinates_score_zero_proximity(make_flat):
    flat = make_flat(resale_price=Decimal("500000"), remaining_lease=79.5)  # proximity all null
    score = fit(flat, SearchQuery(mrtStationWeight=10, hawkerCentreWeight=5))
    assert score.mrtStationScore == 0 and score.hawkerCentreScore == 0
    assert score.total == 20.0  # (2.5 + 2.5 + 0 + 0) / 25 — still in the denominator


@pytest.mark.django_db
@pytest.mark.parametrize("metres, expected", [(0, 1.0), (500, 0.5), (999, 0.001), (1000, 0.0), (2500, 0.0)])
def test_proximity_falls_to_zero_at_1km(make_flat, metres, expected):
    flat = make_flat(proximity={"nearest_chas_clinic_m": metres}, latitude=1.37, longitude=103.85)
    assert fit(flat, SearchQuery(chasClinicWeight=3)).chasClinicScore == pytest.approx(expected)


def test_price_and_lease_clamp_to_0_1():
    query = SearchQuery()
    assert fit(build_flat(resale_price=Decimal("300000"), remaining_lease=99), query).priceScore == 1
    assert fit(build_flat(resale_price=Decimal("700000"), remaining_lease=40), query).priceScore == 0
    assert fit(build_flat(remaining_lease=40), query).leaseScore == 0
    assert fit(build_flat(remaining_lease=99), query).leaseScore == 1


def test_zero_width_range_scores_one():
    bounds = ScoreBounds(minPrice=500_000, maxPrice=500_000, minLease=99)
    score = fit(build_flat(resale_price=Decimal("500000"), remaining_lease=99), SearchQuery(), bounds)
    assert (score.priceScore, score.leaseScore, score.total) == (1, 1, 100.0)


def test_anchor_sub_score():
    query = SearchQuery()
    query.setAnchor(1.37, 103.85, "Somewhere")
    assert query.anchorWeight == 5
    at_anchor = fit(build_flat(latitude=1.37, longitude=103.85), query)
    assert at_anchor.anchorScore == 1
    # ~1.5 km north of the anchor -> about half of the 3 km radius.
    north = fit(build_flat(latitude=1.37 + 1500 / 111_195, longitude=103.85), query)
    assert north.anchorScore == pytest.approx(0.5, abs=0.002)
    assert fit(build_flat(), query).anchorScore == 0  # no coordinates


# --- Unconstrained thresholds (FR 1.1.6) -------------------------------------------

@pytest.mark.django_db
def test_blank_budget_and_lease_use_the_filtered_set(make_flat):
    cheap = make_flat(resale_price=Decimal("300000"), remaining_lease=50)
    mid = make_flat(resale_price=Decimal("400000"), remaining_lease=70)
    dear = make_flat(resale_price=Decimal("500000"), remaining_lease=90)
    query = SearchQuery()
    result = controller.rank_flats(controller.filter_flats(query), query)
    assert result.bounds == ScoreBounds(300_000, 500_000, 50)
    assert result.fitScores[cheap.id].priceScore == 1 and result.fitScores[dear.id].priceScore == 0
    assert result.fitScores[mid.id].priceScore == 0.5
    assert result.fitScores[cheap.id].leaseScore == 0
    assert result.fitScores[dear.id].leaseScore == pytest.approx(40 / 49, abs=1e-3)


@pytest.mark.django_db
def test_one_sided_budget_uses_the_set_for_the_other_side(make_flat):
    make_flat(resale_price=Decimal("300000"))
    make_flat(resale_price=Decimal("450000"))
    query = SearchQuery(maxBudget=600_000)
    result = controller.rank_flats(controller.filter_flats(query), query)
    assert (result.bounds.minPrice, result.bounds.maxPrice) == (300_000, 600_000)


@pytest.mark.django_db
def test_single_flat_with_blank_thresholds(make_flat):
    flat = make_flat(remaining_lease=54)
    query = SearchQuery()
    result = controller.rank_flats(controller.filter_flats(query), query)
    score = result.fitScores[flat.id]
    # Price: min == max, so 1. Lease: minLease is this flat's own lease, and the range
    # still runs to 99, so (54 − 54) / (99 − 54) = 0.
    assert (score.priceScore, score.leaseScore, score.total) == (1, 0, 50.0)


# --- UC-08 filters ----------------------------------------------------------------

@pytest.mark.django_db
def test_hard_filters(make_flat):
    a = make_flat(resale_price=Decimal("350000"), flat_type="3 ROOM", remaining_lease=55)
    b = make_flat(resale_price=Decimal("520000"), flat_type="4 ROOM", remaining_lease=80)
    c = make_flat(resale_price=Decimal("800000"), flat_type="5 ROOM", remaining_lease=92)

    def ids(**criteria):
        return set(controller.filter_flats(SearchQuery(**criteria)).values_list("id", flat=True))

    assert ids() == {a.id, b.id, c.id}
    assert ids(minBudget=400_000, maxBudget=600_000) == {b.id}
    assert ids(flatTypes=["3 ROOM", "5 ROOM"]) == {a.id, c.id}
    assert ids(minRemainingLease=80) == {b.id, c.id}
    assert ids(maxBudget=100_000) == set()


@pytest.mark.django_db
def test_walk_limits_are_a_provisional_hard_filter(make_flat):
    near = make_flat(proximity={"nearest_bus_stop_m": 150, "nearest_mrt_station_m": 300}, latitude=1.3, longitude=103.8)
    far = make_flat(proximity={"nearest_bus_stop_m": 150, "nearest_mrt_station_m": 1200}, latitude=1.3, longitude=103.8)
    no_coords = make_flat()

    def ids(**criteria):
        return set(controller.filter_flats(SearchQuery(**criteria)).values_list("id", flat=True))

    assert ids(maxWalkMrt=500) == {near.id}
    assert ids(maxWalkBus=200) == {near.id, far.id}
    assert no_coords.id in ids()  # no limit set: flats without coordinates still listed


# --- UC-09 ranking ------------------------------------------------------------------

@pytest.mark.django_db
def test_ranked_by_fit_score_descending_with_stable_ties(make_flat):
    worst = make_flat(resale_price=Decimal("500000"), remaining_lease=60)
    best = make_flat(resale_price=Decimal("300000"), remaining_lease=90)
    tie_dear = make_flat(resale_price=Decimal("400000"), remaining_lease=75)
    tie_cheap = make_flat(resale_price=Decimal("400000"), remaining_lease=75)
    query = SearchQuery()
    result = controller.rank_flats(controller.filter_flats(query), query)
    assert result.flatIds[0] == best.id and result.flatIds[-1] == worst.id
    totals = [result.fitScores[i].total for i in result.flatIds]
    assert totals == sorted(totals, reverse=True)
    assert result.count == 4 and not result.isEmpty
    assert {tie_dear.id, tie_cheap.id} == set(result.flatIds[1:3])


@pytest.mark.django_db
def test_empty_result():
    query = SearchQuery()
    result = controller.rank_flats(controller.filter_flats(query), query)
    assert result.isEmpty and result.count == 0


# --- NFR 1 -------------------------------------------------------------------------

@pytest.mark.django_db
def test_nfr1_ranking_25k_flats_is_well_under_a_second():
    flats = [build_flat(resale_price=Decimal(300_000 + (i % 500) * 1000), remaining_lease=50 + i % 45,
                        flat_type=["3 ROOM", "4 ROOM", "5 ROOM"][i % 3],
                        latitude=1.3 + (i % 100) / 1000, longitude=103.8 + (i % 77) / 1000)
             for i in range(25_000)]
    ResaleFlat.objects.bulk_create(flats, batch_size=5000)
    FlatProximity.objects.bulk_create(
        [FlatProximity(flat_id=fid, nearest_bus_stop_m=(fid % 900), nearest_mrt_station_m=(fid % 1500),
                       nearest_child_care_centre_m=200, nearest_hawker_centre_m=700, nearest_chas_clinic_m=None)
         for fid in ResaleFlat.objects.values_list("id", flat=True)], batch_size=5000)

    query = SearchQuery(busStopWeight=5, mrtStationWeight=8, childCareCentreWeight=3,
                        hawkerCentreWeight=6, chasClinicWeight=2)
    query.setAnchor(1.35, 103.83, "Anchor")
    # Best of three, so a busy machine doesn't fail the test; NFR 1 itself allows 5 s.
    timings = []
    for _ in range(3):
        start = time.perf_counter()
        result = controller.rank_flats(controller.filter_flats(query), query)
        first_page = [result.fitScores[i] for i in result.flatIds[:20]]
        timings.append(time.perf_counter() - start)

    assert result.count == 25_000 and len(first_page) == 20
    assert min(timings) < 1.0, f"ranking took {min(timings):.2f} s at best"


# --- SearchForm -> SearchQuery -------------------------------------------------------

def form_query(params):
    form = SearchForm(QueryDict(params))
    assert form.is_valid(), form.errors
    return form.to_query()


def test_form_builds_search_query():
    query = form_query("min_budget=300000&max_budget=600000&flat_type=4+ROOM&flat_type=5+ROOM"
                       "&min_lease=70&max_walk_mrt=500&bus_any=1&max_walk_bus=300"
                       "&w_bus_stop=3&w_mrt_station=9&ignore_child_care_centre=1&w_child_care_centre=4")
    assert (query.minBudget, query.maxBudget) == (300_000, 600_000)
    assert query.flatTypes == ["4 ROOM", "5 ROOM"]
    assert query.minRemainingLease == 70
    assert (query.maxWalkMrt, query.maxWalkBus) == (500, None)  # bus "No limit" ticked
    assert query.categoryWeights() == {"bus_stop": 3, "mrt_station": 9}  # child care ignored, others blank
    assert not query.hasAnchor


def test_form_blank_means_unconstrained():
    query = form_query("min_budget=&max_budget=&lease_any=1&min_lease=70")
    for field in ("minBudget", "maxBudget", "flatTypes", "minRemainingLease", "maxWalkBus", "maxWalkMrt"):
        assert query.isUnconstrained(field)


def test_form_anchor_params():
    query = form_query("anchor_lat=1.35&anchor_lng=103.83&anchor_label=Bishan&w_anchor=8")
    assert query.hasAnchor and (query.anchorLabel, query.anchorWeight) == ("Bishan", 8)


@pytest.mark.parametrize("params", [
    "min_budget=600000&max_budget=300000", "w_bus_stop=11", "w_bus_stop=0",
    "max_walk_bus=20", "flat_type=PENTHOUSE", "min_lease=120",
])
def test_form_rejects_invalid_input(params):
    assert not SearchForm(QueryDict(params)).is_valid()


def test_sidebar_defaults_for_a_fresh_search():
    state = SearchForm(QueryDict("view=list")).sidebar_state()
    assert all(not w["off"] and w["value"] == 5 for w in state["weights"])
    assert all(w["off"] for w in state["walks"]) and state["lease"]["off"]


def test_sidebar_reflects_submitted_search():
    form = SearchForm(QueryDict("w_bus_stop=7&ignore_mrt_station=1&w_mrt_station=5&max_walk_bus=300&flat_type=3+ROOM"))
    form.is_valid()
    state = form.sidebar_state()
    weights = {w["name"]: w for w in state["weights"]}
    assert weights["w_bus_stop"]["value"] == 7 and not weights["w_bus_stop"]["off"]
    assert weights["w_mrt_station"]["off"]
    assert weights["w_chas_clinic"]["off"]  # not in the URL -> blank -> ignored
    assert state["walks"][0]["value"] == 300 and not state["walks"][0]["off"]
    assert [t["value"] for t in state["flat_types"] if t["checked"]] == ["3 ROOM"]


# --- Pages -------------------------------------------------------------------------

@pytest.mark.django_db
def test_start_page_shows_sidebar(client):
    response = client.get(reverse("core:start"))
    content = response.content.decode()
    assert response.status_code == 200
    assert "Find Matching Flats" in content
    for label in ("Bus Stops", "MRT Stations", "Child Care Centres", "Hawker Centres", "CHAS Clinics"):
        assert label in content


@pytest.mark.django_db
def test_results_page_lists_ranked_flats(client, make_flat):
    make_flat(block="1A", resale_price=Decimal("300000"), remaining_lease=90, coords_approximate=True,
              latitude=1.37, longitude=103.85)
    make_flat(block="9Z", resale_price=Decimal("600000"), remaining_lease=60)
    response = client.get(reverse("core:results"), {"w_bus_stop": 5, "view": "list"})
    content = response.content.decode()
    assert response.status_code == 200
    assert "2 flats in 2 blocks match" in content
    assert content.index("Blk 1A") < content.index("Blk 9Z")
    assert "S$300,000" in content and "Fit Score" in content
    assert "Approximate location (town centre)" in content
    assert "Location not available" in content
    assert "from=results" in content and "w_bus_stop=5" in content  # details link keeps the query


@pytest.mark.django_db
def test_results_are_paginated_20_per_page(client):
    ResaleFlat.objects.bulk_create([build_flat(block=str(i), resale_price=Decimal(300_000 + i)) for i in range(45)])
    first = client.get(reverse("core:results"))
    assert first.context["page"].paginator.num_pages == 3
    assert len(first.context["cards"]) == 20
    last = client.get(reverse("core:results"), {"page": 3})
    assert len(last.context["cards"]) == 5
    assert "Showing 41–45 of 45" in last.content.decode()


@pytest.mark.django_db
def test_no_results_state(client, make_flat):
    make_flat(resale_price=Decimal("500000"))
    response = client.get(reverse("core:results"), {"max_budget": 100000})
    assert response.status_code == 200
    content = response.content.decode()
    assert "No flats match your requirements" in content
    assert "Adjust your requirements" in content


@pytest.mark.django_db
def test_invalid_search_shows_errors(client):
    response = client.get(reverse("core:results"), {"min_budget": 600000, "max_budget": 300000})
    assert response.status_code == 400
    assert "Maximum budget must be at least the minimum budget." in response.content.decode()


@pytest.mark.django_db
def test_view_toggle_keeps_the_search(client, make_flat):
    make_flat()
    content = client.get(reverse("core:results"), {"max_budget": 700000, "page": 1}).content.decode()
    assert "?max_budget=700000&amp;view=map" in content


# --- Fixes from the pre-phase-5 review ---------------------------------------------------

@pytest.mark.django_db
def test_error_messages_name_the_control(client):
    response = client.get(reverse("core:results"), {"w_hawker_centre": 50, "min_budget": 5, "max_budget": 1})
    content = response.content.decode()
    assert "Hawker Centres importance: Ensure this value is less than or equal to 10." in content
    assert "Maximum budget must be at least the minimum budget." in content
    assert "Maximum budget: Maximum budget" not in content


@pytest.mark.django_db
def test_singular_result_heading(client, make_flat):
    make_flat()
    assert "1 flat in 1 block matches" in client.get(reverse("core:results")).content.decode()


@pytest.mark.django_db
def test_off_sliders_are_not_server_disabled(client):
    # Without JS the user must still be able to untick "Any" and use the slider.
    content = client.get(reverse("core:start")).content.decode()
    assert 'name="min_lease"' in content
    assert " disabled" not in content
