"""CRL-WP-03 CW-AC-02/03: a foreign root and an absent root are one `not_found`.

Archive, restore and read of another Principal's Capture answer the same public
error as a Capture that was never stored. That error does not carry
`capture_withdrawn`, and it does not carry the owner's receipt.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from tests.database.test_task_record_events import Runtime

from my_pa.application.commands import (
    ArchiveCapture,
    CreateCapture,
    ListCaptures,
    ReadCapture,
    RestoreCapture,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.lifecycle import CaptureLifecycleSelector
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier

pytestmark = pytest.mark.database

REASON = "Synthetic isolation withdrawal"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _public(runtime: Runtime, command: object, principal: str) -> dict[str, object]:
    response = runtime.invoke(command, principal_id=principal)  # type: ignore[arg-type]
    assert response.error is not None and response.result is None
    dumped = response.error.model_dump(mode="json")
    assert dumped["code"] == ErrorCode.NOT_FOUND.value
    return dumped


def test_foreign_and_absent_archive_restore_and_read_are_one_not_found(runtime: Runtime) -> None:
    owner = issue_identifier(IdKind.PRINCIPAL)
    stranger = issue_identifier(IdKind.PRINCIPAL)
    created = runtime.ok(
        CreateCapture(
            text="Synthetic isolation note",
            idempotency_key="lifecycle-isolation-create",
        ),
        principal_id=owner,
    )
    capture_id = str(created["capture_id"])
    owned = runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-isolation-archive",
            reason=REASON,
        ),
        principal_id=owner,
    )
    absent = issue_identifier(IdKind.CAPTURE)
    pairs = (
        (
            ArchiveCapture(
                capture_id=capture_id,
                expected_lifecycle_revision=1,
                idempotency_key="lifecycle-isolation-foreign-archive",
                reason=REASON,
            ),
            ArchiveCapture(
                capture_id=absent,
                expected_lifecycle_revision=1,
                idempotency_key="lifecycle-isolation-absent-archive",
                reason=REASON,
            ),
        ),
        (
            RestoreCapture(
                capture_id=capture_id,
                expected_lifecycle_revision=1,
                idempotency_key="lifecycle-isolation-foreign-restore",
                reason=REASON,
            ),
            RestoreCapture(
                capture_id=absent,
                expected_lifecycle_revision=1,
                idempotency_key="lifecycle-isolation-absent-restore",
                reason=REASON,
            ),
        ),
        (ReadCapture(capture_id=capture_id), ReadCapture(capture_id=absent)),
    )
    for foreign_command, absent_command in pairs:
        foreign = _public(runtime, foreign_command, stranger)
        missing = _public(runtime, absent_command, stranger)
        # correlation_id is issued per request. The public error otherwise matches.
        foreign_public = {key: value for key, value in foreign.items() if key != "correlation_id"}
        missing_public = {key: value for key, value in missing.items() if key != "correlation_id"}
        assert foreign_public == missing_public
        published = json.dumps(foreign)
        assert "capture_withdrawn" not in published
        assert owned["receipt_id"] not in published
        assert capture_id not in published
    replay = runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-isolation-archive",
            reason=REASON,
        ),
        principal_id=owner,
    )
    assert replay["receipt_id"] == owned["receipt_id"]
    assert replay["replayed"] is True
    stranger_page = runtime.ok(
        ListCaptures(lifecycle=CaptureLifecycleSelector.ALL),
        principal_id=stranger,
    )
    assert capture_id not in json.dumps(stranger_page)
