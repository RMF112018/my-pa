"""The Pulse explains why-now, and is structurally incapable of being a feed.

FAST tier, over the pure derivation. `derive_pulse` takes rows and a moment and
returns items; nothing here opens a connection, so what is asserted is the
*rule*, not the query. The query's half — the `principal_id` and
`evidence_state = 'accepted'` predicates — is asserted against a live server in
`tests/database/test_continuity_isolation.py`, and neither tier is sufficient
alone.

**The distinction this module exists to make real.** "Not an activity feed" is
easy to write in a docstring and hard to fail. It is failed here three ways:

* an accepted object that is *merely recent* — created a moment ago, with no due
  moment, no named authority point and no unmet obligation — must not appear at
  all;
* recency ordering and urgency ordering are made to **disagree**, and urgency has
  to win;
* every item that does appear has to carry a closed reason code and a non-empty
  basis, so "why am I seeing this" is answerable by opening rows.

**§22.** One test constructs two commitments identical in every evidentiary
respect and differing only in counterparty, and requires the ranks to be equal:
nothing here may score a person.

Every identifier and every string is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.situation.continuity import (
    Commitment,
    CommitmentDirection,
    CommitmentState,
    ContinuityEvidenceState,
    Decision,
    DecisionState,
    Task,
    TaskState,
)
from my_pa.domain.situation.pulse_derivation import (
    DUE_SOON_WINDOW,
    FramedObligation,
    derive_pulse,
)
from my_pa.domain.situation.situation import PulseReasonCode

PRINCIPAL_A = "prn_aaaa0001aaaa0001aaaa0001"
COUNTERPARTY_ONE = "per_counterparty0001aaaa"
COUNTERPARTY_TWO = "per_counterparty0002bbbb"

NOW = datetime(2026, 8, 10, 12, tzinfo=UTC)

#: A synthetic evidence reference of the shape a real origin carries.
ORIGIN = "cap_origin0001origin0001"


def _commitment(
    identifier: str,
    *,
    due_at: datetime | None,
    created_at: datetime,
    counterparty: str = COUNTERPARTY_ONE,
    evidence_state: ContinuityEvidenceState = ContinuityEvidenceState.ACCEPTED,
) -> Commitment:
    review = "rdec_review0001review0001"
    return Commitment(
        commitment_id=identifier,
        principal_id=PRINCIPAL_A,
        counterparty_person_id=counterparty,
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send Sample Counterparty the revised figure",
        state=CommitmentState.OPEN,
        evidence_state=evidence_state,
        origin_evidence_ref=ORIGIN,
        opened_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        due_at=due_at,
        accepted_by_review_decision_id=(
            review if evidence_state is ContinuityEvidenceState.ACCEPTED else None
        ),
    )


def _task(identifier: str, *, due_at: datetime | None, created_at: datetime) -> Task:
    return Task(
        task_id=identifier,
        principal_id=PRINCIPAL_A,
        title="Draft the synthetic summary",
        state=TaskState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_evidence_ref=ORIGIN,
        opened_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        due_at=due_at,
        accepted_by_review_decision_id="rdec_review0001review0001",
    )


def _decision(identifier: str, *, authority: str | None, created_at: datetime) -> Decision:
    return Decision(
        decision_id=identifier,
        principal_id=PRINCIPAL_A,
        question="Which synthetic option is taken",
        state=DecisionState.OPEN,
        evidence_state=ContinuityEvidenceState.ACCEPTED,
        origin_evidence_ref=ORIGIN,
        opened_at=created_at,
        created_at=created_at,
        updated_at=created_at,
        awaiting_authority_ref=authority,
        accepted_by_review_decision_id="rdec_review0001review0001",
    )


def test_an_object_that_is_merely_recent_does_not_appear() -> None:
    """The whole distinction, as one assertion.

    Three accepted objects, all created seconds ago, none carrying a why-now
    condition: a commitment with no due moment, a task with no due moment, and a
    decision waiting on nothing. A feed would show all three, because all three
    just happened. The Pulse shows none, because there is nothing to say about
    them today.
    """
    items = derive_pulse(
        principal_id=PRINCIPAL_A,
        now=NOW,
        commitments=[_commitment("cmt_recent0001recent0001", due_at=None, created_at=NOW)],
        tasks=[_task("tsk_recent0001recent0001", due_at=None, created_at=NOW)],
        decisions=[_decision("cdec_recent0001recent001", authority=None, created_at=NOW)],
    )
    assert items == ()


def test_urgency_wins_where_recency_and_urgency_disagree() -> None:
    """The ordering claim, constructed so the two orders cannot coincide.

    `newest` was created one minute ago and is due in three hours — real, and not
    yet a failure. `oldest` was created forty days ago and passed its agreed
    moment ten days ago. Reverse-chronological ordering by *any* of the three
    timestamps a feed would reach for — created, updated, or due — puts `newest`
    first. Evidentiary urgency puts `oldest` first, and that is what is asserted.
    """
    newest = _commitment(
        "cmt_newest0001newest0001",
        due_at=NOW + timedelta(hours=3),
        created_at=NOW - timedelta(minutes=1),
    )
    oldest = _commitment(
        "cmt_oldest0001oldest0001",
        due_at=NOW - timedelta(days=10),
        created_at=NOW - timedelta(days=40),
    )

    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[newest, oldest])

    assert [item.item_ref for item in items] == [oldest.commitment_id, newest.commitment_id]
    # And the disagreement is real rather than asserted: every recency key a feed
    # could sort on ranks them the other way round.
    by_created = sorted(
        (newest, oldest), key=lambda commitment: commitment.created_at, reverse=True
    )
    assert [commitment.commitment_id for commitment in by_created] == [
        newest.commitment_id,
        oldest.commitment_id,
    ]


def test_a_further_passed_moment_outranks_a_recently_passed_one() -> None:
    """Escalation is evidentiary: how far past due, not how recently touched."""
    slightly = _commitment(
        "cmt_slight0001slight0001",
        due_at=NOW - timedelta(hours=2),
        created_at=NOW - timedelta(days=1),
    )
    badly = _commitment(
        "cmt_badly00001badly00001",
        due_at=NOW - timedelta(days=45),
        created_at=NOW - timedelta(days=60),
    )
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[slightly, badly])
    assert [item.item_ref for item in items] == [badly.commitment_id, slightly.commitment_id]
    assert items[0].attention_rank > items[1].attention_rank


def test_generated_at_is_identical_on_every_item_so_it_cannot_order_them() -> None:
    """A structural reason recency ordering is unavailable, not merely unused."""
    items = derive_pulse(
        principal_id=PRINCIPAL_A,
        now=NOW,
        commitments=[
            _commitment(
                "cmt_first00001first00001",
                due_at=NOW - timedelta(days=1),
                created_at=NOW - timedelta(days=9),
            ),
            _commitment(
                "cmt_second0001second0001",
                due_at=NOW + timedelta(hours=1),
                created_at=NOW - timedelta(days=2),
            ),
        ],
        tasks=[
            _task(
                "tsk_third00001third00001",
                due_at=NOW - timedelta(days=3),
                created_at=NOW - timedelta(days=4),
            )
        ],
    )
    assert len(items) == 3
    assert {item.generated_at for item in items} == {NOW}


def test_every_derived_item_names_a_reason_and_cites_a_basis() -> None:
    """No item without a why-now and something to open. The domain half."""
    items = derive_pulse(
        principal_id=PRINCIPAL_A,
        now=NOW,
        commitments=[
            _commitment(
                "cmt_basis00001basis00001",
                due_at=NOW - timedelta(days=2),
                created_at=NOW - timedelta(days=5),
            )
        ],
        decisions=[
            _decision(
                "cdec_basis0001basis0001",
                authority="rvw_authority0001authority",
                created_at=NOW - timedelta(days=5),
            )
        ],
        obligations=[
            FramedObligation(
                situation_id="sit_basis00001basis00001",
                frame_id="frm_basis00001basis00001",
                obligation_count=2,
            )
        ],
    )
    assert len(items) == 3
    for item in items:
        assert isinstance(item.reason_code, PulseReasonCode)
        assert item.basis_refs
        assert all(reference.strip() for reference in item.basis_refs)
        assert item.consequence and item.next_step
        assert item.principal_id == PRINCIPAL_A


def test_a_decision_with_no_named_authority_point_produces_nothing() -> None:
    """ "You have an open decision" is a listing, and a listing is not a Pulse."""
    blocked = _decision(
        "cdec_blocked001blocked01",
        authority="rvw_authority0001authority",
        created_at=NOW - timedelta(days=3),
    )
    idle = _decision("cdec_idle00001idle00001x", authority=None, created_at=NOW)
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, decisions=[blocked, idle])
    assert [item.item_ref for item in items] == [blocked.decision_id]
    assert items[0].reason_code is PulseReasonCode.DECISION_AWAITING_AUTHORITY


def test_a_due_moment_beyond_the_window_is_not_yet_a_reason() -> None:
    """The window is a bound with a number, not a mood."""
    inside = _commitment(
        "cmt_inside0001inside0001",
        due_at=NOW + DUE_SOON_WINDOW - timedelta(minutes=1),
        created_at=NOW,
    )
    outside = _commitment(
        "cmt_outside001outside001",
        due_at=NOW + DUE_SOON_WINDOW + timedelta(minutes=1),
        created_at=NOW,
    )
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[inside, outside])
    assert [item.item_ref for item in items] == [inside.commitment_id]


def test_a_commitment_outranks_a_task_in_the_same_condition() -> None:
    """The type distinction is load-bearing: somebody else is waiting on one of them."""
    commitment = _commitment(
        "cmt_pair000001pair000001", due_at=NOW - timedelta(hours=1), created_at=NOW
    )
    task = _task("tsk_pair000001pair000001", due_at=NOW - timedelta(hours=1), created_at=NOW)
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[commitment], tasks=[task])
    assert [item.item_ref for item in items] == [commitment.commitment_id, task.task_id]


def test_the_counterparty_does_not_change_the_rank() -> None:
    """§22: nothing here scores a person.

    Two commitments identical in every evidentiary respect and differing only in
    who they are owed to. If any relationship weight existed anywhere in this
    derivation, these two ranks would differ. They do not, and the order between
    them falls back to the identifier rather than to anything about the people.
    """
    one = _commitment(
        "cmt_person0001person0001",
        due_at=NOW - timedelta(days=2),
        created_at=NOW - timedelta(days=5),
        counterparty=COUNTERPARTY_ONE,
    )
    two = _commitment(
        "cmt_person0002person0002",
        due_at=NOW - timedelta(days=2),
        created_at=NOW - timedelta(days=5),
        counterparty=COUNTERPARTY_TWO,
    )
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[one, two])
    assert len(items) == 2
    assert items[0].attention_rank == items[1].attention_rank
    assert [item.item_ref for item in items] == [one.commitment_id, two.commitment_id]


def test_a_dismissed_item_stays_dismissed_across_reads() -> None:
    """The derived identifier is deterministic, which is what makes dismissal stick."""
    commitment = _commitment(
        "cmt_dismiss001dismiss001", due_at=NOW - timedelta(days=1), created_at=NOW
    )
    first = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[commitment])
    assert len(first) == 1
    again = derive_pulse(
        principal_id=PRINCIPAL_A, now=NOW + timedelta(hours=1), commitments=[commitment]
    )
    assert [item.pulse_id for item in again] == [first[0].pulse_id]
    after = derive_pulse(
        principal_id=PRINCIPAL_A,
        now=NOW,
        commitments=[commitment],
        dismissed_pulse_ids=frozenset({first[0].pulse_id}),
    )
    assert after == ()


def test_the_derivation_returns_one_principals_items_only() -> None:
    """It is handed one Principal's rows and stamps that Principal on every item.

    The partition itself is the query's — see the database tier — but this is the
    other half: the derivation has no path by which a second Principal's
    identifier could reach an item, because it takes one.
    """
    items = derive_pulse(
        principal_id=PRINCIPAL_A,
        now=NOW,
        commitments=[
            _commitment("cmt_stamp00001stamp00001", due_at=NOW - timedelta(days=1), created_at=NOW)
        ],
    )
    assert {item.principal_id for item in items} == {PRINCIPAL_A}


def test_task_backed_pulse_items_carry_subject_title_and_state() -> None:
    """F-001: Task-derived PulseItems carry subject_title and subject_state."""
    task = _task(
        "tsk_enrich001enrich0001",
        due_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=3),
    )
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, tasks=[task])
    assert len(items) == 1
    item = items[0]
    assert item.subject_title == "Draft the synthetic summary"
    assert item.subject_state == "open"
    assert item.subject_version is None
    assert item.subject_priority is None


def test_non_task_pulse_items_have_no_subject_fields() -> None:
    """Non-Task PulseItems leave subject fields as None."""
    commitment = _commitment(
        "cmt_nosubj001nosubj0001",
        due_at=NOW - timedelta(days=1),
        created_at=NOW - timedelta(days=3),
    )
    items = derive_pulse(principal_id=PRINCIPAL_A, now=NOW, commitments=[commitment])
    assert len(items) == 1
    item = items[0]
    assert item.subject_title is None
    assert item.subject_state is None
    assert item.subject_version is None
    assert item.subject_priority is None


def test_a_framed_obligation_must_stand_for_at_least_one_obligation() -> None:
    """Guards the obligation rule against a zero-count row producing an item."""
    with pytest.raises(ValueError, match="at least one obligation"):
        FramedObligation(
            situation_id="sit_zero00001zero00001aa",
            frame_id="frm_zero00001zero00001aa",
            obligation_count=0,
        )
