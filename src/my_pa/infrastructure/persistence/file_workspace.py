"""The files workspace repository on PostgreSQL (files-workspace contract, WP4).

The four plane tables of revision `640aaacc78e8`, over the caller's open
connection, so every method commits or rolls back with the request:
`file_workspace_transfers` (upload and download tickets),
`file_workspace_versions` (preserved preimages), `file_workspace_trash` (trash
items) and `file_workspace_receipts` (idempotency receipts).

**Every statement but one is scoped by the authenticated Principal**: each
SELECT and UPDATE composes `_mine` over `partition_criterion`, each INSERT
`_bound` over `principal_bound_values`. A row of another Principal answers
exactly what an absent one answers, and a malformed identifier on a read is
the same `None`. The one deliberately unpartitioned read is
`authenticate_ticket`, the byte routes' bearer-ticket lookup: a route carries a
ticket, not a session, so the ticket's own row names its owner. It returns a
row only when the presented token's digest equals the stored one (constant
time) and the ticket is open, unexpired and of the route's kind; every other
case is one `None`, and every later statement of that request is scoped by
the owner the row named.

`now` is always the caller's, never the database clock. Opaque ids are minted
by the caller and only shape-checked here (`domain.files.transfer`). No
statement deletes a row; the guarded updates are the schema's
(`a_file_workspace_transfer_moves_forward`,
`a_file_workspace_trash_item_is_restored_once`). No row holds a body, a
`write_text` text, a preview text, a raw token or a host path (contract
section 11): a receipt result naming `text` or a `*_token` key is refused.
Application rules (CAS, idempotent replay, refusal mapping) are the caller's.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Connection,
    DateTime,
    RowMapping,
    Table,
    Text,
    literal,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.contracts.ports import (
    FileHistoryPage,
    FileReceiptRecord,
    FileTransferKind,
    FileTransferRecord,
    FileTransferState,
    FileTrashRecord,
    FileVersionRecord,
    FileWorkspaceRepository,
)
from my_pa.domain.files.errors import FilesArgumentError, FilesRefusal
from my_pa.domain.files.paths import parse_path
from my_pa.domain.files.transfer import (
    DOWNLOAD_ID_PREFIX,
    RECEIPT_ID_PREFIX,
    TRASH_ITEM_ID_PREFIX,
    UPLOAD_ID_PREFIX,
    VERSION_ID_PREFIX,
    parse_file_id,
    validate_sha256,
)
from my_pa.domain.files.versions import EntryKind, parse_version_token
from my_pa.domain.files.vocabulary import PAGE_SIZE
from my_pa.domain.identity.secret_digests import digests_match
from my_pa.domain.reports.transfer import CLIENT_REF_PATTERN
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    FILE_RECEIPT_CAPABILITIES,
    FILE_VERSION_CAUSES,
    file_workspace_receipts,
    file_workspace_transfers,
    file_workspace_trash,
    file_workspace_versions,
)

__all__ = ["MAX_EXPIRE_BATCH", "SqlFileWorkspaceRepository"]

#: The most tickets one `expire_due` call moves.
MAX_EXPIRE_BATCH: Final = 1000
_MAX_KEY_CHARACTERS: Final = 128
_CLIENT_REF: Final = re.compile(CLIENT_REF_PATTERN.replace("^", r"\A", 1).replace("$", r"\Z"))
_WORKSPACE_ALIAS: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
_TRASH_KINDS: Final = frozenset({EntryKind.FILE, EntryKind.DIRECTORY})
_SETTLED: Final = frozenset(
    {FileTransferState.FINALIZED, FileTransferState.ABORTED, FileTransferState.EXPIRED}
)
_TRANSFER_PREFIX: Final = {
    FileTransferKind.UPLOAD: UPLOAD_ID_PREFIX,
    FileTransferKind.DOWNLOAD: DOWNLOAD_ID_PREFIX,
}


# ---- argument checks (a fault here is a caller's programming error) ------------------


def _mine(table: Table, context: PrincipalContext) -> ColumnElement[bool]:
    return partition_criterion(table, context)


def _bound(values: dict[str, object], table: Table, context: PrincipalContext) -> dict[str, object]:
    return principal_bound_values(values, table, context)


def _utc(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.tzinfo.utcoffset(value) is None
    ):
        raise FilesArgumentError(field, "naive")
    return value.astimezone(UTC)


def _id(value: object, prefix: str, field: str) -> str:
    valid = parse_file_id(value, prefix)
    if valid is None:
        raise FilesArgumentError(field, "pattern")
    return valid


def _client_ref(value: object) -> str:
    if type(value) is not str or _CLIENT_REF.match(value) is None:
        raise FilesArgumentError("client_ref", "pattern")
    return value


def _workspace(value: object) -> str:
    if type(value) is not str or _WORKSPACE_ALIAS.match(value) is None:
        raise FilesArgumentError("workspace_id", "pattern")
    return value


def _path(value: object, field: str) -> str:
    """A non-root workspace path, unchanged (the domain's section 3 rules)."""
    try:
        parse_path(value, field)
    except FilesRefusal:
        raise FilesArgumentError(field, "pattern") from None
    assert isinstance(value, str)  # noqa: S101 - parse_path refused anything else
    return value


def _version(value: object, field: str) -> str:
    valid = parse_version_token(value)
    if valid is None:
        raise FilesArgumentError(field, "pattern")
    return valid


def _count(value: object, field: str) -> int:
    if type(value) is not int:
        raise FilesArgumentError(field, "type")
    if value < 0:
        raise FilesArgumentError(field, "bounds")
    return value


def _limit(value: object, ceiling: int) -> int:
    if type(value) is not int:
        raise FilesArgumentError("limit", "type")
    if not 1 <= value <= ceiling:
        raise FilesArgumentError("limit", "bounds")
    return value


def _key(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= _MAX_KEY_CHARACTERS:
        raise FilesArgumentError("idempotency_key", "bounds")
    return value


def _receipt_capability(value: object) -> str:
    if type(value) is not str or value not in FILE_RECEIPT_CAPABILITIES:
        raise FilesArgumentError("capability", "pattern")
    return value


def _check_result(value: object, *, depth: int = 0) -> None:
    """A receipt result names no `text` and no `*_token`, at any depth (section 11)."""
    if depth > 16:
        raise FilesArgumentError("result", "bounds")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if type(key) is not str:
                raise FilesArgumentError("result", "type")
            if key == "text" or key == "token" or key.endswith("_token"):
                raise FilesArgumentError("result", "pattern")
            _check_result(item, depth=depth + 1)
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes):
        for item in value:
            _check_result(item, depth=depth + 1)


# ---- hydration -----------------------------------------------------------------------


def _optional_str(value: object) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: object) -> int | None:
    return None if value is None else int(str(value))


