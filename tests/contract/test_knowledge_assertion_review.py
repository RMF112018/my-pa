"""Knowledge cases on the shared Review surface, at the service boundary (KLP-WP-04 slice C).

FAST, over the capture fake world plus a canned Knowledge plane.

* **KLP-AC-033 (Python half)** -- `review.list` asks the Knowledge plane only
  when it is composed and, for a remote caller (a `REMOTE_CLIENT` transport or a
  grant ceiling), only when the caller holds `knowledge.assertions.read` for
  `knowledge_assertion_read`; it passes `remote=True` so the plane withholds in
  its own statement; a Knowledge row carries exactly the frozen R6 section 10.1
  keys (`subject_kind = knowledge_assertion`, `subject_kind_of_fact`,
  `subject_id`, `predicate_code`, `review_requirement`, plus the common seven);
  one page mixes a capture case and a Knowledge case in `(opened_at,
  review_case_id)` order; the `knowledge_assertion` subject filter asks no
  other plane and any other filter asks no Knowledge plane. The page binding,
  cursor and truncation stay the generic ones. (The withholding *before LIMIT*
  is proven on SQL in `tests/security/test_knowledge_review_disclosure.py`; the
  web decoder half is slice D's.)
* **KLP-AC-041** -- a stable Knowledge `review_case_id` decided by an
  operator-review client records `remote_operator_review` /
  `remote_operator_attested` with its client id for every typed disposition;
  the same call from an ordinary ChatLLM client records `remote_interactive` /
  `ordinary_reviewer` and is denied on `requires_operator`.
* **KLP-AC-038 (shape)** -- the decide result is exactly the seven existing
  keys with no discriminator.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import pytest
from tests.conftest import WHEN, Scene, staged_review_case
from tests.contract.test_knowledge_review_operator_authority import (
    CHAT_CLIENT,
    OPERATOR_CASE,
    READ,
    REVIEW_CASE,
    REVIEW_CLIENT,
    _metadata,
    _ReviewPlane,
    _service,
)

from my_pa.application.commands import DecideReviewCase, ListReviewCases
from my_pa.contracts.ports import KnowledgeReviewCaseRow
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.review import CorrectionPatch, Disposition, ReviewSubjectKind
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.purpose import Purpose

KNOWLEDGE_ROW_KEYS: Final = frozenset(
    {
        "review_case_id",
        "proposal_id",
        "proposal_state",
        "risk_class",
        "opened_at",
        "review_version",
        "latest_disposition",
        "subject_kind",
        "subject_kind_of_fact",
        "subject_id",
        "predicate_code",
        "review_requirement",
    }
)
DECIDE_KEYS: Final = frozenset(
    {
        "review_case_id",
        "decision_id",
        "review_version",
        "disposition",
        "proposal_state",
        "assertion_id",
        "receipt_id",
    }
)
NO_READ: Final = frozenset({(Capability.REVIEW_LIST, None), (Capability.REVIEW_DECIDE, None)})
REMOTE_REVIEWER: Final[dict[str, Any]] = {
    "transport": CaptureTransport.REMOTE_CLIENT,
    "capability_grants": READ,
    "authenticated_client_id": REVIEW_CLIENT,
}


class _ListedPlane(_ReviewPlane):
    """Answers `review_cases` with its two cases and records each call's arguments."""

    def __init__(self) -> None:
        super().__init__()
        self.listed: list[dict[str, Any]] = []

    def review_cases(  # type: ignore[override]
        self,
        principal_id: str,
        **arguments: Any,  # noqa: ANN401 - the port's keyword arguments
    ) -> tuple[KnowledgeReviewCaseRow, ...]:
        self.listed.append(arguments)
        rows = sorted(self.cases.values(), key=lambda row: (row.opened_at, row.review_case_id))
        after = arguments["after_opened_at"], arguments["after_review_case_id"]
        if after[0] is not None:
            rows = [row for row in rows if (row.opened_at, row.review_case_id) > after]
        return tuple(rows[: arguments["limit"]])


_LISTS: list[int] = []


def _list(
    service: Any,  # noqa: ANN401 - ApplicationService
    scene: Scene,
    command: ListReviewCases | None = None,
    **composition: Any,  # noqa: ANN401
) -> ResponseEnvelope:
    _LISTS.append(1)
    return service.invoke(
        RequestMetadata(
            request_id=f"req-klp04-review-list-{len(_LISTS)}",
            capability=Capability.REVIEW_LIST,
            purpose=sorted(permitted_purposes(Capability.REVIEW_LIST))[0],
            principal_id=scene.principal.principal_id,
            requested_at=WHEN,
        ),
        command or ListReviewCases(),
        principal=scene.principal,
        **composition,
    )


