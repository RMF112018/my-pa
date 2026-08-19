"""Revision `9def3c2e63bb` against a real PostgreSQL server.

`tests/unit/test_entity_domain.py` proves the dataclasses refuse a bad value.
This proves the *server* refuses it, which is the claim that matters: the
database is the canonical store (`AGENTS.md` section 4), and a plane whose only
guard is the one the application remembers to call is a plane a migration, a
fixture, a backfill, or a future writer can put a bad row into.

Three groups:

* the revision is on a single unbranched chain, and runs empty-to-head and
  head-to-empty leaving no residue (`AGENTS.md` section 6);
* every constraint name the declaration in `tables.py` gives appears on the
  migrated server -- the cost of writing the DDL out by hand rather than
  importing `METADATA` (`D-48`, `D-69`), paid rather than described;
* each CHECK actually rejects the row it names.
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

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

ENTITY_REVISION: Final = "9def3c2e63bb"
PREVIOUS_REVISION: Final = "f4c1a8e6b205"

#: WP-RI-03's alias table, on the revision after the four.
ALIAS_REVISION: Final = "b7f4d1a92c36"

ENTITY_TABLES: Final = frozenset(
    {
        "entities",
        "entity_external_identifiers",
        "entity_assignments",
        "entity_relationships",
    }
)

NEW_TABLES: Final = ENTITY_TABLES | {"entity_aliases"}

#: WP-RI-06's governance tables, on `d2b8f5c04e71`. Kept separate from
#: `NEW_TABLES` because the two arrive on different revisions and a downgrade to
#: `PREVIOUS_REVISION` passes through both, so this names what that downgrade
#: additionally removes.
#:
#: The parity and CHECK groups below *do* reach these three: they parameterize
#: on `PLANE_TABLES`, which is this set unioned with `NEW_TABLES`. An earlier
#: version of this comment said they did not and pointed at
#: `tests/schema/test_entity_governance_migration.py` for them, which has never
#: existed -- the governance revision has no suite of its own, which is precisely
#: why the groups here were widened to cover it.
GOVERNANCE_TABLES: Final = frozenset(
    {"entity_observations", "entity_proposals", "entity_merge_records"}
)

#: Everything the entity plane adds between `PREVIOUS_REVISION` and head.
PLANE_TABLES: Final = NEW_TABLES | GOVERNANCE_TABLES

#: A name distinct from every other database-tier fixture's disposable
#: database, so this suite can run alongside them without one dropping the
#: database another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY_A: Final = "ent_aaaa0001aaaa0001"
ENTITY_B: Final = "ent_bbbb0002bbbb0002"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards.

    Copied rather than shared, as every other database-tier module copies it:
    the fixture names a database of its own so two suites cannot drop each
    other's, and the canonical `my_pa` database is never migrated or opened.
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


def _tables(engine: Engine, schema: str = SCHEMA) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = :schema"),
                {"schema": schema},
            )
        }


def _constraint_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND t.relname = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def _seed_entity(engine: Engine, entity_id: str, principal_id: str, status: str = "active") -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, 'person', :name, :name, :status)"
            ),
            {
                "entity_id": entity_id,
                "principal_id": principal_id,
                "name": "synthetic person",
                "status": status,
            },
        )


# --- chain position (no database) -------------------------------------------


def test_the_alias_revision_is_in_the_chain_on_the_entity_revision() -> None:
    """The alias table follows the four it references, on one unbranched chain."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert ALIAS_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(ALIAS_REVISION).down_revision == ENTITY_REVISION


