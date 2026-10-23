"""
«Boundary» FlatDetailsUI — Property Details Page (UC-02): the FR 2.2.3.1 fields, the
Fit Score breakdown and nearby amenities (UC-11). When opened from Results with a search,
the page is block-level: shared block fields, a table of (flat_type, storey_range)
combinations, and the block's best flat's Fit Score with the Price row highlighted as the
varying part. Back follows the `from` guard (start | results | saved). Selecting an amenity
happens on the map, through MapUI.
"""
from django.conf import settings
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from backend.core.services.amenity import AmenityController
from backend.core.services.search import SearchController
from backend.core.models import CATEGORIES, FLAT_TYPES, ResaleFlat
from backend.core.templatetags.flatfinder import display_name

from .forms import SearchForm, has_search

ORIGINS = ("start", "results", "saved", "compare")


def flat_details(request, flat_id):
    flat = get_object_or_404(ResaleFlat.objects.select_related("proximity"), pk=flat_id)
    origin = request.GET.get("from")
    # `block` was the pre-consolidation origin for the old block page; treat it as Results.
    origin = "results" if origin == "block" else (origin if origin in ORIGINS else "start")

    fit, breakdown, search_error = None, None, False
    block_view = False
    shared, variants, best_flat, location_flat = None, [], flat, flat
    query = None

    form = SearchForm(request.GET)
    if has_search(request.GET):
        if form.is_valid():
            query = form.to_query()
            controller = SearchController()
            if origin == "results":
                # Block-level view: every matching flat in this block, scored on the whole
                # search's thresholds so its Fit Scores match the Results page exactly.
                matching = controller.filter_flats(query).filter(block=flat.block, street_name=flat.street_name)
                result = controller.rank_flats(matching, query, bounds=controller.bounds_for(query))
                flats = ResaleFlat.objects.select_related("proximity").in_bulk(result.flatIds)
                sorted_flats = [flats[fid] for fid in result.flatIds]
                if sorted_flats:
                    variants = _variants(sorted_flats, result.fitScores)
                    location_flat = next((f for f in sorted_flats if f.has_coords), flat)
                    shared = _shared(sorted_flats, location_flat, variants)
                    best_flat = _best_flat(sorted_flats, result.fitScores)
                    fit = result.fitScores[best_flat.id]
                    breakdown = breakdown_rows(fit, query, price_range=(shared["min_price"], shared["max_price"]))
                    block_view = True
            else:
                # Saved / direct link that still carries a search in its URL: score this flat.
                fit = controller.calculate_fit_score(flat, query, controller.bounds_for(query))
                breakdown = breakdown_rows(fit, query)
        else:
            search_error = True

    # The "Flat types and storeys" table always appears. With a Results search it holds the
    # matching flats (with Fit Scores); otherwise it lists every flat in the block (no Fit
    # Scores, so the Fit Score column shows a dash).
    if not block_view:
        block_flats = ResaleFlat.objects.filter(block=flat.block, street_name=flat.street_name)
        variants = _variants(block_flats)

    # Past transactions (Phase G): every transaction for this block, filtered (defaulting to
    # the search's flat type / price / lease unless overridden) and paged 7 per page.
    tx_filters = _transaction_filters(request, query)
    transactions = ResaleFlat.objects.filter(block=flat.block, street_name=flat.street_name)
    if tx_filters["flat_types"]:
        transactions = transactions.filter(flat_type__in=tx_filters["flat_types"])
    if tx_filters["min_price"] is not None:
        transactions = transactions.filter(resale_price__gte=tx_filters["min_price"])
    if tx_filters["max_price"] is not None:
        transactions = transactions.filter(resale_price__lte=tx_filters["max_price"])
    if tx_filters["min_lease"] is not None:
        transactions = transactions.filter(remaining_lease__gte=tx_filters["min_lease"])
    transactions = transactions.order_by("-month", "-resale_price")
    tx_paginator = Paginator(transactions, 7)
    transactions_page = tx_paginator.get_page(request.GET.get("tx_page"))
    tx_page_range = tx_paginator.get_elided_page_range(transactions_page.number, on_each_side=1, on_ends=1)

    nearby = AmenityController().find_nearest_amenities(location_flat)
    amenity_groups = [
        {"key": c.key, "label": c.label, "items": nearby.get(c.key, [])} for c in CATEGORIES
    ]

    # Keep the current search when switching the same flat/block to Map View from the list layout.
    map_params = request.GET.copy()
    map_params["view"] = "map"
    map_view_url = f"{reverse('core:flat_details', args=[best_flat.id])}?{map_params.urlencode()}"

    return render(request, "details.html", {
        "flat": flat,
        "origin": origin,
        "block_view": block_view,
        "shared": shared,
        "variants": variants,
        "best_flat": best_flat,
        "location_flat": location_flat,
        "back_url": back_url(request, origin),
        "fit": fit,
        "breakdown": breakdown,
        "search_error": search_error,
        "amenity_groups": amenity_groups,
        "radius_m": settings.AMENITY_RADIUS_M,
        "map_view_url": map_view_url,
        "transactions": transactions_page,
        "tx_page_range": tx_page_range,
        "tx_form": {
            "flat_type_options": [
                {"value": t, "label": t.title(), "checked": t in tx_filters["flat_types"]}
                for t in FLAT_TYPES
            ],
            "min_price": "" if tx_filters["min_price"] is None else str(tx_filters["min_price"]),
            "max_price": "" if tx_filters["max_price"] is None else str(tx_filters["max_price"]),
            "min_lease": "" if tx_filters["min_lease"] is None else format(tx_filters["min_lease"], "g"),
        },
    })


