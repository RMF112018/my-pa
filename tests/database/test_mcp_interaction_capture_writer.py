"""The composed interaction log writes real rows, and a dead database changes no response.

Both tests go through `apps.gateway.with_interaction_log`, the composition the
`mcp-remote` process uses: its own bounded engine, a one-row-per-transaction
sink over `insert_interaction`, and the background recorder. The first appends
into a current-head clone and reads the rows back; the second points the writer
at a closed local port and shows the responses are byte-identical to an
unwrapped app's while the failures are counted.
"""

from __future__ import annotations

import io
import json
import socket
from typing import Any

import httpx2
import pytest
from apps.gateway import with_interaction_log
from sqlalchemy import Engine

from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp_interaction_capture import McpInteractionCapture
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.persistence.mcp_interactions import (
    get_interaction,
    list_interactions,
)
from tests.conftest import Scene, build_service

pytestmark = pytest.mark.database

CLIENT = "client-synthetic-db"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(scene: Scene) -> Any:  # noqa: ANN401
    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=lambda authorization: (
            RemoteAccessContext(scene.principal, authenticated_client_id=CLIENT)
            if authorization == "Bearer synthetic"
            else None
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="http://testserver",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


_BODIES: list[tuple[str, dict[str, object]]] = [
    (
        "Bearer synthetic",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": Capability.CAPABILITIES_GET.value,
                "arguments": {"api_key": "MARKERDBSECRET"},
            },
        },
    ),
    ("Bearer synthetic", {"jsonrpc": "2.0", "id": 2, "method": "nope/nope"}),
    ("Bearer revoked", {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}),
]


async def _post_all(asgi: Any, lifespan_app: Any) -> list[httpx2.Response]:  # noqa: ANN401
    responses = []
    async with (
        lifespan_app.router.lifespan_context(lifespan_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=asgi), base_url="http://testserver"
        ) as client,
    ):
        for authorization, body in _BODIES:
            responses.append(
                await client.post(
                    "/mcp",
                    headers={
                        "Authorization": authorization,
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(body).encode(),
                )
            )
    return responses


@pytest.mark.anyio
async def test_the_composed_sink_appends_redacted_rows(
    scene: Scene, db_engine: Engine, cloned_database_url: str
) -> None:
    settings = Settings(database_url=cloned_database_url, mcp_interaction_log_enabled=True)
    app = _app(scene)
    served, close = with_interaction_log(settings, app)
    assert isinstance(served, McpInteractionCapture)
    try:
        responses = await _post_all(served, app)
    finally:
        close()
    assert served.recorder.write_failures == 0
    assert served.recorder.dropped == 0

    with db_engine.connect() as connection:
        summaries = list_interactions(connection, limit=10)
        full = {s.interaction_id: get_interaction(connection, s.interaction_id) for s in summaries}
    assert len(summaries) == 3
    by_id = {
        summary.jsonrpc_id: full[summary.interaction_id]
        for summary in summaries
        if summary.jsonrpc_id is not None
    }
    call = by_id["1"]
    assert call is not None
    assert call.oauth_client_id == CLIENT
    assert call.principal_id == scene.principal.principal_id
    assert call.capability == Capability.CAPABILITIES_GET.value
    # The synthetic secret is an argument `capabilities.get` does not take, so
    # the call is refused as a tool error carrying the ProblemDetail.
    assert (call.outcome, call.error_code) == ("tool_error", "invalid_request")
    assert call.diagnostics["problem"]["code"] == "invalid_request"  # type: ignore[index]
    assert call.http_status == 200
    assert call.response_bytes == len(responses[0].content)
    assert call.request_body["params"]["arguments"] == {"api_key": "[REDACTED]"}  # type: ignore[index]
    assert call.correlation_id is not None
    assert call.recorded_at is not None
    error = by_id["2"]
    assert error is not None
    assert (error.outcome, error.error_code) == ("jsonrpc_error", "-32601")
    refused = next(s for s in summaries if s.http_status == 401)
    assert (refused.outcome, refused.error_code) == ("auth_refused", "invalid_token")
    assert refused.oauth_client_id is None
    for interaction in full.values():
        assert interaction is not None
        stored = json.dumps(
            [interaction.request_body, interaction.response_body, interaction.request_headers]
        )
        assert "MARKERDBSECRET" not in stored
        assert "Bearer" not in stored


def _closed_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.anyio
async def test_an_unreachable_database_changes_no_response_and_counts_failures(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    unwrapped = _app(scene)
    plain = await _post_all(unwrapped, unwrapped)

    url = f"postgresql+psycopg://nobody@127.0.0.1:{_closed_port()}/nowhere"
    settings = Settings(database_url=url, mcp_interaction_log_enabled=True)
    stderr = io.StringIO()
    monkeypatch.setattr("sys.stderr", stderr)
    app = _app(scene)
    served, close = with_interaction_log(settings, app)
    assert isinstance(served, McpInteractionCapture)
    try:
        responses = await _post_all(served, app)
    finally:
        close()

    def wire(response: httpx2.Response) -> tuple[int, list[tuple[bytes, bytes]]]:
        return response.status_code, list(response.headers.raw)

    assert [wire(r) for r in responses] == [wire(r) for r in plain]
    # Deterministic bodies are byte-identical; the tool result carries a fresh
    # correlation per call, so it is compared on everything but that.
    assert [r.content for r in responses[1:]] == [r.content for r in plain[1:]]
    assert responses[0].json()["result"]["isError"] is plain[0].json()["result"]["isError"]
    assert served.recorder.write_failures == 3
    assert served.recorder.capture_errors == 0
    report = stderr.getvalue()
    assert report.count("write_failed") == 1  # throttled: first failure only
    assert "write_failures=1" in report
    assert "MARKERDBSECRET" not in report


@pytest.mark.anyio
@pytest.mark.parametrize("number", ["NaN", "1e999"])
async def test_a_non_finite_number_in_the_body_still_produces_a_row(
    scene: Scene, db_engine: Engine, cloned_database_url: str, number: str
) -> None:
    """Python parses `NaN` and `1e999` (as inf); JSONB refuses both, so they become strings."""
    settings = Settings(database_url=cloned_database_url, mcp_interaction_log_enabled=True)
    app = _app(scene)
    served, close = with_interaction_log(settings, app)
    assert isinstance(served, McpInteractionCapture)
    raw = (
        '{"jsonrpc":"2.0","id":41,"method":"tools/call","params":{"name":"'
        + Capability.CAPABILITIES_GET.value
        + '","arguments":{},"_meta":{"x":'
        + number
        + "}}}"
    ).encode()
    try:
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=served), base_url="http://testserver"
            ) as client,
        ):
            response = await client.post(
                "/mcp",
                headers={
                    "Authorization": "Bearer synthetic",
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
                content=raw,
            )
    finally:
        close()
    assert response.status_code == 200
    assert served.recorder.write_failures == 0
    with db_engine.connect() as connection:
        (summary,) = list_interactions(connection, limit=10)
        stored = get_interaction(connection, summary.interaction_id)
    assert stored is not None
    assert stored.jsonrpc_id == "41"
    assert stored.request_body["params"]["_meta"] == {"x": number}  # type: ignore[index]
    assert stored.diagnostics["capture"]["non_finite_replaced"] is True  # type: ignore[index]
