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

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import (
    IdKind,
    make_identifier,
    parse_identifier,
    validate_identifier,
)
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "EDGE_WHITESPACE",
    "ENTITY_CHANGE_REASON_LIMIT",
    "MENTION_DISPLAY_NAME_LIMIT",
    "NEGATIVE_IDENTITY_EVIDENCE_ROLE",
    "OBSERVED_VALUE_LIMIT",
    "PRODUCT_OWNED_CAPTURE_SOURCE_ID",
    "ActorClass",
    "EntityFactEvidenceLink",
    "EntityGovernanceError",
    "EntityMergeRecord",
    "EntityMutationConflictError",
    "EntityMutationEvent",
    "EntityObservation",
    "EntityProposal",
    "EntityProposalKind",
    "EntityProposalState",
    "EntityResolutionDecision",
    "EvidenceRole",
    "MutationAuthority",
    "MutationRecordFamily",
    "ObservationAuthority",
    "ObservationAuthorityError",
    "ObservationKind",
    "ObservationOrigin",
    "ObservationState",
    "ObservationTimeError",
    "ResolutionDisposition",
    "ReviewRequirement",
    "StaleResolutionVersionError",
    "capture_origin_triple",
    "origin_of",
]

#: How long a disclosed mention name may be. Stated here and repeated as a CHECK
#: in `f3a8c1d7e592`, because this is the one field the queue publishes and a
#: column with no ceiling is a column an ingester can put a document in. Long
#: enough for a person's full name with honorifics and a long organization name;
#: short enough that a paragraph of lifted text does not fit.
MENTION_DISPLAY_NAME_LIMIT = 200

#: The whitespace a disclosed mention name may not begin or end with, written
#: out rather than taken from `str.isspace()` or from SQL's `[[:space:]]`.
#:
#: Both of those are larger than this and **larger by different amounts**:
#: Python strips U+00A0, PostgreSQL's class here does not; PostgreSQL's class
#: matches U+2003 and U+3000, Python's `strip()` of this set does not. A rule
#: expressed in either one cannot be checked by the other, and the CHECK in
#: `f3a8c1d7e592` has to refuse exactly what this record refuses. This set is
#: the intersection both engines agree on, and unlike a character class it does
#: not move with the server's collation.
EDGE_WHITESPACE = " \t\n\r\v\f"

#: How long a stored explanation of one change may be: the `reason` on a
#: mutation-ledger row, the `state_reason` on an observation, and the `reason` on
#: a resolution decision.
#:
#: Bounded for the reason `MENTION_DISPLAY_NAME_LIMIT` is bounded, and the
#: failure it prevents is worse here: these three columns are the ones a writer
#: reaches for when it wants to say what happened, and an unbounded text column
#: on an append-only ledger is where a caller eventually puts the payload it
#: could not fit anywhere else -- source text, a stack trace, a document. Long
#: enough for a sentence explaining a decision; short enough that a document
#: does not fit.
ENTITY_CHANGE_REASON_LIMIT = 500

#: How long an observed value may be.
#:
#: **The column has no such CHECK, and this is stated rather than implied.**
#: `entity_observations.observed_value` is bounded only by `text`, which is the
#: shape `MENTION_DISPLAY_NAME_LIMIT`'s own note calls "a column an ingester can
#: put a document in" -- and relaxing that here would be worse than on the
#: disclosed column, because this is the one that holds the raw source span.
#: `MYPA-RI-COMP-04`'s change list for this table does not add the constraint,
#: so the bound lives at the write path instead: every caller reaches this
#: column through `entities.observe`, and that command refuses a longer value.
#: A row written around the command can still be longer, which is exactly the
#: residual a CHECK would close and a comment cannot.
#:
#: Long enough for a mail envelope with a display name and a long address, or a
#: full name with honorifics; short enough that a paragraph of lifted document
#: text does not fit.
OBSERVED_VALUE_LIMIT = 500

#: The shape a request digest takes, restated here because the CHECK on
#: `entity_mutation_events.request_digest` says the same thing in SQL and the
#: two have to refuse the same values.
_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")


