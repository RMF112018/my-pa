"""The `files.*` handlers (files-workspace contract sections 5-7, WP5), without a database.

`FileWorkspaceApplication` over the real contained store on a synthetic
`tmp_path` root and an in-memory stand-in for the WP4 repository that keeps the
rows the handlers write. Every path, byte and identifier here is synthetic. The
advisory lock, the Principal partition and the stored CHECKs are proved against
PostgreSQL in `tests/database/test_files_workspace_application.py`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from my_pa.application.commands import (
    AbortFileUpload,
    BeginFileDownload,
    BeginFileUpload,
    Command,
    FinalizeFileUpload,
    GetFileHistory,
    ListFiles,
    ListFileWorkspaces,
    MakeFileDirectory,
    MoveFile,
    PreviewFile,
    RenameFile,
    RestoreFile,
    StatFile,
    TrashFile,
    WriteFileText,
)
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
    UnsupportedError,
)
from my_pa.application.file_workspace import FileWorkspaceApplication
from my_pa.contracts.ports import (
    FileHistoryPage,
    FileReceiptRecord,
    FileTransferKind,
    FileTransferRecord,
    FileTransferState,
    FileTrashRecord,
    FileVersionRecord,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.files.transfer import ticket_token_digest
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore

WORKSPACE = "mcp"
PRINCIPAL = "prn_fileswp5unit0001"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


class _Rows:
    """The WP4 repository's contract, in memory: rows the handlers write, scoped by owner."""

    def __init__(self) -> None:
        self.locks: list[str] = []
        self.transfers: dict[str, FileTransferRecord] = {}
        self.versions: dict[str, FileVersionRecord] = {}
        self.trash: dict[str, FileTrashRecord] = {}
        self.receipts: dict[tuple[str, str, str, str], FileReceiptRecord] = {}

    def lock_workspace(self, workspace_id: str) -> None:
        self.locks.append(workspace_id)

    def create_transfer(self, **values: Any) -> FileTransferRecord:  # noqa: ANN401
        record = FileTransferRecord(
            transfer_id=values["transfer_id"],
            owner_principal_id=values["principal_id"],
            client_ref=values["client_ref"],
            kind=values["kind"],
            workspace_id=values["workspace_id"],
            path=values["path"],
            expected_version=values["expected_version"],
            preserved_version_id=values["preserved_version_id"],
            declared_size=values["declared_size"],
            declared_sha256=values["declared_sha256"],
            received_bytes=0,
            state=FileTransferState.OPEN,
            created_at=values["created_at"],
            expires_at=values["expires_at"],
            finalized_at=None,
            token_digest=values["token_digest"],
        )
        self.transfers[record.transfer_id] = record
        return record

    def get_transfer(
        self, transfer_id: str, *, principal_id: str, for_update: bool = False
    ) -> FileTransferRecord | None:
        del for_update
        record = self.transfers.get(transfer_id)
        return record if record and record.owner_principal_id == principal_id else None

    def advance_offset(
        self,
        transfer_id: str,
        *,
        principal_id: str,
        expected_offset: int,
        new_offset: int,
        now: datetime,
    ) -> FileTransferRecord | None:
        record = self.get_transfer(transfer_id, principal_id=principal_id)
        if (
            record is None
            or not record.usable_at(now)
            or record.received_bytes != expected_offset
            or new_offset < expected_offset
        ):
            return None
        advanced = replace(record, received_bytes=new_offset)
        self.transfers[transfer_id] = advanced
        return advanced

    def settle_transfer(
        self, transfer_id: str, *, principal_id: str, state: FileTransferState, now: datetime
    ) -> FileTransferRecord | None:
        record = self.get_transfer(transfer_id, principal_id=principal_id)
        if record is None or record.state is not FileTransferState.OPEN:
            return None
        settled = replace(
            record,
            state=state,
            finalized_at=now if state is FileTransferState.FINALIZED else None,
        )
        self.transfers[transfer_id] = settled
        return settled

    def expire_due(
        self, *, principal_id: str, now: datetime, limit: int
    ) -> tuple[FileTransferRecord, ...]:
        due = [
            record
            for record in self.transfers.values()
            if record.owner_principal_id == principal_id
            and record.state is FileTransferState.OPEN
            and record.expires_at <= now
        ][:limit]
        return tuple(
            self.settle_transfer(
                record.transfer_id,
                principal_id=principal_id,
                state=FileTransferState.EXPIRED,
                now=now,
            )
            or record
            for record in due
        )

    def record_version(self, **values: Any) -> FileVersionRecord:  # noqa: ANN401
        record = FileVersionRecord(
            version_id=values["version_id"],
            owner_principal_id=values["principal_id"],
            workspace_id=values["workspace_id"],
            path=values["path"],
            version=values["version"],
            size=values["size"],
            sha256=values["sha256"],
            cause=values["cause"],
            captured_at=values["captured_at"],
        )
        self.versions[record.version_id] = record
        return record

    def get_version(self, version_id: str, *, principal_id: str) -> FileVersionRecord | None:
        record = self.versions.get(version_id)
        return record if record and record.owner_principal_id == principal_id else None

    @staticmethod
    def _page(rows: list[Any], key: str, after: str | None, limit: int) -> tuple[list[Any], bool]:
        stamp = "captured_at" if key == "version_id" else "trashed_at"
        rows.sort(key=lambda row: (getattr(row, stamp), getattr(row, key)), reverse=True)
        if after is not None:
            position = [getattr(row, key) for row in rows].index(after)
            rows = rows[position + 1 :]
        return rows[:limit], len(rows) > limit

    def list_versions(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        path: str | None = None,
        after: str | None = None,
        limit: int = 200,
    ) -> FileHistoryPage:
        rows = [
            row
            for row in self.versions.values()
            if row.owner_principal_id == principal_id
            and row.workspace_id == workspace_id
            and (path is None or row.path == path)
        ]
        page, more = self._page(rows, "version_id", after, limit)
        return FileHistoryPage(
            versions=tuple(page), next_after=page[-1].version_id if more else None
        )

    def record_trash(self, **values: Any) -> FileTrashRecord:  # noqa: ANN401
        record = FileTrashRecord(
            trash_item_id=values["trash_item_id"],
            owner_principal_id=values["principal_id"],
            workspace_id=values["workspace_id"],
            original_path=values["original_path"],
            kind=values["kind"],
            original_version=values["original_version"],
            trashed_version=values["trashed_version"],
            size=values["size"],
            trashed_at=values["trashed_at"],
        )
        self.trash[record.trash_item_id] = record
        return record

    def get_trash_item(
        self, trash_item_id: str, *, principal_id: str, for_update: bool = False
    ) -> FileTrashRecord | None:
        del for_update
        record = self.trash.get(trash_item_id)
        return record if record and record.owner_principal_id == principal_id else None

    def mark_restored(
        self, trash_item_id: str, *, principal_id: str, restored_path: str, now: datetime
    ) -> FileTrashRecord | None:
        record = self.get_trash_item(trash_item_id, principal_id=principal_id)
        if record is None or record.restored_at is not None:
            return None
        restored = replace(record, restored_at=now, restored_path=restored_path)
        self.trash[trash_item_id] = restored
        return restored

    def list_trash(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        original_path: str | None = None,
        after: str | None = None,
        limit: int = 200,
    ) -> FileHistoryPage:
        rows = [
            row
            for row in self.trash.values()
            if row.owner_principal_id == principal_id
            and row.workspace_id == workspace_id
            and (original_path is None or row.original_path == original_path)
        ]
        page, more = self._page(rows, "trash_item_id", after, limit)
        return FileHistoryPage(
            trash=tuple(page), next_after=page[-1].trash_item_id if more else None
        )

    def get_receipt(
        self, *, principal_id: str, client_ref: str, capability: str, idempotency_key: str
    ) -> FileReceiptRecord | None:
        return self.receipts.get((principal_id, client_ref, capability, idempotency_key))

    def insert_receipt(self, **values: Any) -> tuple[FileReceiptRecord, bool]:  # noqa: ANN401
        result = values["result"]
        assert not _names_a_token_or_text(result), "a receipt kept a token or a text"
        scope = (
            values["principal_id"],
            values["client_ref"],
            values["capability"],
            values["idempotency_key"],
        )
        existing = self.receipts.get(scope)
        if existing is not None:
            return existing, False
        record = FileReceiptRecord(
            receipt_id=values["receipt_id"],
            owner_principal_id=values["principal_id"],
            client_ref=values["client_ref"],
            capability=values["capability"],
            idempotency_key=values["idempotency_key"],
            intent_digest=values["intent_digest"],
            result=result,
            created_at=values["created_at"],
        )
        self.receipts[scope] = record
        return record, True