def _knowledge_rows(envelope: ResponseEnvelope) -> list[dict[str, Any]]:
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return [
        row
        for row in envelope.result["review_cases"]
        if row["subject_kind"] == ReviewSubjectKind.KNOWLEDGE_ASSERTION.value
    ]


@pytest.fixture
def plane() -> _ListedPlane:
    return _ListedPlane()


# ---- KLP-AC-033 ----------------------------------------------------------------------


def test_a_knowledge_row_carries_exactly_the_frozen_keys(scene: Scene, plane: _ListedPlane) -> None:
    service = _service(scene.world, plane)
    rows = _knowledge_rows(_list(service, scene))
    assert len(rows) == 2
    for row in rows:
        assert set(row) == KNOWLEDGE_ROW_KEYS
        assert row["subject_kind"] == "knowledge_assertion"
        assert row["subject_kind_of_fact"] == "entity"
        assert row["subject_id"] == "ent_fastworld00000001"
        assert row["predicate_code"] == "organization.payment_terms"
        assert row["proposal_state"] == "needs_review"
        assert row["risk_class"] == "high"
        assert row["review_version"] == 0
        assert row["latest_disposition"] is None
    assert {row["review_requirement"] for row in rows} == {"requires_operator", "requires_review"}
    assert plane.listed[0]["remote"] is False


def test_one_page_mixes_capture_and_knowledge_cases_in_keyset_order(
    scene: Scene, plane: _ListedPlane
) -> None:
    capture = staged_review_case(scene)
    early = plane.cases[OPERATOR_CASE]
    plane.cases[OPERATOR_CASE] = KnowledgeReviewCaseRow(
        **{**_fields(early), "opened_at": capture.opened_at - timedelta(minutes=1)}
    )
    plane.cases[REVIEW_CASE] = KnowledgeReviewCaseRow(
        **{**_fields(plane.cases[REVIEW_CASE]), "opened_at": capture.opened_at + timedelta(1)}
    )
    service = _service(scene.world, plane)
    envelope = _list(service, scene)
    assert envelope.result is not None
    kinds = [row["subject_kind"] for row in envelope.result["review_cases"]]
    assert kinds == ["knowledge_assertion", "capture_proposal", "knowledge_assertion"]
    page = _list(service, scene, ListReviewCases(page_size=2))
    assert page.result is not None
    assert [row["subject_kind"] for row in page.result["review_cases"]] == [
        "knowledge_assertion",
        "capture_proposal",
    ]
    assert page.disclosure.truncation.is_truncated is True
    cursor = page.disclosure.truncation.next_cursor
    rest = _list(service, scene, ListReviewCases(page_size=2, after=cursor))
    assert rest.result is not None
    assert [row["review_case_id"] for row in rest.result["review_cases"]] == [REVIEW_CASE]
    assert plane.listed[-1]["after_review_case_id"] is not None


def _fields(row: KnowledgeReviewCaseRow) -> dict[str, Any]:
    return {name: getattr(row, name) for name in row.__dataclass_fields__}


def test_an_uncomposed_plane_is_never_asked(scene: Scene, plane: _ListedPlane) -> None:
    from tests.conftest import DEFAULT_LIMITS
    from tests.contract.test_knowledge_review_operator_authority import _UnitOfWork

    from my_pa.application.service import ApplicationService

    off = ApplicationService(
        unit_of_work=lambda: _UnitOfWork(scene.world, plane),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=False,
    )
    assert _knowledge_rows(_list(off, scene)) == []
    assert plane.listed == []


@pytest.mark.parametrize(
    "composition",
    [
        {"transport": CaptureTransport.REMOTE_CLIENT, "capability_grants": NO_READ},
        {"capability_grants": NO_READ},
        {"transport": CaptureTransport.REMOTE_CLIENT},
        {
            "transport": CaptureTransport.REMOTE_CLIENT,
            "capability_grants": frozenset(
                {(Capability.KNOWLEDGE_ASSERTIONS_LIST, Purpose.KNOWLEDGE_ASSERTION_READ)}
            ),
        },
    ],
    ids=["remote-no-read", "local-grants-no-read", "remote-no-grant-set", "list-not-read"],
)
def test_a_remote_caller_without_the_read_grant_never_asks_the_plane(
    scene: Scene, plane: _ListedPlane, composition: dict[str, Any]
) -> None:
    service = _service(scene.world, plane)
    assert _knowledge_rows(_list(service, scene, **composition)) == []
    assert plane.listed == []


