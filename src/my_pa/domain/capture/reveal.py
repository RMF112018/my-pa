"""The evidence behind one subject, and the three answers a reveal can be.

`INV-PKL-007` forbids converting unavailable, stale, partial, quarantined, or
unsupported evidence into empty or complete, and `domain.common.coverage` already
says that rule is only enforceable if the states it names exist separately. This
module applies the same reasoning one level down, to a question that has no
coverage counts: **"we looked and there is no evidence" and "we could not look"
are different answers, and an empty list is neither of them.**

Three states, and the constructor refuses most of the combinations that would let
one pass for another:

* `EVIDENCE` — spans were found. A reveal in this state carries at least one.
* `NO_EVIDENCE` — the scope was searched to completion and holds none, and it is
  meant to be a measurement rather than a default. **The constructor does not
  enforce that.** `__post_init__` has no rule tying `NO_EVIDENCE` to completed
  derivation, so this type can be built in that state over a version whose
  derivation has not completed. The guarantee holds one layer out, in
  `infrastructure.persistence.reveal._state_and_gap`, which tests the derivation
  gap before `NO_EVIDENCE` can be returned and which every assembly path in this
  build goes through. A future path that bypassed it would not be caught here,
  and no test covers that gap.
* `UNAVAILABLE` — the scope could not be searched, and `gap` says which of the
  two reasons applies. **This is not an error and not an absence**: the subject
  may well have evidence that this build cannot reach yet, and reporting it as
  an empty result would be the claim `INV-PKL-007` prohibits.

A subject that does not exist, and a subject belonging to another Principal, are
neither of the three: both are refused as *not found* by the caller above, with
the same answer, so a reveal cannot be used to discover that somebody else's
record exists.

**Nothing here carries capture text.** A span is offsets, a basis, a line and
column pair, a role, and the SHA-256 of the slice it covers —
`domain.capture.span` explains why the quote itself is never stored, and the
same argument applies to publishing one: a digest lets a holder of the text
verify the citation, and lets nobody else read it. `QC-AC-041` keeps capture
content out of the answers a caller sees most often, and an explanation of why
an item was surfaced is one of those.

**Proposed and accepted are separate collections, not one collection with a
state column.** A proposal is a model's candidate and an assertion is what a
reviewer promoted; a reader that had to consult a field to tell them apart is a
reader that can fail to. `docs/specs` requires model output to propose and never
to promote, and two containers is the shape of that rule that a renderer cannot
get wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.capture.pipeline import ProcessingState
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import OffsetBasis, SpanRole
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "EvidenceGap",
    "EvidenceState",
    "Reveal",
    "RevealError",
    "RevealSubjectKind",
    "RevealedAssertion",
    "RevealedProposal",
    "RevealedSpan",
    "RevealedVersion",
]


class RevealError(CaptureError):
    """A reveal was assembled in a shape that would misreport what was found."""


class RevealSubjectKind(StrEnum):
    """The subject kinds this build's evidence model can traverse.

    Two, and the set is small because it is honest rather than because it is
    provisional: a capture and an assertion are the only subjects whose evidence
    the stored rows can be walked back from without inventing a link. A subject
    of any other kind is answered `UNAVAILABLE`, which says exactly that.
    """

    CAPTURE = "capture"
    ASSERTION = "assertion"


class EvidenceState(StrEnum):
    """What kind of answer a reveal is. Distinct; none collapses into "empty"."""

    EVIDENCE = "evidence"
    NO_EVIDENCE = "no_evidence"
    UNAVAILABLE = "unavailable"


class EvidenceGap(StrEnum):
    """Why a scope could not be searched. Closed, and each names something actionable."""

    #: The subject identifier names a plane this evidence model does not cover.
    #: A caller can act on it by asking a capability that does cover that plane.
    SUBJECT_KIND_NOT_COVERED = "subject_kind_is_outside_the_evidence_model"
    #: At least one version of the subject has not finished the stage that
    #: persists proposals, so "no evidence" would be a claim about work that has
    #: not happened. A caller can act on it by waiting or by asking again.
    DERIVATION_HAS_NOT_COMPLETED = "derivation_has_not_completed_for_every_version"


@dataclass(frozen=True, slots=True)
class RevealedSpan:
    """One exact citation back into one stored capture version.

    The same seven-part locator `capture_spans` holds, published unchanged: the
    version it is measured against, the code-point range, the basis those
    offsets are counted in, the one-based line and column at each end, the role
    the span plays for whatever cites it, and the digest of the slice. A holder
    of the version's text can re-derive the digest and confirm the citation;
    nobody else can read the slice from any of it.
    """

    span_id: str
    version_id: str
    start_offset: int
    end_offset: int
    offset_basis: OffsetBasis
    line_start: int
    column_start: int
    line_end: int
    column_end: int
    quoted_text_sha256: str
    span_role: SpanRole
    mapping_version: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.span_id, IdKind.SPAN)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.end_offset <= self.start_offset or self.start_offset < 0:
            raise RevealError("a revealed span covers at least one character")

    @property
    def character_count(self) -> int:
        """How many code points the span covers. A count, never the quote."""
        return self.end_offset - self.start_offset


@dataclass(frozen=True, slots=True)
class RevealedVersion:
    """One stored version of the subject's capture, and how far derivation got.

    `derivation_state` is `None` when no stage result exists for the version at
    all, which is a different fact from a stage that ran and failed. Both stop a
    reveal from claiming `NO_EVIDENCE`; only the second can say why it stopped.
    """

    version_id: str
    capture_id: str
    version_number: int
    is_current: bool
    content_sha256: str
    recorded_at: datetime
    derivation_state: ProcessingState | None

    def __post_init__(self) -> None:
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        if self.version_number < 1:
            raise RevealError("version numbers start at one")

    @property
    def derivation_is_complete(self) -> bool:
        """Whether this version's proposals were persisted to completion."""
        return self.derivation_state is ProcessingState.COMPLETE


