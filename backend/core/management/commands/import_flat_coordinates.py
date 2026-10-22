"""
DataLoader step 5 (PLAN §3.3, decision 6): real flat coordinates from a team-supplied CSV.

CSV contract — columns `block,street_name,latitude,longitude`, WGS84 decimal degrees.
Rows match flats on normalised (upper-case, trimmed, single-spaced) block and street name.
Matched flats get coords_approximate=False. Run `compute_proximity` afterwards.
"""
import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backend.core.models import ResaleFlat
from backend.core.management.parsers import normalise_address_part

REQUIRED_COLUMNS = {"block", "street_name", "latitude", "longitude"}
# Generous bounding box around Singapore, to catch swapped or projected coordinates.
SG_BOUNDS = {"lat": (1.15, 1.48), "lng": (103.6, 104.1)}


class Command(BaseCommand):
    help = "Load flat coordinates from a CSV with columns block,street_name,latitude,longitude."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")

    def handle(self, *args, csv_path, **options):
        try:
            with open(csv_path, encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
                if missing:
                    raise CommandError(f"CSV is missing column(s): {', '.join(sorted(missing))}")
                rows = list(reader)
        except FileNotFoundError:
            raise CommandError(f"{csv_path} not found.")

        coords, invalid = {}, 0
        for row in rows:
            try:
                lat, lng = float(row["latitude"]), float(row["longitude"])
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not (SG_BOUNDS["lat"][0] <= lat <= SG_BOUNDS["lat"][1]
                    and SG_BOUNDS["lng"][0] <= lng <= SG_BOUNDS["lng"][1]):
                invalid += 1
                continue
            key = (normalise_address_part(row["block"]), normalise_address_part(row["street_name"]))
            coords[key] = (lat, lng)

        addresses = set(ResaleFlat.objects.values_list("block", "street_name"))
        matched_addresses = addresses & coords.keys()
        with transaction.atomic():
            flats_updated = 0
            for block, street in matched_addresses:
                lat, lng = coords[(block, street)]
                flats_updated += ResaleFlat.objects.filter(block=block, street_name=street).update(
                    latitude=lat, longitude=lng, coords_approximate=False)

        unmatched_rows = len(coords) - len(matched_addresses)
        still_missing = ResaleFlat.objects.filter(latitude__isnull=True).count()
        self.stdout.write(self.style.SUCCESS(
            f"Coordinates: {flats_updated:,} flats at {len(matched_addresses):,} addresses matched. "
            f"{unmatched_rows:,} CSV addresses matched no flat; {invalid:,} rows had invalid coordinates; "
            f"{len(addresses - coords.keys()):,} flat addresses had no CSV row ({still_missing:,} flats still "
            f"without coordinates). Run `manage.py compute_proximity` next."))
