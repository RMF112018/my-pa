"""The Issue state moves of record lineage Slice S1 (S1 contract sections 3 and 7.2).

An Issue is a `situations` row of kind `issue_workstream`. S1 admits three of
`SituationState`'s members on an Issue -- `open`, `active` and `suspended` --
and no close or reopen (S2). `issues.update` may move the state along exactly
these edges:

* `open -> active` and `suspended -> active`, recorded as `activated`;
* `open -> suspended` and `active -> suspended`, recorded as `suspended`;

and a request that names no state move is recorded as `updated`. Every other
pair -- naming the state the Issue is already in, moving back to `open`, or
naming `closed` -- is refused with `IssueStateMoveError`, which the application
reports as `invalid_request` / `state`.

Pure: no clock, no persistence, no identifiers.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from my_pa.domain.lineage.vocabulary import IssueRevisionAction
from my_pa.domain.situation.situation import SituationState

__all__ = [
    "ISSUE_STATE_MOVES",
    "IssueStateMoveError",
    "issue_update_action",
]

#: Every admitted `(from, to)` state move and the revision action it records.
ISSUE_STATE_MOVES: Final[
    MappingProxyType[tuple[SituationState, SituationState], IssueRevisionAction]
] = MappingProxyType(
    {
        (SituationState.OPEN, SituationState.ACTIVE): IssueRevisionAction.ACTIVATED,
        (SituationState.SUSPENDED, SituationState.ACTIVE): IssueRevisionAction.ACTIVATED,
        (SituationState.OPEN, SituationState.SUSPENDED): IssueRevisionAction.SUSPENDED,
        (SituationState.ACTIVE, SituationState.SUSPENDED): IssueRevisionAction.SUSPENDED,
    }
)

#: The Issue states S1 holds on a stored Issue.
_ISSUE_STATES: Final = frozenset(
    {SituationState.OPEN, SituationState.ACTIVE, SituationState.SUSPENDED}
)


class IssueStateMoveError(ValueError):
    """An `issues.update` named a state move S1 does not admit."""


def issue_update_action(
    current: SituationState, requested: SituationState | None
) -> IssueRevisionAction:
    """The revision action an `issues.update` records, or a refusal.

    `requested` is `None` when the request names no state; the action is then
    `updated` (the caller has already checked that something else changes).
    """
    if current not in _ISSUE_STATES:
        raise IssueStateMoveError("an Issue in S1 is open, active or suspended")
    if requested is None:
        return IssueRevisionAction.UPDATED
    action = ISSUE_STATE_MOVES.get((current, requested))
    if action is None:
        raise IssueStateMoveError("S1 does not admit this Issue state move")
    return action
