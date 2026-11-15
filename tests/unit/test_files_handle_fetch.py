"""The SSRF-safe streaming fetcher behind native file handles (files-workspace section 17).

Every fetch here goes to a stdlib fake blob server on 127.0.0.1 over plain HTTP,
reached through an injected connector; the resolver answers a public address so
the real `is_public_address` lets the fetch through. The URLs are synthetic and
carry a synthetic `sig=` so the "never leaks" assertions have something to find.
No test touches the network.
"""

from __future__ import annotations

import ast
import contextlib
import hashlib
import http.client
import http.server
import socket
import ssl
import threading
import time
import traceback
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from my_pa.contracts.ports import FileWorkspaceUnavailableError
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.infrastructure.file_workspace import handle_fetch
from my_pa.infrastructure.file_workspace.handle_fetch import (
    HandleFetchPolicy,
    SafeHandleFetcher,
    is_public_address,
)

HOST = "acct.blob.core.windows.net"
SECRET = "SYNTHETICSECRET"  # noqa: S105 - a synthetic marker, not a credential
PUBLIC_IP = "52.239.0.10"
SMALL = bytes(range(256)) * 4  # 1 KiB
BIG = hashlib.sha256(b"seed").digest() * (5 * 1024 * 1024 // 32)  # 5 MiB
MIB = 1024 * 1024
#: Fragments of the fake URLs that must never surface in an error.
LEAK_MARKERS = (SECRET, "acct.blob", "sig=", "sv=x", "/c/", "evil", "example.com")

MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "my_pa"
    / "infrastructure"
    / "file_workspace"
    / "handle_fetch.py"
)


def _url(route: str) -> str:
    return f"https://{HOST}/c/{route}?sv=x&sig={SECRET}"


