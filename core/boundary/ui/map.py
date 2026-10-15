"""
«Boundary» MapUI, server side — the JSON endpoints that static/core/js/map.js fetches
(UC-03, UC-04, UC-11, UC-12). Rendering happens in the browser.
"""
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from core.control.amenity import AmenityController
from core.control.bookmark import BookmarkController
from core.control.map import MapController, flats_as_pins
from core.entity import CATEGORIES, ResaleFlat

from . import not_implemented
from .forms import SearchForm, has_search


def _query_or_error(request):
    form = SearchForm(request.GET)
    if not form.is_valid():
        return None, JsonResponse({"error": "Invalid search parameters.", "fields": list(form.errors)}, status=400)
    return form.to_query(), None


@require_GET
def area_counts_api(request):
    """GET /api/flats/area-counts?<query> — FR 2.1.1: matching flats per town, at its centroid."""
    query, error = _query_or_error(request)
    if error:
        return error
    areas = MapController().get_area_counts(query)
    return JsonResponse({"areas": areas, "total": sum(a["count"] for a in areas)})


@require_GET
def flats_in_bounds_api(request):
    """
    GET /api/flats/in-bounds?south=&west=&north=&east=&<query> — FR 2.1.2, FR 2.2.1.
    Fit Scores are included only when the URL carries a search.
    """
    query, error = _query_or_error(request)
    if error:
        return error
    try:
        bounds = tuple(float(request.GET[k]) for k in ("south", "west", "north", "east"))
    except (KeyError, ValueError):
        return JsonResponse({"error": "south, west, north and east are required numbers."}, status=400)
    if bounds[0] > bounds[2] or bounds[1] > bounds[3]:
        return JsonResponse({"error": "Bounds must have south <= north and west <= east."}, status=400)
    pins = MapController().get_pins_in_view(bounds, query, limit=settings.MAP_PIN_LIMIT,
                                            with_scores=has_search(request.GET))
    return JsonResponse(pins)


@require_GET
def flat_amenities_api(request, flat_id):
    """GET /api/flats/<id>/amenities — UC-11, FR 2.3: the flat and everything within 1 km, by category."""
    flat = get_object_or_404(ResaleFlat, pk=flat_id)
    nearby = AmenityController().find_nearest_amenities(flat)
    return JsonResponse({
        "flat": {"id": flat.id, "lat": flat.latitude, "lng": flat.longitude,
                 "approximate": flat.coords_approximate, "label": f"Blk {flat.block} {flat.street_name}"},
        "radiusM": settings.AMENITY_RADIUS_M,
        "categories": [
            {"key": c.key, "label": c.label,
             "items": [{"id": a.id, "name": a.name, "lat": a.latitude, "lng": a.longitude,
                        "distanceM": a.distance_m, "detail": a.detail} for a in nearby.get(c.key, [])]}
            for c in CATEGORIES
        ],
    })


@require_GET
def bookmarks_api(request):
    """GET /api/bookmarks — the session's saved flats as pins (UC-03.AC.1, UC-14 Map View)."""
    controller = BookmarkController()
    ids = [b.flat_id for b in controller.get_bookmarks(request.session)]
    flats = ResaleFlat.objects.in_bulk(ids)
    return JsonResponse({"count": len(flats), "flats": flats_as_pins(flats[i] for i in ids if i in flats)})


def walking_distance_api(request):
    """GET /api/walking-distance?flat_id=&lat=&lng= -> {metres, minutes} or {error} 502 (UC-04)."""
    return not_implemented(7)
