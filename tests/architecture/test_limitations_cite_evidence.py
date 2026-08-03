"""Every limitation in the limitations document cites evidence that exists.

`docs/operations/mcv-limitations.md` states what the read-only slice does **not**
do. A limitations document is the easiest document in a repository to write
aspirationally: nothing in it can be run, so nothing in it can be wrong in a way
that shows. This is what makes it wrong in a way that shows.

Three checks, and each catches a different failure:

1. **Every cited path exists.** A limitation attributed to a module that has been
   renamed is a claim with nothing behind it, and it reads exactly like a claim
   with something behind it.
2. **Every cited test node id resolves to a real test function** in the file it
   names. This is the citation form that rots invisibly, because a renamed test
   leaves the document reading perfectly.
3. **No citation names a real artifact that neither rule asserts.** Rules 1 and 2
   classify by shape, so anything they do not recognise is not checked — and an
   unchecked citation reads exactly like a checked one. Three did: `TRACKED_ROOTS`
   admitted only top-level *directories*, so `PHASE-00-OPEN-DECISION-LEDGER.md`,
   `pyproject.toml` and `AGENTS.md` matched nothing and were asserted by nothing,
   while the document's preamble said every cited path was checked. Rule 3 is what
   makes a blind spot fail instead of pass.

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

#: Suffixes of repository-**root** files a citation may name.
#:
#: `TRACKED_ROOTS` admits only directories, so a citation of a file at the
#: repository root — `pyproject.toml`, `AGENTS.md` — carried no prefix to match
#: and escaped both rules silently. Three live citations sat in that gap.
#:
#: A closed suffix list rather than "any bare filename", because backticks are
#: also prose here and `invoke.py` is written as shorthand for
#: `apps/cli/invoke.py`; treating every dotted token as a path would flag it,
#: `capabilities.get`, `knowledge.audit_events` and `127.0.0.1` alike. The list
#: is deliberately narrow, and `uncovered_citations` is what stops it from
#: being *quietly* narrow: a citation that names a real
#: repository entry and matches nothing here fails rather than passing unchecked.
ROOT_FILE_SUFFIXES = (".cfg", ".ini", ".md", ".toml", ".txt", ".yaml", ".yml")

#: The fewest of each kind before this rule is deciding anything. A document
#: that lost its citation formatting would parse to zero of both and would
#: otherwise pass every check below.
FEWEST_PATHS = 15
FEWEST_TESTS = 5

#: A backticked token. Citations are written in backticks throughout the
#: document, which is also how it renders them as code.
_BACKTICKED = re.compile(r"`([^`\n]+)`")

_UNDER_TRACKED_ROOT = re.compile(
    r"^(?:" + "|".join(re.escape(root) for root in TRACKED_ROOTS) + r")[\w./-]+$"
)

#: A file at the repository root: no separator, and one of the closed suffixes.
_ROOT_FILE = re.compile(
    r"^[\w.-]+(?:" + "|".join(re.escape(suffix) for suffix in ROOT_FILE_SUFFIXES) + r")$"
)


def _pathlike(token: str) -> bool:
    """Whether `token` is written as a repository path rather than as prose.

    Decided by shape alone and never by whether the named file happens to
    exist, because a rule that classified by existence could not fail: a
    citation of a renamed file would stop being a path and start being prose,
    and the document would go green by rotting.
    """
    return bool(_UNDER_TRACKED_ROOT.match(token) or _ROOT_FILE.match(token))


#: Every `## ` heading is one limitation. Numbered, so the count is visible.
_LIMITATION = re.compile(r"^## \d+\. ", re.MULTILINE)


def _backticked(document: Path) -> list[str]:
    return _BACKTICKED.findall(document.read_text(encoding="utf-8"))


def cited_paths(document: Path) -> set[str]:
    """Every citation naming a repository path and no test."""
    return {token for token in _backticked(document) if "::" not in token and _pathlike(token)}


def cited_tests(document: Path) -> set[tuple[str, str]]:
    """Every citation naming a test, as `(file, function)`."""
    found: set[tuple[str, str]] = set()
    for token in _backticked(document):
        if "::" not in token:
            continue
        path, _, name = token.partition("::")
        if _pathlike(path):
            found.add((path, name))
    return found


def uncovered_citations(document: Path) -> set[str]:
    """Citations that name a real repository entry and that no rule asserts.

    The complement of the two rules above, and the reason a narrow classifier
    is safe. `cited_paths` and `cited_tests` decide by shape; this decides by
    the filesystem, and reports any token that denotes something real which
    neither rule claimed. A citation shape the classifier does not know — a
    root file with no suffix, say — surfaces here as a failure instead of
    passing unchecked, which is exactly how the root-file gap survived.
    """
    asserted = cited_paths(document) | {f"{path}::{name}" for path, name in cited_tests(document)}
    return {
        token
        for token in _backticked(document)
        if token not in asserted and (ROOT / token.partition("::")[0]).exists()
    }


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
    """Guard all three rules: each is an existence test over a parsed set."""
    assert LIMITATIONS.is_file(), f"{LIMITATIONS} is gone; the three rules below decide nothing"

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


def test_the_citation_universe_covers_every_shape_the_document_uses() -> None:
    """No citation names a real artifact that neither rule asserts.

    The third rule, and the one that makes the other two honest. Without it the
    classifier's blind spots are silent by construction: a citation it does not
    recognise is simply not checked, and reads exactly like one that passed.
    Three did — `PHASE-00-OPEN-DECISION-LEDGER.md`, `pyproject.toml` and
    `AGENTS.md`, all repository-root files, which `TRACKED_ROOTS` could not
    match because it lists only directories.
    """
    uncovered = sorted(uncovered_citations(LIMITATIONS))
    assert not uncovered, (
        f"{LIMITATIONS.relative_to(ROOT)} cites {uncovered}, which name real "
        "repository entries that neither rule asserts; widen the classifier "
        "rather than leaving a citation shape unchecked"
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


@pytest.mark.parametrize(
    ("citation", "is_path"),
    [
        ("pyproject.toml", True),
        ("AGENTS.md", True),
        ("PHASE-00-OPEN-DECISION-LEDGER.md", True),
        ("pyproject-that-is-gone.toml", True),
        ("invoke.py", False),
        ("capabilities.get", False),
        ("knowledge.audit_events", False),
        ("truncation.is_truncated", False),
        ("127.0.0.1", False),
        ("my_pa", False),
    ],
    ids=[
        "a root file that exists is a path",
        "so is the second one that escaped",
        "and the third",
        "a root file that does not exist is still a path, or the rule cannot fail",
        "a bare module name used as prose is not",
        "nor is a capability name",
        "nor is a qualified table name",
        "nor is a field path",
        "nor is a loopback address",
        "nor is the namespace",
    ],
)
def test_the_root_file_rule_separates_root_files_from_dotted_prose(
    tmp_path: Path, citation: str, is_path: bool
) -> None:
    """The gap the guard had, and the false findings a looser fix would create.

    The fourth case is the isolation that matters: a root-file citation is
    classified by **shape**, so a renamed file stays a path citation and fails
    `test_every_cited_path_exists`. A rule that classified by existence would
    have reclassified it as prose and gone green, which is the failure this
    whole file exists to prevent one layer up.

    The dotted cases are the other end. `capabilities.get` and
    `knowledge.audit_events` are real tokens in the real document, and a rule
    that treated any dot as a file extension would report both as missing
    files.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(f"Evidence: `{citation}`.\n", encoding="utf-8")

    assert (cited_paths(planted) == {citation}) is is_path
    assert cited_tests(planted) == set()


def test_the_coverage_rule_reports_a_citation_shape_the_classifier_does_not_know(
    tmp_path: Path,
) -> None:
    """`LICENSE` is real, is cited-shaped, and matches no rule — so it is reported.

    The plant is a suffixless root file rather than an invented one, because
    the point is that the classifier's *closed* suffix list has an edge and the
    coverage rule is what keeps that edge loud. The green half is asserted in
    the same test: a document citing only shapes the classifier knows reports
    nothing, so this is not a rule that flags everything.
    """
    assert (ROOT / "LICENSE").is_file(), "the plant needs a suffixless root file"

    planted = tmp_path / "planted.md"
    planted.write_text("Evidence: `LICENSE`, `apps/cli/health.py`, `D-65`.\n", encoding="utf-8")
    assert uncovered_citations(planted) == {"LICENSE"}

    covered = tmp_path / "covered.md"
    covered.write_text("Evidence: `apps/cli/health.py`, `pyproject.toml`, `D-65`.\n", "utf-8")
    assert uncovered_citations(covered) == set()
