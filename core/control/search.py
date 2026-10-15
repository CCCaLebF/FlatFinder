from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.db.models import Max, Min

from core.control.distance import EARTH_RADIUS_M
from core.entity import CATEGORIES, FitScore, ResaleFlat, SearchQuery, SearchResult, SortOrder

# Columns pulled for scoring, in one query joined to FlatProximity (PLAN §4, NFR 1).
_SCORE_COLUMNS = (
    ["id", "resale_price", "remaining_lease", "floor_area_sqm", "latitude", "longitude"]
    + [f"proximity__{c.proximity_field}" for c in CATEGORIES]
)


@dataclass(frozen=True)
class ScoreBounds:
    """
    Price and lease thresholds for the Fit Score. Taken from the SearchQuery, or from
    the filtered set when the user left the criterion blank (FR 1.1.6, PLAN §4).
    """

    minPrice: float
    maxPrice: float
    minLease: float


class SearchController:
    """
    «Control» SearchController — runs a search: filter, score, rank and sort.

    - UC-01 Search Resale Flats
    - UC-08 Filter Search Results (budget FR 1.1.1, flat types FR 1.1.2, lease FR 1.1.5,
      walk limits FR 1.1.3)
    - UC-09 Rank Search Results (Fit Score FR 2.2.2, PLAN §4)
    - UC-10 Sort Search Results (FR 2.2.3.3)
    - UC-07 Search via Search Bar (proximity anchor, decision 4)

    Filtering is separate from scoring (PLAN §4): hard filters run in SQL, then the
    remaining rows are scored together with numpy.
    """

    # --- UC-08 Filter --------------------------------------------------------------

    def filter_flats(self, query: SearchQuery):
        """UC-08: return a ResaleFlat queryset with the hard filters applied."""
        qs = ResaleFlat.objects.all()
        if query.minBudget is not None:
            qs = qs.filter(resale_price__gte=query.minBudget)
        if query.maxBudget is not None:
            qs = qs.filter(resale_price__lte=query.maxBudget)
        if query.flatTypes:
            qs = qs.filter(flat_type__in=query.flatTypes)
        if query.minRemainingLease is not None:
            qs = qs.filter(remaining_lease__gte=query.minRemainingLease)
        return self.apply_walk_limits(qs, query)

    def apply_walk_limits(self, qs, query: SearchQuery):
        """
        FR 1.1.3: apply the bus and MRT walking-distance sliders.

        OPEN DECISION (FR 1.1.3) — provisional (decision 3): a hard filter on the
        pre-computed straight-line distance to the nearest stop/exit in FlatProximity.
        Flats with no coordinates have no distance and are excluded while a limit is set.
        """
        if query.maxWalkBus is not None:
            qs = qs.filter(proximity__nearest_bus_stop_m__lte=query.maxWalkBus)
        if query.maxWalkMrt is not None:
            qs = qs.filter(proximity__nearest_mrt_station_m__lte=query.maxWalkMrt)
        return qs

    # --- UC-09 Rank ------------------------------------------------------------------

    def compute_bounds(self, query: SearchQuery, prices, leases) -> ScoreBounds:
        """FR 1.1.6: blank thresholds fall back to the filtered set's own range."""
        prices = np.asarray(prices, dtype=float)
        leases = np.asarray(leases, dtype=float)
        empty = prices.size == 0
        return ScoreBounds(
            minPrice=float(query.minBudget if query.minBudget is not None else (0 if empty else prices.min())),
            maxPrice=float(query.maxBudget if query.maxBudget is not None else (0 if empty else prices.max())),
            minLease=float(query.minRemainingLease if query.minRemainingLease is not None
                           else (0 if empty else leases.min())),
        )

    def bounds_for(self, query: SearchQuery) -> ScoreBounds:
        """
        The ScoreBounds rank_flats would use for this query, from a SQL min/max over the
        filtered set. Lets one flat (UC-02) be scored exactly as it is in the results list.
        """
        stats = self.filter_flats(query).aggregate(
            min_price=Min("resale_price"), max_price=Max("resale_price"), min_lease=Min("remaining_lease"))
        if stats["min_price"] is None:
            return self.compute_bounds(query, [], [])
        return self.compute_bounds(query, [stats["min_price"], stats["max_price"]], [stats["min_lease"]])

    def calculate_fit_score(self, flat: ResaleFlat, query: SearchQuery, bounds: ScoreBounds) -> FitScore:
        """UC-09 / FR 2.2.2: the FitScore of one flat, given the price/lease bounds."""
        proximity = getattr(flat, "proximity", None)
        distances = {c.key: np.array([getattr(proximity, c.proximity_field, None)], dtype=float)
                     for c in CATEGORIES}
        scores = self._score_arrays(
            query, bounds,
            prices=np.array([float(flat.resale_price)]),
            leases=np.array([flat.remaining_lease]),
            lats=np.array([flat.latitude], dtype=float),
            lngs=np.array([flat.longitude], dtype=float),
            distances=distances,
        )
        return self._fit_score_at(scores, 0)

    def rank_flats(self, qs, query: SearchQuery, bounds: ScoreBounds = None) -> SearchResult:
        """
        UC-09 / FR 2.2.3.2: score every filtered flat and order by Fit Score, descending.
        One query pulls the rows and their FlatProximity values; numpy does the scoring.
        Pass `bounds` to score a subset (e.g. the map's visible area) on the full
        filtered set's thresholds, so scores match the results list.
        """
        rows = list(qs.values_list(*_SCORE_COLUMNS))
        if not rows:
            return SearchResult(query=query)

        columns = list(zip(*rows))
        ids = np.array(columns[0], dtype=np.int64)
        prices = np.array(columns[1], dtype=float)
        leases = np.array(columns[2], dtype=float)
        areas = np.array(columns[3], dtype=float)
        lats = np.array(columns[4], dtype=float)
        lngs = np.array(columns[5], dtype=float)
        distances = {c.key: np.array(columns[6 + i], dtype=float) for i, c in enumerate(CATEGORIES)}

        bounds = bounds or self.compute_bounds(query, prices, leases)
        scores = self._score_arrays(query, bounds, prices, leases, lats, lngs, distances)

        result = SearchResult(query=query, bounds=bounds)
        result.baseIds = ids
        result.sortKeys = {"price": prices, "remaining_lease": leases,
                           "floor_area": areas, "fit_score": scores["total"]}
        result.fitScores = _FitScoreMap(ids, scores, self._fit_score_at)
        return self.sort_results(result, SortOrder())

    # --- UC-10 Sort ------------------------------------------------------------------

    def sort_results(self, result: SearchResult, order: SortOrder) -> SearchResult:
        """
        UC-10 / FR 2.2.3.3: reorder results by price, remaining lease, floor area or Fit
        Score. Only the display order changes. Ties fall back to Fit Score (descending),
        then price (ascending), so the order is stable.
        """
        result.sortOrder = order
        if result.baseIds is None or len(result.baseIds) == 0:
            return result
        keys = result.sortKeys
        primary = keys[order.field] if order.direction == "asc" else -keys[order.field]
        # np.lexsort sorts by the last key first.
        index = np.lexsort((keys["price"], -keys["fit_score"], primary))
        result.flatIds = [int(i) for i in result.baseIds[index]]
        return result

    # --- UC-07 Anchor ----------------------------------------------------------------

    def set_proximity_anchor(self, query: SearchQuery, text: str, gateway=None) -> bool:
        """
        UC-07: geocode a postal code or place name with OneMapSearchGateway and set it
        as the query's anchor. Returns False when there is no match (UC-07.EX.2).
        Raises OneMapError if OneMap fails (UC-07.EX.1 -> UC-06).
        """
        if gateway is None:
            from core.boundary.gateways.onemap import OneMapSearchGateway
            gateway = OneMapSearchGateway()
        found = gateway.geocode(text.strip())
        if found is None:
            return False
        query.setAnchor(*found)
        return True

    # --- The Fit Score formula (PLAN §4), vectorised ----------------------------------

    def _score_arrays(self, query, bounds, prices, leases, lats, lngs, distances) -> dict:
        """
        Every sub-score is 0–1:
          proximity_c = max(0, 1 − d_c / 1000); 0 with no node within 1 km or no coordinates
          price       = clamp((maxBudget − price) / (maxBudget − minBudget), 0, 1)
          lease       = clamp((remaining − minLease) / (99 − minLease), 0, 1)
          anchor      = max(0, 1 − d_anchor / ANCHOR_RADIUS_M), only when an anchor is set
          total       = round(100 × Σ(w_i × s_i) / Σ w_i, 1)
        A range of zero width gives a sub-score of 1.
        """
        fixed = settings.FIT_SCORE_FIXED_WEIGHTS
        radius = settings.AMENITY_RADIUS_M

        scores = {
            "price": _ratio(bounds.maxPrice - prices, bounds.maxPrice - bounds.minPrice),
            "lease": _ratio(leases - bounds.minLease, 99 - bounds.minLease),
        }
        weights = {"price": fixed["price"], "lease": fixed["lease"]}

        for key, weight in query.categoryWeights().items():
            scores[key] = _proximity(distances[key], radius)
            weights[key] = weight

        if query.hasAnchor:
            anchor_d = _haversine_m(lats, lngs, query.anchorLat, query.anchorLng)
            scores["anchor"] = _proximity(anchor_d, settings.ANCHOR_RADIUS_M)
            weights["anchor"] = query.anchorWeight or settings.DEFAULT_ANCHOR_WEIGHT

        weighted = sum(weights[k] * scores[k] for k in weights)
        scores["total"] = np.round(100 * weighted / sum(weights.values()), 1)
        return scores

    def _fit_score_at(self, scores: dict, i: int) -> FitScore:
        def value(key):
            return round(float(scores[key][i]), 3) if key in scores else None

        return FitScore(
            total=float(scores["total"][i]),
            priceScore=value("price"),
            leaseScore=value("lease"),
            anchorScore=value("anchor"),
            **{c.score_field: value(c.key) for c in CATEGORIES},
        )


class _FitScoreMap(Mapping):
    """flat id -> FitScore, built on first access: a page reads 20 of ~25k (NFR 1)."""

    def __init__(self, ids, scores, build):
        self._index = {int(fid): i for i, fid in enumerate(ids)}
        self._scores = scores
        self._build = build
        self._cache = {}

    def __getitem__(self, flat_id):
        if flat_id not in self._cache:
            self._cache[flat_id] = self._build(self._scores, self._index[flat_id])
        return self._cache[flat_id]

    def __iter__(self):
        return iter(self._index)

    def __len__(self):
        return len(self._index)


def _ratio(numerator, denominator):
    if denominator <= 0:
        return np.ones_like(numerator, dtype=float)
    return np.clip(numerator / denominator, 0, 1)


def _proximity(distance_m, radius_m):
    """max(0, 1 − d / radius); NaN (no coordinates / no node) scores 0."""
    return np.nan_to_num(np.clip(1 - distance_m / radius_m, 0, 1), nan=0.0)


def _haversine_m(lats, lngs, lat0, lng0):
    lat1, lng1 = np.radians(lats), np.radians(lngs)
    lat2, lng2 = np.radians(lat0), np.radians(lng0)
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))
