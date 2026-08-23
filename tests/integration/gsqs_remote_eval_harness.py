"""In-process Streamable HTTP harness for GSQS remote-eval MCP.

Drives ``create_gsqs_remote_eval_app`` with ``httpx2.ASGITransport`` the same
way ``tests/contract/test_remote_mcp_transport.py`` drives production MCP.
Evaluation sessions are prepared locally through ``RemoteEvalService``; remote
tools never open repetitions.
"""

from __future__ import annotations

import json
from base64 import b64decode
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, ImageContent
from starlette.applications import Starlette

from my_pa.adapters.gsqs_remote_eval_mcp import (
    DEFAULT_EVAL_RESOURCE,
    EVAL_TOOL_NEXT,
    EVAL_TOOL_STATUS,
    EVAL_TOOL_SUBMIT,
    create_gsqs_remote_eval_app,
)
from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import RemoteEvalError
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import (
    JOURNAL_FILENAME,
    FilesystemDisclosureJournal,
)
from my_pa.application.goodnotes_gsqs_remote_eval_staging import FilesystemRasterStaging
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    FilesystemRemoteEvalStore,
    session_directory,
)
from tests.unit.test_goodnotes_gsqs_remote_eval_orchestration import (
    FakeClock,
    _load_generate,
    _ready_session,
)

SESSION_PRINCIPAL_ID = "principal-1"
BEARER_AUTHORIZATION = "Bearer synthetic"
ALLOWED_HOSTS = ("testserver",)
AUTHORIZATION_SERVERS = ("https://issuer.example.invalid",)
PRODUCTION_TOOL_NAMES = ("goodnotes.propose", "goodnotes.work", "goodnotes.content")
EVAL_TOOL_NAMES = (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT, EVAL_TOOL_SUBMIT)
PNG_MAGIC = b"\x89PNG"


def assert_eval_tool_schemas(tools: Sequence[object]) -> None:
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == set(EVAL_TOOL_NAMES)
    for name in (EVAL_TOOL_STATUS, EVAL_TOOL_NEXT):
        schema = by_name[name].input_schema
        assert schema["additionalProperties"] is False
        assert schema["type"] == "object"
        assert schema.get("properties", {}) == {}
    submit = by_name[EVAL_TOOL_SUBMIT].input_schema
    assert submit["additionalProperties"] is False
    assert submit["type"] == "object"
    assert set(submit["properties"]) == {"lease_id", "segments"}
    assert set(submit["required"]) == {"lease_id", "segments"}


def assert_eval_tool_annotations(tools: Sequence[object]) -> None:
    by_name = {tool.name: tool for tool in tools}
    assert set(by_name) == set(EVAL_TOOL_NAMES)
    for name, tool in by_name.items():
        annotations = getattr(tool, "annotations", None)
        assert annotations is not None, f"{name} is missing ToolAnnotations"
        assert annotations.destructive_hint is False
        assert annotations.open_world_hint is False
    assert by_name[EVAL_TOOL_STATUS].annotations.read_only_hint is True
    assert by_name[EVAL_TOOL_NEXT].annotations.read_only_hint is False
    assert by_name[EVAL_TOOL_SUBMIT].annotations.read_only_hint is False


@dataclass(frozen=True)
class FakePrincipal:
    principal_id: str


class FakeAuthenticator:
    """Header-only fake matching ``GsqsEvalAuthenticator``."""

    def __init__(
        self,
        principal_id: str = SESSION_PRINCIPAL_ID,
        *,
        authorization: str = BEARER_AUTHORIZATION,
    ) -> None:
        self._principal_id = principal_id
        self._authorization = authorization

    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        if authorization_header != self._authorization:
            raise RemoteEvalError("UNAUTHENTICATED", "unauthenticated")
        return FakePrincipal(self._principal_id)


def forbid_external_io(*_args: object, **_kwargs: object) -> object:
    raise AssertionError("external API or model call is forbidden in GSQS remote-eval tests")


