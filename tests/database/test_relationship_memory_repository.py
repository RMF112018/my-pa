"""`SqlRelationshipMemoryRepository` against a real PostgreSQL server.

Beside `tests/database/test_entity_repository.py`, which makes the same kind of
claim about the plane that owns a memory's subject, and structured the same way:
real statements, real constraints, a real append-only trigger, and a partition
predicate that is either in the WHERE clause or is not.

Four claims carry this plane and each is asserted here against the server rather
than against the code that usually calls it:

* **A version is written once.** `revise` appends a successor and leaves the
  predecessor's exact text retrievable, and a raw `UPDATE` on the version table
  is refused by the trigger — which is the half no application rule can hold,
  because a rule the current writer remembers is not a rule the next writer
  inherits.
* **A stale expectation writes nothing.** The guarded `UPDATE … WHERE version =
  expected` is read for its row count before anything else is written, so the
  rows are counted inside the failed transaction and again after it.
* **A foreign memory answers exactly what an absent one answers.** Asserted as an
  equality between the two answers rather than as two separate `is None` checks,
  because "both happen to be falsey" is a weaker claim than "indistinguishable".
* **Ownership of the subject and of every context target is proven before the
  insert.** A foreign subject, a foreign context target and a merged-away subject
  are each refused, and the row counts show the refusal came first.

Everything is synthetic: two invented Principals, invented entities, invented
notes. No real person and no live data. The database is created and dropped by
this module's own fixture and is never the configured one.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import MemoryWriteRequest, UnknownScopeError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    MemoryActorClass,
    MemoryAdmission,
    MemoryAuthority,
    MemoryConflictError,
    MemoryKind,
    MemoryLifecycle,
    MemoryOperation,
    MemoryReceipt,
    MergedSubjectError,
    StaleMemoryVersionError,
    classification_floor_for,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable database,
#: so this suite can run alongside them without one dropping the database
#: another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_relationship_memory_repository_test"

#: This plane's revision and the one it revises, for the round trip below.
MEMORY_REVISION: Final = "f1c6b904a2d7"
PREVIOUS_REVISION: Final = "e9b2c4d7a150"

#: The eight tables the revision creates.
MEMORY_TABLES: Final = frozenset(
    {
        "relationship_memories",
        "relationship_memory_versions",
        "relationship_memory_submissions",
        "relationship_memory_context_links",
        "relationship_memory_evidence_links",
        "relationship_memory_proposals",
        "relationship_memory_proposal_evidence",
        "relationship_memory_review_decisions",
    }
)

#: The three tables one admitted write touches, counted together whenever the
#: claim is "nothing was written".
WRITE_TABLES: Final = (
    "relationship_memories",
    "relationship_memory_versions",
    "relationship_memory_submissions",
)

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: A's synthetic people, and one project A owns so a context link has somewhere
#: real to point.
DANA: Final = "ent_aaaa0001aaaa0001"
ELI: Final = "ent_cccc0003cccc0003"
RIVERSIDE: Final = "ent_dddd0004dddd0004"
#: A's merged-away identity, and the identity it was merged into.
OLD_DANA: Final = "ent_eeee0005eeee0005"
#: B's own person, so every read of A's has a foreign decoy beside it.
FOREIGN_PERSON: Final = "ent_bbbb0002bbbb0002"
#: An entity nobody created, so "absent" has an identifier to be absent under.
ABSENT_ENTITY: Final = "ent_ffff0006ffff0006"
ABSENT_MEMORY: Final = "mem_ffff0006ffff0006"

FIRST_NOTE: Final = "Synthetic subject prefers Teams messages."
SECOND_NOTE: Final = "Synthetic subject prefers phone calls now, not Teams."

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 8, 22, 13, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards.

    Copied rather than shared, as every other database-tier module copies it:
    the fixture names a database of its own so two suites cannot drop each
    other's, and the canonical database is never migrated or opened.
    """
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