class EntityGovernanceError(Exception):
    """Anything the governed half of the entity plane refuses.

    A base class rather than three unrelated exceptions, so a caller that wants
    to translate the whole family can, and one that wants to tell a stale
    version from a duplicate key still can.
    """


class StaleResolutionVersionError(EntityGovernanceError):
    """A resolution decision expected a version the observation no longer holds.

    Raised *before* anything is written, and nothing is written after it: the
    guarded `UPDATE` that checks the version is the first write of the
    transaction, so a decision that lost the race leaves no ledger row, no
    evidence link and no decision behind.
    """


class EntityMutationConflictError(EntityGovernanceError):
    """One idempotency key is already held under this capability for a different request.

    Distinguished from a replay by the request digest and by nothing else. Same
    key and same digest is the caller retrying and gets the first answer back;
    same key and a different digest is a caller reusing a key for a second
    request, which is the one case that has to be refused rather than absorbed.
    """


class ObservationTimeError(EntityGovernanceError):
    """An observation was said to have been observed after it was recorded.

    Its own refusal rather than the `ValueError` `EntityObservation` raises,
    because the two travel differently: the record's own check is the last line
    of defence and reaches a caller as `internal_error`, which says "this is our
    fault, retrying will not help" about a request that named a moment in the
    future. A caller that mistyped a date is owed `invalid_request` naming
    `observed_at`, and only the layer holding the server clock can tell the two
    apart.
    """


class ObservationAuthorityError(EntityGovernanceError):
    """An observation claimed standing its origin does not support.

    The refusal that keeps a model conclusion out of `SOURCE_OBSERVATION`. It is
    a refusal about the *origin* rather than about the caller, because a rule
    that asked who was calling would be satisfied by anything willing to say it
    was a source.
    """


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


class ObservationAuthority(StrEnum):
    """What kind of standing one observation has.

    Section 12.2 says a contact row or a calendar attendee "does not become the
    canonical person by itself", and that rule has always been enforced by the
    *shape* of this plane -- an observation is a separate record from an entity.
    What the shape could not say is that three unlike things were being stored in
    one table once a user could speak into it: what a source said, what the user
    said, and what this product computed.

    They are not interchangeable, and the difference is not a ranking. A
    SOURCE_OBSERVATION can be re-derived from the source and is falsified when
    the source version changes. A USER_AUTHORED_STATEMENT cannot be re-derived at
    all and is never falsified by a source, because the user is not quoting one.
    A SYSTEM_DETERMINISTIC_OBSERVATION is reproducible from inputs this product
    already holds. A reader that could not tell them apart would treat a user's
    own correction as stale the moment the mailbox it disagreed with was re-read.
    """

    SOURCE_OBSERVATION = "source_observation"
    USER_AUTHORED_STATEMENT = "user_authored_statement"
    SYSTEM_DETERMINISTIC_OBSERVATION = "system_deterministic_observation"


class ObservationOrigin(StrEnum):
    """Where the record an observation quotes actually lives.

    Two members, and they are not a ranking either. `CONFIGURED_SOURCE` names a
    row in somebody's mailbox, calendar or contact store, reachable again
    through the enrollment that admitted it. `PRODUCT_OWNED_CAPTURE` names a
    record this product itself holds -- a capture the user typed, or a version
    of one -- which belongs to no configured source and never will
    (`ADR-003` makes that a third authority class, and `_SCOPELESS` in
    `domain.policy.decision` says the same thing about every plane built on it).

    It exists because `entity_observations.source_id`, `source_object_id` and
    `source_version_id` are `NOT NULL` and stay that way: `MYPA-RI-COMP-04`'s
    change list for that table does not relax them, and those three columns
    carry no foreign key and no identifier-shape CHECK, so a product-owned
    capture identity fits the triple the table already has. What the triple
    *cannot* say by itself is which of the two kinds of record it names, and
    that difference decides what authority an observation may claim -- so it is
    a closed vocabulary here rather than a prefix comparison spelled out at
    every reader.
    """

    CONFIGURED_SOURCE = "configured_source"
    PRODUCT_OWNED_CAPTURE = "product_owned_capture"