@dataclass(frozen=True, slots=True)
class RevealedProposal:
    """A candidate. **Not a fact, and structurally incapable of being read as one.**

    Carries the method and both versions of it that produced the candidate, so a
    reader can tell which extractor and which schema is responsible, and the
    review case it was routed to when policy opened one. It carries no
    `normalized_value`: the value a proposal derived is content, and a surface
    that renders a proposed value beside an accepted one is the "model output
    promotes state" failure this whole plane exists to prevent.
    """

    proposal_id: str
    version_id: str
    proposal_type: ProposalType
    state: ProposalState
    risk_class: RiskClass
    method: str
    method_version: str
    schema_version: str
    created_at: datetime
    span_ids: tuple[str, ...]
    review_case_id: str | None = None
    latest_disposition: Disposition | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        for span_id in self.span_ids:
            validate_identifier(span_id, IdKind.SPAN)


@dataclass(frozen=True, slots=True)
class RevealedAssertion:
    """What a reviewer promoted, and the exact act that promoted it.

    Every field after `assertion_type` is the derivation trace `QC-AC-022`
    protects: the proposal it came from, the case it was reviewed in, the
    decision that disposed of it, when that decision was taken, and the receipt
    that recorded the promotion under a named policy version. An assertion with
    no receipt is not a promotion this build can have made, so the absence would
    itself be evidence.
    """

    assertion_id: str
    version_id: str
    proposal_id: str
    decision_id: str
    assertion_type: ProposalType
    state: AssertionState
    accepted_at: datetime
    span_ids: tuple[str, ...]
    review_case_id: str | None = None
    disposition: Disposition | None = None
    decided_at: datetime | None = None
    receipt_id: str | None = None
    policy_version: str | None = None
    revalidation_required_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.assertion_id, IdKind.ASSERTION)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        validate_identifier(self.decision_id, IdKind.REVIEW_DECISION)
        if self.receipt_id is not None:
            validate_identifier(self.receipt_id, IdKind.RECEIPT)
        if self.review_case_id is not None:
            validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        if not self.span_ids:
            raise RevealError("an assertion cites at least one span")
        for span_id in self.span_ids:
            validate_identifier(span_id, IdKind.SPAN)


@dataclass(frozen=True, slots=True)
class Reveal:
    """One answer to "what is the evidence behind this subject?".

    **The constructor carries most of the honesty.** Each rule below removes a
    way of reporting one of the three states while holding the rows of another:

    * `UNAVAILABLE` requires a `gap` and every other state forbids one, so a
      reveal cannot be unavailable for no stated reason and cannot state a
      reason while claiming to have searched.
    * `EVIDENCE` requires at least one span, so the state cannot be claimed over
      nothing.
    * `NO_EVIDENCE` forbids every row, so a reveal holding a proposal cannot say
      it found none.
    * `SUBJECT_KIND_NOT_COVERED` forbids every row, because a subject this build
      cannot traverse is one it read nothing about.
    * `DERIVATION_HAS_NOT_COMPLETED` requires a version whose derivation did not
      complete, so the gap is a measurement of the rows in hand rather than a
      label a caller could attach to a scope that was fully searched.

    **What those rules do not include, stated plainly:** none of them forbids
    `NO_EVIDENCE` over a version whose derivation has not completed, so the
    empty-success shape *is* constructible through this type. It is refused where
    reveals are assembled — `infrastructure.persistence.reveal._state_and_gap`
    checks the derivation gap before it may return `NO_EVIDENCE` — and that
    repository path is the layer the guarantee actually holds at. An assembly
    path that did not go through it would not be caught here, and no test covers
    that gap.
    """

    subject_id: str
    subject_kind: RevealSubjectKind | None
    state: EvidenceState
    gap: EvidenceGap | None = None
    capture_id: str | None = None
    versions: tuple[RevealedVersion, ...] = ()
    spans: tuple[RevealedSpan, ...] = ()
    proposed: tuple[RevealedProposal, ...] = ()
    accepted: tuple[RevealedAssertion, ...] = ()

    def __post_init__(self) -> None:
        if (self.state is EvidenceState.UNAVAILABLE) is not (self.gap is not None):
            raise RevealError("an unavailable reveal states its gap and no other reveal does")
        if self.state is EvidenceState.EVIDENCE and not self.spans:
            raise RevealError("a reveal claiming evidence carries at least one span")
        if self.state is EvidenceState.NO_EVIDENCE and (
            self.spans or self.proposed or self.accepted
        ):
            raise RevealError("a reveal claiming no evidence carries none")
        if self.gap is EvidenceGap.SUBJECT_KIND_NOT_COVERED and (
            self.versions or self.spans or self.proposed or self.accepted or self.capture_id
        ):
            raise RevealError("an uncovered subject kind is read about, not read")
        if self.gap is EvidenceGap.DERIVATION_HAS_NOT_COMPLETED and all(
            version.derivation_is_complete for version in self.versions
        ):
            raise RevealError("an incomplete derivation names the version that is incomplete")
        if self.capture_id is not None:
            validate_identifier(self.capture_id, IdKind.CAPTURE)

    @property
    def versions_with_completed_derivation(self) -> int:
        """How many of `versions` finished the stage that persists proposals."""
        return sum(1 for version in self.versions if version.derivation_is_complete)
