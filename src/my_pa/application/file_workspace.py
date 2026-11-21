"""The files workspace capabilities (`files.*`, ADR-019, files-workspace contract sections 5-8).

`ApplicationService` binds the 17 names here and holds no logic for them. Each
call runs inside the request's one unit of work, after `authorize` (which
writes the audit event: capability, purpose and outcome). Here:

- **Principal and client from authentication only.** The Principal is the
  Authorization's; the client reference is the server-derived writer
  (`"<creator kind>:<creator id>"`, the `reports.transfer` binding). No
  argument names either.
- **Workspaces.** `workspace_id` must name a composed workspace the caller is
  admitted to (section 18.1: `MY_PA_FILES_WORKSPACES`, or the single
  `MY_PA_FILES_WORKSPACE_ID`); any other is `not_found`. A `read_only`
  workspace refuses every write `workspace_read_only`; an `approval`
  workspace turns every write into a pending change (`PendingWrites`,
  section 18.3) that only the operator applies (`file_workspace_approval`).
- **Writes** take the per-workspace advisory lock first
  (`FileWorkspaceRepository.lock_workspace`, `pg_advisory_xact_lock` keyed from
  the alias), so the product's own mutations of one workspace serialize until
  the transaction ends. Then the idempotency receipt: the same key with the
  same intent (`write_intent_digest` of the normalized arguments, a text by
  its SHA-256 only) answers the stored result with `replayed: true` and touches
  nothing; another intent is `conflict` on `idempotency_key`. A receipt never
  holds a text or a token: `files.upload.begin`'s `upload_token` is answered
  once and a replay answers without it (the client aborts and begins again).
- **CAS and no overwrite** are the store's: `expected_version` must equal the
  current token (`version_conflict`), a destination that exists is `exists`,
  and only `upload.finalize` and `write_text` replace -- with
  `expected_version`, after preserving the preimage, whose row is recorded
  here (`files.history`). Trash and restore record their row likewise.
- **Tickets** are minted with the `reports.transfer` helpers (`gfwtk_`, digest
  only stored; TTL default 3600 s, 300..86400). `files.upload.begin` first
  expires the caller's due tickets and discards their staging (trim T6).
- **Native file handles** (contract section 17.2): `files.upload.begin` with
  `source_file` checks the target, streams the handle's `download_url` through
  the composed `FileHandleFetcher` into a fresh staging file -- before the
  workspace lock, so a slow fetch never holds it -- then, under the lock and
  the receipt, records an upload row, closes it at once and publishes through
  the same finalize path as `files.upload.finalize`. The URL is read here only
  to hand it to the fetcher: it reaches no row, receipt, answer or error.
  `files.download.begin` also answers `name` and `resource_uri` (section 17.3).

The filesystem is not transactional. A store mutation that succeeded is not
undone if a later row write fails and the transaction rolls back; the
fingerprint checks of the next call see the filesystem as it is.
Every refusal is a section 7 reason token (`SafeDetail`) under its public code
and names no path, content or token.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from my_pa.application.authorization import Authorization
from my_pa.application.commands import (
    AbortFileUpload,
    BeginFileDownload,
    BeginFileUpload,
    Command,
    CopyFile,
    FinalizeFileUpload,
    GetFileHistory,
    ListFiles,
    ListFileWorkspaces,
    MakeFileDirectory,
    MoveFile,
    PreviewFile,
    RenameFile,
    RestoreFile,
    SearchFiles,
    StatFile,
    TrashFile,
    WriteFileText,
    parse_files_history_cursor,
)
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
)
from my_pa.application.lineage_visibility import require_read_grant, require_write_grant
from my_pa.contracts.ports import (
    FileHandleFetcher,
    FileHistoryPage,
    FilePendingChange,
    FilePendingChangeStore,
    FilePendingStatus,
    FileTransferKind,
    FileTransferRecord,
    FileTransferState,
    FileTrashRecord,
    FileVersionRecord,
    FileWorkspaceEntry,
    FileWorkspaceRepository,
    FileWorkspaceStore,
    FileWorkspaceUnavailableError,
    UnitOfWork,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.files.errors import FilesArgumentError, FilesRefusal
from my_pa.domain.files.sdcc_placement import PlacementDenied, SDCRPlacementGate
from my_pa.domain.files.paths import parse_path
from my_pa.domain.files.transfer import (
    BROWSER_DOWNLOAD_INSTRUCTIONS,
    UploadCompletion,
    UploadDeclaration,
    browser_link_segment,
    download_transfer,
    mint_browser_token,
    mint_ticket_token,
    transfer_url,
    upload_transfer,
    verify_staged,
    write_intent_digest,
)
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import (
    MAX_PREVIEW_BYTES,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_CHUNK_BYTES,
    MAX_WRITE_TEXT_BYTES,
    PAGE_SIZE,
    SEARCH_WALK_MAX_DEPTH,
    SEARCH_WALK_MAX_ENTRIES,
    TICKET_TTL_DEFAULT_SECONDS,
    TICKET_TTL_MAX_SECONDS,
    TICKET_TTL_MIN_SECONDS,
    FilesReason,
)
from my_pa.domain.files.workspaces import DEFAULT_MAX_PENDING_BYTES, WriteMode
from my_pa.domain.identity.operation import Capability, granted_purposes, is_write_capability
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.transfer import client_ref_of
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "APPROVAL_TTL_DEFAULT_SECONDS",
    "BROWSER_DOWNLOAD_ROUTE",
    "DOWNLOAD_RESOURCE_PREFIX",
    "FILE_WORKSPACE_CAPABILITIES",
    "PENDING_OPERATIONS",
    "BrowserDownloads",
    "ComposedFileWorkspace",
    "FileWorkspaceApplication",
    "PendingWrites",
    "decide_change",
    "entry_shape",
    "expire_change",
    "pending_binding",
    "pending_item",
]

#: The 17 names this module serves (contract section 1.1).
FILE_WORKSPACE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.FILES_WORKSPACES_LIST,
        Capability.FILES_LIST,
        Capability.FILES_STAT,
        Capability.FILES_SEARCH,
        Capability.FILES_PREVIEW,
        Capability.FILES_HISTORY,
        Capability.FILES_DOWNLOAD_BEGIN,
        Capability.FILES_MKDIR,
        Capability.FILES_COPY,
        Capability.FILES_UPLOAD_BEGIN,
        Capability.FILES_UPLOAD_ABORT,
        Capability.FILES_RENAME,
        Capability.FILES_MOVE,
        Capability.FILES_TRASH,
        Capability.FILES_RESTORE,
        Capability.FILES_UPLOAD_FINALIZE,
        Capability.FILES_WRITE_TEXT,
    }
)

#: Contract section 18.5: one operator server-log line per decision; never a path.
_APPROVAL_LOGGER: Final = logging.getLogger("my_pa.files.approval")

#: Section 10: the relative byte routes a ticket names.
_UPLOAD_ROUTE: Final = "/files/v1/uploads/"
_DOWNLOAD_ROUTE: Final = "/files/v1/downloads/"
#: Section 17.6: the browser download route a single-use link names.
BROWSER_DOWNLOAD_ROUTE: Final = "/files/v1/browser-downloads/"


@dataclass(frozen=True, slots=True)
class BrowserDownloads:
    """Section 17.6's composition: who gets a browser link, for how long, at which origin."""

    client_ids: frozenset[str]
    ttl_seconds: int
    public_origin: str


#: Section 17.3: the MCP resource URI a download ticket is also readable at.
DOWNLOAD_RESOURCE_PREFIX: Final = "mcp-files://downloads/"
#: How many due tickets one `files.upload.begin` expires (trim T6).
_REAP_LIMIT: Final = 64

