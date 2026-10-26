"""AT-001 + AT-013 (timeline): `issues.timeline` (S3 contract sections 3.2, 3.4, 7.3 and 12).

Against PostgreSQL through `ApplicationService.invoke` (worker L4):

* the S2 fourteen-stage workflow's timeline lists the stage writes in stage
  order, ordered `(at, plane, kind, entry_id)`;
* a native entry carries no field value: a renamed Task is a partial event,
  never its title; a Constraint event carries the ball-in-court of its stored
  revision snapshot, exactly as `constraints.read` renders it, so a past
  ball-in-court is read with `valid_at`;
* an as-of timeline omits the native plane and says `partial_native_history`;
  a current one shows a native change made after the lineage horizon at a
  later `valid_at` (the native plane's own valid cut, R3-F02);
* a Project link entry names no Project; no entry names another Issue's
  record; association entries follow section 3.2's one in-context definition;
* pages under one cursor reconstruct the whole timeline.

Every identity and every body is synthetic.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from my_pa.application.commands import ReadConstraint, UpdateConstraint, UpdateTask
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.task.lifecycle import TaskLifecycleState
from tests.database.lineage_record_harness import NOTE_BODY, note_anchor, originated_from
from tests.database.lineage_s2_harness import GATEWAY, assertion
from tests.database.lineage_s3_harness import corroborates
from tests.database.lineage_s3_read_harness import S3ReadRuntime, horizon, instant
from tests.integration.test_issue_lineage_14step import Workflow

pytestmark = pytest.mark.database

#: Section 7.3: the kind order.
_KIND_RANK: Final = {
    kind: rank
    for rank, kind in enumerate(
        (
            "issue_revision",
            "project_link",
            "membership",
            "association",
            "handoff",
            "handoff_correction",
            "native_event",
        )
    )
}
#: Section 7.3: every key an entry carries, whatever its kind.
_ENTRY_KEYS: Final = frozenset(
    {
        "entry_id",
        "kind",
        "plane",
        "at",
        "recorded_at",
        "subject",
        "action",
        "historical_fields_partial",
        "issue_version",
        "state",
        "title",
        "closed_at",
        "outcome",
        "project_id",
        "membership_revision_no",
        "link_state",
        "link_id",
        "revision_no",
        "relation_type",
        "member_role",
        "lifecycle_state",
        "from",
        "to",
        "handoff_id",
        "commitment_id",
        "sequence_no",
        "from_holder",
        "to_holder",
        "voided",
        "correction_id",
        "correction_action",
        "corrected_effective_at",
        "native",
        "recorded_fields",
        # S3.1 lockstep (S3.1 contract sections 7.6 and 10.1): the provenance labels.
        "acceptance_basis",
        "user_directed_claim",
        "asserting_client_id",
    }
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _entries(runtime: S3ReadRuntime, issue_id: str, **kwargs: Any) -> list[dict[str, Any]]:  # noqa: ANN401
    """Every entry of the timeline, following the cursor to the end."""
    return [
        entry for page in runtime.timeline_pages(issue_id, **kwargs) for entry in page["entries"]
    ]


def _key(entry: dict[str, Any]) -> tuple[str, int, int, str]:
    plane = 0 if entry["plane"] == "lineage" else 1
    return (entry["at"], plane, _KIND_RANK[entry["kind"]], entry["entry_id"])


def _native(entries: list[dict[str, Any]], record_id: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in entries
        if entry["kind"] == "native_event" and entry["native"]["record_id"] == record_id
    ]


def _now() -> str:
    return instant(datetime.now(UTC))


def _bic(runtime: S3ReadRuntime, constraint_id: str) -> tuple[str, Any]:
    """`constraints.read`'s status and `bic`, as the timeline must render them."""
    view = runtime.ok(ReadConstraint(constraint_id=constraint_id))["constraint"]
    return str(view["status"]), view["bic"]


def _move_bic(runtime: S3ReadRuntime, constraint_id: str, label: str, key: str) -> None:
    """`constraints.update` of the ball-in-court to one unresolved party named `label`."""
    runtime.ok(
        UpdateConstraint(
            constraint_id=constraint_id,
            expected_version=runtime.constraint_version(constraint_id),
            bic=(PartyRef(kind=PartyKind.UNRESOLVED, label=label),),
            idempotency_key=f"tl-bic-{key}",
        )
    )


def _constraint_member(runtime: S3ReadRuntime, key: str) -> tuple[str, str]:
    """An Issue linked to a Project, with one published Constraint of it as a member."""
    issue = runtime.issue(key)
    project = runtime.project_with_constraints(key)
    runtime.link_project(issue, project, key)
    constraint = runtime.constraint(project, key)
    runtime.member(issue, "constraint", constraint, key, "constraint")
    return issue, constraint


