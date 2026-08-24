"""Revision `2fe4e13fb449` against a real PostgreSQL server.

A sibling of `tests/schema/test_entity_schema_migration.py` rather than more of
it: that module's subject is the shape the entity plane was created with, and
this one's is the lifecycle, Principal-integrity and ledger revision laid on top
of it. Splitting them keeps each file's `PREVIOUS_REVISION` meaning one thing.

Four groups, and the second is the one that could not be asserted any other way:

* the revision is on the single unbranched chain, and returns the database to
  what `f1c6b904a2d7` denotes;
* **the backfill aborts rather than guessing.** Four legacy states are seeded
  at the revision below, the upgrade is run, and it must raise and name what it
  found. A migration that guessed would put exactly the row the new CHECK
  refuses on the other side of the CHECK, and nothing downstream could tell;
* every constraint and index the declaration names exists on the migrated
  server, for the three new tables, the six that were widened and the two that
  gain composite references only;
* each new rule actually refuses the row it names -- the closed sets, the
  canonical binding, the composite Principal references, the exactly-one
  evidence shape, and the two append-only triggers. The four partial uniques are
  asserted *behaviourally* rather than by name, because a non-unique index
  carrying the declared name satisfies every parity assertion in the group
  above and enforces nothing.

The database is disposable, created and dropped by this module's own fixture
under a name no other module uses, and is never the configured one.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.sql.elements import TextClause

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

LIFECYCLE_REVISION: Final = "2fe4e13fb449"
PREVIOUS_REVISION: Final = "f1c6b904a2d7"

#: The three tables this revision creates.
NEW_TABLES: Final = frozenset(
    {
        "entity_mutation_events",
        "entity_fact_evidence_links",
        "entity_resolution_decisions",
    }
)

#: The six tables it widens. Named because the parity assertions below cover
#: them too: a column added by hand-written `ALTER` that the declaration does not
#: name, or the reverse, is invisible from the application until a write fails.
WIDENED_TABLES: Final = frozenset(
    {
        "entities",
        "entity_external_identifiers",
        "entity_aliases",
        "entity_assignments",
        "entity_relationships",
        "entity_observations",
    }
)

#: The two tables it gives Principal-composite references and nothing else.
#: Named apart from `WIDENED_TABLES` because no column of either changes, and
#: the parity assertions below cover all three sets alike.
REFERENCED_TABLES: Final = frozenset({"entity_proposals", "entity_merge_records"})

DISPOSABLE_DATABASE: Final = "my_pa_entity_lifecycle_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY_A: Final = "ent_aaaa0001aaaa0001"
ENTITY_B: Final = "ent_bbbb0002bbbb0002"
ENTITY_C: Final = "ent_cccc0003cccc0003"
OBSERVATION_A: Final = "eobs_aaaa0001aaaa0001"
PROPOSAL_A: Final = "eprp_aaaa0001aaaa0001"
PROPOSAL_B: Final = "eprp_bbbb0002bbbb0002"


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
def previous_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database at the revision *below* this one.

    The seeding fixture for the abort group: a legacy row can only be written
    where the constraint that refuses it does not exist yet.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _execute(engine: Engine, statement: TextClause, **parameters: object) -> None:
    with engine.begin() as connection:
        connection.execute(statement, parameters)


def _facts(engine: Engine) -> set[str]:
    """Constraints, columns, indexes and triggers of the `knowledge` schema."""
    with engine.connect() as connection:
        return {
            str(row)
            for row in connection.execute(
                text(
                    "SELECT 'constraint '||t.relname||'.'||con.conname"
                    "       ||' = '||pg_get_constraintdef(con.oid) "
                    "FROM pg_constraint con JOIN pg_class t ON t.oid = con.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = :schema "
                    "UNION ALL "
                    "SELECT 'column '||t.relname||'.'||a.attname"
                    "       ||' = '||format_type(a.atttypid, a.atttypmod)"
                    "       ||' notnull='||a.attnotnull "
                    "FROM pg_attribute a JOIN pg_class t ON t.oid = a.attrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND a.attnum > 0 AND NOT a.attisdropped "
                    "  AND t.relkind = 'r' "
                    "UNION ALL "
                    "SELECT 'index '||i.indexrelid::regclass::text"
                    "       ||' = '||pg_get_indexdef(i.indexrelid) "
                    "FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = :schema "
                    "UNION ALL "
                    "SELECT 'trigger '||t.relname||'.'||g.tgname"
                    "       ||' = '||pg_get_triggerdef(g.oid) "
                    "FROM pg_trigger g JOIN pg_class t ON t.oid = g.tgrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND NOT g.tgisinternal"
                ),
                {"schema": SCHEMA},
            ).scalars()
        }


def _seed_entity(engine: Engine, entity_id: str, principal_id: str) -> None:
    _execute(
        engine,
        text(
            f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
            "(entity_id, principal_id, entity_type, canonical_name, display_name) "
            "VALUES (:entity_id, :principal_id, 'person', :name, :name)"
        ),
        entity_id=entity_id,
        principal_id=principal_id,
        name="synthetic person",
    )


def _seed_observation(engine: Engine, observation_id: str = OBSERVATION_A) -> None:
    _execute(
        engine,
        text(
            f"INSERT INTO {SCHEMA}.entity_observations "  # noqa: S608
            "(observation_id, principal_id, kind, observed_value, normalized_value, "
            "source_id, source_object_id, source_version_id, observed_at, recorded_at) "
            "VALUES (:observation_id, :principal_id, 'message_participant', 'Alice Chen', "
            "'alice chen', 'src_aaaa0001aaaa0001', 'obj_aaaa0001aaaa0001', "
            "'ver_aaaa0001aaaa0001', '2026-08-23T12:00:00+00:00', '2026-08-23T12:00:00+00:00')"
        ),
        observation_id=observation_id,
        principal_id=PRINCIPAL_A,
    )


def _seed_identifier(
    engine: Engine, identifier_id: str, entity_id: str, value: str, namespace: str = "email"
) -> None:
    _execute(
        engine,
        text(
            f"INSERT INTO {SCHEMA}.entity_external_identifiers "  # noqa: S608
            "(identifier_id, entity_id, namespace, normalized_value, display_value, principal_id) "
            "VALUES (:identifier_id, :entity_id, :namespace, :value, :value, :principal_id)"
        ),
        identifier_id=identifier_id,
        entity_id=entity_id,
        namespace=namespace,
        value=value,
        principal_id=PRINCIPAL_A,
    )


def _seed_alias(
    engine: Engine,
    alias_id: str,
    entity_id: str,
    value: str,
    alias_type: str = "nickname",
    principal_id: str = PRINCIPAL_A,
) -> None:
    _execute(
        engine,
        text(
            f"INSERT INTO {SCHEMA}.entity_aliases "  # noqa: S608
            "(alias_id, entity_id, alias_type, normalized_value, display_value, principal_id) "
            "VALUES (:alias_id, :entity_id, :alias_type, :value, :value, :principal_id)"
        ),
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=alias_type,
        value=value,
        principal_id=principal_id,
    )


def _retire(engine: Engine, table: str, key_column: str, key: str) -> None:
    """Take one binding out of service, which is what makes the uniques partial."""
    _execute(
        engine,
        text(
            f"UPDATE {SCHEMA}.{table} SET state = 'retired', retired_at = now() "  # noqa: S608
            f"WHERE {key_column} = :key"
        ),
        key=key,
    )


def _seed_relationship(
    engine: Engine,
    relationship_id: str,
    from_entity_id: str,
    to_entity_id: str,
    relationship_type: str = "works_for",
    scope_entity_id: str | None = None,
) -> None:
    _execute(
        engine,
        text(
            f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
            "(relationship_id, from_entity_id, to_entity_id, relationship_type, "
            "scope_entity_id, principal_id) "
            "VALUES (:relationship_id, :from_id, :to_id, :relationship_type, :scope_id, "
            ":principal_id)"
        ),
        relationship_id=relationship_id,
        from_id=from_entity_id,
        to_id=to_entity_id,
        relationship_type=relationship_type,
        scope_id=scope_entity_id,
        principal_id=PRINCIPAL_A,
    )


def _seed_proposal(engine: Engine, proposal_id: str, principal_id: str) -> None:
    _execute(
        engine,
        text(
            f"INSERT INTO {SCHEMA}.entity_proposals "  # noqa: S608
            "(proposal_id, principal_id, kind, payload, observation_ids, proposed_at, "
            "proposed_by) VALUES (:proposal_id, :principal_id, 'merge_entities', "
            "'{}'::jsonb, '[]'::jsonb, now(), 'the operator')"
        ),
        proposal_id=proposal_id,
        principal_id=principal_id,
    )


def _insert_merge(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "merge_id": "emrg_aaaa0001aaaa0001",
        "principal_id": PRINCIPAL_A,
        "retained_entity_id": ENTITY_A,
        "merged_entity_id": ENTITY_B,
        "proposal_id": PROPOSAL_A,
        "decided_by": "the operator",
        "reason": "one person, two rows",
        "decided_at": "2026-08-23T12:00:00+00:00",
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    _execute(
        engine,
        text(f"INSERT INTO {SCHEMA}.entity_merge_records ({columns}) VALUES ({binds})"),  # noqa: S608
        **values,
    )


# --- chain position (no database) -------------------------------------------


def test_the_lifecycle_revision_is_in_the_chain_on_the_memory_revision() -> None:
    """One head, and this revision revises the one the memory plane left at head."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert LIFECYCLE_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(LIFECYCLE_REVISION).down_revision == PREVIOUS_REVISION


