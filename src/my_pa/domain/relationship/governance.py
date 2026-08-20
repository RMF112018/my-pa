"""Observations, proposals, and merge lineage: how the entity plane changes.

Three records, and the separation between them is the whole governance model.

**An observation is what a source said.** Section 12.2: a contact row, an email
address, a calendar attendee "does not become the canonical person by itself".
So an observation carries its source, its version, and its times, and its
`entity_id` is nullable — an observation nothing has linked yet is an
*unresolved mention*, which section 13.1 makes a first-class state rather than a
failure to store something.

**A proposal is what something wants to change.** Section 8.6: "Extracted data
begins as proposals." Section 21.4 forbids a model creating a canonical person
or merging identities. So nothing here applies itself: a proposal carries the
mutation it wants, the evidence for it, and what would have to happen before it
could be accepted -- and a decision is a separate act with an actor attached.

**A merge record is what an accepted merge left behind.** Section 15.3 requires
a merge to name the retained identifier, preserve prior ones as lineage, and
support a governed correction path. A merge that only rewrote rows would satisfy
none of that; the lineage record is what makes it reversible.

**On the absence of a risk band.** Section 12.18 asks a review case to carry a
"risk class". `ReviewRequirement` is that concept named for what it *does*
instead: `tests/architecture/test_relationship_scoring_surface_is_denied`
refuses the token `risk` on this surface, and a band is in any case less useful
than the requirement it implies. "This needs an operator" is actionable;
"this is high risk" is a label somebody still has to translate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "MENTION_DISPLAY_NAME_LIMIT",
    "EntityMergeRecord",
    "EntityObservation",
    "EntityProposal",
    "EntityProposalKind",
    "EntityProposalState",
    "ObservationKind",
    "ReviewRequirement",
]

#: How long a disclosed mention name may be. Stated here and repeated as a CHECK
#: in `f3a8c1d7e592`, because this is the one field the queue publishes and a
#: column with no ceiling is a column an ingester can put a document in. Long
#: enough for a person's full name with honorifics and a long organization name;
#: short enough that a paragraph of lifted text does not fit.
MENTION_DISPLAY_NAME_LIMIT = 200


class ObservationKind(StrEnum):
    """What kind of source record an observation came from.

    The list is section 12.2's examples, closed: a contact row, an address, a
    calendar attendee, a mention in a document. Widening it is a visible schema
    change, because the migration's CHECK references these values.
    """

    CONTACT_RECORD = "contact_record"
    MESSAGE_PARTICIPANT = "message_participant"
    CALENDAR_ATTENDEE = "calendar_attendee"
    DOCUMENT_MENTION = "document_mention"
    USER_STATEMENT = "user_statement"


class EntityProposalKind(StrEnum):
    """The mutations a proposal may ask for.

    Every one of them is a mutation this plane can already perform through
    `EntitiesRepository`. A proposal kind with no corresponding write would be a
    request nothing could ever accept.
    """

    CREATE_ENTITY = "create_entity"
    BIND_IDENTIFIER = "bind_identifier"
    RECORD_ALIAS = "record_alias"
    RECORD_ASSIGNMENT = "record_assignment"
    RECORD_RELATIONSHIP = "record_relationship"
    MERGE_ENTITIES = "merge_entities"


class EntityProposalState(StrEnum):
    """Where a proposal stands.

    `SUPERSEDED` rather than deletion, because section 10.11 says no record is
    silently deleted and a proposal that was overtaken is evidence about how the
    understanding developed.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class ReviewRequirement(StrEnum):
    """What has to happen before a proposal may be accepted.

    Section 19.4: "Low-risk topic and project suggestions may be accepted under
    configured thresholds. Person identity, commitments, financial or schedule
    facts, critical dates, and sensitive observations require review in the
    initial posture." Section 8.4 adds that identity merges are not eligible for
    default bulk acceptance at all.

    Three levels rather than a boolean, because those are three different
    sentences and collapsing the last two would make a merge acceptable by
    whatever mechanism clears an alias.
    """

    #: Deterministic metadata a configured threshold may accept.
    MAY_BE_ACCEPTED_AUTOMATICALLY = "may_be_accepted_automatically"
    #: A person has to look at it. The initial posture for identity.
    REQUIRES_REVIEW = "requires_review"
    #: The operator specifically, and never a bulk action. Identity merges.
    REQUIRES_OPERATOR = "requires_operator"


#: What each proposal kind requires before acceptance. A mapping rather than a
#: field the proposer supplies, because a proposer that could name its own
#: review requirement could name the lowest one.
_REQUIREMENT_BY_KIND: dict[EntityProposalKind, ReviewRequirement] = {
    EntityProposalKind.CREATE_ENTITY: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.BIND_IDENTIFIER: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.RECORD_ALIAS: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.RECORD_ASSIGNMENT: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.RECORD_RELATIONSHIP: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.MERGE_ENTITIES: ReviewRequirement.REQUIRES_OPERATOR,
}


def requirement_for(kind: EntityProposalKind) -> ReviewRequirement:
    """What `kind` requires before it may be accepted.

    Derived rather than stored, so a proposal cannot be written with a weaker
    requirement than its kind carries -- which is the shape this rule would fail
    in if it were a column.
    """
    return _REQUIREMENT_BY_KIND[kind]