def test_the_entity_revision_is_in_the_chain_on_the_goodnotes_revision() -> None:
    """One head, and this revision revises the one the campaign left at head.

    Deliberately not "is the head", for the reason
    `test_the_extraction_revision_is_in_the_chain_on_the_knowledge_revision`
    gives: that property is true only until the next revision is written, and
    asserting it makes every later work package edit this file.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert ENTITY_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(ENTITY_REVISION).down_revision == PREVIOUS_REVISION


def test_the_revision_declares_the_tables_it_creates() -> None:
    """The declaration and the migration name the same tables.

    **Corrected 2026-08-19: this was `..._the_four_tables_...` and compared five.**
    `NEW_TABLES` is `ENTITY_TABLES | {"entity_aliases"}` and has held five since
    `b7f4d1a92c36` added the alias table; the name and the docstring kept saying
    four, so the one place a reader could learn the count from was wrong while
    the assertion beside it was right. Neither number is written down now — the
    set is named and `len()` is nobody's business but `NEW_TABLES`'s, which is
    the shape that cannot go stale when the next revision widens it.
    """
    declared = {table.name for table in METADATA.tables.values() if table.name in NEW_TABLES}
    assert declared == NEW_TABLES


# --- migration round trip ----------------------------------------------------


@pytest.mark.database
def test_the_entity_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and nothing of this revision survives `downgrade base`."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _tables(engine) >= NEW_TABLES

        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_to_before_this_revision_drops_only_the_entity_plane(
    migrated_engine: Engine,
) -> None:
    """Additive: the WP-9 substrate is untouched by this revision's downgrade.

    The downgrade target is the revision *below* this one, so it passes through
    every entity-plane revision above it as well -- the aliases table and the
    three governance tables. The equality is stated over all of them rather than
    over this revision's four alone, because a set that named only the four
    would fail the moment the plane grew, which is bookkeeping rather than a
    finding. What it still catches is the thing worth catching: a table outside
    the plane removed by one of those downgrades, or a plane table left behind.
    """
    before = _tables(migrated_engine)
    assert {"relationship_people", "relationship_organizations"} <= before

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    assert before - after == PLANE_TABLES
    assert {"relationship_people", "relationship_organizations"} <= after


# --- declaration parity ------------------------------------------------------
#
# Parameterized over `PLANE_TABLES` rather than `NEW_TABLES`: these four claims
# are about hand-written DDL matching a declaration, and that cost is paid the
# same way by every table on the plane. The governance revision added three
# without a suite of its own, which meant three tables whose constraint names,
# columns and partition column nothing checked against a server.


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(PLANE_TABLES))
def test_every_declared_constraint_name_exists_on_the_server(
    migrated_engine: Engine, table_name: str
) -> None:
    """The whole cost of hand-written DDL: the names have to actually match.

    An inline column `CHECK` is auto-named by PostgreSQL, so a migration that
    wrote one would create a constraint the declaration does not name -- and
    every later revision that wanted to drop or restate it by name would fail
    in the field while passing here.
    """
    table = METADATA.tables[f"{SCHEMA}.{table_name}"]
    declared = {
        constraint.name
        for constraint in table.constraints
        if constraint.name is not None and not str(constraint.name).startswith("_")
    }
    live = _constraint_names(migrated_engine, table_name)
    assert declared <= live, f"the declaration names {sorted(declared - live)}, the server does not"


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(PLANE_TABLES))
def test_every_declared_column_exists_on_the_server(
    migrated_engine: Engine, table_name: str
) -> None:
    table = METADATA.tables[f"{SCHEMA}.{table_name}"]
    declared = {column.name for column in table.columns}
    assert declared == _columns(migrated_engine, table_name)


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(PLANE_TABLES))
def test_every_entity_table_carries_a_principal_partition(
    migrated_engine: Engine, table_name: str
) -> None:
    """No row on this plane is unowned; the partition is a NOT NULL column."""
    assert "principal_id" in _columns(migrated_engine, table_name)


@pytest.mark.database
def test_no_entity_table_carries_a_confidence_or_score_column(
    migrated_engine: Engine,
) -> None:
    """The scoring prohibition, asserted against the server rather than the source.

    `tests/architecture/test_relationship_scoring_surface_is_denied` reads the
    declaration. This reads what was actually created, so a column added by a
    hand-written migration and never declared is caught too.
    """
    denied = {"confidence", "score", "rating", "rank", "trust", "sentiment"}
    for table_name in PLANE_TABLES:
        assert not _columns(migrated_engine, table_name) & denied


# --- the CHECKs actually refuse ----------------------------------------------


@pytest.mark.database
def test_a_merged_entity_with_no_successor_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="an_entity_redirects_exactly_when_it_is_merged_away"):
        _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, status="merged_redirect")


@pytest.mark.database
def test_a_live_entity_naming_a_successor_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    with (
        pytest.raises(IntegrityError, match="an_entity_redirects_exactly_when_it_is_merged_away"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities SET superseded_by_entity_id = :target "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"target": ENTITY_B, "entity_id": ENTITY_A},
        )


@pytest.mark.database
def test_two_entities_may_be_merged_into_one_survivor(migrated_engine: Engine) -> None:
    """The defect the prior `UNIQUE` on `superseded_by_entity_id` would have caused.

    Merging A into C and B into C is the ordinary shape of a duplicate cleanup;
    a unique index on the successor column forbids it outright.
    """
    survivor = "ent_cccc0003cccc0003"
    _seed_entity(migrated_engine, survivor, PRINCIPAL_A)
    for merged in (ENTITY_A, ENTITY_B):
        _seed_entity(migrated_engine, merged, PRINCIPAL_A)
        with migrated_engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.entities "  # noqa: S608
                    "SET status = 'merged_redirect', superseded_by_entity_id = :survivor "
                    "WHERE entity_id = :entity_id"
                ),
                {"survivor": survivor, "entity_id": merged},
            )
    with migrated_engine.connect() as connection:
        redirected = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE superseded_by_entity_id = :survivor"
            ),
            {"survivor": survivor},
        ).scalar_one()
    assert redirected == 2


@pytest.mark.database
def test_an_entity_cannot_supersede_itself(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with (
        pytest.raises(IntegrityError, match="an_entity_does_not_supersede_itself"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entities "  # noqa: S608
                "SET status = 'merged_redirect', superseded_by_entity_id = entity_id "
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": ENTITY_A},
        )


@pytest.mark.database
@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("entity_type", "'consultant'", "an_entity_type_is_known"),
        ("status", "'pending'", "an_entity_status_is_known"),
        ("canonical_name", "'   '", "an_entity_canonical_name_is_not_blank"),
        ("display_name", "'   '", "an_entity_display_name_is_not_blank"),
    ],
)
def test_an_entity_column_refuses_a_value_outside_its_closed_set(
    migrated_engine: Engine, column: str, value: str, constraint: str
) -> None:
    columns = {
        "entity_id": f"'{ENTITY_A}'",
        "principal_id": f"'{PRINCIPAL_A}'",
        "entity_type": "'person'",
        "canonical_name": "'synthetic person'",
        "display_name": "'Synthetic Person'",
        "status": "'active'",
    }
    columns[column] = value
    with (
        pytest.raises(IntegrityError, match=constraint),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities ({', '.join(columns)}) "  # noqa: S608
                f"VALUES ({', '.join(columns.values())})"
            )
        )


@pytest.mark.database
def test_an_entity_identifier_must_carry_its_own_prefix(migrated_engine: Engine) -> None:
    """A `per_` identifier belongs to the WP-9 plane; the server refuses it by shape."""
    with pytest.raises(IntegrityError, match="entity_id_is_an_opaque_identifier"):
        _seed_entity(migrated_engine, "per_aaaa0001aaaa0001", PRINCIPAL_A)


@pytest.mark.database
def test_the_same_external_identity_cannot_be_recorded_twice(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    statement = text(
        f"INSERT INTO {SCHEMA}.entity_external_identifiers "  # noqa: S608
        "(identifier_id, entity_id, namespace, normalized_value, display_value, principal_id) "
        "VALUES (:identifier_id, :entity_id, 'email', :value, :value, :principal_id)"
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            statement,
            {
                "identifier_id": "xid_aaaa0001aaaa0001",
                "entity_id": ENTITY_A,
                "value": "person@example.test",
                "principal_id": PRINCIPAL_A,
            },
        )
    with (
        pytest.raises(
            IntegrityError, match="an_external_identifier_is_recorded_once_per_namespace"
        ),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            statement,
            {
                "identifier_id": "xid_bbbb0002bbbb0002",
                "entity_id": ENTITY_A,
                "value": "person@example.test",
                "principal_id": PRINCIPAL_A,
            },
        )


@pytest.mark.database
def test_an_external_identifier_cannot_end_before_it_begins(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with (
        pytest.raises(IntegrityError, match="an_external_identifier_ends_after_it_starts"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_external_identifiers "  # noqa: S608
                "(identifier_id, entity_id, namespace, normalized_value, display_value, "
                "effective_from, effective_to, principal_id) VALUES "
                "(:identifier_id, :entity_id, 'email', :value, :value, "
                "'2026-08-18T00:00:00Z', '2026-08-17T00:00:00Z', :principal_id)"
            ),
            {
                "identifier_id": "xid_aaaa0001aaaa0001",
                "entity_id": ENTITY_A,
                "value": "person@example.test",
                "principal_id": PRINCIPAL_A,
            },
        )


@pytest.mark.database
def test_a_relationship_cannot_connect_an_entity_to_itself(migrated_engine: Engine) -> None:
    """A self-edge is a false join the server refuses, not only the domain."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with (
        pytest.raises(
            IntegrityError, match="an_entity_relationship_connects_two_distinct_entities"
        ),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, to_entity_id, relationship_type, "
                "principal_id) VALUES "
                "(:relationship_id, :entity_id, :entity_id, 'works_for', :principal_id)"
            ),
            {
                "relationship_id": "erel_aaaa0001aaaa0001",
                "entity_id": ENTITY_A,
                "principal_id": PRINCIPAL_A,
            },
        )