def _names_a_token_or_text(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key == "text" or str(key).endswith("_token") or _names_a_token_or_text(item)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple):
        return any(_names_a_token_or_text(item) for item in value)
    return False


class _World:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
        self.rows = _Rows()
        self.files = FileWorkspaceApplication(
            self.store, workspace_id=WORKSPACE, max_upload_bytes=1024
        )
        self.at = NOW

    def authorization(
        self,
        *,
        grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
        client: str | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            principal=SimpleNamespace(principal_id=PRINCIPAL),
            at=self.at,
            capability_grants=grants,
            transport=CaptureTransport.LOCAL if client is None else CaptureTransport.REMOTE_CLIENT,
            authenticated_client_id=client,
        )

    def run(self, command: Command, **authorization: Any) -> dict[str, Any]:  # noqa: ANN401
        return self.files.handle(
            SimpleNamespace(file_workspace=self.rows),  # type: ignore[arg-type]
            self.authorization(**authorization),  # type: ignore[arg-type]
            command,
        )


@pytest.fixture
def world(tmp_path: Path) -> Iterator[_World]:
    root = tmp_path / "workspace"
    root.mkdir()
    yield _World(root)


def _refused(world: _World, command: Command, kind: type[ApplicationError]) -> ApplicationError:
    with pytest.raises(kind) as caught:
        world.run(command)
    return caught.value


