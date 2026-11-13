"""The files workspace capabilities (`files.*`, ADR-019, files-workspace contract sections 5-8).

`ApplicationService` binds the 17 names here and holds no logic for them. Each
call runs inside the request's one unit of work, after `authorize` (which
writes the audit event: capability, purpose and outcome). Here:

- **Principal and client from authentication only.** The Principal is the
  Authorization's; the client reference is the server-derived writer
  (`"<creator kind>:<creator id>"`, the `reports.transfer` binding). No
  argument names either.
- **One workspace.** `workspace_id` must equal the configured alias
  (`MY_PA_FILES_WORKSPACE_ID`); any other is `not_found` (trim T8).
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

The filesystem is not transactional. A store mutation that succeeded is not
undone if a later row write fails and the transaction rolls back; the
fingerprint checks of the next call see the filesystem as it is.
Every refusal is a section 7 reason token (`SafeDetail`) under its public code
and names no path, content or token.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
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
    FileHistoryPage,
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
from my_pa.domain.files.paths import parse_path
from my_pa.domain.files.transfer import (
    UploadCompletion,
    UploadDeclaration,
    mint_ticket_token,
    verify_staged,
    write_intent_digest,
)
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import (
    MAX_PREVIEW_BYTES,
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
from my_pa.domain.identity.operation import Capability, granted_purposes, is_write_capability
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.transfer import client_ref_of
from my_pa.domain.source.registry import issue_identifier

__all__ = ["FILE_WORKSPACE_CAPABILITIES", "FileWorkspaceApplication"]

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

#: Section 10: the relative byte routes a ticket names.
_UPLOAD_ROUTE: Final = "/files/v1/uploads/"
_DOWNLOAD_ROUTE: Final = "/files/v1/downloads/"
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
    return _REFUSAL_CODES[reason](SafeDetail(reason.value))


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


class FileWorkspaceApplication:
    """The 17 `files.*` handlers over one composed store (see the module docstring)."""

    def __init__(
        self,
        store: FileWorkspaceStore,
        *,
        workspace_id: str,
        max_upload_bytes: int,
    ) -> None:
        self._store: Final = store
        self._workspace_id: Final = workspace_id
        self._max_upload_bytes: Final = max_upload_bytes
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
        workspace_id = getattr(command, "workspace_id", self._workspace_id)
        if workspace_id != self._workspace_id:
            raise NotFoundError(SafeDetail.NOT_FOUND)
        context = _Call(unit_of_work.file_workspace, authorization)
        with _translated():
            return handler(context, command)

    # ---- shapes -------------------------------------------------------------------

    def _entry(self, entry: FileWorkspaceEntry, *, sha256: bool = False) -> dict[str, Any]:
        shaped: dict[str, Any] = {
            "workspace_id": self._workspace_id,
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
        grants = call.authorization.capability_grants
        writable = grants is None or any(
            granted_purposes(capability, grants)
            for capability in FILE_WORKSPACE_CAPABILITIES
            if is_write_capability(capability)
        )
        return {
            "workspaces": [
                {
                    "workspace_id": self._workspace_id,
                    "writable": writable,
                    "limits": {
                        "max_upload_bytes": self._max_upload_bytes,
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
            ]
        }

    def _list(self, call: _Call, command: ListFiles) -> dict[str, Any]:
        del call
        page = self._store.list_directory(
            command.path,
            after=command.after,
            page_size=PAGE_SIZE if command.page_size is None else command.page_size,
        )
        return {
            "entries": [self._entry(entry) for entry in page.entries],
            "next_after": page.next_after,
        }

    def _stat(self, call: _Call, command: StatFile) -> dict[str, Any]:
        del call
        entry = self._store.stat(command.path, include_sha256=command.include_sha256)
        return self._entry(entry, sha256=command.include_sha256)

    def _search(self, call: _Call, command: SearchFiles) -> dict[str, Any]:
        del call
        page = self._store.search(
            command.path,
            command.query,
            page_size=PAGE_SIZE if command.page_size is None else command.page_size,
        )
        return {
            "entries": [self._entry(entry) for entry in page.entries],
            "truncated": page.truncated,
        }

    def _preview(self, call: _Call, command: PreviewFile) -> dict[str, Any]:
        del call
        window = self._store.preview(
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
            workspace_id=self._workspace_id,
            path=command.path,
            after=after_version,
            limit=size,
        )
        trash: FileHistoryPage = call.rows.list_trash(
            principal_id=owner,
            workspace_id=self._workspace_id,
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
            if preserved is None or preserved.workspace_id != self._workspace_id:
                raise NotFoundError(SafeDetail.NOT_FOUND)
            reader = self._store.open_preserved_version(command.version_id)
            path = preserved.path
        else:
            assert command.path is not None  # noqa: S101 - the command requires one
            current = self._store.stat(command.path)
            if current.kind is not EntryKind.FILE:
                raise _refusal(FilesReason.UNSUPPORTED_ENTRY)
            if command.expected_version is not None and command.expected_version != current.version:
                raise _refusal(FilesReason.VERSION_CONFLICT)
            reader = self._store.open_download(command.path, expected_version=current.version)
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
            workspace_id=self._workspace_id,
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
            "size": size,
            "version": version,
            "expires_at": format_rfc3339(ticket.expires_at),
        }
        if command.include_sha256:
            answer["sha256"] = sha256
        return answer

    # ---- writes ---------------------------------------------------------------------

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
        call.rows.lock_workspace(self._workspace_id)
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
            "workspace_id": self._workspace_id,
            "path": command.path,
            "parents": command.parents,
        }
        return self._write(
            call,
            command,
            arguments,
            lambda: self._entry(self._store.mkdir(command.path, parents=command.parents)),
        )

    def _copy(self, call: _Call, command: CopyFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
            "path": command.path,
            "to_path": command.to_path,
            "expected_version": command.expected_version,
        }
        return self._write(
            call,
            command,
            arguments,
            lambda: self._entry(
                self._store.copy(
                    command.path, command.to_path, expected_version=command.expected_version
                )
            ),
        )

    def _move_to(self, call: _Call, command: RenameFile | MoveFile, to_path: str) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
            "path": command.path,
            "to_path": to_path,
            "expected_version": command.expected_version,
        }
        return self._write(
            call,
            command,
            arguments,
            lambda: self._entry(
                self._store.move(command.path, to_path, expected_version=command.expected_version)
            ),
        )

    def _rename(self, call: _Call, command: RenameFile) -> dict[str, Any]:
        target = parse_path(command.path).parent.join(command.new_name, "new_name")
        return self._move_to(call, command, target.text)

    def _move(self, call: _Call, command: MoveFile) -> dict[str, Any]:
        return self._move_to(call, command, command.to_path)

    def _trash(self, call: _Call, command: TrashFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
            "path": command.path,
            "expected_version": command.expected_version,
        }

        def perform() -> dict[str, Any]:
            item_id = issue_identifier(IdKind.FILE_TRASH_ITEM)
            moved = self._store.trash(
                command.path, item_id, expected_version=command.expected_version
            )
            call.rows.record_trash(
                trash_item_id=item_id,
                principal_id=call.owner,
                workspace_id=self._workspace_id,
                original_path=moved.entry.path,
                kind=moved.entry.kind,
                original_version=moved.entry.version,
                trashed_version=moved.trashed_version,
                size=moved.entry.size,
                trashed_at=call.at,
            )
            return {"trash_item_id": item_id, "entry": self._entry(moved.entry)}

        return self._write(call, command, arguments, perform)

    def _restore(self, call: _Call, command: RestoreFile) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
            "trash_item_id": command.trash_item_id,
            "to_path": command.to_path,
        }

        def perform() -> dict[str, Any]:
            item = call.rows.get_trash_item(
                command.trash_item_id, principal_id=call.owner, for_update=True
            )
            if (
                item is None
                or item.workspace_id != self._workspace_id
                or item.restored_at is not None
            ):
                raise NotFoundError(SafeDetail.NOT_FOUND)
            target = item.original_path if command.to_path is None else command.to_path
            entry = self._store.restore(
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
            return self._entry(entry)

        return self._write(call, command, arguments, perform)

    def _write_text(self, call: _Call, command: WriteFileText) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
            "path": command.path,
            "text_sha256": hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
            "expected_version": command.expected_version,
        }

        def perform() -> dict[str, Any]:
            if command.expected_version is None:
                published = self._store.write_text(command.path, command.text)
                return self._published(published.entry, None)
            replaced = self._replaced(command.path, command.expected_version)
            version_id = issue_identifier(IdKind.FILE_VERSION)
            published = self._store.write_text(
                command.path,
                command.text,
                expected_version=command.expected_version,
                preimage_version_id=version_id,
            )
            self._record_preimage(call, published.preimage_version_id, replaced, "write_text")
            return self._published(published.entry, published.preimage_version_id)

        return self._write(call, command, arguments, perform)

    # ---- uploads --------------------------------------------------------------------

    def _upload_begin(self, call: _Call, command: BeginFileUpload) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
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
                max_upload_bytes=self._max_upload_bytes,
            )
            self._check_upload_target(command.path, command.expected_version)
            self._store.ensure_free_space(0 if declaration.size is None else declaration.size)
            upload_id = issue_identifier(IdKind.FILE_UPLOAD)
            token, digest = mint_ticket_token()
            self._store.begin_upload(upload_id)
            ticket = call.rows.create_transfer(
                transfer_id=upload_id,
                principal_id=call.owner,
                client_ref=call.client_ref,
                kind=FileTransferKind.UPLOAD,
                workspace_id=self._workspace_id,
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
        self._store.reap_uploads(
            record.transfer_id for record in expired if record.kind is FileTransferKind.UPLOAD
        )

    def _check_upload_target(self, path: str, expected_version: str | None) -> None:
        """Section 5: a create needs an absent target in a directory, a replace its version."""
        target = parse_path(path)
        try:
            current: FileWorkspaceEntry | None = self._store.stat(path)
        except FilesRefusal as refusal:
            if refusal.reason is not FilesReason.NOT_FOUND:
                raise
            current = None
        if current is None:
            if expected_version is not None:
                raise _refusal(FilesReason.NOT_FOUND)
            if not target.parent.is_root:
                parent = self._store.stat(target.parent.text)
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
            or ticket.workspace_id != self._workspace_id
            or ticket.client_ref != call.client_ref
        ):
            raise NotFoundError(SafeDetail.NOT_FOUND)
        return ticket

    def _upload_abort(self, call: _Call, command: AbortFileUpload) -> dict[str, Any]:
        arguments = {"workspace_id": self._workspace_id, "upload_id": command.upload_id}

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
            self._store.discard_upload(command.upload_id)
            return {"upload_id": command.upload_id, "aborted": True}

        return self._write(call, command, arguments, perform)

    def _upload_finalize(self, call: _Call, command: FinalizeFileUpload) -> dict[str, Any]:
        arguments = {
            "workspace_id": self._workspace_id,
            "upload_id": command.upload_id,
            "length": command.length,
            "sha256": command.sha256,
        }

        def perform() -> dict[str, Any]:
            ticket = self._owned_upload(call, command.upload_id)
            if not ticket.usable_at(call.at):
                raise _refusal(FilesReason.TICKET_INVALID)
            staged_length, staged_sha256 = self._store.upload_digest(command.upload_id)
            verify_staged(
                UploadCompletion(sha256=command.sha256, length=command.length),
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
                    command.upload_id,
                    principal_id=call.owner,
                    expected_offset=ticket.received_bytes,
                    new_offset=staged_length,
                    now=call.at,
                )
                is None
            ):
                raise _refusal(FilesReason.OFFSET_MISMATCH)
            if ticket.expected_version is None:
                published = self._store.publish_upload(
                    command.upload_id, ticket.path, length=command.length, sha256=command.sha256
                )
            else:
                replaced = self._replaced(
                    ticket.path,
                    ticket.expected_version,
                    drift=FilesReason.EXTERNAL_CHANGE_DETECTED,
                )
                published = self._store.publish_upload(
                    command.upload_id,
                    ticket.path,
                    length=command.length,
                    sha256=command.sha256,
                    expected_version=ticket.expected_version,
                    preimage_version_id=issue_identifier(IdKind.FILE_VERSION),
                )
                self._record_preimage(
                    call, published.preimage_version_id, replaced, "upload.finalize"
                )
            if (
                call.rows.settle_transfer(
                    command.upload_id,
                    principal_id=call.owner,
                    state=FileTransferState.FINALIZED,
                    now=call.at,
                )
                is None
            ):  # pragma: no cover - the ticket was locked open above
                raise InternalError()
            return self._published(published.entry, published.preimage_version_id)

        return self._write(call, command, arguments, perform)

    # ---- replacement ------------------------------------------------------------------

    def _replaced(
        self,
        path: str,
        expected_version: str,
        *,
        drift: FilesReason = FilesReason.VERSION_CONFLICT,
    ) -> FileWorkspaceEntry:
        """The file a replace will preserve: a file at exactly `expected_version`."""
        current = self._store.stat(path)
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
            workspace_id=self._workspace_id,
            path=replaced.path,
            version=replaced.version,
            size=0 if replaced.size is None else replaced.size,
            sha256=None,
            cause=f"files.{operation}",
            captured_at=call.at,
        )

    def _published(
        self, entry: FileWorkspaceEntry, preimage_version_id: str | None
    ) -> dict[str, Any]:
        return {"entry": self._entry(entry), "preimage_version_id": preimage_version_id}


class _Call:
    """One request's rows, Principal, client reference and time, from authentication only."""

    __slots__ = ("at", "authorization", "client_ref", "owner", "rows")

    def __init__(self, rows: FileWorkspaceRepository, authorization: Authorization) -> None:
        self.rows = rows
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