@pytest.mark.database
def test_an_assignment_naming_no_entity_is_refused(migrated_engine: Engine) -> None:
    """The foreign key holds even though it cannot hold the partition."""
    with (
        pytest.raises((IntegrityError, ProgrammingError)),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_assignments "  # noqa: S608
                "(assignment_id, entity_id, assignment_type, principal_id) VALUES "
                "(:assignment_id, :entity_id, 'employment', :principal_id)"
            ),
            {
                "assignment_id": "asn_aaaa0001aaaa0001",
                "entity_id": "ent_dddd0004dddd0004",
                "principal_id": PRINCIPAL_A,
            },
        )


@pytest.mark.database
def test_the_foreign_key_alone_admits_a_cross_principal_reference(
    migrated_engine: Engine,
) -> None:
    """Why `SqlEntityRepository` checks every entity reference itself.

    The foreign key spans every Principal, so the *server* accepts an assignment
    whose subject belongs to someone else. Asserted rather than assumed, because
    the repository's guard is only worth its cost if this is true.
    """
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_B)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_assignments "  # noqa: S608
                "(assignment_id, entity_id, assignment_type, principal_id) VALUES "
                "(:assignment_id, :entity_id, 'employment', :principal_id)"
            ),
            {
                "assignment_id": "asn_aaaa0001aaaa0001",
                "entity_id": ENTITY_B,
                "principal_id": PRINCIPAL_A,
            },
        )
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            text(
                f"SELECT principal_id FROM {SCHEMA}.entity_assignments "  # noqa: S608
                "WHERE assignment_id = 'asn_aaaa0001aaaa0001'"
            )
        ).scalar_one()
    assert stored == PRINCIPAL_A