@dataclass(frozen=True, slots=True)
class EntityObservation:
    """One source-bound observation that may refer to an entity.

    `entity_id` is nullable and that is the record's most important property: an
    observation nothing has linked is an unresolved mention, which section 13.1
    makes a state rather than an absence. Linking one is a separate act, and it
    is why `entities.resolve` returning `AMBIGUOUS` can be stored rather than
    only reported.

    `observed_value` is `repr=False`: it is a name or an address read out of
    someone's mail, and a dataclass `repr` reaches a traceback and a log record
    without anyone deciding it should (`AGENTS.md` section 5).

    **Three values, and only one of them is published.** `observed_value` is
    what the source wrote. `normalized_value` is what matching compares against,
    and it is **not** a redaction of the first -- `normalize_name` casefolds and
    unpunctuates and removes no content, so a writer that derives it from raw
    text produces a value that is `is_normalized_name`-true and still carries
    the envelope. `mention_display_name` is the one field
    `entities.unresolved_mentions` discloses, it is optional, and it defaults to
    `None`: a writer that does nothing deliberate publishes nothing, and
    disclosing is an affirmative act into a field whose name says what it is
    for. `f3a8c1d7e592` records the argument.
    """

    observation_id: str
    principal_id: str
    kind: ObservationKind
    observed_value: str = field(repr=False)
    normalized_value: str = field(repr=False)
    source_id: str
    source_object_id: str
    source_version_id: str
    observed_at: datetime
    recorded_at: datetime
    entity_id: str | None = None
    mention_display_name: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        validate_identifier(self.observation_id, IdKind.ENTITY_OBSERVATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.source_version_id, IdKind.VERSION)
        if not isinstance(self.kind, ObservationKind):
            raise ValueError("an observation has a closed kind")
        if not self.observed_value.strip():
            raise ValueError("an observation records what was observed")
        if not self.normalized_value.strip():
            raise ValueError("an observation records the form it is matched by")
        if self.entity_id is not None:
            validate_identifier(self.entity_id, IdKind.ENTITY)
        if self.mention_display_name is not None:
            # Bounded, and blank is not a disclosure. A caller that meant to
            # publish nothing passes `None`; a whitespace-only string is a
            # writer bug, and admitting it would put an empty row on a queue
            # whose whole purpose is showing the operator what could not be
            # placed.
            if not self.mention_display_name.strip():
                raise ValueError("a disclosed mention name is not blank")
            if len(self.mention_display_name.strip()) > MENTION_DISPLAY_NAME_LIMIT:
                raise ValueError("a disclosed mention name is bounded")
        ensure_utc(self.observed_at)
        ensure_utc(self.recorded_at)
        if self.recorded_at < self.observed_at:
            raise ValueError("an observation cannot be recorded before it was observed")

    @property
    def is_unresolved_mention(self) -> bool:
        """Whether this observation has been linked to an entity yet."""
        return self.entity_id is None


@dataclass(frozen=True, slots=True)
class EntityProposal:
    """One proposed mutation of the entity plane, and the evidence for it.

    Carries no decision. `decided_by` and `decided_at` are set when a decision
    is *made*, by the service that makes it, and a proposal in `PROPOSED` has
    neither -- so "nothing has decided this" is a shape rather than a
    convention.

    `payload` is the mutation's own fields as a mapping, deliberately untyped
    here: a proposal is a request to call one of six repository writes, and
    typing six shapes into this record would duplicate the six signatures that
    already exist. The service that applies a proposal is where the shape is
    checked, because that is where getting it wrong is caught.
    """

    proposal_id: str
    principal_id: str
    kind: EntityProposalKind
    state: EntityProposalState
    payload: tuple[tuple[str, str], ...]
    observation_ids: tuple[str, ...]
    proposed_at: datetime
    proposed_by: str
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_id, IdKind.ENTITY_PROPOSAL)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.kind, EntityProposalKind):
            raise ValueError("a proposal has a closed kind")
        if not isinstance(self.state, EntityProposalState):
            raise ValueError("a proposal has a closed state")
        if not self.proposed_by.strip():
            raise ValueError("a proposal names what proposed it")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.ENTITY_OBSERVATION)
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("a proposal cites each observation once")
        ensure_utc(self.proposed_at)
        decided = self.state in (EntityProposalState.ACCEPTED, EntityProposalState.REJECTED)
        if decided != (self.decided_by is not None):
            raise ValueError("a decided proposal names who decided it, and only a decided one")
        if (self.decided_at is not None) != (self.decided_by is not None):
            raise ValueError("a decision has both an actor and a moment")
        if self.decided_at is not None:
            ensure_utc(self.decided_at)
            if self.decided_at < self.proposed_at:
                raise ValueError("a proposal cannot be decided before it was proposed")

    @property
    def requirement(self) -> ReviewRequirement:
        """What must happen before this may be accepted."""
        return requirement_for(self.kind)

    @property
    def is_open(self) -> bool:
        return self.state is EntityProposalState.PROPOSED


@dataclass(frozen=True, slots=True)
class EntityMergeRecord:
    """The lineage one accepted merge left behind.

    Section 15.3 asks a merge to name the retained identifier, preserve the
    prior one as lineage, and record actor, reason, evidence and time. This is
    that record, and it is why `Entity.superseded_by_entity_id` is a redirect
    rather than an erasure: the merged-away entity still exists, still resolves
    as a `HISTORICAL_MATCH`, and can be pointed back out again.
    """

    merge_id: str
    principal_id: str
    retained_entity_id: str
    merged_entity_id: str
    proposal_id: str
    decided_by: str
    reason: str
    decided_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.merge_id, IdKind.ENTITY_MERGE)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.retained_entity_id, IdKind.ENTITY)
        validate_identifier(self.merged_entity_id, IdKind.ENTITY)
        validate_identifier(self.proposal_id, IdKind.ENTITY_PROPOSAL)
        if self.retained_entity_id == self.merged_entity_id:
            raise ValueError("a merge joins two distinct entities")
        if not self.decided_by.strip():
            raise ValueError("a merge names who decided it")
        if not self.reason.strip():
            raise ValueError("a merge records why it was accepted")
        ensure_utc(self.decided_at)
