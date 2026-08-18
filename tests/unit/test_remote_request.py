"""Remote MCP stamps server-owned metadata; it does not take it from the caller."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import get_args

import pytest

from my_pa.adapters.mcp.remote import _WRITE_PURPOSES
from my_pa.adapters.mcp.tools import input_schema_for
from my_pa.adapters.remote_request import (
    _IDEMPOTENT_REMOTE_CAPABILITIES,
    CANONICAL_REMOTE_PURPOSES,
    REMOTE_OWNED_PAYLOAD_FIELDS,
    SERVER_OWNED_REMOTE_FIELDS,
    compose_remote_arguments,
    remote_tool_schema,
    resolve_remote_purpose,
)
from my_pa.application.commands import Command
from my_pa.application.errors import InvalidRequestError, UnsupportedError
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose

PRINCIPAL = Principal(
    principal_id="prn_24abf5d2d0c25e1c82f6e72425e9ed37",
    kind=PrincipalKind.OPERATOR,
    authenticated=True,
)
FROZEN = datetime(2026, 8, 15, 9, 30, tzinfo=UTC)


def _issue(_kind: object) -> str:
    return "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _remote_read_capabilities() -> tuple[Capability, ...]:
    return tuple(
        capability
        for capability in Capability
        if not is_operator_only(capability)
        and not (permitted_purposes(capability) & _WRITE_PURPOSES)
    )


def test_single_permitted_purpose_is_injected() -> None:
    assert resolve_remote_purpose(Capability.CONTINUITY_PROJECTS, None) is Purpose.CAPTURE_REVIEW


def test_capability_wide_grant_uses_canonical_purpose() -> None:
    grants = frozenset({(Capability.CAPABILITIES_GET, None)})
    assert resolve_remote_purpose(Capability.CAPABILITIES_GET, grants) is Purpose.STATUS_OBSERVATION


def test_single_granted_purpose_wins_over_canonical() -> None:
    grants = frozenset({(Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION)})
    assert resolve_remote_purpose(Capability.SOURCES_FETCH, grants) is Purpose.CONTENT_EXTRACTION


def test_multiple_granted_purposes_use_canonical() -> None:
    grants = frozenset(
        {
            (Capability.SOURCES_FETCH, Purpose.SOURCE_INSPECTION),
            (Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION),
        }
    )
    assert resolve_remote_purpose(Capability.SOURCES_FETCH, grants) is Purpose.SOURCE_INSPECTION


def test_unrestricted_access_uses_canonical_for_capabilities_get() -> None:
    assert resolve_remote_purpose(Capability.CAPABILITIES_GET, None) is Purpose.STATUS_OBSERVATION


def test_missing_grant_is_unsupported() -> None:
    with pytest.raises(UnsupportedError):
        resolve_remote_purpose(Capability.CONTINUITY_PROJECTS, frozenset())


def test_grant_for_another_capability_is_unsupported() -> None:
    grants = frozenset({(Capability.CONTINUITY_PULSE, Purpose.CAPTURE_REVIEW)})
    with pytest.raises(UnsupportedError):
        resolve_remote_purpose(Capability.CONTINUITY_PROJECTS, grants)


def test_wrong_purpose_grant_is_unsupported() -> None:
    grants = frozenset({(Capability.CONTINUITY_PROJECTS, Purpose.KNOWLEDGE_READ)})
    with pytest.raises(UnsupportedError):
        resolve_remote_purpose(Capability.CONTINUITY_PROJECTS, grants)


def test_compose_rejects_caller_owned_server_fields() -> None:
    for field in sorted(SERVER_OWNED_REMOTE_FIELDS):
        with pytest.raises(InvalidRequestError):
            compose_remote_arguments(
                capability_name=Capability.CONTINUITY_PROJECTS.value,
                arguments={field: "forged", "payload": {"page_size": 20}},
                principal=PRINCIPAL,
                grants=None,
                clock=lambda: FROZEN,
                issue_id=_issue,
            )


def test_compose_stamps_server_owned_fields() -> None:
    composed = compose_remote_arguments(
        capability_name=Capability.CONTINUITY_PROJECTS.value,
        arguments={"payload": {"page_size": 20}},
        principal=PRINCIPAL,
        grants=frozenset({(Capability.CONTINUITY_PROJECTS, Purpose.CAPTURE_REVIEW)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert composed["payload"] == {"page_size": 20}
    assert composed["contract_version"] == "v1"
    assert composed["request_id"] == "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert composed["requested_at"] == "2026-08-15T09:30:00.000Z"
    assert composed["principal_id"] == PRINCIPAL.principal_id
    assert composed["purpose"] == Purpose.CAPTURE_REVIEW.value
    assert composed["scope"] == {"source_ids": [], "enrollment_ids": []}


def test_compose_rejects_unknown_capability() -> None:
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name="not.a.capability",
            arguments={},
            principal=PRINCIPAL,
            grants=None,
            clock=lambda: FROZEN,
            issue_id=_issue,
        )


def test_every_multi_purpose_remote_read_has_a_canonical_rule() -> None:
    for capability in _remote_read_capabilities():
        permitted = permitted_purposes(capability)
        if len(permitted) > 1:
            assert capability in CANONICAL_REMOTE_PURPOSES
            assert CANONICAL_REMOTE_PURPOSES[capability] in permitted


def test_every_remote_read_purpose_resolves() -> None:
    for capability in _remote_read_capabilities():
        purpose = resolve_remote_purpose(capability, None)
        assert purpose in permitted_purposes(capability)
        assert not (permitted_purposes(capability) & _WRITE_PURPOSES)
        assert not is_operator_only(capability)


def test_remote_schemas_exclude_server_owned_metadata() -> None:
    commands = {member.capability: member for member in get_args(Command.__value__)}
    for capability in _remote_read_capabilities():
        schema = remote_tool_schema(input_schema_for(commands[capability]))
        properties = schema["properties"]
        assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(properties)
        assert "principal_id" not in properties
        assert schema.get("additionalProperties") is False
        assert "Purpose" not in schema.get("$defs", {})
        assert "Scope" not in schema.get("$defs", {})


def _remote_write_capabilities() -> tuple[Capability, ...]:
    return tuple(
        capability
        for capability in Capability
        if not is_operator_only(capability)
        and bool(permitted_purposes(capability) & _WRITE_PURPOSES)
    )


def test_remote_write_schemas_are_domain_only() -> None:
    commands = {member.capability: member for member in get_args(Command.__value__)}
    for capability in _remote_write_capabilities():
        schema = remote_tool_schema(input_schema_for(commands[capability]))
        properties = schema["properties"]
        assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(properties)
        payload = properties.get("payload", {})
        payload_properties = payload.get("properties", {})
        assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(payload_properties)
        assert "idempotency_key" not in payload_properties
        assert "principal_id" not in properties
        assert "Purpose" not in schema.get("$defs", {})


def test_compose_rejects_caller_owned_idempotency_key() -> None:
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=Capability.CONTINUITY_PROJECTS_CREATE.value,
            arguments={"payload": {"name": "Home", "idempotency_key": "forged"}},
            principal=PRINCIPAL,
            grants=None,
            clock=lambda: FROZEN,
            issue_id=_issue,
        )


def test_compose_stamps_content_addressed_idempotency_key() -> None:
    composed = compose_remote_arguments(
        capability_name=Capability.CONTINUITY_PROJECTS_CREATE.value,
        arguments={"payload": {"name": "Home Renovation"}},
        principal=PRINCIPAL,
        grants=frozenset({(Capability.CONTINUITY_PROJECTS_CREATE, Purpose.CONTINUITY_AUTHORING)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    key = composed["payload"]["idempotency_key"]
    assert key.startswith("idk_")
    replay = compose_remote_arguments(
        capability_name=Capability.CONTINUITY_PROJECTS_CREATE.value,
        arguments={"payload": {"name": "Home Renovation"}},
        principal=PRINCIPAL,
        grants=frozenset({(Capability.CONTINUITY_PROJECTS_CREATE, Purpose.CONTINUITY_AUTHORING)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert replay["payload"]["idempotency_key"] == key
    assert composed["purpose"] == Purpose.CONTINUITY_AUTHORING.value


def test_every_write_purpose_is_classified_as_a_remote_write() -> None:
    assert {
        Purpose.BOUNDED_ENROLLMENT,
        Purpose.CAPTURE_AUTHORING,
        Purpose.REVIEW_DISPOSITION,
        Purpose.DOCUMENT_AUTHORING,
        Purpose.CONTINUITY_AUTHORING,
        Purpose.TASK_AUTHORING,
        Purpose.COMMITMENT_AUTHORING,
        Purpose.CONTEXT_PREFERENCE,
        Purpose.GOODNOTES_PROPOSAL,
    } <= set(_WRITE_PURPOSES)
    assert Purpose.TASK_AUTHORING in _WRITE_PURPOSES
    assert Purpose.COMMITMENT_AUTHORING in _WRITE_PURPOSES


def test_task_and_commitment_writes_are_stamped_remotely() -> None:
    assert {
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_BULK_CONFIRM,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_CLOSE,
        Capability.GOODNOTES_PROPOSE,
    } <= _IDEMPOTENT_REMOTE_CAPABILITIES


def _connected_v2_proposal_payload(
    *,
    run_id: str = "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
    page_version_id: str = "gnver_aaaaaaaaaaaaaaaaaaaaaaaa",
    content_sha256: str = "a" * 64,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "page_version_id": page_version_id,
        "content_sha256": content_sha256,
        "schema_version": "note-unit.v2",
        "analyzer_name": "chatllm-synthetic-validator",
        "analyzer_version": "1.0.0",
        "segments": [
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.5, "height": 0.2},
                "transcription": None,
                "transcription_status": "UNREADABLE",
                "confidence": {"transcription": 0.0, "classification": 0.6},
                "candidate_tags": ["GENERAL"],
                "ranked_candidates": [],
            }
        ],
        "confidence": {
            "transcription": 0.0,
            "segmentation": 0.85,
            "classification": 0.6,
        },
        "candidate_tags": ["GENERAL"],
        "ranked_candidates": [],
    }


def test_goodnotes_propose_remote_schema_hides_idempotency_key() -> None:
    commands = {member.capability: member for member in get_args(Command.__value__)}
    schema = remote_tool_schema(input_schema_for(commands[Capability.GOODNOTES_PROPOSE]))
    payload = schema["properties"]["payload"]
    payload_properties = payload.get("properties", {})
    assert "idempotency_key" not in payload_properties
    assert "idempotency_key" not in payload.get("required", [])


def test_compose_stamps_idempotency_for_goodnotes_propose() -> None:
    payload = _connected_v2_proposal_payload()
    composed = compose_remote_arguments(
        capability_name=Capability.GOODNOTES_PROPOSE.value,
        arguments={"payload": payload},
        principal=PRINCIPAL,
        grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    key = composed["payload"]["idempotency_key"]
    assert key.startswith("idk_")
    assert len(key) == 36
    assert composed["purpose"] == Purpose.GOODNOTES_PROPOSAL.value
    replay = compose_remote_arguments(
        capability_name=Capability.GOODNOTES_PROPOSE.value,
        arguments={"payload": payload},
        principal=PRINCIPAL,
        grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert replay["payload"]["idempotency_key"] == key
    changed = compose_remote_arguments(
        capability_name=Capability.GOODNOTES_PROPOSE.value,
        arguments={
            "payload": {
                **_connected_v2_proposal_payload(),
                "candidate_tags": ["CHANGED"],
            }
        },
        principal=PRINCIPAL,
        grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert changed["payload"]["idempotency_key"] != key


def test_compose_rejects_caller_owned_goodnotes_idempotency_key() -> None:
    payload = _connected_v2_proposal_payload()
    payload["idempotency_key"] = "forged"
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=Capability.GOODNOTES_PROPOSE.value,
            arguments={"payload": payload},
            principal=PRINCIPAL,
            grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
            clock=lambda: FROZEN,
            issue_id=_issue,
        )


def test_remote_goodnotes_proposal_payload_normalizes() -> None:
    from my_pa.adapters.normalization import normalize
    from my_pa.application.commands import SubmitGoodNotesProposal

    composed = compose_remote_arguments(
        capability_name=Capability.GOODNOTES_PROPOSE.value,
        arguments={"payload": _connected_v2_proposal_payload()},
        principal=PRINCIPAL,
        grants=frozenset({(Capability.GOODNOTES_PROPOSE, Purpose.GOODNOTES_PROPOSAL)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    _metadata, command = normalize(Capability.GOODNOTES_PROPOSE.value, composed)
    assert isinstance(command, SubmitGoodNotesProposal)
    assert command.idempotency_key.startswith("idk_")


def test_compose_stamps_idempotency_for_task_create() -> None:
    composed = compose_remote_arguments(
        capability_name=Capability.TASKS_CREATE.value,
        arguments={
            "payload": {
                "title": "Follow up with the architect",
                "origin_evidence_ref": "cap_origin0001origin0001",
            }
        },
        principal=PRINCIPAL,
        grants=frozenset({(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    key = composed["payload"]["idempotency_key"]
    assert key.startswith("idk_")
    assert composed["purpose"] == Purpose.TASK_AUTHORING.value
    replay = compose_remote_arguments(
        capability_name=Capability.TASKS_CREATE.value,
        arguments={
            "payload": {
                "title": "Follow up with the architect",
                "origin_evidence_ref": "cap_origin0001origin0001",
            }
        },
        principal=PRINCIPAL,
        grants=frozenset({(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING)}),
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert replay["payload"]["idempotency_key"] == key
