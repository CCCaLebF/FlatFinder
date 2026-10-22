"""
DataLoader step 3 (PLAN §3.4): BusStop and MrtStation rows from the LTA GeoJSON files.

The MRT file has one row per exit; each exit becomes one MrtStation row so distances
use the nearest exit (PLAN §3.1). LRT stations are included as rail stations.
Truncates and reloads in one transaction.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from backend.core.models import BusStop, MrtStation
from backend.core.management.datasets import raw_path
from backend.core.management.parsers import iter_points

# A few exits carry a station code instead of a name.
MRT_CODE_NAMES = {
    "CC9": "PAYA LEBAR MRT STATION",
    "CC30": "KEPPEL MRT STATION",
    "CC31": "CANTONMENT MRT STATION",
    "CC32": "PRINCE EDWARD ROAD MRT STATION",
    "DT4": "HILLVIEW MRT STATION",
    "DT18": "TELOK AYER MRT STATION",
    "NE18": "PUNGGOL COAST MRT STATION",
}


def mrt_station_name(raw: str) -> str:
    name = " ".join(raw.upper().split())
    return MRT_CODE_NAMES.get(name, name)


def mrt_exit_code(raw: str) -> str:
    """'Exit A' stays; a bare 'A' or '1' becomes 'Exit A' / 'Exit 1'."""
    code = " ".join(raw.split())
    if code and not code.lower().startswith("exit"):
        code = f"Exit {code}"
    return code


class Command(BaseCommand):
    help = "Import bus stops and MRT/LRT station exits."

    def add_arguments(self, parser):
        parser.add_argument("--bus-path", help="Bus stop GeoJSON (default: database/data/raw/bus_stops.geojson).")
        parser.add_argument("--mrt-path", help="MRT exit GeoJSON (default: database/data/raw/mrt_station_exits.geojson).")

    def handle(self, *args, bus_path=None, mrt_path=None, **options):
        bus_path = bus_path or raw_path("bus_stops")
        mrt_path = mrt_path or raw_path("mrt_exits")
        try:
            bus_points = list(iter_points(bus_path))
            mrt_points = list(iter_points(mrt_path))
        except FileNotFoundError as exc:
            raise CommandError(f"{exc.filename} not found. Run `manage.py download_datasets` first.")

        bus_stops = {}
        for attrs, lat, lng in bus_points:
            code = str(attrs.get("BUS_STOP_NUM", "")).strip()
            if not code or code in bus_stops:
                continue
            # The dataset has no stop names; the stop number is what is printed on the pole.
            bus_stops[code] = BusStop(stop_code=code, name=f"Bus Stop {code}", type=BusStop.BUS,
                                      latitude=lat, longitude=lng)

        exits = {}
        for attrs, lat, lng in mrt_points:
            name = mrt_station_name(attrs.get("STATION_NA", ""))
            exit_code = mrt_exit_code(attrs.get("EXIT_CODE", ""))
            key = (name, exit_code, round(lat, 6), round(lng, 6))  # drop exact duplicates only
            if name and key not in exits:
                exits[key] = MrtStation(name=name, exit_code=exit_code, type=MrtStation.MRT,
                                        latitude=lat, longitude=lng)

        with transaction.atomic():
            BusStop.objects.all().delete()
            MrtStation.objects.all().delete()
            BusStop.objects.bulk_create(bus_stops.values(), batch_size=2000)
            MrtStation.objects.bulk_create(exits.values(), batch_size=2000)

        stations = len({e.name for e in exits.values()})
        self.stdout.write(self.style.SUCCESS(
            f"Transport: {len(bus_stops):,} bus stops; {len(exits):,} exits at {stations} MRT/LRT stations."))
