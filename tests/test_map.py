"""Phase 6: UC-03 Display Interactive Map, UC-12 Toggle Amenity Layers, UC-13 MapState."""
from decimal import Decimal
from pathlib import Path

import pytest
from django.conf import settings
from django.urls import reverse

from backend.core.services.map import MapController
from backend.core.services.search import SearchController
from backend.core.models import BusStop, SearchQuery, Town

JSON = {"HTTP_ACCEPT": "application/json"}
STATIC_JS = Path(__file__).resolve().parent.parent / "frontend" / "static" / "js"
VIEW = {"south": 1.30, "west": 103.80, "north": 1.40, "east": 103.90}


@pytest.fixture
def towns(db):
    Town.objects.create(name="ANG MO KIO", centroid_lat=1.38, centroid_lng=103.84)
    Town.objects.create(name="BEDOK", centroid_lat=1.33, centroid_lng=103.93)


# --- MapController ---------------------------------------------------------------------

@pytest.mark.django_db
def test_area_counts_follow_the_filters(towns, make_flat):
    for _ in range(3):
        make_flat(town="ANG MO KIO", flat_type="4 ROOM")
    make_flat(town="ANG MO KIO", flat_type="3 ROOM")
    make_flat(town="BEDOK", flat_type="4 ROOM")
    make_flat(town="ATLANTIS", flat_type="4 ROOM")  # no centroid: no marker to put it on

    areas = MapController().get_area_counts(SearchQuery())
    assert areas == [{"town": "ANG MO KIO", "lat": 1.38, "lng": 103.84, "count": 4},
                     {"town": "BEDOK", "lat": 1.33, "lng": 103.93, "count": 1}]
    four_room = MapController().get_area_counts(SearchQuery(flatTypes=["4 ROOM"]))
    assert [(a["town"], a["count"]) for a in four_room] == [("ANG MO KIO", 3), ("BEDOK", 1)]


@pytest.mark.django_db
def test_pins_in_view_group_flats_at_the_same_point(make_flat):
    shared = dict(latitude=1.35, longitude=103.85)
    best = make_flat(resale_price=Decimal("300000"), remaining_lease=95, block="1", **shared)
    make_flat(resale_price=Decimal("600000"), remaining_lease=60, block="2", **shared)
    make_flat(resale_price=Decimal("450000"), remaining_lease=80, block="3", latitude=1.36, longitude=103.86)
    make_flat(latitude=1.45, longitude=103.85)  # outside the view
    make_flat()  # no coordinates: never a pin

    pins = MapController().get_pins_in_view((1.30, 103.80, 1.40, 103.90), SearchQuery())
    assert pins["total"] == 3 and not pins["truncated"]
    first = pins["locations"][0]
    assert (first["lat"], first["lng"], first["count"]) == (1.35, 103.85, 2)
    assert first["price"] == 300000.0  # the best flat's price, for a price tag
    assert first["id"] == best.id      # the pin opens the best flat's (block-level) details
    assert "flats" not in first        # the popup list is fetched when the pin opens
    assert [loc["count"] for loc in pins["locations"]] == [2, 1]

    popup = MapController().get_flats_at_location(1.35, 103.85, SearchQuery())
    assert popup["count"] == 2 and popup["flats"][0]["id"] == best.id  # best Fit Score first
    assert popup["flats"][0]["block"] == "1" and popup["approximate"] is False


@pytest.mark.django_db
def test_pin_scores_match_the_results_list(make_flat):
    make_flat(resale_price=Decimal("300000"), latitude=1.35, longitude=103.85,
              proximity={"nearest_mrt_station_m": 200})
    make_flat(resale_price=Decimal("700000"), latitude=1.50, longitude=103.95)  # out of view, sets the price range
    query = SearchQuery(mrtStationWeight=7)
    controller = SearchController()
    result = controller.rank_flats(controller.filter_flats(query), query)
    pin = MapController().get_pins_in_view((1.30, 103.80, 1.40, 103.90), query)["locations"][0]
    popup_flat = MapController().get_flats_at_location(1.35, 103.85, query)["flats"][0]
    assert pin["fit"] == popup_flat["fit"] == result.fitScores[popup_flat["id"]].total


