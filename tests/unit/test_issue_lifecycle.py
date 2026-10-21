"""The S1 Issue state moves (`domain.situation.issue_lifecycle`, S1 contract 7.2)."""

from __future__ import annotations

import itertools

import pytest

from my_pa.domain.lineage.vocabulary import IssueRevisionAction
from my_pa.domain.situation.issue_lifecycle import (
    ISSUE_STATE_MOVES,
    IssueStateMoveError,
    issue_update_action,
)
from my_pa.domain.situation.situation import SituationState

OPEN = SituationState.OPEN
ACTIVE = SituationState.ACTIVE
SUSPENDED = SituationState.SUSPENDED
CLOSED = SituationState.CLOSED

#: Exactly the four edges section 7.2 admits.
ALLOWED = {
    (OPEN, ACTIVE): IssueRevisionAction.ACTIVATED,
    (SUSPENDED, ACTIVE): IssueRevisionAction.ACTIVATED,
    (OPEN, SUSPENDED): IssueRevisionAction.SUSPENDED,
    (ACTIVE, SUSPENDED): IssueRevisionAction.SUSPENDED,
}


@pytest.mark.parametrize(("current", "requested"), sorted(ALLOWED))
def test_allowed_state_moves(current: SituationState, requested: SituationState) -> None:
    assert issue_update_action(current, requested) is ALLOWED[(current, requested)]
    assert dict(ISSUE_STATE_MOVES) == ALLOWED


REFUSED = sorted(
    pair for pair in itertools.product(SituationState, SituationState) if pair not in ALLOWED
)


@pytest.mark.parametrize(("current", "requested"), REFUSED)
def test_refused_state_moves(current: SituationState, requested: SituationState) -> None:
    """Every other pair: a no-move, back to `open`, any `closed` (S2), from `closed`."""
    with pytest.raises(IssueStateMoveError):
        issue_update_action(current, requested)


@pytest.mark.parametrize("current", [OPEN, ACTIVE, SUSPENDED])
def test_update_action_follows_the_state_move(current: SituationState) -> None:
    """No state move is `updated`; a move is `activated` or `suspended`, never `updated`."""
    assert issue_update_action(current, None) is IssueRevisionAction.UPDATED
    for requested in (ACTIVE, SUSPENDED):
        if (current, requested) in ALLOWED:
            action = issue_update_action(current, requested)
            assert action is not IssueRevisionAction.UPDATED
            assert action.value == {ACTIVE: "activated", SUSPENDED: "suspended"}[requested]
    # A closed Issue does not exist in S1, so there is nothing to update.
    with pytest.raises(IssueStateMoveError):
        issue_update_action(CLOSED, None)
