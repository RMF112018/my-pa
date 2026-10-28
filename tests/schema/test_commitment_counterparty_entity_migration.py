"""`5c1e7a9b3d42`: a Commitment's counterparty is an Entity, not a Person.

The revision drops `knowledge.commitments.counterparty_person_id` and its CHECK
and adds `counterparty_entity_id text NOT NULL` with the `ent_` CHECK, the
composite foreign key onto `entities (entity_id, principal_id)` and a lookup
index. There is no backfill: both directions refuse with `restrict_violation`,
changing nothing, while any Commitment row exists. On an empty table the
downgrade restores the Person column and its CHECK exactly.
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
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import commitments

ROOT: Final = Path(__file__).resolve().parents[2]
VERSIONS: Final = ROOT / "migrations" / "versions"
REVISION: Final = "5c1e7a9b3d42"
PREVIOUS: Final = "c8f7ae406d47"
#: `b9025e7fb738` (WP-MCP-PROJ-05, legacy Project-Entity bridge reconciliation)
#: is additive directly on this revision, and `264310e0416a` (record lineage S1)
#: on that; the latter is now the chain's sole head.
HEAD: Final = "6c2306330ceb"
MIGRATION: Final = VERSIONS / "20261014_5c1e7a9b3d42_commitment_counterparty_entity.py"
RESTRICT_VIOLATION: Final = "23001"
FOREIGN_KEY_VIOLATION: Final = "23503"

PRINCIPAL: Final = "prn_cptymig0001cptymig0001"
OTHER_PRINCIPAL: Final = "prn_cptymig0002cptymig0002"
ENTITY: Final = "ent_cptymig0001cptymig0001"

#: `pg_get_constraintdef` of every counterparty constraint, before and at.
BEFORE: Final = {
    "counterparty_person_id_is_an_opaque_identifier": (
        "CHECK ((counterparty_person_id ~ '^per_[A-Za-z0-9]{8,64}$'::text))"
    ),
}
AT: Final = {
    "counterparty_entity_id_is_an_opaque_identifier": (
        "CHECK ((counterparty_entity_id ~ '^ent_[A-Za-z0-9]{8,64}$'::text))"
    ),
    "a_commitment_counterparty_is_an_entity_of_its_principal": (
        "FOREIGN KEY (counterparty_entity_id, principal_id) "
        "REFERENCES knowledge.entities(entity_id, principal_id)"
    ),
}
INDEX_AT: Final = (
    "CREATE INDEX commitments_by_counterparty_entity ON knowledge.commitments "
    "USING btree (counterparty_entity_id)"
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


# ---- FAST: the graph, the freeze and the declaration --------------------------------


def test_the_revision_is_the_single_head_directly_on_the_mcp_interaction_log() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == "023f8f7eb499"
    assert script.get_revision("c5260943d933").down_revision == "6f1476b8da52"
    assert script.get_revision("6f1476b8da52").down_revision == "d020b532ad7d"
    assert script.get_revision("d020b532ad7d").down_revision == "264310e0416a"
    assert script.get_revision("264310e0416a").down_revision == "b9025e7fb738"
    assert script.get_revision("b9025e7fb738").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == "a591b81f10a2"
    assert [path.name for path in VERSIONS.glob(f"*_{REVISION}_*.py")] == [MIGRATION.name]


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    """`D-48`/`D-69`: every literal is frozen text, never derived from an enum."""
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing", "collections.abc"}
    assert "my_pa" not in source
    code = source.split('"""', 2)[2].upper()
    for statement in ("DELETE FROM", "UPDATE {SCHEMA}", "UPDATE KNOWLEDGE", "GRANT ", "TRUNCATE"):
        assert statement not in code


def test_the_declaration_names_the_entity_column_and_not_the_person_one() -> None:
    assert "counterparty_entity_id" in commitments.c
    assert "counterparty_person_id" not in commitments.c
    assert not commitments.c.counterparty_entity_id.nullable
    (foreign_key,) = [
        constraint
        for constraint in commitments.foreign_key_constraints
        if constraint.name == "a_commitment_counterparty_is_an_entity_of_its_principal"
    ]
    assert [column.name for column in foreign_key.columns] == [
        "counterparty_entity_id",
        "principal_id",
    ]
    assert [element.target_fullname for element in foreign_key.elements] == [
        "knowledge.entities.entity_id",
        "knowledge.entities.principal_id",
    ]
    assert "commitments_by_counterparty_entity" in {index.name for index in commitments.indexes}


