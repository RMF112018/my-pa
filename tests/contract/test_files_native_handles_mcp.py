"""Native file handles on the remote MCP surface (files-workspace contract section 17).

The wire half of ADR-019 Amendment 1, over the real `create_remote_mcp_app`
and the official SDK client:

* `files.upload.begin`'s remote schema publishes `source_file` at the top
  level with `_meta["openai/fileParams"] = ["source_file"]` and the four
  OpenAI file-object properties (two required); the canonical schema keeps it
  under `payload`; no other tool declares a file param; the remote boundary
  moves the top-level field back under `payload`;
* a download result's `resource_link` projection;
* `resources/read` streams the source's bytes into the SDK's own JSON-RPC
  answer -- exact `Content-Length`, byte-exact base64, a 50 MiB read within a
  small memory bound -- after the `/mcp` call slot is released, and a refusal
  is a JSON-RPC error carrying only a reason token.

The resource source is a synthetic stand-in; the gate it is composed over in
production is proved in `tests/unit/test_files_download_resources.py` and the
database-tier slice. Every value is synthetic.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import tracemalloc
from collections.abc import Awaitable, Callable
from typing import Any, Final

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from tests.conftest import Scene, build_service

from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.server import _remote_tool, _resource_link_from_result
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    REMOTE_FILE_PARAM_FIELDS,
    compose_remote_arguments,
    remote_tool_schema,
)
from my_pa.adapters.remote_resources import RemoteResourceRefused, RemoteResourceTemplate
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind

URI: Final = "mcp-files://downloads/fwdnl_00000000000000000000000000000001"
PIECE: Final = 3 * 256 * 1024
_PATTERN: Final = bytes(range(256)) * (PIECE // 256 + 1)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _piece(position: int, length: int) -> bytes:
    offset = position % 256
    return _PATTERN[offset : offset + length]


def _expected_sha256(size: int) -> str:
    digest = hashlib.sha256()
    position = 0
    while position < size:
        length = min(PIECE, size - position)
        digest.update(_piece(position, length))
        position += length
    return digest.hexdigest()


class _Stream:
    def __init__(self, size: int, *, fail_after: int | None = None) -> None:
        self.size = size
        self.mime_type = "application/octet-stream"
        self.fail_after = fail_after
        self.closed = 0
        self.gate: asyncio.Event | None = None

    async def stream(self, write: Callable[[bytes], Awaitable[None]]) -> None:
        position = 0
        while position < self.size:
            if self.gate is not None:
                await self.gate.wait()
            length = min(PIECE, self.size - position)
            await write(_piece(position, length))
            position += length
            if self.fail_after is not None and position >= self.fail_after:
                raise RuntimeError("synthetic stream failure")

    async def aclose(self) -> None:
        self.closed += 1


class _Source:
    def __init__(self, stream: _Stream | None = None, refusal: str | None = None) -> None:
        self.stream = stream
        self.refusal = refusal
        self.opened: list[tuple[str, RemoteAccessContext]] = []

    def templates(self) -> list[RemoteResourceTemplate]:
        return [
            RemoteResourceTemplate(
                name="workspace-download",
                uri_template="mcp-files://downloads/{download_id}",
                description="synthetic",
                mime_type="application/octet-stream",
            )
        ]

    async def open(self, uri: str, access: RemoteAccessContext) -> _Stream:
        self.opened.append((uri, access))
        if self.refusal is not None or self.stream is None:
            raise RemoteResourceRefused(self.refusal or "ticket_invalid")
        return self.stream


def _app(scene: Scene, source: _Source | None, **options: Any) -> Any:  # noqa: ANN401
    service = build_service(scene.world, scene.providers)
    return create_remote_mcp_app(
        service,
        resolve_access=lambda authorization: (
            RemoteAccessContext(scene.principal, authenticated_client_id="synthetic-client")
            if authorization == "Bearer synthetic"
            else None
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        resource="http://testserver",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
        resources=source,
        **options,
    )


async def _session_run(
    app: Any,  # noqa: ANN401
    body: Callable[[ClientSession], Awaitable[Any]],
) -> Any:  # noqa: ANN401
    transport = httpx2.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer synthetic"},
        ) as http,
        streamable_http_client("http://testserver/mcp", http_client=http) as streams,
        ClientSession(*streams[:2]) as session,
    ):
        await session.initialize()
        return await body(session)


# ---- the upload tool's schema and the boundary's lift --------------------------------------


def _tool(name: str) -> Any:  # noqa: ANN401
    return next(tool for tool in TOOLS if tool.name == name)


def test_the_remote_upload_begin_declares_one_top_level_openai_file_param() -> None:
    remote = _remote_tool(
        _tool(Capability.FILES_UPLOAD_BEGIN.value), oauth_scopes=frozenset({"my-pa.write"})
    )
    assert remote.meta is not None
    assert remote.meta["openai/fileParams"] == ["source_file"]
    schema = remote.input_schema
    source = schema["properties"]["source_file"]
    assert source["type"] == "object"
    assert set(source["properties"]) == {"download_url", "file_id", "file_name", "mime_type"}
    assert source["required"] == ["download_url", "file_id"]
    assert "source_file" not in schema["required"]
    assert "source_file" not in schema["properties"]["payload"]["properties"]
    assert "source_file" not in schema["properties"]["payload"]["required"]
    # Everything else on the payload is as it was.
    assert {"path", "expected_version", "size", "sha256", "ttl_seconds"} <= set(
        schema["properties"]["payload"]["properties"]
    )


def test_the_canonical_schema_keeps_the_handle_under_payload_and_declares_nothing() -> None:
    canonical = _tool(Capability.FILES_UPLOAD_BEGIN.value)
    assert "source_file" in canonical.input_schema["properties"]["payload"]["properties"]
    assert "source_file" not in canonical.input_schema["properties"]
    assert not (canonical.meta or {}).get("openai/fileParams")


def test_no_other_tool_declares_a_file_param() -> None:
    declaring = [
        tool.name
        for tool in TOOLS
        if (_remote_tool(tool, oauth_scopes=frozenset()).meta or {}).get("openai/fileParams")
    ]
    assert declaring == [Capability.FILES_UPLOAD_BEGIN.value]
    for tool in TOOLS:
        if tool.name == Capability.FILES_UPLOAD_BEGIN.value:
            continue
        schema = remote_tool_schema(tool.input_schema)
        assert REMOTE_FILE_PARAM_FIELDS.isdisjoint(schema["properties"]), tool.name


def _principal() -> Principal:
    return Principal(
        principal_id="prn_" + "1" * 32, kind=PrincipalKind.OPERATOR, authenticated=True
    )


def test_the_boundary_lifts_a_top_level_handle_under_payload() -> None:
    handle = {"download_url": "https://a.blob.core.windows.net/c/x?sig=s", "file_id": "f"}
    composed = compose_remote_arguments(
        capability_name=Capability.FILES_UPLOAD_BEGIN.value,
        arguments={"payload": {"workspace_id": "mcp", "path": "a.bin"}, "source_file": handle},
        principal=_principal(),
        grants=None,
    )
    assert "source_file" not in composed
    assert composed["payload"]["source_file"] == handle
    assert composed["payload"]["path"] == "a.bin"
    assert composed["payload"]["idempotency_key"].startswith("idk_")
    absent = compose_remote_arguments(
        capability_name=Capability.FILES_UPLOAD_BEGIN.value,
        arguments={"payload": {"workspace_id": "mcp", "path": "a.bin"}, "source_file": None},
        principal=_principal(),
        grants=None,
    )
    assert absent["payload"]["source_file"] is None


@pytest.mark.parametrize(
    "arguments",
    [
        {"payload": {"workspace_id": "mcp", "path": "a", "source_file": {}}, "source_file": {}},
        {"payload": "not an object", "source_file": {}},
    ],
)
def test_a_handle_in_both_places_or_beside_a_bad_payload_is_refused(
    arguments: dict[str, object],
) -> None:
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=Capability.FILES_UPLOAD_BEGIN.value,
            arguments=arguments,
            principal=_principal(),
            grants=None,
        )


# ---- the download result's resource link ---------------------------------------------------


def test_a_download_result_projects_one_resource_link() -> None:
    link = _resource_link_from_result(
        {
            "download_id": "fwdnl_x",
            "download_token": "gfwtk_" + "0" * 64,
            "route": "/files/v1/downloads/fwdnl_x",
            "resource_uri": URI,
            "name": "report.pdf",
            "size": 12,
            "version": "fv1_" + "0" * 64,
        }
    )
    assert link is not None
    assert (link.uri, link.name, link.mime_type, link.size) == (
        URI,
        "report.pdf",
        "application/octet-stream",
        12,
    )
    assert "gfwtk_" not in link.model_dump_json()


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        {"resource_uri": "https://example.invalid/x", "name": "a", "size": 1},
        {"resource_uri": URI, "name": "", "size": 1},
        {"resource_uri": URI, "name": "a", "size": True},
        {"resource_uri": URI, "size": 1},
        {"name": "a", "size": 1},
    ],
)
def test_other_results_project_no_link(result: object) -> None:
    assert _resource_link_from_result(result) is None


# ---- resources over the wire -------------------------------------------------------------


@pytest.mark.anyio
async def test_resources_are_advertised_listed_empty_and_templated(scene: Scene) -> None:
    app = _app(scene, _Source(_Stream(1)))

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        return await session.list_resources(), await session.list_resource_templates()

    listed, templates = await _session_run(app, body)
    assert listed.resources == []
    assert [template.uri_template for template in templates.resource_templates] == [
        "mcp-files://downloads/{download_id}"
    ]


@pytest.mark.anyio
async def test_without_a_source_no_resource_is_served(scene: Scene) -> None:
    app = _app(scene, None)

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        with pytest.raises(MCPError):
            await session.read_resource(URI)
        return True

    assert await _session_run(app, body)


@pytest.mark.anyio
async def test_a_read_streams_the_exact_bytes_as_one_blob(scene: Scene) -> None:
    stream = _Stream(5 * 1024 * 1024 + 7)
    source = _Source(stream)
    app = _app(scene, source)

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        return await session.read_resource(URI)

    read = await _session_run(app, body)
    (content,) = read.contents
    assert str(content.uri) == URI and content.mime_type == "application/octet-stream"
    data = base64.b64decode(content.blob)
    assert len(data) == stream.size
    assert hashlib.sha256(data).hexdigest() == _expected_sha256(stream.size)
    assert stream.closed == 1
    ((uri, access),) = source.opened
    assert uri == URI and access.principal == scene.principal
    assert access.authenticated_client_id == "synthetic-client"


@pytest.mark.anyio
async def test_a_refusal_is_a_json_rpc_error_naming_only_its_token(scene: Scene) -> None:
    app = _app(scene, _Source(refusal="ticket_invalid"))

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        with pytest.raises(MCPError) as caught:
            await session.read_resource(URI)
        return caught.value

    error = await _session_run(app, body)
    assert error.error.message == "ticket_invalid"
    assert URI not in json.dumps(error.error.model_dump(mode="json"))


# ---- the raw ASGI stream: length, memory, failure, and the released slot ------------------


def _scope() -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 1),
        "headers": [
            (b"host", b"testserver"),
            (b"authorization", b"Bearer synthetic"),
            (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
            (b"mcp-protocol-version", b"2025-06-18"),
        ],
    }


class _Collector:
    """Receives a response without keeping it: a streaming base64 decode and hash."""

    def __init__(self) -> None:
        self.status: int | None = None
        self.headers: dict[bytes, bytes] = {}
        self.received = 0
        self.largest = 0
        self.head = bytearray()
        self.tail = b""
        self._pending = b""
        self._in_blob = False
        self.digest = hashlib.sha256()
        self.decoded = 0
        self.finished = False

    async def __call__(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = dict(message.get("headers", []))
            return
        chunk: bytes = message.get("body", b"")
        self.received += len(chunk)
        self.largest = max(self.largest, len(chunk))
        if not self._in_blob:
            self.head.extend(chunk)
            marker = self.head.find(b'"blob":"')
            if marker >= 0:
                self._in_blob = True
                chunk = bytes(self.head[marker + 8 :])
                del self.head[marker + 8 :]
            else:
                chunk = b""
        if self._in_blob and chunk:
            end = chunk.find(b'"')
            if end >= 0:
                self.tail = chunk[end:]
                chunk = chunk[:end]
                self._in_blob = False
            data = self._pending + chunk
            usable = len(data) - len(data) % 4
            decoded = base64.b64decode(data[:usable])
            self.digest.update(decoded)
            self.decoded += len(decoded)
            self._pending = data[usable:]
        if not message.get("more_body", False):
            self.finished = True


def _receive(document: dict[str, Any]) -> Callable[[], Awaitable[dict[str, Any]]]:
    body = json.dumps(document).encode()
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    return receive


_READ: Final = {"jsonrpc": "2.0", "id": 7, "method": "resources/read", "params": {"uri": URI}}


@pytest.mark.anyio
async def test_a_fifty_mib_read_streams_in_bounded_memory_with_an_exact_length(
    scene: Scene,
) -> None:
    stream = _Stream(50 * 1024 * 1024)
    app = _app(scene, _Source(stream))
    collector = _Collector()
    async with app.router.lifespan_context(app):
        tracemalloc.start()
        try:
            await app(_scope(), _receive(_READ), collector)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    assert collector.status == 200 and collector.finished
    assert int(collector.headers[b"content-length"]) == collector.received
    assert collector.decoded == stream.size
    assert collector.digest.hexdigest() == _expected_sha256(stream.size)
    assert stream.closed == 1
    # 50 MiB of file (67 MiB of base64) left through pieces of about 1 MiB.
    assert collector.largest <= 2 * 1024 * 1024
    assert peak < 24 * 1024 * 1024, f"peak traced memory {peak} bytes"


@pytest.mark.anyio
async def test_a_stream_failure_stops_short_of_its_length_and_closes_once(scene: Scene) -> None:
    stream = _Stream(4 * PIECE, fail_after=2 * PIECE)
    app = _app(scene, _Source(stream))
    collector = _Collector()
    async with app.router.lifespan_context(app):
        await app(_scope(), _receive(_READ), collector)
    assert collector.status == 200
    assert collector.received < int(collector.headers[b"content-length"])
    assert not collector.finished
    assert stream.closed == 1


@pytest.mark.anyio
async def test_a_stream_holds_no_mcp_call_slot(scene: Scene) -> None:
    stream = _Stream(2 * PIECE)
    stream.gate = asyncio.Event()
    app = _app(scene, _Source(stream), max_concurrent_calls=1, call_timeout_seconds=2.0)
    reader = _Collector()
    lister = _Collector()
    listing = {"jsonrpc": "2.0", "id": 8, "method": "tools/list", "params": {}}
    async with app.router.lifespan_context(app):
        reading = asyncio.create_task(app(_scope(), _receive(_READ), reader))
        while reader.status is None:
            await asyncio.sleep(0.01)
        # The read has answered its headers and waits mid-stream; the one call
        # slot is free, and the stream outlives the 2 s call timeout.
        await asyncio.wait_for(app(_scope(), _receive(listing), lister), timeout=5)
        await asyncio.sleep(2.5)
        stream.gate.set()
        await asyncio.wait_for(reading, timeout=5)
    assert lister.status == 200 and lister.finished
    assert reader.finished and reader.decoded == stream.size
    assert stream.closed == 1


# ---- the compact client's four top-level file tools (section 17.4) -------------------------


def test_exactly_four_primary_file_names_are_offered_top_level() -> None:
    from my_pa.domain.identity.chatllm_capability_policy import COMPACT_TOP_LEVEL_TOOL_NAMES

    assert {
        "files.upload.begin",
        "files.download.begin",
        "files.list",
        "files.search",
    } == COMPACT_TOP_LEVEL_TOOL_NAMES
    assert {tool.name for tool in TOOLS} >= COMPACT_TOP_LEVEL_TOOL_NAMES


def test_a_compact_call_to_a_canonical_name_outside_its_set_never_reaches_invoke(
    scene: Scene,
) -> None:
    from my_pa.adapters.mcp.server import _answer
    from my_pa.domain.capture.submission import CaptureTransport

    service = build_service(scene.world, scene.providers)
    text, failed, extra = _answer(
        service,
        scene.principal,
        Capability.FILES_MKDIR.value,
        {"payload": {"workspace_id": "mcp", "path": "x"}},
        CaptureTransport.REMOTE_CLIENT,
        None,
        canonical_targets=frozenset({Capability.FILES_LIST.value}),
        authenticated_client_id="synthetic-client",
    )
    assert failed is True and extra is None
    assert json.loads(text)["code"] == "unsupported"


@pytest.mark.anyio
async def test_without_the_files_plane_a_compact_client_lists_only_facade_tools(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    app = create_remote_mcp_app(
        service,
        resolve_access=lambda authorization: (
            RemoteAccessContext(
                scene.principal, compact_publication=True, authenticated_client_id="c"
            )
            if authorization == "Bearer synthetic"
            else None
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=True,
        resource="http://testserver",
        authorization_servers=("https://issuer.example.invalid",),
        scopes=frozenset({"my-pa.read"}),
    )

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        return await session.list_tools()

    listed = await _session_run(app, body)
    names = {tool.name for tool in listed.tools}
    assert names <= {"my_pa.describe", "my_pa.read", "my_pa.write", "my_pa.operator"}
    write = next(tool for tool in listed.tools if tool.name == "my_pa.write")
    assert "source_file" not in write.input_schema["properties"]
    assert write.meta == {"securitySchemes": [{"type": "oauth2", "scopes": ["my-pa.read"]}]}


# ---- the quoted-capability hint (section 17.4) ---------------------------------------------

from my_pa.adapters.mcp.chatllm_gateway import (  # noqa: E402
    DESCRIBE_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    prepare_compact_call,
    render_describe,
)
from my_pa.application.errors import SafeDetail, UnsupportedError  # noqa: E402

_ELIGIBLE: Final = frozenset({"files.write_text", "files.stat"})
_ARGS: Final = {"payload": {"workspace_id": "mcp", "path": "a.txt", "text": "x"}}


@pytest.mark.parametrize(
    "quoted",
    [
        '"files.write_text"',
        "'files.write_text'",
        "`files.write_text`",
        "\u201cfiles.write_text\u201d",
        "\u2018files.write_text\u2019",
        '  "files.write_text"  ',
        " files.write_text\t",
        '" files.write_text "',
    ],
)
def test_a_quoted_eligible_name_is_refused_with_the_closed_hint(quoted: str) -> None:
    with pytest.raises(UnsupportedError) as caught:
        prepare_compact_call(
            WRITE_TOOL, {"capability": quoted, "arguments": _ARGS}, allowed_canonical=_ELIGIBLE
        )
    assert caught.value.safe_details == (SafeDetail.CAPABILITY_NAME_HAS_QUOTES,)


@pytest.mark.parametrize(
    ("tool", "name", "allowed"),
    [
        (READ_TOOL, '"files.write_text"', _ELIGIBLE),  # a write name through my_pa.read
        (WRITE_TOOL, '"files.stat"', _ELIGIBLE),  # a read name through my_pa.write
        (WRITE_TOOL, '"files.write_text"', frozenset({"files.stat"})),  # not eligible
        (WRITE_TOOL, '"files.nope"', _ELIGIBLE),  # unknown
        (WRITE_TOOL, '""files.write_text""', _ELIGIBLE),  # two pairs: one only
        (WRITE_TOOL, "\"files.write_text'", _ELIGIBLE),  # mismatched pair
        (WRITE_TOOL, "files_write_text", _ELIGIBLE),  # no fuzzy matching
        (WRITE_TOOL, "FILES.WRITE_TEXT", _ELIGIBLE),
        (WRITE_TOOL, '""', _ELIGIBLE),
    ],
)
def test_no_hint_unless_the_unquoted_name_is_eligible_through_this_tool(
    tool: str, name: str, allowed: frozenset[str]
) -> None:
    with pytest.raises(UnsupportedError) as caught:
        prepare_compact_call(
            tool, {"capability": name, "arguments": _ARGS}, allowed_canonical=allowed
        )
    assert caught.value.safe_details == ()


def test_describe_hints_a_quoted_eligible_name_only() -> None:
    with pytest.raises(UnsupportedError) as hinted:
        render_describe({"capability": "`files.stat`"}, allowed_canonical=_ELIGIBLE)
    assert hinted.value.safe_details == (SafeDetail.CAPABILITY_NAME_HAS_QUOTES,)
    with pytest.raises(UnsupportedError) as bare:
        render_describe({"capability": "`files.mkdir`"}, allowed_canonical=_ELIGIBLE)
    assert bare.value.safe_details == ()
    assert DESCRIBE_TOOL == "my_pa.describe"


def test_a_quoted_call_is_never_executed_and_answers_one_problem(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    from my_pa.adapters.mcp.server import _answer
    from my_pa.domain.capture.submission import CaptureTransport

    service = build_service(scene.world, scene.providers)

    def never(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("invoke reached")

    monkeypatch.setattr(service, "invoke", never)
    hinted_text, failed, extra = _answer(
        service,
        scene.principal,
        WRITE_TOOL,
        {"capability": '"files.write_text"', "arguments": _ARGS},
        CaptureTransport.REMOTE_CLIENT,
        None,
        canonical_targets=_ELIGIBLE,
        authenticated_client_id="synthetic-client",
    )
    bare_text, _failed, _extra = _answer(
        service,
        scene.principal,
        WRITE_TOOL,
        {"capability": '"files.mkdir"', "arguments": _ARGS},
        CaptureTransport.REMOTE_CLIENT,
        None,
        canonical_targets=_ELIGIBLE,
        authenticated_client_id="synthetic-client",
    )
    assert failed is True and extra is None
    hinted, bare = json.loads(hinted_text), json.loads(bare_text)
    assert hinted["code"] == bare["code"] == "unsupported"
    assert hinted["safe_details"] == ["capability_name_has_quotes"]
    assert "safe_details" not in bare or bare["safe_details"] == []
    assert "files.write_text" not in hinted_text
    assert "allowed_values" not in hinted
