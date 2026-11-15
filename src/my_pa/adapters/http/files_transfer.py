"""The files byte routes on the remote MCP process (files-workspace contract section 10).

Three exchanges, appended to `create_remote_mcp_app(..., additional_routes=...)`
only when the files plane is composed, and never mounted on the private HTTP
gateway:

- `HEAD /files/v1/uploads/{id}`: 204, `Upload-Offset`, `Upload-Length` (if declared);
- `PATCH /files/v1/uploads/{id}`: the raw body appended at `Upload-Offset`, 204
  with the new offset; with `Upload-Complete: sha256=<hex>, length=<n>`, then
  `files.upload.finalize` through `ApplicationService.invoke`, 200 and its result;
- `GET /files/v1/downloads/{id}`: the file, or one `Range: bytes=a-b` of it (206).

This module maps HTTP to `application.file_transfer.FileTransferGate` and back;
the gate decides. The rules the transport itself owns:

- **Before any body byte:** a query string is 400; the ticket is authenticated
  and the client's grants re-read (401 `ticket_invalid`, 403 `denied`); a
  declared `Content-Length` over 32 MiB, or past what the ticket may still
  hold, is 413 `too_large`; the offset must match (409 `offset_mismatch`,
  carrying the current `Upload-Offset`).
- **Authentication first.** Every request is authenticated before it takes a
  slot or waits on an upload's lock: a request without a ticket-shaped bearer
  is answered on the loop, any other is checked in a worker thread (the
  loop's default executor), and a refused one is answered then -- it never
  holds a slot or queues behind an upload. A PATCH authenticates again once
  it holds the upload's lock, since the ticket or the offset may change while
  it waits.
- **Bounded authentication.** The pre-slot check has its own per-process cap
  (default twice the slot count), separate from the `/mcp` `auth_slots`: it
  is taken without waiting, so a request that finds none free is the same 503
  `unavailable` with `Retry-After` as a full slot count, and nothing queues on
  the shared default executor. A permit is returned when its worker thread
  returns, not when the request is cancelled, so a client that disconnects
  mid-check frees nothing early and leaks nothing. The PATCH re-check under the
  lock and a download's periodic re-check run while the request already holds
  a slot, so they are bounded by the slot count and do not take a permit (no
  request ever waits on both): worker threads in flight stay at most the auth
  cap plus the slot count.
- **Concurrency.** Its own per-process slot count (default 4), separate from
  the `/mcp` semaphores: an authenticated request that finds none free is 503
  with `Retry-After` and nothing read. Concurrent PATCHes of one upload are
  serialized by a per-upload lock, behind the store's offset check and the
  row's offset CAS.
- **Off the event loop.** Every store and database call runs in a worker
  thread. The body is bridged into that thread one chunk at a time
  (`_BodyChunks`: the thread asks the loop for the next chunk and waits for it),
  so memory is bounded by one server chunk and there is no queue. Each wait is
  bounded by `body_idle_timeout_seconds` and the whole PATCH by
  `patch_deadline_seconds` (408 when either passes); a thread the request no
  longer waits for keeps its slot and its upload lock until it returns.
- **Bounded downloads.** Each send of a GET's response is bounded by the same
  idle bound (a reader that stops reading), the whole stream by
  `download_deadline_seconds`, and the ticket and grants are re-checked every
  `download_recheck_seconds` between chunks, so an expiry or a revocation
  stops the stream. A stream stopped for any of these reasons (or because the
  file changed) ends short of `Content-Length` and the connection is closed;
  the client resumes with `Range`.
- **Privacy.** Nothing here logs. Errors are JSON `{error, reason}` -- a public
  code and a section 7 token or `null` -- and never carry a token, a path or a
  body byte. The interaction log wraps `/mcp` only, so these routes are not
  recorded.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import re
import sys
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any, Final, TextIO, TypeVar

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import BaseRoute, Route
from starlette.types import Message, Receive, Scope, Send

from my_pa.application.errors import ApplicationError, DeniedError
from my_pa.application.file_transfer import (
    FileTransferAccess,
    FileTransferGate,
    UploadOffsetMismatch,
)
from my_pa.contracts.ports import FileTransferKind, FileWorkspaceUnavailableError
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.files.errors import (
    FilesArgumentError,
    FilesRefusal,
    RangeNotSatisfiableError,
)
from my_pa.domain.files.transfer import (
    UploadCompletion,
    content_disposition,
    parse_browser_link,
    parse_range,
    parse_upload_complete,
    parse_upload_offset,
    ticket_token_from_authorization,
)
from my_pa.domain.files.vocabulary import FilesReason

__all__ = [
    "AUTH_SLOTS_PER_TRANSFER_SLOT",
    "BODY_IDLE_TIMEOUT_SECONDS",
    "BROWSER_DOWNLOADS_PATH",
    "DOWNLOADS_PATH",
    "DOWNLOAD_DEADLINE_SECONDS",
    "DOWNLOAD_RECHECK_SECONDS",
    "MAX_CONCURRENT_TRANSFERS",
    "PATCH_DEADLINE_SECONDS",
    "UPLOADS_PATH",
    "build_file_transfer_routes",
]

UPLOADS_PATH: Final = "/files/v1/uploads/"
DOWNLOADS_PATH: Final = "/files/v1/downloads/"
#: Contract section 17.6: the single-use browser link route.
BROWSER_DOWNLOADS_PATH: Final = "/files/v1/browser-downloads/"
#: Section 17.6: the operator's completion line (no path, no token).
BROWSER_LOGGER: Final = logging.getLogger("my_pa.files.browser_download")
#: Section 17.6: every browser refusal is these same bytes.
_BROWSER_HEADERS: Final = {
    "Content-Type": "application/octet-stream",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "sandbox",
}
#: Contract section 8: the byte routes' own per-process cap.
MAX_CONCURRENT_TRANSFERS: Final = 4
#: The longest one wait for the next body chunk may take, the remote MCP
#: `call_timeout_seconds` default: a stalled client releases its slot then.
BODY_IDLE_TIMEOUT_SECONDS: Final = 30.0
#: The longest one PATCH may stream: 32 MiB at about 56 KiB/s. A slow-drip
#: client that never idles past the bound above still cannot hold a slot longer.
PATCH_DEADLINE_SECONDS: Final = 600.0
#: The longest one GET may stream, the PATCH deadline's twin: a slow reader of
#: a large file is cut there and resumes with `Range` (the reference client does).
DOWNLOAD_DEADLINE_SECONDS: Final = 600.0
#: How often a streaming GET re-reads its ticket and grants (one short unit of
#: work), so an expiry or a revocation stops it within about this long.
DOWNLOAD_RECHECK_SECONDS: Final = 5.0
RETRY_AFTER_SECONDS: Final = 1
#: The pre-slot authentication cap per transfer slot: a flood of well-formed
#: bogus tickets holds at most this many default-executor threads per slot.
AUTH_SLOTS_PER_TRANSFER_SLOT: Final = 2

_NO_STORE: Final = {"Cache-Control": "no-store"}
_CONTENT_LENGTH: Final = re.compile(r"\A(?:0|[1-9][0-9]{0,18})\Z")

#: Contract section 7: each reason token's public code and byte-route status.
#: The four tokens with no section 7 status take their code's status.
_REASONS: Final[dict[FilesReason, tuple[str, int]]] = {
    FilesReason.INVALID_PATH: ("invalid_request", 400),
    FilesReason.NOT_FOUND: ("not_found", 404),
    FilesReason.EXISTS: ("conflict", 409),
    FilesReason.VERSION_CONFLICT: ("conflict", 409),
    FilesReason.EXTERNAL_CHANGE_DETECTED: ("conflict", 412),
    FilesReason.UNSUPPORTED_ENTRY: ("unsupported", 422),
    FilesReason.TOO_LARGE: ("invalid_request", 413),
    FilesReason.QUOTA: ("unavailable", 507),
    FilesReason.DIGEST_MISMATCH: ("conflict", 409),
    FilesReason.OFFSET_MISMATCH: ("conflict", 409),
    FilesReason.TICKET_INVALID: ("denied", 401),
}
#: A public error code's status when no reason token names one.
_CODES: Final[dict[str, int]] = {
    "invalid_request": 400,
    "ambiguous_request": 400,
    "denied": 403,
    "unavailable": 503,
    "unsupported": 422,
    "not_found": 404,
    "conflict": 409,
    "rate_limited": 429,
    "quarantined": 409,
    "cancelled": 409,
    "internal_error": 500,
}

_T = TypeVar("_T")


def _error(
    code: str, reason: str | None, status: int, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        {"error": code, "reason": reason},
        status_code=status,
        headers={**_NO_STORE, **(headers or {})},
    )


def _refusal(reason: FilesReason, headers: dict[str, str] | None = None) -> JSONResponse:
    code, status = _REASONS[reason]
    return _error(code, reason.value, status, headers)


def _busy() -> JSONResponse:
    return _error("unavailable", None, 503, {"Retry-After": str(RETRY_AFTER_SECONDS)})


def _failure(error: BaseException) -> JSONResponse:
    """The one JSON answer for anything the gate or the store raised; names no value."""
    if isinstance(error, UploadOffsetMismatch):
        return _refusal(error.reason, {"Upload-Offset": str(error.current)})
    if isinstance(error, FilesRefusal):
        return _refusal(error.reason)
    if isinstance(error, FilesArgumentError):
        return _error("invalid_request", None, 400)
    if isinstance(error, DeniedError):
        return _error("denied", None, 403)
    if isinstance(error, FileWorkspaceUnavailableError):
        return _error("unavailable", None, 503)
    if isinstance(error, _AuthBusy):
        return _busy()
    if isinstance(error, _BodyTimeout):
        return _error("unavailable", None, 408)
    if isinstance(error, TimeoutError):  # the upload's lock stayed held past the idle bound
        return _error("unavailable", None, 503, {"Retry-After": str(RETRY_AFTER_SECONDS)})
    if isinstance(error, ApplicationError):
        code = error.code.value
        return _error(code, None, _CODES.get(code, 500))
    return _error("internal_error", None, 500)


def _envelope_answer(envelope: ResponseEnvelope) -> JSONResponse:
    """A finalize envelope as HTTP: 200 and its result, or its refusal's status."""
    document = envelope.to_canonical_dict()
    if envelope.error is None:
        return JSONResponse(document["result"], status_code=200, headers=_NO_STORE)
    error = document["error"]
    code = str(error.get("code", "internal_error"))
    for detail in error.get("safe_details") or ():
        try:
            reason = FilesReason(detail)
        except ValueError:
            continue
        return _error(code, reason.value, _REASONS[reason][1])
    return _error(code, None, _CODES.get(code, 500))


