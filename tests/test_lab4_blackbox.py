"""
Lab 4 §3.2.1: black box tests of «Control» SearchController — equivalence classes and
boundary values. Test IDs, ECs and oracles are in docs/testing/Lab4_Test_Design.md §1.
"""
from decimal import Decimal

import pytest
from django.http import QueryDict

from backend.core.models import FLAT_TYPES, CATEGORIES, SearchQuery, SortOrder
from backend.core.services.search import ScoreBounds, SearchController
from backend.core.views.forms import SearchForm, parse_sort_order

controller = SearchController()

# Valid values for every parameter; each invalid test overrides exactly one (§1.5).
BASELINE = {
    "min_budget": "300000", "max_budget": "700000", "flat_type": ["4 ROOM"], "min_lease": "60",
    "max_walk_bus": "400", "max_walk_mrt": "800", "sort": "fit_score-desc",
    **{f"w_{c.key}": "5" for c in CATEGORIES},
}


def params(values):
    """A QueryDict from a dict; list values become repeated parameters (flat_type=..&flat_type=..)."""
    data = QueryDict(mutable=True)
    for name, value in values.items():
        data.setlist(name, value if isinstance(value, list) else [value])
    return data


def run_search(values):
    """Drive SearchController the way the results view does: form -> query -> filter -> rank -> sort."""
    data = params(values)
    form = SearchForm(data)
    if not form.is_valid():
        return form, None, None
    query = form.to_query()
    result = controller.rank_flats(controller.filter_flats(query), query)
    result = controller.sort_results(result, parse_sort_order(data.get("sort")))
    return form, query, result


def ids_of(*flats):
    return {f.id for f in flats}


# --- 1.4 Valid inputs ------------------------------------------------------------------------

@pytest.mark.django_db
def test_bb_v1_lower_and_upper_valid_boundaries(lab4_flats):
    f = lab4_flats
    form, query, result = run_search({
        "min_budget": "0", "max_budget": "10000000", "flat_type": ["4 ROOM"], "min_lease": "0",
        "max_walk_bus": "100", "max_walk_mrt": "2000", "sort": "price-asc",
        **{f"w_{c.key}": "1" for c in CATEGORIES},
    })
    assert form.is_valid()
    assert (query.minBudget, query.maxBudget, query.minRemainingLease) == (0, 10_000_000, 0)
    assert (query.maxWalkBus, query.maxWalkMrt) == (100, 2000)
    assert query.categoryWeights() == {c.key: 1 for c in CATEGORIES}
    assert result.flatIds == [f["B"].id, f["E"].id, f["A"].id, f["C"].id]  # D is 5 ROOM; price ascending


@pytest.mark.django_db
def test_bb_v2_min_equals_max_and_other_boundaries(lab4_flats):
    form, query, result = run_search({
        "min_budget": "10000000", "max_budget": "10000000", "flat_type": list(FLAT_TYPES),
        "min_lease": "99", "max_walk_bus": "2000", "max_walk_mrt": "100", "sort": "fit_score-desc",
        **{f"w_{c.key}": "10" for c in CATEGORIES},
    })
    assert form.is_valid()
    assert (query.minBudget, query.maxBudget, query.minRemainingLease) == (10_000_000, 10_000_000, 99)
    assert (query.maxWalkBus, query.maxWalkMrt) == (2000, 100)
    assert query.flatTypes == list(FLAT_TYPES)
    assert query.categoryWeights() == {c.key: 10 for c in CATEGORIES}
    assert result.count == 0


@pytest.mark.django_db
def test_bb_v3_switched_off_criteria(lab4_flats):
    form, query, result = run_search({
        "min_budget": "0", "max_budget": "0", "flat_type": ["EXECUTIVE"], "lease_any": "on",
        "bus_any": "on", "mrt_any": "on", "sort": "floor_area-desc",
        **{f"ignore_{c.key}": "on" for c in CATEGORIES},
    })
    assert form.is_valid()
    assert (query.minBudget, query.maxBudget) == (0, 0)
    assert (query.minRemainingLease, query.maxWalkBus, query.maxWalkMrt) == (None, None, None)
    assert query.categoryWeights() == {}
    assert result.count == 0


@pytest.mark.django_db
def test_bb_v4_no_parameters_is_unconstrained(lab4_flats):
    form, query, result = run_search({})
    assert form.is_valid()
    for field in ("minBudget", "maxBudget", "flatTypes", "minRemainingLease", "maxWalkBus", "maxWalkMrt"):
        assert query.isUnconstrained(field)
    assert set(result.flatIds) == ids_of(*lab4_flats.values())


