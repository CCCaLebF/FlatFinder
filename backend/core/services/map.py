from django.db.models import Count

from backend.core.services.search import SearchController
from backend.core.models import SearchQuery, Town

FLATS_PER_LOCATION = 10  # flats listed in one pin's popup; the rest are counted


class MapController:
    """
    «Control» MapController — supplies map data for UC-03 Display Interactive Map.

    - FR 2.1.1: flat counts per town when zoomed out (decision 8)
    - FR 2.1.2 / FR 2.2.1: matching flats as pins when zoomed in

    Has no rendering methods (approved change, PLAN §8); rendering is MapUI's job.
    """

    def __init__(self, search: SearchController = None):
        self.search = search or SearchController()

    def get_area_counts(self, query: SearchQuery) -> list:
        """FR 2.1.1: `[{town, lat, lng, count}]`, one entry per town centroid, by town name."""
        counts = (self.search.filter_flats(query).order_by()
                  .values("town").annotate(count=Count("id")))
        towns = Town.objects.in_bulk(field_name="name")
        areas = [
            {"town": row["town"], "lat": towns[row["town"]].centroid_lat,
             "lng": towns[row["town"]].centroid_lng, "count": row["count"]}
            for row in counts if row["town"] in towns
        ]
        return sorted(areas, key=lambda a: a["town"])

    def get_pins_in_view(self, bounds, query: SearchQuery, limit: int = 500, with_scores: bool = True) -> dict:
        """
        FR 2.1.2: matching flats with coordinates inside `bounds` (south, west, north, east).

        Flats at the same coordinates (several sales in one block, or every flat in a
        town while coordinates are approximate) share one location pin. Locations are
        ordered by their best Fit Score and capped at `limit`. Each pin carries only what
        drawing it needs (count, best Fit Score and that flat's price); its popup list comes
        from get_flats_at_location when opened, which keeps this response small and fast.
        Scores use the whole filtered set's thresholds, so they match the results list.
        """
        south, west, north, east = bounds
        filtered = self.search.filter_flats(query)
        in_view = filtered.filter(latitude__gte=south, latitude__lte=north,
                                  longitude__gte=west, longitude__lte=east)
        result = self.search.rank_flats(in_view, query, bounds=self.search.bounds_for(query))

        rows = {row[0]: row[1:] for row in in_view.values_list(
            "id", "latitude", "longitude", "coords_approximate", "resale_price")}

        locations = {}
        for flat_id in result.flatIds:  # best Fit Score first
            lat, lng, approximate, price = rows[flat_id]
            key = (round(lat, 6), round(lng, 6))
            location = locations.get(key)
            if location is None:
                if len(locations) >= limit:
                    continue
                location = locations[key] = {
                    "id": flat_id,  # the best flat here; its details page shows the whole block
                    "lat": lat, "lng": lng, "approximate": approximate, "count": 0,
                    "fit": result.fitScores[flat_id].total if with_scores else None,  # the best flat's
                    "price": float(price),
                }
            location["count"] += 1

        shown = sum(loc["count"] for loc in locations.values())
        return {"locations": list(locations.values()), "total": result.count, "truncated": shown < result.count}

    def get_flats_at_location(self, lat: float, lng: float, query: SearchQuery, with_scores: bool = True) -> dict:
        """
        One pin's popup list: the matching flats at exactly (lat, lng), best Fit Score first,
        up to FLATS_PER_LOCATION, plus how many there are. Scored on the whole filtered set's
        thresholds, as on the pin itself and in the results list.
        """
        here = self.search.filter_flats(query).filter(latitude=lat, longitude=lng)
        result = self.search.rank_flats(here, query, bounds=self.search.bounds_for(query))
        listed = result.flatIds[:FLATS_PER_LOCATION]
        rows = {row["id"]: row for row in here.filter(id__in=listed).values(
            "id", "block", "street_name", "flat_type", "storey_range", "floor_area_sqm",
            "resale_price", "coords_approximate")}
        return {
            "count": result.count,
            "approximate": bool(listed) and rows[listed[0]]["coords_approximate"],
            "flats": [_pin_flat(rows[fid], result.fitScores[fid].total if with_scores else None) for fid in listed],
        }


def _pin_flat(row, fit):
    return {
        "id": row["id"],
        "block": row["block"],
        "street": row["street_name"],
        "flatType": row["flat_type"],
        "storey": row["storey_range"],
        "area": row["floor_area_sqm"],
        "price": float(row["resale_price"]),
        "fit": fit,
    }


def flats_as_pins(flats) -> list:
    """Saved/bookmarked flats as single-flat pins (UC-03.AC.1). Flats without coordinates are skipped."""
    return [
        {"id": f.id, "lat": f.latitude, "lng": f.longitude, "approximate": f.coords_approximate,
         "block": f.block, "street": f.street_name, "flatType": f.flat_type,
         "price": float(f.resale_price)}
        for f in flats if f.has_coords
    ]
