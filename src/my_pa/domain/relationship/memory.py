"""Relationship Memory: durable, entity-bound knowledge the user meant to keep.

A Relationship Memory is one statement about one generalized `Entity` that the
user intentionally preserved — a preference, an interest, an important date, a
concern, a caution — held so that a later profile view or briefing can use it
without mistaking a private note for an externally proven fact.

**It is a record class of its own, and every alternative was rejected for a
reason.** `EntityObservation` is evidence that a source supplied a value used in
resolution, and overloading it would make "this mailbox spelled her name that
way" and "she prefers a phone call" the same kind of row. The legacy
`RelationshipEvent(OBSERVATION)` is Person-only, carries no versioned statement
and has a different acceptance model. A Quick Capture is the user's unstructured
text at the moment they wrote it, which is a *source* for a memory rather than
the memory. A JSON column on `entities` would put a narrative body on the
identity row and make every entity read a read of private notes. So this module
declares the aggregate, its immutable version chain, and the closed vocabularies
the schema checks against.

**Kind and authority are separate axes, and that separation is the whole point.**
`MemoryKind` says what the information *means*; `MemoryAuthority` says why the
product may present it and with what epistemic status. "Prefers a phone call" is
a `COMMUNICATION_PREFERENCE` whether the user typed it or a reviewer promoted it
from an email, and the two differ only in authority. Collapsing them would make
every user note look like a finding.

**Direct user authorship is ADR-003's third authority class.** The committed text
is source-authoritative for *what the user wrote*, never for whether it is true
about the subject, and a version carries the bindings ADR-003 clause 6 requires:
principal, opaque identity, monotonic number, exact text, a digest of it, server
receipt time, classification, the idempotency key that admitted it, and a
correlation reference. A version that cannot bind those is refused rather than
stored partially.

**Two authorities are deliberately absent.** `model_inference` and
`unresolved_claim` are not members of `MemoryAuthority` at all, because a
vocabulary that named them would be the first half of letting a model write one.
They belong to `MemoryProposalState` until a human decides, which is the
structural form of "models may not silently create active memory".

**Narrative content is immutable per version.** There is no in-place edit and no
delete: a correction appends a successor and the predecessor stays retrievable,
and withdrawal is `MemoryLifecycle.ARCHIVED`, which `restore` undoes. The schema
enforces the first with an append-only trigger and the second by having no
member that could mean "gone".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Final

from my_pa.domain.capture.proposal import ProposalState, RiskClass
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.entity import EntityType

__all__ = [
    "MAX_CONTEXT_LINKS_PER_VERSION",
    "MAX_CORRECTION_REASON_CHARACTERS",
    "MAX_QUALIFIER_CHARACTERS",
    "MAX_STATEMENT_CHARACTERS",
    "MAX_STRUCTURED_VALUE_BYTES",
    "MEMORY_REVIEW_RISK_CLASS",
    "MEMORY_STRUCTURED_SCHEMAS",
    "PERSON_ONLY_KINDS",
    "STRUCTURED_VALUE_KINDS",
    "CommunicationChannel",
    "CommunicationStance",
    "ContextLinkAuthority",
    "ContextLinkRole",
    "ContextLinkTargetType",
    "DatePrecision",
    "DateRecurrence",
    "EvidenceLinkRole",
    "MemoryActorClass",
    "MemoryAdmission",
    "MemoryAuthority",
    "MemoryBoundsError",
    "MemoryConflictError",
    "MemoryContextLink",
    "MemoryEvidenceLink",
    "MemoryKind",
    "MemoryKindNotPermittedError",
    "MemoryLifecycle",
    "MemoryOperation",
    "MemoryProposalEvidence",
    "MemoryProposalMethod",
    "MemoryProposalState",
    "MemoryReceipt",
    "MemoryStructuredValueError",
    "MergedSubjectError",
    "RelationshipMemory",
    "RelationshipMemoryError",
    "RelationshipMemoryProposal",
    "RelationshipMemoryReviewCase",
    "RelationshipMemoryVersion",
    "StaleMemoryVersionError",
    "classification_floor_for",
    "satisfies_floor",
    "statement_digest",
    "validate_statement",
    "validate_structured_value",
]


#: The most characters one memory statement may carry.
#:
#: Well under `MAX_CAPTURE_CHARACTERS` (100,000) and deliberately so: a capture
#: is a transcript the user dictated after a meeting, and a memory is one
#: statement about one person. A ceiling that admitted a transcript would invite
#: the record class this module exists to keep distinct from Quick Capture, and
#: 4,000 characters is several paragraphs — more than any of the contract's own
#: examples and far more than a preference needs.
MAX_STATEMENT_CHARACTERS: Final = 4_000

#: The most bytes one serialized structured value may occupy.
#:
#: Small on purpose. The structured value is subordinate to the statement and
#: exists for filtering and rendering, so the schemas below are a handful of
#: scalars each; two kibibytes is an order of magnitude more than the largest of
#: them and still far too small to become a second content channel.
MAX_STRUCTURED_VALUE_BYTES: Final = 2_048

#: The most characters a `communication_preference` qualifier may carry.
MAX_QUALIFIER_CHARACTERS: Final = 200

#: The most characters a correction reason may carry. Bounded because it is
#: caller-supplied text on a write path and it is disclosed in history.
MAX_CORRECTION_REASON_CHARACTERS: Final = 500

#: The most context links one version may declare.
#:
#: A memory is scoped to a handful of things at most — "on Riverside", "with the
#: closeout team" — and an unbounded list would make one write an unbounded
#: number of validated lookups, each of which is a round trip that must prove
#: same-Principal ownership.
MAX_CONTEXT_LINKS_PER_VERSION: Final = 10


class RelationshipMemoryError(Exception):
    """A Relationship Memory rule this layer refused.

    Named `RelationshipMemoryError` rather than `MemoryError`, which is a Python
    builtin meaning the interpreter is out of memory. Shadowing it in a module
    every layer imports would make an ordinary `except MemoryError` somewhere
    else catch a validation refusal, or miss a real allocation failure.
    """


class MemoryBoundsError(RelationshipMemoryError):
    """A statement, structured value, or collection exceeded its ceiling."""


class MemoryStructuredValueError(RelationshipMemoryError):
    """A structured value did not validate against its kind's schema."""


