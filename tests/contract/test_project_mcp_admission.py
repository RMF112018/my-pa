"""GAP-007: generated MCP descriptions and schemas for Continuity Project.

The five Project tools exist because five commands joined the `Command` union.
`adapters.mcp.tools` derives `_COMMANDS` from that union and every schema from
the command's own fields. Compact `my_pa.describe` inherits
`payload_schema_for` through `remote_tool_schema`; there is no Project façade
branch.
"""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from typing import Any, Final

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.conftest import Scene, build_service
from tests.contract.test_transport_parity import document
from tests.transports import McpTransport, mcp_transport

from my_pa.adapters.mcp.chatllm_gateway import DESCRIBE_TOOL, WRITE_TOOL, render_describe
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.server import _answer
from my_pa.adapters.mcp.tools import TOOLS, payload_schema_for
from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.adapters.remote_request import SERVER_OWNED_REMOTE_FIELDS, remote_tool_schema
from my_pa.application.commands import (
    CloseProject,
    CreateEntityParticipation,
    CreateProject,
    ListEntityParticipations,
    ListProjects,
    ListTasks,
    ReadProject,
    UpdateProject,
    UpdateTask,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier

type Served = AbstractContextManager[McpTransport]

TOOLS_BY_NAME: Final[dict[str, Any]] = {tool.name: tool for tool in TOOLS}

PROJECT: Final[tuple[Capability, ...]] = (
    Capability.CONTINUITY_PROJECTS,
    Capability.CONTINUITY_PROJECTS_READ,
    Capability.CONTINUITY_PROJECTS_CREATE,
    Capability.CONTINUITY_PROJECTS_UPDATE,
    Capability.CONTINUITY_PROJECTS_CLOSE,
)

VENDOR_MARKERS: Final[tuple[str, ...]] = (
    "chatllm",
    "mossaic",
    "moss-aic",
    "hbintel",
    "hedrick",
)

SYSTEM_OWNED_PAYLOAD_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "principal_id",
        "version",
        "opened_at",
        "closed_at",
        "created_at",
        "updated_at",
        "participants",
        "canonical_participations",
    }
)