# --- 1.5 Invalid inputs: one invalid value per test case ---------------------------------------

@pytest.mark.parametrize("test_id, field, value", [
    ("BB-I1", "min_budget", "-1"),
    ("BB-I2", "min_budget", "10000001"),
    ("BB-I3", "max_budget", "-1"),
    ("BB-I4", "max_budget", "10000001"),
    ("BB-I6", "min_lease", "-1"),
    ("BB-I7", "min_lease", "100"),
    ("BB-I8", "max_walk_bus", "99"),
    ("BB-I9", "max_walk_bus", "2001"),
    ("BB-I10", "max_walk_mrt", "99"),
    ("BB-I11", "max_walk_mrt", "2001"),
    ("BB-I12", "w_mrt_station", "0"),
    ("BB-I13", "w_mrt_station", "11"),
    ("BB-I14", "flat_type", ["PENTHOUSE"]),
])
def test_bb_invalid_input_is_rejected(test_id, field, value):
    form, query, _ = run_search({**BASELINE, field: value})
    assert not form.is_valid()
    assert set(form.errors) == {field}  # only the one invalid input is reported
    assert query is None  # no search is run


def test_bb_i5_min_budget_above_max():
    form, query, _ = run_search({**BASELINE, "min_budget": "700001"})  # max stays 700,000
    assert not form.is_valid()
    assert form.errors["max_budget"] == ["Maximum budget must be at least the minimum budget."]
    assert set(form.errors) == {"max_budget"}
    assert query is None


@pytest.mark.django_db
def test_bb_i15_unknown_sort_falls_back_to_fit_score(lab4_flats):
    form, _, result = run_search({**BASELINE, "sort": "rating-asc"})
    assert form.is_valid()
    assert result.sortOrder == SortOrder("fit_score", "desc")
    assert set(result.flatIds) == ids_of(lab4_flats["A"], lab4_flats["E"])
    totals = [result.fitScores[i].total for i in result.flatIds]
    assert totals == sorted(totals, reverse=True)


# --- 1.6 Filter and score boundaries -----------------------------------------------------------

def filtered_ids(**criteria):
    return set(controller.filter_flats(SearchQuery(**criteria)).values_list("id", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize("test_id, price, included", [
    ("BB-F1", "399999", False),
    ("BB-F2", "400000", True),
    ("BB-F3", "600000", True),
    ("BB-F4", "600001", False),
])
def test_bb_budget_filter_boundaries(make_flat, test_id, price, included):
    flat = make_flat(resale_price=Decimal(price))
    assert (flat.id in filtered_ids(minBudget=400_000, maxBudget=600_000)) is included


@pytest.mark.django_db
@pytest.mark.parametrize("test_id, lease, included", [
    ("BB-F5", 59 + 11 / 12, False),  # 59 years 11 months
    ("BB-F6", 60.0, True),
])
def test_bb_lease_filter_boundaries(make_flat, test_id, lease, included):
    flat = make_flat(remaining_lease=lease)
    assert (flat.id in filtered_ids(minRemainingLease=60)) is included


@pytest.mark.django_db
@pytest.mark.parametrize("test_id, metres, included", [
    ("BB-F7", 800, True),
    ("BB-F8", 801, False),
    ("BB-F9", None, False),  # no coordinates, so no proximity data
])
def test_bb_walk_limit_boundaries(make_flat, test_id, metres, included):
    if metres is None:
        flat = make_flat()
    else:
        flat = make_flat(proximity={"nearest_mrt_station_m": metres}, latitude=1.35, longitude=103.85)
    assert (flat.id in filtered_ids(maxWalkMrt=800)) is included


@pytest.mark.django_db
@pytest.mark.parametrize("test_id, metres, expected", [
    ("BB-S1", 0, 1.0),
    ("BB-S2", 250, 0.75),
    ("BB-S3", 1000, 0.0),
    ("BB-S4", 1001, 0.0),
    ("BB-S5", None, 0.0),
])
def test_bb_mrt_sub_score_boundaries(make_flat, test_id, metres, expected):
    if metres is None:
        flat = make_flat()
    else:
        flat = make_flat(proximity={"nearest_mrt_station_m": metres}, latitude=1.35, longitude=103.85)
    bounds = ScoreBounds(minPrice=400_000, maxPrice=600_000, minLease=60)
    score = controller.calculate_fit_score(flat, SearchQuery(mrtStationWeight=10), bounds)
    assert score.mrtStationScore == expected
