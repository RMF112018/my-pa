"""Revision `f5b06925857e` against a real PostgreSQL server.

RI-ENT-WP-04. Follows the pattern
`tests/schema/test_entity_addresses_and_communication_methods_migration.py`
established for the prior revision on this chain: the revision sits alone on
the chain, empty-to-head and head-to-`441b071bf37b` leave no residue outside
the three tables this revision adds, every hand-written constraint name in the
migration matches the declaration in `tables.py` (the cost of `D-48`/`D-69`,
paid rather than described), and each CHECK actually rejects the row it names.

`tests/unit/test_project_entity_participation_domain.py` proves
`EntityRoleType`/`EntityDisciplineType`/`EntityProjectParticipation` refuse a
bad value in the dataclass. This proves the *server* refuses it too --
including the taxonomy foreign keys, the deliberately role-inclusive active
uniqueness key, and the composite-FK Principal partitioning on both entity
references a participation row carries.
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

REVISION: Final = "f5b06925857e"
PREVIOUS_REVISION: Final = "441b071bf37b"

NEW_TABLES: Final = frozenset(
    {"entity_role_types", "entity_discipline_types", "entity_project_participations"}
)

DISPOSABLE_DATABASE: Final = "my_pa_entity_project_participations_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
PROJECT_A: Final = "ent_aaaa0001aaaa0001"
PROJECT_B: Final = "ent_bbbb0002bbbb0002"
PARTICIPANT_A: Final = "ent_cccc0003cccc0003"
PARTICIPANT_B: Final = "ent_dddd0004dddd0004"
OTHER_PRINCIPAL_ENTITY: Final = "ent_eeee0005eeee0005"


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
    entity_type: str = "project",
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
                "name": f"synthetic entity {entity_id}",
            },
        )


def _insert_participation(
    engine: Engine,
    *,
    participation_id: str,
    principal_id: str,
    project_entity_id: str,
    participant_entity_id: str,
    project_display_name: str = "Larkspur Commons",
    role_code: str | None = None,
    role_text: str | None = None,
    discipline_code: str | None = None,
    discipline_text: str | None = None,
    scope_text: str | None = None,
    role_basis_code: str = "contractual",
    stakeholder_side_code: str = "contractor",
    stakeholder_class_code: str = "core",
    relationship_status_code: str = "active",
    effective_from: str | None = None,
    effective_to: str | None = None,
    state: str = "active",
    retired_at: str | None = None,
    superseded_by_participation_id: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, participant_entity_id, "
                "project_display_name, role_code, role_text, discipline_code, discipline_text, "
                "scope_text, role_basis_code, stakeholder_side_code, stakeholder_class_code, "
                "relationship_status_code, effective_from, effective_to, state, retired_at, "
                "superseded_by_participation_id) VALUES "
                "(:participation_id, :principal_id, :project_entity_id, :participant_entity_id, "
                ":project_display_name, :role_code, :role_text, :discipline_code, "
                ":discipline_text, :scope_text, :role_basis_code, :stakeholder_side_code, "
                ":stakeholder_class_code, :relationship_status_code, :effective_from, "
                ":effective_to, :state, :retired_at, :superseded_by_participation_id)"
            ),
            {
                "participation_id": participation_id,
                "principal_id": principal_id,
                "project_entity_id": project_entity_id,
                "participant_entity_id": participant_entity_id,
                "project_display_name": project_display_name,
                "role_code": role_code,
                "role_text": role_text,
                "discipline_code": discipline_code,
                "discipline_text": discipline_text,
                "scope_text": scope_text,
                "role_basis_code": role_basis_code,
                "stakeholder_side_code": stakeholder_side_code,
                "stakeholder_class_code": stakeholder_class_code,
                "relationship_status_code": relationship_status_code,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "state": state,
                "retired_at": retired_at,
                "superseded_by_participation_id": superseded_by_participation_id,
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
def test_downgrading_one_step_removes_exactly_these_three_tables(migrated_engine: Engine) -> None:
    """Additive: everything below this revision is untouched by its downgrade."""
    before = _tables(migrated_engine)
    assert before >= NEW_TABLES

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    assert before - after == {
        "entity_project_participations",
        "entity_discipline_types",
        "entity_role_types",
    }
    # The rest of the entity plane, including WP-02's and WP-03's tables,
    # survives the downgrade of this revision alone.
    assert {
        "entities",
        "entity_names",
        "entity_organization_profiles",
        "entity_addresses",
        "entity_communication_methods",
    } <= after


@pytest.mark.database
def test_upgrading_from_the_previous_head_with_seeded_data_preserves_it(
    disposable_database: str,
) -> None:
    """`441b071bf37b` (WP-03) with a seeded project entity, a participant
    entity, and a participation row referencing both, upgraded to head,
    disturbs neither -- this revision is purely additive."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        _seed_entity(engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
        _seed_entity(engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")

        command.upgrade(_config(), "head")

        assert _tables(engine) >= NEW_TABLES
        # Confirm entities that predate the new tables can now be referenced
        # by a participation row inserted after the upgrade.
        _insert_participation(
            engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            role_code="CONSULTANT",
        )
        with engine.connect() as connection:
            preserved_project = connection.execute(
                text(f"SELECT entity_id FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
                {"entity_id": PROJECT_A},
            ).scalar_one()
            preserved_participant = connection.execute(
                text(f"SELECT entity_id FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
                {"entity_id": PARTICIPANT_A},
            ).scalar_one()
            participation_row = connection.execute(
                text(
                    f"SELECT project_entity_id, participant_entity_id FROM "  # noqa: S608
                    f"{SCHEMA}.entity_project_participations WHERE participation_id = :pid"
                ),
                {"pid": "eppt_aaaa0001aaaa0001"},
            ).one()
        assert preserved_project == PROJECT_A
        assert preserved_participant == PARTICIPANT_A
        assert participation_row == (PROJECT_A, PARTICIPANT_A)
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
def test_the_expected_indexes_exist_on_entity_project_participations(
    migrated_engine: Engine,
) -> None:
    assert {
        "entity_project_participations_by_principal",
        "entity_project_participations_by_project_state",
        "an_active_project_participation_is_unique_per_project_and_role",
    } <= _index_names(migrated_engine, "entity_project_participations")


# --- entity_role_types / entity_discipline_types CHECK constraints ------------


@pytest.mark.database
def test_a_role_type_status_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_role_types "  # noqa: S608
                "(role_code, label, status) VALUES ('NEW_ROLE', 'New Role', 'pending')"
            )
        )


@pytest.mark.database
def test_a_discipline_type_status_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_discipline_types "  # noqa: S608
                "(discipline_code, label, status) VALUES "
                "('NEW_DISCIPLINE', 'New Discipline', 'pending')"
            )
        )