class MemoryKindNotPermittedError(RelationshipMemoryError):
    """A Person-only kind was used for a subject that is not a Person."""


class StaleMemoryVersionError(RelationshipMemoryError):
    """The named expected version is no longer the aggregate's current version."""


class MemoryConflictError(RelationshipMemoryError):
    """One idempotency key is bound to a materially different request."""


class MergedSubjectError(RelationshipMemoryError):
    """The subject entity has been merged away and names a canonical successor.

    Carries the canonical identifier so the caller can be told where the subject
    went. The service must *not* follow it on a write: silently rebinding would
    turn a deliberate annotation about a historical identity into one about the
    current person, which is a different statement than the one the user made.
    """

    def __init__(self, canonical_entity_id: str) -> None:
        super().__init__("the subject entity has been merged away")
        self.canonical_entity_id = canonical_entity_id


class MemoryOperation(StrEnum):
    """Which public write one admission record describes."""

    CREATE = "create"
    REVISE = "revise"
    ARCHIVE = "archive"
    RESTORE = "restore"


class MemoryKind(StrEnum):
    """What one memory *means*, in a closed vocabulary.

    Ten members, frozen as of this revision because the schema's
    `a_memory_kind_is_known` CHECK references these values. Widening is a visible
    schema change rather than a silent one.

    The set is semantic and says nothing about trust: `SENSITIVITY` is not a more
    privileged authority, it is a different subject matter that carries a
    stricter classification floor (`classification_floor_for`).
    """

    GENERAL_NOTE = "general_note"
    PERSONAL_DETAIL = "personal_detail"
    IMPORTANT_DATE = "important_date"
    INTEREST = "interest"
    COMMUNICATION_PREFERENCE = "communication_preference"
    WORKING_PREFERENCE = "working_preference"
    CONCERN = "concern"
    SENSITIVITY = "sensitivity"
    FOLLOW_UP_CONTEXT = "follow_up_context"
    USER_PINNED_CONTEXT = "user_pinned_context"


#: The kinds whose semantics require the subject to be a Person.
#:
#: Four rather than ten, and the four are the ones whose meaning is about a human
#: being: a biographical detail, a birthday or anniversary, a personal interest,
#: and a caution about how to treat someone. The other six are meaningful about
#: an organization, a project or a work package — a project can have a working
#: preference ("wants cost issues in writing"), a concern, a follow-up, a pin,
#: and a general note, and a team can have a communication preference.
#:
#: `SENSITIVITY` is deliberately *not* here, and that is the one that needs
#: saying: "do not raise the Riverside dispute" is a caution about a topic, and
#: the topic can as easily belong to an organization as to a person. Restricting
#: it to People would push the same statement into `GENERAL_NOTE` for a vendor,
#: which is exactly the downgrade its classification floor exists to prevent.
PERSON_ONLY_KINDS: Final[frozenset[MemoryKind]] = frozenset(
    {
        MemoryKind.PERSONAL_DETAIL,
        MemoryKind.IMPORTANT_DATE,
        MemoryKind.INTEREST,
    }
)


class MemoryAuthority(StrEnum):
    """Why the product may present a memory, and with what epistemic status.

    Four members, and the two that are missing are the decision. `model_inference`
    and `unresolved_claim` appear in the parent specification's trust vocabulary
    and are *not* memory authorities: a record carrying either is a proposal, and
    `MemoryProposalState` is where it lives until a human decides. Naming them
    here would give a promotion path a value to write.

    `USER_AUTHORED_PRIVATE_NOTE` reuses the string
    `relationship.profile.EvidenceAuthority` already spells, because it is the
    same concept and a second spelling would make two rows about the same note
    disagree. It is not a reuse of the *enum*: that one is the legacy Person
    profile's evidence vocabulary and carries `CONTRADICTION` and
    `STALE_ASSERTION`, which are relationships between claims rather than
    authorities a stored memory could hold.
    """

    USER_AUTHORED_PRIVATE_NOTE = "user_authored_private_note"
    USER_CONFIRMED_ASSERTION = "user_confirmed_assertion"
    SOURCE_BACKED_ASSERTION = "source_backed_assertion"
    PUBLIC_ASSERTION = "public_assertion"


#: The one authority a direct user write may carry.
#:
#: A single-member set rather than a check written out at each call site, so the
#: rule "a public create or revise cannot self-assert a source-backed, public or
#: confirmed authority" has one statement that the command layer, the service and
#: the schema all read.
DIRECT_USER_AUTHORITY: Final = MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE


class MemoryLifecycle(StrEnum):
    """Whether a memory is in the current set.

    Two members, and there is deliberately no third, for the reason
    `documents.DocumentState` gives: `deleted` would be a state whose only honest
    implementation destroys the user's own record, hard deletion is unresolved by
    ADR-003 and reserved to the operator, and a vocabulary that named it would be
    the first half of building it.
    """

    ACTIVE = "active"
    ARCHIVED = "archived"


