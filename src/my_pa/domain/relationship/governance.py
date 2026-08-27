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
The mutation it wants is checked against its kind's schema in
`domain.relationship.proposal_payload`, which is also where the fields a
proposal may never carry are named; what would have to happen is derived from
the kind by `requirement_for` and is never a column, so nothing can propose
itself into a lower requirement.

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
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalKind,
    EntityProposalPayload,
)
from my_pa.domain.relationship.proposal_validation import ResolutionDisposition

__all__ = [
    "ACCEPTED_PROPOSAL_STATES",
    "DEFAULT_MUTATION_ACTOR_CLASS",
    "DEFAULT_MUTATION_AUTHORITY",
    "EDGE_WHITESPACE",
    "ENTITY_CHANGE_REASON_LIMIT",
    "IDENTITY_CORRECTION_PROPOSAL_KINDS",
    "MENTION_DISPLAY_NAME_LIMIT",
    "NEGATIVE_IDENTITY_EVIDENCE_ROLE",
    "OBSERVED_VALUE_LIMIT",
    "OPEN_EQUIVALENT_PROPOSAL_STATES",
    "PRODUCT_OWNED_CAPTURE_SOURCE_ID",
    "PROPOSAL_METHOD_VERSION_LIMIT",
    "UNDECIDED_PROPOSAL_STATES",
    "ActorClass",
    "EntityFactEvidenceLink",
    "EntityGovernanceError",
    "EntityMergeRecord",
    "EntityMutationConflictError",
    "EntityMutationEvent",
    "EntityObservation",
    "EntityProposal",
    "EntityProposalEvidenceLink",
    "EntityProposalKind",
    "EntityProposalMethod",
    "EntityProposalPayload",
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
    "initial_state_for",
    "origin_of",
    "requirement_for",
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


#: What a governed entity write carries when nothing on the path says otherwise.
#:
#: Declared here, in the module that owns both vocabularies, because three
#: records in `contracts.ports` and two writers in `infrastructure.persistence`
#: all have to agree on it and a default spelled at each of them is five things
#: that can drift. `infrastructure.persistence.entity_authoring` held these as
#: two private constants until `WP-RI-B-05`; its comment block records why they
#: moved and which half of its reasoning stopped being true.
#:
#: A *default* rather than the only value: review promotion executes an accepted
#: proposal through the same services a user's own write goes through, and a
#: promoted source or local-model conclusion recorded as
#: `user_confirmed_assertion` would claim the user asserted what somebody else
#: did. The pair moves together -- see `contracts.ports._check_write_authority`.
DEFAULT_MUTATION_AUTHORITY: Final = MutationAuthority.USER_CONFIRMED_ASSERTION
DEFAULT_MUTATION_ACTOR_CLASS: Final = ActorClass.USER


class EntityProposalState(StrEnum):
    """Where a proposal stands.

    `SUPERSEDED` rather than deletion, because section 10.11 says no record is
    silently deleted and a proposal that was overtaken is evidence about how the
    understanding developed.

    Eight, and deliberately the same eight `MemoryProposalState` names: Entity
    and Relationship Memory candidates are decided on one Review surface by one
    `Disposition` vocabulary, and two state sets of different sizes would make
    "what can a reviewer do to this case" depend on which subject it carried.
    Declared separately rather than shared for the reason `ActorClass` states
    about `MemoryActorClass`: the two planes are widened independently, and one
    enum would make widening either a silent widening of both.

    `NEEDS_REVIEW` is where `requirement_for` puts a proposal a person has to
    look at, and it is the difference this plane could not previously express --
    with four states, a merge awaiting an operator and an alias awaiting a
    threshold were both just `proposed`.
    """

    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    CORRECTED_ACCEPTED = "corrected_accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


#: The states a second identical proposal would be a duplicate of.
#:
#: Three rather than one, and `DEFERRED` is the member that decides what this
#: set is for. A deferred case is one a reviewer looked at and pushed out; a
#: second identical row while it stands would put the same decision in front of
#: that reviewer twice and let a producer clear a deferral by re-filing. So the
#: rule is "nothing has finally disposed of this", not "nothing has touched it".
#:
#: `REJECTED` and `INVALIDATED` are absent because they are final, and a
#: re-proposal after a refusal is a question about *evidence* -- section 15.2's
#: negative identity evidence, read by a producer before it proposes -- rather
#: than a uniqueness rule. A unique index cannot tell a producer that genuinely
#: new evidence has invalidated the prior basis; only the evidence can.
#:
#: `entity_proposals` carries the matching partial unique index over
#: `(principal_id, dedupe_sha256)`.
OPEN_EQUIVALENT_PROPOSAL_STATES: Final[frozenset[EntityProposalState]] = frozenset(
    {
        EntityProposalState.PROPOSED,
        EntityProposalState.NEEDS_REVIEW,
        EntityProposalState.DEFERRED,
    }
)

#: The states in which nothing has decided a proposal yet, and it is therefore
#: still available to be decided for the first time.
#:
#: Two, and `DEFERRED` is deliberately not one of them although
#: `OPEN_EQUIVALENT_PROPOSAL_STATES` holds it: a deferred proposal *was* decided
#: -- somebody looked at it and pushed it out -- and the two sets answer
#: different questions. This one answers "may a decision be recorded against
#: this row", which is the predicate `SqlEntityRepository.decide_proposal` puts
#: inside its guarded `UPDATE`; that one answers "would a second identical
#: proposal be a duplicate". Routing a deferral back to a reviewer is the Review
#: plane's disposition and will widen this set when it lands, together with the
#: predicate, exactly as `WP-RI-B-05` widened both from `PROPOSED` alone.
#:
#: A tuple rather than a module-level `frozenset` for `_DECIDED_PROPOSAL_STATES`'
#: measured reason: the enum-derivation guard reports any revision whose CHECK
#: vocabulary equals a live closed set exactly, and these two values are what a
#: `state IN (...)` predicate on this table would spell.
UNDECIDED_PROPOSAL_STATES: Final = (
    EntityProposalState.PROPOSED,
    EntityProposalState.NEEDS_REVIEW,
)

#: The states in which a reviewer has made the call, and the record therefore
#: names who made it and when. `SUPERSEDED` is not one of them: a proposal
#: overtaken by a successor was not decided, which is why it carries
#: `superseded_at` instead of a decision.
#:
#: A tuple rather than a module-level `frozenset`, and the shape is deliberate.
#: `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum`
#: discovers live closed sets by walking `my_pa` for every `StrEnum` and every
#: module-level `frozenset[str]`, and reports any revision whose emitted CHECK
#: vocabulary equals one exactly -- because a literal that agrees today is
#: indistinguishable from a derived one. A frozenset naming these five would
#: have been reported against the `entity_proposals` CHECK that says the same
#: thing, and the two are meant to be independent: this one is what the record
#: refuses now, and the migration's is what a database migrated to that revision
#: refuses forever.
_DECIDED_PROPOSAL_STATES: Final = (
    EntityProposalState.ACCEPTED,
    EntityProposalState.CORRECTED_ACCEPTED,
    EntityProposalState.REJECTED,
    EntityProposalState.DEFERRED,
    EntityProposalState.INVALIDATED,
)

#: The states in which a proposal produced a canonical record, and the states in
#: which one may be promoted -- `application.entity_promotion` reads this rather
#: than spelling the pair, so "accepted" means one thing on both sides of the
#: promotion. A tuple for the reason above, and measured rather than assumed:
#: written as a frozenset, these two values matched `f1c6b904a2d7`'s
#: `a_memory_proposal_names_its_result_exactly_when_accepted` -- the same
#: sentence about the memory plane -- and that guard went red.
ACCEPTED_PROPOSAL_STATES: Final = (
    EntityProposalState.ACCEPTED,
    EntityProposalState.CORRECTED_ACCEPTED,
)

#: The two kinds whose acceptance changes no identity.
#:
#: Named once here rather than spelled at each reader, because this pair is the
#: whole of section 15's division and every place that has to honour it -- the
#: reviewer's promotion path, the merge application, the preview's affected
#: proposals -- has to agree on which kinds it names. Accepting one of these
#: records reviewed intent and lineage; the mutation itself is a separate
#: operator act, and a reviewer grant is not an identity-correction grant.
IDENTITY_CORRECTION_PROPOSAL_KINDS: Final[frozenset[EntityProposalKind]] = frozenset(
    {EntityProposalKind.MERGE_ENTITIES, EntityProposalKind.SPLIT_IDENTITY}
)


class EntityProposalMethod(StrEnum):
    """How a proposal was produced.

    Three members, and the absences are the same ones `MemoryProposalMethod`
    records: there is no `cloud_model` and no `hybrid`, because no path in this
    build routes relationship evidence to a cloud model and a vocabulary that
    named one would advertise a method a caller could ask for and a reviewer
    could believe had run.

    This is a *server-owned* value -- `FORBIDDEN_PAYLOAD_FIELDS` refuses
    `method` in a payload -- for the reason section 21.4 gives: a model
    conclusion filed as a deterministic match is a model conclusion a threshold
    would accept without a person, which is exactly the promotion this whole
    plane exists to prevent.
    """

    DETERMINISTIC = "deterministic"
    RULE = "rule"
    LOCAL_MODEL = "local_model"


#: How long a method or model version token may be, and the shape it takes.
#:
#: The bounded lowercase token `domain.capture.proposal` uses for the same two
#: fields, restated rather than imported for the reason that module's own
#: constant is not this plane's: these are two vocabularies about two planes,
#: and a shared constant would make widening one widen the other.
PROPOSAL_METHOD_VERSION_LIMIT = 32

_METHOD_VERSION_PATTERN: Final = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,31}\Z")


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
#:
#: **Three rules decide all seventeen, and they are stated because a table of
#: seventeen hand-assigned values is a table nobody can check.**
#:
#: *An identity claim needs a person.* Bringing an entity into existence,
#: changing the name resolution matches on, claiming an external address, or
#: saying which person a mention meant are all assertions about who somebody is,
#: and section 21.4 reserves those from autonomous action.
#:
#: *A subtractive change needs a person.* `record_alias` may clear a threshold
#: because an alias is additive and non-exclusive -- adding one takes nothing
#: away and collides with nothing. Retiring or superseding one *removes a path
#: something already resolves through*, so a four-year-old message stops finding
#: its sender; ending an assignment or a relationship drops the subject out of
#: the context the plane assembles about them. Wrong-and-additive costs a row a
#: reviewer deletes. Wrong-and-subtractive costs a link nobody knows is gone.
#:
#: *Identity correction needs the operator specifically.* Section 8.4 keeps
#: merges out of default bulk acceptance, and a split is the same act read
#: backwards.
#:
#: What is left -- recording and revising assignments and relationships -- is
#: the "low-risk topic and project" class section 19.4 admits to a configured
#: threshold, and revising is the same class as recording because it corrects
#: the record it corrects rather than removing it.
_REQUIREMENT_BY_KIND: dict[EntityProposalKind, ReviewRequirement] = {
    EntityProposalKind.CREATE_ENTITY: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.UPDATE_ENTITY: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.BIND_IDENTIFIER: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.RETIRE_IDENTIFIER: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.SUPERSEDE_IDENTIFIER: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.RECORD_ALIAS: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.RETIRE_ALIAS: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.SUPERSEDE_ALIAS: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.RECORD_ASSIGNMENT: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.REVISE_ASSIGNMENT: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.END_ASSIGNMENT: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.RECORD_RELATIONSHIP: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.REVISE_RELATIONSHIP: ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY,
    EntityProposalKind.END_RELATIONSHIP: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.RESOLVE_MENTION: ReviewRequirement.REQUIRES_REVIEW,
    EntityProposalKind.MERGE_ENTITIES: ReviewRequirement.REQUIRES_OPERATOR,
    EntityProposalKind.SPLIT_IDENTITY: ReviewRequirement.REQUIRES_OPERATOR,
}


