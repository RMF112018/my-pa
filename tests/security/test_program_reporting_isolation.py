"""AT-023 (S4, DB): Program reporting discloses nothing across Principals or families.

Record lineage S4 contract sections 6.1, 6.2 and 7.5, against PostgreSQL
through `ApplicationService.invoke` with the Program read pool composed as the
gateway composes it. The resolver rows (worker M2, WP-04A):

* another Principal's Program answers exactly as an absent one;
* a remote reader without a grant on `programs.members.resolve` (or, worker
  M5, on `reports.manifest`) is `unsupported` (the S3 grant re-check, R3-F13);
* a remote reader that does not see both the `entity` and the `project`
  family sees no Program -- `not_found`, never a partial answer;
* with either switch off, every S4 capability answers `unsupported`;
* a Program-read statement cancelled by its timeout answers `unavailable`.

The Commitment v2 rows (worker M3, section 7.3):

* a remote reader without a grant on its own `commitments.v2.*` name is
  `unsupported`, whatever family reads it holds;
* `project_reference` is `restricted` without the `project` family, and a
  context `situation_reference` without the `situation` family;
* an Issue `situation_reference` needs the `issue` family, never the
  `situation` one (R4-F17).

The overview rows (worker M4, section 7.2):

* another Principal's rows -- a full copy of the scene and a Commitment storing
  this Principal's Project id -- change nothing in this Principal's overview;
* a remote reader without a grant on `programs.overview` is `unsupported`, and
  one without the `entity` and `project` families sees no Program;
* an invisible family's metrics are `restricted` at every scope, never a
  count, and every field derived from it is `null`: the calendar, source state,
  sync and source-state denominator without `constraint`, the lineage horizon
  and the legacy-link fields without `issue`;
* an overview statement cancelled by its timeout answers `unavailable`.

The manifest rows (worker M5, sections 6.2 and 7.4):

* a commit-time recompute runs with the committing caller's visibility, so
  its outcome is exactly that caller's own `programs.overview`; a caller
  `programs.overview` does not admit records `not_attempted`, whatever the
  Program ids name;
* `reports.manifest` releases a manifest whose Program state is not
  `not_attempted` only to a reader holding a `programs.overview` grant for
  `program_reporting_read`, the `entity` and `project` families, and every
  family the server state was computed with -- otherwise
  `restricted_evidence`, with neither the text nor any digest of it;
* `families_seen` names only the overview's 5 families.

Every identity is synthetic.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import text
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_s3_read_harness import grant
from tests.database.lineage_s4_harness import (
    PROGRAM_STATEMENT_TIMEOUT_MS,
    T0,
    S4Runtime,
)

from my_pa.application.commands import (
    Command,
    ListCommitmentsV2,
    ReadCommitmentV2,
    ReadProgramOverview,
    ReadReportManifest,
    ResolveProgramMembers,
    SearchCommitmentsV2,
    WaitingOnV2,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import IntelligenceStage
from my_pa.domain.intelligence.source_manifest import server_state
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

pytestmark = pytest.mark.database

#: The 2 families both Program reads need (section 6.2), by one read each.
ROOT_READS: Final = ("entities.get", "continuity.projects")
#: An Entity identifier no row carries.
ABSENT: Final = "ent_programisolabsent01"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _program_with_member(runtime: S4Runtime, *, principal_id: str | None = None) -> str:
    seeds = runtime.seeds
    owner = {} if principal_id is None else {"principal_id": principal_id}
    program = seeds.program("Isolation Program", **owner)
    _project, entity = seeds.project("Isolation member", **owner)
    seeds.edge(entity, program, effective_from=T0, **owner)
    return program


def _document(error: dict[str, Any]) -> dict[str, Any]:
    """The error document without its per-request correlation id."""
    return {key: value for key, value in error.items() if key != "correlation_id"}


def _resolve(program: str) -> ResolveProgramMembers:
    return ResolveProgramMembers(program_entity_ids=(program,))


def _error(runtime: S4Runtime, command: Command, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def test_a_foreign_program_answers_like_an_absent_one(runtime: S4Runtime) -> None:
    foreign = _program_with_member(runtime, principal_id=OTHER_PRINCIPAL)
    own = _program_with_member(runtime)
    # The owner sees its Program; the other Principal's id answers exactly as
    # an id no row carries -- the whole error document, not only its code.
    assert runtime.resolve(foreign, principal_id=OTHER_PRINCIPAL)["programs"][0]["members"]
    absent = _document(runtime.refused(_resolve(ABSENT)))
    assert _document(runtime.refused(_resolve(foreign))) == absent
    assert (absent["code"], absent["safe_details"]) == ("not_found", ["program_entity_ids"])
    # Mixed with an own Program, the foreign one still refuses the request.
    mixed = runtime.refused(ResolveProgramMembers(program_entity_ids=(own, foreign)))
    assert _document(mixed) == absent
    # Nothing of the other Principal's graph reaches an own Program's answer.
    answer = runtime.resolve(own)
    assert foreign not in str(answer)


def test_a_remote_read_without_its_grant_is_unsupported(runtime: S4Runtime) -> None:
    program = _program_with_member(runtime)
    _commitment_v2_grant_cases(runtime)
    _overview_grant_cases(runtime, program)
    _manifest_grant_cases(runtime)
    # Every family read, but no grant on `programs.members.resolve` itself.
    families_only = grant(*ROOT_READS)
    assert _error(runtime, _resolve(program), grants=families_only) == ("unsupported", [])
    # A grant on it for a purpose it does not permit admits nothing either.
    misgranted = families_only | {(Capability.PROGRAMS_MEMBERS_RESOLVE, Purpose.REPORT_READ)}
    assert _error(runtime, _resolve(program), grants=misgranted) == ("unsupported", [])
    # With the grant, the same caller is answered.
    granted = grant("programs.members.resolve", *ROOT_READS)
    answer = runtime.ok(_resolve(program), grants=granted)
    assert len(answer["programs"][0]["members"]) == 1


@pytest.mark.parametrize(
    "reads",
    [(), ("entities.get",), ("continuity.projects",), ("continuity.projects.read",)],
    ids=["neither", "entity-only", "project-only", "project-read-only"],
)
def test_a_remote_reader_without_entity_and_project_reads_sees_no_program(
    runtime: S4Runtime, reads: tuple[str, ...]
) -> None:
    program = _program_with_member(runtime)
    grants = grant("programs.members.resolve", *reads)
    # Not a partial answer: the Program is invisible, as an absent one is.
    assert _error(runtime, _resolve(program), grants=grants) == (
        "not_found",
        ["program_entity_ids"],
    )
    assert _error(runtime, _resolve(ABSENT), grants=grants) == (
        "not_found",
        ["program_entity_ids"],
    )
    # Either read of each family is enough.
    for entity_read in ("entities.get", "entities.search"):
        for project_read in ("continuity.projects", "continuity.projects.read"):
            seen = grant("programs.members.resolve", entity_read, project_read)
            assert runtime.ok(_resolve(program), grants=seen)["programs"][0]["members"]
    # The overview applies the same root rule (worker M4), every other family granted.
    overview_grants = grant("programs.overview", *reads, *METRIC_FAMILY_READS)
    for requested in (program, ABSENT):
        assert _error(runtime, _overview(requested), grants=overview_grants) == (
            "not_found",
            ["program_entity_ids"],
        )
    for entity_read in ("entities.get", "entities.search"):
        for project_read in ("continuity.projects", "continuity.projects.read"):
            seen = grant("programs.overview", entity_read, project_read)
            assert runtime.ok(_overview(program), grants=seen)["programs"][0]["project_ids"]


#: Every family read a v2 Commitment reference can need (section 6.2).
V2_FAMILY_READS: Final = (
    "commitments.read",
    "continuity.projects",
    "continuity.situations",
    "issues.read",
)


def _commitment_v2_grant_cases(runtime: S4Runtime) -> None:
    """Each `commitments.v2.*` name re-checks its own grant (section 6.1, R3-F13)."""
    project, _entity = runtime.seeds.project("Isolation v2 grant")
    commitment = runtime.work_commitment("isolation-v2-grant", project_id=project)
    for command in (
        ReadCommitmentV2(commitment_id=commitment),
        ListCommitmentsV2(project_ids=(project,)),
        SearchCommitmentsV2(query="isolation"),
        WaitingOnV2(),
    ):
        name = command.capability.value
        # Every family read and the v1 sibling, but no grant on the v2 name.
        sibling = name.replace(".v2.", ".")
        families_only = grant(*V2_FAMILY_READS, sibling)
        assert _error(runtime, command, grants=families_only) == ("unsupported", []), name
        # A grant on it for a purpose it does not permit admits nothing either.
        misgranted = families_only | {(command.capability, Purpose.REPORT_READ)}
        assert _error(runtime, command, grants=misgranted) == ("unsupported", []), name
        # With the grant, the same caller is answered.
        assert runtime.ok(command, grants=grant(name, *V2_FAMILY_READS)), name


def _manifest_grant_cases(runtime: S4Runtime) -> None:
    """`reports.manifest` re-checks its own grant (section 6.1, R3-F13)."""
    cycle = runtime.cycle("isolation-manifest-grant")
    collector = runtime.commit_report(
        runtime.report(cycle, IntelligenceStage.COLLECTOR, "isolation-manifest-grant")
    )
    command = ReadReportManifest(report_id=collector["report_id"])
    # `reports.read` and the Program reads, but no grant on `reports.manifest`.
    families_only = grant("reports.read", "programs.overview", *ROOT_READS)
    assert _error(runtime, command, grants=families_only) == ("unsupported", [])
    misgranted = families_only | {(Capability.REPORTS_MANIFEST, Purpose.PROGRAM_REPORTING_READ)}
    assert _error(runtime, command, grants=misgranted) == ("unsupported", [])
    granted = runtime.ok(command, grants=grant("reports.manifest"))
    assert granted["manifest_state"] == "recorded"


def _references(
    runtime: S4Runtime, commitment_id: str, reads: tuple[str, ...]
) -> list[tuple[Any, Any, Any, Any]]:
    """`(project_id, project_reference, situation_id, situation_reference)` per v2 read.

    The single read, and the row of the same Commitment in the list, search and
    `waiting_on` pages, for a remote reader holding the 4 v2 grants and `reads`.
    """
    grants = grant(
        "commitments.v2.read",
        "commitments.v2.list",
        "commitments.v2.search",
        "commitments.v2.waiting_on",
        *reads,
    )

    def shown(item: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
        return (
            item["project_id"],
            item["project_reference"],
            item["situation_id"],
            item["situation_reference"],
        )

    found = [
        shown(
            runtime.ok(ReadCommitmentV2(commitment_id=commitment_id), grants=grants)["commitment"]
        )
    ]
    for command, key in (
        (ListCommitmentsV2(), "commitments"),
        (SearchCommitmentsV2(query="isolation"), "commitments"),
        (WaitingOnV2(), "waiting_on"),
    ):
        rows = runtime.ok(command, grants=grants)[key]
        found.extend(shown(item) for item in rows if item["commitment_id"] == commitment_id)
    assert len(found) == 4
    return found


def test_v2_references_are_restricted_without_the_project_or_situation_family(
    runtime: S4Runtime,
) -> None:
    project, _entity = runtime.seeds.project("Isolation v2 references")
    context = runtime.context_situation("isolation-v2-context")
    commitment = runtime.work_commitment(
        "isolation-v2-references", project_id=project, situation_id=context
    )
    # Neither family: both references restricted, neither id shown.
    assert set(_references(runtime, commitment, ())) == {(None, "restricted", None, "restricted")}
    # The `project` family (either read) shows the Project only.
    for project_read in ("continuity.projects", "continuity.projects.read"):
        assert set(_references(runtime, commitment, (project_read,))) == {
            (project, "owned", None, "restricted")
        }
    # The `situation` family shows the context Situation only.
    assert set(_references(runtime, commitment, ("continuity.situations",))) == {
        (None, "restricted", context, "owned")
    }
    # Both: both shown, as a local caller sees them.
    assert set(
        _references(runtime, commitment, ("continuity.projects", "continuity.situations"))
    ) == {(project, "owned", context, "owned")}
    local = runtime.ok(ReadCommitmentV2(commitment_id=commitment))["commitment"]
    assert (local["project_id"], local["situation_id"]) == (project, context)
    # A remote reader without the `project` family sees no Project to filter
    # by either: its own Project answers as an absent one.
    without = grant("commitments.v2.list")
    assert _error(runtime, ListCommitmentsV2(project_ids=(project,)), grants=without) == (
        "not_found",
        ["project_ids"],
    )
    with_projects = grant("commitments.v2.list", "continuity.projects")
    listed = runtime.ok(ListCommitmentsV2(project_ids=(project,)), grants=with_projects)
    assert [item["commitment_id"] for item in listed["commitments"]] == [commitment]


def test_an_issue_situation_reference_needs_the_issue_family(runtime: S4Runtime) -> None:
    project, _entity = runtime.seeds.project("Isolation v2 issue reference")
    issue = runtime.issue("isolation-v2-issue")
    context = runtime.context_situation("isolation-v2-issue-context")
    on_issue = runtime.work_commitment("isolation-v2-on-issue", project_id=project)
    runtime.store_situation(on_issue, issue)
    on_context = runtime.work_commitment(
        "isolation-v2-on-context", project_id=project, situation_id=context
    )
    projects = "continuity.projects"
    # The `situation` family does not reach an Issue ...
    assert {
        row[2:] for row in _references(runtime, on_issue, (projects, "continuity.situations"))
    } == {(None, "restricted")}
    # ... the `issue` family does, by either of its reads ...
    for issue_read in ("issues.read", "issues.list"):
        assert {row[2:] for row in _references(runtime, on_issue, (projects, issue_read))} == {
            (issue, "owned")
        }
    # ... and the `issue` family does not reach a context Situation.
    assert {row[2:] for row in _references(runtime, on_context, (projects, "issues.read"))} == {
        (None, "restricted")
    }
    assert {
        row[2:] for row in _references(runtime, on_context, (projects, "continuity.situations"))
    } == {(context, "owned")}


def _every_s4_command(program: str) -> list[Command]:
    return [
        ResolveProgramMembers(program_entity_ids=(program,)),
        ReadProgramOverview(program_entity_ids=(program,)),
        ReadCommitmentV2(commitment_id="cmt_programisolation01"),
        ListCommitmentsV2(),
        SearchCommitmentsV2(query="synthetic"),
        WaitingOnV2(),
        ReadReportManifest(report_id="rpt_programisolation01"),
    ]


@pytest.mark.parametrize(
    ("lineage", "program_reporting"),
    [(True, False), (False, True), (False, False)],
    ids=["program-switch-off", "lineage-off", "both-off"],
)
def test_switch_off_answers_unsupported_for_every_s4_capability(
    disposable_database: str, lineage: bool, program_reporting: bool
) -> None:
    off = S4Runtime(
        disposable_database, lineage_enabled=lineage, program_reporting_enabled=program_reporting
    )
    try:
        program = _program_with_member(off)
        commands = _every_s4_command(program)
        assert {command.capability.value for command in commands} == PROGRAM_REPORTING_CAPABILITIES
        for command in commands:
            # Locally and remotely with every grant: the switch decides first.
            assert _error(off, command) == ("unsupported", []), command.capability.value
            everything = grant(command.capability.value, *ROOT_READS)
            assert _error(off, command, grants=everything) == ("unsupported", [])
    finally:
        off.close()


def test_a_program_statement_timeout_answers_unavailable(runtime: S4Runtime) -> None:
    program = _program_with_member(runtime)
    locked = threading.Event()
    release = threading.Event()

    def hold_the_edges() -> None:
        # An `ACCESS EXCLUSIVE` lock is the one thing a read-only snapshot
        # read waits on; the Program engine's statement timeout cancels it.
        with runtime.engine.connect() as connection, connection.begin():
            connection.execute(
                text("LOCK TABLE knowledge.entity_relationships IN ACCESS EXCLUSIVE MODE")
            )
            locked.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold_the_edges)
    holder.start()
    try:
        assert locked.wait(timeout=30)
        started = datetime.now(UTC)
        error = runtime.refused(_resolve(program))
        waited = (datetime.now(UTC) - started).total_seconds()
    finally:
        release.set()
        holder.join(timeout=30)
    assert (error["code"], error.get("safe_details") or []) == ("unavailable", [])
    # It waited one statement budget, not forever, and returned its connection.
    assert waited >= PROGRAM_STATEMENT_TIMEOUT_MS / 1000 * 0.9
    assert waited < 15
    assert runtime.program_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    # Once the lock is gone, the same read is answered.
    assert runtime.resolve(program)["programs"][0]["members"]
    # The overview (worker M4): a metric read -- here the Constraint portfolio
    # path's statements, which are not the S4 repositories' own -- cancelled by
    # its timeout answers `unavailable` as well.
    for table in ("commitments", "constraint_project_settings"):
        assert _overview_timed_out(runtime, program, table) == ("unavailable", [])
    assert runtime.overview(program)["programs"][0]["project_ids"]


def _overview_timed_out(runtime: S4Runtime, program: str, table: str) -> tuple[str, list[str]]:
    """`programs.overview` while another connection holds `table` exclusively."""
    locked = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with runtime.engine.connect() as connection, connection.begin():
            connection.execute(text(f"LOCK TABLE knowledge.{table} IN ACCESS EXCLUSIVE MODE"))
            locked.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold)
    holder.start()
    try:
        assert locked.wait(timeout=30)
        started = datetime.now(UTC)
        error = runtime.overview_refused(program)
        waited = (datetime.now(UTC) - started).total_seconds()
    finally:
        release.set()
        holder.join(timeout=30)
    assert PROGRAM_STATEMENT_TIMEOUT_MS / 1000 * 0.9 <= waited < 15, (table, waited)
    assert runtime.program_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    return str(error["code"]), list(error.get("safe_details") or [])


# --- programs.overview (worker M4, sections 6.1, 6.2 and 7.2) ---------------------

#: The 3 metric families' reads (one each), beside the 2 root reads.
METRIC_FAMILY_READS: Final = ("commitments.read", "issues.read", "constraints.read")
#: Each metric family, the reads that make it visible, and the metrics it derives.
FAMILY_METRICS: Final = {
    "commitment": (
        ("commitments.read", "commitments.list"),
        (
            "commitment_open_accepted",
            "commitment_open_proposed",
            "commitment_closed_proposed",
            "commitment_overdue_accepted",
            "commitment_overdue_proposed",
            "commitment_unscheduled_accepted",
            "commitment_unscheduled_proposed",
        ),
    ),
    "issue": (("issues.read", "issues.list"), ("issue_outstanding",)),
    "constraint": (
        ("constraints.read", "constraints.list"),
        (
            "constraint_open",
            "constraint_overdue",
            "constraint_due_soon",
            "constraint_in_my_court",
            "constraint_draft",
        ),
    ),
}


def _overview(program: str) -> ReadProgramOverview:
    return ReadProgramOverview(program_entity_ids=(program,))


def _overview_grant_cases(runtime: S4Runtime, program: str) -> None:
    """`programs.overview` re-checks its own grant (section 6.1, R3-F13)."""
    families_only = grant(*ROOT_READS, *METRIC_FAMILY_READS)
    assert _error(runtime, _overview(program), grants=families_only) == ("unsupported", [])
    # A grant on it for a purpose it does not permit admits nothing either.
    misgranted = families_only | {(Capability.PROGRAMS_OVERVIEW, Purpose.REPORT_READ)}
    assert _error(runtime, _overview(program), grants=misgranted) == ("unsupported", [])
    # Nor does the resolver's grant.
    resolver = families_only | grant("programs.members.resolve")
    assert _error(runtime, _overview(program), grants=resolver) == ("unsupported", [])
    granted = grant("programs.overview", *ROOT_READS, *METRIC_FAMILY_READS)
    assert runtime.ok(_overview(program), grants=granted)["programs"][0]["project_ids"]


def _overview_scene(runtime: S4Runtime, *, principal_id: str = PRINCIPAL) -> dict[str, str]:
    """A Program of 2 members with every family's facts (synthetic).

    Member A: a calendar, a verified in-sync target, Constraints, Commitments,
    a native Issue link and a legacy Issue link. Member B: no calendar.
    """
    seeds = runtime.seeds
    owner = {"principal_id": principal_id}
    program = seeds.program("Overview isolation", **owner)
    first, first_entity = seeds.project("Overview isolation A", **owner)
    second, second_entity = seeds.project("Overview isolation B", **owner)
    for entity in (first_entity, second_entity):
        seeds.edge(entity, program, effective_from=T0, **owner)
    category = seeds.constraint_calendar(first, **owner)
    seeds.sync_target(first, **owner)
    seeds.constraint(first, category, due_date=date(2099, 1, 1), **owner)
    tag = "own" if principal_id == PRINCIPAL else "other"
    runtime.work_commitment(f"iso-{tag}-accepted", project_id=first, **owner)
    runtime.work_commitment(f"iso-{tag}-proposed", project_id=second, accepted=False, **owner)
    runtime.linked_issue(f"iso-{tag}", first, second, principal_id=principal_id)
    legacy = runtime.issue(f"s4-iso-{tag}-legacy", principal_id=principal_id)
    seeds.legacy_issue_link(second, legacy, **owner)
    return {"program": program, "first": first, "second": second}


def _restricted(row: dict[str, Any]) -> bool:
    return (row["value"], row["value_state"], row["reasons"]) == (None, "restricted", [])


def _every_metric(answer: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        *(row for scope in answer["programs"] for row in scope["totals"]),
        *answer["portfolio"]["totals"],
        *(row for entry in answer["per_project"] for row in entry["metrics"]),
    ]


def test_cross_principal_overviews_disclose_nothing(runtime: S4Runtime) -> None:
    own = _overview_scene(runtime)
    before = runtime.overview(own["program"])
    # The other Principal: a full copy of the scene, and a Commitment storing
    # this Principal's Project id (the global foreign key admits it, D-16).
    other = _overview_scene(runtime, principal_id=OTHER_PRINCIPAL)
    runtime.work_commitment(
        "iso-foreign-naming-own", project_id=own["first"], principal_id=OTHER_PRINCIPAL
    )
    after = runtime.overview(own["program"])
    assert after["overview_sha256"] == before["overview_sha256"]
    assert {key: value for key, value in after.items() if key != "source_cutoff_at"} == {
        key: value for key, value in before.items() if key != "source_cutoff_at"
    }
    text_of_answer = str(after)
    for foreign in other.values():
        assert foreign not in text_of_answer
    # The other Principal sees its own, and nothing of this Principal's.
    theirs = runtime.overview(other["program"], principal_id=OTHER_PRINCIPAL)
    assert theirs["portfolio"]["project_ids"] == sorted([other["first"], other["second"]])
    for mine in own.values():
        assert mine not in str(theirs)
    # Its Commitment naming this Principal's Project is in no count of either:
    # each side counts exactly its own one accepted Commitment.
    for answer, first in ((after, own["first"]), (theirs, other["first"])):
        accepted = {
            entry["project_id"]: next(
                row["value"]
                for row in entry["metrics"]
                if row["metric_id"] == "commitment_open_accepted"
            )
            for entry in answer["per_project"]
        }
        assert accepted == {first: 1, next(iter(set(accepted) - {first})): 0}
    # Each Program answers the other Principal exactly as an absent one.
    absent = _document(runtime.overview_refused(ABSENT))
    assert _document(runtime.overview_refused(other["program"])) == absent
    assert (
        _document(runtime.overview_refused(own["program"], principal_id=OTHER_PRINCIPAL)) == absent
    )


def test_an_invisible_family_is_restricted_never_counted(runtime: S4Runtime) -> None:
    scene = _overview_scene(runtime)
    local = runtime.overview(scene["program"])
    everything = grant("programs.overview", *ROOT_READS, *METRIC_FAMILY_READS)
    full = runtime.ok(_overview(scene["program"]), grants=everything)
    # Every family granted: exactly the local answer.
    assert full["overview_sha256"] == local["overview_sha256"]
    assert "restricted_evidence" not in full["qualifiers"]
    for family, (reads, metrics) in FAMILY_METRICS.items():
        others = tuple(
            read
            for name, (family_reads, _m) in FAMILY_METRICS.items()
            if name != family
            for read in family_reads[:1]
        )
        answer = runtime.ok(
            _overview(scene["program"]), grants=grant("programs.overview", *ROOT_READS, *others)
        )
        rows = _every_metric(answer)
        assert rows
        for row in rows:
            # Withheld: never a count, never a reason; the others untouched.
            assert _restricted(row) is (row["metric_id"] in metrics), (family, row)
        assert "restricted_evidence" in answer["qualifiers"], family
        assert answer["overview_sha256"] != local["overview_sha256"], family
        # Either read of the family makes it visible again.
        for read in reads:
            seen = runtime.ok(
                _overview(scene["program"]),
                grants=grant("programs.overview", *ROOT_READS, *others, read),
            )
            assert seen["overview_sha256"] == local["overview_sha256"], (family, read)


def test_an_invisible_constraint_family_hides_every_constraint_derived_field(
    runtime: S4Runtime,
) -> None:
    scene = _overview_scene(runtime)
    local = runtime.overview(scene["program"])
    first = next(entry for entry in local["per_project"] if entry["project_id"] == scene["first"])
    assert first["calendar"]["timezone_name"] == "UTC"
    assert first["constraint_source_state"] == "in_sync"
    without = grant("programs.overview", *ROOT_READS, "commitments.read", "issues.read")
    answer = runtime.ok(_overview(scene["program"]), grants=without)
    for entry in answer["per_project"]:
        assert entry["calendar"] is None
        assert entry["constraint_source_state"] is None
        assert entry["constraint_last_run_sync_states"] is None
        assert entry["constraint_sync"] is None
    for scope in (*answer["programs"], answer["portfolio"]):
        assert scope["denominator"]["projects_by_constraint_source_state"] is None
        assert scope["project_ids_by_constraint_source_state"] is None
        # The other families' denominators stay.
        assert scope["denominator"]["legacy_issue_links"] == 1
        assert scope["denominator"]["member_projects"] == 2
    for token in ("UTC", "in_sync", "calendar_unconfigured", "never_synced"):
        assert token not in str(answer), token


def test_an_invisible_issue_family_hides_the_lineage_horizon_and_legacy_links(
    runtime: S4Runtime,
) -> None:
    scene = _overview_scene(runtime)
    local = runtime.overview(scene["program"])
    assert local["lineage_known_at"] is not None
    assert local["portfolio"]["project_ids_with_legacy_issue_links"] == [scene["second"]]
    without = grant("programs.overview", *ROOT_READS, "commitments.read", "constraints.read")
    answer = runtime.ok(_overview(scene["program"]), grants=without)
    assert answer["lineage_known_at"] is None
    for entry in answer["per_project"]:
        assert entry["legacy_issue_links"] is None
        assert entry["legacy_issue_links_closed"] is None
    for scope in (*answer["programs"], answer["portfolio"]):
        assert scope["denominator"]["legacy_issue_links"] is None
        assert scope["denominator"]["legacy_issue_links_closed"] is None
        assert scope["project_ids_with_legacy_issue_links"] is None
        # The Constraint denominator stays.
        assert scope["denominator"]["projects_by_constraint_source_state"] is not None
    assert local["lineage_known_at"] not in str(answer)


# --- reports.commit and reports.manifest (worker M5, sections 6.2 and 7.4) --------

#: A remote producer's grants: the commit, the overview and its 2 root reads.
PRODUCER: Final = ("reports.commit", "programs.overview", *ROOT_READS)


def _manifest_scene(runtime: S4Runtime) -> tuple[dict[str, str], str, str]:
    """The overview scene, a cycle and one researcher: `(scene, cycle, researcher)`."""
    scene = _overview_scene(runtime)
    cycle = runtime.cycle("isolation-manifest")
    researcher = runtime.research(cycle, "isolation-manifest")
    return scene, cycle, researcher


def _commit_with(
    runtime: S4Runtime,
    cycle: str,
    researcher: str,
    key: str,
    block: dict[str, object],
    **kwargs: Any,  # noqa: ANN401
) -> str:
    """A synthesizer carrying `block`: its `report_id` (committed with `kwargs`' caller)."""
    written = runtime.commit_report(
        runtime.report(
            cycle,
            IntelligenceStage.SYNTHESIZER,
            key,
            dependencies=(researcher,),
            structured_content=block,
        ),
        **kwargs,
    )
    return str(written["report_id"])


def _section(runtime: S4Runtime, report_id: str) -> dict[str, Any]:
    """The stored manifest's Program section (read locally)."""
    program = json.loads(runtime.manifest(report_id)["manifest_canonical"])["program"]
    assert isinstance(program, dict)
    return program


def _manifest_state(runtime: S4Runtime, report_id: str, *reads: str) -> dict[str, Any]:
    """`reports.manifest` for a remote reader granted it and `reads`."""
    return runtime.manifest(report_id, grants=grant("reports.manifest", *reads))


def test_a_commit_outcome_reveals_nothing_beyond_the_callers_own_overview(
    runtime: S4Runtime,
) -> None:
    scene, cycle, researcher = _manifest_scene(runtime)
    program = scene["program"]
    # A remote producer missing the commitment family: its own overview ...
    without_commitments = grant(*PRODUCER, "issues.read", "constraints.read")
    own = runtime.ok(_overview(program), grants=without_commitments)
    report = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-own-view",
        runtime.program_reference(own, program),
        grants=without_commitments,
    )
    section = _section(runtime, report)
    # ... is exactly what the commit records: verified against its own view,
    # Commitment totals `restricted`, never the full (local) totals.
    assert section["verification_state"] == "verified_at_commit"
    assert section["server"] == server_state(own) | {
        "source_cutoff_at": section["server"]["source_cutoff_at"]
    }
    for row in section["server"]["totals"]:
        if row["metric_id"].startswith("commitment_"):
            assert (row["value"], row["value_state"], row["reasons"]) == (None, "restricted", [])
    assert "commitment" not in section["families_seen"]
    local = runtime.overview(program)
    assert section["server"]["overview_sha256"] != local["overview_sha256"]
    # A producer `programs.overview` does not admit -- no grant on it, or no
    # `entity` family -- records `not_attempted`, whatever the ids name: an own
    # Program, an absent id, or an Entity that is no Program.
    _project, project_entity = runtime.seeds.project("Isolation not a program")
    claim = {"overview_sha256": "a" * 64, "source_cutoff_at": own["source_cutoff_at"]}
    for index, grants in enumerate(
        (
            grant("reports.commit", *ROOT_READS, *METRIC_FAMILY_READS),
            grant(
                "reports.commit", "programs.overview", "continuity.projects", *METRIC_FAMILY_READS
            ),
        )
    ):
        sections = []
        for target in (program, ABSENT, project_entity):
            written = _commit_with(
                runtime,
                cycle,
                researcher,
                f"isolation-unadmitted-{index}-{target}",
                runtime.program_reference(claim, target),
                grants=grants,
            )
            found = _section(runtime, written)
            assert found["verification_state"] == "not_attempted"
            assert (found["server"], found["families_seen"], found["recompute_failure"]) == (
                None,
                None,
                None,
            )
            sections.append(
                {key: value for key, value in found.items() if key != "program_entity_ids"}
            )
        assert sections[0] == sections[1] == sections[2]


