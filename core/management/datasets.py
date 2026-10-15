"""The data.gov.sg datasets FlatFinder imports (PLAN §3.1), and where they live in data/raw/."""
from pathlib import Path

from django.conf import settings

# key -> (data.gov.sg dataset id, file name in data/raw/)
DATASETS = {
    "resale_flats": ("d_8b84c4ee58e3cfc0ece0d773c8ca6abc", "resale_flats.csv"),
    "towns": ("d_2cc750190544007400b2cfd5d7f53209", "town_boundaries.geojson"),
    "mrt_exits": ("d_b39d3a0871985372d7e1637193335da5", "mrt_station_exits.geojson"),
    "bus_stops": ("d_3f172c6feb3f4f92a2f47d93eed2908a", "bus_stops.geojson"),
    "child_care": ("d_5d668e3f544335f8028f546827b773b4", "child_care_centres.geojson"),
    "hawker_centres": ("d_4a086da0a5553be1d89383cd90d07ecd", "hawker_centres.geojson"),
    "chas_clinics": ("d_548c33ea2d99e29ec63a7cc9edcccedc", "chas_clinics.geojson"),
}


def raw_path(key: str) -> Path:
    return Path(settings.DATA_RAW_DIR) / DATASETS[key][1]