#: Section 7: each reason token's public code.
_REFUSAL_CODES: Final[Mapping[FilesReason, type[ApplicationError]]] = {
    FilesReason.INVALID_PATH: InvalidRequestError,
    FilesReason.NOT_FOUND: NotFoundError,
    FilesReason.EXISTS: ConflictError,
    FilesReason.VERSION_CONFLICT: ConflictError,
    FilesReason.EXTERNAL_CHANGE_DETECTED: ConflictError,
    FilesReason.UNSUPPORTED_ENTRY: UnsupportedError,
    FilesReason.TOO_LARGE: InvalidRequestError,
    FilesReason.QUOTA: UnavailableError,
    FilesReason.DIGEST_MISMATCH: ConflictError,
    FilesReason.OFFSET_MISMATCH: ConflictError,
    FilesReason.TICKET_INVALID: DeniedError,
    FilesReason.FILE_HANDLE_UNSUPPORTED: UnsupportedError,
    FilesReason.FILE_HANDLE_REFUSED: InvalidRequestError,
}

#: A domain argument fault's field, as the public detail naming it.
_ARGUMENT_DETAILS: Final[Mapping[str, SafeDetail]] = {
    "after": SafeDetail.AFTER,
    "page_size": SafeDetail.PAGE_SIZE,
    "query": SafeDetail.QUERY,
    "offset": SafeDetail.OFFSET,
    "max_bytes": SafeDetail.MAX_BYTES,
    "expected_version": SafeDetail.EXPECTED_VERSION,
    "size": SafeDetail.SIZE,
    "sha256": SafeDetail.SHA256,
    "ttl_seconds": SafeDetail.TTL_SECONDS,
    "length": SafeDetail.LENGTH,
}


def _refusal(reason: FilesReason) -> ApplicationError:
    error_type = _REFUSAL_CODES[reason]
    return error_type(SafeDetail(reason.value))


@contextmanager
def _translated() -> Iterator[None]:
    """Map the domain's and the store's refusals to public errors, naming no value."""
    failure: ApplicationError | None = None
    try:
        yield
    except FilesRefusal as error:
        failure = _refusal(error.reason)
    except FilesArgumentError as error:
        detail = _ARGUMENT_DETAILS.get(error.field)
        failure = InvalidRequestError() if detail is None else InvalidRequestError(detail)
    except FileWorkspaceUnavailableError:
        failure = UnavailableError()
    if failure is not None:
        # Raised outside the handler, so no store error rides in `__context__`.
        raise failure


