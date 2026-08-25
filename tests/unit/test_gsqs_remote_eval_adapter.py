"""Unit tests for the isolated GSQS remote-eval MCP transport."""

from __future__ import annotations

import asyncio
import json
from base64 import b64decode
from dataclasses import dataclass
from pathlib import Path

import httpx2

from my_pa.adapters.gsqs_remote_eval_mcp import (
    EVAL_TOOL_NEXT,
    EVAL_TOOL_STATUS,
    EVAL_TOOL_SUBMIT,
    create_gsqs_remote_eval_app,
    gsqs_eval_tools,
    invoke_gsqs_eval_tool,
    png_image_content,
    wrap_eval_asgi_send,
)
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_NO_ACTIVE_SESSION,
    RemoteEvalError,
)

ADAPTER_SOURCE = Path("src/my_pa/adapters/gsqs_remote_eval_mcp.py")
ENTRYPOINT_SOURCE = Path("apps/gsqs_remote_eval.py")
PRODUCTION_TOOL_NAMES = frozenset({"goodnotes.propose", "goodnotes.work", "goodnotes.content"})
ONE_BY_ONE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@dataclass(frozen=True)
class FakePrincipal:
    principal_id: str = "principal-1"


class FakeAuthenticator:
    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        if authorization_header != "Bearer synthetic":
            raise RemoteEvalError("UNAUTHENTICATED", "unauthenticated")
        return FakePrincipal()


class FakeStore:
    def list_session_ids(self) -> tuple[str, ...]:
        return ()

    def find_non_terminal_session_id(self) -> str | None:
        return None

    def load_state(self, session_id: str) -> object | None:
        _ = session_id
        return None

    def load_session(self, session_id: str) -> object | None:
        _ = session_id
        return None


class FakeService:
    def __init__(self) -> None:
        self._store = FakeStore()

    def status(self, session_id: str) -> object:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "no active session")


def test_tool_names_are_exactly_the_three_eval_tools() -> None:
    names = tuple(tool.name for tool in gsqs_eval_tools())
    assert names == (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT, EVAL_TOOL_SUBMIT)


def test_each_input_schema_forbids_additional_properties() -> None:
    for tool in gsqs_eval_tools():
        assert tool.input_schema["additionalProperties"] is False
        assert tool.input_schema["type"] == "object"


def test_status_and_next_schemas_are_empty_and_submit_is_lease_and_segments() -> None:
    by_name = {tool.name: tool for tool in gsqs_eval_tools()}
    for name in (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT):
        schema = by_name[name].input_schema
        assert schema.get("properties", {}) == {}
        assert schema["additionalProperties"] is False
    submit = by_name[EVAL_TOOL_SUBMIT].input_schema
    assert set(submit["properties"]) == {"lease_id", "segments"}
    assert set(submit["required"]) == {"lease_id", "segments"}
    assert submit["additionalProperties"] is False


def test_eval_tools_carry_tool_annotations() -> None:
    by_name = {tool.name: tool for tool in gsqs_eval_tools()}
    for name, tool in by_name.items():
        assert tool.annotations is not None, f"{name} is missing ToolAnnotations"
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False
    assert by_name[EVAL_TOOL_STATUS].annotations.read_only_hint is True
    assert by_name[EVAL_TOOL_NEXT].annotations.read_only_hint is False
    assert by_name[EVAL_TOOL_SUBMIT].annotations.read_only_hint is False


def test_production_goodnotes_tools_are_absent() -> None:
    names = {tool.name for tool in gsqs_eval_tools()}
    assert names.isdisjoint(PRODUCTION_TOOL_NAMES)


def test_adapter_source_does_not_mention_production_tools() -> None:
    source = ADAPTER_SOURCE.read_text(encoding="utf-8")
    assert "adapters.mcp.tools" not in source
    assert "published_tools" not in source
    assert "ApplicationService" not in source
    entry = ENTRYPOINT_SOURCE.read_text(encoding="utf-8")
    assert "adapters.mcp.tools" not in entry
    assert "published_tools" not in entry


def test_image_content_helper_uses_png_bytes_not_a_url() -> None:
    image = png_image_content(ONE_BY_ONE_PNG)
    assert image.type == "image"
    assert image.mime_type == "image/png"
    assert not image.data.startswith(("http://", "https://", "data:", "/", "."))
    assert b64decode(image.data) == ONE_BY_ONE_PNG


def test_no_session_maps_to_no_active_session() -> None:
    result = invoke_gsqs_eval_tool(
        EVAL_TOOL_STATUS,
        {},
        principal=FakePrincipal(),
        service=FakeService(),
        store=FakeStore(),
    )
    assert result.is_error is True
    payload = json.loads(result.content[0].text)
    assert payload["code"] == ERROR_NO_ACTIVE_SESSION
    assert payload["error"]


def test_enabled_false_returns_404_for_mcp() -> None:
    app = create_gsqs_remote_eval_app(
        FakeAuthenticator(),
        FakeService(),
        enabled=False,
        allowed_hosts=("testserver",),
    )

    async def _exercise() -> tuple[int, int, object]:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            refused = await client.post("/mcp")
            health = await client.get("/healthz")
        return refused.status_code, health.status_code, health.json()

    status, health_status, health_body = asyncio.run(_exercise())
    assert status == 404
    assert health_status == 200
    assert health_body == {"status": "ok"}


def test_wrap_eval_asgi_send_is_identity() -> None:
    async def send(message: object) -> None:
        _ = message

    assert wrap_eval_asgi_send(send) is send
