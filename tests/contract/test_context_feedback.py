"""context.feedback records reversible retrieval preferences without mutating facts."""

from __future__ import annotations

import json

from tests.conftest import (
    Scene,
    build_service,
    metadata_for,
    operator,
    staged_capture,
    staged_project,
    staged_search,
    staged_situation,
)
from tests.contract.test_application_capabilities import run, succeeded

from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.mcp.tools import input_schema_for, payload_schema_for
from my_pa.adapters.remote_request import remote_tool_schema
from my_pa.application.commands import (
    PrepareContext,
    ReadCapture,
    RecordContextFeedback,
)
from my_pa.application.errors import SafeDetail
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.context.preference import ContextPreferenceAction
from my_pa.domain.context.prepared import ContextLimitationCode, SelectionReasonCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier

ALIAS = "qplan"


def _feedback(
    scene: Scene,
    command: RecordContextFeedback,
    *,
    principal: object | None = None,
) -> ResponseEnvelope:
    service = build_service(scene.world, scene.providers)
    actor = scene.principal if principal is None else principal
    return service.invoke(
        metadata_for(Capability.CONTEXT_FEEDBACK, Purpose.CONTEXT_PREFERENCE, actor),  # type: ignore[arg-type]
        command,
        principal=actor,  # type: ignore[arg-type]
    )


def _prepare(
    scene: Scene, command: PrepareContext, *, principal: object | None = None
) -> ResponseEnvelope:
    service = build_service(scene.world, scene.providers)
    actor = scene.principal if principal is None else principal
    return service.invoke(
        metadata_for(Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION, actor),  # type: ignore[arg-type]
        command,
        principal=actor,  # type: ignore[arg-type]
    )


def test_command_has_no_principal_id() -> None:
    assert "principal_id" not in RecordContextFeedback.__dataclass_fields__


def test_alias_is_redacted_from_repr() -> None:
    command = RecordContextFeedback(
        action=ContextPreferenceAction.CONFIRM_ALIAS,
        target_id=issue_identifier(IdKind.SITUATION),
        idempotency_key="feedback-repr-0001",
        alias=ALIAS,
    )
    rendered = repr(command)
    assert ALIAS not in rendered


def test_same_key_and_payload_replays(scene: Scene) -> None:
    target_id = issue_identifier(IdKind.PROJECT)
    command = RecordContextFeedback(
        action=ContextPreferenceAction.PIN,
        target_id=target_id,
        idempotency_key="feedback-replay-0001",
    )
    first = succeeded(_feedback(scene, command))
    second = succeeded(_feedback(scene, command))
    assert first["event_id"] == second["event_id"]
    assert len(scene.world.preference_events) == 1


def test_same_key_different_payload_conflicts(scene: Scene) -> None:
    first_target = issue_identifier(IdKind.PROJECT)
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.PIN,
                target_id=first_target,
                idempotency_key="feedback-conflict-0001",
            ),
        )
    )
    envelope = _feedback(
        scene,
        RecordContextFeedback(
            action=ContextPreferenceAction.PIN,
            target_id=issue_identifier(IdKind.PROJECT),
            idempotency_key="feedback-conflict-0001",
        ),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.CONFLICT
    assert envelope.error.safe_details == (SafeDetail.IDEMPOTENCY_KEY.value,)
    assert len(scene.world.preference_events) == 1
    assert scene.world.preference_events[0].target_id == first_target


def test_pin_ranks_the_subject_first(scene: Scene) -> None:
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    staged_capture(scene, text="quarterly revenue from the dock")
    situation = staged_situation(scene, title="quarterly planning")
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.PIN,
                target_id=situation.situation_id,
                idempotency_key="feedback-pin-0001",
            ),
        )
    )
    result = succeeded(_prepare(scene, PrepareContext(query="quarterly")))
    first = result["evidence"][0]
    assert first["product_id"] == situation.situation_id
    assert SelectionReasonCode.PINNED_FOCUS.value in first["reason_codes"]
    assert situation.situation_id in result["applied_preferences"]


def test_mark_irrelevant_excludes_the_item(scene: Scene) -> None:
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    capture = staged_capture(scene, text="quarterly revenue from the dock")
    staged_situation(scene, title="quarterly planning")
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.MARK_IRRELEVANT,
                target_id=capture.capture_id,
                idempotency_key="feedback-irrelevant-0001",
            ),
        )
    )
    result = succeeded(_prepare(scene, PrepareContext(query="quarterly")))
    capture_ids = {item.get("capture_id") for item in result["evidence"]}
    assert capture.capture_id not in capture_ids
    assert ContextLimitationCode.PREFERENCE_FILTERED.value in result["limitations"]


