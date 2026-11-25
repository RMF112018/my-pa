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
from tests import pins

from my_pa.adapters.mcp.server import published_tools
from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.file_workspace import FILE_WORKSPACE_CAPABILITIES
from my_pa.application.service import (
    _COMMUNICATIONS_CAPABILITIES,
    _ENTITY_CAPABILITIES,
    _ENTITY_WRITE_CAPABILITIES,
    _HANDLERS,
    _LINEAGE_CAPABILITIES,
    _PROGRAM_REPORTING_CAPABILITIES,
    _REPORT_TRANSFER_UPLOAD_CAPABILITIES,
    _SCHEDULE_CAPABILITIES,
    _SCHEDULE_SCENARIO_CAPABILITIES,
)
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.v1.capabilities import Availability, ReadinessState
from my_pa.domain.identity.chatllm_capability_policy import KNOWLEDGE_ASSERTION_DATA_NAMES
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
ARCHITECTURE_INDEX = ROOT / "docs" / "architecture" / "00_ARCHITECTURE_INDEX.md"

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
    # `not_implemented` is both an Availability and a ReadinessState token.
    # In this paragraph it qualifies individual capabilities, while `degraded`
    # is the explicitly stated aggregate readiness.
    claimed = (claimed_tokens() & {member.value for member in ReadinessState}) - {
        Availability.NOT_IMPLEMENTED.value
    }
    _, readiness = published()
    assert claimed == {readiness}, (
        f"The README says readiness is {sorted(claimed)}; it is {readiness!r}."
    )


#: The generated current-state page (phase P5, operator decision O1-a). The
#: head, the revision count and the capability total are stated there and only
#: there; `test_generated_repository_state_is_rendered` holds it to the snapshot.
GENERATED_STATE: Final = "generated/repository-state.md"

#: Every current-state document that used to restate those figures by hand.
CURRENT_STATE_DOCS: Final = {
    "README": README,
    "architecture index": ARCHITECTURE_INDEX,
    "system context": SYSTEM_CONTEXT,
    "module boundaries": MODULE_BOUNDARIES,
    "gateway runbook": ROOT / "ops" / "runbooks" / "gateway-operations.md",
    "MCP runbook": ROOT / "ops" / "runbooks" / "mcp-and-cli-operations.md",
}

#: A spelled count of revisions or capabilities, in any of the shapes these
#: documents wrote it: "<N> Alembic revisions", "**<N>** revisions", "at
#: revision <N>", "<N> capabilities", "<N> public capabilities", with <N> a
#: spelled number of a hundred or more. Any number, right or wrong: the figure
#: lives in the generated page, so restating it is the defect. (The shapes are
#: written with a placeholder here, and planted below through `pins.spell`, so
#: this module states no spelled capability count for the sibling sweep to read.)
_SPELLED_NUMBER: Final = (
    r"(?:(?:one|two|three|four|five|six|seven|eight|nine) (?:thousand|hundred)"
    r"(?: and)?[ -]?)+[a-z-]*"
)
RESTATED_FIGURE: Final = re.compile(
    rf"\b(?:{_SPELLED_NUMBER})\**\s+(?:public\s+)?(?:Alembic\s+)?(?:revisions|capabilit)"
    rf"|\bat revision (?:{_SPELLED_NUMBER})"
    r"|\bhead `[0-9a-f]{12}` at revision",
    re.IGNORECASE,
)


#: A double-quoted span on one line: a dated correction quoting what a sentence
#: used to say ("exposes one hundred one capabilities"), which is history.
_QUOTED: Final = re.compile(r'"[^"\n]*"')


def _unquoted(text: str) -> str:
    return _QUOTED.sub('""', text)


def test_current_state_docs_link_to_the_generated_state_and_do_not_restate_it() -> None:
    """The replacement for the two derived-count guards (O1-a).

    `test_readme_derives_the_current_alembic_count_and_head` and
    `test_current_state_docs_name_the_current_capability_and_migration_counts`
    derived the head, the revision count and the capability total and required
    each document to spell them: correct, and the reason every migration or
    capability edited seven to nine documents. The figures are generated into
    `docs/generated/repository-state.md` now, bound there to the chain and the
    enum. Each document must link to it, and none may spell a revision count, a
    capability total or a `head ... at revision` pair of its own.
    """
    unlinked = [
        label
        for label, path in CURRENT_STATE_DOCS.items()
        if GENERATED_STATE not in path.read_text(encoding="utf-8")
    ]
    assert not unlinked, f"{unlinked} no longer link to docs/{GENERATED_STATE}"
    restated = [
        f"{label}: {match.group(0)!r}"
        for label, path in CURRENT_STATE_DOCS.items()
        for match in RESTATED_FIGURE.finditer(_unquoted(path.read_text(encoding="utf-8")))
    ]
    assert not restated, (
        f"current-state documents restate a figure the generated page owns: {restated}. "
        f"Link to docs/{GENERATED_STATE} instead"
    )


