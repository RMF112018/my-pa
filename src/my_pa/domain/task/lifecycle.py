"""The Task lifecycle, priority, and scheduling model WP-TM-01 adds.

WP-11's `situation.continuity.Task` is a minimal continuity object: it shares
`OPEN`/`CLOSED` with `Commitment` and `Decision` because closing any of the
three on the same terms is what makes `continuity_lifecycle_events` one table
instead of three. That two-member vocabulary cannot say whether an open Task is
merely queued, actively being worked, waiting on somebody else, or blocked on
something else entirely — a distinction only Task needs, because only Task is
work the Principal executes step by step.

`TaskLifecycleState` is that finer vocabulary, and it is deliberately its own
type rather than a widening of `continuity.TaskState`: `Commitment` and
`Decision` keep the two-member model this module does not touch, and a shared
enum would force a widening neither of them asked for. `legacy_state_for` is the
one function that relates the two: every `TaskLifecycleState` maps to exactly
one legacy `open`/`closed` value, and `tables.py` restates the mapping as the
CHECK `a_task_lifecycle_state_matches_its_legacy_state` so the two columns
cannot drift at the server either.

`TaskPriority` is a Principal-assigned rank on the work itself. It is not, and
must never become, an attention-ranking output: nothing in this module reads a
derived score to set it, and nothing derives a score from it. The two are kept
separate for the same reason `§22` keeps relationship characterisation out of
`CommitmentDirection` — a ranking system with write access to the field it is
supposedly only reading from is not a ranking system a Principal can trust.

`scheduled_at`, `deferred_until`, and `archived_at` are orthogonal to lifecycle
state on purpose: a task can be scheduled, deferred, or archived in any
lifecycle state, and none of the three is itself a state transition. Archiving a
completed task does not reopen it, and scheduling a blocked one does not
unblock it — each is a separate fact recorded beside the lifecycle rather than
folded into it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "TERMINAL_TASK_LIFECYCLE_STATES",
    "TaskArchiveMode",
    "TaskLifecycleState",
    "TaskPriority",
    "TaskWorkView",
    "legacy_state_for",
]


class TaskLifecycleState(StrEnum):
    """Where a Task sits in its execution lifecycle.

    Six members. `OPEN` is queued but not yet started; `IN_PROGRESS` is being
    worked; `WAITING` and `BLOCKED` are both "not moving right now" but for
    different reasons a reader has to be able to tell apart — `WAITING` names
    time (a reply, a delivery) and `BLOCKED` names a dependency (another Task, a
    Decision, an external event) — and `COMPLETED`/`CANCELLED` are the two
    terminal states, kept apart because closing a Task by finishing it and
    closing it by abandoning it are different facts a reader of the history
    should not have to infer from context.
    """

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


#: The two lifecycle states that correspond to legacy `state = 'closed'`.
TERMINAL_TASK_LIFECYCLE_STATES: Final[frozenset[TaskLifecycleState]] = frozenset(
    {TaskLifecycleState.COMPLETED, TaskLifecycleState.CANCELLED}
)


class TaskPriority(StrEnum):
    """A Principal-assigned rank, separate from any derived attention ranking.

    Optional: a Task with no priority is not a Task the Principal has declined
    to rank low, it is a Task nobody has ranked at all, and the two must stay
    distinguishable.
    """

    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class TaskWorkView(StrEnum):
    """The server-owned Task sections admitted for the Work surface.

    Date-bounded members are evaluated against one validated civil day by the
    application service.  They remain query vocabulary, never stored Task
    state, and therefore cannot blur due, scheduled, or deferred semantics.
    """

    OVERDUE = "overdue"
    TODAY = "today"
    UPCOMING = "upcoming"
    UNSCHEDULED = "unscheduled"
    WAITING = "waiting"
    BLOCKED = "blocked"
    ALL_OPEN = "all-open"
    COMPLETED = "completed"
    RECENTLY_UPDATED = "recently-updated"


class TaskArchiveMode(StrEnum):
    """Whether a Work query returns active or archived Tasks, never a mixture."""

    EXCLUDE = "exclude"
    ONLY = "only"


def legacy_state_for(lifecycle_state: TaskLifecycleState) -> str:
    """The one `open`/`closed` value `lifecycle_state` corresponds to.

    The single source of truth `tables.py`'s CHECK restates and
    `tests/schema/test_task_schema_migration.py` checks against: every member
    maps to exactly one legacy value, so the two columns can be compared without
    either side guessing at the other's rule.
    """
    if lifecycle_state in TERMINAL_TASK_LIFECYCLE_STATES:
        return "closed"
    return "open"
