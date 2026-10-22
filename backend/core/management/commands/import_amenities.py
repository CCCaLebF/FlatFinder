"""
DataLoader step 4 (PLAN §3.4): ChildCareCentre, HawkerCentre and ChasClinic rows.

Each source has its own attribute names; the CHAS file keeps them in an HTML
`Description` table (handled by parsers.feature_attributes). Truncates and reloads
each model in one transaction.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backend.core.models import CATEGORIES, ChasClinic, ChildCareCentre, HawkerCentre
from backend.core.management.datasets import raw_path
from backend.core.management.parsers import iter_points

HAWKER_EXCLUDED_STATUSES = {"UNDER CONSTRUCTION"}


def _join(*parts):
    return ", ".join(p.strip() for p in parts if p and p.strip())


def child_care_fields(a):
    # ADDRESSSTREETNAME already holds the full address, e.g. "44, LIMAU GARDEN, ..., SINGAPORE 467903".
    return dict(name=a.get("NAME", ""), postal_code=a.get("ADDRESSPOSTALCODE", ""),
                address=a.get("ADDRESSSTREETNAME", ""))


def hawker_fields(a):
    if a.get("STATUS", "").strip().upper() in HAWKER_EXCLUDED_STATUSES:
        return None
    address = a.get("ADDRESS_MYENV") or _join(a.get("ADDRESSBLOCKHOUSENUMBER"), a.get("ADDRESSSTREETNAME"))
    return dict(name=a.get("NAME", ""), postal_code=a.get("ADDRESSPOSTALCODE", ""), address=address)


def chas_fields(a):
    building = a.get("BUILDING_NAME", "")
    address = _join(a.get("BLK_HSE_NO"), a.get("STREET_NAME"), building,
                    f"SINGAPORE {a['POSTAL_CD']}" if a.get("POSTAL_CD") else "")
    return dict(name=a.get("HCI_NAME", ""), postal_code=a.get("POSTAL_CD", ""), address=address)


SOURCES = [
    # (model, dataset key, attribute mapper)
    (ChildCareCentre, "child_care", child_care_fields),
    (HawkerCentre, "hawker_centres", hawker_fields),
    (ChasClinic, "chas_clinics", chas_fields),
]


class Command(BaseCommand):
    help = "Import child care centres, hawker centres and CHAS clinics."

    def add_arguments(self, parser):
        parser.add_argument("--child-care-path")
        parser.add_argument("--hawker-path")
        parser.add_argument("--chas-path")

    def handle(self, *args, **options):
        overrides = {"child_care": options.get("child_care_path"),
                     "hawker_centres": options.get("hawker_path"),
                     "chas_clinics": options.get("chas_path")}
        loaded = []
        for model, key, mapper in SOURCES:
            path = overrides[key] or raw_path(key)
            try:
                points = list(iter_points(path))
            except FileNotFoundError:
                raise CommandError(f"{path} not found. Run `manage.py download_datasets {key}` first.")
            rows, skipped = [], 0
            for attrs, lat, lng in points:
                fields = mapper(attrs)
                if not fields or not fields["name"]:
                    skipped += 1
                    continue
                fields["name"] = fields["name"].strip()
                fields["postal_code"] = str(fields["postal_code"]).strip()[:6]
                rows.append(model(type=model.TYPE_VALUE, latitude=lat, longitude=lng, **fields))
            loaded.append((model, rows, skipped))

        with transaction.atomic():
            for model, rows, _ in loaded:
                model.objects.all().delete()
                model.objects.bulk_create(rows, batch_size=2000)

        labels = {c.model_name: c.label for c in CATEGORIES}
        for model, rows, skipped in loaded:
            self.stdout.write(self.style.SUCCESS(
                f"{labels[model.__name__]}: {len(rows):,} imported, {skipped} skipped."))
