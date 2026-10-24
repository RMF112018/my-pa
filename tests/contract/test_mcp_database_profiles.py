"""Real MCP protocol routing with two synthetic application services."""

from __future__ import annotations

from dataclasses import replace

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from tests.conftest import Scene, build_service

from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.bootstrap.mcp_database_profiles import McpDatabaseServices
from my_pa.domain.identity.operation import Capability, permitted_purposes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "client,writes,expect_write", [("ro", True, False), ("rw", False, False), ("rw", True, True)]
)
async def test_profile_catalog_and_direct_calls_have_same_ceiling(
    scene: Scene, client: str, writes: bool, expect_write: bool
) -> None:
    ro = build_service(scene.world, scene.providers)
    rw = build_service(scene.world, scene.providers)
    profiles = McpDatabaseServices(ro, rw, frozenset({"ro"}), frozenset({"rw"}), ())  # type: ignore[arg-type]
    context = RemoteAccessContext(
        scene.principal,
        authenticated_client_id=client,
        allowed_capabilities=frozenset(c.value for c in Capability),
        capability_purposes=frozenset((c, p) for c in Capability for p in permitted_purposes(c)),
    )
    app = create_remote_mcp_app(
        ro,
        resolve_access=lambda _: profiles.access(context, write_allowed=writes),
        require_bound_service=True,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://mcp.example.invalid",),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        assert (Capability.CANVAS_WORKSPACE_PUT.value in names) is expect_write
        for name in (
            Capability.REPORTS_COMMIT.value,
            Capability.TASKS_CREATE.value,
            Capability.CAPTURE_CREATE.value,
        ):
            assert name not in names
            assert (await session.call_tool(name, {})).is_error
        focus = "ent_" + "a" * 32
        write = await session.call_tool(
            Capability.CANVAS_WORKSPACE_PUT.value,
            {
                "payload": {
                    "focus_entity_id": focus,
                    "scope_entity_id": None,
                    "expected_version": 0,
                    "positions": {focus: {"x": 1.0, "y": 2.0}},
                }
            },
        )
        assert bool(write.is_error) is not expect_write
        # Malformed selectors must never select a service or grant write authority.
        result = await session.call_tool(
            Capability.CANVAS_WORKSPACE_GET.value,
            {"payload": {"database_profile": "rw", "principal_id": scene.principal.principal_id}},
        )
        assert result.is_error
        # Revocation/unmapping is rechecked even on this established SDK session.
        context = replace(context, authenticated_client_id="unmapped")
        with pytest.raises(
            (MCPError, httpx2.HTTPStatusError)
        ):  # Refused at the authenticated HTTP boundary.
            await session.list_tools()


@pytest.mark.anyio
async def test_missing_bound_service_never_falls_back_to_control_service(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda _: RemoteAccessContext(scene.principal),
        require_bound_service=True,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://mcp.example.invalid",),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        assert not (await session.list_tools()).tools
        assert (await session.call_tool(Capability.CAPABILITIES_GET.value, {})).is_error


@pytest.mark.anyio
@pytest.mark.parametrize("writes", [False, True])
async def test_compact_umbrella_cannot_bypass_profile_or_protected_ceiling(
    scene: Scene, writes: bool
) -> None:
    service = build_service(scene.world, scene.providers)
    profiles = McpDatabaseServices(service, service, frozenset({"ro"}), frozenset({"rw"}), ())  # type: ignore[arg-type]
    context = RemoteAccessContext(
        scene.principal,
        authenticated_client_id="rw" if writes else "ro",
        compact_publication=True,
        allowed_capabilities=frozenset(c.value for c in Capability),
        capability_purposes=frozenset((c, p) for c in Capability for p in permitted_purposes(c)),
    )
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda _: profiles.access(context, write_allowed=True),
        require_bound_service=True,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://mcp.example.invalid",),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        names = {t.name for t in (await session.list_tools()).tools}
        assert ("my_pa.write" in names) is writes
        blocked = await session.call_tool(
            "my_pa.write", {"capability": "reports.commit", "payload": {}}
        )
        assert blocked.is_error
        hidden = await session.call_tool(
            "my_pa.read", {"capability": "tasks.create", "payload": {}}
        )
        assert hidden.is_error


@pytest.mark.anyio
async def test_revoked_write_grant_demotes_established_session_to_ro_service(scene: Scene) -> None:
    from my_pa.domain.identity.purpose import Purpose

    ro = build_service(scene.world, scene.providers)
    rw = build_service(scene.world, scene.providers)
    profiles = McpDatabaseServices(ro, rw, frozenset(), frozenset({"rw"}), ())  # type: ignore[arg-type]
    read = Capability.CANVAS_WORKSPACE_GET
    write = Capability.CANVAS_WORKSPACE_PUT
    current = RemoteAccessContext(
        scene.principal,
        authenticated_client_id="rw",
        allowed_capabilities=frozenset({read.value, write.value}),
        capability_purposes=frozenset(
            {(read, Purpose.CANVAS_WORKSPACE_READ), (write, Purpose.CANVAS_WORKSPACE_AUTHORING)}
        ),
    )
    selections = []

    def resolve(_header: str | None) -> RemoteAccessContext | None:
        bound = profiles.access(current, write_allowed=True)
        assert bound is not None
        selections.append(bound.service)
        return bound

    app = create_remote_mcp_app(
        ro,
        resolve_access=resolve,
        require_bound_service=True,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="https://mcp.example.invalid/mcp",
        authorization_servers=("https://mcp.example.invalid",),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(streams[0], streams[1]) as session,
    ):
        await session.initialize()
        assert write.value in {t.name for t in (await session.list_tools()).tools}
        assert selections[-1] is rw
        # Token read scope, expired/revoked grant and deny overlay all arrive as a
        # fresh reduced capability/purpose ceiling; the durable write flag may stay true.
        current = replace(
            current,
            allowed_capabilities=frozenset({read.value}),
            capability_purposes=frozenset({(read, Purpose.CANVAS_WORKSPACE_READ)}),
        )
        assert write.value not in {t.name for t in (await session.list_tools()).tools}
        assert selections[-1] is ro
        assert (await session.call_tool(write.value, {})).is_error
        assert selections[-1] is ro