@pytest.mark.django_db
def test_pin_limit_marks_truncation(make_flat):
    for i in range(5):
        make_flat(latitude=1.31 + i / 100, longitude=103.85)
    pins = MapController().get_pins_in_view((1.30, 103.80, 1.40, 103.90), SearchQuery(), limit=3)
    assert len(pins["locations"]) == 3 and pins["truncated"] and pins["total"] == 5


# --- JSON endpoints -----------------------------------------------------------------------

@pytest.mark.django_db
def test_area_counts_api(client, towns, make_flat):
    make_flat(town="BEDOK", resale_price=Decimal("400000"))
    make_flat(town="BEDOK", resale_price=Decimal("900000"))
    data = client.get(reverse("core:api_area_counts"), {"max_budget": 500000}, **JSON).json()
    assert data == {"areas": [{"town": "BEDOK", "lat": 1.33, "lng": 103.93, "count": 1}], "total": 1}


@pytest.mark.django_db
def test_in_bounds_api_and_fit_only_with_a_search(client, make_flat):
    make_flat(latitude=1.35, longitude=103.85, coords_approximate=True)
    no_search = client.get(reverse("core:api_flats_in_bounds"), VIEW).json()
    assert no_search["locations"][0]["approximate"] is True
    assert no_search["locations"][0]["fit"] is None
    with_search = client.get(reverse("core:api_flats_in_bounds"), {**VIEW, "w_bus_stop": 5}).json()
    assert with_search["locations"][0]["fit"] is not None


@pytest.mark.django_db
def test_at_location_api(client, make_flat):
    flat = make_flat(latitude=1.35, longitude=103.85, coords_approximate=True)
    make_flat(latitude=1.36, longitude=103.85)  # another pin
    data = client.get(reverse("core:api_flats_at_location"), {"lat": 1.35, "lng": 103.85, "w_bus_stop": 5}).json()
    assert data["count"] == 1 and data["approximate"] is True
    assert [f["id"] for f in data["flats"]] == [flat.id] and data["flats"][0]["fit"] is not None
    no_search = client.get(reverse("core:api_flats_at_location"), {"lat": 1.35, "lng": 103.85}).json()
    assert no_search["flats"][0]["fit"] is None
    assert client.get(reverse("core:api_flats_at_location"), {"lat": "x"}).status_code == 400


@pytest.mark.django_db
def test_in_bounds_api_is_compressed(client, make_flat):
    for i in range(30):
        make_flat(latitude=1.31 + i / 1000, longitude=103.85)
    response = client.get(reverse("core:api_flats_in_bounds"), VIEW, HTTP_ACCEPT_ENCODING="gzip")
    assert response["Content-Encoding"] == "gzip"


@pytest.mark.django_db
@pytest.mark.parametrize("params", [
    {},  # no bounds
    {"south": "x", "west": 103.8, "north": 1.4, "east": 103.9},
    {"south": 1.4, "west": 103.8, "north": 1.3, "east": 103.9},  # south > north
    {**VIEW, "w_bus_stop": 40},  # invalid search
])
def test_in_bounds_api_rejects_bad_input(client, params):
    response = client.get(reverse("core:api_flats_in_bounds"), params)
    assert response.status_code == 400 and "error" in response.json()


@pytest.mark.django_db
def test_amenities_api(client, make_flat):
    flat = make_flat(latitude=1.37, longitude=103.85)
    BusStop.objects.create(name="Bus Stop 1", stop_code="1", latitude=1.3710, longitude=103.85)
    data = client.get(reverse("core:api_flat_amenities", args=[flat.id])).json()
    assert data["flat"]["lat"] == 1.37 and data["radiusM"] == 1000
    assert [c["key"] for c in data["categories"]] == [
        "bus_stop", "mrt_station", "child_care_centre", "hawker_centre", "chas_clinic"]
    bus = data["categories"][0]["items"][0]
    assert bus["name"] == "Bus Stop 1" and bus["distanceM"] == 111

    no_coords = client.get(reverse("core:api_flat_amenities", args=[make_flat().id])).json()
    assert no_coords["flat"]["lat"] is None and all(not c["items"] for c in no_coords["categories"])
    assert client.get(reverse("core:api_flat_amenities", args=[999999])).status_code == 404