class MemoryActorClass(StrEnum):
    """What class of actor committed one version.

    A closed class rather than a model name or a free string. A version says it
    was written by the user, by a review promotion, or by deterministic system
    work; *which* model proposed the thing a reviewer accepted is recorded on the
    proposal, where the method and model identity belong. Putting a model name
    here would make the version row the place a caller reads to learn what wrote
    it, and the honest answer for a promotion is "a person decided".
    """

    USER = "user"
    REVIEW_PROMOTION = "review_promotion"
    SYSTEM_DETERMINISTIC = "system_deterministic"


class ContextLinkRole(StrEnum):
    """How a memory relates to the thing it is linked to."""

    APPLIES_IN = "applies_in"
    AROSE_FROM = "arose_from"
    RELATED_TO = "related_to"


class ContextLinkTargetType(StrEnum):
    """What a context link may point at.

    Closed to object families this build actually has, with a real identifier
    kind and a validation path apiece. There is deliberately no `other`: an
    unsupported context stays narrative until a real target model exists, because
    a generic escape hatch is how an unvalidated polymorphic edge gets built one
    caller at a time.

    `capture` is absent from *this* enum and present in `EvidenceLinkRole`'s
    world instead, because a capture is where a memory came *from* rather than
    where it applies — the contract draws that line and so does this.
    """

    ENTITY = "entity"
    SITUATION = "situation"
    TASK = "task"
    COMMITMENT = "commitment"


#: The identifier kind each context target type names.
CONTEXT_TARGET_ID_KINDS: Final[dict[ContextLinkTargetType, IdKind]] = {
    ContextLinkTargetType.ENTITY: IdKind.ENTITY,
    ContextLinkTargetType.SITUATION: IdKind.SITUATION,
    ContextLinkTargetType.TASK: IdKind.TASK,
    ContextLinkTargetType.COMMITMENT: IdKind.COMMITMENT,
}


class ContextLinkAuthority(StrEnum):
    """What established a context link."""

    USER_CONFIRMED = "user_confirmed"
    DETERMINISTIC = "deterministic"
    REVIEW_ACCEPTED = "review_accepted"


class EvidenceLinkRole(StrEnum):
    """How one evidence record bears on a memory version."""

    DIRECT = "direct"
    SUPPORTING = "supporting"
    COUNTEREVIDENCE = "counterevidence"


class MemoryProposalState(StrEnum):
    """Where a candidate memory is in the review posture.

    A proposal in any of these states is *not* current memory. The read paths
    filter on the aggregate table, which a proposal never enters until a decision
    creates one, so "not yet accepted" is structural rather than a predicate a
    query could forget.
    """

    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    CORRECTED_ACCEPTED = "corrected_accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class MemoryProposalMethod(StrEnum):
    """How a candidate memory was produced.

    Three members, and the absences are deliberate: there is no `cloud_model` and
    no `hybrid`, because no path in this build routes private relationship text
    to a cloud model and a vocabulary that named one would advertise a method a
    caller could ask for and a reviewer could believe had run.
    """

    DETERMINISTIC = "deterministic"
    RULE = "rule"
    LOCAL_MODEL = "local_model"


class DatePrecision(StrEnum):
    """How much of an important date is actually known."""

    MONTH_DAY = "month_day"
    DATE = "date"
    YEAR_ONLY = "year_only"
    APPROXIMATE = "approximate"


class DateRecurrence(StrEnum):
    """Whether an important date recurs."""

    NONE = "none"
    ANNUAL = "annual"


class CommunicationChannel(StrEnum):
    """The channel a communication preference names."""

    PHONE = "phone"
    EMAIL = "email"
    TEAMS = "teams"
    SMS = "sms"
    IN_PERSON = "in_person"
    OTHER = "other"


class CommunicationStance(StrEnum):
    """How the subject regards the named channel."""

    PREFERRED = "preferred"
    AVOID = "avoid"
    ACCEPTABLE = "acceptable"


#: The structured-value schema identifier for each kind that has one.
#:
#: The envelope stores the schema name beside the value so a row written under
#: `v1` is never reinterpreted under a later schema — the failure mode a bare
#: JSON blob has and the reason the contract asks for a versioned envelope.
#:
#: Seven kinds have no entry, and that is the decision rather than an omission: a
#: `general_note`, a `concern`, a `follow_up_context`, a pin, a
#: `personal_detail`, a `working_preference` and a `sensitivity` are narrative,
#: and inventing a schema for one because JSONB is available is exactly the CRM
#: data-entry the product refuses. `sensitivity` is the one worth naming: it has
#: no structured topic classification *on purpose*, because a machine-readable
#: taxonomy of what to avoid discussing with someone is the automated
#: psychological profiling this feature is forbidden to build.
MEMORY_STRUCTURED_SCHEMAS: Final[dict[MemoryKind, str]] = {
    MemoryKind.IMPORTANT_DATE: "relationship_memory.important_date.v1",
    MemoryKind.COMMUNICATION_PREFERENCE: "relationship_memory.communication_preference.v1",
    MemoryKind.INTEREST: "relationship_memory.interest.v1",
}

#: The kinds that admit a structured value at all.
STRUCTURED_VALUE_KINDS: Final[frozenset[MemoryKind]] = frozenset(MEMORY_STRUCTURED_SCHEMAS)

#: Days per month for a date with no year. February admits 29 because a
#: month-and-day birthday of 29 February is a real one, and the record carries no
#: year to check it against — refusing it would lose a date the user has.
_DAYS_IN_MONTH: Final[dict[int, int]] = {
    1: 31,
    2: 29,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}

#: The range a recorded year may fall in. Bounded rather than unbounded so a
#: transposed digit is refused at the edge rather than stored and rendered.
_MIN_YEAR: Final = 1900
_MAX_YEAR: Final = 2200


