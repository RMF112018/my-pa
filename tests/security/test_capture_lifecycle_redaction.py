"""CRL-WP-03 CW-AC-10: a lifecycle feed row carries no reason, digest, or key.

Archive and restore each commit one `capture` `state_changed` row whose
`changed_fields` are exactly `CAPTURE_LIFECYCLE_FIELDS` and whose classification
is the content head's. The sentinel reason, its SHA-256, the intent digest and
the idempotency key are absent from `row_to_json(record_events)`, from the
public receipt, from the public error, and from the audit row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from tests.database.test_task_record_events import Runtime

from my_pa.application.commands import ArchiveCapture, CreateCapture, RestoreCapture
from my_pa.domain.capture.lifecycle import CaptureLifecycleOperation, intent_digest
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import CAPTURE_LIFECYCLE_FIELDS
from my_pa.domain.source.registry import issue_identifier

pytestmark = pytest.mark.database

SENTINEL = "SENTINEL lifecycle reason quartz-moth-91"
ARCHIVE_KEY = "lifecycle-redaction-archive"
RESTORE_KEY = "lifecycle-redaction-restore"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def test_the_committed_capture_lifecycle_feed_carries_no_reason_text_digest_or_key(
    runtime: Runtime,
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    created = runtime.ok(
        CreateCapture(
            text="Synthetic lifecycle redaction note",
            idempotency_key="lifecycle-redaction-create",
        ),
        principal_id=principal,
    )
    capture_id = str(created["capture_id"])
    archived = runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key=ARCHIVE_KEY,
            reason=f"  {SENTINEL}  ",
        ),
        principal_id=principal,
    )
    restored = runtime.ok(
        RestoreCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=1,
            idempotency_key=RESTORE_KEY,
            reason=SENTINEL,
        ),
        principal_id=principal,
    )
    stale = runtime.invoke(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-redaction-stale",
            reason=SENTINEL,
        ),
        principal_id=principal,
    )
    assert stale.error is not None
    with runtime.work_engine.connect() as connection:
        rows = [
            json.loads(row[0])
            for row in connection.execute(
                text(
                    "SELECT row_to_json(e)::text FROM knowledge.record_events e "
                    "WHERE principal_id = :p ORDER BY sequence_number"
                ),
                {"p": principal},
            )
        ]
        head = connection.execute(
            text(
                "SELECT classification FROM knowledge.capture_versions "
                "WHERE capture_id = :c ORDER BY version_number DESC LIMIT 1"
            ),
            {"c": capture_id},
        ).scalar_one()
        audits = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT row_to_json(a)::text FROM knowledge.audit_events a "
                    "WHERE principal_id = :p"
                ),
                {"p": principal},
            )
        ]
    lifecycle = [row for row in rows if row["event_kind"] == "state_changed"]
    assert [row["source_capability"] for row in lifecycle] == ["capture.archive", "capture.restore"]
    assert [row["record_version"] for row in lifecycle] == [1, 1]
    assert [row["source_receipt_id"] for row in lifecycle] == [
        archived["receipt_id"],
        restored["receipt_id"],
    ]
    digests = [
        intent_digest(
            owner_principal_id=principal,
            operation=operation,
            capture_id=capture_id,
            expected_lifecycle_revision=expected,
            reason=SENTINEL,
        )
        for operation, expected in (
            (CaptureLifecycleOperation.ARCHIVE, 0),
            (CaptureLifecycleOperation.RESTORE, 1),
        )
    ]
    forbidden = (
        SENTINEL,
        hashlib.sha256(SENTINEL.encode()).hexdigest(),
        *digests,
        ARCHIVE_KEY,
        RESTORE_KEY,
        "Synthetic lifecycle redaction note",
    )
    serialized = json.dumps(rows)
    for value in forbidden:
        assert value not in serialized, value
    for row in lifecycle:
        assert tuple(row["changed_fields"]) == CAPTURE_LIFECYCLE_FIELDS
        assert row["classification"] == head == "private_local"
    public = json.dumps([archived, restored, stale.error.model_dump(mode="json")])
    for value in (SENTINEL, *digests, "Synthetic lifecycle redaction note"):
        assert value not in public
    assert "reason" not in archived
    assert "intent_digest" not in archived
    for audit in audits:
        assert SENTINEL not in audit
