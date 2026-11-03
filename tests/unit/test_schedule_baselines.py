"""Schedule Scenarios S6-1: operator-approved Project baselines, pure over event lists (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 12, vectors
B1-B11 (section 12.5). Each vector replays the Project's append-only event
chains through the transition rules (`decide_baseline_write`) the S6-2 writer
re-checks under the Project lock, then reads the derived state. Every
identifier and instant is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

import pytest

from my_pa.domain.schedule.baselines import (
    MAX_PENDING_PER_BUCKET,
    MAX_PENDING_PER_PROJECT,
    ApproveRequest,
    BaselineAction,
    BaselineEvent,
    BaselinePlan,
    BaselineRefusal,
    BaselineRequest,
    BaselineStatus,
    BaselineType,
    BaselineView,
    GoverningEvent,
    ProposeRequest,
    RejectRequest,
    RevokeRequest,
    SetGoverningRequest,
    WithdrawRequest,
    baseline_status,
    compare_refusal,
    decide_baseline_write,
    governing_baseline,
    next_baseline_label,
)

CONTRACT: Final = BaselineType.CONTRACT
UPDATE: Final = BaselineType.APPROVED_UPDATE
EFFECTIVE: Final = date(2027, 1, 1)


@dataclass
class Project:
    """One Project's chains, appended only through the transition rules."""

    eligible: set[str] = field(default_factory=set)
    events: list[BaselineEvent] = field(default_factory=list)
    governing: list[GoverningEvent] = field(default_factory=list)
    clock: datetime = datetime(2027, 1, 10, 9, 0)
    minted: int = 0

    def views(self) -> dict[str, BaselineView]:
        return baseline_status(self.events, eligible_publication_ids=self.eligible)

    def by_label(self, label: str) -> BaselineView:
        return next(view for view in self.views().values() if view.label == label)

    def on(self, publication: str) -> BaselineView:
        return next(view for view in self.views().values() if view.publication_id == publication)

    def write(
        self,
        request: BaselineRequest,
        *,
        bucket: str | None = None,
        type_: BaselineType | None = None,
        effective_from: date | None = None,
        supersedes: str | None = None,
        recorded_at: datetime | None = None,
    ) -> BaselinePlan | BaselineRefusal:
        plan = decide_baseline_write(
            self.events, self.governing, request, eligible_publication_ids=self.eligible
        )
        if isinstance(plan, BaselineRefusal):
            return plan
        when = recorded_at or self.clock
        self.clock = when
        if plan.action is not None:
            baseline_id = plan.baseline_id
            if baseline_id is None:
                self.minted += 1
                baseline_id = f"sbl_{self.minted:010d}"
            assert plan.publication_id is not None
            self.events.append(
                BaselineEvent(
                    seq=len(self.events) + 1,
                    baseline_id=baseline_id,
                    publication_id=plan.publication_id,
                    action=plan.action,
                    recorded_at=when,
                    type=type_,
                    label=plan.label,
                    effective_from=effective_from,
                    supersedes_baseline_id=supersedes,
                    proposal_ordinal=plan.proposal_ordinal,
                    writer_bucket=bucket,
                )
            )
        if plan.governing:
            governed = plan.baseline_id or self.events[-1].baseline_id
            self.governing.append(
                GoverningEvent(seq=len(self.governing) + 1, baseline_id=governed, recorded_at=when)
            )
        return plan

    def import_approve(
        self, publication: str, type_: BaselineType, *, effective_from: date = EFFECTIVE
    ) -> str:
        """The import-time approval: written before the parse decides eligibility."""
        plan = self.write(
            ApproveRequest(
                type=type_,
                effective_from=effective_from,
                publication_id=publication,
                at_import=True,
            ),
            type_=type_,
            effective_from=effective_from,
        )
        assert isinstance(plan, BaselinePlan)
        return self.events[-1].baseline_id

    def propose(
        self, publication: str, type_: BaselineType, bucket: str = "client-a"
    ) -> BaselinePlan | BaselineRefusal:
        return self.write(ProposeRequest(publication, type_, bucket), bucket=bucket, type_=type_)

    def set_governing(
        self, baseline_id: str, expected: str | None, *, at: datetime | None = None
    ) -> BaselinePlan | BaselineRefusal:
        return self.write(SetGoverningRequest(baseline_id, expected), recorded_at=at)


