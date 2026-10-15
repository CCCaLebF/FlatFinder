import math
from dataclasses import dataclass

from django.apps import apps
from django.conf import settings

from core.control.distance import StraightLineDistance
from core.entity import CATEGORIES


@dataclass
class NearbyAmenity:
    """One amenity or transport node near a flat, with its straight-line distance (UC-11)."""

    category: str      # Category.key
    id: int
    name: str
    latitude: float
    longitude: float
    distance_m: float
    detail: str = ""   # exit code, stop number or address


class AmenityController:
    """
    «Control» AmenityController — UC-11 Find Nearest Amenity (FR 2.3.1–2.3.5).

    Queries our database, never OneMap (decision 5): a bounding-box query on the
    latitude/longitude indexes, then StraightLineDistance (haversine).
    """

    def __init__(self, distance=None):
        self.distance = distance or StraightLineDistance()

    def find_nearest_amenities(self, flat, radius_m: int = None) -> dict:
        """
        Amenities and transport nodes within `radius_m` (default 1 km) of the flat,
        as {category key: [NearbyAmenity, ...]} in CATEGORIES order, each list sorted
        by distance. MRT exits are collapsed to one entry per station name (its nearest
        exit). Returns {} when the flat has no coordinates.
        """
        if not flat.has_coords:
            return {}
        radius_m = radius_m or settings.AMENITY_RADIUS_M
        origin = (flat.latitude, flat.longitude)
        box = _bounding_box(flat.latitude, flat.longitude, radius_m)

        nearby = {}
        for category in CATEGORIES:
            model = apps.get_model("core", category.model_name)
            found = []
            for node in model.objects.filter(**box):
                metres = self.distance.distance_m(origin, (node.latitude, node.longitude))
                if metres <= radius_m:
                    found.append(NearbyAmenity(category.key, node.pk, node.name, node.latitude,
                                               node.longitude, round(metres), _detail(node)))
            found.sort(key=lambda a: (a.distance_m, a.name))
            if category.key == "mrt_station":
                found = _one_per_station(found)
            nearby[category.key] = found
        return nearby


def _bounding_box(lat, lng, radius_m):
    """A lat/lng box that contains the circle, so the indexed filter does the coarse work."""
    dlat = math.degrees(radius_m / 6_371_008.8)
    dlng = dlat / max(math.cos(math.radians(lat)), 1e-6)
    return {"latitude__gte": lat - dlat, "latitude__lte": lat + dlat,
            "longitude__gte": lng - dlng, "longitude__lte": lng + dlng}


def _detail(node):
    if getattr(node, "exit_code", ""):
        return f"Nearest exit: {node.exit_code}"
    return getattr(node, "address", "") or ""  # bus stops: the name already is the stop number


def _one_per_station(exits):
    """Keep each station's nearest exit (the list is already sorted by distance)."""
    seen, stations = set(), []
    for exit_ in exits:
        if exit_.name not in seen:
            seen.add(exit_.name)
            stations.append(exit_)
    return stations
