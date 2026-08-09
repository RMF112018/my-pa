"""The README's statement of what this build reports is derived, not asserted.

The paragraph in question said "every capability still reports `not_implemented`
… readiness reports `contracts_only`" and stayed there while the capabilities
were wired. Nothing connected the prose to the value, so nothing went red — the
same shape of defect `test_open_decision_counts.py` exists to prevent for section
14's figures, and the same remedy: recompute the claim and compare.

What is bound is deliberately narrow. Only the availability and readiness
*vocabulary* is checked — the closed sets of `Availability` and `ReadinessState`
values — against what the manifest a running service would publish actually
holds. The surrounding sentences are prose and stay prose; binding those would be
brittle without being useful, because they say things no value can confirm.

The manifest is built the way `ApplicationService._capabilities_get` builds it:
from the dispatch table's own keys and from the limits `bootstrap.settings`
defaults to. A README claim checked against a manifest assembled by hand here
would be checked against this file's opinion rather than against the build.
"""

from __future__ import annotations

import re
from pathlib import Path

from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.v1.capabilities import Availability, ReadinessState

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
RELATIONSHIP_PACKAGE = ROOT / "src" / "my_pa" / "domain" / "relationship"
SOURCE_INDEX = ROOT / "docs" / "00_REPOSITORY_SOURCE_INDEX.md"
SPECS_INDEX = ROOT / "docs" / "specs" / "README.md"
COMPLETION_PLAN = ROOT / "docs" / "plans" / "mcv-completion-plan.md"

#: The paragraph that states what this build reports. Anchored on its opening
#: word rather than on a line number, and read to the next blank line, so
#: reflowing it is safe and moving it is not silent.
CLAIM = re.compile(r"^Accordingly, (.+?)\n\n", re.DOTALL | re.MULTILINE)

_BACKTICKED = re.compile(r"`([A-Za-z][A-Za-z0-9_.-]*)`")

#: A settings URL that is well formed and unreachable, as in `tests/unit`.
#: Nothing connects; the limits are what this test is after.
_A_URL = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"

#: The paragraph naming the frontend's personal-data ingestion posture:
#: Apple-first, and Microsoft Graph retained but off by default. Anchored on
#: its opening words and read to the next blank line, for the same reason the
#: state paragraph is: reflowing it is safe, moving or dropping it is not silent.
INGESTION_CLAIM = re.compile(r"^A frontend exists under.+?\n\n", re.DOTALL | re.MULTILINE)


def frontend_paragraph() -> str:
    """The paragraph stating the ingestion posture, or a loud failure if it moved."""
    match = INGESTION_CLAIM.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "The README paragraph beginning 'A frontend exists under' is gone. It is "
        "the only place the Apple-first / Graph-off-by-default ingestion posture "
        "is stated, and these tests are what keeps that statement true. Move the "
        "anchor deliberately, not by watching this pass."
    )
    return match.group(0)


def claimed_tokens() -> set[str]:
    """Every backticked token in the README's state paragraph."""
    match = CLAIM.search(README.read_text(encoding="utf-8"))
    assert match is not None, (
        "The README paragraph beginning 'Accordingly,' is gone. It states what "
        "this build reports, and this test is the only thing keeping that "
        "statement true. Move the anchor deliberately, not by watching this pass."
    )
    return set(_BACKTICKED.findall(match.group(1)))


def published() -> tuple[set[str], str]:
    """What a running service would publish: availabilities, and readiness."""
    manifest = build_capability_manifest(
        implemented=frozenset(_HANDLERS),
        limits=Settings(database_url=_A_URL).effective_limits(),
    )
    availabilities = {status.availability.value for status in manifest.capabilities} | {
        status.availability.value for status in manifest.content_types
    }
    return availabilities, build_readiness_report(manifest).state.value


def test_the_state_paragraph_still_names_states() -> None:
    """Guard the parser: a paragraph naming none would make the checks vacuous."""
    tokens = claimed_tokens()
    assert tokens & {member.value for member in Availability}, (
        "The README's state paragraph names no availability value. Either it was "
        "reworded past this parser or it stopped making the claim; decide which."
    )
    assert tokens & {member.value for member in ReadinessState}, (
        "The README's state paragraph names no readiness state."
    )


def test_the_readme_names_exactly_the_availabilities_the_build_publishes() -> None:
    """Both directions: nothing claimed that is absent, nothing present unclaimed."""
    claimed = claimed_tokens() & {member.value for member in Availability}
    availabilities, _ = published()
    assert claimed == availabilities, (
        f"The README says this build reports {sorted(claimed)}; it reports "
        f"{sorted(availabilities)}. The manifest is derived from the application's "
        "dispatch table, so the prose is what is wrong."
    )


def test_the_readme_names_the_readiness_state_the_build_reports() -> None:
    claimed = claimed_tokens() & {member.value for member in ReadinessState}
    _, readiness = published()
    assert claimed == {readiness}, (
        f"The README says readiness is {sorted(claimed)}; it is {readiness!r}."
    )


