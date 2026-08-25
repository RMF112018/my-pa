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
            "subject_kind": "capture_proposal",
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

    service = build_service(scene.world, scene.providers)
    stale_metadata = metadata_for(
        Capability.REVIEW_DECIDE, Purpose.REVIEW_DISPOSITION, scene.principal
    ).model_copy(update={"request_id": f"req-{issue_identifier(IdKind.CORRELATION)}"})
    stale = service.invoke(stale_metadata, command, principal=scene.principal)
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    assert stale.error.safe_details == ("expected_review_version",)
    assert len(scene.world.review_decisions) == 1


def test_review_request_replay_returns_the_exact_original_logical_receipt(scene: Scene) -> None:
    case = staged_review_case(scene)
    service = build_service(scene.world, scene.providers)
    metadata = metadata_for(Capability.REVIEW_DECIDE, Purpose.REVIEW_DISPOSITION, scene.principal)
    command = DecideReviewCase(
        review_case_id=case.review_case_id,
        expected_review_version=0,
        disposition=Disposition.REJECT,
    )
    first = service.invoke(metadata, command, principal=scene.principal)
    retry = service.invoke(metadata, command, principal=scene.principal)
    assert first.error is None and retry.error is None
    assert retry.result == first.result
    assert len(scene.world.review_decisions) == 1


def test_review_request_identity_conflicts_when_material_changes(scene: Scene) -> None:
    case = staged_review_case(scene)
    service = build_service(scene.world, scene.providers)
    metadata = metadata_for(Capability.REVIEW_DECIDE, Purpose.REVIEW_DISPOSITION, scene.principal)
    first = DecideReviewCase(
        review_case_id=case.review_case_id,
        expected_review_version=0,
        disposition=Disposition.REJECT,
    )
    changed = DecideReviewCase(
        review_case_id=case.review_case_id,
        expected_review_version=0,
        disposition=Disposition.DEFER,
        reason="changed decision",
    )
    assert service.invoke(metadata, first, principal=scene.principal).error is None
    refused = service.invoke(metadata, changed, principal=scene.principal)
    assert refused.error is not None
    assert refused.error.code is ErrorCode.CONFLICT
    assert len(scene.world.review_decisions) == 1


def test_review_replay_arbitration_encloses_the_single_shared_subject_router() -> None:
    """All four subject branches pass through one reserve/result-complete path."""
    import inspect

    from my_pa.application.service import ApplicationService

    source = inspect.getsource(ApplicationService._review_decide)
    reserve = source.index("_reserve_relationship_write")
    router = source.index("entity_proposal_case")
    delegated_router = source.index("unit_of_work.reviews.decide")
    shared_result = source.index('result_family="review_decision"')
    completion = source.rindex("_complete_relationship_write")
    assert reserve < router < delegated_router < completion < shared_result
    assert source.count("unit_of_work.reviews.decide") == 1


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
