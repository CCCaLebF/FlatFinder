"""
«Entity» layer as models: Django models (database tables) and plain dataclasses.

MapState is the one entity that lives client-side, in frontend/static/js/mapstate.js (UC-13).
"""
from .amenity import Amenity, ChasClinic, ChildCareCentre, HawkerCentre
from .bookmark import Bookmark
from .categories import CATEGORIES, CATEGORY_BY_KEY, FLAT_TYPES, Category
from .flat import ResaleFlat
from .proximity import FlatProximity
from .query import SearchQuery, SortOrder
from .results import FitScore, SearchResult
from .town import Town
from .transport import BusStop, MrtStation, TransportNode

__all__ = [
    "Amenity", "ChasClinic", "ChildCareCentre", "HawkerCentre",
    "Bookmark",
    "CATEGORIES", "CATEGORY_BY_KEY", "FLAT_TYPES", "Category",
    "ResaleFlat", "FlatProximity", "Town",
    "SearchQuery", "SortOrder", "FitScore", "SearchResult",
    "BusStop", "MrtStation", "TransportNode",
]
