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
from typing import Final

import pytest

from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.v1.capabilities import Availability, ReadinessState
from my_pa.domain.identity.operation import Capability

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
WEB_README = ROOT / "web" / "README.md"
RELATIONSHIP_PACKAGE = ROOT / "src" / "my_pa" / "domain" / "relationship"
SOURCE_INDEX = ROOT / "docs" / "00_REPOSITORY_SOURCE_INDEX.md"
SPECS_INDEX = ROOT / "docs" / "specs" / "README.md"
COMPLETION_PLAN = ROOT / "docs" / "plans" / "mcv-completion-plan.md"
SYSTEM_CONTEXT = ROOT / "docs" / "architecture" / "system-context.md"
MODULE_BOUNDARIES = ROOT / "docs" / "architecture" / "module-boundaries.md"

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
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1
    return len(list(script.walk_revisions())), heads[0]


#: Spelled revision counts, so a guard states the count the chain actually has
#: rather than a literal that goes stale in step with the prose it guards.
SPELLED_COUNTS: Final[dict[int, str]] = {
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
    22: "Twenty-two",
    23: "Twenty-three",
    24: "Twenty-four",
    25: "Twenty-five",
    26: "Twenty-six",
    27: "Twenty-seven",
    28: "Twenty-eight",
    29: "Twenty-nine",
    30: "Thirty",
    31: "Thirty-one",
    32: "Thirty-two",
    33: "Thirty-three",
    34: "Thirty-four",
    35: "Thirty-five",
    36: "Thirty-six",
    37: "Thirty-seven",
    38: "Thirty-eight",
    39: "Thirty-nine",
    40: "Forty",
    41: "Forty-one",
    42: "Forty-two",
    43: "Forty-three",
    44: "Forty-four",
    45: "Forty-five",
    46: "Forty-six",
    47: "Forty-seven",
    48: "Forty-eight",
    49: "Forty-nine",
    50: "Fifty",
    51: "Fifty-one",
    52: "Fifty-two",
    53: "Fifty-three",
    54: "Fifty-four",
    55: "Fifty-five",
    56: "Fifty-six",
    57: "Fifty-seven",
    58: "Fifty-eight",
    59: "Fifty-nine",
    60: "Sixty",
    61: "Sixty-one",
    62: "Sixty-two",
    63: "Sixty-three",
    64: "Sixty-four",
    65: "Sixty-five",
    66: "Sixty-six",
    67: "Sixty-seven",
    68: "Sixty-eight",
    69: "Sixty-nine",
    70: "Seventy",
    71: "Seventy-one",
    72: "Seventy-two",
    73: "Seventy-three",
    74: "Seventy-four",
    75: "Seventy-five",
    76: "Seventy-six",
    77: "Seventy-seven",
    78: "Seventy-eight",
    79: "Seventy-nine",
    80: "Eighty",
    # The eighties and the nineties, extended each time the public capability
    # set crossed a decade -- at `WP-RI-A-02`, and again when Phase A's three
    # entity work packages integrated and it reached ninety-five. The map is
    # extended rather than the assertion relaxed, for the reason it exists: a
    # figure this test cannot spell is a figure it cannot check, and "extend the
    # readable count vocabulary" is a refusal rather than a pass.
    81: "Eighty-one",
    82: "Eighty-two",
    83: "Eighty-three",
    84: "Eighty-four",
    85: "Eighty-five",
    86: "Eighty-six",
    87: "Eighty-seven",
    88: "Eighty-eight",
    89: "Eighty-nine",
    90: "Ninety",
    91: "Ninety-one",
    92: "Ninety-two",
    93: "Ninety-three",
    94: "Ninety-four",
    95: "Ninety-five",
    96: "Ninety-six",
    97: "Ninety-seven",
    98: "Ninety-eight",
    99: "Ninety-nine",
    100: "One hundred",
    101: "One hundred one",
    102: "One hundred two",
    103: "One hundred three",
    104: "One hundred and four",
    # Extended at `RI-ENT-WP-10`, when the entity plane's five record-family
    # reads took the public set past a hundred and four. The map is extended
    # rather than the assertion relaxed, for the reason stated at the eighties:
    # a figure this test cannot spell is a figure it cannot check.
    105: "One hundred five",
    106: "One hundred six",
    107: "One hundred seven",
    108: "One hundred eight",
    109: "One hundred and nine",
}


def test_readme_derives_the_current_alembic_count_and_head() -> None:
    count, head = _alembic_identity()
    assert count in SPELLED_COUNTS, "extend the readable README count vocabulary"
    readme = README.read_text(encoding="utf-8")
    assert f"{SPELLED_COUNTS[count]} Alembic revisions" in readme
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


def test_readme_declares_the_current_remediation_lineage_and_preserves_history() -> None:
    """Current branch/base authority and the former lineage must not blur."""
    readme = README.read_text(encoding="utf-8")
    assert "## Operating lineage" in readme, "The README's 'Operating lineage' section is gone."
    section = readme.split("## Operating lineage", 1)[1].split("## Current state", 1)[0]
    assert "bf/pilot-blocker-remediation" in section
    assert "9b35476b70fe4fbc03bb8f9835d93c1b71089bbe" in section
    assert "recovery/pre-20260805-utc-rollback-c9fb513" in section
    assert "campaign history" in section and "no longer current-state authority" in section


