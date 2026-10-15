class AmenityController:
    """
    «Control» AmenityController — UC-11 Find Nearest Amenity (FR 2.3.1–2.3.5).

    Queries our database, never OneMap (decision 5): a bounding-box query on the
    latitude/longitude indexes, then StraightLineDistance (haversine).
    """

    def find_nearest_amenities(self, flat, radius_m: int = 1000) -> dict:
        """
        Amenities and transport nodes within `radius_m` of the flat, grouped by
        category key and sorted by distance. MRT exits are collapsed to one entry
        per station name.
        """
        raise NotImplementedError("Phase 5")