def requirement_for(kind: EntityProposalKind) -> ReviewRequirement:
    """What `kind` requires before it may be accepted.

    Derived rather than stored, so a proposal cannot be written with a weaker
    requirement than its kind carries -- which is the shape this rule would fail
    in if it were a column.
    """
    return _REQUIREMENT_BY_KIND[kind]


def initial_state_for(kind: EntityProposalKind) -> EntityProposalState:
    """The state a newly recorded proposal of `kind` is written in.

    **Derived from the requirement, and that is the whole of it.** `WP-RI-B-05`
    added `NEEDS_REVIEW` to this plane precisely so that "a person has to look
    at this" could be a state rather than a fact a reader had to recompute, and
    then wrote `PROPOSED` for all seventeen kinds anyway, because widening
    `EntityProposal.is_open` without widening the repository's `UPDATE`
    predicate would have made the record claim a decision was available that the
    server refused. Both are widened now, and this is where the claim is made.

    So a queue filtered to `NEEDS_REVIEW` is the reviewer's queue and a queue
    filtered to `PROPOSED` is what a configured threshold may act on -- and
    neither reader has to hold a copy of `_REQUIREMENT_BY_KIND` to tell them
    apart. A kind added to that mapping gets its initial state from the same
    rule on the same day; there is no second table to forget.

    `REQUIRES_OPERATOR` lands in `NEEDS_REVIEW` beside `REQUIRES_REVIEW` rather
    than in a state of its own, because the *state* says a person must look and
    the *requirement* says which person may act -- and `_decide` reads the
    requirement, not the state, when it refuses a merge to a caller declaring no
    operator authority. A third open state would put that rule in two places.

    Both answers are in `UNDECIDED_PROPOSAL_STATES`, and a test holds that over
    every kind: a proposal that arrived already decided is the failure this
    whole plane exists to prevent.
    """
    if requirement_for(kind) is ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY:
        return EntityProposalState.PROPOSED
    return EntityProposalState.NEEDS_REVIEW


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

    **On the payload, and on the reasoning this record used to carry.** WP-RI-06
    stored `payload` as untyped string pairs and argued: "a proposal is a request
    to call one of six repository writes, and typing six shapes into this record
    would duplicate the six signatures that already exist. The service that
    applies a proposal is where the shape is checked, because that is where
    getting it wrong is caught." That was true of the record it described --
    nothing could reach `propose` except this repository's own service, so the
    only writer was the one that also read it back.

    It is not true of this one. WP-05 publishes `entities.proposals.create`,
    which makes the payload a remote caller's mapping, and the field set of a
    caller-supplied mapping is precisely what "checked where it is applied"
    cannot defend: by the time an applier reads `principal_id` out of a payload,
    the caller has already named the Principal, and an applier that ignored the
    key would leave it stored as evidence of an assertion the server never
    accepted. So the shape is checked where the value is *admitted*, and
    `EntityProposalPayload` is where. The old argument's other half survives
    intact and is stated in that module: the schema owns which fields exist and
    the canonical command still owns what they mean.

    **Method, and why the server owns it.** `method`/`method_version` say what
    produced the request, and `model_id`/`model_version` are permitted only for
    `LOCAL_MODEL` -- a deterministic proposal naming a model would be claiming a
    model ran, and a model proposal naming none would be a model conclusion
    filed under no authority at all. Both are refused. This is the same pair
    `RelationshipMemoryProposal` carries and the same rule it enforces, because
    it is the same question about a different subject.

    **`expected_target_version` is nullable, and which kinds leave it null is a
    property of the kind.** It names the version of the one record this proposal
    changes: the alias for `retire_alias`, the relationship for
    `revise_relationship`. Creating kinds have no such record yet, so they leave
    it null and the parent versions are read *fresh at promotion* rather than
    carried from proposal time -- a version read when a proposal was filed and
    replayed when a reviewer accepted it days later would be a stale-write check
    that had stopped checking anything.

    **`dedupe_sha256` is the whole of open-equivalent dedupe** and is required
    even on a decided proposal: the partial unique index is scoped by state, so
    a row that left the open set still has to carry the digest that would
    collide if it came back.
    """

    proposal_id: str
    principal_id: str
    kind: EntityProposalKind
    state: EntityProposalState
    payload: EntityProposalPayload
    observation_ids: tuple[str, ...]
    proposed_at: datetime
    proposed_by: str
    method: EntityProposalMethod
    method_version: str
    dedupe_sha256: str
    model_id: str | None = None
    model_version: str | None = None
    expected_target_version: int | None = None
    review_case_id: str | None = None
    accepted_record_type: MutationRecordFamily | None = None
    accepted_record_id: str | None = None
    accepted_record_version: int | None = None
    invalidated_reason: str | None = None
    superseded_at: datetime | None = None
    #: The proposal that replaced this one, when a reprocess produced a
    #: successor against current evidence. Nullable in both directions: a
    #: proposal can be superseded with nothing to point at -- a merge preview
    #: invalidating what it made unanswerable, say -- and a successor pointer
    #: without supersession would be a live proposal claiming to have been
    #: replaced. `WP-RI-B-05` adds the column and the writer
    #: (`EntitiesRepository.supersede_proposal`); the `reprocess` disposition
    #: that mints the successor is the Review plane's.
    superseded_by_proposal_id: str | None = None
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
        if not isinstance(self.payload, EntityProposalPayload):
            raise ValueError("a proposal carries a schema-checked payload")
        if self.payload.kind is not self.kind:
            raise ValueError("a proposal's payload is the payload of its own kind")
        if not self.proposed_by.strip():
            raise ValueError("a proposal names what proposed it")
        for observation_id in self.observation_ids:
            validate_identifier(observation_id, IdKind.ENTITY_OBSERVATION)
        if len(set(self.observation_ids)) != len(self.observation_ids):
            raise ValueError("a proposal cites each observation once")
        self._check_method()
        # The same `_SHA256` a mutation-ledger request digest is checked
        # against: a dedupe column that admitted anything would admit a
        # producer's own opaque token, and the uniqueness rule would then be
        # over whatever that producer chose to put there.
        if not _SHA256.fullmatch(self.dedupe_sha256):
            raise ValueError("a proposal's dedupe digest is a sha256 digest")
        if self.expected_target_version is not None:
            if self.expected_target_version < 0:
                raise ValueError("an expected target version is not negative")
            if (
                self.expected_target_version == 0
                and self.kind is not EntityProposalKind.RESOLVE_MENTION
            ):
                raise ValueError("only mention resolution may expect target version zero")
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        self._check_result()
        ensure_utc(self.proposed_at)
        self._check_decision()

    def _check_method(self) -> None:
        if not isinstance(self.method, EntityProposalMethod):
            raise ValueError("a proposal names a known method")
        if not _METHOD_VERSION_PATTERN.fullmatch(self.method_version):
            raise ValueError("a proposal names its method version as a bounded lowercase token")
        if (self.method is EntityProposalMethod.LOCAL_MODEL) is not (self.model_id is not None):
            raise ValueError("a model proposal names its model, and only a model proposal does")
        if (self.model_id is None) is not (self.model_version is None):
            raise ValueError("a named model states its version")
        for token in (self.model_id, self.model_version):
            if token is not None and not _METHOD_VERSION_PATTERN.fullmatch(token):
                raise ValueError("a model identity is a bounded lowercase token")

    def _check_result(self) -> None:
        # One direction only, and the asymmetry is section 15's. An accepted
        # `merge_entities` or `split_identity` proposal establishes reviewed
        # intent and produces no canonical record at all -- identity mutation is
        # a separate operator act through `entities.merge` -- so "accepted"
        # cannot imply "named a record". What does hold is the other way round:
        # a record named by a proposal nobody accepted would be a promotion with
        # no acceptance behind it.
        if self.accepted_record_id is not None and self.state not in ACCEPTED_PROPOSAL_STATES:
            raise ValueError("a proposal names the record it became only when it was accepted")
        if self.accepted_record_id is not None and self.kind in IDENTITY_CORRECTION_PROPOSAL_KINDS:
            raise ValueError("an accepted identity correction records intent, not a record")
        named = (
            self.accepted_record_type is not None,
            self.accepted_record_id is not None,
            self.accepted_record_version is not None,
        )
        if len(set(named)) != 1:
            raise ValueError("an accepted record is named by its family, identifier and version")
        if self.accepted_record_type is not None and not isinstance(
            self.accepted_record_type, MutationRecordFamily
        ):
            raise ValueError("an accepted record names a known family")
        if self.accepted_record_version is not None and self.accepted_record_version < 1:
            raise ValueError("an accepted record version is a positive integer")
        # A reason explains a *departure*, which is the rule `state_reason`
        # follows on an observation: an invalidated proposal with no reason
        # records that its basis failed without recording how, and any other
        # state carrying one attributes a refusal to a proposal nobody refused.
        if (self.state is EntityProposalState.INVALIDATED) is not (
            self.invalidated_reason is not None
        ):
            raise ValueError("an invalidated proposal records why, and only an invalidated one")
        if self.invalidated_reason is not None:
            if not self.invalidated_reason.strip():
                raise ValueError("an invalidation reason is not blank")
            if len(self.invalidated_reason) > ENTITY_CHANGE_REASON_LIMIT:
                raise ValueError("an invalidation reason is bounded")

    def _check_decision(self) -> None:
        decided = self.state in _DECIDED_PROPOSAL_STATES
        if decided != (self.decided_by is not None):
            raise ValueError("a decided proposal names who decided it, and only a decided one")
        if (self.decided_at is not None) != (self.decided_by is not None):
            raise ValueError("a decision has both an actor and a moment")
        if self.decided_at is not None:
            ensure_utc(self.decided_at)
            if self.decided_at < self.proposed_at:
                raise ValueError("a proposal cannot be decided before it was proposed")
        # Supersession is not a decision and carries its own moment. A proposal
        # a successor overtook was never disposed of by anyone, so recording it
        # under `decided_at` would put an actor on an event that had none.
        if (self.state is EntityProposalState.SUPERSEDED) is not (self.superseded_at is not None):
            raise ValueError("a superseded proposal records when, and only a superseded one")
        if self.superseded_at is not None:
            ensure_utc(self.superseded_at)
            if self.superseded_at < self.proposed_at:
                raise ValueError("a proposal cannot be superseded before it was proposed")
        # One direction, like the accepted-record rule above and for the same
        # reason: a successor pointer on a live proposal would say it had been
        # replaced while it was still awaiting a decision, but a proposal may be
        # superseded by something that is not another proposal and then has
        # nothing to name.
        if self.superseded_by_proposal_id is not None:
            validate_identifier(self.superseded_by_proposal_id, IdKind.ENTITY_PROPOSAL)
            if self.state is not EntityProposalState.SUPERSEDED:
                raise ValueError("only a superseded proposal names its successor")
            if self.superseded_by_proposal_id == self.proposal_id:
                raise ValueError("a proposal is not its own successor")

    @property
    def requirement(self) -> ReviewRequirement:
        """What must happen before this may be accepted."""
        return requirement_for(self.kind)

    @property
    def is_open(self) -> bool:
        """Whether this proposal is still awaiting its first decision.

        `UNDECIDED_PROPOSAL_STATES`, which is `PROPOSED` and `NEEDS_REVIEW`.
        This was `PROPOSED` alone at `WP-RI-B-05`'s first commit, and the reason
        recorded for the narrowness was that `EntitiesRepository.decide_proposal`
        settles a decision at the server with `state = 'proposed'` inside the
        `UPDATE` predicate -- so widening the property alone would make the
        record claim a decision was available that the database would refuse,
        and the caller would see a scope error rather than the refusal it hit.
        That reason was right, and it was applied to too small a population.
        `initial_state_for` now writes `NEEDS_REVIEW` for every kind a person
        has to look at, and `decide_proposal`'s predicate was widened with it --
        but `invalidate_proposal`, which is the merge path's way of closing a
        proposal an identity correction made unanswerable, kept the `proposed`
        literal. It was not the predicate anybody was looking at, and a governed
        merge naming an entity with a review-requiring proposal failed outright
        as a result.

        So the rule this property carries is about a *population*, not about one
        statement: every statement that guards "has this been decided yet" reads
        this tuple, and the two that do are `decide_proposal` and
        `invalidate_proposal`. A third would have to read it too. `is_open` is
        also what `IdentityCorrectionService` selects on when it plans which
        proposals a merge must close, which is why a statement that disagrees
        with this property does not merely refuse -- it refuses something the
        planner already committed to.

        `DEFERRED` is still absent, and that is not an oversight: a deferred
        proposal was decided once. Routing a deferral back is the Review plane's
        disposition and widens the same tuple when it lands.

        Distinct from `OPEN_EQUIVALENT_PROPOSAL_STATES`, which answers a
        different question -- whether a *second identical proposal* would be a
        duplicate -- and answers it for a deferred proposal too.
        """
        return self.state in UNDECIDED_PROPOSAL_STATES


@dataclass(frozen=True, slots=True)
class EntityProposalEvidenceLink:
    """One exact record a proposal rests on.

    Three evidence kinds where `EntityProposal.observation_ids` holds one, and a
    role where it holds none. That array can say "this proposal cites these
    observations"; it cannot cite the capture span a user's own note came from,
    it cannot cite a knowledge record, and it cannot distinguish an observation
    that *argues against* the proposal from one that supports it. A proposal
    plane that could only accumulate supporting references is a plane that can
    only ever make a candidate look better founded than it is, which is the
    argument `EvidenceRole.COUNTEREVIDENCE` already records one record over.

    So this table is the complete evidence target and the array is the Phase A
    shape that preceded it. The array is *not* removed here: dropping a column
    is not an additive migration, and every writer of it belongs to work
    packages this one does not own. Whoever moves those writers drops it.

    **No opaque identifier of its own, and that is a decision.** This plane
    gives a record its own identifier prefix when something has to point *at*
    it -- `entity_fact_evidence_links` carries `link_id` because
    `entity_resolution_decisions.evidence_link_ids` cites links by identifier.
    Nothing cites one of these: a proposal is the addressable record and its
    evidence is read through it. `(proposal_id, sequence)` is the ordering key
    `entity_resolution_decisions` already uses for the same shape, and it makes
    "the third piece of evidence for this proposal" nameable without promising a
    prefix nothing issues.

    **No `authority` column either**, unlike its sibling on canonical facts. A
    proposal has no mutation authority -- that is what makes it a proposal.
    Authority is established when a reviewer accepts it, and
    `entity_fact_evidence_links.authority` is where that gets recorded, on the
    fact rather than on the request.
    """

    proposal_id: str
    principal_id: str
    sequence: int
    role: EvidenceRole
    created_at: datetime
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_id, IdKind.ENTITY_PROPOSAL)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.sequence < 1:
            raise ValueError("proposal evidence is numbered from one")
        if not isinstance(self.role, EvidenceRole):
            raise ValueError("proposal evidence carries a known role")
        named = [
            target
            for target in (self.entity_observation_id, self.capture_span_id, self.knowledge_id)
            if target is not None
        ]
        if len(named) != 1:
            raise ValueError("proposal evidence names exactly one evidence record")
        if self.entity_observation_id is not None:
            validate_identifier(self.entity_observation_id, IdKind.ENTITY_OBSERVATION)
        if self.capture_span_id is not None:
            validate_identifier(self.capture_span_id, IdKind.SPAN)
        if self.knowledge_id is not None:
            validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        ensure_utc(self.created_at)


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
