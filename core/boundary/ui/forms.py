"""
«Boundary» SearchUI form — turns the sidebar's GET parameters into a SearchQuery.

All search state lives in the URL (PLAN §6). Each slider has an "off" checkbox:
"Ignore" for weights, "No limit" for walk limits, "Any" for the minimum lease.
A slider that is off — or missing from the URL — means the criterion is blank,
i.e. unconstrained (FR 1.1.6). The JS disables an off slider so it isn't submitted,
but the server also honours the checkbox, so the form works without JS.
"""
from django import forms
from django.conf import settings

from core.entity import CATEGORIES, FLAT_TYPES, SearchQuery, SortOrder

WALK_MIN_M, WALK_MAX_M, WALK_STEP_M = 100, 2000, 50
LEASE_MIN, LEASE_MAX = 20, 95

# UC-10 sort control: the `sort` URL parameter is "<SortOrder.field>-<SortOrder.direction>".
SORT_OPTIONS = [
    ("fit_score-desc", "Fit Score: highest first"),
    ("fit_score-asc", "Fit Score: lowest first"),
    ("price-asc", "Price: lowest first"),
    ("price-desc", "Price: highest first"),
    ("remaining_lease-desc", "Remaining lease: longest first"),
    ("remaining_lease-asc", "Remaining lease: shortest first"),
    ("floor_area-desc", "Floor area: largest first"),
    ("floor_area-asc", "Floor area: smallest first"),
]


def parse_sort_order(value) -> SortOrder:
    """`price-asc` -> SortOrder("price", "asc"). Anything unknown gives the default (FR 2.2.3.2)."""
    field, _, direction = (value or "").rpartition("-")
    try:
        return SortOrder(field, direction)
    except ValueError:
        return SortOrder()


def sort_param(order: SortOrder) -> str:
    return f"{order.field}-{order.direction}"


# Slider positions shown when the user hasn't set a value yet.
DEFAULTS = {
    "max_walk_bus": 400,
    "max_walk_mrt": 800,
    "min_lease": 60,
    "weight": 5,
}