def an_entity(
    entity_id: str,
    principal_id: str,
    display_name: str,
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def two_principals(migrated_engine: Engine) -> Engine:
    """A holds Dana, Eli, Riverside and a merged-away identity; B holds one person.

    Every read below therefore has a foreign decoy that really exists, so an
    empty answer is evidence about the partition rather than about the fixture.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, an_entity(DANA, PRINCIPAL_A, "Dana Synthetic"))
        repository.create(PRINCIPAL_A, an_entity(ELI, PRINCIPAL_A, "Eli Synthetic"))
        repository.create(
            PRINCIPAL_A,
            an_entity(RIVERSIDE, PRINCIPAL_A, "Riverside Synthetic", EntityType.PROJECT),
        )
        repository.create(PRINCIPAL_A, an_entity(OLD_DANA, PRINCIPAL_A, "Dana Old Synthetic"))
        repository.create(PRINCIPAL_B, an_entity(FOREIGN_PERSON, PRINCIPAL_B, "Bo Synthetic"))
        repository.redirect_entity(PRINCIPAL_A, OLD_DANA, DANA)
    return migrated_engine


# --- request builders ---------------------------------------------------------
#
# `MemoryWriteRequest` is what the repository takes, so these build one directly
# rather than going through `RelationshipMemoryService`. The service is proved
# elsewhere; here it would only stand between the assertion and the SQL.


def _create_request(
    *,
    principal_id: str,
    subject_entity_id: str,
    statement: str,
    idempotency_key: str,
    kind: MemoryKind = MemoryKind.GENERAL_NOTE,
    structured_value: dict[str, Any] | None = None,
    context_links: tuple[Mapping[str, str], ...] = (),
    pinned: bool = False,
    at: datetime = WHEN,
) -> MemoryWriteRequest:
    return MemoryWriteRequest(
        operation=MemoryOperation.CREATE,
        memory_id=None,
        memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
        expected_version=None,
        principal_id=principal_id,
        subject_entity_id=subject_entity_id,
        memory_kind=kind,
        statement=statement,
        statement_sha256=statement_digest(statement),
        structured_value=structured_value,
        authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
        classification=classification_floor_for(kind),
        created_by_actor=MemoryActorClass.USER,
        context_links=context_links,
        pinned=pinned,
        observed_at=None,
        effective_from=None,
        effective_to=None,
        correction_reason=None,
        idempotency_key=idempotency_key,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        server_received_at=at,
    )


def _mutate_request(
    operation: MemoryOperation,
    *,
    principal_id: str,
    memory_id: str,
    expected_version: int,
    idempotency_key: str,
    statement: str | None = None,
    kind: MemoryKind | None = None,
    correction_reason: str | None = None,
    context_links: tuple[Mapping[str, str], ...] = (),
    at: datetime = LATER,
) -> MemoryWriteRequest:
    # A revise carries a kind because it writes a version; an archive and a
    # restore carry none, because the repository keeps the aggregate's own.
    revising = operation is MemoryOperation.REVISE
    effective_kind = (kind or MemoryKind.GENERAL_NOTE) if revising else None
    floor = classification_floor_for(effective_kind or MemoryKind.GENERAL_NOTE)
    return MemoryWriteRequest(
        operation=operation,
        memory_id=memory_id,
        memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
        expected_version=expected_version,
        principal_id=principal_id,
        subject_entity_id=None,
        memory_kind=effective_kind,
        statement=statement,
        statement_sha256=None if statement is None else statement_digest(statement),
        structured_value=None,
        authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
        classification=floor,
        created_by_actor=MemoryActorClass.USER,
        context_links=context_links,
        pinned=False,
        observed_at=None,
        effective_from=None,
        effective_to=None,
        correction_reason=correction_reason,
        idempotency_key=idempotency_key,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        server_received_at=at,
    )


def _admit(
    repository: SqlRelationshipMemoryRepository, request: MemoryWriteRequest
) -> MemoryAdmission:
    """Replay first, then write — the order `RelationshipMemoryService._admit` uses.

    Written out here rather than imported so the repository's two write entry
    points are both exercised by name: a test that only called `admit` would
    never reach `replay_for`, which is where a conflicting key is refused.
    """
    replayed = repository.replay_for(
        request.idempotency_key, request.payload_digest, principal_id=request.principal_id
    )
    if replayed is not None:
        return MemoryAdmission(receipt=replayed, created=False)
    return repository.admit(request)


def _counts(connection: Connection) -> dict[str, int]:
    """How many rows each write table holds, read on the given connection."""
    return {
        table: int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )
        for table in WRITE_TABLES
    }


def _created(engine: Engine, **overrides: object) -> MemoryReceipt:
    """One admitted create, committed, with `overrides` applied to the request."""
    fields: dict[str, object] = {
        "principal_id": PRINCIPAL_A,
        "subject_entity_id": DANA,
        "statement": FIRST_NOTE,
        "idempotency_key": "synthetic-create-0001",
    }
    with engine.begin() as connection:
        request = _create_request(**{**fields, **overrides})  # type: ignore[arg-type]
        return _admit(SqlRelationshipMemoryRepository(connection), request).receipt


# --- create, read, list, history ---------------------------------------------


def test_a_created_memory_round_trips_through_every_read(two_principals: Engine) -> None:
    """One write, then the four reads that must agree about it.

    `detail`, `page_for_entity` and `history` each build their own statement, so
    a write that only one of them could see would be a plane whose profile view
    and whose history disagree about what was recorded.
    """
    receipt = _created(two_principals)
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        detail = repository.detail(receipt.memory_id, principal_id=PRINCIPAL_A)
        page = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        versions, truncated = repository.history(
            receipt.memory_id, principal_id=PRINCIPAL_A, limit=10
        )
    assert detail is not None
    assert detail.memory.memory_id == receipt.memory_id
    assert detail.memory.subject_entity_id == DANA
    assert detail.memory.lifecycle_state is MemoryLifecycle.ACTIVE
    assert detail.current_version.statement == FIRST_NOTE
    assert detail.current_version.statement_sha256 == statement_digest(FIRST_NOTE)
    assert [memory.memory_id for memory in page.memories] == [receipt.memory_id]
    assert page.statements[receipt.memory_id] == FIRST_NOTE
    assert [version.version_number for version in versions] == [1]
    assert versions[0].statement == FIRST_NOTE
    assert truncated is False


def test_the_receipt_names_the_version_that_was_written(two_principals: Engine) -> None:
    """A receipt for a version the write did not create would be unusable as one."""
    receipt = _created(two_principals)
    assert receipt.created is True
    assert receipt.version_number == 1
    assert receipt.aggregate_version == 1
    assert receipt.statement_sha256 == statement_digest(FIRST_NOTE)
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            receipt.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.current_version.memory_version_id == receipt.memory_version_id


# --- the version chain is append only ----------------------------------------


def test_a_revision_appends_a_successor_and_keeps_the_predecessor(
    two_principals: Engine,
) -> None:
    """Correction is an append. The words the user first wrote stay readable.

    Without this, "immutable" would mean only that the current row is not edited
    in place, and a corrected note would lose the wording the user is entitled to
    see in its history.
    """
    created = _created(two_principals)
    with two_principals.begin() as connection:
        revised = _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.REVISE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=created.aggregate_version,
                idempotency_key="synthetic-revise-0001",
                statement=SECOND_NOTE,
                correction_reason="the preference changed",
            ),
        ).receipt
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        versions, _ = repository.history(created.memory_id, principal_id=PRINCIPAL_A, limit=10)
        detail = repository.detail(created.memory_id, principal_id=PRINCIPAL_A)
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[0].statement == FIRST_NOTE
    assert versions[1].statement == SECOND_NOTE
    assert versions[0].prior_version_id is None
    assert versions[1].prior_version_id == versions[0].memory_version_id
    assert versions[1].correction_reason == "the preference changed"
    assert detail is not None
    assert detail.current_version.memory_version_id == revised.memory_version_id
    assert revised.version_number == 2
    assert revised.aggregate_version == 2


def test_a_raw_update_of_a_stored_version_is_refused_by_the_server(
    two_principals: Engine,
) -> None:
    """The half no application rule can hold.

    A rule enforced only by the current writer is a rule a repair script, a
    backfill or the next repository does not inherit, so the append-only claim is
    made by a `BEFORE UPDATE OR DELETE` trigger and asserted here against the
    server with the application out of the way.
    """
    receipt = _created(two_principals)
    with two_principals.connect() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.relationship_memory_versions "  # noqa: S608
                    "SET statement_text = 'rewritten' "
                    "WHERE memory_version_id = :memory_version_id"
                ),
                {"memory_version_id": receipt.memory_version_id},
            )
    with two_principals.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT statement_text FROM {SCHEMA}.relationship_memory_versions "  # noqa: S608
                "WHERE memory_version_id = :memory_version_id"
            ),
            {"memory_version_id": receipt.memory_version_id},
        ).scalar_one()
    assert stored == FIRST_NOTE


def test_a_raw_delete_of_a_stored_version_is_refused_by_the_server(
    two_principals: Engine,
) -> None:
    """The same trigger, and the reason the lifecycle vocabulary has no `deleted`."""
    receipt = _created(two_principals)
    with two_principals.connect() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    f"DELETE FROM {SCHEMA}.relationship_memory_versions "  # noqa: S608
                    "WHERE memory_version_id = :memory_version_id"
                ),
                {"memory_version_id": receipt.memory_version_id},
            )


# --- optimistic concurrency ---------------------------------------------------


def test_a_stale_expected_version_raises_and_writes_nothing(two_principals: Engine) -> None:
    """The refusal happens before the successor is inserted, not after.

    Counted twice: inside the transaction that raised — which is possible because
    the refusal is the guarded UPDATE's own row count rather than a database
    error, so the transaction is still usable — and again from a fresh connection
    afterwards. Counting only after would leave a rollback as an equally good
    explanation for the absent rows.
    """
    created = _created(two_principals)
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(StaleMemoryVersionError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _mutate_request(
                    MemoryOperation.REVISE,
                    principal_id=PRINCIPAL_A,
                    memory_id=created.memory_id,
                    expected_version=created.aggregate_version + 99,
                    idempotency_key="synthetic-stale-0001",
                    statement=SECOND_NOTE,
                ),
            )
        assert _counts(connection) == before
    with two_principals.connect() as connection:
        assert _counts(connection) == before
        detail = SqlRelationshipMemoryRepository(connection).detail(
            created.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert detail.current_version.statement == FIRST_NOTE
    assert detail.memory.version == created.aggregate_version


# --- idempotency --------------------------------------------------------------


def test_replaying_one_key_returns_the_original_receipt_and_writes_no_second_row(
    two_principals: Engine,
) -> None:
    """A retry is not a second memory.

    The replayed receipt says `created=False`, so a client can tell an
    acknowledged write from a repeated one without comparing versions.
    """
    first = _created(two_principals, idempotency_key="synthetic-replay-0001")
    with two_principals.connect() as connection:
        before = _counts(connection)
    with two_principals.begin() as connection:
        replay = _admit(
            SqlRelationshipMemoryRepository(connection),
            _create_request(
                principal_id=PRINCIPAL_A,
                subject_entity_id=DANA,
                statement=FIRST_NOTE,
                idempotency_key="synthetic-replay-0001",
            ),
        )
    with two_principals.connect() as connection:
        after = _counts(connection)
    assert replay.created is False
    assert replay.receipt.created is False
    assert replay.receipt.memory_id == first.memory_id
    assert replay.receipt.memory_version_id == first.memory_version_id
    assert replay.receipt.version_number == first.version_number
    assert replay.receipt.statement_sha256 == first.statement_sha256
    assert after == before


def test_one_key_bound_to_a_different_payload_is_a_conflict(two_principals: Engine) -> None:
    """A lookup on the key alone would answer a *different* request with the
    original receipt, reporting a write that never happened as durable."""
    _created(two_principals, idempotency_key="synthetic-conflict-0001")
    with two_principals.begin() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(MemoryConflictError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=DANA,
                    statement=SECOND_NOTE,
                    idempotency_key="synthetic-conflict-0001",
                ),
            )


# --- archive and restore ------------------------------------------------------


def test_archive_and_restore_are_reversible_and_write_no_version(
    two_principals: Engine,
) -> None:
    """Two counters, and only one of them moves.

    The aggregate version advances on each transition — so a caller who read
    before the archive cannot then revise blindly — while the version *number*
    does not, because a lifecycle transition is not a correction and writes no
    statement. Collapsing the two would make `expected_version` on an archive
    either meaningless or a lie about the version chain.
    """
    created = _created(two_principals)
    with two_principals.begin() as connection:
        archived = _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.ARCHIVE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=created.aggregate_version,
                idempotency_key="synthetic-archive-0001",
            ),
        ).receipt
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        while_archived = repository.detail(created.memory_id, principal_id=PRINCIPAL_A)
        active_page = repository.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        archived_page = repository.page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10, lifecycle=MemoryLifecycle.ARCHIVED
        )
        versions_after_archive, _ = repository.history(
            created.memory_id, principal_id=PRINCIPAL_A, limit=10
        )
    with two_principals.begin() as connection:
        restored = _admit(
            SqlRelationshipMemoryRepository(connection),
            _mutate_request(
                MemoryOperation.RESTORE,
                principal_id=PRINCIPAL_A,
                memory_id=created.memory_id,
                expected_version=archived.aggregate_version,
                idempotency_key="synthetic-restore-0001",
            ),
        ).receipt
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        while_active = repository.detail(created.memory_id, principal_id=PRINCIPAL_A)
        versions_after_restore, _ = repository.history(
            created.memory_id, principal_id=PRINCIPAL_A, limit=10
        )

    assert archived.lifecycle_state is MemoryLifecycle.ARCHIVED
    assert while_archived is not None
    assert while_archived.memory.lifecycle_state is MemoryLifecycle.ARCHIVED
    assert while_archived.memory.archived_at is not None
    assert [memory.memory_id for memory in active_page.memories] == []
    assert [memory.memory_id for memory in archived_page.memories] == [created.memory_id]

    assert restored.lifecycle_state is MemoryLifecycle.ACTIVE
    assert while_active is not None
    assert while_active.memory.lifecycle_state is MemoryLifecycle.ACTIVE
    assert while_active.memory.archived_at is None

    # The aggregate version advances each time; the version number never does.
    assert [created.aggregate_version, archived.aggregate_version, restored.aggregate_version] == [
        1,
        2,
        3,
    ]
    assert [created.version_number, archived.version_number, restored.version_number] == [1, 1, 1]
    assert [version.version_number for version in versions_after_archive] == [1]
    assert [version.version_number for version in versions_after_restore] == [1]


# --- the partition ------------------------------------------------------------


def test_a_foreign_memory_reads_exactly_as_an_absent_one(two_principals: Engine) -> None:
    """Not "is also empty": the same answer, asserted as an equality.

    A refusal that differed from an absence — a different error, a different
    shape, a message — would let a caller learn that an identifier names
    something another Principal holds.
    """
    theirs = _created(
        two_principals,
        principal_id=PRINCIPAL_B,
        subject_entity_id=FOREIGN_PERSON,
        statement="Bo Synthetic prefers email.",
        idempotency_key="synthetic-foreign-0001",
    )
    mine = _created(two_principals, idempotency_key="synthetic-mine-0001")
    with two_principals.connect() as connection:
        repository = SqlRelationshipMemoryRepository(connection)
        held = repository.detail(mine.memory_id, principal_id=PRINCIPAL_A)
        foreign = repository.detail(theirs.memory_id, principal_id=PRINCIPAL_A)
        absent = repository.detail(ABSENT_MEMORY, principal_id=PRINCIPAL_A)
        foreign_history = repository.history(theirs.memory_id, principal_id=PRINCIPAL_A, limit=10)
        absent_history = repository.history(ABSENT_MEMORY, principal_id=PRINCIPAL_A, limit=10)
        foreign_page = repository.page_for_entity(
            FOREIGN_PERSON, principal_id=PRINCIPAL_A, limit=10
        )
        absent_page = repository.page_for_entity(ABSENT_ENTITY, principal_id=PRINCIPAL_A, limit=10)
    assert held is not None, "the fixture wrote nothing, so nothing below is evidence"
    assert foreign is None
    assert foreign == absent
    assert foreign_history == absent_history
    assert foreign_page == absent_page


def test_a_create_naming_another_principals_subject_is_refused_before_any_row(
    two_principals: Engine,
) -> None:
    """A foreign-key constraint proves a row exists, never that it is yours.

    The identifiers are globally unique, so ownership of the subject has to be
    proven by a scoped read before the insert — and the counts show it was.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(UnknownScopeError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=FOREIGN_PERSON,
                    statement=FIRST_NOTE,
                    idempotency_key="synthetic-foreign-subject-0001",
                ),
            )
        assert _counts(connection) == before
    with two_principals.connect() as connection:
        assert _counts(connection) == before