#: The reserved `src_...` identity every product-owned capture observation
#: carries in `entity_observations.source_id`.
#:
#: A constant rather than a row: there is no configured source to point at, and
#: inventing one would put a fabricated enrollment in front of an operator
#: reading `sources.list`. The column carries no foreign key, so nothing is
#: violated by a value naming no row -- and `origin_of` reads this exact string
#: back out, so "which kind of record is this" stays decidable from the stored
#: triple alone rather than from a second column nothing would keep in step.
#:
#: **It is deliberately not a real-looking identifier.** The suffix spells what
#: it is, because an operator who finds it in a row should be able to tell that
#: it is the product's own custody and not a source they have forgotten
#: enrolling.
PRODUCT_OWNED_CAPTURE_SOURCE_ID: str = "src_productownedcapture"


def capture_origin_triple(capture_id: str, capture_version_id: str) -> tuple[str, str, str]:
    """The `(source, object, version)` triple one product-owned capture observation carries.

    Deterministic, and that is a requirement rather than a nicety: the triple is
    part of what an idempotent replay compares, so a mapping that minted fresh
    identifiers would make every retry a conflict.

    The capture's own suffix is carried across rather than digested, so the row
    still points back at the capture an operator can go and read. Re-prefixing
    is not an identity claim about a source object -- `PRODUCT_OWNED_CAPTURE_SOURCE_ID`
    is what says the record is the product's own -- it is what lets a `NOT NULL`
    column whose shape the domain record checks hold a capture identity at all.
    """
    _, capture_suffix = parse_identifier(validate_identifier(capture_id, IdKind.CAPTURE))
    _, version_suffix = parse_identifier(
        validate_identifier(capture_version_id, IdKind.CAPTURE_VERSION)
    )
    return (
        PRODUCT_OWNED_CAPTURE_SOURCE_ID,
        make_identifier(IdKind.SOURCE_OBJECT, capture_suffix),
        make_identifier(IdKind.VERSION, version_suffix),
    )


def origin_of(source_id: str) -> ObservationOrigin:
    """Which kind of record the stored triple names.

    Derived from the one column that can say so rather than stored beside it: a
    second column would be a second place for the same fact, and the two would
    eventually disagree about a row nobody rewrote.
    """
    if source_id == PRODUCT_OWNED_CAPTURE_SOURCE_ID:
        return ObservationOrigin.PRODUCT_OWNED_CAPTURE
    return ObservationOrigin.CONFIGURED_SOURCE


class ObservationState(StrEnum):
    """Where one observation stands as evidence.

    CURRENT is the steady state. The other four are the four different ways an
    observation stops being usable evidence, and they are separate because the
    right response to each is different:

    * STALE -- the source version it came from is no longer the current one, so
      it may still be true and is no longer *checked*;
    * CONTRADICTED -- something the product also holds says otherwise, and both
      are still recorded, because deciding between them is a review's job;
    * SUPERSEDED -- a later observation of the same fact replaced this one, and
      `superseded_by_observation_id` says which;
    * QUARANTINED -- the observation itself is not trustworthy input, on the same
      terms `domain.extraction.quarantine` uses, and must not feed a resolution
      even as a candidate.

    None of them deletes the row. Section 10.11 forbids the silent deletion, and
    a contradicted observation is exactly the evidence a reviewer needs in order
    to decide anything at all.
    """

    CURRENT = "current"
    STALE = "stale"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    QUARANTINED = "quarantined"


class MutationAuthority(StrEnum):
    """What admitted one change to a canonical record.

    Three members, and each names a *mechanism* rather than an actor: the same
    person can act through any of them and the accountability differs.
    USER_CONFIRMED_ASSERTION is the user having been asked and having answered.
    REVIEW_ACCEPTED is a review case having been dispositioned, which is the path
    section 21.4 requires for identity. SYSTEM_DETERMINISTIC is work that follows
    from inputs already held and could be recomputed -- and is therefore the one
    authority that may never, by itself, create or merge an identity.

    Shared by `entity_mutation_events` and `entity_fact_evidence_links` because
    they answer the same question about the same act: what admitted this. Two
    vocabularies would let the ledger and the evidence disagree about a single
    write.
    """

    USER_CONFIRMED_ASSERTION = "user_confirmed_assertion"
    REVIEW_ACCEPTED = "review_accepted"
    SYSTEM_DETERMINISTIC = "system_deterministic"


