"""Revision `441b071bf37b` against a real PostgreSQL server.

RI-ENT-WP-03. Follows the pattern
`tests/schema/test_entity_names_and_organization_profile_migration.py`
established for the prior revision on this chain: the revision sits alone on
the chain, empty-to-head and head-to-`7e114f822af2` leave no residue outside
the two tables this revision adds, every hand-written constraint name in the
migration matches the declaration in `tables.py` (the cost of `D-48`/`D-69`,
paid rather than described), and each CHECK actually rejects the row it
names.

`tests/unit/test_entity_address_and_communication_method_domain.py` proves
`EntityAddress`/`EntityCommunicationMethod` refuse a bad value in the
dataclass. This proves the *server* refuses it too -- including the two
positive uniqueness cases the manager singled out: the same normalized
address recurring for one entity under two *different* address types, and
the identity/channel boundary (`linked_external_identifier_id`) actually
working end-to-end against a real `entity_external_identifiers` row.
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

REVISION: Final = "441b071bf37b"
PREVIOUS_REVISION: Final = "7e114f822af2"

NEW_TABLES: Final = frozenset({"entity_addresses", "entity_communication_methods"})

DISPOSABLE_DATABASE: Final = "my_pa_entity_addresses_comm_methods_schema_test"

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


def _index_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = :table"
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


def _seed_email_identifier(
    engine: Engine, identifier_id: str, entity_id: str, principal_id: str, value: str
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_external_identifiers "  # noqa: S608
                "(identifier_id, entity_id, namespace, normalized_value, display_value, "
                "principal_id) VALUES "
                "(:identifier_id, :entity_id, 'email', :value, :value, :principal_id)"
            ),
            {
                "identifier_id": identifier_id,
                "entity_id": entity_id,
                "value": value,
                "principal_id": principal_id,
            },
        )


def _insert_address(
    engine: Engine,
    *,
    entity_address_id: str,
    entity_id: str,
    principal_id: str,
    address_type_code: str,
    normalized_address_value: str,
    raw_value: str | None = None,
    state: str = "active",
    is_preferred: bool = False,
    retired_at: str | None = None,
    superseded_by_entity_address_id: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, raw_value, "
                "normalized_address_value, state, is_preferred, retired_at, "
                "superseded_by_entity_address_id) VALUES "
                "(:entity_address_id, :entity_id, :principal_id, :address_type_code, :raw_value, "
                ":normalized_address_value, :state, :is_preferred, :retired_at, "
                ":superseded_by_entity_address_id)"
            ),
            {
                "entity_address_id": entity_address_id,
                "entity_id": entity_id,
                "principal_id": principal_id,
                "address_type_code": address_type_code,
                "raw_value": raw_value or normalized_address_value,
                "normalized_address_value": normalized_address_value,
                "state": state,
                "is_preferred": is_preferred,
                "retired_at": retired_at,
                "superseded_by_entity_address_id": superseded_by_entity_address_id,
            },
        )


def _insert_communication_method(
    engine: Engine,
    *,
    communication_method_id: str,
    entity_id: str,
    principal_id: str,
    method_type_code: str,
    normalized_value: str,
    usage_context_code: str = "corporate",
    display_value: str | None = None,
    state: str = "active",
    is_preferred: bool = False,
    retired_at: str | None = None,
    superseded_by_communication_method_id: str | None = None,
    linked_external_identifier_id: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, state, is_preferred, "
                "retired_at, superseded_by_communication_method_id, "
                "linked_external_identifier_id) VALUES "
                "(:communication_method_id, :entity_id, :principal_id, :method_type_code, "
                ":usage_context_code, :normalized_value, :display_value, :state, :is_preferred, "
                ":retired_at, :superseded_by_communication_method_id, "
                ":linked_external_identifier_id)"
            ),
            {
                "communication_method_id": communication_method_id,
                "entity_id": entity_id,
                "principal_id": principal_id,
                "method_type_code": method_type_code,
                "usage_context_code": usage_context_code,
                "normalized_value": normalized_value,
                "display_value": display_value or normalized_value,
                "state": state,
                "is_preferred": is_preferred,
                "retired_at": retired_at,
                "superseded_by_communication_method_id": superseded_by_communication_method_id,
                "linked_external_identifier_id": linked_external_identifier_id,
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


# --- migration mechanics -------------------------------------------------------


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
    """Additive: everything below this revision is untouched by its downgrade.

    `migrated_engine` upgrades to the true chain head, which since
    `f5b06925857e` (RI-ENT-WP-04) sits one revision above this file's own
    `REVISION`. Step down to `REVISION` first so "before" reflects exactly
    what *this* revision's own upgrade left behind, not RI-ENT-WP-04's tables
    stacked on top of it, before checking the one-step downgrade this test is
    actually about.
    """
    command.downgrade(_config(), REVISION)
    before = _tables(migrated_engine)
    assert before >= NEW_TABLES

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    assert before - after == NEW_TABLES
    # The rest of the entity plane, including WP-02's tables, survives the
    # downgrade of this revision alone.
    assert {"entities", "entity_names", "entity_organization_profiles"} <= after


@pytest.mark.database
def test_upgrading_from_the_previous_head_with_seeded_data_preserves_it(
    disposable_database: str,
) -> None:
    """`7e114f822af2` (WP-02) with a seeded entity and name, upgraded to head,
    disturbs neither -- this revision is purely additive."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        _seed_entity(engine, ENTITY_A, PRINCIPAL_A)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                    "(entity_name_id, entity_id, name_type_code, normalized_value, "
                    "display_value, principal_id) VALUES "
                    "('enam_aaaa0001aaaa0001', :entity_id, 'legal', 'x', 'X', :principal_id)"
                ),
                {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
            )

        command.upgrade(_config(), "head")

        assert _tables(engine) >= NEW_TABLES
        with engine.connect() as connection:
            preserved_entity = connection.execute(
                text(f"SELECT entity_id FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
                {"entity_id": ENTITY_A},
            ).scalar_one()
            # Read the seeded row by its own identifier, not by entity: `head`
            # now carries `b8e4d1a6c073` (RI-ENT-WP-12), which backfills one
            # `display`-typed row per active entity, so `ENTITY_A` holds two
            # name rows at head and a read by `entity_id` alone answered
            # `MultipleResultsFound` (found by the database tier on 2026-09-03).
            # The claim is unchanged: the `legal` row this test seeded survives
            # every later revision with its value intact.
            preserved_name = connection.execute(
                text(
                    f"SELECT display_value FROM {SCHEMA}.entity_names "  # noqa: S608
                    "WHERE entity_name_id = :entity_name_id"
                ),
                {"entity_name_id": "enam_aaaa0001aaaa0001"},
            ).scalar_one()
        assert preserved_entity == ENTITY_A
        assert preserved_name == "X"
    finally:
        engine.dispose()


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


@pytest.mark.database
def test_the_expected_indexes_exist_on_entity_addresses(migrated_engine: Engine) -> None:
    assert {
        "entity_addresses_by_principal",
        "entity_addresses_by_normalized_address_value",
        "entity_addresses_by_entity_type_state",
        "an_active_entity_address_is_unique_per_entity_and_type",
        "an_active_entity_address_has_one_preferred_per_type",
    } <= _index_names(migrated_engine, "entity_addresses")


@pytest.mark.database
def test_the_expected_indexes_exist_on_entity_communication_methods(
    migrated_engine: Engine,
) -> None:
    assert {
        "entity_communication_methods_by_principal",
        "entity_communication_methods_by_normalized_value",
        "entity_communication_methods_by_entity_type_state",
        "an_active_communication_method_is_unique_per_entity_and_type",
        "an_active_communication_method_has_one_preferred_per_type",
    } <= _index_names(migrated_engine, "entity_communication_methods")


# --- entity_addresses CHECK constraints --------------------------------------


@pytest.mark.database
def test_an_entity_address_type_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="warehouse",
            normalized_address_value="x",
        )