def test_a_context_link_naming_another_principals_entity_is_refused(
    two_principals: Engine,
) -> None:
    """Every context target is proven to belong to the acting Principal.

    A link is a validated edge, not a free identifier field: without the check a
    memory of A's could name B's project and disclose that it exists.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(UnknownScopeError):
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=DANA,
                    statement=FIRST_NOTE,
                    idempotency_key="synthetic-foreign-link-0001",
                    context_links=(
                        {
                            "target_type": "entity",
                            "target_id": FOREIGN_PERSON,
                            "role": "applies_in",
                        },
                    ),
                ),
            )
        assert _counts(connection) == before


def test_a_context_link_naming_the_acting_principals_own_entity_is_stored(
    two_principals: Engine,
) -> None:
    """The other half, so the refusal above is not passing by refusing every link."""
    receipt = _created(
        two_principals,
        idempotency_key="synthetic-own-link-0001",
        context_links=({"target_type": "entity", "target_id": RIVERSIDE, "role": "applies_in"},),
    )
    with two_principals.connect() as connection:
        detail = SqlRelationshipMemoryRepository(connection).detail(
            receipt.memory_id, principal_id=PRINCIPAL_A
        )
    assert detail is not None
    assert [(link.target_type.value, link.target_id) for link in detail.context_links] == [
        ("entity", RIVERSIDE)
    ]


def test_a_write_to_a_merged_away_subject_is_refused_and_names_the_survivor(
    two_principals: Engine,
) -> None:
    """Following the redirect would rebind the note to a different identity.

    A deliberate annotation about a historical identity is a different statement
    from one about the current person, so the write is refused and the caller is
    told where the subject went rather than silently retargeted.
    """
    with two_principals.begin() as connection:
        before = _counts(connection)
        with pytest.raises(MergedSubjectError) as refusal:
            _admit(
                SqlRelationshipMemoryRepository(connection),
                _create_request(
                    principal_id=PRINCIPAL_A,
                    subject_entity_id=OLD_DANA,
                    statement=FIRST_NOTE,
                    idempotency_key="synthetic-merged-0001",
                ),
            )
        assert _counts(connection) == before
    assert refusal.value.canonical_entity_id == DANA


# --- the migration ------------------------------------------------------------


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
                {"schema": SCHEMA},
            )
        }


def test_the_revision_is_on_one_unbranched_chain_above_the_one_it_revises() -> None:
    """No database. A branched chain is an upgrade with two possible outcomes."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert script.get_revision(MEMORY_REVISION).down_revision == PREVIOUS_REVISION


