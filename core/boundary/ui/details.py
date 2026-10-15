"""
«Boundary» FlatDetailsUI — Property Details Page (UC-02): the FR 2.2.3.1 fields, the
Fit Score breakdown and nearby amenities (UC-11). Back follows the `from` guard
(start | results | saved). Selecting an amenity happens on the map, through MapUI.
"""
from django.conf import settings
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from core.control.amenity import AmenityController
from core.control.search import SearchController
from core.entity import CATEGORIES, ResaleFlat
from core.templatetags.flatfinder import display_name

from .forms import SearchForm, has_search

ORIGINS = ("start", "results", "saved")


def flat_details(request, flat_id):
    flat = get_object_or_404(ResaleFlat.objects.select_related("proximity"), pk=flat_id)
    origin = request.GET.get("from")
    origin = origin if origin in ORIGINS else "start"

    fit, breakdown, search_error = None, None, False
    form = SearchForm(request.GET)
    if has_search(request.GET):
        if form.is_valid():
            query = form.to_query()
            controller = SearchController()
            fit = controller.calculate_fit_score(flat, query, controller.bounds_for(query))
            breakdown = breakdown_rows(fit, query)
        else:
            search_error = True

    nearby = AmenityController().find_nearest_amenities(flat)
    amenity_groups = [
        {"key": c.key, "label": c.label, "items": nearby.get(c.key, [])} for c in CATEGORIES
    ]

    return render(request, "core/details.html", {
        "flat": flat,
        "origin": origin,
        "back_url": back_url(request, origin),
        "fit": fit,
        "breakdown": breakdown,
        "search_error": search_error,
        "amenity_groups": amenity_groups,
        "radius_m": settings.AMENITY_RADIUS_M,
    })


def back_url(request, origin) -> str:
    """
    The `from` guard on Back (dialog map): Results keeps its full query string,
    Saved goes to the Saved page, and Start (or anything unknown) goes to Start.
    """
    if origin == "saved":
        return reverse("core:saved")
    params = request.GET.copy()
    params.pop("from", None)
    query = params.urlencode()
    path = reverse("core:results") if origin == "results" else reverse("core:start")
    return f"{path}?{query}" if query else path


def breakdown_rows(fit, query) -> list:
    """
    One row per part of the Fit Score (PLAN §4): its weight, its 0–1 sub-score and the
    points it adds to the total, so the rows add up to the score. Ignored categories
    have no weight and add nothing.
    """
    fixed = settings.FIT_SCORE_FIXED_WEIGHTS
    rows = [
        {"label": "Price", "weight": fixed["price"], "score": fit.priceScore, "fixed": True},
        {"label": "Remaining lease", "weight": fixed["lease"], "score": fit.leaseScore, "fixed": True},
    ]
    for category in CATEGORIES:
        rows.append({"label": category.label, "weight": getattr(query, category.weight_field),
                     "score": getattr(fit, category.score_field), "fixed": False})
    if query.hasAnchor:
        rows.append({"label": f"Near {display_name(query.anchorLabel)}", "weight": query.anchorWeight,
                     "score": fit.anchorScore, "fixed": False})

    total_weight = sum(r["weight"] for r in rows if r["weight"] is not None)
    for row in rows:
        row["ignored"] = row["weight"] is None
        row["points"] = None if row["ignored"] else 100 * row["weight"] * row["score"] / total_weight
    return rows
