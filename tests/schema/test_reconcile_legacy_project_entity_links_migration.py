"""WP-MCP-PROJ-05: reconcile legacy `unresolved_missing` Project-Entity links.

Revision `b9025e7fb738` revises `5c1e7a9b3d42`. `9f2c8a1d4e70` (WP-MCP-PROJ-01)
backfilled every pre-existing Continuity Project with an `unresolved_missing`
`project_entity_links` row and a null entity id, and nothing ever resolved
those rows afterward. This revision calls
`my_pa.infrastructure.persistence.project_entity_reconciliation.reconcile_project_entity_links`
once on its own connection. The assertions here are the chain position, the
narrow (and deliberate) import exception this revision takes from the
pure-SQL precedent, empty-to-head, the zero-candidate mint-and-bind branch,
the one-candidate ambiguous-flag branch (no auto-merge on a name match, ever),
the same-run same-canonical-name ordering trap, that already-resolved rows
are left untouched, and the documented no-op downgrade.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "b9025e7fb738"
PREVIOUS: Final = "5c1e7a9b3d42"
MIGRATION: Final = (
    ROOT
    / "migrations"
    / "versions"
    / "20261015_b9025e7fb738_reconcile_legacy_project_entity_links.py"
)

PRINCIPAL: Final = "prn_aaaaaaaa11111111"
PRINCIPAL_B: Final = "prn_bbbbbbbb22222222"
PROJECT_A: Final = "prj_aaaaaaaa11111111"
PROJECT_B: Final = "prj_bbbbbbbb22222222"
PROJECT_C: Final = "prj_cccccccc33333333"
ENTITY_EXISTING: Final = "ent_aaaaaaaa11111111"
WHEN: Final = "2026-09-13 12:00:00+00"
PARTICIPANTS: Final = "[]"


def _config(output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer or io.StringIO())


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; this module drives Alembic itself."""
    return empty_database_url


