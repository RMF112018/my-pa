"""Mutation-strength proofs for the compact `/mcp` publication profile."""

from __future__ import annotations

import json

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.conftest import Scene, build_service

from my_pa.adapters.mcp import chatllm_gateway as gateway
from my_pa.adapters.mcp.chatllm_gateway import DESCRIBE_TOOL, OPERATOR_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.application.errors import InvalidRequestError, UnsupportedError
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

RESOURCE = "https://mcp.example.invalid/mcp"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(scene: Scene, context: RemoteAccessContext, *, writes_enabled: bool = False) -> object:
    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda _authorization: context,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=writes_enabled,
        resource=RESOURCE,
        authorization_servers=("https://mcp.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


async def _call(app: object, name: str, arguments: dict[str, object] | None = None) -> object:
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
        tools = {tool.name for tool in (await session.list_tools()).tools}
        result = await session.call_tool(name, arguments or {})
        return tools, result


@pytest.mark.anyio
async def test_describe_is_grant_filtered(scene: Scene) -> None:
    context = RemoteAccessContext(
        principal=scene.principal,
        allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
        compact_publication=True,
    )
    tools, described = await _call(_app(scene, context), DESCRIBE_TOOL, {})
    assert READ_TOOL in tools
    body = json.loads(described.content[0].text)
    names = {item["capability"] for item in body["items"]}
    assert names == {Capability.CAPABILITIES_GET.value}
    assert Capability.TASKS_SEARCH.value not in names


def test_taxonomy_cannot_elevate_a_denied_capability() -> None:
    with pytest.raises(UnsupportedError):
        gateway.prepare_compact_call(
            READ_TOOL,
            {"capability": Capability.TASKS_SEARCH.value, "arguments": {}},
            allowed_canonical=frozenset({Capability.CAPABILITIES_GET.value}),
        )


def test_kind_guard_refuses_before_invoke() -> None:
    with pytest.raises(InvalidRequestError):
        gateway.prepare_compact_call(
            READ_TOOL,
            {"capability": Capability.TASKS_CREATE.value, "arguments": {}},
            allowed_canonical=frozenset({Capability.TASKS_CREATE.value}),
        )


def test_caller_principal_is_not_accepted() -> None:
    with pytest.raises(InvalidRequestError):
        gateway.prepare_compact_call(
            READ_TOOL,
            {
                "capability": Capability.CAPABILITIES_GET.value,
                "arguments": {},
                "principal_id": "prn_attacker",
            },
            allowed_canonical=frozenset({Capability.CAPABILITIES_GET.value}),
        )


def test_facade_grant_does_not_authorize_a_canonical_target() -> None:
    with pytest.raises(UnsupportedError):
        gateway.prepare_compact_call(
            READ_TOOL,
            {"capability": READ_TOOL, "arguments": {}},
            allowed_canonical=frozenset({Capability.CAPABILITIES_GET.value}),
        )


def test_writes_are_not_forced_enabled() -> None:
    names = gateway.facade_tool_names(frozenset({Capability.TASKS_SEARCH.value}))
    assert WRITE_TOOL not in names


def test_operator_is_absent_without_operator_targets() -> None:
    names = gateway.facade_tool_names(frozenset({Capability.TASKS_SEARCH.value}))
    assert OPERATOR_TOOL not in names


@pytest.mark.anyio
async def test_payload_cannot_self_select_compact_or_operator(scene: Scene) -> None:
    context = RemoteAccessContext(
        principal=scene.principal,
        allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
        compact_publication=False,
    )
    tools, result = await _call(
        _app(scene, context),
        READ_TOOL,
        {
            "capability": Capability.CAPABILITIES_GET.value,
            "arguments": {},
            "compact": True,
            "profile": "remote.operator",
        },
    )
    assert DESCRIBE_TOOL not in tools
    assert Capability.CAPABILITIES_GET.value in tools
    assert result.is_error is True


@pytest.mark.anyio
async def test_catalog_does_not_cross_principals(scene: Scene) -> None:
    first = RemoteAccessContext(
        principal=scene.principal,
        allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
        compact_publication=True,
    )
    second = RemoteAccessContext(
        principal=scene.principal,
        allowed_capabilities=frozenset({Capability.TASKS_SEARCH.value}),
        capability_purposes=frozenset({(Capability.TASKS_SEARCH, Purpose.TASK_READ)}),
        compact_publication=True,
    )
    _, described_a = await _call(_app(scene, first), DESCRIBE_TOOL, {})
    _, described_b = await _call(_app(scene, second), DESCRIBE_TOOL, {})
    names_a = {item["capability"] for item in json.loads(described_a.content[0].text)["items"]}
    names_b = {item["capability"] for item in json.loads(described_b.content[0].text)["items"]}
    assert names_a == {Capability.CAPABILITIES_GET.value}
    assert names_b == {Capability.TASKS_SEARCH.value}


@pytest.mark.anyio
async def test_unknown_future_name_is_not_auto_admitted(scene: Scene) -> None:
    context = RemoteAccessContext(
        principal=scene.principal,
        allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
        compact_publication=True,
    )
    _, described = await _call(
        _app(scene, context),
        DESCRIBE_TOOL,
        {"capability": "not-a-capability.future"},
    )
    assert described.is_error is True
    assert json.loads(described.content[0].text)["code"] == "unsupported"