@pytest.mark.database
def test_a_role_type_blank_code_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_role_types "  # noqa: S608
                "(role_code, label) VALUES ('   ', 'Blank Role')"
            )
        )


@pytest.mark.database
def test_a_discipline_type_blank_label_is_refused(migrated_engine: Engine) -> None:
    with pytest.raises(IntegrityError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_discipline_types "  # noqa: S608
                "(discipline_code, label) VALUES ('BLANK_LABEL', '   ')"
            )
        )


# --- entity_project_participations CHECK constraints --------------------------


@pytest.mark.database
def test_a_role_basis_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            role_basis_code="guessed",
        )


@pytest.mark.database
def test_a_stakeholder_side_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            stakeholder_side_code="bystander",
        )


@pytest.mark.database
def test_a_stakeholder_class_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            stakeholder_class_code="tier_one",
        )


@pytest.mark.database
def test_a_relationship_status_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            relationship_status_code="pending",
        )


@pytest.mark.database
def test_a_participation_state_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            state="pending",
        )


@pytest.mark.database
def test_a_blank_project_display_name_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            project_display_name="   ",
        )


@pytest.mark.database
@pytest.mark.parametrize("field_name", ["role_text", "discipline_text", "scope_text"])
def test_a_blank_optional_text_field_is_refused_when_present(
    migrated_engine: Engine, field_name: str
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            **{field_name: "   "},
        )