def test_the_declaration_names_the_tables_this_revision_creates() -> None:
    declared = {table.name for table in METADATA.tables.values() if table.name in NEW_TABLES}
    assert declared == NEW_TABLES


# --- round trip --------------------------------------------------------------


@pytest.mark.database
def test_the_revision_returns_the_database_to_what_the_one_below_it_denotes(
    previous_engine: Engine,
) -> None:
    """Reversible, in every dimension the `knowledge` schema has.

    The three controls are ordered so each failure means something different:
    the snapshot must see something at all, the upgrade must change it, and the
    downgrade must restore it exactly.
    """
    before = _facts(previous_engine)
    assert before, "the snapshot saw nothing, so the equality below would prove nothing"

    command.upgrade(_config(), LIFECYCLE_REVISION)
    at_head = _facts(previous_engine)
    assert at_head != before

    command.downgrade(_config(), PREVIOUS_REVISION)
    assert _facts(previous_engine) == before


@pytest.mark.database
def test_downgrading_leaves_no_trace_of_the_three_ledgers(previous_engine: Engine) -> None:
    """Including the trigger function, which no table's `DROP` would take with it."""
    command.upgrade(_config(), LIFECYCLE_REVISION)
    command.downgrade(_config(), PREVIOUS_REVISION)
    with previous_engine.connect() as connection:
        remaining = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
                {"schema": SCHEMA},
            ).scalars()
        )
        functions = connection.execute(
            text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = :schema AND p.proname = :name"
            ),
            {"schema": SCHEMA, "name": "entity_ledger_rows_stay_as_written"},
        ).scalar_one()
    assert remaining & NEW_TABLES == set()
    assert functions == 0


