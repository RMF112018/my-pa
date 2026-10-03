"""CRL-WP-03 CRL-AC-D1..D4: capture lifecycle events on a real database.

An APPLIED archive or restore commits one `capture` `state_changed` event whose
`record_version` is the content head. A NO_OP, a replay, a stale revision, a
changed intent, a denied revise, a foreign root and a rolled-back transition
commit nothing and do not advance the sequence. A remote caller does not see a
lifecycle event of a capture whose current version is restricted, and a cursor
anchored on that event is `invalid_request(cursor)`; a local caller still
resumes. A `capture.list(lifecycle="all")` snapshot sees the archived root, and
the delta after W0 delivers the transition.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from my_pa.application.authorization import Authorization
from my_pa.application.capture_lifecycle import transition_capture
from my_pa.application.commands import (
    ArchiveCapture,
    CreateCapture,
    ListCaptures,
    ReadCapture,
    RestoreCapture,
    ReviseCapture,
)
from my_pa.application.errors import SafeDetail
from my_pa.application.record_events import encode_cursor
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.lifecycle import CaptureLifecycleOperation, CaptureLifecycleSelector
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.record_events import CAPTURE_LIFECYCLE_FIELDS
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_record_events_bootstrap_race import (
    CAPTURE_GRANTS,
    _raise_to_restricted,
)
from tests.database.test_record_events_cursor_visibility import assert_refused, binding_of, listing
from tests.database.test_task_record_events import Runtime, feed, next_sequence

pytestmark = pytest.mark.database

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
REASON = "Synthetic lifecycle record-event reason"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _create(runtime: Runtime, principal: str, key: str) -> str:
    created = runtime.ok(
        CreateCapture(text=f"Synthetic lifecycle feed note {key}", idempotency_key=key),
        principal_id=principal,
    )
    return str(created["capture_id"])


def _lifecycle(runtime: Runtime, principal: str) -> list[dict[str, object]]:
    return [
        row
        for row in feed(runtime.work_engine, principal)
        if row["record_family"] == "capture" and row["event_kind"] == "state_changed"
    ]


def test_applied_archive_and_restore_each_commit_one_event(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    capture_id = _create(runtime, principal, "lifecycle-d1-create")
    archived = runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d1-archive",
            reason=REASON,
        ),
        principal_id=principal,
    )
    restored = runtime.ok(
        RestoreCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=1,
            idempotency_key="lifecycle-d1-restore",
            reason=REASON,
        ),
        principal_id=principal,
    )
    rows = _lifecycle(runtime, principal)
    assert [row["source_capability"] for row in rows] == ["capture.archive", "capture.restore"]
    assert [row["record_version"] for row in rows] == [1, 1]
    assert [tuple(row["changed_fields"]) for row in rows] == [
        CAPTURE_LIFECYCLE_FIELDS,
        CAPTURE_LIFECYCLE_FIELDS,
    ]
    assert [row["source_receipt_id"] for row in rows] == [
        archived["receipt_id"],
        restored["receipt_id"],
    ]
    assert [row["classification"] for row in rows] == ["private_local", "private_local"]
    reread = runtime.ok(ReadCapture(capture_id=capture_id), principal_id=principal)
    assert reread["capture_id"] == capture_id
    assert reread["lifecycle_state"] == "active"


def test_no_op_replay_stale_conflict_denied_and_not_found_commit_nothing(
    runtime: Runtime,
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    capture_id = _create(runtime, principal, "lifecycle-d2-create")
    runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d2-archive",
            reason=REASON,
        ),
        principal_id=principal,
    )
    before = len(feed(runtime.work_engine, principal))
    sequence = next_sequence(runtime.work_engine, principal)
    noop = runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=1,
            idempotency_key="lifecycle-d2-noop",
            reason=REASON,
        ),
        principal_id=principal,
    )
    assert noop["outcome"] == "no_op"
    assert noop["replayed"] is False
    replay = runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d2-archive",
            reason=REASON,
        ),
        principal_id=principal,
    )
    assert replay["replayed"] is True
    stale = runtime.invoke(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=9,
            idempotency_key="lifecycle-d2-stale",
            reason=REASON,
        ),
        principal_id=principal,
    )
    conflict = runtime.invoke(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d2-archive",
            reason="A different statement",
        ),
        principal_id=principal,
    )
    denied = runtime.invoke(
        ReviseCapture(
            capture_id=capture_id,
            text="Synthetic successor that must not land",
            idempotency_key="lifecycle-d2-revise",
        ),
        principal_id=principal,
    )
    missing = runtime.invoke(
        ArchiveCapture(
            capture_id=issue_identifier(IdKind.CAPTURE),
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d2-absent",
            reason=REASON,
        ),
        principal_id=principal,
    )
    assert stale.error is not None and stale.error.code == ErrorCode.CONFLICT
    assert conflict.error is not None and conflict.error.code == ErrorCode.CONFLICT
    assert denied.error is not None and denied.error.code == ErrorCode.DENIED
    assert SafeDetail.CAPTURE_WITHDRAWN.value in denied.error.safe_details
    assert missing.error is not None and missing.error.code == ErrorCode.NOT_FOUND
    assert len(feed(runtime.work_engine, principal)) == before
    assert next_sequence(runtime.work_engine, principal) == sequence
    assert len(_lifecycle(runtime, principal)) == 1


def test_a_rolled_back_transition_advances_no_sequence(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    capture_id = _create(runtime, principal, "lifecycle-d2-rollback")
    before = len(feed(runtime.work_engine, principal))
    sequence = next_sequence(runtime.work_engine, principal)
    authorization = Authorization(
        principal=Principal(principal, PrincipalKind.OPERATOR, authenticated=True),
        capability=Capability.CAPTURE_ARCHIVE,
        purpose=Purpose.CAPTURE_AUTHORING,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id="req-lifecycle-rollback",
        audit_id=issue_identifier(IdKind.AUDIT),
        at=NOW,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
    )
    audit = SqlAlchemyAuditSink(runtime.work_engine)
    with (
        pytest.raises(RuntimeError, match="injected"),
        SqlAlchemyUnitOfWork(runtime.work_engine, audit=audit) as unit_of_work,
    ):
        transition_capture(
            unit_of_work,
            authorization,
            operation=CaptureLifecycleOperation.ARCHIVE,
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            reason=REASON,
            idempotency_key="lifecycle-d2-rollback-archive",
            now=NOW,
        )
        raise RuntimeError("injected")
    assert len(feed(runtime.work_engine, principal)) == before
    assert next_sequence(runtime.work_engine, principal) == sequence
    assert _lifecycle(runtime, principal) == []


def test_a_remote_caller_does_not_see_a_restricted_captures_lifecycle_event(
    runtime: Runtime,
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    engine = runtime.work_engine
    plain = _create(runtime, principal, "lifecycle-d3-plain")
    hidden = _create(runtime, principal, "lifecycle-d3-hidden")
    runtime.ok(
        ArchiveCapture(
            capture_id=hidden,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d3-archive",
            reason=REASON,
        ),
        principal_id=principal,
    )
    lifecycle_event = _lifecycle(runtime, principal)[0]["event_id"]
    raised = {"capture_id": hidden, "version_id": _version(runtime, hidden)}
    _raise_to_restricted(engine, principal, raised)
    followed = _create(runtime, principal, "lifecycle-d3-later")
    remote = listing(engine, principal, capability_grants=CAPTURE_GRANTS, page_size=20)
    assert hidden not in {item.record_id for item in remote.events}
    assert plain in {item.record_id for item in remote.events}
    assert_refused(
        engine,
        principal,
        encode_cursor(binding_of(remote), str(lifecycle_event)),
        capability_grants=CAPTURE_GRANTS,
        page_size=20,
    )
    local = listing(engine, principal, capability_grants=None, page_size=20)
    resumed = listing(
        engine,
        principal,
        capability_grants=None,
        page_size=20,
        cursor=encode_cursor(binding_of(local), str(lifecycle_event)),
    )
    assert followed in {item.record_id for item in resumed.events}


def test_bootstrap_lists_an_archived_root_and_the_delta_delivers_it(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    capture_id = _create(runtime, principal, "lifecycle-d4-create")
    watermark = listing(
        runtime.work_engine, principal, capability_grants=None, page_size=20
    ).high_watermark_cursor
    runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="lifecycle-d4-archive",
            reason=REASON,
        ),
        principal_id=principal,
    )
    active = runtime.ok(ListCaptures(), principal_id=principal)
    everything = runtime.ok(
        ListCaptures(lifecycle=CaptureLifecycleSelector.ALL),
        principal_id=principal,
    )
    assert capture_id not in {item["capture_id"] for item in active["captures"]}
    archived = [item for item in everything["captures"] if item["capture_id"] == capture_id]
    assert [item["lifecycle_state"] for item in archived] == ["archived"]
    delta = listing(
        runtime.work_engine,
        principal,
        capability_grants=None,
        page_size=20,
        cursor=watermark,
    )
    delivered = [
        item
        for item in delta.events
        if item.record_id == capture_id and item.event_kind.value == "state_changed"
    ]
    assert len(delivered) == 1
    assert delivered[0].record_version == 1


def _version(runtime: Runtime, capture_id: str) -> str:
    with runtime.work_engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT version_id FROM knowledge.capture_versions "
                    "WHERE capture_id = :c AND version_number = 1"
                ),
                {"c": capture_id},
            ).scalar_one()
        )
