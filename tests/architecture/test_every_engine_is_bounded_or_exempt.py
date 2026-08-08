"""Every engine this repository builds either bounds a statement or says why not.

`create_database_engine` sets pool options and, until this package, nothing else.
PostgreSQL's own `statement_timeout` default is `0` — no bound at all — so a
query the planner got wrong, or one over a corpus larger than the one it was
measured on, ran until it finished or the client went away, holding one of five
connections in a pool with overflow disabled. The functional indexes remove the
sequential scan as the *only* possibility; they bound nothing.

The setting closes that, and a setting closes it only for the callers that pass
it. Several of the callers were absent from the list this package was briefed
with, and two of the absent ones turned out to be callers that must *not* be
bounded — so a fix built from that list would have been correct by luck. A rule
stated as a list of call sites is a rule that is wrong the next time somebody
adds one, which is this campaign's most-repeated finding: a correction that
closes exactly the case its finding named and leaves the adjacent one open. So
the rule is derived from the syntax tree instead:

    every `create_database_engine(...)` in `src/`, `apps/`, `migrations/` and
    `scripts/` either passes a `statement_timeout_ms=` that is a real bound, or
    carries an `# statement-timeout-exempt:` comment on the line above it.

**No count of those callers is written in this docstring, and the omission is
deliberate.** The first version stated one, and it was wrong — and the second
version recorded the correction by stating the *right* one, which is the same
defect with a better value in it. A number maintained beside the thing instead of
derived from it is the `D-24` shape, and writing one in the prose of the guard
whose whole subject is that shape is the failure inside the fix, twice over.
`test_the_exemptions_are_the_ones_that_are_meant` names the exempt *files*, which
is a set a reader can act on and which reddens when it changes; the total is
derivable by running the scan and is restated nowhere.

**The exemptions are the interesting half.** Alembic (`migrations/env.py`) runs
DDL and functional-index builds sized to the corpus, and a `CREATE INDEX`
cancelled halfway leaves the database between revisions — strictly worse than the
unbounded query the bound prevents. `apps/cli/migration.py` and
`scripts/migration/reconcile.py` load and reconcile a legacy corpus in statements
sized to it. Each says so where it builds its engine; this test only requires
that it say *something* there, because a mechanical rule cannot judge a reason and
one that pretended to would be the aspirational document one layer down.

**A bound must be a bound, not merely a keyword.** The first version of this
guard checked only that `statement_timeout_ms=` was *present*, so
`statement_timeout_ms=None` reported clean — and `None` is exactly how
`create_database_engine` documents an exemption, so the guard accepted a silent
one. `=0` passed too, the one value `Settings.statement_timeout_ms` forbids. The
check below refuses a literal that means "no bound" and trusts anything it cannot
evaluate, which is stated precisely at `_is_a_bound`.

**Bounded to non-test code, and that boundary is a decision rather than an
oversight.** The test suite builds many engines against disposable databases,
several to run the migration chain, and requiring a marker on each would produce
markers that mean nothing. What the tests do is checked where it can be checked —
by the database tier, against a real server.

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


def _is_a_bound(value: ast.expr) -> bool:
    """Whether this argument expression can be a real `statement_timeout`.

    Refuses the two literals that mean "no bound": `None`, which is exactly how
    `create_database_engine` documents an exemption, and any number `<= 0`, `0`
    being how PostgreSQL spells "no timeout" and the value
    `Settings.statement_timeout_ms` refuses with `gt=0`.

    **Trusts everything it cannot evaluate, and that boundary is named rather
    than left to be found.** `settings.statement_timeout_ms` is an attribute
    whose value no syntax tree knows, so a caller passing a variable is accepted
    here. What backs that up is not this scan: the field is typed `int` with
    `gt=0`, so a `Settings` carrying `None` or `0` cannot be constructed, and
    `mypy --strict` rejects `int | None` where `int | None` is not the parameter
    type. A caller who computes a zero at runtime from something that is not
    `Settings` is outside what either can see, and no rule short of running the
    program would catch it.
    """
    if isinstance(value, ast.Constant):
        if value.value is None:
            return False
        if isinstance(value.value, int | float) and not isinstance(value.value, bool):
            return value.value > 0
    # `-1` is a `UnaryOp` over a positive constant, not a negative literal.
    return not (isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub))


def _builder_calls(source: str, filename: str) -> list[ast.Call]:
    """Every `create_database_engine(...)` in `source`, however it is named."""
    tree = ast.parse(source, filename=filename)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == BUILDER)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == BUILDER)
        )
    ]


def _bounds_its_statements(call: ast.Call) -> bool:
    """Whether this call passes a `statement_timeout_ms` that is a real bound."""
    return any(keyword.arg == SETTING and _is_a_bound(keyword.value) for keyword in call.keywords)


def unbounded_engines(source: str, filename: str) -> list[str]:
    """Every `create_database_engine(...)` in `source` that neither binds nor excuses.

    The exemption is looked for on the line above the call and on the call's own
    first line, which are the two places a reader would write it. It is matched
    against the source text rather than the syntax tree because comments are not
    in the tree at all — the alternative, a marker that lives in the code as a
    keyword argument, would be a second way of spelling the setting.
    """
    lines = source.splitlines()
    return [
        f"{filename}:{call.lineno}"
        for call in _builder_calls(source, filename)
        if not _bounds_its_statements(call)
        and not any(EXEMPTION.search(line) for line in lines[max(0, call.lineno - 2) : call.lineno])
    ]


def unbounded_files(source: str, filename: str) -> list[str]:
    """Every file with a call that sets no real `statement_timeout`, marked or not.

    The census below is built from this rather than from the marker, which is the
    correction the reviewer's finding forced. Scanning for comments meant the
    census answered "which files carry a marker" while claiming to answer "which
    files run unbounded" — so an exemption that was marked *and* uncensused was
    invisible to both tests, and an exemption that was unmarked was invisible to
    this one. Deriving both from the calls makes the two questions the same
    question asked twice.
    """
    return (
        [filename]
        if any(not _bounds_its_statements(c) for c in _builder_calls(source, filename))
        else []
    )


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


def test_the_exemptions_are_the_ones_that_are_meant() -> None:
    """The exemptions are enumerated as well as permitted, and derived from calls.

    The rule above accepts any marked call, which is what makes it a rule rather
    than a list — but on its own it would let a fourth exemption appear with
    nothing to notice it. So the set is named here too, and adding one is a change
    to this test rather than a comment nobody reads. Deleting the rule above and
    keeping only this would be the list this package exists to avoid; the two
    together are a rule with a census.

    **Derived from the calls and not from the markers.** The first version listed
    files containing an `# statement-timeout-exempt:` comment, so a fourth
    exemption that was marked and left out of this list satisfied both tests at
    once — which is the thing the paragraph above claims cannot happen.
    """
    exempted = sorted(
        entry
        for path in _python_files()
        for entry in unbounded_files(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
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
NULLED = "    return create_database_engine(url, statement_timeout_ms=None)"
ZEROED = "    return create_database_engine(url, statement_timeout_ms=0)"
NEGATED = "    return create_database_engine(url, statement_timeout_ms=-1)"

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
    # The three bypasses the presence-only check accepted. `None` is the one
    # that matters most: it is how `create_database_engine` documents an
    # exemption, so the guard was accepting a silent, unmarked, uncensused one
    # while reporting the tree clean.
    "the keyword set to None": (f"nulled():\n{NULLED}", [NULLED]),
    "the keyword set to zero": (f"zeroed():\n{ZEROED}", [ZEROED]),
    "the keyword set negative": (f"negated():\n{NEGATED}", [NEGATED]),
    # The control for those three: a variable is trusted, because no syntax tree
    # can evaluate it and `Settings.statement_timeout_ms` is `int` with `gt=0`.
    "the keyword set from settings": (
        "configured():\n    return create_database_engine(url, "
        "statement_timeout_ms=settings.statement_timeout_ms)",
        [],
    ),
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