# --- the backfill aborts rather than guessing --------------------------------


@pytest.mark.database
def test_an_unknown_legacy_assignment_status_aborts_the_migration(
    previous_engine: Engine,
) -> None:
    """The whole argument for this revision, executed rather than described.

    A migration that mapped `'Active'` to `active` would be guessing that the
    capitalisation was cosmetic, and a migration that mapped `'pending'` to
    anything would be inventing a lifecycle. Both values are reported together
    with the row count, so one run tells a reader everything they have to fix.
    """
    _seed_entity(previous_engine, ENTITY_A, PRINCIPAL_A)
    for assignment_id, status in (
        ("asn_aaaa0001aaaa0001", "Active"),
        ("asn_bbbb0002bbbb0002", "pending"),
    ):
        _execute(
            previous_engine,
            text(
                f"INSERT INTO {SCHEMA}.entity_assignments "  # noqa: S608
                "(assignment_id, entity_id, assignment_type, status, principal_id) "
                "VALUES (:assignment_id, :entity_id, 'employment', :status, :principal_id)"
            ),
            assignment_id=assignment_id,
            entity_id=ENTITY_A,
            status=status,
            principal_id=PRINCIPAL_A,
        )
    with pytest.raises(ProgrammingError) as raised:
        command.upgrade(_config(), LIFECYCLE_REVISION)
    message = str(raised.value)
    assert "holds 2 row(s)" in message
    assert "Active, pending" in message
    assert "does not guess" in message