class _BodyTimeout(Exception):  # noqa: N818 - internal signal, never rendered
    """The body stalled past the idle bound or the PATCH passed its deadline."""


class _AuthBusy(Exception):  # noqa: N818 - internal signal, rendered as `_busy()`
    """Every pre-slot authentication permit is in use."""


class _StreamStopped(Exception):  # noqa: N818 - internal signal, never rendered
    """A download stream ends short: its deadline, a re-check or a read refused it."""


async def _next_chunk(stream: AsyncIterator[bytes]) -> bytes | None:
    """The next body chunk, on the loop; `None` at the end."""
    try:
        return await anext(stream)
    except StopAsyncIteration:
        return None


class _BodyChunks:
    """The request body as a synchronous iterable, for the store's worker thread.

    Each step schedules one `_next_chunk` on the loop and waits for it, so at
    most one chunk is in flight and nothing is buffered beyond it. A wait past
    the idle bound, or a step after the deadline, is `_BodyTimeout`.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        stream: AsyncIterator[bytes],
        *,
        idle_seconds: float,
        deadline: float,
    ) -> None:
        self._loop = loop
        self._stream = stream
        self._idle = idle_seconds
        self._deadline = deadline

    def __iter__(self) -> Iterator[bytes]:
        while True:
            remaining = self._deadline - time.monotonic()
            if remaining <= 0:
                raise _BodyTimeout
            future = asyncio.run_coroutine_threadsafe(_next_chunk(self._stream), self._loop)
            try:
                chunk = future.result(timeout=min(self._idle, remaining))
            except concurrent.futures.TimeoutError:
                future.cancel()
                raise _BodyTimeout from None
            if chunk is None:
                return
            if chunk:
                yield chunk


class _Held:
    """What one request holds -- its slot, its upload lock -- until its last thread ends."""

    __slots__ = ("lock", "releases", "running")

    def __init__(self) -> None:
        self.releases: list[Callable[[], None]] = []
        self.running: asyncio.Future[Any] | None = None
        self.lock: asyncio.Lock | None = None

    def release(self) -> None:
        def free(_done: object = None) -> None:
            for release in reversed(self.releases):
                release()
            self.releases.clear()

        if self.running is not None and not self.running.done():
            self.running.add_done_callback(free)
        else:
            free()


def _content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    if _CONTENT_LENGTH.match(raw) is None:
        raise FilesArgumentError("Content-Length", "pattern")
    return int(raw)


class _FileTransferEndpoint:
    """One ASGI endpoint for both routes of one kind (see the module docstring)."""

    def __init__(
        self,
        gate: FileTransferGate,
        kind: FileTransferKind,
        *,
        slots: list[int],
        auth_slots: list[int],
        upload_locks: dict[str, tuple[asyncio.Lock, int]],
        body_idle_timeout_seconds: float,
        patch_deadline_seconds: float,
        download_deadline_seconds: float,
        download_recheck_seconds: float,
    ) -> None:
        self._gate = gate
        self._kind = kind
        self._slots = slots
        self._auth_slots = auth_slots
        self._locks = upload_locks
        self._idle = body_idle_timeout_seconds
        self._deadline = patch_deadline_seconds
        self._download_deadline = download_deadline_seconds
        self._recheck = download_recheck_seconds

    # ---- shared plumbing --------------------------------------------------------

    def _take_slot(self, held: _Held) -> bool:
        """Non-blocking: one of the free slots, or `False` (the loop is one thread)."""
        if self._slots[0] <= 0:
            return False
        self._slots[0] -= 1

        def give() -> None:
            self._slots[0] += 1

        held.releases.append(give)
        return True

    def _lock_for(self, upload_id: str, held: _Held) -> asyncio.Lock:
        lock, users = self._locks.get(upload_id, (asyncio.Lock(), 0))
        self._locks[upload_id] = (lock, users + 1)

        def forget() -> None:
            current, count = self._locks[upload_id]
            if count <= 1:
                del self._locks[upload_id]
            else:
                self._locks[upload_id] = (current, count - 1)

        held.releases.append(forget)
        return lock

    async def _offload(
        self,
        held: _Held,
        call: Callable[[], _T],
        on_done: Callable[[object], None] | None = None,
    ) -> _T:
        """`call()` in a worker thread; the request keeps what it holds until it returns.

        `on_done` runs when the thread returns, even if the request was cancelled.
        """
        task = asyncio.ensure_future(asyncio.to_thread(call))
        if on_done is not None:
            task.add_done_callback(on_done)
        held.running = task
        return await asyncio.shield(task)

    async def _authenticate(
        self,
        held: _Held,
        transfer_id: str,
        authorization: str | None,
        *,
        holds_slot: bool = False,
    ) -> FileTransferAccess:
        """The ticket and its client's standing.

        A header that cannot carry a ticket token is refused on the loop, with
        no thread; anything else is the gate's digest and grant check, offloaded.
        Before a slot (`holds_slot` false) the check takes one auth permit
        without waiting -- none free is `_AuthBusy` -- and gives it back when
        its thread returns, whatever became of the request meanwhile. A request
        that already holds a slot is bounded by the slot count and takes none.
        """
        if ticket_token_from_authorization(authorization) is None:
            raise FilesRefusal("ticket", FilesReason.TICKET_INVALID)
        gate, kind = self._gate, self._kind
        give: Callable[[object], None] | None = None
        if not holds_slot:
            permits = self._auth_slots
            if permits[0] <= 0:
                raise _AuthBusy
            permits[0] -= 1

            def give(_done: object) -> None:
                permits[0] += 1

        return await self._offload(
            held, lambda: gate.authenticate(kind, transfer_id, authorization), give
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if scope.get("query_string"):
            await _error("invalid_request", None, 400)(scope, receive, send)
            return
        if self._kind is FileTransferKind.DOWNLOAD and request.method != "GET":
            await _error("invalid_request", None, 405, {"Allow": "GET"})(scope, receive, send)
            return
        held = _Held()
        try:
            if self._kind is FileTransferKind.DOWNLOAD:
                await self._download(request, held, scope, receive, send)
                return
            try:
                response = await self._upload(request, held)
            except Exception as error:
                response = _failure(error)
            await response(scope, receive, send)
        except Exception:  # noqa: S110 - the client left; nothing to answer, nothing to log
            pass
        finally:
            if held.lock is not None and held.lock.locked():
                lock = held.lock
                held.releases.append(lock.release)
            held.release()

    # ---- uploads ----------------------------------------------------------------

    async def _upload(self, request: Request, held: _Held) -> Response:
        path_id = request.path_params.get("transfer_id")
        authorization = request.headers.get("authorization")
        gate = self._gate
        upload_id = gate.parse_id(FileTransferKind.UPLOAD, path_id)
        if upload_id is None:
            return _refusal(FilesReason.TICKET_INVALID)
        if request.method == "HEAD":
            access = await self._authenticate(held, upload_id, authorization)
            if not self._take_slot(held):
                return _busy()
            offset = await self._offload(held, lambda: gate.upload_offset(access))
            headers = {**_NO_STORE, "Upload-Offset": str(offset)}
            if access.ticket.declared_size is not None:
                headers["Upload-Length"] = str(access.ticket.declared_size)
            return Response(status_code=204, headers=headers)
        # Authenticated first -- an unauthenticated caller only ever learns the
        # one 401 -- and refused before it may hold a slot or queue behind the
        # upload's lock.
        await self._authenticate(held, upload_id, authorization)
        presented = parse_upload_offset(request.headers.get("upload-offset"))
        raw_complete = request.headers.get("upload-complete")
        completion = None if raw_complete is None else parse_upload_complete(raw_complete)
        content_length = _content_length(request)
        if not self._take_slot(held):
            return _busy()
        lock = self._lock_for(upload_id, held)
        async with asyncio.timeout(self._idle):
            await lock.acquire()
        held.lock = lock
        # Again under the lock: the ticket may have closed while this waited.
        access = await self._authenticate(held, upload_id, authorization, holds_slot=True)
        offset = await self._offload(
            held, lambda: gate.check_append(access, presented, content_length)
        )
        if content_length != 0 or completion is None:
            offset = await self._append(request, held, access, offset)
        if completion is None:
            return Response(status_code=204, headers={**_NO_STORE, "Upload-Offset": str(offset)})
        return await self._finalize(held, access, completion)

    async def _append(
        self, request: Request, held: _Held, access: FileTransferAccess, offset: int
    ) -> int:
        chunks = _BodyChunks(
            asyncio.get_running_loop(),
            request.stream(),
            idle_seconds=self._idle,
            deadline=time.monotonic() + self._deadline,
        )
        return await self._offload(held, lambda: self._gate.append(access, offset, chunks))

    async def _finalize(
        self, held: _Held, access: FileTransferAccess, completion: UploadCompletion
    ) -> Response:
        envelope = await self._offload(held, lambda: self._gate.finalize(access, completion))
        return _envelope_answer(envelope)

    # ---- downloads --------------------------------------------------------------

    async def _download(
        self, request: Request, held: _Held, scope: Scope, receive: Receive, send: Send
    ) -> None:
        gate = self._gate
        path_id = request.path_params.get("transfer_id")
        authorization = request.headers.get("authorization")
        range_header = request.headers.get("range")
        try:
            download_id = gate.parse_id(FileTransferKind.DOWNLOAD, path_id)
            if download_id is None:
                raise FilesRefusal("ticket", FilesReason.TICKET_INVALID)
            access = await self._authenticate(held, download_id, authorization)
        except Exception as error:
            await _failure(error)(scope, receive, send)
            return
        if not self._take_slot(held):
            await _busy()(scope, receive, send)
            return
        deadline = time.monotonic() + self._download_deadline

        def hold_reader(done: object) -> None:
            # Registered when the opening thread returns -- before this request
            # resumes, and even if it was cancelled while the thread ran -- so
            # every exit (stream, 206, 416, failure, cancellation) closes the
            # reader exactly once, ahead of the slot it was opened under.
            if (
                isinstance(done, asyncio.Future)
                and not done.cancelled()
                and done.exception() is None
            ):
                held.releases.append(done.result().close)

        try:
            opened = await self._offload(held, lambda: gate.open_download(access), hold_reader)
            try:
                selected = parse_range(range_header, opened.size)
            except RangeNotSatisfiableError:
                unsatisfiable = _error(
                    "invalid_request", None, 416, {"Content-Range": f"bytes */{opened.size}"}
                )
                await unsatisfiable(scope, receive, send)
                return
            start, length = (
                (0, opened.size)
                if selected is None
                else (
                    selected.start,
                    selected.length,
                )
            )
            chunks = await self._offload(held, lambda: opened.read_range(start, length))
            first = await self._offload(held, lambda: next(chunks, None))
        except Exception as error:
            await _failure(error)(scope, receive, send)
            return
        headers = {
            **_NO_STORE,
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
            "ETag": f'"{access.ticket.expected_version}"',
        }
        if access.ticket.declared_sha256 is not None:
            headers["X-Content-SHA256"] = access.ticket.declared_sha256
        if selected is not None:
            headers["Content-Range"] = selected.content_range

        recheck_every = self._recheck
        idle = self._idle

        async def body() -> AsyncIterator[bytes]:
            # After the headers left nothing can become a status: a changed
            # file, the deadline, an expired ticket or a revoked grant stops the
            # stream short of `Content-Length` and the connection is closed.
            chunk = first
            recheck_at = time.monotonic() + recheck_every
            while chunk is not None:
                yield chunk
                now = time.monotonic()
                if now >= deadline:
                    raise _StreamStopped
                try:
                    if now >= recheck_at:
                        await self._authenticate(held, download_id, authorization, holds_slot=True)
                        recheck_at = time.monotonic() + recheck_every
                    chunk = await self._offload(held, lambda: next(chunks, None))
                except Exception:
                    raise _StreamStopped from None

        async def bounded_send(message: Message) -> None:
            # A reader that stops reading blocks this send (transport flow
            # control); past the idle bound, or the deadline, the stream stops.
            limit = idle
            if message.get("body"):
                limit = min(idle, deadline - time.monotonic())
                if limit <= 0:
                    raise _StreamStopped
            async with asyncio.timeout(limit):
                await send(message)

        response = StreamingResponse(
            body(),
            status_code=200 if selected is None else 206,
            headers=headers,
            media_type="application/octet-stream",
        )
        await response(scope, receive, bounded_send)


class _BrowserDownloadEndpoint(_FileTransferEndpoint):
    """`GET|HEAD /files/v1/browser-downloads/{segment}` (contract section 17.6).

    The link is the credential. Every refusal is one undistinguished, empty
    `404`, decided before a slot is taken where it can be: a query string, any
    other method, a malformed segment, the feature off, then -- under one
    pre-slot permit, in a thread -- the link's row, its client's standing, its
    grant and the allowlist; then a slot, then the file at the link's version.
    A completed GET settles the link (single use); a HEAD, a cut or a failed GET
    never does. Shares the byte routes' slot and pre-slot caps.
    """

    def __init__(self, gate: FileTransferGate, **bounds: Any) -> None:  # noqa: ANN401
        super().__init__(gate, FileTransferKind.DOWNLOAD, **bounds)
        self._active: set[str] = set()
        self._settling: set[asyncio.Future[None]] = set()

    @staticmethod
    async def _not_found(scope: Scope, receive: Receive, send: Send) -> None:
        await Response(status_code=404, headers={"Cache-Control": "no-store"})(scope, receive, send)

    async def _authenticate_link(
        self, held: _Held, segment: object, *, holds_slot: bool = False
    ) -> FileTransferAccess:
        gate = self._gate
        give: Callable[[object], None] | None = None
        if not holds_slot:
            permits = self._auth_slots
            if permits[0] <= 0:
                raise _AuthBusy
            permits[0] -= 1

            def give(_done: object) -> None:
                permits[0] += 1

        return await self._offload(held, lambda: gate.authenticate_browser(segment), give)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        segment = request.path_params.get("segment")
        held = _Held()
        try:
            if (
                scope.get("query_string")
                or request.method not in {"GET", "HEAD"}
                or not self._gate.browser_client_ids
                or parse_browser_link(segment) is None
            ):
                await self._not_found(scope, receive, send)
                return
            await self._serve(request, held, str(segment), scope, receive, send)
        except Exception:  # noqa: S110 - the client left; nothing to answer, nothing to log
            pass
        finally:
            held.release()

    async def _serve(
        self,
        request: Request,
        held: _Held,
        segment: str,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        gate = self._gate
        try:
            access = await self._authenticate_link(held, segment)
        except Exception:
            await self._not_found(scope, receive, send)
            return
        link_id = access.ticket.transfer_id
        if link_id in self._active or not self._take_slot(held):
            await self._not_found(scope, receive, send)
            return
        self._active.add(link_id)
        held.releases.append(lambda: self._active.discard(link_id))

        def hold_reader(done: object) -> None:
            if (
                isinstance(done, asyncio.Future)
                and not done.cancelled()
                and done.exception() is None
            ):
                held.releases.append(done.result().close)

        try:
            opened = await self._offload(held, lambda: gate.open_download(access), hold_reader)
        except Exception:
            await self._not_found(scope, receive, send)
            return
        size = opened.size
        headers = {
            **_BROWSER_HEADERS,
            "Content-Disposition": content_disposition(access.ticket.path.rsplit("/", 1)[-1]),
            "Content-Length": str(size),
        }
        if request.method == "HEAD":
            await Response(status_code=200, headers=headers)(scope, receive, send)
            return
        try:
            chunks = await self._offload(held, lambda: opened.read_range(0, size))
            first = await self._offload(held, lambda: next(chunks, None))
        except Exception:
            await self._not_found(scope, receive, send)
            return
        deadline = time.monotonic() + self._download_deadline
        recheck_every, idle = self._recheck, self._idle
        client_id = access.standing.oauth_client_id

        async def body() -> AsyncIterator[bytes]:
            chunk = first
            sent = 0
            settled = False
            recheck_at = time.monotonic() + recheck_every

            # Every byte was handed to the transport: the link is spent. The
            # line is written in a worker thread that no cancellation reaches,
            # so a client that hangs up right after its last byte cannot cancel
            # it away.
            def settle() -> None:
                if gate.consume_browser(access):
                    BROWSER_LOGGER.info(
                        "files browser download completed client=%s size=%s", client_id, size
                    )

            try:
                while chunk is not None:
                    yield chunk
                    sent += len(chunk)
                    now = time.monotonic()
                    if now >= deadline:
                        raise _StreamStopped
                    try:
                        if now >= recheck_at:
                            await self._authenticate_link(held, segment, holds_slot=True)
                            recheck_at = time.monotonic() + recheck_every
                        chunk = await self._offload(held, lambda: next(chunks, None))
                    except Exception:
                        raise _StreamStopped from None
                if sent != size:
                    raise _StreamStopped
                settled = True
                await self._offload(held, settle)
            finally:
                # The generator only resumes past the last `yield` once the
                # transport took that chunk, so `sent == size` here means the
                # whole body went out even if the client's hang-up cancelled
                # this request while it waited for the next (empty) chunk.
                if sent == size and not settled:
                    settled = True
                    task = asyncio.ensure_future(asyncio.to_thread(settle))
                    self._settling.add(task)
                    task.add_done_callback(self._settling.discard)

        async def bounded_send(message: Message) -> None:
            limit = idle
            if message.get("body"):
                limit = min(idle, deadline - time.monotonic())
                if limit <= 0:
                    raise _StreamStopped
            async with asyncio.timeout(limit):
                await send(message)

        await StreamingResponse(body(), status_code=200, headers=headers)(
            scope, receive, bounded_send
        )


_BROWSER_TOKEN_TEXT: Final = re.compile(r"gfwbd_[0-9a-f]{64}")


class _BrowserTokenRedaction(logging.Filter):
    """Section 17.6: a browser link's token never reaches an access log line.

    Production runs uvicorn with `access_log=False`, but a process configured
    otherwise would log the request line, whose path *is* the credential. This
    filter rewrites the token out of any `uvicorn.access` record first.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _BROWSER_TOKEN_TEXT.sub("gfwbd_[REDACTED]", record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                _BROWSER_TOKEN_TEXT.sub("gfwbd_[REDACTED]", value)
                if isinstance(value, str)
                else value
                for value in record.args
            )
        return True