class MutationRecordFamily(StrEnum):
    """Which canonical record family one ledger row is about.

    Closed at the six families this plane holds as canonical fact. It is a family
    rather than a table name because the ledger has to survive a table being
    split or renamed without every historical row becoming unreadable, and it is
    closed rather than free text because a ledger whose subject is unconstrained
    is a ledger no reader can enumerate.

    `entity_proposals` and `entity_merge_records` are deliberately absent: a
    proposal is not canonical fact -- it is a request -- and a merge record is the
    lineage an accepted proposal leaves, which is already an append-only row of
    its own. A mutation ledger that also recorded proposals would record the
    asking as if it were the doing.
    """

    ENTITY = "entity"
    IDENTIFIER = "identifier"
    ALIAS = "alias"
    ASSIGNMENT = "assignment"
    RELATIONSHIP = "relationship"
    OBSERVATION = "observation"


class EvidenceRole(StrEnum):
    """How one evidence record bears on the fact it is linked to.

    COUNTEREVIDENCE is the member that matters. A link table holding only
    supporting records is a table that can only ever make a fact look better
    supported than it is, and the state this plane most needs to be able to
    represent is "we hold something that argues against this". Named the same way
    `relationship_memory_evidence_links` names it, because it is the same
    question about a different subject.
    """

    DIRECT = "direct"
    SUPPORTING = "supporting"
    COUNTEREVIDENCE = "counterevidence"


#: The `EvidenceRole` a rejected identity pairing is preserved under.
#:
#: Named rather than spelled at each writer, because this is the whole mechanism
#: by which a refusal has a durable operational effect: the resolver reads back
#: exactly the links carrying this role, and a writer that reached for
#: `SUPPORTING` by accident would record the opposite of what was decided while
#: still looking like a record of it.
NEGATIVE_IDENTITY_EVIDENCE_ROLE: EvidenceRole = EvidenceRole.COUNTEREVIDENCE


class ResolutionDisposition(StrEnum):
    """What was decided about one observation.

    Five outcomes, and three of them are refusals. That ratio is the design:
    section 15.2 requires an ambiguous mention to remain unresolved rather than
    be forced into the nearest person, so the vocabulary has to make *not*
    resolving an ordinary recorded decision rather than an absence of one.

    DEFER and REJECT differ in what they say about the future: a deferred
    observation is expected to be decidable later, and a rejected one has been
    decided -- it refers to nothing this plane holds. QUARANTINE is the third
    refusal and is about the observation rather than the match.
    """

    LINK_EXISTING = "link_existing"
    CREATE_NEW = "create_new"
    REJECT = "reject"
    DEFER = "defer"
    QUARANTINE = "quarantine"