@pytest.mark.database
def test_an_unknown_legacy_relationship_state_aborts_the_migration(
    previous_engine: Engine,
) -> None:
    _seed_entity(previous_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(previous_engine, ENTITY_B, PRINCIPAL_A)
    _execute(
        previous_engine,
        text(
            f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
            "(relationship_id, from_entity_id, to_entity_id, relationship_type, state, "
            "principal_id) VALUES (:relationship_id, :from_id, :to_id, 'works_for', 'LIVE', "
            ":principal_id)"
        ),
        relationship_id="erel_aaaa0001aaaa0001",
        from_id=ENTITY_A,
        to_id=ENTITY_B,
        principal_id=PRINCIPAL_A,
    )
    with pytest.raises(ProgrammingError) as raised:
        command.upgrade(_config(), LIFECYCLE_REVISION)
    assert "LIVE" in str(raised.value)


@pytest.mark.database
def test_two_entities_claiming_one_active_address_abort_the_migration(
    previous_engine: Engine,
) -> None:
    """Reported before the index is built, naming the namespace and the value.

    A duplicate-key failure from `CREATE UNIQUE INDEX` names one pair; this names
    every conflict, which is the difference between one migration run and one per
    duplicate.
    """
    _seed_entity(previous_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(previous_engine, ENTITY_B, PRINCIPAL_A)
    _seed_identifier(previous_engine, "xid_aaaa0001aaaa0001", ENTITY_A, "shared@example.test")
    _seed_identifier(previous_engine, "xid_bbbb0002bbbb0002", ENTITY_B, "shared@example.test")
    with pytest.raises(ProgrammingError) as raised:
        command.upgrade(_config(), LIFECYCLE_REVISION)
    assert "email=shared@example.test" in str(raised.value)


@pytest.mark.database
def test_an_already_archived_entity_aborts_the_migration(previous_engine: Engine) -> None:
    """The fourth abort, which was the one missing.

    No writer sets `archived` today, so this is unreachable from the current
    code -- and the asymmetry was the defect: the three vocabularies above got a
    message naming the offending rows and a remedy, while a restored or
    hand-edited archived row got `an_entity_records_the_status_it_was_archived_from
    is violated by some row`, which names neither the row nor what to do.
    """
    _seed_entity(previous_engine, ENTITY_A, PRINCIPAL_A)
    _execute(
        previous_engine,
        text(
            f"UPDATE {SCHEMA}.entities SET status = 'archived' "  # noqa: S608
            "WHERE entity_id = :entity_id"
        ),
        entity_id=ENTITY_A,
    )
    with pytest.raises(ProgrammingError) as raised:
        command.upgrade(_config(), LIFECYCLE_REVISION)
    message = str(raised.value)
    assert "holds 1 row(s) already archived" in message
    assert "does not guess" in message


@pytest.mark.database
def test_a_legacy_active_assignment_carries_its_state_across(previous_engine: Engine) -> None:
    """The other half: what the migration *does* migrate, and what it stamps.

    A blank status is mapped to `active` -- the column's own default and the only
    lifecycle this plane has ever written -- and the new version column starts at
    one. Without this the abort tests above would be satisfied by a migration
    that refused everything.
    """
    _seed_entity(previous_engine, ENTITY_A, PRINCIPAL_A)
    # Distinct roles, because the semantic unique this revision adds would
    # otherwise refuse the second row as a duplicate of the first -- which is
    # what it is for, and is not what this test is measuring.
    for assignment_id, status, role in (
        ("asn_aaaa0001aaaa0001", "active", "project executive"),
        ("asn_bbbb0002bbbb0002", "", "superintendent"),
    ):
        _execute(
            previous_engine,
            text(
                f"INSERT INTO {SCHEMA}.entity_assignments "  # noqa: S608
                "(assignment_id, entity_id, assignment_type, status, role, principal_id) "
                "VALUES (:assignment_id, :entity_id, 'employment', :status, :role, "
                ":principal_id)"
            ),
            assignment_id=assignment_id,
            entity_id=ENTITY_A,
            status=status,
            role=role,
            principal_id=PRINCIPAL_A,
        )
    command.upgrade(_config(), LIFECYCLE_REVISION)
    with previous_engine.connect() as connection:
        held = sorted(
            tuple(row)
            for row in connection.execute(
                text(f"SELECT assignment_id, state, version FROM {SCHEMA}.entity_assignments")  # noqa: S608
            )
        )
    assert held == [
        ("asn_aaaa0001aaaa0001", "active", 1),
        ("asn_bbbb0002bbbb0002", "active", 1),
    ]


# --- declaration parity ------------------------------------------------------


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(NEW_TABLES | WIDENED_TABLES | REFERENCED_TABLES))
def test_every_declared_constraint_name_exists_on_the_server(
    migrated_engine: Engine, table_name: str
) -> None:
    """The cost of hand-written DDL, paid rather than described."""
    table = METADATA.tables[f"{SCHEMA}.{table_name}"]
    declared = {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None and not str(constraint.name).startswith("_")
    }
    with migrated_engine.connect() as connection:
        live = set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND t.relname = :table"
                ),
                {"schema": SCHEMA, "table": table_name},
            ).scalars()
        )
    assert declared <= live, f"the declaration names {sorted(declared - live)}, not the server"


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(NEW_TABLES | WIDENED_TABLES | REFERENCED_TABLES))
def test_every_declared_column_and_index_exists_on_the_server(
    migrated_engine: Engine, table_name: str
) -> None:
    table = METADATA.tables[f"{SCHEMA}.{table_name}"]
    with migrated_engine.connect() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table_name},
            ).scalars()
        )
        indexes = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = :s AND tablename = :t"),
                {"s": SCHEMA, "t": table_name},
            ).scalars()
        )
    assert {column.name for column in table.columns} == columns
    assert {index.name for index in table.indexes} <= indexes


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(NEW_TABLES))
def test_every_new_table_carries_a_principal_partition(
    migrated_engine: Engine, table_name: str
) -> None:
    table = METADATA.tables[f"{SCHEMA}.{table_name}"]
    assert not table.c.principal_id.nullable


# --- the new rules actually refuse -------------------------------------------


