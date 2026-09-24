"""Admit `continuity.projects.read` (WP-MCP-PROJ-02).

`b3e9d7a41c25` widens `knowledge.audit_events.capability_is_known` by one name
and adds the Project list keyset index. Modelled on
`tests/schema/test_constraint_authoring_capability_migration.py`.

**The graph.** One head, and it is this revision, descending from
`9f2c8a1d4e70`. A second head makes `alembic upgrade head` ambiguous.

**The freeze.** The revision imports no domain enum and no declaration module,
and its `BEFORE` texts are byte-for-byte the `AT` texts of the revision that
last froze the audited closed sets (`de5ec1c65857`). `9f2c8a1d4e70` did not
restate those sets.

**The database.** Empty to head, previous head to this head, and a downgrade
that restores refusal of `continuity.projects.read`.
"""

from __future__ import annotations

import ast
import io
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "b3e9d7a41c25"
CURRENT_HEAD: Final = "6f6ead27d122"
PREVIOUS: Final = "9f2c8a1d4e70"
VOCABULARY_PREDECESSOR: Final = "de5ec1c65857"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20260913_b3e9d7a41c25_admit_continuity_projects_read.py"
PREVIOUS_MIGRATION: Final = (
    MIGRATIONS / "20260911_de5ec1c65857_wp_tux_01_task_origin_closure_comments.py"
)
INDEX: Final = "projects_by_principal_created_at_id_desc"
ADMITTED_CAPABILITIES: Final[tuple[str, ...]] = ("continuity.projects.read",)
SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
CAPTURE_REVIEW: Final = "capture_review"
PRINCIPAL_A: Final = "prn_cccc0001cccc0001cccc0001"
WHEN: Final = datetime(2026, 9, 13, 12, tzinfo=UTC)
POLICY_VERSION: Final = "policy-v1"
_ROWS = count(1)
AUDITED_CONSTRAINTS: Final[tuple[str, ...]] = ("capability_is_known", "purpose_is_known")


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    return empty_database_url


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _index() -> str:
    return f"{next(_ROWS):016x}"


def _audit(engine: Engine, *, capability: str, purpose: str) -> None:
    index = _index()
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.audit_events "  # noqa: S608
                "(audit_id, correlation_id, principal_id, capability, purpose, outcome, "
                " policy_version, scope_source_id_count, recorded_at) "
                "VALUES (:audit_id, :correlation_id, :principal_id, :capability, :purpose, "
                " 'allowed', :policy_version, 0, :recorded_at)"
            ),
            {
                "audit_id": f"audit_{index}",
                "correlation_id": f"corr_{index}",
                "principal_id": PRINCIPAL_A,
                "capability": capability,
                "purpose": purpose,
                "policy_version": POLICY_VERSION,
                "recorded_at": WHEN,
            },
        )


def _constant(source: str, name: str) -> str:
    """One spelled `Final` literal, as written, including its line breaks."""
    found = re.search(rf"^{name}: Final = \(\n(.*?)^\)\n", source, re.S | re.M)
    assert found is not None, f"{name} is not spelled in the revision"
    return found.group(1)


def _literals(block: str) -> list[str]:
    return re.findall(r"'([^']+)'", block)


def test_revision_is_the_only_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CURRENT_HEAD).down_revision == "e6a4c2f91b73"
    assert script.get_revision("e6a4c2f91b73").down_revision == "c4f1a8e52d90"
    assert script.get_revision("c4f1a8e52d90").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == VOCABULARY_PREDECESSOR


def test_the_chain_holds_the_files_it_claims() -> None:
    assert len(list(MIGRATIONS.glob("*.py"))) == 107


def test_revision_is_frozen_and_does_not_import_live_schema_or_enums() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "my_pa.infrastructure.persistence.tables" not in imported
    assert not any(module.startswith("my_pa.domain") for module in imported)
    assert imported <= {"alembic", "typing", "__future__"}
    for value in ADMITTED_CAPABILITIES:
        assert value in source


