"""
«Boundary» CompareUI — the Compare page and the compare-tray toggle (Phase H).

Selection lives in a session tray (`compare_ids`, up to 3). The compare page reads the tray,
rebuilds the search context when a search is present (so the default Compare total equals the
Fit Score), applies any cw_* weight overrides (sliders + "ignore" flags), and renders the
side-by-side breakdown.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from backend.core.models import CATEGORIES, ResaleFlat
from backend.core.services.compare import (
    CompareController, compare_homes, parse_weights, weight_param_names,
)
from backend.core.services.search import SearchController

from .forms import SearchForm, has_search

_CATEGORY_KEYS = {c.key for c in CATEGORIES}


def compare(request):
    controller = CompareController()
    ids = controller.ids(request.session)
    flats = []
    if ids:
        by_id = ResaleFlat.objects.select_related("proximity").in_bulk(ids)
        flats = [by_id[i] for i in ids if i in by_id]
        if len(flats) != len(ids):
            # Drop ids that no longer resolve (e.g. after a re-import).
            request.session["compare_ids"] = [f.id for f in flats]
            request.session.modified = True

    query = None
    bounds = None
    search_error = False
    if has_search(request.GET):
        form = SearchForm(request.GET)
        if form.is_valid():
            query = form.to_query()
            bounds = SearchController().bounds_for(query)
        else:
            search_error = True

    result = compare_homes(flats, query, bounds, parse_weights(request.GET, query)) if len(flats) >= 2 else None

    origin = request.GET.get("from")
    origin = origin if origin in ("results", "saved") else ("results" if has_search(request.GET) else "saved")

    return render(request, "compare.html", {
        "result": result,
        "weight_rows": _weight_rows(result) if result else [],
        "weight_exclude": ",".join(weight_param_names()),
        "origin": origin,
        "back_url": back_url(request, origin),
        "reset_url": _reset_url(request),
        "search_error": search_error,
        "hide_view_toggle": True,
    })


def _weight_rows(result) -> list:
    """One slider row per factor: a 1–10 slider plus an "Ignore" checkbox (off = weight 0)."""
    rows = []
    for factor in result["factors"]:
        key = factor["key"]
        weight = factor["weight"]
        rows.append({
            "label": factor["label"],
            "name": f"cw_{key}",
            "flag": f"cw_{key}_off",
            "value": weight if weight > 0 else 5,
            "off": weight == 0,
            "swatch": _swatch(key),
        })
    return rows


def _swatch(key):
    if key == "anchor":
        return "anchor"
    return key if key in _CATEGORY_KEYS else None


def _reset_url(request) -> str:
    """The compare page URL with every cw_* param removed (defaults restored)."""
    params = request.GET.copy()
    for key in list(params.keys()):
        if key.startswith("cw_"):
            params.pop(key)
    query = params.urlencode()
    return f"{reverse('core:compare')}?{query}" if query else reverse("core:compare")


def back_url(request, origin) -> str:
    """Back returns to Results (keeping the search) or to Saved, matching the tray entry point."""
    if origin == "saved":
        return reverse("core:saved")
    params = request.GET.copy()
    for key in list(params.keys()):
        if key == "from" or key == "ids" or key.startswith("cw_"):
            params.pop(key)
    query = params.urlencode()
    path = reverse("core:results") if origin == "results" else reverse("core:start")
    return f"{path}?{query}" if query else path


@require_POST
def toggle_compare_api(request, flat_id):
    """POST /api/compare/<flat_id>/toggle -> {added, count}. A plain form post redirects to `next`."""
    get_object_or_404(ResaleFlat, pk=flat_id)
    controller = CompareController()
    added = controller.toggle(request.session, flat_id)
    count = len(controller.ids(request.session))
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"added": added, "count": count})
    return redirect(_safe_next(request))


@require_POST
def clear_compare_api(request):
    """POST /api/compare/clear -> {count: 0}. A plain form post redirects to `next`."""
    CompareController().clear(request.session)
    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"count": 0})
    return redirect(_safe_next(request))


def _safe_next(request) -> str:
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("core:saved")
    return next_url