class _UncalledService:
    def invoke(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("malformed MCP input must not reach the application")


def _payload_schema(capability: Capability) -> dict[str, Any]:
    schema: dict[str, Any] = TOOLS_BY_NAME[capability.value].input_schema
    payload: dict[str, Any] = schema["properties"][PAYLOAD_KEY]
    return payload


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def served(scene: Scene) -> Served:
    return mcp_transport(build_service(scene.world, scene.providers), scene.principal)


def test_tools_list_exposes_the_five_project_capabilities() -> None:
    names = {tool.name for tool in TOOLS}
    published = {capability.value for capability in PROJECT}
    assert published <= names
    assert published == {
        "continuity.projects",
        "continuity.projects.read",
        "continuity.projects.create",
        "continuity.projects.update",
        "continuity.projects.close",
    }


def test_tools_list_over_the_protocol_names_the_five_project_capabilities(
    served: Served,
) -> None:
    with served as session:
        listed = {tool.name for tool in session.list_tools().tools}
    assert {capability.value for capability in PROJECT} <= listed


def test_no_vendor_specific_project_tool_name_is_published() -> None:
    for tool in TOOLS:
        lowered = tool.name.lower()
        if "project" not in lowered and not lowered.startswith("continuity.projects"):
            continue
        for marker in VENDOR_MARKERS:
            assert marker not in lowered, f"{tool.name} carries vendor marker {marker}"
        assert tool.name in {capability.value for capability in Capability}


@pytest.mark.parametrize("capability", PROJECT, ids=lambda c: c.value)
def test_every_project_payload_is_nested_and_closed(capability: Capability) -> None:
    schema = TOOLS_BY_NAME[capability.value].input_schema
    assert schema["additionalProperties"] is False
    assert PAYLOAD_KEY in schema["properties"]
    payload = schema["properties"][PAYLOAD_KEY]
    assert payload["type"] == "object"
    assert payload["additionalProperties"] is False
    assert SYSTEM_OWNED_PAYLOAD_FIELDS.isdisjoint(payload["properties"])
    assert "principal_id" not in payload["properties"]


@pytest.mark.parametrize(
    "capability",
    (Capability.CONTINUITY_PROJECTS_UPDATE, Capability.CONTINUITY_PROJECTS_CLOSE),
    ids=lambda c: c.value,
)
def test_expected_version_is_required_on_update_and_close(capability: Capability) -> None:
    payload = _payload_schema(capability)
    assert "expected_version" in payload["required"]
    assert payload["properties"]["expected_version"]["type"] == "integer"


def test_expected_version_is_absent_from_list_read_and_create() -> None:
    for capability in (
        Capability.CONTINUITY_PROJECTS,
        Capability.CONTINUITY_PROJECTS_READ,
        Capability.CONTINUITY_PROJECTS_CREATE,
    ):
        assert "expected_version" not in _payload_schema(capability)["properties"]


def test_update_state_enum_omits_closed() -> None:
    state = _payload_schema(Capability.CONTINUITY_PROJECTS_UPDATE)["properties"]["state"]
    assert state["enum"] == ["active", "on_hold"]
    assert "closed" not in state["enum"]


def test_list_state_enum_includes_closed() -> None:
    state = _payload_schema(Capability.CONTINUITY_PROJECTS)["properties"]["state"]
    assert state["enum"] == ["active", "on_hold", "closed"]


def test_generated_descriptions_teach_payload_and_lifecycle() -> None:
    listed = {tool.name: tool.description or "" for tool in TOOLS}
    assert "payload" in listed[Capability.CONTINUITY_PROJECTS.value]
    assert "payload" in listed[Capability.CONTINUITY_PROJECTS_READ.value]
    assert "payload" in listed[Capability.CONTINUITY_PROJECTS_CREATE.value]
    update = listed[Capability.CONTINUITY_PROJECTS_UPDATE.value]
    close = listed[Capability.CONTINUITY_PROJECTS_CLOSE.value]
    assert "expected_version" in update
    assert "expected_version" in close
    assert "reopen" in update or "delete" in update
    assert "reopen" in close or "delete" in close


def test_participation_and_task_schemas_name_project_id() -> None:
    create = payload_schema_for(CreateEntityParticipation)
    listed = payload_schema_for(ListEntityParticipations)
    tasks = payload_schema_for(ListTasks)
    update_task = payload_schema_for(UpdateTask)
    assert "project_id" in create["properties"]
    create_summary = (
        TOOLS_BY_NAME[Capability.ENTITIES_PARTICIPATIONS_CREATE.value].description or ""
    )
    list_summary = TOOLS_BY_NAME[Capability.ENTITIES_PARTICIPATIONS_LIST.value].description or ""
    assert "XOR" in create_summary
    assert "XOR" in list_summary
    assert "exactly one" in create["properties"]["project_id"]["description"].lower()
    assert "exactly one" in listed["properties"]["project_id"]["description"].lower()
    assert "project_id" in tasks["properties"]
    assert "clear_project" in update_task["properties"]
    assert "detach" in update_task["properties"]["clear_project"]["description"]


def test_describe_inherits_canonical_nested_payload_schema() -> None:
    allowed = frozenset(capability.value for capability in PROJECT)
    for capability in (
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Capability.CONTINUITY_PROJECTS_CLOSE,
    ):
        body = json.loads(
            render_describe({"capability": capability.value}, allowed_canonical=allowed)
        )
        canonical = remote_tool_schema(TOOLS_BY_NAME[capability.value].input_schema)
        assert body["input_schema"] == canonical
        payload = body["input_schema"]["properties"][PAYLOAD_KEY]
        assert "expected_version" in payload["required"]
        assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(body["input_schema"]["properties"])


def test_a_command_field_at_the_top_level_is_invalid_request() -> None:
    project_id = issue_identifier(IdKind.PROJECT)
    rendered, failed, _image = _answer(
        _UncalledService(),  # type: ignore[arg-type]
        Principal("prn_12345678", PrincipalKind.OPERATOR, authenticated=True),
        Capability.CONTINUITY_PROJECTS_UPDATE.value,
        {
            "request_id": "req-top-level-project-id",
            "purpose": Purpose.CONTINUITY_AUTHORING.value,
            "principal_id": "prn_12345678",
            "requested_at": "2026-09-13T12:00:00Z",
            "project_id": project_id,
            PAYLOAD_KEY: {
                "project_id": project_id,
                "expected_version": 1,
                "idempotency_key": "idk_top_level_0000000000000001",
                "name": "Should not land",
            },
        },
    )
    assert failed is True
    assert json.loads(rendered)["code"] == ErrorCode.INVALID_REQUEST.value


def test_expected_version_at_the_top_level_is_invalid_request() -> None:
    project_id = issue_identifier(IdKind.PROJECT)
    rendered, failed, _image = _answer(
        _UncalledService(),  # type: ignore[arg-type]
        Principal("prn_12345678", PrincipalKind.OPERATOR, authenticated=True),
        Capability.CONTINUITY_PROJECTS_CLOSE.value,
        {
            "request_id": "req-top-level-expected-version",
            "purpose": Purpose.CONTINUITY_AUTHORING.value,
            "principal_id": "prn_12345678",
            "requested_at": "2026-09-13T12:00:00Z",
            "expected_version": 1,
            PAYLOAD_KEY: {
                "project_id": project_id,
                "expected_version": 1,
                "idempotency_key": "idk_top_level_0000000000000002",
            },
        },
    )
    assert failed is True
    assert json.loads(rendered)["code"] == ErrorCode.INVALID_REQUEST.value


@pytest.mark.parametrize("field", sorted(SYSTEM_OWNED_PAYLOAD_FIELDS))
def test_a_server_owned_payload_field_is_invalid_request(field: str) -> None:
    project_id = issue_identifier(IdKind.PROJECT)
    payload: dict[str, object] = {
        "project_id": project_id,
        "expected_version": 1,
        "idempotency_key": "idk_system_owned_00000000000001",
        "name": "Should not land",
        field: 1 if field == "version" else "prn_12345678" if field == "principal_id" else [],
    }
    if field in {"opened_at", "closed_at", "created_at", "updated_at"}:
        payload[field] = "2026-09-13T12:00:00Z"
    rendered, failed, _image = _answer(
        _UncalledService(),  # type: ignore[arg-type]
        Principal("prn_12345678", PrincipalKind.OPERATOR, authenticated=True),
        Capability.CONTINUITY_PROJECTS_UPDATE.value,
        document(
            Capability.CONTINUITY_PROJECTS_UPDATE,
            "prn_12345678",
            payload,
        ),
    )
    assert failed is True
    assert json.loads(rendered)["code"] == ErrorCode.INVALID_REQUEST.value


def test_schema_builder_matches_the_five_command_types() -> None:
    assert payload_schema_for(ListProjects) == _payload_schema(Capability.CONTINUITY_PROJECTS)
    assert payload_schema_for(ReadProject) == _payload_schema(Capability.CONTINUITY_PROJECTS_READ)
    assert payload_schema_for(CreateProject) == _payload_schema(
        Capability.CONTINUITY_PROJECTS_CREATE
    )
    assert payload_schema_for(UpdateProject) == _payload_schema(
        Capability.CONTINUITY_PROJECTS_UPDATE
    )
    assert payload_schema_for(CloseProject) == _payload_schema(Capability.CONTINUITY_PROJECTS_CLOSE)


@pytest.mark.anyio
async def test_remote_describe_shows_nested_payload_and_expected_version(scene: Scene) -> None:
    update = Capability.CONTINUITY_PROJECTS_UPDATE.value
    close = Capability.CONTINUITY_PROJECTS_CLOSE.value
    allowed = frozenset({update, close})
    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            scene.principal,
            allowed_capabilities=allowed,
            capability_purposes=frozenset(
                {
                    (Capability.CONTINUITY_PROJECTS_UPDATE, Purpose.CONTINUITY_AUTHORING),
                    (Capability.CONTINUITY_PROJECTS_CLOSE, Purpose.CONTINUITY_AUTHORING),
                }
            ),
            compact_publication=True,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        names = {tool.name for tool in (await session.list_tools()).tools}
        described_update = await session.call_tool(DESCRIBE_TOOL, {"capability": update})
        described_close = await session.call_tool(DESCRIBE_TOOL, {"capability": close})
        forged = await session.call_tool(
            WRITE_TOOL,
            {
                "capability": update,
                "arguments": {
                    "purpose": "not-a-purpose",
                    "payload": {
                        "project_id": issue_identifier(IdKind.PROJECT),
                        "expected_version": 1,
                        "name": "Should not land",
                    },
                },
            },
        )
    assert names == {DESCRIBE_TOOL, WRITE_TOOL}
    assert update not in names
    for described, capability in (
        (described_update, Capability.CONTINUITY_PROJECTS_UPDATE),
        (described_close, Capability.CONTINUITY_PROJECTS_CLOSE),
    ):
        body = json.loads(described.content[0].text)
        schema = body["input_schema"]
        assert schema == remote_tool_schema(TOOLS_BY_NAME[capability.value].input_schema)
        assert PAYLOAD_KEY in schema["properties"]
        assert "expected_version" in schema["properties"][PAYLOAD_KEY]["required"]
        assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(schema["properties"])
    assert forged.is_error is True
    assert json.loads(forged.content[0].text)["code"] == ErrorCode.INVALID_REQUEST.value
