"""Revision `8dc3619891bb` against a real PostgreSQL server (RI-ENT-WP-06a).

Closes `ENTITY-REL-001`. Follows the pattern
`tests/schema/test_person_organization_affiliations_migration.py` established
for the prior revision on this chain: the revision sits alone on the chain,
empty-to-head and head-to-`17149a48fa30` leave no residue outside the one
table this revision adds, every hand-written constraint name in the migration
matches the declaration in `tables.py` (the cost of `D-48`/`D-69`, paid
rather than described), and each CHECK actually rejects the row it names.

`tests/unit/test_relationship_type_taxonomy_domain.py` proves
`RelationshipTypeTaxonomyEntry` refuses a bad value in the dataclass. This
proves the *server* refuses it too -- including every one of the fifteen
pre-existing `relationship_type` codes still being accepted after the CHECK
is replaced by a foreign key (one assertion per code, not a loop that could
silently skip one), each of the twenty new codes being accepted, an unknown
code being refused, and the downgrade restoring the original CHECK without
orphaning any row.
"""

from __future__ import annotations

import ast
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

REVISION: Final = "8dc3619891bb"
PREVIOUS_REVISION: Final = "17149a48fa30"

NEW_TABLES: Final = frozenset({"entity_relationship_types"})

DISPOSABLE_DATABASE: Final = "my_pa_entity_relationship_types_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY_A: Final = "ent_aaaa0001aaaa0001"
ENTITY_B: Final = "ent_bbbb0002bbbb0002"
ENTITY_C: Final = "ent_cccc0003cccc0003"

#: The fifteen pre-existing `EntityRelationshipType` codes, restated (not
#: imported) so this list cannot silently drift from what the migration
#: seeds first -- the same discipline `_RELATIONSHIP_TYPE_VALUES` follows in
#: the migration itself.
EXISTING_CODES: Final = (
    "works_for",
    "reports_to",
    "represents",
    "manages",
    "leads",
    "responsible_for",
    "approver_for",
    "decision_maker_for",
    "primary_contact_for",
    "member_of",
    "consultant_to",
    "contractor_on",
    "subcontractor_to",
    "vendor_for",
    "affiliated_with",
)

#: The twenty codes `8dc3619891bb` (this revision) originally seeded, restated
#: verbatim from its own `_NEW_CODES` tuple except for `design_coordinates_with`,
#: which migration `c99cd8ed8d1c` (RI-ENT-WP-08 blocker-clearing pass, later in
#: this chain) renamed to `design_coordination_with`. `migrated_engine` below
#: upgrades to the chain's true head, not to this file's own `REVISION` alone,
#: so this list has to state the code's *current* (post-rename) value or the
#: parametrized tests further down -- which insert live rows against a
#: head-migrated database -- would fail the foreign key this revision installs.
NEW_CODES: Final = (
    "brand_of",
    "operates_as",
    "dba_of",
    "historical_identity_of",
    "parent_of",
    "subsidiary_of",
    "acquired_by",
    "practice_of",
    "contracting_entity_for",
    "managed_by",
    "owner_representative_for",
    "project_controls_advisor_to",
    "technical_reviewer_of",
    "peer_reviewer_of",
    "design_coordination_with",
    "utility_provider_for",
    "permitting_authority_for",
    "seller_developer_for",
    "sales_marketing_agent_for",
    "sequence_interfaces_with",
)


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


def _constraint_def(engine: Engine, table: str, constraint: str) -> str | None:
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "JOIN pg_namespace n ON t.relnamespace = n.oid "
                "WHERE n.nspname = :schema AND t.relname = :table AND c.conname = :constraint"
            ),
            {"schema": SCHEMA, "table": table, "constraint": constraint},
        ).scalar_one_or_none()


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
                "name": f"synthetic entity {entity_id}",
            },
        )


def _insert_relationship(
    engine: Engine,
    *,
    relationship_id: str,
    from_entity_id: str,
    to_entity_id: str,
    relationship_type: str,
    principal_id: str = PRINCIPAL_A,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, to_entity_id, relationship_type, "
                "principal_id) VALUES "
                "(:relationship_id, :from_entity_id, :to_entity_id, :relationship_type, "
                ":principal_id)"
            ),
            {
                "relationship_id": relationship_id,
                "from_entity_id": from_entity_id,
                "to_entity_id": to_entity_id,
                "relationship_type": relationship_type,
                "principal_id": principal_id,
            },
        )


