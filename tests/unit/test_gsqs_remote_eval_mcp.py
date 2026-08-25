"""Unit tests for the isolated GSQS remote-eval MCP adapter."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
from base64 import b64decode
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from subprocess import run

import httpx2
from mcp.types import CallToolResult, ImageContent

from my_pa.adapters.gsqs_remote_eval_mcp import (
    DEFAULT_EVAL_RESOURCE,
    EVAL_TOOL_NEXT,
    EVAL_TOOL_STATUS,
    EVAL_TOOL_SUBMIT,
    create_gsqs_remote_eval_app,
    gsqs_eval_disclosure_attempt,
    gsqs_eval_tools,
    invoke_gsqs_eval_tool,
    png_image_content,
    wrap_eval_asgi_send,
)
from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_FORBIDDEN_SCOPE,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_SESSION_NOT_IN_PROGRESS,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    RemoteEvalError,
    RemoteEvalSessionState,
)
from my_pa.infrastructure.security.gsqs_remote_eval_authentication import (
    GsqsRemoteEvalAuthenticationError,
)
from tests.conftest import _staged_gray_png
from tests.unit.test_goodnotes_gsqs_remote_eval_state import (
    VALID_SEGMENTS,
    FakeDisclosure,
    FakeStore,
    _harness,
    _request,
)

ADAPTER = Path("src/my_pa/adapters/gsqs_remote_eval_mcp.py")
ENTRYPOINT = Path("apps/gsqs_remote_eval.py")
PRODUCTION_TOOL_NAMES = ("goodnotes.propose", "goodnotes.work", "goodnotes.content")


@dataclass(frozen=True)
class FakePrincipal:
    principal_id: str


class FakeAuthenticator:
    def __init__(self, principal_id: str = "principal-1") -> None:
        self._principal_id = principal_id
        self._authorization = "Bearer synthetic"

    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        if authorization_header != self._authorization:
            raise RemoteEvalError("UNAUTHENTICATED", "unauthenticated")
        return FakePrincipal(self._principal_id)


class ForbiddenScopeAuthenticator:
    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        _ = authorization_header
        raise RemoteEvalError(ERROR_FORBIDDEN_SCOPE, "insufficient scope")


class ForbiddenScopeAuthErrorAuthenticator:
    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        _ = authorization_header
        raise GsqsRemoteEvalAuthenticationError("FORBIDDEN_SCOPE")


class FakeRasterReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read_png(
        self,
        *,
        session_id: str,
        staged_filename: str,
        content_sha256: str,
        byte_length: int,
    ) -> bytes:
        _ = (session_id, staged_filename, content_sha256, byte_length)
        return self.payload


def _png() -> bytes:
    return _staged_gray_png()


def _error_code(result: CallToolResult) -> str:
    payload = json.loads(result.content[0].text)
    return str(payload["error"])


def _text_payload(result: CallToolResult) -> dict[str, object]:
    texts = [block for block in result.content if getattr(block, "type", None) == "text"]
    assert texts
    payload = json.loads(texts[0].text)
    assert isinstance(payload, dict)
    return payload


def _in_progress_with_png() -> tuple[RemoteEvalService, FakeStore, FakeDisclosure, str, bytes]:
    service, store, clock, _staging, disclosure = _harness()
    session = service.create_session(_request(clock))
    service.seal_ready(session.session_id)
    service.open_repetition(session.session_id, 1)
    png = _png()
    digest = sha256(png).hexdigest()
    manifest = store.manifests[session.session_id]
    cases = list(manifest.cases)
    cases[0] = replace(cases[0], content_sha256=digest, byte_length=len(png))
    store.manifests[session.session_id] = replace(manifest, cases=tuple(cases))
    return service, store, disclosure, session.session_id, png


def test_tools_list_is_exactly_the_three_eval_names() -> None:
    names = tuple(tool.name for tool in gsqs_eval_tools())
    assert names == (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT, EVAL_TOOL_SUBMIT)
    for production in PRODUCTION_TOOL_NAMES:
        assert production not in names


def test_eval_tools_restore_annotations_and_keep_oauth_meta() -> None:
    tools = {tool.name: tool for tool in gsqs_eval_tools()}
    status = tools[EVAL_TOOL_STATUS].annotations
    nxt = tools[EVAL_TOOL_NEXT].annotations
    submit = tools[EVAL_TOOL_SUBMIT].annotations
    assert status is not None
    assert nxt is not None
    assert submit is not None
    assert status.read_only_hint is True
    assert status.destructive_hint is False
    assert status.open_world_hint is False
    assert nxt.read_only_hint is False
    assert nxt.destructive_hint is False
    assert nxt.open_world_hint is False
    assert submit.read_only_hint is False
    assert submit.destructive_hint is False
    assert submit.open_world_hint is False
    for tool in tools.values():
        meta = tool.meta or {}
        schemes = meta.get("securitySchemes")
        assert isinstance(schemes, list)
        assert schemes[0]["type"] == "oauth2"
        assert "my-pa.gsqs.evaluate" in schemes[0]["scopes"]


def test_input_schemas_forbid_additional_properties() -> None:
    tools = {tool.name: tool for tool in gsqs_eval_tools()}
    for name in (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT, EVAL_TOOL_SUBMIT):
        schema = tools[name].input_schema
        assert schema["additionalProperties"] is False
        assert schema["type"] == "object"
    assert tools[EVAL_TOOL_STATUS].input_schema["properties"] == {}
    assert tools[EVAL_TOOL_NEXT].input_schema["properties"] == {}
    submit = tools[EVAL_TOOL_SUBMIT].input_schema
    assert set(submit["properties"]) == {"lease_id", "segments"}
    assert set(submit["required"]) == {"lease_id", "segments"}


def test_adapter_and_entrypoint_do_not_import_production_tools() -> None:
    for path in (ADAPTER, ENTRYPOINT):
        source = path.read_text(encoding="utf-8")
        assert "adapters.mcp.tools" not in source
        assert "published_tools" not in source
        tree = ast.parse(source, filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert "my_pa.adapters.mcp.tools" not in imported
        assert "my_pa.adapters.mcp" not in imported
        assert not any(
            name == "my_pa.adapters.mcp" or name.startswith("my_pa.adapters.mcp.")
            for name in imported
        )
        assert "my_pa.application.service" not in imported


def test_importing_the_adapter_does_not_load_production_tools() -> None:
    script = """
