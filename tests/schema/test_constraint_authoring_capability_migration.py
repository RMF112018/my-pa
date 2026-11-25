"""Admit the Constraint Management authoring vocabulary (PC-CM-IMP-WP07).

`f7a2c9d51e64` widens both closed-set CHECKs on `knowledge.audit_events` and
touches nothing else. Modelled on
`tests/schema/test_constraint_read_capability_migration.py`, because the rule it
is enforcing is the same rule.

**The graph.** One head, and it is this revision, descending from
`c5b71e0a8d43`. A second head makes `alembic upgrade head` ambiguous.

**The freeze.** The revision imports no domain enum and no declaration module,
and its `BEFORE` texts are byte-for-byte the `AT` texts of the revision it
descends from. A revision that derived its literals from `Capability` would be
green on the day it merged and would rewrite history on every later widening --
the rule `9c6b4a18ed72` states.

**The database.** Old head to new head, empty to head, and a downgrade that
restores the previous vocabulary exactly -- proved by writing an audit row the
new vocabulary admits and the old one refuses, which is the only thing that
distinguishes a restated CHECK from a dropped one.

**The head pins.** The head is pinned once, in the reviewed `tests/pins.json`,
and `tests/architecture/test_no_test_spells_the_current_head.py` keeps every
other test from spelling it. That replaces this module's former 56-file head-pin
registry and its three guards, which `W4-F02` prompted after a file declared
`CURRENT_HEAD_REVISION` twice so that an edit to one silently did nothing.
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
from tests.pins import ALEMBIC_CHAIN, ALEMBIC_HEAD, ALEMBIC_REVISION_COUNT

from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "f7a2c9d51e64"
CURRENT_HEAD: Final = ALEMBIC_HEAD
#: The chain parent. `4e9a1c7b2d60` (AUTH-IMP) landed on `c5b71e0a8d43` while
#: this revision was in review, so this migration was repointed onto it. The
#: chain parent and the *vocabulary* predecessor are no longer the same
#: revision, and the two are used for different assertions below.
PREVIOUS: Final = "4e9a1c7b2d60"
#: The revision that last stated the two audited closed sets, and therefore the
#: only correct source for this revision's BEFORE literals. `4e9a1c7b2d60`
#: restates `webauthn_challenge_purpose_is_known` and adds
#: `auth_grant_purpose_is_known`; it does not touch `capability_is_known` or
#: `purpose_is_known`, so the vocabulary is unchanged across it.
VOCABULARY_PREDECESSOR: Final = "c5b71e0a8d43"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = (
    MIGRATIONS / "20260907_f7a2c9d51e64_admit_the_constraint_authoring_capabilities.py"
)
#: The one sanctioned edit to a historical revision (operator ruling
#: OPERATOR_RULING_WP04_A_to_E.md section E). Like D-48, the Meeting-records
#: work freezes `a_managed_document_is_identified_within_its_owner` out of
#: `4c7b2e91d8a5`: that revision no longer creates the owner unique, and the
#: Meeting revision `7d9a450dfd07` adds it unconditionally. Exactly this path is
#: exempt; an edit to any other historical revision still fails the guard below.
SANCTIONED_HISTORICAL_EDIT: Final = (
    MIGRATIONS / "20260811_4c7b2e91d8a5_create_the_managed_document_tables.py"
)
PREVIOUS_MIGRATION: Final = (
    MIGRATIONS / "20260906_c5b71e0a8d43_admit_the_constraint_read_capabilities.py"
)

ADMITTED_CAPABILITIES: Final[tuple[str, ...]] = (
    "constraint_categories.create",
    "constraint_categories.deactivate",
    "constraint_categories.reorder",
    "constraint_categories.update",
    "constraints.close",
    "constraints.close_follow_up",
    "constraints.create",
    "constraints.publish",
    "constraints.reopen",
    "constraints.transition",
    "constraints.update",
    "constraints.void",
)
ADMITTED_PURPOSES: Final[tuple[str, ...]] = ("constraint_authoring",)

SETTLED_CAPABILITY: Final = "capabilities.get"
SETTLED_PURPOSE: Final = "status_observation"
CONSTRAINT_READ_CAPABILITY: Final = "constraints.read"
CONSTRAINT_READ_PURPOSE: Final = "constraint_read"
PRINCIPAL_A: Final = "prn_cccc0001cccc0001cccc0001"
WHEN: Final = datetime(2026, 9, 7, 12, tzinfo=UTC)
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
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_the_chain_holds_the_files_it_claims() -> None:
    assert len(list(MIGRATIONS.glob("*.py"))) == ALEMBIC_REVISION_COUNT


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


#: The two audited closed sets, matched as whole identifiers. `purpose_is_known`
#: is a suffix of `auth_grant_purpose_is_known` and
#: `webauthn_challenge_purpose_is_known`, which `4e9a1c7b2d60` does state, so a
#: substring test would report a restatement that never happened.
AUDITED_CONSTRAINTS: Final[tuple[str, ...]] = ("capability_is_known", "purpose_is_known")


def test_no_revision_between_the_vocabulary_predecessor_and_this_one_restates_the_sets() -> None:
    """The premise the byte copy above rests on, asserted instead of assumed.

    The BEFORE literals are copied from `VOCABULARY_PREDECESSOR` rather than
    from the chain parent, because `4e9a1c7b2d60` landed between the two while
    this revision was in review and states neither audited set. That is a claim
    about a *different* revision, and the byte-copy test cannot fail on it: if a
    future revision restated either set between these two, the copy would still
    match its source and the literals would silently go stale. This is the test
    that would fail instead.
    """
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
    # Measured, not assumed: exactly the auth revision sits in the gap today.
    assert between == [PREVIOUS]
    for revision in between:
        source = Path(script.get_revision(revision).path).read_text(encoding="utf-8")
        for constraint in AUDITED_CONSTRAINTS:
            found = re.search(rf"(?<![A-Za-z0-9_]){re.escape(constraint)}", source)
            assert found is None, (
                f"{revision} restates {constraint}, so it — not {VOCABULARY_PREDECESSOR} — "
                f"is the correct source for this revision's BEFORE literals"
            )


def test_the_at_texts_add_exactly_the_thirteen_new_values_and_stay_sorted() -> None:
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


def test_the_at_texts_admit_no_synchronisation_vocabulary() -> None:
    """`PC-CM-IMP-WP11`'s plane is not admitted here, and the absence is deliberate."""
    source = MIGRATION.read_text(encoding="utf-8")
    at = _literals(_constant(source, "_CAPABILITIES_AT_THIS_REVISION"))
    assert [value for value in at if value.startswith("constraint_sync")] == []
    purposes = _literals(_constant(source, "_PURPOSES_AT_THIS_REVISION"))
    assert [value for value in purposes if "sync" in value] == []


