"""WP-27's controls against a live PostgreSQL server and a real temporary root.

The `database` tier. Everything here runs on a disposable database created and
dropped by its own fixture, migrated to head, and never the configured one; every
byte is written into `tmp_path` and torn down with it. Nothing here reads
`MY_PA_MANAGED_DOCUMENT_ROOT`, creates a directory in the repository, or touches
any real document tree.

What each section proves, and at what level, stated so the level cannot be
over-read later:

* **Immutable versions.** Both halves. The bytes are refused a second write by
  `O_CREAT | O_EXCL` (proved in `tests/security/test_managed_document_containment.py`);
  the row is refused an `UPDATE` and a `DELETE` by a `BEFORE UPDATE OR DELETE`
  trigger, at the server, on the two append-only tables — proved here, on a real
  connection, because a trigger is not a property any parse of the source can
  show.
* **Expected version.** A revision naming a stale version is refused, writes no
  row, and leaves the head where it was. The head is *also* protected by two
  unique constraints, which is what makes two writers who read the same head
  produce one winner rather than a fork.
* **Idempotency.** A replayed write returns the original receipt and produces
  exactly one document, one version, one receipt, and one object. A key rebound
  to a different request is a conflict and writes nothing.
* **Principal isolation.** Two synthetic Principals. B cannot read, revise,
  archive, restore, or list A's document, and every negative carries a non-zero
  control in the same test so it cannot pass against an empty table.
* **Archive and restore.** A state transition in both directions, appended and
  never rewritten, with the bytes still present and readable afterwards — archive
  is not destruction.
* **The metadata/bytes failure window.** Written as a test rather than as a
  paragraph: a transaction that stores bytes and then rolls back leaves an orphan
  object and no row, and `verify` finds it. The reverse — a row naming absent
  bytes — is what the ordering exists to prevent.
* **Backup and restore.** A real round trip: back up to a second temporary root,
  drop every managed row, restore into a *fresh* root and the emptied database,
  and compare content digests.

Every identifier, title, and byte string here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, make_url

from my_pa.application.commands import (
    ArchiveManagedDocumentCommand,
    CreateManagedDocumentCommand,
    ListManagedDocumentsCommand,
    ReadManagedDocumentCommand,
    RestoreManagedDocumentCommand,
    ReviseManagedDocumentCommand,
)
from my_pa.application.managed_documents import ManagedDocumentService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.documents.managed import (
    DocumentState,
    ManagedDocumentConflictError,
    StaleExpectedVersionError,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.managed_document_stores.filesystem.store import (
    FilesystemManagedByteStore,
    ManagedStoreError,
)
from my_pa.infrastructure.persistence.managed_documents import SqlManagedDocumentRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE: Final = "my_pa_managed_documents_test"

#: The two synthetic Principals every isolation suite in this repository uses.
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

FIRST: Final = b"# Synthetic managed note\n\nThe first version.\n"
SECOND: Final = b"# Synthetic managed note\n\nThe second version.\n"

#: Every table this package's write path can touch, counted so an assertion about
#: "exactly one" is about the whole plane rather than one table of it.
MANAGED_TABLES: Final = (
    "managed_documents",
    "managed_document_versions",
    "managed_document_submissions",
    "managed_document_receipts",
    "managed_document_lifecycle_events",
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def managed_root(tmp_path: Path) -> Path:
    """A managed root that exists only for this test and is removed with it."""
    root = tmp_path / "managed"
    root.mkdir()
    return root


def _store(root: Path) -> FilesystemManagedByteStore:
    return FilesystemManagedByteStore(root)


def _counts(connection: Connection) -> dict[str, int]:
    return {
        table: int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )
        for table in MANAGED_TABLES
    }


def _create(
    connection: Connection,
    store: FilesystemManagedByteStore,
    *,
    principal_id: str = PRINCIPAL_A,
    key: str = "synthetic-managed-0001",
    content: bytes = FIRST,
    title: str = "Synthetic managed note",
) -> str:
    receipt = ManagedDocumentService().create(
        SqlManagedDocumentRepository(connection),
        store,
        CreateManagedDocumentCommand(
            principal_id=principal_id,
            title=title,
            media_type="text/markdown",
            content=content,
            idempotency_key=key,
        ),
    )
    return receipt.document_id


# --- immutable versions ------------------------------------------------------


def test_a_stored_version_row_cannot_be_updated_or_deleted(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """The metadata half of immutability, enforced by the server.

    A rule enforced only by the writer is a rule the next writer does not
    inherit, so this is asked of PostgreSQL rather than of the source. Both
    statements are attempted, because a trigger that fired for one and not the
    other would leave a correction path open in exactly the shape ADR-003's
    "an edit is a new version" forbids.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)

    for statement in (
        f"UPDATE {SCHEMA}.managed_document_versions SET title = 'rewritten'",  # noqa: S608
        f"DELETE FROM {SCHEMA}.managed_document_versions",  # noqa: S608
    ):
        with pytest.raises(Exception, match="append only"), migrated_engine.begin() as connection:
            connection.execute(text(statement))

    with migrated_engine.connect() as connection:
        stored = SqlManagedDocumentRepository(connection).version(
            document_id, principal_id=PRINCIPAL_A
        )
        assert stored is not None
        assert stored.title == "Synthetic managed note"