@pytest.mark.database
def test_an_archived_entity_must_record_the_status_it_was_archived_from(
    migrated_engine: Engine,
) -> None:
    """Un-archiving has to restore a status rather than assume `active`."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with (
        pytest.raises(IntegrityError, match="an_entity_records_the_status_it_was_archived_from"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities SET status = 'archived' "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": ENTITY_A},
        )


@pytest.mark.database
def test_an_entity_cannot_be_archived_from_a_status_it_could_not_stand_in(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with (
        pytest.raises(IntegrityError, match="an_archived_from_status_is_known"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities "  # noqa: S608
                "SET status = 'archived', archived_from_status = 'merged_redirect' "
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": ENTITY_A},
        )


@pytest.mark.database
def test_one_active_address_binds_one_entity_per_principal(migrated_engine: Engine) -> None:
    """The canonical binding, which is what makes an identifier an identity."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_identifier(migrated_engine, "xid_aaaa0001aaaa0001", ENTITY_A, "shared@example.test")
    with pytest.raises(IntegrityError, match="an_active_external_identifier_binding_is_unique"):
        _seed_identifier(migrated_engine, "xid_bbbb0002bbbb0002", ENTITY_B, "shared@example.test")


@pytest.mark.database
def test_a_retired_binding_leaves_the_address_free_and_stays_queryable(
    migrated_engine: Engine,
) -> None:
    """Partial, not total: the historical row is the point of the vocabulary."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_identifier(migrated_engine, "xid_aaaa0001aaaa0001", ENTITY_A, "shared@example.test")
    _execute(
        migrated_engine,
        text(
            f"UPDATE {SCHEMA}.entity_external_identifiers "  # noqa: S608
            "SET state = 'retired', retired_at = now() WHERE identifier_id = :identifier_id"
        ),
        identifier_id="xid_aaaa0001aaaa0001",
    )
    _seed_identifier(migrated_engine, "xid_bbbb0002bbbb0002", ENTITY_B, "shared@example.test")
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_external_identifiers "  # noqa: S608
                "WHERE normalized_value = 'shared@example.test'"
            )
        ).scalar_one()
    assert held == 2


@pytest.mark.database
def test_an_address_retired_from_an_entity_may_be_rebound_to_the_same_entity(
    migrated_engine: Engine,
) -> None:
    """The case the *total* unique refused, and the reason it had to come off.

    `an_external_identifier_is_recorded_once_per_namespace` was UNIQUE over
    `(entity_id, namespace, normalized_value)` whatever the state, so an address
    retired from an entity could never be recorded as current on that entity
    again -- the plane would have had to delete the retired row, which is the
    row that resolves the messages sent while the address was out of service.
    The sibling above re-binds on a *different* entity and so never reached this.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_identifier(migrated_engine, "xid_aaaa0001aaaa0001", ENTITY_A, "alice@example.test")
    _retire(migrated_engine, "entity_external_identifiers", "identifier_id", "xid_aaaa0001aaaa0001")
    _seed_identifier(migrated_engine, "xid_bbbb0002bbbb0002", ENTITY_A, "alice@example.test")
    with migrated_engine.connect() as connection:
        held = sorted(
            tuple(row)
            for row in connection.execute(
                text(
                    f"SELECT identifier_id, state FROM {SCHEMA}.entity_external_identifiers "  # noqa: S608
                    "WHERE entity_id = :entity_id AND normalized_value = 'alice@example.test'"
                ),
                {"entity_id": ENTITY_A},
            )
        )
    assert held == [
        ("xid_aaaa0001aaaa0001", "retired"),
        ("xid_bbbb0002bbbb0002", "active"),
    ]


@pytest.mark.database
def test_a_name_retired_from_an_entity_may_be_recorded_on_it_again(
    migrated_engine: Engine,
) -> None:
    """The alias half of the same defect, and the same total unique."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali")
    _retire(migrated_engine, "entity_aliases", "alias_id", "eals_aaaa0001aaaa0001")
    _seed_alias(migrated_engine, "eals_bbbb0002bbbb0002", ENTITY_A, "ali")
    with migrated_engine.connect() as connection:
        held = sorted(
            tuple(row)
            for row in connection.execute(
                text(
                    f"SELECT alias_id, state FROM {SCHEMA}.entity_aliases "  # noqa: S608
                    "WHERE entity_id = :entity_id AND normalized_value = 'ali'"
                ),
                {"entity_id": ENTITY_A},
            )
        )
    assert held == [
        ("eals_aaaa0001aaaa0001", "retired"),
        ("eals_bbbb0002bbbb0002", "active"),
    ]


@pytest.mark.database
def test_one_entity_may_not_hold_one_active_name_form_twice(migrated_engine: Engine) -> None:
    """`an_active_alias_is_unique_per_entity_and_type` is unique, not merely named.

    Asserted behaviourally because the declaration parity tests above compare
    index *names*: a non-unique index called this would satisfy every one of
    them, and this plane's uniques are the whole rule.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali")
    with pytest.raises(IntegrityError, match="an_active_alias_is_unique_per_entity_and_type"):
        _seed_alias(migrated_engine, "eals_bbbb0002bbbb0002", ENTITY_A, "ali")


