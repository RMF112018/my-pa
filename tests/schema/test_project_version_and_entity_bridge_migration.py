"""WP-MCP-PROJ-01: Project.version and the Project↔Entity bridge.

Revision `9f2c8a1d4e70` revises `de5ec1c65857`. Empty-to-head, prior-to-head
backfill, uniqueness/CHECKs, and a fail-closed downgrade are asserted here.
The revision SQL must not join on a name: `canonical_name` and
`project_display_name` are forbidden as join keys.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import project_entity_links, projects

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "9f2c8a1d4e70"
CURRENT_HEAD: Final = "7a5c4e9d2b61"
PREVIOUS_REVISION: Final = "de5ec1c65857"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20260913_9f2c8a1d4e70_project_version_and_entity_bridge.py"
)

PRINCIPAL: Final = "prn_aaaaaaaa11111111"
PRINCIPAL_B: Final = "prn_bbbbbbbb22222222"
PROJECT: Final = "prj_aaaaaaaa11111111"
PROJECT_B: Final = "prj_bbbbbbbb22222222"
ENTITY: Final = "ent_aaaaaaaa11111111"
WHEN: Final = "2026-09-13 12:00:00+00"
PARTICIPANTS: Final = '["per_aaaaaaaa11111111"]'


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; this module drives Alembic itself."""
    return empty_database_url


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


