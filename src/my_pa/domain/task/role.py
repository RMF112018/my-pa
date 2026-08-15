"""`TaskRole`: the closed vocabulary of roles a Task may additionally carry.

WP-TM-05. A Task is still the one canonical work-item type WP-TM-01 built; a
role is not a second kind of Task, it is an optional tag naming a purpose a
particular Task instance serves beyond ordinary work. `FOLLOW_UP` is the one
member this package needs: the operator-approved scope for WP-TM-05 asks for
"Follow-Up represented as a canonical Task role, not a separate root entity",
and this is that role, nothing more. No other member is added speculatively —
`AGENTS.md`'s minimal-implementation rule applies to this vocabulary exactly as
it applies to every other one in this codebase.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["TaskRole"]


class TaskRole(StrEnum):
    """A purpose a Task additionally serves, beyond ordinary work.

    One member. `FOLLOW_UP` names a Task whose point is checking back on a
    `Commitment` this Principal is owed — typically linked to one via
    `Task.commitment_id` — rather than a second, competing "follow-up" entity.
    """

    FOLLOW_UP = "follow_up"