def test_the_revision_restates_both_named_checks_and_nothing_else() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    assert '("capability_is_known", capability)' in source
    assert '("purpose_is_known", purpose)' in source
    assert "_restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)" in source
    assert "_restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)" in source


def test_the_revision_touches_only_the_audit_events_table() -> None:
    """One table, and no Constraint table anywhere in it."""
    source = MIGRATION.read_text(encoding="utf-8")
    # Word-boundary and not a bare substring: `constraint_categories.create` is a
    # capability *value* this revision admits, and a naive containment check
    # would read it as the table of nearly the same name.
    named = sorted(
        table for table in CONSTRAINT_TABLES if re.search(rf"\b{re.escape(table)}\b(?!\.)", source)
    )
    assert named == []
    tables = set(re.findall(r"ALTER TABLE \{SCHEMA\}\.(\w+)", source))
    assert tables == {"audit_events"}


def _git_migrations_diff(*options: str) -> subprocess.CompletedProcess[str]:
    command = ["git", "diff", "--name-only", "--no-renames", *options, "origin/main...HEAD"]
    return subprocess.run(  # noqa: S603
        [*command, "--", "migrations/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _revision_id(relative: str) -> str:
    """The `revision = "..."` an added revision file declares."""
    source = (ROOT / relative).read_text(encoding="utf-8")
    found = re.search(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)[\"']", source, re.M)
    assert found is not None, f"{relative} declares no `revision`"
    return found.group(1)


def test_no_historical_revision_was_edited() -> None:
    """The chain below the head is untouched, measured against git.

    Derived rather than listed: a branch may only add revision files, and only
    ones that extend the chain at its head (the last `len(added)` entries of
    the reviewed `tests.pins.ALEMBIC_CHAIN`). Any other modified, deleted or
    renamed path must be the one `SANCTIONED_HISTORICAL_EDIT`.
    """
    changed = _git_migrations_diff()
    if changed.returncode != 0:
        pytest.skip("no merge base available in this checkout")
    added_run = _git_migrations_diff("--diff-filter=A")
    assert added_run.returncode == 0, added_run.stderr
    touched = {line for line in changed.stdout.splitlines() if line.strip()}
    added = {line for line in added_run.stdout.splitlines() if line.strip()}
    edited = touched - added
    assert edited <= {SANCTIONED_HISTORICAL_EDIT.relative_to(ROOT).as_posix()}, (
        f"a historical revision changed: {sorted(edited)}"
    )
    revision_files = sorted(
        path for path in added if path.startswith("migrations/versions/") and path.endswith(".py")
    )
    added_revisions = {_revision_id(path) for path in revision_files}
    tail = (
        set(ALEMBIC_CHAIN[len(ALEMBIC_CHAIN) - len(revision_files) :]) if revision_files else set()
    )
    assert added_revisions <= tail, (
        f"an added revision does not extend the chain at its head: {sorted(added_revisions)}"
    )


# ---- the database -----------------------------------------------------------


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_head_admits_the_constraint_authoring_vocabulary(migrated_engine: Engine) -> None:
    for capability in ADMITTED_CAPABILITIES:
        _audit(migrated_engine, capability=capability, purpose=ADMITTED_PURPOSES[0])


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_downgrade_restores_the_previous_vocabulary(migrated_engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS)
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    # The read half `c5b71e0a8d43` admitted is still admitted after the
    # downgrade: this revision widened and nothing else.
    _audit(
        migrated_engine,
        capability=CONSTRAINT_READ_CAPABILITY,
        purpose=CONSTRAINT_READ_PURPOSE,
    )
    with pytest.raises(IntegrityError) as capability_refusal:
        _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=SETTLED_PURPOSE)
    assert "capability_is_known" in str(capability_refusal.value)
    with pytest.raises(IntegrityError) as purpose_refusal:
        _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=ADMITTED_PURPOSES[0])
    assert "purpose_is_known" in str(purpose_refusal.value)
    command.upgrade(_config(), "head")
    _audit(migrated_engine, capability=ADMITTED_CAPABILITIES[0], purpose=ADMITTED_PURPOSES[0])


@pytest.mark.migration
@pytest.mark.migration_edge
@pytest.mark.database
def test_the_settled_vocabulary_still_answers_at_head(migrated_engine: Engine) -> None:
    """A widening widens. Nothing the previous head admitted is refused now."""
    _audit(migrated_engine, capability=SETTLED_CAPABILITY, purpose=SETTLED_PURPOSE)
    _audit(
        migrated_engine,
        capability=CONSTRAINT_READ_CAPABILITY,
        purpose=CONSTRAINT_READ_PURPOSE,
    )


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
