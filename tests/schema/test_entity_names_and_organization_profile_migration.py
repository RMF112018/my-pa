"""Revision `7e114f822af2` against a real PostgreSQL server.

RI-ENT-WP-02. Follows the pattern `tests/schema/test_entity_schema_migration.py`
established for the entity plane's earlier revisions: the revision sits alone on
the chain, empty-to-head and head-to-`b727e870d45e` leave no residue outside the
two tables this revision adds, every hand-written constraint name in the
migration matches the declaration in `tables.py` (the cost of `D-48`/`D-69`,
paid rather than described), and each CHECK actually rejects the row it names.

`tests/unit/test_entity_domain.py` proves `EntityName`/`EntityOrganizationProfile`
refuse a bad value in the dataclass. This proves the *server* refuses it too.
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
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

REVISION: Final = "7e114f822af2"
PREVIOUS_REVISION: Final = "b727e870d45e"

NEW_TABLES: Final = frozenset({"entity_names", "entity_organization_profiles"})

DISPOSABLE_DATABASE: Final = "my_pa_entity_names_org_profile_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY_A: Final = "ent_aaaa0001aaaa0001"
ENTITY_B: Final = "ent_bbbb0002bbbb0002"


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


def _seed_entity(
    engine: Engine,
    entity_id: str,
    principal_id: str,
    entity_type: str = "organization",
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, :entity_type, :name, :name, 'active')"
            ),
            {
                "entity_id": entity_id,
                "principal_id": principal_id,
                "entity_type": entity_type,
                "name": "synthetic organization",
            },
        )


# --- chain position (no database) -------------------------------------------


def test_the_revision_is_in_the_chain_on_the_prior_head() -> None:
    """One head, and this revision revises the campaign's prior head exactly."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_the_revision_declares_the_tables_it_creates() -> None:
    declared = {table.name for table in METADATA.tables.values() if table.name in NEW_TABLES}
    assert declared == NEW_TABLES


# --- migration round trip ----------------------------------------------------


@pytest.mark.database
def test_the_revision_runs_empty_to_head_and_head_to_empty(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _tables(engine) >= NEW_TABLES

        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_one_step_removes_exactly_these_two_tables(migrated_engine: Engine) -> None:
    """Additive: everything below this revision is untouched by its downgrade."""
    # `migrated_engine` upgrades to the chain's true head, which may now sit
    # above `REVISION` -- `441b071bf37b` (RI-ENT-WP-03) does. Step down to
    # `REVISION` itself first so the delta measured below is this revision's
    # own tables, not every revision stacked on top of it as well.
    command.downgrade(_config(), REVISION)
    before = _tables(migrated_engine)
    assert before >= NEW_TABLES

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    assert before - after == NEW_TABLES
    # The rest of the entity plane survives the downgrade of this revision alone.
    assert {"entities", "entity_aliases", "entity_external_identifiers"} <= after


# --- declaration parity -------------------------------------------------------


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(NEW_TABLES))
def test_every_declared_constraint_name_exists_on_the_server(
    migrated_engine: Engine, table_name: str
) -> None:
    declared = {
        constraint.name
        for constraint in METADATA.tables[f"{SCHEMA}.{table_name}"].constraints
        if constraint.name is not None
    }
    on_server = _constraint_names(migrated_engine, table_name)
    assert declared <= on_server, declared - on_server


@pytest.mark.database
@pytest.mark.parametrize("table_name", sorted(NEW_TABLES))
def test_every_declared_column_exists_on_the_server(
    migrated_engine: Engine, table_name: str
) -> None:
    with migrated_engine.connect() as connection:
        on_server = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table_name},
            )
        }
    declared = {column.name for column in METADATA.tables[f"{SCHEMA}.{table_name}"].columns}
    assert declared == on_server


# --- entity_names CHECK constraints actually reject the row they name -------


