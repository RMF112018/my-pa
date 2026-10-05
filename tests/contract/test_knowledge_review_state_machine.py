"""The Knowledge Review state machine and correction contract (KLP-WP-04 slice C).

FAST. KLP-AC-096 and KLP-AC-037 (Python half; the workbench half is slice D's
`web/src/components/review/review.test.tsx`).

* **KLP-AC-096** -- the Knowledge proposal vocabulary contains `unresolved`; the
  open states (`needs_review`, `deferred`, `unresolved`) and the terminal ones
  (`accepted`, `corrected_accepted`, `rejected`, `invalidated`, `superseded`)
  are explicit and disjoint; each of the six Knowledge dispositions leaves a
  stated state; `reprocess` and `escalate` -- declared on the shared
  `Disposition` -- are refused `unsupported(disposition)` for a Knowledge case
  before the decide port is reached. Every Knowledge state is a capture
  `ProposalState` token and every risk class a `RiskClass` token, so the shared
  wire vocabulary gains nothing.
* **KLP-AC-037** -- `correct_and_accept` takes a `correction_patch` naming only
  value-branch fields (`value`), `effective_from`/`effective_to` and, only where
  the predicate's qualifier rule declares it, `date_kind`. Subject, predicate,
  owner, Principal or source profile in a patch, a free-text
  `corrected_value`, an oversized patch, or a corrected fact that fails the
  submit validation (typed value, aware instants, ordered interval, closed
  qualifier) is `invalid_request(corrected_value)` and never reaches the port.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

import pytest
from tests.conftest import Scene
from tests.contract.test_knowledge_review_operator_authority import (
    OPERATOR_CASE,
    _metadata,
    _ReviewPlane,
    _service,
)
from tests.unit.test_knowledge_assertion_domain import SEEDS, _predicate_from_seed

from my_pa.application.commands import DecideReviewCase
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.knowledge_assertions import (
    KNOWLEDGE_CORRECTABLE_FIELDS,
    KNOWLEDGE_PATCH_OCTET_LIMIT,
    KNOWLEDGE_PROMOTING_DISPOSITIONS,
    KNOWLEDGE_REVIEW_DISPOSITIONS,
    corrected_candidate,
)
from my_pa.domain.capture.proposal import ProposalState, RiskClass
from my_pa.domain.capture.review import CorrectionPatch, Disposition
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.knowledge_assertion.vocabulary import (
    OPEN_PROPOSAL_STATES,
    TERMINAL_PROPOSAL_STATES,
    KnowledgeProposalState,
    KnowledgeReviewDisposition,
)
from my_pa.infrastructure.persistence.knowledge_assertions import _STATE_AFTER

PAYMENT: Final = _predicate_from_seed(SEEDS["organization.payment_terms"])
CRITICAL_DATE: Final = _predicate_from_seed(SEEDS["project.critical_date"])
PAYMENT_INSTANT: Final = datetime(2026, 12, 1, tzinfo=UTC)


def _case(plane: _ReviewPlane) -> object:
    return plane.cases[OPERATOR_CASE]


# ---- KLP-AC-096 -----------------------------------------------------------------------


def test_the_proposal_vocabulary_has_explicit_open_and_terminal_states() -> None:
    states = {member.value for member in KnowledgeProposalState}
    assert "unresolved" in states
    assert {member.value for member in OPEN_PROPOSAL_STATES} == {
        "needs_review",
        "deferred",
        "unresolved",
    }
    assert {member.value for member in TERMINAL_PROPOSAL_STATES} == {
        "accepted",
        "corrected_accepted",
        "rejected",
        "invalidated",
        "superseded",
    }
    assert OPEN_PROPOSAL_STATES.isdisjoint(TERMINAL_PROPOSAL_STATES)
    assert frozenset(KnowledgeProposalState) == OPEN_PROPOSAL_STATES | TERMINAL_PROPOSAL_STATES


def test_every_knowledge_token_is_an_existing_shared_wire_token() -> None:
    assert {member.value for member in KnowledgeProposalState} <= {
        member.value for member in ProposalState
    }
    assert {"low", "moderate", "high", "critical"} == {member.value for member in RiskClass}


def test_each_knowledge_disposition_leaves_a_stated_state() -> None:
    assert {member.value for member in KnowledgeReviewDisposition} == KNOWLEDGE_REVIEW_DISPOSITIONS
    assert {
        member.value
        for member in Disposition
        if member not in {Disposition.REPROCESS, Disposition.ESCALATE}
    } == KNOWLEDGE_REVIEW_DISPOSITIONS
    assert set(_STATE_AFTER) == KNOWLEDGE_REVIEW_DISPOSITIONS
    assert dict(_STATE_AFTER) == {
        "accept": "accepted",
        "correct_and_accept": "corrected_accepted",
        "reject": "rejected",
        "defer": "deferred",
        "mark_unresolved": "unresolved",
        "invalidate": "invalidated",
    }
    assert {"accept", "correct_and_accept"} == KNOWLEDGE_PROMOTING_DISPOSITIONS
    # `superseded` is reachable only by a later proposal, never by a decision.
    assert "superseded" not in set(_STATE_AFTER.values())


@pytest.mark.parametrize(
    ("disposition", "reason"),
    [(Disposition.REPROCESS, None), (Disposition.ESCALATE, "Synthetic escalation reason")],
)
def test_unsupported_dispositions_fail_closed_before_the_port(
    scene: Scene, disposition: Disposition, reason: str | None
) -> None:
    plane = _ReviewPlane()
    service = _service(scene.world, plane)
    envelope = service.invoke(
        _metadata(scene.principal),
        DecideReviewCase(
            review_case_id=OPERATOR_CASE,
            expected_review_version=0,
            disposition=disposition,
            reason=reason,
        ),
        principal=scene.principal,
        operator_surface=OperatorSurface.CLI,
    )
    assert envelope.error is not None
    assert envelope.error.code.value == "unsupported"
    assert envelope.error.safe_details == ("disposition",)
    assert plane.requests == []


# ---- KLP-AC-037 ----------------------------------------------------------------------


def test_the_correctable_fields_are_the_value_branch_and_effective_bounds() -> None:
    assert frozenset({"value", "effective_from", "effective_to"}) == KNOWLEDGE_CORRECTABLE_FIELDS
    assert KNOWLEDGE_PATCH_OCTET_LIMIT == 8192


def test_a_value_correction_keeps_subject_and_predicate_and_refingerprints() -> None:
    case = _case(_ReviewPlane())
    corrected = corrected_candidate(case, PAYMENT, {"value": "  Synthetic   net 45 "})  # type: ignore[arg-type]
    unchanged = corrected_candidate(case, PAYMENT, {"value": "Synthetic net 30"})  # type: ignore[arg-type]
    assert corrected.value_text == "Synthetic net 45"
    assert corrected.assertion_fingerprint != unchanged.assertion_fingerprint
    assert corrected.qualifier is None


def test_bounds_and_qualifier_are_correctable_only_where_declared() -> None:
    case = replace(
        _case(_ReviewPlane()),  # type: ignore[type-var]
        subject_kind="project",
        subject_id="prj_fastworld00000001",
        predicate_code=CRITICAL_DATE.predicate_code,
        value_text=None,
        value_datetime=PAYMENT_INSTANT,
        qualifier={"date_kind": "milestone"},
    )
    corrected = corrected_candidate(
        case,
        CRITICAL_DATE,
        {
            "date_kind": "deadline",
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_to": None,
        },
    )
    assert corrected.qualifier == {"date_kind": "deadline"}
    assert corrected.value_datetime == PAYMENT_INSTANT
    assert corrected.effective_from is not None and corrected.effective_to is None


@pytest.mark.parametrize(
    "patch",
    [
        {"subject_id": "ent_fastworld00000002"},
        {"subject_kind": "project"},
        {"predicate_code": "policy.requirement"},
        {"owner_ref": {"kind": "task", "id": "tsk_fastworld0000001"}},
        {"principal_id": "prn_fastworld00000002"},
        {"source_profile_id": "kdsp_fastworld000001"},
        {"corrected_value": "Synthetic"},
        {"date_kind": "deadline"},
        {"value": 30},
        {"value": None},
        {"value": "Synthetic", "classification": "synthetic_test"},
        {"effective_from": "2026-09-01"},
        {"effective_from": 1},
        {"effective_from": "2026-09-02T00:00:00Z", "effective_to": "2026-09-01T00:00:00Z"},
        {"value": "x" * (KNOWLEDGE_PATCH_OCTET_LIMIT + 1)},
    ],
    ids=[
        "subject_id",
        "subject_kind",
        "predicate",
        "owner",
        "principal",
        "source_profile",
        "corrected_value_key",
        "undeclared_qualifier",
        "non_text_value",
        "null_value",
        "extra_field",
        "naive_instant",
        "non_string_instant",
        "unordered_interval",
        "oversized",
    ],
)
def test_an_uncorrectable_patch_is_invalid(patch: dict[str, object]) -> None:
    with pytest.raises(InvalidRequestError) as refused:
        corrected_candidate(_case(_ReviewPlane()), PAYMENT, patch)  # type: ignore[arg-type]
    assert refused.value.safe_details == (SafeDetail.CORRECTED_VALUE,)


def test_service_refuses_a_free_text_corrected_value_and_a_bad_patch_before_the_port(
    scene: Scene,
) -> None:
    plane = _ReviewPlane()
    service = _service(scene.world, plane)
    for command in (
        DecideReviewCase(
            review_case_id=OPERATOR_CASE,
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            corrected_value="Synthetic net 60",
        ),
        DecideReviewCase(
            review_case_id=OPERATOR_CASE,
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            correction_patch=CorrectionPatch.of({"subject_id": "ent_fastworld00000002"}),
        ),
    ):
        envelope = service.invoke(
            _metadata(scene.principal),
            command,
            principal=scene.principal,
            operator_surface=OperatorSurface.CLI,
        )
        assert envelope.error is not None
        assert envelope.error.code.value == "invalid_request"
        assert envelope.error.safe_details == ("corrected_value",)
    assert plane.requests == []


def test_a_valid_patch_reaches_the_port_with_the_corrected_fact(scene: Scene) -> None:
    plane = _ReviewPlane()
    service = _service(scene.world, plane)
    envelope = service.invoke(
        _metadata(scene.principal),
        DecideReviewCase(
            review_case_id=OPERATOR_CASE,
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            correction_patch=CorrectionPatch.of({"value": "Synthetic net 45"}),
        ),
        principal=scene.principal,
        operator_surface=OperatorSurface.CLI,
    )
    assert envelope.error is None, envelope.error
    (request,) = plane.requests
    assert request.disposition == "correct_and_accept"
    assert request.correction_patch == {"value": "Synthetic net 45"}
    assert request.corrected is not None
    assert request.corrected.value_text == "Synthetic net 45"
    assert request.predicate is not None
    assert request.predicate.predicate_code == "organization.payment_terms"
