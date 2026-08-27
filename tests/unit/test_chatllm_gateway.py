"""Compact façade catalog, wrapper, and kind-guard behaviour."""

from __future__ import annotations

import json

import pytest

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    PROFILE_VERSION,
    READ_TOOL,
    WRITE_TOOL,
    facade_kind,
    facade_tool_names,
    prepare_compact_call,
    render_describe,
)
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    REMOTE_OWNED_PAYLOAD_FIELDS,
    SERVER_OWNED_REMOTE_FIELDS,
    remote_tool_schema,
)
from my_pa.application.errors import InvalidRequestError, UnsupportedError
from my_pa.domain.identity.operation import Capability


def test_facade_names_follow_eligible_kinds() -> None:
    reads = frozenset({Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value})
    assert facade_tool_names(reads) == frozenset({DESCRIBE_TOOL, READ_TOOL})
    writes = frozenset({Capability.TASKS_CREATE.value})
    assert WRITE_TOOL in facade_tool_names(writes)
    assert READ_TOOL not in facade_tool_names(writes)
    assert facade_tool_names(frozenset()) == frozenset()


def test_empty_eligible_set_publishes_no_facade() -> None:
    assert facade_tool_names(frozenset()) == frozenset()


def test_gsqs_start_is_read_kind_on_the_remote_classifier() -> None:
    assert facade_kind(Capability.GSQS_START) == "read"


def test_merge_is_operator_kind() -> None:
    assert facade_kind(Capability.ENTITIES_MERGE) == "operator"


def test_prepare_rejects_principal_and_wrong_kind() -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.TASKS_CREATE.value})
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(
            READ_TOOL,
            {
                "capability": Capability.TASKS_SEARCH.value,
                "arguments": {},
                "principal_id": "prn_forged",
            },
            allowed_canonical=allowed,
        )
    with pytest.raises(InvalidRequestError):
        prepare_compact_call(
            READ_TOOL,
            {"capability": Capability.TASKS_CREATE.value, "arguments": {}},
            allowed_canonical=allowed,
        )


def test_prepare_hides_ungranted_targets() -> None:
    with pytest.raises(UnsupportedError):
        prepare_compact_call(
            READ_TOOL,
            {"capability": Capability.TASKS_SEARCH.value, "arguments": {}},
            allowed_canonical=frozenset({Capability.CAPABILITIES_GET.value}),
        )


def test_describe_does_not_disclose_hidden_schema() -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})
    with pytest.raises(UnsupportedError):
        render_describe(
            {"capability": Capability.TASKS_SEARCH.value},
            allowed_canonical=allowed,
        )
    listed = json.loads(render_describe({}, allowed_canonical=allowed))
    assert listed["profile"] == PROFILE_VERSION
    assert [item["capability"] for item in listed["items"]] == [Capability.CAPABILITIES_GET.value]


def test_describe_paginates_deterministically() -> None:
    allowed = frozenset(
        {
            Capability.CAPABILITIES_GET.value,
            Capability.TASKS_SEARCH.value,
            Capability.TASKS_LIST.value,
        }
    )
    first = json.loads(render_describe({"limit": 1}, allowed_canonical=allowed))
    assert len(first["items"]) == 1
    assert first["next_cursor"] == first["items"][0]["capability"]
    second = json.loads(
        render_describe(
            {"limit": 10, "cursor": first["next_cursor"]},
            allowed_canonical=allowed,
        )
    )
    assert first["items"][0]["capability"] not in {item["capability"] for item in second["items"]}


def test_exact_describe_uses_remote_tool_schema() -> None:
    tools = {tool.name: tool for tool in TOOLS}
    read_name = Capability.CAPABILITIES_GET.value
    write_name = Capability.TASKS_CREATE.value
    read_described = json.loads(
        render_describe({"capability": read_name}, allowed_canonical=frozenset({read_name}))
    )
    write_described = json.loads(
        render_describe({"capability": write_name}, allowed_canonical=frozenset({write_name}))
    )
    assert read_described["input_schema"] == remote_tool_schema(tools[read_name].input_schema)
    assert write_described["input_schema"] == remote_tool_schema(tools[write_name].input_schema)
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(read_described["input_schema"]["properties"])
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(write_described["input_schema"]["properties"])
    payload = write_described["input_schema"]["properties"]["payload"]
    assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(payload["properties"])
    canonical_payload = tools[write_name].input_schema["properties"]["payload"]["properties"]
    assert "idempotency_key" in canonical_payload


def test_taxonomy_is_not_a_grant() -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})
    listed = json.loads(render_describe({"feature": "work"}, allowed_canonical=allowed))
    assert listed["items"] == []
    with pytest.raises(UnsupportedError):
        prepare_compact_call(
            READ_TOOL,
            {"capability": Capability.TASKS_SEARCH.value, "arguments": {}},
            allowed_canonical=allowed,
        )
