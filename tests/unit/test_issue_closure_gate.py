"""The pure S2 Issue rules: the closure gate, the Issue moves and the handoff chain.

S2 contract sections 3.3 and 3.4 (`domain.lineage.closure`,
`domain.situation.issue_lifecycle`, `domain.lineage.handoff`). No clock, no
persistence: every case is a value in and an answer out. Every identifier is
synthetic.
"""

from __future__ import annotations

import pytest

from my_pa.domain.lineage.closure import (
    MemberNativeFacts,
    MembershipHeadEvidence,
    has_resolution_anchor,
    member_blockers,
)
from my_pa.domain.lineage.handoff import HandoffHolder, HandoffSideError, resolve_handoff
from my_pa.domain.lineage.model import EvidenceAnchor
from my_pa.domain.lineage.vocabulary import (
    MANDATORY_MEMBER_ROLES,
    EvidenceAvailability,
    EvidenceRole,
    EvidenceSourceFamily,
    HandoffHolderKind,
    HandoffSide,
    IssueClosureBlocker,
    IssueRevisionAction,
    MemberRole,
    RecordFamily,
    SourceVersionKind,
)
from my_pa.domain.situation.issue_lifecycle import (
    IssueStateMoveError,
    issue_close_action,
    issue_correction_action,
    issue_reopen_action,
    issue_update_action,
)
from my_pa.domain.situation.situation import SituationState

B = IssueClosureBlocker
DIGEST = "a" * 64


def _note(role: EvidenceRole, *, number: int = 1) -> EvidenceAnchor:
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily.MEETING_NOTE_VERSION,
        source_root_id="mtg_closuregate0001",
        source_version_kind=SourceVersionKind.IMMUTABLE_VERSION,
        source_version_id=f"mnote_closuregate000{number}",
        source_version_no=number,
        source_sha256=DIGEST,
        passage_start_cp=None,
        passage_end_cp=None,
        passage_sha256=None,
        role=role,
    )


def _capture(role: EvidenceRole) -> EvidenceAnchor:
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily.CAPTURE_VERSION,
        source_root_id="cap_closuregate0001",
        source_version_kind=SourceVersionKind.IMMUTABLE_VERSION,
        source_version_id="capver_closuregate0001",
        source_version_no=1,
        source_sha256=DIGEST,
        passage_start_cp=None,
        passage_end_cp=None,
        passage_sha256=None,
        role=role,
    )


def _legacy(role: EvidenceRole) -> EvidenceAnchor:
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily.CAPTURE,
        source_root_id="cap_closuregate0002",
        source_version_kind=SourceVersionKind.LEGACY_UNVERSIONED,
        source_version_id=None,
        source_version_no=None,
        source_sha256=None,
        passage_start_cp=None,
        passage_end_cp=None,
        passage_sha256=None,
        role=role,
    )


def _available(anchor: EvidenceAnchor) -> EvidenceAvailability:
    del anchor
    return EvidenceAvailability.AVAILABLE


def _archived_captures(anchor: EvidenceAnchor) -> EvidenceAvailability:
    if anchor.source_family is EvidenceSourceFamily.MEETING_NOTE_VERSION:
        return EvidenceAvailability.AVAILABLE
    return EvidenceAvailability.ARCHIVED


PROVEN = MembershipHeadEvidence(anchors=(_note(EvidenceRole.RESOLUTION),), member_native_version=3)


def _facts(family: RecordFamily, state: str, evidence: str | None = None) -> MemberNativeFacts:
    return MemberNativeFacts(family=family, native_state=state, evidence_state=evidence, version=3)


def test_mandatory_roles_are_work_and_constraint() -> None:
    assert frozenset({MemberRole.WORK, MemberRole.CONSTRAINT}) == MANDATORY_MEMBER_ROLES
    assert set(MemberRole) - MANDATORY_MEMBER_ROLES == {
        MemberRole.ORIGIN_EVIDENCE,
        MemberRole.DISCUSSION,
        MemberRole.SUPPORTING_EVIDENCE,
        MemberRole.REFERENCE,
    }
    # The blockers are declared in the order the gate reports them.
    assert [blocker.value for blocker in B] == [
        "native_open",
        "native_terminal_unsuccessful",
        "native_not_accepted",
        "role_family_not_closable",
        "resolution_evidence_missing",
        "resolution_evidence_unavailable",
        "resolution_evidence_contradicted",
        "resolution_evidence_stale",
    ]


