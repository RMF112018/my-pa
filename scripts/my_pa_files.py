#!/usr/bin/env python3
"""Reference client for the files byte routes (files-workspace contract section 10).

    MY_PA_FILES_TICKET=... python scripts/my_pa_files.py upload LOCAL \\
        --origin https://<remote MCP host> --route /files/v1/uploads/<id>
    MY_PA_FILES_TICKET=... python scripts/my_pa_files.py download OUT \\
        --origin https://<remote MCP host> --route /files/v1/downloads/<id>

Standard library only. It does **not** speak MCP: the caller first invokes
`files.upload.begin` or `files.download.begin` and passes the returned `route`
here, with the returned `upload_token` / `download_token` as the ticket.

**The ticket.** Read from the `MY_PA_FILES_TICKET` environment variable or from
`--token-file` (one line), never from a command-line value, so it does not land
in shell history or a process listing. It is sent only as
`Authorization: Bearer`, never in a URL, and is never printed or logged; error
messages carry an HTTP status and the server's `{error, reason}` codes only.

**Upload.** HEAD for the server's offset, then PATCH chunks of at most
`--chunk-bytes` (default and ceiling 32 MiB, the server's per-request bound)
from that offset. The last PATCH carries
`Upload-Complete: sha256=<hex>, length=<n>` (an empty PATCH for a zero-byte
file), computed over the whole local file before sending. A dropped
connection, 408, 503 or 409 `offset_mismatch` re-reads HEAD and resumes. The
finalize JSON result is printed on stdout.

**Download.** Refuses an existing OUT unless `--overwrite`. Bytes go to
`OUT.part`; a partial `.part` whose recorded ETag (`OUT.part.etag`) matches the
server's is resumed with `Range` (and `If-Match`), anything else restarts from
zero. The whole file is then checked against `X-Content-SHA256` (when the
server sends it) and `--sha256` (when given), fsynced, and moved into place:
with `--overwrite` by `os.replace`, otherwise without clobbering (a hard link
that fails if OUT now exists), so an OUT that appeared during the download is
exit 1 with the verified bytes kept in `OUT.part`. A mismatch deletes the
`.part` and fails.

Memory is bounded by one 1 MiB block in both directions.

Exit status:

- 0  done;
- 1  a local problem (bad arguments, missing ticket, OUT exists, I/O error);
- 3  the server refused (401, 403, 409, 412, 413, 416, 422, 507, ...);
- 4  the downloaded bytes do not match the expected SHA-256 (nothing kept);
- 5  outcome unknown: a completing PATCH lost its response and the ticket now
     answers 401, so the finalize may have committed. Verify with `files.stat`
     (or `files.list`) before beginning a new upload;
- 6  the transport kept failing after `--retries` attempts.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import ipaddress
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import BinaryIO, Final, NoReturn
from urllib.parse import urlsplit

TOKEN_ENV: Final = "MY_PA_FILES_TICKET"  # noqa: S105 - a variable name, not a secret
UPLOADS_PREFIX: Final = "/files/v1/uploads/"
DOWNLOADS_PREFIX: Final = "/files/v1/downloads/"
#: Contract section 8: the largest body one PATCH may carry.
MAX_CHUNK_BYTES: Final = 32 * 1024 * 1024
BLOCK_BYTES: Final = 1024 * 1024
MAX_ERROR_BODY: Final = 4096
MAX_BACKOFF_SECONDS: Final = 30.0

EXIT_OK: Final = 0
EXIT_LOCAL: Final = 1
EXIT_REFUSED: Final = 3
EXIT_DIGEST: Final = 4
EXIT_UNKNOWN: Final = 5
EXIT_TRANSPORT: Final = 6

_TOKEN_LIKE: Final = re.compile(r"gfwtk_\S*")
_TOKEN: Final = re.compile(r"\Agfwtk_[0-9a-f]{64}\Z")
_ID: Final = re.compile(r"\A[^/?#\s]+\Z")
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_CONTENT_RANGE: Final = re.compile(r"\Abytes ([0-9]+)-([0-9]+)/([0-9]+)\Z")
_UNSATISFIED_RANGE: Final = re.compile(r"\Abytes \*/([0-9]+)\Z")
_DIGITS: Final = re.compile(r"\A[0-9]{1,19}\Z")
#: A server error or reason code is echoed only when it is a plain token.
_CODE: Final = re.compile(r"\A[a-z_]{1,40}\Z")

_TRANSPORT_ERRORS: Final = (OSError, http.client.HTTPException)


class ClientError(Exception):
    """A failure with an exit status and a message that names no secret."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _Retry(Exception):  # noqa: N818 - internal control signal
    """Re-read the server's state and try again (counts as one attempt)."""

    def __init__(self, delay: float | None = None) -> None:
        super().__init__()
        self.delay = delay


