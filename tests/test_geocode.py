"""
GEOCODING_PLAN §4: the offline `geocode_flat_addresses` tool.
OneMap is mocked with `responses`; these tests never call the real API and never really sleep.
"""
import csv
import json
from io import StringIO
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from django.core.management import call_command

from backend.core.integrations import onemap
from backend.core.integrations.onemap import OneMapSearchGateway
from backend.core.models import ResaleFlat, Town
from backend.core.management.commands import geocode_flat_addresses as geo
from tests.conftest import build_flat

SEARCH_URL = "https://www.onemap.gov.sg" + onemap.SEARCH_PATH
AMK = (1.3700, 103.8490)  # Ang Mo Kio town centroid in these tests
NEAR_AMK = (1.3690, 103.8480)


def hit(blk, road, lat=NEAR_AMK[0], lng=NEAR_AMK[1], postal="560406"):
    return {"BLK_NO": blk, "ROAD_NAME": road, "POSTAL": postal, "LATITUDE": str(lat), "LONGITUDE": str(lng),
            "BUILDING": "NIL", "SEARCHVAL": f"{blk} {road}"}


class Answers(list):
    """Successive answers to one query: HTTP status codes, then a results list (the last one repeats)."""


class FakeOneMap:
    """Answers searches from {searchVal: results | Answers}; unknown queries find nothing."""

    def __init__(self, table):
        self.table = table
        self.queries = []

    def __call__(self, request):
        query = parse_qs(urlparse(request.url).query)["searchVal"][0]
        self.queries.append(query)
        answer = self.table.get(query, [])
        if isinstance(answer, Answers):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, int):
            return answer, {}, "{}"
        return 200, {}, json.dumps({"found": len(answer), "totalNumPages": 1, "pageNum": 1, "results": answer})


@pytest.fixture
def onemap_mock():
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        def install(table):
            fake = FakeOneMap(table)
            rsps.add_callback(responses.GET, SEARCH_URL, callback=fake)
            return fake
        yield install


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(geo.time, "sleep", calls.append)
    return calls


@pytest.fixture
def flats(db):
    Town.objects.create(name="ANG MO KIO", centroid_lat=AMK[0], centroid_lng=AMK[1])

    def _add(*addresses, town="ANG MO KIO"):
        for block, street in addresses:
            build_flat(block=block, street_name=street, town=town).save()
    return _add


def run(tmp_path, *args):
    out = StringIO()
    call_command("geocode_flat_addresses", "--out", str(tmp_path / "coords.csv"), *args, stdout=out, stderr=out)
    return out.getvalue()