# --- the alias table -------------------------------------------------------


def _seed_alias(
    engine: Engine,
    alias_id: str,
    entity_id: str,
    value: str,
    principal_id: str = PRINCIPAL_A,
    alias_type: str = "nickname",
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_aliases "  # noqa: S608
                "(alias_id, entity_id, alias_type, normalized_value, display_value, principal_id) "
                "VALUES (:alias_id, :entity_id, :alias_type, :value, :value, :principal_id)"
            ),
            {
                "alias_id": alias_id,
                "entity_id": entity_id,
                "alias_type": alias_type,
                "value": value,
                "principal_id": principal_id,
            },
        )


@pytest.mark.database
def test_two_entities_may_carry_the_same_alias(migrated_engine: Engine) -> None:
    """The safety argument of this table, asserted against the server.

    Two real people share a name. A unique index on `normalized_value` would
    make that a constraint violation, and the only way to satisfy it would be to
    merge one into the other -- the false join the whole plane exists to avoid.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "alice synthetic")
    _seed_alias(migrated_engine, "eals_bbbb0002bbbb0002", ENTITY_B, "alice synthetic")
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_aliases "  # noqa: S608
                "WHERE normalized_value = 'alice synthetic'"
            )
        ).scalar_one()
    assert held == 2


@pytest.mark.database
def test_one_entity_cannot_record_the_same_alias_twice(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali")
    with pytest.raises(IntegrityError, match="an_alias_is_recorded_once_per_entity_and_type"):
        _seed_alias(migrated_engine, "eals_bbbb0002bbbb0002", ENTITY_A, "ali")


@pytest.mark.database
def test_the_same_alias_under_a_different_type_is_a_second_record(
    migrated_engine: Engine,
) -> None:
    """The key includes the type, so a full name and a nickname may coincide."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali", alias_type="nickname")
    _seed_alias(migrated_engine, "eals_bbbb0002bbbb0002", ENTITY_A, "ali", alias_type="full_name")
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_aliases")  # noqa: S608
        ).scalar_one()
    assert held == 2