class ActorClass(StrEnum):
    """What class of actor performed one recorded act.

    Deliberately the same three classes `relationship.memory.MemoryActorClass`
    names, and deliberately a separate declaration: the two planes are widened
    independently, and one enum would make widening either a silent widening of
    both. A model name never appears here -- which model proposed the thing a
    reviewer accepted belongs on the proposal, and the honest answer for a
    promotion is "a person decided".
    """

    USER = "user"
    REVIEW_PROMOTION = "review_promotion"
    SYSTEM_DETERMINISTIC = "system_deterministic"


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

    **`resolution_version` is the value an optimistic decision is checked
    against.** It counts how many times this observation's resolution has been
    decided, and a decision states the version it expected to be deciding
    against. Without it, two reviewers looking at the same unresolved mention
    both write a decision and the second silently overwrites the first's
    conclusion -- on a record whose whole purpose is that identity is not
    decided by accident. It starts at zero because an observation nothing has
    decided has had no resolution, and zero is that fact rather than a sentinel.

    `authority` and `state` are the two things this record could not previously
    say about itself: where its claim comes from, and whether it is still usable
    as evidence. Both default to the values every row written before this
    revision actually holds -- a source-bound observation that nothing has
    contradicted -- so the defaults are a statement about the existing rows
    rather than a convenience.
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
    authority: ObservationAuthority = ObservationAuthority.SOURCE_OBSERVATION
    state: ObservationState = ObservationState.CURRENT
    state_reason: str | None = field(default=None, repr=False)
    superseded_by_observation_id: str | None = None
    resolution_version: int = 0

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
            #
            # **Refused rather than trimmed, against an explicit character
            # set, and the length is of the value itself.** The CHECK in
            # `f3a8c1d7e592` has to refuse exactly what this refuses, and two
            # earlier attempts did not.
            #
            # The first compared `str.strip()` against SQL's `trim()`. Those
            # disagree in both directions: `str.strip()` removes every kind of
            # whitespace and `trim()` removes only spaces, so a tab-padded value
            # was short enough here and too long at the server, and a tab-only
            # value was blank here and acceptable there.
            #
            # The second kept `str.strip()` and moved the CHECK to
            # `[[:space:]]`. That closed the two values a reviewer had named and
            # left the class open: `"\tA. Chen"` is still refused here and
            # accepted there, so the row this guard exists to stop could be
            # written around the repository and then make the whole
            # `entities.unresolved_mentions` page raise on read. Worse,
            # `[[:space:]]` is decided by the server's collation -- measured
            # matching U+2003 and U+3000 but not U+00A0 -- which is the exact
            # locale dependence `persistence.entity` already refuses for
            # `[[:alnum:]]`, one module over.
            #
            # So the set is written out. It is the ASCII whitespace both
            # engines name the same way, it does not move with a locale, and it
            # is small enough to state in both languages and compare. What is
            # stored is what is published, with no padding.
            edges = self.mention_display_name[:1] + self.mention_display_name[-1:]
            if any(character in EDGE_WHITESPACE for character in edges):
                raise ValueError("a disclosed mention name carries no leading or trailing space")
            if not self.mention_display_name.strip(EDGE_WHITESPACE):
                raise ValueError("a disclosed mention name is not blank")
            if len(self.mention_display_name) > MENTION_DISPLAY_NAME_LIMIT:
                raise ValueError("a disclosed mention name is bounded")
        if not isinstance(self.authority, ObservationAuthority):
            raise ValueError("an observation has a closed authority")
        if not isinstance(self.state, ObservationState):
            raise ValueError("an observation has a closed state")
        if self.state_reason is not None:
            # A reason explains a *departure* from CURRENT. On a current
            # observation there is nothing to explain, and admitting one would
            # make the column a free-text note field on the busiest table on the
            # plane -- which is how an unbounded column acquires source text.
            if self.state is ObservationState.CURRENT:
                raise ValueError("a current observation has no state to explain")
            if not self.state_reason.strip():
                raise ValueError("an observation state reason is not blank")
            if len(self.state_reason) > ENTITY_CHANGE_REASON_LIMIT:
                raise ValueError("an observation state reason is bounded")
        if self.superseded_by_observation_id is not None:
            validate_identifier(self.superseded_by_observation_id, IdKind.ENTITY_OBSERVATION)
            if self.superseded_by_observation_id == self.observation_id:
                raise ValueError("an observation cannot supersede itself")
            if self.state is not ObservationState.SUPERSEDED:
                raise ValueError("an observation names a successor only when superseded")
        if self.resolution_version < 0:
            raise ValueError("an observation resolution version is not negative")
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