# --------------------------------------------------------------------------- server


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server: _Server

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib name
        return

    def _head(self, status: int, headers: dict[str, str]) -> None:
        self.send_response_only(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def do_GET(self) -> None:
        self.server.requests.append((self.path, list(self.headers.items())))
        route = self.path.split("?", 1)[0].rsplit("/", 1)[-1]
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            getattr(self, f"route_{route.replace('-', '_')}")()

    def _fixed(self, body: bytes, **extra: str) -> None:
        self._head(200, {"Content-Length": str(len(body)), **extra})
        self.wfile.write(body)

    def route_small(self) -> None:
        self._fixed(SMALL)

    route_ = route_small  # the bare "/" target

    def route_big(self) -> None:
        self._fixed(BIG)

    def route_empty(self) -> None:
        self._fixed(b"")

    def route_chunked(self) -> None:
        self._head(200, {"Transfer-Encoding": "chunked"})
        for piece in (SMALL[:100], SMALL[100:]):
            self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
        self.wfile.write(b"0\r\n\r\n")

    def route_nolength(self) -> None:
        self._head(200, {})
        self.wfile.write(SMALL)

    def route_undeclared_big(self) -> None:
        self._head(200, {})
        self.wfile.write(b"x" * 3000)

    def route_redirect(self) -> None:
        self._head(302, {"Location": "http://127.0.0.1/", "Content-Length": "0"})

    def route_forbidden(self) -> None:
        self._head(403, {"Content-Length": "0"})

    def route_missing(self) -> None:
        self._head(404, {"Content-Length": "0"})

    def route_oversize(self) -> None:
        self._head(200, {"Content-Length": str(10 * MIB)})
        self.wfile.write(b"x" * 10)

    def route_long(self) -> None:
        self._head(200, {"Content-Length": "10"})
        self.wfile.write(b"0123456789EXTRAEXTRA")

    def route_short(self) -> None:
        self._head(200, {"Content-Length": "100"})
        self.wfile.write(b"x" * 10)

    def route_gzip(self) -> None:
        self._fixed(b"\x1f\x8b fake", **{"Content-Encoding": "gzip"})

    def route_identity(self) -> None:
        self._fixed(SMALL, **{"Content-Encoding": "identity"})

    def route_bad_length(self) -> None:
        self._head(200, {"Content-Length": "abc"})
        self.wfile.write(b"x")

    def route_both(self) -> None:
        self._head(200, {"Transfer-Encoding": "chunked", "Content-Length": "5"})
        self.wfile.write(b"5\r\nhello\r\n0\r\n\r\n")

    def route_gzip_chunked(self) -> None:
        self._head(200, {"Transfer-Encoding": "gzip, chunked"})
        self.wfile.write(b"5\r\nhello\r\n0\r\n\r\n")

    def route_dribble(self) -> None:
        self._head(200, {"Content-Length": "1000"})
        self.wfile.flush()
        for _ in range(40):
            self.wfile.write(b"x")
            self.wfile.flush()
            time.sleep(0.2)

    def route_dribble_headers(self) -> None:
        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
        self.wfile.flush()
        for _ in range(40):
            self.wfile.write(b"X")
            self.wfile.flush()
            time.sleep(0.2)


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests: list[tuple[str, list[tuple[str, str]]]] = []


@pytest.fixture(scope="module")
def server() -> Iterator[_Server]:
    srv = _Server()
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


@dataclass
class _Rig:
    """Counting fakes for the resolver and the connector."""

    port: int
    answers: list[list[str]] = field(default_factory=lambda: [[PUBLIC_IP]])
    resolved: list[tuple[str, int]] = field(default_factory=list)
    connected: list[tuple[str, str, int, float]] = field(default_factory=list)
    connections: list[http.client.HTTPConnection] = field(default_factory=list)

    def resolver(self, host: str, port: int) -> list[str]:
        self.resolved.append((host, port))
        return self.answers[min(len(self.resolved), len(self.answers)) - 1]

    def connector(
        self, host: str, ip: str, port: int, timeout: float
    ) -> http.client.HTTPConnection:
        self.connected.append((host, ip, port, timeout))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        self.connections.append(conn)
        return conn

    def fetcher(self, policy: HandleFetchPolicy | None = None, **kwargs: Any) -> SafeHandleFetcher:  # noqa: ANN401
        return SafeHandleFetcher(
            policy or HandleFetchPolicy(),
            resolver=self.resolver,
            connector=self.connector,
            **kwargs,
        )


@pytest.fixture
def rig(server: _Server) -> _Rig:
    server.requests.clear()
    return _Rig(port=server.server_address[1])


def _read(
    fetcher: SafeHandleFetcher, url: str, max_bytes: int = 6 * MIB
) -> tuple[int | None, bytes]:
    with fetcher.open(url, max_bytes=max_bytes) as body:
        return body.declared_length, b"".join(body.chunks)


def _assert_no_leak(exc: BaseException) -> None:
    rendered = [
        str(exc),
        repr(exc),
        repr(exc.__cause__),
        repr(exc.__context__),
        "".join(traceback.format_exception(exc)),
    ]
    assert exc.__cause__ is None
    assert exc.__context__ is None
    for text in rendered:
        for marker in LEAK_MARKERS:
            assert marker not in text


def _refusal(exc_info: pytest.ExceptionInfo[FilesRefusal], reason: FilesReason) -> None:
    exc = exc_info.value
    assert type(exc) is FilesRefusal
    assert exc.field == "source_file"
    assert exc.reason is reason
    _assert_no_leak(exc)


# --------------------------------------------------------------------------- success


def test_fixed_length_small_body_streams_and_sends_only_the_three_headers(
    rig: _Rig, server: _Server
) -> None:
    declared, data = _read(rig.fetcher(), _url("small"))
    assert declared == len(SMALL)
    assert hashlib.sha256(data).digest() == hashlib.sha256(SMALL).digest()
    assert rig.resolved == [(HOST, 443)]
    assert [(h, ip, port) for h, ip, port, _ in rig.connected] == [(HOST, PUBLIC_IP, 443)]
    ((path, headers),) = server.requests
    assert path == f"/c/small?sv=x&sig={SECRET}"
    assert sorted(headers) == sorted(
        [("Host", HOST), ("User-Agent", "my-pa-files/1"), ("Accept-Encoding", "identity")]
    )


def test_five_mib_body_round_trips_in_bounded_chunks(rig: _Rig) -> None:
    with rig.fetcher().open(_url("big"), max_bytes=6 * MIB) as body:
        assert body.declared_length == len(BIG)
        chunks = list(body.chunks)
    assert all(len(chunk) <= 1 << 20 for chunk in chunks)
    assert hashlib.sha256(b"".join(chunks)).hexdigest() == hashlib.sha256(BIG).hexdigest()


def test_body_exactly_at_the_cap_is_accepted(rig: _Rig) -> None:
    assert _read(rig.fetcher(), _url("small"), max_bytes=len(SMALL))[1] == SMALL


def test_empty_body_and_zero_cap(rig: _Rig) -> None:
    assert _read(rig.fetcher(), _url("empty"), max_bytes=0) == (0, b"")


def test_chunked_and_unlengthed_bodies_have_no_declared_length(rig: _Rig) -> None:
    assert _read(rig.fetcher(), _url("chunked")) == (None, SMALL)
    assert _read(rig.fetcher(), _url("nolength")) == (None, SMALL)


def test_identity_content_encoding_is_accepted(rig: _Rig) -> None:
    assert _read(rig.fetcher(), _url("identity"))[1] == SMALL


def test_uppercase_host_and_explicit_443_are_normalised(rig: _Rig, server: _Server) -> None:
    url = f"https://ACCT.Blob.Core.Windows.Net:443/c/small?sv=x&sig={SECRET}"
    assert _read(rig.fetcher(), url)[1] == SMALL
    assert rig.resolved == [(HOST, 443)]
    assert ("Host", HOST) in server.requests[0][1]


def test_path_defaults_to_slash(rig: _Rig, server: _Server) -> None:
    assert _read(rig.fetcher(), f"https://{HOST}")[1] == SMALL
    assert server.requests[0][0] == "/"


def test_longer_than_declared_yields_exactly_the_declared_bytes(rig: _Rig) -> None:
    # http.client stops at Content-Length; the excess is never read.
    assert _read(rig.fetcher(), _url("long")) == (10, b"0123456789")


# --------------------------------------------------------------------------- response refusals


@pytest.mark.parametrize(
    "route",
    ["redirect", "forbidden", "missing", "gzip", "short", "bad-length", "both", "gzip-chunked"],
)
def test_response_refusals(rig: _Rig, route: str) -> None:
    with pytest.raises(FilesRefusal) as exc_info:
        _read(rig.fetcher(), _url(route))
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)
    assert len(rig.connected) == 1  # no redirect was followed


