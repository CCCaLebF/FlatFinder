"""PLAN §11: results grouped by block, and the Block Results page."""
from decimal import Decimal
from urllib.parse import quote

import pytest
from django.urls import reverse

from backend.core.models import ResaleFlat, SearchQuery, SearchResult, SortOrder
from backend.core.services.search import SearchController
from tests.conftest import build_flat

STREET = "ANG MO KIO AVE 3"  # the fixture's default street


def block_path(block, street=STREET):
    return reverse("core:block_results", args=[block, street])


@pytest.fixture
def two_blocks(make_flat):
    """Block 1A has three sales, block 2B has one."""
    return {
        "a_cheap": make_flat(block="1A", resale_price=Decimal("300000"), storey_range="01 TO 03"),
        "a_mid": make_flat(block="1A", resale_price=Decimal("500000"), storey_range="04 TO 06"),
        "a_dear": make_flat(block="1A", resale_price=Decimal("700000"), storey_range="07 TO 09"),
        "b_only": make_flat(block="2B", resale_price=Decimal("400000")),
    }


def ranked(order=SortOrder(), query=None):
    controller = SearchController()
    query = query or SearchQuery()
    return controller.sort_results(controller.rank_flats(controller.filter_flats(query), query), order)


# --- SearchController.group_by_block --------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("direction, expected", [
    ("asc", [["a_cheap", "a_mid", "a_dear"], ["b_only"]]),
    ("desc", [["a_dear", "a_mid", "a_cheap"], ["b_only"]]),
])
def test_groups_follow_the_sort(two_blocks, direction, expected):
    result = ranked(SortOrder("price", direction))
    names = {flat.id: name for name, flat in two_blocks.items()}
    assert [[names[fid] for fid in group] for group in result.blockGroups] == expected
    assert result.count == 4 and result.blockCount == 2


@pytest.mark.django_db
def test_a_block_takes_the_place_of_its_best_flat(make_flat):
    # Sorted by price ascending: 1A's cheapest (300k) beats 2B (400k), even though 1A also has the dearest.
    a1 = make_flat(block="1A", resale_price=Decimal("300000"))
    b = make_flat(block="2B", resale_price=Decimal("400000"))
    a2 = make_flat(block="1A", resale_price=Decimal("900000"))
    assert ranked(SortOrder("price", "asc")).blockGroups == [[a1.id, a2.id], [b.id]]


@pytest.mark.django_db
def test_same_block_number_on_another_street_is_another_block(make_flat):
    make_flat(block="1A")
    make_flat(block="1A", street_name="BISHAN ST 11")
    assert ranked().blockCount == 2


def test_empty_result_has_no_groups():
    assert SearchController().group_by_block(SearchResult(query=SearchQuery())).blockGroups == []


# --- Results page -----------------------------------------------------------------------------

@pytest.mark.django_db
def test_results_show_a_block_card_and_a_flat_card(client, two_blocks):
    content = client.get(reverse("core:results"), {"view": "list", "w_bus_stop": 5}).content.decode()
    assert "4 flats in 2 blocks match your requirements" in content
    assert content.count("data-block-card=") == 1 and content.count("data-flat-card=") == 1
    assert f'data-flat-card="{two_blocks["b_only"].id}"' in content  # one sale keeps the flat card
    assert "3 matching flats" in content and "S$300,000 – S$700,000" in content
    assert f'href="{block_path("1A")}?' in content and "w_bus_stop=5" in content


@pytest.mark.django_db
def test_results_are_paginated_20_blocks_per_page(client):
    ResaleFlat.objects.bulk_create(
        [build_flat(block=str(i), resale_price=Decimal(300_000 + i)) for i in range(25) for _ in range(2)])
    first = client.get(reverse("core:results"))
    assert len(first.context["cards"]) == 20 and first.context["page"].paginator.num_pages == 2
    last = client.get(reverse("core:results"), {"page": 2})
    assert len(last.context["cards"]) == 5
    assert "Showing 21–25 of 25 blocks" in last.content.decode()


