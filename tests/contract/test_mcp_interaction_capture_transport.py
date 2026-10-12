"""The interaction capture around the real remote MCP app.

Drives `create_remote_mcp_app` in process (httpx ASGI transport, as
`test_remote_mcp_transport.py` does) with `McpInteractionCapture` around it and an
in-memory sink behind a real `InteractionRecorder`. Two properties are held:

* **the row is right** — client, principal, method, tool, capability, id,
  status, outcome, error code, sizes and digest, for each kind of exchange the
  endpoint answers;
* **the wire is untouched** — what the client receives (status, headers, body
  bytes) is byte-for-byte what the app sent, and what the app reads is
  byte-for-byte what the client sent, whether the sink works, fails, or the
  capture itself breaks. A probe between the capture and the app records the
  app's side; deterministic exchanges are also compared with the app unwrapped.

The authenticated context is read from `scope["state"]` after the inner app
returns. That this mutation is visible to the outer wrapper is asserted here
rather than assumed, with and without a server-provided `state` dict.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

import httpx2
import pytest
from tests.conftest import Scene, build_service

from my_pa.adapters import mcp_interaction_capture as capture
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp_interaction_capture import InteractionRecorder, McpInteractionCapture
from my_pa.domain.identity.operation import Capability

RESOURCE = "http://testserver"
CLIENT = "client-synthetic-capture"
_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _app(scene: Scene) -> Any:  # noqa: ANN401
    """The real remote app with a resolver that names four credentials."""

    def resolve(authorization: str | None) -> RemoteAccessContext | None:
        if authorization == "Bearer synthetic":
            return RemoteAccessContext(scene.principal, authenticated_client_id=CLIENT)
        if authorization == "Bearer compact":
            return RemoteAccessContext(
                scene.principal,
                authenticated_client_id=CLIENT,
                allowed_capabilities=frozenset({Capability.CAPABILITIES_GET.value}),
                compact_publication=True,
            )
        if authorization == "Bearer empty":
            return RemoteAccessContext(
                scene.principal,
                authenticated_client_id=CLIENT,
                allowed_capabilities=frozenset(),
            )
        return None

    return create_remote_mcp_app(
        build_service(scene.world, scene.providers),
        resolve_access=resolve,
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource=RESOURCE,
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )


class _Probe:
    """Sits between the capture and the app and records the app's side of the wire."""

    def __init__(self, app: Any) -> None:  # noqa: ANN401
        self.app = app
        self.exchanges: list[dict[str, Any]] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        record: dict[str, Any] = {"read": b"", "start": None, "body": b""}
        self.exchanges.append(record)

        async def probe_receive() -> Any:  # noqa: ANN401
            message = await receive()
            if message["type"] == "http.request":
                record["read"] += message.get("body", b"")
            return message

        async def probe_send(message: Any) -> None:  # noqa: ANN401
            if message["type"] == "http.response.start":
                record["start"] = (message["status"], list(message.get("headers", [])))
            elif message["type"] == "http.response.body":
                record["body"] += message.get("body", b"")
            await send(message)

        await self.app(scope, probe_receive, probe_send)


async def _exchange(
    asgi: Any,  # noqa: ANN401
    lifespan_app: Any,  # noqa: ANN401
    requests: list[tuple[str, str, object]],
    between: Callable[[int], Awaitable[None]] | None = None,
) -> list[httpx2.Response]:
    responses: list[httpx2.Response] = []
    async with (
        lifespan_app.router.lifespan_context(lifespan_app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=asgi), base_url="http://testserver"
        ) as client,
    ):
        for index, (method, authorization, body) in enumerate(requests):
            if between is not None:
                await between(index)
            headers = {**_HEADERS, "Authorization": authorization}
            if method == "GET":
                responses.append(await client.get(str(body), headers=headers))
            else:
                responses.append(
                    await client.post("/mcp", headers=headers, content=json.dumps(body).encode())
                )
    return responses


def _wire(response: httpx2.Response) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    return response.status_code, list(response.headers.raw), response.content


def _initialize(request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "synthetic", "version": "1"},
        },
    }


def _call(request_id: int, name: str, arguments: object) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


