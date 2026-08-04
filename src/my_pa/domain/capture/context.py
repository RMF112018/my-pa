"""What a capture was launched from, and how firmly that link is held.

`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:106-124` describes a link
from a capture to another object, its role, and the authority under which it is
held. Three closed sets come out of it, and two of them have one member each in
this build.

**`ContextLinkTarget` — one member.**
`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:108` names nine kinds of
target: Situation, Project, Relationship, Organization, meeting, Decision,
Commitment, source, and "other object". Exactly one of them has a table in this
repository — a source object — so the other eight name nothing a foreign key
could reach. Project, Situation, Relationship and Organization are a later
package's. A member for a target that cannot exist would be a column value
nothing could write, which is the rule `capture_entity_mentions.resolution_state`
follows for the same reason.

**`ContextLinkRole` — one member.**
`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:116` names six roles, of
which five — `mentioned`, `about`, `resulted_in`, `supports`, `contradicts` —
require inference over the capture's text. `launch_context` is the one a
deterministic writer can record, because it is a fact about how the capture was
started rather than a claim about what it says. WP-8 resolves `O-15` and
`RI-OD-011`: deterministic launch context is the only automatically accepted
link, and inferred links remain proposed.

**`ContextLinkAuthority` — all five, and `superseded` is load-bearing.**
`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:117` gives the five, and
`:124` requires a unique *active* link per capture, target and role. "Active" is
unstatable without a way to say a link has been replaced, so dropping
`superseded` would drop the constraint with it. `rejected` is the other half of
`user_confirmed`: a reviewer who refuses a proposed link has to be able to say
so, and deleting the row instead would lose the lineage `QC-AC-022` protects.

The unique index is over capture, target and role and **not** over authority,
which is narrower than the specification's "per capture/target/role/authority".
Including authority would admit a `proposed` link and a `deterministic` link to
the same target at the same time, which is two answers to one question; the
narrower key is the one that makes supersession mean something, and the
specification qualifies its own list with "where appropriate".
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ContextLinkAuthority", "ContextLinkRole", "ContextLinkTarget"]


class ContextLinkTarget(StrEnum):
    """What a capture may be linked to. One member; see the module docstring."""

    SOURCE_OBJECT = "source_object"


class ContextLinkRole(StrEnum):
    """Why the link exists. One member; see the module docstring."""

    LAUNCH_CONTEXT = "launch_context"


class ContextLinkAuthority(StrEnum):
    """How firmly the link is held; this build writes deterministic links only."""

    DETERMINISTIC = "deterministic"
    USER_CONFIRMED = "user_confirmed"
    PROPOSED = "proposed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