def _write(world: _World, path: str, text: str, key: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return world.run(
        WriteFileText(workspace_id=WORKSPACE, path=path, text=text, idempotency_key=key, **extra)
    )


# ---- the workspace and reads -----------------------------------------------------------


def test_the_one_workspace_is_listed_with_its_limits(world: _World) -> None:
    answer = world.run(ListFileWorkspaces())
    (workspace,) = answer["workspaces"]
    assert workspace["workspace_id"] == WORKSPACE
    assert workspace["writable"] is True
    assert workspace["limits"]["max_upload_bytes"] == 1024
    assert workspace["limits"]["ticket_ttl_default_seconds"] == 3600


def test_a_reader_without_a_write_grant_is_told_the_workspace_is_not_writable(
    world: _World,
) -> None:
    grants = frozenset({(Capability.FILES_WORKSPACES_LIST, Purpose.FILE_WORKSPACE_READ)})
    answer = world.run(ListFileWorkspaces(), grants=grants, client="synthetic-client")
    assert answer["workspaces"][0]["writable"] is False


def test_an_unknown_alias_is_not_found(world: _World) -> None:
    error = _refused(world, ListFiles(workspace_id="elsewhere", path=""), NotFoundError)
    assert error.safe_details == (SafeDetail.NOT_FOUND,)


def test_a_remote_caller_without_the_grant_is_refused_before_anything_is_read(
    world: _World,
) -> None:
    with pytest.raises(UnsupportedError):
        world.run(
            MakeFileDirectory(workspace_id=WORKSPACE, path="a", idempotency_key="k1"),
            grants=frozenset(),
            client="synthetic-client",
        )
    assert not (world.root / "a").exists()
    assert world.rows.locks == []


def test_list_stat_and_preview_answer_relative_entries_and_never_a_host_path(
    world: _World,
) -> None:
    _write(world, "notes.md", "hello synthetic", "k-write")
    listed = world.run(ListFiles(workspace_id=WORKSPACE, path=""))
    (entry,) = listed["entries"]
    assert entry["path"] == "notes.md" and entry["kind"] == "file" and entry["size"] == 15
    assert entry["version"].startswith("fv1_")
    assert entry["modified_at"].endswith("Z")
    assert str(world.root) not in repr(listed)
    stat = world.run(StatFile(workspace_id=WORKSPACE, path="notes.md", include_sha256=True))
    assert stat["sha256"] == hashlib.sha256(b"hello synthetic").hexdigest()
    preview = world.run(PreviewFile(workspace_id=WORKSPACE, path="notes.md"))
    assert preview == {
        "text": "hello synthetic",
        "binary": False,
        "next_offset": None,
        "version": entry["version"],
    }
    error = _refused(world, StatFile(workspace_id=WORKSPACE, path="absent.md"), NotFoundError)
    assert error.safe_details == (SafeDetail.NOT_FOUND,)


# ---- idempotency, CAS and no overwrite --------------------------------------------------


def test_a_replayed_key_answers_the_stored_result_and_touches_nothing(world: _World) -> None:
    command = MakeFileDirectory(workspace_id=WORKSPACE, path="Synthetic", idempotency_key="k-mk")
    first = world.run(command)
    assert first["replayed"] is False and first["kind"] == "directory"
    (world.root / "Synthetic").rmdir()
    again = world.run(command)
    assert again == {**first, "replayed": True}
    assert not (world.root / "Synthetic").exists(), "a replay touched the filesystem"
    assert world.rows.locks == [WORKSPACE, WORKSPACE]


def test_the_same_key_with_another_intent_is_a_conflict_on_the_key(world: _World) -> None:
    world.run(MakeFileDirectory(workspace_id=WORKSPACE, path="a", idempotency_key="k-same"))
    error = _refused(
        world,
        MakeFileDirectory(workspace_id=WORKSPACE, path="b", idempotency_key="k-same"),
        ConflictError,
    )
    assert error.safe_details == (SafeDetail.IDEMPOTENCY_KEY,)
    assert not (world.root / "b").exists()


def test_write_text_never_overwrites_and_a_replace_preserves_the_preimage(world: _World) -> None:
    created = _write(world, "a.txt", "one", "k-a1")
    assert created["preimage_version_id"] is None
    version = created["entry"]["version"]
    exists = _refused(
        world,
        WriteFileText(workspace_id=WORKSPACE, path="a.txt", text="two", idempotency_key="k-a2"),
        ConflictError,
    )
    assert exists.safe_details == (SafeDetail.EXISTS,)
    stale = _refused(
        world,
        WriteFileText(
            workspace_id=WORKSPACE,
            path="a.txt",
            text="two",
            idempotency_key="k-a3",
            expected_version="fv1_" + "0" * 64,
        ),
        ConflictError,
    )
    assert stale.safe_details == (SafeDetail.VERSION_CONFLICT,)
    replaced = _write(world, "a.txt", "two", "k-a4", expected_version=version)
    preimage = replaced["preimage_version_id"]
    assert preimage is not None and preimage.startswith("fwver_")
    assert (world.root / "a.txt").read_text() == "two"
    row = world.rows.versions[preimage]
    assert (row.path, row.version, row.size, row.cause) == ("a.txt", version, 3, "files.write_text")
    history = world.run(GetFileHistory(workspace_id=WORKSPACE, path="a.txt"))
    assert [item["version_id"] for item in history["items"]] == [preimage]
    (receipt,) = (
        row for key, row in world.rows.receipts.items() if key[2:] == ("files.write_text", "k-a4")
    )
    assert receipt.result["preimage_version_id"] == preimage


def test_move_and_rename_never_overwrite(world: _World) -> None:
    _write(world, "a.txt", "a", "k-1")
    _write(world, "b.txt", "b", "k-2")
    taken = _refused(
        world,
        MoveFile(workspace_id=WORKSPACE, path="a.txt", to_path="b.txt", idempotency_key="k-3"),
        ConflictError,
    )
    assert taken.safe_details == (SafeDetail.EXISTS,)
    renamed = world.run(
        RenameFile(workspace_id=WORKSPACE, path="a.txt", new_name="c.txt", idempotency_key="k-4")
    )
    assert renamed["path"] == "c.txt"
    world.run(MakeFileDirectory(workspace_id=WORKSPACE, path="d", idempotency_key="k-5"))
    moved = world.run(
        MoveFile(workspace_id=WORKSPACE, path="c.txt", to_path="d/c.txt", idempotency_key="k-6")
    )
    assert moved["path"] == "d/c.txt"
    assert (world.root / "d" / "c.txt").read_text() == "a"


# ---- trash and restore ------------------------------------------------------------------


def test_trash_and_restore_record_their_rows_and_restore_once(world: _World) -> None:
    created = _write(world, "t.txt", "trash me", "k-t1")
    trashed = world.run(TrashFile(workspace_id=WORKSPACE, path="t.txt", idempotency_key="k-t2"))
    item = trashed["trash_item_id"]
    assert item.startswith("fwtrs_") and not (world.root / "t.txt").exists()
    row = world.rows.trash[item]
    assert (row.original_path, row.kind, row.original_version, row.size) == (
        "t.txt",
        EntryKind.FILE,
        created["entry"]["version"],
        8,
    )
    restored = world.run(
        RestoreFile(workspace_id=WORKSPACE, trash_item_id=item, idempotency_key="k-t3")
    )
    assert restored["path"] == "t.txt" and (world.root / "t.txt").read_text() == "trash me"
    assert world.rows.trash[item].restored_path == "t.txt"
    again = _refused(
        world,
        RestoreFile(workspace_id=WORKSPACE, trash_item_id=item, idempotency_key="k-t4"),
        NotFoundError,
    )
    assert again.safe_details == (SafeDetail.NOT_FOUND,)


def test_history_merges_versions_and_trash_newest_first_across_pages(world: _World) -> None:
    created = _write(world, "h.txt", "1", "k-h1")
    version = created["entry"]["version"]
    for step in range(3):
        world.at = NOW + timedelta(minutes=step + 1)
        replaced = _write(world, "h.txt", str(step + 2), f"k-h{step + 2}", expected_version=version)
        version = replaced["entry"]["version"]
    world.at = NOW + timedelta(minutes=10)
    world.run(TrashFile(workspace_id=WORKSPACE, path="h.txt", idempotency_key="k-ht"))
    seen: list[str] = []
    after = None
    while True:
        page = world.run(
            GetFileHistory(workspace_id=WORKSPACE, path="h.txt", after=after, page_size=2)
        )
        seen.extend(item["item"] for item in page["items"])
        after = page["next_after"]
        if after is None:
            break
    assert seen == ["trash", "version", "version", "version"]


# ---- uploads and downloads --------------------------------------------------------------


def _begin(world: _World, path: str, key: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return world.run(
        BeginFileUpload(workspace_id=WORKSPACE, path=path, idempotency_key=key, **extra)
    )


def test_an_upload_publishes_verified_bytes_and_its_token_is_answered_once(world: _World) -> None:
    data = b"synthetic upload bytes"
    digest = hashlib.sha256(data).hexdigest()
    begun = _begin(world, "up.bin", "k-u1", size=len(data), sha256=digest)
    token = begun["upload_token"]
    upload = begun["upload_id"]
    assert token.startswith("gfwtk_") and begun["route"] == f"/files/v1/uploads/{upload}"
    ticket = world.rows.transfers[upload]
    assert ticket.token_digest == ticket_token_digest(token)
    assert token not in repr(world.rows.receipts)
    replay = _begin(world, "up.bin", "k-u1", size=len(data), sha256=digest)
    assert replay["replayed"] is True and "upload_token" not in replay
    assert replay["upload_id"] == upload
    world.store.append_upload(upload, 0, [data], limit=1024)
    mismatch = _refused(
        world,
        FinalizeFileUpload(
            workspace_id=WORKSPACE,
            upload_id=upload,
            length=len(data),
            sha256="0" * 64,
            idempotency_key="k-u2",
        ),
        ConflictError,
    )
    assert mismatch.safe_details == (SafeDetail.DIGEST_MISMATCH,)
    assert not (world.root / "up.bin").exists()
    published = world.run(
        FinalizeFileUpload(
            workspace_id=WORKSPACE,
            upload_id=upload,
            length=len(data),
            sha256=digest,
            idempotency_key="k-u3",
        )
    )
    assert published["entry"]["size"] == len(data) and published["preimage_version_id"] is None
    assert (world.root / "up.bin").read_bytes() == data
    assert world.rows.transfers[upload].state is FileTransferState.FINALIZED
    assert world.rows.transfers[upload].received_bytes == len(data)
    used = _refused(
        world,
        FinalizeFileUpload(
            workspace_id=WORKSPACE,
            upload_id=upload,
            length=len(data),
            sha256=digest,
            idempotency_key="k-u4",
        ),
        DeniedError,
    )
    assert used.safe_details == (SafeDetail.TICKET_INVALID,)


def test_an_upload_replace_needs_the_current_version_and_keeps_the_preimage(
    world: _World,
) -> None:
    current = _write(world, "r.bin", "old", "k-r1")["entry"]["version"]
    exists = _refused(
        world,
        BeginFileUpload(workspace_id=WORKSPACE, path="r.bin", idempotency_key="k-r2"),
        ConflictError,
    )
    assert exists.safe_details == (SafeDetail.EXISTS,)
    begun = _begin(world, "r.bin", "k-r3", expected_version=current)
    world.store.append_upload(begun["upload_id"], 0, [b"new"], limit=1024)
    published = world.run(
        FinalizeFileUpload(
            workspace_id=WORKSPACE,
            upload_id=begun["upload_id"],
            length=3,
            sha256=hashlib.sha256(b"new").hexdigest(),
            idempotency_key="k-r4",
        )
    )
    preimage = published["preimage_version_id"]
    assert world.rows.versions[preimage].cause == "files.upload.finalize"
    assert (world.root / "r.bin").read_bytes() == b"new"


def test_an_upload_larger_than_the_limit_is_too_large(world: _World) -> None:
    error = _refused(
        world,
        BeginFileUpload(workspace_id=WORKSPACE, path="big.bin", idempotency_key="k-b", size=2048),
        InvalidRequestError,
    )
    assert error.safe_details == (SafeDetail.TOO_LARGE,)


def test_abort_discards_the_staging_and_begin_reaps_expired_tickets(world: _World) -> None:
    first = _begin(world, "x.bin", "k-x1", ttl_seconds=300)
    second = _begin(world, "y.bin", "k-x2", ttl_seconds=300)
    aborted = world.run(
        AbortFileUpload(
            workspace_id=WORKSPACE, upload_id=first["upload_id"], idempotency_key="k-x3"
        )
    )
    assert aborted["aborted"] is True
    assert world.rows.transfers[first["upload_id"]].state is FileTransferState.ABORTED
    staging = world.root / ".my-pa" / "staging"
    assert {path.name for path in staging.iterdir()} == {second["upload_id"]}
    world.at = NOW + timedelta(seconds=301)
    _begin(world, "z.bin", "k-x4")
    assert world.rows.transfers[second["upload_id"]].state is FileTransferState.EXPIRED
    assert second["upload_id"] not in {path.name for path in staging.iterdir()}


def test_a_download_ticket_binds_the_current_version(world: _World) -> None:
    version = _write(world, "d.txt", "download me", "k-d1")["entry"]["version"]
    conflict = _refused(
        world,
        BeginFileDownload(workspace_id=WORKSPACE, path="d.txt", expected_version="fv1_" + "1" * 64),
        ConflictError,
    )
    assert conflict.safe_details == (SafeDetail.VERSION_CONFLICT,)
    begun = world.run(BeginFileDownload(workspace_id=WORKSPACE, path="d.txt", include_sha256=True))
    assert begun["download_token"].startswith("gfwtk_")
    assert begun["version"] == version and begun["size"] == 11
    assert begun["sha256"] == hashlib.sha256(b"download me").hexdigest()
    ticket = world.rows.transfers[begun["download_id"]]
    assert ticket.kind is FileTransferKind.DOWNLOAD and ticket.expected_version == version
    assert ticket.expires_at == NOW + timedelta(seconds=3600)
    assert not any(key[2] == "files.download.begin" for key in world.rows.receipts)
