"""The files byte routes' application half (files-workspace contract sections 7, 8, 10).

`adapters/http/files_transfer.py` carries HTTP; every decision about a byte
request is made here, synchronously, off the event loop:

- **Authentication.** The token is only an exact `Authorization: Bearer
  gfwtk_…` (`ticket_token_from_authorization`), the path id must be an id of
  the route's kind, and the ticket is the row `authenticate_ticket` opens
  (digest only, constant time, usable now, the route's kind). Every miss is
  the one `ticket_invalid`. A ticket bound to a local caller
  (`local_principal:…`) is not usable at these remote routes: `ticket_invalid`.
- **Grant re-check, every request.** `RemoteClientStandingReader` re-reads
  the client the ticket names durably: remote access on, the client enabled
  and not revoked, the Principal still the ticket's owner, an active grant for
  the capability that *issued* the ticket (`files.upload.begin`,
  `files.download.begin`) under its purpose, and for uploads writes allowed
  (client, global, and this process's `MY_PA_REMOTE_WRITES_ENABLED`). Any miss
  is `DeniedError` (HTTP 403), so a revocation takes effect on the next request.
- **Resource reads** (contract section 17.3): `authenticate_resource` opens a
  download ticket by id for an authenticated `/mcp` request -- no ticket token
  -- only when the ticket is the request's Principal's, issued to the same
  OAuth client (constant-time compare of the derived client reference), of this
  workspace and usable now; then the same standing re-check. Every miss is the
  one `ticket_invalid`, so another client's ticket and an unknown id are alike.
- **Short transactions.** Authentication is one unit of work, the body is
  streamed with none open, and the offset CAS is a second one.
- **Finalize** is `files.upload.finalize` through `ApplicationService.invoke`
  with the ticket's owner, `REMOTE_CLIENT`, the client's OAuth id and its
  freshly read grants -- the same `authorize` audit, CAS and refusals as the MCP
  tool. Its idempotency key is derived from the upload id
  (`files-route-finalize:<upload id>`). A completing PATCH retried after that
  finalize committed does not reach it: the ticket is closed, so the retry is
  401 `ticket_invalid` and the caller verifies with `files.stat` (contract
  section 10.1).

Refusals are the domain's `FilesRefusal` (a section 7 token), `FilesArgumentError`
(a malformed header), `RangeNotSatisfiableError`, `DeniedError`, or the store's
`FileWorkspaceUnavailableError`; none names a path, a token or a body byte.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

from my_pa.application.commands import FinalizeFileUpload
from my_pa.application.errors import DeniedError
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    FileTransferKind,
    FileTransferRecord,
    FileWorkspaceReader,
    FileWorkspaceStore,
    RemoteClientStanding,
    RemoteClientStandingReader,
    UnitOfWork,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.transfer import (
    DOWNLOAD_ID_PREFIX,
    UPLOAD_ID_PREFIX,
    UploadCompletion,
    check_upload_offset,
    parse_file_id,
    ticket_token_digest,
    ticket_token_from_authorization,
)
from my_pa.domain.files.vocabulary import MAX_UPLOAD_CHUNK_BYTES, FilesReason
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.transfer import client_ref_of
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "FINALIZE_KEY_PREFIX",
    "FileTransferAccess",
    "FileTransferGate",
    "UploadOffsetMismatch",
]

#: The idempotency key of a route finalize: this prefix and the upload id
#: (at most 6 + 64 characters, well under the 128-character key bound).
FINALIZE_KEY_PREFIX: Final = "files-route-finalize:"
_REMOTE_CLIENT_REF: Final = f"{CreatorKind.REMOTE_CLIENT.value}:"

#: The capability that issued each kind of ticket, and its one purpose.
_ISSUER: Final = {
    FileTransferKind.UPLOAD: (Capability.FILES_UPLOAD_BEGIN, Purpose.FILE_WORKSPACE_AUTHORING),
    FileTransferKind.DOWNLOAD: (Capability.FILES_DOWNLOAD_BEGIN, Purpose.FILE_WORKSPACE_READ),
}
_PREFIX: Final = {
    FileTransferKind.UPLOAD: UPLOAD_ID_PREFIX,
    FileTransferKind.DOWNLOAD: DOWNLOAD_ID_PREFIX,
}


class UploadOffsetMismatch(FilesRefusal):
    """`offset_mismatch`, carrying the staged offset the response must name."""

    def __init__(self, current: int) -> None:
        super().__init__("Upload-Offset", FilesReason.OFFSET_MISMATCH)
        self.current = current


@dataclass(frozen=True, slots=True)
class FileTransferAccess:
    """One authenticated byte request: the ticket and its client's fresh standing."""

    ticket: FileTransferRecord
    standing: RemoteClientStanding = field(repr=False)

    @property
    def principal(self) -> Principal:
        return Principal(
            principal_id=self.ticket.owner_principal_id,
            kind=PrincipalKind.OPERATOR,
            authenticated=True,
        )


