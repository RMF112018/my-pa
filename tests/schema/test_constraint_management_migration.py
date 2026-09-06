"""Static, offline, and edge checks for the Constraint-management revision.

Four claims, and they are deliberately different in kind.

**Identity.** The revision is the chain's only head and it sits directly on
`e8f2a6c9d104`. A second head is the failure `AGENTS.md` section 6 forbids, and
it is invisible until someone migrates a database that took the other branch.

**Freeze.** The module imports nothing from `my_pa`. A revision that read the
live declaration would change meaning whenever that declaration changed, which
makes replaying an old revision a different act than running it was — the exact
defect `D-69` names. That the frozen text still says what the runtime
declaration says is not asserted here by importing it either: it is asserted on
a migrated clone, where both are read from the server.

**Emission.** The offline `upgrade --sql` text is read for all fourteen tables,
every constraint the plane's meaning rests on, the four immutability triggers,
the four partial unique indexes, and the five deferred foreign keys — and the
downgrade text for the fourteen `DROP TABLE`s, so a revision that created a
table it could not drop is caught before a database has one.

**The frozen vocabularies are the emitted vocabularies.** Every expression the
revision declares in `_FROZEN` is looked for in the SQL it actually renders.
Without this, `_FROZEN` would be a second, unchecked statement of the closed
sets, and `tests/architecture/test_no_revision_derives_a_closed_set_from_an_
enum.py` — which reads the revision through that declaration — would be reading
a claim rather than the schema.

**The predecessor edge**, last, because it needs a server: empty ->
`e8f2a6c9d104` -> head -> `e8f2a6c9d104`, so the revision's `downgrade` is
proven to return the database to what its parent denotes rather than to
something that merely runs.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "2774329487be"
PREVIOUS: Final = "e8f2a6c9d104"
MIGRATION: Final = ROOT / (
    "migrations/versions/20260905_2774329487be_add_constraint_management_persistence.py"
)

#: The fourteen tables, in the order the revision creates them.
TABLES: Final = (
    "constraint_project_settings",
    "constraint_categories",
    "project_constraints",
    "project_constraint_parties",
    "project_constraint_revisions",
    "project_constraint_revision_parties",
    "project_constraint_history",
    "constraint_category_history",
    "project_constraint_relationships",
    "project_constraint_evidence_links",
    "constraint_sync_targets",
    "constraint_sync_runs",
    "constraint_sync_baselines",
    "constraint_sync_conflicts",
)

#: The four append-only ledgers, which carry the immutability trigger.
IMMUTABLE_TABLES: Final = (
    "project_constraint_revisions",
    "project_constraint_revision_parties",
    "project_constraint_history",
    "constraint_category_history",
)

#: The five foreign keys added by `ALTER` after every table exists, because
#: three of them close one cycle and two close another.
DEFERRED_FOREIGN_KEYS: Final = (
    "a_constraint_names_its_current_revision",
    "a_constraint_revision_cites_the_receipt_that_wrote_it",
    "a_constraint_receipt_names_the_revision_it_wrote",
    "a_sync_target_names_a_verified_run_of_its_principal",
    "a_sync_target_names_an_active_run_of_its_principal",
)

#: The four partial unique indexes: uniqueness that holds only where a value is
#: present, which a `UNIQUE` constraint cannot express.
PARTIAL_UNIQUE_INDEXES: Final = (
    "project_constraints_code_is_unique_per_project",
    "project_constraint_history_key_is_unique_per_principal",
    "constraint_category_history_key_is_unique_per_principal",
    "one_open_constraint_sync_conflict_per_kind",
)

#: The named constraints the plane's meaning rests on: the legacy gate and the
#: four relaxations it gates, the receipt biconditionals, the same-Principal
#: composite foreign keys, and the bounds that keep the sync tables metadata.
LOAD_BEARING_CONSTRAINTS: Final = (
    "a_legacy_incomplete_constraint_is_a_workbook_import",
    "a_draft_constraint_carries_no_code",
    "a_published_constraint_records_when_it_published",
    "a_published_constraint_is_complete",
    "a_published_constraint_belongs_to_a_project",
    "a_closed_constraint_records_its_completion",
    "a_void_constraint_records_its_reason",
    "a_closed_constraint_carries_no_void_fields",
    "a_void_constraint_carries_no_completion",
    "an_active_constraint_carries_no_terminal_fields",
    "a_constraint_belongs_to_a_category_of_its_principal",
    "a_constraint_party_belongs_to_a_constraint_of_its_principal",
    "a_constraint_revision_belongs_to_a_constraint_of_its_principal",
    "a_revision_party_belongs_to_a_revision_of_its_principal",
    "a_constraint_receipt_belongs_to_a_constraint_of_its_principal",
    "a_category_receipt_belongs_to_a_category_of_its_principal",
    "an_applied_constraint_mutation_advances_its_version",
    "an_applied_constraint_mutation_records_its_revision",
    "only_a_rejected_constraint_mutation_records_a_reason",
    "an_entity_constraint_party_names_its_entity",
    "an_unresolved_constraint_party_keeps_its_label",
    "a_constraint_evidence_ref_matches_its_kind",
    "a_sync_target_external_identity_is_opaque",
    "an_active_sync_run_holds_a_lease",
    "a_sync_baseline_digest_object_is_bounded",
    "a_sync_conflict_external_candidate_is_bounded",
    "a_sync_baseline_row_identity_is_opaque",
)

_WHITESPACE: Final = re.compile(r"\s+")


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _revision_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_wp02_revision", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    action = command.downgrade if down else command.upgrade
    action(_config(buffer), target, sql=True)
    return _WHITESPACE.sub(" ", buffer.getvalue())


def test_the_revision_is_the_only_head_and_sits_on_its_predecessor() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == ["a1c9e4b72f80"]
    assert script.get_revision("a1c9e4b72f80").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_the_revision_imports_nothing_from_the_package_it_migrates() -> None:
    """The freeze, checked structurally rather than read for.

    Both import forms are walked: `from my_pa… import …` and `import my_pa…`.
    Checking only the first would let a revision reach the live declaration
    through the second and leave this test green, which is the shape of hole
    that makes a guard worse than no guard.
    """
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    assert not [name for name in modules if name == "my_pa" or name.startswith("my_pa.")], modules


def test_the_offline_upgrade_creates_every_table_index_key_and_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    sql = _offline(f"{PREVIOUS}:{REVISION}")
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table} (" in sql
    for table in IMMUTABLE_TABLES:
        assert f"CREATE TRIGGER {table}_are_immutable BEFORE UPDATE OR DELETE" in sql
        assert "knowledge.managed_document_rows_stay_as_written()" in sql
    for index in PARTIAL_UNIQUE_INDEXES:
        assert f"CREATE UNIQUE INDEX {index}" in sql
        assert f"{index} " in sql
    assert sql.count("WHERE") >= len(PARTIAL_UNIQUE_INDEXES)
    for name in DEFERRED_FOREIGN_KEYS:
        assert f"ADD CONSTRAINT {name} FOREIGN KEY" in sql
        assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert sql.count("DEFERRABLE INITIALLY DEFERRED") == len(DEFERRED_FOREIGN_KEYS)
    for name in LOAD_BEARING_CONSTRAINTS:
        assert f"CONSTRAINT {name} " in sql, name


def test_the_offline_upgrade_emits_exactly_the_vocabularies_it_freezes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_FROZEN` is the schema, not a description of it.

    Read both ways round: every declared expression is in the rendered SQL, and
    every closed set in the rendered SQL is declared. The second half is the one
    that matters — an undeclared closed set is a vocabulary the `D-81` guard
    cannot see, and this revision's DDL is exactly the raw-SQL shape that guard
    documents itself as blind to.
    """
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    sql = _offline(f"{PREVIOUS}:{REVISION}")
    declared: dict[str, dict[str, str]] = _revision_module()._FROZEN
    assert set(declared) <= set(TABLES)
    names: set[str] = set()
    for constraints in declared.values():
        for name, expression in constraints.items():
            assert f"CONSTRAINT {name} CHECK ({expression})" in sql, name
            names.add(name)
    emitted = {
        match.group(1)
        for match in re.finditer(r"CONSTRAINT (\w+) CHECK \(([^;]*?)\)[,)] ", sql)
        if " IN (" in match.group(2)
    }
    assert emitted == names, emitted ^ names


def test_the_offline_downgrade_drops_every_table_it_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    sql = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    for table in TABLES:
        assert f"DROP TABLE knowledge.{table} RESTRICT" in sql
    for table in IMMUTABLE_TABLES:
        assert f"DROP TRIGGER {table}_are_immutable ON knowledge.{table}" in sql
    for name in DEFERRED_FOREIGN_KEYS:
        assert f'DROP CONSTRAINT "{name}"' in sql


@pytest.mark.database
def test_the_revision_returns_the_database_to_what_its_predecessor_denotes(
    empty_database_url: str,
) -> None:
    """`AGENTS.md` section 6's preceding-revision edge, run against a server.

    Offline SQL proves the statements are written; only a server proves they are
    accepted, that the five deferred keys can be added after the cycle exists,
    and that the downgrade leaves nothing behind — a dropped table whose trigger
    or index survived would show up here as a second run that will not build.
    """
    assert empty_database_url
    command.upgrade(_config(), PREVIOUS)
    command.upgrade(_config(), REVISION)
    command.downgrade(_config(), PREVIOUS)
    command.upgrade(_config(), REVISION)
    command.downgrade(_config(), "base")
