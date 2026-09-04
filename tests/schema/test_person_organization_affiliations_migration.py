"""Revision `17149a48fa30` against a real PostgreSQL server.

RI-ENT-WP-05. Follows the pattern
`tests/schema/test_entity_project_participations_migration.py` established
for the prior revision on this chain: the revision sits alone on the chain,
empty-to-head and head-to-`f5b06925857e` leave no residue outside the one
table this revision adds, every hand-written constraint name in the migration
matches the declaration in `tables.py` (the cost of `D-48`/`D-69`, paid
rather than described), and each CHECK actually rejects the row it names.

`tests/unit/test_person_organization_affiliation_domain.py` proves
`PersonOrganizationAffiliation` refuses a bad value in the dataclass. This
proves the *server* refuses it too -- including both composite-FK Principal
partitions, the nullable `organization_entity_id`, and the partial unique
index that makes "current" unambiguous per person.
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
from sqlalchemy.exc import IntegrityError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import METADATA

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

REVISION: Final = "17149a48fa30"
PREVIOUS_REVISION: Final = "f5b06925857e"

NEW_TABLES: Final = frozenset({"entity_person_organization_affiliations"})

DISPOSABLE_DATABASE: Final = "my_pa_person_organization_affiliations_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
PERSON_A: Final = "ent_aaaa0001aaaa0001"
PERSON_B: Final = "ent_bbbb0002bbbb0002"
ORGANIZATION_A: Final = "ent_cccc0003cccc0003"
ORGANIZATION_B: Final = "ent_dddd0004dddd0004"
OTHER_PRINCIPAL_ENTITY: Final = "ent_eeee0005eeee0005"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


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
    entity_type: str = "person",
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


def _insert_affiliation(
    engine: Engine,
    *,
    affiliation_id: str,
    principal_id: str,
    person_entity_id: str,
    organization_entity_id: str | None,
    job_title: str | None = "Project Executive",
    affiliation_type_code: str = "employment",
    effective_from: str | None = None,
    effective_to: str | None = None,
    state: str = "active",
    retired_at: str | None = None,
    superseded_by_affiliation_id: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_person_organization_affiliations "  # noqa: S608
                "(affiliation_id, principal_id, person_entity_id, organization_entity_id, "
                "job_title, affiliation_type_code, effective_from, effective_to, state, "
                "retired_at, superseded_by_affiliation_id) VALUES "
                "(:affiliation_id, :principal_id, :person_entity_id, :organization_entity_id, "
                ":job_title, :affiliation_type_code, :effective_from, :effective_to, :state, "
                ":retired_at, :superseded_by_affiliation_id)"
            ),
            {
                "affiliation_id": affiliation_id,
                "principal_id": principal_id,
                "person_entity_id": person_entity_id,
                "organization_entity_id": organization_entity_id,
                "job_title": job_title,
                "affiliation_type_code": affiliation_type_code,
                "effective_from": effective_from,
                "effective_to": effective_to,
                "state": state,
                "retired_at": retired_at,
                "superseded_by_affiliation_id": superseded_by_affiliation_id,
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
def test_downgrading_one_step_removes_exactly_this_table(migrated_engine: Engine) -> None:
    """Additive: everything below this revision is untouched by its downgrade.

    Steps down to `REVISION` itself first, following the pattern
    `test_entity_project_participations_migration.py` established for the
    same reason: `migrated_engine` upgrades to the chain's true head, which
    may now sit above `REVISION` -- `8dc3619891bb` (RI-ENT-WP-06a) does. This
    test's subject is specifically *this* revision's own downgrade, one step
    below it, not one step below whatever the chain's head happens to be
    today.
    """
    command.downgrade(_config(), REVISION)
    before = _tables(migrated_engine)
    assert before >= NEW_TABLES

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    assert before - after == {"entity_person_organization_affiliations"}
    # The rest of the entity plane, including WP-04's tables, survives the
    # downgrade of this revision alone.
    assert {
        "entities",
        "entity_names",
        "entity_organization_profiles",
        "entity_addresses",
        "entity_communication_methods",
        "entity_project_participations",
        "entity_role_types",
        "entity_discipline_types",
    } <= after


@pytest.mark.database
def test_downgrading_then_upgrading_again_is_clean(migrated_engine: Engine) -> None:
    """Downgrade one step, then upgrade back to head, without residue."""
    command.downgrade(_config(), PREVIOUS_REVISION)
    assert "entity_person_organization_affiliations" not in _tables(migrated_engine)

    command.upgrade(_config(), "head")
    assert _tables(migrated_engine) >= NEW_TABLES


@pytest.mark.database
def test_upgrading_from_the_previous_head_with_seeded_data_preserves_it(
    disposable_database: str,
) -> None:
    """`f5b06925857e` (WP-04) with a seeded person entity, an organization
    entity, and an existing project-participation row, upgraded to head,
    disturbs neither -- this revision is purely additive."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        _seed_entity(engine, PERSON_A, PRINCIPAL_A, entity_type="person")
        _seed_entity(engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
        project = "ent_ffff0006ffff0006"
        _seed_entity(engine, project, PRINCIPAL_A, entity_type="project")
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                    "(participation_id, principal_id, project_entity_id, "
                    "participant_entity_id, project_display_name, role_basis_code, "
                    "stakeholder_side_code, stakeholder_class_code, relationship_status_code) "
                    "VALUES ('eppt_aaaa0001aaaa0001', :principal_id, :project_entity_id, "
                    ":participant_entity_id, 'Larkspur Commons', 'contractual', "
                    "'consultant', 'core', 'active')"
                ),
                {
                    "principal_id": PRINCIPAL_A,
                    "project_entity_id": project,
                    "participant_entity_id": PERSON_A,
                },
            )

        command.upgrade(_config(), "head")

        assert _tables(engine) >= NEW_TABLES
        # Confirm entities and the pre-existing participation row survived,
        # and a new affiliation row can now reference the same person.
        _insert_affiliation(
            engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
        )
        with engine.connect() as connection:
            preserved_participation = connection.execute(
                text(
                    f"SELECT participant_entity_id FROM "  # noqa: S608
                    f"{SCHEMA}.entity_project_participations WHERE participation_id = :pid"
                ),
                {"pid": "eppt_aaaa0001aaaa0001"},
            ).scalar_one()
            affiliation_row = connection.execute(
                text(
                    f"SELECT person_entity_id, organization_entity_id FROM "  # noqa: S608
                    f"{SCHEMA}.entity_person_organization_affiliations "
                    "WHERE affiliation_id = :aid"
                ),
                {"aid": "poaf_aaaa0001aaaa0001"},
            ).one()
        assert preserved_participation == PERSON_A
        assert affiliation_row == (PERSON_A, ORGANIZATION_A)
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
def test_the_expected_indexes_exist_on_the_affiliations_table(
    migrated_engine: Engine,
) -> None:
    assert {
        "entity_person_organization_affiliations_by_principal",
        "entity_person_organization_affiliations_by_person_state",
        "an_open_ended_affiliation_is_unique_per_person",
    } <= _index_names(migrated_engine, "entity_person_organization_affiliations")