def test_a_lifecycle_row_cannot_be_updated_or_deleted(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """Archiving is an event, and an event that can be rewritten is a status field.

    Without this trigger, "restore" could be implemented by editing the archive
    row away, and a document would carry no trace of ever having been archived.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
        ManagedDocumentService().archive(
            SqlManagedDocumentRepository(connection),
            ArchiveManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=document_id),
        )

    for statement in (
        f"UPDATE {SCHEMA}.managed_document_lifecycle_events SET transition = 'restored'",  # noqa: S608
        f"DELETE FROM {SCHEMA}.managed_document_lifecycle_events",  # noqa: S608
    ):
        with pytest.raises(Exception, match="append only"), migrated_engine.begin() as connection:
            connection.execute(text(statement))


def test_a_revision_appends_and_leaves_the_predecessor_exactly_as_written(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """A correction is a new version; the old one stays retrievable at its own id."""
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
        first = SqlManagedDocumentRepository(connection).version(
            document_id, principal_id=PRINCIPAL_A
        )
        assert first is not None

    with migrated_engine.begin() as connection:
        receipt = ManagedDocumentService().revise(
            SqlManagedDocumentRepository(connection),
            store,
            ReviseManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                document_id=document_id,
                expected_version_number=1,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=SECOND,
                idempotency_key="synthetic-managed-0002",
            ),
        )
    assert receipt.version_number == 2

    with migrated_engine.connect() as connection:
        service = ManagedDocumentService()
        repository = SqlManagedDocumentRepository(connection)
        old = service.read(
            repository,
            store,
            ReadManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                document_id=document_id,
                version_id=first.version_id,
                include_bytes=True,
            ),
        )
        new = service.read(
            repository,
            store,
            ReadManagedDocumentCommand(
                principal_id=PRINCIPAL_A, document_id=document_id, include_bytes=True
            ),
        )
        assert old is not None and new is not None
        assert old.content is not None and new.content is not None
        assert old.content.bytes_ == FIRST
        assert new.content.bytes_ == SECOND
        assert old.is_current is False
        assert new.is_current is True
        assert new.version.supersedes_version_id == first.version_id


# --- expected version and idempotency ---------------------------------------


def test_a_revision_against_a_stale_expected_version_is_refused_and_writes_nothing(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """The stale writer is refused clearly, and the head does not move.

    The orphan the refused attempt leaves behind is asserted rather than glossed
    over: the bytes were written before the row was attempted, which is the
    ordering this package chose, and `verify` is what finds them.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
    with migrated_engine.begin() as connection:
        ManagedDocumentService().revise(
            SqlManagedDocumentRepository(connection),
            store,
            ReviseManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                document_id=document_id,
                expected_version_number=1,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=SECOND,
                idempotency_key="synthetic-managed-0002",
            ),
        )

    with pytest.raises(StaleExpectedVersionError), migrated_engine.begin() as connection:
        ManagedDocumentService().revise(
            SqlManagedDocumentRepository(connection),
            store,
            ReviseManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                document_id=document_id,
                expected_version_number=1,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=b"a third version written against a stale read\n",
                idempotency_key="synthetic-managed-0003",
            ),
        )

    with migrated_engine.connect() as connection:
        head = SqlManagedDocumentRepository(connection).version(
            document_id, principal_id=PRINCIPAL_A
        )
        assert head is not None
        assert head.version_number == 2
        assert _counts(connection)["managed_document_versions"] == 2
        report = ManagedDocumentService().verify(
            SqlManagedDocumentRepository(connection), store, principal_id=PRINCIPAL_A
        )
    assert report.missing_bytes == ()
    assert len(report.orphaned_version_ids) == 1, (
        "the refused revision's bytes should be an orphan; the ordering writes "
        "bytes before rows so that this is the failure that survives"
    )