def test_declared_oversize_is_too_large_before_the_body(rig: _Rig) -> None:
    with (
        pytest.raises(FilesRefusal) as exc_info,
        rig.fetcher().open(_url("oversize"), max_bytes=MIB),
    ):
        pytest.fail("the context must not be entered")
    _refusal(exc_info, FilesReason.TOO_LARGE)


def test_declared_one_byte_over_the_cap_is_too_large(rig: _Rig) -> None:
    with pytest.raises(FilesRefusal) as exc_info:
        _read(rig.fetcher(), _url("small"), max_bytes=len(SMALL) - 1)
    _refusal(exc_info, FilesReason.TOO_LARGE)


def test_undeclared_body_past_the_cap_is_too_large_while_streaming(rig: _Rig) -> None:
    received: list[bytes] = []
    with (
        pytest.raises(FilesRefusal) as exc_info,
        rig.fetcher().open(_url("undeclared-big"), max_bytes=1000) as body,
    ):
        assert body.declared_length is None
        received.extend(body.chunks)
    _refusal(exc_info, FilesReason.TOO_LARGE)
    assert sum(map(len, received)) <= 1000


@pytest.mark.parametrize("cap", [-1, True, 1.5, "10"])
def test_max_bytes_must_be_a_non_negative_int(rig: _Rig, cap: object) -> None:
    with pytest.raises(ValueError), rig.fetcher().open(_url("small"), max_bytes=cap):  # type: ignore[arg-type]
        pass
    assert rig.resolved == []