def _seed_legacy_project(
    connection: Connection,
    *,
    project_id: str,
    principal_id: str = PRINCIPAL,
    name: str,
) -> None:
    """A Project plus its `unresolved_missing` bridge row, at the predecessor head.

    This is exactly the shape `9f2c8a1d4e70`'s backfill left behind: a Project
    row and a `project_entity_links` row with `linkage_state =
    'unresolved_missing'` and a null entity id. No Entity is created here —
    that absence is the defect this revision resolves.
    """
    connection.execute(
        text(
            """
            INSERT INTO knowledge.projects (
              project_id, principal_id, name, description, state, participants,
              opened_at, closed_at, created_at, updated_at, version
            ) VALUES (
              :project_id, :principal_id, :name, NULL, 'active',
              CAST(:participants AS jsonb), :when, NULL, :when, :when, 1
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
    connection.execute(
        text(
            """
            INSERT INTO knowledge.project_entity_links (
              principal_id, project_id, project_entity_id, linkage_state,
              created_at, updated_at
            ) VALUES (
              :principal_id, :project_id, NULL, 'unresolved_missing', :when, :when
            )
            """
        ),
        {"principal_id": principal_id, "project_id": project_id, "when": WHEN},
    )


def _seed_existing_entity(
    connection: Connection,
    *,
    entity_id: str,
    principal_id: str = PRINCIPAL,
    canonical_name: str,
    display_name: str,
    status: str = "active",
) -> None:
    connection.execute(
        text(
            """
            INSERT INTO knowledge.entities (
              entity_id, principal_id, entity_type, canonical_name,
              display_name, status, created_at, updated_at, version
            ) VALUES (
              :entity_id, :principal_id, 'project', :canonical_name,
              :display_name, :status, :when, :when, 1
            )
            """
        ),
        {
            "entity_id": entity_id,
            "principal_id": principal_id,
            "canonical_name": canonical_name,
            "display_name": display_name,
            "status": status,
            "when": WHEN,
        },
    )


def _link_row(
    engine: Engine, *, project_id: str, principal_id: str = PRINCIPAL
) -> dict[str, object]:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT linkage_state, project_entity_id FROM knowledge.project_entity_links "
                    "WHERE principal_id = :principal_id AND project_id = :project_id"
                ),
                {"principal_id": principal_id, "project_id": project_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


def _entity_count(engine: Engine, *, principal_id: str = PRINCIPAL) -> int:
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT count(*) FROM knowledge.entities WHERE principal_id = :principal_id"),
            {"principal_id": principal_id},
        ).scalar_one()


# ---- a. chain position (no database) ----------------------------------------


def test_the_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    # `264310e0416a` (record lineage S1, ADR-015) is additive on this revision.
    assert script.get_heads() == ["6c2306330ceb"]
    assert script.get_revision("6c2306330ceb").down_revision == "023f8f7eb499"
    assert script.get_revision("c5260943d933").down_revision == "6f1476b8da52"
    assert script.get_revision("6f1476b8da52").down_revision == "d020b532ad7d"
    assert script.get_revision("264310e0416a").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_revision_takes_the_narrow_python_import_exception_and_nothing_else() -> None:
    """Only the reconciliation function is imported; no raw table/enum reach-in.

    Every other data-only revision in this chain is pure `op.execute(...)` SQL.
    This one imports exactly one function from
    `infrastructure.persistence.project_entity_reconciliation` because that
    function, not this file, is what needs `normalize_name` and
    `issue_identifier` -- the migration module itself reaches for nothing
    beyond `alembic` and that one function. The docstring is free to *discuss*
    those names in prose (and does); only the actual `import` statements are
    checked here, via AST rather than substring search, for exactly that
    reason.
    """
    import ast

    source = MIGRATION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    import_froms = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    modules = {node.module for node in import_froms}
    assert modules == {
        "__future__",
        "alembic",
        "my_pa.infrastructure.persistence.project_entity_reconciliation",
    }
    my_pa_froms = [node for node in import_froms if node.module and node.module.startswith("my_pa")]
    assert {node.module for node in my_pa_froms} == {
        "my_pa.infrastructure.persistence.project_entity_reconciliation"
    }
    imported_names = {alias.name for node in my_pa_froms for alias in node.names}
    assert imported_names == {"reconcile_project_entity_links"}
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Import)]


def test_revision_adds_no_ddl() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    for token in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE INDEX", "DROP INDEX"):
        assert token not in source


def test_offline_mode_fails_closed_instead_of_reconciling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--sql` has no connection to read or write against; it must not try.

    `reconcile_project_entity_links` mints opaque identifiers and branches on
    live candidate-count data -- neither is reproducible as static SQL a
    script could emit instead -- so this revision's `upgrade()` checks
    `context.is_offline_mode()` and raises instead, the same
    `DO $$ BEGIN RAISE EXCEPTION ...; END $$` pattern `8e1c4a7b2d90` uses for
    its own offline-unsafe step. Asserted by running `--sql` for real and
    reading the emitted script, not by inspecting source text, so a future
    edit that silently drops the branch fails this test rather than only a
    reviewer's eye.
    """
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    buffer = io.StringIO()
    command.upgrade(_config(buffer), "head", sql=True)
    emitted = buffer.getvalue()
    assert "RAISE EXCEPTION" in emitted
    assert "b9025e7fb738 requires online Alembic execution" in emitted


# ---- b. empty-to-head ---------------------------------------------------------


@pytest.mark.database
def test_empty_to_head_still_works(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            tables = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert "project_entity_links" in tables
        assert "entities" in tables
    finally:
        engine.dispose()


# ---- c. zero-candidate branch: mint and bind ----------------------------------


@pytest.mark.database
def test_predecessor_to_head_mints_and_binds_when_no_candidate_exists(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
        command.upgrade(_config(), REVISION)
        link = _link_row(engine, project_id=PROJECT_A)
        assert link["linkage_state"] == "bound"
        assert link["project_entity_id"] is not None
        with engine.connect() as connection:
            entity = (
                connection.execute(
                    text(
                        "SELECT entity_type, canonical_name, display_name, status, version "
                        "FROM knowledge.entities WHERE entity_id = :entity_id"
                    ),
                    {"entity_id": link["project_entity_id"]},
                )
                .mappings()
                .one()
            )
        assert entity["entity_type"] == "project"
        assert entity["canonical_name"] == "harbour tower"
        assert entity["display_name"] == "Harbour Tower"
        assert entity["status"] == "active"
        assert int(entity["version"]) == 1
        assert _entity_count(engine) == 1
    finally:
        engine.dispose()


# ---- d. one-candidate branch: flag, never auto-bind ---------------------------


@pytest.mark.database
def test_predecessor_to_head_flags_ambiguous_and_never_auto_binds(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
            _seed_existing_entity(
                connection,
                entity_id=ENTITY_EXISTING,
                canonical_name="harbour tower",
                display_name="Harbour Tower (pre-existing)",
            )
        command.upgrade(_config(), REVISION)
        link = _link_row(engine, project_id=PROJECT_A)
        assert link["linkage_state"] == "unresolved_ambiguous"
        assert link["project_entity_id"] is None
        # The pre-existing candidate Entity is untouched, and no second Entity
        # was minted: exactly the one row seeded before upgrading survives.
        assert _entity_count(engine) == 1
        with engine.connect() as connection:
            untouched = (
                connection.execute(
                    text(
                        "SELECT display_name, version FROM knowledge.entities WHERE entity_id = :id"
                    ),
                    {"id": ENTITY_EXISTING},
                )
                .mappings()
                .one()
            )
        assert untouched["display_name"] == "Harbour Tower (pre-existing)"
        assert int(untouched["version"]) == 1
    finally:
        engine.dispose()


# ---- e. same-run, same-canonical-name ordering trap ---------------------------


@pytest.mark.database
def test_two_unresolved_rows_sharing_a_name_mint_exactly_one_entity(
    disposable_database: str,
) -> None:
    """The first row to see zero candidates mints; the second sees that mint.

    Both `PROJECT_A` and `PROJECT_B` normalize to the same canonical name.
    Processed in one pass, in `(principal_id, project_id)` order, the first
    (`PROJECT_A`) finds no candidate and mints; the second (`PROJECT_B`) then
    finds the just-minted Entity as its candidate and is flagged ambiguous --
    never a second, duplicate mint.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
            _seed_legacy_project(connection, project_id=PROJECT_B, name="Harbour Tower")
        command.upgrade(_config(), REVISION)
        link_a = _link_row(engine, project_id=PROJECT_A)
        link_b = _link_row(engine, project_id=PROJECT_B)
        bound = [link for link in (link_a, link_b) if link["linkage_state"] == "bound"]
        ambiguous = [
            link for link in (link_a, link_b) if link["linkage_state"] == "unresolved_ambiguous"
        ]
        assert len(bound) == 1
        assert len(ambiguous) == 1
        assert bound[0]["project_entity_id"] is not None
        assert ambiguous[0]["project_entity_id"] is None
        # PROJECT_A sorts before PROJECT_B, so PROJECT_A is the one minted.
        assert link_a["linkage_state"] == "bound"
        assert link_b["linkage_state"] == "unresolved_ambiguous"
        assert _entity_count(engine) == 1
    finally:
        engine.dispose()


# ---- f. already-resolved rows are left untouched ------------------------------


@pytest.mark.database
def test_an_already_bound_row_is_left_untouched(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
            _seed_existing_entity(
                connection,
                entity_id=ENTITY_EXISTING,
                canonical_name="harbour tower",
                display_name="Harbour Tower",
            )
            connection.execute(
                text(
                    "UPDATE knowledge.project_entity_links "
                    "SET linkage_state = 'bound', project_entity_id = :entity_id, "
                    "updated_at = :when "
                    "WHERE principal_id = :principal_id AND project_id = :project_id"
                ),
                {
                    "entity_id": ENTITY_EXISTING,
                    "when": WHEN,
                    "principal_id": PRINCIPAL,
                    "project_id": PROJECT_A,
                },
            )
        command.upgrade(_config(), REVISION)
        link = _link_row(engine, project_id=PROJECT_A)
        assert link["linkage_state"] == "bound"
        assert link["project_entity_id"] == ENTITY_EXISTING
        assert _entity_count(engine) == 1
    finally:
        engine.dispose()


@pytest.mark.database
def test_an_already_ambiguous_row_is_left_untouched(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
            connection.execute(
                text(
                    "UPDATE knowledge.project_entity_links "
                    "SET linkage_state = 'unresolved_ambiguous', updated_at = :when "
                    "WHERE principal_id = :principal_id AND project_id = :project_id"
                ),
                {"when": WHEN, "principal_id": PRINCIPAL, "project_id": PROJECT_A},
            )
        command.upgrade(_config(), REVISION)
        link = _link_row(engine, project_id=PROJECT_A)
        assert link["linkage_state"] == "unresolved_ambiguous"
        assert link["project_entity_id"] is None
        assert _entity_count(engine) == 0
    finally:
        engine.dispose()


# ---- g. a third, unrelated row is unaffected by either branch -----------------


@pytest.mark.database
def test_an_unrelated_third_project_resolves_independently(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
            _seed_legacy_project(connection, project_id=PROJECT_C, name="Riverside Depot")
        command.upgrade(_config(), REVISION)
        link_a = _link_row(engine, project_id=PROJECT_A)
        link_c = _link_row(engine, project_id=PROJECT_C)
        assert link_a["linkage_state"] == "bound"
        assert link_c["linkage_state"] == "bound"
        assert link_a["project_entity_id"] != link_c["project_entity_id"]
        assert _entity_count(engine) == 2
    finally:
        engine.dispose()


# ---- h. downgrade is a documented no-op ---------------------------------------


@pytest.mark.database
def test_downgrade_is_a_documented_no_op_on_data(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS)
        with engine.begin() as connection:
            _seed_legacy_project(connection, project_id=PROJECT_A, name="Harbour Tower")
        command.upgrade(_config(), REVISION)
        before = _link_row(engine, project_id=PROJECT_A)
        before_count = _entity_count(engine)
        command.downgrade(_config(), PREVIOUS)
        after = _link_row(engine, project_id=PROJECT_A)
        after_count = _entity_count(engine)
        assert after == before
        assert after_count == before_count
    finally:
        engine.dispose()