@pytest.mark.database
def test_two_entities_may_both_be_actively_called_the_same_thing(
    migrated_engine: Engine,
) -> None:
    """The product rule the alias unique must not break: two real people share a name.

    The other half of the test above. A unique that was per Principal rather
    than per entity would refuse this, and refusing it would force exactly the
    false join this plane exists to avoid.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali")
    _seed_alias(migrated_engine, "eals_bbbb0002bbbb0002", ENTITY_B, "ali")
    _seed_alias(migrated_engine, "eals_cccc0003cccc0003", ENTITY_A, "ali", alias_type="initials")
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_aliases "  # noqa: S608
                "WHERE normalized_value = 'ali'"
            )
        ).scalar_one()
    assert held == 3


@pytest.mark.database
def test_the_same_active_relationship_cannot_be_recorded_twice(migrated_engine: Engine) -> None:
    """`an_active_entity_relationship_is_recorded_once` is unique, not merely named.

    Unscoped, which is the null-safe half: `scope_entity_id` is nullable, and an
    index over the bare column would let two unscoped duplicates through because
    `NULL` is distinct from `NULL`. The index coalesces it, so the two rows below
    collide.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_relationship(migrated_engine, "erel_aaaa0001aaaa0001", ENTITY_A, ENTITY_B)
    with pytest.raises(IntegrityError, match="an_active_entity_relationship_is_recorded_once"):
        _seed_relationship(migrated_engine, "erel_bbbb0002bbbb0002", ENTITY_A, ENTITY_B)


@pytest.mark.database
def test_a_scoped_relationship_is_a_different_edge_from_an_unscoped_one(
    migrated_engine: Engine,
) -> None:
    """And the opposite direction is a third: the key is directed and scoped."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_C, PRINCIPAL_A)
    _seed_relationship(migrated_engine, "erel_aaaa0001aaaa0001", ENTITY_A, ENTITY_B)
    _seed_relationship(
        migrated_engine,
        "erel_bbbb0002bbbb0002",
        ENTITY_A,
        ENTITY_B,
        scope_entity_id=ENTITY_C,
    )
    _seed_relationship(migrated_engine, "erel_cccc0003cccc0003", ENTITY_B, ENTITY_A)
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_relationships")  # noqa: S608
        ).scalar_one()
    assert held == 3


@pytest.mark.database
def test_the_two_legacy_namespaces_are_admitted(migrated_engine: Engine) -> None:
    """The WP-9 substrate's identities are recorded as identities, not as columns."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_identifier(
        migrated_engine,
        "xid_aaaa0001aaaa0001",
        ENTITY_A,
        "per_aaaa0001aaaa0001",
        namespace="legacy_relationship_person_id",
    )
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(
                f"SELECT namespace FROM {SCHEMA}.entity_external_identifiers "  # noqa: S608
                "WHERE identifier_id = 'xid_aaaa0001aaaa0001'"
            )
        ).scalar_one()
    assert held == "legacy_relationship_person_id"


@pytest.mark.database
def test_the_same_active_assignment_cannot_be_recorded_twice(migrated_engine: Engine) -> None:
    """Folded and trimmed, so two spellings of one role are one assignment."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    statement = text(
        f"INSERT INTO {SCHEMA}.entity_assignments "  # noqa: S608
        "(assignment_id, entity_id, assignment_type, role, principal_id) "
        "VALUES (:assignment_id, :entity_id, 'employment', :role, :principal_id)"
    )
    _execute(
        migrated_engine,
        statement,
        assignment_id="asn_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        role="Project Manager",
        principal_id=PRINCIPAL_A,
    )
    with pytest.raises(IntegrityError, match="an_active_assignment_is_recorded_once"):
        _execute(
            migrated_engine,
            statement,
            assignment_id="asn_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            role=" project manager ",
            principal_id=PRINCIPAL_A,
        )


@pytest.mark.database
def test_a_merge_record_binds_two_entities_and_a_proposal_of_its_own_principal(
    migrated_engine: Engine,
) -> None:
    """The legal control, so the three refusals below cannot pass by refusing everything."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_proposal(migrated_engine, PROPOSAL_A, PRINCIPAL_A)
    _insert_merge(migrated_engine)
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_merge_records")  # noqa: S608
        ).scalar_one()
    assert held == 1