def _transfer(row: RowMapping) -> FileTransferRecord:
    return FileTransferRecord(
        transfer_id=str(row["transfer_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        client_ref=str(row["client_ref"]),
        kind=FileTransferKind(row["kind"]),
        workspace_id=str(row["workspace_id"]),
        path=str(row["path"]),
        expected_version=_optional_str(row["expected_version"]),
        preserved_version_id=_optional_str(row["preserved_version_id"]),
        declared_size=_optional_int(row["declared_size"]),
        declared_sha256=_optional_str(row["declared_sha256"]),
        received_bytes=int(row["received_bytes"]),
        state=FileTransferState(row["state"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        finalized_at=row["finalized_at"],
        token_digest=str(row["token_digest"]),
    )


def _version_row(row: RowMapping) -> FileVersionRecord:
    return FileVersionRecord(
        version_id=str(row["version_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        workspace_id=str(row["workspace_id"]),
        path=str(row["path"]),
        version=str(row["version"]),
        size=int(row["size"]),
        sha256=_optional_str(row["sha256"]),
        cause=str(row["cause"]),
        captured_at=row["captured_at"],
    )


def _trash_row(row: RowMapping) -> FileTrashRecord:
    return FileTrashRecord(
        trash_item_id=str(row["trash_item_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        workspace_id=str(row["workspace_id"]),
        original_path=str(row["original_path"]),
        kind=EntryKind(row["kind"]),
        original_version=str(row["original_version"]),
        trashed_version=str(row["trashed_version"]),
        size=_optional_int(row["size"]),
        trashed_at=row["trashed_at"],
        restored_at=row["restored_at"],
        restored_path=_optional_str(row["restored_path"]),
    )


def _receipt_row(row: RowMapping) -> FileReceiptRecord:
    result: dict[str, Any] = dict(row["result"])
    return FileReceiptRecord(
        receipt_id=str(row["receipt_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        client_ref=str(row["client_ref"]),
        capability=str(row["capability"]),
        idempotency_key=str(row["idempotency_key"]),
        intent_digest=str(row["intent_digest"]),
        result=result,
        created_at=row["created_at"],
    )


class SqlFileWorkspaceRepository(FileWorkspaceRepository):
    """The files workspace port over one connection the caller owns (see the module docstring)."""

    def __init__(self, connection: Connection) -> None:
        self._connection: Final = connection

    # ---- tickets ---------------------------------------------------------------

    def create_transfer(
        self,
        *,
        transfer_id: str,
        principal_id: str,
        client_ref: str,
        kind: FileTransferKind,
        workspace_id: str,
        path: str,
        expected_version: str | None,
        preserved_version_id: str | None,
        declared_size: int | None,
        declared_sha256: str | None,
        token_digest: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> FileTransferRecord:
        context = capture_context(principal_id)
        if not isinstance(kind, FileTransferKind):
            raise FilesArgumentError("kind", "type")
        values: dict[str, object] = {
            "transfer_id": _id(transfer_id, _TRANSFER_PREFIX[kind], "transfer_id"),
            "client_ref": _client_ref(client_ref),
            "kind": kind.value,
            "workspace_id": _workspace(workspace_id),
            "path": _path(path, "path"),
            "expected_version": (
                None if expected_version is None else _version(expected_version, "expected_version")
            ),
            "preserved_version_id": (
                None
                if preserved_version_id is None
                else _id(preserved_version_id, VERSION_ID_PREFIX, "preserved_version_id")
            ),
            "declared_size": (
                None if declared_size is None else _count(declared_size, "declared_size")
            ),
            "declared_sha256": (
                None if declared_sha256 is None else validate_sha256(declared_sha256)
            ),
            "received_bytes": 0,
            "token_digest": validate_sha256(token_digest, "token_digest"),
            "state": FileTransferState.OPEN.value,
            "created_at": _utc(created_at, "created_at"),
            "expires_at": _utc(expires_at, "expires_at"),
            "finalized_at": None,
        }
        table = file_workspace_transfers
        row = (
            self._connection.execute(
                table.insert().values(**_bound(values, table, context)).returning(table)
            )
            .mappings()
            .one()
        )
        return _transfer(row)

    def get_transfer(
        self, transfer_id: str, *, principal_id: str, for_update: bool = False
    ) -> FileTransferRecord | None:
        context = capture_context(principal_id)
        valid = parse_file_id(transfer_id, UPLOAD_ID_PREFIX) or parse_file_id(
            transfer_id, DOWNLOAD_ID_PREFIX
        )
        if valid is None:
            return None
        table = file_workspace_transfers
        statement = select(table).where(_mine(table, context), table.c.transfer_id == valid)
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        return None if row is None else _transfer(row)

    def authenticate_ticket(
        self, transfer_id: str, token_digest: str, *, kind: FileTransferKind, now: datetime
    ) -> FileTransferRecord | None:
        at = _utc(now, "now")
        if not isinstance(kind, FileTransferKind):
            raise FilesArgumentError("kind", "type")
        valid = parse_file_id(transfer_id, _TRANSFER_PREFIX[kind])
        if valid is None or type(token_digest) is not str:
            return None
        table = file_workspace_transfers
        # Deliberately unpartitioned (module docstring): the bearer ticket names
        # its owner; nothing but a matching digest returns the row.
        row = (
            self._connection.execute(
                select(table).where(table.c.transfer_id == valid, table.c.kind == kind.value)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        ticket = _transfer(row)
        if not digests_match(ticket.token_digest, token_digest) or not ticket.usable_at(at):
            return None
        return ticket

    def advance_offset(
        self,
        transfer_id: str,
        *,
        principal_id: str,
        expected_offset: int,
        new_offset: int,
        now: datetime,
    ) -> FileTransferRecord | None:
        context = capture_context(principal_id)
        valid = _id(transfer_id, UPLOAD_ID_PREFIX, "transfer_id")
        expected = _count(expected_offset, "expected_offset")
        moved = _count(new_offset, "new_offset")
        if moved < expected:
            raise FilesArgumentError("new_offset", "bounds")
        at = _utc(now, "now")
        table = file_workspace_transfers
        row = (
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.transfer_id == valid,
                    table.c.kind == FileTransferKind.UPLOAD.value,
                    table.c.state == FileTransferState.OPEN.value,
                    table.c.expires_at > at,
                    table.c.received_bytes == expected,
                )
                .values(received_bytes=moved)
                .returning(table)
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _transfer(row)

    def settle_transfer(
        self,
        transfer_id: str,
        *,
        principal_id: str,
        state: FileTransferState,
        now: datetime,
    ) -> FileTransferRecord | None:
        context = capture_context(principal_id)
        if state not in _SETTLED:
            raise FilesArgumentError("state", "pattern")
        valid = parse_file_id(transfer_id, UPLOAD_ID_PREFIX) or parse_file_id(
            transfer_id, DOWNLOAD_ID_PREFIX
        )
        if valid is None:
            raise FilesArgumentError("transfer_id", "pattern")
        at = _utc(now, "now")
        table = file_workspace_transfers
        changes: dict[str, object] = {"state": state.value}
        if state is FileTransferState.FINALIZED:
            changes["finalized_at"] = at
        row = (
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.transfer_id == valid,
                    table.c.state == FileTransferState.OPEN.value,
                )
                .values(**changes)
                .returning(table)
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _transfer(row)

    def expire_due(
        self, *, principal_id: str, now: datetime, limit: int
    ) -> tuple[FileTransferRecord, ...]:
        context = capture_context(principal_id)
        at = _utc(now, "now")
        bound = _limit(limit, MAX_EXPIRE_BATCH)
        table = file_workspace_transfers
        due = [
            str(value)
            for value in self._connection.execute(
                select(table.c.transfer_id)
                .where(
                    _mine(table, context),
                    table.c.state == FileTransferState.OPEN.value,
                    table.c.expires_at <= at,
                )
                .order_by(table.c.expires_at, table.c.transfer_id)
                .limit(bound)
                .with_for_update(skip_locked=True)
            ).scalars()
        ]
        if not due:
            return ()
        rows = (
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.transfer_id.in_(due),
                    table.c.state == FileTransferState.OPEN.value,
                )
                .values(state=FileTransferState.EXPIRED.value)
                .returning(table)
            )
            .mappings()
            .all()
        )
        expired = sorted(
            (_transfer(row) for row in rows), key=lambda t: (t.expires_at, t.transfer_id)
        )
        return tuple(expired)

    # ---- preimages ---------------------------------------------------------------

    def record_version(
        self,
        *,
        version_id: str,
        principal_id: str,
        workspace_id: str,
        path: str,
        version: str,
        size: int,
        sha256: str | None,
        cause: str,
        captured_at: datetime,
    ) -> FileVersionRecord:
        context = capture_context(principal_id)
        if type(cause) is not str or cause not in FILE_VERSION_CAUSES:
            raise FilesArgumentError("cause", "pattern")
        values: dict[str, object] = {
            "version_id": _id(version_id, VERSION_ID_PREFIX, "version_id"),
            "workspace_id": _workspace(workspace_id),
            "path": _path(path, "path"),
            "version": _version(version, "version"),
            "size": _count(size, "size"),
            "sha256": None if sha256 is None else validate_sha256(sha256),
            "cause": cause,
            "captured_at": _utc(captured_at, "captured_at"),
        }
        table = file_workspace_versions
        row = (
            self._connection.execute(
                table.insert().values(**_bound(values, table, context)).returning(table)
            )
            .mappings()
            .one()
        )
        return _version_row(row)

    def get_version(self, version_id: str, *, principal_id: str) -> FileVersionRecord | None:
        context = capture_context(principal_id)
        valid = parse_file_id(version_id, VERSION_ID_PREFIX)
        if valid is None:
            return None
        table = file_workspace_versions
        row = (
            self._connection.execute(
                select(table).where(_mine(table, context), table.c.version_id == valid)
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _version_row(row)

    def list_versions(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        path: str | None = None,
        after: str | None = None,
        limit: int = PAGE_SIZE,
    ) -> FileHistoryPage:
        context = capture_context(principal_id)
        table = file_workspace_versions
        size = _limit(limit, PAGE_SIZE)
        where: list[ColumnElement[bool]] = [
            _mine(table, context),
            table.c.workspace_id == _workspace(workspace_id),
        ]
        if path is not None:
            where.append(table.c.path == _path(path, "path"))
        if after is not None:
            cursor = self.get_version(
                _id(after, VERSION_ID_PREFIX, "after"), principal_id=principal_id
            )
            if cursor is None or cursor.workspace_id != workspace_id:
                raise FilesArgumentError("after", "unknown")
            where.append(
                tuple_(table.c.captured_at, table.c.version_id)
                < tuple_(
                    literal(cursor.captured_at, DateTime(timezone=True)),
                    literal(cursor.version_id, Text),
                )
            )
        rows = (
            self._connection.execute(
                select(table)
                .where(*where)
                .order_by(table.c.captured_at.desc(), table.c.version_id.desc())
                .limit(size + 1)
            )
            .mappings()
            .all()
        )
        versions = tuple(_version_row(row) for row in rows[:size])
        next_after = versions[-1].version_id if len(rows) > size else None
        return FileHistoryPage(versions=versions, next_after=next_after)

    # ---- trash -------------------------------------------------------------------

    def record_trash(
        self,
        *,
        trash_item_id: str,
        principal_id: str,
        workspace_id: str,
        original_path: str,
        kind: EntryKind,
        original_version: str,
        trashed_version: str,
        size: int | None,
        trashed_at: datetime,
    ) -> FileTrashRecord:
        context = capture_context(principal_id)
        if kind not in _TRASH_KINDS:
            raise FilesArgumentError("kind", "pattern")
        if (kind is EntryKind.FILE) != (size is not None):
            raise FilesArgumentError("size", "pattern")
        values: dict[str, object] = {
            "trash_item_id": _id(trash_item_id, TRASH_ITEM_ID_PREFIX, "trash_item_id"),
            "workspace_id": _workspace(workspace_id),
            "original_path": _path(original_path, "original_path"),
            "kind": EntryKind(kind).value,
            "original_version": _version(original_version, "original_version"),
            "trashed_version": _version(trashed_version, "trashed_version"),
            "size": None if size is None else _count(size, "size"),
            "trashed_at": _utc(trashed_at, "trashed_at"),
            "restored_at": None,
            "restored_path": None,
        }
        table = file_workspace_trash
        row = (
            self._connection.execute(
                table.insert().values(**_bound(values, table, context)).returning(table)
            )
            .mappings()
            .one()
        )
        return _trash_row(row)

    def get_trash_item(
        self, trash_item_id: str, *, principal_id: str, for_update: bool = False
    ) -> FileTrashRecord | None:
        context = capture_context(principal_id)
        valid = parse_file_id(trash_item_id, TRASH_ITEM_ID_PREFIX)
        if valid is None:
            return None
        table = file_workspace_trash
        statement = select(table).where(_mine(table, context), table.c.trash_item_id == valid)
        if for_update:
            statement = statement.with_for_update()
        row = self._connection.execute(statement).mappings().one_or_none()
        return None if row is None else _trash_row(row)

    def mark_restored(
        self, trash_item_id: str, *, principal_id: str, restored_path: str, now: datetime
    ) -> FileTrashRecord | None:
        context = capture_context(principal_id)
        valid = _id(trash_item_id, TRASH_ITEM_ID_PREFIX, "trash_item_id")
        target = _path(restored_path, "restored_path")
        at = _utc(now, "now")
        table = file_workspace_trash
        row = (
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.trash_item_id == valid,
                    table.c.restored_at.is_(None),
                )
                .values(restored_at=at, restored_path=target)
                .returning(table)
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _trash_row(row)

    def list_trash(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        original_path: str | None = None,
        after: str | None = None,
        limit: int = PAGE_SIZE,
    ) -> FileHistoryPage:
        context = capture_context(principal_id)
        table = file_workspace_trash
        size = _limit(limit, PAGE_SIZE)
        where: list[ColumnElement[bool]] = [
            _mine(table, context),
            table.c.workspace_id == _workspace(workspace_id),
        ]
        if original_path is not None:
            where.append(table.c.original_path == _path(original_path, "original_path"))
        if after is not None:
            cursor = self.get_trash_item(
                _id(after, TRASH_ITEM_ID_PREFIX, "after"), principal_id=principal_id
            )
            if cursor is None or cursor.workspace_id != workspace_id:
                raise FilesArgumentError("after", "unknown")
            where.append(
                tuple_(table.c.trashed_at, table.c.trash_item_id)
                < tuple_(
                    literal(cursor.trashed_at, DateTime(timezone=True)),
                    literal(cursor.trash_item_id, Text),
                )
            )
        rows = (
            self._connection.execute(
                select(table)
                .where(*where)
                .order_by(table.c.trashed_at.desc(), table.c.trash_item_id.desc())
                .limit(size + 1)
            )
            .mappings()
            .all()
        )
        trash = tuple(_trash_row(row) for row in rows[:size])
        next_after = trash[-1].trash_item_id if len(rows) > size else None
        return FileHistoryPage(trash=trash, next_after=next_after)

    # ---- receipts ----------------------------------------------------------------

    def get_receipt(
        self, *, principal_id: str, client_ref: str, capability: str, idempotency_key: str
    ) -> FileReceiptRecord | None:
        context = capture_context(principal_id)
        table = file_workspace_receipts
        row = (
            self._connection.execute(
                select(table).where(
                    _mine(table, context),
                    table.c.client_ref == _client_ref(client_ref),
                    table.c.capability == _receipt_capability(capability),
                    table.c.idempotency_key == _key(idempotency_key),
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _receipt_row(row)

    def insert_receipt(
        self,
        *,
        receipt_id: str,
        principal_id: str,
        client_ref: str,
        capability: str,
        idempotency_key: str,
        intent_digest: str,
        result: Mapping[str, Any],
        created_at: datetime,
    ) -> tuple[FileReceiptRecord, bool]:
        context = capture_context(principal_id)
        if not isinstance(result, Mapping):
            raise FilesArgumentError("result", "type")
        _check_result(result)
        values: dict[str, object] = {
            "receipt_id": _id(receipt_id, RECEIPT_ID_PREFIX, "receipt_id"),
            "client_ref": _client_ref(client_ref),
            "capability": _receipt_capability(capability),
            "idempotency_key": _key(idempotency_key),
            "intent_digest": validate_sha256(intent_digest, "intent_digest"),
            "result": dict(result),
            "created_at": _utc(created_at, "created_at"),
        }
        table = file_workspace_receipts
        row = (
            self._connection.execute(
                pg_insert(table)
                .values(**_bound(values, table, context))
                .on_conflict_do_nothing(constraint="one_file_receipt_per_key")
                .returning(table)
            )
            .mappings()
            .one_or_none()
        )
        if row is not None:
            return _receipt_row(row), True
        existing = self.get_receipt(
            principal_id=principal_id,
            client_ref=client_ref,
            capability=capability,
            idempotency_key=idempotency_key,
        )
        if existing is None:  # pragma: no cover - the conflicting row is visible once committed
            raise FilesArgumentError("idempotency_key", "conflict")
        return existing, False