def classification_floor_for(kind: MemoryKind) -> Classification:
    """The least restrictive classification `kind` may be stored at.

    `SENSITIVITY` floors at `RESTRICTED_LOCAL` and everything else at
    `PRIVATE_LOCAL`. This is a floor and not an assignment: a caller may record
    an ordinary note as restricted, which is a monotonic tightening, and may
    never record a sensitivity as merely private.
    """
    if kind is MemoryKind.SENSITIVITY:
        return Classification.RESTRICTED_LOCAL
    return Classification.PRIVATE_LOCAL


#: Which classifications are at least as restrictive as which, as a rank. Used to
#: check the floor without enumerating pairs; a higher rank is more restrictive.
_CLASSIFICATION_RANK: Final[dict[Classification, int]] = {
    Classification.SYNTHETIC_TEST: 0,
    Classification.PRIVATE_LOCAL: 1,
    Classification.RESTRICTED_LOCAL: 2,
}


def satisfies_floor(classification: Classification, kind: MemoryKind) -> bool:
    """Whether `classification` is at least as restrictive as `kind` requires."""
    floor = classification_floor_for(kind)
    return _CLASSIFICATION_RANK[classification] >= _CLASSIFICATION_RANK[floor]


def validate_statement(statement: str) -> str:
    """Return `statement` unchanged, or refuse it.

    Two statements rather than one condition, for the reason
    `documents.validate_managed_title` splits its own: domain models are plain
    dataclasses with no runtime type enforcement, so a non-string really can
    reach here and must fail as a domain error rather than as an incidental
    `AttributeError` from `strip()`.
    """
    if not isinstance(statement, str):
        raise MemoryBoundsError("a relationship memory statement is text")
    if not statement.strip():
        raise MemoryBoundsError("a relationship memory carries a non-blank statement")
    if len(statement) > MAX_STATEMENT_CHARACTERS:
        raise MemoryBoundsError(
            f"a relationship memory statement is at most {MAX_STATEMENT_CHARACTERS} characters"
        )
    return statement


def statement_digest(statement: str) -> str:
    """The SHA-256 of the exact committed statement, lowercase hexadecimal.

    Over `statement.encode("utf-8")` and nothing else: no normalization, no
    trimming, no case folding. The digest identifies the bytes this product
    committed, so any transformation between the text and the hash would make it
    a digest of something the user did not write.
    """
    return hashlib.sha256(statement.encode("utf-8")).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MemoryStructuredValueError(message)


def _optional_int(value: object, name: str) -> int | None:
    """One optional whole number out of a caller's JSON object.

    `type(value) is int` rather than `isinstance`, because `bool` is a subclass
    of `int` and `True` is not a month. The narrowing is a real `if` rather than
    a `_require` plus a cast: `_require` raises but says nothing a type checker
    can read, so the value stayed `object` and the conversion needed a
    suppression — and a suppression is what the dependency-floor job forbids.
    """
    if value is None:
        return None
    if type(value) is not int:
        raise MemoryStructuredValueError(f"{name} is a whole number")
    return value


def _validate_important_date(value: dict[str, Any]) -> None:
    """Validate an `important_date` v1 value, and never infer what is missing."""
    permitted = {"month", "day", "year", "precision", "recurrence"}
    _require(set(value) <= permitted, "an important date carries only its own fields")
    month = _optional_int(value.get("month"), "an important date month")
    day = _optional_int(value.get("day"), "an important date day")
    year = _optional_int(value.get("year"), "an important date year")
    precision_value = value.get("precision")
    if not isinstance(precision_value, str):
        raise MemoryStructuredValueError("an important date states its precision")
    try:
        precision = DatePrecision(precision_value)
    except ValueError as exc:
        raise MemoryStructuredValueError("an important date precision is known") from exc
    recurrence_value = value.get("recurrence", DateRecurrence.NONE.value)
    if not isinstance(recurrence_value, str):
        raise MemoryStructuredValueError("an important date recurrence is text")
    try:
        DateRecurrence(recurrence_value)
    except ValueError as exc:
        raise MemoryStructuredValueError("an important date recurrence is known") from exc
    if month is not None:
        _require(1 <= month <= 12, "an important date month is between one and twelve")
    if day is not None:
        if month is None:
            # `_require` above already refused this; raising rather than
            # asserting keeps the narrowing under `-O`, where an assertion is
            # removed and the dictionary lookup below would raise `KeyError`.
            raise MemoryStructuredValueError("an important date with a day states its month")
        _require(1 <= day <= _DAYS_IN_MONTH[month], "an important date day is valid for its month")
    if year is not None:
        _require(_MIN_YEAR <= year <= _MAX_YEAR, "an important date year is within range")
    # Each precision states exactly which parts the record claims to know. The
    # point is not tidiness: `month_day` with a year present would be a record
    # whose own precision says the year is unknown while carrying one, and a
    # reader has no way to tell which half to believe.
    if precision is DatePrecision.MONTH_DAY:
        _require(
            month is not None and day is not None and year is None,
            "a month_day important date knows month and day and no year",
        )
    elif precision is DatePrecision.DATE:
        _require(
            month is not None and day is not None and year is not None,
            "a date important date knows year, month and day",
        )
    elif precision is DatePrecision.YEAR_ONLY:
        _require(
            year is not None and month is None and day is None,
            "a year_only important date knows a year and nothing finer",
        )
    else:
        _require(
            month is not None or year is not None,
            "an approximate important date knows a month or a year",
        )


