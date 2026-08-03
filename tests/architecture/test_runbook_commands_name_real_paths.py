"""A runbook command that names a path this repository does not have is a lie.

`ops/runbooks/README.md` binds every procedure there to having been executed, so
a path inside a command block was, at the moment of writing, a path that existed.
Nothing kept it that way. A file renamed by a later package leaves the runbook
telling an operator to run something that cannot run, and the operator finds out
at a shell rather than in review.

**Every runbook, not just the new one.** WP-5B added
`ops/runbooks/end-to-end-operations.md` and this rule was written for it, but a
rule scoped to the file that motivated it is the shape this campaign keeps
catching — a guarantee proven in one place and not in its neighbours. Measured at
the time of writing: the four pre-existing runbooks all pass, so covering them
costs nothing and stops the next rename silently.

**What is checked, and what deliberately is not.** Only tokens beginning with a
tracked top-level directory of this repository. `.venv/bin/python` is excluded
by construction and that is not laziness: CI installs the package with
`pip install -e .` and has no `.venv`, so asserting it exists would make this
rule pass locally and fail in the job that matters. URLs, identifiers, JSON
payloads, and shell variables are not paths and are not matched.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ROOT / "ops" / "runbooks"

#: Tracked top-level directories a runbook may name. `.venv/` is absent on
#: purpose — see the module docstring.
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

#: The fewest distinct paths this rule must find across all runbooks before it
#: is deciding anything. A regex that stopped matching would otherwise report
#: success over an empty set, which is the failure mode that let six planted
#: violations through a guard in this campaign. Measured at the time of writing:
#: **7** distinct paths across 5 runbooks and their index — the five programs
#: under `apps/`, `fixtures/mcv/root`, and `ops/compose/postgres.yml`. The floor
#: is set just below it rather than at a round number, so a pattern that broke
#: would have to keep matching almost everything to escape.
FEWEST_PATHS = 6

_BLOCK = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)
_PATH = re.compile(
    r"(?<![\w./-])((?:" + "|".join(re.escape(root) for root in TRACKED_ROOTS) + r")[\w./-]*)"
)

#: Trailing punctuation a path can pick up from prose inside a block.
_TRAILING = ".,;:'\"`)"


def command_blocks(document: Path) -> list[str]:
    """Every fenced block in a Markdown document, of any language."""
    return _BLOCK.findall(document.read_text(encoding="utf-8"))


def paths_named(document: Path) -> set[str]:
    """Every repository path a document's fenced blocks name."""
    return {
        match.rstrip(_TRAILING)
        for block in command_blocks(document)
        for match in _PATH.findall(block)
    }


def runbooks() -> list[Path]:
    return sorted(RUNBOOKS.glob("*.md"))


def test_the_rule_has_runbooks_and_paths_to_decide_over() -> None:
    """Guard the rule: it is an existence test over a regex's output."""
    found = runbooks()
    assert len(found) >= 5, f"only {len(found)} runbooks found under {RUNBOOKS}"

    named = {path for document in found for path in paths_named(document)}
    assert len(named) >= FEWEST_PATHS, (
        f"only {len(named)} repository paths parsed out of {len(found)} runbooks; "
        "the block or path pattern stopped matching"
    )


@pytest.mark.parametrize("runbook", runbooks(), ids=lambda value: str(value.name))
def test_every_path_a_runbook_command_names_exists(runbook: Path) -> None:
    """The rule, per runbook, so a failure names the file that is wrong."""
    missing = sorted(path for path in paths_named(runbook) if not (ROOT / path).exists())
    assert not missing, (
        f"{runbook.relative_to(ROOT)} runs commands naming {missing}, which this "
        "repository does not have; a procedure here is written only after it has "
        "been executed, so a path that is gone means the transcript is stale"
    )


def test_the_end_to_end_runbook_probes_before_it_registers() -> None:
    """AC-2's actual criterion: the probe is the sequence's *first* step.

    Ordering, not presence. A runbook that mentioned the probe somewhere below
    registration would satisfy "names the probe" and would have told an operator
    to configure a source against a database that cannot hold one.

    Compared by position in the file rather than by heading text, so rewording a
    heading does not silently retire the check.
    """
    document = RUNBOOKS / "end-to-end-operations.md"
    text = document.read_text(encoding="utf-8")

    probe = text.find("apps/cli/health.py")
    register = text.find("apps/cli/sources.py")
    enroll = text.find("sources.enroll")
    assert probe != -1, f"{document.name} never names the probe"
    assert register != -1, f"{document.name} never names source registration"
    assert enroll != -1, f"{document.name} never names enrollment"
    assert probe < register < enroll, (
        f"{document.name} orders probe/register/enroll at {probe}/{register}/{enroll}; "
        "the probe is the first step of the sequence, before registration"
    )


# ---- the plant ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("block", "expected"),
    [
        ("```sh\n.venv/bin/python apps/cli/health.py\n```\n", set()),
        (
            "```sh\n.venv/bin/python apps/cli/no_such_command.py\n```\n",
            {"apps/cli/no_such_command.py"},
        ),
        ("```sh\ncurl -sS http://127.0.0.1:8765/v1/capabilities.get\n```\n", set()),
        ("```sh\ncat docs/gone.md fixtures/mcv/root/notes.md\n```\n", {"docs/gone.md"}),
    ],
    ids=[
        "a real path passes",
        "a path that does not exist is a finding",
        "a URL is not a path",
        "one real and one missing, in the same command",
    ],
)
def test_the_rule_flags_exactly_the_paths_that_do_not_exist(
    tmp_path: Path, block: str, expected: set[str]
) -> None:
    """Planted outside the repository; the real runbooks are never touched.

    The third case is the one worth keeping. `http://127.0.0.1:8765/v1/…` sits
    inside every command block in the gateway runbook, and a pattern that
    matched it would report a permanent false finding — so the rule staying
    **green** there is asserted rather than assumed.

    The fourth is the isolation: a block holding a real path and a missing one
    must flag the missing one only.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(block, encoding="utf-8")

    assert command_blocks(planted), "the plant parsed to no command block"
    missing = {path for path in paths_named(planted) if not (ROOT / path).exists()}
    assert missing == expected
