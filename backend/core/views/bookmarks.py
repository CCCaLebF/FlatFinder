"""
«Boundary» BookmarkUI — bookmark toggle, Saved (n) counter and the Saved Flats page
(UC-05, UC-14, FR 2.2.4). The client side is frontend/static/js/bookmarks.js.
"""
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from backend.core.services.bookmark import BookmarkController
from backend.core.models import ResaleFlat

from .search import LAST_BROWSE_KEY


def saved(request):
    """Saved Flats page, or the "No saved flats yet" empty state (UC-14, FR 2.2.4.2)."""
    controller = BookmarkController()
    bookmarks = controller.get_bookmarks(request.session)
    flats = ResaleFlat.objects.select_related("proximity").in_bulk([b.flat_id for b in bookmarks])
    controller.forget(request.session, [b.flat_id for b in bookmarks if b.flat_id not in flats])
    entries = [{"flat": flats[b.flat_id], "bookmark": b} for b in bookmarks if b.flat_id in flats]

    return render(request, "saved.html", {
        "entries": entries,
        "back_url": _back_url(request),
        "saved_count": len(entries),
    })


@require_POST
def toggle_bookmark_api(request, flat_id):
    """
    POST /api/bookmarks/<flat_id>/toggle -> {saved, count} (UC-05, UC-05.AC.1). CSRF-protected.
    A plain form post (no JS) is redirected back to `next` instead.
    """
    get_object_or_404(ResaleFlat, pk=flat_id)
    controller = BookmarkController()
    saved_now = controller.toggle_bookmark(request.session, flat_id)
    count = len(controller.bookmarked_ids(request.session))

    if "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({"saved": saved_now, "count": count})
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        next_url = reverse("core:saved")
    return redirect(next_url)


def _back_url(request):
    """Back from Saved returns to the last Browsing page: stored, then the referrer, then Start."""
    stored = request.session.get(LAST_BROWSE_KEY)
    if stored:
        return stored
    referrer = request.headers.get("Referer", "")
    saved_path = reverse("core:saved")
    if referrer and saved_path not in referrer and url_has_allowed_host_and_scheme(
            referrer, allowed_hosts={request.get_host()}):
        return referrer
    return reverse("core:start")
