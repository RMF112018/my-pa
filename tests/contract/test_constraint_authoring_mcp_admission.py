"""The generated MCP surface for Constraint authoring (PC-CM-IMP-WP07).

`T07-05` and `T07-06`, over the MCP transport rather than in the abstract.

**No parallel transport was built.** The twelve tools exist because twelve
commands joined the `Command` union: `adapters.mcp.tools` derives `_COMMANDS`
from `get_args(Command.__value__)` and every schema from the command's own
fields. What is asserted here is what that derivation produced.

**W4-F01, stated exactly.** The published envelope *does* carry `principal_id`
on every tool, this build's twelve included. It is a required field of the v1
request envelope on every transport, it is correlation input, and it confers no
authority. What no generated command payload accepts is a caller-supplied
principal identifier — and that is the claim, made here on the transport rather
than restated as prose. The equivalent existing test is CLI-scoped
(`tests/contract/test_cli_transport.py::test_a_supplied_principal_id_does_not_become_authority`);
this closes the MCP half for a mutation.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any, Final

import pytest
from tests.conftest import Scene, build_service, staged_record
from tests.contract.test_transport_parity import document, payloads_for
from tests.transports import McpTransport, mcp_transport

from my_pa.adapters.mcp import TOOLS
from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.source.registry import issue_identifier

type Served = AbstractContextManager[McpTransport]

AUTHORING: Final[tuple[Capability, ...]] = (
    Capability.CONSTRAINTS_CREATE,
    Capability.CONSTRAINTS_PUBLISH,
    Capability.CONSTRAINTS_UPDATE,
    Capability.CONSTRAINTS_TRANSITION,
    Capability.CONSTRAINTS_CLOSE,
    Capability.CONSTRAINTS_CLOSE_FOLLOW_UP,
    Capability.CONSTRAINTS_VOID,
    Capability.CONSTRAINTS_REOPEN,
    Capability.CONSTRAINT_CATEGORIES_CREATE,
    Capability.CONSTRAINT_CATEGORIES_UPDATE,
    Capability.CONSTRAINT_CATEGORIES_DEACTIVATE,
    Capability.CONSTRAINT_CATEGORIES_REORDER,
)

CREATIONS: Final[frozenset[Capability]] = frozenset(
    {Capability.CONSTRAINTS_CREATE, Capability.CONSTRAINT_CATEGORIES_CREATE}
)

TOOLS_BY_NAME: Final[dict[str, Any]] = {tool.name: tool for tool in TOOLS}


@pytest.fixture
def served(scene: Scene) -> Served[McpTransport]:
    staged_record(scene, text="a synthetic record")
    return mcp_transport(build_service(scene.world, scene.providers), scene.principal)


def _payload_schema(capability: Capability) -> dict[str, Any]:
    schema: dict[str, Any] = TOOLS_BY_NAME[capability.value].input_schema
    payload: dict[str, Any] = schema["properties"][PAYLOAD_KEY]
    return payload


def _property_names(schema: object) -> list[str]:
    found: list[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "properties" and isinstance(value, dict):
                for name, nested in value.items():
                    found.append(name)
                    found.extend(_property_names(nested))
            elif isinstance(value, dict | list):
                found.extend(_property_names(value))
    elif isinstance(schema, list):
        for item in schema:
            found.extend(_property_names(item))
    return found


#: An authenticated Principal identifier that is not the one the transport was
#: given. Spelled rather than minted, so the spoof is legible in the assertions.
ANOTHER_PRINCIPAL: Final = "prn_ffff0001ffff0001ffff0001"


# ---- T07-05: the twelve tools and their schemas ------------------------------


def test_twelve_authoring_tools_are_published() -> None:
    for capability in AUTHORING:
        assert capability.value in TOOLS_BY_NAME, f"{capability.value} publishes no tool"
    assert len(TOOLS) == len(Capability)


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_no_authoring_payload_accepts_a_caller_supplied_principal(
    capability: Capability,
) -> None:
    """`CM-BE-AC-083`, stated about the payload and not about the envelope.

    The envelope's `principal_id` is a required v1 contract field and is
    published on all one hundred and fifty-four tools; it is correlation input.
    What must not exist is a *command* field a caller could set.
    """
    payload = _payload_schema(capability)
    named = [name for name in _property_names(payload) if "principal" in name.lower()]
    assert named == []


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_every_authoring_payload_is_closed(capability: Capability) -> None:
    payload = _payload_schema(capability)
    assert payload["additionalProperties"] is False
    assert payload["type"] == "object"


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_no_authoring_payload_publishes_an_undescribed_field(capability: Capability) -> None:
    """An empty schema is a field documented as accepting anything."""
    undescribed = sorted(
        name for name, value in _payload_schema(capability)["properties"].items() if not value
    )
    assert undescribed == []


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_expected_version_is_required_on_the_ten_and_absent_from_the_two(
    capability: Capability,
) -> None:
    payload = _payload_schema(capability)
    if capability in CREATIONS:
        assert "expected_version" not in payload["properties"]
        return
    if capability is Capability.CONSTRAINT_CATEGORIES_REORDER:
        assert "expected_versions" in payload["required"]
        return
    assert "expected_version" in payload["required"]


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_no_authoring_payload_publishes_a_server_issued_code(capability: Capability) -> None:
    named = [name for name in _property_names(_payload_schema(capability)) if "code" in name]
    # `code_segment` is a Category's own caller-chosen stem, not a Constraint's
    # allocated public code. The allocated one has no field anywhere.
    assert "constraint_code" not in named
    assert set(named) <= {"code_segment"}


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_no_authoring_payload_publishes_a_workbook_or_sync_field(
    capability: Capability,
) -> None:
    """`CM-BE-AC-086`. No workbook manipulation reaches this surface."""
    forbidden = ("workbook", "sharepoint", "sync", "excel", "worksheet")
    named = [
        name
        for name in _property_names(_payload_schema(capability))
        if any(word in name.lower() for word in forbidden)
    ]
    assert named == []


@pytest.mark.parametrize("capability", AUTHORING, ids=lambda c: c.value)
def test_every_authoring_tool_is_annotated_as_a_write(capability: Capability) -> None:
    annotations = TOOLS_BY_NAME[capability.value].annotations
    assert annotations is not None
    assert annotations.read_only_hint is False
    assert annotations.destructive_hint is (capability not in CREATIONS)
    assert annotations.open_world_hint is False


def test_exactly_ten_authoring_tools_are_annotated_destructive() -> None:
    destructive = [
        capability
        for capability in AUTHORING
        if TOOLS_BY_NAME[capability.value].annotations.destructive_hint
    ]
    assert len(destructive) == 10


def test_the_lifecycle_states_a_tool_admits_are_a_closed_enum() -> None:
    payload = _payload_schema(Capability.CONSTRAINTS_TRANSITION)
    admitted = payload["properties"]["to_state"]["enum"]
    assert admitted == [
        "draft",
        "identified",
        "pending",
        "in_progress",
        "on_hold",
        "closed",
        "void",
    ]


def test_close_with_follow_up_is_one_tool() -> None:
    """Never two mutations: one name, and the successor's fields are on it."""
    payload = _payload_schema(Capability.CONSTRAINTS_CLOSE_FOLLOW_UP)
    assert "successor_description" in payload["required"]
    assert "successor_due_date" in payload["properties"]