class _BrowserCompletionHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """Section 17.6: the operator's completion line, on stderr, in a real process.

    `apps/gateway.py` configures no logging, so the root logger stays at
    WARNING and Python's last-resort handler drops INFO: without its own
    handler the line would never be seen. This one handler is attached to the
    browser logger alone (which then does not propagate), so no global logging
    configuration changes and nothing is printed twice.

    The stream is resolved at emit time, not bound at construction, so a
    redirected or replaced `sys.stderr` (a test capture, a supervisor) is
    always the one written to.
    """

    def __init__(self) -> None:
        logging.Handler.__init__(self)

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, _value: TextIO) -> None:
        return None


def _emit_browser_completions_to_stderr() -> None:
    logger = BROWSER_LOGGER
    if not any(isinstance(item, _BrowserCompletionHandler) for item in logger.handlers):
        handler = _BrowserCompletionHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def _redact_browser_tokens_in_access_log() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _BrowserTokenRedaction) for item in logger.filters):
        logger.addFilter(_BrowserTokenRedaction())


def build_file_transfer_routes(
    gate: FileTransferGate,
    *,
    max_concurrent: int = MAX_CONCURRENT_TRANSFERS,
    max_concurrent_authentications: int | None = None,
    body_idle_timeout_seconds: float = BODY_IDLE_TIMEOUT_SECONDS,
    patch_deadline_seconds: float = PATCH_DEADLINE_SECONDS,
    download_deadline_seconds: float = DOWNLOAD_DEADLINE_SECONDS,
    download_recheck_seconds: float = DOWNLOAD_RECHECK_SECONDS,
    browser_downloads: bool = False,
) -> Sequence[BaseRoute]:
    """The two section 10 routes over one gate, sharing one slot count.

    They also share one pre-slot authentication cap,
    `max_concurrent_authentications` (default `AUTH_SLOTS_PER_TRANSFER_SLOT`
    times `max_concurrent`).
    """
    auth_cap = (
        AUTH_SLOTS_PER_TRANSFER_SLOT * max_concurrent
        if max_concurrent_authentications is None
        else max_concurrent_authentications
    )
    if (
        max_concurrent < 1
        or auth_cap < 1
        or min(
            body_idle_timeout_seconds,
            patch_deadline_seconds,
            download_deadline_seconds,
            download_recheck_seconds,
        )
        <= 0
    ):
        raise ValueError("byte-route bounds must be positive")
    slots = [max_concurrent]
    auth_slots = [auth_cap]
    locks: dict[str, tuple[asyncio.Lock, int]] = {}

    def endpoint(kind: FileTransferKind) -> _FileTransferEndpoint:
        return _FileTransferEndpoint(
            gate,
            kind,
            slots=slots,
            auth_slots=auth_slots,
            upload_locks=locks,
            body_idle_timeout_seconds=body_idle_timeout_seconds,
            patch_deadline_seconds=patch_deadline_seconds,
            download_deadline_seconds=download_deadline_seconds,
            download_recheck_seconds=download_recheck_seconds,
        )

    routes: list[BaseRoute] = [
        Route(
            UPLOADS_PATH + "{transfer_id}",
            endpoint(FileTransferKind.UPLOAD),
            methods=["HEAD", "PATCH"],
        ),
        Route(
            DOWNLOADS_PATH + "{transfer_id}",
            endpoint(FileTransferKind.DOWNLOAD),
            methods=["GET"],
        ),
    ]
    if browser_downloads:
        _redact_browser_tokens_in_access_log()
        _emit_browser_completions_to_stderr()
        # Section 17.6: mounted only when the feature is on; any method reaches
        # the endpoint, which answers everything but GET and HEAD with its 404.
        routes.append(
            Route(
                BROWSER_DOWNLOADS_PATH + "{segment}",
                _BrowserDownloadEndpoint(
                    gate,
                    slots=slots,
                    auth_slots=auth_slots,
                    upload_locks=locks,
                    body_idle_timeout_seconds=body_idle_timeout_seconds,
                    patch_deadline_seconds=patch_deadline_seconds,
                    download_deadline_seconds=download_deadline_seconds,
                    download_recheck_seconds=download_recheck_seconds,
                ),
            )
        )
    return tuple(routes)