# --- chain position (no database) -------------------------------------------


def test_the_revision_is_in_the_chain_on_the_prior_head() -> None:
    """One head, and this revision revises the campaign's prior head exactly.

    `REVISION` is no longer necessarily the chain's head: RI-ENT-WP-06b
    (`9a3f6c1e8d24`) stacked on top of it. This test's own name only ever
    promised "in the chain on the prior head", not "is the head" -- that is
    what the single-head and down-revision assertions below check; whether
    `REVISION` is currently the head is a separate, narrower fact this test
    does not own.
    """
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
def test_downgrading_one_step_removes_exactly_this_table_and_restores_the_original_check(
    migrated_engine: Engine,
) -> None:
    """Additive: everything below this revision is untouched by its downgrade,
    and the original `9def3c2e63bb` CHECK is restored verbatim."""
    before = _tables(migrated_engine)
    assert before >= NEW_TABLES
    assert "an_entity_relationship_type_is_seeded" in _constraint_names(
        migrated_engine, "entity_relationships"
    )

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    # `migrated_engine` upgrades to the chain's true head, which now sits above
    # REVISION: `1cda4d536268` (RI-ENT-WP-07) adds `entity_assertions`/
    # `entity_assertion_evidence` on top of `8dc3619891bb`, so downgrading all
    # the way to this file's own PREVIOUS_REVISION also unwinds that later
    # revision's two tables, not just this file's own one.
    assert before - after == {
        "entity_relationship_types",
        "entity_assertions",
        "entity_assertion_evidence",
    }
    # The rest of the entity plane survives the downgrade of this revision alone.
    assert {
        "entities",
        "entity_relationships",
        "entity_names",
        "entity_organization_profiles",
        "entity_addresses",
        "entity_communication_methods",
        "entity_project_participations",
        "entity_role_types",
        "entity_discipline_types",
        "entity_person_organization_affiliations",
    } <= after
    live_constraints = _constraint_names(migrated_engine, "entity_relationships")
    assert "an_entity_relationship_type_is_known" in live_constraints
    assert "an_entity_relationship_type_is_seeded" not in live_constraints
    restored = _constraint_def(
        migrated_engine, "entity_relationships", "an_entity_relationship_type_is_known"
    )
    assert restored is not None
    for code in EXISTING_CODES:
        assert f"'{code}'" in restored
    for code in NEW_CODES:
        assert f"'{code}'" not in restored


@pytest.mark.database
def test_downgrading_then_upgrading_again_is_clean(migrated_engine: Engine) -> None:
    """Downgrade one step, then upgrade back to head, without residue."""
    command.downgrade(_config(), PREVIOUS_REVISION)
    assert "entity_relationship_types" not in _tables(migrated_engine)

    command.upgrade(_config(), "head")
    assert _tables(migrated_engine) >= NEW_TABLES