def test_the_plane_migrates_empty_to_head_and_back_to_head_again(
    disposable_database: str,
) -> None:
    """Empty to head, head to the previous revision, and up again.

    The downgrade half is the one that matters: it drops two triggers, a
    function, eight tables and restates two closed sets, and a downgrade that
    left residue would make the next upgrade fail on a name that already exists.
    Asserted by running the upgrade a second time rather than by inspecting what
    the downgrade left.
    """
    engine = create_database_engine(disposable_database)
    try:
        assert _tables(engine).isdisjoint(MEMORY_TABLES), "the database was not empty"
        command.upgrade(_config(), "head")
        assert _tables(engine).issuperset(MEMORY_TABLES)
        command.downgrade(_config(), PREVIOUS_REVISION)
        assert _tables(engine).isdisjoint(MEMORY_TABLES)
        command.upgrade(_config(), "head")
        assert _tables(engine).issuperset(MEMORY_TABLES)
    finally:
        engine.dispose()


def test_the_append_only_trigger_exists_on_the_version_table(migrated_engine: Engine) -> None:
    """Named rather than inferred from behaviour, so a rename is visible here."""
    with migrated_engine.connect() as connection:
        triggers = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT t.tgname FROM pg_trigger t "
                    "JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :table AND NOT t.tgisinternal"
                ),
                {"schema": SCHEMA, "table": "relationship_memory_versions"},
            )
        }
    assert "relationship_memory_versions_are_append_only" in triggers


