"""Shared seeds and request builders for the record lineage S1 link tests.

A helper module, not a test module: pytest does not collect it. It builds on
`lineage_issue_harness.LineageRuntime` (the real `ApplicationService` over
PostgreSQL with `lineage_enabled` on) and adds what the membership,
association, reverse-read and note-history tests need: synthetic Meetings
with note versions, Captures, Commitments and Tasks created through their own
capabilities, exact evidence anchors computed from the stored bodies, and row
counts over every S1 table.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import Engine, func, select, text

from my_pa.application.commands import (
    AddIssueMembership,
    AssertRecordAssociation,
    CreateCapture,
    CreateCommitment,
    CreateMeeting,
    CreateTask,
    ReadMeeting,
    ReadMeetingNoteVersion,
    UpdateMeeting,
)
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.meeting.model import MeetingNotesMode
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.tables import (
    issue_project_membership_events,
    issue_revisions,
    lineage_evidence_anchors,
    lineage_write_requests,
    project_situations,
    record_link_heads,
    record_link_revision_evidence,
    record_link_revisions,
    record_links,
)
from tests.database.lineage_issue_harness import PRINCIPAL, LineageRuntime
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

__all__ = [
    "GATEWAY",
    "NOTE_BODY",
    "all_lineage_counts",
    "capture",
    "capture_anchor",
    "commitment",
    "legacy_anchor",
    "meeting",
    "membership",
    "note",
    "note_anchor",
    "originated_from",
    "revise_notes",
    "task",
]

#: The stamped operator surface an attested S1 write needs (local operator).
GATEWAY: Final = OperatorSurface.HTTP_GATEWAY

#: A synthetic note body with a multi-byte passage, so code points and bytes differ.
NOTE_BODY: Final = "Decisions: Ana will send the façade survey by Friday. Next: pour."

_STARTS: Final = datetime(2026, 10, 1, 15, tzinfo=UTC)

_ALL_TABLES: Final = (
    issue_revisions,
    issue_project_membership_events,
    project_situations,
    lineage_evidence_anchors,
    lineage_write_requests,
    record_links,
    record_link_revisions,
    record_link_revision_evidence,
    record_link_heads,
)


def all_lineage_counts(engine: Engine) -> Mapping[str, int]:
    """Row counts of every S1 table."""
    with engine.connect() as connection:
        return {
            table.name: int(
                connection.execute(select(func.count()).select_from(table)).scalar_one()
            )
            for table in _ALL_TABLES
        }


# --- seeds ------------------------------------------------------------------


def meeting(
    runtime: LineageRuntime, key: str, *, body: str = NOTE_BODY, principal_id: str = PRINCIPAL
) -> tuple[str, str]:
    """A Meeting with one note version: `(meeting_id, note_version_id)`."""
    written = runtime.ok(
        CreateMeeting(
            title=f"Synthetic meeting {key}",
            start_at=_STARTS,
            timezone_name="UTC",
            idempotency_key=f"lineage-mtg-{key}",
            notes_markdown=body,
        ),
        principal_id=principal_id,
    )
    view = written["meeting"]
    return str(view["meeting_id"]), str(view["notes"]["note_version_id"])


def revise_notes(
    runtime: LineageRuntime,
    meeting_id: str,
    key: str,
    *,
    body: str,
    mode: MeetingNotesMode = MeetingNotesMode.REPLACE,
    principal_id: str = PRINCIPAL,
) -> str:
    """A later note version (`replace` or `append`); its `note_version_id`."""
    current = runtime.ok(ReadMeeting(meeting_id=meeting_id), principal_id=principal_id)
    written = runtime.ok(
        UpdateMeeting(
            meeting_id=meeting_id,
            expected_version=int(current["meeting"]["version"]),
            idempotency_key=f"lineage-mtg-notes-{key}",
            notes_mode=mode,
            notes_markdown=body,
        ),
        principal_id=principal_id,
    )
    return str(written["meeting"]["notes"]["note_version_id"])


def note(
    runtime: LineageRuntime, meeting_id: str, note_version_id: str, principal_id: str = PRINCIPAL
) -> dict[str, Any]:
    """`meetings.notes.read_version` with the body: the stored digest and text."""
    written = runtime.ok(
        ReadMeetingNoteVersion(
            meeting_id=meeting_id, note_version_id=note_version_id, include_body=True
        ),
        principal_id=principal_id,
    )
    return dict(written["note"])


def capture(
    runtime: LineageRuntime, key: str, *, body: str = NOTE_BODY, principal_id: str = PRINCIPAL
) -> tuple[str, str, str]:
    """A Capture: `(capture_id, version_id, content_sha256)`."""
    written = runtime.ok(
        CreateCapture(text=body, idempotency_key=f"lineage-cap-{key}"),
        principal_id=principal_id,
    )
    return str(written["capture_id"]), str(written["version_id"]), str(written["content_sha256"])


def commitment(runtime: LineageRuntime, key: str, *, principal_id: str = PRINCIPAL) -> str:
    """A Commitment with a legacy `cap_` origin, as the Work writers accept today."""
    origin, _, _ = capture(runtime, f"cmt-origin-{key}", principal_id=principal_id)
    counterparty = seed_counterparty_entity(runtime.engine, principal_id)
    written = runtime.ok(
        CreateCommitment(
            counterparty_entity_id=counterparty,
            direction=CommitmentDirection.OWED_BY_PRINCIPAL,
            summary=f"Synthetic commitment {key}",
            origin_evidence_ref=origin,
            idempotency_key=f"lineage-cmt-{key}",
        ),
        principal_id=principal_id,
    )
    return str(written["commitment"]["commitment_id"])


def task(runtime: LineageRuntime, key: str, *, principal_id: str = PRINCIPAL) -> str:
    written = runtime.ok(
        CreateTask(
            title=f"Synthetic task {key}",
            idempotency_key=f"lineage-tsk-{key}",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        ),
        principal_id=principal_id,
    )
    return str(written["task"]["task_id"])


def restricted_capture_version(engine: Engine, version_id: str) -> str:
    """Append a `restricted_local` version after `version_id`, by SQL (no capability does)."""
    new_id = "capver_" + hashlib.sha256(version_id.encode()).hexdigest()[:24]
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_versions (version_id, capture_id, version_number, "
                "supersedes_version_id, content, content_sha256, owner_principal_id, "
                "classification, processing_policy, idempotency_key, correlation_id, audit_id, "
                "client_created_at, server_received_at, occurred_at, accepted_at, recorded_at) "
                "SELECT :new_id, capture_id, version_number + 1, version_id, content, "
                "content_sha256, owner_principal_id, 'restricted_local', processing_policy, "
                "idempotency_key || '-restricted', correlation_id, audit_id, client_created_at, "
                "server_received_at, occurred_at, accepted_at, recorded_at "
                "FROM knowledge.capture_versions WHERE version_id = :version_id"
            ),
            {"new_id": new_id, "version_id": version_id},
        )
    return new_id


# --- anchors -------------------------------------------------------------------


def _passage(body: str, passage: str) -> tuple[int, int, str]:
    start = body.index(passage)
    end = start + len(passage)
    return start, end, hashlib.sha256(body[start:end].encode("utf-8")).hexdigest()


def note_anchor(
    meeting_id: str,
    note_version_id: str,
    body: str,
    *,
    passage: str | None = "façade survey",
    role: str = "origin",
    source_sha256: str | None = None,
) -> dict[str, object]:
    """An exact note-version anchor, digests computed from the stored body."""
    document: dict[str, object] = {
        "family": "meeting_note_version",
        "root_id": meeting_id,
        "version_kind": "immutable_version",
        "version_id": note_version_id,
        "source_sha256": source_sha256 or hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "role": role,
    }
    if passage is not None:
        start, end, digest = _passage(body, passage)
        document.update(passage_start_cp=start, passage_end_cp=end, passage_sha256=digest)
    return document


def capture_anchor(
    capture_id: str,
    version_id: str,
    body: str,
    *,
    passage: str | None = "façade survey",
    role: str = "origin",
) -> dict[str, object]:
    document: dict[str, object] = {
        "family": "capture_version",
        "root_id": capture_id,
        "version_kind": "immutable_version",
        "version_id": version_id,
        "source_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "role": role,
    }
    if passage is not None:
        start, end, digest = _passage(body, passage)
        document.update(passage_start_cp=start, passage_end_cp=end, passage_sha256=digest)
    return document


def legacy_anchor(capture_id: str, *, role: str = "corroborates") -> dict[str, object]:
    return {
        "family": "capture",
        "root_id": capture_id,
        "version_kind": "legacy_unversioned",
        "role": role,
    }


# --- requests --------------------------------------------------------------------


def membership(
    issue_id: str,
    family: str,
    record_id: str,
    key: str,
    *,
    role: str = "work",
    anchors: tuple[dict[str, object], ...] = (),
) -> AddIssueMembership:
    return AddIssueMembership(
        issue_id=issue_id,
        member={"family": family, "record_id": record_id},
        role=role,
        idempotency_key=f"lineage-member-{key}",
        evidence_anchors=anchors,
    )


def originated_from(
    from_family: str,
    from_id: str,
    to_family: str,
    to_id: str,
    key: str,
    anchors: tuple[dict[str, object], ...],
    *,
    context_issue_id: str | None = None,
) -> AssertRecordAssociation:
    return AssertRecordAssociation(
        from_record={"family": from_family, "record_id": from_id},
        to_record={"family": to_family, "record_id": to_id},
        relation_type="originated_from",
        idempotency_key=f"lineage-assoc-{key}",
        evidence_anchors=anchors,
        context_issue_id=context_issue_id,
    )