# --- CHECK constraints ----------------------------------------------------------


@pytest.mark.database
def test_an_affiliation_type_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            affiliation_type_code="primary_employer",
        )


@pytest.mark.database
def test_an_affiliation_state_outside_the_closed_set_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            state="pending",
        )


@pytest.mark.database
def test_a_blank_job_title_is_refused_when_present(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            job_title="   ",
        )


@pytest.mark.database
def test_effective_to_before_effective_from_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            effective_from="2026-06-01",
            effective_to="2026-01-01",
        )


@pytest.mark.database
def test_an_organization_cannot_be_the_person_itself_at_the_server(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=PERSON_A,
        )


# --- the nullable organization, at the database ---------------------------------


@pytest.mark.database
def test_a_null_organization_persists_and_round_trips(migrated_engine: Engine) -> None:
    """No NOT NULL constraint or trigger rejects `organization_entity_id IS
    NULL` -- the independent-consultant case, proved at the server."""
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=None,
        affiliation_type_code="independent_consultant",
        job_title="Independent Consultant",
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT organization_entity_id, affiliation_type_code, job_title "  # noqa: S608
                f"FROM {SCHEMA}.entity_person_organization_affiliations "
                "WHERE affiliation_id = :aid"
            ),
            {"aid": "poaf_aaaa0001aaaa0001"},
        ).one()
    assert row == (None, "independent_consultant", "Independent Consultant")


# --- supersession rules ---------------------------------------------------------


@pytest.mark.database
def test_a_superseded_by_reference_requires_the_superseded_state(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
        effective_to="2020-01-01",
    )
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_bbbb0002bbbb0002",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            effective_to="2019-01-01",
            state="active",
            superseded_by_affiliation_id="poaf_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_an_affiliation_cannot_supersede_itself_at_the_server(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            state="superseded",
            superseded_by_affiliation_id="poaf_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_a_superseded_affiliation_resolves_to_its_successor_within_the_same_principal(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
        job_title="Corrected Title",
    )
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
        job_title="Wrong Title",
        state="superseded",
        superseded_by_affiliation_id="poaf_bbbb0002bbbb0002",
    )
    with migrated_engine.connect() as connection:
        successor = connection.execute(
            text(
                f"SELECT successor.affiliation_id, successor.job_title "  # noqa: S608
                f"FROM {SCHEMA}.entity_person_organization_affiliations predecessor "
                f"JOIN {SCHEMA}.entity_person_organization_affiliations successor "
                "ON successor.affiliation_id = predecessor.superseded_by_affiliation_id "
                "AND successor.principal_id = predecessor.principal_id "
                "WHERE predecessor.affiliation_id = :predecessor_id"
            ),
            {"predecessor_id": "poaf_aaaa0001aaaa0001"},
        ).one()
    assert successor[0] == "poaf_bbbb0002bbbb0002"
    assert successor[1] == "Corrected Title"


