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

Items. `multi_lane_items` counts mailbox items (one provider id within one
publication) observed in more than one folder lane -- the backfill
folder-attribution shape -- and `inbox_sent_identity_pairs` counts identities
held by *distinct* provider ids whose primary lanes include both inbox and
sent (genuine separate mailbox items). The two shapes are counted apart.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
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
    ItemFlag,
    NormalizedMessage,
    Publication,
    RecordClassification,
)

__all__ = [
    "ADJACENCY_TOLERANCE_SECONDS",
    "CorpusSummary",
    "Interval",
    "merge_intervals",
    "summarize_corpus",
]

#: Inclusive windows at most this far apart are contiguous (`WINDOW_RESOLUTION`).
ADJACENCY_TOLERANCE_SECONDS = int(WINDOW_RESOLUTION.total_seconds())


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
    inbox_sent_identity_pairs: int
    multi_lane_items: int
    participant_reconciliations: int
    participant_disagreements: int
    lane_verification: Mapping[str, int]
    null_from_records: int
    empty_subjects: int
    window_rules: Mapping[str, int]
    dst_flagged_windows: int
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
    identity_signatures: defaultdict[CanonicalKey, set[tuple[str | None, str]]] = defaultdict(set)
    for index, message in usable:
        key = message.canonical_key
        provider_pubs[(message.mailbox_ref, message.provider_id)].add(index)
        identity_pubs[key].add(index)
        identity_signatures[key].add((message.sender_address, message.body.sha256))

    items = [item for publication in publications for item in publication.items]
    identity_items: defaultdict[CanonicalKey, dict[str, set[FolderRole]]] = defaultdict(dict)
    for item in items:
        if item.canonical_key.kind is IdentityState.PROVIDER_RETURNED:
            primary_role = next(
                o.role for o in item.observations if o.ordinal == item.primary_ordinal
            )
            identity_items[item.canonical_key].setdefault(item.provider_id, set()).add(primary_role)

    def distinct_pair(key: CanonicalKey) -> bool:
        roles_by_item = identity_items[key]
        inbox = {pid for pid, roles in roles_by_item.items() if FolderRole.INBOX in roles}
        sent = {pid for pid, roles in roles_by_item.items() if FolderRole.SENT in roles}
        return any(a != b for a in inbox for b in sent)

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
        inbox_sent_identity_pairs=sum(1 for key in identity_items if distinct_pair(key)),
        multi_lane_items=sum(1 for item in items if ItemFlag.MULTI_LANE in item.flags),
        participant_reconciliations=sum(
            1 for item in items if ItemFlag.PARTICIPANTS_RECONCILED in item.flags
        ),
        participant_disagreements=sum(
            1 for item in items if ItemFlag.PARTICIPANTS_DISAGREED in item.flags
        ),
        lane_verification=dict(
            sorted(Counter(m.folder_verification.value for _, m in usable).items())
        ),
        null_from_records=sum(1 for _, m in usable if not m.participants["from"].addresses),
        empty_subjects=sum(
            1 for p in publications for r in p.records if ReasonCode.SUBJECT_EMPTY in r.reasons
        ),
        window_rules=dict(sorted(Counter(p.window.rule.value for p in publications).items())),
        dst_flagged_windows=sum(
            1 for p in publications if p.window.dst_change_declared or p.window.dst_change_computed
        ),
        within_publication_identity_conflict_records=conflict_records,
        cross_publication_identity_conflicts=sum(1 for key in identity_pubs if cross_conflict(key)),
        coverage_intervals=merged,
        coverage_gaps=_gaps(merged),
        publications_excluded_from_coverage=len(publications) - len(covered),
    )
