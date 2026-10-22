"""Phase 2: DataLoader commands and parsers (PLAN §3), run on small fixture files."""
import math
import shutil
from datetime import date
from io import StringIO
from pathlib import Path

import numpy as np
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from backend.core.services.distance import StraightLineDistance
from backend.core.models import (
    BusStop, ChasClinic, ChildCareCentre, FlatProximity, HawkerCentre, MrtStation, ResaleFlat, Town,
)
from backend.core.management.parsers import (
    area_weighted_centroid, months_back, parse_html_description, polygon_parts, remaining_lease_years,
    to_wgs84,
)

FIXTURES = Path(__file__).parent / "fixtures"


def run(command, *args, **kwargs):
    out = StringIO()
    call_command(command, *args, stdout=out, stderr=StringIO(), **kwargs)
    return out.getvalue()


def import_towns_and_flats():
    run("import_towns", path=FIXTURES / "towns_sample.geojson")
    run("import_flats", path=FIXTURES / "resale_sample.csv")


# --- Parsers -------------------------------------------------------------------

def test_parse_html_description():
    html = ("<table><tr><th>HCI_NAME</th> <td>Tan &amp; Lim Clinic</td></tr>"
            "<tr><th>POSTAL_CD</th><td>560123</td></tr><tr><th>BUILDING_NAME</th><td></td></tr></table>")
    assert parse_html_description(html) == {
        "HCI_NAME": "Tan & Lim Clinic", "POSTAL_CD": "560123", "BUILDING_NAME": ""}


def test_svy21_is_converted_and_wgs84_passes_through():
    # Commonwealth Crescent Market: SVY21 X/Y and WGS84 point from the same data.gov.sg record.
    lat, lng = to_wgs84(24332.82477688, 32135.91866726)
    assert lat == pytest.approx(1.3069001, abs=1e-5)
    assert lng == pytest.approx(103.8003673, abs=1e-5)
    assert to_wgs84(103.85, 1.37) == (1.37, 103.85)


def test_polygon_centroid_subtracts_holes():
    geometry = {"type": "Polygon", "coordinates": [
        [[0, 0], [6, 0], [6, 4], [0, 4], [0, 0]],
        [[0, 0], [0, 2], [3, 2], [3, 0], [0, 0]],
    ]}
    lat, lng = area_weighted_centroid(polygon_parts(geometry))
    assert (lng, lat) == (pytest.approx(3.5), pytest.approx(7 / 3))


def test_months_back_and_remaining_lease():
    assert months_back(date(2026, 10, 1), 12) == date(2025, 11, 1)
    assert months_back(date(2026, 1, 1), 1) == date(2026, 1, 1)
    assert remaining_lease_years(1980, date(2026, 1, 1)) == 53.0
    assert remaining_lease_years(1980, date(2026, 7, 2)) == pytest.approx(52.5, abs=0.01)


# --- import_towns ----------------------------------------------------------------

@pytest.mark.django_db
def test_import_towns_maps_planning_areas_and_is_rerunnable():
    run("import_towns", path=FIXTURES / "towns_sample.geojson")
    run("import_towns", path=FIXTURES / "towns_sample.geojson")
    towns = {t.name: t for t in Town.objects.all()}
    assert set(towns) == {"ANG MO KIO", "KALLANG/WHAMPOA", "CENTRAL AREA"}
    assert (towns["ANG MO KIO"].centroid_lat, towns["ANG MO KIO"].centroid_lng) == (
        pytest.approx(1.383333), pytest.approx(103.835))
    assert (towns["KALLANG/WHAMPOA"].centroid_lat, towns["KALLANG/WHAMPOA"].centroid_lng) == (
        pytest.approx(1.31), pytest.approx(103.86))
    # Downtown Core + Outram + Rochor, area-weighted.
    assert (towns["CENTRAL AREA"].centroid_lat, towns["CENTRAL AREA"].centroid_lng) == (
        pytest.approx(1.285), pytest.approx(103.8475))


@pytest.mark.django_db
def test_import_towns_logs_unmatched_planning_areas(caplog):
    with caplog.at_level("INFO", logger="core.import"):
        run("import_towns", path=FIXTURES / "towns_sample.geojson")
    assert "TUAS" in caplog.text


# --- import_flats ------------------------------------------------------------------