def back_url(request, origin) -> str:
    """
    The `from` guard on Back (dialog map): Results keeps its full query string, Saved goes
    to the Saved page, Compare returns to the Compare page, and Start (or unknown) to Start.
    """
    if origin == "compare":
        return reverse("core:compare")
    if origin == "saved":
        return reverse("core:saved")
    params = request.GET.copy()
    params.pop("from", None)
    query = params.urlencode()
    path = reverse("core:results") if origin == "results" else reverse("core:start")
    return f"{path}?{query}" if query else path


def _variants(flats, fit_scores=None) -> list:
    """Group a block's flats by (flat_type, storey_range) for the details table.

    With `fit_scores`, each combination carries its best Fit Score; without it (no search),
    `best_fit` is None and the Fit Score column renders as a dash.
    """
    groups = {}
    for flat in flats:
        key = (flat.flat_type, flat.storey_range)
        group = groups.setdefault(key, {
            "flat_type": flat.flat_type, "storey_range": flat.storey_range,
            "prices": [], "areas": [], "fits": [],
        })
        group["prices"].append(flat.resale_price)
        group["areas"].append(flat.floor_area_sqm)
        if fit_scores is not None:
            group["fits"].append(fit_scores[flat.id].total)

    variants = [
        {
            "flat_type": group["flat_type"],
            "storey_range": group["storey_range"],
            "count": len(group["prices"]),
            "min_price": min(group["prices"]),
            "max_price": max(group["prices"]),
            "min_area": min(group["areas"]),
            "max_area": max(group["areas"]),
            "best_fit": max(group["fits"]) if group["fits"] else None,
        }
        for group in groups.values()
    ]
    if fit_scores is not None:
        variants.sort(key=lambda v: (-v["best_fit"], v["flat_type"], v["storey_range"]))
    else:
        variants.sort(key=lambda v: (v["flat_type"], v["storey_range"]))
    return variants


def _shared(sorted_flats, location_flat, variants) -> dict:
    """The block-level fields shown once above the per-variant table."""
    leases = [f.remaining_lease for f in sorted_flats]
    commenced = [f.lease_commence_date for f in sorted_flats]
    prices = [f.resale_price for f in sorted_flats]
    areas = [f.floor_area_sqm for f in sorted_flats]
    return {
        "block": location_flat.block,
        "street_name": location_flat.street_name,
        "town": location_flat.town,
        "models": sorted({f.flat_model for f in sorted_flats}),
        "first_commenced": min(commenced),
        "last_commenced": max(commenced),
        "min_lease": min(leases),
        "max_lease": max(leases),
        "min_price": min(prices),
        "max_price": max(prices),
        "min_area": min(areas),
        "max_area": max(areas),
        "count": len(sorted_flats),
        "variant_count": len(variants),
        "best_fit": max(v["best_fit"] for v in variants),
    }


def _best_flat(sorted_flats, fit_scores) -> ResaleFlat:
    """The block's highest-Fit flat; ties break to the cheaper flat (like sort_results)."""
    return max(sorted_flats, key=lambda f: (fit_scores[f.id].total, -float(f.resale_price)))


def breakdown_rows(fit, query, price_range=None) -> list:
    """
    One row per part of the Fit Score (PLAN §4): its weight, its 0–1 sub-score and the
    points it adds to the total, so the rows add up to the score. Ignored categories
    have no weight and add nothing. When `price_range` is given (block view), the Price
    row is marked `varying` with that min/max range.
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
        row["varying"] = False
    if price_range is not None:
        rows[0].update(varying=True, min_price=price_range[0], max_price=price_range[1])
    return rows


def _transaction_filters(request, query) -> dict:
    """Past-transaction filters, defaulting to the search's (UC-01) values unless overridden.

    The filter form submits a `tx_submit` marker, so an empty flat-type selection ("all
    types") is distinguishable from "not yet filtered" (which falls back to the search).
    """
    submitted = "tx_submit" in request.GET
    return {
        "flat_types": (request.GET.getlist("tx_flat_type") if submitted
                       else (query.flatTypes if query else [])),
        "min_price": (_parse_int(request.GET.get("tx_min_price")) if submitted
                      else (query.minBudget if query else None)),
        "max_price": (_parse_int(request.GET.get("tx_max_price")) if submitted
                      else (query.maxBudget if query else None)),
        "min_lease": (_parse_float(request.GET.get("tx_min_lease")) if submitted
                      else (query.minRemainingLease if query else None)),
    }


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
