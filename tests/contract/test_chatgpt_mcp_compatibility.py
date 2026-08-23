"""Synthetic ChatGPT DCR, OAuth, and shared Streamable HTTP MCP contract."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import TextContent
from sqlalchemy import Connection, create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from tests.conftest import Scene, build_service

from my_pa.adapters.http.oauth import build_origin_oauth_routes
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.remote_identity import (
    REMOTE_IDENTITY_METADATA,
    RemoteIdentityRepository,
    remote_clients,
    remote_security_controls,
)
from my_pa.infrastructure.security.origin_authorization import OriginOAuthServer
from my_pa.infrastructure.security.remote_oauth import (
    RemoteAuthenticationError,
    RemoteAuthenticator,
)

WHEN = datetime(2026, 8, 23, 12, tzinfo=UTC)
ISSUER = "https://mcp.example.invalid"
RESOURCE = f"{ISSUER}/mcp"
CHATGPT_REDIRECT = "https://chatgpt.com/connector/oauth/synthetic-callback"
OPERATOR_SECRET = "s" * 43
VERIFIER = "v" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def identity_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
        connection.execute(
            remote_security_controls.insert().values(
                singleton=True,
                remote_enabled=True,
                writes_enabled=False,
                updated_at=WHEN,
            )
        )
    yield engine
    engine.dispose()


@pytest.mark.anyio
async def test_chatgpt_dcr_oauth_and_shared_mcp_protocol(
    scene: Scene, identity_engine: Engine
) -> None:
    @contextmanager
    def connections() -> Iterator[Connection]:
        with identity_engine.begin() as connection:
            yield connection

    oauth = OriginOAuthServer(
        connections=connections,
        issuer=ISSUER,
        resource=RESOURCE,
        supported_scopes=frozenset({"my-pa.read"}),
        now=lambda: WHEN,
    )
    authenticator = RemoteAuthenticator(
        token_context=oauth.introspect,
        connections=connections,
        required_resource=RESOURCE,
        now=lambda: WHEN,
    )

    def resolve(header: str | None) -> RemoteAccessContext | None:
        try:
            authenticated = authenticator.authenticate(header)
        except RemoteAuthenticationError:
            return None
        return RemoteAccessContext(
            principal=authenticated.principal,
            allowed_capabilities=frozenset(
                capability.value for capability in authenticated.capabilities
            ),
            capability_purposes=authenticated.capability_purposes,
        )

    app = create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=resolve,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource=RESOURCE,
        authorization_servers=(ISSUER,),
        scopes=frozenset({"my-pa.read"}),
        additional_routes=build_origin_oauth_routes(oauth, operator_secret=OPERATOR_SECRET),
    )

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as http,
    ):
        registered = await http.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": [CHATGPT_REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "my-pa.read",
            },
        )
        assert registered.status_code == 201
        client_id = str(registered.json()["client_id"])

        with identity_engine.begin() as connection:
            row = connection.execute(
                select(remote_clients).where(remote_clients.c.oauth_client_id == client_id)
            ).one()
            assert row.client_name == "ChatGPT"
            assert row.writes_enabled is False
            assert row.refresh_enabled is False
            repository = RemoteIdentityRepository(connection)
            repository.grant(
                remote_client_id=row.id,
                external_scope="my-pa.read",
                capability=Capability.CAPABILITIES_GET,
                purpose=Purpose.STATUS_OBSERVATION,
                resource=RESOURCE,
                is_write=False,
                now=WHEN,
            )
            assert repository.set_client_refresh(oauth_client_id=client_id, refresh_enabled=True)

        authorization = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CHATGPT_REDIRECT,
            "scope": "my-pa.read",
            "state": "chatgpt-synthetic-state",
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "resource": RESOURCE,
        }
        consent = await http.get("/oauth/authorize", params=authorization)
        assert consent.status_code == 200
        assert "Client: <strong>ChatGPT</strong>" in consent.text
        approved = await http.post(
            "/oauth/authorize",
            data={
                **authorization,
                "operator_secret": OPERATOR_SECRET,
                "decision": "approve",
            },
        )
        assert approved.status_code == 303
        query = parse_qs(urlsplit(approved.headers["location"]).query)
        assert query["state"] == ["chatgpt-synthetic-state"]

        issued = await http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "client_id": client_id,
                "redirect_uri": CHATGPT_REDIRECT,
                "code_verifier": VERIFIER,
                "resource": RESOURCE,
            },
        )
        assert issued.status_code == 200
        tokens = issued.json()
        assert tokens["token_type"] == "Bearer"  # noqa: S105 - protocol field, not a token
        assert "refresh_token" in tokens

        http.headers["Authorization"] = f"Bearer {tokens['access_token']}"
        async with (
            streamable_http_client("http://testserver/mcp", http_client=http) as streams,
            ClientSession(*streams[:2]) as session,
        ):
            initialized = await session.initialize()
            listed = await session.list_tools()
            result = await session.call_tool(Capability.CAPABILITIES_GET.value, {})

    assert initialized.server_info.name == "my-pa"
    assert [tool.name for tool in listed.tools] == [Capability.CAPABILITIES_GET.value]
    tool = listed.tools[0]
    assert tool.annotations is not None and tool.annotations.read_only_hint is True
    assert tool.meta == {"securitySchemes": [{"type": "oauth2", "scopes": ["my-pa.read"]}]}
    assert result.is_error is False
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text)["error"] is None