@pytest.mark.database
def test_upgrading_from_the_previous_head_with_seeded_data_preserves_it(
    disposable_database: str,
) -> None:
    """`17149a48fa30` (WP-05) with pre-existing `entity_relationships` rows
    using OLD codes, upgraded to head, disturbs neither their count nor their
    values -- this revision's FK swap is purely additive over existing data.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        _seed_entity(engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
        _seed_entity(engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
        _seed_entity(engine, ENTITY_C, PRINCIPAL_A, entity_type="organization")
        _insert_relationship(
            engine,
            relationship_id="erel_aaaa0001aaaa0001",
            from_entity_id=ENTITY_A,
            to_entity_id=ENTITY_B,
            relationship_type="works_for",
        )
        _insert_relationship(
            engine,
            relationship_id="erel_bbbb0002bbbb0002",
            from_entity_id=ENTITY_B,
            to_entity_id=ENTITY_C,
            relationship_type="vendor_for",
        )

        command.upgrade(_config(), "head")

        assert _tables(engine) >= NEW_TABLES
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"SELECT relationship_id, relationship_type FROM "  # noqa: S608
                    f"{SCHEMA}.entity_relationships ORDER BY relationship_id"
                )
            ).all()
            taxonomy_count = connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_relationship_types")  # noqa: S608
            ).scalar_one()
        assert rows == [
            ("erel_aaaa0001aaaa0001", "works_for"),
            ("erel_bbbb0002bbbb0002", "vendor_for"),
        ]
        assert taxonomy_count == 35
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
def test_the_relationship_type_fk_exists_on_entity_relationships(
    migrated_engine: Engine,
) -> None:
    live = _constraint_names(migrated_engine, "entity_relationships")
    assert "an_entity_relationship_type_is_seeded" in live
    assert "an_entity_relationship_type_is_known" not in live


# --- the taxonomy is seeded with all thirty-five codes -------------------------


@pytest.mark.database
def test_the_taxonomy_table_holds_exactly_thirty_five_seeded_codes(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.connect() as connection:
        codes = set(
            connection.execute(
                text(
                    f"SELECT relationship_type_code FROM {SCHEMA}.entity_relationship_types"  # noqa: S608
                )
            ).scalars()
        )
    assert codes == set(EXISTING_CODES) | set(NEW_CODES)
    assert len(codes) == 35


@pytest.mark.database
def test_every_seeded_code_is_directed(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        undirected = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_relationship_types "  # noqa: S608
                "WHERE directed IS NOT TRUE"
            )
        ).scalar_one()
    assert undirected == 0


@pytest.mark.database
def test_the_two_definitional_inverse_pairs_are_wired(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        rows = dict(
            connection.execute(
                text(
                    f"SELECT relationship_type_code, inverse_type_code "  # noqa: S608
                    f"FROM {SCHEMA}.entity_relationship_types "
                    "WHERE relationship_type_code IN "
                    "('parent_of', 'subsidiary_of', 'manages', 'managed_by')"
                )
            ).all()
        )
    assert rows == {
        "parent_of": "subsidiary_of",
        "subsidiary_of": "parent_of",
        "manages": "managed_by",
        "managed_by": "manages",
    }


@pytest.mark.database
def test_an_unpaired_code_has_no_inverse(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        inverse = connection.execute(
            text(
                f"SELECT inverse_type_code FROM {SCHEMA}.entity_relationship_types "  # noqa: S608
                "WHERE relationship_type_code = 'technical_reviewer_of'"
            )
        ).scalar_one()
    assert inverse is None


# --- every one of the fifteen existing codes is still accepted -----------------
# One test function per code, deliberately, not a loop over a list -- a loop
# that silently skipped one code would still show green.


@pytest.mark.database
def test_the_server_still_accepts_works_for(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="works_for",
    )


@pytest.mark.database
def test_the_server_still_accepts_reports_to(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="person")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="reports_to",
    )


@pytest.mark.database
def test_the_server_still_accepts_represents(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="represents",
    )


@pytest.mark.database
def test_the_server_still_accepts_manages(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="manages",
    )


@pytest.mark.database
def test_the_server_still_accepts_leads(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="leads",
    )


@pytest.mark.database
def test_the_server_still_accepts_responsible_for(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="responsible_for",
    )


@pytest.mark.database
def test_the_server_still_accepts_approver_for(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="approver_for",
    )


@pytest.mark.database
def test_the_server_still_accepts_decision_maker_for(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="decision_maker_for",
    )


@pytest.mark.database
def test_the_server_still_accepts_primary_contact_for(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="primary_contact_for",
    )


@pytest.mark.database
def test_the_server_still_accepts_member_of(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="team_or_group")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="member_of",
    )


@pytest.mark.database
def test_the_server_still_accepts_consultant_to(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="consultant_to",
    )


@pytest.mark.database
def test_the_server_still_accepts_contractor_on(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="contractor_on",
    )


@pytest.mark.database
def test_the_server_still_accepts_subcontractor_to(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="subcontractor_to",
    )


@pytest.mark.database
def test_the_server_still_accepts_vendor_for(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="project")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="vendor_for",
    )


@pytest.mark.database
def test_the_server_still_accepts_affiliated_with(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="affiliated_with",
    )


def test_fifteen_existing_code_tests_cover_every_member_exactly_once() -> None:
    """Guards the fifteen tests above: proves the module actually defines one
    dedicated test per pre-existing code, not fourteen with a typo'd
    duplicate."""
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name.startswith("test_the_server_still_accepts_")
        and node.name != "test_the_server_still_accepts_all_new_codes"
    }
    covered = {name.removeprefix("test_the_server_still_accepts_") for name in names}
    assert covered == set(EXISTING_CODES)


# --- every one of the twenty new codes is accepted ------------------------------


@pytest.mark.database
@pytest.mark.parametrize("code", NEW_CODES)
def test_the_server_still_accepts_all_new_codes(migrated_engine: Engine, code: str) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type=code,
    )


# --- an unknown code is refused --------------------------------------------------


@pytest.mark.database
def test_an_unknown_relationship_type_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    with pytest.raises(IntegrityError, match="an_entity_relationship_type_is_seeded"):
        _insert_relationship(
            migrated_engine,
            relationship_id="erel_aaaa0001aaaa0001",
            from_entity_id=ENTITY_A,
            to_entity_id=ENTITY_B,
            relationship_type="made_up_relationship_type",
        )


# --- taxonomy-row CHECK constraints ----------------------------------------------


@pytest.mark.database
def test_a_relationship_type_code_outside_the_status_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    with (
        pytest.raises(IntegrityError, match="a_relationship_type_status_is_known"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationship_types "  # noqa: S608
                "(relationship_type_code, label, directed, status) VALUES "
                "('made_up_status_code', 'Made Up', true, 'pending')"
            )
        )


@pytest.mark.database
def test_a_relationship_type_source_entity_type_outside_the_closed_set_is_refused(
    migrated_engine: Engine,
) -> None:
    with (
        pytest.raises(IntegrityError, match="a_relationship_type_source_entity_type_is_known"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationship_types "  # noqa: S608
                "(relationship_type_code, label, directed, source_entity_type) VALUES "
                "('made_up_source_code', 'Made Up', true, 'project')"
            )
        )


@pytest.mark.database
def test_a_blank_relationship_type_label_is_refused(migrated_engine: Engine) -> None:
    with (
        pytest.raises(IntegrityError, match="a_relationship_type_label_is_not_blank"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationship_types "  # noqa: S608
                "(relationship_type_code, label, directed) VALUES "
                "('made_up_blank_label_code', '   ', true)"
            )
        )


@pytest.mark.database
def test_a_relationship_type_does_not_invert_itself_at_the_server(
    migrated_engine: Engine,
) -> None:
    with (
        pytest.raises(IntegrityError, match="a_relationship_type_does_not_invert_itself"),
        migrated_engine.begin() as connection,
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationship_types "  # noqa: S608
                "(relationship_type_code, label, directed, inverse_type_code) VALUES "
                "('made_up_self_inverse_code', 'Made Up', true, 'made_up_self_inverse_code')"
            )
        )


# --- downgrade does not orphan pre-existing-code data ---------------------------


@pytest.mark.database
def test_downgrade_with_only_pre_existing_code_data_restores_the_check_and_keeps_the_data(
    migrated_engine: Engine,
) -> None:
    """Seeds only pre-existing-code rows, downgrades, and proves the original
    fifteen-code CHECK is back with the data intact -- the case this revision
    promises to support without loss."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="person")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="works_for",
    )

    command.downgrade(_config(), PREVIOUS_REVISION)

    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT relationship_type FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE relationship_id = :rid"
            ),
            {"rid": "erel_aaaa0001aaaa0001"},
        ).one()
    assert row[0] == "works_for"
    live_constraints = _constraint_names(migrated_engine, "entity_relationships")
    assert "an_entity_relationship_type_is_known" in live_constraints
    assert "entity_relationship_types" not in _tables(migrated_engine)


@pytest.mark.database
def test_downgrade_correctly_refuses_when_a_new_code_row_exists(
    migrated_engine: Engine,
) -> None:
    """If a row uses one of the twenty new codes, the restored CHECK correctly
    refuses it and the downgrade aborts -- intended, safe behavior (the old
    schema cannot represent the new codes), not a bug. Proved as an
    IntegrityError during the downgrade transaction rather than assumed."""
    _seed_entity(migrated_engine, ENTITY_A, PRINCIPAL_A, entity_type="organization")
    _seed_entity(migrated_engine, ENTITY_B, PRINCIPAL_A, entity_type="organization")
    _insert_relationship(
        migrated_engine,
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY_A,
        to_entity_id=ENTITY_B,
        relationship_type="parent_of",
    )

    with pytest.raises(IntegrityError, match="an_entity_relationship_type_is_known"):
        command.downgrade(_config(), PREVIOUS_REVISION)


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
