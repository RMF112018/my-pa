"""A README that says something must be reachable from the top-level index.

`docs/00_REPOSITORY_SOURCE_INDEX.md` is where a reader — human or agent — is
told to start. A directory that carries a real, populated README and appears
nowhere in it is documentation nobody is routed to, which is the same defect as
documentation that does not exist, only harder to notice.

**The scaffold READMEs are excluded by construction, and that is deliberate.**
Counted at `bcdbf6d`, and bound to it because an unbound count cannot be told
from one that has already rotted: **96 of this repository's 113 READMEs** carry
`Status: SCAFFOLD_ONLY` and say, in those words, that their responsibility "is
routed through `docs/00_REPOSITORY_SOURCE_INDEX.md` and the nearest owning
index" — they delegate rather than assert, so routing each of them individually
would be routing 96 pointers back to the router. They are also not stale: **27
of the 96 sit beside real Python**, including `src/README.md` (93 modules) and
`tests/README.md` (74 at `bcdbf6d`; this package's own four test files make it
78), so a rule that treated "scaffold README beside real content" as a finding
would flag the entire source tree. The marker is a repository-wide convention
and this rule respects it.

**What "routed" means here is the directory, not the file.** The index reaches
`docs/architecture/` through `00_ARCHITECTURE_INDEX.md` and `docs/security/`
through `threat-model.md`, and in both cases a reader who follows the link
arrives beside the README and can see it. Requiring the README itself to be
linked would demand churn in two places that are already reachable, and would be
a stricter rule than the property is.

**The universe this measured, and where the assignment was wrong.** WP-5B's
brief and design both stated that `ops/runbooks/README.md` was the only
violation. Enumerated at `bcdbf6d`: **17 of the 113** were non-scaffold, of
which **11** were routed by nothing — `.ai/goals/`, `apps/cli/`, `evidence/`,
`evidence/completion/`, `fixtures/mcv/`, `migrations/`, `migrations/versions/`,
`ops/compose/`, `ops/postgres/`, `ops/runbooks/`, and
`src/my_pa/infrastructure/database/`. Narrowing the rule until one of them
remained would have been narrowing an acceptance criterion to fit a claim, so
the index gained the eleven entries instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "docs" / "00_REPOSITORY_SOURCE_INDEX.md"

#: The marker that makes a README a delegation rather than a statement.
SCAFFOLD = "SCAFFOLD_ONLY"

#: Directories that hold no tracked file. Enumerated rather than inferred from a
#: leading dot, because `.ai/` and `.github/` are tracked and `.ai/goals/README.md`
#: is one of the seventeen — excluding every dotted directory would have quietly
#: removed a real finding from the universe.
UNTRACKED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)

#: The smallest universe this rule can decide anything over. A glob that matched
#: nothing would make every assertion below pass, which is the shape that let six
#: planted violations through a guard in this campaign already.
FEWEST_READMES = 100

_LINK = re.compile(r"\]\(([^)]+)\)")


def link_targets(document: Path, root: Path = ROOT) -> set[Path]:
    """Every in-tree path a Markdown document links to, resolved.

    A leading `/` means the tree's root — that is the form the scaffold READMEs
    and several index entries use — and anything else resolves against the
    linking document's own directory. External URLs and anchors are dropped; a
    link that escapes the tree is dropped rather than raising, because this
    function's job is to report what the index reaches, not to validate it.

    `root` is a parameter so the plant below runs the real parser over a planted
    index instead of a hand-built set of paths.
    """
    found: set[Path] = set()
    for match in _LINK.finditer(document.read_text(encoding="utf-8")):
        target = match.group(1).split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        base = root / target.lstrip("/") if target.startswith("/") else document.parent / target
        resolved = base.resolve()
        if root.resolve() == resolved or root.resolve() in resolved.parents:
            found.add(resolved)
    return found


def readmes(root: Path) -> list[Path]:
    """Every README under `root`, skipping directories that hold no tracked file."""
    return sorted(
        path
        for path in root.rglob("*README.md")
        if not UNTRACKED_DIRECTORIES & set(path.relative_to(root).parts)
    )


def is_scaffold(readme: Path) -> bool:
    return SCAFFOLD in readme.read_text(encoding="utf-8")


def unrouted(candidates: list[Path], targets: set[Path]) -> list[Path]:
    """The non-scaffold READMEs whose directory nothing in `targets` reaches."""
    reached = {target.parent for target in targets} | targets
    return [
        readme
        for readme in candidates
        if not is_scaffold(readme) and readme not in targets and readme.parent not in reached
    ]


def test_the_universe_is_not_empty_and_holds_both_kinds() -> None:
    """Guard the rule: it is an emptiness test over two enumerations.

    Both counts are asserted, not just the total. A run in which every README
    parsed as a scaffold would report zero violations and would have decided
    nothing at all.
    """
    found = readmes(ROOT)
    assert len(found) >= FEWEST_READMES, f"only {len(found)} READMEs found under {ROOT}"

    scaffolds = [readme for readme in found if is_scaffold(readme)]
    stated = [readme for readme in found if not is_scaffold(readme)]
    assert len(scaffolds) >= 50, f"only {len(scaffolds)} scaffold READMEs; the marker moved"
    assert len(stated) >= 10, f"only {len(stated)} non-scaffold READMEs; the marker moved"

    assert link_targets(INDEX), "the repository source index links to nothing in the repository"


def test_every_non_scaffold_readme_is_routed_by_the_repository_source_index() -> None:
    """The rule. A README that states something is reachable from the router."""
    offending = unrouted(readmes(ROOT), link_targets(INDEX))
    assert not offending, (
        f"{[str(path.relative_to(ROOT)) for path in offending]} state their own content "
        f"and are routed by nothing in {INDEX.relative_to(ROOT)}; either route them or "
        f"mark them `{SCAFFOLD}`, which is the convention for a directory that delegates"
    )


def test_every_path_the_index_routes_to_exists() -> None:
    """The other direction: routing to a file that is gone is a dead entry.

    Without this the rule above could be satisfied by adding an entry for a path
    nobody ever creates.
    """
    missing = sorted(
        str(target.relative_to(ROOT)) for target in link_targets(INDEX) if not target.exists()
    )
    assert not missing, f"{INDEX.relative_to(ROOT)} routes to paths that do not exist: {missing}"


# ---- the plant ----------------------------------------------------------------


def test_the_rule_flags_a_planted_directory_and_leaves_a_scaffold_alone(tmp_path: Path) -> None:
    """Two planted directories, routed by nothing, and only one is a finding.

    Both cases go through the same `readmes`, `is_scaffold`, and `unrouted` the
    rule above uses, so narrowing any of the three breaks this plant in the same
    commit. Planted under `tmp_path`, outside the repository, so the real tree is
    never touched.

    The second half is the one that matters. A rule that flagged the scaffold
    README too would demand routing for all 96 of them and would be a
    false-finding machine rather than a control — which is why the *green* case
    is asserted here rather than assumed.
    """
    stated = tmp_path / "states_its_own_content"
    stated.mkdir()
    (stated / "README.md").write_text("# Something\n\nReal content.\n", encoding="utf-8")

    delegating = tmp_path / "delegates_to_the_index"
    delegating.mkdir()
    (delegating / "README.md").write_text(
        f"# Scaffold Directory\n\n**Status:** `{SCAFFOLD}`\n", encoding="utf-8"
    )

    planted = readmes(tmp_path)
    assert len(planted) == 2, f"the plant enumerated {planted}"

    offending = unrouted(planted, targets=set())
    assert offending == [stated / "README.md"], (
        f"routed by nothing, the rule reported {[str(path) for path in offending]}; "
        "it must flag the README that states content and leave the scaffold alone"
    )


@pytest.mark.parametrize(
    "entry",
    ["[x](states_its_own_content/README.md)", "[x](states_its_own_content/anything.md)"],
    ids=["the README itself", "any file beside it"],
)
def test_a_routed_planted_directory_stops_being_a_finding(tmp_path: Path, entry: str) -> None:
    """The rule clears when the directory is reached, by either form of link.

    The second case is the directory-level reading stated at the top of this
    module, and it is asserted rather than described: `docs/architecture/` and
    `docs/security/` are routed exactly that way today and must stay green.
    """
    stated = tmp_path / "states_its_own_content"
    stated.mkdir()
    (stated / "README.md").write_text("# Something\n\nReal content.\n", encoding="utf-8")

    index = tmp_path / "index.md"
    index.write_text(f"- {entry}\n", encoding="utf-8")

    targets = link_targets(index, root=tmp_path)
    assert targets, "the planted index parsed to no target; this case decides nothing"
    assert unrouted(readmes(stated), targets) == []
