"""
«Boundary» OneMap gateways (PLAN §5).

Every gateway uses a 5 s timeout and raises OneMapError on a timeout, a network error or
a non-2xx response, which ErrorHandler turns into the UC-06 banner. Credentials come from
ONEMAP_EMAIL / ONEMAP_PASSWORD in `.env`; the token never reaches the browser.

Checked against the live API (Phase 7): search needs no token; routing needs one, sent
as the raw value of the Authorization header. Tokens last 3 days.

MapGateway (the base-map tile URL and attribution) is configuration only:
settings.MAP_TILE_URL and settings.MAP_TILE_ATTRIBUTION, passed to MapUI.
"""
import threading
import time

import requests
from django.conf import settings

TOKEN_PATH = "/api/auth/post/getToken"
SEARCH_PATH = "/api/common/elastic/search"
ROUTE_PATH = "/api/public/routingsvc/route"
REFRESH_MARGIN_S = 3600  # fetch a new token an hour before the old one expires


class OneMapError(Exception):
    """A OneMap call failed: timeout, network error, bad response or non-2xx status (UC-06)."""

    def __init__(self, endpoint: str, code=None, message: str = ""):
        self.endpoint = endpoint
        self.code = code
        super().__init__(message or f"OneMap request to {endpoint} failed ({code})")


def _call(method, path, *, params=None, json=None, headers=None):
    """One HTTP call to OneMap. Returns the decoded JSON body or raises OneMapError."""
    url = settings.ONEMAP_BASE_URL + path
    try:
        response = requests.request(method, url, params=params, json=json, headers=headers,
                                    timeout=settings.ONEMAP_TIMEOUT_S)
    except requests.Timeout:
        raise OneMapError(path, "timeout", f"OneMap {path} timed out")
    except requests.RequestException as exc:
        raise OneMapError(path, "network", f"OneMap {path} unreachable: {exc.__class__.__name__}")
    if not 200 <= response.status_code < 300:
        raise OneMapError(path, response.status_code)
    try:
        return response.json()
    except ValueError:
        raise OneMapError(path, "bad-response", f"OneMap {path} returned non-JSON")


class OneMapTokenProvider:
    """
    Shared token helper: fetches an access token with the account credentials, caches it
    and refreshes it before it expires. One instance is shared by the whole process.
    """

    def __init__(self):
        self._token = None
        self._expires_at = 0.0
        self._lock = threading.Lock()

    def get_token(self) -> str:
        with self._lock:
            if self._token and self._expires_at - time.time() > REFRESH_MARGIN_S:
                return self._token
            email, password = settings.ONEMAP_EMAIL, settings.ONEMAP_PASSWORD
            if not email or not password:
                raise OneMapError(TOKEN_PATH, "no-credentials",
                                  "ONEMAP_EMAIL and ONEMAP_PASSWORD are not set in .env")
            body = _call("POST", TOKEN_PATH, json={"email": email, "password": password})
            token = body.get("access_token")
            if not token:
                raise OneMapError(TOKEN_PATH, "bad-response", "OneMap returned no access token")
            self._token = token
            self._expires_at = float(body.get("expiry_timestamp") or time.time() + 3 * 86400)
            return self._token

    def invalidate(self) -> None:
        """Forget the cached token, e.g. after OneMap rejects it with 401."""
        with self._lock:
            self._token, self._expires_at = None, 0.0


token_provider = OneMapTokenProvider()


class OneMapSearchGateway:
    """«Boundary» OneMapSearchGateway — geocodes search-bar text (UC-07, FR 1.1.7 anchor)."""

    def geocode(self, text: str):
        """Return `(lat, lng, label)` for the best match, or None if nothing matches."""
        body = _call("GET", SEARCH_PATH, params={
            "searchVal": text, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1})
        results = body.get("results") or []
        if not body.get("found") or not results:
            return None
        best = results[0]
        try:
            lat, lng = float(best["LATITUDE"]), float(best["LONGITUDE"])
        except (KeyError, TypeError, ValueError):
            raise OneMapError(SEARCH_PATH, "bad-response", "OneMap search result has no coordinates")
        return lat, lng, _label(best)

    def search_addresses(self, text: str) -> list[dict]:
        """Raw results (page 1) for an address search; [] when nothing matches."""
        body = _call("GET", SEARCH_PATH, params={
            "searchVal": text, "returnGeom": "Y", "getAddrDetails": "Y", "pageNum": 1})
        if not body.get("found"):
            return []
        return list(body.get("results") or [])


class OneMapRoutingGateway:
    """«Boundary» OneMapRoutingGateway — walking routes (UC-04, FR 1.2.1)."""

    def __init__(self, tokens: OneMapTokenProvider = None):
        self.tokens = tokens or token_provider

    def walking_route(self, origin, destination) -> dict:
        """{"metres", "seconds", "route_geometry"} for a walk between two `(lat, lng)` points."""
        params = {"start": f"{origin[0]},{origin[1]}", "end": f"{destination[0]},{destination[1]}",
                  "routeType": "walk"}
        try:
            body = _call("GET", ROUTE_PATH, params=params, headers={"Authorization": self.tokens.get_token()})
        except OneMapError as exc:
            if exc.code != 401:
                raise
            self.tokens.invalidate()  # expired or revoked: one retry with a fresh token
            body = _call("GET", ROUTE_PATH, params=params, headers={"Authorization": self.tokens.get_token()})
        summary = body.get("route_summary") or {}
        if "total_distance" not in summary:
            raise OneMapError(ROUTE_PATH, "no-route", body.get("status_message") or "OneMap found no walking route")
        return {
            "metres": float(summary["total_distance"]),
            "seconds": float(summary.get("total_time") or 0),
            "route_geometry": body.get("route_geometry"),
        }

    def walking_distance_m(self, origin, destination) -> float:
        """Walking distance in metres between two `(lat, lng)` points (routeType=walk)."""
        return self.walking_route(origin, destination)["metres"]


def _label(result: dict) -> str:
    """A short name for a search result: the building, else the address."""
    building = (result.get("BUILDING") or "").strip()
    if building and building.upper() != "NIL":
        return building
    return (result.get("ADDRESS") or result.get("SEARCHVAL") or "Selected location").strip()