@pytest.mark.database
def test_an_entity_address_state_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="x",
            state="pending",
        )


@pytest.mark.database
def test_a_blank_raw_value_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="x",
            raw_value="   ",
        )


@pytest.mark.database
def test_address_effective_to_before_effective_from_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, raw_value, "
                "normalized_address_value, effective_from, effective_to) VALUES "
                "('eadr_aaaa0001aaaa0001', :entity_id, :principal_id, 'legal_principal', 'x', "
                "'x', '2026-06-01', '2026-01-01')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_an_address_superseded_by_reference_requires_the_superseded_state(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="first",
    )
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="second",
            state="active",
            superseded_by_entity_address_id="eadr_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_an_address_cannot_supersede_itself(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="first",
            state="superseded",
            superseded_by_entity_address_id="eadr_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_an_active_address_cannot_carry_a_retired_at(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="first",
            state="active",
            retired_at="2026-01-01T00:00:00Z",
        )


@pytest.mark.database
def test_retiring_an_address_with_retired_at_succeeds(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="first",
        state="retired",
        retired_at="2026-01-01T00:00:00Z",
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT state, retired_at FROM {SCHEMA}.entity_addresses "  # noqa: S608
                "WHERE entity_address_id = :entity_address_id"
            ),
            {"entity_address_id": "eadr_aaaa0001aaaa0001"},
        ).one()
    assert row[0] == "retired"
    assert row[1] is not None


