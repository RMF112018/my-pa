"""The knowledge revision round-trips, and its constraints hold on the server.

The schema name, the five table names, and the constraint names are restated
here rather than imported from the revision or from `tables.py`. A test that
imports the list it is checking proves only that a loop ran; these names are the
contract the enrollment and job writers depend on, so they are written out and a
change to any of them has to be acknowledged here.

Every database test runs against a disposable database created and dropped by
its fixture, never against the configured one. `downgrade base` deletes schemas,
and pointing that at the canonical `my_pa` database would destroy the migrated
corpus. Nothing here reads the legacy SQLite source, and every value inserted is
synthetic.

The writer round-trips at the end are here rather than in their own module
because they are claims about the same objects: that the unique constraint makes
an idempotent retry safe, and that a lease expires by the server's clock.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from my_pa.bootstrap.settings import ENV_PREFIX
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import (
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import IsolationLevelError, conflicting_row
from my_pa.infrastructure.persistence.enrollment import accept_enrollment
from my_pa.infrastructure.persistence.jobs import (
    JobState,
    claim_job,
    complete_job,
    enqueue_job,
    job_state,
    reap_abandoned_jobs,
    release_job,
)
from my_pa.infrastructure.persistence.registry import (
    get_source,
    observe_object,
    register_source,
    resolve_native_locator,
)

ROOT = Path(__file__).resolve().parents[2]

#: Restated, not imported.
EXPECTED_SCHEMA = "knowledge"
EXPECTED_TABLES = frozenset(
    {
        "sources",
        "source_objects",
        "source_object_versions",
        "enrollments",
        "jobs",
    }
)
EXPECTED_UNIQUE_CONSTRAINTS = frozenset(
    {
        "sources_native_root_is_configured_once",
        "source_objects_locator_is_issued_once",
        "source_object_versions_are_one_per_fingerprint",
        "enrollments_idempotency_key_is_scoped",
    }
)
EXPECTED_CHECK_CONSTRAINTS = frozenset(
    {
        "enrollment_names_exactly_one_selector",
        "enrollment_depth_is_bounded",
        "an_object_list_has_no_depth",
        "a_job_is_running_exactly_while_leased",
        "attempts_are_bounded",
    }
)

#: Index statements the offline `--sql` artifact must carry, written out in the
#: exact spelling PostgreSQL DDL emits. Restated rather than imported, for the
#: reason the module docstring gives about the names above.
#:
#: **Scope, stated narrowly on purpose.** This closes a gap in *one review
#: artifact*, not an unpinned index. Both functional text indexes are already
#: pinned against a live server by `EXPLAIN`-plan assertion —
#: `tests/search_quality/test_lexical_search.py` for `extractions_full_text` and
#: `tests/search_quality/test_capture_search.py` for `capture_versions_full_text`
#: — and `tests/schema/test_capture_schema_migration.py` checks the second one's
#: definition on the server as well. What none of that covers is the reviewer who
#: reads `--sql` with no server at all: until now that output could have lost an
#: index, or had its expression changed from `gin` to `btree` or its
#: configuration from `english` to `simple`, and this suite would have said
#: nothing. Three statements, not seventeen: this revision's own index, and the
#: two functional ones whose *expression* is the thing a reader cannot verify by
#: eye. The chain emits fourteen more into `knowledge` that are not asserted
#: here, and the assertion below is a subset test, so a new index does not force
#: an edit and is not attested either.
EXPECTED_INDEX_STATEMENTS = frozenset(
    {
        "CREATE INDEX jobs_by_state ON knowledge.jobs (state, created_at);",
        "CREATE INDEX extractions_full_text ON knowledge.extractions "
        "USING gin (to_tsvector('english', text));",
        "CREATE INDEX capture_versions_full_text ON knowledge.capture_versions "
        "USING gin (to_tsvector('simple', content));",
    }
)

KNOWLEDGE_REVISION = "7e5a1fb93d62"
FOUNDATION_HEAD = "6c4d3ea82f10"

#: Schemas this revision must leave alone. They hold the migrated corpus.
FOUNDATION_SCHEMAS = frozenset(
    {
        "core",
        "procore",
        "email",
        "calendar",
        "contacts",
        "financial",
        "schedule",
        "construction",
        "migration_control",
    }
)

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one instead of leaving a growing pile of databases behind. Distinct from the
#: names the foundation and loader suites use, so the three cannot collide.
DISPOSABLE_DATABASE = "my_pa_knowledge_test"

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/fixtures/corpus"
NATIVE_LOCATOR = "/synthetic/fixtures/corpus/quarterly-report.md"


def _config(output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)


def _schemas(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": EXPECTED_SCHEMA},
            ).scalars()
        )


def _constraints(engine: Engine, kind: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_namespace n ON n.oid = con.connamespace "
                    "WHERE n.nspname = :schema AND con.contype = :kind"
                ),
                {"schema": EXPECTED_SCHEMA, "kind": kind},
            ).scalars()
        )


def test_the_knowledge_revision_is_in_the_chain_on_the_foundation_head() -> None:
    """Guards the rest of this module: an absent revision would collect nothing.

    This asserted that the knowledge revision *was* the head until WP-3's
    extraction revision landed on top of it. Being the head was never the
    property worth guarding — it is true only until the next revision is written,
    and any later work would have had to edit this line. What matters is that the
    revision exists, sits on the foundation head, and lies on a single unbranched
    chain, so the tables below are the ones a migration to head produces.

    Needs no database, so it stays in the fast tier.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert KNOWLEDGE_REVISION in {entry.revision for entry in script.walk_revisions()}
    revision = script.get_revision(KNOWLEDGE_REVISION)
    assert revision.down_revision == FOUNDATION_HEAD
    assert len(list(script.walk_revisions())) >= 7
    assert EXPECTED_TABLES and EXPECTED_UNIQUE_CONSTRAINTS and EXPECTED_CHECK_CONSTRAINTS
    assert EXPECTED_INDEX_STATEMENTS


