from django.conf import settings

from core.control.bookmark import BookmarkController


def flatfinder_context(request):
    """
    Values every page needs: the header's Saved (n) counter, which flats are bookmarked
    (for the bookmark icons, UC-05) and the view mode (PLAN §6).
    """
    view_mode = request.GET.get("view")
    bookmarked_ids = BookmarkController().bookmarked_ids(request.session)
    return {
        "saved_count": len(bookmarked_ids),
        "bookmarked_ids": bookmarked_ids,
        "view_mode": view_mode if view_mode in ("list", "map") else None,
        "map_config": {
            "tileUrl": settings.MAP_TILE_URL,
            "attribution": settings.MAP_TILE_ATTRIBUTION,
            "pinMinZoom": settings.MAP_PIN_MIN_ZOOM,
            "minZoom": settings.MAP_MIN_ZOOM,
            "maxZoom": settings.MAP_MAX_ZOOM,
        },
    }