def test_a_manifest_program_section_needs_every_family_it_was_computed_with(
    runtime: S4Runtime,
) -> None:
    scene, cycle, researcher = _manifest_scene(runtime)
    program = scene["program"]
    report = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-families",
        runtime.program_reference(runtime.overview(program), program),
    )
    assert _section(runtime, report)["families_seen"] == [
        "commitment",
        "constraint",
        "entity",
        "issue",
        "project",
    ]
    reader = ("programs.overview", *ROOT_READS)
    full = _manifest_state(runtime, report, *reader, *METRIC_FAMILY_READS)
    assert full["manifest_state"] == "recorded"
    assert full == runtime.manifest(report)
    for missing in METRIC_FAMILY_READS:
        reads = tuple(read for read in METRIC_FAMILY_READS if read != missing)
        answer = _manifest_state(runtime, report, *reader, *reads)
        assert answer["manifest_state"] == "restricted_evidence", missing
    # A producer that saw fewer families binds fewer: such a reader then sees it.
    narrow = grant(*PRODUCER, "issues.read", "constraints.read")
    own = runtime.ok(_overview(program), grants=narrow)
    narrower = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-narrow",
        runtime.program_reference(own, program),
        grants=narrow,
    )
    answer = _manifest_state(runtime, narrower, *reader, "issues.read", "constraints.read")
    assert answer["manifest_state"] == "recorded"


