"""
«Boundary» SearchUI — sidebar filter form, results list (one card per block), the Block
Results page, sort control, search bar and the No Results state (UC-01, UC-07, UC-08, UC-09,
UC-10; NFR 2.2, NFR 3.2; PLAN §11).
"""
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from backend.core.integrations.onemap import OneMapError
from backend.core.services.errors import ErrorHandler
from backend.core.services.search import SearchController
from backend.core.models import CATEGORIES, FLAT_TYPES, ResaleFlat, SearchQuery

from .forms import SORT_OPTIONS, SearchForm, parse_sort_order, sort_param

# The last Browsing page (Start or Results), for Back on the Saved page (PLAN §6).
LAST_BROWSE_KEY = "last_browse_url"


def remember_browsing_page(request):
    """Store this page for Back on the Saved page; only write the session when it changes."""
    path = request.get_full_path()
    if request.session.get(LAST_BROWSE_KEY) != path:
        request.session[LAST_BROWSE_KEY] = path


def start(request):
    """Start Page (dialog map): the sidebar form, plus an intro panel or the map."""
    remember_browsing_page(request)
    form = SearchForm(request.GET or None)
    return render(request, "start.html", {"sidebar": form.sidebar_state()})


def results(request):
    """Results Page (dialog map): ranked, sorted, paginated matches (20 per page), or No Results."""
    if "q" in request.GET:
        return apply_search_bar(request)
    remember_browsing_page(request)
    form = SearchForm(request.GET)
    context = {"sidebar": None, "form_errors": None, "result": None}
    if not form.is_valid():
        context.update(sidebar=form.sidebar_state(), form_errors=_error_messages(form))
        return render(request, "results.html", context, status=400)

    query = form.to_query()
    controller = SearchController()
    result = controller.rank_flats(controller.filter_flats(query), query)
    order = parse_sort_order(request.GET.get("sort"))
    result = controller.sort_results(result, order)  # UC-10

    # One card per block, 20 blocks per page (PLAN §11).
    page = Paginator(result.blockGroups, settings.RESULTS_PER_PAGE).get_page(request.GET.get("page"))
    flats = ResaleFlat.objects.select_related("proximity").in_bulk(
        [fid for group in page.object_list for fid in group])
    block_query = request.GET.urlencode()
    cards = [_card([flats[fid] for fid in group], result.fitScores, block_query) for group in page.object_list]

    details_params = request.GET.copy()
    details_params.pop("page", None)
    details_params["from"] = "results"

    context.update(
        sidebar=form.sidebar_state(),
        result=result,
        query=query,
        page=page,
        page_range=page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1),
        cards=cards,
        details_query=details_params.urlencode(),
        sort_options=SORT_OPTIONS,
        current_sort=sort_param(order),
    )
    return render(request, "results.html", context)


def block_results(request, block, street):
    """
    Block Results page (PLAN §11): the flats in one block that match the search, each with
    the Fit Score it has on the Results page (scored on the whole search's thresholds).
    Back returns to the Results page with the same search, page and sort.
    """
    lead = ResaleFlat.objects.select_related("proximity").filter(block=block, street_name=street).first()
    if lead is None:
        raise Http404("No such block.")
    remember_browsing_page(request)
    form = SearchForm(request.GET)
    back = request.GET.urlencode()
    # No map on this page, so the List/Map toggle is hidden; Back keeps the view mode.
    context = {"lead": lead, "back_url": reverse("core:results") + (f"?{back}" if back else ""),
               "sidebar": form.sidebar_state(), "hide_view_toggle": True,
               "result": None, "cards": [], "form_errors": None}
    if not form.is_valid():
        context["form_errors"] = _error_messages(form)
        return render(request, "block.html", context, status=400)

    query = form.to_query()
    controller = SearchController()
    order = parse_sort_order(request.GET.get("sort"))
    matching = controller.filter_flats(query).filter(block=block, street_name=street)
    result = controller.rank_flats(matching, query, bounds=controller.bounds_for(query))
    result = controller.sort_results(result, order)
    flats = ResaleFlat.objects.select_related("proximity").in_bulk(result.flatIds)

    details_params = request.GET.copy()
    details_params["from"] = "block"
    context.update(
        result=result,
        cards=[{"flat": flats[fid], "fit": result.fitScores[fid]} for fid in result.flatIds],
        details_query=details_params.urlencode(),
        sort_options=SORT_OPTIONS,
        current_sort=sort_param(order),
    )
    return render(request, "block.html", context)