@pytest.mark.database
@pytest.mark.parametrize("field_name", ["role_text", "discipline_text", "scope_text"])
def test_the_optional_text_field_may_be_absent(migrated_engine: Engine, field_name: str) -> None:
    """Non-null-when-absent is fine: the CHECK only fires when the field is
    present but blank, never merely because it is NULL."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        **{field_name: None},
    )


@pytest.mark.database
def test_effective_to_before_effective_from_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            effective_from="2026-06-01",
            effective_to="2026-01-01",
        )


@pytest.mark.database
def test_a_project_cannot_participate_in_itself_at_the_server(migrated_engine: Engine) -> None:
    """`project_entity_id == participant_entity_id` refused by the CHECK,
    not merely the dataclass."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PROJECT_A,
        )


# --- supersession rules ---------------------------------------------------------


@pytest.mark.database
def test_a_superseded_by_reference_requires_the_superseded_state(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code="CONSULTANT",
    )
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_bbbb0002bbbb0002",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            role_code="OWNER_REPRESENTATIVE",
            state="active",
            superseded_by_participation_id="eppt_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_a_participation_cannot_supersede_itself_at_the_server(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            state="superseded",
            superseded_by_participation_id="eppt_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_a_superseded_participation_resolves_to_its_successor_within_the_same_principal(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        project_display_name="successor display name",
    )
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        project_display_name="predecessor display name",
        state="superseded",
        superseded_by_participation_id="eppt_bbbb0002bbbb0002",
    )
    with migrated_engine.connect() as connection:
        successor = connection.execute(
            text(
                f"SELECT successor.participation_id, successor.project_display_name "  # noqa: S608
                f"FROM {SCHEMA}.entity_project_participations predecessor "
                f"JOIN {SCHEMA}.entity_project_participations successor "
                "ON successor.participation_id = predecessor.superseded_by_participation_id "
                "AND successor.principal_id = predecessor.principal_id "
                "WHERE predecessor.participation_id = :predecessor_id"
            ),
            {"predecessor_id": "eppt_aaaa0001aaaa0001"},
        ).one()
    assert successor[0] == "eppt_bbbb0002bbbb0002"
    assert successor[1] == "successor display name"


@pytest.mark.database
def test_a_participation_supersession_cannot_cross_principals(migrated_engine: Engine) -> None:
    """The self-referencing FK is `(superseded_by_participation_id, principal_id)`."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, PROJECT_B, PRINCIPAL_B, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_B, PRINCIPAL_B, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_B,
        project_entity_id=PROJECT_B,
        participant_entity_id=PARTICIPANT_B,
        project_display_name="other principal's participation",
    )
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            state="superseded",
            superseded_by_participation_id="eppt_bbbb0002bbbb0002",
        )


# --- cross-Principal binds: the composite FK on both entity references -------


@pytest.mark.database
def test_a_participation_cannot_bind_a_project_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    """Principal partitioning: the composite FK on `project_entity_id` refuses
    a cross-Principal bind."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_B, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_B,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
        )


@pytest.mark.database
def test_a_participation_cannot_bind_a_participant_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    """Principal partitioning: the composite FK on `participant_entity_id`
    refuses a cross-Principal bind."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, OTHER_PRINCIPAL_ENTITY, PRINCIPAL_B, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=OTHER_PRINCIPAL_ENTITY,
        )


# --- taxonomy FK tests -----------------------------------------------------------


@pytest.mark.database
def test_a_role_code_not_present_in_the_taxonomy_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            role_code="NOT_A_SEEDED_ROLE",
        )


@pytest.mark.database
def test_a_discipline_code_not_present_in_the_taxonomy_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            discipline_code="NOT_A_SEEDED_DISCIPLINE",
        )


@pytest.mark.database
def test_a_valid_seeded_role_code_succeeds(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code="OWNER",
    )


@pytest.mark.database
def test_a_valid_seeded_discipline_code_succeeds(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        discipline_code="CIVIL_ENGINEERING",
    )


@pytest.mark.database
def test_a_null_role_code_and_discipline_code_succeed(migrated_engine: Engine) -> None:
    """Both taxonomy references are nullable."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code=None,
        discipline_code=None,
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT role_code, discipline_code FROM "  # noqa: S608
                f"{SCHEMA}.entity_project_participations WHERE participation_id = :pid"
            ),
            {"pid": "eppt_aaaa0001aaaa0001"},
        ).one()
    assert row == (None, None)


