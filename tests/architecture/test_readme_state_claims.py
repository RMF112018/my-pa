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

import pytest

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

#: A Markdown heading at any level. A section ends where the next one begins,
#: which is the document's own boundary rather than a second literal written
#: here that a rename or a reorder can silently detach.
_HEADING = re.compile(r"^#{1,6} ", re.MULTILINE)

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


def section_of(text: str, title: str) -> str:
    """The named section's own text, ending where the next heading begins.

    `README.split("## Current state", 1)[1]` had no terminator, so a scan called
    "Current state" actually covered "Approved architectural decisions",
    "Repository map" and "Boundaries" too. That is not a wider check; it is a
    check of a different thing. Proven with a plant: the Current state sentence
    was rewritten to say the opposite — the capture workflows *unproven and
    untested* — and the phrases it is asserted to contain were moved down into
    "Boundaries", and every assertion below still passed.

    The boundary is `_HEADING`, so a renamed or reordered section moves the end
    of the scan with it, and a heading inserted in the middle narrows the scan
    rather than leaving it silently open to end of file.
    """
    opening = re.compile(rf"^#{{1,6}} {re.escape(title)}\s*$", re.MULTILINE).search(text)
    assert opening is not None, (
        f"the document has no {title!r} heading. This scan is anchored on it, and a "
        "scan whose anchor is gone decides nothing."
    )
    following = [
        match.start() for match in _HEADING.finditer(text) if match.start() > opening.start()
    ]
    section = text[opening.end() : following[0] if following else len(text)]
    assert section.strip(), f"the {title!r} section is empty"
    return section


def readme_section(title: str) -> str:
    """`section_of` over the real README."""
    return section_of(README.read_text(encoding="utf-8"), title)


def test_a_readme_section_stops_at_the_next_heading() -> None:
    """The plant the reviewer ran, hermetically: the claim moved out of the section.

    `## Current state` used to be split with no terminator, so the scan covered
    every later section too and a sentence relocated into `## Boundaries`
    satisfied it. Here the same relocation is written out. The control is the
    other half — the section still yields its own sentence and the boundary has
    not narrowed to nothing — and the third case is the one a missing terminator
    gets right by accident, the last section in the document.
    """
    document = "\n".join(
        [
            "# my-pa",
            "",
            "## Current state",
            "",
            "the capture workflows are unproven and untested.",
            "",
            "## Boundaries",
            "",
            "the capture workflows run end to end over synthetic fixtures.",
            "",
        ]
    )

    current = section_of(document, "Current state")
    assert "unproven and untested" in current
    assert "run end to end over synthetic fixtures" not in current
    assert "run end to end over synthetic fixtures" in section_of(document, "Boundaries")

    with pytest.raises(AssertionError, match="has no 'Repository map' heading"):
        section_of(document, "Repository map")


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
    """The not-implemented list, with the emptiness the `not in` below needs.

    The region is bounded by two literals, and `Accordingly,` is a word rather
    than a heading: a second sentence beginning with it, written anywhere above
    the current one, collapses the region to nothing and leaves the absence
    assertion passing on an empty string. A rule that cannot fail is the same
    defect as a rule that scans the wrong section, one layer along, so the list
    the region is *about* is what has to be there before its absence means
    anything.

    The threshold is one entry rather than two. It arrived here as two, keyed to
    a README on another branch whose not-implemented list was longer; this
    repository's list currently names a single item, so two would be a spelled
    count of a set that shrinks as packages land — the defect this file's
    siblings were just unkeyed from. One entry is the whole of what the absence
    assertion needs: at zero the region has collapsed and `not in` decides
    nothing, at one or more it is demonstrably the list.
    """
    assert RELATIONSHIP_PACKAGE.is_dir()
    readme = README.read_text(encoding="utf-8")
    section = readme.split("Not implemented.", 1)[1].split("Accordingly,", 1)[0]
    entries = re.findall(r"^- .+$", section, re.MULTILINE)
    assert entries, (
        "the README's not-implemented region holds no list entries; "
        "the absence assertion below would be passing on nothing"
    )
    assert "relationship identity and profiles" not in section.lower()
    assert "fixture" in readme.lower() and "wp-9" in readme.lower()


def test_current_state_says_the_synthetic_workflow_runs_but_is_not_deployable() -> None:
    """Bounded to the section it names. See `readme_section` for what it was."""
    current = " ".join(readme_section("Current state").split())
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