# ---- target and ticket --------------------------------------------------------


class Target:
    """Where the requests go: scheme, host, port and the route path. No query."""

    def __init__(self, origin: str, route: str, prefix: str, timeout: float) -> None:
        base = urlsplit(origin)
        if base.scheme not in ("https", "http") or not base.hostname:
            raise ClientError(EXIT_LOCAL, "--origin must be an https:// URL")
        if base.query or base.fragment or base.username or base.password:
            raise ClientError(EXIT_LOCAL, "--origin must not carry credentials, query or fragment")
        if base.path not in ("", "/"):
            raise ClientError(EXIT_LOCAL, "--origin must not carry a path")
        if base.scheme == "http" and not _loopback(base.hostname):
            raise ClientError(EXIT_LOCAL, "--origin must be https:// (http only for loopback)")
        if "?" in route or "#" in route:
            raise ClientError(EXIT_LOCAL, "--route must not carry a query string or fragment")
        parsed = urlsplit(route)
        if (parsed.scheme or parsed.netloc) and (
            parsed.scheme != base.scheme
            or parsed.hostname != base.hostname
            or parsed.port != base.port
        ):
            raise ClientError(EXIT_LOCAL, "--route names a different host than --origin")
        path = parsed.path
        if not path.startswith(prefix) or _ID.match(path[len(prefix) :]) is None:
            raise ClientError(EXIT_LOCAL, f"--route must be {prefix}<id>")
        self.scheme = base.scheme
        self.host = base.hostname
        self.port = base.port
        self.path = path
        self.timeout = timeout

    def connect(self) -> http.client.HTTPConnection:
        if self.scheme == "https":
            return http.client.HTTPSConnection(self.host, self.port, timeout=self.timeout)
        return http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_ticket(token_file: Path | None, environ: Mapping[str, str]) -> str:
    """The ticket from `--token-file` or the environment; validated, never echoed."""
    if token_file is not None:
        try:
            raw = token_file.read_text(encoding="ascii").strip()
        except (OSError, UnicodeDecodeError):
            raise ClientError(EXIT_LOCAL, "the --token-file could not be read") from None
    else:
        raw = environ.get(TOKEN_ENV, "").strip()
        if not raw:
            raise ClientError(EXIT_LOCAL, f"no ticket: set {TOKEN_ENV} or pass --token-file")
    if _TOKEN.match(raw) is None:
        raise ClientError(EXIT_LOCAL, "the ticket is not a files ticket token")
    return raw


# ---- HTTP plumbing ------------------------------------------------------------


def _refusal(response: http.client.HTTPResponse) -> str:
    """`HTTP <status> <error>/<reason>` from a bounded read of the JSON body."""
    text = f"HTTP {response.status}"
    try:
        document = json.loads(response.read(MAX_ERROR_BODY))
    except (ValueError, *_TRANSPORT_ERRORS):
        return text
    if not isinstance(document, dict):
        return text
    code, reason = document.get("error"), document.get("reason")
    if isinstance(code, str) and _CODE.match(code):
        text += f" {code}"
        if isinstance(reason, str) and _CODE.match(reason):
            text += f"/{reason}"
    return text


def _retry_after(response: http.client.HTTPResponse) -> float | None:
    raw = response.getheader("Retry-After")
    if raw is not None and _DIGITS.match(raw.strip()):
        return min(float(raw.strip()), MAX_BACKOFF_SECONDS)
    return None


def _header_int(response: http.client.HTTPResponse, name: str) -> int | None:
    raw = response.getheader(name)
    if raw is None or _DIGITS.match(raw.strip()) is None:
        return None
    return int(raw.strip())


@contextmanager
def _send(
    target: Target,
    method: str,
    headers: Mapping[str, str],
    body: Callable[[http.client.HTTPConnection], None] | None = None,
) -> Iterator[http.client.HTTPResponse]:
    """One request on a fresh connection, closed on exit. A body send that fails
    still reads a response if the server answered early (it refuses before
    reading the body)."""
    connection = target.connect()
    try:
        connection.putrequest(method, target.path, skip_accept_encoding=True)
        for name, value in headers.items():
            connection.putheader(name, value)
        connection.endheaders()
        if body is not None:
            with suppress(OSError):
                body(connection)
        yield connection.getresponse()
    finally:
        connection.close()


