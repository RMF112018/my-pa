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

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
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
from my_pa.infrastructure.persistence.enrollment import accept_enrollment
from my_pa.infrastructure.persistence.jobs import (
    JobState,
    claim_job,
    complete_job,
    enqueue_job,
    job_state,
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


def test_the_revision_chain_ends_at_the_knowledge_revision() -> None:
    """Guards the rest of this module: an absent revision would collect nothing.

    Needs no database, so it stays in the fast tier.
    """
    script = ScriptDirectory.from_config(_config())
    assert list(script.get_heads()) == [KNOWLEDGE_REVISION]
    revision = script.get_revision(KNOWLEDGE_REVISION)
    assert revision.down_revision == FOUNDATION_HEAD
    assert len(list(script.walk_revisions())) >= 7
    assert EXPECTED_TABLES and EXPECTED_UNIQUE_CONSTRAINTS and EXPECTED_CHECK_CONSTRAINTS


def test_offline_mode_emits_the_knowledge_ddl_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--sql` has to work with no server: it is how the DDL gets reviewed."""
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    buffer = io.StringIO()

    command.upgrade(_config(output_buffer=buffer), "head", sql=True)

    emitted = buffer.getvalue()
    assert f'CREATE SCHEMA IF NOT EXISTS "{EXPECTED_SCHEMA}"' in emitted
    for table in EXPECTED_TABLES:
        assert f"CREATE TABLE {EXPECTED_SCHEMA}.{table}" in emitted
    for constraint in EXPECTED_UNIQUE_CONSTRAINTS | EXPECTED_CHECK_CONSTRAINTS:
        assert constraint in emitted


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        # CREATE and DROP DATABASE cannot run inside a transaction block.
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
    engine = create_database_engine(disposable_database)
    try:
        assert EXPECTED_SCHEMA not in _schemas(engine)

        command.upgrade(_config(), "head")

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
    """A resumed run re-applies head; the revision must not depend on being new."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        command.downgrade(_config(), "base")
        command.upgrade(_config(), "head")

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
) -> str:
    enrollment_id = issue_identifier(IdKind.ENROLLMENT)
    connection.execute(
        text(
            "INSERT INTO knowledge.enrollments "
            "(enrollment_id, source_id, principal_id, purpose, policy_version, "
            " idempotency_key, request_fingerprint, root_object_id, object_ids, depth, "
            " media_types, max_items, max_bytes) "
            "VALUES (:enrollment_id, :source_id, :principal_id, :purpose, 'mcv-1', "
            " :idempotency_key, :fingerprint, :root_object_id, '{}', :depth, "
            " ARRAY['text/plain'], 100, 1024)"
        ),
        {
            "enrollment_id": enrollment_id,
            "source_id": source_id,
            "principal_id": principal_id,
            "purpose": Purpose.BOUNDED_ENROLLMENT.value,
            "idempotency_key": idempotency_key,
            "fingerprint": fingerprint,
            "root_object_id": issue_identifier(IdKind.SOURCE_OBJECT),
            "depth": depth,
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
        accepted = accept_enrollment(
            connection, _request(source.source_id, issue_identifier(IdKind.PRINCIPAL))
        )
        operation_id = enqueue_job(connection, accepted.enrollment.enrollment_id)

        first = claim_job(connection, owner="worker-one", lease_seconds=1)
        assert first is not None
        assert first.operation_id == operation_id
        assert first.attempt == 1
        assert job_state(connection, operation_id) is JobState.RUNNING

        # A live lease is not claimable by anyone else.
        assert claim_job(connection, owner="worker-two", lease_seconds=1) is None

    with knowledge_engine.begin() as connection:
        # Expire the lease the way a crashed worker would: by the server clock.
        connection.execute(
            text(
                "UPDATE knowledge.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE operation_id = :operation_id"
            ),
            {"operation_id": operation_id},
        )
        second = claim_job(connection, owner="worker-two", lease_seconds=60)
        assert second is not None
        assert second.operation_id == operation_id
        assert second.attempt == 2

        # The worker that lost the lease cannot report on the work.
        assert complete_job(connection, operation_id, owner="worker-one") is False
        assert complete_job(connection, operation_id, owner="worker-two") is True
        assert job_state(connection, operation_id) is JobState.SUCCEEDED


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
        accepted = accept_enrollment(
            connection, _request(source.source_id, issue_identifier(IdKind.PRINCIPAL))
        )
        operation_id = enqueue_job(connection, accepted.enrollment.enrollment_id, max_attempts=2)

        claimed = claim_job(connection, owner="worker-one", lease_seconds=60)
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

        claimed = claim_job(connection, owner="worker-one", lease_seconds=60)
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
        assert claim_job(connection, owner="worker-one", lease_seconds=60) is None
        assert job_state(connection, operation_id) is JobState.FAILED