@pytest.mark.django_db
def test_bookmarks_api_lists_saved_flats_with_a_location(client, make_flat):
    located, unlocated = make_flat(latitude=1.37, longitude=103.85), make_flat()
    for flat in (located, unlocated):
        client.post(reverse("core:api_toggle_bookmark", args=[flat.id]), **JSON)
    data = client.get(reverse("core:api_bookmarks")).json()
    assert data["count"] == 2
    assert [f["id"] for f in data["flats"]] == [located.id]


@pytest.mark.django_db
def test_map_endpoints_are_get_only(client, make_flat):
    flat = make_flat()
    for url in (reverse("core:api_area_counts"), reverse("core:api_flats_in_bounds"),
                reverse("core:api_flat_amenities", args=[flat.id]), reverse("core:api_bookmarks")):
        assert client.post(url).status_code == 405


# --- Pages in Map View -----------------------------------------------------------------------

@pytest.mark.django_db
def test_start_map_view(client):
    content = client.get(reverse("core:start"), {"view": "map"}).content.decode()
    assert 'id="map"' in content and 'data-map-mode="browse"' in content and 'data-origin="start"' in content
    assert "Find an HDB resale flat" not in content  # the intro panel is List View only
    assert 'data-map-capable="1"' in content


@pytest.mark.django_db
def test_results_map_view_has_side_list_and_map(client, make_flat):
    flat = make_flat(latitude=1.37, longitude=103.85)
    make_flat(block="9Z")  # another block, so two cards
    content = client.get(reverse("core:results"), {"view": "map", "w_bus_stop": 5}).content.decode()
    assert 'data-map-mode="browse"' in content and 'data-origin="results"' in content
    assert content.count("data-flat-card=") == 2
    assert 'data-show-on-map data-lat="1.370000"' in content
    assert "No location" in content
    assert 'name="sort"' in content  # sort control still there
    assert f"/flats/{flat.id}/?" in content and "view=map" in content  # single-flat cards open the flat details page


@pytest.mark.django_db
def test_results_map_view_with_no_matches_shows_no_results(client):
    content = client.get(reverse("core:results"), {"view": "map", "max_budget": 1}).content.decode()
    assert "No flats match your requirements" in content and 'id="map"' not in content


@pytest.mark.django_db
def test_details_map_view_has_layer_toggles(client, make_flat):
    flat = make_flat(latitude=1.37, longitude=103.85)
    content = client.get(reverse("core:flat_details", args=[flat.id]), {"view": "map", "from": "results"}).content.decode()
    assert 'data-map-mode="flat"' in content and f'data-flat-id="{flat.id}"' in content
    assert 'class="ff-map-layers' in content
    assert "Active map layers" not in content
    for key in ("bus_stop", "mrt_station", "child_care_centre", "hawker_centre", "chas_clinic"):
        assert f'data-layer-toggle="{key}"' in content
    assert "Fit Score" in content


@pytest.mark.django_db
def test_saved_map_view(client, make_flat):
    flat = make_flat(latitude=1.37, longitude=103.85)
    client.post(reverse("core:api_toggle_bookmark", args=[flat.id]), **JSON)
    content = client.get(reverse("core:saved"), {"view": "map"}).content.decode()
    assert 'data-map-mode="saved"' in content and "data-saved-item" in content
    assert f"/flats/{flat.id}/?from=saved&view=map" in content.replace("&amp;", "&")


@pytest.mark.django_db
def test_list_view_has_no_map(client, make_flat):
    make_flat()
    assert 'id="map"' not in client.get(reverse("core:results")).content.decode()
    assert 'id="map"' not in client.get(reverse("core:start")).content.decode()


