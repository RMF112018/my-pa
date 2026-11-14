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
- **Concurrency.** Its own per-process slot count (default 4), separate from
  the `/mcp` semaphores: a request that finds none free is 503 with
  `Retry-After` and nothing read. Concurrent PATCHes of one upload are
  serialized by a per-upload lock, behind the store's offset check and the
  row's offset CAS.
- **Off the event loop.** Every store and database call runs in a worker
  thread. The body is bridged into that thread one chunk at a time
  (`_BodyChunks`: the thread asks the loop for the next chunk and waits for it),
  so memory is bounded by one server chunk and there is no queue. Each wait is
  bounded by `body_idle_timeout_seconds` and the whole PATCH by
  `patch_deadline_seconds` (408 when either passes); a thread the request no
  longer waits for keeps its slot and its upload lock until it returns.
- **Privacy.** Nothing here logs. Errors are JSON `{error, reason}` -- a public
  code and a section 7 token or `null` -- and never carry a token, a path or a
  body byte. The interaction log wraps `/mcp` only, so these routes are not
  recorded.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from typing import Any, Final, TypeVar

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import BaseRoute, Route
from starlette.types import Receive, Scope, Send

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
    parse_range,
    parse_upload_complete,
    parse_upload_offset,
)
from my_pa.domain.files.vocabulary import FilesReason

__all__ = [
    "BODY_IDLE_TIMEOUT_SECONDS",
    "DOWNLOADS_PATH",
    "MAX_CONCURRENT_TRANSFERS",
    "PATCH_DEADLINE_SECONDS",
    "UPLOADS_PATH",
    "build_file_transfer_routes",
]

UPLOADS_PATH: Final = "/files/v1/uploads/"
DOWNLOADS_PATH: Final = "/files/v1/downloads/"
#: Contract section 8: the byte routes' own per-process cap.
MAX_CONCURRENT_TRANSFERS: Final = 4
#: The longest one wait for the next body chunk may take, the remote MCP
#: `call_timeout_seconds` default: a stalled client releases its slot then.
BODY_IDLE_TIMEOUT_SECONDS: Final = 30.0
#: The longest one PATCH may stream: 32 MiB at about 56 KiB/s. A slow-drip
#: client that never idles past the bound above still cannot hold a slot longer.
PATCH_DEADLINE_SECONDS: Final = 600.0
RETRY_AFTER_SECONDS: Final = 1

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
        upload_locks: dict[str, tuple[asyncio.Lock, int]],
        body_idle_timeout_seconds: float,
        patch_deadline_seconds: float,
    ) -> None:
        self._gate = gate
        self._kind = kind
        self._slots = slots
        self._locks = upload_locks
        self._idle = body_idle_timeout_seconds
        self._deadline = patch_deadline_seconds

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

    async def _offload(self, held: _Held, call: Callable[[], _T]) -> _T:
        """`call()` in a worker thread; the request keeps what it holds until it returns."""
        task = asyncio.ensure_future(asyncio.to_thread(call))
        held.running = task
        return await asyncio.shield(task)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive)
        if scope.get("query_string"):
            await _error("invalid_request", None, 400)(scope, receive, send)
            return
        if self._kind is FileTransferKind.DOWNLOAD and request.method != "GET":
            await _error("invalid_request", None, 405, {"Allow": "GET"})(scope, receive, send)
            return
        held = _Held()
        if not self._take_slot(held):
            busy = _error("unavailable", None, 503, {"Retry-After": str(RETRY_AFTER_SECONDS)})
            await busy(scope, receive, send)
            return
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
            access = await self._offload(
                held, lambda: gate.authenticate(FileTransferKind.UPLOAD, upload_id, authorization)
            )
            offset = await self._offload(held, lambda: gate.upload_offset(access))
            headers = {**_NO_STORE, "Upload-Offset": str(offset)}
            if access.ticket.declared_size is not None:
                headers["Upload-Length"] = str(access.ticket.declared_size)
            return Response(status_code=204, headers=headers)
        presented = parse_upload_offset(request.headers.get("upload-offset"))
        raw_complete = request.headers.get("upload-complete")
        completion = None if raw_complete is None else parse_upload_complete(raw_complete)
        content_length = _content_length(request)
        lock = self._lock_for(upload_id, held)
        async with asyncio.timeout(self._idle):
            await lock.acquire()
        held.lock = lock
        access = await self._offload(
            held, lambda: gate.authenticate(FileTransferKind.UPLOAD, upload_id, authorization)
        )
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
        reader = None
        try:
            access = await self._offload(
                held, lambda: gate.authenticate(FileTransferKind.DOWNLOAD, path_id, authorization)
            )
            reader = await self._offload(held, lambda: gate.open_download(access))
            opened = reader
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
            if reader is not None:
                await self._offload(held, reader.close)
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

        async def body() -> AsyncIterator[bytes]:
            # A change found after the headers left cannot become a 412: the
            # stream stops short of `Content-Length`, which the client detects.
            chunk = first
            try:
                while chunk is not None:
                    yield chunk
                    chunk = await self._offload(held, lambda: next(chunks, None))
            except Exception:
                return

        response = StreamingResponse(
            body(),
            status_code=200 if selected is None else 206,
            headers=headers,
            media_type="application/octet-stream",
        )
        try:
            await response(scope, receive, send)
        finally:
            held.releases.append(opened.close)


def build_file_transfer_routes(
    gate: FileTransferGate,
    *,
    max_concurrent: int = MAX_CONCURRENT_TRANSFERS,
    body_idle_timeout_seconds: float = BODY_IDLE_TIMEOUT_SECONDS,
    patch_deadline_seconds: float = PATCH_DEADLINE_SECONDS,
) -> Sequence[BaseRoute]:
    """The two section 10 routes over one gate, sharing one slot count."""
    if max_concurrent < 1 or body_idle_timeout_seconds <= 0 or patch_deadline_seconds <= 0:
        raise ValueError("byte-route bounds must be positive")
    slots = [max_concurrent]
    locks: dict[str, tuple[asyncio.Lock, int]] = {}

    def endpoint(kind: FileTransferKind) -> _FileTransferEndpoint:
        return _FileTransferEndpoint(
            gate,
            kind,
            slots=slots,
            upload_locks=locks,
            body_idle_timeout_seconds=body_idle_timeout_seconds,
            patch_deadline_seconds=patch_deadline_seconds,
        )

    return (
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
    )
