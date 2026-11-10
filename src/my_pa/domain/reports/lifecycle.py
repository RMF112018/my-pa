"""The pure lifecycle rule of a general report: archive, delete, restore.

The legal transitions, and nothing else:

- archive: `active -> archived`; on `archived` it is a no-op;
- delete: `active -> trashed` and `archived -> trashed`, recording the state
  it trashed from;
- restore: `archived -> active`, and `trashed ->` the state the delete
  recorded (`active` or `archived`), so trashing an archived report and then
  restoring it brings back an archived report, not an active one.

Every other pair is a `ReportLifecycleRefusal`. The no-op is an *outcome*, not
an error: it writes no event, and a receipt records it as `no_op`. The WP01
lifecycle-event CHECKs restate this table; this function is the rule in one
place so the CHECK and the code can be compared rather than assumed equal.
"""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.domain.reports.errors import ReportLifecycleRefusal, ReportValidationError
from my_pa.domain.reports.vocabulary import LifecycleOperation, LifecycleState, ReceiptOutcome

__all__ = ["LifecycleDecision", "decide_lifecycle_transition"]

_ACTIVE = LifecycleState.ACTIVE
_ARCHIVED = LifecycleState.ARCHIVED
_TRASHED = LifecycleState.TRASHED


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    """What an operation does to a report in a given state.

    `outcome` is `APPLIED` when an event is to be written and `NO_OP` when the
    report is already where the operation would put it; for a no-op
    `resulting_state == prior_state`.
    """

    operation: LifecycleOperation
    outcome: ReceiptOutcome
    prior_state: LifecycleState
    resulting_state: LifecycleState


def decide_lifecycle_transition(
    state: LifecycleState,
    operation: LifecycleOperation,
    *,
    trashed_from: LifecycleState | None = None,
) -> LifecycleDecision:
    """Decide `operation` from `state`, or raise `ReportLifecycleRefusal`.

    `trashed_from` is the prior state the delete that trashed the report
    recorded. It is required exactly when `state` is `trashed` and must then
    be `active` or `archived`; anything else is a caller error, not a refusal.
    """
    if not isinstance(state, LifecycleState):
        raise ReportValidationError("lifecycle_state", "type")
    if not isinstance(operation, LifecycleOperation):
        raise ReportValidationError("lifecycle_operation", "type")
    if state is _TRASHED:
        if trashed_from not in (_ACTIVE, _ARCHIVED):
            raise ReportValidationError("trashed_from", "required")
    elif trashed_from is not None:
        raise ReportValidationError("trashed_from", "unexpected")

    def applied(resulting: LifecycleState) -> LifecycleDecision:
        return LifecycleDecision(operation, ReceiptOutcome.APPLIED, state, resulting)

    if operation is LifecycleOperation.ARCHIVE:
        if state is _ACTIVE:
            return applied(_ARCHIVED)
        if state is _ARCHIVED:
            return LifecycleDecision(operation, ReceiptOutcome.NO_OP, state, state)
    elif operation is LifecycleOperation.DELETE:
        if state is not _TRASHED:
            return applied(_TRASHED)
    elif state is _ARCHIVED:
        return applied(_ACTIVE)
    elif state is _TRASHED and trashed_from is not None:  # established above
        return applied(trashed_from)
    raise ReportLifecycleRefusal(state.value, operation.value)
