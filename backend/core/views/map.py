"""
«Boundary» MapUI, server side — the JSON endpoints that frontend/static/js/map.js fetches
(UC-03, UC-04, UC-11, UC-12). Rendering happens in the browser.
"""
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.gzip import gzip_page
from django.views.decorators.http import require_GET

from backend.core.integrations.onemap import OneMapError
from backend.core.services.amenity import AmenityController
from backend.core.services.bookmark import BookmarkController
from backend.core.services.distance import StraightLineDistance, WalkingDistance
from backend.core.services.errors import ErrorHandler
from backend.core.services.map import MapController, flats_as_pins
from backend.core.models import CATEGORIES, ResaleFlat

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
@gzip_page  # the biggest response the map fetches; it holds no secrets, so compressing is safe
def flats_in_bounds_api(request):
    """
    GET /api/flats/in-bounds?south=&west=&north=&east=&<query> — FR 2.1.2, FR 2.2.1.
    Fit Scores are included only when the URL carries a search. Each pin's flat list comes
    from flats_at_location_api when its popup opens.
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
def flats_at_location_api(request):
    """
    GET /api/flats/at-location?lat=&lng=&<query> — the matching flats at one pin, best Fit
    Score first, for its popup (FR 2.2.1). Fit Scores only when the URL carries a search.
    """
    query, error = _query_or_error(request)
    if error:
        return error
    try:
        lat, lng = float(request.GET["lat"]), float(request.GET["lng"])
    except (KeyError, ValueError):
        return JsonResponse({"error": "lat and lng are required numbers."}, status=400)
    return JsonResponse(MapController().get_flats_at_location(lat, lng, query, with_scores=has_search(request.GET)))


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


WALK_MAX_STRAIGHT_LINE_M = 1500  # amenities are within 1 km; a little slack, but no open proxy
WALK_CACHE_SECONDS = 24 * 3600


@require_GET
def walking_distance_api(request):
    """
    GET /api/walking-distance?flat_id=&lat=&lng= -> {metres, minutes, routeGeometry}
    (UC-04, FR 1.2.1), or {error} with HTTP 502 when OneMap fails (UC-04.EX.1 -> UC-06).

    Only routes to points near the flat, so the endpoint can't be used to spend our
    OneMap quota on arbitrary routes. Results are cached for a day.
    """
    try:
        flat_id = int(request.GET["flat_id"])
        target = (float(request.GET["lat"]), float(request.GET["lng"]))
    except (KeyError, ValueError):
        return JsonResponse({"error": "flat_id, lat and lng are required numbers."}, status=400)
    flat = get_object_or_404(ResaleFlat, pk=flat_id)
    if not flat.has_coords:
        return JsonResponse({"error": "This flat has no location yet."}, status=400)
    origin = (flat.latitude, flat.longitude)
    if StraightLineDistance().distance_m(origin, target) > WALK_MAX_STRAIGHT_LINE_M:
        return JsonResponse({"error": "That point is too far from the flat."}, status=400)

    # v2: cache the route geometry too; don't reuse pre-Phase-E entries that lack it.
    key = "walk:v2:%.6f,%.6f:%.6f,%.6f" % (*origin, *target)
    route = cache.get(key)
    if route is None:
        try:
            route = WalkingDistance().route(origin, target)
        except OneMapError as exc:
            return ErrorHandler().to_response(exc)
        cache.set(key, route, WALK_CACHE_SECONDS)
    return JsonResponse({
        "metres": round(route["metres"]),
        "minutes": max(1, round(route["seconds"] / 60)) if route["seconds"] else None,
        "routeGeometry": route.get("route_geometry"),
        "fromTownCentre": flat.coords_approximate,
    })