def test_current_state_docs_name_the_current_capability_and_migration_counts() -> None:
    """Protect the two exact-state figures that repeatedly went stale.

    The head is derived rather than written down here. It was a literal until
    `9def3c2e63bb` moved it, and a literal in the guard is the same claim with
    the same shelf life as the literal in the document it is guarding — so the
    guard went stale in step with the prose instead of catching it.

    The capability figure is now derived for the same reason and by the same
    argument. It was a spelled literal until `d2b8f5c04e71` admitted the
    `entities.*` names, and on that day the guard and all three documents were
    wrong together — the guard asserting the stale spelling was present, which is
    the one thing that cannot detect a stale spelling. `Capability` is what the
    application dispatches on, so it is what the prose has to agree with.
    """
    _count, head = _alembic_identity()
    capabilities = len(list(Capability))
    assert capabilities in SPELLED_COUNTS, "extend the readable count vocabulary"
    spelled = SPELLED_COUNTS[capabilities].lower()
    documents = {
        "system context": ROOT / "docs" / "architecture" / "system-context.md",
        "gateway runbook": ROOT / "ops" / "runbooks" / "gateway-operations.md",
        "MCP runbook": ROOT / "ops" / "runbooks" / "mcp-and-cli-operations.md",
    }
    for label, path in documents.items():
        text = path.read_text(encoding="utf-8")
        assert f"{spelled} capabilit" in text.lower().replace(" public ", " "), (
            f"{label} lost the current capability count"
        )
        assert SPELLED_COUNTS[_count].lower() in text.lower(), (
            f"{label} lost the current revision count"
        )
        assert head in text, f"{label} lost the current Alembic head"


def test_current_state_docs_derive_the_default_capability_split() -> None:
    """Bind the default and withheld capability figures to runtime wiring."""
    total = len(Capability)
    withheld_families = {
        capability
        for capability in _HANDLERS
        if capability.value.startswith(("documents.", "entities.", "relationship_memory."))
    }
    default = len(frozenset(_HANDLERS) - withheld_families)
    withheld = total - default
    # Phase B's additions all arrived on the withheld side; GSQS B0's pair is
    # composed by default, and `RI-ENT-WP-10`'s five record-family reads arrive
    # on the withheld side too. The combined surface therefore still exposes
    # fifty-five and withholds five more feature-gated names than before.
    assert default == 55 and total == 109 and withheld == 54

    readme = README.read_text(encoding="utf-8")
    assert f"{default} of the {total} capabilities are `available`" in readme
    assert f"`{withheld} of {total} capabilities are unwired.`" in readme

    system_context = SYSTEM_CONTEXT.read_text(encoding="utf-8").lower()
    assert "one hundred and nine capabilities" in system_context
    assert "exposes fifty-five of them" in system_context

    module_boundaries = MODULE_BOUNDARIES.read_text(encoding="utf-8").lower()
    assert "one hundred and nine capabilities" in module_boundaries


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


def test_web_readme_names_the_routes_and_capabilities_the_bff_reaches() -> None:
    """Keep the web current-state map tied to the route source, not campaign history."""
    text = WEB_README.read_text(encoding="utf-8")
    lowered = text.lower()
    for route in (
        "/api/capture",
        "/api/library",
        "/api/projects",
        "/api/pulse",
        "/api/relationships/:personId/timeline",
        "/api/reveal",
        "/api/review",
        "/api/situations",
        "/api/system",
        "/api/session",
        "/auth/sign-in",
        "/auth/callback",
    ):
        assert route in text, f"web README lost current route {route}"

    capability_values = {capability.value for capability in Capability}
    routed = set()
    for path in (ROOT / "web" / "src" / "app" / "api").rglob("route.ts"):
        routed.update(re.findall(r'["\']([a-z]+(?:\.[a-z]+)+)["\']', path.read_text()))
    routed &= capability_values
    assert routed, "the API route scan found no capability names"
    documented = set(re.findall(r"`([a-z]+(?:\.[a-z]+)+)`", text))
    assert routed <= documented, (
        f"web README omits routed capabilities {sorted(routed - documented)}"
    )
    # Derived, not spelled out here: see the note on
    # `test_current_state_docs_name_the_current_capability_and_migration_counts`.
    # A literal in this guard is the same claim, with the same shelf life, as the
    # literal in the document it is guarding.
    assert len(capability_values) in SPELLED_COUNTS, "extend the readable count vocabulary"
    assert f"{SPELLED_COUNTS[len(capability_values)].lower()} capability names" in lowered
    work_routed = {
        "tasks.read",
        "tasks.list",
        "tasks.search",
        "tasks.history",
        "tasks.create",
        "tasks.update",
        "tasks.transition",
        "commitments.read",
        "commitments.list",
        "commitments.search",
        "commitments.history",
        "commitments.create",
        "commitments.update",
        "commitments.close",
    }
    assert work_routed <= routed
    assert work_routed <= documented
    assert "worker_planes" in text and "capture" in text and "enrollment" in text
    assert "managed-document lifecycle" in lowered


def test_web_readme_does_not_restore_superseded_frontend_claims() -> None:
    text = WEB_README.read_text(encoding="utf-8").lower()
    for stale in (
        "operating lineage",
        "relationship timeline | `/api/relationships/:id/timeline` | **not wired**",
        "this tier holds none",
        "implements no real sign-in",
        "dispatches fifteen",
        "none exists",
    ):
        assert stale not in text, f"web README restored stale claim: {stale}"
    for current in (
        "authorization-code",
        "pkce s256",
        "process-local",
        "server-held bearer",
        "explicitly release it for retry or delete the local copy",
    ):
        assert current in text, f"web README lost current claim: {current}"


def test_root_readme_distinguishes_credentialless_local_mode_from_entra() -> None:
    text = README.read_text(encoding="utf-8")
    assert "no credential is issued, read, or required" not in text
    assert "`local_operator` mode" in text
    assert "`entra` mode it requires and validates a bearer token" in text
    assert "credential creation/disclosure/rotation" in text


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