@dataclass(frozen=True, slots=True)
class EntityMutationEvent:
    """One append-only row of the entity plane's mutation ledger.

    **It is two records that happen to share a table, and the second one is the
    reason this type exists at all.** As a ledger it says what changed, under
    whose authority, and against which version. As an idempotency store its
    `(principal_id, capability, idempotency_key)` is unique, so a replayed write
    finds its own earlier row instead of writing a second one — the shape
    `capture_submissions` and `relationship_memory_submissions` already use, and
    `capability` is part of the key because one key replayed against a
    *different* capability is a different request.

    `request_digest` is what makes a replay decidable without keeping a second
    copy of the request. Same key and same digest is a replay; same key and a
    different digest is a conflict, and the difference has to be computable from
    a row that stores none of the caller's text.

    **`before_state` and `after_state` never carry raw observed content.** They
    are `repr=False` and the writers on this plane put identifiers, closed
    vocabulary members and versions in them and nothing else. The rule is stated
    here because a photograph of an `entity_observations` row is exactly where
    `observed_value` would end up if a writer photographed the row wholesale,
    and this ledger is read by operators, exported, and rendered in failures.
    """

    event_id: str
    principal_id: str
    capability: str
    record_family: MutationRecordFamily
    record_id: str
    new_version: int
    authority: MutationAuthority
    actor_class: ActorClass
    idempotency_key: str = field(repr=False)
    request_digest: str
    correlation_id: str
    audit_id: str
    recorded_at: datetime
    prior_version: int | None = None
    before_state: Mapping[str, object] | None = field(default=None, repr=False)
    after_state: Mapping[str, object] | None = field(default=None, repr=False)
    reason: str | None = field(default=None, repr=False)
    receipt_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, IdKind.ENTITY_MUTATION_EVENT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        # No expected kind: `record_id` names a row in whichever of six tables
        # `record_family` says, and no single kind can express that. What is
        # still checked is that the value is an opaque identifier at all, which
        # is the same rule the column's own CHECK applies.
        validate_identifier(self.record_id)
        if self.receipt_id is not None:
            validate_identifier(self.receipt_id)
        if not isinstance(self.record_family, MutationRecordFamily):
            raise ValueError("a mutation names a closed record family")
        if not isinstance(self.authority, MutationAuthority):
            raise ValueError("a mutation has a closed authority")
        if not isinstance(self.actor_class, ActorClass):
            raise ValueError("a mutation has a closed actor class")
        if not self.capability.strip():
            raise ValueError("a mutation names the capability that made it")
        if not self.idempotency_key:
            raise ValueError("a mutation carries an idempotency key")
        if not _SHA256.fullmatch(self.request_digest):
            raise ValueError("a mutation request digest is a sha256 digest")
        if self.new_version < 1:
            raise ValueError("a mutation new version is positive")
        if self.prior_version is not None:
            if self.prior_version < 1:
                raise ValueError("a mutation prior version is positive")
            if self.new_version <= self.prior_version:
                raise ValueError("a mutation advances the version it names")
        if self.reason is not None:
            if not self.reason.strip():
                raise ValueError("a mutation reason is not blank")
            if len(self.reason) > ENTITY_CHANGE_REASON_LIMIT:
                raise ValueError("a mutation reason is bounded")
        ensure_utc(self.recorded_at)


@dataclass(frozen=True, slots=True)
class EntityFactEvidenceLink:
    """One binding between a canonical fact and the single record that evidences it.

    Exactly one fact and exactly one evidence record, refused here on the same
    terms the server refuses them: a row naming two facts has an ambiguous
    subject and a row naming two evidence records has an ambiguous basis, and
    neither is a state a later read could disentangle.

    **`COUNTEREVIDENCE` is what makes a refusal durable.** A rejected identity
    decision names no entity on `entity_resolution_decisions` — the column's own
    CHECK reserves `entity_id` for the two dispositions that *bind* one — so the
    pairing a user refused would be unrecoverable if it were recorded nowhere
    else. It is recorded here: the entity on one side, the observation on the
    other, and `NEGATIVE_IDENTITY_EVIDENCE_ROLE` saying which way the evidence
    points. That is the row `EntityResolutionService` reads so a known-bad
    pairing is not offered again.
    """

    link_id: str
    principal_id: str
    role: EvidenceRole
    authority: MutationAuthority
    created_at: datetime
    entity_id: str | None = None
    identifier_id: str | None = None
    alias_id: str | None = None
    assignment_id: str | None = None
    relationship_id: str | None = None
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.link_id, IdKind.ENTITY_FACT_EVIDENCE_LINK)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.role, EvidenceRole):
            raise ValueError("an evidence link has a closed role")
        if not isinstance(self.authority, MutationAuthority):
            raise ValueError("an evidence link has a closed authority")
        named = [
            (self.entity_id, IdKind.ENTITY),
            (self.identifier_id, IdKind.EXTERNAL_IDENTIFIER),
            (self.alias_id, IdKind.ENTITY_ALIAS),
            (self.assignment_id, IdKind.ASSIGNMENT),
            (self.relationship_id, IdKind.ENTITY_RELATIONSHIP),
        ]
        cited = [
            (self.entity_observation_id, IdKind.ENTITY_OBSERVATION),
            (self.capture_span_id, IdKind.SPAN),
            (self.knowledge_id, IdKind.KNOWLEDGE),
        ]
        for value, kind in (*named, *cited):
            if value is not None:
                validate_identifier(value, kind)
        if sum(value is not None for value, _ in named) != 1:
            raise ValueError("entity evidence names exactly one fact")
        if sum(value is not None for value, _ in cited) != 1:
            raise ValueError("entity evidence names exactly one record")
        ensure_utc(self.created_at)

    @property
    def is_negative_identity_evidence(self) -> bool:
        """Whether this link refuses a pairing rather than supporting one."""
        return (
            self.role is NEGATIVE_IDENTITY_EVIDENCE_ROLE
            and self.entity_id is not None
            and self.entity_observation_id is not None
        )


