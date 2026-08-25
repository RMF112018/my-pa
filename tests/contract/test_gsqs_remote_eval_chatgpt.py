"""ChatGPT-shaped contract for the isolated GSQS remote-eval MCP surface.

Does not mutate production ChatGPT or remote-MCP suites. Synthetic only.
No ChatLLM, no network, no gold, no Phase C.
"""

from __future__ import annotations

from pathlib import Path

import httpx2
import pytest
from tests.integration.gsqs_remote_eval_harness import (
    ALLOWED_HOSTS,
    AUTHORIZATION_SERVERS,
    BEARER_AUTHORIZATION,
    FakePrincipal,
    assert_eval_tool_annotations,
    connected_eval_session,
    empty_eval_service,
    eval_app,
    running_eval_http,
)

from my_pa.adapters.gsqs_remote_eval_mcp import (
    DEFAULT_EVAL_RESOURCE,
    EVAL_TOOL_NEXT,
    EVAL_TOOL_STATUS,
    EVAL_TOOL_SUBMIT,
    create_gsqs_remote_eval_app,
    gsqs_eval_tools,
)
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_FORBIDDEN_SCOPE,
    RemoteEvalError,
)

pytestmark = pytest.mark.anyio

EXPECTED_RESOURCE_METADATA = (
    f"{DEFAULT_EVAL_RESOURCE.removesuffix('/mcp').rstrip('/')}"
    "/.well-known/oauth-protected-resource/mcp"
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class ForbiddenAuthenticator:
    """Valid bearer, missing evaluate scope — ChatGPT expects HTTP 403 here."""

    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        if authorization_header != BEARER_AUTHORIZATION:
            raise RemoteEvalError("UNAUTHENTICATED", "unauthenticated")
        raise RemoteEvalError(ERROR_FORBIDDEN_SCOPE, "insufficient scope")


def test_eval_tools_publish_chatgpt_tool_annotations() -> None:
    tools = gsqs_eval_tools()
    assert tuple(tool.name for tool in tools) == (
        EVAL_TOOL_STATUS,
        EVAL_TOOL_NEXT,
        EVAL_TOOL_SUBMIT,
    )
    assert_eval_tool_annotations(tools)


async def test_tools_list_over_http_carries_chatgpt_tool_annotations(tmp_path: Path) -> None:
    service, _store, _state_root = empty_eval_service(tmp_path)
    app = eval_app(service)
    async with running_eval_http(app) as http, connected_eval_session(http) as session:
        listed = await session.list_tools()
    assert_eval_tool_annotations(listed.tools)


async def test_unauthenticated_mcp_challenge_includes_resource_metadata(tmp_path: Path) -> None:
    service, _store, _state_root = empty_eval_service(tmp_path)
    app = eval_app(service)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        metadata = await client.get("/.well-known/oauth-protected-resource/mcp")
        refused = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert metadata.status_code == 200
    body = metadata.json()
    assert body["resource"] == DEFAULT_EVAL_RESOURCE
    assert "authorization_servers" in body
    assert refused.status_code == 401
    assert EXPECTED_RESOURCE_METADATA in refused.headers.get("www-authenticate", "")


async def test_forbidden_scope_challenge_includes_resource_metadata(tmp_path: Path) -> None:
    service, _store, _state_root = empty_eval_service(tmp_path)
    app = create_gsqs_remote_eval_app(
        ForbiddenAuthenticator(),
        service=service,
        enabled=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=(),
        resource=DEFAULT_EVAL_RESOURCE,
        authorization_servers=AUTHORIZATION_SERVERS,
    )
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": BEARER_AUTHORIZATION},
        ) as client,
    ):
        refused = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert refused.status_code == 403
    assert EXPECTED_RESOURCE_METADATA in refused.headers.get("www-authenticate", "")
