"""CRL-WP-03 CP-CRL-03: lifecycle Record Event staging (FAST half).

An APPLIED archive or restore stages one `capture` `state_changed` event.
A NO_OP, a replay, a stale revision, a changed intent, a foreign root and a
rolled-back transition stage none. The database half lands with the
persistence checkpoint's record-event tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.authorization import Authorization
from my_pa.application.capture_lifecycle import CaptureLifecycleResult, transition_capture
from my_pa.application.commands import CreateCapture
from my_pa.application.errors import ConflictError, NotFoundError
from my_pa.domain.capture.lifecycle import CaptureLifecycleOperation, CaptureLifecycleReceipt
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.record_events import (
    CAPTURE_LIFECYCLE_FIELDS,
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

NOW = datetime(2026, 10, 1, 16, 0, tzinfo=UTC)


def _auth(principal: Principal) -> Authorization:
    return Authorization(
        principal=principal,
        capability=Capability.CAPTURE_REVISE,
        purpose=Purpose.CAPTURE_AUTHORING,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id="req-lifecycle-event",
        audit_id=issue_identifier(IdKind.AUDIT),
        at=NOW,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
    )


def _seed(scene: Scene) -> str:
    service = build_service(scene.world, scene.providers)
    response = service.invoke(
        metadata_for(Capability.CAPTURE_CREATE, Purpose.CAPTURE_AUTHORING, scene.principal),
        CreateCapture(text="Synthetic lifecycle event capture", idempotency_key="event-seed"),
        principal=scene.principal,
    )
    assert response.error is None and response.result is not None
    scene.world.record_events.clear()
    return str(response.result["capture_id"])


def _run(
    scene: Scene,
    capture_id: str,
    operation: CaptureLifecycleOperation,
    *,
    expected: int,
    key: str,
    reason: str = "Withdrawn from active use",
) -> CaptureLifecycleResult:
    with FakeUnitOfWork(scene.world) as unit_of_work:
        return transition_capture(
            unit_of_work,
            _auth(scene.principal),
            operation=operation,
            capture_id=capture_id,
            expected_lifecycle_revision=expected,
            reason=reason,
            idempotency_key=key,
            now=NOW,
        )


def _lifecycle(scene: Scene) -> list[RecordEventDraft]:
    return [
        event
        for event in scene.world.record_events
        if event.record_family is RecordEventFamily.CAPTURE
        and event.event_kind is RecordEventKind.STATE_CHANGED
    ]


def test_applied_archive_and_restore_each_stage_one_state_changed_event(scene: Scene) -> None:
    capture_id = _seed(scene)
    authorization = _auth(scene.principal)
    with FakeUnitOfWork(scene.world) as unit_of_work:
        archived = transition_capture(
            unit_of_work,
            authorization,
            operation=CaptureLifecycleOperation.ARCHIVE,
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            reason="Withdrawn from active use",
            idempotency_key="a1",
            now=NOW,
        )
    event = _lifecycle(scene)[0]
    assert len(_lifecycle(scene)) == 1
    assert event.record_id == capture_id
    assert event.record_version == 1
    assert event.changed_fields == CAPTURE_LIFECYCLE_FIELDS
    assert event.source_capability == "capture.archive"
    assert event.source_receipt_id == archived.receipt.receipt_id
    assert event.actor_class is RecordEventActorClass.PRINCIPAL
    assert event.classification is Classification.PRIVATE_LOCAL
    assert event.principal_id == scene.principal.principal_id
    assert event.correlation_id == authorization.correlation_id
    assert "reason" not in event.changed_fields
    restored = _run(scene, capture_id, CaptureLifecycleOperation.RESTORE, expected=1, key="r1")
    assert len(_lifecycle(scene)) == 2
    assert _lifecycle(scene)[1].source_capability == "capture.restore"
    assert _lifecycle(scene)[1].source_receipt_id == restored.receipt.receipt_id
    assert _lifecycle(scene)[1].record_version == 1


def test_no_op_replay_stale_conflict_and_not_found_stage_nothing(scene: Scene) -> None:
    capture_id = _seed(scene)
    _run(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="a1")
    scene.world.record_events.clear()
    _run(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=1, key="noop")
    _run(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="a1")
    with pytest.raises(ConflictError):
        _run(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=9, key="stale")
    with pytest.raises(ConflictError):
        _run(
            scene,
            capture_id,
            CaptureLifecycleOperation.ARCHIVE,
            expected=0,
            key="a1",
            reason="Different reason",
        )
    stranger = Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        kind=scene.principal.kind,
        authenticated=True,
    )
    with pytest.raises(NotFoundError), FakeUnitOfWork(scene.world) as unit_of_work:
        transition_capture(
            unit_of_work,
            _auth(stranger),
            operation=CaptureLifecycleOperation.ARCHIVE,
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            reason="Withdrawn from active use",
            idempotency_key="foreign",
            now=NOW,
        )
    assert _lifecycle(scene) == []


def test_a_failure_after_the_event_stages_no_record_event(scene: Scene) -> None:
    capture_id = _seed(scene)
    repository = type(FakeUnitOfWork(scene.world).capture_lifecycle)
    original = repository.record_receipt

    def explode(self: object, receipt: CaptureLifecycleReceipt, *, principal_id: str) -> None:
        raise RuntimeError("injected")

    repository.record_receipt = explode  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError):
            _run(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="boom")
    finally:
        repository.record_receipt = original  # type: ignore[method-assign]
    assert _lifecycle(scene) == []