def _b1() -> tuple[Project, str]:
    project = Project(eligible={"spub_p0"})
    return project, project.import_approve("spub_p0", CONTRACT)


def _b4() -> tuple[Project, str, str]:
    project, bl0 = _b1()
    project.set_governing(bl0, None)
    project.eligible.add("spub_p5")
    project.propose("spub_p5", UPDATE)
    proposal = project.on("spub_p5").baseline_id
    plan = project.write(
        ApproveRequest(
            type=UPDATE,
            effective_from=date(2027, 2, 1),
            baseline_id=proposal,
            supersedes_baseline_id=bl0,
        ),
        type_=UPDATE,
        effective_from=date(2027, 2, 1),
        supersedes=bl0,
    )
    assert isinstance(plan, BaselinePlan)
    return project, bl0, proposal


def _check_b1() -> None:
    project, bl0 = _b1()
    view = project.views()[bl0]
    assert (view.status, view.label, view.effective_type, view.effective) == (
        BaselineStatus.APPROVED,
        "BL-0",
        CONTRACT,
        True,
    )
    assert governing_baseline(project.governing) is None


@pytest.mark.parametrize(
    "vector", ["B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11"]
)
def test_baseline_vectors(vector: str) -> None:
    VECTOR_CHECKS[vector]()


def _check_b2() -> None:
    project, bl0 = _b1()
    assert isinstance(project.set_governing(bl0, None), BaselinePlan)
    assert governing_baseline(project.governing) == bl0


def _check_b3() -> None:
    project, bl0 = _b1()
    project.set_governing(bl0, None)
    project.eligible.add("spub_p5")
    assert isinstance(project.propose("spub_p5", UPDATE), BaselinePlan)
    proposal = project.on("spub_p5")
    assert proposal.status is BaselineStatus.PROPOSED
    assert proposal.pending and not proposal.effective
    assert (proposal.label, proposal.effective_type, proposal.proposed_type) == (None, None, UPDATE)
    assert governing_baseline(project.governing) == bl0
    effective = {view.publication_id for view in project.views().values() if view.effective}
    assert effective == {"spub_p0"}  # P5 is still a standard update for currency
    assert next_baseline_label(project.events) == "BL-1"


def _check_b4() -> None:
    project, bl0, bl1 = _b4()
    views = project.views()
    assert (views[bl1].status, views[bl1].label) == (BaselineStatus.APPROVED, "BL-1")
    assert views[bl0].superseded is True and views[bl0].effective is True
    assert views[bl1].superseded is False
    assert governing_baseline(project.governing) == bl0


def _b5() -> tuple[Project, str, str]:
    project = Project(eligible={"spub_p0", "spub_p5"})
    bl0 = project.import_approve("spub_p0", CONTRACT, effective_from=date(2027, 1, 1))
    project.propose("spub_p5", UPDATE)
    bl1 = project.on("spub_p5").baseline_id
    project.write(
        ApproveRequest(
            type=UPDATE,
            effective_from=date(2026, 12, 1),
            baseline_id=bl1,
            supersedes_baseline_id=bl0,
        ),
        type_=UPDATE,
        effective_from=date(2026, 12, 1),
        supersedes=bl0,
    )
    project.set_governing(bl0, None, at=datetime(2027, 2, 1, 10, 0))
    project.set_governing(bl1, bl0, at=datetime(2027, 3, 1, 10, 0))
    return project, bl0, bl1


def _check_b5() -> None:
    project, bl0, bl1 = _b5()
    chain = project.governing
    assert governing_baseline(chain) == bl1
    assert governing_baseline(chain, as_of=datetime(2027, 1, 15)) is None
    assert governing_baseline(chain, as_of=datetime(2027, 2, 15)) == bl0
    assert governing_baseline(chain, as_of=datetime(2027, 3, 15)) == bl1
    views = project.views()
    assert (views[bl0].effective_from, views[bl1].effective_from) == (
        date(2027, 1, 1),
        date(2026, 12, 1),
    )