def test_the_before_texts_are_byte_copies_of_the_vocabulary_predecessor() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    previous = PREVIOUS_MIGRATION.read_text(encoding="utf-8")
    assert _constant(source, "_CAPABILITIES_BEFORE_THIS_REVISION") == _constant(
        previous, "_CAPABILITIES_AT_THIS_REVISION"
    )
    assert _constant(source, "_PURPOSES_BEFORE_THIS_REVISION") == _constant(
        previous, "_PURPOSES_AT_THIS_REVISION"
    )


def test_no_revision_between_the_vocabulary_predecessor_and_this_one_restates_the_sets() -> None:
    script = ScriptDirectory.from_config(_config())
    between: list[str] = []
    current = script.get_revision(REVISION).down_revision
    while current != VOCABULARY_PREDECESSOR:
        assert current is not None, (
            f"{VOCABULARY_PREDECESSOR} is not an ancestor of {REVISION}; the BEFORE "
            "literals are copied from a revision that is not on this chain"
        )
        assert isinstance(current, str), f"{current!r} is a branch point, not a linear parent"
        between.append(current)
        current = script.get_revision(current).down_revision
    assert between == [PREVIOUS]
    for revision in between:
        source = Path(script.get_revision(revision).path).read_text(encoding="utf-8")
        for constraint in AUDITED_CONSTRAINTS:
            found = re.search(rf"(?<![A-Za-z0-9_]){re.escape(constraint)}", source)
            assert found is None, (
                f"{revision} restates {constraint}, so it — not {VOCABULARY_PREDECESSOR} — "
                f"is the correct source for this revision's BEFORE literals"
            )


def test_the_at_texts_add_exactly_the_new_capability_and_stay_sorted() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    before = _literals(_constant(source, "_CAPABILITIES_BEFORE_THIS_REVISION"))
    at = _literals(_constant(source, "_CAPABILITIES_AT_THIS_REVISION"))
    assert sorted(set(at) - set(before)) == sorted(ADMITTED_CAPABILITIES)
    assert set(before) - set(at) == set()
    assert at == sorted(at)
    purposes_before = _literals(_constant(source, "_PURPOSES_BEFORE_THIS_REVISION"))
    purposes_at = _literals(_constant(source, "_PURPOSES_AT_THIS_REVISION"))
    assert purposes_at == purposes_before
    assert purposes_at == sorted(purposes_at)


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_head_admits_continuity_projects_read(migrated_engine: Engine) -> None:
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=CAPTURE_REVIEW)
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    with migrated_engine.connect() as connection:
        named = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND indexname = :index"
            ),
            {"schema": SCHEMA, "index": INDEX},
        ).scalar_one_or_none()
    assert named == INDEX


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_downgrade_restores_refusal_of_the_new_capability(migrated_engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS)
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    with pytest.raises(IntegrityError) as capability_refusal:
        _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=CAPTURE_REVIEW)
    assert "capability_is_known" in str(capability_refusal.value)
    with migrated_engine.connect() as connection:
        named = connection.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = :schema AND indexname = :index"
            ),
            {"schema": SCHEMA, "index": INDEX},
        ).scalar_one_or_none()
    assert named is None
    command.upgrade(_config(), "head")
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=CAPTURE_REVIEW)


@pytest.mark.migration_empty_to_head
@pytest.mark.database
def test_an_empty_database_upgrades_to_the_new_head(disposable_database: str) -> None:
    command.upgrade(_config(), "head")
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            stamped = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert stamped == CURRENT_HEAD
    finally:
        engine.dispose()


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_previous_head_upgrades_to_this_revision(disposable_database: str) -> None:
    command.upgrade(_config(), PREVIOUS)
    command.upgrade(_config(), REVISION)
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            stamped = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert stamped == REVISION
        _audit(engine, capability=ADMITTED_CAPABILITIES[0], purpose=CAPTURE_REVIEW)
    finally:
        engine.dispose()