@pytest.mark.database
def test_an_entity_name_type_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'trademark', 'x', 'X', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_an_entity_name_state_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, state) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'legal', 'x', 'X', "
                ":principal_id, 'pending')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_a_blank_normalized_value_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'legal', '   ', 'X', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_effective_to_before_effective_from_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, effective_from, effective_to) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'legal', 'x', 'X', :principal_id, "
                "'2026-06-01', '2026-01-01')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_a_superseded_by_reference_requires_the_superseded_state(migrated_engine: Engine) -> None:
    """A name may not name a successor unless its own state says SUPERSEDED."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'legal', 'first', 'First', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, state, superseded_by_entity_name_id) VALUES "
                "('enam_bbbb0002bbbb0002', :entity_id, 'legal', 'second', 'Second', "
                ":principal_id, 'active', 'enam_aaaa0001aaaa0001')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_two_active_names_of_one_type_with_the_same_value_collide(migrated_engine: Engine) -> None:
    """The active per-(entity, type) uniqueness this table exists to enforce."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'brand', 'synthetic studio four', "
                "'Synthetic Studio Four', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_bbbb0002bbbb0002', :entity_id, 'brand', 'synthetic studio four', "
                "'Synthetic Studio Four (dup)', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_two_different_entities_may_share_an_active_name(migrated_engine: Engine) -> None:
    """Not a global uniqueness: two real organizations may share a name form."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'brand', 'the studio', "
                "'The Studio', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_bbbb0002bbbb0002', :entity_id, 'brand', 'the studio', "
                "'The Studio', :principal_id)"
            ),
            {"entity_id": ENTITY_B, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_two_active_preferred_names_of_one_type_collide(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, is_preferred) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'brand', 'alpha', 'Alpha', "
                ":principal_id, true)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, is_preferred) VALUES "
                "('enam_bbbb0002bbbb0002', :entity_id, 'brand', 'beta', 'Beta', "
                ":principal_id, true)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_an_entity_name_cannot_bind_an_entity_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    """Principal partitioning: the composite FK refuses a cross-Principal bind."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'legal', 'x', 'X', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_B},
        )


# --- entity_organization_profiles CHECK constraints -------------------------


@pytest.mark.database
def test_an_organization_kind_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code, "
                "legal_identity_status_code) VALUES "
                "(:entity_id, :principal_id, 'shell_corp', 'unresolved')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_a_legal_identity_status_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code, "
                "legal_identity_status_code) VALUES "
                "(:entity_id, :principal_id, 'company', 'probably_true')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_the_legal_identity_status_default_is_unresolved(migrated_engine: Engine) -> None:
    """A writer that states no status gets the non-affirmative default, never a guess."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code) VALUES "
                "(:entity_id, :principal_id, 'company')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with migrated_engine.connect() as connection:
        status = connection.execute(
            text(
                f"SELECT legal_identity_status_code FROM {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": ENTITY_A},
        ).scalar_one()
    assert status == "unresolved"


@pytest.mark.database
def test_an_entity_carries_at_most_one_organization_profile(migrated_engine: Engine) -> None:
    """One row per entity: the primary key on `entity_id` is the whole rule."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code) VALUES "
                "(:entity_id, :principal_id, 'company')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code) VALUES "
                "(:entity_id, :principal_id, 'llc_or_spv')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_an_organization_profile_cannot_bind_an_entity_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code) VALUES "
                "(:entity_id, :principal_id, 'company')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_B},
        )


@pytest.mark.database
def test_deleting_an_entity_cascades_to_its_names_and_profile(migrated_engine: Engine) -> None:
    """`ON DELETE CASCADE` on both tables, proven rather than assumed from the DDL."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id) VALUES "
                "('enam_aaaa0001aaaa0001', :entity_id, 'legal', 'x', 'X', :principal_id)"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code) VALUES "
                "(:entity_id, :principal_id, 'company')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": ENTITY_A},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_names"),  # noqa: S608
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_organization_profiles"),  # noqa: S608
            ).scalar_one()
            == 0
        )