@pytest.mark.database
def test_a_superseded_address_resolves_to_its_successor_within_the_same_principal(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_bbbb0002bbbb0002",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="successor",
    )
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="regional_office",
        normalized_address_value="predecessor",
        state="superseded",
        superseded_by_entity_address_id="eadr_bbbb0002bbbb0002",
    )
    with migrated_engine.connect() as connection:
        successor = connection.execute(
            text(
                f"SELECT successor.entity_address_id, successor.normalized_address_value "  # noqa: S608
                f"FROM {SCHEMA}.entity_addresses predecessor "
                f"JOIN {SCHEMA}.entity_addresses successor "
                "ON successor.entity_address_id = predecessor.superseded_by_entity_address_id "
                "AND successor.principal_id = predecessor.principal_id "
                "WHERE predecessor.entity_address_id = :predecessor_id"
            ),
            {"predecessor_id": "eadr_aaaa0001aaaa0001"},
        ).one()
    assert successor[0] == "eadr_bbbb0002bbbb0002"
    assert successor[1] == "successor"


@pytest.mark.database
def test_an_entity_address_cannot_bind_an_entity_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    """Principal partitioning: the composite FK refuses a cross-Principal bind."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_B,
            address_type_code="legal_principal",
            normalized_address_value="x",
        )


@pytest.mark.database
def test_an_address_supersession_cannot_cross_principals(migrated_engine: Engine) -> None:
    """The self-referencing FK is `(superseded_by_entity_address_id, principal_id)`."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_B)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_bbbb0002bbbb0002",
        entity_id=ENTITY_B,
        principal_id=PRINCIPAL_B,
        address_type_code="legal_principal",
        normalized_address_value="other principal's address",
    )
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="x",
            state="superseded",
            superseded_by_entity_address_id="eadr_bbbb0002bbbb0002",
        )


# --- entity_addresses uniqueness: the negative case --------------------------


@pytest.mark.database
def test_two_active_addresses_of_one_type_with_the_same_value_collide(
    migrated_engine: Engine,
) -> None:
    """The active per-(entity, type) uniqueness this table exists to enforce."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="742 synthetic lane",
    )
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="legal_principal",
            normalized_address_value="742 synthetic lane",
        )


# --- entity_addresses uniqueness: the positive case (the one that matters) ---


@pytest.mark.database
def test_the_same_normalized_address_under_two_different_types_is_permitted(
    migrated_engine: Engine,
) -> None:
    """RI-ENT-WP-03's single most important uniqueness rule.

    A seller's legal-principal address and a project address are often the
    identical street address, and the manager was explicit that this must be
    admitted, not refused: `address_type_code` is part of the active
    uniqueness key precisely so this insert succeeds twice.
    """
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="742 synthetic lane|springfield",
    )
    # No exception: the identical normalized address under a DIFFERENT type
    # for the SAME entity is a distinct, permitted row.
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_bbbb0002bbbb0002",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="project",
        normalized_address_value="742 synthetic lane|springfield",
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT address_type_code FROM {SCHEMA}.entity_addresses "  # noqa: S608
                "WHERE entity_id = :entity_id AND state = 'active'"
            ),
            {"entity_id": ENTITY_A},
        ).all()
    assert {row[0] for row in rows} == {"legal_principal", "project"}


@pytest.mark.database
def test_two_different_entities_may_share_an_active_address(migrated_engine: Engine) -> None:
    """Not a global uniqueness: two real organizations may share an address."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="office",
        normalized_address_value="shared building",
    )
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_bbbb0002bbbb0002",
        entity_id=ENTITY_B,
        principal_id=PRINCIPAL_A,
        address_type_code="office",
        normalized_address_value="shared building",
    )