class SearchForm(forms.Form):
    min_budget = forms.IntegerField(required=False, min_value=0, max_value=10_000_000)   # FR 1.1.1
    max_budget = forms.IntegerField(required=False, min_value=0, max_value=10_000_000)
    flat_type = forms.MultipleChoiceField(                                                # FR 1.1.2
        required=False, choices=[(t, t.title()) for t in FLAT_TYPES])
    min_lease = forms.FloatField(required=False, min_value=0, max_value=99)              # FR 1.1.5
    lease_any = forms.BooleanField(required=False)
    max_walk_bus = forms.IntegerField(required=False, min_value=WALK_MIN_M, max_value=WALK_MAX_M)  # FR 1.1.3.1
    bus_any = forms.BooleanField(required=False)
    max_walk_mrt = forms.IntegerField(required=False, min_value=WALK_MIN_M, max_value=WALK_MAX_M)  # FR 1.1.3.2
    mrt_any = forms.BooleanField(required=False)
    # UC-07 anchor (decision 4); set by the search bar in phase 7.
    anchor_lat = forms.FloatField(required=False, min_value=-90, max_value=90)
    anchor_lng = forms.FloatField(required=False, min_value=-180, max_value=180)
    anchor_label = forms.CharField(required=False, max_length=200)
    w_anchor = forms.IntegerField(required=False, min_value=settings.WEIGHT_MIN, max_value=settings.WEIGHT_MAX)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for category in CATEGORIES:  # FR 1.1.4: a 1–10 weight per category, or ignored
            self.fields[f"w_{category.key}"] = forms.IntegerField(
                required=False, min_value=settings.WEIGHT_MIN, max_value=settings.WEIGHT_MAX)
            self.fields[f"ignore_{category.key}"] = forms.BooleanField(required=False)

    def clean(self):
        data = super().clean()
        low, high = data.get("min_budget"), data.get("max_budget")
        if low is not None and high is not None and low > high:
            self.add_error("max_budget", "Maximum budget must be at least the minimum budget.")
        return data

    def _value(self, name, off_flag=None):
        """A cleaned value, or None if it's blank or its "off" checkbox is ticked."""
        if off_flag and self.cleaned_data.get(off_flag):
            return None
        return self.cleaned_data.get(name)

    def to_query(self) -> SearchQuery:
        """Build the SearchQuery. Call only after is_valid()."""
        query = SearchQuery(
            minBudget=self._value("min_budget"),
            maxBudget=self._value("max_budget"),
            flatTypes=list(self.cleaned_data.get("flat_type") or []),
            maxWalkBus=self._value("max_walk_bus", "bus_any"),
            maxWalkMrt=self._value("max_walk_mrt", "mrt_any"),
            minRemainingLease=self._value("min_lease", "lease_any"),
            anchorWeight=self._value("w_anchor"),
        )
        for category in CATEGORIES:
            setattr(query, category.weight_field, self._value(f"w_{category.key}", f"ignore_{category.key}"))
        lat, lng = self._value("anchor_lat"), self._value("anchor_lng")
        if lat is not None and lng is not None:
            query.setAnchor(lat, lng, self._value("anchor_label") or "Selected location")
        return query

    # --- What the sidebar template needs ------------------------------------------------

    def sidebar_state(self) -> dict:
        """
        Values for every sidebar control. With no search yet (an empty GET), the
        defaults are: weights on at 5, walk limits off, lease off.
        """
        raw = self.data if self.is_bound else {}
        # Other parameters (view, page, sort) don't count as a search.
        fresh = not any(name in raw for name in self.fields)
        data = self.cleaned_data if hasattr(self, "cleaned_data") else {}

        def number(name, default):
            value = data.get(name)
            if value is None:
                try:
                    value = float(raw.get(name))
                except (TypeError, ValueError):
                    value = default
            return int(value) if float(value).is_integer() else value

        def is_off(flag, value_name, default_off):
            if fresh:
                return default_off
            return bool(data.get(flag) or raw.get(flag)) or raw.get(value_name) in (None, "")

        return {
            "min_budget": raw.get("min_budget", ""),
            "max_budget": raw.get("max_budget", ""),
            "flat_types": [
                {"value": t, "label": t.title(), "checked": t in (raw.getlist("flat_type") if raw else [])}
                for t in FLAT_TYPES
            ],
            "lease": {"value": number("min_lease", DEFAULTS["min_lease"]),
                      "off": is_off("lease_any", "min_lease", True),
                      "min": LEASE_MIN, "max": LEASE_MAX},
            "walks": [
                {"name": "max_walk_bus", "flag": "bus_any", "label": "Bus stop",
                 "value": number("max_walk_bus", DEFAULTS["max_walk_bus"]),
                 "off": is_off("bus_any", "max_walk_bus", True)},
                {"name": "max_walk_mrt", "flag": "mrt_any", "label": "MRT station",
                 "value": number("max_walk_mrt", DEFAULTS["max_walk_mrt"]),
                 "off": is_off("mrt_any", "max_walk_mrt", True)},
            ],
            "walk_range": {"min": WALK_MIN_M, "max": WALK_MAX_M, "step": WALK_STEP_M},
            "weights": [
                {"name": f"w_{c.key}", "flag": f"ignore_{c.key}", "label": c.label,
                 "value": number(f"w_{c.key}", DEFAULTS["weight"]),
                 "off": is_off(f"ignore_{c.key}", f"w_{c.key}", False)}
                for c in CATEGORIES
            ],
            "weight_range": {"min": settings.WEIGHT_MIN, "max": settings.WEIGHT_MAX},
            "anchor": {key: raw.get(key, "") for key in ("anchor_lat", "anchor_lng", "anchor_label", "w_anchor")},
        }
