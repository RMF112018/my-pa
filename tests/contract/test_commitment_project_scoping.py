"""AT-015 (S4): the `commitments.v2.*` reads expose and filter by Project, owned only.

Record lineage S4 contract sections 6.2, 7.3, 8 and 12 (D-03, D-16, D-22),
against PostgreSQL through `ApplicationService.invoke` with the S4 switch on
(worker M3):

* each v2 read answers its v1 sibling's top-level keys, its Commitment objects
  carrying every v1 key plus `project_id`, `project_reference`,
  `situation_id`, `situation_reference`, `acceptance_verification` (and a
  list entry also `evidence_state`);
* `project_ids` keeps the rows whose stored Project is in the set, inside the
  v1 order and keyset; an id that is not a Project of this Principal answers
  exactly as an absent one;
* a stored identifier of another Principal's record is never echoed
  (`not_owned`); native acceptance is `unverified_review_reference`, never
  proven, and a closed proposal is never accepted;
* the Commitments of a Program are exactly those of its resolved member
  Projects: an unrelated Project's never enter, and another Principal's
  Commitment storing this Principal's Project id never does;
* a v2 page issues a constant number of statements whatever its size.

The overview counts of AT-015 (worker M4): `programs.overview` of the
Program counts per Project, per Program and per portfolio exactly the
Commitments whose own `project_id` is a resolved member of this Principal --
never the unrelated Project's, never a closed proposal as accepted, never
another Principal's Commitment storing this Principal's Project id. Every
identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

import pytest
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL
from tests.database.lineage_s3_harness import statements
from tests.database.lineage_s4_harness import T0, S4Runtime

from my_pa.application.commands import (
    Command,
    ListCommitments,
    ListCommitmentsV2,
    ReadCommitment,
    ReadCommitmentV2,
    SearchCommitments,
    SearchCommitmentsV2,
    WaitingOn,
    WaitingOnV2,
)
from my_pa.contracts.v1.commitments import CommitmentListEntry, CommitmentView, WaitingOnEntry
from my_pa.domain.situation.continuity import CommitmentDirection, CommitmentState

pytestmark = pytest.mark.database

#: The 5 keys every v2 Commitment object adds (section 7.3).
REFERENCE_KEYS: Final = frozenset(
    {
        "project_id",
        "project_reference",
        "situation_id",
        "situation_reference",
        "acceptance_verification",
    }
)
#: A well-formed Project id no row carries.
ABSENT_PROJECT: Final = "prj_scopingabsent0001"
#: The word every scene Commitment summary carries, for `search`.
WORD: Final = "scoping"


@dataclass(frozen=True, slots=True)
class Scene:
    """The AT-015 fixture: one Program of 3 bound Projects, an unrelated 4th, 2 Principals."""

    program: str
    b1: str
    b2: str
    b3: str
    unrelated: str
    issue: str
    context: str
    b1_open_accepted: str
    b1_open_proposed: str
    b2_closed_proposed: str
    b2_open_accepted: str
    b2_follow_up: str
    b3_open_accepted: str
    unrelated_open_accepted: str
    unscoped: str
    foreign_references: str
    foreign_project: str
    foreign_situation: str
    foreign_naming_b1: str


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _scene(runtime: S4Runtime) -> Scene:
    seeds = runtime.seeds
    program = seeds.program("Scoping Program")
    b1, b1_entity = seeds.project("Scoping B1")
    b2, b2_entity = seeds.project("Scoping B2")
    b3, b3_entity = seeds.project("Scoping B3")
    # The 4th Project carries B1's very name and no edge: never a member.
    unrelated, _unrelated_entity = seeds.project("Scoping B1")
    for entity in (b1_entity, b2_entity, b3_entity):
        seeds.edge(entity, program, effective_from=T0)
    issue = runtime.issue("scoping-issue")
    context = runtime.context_situation("scoping-context")
    # The other Principal: its own Project and Situation, and a Commitment that
    # stores *this* Principal's B1 and context Situation (the global foreign
    # keys admit it, D-16).
    foreign_project, _foreign_entity = seeds.project(
        "Scoping foreign", principal_id=OTHER_PRINCIPAL
    )
    foreign_situation = runtime.context_situation("scoping-foreign", principal_id=OTHER_PRINCIPAL)
    foreign_naming_b1 = runtime.work_commitment(
        "foreign-b1",
        project_id=b1,
        situation_id=context,
        summary=f"{WORD} foreign naming b1",
        principal_id=OTHER_PRINCIPAL,
    )

    def commitment(key: str, **kwargs: Any) -> str:  # noqa: ANN401
        return runtime.work_commitment(key, summary=f"{WORD} {key}", **kwargs)

    b1_open_accepted = commitment("b1-open-accepted", project_id=b1)
    # It names one of this Principal's Issues (only SQL can store one).
    runtime.store_situation(b1_open_accepted, issue)
    b1_open_proposed = commitment("b1-open-proposed", project_id=b1, accepted=False)
    b2_closed_proposed = commitment("b2-closed-proposed", project_id=b2, accepted=False)
    runtime.close_work_commitment(b2_closed_proposed, "b2-closed-proposed")
    b2_open_accepted = commitment("b2-open-accepted", project_id=b2, situation_id=context)
    b2_follow_up = runtime.follow_up(b2_open_accepted, "b2-open-accepted")
    b3_open_accepted = commitment(
        "b3-open-accepted", project_id=b3, direction=CommitmentDirection.OWED_BY_PRINCIPAL
    )
    unrelated_open_accepted = commitment("unrelated-open-accepted", project_id=unrelated)
    unscoped = commitment("unscoped")
    foreign_references = commitment(
        "foreign-references", project_id=foreign_project, situation_id=foreign_situation
    )
    return Scene(
        program=program,
        b1=b1,
        b2=b2,
        b3=b3,
        unrelated=unrelated,
        issue=issue,
        context=context,
        b1_open_accepted=b1_open_accepted,
        b1_open_proposed=b1_open_proposed,
        b2_closed_proposed=b2_closed_proposed,
        b2_open_accepted=b2_open_accepted,
        b2_follow_up=b2_follow_up,
        b3_open_accepted=b3_open_accepted,
        unrelated_open_accepted=unrelated_open_accepted,
        unscoped=unscoped,
        foreign_references=foreign_references,
        foreign_project=foreign_project,
        foreign_situation=foreign_situation,
        foreign_naming_b1=foreign_naming_b1,
    )


def _ids(answer: dict[str, Any], key: str = "commitments") -> list[str]:
    return [str(item["commitment_id"]) for item in answer[key]]


def _document(error: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in error.items() if key != "correlation_id"}


def _v1_keys(view: type) -> frozenset[str]:
    return frozenset(view.__dataclass_fields__) | {"counterparty"}


def _counts(answer: dict[str, Any], metric_id: str) -> dict[str, Any]:
    """`metric_id` per Project, per Program and per portfolio of one overview."""

    def value(rows: list[dict[str, Any]]) -> Any:  # noqa: ANN401
        (row,) = [row for row in rows if row["metric_id"] == metric_id]
        return row["value"]

    return {
        "per_project": {
            entry["project_id"]: value(entry["metrics"]) for entry in answer["per_project"]
        },
        "program": value(answer["programs"][0]["totals"]),
        "portfolio": value(answer["portfolio"]["totals"]),
    }


def test_v2_reads_expose_project_and_situation(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    read_v1 = runtime.ok(ReadCommitment(commitment_id=scene.b1_open_accepted))
    read_v2 = runtime.ok(ReadCommitmentV2(commitment_id=scene.b1_open_accepted))
    # The v1 top-level keys, the v1 Commitment keys plus exactly the 5.
    assert set(read_v2) == set(read_v1)
    commitment = read_v2["commitment"]
    assert set(commitment) == _v1_keys(CommitmentView) | REFERENCE_KEYS
    assert {key: commitment[key] for key in read_v1["commitment"]} == read_v1["commitment"]
    assert (commitment["project_id"], commitment["project_reference"]) == (scene.b1, "owned")
    assert (commitment["situation_id"], commitment["situation_reference"]) == (
        scene.issue,
        "owned",
    )
    context = runtime.ok(ReadCommitmentV2(commitment_id=scene.b2_open_accepted))
    assert (
        context["commitment"]["situation_id"],
        context["commitment"]["situation_reference"],
    ) == (
        scene.context,
        "owned",
    )
    assert context["follow_up_task"]["task_id"] == scene.b2_follow_up
    # The list and search entries: the v1 entry keys, `evidence_state` and the 5.
    for v1, v2 in (
        (ListCommitments(), ListCommitmentsV2()),
        (SearchCommitments(query=WORD), SearchCommitmentsV2(query=WORD)),
    ):
        old = runtime.ok(v1)
        new = runtime.ok(v2)
        assert set(new) == set(old)
        assert _ids(new) == _ids(old)
        for entry, before in zip(new["commitments"], old["commitments"], strict=True):
            assert set(entry) == _v1_keys(CommitmentListEntry) | REFERENCE_KEYS | {"evidence_state"}
            assert {key: entry[key] for key in before} == before
        by_id = {entry["commitment_id"]: entry for entry in new["commitments"]}
        assert by_id[scene.b1_open_accepted]["project_id"] == scene.b1
        assert by_id[scene.b1_open_proposed]["evidence_state"] == "proposed"
        assert by_id[scene.unscoped]["project_reference"] == "none"
        assert by_id[scene.unscoped]["situation_reference"] == "none"
    # `waiting_on`: the v1 entry keys and the 5, the follow-up Task kept.
    old_waiting = runtime.ok(WaitingOn())
    new_waiting = runtime.ok(WaitingOnV2())
    assert set(new_waiting) == set(old_waiting) == {"waiting_on"}
    assert _ids(new_waiting, "waiting_on") == _ids(old_waiting, "waiting_on")
    for entry, before in zip(new_waiting["waiting_on"], old_waiting["waiting_on"], strict=True):
        assert set(entry) == _v1_keys(WaitingOnEntry) | REFERENCE_KEYS
        assert {key: entry[key] for key in before} == before
    waiting = {entry["commitment_id"]: entry for entry in new_waiting["waiting_on"]}
    assert waiting[scene.b2_open_accepted]["follow_up_task_id"] == scene.b2_follow_up
    assert waiting[scene.b2_open_accepted]["project_id"] == scene.b2


def test_v2_list_search_and_waiting_on_filter_by_project_ids(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    b1 = (scene.b1,)
    listed = runtime.ok(ListCommitmentsV2(project_ids=b1))
    assert set(_ids(listed)) == {scene.b1_open_accepted, scene.b1_open_proposed}
    # Inside the v1 order: the filtered page is the v1 page with the others removed.
    every = _ids(runtime.ok(ListCommitments()))
    assert _ids(listed) == [cid for cid in every if cid in set(_ids(listed))]
    both = runtime.ok(ListCommitmentsV2(project_ids=(scene.b1, scene.b2)))
    assert set(_ids(both)) == {
        scene.b1_open_accepted,
        scene.b1_open_proposed,
        scene.b2_closed_proposed,
        scene.b2_open_accepted,
    }
    assert {entry["project_id"] for entry in both["commitments"]} == {scene.b1, scene.b2}
    # The v1 filters still apply inside the Project filter.
    closed = runtime.ok(ListCommitmentsV2(project_ids=(scene.b2,), state=CommitmentState.CLOSED))
    assert _ids(closed) == [scene.b2_closed_proposed]
    searched = runtime.ok(SearchCommitmentsV2(query="open", project_ids=b1))
    assert set(_ids(searched)) == {scene.b1_open_accepted, scene.b1_open_proposed}
    # `waiting_on` is the open, accepted, owed-to-the-Principal grain.
    waiting = runtime.ok(WaitingOnV2(project_ids=(scene.b1, scene.b2, scene.b3)))
    assert _ids(waiting, "waiting_on") == [
        cid
        for cid in _ids(runtime.ok(WaitingOn()), "waiting_on")
        if cid in {scene.b1_open_accepted, scene.b2_open_accepted}
    ]
    # The keyset continues inside the filter.
    first = runtime.invoke(ListCommitmentsV2(project_ids=b1, page_size=1))
    assert first.error is None and first.disclosure is not None
    cursor = first.disclosure.truncation.next_cursor
    assert cursor is not None
    second = runtime.ok(ListCommitmentsV2(project_ids=b1, page_size=1, after=cursor))
    assert [*_ids(first.to_canonical_dict()["result"]), *_ids(second)] == _ids(listed)
    # A Project with no Commitment is a verified empty page, not a refusal.
    empty, _entity = runtime.seeds.project("Scoping empty")
    assert _ids(runtime.ok(ListCommitmentsV2(project_ids=(empty,)))) == []


def test_a_foreign_project_filter_answers_like_an_absent_one(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    for build in (
        lambda ids: ListCommitmentsV2(project_ids=ids),
        lambda ids: SearchCommitmentsV2(query=WORD, project_ids=ids),
        lambda ids: WaitingOnV2(project_ids=ids),
    ):
        absent = _document(runtime.refused(build((ABSENT_PROJECT,))))
        assert (absent["code"], absent["safe_details"]) == ("not_found", ["project_ids"])
        # The other Principal's Project, alone or beside an own one, is never
        # dropped silently: the whole request answers as for an absent id.
        assert _document(runtime.refused(build((scene.foreign_project,)))) == absent
        assert _document(runtime.refused(build((scene.b1, scene.foreign_project)))) == absent
        # And its owner may filter by it.
        assert runtime.ok(build((scene.foreign_project,)), principal_id=OTHER_PRINCIPAL)


def test_a_foreign_project_reference_is_never_shown(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    read = runtime.ok(ReadCommitmentV2(commitment_id=scene.foreign_references))
    commitment = read["commitment"]
    assert (commitment["project_id"], commitment["project_reference"]) == (None, "not_owned")
    assert (commitment["situation_id"], commitment["situation_reference"]) == (None, "not_owned")
    listed = runtime.ok(ListCommitmentsV2())
    searched = runtime.ok(SearchCommitmentsV2(query=WORD))
    waiting = runtime.ok(WaitingOnV2())
    for answer in (read, listed, searched, waiting):
        text = str(answer)
        assert scene.foreign_project not in text
        assert scene.foreign_situation not in text
    entry = {item["commitment_id"]: item for item in listed["commitments"]}[
        scene.foreign_references
    ]
    assert (entry["project_id"], entry["project_reference"]) == (None, "not_owned")
    # The other Principal's own Commitment that stores *this* Principal's ids:
    # to its owner those ids are foreign, so they are not echoed either.
    theirs = runtime.ok(
        ReadCommitmentV2(commitment_id=scene.foreign_naming_b1), principal_id=OTHER_PRINCIPAL
    )["commitment"]
    assert (theirs["project_id"], theirs["project_reference"]) == (None, "not_owned")
    assert (theirs["situation_id"], theirs["situation_reference"]) == (None, "not_owned")
    # The v1 read of the same row is unchanged: it never carried the field.
    assert (
        "project_id"
        not in runtime.ok(ReadCommitment(commitment_id=scene.foreign_references))["commitment"]
    )


def test_v2_marks_native_acceptance_unverified(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    listed = {
        entry["commitment_id"]: entry for entry in runtime.ok(ListCommitmentsV2())["commitments"]
    }
    for accepted in (scene.b1_open_accepted, scene.b2_open_accepted, scene.b3_open_accepted):
        assert listed[accepted]["evidence_state"] == "accepted"
        assert listed[accepted]["acceptance_verification"] == "unverified_review_reference"
        read = runtime.ok(ReadCommitmentV2(commitment_id=accepted))["commitment"]
        assert read["acceptance_verification"] == "unverified_review_reference"
    for proposed in (scene.b1_open_proposed, scene.b2_closed_proposed):
        assert listed[proposed]["evidence_state"] == "proposed"
        assert listed[proposed]["acceptance_verification"] == "not_accepted"
    for entry in runtime.ok(WaitingOnV2())["waiting_on"]:
        assert entry["acceptance_verification"] == "unverified_review_reference"


def test_a_closed_proposed_commitment_is_never_counted_as_accepted(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    read = runtime.ok(ReadCommitmentV2(commitment_id=scene.b2_closed_proposed))["commitment"]
    assert (read["state"], read["evidence_state"]) == ("closed", "proposed")
    assert read["acceptance_verification"] == "not_accepted"
    # The accepted grain (`waiting_on`: open, accepted) of B2 holds the
    # accepted Commitment only, never the closed proposal.
    waiting = runtime.ok(WaitingOnV2(project_ids=(scene.b2,)))
    assert _ids(waiting, "waiting_on") == [scene.b2_open_accepted]
    accepted = [
        entry["commitment_id"]
        for entry in runtime.ok(ListCommitmentsV2(project_ids=(scene.b2,)))["commitments"]
        if entry["acceptance_verification"] != "not_accepted"
    ]
    assert accepted == [scene.b2_open_accepted]
    # The overview's accepted grain of B2 is its one open accepted Commitment;
    # the closed proposal is counted only as what it is.
    answer = runtime.overview(scene.program)
    assert _counts(answer, "commitment_open_accepted")["per_project"][scene.b2] == 1
    assert _counts(answer, "commitment_unscheduled_accepted")["per_project"][scene.b2] == 1
    assert _counts(answer, "commitment_open_proposed")["per_project"][scene.b2] == 0
    closed = _counts(answer, "commitment_closed_proposed")
    assert (closed["per_project"][scene.b2], closed["program"], closed["portfolio"]) == (1, 1, 1)


def test_an_unrelated_project_never_enters_a_program_count(runtime: S4Runtime) -> None:
    scene = _scene(runtime)
    members = [
        member["project_id"] for member in runtime.resolve(scene.program)["programs"][0]["members"]
    ]
    assert sorted(members) == sorted([scene.b1, scene.b2, scene.b3])
    assert scene.unrelated not in members
    scoped = runtime.ok(ListCommitmentsV2(project_ids=tuple(members)))
    assert set(_ids(scoped)) == {
        scene.b1_open_accepted,
        scene.b1_open_proposed,
        scene.b2_closed_proposed,
        scene.b2_open_accepted,
        scene.b3_open_accepted,
    }
    for answer in (
        scoped,
        runtime.ok(SearchCommitmentsV2(query=WORD, project_ids=tuple(members))),
    ):
        assert scene.unrelated_open_accepted not in _ids(answer)
        assert scene.unrelated not in {entry["project_id"] for entry in answer["commitments"]}
    waiting = runtime.ok(WaitingOnV2(project_ids=tuple(members)))
    assert scene.unrelated_open_accepted not in _ids(waiting, "waiting_on")
    # The unrelated Project's own filter does find it: it is excluded, not lost.
    assert _ids(runtime.ok(ListCommitmentsV2(project_ids=(scene.unrelated,)))) == [
        scene.unrelated_open_accepted
    ]
    # The overview: per Project, per Program and per portfolio, only the members'.
    answer = runtime.overview(scene.program)
    assert answer["portfolio"]["project_ids"] == sorted(members)
    assert scene.unrelated not in str(answer)
    accepted = _counts(answer, "commitment_open_accepted")
    assert accepted["per_project"] == {scene.b1: 1, scene.b2: 1, scene.b3: 1}
    assert sum(accepted["per_project"].values()) == 3
    proposed = _counts(answer, "commitment_open_proposed")
    assert proposed["per_project"] == {scene.b1: 1, scene.b2: 0, scene.b3: 0}
    assert (proposed["program"], proposed["portfolio"]) == (1, 1)


def test_a_foreign_principals_commitment_naming_this_project_is_never_counted(
    runtime: S4Runtime,
) -> None:
    scene = _scene(runtime)
    own_b1 = {scene.b1_open_accepted, scene.b1_open_proposed}
    for command in (
        ListCommitmentsV2(project_ids=(scene.b1,)),
        SearchCommitmentsV2(query=WORD, project_ids=(scene.b1,)),
        ListCommitmentsV2(),
    ):
        answer = runtime.ok(command)
        assert scene.foreign_naming_b1 not in _ids(answer)
    assert set(_ids(runtime.ok(ListCommitmentsV2(project_ids=(scene.b1,))))) == own_b1
    waiting = runtime.ok(WaitingOnV2(project_ids=(scene.b1,)))
    assert _ids(waiting, "waiting_on") == [scene.b1_open_accepted]
    # Nor through the Program: the resolved B1 of this Principal is the filter.
    members = tuple(
        member["project_id"] for member in runtime.resolve(scene.program)["programs"][0]["members"]
    )
    assert scene.foreign_naming_b1 not in _ids(runtime.ok(ListCommitmentsV2(project_ids=members)))
    # The row exists, for its own Principal only.
    assert runtime.ok(
        ReadCommitmentV2(commitment_id=scene.foreign_naming_b1), principal_id=OTHER_PRINCIPAL
    )
    error = runtime.refused(ReadCommitmentV2(commitment_id=scene.foreign_naming_b1))
    assert (error["code"], error["safe_details"]) == ("not_found", ["commitment_id"])
    # Nor in any overview count: B1's per-Project figures are its own 2
    # Commitments, and the Program and portfolio totals hold no third.
    answer = runtime.overview(scene.program)
    assert _counts(answer, "commitment_open_accepted")["per_project"][scene.b1] == 1
    assert _counts(answer, "commitment_unscheduled_accepted")["per_project"][scene.b1] == 1
    assert _counts(answer, "commitment_open_proposed")["per_project"][scene.b1] == 1
    for metric_id in ("commitment_open_proposed", "commitment_unscheduled_proposed"):
        counted = _counts(answer, metric_id)
        assert (counted["program"], counted["portfolio"]) == (1, 1), metric_id
    assert scene.foreign_naming_b1 not in str(answer)


def _page_scene(runtime: S4Runtime, count: int) -> tuple[str, str]:
    """`count` waiting-on Commitments of one Project, each with its own counterparty,
    a follow-up Task, an Issue reference and the Project reference."""
    project, _entity = runtime.seeds.project("Scoping paged")
    issue = runtime.issue("scoping-paged")
    for index in range(count):
        commitment = runtime.work_commitment(
            f"paged-{index}", project_id=project, summary=f"{WORD} paged {index}"
        )
        runtime.store_situation(commitment, issue)
        runtime.follow_up(commitment, f"paged-{index}")
    return project, issue


def _statement_count(runtime: S4Runtime, command: Command) -> int:
    with statements(runtime.engine) as seen:
        envelope = runtime.invoke(command)
    assert envelope.error is None, envelope.error
    return len(seen)


def test_v2_pages_issue_a_constant_number_of_statements(runtime: S4Runtime) -> None:
    project, _issue = _page_scene(runtime, 12)
    ids = (project,)
    for build, key in (
        (lambda size: ListCommitmentsV2(project_ids=ids, page_size=size), "commitments"),
        (
            lambda size: SearchCommitmentsV2(query=WORD, project_ids=ids, page_size=size),
            "commitments",
        ),
        (lambda size: WaitingOnV2(project_ids=ids, page_size=size), "waiting_on"),
    ):
        assert len(runtime.ok(build(2))[key]) == 2
        assert len(runtime.ok(build(12))[key]) == 12
        small = _statement_count(runtime, build(2))
        large = _statement_count(runtime, build(12))
        assert small == large, (build(2).capability.value, small, large)
    # The control: the v1 sibling reads a counterparty (and a follow-up) per
    # row, so the recorder does see a page grow when its statements do.
    assert _statement_count(runtime, WaitingOn(page_size=12)) > _statement_count(
        runtime, WaitingOn(page_size=2)
    )