def read(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def outputs(tmp_path):
    return read(tmp_path / "coords.csv"), read(tmp_path / "coords_unmatched.csv")


# --- Gateway and helpers -----------------------------------------------------------------

def test_search_addresses_returns_raw_results(onemap_mock):
    onemap_mock({"406 ANG MO KIO AVE 10": [hit("406", "ANG MO KIO AVENUE 10")]})
    gateway = OneMapSearchGateway()
    assert gateway.search_addresses("406 ANG MO KIO AVE 10")[0]["BLK_NO"] == "406"
    assert gateway.search_addresses("nothing here") == []


def test_expand_street():
    assert geo.expand_street("C'WEALTH AVE") == "COMMONWEALTH AVENUE"
    assert geo.expand_street("BT BATOK ST 21") == "BUKIT BATOK STREET 21"
    assert geo.expand_street("ST. GEORGE'S RD") == "SAINT GEORGE'S ROAD"
    assert geo.expand_street("STIRLING RD") == "STIRLING ROAD"  # whole words only


# --- Matching ----------------------------------------------------------------------------

def test_exact_match_on_first_query(tmp_path, flats, onemap_mock):
    flats(("406", "ANG MO KIO AVE 10"))
    fake = onemap_mock({"406 ANG MO KIO AVE 10": [hit("406", "ANG MO KIO AVENUE 10")]})
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert fake.queries == ["406 ANG MO KIO AVE 10"]
    assert unmatched == []
    assert matched == [{"block": "406", "street_name": "ANG MO KIO AVE 10", "latitude": "1.369",
                        "longitude": "103.848", "postal": "560406", "onemap_road_name": "ANG MO KIO AVENUE 10",
                        "match_method": "exact", "query": "406 ANG MO KIO AVE 10"}]


def test_raw_miss_then_expanded_query_matches(tmp_path, flats, onemap_mock):
    flats(("10", "C'WEALTH AVE"))
    fake = onemap_mock({"10 COMMONWEALTH AVENUE": [hit("10", "COMMONWEALTH AVENUE")]})
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert fake.queries == ["10 C'WEALTH AVE", "10 COMMONWEALTH AVENUE"]
    assert unmatched == []
    assert matched[0]["match_method"] == "expanded"
    assert matched[0]["query"] == "10 COMMONWEALTH AVENUE"


def test_right_road_wrong_block_is_rejected(tmp_path, flats, onemap_mock):
    flats(("406", "ANG MO KIO AVE 10"))
    onemap_mock({"406 ANG MO KIO AVE 10": [hit("408", "ANG MO KIO AVENUE 10")],
                 "406 ANG MO KIO AVENUE 10": [hit("4066", "ANG MO KIO AVENUE 10")]})
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert matched == []
    assert unmatched == [{"block": "406", "street_name": "ANG MO KIO AVE 10", "reason": "block_mismatch",
                          "candidates": "4066 ANG MO KIO AVENUE 10 (560406)"}]


def test_fuzzy_match_with_one_close_candidate(tmp_path, flats, onemap_mock):
    flats(("6", "UPP BOON KENG RD"))
    onemap_mock({"6 UPP BOON KENG RD": [hit("6", "UPPER BOON KEANG ROAD"), hit("6", "JALAN BESAR")]})
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert unmatched == []
    assert matched[0]["match_method"] == "fuzzy"
    assert matched[0]["onemap_road_name"] == "UPPER BOON KEANG ROAD"


def test_two_close_candidates_are_ambiguous(tmp_path, flats, onemap_mock):
    flats(("6", "UPP BOON KENG RD"))
    both = [hit("6", "UPPER BOON KEANG ROAD"), hit("6", "UPPER BOON KENG ROADS")]
    onemap_mock({"6 UPP BOON KENG RD": both, "6 UPPER BOON KENG ROAD": both})
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert matched == []
    assert unmatched[0]["reason"] == "ambiguous"
    assert unmatched[0]["candidates"] == "6 UPPER BOON KEANG ROAD (560406) | 6 UPPER BOON KENG ROADS (560406)"


def test_no_results_is_unmatched(tmp_path, flats, onemap_mock):
    flats(("1", "NOWHERE RD"))
    fake = onemap_mock({})
    run(tmp_path)
    assert fake.queries == ["1 NOWHERE RD", "1 NOWHERE ROAD"]
    assert outputs(tmp_path)[1][0]["reason"] == "no_results"


def test_out_of_bounds_rejected_and_far_from_town_flagged(tmp_path, flats, onemap_mock):
    flats(("1", "FAR RD"), ("2", "OUT RD"))
    onemap_mock({"1 FAR RD": [hit("1", "FAR ROAD", 1.2800, 103.8500)],    # ~10 km south of AMK
                 "2 OUT RD": [hit("2", "OUT ROAD", 29000.0, 37000.0)]})   # SVY21 metres, not degrees
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert [(r["block"], r["match_method"]) for r in matched] == [("1", "exact+far_from_town")]
    assert [(r["block"], r["reason"]) for r in unmatched] == [("2", "out_of_bounds")]


# --- Pacing and failures -----------------------------------------------------------------

def test_429_backs_off_then_halves_the_rate(tmp_path, flats, onemap_mock, sleeps):
    flats(("406", "ANG MO KIO AVE 10"), ("407", "ANG MO KIO AVE 10"))
    onemap_mock({"406 ANG MO KIO AVE 10": Answers([429, [hit("406", "ANG MO KIO AVENUE 10")]]),
                 "407 ANG MO KIO AVE 10": [hit("407", "ANG MO KIO AVENUE 10")]})
    output = run(tmp_path, "--rate", "1.0")
    matched, _ = outputs(tmp_path)
    assert [r["block"] for r in matched] == ["406", "407"]
    assert 10 in sleeps                                # first backoff step
    assert "slowing to 0.5 requests/s" in output
    assert sleeps[-1] == pytest.approx(2.0, abs=0.1)   # the next request is paced at 0.5/s
    assert "1 rate-limited" in output


def test_rate_never_drops_below_minimum(tmp_path, flats, onemap_mock):
    flats(("406", "ANG MO KIO AVE 10"))
    onemap_mock({"406 ANG MO KIO AVE 10": Answers([429, [hit("406", "ANG MO KIO AVENUE 10")]])})
    assert "slowing to 0.25 requests/s" in run(tmp_path, "--rate", "0.3")


def test_stops_cleanly_after_five_failed_retries(tmp_path, flats, onemap_mock, sleeps):
    flats(("406", "ANG MO KIO AVE 10"), ("407", "ANG MO KIO AVE 10"))
    fake = onemap_mock({"406 ANG MO KIO AVE 10": Answers([429])})
    output = run(tmp_path)
    assert len(fake.queries) == 6                      # first try + 5 retries, then stop
    assert [s for s in sleeps if s >= 10] == [10, 30, 60, 120, 120]
    assert "resume" in output
    assert outputs(tmp_path) == ([], [])


# --- Resuming ----------------------------------------------------------------------------

def test_resume_skips_pairs_in_either_file(tmp_path, flats, onemap_mock):
    flats(("1", "A RD"), ("2", "B RD"), ("3", "C RD"))
    (tmp_path / "coords.csv").write_text(
        "block,street_name,latitude,longitude\n1,A RD,1.369,103.848", encoding="utf-8")  # no final newline
    (tmp_path / "coords_unmatched.csv").write_text(
        "block,street_name,reason,candidates\n2,B RD,no_results,\n", encoding="utf-8")
    fake = onemap_mock({"3 C RD": [hit("3", "C ROAD")]})
    run(tmp_path)
    matched, unmatched = outputs(tmp_path)
    assert fake.queries == ["3 C RD"]
    assert [r["block"] for r in matched] == ["1", "3"]
    assert [r["block"] for r in unmatched] == ["2"]


def test_limit(tmp_path, flats, onemap_mock):
    flats(("1", "A RD"), ("2", "B RD"))
    fake = onemap_mock({"1 A RD": [hit("1", "A ROAD")], "2 B RD": [hit("2", "B ROAD")]})
    run(tmp_path, "--limit", "1")
    assert fake.queries == ["1 A RD"]


def test_retry_unmatched_moves_a_success_to_the_output(tmp_path, flats, onemap_mock):
    flats(("1", "A RD"), ("2", "B RD"))
    (tmp_path / "coords_unmatched.csv").write_text(
        "block,street_name,reason,candidates\n1,A RD,no_results,\n2,B RD,no_results,\n", encoding="utf-8")
    fake = onemap_mock({"1 A RD": [hit("1", "A ROAD")]})
    run(tmp_path, "--retry-unmatched")
    matched, unmatched = outputs(tmp_path)
    assert fake.queries == ["1 A RD", "2 B RD", "2 B ROAD"]
    assert [r["block"] for r in matched] == ["1"]
    assert [r["block"] for r in unmatched] == ["2"]


# --- Hand-off to import_flat_coordinates -------------------------------------------------

def test_output_loads_with_import_flat_coordinates(tmp_path, flats, onemap_mock):
    flats(("406", "ANG MO KIO AVE 10"))
    ResaleFlat.objects.update(latitude=AMK[0], longitude=AMK[1], coords_approximate=True)
    onemap_mock({"406 ANG MO KIO AVE 10": [hit("406", "ANG MO KIO AVENUE 10")]})
    run(tmp_path)
    assert ResaleFlat.objects.get().coords_approximate is True  # the tool never touches the database
    call_command("import_flat_coordinates", str(tmp_path / "coords.csv"), stdout=StringIO())
    flat = ResaleFlat.objects.get()
    assert (flat.latitude, flat.longitude, flat.coords_approximate) == (NEAR_AMK[0], NEAR_AMK[1], False)