@pytest.mark.parametrize(
    "composition",
    [REMOTE_REVIEWER, {"capability_grants": READ}],
    ids=["remote-client", "local-with-grants"],
)
def test_a_granted_remote_caller_asks_the_plane_to_withhold(
    scene: Scene, plane: _ListedPlane, composition: dict[str, Any]
) -> None:
    service = _service(scene.world, plane)
    assert len(_knowledge_rows(_list(service, scene, **composition))) == 2
    assert plane.listed[0]["remote"] is True


def test_the_subject_filter_routes_to_exactly_one_side(scene: Scene, plane: _ListedPlane) -> None:
    staged_review_case(scene)
    service = _service(scene.world, plane)
    only = _list(
        service, scene, ListReviewCases(subject_kind=ReviewSubjectKind.KNOWLEDGE_ASSERTION)
    )
    assert only.result is not None
    assert {row["subject_kind"] for row in only.result["review_cases"]} == {"knowledge_assertion"}
    asked = len(plane.listed)
    other = _list(service, scene, ListReviewCases(subject_kind=ReviewSubjectKind.CAPTURE_PROPOSAL))
    assert other.result is not None
    assert {row["subject_kind"] for row in other.result["review_cases"]} == {"capture_proposal"}
    assert len(plane.listed) == asked


def test_state_and_entity_filters_reach_the_plane(scene: Scene, plane: _ListedPlane) -> None:
    from my_pa.domain.capture.proposal import ProposalState

    service = _service(scene.world, plane)
    _list(
        service,
        scene,
        ListReviewCases(state=ProposalState.DEFERRED, entity_id="ent_fastworld00000001"),
    )
    (arguments,) = plane.listed
    assert arguments["state"] == "deferred"
    assert arguments["entity_id"] == "ent_fastworld00000001"


# ---- KLP-AC-041 / KLP-AC-038 (shape) ----------------------------------------------------------


def _decide(
    service: Any,  # noqa: ANN401
    scene: Scene,
    case: str,
    disposition: Disposition,
    **composition: Any,  # noqa: ANN401
) -> ResponseEnvelope:
    patch = (
        CorrectionPatch.of({"value": "Synthetic net 45"})
        if disposition is Disposition.CORRECT_AND_ACCEPT
        else None
    )
    reason = "Synthetic basis went away" if disposition is Disposition.INVALIDATE else None
    return service.invoke(
        _metadata(scene.principal),
        DecideReviewCase(
            review_case_id=case,
            expected_review_version=0,
            disposition=disposition,
            correction_patch=patch,
            reason=reason,
        ),
        principal=scene.principal,
        **composition,
    )


@pytest.mark.parametrize(
    "disposition",
    [
        Disposition.ACCEPT,
        Disposition.CORRECT_AND_ACCEPT,
        Disposition.REJECT,
        Disposition.DEFER,
        Disposition.MARK_UNRESOLVED,
        Disposition.INVALIDATE,
    ],
)
def test_an_operator_review_client_decides_every_typed_disposition_attested(
    scene: Scene, plane: _ListedPlane, disposition: Disposition
) -> None:
    service = _service(scene.world, plane)
    envelope = _decide(service, scene, OPERATOR_CASE, disposition, **REMOTE_REVIEWER)
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    assert set(envelope.result) == DECIDE_KEYS
    (request,) = plane.requests
    assert request.review_case_id == OPERATOR_CASE
    assert request.disposition == disposition.value
    assert request.decision_channel == "remote_operator_review"
    assert request.operator_authority_class == "remote_operator_attested"
    assert request.authenticated_client_id == REVIEW_CLIENT


def test_an_ordinary_chatllm_client_is_interactive_and_refused_operator_cases(
    scene: Scene, plane: _ListedPlane
) -> None:
    service = _service(scene.world, plane)
    chat = {**REMOTE_REVIEWER, "authenticated_client_id": CHAT_CLIENT}
    refused = _decide(service, scene, OPERATOR_CASE, Disposition.ACCEPT, **chat)
    assert refused.error is not None and refused.error.code.value == "denied"
    accepted = _decide(service, scene, REVIEW_CASE, Disposition.ACCEPT, **chat)
    assert accepted.error is None, accepted.error
    (request,) = plane.requests
    assert request.decision_channel == "remote_interactive"
    assert request.operator_authority_class == "ordinary_reviewer"
    assert request.authenticated_client_id == CHAT_CLIENT


def test_a_local_operator_decision_carries_no_client(scene: Scene, plane: _ListedPlane) -> None:
    service = _service(scene.world, plane)
    envelope = _decide(
        service, scene, OPERATOR_CASE, Disposition.ACCEPT, operator_surface=OperatorSurface.CLI
    )
    assert envelope.error is None, envelope.error
    (request,) = plane.requests
    assert request.authenticated_client_id is None