def _validate_communication_preference(value: dict[str, Any]) -> None:
    """Validate a `communication_preference` v1 value.

    No contact address of any kind. The Entity identifier plane owns actual
    addresses, and admitting one here would put a second, unvalidated copy of a
    person's phone number inside a private note.
    """
    permitted = {"channel", "preference", "qualifiers"}
    _require(set(value) <= permitted, "a communication preference carries only its own fields")
    channel = value.get("channel")
    if channel is not None:
        _require(isinstance(channel, str), "a communication channel is text")
        try:
            CommunicationChannel(channel)
        except ValueError as exc:
            raise MemoryStructuredValueError("a communication channel is known") from exc
    stance = value.get("preference")
    _require(isinstance(stance, str), "a communication preference states a stance")
    try:
        CommunicationStance(str(stance))
    except ValueError as exc:
        raise MemoryStructuredValueError("a communication stance is known") from exc
    qualifiers = value.get("qualifiers")
    if qualifiers is not None:
        _require(isinstance(qualifiers, str), "a communication qualifier is text")
        _require(
            len(str(qualifiers)) <= MAX_QUALIFIER_CHARACTERS,
            "a communication qualifier is bounded",
        )


def _validate_interest(value: dict[str, Any]) -> None:
    """Validate an `interest` v1 value.

    One optional label, and no taxonomy. A controlled vocabulary of interests is
    how a protected-trait classifier gets built without anyone deciding to build
    one, so the label is whatever the user confirmed and nothing normalizes it.
    """
    _require(set(value) <= {"label"}, "an interest carries only its own fields")
    label = value.get("label")
    if label is not None:
        _require(isinstance(label, str), "an interest label is text")
        _require(bool(str(label).strip()), "an interest label is not blank")
        _require(len(str(label)) <= MAX_QUALIFIER_CHARACTERS, "an interest label is bounded")


_VALIDATORS: Final[dict[MemoryKind, Any]] = {
    MemoryKind.IMPORTANT_DATE: _validate_important_date,
    MemoryKind.COMMUNICATION_PREFERENCE: _validate_communication_preference,
    MemoryKind.INTEREST: _validate_interest,
}


