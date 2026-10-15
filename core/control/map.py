from core.entity import SearchQuery


class MapController:
    """
    «Control» MapController — supplies map data for UC-03 Display Interactive Map.

    - FR 2.1.1: flat counts per town when zoomed out (decision 8)
    - FR 2.1.2 / FR 2.2.1: matching flats as pins when zoomed in

    Has no rendering methods (approved change, PLAN §8); rendering is MapUI's job.
    """

    def get_area_counts(self, query: SearchQuery) -> list:
        """FR 2.1.1: `[{town, lat, lng, count}]`, one entry per town centroid."""
        raise NotImplementedError("Phase 6")

    def get_pins_in_view(self, bounds, query: SearchQuery, limit: int = 500) -> list:
        """FR 2.1.2: matching flats with coordinates inside the map bounds."""
        raise NotImplementedError("Phase 6")
