"""
DataLoader step 2 (PLAN §3.4): ResaleFlat rows from the resale CSV.

Keeps the transactions from the last 12 months, counted back from the latest
`month` in the file (decision 7). Truncates and reloads in one transaction, but
carries existing coordinates over by block and street, so re-running doesn't lose
the output of `import_flat_coordinates` (run `compute_proximity` again afterwards).
"""
import csv
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backend.core.models import ResaleFlat, Town
from backend.core.management.datasets import raw_path
from backend.core.management.parsers import (
    months_back, normalise_address_part, parse_month, remaining_lease_years,
)

WINDOW_MONTHS = 12


class Command(BaseCommand):
    help = "Import the last 12 months of HDB resale transactions as ResaleFlat rows."

    def add_arguments(self, parser):
        parser.add_argument("--path", help="CSV file (default: database/data/raw/resale_flats.csv).")

    def handle(self, *args, path=None, **options):
        path = path or raw_path("resale_flats")
        try:
            with open(path, encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
        except FileNotFoundError:
            raise CommandError(f"{path} not found. Run `manage.py download_datasets resale_flats` first.")
        if not rows:
            raise CommandError(f"{path} has no rows.")

        latest = max(parse_month(r["month"]) for r in rows)
        start = months_back(latest, WINDOW_MONTHS)
        today = date.today()

        flats = []
        for r in rows:
            month = parse_month(r["month"])
            if month < start:
                continue
            lease_year = int(r["lease_commence_date"])
            flats.append(ResaleFlat(
                month=month,
                town=r["town"].strip().upper(),
                flat_type=r["flat_type"].strip().upper(),
                block=r["block"].strip().upper(),
                street_name=normalise_address_part(r["street_name"]),
                storey_range=r["storey_range"].strip(),
                floor_area_sqm=float(r["floor_area_sqm"]),
                flat_model=r["flat_model"].strip(),
                lease_commence_date=lease_year,
                remaining_lease=remaining_lease_years(lease_year, today),
                remaining_lease_raw=(r.get("remaining_lease") or "").strip(),
                resale_price=Decimal(r["resale_price"]),
            ))

        with transaction.atomic():
            # Coordinates belong to an address, not a transaction: keep them across reloads.
            kept = {
                (block, street): (lat, lng, approx)
                for block, street, lat, lng, approx in ResaleFlat.objects.filter(latitude__isnull=False)
                .values_list("block", "street_name", "latitude", "longitude", "coords_approximate")
            }
            for flat in flats:
                coords = kept.get((flat.block, flat.street_name))
                if coords:
                    flat.latitude, flat.longitude, flat.coords_approximate = coords
            ResaleFlat.objects.all().delete()
            ResaleFlat.objects.bulk_create(flats, batch_size=2000)

        no_town = sorted({f.town for f in flats} - set(Town.objects.values_list("name", flat=True)))
        if no_town:
            self.stderr.write(self.style.WARNING(
                f"Towns with no centroid (add them to import_towns): {', '.join(no_town)}"))

        with_coords = sum(1 for f in flats if f.latitude is not None)
        self.stdout.write(self.style.SUCCESS(
            f"Flats: {len(flats):,} transactions from {start:%Y-%m} to {latest:%Y-%m} "
            f"({len(rows):,} rows in file); {with_coords:,} kept their coordinates. "
            f"Run `manage.py compute_proximity` again before searching."))
