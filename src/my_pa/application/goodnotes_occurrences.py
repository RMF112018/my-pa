"""Deterministic NOTE_UNIT occurrence reconciliation.

Reads Principal-bound GN-04 proposals, re-reads committed GN-03 occurrence
state, matches on visual region/geometry/context, and writes notes,
occurrences, revisions, links, and supplied-as-computed run-note-changes in
one transaction. Does not build a user-facing NEW-only summary. Does not
deliver. On uncertainty the change state is AMBIGUOUS; identity is never
reused optimistically.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.models import (
    GoodNotesIdentityStatus,
    GoodNotesIngestionRun,
    GoodNotesNote,
    GoodNotesNoteChangeState,
    GoodNotesNoteClass,
    GoodNotesNoteLink,
    GoodNotesNoteLinkKind,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesPagePosition,
    GoodNotesPageVersion,
    GoodNotesRunNoteChange,
    GoodNotesSegmentKind,
    GoodNotesSourceSnapshot,
    issue_stable_id,
    occurrence_geometry_key,
)

_LEASE_TTL = timedelta(minutes=5)
_LEASE_OWNER_DEFAULT = "occurrence-reconcile"
_ACTIVE_PRIOR = frozenset({GoodNotesIdentityStatus.ACTIVE, GoodNotesIdentityStatus.AMBIGUOUS})


class OccurrenceReconcileBusyError(ValueError):
    """Another reconcile already holds the Principal+source_root lease."""


class OccurrenceMatchMethod(StrEnum):
    EXACT_GEOMETRY_KEY = "EXACT_GEOMETRY_KEY"
    UNIQUE_CROP = "UNIQUE_CROP"
    CONTEXT_OVERLAP = "CONTEXT_OVERLAP"
    UNRESOLVED = "UNRESOLVED"


class OccurrenceMatchKind(StrEnum):
    PAIRED = "PAIRED"
    NEW = "NEW"
    REMOVED = "REMOVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class CurrentOccurrence:
    """One NOTE_UNIT proposal on a logical page. Transcription is not identity."""

    logical_page_id: str
    page_version_id: str
    snapshot_id: str | None
    x_min: float
    y_min: float
    width: float
    height: float
    crop_sha256: str | None
    context_anchor_sha256: str | None
    transcription: str
    primary_class: GoodNotesNoteClass | None
    schema_version: str
    analyzer_name: str
    analyzer_version: str
    geometry_key: str


@dataclass(frozen=True, slots=True)
class OccurrenceMatch:
    kind: OccurrenceMatchKind
    method: OccurrenceMatchMethod
    current: CurrentOccurrence | None = None
    prior: GoodNotesNoteOccurrence | None = None


@dataclass(frozen=True, slots=True)
class OccurrenceReconcileResult:
    run_id: str
    principal_id: str
    replayed: bool
    changes: tuple[GoodNotesRunNoteChange, ...]


class GoodNotesOccurrenceRepository(Protocol):
    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None: ...

    def update_run(self, run: GoodNotesIngestionRun) -> GoodNotesIngestionRun: ...

    def try_lock_source_root(self, principal_id: str, source_root_id: str) -> bool: ...

    def snapshots_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesSourceSnapshot, ...]: ...

    def page_positions(
        self, principal_id: str, snapshot_id: str
    ) -> tuple[GoodNotesPagePosition, ...]: ...

    def page_version(
        self, principal_id: str, page_version_id: str
    ) -> GoodNotesPageVersion | None: ...

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]: ...

    def occurrences_for_logical_pages(
        self, principal_id: str, logical_page_ids: tuple[str, ...]
    ) -> tuple[GoodNotesNoteOccurrence, ...]: ...

    def latest_revision_for_occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteRevision | None: ...

    def run_note_changes(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesRunNoteChange, ...]: ...

    def note(self, principal_id: str, note_id: str) -> GoodNotesNote | None: ...

    def store_note(self, note: GoodNotesNote) -> GoodNotesNote: ...

    def store_occurrence(self, occurrence: GoodNotesNoteOccurrence) -> GoodNotesNoteOccurrence: ...

    def store_revision(self, revision: GoodNotesNoteRevision) -> GoodNotesNoteRevision: ...

    def store_note_link(self, link: GoodNotesNoteLink) -> GoodNotesNoteLink: ...

    def store_run_note_change(self, change: GoodNotesRunNoteChange) -> GoodNotesRunNoteChange: ...


def match_occurrences(
    *,
    current: Sequence[CurrentOccurrence],
    prior: Sequence[GoodNotesNoteOccurrence],
) -> tuple[OccurrenceMatch, ...]:
    """Match strongest unique visual evidence to weakest. Never uses page number."""
    pages = _logical_pages(current, prior)
    matches: list[OccurrenceMatch] = []
    for page_id in pages:
        matches.extend(
            _match_page(
                [item for item in current if item.logical_page_id == page_id],
                [item for item in prior if item.logical_page_id == page_id],
            )
        )
    return tuple(matches)


def _logical_pages(
    current: Sequence[CurrentOccurrence], prior: Sequence[GoodNotesNoteOccurrence]
) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for proposed in current:
        seen.setdefault(proposed.logical_page_id, None)
    for existing in prior:
        seen.setdefault(existing.logical_page_id, None)
    return tuple(seen)


def _match_page(
    current: list[CurrentOccurrence], prior: list[GoodNotesNoteOccurrence]
) -> tuple[OccurrenceMatch, ...]:
    remaining_current = list(current)
    remaining_prior = list(prior)
    claimed: list[OccurrenceMatch] = []

    def claim(
        item: CurrentOccurrence,
        evidence: GoodNotesNoteOccurrence,
        method: OccurrenceMatchMethod,
    ) -> None:
        remaining_current.remove(item)
        remaining_prior.remove(evidence)
        claimed.append(
            OccurrenceMatch(
                kind=OccurrenceMatchKind.PAIRED,
                method=method,
                current=item,
                prior=evidence,
            )
        )

    def mark_ambiguous(
        currents: Iterable[CurrentOccurrence],
        priors: Iterable[GoodNotesNoteOccurrence],
    ) -> None:
        for item in tuple(currents):
            if item not in remaining_current:
                continue
            remaining_current.remove(item)
            claimed.append(
                OccurrenceMatch(
                    kind=OccurrenceMatchKind.AMBIGUOUS,
                    method=OccurrenceMatchMethod.UNRESOLVED,
                    current=item,
                )
            )
        for evidence in tuple(priors):
            if evidence not in remaining_prior:
                continue
            remaining_prior.remove(evidence)
            claimed.append(
                OccurrenceMatch(
                    kind=OccurrenceMatchKind.AMBIGUOUS,
                    method=OccurrenceMatchMethod.UNRESOLVED,
                    prior=evidence,
                )
            )

    _assign_unique(
        remaining_current,
        remaining_prior,
        key_current=lambda item: item.geometry_key,
        key_prior=lambda item: item.geometry_key,
        method=OccurrenceMatchMethod.EXACT_GEOMETRY_KEY,
        claim=claim,
        mark_ambiguous=mark_ambiguous,
    )
    _assign_unique(
        remaining_current,
        remaining_prior,
        key_current=lambda item: item.crop_sha256,
        key_prior=lambda item: item.crop_sha256,
        method=OccurrenceMatchMethod.UNIQUE_CROP,
        claim=claim,
        mark_ambiguous=mark_ambiguous,
    )
    _assign_context_overlap(remaining_current, remaining_prior, claim, mark_ambiguous)

    if remaining_current and remaining_prior:
        mark_ambiguous(remaining_current, remaining_prior)
    else:
        for item in tuple(remaining_current):
            remaining_current.remove(item)
            claimed.append(
                OccurrenceMatch(
                    kind=OccurrenceMatchKind.NEW,
                    method=OccurrenceMatchMethod.UNRESOLVED,
                    current=item,
                )
            )
        for evidence in tuple(remaining_prior):
            remaining_prior.remove(evidence)
            claimed.append(
                OccurrenceMatch(
                    kind=OccurrenceMatchKind.REMOVED,
                    method=OccurrenceMatchMethod.UNRESOLVED,
                    prior=evidence,
                )
            )
    return tuple(claimed)


def _assign_unique(
    remaining_current: list[CurrentOccurrence],
    remaining_prior: list[GoodNotesNoteOccurrence],
    *,
    key_current: Callable[[CurrentOccurrence], str | None],
    key_prior: Callable[[GoodNotesNoteOccurrence], str | None],
    method: OccurrenceMatchMethod,
    claim: Callable[[CurrentOccurrence, GoodNotesNoteOccurrence, OccurrenceMatchMethod], None],
    mark_ambiguous: Callable[
        [Iterable[CurrentOccurrence], Iterable[GoodNotesNoteOccurrence]], None
    ],
) -> None:
    current_unique = _unique_index(remaining_current, key_current)
    prior_unique = _unique_index(remaining_prior, key_prior)
    for key, item in tuple(current_unique.items()):
        evidence = prior_unique.get(key)
        if evidence is None or item not in remaining_current or evidence not in remaining_prior:
            continue
        claim(item, evidence, method)
    contested_current: list[CurrentOccurrence] = []
    contested_prior: list[GoodNotesNoteOccurrence] = []
    for item in remaining_current:
        feature = key_current(item)
        if feature is None:
            continue
        hits = [prior for prior in remaining_prior if key_prior(prior) == feature]
        current_count = sum(1 for other in remaining_current if key_current(other) == feature)
        if len(hits) > 1 or (hits and current_count > 1):
            contested_current.append(item)
            contested_prior.extend(hits)
    if contested_current:
        unique_priors: list[GoodNotesNoteOccurrence] = []
        seen: set[str] = set()
        for evidence in contested_prior:
            if evidence.occurrence_id in seen:
                continue
            seen.add(evidence.occurrence_id)
            unique_priors.append(evidence)
        mark_ambiguous(contested_current, unique_priors)


def _assign_context_overlap(
    remaining_current: list[CurrentOccurrence],
    remaining_prior: list[GoodNotesNoteOccurrence],
    claim: Callable[[CurrentOccurrence, GoodNotesNoteOccurrence, OccurrenceMatchMethod], None],
    mark_ambiguous: Callable[
        [Iterable[CurrentOccurrence], Iterable[GoodNotesNoteOccurrence]], None
    ],
) -> None:
    unique_pairs: list[tuple[CurrentOccurrence, GoodNotesNoteOccurrence]] = []
    contested_current: list[CurrentOccurrence] = []
    contested_prior: list[GoodNotesNoteOccurrence] = []
    for item in remaining_current:
        hits = [prior for prior in remaining_prior if _context_overlap(item, prior)]
        if len(hits) == 1:
            unique_pairs.append((item, hits[0]))
        elif len(hits) > 1:
            contested_current.append(item)
            contested_prior.extend(hits)
    prior_claimed: dict[str, list[CurrentOccurrence]] = {}
    for item, evidence in unique_pairs:
        prior_claimed.setdefault(evidence.occurrence_id, []).append(item)
    for evidence_id, currents in prior_claimed.items():
        if len(currents) == 1:
            item = currents[0]
            evidence = next(
                prior for prior in remaining_prior if prior.occurrence_id == evidence_id
            )
            if item in remaining_current and evidence in remaining_prior:
                claim(item, evidence, OccurrenceMatchMethod.CONTEXT_OVERLAP)
        else:
            contested_current.extend(currents)
            contested_prior.extend(
                prior for prior in remaining_prior if prior.occurrence_id == evidence_id
            )
    if contested_current:
        unique_priors: list[GoodNotesNoteOccurrence] = []
        seen: set[str] = set()
        for evidence in contested_prior:
            if evidence.occurrence_id in seen or evidence not in remaining_prior:
                continue
            seen.add(evidence.occurrence_id)
            unique_priors.append(evidence)
        mark_ambiguous(
            [item for item in contested_current if item in remaining_current],
            unique_priors,
        )


def _context_overlap(current: CurrentOccurrence, prior: GoodNotesNoteOccurrence) -> bool:
    if current.context_anchor_sha256 is None or prior.context_anchor_sha256 is None:
        return False
    if current.context_anchor_sha256 != prior.context_anchor_sha256:
        return False
    if current.logical_page_id != prior.logical_page_id:
        return False
    return _boxes_overlap(
        current.x_min,
        current.y_min,
        current.width,
        current.height,
        prior.x_min,
        prior.y_min,
        prior.width,
        prior.height,
    )


def _boxes_overlap(
    ax: float,
    ay: float,
    aw: float,
    ah: float,
    bx: float,
    by: float,
    bw: float,
    bh: float,
) -> bool:
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _unique_index[T](items: Sequence[T], key_fn: Callable[[T], str | None]) -> dict[str, T]:
    grouped: dict[str, list[T]] = {}
    for item in items:
        key = key_fn(item)
        if key is None:
            continue
        grouped.setdefault(key, []).append(item)
    return {key: group[0] for key, group in grouped.items() if len(group) == 1}


def _transcription_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _context_anchor(segments: Sequence[dict[str, object]]) -> str | None:
    parts: list[str] = []
    for segment in segments:
        if segment.get("kind") != GoodNotesSegmentKind.SOURCE_CONTEXT.value:
            continue
        geometry = segment.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("a GoodNotes proposal is missing required geometry")
        key = occurrence_geometry_key(
            float(geometry["x_min"]),
            float(geometry["y_min"]),
            float(geometry["width"]),
            float(geometry["height"]),
            None,
        )
        text = segment.get("transcription")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise ValueError("a GoodNotes proposal is missing required geometry")
        parts.append(f"{key}\x1f{text}")
    if not parts:
        return None
    return hashlib.sha256("\x1e".join(sorted(parts)).encode()).hexdigest()


def _note_units(
    *,
    payload: dict[str, object],
    page_version_id: str,
    logical_page_id: str,
    snapshot_id: str | None,
    schema_version: str,
    analyzer_name: str,
    analyzer_version: str,
) -> tuple[CurrentOccurrence, ...]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list | tuple) or not raw_segments:
        raise ValueError("a GoodNotes proposal is missing required geometry")
    segments = tuple(item for item in raw_segments if isinstance(item, dict))
    if len(segments) != len(raw_segments):
        raise ValueError("a GoodNotes proposal is missing required geometry")
    anchor = _context_anchor(segments)
    current: list[CurrentOccurrence] = []
    for segment in segments:
        kind = segment.get("kind")
        if kind != GoodNotesSegmentKind.NOTE_UNIT.value:
            continue
        geometry = segment.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError("a GoodNotes proposal is missing required geometry")
        try:
            x_min = float(geometry["x_min"])
            y_min = float(geometry["y_min"])
            width = float(geometry["width"])
            height = float(geometry["height"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("a GoodNotes proposal is missing required geometry") from error
        crop = segment.get("crop_sha256")
        if crop is not None and not isinstance(crop, str):
            raise ValueError("a GoodNotes proposal is missing required geometry")
        transcription = segment.get("transcription")
        if not isinstance(transcription, str) or not transcription:
            raise ValueError("a GoodNotes proposal is missing required geometry")
        primary = segment.get("primary_class")
        primary_class = None if primary is None else GoodNotesNoteClass(str(primary))
        current.append(
            CurrentOccurrence(
                logical_page_id=logical_page_id,
                page_version_id=page_version_id,
                snapshot_id=snapshot_id,
                x_min=x_min,
                y_min=y_min,
                width=width,
                height=height,
                crop_sha256=crop,
                context_anchor_sha256=anchor,
                transcription=transcription,
                primary_class=primary_class,
                schema_version=schema_version,
                analyzer_name=analyzer_name,
                analyzer_version=analyzer_version,
                geometry_key=occurrence_geometry_key(x_min, y_min, width, height, crop),
            )
        )
    return tuple(current)


class GoodNotesOccurrenceReconciler:
    def reconcile(
        self,
        principal_id: str,
        run_id: str,
        *,
        repository: GoodNotesOccurrenceRepository,
        clock: Callable[[], datetime] = utc_now,
        lease_owner: str = _LEASE_OWNER_DEFAULT,
    ) -> OccurrenceReconcileResult:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        run = repository.run(principal_id, run_id)
        if run is None:
            raise ValueError("the request names no stored GoodNotes ingestion run")
        if not repository.try_lock_source_root(principal_id, run.source_root_id):
            raise OccurrenceReconcileBusyError(
                "another GoodNotes occurrence reconcile holds the source-root lease"
            )
        existing = repository.run_note_changes(principal_id, run_id)
        if existing:
            return OccurrenceReconcileResult(
                run_id=run_id,
                principal_id=principal_id,
                replayed=True,
                changes=existing,
            )
        now = clock()
        repository.update_run(
            replace(run, lease_owner=lease_owner, lease_expires_at=now + _LEASE_TTL)
        )
        snapshots = repository.snapshots_for_run(principal_id, run_id)
        if not snapshots:
            raise ValueError("the request names no stored GoodNotes ingestion run")
        notebook_id = snapshots[0].notebook_id
        snapshot_by_page: dict[str, str] = {}
        logical_pages: dict[str, None] = {}
        for snapshot in snapshots:
            for position in repository.page_positions(principal_id, snapshot.snapshot_id):
                logical_pages.setdefault(position.logical_page_id, None)
                if position.page_version_id is not None:
                    snapshot_by_page[position.page_version_id] = snapshot.snapshot_id
        page_ids = tuple(logical_pages)
        proposals = repository.semantic_proposals_for_run(principal_id, run_id)
        current: list[CurrentOccurrence] = []
        for page_version_id, schema_version, analyzer_name, analyzer_version, payload in proposals:
            version = repository.page_version(principal_id, page_version_id)
            if version is None:
                raise ValueError("a GoodNotes proposal is missing required geometry")
            if version.logical_page_id is None:
                raise ValueError("a GoodNotes proposal is missing required geometry")
            current.extend(
                _note_units(
                    payload=payload,
                    page_version_id=page_version_id,
                    logical_page_id=version.logical_page_id,
                    snapshot_id=snapshot_by_page.get(page_version_id),
                    schema_version=schema_version,
                    analyzer_name=analyzer_name,
                    analyzer_version=analyzer_version,
                )
            )
        prior = tuple(
            item
            for item in repository.occurrences_for_logical_pages(principal_id, page_ids)
            if item.identity_status in _ACTIVE_PRIOR
        )
        matches = match_occurrences(current=current, prior=prior)
        changes = self._persist(
            principal_id=principal_id,
            run_id=run_id,
            notebook_id=notebook_id,
            matches=matches,
            repository=repository,
            now=now,
        )
        repository.update_run(replace(run, lease_owner=None, lease_expires_at=None))
        return OccurrenceReconcileResult(
            run_id=run_id,
            principal_id=principal_id,
            replayed=False,
            changes=changes,
        )

    def _persist(
        self,
        *,
        principal_id: str,
        run_id: str,
        notebook_id: str,
        matches: Sequence[OccurrenceMatch],
        repository: GoodNotesOccurrenceRepository,
        now: datetime,
    ) -> tuple[GoodNotesRunNoteChange, ...]:
        note_ids_for_anchor: dict[str, set[str]] = {}
        for match in matches:
            if match.prior is None or match.prior.context_anchor_sha256 is None:
                continue
            note_ids_for_anchor.setdefault(match.prior.context_anchor_sha256, set()).add(
                match.prior.note_id
            )
        written: list[GoodNotesRunNoteChange] = []
        for match in matches:
            if match.kind is OccurrenceMatchKind.AMBIGUOUS:
                if match.prior is None:
                    continue
                occurrence = repository.store_occurrence(
                    replace(
                        match.prior,
                        identity_status=GoodNotesIdentityStatus.AMBIGUOUS,
                        last_seen_at=now,
                        run_id=run_id,
                    )
                )
                written.append(
                    repository.store_run_note_change(
                        _change(
                            principal_id,
                            run_id,
                            occurrence.note_id,
                            occurrence.occurrence_id,
                            GoodNotesNoteChangeState.AMBIGUOUS,
                            now,
                        )
                    )
                )
                continue
            if match.kind is OccurrenceMatchKind.REMOVED:
                if match.prior is None:
                    raise ValueError("a removed occurrence match is missing prior identity")
                occurrence = repository.store_occurrence(
                    replace(
                        match.prior,
                        identity_status=GoodNotesIdentityStatus.RETIRED,
                        last_seen_at=now,
                        run_id=run_id,
                    )
                )
                written.append(
                    repository.store_run_note_change(
                        _change(
                            principal_id,
                            run_id,
                            occurrence.note_id,
                            occurrence.occurrence_id,
                            GoodNotesNoteChangeState.REMOVED_OR_NO_LONGER_PRESENT,
                            now,
                        )
                    )
                )
                continue
            if match.kind is OccurrenceMatchKind.PAIRED:
                if match.current is None or match.prior is None:
                    raise ValueError(
                        "a paired occurrence match is missing current or prior identity"
                    )
                written.append(
                    self._write_paired(
                        principal_id=principal_id,
                        run_id=run_id,
                        match=match,
                        repository=repository,
                        now=now,
                    )
                )
                continue
            if match.current is None:
                raise ValueError("an occurrence match could not be classified")
            written.append(
                self._write_new(
                    principal_id=principal_id,
                    run_id=run_id,
                    notebook_id=notebook_id,
                    current=match.current,
                    note_ids_for_anchor=note_ids_for_anchor,
                    repository=repository,
                    now=now,
                )
            )
        return tuple(written)

    def _write_paired(
        self,
        *,
        principal_id: str,
        run_id: str,
        match: OccurrenceMatch,
        repository: GoodNotesOccurrenceRepository,
        now: datetime,
    ) -> GoodNotesRunNoteChange:
        current = match.current
        prior = match.prior
        if current is None or prior is None:
            raise ValueError("a paired occurrence match is missing current or prior identity")
        latest = repository.latest_revision_for_occurrence(principal_id, prior.occurrence_id)
        prior_digest = None if latest is None else _transcription_digest(latest.transcription)
        current_digest = _transcription_digest(current.transcription)
        revised = prior_digest != current_digest
        occurrence = repository.store_occurrence(
            replace(
                prior,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                last_seen_at=now,
                page_version_id=current.page_version_id,
                snapshot_id=current.snapshot_id,
                run_id=run_id,
                context_anchor_sha256=current.context_anchor_sha256,
            )
        )
        note = repository.note(principal_id, occurrence.note_id)
        if note is None:
            raise ValueError("the GoodNotes note could not be stored")
        repository.store_note(
            replace(
                note,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                last_seen_at=now,
                primary_class=current.primary_class or note.primary_class,
            )
        )
        if revised:
            repository.store_revision(
                GoodNotesNoteRevision(
                    revision_id=issue_stable_id(
                        "gnrev", principal_id, run_id, occurrence.occurrence_id, current_digest
                    ),
                    principal_id=principal_id,
                    note_id=occurrence.note_id,
                    schema_version=current.schema_version,
                    analyzer_name=current.analyzer_name,
                    analyzer_version=current.analyzer_version,
                    transcription=current.transcription,
                    created_at=now,
                    occurrence_id=occurrence.occurrence_id,
                    supersedes_revision_id=None if latest is None else latest.revision_id,
                    primary_class=current.primary_class,
                )
            )
        state = GoodNotesNoteChangeState.REVISED if revised else GoodNotesNoteChangeState.UNCHANGED
        return repository.store_run_note_change(
            _change(
                principal_id,
                run_id,
                occurrence.note_id,
                occurrence.occurrence_id,
                state,
                now,
            )
        )

    def _write_new(
        self,
        *,
        principal_id: str,
        run_id: str,
        notebook_id: str,
        current: CurrentOccurrence,
        note_ids_for_anchor: dict[str, set[str]],
        repository: GoodNotesOccurrenceRepository,
        now: datetime,
    ) -> GoodNotesRunNoteChange:
        attached: str | None = None
        if current.context_anchor_sha256 is not None:
            notes = note_ids_for_anchor.get(current.context_anchor_sha256, set())
            if len(notes) == 1:
                attached = next(iter(notes))
        if attached is None:
            note = repository.store_note(
                GoodNotesNote(
                    note_id=issue_stable_id(
                        "gnnt", principal_id, run_id, current.logical_page_id, current.geometry_key
                    ),
                    principal_id=principal_id,
                    notebook_id=notebook_id,
                    identity_status=GoodNotesIdentityStatus.ACTIVE,
                    created_at=now,
                    last_seen_at=now,
                    primary_class=current.primary_class,
                )
            )
            repository.store_note_link(
                GoodNotesNoteLink(
                    link_id=issue_stable_id(
                        "gnlink", principal_id, note.note_id, "page", current.logical_page_id
                    ),
                    principal_id=principal_id,
                    note_id=note.note_id,
                    link_kind=GoodNotesNoteLinkKind.NOTE_TO_LOGICAL_PAGE,
                    created_at=now,
                    target_logical_page_id=current.logical_page_id,
                )
            )
            if current.context_anchor_sha256 is not None:
                repository.store_note_link(
                    GoodNotesNoteLink(
                        link_id=issue_stable_id(
                            "gnlink",
                            principal_id,
                            note.note_id,
                            "ctx",
                            current.context_anchor_sha256,
                        ),
                        principal_id=principal_id,
                        note_id=note.note_id,
                        link_kind=GoodNotesNoteLinkKind.NOTE_TO_SOURCE_CONTEXT,
                        created_at=now,
                        target_context_anchor_sha256=current.context_anchor_sha256,
                    )
                )
        else:
            existing = repository.note(principal_id, attached)
            if existing is None:
                raise ValueError("the GoodNotes note could not be stored")
            note = repository.store_note(
                replace(
                    existing,
                    identity_status=GoodNotesIdentityStatus.ACTIVE,
                    last_seen_at=now,
                    primary_class=current.primary_class or existing.primary_class,
                )
            )
        occurrence = repository.store_occurrence(
            GoodNotesNoteOccurrence(
                occurrence_id=issue_stable_id(
                    "gnocc", principal_id, run_id, current.logical_page_id, current.geometry_key
                ),
                principal_id=principal_id,
                note_id=note.note_id,
                logical_page_id=current.logical_page_id,
                x_min=current.x_min,
                y_min=current.y_min,
                width=current.width,
                height=current.height,
                identity_status=GoodNotesIdentityStatus.ACTIVE,
                created_at=now,
                last_seen_at=now,
                page_version_id=current.page_version_id,
                snapshot_id=current.snapshot_id,
                run_id=run_id,
                crop_sha256=current.crop_sha256,
                context_anchor_sha256=current.context_anchor_sha256,
            )
        )
        repository.store_revision(
            GoodNotesNoteRevision(
                revision_id=issue_stable_id(
                    "gnrev",
                    principal_id,
                    run_id,
                    occurrence.occurrence_id,
                    _transcription_digest(current.transcription),
                ),
                principal_id=principal_id,
                note_id=note.note_id,
                schema_version=current.schema_version,
                analyzer_name=current.analyzer_name,
                analyzer_version=current.analyzer_version,
                transcription=current.transcription,
                created_at=now,
                occurrence_id=occurrence.occurrence_id,
                primary_class=current.primary_class,
            )
        )
        return repository.store_run_note_change(
            _change(
                principal_id,
                run_id,
                note.note_id,
                occurrence.occurrence_id,
                GoodNotesNoteChangeState.NEW,
                now,
            )
        )


def _change(
    principal_id: str,
    run_id: str,
    note_id: str,
    occurrence_id: str,
    state: GoodNotesNoteChangeState,
    now: datetime,
) -> GoodNotesRunNoteChange:
    return GoodNotesRunNoteChange(
        change_id=issue_stable_id("gnchg", principal_id, run_id, occurrence_id, state.value),
        principal_id=principal_id,
        run_id=run_id,
        note_id=note_id,
        occurrence_id=occurrence_id,
        change_state=state,
        created_at=now,
    )
