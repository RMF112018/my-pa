"""WP-RE-08 G-A02-3 (RE-AC-106, Amendment 02 (3)): a Record Event is never lost.

No application, repository, CLI, ops or script path updates, deletes or
truncates `record_events` or `record_event_sequences`, or re-keys a principal --
except the allocator's own `next_sequence` upsert. FAST, by `ast` and by
string scan:

1. **Importers.** Only `infrastructure/persistence/record_events.py` imports the
   two `Table` objects from `tables.py`.
2. **Builders.** In that module the only statements built on them are
   `pg_insert(record_event_sequences)` with `on_conflict_do_update(set_=...)`
   whose keys are exactly `{"next_sequence"}` -- so the principal can never be
   re-keyed -- and `insert(record_events)`. No `update`, `delete` or
   attribute-form `.update()`/`.delete()` on either.
3. **Raw SQL.** No string literal in `src/`, `apps/`, `ops/` or `scripts/`
   updates, deletes from or truncates either table, except the Record Event
   privilege gate. That gate's literals are arguments of `_expect_sqlstate`
   and must come back `42501`. In `migrations/`, only the feed admission
   revision, the TRUNCATE-refusal revision and the Knowledge revision (A3,
   read-only: a CHECK restatement, a foreign key and a refusal read) name the
   relations, and the Knowledge revision never rewrites them. The
   admission revision's downgrade starts with its refusal and its append-only
   trigger stays `BEFORE UPDATE OR DELETE` on `record_events`. No revision
   drops that trigger. The refusal revision's downgrade starts with its own
   row-preserving refusal.

The database half is existing: the append-only trigger
(`tests/database/test_record_event_persistence.py`), the downgrade refusals
(`tests/schema/test_record_events_migration.py`), and the executed TRUNCATE
refusals (`tests/database/test_record_event_role_privileges.py`). A
`TRUNCATE` literal outside the privilege gate's refusal probes still fails
this module.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
TABLES_MODULE: Final = "my_pa.infrastructure.persistence.tables"
FEED_TABLES: Final = frozenset({"record_events", "record_event_sequences"})
#: The SQLAlchemy write-statement constructors (reads are not rewrites).
WRITE_BUILDERS: Final = frozenset({"insert", "pg_insert", "update", "delete"})
OWNER: Final = "src/my_pa/infrastructure/persistence/record_events.py"
GATE: Final = "src/my_pa/infrastructure/database/record_event_privilege_gate.py"
REFUSAL_PROBES: Final = frozenset(
    {
        "TRUNCATE TABLE knowledge.record_events",
        "TRUNCATE TABLE knowledge.record_event_sequences",
        "UPDATE knowledge.record_events SET record_version = record_version "
        "WHERE record_events.principal_id = :principal_id",
        "DELETE FROM knowledge.record_events WHERE record_events.principal_id = :principal_id",
    }
)
#: The Record Event revision is found by its content, not pinned by filename:
#: naming the head here would make this a head-pin file for every later
#: revision to edit.
REVISION_DOCSTRING: Final = "Admit the Record Event feed"
#: KLP-WP-02's single Knowledge revision also names the feed, read-only: it
#: restates `a_record_event_family_is_known` (+`knowledge_assertion`, A3), cites
#: `record_events (event_id, principal_id)` by foreign key from
#: `knowledge_submission_trigger_events`, and reads it in its downgrade refusal.
#: It is found by content for the same reason, and it may never rewrite the feed.
KNOWLEDGE_REVISION_DOCSTRING: Final = "Admit the Knowledge Assertion layer"
RAW_REWRITE: Final = re.compile(
    r"\b(UPDATE|DELETE\s+FROM|TRUNCATE(\s+TABLE)?)\s+(ONLY\s+)?(\w+\.)?record_event(s|_sequences)\b",
    re.IGNORECASE,
)
#: MR-C20 (operator ruling on D-1, 2026-10-01). A revision names the feed when it
#: refers to either table. The capability token `record_events.list` is not a
#: table reference: the negative lookahead keeps a vocabulary restatement from
#: matching, and `record_event_sequences` has no such token. Raw SQL, a
#: SQLAlchemy `Table` or `table()`, and `{SCHEMA}.record_events` still match.
FEED_TABLE_REFERENCE: Final = re.compile(r"\brecord_events\b(?!\.list)|\brecord_event_sequences\b")
DROP_TRIGGER: Final = re.compile(r"DROP\s+TRIGGER\s+(IF\s+EXISTS\s+)?record_events_are_append_only")


def _code_sources() -> dict[str, str]:
    return {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for root in ("src", "apps", "ops", "scripts")
        if (ROOT / root).is_dir()
        for path in sorted((ROOT / root).rglob("*.py"))
    }


def _importers(sources: dict[str, str]) -> set[str]:
    found: set[str] = set()
    for path, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == TABLES_MODULE
                and any(alias.name in FEED_TABLES for alias in node.names)
            ):
                found.add(path)
    return found


def _statements(source: str) -> set[str]:
    """Every statement builder applied to a feed table, as `builder(table)`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in WRITE_BUILDERS and node.args:
            target = node.args[0]
            if isinstance(target, ast.Name) and target.id in FEED_TABLES:
                found.add(f"{func.id}({target.id})")
        if (
            isinstance(func, ast.Attribute)
            and func.attr in {"insert", "update", "delete"}
            and isinstance(func.value, ast.Name)
            and func.value.id in FEED_TABLES
        ):
            found.add(f"{func.value.id}.{func.attr}()")
    return found