def _check_b6() -> None:
    project, _, bl1 = _b5()
    assert project.write(RevokeRequest(bl1)) is BaselineRefusal.CONFLICT_GOVERNING


def _check_b7() -> None:
    project = Project(eligible={"spub_p3"})
    project.propose("spub_p3", UPDATE)
    proposal = project.on("spub_p3").baseline_id
    assert isinstance(project.write(RejectRequest(proposal)), BaselinePlan)
    assert project.views()[proposal].status is BaselineStatus.REJECTED
    assert project.views()[proposal].label is None
    assert next_baseline_label(project.events) == "BL-0"


def _check_b8() -> None:
    project = Project(eligible=set())
    bl = project.import_approve("spub_p9", CONTRACT)  # its parse then ends `failed`
    view = project.views()[bl]
    assert (view.status, view.label, view.effective) == (BaselineStatus.INELIGIBLE, "BL-0", False)
    assert next_baseline_label(project.events) == "BL-1"
    assert project.set_governing(bl, None) is BaselineRefusal.CONFLICT_BASELINE_ID
    assert governing_baseline(project.governing) is None


def _check_b9() -> None:
    project = Project(eligible={"spub_p4"})
    assert isinstance(project.propose("spub_p4", UPDATE, "client-a"), BaselinePlan)
    assert project.propose("spub_p4", CONTRACT, "client-b") is BaselineRefusal.CONFLICT_BASELINE_ID


def _check_b10() -> None:
    project, bl0 = _b1()
    view = project.views()[bl0]
    assert compare_refusal(
        view, baseline_series_id="sser_x", to_series_id="sser_y", to_eligible=True
    ) is (BaselineRefusal.INVALID_TO_PUBLICATION_ID)
    assert (
        compare_refusal(view, baseline_series_id="sser_x", to_series_id="sser_x", to_eligible=True)
        is None
    )


def _check_b11() -> None:
    project = Project(eligible={"spub_p7"})
    project.propose("spub_p7", UPDATE, "client-a")
    proposal = project.on("spub_p7").baseline_id
    plan = project.write(
        ApproveRequest(type=CONTRACT, effective_from=EFFECTIVE, publication_id="spub_p7"),
        type_=CONTRACT,
        effective_from=EFFECTIVE,
    )
    assert isinstance(plan, BaselinePlan)
    assert plan.baseline_id == proposal  # adopted, not a second Baseline row
    views = project.views()
    assert list(views) == [proposal]
    view = views[proposal]
    assert (view.status, view.label, view.proposed_type, view.effective_type) == (
        BaselineStatus.APPROVED,
        "BL-0",
        UPDATE,
        CONTRACT,
    )
    assert not view.pending
    assert project.write(WithdrawRequest(proposal, "client-a"), bucket="client-a") is (
        BaselineRefusal.CONFLICT_BASELINE_ID
    )


VECTOR_CHECKS: Final = {
    "B1": _check_b1,
    "B2": _check_b2,
    "B3": _check_b3,
    "B4": _check_b4,
    "B5": _check_b5,
    "B6": _check_b6,
    "B7": _check_b7,
    "B8": _check_b8,
    "B9": _check_b9,
    "B10": _check_b10,
    "B11": _check_b11,
}


