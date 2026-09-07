"""Admit the Constraint Management read vocabulary (PC-CM-IMP-WP04).

`c5b71e0a8d43` widens both closed-set CHECKs on `knowledge.audit_events` and
touches nothing else. Four things are asserted and they fail in different ways.

**The graph.** One head, and it is this revision, descending from `a1c9e4b72f80`.
A second head makes `alembic upgrade head` ambiguous.

**The freeze.** The revision imports no domain enum and no declaration module,
and its `BEFORE` texts are byte-for-byte the `AT` texts of the revision it
descends from. A revision that derived its literals from `Capability` would be
green on the day it merged and would rewrite history on every later widening --
which is the rule `9c6b4a18ed72` states and
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces from the other side.

**The database.** Old head to new head, empty to head, and a downgrade that
restores the previous vocabulary exactly -- proved by writing an audit row the
new vocabulary admits and the old one refuses, which is the only thing that
distinguishes a restated CHECK from a dropped one.

**The blast radius.** The revision names `audit_events` and no Constraint table.
`tests/architecture/test_constraint_read_plane_boundaries.py` asserts the same
thing across every revision; this asserts it about the one added here.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
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
REVISION: Final = "c5b71e0a8d43"
PREVIOUS: Final = "a1c9e4b72f80"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20260906_c5b71e0a8d43_admit_the_constraint_read_capabilities.py"
PREVIOUS_MIGRATION: Final = (
    MIGRATIONS / "20260906_a1c9e4b72f80_admit_goodnotes_browser_contracts.py"
)

ADMITTED_CAPABILITIES: Final[tuple[str, ...]] = (
    "constraint_categories.list",
    "constraints.history",
    "constraints.list",
    "constraints.overview",
    "constraints.read",
    "constraints.search",
)
ADMITTED_PURPOSES: Final[tuple[str, ...]] = ("constraint_read",)

SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
PRINCIPAL_A: Final = "prn_cccc0001cccc0001cccc0001"
WHEN: Final = datetime(2026, 9, 6, 12, tzinfo=UTC)
POLICY_VERSION: Final = "policy-v1"
_ROWS = count(1)

#: The fourteen Constraint tables WP02 installed. Named here rather than imported
#: so this file states what it forbids rather than inheriting it.
CONSTRAINT_TABLES: Final[frozenset[str]] = frozenset(
    {
        "project_constraint_settings",
        "constraint_categories",
        "constraint_category_history",
        "project_constraints",
        "project_constraint_revisions",
        "project_constraint_history",
        "project_constraint_parties",
        "project_constraint_relationships",
        "project_constraint_evidence_links",
        "constraint_sync_targets",
        "constraint_sync_runs",
        "constraint_sync_baselines",
        "constraint_sync_conflicts",
        "constraint_workbook_imports",
    }
)


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


# ---- the graph --------------------------------------------------------------


def test_revision_is_the_only_linear_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


# ---- the freeze -------------------------------------------------------------


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
    for value in (*ADMITTED_CAPABILITIES, *ADMITTED_PURPOSES):
        assert value in source


def test_the_before_texts_are_byte_copies_of_the_revision_below() -> None:
    """Copied, not reconstructed, and this is what tells the two apart.

    A `BEFORE` text rebuilt from the domain would be *equal* to the previous
    revision's `AT` text today and would silently become a different set the next
    time a member is added — so equality of the parsed values is not the claim.
    The claim is that the characters match.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    previous = PREVIOUS_MIGRATION.read_text(encoding="utf-8")
    assert _constant(source, "_CAPABILITIES_BEFORE_THIS_REVISION") == _constant(
        previous, "_CAPABILITIES_AT_THIS_REVISION"
    )
    assert _constant(source, "_PURPOSES_BEFORE_THIS_REVISION") == _constant(
        previous, "_PURPOSES_AT_THIS_REVISION"
    )


def test_the_at_texts_add_exactly_the_seven_new_values_and_stay_sorted() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    before = _literals(_constant(source, "_CAPABILITIES_BEFORE_THIS_REVISION"))
    at = _literals(_constant(source, "_CAPABILITIES_AT_THIS_REVISION"))
    assert sorted(set(at) - set(before)) == sorted(ADMITTED_CAPABILITIES)
    assert set(before) - set(at) == set()
    assert at == sorted(at)

    purposes_before = _literals(_constant(source, "_PURPOSES_BEFORE_THIS_REVISION"))
    purposes_at = _literals(_constant(source, "_PURPOSES_AT_THIS_REVISION"))
    assert sorted(set(purposes_at) - set(purposes_before)) == sorted(ADMITTED_PURPOSES)
    assert set(purposes_before) - set(purposes_at) == set()
    assert purposes_at == sorted(purposes_at)


def test_the_revision_restates_both_named_checks_and_nothing_else() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert '("capability_is_known", capability)' in source
    assert '("purpose_is_known", purpose)' in source
    assert "_restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)" in source
    assert "_restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)" in source


def test_the_revision_touches_only_the_audit_events_table() -> None:
    """One table, and no Constraint table anywhere in it.

    `tests/architecture/test_constraint_read_plane_boundaries.py` reddens if any
    revision but WP02's names a Constraint table; this states the same fact about
    the revision added here so the failure names this file when it is this file's
    fault.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    # Word-boundary and not a bare substring: `constraint_categories.list` is a
    # capability *value* this revision admits, and a naive containment check
    # would read it as the table of nearly the same name. The lookahead is what
    # separates a table reference from a dotted capability name.
    named = sorted(
        table for table in CONSTRAINT_TABLES if re.search(rf"\b{re.escape(table)}\b(?!\.)", source)
    )
    assert named == []
    tables = set(re.findall(r"ALTER TABLE \{SCHEMA\}\.(\w+)", source))
    assert tables == {"audit_events"}


def test_no_historical_revision_was_edited() -> None:
    """The chain below this revision is untouched, measured against git.

    Asserted by content rather than by trust: every revision file except the one
    this work package adds must be byte-identical to the merge base. A widening
    that edited a merged revision would change what a database at that revision
    is supposed to hold.
    """
    changed = subprocess.run(
        ["git", "diff", "--name-only", "origin/main...HEAD", "--", "migrations/"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if changed.returncode != 0:
        pytest.skip("no merge base available in this checkout")
    touched = {line for line in changed.stdout.splitlines() if line.strip()}
    assert touched <= {MIGRATION.relative_to(ROOT).as_posix()}, (
        f"a revision other than this one changed: {sorted(touched)}"
    )


# ---- the database -----------------------------------------------------------


@pytest.mark.database
def test_head_admits_the_constraint_read_vocabulary(migrated_engine: Engine) -> None:
    for capability in ADMITTED_CAPABILITIES:
        _audit(migrated_engine, capability=capability, purpose=ADMITTED_PURPOSES[0])


@pytest.mark.database
def test_downgrade_restores_the_previous_vocabulary(migrated_engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS)
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    with pytest.raises(IntegrityError) as capability_refusal:
        _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=SETTLED_PURPOSE)
    assert "capability_is_known" in str(capability_refusal.value)
    with pytest.raises(IntegrityError) as purpose_refusal:
        _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=ADMITTED_PURPOSES[0])
    assert "purpose_is_known" in str(purpose_refusal.value)
    command.upgrade(_config(), "head")
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=ADMITTED_PURPOSES[0])


@pytest.mark.database
def test_the_settled_vocabulary_still_answers_at_head(migrated_engine: Engine) -> None:
    """A widening widens. Nothing the previous head admitted is refused now."""
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
