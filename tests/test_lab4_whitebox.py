"""
Lab 4 §3.2.2: white box (basis path) tests of SearchController.filter_flats() and
parse_weights(). Paths, CFGs and oracles are in docs/testing/Lab4_Test_Design.md §2-3.
"""
import pytest
from django.http import QueryDict

from backend.core.models import CATEGORIES, SearchQuery
from backend.core.services.compare import parse_weights
from backend.core.services.search import SearchController

controller = SearchController()

# --- §2 filter_flats: CC = 5, baseline sets every criterion, each path flips one decision -------

BASELINE = {"minBudget": 350_000, "maxBudget": 700_000, "flatTypes": ["4 ROOM"], "minRemainingLease": 80}


@pytest.mark.django_db
@pytest.mark.parametrize("test_id, blank, expected", [
    ("WB-F1", None, "A"),                    # 54,55,56,57,58,59,60,61,62,63
    ("WB-F2", "minBudget", "AB"),            # 54,55,57,58,59,60,61,62,63
    ("WB-F3", "maxBudget", "AC"),            # 54,55,56,57,59,60,61,62,63
    ("WB-F4", "flatTypes", "AD"),            # 54,55,56,57,58,59,61,62,63
    ("WB-F5", "minRemainingLease", "AE"),    # 54,55,56,57,58,59,60,61,63
])
def test_filter_flats_basis_paths(lab4_flats, test_id, blank, expected):
    criteria = dict(BASELINE)
    if blank:
        criteria[blank] = [] if blank == "flatTypes" else None
    ids = set(controller.filter_flats(SearchQuery(**criteria)).values_list("id", flat=True))
    assert ids == {lab4_flats[name].id for name in expected}


# --- §3 parse_weights: CC = 5; path 91,92,101 is infeasible (WEIGHT_PARAMS is never empty) ------

DEFAULTS = {"price": 5, "lease": 5, "area": 0, **{c.key: 5 for c in CATEGORIES}}


@pytest.mark.parametrize("test_id, query_string, changed", [
    ("WB-P1", "cw_price=8", {"price": 8}),         # 91,92,93,95,97,100,92,101 (baseline)
    ("WB-P2", "cw_price_off=on", {"price": 0}),    # 91,92,93,94,92,101
    ("WB-P3", "", {}),                             # 91,92,93,95,92,101
    ("WB-P4", "cw_price=abc", {}),                 # 91,92,93,95,97,99,92,101
])
def test_parse_weights_basis_paths(test_id, query_string, changed):
    assert parse_weights(QueryDict(query_string), None) == {**DEFAULTS, **changed}
