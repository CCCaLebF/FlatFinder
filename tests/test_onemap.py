"""
Phase 7: UC-04 Calculate Walking Distance, UC-07 Search via Search Bar, UC-06 Handle API Failure.
OneMap is mocked with `responses`; these tests never call the real API.
"""
import time
from pathlib import Path

import pytest
import requests
import responses
from django.urls import reverse

from backend.core.integrations import onemap
from backend.core.integrations.onemap import (
    OneMapError, OneMapRoutingGateway, OneMapSearchGateway, OneMapTokenProvider,
)
from backend.core.services.distance import WalkingDistance
from backend.core.services.errors import ErrorHandler
from backend.core.services.search import SearchController
from backend.core.models import SearchQuery

BASE = "https://www.onemap.gov.sg"
TOKEN_URL = BASE + onemap.TOKEN_PATH
SEARCH_URL = BASE + onemap.SEARCH_PATH
ROUTE_URL = BASE + onemap.ROUTE_PATH
STATIC_JS = Path(__file__).resolve().parent.parent / "frontend" / "static" / "js"

SEARCH_HIT = {"found": 1, "totalNumPages": 1, "pageNum": 1, "results": [{
    "SEARCHVAL": "BISHAN MRT STATION (NS17 / CC15)", "BLK_NO": "200", "ROAD_NAME": "BISHAN ROAD",
    "BUILDING": "BISHAN MRT STATION (NS17 / CC15)", "ADDRESS": "200 BISHAN ROAD SINGAPORE 579827",
    "POSTAL": "579827", "LATITUDE": "1.35100", "LONGITUDE": "103.84850", "X": "29000", "Y": "37000"}]}
ROUTE_OK = {"status": 0, "status_message": "Found route", "route_summary": {"total_distance": 1514, "total_time": 1090}}


@pytest.fixture(autouse=True)
def onemap_settings(settings):
    settings.ONEMAP_EMAIL = "team@example.com"
    settings.ONEMAP_PASSWORD = "not-a-real-password"
    onemap.token_provider.invalidate()  # no token carried between tests
    yield
    onemap.token_provider.invalidate()


def add_token(rsps, token="tok-1", valid_for=3 * 86400):
    rsps.add(responses.POST, TOKEN_URL, json={"access_token": token, "expiry_timestamp": str(int(time.time() + valid_for))})


# --- Token helper ----------------------------------------------------------------------

@responses.activate
def test_token_is_cached_and_sent_with_credentials():
    add_token(responses)
    provider = OneMapTokenProvider()
    assert provider.get_token() == "tok-1"
    assert provider.get_token() == "tok-1"
    assert len(responses.calls) == 1  # cached
    assert responses.calls[0].request.body == b'{"email": "team@example.com", "password": "not-a-real-password"}'


@responses.activate
def test_token_is_refreshed_before_it_expires():
    add_token(responses, "old", valid_for=600)   # inside the 1-hour refresh margin
    add_token(responses, "new")
    provider = OneMapTokenProvider()
    assert provider.get_token() == "old"
    assert provider.get_token() == "new"


def test_missing_credentials(settings):
    settings.ONEMAP_EMAIL = ""
    with pytest.raises(OneMapError) as info:
        OneMapTokenProvider().get_token()
    assert info.value.code == "no-credentials"


@responses.activate
def test_token_endpoint_401():
    responses.add(responses.POST, TOKEN_URL, json={"error": "bad credentials"}, status=401)
    with pytest.raises(OneMapError) as info:
        OneMapTokenProvider().get_token()
    assert info.value.code == 401


# --- Search gateway (UC-07) --------------------------------------------------------------

@responses.activate
def test_geocode_success_needs_no_token():
    responses.add(responses.GET, SEARCH_URL, json=SEARCH_HIT)
    assert OneMapSearchGateway().geocode("Bishan MRT") == (1.351, 103.8485, "BISHAN MRT STATION (NS17 / CC15)")
    request = responses.calls[0].request
    assert "searchVal=Bishan+MRT" in request.url and "returnGeom=Y" in request.url
    assert "Authorization" not in request.headers