@pytest.mark.database
@pytest.mark.parametrize(
    ("column", "constraint"),
    [
        ("retained_entity_id", "a_merge_retains_an_entity_of_its_principal"),
        ("merged_entity_id", "a_merge_merges_away_an_entity_of_its_principal"),
    ],
)
def test_a_merge_record_may_not_name_another_principals_entity(
    migrated_engine: Engine, column: str, constraint: str
) -> None:
    """The defect the single-column reference left open, on the ledger that redirects.

    `entity_merge_records` carries a NOT NULL `principal_id` and named both of
    its entities by `entity_id` alone, so the server accepted a merge record
    owned by one Principal that merged away another Principal's entity -- and a
    merge is what writes a redirect. Only the repository's own predicate stood
    between that and a read crossing the partition.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_C, PRINCIPAL_B)
    _seed_proposal(migrated_engine, PROPOSAL_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match=constraint):
        _insert_merge(migrated_engine, **{column: ENTITY_C})


@pytest.mark.database
def test_a_merge_record_may_not_cite_another_principals_proposal(
    migrated_engine: Engine,
) -> None:
    """A merge says which proposal authorised it, and that has to be one it could read."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_proposal(migrated_engine, PROPOSAL_B, PRINCIPAL_B)
    with pytest.raises(IntegrityError, match="a_merge_cites_a_proposal_of_its_principal"):
        _insert_merge(migrated_engine, proposal_id=PROPOSAL_B)


@pytest.mark.database
def test_an_observation_may_not_refer_to_another_principals_entity(
    migrated_engine: Engine,
) -> None:
    """The composite reference, which is the partition the plain key could not hold."""
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_B)
    _seed_observation(migrated_engine)
    with (
        pytest.raises(IntegrityError, match="an_observation_refers_to_an_entity_of_its_principal"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_observations SET entity_id = :entity_id "  # noqa: S608
                "WHERE observation_id = :observation_id"
            ),
            {"entity_id": ENTITY_B, "observation_id": OBSERVATION_A},
        )


@pytest.mark.database
def test_a_current_observation_may_not_carry_a_reason_for_not_being_current(
    migrated_engine: Engine,
) -> None:
    _seed_observation(migrated_engine)
    with (
        pytest.raises(
            IntegrityError,
            match="an_observation_state_reason_explains_a_departure_from_current",
        ),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_observations "  # noqa: S608
                "SET state_reason = 'the source moved on' WHERE observation_id = :observation_id"
            ),
            {"observation_id": OBSERVATION_A},
        )


def _mutation_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event_id": "emut_aaaa0001aaaa0001",
        "principal_id": PRINCIPAL_A,
        "capability": "entities.record_alias",
        "record_family": "alias",
        "record_id": "eals_aaaa0001aaaa0001",
        "new_version": 1,
        "authority": "user_confirmed_assertion",
        "idempotency_key": "key-0001",
        "request_digest": "0" * 64,
        "correlation_id": "corr_aaaa0001aaaa0001",
        "audit_id": "audit_aaaa0001aaaa0001",
        "actor_class": "user",
    }
    values.update(overrides)
    return values


