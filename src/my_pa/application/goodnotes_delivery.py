"""NEW-only GoodNotes summary, entity association, and idempotent delivery receipts.

Reads committed GN-05 run-note-changes. Does not re-reconcile, does not write
notes/occurrences/revisions/run-change rows, and does not decide change state.
Does not create Projects, people, Tasks, Meetings, or Agendas.
Does not send to Teams, email, or Abacus. Destination is an explicit string such as
`operator-local`. A dormant attempt ledger may record crash windows; live send stays
off. Page-level `note-unit.v1` candidates are not attached to notes.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.models import (
    NOTE_UNIT_SCHEMA_V2,
    GoodNotesDeliveryAttempt,
    GoodNotesDeliveryAttemptState,
    GoodNotesDeliveryReceipt,
    GoodNotesEntityAssociation,
    GoodNotesEntityDirectoryRecord,
    GoodNotesEntityKind,
    GoodNotesEntityResolution,
    GoodNotesIngestionRun,
    GoodNotesNoteChangeState,
    GoodNotesNoteClass,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesRunNoteChange,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
    inferred_transcription_status,
    issue_stable_id,
)

_LOW_LINKING = 0.5
_IDENTIFIER = re.compile(r"\A(?:prj_[A-Za-z0-9]{8,64}|per_[A-Za-z0-9]{8,64}|gnnt_[a-f0-9]{24})\Z")
_SECTION_TITLES: tuple[tuple[GoodNotesNoteClass, str], ...] = (
    (GoodNotesNoteClass.MEETING, "NEW MEETING NOTES"),
    (GoodNotesNoteClass.PROJECT, "NEW PROJECT NOTES"),
    (GoodNotesNoteClass.RELATIONSHIP, "NEW RELATIONSHIP NOTES"),
    (GoodNotesNoteClass.GENERAL, "NEW GENERAL NOTES"),
)
_REVIEW_SECTION = "LOW-CONFIDENCE / REVIEW NEEDED"


@dataclass(frozen=True, slots=True)
class NewOnlySummaryNote:
    """One committed NEW note. Transcription is not a uniqueness key."""

    note_id: str
    occurrence_id: str
    primary_class: GoodNotesNoteClass | None
    uncertain: bool
    transcription: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class GoodNotesDeliveryResult:
    receipt: GoodNotesDeliveryReceipt
    associations: tuple[GoodNotesEntityAssociation, ...]


class GoodNotesDeliveryRepository(Protocol):
    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None: ...

    def run_note_changes(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesRunNoteChange, ...]: ...

    def occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteOccurrence | None: ...

    def revision(self, principal_id: str, revision_id: str) -> GoodNotesNoteRevision | None: ...

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]: ...

    def entity_directory(self, principal_id: str) -> tuple[GoodNotesEntityDirectoryRecord, ...]: ...

    def store_entity_association(
        self, association: GoodNotesEntityAssociation
    ) -> GoodNotesEntityAssociation: ...

    def entity_associations_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesEntityAssociation, ...]: ...

    def store_delivery_receipt(
        self, receipt: GoodNotesDeliveryReceipt
    ) -> GoodNotesDeliveryReceipt: ...

    def delivery_receipt_by_key(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        summary_hash: str,
    ) -> GoodNotesDeliveryReceipt | None: ...

    def store_delivery_attempt(
        self, attempt: GoodNotesDeliveryAttempt
    ) -> GoodNotesDeliveryAttempt: ...

    def delivery_attempt(
        self, principal_id: str, attempt_id: str
    ) -> GoodNotesDeliveryAttempt | None: ...

    def delivery_attempts_for_token(
        self, principal_id: str, idempotency_token: str
    ) -> tuple[GoodNotesDeliveryAttempt, ...]: ...


def normalize_entity_name(value: str) -> str:
    return " ".join(value.casefold().split())


def resolve_entity_candidate(
    literal: str, directory: Sequence[GoodNotesEntityDirectoryRecord]
) -> tuple[GoodNotesEntityResolution, GoodNotesEntityKind | None, str | None]:
    """RESOLVE_FIRST -> ASSOCIATE_IF_CONFIDENT -> STORE_LITERAL if 0 or 2+ matches."""
    identifier_hits = tuple(item for item in directory if item.entity_id == literal)
    if _IDENTIFIER.fullmatch(literal) or identifier_hits:
        if len(identifier_hits) == 1:
            hit = identifier_hits[0]
            return GoodNotesEntityResolution.ASSOCIATED, hit.kind, hit.entity_id
        return GoodNotesEntityResolution.UNRESOLVED, None, None
    wanted = normalize_entity_name(literal)
    name_hits = tuple(
        item
        for item in directory
        if item.normalized_name is not None and item.normalized_name == wanted
    )
    if len(name_hits) == 1:
        hit = name_hits[0]
        return GoodNotesEntityResolution.ASSOCIATED, hit.kind, hit.entity_id
    return GoodNotesEntityResolution.UNRESOLVED, None, None


def new_note_is_uncertain(
    *,
    primary_class: GoodNotesNoteClass | None,
    confidence: Mapping[str, object] | None,
) -> bool:
    if primary_class is None:
        return True
    if confidence is None:
        return False
    note = confidence.get("uncertainty")
    if isinstance(note, str) and note:
        return True
    linking = confidence.get("linking")
    if isinstance(linking, bool) or not isinstance(linking, int | float):
        return False
    return float(linking) < _LOW_LINKING


def build_new_only_summary(notes: Sequence[NewOnlySummaryNote]) -> str | None:
    """User-facing body from committed NEW notes only. Empty input suppresses."""
    if not notes:
        return None
    sections: list[str] = []
    for note_class, title in _SECTION_TITLES:
        members = tuple(item for item in notes if item.primary_class is note_class)
        if members:
            sections.append(_section(title, members))
    review = tuple(item for item in notes if item.uncertain)
    if review:
        sections.append(_section(_REVIEW_SECTION, review))
    if not sections:
        return None
    return "\n\n".join(sections)


def summary_digest(body: str | None) -> str:
    return hashlib.sha256((body or "").encode()).hexdigest()


def _section(title: str, notes: Sequence[NewOnlySummaryNote]) -> str:
    lines = [title, *(f"- {item.transcription}" for item in notes)]
    return "\n".join(lines)


def _ranked_candidates(payload: Mapping[str, object]) -> tuple[tuple[int, str], ...]:
    raw = payload.get("ranked_candidates")
    if not isinstance(raw, list | tuple):
        return ()
    ranked: list[tuple[int, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rank = item.get("rank")
        candidate = item.get("candidate")
        if type(rank) is not int or rank < 1:
            continue
        if not isinstance(candidate, str) or not candidate:
            continue
        ranked.append((rank, candidate))
    return tuple(ranked)


def _confidence(payload: Mapping[str, object]) -> dict[str, object] | None:
    raw = payload.get("confidence")
    return raw if isinstance(raw, dict) else None


def _box_key(x_min: float, y_min: float, width: float, height: float) -> str:
    return f"{x_min:.4f},{y_min:.4f},{width:.4f},{height:.4f}"


def _matching_note_unit(
    occurrence: GoodNotesNoteOccurrence,
    proposals: Sequence[tuple[str, str, str, str, dict[str, object]]],
) -> tuple[str, Mapping[str, object]] | None:
    """The unique NOTE_UNIT on this page version whose geometry produced the occurrence."""
    if occurrence.page_version_id is None:
        return None
    wanted = _box_key(occurrence.x_min, occurrence.y_min, occurrence.width, occurrence.height)
    matches: list[tuple[str, Mapping[str, object]]] = []
    for page_version_id, schema_version, _analyzer, _version, payload in proposals:
        if page_version_id != occurrence.page_version_id:
            continue
        raw_segments = payload.get("segments")
        if not isinstance(raw_segments, list | tuple):
            continue
        for segment in raw_segments:
            if not isinstance(segment, dict):
                continue
            if segment.get("kind") != GoodNotesSegmentKind.NOTE_UNIT.value:
                continue
            geometry = segment.get("geometry")
            if not isinstance(geometry, dict):
                continue
            try:
                key = _box_key(
                    float(geometry["x_min"]),
                    float(geometry["y_min"]),
                    float(geometry["width"]),
                    float(geometry["height"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if key == wanted:
                matches.append((schema_version, segment))
    if len(matches) != 1:
        return None
    return matches[0]


def _note_unit_status(
    schema_version: str, segment: Mapping[str, object]
) -> GoodNotesTranscriptionStatus | None:
    if schema_version != NOTE_UNIT_SCHEMA_V2:
        return None
    raw = segment.get("transcription_status")
    transcription = segment.get("transcription")
    text = transcription if isinstance(transcription, str) else None
    if isinstance(raw, str) and raw:
        try:
            return GoodNotesTranscriptionStatus(raw)
        except ValueError:
            return inferred_transcription_status(
                transcription=text,
                confidence=_confidence(segment),
            )
    return inferred_transcription_status(
        transcription=text,
        confidence=_confidence(segment),
    )


class GoodNotesNewOnlyDelivery:
    def deliver(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        *,
        repository: GoodNotesDeliveryRepository,
        clock: Callable[[], datetime] = utc_now,
    ) -> GoodNotesDeliveryResult:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        run = repository.run(principal_id, run_id)
        if run is None:
            raise ValueError("the request names no stored GoodNotes ingestion run")
        changes = repository.run_note_changes(principal_id, run_id)
        new_changes = tuple(
            item for item in changes if item.change_state is GoodNotesNoteChangeState.NEW
        )
        proposals = repository.semantic_proposals_for_run(principal_id, run_id)
        directory = repository.entity_directory(principal_id)
        now = clock()
        summary_notes: list[NewOnlySummaryNote] = []
        associations: list[GoodNotesEntityAssociation] = []
        for change in new_changes:
            if change.occurrence_id is None or change.note_id is None:
                raise ValueError("the request names no stored GoodNotes ingestion run")
            occurrence = repository.occurrence(principal_id, change.occurrence_id)
            if occurrence is None:
                raise ValueError("the request names no stored GoodNotes ingestion run")
            if change.revision_id is None:
                raise ValueError("the request names no stored GoodNotes note revision")
            revision = repository.revision(principal_id, change.revision_id)
            if revision is None:
                raise ValueError("the request names no stored GoodNotes note revision")
            matched = _matching_note_unit(occurrence, proposals)
            schema_version = "" if matched is None else matched[0]
            segment: Mapping[str, object] = {} if matched is None else matched[1]
            status = _note_unit_status(schema_version, segment)
            confidence = _confidence(segment) if schema_version == NOTE_UNIT_SCHEMA_V2 else None
            uncertain = (
                status is GoodNotesTranscriptionStatus.UNCERTAIN
                or status is GoodNotesTranscriptionStatus.UNREADABLE
                or new_note_is_uncertain(
                    primary_class=revision.primary_class,
                    confidence=confidence,
                )
            )
            summary_notes.append(
                NewOnlySummaryNote(
                    note_id=change.note_id,
                    occurrence_id=change.occurrence_id,
                    primary_class=revision.primary_class,
                    uncertain=uncertain,
                    transcription=revision.transcription,
                )
            )
            ranked = _ranked_candidates(segment) if schema_version == NOTE_UNIT_SCHEMA_V2 else ()
            seen: set[tuple[int, str]] = set()
            for rank, candidate in ranked:
                key = (rank, candidate)
                if key in seen:
                    continue
                seen.add(key)
                resolution, kind, resolved_id = resolve_entity_candidate(candidate, directory)
                associations.append(
                    GoodNotesEntityAssociation(
                        association_id=issue_stable_id(
                            "gnent",
                            principal_id,
                            run_id,
                            change.note_id,
                            str(rank),
                            candidate,
                        ),
                        principal_id=principal_id,
                        run_id=run_id,
                        note_id=change.note_id,
                        candidate=candidate,
                        rank=rank,
                        resolution=resolution,
                        created_at=now,
                        entity_kind=kind,
                        resolved_id=resolved_id,
                    )
                )
        body = build_new_only_summary(summary_notes)
        digest = summary_digest(body)
        existing = repository.delivery_receipt_by_key(principal_id, run_id, destination, digest)
        if existing is not None:
            stored_associations = repository.entity_associations_for_run(principal_id, run_id)
            return GoodNotesDeliveryResult(
                receipt=GoodNotesDeliveryReceipt(
                    receipt_id=existing.receipt_id,
                    principal_id=existing.principal_id,
                    run_id=existing.run_id,
                    destination=existing.destination,
                    summary_hash=existing.summary_hash,
                    suppressed=existing.suppressed,
                    created_at=existing.created_at,
                    body=existing.body,
                    replayed=True,
                ),
                associations=stored_associations,
            )
        written = tuple(repository.store_entity_association(item) for item in associations)
        receipt = repository.store_delivery_receipt(
            GoodNotesDeliveryReceipt(
                receipt_id=issue_stable_id("gndlv", principal_id, run_id, destination, digest),
                principal_id=principal_id,
                run_id=run_id,
                destination=destination,
                summary_hash=digest,
                suppressed=body is None,
                created_at=now,
                body=body,
            )
        )
        return GoodNotesDeliveryResult(receipt=receipt, associations=written)


class GoodNotesDeliveryAttemptLedger:
    """Record crash windows independently of semantic notes. Does not send."""

    def record(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        idempotency_token: str,
        state: GoodNotesDeliveryAttemptState,
        *,
        repository: GoodNotesDeliveryRepository,
        clock: Callable[[], datetime] = utc_now,
        summary_hash: str | None = None,
        receipt_id: str | None = None,
    ) -> GoodNotesDeliveryAttempt:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        run = repository.run(principal_id, run_id)
        if run is None:
            raise ValueError("the request names no stored GoodNotes ingestion run")
        return repository.store_delivery_attempt(
            GoodNotesDeliveryAttempt(
                attempt_id=issue_stable_id(
                    "gndla",
                    principal_id,
                    run_id,
                    destination,
                    idempotency_token,
                    state.value,
                ),
                principal_id=principal_id,
                run_id=run_id,
                destination=destination,
                idempotency_token=idempotency_token,
                state=state,
                created_at=clock(),
                summary_hash=summary_hash,
                receipt_id=receipt_id,
            )
        )
