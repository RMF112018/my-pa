"""What a reviewer may decide about a proposal, and nothing else.

A review case is opened for a proposal whose risk class requires one, and every
decision taken on it is appended rather than written over the last. The case
carries no risk class of its own: `capture_review_cases.proposal_id` is `UNIQUE`
and `NOT NULL`, so the proposal's own `risk_class` is one join away and a second
copy would be two writers for one fact — the rule `capture_processing_text`
states for `transformations` and `capture_submissions` for `registered_client_id`.

**Eight dispositions, and which of them a case can reach is now a property of
its subject rather than of the build.** Seven come from
`docs/specs/quick-capture/12_REVIEW_AND_PROMOTION_POLICY.md:129-135`;
`invalidate` is `WP-RI-B-05`'s, and it is what a case gets when the ground it
stood on went away rather than when a reviewer disagreed with it. `accept`,
`correct_and_accept`, `reject`, `defer` and `mark_unresolved` are reachable for
every subject kind on this surface.

**`reprocess` and `escalate` were declared-and-unreachable for measured reasons,
and this states the new division rather than deleting them.** Half of each old
reason is still exactly true, so it is quoted rather than replaced:

- `reprocess` — "under an eligible route", and for a *capture* proposal there is
  still exactly one route. No model route exists while `P00-OD-006` is open, the
  deterministic pipeline is a function of the immutable version and the pipeline
  version, and `QC-AC-035` requires a replayed stage to return the prior output.
  A capture reprocess is still provably a no-op and is still refused here.
  What changed is that an Entity proposal is *not* a function of an immutable
  version: it carries `method`, `method_version` and, for a local model,
  `model_id`/`model_version`, and it rests on evidence links that can grow after
  it was filed. Reprocessing one against current evidence and the current method
  can genuinely produce a different request, so a successor proposal is minted
  and the predecessor becomes `superseded` and points at it. The eligible route
  the capture plane lacks is one the Entity plane has.
- `escalate` — "to operator-only decision", and the old reason was that
  `domain.identity.operation` restricted exactly one capability to an operator
  and `P00-OD-010` leaves a single local principal (`D-72`), so there was no
  non-operator to escalate *from*. The principal count has not changed and is
  not what made this reachable. What made it reachable is that WP-RI-B-05 and
  WP-RI-B-06 introduce the first real producer/reviewer/operator separation on
  this plane: a source, rule or local-model **producer** may raise a proposal and
  may never decide one; a **reviewer** may decide an ordinary proposal and may
  never perform identity correction; and the kinds
  `ReviewRequirement.REQUIRES_OPERATOR` names require an **operator**
  specifically. Escalating therefore has a ceiling to raise a case *to* — a
  decision the holder of `review.decide` cannot take — which is what was
  missing. It is a fact about authority, not about how many people hold accounts.

`invalidate` needs no such argument. It exists because a governed merge, or any
later act that removes what a proposal rested on, has to be able to close a case
without asserting that a reviewer refused it. It creates no canonical record, it
requires a reason, and it keeps the case and its lineage.

**Declaring a disposition rather than omitting it is safe here, and it is not
safe everywhere.** `ProposalState` is treated the same way and `ProposalMethod`
deliberately is not: an unwritable `cloud_model` method would let a model output
be filed as deterministic, which is a laundering path, whereas a disposition no
plane routes cannot launder anything — it is a decision nobody can record, not a
provenance nobody can check. The set is the instrument's own vocabulary of one
act, and a plane that reaches one of them must not have to widen a frozen
constraint to say so.

**One surface, four subject kinds.** `ReviewRepository.cases` returns a union of
`ReviewCase`, `GoodNotesReviewCase`, `RelationshipMemoryReviewCase` and
`EntityProposalReviewCase`; each variant carries only the subject facts its own
decision needs, and the union is what keeps one reviewer surface from becoming
four.

`O-16` and `RI-OD-012` are resolved by WP-8: every consequential class below
requires review regardless of confidence. `O-17` is also resolved: a disposition
creates only canonical product-owned records and receipts, never an external
action. The port and architecture test make that absence structural.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.governance import (
    EntityProposalKind,
    EntityProposalMethod,
    ReviewRequirement,
    requirement_for,
)

__all__ = [
    "CORRECTION_PATCH_FIELD_LIMIT",
    "CORRECTION_PATCH_VALUE_LIMIT",
    "REVIEW_REASON_LIMIT",
    "ConsequentialClass",
    "CorrectionPatch",
    "Disposition",
    "EntityProposalReviewCase",
    "EntityProposalReviewDecision",
    "ReviewCase",
    "ReviewConflictError",
    "ReviewCorrectionError",
    "ReviewDecision",
    "ReviewError",
    "ReviewNotFoundError",
    "ReviewRequiredError",
    "ReviewSubjectKind",
    "ReviewUnsupportedError",
    "requires_review",
]


class Disposition(StrEnum):
    """The eight a reviewer may take. See the module docstring for which reach where."""

    ACCEPT = "accept"
    CORRECT_AND_ACCEPT = "correct_and_accept"
    REJECT = "reject"
    DEFER = "defer"
    MARK_UNRESOLVED = "mark_unresolved"
    REPROCESS = "reprocess"
    ESCALATE = "escalate"
    INVALIDATE = "invalidate"


class ReviewSubjectKind(StrEnum):
    """What a case on the one Review surface is about.

    Declared rather than left as the four string literals the payload formatter
    used to spell, because `review.list` now takes a subject filter and a filter
    over an open vocabulary is a filter that silently matches nothing when a
    caller misspells it. The values are exactly the `subject_kind` strings the
    contract already published, so nothing a caller reads changes.
    """

    CAPTURE_PROPOSAL = "capture_proposal"
    GOODNOTES_REGION = "goodnotes_region"
    RELATIONSHIP_MEMORY = "relationship_memory"
    ENTITY_PROPOSAL = "entity_proposal"


class ConsequentialClass(StrEnum):
    """The seven classes QC-AC-020 makes review-gated."""

    COMMITMENT = "commitment"
    DECISION = "decision"
    CRITICAL_DATE = "critical_date"
    FINANCIAL_FACT = "financial_fact"
    IDENTITY_MERGE = "identity_merge"
    CONTRADICTION = "contradiction"
    SENSITIVE_RELATIONSHIP_CONCLUSION = "sensitive_relationship_conclusion"


def requires_review(subject: ConsequentialClass) -> bool:
    """Return the closed policy answer for a consequential class.

    Deliberately total and deliberately always true. Confidence and a low
    extractor risk label cannot weaken consequence.
    """
    if not isinstance(subject, ConsequentialClass):
        raise TypeError("review policy accepts one consequential class")
    return True


#: How long one field of a correction patch may be.
#:
#: Restated rather than imported from `PROPOSAL_PAYLOAD_VALUE_LIMIT`, which it
#: equals today, for the reason that constant states about its own siblings:
#: these are two ceilings on two things — what a *producer* may put in a stored
#: JSONB column, and what a *reviewer* may hand a decision — and sharing the
#: constant would make widening one silently widen the other.
#:
#: This is not a second validation of any field. A patch's real rule is the
#: target command's schema, which the plane that owns the subject checks before
#: it commits anything. What this bounds is the failure an unbounded structural
#: record always has: a caller putting the document it could not fit anywhere
#: else into the one shape with no schema attached to it yet.
CORRECTION_PATCH_VALUE_LIMIT: Final = 500

#: How many fields one correction patch may name. Larger than any target
#: command's field count, deliberately: this is not the schema's job, it is the
#: bound that keeps a patch small enough to be worth handing to the schema.
CORRECTION_PATCH_FIELD_LIMIT: Final = 16

#: How long the reason a disposition states may be.
#:
#: A decision's reason is prose a person wrote about why they refused, deferred
#: or escalated. Bounded here because every prose column on this surface is
#: bounded, and at the same ceiling `entity_proposals.decision_reason` already
#: carries, so a reason that reaches the Entity plane's decision ledger cannot
#: be refused by the column after the request accepted it.
REVIEW_REASON_LIMIT: Final = 500


class ReviewError(Exception):
    """A review transition was refused without carrying capture content."""


class ReviewConflictError(ReviewError):
    """The expected review sequence or current proposal state is stale."""


class ReviewRequiredError(ReviewError):
    """Canonical promotion was attempted without an applicable disposition."""


class ReviewNotFoundError(ReviewError):
    """A request named no stored review case."""


class ReviewUnsupportedError(ReviewError):
    """A declared disposition has no eligible route in this build."""


class ReviewCorrectionError(ReviewError):
    """A correction was refused by the schema of the command it corrects.

    Separate from `ReviewConflictError` because only one of the two is fixed by
    looking again: a stale version means the world moved, and this means the
    patch named a field the target command does not take. It carries the rule
    and never the value, like every error on this surface.
    """


@dataclass(frozen=True, slots=True)
class ReviewCase:
    """One consequential proposal awaiting or retaining a disposition."""

    review_case_id: str
    proposal_id: str
    capture_id: str
    version_id: str
    principal_id: str
    proposal_type: ProposalType
    proposal_state: ProposalState
    risk_class: RiskClass
    opened_at: datetime
    review_version: int = 0
    latest_disposition: Disposition | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        ensure_utc(self.opened_at)
        if self.review_version < 0:
            raise ReviewError("a review version is not negative")
        if (self.review_version == 0) is not (self.latest_disposition is None):
            raise ReviewError("an undecided case has version zero and no disposition")


@dataclass(frozen=True, slots=True)
class CorrectionPatch:
    """A reviewer's correction, named field by field rather than as one string.

    **What this is and, more importantly, what it is not.** It is the *shape* a
    typed correction takes on the way to a decision: named fields, each holding
    a string or a flag, bounded and in name order. It is emphatically not a
    second schema. Whether `display_name` is a field the target command takes,
    and whether the value is a name that command would accept, is the target
    command schema's answer and is checked by the plane that owns the subject —
    for an Entity proposal, by constructing `EntityProposalPayload` against
    `schema_for(kind)`, which is the same validator the producer's payload went
    through. A second, weaker copy of that rule here is exactly the failure the
    proposal payload module argues against.

    **Why `corrected_value` could not simply be widened.** A capture assertion
    has one normalized value, so a correction to it is one string and
    `ReviewDecisionRequest.corrected_value` is the right shape for it; a memory
    candidate has one statement, and the same holds. An Entity proposal asks for
    a *mutation with named arguments* — `entity_id`, `display_name`, `reason` —
    and a single string cannot say which of them the reviewer changed. Repurposing
    `corrected_value` to carry an encoded mapping would have made one column mean
    two things and would have left the capture plane's bound guarding a document.
    So this is added beside it and the two never travel together.

    `values` is a sorted tuple rather than a mapping for the reason
    `EntityProposalPayload.values` is: it makes the record hashable and
    comparable, and it makes any digest over it depend on content rather than on
    the iteration order of whatever mapping a caller happened to build.
    """

    values: tuple[tuple[str, str | bool], ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ReviewError("a correction patch names at least one field")
        if len(self.values) > CORRECTION_PATCH_FIELD_LIMIT:
            raise ReviewError("a correction patch names a bounded number of fields")
        names = [name for name, _ in self.values]
        if len(set(names)) != len(names):
            raise ReviewError("a correction patch names each field once")
        if names != sorted(names):
            raise ReviewError("a correction patch's fields are in name order")
        for name, value in self.values:
            if not name.strip():
                raise ReviewError("a correction patch names each field")
            if isinstance(value, bool):
                continue
            if not isinstance(value, str):
                raise ReviewError("a correction patch value is a string or a flag")
            if not value.strip():
                raise ReviewError("a correction patch names no blank value")
            if len(value) > CORRECTION_PATCH_VALUE_LIMIT:
                raise ReviewError("a correction patch value is bounded")

    @classmethod
    def of(cls, values: Mapping[str, str | bool]) -> CorrectionPatch:
        """`values` as a patch, in the name order the record requires."""
        return cls(values=tuple(sorted(values.items())))

    def as_mapping(self) -> dict[str, str | bool]:
        """The correction as the keyword arguments its target command takes."""
        return dict(self.values)


@dataclass(frozen=True, slots=True)
class EntityProposalReviewCase:
    """One Entity proposal exposed through the ordinary canonical Review surface.

    The **fourth** subject kind on one surface, after capture proposals,
    GoodNotes regions and Relationship Memory candidates, and it mirrors
    `RelationshipMemoryReviewCase` deliberately rather than inventing a fourth
    review vocabulary. `ProposalState` and `Disposition` are the shared
    capture-plane ones, reused as *values* and not as tables: nothing here
    writes a capture row, so no frozen capture-plane CHECK has to widen to admit
    an Entity proposal.

    **It carries no payload values, and that absence is the disclosure
    control.** A capture case names its capture and version; a GoodNotes case
    names its region and page version; a memory case names its subject and the
    kind it would become. None of them hands the reviewer the words. An Entity
    proposal's payload is a producer's assertion about a person — the display
    name a rule inferred, the external address a source claimed — and a listing
    that printed it would put a source-derived claim about somebody in front of
    every caller of `review.list`, on a read that carries no eligibility
    decision to make it with. A reviewer who needs the requested values reads
    the proposal through the proposal plane, where the authorization for that
    read is checked.

    **What it does disclose is what a decision needs**: which mutation is
    proposed (`proposed_kind`), what produced it (`method`), which entity it
    would change where the kind names one, and — once accepted — the record it
    produced. `method` is disclosed for the same reason
    `RelationshipMemoryReviewCase` discloses `proposed_kind`: a reviewer being
    asked to accept a local model's conclusion has to know that is what they are
    accepting, and section 21.4's whole anti-laundering argument is that a
    model's output must not be indistinguishable from a deterministic match.

    **`risk_class` is a property, not a field**, and derived from the kind's
    review requirement rather than stored. Two reasons, both measured. A stored
    copy would be a second writer for a fact `requirement_for` already owns —
    the rule this module's own docstring states about `capture_review_cases`.
    And a dataclass *field* named `risk_class` on a record about an entity is
    the shape `tests/architecture/test_relationship_scoring_surface_is_denied.py`
    exists to refuse; deriving it keeps the value available to the one formatter
    that publishes it without storing a number about a person anywhere.
    """

    review_case_id: str
    proposal_id: str
    principal_id: str
    proposed_kind: EntityProposalKind
    method: EntityProposalMethod
    opened_at: datetime
    target_entity_id: str | None = None
    proposal_state: ProposalState = ProposalState.NEEDS_REVIEW
    review_version: int = 0
    latest_disposition: Disposition | None = None
    #: Whether a reviewer has raised this case to the operator ceiling. Derived
    #: from the decision ledger rather than stored on the proposal: escalation is
    #: something a *decision* did, and a column on the proposal would be a second
    #: place the same fact could be written and then disagree with the ledger.
    escalated: bool = False
    accepted_record_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.proposal_id, IdKind.ENTITY_PROPOSAL)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.target_entity_id is not None:
            validate_identifier(self.target_entity_id, IdKind.ENTITY)
        if not isinstance(self.proposed_kind, EntityProposalKind):
            raise ReviewError("an entity proposal case names a known kind")
        if not isinstance(self.method, EntityProposalMethod):
            raise ReviewError("an entity proposal case names a known method")
        if not isinstance(self.proposal_state, ProposalState):
            raise ReviewError("an entity proposal case carries a known state")
        ensure_utc(self.opened_at)
        if self.review_version < 0:
            raise ReviewError("a review version is not negative")
        if (self.review_version == 0) is not (self.latest_disposition is None):
            raise ReviewError("an undecided case has version zero and no disposition")
        accepted = self.proposal_state in (
            ProposalState.ACCEPTED,
            ProposalState.CORRECTED_ACCEPTED,
        )
        if self.accepted_record_id is not None and not accepted:
            raise ReviewError("a case names the record it produced only when it was accepted")

    @property
    def risk_class(self) -> RiskClass:
        """What a wrong acceptance of this kind would cost. See the class docstring."""
        requirement = requirement_for(self.proposed_kind)
        if requirement is ReviewRequirement.REQUIRES_OPERATOR:
            return RiskClass.CRITICAL
        if requirement is ReviewRequirement.REQUIRES_REVIEW:
            return RiskClass.HIGH
        return RiskClass.MODERATE


@dataclass(frozen=True, slots=True)
class EntityProposalReviewDecision:
    """One appended decision on an Entity proposal's review case.

    The Entity plane's row in its own decision ledger, mirroring what
    `capture_review_decisions`, `goodnotes_review_decisions` and
    `relationship_memory_review_decisions` already are for the other three
    subject kinds. It is a separate record from `ReviewDecision` because that one
    is what the *capability* returns — an assertion identifier, a receipt
    identifier and a proposal state — and this one is what the ledger *stores*,
    which includes the reason and the correction and excludes anything about a
    capture assertion.

    `sequence` numbers from one and is what `expected_review_version` is checked
    against: the version is the count of these, so a stale request names a count
    the ledger has already passed and writes nothing.
    """

    decision_id: str
    proposal_id: str
    review_case_id: str
    principal_id: str
    sequence: int
    disposition: Disposition
    correlation_id: str
    audit_id: str
    decided_at: datetime
    reason: str | None = None
    corrected_payload: CorrectionPatch | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value, kind in (
            (self.decision_id, IdKind.REVIEW_DECISION),
            (self.proposal_id, IdKind.ENTITY_PROPOSAL),
            (self.review_case_id, IdKind.REVIEW_CASE),
            (self.principal_id, IdKind.PRINCIPAL),
            (self.correlation_id, IdKind.CORRELATION),
            (self.audit_id, IdKind.AUDIT),
        ):
            validate_identifier(value, kind)
        if not isinstance(self.disposition, Disposition):
            raise ReviewError("a decision names one disposition")
        if self.sequence < 1:
            raise ReviewError("review decisions are numbered from one")
        ensure_utc(self.decided_at)
        corrected = self.disposition is Disposition.CORRECT_AND_ACCEPT
        if corrected is not (self.corrected_payload is not None):
            raise ReviewError("a corrected payload belongs only to correct-and-accept")
        if self.reason is not None and (
            not self.reason.strip() or len(self.reason) > REVIEW_REASON_LIMIT
        ):
            raise ReviewError("a reason is bounded and not blank")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """An appended review decision and any canonical result it produced."""

    decision_id: str
    review_case_id: str
    sequence: int
    disposition: Disposition
    principal_id: str
    correlation_id: str
    audit_id: str
    decided_at: datetime
    proposal_state: ProposalState
    assertion_id: str | None = None
    receipt_id: str | None = None
    normalized_value: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value, kind in (
            (self.decision_id, IdKind.REVIEW_DECISION),
            (self.review_case_id, IdKind.REVIEW_CASE),
            (self.principal_id, IdKind.PRINCIPAL),
            (self.correlation_id, IdKind.CORRELATION),
            (self.audit_id, IdKind.AUDIT),
        ):
            validate_identifier(value, kind)
        if self.assertion_id is not None:
            validate_identifier(self.assertion_id, IdKind.ASSERTION)
        if self.receipt_id is not None:
            validate_identifier(self.receipt_id, IdKind.RECEIPT)
        if self.sequence < 1:
            raise ReviewError("review decisions are numbered from one")
        ensure_utc(self.decided_at)