def test_a_reorder_is_one_tool_taking_the_whole_ordering() -> None:
    payload = _payload_schema(Capability.CONSTRAINT_CATEGORIES_REORDER)
    assert payload["properties"]["ordered_category_ids"]["type"] == "array"
    assert payload["properties"]["expected_versions"]["type"] == "array"


# ---- T07-06: W4-F01, on the MCP transport -----------------------------------


def test_the_envelope_still_publishes_principal_id_on_an_authoring_tool() -> None:
    """Stated rather than implied, because the wording matters.

    The disposition is RETAIN_AND_PROVE_NON_AUTHORITATIVE. This asserts the
    field *is* published, so no reader of this file can come away believing the
    published schema hides one.
    """
    schema = TOOLS_BY_NAME[Capability.CONSTRAINTS_CLOSE.value].input_schema
    assert "principal_id" in schema["properties"]
    assert "principal_id" in schema["required"]


def test_a_spoofed_envelope_principal_changes_nothing_about_a_mutation(
    served: Served[McpTransport], scene: Scene
) -> None:
    """One close, over a real MCP exchange, whose envelope names another Principal.

    The honest document is built only to derive the spoofed one from it, so the
    two differ in exactly the envelope field and nothing else; a single exchange
    is then sent. The answer must be the one the transport-fixed Principal is
    owed in every part a caller could try to influence: the outcome, the record
    reached, the receipt's owner, and the response's partitioning, with the
    spoofed identifier appearing nowhere in the result.

    The audit row is not asserted here. `_run` records it from the authenticated
    `principal`, never from `metadata`, and the persistence-tier sibling
    `test_the_acting_principal_and_not_the_envelope_owns_every_receipt` checks
    the history rows directly under the same spoof.
    """
    record = staged_record(scene, text="a synthetic record")
    payload = payloads_for(scene, record)[Capability.CONSTRAINTS_CLOSE]
    honest = document(Capability.CONSTRAINTS_CLOSE, scene.principal.principal_id, payload)
    spoofed = {**honest, "principal_id": ANOTHER_PRINCIPAL}
    assert spoofed["principal_id"] != scene.principal.principal_id

    with served as transport:
        answer = transport.send(Capability.CONSTRAINTS_CLOSE.value, spoofed)

    assert answer.failed is False, answer.document
    assert answer.document["error"] is None
    result = answer.document["result"]
    receipt = result["receipt"]
    # Ownership follows the transport-resolved Principal, not the envelope.
    assert receipt["principal_id"] == scene.principal.principal_id
    assert receipt["principal_id"] != spoofed["principal_id"]
    assert result["constraint"]["principal_id"] == scene.principal.principal_id
    # And the record reached is the acting Principal's own.
    assert result["constraint"]["constraint_id"] == scene.constraint_close_id
    assert json.dumps(result).count(spoofed["principal_id"]) == 0