def block_url(block, street, query="") -> str:
    """The Block Results page for one block, carrying the search's query string."""
    path = reverse("core:block_results", args=[block, street])
    return f"{path}?{query}" if query else path


def _card(flats, fit_scores, block_query) -> dict:
    """
    One results card (PLAN §11): a flat card when the block has one matching flat,
    otherwise a block card summarising its flats, which links to the Block Results page.
    """
    lead = flats[0]
    if len(flats) == 1:
        return {"flat": lead, "fit": fit_scores[lead.id]}
    prices = [f.resale_price for f in flats]
    areas = [f.floor_area_sqm for f in flats]
    leases = [f.remaining_lease for f in flats]
    commenced = [f.lease_commence_date for f in flats]
    return {"block": {
        "lead": lead,
        "count": len(flats),
        "best_fit": max(fit_scores[f.id].total for f in flats),
        "flat_types": [t for t in FLAT_TYPES if any(f.flat_type == t for f in flats)],
        "min_price": min(prices), "max_price": max(prices),
        "min_area": min(areas), "max_area": max(areas),
        "min_lease": min(leases), "max_lease": max(leases),
        "first_commenced": min(commenced), "last_commenced": max(commenced),
        "url": block_url(lead.block, lead.street_name, block_query),
    }}


def apply_search_bar(request):
    """
    UC-07 Search via Search Bar: geocode `q` through OneMap and make it the proximity
    anchor (decision 4). Every outcome redirects to a URL without `q`, so paging and
    sorting never geocode again:
      - match:     the URL gains anchor_lat / anchor_lng / anchor_label (and w_anchor)
      - no match:  "No matching location found" (UC-07.EX.2)
      - failure:   the OneMap banner (UC-07.EX.1 -> UC-06); results still load
    """
    params = request.GET.copy()
    text = (params.pop("q", [""])[0] or "").strip()[:120]
    params.pop("page", None)
    if text:
        form = SearchForm(params)
        query = form.to_query() if form.is_valid() else SearchQuery()
        try:
            found = SearchController().set_proximity_anchor(query, text)
        except OneMapError as exc:
            messages.error(request, ErrorHandler().handle(exc))
        else:
            if found:
                params["anchor_lat"] = f"{query.anchorLat:.6f}"
                params["anchor_lng"] = f"{query.anchorLng:.6f}"
                params["anchor_label"] = query.anchorLabel
                params.setdefault("w_anchor", str(query.anchorWeight))
            else:
                messages.warning(request, f'No matching location found for "{text}". Try a postal code or a place name.')
    encoded = params.urlencode()
    return redirect(reverse("core:results") + (f"?{encoded}" if encoded else ""))


FIELD_LABELS = {
    "min_budget": "Minimum budget", "max_budget": "Maximum budget", "flat_type": "Flat types",
    "min_lease": "Minimum remaining lease", "max_walk_bus": "Walk to bus stop",
    "max_walk_mrt": "Walk to MRT station", "w_anchor": "Search location importance",
    **{f"w_{c.key}": f"{c.label} importance" for c in CATEGORIES},
}


def _error_messages(form):
    """Each error prefixed with the control it belongs to, unless it already names it."""
    messages = []
    for field, errors in form.errors.items():
        label = FIELD_LABELS.get(field, "")
        for error in errors:
            messages.append(f"{label}: {error}" if label and not error.startswith(label) else error)
    return messages