def test_confirmed_alias_affects_later_prepare(scene: Scene) -> None:
    situation = staged_situation(scene, title="unrelated title")
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.CONFIRM_ALIAS,
                target_id=situation.situation_id,
                alias=ALIAS,
                idempotency_key="feedback-alias-0001",
            ),
        )
    )
    result = succeeded(_prepare(scene, PrepareContext(query=ALIAS)))
    continuity = next(item for item in result["evidence"] if item["plane"] == "continuity")
    assert continuity["product_id"] == situation.situation_id
    assert SelectionReasonCode.EXPLICIT_SUBJECT.value in continuity["reason_codes"]
    assert SelectionReasonCode.CONFIRMED_ALIAS.value in continuity["reason_codes"]
    assert situation.situation_id in result["applied_preferences"]


def test_unpin_and_clear_reverse(scene: Scene) -> None:
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    situation = staged_situation(scene, title="quarterly planning")
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.PIN,
                target_id=situation.situation_id,
                idempotency_key="feedback-reverse-pin-0001",
            ),
        )
    )
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.UNPIN,
                target_id=situation.situation_id,
                idempotency_key="feedback-reverse-unpin-0001",
            ),
        )
    )
    after_unpin = succeeded(_prepare(scene, PrepareContext(query="quarterly")))
    pinned = [
        item
        for item in after_unpin["evidence"]
        if SelectionReasonCode.PINNED_FOCUS.value in item["reason_codes"]
    ]
    assert pinned == []
    assert len(scene.world.preference_events) == 2

    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.MARK_IRRELEVANT,
                target_id=situation.situation_id,
                idempotency_key="feedback-reverse-irrelevant-0001",
            ),
        )
    )
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.CLEAR,
                target_id=situation.situation_id,
                idempotency_key="feedback-reverse-clear-0001",
            ),
        )
    )
    after_clear = succeeded(_prepare(scene, PrepareContext(query="quarterly")))
    product_ids = {item.get("product_id") for item in after_clear["evidence"]}
    assert situation.situation_id in product_ids
    assert ContextLimitationCode.PREFERENCE_FILTERED.value not in after_clear["limitations"]


def test_preferences_do_not_change_canonical_records(scene: Scene) -> None:
    capture = staged_capture(scene, text="canonical capture text")
    project = staged_project(scene, name="canonical project title")
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.PIN,
                target_id=project.project_id,
                idempotency_key="feedback-canonical-0001",
            ),
        )
    )
    listed = scene.world.projects
    assert listed[0].name == "canonical project title"
    read = succeeded(
        run(
            build_service(scene.world, scene.providers),
            scene,
            Capability.CAPTURE_READ,
            Purpose.CAPTURE_REVIEW,
            ReadCapture(capture_id=capture.capture_id),
        )
    )
    assert read["text"] == "canonical capture text"


def test_principal_a_preferences_do_not_affect_principal_b(scene: Scene) -> None:
    scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
    situation = staged_situation(scene, title="quarterly planning")
    succeeded(
        _feedback(
            scene,
            RecordContextFeedback(
                action=ContextPreferenceAction.PIN,
                target_id=situation.situation_id,
                idempotency_key="feedback-isolation-a-0001",
            ),
        )
    )
    other = operator()
    result = succeeded(_prepare(scene, PrepareContext(query="quarterly"), principal=other))
    assert result["applied_preferences"] == []
    assert all(
        SelectionReasonCode.PINNED_FOCUS.value not in item["reason_codes"]
        for item in result["evidence"]
    )


def test_mcp_schema_has_no_principal_or_grants() -> None:
    payload = payload_schema_for(RecordContextFeedback)
    names = set(payload.get("properties", {}))
    assert "principal_id" not in names
    assert "grants" not in names
    assert "capability_grants" not in names
    remote = json.dumps(remote_tool_schema(input_schema_for(RecordContextFeedback)))
    assert "grants" not in remote
    assert "capability_grants" not in remote
    assert '"principal_id"' not in remote


def test_write_purpose_hides_the_remote_tool_unless_writes_enabled(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    disabled = remote_tool_names(service, writes_enabled=False)
    assert Capability.CONTEXT_FEEDBACK.value not in disabled
    enabled = remote_tool_names(service, writes_enabled=True)
    assert Capability.CONTEXT_FEEDBACK.value in enabled
    assert Capability.CAPTURE_CREATE.value in enabled
