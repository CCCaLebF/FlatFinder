"""Phase 4: UC-10 Sort, UC-05 Bookmark Resale Flat, UC-14 View Bookmarked Flats."""
from decimal import Decimal

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client
from django.urls import reverse

from backend.core.views.forms import SORT_OPTIONS, parse_sort_order
from backend.core.services.bookmark import BookmarkController
from backend.core.services.search import SearchController
from backend.core.models import ResaleFlat, SearchQuery, SortOrder

JSON = {"HTTP_ACCEPT": "application/json"}


def toggle_url(flat_id):
    return reverse("core:api_toggle_bookmark", args=[flat_id])


# --- UC-10 Sort ---------------------------------------------------------------------

@pytest.fixture
def three_flats(make_flat):
    return {
        "small_cheap_old": make_flat(block="1", resale_price=Decimal("300000"), remaining_lease=55, floor_area_sqm=67),
        "mid": make_flat(block="2", resale_price=Decimal("450000"), remaining_lease=90, floor_area_sqm=110),
        "big_dear": make_flat(block="3", resale_price=Decimal("700000"), remaining_lease=75, floor_area_sqm=140),
    }


@pytest.mark.django_db
@pytest.mark.parametrize("field, direction, expected", [
    ("price", "asc", ["small_cheap_old", "mid", "big_dear"]),
    ("price", "desc", ["big_dear", "mid", "small_cheap_old"]),
    ("remaining_lease", "desc", ["mid", "big_dear", "small_cheap_old"]),
    ("remaining_lease", "asc", ["small_cheap_old", "big_dear", "mid"]),
    ("floor_area", "desc", ["big_dear", "mid", "small_cheap_old"]),
    ("floor_area", "asc", ["small_cheap_old", "mid", "big_dear"]),
])
def test_sort_results(three_flats, field, direction, expected):
    controller = SearchController()
    query = SearchQuery()
    result = controller.rank_flats(controller.filter_flats(query), query)
    scores_before = {i: result.fitScores[i].total for i in result.flatIds}

    result = controller.sort_results(result, SortOrder(field, direction))
    assert result.flatIds == [three_flats[name].id for name in expected]
    assert result.sortOrder == SortOrder(field, direction)
    # Sorting changes only the order, never which flats or their scores (SRS: Sort Order).
    assert {i: result.fitScores[i].total for i in result.flatIds} == scores_before


@pytest.mark.django_db
def test_fit_score_sort_both_ways(three_flats):
    controller = SearchController()
    query = SearchQuery()
    result = controller.rank_flats(controller.filter_flats(query), query)
    desc = list(result.flatIds)
    totals = [result.fitScores[i].total for i in desc]
    assert totals == sorted(totals, reverse=True)
    assert controller.sort_results(result, SortOrder("fit_score", "asc")).flatIds == desc[::-1]


def test_parse_sort_order():
    assert parse_sort_order("price-asc") == SortOrder("price", "asc")
    assert parse_sort_order("remaining_lease-desc") == SortOrder("remaining_lease", "desc")
    for bad in (None, "", "town-asc", "price-up", "price"):
        assert parse_sort_order(bad) == SortOrder()
    for value, _ in SORT_OPTIONS:
        assert parse_sort_order(value) != SortOrder() or value == "fit_score-desc"


@pytest.mark.django_db
def test_results_page_sort_control(client, three_flats):
    response = client.get(reverse("core:results"), {"sort": "price-desc", "max_budget": 800000, "page": 1})
    content = response.content.decode()
    order = [content.index(f"data-flat-card=\"{three_flats[n].id}\"") for n in ("big_dear", "mid", "small_cheap_old")]
    assert order == sorted(order)
    assert '<option value="price-desc" selected>' in content
    # The sort form carries the search but not sort/page.
    sort_form = content[content.index("data-sort-form"):]
    sort_form = sort_form[:sort_form.index("</form>")]
    assert '<input type="hidden" name="max_budget" value="800000">' in sort_form
    assert 'name="page"' not in sort_form and 'type="hidden" name="sort"' not in sort_form


@pytest.mark.django_db
def test_invalid_sort_falls_back_to_fit_score(client, three_flats):
    response = client.get(reverse("core:results"), {"sort": "nonsense"})
    assert response.status_code == 200
    assert '<option value="fit_score-desc" selected>' in response.content.decode()


# --- BookmarkController -------------------------------------------------------------

@pytest.mark.django_db
def test_bookmark_controller_toggle_and_list():
    session = SessionStore()
    controller = BookmarkController()
    assert controller.get_bookmarks(session) == []

    assert controller.toggle_bookmark(session, 5) is True
    assert controller.toggle_bookmark(session, "7") is True
    assert controller.is_bookmarked(session, 5) and controller.is_bookmarked(session, 7)

    bookmarks = controller.get_bookmarks(session)
    assert [b.flat_id for b in bookmarks] == [7, 5]  # newest first
    assert all(b.session_id == session.session_key for b in bookmarks)
    assert bookmarks[0].timestamp >= bookmarks[1].timestamp

    assert controller.toggle_bookmark(session, 5) is False  # UC-05.AC.1: toggles off
    assert controller.bookmarked_ids(session) == {7}