def _modified_at(mtime_ns: int) -> str:
    seconds, remainder = divmod(mtime_ns, 1_000_000_000)
    moment = datetime.fromtimestamp(seconds, UTC).replace(microsecond=remainder // 1000)
    return format_rfc3339(moment)


#: Contract section 18.3: a pending change's default lifetime (15 minutes).
APPROVAL_TTL_DEFAULT_SECONDS: Final = 900
#: Contract section 18.3: at most this many pending changes per workspace at once.
MAX_LIVE_PENDING_CHANGES: Final = 256
#: The pending changes one write expires at most (as trim T6's reap bound).
_PENDING_REAP_LIMIT: Final = 64
#: Contract section 18.3: the writes a pending change can carry.
PENDING_OPERATIONS: Final[frozenset[Capability]] = frozenset(
    {
        Capability.FILES_MKDIR,
        Capability.FILES_COPY,
        Capability.FILES_RENAME,
        Capability.FILES_MOVE,
        Capability.FILES_TRASH,
        Capability.FILES_RESTORE,
        Capability.FILES_WRITE_TEXT,
        Capability.FILES_UPLOAD_FINALIZE,
    }
)


@dataclass(frozen=True, slots=True)
class ComposedFileWorkspace:
    """One composed workspace (contract section 18.1-18.2).

    `store` serves reads, and the writes of a `direct` workspace. An
    `approval` workspace also has `staging` (its state directory's store, for
    upload and content staging) and `pending` (its pending change records).
    """

    workspace_id: str
    store: FileWorkspaceStore
    write_mode: WriteMode = WriteMode.DIRECT
    max_upload_bytes: int = MAX_UPLOAD_BYTES
    staging: FileWorkspaceStore | None = None
    pending: FilePendingChangeStore | None = None
    max_pending_bytes: int = DEFAULT_MAX_PENDING_BYTES
    #: Section 18.1 `clients=`: `None` admits every client its grants admit.
    allowed_clients: frozenset[str] | None = None
    sdcr_placement_gate: SDCRPlacementGate | None = None

    def __post_init__(self) -> None:
        approval = self.write_mode is WriteMode.APPROVAL
        if approval != (self.staging is not None and self.pending is not None):
            raise ValueError("an approval workspace, and only one, has staging and pending stores")

    def admits(self, authorization: Authorization) -> bool:
        """Whether this caller may see the workspace at all (section 18.1 `clients=`)."""
        if self.allowed_clients is None or authorization.transport is CaptureTransport.LOCAL:
            return True
        return authorization.authenticated_client_id in self.allowed_clients

    @property
    def staging_store(self) -> FileWorkspaceStore:
        """Where upload staging lives: the state directory's store, or the root's."""
        return self.store if self.staging is None else self.staging


def entry_shape(
    workspace_id: str, entry: FileWorkspaceEntry, *, sha256: bool = False
) -> dict[str, Any]:
    """Section 4's entry shape, workspace-relative."""
    shaped: dict[str, Any] = {
        "workspace_id": workspace_id,
        "path": entry.path,
        "name": entry.name,
        "kind": entry.kind.value,
        "size": entry.size,
        "modified_at": _modified_at(entry.mtime_ns),
        "version": entry.version,
    }
    if sha256:
        shaped["sha256"] = entry.sha256
    return shaped


def pending_binding(change: FilePendingChange) -> str:
    """Contract section 18.5: SHA-256 of the record's immutable fields, canonical JSON.

    The operator approves a change by this digest, so a record altered after
    review -- another operation, path, hash or bound version -- is refused.
    """
    document = {
        "pending_change_id": change.pending_change_id,
        "workspace_id": change.workspace_id,
        "owner_principal_id": change.owner_principal_id,
        "client_ref": change.client_ref,
        "operation": change.operation,
        "arguments": dict(change.arguments),
        "size": change.size,
        "sha256": change.sha256,
        "staged_upload_id": change.staged_upload_id,
        "created_at": change.created_at.isoformat(),
        "expires_at": change.expires_at.isoformat(),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


class FileWorkspaceApplication:
    """The 17 `files.*` handlers over the composed workspaces (see the module docstring)."""

    def __init__(
        self,
        store: FileWorkspaceStore | None = None,
        *,
        workspace_id: str = "mcp",
        max_upload_bytes: int = MAX_UPLOAD_BYTES,
        workspaces: Sequence[ComposedFileWorkspace] | None = None,
        handle_fetcher: FileHandleFetcher | None = None,
        public_origin: str | None = None,
        browser_downloads: BrowserDownloads | None = None,
        approval_ttl_seconds: int = APPROVAL_TTL_DEFAULT_SECONDS,
    ) -> None:
        if workspaces is None:
            if store is None:
                raise ValueError("a store or the composed workspaces are required")
            workspaces = (
                ComposedFileWorkspace(
                    workspace_id=workspace_id, store=store, max_upload_bytes=max_upload_bytes
                ),
            )
        elif store is not None or not workspaces:
            raise ValueError("name either one store or the composed workspaces")
        self._spaces: Final[Mapping[str, ComposedFileWorkspace]] = {
            space.workspace_id: space for space in workspaces
        }
        if len(self._spaces) != len(workspaces):
            raise ValueError("workspace aliases must be unique")
        self._default: Final = workspaces[0]
        self._approval_ttl: Final = timedelta(seconds=approval_ttl_seconds)
        self._approvals: Final = PendingWrites(self)
        self._handle_fetcher: Final = handle_fetcher
        #: Section 17.5: the origin a ticket's `transfer.url` is joined to.
        self._public_origin: Final = public_origin
        #: Section 17.6: `None` (the default) is the feature off.
        self._browser: Final = browser_downloads
        self._handlers: Final[Mapping[Capability, Callable[..., dict[str, Any]]]] = {
            Capability.FILES_WORKSPACES_LIST: self._workspaces_list,
            Capability.FILES_LIST: self._list,
            Capability.FILES_STAT: self._stat,
            Capability.FILES_SEARCH: self._search,
            Capability.FILES_PREVIEW: self._preview,
            Capability.FILES_HISTORY: self._history,
            Capability.FILES_DOWNLOAD_BEGIN: self._download_begin,
            Capability.FILES_MKDIR: self._mkdir,
            Capability.FILES_COPY: self._copy,
            Capability.FILES_UPLOAD_BEGIN: self._upload_begin,
            Capability.FILES_UPLOAD_ABORT: self._upload_abort,
            Capability.FILES_RENAME: self._rename,
            Capability.FILES_MOVE: self._move,
            Capability.FILES_TRASH: self._trash,
            Capability.FILES_RESTORE: self._restore,
            Capability.FILES_UPLOAD_FINALIZE: self._upload_finalize,
            Capability.FILES_WRITE_TEXT: self._write_text,
        }

    @property
    def store(self) -> FileWorkspaceStore:
        """The first workspace's store (the single-workspace composition's one store)."""
        return self._default.store

    @property
    def workspaces(self) -> tuple[ComposedFileWorkspace, ...]:
        """Every composed workspace, in configuration order (contract section 18.1)."""
        return tuple(self._spaces.values())

    @property
    def approval_ttl(self) -> timedelta:
        """Contract section 18.3: a pending change's lifetime."""
        return self._approval_ttl

    # ---- the one entry point ------------------------------------------------------

    def handle(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: Command
    ) -> dict[str, Any]:
        """Serve one `files.*` command: the grant re-check, the alias, then the handler."""
        capability = command.capability
        handler = self._handlers.get(capability)
        if handler is None:
            raise InternalError()
        # Defence in depth (G1-RD-008): `invoke` does not consult the grant set.
        if is_write_capability(capability):
            require_write_grant(authorization.capability_grants, capability)
        else:
            require_read_grant(authorization.capability_grants, capability)
        workspace_id = getattr(command, "workspace_id", self._default.workspace_id)
        space = self._spaces.get(workspace_id)
        if space is None or not space.admits(authorization):
            # An unlisted client is told the same as for an unknown alias.
            raise NotFoundError(SafeDetail.NOT_FOUND)
        writes = is_write_capability(capability)
        if writes and space.write_mode is WriteMode.READ_ONLY:
            raise UnsupportedError(SafeDetail.WORKSPACE_READ_ONLY)
        context = _Call(unit_of_work.file_workspace, authorization, space)
        with _translated():
            if writes and space.write_mode is WriteMode.APPROVAL:
                proposed = self._approvals.propose(context, command)
                if proposed is not None:
                    return proposed
            pending_change_id = getattr(command, "pending_change_id", None)
            if capability is Capability.FILES_HISTORY and pending_change_id is not None:
                return self._approvals.status(context, pending_change_id)
            return handler(context, command)

    # ---- shapes -------------------------------------------------------------------

    @staticmethod
    def _entry(call: _Call, entry: FileWorkspaceEntry, *, sha256: bool = False) -> dict[str, Any]:
        return entry_shape(call.workspace_id, entry, sha256=sha256)

    @staticmethod
    def _version_item(record: FileVersionRecord) -> dict[str, Any]:
        return {
            "item": "version",
            "version_id": record.version_id,
            "path": record.path,
            "version": record.version,
            "size": record.size,
            "sha256": record.sha256,
            "cause": record.cause,
            "recorded_at": format_rfc3339(record.captured_at),
        }

    @staticmethod
    def _trash_item(record: FileTrashRecord) -> dict[str, Any]:
        return {
            "item": "trash",
            "trash_item_id": record.trash_item_id,
            "path": record.original_path,
            "kind": record.kind.value,
            "version": record.original_version,
            "size": record.size,
            "recorded_at": format_rfc3339(record.trashed_at),
            "restored_at": None
            if record.restored_at is None
            else format_rfc3339(record.restored_at),
            "restored_path": record.restored_path,
        }

    # ---- reads ----------------------------------------------------------------------

    def _workspaces_list(self, call: _Call, command: ListFileWorkspaces) -> dict[str, Any]:
        del command
        # `writable` reflects the caller's grants only (any files write grant,
        # or no grant restriction). It does not read the remote process's
        # writes-disabled switch, which refuses a write at the boundary instead.
        grants = call.authorization.capability_grants
        granted = grants is None or any(
            granted_purposes(capability, grants)
            for capability in FILE_WORKSPACE_CAPABILITIES
            if is_write_capability(capability)
        )
        return {
            "workspaces": [
                {
                    "workspace_id": space.workspace_id,
                    "writable": granted and space.write_mode is not WriteMode.READ_ONLY,
                    "write_mode": space.write_mode.value,
                    "limits": {
                        "max_upload_bytes": space.max_upload_bytes,
                        "max_upload_chunk_bytes": MAX_UPLOAD_CHUNK_BYTES,
                        "max_preview_bytes": MAX_PREVIEW_BYTES,
                        "max_write_text_bytes": MAX_WRITE_TEXT_BYTES,
                        "page_size": PAGE_SIZE,
                        "search_walk_max_entries": SEARCH_WALK_MAX_ENTRIES,
                        "search_walk_max_depth": SEARCH_WALK_MAX_DEPTH,
                        "ticket_ttl_default_seconds": TICKET_TTL_DEFAULT_SECONDS,
                        "ticket_ttl_min_seconds": TICKET_TTL_MIN_SECONDS,
                        "ticket_ttl_max_seconds": TICKET_TTL_MAX_SECONDS,
                    },
                }
                for space in self._spaces.values()
                if space.admits(call.authorization)
            ]
        }

    def _list(self, call: _Call, command: ListFiles) -> dict[str, Any]:
        page = call.store.list_directory(
            command.path,
            after=command.after,
            page_size=PAGE_SIZE if command.page_size is None else command.page_size,
        )
        return {
            "entries": [self._entry(call, entry) for entry in page.entries],
            "next_after": page.next_after,
        }

    def _stat(self, call: _Call, command: StatFile) -> dict[str, Any]:
        entry = call.store.stat(command.path, include_sha256=command.include_sha256)
        return self._entry(call, entry, sha256=command.include_sha256)

    def _search(self, call: _Call, command: SearchFiles) -> dict[str, Any]:
        page = call.store.search(
            command.path,
            command.query,
            page_size=PAGE_SIZE if command.page_size is None else command.page_size,
        )
        return {
            "entries": [self._entry(call, entry) for entry in page.entries],
            "truncated": page.truncated,
        }

    def _preview(self, call: _Call, command: PreviewFile) -> dict[str, Any]:
        window = call.store.preview(
            command.path,
            offset=command.offset,
            max_bytes=command.max_bytes,
            expected_version=command.expected_version,
        )
        return {
            "text": window.text,
            "binary": window.binary,
            "next_offset": window.next_offset,
            "version": window.version,
        }

    def _history(self, call: _Call, command: GetFileHistory) -> dict[str, Any]:
        """Versions and trash items merged newest first, each stream on its own keyset.

        The cursor is the last version and the last trash item this page
        returned (`fwver_…,fwtrs_…`); a stream absent from it has returned
        nothing yet and starts from its newest row.
        """
        size = PAGE_SIZE if command.page_size is None else command.page_size
        after_version, after_trash = parse_files_history_cursor(command.after)
        owner = call.owner
        versions: FileHistoryPage = call.rows.list_versions(
            principal_id=owner,
            workspace_id=call.workspace_id,
            path=command.path,
            after=after_version,
            limit=size,
        )
        trash: FileHistoryPage = call.rows.list_trash(
            principal_id=owner,
            workspace_id=call.workspace_id,
            original_path=command.path,
            after=after_trash,
            limit=size,
        )
        merged: list[tuple[datetime, str, FileVersionRecord | FileTrashRecord]] = [
            (record.captured_at, record.version_id, record) for record in versions.versions
        ]
        merged.extend((record.trashed_at, record.trash_item_id, record) for record in trash.trash)
        merged.sort(key=lambda item: (item[0], item[1]), reverse=True)
        page = merged[:size]
        more = len(merged) > size or versions.next_after is not None or trash.next_after is not None
        last_version = after_version
        last_trash = after_trash
        items: list[dict[str, Any]] = []
        for _, identifier, record in page:
            if isinstance(record, FileVersionRecord):
                last_version = identifier
                items.append(self._version_item(record))
            else:
                last_trash = identifier
                items.append(self._trash_item(record))
        next_after = (
            ",".join(part for part in (last_version, last_trash) if part is not None)
            if more and page
            else None
        )
        return {"items": items, "next_after": next_after}

    def _download_begin(self, call: _Call, command: BeginFileDownload) -> dict[str, Any]:
        preserved: FileVersionRecord | None = None
        if command.version_id is not None:
            preserved = call.rows.get_version(command.version_id, principal_id=call.owner)
            if preserved is None or preserved.workspace_id != call.workspace_id:
                raise NotFoundError(SafeDetail.NOT_FOUND)
            reader = call.store.open_preserved_version(command.version_id)
            path = preserved.path
        else:
            assert command.path is not None  # noqa: S101 - the command requires one
            current = call.store.stat(command.path)
            if current.kind is not EntryKind.FILE:
                raise _refusal(FilesReason.UNSUPPORTED_ENTRY)
            if command.expected_version is not None and command.expected_version != current.version:
                raise _refusal(FilesReason.VERSION_CONFLICT)
            reader = call.store.open_download(command.path, expected_version=current.version)
            path = command.path
        try:
            size = reader.size
            version = reader.version
            sha256 = reader.sha256() if command.include_sha256 else None
        finally:
            reader.close()
        ttl = TICKET_TTL_DEFAULT_SECONDS if command.ttl_seconds is None else command.ttl_seconds
        download_id = issue_identifier(IdKind.FILE_DOWNLOAD)
        token, digest = mint_ticket_token()
        ticket = call.rows.create_transfer(
            transfer_id=download_id,
            principal_id=call.owner,
            client_ref=call.client_ref,
            kind=FileTransferKind.DOWNLOAD,
            workspace_id=call.workspace_id,
            path=path,
            expected_version=version,
            preserved_version_id=None if preserved is None else preserved.version_id,
            declared_size=size,
            declared_sha256=sha256,
            token_digest=digest,
            created_at=call.at,
            expires_at=call.at + timedelta(seconds=ttl),
        )
        answer: dict[str, Any] = {
            "download_id": download_id,
            "download_token": token,
            "route": _DOWNLOAD_ROUTE + download_id,
            "transfer": download_transfer(
                transfer_url(_DOWNLOAD_ROUTE + download_id, self._public_origin)
            ),
            "resource_uri": DOWNLOAD_RESOURCE_PREFIX + download_id,
            "name": parse_path(path).name,
            "size": size,
            "version": version,
            "expires_at": format_rfc3339(ticket.expires_at),
        }
        if command.include_sha256:
            answer["sha256"] = sha256
        link = self._browser_link(
            call, path=path, version=version, size=size, sha256=sha256, preserved=preserved
        )
        if link is not None:
            answer["browser_download"] = link
        return answer

    def _browser_link(
        self,
        call: _Call,
        *,
        path: str,
        version: str,
        size: int,
        sha256: str | None,
        preserved: FileVersionRecord | None,
    ) -> dict[str, Any] | None:
        """Section 17.6: a single-use browser link, for an allowlisted remote client only."""
        browser = self._browser
        authorization = call.authorization
        if (
            browser is None
            or authorization.transport is not CaptureTransport.REMOTE_CLIENT
            or authorization.authenticated_client_id not in browser.client_ids
        ):
            return None
        link_id = issue_identifier(IdKind.FILE_DOWNLOAD)
        token, digest = mint_browser_token()
        row = call.rows.create_transfer(
            transfer_id=link_id,
            principal_id=call.owner,
            client_ref=call.client_ref,
            kind=FileTransferKind.DOWNLOAD,
            workspace_id=call.workspace_id,
            path=path,
            expected_version=version,
            preserved_version_id=None if preserved is None else preserved.version_id,
            declared_size=size,
            declared_sha256=sha256,
            token_digest=digest,
            created_at=call.at,
            expires_at=call.at + timedelta(seconds=browser.ttl_seconds),
        )
        return {
            "url": browser.public_origin.rstrip("/")
            + BROWSER_DOWNLOAD_ROUTE
            + browser_link_segment(link_id, token),
            "expires_at": format_rfc3339(row.expires_at),
            "single_use": True,
            "instructions": BROWSER_DOWNLOAD_INSTRUCTIONS,
        }

    # ---- writes ---------------------------------------------------------------------

    def _receipt_answer(
        self, call: _Call, command: Command, arguments: Mapping[str, object]
    ) -> dict[str, Any] | None:
        """A taken key's stored answer (`replayed: true`), `conflict`, or `None` when free."""
        capability = command.capability.value
        existing = call.rows.get_receipt(
            principal_id=call.owner,
            client_ref=call.client_ref,
            capability=capability,
            idempotency_key=getattr(command, "idempotency_key"),  # noqa: B009
        )
        if existing is None:
            return None
        if existing.intent_digest != write_intent_digest(capability, arguments):
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        return {**existing.result, "replayed": True}

    def _write(
        self,
        call: _Call,
        command: Command,
        arguments: Mapping[str, object],
        perform: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """Lock, then replay or refuse a taken key, else perform and keep the receipt."""
        capability = command.capability.value
        key: str = getattr(command, "idempotency_key")  # noqa: B009 - every write has one
        call.rows.lock_workspace(call.workspace_id)
        intent = write_intent_digest(capability, arguments)
        existing = call.rows.get_receipt(
            principal_id=call.owner,
            client_ref=call.client_ref,
            capability=capability,
            idempotency_key=key,
        )
        if existing is not None:
            if existing.intent_digest != intent:
                raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
            return {**existing.result, "replayed": True}
        answer = perform()
        kept = {name: value for name, value in answer.items() if not name.endswith("_token")}
        _, inserted = call.rows.insert_receipt(
            receipt_id=issue_identifier(IdKind.FILE_RECEIPT),
            principal_id=call.owner,
            client_ref=call.client_ref,
            capability=capability,
            idempotency_key=key,
            intent_digest=intent,
            result=kept,
            created_at=call.at,
        )
        if not inserted:  # pragma: no cover - the workspace lock serializes the key
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        return {**answer, "replayed": False}

    def _mkdir(self, call: _Call, command: MakeFileDirectory) -> dict[str, Any]:
        arguments: dict[str, object] = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "parents": command.parents,
        }
        return self._write(
            call,
            command,
            arguments,
            lambda: self._entry(call, call.store.mkdir(command.path, parents=command.parents)),
        )

    def _copy(self, call: _Call, command: CopyFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "to_path": command.to_path,
            "expected_version": command.expected_version,
        }
        return self._write(
            call,
            command,
            arguments,
            lambda: self._entry(
                call,
                call.store.copy(
                    command.path, command.to_path, expected_version=command.expected_version
                ),
            ),
        )

    def _move_to(self, call: _Call, command: RenameFile | MoveFile, to_path: str) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "to_path": to_path,
            "expected_version": command.expected_version,
        }
        return self._write(
            call,
            command,
            arguments,
            lambda: self._entry(
                call,
                call.store.move(command.path, to_path, expected_version=command.expected_version),
            ),
        )

    def _rename(self, call: _Call, command: RenameFile) -> dict[str, Any]:
        target = parse_path(command.path).parent.join(command.new_name, "new_name")
        return self._move_to(call, command, target.text)

    def _move(self, call: _Call, command: MoveFile) -> dict[str, Any]:
        return self._move_to(call, command, command.to_path)

    def _trash(self, call: _Call, command: TrashFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "expected_version": command.expected_version,
        }

        def perform() -> dict[str, Any]:
            item_id = issue_identifier(IdKind.FILE_TRASH_ITEM)
            moved = call.store.trash(
                command.path, item_id, expected_version=command.expected_version
            )
            call.rows.record_trash(
                trash_item_id=item_id,
                principal_id=call.owner,
                workspace_id=call.workspace_id,
                original_path=moved.entry.path,
                kind=moved.entry.kind,
                original_version=moved.entry.version,
                trashed_version=moved.trashed_version,
                size=moved.entry.size,
                trashed_at=call.at,
            )
            return {"trash_item_id": item_id, "entry": self._entry(call, moved.entry)}

        return self._write(call, command, arguments, perform)

    def _restore(self, call: _Call, command: RestoreFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "trash_item_id": command.trash_item_id,
            "to_path": command.to_path,
        }

        def perform() -> dict[str, Any]:
            item = call.rows.get_trash_item(
                command.trash_item_id, principal_id=call.owner, for_update=True
            )
            if (
                item is None
                or item.workspace_id != call.workspace_id
                or item.restored_at is not None
            ):
                raise NotFoundError(SafeDetail.NOT_FOUND)
            target = item.original_path if command.to_path is None else command.to_path
            if call.space.sdcr_placement_gate is not None:
                try:
                    call.space.sdcr_placement_gate.admit_transition(
                        target, source=item.original_path
                    )
                except PlacementDenied:
                    raise _refusal(FilesReason.INVALID_PATH) from None
            entry = call.store.restore(
                command.trash_item_id, target, trashed_version=item.trashed_version
            )
            if (
                call.rows.mark_restored(
                    command.trash_item_id,
                    principal_id=call.owner,
                    restored_path=target,
                    now=call.at,
                )
                is None
            ):  # pragma: no cover - the row was locked unrestored above
                raise InternalError()
            return self._entry(call, entry)

        return self._write(call, command, arguments, perform)

    def _write_text(self, call: _Call, command: WriteFileText) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "text_sha256": hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
            "expected_version": command.expected_version,
        }

        def perform() -> dict[str, Any]:
            if command.expected_version is None:
                published = call.store.write_text(command.path, command.text)
                return self._published(call, published.entry, None)
            replaced = self._replaced(call, command.path, command.expected_version)
            version_id = issue_identifier(IdKind.FILE_VERSION)
            published = call.store.write_text(
                command.path,
                command.text,
                expected_version=command.expected_version,
                preimage_version_id=version_id,
            )
            self._record_preimage(call, published.preimage_version_id, replaced, "write_text")
            return self._published(call, published.entry, published.preimage_version_id)

        return self._write(call, command, arguments, perform)

    # ---- uploads --------------------------------------------------------------------

    def _upload_begin(self, call: _Call, command: BeginFileUpload) -> dict[str, Any]:
        if call.space.sdcr_placement_gate is not None:
            try:
                call.space.sdcr_placement_gate.admit_create(
                    command.path, is_directory=False, expected_version=command.expected_version
                )
            except PlacementDenied:
                raise _refusal(FilesReason.INVALID_PATH) from None
        if command.source_file is not None:
            return self._ingest_handle(call, command, command.source_file)
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "expected_version": command.expected_version,
            "size": command.size,
            "sha256": command.sha256,
            "ttl_seconds": command.ttl_seconds,
        }

        def perform() -> dict[str, Any]:
            self._reap(call)
            declaration = UploadDeclaration.of(
                size=command.size,
                sha256=command.sha256,
                ttl_seconds=command.ttl_seconds,
                max_upload_bytes=call.space.max_upload_bytes,
            )
            self._check_upload_target(call, command.path, command.expected_version)
            call.staging.ensure_free_space(0 if declaration.size is None else declaration.size)
            upload_id = issue_identifier(IdKind.FILE_UPLOAD)
            token, digest = mint_ticket_token()
            call.staging.begin_upload(upload_id)
            ticket = call.rows.create_transfer(
                transfer_id=upload_id,
                principal_id=call.owner,
                client_ref=call.client_ref,
                kind=FileTransferKind.UPLOAD,
                workspace_id=call.workspace_id,
                path=command.path,
                expected_version=command.expected_version,
                preserved_version_id=None,
                declared_size=declaration.size,
                declared_sha256=declaration.sha256,
                token_digest=digest,
                created_at=call.at,
                expires_at=call.at + timedelta(seconds=declaration.ttl_seconds),
            )
            return {
                "upload_id": upload_id,
                "upload_token": token,
                "route": _UPLOAD_ROUTE + upload_id,
                "transfer": upload_transfer(
                    transfer_url(_UPLOAD_ROUTE + upload_id, self._public_origin),
                    MAX_UPLOAD_CHUNK_BYTES,
                ),
                "offset": 0,
                "chunk_max_bytes": MAX_UPLOAD_CHUNK_BYTES,
                "expires_at": format_rfc3339(ticket.expires_at),
            }

        return self._write(call, command, arguments, perform)

    def _reap(self, call: _Call) -> None:
        """Trim T6: expire the caller's due tickets and discard the uploads' staging.

        Safe inside the transaction: a ticket due at `now` is unusable whatever
        its state column says (`FileTransferRecord.usable_at`), so its staging
        is never needed again even if this transaction rolls back.
        """
        expired = call.rows.expire_due(principal_id=call.owner, now=call.at, limit=_REAP_LIMIT)
        # Each ticket's staging is in its own workspace's staging store
        # (contract section 18.2); the caller's due tickets span workspaces.
        for space in self._spaces.values():
            space.staging_store.reap_uploads(
                record.transfer_id
                for record in expired
                if record.kind is FileTransferKind.UPLOAD
                and record.workspace_id == space.workspace_id
            )

    def _check_upload_target(self, call: _Call, path: str, expected_version: str | None) -> None:
        """Section 5: a create needs an absent target in a directory, a replace its version."""
        target = parse_path(path)
        try:
            current: FileWorkspaceEntry | None = call.store.stat(path)
        except FilesRefusal as refusal:
            if refusal.reason is not FilesReason.NOT_FOUND:
                raise
            current = None
        if current is None:
            if expected_version is not None:
                raise _refusal(FilesReason.NOT_FOUND)
            if not target.parent.is_root:
                parent = call.store.stat(target.parent.text)
                if parent.kind is not EntryKind.DIRECTORY:
                    raise _refusal(FilesReason.UNSUPPORTED_ENTRY)
            return
        if current.kind is not EntryKind.FILE:
            raise _refusal(FilesReason.UNSUPPORTED_ENTRY)
        if expected_version is None:
            raise _refusal(FilesReason.EXISTS)
        if expected_version != current.version:
            raise _refusal(FilesReason.VERSION_CONFLICT)

    def _owned_upload(self, call: _Call, upload_id: str) -> FileTransferRecord:
        ticket = call.rows.get_transfer(upload_id, principal_id=call.owner, for_update=True)
        if (
            ticket is None
            or ticket.kind is not FileTransferKind.UPLOAD
            or ticket.workspace_id != call.workspace_id
            or ticket.client_ref != call.client_ref
        ):
            raise NotFoundError(SafeDetail.NOT_FOUND)
        return ticket

    def _upload_abort(self, call: _Call, command: AbortFileUpload) -> dict[str, Any]:
        arguments = {"workspace_id": call.workspace_id, "upload_id": command.upload_id}

        def perform() -> dict[str, Any]:
            ticket = self._owned_upload(call, command.upload_id)
            if ticket.state is FileTransferState.OPEN:
                call.rows.settle_transfer(
                    command.upload_id,
                    principal_id=call.owner,
                    state=FileTransferState.ABORTED,
                    now=call.at,
                )
            elif ticket.state is not FileTransferState.ABORTED:
                raise _refusal(FilesReason.TICKET_INVALID)
            call.staging.discard_upload(command.upload_id)
            return {"upload_id": command.upload_id, "aborted": True}

        return self._write(call, command, arguments, perform)

    def _upload_finalize(self, call: _Call, command: FinalizeFileUpload) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "upload_id": command.upload_id,
            "length": command.length,
            "sha256": command.sha256,
        }

        def perform() -> dict[str, Any]:
            ticket = self._owned_upload(call, command.upload_id)
            if not ticket.usable_at(call.at):
                raise _refusal(FilesReason.TICKET_INVALID)
            return self._finalize_open(call, ticket, length=command.length, sha256=command.sha256)

        return self._write(call, command, arguments, perform)

    def _finalize_open(
        self,
        call: _Call,
        ticket: FileTransferRecord,
        *,
        length: int,
        sha256: str,
        operation: Capability = Capability.FILES_UPLOAD_FINALIZE,
    ) -> dict[str, Any]:
        """Verify an open, usable upload ticket's staged bytes and publish them (section 5)."""
        upload_id = ticket.transfer_id
        # Hashed once: the publication re-checks this fingerprint rather
        # than reading the staged bytes again under the workspace lock.
        staged_length, staged_sha256, staged_version = call.staging.upload_digest(upload_id)
        verify_staged(
            UploadCompletion(sha256=sha256, length=length),
            UploadDeclaration(
                size=ticket.declared_size,
                sha256=ticket.declared_sha256,
                ttl_seconds=TICKET_TTL_DEFAULT_SECONDS,
            ),
            staged_length=staged_length,
            staged_sha256=staged_sha256,
        )
        # The verified staged bytes are the upload's truth; the row's offset
        # (moved by the byte routes) is brought to them, forward only, before
        # the `finalized` state demands they agree.
        if ticket.received_bytes != staged_length and (
            staged_length < ticket.received_bytes
            or call.rows.advance_offset(
                upload_id,
                principal_id=call.owner,
                expected_offset=ticket.received_bytes,
                new_offset=staged_length,
                now=call.at,
            )
            is None
        ):
            raise _refusal(FilesReason.OFFSET_MISMATCH)
        if call.space.write_mode is WriteMode.APPROVAL:
            # Section 18.3: the verified staged bytes become a pending change.
            return self._approvals.pend_upload(
                call, ticket, length=length, sha256=sha256, operation=operation
            )
        if ticket.expected_version is None:
            published = call.store.publish_upload(
                upload_id,
                ticket.path,
                length=length,
                sha256=sha256,
                staged_version=staged_version,
            )
        else:
            replaced = self._replaced(
                call,
                ticket.path,
                ticket.expected_version,
                drift=FilesReason.EXTERNAL_CHANGE_DETECTED,
            )
            published = call.store.publish_upload(
                upload_id,
                ticket.path,
                length=length,
                sha256=sha256,
                expected_version=ticket.expected_version,
                preimage_version_id=issue_identifier(IdKind.FILE_VERSION),
                staged_version=staged_version,
            )
            self._record_preimage(call, published.preimage_version_id, replaced, "upload.finalize")
        if (
            call.rows.settle_transfer(
                upload_id,
                principal_id=call.owner,
                state=FileTransferState.FINALIZED,
                now=call.at,
            )
            is None
        ):  # pragma: no cover - the ticket was locked open above
            raise InternalError()
        return self._published(call, published.entry, published.preimage_version_id)

    # ---- native file handles (section 17.2) --------------------------------------------

    def _ingest_handle(
        self, call: _Call, command: BeginFileUpload, handle: Mapping[str, object]
    ) -> dict[str, Any]:
        """Fetch a client's native file handle into staging, then publish it in this call."""
        fetcher = self._handle_fetcher
        if fetcher is None:
            raise _refusal(FilesReason.FILE_HANDLE_UNSUPPORTED)
        url, file_id = handle.get("download_url"), handle.get("file_id")
        if not isinstance(url, str) or not isinstance(file_id, str):  # pragma: no cover
            raise InvalidRequestError(SafeDetail.SOURCE_FILE)  # the command checked both
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "expected_version": command.expected_version,
            "size": command.size,
            "sha256": command.sha256,
            # The handle's identity by digest only; never the bearer URL.
            "source_file_id_sha256": hashlib.sha256(file_id.encode("utf-8")).hexdigest(),
        }
        declaration = UploadDeclaration.of(
            size=command.size, sha256=command.sha256, max_upload_bytes=call.space.max_upload_bytes
        )
        # A retried key replays (or conflicts) before anything is fetched; the
        # receipt is read again under the lock by `_write`.
        replayed = self._receipt_answer(call, command, arguments)
        if replayed is not None:
            return replayed
        self._check_upload_target(call, command.path, command.expected_version)
        cap = call.space.max_upload_bytes if declaration.size is None else declaration.size
        upload_id = issue_identifier(IdKind.FILE_UPLOAD)
        call.staging.begin_upload(upload_id)
        pended = False
        try:
            length, digest = self._fetch_into(call, fetcher, url, upload_id, cap)

            def perform() -> dict[str, Any]:
                nonlocal pended
                self._reap(call)
                _token, token_digest = mint_ticket_token()  # never issued: closed below
                ticket = call.rows.create_transfer(
                    transfer_id=upload_id,
                    principal_id=call.owner,
                    client_ref=call.client_ref,
                    kind=FileTransferKind.UPLOAD,
                    workspace_id=call.workspace_id,
                    path=command.path,
                    expected_version=command.expected_version,
                    preserved_version_id=None,
                    declared_size=declaration.size,
                    declared_sha256=declaration.sha256,
                    token_digest=token_digest,
                    created_at=call.at,
                    expires_at=call.at + timedelta(seconds=TICKET_TTL_MIN_SECONDS),
                )
                published = self._finalize_open(
                    call,
                    ticket,
                    length=length,
                    sha256=digest,
                    operation=Capability.FILES_UPLOAD_BEGIN,
                )
                pended = published.get("approval_required") is True
                return {"upload_id": upload_id, **published, "size": length, "sha256": digest}

            return self._write(call, command, arguments, perform)
        finally:
            # Published bytes were renamed out of staging; anything left is
            # a refused, replayed or failed ingest's, and is never needed --
            # unless a pending change of an `approval` workspace now holds it.
            if not pended:
                with suppress(FilesRefusal, FileWorkspaceUnavailableError):
                    call.staging.discard_upload(upload_id)

    def _fetch_into(
        self, call: _Call, fetcher: FileHandleFetcher, url: str, upload_id: str, cap: int
    ) -> tuple[int, str]:
        """Stream the handle's body onto the staging file; its length and SHA-256."""
        hasher = hashlib.sha256()
        with fetcher.open(url, max_bytes=cap) as body:
            if body.declared_length is not None:
                call.staging.ensure_free_space(body.declared_length)

            def hashed() -> Iterator[bytes]:
                for chunk in body.chunks:
                    hasher.update(chunk)
                    yield chunk

            length = call.staging.append_upload(upload_id, 0, hashed(), limit=cap)
        return length, hasher.hexdigest()

    # ---- replacement ------------------------------------------------------------------

    def _replaced(
        self,
        call: _Call,
        path: str,
        expected_version: str,
        *,
        drift: FilesReason = FilesReason.VERSION_CONFLICT,
    ) -> FileWorkspaceEntry:
        """The file a replace will preserve: a file at exactly `expected_version`."""
        current = call.store.stat(path)
        if current.kind is not EntryKind.FILE:
            raise _refusal(FilesReason.UNSUPPORTED_ENTRY)
        if current.version != expected_version:
            raise _refusal(drift)
        return current

    def _record_preimage(
        self,
        call: _Call,
        version_id: str | None,
        replaced: FileWorkspaceEntry,
        operation: str,
    ) -> None:
        if version_id is None:  # pragma: no cover - a replace always preserves one
            raise InternalError()
        call.rows.record_version(
            version_id=version_id,
            principal_id=call.owner,
            workspace_id=call.workspace_id,
            path=replaced.path,
            version=replaced.version,
            size=0 if replaced.size is None else replaced.size,
            sha256=None,
            cause=f"files.{operation}",
            captured_at=call.at,
        )

    def _published(
        self, call: _Call, entry: FileWorkspaceEntry, preimage_version_id: str | None
    ) -> dict[str, Any]:
        return {"entry": self._entry(call, entry), "preimage_version_id": preimage_version_id}