@dataclass(frozen=True, slots=True)
class EntityResolutionDecision:
    """One append-only disposition of one observation.

    Three of the five dispositions are refusals, and recording a refusal is the
    point: section 15.2 requires an ambiguous mention to stay unresolved rather
    than be forced into the nearest person, so "we looked and declined to
    decide" has to be storable and has to be distinguishable from "nobody
    looked".

    `expected_resolution_version` is the value the decider believed it was
    deciding against, and `sequence` is where this decision falls in the
    observation's own order. They are both here and they are not the same fact:
    the first is an optimistic check the writer performs against the
    observation, and the second is the uniqueness the table enforces. A writer
    that derived one from the other silently would lose the check the moment the
    derivation was wrong.

    `reason` is bounded and never carries the observed text. It explains a
    decision; a column that could hold a document is a column an ingester
    eventually puts one in.
    """

    decision_id: str
    principal_id: str
    observation_id: str
    sequence: int
    expected_resolution_version: int
    disposition: ResolutionDisposition
    decided_by: str
    actor_class: ActorClass
    correlation_id: str
    audit_id: str
    decided_at: datetime
    entity_id: str | None = None
    reason: str | None = field(default=None, repr=False)
    evidence_link_ids: tuple[str, ...] = ()
    review_case_id: str | None = None
    receipt_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.decision_id, IdKind.ENTITY_RESOLUTION_DECISION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.observation_id, IdKind.ENTITY_OBSERVATION)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        if not isinstance(self.disposition, ResolutionDisposition):
            raise ValueError("a resolution has a closed disposition")
        if not isinstance(self.actor_class, ActorClass):
            raise ValueError("a resolution has a closed actor class")
        if self.sequence < 1:
            raise ValueError("a resolution sequence is positive")
        if self.expected_resolution_version < 0:
            raise ValueError("a resolution expects a version that could exist")
        if not self.decided_by.strip():
            raise ValueError("a resolution names what decided it")
        binds = self.disposition in (
            ResolutionDisposition.LINK_EXISTING,
            ResolutionDisposition.CREATE_NEW,
        )
        if binds != (self.entity_id is not None):
            raise ValueError("a resolution names an entity exactly when it binds one")
        if self.entity_id is not None:
            validate_identifier(self.entity_id, IdKind.ENTITY)
        if self.reason is not None:
            if not self.reason.strip():
                raise ValueError("a resolution reason is not blank")
            if len(self.reason) > ENTITY_CHANGE_REASON_LIMIT:
                raise ValueError("a resolution reason is bounded")
        for link_id in self.evidence_link_ids:
            validate_identifier(link_id, IdKind.ENTITY_FACT_EVIDENCE_LINK)
        if len(set(self.evidence_link_ids)) != len(self.evidence_link_ids):
            raise ValueError("a resolution cites each evidence link once")
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        if self.receipt_id is not None:
            validate_identifier(self.receipt_id)
        ensure_utc(self.decided_at)
