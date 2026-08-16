"""The enrollment-objects revision round-trips, and the scope it records is real.

Three claims, separated because they fail for different reasons.

**The revision is in the chain.** Deliberately not "is the head", for the reason
`test_the_audit_revision_is_in_the_chain_on_the_extraction_revision` in
`test_audit_schema_migration.py` records: that property is true only until the
next revision is written, and asserting it makes every later work package edit
this file. A single unbranched chain containing this revision on
`9c6b4a18ed72` is the property everything below actually depends on.

**The DDL is reviewable offline.** `--sql` from the revision below to this one
has to emit the whole change — the new table, its composite primary key, and its
two foreign keys — with no server. That is how the DDL gets reviewed, and it is
what keeps the guard in the fast tier.

**There is no foreign key on `enrollments.root_object_id`, on purpose.**
`enrollments` is created by `7e5a1fb93d62` from the shared `MetaData`, so
declaring that reference would retroactively change the DDL an already-merged
revision emits. The guarantee it would have bought — a root that names no
observed object — is held by `record_scope`, which refuses an unobserved object
and refuses an empty set, and the tests below assert it there.

**The scope is measured, not asserted.** The failure mode in this package is
silent: a mismatched identifier produces empty coverage with no exception
anywhere. So every test here asserts on a *non-empty* count, and the two tests
whose subject is a zero — a refused empty set and a refused foreign object —
carry a control in the same test that produces a non-zero, or the zero would
mean nothing.

The database is disposable, created and dropped by its fixture, and never the
configured one: `downgrade base` deletes schemas, and pointing that at the
canonical `my_pa` database would destroy the migrated corpus. Every value here is
synthetic; no path exists and none is opened.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, NamedTuple

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.enrollment import (
    accept_enrollment,
    enrolled_object_count,
    record_scope,
)
from my_pa.infrastructure.persistence.registry import observe_object, register_source

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

ENROLLMENT_OBJECTS_REVISION = "af3d35efb9c0"
AUDIT_REVISION = "9c6b4a18ed72"

#: The constraints this revision exists to add, by name. Restated rather than
#: imported: a test that reads the name out of the code it is checking proves
#: only that a string was defined once. The primary key is named in the
#: declaration; the two foreign keys are not, so PostgreSQL names them, and these
#: are the names it gives.
#: The tables the revisions *above* this one create, which a downgrade reached
#: from head therefore also removes. Stated explicitly rather than derived, in
#: the style this suite already uses for the same claim: an extra table left
#: behind by any of those downgrades is exactly what these equalities exist to
#: see, and a set computed from the chain would absorb one.
TABLES_ABOVE: Final[frozenset[str]] = frozenset(
    {
        "captures",
        "capture_versions",
        "capture_receipts",
        "capture_submissions",
        "capture_jobs",
        "capture_processing_text",
        "capture_stage_results",
        "capture_spans",
        "capture_proposals",
        "capture_proposal_spans",
        "capture_classifications",
        "capture_entity_mentions",
        "capture_review_cases",
        "capture_review_decisions",
        "capture_assertions",
        "capture_assertion_spans",
        "capture_promotion_receipts",
        "capture_context_links",
        "capture_conversations",
        "capture_clients",
        "commitments",
        "decisions",
        "tasks",
        "continuity_lifecycle_events",
        "task_recurrences",
        "task_history",
        "commitment_history",
        "situations",
        "frames",
        "traces",
        "projects",
        "project_situations",
        "relationship_events",
        "pulse_items",
        "goodnotes_pages",
        "goodnotes_page_versions",
        "goodnotes_region_proposals",
        "goodnotes_review_decisions",
        "goodnotes_reconciliation_receipts",
        "worker_heartbeats",
        # WP-27's managed-document plane.
        "managed_documents",
        "managed_document_versions",
        "managed_document_submissions",
        "managed_document_receipts",
        "managed_document_lifecycle_events",
        "relationship_people",
        "relationship_organizations",
        "relationship_identity_observations",
        "relationship_unresolved_mentions",
        "relationship_duplicate_sets",
        "relationship_duplicate_members",
        "relationship_identity_review_cases",
        "relationship_identity_review_decisions",
        "relationship_identity_resolutions",
        "relationship_resolution_observations",
        "relationship_observation_links",
        "relationship_aliases",
        "relationship_affiliations",
        "relationship_evidence",
        "relationship_evidence_observations",
        "relationship_conversation_participants",
        "relationship_conversation_observations",
        "source_version_evidence",
        "native_bridges",
        "native_bridge_observations",
        "native_source_accounts",
        "native_source_buckets",
        "native_discovery_snapshots",
        "native_configuration_revisions",
        "native_configuration_buckets",
        "native_sync_runs",
        "native_bucket_runs",
        "native_sync_jobs",
        "native_checkpoints",
        "source_observations",
        "source_memberships",
        "native_watcher_simulations",
        "native_simulation_receipts",
        "native_live_activation_gates",
        "native_admission_authorities",
        "native_preflight_observations",
        "native_source_review_routes",
        "native_apple_bridge_credentials",
        "native_apple_read_grants",
        "continuity_authoring_submissions",
        # Context-prepare run tables (`9b2d5f8c3e01`) and preference tables
        # (`c6f1a8d3e204`).
        "context_runs",
        "context_run_items",
        "context_preference_events",
        "context_preference_current",
        "goodnotes_notebooks",
        "goodnotes_notebook_paths",
        "goodnotes_source_snapshots",
        "goodnotes_logical_pages",
        "goodnotes_page_positions",
        "goodnotes_ingestion_runs",
    }
)


SCOPE_PRIMARY_KEY = "an_enrollment_holds_an_object_once"
SCOPE_FOREIGN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "enrollment_objects_enrollment_id_fkey",
        "enrollment_objects_source_object_id_fkey",
    }
)

#: Every column of `enrollment_objects`, restated. The table records which
#: objects, and nothing about where any of them got to — that is `extractions`
#: and `quarantine_records`, and a status column here would give one fact two
#: writers. A column added has to be acknowledged in this list, which is the
#: point.
EXPECTED_SCOPE_COLUMNS: Final[frozenset[str]] = frozenset(
    {"enrollment_id", "source_object_id", "enumerated_at"}
)

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide.
DISPOSABLE_DATABASE = "my_pa_enrollment_objects_test"

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/fixtures/scope"

OBSERVED_AT = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: Well formed and bound to no row: the shape passes `validate_identifier` and
#: `record_scope`'s pre-check is what refuses it.
ABSENT_OBJECT = "obj_0123456789abcdef"


def _config(output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)


def test_the_enrollment_objects_revision_is_in_the_chain() -> None:
    """Guards the rest of this module: an absent revision would create nothing.

    Deliberately not "is the head", for the reason
    `test_the_audit_revision_is_in_the_chain_on_the_extraction_revision` in
    `test_audit_schema_migration.py` gives: that property is true only until the
    next revision is written, and asserting it would make every later work
    package edit this file.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert ENROLLMENT_OBJECTS_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(ENROLLMENT_OBJECTS_REVISION).down_revision == AUDIT_REVISION


