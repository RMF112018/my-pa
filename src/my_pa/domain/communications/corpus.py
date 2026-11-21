"""Cross-publication summaries: merged coverage intervals, gaps, and identity counts.

Coverage. Only an accepted publication whose overall coverage is `complete`
contributes its window. Windows are inclusive at both ends, so two windows
whose bounds are at most `WINDOW_RESOLUTION` (one second) apart are contiguous
-- a backfill day ending `04:59:59` and the next starting `05:00:00` leave no gap.
A gap runs from one merged interval's end to the next one's start.

Identity. Counts are taken over *usable* records -- every classification but
`quarantined`. An identity seen in two publications is a cross-publication
repeat; if its sender address or body digest differs between them that is a
cross-publication identity conflict (counted here, never merged).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from my_pa.domain.communications.diagnostics import ReasonCode
from my_pa.domain.communications.model import (
    WINDOW_RESOLUTION,
    CanonicalKey,
    CoverageState,
    FolderRole,
    IdentityState,
    NormalizedMessage,
    Publication,
    RecordClassification,
)

__all__ = ["CorpusSummary", "Interval", "merge_intervals", "summarize_corpus"]


@dataclass(frozen=True, slots=True, order=True)
class Interval:
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class CorpusSummary:
    publications: int
    observations: int
    usable_observations: int
    unique_canonical_identities: int
    unique_provider_ids: int
    provider_id_cross_publication_repeats: int
    identity_cross_publication_repeats: int
    inbox_sent_pairs: int
    within_publication_identity_conflict_records: int
    cross_publication_identity_conflicts: int
    coverage_intervals: tuple[Interval, ...]
    coverage_gaps: tuple[Interval, ...]
    publications_excluded_from_coverage: int


def merge_intervals(intervals: Sequence[Interval]) -> tuple[Interval, ...]:
    merged: list[Interval] = []
    for interval in sorted(intervals):
        if merged and interval.start <= merged[-1].end + WINDOW_RESOLUTION:
            last = merged[-1]
            merged[-1] = Interval(last.start, max(last.end, interval.end))
        else:
            merged.append(interval)
    return tuple(merged)


def _gaps(merged: Sequence[Interval]) -> tuple[Interval, ...]:
    return tuple(Interval(a.end, b.start) for a, b in pairwise(merged))


def summarize_corpus(publications: Sequence[Publication]) -> CorpusSummary:
    usable: list[tuple[int, NormalizedMessage]] = []
    observations = 0
    conflict_records = 0
    for index, publication in enumerate(publications):
        for record in publication.records:
            observations += 1
            if ReasonCode.IDENTITY_CONFLICT in record.reasons:
                conflict_records += 1
            if record.classification is not RecordClassification.QUARANTINED and record.message:
                usable.append((index, record.message))

    provider_pubs: defaultdict[tuple[str, str], set[int]] = defaultdict(set)
    identity_pubs: defaultdict[CanonicalKey, set[int]] = defaultdict(set)
    identity_roles: defaultdict[CanonicalKey, set[FolderRole]] = defaultdict(set)
    identity_signatures: defaultdict[CanonicalKey, set[tuple[str | None, str]]] = defaultdict(set)
    for index, message in usable:
        key = message.canonical_key
        provider_pubs[(message.mailbox_ref, message.provider_id)].add(index)
        identity_pubs[key].add(index)
        identity_roles[key].add(message.folder_role)
        identity_signatures[key].add((message.sender_address, message.body.sha256))

    def cross_conflict(key: CanonicalKey) -> bool:
        signatures = identity_signatures[key]
        senders = {sender for sender, _ in signatures if sender is not None}
        digests = {digest for _, digest in signatures}
        return len(identity_pubs[key]) > 1 and (len(senders) > 1 or len(digests) > 1)

    covered = [
        Interval(p.window.start_utc, p.window.end_utc)
        for p in publications
        if p.coverage_overall is CoverageState.COMPLETE
    ]
    merged = merge_intervals(covered)
    return CorpusSummary(
        publications=len(publications),
        observations=observations,
        usable_observations=len(usable),
        unique_canonical_identities=len(identity_pubs),
        unique_provider_ids=len(provider_pubs),
        provider_id_cross_publication_repeats=sum(1 for v in provider_pubs.values() if len(v) > 1),
        identity_cross_publication_repeats=sum(1 for v in identity_pubs.values() if len(v) > 1),
        inbox_sent_pairs=sum(
            1
            for key, roles in identity_roles.items()
            if key.kind is IdentityState.PROVIDER_RETURNED
            and {FolderRole.INBOX, FolderRole.SENT} <= roles
        ),
        within_publication_identity_conflict_records=conflict_records,
        cross_publication_identity_conflicts=sum(1 for key in identity_pubs if cross_conflict(key)),
        coverage_intervals=merged,
        coverage_gaps=_gaps(merged),
        publications_excluded_from_coverage=len(publications) - len(covered),
    )
