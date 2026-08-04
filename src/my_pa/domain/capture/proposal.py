"""Typed, non-canonical candidates derived from a capture version.

A proposal is a claim the product makes *about* what the user wrote. It is never
authoritative, never acted on, and never presented as an accepted record —
`docs/specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:185` (`P-15`)
requires that anything failing validation be rejected or quarantined rather than
"stored as an accepted-looking record", and that is what the states below make
representable.

**Nine states, from the canonical set** (`docs/specs/canonical-product-definition/
09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:94`), not the seven at
`09_LOGICAL_DATA_MODEL.md:154`. The canonical set is the superset — it adds
`needs_review` and `unresolved` — so taking it loses nothing, and
`docs/plans/mcv-completion-plan.md:920` already rules canonical over
quick-capture for state vocabularies. **This build can reach two of the nine**:
`proposed`, and `invalidated` when a cited span no longer re-derives. The other
seven need acceptance, review routing, or identity resolution, none of which
exists here. They are declared rather than omitted because the set is the
canonical vocabulary of one object, not a list of what this package happens to
write, and a later package that reaches one of them must not have to widen a
frozen constraint to say so.

**One method, and the reason is `D-78`'s.** `09_LOGICAL_DATA_MODEL.md:157` names
five (deterministic rule, resolver, local model, cloud model, hybrid). Four of
them require a resolver or a model, and `P00-OD-006` is open, so a proposal
filed under any of them could not have been produced by this build. One member
means no writer, hand-run statement, or later revision can file a model output
as a deterministic match without changing this enum and the frozen literal in
the migration that mirrors it — a visible change rather than a silent one. That
is the same argument `ProcessingPolicy` and `extractions.trust_level` make.

**Missing required fields are recorded, not filled in.** `11_…:131` requires each
work-object proposal to carry "missing required fields", and a deterministic cue
extractor misses most of them: a note saying "send the RFI response by Friday"
names an action and a due condition and no counterparty at all. Recording which
fields are absent is the difference between an honest partial proposal and an
invented complete one, and it is `AGENTS.md` section 5's never-launder rule
applied to a record rather than to a row.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "MAX_NORMALIZED_VALUE_CHARACTERS",
    "MAX_PROPOSAL_VERSION_CHARACTERS",
    "Proposal",
    "ProposalError",
    "ProposalField",
    "ProposalMethod",
    "ProposalQuarantineReason",
    "ProposalState",
    "ProposalType",
    "RiskClass",
    "missing_required_fields",
    "required_fields_for",
]

#: A normalized value is what a deterministic match resolved to — an ISO date, a
#: decimal amount, a document identifier. Bounded because it is derived from
#: capture text and an unbounded derived column would carry as much of the text
#: as a match happened to cover.
MAX_NORMALIZED_VALUE_CHARACTERS: Final = 256

#: Method and schema versions are bounded lowercase tokens, the same shape
#: `domain.capture.pipeline` uses for its own.
MAX_PROPOSAL_VERSION_CHARACTERS: Final = 32

_VERSION_PATTERN: Final = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,31}\Z")


class ProposalError(CaptureError):
    """A proposal value refused to exist. Names the rule, never the value."""


class ProposalType(StrEnum):
    """The seven work objects `P-09` proposes (`11_…:119-129`)."""

    TASK = "task"
    COMMITMENT = "commitment"
    DECISION = "decision"
    FOLLOW_UP = "follow_up"
    OPEN_QUESTION = "open_question"
    RISK = "risk"
    ISSUE = "issue"


class ProposalState(StrEnum):
    """The canonical nine (`09_CANONICAL_…:94`). Two are reachable here."""

    PROPOSED = "proposed"
    NEEDS_REVIEW = "needs_review"
    ACCEPTED = "accepted"
    CORRECTED_ACCEPTED = "corrected_accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    UNRESOLVED = "unresolved"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class RiskClass(StrEnum):
    """How much a wrong proposal would cost (`09_LOGICAL_DATA_MODEL.md:155`).

    Recorded on the proposal rather than computed at review time, because the
    class is a property of what was proposed and review is a later package's.
    """

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ProposalMethod(StrEnum):
    """What produced the proposal. One member; see the module docstring."""

    DETERMINISTIC_RULE = "deterministic_rule"


class ProposalField(StrEnum):
    """The fields `11_…:131` requires a work-object proposal to carry.

    `direct spans` is in that sentence too and is not a member here: a span is a
    row in `capture_proposal_spans` and its absence is refused by a deferred
    constraint trigger rather than recorded as a missing field (`D-98`). A
    proposal with no span does not exist; a proposal with no counterparty does.
    """

    ACTOR = "actor"
    COUNTERPARTY = "counterparty"
    ACTION = "action"
    DUE_CONDITION = "due_condition"
    STATUS = "status"


class ProposalQuarantineReason(StrEnum):
    """Why a proposal is `invalidated` rather than presented.

    Its own vocabulary rather than `domain.extraction.quarantine.QuarantineReason`,
    and the reason is subject rather than convenience: that enum is about *source
    objects*, keyed by `(enrollment_id, source_object_id)`, and every one of its
    eight members describes a parser or a containment failure over bytes nobody
    authored. A proposal is quarantined because the evidence it cites no longer
    holds, which none of the eight can say. Reusing it would also move a
    still-derived constraint in an already-merged revision (`D-91`).

    Three members, and all three are reachable by this build's validation:
    `capture_versions` is append-only, so the mismatch cannot come from the text
    changing, and these are the three ways a span can fail to hold against it.
    """

    #: The stored digest is not what the version's content produces at the
    #: span's offsets.
    SPAN_TEXT_DOES_NOT_RE_DERIVE = "span_text_does_not_re_derive"
    #: The span's offsets fall outside the version's code-point length.
    SPAN_OUTSIDE_VERSION_TEXT = "span_outside_version_text"
    #: The span belongs to a different version than the proposal citing it —
    #: the supersession case at
    #: `docs/specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:107`.
    SPAN_CITES_ANOTHER_VERSION = "span_cites_another_version"


#: Which fields each proposal type requires. Derived from `11_…:131`, which
#: states one list for every work object; the difference between the types is
#: which of them a deterministic cue can fill, not which are required.
_REQUIRED_FIELDS: Mapping[ProposalType, frozenset[ProposalField]] = MappingProxyType(
    dict.fromkeys(
        ProposalType,
        frozenset(
            {
                ProposalField.ACTOR,
                ProposalField.COUNTERPARTY,
                ProposalField.ACTION,
                ProposalField.DUE_CONDITION,
                ProposalField.STATUS,
            }
        ),
    )
)


def required_fields_for(proposal_type: ProposalType) -> frozenset[ProposalField]:
    """The fields `proposal_type` requires.

    An unmapped type would yield the empty set, which would report every
    proposal of it as complete — the silent shape this repository's policy maps
    also have — so the mapping is built from the enum itself and cannot miss a
    member.
    """
    return _REQUIRED_FIELDS[proposal_type]


def missing_required_fields(
    proposal_type: ProposalType, present: frozenset[ProposalField]
) -> tuple[ProposalField, ...]:
    """Which required fields `present` does not fill, sorted by value.

    Sorted so that two runs over the same capture record the same array and a
    replay comparison is about content rather than about iteration order.
    """
    if not isinstance(proposal_type, ProposalType):
        raise ProposalError("a proposal names one work-object type")
    for value in present:
        if not isinstance(value, ProposalField):
            raise ProposalError("a present field is one of the required field names")
    return tuple(sorted(required_fields_for(proposal_type) - present, key=lambda item: item.value))


def _validated_token(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ProposalError(f"{field_name} must be a bounded lowercase token")
    if not _VERSION_PATTERN.fullmatch(value):
        raise ProposalError(f"{field_name} must be a bounded lowercase token")
    return value


@dataclass(frozen=True, slots=True)
class Proposal:
    """One candidate derived from one capture version.

    `accepted_record_type` and `accepted_record_id` are nullable and are never
    written here. They are the forward reference `09_LOGICAL_DATA_MODEL.md:162`
    names, and they are declared rather than left to WP-8 for one reason that
    distinguishes them from `capture_submissions.registered_client_id`, which
    `D-74` refused outright: the package that writes them is the next one and
    the table they will point at is already scoped, whereas no package and no
    mechanism existed for a registered client. They carry no foreign key,
    because the target table does not exist yet and a constraint naming it could
    not be created.

    `normalized_value` is `repr=False` for the reason `CaptureContent.text` is:
    it is derived from what the user wrote, and a dataclass `repr` reaches a
    traceback and a log record without anyone deciding it should.
    """

    proposal_id: str
    version_id: str
    proposal_type: ProposalType
    state: ProposalState
    risk_class: RiskClass
    method: ProposalMethod
    method_version: str
    schema_version: str
    missing_fields: tuple[ProposalField, ...] = ()
    normalized_value: str | None = field(default=None, repr=False)
    quarantine_reason: ProposalQuarantineReason | None = None
    accepted_record_type: str | None = None
    accepted_record_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        for name, value in (
            ("proposal type", self.proposal_type),
            ("state", self.state),
            ("risk class", self.risk_class),
            ("method", self.method),
        ):
            if value is None:
                raise ProposalError(f"a proposal names one {name}")
        _validated_token(self.method_version, field_name="method version")
        _validated_token(self.schema_version, field_name="schema version")
        if self.normalized_value is not None and (
            not self.normalized_value
            or len(self.normalized_value) > MAX_NORMALIZED_VALUE_CHARACTERS
        ):
            raise ProposalError("a normalized value is bounded and not empty")
        if len(set(self.missing_fields)) != len(self.missing_fields):
            raise ProposalError("a missing required field is recorded once")
        if not set(self.missing_fields) <= required_fields_for(self.proposal_type):
            raise ProposalError("a missing required field is one this proposal type requires")
        # The rule the table also states. An `invalidated` proposal with no
        # reason records that evidence failed without recording how, and any
        # other state with one attributes a refusal to a proposal that was not
        # refused.
        if (self.state is ProposalState.INVALIDATED) is not (self.quarantine_reason is not None):
            raise ProposalError(
                "an invalidated proposal records its quarantine reason and no other state does"
            )
        if (self.accepted_record_type is None) is not (self.accepted_record_id is None):
            raise ProposalError("an accepted record is named by both its type and its identifier")
