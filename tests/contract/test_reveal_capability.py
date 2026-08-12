"""`knowledge.reveal` answers three distinguishable things, and discloses which.

The FAST-tier half of WP-09's controls. What it proves is the *application*
layer's arithmetic — which state a set of rows supports, what the envelope says
about each, and what the answer refuses to carry. What it cannot prove is that
the real statements are principal-scoped at the query rather than filtered
afterwards; that is a property of the SQL and is proved against a live server in
`tests/database/test_reveal_isolation.py`. Neither test is sufficient alone.

Every value here is synthetic: one invented sentence, invented opaque
identifiers, and a fake world.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from tests.conftest import Scene, build_service, metadata_for, staged_capture

from my_pa.application.commands import RevealSubject
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.pipeline import ProcessingState
from my_pa.domain.capture.proposal import ProposalState, ProposalType, RiskClass
from my_pa.domain.capture.reveal import (
    RevealedAssertion,
    RevealedProposal,
    RevealedSpan,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import OffsetBasis, SpanRole
from my_pa.domain.capture.version import CaptureVersion
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier

#: The one synthetic sentence, and the range the span below covers in it.
TEXT = "Pour the north slab on Tuesday."
START, END = 0, 22
WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


def _reveal(scene: Scene, subject_id: str) -> ResponseEnvelope:
    return build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.KNOWLEDGE_REVEAL, Purpose.CAPTURE_REVIEW, scene.principal),
        RevealSubject(subject_id=subject_id),
        principal=scene.principal,
    )


def _span(version: CaptureVersion) -> RevealedSpan:
    return RevealedSpan(
        span_id=issue_identifier(IdKind.SPAN),
        version_id=version.version_id,
        start_offset=START,
        end_offset=END,
        offset_basis=OffsetBasis.UNICODE_CODE_POINT_V1,
        line_start=1,
        column_start=1,
        line_end=1,
        column_end=END + 1,
        quoted_text_sha256="a" * 64,
        span_role=SpanRole.DIRECT,
    )


def _stage(scene: Scene, version: CaptureVersion, state: ProcessingState | None) -> None:
    if state is not None:
        scene.world.derivation_states[version.version_id] = state


@pytest.fixture
def derived(
    scene: Scene,
) -> tuple[CaptureVersion, RevealedSpan, RevealedProposal, RevealedAssertion]:
    """One capture with a span, a proposal, and the assertion it was promoted to."""
    version = staged_capture(scene, text=TEXT)
    span = _span(version)
    proposal = RevealedProposal(
        proposal_id=issue_identifier(IdKind.PROPOSAL),
        version_id=version.version_id,
        proposal_type=ProposalType.COMMITMENT,
        state=ProposalState.ACCEPTED,
        risk_class=RiskClass.HIGH,
        method="deterministic_rule",
        method_version="m1",
        schema_version="s1",
        created_at=WHEN,
        span_ids=(span.span_id,),
        review_case_id=issue_identifier(IdKind.REVIEW_CASE),
        latest_disposition=Disposition.ACCEPT,
    )
    assertion = RevealedAssertion(
        assertion_id=issue_identifier(IdKind.ASSERTION),
        version_id=version.version_id,
        proposal_id=proposal.proposal_id,
        decision_id=issue_identifier(IdKind.REVIEW_DECISION),
        assertion_type=ProposalType.COMMITMENT,
        state=AssertionState.ACCEPTED,
        accepted_at=WHEN,
        span_ids=(span.span_id,),
        review_case_id=proposal.review_case_id,
        disposition=Disposition.ACCEPT,
        decided_at=WHEN,
        receipt_id=issue_identifier(IdKind.RECEIPT),
        policy_version="policy-v1",
    )
    scene.world.capture_spans[version.version_id] = (span,)
    scene.world.capture_proposals[version.version_id] = (proposal,)
    scene.world.capture_assertions[version.version_id] = (assertion,)
    _stage(scene, version, ProcessingState.COMPLETE)
    return version, span, proposal, assertion


def test_every_result_identifies_its_authority_version_span_and_coverage(
    scene: Scene,
    derived: tuple[CaptureVersion, RevealedSpan, RevealedProposal, RevealedAssertion],
) -> None:
    """Control 1, in one assertion per word of it.

    A result that cannot identify its provenance must say so rather than render
    bare — so this asserts that every part is *present and named*, not that some
    of them are.
    """
    version, span, proposal, assertion = derived
    answer = _reveal(scene, version.capture_id)

    assert answer.error is None
    result = answer.result
    assert result is not None
    assert result["state"] == "evidence"

    # Version: named, and the offsets say which one they are counted in.
    assert [entry["version_id"] for entry in result["versions"]] == [version.version_id]
    assert result["spans"][0]["version_id"] == version.version_id
    # Source span: the exact locator, with the basis its offsets are counted in.
    assert (result["spans"][0]["start_offset"], result["spans"][0]["end_offset"]) == (START, END)
    assert result["spans"][0]["offset_basis"] == OffsetBasis.UNICODE_CODE_POINT_V1.value
    assert result["spans"][0]["quoted_text_sha256"] == span.quoted_text_sha256
    # Authority: the decision that promoted it and the receipt that recorded it.
    assert result["accepted"][0]["decision_id"] == assertion.decision_id
    assert result["accepted"][0]["receipt_id"] == assertion.receipt_id
    assert result["accepted"][0]["policy_version"] == "policy-v1"
    assert result["accepted"][0]["disposition"] == Disposition.ACCEPT.value
    # Coverage: how much of the scope was actually searched.
    assert result["versions_with_completed_derivation"] == 1
    assert answer.disclosure is not None
    assert answer.disclosure.coverage.state is not CoverageState.UNAVAILABLE

    # Proposed and accepted are two collections, and the proposal is in one only.
    assert [entry["proposal_id"] for entry in result["proposed"]] == [proposal.proposal_id]
    assert "proposal_type" not in result["accepted"][0]


def test_no_capture_text_and_no_derived_value_appears_in_the_answer(
    scene: Scene,
    derived: tuple[CaptureVersion, RevealedSpan, RevealedProposal, RevealedAssertion],
) -> None:
    """The span is a locator. A reveal is not a second read of the content."""
    version, _, _, _ = derived
    rendered = _reveal(scene, version.capture_id).to_canonical_json()
    assert TEXT not in rendered
    assert "north slab" not in rendered
    assert "normalized_value" not in rendered


def test_an_unsearched_scope_is_unavailable_and_a_searched_empty_one_is_not(
    scene: Scene,
) -> None:
    """**Control 3.** Identical empty results; two structurally different answers.

    The assertion that matters is the last one in each half: the disclosure. A
    caller reading only the envelope still cannot mistake the unsearched scope
    for an empty one, because `coverage.state` is `unavailable`, `partial_result`
    is set, and `unavailable_evidence` names the gap.
    """
    searched = staged_capture(scene, text=TEXT)
    _stage(scene, searched, ProcessingState.COMPLETE)
    unsearched = staged_capture(scene, text=TEXT)

    empty = _reveal(scene, searched.capture_id)
    unavailable = _reveal(scene, unsearched.capture_id)

    for answer in (empty, unavailable):
        assert answer.error is None
        assert answer.result is not None
        # The same rows: none.
        assert (answer.result["spans"], answer.result["proposed"], answer.result["accepted"]) == (
            [],
            [],
            [],
        )

    assert empty.result is not None and unavailable.result is not None
    assert empty.result["state"] == "no_evidence"
    assert empty.result["gap"] is None
    assert empty.disclosure is not None
    assert empty.disclosure.coverage.state is not CoverageState.UNAVAILABLE
    assert empty.disclosure.unavailable_evidence == ()
    assert empty.disclosure.partial_result is False

    assert unavailable.result["state"] == "unavailable"
    assert unavailable.result["gap"] == "derivation_has_not_completed_for_every_version"
    assert unavailable.disclosure is not None
    assert unavailable.disclosure.coverage.state is CoverageState.UNAVAILABLE
    assert unavailable.disclosure.partial_result is True
    assert unavailable.disclosure.unavailable_evidence == (
        "derivation_has_not_completed_for_every_version",
    )
    assert "evidence_scope_was_not_searched" in unavailable.disclosure.limitations


def test_a_subject_kind_this_build_cannot_traverse_is_unavailable_not_not_found(
    scene: Scene,
) -> None:
    """A `kn_…` is a coverage answer, and a coverage answer is not an error."""
    answer = _reveal(scene, issue_identifier(IdKind.KNOWLEDGE))

    assert answer.error is None
    assert answer.result is not None
    assert answer.result["state"] == "unavailable"
    assert answer.result["gap"] == "subject_kind_is_outside_the_evidence_model"
    assert answer.result["subject_kind"] is None
    assert answer.disclosure is not None
    assert answer.disclosure.coverage.state is CoverageState.UNAVAILABLE


def test_a_subject_that_does_not_exist_is_not_found_and_says_nothing_else(
    scene: Scene,
) -> None:
    """`not_found`, with the field named and the value never echoed."""
    subject = issue_identifier(IdKind.CAPTURE)
    answer = _reveal(scene, subject)

    assert answer.result is None
    assert answer.error is not None
    assert answer.error.code is ErrorCode.NOT_FOUND
    assert answer.error.safe_details == ("subject",)
    assert subject not in answer.to_canonical_json()


def test_a_malformed_subject_is_a_request_error_and_not_a_coverage_answer(
    scene: Scene,
) -> None:
    """Shape is validation; coverage is an answer. The two must not be confused.

    `scene` is a parameter because the distinction is only meaningful beside the
    coverage answer above: a build that refused every uncovered prefix here would
    pass this test and make `SUBJECT_KIND_NOT_COVERED` unreachable.
    """
    assert scene is not None
    with pytest.raises(InvalidRequestError) as raised:
        RevealSubject(subject_id="../../etc/passwd")
    assert raised.value.safe_details == (SafeDetail.SUBJECT,)
