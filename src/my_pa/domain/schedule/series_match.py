"""Schedule Scenarios S6-1: the pure Series matcher `series-match-v1` (contract section 11.2.1).

Exact string equality only (R2 section 16): published Activity IDs and
normalized names are never case-folded, trimmed further or fuzzily compared.
The score is the Jaccard index in permille, `floor(1000 * |A n B| / |A u B|)`.
The name agreement on the shared IDs is a **veto only**: it can demote a match
to `ambiguous`, never select one. The publication title is recorded
(`title_equal`) and never read by the outcome.

`match_series` decides `matched`, `created`, `ambiguous`, `needs_series` or
`already_present`; `admission_refused` and `not_eligible` are decided by the
worker hook (S6-2) around it. An `ambiguous` decision carries exactly 1 reason,
by the precedence `candidate_bound` > `insufficient_evidence` > `multiple_high`
> `margin` > `data_date_incoherent` > `evidence_conflict` > `name_conflict`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Final

__all__ = [
    "CONSIDER_THRESHOLD",
    "MARGIN_THRESHOLD",
    "MATCH_THRESHOLD",
    "MAX_MATCH_CANDIDATES",
    "MINIMUM_INCOMING_IDS",
    "NAME_AGREEMENT_THRESHOLD",
    "SERIES_MATCH_VERSION",
    "MatchCandidate",
    "MatchDecision",
    "MatchIncoming",
    "MatchOutcome",
    "MatchReason",
    "NewSeriesName",
    "SeriesCandidate",
    "match_series",
]

SERIES_MATCH_VERSION: Final = "series-match-v1"
#: Operator default S6-O11.
CONSIDER_THRESHOLD: Final = 300
MATCH_THRESHOLD: Final = 800
MARGIN_THRESHOLD: Final = 500
MINIMUM_INCOMING_IDS: Final = 20
NAME_AGREEMENT_THRESHOLD: Final = 600
#: More non-intake Series than this makes the outcome `ambiguous`/`candidate_bound`.
MAX_MATCH_CANDIDATES: Final = 50


class MatchOutcome(StrEnum):
    """The closed outcome set (section 11.2 step 5)."""

    MATCHED = "matched"
    CREATED = "created"
    AMBIGUOUS = "ambiguous"
    NEEDS_SERIES = "needs_series"
    ALREADY_PRESENT = "already_present"
    ADMISSION_REFUSED = "admission_refused"
    NOT_ELIGIBLE = "not_eligible"


class MatchReason(StrEnum):
    """`ambiguous` reasons, in precedence order."""

    CANDIDATE_BOUND = "candidate_bound"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    MULTIPLE_HIGH = "multiple_high"
    MARGIN = "margin"
    DATA_DATE_INCOHERENT = "data_date_incoherent"
    EVIDENCE_CONFLICT = "evidence_conflict"
    NAME_CONFLICT = "name_conflict"


class NewSeriesName(StrEnum):
    """The `series_name_if_new` state, decided by the caller under the Project lock."""

    ABSENT = "absent"
    FREE = "free"
    TAKEN = "taken"


@dataclass(frozen=True, slots=True)
class MatchIncoming:
    """The incoming accepted run: published Activity ID -> normalized name."""

    activities: Mapping[str, str]
    data_date: date
    title: str | None = None


@dataclass(frozen=True, slots=True)
class SeriesCandidate:
    """One non-intake Series of the Project and its current (or newest) publication."""

    series_id: str
    created_at: datetime
    publication_id: str
    data_date: date
    activities: Mapping[str, str]
    title: str | None = None
    #: The Series already holds the incoming source version (outcome `already_present`).
    holds_source_version: bool = False
    #: That existing publication, when it does.
    existing_publication_id: str | None = None


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """One candidate as the decision records it."""

    series_id: str
    publication_id: str
    data_date: date
    score: int
    data_date_coherent: bool
    name_agreement_permille: int
    title_equal: bool


@dataclass(frozen=True, slots=True)
class MatchDecision:
    outcome: MatchOutcome
    reason: MatchReason | None
    incoming_id_count: int
    candidates: tuple[MatchCandidate, ...] = field(default=())
    series_id: str | None = None
    existing_publication_id: str | None = None
    threshold_version: str = SERIES_MATCH_VERSION


def _permille(part: int, whole: int) -> int:
    return 0 if whole == 0 else (1000 * part) // whole


def _scored(incoming: MatchIncoming, candidate: SeriesCandidate) -> MatchCandidate:
    a, b = incoming.activities, candidate.activities
    shared = a.keys() & b.keys()
    union = len(a.keys() | b.keys())
    agreeing = sum(1 for key in shared if a[key] == b[key])
    return MatchCandidate(
        series_id=candidate.series_id,
        publication_id=candidate.publication_id,
        data_date=candidate.data_date,
        score=_permille(len(shared), union),
        data_date_coherent=incoming.data_date >= candidate.data_date,
        name_agreement_permille=_permille(agreeing, len(shared)),
        title_equal=incoming.title is not None and incoming.title == candidate.title,
    )


def _ambiguity(incoming_count: int, ranked: Sequence[MatchCandidate]) -> MatchReason | None:
    """The single reason `matched` fails, or `None` when it holds."""
    high = [item for item in ranked if item.score >= MATCH_THRESHOLD]
    if incoming_count < MINIMUM_INCOMING_IDS or not high:
        return MatchReason.INSUFFICIENT_EVIDENCE
    if len(high) > 1:
        return MatchReason.MULTIPLE_HIGH
    top = high[0]
    if any(item.score >= MARGIN_THRESHOLD for item in ranked if item is not top):
        return MatchReason.MARGIN
    if not top.data_date_coherent:
        return MatchReason.DATA_DATE_INCOHERENT
    if top.name_agreement_permille < NAME_AGREEMENT_THRESHOLD:
        return MatchReason.EVIDENCE_CONFLICT
    return None


def match_series(
    incoming: MatchIncoming,
    candidates: Sequence[SeriesCandidate],
    *,
    new_series_name: NewSeriesName = NewSeriesName.ABSENT,
) -> MatchDecision:
    """Decide one intake publication against the Project's non-intake Series."""
    count = len(incoming.activities)
    if len(candidates) > MAX_MATCH_CANDIDATES:
        return MatchDecision(MatchOutcome.AMBIGUOUS, MatchReason.CANDIDATE_BOUND, count)
    by_id = {candidate.series_id: candidate for candidate in candidates}
    created = {candidate.series_id: candidate.created_at for candidate in candidates}
    ranked = tuple(
        sorted(
            (_scored(incoming, candidate) for candidate in candidates),
            key=lambda item: (-item.score, created[item.series_id], item.series_id),
        )
    )
    considered = [item for item in ranked if item.score >= CONSIDER_THRESHOLD]
    if not considered:
        if new_series_name is NewSeriesName.FREE:
            return MatchDecision(MatchOutcome.CREATED, None, count, ranked)
        if new_series_name is NewSeriesName.TAKEN:
            return MatchDecision(MatchOutcome.AMBIGUOUS, MatchReason.NAME_CONFLICT, count, ranked)
        return MatchDecision(MatchOutcome.NEEDS_SERIES, None, count, ranked)
    reason = _ambiguity(count, ranked)
    if reason is not None:
        return MatchDecision(MatchOutcome.AMBIGUOUS, reason, count, ranked)
    winner = ranked[0]
    target = by_id[winner.series_id]
    if target.holds_source_version:
        return MatchDecision(
            MatchOutcome.ALREADY_PRESENT,
            None,
            count,
            ranked,
            series_id=winner.series_id,
            existing_publication_id=target.existing_publication_id,
        )
    return MatchDecision(MatchOutcome.MATCHED, None, count, ranked, series_id=winner.series_id)
