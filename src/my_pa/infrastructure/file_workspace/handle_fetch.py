"""The SSRF-safe streaming fetcher behind native file handles (files-workspace section 17).

A client platform (ChatGPT) hands an MCP tool a user-attached file as
`{download_url, file_id, ...}`, where `download_url` is a short-lived Azure blob
SAS URL. The server fetches it. Two properties drive every decision here:

**The URL is a bearer credential.** Whoever holds it can read the file until it
expires, so no part of it may reach a log, an exception message, a `repr` or a
return value. This module therefore imports no `logging` and never prints; it
does not keep the URL on `self`; every refusal is a `FilesRefusal` naming only
`source_file` and a closed section 7 token; and every refusal is raised *outside*
the `except` block that observed the failure, so neither `__cause__` nor
`__context__` carries a library exception whose message may quote the URL
(`http.client.InvalidURL`, `ValueError` from `urlsplit`, `ssl` errors naming
the host).

**The URL is attacker-influenced input to a server-side request (SSRF).** It is
validated before anything is resolved, and the connection can only reach a
public address of an allowlisted host:

* *Shape.* A `str` of bounded length, ASCII with no control character or
  whitespace, scheme exactly `https`, no userinfo, port absent or 443, no
  fragment, and a hostname that is a DNS name (never an IPv4 or IPv6 literal)
  ending in one of the policy's suffixes with at least one label before it. The
  suffixes carry their leading dot, so `.blob.core.windows.net` admits
  `acct.blob.core.windows.net` and refuses `evilblob.core.windows.net`,
  `blob.core.windows.net` itself and `blob.core.windows.net.evil.com`.
* *Resolution once, every answer judged.* The host is resolved exactly once; if
  *any* returned address is not public (`is_public_address`: loopback, private,
  link-local including `169.254.169.254`, CGNAT `100.64/10`, unspecified,
  multicast, reserved, and IPv6 forms that embed an IPv4 address -- mapped,
  6to4, NAT64, Teredo, IPv4-compatible) the fetch is refused before any
  connection. The first address is then *pinned*: the connector dials that IP
  and never resolves again, which is the DNS-rebinding defence (a second lookup
  could answer differently from the one that was judged).
* *TLS against the original name.* The default connector dials the pinned IP and
  wraps the socket with `ssl.create_default_context()` using
  `server_hostname=<host>`, so SNI, certificate chain and hostname verification
  are all against the validated name, not the IP.
* *No redirects.* `http.client` never follows one and any status other than 200
  is refused, so a 302 to `http://127.0.0.1/` goes nowhere.

**Bounded in bytes and in time.** A declared `Content-Length` above the cap is
`too_large` before a body byte is read, and the streamed total is counted so an
undeclared body is cut the moment it passes the cap. `Content-Encoding` other
than `identity` is refused (the cap must bound the bytes written, not a
compressed form of them), as is any `Transfer-Encoding` other than plain
`chunked` and a response that declares both. The whole fetch -- connect,
headers and body -- has one deadline. Each socket read gets a timeout of
`min(read_timeout, remaining)` and the deadline is re-checked before each read,
but a per-read timeout alone cannot bound a server that dribbles header lines
or chunk-size lines (`http.client` loops `recv` inside `readline`), so a
watchdog timer also shuts the socket down at the deadline. The body is read with
`read1`, which performs at most one underlying read, rather than `read(n)`, which
loops until `n` bytes arrive.

**Deviations stated rather than implied away.** A body *longer* than its
declared `Content-Length` cannot be observed through `http.client`, which stops
reading at the declared length; the excess is simply never read, so the bytes
yielded are exactly the declared ones. The watchdog can only shut a socket that
exists: the TCP connect and TLS handshake are bounded by their per-operation
timeout (`min(connect_timeout, remaining)`), not by the watchdog. The deadline
is measured with the injected `clock`, the watchdog with the real one.

A process-local `BoundedSemaphore` caps concurrent fetches; when it is full the
fetch fails at once with `FileWorkspaceUnavailableError` rather than queueing.
"""

from __future__ import annotations

import http.client
import ipaddress
import math
import re
import socket
import ssl
import threading
import time
import urllib.parse
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from typing import Final

