"""Isolation of the GSQS ChatLLM remote-eval MCP surface from production MCP.

Synthetic only. No network. No live credentials. Distinctive planted markers
make a leak unmistakable rather than a substring coincidence.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from types import SimpleNamespace
from typing import Any, Final

import pytest
from tests.conftest import _staged_gray_png

from my_pa.adapters.gsqs_remote_eval_mcp import (
    EVAL_TOOL_NEXT,
    EVAL_TOOL_STATUS,
    EVAL_TOOL_SUBMIT,
    create_gsqs_remote_eval_app,
    gsqs_eval_tools,
    invoke_gsqs_eval_tool,
)
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.infrastructure.security.gsqs_remote_eval_authentication import (
    GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
    GSQS_REMOTE_EVAL_SCOPE,
    GsqsRemoteEvalAuthenticationError,
    GsqsRemoteEvalAuthenticator,
)
from my_pa.infrastructure.security.remote_oauth import OriginTokenContext

PUBLIC_EVAL_TOOLS: Final = (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT, EVAL_TOOL_SUBMIT)
STATUS_PUBLIC_KEYS: Final = frozenset(
    {
        "schema_version",
        "state",
        "repetition",
        "repetitions_required",
        "next_case_ordinal",
        "cases_per_repetition",
        "expires_at",
        "session_identity_sha256",
    }
)
NEXT_PUBLIC_KEYS: Final = frozenset(
    {
        "lease_id",
        "ordinal",
        "repetition",
        "content_sha256",
        "mime_type",
        "byte_length",
    }
)
SUBMIT_PUBLIC_KEYS: Final = frozenset(
    {
        "repetition",
        "ordinal",
        "capture_identity_sha256",
        "duplicate",
        "state",
    }
)
PLANTED_GOLD: Final = "PLANTED_GOLD_LABEL_SYNTHETIC"
PLANTED_PRIVATE_LABEL: Final = "PLANTED_PRIVATE_LABEL_SYNTHETIC"
PLANTED_SOURCE_PATH: Final = "/var/db/gsqs/private/gold/source-raster-PLANTED.png"
PLANTED_BEARER: Final = "SYNTHETIC-EVAL-BEARER-TOKEN-9f3c"
PLANTED_CLIENT_SECRET: Final = "SYNTHETIC-CLIENT-SECRET-aa11"  # noqa: S105
PRODUCTION_RESOURCE: Final = "https://my-pa-mcp.bobby-fetting.me/mcp"
PRODUCTION_SCOPE: Final = "my-pa.read"
NAMED_ABSENT_TOOLS: Final = (
    "goodnotes.propose",
    "goodnotes.work",
    "goodnotes.content",
    "goodnotes.eval.abort",
    "goodnotes.eval.export",
    "goodnotes.eval.score",
    "goodnotes.eval.start",
    "goodnotes.eval.prepare",
    "goodnotes.eval.create",
)
PHASE_C_CREATE_TOOLS: Final = (
    "goodnotes.eval.create",
    "goodnotes.eval.start",
    "goodnotes.eval.prepare",
    "goodnotes.eval.begin",
    "session.create",
)
FORBIDDEN_RESULT_MARKERS: Final = (
    PLANTED_GOLD,
    PLANTED_PRIVATE_LABEL,
    PLANTED_SOURCE_PATH,
    "private_label",
    "private_gold",
    "source_path",
    "/var/db/gsqs/",
    "/Users/",
    "file://",
)


@dataclass
class _Principal:
    principal_id: str = "principal-1"


class _Store:
    def list_session_ids(self) -> tuple[str, ...]:
        return ("sess-1",)

    def find_non_terminal_session_id(self) -> str | None:
        return "sess-1"

    def load_state(self, session_id: str) -> object:
        _ = session_id
        return SimpleNamespace(state="IN_PROGRESS")

    def load_session(self, session_id: str) -> object:
        return SimpleNamespace(
            session_id=session_id,
            principal_id="principal-1",
            gold=PLANTED_GOLD,
            private_label=PLANTED_PRIVATE_LABEL,
            source_path=PLANTED_SOURCE_PATH,
        )


class _Service:
    def __init__(self, png: bytes) -> None:
        self._store = _Store()
        self._png = png
        self._digest = sha256(png).hexdigest()

    def status(self, session_id: str) -> object:
        _ = session_id
        return SimpleNamespace(
            state="IN_PROGRESS",
            active_repetition=1,
            repetitions_required=3,
            next_case_ordinal=1,
            case_count=73,
            expires_at=datetime(2026, 8, 23, tzinfo=UTC),
            session_identity_sha256="ab" * 32,
            gold=PLANTED_GOLD,
            private_label=PLANTED_PRIVATE_LABEL,
            source_path=PLANTED_SOURCE_PATH,
        )

    def acquire_case(self, session_id: str) -> object:
        _ = session_id
        return SimpleNamespace(
            lease=SimpleNamespace(lease_id="lease-1"),
            ordinal=1,
            repetition=1,
            content_sha256=self._digest,
            staged_filename=PLANTED_SOURCE_PATH.rsplit("/", maxsplit=1)[-1],
            case_id="syn-b-001",
            byte_length=len(self._png),
            gold=PLANTED_GOLD,
            private_label=PLANTED_PRIVATE_LABEL,
            source_path=PLANTED_SOURCE_PATH,
        )

    def record_outbound_attempt(self, session_id: str, *, repetition: int, case_id: str) -> str:
        _ = (session_id, repetition, case_id)
        return "attempt-1"

    def submit_capture(self, session_id: str, lease_id: str, segments: object) -> object:
        _ = (session_id, lease_id, segments)
        return SimpleNamespace(
            repetition=1,
            ordinal=1,
            capture_identity_sha256="ef" * 32,
            duplicate=False,
            state="IN_PROGRESS",
            gold=PLANTED_GOLD,
            private_label=PLANTED_PRIVATE_LABEL,
            source_path=PLANTED_SOURCE_PATH,
        )


class _RasterReader:
    def __init__(self, png: bytes) -> None:
        self._png = png

    def read_png(
        self,
        *,
        session_id: str,
        staged_filename: str,
        content_sha256: str,
        byte_length: int,
    ) -> bytes:
        _ = (session_id, staged_filename, content_sha256, byte_length)
        return self._png


class _AcceptingAuthenticator:
    def authenticate(self, authorization_header: str | None) -> _Principal:
        _ = authorization_header
        return _Principal()


@contextmanager
def _connections() -> Iterator[object]:
    yield object()


def _png() -> bytes:
    return _staged_gray_png()


def _invoke(name: str, arguments: dict[str, Any] | None = None) -> object:
    png = _png()
    return invoke_gsqs_eval_tool(
        name,
        arguments,
        principal=_Principal(),
        service=_Service(png),
        store=_Store(),
        raster_reader=_RasterReader(png),
    )


def _text_payload(result: object) -> dict[str, object]:
    content = getattr(result, "content", ())
    assert content, "tool result had no content"
    for block in content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    raise AssertionError("tool result had no text content")


def _visible_text(result: object) -> str:
    parts: list[str] = []
    for block in getattr(result, "content", ()):
        text = getattr(block, "text", None)
        if isinstance(text, str):
            parts.append(text)
        mime = getattr(block, "mime_type", None)
        if isinstance(mime, str):
            parts.append(mime)
        kind = getattr(block, "type", None)
        if isinstance(kind, str):
            parts.append(kind)
    return "\n".join(parts)


def _assert_no_sensitive_markers(text: str) -> None:
    lowered = text.lower()
    for marker in FORBIDDEN_RESULT_MARKERS:
        assert marker.lower() not in lowered, f"sensitive marker leaked: {marker}"


def test_public_tools_are_exactly_status_next_submit() -> None:
    names = tuple(tool.name for tool in gsqs_eval_tools())
    assert names == PUBLIC_EVAL_TOOLS
    assert set(names) == {EVAL_TOOL_STATUS, EVAL_TOOL_NEXT, EVAL_TOOL_SUBMIT}


def test_production_and_eval_lifecycle_tools_are_absent() -> None:
    names = {tool.name for tool in gsqs_eval_tools()}
    write_tools = {capability.value for capability in Capability if is_write_capability(capability)}
    absent = (
        set(NAMED_ABSENT_TOOLS)
        | write_tools
        | {
            Capability.GOODNOTES_WORK.value,
            Capability.GOODNOTES_CONTENT.value,
            Capability.GOODNOTES_PROPOSE.value,
        }
    )
    leaked = names & absent
    assert not leaked, f"isolated eval surface published production tools: {sorted(leaked)}"
    for name in sorted(absent):
        result = _invoke(name, {})
        assert getattr(result, "is_error", False) is True
        payload = _text_payload(result)
        assert payload["code"] == "UNSUPPORTED_TOOL"
        _assert_no_sensitive_markers(json.dumps(payload))


def test_status_and_next_and_submit_omit_gold_labels_and_source_paths() -> None:
    status = _invoke(EVAL_TOOL_STATUS, {})
    assert getattr(status, "is_error", True) is False
    status_payload = _text_payload(status)
    assert set(status_payload) == STATUS_PUBLIC_KEYS
    _assert_no_sensitive_markers(_visible_text(status))
    _assert_no_sensitive_markers(json.dumps(status_payload, sort_keys=True))

    nxt = _invoke(EVAL_TOOL_NEXT, {})
    assert getattr(nxt, "is_error", True) is False
    next_payload = _text_payload(nxt)
    assert set(next_payload) == NEXT_PUBLIC_KEYS
    _assert_no_sensitive_markers(_visible_text(nxt))
    _assert_no_sensitive_markers(json.dumps(next_payload, sort_keys=True))
    assert next_payload["mime_type"] == "image/png"
    assert "url" not in next_payload
    assert "path" not in next_payload
    assert "gold" not in next_payload

    submitted = _invoke(
        EVAL_TOOL_SUBMIT,
        {"lease_id": "lease-1", "segments": [{"kind": "SOURCE_CONTEXT"}]},
    )
    assert getattr(submitted, "is_error", True) is False
    submit_payload = _text_payload(submitted)
    assert set(submit_payload) == SUBMIT_PUBLIC_KEYS
    _assert_no_sensitive_markers(_visible_text(submitted))
    _assert_no_sensitive_markers(json.dumps(submit_payload, sort_keys=True))


def test_input_schemas_set_additional_properties_false() -> None:
    tools = {tool.name: tool for tool in gsqs_eval_tools()}
    for name in PUBLIC_EVAL_TOOLS:
        schema = tools[name].input_schema
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
    assert tools[EVAL_TOOL_STATUS].input_schema["properties"] == {}
    assert tools[EVAL_TOOL_NEXT].input_schema["properties"] == {}
    submit = tools[EVAL_TOOL_SUBMIT].input_schema
    assert set(submit["properties"]) == {"lease_id", "segments"}
    assert set(submit["required"]) == {"lease_id", "segments"}


def test_wildcard_origin_and_missing_hosts_are_rejected() -> None:
    with pytest.raises(ValueError, match="wildcard"):
        create_gsqs_remote_eval_app(
            _AcceptingAuthenticator(),
            enabled=False,
            allowed_hosts=("eval.example",),
            allowed_origins=("*",),
        )
    with pytest.raises(ValueError, match="host"):
        create_gsqs_remote_eval_app(
            _AcceptingAuthenticator(),
            enabled=False,
            allowed_hosts=(),
        )


def test_factory_enables_dns_rebinding_protection_with_exact_allowlists() -> None:
    png = _png()
    app = create_gsqs_remote_eval_app(
        _AcceptingAuthenticator(),
        service=_Service(png),
        enabled=True,
        allowed_hosts=("eval.example",),
        allowed_origins=("https://chat.example",),
        store=_Store(),
        raster_reader=_RasterReader(png),
    )
    endpoint = next(
        route.endpoint for route in app.routes if getattr(route, "path", None) == "/mcp"
    )
    settings = endpoint.manager.security_settings
    assert settings.enable_dns_rebinding_protection is True
    assert settings.allowed_hosts == ["eval.example"]
    assert settings.allowed_origins == ["https://chat.example"]
    assert "*" not in settings.allowed_hosts
    assert "*" not in settings.allowed_origins


def test_production_resource_token_does_not_authorize_evaluation() -> None:
    def token_context(token: str) -> OriginTokenContext | None:
        if token == "eval-token":  # noqa: S105
            return OriginTokenContext(
                client_id="eval-client",
                scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
                resource=GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
            )
        if token == "prod-token":  # noqa: S105
            return OriginTokenContext(
                client_id="prod-client",
                scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE, PRODUCTION_SCOPE}),
                resource=PRODUCTION_RESOURCE,
            )
        if token == PLANTED_BEARER:
            return OriginTokenContext(
                client_id="prod-client",
                scopes=frozenset({PRODUCTION_SCOPE}),
                resource=PRODUCTION_RESOURCE,
            )
        return None

    authenticator = GsqsRemoteEvalAuthenticator(
        token_context=token_context,
        connections=_connections,
        required_resource=GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
        required_scope=GSQS_REMOTE_EVAL_SCOPE,
        principal_resolver=lambda _client_id: "principal-1",
    )
    principal = authenticator.authenticate("Bearer eval-token")
    assert principal.principal_id == "principal-1"
    assert principal.resource == GSQS_REMOTE_EVAL_RESOURCE_DEFAULT

    with pytest.raises(GsqsRemoteEvalAuthenticationError) as production:
        authenticator.authenticate("Bearer prod-token")
    assert production.value.code == "UNAUTHENTICATED"
    assert "prod-token" not in str(production.value)
    assert PRODUCTION_RESOURCE not in str(production.value)

    with pytest.raises(GsqsRemoteEvalAuthenticationError) as planted:
        authenticator.authenticate(f"Bearer {PLANTED_BEARER}")
    assert planted.value.code == "UNAUTHENTICATED"
    assert PLANTED_BEARER not in str(planted.value)


def test_logs_around_authenticate_next_and_status_omit_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def token_context(token: str) -> OriginTokenContext | None:
        if token == PLANTED_BEARER:
            return OriginTokenContext(
                client_id="prod-client",
                scopes=frozenset({PRODUCTION_SCOPE}),
                resource=PRODUCTION_RESOURCE,
            )
        if token == "eval-token":  # noqa: S105
            return OriginTokenContext(
                client_id="eval-client",
                scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
                resource=GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
            )
        return None

    authenticator = GsqsRemoteEvalAuthenticator(
        token_context=token_context,
        connections=_connections,
        required_resource=GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
        required_scope=GSQS_REMOTE_EVAL_SCOPE,
        principal_resolver=lambda _client_id: "principal-1",
    )
    png = _png()
    image_b64 = __import__("base64").standard_b64encode(png).decode("ascii")

    with caplog.at_level(logging.DEBUG):
        authenticator.authenticate("Bearer eval-token")
        with pytest.raises(GsqsRemoteEvalAuthenticationError):
            authenticator.authenticate(f"Bearer {PLANTED_BEARER}")
        _invoke(EVAL_TOOL_STATUS, {})
        _invoke(EVAL_TOOL_NEXT, {})

    rendered = caplog.text
    assert PLANTED_BEARER not in rendered
    assert PLANTED_CLIENT_SECRET not in rendered
    assert PLANTED_GOLD not in rendered
    assert PLANTED_SOURCE_PATH not in rendered
    assert image_b64 not in rendered
    assert png.decode("latin-1") not in rendered


def test_phase_c_cannot_be_created_via_remote_tools() -> None:
    names = {tool.name for tool in gsqs_eval_tools()}
    create_like = {
        name for name in names if "create" in name or "start" in name or "prepare" in name
    }
    assert not create_like
    for name in PHASE_C_CREATE_TOOLS:
        assert name not in names
        result = _invoke(name, {"mode": "PHASE_C"})
        assert getattr(result, "is_error", False) is True
        payload = _text_payload(result)
        assert payload["code"] == "UNSUPPORTED_TOOL"
        _assert_no_sensitive_markers(json.dumps(payload))
