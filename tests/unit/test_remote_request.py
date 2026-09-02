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
from my_pa.application.commands import Command, StartGsqsB0
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


def test_gsqs_start_is_server_stamped_on_the_remote_read_profile() -> None:
    """ChatLLM cannot send `idempotency_key` and cannot omit it either.

    `gsqs.start` is a domain write whose purpose is not in `_WRITE_PURPOSES`, so
    the read-only remote profile publishes it. Without a server stamp the
    command cannot be constructed. Identical payloads must replay.
    """
    assert Capability.GSQS_START in _IDEMPOTENT_REMOTE_CAPABILITIES
    arguments = {
        "payload": {
            "authorization_id": "synthetic-b0-commissioning",
            "campaign_class": "SYNTHETIC",
            "repetition": 1,
        }
    }
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=Capability.GSQS_START.value,
            arguments={"payload": {**arguments["payload"], "idempotency_key": "caller-key"}},
            principal=PRINCIPAL,
            grants=None,
            clock=lambda: FROZEN,
            issue_id=_issue,
        )
    composed = compose_remote_arguments(
        capability_name=Capability.GSQS_START.value,
        arguments=arguments,
        principal=PRINCIPAL,
        grants=None,
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    key = composed["payload"]["idempotency_key"]
    assert isinstance(key, str) and key.startswith("idk_")
    command = StartGsqsB0(**composed["payload"])
    assert command.idempotency_key == key
    replay = compose_remote_arguments(
        capability_name=Capability.GSQS_START.value,
        arguments=arguments,
        principal=PRINCIPAL,
        grants=None,
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert replay["payload"]["idempotency_key"] == key


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


# ---- the entity plane's replay-safe writes ---------------------------------


#: The `entities.` writes whose replay identity is **not** a caller-shaped key,
#: and so are deliberately outside the sweep below.
#:
#: Every one of the thirty keyed writes -- Phase A's eighteen plus
#: `RI-ENT-WP-11`'s record-family writes -- carries an `idempotency_key` field on
#: its command, which is what makes membership of
#: `_IDEMPOTENT_REMOTE_CAPABILITIES` meaningful for it: the set's mechanism is
#: *inserting a derived key into the payload*, so a capability in it must have a
#: field to insert one into. The governed producer/correction commands carry none, and
#: that absence is their contract rather than an omission:
#:
#: * `entities.proposals.create` is arbitrated by the server-derived
#:   `dedupe_sha256` under `UNIQUE (principal_id, dedupe_sha256)` on the open
#:   states, so a repeat is answered by the proposal that is already open and
#:   writes nothing -- a stronger guarantee than a key, and one that holds on
#:   every transport rather than only the remote one;
#: * `entities.merge` is arbitrated by `UNIQUE (principal_id, idempotency_key)`
#:   on `entity_identity_operations`, with the key derived by the handler from
#:   the preview it consumes -- so an identical retry replays and a materially
#:   different request against the same preview conflicts, on all three
#:   transports;
#: * `entities.merge.preview` mints a fresh preview on every call and has no
#:   replay identity to key on at all.
#: * split preview follows that same contract, while split apply is
#:   replay-arbitrated by its consumed preview and persisted operation receipt.
#:
#: Named here rather than derived, so admitting another write to this
#: exception is a decision made in this file and argued for.
KEYLESS_ENTITY_WRITES: frozenset[Capability] = frozenset(
    {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
)


def _entity_writes() -> frozenset[Capability]:
    """The population, read off the purpose map rather than listed here.

    A further entity write mapped to a write purpose joins this sweep on arrival,
    which is the failure mode the two tests below exist for: a remote write that
    never joined `_IDEMPOTENT_REMOTE_CAPABILITIES` accepts no key from the caller
    and is stamped with none by the server, so a lost response and a retry write a
    second row. `KEYLESS_ENTITY_WRITES` is subtracted, and every member of it has
    a stated replay identity of its own.
    """
    return (
        frozenset(
            capability
            for capability in Capability
            if capability.value.startswith("entities.")
            and permitted_purposes(capability) & _WRITE_PURPOSES
        )
        - KEYLESS_ENTITY_WRITES
    )


def test_every_entity_write_is_a_server_stamped_idempotent_remote_capability() -> None:
    """The whole write half, derived and compared rather than enumerated twice."""
    writes = _entity_writes()
    # Thirty after `RI-ENT-WP-11`'s first four record families: Phase A's
    # eighteen plus three verbs per family, each carrying its own key.
    assert len(writes) == 30
    assert writes <= _IDEMPOTENT_REMOTE_CAPABILITIES
    # And the exception is not the rule: every keyless write really does carry a
    # write purpose, so subtracting them narrowed the sweep rather than being a
    # no-op somebody could delete without noticing.
    for capability in KEYLESS_ENTITY_WRITES:
        assert permitted_purposes(capability) & _WRITE_PURPOSES
        assert capability not in _IDEMPOTENT_REMOTE_CAPABILITIES


def test_no_entity_read_is_stamped_with_an_idempotency_key() -> None:
    """The control: stamping a read would put a key on a command with no field for one."""
    reads = {
        capability
        for capability in Capability
        if capability.value.startswith("entities.")
        and not permitted_purposes(capability) & _WRITE_PURPOSES
    }
    # Sixteen after `RI-ENT-WP-10`: the eleven earlier reads plus its five
    # record-family reads, none of which carries an `idempotency_key` field
    # because none of them writes.
    assert len(reads) == 16
    assert not reads & _IDEMPOTENT_REMOTE_CAPABILITIES


def test_compose_stamps_a_content_addressed_key_for_an_entity_write() -> None:
    """Derived server-side from capability, Principal and canonical payload.

    Asserted as a *replay* rather than as a shape: what makes the key useful is
    that the same request from the same Principal produces the same key, and
    that a different payload does not.
    """
    grants = frozenset({(Capability.ENTITIES_CREATE, Purpose.ENTITY_AUTHORING)})
    payload = {"entity_type": "person", "display_name": "Remote Newcomer"}
    composed = compose_remote_arguments(
        capability_name=Capability.ENTITIES_CREATE.value,
        arguments={"payload": dict(payload)},
        principal=PRINCIPAL,
        grants=grants,
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    key = composed["payload"]["idempotency_key"]
    assert key.startswith("idk_")
    assert composed["purpose"] == Purpose.ENTITY_AUTHORING.value
    replay = compose_remote_arguments(
        capability_name=Capability.ENTITIES_CREATE.value,
        arguments={"payload": dict(payload)},
        principal=PRINCIPAL,
        grants=grants,
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert replay["payload"]["idempotency_key"] == key
    different = compose_remote_arguments(
        capability_name=Capability.ENTITIES_CREATE.value,
        arguments={"payload": {**payload, "display_name": "Someone Else"}},
        principal=PRINCIPAL,
        grants=grants,
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert different["payload"]["idempotency_key"] != key


def test_compose_stamps_a_key_for_an_observation_ingest_write() -> None:
    """`entities.observe` too, and it carries the plane's other write purpose.

    Separated from the test above because the purpose is the thing most likely
    to be got wrong here: `entity_observation_ingest` maps to exactly one
    capability, so a classification that missed it would leave the one caller
    most likely to retry -- an ingest path -- writing a second observation for
    every lost response.
    """
    grants = frozenset({(Capability.ENTITIES_OBSERVE, Purpose.ENTITY_OBSERVATION_INGEST)})
    composed = compose_remote_arguments(
        capability_name=Capability.ENTITIES_OBSERVE.value,
        arguments={
            "payload": {
                "kind": "user_statement",
                "authority": "user_authored_statement",
                "observed_value": "Remote Person",
            }
        },
        principal=PRINCIPAL,
        grants=grants,
        clock=lambda: FROZEN,
        issue_id=_issue,
    )
    assert composed["payload"]["idempotency_key"].startswith("idk_")
    assert composed["purpose"] == Purpose.ENTITY_OBSERVATION_INGEST.value


@pytest.mark.parametrize(
    "capability",
    sorted(_entity_writes(), key=lambda item: item.value),
    ids=lambda item: item.value,
)
def test_no_entity_write_accepts_a_caller_supplied_key(capability: Capability) -> None:
    """Refused before a Purpose is resolved, on every one of them.

    Parametrised deliberately: `REMOTE_OWNED_PAYLOAD_FIELDS` is checked once in
    `compose_remote_arguments` for every capability, so a per-capability sweep
    is what proves the check is not reached through a branch one of them skips.
    """
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=capability.value,
            arguments={"payload": {"idempotency_key": "forged"}},
            principal=PRINCIPAL,
            grants=None,
            clock=lambda: FROZEN,
            issue_id=_issue,
        )


@pytest.mark.parametrize("field", sorted(SERVER_OWNED_REMOTE_FIELDS))
def test_no_entity_write_accepts_a_caller_supplied_envelope_field(field: str) -> None:
    """The other injection surface, on a capability that decides who a person is."""
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE.value,
            arguments={field: "forged", "payload": {}},
            principal=PRINCIPAL,
            grants=None,
            clock=lambda: FROZEN,
            issue_id=_issue,
        )


def test_no_entity_write_publishes_a_field_the_server_owns() -> None:
    """A published schema that named one would be inviting a refusal."""
    for capability in sorted(_entity_writes(), key=lambda item: item.value):
        command = next(
            member for member in get_args(Command.__value__) if member.capability is capability
        )
        schema = remote_tool_schema(input_schema_for(command))
        assert not SERVER_OWNED_REMOTE_FIELDS & set(schema["properties"])
        payload = schema["properties"]["payload"]
        assert not REMOTE_OWNED_PAYLOAD_FIELDS & set(payload.get("properties", {}))
        assert "idempotency_key" not in payload.get("required", [])