def _attempts(
    retries: int,
    backoff: float,
    step: Callable[[], int],
    on_transport_failure: Callable[[], None] = lambda: None,
    progress: Callable[[], int] = lambda: 0,
) -> int:
    """Run `step` until it returns, retrying transport failures and `_Retry`.

    `retries` bounds consecutive attempts that moved no byte: an attempt after
    which `progress()` grew resets the count and the backoff, so a long transfer
    over a flaky link is not cut off by failures spread across its length.
    """
    delay = backoff
    failures = 0
    mark = progress()
    while True:
        try:
            return step()
        except _Retry as again:
            wait = again.delay if again.delay is not None else delay
        except _TRANSPORT_ERRORS:
            on_transport_failure()
            wait = delay
        now = progress()
        if now > mark:
            mark, failures, delay = now, 0, backoff
        else:
            failures += 1
        if failures > retries:
            raise ClientError(EXIT_TRANSPORT, f"gave up after {failures} attempts with no progress")
        time.sleep(wait)
        delay = min(max(delay * 2, 0.0), MAX_BACKOFF_SECONDS)


# ---- upload -------------------------------------------------------------------


def file_sha256(handle: BinaryIO) -> tuple[str, int]:
    handle.seek(0)
    digest = hashlib.sha256()
    length = 0
    while block := handle.read(BLOCK_BYTES):
        digest.update(block)
        length += len(block)
    return digest.hexdigest(), length


def upload(
    local: Path,
    target: Target,
    token: str,
    *,
    chunk_bytes: int = MAX_CHUNK_BYTES,
    retries: int = 5,
    backoff: float = 1.0,
) -> dict[str, object]:
    """Send `local` to the upload route; the finalize result."""
    if not 1 <= chunk_bytes <= MAX_CHUNK_BYTES:
        raise ClientError(EXIT_LOCAL, f"--chunk-bytes must be 1..{MAX_CHUNK_BYTES}")
    try:
        handle = local.open("rb")
    except OSError:
        raise ClientError(EXIT_LOCAL, "the local file could not be opened") from None
    with handle:
        sha256, size = file_sha256(handle)
        completion = f"sha256={sha256}, length={size}"
        auth = {"Authorization": f"Bearer {token}"}
        state = {"completing": False, "unconfirmed": False}
        sent = [0]  # the highest offset the server has acknowledged

        def unauthorized() -> ClientError:
            if state["unconfirmed"]:
                return ClientError(
                    EXIT_UNKNOWN,
                    "outcome unknown: the completing request lost its response and the "
                    "ticket is now closed; verify with files.stat before retrying",
                )
            return ClientError(EXIT_REFUSED, "upload refused: HTTP 401 denied/ticket_invalid")

        def head() -> int:
            with _send(target, "HEAD", auth) as response:
                response.read()
                if response.status == 204:
                    offset = _header_int(response, "Upload-Offset")
                    if offset is None or offset > size:
                        raise ClientError(EXIT_REFUSED, "the server reported an impossible offset")
                    sent[0] = max(sent[0], offset)
                    return offset
                if response.status == 401:
                    raise unauthorized()
                if response.status in (408, 503):
                    raise _Retry(_retry_after(response))
                raise ClientError(EXIT_REFUSED, f"upload refused: HTTP {response.status}")

        def patch(offset: int) -> tuple[int, dict[str, object] | None]:
            length = min(chunk_bytes, size - offset)
            last = offset + length == size
            headers = {
                **auth,
                "Upload-Offset": str(offset),
                "Content-Length": str(length),
                "Content-Type": "application/offset+octet-stream",
            }
            if last:
                headers["Upload-Complete"] = completion

            def body(connection: http.client.HTTPConnection) -> None:
                handle.seek(offset)
                left = length
                while left:
                    block = handle.read(min(BLOCK_BYTES, left))
                    if not block:
                        raise ClientError(EXIT_LOCAL, "the local file shrank while uploading")
                    connection.send(block)
                    left -= len(block)

            state["completing"] = last
            with _send(target, "PATCH", headers, body) as response:
                status = response.status
                if status == 204:
                    response.read()
                    moved = _header_int(response, "Upload-Offset")
                    if moved != offset + length or last:
                        raise _Retry(0.0)
                    sent[0] = max(sent[0], moved)
                    return moved, None
                if status == 200 and last:
                    try:
                        result = json.loads(response.read())
                    except ValueError:
                        result = None
                    if not isinstance(result, dict):
                        raise ClientError(
                            EXIT_UNKNOWN,
                            "the finalize answered 200 with an unreadable result; "
                            "verify with files.stat",
                        )
                    return size, result
                if status == 401:
                    response.read(MAX_ERROR_BODY)
                    raise unauthorized()
                if status in (408, 503):
                    delay = _retry_after(response)
                    response.read(MAX_ERROR_BODY)
                    raise _Retry(delay)
                message = _refusal(response)
                if status == 409 and message.endswith("/offset_mismatch"):
                    raise _Retry(0.0)
                raise ClientError(EXIT_REFUSED, f"upload refused: {message}")

        result: dict[str, object] = {}

        def step() -> int:
            offset = head()
            while True:
                offset, finished = patch(offset)
                if finished is not None:
                    result.update(finished)
                    return EXIT_OK

        def lost() -> None:
            if state["completing"]:
                state["unconfirmed"] = True

        _attempts(retries, backoff, step, lost, lambda: sent[0])
        return result


