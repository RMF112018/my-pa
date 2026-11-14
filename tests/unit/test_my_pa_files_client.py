"""`scripts/my_pa_files.py`, the stdlib reference client, against a section 10 stub.

The stub is a loopback `http.server` that speaks the files-workspace contract
section 10 grammar strictly -- bearer ticket before any body byte, no query
string, `Upload-Offset` CAS with 409 `offset_mismatch` carrying the current
offset, `Upload-Complete: sha256=<hex>, length=<n>` finalize, a closed ticket
answering 401, single `Range` with 206/416, `ETag`, `X-Content-SHA256`, 412 on
a moved version -- and can drop a connection mid-body, mid-download or after a
committed finalize. The real routes are exercised by
`tests/contract/test_files_transfer_routes.py`; the whole vertical slice (MCP
begin -> bytes -> finalize) is WP7's. Everything here is synthetic.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest
from _pytest.capture import CaptureResult

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "my_pa_files.py"
TOKEN = "gfwtk_" + "ab" * 32
UPLOAD = "/files/v1/uploads/fwupl_synthetic"
DOWNLOAD = "/files/v1/downloads/fwdnl_synthetic"
_COMPLETE = re.compile(r"\Asha256=([0-9a-f]{64}), length=([0-9]+)\Z")
_RANGE = re.compile(r"\Abytes=([0-9]+)-([0-9]*)\Z")


def _client() -> ModuleType:
    spec = importlib.util.spec_from_file_location("my_pa_files", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


client = _client()


@dataclass
class Stub:
    """Server state plus one-shot faults; every request is recorded."""

    data: bytearray = field(default_factory=bytearray)
    closed: bool = False
    finalized: bool = False
    content: bytes = b""
    etag: str = '"v1-synthetic"'
    sha256: str | None = None
    changed: bool = False
    drop_patch_after: int | None = None
    drop_every_patch: bool = False
    drop_completing_response: bool = False
    skew_once: bool = False
    busy_once: bool = False
    refuse_patch: tuple[int, str, str | None] | None = None
    corrupt: bool = False
    drop_download_after: int | None = None
    requests: list[tuple[str, str, dict[str, str]]] = field(default_factory=list)


def _handler(stub: Stub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def _answer(
            self,
            status: int,
            headers: dict[str, str] | None = None,
            document: dict[str, object] | None = None,
        ) -> None:
            body = b"" if document is None else json.dumps(document).encode()
            self.send_response(status)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Cache-Control", "no-store")
            if status != 204:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def _refuse(self, status: int, code: str, reason: str | None, **headers: str) -> None:
            self.close_connection = True
            self._answer(status, headers, {"error": code, "reason": reason})

        def _drop(self) -> None:
            self.close_connection = True
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_RDWR)

        def _gate(self, prefix: str) -> bool:
            stub.requests.append((self.command, self.path, dict(self.headers.items())))
            if "?" in self.path:
                self._refuse(400, "invalid_request", None)
                return False
            if not self.path.startswith(prefix):
                self._refuse(404, "not_found", None)
                return False
            if self.headers.get("Authorization") != f"Bearer {TOKEN}" or stub.closed:
                self._refuse(401, "denied", "ticket_invalid")
                return False
            return True

        def do_HEAD(self) -> None:
            if not self._gate(UPLOAD):
                return
            self._answer(204, {"Upload-Offset": str(len(stub.data))})

        def do_PATCH(self) -> None:
            if not self._gate(UPLOAD):
                return
            if stub.busy_once:
                stub.busy_once = False
                self._refuse(503, "unavailable", None, **{"Retry-After": "0"})
                return
            offset = self.headers.get("Upload-Offset")
            if stub.skew_once or offset != str(len(stub.data)):
                stub.skew_once = False
                self._refuse(
                    409,
                    "conflict",
                    "offset_mismatch",
                    **{"Upload-Offset": str(len(stub.data))},
                )
                return
            length = int(self.headers.get("Content-Length", "-1"))
            if length < 0 or length > 32 * 1024 * 1024:
                self._refuse(413, "invalid_request", "too_large")
                return
            if stub.refuse_patch is not None:
                status, code, reason = stub.refuse_patch
                self._refuse(status, code, reason)
                return
            limit = length
            if stub.drop_patch_after is not None and length > stub.drop_patch_after:
                limit = min(length, stub.drop_patch_after)
                if not stub.drop_every_patch:
                    stub.drop_patch_after = None
                stub.data += self.rfile.read(limit)
                self._drop()
                return
            stub.data += self.rfile.read(limit)
            complete = self.headers.get("Upload-Complete")
            if complete is None:
                self._answer(204, {"Upload-Offset": str(len(stub.data))})
                return
            matched = _COMPLETE.match(complete)
            if matched is None:
                self._refuse(400, "invalid_request", None)
                return
            if stub.corrupt:
                stub.data[:1] = b"\x00" if stub.data[:1] != b"\x00" else b"\x01"
            if int(matched.group(2)) != len(stub.data) or hashlib.sha256(
                stub.data
            ).hexdigest() != matched.group(1):
                self._refuse(409, "conflict", "digest_mismatch")
                return
            stub.finalized = stub.closed = True
            if stub.drop_completing_response:
                self._drop()
                return
            self._answer(
                200,
                {"Content-Type": "application/json"},
                {"entry": {"path": "synthetic/a.bin", "size": len(stub.data)}},
            )

        def do_GET(self) -> None:
            if not self._gate(DOWNLOAD):
                return
            if stub.changed:
                self._refuse(412, "conflict", "external_change_detected")
                return
            content = stub.content
            headers = {
                "Accept-Ranges": "bytes",
                "ETag": stub.etag,
                "Content-Type": "application/octet-stream",
            }
            if stub.sha256 is not None:
                headers["X-Content-SHA256"] = stub.sha256
            start, end, status = 0, len(content), 200
            raw = self.headers.get("Range")
            if raw is not None:
                matched = _RANGE.match(raw)
                if matched is None:
                    self._refuse(400, "invalid_request", None)
                    return
                start = int(matched.group(1))
                end = int(matched.group(2)) + 1 if matched.group(2) else len(content)
                if start >= len(content):
                    self._refuse(
                        416, "invalid_request", None, **{"Content-Range": f"bytes */{len(content)}"}
                    )
                    return
                end = min(end, len(content))
                headers["Content-Range"] = f"bytes {start}-{end - 1}/{len(content)}"
                status = 206
            body = content[start:end]
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if stub.drop_download_after is not None:
                cut, stub.drop_download_after = stub.drop_download_after, None
                self.wfile.write(body[:cut])
                self._drop()
                return
            self.wfile.write(body)

    return Handler


@pytest.fixture
def server() -> Iterator[tuple[Stub, str]]:
    stub = Stub()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(stub))
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    try:
        yield stub, f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


ENV = {client.TOKEN_ENV: TOKEN}


def _upload(origin: str, local: Path, *extra: str) -> list[str]:
    return [
        "upload",
        str(local),
        "--origin",
        origin,
        "--route",
        UPLOAD,
        "--backoff-seconds",
        "0",
        "--timeout",
        "10",
        *extra,
    ]


def _download(origin: str, out: Path, *extra: str) -> list[str]:
    return [
        "download",
        str(out),
        "--origin",
        origin,
        "--route",
        DOWNLOAD,
        "--backoff-seconds",
        "0",
        "--timeout",
        "10",
        *extra,
    ]


def _assert_token_private(stub: Stub, captured: CaptureResult[str]) -> None:
    assert TOKEN not in captured.out
    assert TOKEN not in captured.err
    for _method, path, headers in stub.requests:
        assert TOKEN not in path
        assert "?" not in path
        carried = [name for name, value in headers.items() if TOKEN in value]
        assert carried in ([], ["Authorization"])


# ---- upload -------------------------------------------------------------------


def test_upload_sends_chunks_from_the_offset_and_finalizes(
    server: tuple[Stub, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(os.urandom(5000))
    assert client.main(_upload(origin, local, "--chunk-bytes", "1024"), ENV) == 0
    assert bytes(stub.data) == local.read_bytes()
    assert stub.finalized
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"entry": {"path": "synthetic/a.bin", "size": 5000}}
    patches = [headers for method, _path, headers in stub.requests if method == "PATCH"]
    assert len(patches) == 5
    assert [h["Upload-Offset"] for h in patches] == ["0", "1024", "2048", "3072", "4096"]
    assert all("Upload-Complete" not in h for h in patches[:-1])
    digest = hashlib.sha256(local.read_bytes()).hexdigest()
    assert patches[-1]["Upload-Complete"] == f"sha256={digest}, length=5000"
    _assert_token_private(stub, captured)


def test_upload_resumes_after_a_dropped_connection(
    server: tuple[Stub, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(os.urandom(3000))
    stub.drop_patch_after = 700  # the first PATCH stores 700 of 1024 bytes and hangs up
    assert client.main(_upload(origin, local, "--chunk-bytes", "1024"), ENV) == 0
    assert bytes(stub.data) == local.read_bytes()
    methods = [method for method, _path, _headers in stub.requests]
    assert methods[:3] == ["HEAD", "PATCH", "HEAD"]
    resumed = [h for m, _p, h in stub.requests if m == "PATCH"][1]
    assert resumed["Upload-Offset"] == "700"
    _assert_token_private(stub, capsys.readouterr())


def test_upload_rereads_the_offset_after_offset_mismatch_and_busy(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(b"x" * 2500)
    stub.skew_once = stub.busy_once = True
    assert client.main(_upload(origin, local, "--chunk-bytes", "1000"), ENV) == 0
    assert bytes(stub.data) == local.read_bytes()


def test_a_zero_byte_upload_is_one_empty_completing_patch(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    local = tmp_path / "empty"
    local.write_bytes(b"")
    assert client.main(_upload(origin, local), ENV) == 0
    patches = [h for m, _p, h in stub.requests if m == "PATCH"]
    assert len(patches) == 1
    assert patches[0]["Content-Length"] == "0"
    assert patches[0]["Upload-Complete"] == (f"sha256={hashlib.sha256(b'').hexdigest()}, length=0")
    assert stub.finalized


def test_a_lost_completing_response_then_401_is_unknown_not_failure(
    server: tuple[Stub, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(b"y" * 100)
    stub.drop_completing_response = True
    assert client.main(_upload(origin, local), ENV) == client.EXIT_UNKNOWN
    assert stub.finalized  # the server committed; the client could not know
    captured = capsys.readouterr()
    assert "verify with files.stat" in captured.err
    assert captured.out == ""
    _assert_token_private(stub, captured)


@pytest.mark.parametrize(
    ("status", "code", "reason"),
    [
        (403, "denied", None),
        (412, "conflict", "external_change_detected"),
        (413, "invalid_request", "too_large"),
        (507, "unavailable", "quota"),
    ],
)
def test_upload_refusals_exit_with_a_short_reason(
    server: tuple[Stub, str],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    status: int,
    code: str,
    reason: str | None,
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(b"z" * 10)
    stub.refuse_patch = (status, code, reason)
    assert client.main(_upload(origin, local), ENV) == client.EXIT_REFUSED
    captured = capsys.readouterr()
    assert f"HTTP {status} {code}" in captured.err
    if reason:
        assert f"/{reason}" in captured.err
    _assert_token_private(stub, captured)


def test_upload_digest_mismatch_and_a_bad_ticket_are_refused(
    server: tuple[Stub, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(b"q" * 10)
    stub.corrupt = True
    assert client.main(_upload(origin, local), ENV) == client.EXIT_REFUSED
    assert "digest_mismatch" in capsys.readouterr().err
    other = "gfwtk_" + "cd" * 32
    assert client.main(_upload(origin, local), {client.TOKEN_ENV: other}) == client.EXIT_REFUSED
    captured = capsys.readouterr()
    assert "401" in captured.err
    assert other not in captured.err


# ---- download -----------------------------------------------------------------


def test_download_writes_a_part_then_renames_into_place(
    server: tuple[Stub, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub, origin = server
    stub.content = os.urandom(4096)
    stub.sha256 = hashlib.sha256(stub.content).hexdigest()
    out = tmp_path / "out.bin"
    assert client.main(_download(origin, out), ENV) == 0
    assert out.read_bytes() == stub.content
    assert sorted(path.name for path in tmp_path.iterdir()) == ["out.bin"]
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary == {"bytes": 4096, "sha256": stub.sha256, "server_sha256_checked": True}
    _assert_token_private(stub, captured)


def test_download_refuses_an_existing_out_unless_overwrite(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    stub.content = b"new"
    out = tmp_path / "out.bin"
    out.write_bytes(b"old")
    assert client.main(_download(origin, out), ENV) == client.EXIT_LOCAL
    assert stub.requests == []
    assert out.read_bytes() == b"old"
    assert client.main(_download(origin, out, "--overwrite"), ENV) == 0
    assert out.read_bytes() == b"new"


def test_download_resumes_a_partial_part_with_range_and_if_match(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    stub.content = os.urandom(5000)
    stub.sha256 = hashlib.sha256(stub.content).hexdigest()
    stub.drop_download_after = 1200
    out = tmp_path / "out.bin"
    assert client.main(_download(origin, out), ENV) == 0
    assert out.read_bytes() == stub.content
    second = stub.requests[1][2]
    assert second["Range"] == "bytes=1200-"
    assert second["If-Match"] == stub.etag


def test_download_restarts_a_part_whose_etag_is_stale(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    stub.content = b"fresh content"
    out = tmp_path / "out.bin"
    (tmp_path / "out.bin.part").write_bytes(b"stale")
    (tmp_path / "out.bin.part.etag").write_text(json.dumps({"etag": '"v0"', "sha256": None}))
    assert client.main(_download(origin, out), ENV) == 0
    assert out.read_bytes() == b"fresh content"
    assert [h.get("Range") for _m, _p, h in stub.requests] == ["bytes=5-", None]


def test_download_sha_mismatch_keeps_nothing(
    server: tuple[Stub, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    stub, origin = server
    stub.content = b"content"
    stub.sha256 = "0" * 64
    out = tmp_path / "out.bin"
    assert client.main(_download(origin, out), ENV) == client.EXIT_DIGEST
    assert list(tmp_path.iterdir()) == []
    stub.sha256 = None
    assert client.main(_download(origin, out, "--sha256", "1" * 64), ENV) == client.EXIT_DIGEST
    assert list(tmp_path.iterdir()) == []
    capsys.readouterr()
    good = hashlib.sha256(b"content").hexdigest()
    assert client.main(_download(origin, out, "--sha256", good), ENV) == 0
    assert json.loads(capsys.readouterr().out)["server_sha256_checked"] is False


def test_download_412_discards_the_part(server: tuple[Stub, str], tmp_path: Path) -> None:
    stub, origin = server
    stub.changed = True
    out = tmp_path / "out.bin"
    (tmp_path / "out.bin.part").write_bytes(b"partial")
    (tmp_path / "out.bin.part.etag").write_text(json.dumps({"etag": stub.etag}))
    assert client.main(_download(origin, out), ENV) == client.EXIT_REFUSED
    assert list(tmp_path.iterdir()) == []


# ---- target and ticket ----------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "route"),
    [
        ("https://mcp.example.com", UPLOAD + "?x=1"),
        ("https://mcp.example.com", UPLOAD + "#f"),
        ("https://mcp.example.com", "https://evil.example.net" + UPLOAD),
        ("https://mcp.example.com", "http://mcp.example.com" + UPLOAD),
        ("https://mcp.example.com", DOWNLOAD),
        ("https://mcp.example.com", "/files/v1/uploads/a/b"),
        ("http://mcp.example.com", UPLOAD),
        ("https://user:pw@mcp.example.com", UPLOAD),
        ("https://mcp.example.com/base", UPLOAD),
        ("ftp://mcp.example.com", UPLOAD),
    ],
)
def test_the_target_refuses_queries_foreign_hosts_and_plain_http(origin: str, route: str) -> None:
    with pytest.raises(client.ClientError) as refused:
        client.Target(origin, route, client.UPLOADS_PREFIX, 1.0)
    assert refused.value.status == client.EXIT_LOCAL


def test_the_target_accepts_a_relative_or_same_origin_route() -> None:
    for route in (UPLOAD, "https://mcp.example.com" + UPLOAD):
        target = client.Target("https://mcp.example.com", route, client.UPLOADS_PREFIX, 1.0)
        assert (target.scheme, target.host, target.path) == ("https", "mcp.example.com", UPLOAD)


def test_the_ticket_is_never_a_command_line_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local = tmp_path / "a"
    local.write_bytes(b"a")
    with pytest.raises(SystemExit):
        client.main([*_upload("https://mcp.example.com", local), "--token", TOKEN], {})
    assert TOKEN not in capsys.readouterr().err
    assert client.main(_upload("https://mcp.example.com", local), {}) == client.EXIT_LOCAL
    assert client.TOKEN_ENV in capsys.readouterr().err
    malformed = "gfwtk_" + "Z" * 64
    status = client.main(_upload("https://mcp.example.com", local), {client.TOKEN_ENV: malformed})
    assert status == client.EXIT_LOCAL
    assert malformed not in capsys.readouterr().err


def test_a_token_file_is_read_and_the_subprocess_never_echoes_it(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(b"subprocess" * 100)
    token_file = tmp_path / "ticket"
    token_file.write_text(TOKEN + "\n")
    argv = [sys.executable, str(SCRIPT), *_upload(origin, local, "--token-file", str(token_file))]
    environment = {key: value for key, value in os.environ.items() if key != client.TOKEN_ENV}
    finished = subprocess.run(  # noqa: S603 - the script under test, fixed argv
        argv, capture_output=True, text=True, timeout=60, env=environment, check=False
    )
    assert finished.returncode == 0, finished.stderr
    assert TOKEN not in finished.stdout + finished.stderr
    assert TOKEN not in " ".join(argv)
    assert bytes(stub.data) == local.read_bytes()
    for _method, path, _headers in stub.requests:
        assert TOKEN not in path


def test_the_transport_gives_up_after_its_retries(tmp_path: Path) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()  # nothing listens: every attempt is refused
    local = tmp_path / "a"
    local.write_bytes(b"a")
    argv = _upload(f"http://127.0.0.1:{port}", local, "--retries", "2")
    assert client.main(argv, ENV) == client.EXIT_TRANSPORT


def test_retries_bound_attempts_without_progress_not_the_whole_transfer(
    server: tuple[Stub, str], tmp_path: Path
) -> None:
    stub, origin = server
    local = tmp_path / "a.bin"
    local.write_bytes(os.urandom(1000))
    stub.drop_patch_after, stub.drop_every_patch = 100, True  # every PATCH hangs up early
    assert client.main(_upload(origin, local, "--retries", "1"), ENV) == 0
    assert bytes(stub.data) == local.read_bytes()
    assert sum(1 for m, _p, _h in stub.requests if m == "PATCH") >= 10