def test_slow_body_dribble_is_cut_at_the_deadline(rig: _Rig) -> None:
    fetcher = rig.fetcher(HandleFetchPolicy(deadline_seconds=1.0))
    started = time.monotonic()
    with pytest.raises(FilesRefusal) as exc_info:
        _read(fetcher, _url("dribble"))
    assert time.monotonic() - started < 3.0
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)


def test_slow_header_dribble_is_cut_by_the_watchdog(rig: _Rig) -> None:
    fetcher = rig.fetcher(HandleFetchPolicy(deadline_seconds=1.0))
    started = time.monotonic()
    with pytest.raises(FilesRefusal) as exc_info:
        _read(fetcher, _url("dribble-headers"))
    assert time.monotonic() - started < 3.0
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)


def test_a_deadline_already_past_refuses_before_connecting(rig: _Rig) -> None:
    ticks = iter([0.0, 100.0, 100.0, 100.0])
    fetcher = rig.fetcher(clock=lambda: next(ticks))
    with pytest.raises(FilesRefusal) as exc_info:
        _read(fetcher, _url("small"))
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)
    assert rig.connected == []


# --------------------------------------------------------------------------- SSRF


@pytest.mark.parametrize(
    "answer",
    [
        ["127.0.0.1"],
        ["10.0.0.1"],
        ["172.16.0.1"],
        ["192.168.1.1"],
        ["169.254.169.254"],
        ["100.64.0.1"],
        ["0.0.0.0"],  # noqa: S104 - a refused answer, not a bind
        ["::1"],
        ["fe80::1"],
        ["fc00::1"],
        ["::ffff:127.0.0.1"],
        ["::ffff:10.0.0.1"],
        [PUBLIC_IP, "127.0.0.1"],
        ["not-an-ip"],
        [],
    ],
)
def test_non_public_answers_are_refused_without_connecting(rig: _Rig, answer: list[str]) -> None:
    rig.answers = [answer]
    with pytest.raises(FilesRefusal) as exc_info:
        _read(rig.fetcher(), _url("small"))
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)
    assert len(rig.resolved) == 1
    assert rig.connected == []


def test_a_resolver_exception_is_refused(rig: _Rig) -> None:
    def boom(host: str, port: int) -> list[str]:
        raise OSError(f"cannot resolve {host}")

    fetcher = SafeHandleFetcher(resolver=boom, connector=rig.connector)
    with pytest.raises(FilesRefusal) as exc_info:
        _read(fetcher, _url("small"))
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)


def test_a_connector_exception_is_refused(rig: _Rig) -> None:
    def boom(host: str, ip: str, port: int, timeout: float) -> http.client.HTTPConnection:
        raise OSError(f"cannot reach {host}{_url('x')}")

    fetcher = SafeHandleFetcher(resolver=rig.resolver, connector=boom)
    with pytest.raises(FilesRefusal) as exc_info:
        _read(fetcher, _url("small"))
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)


def test_dns_rebinding_resolves_once_per_fetch_and_dials_the_pinned_answer(rig: _Rig) -> None:
    rig.answers = [[PUBLIC_IP, "20.60.1.1"], ["127.0.0.1"]]
    fetcher = rig.fetcher()
    assert _read(fetcher, _url("small"))[1] == SMALL
    assert len(rig.resolved) == 1
    assert rig.connected[0][1] == PUBLIC_IP
    with pytest.raises(FilesRefusal):
        _read(fetcher, _url("small"))
    assert len(rig.resolved) == 2
    assert len(rig.connected) == 1


