"""
«Boundary» OneMap gateways (PLAN §5).

Every gateway uses a 5 s timeout and raises OneMapError on a timeout or a non-2xx
response, which ErrorHandler turns into the UC-06 banner. Credentials come from
ONEMAP_EMAIL / ONEMAP_PASSWORD in `.env`; the token never reaches the browser.

MapGateway (the base-map tile URL and attribution) is configuration only:
settings.MAP_TILE_URL and settings.MAP_TILE_ATTRIBUTION, passed to MapUI.
"""


class OneMapError(Exception):
    """A OneMap call failed: timeout, network error or non-2xx response (UC-06)."""

    def __init__(self, endpoint: str, code=None, message: str = ""):
        self.endpoint = endpoint
        self.code = code
        super().__init__(message or f"OneMap request to {endpoint} failed ({code})")


class OneMapTokenProvider:
    """
    Shared token helper: fetches an access token with the account credentials,
    caches it and refreshes it before it expires.
    """

    def get_token(self) -> str:
        raise NotImplementedError("Phase 7")


class OneMapSearchGateway:
    """«Boundary» OneMapSearchGateway — geocodes search-bar text (UC-07, FR 1.1.7 anchor)."""

    def geocode(self, text: str):
        """Return `(lat, lng, label)` for the best match, or None if nothing matches."""
        raise NotImplementedError("Phase 7")


class OneMapRoutingGateway:
    """«Boundary» OneMapRoutingGateway — walking routes (UC-04, FR 1.2.1)."""

    def walking_distance_m(self, origin, destination) -> float:
        """Walking distance in metres between two `(lat, lng)` points (routeType=walk)."""
        raise NotImplementedError("Phase 7")