class PendingWrites:
    """Contract section 18.3-18.4: an `approval` workspace's writes become pending changes.

    Every method runs inside `FileWorkspaceApplication.handle` (the grant
    re-check, the alias, the refusal translation); a builder runs under the
    workspace lock and the idempotency receipt (`_write`). Nothing here writes
    the workspace root: content is staged in the state directory.
    """

    def __init__(self, application: FileWorkspaceApplication) -> None:
        self._app = application

    # ---- dispatch -------------------------------------------------------------------

    def propose(self, call: _Call, command: Command) -> dict[str, Any] | None:
        """The pending answer for a write that becomes a change, or `None` to run the handler.

        `upload.begin` (a ticket) and `upload.abort` touch only the state
        directory and run their handler; `upload.finalize` and a native-handle
        `upload.begin` run theirs too and reach `pend_upload` from `_finalize_open`.
        """
        capability = command.capability
        builders: Mapping[Capability, Callable[[_Call, Any], dict[str, Any]]] = {
            Capability.FILES_MKDIR: self._mkdir,
            Capability.FILES_COPY: self._copy,
            Capability.FILES_RENAME: self._rename,
            Capability.FILES_MOVE: self._move,
            Capability.FILES_TRASH: self._trash,
            Capability.FILES_RESTORE: self._restore,
            Capability.FILES_WRITE_TEXT: self._write_text,
        }
        builder = builders.get(capability)
        return None if builder is None else builder(call, command)

    # ---- the request-time checks (section 18.3 step 1) ---------------------------------

    @staticmethod
    def _observed(call: _Call, path: str, expected_version: str | None) -> FileWorkspaceEntry:
        current = call.store.stat(path)
        if current.kind is EntryKind.OTHER:
            raise _refusal(FilesReason.UNSUPPORTED_ENTRY)
        if expected_version is not None and expected_version != current.version:
            raise _refusal(FilesReason.VERSION_CONFLICT)
        return current

    @staticmethod
    def _absent(call: _Call, path: str, *, parents: bool = False) -> None:
        """A create's target is absent and (unless `parents`) its parent is a directory."""
        target = parse_path(path)
        try:
            call.store.stat(path)
        except FilesRefusal as refusal:
            if refusal.reason is not FilesReason.NOT_FOUND:
                raise
        else:
            raise _refusal(FilesReason.EXISTS)
        if target.parent.is_root or parents:
            return
        parent = call.store.stat(target.parent.text)
        if parent.kind is not EntryKind.DIRECTORY:
            raise _refusal(FilesReason.UNSUPPORTED_ENTRY)

    # ---- builders -------------------------------------------------------------------------

    def _mkdir(self, call: _Call, command: MakeFileDirectory) -> dict[str, Any]:
        arguments: dict[str, object] = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "parents": command.parents,
        }

        def perform() -> dict[str, Any]:
            self._absent(call, command.path, parents=command.parents)
            return self._pend(call, command, {"path": command.path, "parents": command.parents})

        return self._app._write(call, command, arguments, perform)

    def _relocation(
        self, call: _Call, command: Command, path: str, to_path: str, expected: str | None
    ) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "path": path,
            "to_path": to_path,
            "expected_version": expected,
        }

        def perform() -> dict[str, Any]:
            current = self._observed(call, path, expected)
            self._absent(call, to_path)
            return self._pend(
                call, command, {"path": path, "to_path": to_path, "version": current.version}
            )

        return self._app._write(call, command, arguments, perform)

    def _copy(self, call: _Call, command: CopyFile) -> dict[str, Any]:
        return self._relocation(
            call, command, command.path, command.to_path, command.expected_version
        )

    def _rename(self, call: _Call, command: RenameFile) -> dict[str, Any]:
        target = parse_path(command.path).parent.join(command.new_name, "new_name")
        return self._relocation(call, command, command.path, target.text, command.expected_version)

    def _move(self, call: _Call, command: MoveFile) -> dict[str, Any]:
        return self._relocation(
            call, command, command.path, command.to_path, command.expected_version
        )

    def _trash(self, call: _Call, command: TrashFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "expected_version": command.expected_version,
        }

        def perform() -> dict[str, Any]:
            current = self._observed(call, command.path, command.expected_version)
            return self._pend(call, command, {"path": command.path, "version": current.version})

        return self._app._write(call, command, arguments, perform)

    def _restore(self, call: _Call, command: RestoreFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": call.workspace_id,
            "trash_item_id": command.trash_item_id,
            "to_path": command.to_path,
        }

        def perform() -> dict[str, Any]:
            item = call.rows.get_trash_item(command.trash_item_id, principal_id=call.owner)
            if (
                item is None
                or item.workspace_id != call.workspace_id
                or item.restored_at is not None
            ):
                raise NotFoundError(SafeDetail.NOT_FOUND)
            target = item.original_path if command.to_path is None else command.to_path
            self._absent(call, target)
            return self._pend(
                call,
                command,
                {
                    "trash_item_id": command.trash_item_id,
                    "to_path": target,
                    "trashed_version": item.trashed_version,
                },
            )

        return self._app._write(call, command, arguments, perform)

    def _write_text(self, call: _Call, command: WriteFileText) -> dict[str, Any]:
        data = command.text.encode("utf-8")
        sha256 = hashlib.sha256(data).hexdigest()
        arguments = {
            "workspace_id": call.workspace_id,
            "path": command.path,
            "text_sha256": sha256,
            "expected_version": command.expected_version,
        }

        def perform() -> dict[str, Any]:
            self._app._check_upload_target(call, command.path, command.expected_version)
            self._check_room(call, len(data))
            upload_id = issue_identifier(IdKind.FILE_UPLOAD)
            call.staging.ensure_free_space(len(data))
            call.staging.begin_upload(upload_id)
            try:
                length = call.staging.append_upload(upload_id, 0, iter((data,)), limit=len(data))
                if length != len(data):  # pragma: no cover - one whole chunk
                    raise _refusal(FilesReason.DIGEST_MISMATCH)
                return self._pend(
                    call,
                    command,
                    {"path": command.path, "expected_version": command.expected_version},
                    size=length,
                    sha256=sha256,
                    staged_upload_id=upload_id,
                    checked=True,
                )
            except BaseException:
                with suppress(FilesRefusal, FileWorkspaceUnavailableError):
                    call.staging.discard_upload(upload_id)
                raise

        return self._app._write(call, command, arguments, perform)

    def pend_upload(
        self,
        call: _Call,
        ticket: FileTransferRecord,
        *,
        length: int,
        sha256: str,
        operation: Capability = Capability.FILES_UPLOAD_FINALIZE,
    ) -> dict[str, Any]:
        """A verified, open upload ticket's staged bytes as a pending change (section 18.3).

        The ticket is settled `finalized`, so its token closes; its staging
        stays in the state directory, now held by the change.
        """
        self._app._check_upload_target(call, ticket.path, ticket.expected_version)
        if (
            call.rows.settle_transfer(
                ticket.transfer_id,
                principal_id=call.owner,
                state=FileTransferState.FINALIZED,
                now=call.at,
            )
            is None
        ):  # pragma: no cover - the ticket was locked open by the caller
            raise InternalError()
        return self._pend(
            call,
            operation,
            {"path": ticket.path, "expected_version": ticket.expected_version},
            size=length,
            sha256=sha256,
            staged_upload_id=ticket.transfer_id,
        )

    # ---- the record -------------------------------------------------------------------

    @staticmethod
    def _pending_store(call: _Call) -> FilePendingChangeStore:
        store = call.space.pending
        if store is None:  # pragma: no cover - only approval workspaces reach here
            raise InternalError()
        return store

    def _expire_due(self, call: _Call) -> list[FilePendingChange]:
        """Expire this workspace's due changes (under the lock); the live ones remain."""
        store = self._pending_store(call)
        live: list[FilePendingChange] = []
        reaped = 0
        for change in store.list_changes(limit=MAX_LIVE_PENDING_CHANGES * 2):
            if (
                change.status is FilePendingStatus.PENDING
                and change.expires_at <= call.at
                and reaped < _PENDING_REAP_LIMIT
            ):
                expire_change(call.space, change, now=call.at)
                reaped += 1
            else:
                live.append(change)
        return live

    def _check_room(self, call: _Call, size: int) -> list[FilePendingChange]:
        """Refuse `quota` past the live-change count or the staged-bytes cap."""
        live = self._expire_due(call)
        held = sum(change.size or 0 for change in live)
        if len(live) >= MAX_LIVE_PENDING_CHANGES or held + size > call.space.max_pending_bytes:
            raise _refusal(FilesReason.QUOTA)
        return live

    def _pend(
        self,
        call: _Call,
        command: Command | Capability,
        arguments: Mapping[str, object],
        *,
        size: int | None = None,
        sha256: str | None = None,
        staged_upload_id: str | None = None,
        checked: bool = False,
    ) -> dict[str, Any]:
        operation = command if isinstance(command, Capability) else command.capability
        if not checked:
            self._check_room(call, size or 0)
        change = FilePendingChange(
            pending_change_id=issue_identifier(IdKind.FILE_PENDING_CHANGE),
            workspace_id=call.workspace_id,
            owner_principal_id=call.owner,
            client_ref=call.client_ref,
            operation=operation.value,
            arguments=dict(arguments),
            size=size,
            sha256=sha256,
            staged_upload_id=staged_upload_id,
            created_at=call.at,
            expires_at=call.at + self._app.approval_ttl,
        )
        self._pending_store(call).create(change)
        return {
            "approval_required": True,
            "pending_change_id": change.pending_change_id,
            "status": FilePendingStatus.PENDING.value,
            "operation": change.operation,
            "expires_at": format_rfc3339(change.expires_at),
        }

    # ---- status (section 18.4) -----------------------------------------------------------

    def status(self, call: _Call, pending_change_id: str) -> dict[str, Any]:
        """The caller's own change, as `files.history`'s one item; anything else `not_found`."""
        store = call.space.pending
        change = None if store is None else store.get(pending_change_id)
        if (
            change is None
            or change.workspace_id != call.workspace_id
            or change.owner_principal_id != call.owner
            or not hmac.compare_digest(change.client_ref.encode(), call.client_ref.encode())
        ):
            raise NotFoundError(SafeDetail.NOT_FOUND)
        return {"items": [pending_item(change, now=call.at)], "next_after": None}


