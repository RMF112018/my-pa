"""Schedule Scenarios S6-1: the pure Series matcher `series-match-v1` (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 11.2.1,
vectors M1-M9 (M1c named alone, R8-F08). Unless a vector says otherwise every
incoming set has a coherent Data Date and every candidate's names agree with
the incoming names on the shared IDs. Every identifier is synthetic.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Final

import pytest

from my_pa.domain.schedule.series_match import (
    MAX_MATCH_CANDIDATES,
    SERIES_MATCH_VERSION,
    MatchDecision,
    MatchIncoming,
    MatchOutcome,
    MatchReason,
    NewSeriesName,
    SeriesCandidate,
    match_series,
)

INCOMING_DATE: Final = date(2027, 3, 1)


def ids(prefix: str, first: int, last: int) -> list[str]:
    return [f"{prefix}{index}" for index in range(first, last + 1)]


def named(keys: list[str], names: dict[str, str] | None = None) -> dict[str, str]:
    """Names agree with the incoming `N<k>` for `S<k>` unless given."""
    return {key: (names or {}).get(key, "N" + key[1:]) for key in keys}


def candidate(
    series: str,
    keys: list[str],
    *,
    names: dict[str, str] | None = None,
    data_date: date = date(2027, 2, 1),
    order: int = 0,
    title: str | None = None,
    holds_source_version: bool = False,
) -> SeriesCandidate:
    return SeriesCandidate(
        series_id=f"sser_{series * 10}",
        created_at=datetime(2026, 12, 1, 9, order),
        publication_id=f"spub_{series * 10}",
        data_date=data_date,
        activities=named(keys, names),
        title=title,
        holds_source_version=holds_source_version,
        existing_publication_id=f"spub_{series * 9}z" if holds_source_version else None,
    )


S100: Final = ids("S", 1, 100)
X_M1: Final = ids("S", 1, 95) + ids("T", 1, 5)
Y_M1: Final = ids("S", 1, 10) + ids("U", 1, 90)

Vector = tuple[MatchIncoming, list[SeriesCandidate], NewSeriesName]


def _incoming(
    keys: list[str],
    *,
    names: dict[str, str] | None = None,
    title: str | None = None,
    data_date: date = INCOMING_DATE,
) -> MatchIncoming:
    return MatchIncoming(activities=named(keys, names), data_date=data_date, title=title)


GC: Final = {key: f"GC-{index}" for index, key in enumerate(ids("A", 1000, 1099), 1)}
SUB: Final = {key: f"SUB-{index}" for index, key in enumerate(ids("A", 1000, 1099), 1)}

VECTORS: Final[dict[str, tuple[Vector, MatchOutcome, MatchReason | None, str | None]]] = {
    "M1": (
        (
            _incoming(S100),
            [candidate("X", X_M1), candidate("Y", Y_M1, order=1)],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.MATCHED,
        None,
        "X",
    ),
    "M1c": (
        (_incoming(S100), [candidate("X", [key.lower() for key in S100])], NewSeriesName.ABSENT),
        MatchOutcome.NEEDS_SERIES,
        None,
        None,
    ),
    "M2": (
        (
            _incoming(S100),
            [candidate("X", X_M1), candidate("Y", ids("S", 1, 90) + ids("V", 1, 10), order=1)],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.AMBIGUOUS,
        MatchReason.MULTIPLE_HIGH,
        None,
    ),
    "M3": (
        (_incoming(S100), [candidate("X", ids("W", 1, 100))], NewSeriesName.ABSENT),
        MatchOutcome.NEEDS_SERIES,
        None,
        None,
    ),
    "M3n": (
        (_incoming(S100), [candidate("X", ids("W", 1, 100))], NewSeriesName.FREE),
        MatchOutcome.CREATED,
        None,
        None,
    ),
    "M4": (
        (
            _incoming(ids("A", 1000, 1099), data_date=date(2027, 1, 4)),
            [candidate("X", ids("A", 1000, 1099), data_date=date(2027, 2, 1))],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.AMBIGUOUS,
        MatchReason.DATA_DATE_INCOHERENT,
        None,
    ),
    "M5": (
        (_incoming(ids("S", 1, 12)), [candidate("X", ids("S", 1, 12))], NewSeriesName.ABSENT),
        MatchOutcome.AMBIGUOUS,
        MatchReason.INSUFFICIENT_EVIDENCE,
        None,
    ),
    "M6a": (
        (
            _incoming(S100),
            [
                candidate("X", ids("S", 1, 90) + ids("P", 1, 10)),
                candidate("Y", ids("S", 1, 69) + ids("Q", 1, 31), order=1),
            ],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.AMBIGUOUS,
        MatchReason.MARGIN,
        None,
    ),
    "M6b": (
        (
            _incoming(S100),
            [
                candidate("X", ids("S", 1, 90) + ids("P", 1, 10)),
                candidate("Y", ids("S", 1, 66) + ids("Q", 1, 34), order=1),
            ],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.MATCHED,
        None,
        "X",
    ),
    "M7": (
        (
            _incoming(S100, title="Synthetic Master Schedule"),
            [
                candidate("X", X_M1),
                candidate("Y", Y_M1, order=1, title="Synthetic Master Schedule"),
            ],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.MATCHED,
        None,
        "X",
    ),
    "M8": (
        (
            _incoming(ids("A", 1000, 1099), names=GC),
            [candidate("X", ids("A", 1000, 1099), names=SUB)],
            NewSeriesName.ABSENT,
        ),
        MatchOutcome.AMBIGUOUS,
        MatchReason.EVIDENCE_CONFLICT,
        None,
    ),
    "M9": (
        (_incoming(S100), [candidate("X", X_M1, holds_source_version=True)], NewSeriesName.ABSENT),
        MatchOutcome.ALREADY_PRESENT,
        None,
        "X",
    ),
}

#: Contract scores, in permille, per vector and candidate.
SCORES: Final = {
    "M1": {"X": 904, "Y": 52},
    "M1c": {"X": 0},
    "M2": {"X": 904, "Y": 818},
    "M3": {"X": 0},
    "M4": {"X": 1000},
    "M5": {"X": 1000},
    "M6a": {"X": 818, "Y": 526},
    "M6b": {"X": 818, "Y": 492},
    "M7": {"X": 904, "Y": 52},
    "M8": {"X": 1000},
    "M9": {"X": 904},
}


def _decide(vector: str) -> MatchDecision:
    (incoming, candidates, name), *_ = VECTORS[vector]
    return match_series(incoming, candidates, new_series_name=name)


@pytest.mark.parametrize("vector", sorted(VECTORS))
def test_series_match_vectors(vector: str) -> None:
    _, outcome, reason, series = VECTORS[vector]
    decision = _decide(vector)
    assert decision.outcome is outcome
    assert decision.reason is reason
    assert decision.series_id == (None if series is None else f"sser_{series * 10}")
    assert decision.threshold_version == SERIES_MATCH_VERSION == "series-match-v1"
    if vector in SCORES:
        scores = {
            item.series_id.removeprefix("sser_")[0]: item.score for item in decision.candidates
        }
        assert scores == SCORES[vector]


def test_m8_records_the_name_agreement_and_m9_the_existing_publication() -> None:
    m8 = _decide("M8")
    assert [(item.score, item.name_agreement_permille) for item in m8.candidates] == [(1000, 0)]
    assert _decide("M1").candidates[0].name_agreement_permille == 1000
    assert _decide("M9").existing_publication_id == "spub_" + "X" * 9 + "z"


def test_title_is_recorded_and_never_decides() -> None:
    decision = _decide("M7")
    by_series = {item.series_id: item for item in decision.candidates}
    assert by_series["sser_" + "Y" * 10].title_equal is True
    assert by_series["sser_" + "X" * 10].title_equal is False
    assert decision.outcome is MatchOutcome.MATCHED


def test_candidates_are_ranked_by_score_then_creation_then_id() -> None:
    incoming = _incoming(S100)
    tied = [
        candidate("Z", ids("W", 1, 10), order=0),
        candidate("B", ids("W", 1, 10), order=5),
        candidate("A", ids("W", 1, 10), order=5),
        candidate("X", X_M1, order=9),
    ]
    decision = match_series(incoming, tied)
    assert [item.series_id[5] for item in decision.candidates] == ["X", "Z", "A", "B"]


def test_a_taken_new_series_name_is_a_name_conflict() -> None:
    (incoming, candidates, _), *_ = VECTORS["M3"]
    decision = match_series(incoming, candidates, new_series_name=NewSeriesName.TAKEN)
    assert (decision.outcome, decision.reason) == (
        MatchOutcome.AMBIGUOUS,
        MatchReason.NAME_CONFLICT,
    )


def test_more_than_the_candidate_bound_is_ambiguous_without_scoring() -> None:
    many = [
        candidate(f"{index:02d}", X_M1, order=index % 60)
        for index in range(MAX_MATCH_CANDIDATES + 1)
    ]
    decision = match_series(_incoming(S100), many)
    assert (decision.outcome, decision.reason, decision.candidates) == (
        MatchOutcome.AMBIGUOUS,
        MatchReason.CANDIDATE_BOUND,
        (),
    )
    assert match_series(_incoming(S100), many[:MAX_MATCH_CANDIDATES]).reason is (
        MatchReason.MULTIPLE_HIGH
    )


def test_a_considered_candidate_below_the_match_score_is_insufficient_evidence() -> None:
    decision = match_series(_incoming(S100), [candidate("X", ids("S", 1, 70) + ids("R", 1, 30))])
    assert decision.candidates[0].score == 538
    assert (decision.outcome, decision.reason) == (
        MatchOutcome.AMBIGUOUS,
        MatchReason.INSUFFICIENT_EVIDENCE,
    )


def test_outcomes_and_reasons_are_closed() -> None:
    assert [member.value for member in MatchOutcome] == [
        "matched",
        "created",
        "ambiguous",
        "needs_series",
        "already_present",
        "admission_refused",
        "not_eligible",
    ]
    assert [member.value for member in MatchReason] == [
        "candidate_bound",
        "insufficient_evidence",
        "multiple_high",
        "margin",
        "data_date_incoherent",
        "evidence_conflict",
        "name_conflict",
    ]


def test_a_second_candidate_at_exactly_the_margin_is_ambiguous() -> None:
    """Section 11.2.1: every other candidate must be < 500, so exactly 500 fails `matched`."""
    at_margin = candidate("Y", S100 + ids("Z", 1, 100), order=1)
    decision = match_series(_incoming(S100), [candidate("X", X_M1), at_margin])
    scores = sorted(item.score for item in decision.candidates)
    assert scores == [500, 904]
    assert (decision.outcome, decision.reason) == (MatchOutcome.AMBIGUOUS, MatchReason.MARGIN)