def test_offline_mode_emits_the_knowledge_ddl_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--sql` has to work with no server: it is how the DDL gets reviewed.

    Indexes are asserted here as whole statements rather than as bare names.
    A name alone would be satisfied by `CREATE INDEX extractions_full_text ON
    knowledge.extractions (text)` — the same name over a plain btree, which the
    online `EXPLAIN` tests would catch and a reader of this artifact would not.
    `EXPECTED_INDEX_STATEMENTS` says what the gap is and, more importantly, what
    it is not.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    buffer = io.StringIO()

    command.upgrade(_config(output_buffer=buffer), "head", sql=True)

    emitted = buffer.getvalue()
    assert f'CREATE SCHEMA IF NOT EXISTS "{EXPECTED_SCHEMA}"' in emitted
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {EXPECTED_SCHEMA}.{table}" in emitted
    for constraint in EXPECTED_UNIQUE_CONSTRAINTS | EXPECTED_CHECK_CONSTRAINTS:
        assert constraint in emitted
    for statement in EXPECTED_INDEX_STATEMENTS:
        assert statement in emitted, statement


@pytest.fixture
def knowledge_engine(disposable_database: str) -> Iterator[Engine]:
    """A disposable database upgraded to head, disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


@pytest.mark.database
def test_upgrade_from_empty_and_downgrade_back_to_empty(disposable_database: str) -> None:
    """Empty to this revision and back.

    The target is the knowledge revision rather than `head`, because the claim
    is an equality: these five tables and no others. A later revision adding a
    table to this schema — WP-3's extraction revision does — would otherwise turn
    a statement about what this revision creates into a statement about what
    every revision creates, and the equality would have to be weakened to a
    subset. Naming the revision keeps the stronger claim.
    """
    engine = create_database_engine(disposable_database)
    try:
        assert EXPECTED_SCHEMA not in _schemas(engine)

        command.upgrade(_config(), KNOWLEDGE_REVISION)

        assert EXPECTED_SCHEMA in _schemas(engine)
        assert _tables(engine) == EXPECTED_TABLES
        assert _constraints(engine, "u") >= EXPECTED_UNIQUE_CONSTRAINTS
        assert _constraints(engine, "c") >= EXPECTED_CHECK_CONSTRAINTS

        command.downgrade(_config(), "base")

        assert EXPECTED_SCHEMA not in _schemas(engine)
        assert _schemas(engine).isdisjoint(FOUNDATION_SCHEMAS)
    finally:
        engine.dispose()


@pytest.mark.database
def test_upgrade_is_repeatable_after_a_full_round_trip(disposable_database: str) -> None:
    """A resumed run re-applies the revision; it must not depend on being new.

    Targets the revision rather than `head` for the same reason as the test
    above.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), KNOWLEDGE_REVISION)
        command.downgrade(_config(), "base")
        command.upgrade(_config(), KNOWLEDGE_REVISION)

        assert _tables(engine) == EXPECTED_TABLES
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_one_revision_removes_only_the_knowledge_schema(
    disposable_database: str,
) -> None:
    """The migrated corpus is not this revision's to touch, in either direction."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        command.downgrade(_config(), FOUNDATION_HEAD)

        schemas = _schemas(engine)
        assert EXPECTED_SCHEMA not in schemas
        assert schemas >= FOUNDATION_SCHEMAS

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


def _insert_source(connection: Connection, *, native_root: str = NATIVE_ROOT) -> str:
    source_id = issue_identifier(IdKind.SOURCE)
    connection.execute(
        text(
            "INSERT INTO knowledge.sources "
            "(source_id, provider_kind, label, classification, native_root) "
            "VALUES (:source_id, 'fixture', 'Fixture corpus', 'synthetic_test', :native_root)"
        ),
        {"source_id": source_id, "native_root": native_root},
    )
    return source_id


def _insert_enrollment(
    connection: Connection,
    *,
    source_id: str,
    principal_id: str,
    idempotency_key: str,
    fingerprint: str,
    depth: int = 0,
    object_ids: tuple[str, ...] = (),
    max_items: int = 100,
) -> str:
    """Insert one enrollment by hand.

    Raw SQL rather than the writer, because these tests are about what the table
    refuses. A constraint that only holds when the writer is used is not a
    constraint.
    """
    enrollment_id = issue_identifier(IdKind.ENROLLMENT)
    connection.execute(
        text(
            "INSERT INTO knowledge.enrollments "
            "(enrollment_id, source_id, principal_id, purpose, policy_version, "
            " idempotency_key, request_fingerprint, root_object_id, object_ids, depth, "
            " media_types, max_items, max_bytes) "
            "VALUES (:enrollment_id, :source_id, :principal_id, :purpose, 'mcv-1', "
            " :idempotency_key, :fingerprint, :root_object_id, :object_ids, :depth, "
            " ARRAY['text/plain'], :max_items, 1024)"
        ),
        {
            "enrollment_id": enrollment_id,
            "source_id": source_id,
            "principal_id": principal_id,
            "purpose": Purpose.BOUNDED_ENROLLMENT.value,
            "idempotency_key": idempotency_key,
            "fingerprint": fingerprint,
            # Exactly one selector, so naming objects means naming no root.
            "root_object_id": None if object_ids else issue_identifier(IdKind.SOURCE_OBJECT),
            "object_ids": list(object_ids),
            "depth": depth,
            "max_items": max_items,
        },
    )
    return enrollment_id


@pytest.mark.database
def test_one_idempotency_key_admits_exactly_one_row(knowledge_engine: Engine) -> None:
    """The structural half of section 8.6, proved against a hand-run statement.

    Enforcing this in Python alone would leave two concurrent requests able to
    both read "absent" and both insert.
    """
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with knowledge_engine.begin() as connection:
        source_id = _insert_source(connection)
        _insert_enrollment(
            connection,
            source_id=source_id,
            principal_id=principal_id,
            idempotency_key="enroll-0000000001",
            fingerprint="a" * 64,
        )

    with pytest.raises(IntegrityError), knowledge_engine.begin() as connection:
        _insert_enrollment(
            connection,
            source_id=source_id,
            principal_id=principal_id,
            idempotency_key="enroll-0000000001",
            fingerprint="b" * 64,
        )


@pytest.mark.database
def test_the_schema_refuses_an_enrollment_deeper_than_the_bound(
    knowledge_engine: Engine,
) -> None:
    """The domain type is not the only guard; the table is bounded too."""
    with pytest.raises(IntegrityError), knowledge_engine.begin() as connection:
        source_id = _insert_source(connection)
        _insert_enrollment(
            connection,
            source_id=source_id,
            principal_id=issue_identifier(IdKind.PRINCIPAL),
            idempotency_key="enroll-0000000002",
            fingerprint="c" * 64,
            depth=9,
        )


@pytest.mark.database
def test_the_schema_refuses_an_enrollment_naming_more_objects_than_it_allows(
    knowledge_engine: Engine,
) -> None:
    """The request type is not the only guard; the table relates the two bounds too."""
    named = tuple(issue_identifier(IdKind.SOURCE_OBJECT) for _ in range(5))
    with pytest.raises(IntegrityError), knowledge_engine.begin() as connection:
        source_id = _insert_source(connection)
        _insert_enrollment(
            connection,
            source_id=source_id,
            principal_id=issue_identifier(IdKind.PRINCIPAL),
            idempotency_key="enroll-0000000004",
            fingerprint="d" * 64,
            object_ids=named,
            max_items=1,
        )


@pytest.mark.database
def test_the_schema_accepts_an_object_list_that_fits_its_ceiling(
    knowledge_engine: Engine,
) -> None:
    """The paired negative: the constraint must not refuse a legitimate grant."""
    named = tuple(issue_identifier(IdKind.SOURCE_OBJECT) for _ in range(5))
    with knowledge_engine.begin() as connection:
        source_id = _insert_source(connection)
        enrollment_id = _insert_enrollment(
            connection,
            source_id=source_id,
            principal_id=issue_identifier(IdKind.PRINCIPAL),
            idempotency_key="enroll-0000000005",
            fingerprint="e" * 64,
            object_ids=named,
            max_items=5,
        )
    assert enrollment_id


@pytest.mark.database
def test_registering_the_same_root_twice_returns_one_identity(
    knowledge_engine: Engine,
) -> None:
    with knowledge_engine.begin() as connection:
        first = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        second = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        assert first.source_id == second.source_id
        assert get_source(connection, first.source_id) == first


@pytest.mark.database
def test_an_object_keeps_its_identity_and_gains_a_version_when_it_changes(
    knowledge_engine: Engine,
) -> None:
    when = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        first = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=NATIVE_LOCATOR,
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-one",
            modified_at=when,
            media_type="text/markdown",
            size_bytes=12,
        )
        again = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=NATIVE_LOCATOR,
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-one",
            modified_at=when,
            media_type="text/markdown",
            size_bytes=12,
        )
        changed = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=NATIVE_LOCATOR,
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-two",
            modified_at=when,
            media_type="text/markdown",
            size_bytes=13,
        )

        assert again == first
        assert changed.source_object_id == first.source_object_id
        assert changed.version_id != first.version_id

        # The locator is resolvable internally and appears in no domain value.
        assert resolve_native_locator(connection, first.source_object_id) == NATIVE_LOCATOR
        assert NATIVE_LOCATOR not in repr(first)


def _request(source_id: str, principal_id: str, **overrides: object) -> EnrollmentRequest:
    values: dict[str, object] = {
        "source_id": source_id,
        "principal_id": principal_id,
        "purpose": Purpose.BOUNDED_ENROLLMENT,
        "scope": EnrollmentScope(root_object_id=issue_identifier(IdKind.SOURCE_OBJECT)),
        "media_types": ("text/plain",),
        "policy_version": "mcv-1",
        "idempotency_key": "enroll-0000000003",
        "max_items": 10,
        "max_bytes": 1024,
    }
    values.update(overrides)
    return EnrollmentRequest(**values)  # type: ignore[arg-type]


@pytest.mark.database
def test_reusing_a_key_with_the_same_request_returns_the_same_enrollment(
    knowledge_engine: Engine,
) -> None:
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        principal_id = issue_identifier(IdKind.PRINCIPAL)
        request = _request(source.source_id, principal_id)

        first = accept_enrollment(connection, request)
        second = accept_enrollment(connection, request)

    assert first.created is True
    assert second.created is False
    assert second.enrollment == first.enrollment


@pytest.mark.database
def test_reusing_a_key_with_a_different_request_is_a_conflict(
    knowledge_engine: Engine,
) -> None:
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        principal_id = issue_identifier(IdKind.PRINCIPAL)
        accepted = accept_enrollment(connection, _request(source.source_id, principal_id))

        with pytest.raises(EnrollmentConflictError) as raised:
            accept_enrollment(
                connection,
                _request(source.source_id, principal_id, max_items=9),
            )

    assert raised.value.enrollment_id == accepted.enrollment.enrollment_id


#: The Principal whose queue every job test below claims from.
#:
#: One value rather than a fresh identifier per job, because `claim_job` is
#: partitioned by Principal (WP-04, revision `4f1a8b6d92e3`): the contended
#: tests enqueue two jobs and expect two workers to take one each, which is a
#: claim about `SKIP LOCKED` and not about the partition, so both jobs have to
#: be in the same partition for the claim to be reachable at all.
QUEUE_PRINCIPAL: Final = "prn_qqqq0004qqqqqqqqqqqqqq00000004"


def _enqueued(
    connection: Connection,
    *,
    max_attempts: int = 3,
    principal_id: str = QUEUE_PRINCIPAL,
) -> str:
    """A source, an enrollment, and one queued job. Returns the operation id."""
    source = register_source(
        connection,
        provider_kind=SourceProviderKind.FIXTURE,
        label="Fixture corpus",
        classification=Classification.SYNTHETIC_TEST,
        native_root=NATIVE_ROOT,
    )
    accepted = accept_enrollment(
        connection,
        _request(
            source.source_id,
            principal_id,
            idempotency_key=f"enroll-{uuid4().hex[:10]}",
        ),
    )
    return enqueue_job(connection, accepted.enrollment.enrollment_id, max_attempts=max_attempts)


def _expire_lease(connection: Connection, operation_id: str) -> None:
    """Age a lease past its expiry the way a crashed worker would: by the clock."""
    connection.execute(
        text(
            "UPDATE knowledge.jobs SET lease_expires_at = now() - interval '1 second' "
            "WHERE operation_id = :operation_id"
        ),
        {"operation_id": operation_id},
    )


def _stored_row(connection: Connection, operation_id: str) -> tuple[str, str | None, str | None]:
    """The columns as written, bypassing any derivation `job_state` performs."""
    row = connection.execute(
        text(
            "SELECT state, lease_owner, last_error_code FROM knowledge.jobs "
            "WHERE operation_id = :operation_id"
        ),
        {"operation_id": operation_id},
    ).one()
    return (str(row[0]), row[1], row[2])


@pytest.mark.database
def test_a_worker_that_crashes_on_its_final_attempt_reaches_a_terminal_state(
    knowledge_engine: Engine,
) -> None:
    """The case an expiring lease alone does not recover.

    With attempts left, an expired lease makes the job claimable again. On the
    final attempt there is no next claim to recover it, so without the reap the
    row sits at `running` — unclaimable and non-terminal — and `job_state`
    reports live work that nothing is doing, forever.
    """
    with knowledge_engine.begin() as connection:
        operation_id = _enqueued(connection, max_attempts=1)
        claimed = claim_job(
            connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60
        )
        assert claimed is not None
        assert claimed.attempt == 1

        # The worker vanishes: it neither completes nor releases.
        _expire_lease(connection, operation_id)

        assert (
            claim_job(
                connection, principal_id=QUEUE_PRINCIPAL, owner="worker-two", lease_seconds=60
            )
            is None
        )
        assert job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.FAILED
        # Terminal in the column, not only in the answer.
        assert _stored_row(connection, operation_id) == ("failed", None, "unavailable")


@pytest.mark.database
def test_an_abandoned_final_attempt_reads_as_failed_before_anything_reclaims_it(
    knowledge_engine: Engine,
) -> None:
    """`job_state` derives the terminal answer; the reap writes it down.

    The two use one predicate, so the answer given before convergence and the
    value stored after it are the same answer.
    """
    with knowledge_engine.begin() as connection:
        operation_id = _enqueued(connection, max_attempts=1)
        assert (
            claim_job(
                connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60
            )
            is not None
        )
        _expire_lease(connection, operation_id)

        # Reported terminal immediately, without a write.
        assert job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.FAILED
        assert _stored_row(connection, operation_id)[0] == "running"

        assert reap_abandoned_jobs(connection, principal_id=QUEUE_PRINCIPAL) == 1
        assert _stored_row(connection, operation_id) == ("failed", None, "unavailable")
        # Idempotent: the first call left nothing for the second.
        assert reap_abandoned_jobs(connection, principal_id=QUEUE_PRINCIPAL) == 0
        assert job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.FAILED


@pytest.mark.database
def test_a_live_lease_is_not_reaped_however_many_attempts_it_has_used(
    knowledge_engine: Engine,
) -> None:
    """The paired negative: work in progress on its last attempt is still running."""
    with knowledge_engine.begin() as connection:
        operation_id = _enqueued(connection, max_attempts=1)
        assert (
            claim_job(
                connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=600
            )
            is not None
        )

        assert reap_abandoned_jobs(connection, principal_id=QUEUE_PRINCIPAL) == 0
        assert job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.RUNNING
        assert _stored_row(connection, operation_id)[0] == "running"
        assert complete_job(connection, operation_id, owner="worker-one") is True


@pytest.mark.database
def test_a_job_is_claimed_once_and_an_expired_lease_is_reclaimed(
    knowledge_engine: Engine,
) -> None:
    """A crashed worker releases its work by doing nothing at all."""
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        accepted = accept_enrollment(connection, _request(source.source_id, QUEUE_PRINCIPAL))
        operation_id = enqueue_job(connection, accepted.enrollment.enrollment_id)

        first = claim_job(
            connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=1
        )
        assert first is not None
        assert first.operation_id == operation_id
        assert first.attempt == 1
        assert job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.RUNNING

        # A live lease is not claimable by anyone else.
        assert (
            claim_job(connection, principal_id=QUEUE_PRINCIPAL, owner="worker-two", lease_seconds=1)
            is None
        )

    with knowledge_engine.begin() as connection:
        # Expire the lease the way a crashed worker would: by the server clock.
        connection.execute(
            text(
                "UPDATE knowledge.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        )
        second = claim_job(
            connection, principal_id=QUEUE_PRINCIPAL, owner="worker-two", lease_seconds=60
        )
        assert second is not None
        assert second.operation_id == operation_id
        assert second.attempt == 2

        # The worker that lost the lease cannot report on the work.
        assert complete_job(connection, operation_id, owner="worker-one") is False
        assert complete_job(connection, operation_id, owner="worker-two") is True
        assert (
            job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.SUCCEEDED
        )


@pytest.mark.database
def test_attempts_are_bounded_and_end_in_a_terminal_state(knowledge_engine: Engine) -> None:
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        accepted = accept_enrollment(connection, _request(source.source_id, QUEUE_PRINCIPAL))
        operation_id = enqueue_job(connection, accepted.enrollment.enrollment_id, max_attempts=2)

        claimed = claim_job(
            connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60
        )
        assert claimed is not None
        assert (
            release_job(
                connection,
                operation_id,
                owner="worker-one",
                error_code=ErrorCode.UNAVAILABLE,
            )
            is JobState.QUEUED
        )

        claimed = claim_job(
            connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60
        )
        assert claimed is not None
        assert claimed.attempt == 2
        assert (
            release_job(
                connection,
                operation_id,
                owner="worker-one",
                error_code=ErrorCode.UNAVAILABLE,
            )
            is JobState.FAILED
        )

        # Exhausted work is not handed out again.
        assert (
            claim_job(
                connection, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60
            )
            is None
        )
        assert job_state(connection, operation_id, principal_id=QUEUE_PRINCIPAL) is JobState.FAILED


#: Long enough that a healthy claim never trips it, short enough that a claim
#: which blocks fails the test instead of hanging the suite. Without
#: `SKIP LOCKED` the second claim below waits on the first worker's row lock,
#: and waiting forever is not a test result.
CONTENDED_CLAIM_TIMEOUT_MS = 5000


@pytest.mark.database
def test_two_simultaneous_workers_do_not_take_the_same_job(knowledge_engine: Engine) -> None:
    """Two real connections, two open transactions — the contended path.

    A single-transaction test cannot reach this code: the second claim there is
    filtered out by the lease predicate before `SKIP LOCKED` is consulted, so it
    proves nothing about locking. Here the first worker's row lock is genuinely
    held by another transaction when the second worker scans.
    """
    with knowledge_engine.begin() as setup:
        _enqueued(setup)
        _enqueued(setup)

    with knowledge_engine.connect() as alpha, knowledge_engine.connect() as beta:
        beta.execute(text(f"SET LOCAL statement_timeout = '{CONTENDED_CLAIM_TIMEOUT_MS}ms'"))

        first = claim_job(alpha, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60)
        second = claim_job(beta, principal_id=QUEUE_PRINCIPAL, owner="worker-two", lease_seconds=60)

        assert first is not None
        assert second is not None
        assert first.operation_id != second.operation_id
        assert first.attempt == second.attempt == 1


@pytest.mark.database
def test_a_contended_claim_yields_rather_than_waiting(knowledge_engine: Engine) -> None:
    """With one job and two claimers, the loser gets `None` instead of blocking.

    This is what `SKIP LOCKED` buys. Without it the second claim waits on the
    first transaction's row lock and the statement timeout fires, so the
    assertion below is reached only when the lock is genuinely skipped.
    """
    with knowledge_engine.begin() as setup:
        operation_id = _enqueued(setup)

    with knowledge_engine.connect() as alpha, knowledge_engine.connect() as beta:
        beta.execute(text(f"SET LOCAL statement_timeout = '{CONTENDED_CLAIM_TIMEOUT_MS}ms'"))

        first = claim_job(alpha, principal_id=QUEUE_PRINCIPAL, owner="worker-one", lease_seconds=60)
        assert first is not None
        assert first.operation_id == operation_id

        assert (
            claim_job(beta, principal_id=QUEUE_PRINCIPAL, owner="worker-two", lease_seconds=60)
            is None
        )


@pytest.mark.database
def test_a_retry_on_a_new_connection_finds_the_committed_enrollment(
    knowledge_engine: Engine,
) -> None:
    """The insert-then-select fallback, across a commit boundary.

    Deliberately not the simultaneous-insert race: the second `INSERT` blocks on
    the unique index until the first transaction commits, so interleaving the
    two needs a second thread and this test does not attempt it. What it proves
    is the half that needs no thread — that a retry arriving on a fresh
    connection, with a fresh snapshot, takes the `ON CONFLICT` path, finds the
    committed row, and returns it rather than raising or inserting a second.
    """
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        request = _request(source.source_id, issue_identifier(IdKind.PRINCIPAL))
        first = accept_enrollment(connection, request)
    assert first.created is True

    with knowledge_engine.begin() as connection:
        second = accept_enrollment(connection, request)
    assert second.created is False
    assert second.enrollment == first.enrollment

    with knowledge_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT count(*) FROM knowledge.enrollments WHERE source_id = :source_id"),
            {"source_id": source.source_id},
        ).scalar_one()
    assert rows == 1


def test_the_conflict_fallback_names_its_isolation_dependency() -> None:
    """`conflicting_row` is the guard, and it says what it is guarding.

    A pure function, so it needs no server. Reaching it means an insert
    conflicted and the row it conflicted with was not readable a statement
    later, which under READ COMMITTED means the row was deleted in between.
    Letting `.one()` raise `NoResultFound` there would report that as an absent
    enrollment, which is the one thing it is not.
    """
    assert conflicting_row("enr_present", "knowledge.enrollments") == "enr_present"
    with pytest.raises(IsolationLevelError, match="READ COMMITTED"):
        conflicting_row(None, "knowledge.enrollments")


@pytest.mark.database
def test_raising_the_isolation_level_breaks_the_retry_rather_than_corrupting_it(
    knowledge_engine: Engine,
) -> None:
    """Measured, not assumed: what a higher isolation level actually does here.

    The insert-then-select fallback is correct under READ COMMITTED, which is
    PostgreSQL's default and which `create_database_engine` does not override —
    so it is correct by configuration rather than by anything the writer does.
    Raising the level does not silently corrupt the result: when the conflicting
    row was committed after this transaction's snapshot, PostgreSQL refuses the
    `ON CONFLICT DO NOTHING` itself with a serialization failure, before the
    select is reached. That is a retryable error rather than a wrong answer, but
    it is still a broken retry path, and it is why the dependency is written
    down at each call site.
    """
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        request = _request(source.source_id, issue_identifier(IdKind.PRINCIPAL))

    with knowledge_engine.connect().execution_options(isolation_level="REPEATABLE READ") as stale:
        # Fix the snapshot before the enrollment exists.
        stale.execute(text("SELECT 1"))

        with knowledge_engine.begin() as connection:
            accept_enrollment(connection, request)

        with pytest.raises(OperationalError, match="could not serialize access"):
            accept_enrollment(stale, request)


@pytest.mark.database
def test_repeatable_read_is_only_a_problem_when_the_row_arrives_after_the_snapshot(
    knowledge_engine: Engine,
) -> None:
    """The boundary of the finding above, so the docstrings do not overstate it.

    When the conflicting row was already committed when the transaction began,
    the insert conflicts against a row the snapshot can see, nothing serializes,
    and the fallback select returns it. The dependency is on snapshot age, not
    on the isolation level alone.
    """
    with knowledge_engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=NATIVE_ROOT,
        )
        request = _request(source.source_id, issue_identifier(IdKind.PRINCIPAL))
        first = accept_enrollment(connection, request)

    with knowledge_engine.connect().execution_options(isolation_level="REPEATABLE READ") as later:
        retried = accept_enrollment(later, request)

    assert retried.created is False
    assert retried.enrollment == first.enrollment


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