# ---- the fourteen stages ------------------------------------------------------------------


def test_the_timeline_orders_the_fourteen_stages(runtime: S3ReadRuntime) -> None:
    stage_of: dict[str, int] = {}

    def record(flow: Workflow) -> None:
        for entry in _entries(runtime, flow.ids["I"]):
            stage_of.setdefault(entry["entry_id"], flow.stage)

    flow = Workflow(runtime)
    for number in range(1, 15):
        flow.after[number] = record
    flow.run(14)
    entries = _entries(runtime, flow.ids["I"])
    assert [_key(entry) for entry in entries] == sorted(_key(entry) for entry in entries)
    assert all(set(entry) == _ENTRY_KEYS for entry in entries)
    assert {entry["entry_id"] for entry in entries} == set(stage_of)
    # Every entry stamped by its recording lists in stage order. A handoff is at
    # its business time (stage 4 recorded it effective just after C1's creation).
    stamped = [stage_of[entry["entry_id"]] for entry in entries if entry["kind"] != "handoff"]
    assert stamped == sorted(stamped)
    assert {stage_of[entry["entry_id"]] for entry in entries} == set(range(1, 15))
    kinds = {entry["kind"] for entry in entries}
    assert kinds >= {
        "issue_revision",
        "project_link",
        "membership",
        "association",
        "handoff",
        "native_event",
    }
    revisions = [entry for entry in entries if entry["kind"] == "issue_revision"]
    assert [(entry["issue_version"], entry["state"]) for entry in revisions] == [
        (1, "open"),
        (2, "closed"),
    ]
    (handoff,) = [entry for entry in entries if entry["kind"] == "handoff"]
    assert stage_of[handoff["entry_id"]] == 4
    assert (handoff["commitment_id"], handoff["voided"], handoff["sequence_no"]) == (
        flow.ids["C1"],
        False,
        1,
    )
    assert handoff["at"] < handoff["recorded_at"]
    # 9 memberships and 12 associations, each with every revision it has.
    memberships = {entry["link_id"] for entry in entries if entry["kind"] == "membership"}
    associations = {entry["link_id"] for entry in entries if entry["kind"] == "association"}
    assert len(memberships) == 9
    assert len(associations) == 12
    # The current timeline is complete; nothing of Issue J is in it.
    page = runtime.timeline(flow.ids["I"], page_size=100)
    assert (page["complete_state"], page["qualifiers"]) == ("complete", ["complete"])
    rendered = json.dumps(entries)
    for name in ("J", "MJ", "NJ", "TJ", "MB", "NB"):
        assert flow.ids[name] not in rendered, name


# ---- native entries carry no values ---------------------------------------------------------


def test_a_renamed_task_is_a_partial_event_never_its_title(runtime: S3ReadRuntime) -> None:
    issue = runtime.issue("tl-rename")
    task = runtime.task("tl-rename")
    runtime.member(issue, "task", task, "tl-rename", "work")
    runtime.ok(
        UpdateTask(
            task_id=task,
            expected_version=runtime.task_version(task),
            idempotency_key="tl-rename-title",
            title="Renamed synthetic title Zeta",
        )
    )
    entries = _entries(runtime, issue)
    native = _native(entries, task)
    (renamed,) = [
        entry
        for entry in native
        if entry["native"]["event_kind"] == "updated"
        and "title" in entry["native"]["changed_fields"]
    ]
    assert renamed["subject"] == {"family": "task", "record_id": task}
    assert renamed["action"] == renamed["native"]["event_kind"]
    for entry in native:
        assert entry["historical_fields_partial"] is True
        assert entry["recorded_fields"] is None
        assert entry["title"] is None
    rendered = json.dumps(entries)
    assert "Renamed synthetic title Zeta" not in rendered
    assert "Synthetic task tl-rename" not in rendered


def test_a_constraint_event_carries_its_recorded_ball_in_court(runtime: S3ReadRuntime) -> None:
    issue, constraint = _constraint_member(runtime, "tl-bic")
    recorded = {runtime.constraint_version(constraint): _bic(runtime, constraint)}
    _move_bic(runtime, constraint, "Synthetic subcontractor Kappa", "kappa")
    recorded[runtime.constraint_version(constraint)] = _bic(runtime, constraint)
    native = _native(_entries(runtime, issue), constraint)
    assert {entry["native"]["record_version"] for entry in native} == set(recorded)
    for entry in native:
        state, bic = recorded[entry["native"]["record_version"]]
        assert entry["historical_fields_partial"] is False
        assert entry["recorded_fields"] == {"lifecycle_state": state, "ball_in_court": bic}
    later = max(native, key=lambda entry: entry["native"]["record_version"])
    assert later["recorded_fields"]["ball_in_court"] == [
        {
            "kind": "unresolved",
            "party_ref_id": None,
            "display_label": "Synthetic subcontractor Kappa",
            "entity_id": None,
        }
    ]