def empty_eval_service(tmp_path: Path) -> tuple[RemoteEvalService, FilesystemRemoteEvalStore, Path]:
    state_root = tmp_path / "empty-state"
    source_root = tmp_path / "empty-rasters"
    source_root.mkdir()
    clock = FakeClock(datetime(2026, 8, 23, 12, 0, tzinfo=UTC))
    store = FilesystemRemoteEvalStore(state_root)
    staging = FilesystemRasterStaging(state_root, source_root)
    disclosure = FilesystemDisclosureJournal(state_root, clock=clock)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=staging,
        disclosure=disclosure,
    )
    return service, store, state_root


def in_progress_session(
    tmp_path: Path, *, session_id: str
) -> tuple[RemoteEvalService, FilesystemRemoteEvalStore, Path, str, ModuleType]:
    generate = _load_generate()
    service, store, _clock, state_root, _source_root, bound_id = _ready_session(
        tmp_path, generate, session_id=session_id
    )
    service.open_repetition(bound_id, 1)
    return service, store, state_root, bound_id, generate


def eval_app(
    service: RemoteEvalService,
    *,
    authenticator: FakeAuthenticator | None = None,
    enabled: bool = True,
    principal_id: str = SESSION_PRINCIPAL_ID,
) -> Starlette:
    return create_gsqs_remote_eval_app(
        authenticator or FakeAuthenticator(principal_id),
        service=service,
        enabled=enabled,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=(),
        resource=DEFAULT_EVAL_RESOURCE,
        authorization_servers=AUTHORIZATION_SERVERS,
    )


@asynccontextmanager
async def running_eval_http(
    app: Starlette, *, authorization: str = BEARER_AUTHORIZATION
) -> AsyncIterator[httpx2.AsyncClient]:
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Authorization": authorization},
        ) as http,
    ):
        yield http


@asynccontextmanager
async def connected_eval_session(http: httpx2.AsyncClient) -> AsyncIterator[ClientSession]:
    async with (
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        yield session


def text_payload(result: CallToolResult) -> dict[str, object]:
    assert result.content, "tool result has no content"
    block = result.content[0]
    assert getattr(block, "type", None) == "text"
    loaded = json.loads(block.text)
    assert isinstance(loaded, dict)
    return loaded


def error_code(result: CallToolResult) -> str:
    assert result.is_error is True
    payload = text_payload(result)
    code = payload.get("code") or payload.get("error")
    assert isinstance(code, str) and code
    return code


def image_blocks(result: CallToolResult) -> list[object]:
    return [block for block in result.content if getattr(block, "type", None) == "image"]


def assert_no_image(result: CallToolResult) -> None:
    assert image_blocks(result) == []


def png_image(result: CallToolResult) -> ImageContent:
    images = image_blocks(result)
    assert len(images) == 1
    image = images[0]
    assert isinstance(image, ImageContent)
    assert getattr(image, "type", "image") == "image"
    assert image.mime_type == "image/png"
    assert image.data
    assert not image.data.startswith(("http://", "https://", "data:", "/", "."))
    return image


def png_bytes(result: CallToolResult) -> bytes:
    payload = b64decode(png_image(result).data)
    assert payload.startswith(PNG_MAGIC)
    return payload


def journal_event_types(state_root: Path, session_id: str) -> list[str]:
    path = session_directory(state_root, session_id) / "journal" / JOURNAL_FILENAME
    if not path.is_file():
        return []
    types: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        types.append(str(event["event_type"]))
    return types


def capture_path(
    state_root: Path, session_id: str, repetition: int, ordinal: int, case_id: str
) -> Path:
    return (
        session_directory(state_root, session_id)
        / "captures"
        / f"repetition-{repetition:03d}"
        / f"{ordinal:03d}-{case_id}.json"
    )


async def call_status(session: ClientSession) -> CallToolResult:
    return await session.call_tool(EVAL_TOOL_STATUS, {})


async def call_next(session: ClientSession) -> CallToolResult:
    return await session.call_tool(EVAL_TOOL_NEXT, {})


async def call_submit(
    session: ClientSession, *, lease_id: str, segments: Sequence[object]
) -> CallToolResult:
    return await session.call_tool(
        EVAL_TOOL_SUBMIT,
        {"lease_id": lease_id, "segments": list(segments)},
    )
