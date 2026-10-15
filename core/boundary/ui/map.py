"""
«Boundary» MapUI, server side — the JSON endpoints that static/core/js/map.js fetches
(UC-03, UC-04, UC-11, UC-12). Rendering happens in the browser.
"""
from . import not_implemented


def area_counts_api(request):
    """GET /api/flats/area-counts?<query> — FR 2.1.1."""
    return not_implemented(6)


def flats_in_bounds_api(request):
    """GET /api/flats/in-bounds?south=&west=&north=&east=&<query> — FR 2.1.2, FR 2.2.1."""
    return not_implemented(6)


def flat_amenities_api(request, flat_id):
    """GET /api/flats/<id>/amenities — UC-11, FR 2.3."""
    return not_implemented(6)


def walking_distance_api(request):
    """GET /api/walking-distance?flat_id=&lat=&lng= -> {metres, minutes} or {error} 502 (UC-04)."""
    return not_implemented(7)