def pending_item(change: FilePendingChange, *, now: datetime) -> dict[str, Any]:
    """A change as a status item (section 18.4): workspace-relative, no token or text."""
    status = change.status
    if status is FilePendingStatus.PENDING and change.expires_at <= now:
        status = FilePendingStatus.EXPIRED
    arguments = change.arguments
    item: dict[str, Any] = {
        "item": "pending",
        "pending_change_id": change.pending_change_id,
        "operation": change.operation,
        "status": status.value,
        "path": arguments.get("path"),
        "to_path": arguments.get("to_path"),
        "trash_item_id": arguments.get("trash_item_id"),
        "size": change.size,
        "sha256": change.sha256,
        "created_at": format_rfc3339(change.created_at),
        "expires_at": format_rfc3339(change.expires_at),
        "decided_at": None if change.decided_at is None else format_rfc3339(change.decided_at),
    }
    if change.result is not None:
        item["result"] = dict(change.result)
    if change.reason is not None:
        item["reason"] = change.reason
    return item


def decide_change(
    space: ComposedFileWorkspace,
    change: FilePendingChange,
    *,
    status: FilePendingStatus,
    now: datetime,
    decision: str,
    result: Mapping[str, Any] | None = None,
    reason: str | None = None,
) -> FilePendingChange:
    """Move a change to `status`, discard its staged bytes when it is final, and record it."""
    pending = space.pending
    if pending is None:  # pragma: no cover - only approval workspaces hold changes
        raise InternalError()
    decided = replace(
        change,
        status=status,
        decided_at=now if status is not FilePendingStatus.APPLYING else None,
        result=None if result is None else dict(result),
        reason=reason,
    )
    pending.replace(decided)
    if status is not FilePendingStatus.APPLYING:
        if change.staged_upload_id is not None and space.staging is not None:
            with suppress(FilesRefusal, FileWorkspaceUnavailableError):
                space.staging.discard_upload(change.staged_upload_id)
        pending.record_decision(
            {
                "at": format_rfc3339(now),
                "pending_change_id": change.pending_change_id,
                "workspace_id": change.workspace_id,
                "operation": change.operation,
                "decision": decision,
                "status": status.value,
                "reason": reason,
            }
        )
        _APPROVAL_LOGGER.info(
            "files pending change %s: decision=%s status=%s reason=%s",
            change.pending_change_id,
            decision,
            status.value,
            reason or "-",
        )
    return decided