@pytest.mark.django_db
def test_map_config_reaches_the_page(client):
    content = client.get(reverse("core:start")).content.decode()
    assert '"tileUrl": "https://www.onemap.gov.sg/maps/tiles/Default/{z}/{x}/{y}.png"' in content
    assert f'"pinMinZoom": {settings.MAP_PIN_MIN_ZOOM}' in content


# --- Client-side contracts (no JS test runner, so check the code says what it must) -----

def test_map_js_contracts():
    source = (STATIC_JS / "map.js").read_text(encoding="utf-8")
    assert "cfg.pinMinZoom" in source                                 # FR 2.1.1 / 2.1.2 switch
    assert "/api/flats/area-counts?" in source and "/api/flats/in-bounds?" in source
    assert "/api/bookmarks" in source                                  # UC-03.AC.1
    assert "map.removeLayer(layers[type])" in source                   # UC-12: hide without re-fetching
    assert "MapState.save" in source                                   # UC-13
    assert '"View details"' in source and "View each flat in this block" not in source
    assert "innerHTML" not in source                                   # server text is never parsed as HTML


def test_mapstate_js_handles_missing_storage():
    source = (STATIC_JS / "mapstate.js").read_text(encoding="utf-8")
    assert source.count("try {") >= 2 and "localStorage" in source
    for key in ("centre", "zoom", "visibleLayers", "viewMode"):
        assert key in source


# --- Collapsible side panels in Map View ------------------------------------------------------

@pytest.mark.django_db
def test_side_panels_are_collapsible_in_map_view_only(client, make_flat):
    flat = make_flat(latitude=1.37, longitude=103.85)
    map_pages = {
        "start": (reverse("core:start"), 1),            # filters
        "results": (reverse("core:results"), 2),        # filters + results list
        "saved": (reverse("core:saved"), 1),            # saved list
        "details": (reverse("core:flat_details", args=[flat.id]), 1),  # details panel
    }
    for name, (url, panels) in map_pages.items():
        assert client.get(url, {"view": "map"}).content.decode().count("data-side-panel") == panels, name
        assert "data-side-panel" not in client.get(url, {"view": "list"}).content.decode(), name


def test_panel_toggle_contracts():
    source = (STATIC_JS / "map.js").read_text(encoding="utf-8")
    assert "[data-side-panel]" in source and "panelsHidden" in source
    assert "map.invalidateSize()" in source                             # the map refits its new box
    state = (STATIC_JS / "mapstate.js").read_text(encoding="utf-8")
    assert "dataset.panelsHidden" in state                              # applied before paint


# --- Pins coloured by Fit Score -----------------------------------------------------------------

def test_fit_legend_rows_follow_the_bands():
    from backend.core.views.context import fit_legend
    assert fit_legend((85, 75, 65, 55, 45)) == [
        {"band": 1, "label": "85+"}, {"band": 2, "label": "75–85"}, {"band": 3, "label": "65–75"},
        {"band": 4, "label": "55–65"}, {"band": 5, "label": "45–55"}, {"band": 6, "label": "under 45"}]


@pytest.mark.django_db
def test_browse_map_has_fit_bands_and_legend(client):
    content = client.get(reverse("core:start"), {"view": "map"}).content.decode()
    assert f'"fitBands": {list(settings.MAP_FIT_COLOUR_BANDS)}' in content
    assert "Best Fit Score" in content and 'class="ff-swatch ff-fit-1"' in content and "under 45" in content


def test_map_js_colours_pins_by_fit():
    source = (STATIC_JS / "map.js").read_text(encoding="utf-8")
    assert "function fitBandClass" in source and "cfg.fitBands" in source
    assert "fitBandClass(loc.fit)" in source  # the location's best flat


def test_map_js_keeps_unchanged_pins():
    """A redraw only touches pins that changed; clearing all 500 every move made zoom 14 laggy."""
    source = (STATIC_JS / "map.js").read_text(encoding="utf-8")
    assert "pinMarkers" in source and "pinLayer.removeLayer(pinMarkers[key].marker)" in source
    body = source[source.index("function displayFlatPins"):source.index("function displayBookmarkPins")]
    assert "pinLayer.clearLayers()" not in body
