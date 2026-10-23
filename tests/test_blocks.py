"""PLAN §11: results grouped by block, and the block-level flat details page."""
from decimal import Decimal

import pytest
from django.urls import reverse

from backend.core.models import ResaleFlat, SearchQuery, SearchResult, SortOrder
from backend.core.services.search import SearchController
from tests.conftest import build_flat

STREET = "ANG MO KIO AVE 3"  # the fixture's default street


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
    assert f'/flats/{two_blocks["a_cheap"].id}/?' in content  # block card opens its best-fit flat's details
    assert f'/flats/{two_blocks["b_only"].id}/?' in content  # single-flat card opens its own details
    assert "View details" in content and "View block" not in content
    assert "w_bus_stop=5" in content and "from=results" in content
    # Change 11: block cards and single-flat cards share the inline house drawing.
    assert content.count("data-block-house") == 2
    assert 'aria-label="View details at Blk 1A' in content  # change 7: block-card overlay
    assert 'aria-label="View details for Blk 2B' in content  # change 7: single-flat-card overlay


@pytest.mark.django_db
def test_single_flat_block_shows_the_same_house(client, make_flat):
    flat = make_flat(block="4D")
    content = client.get(reverse("core:results"), {"view": "list"}).content.decode()
    assert content.count("data-flat-card=") == 1
    assert content.count("data-block-house") == 1
    assert f'/flats/{flat.id}/?' in content  # Phase F: single-flat cards open the flat details page


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
    assert 'data-storey="storeys 07 to 09"' in content  # change 2: focus popup carries the storey range
    # Change 7: the compact card also carries a whole-card overlay, with the actions above it.
    assert 'aria-label="View details at Blk 1A' in content
    assert "View flats" not in content
    assert 'class="relative z-20' in content  # "Show on map" stays clickable above the overlay


@pytest.mark.django_db
def test_compact_flat_card_is_fully_clickable(client, make_flat):
    flat = make_flat(block="3C", latitude=1.37, longitude=103.85)
    content = client.get(reverse("core:results"), {"view": "map"}).content.decode()
    assert 'aria-label="View details for Blk 3C' in content
    assert f'/flats/{flat.id}/?' in content
    assert "Show on map" in content
    assert 'data-summary="4 Room"' in content and 'data-storey="storey 07 to 09"' in content


@pytest.mark.django_db
def test_block_focus_lists_every_storey_range(client, make_flat):
    make_flat(block="5E", storey_range="01 TO 03", latitude=1.37, longitude=103.85)
    make_flat(block="5E", storey_range="04 TO 06", latitude=1.37, longitude=103.85)
    content = client.get(reverse("core:results"), {"view": "map"}).content.decode()
    assert 'data-storey="storeys 01 to 03, 04 to 06"' in content