def test_a_manifest_program_section_needs_the_program_grant(runtime: S4Runtime) -> None:
    scene, cycle, researcher = _manifest_scene(runtime)
    program = scene["program"]
    report = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-grant",
        runtime.program_reference(runtime.overview(program), program),
    )
    families = (*ROOT_READS, *METRIC_FAMILY_READS)
    # Every family, but no `programs.overview` grant: withheld.
    assert _manifest_state(runtime, report, *families)["manifest_state"] == "restricted_evidence"
    # A grant on it for a purpose it does not permit admits nothing.
    misgranted = grant("reports.manifest", *families) | {
        (Capability.PROGRAMS_OVERVIEW, Purpose.REPORT_READ)
    }
    assert runtime.manifest(report, grants=misgranted)["manifest_state"] == "restricted_evidence"
    # Nor does the resolver's grant.
    resolver = _manifest_state(runtime, report, "programs.members.resolve", *families)
    assert resolver["manifest_state"] == "restricted_evidence"
    granted = _manifest_state(runtime, report, "programs.overview", *families)
    assert granted["manifest_state"] == "recorded"


def test_a_failed_recompute_manifest_needs_the_program_grant_and_entity_family(
    runtime: S4Runtime,
) -> None:
    scene, cycle, researcher = _manifest_scene(runtime)
    overview = runtime.overview(scene["program"])
    failed = _commit_with(
        runtime, cycle, researcher, "isolation-failed", runtime.program_reference(overview, ABSENT)
    )
    section = _section(runtime, failed)
    assert (section["verification_state"], section["recompute_failure"], section["server"]) == (
        "recompute_failed",
        "program_not_found",
        None,
    )
    # The failure token would tell whether the id exists and is a Program.
    for reads in (
        (*ROOT_READS, *METRIC_FAMILY_READS),
        ("programs.overview", "continuity.projects", *METRIC_FAMILY_READS),
        ("programs.overview", "entities.get", *METRIC_FAMILY_READS),
    ):
        assert _manifest_state(runtime, failed, *reads)["manifest_state"] == "restricted_evidence"
    released = _manifest_state(runtime, failed, "programs.overview", *ROOT_READS)
    assert released["manifest_state"] == "recorded"
    # A `not_attempted` manifest carries only the producer's claim: ungated.
    unattempted = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-unattempted",
        runtime.program_reference(overview, scene["program"]),
        grants=grant("reports.commit", *ROOT_READS),
    )
    assert _section(runtime, unattempted)["verification_state"] == "not_attempted"
    assert _manifest_state(runtime, unattempted)["manifest_state"] == "recorded"
    # So is a manifest with no Program section at all.
    assert _section_or_none(runtime, researcher) is None
    assert _manifest_state(runtime, researcher)["manifest_state"] == "recorded"


