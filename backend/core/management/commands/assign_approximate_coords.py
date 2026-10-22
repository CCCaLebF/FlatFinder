"""
DataLoader step 5, development fallback only (PLAN §3.3). Opt-in.

Gives every flat without coordinates its town's centroid and sets
coords_approximate=True; the UI then shows "Approximate location (town centre)".
No jitter and no other invented coordinates (PLAN §8).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from backend.core.models import ResaleFlat, Town


class Command(BaseCommand):
    help = "DEV ONLY: place flats without coordinates at their town centroid (coords_approximate=True)."

    def handle(self, *args, **options):
        updated = 0
        with transaction.atomic():
            for town in Town.objects.all():
                updated += ResaleFlat.objects.filter(town=town.name, latitude__isnull=True).update(
                    latitude=town.centroid_lat, longitude=town.centroid_lng, coords_approximate=True)
        remaining = ResaleFlat.objects.filter(latitude__isnull=True).count()
        self.stdout.write(self.style.WARNING(
            f"Approximate coordinates: {updated:,} flats placed at their town centre; "
            f"{remaining:,} still without coordinates. Run `manage.py compute_proximity` next."))