def test_a_replayed_write_produces_one_version_and_returns_the_original_receipt(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """`QC-AC-031`'s shape on this plane: one key, one version, one object."""
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        first = ManagedDocumentService().create(
            SqlManagedDocumentRepository(connection),
            store,
            CreateManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=FIRST,
                idempotency_key="synthetic-managed-0001",
            ),
        )
    with migrated_engine.begin() as connection:
        replayed = ManagedDocumentService().create(
            SqlManagedDocumentRepository(connection),
            store,
            CreateManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=FIRST,
                idempotency_key="synthetic-managed-0001",
            ),
        )

    assert replayed.receipt_id == first.receipt_id
    assert replayed.version_id == first.version_id
    assert replayed.created is False
    with migrated_engine.connect() as connection:
        counted = _counts(connection)
    assert counted["managed_documents"] == 1
    assert counted["managed_document_versions"] == 1
    assert counted["managed_document_receipts"] == 1
    assert counted["managed_document_submissions"] == 1
    assert store.stored_version_ids() == (first.version_id,)


def test_a_key_rebound_to_a_different_request_is_a_conflict(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """`QC-AC-032`'s shape: a reused key carrying different content writes nothing.

    The refusal names no field, on purpose: reporting which one differed would
    describe the stored request to whoever guessed the key.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        _create(connection, store)

    with pytest.raises(ManagedDocumentConflictError), migrated_engine.begin() as connection:
        ManagedDocumentService().create(
            SqlManagedDocumentRepository(connection),
            store,
            CreateManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                title="A different synthetic note",
                media_type="text/markdown",
                content=b"materially different bytes\n",
                idempotency_key="synthetic-managed-0001",
            ),
        )

    with migrated_engine.connect() as connection:
        assert _counts(connection)["managed_document_versions"] == 1


def test_one_key_per_principal_so_a_replay_never_crosses_a_partition(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """The collision domain is the Principal's own submissions.

    B reusing A's key is a new document for B, not a replay of A's receipt. The
    alternative — a global key space — would let one Principal learn another's
    receipt by guessing a string.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        mine = _create(connection, store, principal_id=PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        theirs = _create(connection, store, principal_id=PRINCIPAL_B)
    assert mine != theirs
    with migrated_engine.connect() as connection:
        assert _counts(connection)["managed_document_versions"] == 2


# --- principal isolation -----------------------------------------------------


def test_principal_b_cannot_read_revise_archive_restore_or_discover_principal_a(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """The mandatory two-Principal negative, with a control in the same test.

    Every one of B's reads answers exactly what an absent document answers, and
    every one of B's writes refuses without naming an identifier. The control is
    A's own read of the same document in the same transaction: without it, all
    six negatives would pass against an empty table.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)

    with migrated_engine.begin() as connection:
        service = ManagedDocumentService()
        repository = SqlManagedDocumentRepository(connection)

        # The control.
        mine = service.read(
            repository,
            store,
            ReadManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=document_id),
        )
        assert mine is not None, "the control read found nothing; the negatives prove nothing"
        assert (
            service.list_documents(
                repository, ListManagedDocumentsCommand(principal_id=PRINCIPAL_A)
            )
            != ()
        )

        # Read.
        assert (
            service.read(
                repository,
                store,
                ReadManagedDocumentCommand(principal_id=PRINCIPAL_B, document_id=document_id),
            )
            is None
        )
        # Discover.
        assert (
            service.list_documents(
                repository,
                ListManagedDocumentsCommand(principal_id=PRINCIPAL_B, include_archived=True),
            )
            == ()
        )
        # State.
        assert repository.state(document_id, principal_id=PRINCIPAL_B) is None
        # Versions.
        assert repository.versions(document_id, principal_id=PRINCIPAL_B) == ()

    with pytest.raises(UnknownScopeError), migrated_engine.begin() as connection:
        ManagedDocumentService().revise(
            SqlManagedDocumentRepository(connection),
            store,
            ReviseManagedDocumentCommand(
                principal_id=PRINCIPAL_B,
                document_id=document_id,
                expected_version_number=1,
                title="Taken over",
                media_type="text/markdown",
                content=b"a version written by the wrong principal\n",
                idempotency_key="synthetic-managed-b-0001",
            ),
        )

    with pytest.raises(UnknownScopeError), migrated_engine.begin() as connection:
        ManagedDocumentService().archive(
            SqlManagedDocumentRepository(connection),
            ArchiveManagedDocumentCommand(principal_id=PRINCIPAL_B, document_id=document_id),
        )

    with pytest.raises(UnknownScopeError), migrated_engine.begin() as connection:
        ManagedDocumentService().restore(
            SqlManagedDocumentRepository(connection),
            RestoreManagedDocumentCommand(principal_id=PRINCIPAL_B, document_id=document_id),
        )

    with migrated_engine.connect() as connection:
        counted = _counts(connection)
    assert counted["managed_document_versions"] == 1
    assert counted["managed_document_lifecycle_events"] == 0


def test_a_write_naming_another_principal_in_its_payload_is_refused(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """Identity comes from the context, never from the request that carries it.

    The port's request value holds a `principal_id` because the capture plane's
    does; it is verified against the authenticated context rather than trusted,
    so even a composition bug cannot write a row into another partition.
    """
    from my_pa.contracts.ports import ManagedWriteRequest
    from my_pa.domain.common.identifiers import IdKind
    from my_pa.domain.common.time import utc_now
    from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
    from my_pa.domain.source.registry import issue_identifier
    from my_pa.infrastructure.persistence.managed_documents import admit_managed_write
    from my_pa.infrastructure.persistence.principal_scope import capture_context

    request = ManagedWriteRequest(
        document_id=None,
        expected_version_number=None,
        version_id=issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION),
        title="Synthetic managed note",
        media_type="text/markdown",
        content_sha256="0" * 64,
        byte_size=1,
        idempotency_key="synthetic-managed-forged",
        correlation_id=issue_identifier(IdKind.CORRELATION),
        principal_id=PRINCIPAL_B,
        server_received_at=utc_now(),
    )
    with pytest.raises(CallerSuppliedPrincipalError), migrated_engine.begin() as connection:
        admit_managed_write(connection, request, context=capture_context(PRINCIPAL_A))


# --- archive and restore -----------------------------------------------------


def test_archive_and_restore_are_reversible_and_destroy_nothing(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """Archive withdraws, restore returns, and the bytes never move.

    The digest is compared before and after both transitions, because "archive is
    a state, not destruction" is a claim about the bytes and not about a column.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
        version = SqlManagedDocumentRepository(connection).version(
            document_id, principal_id=PRINCIPAL_A
        )
        assert version is not None
    before = store.read(version.version_id)

    with migrated_engine.begin() as connection:
        service = ManagedDocumentService()
        repository = SqlManagedDocumentRepository(connection)
        assert (
            service.archive(
                repository,
                ArchiveManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=document_id),
            )
            is True
        )
        assert repository.state(document_id, principal_id=PRINCIPAL_A) is DocumentState.ARCHIVED
        # Archiving twice appends nothing: the caller asked for a state and the
        # document is in it.
        assert (
            service.archive(
                repository,
                ArchiveManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=document_id),
            )
            is False
        )
        # And it leaves the active listing.
        assert (
            service.list_documents(
                repository, ListManagedDocumentsCommand(principal_id=PRINCIPAL_A)
            )
            == ()
        )
        assert (
            len(
                service.list_documents(
                    repository,
                    ListManagedDocumentsCommand(principal_id=PRINCIPAL_A, include_archived=True),
                )
            )
            == 1
        )

    assert store.read(version.version_id) == before, "archiving changed the stored bytes"

    with migrated_engine.begin() as connection:
        service = ManagedDocumentService()
        repository = SqlManagedDocumentRepository(connection)
        assert (
            service.restore(
                repository,
                RestoreManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=document_id),
            )
            is True
        )
        assert repository.state(document_id, principal_id=PRINCIPAL_A) is DocumentState.ACTIVE
        assert (
            len(
                service.list_documents(
                    repository, ListManagedDocumentsCommand(principal_id=PRINCIPAL_A)
                )
            )
            == 1
        )

    assert store.read(version.version_id) == before
    with migrated_engine.connect() as connection:
        assert _counts(connection)["managed_document_lifecycle_events"] == 2