@pytest.mark.django_db
def test_import_flats_keeps_last_12_months():
    import_towns_and_flats()
    months = sorted(ResaleFlat.objects.values_list("month", flat=True))
    assert len(months) == 4
    assert months[0] == date(2025, 11, 1) and months[-1] == date(2026, 10, 1)


@pytest.mark.django_db
def test_import_flats_parses_fields():
    import_towns_and_flats()
    flat = ResaleFlat.objects.get(block="123")
    assert flat.street_name == "ANG MO KIO AVE 3"  # normalised from "ang mo kio  ave 3"
    assert flat.remaining_lease_raw == "53 years 10 months"
    assert flat.remaining_lease == remaining_lease_years(1980, date.today())
    assert flat.latitude is None and not flat.coords_approximate
    assert ResaleFlat.objects.get(block="1G").resale_price == 1500000


@pytest.mark.django_db
def test_import_flats_rerun_keeps_coordinates():
    import_towns_and_flats()
    ResaleFlat.objects.filter(block="123").update(latitude=1.369, longitude=103.845)
    run("import_flats", path=FIXTURES / "resale_sample.csv")
    assert ResaleFlat.objects.count() == 4
    assert ResaleFlat.objects.get(block="123").latitude == 1.369


@pytest.mark.django_db
def test_import_flats_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(CommandError, match="download_datasets"):
        run("import_flats", path=tmp_path / "nope.csv")


# --- import_transport / import_amenities --------------------------------------------

@pytest.mark.django_db
def test_import_transport():
    for _ in range(2):  # safe to re-run
        run("import_transport", bus_path=FIXTURES / "bus_stops_svy21_sample.geojson",
            mrt_path=FIXTURES / "mrt_exits_sample.geojson")
    assert BusStop.objects.count() == 2  # duplicate stop number dropped
    svy21_stop = BusStop.objects.get(stop_code="11111")
    assert svy21_stop.latitude == pytest.approx(1.3069, abs=1e-4)
    assert svy21_stop.longitude == pytest.approx(103.8004, abs=1e-4)
    assert svy21_stop.name == "Bus Stop 11111" and svy21_stop.type == "BUS"

    # Exact duplicate dropped; same label at a different point kept; station code mapped.
    assert MrtStation.objects.filter(name="ANG MO KIO MRT STATION").count() == 2
    paya_lebar = MrtStation.objects.get(name="PAYA LEBAR MRT STATION")
    assert paya_lebar.exit_code == "Exit E" and paya_lebar.type == "MRT"


@pytest.mark.django_db
def test_import_amenities():
    kwargs = dict(child_care_path=FIXTURES / "child_care_sample.geojson",
                  hawker_path=FIXTURES / "hawker_sample.geojson",
                  chas_path=FIXTURES / "chas_html_sample.geojson")
    run("import_amenities", **kwargs)
    run("import_amenities", **kwargs)

    centre = ChildCareCentre.objects.get()  # the row with NAME "None" is skipped
    assert (centre.name, centre.postal_code, centre.type) == ("SUNSHINE PLAYHOUSE", "560123", "CHILD_CARE")

    hawker = HawkerCentre.objects.get()  # "Under Construction" is skipped
    assert hawker.address == "628, Ang Mo Kio Avenue 4" and hawker.type == "HAWKER"

    clinic = ChasClinic.objects.get()
    assert clinic.name == "Acumed Medical Group & Partners"
    assert clinic.postal_code == "560123"
    assert clinic.address == "123, ANG MO KIO AVENUE 3, SINGAPORE 560123"
    assert (clinic.latitude, clinic.longitude, clinic.type) == (1.3695, 103.846, "CHAS")


# --- Coordinates contract (PLAN §3.3) -------------------------------------------------

@pytest.mark.django_db
def test_import_flat_coordinates():
    import_towns_and_flats()
    ResaleFlat.objects.filter(block="55").update(latitude=1.31, longitude=103.86, coords_approximate=True)
    output = run("import_flat_coordinates", str(FIXTURES / "coords_sample.csv"))

    amk = ResaleFlat.objects.get(block="123")
    assert (amk.latitude, amk.longitude, amk.coords_approximate) == (1.369, 103.845, False)
    kallang = ResaleFlat.objects.get(block="55")  # real coords replace the approximate ones
    assert (kallang.latitude, kallang.coords_approximate) == (1.324, False)
    assert ResaleFlat.objects.get(block="456").latitude is None  # swapped lat/lng rejected
    assert "2 flats at 2 addresses matched" in output
    assert "1 CSV addresses matched no flat" in output
    assert "1 rows had invalid coordinates" in output