def test_transition_refusals() -> None:
    project, bl0 = _b1()
    # A publication is approved at most once ever (S6-D28), revoked or not.
    assert project.write(
        ApproveRequest(type=UPDATE, effective_from=EFFECTIVE, publication_id="spub_p0")
    ) is (BaselineRefusal.CONFLICT_BASELINE_ID)
    assert project.propose("spub_p0", UPDATE) is BaselineRefusal.CONFLICT_BASELINE_ID
    assert isinstance(project.write(RevokeRequest(bl0)), BaselinePlan)
    assert project.views()[bl0].status is BaselineStatus.REVOKED
    assert project.write(RevokeRequest(bl0)) is BaselineRefusal.CONFLICT_BASELINE_ID
    assert project.write(
        ApproveRequest(type=UPDATE, effective_from=EFFECTIVE, publication_id="spub_p0")
    ) is (BaselineRefusal.CONFLICT_BASELINE_ID)
    # Ineligible publications are refused outside the import-time approval.
    assert project.propose("spub_q1", UPDATE) is BaselineRefusal.CONFLICT_STATUS
    assert project.write(
        ApproveRequest(type=UPDATE, effective_from=EFFECTIVE, publication_id="spub_q1")
    ) is (BaselineRefusal.CONFLICT_STATUS)
    # A withdraw belongs to the proposer's bucket or the operator.
    project.eligible.add("spub_q2")
    project.propose("spub_q2", UPDATE, "client-a")
    pending = project.on("spub_q2").baseline_id
    assert project.write(WithdrawRequest(pending, "client-b")) is BaselineRefusal.DENIED
    assert isinstance(project.write(WithdrawRequest(pending, None)), BaselinePlan)
    assert project.write(RejectRequest(pending)) is BaselineRefusal.CONFLICT_BASELINE_ID
    # A fresh proposal after a decision takes the next proposal ordinal.
    plan = project.propose("spub_q2", UPDATE, "client-a")
    assert isinstance(plan, BaselinePlan) and plan.proposal_ordinal == 1
    # Supersedes must name an approved baseline; governing CAS must match.
    project.eligible.add("spub_q3")
    assert (
        project.write(
            ApproveRequest(
                type=UPDATE,
                effective_from=EFFECTIVE,
                publication_id="spub_q3",
                supersedes_baseline_id=bl0,
            )
        )
        is BaselineRefusal.CONFLICT_BASELINE_ID
    )
    approved = project.write(
        ApproveRequest(type=UPDATE, effective_from=EFFECTIVE, publication_id="spub_q3")
    )
    assert isinstance(approved, BaselinePlan) and approved.label == "BL-1"
    bl1 = project.events[-1].baseline_id
    assert project.set_governing(bl1, "sbl_other") is BaselineRefusal.CONFLICT_GOVERNING
    assert isinstance(project.set_governing(bl1, None), BaselinePlan)
    assert project.set_governing(bl1, None) is BaselineRefusal.CONFLICT_GOVERNING
    assert project.set_governing(pending, bl1) is BaselineRefusal.CONFLICT_BASELINE_ID
    with pytest.raises(ValueError, match="exactly one"):
        project.write(ApproveRequest(type=UPDATE, effective_from=EFFECTIVE))


def test_pending_caps() -> None:
    project = Project(eligible={f"spub_c{index}" for index in range(60)})
    for index in range(MAX_PENDING_PER_BUCKET):
        assert isinstance(project.propose(f"spub_c{index}", UPDATE, "client-a"), BaselinePlan)
    assert (
        project.propose("spub_c10", UPDATE, "client-a") is BaselineRefusal.RATE_LIMITED_BASELINE_ID
    )
    for index in range(10, MAX_PENDING_PER_PROJECT):
        bucket = f"client-{index // MAX_PENDING_PER_BUCKET}"
        assert isinstance(project.propose(f"spub_c{index}", UPDATE, bucket), BaselinePlan)
    assert (
        project.propose("spub_c55", UPDATE, "client-z") is BaselineRefusal.RATE_LIMITED_BASELINE_ID
    )
    # The operator's direct approval is never blocked by a pending proposal.
    assert isinstance(
        project.write(
            ApproveRequest(type=CONTRACT, effective_from=EFFECTIVE, publication_id="spub_c55")
        ),
        BaselinePlan,
    )


def test_chains_must_be_gapless() -> None:
    event = BaselineEvent(2, "sbl_x", "spub_x", BaselineAction.PROPOSE, datetime(2027, 1, 1))
    with pytest.raises(ValueError, match="gaps"):
        baseline_status([event], eligible_publication_ids=())
    with pytest.raises(ValueError, match="gaps"):
        governing_baseline([GoverningEvent(2, "sbl_x", datetime(2027, 1, 1))])


def test_equal_recorded_times_resolve_by_seq() -> None:
    same = datetime(2027, 4, 1, 12, 0)
    chain: Iterable[GoverningEvent] = [
        GoverningEvent(1, "sbl_a", same),
        GoverningEvent(2, "sbl_b", same),
    ]
    assert governing_baseline(chain, as_of=same) == "sbl_b"