@pytest.mark.database
def test_an_affiliation_supersession_cannot_cross_principals(migrated_engine: Engine) -> None:
    """Cross-Principal-binding-must-fail: the self-referencing FK is
    `(superseded_by_affiliation_id, principal_id)`."""
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, PERSON_B, PRINCIPAL_B, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_B, PRINCIPAL_B, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_B,
        person_entity_id=PERSON_B,
        organization_entity_id=ORGANIZATION_B,
        job_title="Other principal's affiliation",
    )
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
            state="superseded",
            superseded_by_affiliation_id="poaf_bbbb0002bbbb0002",
        )


# --- cross-Principal binds: the composite FK on both entity references -------


@pytest.mark.database
def test_an_affiliation_cannot_bind_a_person_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    """Principal partitioning: the composite FK on `person_entity_id`
    refuses a cross-Principal bind."""
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_B, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_A,
        )


@pytest.mark.database
def test_an_affiliation_cannot_bind_an_organization_of_a_different_principal(
    migrated_engine: Engine,
) -> None:
    """Principal partitioning: the composite FK on `organization_entity_id`
    refuses a cross-Principal bind."""
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, OTHER_PRINCIPAL_ENTITY, PRINCIPAL_B, entity_type="organization")
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=OTHER_PRINCIPAL_ENTITY,
        )


@pytest.mark.database
def test_an_affiliation_supersession_cross_principal_bind_is_refused_by_the_composite_fk(
    migrated_engine: Engine,
) -> None:
    """A third, explicit cross-Principal-binding-must-fail test for the
    self-referencing supersession FK, distinct from the "resolves within the
    same principal" behavioural test above: this one targets the composite FK
    directly with a row that would otherwise be perfectly well-formed."""
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, PERSON_B, PRINCIPAL_B, entity_type="person")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_B,
        person_entity_id=PERSON_B,
        organization_entity_id=None,
        affiliation_type_code="independent_consultant",
    )
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=None,
            affiliation_type_code="independent_consultant",
            state="superseded",
            superseded_by_affiliation_id="poaf_bbbb0002bbbb0002",
        )


# --- the "at most one open-ended affiliation per person" partial unique -------


@pytest.mark.database
def test_a_second_open_ended_affiliation_for_the_same_person_is_refused(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ORGANIZATION_B, PRINCIPAL_A, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
        effective_to=None,
    )
    with pytest.raises(IntegrityError):
        _insert_affiliation(
            migrated_engine,
            affiliation_id="poaf_bbbb0002bbbb0002",
            principal_id=PRINCIPAL_A,
            person_entity_id=PERSON_A,
            organization_entity_id=ORGANIZATION_B,
            effective_to=None,
        )


@pytest.mark.database
def test_a_second_closed_affiliation_for_the_same_person_is_accepted(
    migrated_engine: Engine,
) -> None:
    """A second, already-closed (non-null `effective_to`) affiliation for the
    same person freely coexists as history -- the partial index does not
    reach it."""
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ORGANIZATION_B, PRINCIPAL_A, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
        effective_to="2019-01-01",
    )
    # A second, open-ended (current) affiliation succeeds alongside the
    # first, already-closed one.
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_bbbb0002bbbb0002",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_B,
        effective_to=None,
    )
    with migrated_engine.connect() as connection:
        rows = connection.execute(
            text(
                f"SELECT organization_entity_id, effective_to FROM "  # noqa: S608
                f"{SCHEMA}.entity_person_organization_affiliations "
                "WHERE person_entity_id = :person_entity_id ORDER BY affiliation_id"
            ),
            {"person_entity_id": PERSON_A},
        ).all()
    assert {row[0] for row in rows} == {ORGANIZATION_A, ORGANIZATION_B}


# --- cascading delete ------------------------------------------------------------


@pytest.mark.database
def test_deleting_the_person_entity_cascades_to_its_affiliation_rows(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": PERSON_A},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.entity_person_organization_affiliations"  # noqa: S608
                ),
            ).scalar_one()
            == 0
        )


@pytest.mark.database
def test_deleting_the_organization_entity_cascades_to_its_affiliation_rows(
    migrated_engine: Engine,
) -> None:
    _seed_entity(migrated_engine, PERSON_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
    _insert_affiliation(
        migrated_engine,
        affiliation_id="poaf_aaaa0001aaaa0001",
        principal_id=PRINCIPAL_A,
        person_entity_id=PERSON_A,
        organization_entity_id=ORGANIZATION_A,
    )
    with migrated_engine.begin() as connection:
        connection.execute(
            text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
            {"entity_id": ORGANIZATION_A},
        )
    with migrated_engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.entity_person_organization_affiliations"  # noqa: S608
                ),
            ).scalar_one()
            == 0
        )


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