#: One of each kind of exchange the endpoint answers, in order.
_REQUESTS: list[tuple[str, str, object]] = [
    ("POST", "Bearer synthetic", _initialize()),
    ("POST", "Bearer synthetic", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ("POST", "Bearer synthetic", _call(3, Capability.CAPABILITIES_GET.value, {})),
    (
        "POST",
        "Bearer compact",
        _call(4, "my_pa.read", {"capability": Capability.CAPABILITIES_GET.value, "arguments": {}}),
    ),
    ("POST", "Bearer synthetic", {"jsonrpc": "2.0", "id": 5, "method": "nope/nope"}),
    ("POST", "Bearer synthetic", {"jsonrpc": "2.0", "id": 6, "method": "tools/call"}),
    ("POST", "Bearer synthetic", _call(7, "no.such.tool", {})),
    ("POST", "Bearer revoked", _initialize(8)),
    ("POST", "Bearer empty", _initialize(9)),
    ("GET", "Bearer synthetic", "/healthz"),
    ("GET", "Bearer synthetic", "/readyz"),
    ("GET", "Bearer synthetic", "/.well-known/oauth-protected-resource"),
]


def _expected(
    principal_id: str,
) -> list[dict[str, object]]:
    authenticated = {
        "oauth_client_id": CLIENT,
        "principal_id": principal_id,
        "principal_kind": "operator",
    }
    anonymous = {"oauth_client_id": None, "principal_id": None, "principal_kind": None}
    return [
        {
            **authenticated,
            "jsonrpc_method": "initialize",
            "jsonrpc_id": "1",
            "tool_name": None,
            "capability": None,
            "http_status": 200,
            "outcome": "ok",
            "error_code": None,
        },
        {
            **authenticated,
            "jsonrpc_method": "tools/list",
            "jsonrpc_id": "2",
            "tool_name": None,
            "capability": None,
            "http_status": 200,
            "outcome": "ok",
            "error_code": None,
        },
        {
            **authenticated,
            "jsonrpc_method": "tools/call",
            "jsonrpc_id": "3",
            "tool_name": "capabilities.get",
            "capability": "capabilities.get",
            "http_status": 200,
            "outcome": "ok",
            "error_code": None,
        },
        {
            **authenticated,
            "jsonrpc_method": "tools/call",
            "jsonrpc_id": "4",
            "tool_name": "my_pa.read",
            "capability": "capabilities.get",
            "http_status": 200,
            "outcome": "ok",
            "error_code": None,
        },
        {
            **authenticated,
            "jsonrpc_method": "nope/nope",
            "jsonrpc_id": "5",
            "tool_name": None,
            "capability": None,
            "http_status": 200,
            "outcome": "jsonrpc_error",
            "error_code": "-32601",
        },
        {
            **authenticated,
            "jsonrpc_method": "tools/call",
            "jsonrpc_id": "6",
            "tool_name": None,
            "capability": None,
            "http_status": 200,
            "outcome": "jsonrpc_error",
            "error_code": "-32602",
        },
        {
            **authenticated,
            "jsonrpc_method": "tools/call",
            "jsonrpc_id": "7",
            "tool_name": "no.such.tool",
            "capability": "no.such.tool",
            "http_status": 200,
            "outcome": "tool_error",
            "error_code": "unsupported",
        },
        # The endpoint refuses before it reads the body, so the request side is
        # `not_captured` and nothing JSON-RPC is known.
        {
            **anonymous,
            "jsonrpc_method": None,
            "jsonrpc_id": None,
            "tool_name": None,
            "capability": None,
            "http_status": 401,
            "outcome": "auth_refused",
            "error_code": "invalid_token",
        },
        # `_McpEndpoint` sets `scope["state"]` only for a request it admits, so an
        # `insufficient_scope` refusal carries no client either.
        {
            **anonymous,
            "jsonrpc_method": None,
            "jsonrpc_id": None,
            "tool_name": None,
            "capability": None,
            "http_status": 403,
            "outcome": "auth_refused",
            "error_code": "insufficient_scope",
        },
    ]


def _recorder(
    rows: list[Mapping[str, object]],
    **kwargs: Any,  # noqa: ANN401
) -> InteractionRecorder:
    return InteractionRecorder(rows.append, stderr=io.StringIO(), **kwargs)


@pytest.mark.anyio
async def test_each_exchange_is_one_row_with_the_right_metadata_and_an_untouched_wire(
    scene: Scene,
) -> None:
    app = _app(scene)
    probe = _Probe(app)
    rows: list[Mapping[str, object]] = []
    recorder = _recorder(rows)
    recorder.start()
    try:
        responses = await _exchange(McpInteractionCapture(probe, recorder), app, _REQUESTS)
    finally:
        recorder.stop(timeout=5)

    expected = _expected(scene.principal.principal_id)
    assert len(rows) == len(expected), "only /mcp is captured; health/readiness/metadata are not"
    assert recorder.dropped == recorder.write_failures == recorder.capture_errors == 0
    for row, want, response, seen, (_, _, sent) in zip(
        rows, expected, responses, probe.exchanges, _REQUESTS, strict=False
    ):
        assert {key: row[key] for key in want} == want
        # The wire, both directions, is exactly what the app saw and sent.
        assert response.status_code == seen["start"][0]
        assert list(response.headers.raw) == seen["start"][1]
        assert response.content == seen["body"]
        # The size is of the full body the client received; the digest is of the
        # redacted serialization the row stores, never of the wire body.
        assert row["response_bytes"] == len(response.content)
        stored = row["response_body"]
        assert stored is not None
        redacted = json.dumps(stored, ensure_ascii=False, separators=(",", ":")).encode()
        assert row["response_sha256"] == hashlib.sha256(redacted).hexdigest()
        assert row["diagnostics"]["capture"]["response_hash_scope"] == "redacted_full"  # type: ignore[index]
        if row["http_status"] in {401, 403}:
            assert seen["read"] == b""
            assert row["request_bytes"] == 0
            assert row["diagnostics"]["capture"]["request_parse"] == "not_captured"  # type: ignore[index]
        else:
            assert seen["read"] == json.dumps(sent).encode()
            assert row["request_bytes"] == len(seen["read"])
            compact = json.dumps(sent, ensure_ascii=False, separators=(",", ":")).encode()
            assert row["request_sha256"] == hashlib.sha256(compact).hexdigest()
            assert row["request_body"] == sent
        assert row["http_method"] == "POST"
        assert isinstance(row["latency_ms"], float) and row["latency_ms"] >= 0
        assert row["started_at"].tzinfo is not None  # type: ignore[attr-defined]
        assert row["request_headers"]["content-type"] == "application/json"  # type: ignore[index]
        assert "authorization" not in row["request_headers"]  # type: ignore[operator]
        assert "Bearer" not in json.dumps(row, default=str)
    # The ProblemDetail and the correlation the client was given are recorded.
    tool_error = rows[6]
    problem = json.loads(responses[6].json()["result"]["content"][0]["text"])
    assert tool_error["correlation_id"] == problem["correlation_id"]
    assert tool_error["diagnostics"]["problem"]["code"] == "unsupported"  # type: ignore[index]
    assert tool_error["diagnostics"]["is_error"] is True  # type: ignore[index]
    success = json.loads(responses[2].json()["result"]["content"][0]["text"])
    assert rows[2]["correlation_id"] == success["correlation_id"]
    assert rows[4]["diagnostics"]["jsonrpc_error"]["message"] == "Method not found"  # type: ignore[index]
    assert rows[7]["diagnostics"]["endpoint_error"] == "invalid_token"  # type: ignore[index]


@pytest.mark.anyio
async def test_deterministic_exchanges_are_identical_with_and_without_the_wrapper(
    scene: Scene,
) -> None:
    deterministic = [_REQUESTS[i] for i in (0, 1, 4, 5, 7, 8, 9, 10, 11)]
    unwrapped = _app(scene)
    plain = await _exchange(unwrapped, unwrapped, deterministic)
    app = _app(scene)
    rows: list[Mapping[str, object]] = []
    recorder = _recorder(rows)
    recorder.start()
    try:
        wrapped = await _exchange(McpInteractionCapture(app, recorder), app, deterministic)
    finally:
        recorder.stop(timeout=5)
    assert [_wire(r) for r in wrapped] == [_wire(r) for r in plain]
    assert len(rows) == 6


@pytest.mark.anyio
async def test_the_access_context_is_visible_when_the_server_provides_a_state_dict(
    scene: Scene,
) -> None:
    """Uvicorn hands every request a (copied) lifespan `state` dict; the mutation must show."""
    app = _app(scene)
    rows: list[Mapping[str, object]] = []
    recorder = _recorder(rows)
    wrapped = McpInteractionCapture(app, recorder)

    async def with_server_state(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        if scope["type"] == "http":
            scope["state"] = {}
        await wrapped(scope, receive, send)

    recorder.start()
    try:
        await _exchange(with_server_state, app, [_REQUESTS[0]])
    finally:
        recorder.stop(timeout=5)
    (row,) = rows
    assert row["oauth_client_id"] == CLIENT
    assert row["principal_id"] == scene.principal.principal_id


@pytest.mark.anyio
async def test_a_failing_sink_changes_no_response_and_is_reported_on_the_next_row(
    scene: Scene,
) -> None:
    app = _app(scene)
    probe = _Probe(app)
    rows: list[Mapping[str, object]] = []
    failing = [True]

    def sink(row: Mapping[str, object]) -> None:
        if failing[0]:
            raise ConnectionError("database unavailable")
        rows.append(row)

    stderr = io.StringIO()
    recorder = InteractionRecorder(sink, stderr=stderr)
    recorder.start()
    wrapped = McpInteractionCapture(probe, recorder)

    async def recover_before_the_fourth(index: int) -> None:
        if index != 3:
            return
        # Wait for the writer to have tried all three before letting writes succeed.
        for _ in range(500):
            if recorder.write_failures == 3:
                break
            await asyncio.sleep(0.01)
        failing[0] = False

    try:
        responses = await _exchange(
            wrapped, app, [*_REQUESTS[:3], _REQUESTS[1]], recover_before_the_fourth
        )
    finally:
        recorder.stop(timeout=5)
    for response, seen in zip(responses, probe.exchanges, strict=True):
        assert response.status_code == 200
        assert response.content == seen["body"]
    assert recorder.write_failures == 3
    (row,) = rows
    assert row["diagnostics"]["capture"]["write_failures_before"] == 3  # type: ignore[index]
    assert "write_failures=3" in stderr.getvalue()
    assert "capabilities" not in stderr.getvalue()


@pytest.mark.anyio
async def test_a_full_queue_drops_and_counts_without_touching_the_request(scene: Scene) -> None:
    unwrapped = _app(scene)
    plain = await _exchange(unwrapped, unwrapped, [_REQUESTS[0], _REQUESTS[1], _REQUESTS[4]])
    app = _app(scene)
    rows: list[Mapping[str, object]] = []
    recorder = _recorder(rows, maxsize=1)  # not started: nothing drains the queue
    wrapped = await _exchange(
        McpInteractionCapture(app, recorder), app, [_REQUESTS[0], _REQUESTS[1], _REQUESTS[4]]
    )
    assert [_wire(r) for r in wrapped] == [_wire(r) for r in plain]
    assert recorder.dropped == 2
    recorder.start()
    recorder.stop(timeout=5)
    assert len(rows) == 1


@pytest.mark.anyio
async def test_broken_capture_internals_change_no_response(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    unwrapped = _app(scene)
    plain = await _exchange(unwrapped, unwrapped, [_REQUESTS[0], _REQUESTS[4], _REQUESTS[7]])
    app = _app(scene)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("capture broke")

    monkeypatch.setattr(capture._Exchange, "on_request", explode)
    monkeypatch.setattr(capture._Exchange, "on_response", explode)
    monkeypatch.setattr(capture._Exchange, "captured", explode)
    rows: list[Mapping[str, object]] = []
    recorder = _recorder(rows)
    recorder.start()
    try:
        wrapped = await _exchange(
            McpInteractionCapture(app, recorder), app, [_REQUESTS[0], _REQUESTS[4], _REQUESTS[7]]
        )
    finally:
        recorder.stop(timeout=5)
    assert [_wire(r) for r in wrapped] == [_wire(r) for r in plain]
    assert recorder.capture_errors >= 3
    assert rows == []
