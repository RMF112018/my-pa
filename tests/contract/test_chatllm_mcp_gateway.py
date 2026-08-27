"""Compact publication profile on the existing `/mcp` resource."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.conftest import Scene, build_service

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
)
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    REMOTE_OWNED_PAYLOAD_FIELDS,
    SERVER_OWNED_REMOTE_FIELDS,
    remote_tool_schema,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

RESOURCE = "https://mcp.example.invalid/mcp"
ISSUER = "https://mcp.example.invalid"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(
    scene: Scene,
    *,
    compact: bool,
    allowed: frozenset[str],
    purposes: frozenset[tuple[Capability, Purpose | None]] | None = None,
    writes_enabled: bool = False,
    operator: bool = False,
) -> object:
    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: RemoteAccessContext(
            principal=scene.principal,
            allowed_capabilities=allowed,
            capability_purposes=purposes,
            relationship_grant_profile="remote.operator" if operator else None,
            compact_publication=compact,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=writes_enabled,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({"my-pa.read"}),
    )


async def _session(app: object, exercise: Callable[..., object]) -> object:
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
        return await exercise(session)


@pytest.mark.anyio
async def test_unselected_client_keeps_canonical_tools(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(_app(scene, compact=False, allowed=allowed), exercise)
    assert DESCRIBE_TOOL not in names
    assert Capability.TASKS_SEARCH.value in names
    assert Capability.CAPABILITIES_GET.value in names


@pytest.mark.anyio
async def test_selected_client_lists_only_the_facade(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(_app(scene, compact=False, allowed=allowed), exercise)
    compact_names = await _session(_app(scene, compact=True, allowed=allowed), exercise)
    assert compact_names == {DESCRIBE_TOOL, READ_TOOL}
    assert Capability.TASKS_SEARCH.value not in compact_names
    assert names >= {Capability.TASKS_SEARCH.value, Capability.CAPABILITIES_GET.value}


@pytest.mark.anyio
async def test_write_umbrella_is_omitted_when_writes_disabled(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_SEARCH.value, Capability.TASKS_CREATE.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(
        _app(scene, compact=True, allowed=allowed, writes_enabled=False),
        exercise,
    )
    assert WRITE_TOOL not in names
    assert READ_TOOL in names


@pytest.mark.anyio
async def test_write_umbrella_appears_when_an_eligible_write_exists(scene: Scene) -> None:
    allowed = frozenset({Capability.TASKS_CREATE.value})
    purposes = frozenset({(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING)})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    names = await _session(
        _app(
            scene,
            compact=True,
            allowed=allowed,
            purposes=purposes,
            writes_enabled=True,
        ),
        exercise,
    )
    assert names == {DESCRIBE_TOOL, WRITE_TOOL}


@pytest.mark.anyio
async def test_operator_tool_requires_operator_profile(scene: Scene) -> None:
    merge = frozenset({Capability.ENTITIES_MERGE_PREVIEW.value, Capability.ENTITIES_MERGE.value})

    async def exercise(session: ClientSession) -> set[str]:
        return {tool.name for tool in (await session.list_tools()).tools}

    normal = await _session(
        _app(scene, compact=True, allowed=merge, writes_enabled=True, operator=False),
        exercise,
    )
    operator = await _session(
        _app(scene, compact=True, allowed=merge, writes_enabled=True, operator=True),
        exercise,
    )
    assert OPERATOR_TOOL not in normal
    assert OPERATOR_TOOL in operator


@pytest.mark.anyio
async def test_describe_and_read_round_trip(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})
    purposes = frozenset({(Capability.CAPABILITIES_GET, None)})

    async def exercise(session: ClientSession) -> tuple[object, object, object]:
        listed = await session.list_tools()
        described = await session.call_tool(DESCRIBE_TOOL, {})
        read = await session.call_tool(
            READ_TOOL,
            {"capability": Capability.CAPABILITIES_GET.value, "arguments": {}},
        )
        return listed, described, read

    listed, described, read = await _session(
        _app(scene, compact=True, allowed=allowed, purposes=purposes),
        exercise,
    )
    names = {tool.name for tool in listed.tools}
    assert names == {DESCRIBE_TOOL, READ_TOOL}
    body = json.loads(described.content[0].text)
    assert body["profile"] == "chatllm-gateway-v1"
    assert body["items"][0]["capability"] == Capability.CAPABILITIES_GET.value
    assert read.is_error is False
    envelope = json.loads(read.content[0].text)
    assert envelope["error"] is None


@pytest.mark.anyio
async def test_describe_lookup_matches_remote_schema_and_round_trips(scene: Scene) -> None:
    scene.world.work_evidence_refs.add((scene.principal.principal_id, "cap_origin0001origin0001"))
    read_name = Capability.CAPABILITIES_GET.value
    write_name = Capability.TASKS_CREATE.value
    tools = {tool.name: tool for tool in TOOLS}

    async def exercise(session: ClientSession) -> tuple[object, ...]:
        described_read = await session.call_tool(DESCRIBE_TOOL, {"capability": read_name})
        described_write = await session.call_tool(DESCRIBE_TOOL, {"capability": write_name})
        read_schema = json.loads(described_read.content[0].text)["input_schema"]
        write_schema = json.loads(described_write.content[0].text)["input_schema"]
        read_args = {name: {} for name in read_schema.get("properties", {}) if name != "payload"}
        if "payload" in read_schema.get("properties", {}):
            required = read_schema["properties"]["payload"].get("required", [])
            read_args["payload"] = dict.fromkeys(required, "synthetic") if required else {}
        read = await session.call_tool(READ_TOOL, {"capability": read_name, "arguments": read_args})
        write_payload = {
            "title": "Describe schema write",
            "origin_evidence_ref": "cap_origin0001origin0001",
        }
        write = await session.call_tool(
            WRITE_TOOL,
            {"capability": write_name, "arguments": {"payload": write_payload}},
        )
        invalid = await session.call_tool(
            WRITE_TOOL,
            {"capability": write_name, "arguments": {"payload": {}}},
        )
        return described_read, described_write, read, write, invalid, read_schema, write_schema

    app = _app(
        scene,
        compact=True,
        allowed=frozenset({read_name, write_name}),
        purposes=frozenset(
            {
                (Capability.CAPABILITIES_GET, None),
                (Capability.TASKS_CREATE, Purpose.TASK_AUTHORING),
            }
        ),
        writes_enabled=True,
    )
    (
        described_read,
        described_write,
        read,
        write,
        invalid,
        read_schema,
        write_schema,
    ) = await _session(app, exercise)
    assert json.loads(described_read.content[0].text)["input_schema"] == remote_tool_schema(
        tools[read_name].input_schema
    )
    assert json.loads(described_write.content[0].text)["input_schema"] == remote_tool_schema(
        tools[write_name].input_schema
    )
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(read_schema["properties"])
    assert SERVER_OWNED_REMOTE_FIELDS.isdisjoint(write_schema["properties"])
    assert "idempotency_key" not in write_schema["properties"]["payload"]["properties"]
    write_payload_schema = write_schema["properties"]["payload"]["properties"]
    assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(write_payload_schema)
    assert read.is_error is False
    assert write.is_error is False
    assert invalid.is_error is True
    assert json.loads(invalid.content[0].text)["code"] == "invalid_request"


@pytest.mark.anyio
async def test_canonical_call_on_compact_client_is_unpublished(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> object:
        return await session.call_tool(Capability.CAPABILITIES_GET.value, {})

    result = await _session(_app(scene, compact=True, allowed=allowed), exercise)
    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "unsupported"


@pytest.mark.anyio
async def test_facade_name_on_full_client_is_unpublished(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})

    async def exercise(session: ClientSession) -> object:
        return await session.call_tool(
            READ_TOOL,
            {"capability": Capability.CAPABILITIES_GET.value, "arguments": {}},
        )

    result = await _session(_app(scene, compact=False, allowed=allowed), exercise)
    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "unsupported"


@pytest.mark.anyio
async def test_protected_resource_metadata_is_unchanged(scene: Scene) -> None:
    compact = _app(
        scene,
        compact=True,
        allowed=frozenset({Capability.CAPABILITIES_GET.value}),
    )
    challenged = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: None,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({"my-pa.read"}),
    )
    async with (
        compact.router.lifespan_context(compact),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=compact), base_url="http://testserver"
        ) as client,
    ):
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        missing = await client.get("/.well-known/oauth-protected-resource/mcp/chatllm")
        missing_path = await client.post("/mcp/chatllm")
    async with (
        challenged.router.lifespan_context(challenged),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=challenged), base_url="http://testserver"
        ) as client,
    ):
        refused = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert metadata.json()["resource"] == RESOURCE
    assert refused.status_code == 401
    assert "chatllm" not in refused.headers["WWW-Authenticate"]
    assert missing.status_code == 404
    assert missing_path.status_code == 404


@pytest.mark.anyio
async def test_server_owned_fields_in_nested_arguments_still_fail(scene: Scene) -> None:
    allowed = frozenset({Capability.CAPABILITIES_GET.value})
    purposes = frozenset({(Capability.CAPABILITIES_GET, None)})

    async def exercise(session: ClientSession) -> object:
        forged = dict.fromkeys(sorted(SERVER_OWNED_REMOTE_FIELDS), "forged")
        return await session.call_tool(
            READ_TOOL,
            {"capability": Capability.CAPABILITIES_GET.value, "arguments": forged},
        )

    result = await _session(
        _app(scene, compact=True, allowed=allowed, purposes=purposes),
        exercise,
    )
    assert result.is_error is True
    assert json.loads(result.content[0].text)["code"] == "invalid_request"


def test_full_process_still_publishes_canonical_tools_when_compact_off(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    names = {tool.name for tool in published_tools(service)}
    assert DESCRIBE_TOOL not in names
    assert Capability.CAPABILITIES_GET.value in names
