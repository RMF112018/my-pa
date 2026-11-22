"""Cross-publication coverage merging and identity summaries (synthetic publications)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from my_pa.domain.communications.corpus import Interval, merge_intervals, summarize_corpus
from my_pa.domain.communications.model import Publication
from my_pa.infrastructure.communications.evidence_v2 import parse_publication
from tests.fixtures.communications_evidence import synthetic as s


def at(day: int, hour: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, 0, second, tzinfo=UTC)


def parsed(document: dict[str, Any]) -> Publication:
    publication = parse_publication(s.encode(document)).publication
    assert publication is not None
    return publication


def test_inclusive_windows_one_second_apart_are_contiguous() -> None:
    day_end = timedelta(hours=23, minutes=59, seconds=59)
    merged = merge_intervals(
        [Interval(at(18, 5), at(18, 5) + day_end), Interval(at(17, 5), at(17, 5) + day_end)]
    )
    assert merged == (Interval(at(17, 5), at(18, 5) + day_end),)


def test_overlapping_windows_merge_and_gaps_remain() -> None:
    merged = merge_intervals(
        [
            Interval(at(19, 5), at(20, 14)),
            Interval(at(13, 7), at(16, 7)),
            Interval(at(19, 11), at(20, 11)),
            Interval(at(17, 5), at(19, 5)),
        ]
    )
    assert merged == (Interval(at(13, 7), at(16, 7)), Interval(at(17, 5), at(20, 14)))


def test_a_two_second_separation_is_a_gap() -> None:
    merged = merge_intervals([Interval(at(1), at(2)), Interval(at(2, 0, 2), at(3))])
    assert len(merged) == 2


def test_the_corpus_summary_over_the_fixtures() -> None:
    lean, rich, friday = (
        parsed(s.lean_publication()),
        parsed(s.rich_publication()),
        parsed(s.friday_publication()),
    )
    summary = summarize_corpus([lean, rich, friday])
    assert summary.publications == 3
    assert summary.observations == 13 + 8 + 2
    assert summary.usable_observations == 11 + 5 + 2
    assert summary.inbox_sent_identity_pairs == 1
    assert summary.multi_lane_items == 0
    assert summary.within_publication_identity_conflict_records == 2
    assert summary.unique_provider_ids == 10 + 5 + 2
    assert summary.unique_canonical_identities == 9 + 5 + 2
    assert summary.coverage_intervals == (
        Interval(at(13, 7), at(16, 7)),
        Interval(at(17, 5), datetime(2026, 11, 18, 4, 59, 59, tzinfo=UTC)),
        Interval(at(19, 5), datetime(2026, 11, 20, 14, 12, 5, tzinfo=UTC)),
    )
    second = timedelta(seconds=1)
    # Inclusive like a window: the first and last uncovered seconds.
    assert summary.coverage_gaps[0] == Interval(at(16, 7) + second, at(17, 5) - second)
    assert summary.coverage_gaps[0].inclusive_seconds == 22 * 3600 - 1
    assert summary.publications_excluded_from_coverage == 0


def test_repeats_across_publications_are_counted_and_conflicts_detected() -> None:
    win = s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "weekday_prior_24h")
    first = s.publication([s.message(1), s.message(2)], win)
    second = s.publication([s.message(1), s.message(2, content="<p>Changed.</p>")], win)
    second["messages"][1]["id"] = second["messages"][1]["message_id"] = "SYNTHETIC-NEW-ID"
    summary = summarize_corpus([parsed(first), parsed(second)])
    assert summary.provider_id_cross_publication_repeats == 1
    assert summary.identity_cross_publication_repeats == 2
    assert summary.cross_publication_identity_conflicts == 1
    assert summary.unique_canonical_identities == 2
    assert summary.unique_provider_ids == 3


def test_incomplete_coverage_is_excluded_from_the_merged_intervals() -> None:
    document = s.lean_publication()
    document["coverage"]["overall"] = "partial"
    summary = summarize_corpus([parsed(document)])
    assert summary.coverage_intervals == ()
    assert summary.publications_excluded_from_coverage == 1