@pytest.mark.database
def test_two_active_preferred_addresses_of_one_type_collide(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="regional_office",
        normalized_address_value="alpha",
        is_preferred=True,
    )
    with pytest.raises(IntegrityError):
        _insert_address(
            migrated_engine,
            entity_address_id="eadr_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            address_type_code="regional_office",
            normalized_address_value="beta",
            is_preferred=True,
        )


@pytest.mark.database
def test_different_address_types_may_each_have_their_own_preferred(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="legal address",
        is_preferred=True,
    )
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_bbbb0002bbbb0002",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="project",
        normalized_address_value="project address",
        is_preferred=True,
    )


# --- entity_addresses: structured-vs-raw fields (RULING 3) -------------------


@pytest.mark.database
def test_an_address_with_only_raw_value_populated_inserts_successfully(
    migrated_engine: Engine,
) -> None:
    """No structured field NOT NULL anywhere -- unknown stays unresolved."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="known_other",
        normalized_address_value="742 synthetic lane, springfield",
        raw_value="742 Synthetic Lane, Springfield",
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT line1, city, region, postal_code, country FROM {SCHEMA}.entity_addresses "  # noqa: S608
                "WHERE entity_address_id = :entity_address_id"
            ),
            {"entity_address_id": "eadr_aaaa0001aaaa0001"},
        ).one()
    assert row == (None, None, None, None, None)


@pytest.mark.database
def test_an_address_with_only_city_populated_inserts_successfully(
    migrated_engine: Engine,
) -> None:
    """Partial structure is fine: knowing city but not postal_code is not
    all-or-nothing."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, city, "
                "raw_value, normalized_address_value) VALUES "
                "('eadr_aaaa0001aaaa0001', :entity_id, :principal_id, 'known_other', "
                "'Springfield', 'raw text', 'springfield')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT city, line1, postal_code FROM {SCHEMA}.entity_addresses "  # noqa: S608
                "WHERE entity_address_id = :entity_address_id"
            ),
            {"entity_address_id": "eadr_aaaa0001aaaa0001"},
        ).one()
    assert row == ("Springfield", None, None)


# --- entity_communication_methods CHECK constraints --------------------------


@pytest.mark.database
def test_a_communication_method_type_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="fax",
            normalized_value="x",
        )


@pytest.mark.database
def test_a_communication_usage_context_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            usage_context_code="marketing",
        )


@pytest.mark.database
def test_a_communication_verification_status_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, "
                "verification_status_code) VALUES "
                "('ecmm_aaaa0001aaaa0001', :entity_id, :principal_id, 'phone', 'corporate', "
                "'5551234567', '5551234567', 'probably_true')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_a_communication_method_state_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            state="pending",
        )


@pytest.mark.database
def test_a_blank_communication_normalized_value_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value) VALUES "
                "('ecmm_aaaa0001aaaa0001', :entity_id, :principal_id, 'phone', 'corporate', "
                "'   ', 'X')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_communication_method_effective_to_before_effective_from_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, effective_from, "
                "effective_to) VALUES "
                "('ecmm_aaaa0001aaaa0001', :entity_id, :principal_id, 'phone', 'corporate', "
                "'5551234567', '5551234567', '2026-06-01', '2026-01-01')"
            ),
            {"entity_id": ENTITY_A, "principal_id": PRINCIPAL_A},
        )


@pytest.mark.database
def test_a_communication_method_superseded_by_reference_requires_the_superseded_state(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5559876543",
            state="active",
            superseded_by_communication_method_id="ecmm_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_a_communication_method_cannot_supersede_itself(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            state="superseded",
            superseded_by_communication_method_id="ecmm_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_an_active_communication_method_cannot_carry_a_retired_at(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            state="active",
            retired_at="2026-01-01T00:00:00Z",
        )


