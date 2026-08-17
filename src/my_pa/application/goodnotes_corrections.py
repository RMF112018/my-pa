"""Source-agnostic operator corrections on canonical GoodNotes notes.

Appends a semantic revision (and an optional structural link). Does not
re-run occurrence reconciliation, does not rewrite run-note-changes, and
does not overwrite or delete prior revisions, occurrence geometry, or crops.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.goodnotes.models import (
    GoodNotesNoteClass,
    GoodNotesNoteLink,
    GoodNotesNoteLinkKind,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    issue_stable_id,
    note_link_target_key,
)

OPERATOR_CORRECTION_ANALYZER = "operator-correction"
OPERATOR_CORRECTION_VERSION = "1"


class GoodNotesCorrectionRepository(Protocol):
    def occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteOccurrence | None: ...

    def latest_revision_for_occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteRevision | None: ...

    def revision(self, principal_id: str, revision_id: str) -> GoodNotesNoteRevision | None: ...

    def store_revision(self, revision: GoodNotesNoteRevision) -> GoodNotesNoteRevision: ...

    def store_note_link(self, link: GoodNotesNoteLink) -> GoodNotesNoteLink: ...


@dataclass(frozen=True, slots=True)
class GoodNotesCorrectionResult:
    revision: GoodNotesNoteRevision
    prior_revision: GoodNotesNoteRevision
    link: GoodNotesNoteLink | None
    replayed: bool


class GoodNotesCorrectionService:
    def apply(
        self,
        principal_id: str,
        occurrence_id: str,
        *,
        transcription: str,
        repository: GoodNotesCorrectionRepository,
        primary_class: GoodNotesNoteClass | None = None,
        link_kind: GoodNotesNoteLinkKind | None = None,
        target_note_id: str | None = None,
        target_logical_page_id: str | None = None,
        target_occurrence_id: str | None = None,
        target_context_anchor_sha256: str | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> GoodNotesCorrectionResult:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if not transcription:
            raise ValueError("a GoodNotes correction is missing required transcription")
        occurrence = repository.occurrence(principal_id, occurrence_id)
        if occurrence is None:
            raise ValueError("the request names no stored GoodNotes note occurrence")
        if not occurrence.geometry_key:
            raise ValueError("a GoodNotes correction is missing required geometry")
        latest = repository.latest_revision_for_occurrence(principal_id, occurrence_id)
        if latest is None:
            raise ValueError("the request names no stored GoodNotes note revision")
        resolved_class = latest.primary_class if primary_class is None else primary_class
        already_applied = (
            latest.analyzer_name == OPERATOR_CORRECTION_ANALYZER
            and latest.transcription == transcription
            and latest.primary_class == resolved_class
        )
        digest = hashlib.sha256(transcription.encode()).hexdigest()
        revision_id = issue_stable_id(
            "gnrev",
            principal_id,
            occurrence_id,
            OPERATOR_CORRECTION_ANALYZER,
            digest,
            latest.revision_id,
        )
        existing = latest if already_applied else repository.revision(principal_id, revision_id)
        if existing is None:
            stored = repository.store_revision(
                GoodNotesNoteRevision(
                    revision_id=revision_id,
                    principal_id=principal_id,
                    note_id=occurrence.note_id,
                    schema_version=latest.schema_version,
                    analyzer_name=OPERATOR_CORRECTION_ANALYZER,
                    analyzer_version=OPERATOR_CORRECTION_VERSION,
                    transcription=transcription,
                    created_at=clock(),
                    occurrence_id=occurrence.occurrence_id,
                    supersedes_revision_id=latest.revision_id,
                    primary_class=resolved_class,
                )
            )
            prior = latest
            replayed = False
        else:
            stored = existing
            prior_id = existing.supersedes_revision_id
            loaded = latest if prior_id is None else repository.revision(principal_id, prior_id)
            if loaded is None:
                raise ValueError("the request names no stored GoodNotes note revision")
            prior = loaded
            replayed = True
        link = _optional_link(
            principal_id=principal_id,
            note_id=occurrence.note_id,
            link_kind=link_kind,
            target_note_id=target_note_id,
            target_logical_page_id=target_logical_page_id,
            target_occurrence_id=target_occurrence_id,
            target_context_anchor_sha256=target_context_anchor_sha256,
            created_at=stored.created_at,
        )
        stored_link = None if link is None else repository.store_note_link(link)
        return GoodNotesCorrectionResult(
            revision=stored,
            prior_revision=prior,
            link=stored_link,
            replayed=replayed,
        )


def _optional_link(
    *,
    principal_id: str,
    note_id: str,
    link_kind: GoodNotesNoteLinkKind | None,
    target_note_id: str | None,
    target_logical_page_id: str | None,
    target_occurrence_id: str | None,
    target_context_anchor_sha256: str | None,
    created_at: datetime,
) -> GoodNotesNoteLink | None:
    if link_kind is None:
        return None
    target_key = note_link_target_key(
        link_kind=link_kind,
        target_note_id=target_note_id,
        target_logical_page_id=target_logical_page_id,
        target_occurrence_id=target_occurrence_id,
        target_context_anchor_sha256=target_context_anchor_sha256,
    )
    return GoodNotesNoteLink(
        link_id=issue_stable_id("gnlink", principal_id, note_id, link_kind.value, target_key),
        principal_id=principal_id,
        note_id=note_id,
        link_kind=link_kind,
        created_at=created_at,
        target_note_id=target_note_id,
        target_logical_page_id=target_logical_page_id,
        target_occurrence_id=target_occurrence_id,
        target_context_anchor_sha256=target_context_anchor_sha256,
    )
