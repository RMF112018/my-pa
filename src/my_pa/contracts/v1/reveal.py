"""The public shape of "why am I seeing this?".

Five models for one answer, and the split between the last three is the contract
rather than a convenience:

* `RevealSpanView` — one exact citation: the version it is measured against, the
  code-point range, the basis, the line and column at each end, the role, and
  the digest of the slice. **No quoted text**, and no field one could go in, on
  the same terms `CaptureListEntry` carries no content: a structural absence
  survives a refactor that a convention does not.
* `RevealVersionView` — one stored version and how far its derivation got, so a
  caller can see *which* version an offset is counted in and whether the scope
  behind it was finished.
* `RevealProposalView` and `RevealAssertionView` — **two models, not one with a
  state field.** A proposal is a candidate a method produced; an assertion is
  what a reviewer promoted. They land in two separate arrays of the answer, so a
  renderer cannot show one where the other belongs by reading a field wrongly,
  and neither model carries the value it derived or asserted — a proposed value
  rendered beside an accepted one is exactly the "model output promotes state"
  failure the review plane exists to prevent.
* `RevealView` — the answer, whose `state` is one of three and never an empty
  list standing in for one of them.

**`state` is the field a caller must read, and `unavailable` is why.** A reveal
that could not search a scope carries no rows, exactly like one that searched and
found none; the two are told apart by `state` and by the mandatory disclosure's
`coverage.state`, never by counting the arrays. `gap` says which of the two
reasons applies, from a closed vocabulary, so the distinction survives being
rendered by something that does not know this module.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.pipeline import ProcessingState
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.capture.reveal import (
    EvidenceGap,
    EvidenceState,
    Reveal,
    RevealSubjectKind,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import OffsetBasis, SpanRole
from my_pa.domain.capture.version import DIGEST_PATTERN
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "RevealAssertionView",
    "RevealProposalView",
    "RevealSpanView",
    "RevealVersionView",
    "RevealView",
]

_DIGEST = Field(
    pattern=DIGEST_PATTERN.pattern.replace(r"\A", "^").replace(r"\Z", "$"),
    min_length=64,
    max_length=64,
)


class RevealSpanView(StrictModel):
    """One exact citation into one stored capture version. Never the quote."""

    span_id: str
    version_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    offset_basis: OffsetBasis
    line_start: int = Field(ge=1)
    column_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    column_end: int = Field(ge=1)
    character_count: int = Field(ge=1)
    quoted_text_sha256: str = _DIGEST
    span_role: SpanRole
    mapping_version: str | None = None

    @model_validator(mode="after")
    def _check(self) -> RevealSpanView:
        validate_identifier(self.span_id, IdKind.SPAN)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.end_offset <= self.start_offset:
            raise ValueError("a span ends after it starts")
        if self.character_count != self.end_offset - self.start_offset:
            raise ValueError("a span's character count is the range it covers")
        return self


class RevealVersionView(StrictModel):
    """One stored version an offset is counted in, and how far derivation got.

    `derivation_state` is `None` when no stage result exists for the version at
    all. That is not the same as a stage that ran and failed, and both are
    reported rather than flattened, because "nothing has run" and "something ran
    and stopped" call for different actions.
    """

    version_id: str
    capture_id: str
    version_number: int = Field(ge=1)
    is_current: bool
    content_sha256: str = _DIGEST
    recorded_at: UtcDatetime
    derivation_state: ProcessingState | None = None
    derivation_is_complete: bool

    @model_validator(mode="after")
    def _check(self) -> RevealVersionView:
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        if self.derivation_is_complete is not (self.derivation_state is ProcessingState.COMPLETE):
            raise ValueError("a derivation is complete exactly when its stage says so")
        return self


class RevealProposalView(StrictModel):
    """A candidate, and what produced it. Not a fact.

    Carries the method and both of its versions, so a caller can say which
    extractor and which schema is answerable for the candidate, and the review
    case policy routed it to when it opened one. It carries no derived value:
    see this module's docstring.
    """

    proposal_id: str
    version_id: str
    proposal_type: ProposalType
    state: ProposalState
    risk_class: RiskClass
    method: str = Field(min_length=1, max_length=128)
    method_version: str = Field(min_length=1, max_length=64)
    schema_version: str = Field(min_length=1, max_length=64)
    created_at: UtcDatetime
    span_ids: tuple[str, ...]
    review_case_id: str | None = None
    latest_disposition: Disposition | None = None

    @model_validator(mode="after")
    def _check(self) -> RevealProposalView:
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        for span_id in self.span_ids:
            validate_identifier(span_id, IdKind.SPAN)
        return self


class RevealAssertionView(StrictModel):
    """What a reviewer promoted, and the exact act that promoted it.

    The whole derivation trace `QC-AC-022` protects, published: the proposal, the
    case, the decision and its disposition, when it was taken, the receipt, and
    the policy version the promotion was admitted under. An assertion missing a
    receipt is reported missing one rather than dropped, because the absence
    would itself be evidence.
    """

    assertion_id: str
    version_id: str
    proposal_id: str
    decision_id: str
    assertion_type: ProposalType
    state: AssertionState
    accepted_at: UtcDatetime
    span_ids: tuple[str, ...] = Field(min_length=1)
    review_case_id: str | None = None
    disposition: Disposition | None = None
    decided_at: UtcDatetime | None = None
    receipt_id: str | None = None
    policy_version: str | None = None
    revalidation_required_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check(self) -> RevealAssertionView:
        validate_identifier(self.assertion_id, IdKind.ASSERTION)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.decision_id, IdKind.REVIEW_DECISION)
        if self.receipt_id is not None:
            validate_identifier(self.receipt_id, IdKind.RECEIPT)
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        for span_id in self.span_ids:
            validate_identifier(span_id, IdKind.SPAN)
        return self


class RevealView(StrictModel):
    """The evidence behind one subject, in one of three distinguishable states.

    The validator restates `domain.capture.reveal.Reveal`'s own rules on the
    wire, and that duplication is deliberate: the domain object refuses to be
    *built* wrongly and this refuses to be *published* wrongly, so a future
    assembly path that skipped the domain type could not reach a client with an
    empty answer labelled `no_evidence` over an unsearched scope.
    """

    subject_id: str
    subject_kind: RevealSubjectKind | None = None
    state: EvidenceState
    gap: EvidenceGap | None = None
    capture_id: str | None = None
    versions: tuple[RevealVersionView, ...] = ()
    spans: tuple[RevealSpanView, ...] = ()
    proposed: tuple[RevealProposalView, ...] = ()
    accepted: tuple[RevealAssertionView, ...] = ()
    versions_with_completed_derivation: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _check(self) -> RevealView:
        validate_identifier(self.subject_id)
        if self.capture_id is not None:
            validate_identifier(self.capture_id, IdKind.CAPTURE)
        if (self.state is EvidenceState.UNAVAILABLE) is not (self.gap is not None):
            raise ValueError("an unavailable reveal states its gap and no other reveal does")
        if self.state is EvidenceState.EVIDENCE and not self.spans:
            raise ValueError("a reveal claiming evidence carries at least one span")
        if self.state is EvidenceState.NO_EVIDENCE and (
            self.spans or self.proposed or self.accepted
        ):
            raise ValueError("a reveal claiming no evidence carries none")
        if self.versions_with_completed_derivation > len(self.versions):
            raise ValueError("more versions cannot be derived than exist")
        return self

    @classmethod
    def of(cls, reveal: Reveal) -> RevealView:
        """The public view of one assembled reveal, field for field."""
        return cls(
            subject_id=reveal.subject_id,
            subject_kind=reveal.subject_kind,
            state=reveal.state,
            gap=reveal.gap,
            capture_id=reveal.capture_id,
            versions=tuple(
                RevealVersionView(
                    version_id=version.version_id,
                    capture_id=version.capture_id,
                    version_number=version.version_number,
                    is_current=version.is_current,
                    content_sha256=version.content_sha256,
                    recorded_at=version.recorded_at,
                    derivation_state=version.derivation_state,
                    derivation_is_complete=version.derivation_is_complete,
                )
                for version in reveal.versions
            ),
            spans=tuple(
                RevealSpanView(
                    span_id=span.span_id,
                    version_id=span.version_id,
                    start_offset=span.start_offset,
                    end_offset=span.end_offset,
                    offset_basis=span.offset_basis,
                    line_start=span.line_start,
                    column_start=span.column_start,
                    line_end=span.line_end,
                    column_end=span.column_end,
                    character_count=span.character_count,
                    quoted_text_sha256=span.quoted_text_sha256,
                    span_role=span.span_role,
                    mapping_version=span.mapping_version,
                )
                for span in reveal.spans
            ),
            proposed=tuple(
                RevealProposalView(
                    proposal_id=proposal.proposal_id,
                    version_id=proposal.version_id,
                    proposal_type=proposal.proposal_type,
                    state=proposal.state,
                    risk_class=proposal.risk_class,
                    method=proposal.method,
                    method_version=proposal.method_version,
                    schema_version=proposal.schema_version,
                    created_at=proposal.created_at,
                    span_ids=proposal.span_ids,
                    review_case_id=proposal.review_case_id,
                    latest_disposition=proposal.latest_disposition,
                )
                for proposal in reveal.proposed
            ),
            accepted=tuple(
                RevealAssertionView(
                    assertion_id=assertion.assertion_id,
                    version_id=assertion.version_id,
                    proposal_id=assertion.proposal_id,
                    decision_id=assertion.decision_id,
                    assertion_type=assertion.assertion_type,
                    state=assertion.state,
                    accepted_at=assertion.accepted_at,
                    span_ids=assertion.span_ids,
                    review_case_id=assertion.review_case_id,
                    disposition=assertion.disposition,
                    decided_at=assertion.decided_at,
                    receipt_id=assertion.receipt_id,
                    policy_version=assertion.policy_version,
                    revalidation_required_at=assertion.revalidation_required_at,
                )
                for assertion in reveal.accepted
            ),
            versions_with_completed_derivation=reveal.versions_with_completed_derivation,
        )
