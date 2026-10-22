"""«Entity» FitScore and SearchResult — plain dataclasses, not database tables."""
from dataclasses import dataclass, field
from typing import Optional

from .query import SearchQuery, SortOrder


@dataclass
class FitScore:
    """
    «Entity» FitScore — how well one flat matches the current SearchQuery (FR 2.2.2, UC-09).

    `total` is 0–100 (one decimal place); every sub-score is 0–1. A category sub-score
    is None when the user left that category blank, and `anchorScore` is None when no
    anchor is set. The details page shows this breakdown (UC-02). Formula: PLAN §4.
    """

    total: float
    priceScore: float
    leaseScore: float
    busStopScore: Optional[float] = None
    mrtStationScore: Optional[float] = None
    childCareCentreScore: Optional[float] = None
    hawkerCentreScore: Optional[float] = None
    chasClinicScore: Optional[float] = None
    anchorScore: Optional[float] = None


@dataclass
class SearchResult:
    """
    «Entity» SearchResult — the flats returned for a SearchQuery and their Fit Scores
    (UC-01).

    - flatIds: ResaleFlat ids in display order (the page loads only the flats it shows)
    - fitScores: flat id -> FitScore
    - sortOrder: the current SortOrder; sorting (UC-10) reorders flatIds only
    - bounds: the price/lease thresholds the scores were computed with
    - baseIds / sortKeys: the unsorted ids and the parallel numpy arrays used to sort
    """

    query: SearchQuery
    flatIds: list = field(default_factory=list)
    fitScores: dict = field(default_factory=dict)
    sortOrder: SortOrder = field(default_factory=SortOrder)
    bounds: Optional[object] = None
    baseIds: Optional[object] = field(default=None, repr=False)
    sortKeys: dict = field(default_factory=dict, repr=False)

    @property
    def count(self) -> int:
        return len(self.flatIds)

    @property
    def isEmpty(self) -> bool:
        """UC-01.EX.1 / NFR 2.2: no flat matches, so the No Results state is shown."""
        return not self.flatIds
