"""Native file handles, end to end over PostgreSQL (files-workspace contract section 17).

The `database` tier, over the WP6a harness (`tests/contract/
test_files_transfer_routes.py`): a registered remote client holding every
`files.*` grant, the real `create_remote_mcp_app` with the production resource
source (`WorkspaceDownloadResources` over the durable `FileTransferGate`), the
official SDK client, and the real `SafeHandleFetcher` aimed at a fake blob
server on loopback through an injected resolver (a public-looking address)
and connector. It proves, for the ChatGPT-shaped path:

* AT1/AT11: a tool call carrying a top-level `source_file` stores the bytes
  byte-exact, the call is one `authorize` row, and the bearer URL is in no
  audit row, transfer row, receipt, answer or log;
* AT6: `files.download.begin` answers a `resource_link`, and `resources/read`
  of it returns the file byte-exact as one blob -- unaudited, like a
  byte-route GET -- while another OAuth client is refused `ticket_invalid`;
* AT9: with remote writes disabled for the client the handle is never
  fetched;
* AT10: the ticket routes still serve the same download for a sandbox-HTTP
  client.

Every URL, byte and id is synthetic; nothing leaves loopback.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import logging
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from sqlalchemy import text, update

from my_pa.adapters.http.files_resources import WorkspaceDownloadResources
from my_pa.adapters.mcp.remote import RemoteAccessContext, create_remote_mcp_app
from my_pa.application.file_transfer import FileTransferGate
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.infrastructure.file_workspace.handle_fetch import HandleFetchPolicy, SafeHandleFetcher
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.remote_identity import remote_security_controls
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.security.remote_oauth import DurableRemoteClientStanding
from tests.contract.test_files_transfer_routes import (
    GRANTS,
    LIMITS,
    OAUTH_CLIENT,
    PRINCIPAL,
    RESOURCE,
    SCOPE,
    WHEN,
    WORKSPACE,
    Harness,
)

pytestmark = pytest.mark.database

SECRET: Final = "SYNTHETICSLICESIGNATURE987654"  # noqa: S105 - a synthetic marker
HOST: Final = "acct1synthetic.blob.core.windows.net"
BODY: Final = bytes((index * 13 + 5) % 251 for index in range(3 * 1024 * 1024 + 11))


def _url(name: str) -> str:
    return f"https://{HOST}/c/{name}?sv=2026-01-01&sig={SECRET}"


class _Blobs(ThreadingHTTPServer):
    requests: list[str]


def _blob_server() -> _Blobs:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

        def do_GET(self) -> None:
            self.server.requests.append(self.path.split("?", 1)[0])  # type: ignore[attr-defined]
            self.send_response(200)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)

    server = _Blobs(("127.0.0.1", 0), Handler)
    server.requests = []
    return server


class _Slice:
    """The WP6a harness's database and client, recomposed with a fetcher and resources."""

    def __init__(self, harness: Harness, blobs: _Blobs) -> None:
        self.h = harness
        self.blobs = blobs
        port = blobs.server_address[1]
        audit = SqlAlchemyAuditSink(harness.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(harness.engine, audit=audit)

        fetcher = SafeHandleFetcher(
            HandleFetchPolicy(deadline_seconds=10),
            resolver=lambda _host, _port: ["52.239.0.20"],
            connector=lambda _host, _ip, _port, timeout: http.client.HTTPConnection(
                "127.0.0.1", port, timeout=timeout
            ),
        )
        store = FilesystemFileWorkspaceStore(harness.root, disk_reserve_bytes=0)
        files = FileWorkspaceApplication(
            store, workspace_id=WORKSPACE, max_upload_bytes=8 << 20, handle_fetcher=fetcher
        )
        self.service = ApplicationService(
            unit_of_work=unit_of_work, limits=LIMITS, file_workspace=files
        )
        self.gate = FileTransferGate(
            service=self.service,
            store=store,
            unit_of_work=unit_of_work,
            standing=DurableRemoteClientStanding(
                connections=harness.engine.begin, resource=RESOURCE, scopes=frozenset({SCOPE})
            ),
            workspace_id=WORKSPACE,
            max_upload_bytes=8 << 20,
            remote_writes_enabled=True,
        )
        self.client_id = OAUTH_CLIENT

    def app(
        self,
        *,
        compact: bool = False,
        grants: frozenset[tuple[Capability, Any]] = GRANTS,
        writes: bool = True,
    ) -> Any:  # noqa: ANN401
        principal = Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        )

        def resolve(authorization: str | None) -> RemoteAccessContext | None:
            if authorization != "Bearer synthetic":
                return None
            return RemoteAccessContext(
                principal,
                allowed_capabilities=frozenset(capability.value for capability, _ in grants),
                capability_purposes=grants,
                authenticated_client_id=self.client_id,
                compact_publication=compact,
            )

        return create_remote_mcp_app(
            self.service,
            resolve_access=resolve,
            allowed_hosts=("testserver",),
            remote_enabled=True,
            writes_enabled=writes,
            resource=RESOURCE,
            authorization_servers=("https://issuer.invalid",),
            scopes=frozenset({SCOPE}),
            resources=WorkspaceDownloadResources(self.gate),
        )

    def rows_text(self) -> str:
        """Every row the plane and the audit wrote, as text."""
        tables = (
            "knowledge.audit_events",
            "knowledge.file_workspace_transfers",
            "knowledge.file_workspace_receipts",
            "knowledge.file_workspace_versions",
        )
        rendered: list[str] = []
        with self.h.engine.begin() as connection:
            for table in tables:
                schema, name = table.split(".")
                exists = connection.execute(
                    text(
                        "SELECT 1 FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_name = :name"
                    ),
                    {"schema": schema, "name": name},
                ).first()
                if exists is None:
                    continue
                for row in connection.execute(text(f"SELECT * FROM {table}")):  # noqa: S608
                    rendered.append(repr(tuple(row)))
        return "\n".join(rendered)

    def audits(self) -> list[tuple[str, str]]:
        with self.h.engine.begin() as connection:
            return [
                (str(row[0]), str(row[1]))
                for row in connection.execute(
                    text("SELECT capability, outcome FROM knowledge.audit_events ORDER BY 1")
                )
                if str(row[0]).startswith("files.")
            ]


