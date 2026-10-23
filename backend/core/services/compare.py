"""
«Control» CompareController (the session tray) and the Compare Score (Phase H).

The Compare Score is a weight-adjustable cousin of the Fit Score. When a search is present it
reuses the Fit Score's exact normalisation (budget-based price, `(remaining − minLease)/(99 −
minLease)` for lease) and its fixed price/lease weights, so the default Compare total equals the
Fit Score. Floor area is a new factor that defaults to ignored. Without a search, price, lease
and floor area use absolute reference scales (not min–max), so a small difference stays a small
score difference; every factor defaults to 5.
"""
from django.conf import settings

from backend.core.models import CATEGORIES
from backend.core.services.distance import StraightLineDistance


FACTOR_LABELS = {
    "price": "Price",
    "lease": "Remaining lease",
    "area": "Floor area",
    "anchor": "Search location",
    **{c.key: c.label for c in CATEGORIES},
}

FACTOR_ORDER = ("price", "lease", "area") + tuple(c.key for c in CATEGORIES) + ("anchor",)

# factor key -> the GET parameter that overrides its weight on the compare page (0 = ignore).
WEIGHT_PARAMS = {
    "price": "cw_price",
    "lease": "cw_lease",
    "area": "cw_area",
    "anchor": "cw_anchor",
    **{c.key: f"cw_{c.key}" for c in CATEGORIES},
}


class CompareController:
    """«Control» CompareController — a session tray of up to 3 flat ids (Phase H)."""

    SESSION_KEY = "compare_ids"
    MAX = 3

    def ids(self, session) -> list:
        ids = [int(i) for i in session.get(self.SESSION_KEY, [])]
        return ids[: self.MAX]

    def contains(self, session, flat_id) -> bool:
        return int(flat_id) in self.ids(session)

    def toggle(self, session, flat_id) -> bool:
        """Add the flat, or remove it if present. Returns the new "added" state."""
        flat_id = int(flat_id)
        ids = self.ids(session)
        if flat_id in ids:
            session[self.SESSION_KEY] = [i for i in ids if i != flat_id]
            session.modified = True
            return False
        if len(ids) >= self.MAX:
            return False
        ids.append(flat_id)
        session[self.SESSION_KEY] = ids
        session.modified = True
        return True

    def clear(self, session) -> None:
        if self.SESSION_KEY in session:
            del session[self.SESSION_KEY]
            session.modified = True


def default_weights(query):
    """Factor -> weight (0 = ignore). Mirrors the Fit Score exactly when a search is present."""
    weights = {
        "price": settings.FIT_SCORE_FIXED_WEIGHTS["price"],
        "lease": settings.FIT_SCORE_FIXED_WEIGHTS["lease"],
        "area": 0,  # new factor: off by default so Compare matches the Fit Score
    }
    for category in CATEGORIES:
        if query is None:
            weights[category.key] = 5
        else:
            value = getattr(query, category.weight_field)
            weights[category.key] = value if value is not None else 0
    if query is not None and query.hasAnchor:
        weights["anchor"] = query.anchorWeight or settings.DEFAULT_ANCHOR_WEIGHT
    return weights


def parse_weights(params, query) -> dict:
    """Weights from the cw_* slider params (1–10) and their cw_*_off "ignore" flags."""
    weights = default_weights(query)
    for key, param in WEIGHT_PARAMS.items():
        if f"{param}_off" in params:
            weights[key] = 0  # ignored
        elif param in params:
            try:
                value = int(params.get(param))
            except (TypeError, ValueError):
                continue
            weights[key] = max(1, min(10, value))
    return weights


def weight_param_names() -> list:
    """All cw_* GET params (slider values + their _off flags), for hidden-query exclusions."""
    names = list(WEIGHT_PARAMS.values())
    return names + [f"{n}_off" for n in names]


def compare_homes(flats, query=None, bounds=None, weights=None) -> dict:
    """
    Score each flat and return the comparison table data:

    {"factors": [...], "rows": [...], "homes": [...], "winner": home|None}
    """
    weights = dict(weights if weights is not None else default_weights(query))
    has_search = query is not None and bounds is not None

    def clamp01(value):
        return max(0.0, min(1.0, value))

    def score_price(flat):
        if has_search:
            denom = bounds.maxPrice - bounds.minPrice
            return 1.0 if denom <= 0 else clamp01((bounds.maxPrice - float(flat.resale_price)) / denom)
        return clamp01(1 - float(flat.resale_price) / settings.COMPARE_PRICE_REF_MAX)

    def score_lease(flat):
        if has_search:
            denom = 99 - bounds.minLease
            return 1.0 if denom <= 0 else clamp01((float(flat.remaining_lease) - bounds.minLease) / denom)
        return clamp01(float(flat.remaining_lease) / 99)

    def score_area(flat):
        return clamp01(float(flat.floor_area_sqm) / settings.COMPARE_AREA_REF_MAX_M2)

    def score_amenity(flat, field):
        metres = getattr(flat.proximity, field, None)
        if metres is None:
            return 0.0
        return clamp01(1 - metres / settings.AMENITY_RADIUS_M)

    def score_anchor(flat):
        if not flat.has_coords:
            return 0.0
        dist = StraightLineDistance().distance_m(
            (flat.latitude, flat.longitude), (query.anchorLat, query.anchorLng))
        return clamp01(1 - dist / settings.ANCHOR_RADIUS_M)

    score_fns = {"price": score_price, "lease": score_lease, "area": score_area, "anchor": score_anchor}
    for category in CATEGORIES:
        score_fns[category.key] = (lambda flat, field=category.proximity_field: score_amenity(flat, field))

    active = [key for key in FACTOR_ORDER if weights.get(key, 0) > 0]

    homes = []
    for flat in flats:
        scores = {}
        for key in FACTOR_ORDER:
            if key not in weights:
                continue
            if key == "anchor" and not (query is not None and query.hasAnchor):
                scores[key] = None
            else:
                scores[key] = score_fns[key](flat)
        homes.append({"flat": flat, "scores": scores, "points": {}, "total": None})

    total_weight = sum(weights[k] for k in active)
    for home in homes:
        points = {}
        for key in active:
            score = home["scores"].get(key)
            if score is None or total_weight == 0:
                points[key] = None
            else:
                points[key] = 100 * weights[key] * score / total_weight
        home["points"] = points
        if total_weight > 0:
            home["total"] = round(sum(p for p in points.values() if p is not None), 1)

    factors = [
        {
            "key": key,
            "label": FACTOR_LABELS[key],
            "higher_is_better": key != "price",
            "weight": weights.get(key, 0),
        }
        for key in FACTOR_ORDER if key in weights
    ]

    rows = [
        {
            "factor": factor,
            "cells": [
                {"score": home["scores"].get(factor["key"]), "points": home["points"].get(factor["key"])}
                for home in homes
            ],
        }
        for factor in factors if factor["weight"] > 0
    ]

    winner_index = _winner_index(homes)
    if winner_index is not None:
        homes[winner_index]["is_winner"] = True
    winner = homes[winner_index] if winner_index is not None else None

    return {"factors": factors, "rows": rows, "homes": homes, "winner": winner}


def _winner_index(homes):
    """Highest total; ties break to the cheaper flat, then the longer lease."""
    if not homes or any(h["total"] is None for h in homes):
        return None

    def key(index):
        home = homes[index]
        flat = home["flat"]
        return (home["total"], -float(flat.resale_price), float(flat.remaining_lease))

    return max(range(len(homes)), key=key)
