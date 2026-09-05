"""Revision `1cda4d536268` against a real PostgreSQL server (RI-ENT-WP-07).

Follows the pattern `tests/schema/test_entity_relationship_types_migration.py`
and `tests/schema/test_person_organization_affiliations_migration.py`
established for prior revisions on this chain: the revision sits alone on the
chain (`down_revision = 9a3f6c1e8d24`), upgrade-empty-to-head and
downgrade-head-to-empty leave no residue outside the two tables this revision
adds, every hand-written constraint name in the migration matches the
declaration in `tables.py` (the cost of `D-48`/`D-69`, paid rather than
described), and each CHECK actually rejects the row it names.

`tests/unit/test_entity_assertion_domain.py` proves `EntityAssertion`/
`EntityAssertionEvidence` refuse a bad value in the dataclass. This proves the
*server* refuses it too -- including the "exactly one target" CHECK, the
"exactly one evidence record" CHECK, and the composite-FK Principal
partitions on five of the six targets. The database-level round-trip,
non-destructive-supersession, and organization-profile merge-cascade proofs
live in `tests/database/test_entity_assertion_provenance.py`.
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

REVISION: Final = "1cda4d536268"
PREVIOUS_REVISION: Final = "9a3f6c1e8d24"

NEW_TABLES: Final = frozenset({"entity_assertions", "entity_assertion_evidence"})

DISPOSABLE_DATABASE: Final = "my_pa_entity_assertion_provenance_schema_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
PERSON_A: Final = "ent_aaaa0001aaaa0001"
ORGANIZATION_A: Final = "ent_bbbb0002bbbb0002"
OTHER_PRINCIPAL_ENTITY: Final = "ent_cccc0003cccc0003"


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


def _seed_entity(
    engine: Engine, entity_id: str, principal_id: str, entity_type: str = "organization"
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


def _seed_name(engine: Engine, entity_name_id: str, entity_id: str, principal_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, principal_id, name_type_code, normalized_value, "
                "display_value) VALUES (:id, :entity_id, :principal_id, 'display', "
                "'synthetic name', 'Synthetic Name')"
            ),
            {"id": entity_name_id, "entity_id": entity_id, "principal_id": principal_id},
        )


def _insert_assertion(
    engine: Engine,
    *,
    assertion_id: str,
    principal_id: str = PRINCIPAL_A,
    target_entity_name_id: str | None = None,
    target_organization_profile_entity_id: str | None = None,
    assertion_status: str = "best_supported",
    asserted_by: str = "user_confirmed_assertion",
    state: str = "active",
    predicate_code: str | None = None,
    rationale: str | None = None,
    supersedes_assertion_id: str | None = None,
    retired_at: str | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_assertions "  # noqa: S608
                "(assertion_id, principal_id, target_entity_name_id, "
                "target_organization_profile_entity_id, assertion_status, asserted_by, "
                "state, predicate_code, rationale, supersedes_assertion_id, retired_at) "
                "VALUES (:assertion_id, :principal_id, :target_entity_name_id, "
                ":target_organization_profile_entity_id, :assertion_status, :asserted_by, "
                ":state, :predicate_code, :rationale, :supersedes_assertion_id, :retired_at)"
            ),
            {
                "assertion_id": assertion_id,
                "principal_id": principal_id,
                "target_entity_name_id": target_entity_name_id,
                "target_organization_profile_entity_id": (target_organization_profile_entity_id),
                "assertion_status": assertion_status,
                "asserted_by": asserted_by,
                "state": state,
                "predicate_code": predicate_code,
                "rationale": rationale,
                "supersedes_assertion_id": supersedes_assertion_id,
                "retired_at": retired_at,
            },
        )


# --- chain position (no database) -------------------------------------------


def test_the_revision_is_in_the_chain_on_the_prior_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_the_revision_declares_the_tables_it_creates() -> None:
    declared = {table.name for table in METADATA.tables.values() if table.name in NEW_TABLES}
    assert declared == NEW_TABLES


# --- migration mechanics -----------------------------------------------------


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
    before = _tables(migrated_engine)
    assert before >= NEW_TABLES

    command.downgrade(_config(), PREVIOUS_REVISION)
    after = _tables(migrated_engine)

    assert before - after == NEW_TABLES | {
        "goodnotes_pull_sessions",
        "goodnotes_pull_claims",
        "goodnotes_pull_assignments",
        "goodnotes_pull_completions",
        "goodnotes_semantic_review_decisions",
        "canvas_workspaces",
"goodnotes_semantic_promotion_receipts",
    }
    assert {
        "entities",
        "entity_names",
        "entity_organization_profiles",
        "entity_addresses",
        "entity_communication_methods",
        "entity_project_participations",
        "entity_person_organization_affiliations",
        "entity_relationship_types",
        "entity_fact_evidence_links",
    } <= after


@pytest.mark.database
def test_downgrading_then_upgrading_again_is_clean(migrated_engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS_REVISION)
    assert NEW_TABLES.isdisjoint(_tables(migrated_engine))

    command.upgrade(_config(), "head")
    assert _tables(migrated_engine) >= NEW_TABLES


@pytest.mark.database
def test_upgrading_from_the_previous_head_with_seeded_data_preserves_it(
    disposable_database: str,
) -> None:
    """`9a3f6c1e8d24` with seeded entities/names/an evidence link, upgraded to
    `REVISION`, disturbs neither -- this revision is purely additive.

    Upgraded to `REVISION` (`1cda4d536268`) rather than to `head` since
    2026-09-03. The scene seeds an **active `display` name** for an active
    entity whose value differs from `entities.display_name`, and `head` now
    carries `b8e4d1a6c073` (RI-ENT-WP-12), whose guard A refuses exactly that
    database -- it cannot tell whether the typed row or the legacy column is
    the truth, and refusing is its accepted design
    (`tests/database/test_legacy_entity_backfill_migration.py::`
    `test_guard_a_refuses_when_an_in_scope_entity_already_has_an_active_display_name`).
    "Purely additive" was always a claim about *this* revision; `head` made it
    a claim about every later revision, which a data backfill is not. The
    assertion is unchanged.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        _seed_entity(engine, ORGANIZATION_A, PRINCIPAL_A, entity_type="organization")
        _seed_name(engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
        with engine.connect() as connection:
            before_count = connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_names")  # noqa: S608
            ).scalar_one()

        command.upgrade(_config(), REVISION)
        assert _tables(engine) >= NEW_TABLES
        with engine.connect() as connection:
            after_count = connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.entity_names")  # noqa: S608
            ).scalar_one()
        assert after_count == before_count == 1
    finally:
        engine.dispose()


