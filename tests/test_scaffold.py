"""Phase 1: the skeleton loads, migrates and serves the Start page."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from django.conf import settings
from django.urls import reverse

from backend.core.services.distance import DistanceStrategy, StraightLineDistance
from backend.core.models import (
    CATEGORIES, Bookmark, BusStop, ChasClinic, ChildCareCentre, FlatProximity, HawkerCentre,
    MrtStation, ResaleFlat, SearchQuery, SearchResult, SortOrder, Town,
)


def create_flat(**overrides):
    fields = dict(
        month=date(2025, 9, 1), town="ANG MO KIO", flat_type="4 ROOM", block="123",
        street_name="ANG MO KIO AVE 3", storey_range="07 TO 09", floor_area_sqm=92.0,
        flat_model="New Generation", lease_commence_date=1980, remaining_lease=54.0,
        remaining_lease_raw="54 years 02 months", resale_price=Decimal("520000"),
    )
    fields.update(overrides)
    return ResaleFlat.objects.create(**fields)


@pytest.mark.django_db
def test_start_page_renders(client):
    response = client.get(reverse("core:start"))
    assert response.status_code == 200
    assert b"FlatFinder" in response.content
    assert b"Saved (" in response.content


@pytest.mark.django_db
def test_flat_coordinates_are_nullable_and_proximity_links():
    flat = create_flat()
    assert flat.latitude is None and not flat.has_coords and not flat.coords_approximate
    FlatProximity.objects.create(flat=flat, nearest_mrt_station_m=420.0)
    assert ResaleFlat.objects.select_related("proximity").get().proximity.nearest_mrt_station_m == 420.0


@pytest.mark.django_db
def test_concrete_nodes_set_their_type():
    bus = BusStop.objects.create(name="Opp Blk 123", stop_code="54321", latitude=1.37, longitude=103.85)
    mrt = MrtStation.objects.create(name="ANG MO KIO MRT STATION", exit_code="Exit A",
                                    latitude=1.37, longitude=103.85)
    assert (bus.type, mrt.type) == ("BUS", "MRT")
    for model, expected in ((ChildCareCentre, "CHILD_CARE"), (HawkerCentre, "HAWKER"), (ChasClinic, "CHAS")):
        assert model.objects.create(name="x", latitude=1.3, longitude=103.8).type == expected
    Town.objects.create(name="ANG MO KIO", centroid_lat=1.37, centroid_lng=103.85)


def test_search_query_unconstrained_and_anchor():
    query = SearchQuery(maxBudget=600000, busStopWeight=8)
    assert query.isUnconstrained("minBudget")
    assert query.isUnconstrained("flatTypes")
    assert not query.isUnconstrained("maxBudget")
    assert query.categoryWeights() == {"bus_stop": 8}
    assert not query.hasAnchor
    query.setAnchor(1.3521, 103.8198, "Bishan")
    assert query.hasAnchor and query.anchorWeight == settings.DEFAULT_ANCHOR_WEIGHT


def test_sort_order_defaults_and_validation():
    assert SortOrder() == SortOrder("fit_score", "desc")
    with pytest.raises(ValueError):
        SortOrder("town")
    with pytest.raises(ValueError):
        SortOrder("price", "up")
    assert SearchResult(query=SearchQuery()).isEmpty


def test_bookmark_session_round_trip():
    bookmark = Bookmark(session_id="abc", flat_id=7, timestamp=datetime(2026, 10, 15, 9, 30))
    assert Bookmark.from_session(bookmark.to_session()) == bookmark


def test_categories_line_up_with_entities():
    assert [c.label for c in CATEGORIES] == [
        "Bus Stops", "MRT Stations", "Child Care Centres", "Hawker Centres", "CHAS Clinics"]
    proximity_fields = {f.name for f in FlatProximity._meta.get_fields()}
    for category in CATEGORIES:
        assert category.proximity_field in proximity_fields
        assert hasattr(SearchQuery(), category.weight_field)


def test_straight_line_distance():
    strategy = StraightLineDistance()
    assert isinstance(strategy, DistanceStrategy)
    # One degree of latitude is ~111.2 km.
    assert strategy.distance_m((1.0, 103.8), (2.0, 103.8)) == pytest.approx(111_195, rel=1e-3)
    assert strategy.distance_m((1.35, 103.8), (1.35, 103.8)) == 0
