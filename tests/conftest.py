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


@pytest.fixture
def lab4_flats(make_flat):
    """
    Lab 4 shared fixture (docs/testing/Lab4_Test_Design.md). Against the baseline search
    (min $350k, max $700k, [4 ROOM], lease >= 80) only A matches; B-E each fail one criterion.
    """
    near = {"nearest_bus_stop_m": 80, "nearest_mrt_station_m": 500}
    spec = {
        "A": ("4 ROOM", "600000", 90.0),
        "B": ("4 ROOM", "250000", 85.0),  # fails min budget only
        "C": ("4 ROOM", "900000", 95.0),  # fails max budget only
        "D": ("5 ROOM", "500000", 85.0),  # fails flat type only
        "E": ("4 ROOM", "400000", 70.0),  # fails min lease only
    }
    return {
        name: make_flat(proximity=near, block=f"10{i}", flat_type=flat_type, resale_price=Decimal(price),
                        remaining_lease=lease, latitude=1.35 + i / 1000, longitude=103.85)
        for i, (name, (flat_type, price, lease)) in enumerate(spec.items())
    }