def _section_or_none(runtime: S4Runtime, report_id: str) -> dict[str, Any] | None:
    program = json.loads(runtime.manifest(report_id)["manifest_canonical"])["program"]
    return program if isinstance(program, dict) else None


def test_a_restricted_manifest_returns_no_digest(runtime: S4Runtime) -> None:
    scene, cycle, researcher = _manifest_scene(runtime)
    program = scene["program"]
    report = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-digest",
        runtime.program_reference(runtime.overview(program), program),
    )
    stored = runtime.stored_manifest(report)
    assert stored is not None
    answer = _manifest_state(runtime, report, *ROOT_READS)
    assert answer == {
        "report_id": report,
        "manifest_state": "restricted_evidence",
        "manifest_schema_version": 1,
        "manifest_sha256": None,
        "manifest_canonical": None,
    }
    # No digest of the withheld text, of any kind, is anywhere in the answer.
    rendered = json.dumps(answer)
    for digest in (
        stored["manifest_sha256"],
        stored["structured_content_sha256"],
        stored["program_overview_sha256"],
    ):
        assert digest not in rendered
    assert re.search(r"[0-9a-f]{64}", rendered) is None


def test_families_seen_names_only_the_overview_families(runtime: S4Runtime) -> None:
    scene, cycle, researcher = _manifest_scene(runtime)
    program = scene["program"]
    local = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-seen-local",
        runtime.program_reference(runtime.overview(program), program),
    )
    every = ["commitment", "constraint", "entity", "issue", "project"]
    assert _section(runtime, local)["families_seen"] == every
    # A remote producer that also sees context Situations: still never `situation`.
    grants = grant(*PRODUCER, *METRIC_FAMILY_READS, "continuity.situations")
    own = runtime.ok(_overview(program), grants=grants)
    remote = _commit_with(
        runtime,
        cycle,
        researcher,
        "isolation-seen-remote",
        runtime.program_reference(own, program),
        grants=grants,
    )
    assert _section(runtime, remote)["families_seen"] == every