@pytest.mark.parametrize(
    ("family", "state", "evidence", "expected"),
    [
        (RecordFamily.TASK, "completed", "accepted", ()),
        (RecordFamily.TASK, "open", "accepted", (B.NATIVE_OPEN,)),
        (RecordFamily.TASK, "in_progress", "accepted", (B.NATIVE_OPEN,)),
        (RecordFamily.TASK, "waiting", "accepted", (B.NATIVE_OPEN,)),
        (RecordFamily.TASK, "blocked", "accepted", (B.NATIVE_OPEN,)),
        (RecordFamily.TASK, "cancelled", "accepted", (B.NATIVE_TERMINAL_UNSUCCESSFUL,)),
        (RecordFamily.TASK, "completed", "proposed", (B.NATIVE_NOT_ACCEPTED,)),
        (RecordFamily.TASK, "open", "proposed", (B.NATIVE_OPEN, B.NATIVE_NOT_ACCEPTED)),
        (RecordFamily.COMMITMENT, "closed", "accepted", ()),
        (RecordFamily.COMMITMENT, "open", "accepted", (B.NATIVE_OPEN,)),
        (RecordFamily.COMMITMENT, "closed", "proposed", (B.NATIVE_NOT_ACCEPTED,)),
        (RecordFamily.CONSTRAINT, "closed", None, ()),
        (RecordFamily.CONSTRAINT, "draft", None, (B.NATIVE_OPEN,)),
        (RecordFamily.CONSTRAINT, "identified", None, (B.NATIVE_OPEN,)),
        (RecordFamily.CONSTRAINT, "on_hold", None, (B.NATIVE_OPEN,)),
        (RecordFamily.CONSTRAINT, "void", None, (B.NATIVE_TERMINAL_UNSUCCESSFUL,)),
        (RecordFamily.MEETING, "scheduled", None, (B.ROLE_FAMILY_NOT_CLOSABLE,)),
        (RecordFamily.CAPTURE_VERSION, "", None, (B.ROLE_FAMILY_NOT_CLOSABLE,)),
    ],
)
def test_member_blockers_by_family_and_state(
    family: RecordFamily,
    state: str,
    evidence: str | None,
    expected: tuple[IssueClosureBlocker, ...],
) -> None:
    head = PROVEN
    if family not in (RecordFamily.TASK, RecordFamily.COMMITMENT, RecordFamily.CONSTRAINT):
        # Other families record no member version.
        head = MembershipHeadEvidence(anchors=PROVEN.anchors, member_native_version=None)
        facts = MemberNativeFacts(
            family=family, native_state=state, evidence_state=None, version=None
        )
    else:
        facts = _facts(family, state, evidence)
    assert member_blockers(facts, head, _available) == expected


def test_resolution_evidence_rules() -> None:
    done = _facts(RecordFamily.TASK, "completed", "accepted")

    def blockers(
        *anchors: EvidenceAnchor, version: int | None = 3, archived: bool = False
    ) -> tuple[IssueClosureBlocker, ...]:
        head = MembershipHeadEvidence(anchors=anchors, member_native_version=version)
        return member_blockers(done, head, _archived_captures if archived else _available)

    assert blockers(_note(EvidenceRole.RESOLUTION)) == ()
    assert blockers() == (B.RESOLUTION_EVIDENCE_MISSING,)
    # Only `resolution` counts; any other role is no proof.
    assert blockers(_note(EvidenceRole.CORROBORATES)) == (B.RESOLUTION_EVIDENCE_MISSING,)
    # A legacy root never satisfies anything.
    assert blockers(_legacy(EvidenceRole.CORROBORATES)) == (B.RESOLUTION_EVIDENCE_MISSING,)
    assert not has_resolution_anchor((_legacy(EvidenceRole.CORROBORATES),))
    # Every resolution anchor archived: unavailable; one still available: satisfied.
    assert blockers(_capture(EvidenceRole.RESOLUTION), archived=True) == (
        B.RESOLUTION_EVIDENCE_UNAVAILABLE,
    )
    assert (
        blockers(_capture(EvidenceRole.RESOLUTION), _note(EvidenceRole.RESOLUTION), archived=True)
        == ()
    )
    # Any contradicting anchor blocks, even beside a resolution.
    assert blockers(_note(EvidenceRole.RESOLUTION), _note(EvidenceRole.CONTRADICTS, number=2)) == (
        B.RESOLUTION_EVIDENCE_CONTRADICTED,
    )
    # The evidence is bound to the native version it was recorded against.
    assert blockers(_note(EvidenceRole.RESOLUTION), version=2) == (B.RESOLUTION_EVIDENCE_STALE,)
    assert blockers(_note(EvidenceRole.RESOLUTION), version=None) == (B.RESOLUTION_EVIDENCE_STALE,)
    # Every failing condition is reported, in the declared order.
    open_task = _facts(RecordFamily.TASK, "open", "proposed")
    assert member_blockers(
        open_task,
        MembershipHeadEvidence(anchors=(_note(EvidenceRole.CONTRADICTS),), member_native_version=1),
        _available,
    ) == (
        B.NATIVE_OPEN,
        B.NATIVE_NOT_ACCEPTED,
        B.RESOLUTION_EVIDENCE_MISSING,
        B.RESOLUTION_EVIDENCE_CONTRADICTED,
        B.RESOLUTION_EVIDENCE_STALE,
    )


