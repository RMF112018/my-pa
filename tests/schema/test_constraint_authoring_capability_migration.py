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

**The head pins.** Advancing a head means editing every file that names the old
one, and `W4-F02` recorded what that costs when a file names it twice:
`tests/schema/test_webauthn_auth_persistence_migration.py` declared
`CURRENT_HEAD_REVISION` on two consecutive lines, so an edit to one silently did
nothing. The duplicate is gone and the recurrence guard below is deliberately
minimal -- one parametrized check over the fixed file list, not a repository-wide
lint.
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
REVISION: Final = "f7a2c9d51e64"
CURRENT_HEAD: Final = "b8e4d6f20a11"
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
CURRENT_HEAD_MIGRATION: Final = MIGRATIONS / "20260908_b8e4d6f20a11_add_constraint_sync_backend.py"
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

#: Every file that pins the chain's current head, and the constant each uses.
#: Fixed and written out, so the recurrence guard below is a bounded check over a
#: named list rather than a repository-wide scan.
HEAD_PIN_FILES: Final[tuple[str, ...]] = (
    "tests/architecture/test_constraint_read_plane_boundaries.py",
    "tests/database/test_cli_auth.py",
    "tests/database/test_entities_graph_vocabulary_migration.py",
    "tests/database/test_legacy_entity_backfill_migration.py",
    "tests/database/test_phase_b_audit_vocabulary_migration.py",
    "tests/database/test_ri_ent_wp_10_11_vocabulary_migration.py",
    "tests/schema/test_auth_identity_and_grants_migration.py",
    "tests/schema/test_canvas_workspace_migration.py",
    "tests/schema/test_constraint_management_migration.py",
    "tests/schema/test_constraint_read_capability_migration.py",
    "tests/schema/test_constraint_sync_migration.py",
    "tests/schema/test_extraction_schema_migration.py",
    "tests/schema/test_goodnotes_browser_contract_migration.py",
    "tests/schema/test_goodnotes_client_resume_migration.py",
    "tests/schema/test_goodnotes_content_and_durable_note_stages.py",
    "tests/schema/test_goodnotes_delivery_attempt_migration.py",
    "tests/schema/test_goodnotes_delivery_migration.py",
    "tests/schema/test_goodnotes_entity_kind_migration.py",
    "tests/schema/test_goodnotes_exact_render_migration.py",
    "tests/schema/test_goodnotes_lineage_migration.py",
    "tests/schema/test_goodnotes_note_occurrence_migration.py",
    "tests/schema/test_goodnotes_occurrence_grounding_migration.py",
    "tests/schema/test_goodnotes_promotion_receipt_migration.py",
    "tests/schema/test_goodnotes_pull_migration.py",
    "tests/schema/test_goodnotes_semantic_proposal_migration.py",
    "tests/schema/test_oauth_refresh_migration.py",
    "tests/schema/test_webauthn_auth_persistence_migration.py",
    "tests/schema/test_work_task_commitment_migration.py",
    "tests/unit/test_cli_auth.py",
)

#: The constant names those files use for the chain's head.
HEAD_CONSTANTS: Final[tuple[str, ...]] = (
    "CURRENT_HEAD_REVISION",
    # `CURRENT_HEAD` is a fourth spelling, and omitting it let a pin escape the
    # advance once. The guards below read this tuple, so a spelling absent here
    # is a spelling they do not check.
    "CURRENT_HEAD",
    "HEAD_REVISION",
    "HEAD",
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
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CURRENT_HEAD).down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_the_chain_holds_the_files_it_claims() -> None:
    assert len(list(MIGRATIONS.glob("*.py"))) == 101


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


def test_no_historical_revision_was_edited() -> None:
    """The chain below this revision is untouched, measured against git."""
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
    assert touched <= {CURRENT_HEAD_MIGRATION.relative_to(ROOT).as_posix()}, (
        f"a revision other than this one changed: {sorted(touched)}"
    )


# ---- the head pins, and W4-F02's recurrence guard ---------------------------


@pytest.mark.parametrize("relative", HEAD_PIN_FILES)
def test_no_head_pin_file_declares_its_head_constant_more_than_once(relative: str) -> None:
    """`W4-F02`: two identical declarations mean an edit to one changes nothing.

    Deliberately bounded to the files that pin the head. The underlying blind
    spot — mypy excludes tests, and the selected pyflakes rules do not cover
    module-level rebinding — is recorded as an observation rather than answered
    with a repository-wide lint.
    """
    source = (ROOT / relative).read_text(encoding="utf-8")
    for constant in HEAD_CONSTANTS:
        declarations = re.findall(rf"^{constant}(?::\s*Final)?\s*=", source, re.M)
        assert len(declarations) <= 1, f"{relative} declares {constant} {len(declarations)} times"


@pytest.mark.parametrize("relative", HEAD_PIN_FILES)
def test_no_head_pin_file_still_names_the_previous_head_as_the_head(relative: str) -> None:
    """The pin advanced; the historical edges below it did not have to move.

    `tests/schema/test_constraint_read_capability_migration.py` still names
    `c5b71e0a8d43` — as the revision *it* tests — so the check is on the head
    constants rather than on the string.
    """
    source = (ROOT / relative).read_text(encoding="utf-8")
    for constant in HEAD_CONSTANTS:
        for line in re.findall(rf"^{constant}(?::\s*Final)?\s*=.*$", source, re.M):
            assert REVISION not in line, f"{relative} still pins {REVISION} as the head"


def test_the_head_pin_list_is_the_files_that_actually_pin_the_head() -> None:
    """The list above cannot quietly shrink while a file still names the head."""
    naming = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("test_*.py")
        if CURRENT_HEAD in path.read_text(encoding="utf-8") and path.name != Path(__file__).name
    )
    assert naming == sorted(HEAD_PIN_FILES)


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
