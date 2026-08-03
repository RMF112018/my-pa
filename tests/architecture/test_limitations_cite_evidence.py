"""Every limitation in the limitations document cites evidence that exists.

`docs/operations/mcv-limitations.md` states what the read-only slice does **not**
do. A limitations document is the easiest document in a repository to write
aspirationally: nothing in it can be run, so nothing in it can be wrong in a way
that shows. This is what makes it wrong in a way that shows.

Two checks, and each catches a different failure:

1. **Every cited path exists.** A limitation attributed to a module that has been
   renamed is a claim with nothing behind it, and it reads exactly like a claim
   with something behind it.
2. **Every cited test node id resolves to a real test function** in the file it
   names. This is the citation form that rots invisibly, because a renamed test
   leaves the document reading perfectly.

**Why `ast` rather than `pytest --collect-only`.** Resolution is decided by
parsing the named file and looking for a module-level `def` with that name whose
name pytest would collect. Collecting through pytest would import the module —
the `e2e` and `recovery` tests cited here are `database`-marked and open engines
— which would drag a FAST-tier guard into needing a server. An `ast` lookup
answers the same question about the same file in milliseconds, and the plants
below prove it answers it correctly.

**What is deliberately not checked.** Whether the cited test *proves* the
limitation. No mechanical rule can decide that, and a rule that pretended to
would be the aspirational document one layer down.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIMITATIONS = ROOT / "docs" / "operations" / "mcv-limitations.md"

#: Tracked top-level directories a citation may name.
TRACKED_ROOTS = (
    "apps/",
    "docs/",
    "evidence/",
    "fixtures/",
    "migrations/",
    "ops/",
    "schemas/",
    "scripts/",
    "src/",
    "tests/",
)

#: The fewest of each kind before this rule is deciding anything. A document
#: that lost its citation formatting would parse to zero of both and would
#: otherwise pass every check below.
FEWEST_PATHS = 15
FEWEST_TESTS = 5

#: A backticked token. Citations are written in backticks throughout the
#: document, which is also how it renders them as code.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

_PATHLIKE = re.compile(
    r"^(?:" + "|".join(re.escape(root) for root in TRACKED_ROOTS) + r")[\w./-]+$"
)

#: Every `## ` heading is one limitation. Numbered, so the count is visible.
_LIMITATION = re.compile(r"^## \d+\. ", re.MULTILINE)


def _backticked(document: Path) -> list[str]:
    return _BACKTICKED.findall(document.read_text(encoding="utf-8"))


def cited_paths(document: Path) -> set[str]:
    """Every citation naming a repository path and no test."""
    return {
        token for token in _backticked(document) if "::" not in token and _PATHLIKE.match(token)
    }


def cited_tests(document: Path) -> set[tuple[str, str]]:
    """Every citation naming a test, as `(file, function)`."""
    found: set[tuple[str, str]] = set()
    for token in _backticked(document):
        if "::" not in token:
            continue
        path, _, name = token.partition("::")
        if _PATHLIKE.match(path):
            found.add((path, name))
    return found


def resolves_to_a_test(module: Path, name: str) -> bool:
    """Whether `module` defines a module-level test function called `name`.

    The `test_` prefix is part of the question, not a nicety. A citation must
    name something a reader can run; `module.py::some_helper` names a function
    that exists and that pytest would never collect, and accepting it would let
    the document cite a helper as if it were evidence.
    """
    if not name.startswith("test_") or not module.is_file():
        return False
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    return any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name
        for node in tree.body
    )


def test_the_document_exists_and_states_limitations() -> None:
    """Guard both rules: each is an existence test over a parsed set."""
    assert LIMITATIONS.is_file(), f"{LIMITATIONS} is gone; the two rules below decide nothing"

    text = LIMITATIONS.read_text(encoding="utf-8")
    assert len(_LIMITATION.findall(text)) >= 8, "fewer than eight numbered limitations"

    paths = cited_paths(LIMITATIONS)
    tests = cited_tests(LIMITATIONS)
    assert len(paths) >= FEWEST_PATHS, f"only {len(paths)} path citations parsed"
    assert len(tests) >= FEWEST_TESTS, f"only {len(tests)} test citations parsed"


def test_every_cited_path_exists() -> None:
    missing = sorted(path for path in cited_paths(LIMITATIONS) if not (ROOT / path).exists())
    assert not missing, (
        f"{LIMITATIONS.relative_to(ROOT)} cites {missing}, which this repository does "
        "not have; a limitation whose evidence is gone is a claim about nothing"
    )


def test_every_cited_test_resolves_to_a_real_test_function() -> None:
    unresolved = sorted(
        f"{path}::{name}"
        for path, name in cited_tests(LIMITATIONS)
        if not resolves_to_a_test(ROOT / path, name)
    )
    assert not unresolved, (
        f"{LIMITATIONS.relative_to(ROOT)} cites {unresolved}, which resolve to no test; "
        "a renamed test leaves a limitations document reading perfectly"
    )


def test_the_document_is_routed_and_reachable_from_the_runbook() -> None:
    """A limitations document nobody is sent to is one nobody reads.

    Two entry points, both asserted: the repository source index, and the
    end-to-end runbook, which is where an operator meets the slice.
    """
    index = (ROOT / "docs" / "00_REPOSITORY_SOURCE_INDEX.md").read_text(encoding="utf-8")
    runbook = (ROOT / "ops" / "runbooks" / "end-to-end-operations.md").read_text(encoding="utf-8")
    relative = str(LIMITATIONS.relative_to(ROOT))
    assert "operations/mcv-limitations.md" in index, f"{relative} is routed by no index entry"
    assert relative in runbook, f"{relative} is named by no runbook"


# ---- the plants ---------------------------------------------------------------

_THIS = "tests/architecture/test_limitations_cite_evidence.py"


@pytest.mark.parametrize(
    ("citation", "resolves"),
    [
        (f"{_THIS}::resolves_to_a_test", False),
        (f"{_THIS}::test_every_cited_path_exists", True),
        (f"{_THIS}::test_renamed_away", False),
        ("tests/architecture/no_such_file.py::test_anything", False),
    ],
    ids=[
        "a helper that exists is not a test",
        "a real test resolves",
        "a name nothing defines does not",
        "a file that does not exist does not",
    ],
)
def test_the_test_citation_rule_resolves_exactly_the_right_names(
    tmp_path: Path, citation: str, resolves: bool
) -> None:
    """Planted through the real parser and the real resolver.

    The first case is the one a looser rule gets wrong: `resolves_to_a_test` is
    a module-level `def` in the cited file, so a rule matching any function
    would accept it as evidence. The second case is the isolation — it proves
    the resolver is not simply refusing everything.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(f"Evidence: `{citation}`.\n", encoding="utf-8")

    parsed = cited_tests(planted)
    assert len(parsed) == 1, f"{citation!r} did not parse as a test citation: {parsed}"
    path, name = next(iter(parsed))
    assert resolves_to_a_test(ROOT / path, name) is resolves


def test_the_path_rule_separates_paths_from_tests_and_from_prose(tmp_path: Path) -> None:
    """Backticks are used for prose too, and only paths may be checked.

    A rule that treated every backticked token as a path would flag `D-65`,
    `internal_error`, and `P00-OD-010` — all of which appear in the real
    document — and would be a false-finding machine. The green half is asserted
    here for the same reason it is in the README routing rule.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(
        "`D-65` and `internal_error` and `P00-OD-010` are not paths. "
        "`apps/cli/health.py` is. `tests/contract/test_health_probe.py::test_x` is a test.\n",
        encoding="utf-8",
    )

    assert cited_paths(planted) == {"apps/cli/health.py"}
    assert cited_tests(planted) == {("tests/contract/test_health_probe.py", "test_x")}
