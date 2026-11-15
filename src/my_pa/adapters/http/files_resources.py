"""Download tickets as MCP resources (files-workspace contract section 17.3).

`files.download.begin` answers `resource_uri` (`mcp-files://downloads/<id>`) and,
on the remote MCP surface, a `resource_link` to it. A client that cannot make
its own HTTP calls (ChatGPT) reads that link with `resources/read` on `/mcp`;
`adapters/mcp/remote.py` streams the answer's base64 from what this module
opens. Every decision is the gate's (`application.file_transfer`), off the event
loop:

- **Authorization from authentication only.** The request's authenticated
  Principal and OAuth client id, never a field: the ticket must be a download
  ticket of this workspace, the caller's, issued to the same client and usable
  now, and the client's standing is re-checked as the byte route's. Every miss
  is the one `ticket_invalid` (a closed token; the URI is never echoed).
- **The byte route's bounds.** A per-process stream cap (4, separate from the
  byte routes' own), the 600 s deadline, a ticket-and-grant re-check every 5 s,
  and the store's version re-check before every piece. A refusal after the
  first byte stops the stream short of its length.
- **Bounded memory.** Pieces of 768 KiB (a multiple of 3, so each encodes to
  base64 alone) are read in a worker thread one at a time; nothing is buffered
  beyond the piece in flight.
- **The held-open file is released exactly once**, and only after any worker
  thread using it returned, however the request ends.

Not audited, like a byte-route GET (contract section 11).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Final, TypeVar

from my_pa.adapters.remote_resources import (
    RemoteResourceRefused,
    RemoteResourceStream,
    RemoteResourceTemplate,
    ResourceRequester,
)
from my_pa.application.errors import DeniedError
from my_pa.application.file_transfer import FileTransferAccess, FileTransferGate
from my_pa.application.file_workspace import DOWNLOAD_RESOURCE_PREFIX
from my_pa.contracts.ports import FileTransferKind, FileWorkspaceReader
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import FilesReason

__all__ = [
    "RESOURCE_PIECE_BYTES",
    "WorkspaceDownloadResources",
]

#: One streamed piece: 768 KiB, a multiple of 3 (base64 encodes it alone).
RESOURCE_PIECE_BYTES: Final = 3 * 256 * 1024
#: The per-process cap on concurrent resource streams (contract section 8).
MAX_CONCURRENT_RESOURCE_STREAMS: Final = 4
#: As the byte route's download (contract section 10.1).
RESOURCE_DEADLINE_SECONDS: Final = 600.0
RESOURCE_RECHECK_SECONDS: Final = 5.0
_MIME_TYPE: Final = "application/octet-stream"
_TEMPLATE: Final = DOWNLOAD_RESOURCE_PREFIX + "{download_id}"

_T = TypeVar("_T")


def _reason(error: BaseException) -> str:
    """The closed token a refusal answers with; never a value."""
    if isinstance(error, FilesRefusal):
        return error.reason.value
    if isinstance(error, DeniedError):
        return "denied"
    return "unavailable"


class _OpenedDownload:
    """One authorized, held-open download resource (see the module docstring)."""

    def __init__(
        self,
        owner: WorkspaceDownloadResources,
        access: ResourceRequester,
        download_id: str,
        ticket: FileTransferAccess,
        reader: FileWorkspaceReader,
    ) -> None:
        self._owner = owner
        self._access = access
        self._download_id = download_id
        self._ticket = ticket
        self._reader = reader
        self.size = reader.size
        self.mime_type = _MIME_TYPE
        self._running: set[asyncio.Future[object]] = set()
        self._closed = False

    async def _offload(self, call: Callable[[], _T]) -> _T:
        """`call` in a worker thread, tracked so the reader outlives it."""
        future = asyncio.ensure_future(asyncio.to_thread(call))
        self._running.add(future)  # type: ignore[arg-type]
        future.add_done_callback(self._running.discard)
        return await asyncio.shield(future)

    async def stream(self, write: Callable[[bytes], Awaitable[None]]) -> None:
        owner = self._owner
        deadline = owner.clock() + owner.deadline_seconds
        recheck_at = owner.clock() + owner.recheck_seconds
        position = 0
        while position < self.size:
            now = owner.clock()
            if now >= deadline:
                raise FilesRefusal("stream", FilesReason.TICKET_INVALID)
            if now >= recheck_at:
                await self._offload(lambda: owner.authenticate(self._access, self._download_id))
                recheck_at = owner.clock() + owner.recheck_seconds
            length = min(RESOURCE_PIECE_BYTES, self.size - position)
            piece = await self._offload(partial(self._read, position, length))
            if len(piece) != length:
                raise FilesRefusal("stream", FilesReason.EXTERNAL_CHANGE_DETECTED)
            await write(piece)
            position += length

    def _read(self, start: int, length: int) -> bytes:
        return b"".join(self._reader.read_range(start, length))

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        running = tuple(self._running)
        released: list[bool] = []

        def release(_done: object = None) -> None:
            if not released and all(future.done() for future in running):
                released.append(True)
                self._reader.close()
                self._owner.slot_returned()

        if not running:
            release()
            return
        for future in running:
            future.add_done_callback(release)


class WorkspaceDownloadResources:
    """The remote MCP `RemoteResourceSource` over the byte routes' gate."""

    def __init__(
        self,
        gate: FileTransferGate,
        *,
        max_concurrent: int = MAX_CONCURRENT_RESOURCE_STREAMS,
        deadline_seconds: float = RESOURCE_DEADLINE_SECONDS,
        recheck_seconds: float = RESOURCE_RECHECK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_concurrent < 1 or deadline_seconds <= 0 or recheck_seconds <= 0:
            raise ValueError("resource stream bounds must be positive")
        self._gate = gate
        self._free = max_concurrent
        self.deadline_seconds = deadline_seconds
        self.recheck_seconds = recheck_seconds
        self.clock = clock

    def templates(self) -> list[RemoteResourceTemplate]:
        return [
            RemoteResourceTemplate(
                name="workspace-download",
                uri_template=_TEMPLATE,
                description=(
                    "A file opened by files.download.begin; read it with resources/read "
                    "before its ticket expires."
                ),
                mime_type=_MIME_TYPE,
            )
        ]

    def authenticate(self, access: ResourceRequester, download_id: str) -> FileTransferAccess:
        """The gate's resource authentication for this request's identity (a worker thread)."""
        return self._gate.authenticate_resource(
            download_id,
            principal_id=access.principal.principal_id,
            oauth_client_id=access.authenticated_client_id,
        )

    def slot_returned(self) -> None:
        self._free += 1

    async def open(self, uri: str, access: ResourceRequester) -> RemoteResourceStream:
        download_id = uri.removeprefix(DOWNLOAD_RESOURCE_PREFIX)
        if (
            not uri.startswith(DOWNLOAD_RESOURCE_PREFIX)
            or FileTransferGate.parse_id(FileTransferKind.DOWNLOAD, download_id) is None
        ):
            raise RemoteResourceRefused(FilesReason.TICKET_INVALID.value)
        if self._free < 1:
            raise RemoteResourceRefused("unavailable")
        self._free -= 1

        def opened() -> tuple[FileTransferAccess, FileWorkspaceReader]:
            ticket = self.authenticate(access, download_id)
            return ticket, self._gate.open_download(ticket)

        future = asyncio.ensure_future(asyncio.to_thread(opened))
        try:
            ticket, reader = await asyncio.shield(future)
        except asyncio.CancelledError:
            # The thread cannot be cancelled: whatever it opens is closed, and
            # the slot returned, when it really returns.
            def abandon(
                done: asyncio.Future[tuple[FileTransferAccess, FileWorkspaceReader]],
            ) -> None:
                if not done.cancelled() and done.exception() is None:
                    done.result()[1].close()
                self.slot_returned()

            future.add_done_callback(abandon)
            raise
        except Exception as error:
            self.slot_returned()
            raise RemoteResourceRefused(_reason(error)) from None
        return _OpenedDownload(self, access, download_id, ticket, reader)