def _upsert_keys(source: str) -> list[set[str]]:
    keys: list[set[str]] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "on_conflict_do_update"
        ):
            for keyword in node.keywords:
                if keyword.arg == "set_":
                    value = keyword.value
                    keys.append(
                        {str(k.value) for k in value.keys if isinstance(k, ast.Constant)}
                        if isinstance(value, ast.Dict)
                        else {"*"}
                    )
    return keys


def _raw_rewrites(sources: dict[str, str]) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and RAW_REWRITE.search(node.value)
            ):
                found.append((path, node.lineno, node.value.strip()[:80]))
    return found


# ---- 1. importers ------------------------------------------------------------------


def test_only_the_feed_module_imports_the_feed_tables() -> None:
    assert _importers(_code_sources()) == {OWNER}


# ---- 2. builders -------------------------------------------------------------------


def test_the_feed_module_builds_only_the_upsert_and_the_insert() -> None:
    source = (ROOT / OWNER).read_text(encoding="utf-8")
    assert _statements(source) == {"pg_insert(record_event_sequences)", "insert(record_events)"}
    assert _upsert_keys(source) == [{"next_sequence"}], "a principal must never be re-keyed"


# ---- 3. raw SQL --------------------------------------------------------------------


def _refusal_probes(source: str) -> set[str]:
    """String arguments of `_expect_sqlstate(..., _INSUFFICIENT)`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "_expect_sqlstate" or len(node.args) < 3:
            continue
        statement, sqlstate = node.args[1], node.args[2]
        if (
            isinstance(statement, ast.Constant)
            and isinstance(statement.value, str)
            and isinstance(sqlstate, ast.Name)
            and sqlstate.id == "_INSUFFICIENT"
        ):
            found.add(statement.value)
    return found


def test_no_code_path_updates_deletes_or_truncates_the_feed() -> None:
    sources = _code_sources()
    gate = sources.pop(GATE)
    assert _raw_rewrites(sources) == []
    probes = _refusal_probes(gate)
    assert probes >= REFUSAL_PROBES
    assert {item[2] for item in _raw_rewrites({GATE: gate})} == {
        statement[:80] for statement in probes if RAW_REWRITE.search(statement)
    }


def test_only_the_record_event_revisions_name_the_feed_and_keep_the_guards() -> None:
    revisions = {
        path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "migrations" / "versions").glob("*.py"))
    }
    naming = {path for path, text in revisions.items() if FEED_TABLE_REFERENCE.search(text)}
    admission = next(path for path, text in revisions.items() if REVISION_DOCSTRING in text)
    refusal = next(
        path for path, text in revisions.items() if "Refuse TRUNCATE of the Record Event" in text
    )
    knowledge = next(
        path for path, text in revisions.items() if KNOWLEDGE_REVISION_DOCSTRING in text
    )
    assert naming == {admission, refusal, knowledge}, sorted(naming)
    assert not RAW_REWRITE.search(revisions[knowledge]), knowledge
    for path, text in revisions.items():
        assert not DROP_TRIGGER.search(text), path
    tree = ast.parse(revisions[admission])
    downgrade = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    first = downgrade.body[0]
    assert (
        isinstance(first, ast.Expr) and ast.unparse(first.value) == "op.execute(_REFUSE_DOWNGRADE)"
    )
    assert "BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}" in revisions[admission]
    append_only = next(
        node
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "_APPEND_ONLY"
    )
    assert "'record_events'" in ast.unparse(append_only)
    refusal_tree = ast.parse(revisions[refusal])
    refusal_downgrade = next(
        node
        for node in refusal_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    refusal_first = refusal_downgrade.body[0]
    assert (
        isinstance(refusal_first, ast.Expr)
        and ast.unparse(refusal_first.value) == "op.execute(_REFUSE_DOWNGRADE)"
    )
    assert "BEFORE TRUNCATE ON {SCHEMA}.{table}" in revisions[refusal]
    assert "DELETE FROM" not in revisions[refusal].upper()
    assert "TRUNCATE TABLE" not in revisions[refusal].upper()
    assert "TRUNCATE KNOWLEDGE" not in revisions[refusal].upper()


# ---- controls ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "planted",
    [
        "record_events.update()",
        "delete(record_event_sequences)",
        "update(record_events)",
        "record_event_sequences.delete()",
    ],
)
def test_the_builder_scan_sees_a_rewrite(planted: str) -> None:
    assert _statements(planted) - {
        "pg_insert(record_event_sequences)",
        "insert(record_events)",
    }


@pytest.mark.parametrize(
    "planted",
    [
        'text("DELETE FROM knowledge.record_events")',
        'text("TRUNCATE knowledge.record_events")',
        'text("truncate table record_event_sequences")',
        'text("UPDATE knowledge.record_events SET principal_id = 1")',
    ],
)
def test_the_raw_scan_sees_a_rewrite(planted: str) -> None:
    assert _raw_rewrites({"planted.py": planted})


def test_the_upsert_scan_sees_a_rekey() -> None:
    planted = 'x.on_conflict_do_update(set_={"next_sequence": 1, "principal_id": p})'
    assert _upsert_keys(planted) == [{"next_sequence", "principal_id"}]


def test_the_importer_scan_sees_a_second_importer() -> None:
    planted = {"src/other.py": f"from {TABLES_MODULE} import record_events\n"}
    assert _importers(planted) == {"src/other.py"}


# ---- MR-C20 controls ----------------------------------------------------------------


@pytest.mark.parametrize(
    "planted",
    [
        'op.execute("CREATE TABLE knowledge.record_events (event_id TEXT)")',
        'op.execute("ALTER TABLE knowledge.record_event_sequences ADD COLUMN x INT")',
        "record_events = Table('record_events', metadata)",
        "table('record_event_sequences')",
        "{SCHEMA}.record_events",
    ],
)
def test_a_feed_table_reference_is_detected(planted: str) -> None:
    """MR-C20 control (i): raw SQL and a table object still name the feed."""
    assert FEED_TABLE_REFERENCE.search(planted)


def test_a_capability_token_is_not_a_feed_table_reference() -> None:
    """MR-C20 control (ii): the vocabulary literal is not a table reference."""
    planted = "capability IN ('record_events.list')"
    assert FEED_TABLE_REFERENCE.search(planted) is None
