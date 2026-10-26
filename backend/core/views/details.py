"""
«Boundary» FlatDetailsUI — Property Details Page (UC-02): the FR 2.2.3.1 fields, the
Fit Score breakdown and nearby amenities (UC-11). Unless opened from Saved or Compare (which
point at one sale), the page is block-level: shared block fields and the block's sales. With
a search, those are the matching sales and the Fit Score is the block's best, with the Price
row highlighted as the varying part; without one, every sale in the block, unscored. Back follows the `from` guard (start | results | saved). Selecting an amenity
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

from .floor_plans import floor_plan
from .forms import SearchForm, has_search

ORIGINS = ("start", "results", "saved", "compare")
SINGLE_FLAT_ORIGINS = ("saved", "compare")  # these link to one sale; the rest open the block


def flat_details(request, flat_id):
    flat = get_object_or_404(ResaleFlat.objects.select_related("proximity"), pk=flat_id)
    origin = request.GET.get("from")
    # `block` was the pre-consolidation origin for the old block page; treat it as Results.
    origin = "results" if origin == "block" else (origin if origin in ORIGINS else "start")

    fit, breakdown, search_error = None, None, False
    block_view = False
    shared, variants, best_flat, location_flat = None, [], flat, flat
    query = None
    fits = {}  # flat id -> Fit Score total, for the past-transactions table

    form = SearchForm(request.GET)
    if has_search(request.GET):
        if form.is_valid():
            query = form.to_query()
        else:
            search_error = True
    controller = SearchController()

    if origin in SINGLE_FLAT_ORIGINS:
        # Saved / Compare point at one particular sale: show that flat, scored if the link
        # still carries a search.
        if query:
            fit = controller.calculate_fit_score(flat, query, controller.bounds_for(query))
            fits = {flat.id: fit.total}
            breakdown = breakdown_rows(fit, query)
    else:
        # Block-level view. With a search: every matching flat in this block, scored on the
        # whole search's thresholds so its Fit Scores match the Results page exactly. Without
        # one: every sale in the block, unscored.
        scores = None
        if query:
            matching = controller.filter_flats(query).filter(block=flat.block, street_name=flat.street_name)
            result = controller.rank_flats(matching, query, bounds=controller.bounds_for(query))
            flats = ResaleFlat.objects.select_related("proximity").in_bulk(result.flatIds)
            sorted_flats = [flats[fid] for fid in result.flatIds]
            scores = result.fitScores
        else:
            sorted_flats = list(ResaleFlat.objects.select_related("proximity")
                                .filter(block=flat.block, street_name=flat.street_name)
                                .order_by("-month", "-resale_price"))
        if sorted_flats:
            variants = _variants(sorted_flats, scores)
            location_flat = next((f for f in sorted_flats if f.has_coords), flat)
            shared = _shared(sorted_flats, location_flat, variants)
            block_view = True
            if scores:
                best_flat = _best_flat(sorted_flats, scores)
                fit = scores[best_flat.id]
                fits = {fid: score.total for fid, score in scores.items()}
                breakdown = breakdown_rows(fit, query, price_range=(shared["min_price"], shared["max_price"]))

    # Single-flat view: the variants (for the price-by-type lines, the building and the
    # layouts) are every flat in the block.
    if not block_view:
        block_flats = ResaleFlat.objects.filter(block=flat.block, street_name=flat.street_name)
        variants = _variants(block_flats)

    # Past transactions (Phase G): every transaction for this block, filtered (defaulting to
    # the search's flat type / price unless overridden) and paged 7 per page. Each carries its
    # Fit Score when it is one of the scored flats; a dash otherwise.
    tx_filters = _transaction_filters(request, query)
    transactions = ResaleFlat.objects.filter(block=flat.block, street_name=flat.street_name)
    if tx_filters["flat_types"]:
        transactions = transactions.filter(flat_type__in=tx_filters["flat_types"])
    if tx_filters["min_price"] is not None:
        transactions = transactions.filter(resale_price__gte=tx_filters["min_price"])
    if tx_filters["max_price"] is not None:
        transactions = transactions.filter(resale_price__lte=tx_filters["max_price"])
    transactions = transactions.order_by("-month", "-resale_price")
    tx_paginator = Paginator(transactions, 7)
    transactions_page = tx_paginator.get_page(request.GET.get("tx_page"))
    transactions_page.object_list = list(transactions_page.object_list)
    for tx in transactions_page.object_list:
        tx.fit = fits.get(tx.id)
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
        "price_by_type": _price_by_type(variants),
        # Block view: the matching sales; single view: just this flat's storeys.
        "building": _building(flat, variants if block_view else _variants([flat])),
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


def _storeys(storey_range):
    """'07 TO 09' -> (7, 9); None when the text isn't a storey range."""
    try:
        low, high = (int(part) for part in storey_range.split(" TO "))
    except (AttributeError, ValueError):
        return None
    return low, high


def _building(flat, variants) -> dict:
    """
    The block illustration at the top of the details page: one row per storey, as tall as
    the highest storey sold in this block (the dataset has no building heights), with the
    storeys of the shown sales (`variants`) lit up and listed in a legend.
    """
    all_ranges = ResaleFlat.objects.filter(block=flat.block, street_name=flat.street_name) \
        .values_list("storey_range", flat=True).distinct()
    spans = [s for s in map(_storeys, all_ranges) if s]
    top = max([high for _, high in spans] + [4])

    sold, legend = set(), {}
    for variant in variants:
        span = _storeys(variant["storey_range"])
        if not span:
            continue
        sold.update(range(span[0], span[1] + 1))
        entry = legend.setdefault(span, {"low": span[0], "high": span[1], "types": [], "count": 0})
        if variant["flat_type"] not in entry["types"]:
            entry["types"].append(variant["flat_type"])
        entry["count"] += variant["count"]

    return {
        "block": flat.block,
        "top": top,
        "floors": [{"storey": n, "sold": n in sold} for n in range(top, 0, -1)],
        "floor_px": max(3, min(7, 150 // top)),  # keeps the drawing about 150 px tall
        "legend": sorted(legend.values(), key=lambda e: -e["low"]),
    }


def _price_by_type(variants) -> list:
    """
    The resale price and floor-area range of each flat type among the variants, with its
    typical-layout floor plan, in FLAT_TYPES order.
    """
    groups = {}
    for variant in variants:
        group = groups.setdefault(variant["flat_type"], {
            "flat_type": variant["flat_type"], "min_price": variant["min_price"],
            "max_price": variant["max_price"], "min_area": variant["min_area"],
            "max_area": variant["max_area"], "count": 0, "plan": floor_plan(variant["flat_type"]),
        })
        group["min_price"] = min(group["min_price"], variant["min_price"])
        group["max_price"] = max(group["max_price"], variant["max_price"])
        group["min_area"] = min(group["min_area"], variant["min_area"])
        group["max_area"] = max(group["max_area"], variant["max_area"])
        group["count"] += variant["count"]
    order = {t: i for i, t in enumerate(FLAT_TYPES)}
    return sorted(groups.values(), key=lambda g: (order.get(g["flat_type"], len(order)), g["flat_type"]))


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
        "best_fit": max((v["best_fit"] for v in variants if v["best_fit"] is not None), default=None),
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
    }


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
