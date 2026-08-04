"""The state a conversation event holds, and the channel it arrived on.

**`ConversationState` — all five of
`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:211`**, including `archived`.
`skeletal` is reachable now: an explicit Conversation Log seeds it. `proposed`
needs a conversation inferred from a Quick Note, which this build does not
perform; `accepted` needs review of such an inference; `superseded` needs a
later conversation writer; and `archived` needs a retention rule, which `O-10`
has not decided. All five are
declared because the set is the specification's vocabulary of one object, and a
later package that reaches one must not have to widen a frozen constraint to say
so.

**`ConversationChannel` — one member.**
`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:212` describes the field as a
controlled enum plus `unknown`, and does not enumerate the controlled part.
Nothing deterministic in this build can yield a channel: a typed capture arrives
over the local transport whatever the conversation it records happened on, so
inventing `email` or `meeting` here would be a value nobody could write
truthfully. `unknown` is the honest answer, and
`09_LOGICAL_DATA_MODEL.md:224` requires it to be available anyway — an explicit
Conversation Log may be seeded "with unknown channel/time/participants". The
controlled members arrive with the package that can distinguish them, as a
forward `ALTER`.

**Absent rather than declared and unreachable**: `accepted_summary` and
`summary_authority_state` (`09_LOGICAL_DATA_MODEL.md:218-219`) need a model, and
`P00-OD-006` is open, so the columns could hold nothing. `occurred_at_precision`,
`duration_seconds`, `location_text` and `sensitivity` are absent on the same
terms. `mode_source` (`09_LOGICAL_DATA_MODEL.md:65`) names four values of which
one — an explicit route — is reachable, so it would be a column that always says
the same thing.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ConversationChannel", "ConversationState"]


class ConversationState(StrEnum):
    """The five the specification names. One is reachable; see the module docstring."""

    SKELETAL = "skeletal"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class ConversationChannel(StrEnum):
    """How the conversation happened. One member; see the module docstring."""

    UNKNOWN = "unknown"