def test_the_restated_figure_reader_reads_every_shape_it_replaced() -> None:
    revisions, capabilities = pins.spell(132), pins.spell(298)
    planted = (
        f"{revisions.capitalize()} Alembic revisions cover the schema.\n"
        f"Alembic owns {revisions} revisions at head `0123456789ab`.\n"
        f"current head `0123456789ab` at revision {revisions}.\n"
        f"the candidate has **{capabilities}**\ncapabilities.\n"
        f"routes the {capabilities} public capabilities over HTTP.\n"
    )
    assert len(RESTATED_FIGURE.findall(planted)) == 5
    assert RESTATED_FIGURE.search(f"settled at revision {revisions}.")
    assert not RESTATED_FIGURE.search(
        "one hundred and twenty-five: one hundred and seventy-four handler-implemented"
    )


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


def test_current_state_docs_derive_the_default_capability_split() -> None:
    """Bind the default and withheld capability figures to runtime wiring."""
    total = len(Capability)
    implemented = len(_HANDLERS)
    unwired = set(Capability) - set(_HANDLERS)
    withheld_families = {
        capability
        for capability in _HANDLERS
        if capability.value.startswith(("documents.", "entities.", "relationship_memory."))
        # KLP-WP-03: the Knowledge Assertion plane, an explicit name set behind
        # `MY_PA_KNOWLEDGE_ASSERTIONS_ENABLED` (default off), never a prefix.
        or capability in KNOWLEDGE_ASSERTION_DATA_NAMES
        # KLP-WP-04: submit and checkpoint join the same switch's family
        # (KLP-WP-05's `record_events.provenance` is in the data-name set above).
        or capability
        in {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
        # Record lineage S1: the lineage plane, behind `MY_PA_LINEAGE_ENABLED`
        # (default off), an explicit name set.
        or capability in _LINEAGE_CAPABILITIES
        # Record lineage S4: the Program-reporting names, behind
        # `MY_PA_PROGRAM_REPORTING_ENABLED` (default off), an explicit name set.
        or capability in _PROGRAM_REPORTING_CAPABILITIES
        # CPM Workbench S5b-2: the Schedule names, behind `MY_PA_SCHEDULE_ENABLED`
        # (default off), an explicit name set.
        or capability in _SCHEDULE_CAPABILITIES
        # Schedule Scenarios S6-3: the 26 plane names, behind
        # `MY_PA_SCHEDULE_SCENARIOS_ENABLED` on top of that switch (default off).
        or capability in _SCHEDULE_SCENARIO_CAPABILITIES
        # Reports Modernization WP06: the four transfer uploads, served only with
        # a report content store and the transfer staging (unset by default).
        or capability in _REPORT_TRANSFER_UPLOAD_CAPABILITIES
        # Files workspace WP5: the 17 `files.*` names, served only with the
        # workspace store (`MY_PA_FILES_WORKSPACE_ROOT`, unset by default).
        or capability in FILE_WORKSPACE_CAPABILITIES
        # Communications intelligence WP4-S5: the 3 `communications.*` reads,
        # behind `MY_PA_COMMUNICATIONS_ENABLED` (default off).
        or capability in _COMMUNICATIONS_CAPABILITIES
    }
    default = len(frozenset(_HANDLERS) - withheld_families)
    withheld = total - default
    assert implemented == total
    assert len(withheld_families) == 177
    assert unwired == set()
    # Phase B's additions all arrived on the withheld side; GSQS B0's pair is
    # composed by default, and `RI-ENT-WP-10`'s five record-family reads arrived
    # on the withheld side too, as do `RI-ENT-WP-11`'s record-family writes. The
    # GoodNotes pull adds three default-composed names after the entity work,
    # and UI-IMP-WP17 admits canvas.workspace get/put on the served side, so the
    # combined surface exposes the derived default and still withholds seventy.
    # `PC-CM-IMP-WP04`'s six Constraint reads arrive on the served side --
    # they are in none of the three withheld families -- so the default grows
    # by six while the withheld figure is unchanged. `PC-CM-IMP-WP07`'s twelve
    # Constraint mutations arrive on the served side for the same reason, and
    # the withheld figure is again unchanged. `PC-CM-RUN01-WP06`'s three
    # cross-Project Constraint reads arrive on the served side too, so the
    # default grows by three and the withheld figure *falls* by three -- the
    # first package in this campaign to move that figure, because these three
    # were counted as withheld while they were unwired rather than as
    # composition-gated.
    # `PC-CM-RUN01-WP07` wired `constraints.create_published`, the last declared
    # name without a handler. It is in none of the three withheld families, so
    # the default grows by one and the withheld figure *falls* by one -- for the
    # same reason WP06's three did, these having been counted as withheld while
    # unwired rather than as composition-gated. The withheld figure is now
    # exactly the three families, and the structurally-unwired remainder is
    # empty for the first time in this campaign.
    # WP-MTG-04's six Meeting names are core and in none of the three withheld
    # families, so the default grows by six and the withheld figure is unchanged.
    # KLP-WP-03's six Knowledge Assertion names are a fourth withheld family
    # (default-off switch), so the default is unchanged and the withheld figure
    # grows by six.
    # KLP-WP-04's submit and checkpoint join that fourth family, so the default
    # is unchanged and the withheld figure grows by two.
    # KLP-WP-05's `record_events.provenance` joins that family too: the default
    # is unchanged and the withheld figure grows by one.
    # The report type registry's `reports.types.create`/`list` are core and in
    # no withheld family, so the default grows by two and the withheld figure
    # is unchanged.
    # Record lineage S1's six Issue-plane names are a fifth withheld family
    # (default-off switch), so the default is unchanged and the withheld figure
    # grows by six.
    # Record lineage S2's names join that fifth family, so the default is
    # unchanged and the withheld figure grows by as many.
    # Record lineage S3's names join it too: the default is unchanged
    # again and the withheld figure grows by as many.
    # Record lineage S4's seven Program-reporting names are a sixth withheld
    # family (their own default-off sub-switch): the default is unchanged and
    # the withheld figure grows by seven.
    # Record lineage S3.1's names join the fifth (lineage) family: the
    # default is unchanged and the withheld figure grows by four.
    # CPM Workbench S5b-2's seven Schedule names are a seventh withheld family
    # (their own default-off switch): the default is unchanged and the withheld
    # figure grows by seven.
    # Reports Modernization WP02's `reports.publish` is core and in no withheld
    # family, so the default grows by one and the withheld figure is unchanged.
    # Reports Modernization WP03's five are core and in no withheld family, so
    # the default grows by five and the withheld figure is unchanged.
    # Reports Modernization WP05b's four custody names are operator-only, core
    # and in no withheld family, so the default grows by four and the withheld
    # figure is unchanged.
    # Reports Modernization WP06's `reports.transfer.read_chunk` is core (the
    # default grows by one); its four uploads are an eighth withheld family
    # (composed only with the content store and the transfer staging), so the
    # withheld figure grows by four.
    # The files workspace WP5's 17 `files.*` names are a ninth withheld family
    # (composed only with the workspace store): the default is unchanged and the
    # withheld figure grows by seventeen.
    # Communications intelligence WP2-W3's `meetings.provider.bind` is core and
    # in no withheld family: the default grows by one, the withheld figure holds.
    # Communications intelligence WP3b-S4's `meetings.provider.review` and
    # `meetings.provider.reconcile` are core and in no withheld family: the
    # default grows by two, the withheld figure holds.
    # Communications intelligence WP4-S5's three `communications.*` reads are a
    # tenth withheld family (default-off switch): the default is unchanged and
    # the withheld figure grows by three.
    assert default == 127 and withheld == 177

    # Exercise the same application and MCP publication composition that owns
    # the current 91-tool measurement. GoodNotes pull is part of that measured
    # composition and its authenticated-client presence is required for the
    # three pull tools to be published; the other three documented families
    # remain deliberately uncomposed.
    runtime = build_gateway_runtime(
        Settings(
            database_url=f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere",
            goodnotes_pull_enabled=True,
            goodnotes_pull_cursor_signing_key="synthetic-current-state-key-0001",
        )
    )
    try:
        application_capabilities = runtime.service.available_capabilities
        authenticated_mcp_capabilities = {
            tool.name
            for tool in published_tools(runtime.service, authenticated_client_present=True)
        }
        local_mcp_capabilities = {tool.name for tool in published_tools(runtime.service)}
    finally:
        runtime.close()
    assert len(application_capabilities) == default
    assert authenticated_mcp_capabilities == {
        capability.value for capability in application_capabilities
    }
    assert len(local_mcp_capabilities) == default - 3 == 124
    assert authenticated_mcp_capabilities - local_mcp_capabilities == {
        "goodnotes.pull",
        "goodnotes.complete",
        "goodnotes.status",
    }

    entity_total = len(_ENTITY_CAPABILITIES)
    entity_writes = len(_ENTITY_WRITE_CAPABILITIES)
    entity_reads = entity_total - entity_writes
    assert _ENTITY_WRITE_CAPABILITIES <= _ENTITY_CAPABILITIES
    assert entity_total == 55 and entity_reads == 17 and entity_writes == 38

    readme = README.read_text(encoding="utf-8")
    assert f"{default} of the {total} capabilities are `available`" in readme
    assert f"`{withheld} of {total} capabilities are unwired.`" in readme
    assert f"{implemented} have application commands/handlers" in readme
    assert f"fully composed authenticated client sees all {implemented} implemented tools" in readme
    entity_split = (
        f"{pins.spell(entity_total)} `entities.*` capabilities: "
        f"{pins.spell(entity_reads)} reads and "
        f"{pins.spell(entity_writes)} writes"
    )
    assert entity_split in readme
    assert "forty-two `entities.*` capabilities" not in readme
    assert "twenty-nine writes" not in readme

    # PC-CM-RUN01-WP05 corrective cycle. Three derived counts went stale across
    # WP04/WP07 because nothing here named the sentences that carried them: the
    # README's breakdown of the withheld 74, the system-context wiring figure,
    # and the MCP/CLI runbook's command-backed and unwired figures. They are
    # bound now, from `_HANDLERS` and `Capability` rather than from a literal,
    # so the next package that moves the numbers moves these too.
    unwired_count = len(unwired)
    assert withheld == len(withheld_families) + unwired_count
    # The remainder reached one at `PC-CM-RUN01-WP06`, so these sentences are
    # grammatically singular now and will be plural again only if a later
    # package declares a name it does not wire. The number and the grammar are
    # derived together rather than spelled, because a guard that asserted the
    # plural wording while the prose had gone singular would be checking a
    # sentence the document no longer contains.
    # The remainder reached zero at `PC-CM-RUN01-WP07`, so the three sentences
    # that used to count it now have to say there is none rather than count to
    # nothing: "the zero remaining Run 01 names" is not a sentence any of these
    # documents should contain. The claim being bound is unchanged -- the
    # withheld figure is accounted for in full and cannot go stale -- and both
    # branches are written out, so a future package that declares a name ahead
    # of wiring it gets the counting form back automatically rather than
    # needing this guard rebuilt.
    names = "name" if unwired_count == 1 else "names"
    if unwired_count:
        readme_breakdown = (
            f"and the {pins.spell(unwired_count)} remaining Run 01 {names} — are\n`not_implemented`"
        )
    else:
        readme_breakdown = (
            "names, which is now the whole of the withheld figure — are\n`not_implemented`"
        )
    assert readme_breakdown in readme, (
        "The README's breakdown of the withheld capabilities no longer accounts for the "
        f"{unwired_count} structurally unwired Run 01 {names}. It is the sentence "
        f"that accounts for all {withheld} of them."
    )

    system_context_text = SYSTEM_CONTEXT.read_text(encoding="utf-8")
    assert f"wires {implemented} through HTTP, MCP, and CLI composition" in system_context_text
    system_context = system_context_text.lower()
    assert f"exposes {default} of them" in system_context

    architecture_index = (ROOT / "docs/architecture/00_ARCHITECTURE_INDEX.md").read_text(
        encoding="utf-8"
    )
    runbook = (ROOT / "ops/runbooks/mcp-and-cli-operations.md").read_text(encoding="utf-8")
    gateway_runbook = (ROOT / "ops/runbooks/gateway-operations.md").read_text(encoding="utf-8")
    assert f"default composition serves {default} of" in architecture_index
    assert f"**{default} application-available capabilities**" in runbook
    assert f"publishes **{default - 3} tools**" in runbook
    assert f"unconfigured local stdio: {default - 3}" in runbook
    # KLP-WP-04: fully composed local stdio also withholds the two client-bound
    # Knowledge discovery capabilities (three GoodNotes pull + two = five).
    assert f"fully feature-composed local stdio: {implemented - 5}" in runbook
    assert f"{implemented} have application commands/handlers" in runbook
    assert f"all {implemented} implemented tools" in runbook
    normalized_runbook = " ".join(runbook.split()).lower()
    assert f"the {pins.spell(implemented)} command-backed names" in normalized_runbook, (
        "the MCP/CLI runbook's command-backed figure no longer matches the dispatch table"
    )
    unwired_runbook_claim = (
        f"the exact {pins.spell(unwired_count)} remaining run 01 {names} as `not_implemented`"
        if unwired_count
        else "no declared name is left without one"
    )
    assert unwired_runbook_claim in normalized_runbook, (
        "the MCP/CLI runbook's unwired Run 01 figure no longer matches the dispatch table"
    )
    assert f"A default process serves\n{pins.spell(default)}" in gateway_runbook
    assert (
        f"{pins.spell(len(withheld_families))} handler-implemented capabilities "
        "are composition-withheld"
    ) in gateway_runbook
    gateway_unwired_claim = (
        f"{pins.spell(unwired_count)}\n{'is' if unwired_count == 1 else 'are'} structurally unwired"
        if unwired_count
        else "none\nis structurally unwired"
    )
    assert gateway_unwired_claim in gateway_runbook
    assert (
        f"`{withheld} of {total} total capabilities are unavailable or unwired.`" in gateway_runbook
    )

    completion_state = section_of(
        COMPLETION_PLAN.read_text(encoding="utf-8"), "3. What is implemented"
    )
    normalized_completion_state = " ".join(completion_state.split()).lower()
    assert f"names, {implemented} have application commands/handlers" in normalized_completion_state
    completion_unwired_claim = (
        f"{pins.spell(unwired_count)} remaining run 01 {names} "
        f"{'remains' if unwired_count == 1 else 'remain'} structurally unwired"
        if unwired_count
        else "no run 01 name remains structurally unwired"
    )
    assert completion_unwired_claim in normalized_completion_state

    # The spelled capability total these documents carried is generated now:
    # `test_current_state_docs_link_to_the_generated_state_and_do_not_restate_it`.


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
        "/api/webauthn",
        "/sign-in",
        "/setup",
        "/recover/operator",
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
    # The capability total is generated (phase P5): the web README links to it
    # and, like every current-state document, does not restate it.
    assert GENERATED_STATE in text
    assert not RESTATED_FIGURE.search(_unquoted(text)), RESTATED_FIGURE.search(_unquoted(text))
    # WP11 is MCP/backend-only; the browser routes remain the pre-sync subset.
    sync_capabilities = {
        capability for capability in capability_values if capability.startswith("constraint_sync.")
    }
    assert len(sync_capabilities) == 7
    assert sync_capabilities.isdisjoint(routed)
    normalized_text = " ".join(lowered.split())
    assert "seven `constraint_sync.*` backend and mcp capabilities" in normalized_text
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
        "authorization-code",
        "pkce s256",
        "process-local",
        "server-held bearer",
    ):
        assert stale not in text, f"web README restored stale claim: {stale}"
    for current in (
        "opaque sid",
        "passkey",
        "session-service",
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


def test_the_knowledge_plane_switch_and_its_cursor_reset_are_documented() -> None:
    """KLP-AC-083 / KLP-AC-141: default off, needs the entity plane, resets cursors."""
    from my_pa.bootstrap.settings import Settings

    assert Settings.model_fields["knowledge_assertions_enabled"].default is False
    readme = README.read_text(encoding="utf-8")
    gateway_runbook = (ROOT / "ops/runbooks/gateway-operations.md").read_text(encoding="utf-8")
    assert "MY_PA_KNOWLEDGE_ASSERTIONS_ENABLED" in readme
    normalized = " ".join(gateway_runbook.split())
    assert (
        "Enabling the Knowledge Assertion plane is a Record Event cursor-reset condition"
        in normalized
    )
    assert "MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` is on too" in normalized
