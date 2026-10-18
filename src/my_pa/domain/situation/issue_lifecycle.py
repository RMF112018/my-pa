"""The Issue state moves of record lineage (S1 contract 3 and 7.2, S2 contract 3.3 and 7.2).

An Issue is a `situations` row of kind `issue_workstream`. S1 admits three of
`SituationState`'s members on an Issue -- `open`, `active` and `suspended`;
S2 admits `closed`. `issues.update` may move a non-closed Issue's state along
exactly these edges:

* `open -> active` and `suspended -> active`, recorded as `activated`;
* `open -> suspended` and `active -> suspended`, recorded as `suspended`;

and a request that names no state move is recorded as `updated`. Every other
pair -- naming the state the Issue is already in, moving back to `open`, or
naming `closed` -- is refused with `IssueStateMoveError`, which the application
reports as `invalid_request` / `state`.

S2 adds three moves, each its own write:

* `issues.close` moves a non-closed Issue to `closed`, recorded as `closed`
  (`issue_close_action`);
* `issues.reopen` moves a closed Issue to `active`, recorded as `reopened`
  (`issue_reopen_action`);
* an `issues.update` of a closed Issue names no state and keeps it closed,
  recorded as `corrected` (`issue_correction_action`; `issue_update_action`
  still refuses a closed Issue, which it never moves).

A close of a closed Issue and a reopen of a non-closed one raise
`IssueStateMoveError`, which the application reports as `conflict` / `state`.

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
    "issue_close_action",
    "issue_correction_action",
    "issue_reopen_action",
    "issue_update_action",
]

#: Every admitted `issues.update` `(from, to)` state move and the action it records.
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

#: The non-closed Issue states.
_OPEN_ISSUE_STATES: Final = frozenset(
    {SituationState.OPEN, SituationState.ACTIVE, SituationState.SUSPENDED}
)


class IssueStateMoveError(ValueError):
    """A write named an Issue state move that is not admitted."""


def issue_update_action(
    current: SituationState, requested: SituationState | None
) -> IssueRevisionAction:
    """The revision action an `issues.update` records, or a refusal.

    `requested` is `None` when the request names no state; the action is then
    `updated` (the caller has already checked that something else changes). A
    closed Issue is refused here: its update is a correction
    (`issue_correction_action`).
    """
    if current not in _OPEN_ISSUE_STATES:
        raise IssueStateMoveError("issues.update moves only an open, active or suspended Issue")
    if requested is None:
        return IssueRevisionAction.UPDATED
    action = ISSUE_STATE_MOVES.get((current, requested))
    if action is None:
        raise IssueStateMoveError("issues.update does not admit this Issue state move")
    return action


def issue_correction_action(
    current: SituationState, requested: SituationState | None
) -> IssueRevisionAction:
    """`corrected`, for an `issues.update` of a closed Issue that names no state."""
    if current is not SituationState.CLOSED:
        raise IssueStateMoveError("only a closed Issue is corrected")
    if requested is not None:
        raise IssueStateMoveError("a closed Issue changes state only by issues.reopen")
    return IssueRevisionAction.CORRECTED


def issue_close_action(current: SituationState) -> IssueRevisionAction:
    """`closed`, for an Issue that is open, active or suspended; else a refusal."""
    if current not in _OPEN_ISSUE_STATES:
        raise IssueStateMoveError("only an open, active or suspended Issue closes")
    return IssueRevisionAction.CLOSED


def issue_reopen_action(current: SituationState) -> IssueRevisionAction:
    """`reopened`, for a closed Issue; else a refusal. A reopened Issue is `active`."""
    if current is not SituationState.CLOSED:
        raise IssueStateMoveError("only a closed Issue reopens")
    return IssueRevisionAction.REOPENED