from my_pa.contracts.ports import (
    FetchedFileBody,
    FileHandleFetcher,
    FileWorkspaceUnavailableError,
)
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import (
    HANDLE_FETCH_DEADLINE_DEFAULT_SECONDS,
    HANDLE_FETCH_DEADLINE_MAX_SECONDS,
    HANDLE_HOST_SUFFIXES_DEFAULT,
    FilesReason,
)

__all__ = [
    "Connector",
    "HandleFetchPolicy",
    "Resolver",
    "SafeHandleFetcher",
    "is_public_address",
]

#: `(host, port) -> address strings`; resolved once per fetch.
type Resolver = Callable[[str, int], Sequence[str]]
#: `(host, pinned_ip, port, timeout) -> unconnected connection`.
type Connector = Callable[[str, str, int, float], http.client.HTTPConnection]

_FIELD: Final = "source_file"
_PORT: Final = 443
_CHUNK: Final = 1 << 20
_USER_AGENT: Final = "my-pa-files/1"
_LABEL: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_DIGITS: Final = re.compile(r"[0-9]+")
_MAX_HOST_LENGTH: Final = 253

#: IPv6 prefixes that carry or translate to an IPv4 address the global check
#: would not see: 6to4, NAT64 (well-known and local-use) and Teredo. Refused
#: outright rather than decoded. IPv4-mapped (`::ffff:0:0/96`) is decoded instead.
_REFUSED_V6: Final = tuple(
    ipaddress.IPv6Network(net)
    for net in ("2002::/16", "64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "::/96")
)


def _refused() -> FilesRefusal:
    return FilesRefusal(_FIELD, FilesReason.FILE_HANDLE_REFUSED)


def _too_large() -> FilesRefusal:
    return FilesRefusal(_FIELD, FilesReason.TOO_LARGE)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


@dataclass(frozen=True, slots=True)
class HandleFetchPolicy:
    """Where a handle may point and how long fetching it may take."""

    allowed_host_suffixes: tuple[str, ...] = HANDLE_HOST_SUFFIXES_DEFAULT
    deadline_seconds: float = HANDLE_FETCH_DEADLINE_DEFAULT_SECONDS
    connect_timeout_seconds: float = 10.0
    read_timeout_seconds: float = 15.0
    max_url_length: int = 8192

    def __post_init__(self) -> None:
        suffixes: object = self.allowed_host_suffixes
        if not isinstance(suffixes, tuple) or not suffixes:
            raise ValueError("allowed_host_suffixes must be a non-empty tuple")
        normalized: list[str] = []
        for item in suffixes:
            suffix: object = item
            if not isinstance(suffix, str) or not suffix.startswith(".") or len(suffix) < 2:
                raise ValueError("each allowed host suffix must start with '.'")
            lowered = suffix.lower()
            if not all(_LABEL.fullmatch(label) for label in lowered[1:].split(".")):
                raise ValueError("each allowed host suffix must be a DNS name")
            normalized.append(lowered)
        object.__setattr__(self, "allowed_host_suffixes", tuple(normalized))
        deadline = self.deadline_seconds
        if not _is_number(deadline) or not (
            math.isfinite(deadline) and 0 < deadline <= HANDLE_FETCH_DEADLINE_MAX_SECONDS
        ):
            raise ValueError(
                f"deadline_seconds must be in (0, {HANDLE_FETCH_DEADLINE_MAX_SECONDS}]"
            )
        timeouts = (
            ("connect_timeout_seconds", self.connect_timeout_seconds),
            ("read_timeout_seconds", self.read_timeout_seconds),
        )
        for name, value in timeouts:
            if not _is_number(value) or not (math.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be a positive finite number")
        length: object = self.max_url_length
        if not isinstance(length, int) or isinstance(length, bool) or length < 1:
            raise ValueError("max_url_length must be a positive int")


def is_public_address(address: str) -> bool:
    """Whether `address` is a globally routable unicast address a fetch may reach."""
    try:
        ip = ipaddress.ip_address(address)
    except (TypeError, ValueError):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.scope_id is not None:
            return False
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return is_public_address(str(mapped))
        if any(ip in net for net in _REFUSED_V6):
            return False
    return bool(
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_link_local
        and not ip.is_loopback
        and not ip.is_private
        and not ip.is_unspecified
    )


def _is_public_answer(answer: object) -> bool:
    return isinstance(answer, str) and is_public_address(answer)


def _system_resolver(host: str, port: int) -> Sequence[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to a pre-resolved IP, verifying the certificate against `host`."""

    def __init__(self, host: str, pinned_ip: str, port: int, timeout: float) -> None:
        self._tls = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._tls)
        self._pinned_ip = pinned_ip

    def connect(self) -> None:
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        try:
            self.sock = self._tls.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _pinned_https(
    host: str, pinned_ip: str, port: int, timeout: float
) -> http.client.HTTPConnection:
    return _PinnedHTTPSConnection(host, pinned_ip, port, timeout)


def _target(url: str, policy: HandleFetchPolicy) -> tuple[str, str] | None:
    """`(host, request_target)` for an acceptable URL, else `None`. Never raises."""
    raw: object = url
    if not isinstance(raw, str) or len(raw) > policy.max_url_length:
        return None
    if not url.isascii() or any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
        return None
    if not url.startswith("https://") or "#" in url:
        return None
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.fragment or "@" in parts.netloc:
        return None
    if port not in (None, _PORT):
        return None
    host = parts.hostname
    if not host:
        return None
    if parts.netloc.lower() not in (host, f"{host}:{_PORT}"):
        return None  # brackets (IPv6 literal), an empty port, anything odd
    if len(host) > _MAX_HOST_LENGTH:
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return None
    labels = host.split(".")
    if not all(_LABEL.fullmatch(label) for label in labels) or labels[-1].isdigit():
        return None
    if not any(
        host.endswith(suffix) and len(host) > len(suffix) for suffix in policy.allowed_host_suffixes
    ):
        return None
    target = parts.path or "/"
    if parts.query:
        target = f"{target}?{parts.query}"
    return host, target


def _declared_length(response: http.client.HTTPResponse) -> int | None:
    """The single `Content-Length`, or `None`; raises `ValueError` when malformed."""
    values = response.msg.get_all("Content-Length") or []
    if not values:
        return None
    stripped = {value.strip() for value in values}
    if len(stripped) != 1:
        raise ValueError("conflicting lengths")
    (value,) = stripped
    if not _DIGITS.fullmatch(value):
        raise ValueError("malformed length")
    return int(value)


class SafeHandleFetcher(FileHandleFetcher):
    """`FileHandleFetcher` over pinned-IP HTTPS with an allowlist and a deadline."""

    def __init__(
        self,
        policy: HandleFetchPolicy = HandleFetchPolicy(),  # noqa: B008 - frozen value
        *,
        resolver: Resolver = _system_resolver,
        connector: Connector = _pinned_https,
        clock: Callable[[], float] = time.monotonic,
        max_concurrent: int = 2,
    ) -> None:
        count: object = max_concurrent
        if not isinstance(count, int) or isinstance(count, bool):
            raise ValueError("max_concurrent must be an int")
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        self._policy = policy
        self._resolver = resolver
        self._connector = connector
        self._clock = clock
        self._slots = threading.BoundedSemaphore(max_concurrent)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._policy!r})"

    @contextmanager
    def open(self, url: str, *, max_bytes: int) -> Iterator[FetchedFileBody]:
        cap: object = max_bytes
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            raise ValueError("max_bytes must be a non-negative int")
        if not self._slots.acquire(blocking=False):
            raise FileWorkspaceUnavailableError()
        try:
            with self._fetch(url, max_bytes) as body:
                yield body
        finally:
            self._slots.release()

    @contextmanager
    def _fetch(self, url: str, max_bytes: int) -> Iterator[FetchedFileBody]:
        policy = self._policy
        start = self._clock()

        def remaining() -> float:
            return policy.deadline_seconds - (self._clock() - start)

        validated = _target(url, policy)
        del url  # nothing below may reach the URL itself
        if validated is None:
            raise _refused()
        host, target = validated
        pinned = self._resolve(host)

        conn: http.client.HTTPConnection | None = None
        expired = threading.Event()
        watchdog: threading.Timer | None = None
        state = _Body()
        failed = False
        try:
            budget = remaining()
            if budget <= 0:
                raise _refused()
            conn = self._connector(host, pinned, _PORT, min(policy.connect_timeout_seconds, budget))
            watchdog = _arm_watchdog(conn, budget, expired)
            conn.connect()
            _set_timeout(conn, policy.read_timeout_seconds, remaining())
            conn.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host)
            conn.putheader("User-Agent", _USER_AGENT)
            conn.putheader("Accept-Encoding", "identity")
            conn.endheaders()
            response = conn.getresponse()
            if expired.is_set() or remaining() <= 0 or response.status != 200:
                raise _refused()
            encoding = response.getheader("Content-Encoding")
            if encoding is not None and encoding.strip().lower() != "identity":
                raise _refused()
            transfer = response.msg.get_all("Transfer-Encoding") or []
            if transfer and [value.strip().lower() for value in transfer] != ["chunked"]:
                raise _refused()
            declared = _declared_length(response)
            if transfer and declared is not None:
                raise _refused()
        except FilesRefusal:
            failed = True
            if conn is not None:
                _close(conn)
            if watchdog is not None:
                watchdog.cancel()
            raise
        except Exception:
            failed = True
        if failed:
            if conn is not None:
                _close(conn)
            if watchdog is not None:
                watchdog.cancel()
            raise _refused() from None
        assert conn is not None  # noqa: S101 - narrowed by the try above
        assert watchdog is not None  # noqa: S101
        if declared is not None and declared > max_bytes:
            _close(conn)
            watchdog.cancel()
            raise _too_large()

        chunks = _stream(
            conn,
            response,
            declared=declared,
            max_bytes=max_bytes,
            read_timeout=policy.read_timeout_seconds,
            remaining=remaining,
            expired=expired,
            state=state,
        )
        try:
            yield FetchedFileBody(declared_length=declared, chunks=chunks)
        finally:
            state.closed = True
            chunks.close()
            _close(conn)
            watchdog.cancel()

    def _resolve(self, host: str) -> str:
        """Resolve once, judge every answer, return the first. Raises refusals only."""
        failed = False
        addresses: list[str] = []
        try:
            answer = self._resolver(host, _PORT)
            if isinstance(answer, str | bytes):
                failed = True
            else:
                addresses = list(answer)
        except Exception:
            failed = True
        if failed or not addresses:
            raise _refused() from None
        if not all(_is_public_answer(a) for a in addresses):
            raise _refused()
        return addresses[0]


class _Body:
    """Mutable per-fetch state shared between the context manager and the stream."""

    __slots__ = ("closed",)

    def __init__(self) -> None:
        self.closed = False


def _arm_watchdog(
    conn: http.client.HTTPConnection, seconds: float, expired: threading.Event
) -> threading.Timer:
    def fire() -> None:
        expired.set()
        sock = conn.sock
        if sock is not None:
            # The base-class method on the descriptor: `SSLSocket.shutdown`
            # would also drop its SSL object under a reader in another thread.
            with suppress(OSError):
                socket.socket.shutdown(sock, socket.SHUT_RDWR)

    timer = threading.Timer(seconds, fire)
    timer.daemon = True
    timer.start()
    return timer


def _set_timeout(conn: http.client.HTTPConnection, read_timeout: float, budget: float) -> None:
    if budget <= 0:
        raise _refused()
    sock = conn.sock
    if sock is not None:
        sock.settimeout(min(read_timeout, budget))


def _close(conn: http.client.HTTPConnection) -> None:
    with suppress(Exception):  # closing is best effort; nothing may surface
        conn.close()


def _stream(
    conn: http.client.HTTPConnection,
    response: http.client.HTTPResponse,
    *,
    declared: int | None,
    max_bytes: int,
    read_timeout: float,
    remaining: Callable[[], float],
    expired: threading.Event,
    state: _Body,
) -> Generator[bytes]:
    """Yield the body in `read1` pieces, refusing past the cap or the deadline."""
    total = 0
    while True:
        if state.closed or expired.is_set():
            raise _refused()
        failed = False
        chunk = b""
        try:
            _set_timeout(conn, read_timeout, remaining())
            chunk = response.read1(min(_CHUNK, max_bytes - total + 1))
        except Exception:
            failed = True
        if failed:
            raise _refused() from None
        if not chunk:
            if expired.is_set() or state.closed:
                raise _refused()
            if declared is not None and total != declared:
                raise _refused()
            return
        total += len(chunk)
        if total > max_bytes:
            raise _too_large()
        if declared is not None and total > declared:
            raise _refused()
        yield chunk