def _alembic_identity() -> tuple[int, str]:
    revisions: dict[str, str | None] = {}
    identifier = re.compile(r'^revision: str = "(?P<id>[0-9a-f]+)"', re.MULTILINE)
    parent = re.compile(r'^down_revision: str \| None = "(?P<id>[0-9a-f]+)"', re.MULTILINE)
    for path in sorted((ROOT / "migrations" / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        found = identifier.search(text)
        if found is None:
            continue
        below = parent.search(text)
        revisions[found["id"]] = below["id"] if below else None
    heads = set(revisions) - {value for value in revisions.values() if value is not None}
    assert len(heads) == 1
    return len(revisions), heads.pop()


def test_readme_derives_the_current_alembic_count_and_head() -> None:
    words = {
        12: "Twelve",
        13: "Thirteen",
        14: "Fourteen",
        15: "Fifteen",
        16: "Sixteen",
        17: "Seventeen",
        18: "Eighteen",
        19: "Nineteen",
        20: "Twenty",
        21: "Twenty-one",
    }
    count, head = _alembic_identity()
    assert count in words, "extend the readable README count vocabulary"
    readme = README.read_text(encoding="utf-8")
    assert f"{words[count]} Alembic revisions" in readme
    assert f"head `{head}`" in readme


def test_relationships_are_not_listed_as_unimplemented_once_the_package_exists() -> None:
    assert RELATIONSHIP_PACKAGE.is_dir()
    readme = README.read_text(encoding="utf-8")
    section = readme.split("Not implemented.", 1)[1].split("Accordingly,", 1)[0]
    assert "relationship identity and profiles" not in section.lower()
    assert "fixture" in readme.lower() and "wp-9" in readme.lower()


def test_current_state_says_the_synthetic_workflow_runs_but_is_not_deployable() -> None:
    current = " ".join(README.read_text(encoding="utf-8").split("## Current state", 1)[1].split())
    assert "workflows run end to end over synthetic fixtures" in current
    assert "nothing here is deployable" in current
    assert "no product workflow runs end to end" not in current


def test_wp12_stays_provisional_and_operator_authorized_without_boundary_inference() -> None:
    documents = "\n".join(
        path.read_text(encoding="utf-8") for path in (SOURCE_INDEX, SPECS_INDEX, COMPLETION_PLAN)
    )
    normalized = " ".join(documents.split()).lower()

    assert "wp-12" in normalized
    assert "provisional" in normalized
    assert "separate operator authorization" in normalized
    assert "no pre-mcv or post-mcv disposition" in normalized
    assert "mcv is not complete" in normalized
    assert "wp-12 is post-mcv" not in normalized
    assert "no repository wp-12 exists" not in normalized


def test_readme_declares_the_operating_lineage_branch_and_denies_main_authority() -> None:
    """WP-01 exists to establish exactly this pair; guard both halves of it.

    A stale README predating WP-01 names no operating lineage at all, so both
    assertions must hold against the actual `## Operating lineage` section
    rather than anywhere in the file.
    """
    readme = README.read_text(encoding="utf-8")
    assert "## Operating lineage" in readme, "The README's 'Operating lineage' section is gone."
    section = readme.split("## Operating lineage", 1)[1].split("## Current state", 1)[0]
    assert "recovery/pre-20260805-utc-rollback-c9fb513" in section, (
        "The README's Operating lineage section no longer names the operating "
        "lineage branch `recovery/pre-20260805-utc-rollback-c9fb513`."
    )
    assert "`main` is not the current operating lineage" in section, (
        "The README's Operating lineage section no longer states that GitHub's "
        "default `main` branch is not operating-lineage authority."
    )


def test_readme_declares_apple_first_personal_data_ingestion() -> None:
    """The four Apple source families must all still be named, by name."""
    paragraph = frontend_paragraph()
    assert "Personal-data ingestion is Apple-first" in paragraph, (
        "The README's frontend paragraph no longer states that personal-data "
        "ingestion is Apple-first."
    )
    for source in ("Apple Mail", "Calendar", "Contacts", "Tasks/To-Do"):
        assert source in paragraph, (
            f"The README's frontend paragraph no longer names {source!r} among "
            "the Apple source families ingestion is drawn from."
        )
    assert "native Apple architecture" in paragraph, (
        "The README's frontend paragraph no longer attributes ingestion to the "
        "native Apple architecture."
    )


def test_readme_declares_graph_off_by_default_and_entra_separate_from_activation() -> None:
    """Retained-but-inactive is a specific, invertible claim; guard the wording
    that makes it specific rather than a generic mention of Microsoft Graph."""
    paragraph = frontend_paragraph()
    assert "off by default and not an active personal-data ingestion path" in paragraph, (
        "The README's frontend paragraph no longer states that Microsoft Graph "
        "is off by default and not an active personal-data ingestion path."
    )
    assert "Entra authentication" in paragraph, (
        "The README's frontend paragraph no longer mentions Entra authentication."
    )
    assert "separate concern from Graph connector activation" in paragraph, (
        "The README's frontend paragraph no longer states that Entra "
        "authentication is a separate concern from Graph connector activation."
    )
