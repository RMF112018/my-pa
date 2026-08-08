"""Every engine this repository builds either bounds a statement or says why not.

`create_database_engine` sets pool options and, until this package, nothing else.
PostgreSQL's own `statement_timeout` default is `0` — no bound at all — so a
query the planner got wrong, or one over a corpus larger than the one it was
measured on, ran until it finished or the client went away, holding one of five
connections in a pool with overflow disabled. The functional indexes remove the
sequential scan as the *only* possibility; they bound nothing.

The setting closes that, and a setting closes it only for the callers that pass
it. There are seven `create_database_engine` calls outside the tests, in six
files, and four of them were not in the list this package was briefed with. A
rule stated as a list of call sites is a rule that is wrong the next time
somebody adds one, which is this campaign's most-repeated finding — a correction
that closes exactly the case its finding named and leaves the adjacent one open.
So the rule is derived from the syntax tree instead:

    every `create_database_engine(...)` in `src/`, `apps/`, `migrations/` and
    `scripts/` either passes `statement_timeout_ms=`, or carries an
    `# statement-timeout-exempt:` comment on the line above it.

**Three callers are exempt and the exemption is the interesting half.** Alembic
(`migrations/env.py`) runs DDL and functional-index builds sized to the corpus,
and a `CREATE INDEX` cancelled halfway leaves the database between revisions —
strictly worse than the unbounded query the bound prevents. `apps/cli/migration.py`
and `scripts/migration/reconcile.py` load and reconcile a 4.37 GB legacy corpus in
statements sized to it. Each says so where it builds its engine; this test only
requires that it say *something* there, because a mechanical rule cannot judge a
reason and one that pretended to would be the aspirational document one layer
down.

**Bounded to non-test code, and that boundary is a decision rather than an
oversight.** Roughly sixty test call sites build engines against disposable
databases, many of them to run the migration chain, and requiring a marker on
each would produce sixty markers that mean nothing. What the tests do is checked
where it can be checked — by the database tier, against a real server.

**What this does not prove.** That the number is right, that the server honours
it, or that a bounded statement is actually cancelled. The first is argued at
`DEFAULT_STATEMENT_TIMEOUT_MS`, and the last two need a server:
`tests/search_quality/test_lexical_search.py` already cancels a real statement
and asserts the classification. This is a wiring rule and claims to be one.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Where production code lives. `tests/` is deliberately absent; the module
#: docstring says why.
SEARCHED = ("src", "apps", "migrations", "scripts")

BUILDER = "create_database_engine"

SETTING = "statement_timeout_ms"

#: The marker that makes an unbounded engine a decision. Deliberately not a bare
#: suppression token of the linter kind: the text after the colon is where the
#: reason goes, and a marker with nothing after it is not accepted.
EXEMPTION = re.compile(r"#\s*statement-timeout-exempt:\s*\S")


def _python_files() -> list[Path]:
    return sorted(path for root in SEARCHED for path in (ROOT / root).rglob("*.py"))


def unbounded_engines(source: str, filename: str) -> list[str]:
    """Every `create_database_engine(...)` in `source` that neither binds nor excuses.

    The exemption is looked for on the line above the call and on the call's own
    first line, which are the two places a reader would write it. It is matched
    against the source text rather than the syntax tree because comments are not
    in the tree at all — the alternative, a marker that lives in the code as a
    keyword argument, would be a second way of spelling the setting.
    """
    lines = source.splitlines()
    tree = ast.parse(source, filename=filename)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not (isinstance(target, ast.Name) and target.id == BUILDER) and not (
            isinstance(target, ast.Attribute) and target.attr == BUILDER
        ):
            continue
        if any(keyword.arg == SETTING for keyword in node.keywords):
            continue
        nearby = lines[max(0, node.lineno - 2) : node.lineno]
        if any(EXEMPTION.search(line) for line in nearby):
            continue
        found.append(f"{filename}:{node.lineno}")
    return found


def test_every_engine_outside_the_tests_is_bounded_or_exempt() -> None:
    """The rule, applied to the tree that states it."""
    unbounded = [
        entry
        for path in _python_files()
        for entry in unbounded_engines(
            path.read_text(encoding="utf-8"), str(path.relative_to(ROOT))
        )
    ]
    assert unbounded == [], f"engines with no statement_timeout and no exemption: {unbounded}"


def test_the_three_exemptions_are_the_three_that_are_meant() -> None:
    """The exemptions are enumerated as well as permitted.

    The rule above accepts any marked call, which is what makes it a rule rather
    than a list — but an unmarked list would let a fourth exemption appear with
    nothing to notice it. So the set is named here too, and adding one is a
    change to this test rather than a comment nobody reads. Deleting the rule
    above and keeping only this would be the list this package exists to avoid;
    the two together are a rule with a census.
    """
    exempted = sorted(
        str(path.relative_to(ROOT))
        for path in _python_files()
        if EXEMPTION.search(path.read_text(encoding="utf-8"))
    )
    assert exempted == [
        "apps/cli/migration.py",
        "migrations/env.py",
        "scripts/migration/reconcile.py",
    ]


#: A file with one engine of each kind, written out rather than cut from the
#: tree, so the control states the rule instead of copying today's callers.
PLANTED = """\
from my_pa.infrastructure.database.engine import create_database_engine


def bounded():
    return create_database_engine(url, statement_timeout_ms=settings.statement_timeout_ms)


def excused():
    # statement-timeout-exempt: DDL is sized to the corpus.
    return create_database_engine(url)


def {shape}
"""

BARE = "    return create_database_engine(url)"
POSITIONAL = "    return create_database_engine(url, 30_000)"

CASES: dict[str, tuple[str, list[str]]] = {
    # The defect: an engine with no bound and nothing said about it.
    "a bare engine": (f"silent():\n{BARE}", [BARE]),
    # The control: the same call, bounded.
    "the same engine, bounded": (
        "loud():\n    return create_database_engine(url, statement_timeout_ms=30_000)",
        [],
    ),
    # The control: the same call, excused.
    "the same engine, excused": (
        f"loud():\n    # statement-timeout-exempt: a reason.\n{BARE}",
        [],
    ),
    # A marker with no reason after the colon is not a marker.
    "an empty exemption": (f"empty():\n    # statement-timeout-exempt:\n{BARE}", [BARE]),
    # The marker is not a wildcard for the file: it excuses the call beneath it
    # and not the one three lines further on.
    "an exemption that does not reach": (
        f"far():\n    # statement-timeout-exempt: a reason.\n    x = 1\n    y = 2\n{BARE}",
        [BARE],
    ),
    # A positional value is not the keyword; the setting is keyword-only.
    "a positional argument": (f"positional():\n{POSITIONAL}", [POSITIONAL]),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_scan_discriminates(name: str) -> None:
    """Non-vacuity, and its paired controls.

    Six shapes through one planted file. Two of them are the correct forms and
    report nothing; four are the ways an engine can end up unbounded, including
    the two a looser rule would have accepted — an empty marker and a marker
    that excuses a call it is nowhere near.

    The two known-good engines at the top of the planted file are in every case,
    so a scan that had started reporting everything would fail these controls
    rather than pass them.

    Compared by the reported *line's text* and not by its number, because a
    number would pin the layout of the planted source rather than the rule it
    demonstrates — which is what the first version of this test did, and it
    failed on all four defect cases for that reason alone.
    """
    shape, expected = CASES[name]
    source = PLANTED.format(shape=shape)
    lines = source.splitlines()
    reported = unbounded_engines(source, f"<planted: {name}>")
    assert [lines[int(entry.rsplit(":", 1)[1]) - 1] for entry in reported] == expected
