"""
«Control» DistanceStrategy (new, approved in PLAN §8) and its two implementations.

Points are `(lat, lng)` tuples in WGS84 degrees; distances are metres.
"""
import math
from abc import ABC, abstractmethod

EARTH_RADIUS_M = 6_371_008.8  # mean Earth radius


def _unit_vectors(latlng):
    import numpy as np

    lat, lng = np.radians(latlng[:, 0]), np.radians(latlng[:, 1])
    return np.column_stack((np.cos(lat) * np.cos(lng), np.cos(lat) * np.sin(lng), np.sin(lat)))


class DistanceStrategy(ABC):
    """«Interface» DistanceStrategy — how the distance between two points is measured."""

    @abstractmethod
    def distance_m(self, origin, target) -> float:
        ...


class StraightLineDistance(DistanceStrategy):
    """
    Great-circle (haversine) distance. Used by `compute_proximity` and
    AmenityController (UC-11); amenity distances are straight-line estimates
    (SRS data dictionary, Amenity).
    """

    def distance_m(self, origin, target) -> float:
        lat1, lng1 = map(math.radians, origin)
        lat2, lng2 = map(math.radians, target)
        a = (math.sin((lat2 - lat1) / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
        return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))

    def nearest_m(self, origins, targets):
        """
        Distance from each origin to its nearest target, for many points at once
        (decision 9). Both are sequences of (lat, lng). Uses a KD-tree on 3-D unit
        vectors: the straight chord between unit vectors converts exactly to the
        great-circle distance. Returns a numpy array; all inf if there are no targets.
        """
        import numpy as np
        from scipy.spatial import cKDTree

        origins = np.asarray(origins, dtype=float).reshape(-1, 2)
        targets = np.asarray(targets, dtype=float).reshape(-1, 2)
        if len(targets) == 0:
            return np.full(len(origins), np.inf)
        chord, _ = cKDTree(_unit_vectors(targets)).query(_unit_vectors(origins), k=1)
        return 2 * EARTH_RADIUS_M * np.arcsin(np.clip(chord / 2, 0, 1))


class WalkingDistance(DistanceStrategy):
    """
    Walking distance along roads from the OneMap Routing API (UC-04, FR 1.2.1).
    Called only on demand, when the user selects an amenity pin. Raises OneMapError
    on failure (UC-04.EX.1 -> UC-06).
    """

    def __init__(self, gateway=None):
        self.gateway = gateway

    def distance_m(self, origin, target) -> float:
        raise NotImplementedError("Phase 7")