def _ticket_invalid() -> FilesRefusal:
    return FilesRefusal("ticket", FilesReason.TICKET_INVALID)


class FileTransferGate:
    """Authenticate, re-check and serve one byte request (see the module docstring)."""

    def __init__(
        self,
        *,
        service: ApplicationService,
        store: FileWorkspaceStore,
        unit_of_work: Callable[[], UnitOfWork],
        standing: RemoteClientStandingReader,
        workspace_id: str,
        max_upload_bytes: int,
        remote_writes_enabled: bool,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service
        self._store = store
        self._unit_of_work = unit_of_work
        self._standing = standing
        self._workspace_id: Final = workspace_id
        self._max_upload_bytes: Final = max_upload_bytes
        self._remote_writes_enabled: Final = remote_writes_enabled
        self._clock = clock

    # ---- authentication ---------------------------------------------------------

    @staticmethod
    def parse_id(kind: FileTransferKind, path_id: object) -> str | None:
        """The path id if it is an id of `kind`'s prefix, else `None`."""
        return parse_file_id(path_id, _PREFIX[kind])

    def authenticate(
        self, kind: FileTransferKind, path_id: object, authorization: object
    ) -> FileTransferAccess:
        """The ticket the request's token opens for this id, and its client's standing."""
        transfer_id = self.parse_id(kind, path_id)
        token = ticket_token_from_authorization(authorization)
        digest = None if token is None else ticket_token_digest(token)
        if transfer_id is None or digest is None:
            raise _ticket_invalid()
        now = self._clock()
        with self._unit_of_work() as unit_of_work:
            ticket = unit_of_work.file_workspace.authenticate_ticket(
                transfer_id, digest, kind=kind, now=now
            )
        if (
            ticket is None
            or ticket.transfer_id != transfer_id
            or ticket.workspace_id != self._workspace_id
            or not ticket.client_ref.startswith(_REMOTE_CLIENT_REF)
        ):
            raise _ticket_invalid()
        return self._standing_checked(kind, ticket, now)

    def authenticate_resource(
        self, path_id: object, *, principal_id: str, oauth_client_id: str | None
    ) -> FileTransferAccess:
        """A download ticket read as an MCP resource by the client it was issued to."""
        transfer_id = self.parse_id(FileTransferKind.DOWNLOAD, path_id)
        if transfer_id is None or not oauth_client_id:
            raise _ticket_invalid()
        client_ref = client_ref_of(derive_creator(CreatorKind.REMOTE_CLIENT, oauth_client_id))
        now = self._clock()
        with self._unit_of_work() as unit_of_work:
            ticket = unit_of_work.file_workspace.get_transfer(
                transfer_id, principal_id=principal_id
            )
        if (
            ticket is None
            or ticket.transfer_id != transfer_id
            or ticket.kind is not FileTransferKind.DOWNLOAD
            or ticket.workspace_id != self._workspace_id
            or not ticket.usable_at(now)
            or not hmac.compare_digest(ticket.client_ref.encode(), client_ref.encode())
        ):
            raise _ticket_invalid()
        return self._standing_checked(FileTransferKind.DOWNLOAD, ticket, now)

    def _standing_checked(
        self, kind: FileTransferKind, ticket: FileTransferRecord, now: datetime
    ) -> FileTransferAccess:
        """The ticket's client's fresh standing, or `DeniedError` (see the docstring)."""
        standing = self._standing.standing(ticket.client_ref, now=now)
        capability, purpose = _ISSUER[kind]
        if (
            standing is None
            or standing.principal_id != ticket.owner_principal_id
            or not (
                (capability, purpose) in standing.capability_purposes
                or (capability, None) in standing.capability_purposes
            )
            or (
                kind is FileTransferKind.UPLOAD
                and not (standing.write_allowed and self._remote_writes_enabled)
            )
        ):
            raise DeniedError()
        return FileTransferAccess(ticket=ticket, standing=standing)

    # ---- uploads ------------------------------------------------------------------

    def upload_offset(self, access: FileTransferAccess) -> int:
        """The staged byte count: the upload's current `Upload-Offset`."""
        return self._store.upload_offset(access.ticket.transfer_id)

    def upload_ceiling(self, access: FileTransferAccess, offset: int) -> int:
        """The most bytes the upload may hold after one PATCH starting at `offset`.

        The 32 MiB per-request cap, the ticket's declared size and
        `MY_PA_FILES_MAX_UPLOAD_BYTES`, whichever is least.
        """
        ceiling = min(offset + MAX_UPLOAD_CHUNK_BYTES, self._max_upload_bytes)
        declared = access.ticket.declared_size
        if declared is not None:
            ceiling = min(ceiling, declared)
        return max(ceiling, offset)

    def check_append(
        self, access: FileTransferAccess, presented: int, content_length: int | None
    ) -> int:
        """Before any body byte: the offset matches, and a declared length fits.

        Answers the current offset. `offset_mismatch` (with the current offset)
        when `presented` is not it; `too_large` when a declared `Content-Length`
        could not fit; `quota` when it would leave less than the disk reserve.
        """
        current = self.upload_offset(access)
        try:
            check_upload_offset(presented, current)
        except FilesRefusal:
            raise UploadOffsetMismatch(current) from None
        if content_length is not None and (
            content_length > MAX_UPLOAD_CHUNK_BYTES
            or current + content_length > self.upload_ceiling(access, current)
        ):
            raise FilesRefusal("body", FilesReason.TOO_LARGE)
        self._store.ensure_free_space(0 if content_length is None else content_length)
        return current

    def append(self, access: FileTransferAccess, offset: int, chunks: Iterable[bytes]) -> int:
        """Stream `chunks` onto the staging at `offset`, then move the row's offset (CAS).

        The store refuses past the ceiling (`too_large`) and puts the staged
        length back to `offset`; it re-checks the disk reserve per chunk. No
        transaction is open while the body streams. The row's offset moves
        from what it holds now to the new staged length, in one short unit of
        work; a row that cannot move there is `offset_mismatch`.
        """
        upload_id = access.ticket.transfer_id
        position = self._store.append_upload(
            upload_id, offset, chunks, limit=self.upload_ceiling(access, offset)
        )
        owner = access.ticket.owner_principal_id
        now = self._clock()
        with self._unit_of_work() as unit_of_work:
            rows = unit_of_work.file_workspace
            row = rows.get_transfer(upload_id, principal_id=owner, for_update=True)
            if row is None or not row.usable_at(now):
                raise _ticket_invalid()
            if row.received_bytes == position:
                return position
            if (
                row.received_bytes > position
                or rows.advance_offset(
                    upload_id,
                    principal_id=owner,
                    expected_offset=row.received_bytes,
                    new_offset=position,
                    now=now,
                )
                is None
            ):
                raise UploadOffsetMismatch(position)
        return position

    def finalize(
        self, access: FileTransferAccess, completion: UploadCompletion
    ) -> ResponseEnvelope:
        """`files.upload.finalize` through `invoke`, as the ticket's client (see the docstring)."""
        grants = access.standing.capability_purposes
        if not (
            (Capability.FILES_UPLOAD_FINALIZE, Purpose.FILE_WORKSPACE_AUTHORING) in grants
            or (Capability.FILES_UPLOAD_FINALIZE, None) in grants
        ):
            # The same 403 as a missing issuing grant; `invoke` would refuse it
            # too (`unsupported`), after this request had been audited.
            raise DeniedError()
        upload_id = access.ticket.transfer_id
        command = FinalizeFileUpload(
            workspace_id=self._workspace_id,
            upload_id=upload_id,
            length=completion.length,
            sha256=completion.sha256,
            idempotency_key=FINALIZE_KEY_PREFIX + upload_id,
        )
        return self._service.invoke(
            RequestMetadata(
                request_id=issue_identifier(IdKind.CORRELATION),
                capability=Capability.FILES_UPLOAD_FINALIZE,
                purpose=Purpose.FILE_WORKSPACE_AUTHORING,
                principal_id=access.ticket.owner_principal_id,
                requested_at=self._clock(),
            ),
            command,
            principal=access.principal,
            transport=CaptureTransport.REMOTE_CLIENT,
            capability_grants=grants,
            authenticated_client_id=access.standing.oauth_client_id,
        )

    # ---- downloads ----------------------------------------------------------------

    def open_download(self, access: FileTransferAccess) -> FileWorkspaceReader:
        """The ticket's file, held at the ticket's version (`external_change_detected`).

        A preserved-version ticket opens the preimage; a path ticket opens the
        path at its bound version. Either way the reader's version must be the
        ticket's, and every later read re-checks it.
        """
        ticket = access.ticket
        expected = ticket.expected_version
        if expected is None:  # pragma: no cover - a download ticket always binds one
            raise _ticket_invalid()
        if ticket.preserved_version_id is not None:
            reader = self._store.open_preserved_version(ticket.preserved_version_id)
        else:
            reader = self._store.open_download(ticket.path, expected_version=expected)
        if reader.version != expected:
            reader.close()
            raise FilesRefusal("version", FilesReason.EXTERNAL_CHANGE_DETECTED)
        return reader