import sys
sys.modules.pop("my_pa.adapters.mcp", None)
sys.modules.pop("my_pa.adapters.mcp.tools", None)
sys.modules.pop("my_pa.adapters.mcp.server", None)
sys.modules.pop("my_pa.adapters.mcp.remote", None)
import my_pa.adapters.gsqs_remote_eval_mcp as module
assert "my_pa.adapters.mcp" not in sys.modules
assert "my_pa.adapters.mcp.tools" not in sys.modules
assert "published_tools" not in module.__dict__
"""
    completed = run(  # noqa: S603
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path.cwd()),
        env={**os.environ, "PYTHONPATH": "src"},
    )
    assert completed.returncode == 0, completed.stderr


def test_no_active_session_maps_to_error_code() -> None:
    service, store, _clock, _staging, _disclosure = _harness()
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_STATUS,
        {},
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
    )
    assert result.is_error is True
    assert _error_code(result) == ERROR_NO_ACTIVE_SESSION


def test_status_returns_safe_public_fields_for_ready_session() -> None:
    service, store, clock, _staging, _disclosure = _harness()
    session = service.create_session(_request(clock))
    service.seal_ready(session.session_id)
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_STATUS,
        {},
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
    )
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["state"] == "READY"
    assert payload["session_identity_sha256"] == session.session_identity_sha256
    assert payload["repetitions_required"] == 3
    assert payload["cases_per_repetition"] == 73
    assert "session_id" not in payload
    assert "gold" not in payload
    assert "source_path" not in payload
    assert "staged_filename" not in json.dumps(payload)


def test_next_on_ready_session_is_not_in_progress() -> None:
    service, store, clock, _staging, _disclosure = _harness()
    session = service.create_session(_request(clock))
    service.seal_ready(session.session_id)
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_NEXT,
        {},
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
    )
    assert result.is_error is True
    assert _error_code(result) == ERROR_SESSION_NOT_IN_PROGRESS


def test_next_returns_image_content_png_not_a_url() -> None:
    service, store, disclosure, _session_id, png = _in_progress_with_png()
    gsqs_eval_disclosure_attempt.set(None)
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_NEXT,
        {},
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(png),
    )
    assert result.is_error is False
    assert len(result.content) == 2
    assert isinstance(result.content[0], ImageContent)
    assert result.content[0].type == "image"
    payload = _text_payload(result)
    assert payload["mime_type"] == "image/png"
    assert payload["byte_length"] == len(png)
    assert "lease_id" in payload
    assert "url" not in payload
    assert "path" not in payload
    image = result.content[0]
    assert image.mime_type == "image/png"
    assert not image.data.startswith("http")
    assert not image.data.startswith("data:")
    assert b64decode(image.data) == png
    constructed = png_image_content(png)
    assert constructed.data == image.data
    assert EVENT_OUTBOUND_ATTEMPT_STARTED in disclosure.events
    assert "DISCLOSED_TO_TRANSPORT" not in disclosure.events
    assert gsqs_eval_disclosure_attempt.get() == disclosure.started[-1]


def test_tools_bind_occupying_session_not_parked_repetition_complete() -> None:
    service, store, clock, _staging, _disclosure = _harness()
    parked = service.create_session(_request(clock, session_id="parked"))
    service.seal_ready(parked.session_id)
    service.open_repetition(parked.session_id, 1)
    current = store.load_state(parked.session_id)
    assert current is not None
    store.save_state(replace(current, state=RemoteEvalSessionState.REPETITION_COMPLETE))
    live = service.create_session(_request(clock, session_id="live"))
    service.seal_ready(live.session_id)
    service.open_repetition(live.session_id, 1)
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_STATUS,
        {},
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
    )
    assert result.is_error is False
    payload = _text_payload(result)
    assert payload["state"] == "IN_PROGRESS"
    assert payload["session_identity_sha256"] == live.session_identity_sha256


def test_submit_rejects_extra_properties() -> None:
    service, store, _disclosure, _session_id, png = _in_progress_with_png()
    acquired = service.acquire_case(store.find_non_terminal_session_id() or "")
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_SUBMIT,
        {
            "lease_id": acquired.lease.lease_id,
            "segments": VALID_SEGMENTS,
            "session_id": "forged",
        },
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(png),
    )
    assert result.is_error is True
    assert "session_id" not in result.content[0].text or _error_code(result)


def test_submit_accepts_note_unit_segments_for_current_lease() -> None:
    service, store, _disclosure, _session_id, png = _in_progress_with_png()
    acquired = service.acquire_case(store.find_non_terminal_session_id() or "")
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_SUBMIT,
        {"lease_id": acquired.lease.lease_id, "segments": VALID_SEGMENTS},
        principal=FakePrincipal("principal-1"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(png),
    )
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["ordinal"] == 1
    assert payload["duplicate"] is False
    assert "session_id" not in payload
    assert "gold" not in payload


def test_principal_mismatch_is_forbidden() -> None:
    service, store, clock, _staging, _disclosure = _harness()
    service.create_session(_request(clock))
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_STATUS,
        {},
        principal=FakePrincipal("other-principal"),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
    )
    assert result.is_error is True
    assert _error_code(result) == "FORBIDDEN_SCOPE"


EXPECTED_RESOURCE_METADATA = (
    f"{DEFAULT_EVAL_RESOURCE.removesuffix('/mcp').rstrip('/')}"
    "/.well-known/oauth-protected-resource/mcp"
)


def _mcp_auth_status(authenticator: object, *, authorization: str | None) -> tuple[int, str]:
    service, store, _clock, _staging, _disclosure = _harness()
    app = create_gsqs_remote_eval_app(
        authenticator=authenticator,
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
        allowed_hosts=("testserver",),
        enabled=True,
    )

    async def _exercise() -> tuple[int, str]:
        headers = {} if authorization is None else {"Authorization": authorization}
        async with (
            app.router.lifespan_context(app),
            httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
                headers=headers,
            ) as client,
        ):
            response = await client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            )
        return response.status_code, response.headers.get("www-authenticate", "")

    return asyncio.run(_exercise())


def test_mcp_auth_challenge_is_401_unauthenticated_and_403_forbidden_scope() -> None:
    unauthenticated_status, unauthenticated_challenge = _mcp_auth_status(
        FakeAuthenticator(), authorization=None
    )
    assert unauthenticated_status == 401
    assert EXPECTED_RESOURCE_METADATA in unauthenticated_challenge
    assert "insufficient_scope" not in unauthenticated_challenge

    remote_eval_status, remote_eval_challenge = _mcp_auth_status(
        ForbiddenScopeAuthenticator(), authorization="Bearer synthetic"
    )
    assert remote_eval_status == 403
    assert EXPECTED_RESOURCE_METADATA in remote_eval_challenge
    assert 'error="insufficient_scope"' in remote_eval_challenge

    auth_error_status, auth_error_challenge = _mcp_auth_status(
        ForbiddenScopeAuthErrorAuthenticator(), authorization="Bearer synthetic"
    )
    assert auth_error_status == 403
    assert EXPECTED_RESOURCE_METADATA in auth_error_challenge
    assert 'error="insufficient_scope"' in auth_error_challenge


def test_enabled_false_returns_404_for_mcp() -> None:
    service, store, _clock, _staging, _disclosure = _harness()
    app = create_gsqs_remote_eval_app(
        authenticator=FakeAuthenticator(),
        service=service,
        store=store,
        raster_reader=FakeRasterReader(_png()),
        allowed_hosts=("testserver",),
        enabled=False,
    )

    async def _exercise() -> tuple[int, int, object]:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
            )
            health = await client.get("/healthz")
        return response.status_code, health.status_code, health.json()

    status, health_status, health_body = asyncio.run(_exercise())
    assert status == 404
    assert health_status == 200
    assert health_body == {"status": "ok"}


def test_wrap_eval_asgi_send_is_identity() -> None:
    sent: list[object] = []

    async def send(message: object) -> None:
        sent.append(message)

    wrapped = wrap_eval_asgi_send(send, disclosure_journal=object(), attempt_getter=lambda: None)
    assert wrapped is send


def test_wildcard_origins_are_rejected() -> None:
    service, store, _clock, _staging, _disclosure = _harness()
    try:
        create_gsqs_remote_eval_app(
            authenticator=FakeAuthenticator(),
            service=service,
            store=store,
            raster_reader=FakeRasterReader(_png()),
            allowed_hosts=("testserver",),
            allowed_origins=("*",),
            enabled=True,
        )
    except ValueError as exc:
        assert "wildcard" in str(exc)
    else:
        raise AssertionError("wildcard origins must be refused")