@pytest.mark.django_db
def test_import_flat_coordinates_rejects_wrong_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    bad.write_text("blk,street,lat,lng\n1,A,1.3,103.8\n")
    with pytest.raises(CommandError, match="missing column"):
        run("import_flat_coordinates", str(bad))


@pytest.mark.django_db
def test_assign_approximate_coords_uses_town_centroid_only():
    import_towns_and_flats()
    ResaleFlat.objects.filter(block="123").update(latitude=1.369, longitude=103.845)
    run("assign_approximate_coords")

    real = ResaleFlat.objects.get(block="123")
    assert (real.latitude, real.coords_approximate) == (1.369, False)
    town = Town.objects.get(name="CENTRAL AREA")
    central = ResaleFlat.objects.get(block="1G")
    assert (central.latitude, central.longitude) == (town.centroid_lat, town.centroid_lng)  # no jitter
    assert central.coords_approximate
    assert not ResaleFlat.objects.filter(latitude__isnull=True).exists()


# --- compute_proximity ----------------------------------------------------------------

@pytest.mark.django_db
def test_compute_proximity():
    import_towns_and_flats()
    run("import_transport", bus_path=FIXTURES / "bus_stops_svy21_sample.geojson",
        mrt_path=FIXTURES / "mrt_exits_sample.geojson")
    run("import_amenities", child_care_path=FIXTURES / "child_care_sample.geojson",
        hawker_path=FIXTURES / "hawker_sample.geojson", chas_path=FIXTURES / "chas_html_sample.geojson")
    ResaleFlat.objects.filter(block="123").update(latitude=1.369, longitude=103.845)
    run("compute_proximity")
    run("compute_proximity")  # safe to re-run

    assert FlatProximity.objects.count() == ResaleFlat.objects.count()
    located = FlatProximity.objects.get(flat__block="123")
    strategy = StraightLineDistance()
    expected_mrt = min(strategy.distance_m((1.369, 103.845), (m.latitude, m.longitude))
                       for m in MrtStation.objects.all())
    assert located.nearest_mrt_station_m == pytest.approx(expected_mrt, abs=0.1)
    assert located.nearest_chas_clinic_m == pytest.approx(
        strategy.distance_m((1.369, 103.845), (1.3695, 103.846)), abs=0.1)

    unlocated = FlatProximity.objects.get(flat__block="55")
    assert unlocated.nearest_bus_stop_m is None and unlocated.nearest_chas_clinic_m is None


def test_kd_tree_matches_haversine():
    rng = np.random.default_rng(2006)
    origins = np.column_stack((rng.uniform(1.25, 1.45, 200), rng.uniform(103.6, 104.0, 200)))
    targets = np.column_stack((rng.uniform(1.25, 1.45, 300), rng.uniform(103.6, 104.0, 300)))
    strategy = StraightLineDistance()
    fast = strategy.nearest_m(origins, targets)
    slow = [min(strategy.distance_m(o, t) for t in targets) for o in origins]
    np.testing.assert_allclose(fast, slow, rtol=1e-9)
    assert math.isinf(strategy.nearest_m([(1.3, 103.8)], [])[0])


# --- load_all -----------------------------------------------------------------------

@pytest.mark.django_db
def test_load_all_runs_the_pipeline(tmp_path, settings):
    names = {
        "resale_sample.csv": "resale_flats.csv",
        "towns_sample.geojson": "town_boundaries.geojson",
        "mrt_exits_sample.geojson": "mrt_station_exits.geojson",
        "bus_stops_svy21_sample.geojson": "bus_stops.geojson",
        "child_care_sample.geojson": "child_care_centres.geojson",
        "hawker_sample.geojson": "hawker_centres.geojson",
        "chas_html_sample.geojson": "chas_clinics.geojson",
    }
    for source, target in names.items():
        shutil.copy(FIXTURES / source, tmp_path / target)
    settings.DATA_RAW_DIR = tmp_path

    output = run("load_all", "--no-download", "--coords", str(FIXTURES / "coords_sample.csv"))
    assert "Import complete." in output
    assert ResaleFlat.objects.count() == 4
    assert FlatProximity.objects.filter(nearest_bus_stop_m__isnull=False).count() == 2