def test_an_archived_document_still_accepts_a_revision_only_through_the_write_path(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """What archiving does and does not do, asserted rather than assumed.

    Archiving withdraws a document from the active listing. It is deliberately
    *not* a write lock: this build has no consumer that needs one, and inventing
    a refusal here would be a policy nobody asked for. The residual is recorded
    by this test rather than left for a reader to discover from the absence of
    one.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
        ManagedDocumentService().archive(
            SqlManagedDocumentRepository(connection),
            ArchiveManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=document_id),
        )
    with migrated_engine.begin() as connection:
        receipt = ManagedDocumentService().revise(
            SqlManagedDocumentRepository(connection),
            store,
            ReviseManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                document_id=document_id,
                expected_version_number=1,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=SECOND,
                idempotency_key="synthetic-managed-0002",
            ),
        )
    assert receipt.version_number == 2
    with migrated_engine.connect() as connection:
        assert (
            SqlManagedDocumentRepository(connection).state(document_id, principal_id=PRINCIPAL_A)
            is DocumentState.ARCHIVED
        )


# --- the metadata/bytes failure window ---------------------------------------


def test_a_rolled_back_write_leaves_bytes_with_no_row_and_verify_finds_them(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """The failure window, measured rather than described.

    The bytes are written and fsynced before the rows are inserted, so a
    transaction that fails after the byte write leaves an **orphan object and no
    row**. That is the recoverable direction and it is what this asserts. The
    other direction — a row naming absent bytes — is what no reconciliation can
    repair, and the same assertion checks it did not happen.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        _create(connection, store)

    with (
        pytest.raises(RuntimeError, match="synthetic failure"),
        migrated_engine.begin() as connection,
    ):
        if True:
            ManagedDocumentService().create(
                SqlManagedDocumentRepository(connection),
                store,
                CreateManagedDocumentCommand(
                    principal_id=PRINCIPAL_A,
                    title="A note whose transaction fails",
                    media_type="text/markdown",
                    content=b"bytes that will outlive their transaction\n",
                    idempotency_key="synthetic-managed-rolled-back",
                ),
            )
            raise RuntimeError("synthetic failure after the bytes were stored")

    with migrated_engine.connect() as connection:
        counted = _counts(connection)
        report = ManagedDocumentService().verify(
            SqlManagedDocumentRepository(connection), store, principal_id=PRINCIPAL_A
        )
    assert counted["managed_document_versions"] == 1, "the failed transaction left a row"
    assert report.missing_bytes == (), "a row names bytes that are not there"
    assert report.digest_mismatches == ()
    assert len(report.orphaned_version_ids) == 1
    assert len(store.stored_version_ids()) == 2
    assert report.is_consistent is True, (
        "orphan bytes are recoverable and must not be reported as an inconsistency"
    )


def test_verify_reports_a_row_whose_bytes_were_removed_from_under_it(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """The control for the report: it can see the direction it exists to find.

    Nothing in this product removes a stored object, so this failure is produced
    by removing the file directly — which is exactly the situation an operator
    needs the check for.
    """
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
        version = SqlManagedDocumentRepository(connection).version(
            document_id, principal_id=PRINCIPAL_A
        )
        assert version is not None

    suffix = version.version_id.removeprefix("mdver_")
    (managed_root / "objects" / suffix[:2] / suffix[2:4] / version.version_id).unlink()

    with migrated_engine.connect() as connection:
        report = ManagedDocumentService().verify(
            SqlManagedDocumentRepository(connection), store, principal_id=PRINCIPAL_A
        )
    assert report.missing_bytes == (version.version_id,)
    assert report.is_consistent is False


def test_verify_reports_bytes_that_no_longer_match_their_recorded_digest(
    migrated_engine: Engine, managed_root: Path
) -> None:
    """Nothing in this product can produce this; something outside it can."""
    store = _store(managed_root)
    with migrated_engine.begin() as connection:
        document_id = _create(connection, store)
        version = SqlManagedDocumentRepository(connection).version(
            document_id, principal_id=PRINCIPAL_A
        )
        assert version is not None

    suffix = version.version_id.removeprefix("mdver_")
    stored = managed_root / "objects" / suffix[:2] / suffix[2:4] / version.version_id
    stored.unlink()
    stored.write_bytes(b"tampered\n")

    with migrated_engine.connect() as connection:
        report = ManagedDocumentService().verify(
            SqlManagedDocumentRepository(connection), store, principal_id=PRINCIPAL_A
        )
    assert report.digest_mismatches == (version.version_id,)
    assert report.is_consistent is False


# --- backup and restore ------------------------------------------------------


def test_a_backup_restores_into_a_fresh_root_and_an_emptied_database(
    migrated_engine: Engine, managed_root: Path, tmp_path: Path
) -> None:
    """The round trip, with real bytes and real rows on both ends.

    Two documents and three versions, one of them archived, so the restore has a
    chain to rebuild rather than a single row. Every managed row is deleted and a
    *fresh* empty root is used, so nothing about the assertion can be satisfied by
    state the backup did not carry.

    The lifecycle rows are deliberately **not** restored, and the residual is
    asserted rather than hidden: this backup carries versions and their bytes,
    which is what "backup/restore of bytes and metadata" in the register asks
    for, and the archived/active state of a restored document is not part of it.
    A restored plane is therefore active, and the operations document says so.
    """
    store = _store(managed_root)
    backup_root = tmp_path / "backup"
    backup_root.mkdir()
    backup = _store(backup_root)

    with migrated_engine.begin() as connection:
        first_document = _create(connection, store, key="synthetic-managed-0001")
        second_document = _create(
            connection,
            store,
            key="synthetic-managed-0010",
            content=b"a second synthetic document\n",
            title="Second synthetic note",
        )
    with migrated_engine.begin() as connection:
        ManagedDocumentService().revise(
            SqlManagedDocumentRepository(connection),
            store,
            ReviseManagedDocumentCommand(
                principal_id=PRINCIPAL_A,
                document_id=first_document,
                expected_version_number=1,
                title="Synthetic managed note",
                media_type="text/markdown",
                content=SECOND,
                idempotency_key="synthetic-managed-0002",
            ),
        )
        ManagedDocumentService().archive(
            SqlManagedDocumentRepository(connection),
            ArchiveManagedDocumentCommand(principal_id=PRINCIPAL_A, document_id=second_document),
        )

    with migrated_engine.connect() as connection:
        expected = {
            version.version_id: version.content_sha256
            for document in (first_document, second_document)
            for version in SqlManagedDocumentRepository(connection).versions(
                document, principal_id=PRINCIPAL_A
            )
        }
    assert len(expected) == 3

    with migrated_engine.begin() as connection:
        summary = ManagedDocumentService().back_up(
            SqlManagedDocumentRepository(connection),
            store,
            backup,
            principal_id=PRINCIPAL_A,
        )
    assert summary.documents == 2
    assert summary.versions == 3
    assert sorted(backup.stored_version_ids()) == sorted(expected)

    # Empty the plane completely: the triggers refuse a delete on the two
    # append-only tables, so this is done with them disabled — which is a
    # deliberate, operator-shaped act and is exactly why the trigger exists.
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE {SCHEMA}.managed_document_versions DISABLE TRIGGER USER")
        )
        connection.execute(
            text(f"ALTER TABLE {SCHEMA}.managed_document_lifecycle_events DISABLE TRIGGER USER")
        )
        for table in MANAGED_TABLES:
            connection.execute(text(f"DELETE FROM {SCHEMA}.{table}"))  # noqa: S608
        connection.execute(
            text(f"ALTER TABLE {SCHEMA}.managed_document_versions ENABLE TRIGGER USER")
        )
        connection.execute(
            text(f"ALTER TABLE {SCHEMA}.managed_document_lifecycle_events ENABLE TRIGGER USER")
        )
    with migrated_engine.connect() as connection:
        assert _counts(connection) == dict.fromkeys(MANAGED_TABLES, 0)

    fresh_root = tmp_path / "restored"
    fresh_root.mkdir()
    fresh = _store(fresh_root)
    with migrated_engine.begin() as connection:
        restored = ManagedDocumentService().restore_from_backup(
            SqlManagedDocumentRepository(connection), fresh, backup, principal_id=PRINCIPAL_A
        )
    assert restored.documents == 2
    assert restored.versions == 3
    assert restored.versions_already_present == 0

    with migrated_engine.connect() as connection:
        repository = SqlManagedDocumentRepository(connection)
        rebuilt = {
            version.version_id: version.content_sha256
            for document in (first_document, second_document)
            for version in repository.versions(document, principal_id=PRINCIPAL_A)
        }
        report = ManagedDocumentService().verify(repository, fresh, principal_id=PRINCIPAL_A)
    assert rebuilt == expected, "the restored metadata does not match what was backed up"
    assert report.missing_bytes == ()
    assert report.digest_mismatches == ()
    assert report.versions_checked == 3
    # And the bytes themselves, not only their recorded digests.
    for version_id in expected:
        assert fresh.read(version_id) == store.read(version_id)


def test_a_backup_taken_for_one_principal_is_refused_for_another(
    migrated_engine: Engine, managed_root: Path, tmp_path: Path
) -> None:
    """A mistyped `--principal` cannot move a document between partitions."""
    store = _store(managed_root)
    backup_root = tmp_path / "backup"
    backup_root.mkdir()
    backup = _store(backup_root)
    with migrated_engine.begin() as connection:
        _create(connection, store)
        ManagedDocumentService().back_up(
            SqlManagedDocumentRepository(connection), store, backup, principal_id=PRINCIPAL_A
        )

    fresh_root = tmp_path / "restored"
    fresh_root.mkdir()
    with (
        pytest.raises(ValueError, match="different Principal"),
        migrated_engine.begin() as (connection),
    ):
        ManagedDocumentService().restore_from_backup(
            SqlManagedDocumentRepository(connection),
            _store(fresh_root),
            backup,
            principal_id=PRINCIPAL_B,
        )


def test_a_backup_destination_inside_the_live_managed_root_is_refused(
    managed_root: Path,
) -> None:
    """ "Back up in place" is refused before anything is written.

    The overlap check the store makes against source roots is the same one an
    operator command makes against the live managed root, which is why the
    destination is a `ManagedByteStore` rather than a directory.
    """
    inside = managed_root / "backup"
    inside.mkdir()
    with pytest.raises(ManagedStoreError):
        FilesystemManagedByteStore(inside, source_roots=(managed_root,))