def test_past_ball_in_court_is_read_at_valid_at(runtime: S3ReadRuntime) -> None:
    issue, constraint = _constraint_member(runtime, "tl-past")
    first_state, first_bic = _bic(runtime, constraint)
    between = _now()
    time.sleep(0.01)
    _move_bic(runtime, constraint, "Synthetic subcontractor Lambda", "lambda")
    _, second_bic = _bic(runtime, constraint)
    assert second_bic != first_bic
    then = runtime.timeline(issue, valid_at=between, page_size=100)
    assert then["valid_at"] == between
    (past,) = _native(then["entries"], constraint)
    assert past["recorded_fields"] == {"lifecycle_state": first_state, "ball_in_court": first_bic}
    assert all(entry["at"] <= between for entry in then["entries"])
    now = _native(_entries(runtime, issue), constraint)
    assert now[-1]["recorded_fields"]["ball_in_court"] == second_bic


# ---- the two planes and their cuts ------------------------------------------------------------


def test_an_as_of_timeline_omits_native_events_and_says_partial(runtime: S3ReadRuntime) -> None:
    issue = runtime.issue("tl-asof")
    task = runtime.task("tl-asof")
    runtime.member(issue, "task", task, "tl-asof", "work")
    cut = horizon(runtime.engine)
    current = runtime.timeline(issue, page_size=100)
    assert _native(current["entries"], task)
    assert current["complete_state"] == "complete"
    as_of = runtime.timeline(issue, known_at=cut, page_size=100)
    assert [entry for entry in as_of["entries"] if entry["plane"] == "native"] == []
    assert (as_of["complete_state"], as_of["qualifiers"]) == (
        "partial_native_history",
        ["partial_native_history"],
    )
    assert as_of["known_at"] == cut
    # The lineage plane is the same in both.
    assert list(as_of["entries"]) == [
        entry for entry in current["entries"] if entry["plane"] == "lineage"
    ]


def test_a_native_change_after_the_horizon_is_shown_at_a_later_valid_at(
    runtime: S3ReadRuntime,
) -> None:
    issue = runtime.issue("tl-later")
    task = runtime.task("tl-later")
    runtime.member(issue, "task", task, "tl-later", "work")
    cut = horizon(runtime.engine)
    before = _now()
    time.sleep(0.01)
    runtime.transition(task, TaskLifecycleState.IN_PROGRESS, "tl-later")
    time.sleep(0.01)
    after = _now()
    # No lineage write followed: the horizon is unchanged and before the change.
    assert horizon(runtime.engine) == cut < before
    current = runtime.timeline(issue, page_size=100)
    changed = [
        entry
        for entry in _native(current["entries"], task)
        if entry["native"]["event_kind"] == "state_changed"
    ]
    assert len(changed) == 1 and changed[0]["at"] > cut
    later = runtime.timeline(issue, valid_at=after, page_size=100)
    assert (later["valid_at"], later["lineage_valid_at"], later["known_at"]) == (after, cut, cut)
    assert changed[0] in later["entries"]
    earlier = runtime.timeline(issue, valid_at=before, page_size=100)
    assert changed[0] not in earlier["entries"]
    assert _native(earlier["entries"], task)


# ---- what an entry may name -------------------------------------------------------------------


def test_a_project_link_entry_carries_no_project_name(runtime: S3ReadRuntime) -> None:
    issue = runtime.issue("tl-project")
    project = runtime.project("tl-project")
    runtime.link_project(issue, project, "tl-project")
    entries = _entries(runtime, issue)
    (link,) = [entry for entry in entries if entry["kind"] == "project_link"]
    assert (link["project_id"], link["membership_revision_no"], link["link_state"]) == (
        project,
        1,
        "active",
    )
    assert link["subject"] is None and link["title"] is None
    assert "Synthetic project tl-project" not in json.dumps(entries)


