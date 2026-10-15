"""The MCP interaction log has exactly one DELETE in the source tree, and no UPDATE.

`observability.mcp_interactions` is append-only at the database (revision
`c8f7ae406d47`): UPDATE and TRUNCATE always refuse, and DELETE refuses unless
the transaction set the purge switch and the row is past retention. This FAST
scan holds the source side of the same contract: the only statement that
deletes from the table is the one inside
`my_pa.infrastructure.persistence.mcp_interactions.purge_expired`, and nothing
in `src/` or `apps/` updates or truncates it.

It reads source text. It does not see a statement assembled from fragments at
run time (an f-string or concatenation that splits the table name from the
verb); the triggers are what refuse those.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
SCANNED: Final = (ROOT / "src", ROOT / "apps")
STORE: Final = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "mcp_interactions.py"
PURGE: Final = "purge_expired"

_TABLE: Final = r"observability\s*\.\s*mcp_interactions\b"
#: Raw SQL and SQLAlchemy Core spellings of a DELETE against the table.
DELETE: Final = re.compile(
    rf"\bDELETE\s+FROM\s+(?:ONLY\s+)?{_TABLE}"
    r"|\bdelete\(\s*mcp_interactions\b"
    r"|\bmcp_interactions\s*\.\s*delete\s*\(",
    re.IGNORECASE,
)
#: Raw SQL and SQLAlchemy Core spellings of an UPDATE or TRUNCATE against the table.
MUTATE: Final = re.compile(
    rf"\bUPDATE\s+(?:ONLY\s+)?{_TABLE}"
    rf"|\bTRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?{_TABLE}"
    r"|\bupdate\(\s*mcp_interactions\b"
    r"|\bmcp_interactions\s*\.\s*update\s*\(",
    re.IGNORECASE,
)


def _sources() -> list[Path]:
    return sorted(path for root in SCANNED for path in root.rglob("*.py"))


def _hits(pattern: re.Pattern[str]) -> list[tuple[Path, int]]:
    found: list[tuple[Path, int]] = []
    for path in _sources():
        source = path.read_text(encoding="utf-8")
        for match in pattern.finditer(source):
            found.append((path, source.count("\n", 0, match.start()) + 1))
    return found


def _function_span(path: Path, name: str) -> tuple[int, int]:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            assert node.end_lineno is not None
            return node.lineno, node.end_lineno
    raise AssertionError(f"{path.name} defines no {name}()")


def test_the_scan_reads_the_store_module() -> None:
    """Guards the two tests below against a scan that read nothing."""
    assert STORE in _sources()
    assert len(_sources()) > 100


def test_the_only_delete_is_inside_the_purge() -> None:
    hits = _hits(DELETE)
    first, last = _function_span(STORE, PURGE)
    assert len(hits) == 1, f"expected exactly one DELETE against the log, found {hits}"
    path, line = hits[0]
    assert path == STORE and first <= line <= last, (
        f"the DELETE at {path.relative_to(ROOT)}:{line} is outside {PURGE}() (lines {first}-{last})"
    )


def test_nothing_updates_or_truncates_the_log() -> None:
    assert _hits(MUTATE) == []


@pytest.mark.parametrize(
    ("pattern", "sample"),
    [
        (DELETE, "DELETE FROM observability.mcp_interactions WHERE true"),
        (DELETE, "delete from only observability . mcp_interactions"),
        (DELETE, "delete(mcp_interactions).where(x)"),
        (DELETE, "mcp_interactions.delete()"),
        (MUTATE, "UPDATE observability.mcp_interactions SET outcome = 'ok'"),
        (MUTATE, "truncate table observability.mcp_interactions"),
        (MUTATE, "update(mcp_interactions).values(outcome='ok')"),
        (MUTATE, "mcp_interactions.update()"),
    ],
)
def test_the_patterns_discriminate(pattern: re.Pattern[str], sample: str) -> None:
    assert pattern.search(sample)


@pytest.mark.parametrize(
    "sample",
    [
        "BEFORE UPDATE ON observability.mcp_interactions",
        "BEFORE DELETE ON observability.mcp_interactions",
        "SELECT count(*) FROM observability.mcp_interactions",
        "DELETE FROM observability.mcp_interactions_archive",
    ],
)
def test_the_patterns_ignore_what_is_not_a_mutation_of_the_log(sample: str) -> None:
    assert not DELETE.search(sample)
    assert not MUTATE.search(sample)