def validate_structured_value(
    kind: MemoryKind, structured_value: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return the storage envelope for `structured_value`, or refuse it.

    `None` in, `None` out: a structured value is optional for every kind, and a
    memory whose meaning is entirely in its statement is the normal case.

    A value supplied for a kind with no schema is refused rather than stored
    unvalidated, which is what "arbitrary JSON is prohibited" has to mean to be
    enforceable. The returned envelope names the schema the value was checked
    against, so a later reader interprets it under the schema it was written
    under rather than under whatever the current one is.
    """
    if structured_value is None:
        return None
    if not isinstance(structured_value, dict):
        raise MemoryStructuredValueError("a structured value is a JSON object")
    if kind not in MEMORY_STRUCTURED_SCHEMAS:
        raise MemoryStructuredValueError("this memory kind carries no structured value")
    for key in structured_value:
        if not isinstance(key, str):
            raise MemoryStructuredValueError("a structured value is keyed by name")
    _VALIDATORS[kind](structured_value)
    envelope = {"schema": MEMORY_STRUCTURED_SCHEMAS[kind], "value": structured_value}
    encoded = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_STRUCTURED_VALUE_BYTES:
        raise MemoryBoundsError(f"a structured value is at most {MAX_STRUCTURED_VALUE_BYTES} bytes")
    return envelope


@dataclass(frozen=True, slots=True)
class MemoryContextLink:
    """Where one memory version applies, or what it arose from.

    Bound to the *version* rather than to the aggregate, and that is the contract's
    recommendation for a reason this module agrees with: a revision that changes
    "on Riverside, prefers writing" to "prefers writing" has changed what the
    record means, and a link hanging off the aggregate would silently reattach the
    old scope to the new statement.
    """

    context_link_id: str
    memory_version_id: str
    principal_id: str
    target_type: ContextLinkTargetType
    target_id: str
    role: ContextLinkRole
    authority: ContextLinkAuthority
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.context_link_id, IdKind.RELATIONSHIP_MEMORY_CONTEXT_LINK)
        validate_identifier(self.memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.target_type, ContextLinkTargetType):
            raise RelationshipMemoryError("a context link names a known target type")
        validate_identifier(self.target_id, CONTEXT_TARGET_ID_KINDS[self.target_type])
        if not isinstance(self.role, ContextLinkRole):
            raise RelationshipMemoryError("a context link carries a known role")
        if not isinstance(self.authority, ContextLinkAuthority):
            raise RelationshipMemoryError("a context link carries a known authority")
        ensure_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class MemoryEvidenceLink:
    """One exact record a non-direct memory version rests on.

    Exactly one target, chosen from the evidence families that exist. A direct
    user note legitimately has none: the committed statement *is* the source
    record under ADR-003, and requiring evidence for it would be requiring a note
    to cite something outside itself.
    """

    evidence_link_id: str
    memory_version_id: str
    principal_id: str
    role: EvidenceLinkRole
    created_at: datetime
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.evidence_link_id, IdKind.RELATIONSHIP_MEMORY_EVIDENCE_LINK)
        validate_identifier(self.memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.role, EvidenceLinkRole):
            raise RelationshipMemoryError("an evidence link carries a known role")
        named = [
            target
            for target in (self.entity_observation_id, self.capture_span_id, self.knowledge_id)
            if target is not None
        ]
        if len(named) != 1:
            raise RelationshipMemoryError("an evidence link names exactly one evidence record")
        if self.entity_observation_id is not None:
            validate_identifier(self.entity_observation_id, IdKind.ENTITY_OBSERVATION)
        if self.capture_span_id is not None:
            validate_identifier(self.capture_span_id, IdKind.SPAN)
        if self.knowledge_id is not None:
            validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        ensure_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class RelationshipMemoryVersion:
    """One immutable version of one memory.

    `statement` is `repr=False` for the reason
    `application.commands.CreateCapture` marks its text and
    `documents.ManagedContent` marks its bytes: a dataclass `repr` reaches a
    traceback, a log record and a pytest assertion message without anyone
    deciding it should, and this is the field that carries what the user wrote
    about another person.

    **There is no `superseded_at`, and its absence is the design.** The table is
    append-only under a trigger, so a supersession stamp would be an `UPDATE`
    the server refuses; a version is superseded exactly when another version
    names it as `prior_version_id`, which is the same fact read from the chain
    with no second writer and nothing to drift. A field declared here and
    stored nowhere would read as a value a caller could set and silently never
    be persisted.

    The bindings ADR-003 clause 6 requires are all here and all required:
    principal, opaque version identity, monotonic number, exact text, its digest,
    server receipt time, classification, the idempotency key that admitted it,
    and a correlation reference. There is no partial version.
    """

    memory_version_id: str
    memory_id: str
    principal_id: str
    version_number: int
    statement: str = field(repr=False)
    statement_sha256: str
    memory_kind: MemoryKind
    authority: MemoryAuthority
    classification: Classification
    created_by_actor: MemoryActorClass
    recorded_at: datetime
    idempotency_key: str
    correlation_id: str
    structured_value: dict[str, Any] | None = field(default=None, repr=False)
    cloud_eligible: bool = False
    observed_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    prior_version_id: str | None = None
    correction_reason: str | None = field(default=None, repr=False)
    proposal_id: str | None = None
    review_case_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        validate_identifier(self.memory_id, IdKind.RELATIONSHIP_MEMORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        if self.version_number < 1:
            raise RelationshipMemoryError("memory version numbers start at one")
        if (self.version_number == 1) is not (self.prior_version_id is None):
            raise RelationshipMemoryError("only the first memory version supersedes nothing")
        if self.prior_version_id is not None:
            validate_identifier(self.prior_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        validate_statement(self.statement)
        if self.statement_sha256 != statement_digest(self.statement):
            raise RelationshipMemoryError(
                "a memory version's digest is the digest of its own statement"
            )
        if not isinstance(self.memory_kind, MemoryKind):
            raise RelationshipMemoryError("a memory version carries a known kind")
        if not isinstance(self.authority, MemoryAuthority):
            raise RelationshipMemoryError("a memory version carries a known authority")
        if not isinstance(self.classification, Classification):
            raise RelationshipMemoryError("a memory version carries a known classification")
        if not satisfies_floor(self.classification, self.memory_kind):
            raise RelationshipMemoryError("a memory version meets its kind's classification floor")
        if not isinstance(self.created_by_actor, MemoryActorClass):
            raise RelationshipMemoryError("a memory version names a known actor class")
        if self.cloud_eligible:
            # No path sets this true. It exists as a stored column because the
            # contract requires the posture to be explicit and auditable rather
            # than absent, and refusing it here is what keeps "defaults false"
            # from being a default a later writer can quietly change.
            raise RelationshipMemoryError("relationship memory is not cloud eligible")
        if not self.idempotency_key:
            raise RelationshipMemoryError("a memory version records the key that admitted it")
        ensure_utc(self.recorded_at)
        for moment in (
            self.observed_at,
            self.effective_from,
            self.effective_to,
        ):
            if moment is not None:
                ensure_utc(moment)
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_to < self.effective_from
        ):
            raise RelationshipMemoryError(
                "a memory version's applicability does not end before it starts"
            )
        if self.correction_reason is not None:
            if not self.correction_reason.strip():
                raise RelationshipMemoryError("a correction reason is non-blank when it is given")
            if len(self.correction_reason) > MAX_CORRECTION_REASON_CHARACTERS:
                raise MemoryBoundsError("a correction reason is bounded")
        if self.structured_value is not None:
            if set(self.structured_value) != {"schema", "value"}:
                raise MemoryStructuredValueError("a stored structured value is a schema envelope")
            if self.structured_value["schema"] != MEMORY_STRUCTURED_SCHEMAS.get(self.memory_kind):
                raise MemoryStructuredValueError(
                    "a stored structured value names its own kind's schema"
                )
        if self.proposal_id is not None:
            validate_identifier(self.proposal_id, IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        if (
            self.created_by_actor is MemoryActorClass.USER
            and self.authority is not DIRECT_USER_AUTHORITY
        ):
            raise RelationshipMemoryError(
                "a user-written memory version carries user-authored authority"
            )


@dataclass(frozen=True, slots=True)
class RelationshipMemory:
    """One logical memory: stable identity, current version, and lifecycle.

    Holds no statement. The narrative lives on the versions, and an aggregate that
    carried a copy would make every listing a read of private note text and would
    give the current statement two places to disagree with itself.
    """

    memory_id: str
    principal_id: str
    subject_entity_id: str
    memory_kind: MemoryKind
    lifecycle_state: MemoryLifecycle
    current_version_id: str
    current_version_number: int
    version: int
    pinned: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.memory_id, IdKind.RELATIONSHIP_MEMORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.subject_entity_id, IdKind.ENTITY)
        validate_identifier(self.current_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        if not isinstance(self.memory_kind, MemoryKind):
            raise RelationshipMemoryError("a memory carries a known kind")
        if not isinstance(self.lifecycle_state, MemoryLifecycle):
            raise RelationshipMemoryError("a memory carries a known lifecycle state")
        if self.version < 1:
            raise RelationshipMemoryError("a memory version counter is a positive integer")
        if self.current_version_number < 1:
            raise RelationshipMemoryError("memory version numbers start at one")
        ensure_utc(self.created_at)
        ensure_utc(self.updated_at)
        if self.updated_at < self.created_at:
            raise RelationshipMemoryError("a memory cannot be updated before it is created")
        if (self.lifecycle_state is MemoryLifecycle.ARCHIVED) != (self.archived_at is not None):
            raise RelationshipMemoryError(
                "a memory is archived exactly when it records when it was archived"
            )
        if self.archived_at is not None:
            ensure_utc(self.archived_at)

    def requires_person_subject(self) -> bool:
        """Whether this memory's kind is meaningful only about a Person."""
        return self.memory_kind in PERSON_ONLY_KINDS


def check_kind_permits_subject(kind: MemoryKind, entity_type: EntityType) -> None:
    """Refuse a Person-only kind for a subject that is not a Person."""
    if kind in PERSON_ONLY_KINDS and entity_type is not EntityType.PERSON:
        raise MemoryKindNotPermittedError("this memory kind describes a person")


@dataclass(frozen=True, slots=True)
class RelationshipMemoryProposal:
    """A candidate memory that is not memory yet.

    It lives in its own table and never in `relationship_memories`, which is what
    makes "a proposal cannot appear in an ordinary memory read" structural rather
    than a filter a query could omit. Acceptance creates or revises a real memory
    and records the resulting identity here; rejection and deferral leave no
    memory at all.
    """

    memory_proposal_id: str
    principal_id: str
    subject_entity_id: str
    proposed_kind: MemoryKind
    proposed_statement: str = field(repr=False)
    proposed_statement_sha256: str
    state: MemoryProposalState
    method: MemoryProposalMethod
    method_version: str
    classification: Classification
    proposed_at: datetime
    structured_value: dict[str, Any] | None = field(default=None, repr=False)
    model_id: str | None = None
    model_version: str | None = None
    review_case_id: str | None = None
    accepted_memory_id: str | None = None
    accepted_memory_version_id: str | None = None
    invalidated_reason: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.memory_proposal_id, IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.subject_entity_id, IdKind.ENTITY)
        if not isinstance(self.proposed_kind, MemoryKind):
            raise RelationshipMemoryError("a memory proposal carries a known kind")
        validate_statement(self.proposed_statement)
        if self.proposed_statement_sha256 != statement_digest(self.proposed_statement):
            raise RelationshipMemoryError("a proposal's digest is the digest of its own statement")
        if not isinstance(self.state, MemoryProposalState):
            raise RelationshipMemoryError("a memory proposal carries a known state")
        if not isinstance(self.method, MemoryProposalMethod):
            raise RelationshipMemoryError("a memory proposal names a known method")
        if not self.method_version.strip():
            raise RelationshipMemoryError("a memory proposal names the version of its method")
        if not isinstance(self.classification, Classification):
            raise RelationshipMemoryError("a memory proposal carries a known classification")
        if not satisfies_floor(self.classification, self.proposed_kind):
            raise RelationshipMemoryError("a memory proposal meets its kind's classification floor")
        if (self.method is MemoryProposalMethod.LOCAL_MODEL) is not (self.model_id is not None):
            raise RelationshipMemoryError(
                "a model proposal names its model, and only a model proposal does"
            )
        if (self.model_id is None) is not (self.model_version is None):
            raise RelationshipMemoryError("a named model states its version")
        ensure_utc(self.proposed_at)
        accepted = self.state in (
            MemoryProposalState.ACCEPTED,
            MemoryProposalState.CORRECTED_ACCEPTED,
        )
        if accepted != (self.accepted_memory_id is not None):
            raise RelationshipMemoryError(
                "a proposal names an accepted memory exactly when it was accepted"
            )
        if (self.accepted_memory_id is None) is not (self.accepted_memory_version_id is None):
            raise RelationshipMemoryError(
                "an accepted proposal names both the memory and the version"
            )
        if self.accepted_memory_id is not None:
            validate_identifier(self.accepted_memory_id, IdKind.RELATIONSHIP_MEMORY)
        if self.accepted_memory_version_id is not None:
            validate_identifier(self.accepted_memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        if self.structured_value is not None and set(self.structured_value) != {"schema", "value"}:
            raise MemoryStructuredValueError("a proposal's structured value is a schema envelope")


@dataclass(frozen=True, slots=True)
class MemoryProposalEvidence:
    """One exact record a proposal rests on. Same discipline as accepted memory."""

    proposal_evidence_id: str
    memory_proposal_id: str
    principal_id: str
    role: EvidenceLinkRole
    created_at: datetime
    entity_observation_id: str | None = None
    capture_span_id: str | None = None
    knowledge_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_evidence_id, IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE)
        validate_identifier(self.memory_proposal_id, IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.role, EvidenceLinkRole):
            raise RelationshipMemoryError("proposal evidence carries a known role")
        named = [
            target
            for target in (self.entity_observation_id, self.capture_span_id, self.knowledge_id)
            if target is not None
        ]
        if len(named) != 1:
            raise RelationshipMemoryError("proposal evidence names exactly one evidence record")
        if self.entity_observation_id is not None:
            validate_identifier(self.entity_observation_id, IdKind.ENTITY_OBSERVATION)
        if self.capture_span_id is not None:
            validate_identifier(self.capture_span_id, IdKind.SPAN)
        if self.knowledge_id is not None:
            validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        ensure_utc(self.created_at)


