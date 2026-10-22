"""
DataLoader step 6 (PLAN §3.4): FlatProximity — straight-line distance from every flat
to the nearest node of each of the five categories, via StraightLineDistance.nearest_m.

Every flat gets a row; flats without coordinates get nulls (their proximity sub-scores
are 0). Run again whenever coordinates or amenities change.
"""
import math

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db import transaction

from backend.core.services.distance import StraightLineDistance
from backend.core.models import CATEGORIES, FlatProximity, ResaleFlat


class Command(BaseCommand):
    help = "Pre-compute nearest-node distances for every flat (FlatProximity)."

    def handle(self, *args, **options):
        strategy = StraightLineDistance()
        flats = list(ResaleFlat.objects.values_list("id", "latitude", "longitude"))
        located = [(fid, lat, lng) for fid, lat, lng in flats if lat is not None and lng is not None]
        origins = [(lat, lng) for _, lat, lng in located]

        distances = {}  # proximity field -> array aligned with `located`
        for category in CATEGORIES:
            model = apps.get_model("core", category.model_name)
            targets = list(model.objects.values_list("latitude", "longitude"))
            distances[category.proximity_field] = strategy.nearest_m(origins, targets)
            if not targets:
                self.stderr.write(self.style.WARNING(f"No {category.label} imported; distances left empty."))

        rows = {fid: FlatProximity(flat_id=fid) for fid, _, _ in flats}
        for i, (fid, _, _) in enumerate(located):
            for field, values in distances.items():
                value = float(values[i])
                setattr(rows[fid], field, round(value, 1) if math.isfinite(value) else None)

        with transaction.atomic():
            FlatProximity.objects.all().delete()
            FlatProximity.objects.bulk_create(rows.values(), batch_size=2000)

        self.stdout.write(self.style.SUCCESS(
            f"Proximity: {len(rows):,} flats ({len(located):,} with coordinates, "
            f"{len(rows) - len(located):,} without)."))