# ---- download -----------------------------------------------------------------


def _discard(*paths: Path) -> None:
    for path in paths:
        with suppress(FileNotFoundError):
            path.unlink()


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _publish_no_clobber(part: Path, out: Path) -> None:
    """Move the verified `part` to `out` unless something now holds `out`.

    The early `OUT exists` check runs before the download; a file that appears
    at `out` while the bytes arrive must not be replaced silently. A hard link
    is created only when `out` is free (`FileExistsError` otherwise), then the
    part is unlinked. Where the filesystem has no hard links, `out` is reserved
    with `O_CREAT | O_EXCL` and the part replaces that reservation atomically;
    if that replace fails, the empty reservation is removed before the error
    propagates, so no 0-byte `out` is left behind. On a conflict `OUT.part`
    (and its `.etag` marker) are kept for inspection and the client exits 1
    (`EXIT_LOCAL`).
    """
    conflict = ClientError(
        EXIT_LOCAL,
        "OUT appeared during the download; the verified bytes are kept in OUT.part",
    )
    try:
        os.link(part, out, follow_symlinks=False)
    except FileExistsError:
        raise conflict from None
    except (OSError, NotImplementedError):  # no hard links: reserve the name, replace it
        try:
            os.close(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        except FileExistsError:
            raise conflict from None
        try:
            part.replace(out)
        except BaseException:
            out.unlink(missing_ok=True)  # the reservation is ours and still empty
            raise
        return
    part.unlink()


def download(
    out: Path,
    target: Target,
    token: str,
    *,
    overwrite: bool = False,
    expected_sha256: str | None = None,
    retries: int = 5,
    backoff: float = 1.0,
) -> dict[str, object]:
    """Fetch the download route into `out`, resuming `out.part`; a short summary."""
    if expected_sha256 is not None and _SHA256.match(expected_sha256) is None:
        raise ClientError(EXIT_LOCAL, "--sha256 must be 64 lower-case hex characters")
    if os.path.lexists(out) and not overwrite:
        raise ClientError(EXIT_LOCAL, "OUT exists; pass --overwrite to replace it")
    part = out.with_name(out.name + ".part")
    #: The resumable part's identity: the server's ETag and X-Content-SHA256.
    marker = out.with_name(out.name + ".part.etag")
    auth = {"Authorization": f"Bearer {token}"}
    seen: dict[str, str | None] = {"etag": None, "sha256": None}

    def recorded() -> dict[str, str | None]:
        try:
            document = json.loads(marker.read_text(encoding="ascii"))
        except (OSError, ValueError):
            return {"etag": None, "sha256": None}
        if not isinstance(document, dict):
            return {"etag": None, "sha256": None}
        return {
            key: value if isinstance(value, str) else None
            for key, value in ((k, document.get(k)) for k in ("etag", "sha256"))
        }

    def step() -> int:
        previous = recorded()
        etag = previous["etag"]
        have = part.stat().st_size if etag is not None and part.is_file() else 0
        headers = dict(auth)
        if have and etag is not None:
            headers["Range"] = f"bytes={have}-"
            headers["If-Match"] = etag
        with _send(target, "GET", headers) as response:
            status = response.status
            if status in (408, 503):
                delay = _retry_after(response)
                response.read(MAX_ERROR_BODY)
                raise _Retry(delay)
            if status == 416 and have:
                response.read(MAX_ERROR_BODY)
                full = _UNSATISFIED_RANGE.match(response.getheader("Content-Range") or "")
                if full is not None and int(full.group(1)) == have:
                    seen.update(previous)  # the part already holds every byte
                    return EXIT_OK
                _discard(part, marker)
                raise _Retry(0.0)
            if status not in (200, 206):
                message = _refusal(response)
                if status == 412:
                    _discard(part, marker)
                raise ClientError(EXIT_REFUSED, f"download refused: {message}")
            seen["etag"] = response.getheader("ETag")
            seen["sha256"] = response.getheader("X-Content-SHA256")
            length = _header_int(response, "Content-Length")
            if length is None:
                raise ClientError(EXIT_REFUSED, "the server sent no Content-Length")
            start = 0
            if status == 206:
                matched = _CONTENT_RANGE.match(response.getheader("Content-Range") or "")
                if matched is None or int(matched.group(1)) != have or seen["etag"] != etag:
                    _discard(part, marker)
                    raise _Retry(0.0)
                start = have
            elif seen["etag"]:
                marker.write_text(json.dumps(seen), encoding="ascii")
            else:
                _discard(marker)  # no ETag: a later failure restarts from zero
            flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(part, flags, 0o600), "r+b") as sink:
                sink.truncate(start)
                sink.seek(start)
                received = 0
                while received < length:
                    block = response.read(min(BLOCK_BYTES, length - received))
                    if not block:
                        break
                    sink.write(block)
                    received += len(block)
                sink.flush()
                os.fsync(sink.fileno())
            if received != length:
                raise http.client.IncompleteRead(b"", length - received)
            return EXIT_OK

    def held() -> int:
        try:
            return part.stat().st_size
        except OSError:
            return 0

    _attempts(retries, backoff, step, progress=held)
    with part.open("rb") as handle:
        actual, size = file_sha256(handle)
    for expected in (seen["sha256"], expected_sha256):
        if expected is not None and expected.lower() != actual:
            _discard(part, marker)
            raise ClientError(EXIT_DIGEST, "the downloaded bytes do not match the expected SHA-256")
    if overwrite:
        part.replace(out)  # atomic within the directory
    else:
        _publish_no_clobber(part, out)
    _discard(marker)
    _fsync_directory(out.parent)
    return {"bytes": size, "sha256": actual, "server_sha256_checked": seen["sha256"] is not None}