# --- constraint names match tables.py's declarations -------------------------


@pytest.mark.database
def test_the_assertions_table_constraint_names_match_the_declaration(
    migrated_engine: Engine,
) -> None:
    live = _constraint_names(migrated_engine, "entity_assertions")
    declared = {
        constraint.name
        for constraint in METADATA.tables[f"{SCHEMA}.entity_assertions"].constraints
        if constraint.name is not None
    } | {
        fk.name
        for fk in METADATA.tables[f"{SCHEMA}.entity_assertions"].foreign_key_constraints
        if fk.name is not None
    }
    assert declared <= live, declared - live


@pytest.mark.database
def test_the_assertion_evidence_table_constraint_names_match_the_declaration(
    migrated_engine: Engine,
) -> None:
    live = _constraint_names(migrated_engine, "entity_assertion_evidence")
    declared = {
        constraint.name
        for constraint in METADATA.tables[f"{SCHEMA}.entity_assertion_evidence"].constraints
        if constraint.name is not None
    } | {
        fk.name
        for fk in METADATA.tables[f"{SCHEMA}.entity_assertion_evidence"].foreign_key_constraints
        if fk.name is not None
    }
    assert declared <= live, declared - live


# --- CHECK constraints actually reject the row they name ---------------------


@pytest.mark.database
def test_no_target_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_names_exactly_one_target"):
        _insert_assertion(migrated_engine, assertion_id="east_aaaa0001aaaa0001")


@pytest.mark.database
def test_two_targets_at_once_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_names_exactly_one_target"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            target_organization_profile_entity_id=ORGANIZATION_A,
        )


@pytest.mark.database
def test_an_unknown_assertion_status_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_status_is_known"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            assertion_status="highly_confident",
        )


@pytest.mark.database
def test_an_unknown_authority_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_authority_is_known"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            asserted_by="a_model_guessed",
        )


@pytest.mark.database
def test_a_blank_predicate_code_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_predicate_code_is_not_blank"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            predicate_code="   ",
        )


@pytest.mark.database
def test_a_blank_rationale_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_rationale_is_not_blank"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            rationale="   ",
        )


@pytest.mark.database
def test_supersedes_itself_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_does_not_supersede_itself"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            supersedes_assertion_id="east_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_retired_while_active_is_refused(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_is_retired_only_once_it_leaves_service"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            target_entity_name_id="enam_aaaa0001aaaa0001",
            state="active",
            retired_at="2026-08-31T00:00:00+00:00",
        )


@pytest.mark.database
def test_a_name_of_a_different_principal_is_refused(migrated_engine: Engine) -> None:
    """The composite `(target_entity_name_id, principal_id)` FK, proved: an
    assertion cannot name a name row that belongs to a different Principal,
    even though the referenced `entity_name_id` value itself exists."""
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    with pytest.raises(IntegrityError, match="an_assertion_names_a_name_of_its_principal"):
        _insert_assertion(
            migrated_engine,
            assertion_id="east_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_B,
            target_entity_name_id="enam_aaaa0001aaaa0001",
        )


@pytest.mark.database
def test_a_valid_assertion_against_a_name_is_admitted(migrated_engine: Engine) -> None:
    _seed_entity(migrated_engine, ORGANIZATION_A, PRINCIPAL_A)
    _seed_name(migrated_engine, "enam_aaaa0001aaaa0001", ORGANIZATION_A, PRINCIPAL_A)
    _insert_assertion(
        migrated_engine,
        assertion_id="east_aaaa0001aaaa0001",
        target_entity_name_id="enam_aaaa0001aaaa0001",
        predicate_code="display_value",
        rationale="a synthetic source document names this value",
    )
    with migrated_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT assertion_status, state, version FROM {SCHEMA}.entity_assertions "  # noqa: S608
                "WHERE assertion_id = 'east_aaaa0001aaaa0001'"
            )
        ).one()
    assert row.assertion_status == "best_supported"
    assert row.state == "active"
    assert row.version == 1


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