def test_a_principal_id_inside_the_payload_is_rejected_as_an_unknown_field(
    served: Served[McpTransport], scene: Scene
) -> None:
    """The payload is closed, so this is `invalid_request` and never a silent drop."""
    record = staged_record(scene, text="a synthetic record")
    payload = {
        **payloads_for(scene, record)[Capability.CONSTRAINTS_CLOSE],
        "principal_id": scene.principal.principal_id,
    }
    request = document(Capability.CONSTRAINTS_CLOSE, scene.principal.principal_id, payload)
    with served as transport:
        answer = transport.send(Capability.CONSTRAINTS_CLOSE.value, request)
    assert answer.failed is True
    # A refusal before the envelope exists is the problem document itself rather
    # than an envelope carrying one: `normalize` refused, so there is no request
    # to answer. The code is the same either way.
    assert answer.document["code"] == ErrorCode.INVALID_REQUEST.value


def test_a_foreign_constraint_identifier_is_indistinguishable_from_an_absent_one(
    served: Served[McpTransport], scene: Scene
) -> None:
    """`CM-BE-AC-078` on the mutation surface, over the transport.

    A Constraint identifier that exists in another Principal's partition and one
    that exists nowhere must produce the same refusal, byte for byte apart from
    correlation.
    """
    foreign_id = _another_constraint_id()
    scene.world.project_constraints[(ANOTHER_PRINCIPAL, foreign_id)] = (
        scene.world.project_constraints[(scene.principal.principal_id, scene.constraint_id)]
    )
    unknown_id = _another_constraint_id()

    with served as transport:
        foreign_answer = transport.send(
            Capability.CONSTRAINTS_CLOSE.value,
            document(
                Capability.CONSTRAINTS_CLOSE,
                scene.principal.principal_id,
                {"constraint_id": foreign_id, "expected_version": 1},
            ),
        )
        unknown_answer = transport.send(
            Capability.CONSTRAINTS_CLOSE.value,
            document(
                Capability.CONSTRAINTS_CLOSE,
                scene.principal.principal_id,
                {"constraint_id": unknown_id, "expected_version": 1},
            ),
        )

    assert foreign_answer.failed is True
    assert unknown_answer.failed is True
    assert (
        foreign_answer.document["error"]["code"]
        == unknown_answer.document["error"]["code"]
        == ErrorCode.NOT_FOUND.value
    )
    assert (
        foreign_answer.document["error"]["message"] == unknown_answer.document["error"]["message"]
    )
    assert (
        foreign_answer.document["error"]["safe_details"]
        == unknown_answer.document["error"]["safe_details"]
    )


def _another_constraint_id() -> str:
    return issue_identifier(IdKind.PROJECT_CONSTRAINT)