def test_the_new_revision_emits_its_ddl_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--sql` has to work with no server: it is how the DDL gets reviewed.

    Every part of the change is asserted by name, because each one is separately
    droppable: a table with neither reference would accept an identifier bound to
    no row — the exact defect this revision exists to close — and a table without
    the composite primary key would take a duplicate on re-enumeration. The
    foreign keys are unnamed in the declaration, so the emitted DDL states them
    as `REFERENCES` clauses and PostgreSQL names them at creation; the names are
    asserted against the server in the database tier below.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    buffer = io.StringIO()

    command.upgrade(
        _config(output_buffer=buffer),
        f"{AUDIT_REVISION}:{ENROLLMENT_OBJECTS_REVISION}",
        sql=True,
    )
    emitted = buffer.getvalue()

    assert f"CREATE TABLE {SCHEMA}.enrollment_objects" in emitted
    assert SCOPE_PRIMARY_KEY in emitted, "the composite primary key is the idempotency mechanism"
    assert (
        f"FOREIGN KEY(enrollment_id) REFERENCES {SCHEMA}.enrollments (enrollment_id) "
        "ON DELETE CASCADE" in emitted
    ), "the enrollment reference is not emitted; a scope row could outlive its enrollment"
    assert (
        f"FOREIGN KEY(source_object_id) REFERENCES {SCHEMA}.source_objects (source_object_id) "
        "ON DELETE CASCADE" in emitted
    ), "the object reference is not emitted; an identifier bound to no row would be storable"


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
def scope_engine(disposable_database: str) -> Iterator[Engine]:
    """A disposable database upgraded to head, disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
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
                {"schema": SCHEMA, "kind": kind},
            ).scalars()
        )


class Enrolled(NamedTuple):
    """One configured source, one accepted enrollment, and its observed objects."""

    source_id: str
    enrollment_id: str
    object_ids: tuple[str, ...]


def _request(source_id: str, *, scope: EnrollmentScope, key: str) -> EnrollmentRequest:
    return EnrollmentRequest(
        source_id=source_id,
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        purpose=Purpose.BOUNDED_ENROLLMENT,
        scope=scope,
        media_types=("text/markdown",),
        policy_version="mcv-1",
        idempotency_key=key,
        max_items=10,
        max_bytes=4096,
    )


def _enrolled(connection: Connection, *, objects: int = 2, label: str = "one") -> Enrolled:
    """A source, `objects` observed files, and an enrollment naming all of them.

    `label` keeps two calls in one transaction from colliding on the source's
    unique native root or on the enrollment's idempotency key.
    """
    source = register_source(
        connection,
        provider_kind=SourceProviderKind.FIXTURE,
        label=f"Fixture corpus {label}",
        classification=Classification.SYNTHETIC_TEST,
        native_root=f"{NATIVE_ROOT}/{label}",
    )
    observed = [
        observe_object(
            connection,
            source_id=source.source_id,
            native_locator=f"{NATIVE_ROOT}/{label}/note-{index}.md",
            kind=ObjectKind.FILE,
            fingerprint=f"fingerprint-{label}-{index}",
            modified_at=OBSERVED_AT,
            media_type="text/markdown",
            size_bytes=8,
        )
        for index in range(objects)
    ]
    object_ids = tuple(entry.source_object_id for entry in observed)
    accepted = accept_enrollment(
        connection,
        _request(
            source.source_id,
            scope=EnrollmentScope(object_ids=object_ids),
            key=f"enroll-scope-{label}",
        ),
    )
    return Enrolled(
        source_id=source.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids=object_ids,
    )


@pytest.mark.database
def test_the_revision_creates_the_scope_table_and_its_constraints(scope_engine: Engine) -> None:
    """The table exists at head with exactly the columns it declares."""
    assert "enrollment_objects" in _tables(scope_engine)
    assert _columns(scope_engine, "enrollment_objects") == EXPECTED_SCOPE_COLUMNS
    assert SCOPE_PRIMARY_KEY in _constraints(scope_engine, "p")
    assert _constraints(scope_engine, "f") >= SCOPE_FOREIGN_KEYS


@pytest.mark.database
def test_downgrading_this_revision_leaves_the_other_knowledge_tables_alone(
    disposable_database: str,
) -> None:
    """This revision added one table to a schema it did not create.

    Its downgrade therefore removes its own table and not the schema, and not the
    nine tables of evidence the revisions below it own. Reaching it from head
    also unwinds the revisions above it, so their tables go too — which is what
    `TABLES_ABOVE` names.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        before = _tables(engine)
        assert "enrollment_objects" in before

        command.downgrade(_config(), AUDIT_REVISION)

        assert _tables(engine) == before - {"enrollment_objects", *TABLES_ABOVE}
        assert len(_tables(engine)) == 9
        assert not (SCOPE_FOREIGN_KEYS & _constraints(engine, "f"))
        assert SCOPE_PRIMARY_KEY not in _constraints(engine, "p")

        command.upgrade(_config(), "head")
        assert _tables(engine) == before

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_record_scope_stores_one_row_per_named_object(scope_engine: Engine) -> None:
    """The count is the whole point: a silent mismatch would report zero."""
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=3)

        held = record_scope(connection, enrolled.enrollment_id, enrolled.object_ids)

        assert held == 3
        assert enrolled_object_count(connection, enrolled.enrollment_id) == 3
        stored = set(
            connection.execute(
                text(
                    "SELECT source_object_id FROM knowledge.enrollment_objects "
                    "WHERE enrollment_id = :enrollment"
                ),
                {"enrollment": enrolled.enrollment_id},
            ).scalars()
        )
        assert stored == set(enrolled.object_ids)


@pytest.mark.database
def test_recording_the_same_scope_twice_adds_no_row(scope_engine: Engine) -> None:
    """Idempotent by `an_enrollment_holds_an_object_once`, not by convention."""
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=2)

        first = record_scope(connection, enrolled.enrollment_id, enrolled.object_ids)
        second = record_scope(connection, enrolled.enrollment_id, enrolled.object_ids)

        assert first == 2
        assert second == first


@pytest.mark.database
def test_a_partly_overlapping_re_enumeration_adds_only_what_is_new(
    scope_engine: Engine,
) -> None:
    """The conflict clause must skip the held rows without skipping the new one."""
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=3)

        first = record_scope(connection, enrolled.enrollment_id, enrolled.object_ids[:2])
        second = record_scope(connection, enrolled.enrollment_id, enrolled.object_ids)

        assert first == 2
        assert second == 3


@pytest.mark.database
def test_record_scope_refuses_an_empty_set_and_records_a_real_one(
    scope_engine: Engine,
) -> None:
    """An unmeasurable enrollment never exists.

    The refusal is the subject and the control is what makes it mean something:
    the same enrollment, in the same transaction, records a non-empty set and
    counts it. Without the control this test would pass against a `record_scope`
    that refused everything.
    """
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=2)

        with pytest.raises(ValueError):
            record_scope(connection, enrolled.enrollment_id, ())

        assert record_scope(connection, enrolled.enrollment_id, enrolled.object_ids) == 2


@pytest.mark.database
def test_record_scope_refuses_an_object_of_another_source(scope_engine: Engine) -> None:
    """The foreign key proves the object exists, not that it belongs here.

    `other.object_ids[0]` is a real row in `source_objects`, so the foreign key
    admits it. Only the pre-check refuses it, and the control in the same
    transaction shows the enrollment's own objects still record.
    """
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=2, label="one")
        other = _enrolled(connection, objects=1, label="two")

        with pytest.raises(UnknownScopeError):
            record_scope(connection, enrolled.enrollment_id, other.object_ids)

        assert record_scope(connection, enrolled.enrollment_id, enrolled.object_ids) == 2


@pytest.mark.database
def test_record_scope_refuses_an_object_that_was_never_observed(
    scope_engine: Engine,
) -> None:
    """A well-formed identifier bound to no row is refused before the insert."""
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=2)

        with pytest.raises(UnknownScopeError):
            record_scope(connection, enrolled.enrollment_id, (ABSENT_OBJECT,))

        assert record_scope(connection, enrolled.enrollment_id, enrolled.object_ids) == 2


@pytest.mark.database
def test_record_scope_refuses_an_enrollment_that_does_not_exist(
    scope_engine: Engine,
) -> None:
    """No enrollment means no source, so nothing can belong to it."""
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=2)
        absent = issue_identifier(IdKind.ENROLLMENT)

        with pytest.raises(UnknownScopeError):
            record_scope(connection, absent, enrolled.object_ids)

        assert record_scope(connection, enrolled.enrollment_id, enrolled.object_ids) == 2


@pytest.mark.database
def test_the_count_is_scoped_to_one_enrollment(scope_engine: Engine) -> None:
    """Two enrollments, two different non-zero counts.

    The failure this catches is silent: a predicate that dropped the
    `enrollment_id` filter would return the same total for both and nothing
    would raise.
    """
    with scope_engine.begin() as connection:
        first = _enrolled(connection, objects=3, label="one")
        second = _enrolled(connection, objects=1, label="two")

        record_scope(connection, first.enrollment_id, first.object_ids)
        record_scope(connection, second.enrollment_id, second.object_ids)

        assert enrolled_object_count(connection, first.enrollment_id) == 3
        assert enrolled_object_count(connection, second.enrollment_id) == 1


@pytest.mark.database
def test_deleting_an_enrollment_takes_its_scope_rows_with_it(scope_engine: Engine) -> None:
    """`ondelete=CASCADE` on both columns, asserted against the server."""
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=2)
        assert record_scope(connection, enrolled.enrollment_id, enrolled.object_ids) == 2

        connection.execute(
            text("DELETE FROM knowledge.enrollments WHERE enrollment_id = :enrollment"),
            {"enrollment": enrolled.enrollment_id},
        )

        assert enrolled_object_count(connection, enrolled.enrollment_id) == 0


@pytest.mark.database
def test_a_root_that_names_no_observed_object_records_no_scope(scope_engine: Engine) -> None:
    """The root guarantee, at the mechanism that actually holds it.

    There is no foreign key on `enrollments.root_object_id` — declaring one would
    retroactively change what `7e5a1fb93d62` emits — so `accept_enrollment` will
    insert a row naming an unobserved root, and that is asserted here rather than
    left implied. What refuses the enrollment is enumeration: an unobserved root
    resolves to nothing, and both shapes enumeration can hand `record_scope` for
    it are refused, so the accepting transaction rolls back and the enrollment
    does not exist.

    The control is the same request with a root that *was* observed, which
    records a non-empty set through the same call. Without it this test would
    pass against a `record_scope` that refused everything.
    """
    with scope_engine.begin() as connection:
        enrolled = _enrolled(connection, objects=1, label="one")

        observed_root = accept_enrollment(
            connection,
            _request(
                enrolled.source_id,
                scope=EnrollmentScope(root_object_id=enrolled.object_ids[0], depth=1),
                key="enroll-root-observed",
            ),
        )
        assert observed_root.created
        assert observed_root.enrollment.scope.root_object_id == enrolled.object_ids[0]

        absent_root = accept_enrollment(
            connection,
            _request(
                enrolled.source_id,
                scope=EnrollmentScope(root_object_id=ABSENT_OBJECT, depth=1),
                key="enroll-root-absent",
            ),
        )
        assert absent_root.created, "no constraint refuses the row; enumeration is what refuses it"

        # What enumerating an unobserved root can produce, both refused.
        with pytest.raises(UnknownScopeError):
            record_scope(connection, absent_root.enrollment.enrollment_id, (ABSENT_OBJECT,))
        with pytest.raises(ValueError):
            record_scope(connection, absent_root.enrollment.enrollment_id, ())
        assert enrolled_object_count(connection, absent_root.enrollment.enrollment_id) == 0

        # The control: an observed root enumerates and counts.
        held = record_scope(
            connection, observed_root.enrollment.enrollment_id, (enrolled.object_ids[0],)
        )
        assert held == 1
