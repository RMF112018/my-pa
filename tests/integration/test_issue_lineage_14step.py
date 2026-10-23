"""AT-001 (all 14 stages, scenarios A, B and H): the record lineage S2 workflow end to end.

S2 contract section 10 (the AT-001 stage -> call map) against PostgreSQL,
through `ApplicationService.invoke` only: every stage is the capability calls
the map names, and after every stage the reconciliation gate of package 04
section A is asserted -- the Issue graph `records.lineage` returns from I, the
native states (no cascade in either direction), the handoff ledger and the
closure readiness. Stage 14 attempted before stage 13 is refused and writes
nothing; after stage 14, `records.lineage` scoped to I from each of the 14
roots returns one graph (S2 part of the reverse-root equivalence).

The cast: Issue I linked to Project P; Meetings M1, M2, M4 in Series A and M3
in Series B, with note versions N1..N4; C1 (counterparty P1, owed to the
Principal) originated from an exact N1 passage; T1 the Principal's
`direct_principal` follow-up of the closed C1; X1 a published Constraint in P
escalated from T1; C2 and C3 (P2, P3) each delegated from T1; E0..E3 and E1
synthetic Capture versions recording resolution evidence. Issue J holds a
Series A Meeting and a Series B Meeting of its own and is never reached from
I. Acceptance (R2-F04): T1 is natively `accepted` by its origin kind; C1..C3
carry the synthetic `rdec_` in their nested `accepted_by_review_decision_id`.

Every lineage write is a stamped local-operator write. Every identity and
every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import select

from my_pa.application.commands import (
    AssertRecordAssociation,
    Command,
    CreateMeeting,
    ListIssueHandoffs,
    ReadConstraint,
    ReadIssue,
    ReadMeeting,
    ReadRecordLineage,
    ReadTask,
)
from my_pa.domain.task.lifecycle import TaskLifecycleState
from my_pa.infrastructure.persistence.tables import (
    commitments,
    issue_responsibility_events,
    issue_revision_evidence,
    issue_revisions,
    lineage_evidence_anchors,
    lineage_write_request_links,
    lineage_write_requests,
    project_constraints,
    record_link_heads,
    record_link_revision_evidence,
    record_link_revisions,
    record_links,
    situations,
    tasks,
)
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    capture_anchor,
    note,
    note_anchor,
    revise_notes,
)
from tests.database.lineage_s2_harness import (
    GATEWAY,
    REVIEW_DECISION,
    S2Runtime,
    close,
    correct,
    handoff,
    work_commitment,
    work_task,
)
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity

pytestmark = pytest.mark.database

_STARTS: Final = datetime(2026, 10, 3, 15, tzinfo=UTC)
#: M4's note: a reported resolution, in words only.
N4_BODY: Final = "Reported resolution: the façade survey is resolved and the pour can proceed."
#: The four N3 passages, one per discussed record (T1, X1, C2, C3).
N3_PASSAGES: Final = ("Decisions", "Ana will send", "façade survey", "Next: pour")
#: The three N4 passages (I, X1, T1).
N4_PASSAGES: Final = ("Reported resolution", "façade survey is resolved", "pour can proceed")
#: The tables a refused write must leave byte-identical.
_SNAPSHOT_TABLES: Final = (
    situations,
    issue_revisions,
    issue_revision_evidence,
    issue_responsibility_events,
    lineage_evidence_anchors,
    lineage_write_requests,
    lineage_write_request_links,
    record_links,
    record_link_revisions,
    record_link_revision_evidence,
    record_link_heads,
    tasks,
    commitments,
    project_constraints,
)

Ref = tuple[str, str]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S2Runtime]:
    composed = S2Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def snapshot(runtime: S2Runtime) -> dict[str, list[str]]:
    """Every lineage, Issue and native Work and Constraint row, as stored."""
    with runtime.engine.connect() as connection:
        return {
            table.name: sorted(repr(tuple(row)) for row in connection.execute(select(table)))
            for table in _SNAPSHOT_TABLES
        }


def graph(runtime: S2Runtime, root: Ref, issue_id: str) -> dict[str, Any]:
    """`records.lineage` from `root` scoped to `issue_id`, reduced to comparable sets."""
    answer = runtime.ok(
        ReadRecordLineage(origin={"family": root[0], "record_id": root[1]}, issue_id=issue_id)
    )
    assert answer["selected_issue_id"] == issue_id, root
    return {
        "nodes": {(node["family"], node["record_id"]) for node in answer["nodes"]},
        "edges": {edge["link_id"] for edge in answer["typed_edges"]},
        "relations": sorted(edge["relation_type"] for edge in answer["typed_edges"]),
        "virtual": {
            (edge["from"]["record_id"], edge["to"]["record_id"])
            for edge in answer["virtual_native_edges"]
        },
        "complete_state": answer["complete_state"],
        "typed_edges": answer["typed_edges"],
    }


def blocked(runtime: S2Runtime, issue_id: str) -> dict[str, list[str]]:
    """`issues.closure_readiness` as `{member record_id: reasons}`."""
    readiness = runtime.readiness(issue_id)
    assert readiness["ready"] is (not readiness["blockers"] and readiness["state"] != "closed")
    return {
        blocker["member"]["record_id"]: list(blocker["reasons"])
        for blocker in readiness["blockers"]
    }


class Workflow:
    """The section 10 stage -> call map, one method per stage, each asserting its gate."""

    def __init__(self, runtime: S2Runtime, *, revise_m1_after_stage_3: bool = False) -> None:
        self.rt = runtime
        self.revise_m1 = revise_m1_after_stage_3
        self.ids: dict[str, str] = {}
        self.links: dict[str, str] = {}
        self.stage = 0
        self.after: dict[int, Callable[[Workflow], None]] = {}

    # --- calls ---------------------------------------------------------------

    def lineage_write(self, command: Command) -> dict[str, Any]:
        return self.rt.ok(command, surface=GATEWAY)

    def refused(self, command: Command) -> tuple[str, list[str]]:
        error = self.rt.refused(command, surface=GATEWAY)
        return str(error["code"]), list(error.get("safe_details") or [])

    def meeting(
        self, key: str, *, series: str, body: str | None = NOTE_BODY
    ) -> tuple[str, str | None]:
        """A Meeting in Series `series` (created on first use): `(meeting_id, note_id)`."""
        series_id = self.ids.get(f"series-{series}")
        written = self.rt.ok(
            CreateMeeting(
                title=f"Synthetic meeting {key}",
                start_at=_STARTS,
                timezone_name="UTC",
                idempotency_key=f"s2-14-mtg-{key}",
                notes_markdown=body,
                series_title=None if series_id else f"Synthetic Series {series}",
                meeting_series_id=series_id,
            )
        )["meeting"]
        self.ids[f"series-{series}"] = str(written["meeting_series_id"])
        notes = written.get("notes")
        return str(written["meeting_id"]), (str(notes["note_version_id"]) if notes else None)

    def discussion(self, note_ref: Ref, body: str, passage: str) -> dict[str, object]:
        meeting_id = self.ids[note_ref[0]]
        return note_anchor(
            meeting_id, self.ids[note_ref[1]], body, role="discussion", passage=passage
        )

    def discusses(
        self, key: str, source: Ref, body: str, passage: str, target: Ref, *, context: bool = True
    ) -> str:
        """`records.associations.assert` `discusses` from note `source[1]` of `source[0]`."""
        written = self.lineage_write(
            AssertRecordAssociation(
                from_record={"family": "meeting_note_version", "record_id": self.ids[source[1]]},
                to_record={"family": target[0], "record_id": self.ids[target[1]]},
                relation_type="discusses",
                idempotency_key=f"s2-14-discusses-{key}",
                evidence_anchors=(self.discussion(source, body, passage),),
                context_issue_id=None if target[0] == "situation" else self.ids["I"],
            )
        )
        self.links[key] = str(written["association"]["link_id"])
        return self.links[key]

    def member(self, key: str, family: str, name: str, role: str) -> None:
        self.links[key] = self.rt.member(
            self.ids["I"], family, self.ids[name], f"s2-14-{key}", role
        )

    def resolution(self, name: str) -> dict[str, object]:
        """A fresh synthetic Capture version `name` and an exact `resolution` anchor on it."""
        capture_id, version_id, _ = capture(self.rt, f"s2-14-{name}")
        self.ids[name] = version_id
        return capture_anchor(capture_id, version_id, NOTE_BODY, role="resolution")

    def record_resolution(self, member: str, key: str, anchor: dict[str, object]) -> None:
        """`issues.memberships.correct` of `member`'s membership with `anchor`."""
        link = self.links[member]
        revision = self.membership(link)["revision_no"]
        self.lineage_write(correct(link, int(revision), f"14-{key}", (anchor,)))

    def membership(self, link_id: str) -> dict[str, Any]:
        read = self.rt.ok(ReadIssue(issue_id=self.ids["I"], include_members=True))
        (view,) = [view for view in read["memberships"] if view["link_id"] == link_id]
        return dict(view)

    def commitment_object(self, key: str, party: str) -> dict[str, object]:
        origin, _, _ = capture(self.rt, f"s2-14-{key}-native-origin")
        self.ids[party] = seed_counterparty_entity(self.rt.engine, PRINCIPAL)
        return {
            "counterparty_entity_id": self.ids[party],
            "direction": "owed_to_principal",
            "summary": f"Synthetic commitment {key}",
            "origin_evidence_ref": origin,
            "accepted_by_review_decision_id": REVIEW_DECISION,
        }

    # --- reads ---------------------------------------------------------------

    def ref(self, family: str, name: str) -> Ref:
        return (family, self.ids[name])

    def refs(self, *names: str) -> set[Ref]:
        return {self.ref(_FAMILY[name[0]], name) for name in names}

    def from_issue(self) -> dict[str, Any]:
        """The graph from I, with the evidence-availability dimension of each gate.

        Package 04 section A compares evidence availability at every
        intermediate gate: every anchor on every edge I's traversal returns is
        `available` (nothing in this workflow is archived or withdrawn), and
        from stage 3 on there is evidence to compare.
        """
        answer = graph(self.rt, self.ref("situation", "I"), self.ids["I"])
        seen = [
            anchor["availability"] for edge in answer["typed_edges"] for anchor in edge["evidence"]
        ]
        assert set(seen) <= {"available"}, seen
        if "c1-origin" in self.links:
            assert seen, "no evidence on I's graph after stage 3"
        return answer

    def task(self, name: str) -> dict[str, Any]:
        return dict(self.rt.ok(ReadTask(task_id=self.ids[name]))["task"])

    def issue(self) -> dict[str, Any]:
        return dict(self.rt.ok(ReadIssue(issue_id=self.ids["I"]))["issue"])

    def constraint(self, name: str) -> dict[str, Any]:
        return dict(self.rt.ok(ReadConstraint(constraint_id=self.ids[name]))["constraint"])

    def handoffs(self) -> list[dict[str, Any]]:
        page = self.rt.ok(ListIssueHandoffs(issue_id=self.ids["I"]))
        return list(page["handoffs"])

    def assert_n1_origin_unchanged(self) -> None:
        """C1's `originated_from` still names N1, revision 1, with N1's exact evidence."""
        typed = {edge["link_id"]: edge for edge in self.from_issue()["typed_edges"]}
        origin = typed[self.links["c1-origin"]]
        assert origin["to"] == {"family": "meeting_note_version", "record_id": self.ids["N1"]}
        assert origin["revision_no"] == 1
        assert {anchor["version_id"] for anchor in origin["evidence"]} == {self.ids["N1"]}
        stored = note(self.rt, self.ids["M1"], self.ids["N1"])
        assert stored["body_markdown"] == NOTE_BODY

    # --- the stages ------------------------------------------------------------

    def run(self, until: int = 14) -> Workflow:
        stages = (
            self.stage_1,
            self.stage_2,
            self.stage_3,
            self.stage_4,
            self.stage_5,
            self.stage_6,
            self.stage_7,
            self.stage_8,
            self.stage_9,
            self.stage_10,
            self.stage_11,
            self.stage_12,
            self.stage_13,
            self.stage_14,
        )
        for number in range(self.stage + 1, until + 1):
            stages[number - 1]()
            self.stage = number
            if self.revise_m1 and number == 3:
                self.ids["N1b"] = revise_notes(
                    self.rt, self.ids["M1"], "s2-14-n1b", body=NOTE_BODY + " Revised later."
                )
            if self.revise_m1 and number >= 3:
                self.assert_n1_origin_unchanged()
            hook = self.after.get(number)
            if hook is not None:
                hook(self)
        return self

    def stage_1(self) -> None:
        """M1 in Series A; I; I -> P; I -> M1 `discussion`. No Commitment exists."""
        self.ids["M1"], no_note = self.meeting("m1", series="A", body=None)
        assert no_note is None
        self.ids["I"] = self.rt.issue("s2-14-i")
        self.ids["P"] = self.rt.project_with_constraints("s2-14-p")
        self.rt.link_project(self.ids["I"], self.ids["P"], "s2-14-p")
        self.member("m1", "meeting", "M1", "discussion")
        with self.rt.engine.connect() as connection:
            assert connection.execute(select(commitments)).first() is None
        assert self.from_issue()["nodes"] == self.refs("I", "M1")

    def stage_2(self) -> None:
        """M1's note becomes N1: immutable, digest H1."""
        self.ids["N1"] = revise_notes(self.rt, self.ids["M1"], "s2-14-n1", body=NOTE_BODY)
        stored = note(self.rt, self.ids["M1"], self.ids["N1"])
        self.ids["H1"] = str(stored["content_sha256"])
        assert stored["body_markdown"] == NOTE_BODY
        assert stored["meeting_id"] == self.ids["M1"]
        # The note itself creates no link: the graph from I is unchanged.
        assert self.from_issue()["nodes"] == self.refs("I", "M1")

    def stage_3(self) -> None:
        """C1 (P1, owed to the Principal) through the composite, `originated_from` N1."""
        origin = note_anchor(self.ids["M1"], self.ids["N1"], NOTE_BODY)
        written = self.lineage_write(
            work_commitment(
                self.ids["I"],
                "14-c1",
                self.commitment_object("c1", "P1"),
                intents=(
                    {
                        "relation_type": "originated_from",
                        "to_record": {
                            "family": "meeting_note_version",
                            "record_id": self.ids["N1"],
                        },
                        "evidence_anchors": [origin],
                    },
                ),
            )
        )
        self.ids["C1"] = str(written["record"]["record_id"])
        self.links["c1"] = str(written["membership"]["link_id"])
        (association,) = written["associations"]
        self.links["c1-origin"] = str(association["link_id"])
        (anchor,) = association["evidence"]
        # The admitted anchor bound N1's stored digest H1 (admission checks it).
        assert origin["source_sha256"] == self.ids["H1"]
        assert (anchor["version_id"], anchor["role"]) == (self.ids["N1"], "origin")
        view = self.rt.commitment_view(self.ids["C1"])
        assert (view["state"], view["evidence_state"], view["direction"]) == (
            "open",
            "accepted",
            "owed_to_principal",
        )
        assert view["counterparty_entity_id"] == self.ids["P1"]
        self.ids["C1-created"] = str(view["created_at"])
        # Gate: lineage from I = {I, M1, N1, C1}.
        assert self.from_issue()["nodes"] == self.refs("I", "M1", "N1", "C1")

    def stage_4(self) -> None:
        """C1 closes natively; its resolution evidence (E0); one handoff P1 -> Principal."""
        tasks_before = len(snapshot(self.rt)["tasks"])
        self.rt.close_commitment(self.ids["C1"], "s2-14-c1")
        self.record_resolution("c1", "c1", self.resolution("E0"))
        # Neither the native close nor the evidence wrote a handoff or a Task.
        assert self.handoffs() == []
        assert len(snapshot(self.rt)["tasks"]) == tasks_before
        effective = datetime.fromisoformat(self.ids["C1-created"]) + timedelta(milliseconds=1)
        anchor = note_anchor(
            self.ids["M1"], self.ids["N1"], NOTE_BODY, role="handoff", passage="Ana will send"
        )
        written = self.lineage_write(
            handoff(
                self.ids["I"],
                self.ids["C1"],
                "counterparty",
                effective.isoformat(),
                "14-c1",
                anchor,
            )
        )["handoff"]
        assert written["from"] == {"kind": "entity", "entity_id": self.ids["P1"]}
        assert written["to"] == {"kind": "principal", "entity_id": None}
        (event,) = self.handoffs()
        assert event["handoff_id"] == written["handoff_id"]
        assert len(snapshot(self.rt)["tasks"]) == tasks_before
        view = self.rt.commitment_view(self.ids["C1"])
        assert (view["state"], view["counterparty_entity_id"]) == ("closed", self.ids["P1"])
        self.ids["C1-version"] = str(view["version"])
        # C1 is satisfied; nothing gates the close yet.
        assert blocked(self.rt, self.ids["I"]) == {}

    def stage_5(self) -> None:
        """T1: the Principal's `direct_principal` follow-up of the closed C1."""
        before = self.rt.commitment_view(self.ids["C1"])
        written = self.lineage_write(
            work_task(
                self.ids["I"],
                "14-t1",
                {
                    "title": "Synthetic follow-up T1",
                    "origin_kind": "direct_principal",
                    "role": "follow_up",
                    "commitment_id": self.ids["C1"],
                },
            )
        )
        self.ids["T1"] = str(written["record"]["record_id"])
        self.links["t1"] = str(written["membership"]["link_id"])
        view = self.task("T1")
        assert (view["role"], view["commitment_id"]) == ("follow_up", self.ids["C1"])
        assert (view["evidence_state"], view["acceptance_kind"]) == ("accepted", "direct_principal")
        assert view["accepted_by_review_decision_id"] is None
        # Gate: C1's version and state are unchanged, and no handoff was written.
        assert self.rt.commitment_view(self.ids["C1"]) == before
        assert len(self.handoffs()) == 1
        assert set(blocked(self.rt, self.ids["I"])) == {self.ids["T1"]}

    def stage_6(self) -> None:
        """M2 (Series A) + N2 discusses T1; Issue J on another Series A Meeting is not reached."""
        self.ids["M2"], n2 = self.meeting("m2", series="A")
        self.ids["N2"] = str(n2)
        self.member("m2", "meeting", "M2", "discussion")
        self.discusses("n2-t1", ("M2", "N2"), NOTE_BODY, "façade survey", ("task", "T1"))
        # Issue J: its own Series A Meeting MJ and its own Task.
        self.ids["J"] = self.rt.issue("s2-14-j")
        self.ids["MJ"], nj = self.meeting("mj", series="A")
        self.ids["NJ"] = str(nj)
        self.ids["TJ"] = self.rt.task("s2-14-tj")
        self.rt.member(self.ids["J"], "meeting", self.ids["MJ"], "s2-14-j-mj", "discussion")
        self.rt.member(self.ids["J"], "task", self.ids["TJ"], "s2-14-j-tj", "work")
        answer = self.from_issue()
        assert answer["nodes"] == self.refs("I", "M1", "N1", "C1", "T1", "M2", "N2")
        assert not answer["nodes"] & {
            ("situation", self.ids["J"]),
            ("meeting", self.ids["MJ"]),
            ("meeting_note_version", self.ids["NJ"]),
            ("task", self.ids["TJ"]),
        }

    def stage_7(self) -> None:
        """X1 published in P; I -> X1 `constraint`; X1 `escalated_from` T1. T1 and I unchanged."""
        task_before, issue_before = self.task("T1"), self.issue()
        self.ids["X1"] = self.rt.constraint(self.ids["P"], "s2-14-x1")
        self.member("x1", "constraint", "X1", "constraint")
        written = self.lineage_write(
            AssertRecordAssociation(
                from_record={"family": "constraint", "record_id": self.ids["X1"]},
                to_record={"family": "task", "record_id": self.ids["T1"]},
                relation_type="escalated_from",
                idempotency_key="s2-14-x1-escalated",
                evidence_anchors=(
                    note_anchor(self.ids["M2"], self.ids["N2"], NOTE_BODY, passage="Next: pour"),
                ),
                context_issue_id=self.ids["I"],
            )
        )
        self.links["x1-escalated"] = str(written["association"]["link_id"])
        assert self.task("T1") == task_before
        assert self.issue() == issue_before
        assert self.constraint("X1")["status"] == "identified"
        assert set(blocked(self.rt, self.ids["I"])) == {self.ids["T1"], self.ids["X1"]}

    def stage_8(self) -> None:
        """C2 (P2) and C3 (P3), each `delegated_from` T1. 2 Commitments, 0 new handoffs."""
        handoffs_before = self.handoffs()
        for name, party, passage in (("C2", "P2", "Ana will send"), ("C3", "P3", "Decisions")):
            key = name.lower()
            written = self.lineage_write(
                work_commitment(
                    self.ids["I"],
                    f"14-{key}",
                    self.commitment_object(key, party),
                    intents=(
                        {
                            "relation_type": "delegated_from",
                            "to_record": {"family": "task", "record_id": self.ids["T1"]},
                            "evidence_anchors": [
                                note_anchor(
                                    self.ids["M2"], self.ids["N2"], NOTE_BODY, passage=passage
                                )
                            ],
                        },
                    ),
                )
            )
            self.ids[name] = str(written["record"]["record_id"])
            self.links[key] = str(written["membership"]["link_id"])
            (association,) = written["associations"]
            assert association["relation_type"] == "delegated_from"
            self.links[f"{key}-delegated"] = str(association["link_id"])
        c2, c3 = self.rt.commitment_view(self.ids["C2"]), self.rt.commitment_view(self.ids["C3"])
        assert c2["commitment_id"] != c3["commitment_id"]
        assert (c2["counterparty_entity_id"], c3["counterparty_entity_id"]) == (
            self.ids["P2"],
            self.ids["P3"],
        )
        assert len({self.ids["P1"], self.ids["P2"], self.ids["P3"]}) == 3
        assert self.handoffs() == handoffs_before
        assert self.task("T1")["lifecycle_state"] != "completed"

    def stage_9(self) -> None:
        """M3 (Series B) + N3; I -> M3; 4 `discusses` N3 -> T1, X1, C2, C3 on 4 passages."""
        self.ids["M3"], n3 = self.meeting("m3", series="B")
        self.ids["N3"] = str(n3)
        assert self.ids["series-A"] != self.ids["series-B"]
        self.member("m3", "meeting", "M3", "discussion")
        for target, passage in zip(
            (("task", "T1"), ("constraint", "X1"), ("commitment", "C2"), ("commitment", "C3")),
            N3_PASSAGES,
            strict=True,
        ):
            self.discusses(f"n3-{target[1].lower()}", ("M3", "N3"), NOTE_BODY, passage, target)
        # A Series B sibling of M3, a member of J, is never reached.
        self.ids["MB"], nb = self.meeting("mb", series="B")
        self.ids["NB"] = str(nb)
        self.rt.member(self.ids["J"], "meeting", self.ids["MB"], "s2-14-j-mb", "discussion")
        answer = self.from_issue()
        assert answer["nodes"] == self.refs(
            "I", "M1", "N1", "C1", "T1", "M2", "N2", "X1", "C2", "C3", "M3", "N3"
        )
        assert not answer["nodes"] & {
            ("situation", self.ids["J"]),
            ("meeting", self.ids["MB"]),
            ("meeting_note_version", self.ids["NB"]),
            ("meeting", self.ids["MJ"]),
        }
        assert answer["complete_state"] == "complete"

    def stage_10(self) -> None:
        """C2 closes and records its evidence; later C3. Between them C3, T1, X1 block."""
        self.rt.close_commitment(self.ids["C2"], "s2-14-c2")
        self.record_resolution("c2", "c2", self.resolution("E2"))
        between = blocked(self.rt, self.ids["I"])
        assert set(between) == {self.ids["C3"], self.ids["T1"], self.ids["X1"]}
        assert between[self.ids["C3"]][0] == "native_open"
        # Closing C2 closed neither C3 nor T1, and moved no responsibility.
        assert self.rt.commitment_view(self.ids["C3"])["state"] == "open"
        assert self.task("T1")["lifecycle_state"] != "completed"
        assert len(self.handoffs()) == 1
        self.rt.close_commitment(self.ids["C3"], "s2-14-c3")
        self.record_resolution("c3", "c3", self.resolution("E3"))
        assert set(blocked(self.rt, self.ids["I"])) == {self.ids["T1"], self.ids["X1"]}

    def stage_11(self) -> None:
        """T1 completes; its evidence. X1 open; I open; readiness blocks X1 only."""
        constraint_before, issue_before = self.constraint("X1"), self.issue()
        self.rt.transition(self.ids["T1"], TaskLifecycleState.COMPLETED, "s2-14-t1")
        self.record_resolution("t1", "t1", self.resolution("E4"))
        assert self.task("T1")["lifecycle_state"] == "completed"
        assert self.constraint("X1") == constraint_before
        assert self.issue() == issue_before
        assert issue_before["state"] == "open"
        for name in ("C1", "C2", "C3"):
            assert self.rt.commitment_view(self.ids[name])["state"] == "closed", name
        reasons = blocked(self.rt, self.ids["I"])
        assert set(reasons) == {self.ids["X1"]}
        assert reasons[self.ids["X1"]][0] == "native_open"

    def stage_12(self) -> None:
        """M4 (Series A) + N4 discusses I, X1, T1; a close on N4's words is refused, no row."""
        self.ids["M4"], n4 = self.meeting("m4", series="A", body=N4_BODY)
        self.ids["N4"] = str(n4)
        self.member("m4", "meeting", "M4", "discussion")
        for target, passage in zip(
            (("situation", "I"), ("constraint", "X1"), ("task", "T1")), N4_PASSAGES, strict=True
        ):
            self.discusses(f"n4-{target[1].lower()}", ("M4", "N4"), N4_BODY, passage, target)
        before = snapshot(self.rt)
        words = note_anchor(
            self.ids["M4"], self.ids["N4"], N4_BODY, role="resolution", passage=N4_PASSAGES[1]
        )
        assert self.refused(
            close(self.ids["I"], int(self.issue()["version"]), "14-on-words", (words,))
        ) == ("conflict", ["closure_gate"])
        assert snapshot(self.rt) == before
        assert self.constraint("X1")["status"] == "identified"
        assert self.issue()["state"] == "open"

    def stage_13(self) -> None:
        """X1 closes natively; its resolution evidence (E1). Ready; I still open."""
        self.rt.close_constraint(self.ids["X1"], "s2-14-x1")
        self.record_resolution("x1", "x1", self.resolution("E1"))
        readiness = self.rt.readiness(self.ids["I"])
        assert (readiness["ready"], readiness["blockers"]) == (True, [])
        assert self.issue()["state"] == "open"
        assert self.constraint("X1")["status"] == "closed"

    def stage_14(self) -> None:
        """I closes (`resolution` E1, `corroborates` N4) at `version + 1`."""
        version = int(self.issue()["version"])
        e1 = self.membership(self.links["x1"])["evidence"]
        (e1_anchor,) = e1
        anchors = (
            capture_anchor(str(e1_anchor["root_id"]), self.ids["E1"], NOTE_BODY, role="resolution"),
            note_anchor(
                self.ids["M4"],
                self.ids["N4"],
                N4_BODY,
                role="corroborates",
                passage=N4_PASSAGES[1],
            ),
        )
        written = self.lineage_write(close(self.ids["I"], version, "14-i", anchors))
        assert written["issue"]["version"] == version + 1
        assert (written["issue"]["state"], written["issue"]["action"]) == ("closed", "closed")
        closure = written["closure"]
        assert {anchor["availability"] for anchor in closure["evidence"]} == {"available"}
        assert sorted(anchor["role"] for anchor in closure["evidence"]) == [
            "corroborates",
            "resolution",
        ]
        assert {anchor["version_id"] for anchor in closure["evidence"]} == {
            self.ids["E1"],
            self.ids["N4"],
        }
        issue = self.issue()
        assert issue["state"] == "closed"
        assert issue["closure"]["version"] == version + 1