@pytest.fixture
def world(cloned_database_url: str, tmp_path: Path) -> Iterator[_Slice]:
    root = tmp_path / "workspace"
    root.mkdir()
    blobs = _blob_server()
    thread = threading.Thread(target=blobs.serve_forever, daemon=True)
    thread.start()
    harness = Harness(cloned_database_url, root)
    try:
        yield _Slice(harness, blobs)
    finally:
        harness.close()
        blobs.shutdown()
        blobs.server_close()
        thread.join(5)


async def _session(app: Any, body: Any) -> Any:  # noqa: ANN401
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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _envelope(result: Any) -> dict[str, Any]:  # noqa: ANN401
    assert result.is_error is False, result.content[0].text
    document = json.loads(result.content[0].text)
    assert document["error"] is None
    return dict(document["result"])


@pytest.mark.anyio
async def test_a_chatgpt_shaped_handle_goes_in_and_comes_back_as_a_resource(
    world: _Slice, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    app = world.app()

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        listed = await session.list_tools()
        upload_tool = next(
            tool for tool in listed.tools if tool.name == Capability.FILES_UPLOAD_BEGIN.value
        )
        assert upload_tool.meta is not None
        assert upload_tool.meta["openai/fileParams"] == ["source_file"]
        stored = await session.call_tool(
            Capability.FILES_UPLOAD_BEGIN.value,
            {
                "payload": {"workspace_id": WORKSPACE, "path": "from-chat.bin"},
                "source_file": {
                    "download_url": _url("from-chat.bin"),
                    "file_id": "file-synthetic-slice",
                    "file_name": "from-chat.bin",
                    "mime_type": "application/macbinary",
                },
            },
        )
        begun = await session.call_tool(
            Capability.FILES_DOWNLOAD_BEGIN.value,
            {
                "payload": {
                    "workspace_id": WORKSPACE,
                    "path": "from-chat.bin",
                    "include_sha256": True,
                }
            },
        )
        links = [block for block in begun.content if block.type == "resource_link"]
        assert len(links) == 1
        read = await session.read_resource(str(links[0].uri))
        return stored, begun, links[0], read

    stored, begun, link, read = await _session(app, body)
    ingested = _envelope(stored)
    assert ingested["sha256"] == hashlib.sha256(BODY).hexdigest()
    assert ingested["size"] == len(BODY) and ingested["replayed"] is False
    assert (world.h.root / "from-chat.bin").read_bytes() == BODY
    download = _envelope(begun)
    assert str(link.uri) == download["resource_uri"]
    assert link.name == "from-chat.bin" and link.size == len(BODY)
    (content,) = read.contents
    assert base64.b64decode(content.blob) == BODY
    assert world.blobs.requests == ["/c/from-chat.bin"]
    # One authorize row per tool call; the resource read is not audited.
    assert world.audits() == [
        ("files.download.begin", "allowed"),
        ("files.upload.begin", "allowed"),
    ]
    rows = world.rows_text()
    # Every server-side record, at DEBUG: the test's own SDK client logs what it
    # sends, which is the caller's side of the wire, not this server's.
    served = "\n".join(
        record.getMessage() for record in caplog.records if not record.name.startswith("mcp.client")
    )
    assert any(record.name.startswith("mcp.server") for record in caplog.records)
    for leaked in (SECRET, HOST, "file-synthetic-slice"):
        assert leaked not in rows, leaked
        assert leaked not in served, leaked
        assert leaked not in json.dumps([block.model_dump(mode="json") for block in stored.content])

    # AT10: the same ticket still serves a sandbox-HTTP client over the byte route.
    answer = world.h.client.get(
        download["route"], {"Authorization": f"Bearer {download['download_token']}"}
    )
    assert answer.status_code == 200 and answer.content == BODY


@pytest.mark.anyio
async def test_another_client_cannot_read_the_resource(world: _Slice) -> None:
    (world.h.root / "a.bin").write_bytes(b"synthetic a")
    app = world.app()

    async def begin(session: ClientSession) -> Any:  # noqa: ANN401
        return await session.call_tool(
            Capability.FILES_DOWNLOAD_BEGIN.value,
            {"payload": {"workspace_id": WORKSPACE, "path": "a.bin"}},
        )

    download = _envelope(await _session(app, begin))
    world.client_id = "someone-else-synthetic"

    async def read(session: ClientSession) -> Any:  # noqa: ANN401
        with pytest.raises(MCPError) as caught:
            await session.read_resource(download["resource_uri"])
        return caught.value

    error = await _session(world.app(), read)
    assert error.error.message == "ticket_invalid"


@pytest.mark.anyio
async def test_with_writes_disabled_for_the_client_no_handle_is_fetched(world: _Slice) -> None:
    with world.h.engine.begin() as connection:
        connection.execute(
            update(remote_security_controls).values(writes_enabled=False, updated_at=WHEN)
        )
    app = create_remote_mcp_app(
        world.service,
        resolve_access=lambda _header: RemoteAccessContext(
            Principal(principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True),
            capability_purposes=GRANTS,
            authenticated_client_id=OAUTH_CLIENT,
        ),
        allowed_hosts=("testserver",),
        remote_enabled=True,
        writes_enabled=False,
        resource=RESOURCE,
        authorization_servers=("https://issuer.invalid",),
        scopes=frozenset({SCOPE}),
    )

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        listed = await session.list_tools()
        names = {tool.name for tool in listed.tools}
        called = await session.call_tool(
            Capability.FILES_UPLOAD_BEGIN.value,
            {
                "payload": {"workspace_id": WORKSPACE, "path": "x.bin"},
                "source_file": {"download_url": _url("x.bin"), "file_id": "f"},
            },
        )
        return names, called

    names, called = await _session(app, body)
    assert Capability.FILES_UPLOAD_BEGIN.value not in names
    assert called.is_error is True
    assert world.blobs.requests == [] and not (world.h.root / "x.bin").exists()


_FACADE: Final = frozenset({"my_pa.describe", "my_pa.read", "my_pa.write"})
_PRIMARY: Final = frozenset(
    {"files.upload.begin", "files.download.begin", "files.list", "files.search"}
)


@pytest.mark.anyio
async def test_a_compact_client_gets_exactly_four_top_level_file_tools(world: _Slice) -> None:
    app = world.app(compact=True)

    async def body(session: ClientSession) -> Any:  # noqa: ANN401
        listed = await session.list_tools()
        upload = next(tool for tool in listed.tools if tool.name == "files.upload.begin")
        assert upload.meta is not None and upload.meta["openai/fileParams"] == ["source_file"]
        for tool in listed.tools:
            if tool.name != "files.upload.begin":
                assert "openai/fileParams" not in (tool.meta or {}), tool.name
        stored = await session.call_tool(
            "files.upload.begin",
            {
                "payload": {"workspace_id": WORKSPACE, "path": "top-level.bin"},
                "source_file": {"download_url": _url("top-level.bin"), "file_id": "fid-top"},
            },
        )
        begun = await session.call_tool(
            "files.download.begin",
            {"payload": {"workspace_id": WORKSPACE, "path": "top-level.bin"}},
        )
        links = [block for block in begun.content if block.type == "resource_link"]
        assert len(links) == 1
        read = await session.read_resource(str(links[0].uri))
        listing = await session.call_tool(
            "files.list", {"payload": {"workspace_id": WORKSPACE, "path": ""}}
        )
        found = await session.call_tool(
            "files.search",
            {"payload": {"workspace_id": WORKSPACE, "path": "", "query": "top-level"}},
        )
        # The façade still reaches the same names, and every other of the 17.
        via_read = await session.call_tool(
            "my_pa.read",
            {
                "capability": "files.download.begin",
                "arguments": {"payload": {"workspace_id": WORKSPACE, "path": "top-level.bin"}},
            },
        )
        via_write = await session.call_tool(
            "my_pa.write",
            {
                "capability": "files.mkdir",
                "arguments": {"payload": {"workspace_id": WORKSPACE, "path": "made"}},
            },
        )
        described = await session.call_tool("my_pa.describe", {"feature": "files", "limit": 100})
        refused = await session.call_tool(
            "files.mkdir", {"payload": {"workspace_id": WORKSPACE, "path": "direct"}}
        )
        return listed, stored, read, listing, found, via_read, via_write, described, refused

    listed, stored, read, listing, found, via_read, via_write, described, refused = await _session(
        app, body
    )
    names = {tool.name for tool in listed.tools}
    assert names - _FACADE == _PRIMARY, sorted(names)
    assert _envelope(stored)["sha256"] == hashlib.sha256(BODY).hexdigest()
    (content,) = read.contents
    assert base64.b64decode(content.blob) == BODY
    assert [entry["name"] for entry in _envelope(listing)["entries"]] == ["top-level.bin"]
    assert [entry["path"] for entry in _envelope(found)["entries"]] == ["top-level.bin"]
    assert any(block.type == "resource_link" for block in via_read.content)
    assert _envelope(via_write)["path"] == "made"
    catalog = json.loads(described.content[0].text)
    assert len(catalog["items"]) == 17
    assert refused.is_error is True and not (world.h.root / "direct").exists()
    assert SECRET not in world.rows_text()


@pytest.mark.anyio
async def test_the_top_level_tools_follow_the_clients_grants_and_the_write_switch(
    world: _Slice,
) -> None:
    reads = frozenset(
        (capability, purpose)
        for capability, purpose in GRANTS
        if capability in {Capability.FILES_LIST, Capability.FILES_DOWNLOAD_BEGIN}
    )

    async def names(session: ClientSession) -> Any:  # noqa: ANN401
        return {tool.name for tool in (await session.list_tools()).tools}

    granted = await _session(world.app(compact=True, grants=reads), names)
    assert granted - _FACADE == {"files.list", "files.download.begin"}
    read_only = await _session(world.app(compact=True, writes=False), names)
    assert read_only - _FACADE == _PRIMARY - {"files.upload.begin"}