@pytest.mark.django_db
def test_map_view_side_list_uses_compact_block_cards(client, make_flat):
    make_flat(block="1A", latitude=1.37, longitude=103.85)
    make_flat(block="1A", latitude=1.37, longitude=103.85, resale_price=Decimal("600000"))
    content = client.get(reverse("core:results"), {"view": "map"}).content.decode()
    assert content.count("data-block-card=") == 1
    assert 'data-kind="block"' in content and 'data-price="520000" data-price-max="600000"' in content


# --- Block Results page -----------------------------------------------------------------------

@pytest.mark.django_db
def test_block_page_lists_only_matching_flats(client, two_blocks):
    response = client.get(block_path("1A"), {"max_budget": 600000})
    content = response.content.decode()
    assert response.status_code == 200
    assert "2 flats in this block match your search" in content
    # Default sort is Fit Score; with equal leases the cheaper flat scores higher.
    assert [card["flat"] for card in response.context["cards"]] == [two_blocks["a_cheap"], two_blocks["a_mid"]]
    assert f'data-flat-card="{two_blocks["a_dear"].id}"' not in content
    assert f'data-flat-card="{two_blocks["b_only"].id}"' not in content


@pytest.mark.django_db
def test_block_page_fit_scores_match_the_results_page(client, two_blocks):
    params = {"max_budget": 800000, "w_bus_stop": 5}
    results = client.get(reverse("core:results"), params).context["result"]
    cards = client.get(block_path("1A"), params).context["cards"]
    assert {c["flat"].id: c["fit"].total for c in cards} == {
        c["flat"].id: results.fitScores[c["flat"].id].total for c in cards}


@pytest.mark.django_db
def test_block_page_sort(client, two_blocks):
    response = client.get(block_path("1A"), {"sort": "price-desc"})
    assert [c["flat"] for c in response.context["cards"]] == [
        two_blocks["a_dear"], two_blocks["a_mid"], two_blocks["a_cheap"]]
    assert '<option value="price-desc" selected>' in response.content.decode()


@pytest.mark.django_db
def test_back_from_block_page_keeps_search_page_and_sort(client, two_blocks):
    response = client.get(block_path("1A"), {"max_budget": 800000, "page": 2, "sort": "price-asc"})
    assert response.context["back_url"] == reverse("core:results") + "?max_budget=800000&page=2&sort=price-asc"
    assert 'aria-label="View mode"' not in response.content.decode()  # no map here, so no toggle


@pytest.mark.django_db
def test_back_from_details_returns_to_the_block(client, two_blocks):
    content = client.get(block_path("1A"), {"max_budget": 800000}).content.decode()
    assert "from=block" in content
    flat = two_blocks["a_mid"]
    response = client.get(reverse("core:flat_details", args=[flat.id]), {"max_budget": 800000, "from": "block"})
    assert response.context["back_url"] == block_path("1A") + "?max_budget=800000"
    assert "Back to block" in response.content.decode()


@pytest.mark.django_db
def test_block_url_is_readable(two_blocks):
    assert block_path("1A") == f"/blocks/1A/{quote(STREET)}/"


@pytest.mark.django_db
def test_stale_block_link_shows_empty_state(client, two_blocks):
    response = client.get(block_path("1A"), {"max_budget": 100000})
    assert response.status_code == 200
    assert "No flats in this block match your search" in response.content.decode()


@pytest.mark.django_db
def test_unknown_block_is_404(client, two_blocks):
    assert client.get(block_path("999Z")).status_code == 404


@pytest.mark.django_db
def test_invalid_search_on_block_page(client, two_blocks):
    response = client.get(block_path("1A"), {"min_budget": "abc"})
    assert response.status_code == 400
    assert "Please check your search" in response.content.decode()