@responses.activate
def test_geocode_no_match():
    responses.add(responses.GET, SEARCH_URL, json={"found": 0, "totalNumPages": 0, "pageNum": 1, "results": []})
    assert OneMapSearchGateway().geocode("zzqqxx") is None


@responses.activate
def test_geocode_falls_back_to_address_when_building_is_nil():
    hit = {**SEARCH_HIT, "results": [{**SEARCH_HIT["results"][0], "BUILDING": "NIL"}]}
    responses.add(responses.GET, SEARCH_URL, json=hit)
    assert OneMapSearchGateway().geocode("579827")[2] == "200 BISHAN ROAD SINGAPORE 579827"


@responses.activate
@pytest.mark.parametrize("failure, code", [
    (requests.Timeout(), "timeout"),
    (requests.ConnectionError(), "network"),
])
def test_geocode_timeout_and_network_errors(failure, code):
    responses.add(responses.GET, SEARCH_URL, body=failure)
    with pytest.raises(OneMapError) as info:
        OneMapSearchGateway().geocode("Bishan")
    assert info.value.code == code


@responses.activate
def test_geocode_server_error():
    responses.add(responses.GET, SEARCH_URL, status=503)
    with pytest.raises(OneMapError) as info:
        OneMapSearchGateway().geocode("Bishan")
    assert info.value.code == 503