@pytest.mark.django_db
def test_bookmarks_survive_a_saved_session():
    session = SessionStore()
    BookmarkController().toggle_bookmark(session, 3)
    session.save()
    reloaded = SessionStore(session_key=session.session_key)
    assert BookmarkController().is_bookmarked(reloaded, 3)


# --- Toggle API -----------------------------------------------------------------------

@pytest.mark.django_db
def test_toggle_api_returns_saved_and_count(client, make_flat):
    a, b = make_flat(), make_flat()
    assert client.post(toggle_url(a.id), **JSON).json() == {"saved": True, "count": 1}
    assert client.post(toggle_url(b.id), **JSON).json() == {"saved": True, "count": 2}
    assert client.post(toggle_url(a.id), **JSON).json() == {"saved": False, "count": 1}


@pytest.mark.django_db
def test_toggle_api_rejects_get_and_unknown_flats(client, make_flat):
    flat = make_flat()
    assert client.get(toggle_url(flat.id)).status_code == 405
    assert client.post(toggle_url(999_999), **JSON).status_code == 404


@pytest.mark.django_db
def test_toggle_api_is_csrf_protected(make_flat):
    flat = make_flat()
    strict = Client(enforce_csrf_checks=True)
    assert strict.post(toggle_url(flat.id), **JSON).status_code == 403

    strict.get(reverse("core:results"))  # a page with bookmark forms sets the CSRF cookie
    token = strict.cookies["csrftoken"].value
    response = strict.post(toggle_url(flat.id), HTTP_X_CSRFTOKEN=token, **JSON)
    assert response.status_code == 200 and response.json()["saved"] is True


@pytest.mark.django_db
def test_toggle_without_js_redirects_back(client, make_flat):
    flat = make_flat()
    response = client.post(toggle_url(flat.id), {"next": "/results?max_budget=500000"})
    assert response.status_code == 302 and response.url == "/results?max_budget=500000"
    unsafe = client.post(toggle_url(flat.id), {"next": "https://evil.example.com/"})
    assert unsafe.url == reverse("core:saved")


# --- Pages ------------------------------------------------------------------------------

@pytest.mark.django_db
def test_cards_show_bookmark_state_and_header_count(client, make_flat):
    saved, other = make_flat(block="1A"), make_flat(block="2B")
    client.post(toggle_url(saved.id), **JSON)
    content = client.get(reverse("core:results")).content.decode()
    assert 'Saved (<span id="saved-count">1</span>)' in content
    saved_form = content[content.index(f'data-bookmark-form="{saved.id}"'):]
    assert 'aria-pressed="true"' in saved_form[:1200]
    other_form = content[content.index(f'data-bookmark-form="{other.id}"'):]
    assert 'aria-pressed="false"' in other_form[:1200]


@pytest.mark.django_db
def test_saved_page_empty_state(client):
    response = client.get(reverse("core:saved"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "No saved flats yet" in content
    assert 'data-saved-item' not in content


@pytest.mark.django_db
def test_saved_page_lists_bookmarks_newest_first(client, make_flat):
    first, second = make_flat(block="1A"), make_flat(block="2B")
    client.post(toggle_url(first.id), **JSON)
    client.post(toggle_url(second.id), **JSON)
    content = client.get(reverse("core:saved")).content.decode()
    assert content.index("Blk 2B") < content.index("Blk 1A")
    assert content.count('aria-label="Remove from saved flats"') == 2
    assert "from=saved" in content
    assert content.count("data-saved-item") == 2


@pytest.mark.django_db
def test_saved_page_drops_flats_that_no_longer_exist(client, make_flat):
    flat = make_flat()
    client.post(toggle_url(flat.id), **JSON)
    ResaleFlat.objects.all().delete()
    content = client.get(reverse("core:saved")).content.decode()
    assert "No saved flats yet" in content
    assert client.get(reverse("core:start")).context["saved_count"] == 0


@pytest.mark.django_db
def test_saved_back_returns_to_last_browsing_page(client):
    assert client.get(reverse("core:saved")).context["back_url"] == reverse("core:start")  # nothing visited yet
    client.get("/results?max_budget=500000&sort=price-asc")
    assert client.get(reverse("core:saved")).context["back_url"] == "/results?max_budget=500000&sort=price-asc"


@pytest.mark.django_db
def test_saved_back_uses_referrer_when_nothing_stored(client):
    response = client.get(reverse("core:saved"), HTTP_REFERER="http://testserver/results?max_budget=1")
    assert response.context["back_url"] == "http://testserver/results?max_budget=1"
    other_site = client.get(reverse("core:saved"), HTTP_REFERER="https://elsewhere.example/")
    assert other_site.context["back_url"] == reverse("core:start")


# --- Fixes from the pre-phase-5 review ---------------------------------------------------

@pytest.mark.django_db
def test_bookmarks_with_identical_timestamps_keep_newest_first(monkeypatch):
    from django.utils import timezone
    frozen = timezone.now()
    monkeypatch.setattr("backend.core.services.bookmark.timezone.now", lambda: frozen)
    session = SessionStore()
    controller = BookmarkController()
    for flat_id in (1, 2, 3):
        controller.toggle_bookmark(session, flat_id)
    assert [b.flat_id for b in controller.get_bookmarks(session)] == [3, 2, 1]


def test_session_ends_with_the_browser(settings):
    assert settings.SESSION_EXPIRE_AT_BROWSER_CLOSE is True
