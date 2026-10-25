"""OAuth remains reachable while the global MCP kill switch withholds tools.

The same ASGI composition inputs used by apps.gateway are exercised locally.
All identity, authorization-server state, and application storage are synthetic;
no token endpoint, database, socket, or deployed edge is accessed.
"""

from __future__ import annotations

import json

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.conftest import Scene
from tests.contract.test_origin_oauth_routes import (
    SYNTHETIC_APPROVAL_VALUE,
    FakeAuthorizationServer,
)
from tests.security.test_mcp_surface_controls import CountingService

from my_pa.adapters.http.oauth import build_origin_oauth_routes
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.domain.identity.operation import Capability


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("global_enabled", [False, True], ids=["staging", "enabled-control"])
async def test_oauth_staging_preserves_routes_and_obeys_global_mcp_gate(
    scene: Scene, global_enabled: bool
) -> None:
    server = FakeAuthorizationServer()
    service = CountingService(scene.world)
    readiness_calls: list[bool] = []

    def readiness() -> bool:
        readiness_calls.append(True)
        return True

    app = create_remote_mcp_app(
        service,
        resolve_access=lambda authorization: (
            RemoteAccessContext(scene.principal) if authorization == "Bearer synthetic" else None
        ),
        allowed_hosts=("mcp.example.invalid",),
        global_enabled=global_enabled,
        remote_enabled=True,
        readiness=readiness,
        resource=server.resource,
        authorization_servers=(server.issuer,),
        scopes=server.supported_scopes,
        additional_routes=build_origin_oauth_routes(
            server, operator_secret=SYNTHETIC_APPROVAL_VALUE
        ),
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=server.issuer,
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
    ):
        metadata = await http.get("/.well-known/oauth-authorization-server")
        protected = await http.get("/.well-known/oauth-protected-resource/mcp")
        registration = await http.post("/oauth/register", json={"client_name": "Synthetic"})
        consent = await http.get("/oauth/authorize", params={"state": "synthetic-state"})
        health = await http.get("/healthz")
        ready = await http.get("/readyz")

        assert metadata.status_code == 200
        assert metadata.json()["issuer"] == server.issuer
        assert protected.status_code == 200
        assert protected.json()["resource"] == server.resource
        assert registration.status_code == 201
        assert registration.json()["client_id"] == "client"
        assert consent.status_code == 200
        assert "Synthetic client" in consent.text
        assert SYNTHETIC_APPROVAL_VALUE not in consent.text
        assert server.issued == 0
        assert health.status_code == 200 and health.json() == {"status": "ok"}
        assert ready.status_code == (200 if global_enabled else 503)
        assert ready.json() == {"status": "ready" if global_enabled else "unavailable"}
        assert readiness_calls == ([True] if global_enabled else [])

        async with (
            streamable_http_client(server.resource, http_client=http) as streams,
            ClientSession(*streams[:2]) as session,
        ):
            await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool(Capability.CAPABILITIES_GET.value, {})

    if global_enabled:
        assert Capability.CAPABILITIES_GET.value in {tool.name for tool in listed.tools}
        assert not result.is_error
        assert service.calls == [Capability.CAPABILITIES_GET]
    else:
        assert listed.tools == []
        assert result.is_error
        assert json.loads(result.content[0].text)["code"] == "unsupported"
        assert service.calls == []
