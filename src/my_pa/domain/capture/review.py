"""What a reviewer may decide about a proposal, and nothing else.

A review case is opened for a proposal whose risk class requires one, and every
decision taken on it is appended rather than written over the last. The case
carries no risk class of its own: `capture_review_cases.proposal_id` is `UNIQUE`
and `NOT NULL`, so the proposal's own `risk_class` is one join away and a second
copy would be two writers for one fact — the rule `capture_processing_text`
states for `transformations` and `capture_submissions` for `registered_client_id`.

**Seven dispositions, from
`docs/specs/quick-capture/12_REVIEW_AND_PROMOTION_POLICY.md:129-135`, and this
build reaches five.** `accept`, `correct_and_accept`, `reject`, `defer` and
`mark_unresolved` each move the proposal to the state of the same name. The other
two cannot be written here, for measured reasons rather than for want of wiring:

- `reprocess` — "under an eligible route", and there is exactly one route. No
  model route exists while `P00-OD-006` is open, the deterministic pipeline is a
  function of the immutable version and the pipeline version, and `QC-AC-035`
  requires a replayed stage to return the prior output. A reprocess under this
  build is provably a no-op, so a disposition that claimed one would record a
  decision that changed nothing.
- `escalate` — "to operator-only decision", and `domain.identity.operation`
  restricts exactly one capability to an operator. Under `P00-OD-010` there is a
  single local principal (`D-72`), so there is no non-operator to escalate *from*.

**Declaring the two rather than omitting them is safe here, and it is not safe
everywhere.** `ProposalState` is treated the same way and `ProposalMethod`
deliberately is not: an unwritable `cloud_model` method would let a model output
be filed as deterministic, which is a laundering path, whereas an unwritable
`escalate` cannot launder anything — it is a decision nobody can record, not a
provenance nobody can check. The set is the instrument's own vocabulary of one
act, and a later package that reaches one of them must not have to widen a
frozen constraint to say so.

`O-16` and `RI-OD-012` are resolved by WP-8: every consequential class below
requires review regardless of confidence. `O-17` is also resolved: a disposition
creates only canonical product-owned records and receipts, never an external
action. The port and architecture test make that absence structural.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "ConsequentialClass",
    "Disposition",
    "ReviewCase",
    "ReviewConflictError",
    "ReviewDecision",
    "ReviewError",
    "ReviewNotFoundError",
    "ReviewRequiredError",
    "ReviewUnsupportedError",
    "requires_review",
]


class Disposition(StrEnum):
    """The seven a reviewer may take. Five are reachable; see the module docstring."""

    ACCEPT = "accept"
    CORRECT_AND_ACCEPT = "correct_and_accept"
    REJECT = "reject"
    DEFER = "defer"
    MARK_UNRESOLVED = "mark_unresolved"
    REPROCESS = "reprocess"
    ESCALATE = "escalate"


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