def test_close_reopen_and_correct_moves() -> None:
    open_states = (SituationState.OPEN, SituationState.ACTIVE, SituationState.SUSPENDED)
    for state in open_states:
        assert issue_close_action(state) is IssueRevisionAction.CLOSED
        with pytest.raises(IssueStateMoveError):
            issue_reopen_action(state)
        with pytest.raises(IssueStateMoveError):
            issue_correction_action(state, None)
    with pytest.raises(IssueStateMoveError):
        issue_close_action(SituationState.CLOSED)
    assert issue_reopen_action(SituationState.CLOSED) is IssueRevisionAction.REOPENED
    assert issue_correction_action(SituationState.CLOSED, None) is IssueRevisionAction.CORRECTED
    # A correction names no state; `issues.update` never moves a closed Issue.
    for requested in SituationState:
        with pytest.raises(IssueStateMoveError):
            issue_correction_action(SituationState.CLOSED, requested)
        with pytest.raises(IssueStateMoveError):
            issue_update_action(SituationState.CLOSED, requested)
        with pytest.raises(IssueStateMoveError):
            issue_update_action(SituationState.OPEN, SituationState.CLOSED)


def test_handoff_holders_follow_the_chain_and_the_current_counterparty() -> None:
    principal = HandoffHolder(kind=HandoffHolderKind.PRINCIPAL)
    p1 = HandoffHolder(kind=HandoffHolderKind.ENTITY, entity_id="ent_handoffgate0001")
    p1b = HandoffHolder(kind=HandoffHolderKind.ENTITY, entity_id="ent_handoffgate0002")
    # Event 1: the side named is the leaving holder; the other side arrives.
    assert resolve_handoff(
        HandoffSide.COUNTERPARTY, last_holder=None, counterparty_entity_id=p1.entity_id or ""
    ) == (p1, principal)
    assert resolve_handoff(
        HandoffSide.PRINCIPAL, last_holder=None, counterparty_entity_id=p1.entity_id or ""
    ) == (principal, p1)
    # Event n > 1 leaves the chain's last holder; naming the other side is refused.
    assert resolve_handoff(
        HandoffSide.PRINCIPAL, last_holder=principal, counterparty_entity_id="ent_handoffgate0001"
    ) == (principal, p1)
    with pytest.raises(HandoffSideError):
        resolve_handoff(
            HandoffSide.COUNTERPARTY,
            last_holder=principal,
            counterparty_entity_id="ent_handoffgate0001",
        )
    # A counterparty re-pointed P1 -> P1' never wedges the chain: P1 still holds
    # and can only leave; once the Principal holds, P1' is who arrives.
    assert resolve_handoff(
        HandoffSide.COUNTERPARTY, last_holder=p1, counterparty_entity_id="ent_handoffgate0002"
    ) == (p1, principal)
    assert resolve_handoff(
        HandoffSide.PRINCIPAL, last_holder=principal, counterparty_entity_id="ent_handoffgate0002"
    ) == (principal, p1b)
    with pytest.raises(ValueError, match="names no Entity"):
        HandoffHolder(kind=HandoffHolderKind.PRINCIPAL, entity_id="ent_handoffgate0001")
