"""
DataLoader step 1 (PLAN §3.4): Town centroids from the planning-area boundaries.

The boundary file uses URA planning-area names; resale flats use HDB town names.
TOWN_TO_PLANNING_AREAS maps each resale town to the planning area(s) whose combined
area-weighted centroid becomes Town.centroid_lat/lng (FR 2.1.1, decision 8).
"""
import json
import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.entity import Town
from core.management.datasets import raw_path
from core.management.parsers import area_weighted_centroid, polygon_parts

logger = logging.getLogger("core.import")

# Resale towns whose name isn't a planning-area name. Every other resale town
# maps to the planning area of the same name.
TOWN_TO_PLANNING_AREAS = {
    "KALLANG/WHAMPOA": ["KALLANG"],
    # The URA Central Area also covers Marina South/East and Straits View, which are
    # reclaimed land with no HDB blocks; these three hold the Central Area's HDB flats.
    "CENTRAL AREA": ["DOWNTOWN CORE", "OUTRAM", "ROCHOR"],
}

# Resale towns in the dataset (2017 onwards).
RESALE_TOWNS = [
    "ANG MO KIO", "BEDOK", "BISHAN", "BUKIT BATOK", "BUKIT MERAH", "BUKIT PANJANG",
    "BUKIT TIMAH", "CENTRAL AREA", "CHOA CHU KANG", "CLEMENTI", "GEYLANG", "HOUGANG",
    "JURONG EAST", "JURONG WEST", "KALLANG/WHAMPOA", "MARINE PARADE", "PASIR RIS",
    "PUNGGOL", "QUEENSTOWN", "SEMBAWANG", "SENGKANG", "SERANGOON", "TAMPINES",
    "TOA PAYOH", "WOODLANDS", "YISHUN",
]


class Command(BaseCommand):
    help = "Import Town centroids from the planning-area boundary GeoJSON."

    def add_arguments(self, parser):
        parser.add_argument("--path", help="GeoJSON file (default: data/raw/town_boundaries.geojson).")

    def handle(self, *args, path=None, **options):
        path = path or raw_path("towns")
        try:
            with open(path, encoding="utf-8") as fh:
                features = json.load(fh)["features"]
        except FileNotFoundError:
            raise CommandError(f"{path} not found. Run `manage.py download_datasets towns` first.")

        areas = {}
        for feature in features:
            name = (feature["properties"].get("PLN_AREA_N") or "").strip().upper()
            areas.setdefault(name, []).extend(polygon_parts(feature["geometry"]))

        used = set()
        with transaction.atomic():
            for town in RESALE_TOWNS:
                area_names = TOWN_TO_PLANNING_AREAS.get(town, [town])
                missing = [a for a in area_names if a not in areas]
                if missing:
                    logger.warning("Town %s: planning area(s) %s not in boundary file; skipped", town, missing)
                    continue
                used.update(area_names)
                lat, lng = area_weighted_centroid([p for a in area_names for p in areas[a]])
                Town.objects.update_or_create(name=town, defaults={"centroid_lat": lat, "centroid_lng": lng})

        unmatched = sorted(set(areas) - used)
        logger.info("Planning areas with no resale town (ignored): %s", ", ".join(unmatched))
        self.stdout.write(self.style.SUCCESS(
            f"Towns: {Town.objects.count()} imported; {len(unmatched)} planning areas have no resale town."))
