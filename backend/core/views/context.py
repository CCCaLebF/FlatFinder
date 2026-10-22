from django.conf import settings

from backend.core.services.bookmark import BookmarkController


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
            "fitBands": list(settings.MAP_FIT_COLOUR_BANDS),
        },
        "fit_legend": fit_legend(settings.MAP_FIT_COLOUR_BANDS),
    }


def fit_legend(bands) -> list:
    """The map legend's Fit Score rows, best first: [{"band": 1, "label": "85+"}, ..., {"label": "under 45"}]."""
    rows = [{"band": 1, "label": f"{bands[0]}+"}]
    rows += [{"band": i + 2, "label": f"{low}–{high}"} for i, (high, low) in enumerate(zip(bands, bands[1:]))]
    rows.append({"band": len(bands) + 1, "label": f"under {bands[-1]}"})
    return rows
