"""One dated event on a Person's relationship timeline.

A `RelationshipEvent` is a time- and context-aware association event — an
interaction, a meeting, a reciprocal commitment, a private observation, an
affiliation change, or a project link — recorded against one already-resolved
Person. It is the durable substrate the relationship briefing (WF-10) and the
Project/Relationship timeline (WF-12) read, and it lives in the relationship
domain rather than the continuity (`situation`) package because it is a fact
*about a Person*, not a view or a workspace.

**`accepted` gates timeline visibility, and it starts false.** Invariant 5 of
the canonical model — "no timeline entry presents a proposal as accepted" —
means a derived or proposed event must be legible *as proposed* and must never
be read as an accepted relationship fact. Today/Pulse read only accepted
records (the WP-06 acceptance criterion), so an event that has not passed a
human disposition is not yet part of the accepted timeline. Acceptance is a
separate, explicit act; nothing here promotes an event on its own.

Defined here rather than in `domain.situation` so the relationship concepts stay
in the relationship package; the continuity package re-exports it for callers
that build a Project/Relationship timeline in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "RelationshipEvent",
    "RelationshipEventType",
]


class RelationshipEventType(StrEnum):
    """The kinds of association event a Person's timeline records.

    The six mirror the relationship surfaces the canonical model names for R5:
    Interaction/Meeting contacts, reciprocal Commitments, private Observations,
    Affiliation changes, and the link that ties a Person into a Project. The set
    is frozen in the migration's `event_type` CHECK, so widening it is a visible
    schema change rather than a silent one.
    """

    INTERACTION = "interaction"
    MEETING = "meeting"
    COMMITMENT = "commitment"
    OBSERVATION = "observation"
    AFFILIATION_CHANGE = "affiliation_change"
    PROJECT_LINK = "project_link"


@dataclass(frozen=True, slots=True)
class RelationshipEvent:
    """One dated, context-aware event on a Person's relationship timeline.

    `accepted` is the single gate the accepted-timeline read (Today/Pulse and
    the briefing) filters on. It is not a confidence score and it is never set
    by derivation: an event enters accepted only through an explicit human
    disposition, which is why it defaults to false here.
    """

    event_id: str
    principal_id: str
    person_id: str
    event_type: RelationshipEventType
    occurred_at: datetime
    created_at: datetime
    context: str | None = None
    accepted: bool = False
    source_ref: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, IdKind.RELATIONSHIP_EVENT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.person_id, IdKind.PERSON)
        if not isinstance(self.event_type, RelationshipEventType):
            raise ValueError("a relationship event names one event type")
        if not isinstance(self.accepted, bool):
            raise ValueError("acceptance is a boolean gate")
        ensure_utc(self.occurred_at)
        ensure_utc(self.created_at)
