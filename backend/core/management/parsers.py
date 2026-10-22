"""
Parsing helpers shared by the DataLoader commands (PLAN §3).

Pure functions, so they can be tested on the small files in tests/fixtures/.
"""
import html
import json
import re
from datetime import date
from functools import lru_cache

# --- GeoJSON -----------------------------------------------------------------

_HTML_ROW = re.compile(r"<th>\s*(.*?)\s*</th>\s*<td>\s*(.*?)\s*</td>", re.S | re.I)


def parse_html_description(description: str) -> dict:
    """
    Older data.gov.sg GeoJSON files keep their attributes in an HTML table inside a
    `Description` property. Returns {attribute: value}, with empty strings for blanks.
    """
    return {key.strip(): html.unescape(value).strip() for key, value in _HTML_ROW.findall(description or "")}


def feature_attributes(feature: dict) -> dict:
    """A feature's attributes, whichever of the two data.gov.sg formats it uses."""
    props = dict(feature.get("properties") or {})
    description = props.get("Description") or props.get("description")
    if description and "<table" in description.lower():
        props.update(parse_html_description(description))
    # data.gov.sg writes missing values as the string "None".
    return {k: ("" if v is None or v == "None" else v) for k, v in props.items()}


@lru_cache(maxsize=1)
def _svy21_transformer():
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:3414", "EPSG:4326", always_xy=True)


def to_wgs84(x: float, y: float) -> tuple:
    """
    Return (lat, lng). GeoJSON points are (lng, lat) in WGS84, but some LTA files use
    SVY21 (EPSG:3414) metres instead; those are detected by magnitude and converted.
    """
    if abs(x) > 180 or abs(y) > 90:
        lng, lat = _svy21_transformer().transform(x, y)
        return lat, lng
    return y, x


def iter_points(path):
    """Yield (attributes, lat, lng) for every Point feature in a GeoJSON file."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        x, y = geometry["coordinates"][:2]
        lat, lng = to_wgs84(float(x), float(y))
        yield feature_attributes(feature), lat, lng


# --- Polygons (town centroids) -------------------------------------------------

def _ring_area_centroid(ring):
    """Shoelace formula on (x, y) pairs: returns (unsigned area, cx, cy)."""
    a = cx = cy = 0.0
    for (x0, y0, *_), (x1, y1, *_) in zip(ring, ring[1:] + ring[:1]):
        cross = x0 * y1 - x1 * y0
        a += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if a == 0:
        return 0.0, 0.0, 0.0
    return abs(a) / 2, cx / (3 * a), cy / (3 * a)


def polygon_parts(geometry: dict) -> list:
    """List of (area, cx, cy) for a Polygon or MultiPolygon, with holes as negative area."""
    polygons = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    parts = []
    for rings in polygons:
        for i, ring in enumerate(rings):
            area, cx, cy = _ring_area_centroid(ring)
            parts.append((area if i == 0 else -area, cx, cy))
    return parts


def area_weighted_centroid(parts) -> tuple:
    """Combine (area, cx, cy) parts into one centroid. Returns (lat, lng) — inputs are (lng, lat)."""
    total = sum(a for a, _, _ in parts)
    cx = sum(a * x for a, x, _ in parts) / total
    cy = sum(a * y for a, _, y in parts) / total
    return to_wgs84(cx, cy)


# --- Resale flats ---------------------------------------------------------------

def parse_month(value: str) -> date:
    """'2026-10' -> date(2026, 10, 1)."""
    year, month = value.strip().split("-")
    return date(int(year), int(month), 1)


def months_back(latest: date, n: int) -> date:
    """First month of the n-month window ending at `latest` (inclusive)."""
    index = latest.year * 12 + (latest.month - 1) - (n - 1)
    return date(index // 12, index % 12 + 1, 1)


def remaining_lease_years(lease_commence_year: int, as_of: date) -> float:
    """
    PLAN §3.2: 99 − years since lease_commence_date, in decimal years as of `as_of`.
    The dataset gives only the commencement year, so the lease is taken to start on 1 January.
    """
    years_since = as_of.year - lease_commence_year + (as_of.timetuple().tm_yday - 1) / 365.25
    return round(99 - years_since, 2)


def normalise_address_part(value: str) -> str:
    """Upper-case, trimmed, single-spaced: used to match block and street names."""
    return " ".join(str(value).upper().split())
