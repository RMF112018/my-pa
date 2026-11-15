"""Native file handle ingest (files-workspace contract section 17.2), without a database.

`files.upload.begin` with `source_file` over the real contained store on a
synthetic `tmp_path` root, the in-memory repository of
`tests/unit/test_file_workspace_application.py`, and the real
`SafeHandleFetcher` aimed at a fake blob server on loopback through an injected
resolver (a public-looking address) and connector (the loopback socket). The
SSRF checks themselves run unmodified. Acceptance tests AT1-AT5, AT9 and AT11
of the native-handle design, adapted to this slice. Every URL, byte and id here
is synthetic; nothing leaves loopback.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.application.commands import BeginFileUpload
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InvalidRequestError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
)
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.contracts.ports import FetchedFileBody, FileHandleFetcher, FileTransferState
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.file_workspace.handle_fetch import HandleFetchPolicy, SafeHandleFetcher
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore
from tests.unit.test_file_workspace_application import WORKSPACE, _World

SECRET: Final = "SYNTHETICSASSIGNATURE0123456789"  # noqa: S105 - a synthetic marker
HOST: Final = "acct0synthetic.blob.core.windows.net"
PUBLIC_IP: Final = "52.239.0.10"
MAX_UPLOAD: Final = 8 * 1024 * 1024


def _url(name: str) -> str:
    return f"https://{HOST}/container/{name}?sv=2026-01-01&se=x&sig={SECRET}"


def _handle(name: str, **extra: object) -> dict[str, object]:
    return {"download_url": _url(name), "file_id": f"file-synthetic-{name}", **extra}


def _blob(size: int) -> bytes:
    return bytes((index * 7 + 3) % 251 for index in range(size))


# ---- a fake blob server on loopback ----------------------------------------------------


@dataclass
class _Blobs:
    files: dict[str, bytes] = field(default_factory=dict)
    requests: list[str] = field(default_factory=list)
    lie_length: dict[str, int] = field(default_factory=dict)


def _server(blobs: _Blobs) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # the URL must reach no log
            return

        def do_GET(self) -> None:
            name = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
            blobs.requests.append(name)
            body = blobs.files.get(name)
            if body is None:
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            length = blobs.lie_length.get(name, len(body))
            self.send_header("Content-Length", str(length))
            self.send_header("Content-Type", "application/macbinary")
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def blobs() -> Iterator[tuple[_Blobs, int]]:
    state = _Blobs()
    server = _server(state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


@dataclass
class _Network:
    port: int
    resolved: list[str] = field(default_factory=list)
    connected: list[tuple[str, str]] = field(default_factory=list)
    answer: tuple[str, ...] = (PUBLIC_IP,)

    def resolve(self, host: str, port: int) -> list[str]:
        assert port == 443
        self.resolved.append(host)
        return list(self.answer)

    def connect(self, host: str, ip: str, port: int, timeout: float) -> http.client.HTTPConnection:
        assert port == 443
        self.connected.append((host, ip))
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)


class _HandleWorld(_World):
    def __init__(self, root: Path, fetcher: FileHandleFetcher | None, **store: Any) -> None:  # noqa: ANN401
        super().__init__(root)
        self.store = FilesystemFileWorkspaceStore(root, **({"disk_reserve_bytes": 0} | store))
        self.files = FileWorkspaceApplication(
            self.store,
            workspace_id=WORKSPACE,
            max_upload_bytes=MAX_UPLOAD,
            handle_fetcher=fetcher,
        )

    def staging(self) -> list[str]:
        staging = self.root / ".my-pa" / "staging"
        return sorted(path.name for path in staging.iterdir()) if staging.exists() else []


@pytest.fixture
def network(blobs: tuple[_Blobs, int]) -> _Network:
    return _Network(port=blobs[1])


@pytest.fixture
def world(tmp_path: Path, network: _Network) -> _HandleWorld:
    root = tmp_path / "workspace"
    root.mkdir()
    fetcher = SafeHandleFetcher(
        HandleFetchPolicy(deadline_seconds=10), resolver=network.resolve, connector=network.connect
    )
    return _HandleWorld(root, fetcher)


def _ingest(world: _World, path: str, handle: dict[str, object], **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return world.run(
        BeginFileUpload(
            workspace_id=WORKSPACE,
            path=path,
            idempotency_key=f"k-{path}-{len(world.rows.receipts)}",
            source_file=handle,
            **extra,
        )
    )


def _refusal(
    world: _World,
    kind: type[ApplicationError],
    *args: Any,  # noqa: ANN401
    **extra: Any,  # noqa: ANN401
) -> ApplicationError:
    with pytest.raises(kind) as caught:
        _ingest(world, *args, **extra)
    return caught.value


def _no_secret(*values: object) -> None:
    for value in values:
        rendered = value if isinstance(value, str) else repr(value)
        assert SECRET not in rendered and HOST not in rendered, "the bearer URL leaked"


# ---- AT1: a binary arrives byte-exact, and no URL is anywhere ----------------------------


def test_a_five_mib_handle_is_stored_byte_exact_and_no_url_reaches_anything(
    world: _HandleWorld,
    blobs: tuple[_Blobs, int],
    network: _Network,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = _blob(5 * 1024 * 1024)
    blobs[0].files["m5.bin"] = body
    caplog.set_level(logging.DEBUG)
    answer = _ingest(world, "m5.bin", _handle("m5.bin", mime_type="application/macbinary"))
    assert answer["replayed"] is False
    assert answer["size"] == len(body)
    assert answer["sha256"] == hashlib.sha256(body).hexdigest()
    assert answer["entry"]["path"] == "m5.bin" and answer["preimage_version_id"] is None
    assert "upload_token" not in answer and "route" not in answer
    assert (world.root / "m5.bin").read_bytes() == body
    assert network.resolved == [HOST] and network.connected == [(HOST, PUBLIC_IP)]
    (ticket,) = world.rows.transfers.values()
    assert ticket.state is FileTransferState.FINALIZED
    assert world.staging() == []
    _no_secret(json.dumps(answer), world.rows.transfers, world.rows.receipts, caplog.text)


def test_the_client_mime_type_and_file_name_are_never_used(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    blobs[0].files["a.bin"] = b"\x00\x01synthetic"
    answer = _ingest(
        world, "dir-less.bin", _handle("a.bin", file_name="../../etc/passwd", mime_type="text/html")
    )
    assert answer["entry"]["path"] == "dir-less.bin"
    assert sorted(path.name for path in world.root.iterdir()) == [".my-pa", "dir-less.bin"]


def test_a_zero_byte_handle_is_a_valid_file(world: _HandleWorld, blobs: tuple[_Blobs, int]) -> None:
    blobs[0].files["empty.bin"] = b""
    answer = _ingest(world, "empty.bin", _handle("empty.bin"))
    assert answer["size"] == 0 and (world.root / "empty.bin").read_bytes() == b""


# ---- AT2: no overwrite by default; a replace keeps the preimage ----------------------------


def test_an_existing_target_is_refused_before_anything_is_fetched(
    world: _HandleWorld, blobs: tuple[_Blobs, int], network: _Network
) -> None:
    blobs[0].files["one.bin"] = b"first synthetic"
    _ingest(world, "same.bin", _handle("one.bin"))
    before = list(network.connected)
    error = _refusal(world, ConflictError, "same.bin", _handle("one.bin"))
    assert error.safe_details == (SafeDetail.EXISTS,)
    assert network.connected == before, "an exists refusal still fetched"
    assert world.staging() == []


def test_a_replace_at_the_current_version_preserves_the_preimage(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    blobs[0].files["one.bin"] = b"first synthetic"
    blobs[0].files["two.bin"] = b"second synthetic bytes"
    first = _ingest(world, "doc.bin", _handle("one.bin"))
    stale = _refusal(
        world,
        ConflictError,
        "doc.bin",
        _handle("two.bin"),
        expected_version="fv1_" + "0" * 64,
    )
    assert stale.safe_details == (SafeDetail.VERSION_CONFLICT,)
    replaced = _ingest(
        world, "doc.bin", _handle("two.bin"), expected_version=first["entry"]["version"]
    )
    assert replaced["preimage_version_id"] is not None
    assert (world.root / "doc.bin").read_bytes() == b"second synthetic bytes"
    (version,) = world.rows.versions.values()
    assert version.version == first["entry"]["version"]
    assert version.cause == "files.upload.finalize"


def test_a_declared_sha256_that_differs_is_a_digest_mismatch_and_the_target_is_untouched(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    blobs[0].files["a.bin"] = b"synthetic body"
    error = _refusal(world, ConflictError, "a.bin", _handle("a.bin"), sha256="0" * 64)
    assert error.safe_details == (SafeDetail.DIGEST_MISMATCH,)
    assert not (world.root / "a.bin").exists() and world.staging() == []


# ---- AT3: size and disk reserve, before and while streaming --------------------------------


def test_a_declared_length_over_the_cap_is_too_large_before_the_body(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    blobs[0].files["big.bin"] = b"x" * 16
    blobs[0].lie_length["big.bin"] = MAX_UPLOAD + 1
    error = _refusal(world, InvalidRequestError, "big.bin", _handle("big.bin"))
    assert error.safe_details == (SafeDetail.TOO_LARGE,)
    assert not (world.root / "big.bin").exists() and world.staging() == []


def test_a_body_past_a_declared_size_is_too_large(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    blobs[0].files["a.bin"] = b"y" * 64
    error = _refusal(world, InvalidRequestError, "a.bin", _handle("a.bin"), size=10)
    assert error.safe_details == (SafeDetail.TOO_LARGE,)
    assert world.staging() == []


def test_the_disk_reserve_is_quota_and_staging_is_cleaned(
    tmp_path: Path, blobs: tuple[_Blobs, int], network: _Network
) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    fetcher = SafeHandleFetcher(resolver=network.resolve, connector=network.connect)
    world = _HandleWorld(root, fetcher, disk_reserve_bytes=1 << 62)
    blobs[0].files["a.bin"] = b"z" * 1024
    error = _refusal(world, UnavailableError, "a.bin", _handle("a.bin"))
    assert error.safe_details == (SafeDetail.QUOTA,)
    assert world.staging() == [] and not (root / "a.bin").exists()


# ---- AT4: a refused URL fetches nothing ---------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://acct0synthetic.blob.core.windows.net/c/a.bin?sig=SYNTHETICSASSIGNATURE0123456789",
        "https://127.0.0.1/c/a.bin?sig=SYNTHETICSASSIGNATURE0123456789",
        "https://evil.example.invalid/c/a.bin?sig=SYNTHETICSASSIGNATURE0123456789",
        "https://acct0synthetic.blob.core.windows.net.evil.invalid/a?sig=SYNTHETICSASSIGNATURE0123456789",
    ],
)
def test_a_forged_url_is_file_handle_refused_with_no_resolution(
    world: _HandleWorld, network: _Network, url: str
) -> None:
    error = _refusal(world, InvalidRequestError, "a.bin", {"download_url": url, "file_id": "f1"})
    assert error.safe_details == (SafeDetail.FILE_HANDLE_REFUSED,)
    assert network.resolved == [] and network.connected == []
    _no_secret(str(error), repr(error), error.__cause__, error.__context__)
    assert world.staging() == []


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.7", "169.254.169.254", "::1", "fc00::1"])
def test_a_private_answer_is_file_handle_refused_with_no_connection(
    world: _HandleWorld, network: _Network, address: str
) -> None:
    network.answer = (address,)
    error = _refusal(world, InvalidRequestError, "a.bin", _handle("a.bin"))
    assert error.safe_details == (SafeDetail.FILE_HANDLE_REFUSED,)
    assert network.resolved == [HOST] and network.connected == []


def test_an_expired_link_is_file_handle_refused(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    error = _refusal(world, InvalidRequestError, "gone.bin", _handle("gone.bin"))  # 403
    assert error.safe_details == (SafeDetail.FILE_HANDLE_REFUSED,)
    assert blobs[0].requests == ["gone.bin"] and world.staging() == []


# ---- AT5: a missing or malformed handle, and no fetcher -----------------------------------


@pytest.mark.parametrize(
    "handle",
    [
        {"file_id": "f1"},
        {"download_url": _url("a.bin")},
        {"download_url": _url("a.bin"), "file_id": ""},
        {"download_url": _url("a.bin"), "file_id": "f1", "extra": "x"},
        {"download_url": 7, "file_id": "f1"},
        {"download_url": "u" * 8193, "file_id": "f1"},
        {"download_url": _url("a.bin"), "file_id": "f1", "file_name": 3},
    ],
)
def test_a_malformed_handle_is_invalid_and_nothing_is_staged(
    world: _HandleWorld, network: _Network, handle: dict[str, object]
) -> None:
    with pytest.raises(InvalidRequestError) as caught:
        BeginFileUpload(
            workspace_id=WORKSPACE, path="a.bin", idempotency_key="k", source_file=handle
        )
    assert caught.value.safe_details == (SafeDetail.SOURCE_FILE,)
    _no_secret(str(caught.value), repr(caught.value))
    assert network.resolved == [] and world.staging() == []


def test_a_handle_with_a_ticket_lifetime_is_invalid() -> None:
    with pytest.raises(InvalidRequestError) as caught:
        BeginFileUpload(
            workspace_id=WORKSPACE,
            path="a.bin",
            idempotency_key="k",
            ttl_seconds=600,
            source_file=_handle("a.bin"),
        )
    assert caught.value.safe_details == (SafeDetail.TTL_SECONDS,)


def test_the_command_repr_never_shows_the_handle() -> None:
    command = BeginFileUpload(
        workspace_id=WORKSPACE, path="a.bin", idempotency_key="k", source_file=_handle("a.bin")
    )
    _no_secret(repr(command), str(command))


def test_without_a_fetcher_a_handle_is_file_handle_unsupported(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    world = _HandleWorld(root, None)
    error = _refusal(world, UnsupportedError, "a.bin", _handle("a.bin"))
    assert error.safe_details == (SafeDetail.FILE_HANDLE_UNSUPPORTED,)
    assert world.staging() == [] and world.rows.receipts == {}


def test_without_a_handle_begin_is_the_unchanged_ticket(world: _HandleWorld) -> None:
    answer = world.run(BeginFileUpload(workspace_id=WORKSPACE, path="a.bin", idempotency_key="k"))
    assert answer["upload_token"].startswith("gfwtk_")
    assert answer["route"].startswith("/files/v1/uploads/")


# ---- idempotency, grants (AT9) and the fetcher boundary -----------------------------------


def test_the_receipt_and_its_intent_hold_no_url(
    world: _HandleWorld, blobs: tuple[_Blobs, int]
) -> None:
    blobs[0].files["a.bin"] = b"synthetic receipt"
    command = BeginFileUpload(
        workspace_id=WORKSPACE, path="a.bin", idempotency_key="k-same", source_file=_handle("a.bin")
    )
    assert world.run(command)["replayed"] is False
    _no_secret(world.rows.receipts)
    (receipt,) = world.rows.receipts.values()
    assert set(receipt.result) == {"upload_id", "entry", "preimage_version_id", "size", "sha256"}
    # A second ingest with a fresh link to the same file is the same intent
    # (the URL is not in it), so the same key replays without a fetch.
    blobs[0].requests.clear()
    again = BeginFileUpload(
        workspace_id=WORKSPACE,
        path="a.bin",
        idempotency_key="k-same",
        source_file={**_handle("a.bin"), "download_url": _url("a.bin") + "&new=1"},
    )
    replayed = world.run(again)
    assert replayed["replayed"] is True and replayed["sha256"] == receipt.result["sha256"]
    assert blobs[0].requests == [] and world.staging() == []
    # The same key for another file is a conflict, still with no fetch.
    other = BeginFileUpload(
        workspace_id=WORKSPACE, path="b.bin", idempotency_key="k-same", source_file=_handle("b.bin")
    )
    with pytest.raises(ConflictError) as caught:
        world.run(other)
    assert caught.value.safe_details == (SafeDetail.IDEMPOTENCY_KEY,)
    assert blobs[0].requests == []


def test_a_client_without_the_write_grant_never_fetches(
    world: _HandleWorld, network: _Network
) -> None:
    grants = frozenset({(Capability.FILES_STAT, Purpose.FILE_WORKSPACE_READ)})
    with pytest.raises(UnsupportedError):
        world.run(
            BeginFileUpload(
                workspace_id=WORKSPACE,
                path="a.bin",
                idempotency_key="k",
                source_file=_handle("a.bin"),
            ),
            grants=grants,
            client="synthetic-client",
        )
    assert network.resolved == [] and world.staging() == []


class _Exploding(FileHandleFetcher):
    """A fetcher whose body fails mid-stream, as a cut connection would."""

    def __init__(self) -> None:
        self.closed = False

    @contextmanager
    def open(self, url: str, *, max_bytes: int) -> Iterator[FetchedFileBody]:
        del url, max_bytes

        def chunks() -> Iterator[bytes]:
            yield b"partial synthetic bytes"
            from my_pa.domain.files.errors import FilesRefusal
            from my_pa.domain.files.vocabulary import FilesReason

            raise FilesRefusal("source_file", FilesReason.FILE_HANDLE_REFUSED)

        try:
            yield FetchedFileBody(declared_length=None, chunks=chunks())
        finally:
            self.closed = True


def test_a_body_cut_mid_stream_leaves_no_file_and_no_staging(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    fetcher = _Exploding()
    world = _HandleWorld(root, fetcher)
    error = _refusal(world, InvalidRequestError, "a.bin", _handle("a.bin"))
    assert error.safe_details == (SafeDetail.FILE_HANDLE_REFUSED,)
    assert fetcher.closed and world.staging() == [] and not (root / "a.bin").exists()
    assert world.rows.transfers == {} and world.rows.receipts == {}


# ---- the interaction log never keeps a handle's URL (section 11) ---------------------------


def test_the_interaction_log_redacts_every_download_url() -> None:
    from my_pa.adapters.mcp_interaction_capture import redact_json

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "files.upload.begin",
            "arguments": {
                "payload": {"workspace_id": WORKSPACE, "path": "a.bin"},
                "source_file": _handle("a.bin"),
                "nested": [{"downloadUrl": _url("b.bin")}, {"Download-URL": _url("c.bin")}],
            },
        },
    }
    redacted, count, _nul = redact_json(request)
    _no_secret(json.dumps(redacted))
    assert count == 3
    arguments = redacted["params"]["arguments"]  # type: ignore[index]
    assert arguments["source_file"]["file_id"] == "file-synthetic-a.bin"


# ---- agent-usable ticket transfers (section 17.5) ------------------------------------------


def _tokens_in(value: object) -> list[str]:
    import re

    return re.findall(r"gfwtk_[0-9a-f]{64}", json.dumps(value))


def test_a_ticket_answer_carries_a_transfer_recipe_and_no_token_in_it(
    world: _HandleWorld,
) -> None:
    answer = world.run(BeginFileUpload(workspace_id=WORKSPACE, path="a.bin", idempotency_key="k"))
    transfer = answer["transfer"]
    assert set(transfer) == {"method", "url", "auth_header_name", "headers", "usage"}
    assert transfer["method"] == "PATCH" and transfer["url"] == answer["route"]
    assert transfer["auth_header_name"] == "Authorization"
    assert transfer["headers"]["Upload-Offset"] == "0"
    assert transfer["headers"]["Upload-Complete"] == "sha256=<sha256>, length=<length>"
    assert _tokens_in(transfer) == [] and answer["upload_token"] not in json.dumps(transfer)
    usage = transfer["usage"]
    for needed in (
        'curl -sS -f -X PATCH "' + answer["route"] + '"',
        '"Authorization: Bearer $MY_PA_FILES_TICKET"',
        '"Upload-Offset: 0"',
        '"Upload-Complete: sha256=<sha256>, length=<length>"',
        "--data-binary @<file>",
        str(answer["chunk_max_bytes"]),
        "HEAD",
        "files.stat",
    ):
        assert needed in usage, needed
    # The receipt keeps the recipe and never the token.
    (receipt,) = world.rows.receipts.values()
    assert receipt.result["transfer"] == transfer and _tokens_in(receipt.result) == []


def test_a_download_ticket_carries_a_get_recipe_with_range_resume(
    world: _HandleWorld,
) -> None:
    from my_pa.application.commands import BeginFileDownload

    (world.root / "d.bin").write_bytes(b"synthetic download")
    answer = world.run(BeginFileDownload(workspace_id=WORKSPACE, path="d.bin"))
    transfer = answer["transfer"]
    assert transfer["method"] == "GET" and transfer["url"] == answer["route"]
    assert _tokens_in(transfer) == [] and answer["download_token"] not in json.dumps(transfer)
    assert 'curl -sS -f "' + answer["route"] + '"' in transfer["usage"]
    assert "Range: bytes=<n>-" in transfer["usage"]


def test_the_recipe_is_deterministic_and_joins_the_public_origin() -> None:
    from my_pa.domain.files.transfer import download_transfer, transfer_url, upload_transfer

    route = "/files/v1/uploads/fwupl_x"
    assert transfer_url(route, None) == route
    assert (
        transfer_url(route, "https://mcp.example.invalid/") == "https://mcp.example.invalid" + route
    )
    assert upload_transfer(route, 7) == upload_transfer(route, 7)
    assert download_transfer(route) == download_transfer(route)


def test_the_handle_field_is_optional_and_says_it_is_only_for_file_object_hosts() -> None:
    from my_pa.adapters.mcp.server import _remote_tool
    from my_pa.adapters.mcp.tools import TOOLS

    tool = next(tool for tool in TOOLS if tool.name == "files.upload.begin")
    remote = _remote_tool(tool, oauth_scopes=frozenset())
    schema = remote.input_schema
    assert "source_file" not in schema["required"]
    description = schema["properties"]["source_file"]["description"]
    assert description.startswith("Optional; only for hosts that supply file objects")
    assert "Omit it (the default)" in description