@pytest.mark.database
def test_an_alias_type_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_alias_type_is_known"):
        _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali", alias_type="handle")


@pytest.mark.database
def test_an_alias_identifier_must_carry_its_own_prefix(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="alias_id_is_an_opaque_identifier"):
        _seed_alias(migrated_engine, "xid_aaaa0001aaaa0001", ENTITY_A, "ali")


@pytest.mark.database
def test_dropping_an_entity_drops_its_aliases(migrated_engine: Engine) -> None:
    """`ON DELETE CASCADE`: an alias of a deleted entity names nothing."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_alias(migrated_engine, "eals_aaaa0001aaaa0001", ENTITY_A, "ali")
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": ENTITY_A},
        )
    with migrated_engine.connect() as connection:
        held = connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_aliases")  # noqa: S608
        ).scalar_one()
    assert held == 0


#
# `d2b8f5c04e71` added three tables and no suite of its own; these are the CHECKs
# whose absence would be invisible from the application, because the application
# happens never to write the row they refuse. Each is asserted against a server.

OBSERVATION: Final = "eobs_aaaa0001aaaa0001"
PROPOSAL: Final = "eprp_aaaa0001aaaa0001"
MERGE: Final = "emrg_aaaa0001aaaa0001"


def _seed_observation(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "observation_id": OBSERVATION,
        "principal_id": PRINCIPAL_A,
        "kind": "message_participant",
        "observed_value": "Alice Chen",
        "normalized_value": "alice chen",
        "source_id": "src_aaaa0001aaaa0001",
        "source_object_id": "obj_aaaa0001aaaa0001",
        "source_version_id": "ver_aaaa0001aaaa0001",
        "observed_at": "2026-08-18T12:00:00+00:00",
        "recorded_at": "2026-08-18T12:00:00+00:00",
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {SCHEMA}.entity_observations ({columns}) VALUES ({binds})"),  # noqa: S608
            values,
        )


def _seed_proposal(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "proposal_id": PROPOSAL,
        "principal_id": PRINCIPAL_A,
        "kind": "merge_entities",
        "state": "proposed",
        "payload": "{}",
        "observation_ids": "[]",
        "proposed_at": "2026-08-18T12:00:00+00:00",
        "proposed_by": "resolver",
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {SCHEMA}.entity_proposals ({columns}) VALUES ({binds})"),  # noqa: S608
            values,
        )


def _seed_merge(engine: Engine, **overrides: object) -> None:
    values: dict[str, object] = {
        "merge_id": MERGE,
        "principal_id": PRINCIPAL_A,
        "retained_entity_id": ENTITY_A,
        "merged_entity_id": ENTITY_B,
        "proposal_id": PROPOSAL,
        "decided_by": "the operator",
        "reason": "the same person, recorded twice",
        "decided_at": "2026-08-18T12:00:00+00:00",
    }
    values.update(overrides)
    columns = ", ".join(values)
    binds = ", ".join(f":{name}" for name in values)
    with engine.begin() as connection:
        connection.execute(
            text(f"INSERT INTO {SCHEMA}.entity_merge_records ({columns}) VALUES ({binds})"),  # noqa: S608
            values,
        )


@pytest.mark.database
def test_an_observation_of_an_unknown_kind_is_refused(migrated_engine: Engine) -> None:
    """The closed set lives in the migration, so it is the server that must hold it."""
    with pytest.raises(IntegrityError, match="an_observation_kind_is_known"):
        _seed_observation(migrated_engine, kind="overheard_in_a_lift")


@pytest.mark.database
def test_an_observation_with_no_matchable_form_is_refused(migrated_engine: Engine) -> None:
    """An empty normalized value would match nothing, or everything, by query."""
    with pytest.raises(IntegrityError, match="an_observation_records_the_form_it_is_matched_by"):
        _seed_observation(migrated_engine, normalized_value="   ")


@pytest.mark.database
def test_a_proposal_in_an_unknown_state_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError, match="a_proposal_state_is_known"):
        _seed_proposal(migrated_engine, state="probably_fine")


@pytest.mark.database
def test_a_merge_with_no_stated_reason_is_refused(migrated_engine: Engine) -> None:
    """Section 10.11: the record exists to say *why*, not only that."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _seed_proposal(migrated_engine)
    with pytest.raises(IntegrityError, match="a_merge_records_why_it_was_accepted"):
        _seed_merge(migrated_engine, reason="  ")