# ---- command line -------------------------------------------------------------


class _Parser(argparse.ArgumentParser):
    """argparse echoes unrecognized arguments; a ticket pasted there is masked."""

    def error(self, message: str) -> NoReturn:
        super().error(_TOKEN_LIKE.sub("gfwtk_<redacted>", message))


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="my_pa_files.py",
        allow_abbrev=False,
        description="Upload or download through the my-pa files byte routes.",
        epilog=f"The ticket comes from ${TOKEN_ENV} or --token-file, never the command line.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("upload", "download"):
        # No abbreviations: `--token <value>` must not be read as `--token-file`.
        command = commands.add_parser(name, allow_abbrev=False)
        if name == "upload":
            command.add_argument("local", type=Path, help="the local file to send")
        command.add_argument("--origin", required=True, help="https://<remote MCP host>")
        command.add_argument("--route", required=True, help="the begin result's route")
        if name == "download":
            command.add_argument("out", type=Path, help="where to write the file")
            command.add_argument("--overwrite", action="store_true")
            command.add_argument("--sha256", help="also require this SHA-256 (hex)")
        else:
            command.add_argument("--chunk-bytes", type=int, default=MAX_CHUNK_BYTES)
        command.add_argument("--token-file", type=Path, help="a file holding the ticket")
        command.add_argument("--retries", type=int, default=5)
        command.add_argument("--backoff-seconds", type=float, default=1.0)
        command.add_argument("--timeout", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.retries < 0 or args.backoff_seconds < 0 or args.timeout <= 0:
            raise ClientError(EXIT_LOCAL, "--retries, --backoff-seconds and --timeout must be >= 0")
        token = read_ticket(args.token_file, os.environ if environ is None else environ)
        if args.command == "upload":
            target = Target(args.origin, args.route, UPLOADS_PREFIX, args.timeout)
            result = upload(
                args.local,
                target,
                token,
                chunk_bytes=args.chunk_bytes,
                retries=args.retries,
                backoff=args.backoff_seconds,
            )
        else:
            target = Target(args.origin, args.route, DOWNLOADS_PREFIX, args.timeout)
            result = download(
                args.out,
                target,
                token,
                overwrite=args.overwrite,
                expected_sha256=args.sha256,
                retries=args.retries,
                backoff=args.backoff_seconds,
            )
    except ClientError as error:
        print(f"my_pa_files: {error}", file=sys.stderr)
        return error.status
    except OSError as error:
        print(f"my_pa_files: local I/O error ({type(error).__name__})", file=sys.stderr)
        return EXIT_LOCAL
    print(json.dumps(result, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
