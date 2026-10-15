"""
The five proximity categories used everywhere in FlatFinder (PLAN §1).

Bus Stops and MRT Stations are TransportNodes; the other three are Amenities.
Each entry ties together the names used by the models, FlatProximity, SearchQuery
weights and FitScore sub-scores, so other modules can loop over categories
instead of repeating the five names.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str              # used in URLs, JSON and map layer ids
    label: str            # shown in the UI
    model_name: str       # entity class name
    proximity_field: str  # FlatProximity column
    weight_field: str     # SearchQuery attribute
    score_field: str      # FitScore attribute
    short_label: str      # compact UI text, e.g. on result-card chips


CATEGORIES = (
    Category("bus_stop", "Bus Stops", "BusStop",
             "nearest_bus_stop_m", "busStopWeight", "busStopScore", "Bus stop"),
    Category("mrt_station", "MRT Stations", "MrtStation",
             "nearest_mrt_station_m", "mrtStationWeight", "mrtStationScore", "MRT"),
    Category("child_care_centre", "Child Care Centres", "ChildCareCentre",
             "nearest_child_care_centre_m", "childCareCentreWeight", "childCareCentreScore", "Child care"),
    Category("hawker_centre", "Hawker Centres", "HawkerCentre",
             "nearest_hawker_centre_m", "hawkerCentreWeight", "hawkerCentreScore", "Hawker"),
    Category("chas_clinic", "CHAS Clinics", "ChasClinic",
             "nearest_chas_clinic_m", "chasClinicWeight", "chasClinicScore", "CHAS clinic"),
)

CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}

# FR 1.1.2
FLAT_TYPES = (
    "1 ROOM", "2 ROOM", "3 ROOM", "4 ROOM", "5 ROOM", "EXECUTIVE", "MULTI-GENERATION",
)