def expire_change(
    space: ComposedFileWorkspace, change: FilePendingChange, *, now: datetime
) -> FilePendingChange:
    """A due `pending` change becomes `expired` (section 18.3)."""
    return decide_change(
        space, change, status=FilePendingStatus.EXPIRED, now=now, decision="expired"
    )


class _Call:
    """One request's rows, workspace, Principal, client reference and time.

    The Principal and the client reference come from authentication only.
    `store` is the workspace's read (and `direct` write) store; `staging` the
    store holding upload staging -- the same store for a `direct` workspace,
    the state directory's for an `approval` one (contract section 18.2).
    """

    __slots__ = (
        "at",
        "authorization",
        "client_ref",
        "owner",
        "rows",
        "space",
        "staging",
        "store",
        "workspace_id",
    )

    rows: FileWorkspaceRepository
    authorization: Authorization
    space: ComposedFileWorkspace
    store: FileWorkspaceStore
    staging: FileWorkspaceStore
    workspace_id: str
    owner: str
    client_ref: str
    at: datetime

    def __init__(
        self,
        rows: FileWorkspaceRepository,
        authorization: Authorization,
        space: ComposedFileWorkspace,
    ) -> None:
        self.rows = rows
        self.space = space
        self.store = space.store
        self.staging = space.staging_store
        self.workspace_id = space.workspace_id
        self.authorization = authorization
        self.owner = authorization.principal.principal_id
        self.client_ref = _client_ref(authorization)
        self.at = authorization.at


def _client_ref(authorization: Authorization) -> str:
    """The server-derived client binding (`reports.transfer` T4's), never a request field.

    A remote client is its authenticated OAuth client id, a local caller its
    Principal; a remote authorization without a client id is a composition
    fault, never a fallback to the Principal.
    """
    if authorization.transport is CaptureTransport.REMOTE_CLIENT:
        client_id = authorization.authenticated_client_id
        if not client_id:
            raise InternalError()
        return client_ref_of(derive_creator(CreatorKind.REMOTE_CLIENT, client_id))
    if authorization.transport is CaptureTransport.LOCAL:
        return client_ref_of(
            derive_creator(CreatorKind.LOCAL_PRINCIPAL, authorization.principal.principal_id)
        )
    raise InternalError()