_FAMILY: Final = {
    "I": "situation",
    "J": "situation",
    "M": "meeting",
    "N": "meeting_note_version",
    "C": "commitment",
    "T": "task",
    "X": "constraint",
}

#: The 14 roots of the reverse-root equivalence.
ROOTS: Final = ("M1", "M2", "M3", "M4", "N1", "N2", "N3", "N4", "C1", "C2", "C3", "T1", "X1", "I")


# ---- the whole workflow --------------------------------------------------------------


def test_fourteen_stages_end_to_end_with_reconciliation_gates(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(14)
    # After stage 14: the closed Issue's whole graph, every node and typed edge.
    answer = flow.from_issue()
    assert answer["nodes"] == flow.refs(*ROOTS)
    assert answer["relations"] == sorted(
        ["issue_member"] * 9
        + ["originated_from"]
        + ["discusses"] * 8
        + ["escalated_from"]
        + ["delegated_from"] * 2
    )
    assert answer["complete_state"] == "complete"
    # Every member's native state and the ledger at the end.
    assert flow.task("T1")["lifecycle_state"] == "completed"
    assert flow.constraint("X1")["status"] == "closed"
    for name in ("C1", "C2", "C3"):
        view = runtime.commitment_view(flow.ids[name])
        assert (view["state"], view["evidence_state"]) == ("closed", "accepted"), name
    (event,) = flow.handoffs()
    assert (event["sequence_no"], event["commitment_id"]) == (1, flow.ids["C1"])
    # The closed Issue answers not ready, with nothing to list.
    readiness = runtime.readiness(flow.ids["I"])
    assert (readiness["ready"], readiness["blockers"], readiness["state"]) == (
        False,
        [],
        "closed",
    )
    # Principal B sees none of it: I answers like an absent Issue.
    error = runtime.refused(
        ReadRecordLineage(origin={"family": "situation", "record_id": flow.ids["I"]}),
        principal_id=OTHER_PRINCIPAL,
    )
    assert error["code"] == "not_found"


def test_stage_14_before_stage_13_is_refused_and_writes_nothing(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(12)
    version = int(flow.issue()["version"])
    e1 = flow.resolution("E1")
    stage_14 = (
        e1,
        note_anchor(
            flow.ids["M4"], flow.ids["N4"], N4_BODY, role="corroborates", passage=N4_PASSAGES[1]
        ),
    )
    before = snapshot(runtime)
    assert flow.refused(close(flow.ids["I"], version, "14-early", stage_14)) == (
        "conflict",
        ["closure_gate"],
    )
    assert snapshot(runtime) == before
    # Half of stage 13 -- X1 closed natively, no resolution evidence yet -- is not enough.
    runtime.close_constraint(flow.ids["X1"], "s2-14-x1-early")
    assert blocked(runtime, flow.ids["I"])[flow.ids["X1"]] == [
        "resolution_evidence_missing",
        "resolution_evidence_stale",
    ]
    before = snapshot(runtime)
    assert flow.refused(close(flow.ids["I"], version, "14-half", stage_14)) == (
        "conflict",
        ["closure_gate"],
    )
    assert snapshot(runtime) == before
    assert flow.issue()["version"] == version
    assert flow.issue()["state"] == "open"
    # Stage 13 completed, the same closure set closes the Issue.
    flow.record_resolution("x1", "x1", e1)
    closed = flow.lineage_write(close(flow.ids["I"], version, "14-late", stage_14))
    assert (closed["issue"]["state"], closed["issue"]["version"]) == ("closed", version + 1)


# ---- per-stage oracles ------------------------------------------------------------------


def test_closing_c1_records_no_handoff_and_creates_no_task(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(3)
    before = snapshot(runtime)
    runtime.close_commitment(flow.ids["C1"], "s2-14-c1-alone")
    after = snapshot(runtime)
    assert after["issue_responsibility_events"] == before["issue_responsibility_events"] == []
    assert after["tasks"] == before["tasks"]
    # The close moved no lineage row either: only the native Commitment row changed.
    assert {name for name in before if before[name] != after[name]} == {"commitments"}
    assert flow.handoffs() == []
    page = runtime.ok(ListIssueHandoffs(issue_id=flow.ids["I"], commitment_id=flow.ids["C1"]))
    # S3 section 7.1 lockstep: the page also reports the cut it was read at,
    # and (section 6.4) whether anything was withheld.
    assert page == {
        "handoffs": [],
        "next_cursor": None,
        "known_at": page["known_at"],
        "restricted": False,
    }


def test_t1_follows_up_a_closed_c1_without_reopening_it(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(4)
    closed = runtime.commitment_view(flow.ids["C1"])
    flow.run(5)
    after = runtime.commitment_view(flow.ids["C1"])
    assert after == closed
    assert (after["state"], str(after["version"])) == ("closed", flow.ids["C1-version"])
    t1 = flow.task("T1")
    assert t1["commitment_id"] == flow.ids["C1"]
    assert t1["lifecycle_state"] not in {"completed", "cancelled"}
    membership = flow.membership(flow.links["t1"])
    assert (membership["member_role"], membership["to"]["record_id"]) == ("work", flow.ids["T1"])


def test_a_shared_series_a_links_no_other_issue(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(6)
    assert flow.ids["series-A"]
    # M1, M2 and J's MJ share Series A; I's traversal from each I-root reaches no J record.
    foreign = {
        ("situation", flow.ids["J"]),
        ("meeting", flow.ids["MJ"]),
        ("meeting_note_version", flow.ids["NJ"]),
        ("task", flow.ids["TJ"]),
    }
    for name in ("M1", "M2", "N2", "T1", "I"):
        answer = graph(runtime, flow.ref(_FAMILY[name[0]], name), flow.ids["I"])
        assert not answer["nodes"] & foreign, name
    # And J's graph reaches nothing of I's.
    j_answer = graph(runtime, ("situation", flow.ids["J"]), flow.ids["J"])
    # (NJ is no link's endpoint, so it is only MJ's virtual note edge.)
    assert j_answer["nodes"] == foreign - {("meeting_note_version", flow.ids["NJ"])}
    assert j_answer["virtual"] == {(flow.ids["NJ"], flow.ids["MJ"])}
    # A Series A Meeting that is only J's offers only J.
    mj = runtime.ok(ReadRecordLineage(origin={"family": "meeting", "record_id": flow.ids["MJ"]}))
    assert [match["issue_id"] for match in mj["issues_matching_root"]] == [flow.ids["J"]]


def test_creating_x1_changes_no_task_or_issue_state(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(6)
    task_before, issue_before = flow.task("T1"), flow.issue()
    flow.run(7)
    assert flow.task("T1") == task_before
    assert flow.issue() == issue_before
    x1 = flow.constraint("X1")
    assert (x1["status"], x1["project_id"]) == ("identified", flow.ids["P"])
    # X1 is in I's graph through its membership and its escalation from T1.
    edges = {edge["link_id"]: edge for edge in flow.from_issue()["typed_edges"]}
    escalation = edges[flow.links["x1-escalated"]]
    assert escalation["relation_type"] == "escalated_from"
    assert escalation["from"]["record_id"] == flow.ids["X1"]
    assert escalation["to"]["record_id"] == flow.ids["T1"]


def test_one_delegate_closing_leaves_the_other_open(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(9)
    c3_before = runtime.commitment_view(flow.ids["C3"])
    t1_before = flow.task("T1")
    runtime.close_commitment(flow.ids["C2"], "s2-14-c2-alone")
    assert runtime.commitment_view(flow.ids["C2"])["state"] == "closed"
    assert runtime.commitment_view(flow.ids["C3"]) == c3_before
    assert c3_before["state"] == "open"
    assert flow.task("T1") == t1_before
    assert len(flow.handoffs()) == 1
    reasons = blocked(runtime, flow.ids["I"])
    assert reasons[flow.ids["C3"]][0] == "native_open"
    # C2 is closed, but the evidence recorded at its creation predates the close.
    assert "resolution_evidence_stale" in reasons[flow.ids["C2"]]


def test_m3_in_series_b_imports_no_series_sibling(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(9)
    sibling = {
        ("meeting", flow.ids["MB"]),
        ("meeting_note_version", flow.ids["NB"]),
        ("situation", flow.ids["J"]),
    }
    for name in ("M3", "N3"):
        answer = graph(runtime, flow.ref(_FAMILY[name[0]], name), flow.ids["I"])
        assert flow.refs("M3", "N3", "T1", "X1", "C2", "C3") <= answer["nodes"], name
        assert not answer["nodes"] & sibling, name
    # The 4 passage-scoped discussions, one per record, each on its own passage.
    edges = {edge["link_id"]: edge for edge in flow.from_issue()["typed_edges"]}
    for name, passage in zip(("t1", "x1", "c2", "c3"), N3_PASSAGES, strict=True):
        (anchor,) = edges[flow.links[f"n3-{name}"]]["evidence"]
        start = NOTE_BODY.index(passage)
        assert (anchor["passage_start_cp"], anchor["passage_end_cp"]) == (
            start,
            start + len(passage),
        )
    # M3 keeps Series B.
    m3 = runtime.ok(ReadMeeting(meeting_id=flow.ids["M3"]))["meeting"]
    assert m3["meeting_series_id"] == flow.ids["series-B"]


def test_completing_t1_changes_no_constraint_or_issue(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(10)
    x1_before, issue_before = flow.constraint("X1"), flow.issue()
    lineage_before = {name: rows for name, rows in snapshot(runtime).items() if name != "tasks"}
    runtime.transition(flow.ids["T1"], TaskLifecycleState.COMPLETED, "s2-14-t1-alone")
    assert flow.task("T1")["lifecycle_state"] == "completed"
    assert flow.constraint("X1") == x1_before
    assert flow.issue() == issue_before
    after = {name: rows for name, rows in snapshot(runtime).items() if name != "tasks"}
    assert after == lineage_before
    # T1's evidence is now stale: what it recorded predates the completion.
    reasons = blocked(runtime, flow.ids["I"])
    assert set(reasons) == {flow.ids["T1"], flow.ids["X1"]}
    assert "native_open" not in reasons[flow.ids["T1"]]


def test_m4_resolution_words_cannot_close_x1_or_the_issue(runtime: S2Runtime) -> None:
    flow = Workflow(runtime).run(12)
    assert flow.constraint("X1")["status"] == "identified"
    assert flow.issue()["state"] == "open"
    # N4's words are evidence of discussion, not of X1's resolution: as X1's
    # resolution evidence they leave X1 natively open, so the gate still blocks.
    words = note_anchor(
        flow.ids["M4"], flow.ids["N4"], N4_BODY, role="resolution", passage=N4_PASSAGES[1]
    )
    flow.record_resolution("x1", "x1-words", words)
    reasons = blocked(runtime, flow.ids["I"])
    assert set(reasons) == {flow.ids["X1"]}
    assert reasons[flow.ids["X1"]][0] == "native_open"
    assert flow.constraint("X1")["status"] == "identified"
    before = snapshot(runtime)
    assert flow.refused(
        close(flow.ids["I"], int(flow.issue()["version"]), "14-words-again", (words,))
    ) == ("conflict", ["closure_gate"])
    assert snapshot(runtime) == before
    # The discussions themselves are in I's graph, passage-anchored to N4.
    edges = {edge["link_id"]: edge for edge in flow.from_issue()["typed_edges"]}
    for name in ("i", "x1", "t1"):
        edge = edges[flow.links[f"n4-{name}"]]
        assert edge["relation_type"] == "discusses"
        assert edge["from"]["record_id"] == flow.ids["N4"]


def test_every_root_yields_the_same_current_issue_graph_after_stage_14(
    runtime: S2Runtime,
) -> None:
    flow = Workflow(runtime).run(14)
    answers = {
        name: graph(runtime, flow.ref(_FAMILY[name[0]], name), flow.ids["I"]) for name in ROOTS
    }
    expected = answers["I"]
    assert expected["nodes"] == flow.refs(*ROOTS)
    assert len(expected["edges"]) == 21
    # Every note version of every reached Meeting, and nothing else, is a virtual edge.
    assert expected["virtual"] == {
        (flow.ids[f"N{index}"], flow.ids[f"M{index}"]) for index in (1, 2, 3, 4)
    }
    for name, answer in answers.items():
        assert answer["nodes"] == expected["nodes"], name
        assert answer["edges"] == expected["edges"], name
        assert answer["virtual"] == expected["virtual"], name
        assert answer["complete_state"] == "complete", name


def test_n1b_never_retargets_c1_across_the_workflow(runtime: S2Runtime) -> None:
    # The workflow asserts C1 -> N1 (revision 1, N1's exact evidence) after every
    # stage from 3 on, with M1's note revised to N1b right after stage 3.
    flow = Workflow(runtime, revise_m1_after_stage_3=True).run(14)
    current = runtime.ok(
        ReadRecordLineage(origin={"family": "meeting", "record_id": flow.ids["M1"]})
    )
    assert current["selected_issue_id"] == flow.ids["I"]
    nodes = {(node["family"], node["record_id"]) for node in current["nodes"]}
    assert ("meeting_note_version", flow.ids["N1b"]) not in nodes
    assert ("meeting_note_version", flow.ids["N1"]) in nodes
    virtual = {edge["from"]["record_id"] for edge in current["virtual_native_edges"]}
    assert {flow.ids["N1"], flow.ids["N1b"]} <= virtual
    stored = note(runtime, flow.ids["M1"], flow.ids["N1"])
    assert stored["content_sha256"] == flow.ids["H1"] and stored["is_current"] is False