@pytest.mark.parametrize(
    "address",
    ["20.60.1.1", "52.239.1.1", "8.8.8.8", "2603:1030::1"],
)
def test_public_addresses_are_accepted(address: str) -> None:
    assert is_public_address(address)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "172.31.255.255",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104 - a refused answer, not a bind
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "192.0.2.1",
        "::",
        "::1",
        "fe80::1",
        "fe80::1%en0",
        "fc00::1",
        "fd12::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "::ffff:169.254.169.254",
        "::127.0.0.1",
        "2002:7f00:1::1",
        "2002:3427:a::1",  # 6to4 of a public v4: refused outright
        "64:ff9b::7f00:1",
        "64:ff9b::3427:a",  # NAT64 of a public v4: refused outright
        "64:ff9b:1::1",
        "2001::1",  # Teredo
        "2001:db8::1",
        "",
        "example.com",
        "1.2.3",
    ],
)
def test_non_public_addresses_are_refused(address: str) -> None:
    assert not is_public_address(address)


# --------------------------------------------------------------------------- URL shape


@pytest.mark.parametrize(
    "url",
    [
        f"http://{HOST}/c/small?sig={SECRET}",
        f"HTTPS://{HOST}/c/small?sig={SECRET}",
        f"ftp://{HOST}/c/small?sig={SECRET}",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://[::ffff:127.0.0.1]/x",
        "https://2130706433/x",
        "https://example.com/x",
        "https://blob.core.windows.net.evil.com/x",
        "https://evilblob.core.windows.net/x",
        "https://blob.core.windows.net/x",
        "https://.blob.core.windows.net/x",
        f"https://user:pw@{HOST}/x",
        f"https://user@{HOST}/x",
        f"https://{HOST}:8443/x",
        f"https://{HOST}:80/x",
        f"https://{HOST}:/x",
        f"https://{HOST}:notaport/x",
        f"https://{HOST}/x#frag",
        f"https://{HOST}/x?sig={SECRET}#",
        f"https://{HOST}/x y",
        f"https://{HOST}/x\ty",
        f"https://{HOST}/x\ny",
        f"https://{HOST}/x\x00",
        f"https://{HOST}/x\x7f",
        f"https://{HOST}/café",
        f"https://{HOST}/x　",
        f" https://{HOST}/x",
        f"https://acct_x.blob.core.windows.net/x?sig={SECRET}",
        f"https://acct..blob.core.windows.net/x?sig={SECRET}",
        f"https://-acct.blob.core.windows.net/x?sig={SECRET}",
        f"https://{HOST}/" + "a" * 8192,
        "",
        "https://",
        "https:///x",
        f"https://[{HOST}/x",
    ],
)
def test_bad_urls_are_refused_before_resolution(rig: _Rig, url: str) -> None:
    with pytest.raises(FilesRefusal) as exc_info:
        _read(rig.fetcher(), url)
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)
    assert rig.resolved == []
    assert rig.connected == []


def test_a_non_string_url_is_refused(rig: _Rig) -> None:
    with pytest.raises(FilesRefusal):
        _read(rig.fetcher(), b"https://acct.blob.core.windows.net/x")  # type: ignore[arg-type]
    assert rig.resolved == []


def test_max_url_length_is_honoured(rig: _Rig) -> None:
    policy = HandleFetchPolicy(max_url_length=len(_url("small")))
    assert _read(rig.fetcher(policy), _url("small"))[1] == SMALL
    with pytest.raises(FilesRefusal):
        _read(rig.fetcher(HandleFetchPolicy(max_url_length=len(_url("small")) - 1)), _url("small"))


def test_a_custom_suffix_replaces_the_default(rig: _Rig) -> None:
    policy = HandleFetchPolicy(allowed_host_suffixes=(".Files.Example.Test",))
    assert policy.allowed_host_suffixes == (".files.example.test",)
    assert _read(rig.fetcher(policy), "https://a.files.example.test/c/small")[1] == SMALL
    with pytest.raises(FilesRefusal):
        _read(rig.fetcher(policy), _url("small"))


# --------------------------------------------------------------------------- policy