# --- active-uniqueness tests -----------------------------------------------------


@pytest.mark.database
def test_two_active_participations_of_the_same_participant_project_and_role_collide(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code="CONSULTANT",
    )
    with pytest.raises(IntegrityError):
        _insert_participation(
            migrated_engine,
            participation_id="eppt_bbbb0002bbbb0002",
            principal_id=PRINCIPAL_A,
            project_entity_id=PROJECT_A,
            participant_entity_id=PARTICIPANT_A,
            role_code="CONSULTANT",
        )


@pytest.mark.database
def test_the_same_participant_and_project_with_two_different_roles_both_succeed(
    migrated_engine: Engine,
) -> None:
    """Proves the deliberate inclusion of `role_code` in the active
    uniqueness key: one entity may concurrently hold two different roles on
    the same project."""
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code="CONSULTANT",
    )
    _insert_participation(
        migrated_engine,
        participation_id="eppt_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code="OWNER_REPRESENTATIVE",
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT role_code FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE participant_entity_id = :participant_entity_id AND state = 'active'"
            ),
            {"participant_entity_id": PARTICIPANT_A},
        ).all()
    assert {row[0] for row in rows} == {"CONSULTANT", "OWNER_REPRESENTATIVE"}


@pytest.mark.database
def test_two_different_participants_on_the_same_project_with_the_same_role_both_succeed(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, PARTICIPANT_B, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
        role_code="SUBCONTRACTOR",
    )
    _insert_participation(
        migrated_engine,
        participation_id="eppt_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_B,
        role_code="SUBCONTRACTOR",
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT participant_entity_id FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE project_entity_id = :project_entity_id AND state = 'active'"
            ),
            {"project_entity_id": PROJECT_A},
        ).all()
    assert {row[0] for row in rows} == {PARTICIPANT_A, PARTICIPANT_B}


# --- cascading delete ------------------------------------------------------------


@pytest.mark.database
def test_deleting_the_project_entity_cascades_to_its_participation_rows(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": PROJECT_A},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_project_participations"),  # noqa: S608
            ).scalar_one()
            == 0
        )


@pytest.mark.database
def test_deleting_the_participant_entity_cascades_to_its_participation_rows(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PROJECT_A, PRINCIPAL_A, entity_type="project")
    _seed_entity(migrated_engine, PARTICIPANT_A, PRINCIPAL_A, entity_type="organization")
    _insert_participation(
        migrated_engine,
        participation_id="eppt_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        project_entity_id=PROJECT_A,
        participant_entity_id=PARTICIPANT_A,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": PARTICIPANT_A},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_project_participations"),  # noqa: S608
            ).scalar_one()
            == 0
        )


# --- seeded taxonomy rows ---------------------------------------------------------


@pytest.mark.database
def test_the_seeded_role_types_exist_and_are_queryable(migrated_engine: Engine) -> None:
    """Spot-check a handful of the exact codes from the migration's
    `_SEED_ROLE_TYPES` tuple."""
    with migrated_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(f"SELECT role_code, label FROM {SCHEMA}.entity_role_types"),  # noqa: S608
            ).all()
        )
    assert rows["OWNER"] == "Owner"
    assert rows["OWNER_REPRESENTATIVE"] == "Owner's Representative"
    assert rows["GENERAL_CONTRACTOR"] == "General Contractor"
    assert rows["CONSULTANT"] == "Consultant"
    assert rows["ARCHITECT_OF_RECORD"] == "Architect of Record"


@pytest.mark.database
def test_the_seeded_discipline_types_exist_and_are_queryable(migrated_engine: Engine) -> None:
    """Spot-check a handful of the exact codes from the migration's
    `_SEED_DISCIPLINE_TYPES` tuple."""
    with migrated_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(f"SELECT discipline_code, label FROM {SCHEMA}.entity_discipline_types"),  # noqa: S608
            ).all()
        )
    assert rows["CIVIL_ENGINEERING"] == "Civil Engineering"
    assert rows["STRUCTURAL_ENGINEERING"] == "Structural Engineering"
    assert rows["ARCHITECTURE"] == "Architecture"
    assert rows["GEOTECHNICAL_ENGINEERING"] == "Geotechnical Engineering"