# ---- DATABASE: the round trip and both refusals -------------------------------------


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _constraints(engine: Engine) -> dict[str, str]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'knowledge.commitments'::regclass "
                "AND conname LIKE ANY (ARRAY['counterparty%', 'a_commitment_counterparty%'])"
            )
        ).all()
    return {str(name): str(definition) for name, definition in rows}


def _index(engine: Engine) -> str | None:
    with engine.connect() as connection:
        found = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'commitments_by_counterparty_entity'"
            )
        ).scalar_one_or_none()
    return None if found is None else str(found)


def _count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text("SELECT count(*) FROM knowledge.commitments")).scalar_one()
        )


def _insert_commitment(engine: Engine, column: str, counterparty: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.commitments (commitment_id, principal_id, "  # noqa: S608
                f"{column}, direction, summary, origin_evidence_ref, opened_at, "
                "created_at, updated_at) VALUES ('cmt_cptymig0001cptymig0001', "
                ":principal_id, :counterparty, 'owed_by_principal', 'Synthetic', "
                "'cap_cptymig0001cptymig0001', now(), now(), now())"
            ),
            {"principal_id": PRINCIPAL, "counterparty": counterparty},
        )


def _insert_entity(engine: Engine, principal_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.entities (entity_id, principal_id, entity_type, "
                "canonical_name, display_name, status, created_at, updated_at, version) "
                "VALUES (:entity_id, :principal_id, 'organization', 'synthetic ltd', "
                "'Synthetic Ltd', 'active', now(), now(), 1)"
            ),
            {"entity_id": ENTITY, "principal_id": principal_id},
        )


@pytest.mark.database
@pytest.mark.migration_edge
def test_a_clean_downgrade_restores_the_person_column_exactly_and_upgrades_again(
    engine: Engine,
) -> None:
    command.upgrade(_config(), PREVIOUS)
    assert _constraints(engine) == BEFORE
    assert _index(engine) is None
    command.upgrade(_config(), REVISION)
    assert _constraints(engine) == AT
    assert _index(engine) == INDEX_AT
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    assert _constraints(engine) == BEFORE
    assert _index(engine) is None
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    assert _constraints(engine) == AT


@pytest.mark.database
@pytest.mark.migration_edge
def test_the_upgrade_refuses_while_any_person_commitment_exists(engine: Engine) -> None:
    command.upgrade(_config(), PREVIOUS)
    _insert_commitment(engine, "counterparty_person_id", "per_cptymig0001cptymig0001")
    with pytest.raises(DBAPIError) as refused:
        command.upgrade(_config(), REVISION)
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION
    assert _version(engine) == PREVIOUS
    assert _constraints(engine) == BEFORE
    assert _count(engine) == 1


@pytest.mark.database
def test_the_downgrade_refuses_while_any_entity_commitment_exists(engine: Engine) -> None:
    command.upgrade(_config(), "head")
    _insert_entity(engine, PRINCIPAL)
    _insert_commitment(engine, "counterparty_entity_id", ENTITY)
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION
    assert _version(engine) == REVISION
    assert _constraints(engine) == AT
    assert _count(engine) == 1


@pytest.mark.database
def test_the_foreign_key_refuses_an_absent_or_another_principals_entity(engine: Engine) -> None:
    command.upgrade(_config(), "head")
    with pytest.raises(DBAPIError) as absent:
        _insert_commitment(engine, "counterparty_entity_id", ENTITY)
    assert getattr(absent.value.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION
    _insert_entity(engine, OTHER_PRINCIPAL)
    with pytest.raises(DBAPIError) as foreign:
        _insert_commitment(engine, "counterparty_entity_id", ENTITY)
    assert getattr(foreign.value.orig, "sqlstate", None) == FOREIGN_KEY_VIOLATION
    assert _count(engine) == 0