@pytest.mark.parametrize(
    "kwargs",
    [
        {"deadline_seconds": 0},
        {"deadline_seconds": -1},
        {"deadline_seconds": 61},
        {"deadline_seconds": float("nan")},
        {"deadline_seconds": float("inf")},
        {"deadline_seconds": True},
        {"allowed_host_suffixes": ()},
        {"allowed_host_suffixes": ["x.com"]},
        {"allowed_host_suffixes": ("blob.core.windows.net",)},
        {"allowed_host_suffixes": (".",)},
        {"allowed_host_suffixes": (".bad..name",)},
        {"allowed_host_suffixes": (".bad name",)},
        {"connect_timeout_seconds": 0},
        {"read_timeout_seconds": -1},
        {"max_url_length": 0},
    ],
)
def test_policy_rejects_bad_values(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        HandleFetchPolicy(**kwargs)


def test_policy_accepts_the_bounds() -> None:
    assert HandleFetchPolicy(deadline_seconds=60).deadline_seconds == 60
    assert HandleFetchPolicy(deadline_seconds=0.5).deadline_seconds == 0.5
    assert HandleFetchPolicy().allowed_host_suffixes == (".blob.core.windows.net",)
    assert HandleFetchPolicy().deadline_seconds == 25


@pytest.mark.parametrize("count", [0, -1, True])
def test_max_concurrent_must_be_a_positive_int(count: int) -> None:
    with pytest.raises(ValueError):
        SafeHandleFetcher(max_concurrent=count)


# ------------------------------------------------------------------- concurrency and cleanup


def test_concurrency_cap_refuses_at_once_and_releases(rig: _Rig) -> None:
    fetcher = rig.fetcher(max_concurrent=1)
    with fetcher.open(_url("small"), max_bytes=MIB) as body:
        with (
            pytest.raises(FileWorkspaceUnavailableError) as exc_info,
            fetcher.open(_url("small"), max_bytes=MIB),
        ):
            pass
        assert str(exc_info.value) == ""
        assert b"".join(body.chunks) == SMALL
    assert _read(fetcher, _url("small"))[1] == SMALL


def test_slots_are_released_on_every_exit_path(rig: _Rig) -> None:
    fetcher = rig.fetcher(max_concurrent=1)
    for route in ("forbidden", "oversize", "short", "gzip"):
        with pytest.raises(FilesRefusal):
            _read(fetcher, _url(route), max_bytes=MIB)
    with pytest.raises(FilesRefusal):
        _read(fetcher, "http://nope/")
    with pytest.raises(ZeroDivisionError), fetcher.open(_url("small"), max_bytes=MIB):
        raise ZeroDivisionError
    with fetcher.open(_url("big"), max_bytes=6 * MIB) as body:
        next(iter(body.chunks))  # abandon the rest
    assert _read(fetcher, _url("small"))[1] == SMALL


def test_connections_are_closed_on_every_exit_path(rig: _Rig) -> None:
    fetcher = rig.fetcher()
    _read(fetcher, _url("small"))
    with pytest.raises(FilesRefusal):
        _read(fetcher, _url("forbidden"))
    with pytest.raises(FilesRefusal):
        _read(fetcher, _url("oversize"), max_bytes=10)
    with pytest.raises(FilesRefusal):
        _read(fetcher, _url("short"))
    with pytest.raises(KeyError), fetcher.open(_url("big"), max_bytes=6 * MIB) as body:
        next(iter(body.chunks))
        raise KeyError
    assert len(rig.connections) == 5
    assert all(conn.sock is None for conn in rig.connections)


def test_a_caller_exception_inside_the_block_propagates_unchanged(rig: _Rig) -> None:
    sentinel = RuntimeError("caller")
    with pytest.raises(RuntimeError) as exc_info, rig.fetcher().open(_url("small"), max_bytes=MIB):
        raise sentinel
    assert exc_info.value is sentinel


def test_iterating_the_body_after_the_block_is_refused(rig: _Rig) -> None:
    with rig.fetcher().open(_url("nolength"), max_bytes=MIB) as body:
        chunks = body.chunks
    # The stream is closed with the block: it never yields a truncated body later.
    assert list(chunks) == []


def test_reprs_carry_no_url(rig: _Rig) -> None:
    fetcher = rig.fetcher()
    with fetcher.open(_url("small"), max_bytes=MIB) as body:
        texts = [
            repr(fetcher),
            repr(body),
            repr(HandleFetchPolicy()),
        ]
        list(body.chunks)
    for text in texts:
        for marker in LEAK_MARKERS:
            assert marker not in text


# --------------------------------------------------------------------------- default collaborators


class _FakeTLS:
    def __init__(self) -> None:
        self.wrapped: list[tuple[object, str | None]] = []
        self.fail = False

    def wrap_socket(self, sock: object, server_hostname: str | None = None) -> object:
        self.wrapped.append((sock, server_hostname))
        if self.fail:
            raise ssl.SSLError("bad cert")
        return ("tls", sock)


class _FakeRawSocket:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_default_connector_dials_the_pinned_ip_and_verifies_the_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tls = _FakeTLS()
    raw = _FakeRawSocket()
    dialled: list[tuple[tuple[str, int], float | None]] = []

    def create_connection(address: tuple[str, int], timeout: float | None = None) -> object:
        dialled.append((address, timeout))
        return raw

    monkeypatch.setattr(ssl, "create_default_context", lambda: tls)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    conn = handle_fetch._pinned_https(HOST, PUBLIC_IP, 443, 7.5)
    assert isinstance(conn, http.client.HTTPSConnection)
    assert repr(conn).find(HOST) == -1
    conn.connect()
    assert dialled == [((PUBLIC_IP, 443), 7.5)]
    assert tls.wrapped == [(raw, HOST)]
    assert conn.sock == ("tls", raw)
    assert conn.host == HOST


def test_default_connector_closes_the_raw_socket_when_tls_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tls = _FakeTLS()
    tls.fail = True
    raw = _FakeRawSocket()
    monkeypatch.setattr(ssl, "create_default_context", lambda: tls)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: raw)
    conn = handle_fetch._pinned_https(HOST, PUBLIC_IP, 443, 1.0)
    with pytest.raises(ssl.SSLError):
        conn.connect()
    assert raw.closed