#: The risk class every Relationship Memory review case is opened at.
#:
#: A module constant rather than a stored column or a per-case computation, and
#: the distinction is the point: nothing here grades the *subject*. Every
#: candidate memory carries the same consequence — accepting one writes one
#: private statement about one entity into the current set — so a per-case
#: number would be a judgement with nothing behind it, and a stored one would be
#: a column on the relationship surface whose name is `risk`.
#:
#: `MODERATE` is the value `GoodNotesReviewCase` opens at for the same reason:
#: it is the middle of the shared `RiskClass` vocabulary, it widens no frozen
#: capture-plane CHECK, and it neither suppresses the case from a reviewer's
#: attention nor escalates it above the review work that actually is critical.
MEMORY_REVIEW_RISK_CLASS: Final = RiskClass.MODERATE


@dataclass(frozen=True, slots=True)
class RelationshipMemoryReviewCase:
    """One candidate memory exposed through the ordinary canonical Review surface.

    Relationship Memory is the *third* subject kind on the one Review surface,
    after capture proposals and GoodNotes regions, and this mirrors
    `GoodNotesReviewCase` deliberately rather than inventing a fourth review
    vocabulary. `ProposalState`, `RiskClass` and `Disposition` are the shared
    capture-plane ones, reused as values and not as tables: nothing here writes
    a capture row, so no frozen capture-plane CHECK has to widen to admit a
    memory proposal.

    **It carries no statement text, and that absence is the disclosure control.**
    A `sensitivity` memory floors at `RESTRICTED_LOCAL` and the read plane
    withholds restricted statements from search and from pages; putting the
    *proposed* text on a review listing would be a second disclosure channel for
    exactly the text the accepted form is withheld on, reached by a read that has
    no `include_restricted` decision to make. The field is therefore absent from
    the model rather than filtered in the payload, so a later writer cannot
    expose it by editing a formatter. A reviewer who needs the words reads the
    proposal through the memory plane, where the classification is enforced.

    `proposed_kind` *is* disclosed, and that is the deliberate other half: a
    reviewer being asked to decide has to know they are deciding a sensitivity
    rather than a birthday, and the kind is the least that says so.

    **`risk_class` is a property, not a field.** A dataclass field named
    `risk_class` on this package is refused by
    `tests/architecture/test_relationship_scoring_surface_is_denied.py`, which
    denies the token `risk` anywhere on the relationship surface because a
    stored risk number about a person is the hidden relationship score the
    operating brief forbids. The constant above says why nothing is lost:
    the value is the same for every case, so there was never a per-person
    judgement to store.
    """

    review_case_id: str
    proposal_id: str
    subject_entity_id: str
    principal_id: str
    proposed_kind: MemoryKind
    opened_at: datetime
    proposal_state: ProposalState = ProposalState.NEEDS_REVIEW
    review_version: int = 0
    latest_disposition: Disposition | None = None
    accepted_memory_id: str | None = None
    accepted_memory_version_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.proposal_id, IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
        validate_identifier(self.subject_entity_id, IdKind.ENTITY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not isinstance(self.proposed_kind, MemoryKind):
            raise RelationshipMemoryError("a memory review case names a known kind")
        if not isinstance(self.proposal_state, ProposalState):
            raise RelationshipMemoryError("a memory review case carries a known state")
        ensure_utc(self.opened_at)
        if self.review_version < 0:
            raise RelationshipMemoryError("a review version is not negative")
        if (self.review_version == 0) is not (self.latest_disposition is None):
            raise RelationshipMemoryError("an undecided case has version zero and no disposition")
        accepted = self.proposal_state in (
            ProposalState.ACCEPTED,
            ProposalState.CORRECTED_ACCEPTED,
        )
        if accepted is not (self.accepted_memory_id is not None):
            raise RelationshipMemoryError(
                "a review case names a promoted memory exactly when it was accepted"
            )
        if (self.accepted_memory_id is None) is not (self.accepted_memory_version_id is None):
            raise RelationshipMemoryError("a promoted case names both the memory and the version")
        if self.accepted_memory_id is not None:
            validate_identifier(self.accepted_memory_id, IdKind.RELATIONSHIP_MEMORY)
        if self.accepted_memory_version_id is not None:
            validate_identifier(self.accepted_memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)

    @property
    def risk_class(self) -> RiskClass:
        """The one class every candidate memory is reviewed at. See the constant."""
        return MEMORY_REVIEW_RISK_CLASS


@dataclass(frozen=True, slots=True)
class MemoryReceipt:
    """What a caller is handed after a memory write commits.

    Carries no statement. A receipt is the product's acknowledgement that a
    record is durable, and one that echoed the note back would put the text on a
    second surface for no gain — the caller already has it, and a replayed
    receipt would put someone *else's* earlier text on this one.

    `created` distinguishes a write that happened from a replay that did not, so
    a retrying client can tell the two apart without comparing versions.
    """

    memory_id: str
    memory_version_id: str
    version_number: int
    aggregate_version: int
    lifecycle_state: MemoryLifecycle
    idempotency_key: str
    statement_sha256: str
    issued_at: datetime
    created: bool

    def __post_init__(self) -> None:
        validate_identifier(self.memory_id, IdKind.RELATIONSHIP_MEMORY)
        validate_identifier(self.memory_version_id, IdKind.RELATIONSHIP_MEMORY_VERSION)
        if self.version_number < 1 or self.aggregate_version < 1:
            raise RelationshipMemoryError("a memory receipt names positive versions")
        if not isinstance(self.lifecycle_state, MemoryLifecycle):
            raise RelationshipMemoryError("a memory receipt names a known lifecycle state")
        ensure_utc(self.issued_at)


@dataclass(frozen=True, slots=True)
class MemoryAdmission:
    """The outcome of one memory write: the receipt, and whether it is new."""

    receipt: MemoryReceipt
    created: bool