def test_a_timeline_never_names_another_issues_record(runtime: S3ReadRuntime) -> None:
    mine, theirs = runtime.issue("tl-mine"), runtime.issue("tl-theirs")
    meeting_id, note_id = runtime.note("tl-shared")
    runtime.member(mine, "meeting", meeting_id, "tl-mine-m", "discussion")
    runtime.member(theirs, "meeting", meeting_id, "tl-theirs-m", "discussion")
    my_task, their_task = runtime.task("tl-mine"), runtime.task("tl-theirs")
    runtime.member(mine, "task", my_task, "tl-mine-t", "work")
    their_membership = runtime.member(theirs, "task", their_task, "tl-theirs-t", "work")
    discussed = {}
    for issue, task, key in ((mine, my_task, "mine"), (theirs, their_task, "theirs")):
        written = runtime.ok(
            assertion(
                "discusses",
                ("meeting_note_version", note_id),
                ("task", task),
                f"tl-discusses-{key}",
                (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
                context=issue,
            ),
            surface=GATEWAY,
        )
        discussed[key] = str(written["association"]["link_id"])
    entries = _entries(runtime, mine)
    assert discussed["mine"] in {entry["link_id"] for entry in entries}
    assert _native(entries, meeting_id)
    rendered = json.dumps(entries)
    for identifier in (theirs, their_task, their_membership, discussed["theirs"]):
        assert identifier not in rendered, identifier


def test_association_entries_use_the_issue_context_definition(runtime: S3ReadRuntime) -> None:
    issue, other = runtime.issue("tl-ctx"), runtime.issue("tl-ctx-other")
    first, second, third, outside = (runtime.task(f"tl-ctx-{name}") for name in "abcd")
    for task, name in ((first, "a"), (second, "b"), (third, "c")):
        runtime.member(issue, "task", task, f"tl-ctx-{name}", "reference")
    for task, name in ((first, "a"), (third, "c")):
        runtime.member(other, "task", task, f"tl-ctx-other-{name}", "reference")
    meeting_id, note_id = runtime.note("tl-ctx-source")
    anchors = (corroborates(meeting_id, note_id),)

    def blocks(source: str, target: str, key: str, context: str | None) -> str:
        written = runtime.ok(
            assertion("blocks", ("task", source), ("task", target), key, anchors, context=context),
            surface=GATEWAY,
        )
        return str(written["association"]["link_id"])

    in_context = blocks(first, second, "tl-ctx-scoped", issue)
    inside = blocks(second, third, "tl-ctx-inside", None)
    half_outside = blocks(third, outside, "tl-ctx-half", None)
    other_context = blocks(first, third, "tl-ctx-other", other)
    # An endpoint equal to the Issue, whatever the context.
    discusses = runtime.ok(
        assertion(
            "discusses",
            ("meeting_note_version", note_id),
            ("situation", issue),
            "tl-ctx-endpoint",
            (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
        ),
        surface=GATEWAY,
    )
    endpoint = str(discusses["association"]["link_id"])
    # A null-context origin from a member to a note outside the Issue.
    origin = runtime.ok(
        originated_from(
            "task",
            first,
            "meeting_note_version",
            note_id,
            "tl-ctx-origin",
            (note_anchor(meeting_id, note_id, NOTE_BODY),),
        ),
        surface=GATEWAY,
    )
    outward = str(origin["association"]["link_id"])
    entries = _entries(runtime, issue)
    associations = {entry["link_id"] for entry in entries if entry["kind"] == "association"}
    assert associations == {in_context, inside, endpoint}
    assert not {half_outside, other_context, outward} & associations
    memberships = {
        entry["subject"]["record_id"] for entry in entries if entry["kind"] == "membership"
    }
    assert memberships == {first, second, third}


# ---- paging ------------------------------------------------------------------------------------


def test_timeline_pages_reconstruct_the_whole_timeline(runtime: S3ReadRuntime) -> None:
    issue = runtime.issue("tl-pages")
    for number in range(12):
        task = runtime.task(f"tl-pages-{number:02d}")
        runtime.member(issue, "task", task, f"tl-pages-{number:02d}", "work")
    whole = runtime.timeline(issue, page_size=100)
    assert whole["next_cursor"] is None
    assert len(whole["entries"]) == 25  # the revision, 12 memberships, 12 creations
    pages = runtime.timeline_pages(issue, page_size=10)
    assert len(pages) == -(-len(whole["entries"]) // 10)
    assert [entry for page in pages for entry in page["entries"]] == whole["entries"]
    for page in pages:
        for key in ("issue_id", "known_at", "valid_at", "lineage_valid_at", "complete_state"):
            assert page[key] == whole[key], key
    assert [page["next_cursor"] is None for page in pages] == [False] * (len(pages) - 1) + [True]
