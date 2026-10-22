from datetime import date
from decimal import Decimal

import pytest

from backend.core.models import FlatProximity, ResaleFlat


def build_flat(proximity=None, **overrides):
    """An unsaved ResaleFlat with sensible defaults."""
    fields = dict(
        month=date(2026, 9, 1), town="ANG MO KIO", flat_type="4 ROOM", block="123",
        street_name="ANG MO KIO AVE 3", storey_range="07 TO 09", floor_area_sqm=92.0,
        flat_model="New Generation", lease_commence_date=1980, remaining_lease=54.0,
        remaining_lease_raw="54 years 02 months", resale_price=Decimal("520000"),
    )
    fields.update(overrides)
    return ResaleFlat(**fields)


@pytest.fixture
def make_flat(db):
    """Create a ResaleFlat and its FlatProximity row. `proximity` maps field -> metres."""
    def _make(proximity=None, **overrides):
        flat = build_flat(**overrides)
        flat.save()
        FlatProximity.objects.create(flat=flat, **(proximity or {}))
        return flat
    return _make
