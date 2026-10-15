"""
«Entity» SearchQuery and SortOrder — plain dataclasses, not database tables.

Attribute names follow the class diagram (camelCase) so they stay traceable.
"""
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

from .categories import CATEGORIES


@dataclass
class SearchQuery:
    """
    «Entity» SearchQuery — the filters and preferences set in the sidebar (UC-01, UC-08, UC-09).

    Built from GET parameters so Back, refresh and links keep the search (PLAN §6).
    Any criterion left as None is unconstrained (FR 1.1.6).

    - minBudget / maxBudget: SGD budget range (FR 1.1.1)
    - flatTypes: selected flat types; empty means all (FR 1.1.2)
    - maxWalkBus / maxWalkMrt: walking-distance sliders in metres (FR 1.1.3.1, 1.1.3.2).
      How they apply is an OPEN DECISION (decision 3); see SearchController.apply_walk_limits.
    - minRemainingLease: years (FR 1.1.5)
    - five 1–10 importance weights, None = ignored (FR 1.1.4, decision 1)
    - anchorLat / anchorLng / anchorLabel / anchorWeight: search-bar proximity anchor
      geocoded through OneMap (UC-07, decision 4)
    """

    minBudget: Optional[int] = None
    maxBudget: Optional[int] = None
    flatTypes: list = field(default_factory=list)
    maxWalkBus: Optional[int] = None
    maxWalkMrt: Optional[int] = None
    minRemainingLease: Optional[float] = None
    busStopWeight: Optional[int] = None
    mrtStationWeight: Optional[int] = None
    childCareCentreWeight: Optional[int] = None
    hawkerCentreWeight: Optional[int] = None
    chasClinicWeight: Optional[int] = None
    anchorLat: Optional[float] = None
    anchorLng: Optional[float] = None
    anchorLabel: Optional[str] = None
    anchorWeight: Optional[int] = None

    def isUnconstrained(self, field_name: str) -> bool:
        """FR 1.1.6: a criterion left blank is treated as unconstrained."""
        value = getattr(self, field_name)
        return value is None or value == [] or value == ""

    def setAnchor(self, lat: float, lng: float, label: str) -> None:
        """UC-07: store the geocoded search-bar location as the proximity anchor."""
        self.anchorLat = lat
        self.anchorLng = lng
        self.anchorLabel = label
        if self.anchorWeight is None:
            self.anchorWeight = settings.DEFAULT_ANCHOR_WEIGHT

    @property
    def hasAnchor(self) -> bool:
        return self.anchorLat is not None and self.anchorLng is not None

    def categoryWeights(self) -> dict:
        """Category key -> weight, for categories the user did not leave blank."""
        weights = {}
        for category in CATEGORIES:
            weight = getattr(self, category.weight_field)
            if weight is not None:
                weights[category.key] = weight
        return weights


@dataclass(frozen=True)
class SortOrder:
    """
    «Entity» SortOrder — field and direction for reordering results (UC-10, FR 2.2.3.3).

    Changes only the displayed order, never which flats are returned or their scores.
    Default is Fit Score, descending (FR 2.2.3.2, decision 12).
    """

    FIELDS = ("price", "remaining_lease", "floor_area", "fit_score")
    DIRECTIONS = ("asc", "desc")

    field: str = "fit_score"
    direction: str = "desc"

    def __post_init__(self):
        if self.field not in self.FIELDS:
            raise ValueError(f"Unknown sort field: {self.field!r}")
        if self.direction not in self.DIRECTIONS:
            raise ValueError(f"Unknown sort direction: {self.direction!r}")
