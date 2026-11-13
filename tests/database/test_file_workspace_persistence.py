"""Files workspace WP4: the repository and the schema guards on PostgreSQL.

The `database` tier, each test on its own disposable head clone
(`migrated_engine`, revision `640aaacc78e8`; its upgrade and downgrade are
`tests/schema/test_files_workspace_migration.py`'s). It proves:

* tickets: create, Principal-scoped get, the byte routes' token
  authentication (digest, kind, state and expiry, one `None` for every miss),
  the offset guard (only from the expected offset, never backwards, not after
  expiry), settling once, and the bounded expiry sweep that skips a held row;
* preimages and trash: record, scoped get, newest-first pages with an `after`
  cursor, one guarded restore;
* receipts: insert once per (Principal, client, capability, key), the existing
  receipt on a taken key, and a refused result naming a text or a token;
* the schema itself: append-only versions and receipts, the guarded transfer
  and trash updates, no DELETE anywhere, TRUNCATE refused while a row exists,
  and the CHECKs on ids, kinds, states and digests;
* Principal isolation: another Principal's rows answer as absent.

No test can hang: lock waits are bounded (`lock_timeout`). Every identifier,
path and digest is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import FileTransferKind, FileTransferState
from my_pa.domain.files.errors import FilesArgumentError
from my_pa.domain.files.versions import EntryKind
from my_pa.infrastructure.persistence.file_workspace import SqlFileWorkspaceRepository

pytestmark = pytest.mark.database

P_A: Final = "prn_fwpersistaaaa0001"
P_B: Final = "prn_fwpersistbbbb0001"
CLIENT: Final = "remote_client:gcrt_" + "1" * 40
OTHER_CLIENT: Final = "local_principal:gcrt_" + "2" * 40
NOW: Final = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
V1: Final = "fv1_" + "1" * 64
V2: Final = "fv1_" + "2" * 64
SHA: Final = "a" * 64
TOKEN_DIGEST: Final = hashlib.sha256(b"synthetic ticket token bytes").hexdigest()
RESTRICT_VIOLATION: Final = "23001"
CHECK_VIOLATION: Final = "23514"
UNIQUE_VIOLATION: Final = "23505"


@contextmanager
def _repository(engine: Engine) -> Iterator[SqlFileWorkspaceRepository]:
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        yield SqlFileWorkspaceRepository(connection)


def _upload(
    repository: SqlFileWorkspaceRepository,
    transfer_id: str = "fwupl_upload000001",
    *,
    principal: str = P_A,
    declared_size: int | None = 10,
    expires_in: timedelta = timedelta(hours=1),
    created: datetime = NOW,
) -> None:
    repository.create_transfer(
        transfer_id=transfer_id,
        principal_id=principal,
        client_ref=CLIENT,
        kind=FileTransferKind.UPLOAD,
        workspace_id="mcp",
        path="docs/report.bin",
        expected_version=None,
        preserved_version_id=None,
        declared_size=declared_size,
        declared_sha256=SHA,
        token_digest=TOKEN_DIGEST,
        created_at=created,
        expires_at=created + expires_in,
    )


def _sqlstate(error: pytest.ExceptionInfo[DBAPIError]) -> str | None:
    return getattr(error.value.orig, "sqlstate", None)


# ---- tickets -------------------------------------------------------------------


def test_a_ticket_is_created_open_and_read_only_by_its_principal(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _upload(repository)
        mine = repository.get_transfer("fwupl_upload000001", principal_id=P_A)
        assert mine is not None
        assert mine.state is FileTransferState.OPEN
        assert (mine.kind, mine.received_bytes, mine.declared_size) == (
            FileTransferKind.UPLOAD,
            0,
            10,
        )
        assert mine.expected_version is None and mine.finalized_at is None
        assert TOKEN_DIGEST not in repr(mine)
        assert repository.get_transfer("fwupl_upload000001", principal_id=P_B) is None
        assert repository.get_transfer("not-an-id", principal_id=P_A) is None
        assert repository.get_transfer("fwupl_absent00001", principal_id=P_A) is None


def test_a_download_binds_its_version_and_size(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        created = repository.create_transfer(
            transfer_id="fwdnl_download00001",
            principal_id=P_A,
            client_ref=CLIENT,
            kind=FileTransferKind.DOWNLOAD,
            workspace_id="mcp",
            path="docs/report.bin",
            expected_version=V1,
            preserved_version_id="fwver_preimage0001",
            declared_size=0,
            declared_sha256=None,
            token_digest=TOKEN_DIGEST,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )
        assert created.kind is FileTransferKind.DOWNLOAD and created.declared_size == 0
        # The prefix names the kind: a download id cannot be an upload.
        with pytest.raises(FilesArgumentError):
            repository.create_transfer(
                transfer_id="fwdnl_download00002",
                principal_id=P_A,
                client_ref=CLIENT,
                kind=FileTransferKind.UPLOAD,
                workspace_id="mcp",
                path="a",
                expected_version=None,
                preserved_version_id=None,
                declared_size=None,
                declared_sha256=None,
                token_digest=TOKEN_DIGEST,
                created_at=NOW,
                expires_at=NOW + timedelta(hours=1),
            )


def test_authenticate_ticket_answers_only_a_matching_usable_ticket(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _upload(repository)
        found = repository.authenticate_ticket(
            "fwupl_upload000001", TOKEN_DIGEST, kind=FileTransferKind.UPLOAD, now=NOW
        )
        assert found is not None and found.owner_principal_id == P_A
        misses = (
            ("fwupl_upload000001", "b" * 64, FileTransferKind.UPLOAD, NOW),
            ("fwupl_upload000001", TOKEN_DIGEST, FileTransferKind.DOWNLOAD, NOW),
            ("fwupl_upload000001", TOKEN_DIGEST, FileTransferKind.UPLOAD, NOW + timedelta(hours=1)),
            ("fwupl_absent00001", TOKEN_DIGEST, FileTransferKind.UPLOAD, NOW),
            ("garbage", TOKEN_DIGEST, FileTransferKind.UPLOAD, NOW),
        )
        for transfer_id, digest, kind, at in misses:
            assert repository.authenticate_ticket(transfer_id, digest, kind=kind, now=at) is None
        repository.settle_transfer(
            "fwupl_upload000001", principal_id=P_A, state=FileTransferState.ABORTED, now=NOW
        )
        assert (
            repository.authenticate_ticket(
                "fwupl_upload000001", TOKEN_DIGEST, kind=FileTransferKind.UPLOAD, now=NOW
            )
            is None
        )


def test_the_offset_moves_only_from_the_expected_offset(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _upload(repository)
        moved = repository.advance_offset(
            "fwupl_upload000001", principal_id=P_A, expected_offset=0, new_offset=4, now=NOW
        )
        assert moved is not None and moved.received_bytes == 4
        stale = repository.advance_offset(
            "fwupl_upload000001", principal_id=P_A, expected_offset=0, new_offset=8, now=NOW
        )
        assert stale is None
        foreign = repository.advance_offset(
            "fwupl_upload000001", principal_id=P_B, expected_offset=4, new_offset=8, now=NOW
        )
        assert foreign is None
        late = repository.advance_offset(
            "fwupl_upload000001",
            principal_id=P_A,
            expected_offset=4,
            new_offset=8,
            now=NOW + timedelta(hours=2),
        )
        assert late is None
        with pytest.raises(FilesArgumentError):
            repository.advance_offset(
                "fwupl_upload000001", principal_id=P_A, expected_offset=4, new_offset=2, now=NOW
            )
        current = repository.get_transfer("fwupl_upload000001", principal_id=P_A)
        assert current is not None and current.received_bytes == 4


def test_the_declared_size_bounds_the_offset(migrated_engine: Engine) -> None:
    with pytest.raises(DBAPIError) as refused, _repository(migrated_engine) as repository:
        _upload(repository)
        repository.advance_offset(
            "fwupl_upload000001", principal_id=P_A, expected_offset=0, new_offset=11, now=NOW
        )
    assert _sqlstate(refused) == CHECK_VIOLATION


def test_settling_happens_once(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _upload(repository, declared_size=None)
        settled = repository.settle_transfer(
            "fwupl_upload000001", principal_id=P_A, state=FileTransferState.FINALIZED, now=NOW
        )
        assert settled is not None
        assert settled.state is FileTransferState.FINALIZED and settled.finalized_at == NOW
        again = repository.settle_transfer(
            "fwupl_upload000001", principal_id=P_A, state=FileTransferState.ABORTED, now=NOW
        )
        assert again is None
        with pytest.raises(FilesArgumentError):
            repository.settle_transfer(
                "fwupl_upload000001", principal_id=P_A, state=FileTransferState.OPEN, now=NOW
            )


def test_a_finalize_needs_every_declared_byte(migrated_engine: Engine) -> None:
    with pytest.raises(DBAPIError) as refused, _repository(migrated_engine) as repository:
        _upload(repository)
        repository.settle_transfer(
            "fwupl_upload000001", principal_id=P_A, state=FileTransferState.FINALIZED, now=NOW
        )
    assert _sqlstate(refused) == CHECK_VIOLATION


def test_expire_due_moves_the_due_open_tickets_oldest_first(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _upload(repository, "fwupl_due000000002", created=NOW - timedelta(hours=2))
        _upload(
            repository,
            "fwupl_due000000001",
            created=NOW - timedelta(hours=3),
        )
        _upload(repository, "fwupl_live00000001")
        _upload(repository, "fwupl_other0000001", principal=P_B, created=NOW - timedelta(hours=3))
        expired = repository.expire_due(principal_id=P_A, now=NOW, limit=10)
        assert [ticket.transfer_id for ticket in expired] == [
            "fwupl_due000000001",
            "fwupl_due000000002",
        ]
        assert all(ticket.state is FileTransferState.EXPIRED for ticket in expired)
        assert repository.expire_due(principal_id=P_A, now=NOW, limit=10) == ()
        other = repository.get_transfer("fwupl_other0000001", principal_id=P_B)
        assert other is not None and other.state is FileTransferState.OPEN


def test_expire_due_skips_a_ticket_another_transaction_holds(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _upload(repository, "fwupl_held00000001", created=NOW - timedelta(hours=2))
        _upload(repository, "fwupl_free00000001", created=NOW - timedelta(hours=2))
    with migrated_engine.connect() as holder, holder.begin():
        held = SqlFileWorkspaceRepository(holder)
        assert held.get_transfer("fwupl_held00000001", principal_id=P_A, for_update=True)
        with _repository(migrated_engine) as repository:
            expired = repository.expire_due(principal_id=P_A, now=NOW, limit=10)
        assert [ticket.transfer_id for ticket in expired] == ["fwupl_free00000001"]


# ---- preimages and trash ----------------------------------------------------------


def test_versions_page_newest_first_with_an_after_cursor(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        for index in range(5):
            repository.record_version(
                version_id=f"fwver_page0000000{index}",
                principal_id=P_A,
                workspace_id="mcp",
                path="a.txt" if index % 2 == 0 else "b.txt",
                version=V1,
                size=index,
                sha256=None if index else SHA,
                cause="files.write_text",
                captured_at=NOW + timedelta(minutes=index),
            )
        first = repository.list_versions(principal_id=P_A, workspace_id="mcp", limit=2)
        assert [v.version_id for v in first.versions] == [
            "fwver_page00000004",
            "fwver_page00000003",
        ]
        assert first.next_after == "fwver_page00000003"
        second = repository.list_versions(
            principal_id=P_A, workspace_id="mcp", after=first.next_after, limit=2
        )
        assert [v.version_id for v in second.versions] == [
            "fwver_page00000002",
            "fwver_page00000001",
        ]
        last = repository.list_versions(
            principal_id=P_A, workspace_id="mcp", after=second.next_after, limit=2
        )
        assert [v.version_id for v in last.versions] == ["fwver_page00000000"]
        assert last.next_after is None
        by_path = repository.list_versions(principal_id=P_A, workspace_id="mcp", path="a.txt")
        assert [v.version_id for v in by_path.versions] == [
            "fwver_page00000004",
            "fwver_page00000002",
            "fwver_page00000000",
        ]
        assert repository.list_versions(principal_id=P_B, workspace_id="mcp").versions == ()
        got = repository.get_version("fwver_page00000000", principal_id=P_A)
        assert got is not None and got.sha256 == SHA and got.size == 0
        assert repository.get_version("fwver_page00000000", principal_id=P_B) is None
        with pytest.raises(FilesArgumentError):
            repository.list_versions(principal_id=P_A, workspace_id="mcp", limit=201)
        with pytest.raises(FilesArgumentError):
            repository.list_versions(
                principal_id=P_B, workspace_id="mcp", after="fwver_page00000001"
            )


def _trash(repository: SqlFileWorkspaceRepository, trash_item_id: str, **overrides: object) -> None:
    values: dict[str, object] = {
        "trash_item_id": trash_item_id,
        "principal_id": P_A,
        "workspace_id": "mcp",
        "original_path": "dir/a.txt",
        "kind": EntryKind.FILE,
        "original_version": V1,
        "trashed_version": V2,
        "size": 3,
        "trashed_at": NOW,
    }
    values.update(overrides)
    repository.record_trash(**values)  # type: ignore[arg-type]


def test_a_trash_item_is_restored_once(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        _trash(repository, "fwtrs_item00000001")
        _trash(
            repository,
            "fwtrs_item00000002",
            kind=EntryKind.DIRECTORY,
            size=None,
            original_path="dir",
            trashed_at=NOW + timedelta(minutes=1),
        )
        item = repository.get_trash_item("fwtrs_item00000001", principal_id=P_A, for_update=True)
        assert item is not None and item.restored_at is None and item.kind is EntryKind.FILE
        assert repository.get_trash_item("fwtrs_item00000001", principal_id=P_B) is None
        assert (
            repository.mark_restored(
                "fwtrs_item00000001", principal_id=P_B, restored_path="x", now=NOW
            )
            is None
        )
        restored = repository.mark_restored(
            "fwtrs_item00000001", principal_id=P_A, restored_path="dir/b.txt", now=NOW
        )
        assert restored is not None
        assert (restored.restored_at, restored.restored_path) == (NOW, "dir/b.txt")
        assert (
            repository.mark_restored(
                "fwtrs_item00000001", principal_id=P_A, restored_path="dir/c.txt", now=NOW
            )
            is None
        )
        page = repository.list_trash(principal_id=P_A, workspace_id="mcp", limit=1)
        assert [t.trash_item_id for t in page.trash] == ["fwtrs_item00000002"]
        rest = repository.list_trash(principal_id=P_A, workspace_id="mcp", after=page.next_after)
        assert [t.trash_item_id for t in rest.trash] == ["fwtrs_item00000001"]
        assert rest.next_after is None
        by_path = repository.list_trash(principal_id=P_A, workspace_id="mcp", original_path="dir")
        assert [t.trash_item_id for t in by_path.trash] == ["fwtrs_item00000002"]
        with pytest.raises(FilesArgumentError):
            _trash(repository, "fwtrs_item00000003", kind=EntryKind.OTHER)
        with pytest.raises(FilesArgumentError):
            _trash(repository, "fwtrs_item00000003", size=None)


# ---- receipts ----------------------------------------------------------------------


def _receipt(
    repository: SqlFileWorkspaceRepository,
    receipt_id: str,
    *,
    principal: str = P_A,
    client: str = CLIENT,
    capability: str = "files.mkdir",
    key: str = "key-0001",
    intent: str = SHA,
    result: dict[str, object] | None = None,
) -> tuple[object, bool]:
    return repository.insert_receipt(
        receipt_id=receipt_id,
        principal_id=principal,
        client_ref=client,
        capability=capability,
        idempotency_key=key,
        intent_digest=intent,
        result={"entry": {"path": "new", "kind": "directory"}} if result is None else result,
        created_at=NOW,
    )


def test_a_receipt_is_inserted_once_per_key_scope(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository:
        first, inserted = _receipt(repository, "fwrcp_receipt00001")
        assert inserted
        existing, inserted_again = _receipt(repository, "fwrcp_receipt00002", intent="b" * 64)
        assert not inserted_again
        assert existing == first
        assert existing.intent_digest == SHA  # type: ignore[attr-defined]
        assert existing.result == {"entry": {"path": "new", "kind": "directory"}}  # type: ignore[attr-defined]
        # Each scope component makes a separate key.
        assert _receipt(repository, "fwrcp_receipt00003", principal=P_B)[1]
        assert _receipt(repository, "fwrcp_receipt00004", client=OTHER_CLIENT)[1]
        assert _receipt(repository, "fwrcp_receipt00005", capability="files.copy")[1]
        assert _receipt(repository, "fwrcp_receipt00006", key="key-0002")[1]
        found = repository.get_receipt(
            principal_id=P_A,
            client_ref=CLIENT,
            capability="files.mkdir",
            idempotency_key="key-0001",
        )
        assert found == first
        assert (
            repository.get_receipt(
                principal_id=P_B,
                client_ref=OTHER_CLIENT,
                capability="files.mkdir",
                idempotency_key="key-0001",
            )
            is None
        )


@pytest.mark.parametrize(
    "result",
    [
        {"text": "body"},
        {"upload_token": "gfwtk_x"},
        {"entry": {"nested": [{"download_token": "x"}]}},
        {"token": "x"},
    ],
)
def test_a_receipt_result_never_holds_a_text_or_a_token(
    migrated_engine: Engine, result: dict[str, object]
) -> None:
    with _repository(migrated_engine) as repository, pytest.raises(FilesArgumentError):
        _receipt(repository, "fwrcp_receipt00009", result=result)


def test_a_read_capability_has_no_receipt(migrated_engine: Engine) -> None:
    with _repository(migrated_engine) as repository, pytest.raises(FilesArgumentError):
        _receipt(repository, "fwrcp_receipt00010", capability="files.list")


# ---- the schema guards -------------------------------------------------------------


def _seed(engine: Engine) -> None:
    with _repository(engine) as repository:
        _upload(repository)
        repository.record_version(
            version_id="fwver_guard0000001",
            principal_id=P_A,
            workspace_id="mcp",
            path="a.txt",
            version=V1,
            size=1,
            sha256=None,
            cause="files.upload.finalize",
            captured_at=NOW,
        )
        _trash(repository, "fwtrs_guard0000001")
        _receipt(repository, "fwrcp_guard0000001")


_REFUSED: Final[dict[str, tuple[str, str]]] = {
    "version update": (
        "UPDATE knowledge.file_workspace_versions SET size = 2",
        RESTRICT_VIOLATION,
    ),
    "version delete": ("DELETE FROM knowledge.file_workspace_versions", RESTRICT_VIOLATION),
    "receipt update": (
        "UPDATE knowledge.file_workspace_receipts SET intent_digest = repeat('b', 64)",
        RESTRICT_VIOLATION,
    ),
    "receipt delete": ("DELETE FROM knowledge.file_workspace_receipts", RESTRICT_VIOLATION),
    "transfer delete": ("DELETE FROM knowledge.file_workspace_transfers", RESTRICT_VIOLATION),
    "transfer declaration": (
        "UPDATE knowledge.file_workspace_transfers SET path = 'other.bin'",
        RESTRICT_VIOLATION,
    ),
    "transfer token": (
        "UPDATE knowledge.file_workspace_transfers SET token_digest = repeat('c', 64)",
        RESTRICT_VIOLATION,
    ),
    "transfer expiry": (
        "UPDATE knowledge.file_workspace_transfers SET expires_at = expires_at + interval '1s'",
        RESTRICT_VIOLATION,
    ),
    "trash delete": ("DELETE FROM knowledge.file_workspace_trash", RESTRICT_VIOLATION),
    "trash record": (
        "UPDATE knowledge.file_workspace_trash SET original_path = 'elsewhere'",
        RESTRICT_VIOLATION,
    ),
    "trash half restore": (
        "UPDATE knowledge.file_workspace_trash SET restored_at = trashed_at",
        CHECK_VIOLATION,
    ),
    "versions truncate": ("TRUNCATE knowledge.file_workspace_versions", RESTRICT_VIOLATION),
    "transfers truncate": ("TRUNCATE knowledge.file_workspace_transfers", RESTRICT_VIOLATION),
    "trash truncate": ("TRUNCATE knowledge.file_workspace_trash", RESTRICT_VIOLATION),
    "receipts truncate": ("TRUNCATE knowledge.file_workspace_receipts", RESTRICT_VIOLATION),
    "duplicate receipt key": (
        "INSERT INTO knowledge.file_workspace_receipts SELECT 'fwrcp_guard0000002', "
        "owner_principal_id, client_ref, capability, idempotency_key, intent_digest, result, "
        "created_at FROM knowledge.file_workspace_receipts",
        UNIQUE_VIOLATION,
    ),
    "upload offset backwards": (
        "UPDATE knowledge.file_workspace_transfers SET received_bytes = 5",
        "",
    ),
}


@pytest.mark.parametrize("case", sorted(_REFUSED))
def test_the_schema_refuses_each_forbidden_change(migrated_engine: Engine, case: str) -> None:
    _seed(migrated_engine)
    statement, sqlstate = _REFUSED[case]
    if case == "upload offset backwards":
        # Forward first (allowed), then backwards (refused by the guard).
        with migrated_engine.begin() as connection:
            connection.execute(text(statement))
        statement = "UPDATE knowledge.file_workspace_transfers SET received_bytes = 1"
        sqlstate = RESTRICT_VIOLATION
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(text(statement))
    assert _sqlstate(refused) == sqlstate, case


def test_a_settled_transfer_is_immutable(migrated_engine: Engine) -> None:
    _seed(migrated_engine)
    with _repository(migrated_engine) as repository:
        repository.settle_transfer(
            "fwupl_upload000001", principal_id=P_A, state=FileTransferState.EXPIRED, now=NOW
        )
    for statement in (
        "UPDATE knowledge.file_workspace_transfers SET state = 'open'",
        "UPDATE knowledge.file_workspace_transfers SET received_bytes = 3",
    ):
        with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
            connection.execute(text(statement))
        assert _sqlstate(refused) == RESTRICT_VIOLATION, statement


def test_a_restored_trash_item_is_immutable(migrated_engine: Engine) -> None:
    _seed(migrated_engine)
    with _repository(migrated_engine) as repository:
        assert repository.mark_restored(
            "fwtrs_guard0000001", principal_id=P_A, restored_path="b.txt", now=NOW
        )
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(text("UPDATE knowledge.file_workspace_trash SET restored_path = 'c'"))
    assert _sqlstate(refused) == RESTRICT_VIOLATION


_BAD_TRANSFERS: Final[dict[str, str]] = {
    "id prefix": "transfer_id = 'fwver_upload000099'",
    "kind": "kind = 'sideload'",
    "state": "state = 'paused'",
    "digest": "token_digest = 'NOT-A-DIGEST'",
    "path": "path = '/abs'",
    "workspace": "workspace_id = 'Upper'",
    "version": "expected_version = 'fv2_x'",
    "ttl": "expires_at = created_at + interval '25 hours'",
    "client": "client_ref = 'someone'",
}


@pytest.mark.parametrize("case", sorted(_BAD_TRANSFERS))
def test_a_malformed_transfer_row_is_refused(migrated_engine: Engine, case: str) -> None:
    columns = {
        "transfer_id": "'fwupl_upload000099'",
        "owner_principal_id": f"'{P_A}'",
        "client_ref": f"'{CLIENT}'",
        "kind": "'upload'",
        "workspace_id": "'mcp'",
        "path": "'a.bin'",
        "expected_version": "NULL",
        "received_bytes": "0",
        "token_digest": f"'{TOKEN_DIGEST}'",
        "state": "'open'",
        "created_at": "now()",
        "expires_at": "now() + interval '1 hour'",
    }
    column, _, value = _BAD_TRANSFERS[case].partition(" = ")
    columns[column] = value.replace("created_at", "now()")
    statement = (
        f"INSERT INTO knowledge.file_workspace_transfers ({', '.join(columns)}) "  # noqa: S608
        f"VALUES ({', '.join(columns.values())})"
    )
    with pytest.raises(DBAPIError) as refused, migrated_engine.begin() as connection:
        connection.execute(text(statement))
    assert _sqlstate(refused) == CHECK_VIOLATION, case


def test_no_plane_row_holds_a_raw_token(migrated_engine: Engine) -> None:
    """Section 11: the stored digest is the only trace of a token."""
    _seed(migrated_engine)
    reads: tuple[Callable[[Connection], object], ...] = (
        lambda c: c.execute(text("SELECT * FROM knowledge.file_workspace_transfers")).all(),
        lambda c: c.execute(text("SELECT * FROM knowledge.file_workspace_receipts")).all(),
    )
    with migrated_engine.connect() as connection:
        dump = repr([read(connection) for read in reads])
    assert "gfwtk_" not in dump
    assert TOKEN_DIGEST in dump