@pytest.mark.database
def test_retiring_a_communication_method_with_retired_at_succeeds(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
        state="retired",
        retired_at="2026-01-01T00:00:00Z",
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT state, retired_at FROM {SCHEMA}.entity_communication_methods "  # noqa: S608
                "WHERE communication_method_id = :communication_method_id"
            ),
            {"communication_method_id": "ecmm_aaaa0001aaaa0001"},
        ).one()
    assert row[0] == "retired"
    assert row[1] is not None


@pytest.mark.database
def test_a_superseded_communication_method_resolves_to_its_successor(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_bbbb0002bbbb0002",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5559876543",
    )
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
        state="superseded",
        superseded_by_communication_method_id="ecmm_bbbb0002bbbb0002",
    )
    with migrated_engine.connect() as connection:
        successor = connection.execute(
            text(
                f"SELECT successor.communication_method_id, successor.normalized_value "  # noqa: S608
                f"FROM {SCHEMA}.entity_communication_methods predecessor "
                f"JOIN {SCHEMA}.entity_communication_methods successor "
                "ON successor.communication_method_id = "
                "predecessor.superseded_by_communication_method_id "
                "AND successor.principal_id = predecessor.principal_id "
                "WHERE predecessor.communication_method_id = :predecessor_id"
            ),
            {"predecessor_id": "ecmm_aaaa0001aaaa0001"},
        ).one()
    assert successor[0] == "ecmm_bbbb0002bbbb0002"
    assert successor[1] == "5559876543"


@pytest.mark.database
def test_a_communication_method_cannot_bind_an_entity_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_B,
            method_type_code="phone",
            normalized_value="5551234567",
        )


@pytest.mark.database
def test_a_communication_method_supersession_cannot_cross_principals(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_B)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_bbbb0002bbbb0002",
        entity_id=ENTITY_B,
        principal_id=PRINCIPAL_B,
        method_type_code="phone",
        normalized_value="5559876543",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            state="superseded",
            superseded_by_communication_method_id="ecmm_bbbb0002bbbb0002",
        )


# --- entity_communication_methods uniqueness: the negative case --------------


@pytest.mark.database
def test_two_active_methods_of_one_type_with_the_same_value_collide(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
        )


@pytest.mark.database
def test_usage_context_does_not_distinguish_uniqueness(migrated_engine: Engine) -> None:
    """Deliberate design choice: the same value tagged with two DIFFERENT
    usage_context_codes is still one channel double-counted, not two, because
    `usage_context_code` is NOT part of the active uniqueness key."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
        usage_context_code="corporate",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            usage_context_code="generic",
        )


# --- entity_communication_methods uniqueness: the positive multi-channel case


@pytest.mark.database
def test_two_different_values_under_different_usage_contexts_are_both_admitted(
    migrated_engine: Engine,
) -> None:
    """The required multi-channel-by-context case: a corporate number and a
    project's own number already differ in normalized_value, so both insert."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
        usage_context_code="corporate",
    )
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_bbbb0002bbbb0002",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5559876543",
        usage_context_code="project",
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT normalized_value, usage_context_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_communication_methods WHERE entity_id = :entity_id"
            ),
            {"entity_id": ENTITY_A},
        ).all()
    assert {tuple(row) for row in rows} == {
        ("5551234567", "corporate"),
        ("5559876543", "project"),
    }


@pytest.mark.database
def test_two_different_entities_may_share_an_active_communication_method(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="domain",
        normalized_value="shared-example.test",
    )
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_bbbb0002bbbb0002",
        entity_id=ENTITY_B,
        principal_id=PRINCIPAL_A,
        method_type_code="domain",
        normalized_value="shared-example.test",
    )


@pytest.mark.database
def test_two_active_preferred_communication_methods_of_one_type_collide(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
        is_preferred=True,
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_bbbb0002bbbb0002",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5559876543",
            is_preferred=True,
        )


