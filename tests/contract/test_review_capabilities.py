"""The two review capabilities expose bounded metadata and governed transitions."""

from __future__ import annotations

from tests.conftest import Scene, build_service, metadata_for, staged_review_case

from my_pa.application.commands import DecideReviewCase, ListReviewCases
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier


def _invoke(scene: Scene, capability: Capability, command: object) -> ResponseEnvelope:
    return build_service(scene.world, scene.providers).invoke(
        metadata_for(
            capability,
            (
                Purpose.CAPTURE_REVIEW
                if capability is Capability.REVIEW_LIST
                else Purpose.REVIEW_DISPOSITION
            ),
            scene.principal,
        ),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )


def test_review_list_returns_case_metadata_without_capture_content(scene: Scene) -> None:
    case = staged_review_case(scene)
    answer = _invoke(scene, Capability.REVIEW_LIST, ListReviewCases())
    assert answer.error is None
    assert answer.result is not None
    assert answer.result["review_cases"] == [
        {
            "review_case_id": case.review_case_id,
            "proposal_id": case.proposal_id,
            "capture_id": case.capture_id,
            "version_id": case.version_id,
            "proposal_type": "commitment",
            "proposal_state": "needs_review",
            "risk_class": "moderate",
            "opened_at": "2026-08-02T12:00:00.000Z",
            "review_version": 0,
            "latest_disposition": None,
        }
    ]
    rendered = answer.to_canonical_json()
    assert "a synthetic note" not in rendered
    assert "normalized_value" not in rendered


def test_review_decision_appends_and_a_stale_expected_version_conflicts(scene: Scene) -> None:
    case = staged_review_case(scene)
    command = DecideReviewCase(
        review_case_id=case.review_case_id,
        expected_review_version=0,
        disposition=Disposition.REJECT,
    )
    accepted = _invoke(scene, Capability.REVIEW_DECIDE, command)
    assert accepted.error is None
    assert accepted.result is not None
    assert accepted.result["proposal_state"] == "rejected"
    assert accepted.result["review_version"] == 1
    assert len(scene.world.review_decisions) == 1

    stale = _invoke(scene, Capability.REVIEW_DECIDE, command)
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    assert stale.error.safe_details == ("expected_review_version",)
    assert len(scene.world.review_decisions) == 1


def test_acceptance_is_terminal_at_the_application_port(scene: Scene) -> None:
    case = staged_review_case(scene)
    accepted = _invoke(
        scene,
        Capability.REVIEW_DECIDE,
        DecideReviewCase(
            review_case_id=case.review_case_id,
            expected_review_version=0,
            disposition=Disposition.ACCEPT,
        ),
    )
    assert accepted.error is None
    assert accepted.result is not None
    assertion_id = accepted.result["assertion_id"]
    receipt_id = accepted.result["receipt_id"]

    refused = _invoke(
        scene,
        Capability.REVIEW_DECIDE,
        DecideReviewCase(
            review_case_id=case.review_case_id,
            expected_review_version=1,
            disposition=Disposition.REJECT,
        ),
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.CONFLICT
    assert len(scene.world.review_decisions) == 1
    decision = scene.world.review_decisions[0]
    assert decision.assertion_id == assertion_id
    assert decision.receipt_id == receipt_id


def test_review_decide_distinguishes_absence_from_invalid_evidence(scene: Scene) -> None:
    answer = _invoke(
        scene,
        Capability.REVIEW_DECIDE,
        DecideReviewCase(
            review_case_id=issue_identifier(IdKind.REVIEW_CASE),
            expected_review_version=0,
            disposition=Disposition.REJECT,
        ),
    )
    assert answer.error is not None
    assert answer.error.code is ErrorCode.NOT_FOUND
    assert answer.error.safe_details == ("review_case_id",)


def test_unreachable_dispositions_are_unsupported_not_recorded(scene: Scene) -> None:
    case = staged_review_case(scene)
    answer = _invoke(
        scene,
        Capability.REVIEW_DECIDE,
        DecideReviewCase(
            review_case_id=case.review_case_id,
            expected_review_version=0,
            disposition=Disposition.REPROCESS,
        ),
    )
    assert answer.error is not None
    assert answer.error.code is ErrorCode.UNSUPPORTED
    assert answer.error.safe_details == ("disposition",)
    assert not scene.world.review_decisions
