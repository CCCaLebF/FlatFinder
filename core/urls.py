from django.urls import path

from core.boundary.ui import bookmarks, details, map, search

app_name = "core"

urlpatterns = [
    # Pages (PLAN §6, dialog map)
    path("", search.start, name="start"),
    path("results", search.results, name="results"),
    path("flats/<int:flat_id>/", details.flat_details, name="flat_details"),
    path("saved/", bookmarks.saved, name="saved"),
    # JSON endpoints for MapUI and BookmarkUI
    path("api/flats/area-counts", map.area_counts_api, name="api_area_counts"),
    path("api/flats/in-bounds", map.flats_in_bounds_api, name="api_flats_in_bounds"),
    path("api/flats/<int:flat_id>/amenities", map.flat_amenities_api, name="api_flat_amenities"),
    path("api/walking-distance", map.walking_distance_api, name="api_walking_distance"),
    path("api/bookmarks/<int:flat_id>/toggle", bookmarks.toggle_bookmark_api, name="api_toggle_bookmark"),
]