def test_gateways_use_a_5_second_timeout(settings, monkeypatch):
    seen = {}

    def fake_request(method, url, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise requests.Timeout()
    monkeypatch.setattr(onemap.requests, "request", fake_request)
    with pytest.raises(OneMapError):
        OneMapSearchGateway().geocode("x")
    assert seen["timeout"] == settings.ONEMAP_TIMEOUT_S == 5


# --- Routing gateway (UC-04) ---------------------------------------------------------------

@responses.activate
def test_walking_route_success_sends_token():
    add_token(responses)
    responses.add(responses.GET, ROUTE_URL, json=ROUTE_OK)
    route = OneMapRoutingGateway(OneMapTokenProvider()).walking_route((1.38, 103.84), (1.373, 103.8495))
    assert route == {"metres": 1514.0, "seconds": 1090.0}
    request = responses.calls[1].request
    assert request.headers["Authorization"] == "tok-1"
    assert "routeType=walk" in request.url and "start=1.38%2C103.84" in request.url


@responses.activate
def test_walking_route_401_refreshes_the_token_once():
    add_token(responses, "stale")
    responses.add(responses.GET, ROUTE_URL, json={"message": "unauthorised"}, status=401)
    add_token(responses, "fresh")
    responses.add(responses.GET, ROUTE_URL, json=ROUTE_OK)
    gateway = OneMapRoutingGateway(OneMapTokenProvider())
    assert gateway.walking_distance_m((1.38, 103.84), (1.373, 103.8495)) == 1514.0
    assert responses.calls[3].request.headers["Authorization"] == "fresh"


@responses.activate
def test_walking_route_401_twice_is_an_error():
    add_token(responses)
    responses.add(responses.GET, ROUTE_URL, status=401)
    with pytest.raises(OneMapError) as info:
        OneMapRoutingGateway(OneMapTokenProvider()).walking_route((1.38, 103.84), (1.37, 103.85))
    assert info.value.code == 401


@responses.activate
def test_walking_route_timeout():
    add_token(responses)
    responses.add(responses.GET, ROUTE_URL, body=requests.Timeout())
    with pytest.raises(OneMapError) as info:
        OneMapRoutingGateway(OneMapTokenProvider()).walking_route((1.38, 103.84), (1.37, 103.85))
    assert info.value.code == "timeout"


@responses.activate
def test_walking_route_without_summary_is_an_error():
    add_token(responses)
    responses.add(responses.GET, ROUTE_URL, json={"status": 404, "status_message": "No route"})
    with pytest.raises(OneMapError) as info:
        OneMapRoutingGateway(OneMapTokenProvider()).walking_route((1.38, 103.84), (1.37, 103.85))
    assert info.value.code == "no-route"


def test_walking_distance_strategy_uses_the_gateway():
    class FakeGateway:
        def walking_distance_m(self, origin, target):
            return 640.0

        def walking_route(self, origin, target):
            return {"metres": 640.0, "seconds": 480.0}
    strategy = WalkingDistance(FakeGateway())
    assert strategy.distance_m((1, 2), (3, 4)) == 640.0 and strategy.route((1, 2), (3, 4))["seconds"] == 480.0


# --- ErrorHandler (UC-06) ----------------------------------------------------------------------

def test_error_handler_logs_and_returns_502(caplog):
    with caplog.at_level("WARNING", logger="core.onemap"):
        response = ErrorHandler().to_response(OneMapError("/api/public/routingsvc/route", 503))
    assert response.status_code == 502
    assert response.content == b'{"error": "OneMap service currently unavailable. Please try again later."}'
    assert "endpoint=/api/public/routingsvc/route" in caplog.text and "code=503" in caplog.text


# --- Walking-distance endpoint ----------------------------------------------------------------------

@pytest.fixture
def flat(make_flat):
    return make_flat(latitude=1.3800, longitude=103.8421)


def walk_url(flat_id, lat=1.3730, lng=103.8495):
    return f"{reverse('core:api_walking_distance')}?flat_id={flat_id}&lat={lat}&lng={lng}"


@pytest.mark.django_db
@responses.activate
def test_walking_distance_api(client, flat):
    from django.core.cache import cache
    cache.clear()
    add_token(responses)
    responses.add(responses.GET, ROUTE_URL, json=ROUTE_OK)
    first = client.get(walk_url(flat.id))
    assert first.status_code == 200
    assert first.json() == {"metres": 1514, "minutes": 18, "fromTownCentre": False}
    assert client.get(walk_url(flat.id)).json()["metres"] == 1514
    assert len([c for c in responses.calls if "routingsvc" in c.request.url]) == 1  # second answer cached
    assert "tok-1" not in first.content.decode()  # the token never reaches the browser


@pytest.mark.django_db
@responses.activate
def test_walking_distance_api_onemap_failure_is_502(client, flat):
    from django.core.cache import cache
    cache.clear()
    add_token(responses)
    responses.add(responses.GET, ROUTE_URL, body=requests.Timeout())
    response = client.get(walk_url(flat.id))
    assert response.status_code == 502
    assert response.json() == {"error": ErrorHandler.USER_MESSAGE}


@pytest.mark.django_db
def test_walking_distance_api_validation(client, flat, make_flat):
    assert client.get(reverse("core:api_walking_distance")).status_code == 400
    assert client.get(walk_url(flat.id, lat="abc")).status_code == 400
    assert client.get(walk_url(999999)).status_code == 404
    assert client.get(walk_url(make_flat().id)).status_code == 400          # flat has no location
    far = client.get(walk_url(flat.id, lat=1.30, lng=103.80))                # ~10 km away: not proxied
    assert far.status_code == 400 and "too far" in far.json()["error"]


# --- Search bar (UC-07) ------------------------------------------------------------------------------

def test_set_proximity_anchor():
    class Gateway:
        def __init__(self, found):
            self.found = found

        def geocode(self, text):
            return self.found
    query = SearchQuery()
    assert SearchController().set_proximity_anchor(query, " Bishan ", Gateway((1.35, 103.85, "Bishan"))) is True
    assert (query.anchorLat, query.anchorLabel, query.anchorWeight) == (1.35, "Bishan", 5)
    assert SearchController().set_proximity_anchor(SearchQuery(), "x", Gateway(None)) is False


@pytest.mark.django_db
@responses.activate
def test_search_bar_sets_anchor_and_redirects(client, make_flat):
    responses.add(responses.GET, SEARCH_URL, json=SEARCH_HIT)
    make_flat(latitude=1.352, longitude=103.849)
    response = client.get(reverse("core:results"), {"q": "Bishan MRT", "w_bus_stop": 5, "page": 3, "view": "list"})
    assert response.status_code == 302
    target = response.url
    assert "q=" not in target and "page=" not in target
    assert "anchor_lat=1.351000" in target and "anchor_lng=103.848500" in target
    assert "w_anchor=5" in target and "w_bus_stop=5" in target

    page = client.get(target)
    content = page.content.decode()
    assert page.context["query"].hasAnchor
    assert "Ranking includes distance to" in content and "Bishan MRT Station (NS17 / CC15)" in content
    assert 'name="w_anchor"' in content  # its weight slider appears once set (decision 4)
    from backend.core.services.distance import StraightLineDistance
    metres = StraightLineDistance().distance_m((1.352, 103.849), (1.351, 103.8485))
    assert page.context["cards"][0]["fit"].anchorScore == pytest.approx(1 - metres / 3000, abs=0.001)


@pytest.mark.django_db
@responses.activate
def test_search_bar_no_match_message(client, make_flat):
    responses.add(responses.GET, SEARCH_URL, json={"found": 0, "totalNumPages": 0, "pageNum": 1, "results": []})
    make_flat()
    response = client.get(reverse("core:results"), {"q": "zzqqxx", "w_bus_stop": 5}, follow=True)
    content = response.content.decode()
    assert response.redirect_chain[0][1] == 302
    assert "No matching location found" in content and "zzqqxx" in content
    assert not response.context["query"].hasAnchor
    assert "data-dismiss" in content


@pytest.mark.django_db
@responses.activate
def test_search_bar_onemap_failure_shows_banner_and_results(client, make_flat, caplog):
    responses.add(responses.GET, SEARCH_URL, body=requests.ConnectionError())
    make_flat(block="1A")
    with caplog.at_level("WARNING", logger="core.onemap"):
        response = client.get(reverse("core:results"), {"q": "Bishan"}, follow=True)
    content = response.content.decode()
    assert "OneMap service currently unavailable" in content
    assert 'data-error-banner role="alert"' in content
    assert "Blk 1A" in content  # the rest of the page keeps working (UC-06)
    assert "code=network" in caplog.text


@pytest.mark.django_db
def test_clear_anchor_chip(client, make_flat):
    make_flat()
    content = client.get(reverse("core:results"), {
        "anchor_lat": 1.35, "anchor_lng": 103.85, "anchor_label": "Bishan", "w_anchor": 7}).content.decode()
    chip = content[content.index("data-anchor-chip"):]
    href = chip[chip.index('href="') + 6:chip.index('"', chip.index('href="') + 6)]
    assert "anchor_lat" not in href and "w_anchor" not in href


@pytest.mark.django_db
def test_no_banner_when_nothing_failed(client):
    content = client.get(reverse("core:start")).content.decode()
    assert 'class="hidden flex items-start' in content


# --- Client-side contracts --------------------------------------------------------------------------

def test_map_js_onemap_contracts():
    source = (STATIC_JS / "map.js").read_text(encoding="utf-8")
    assert "/api/walking-distance?" in source                # UC-04
    assert 'tiles.on("tileerror"' in source                  # UC-06 for base-map tiles
    assert "FF.MapState.lastView()" in source                # UC-13 restore
    assert "anchor_lat" in source                            # UC-07 anchor pin
    errors = (STATIC_JS / "errors.js").read_text(encoding="utf-8")
    assert "showError" in errors and "textContent" in errors