def test_default_connector_is_real_https_with_verification() -> None:
    conn = handle_fetch._pinned_https(HOST, PUBLIC_IP, 443, 1.0)
    context = conn._context  # type: ignore[attr-defined]
    assert context.verify_mode is ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_default_resolver_uses_getaddrinfo_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    def getaddrinfo(host: str, port: int, **kwargs: object) -> list[tuple[object, ...]]:
        calls.append((host, port, kwargs))
        return [
            (2, 1, 6, "", (PUBLIC_IP, port)),
            (30, 1, 6, "", ("2603:1030::1", port, 0, 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    assert list(handle_fetch._system_resolver(HOST, 443)) == [PUBLIC_IP, "2603:1030::1"]
    assert calls == [(HOST, 443, {"type": socket.SOCK_STREAM})]


def test_tls_failure_through_the_default_connector_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tls = _FakeTLS()
    tls.fail = True
    monkeypatch.setattr(ssl, "create_default_context", lambda: tls)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: _FakeRawSocket())
    fetcher = SafeHandleFetcher(resolver=lambda host, port: [PUBLIC_IP])
    with pytest.raises(FilesRefusal) as exc_info:
        _read(fetcher, _url("small"))
    _refusal(exc_info, FilesReason.FILE_HANDLE_REFUSED)
    assert tls.wrapped[0][1] == HOST


# --------------------------------------------------------------------------- module hygiene


def test_module_imports_no_logging_and_never_prints() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name.split(".")[0] != "logging" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "logging"
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"print", "breakpoint"}
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"getLogger", "warn", "warning", "exception"}


def test_the_url_is_not_kept_on_the_fetcher(rig: _Rig) -> None:
    fetcher = rig.fetcher()
    with fetcher.open(_url("small"), max_bytes=MIB) as body:
        state = repr(
            [getattr(fetcher, name, None) for name in dir(fetcher) if not name.startswith("__")]
        )
        list(body.chunks)
    assert SECRET not in state