def _columns(engine: Engine, table: str) -> dict[str, tuple[Any, ...]]:
    with engine.connect() as connection:
        return {
            str(row[0]): (row[1], row[2])
            for row in connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def _constraint_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT c.conname FROM pg_constraint c "
                    "JOIN pg_class t ON t.oid = c.conrelid "
                    "JOIN pg_namespace n ON n.oid = t.relnamespace "
                    "WHERE n.nspname = :schema AND t.relname = :table"
                ),
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def _index_names(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def _seed_legacy_project(
    connection: Connection,
    *,
    project_id: str = PROJECT,
    principal_id: str = PRINCIPAL,
    name: str = "Seeded project",
) -> None:
    """Insert a pre-WP-MCP-PROJ-01 project row at the WP-TUX-01 head shape."""
    connection.execute(
        text(
            """
            INSERT INTO knowledge.projects (
              project_id, principal_id, name, description, state, participants,
              opened_at, closed_at, created_at, updated_at
            ) VALUES (
              :project_id, :principal_id, :name, 'A seeded description',
              'active', CAST(:participants AS jsonb),
              :when, NULL, :when, :when
            )
            """
        ),
        {
            "project_id": project_id,
            "principal_id": principal_id,
            "name": name,
            "participants": PARTICIPANTS,
            "when": WHEN,
        },
    )


def test_the_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(REVISION).down_revision == PREVIOUS_REVISION


def test_revision_source_does_not_join_on_a_name() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    lowered = source.lower()
    assert "join" not in lowered or (
        "canonical_name" not in lowered and "project_display_name" not in lowered
    )
    for token in ("canonical_name", "project_display_name"):
        assert token not in source


def test_revision_imports_no_domain_enums() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert "from my_pa.domain" not in source
    assert "import my_pa" not in source
    assert "ProjectEntityLinkageState" not in source
    assert "EntityType" not in source


@pytest.mark.database
def test_empty_to_head_installs_version_and_bridge(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert "project_entity_links" in _tables(engine)
        columns = _columns(engine, "projects")
        assert columns["version"][1] == "NO"
        names = _constraint_names(engine, "projects")
        assert "a_project_version_is_positive" in names
        assert "a_project_is_identified_within_its_principal" in names
        link_cols = set(_columns(engine, "project_entity_links"))
        assert link_cols == {
            "principal_id",
            "project_id",
            "project_entity_id",
            "linkage_state",
            "created_at",
            "updated_at",
        }
        link_names = _constraint_names(engine, "project_entity_links")
        assert "a_project_entity_link_state_is_known" in link_names
        assert "a_bound_project_entity_link_names_its_entity" in link_names
        assert "a_project_entity_link_names_a_project_in_its_principal" in link_names
        assert "a_project_entity_link_names_an_entity_in_its_principal" in link_names
        indexes = _index_names(engine, "project_entity_links")
        assert "project_entity_links_by_principal" in indexes
        assert "a_project_entity_is_linked_once_per_principal" in indexes
        assert {column.name for column in project_entity_links.columns} == link_cols
        assert "version" in {column.name for column in projects.columns}
        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_previous_head_to_head_preserves_projects_and_participants(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with engine.begin() as connection:
            _seed_legacy_project(connection)
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            project = (
                connection.execute(
                    text(
                        "SELECT project_id, name, participants, version "
                        "FROM knowledge.projects WHERE project_id = :project_id"
                    ),
                    {"project_id": PROJECT},
                )
                .mappings()
                .one()
            )
            link = (
                connection.execute(
                    text(
                        "SELECT project_id, project_entity_id, linkage_state "
                        "FROM knowledge.project_entity_links "
                        "WHERE principal_id = :principal_id AND project_id = :project_id"
                    ),
                    {"principal_id": PRINCIPAL, "project_id": PROJECT},
                )
                .mappings()
                .one()
            )
            entity_count = connection.execute(
                text("SELECT count(*) FROM knowledge.entities")
            ).scalar_one()
        assert project["name"] == "Seeded project"
        assert project["participants"] == ["per_aaaaaaaa11111111"]
        assert int(project["version"]) == 1
        assert link["linkage_state"] == "unresolved_missing"
        assert link["project_entity_id"] is None
        assert int(entity_count) == 0
    finally:
        engine.dispose()


@pytest.mark.database
def test_version_default_and_unresolved_backfill_for_existing_projects(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.projects (
                      project_id, principal_id, name, state, participants,
                      opened_at, created_at, updated_at
                    ) VALUES (
                      :project_id, :principal_id, 'Forward project', 'active',
                      '[]'::jsonb, :when, :when, :when
                    )
                    """
                ),
                {"project_id": PROJECT, "principal_id": PRINCIPAL, "when": WHEN},
            )
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version FROM knowledge.projects WHERE project_id = :project_id"),
                {"project_id": PROJECT},
            ).scalar_one()
        assert int(version) == 1
    finally:
        engine.dispose()


@pytest.mark.database
def test_uniqueness_and_checks(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.projects (
                      project_id, principal_id, name, state, participants,
                      opened_at, created_at, updated_at, version
                    ) VALUES (
                      :project_id, :principal_id, 'Checked project', 'active',
                      '[]'::jsonb, :when, :when, :when, 1
                    )
                    """
                ),
                {"project_id": PROJECT, "principal_id": PRINCIPAL, "when": WHEN},
            )
        # version < 1 is refused.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.projects (
                      project_id, principal_id, name, state, participants,
                      opened_at, created_at, updated_at, version
                    ) VALUES (
                      :project_id, :principal_id, 'Bad version', 'active',
                      '[]'::jsonb, :when, :when, :when, 0
                    )
                    """
                ),
                {"project_id": PROJECT_B, "principal_id": PRINCIPAL, "when": WHEN},
            )
        # bound without an entity id is refused.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.project_entity_links (
                      principal_id, project_id, project_entity_id, linkage_state,
                      created_at, updated_at
                    ) VALUES (
                      :principal_id, :project_id, NULL, 'bound', :when, :when
                    )
                    """
                ),
                {"principal_id": PRINCIPAL, "project_id": PROJECT, "when": WHEN},
            )
        # unresolved_ambiguous with a null entity id succeeds.
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.project_entity_links (
                      principal_id, project_id, project_entity_id, linkage_state,
                      created_at, updated_at
                    ) VALUES (
                      :principal_id, :project_id, NULL, 'unresolved_ambiguous',
                      :when, :when
                    )
                    """
                ),
                {"principal_id": PRINCIPAL, "project_id": PROJECT, "when": WHEN},
            )
        # unresolved with a non-null entity id is refused.
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM knowledge.project_entity_links"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.project_entity_links (
                      principal_id, project_id, project_entity_id, linkage_state,
                      created_at, updated_at
                    ) VALUES (
                      :principal_id, :project_id, :entity_id, 'unresolved_missing',
                      :when, :when
                    )
                    """
                ),
                {
                    "principal_id": PRINCIPAL,
                    "project_id": PROJECT,
                    "entity_id": ENTITY,
                    "when": WHEN,
                },
            )
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_refuses_bound_rows(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.projects (
                      project_id, principal_id, name, state, participants,
                      opened_at, created_at, updated_at, version
                    ) VALUES (
                      :project_id, :principal_id, 'Bound project', 'active',
                      '[]'::jsonb, :when, :when, :when, 1
                    )
                    """
                ),
                {"project_id": PROJECT, "principal_id": PRINCIPAL, "when": WHEN},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.entities (
                      entity_id, principal_id, entity_type, canonical_name,
                      display_name, status, created_at, updated_at, version
                    ) VALUES (
                      :entity_id, :principal_id, 'project', 'bound project',
                      'Bound project', 'active', :when, :when, 1
                    )
                    """
                ),
                {"entity_id": ENTITY, "principal_id": PRINCIPAL, "when": WHEN},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO knowledge.project_entity_links (
                      principal_id, project_id, project_entity_id, linkage_state,
                      created_at, updated_at
                    ) VALUES (
                      :principal_id, :project_id, :entity_id, 'bound', :when, :when
                    )
                    """
                ),
                {
                    "principal_id": PRINCIPAL,
                    "project_id": PROJECT,
                    "entity_id": ENTITY,
                    "when": WHEN,
                },
            )
        with pytest.raises(Exception, match="bound project-entity links"):
            command.downgrade(_config(), PREVIOUS_REVISION)
        with engine.connect() as connection:
            assert "project_entity_links" in _tables(engine)
            bound = connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.project_entity_links "
                    "WHERE linkage_state = 'bound'"
                )
            ).scalar_one()
        assert int(bound) == 1
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrade_of_unresolved_rows_drops_the_bridge(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with engine.begin() as connection:
            _seed_legacy_project(connection)
        command.upgrade(_config(), "head")
        command.downgrade(_config(), PREVIOUS_REVISION)
        assert "project_entity_links" not in _tables(engine)
        columns = _columns(engine, "projects")
        assert "version" not in columns
        assert "participants" in columns
        names = _constraint_names(engine, "projects")
        assert "a_project_is_identified_within_its_principal" not in names
    finally:
        engine.dispose()
