"""CRL-WP-03 CP-CRL-03: archive/restore use case and read selectors (FAST).

Driven through `transition_capture` and the existing capture read/list/search
handlers over the fake unit of work. No `capture.archive` capability exists
yet; the use case is reached directly, the way the checkpoint owns it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.authorization import Authorization
from my_pa.application.capture_lifecycle import CaptureLifecycleResult, transition_capture
from my_pa.application.commands import ListCaptures, ReadCapture, ReviseCapture, SearchCaptures
from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleOperation,
    CaptureLifecycleOutcome,
    CaptureLifecycleReceipt,
    CaptureLifecycleSelector,
    CaptureLifecycleState,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, PolicyDecision
from my_pa.domain.record_events import CAPTURE_LIFECYCLE_FIELDS, RecordEventFamily, RecordEventKind
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

NOW = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
REASON = "No longer in active use"


def _auth(principal: Principal) -> Authorization:
    return Authorization(
        principal=principal,
        capability=Capability.CAPTURE_REVISE,
        purpose=Purpose.CAPTURE_AUTHORING,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        request_id="req-lifecycle",
        audit_id=issue_identifier(IdKind.AUDIT),
        at=NOW,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
    )


def _service(scene: Scene) -> ApplicationService:
    return build_service(scene.world, scene.providers)


def _invoke(service: ApplicationService, principal: Principal, command: object) -> ResponseEnvelope:
    capability = type(command).capability
    purpose = (
        Purpose.CAPTURE_AUTHORING
        if capability is Capability.CAPTURE_REVISE
        else Purpose.CAPTURE_REVIEW
    )
    return service.invoke(
        metadata_for(capability, purpose, principal), command, principal=principal
    )


def _seed(scene: Scene, key: str = "lifecycle-seed") -> str:
    from my_pa.application.commands import CreateCapture

    service = _service(scene)
    response = service.invoke(
        metadata_for(Capability.CAPTURE_CREATE, Purpose.CAPTURE_AUTHORING, scene.principal),
        CreateCapture(text="Synthetic lifecycle capture", idempotency_key=key),
        principal=scene.principal,
    )
    assert response.error is None, response.error
    assert response.result is not None
    scene.world.record_events.clear()
    return str(response.result["capture_id"])


def _transition(
    scene: Scene,
    capture_id: str,
    operation: CaptureLifecycleOperation,
    *,
    expected: int,
    key: str,
    reason: str = REASON,
    principal: Principal | None = None,
) -> CaptureLifecycleResult:
    who = principal or scene.principal
    with FakeUnitOfWork(scene.world) as unit_of_work:
        return transition_capture(
            unit_of_work,
            _auth(who),
            operation=operation,
            capture_id=capture_id,
            expected_lifecycle_revision=expected,
            reason=reason,
            idempotency_key=key,
            now=NOW,
        )


def test_archive_then_restore_keeps_one_version_and_alternates(scene: Scene) -> None:
    capture_id = _seed(scene)
    versions_before = len(scene.world.capture_versions)
    archived = _transition(
        scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="archive-1"
    )
    assert archived.replayed is False
    assert archived.receipt.outcome is CaptureLifecycleOutcome.APPLIED
    assert archived.receipt.resulting_lifecycle_revision == 1
    restored = _transition(
        scene, capture_id, CaptureLifecycleOperation.RESTORE, expected=1, key="restore-1"
    )
    assert restored.receipt.outcome is CaptureLifecycleOutcome.APPLIED
    assert restored.receipt.resulting_lifecycle_revision == 2
    assert len(scene.world.capture_versions) == versions_before
    events = [
        event for event in scene.world.capture_lifecycle_events if event.capture_id == capture_id
    ]
    assert [event.resulting_state for event in events] == [
        CaptureLifecycleState.ARCHIVED,
        CaptureLifecycleState.ACTIVE,
    ]
    assert REASON not in repr(archived.receipt)


def test_fresh_same_state_is_a_receipted_no_op_and_replay_returns_the_original(
    scene: Scene,
) -> None:
    capture_id = _seed(scene)
    first = _transition(
        scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="archive-1"
    )
    again = _transition(
        scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=1, key="archive-noop"
    )
    assert again.replayed is False
    assert again.receipt.outcome is CaptureLifecycleOutcome.NO_OP
    assert again.receipt.resulting_lifecycle_revision == 1
    assert len(scene.world.capture_lifecycle_events) == 1
    replay = _transition(
        scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="archive-1"
    )
    assert replay.replayed is True
    assert replay.receipt.receipt_id == first.receipt.receipt_id
    _transition(scene, capture_id, CaptureLifecycleOperation.RESTORE, expected=1, key="restore-1")
    after_inverse = _transition(
        scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="archive-1"
    )
    assert after_inverse.replayed is True
    assert after_inverse.receipt.receipt_id == first.receipt.receipt_id
    assert after_inverse.receipt.outcome is CaptureLifecycleOutcome.APPLIED
    assert len([e for e in scene.world.capture_lifecycle_events if e.capture_id == capture_id]) == 2


def test_stale_revision_and_changed_intent_conflict_and_write_nothing(scene: Scene) -> None:
    capture_id = _seed(scene)
    with pytest.raises(ConflictError) as stale:
        _transition(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=4, key="stale")
    assert stale.value.safe_details == (SafeDetail.EXPECTED_LIFECYCLE_REVISION,)
    _transition(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="archive-1")
    with pytest.raises(ConflictError) as changed:
        _transition(
            scene,
            capture_id,
            CaptureLifecycleOperation.ARCHIVE,
            expected=0,
            key="archive-1",
            reason="A different reason",
        )
    assert changed.value.safe_details == (SafeDetail.IDEMPOTENCY_KEY,)
    assert len(scene.world.capture_lifecycle_events) == 1
    assert scene.world.capture_lifecycle_pending_events == []


def test_a_foreign_root_is_not_found_and_a_bad_field_is_invalid(scene: Scene) -> None:
    capture_id = _seed(scene)
    stranger = Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        kind=scene.principal.kind,
        authenticated=True,
    )
    with pytest.raises(NotFoundError) as missing:
        _transition(
            scene,
            capture_id,
            CaptureLifecycleOperation.ARCHIVE,
            expected=0,
            key="foreign",
            principal=stranger,
        )
    assert missing.value.safe_details == (SafeDetail.CAPTURE_ID,)
    with pytest.raises(NotFoundError):
        _transition(
            scene,
            issue_identifier(IdKind.CAPTURE),
            CaptureLifecycleOperation.ARCHIVE,
            expected=0,
            key="absent",
        )
    with pytest.raises(InvalidRequestError) as revision:
        _transition(
            scene,
            capture_id,
            CaptureLifecycleOperation.ARCHIVE,
            expected=True,  # type: ignore[arg-type]
            key="bad-revision",
        )
    assert revision.value.safe_details == (SafeDetail.EXPECTED_LIFECYCLE_REVISION,)
    with pytest.raises(InvalidRequestError) as reason:
        _transition(
            scene,
            capture_id,
            CaptureLifecycleOperation.ARCHIVE,
            expected=0,
            key="bad-reason",
            reason="   ",
        )
    assert reason.value.safe_details == (SafeDetail.REASON,)
    assert scene.world.capture_lifecycle_events == []


def test_an_injected_failure_after_staging_commits_nothing(scene: Scene) -> None:
    capture_id = _seed(scene)

    def explode(self: object, receipt: CaptureLifecycleReceipt, *, principal_id: str) -> None:
        raise RuntimeError("injected after the event")

    original = type(FakeUnitOfWork(scene.world).capture_lifecycle).record_receipt
    type(FakeUnitOfWork(scene.world).capture_lifecycle).record_receipt = explode  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="injected"):
            _transition(
                scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="boom"
            )
    finally:
        type(FakeUnitOfWork(scene.world).capture_lifecycle).record_receipt = original  # type: ignore[method-assign]
    assert scene.world.capture_lifecycle_events == []
    assert scene.world.capture_lifecycle_receipts == {}
    assert scene.world.record_events == []
    assert scene.world.capture_lifecycle_pending_events == []


def test_archived_revise_is_denied_and_reads_disclose_current_lifecycle(scene: Scene) -> None:
    capture_id = _seed(scene)
    service = _service(scene)
    _transition(scene, capture_id, CaptureLifecycleOperation.ARCHIVE, expected=0, key="archive-1")
    scene.world.record_events.clear()
    revised = _invoke(
        service,
        scene.principal,
        ReviseCapture(
            capture_id=capture_id,
            text="Should not land",
            idempotency_key="revise-archived",
        ),
    )
    assert revised.error is not None and revised.error.code is ErrorCode.DENIED
    assert revised.error.safe_details == (SafeDetail.CAPTURE_WITHDRAWN.value,)
    assert len(scene.world.capture_versions) == 1
    assert scene.world.record_events == []

    current = _invoke(service, scene.principal, ReadCapture(capture_id=capture_id))
    assert current.error is None and current.result is not None
    assert current.result["lifecycle_state"] == "archived"
    assert current.result["lifecycle_revision"] == 1
    assert current.result["archived_at"] is not None
    assert "lifecycle_history" not in current.result

    history = _invoke(
        service,
        scene.principal,
        ReadCapture(capture_id=capture_id, include_lifecycle_history=True),
    )
    assert history.result is not None
    assert history.result["lifecycle_history_truncated"] is False
    assert len(history.result["lifecycle_history"]) == 1
    assert "reason" not in history.result["lifecycle_history"][0]

    active = _invoke(service, scene.principal, ListCaptures())
    assert active.result is not None and active.result["captures"] == []
    archived = _invoke(
        service, scene.principal, ListCaptures(lifecycle=CaptureLifecycleSelector.ARCHIVED)
    )
    assert archived.result is not None
    assert [row["capture_id"] for row in archived.result["captures"]] == [capture_id]
    assert archived.result["captures"][0]["lifecycle_state"] == "archived"

    found = _invoke(
        service,
        scene.principal,
        SearchCaptures(query="lifecycle", lifecycle=CaptureLifecycleSelector.ALL),
    )
    assert found.result is not None
    assert found.result["matches"][0]["lifecycle_state"] == "archived"
    hidden = _invoke(service, scene.principal, SearchCaptures(query="lifecycle"))
    assert hidden.result is not None and hidden.result["matches"] == []


def test_selector_vocabulary_is_closed() -> None:
    with pytest.raises(InvalidRequestError) as bad:
        ListCaptures(lifecycle="deleted")  # type: ignore[arg-type]
    assert bad.value.safe_details == (SafeDetail.LIFECYCLE,)
    with pytest.raises(InvalidRequestError):
        ReadCapture(
            capture_id=issue_identifier(IdKind.CAPTURE),
            include_lifecycle_history="yes",  # type: ignore[arg-type]
        )


def test_lifecycle_events_are_the_three_read_fields() -> None:
    assert CAPTURE_LIFECYCLE_FIELDS == ("archived_at", "lifecycle_revision", "lifecycle_state")
    assert RecordEventKind.STATE_CHANGED.value == "state_changed"
    assert RecordEventFamily.CAPTURE.value == "capture"
    # DeniedError is the public type the revise fence raises; imported so a
    # rename of that refusal fails this module at collection.
    assert DeniedError is not None