def _insert_mutation(engine: Engine, **overrides: object) -> None:
    values = _mutation_values(**overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    _execute(
        engine,
        text(f"INSERT INTO {SCHEMA}.entity_mutation_events ({columns}) VALUES ({binds})"),  # noqa: S608
        **values,
    )


@pytest.mark.database
def test_one_key_admits_one_mutation_per_capability(migrated_engine: Engine) -> None:
    _insert_mutation(migrated_engine)
    with pytest.raises(IntegrityError, match="one_entity_mutation_per_key_and_capability"):
        _insert_mutation(migrated_engine, event_id="emut_bbbb0002bbbb0002")


@pytest.mark.database
def test_the_same_key_under_a_different_capability_is_a_different_request(
    migrated_engine: Engine,
) -> None:
    """Which is why `capability` is part of the key rather than assumed."""
    _insert_mutation(migrated_engine)
    _insert_mutation(
        migrated_engine,
        event_id="emut_bbbb0002bbbb0002",
        capability="entities.record_assignment",
        record_family="assignment",
        record_id="asn_aaaa0001aaaa0001",
    )


@pytest.mark.database
def test_a_mutation_request_digest_must_be_a_digest(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="a_mutation_request_digest_is_a_sha256_digest"):
        _insert_mutation(migrated_engine, request_digest="/etc/passwd")


@pytest.mark.database
@pytest.mark.parametrize("operation", ["UPDATE", "DELETE"])
def test_a_mutation_event_cannot_be_rewritten(migrated_engine: Engine, operation: str) -> None:
    """No CHECK can express "no UPDATE", so the trigger is the mechanism."""
    _insert_mutation(migrated_engine)
    statement = (
        f"UPDATE {SCHEMA}.entity_mutation_events SET reason = 'rewritten'"  # noqa: S608
        if operation == "UPDATE"
        else f"DELETE FROM {SCHEMA}.entity_mutation_events"  # noqa: S608
    )
    with (
        pytest.raises(IntegrityError, match="is append only"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(text(statement))


def _decision_values(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "decision_id": "erdc_aaaa0001aaaa0001",
        "principal_id": PRINCIPAL_A,
        "observation_id": OBSERVATION_A,
        "sequence": 1,
        "expected_resolution_version": 0,
        "disposition": "defer",
        "decided_by": "the operator",
        "actor_class": "user",
        "correlation_id": "corr_aaaa0001aaaa0001",
        "audit_id": "audit_aaaa0001aaaa0001",
    }
    values.update(overrides)
    return values


def _insert_decision(engine: Engine, **overrides: object) -> None:
    values = _decision_values(**overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    _execute(
        engine,
        text(f"INSERT INTO {SCHEMA}.entity_resolution_decisions ({columns}) VALUES ({binds})"),  # noqa: S608
        **values,
    )


@pytest.mark.database
def test_a_decision_that_binds_an_entity_must_name_one(migrated_engine: Engine) -> None:
    """And a refusal must not: the subject would contradict the outcome."""
    _seed_observation(migrated_engine)
    with pytest.raises(
        IntegrityError, match="a_resolution_names_an_entity_exactly_when_it_binds_one"
    ):
        _insert_decision(migrated_engine, disposition="link_existing")


@pytest.mark.database
def test_a_rejecting_decision_may_not_name_an_entity(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_observation(migrated_engine)
    with pytest.raises(
        IntegrityError, match="a_resolution_names_an_entity_exactly_when_it_binds_one"
    ):
        _insert_decision(migrated_engine, disposition="reject", entity_id=ENTITY_A)


@pytest.mark.database
def test_one_observation_admits_one_decision_per_sequence(migrated_engine: Engine) -> None:
    _seed_observation(migrated_engine)
    _insert_decision(migrated_engine)
    with pytest.raises(
        IntegrityError, match="one_resolution_decision_per_observation_and_sequence"
    ):
        _insert_decision(migrated_engine, decision_id="erdc_bbbb0002bbbb0002")


@pytest.mark.database
def test_a_resolution_decision_cannot_be_rewritten(migrated_engine: Engine) -> None:
    _seed_observation(migrated_engine)
    _insert_decision(migrated_engine)
    with (
        pytest.raises(IntegrityError, match="is append only"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(f"UPDATE {SCHEMA}.entity_resolution_decisions SET sequence = 2")  # noqa: S608
        )


@pytest.mark.database
@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({}, "entity_evidence_names_exactly_one_fact"),
        (
            {"entity_id": ENTITY_A, "alias_id": "eals_aaaa0001aaaa0001"},
            "entity_evidence_names_exactly_one_fact",
        ),
        (
            {"entity_id": ENTITY_A, "entity_observation_id": None},
            "entity_evidence_names_exactly_one_record",
        ),
        (
            {
                "entity_id": ENTITY_A,
                "capture_span_id": "span_aaaa0001aaaa0001",
            },
            "entity_evidence_names_exactly_one_record",
        ),
    ],
)
def test_one_evidence_link_names_one_fact_and_one_record(
    migrated_engine: Engine, overrides: dict[str, object], constraint: str
) -> None:
    """Two facts is an ambiguous subject; two records is an ambiguous basis."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_observation(migrated_engine)
    values: dict[str, object] = {
        "link_id": "efev_aaaa0001aaaa0001",
        "principal_id": PRINCIPAL_A,
        "entity_observation_id": OBSERVATION_A,
        "role": "direct",
        "authority": "review_accepted",
    }
    values.update(overrides)
    named = {name: value for name, value in values.items() if value is not None}
    columns = ", ".join(named)
    binds = ", ".join(f":{name}" for name in named)
    with pytest.raises(IntegrityError, match=constraint):
        _execute(
            migrated_engine,
            text(f"INSERT INTO {SCHEMA}.entity_fact_evidence_links ({columns}) VALUES ({binds})"),  # noqa: S608
            **named,
        )


@pytest.mark.database
def test_an_evidence_link_may_not_name_another_principals_fact(
    migrated_engine: Engine,
) -> None:
    """The structural half. The evidence half is the application's, and is stated."""
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_B)
    _seed_observation(migrated_engine)
    with pytest.raises(IntegrityError, match="entity_evidence_names_an_entity_of_its_principal"):
        _execute(
            migrated_engine,
            text(
                f"INSERT INTO {SCHEMA}.entity_fact_evidence_links "  # noqa: S608
                "(link_id, principal_id, entity_id, entity_observation_id, role, authority) "
                "VALUES (:link_id, :principal_id, :entity_id, :observation_id, "
                "'direct', 'review_accepted')"
            ),
            link_id="efev_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            entity_id=ENTITY_B,
            observation_id=OBSERVATION_A,
        )