def test_the_server_refuses_a_cloud_eligible_version(two_principals: Engine) -> None:
    """The domain refuses it too. This is the copy a repair script cannot skip."""
    receipt = _created(two_principals)
    with two_principals.connect() as connection:  # noqa: SIM117 - two statements, one block
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.relationship_memory_versions "  # noqa: S608
                    "(memory_version_id, memory_id, principal_id, version_number, "
                    "statement_text, statement_sha256, memory_kind, authority, "
                    "classification, cloud_eligible, created_by_actor, recorded_at, "
                    "prior_version_id, idempotency_key, correlation_id) VALUES "
                    "(:version_id, :memory_id, :principal_id, 2, :statement, :digest, "
                    "'general_note', 'user_authored_private_note', 'private_local', true, "
                    "'user', :recorded_at, :prior, 'synthetic-cloud-0001', :correlation)"
                ),
                {
                    "version_id": "memver_cloud0001cloud0001",
                    "memory_id": receipt.memory_id,
                    "principal_id": PRINCIPAL_A,
                    "statement": SECOND_NOTE,
                    "digest": statement_digest(SECOND_NOTE),
                    "recorded_at": LATER,
                    "prior": receipt.memory_version_id,
                    "correlation": issue_identifier(IdKind.CORRELATION),
                },
            )
