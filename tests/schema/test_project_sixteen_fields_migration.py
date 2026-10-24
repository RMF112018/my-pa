"""`cc373834a485`: sixteen Continuity Project fields on `knowledge.projects`.

The revision is additive: sixteen columns (fifteen nullable, `aliases` defaulting
to an empty array), five CHECKs, and a partial unique index making
`project_number` unique per Principal. Every field stays changeable; the revision
installs no trigger.
Downgrade deletes nothing it was not given: a Project holding any new field
makes it refuse.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.exc import DBAPIError

from my_pa.domain.situation.situation import ProjectSector, ProjectType
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
VERSIONS: Final = ROOT / "migrations" / "versions"
REVISION: Final = "cc373834a485"
PREVIOUS: Final = "93f3aa113f58"
#: The chain head: `a591b81f10a2` (Intelligence report type registry) is additive
#: on `REVISION`.
HEAD: Final = "c5260943d933"
MIGRATION: Final = VERSIONS / "20261011_cc373834a485_project_sixteen_fields.py"
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
WHEN: Final = datetime(2026, 10, 11, 12, tzinfo=UTC)
CHECK_VIOLATION: Final = "23514"
UNIQUE_VIOLATION: Final = "23505"
NEW_COLUMNS: Final = frozenset(
    {
        "aliases",
        "project_number",
        "sector",
        "type",
        "address",
        "city",
        "county",
        "address_state",
        "zip",
        "value",
        "scheduled_start",
        "contract_start",
        "actual_start",
        "scheduled_finish",
        "contract_finish",
        "actual_finish",
    }
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _literals(name: str) -> set[str]:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            text_value = ast.literal_eval(node.value)
            assert isinstance(text_value, str)
            return {part.strip().strip("'") for part in text_value.split(",")}
    raise AssertionError(f"{name} is not a module-level constant of {MIGRATION.name}")


# ---- FAST: the graph and the freeze -----------------------------------------------


def test_the_revision_is_directly_on_the_focus_area_revision_under_one_later_head() -> None:
    """`a591b81f10a2` (Intelligence report type registry) landed on this revision,
    so it is no longer the head. The chain still holds exactly one head, and this
    revision sits directly beneath it.
    """
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD]
    assert script.get_revision(HEAD).down_revision == "6f1476b8da52"
    assert script.get_revision("6f1476b8da52").down_revision == "d020b532ad7d"
    assert script.get_revision("d020b532ad7d").down_revision == "264310e0416a"
    assert script.get_revision("264310e0416a").down_revision == "b9025e7fb738"
    assert script.get_revision("b9025e7fb738").down_revision == "5c1e7a9b3d42"
    assert script.get_revision("5c1e7a9b3d42").down_revision == "c8f7ae406d47"
    assert script.get_revision("c8f7ae406d47").down_revision == "a591b81f10a2"
    assert script.get_revision("a591b81f10a2").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_the_frozen_vocabularies_equal_the_domain_enums_today() -> None:
    """Frozen (`D-48`), not derived; equal at this revision, and free to diverge later."""
    assert _literals("_SECTORS_SQL") == {member.value for member in ProjectSector}
    assert _literals("_TYPES_SQL") == {member.value for member in ProjectType}


def test_the_revision_imports_nothing_from_the_application() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "my_pa" not in source


# ---- the database -----------------------------------------------------------------


@pytest.fixture
def engine(empty_database_url: str) -> Iterator[Engine]:
    built = create_database_engine(empty_database_url)
    try:
        yield built
    finally:
        built.dispose()


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _seed(connection: Connection, project_id: str, principal_id: str = PRINCIPAL_A) -> None:
    """A Project in the shape the previous head writes it."""
    connection.execute(
        text(
            "INSERT INTO knowledge.projects (project_id, principal_id, name, description, "
            "state, participants, opened_at, closed_at, created_at, updated_at) "
            "VALUES (:project_id, :principal_id, :name, NULL, 'active', '[]'::jsonb, "
            ":when, NULL, :when, :when)"
        ),
        {
            "project_id": project_id,
            "principal_id": principal_id,
            "name": f"Seeded {project_id}",
            "when": WHEN,
        },
    )


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


@pytest.mark.database
@pytest.mark.migration_edge
def test_existing_projects_upgrade_to_empty_fields_and_the_guards_hold(engine: Engine) -> None:
    command.upgrade(_config(), PREVIOUS)
    with engine.begin() as connection:
        _seed(connection, "prj_aaaaaaaa00000001")
        _seed(connection, "prj_aaaaaaaa00000002")
        _seed(connection, "prj_bbbbbbbb00000001", PRINCIPAL_B)
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    columns = {column["name"] for column in inspect(engine).get_columns("projects", "knowledge")}
    assert columns >= NEW_COLUMNS
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT aliases, project_number, sector, value, actual_finish "
                "FROM knowledge.projects ORDER BY project_id"
            )
        ).all()
    assert [tuple(row) for row in rows] == [([], None, None, None, None)] * 3

    def refused(statement: str, sqlstate: str) -> None:
        with pytest.raises(DBAPIError) as caught, engine.begin() as connection:
            connection.execute(text(statement))
        assert _sqlstate(caught.value) == sqlstate, statement

    one = "UPDATE knowledge.projects SET {} WHERE project_id = 'prj_aaaaaaaa00000001'"
    refused(one.format("value = -1"), CHECK_VIOLATION)
    refused(one.format("project_number = '   '"), CHECK_VIOLATION)
    refused(one.format(f"project_number = '{'x' * 65}'"), CHECK_VIOLATION)
    refused(one.format("sector = 'housing_and_residential'"), CHECK_VIOLATION)
    refused(one.format("sector = 'nope', type = 'multifamily_housing'"), CHECK_VIOLATION)

    with engine.begin() as connection:
        connection.execute(text(one.format("project_number = 'P-1'")))
        connection.execute(
            text(
                "UPDATE knowledge.projects SET project_number = 'P-1' "
                "WHERE project_id = 'prj_bbbbbbbb00000001'"
            )
        )
    refused(
        "UPDATE knowledge.projects SET project_number = 'P-1' "
        "WHERE project_id = 'prj_aaaaaaaa00000002'",
        UNIQUE_VIOLATION,
    )
    with engine.begin() as connection:
        connection.execute(text(one.format("name = 'Renamed', value = 12.50")))
        connection.execute(text(one.format("project_number = 'P-2'")))
        connection.execute(text(one.format("project_number = NULL")))
        guard = connection.execute(
            text(
                "SELECT count(*) FROM pg_trigger WHERE tgname = 'a_project_number_does_not_change'"
            )
        ).scalar_one()
    assert guard == 0


@pytest.mark.database
@pytest.mark.migration_edge
def test_downgrade_refuses_while_a_project_holds_a_new_field_then_round_trips(
    engine: Engine,
) -> None:
    command.upgrade(_config(), REVISION)
    with engine.begin() as connection:
        _seed(connection, "prj_aaaaaaaa00000003")
        connection.execute(
            text(
                "UPDATE knowledge.projects SET aliases = '[\"NS\"]'::jsonb "
                "WHERE project_id = 'prj_aaaaaaaa00000003'"
            )
        )
    with pytest.raises(DBAPIError):
        command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == REVISION
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.projects SET aliases = '[]'::jsonb "
                "WHERE project_id = 'prj_aaaaaaaa00000003'"
            )
        )
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    columns = {column["name"] for column in inspect(engine).get_columns("projects", "knowledge")}
    assert columns.isdisjoint(NEW_COLUMNS)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM knowledge.projects")).scalar_one() == 1
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
