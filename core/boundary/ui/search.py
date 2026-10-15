"""
«Boundary» SearchUI — sidebar filter form, results list, sort control, search bar
and the No Results state (UC-01, UC-07, UC-08, UC-09, UC-10; NFR 2.2, NFR 3.2).
"""
from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.urls import reverse

from core.boundary.gateways.onemap import OneMapError
from core.control.errors import ErrorHandler
from core.control.search import SearchController
from core.entity import CATEGORIES, ResaleFlat, SearchQuery

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
    return render(request, "core/start.html", {"sidebar": form.sidebar_state()})


def results(request):
    """Results Page (dialog map): ranked, sorted, paginated matches (20 per page), or No Results."""
    if "q" in request.GET:
        return apply_search_bar(request)
    remember_browsing_page(request)
    form = SearchForm(request.GET)
    context = {"sidebar": None, "form_errors": None, "result": None}
    if not form.is_valid():
        context.update(sidebar=form.sidebar_state(), form_errors=_error_messages(form))
        return render(request, "core/results.html", context, status=400)

    query = form.to_query()
    controller = SearchController()
    result = controller.rank_flats(controller.filter_flats(query), query)
    order = parse_sort_order(request.GET.get("sort"))
    result = controller.sort_results(result, order)  # UC-10

    page = Paginator(result.flatIds, settings.RESULTS_PER_PAGE).get_page(request.GET.get("page"))
    flats = ResaleFlat.objects.in_bulk(list(page.object_list))
    cards = [{"flat": flats[fid], "fit": result.fitScores[fid]} for fid in page.object_list]

    details_params = request.GET.copy()
    details_params.pop("page", None)
    details_params["from"] = "results"

    context.update(
        sidebar=form.sidebar_state(),
        result=result,
        query=query,
        page=page,
        cards=cards,
        details_query=details_params.urlencode(),
        sort_options=SORT_OPTIONS,
        current_sort=sort_param(order),
    )
    return render(request, "core/results.html", context)


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