@pytest.mark.database
def test_different_method_types_may_each_have_their_own_preferred(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
        is_preferred=True,
    )
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_bbbb0002bbbb0002",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="domain",
        normalized_value="synthetic-example.test",
        is_preferred=True,
    )


# --- the identity/channel boundary at the database layer ---------------------


@pytest.mark.database
def test_a_phone_method_cannot_link_an_external_identifier(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_email_identifier(
        migrated_engine,
        "xid_aaaa0001aaaa0001",
        ENTITY_A,
        PRINCIPAL_A,
        "contact@synthetic-example.test",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="phone",
            normalized_value="5551234567",
            linked_external_identifier_id="xid_aaaa0001aaaa0001",
        )


@pytest.mark.database
@pytest.mark.parametrize("method_type_code", ["domain", "website"])
def test_a_domain_or_website_method_cannot_link_an_external_identifier(
    migrated_engine: Engine, method_type_code: str
) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_email_identifier(
        migrated_engine,
        "xid_aaaa0001aaaa0001",
        ENTITY_A,
        PRINCIPAL_A,
        "contact@synthetic-example.test",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code=method_type_code,
            normalized_value="synthetic-example.test",
            linked_external_identifier_id="xid_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_an_email_method_may_link_a_real_external_identifier_row(
    migrated_engine: Engine,
) -> None:
    """The identity/channel boundary working end-to-end: a genuine
    `entity_external_identifiers` row of `namespace='email'`, in the same
    Principal, cross-referenced by an EMAIL communication method."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_email_identifier(
        migrated_engine,
        "xid_aaaa0001aaaa0001",
        ENTITY_A,
        PRINCIPAL_A,
        "contact@synthetic-example.test",
    )
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="email",
        normalized_value="contact@synthetic-example.test",
        linked_external_identifier_id="xid_aaaa0001aaaa0001",
    )
    with migrated_engine.connect() as connection:
        linked = connection.execute(
            text(
                f"SELECT xid.namespace, xid.normalized_value "  # noqa: S608
                f"FROM {SCHEMA}.entity_communication_methods ecm "
                f"JOIN {SCHEMA}.entity_external_identifiers xid "
                "ON xid.identifier_id = ecm.linked_external_identifier_id "
                "WHERE ecm.communication_method_id = :communication_method_id"
            ),
            {"communication_method_id": "ecmm_aaaa0001aaaa0001"},
        ).one()
    assert linked[0] == "email"
    assert linked[1] == "contact@synthetic-example.test"


@pytest.mark.database
def test_a_communication_method_link_cannot_cross_principals(migrated_engine: Engine) -> None:
    """The composite FK `(linked_external_identifier_id, principal_id)` refuses
    a cross-Principal link, the same partitioning proof as the entity FK."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_B)
    _seed_email_identifier(
        migrated_engine,
        "xid_bbbb0002bbbb0002",
        ENTITY_B,
        PRINCIPAL_B,
        "other@synthetic-example.test",
    )
    with pytest.raises(IntegrityError):
        _insert_communication_method(
            migrated_engine,
            communication_method_id="ecmm_aaaa0001aaaa0001",
            entity_id=ENTITY_A,
            principal_id=PRINCIPAL_A,
            method_type_code="email",
            normalized_value="other@synthetic-example.test",
            linked_external_identifier_id="xid_bbbb0002bbbb0002",
        )


# --- cascading delete ----------------------------------------------------------


@pytest.mark.database
def test_deleting_an_entity_cascades_to_its_addresses_and_communication_methods(
    migrated_engine: Engine,
) -> None:
    """`ON DELETE CASCADE` on both tables, proven rather than assumed from the DDL."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A)
    _insert_address(
        migrated_engine,
        entity_address_id="eadr_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        address_type_code="legal_principal",
        normalized_address_value="x",
    )
    _insert_communication_method(
        migrated_engine,
        communication_method_id="ecmm_aaaa0001aaaa0001",
        entity_id=ENTITY_A,
        principal_id=PRINCIPAL_A,
        method_type_code="phone",
        normalized_value="5551234567",
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": ENTITY_A},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_addresses"),  # noqa: S608
            ).scalar_one()
            == 0
        )
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_communication_methods"),  # noqa: S608
            ).scalar_one()
            == 0
        )
