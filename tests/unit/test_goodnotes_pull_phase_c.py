"""Phase-C service composition keeps pull identity and completion server-owned."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

import pytest

from my_pa.adapters.mcp.server import _answer
from my_pa.application.commands import (
    CompleteGoodNotesPull,
    GetGoodNotesPullStatus,
    PullGoodNotesWork,
)
from my_pa.application.goodnotes_occurrences import (
    GoodNotesOccurrenceReconciler,
    GoodNotesSemanticPromotionEvidence,
    semantic_proposal_sha256,
)
from my_pa.application.goodnotes_pull_orchestration import (
    PullAssignment,
    PullCompletionAdmission,
    PullCompletionReceipt,
    PullRepositoryConflictError,
    PullWorkState,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import (
    GoodNotesPullCompletionMaterial,
    GoodNotesPullStatusRecord,
    GoodNotesSemanticPromotionEvidenceRecord,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.goodnotes.models import GoodNotesPageWork, issue_stable_id
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.goodnotes_pull import _canonical_payload, _semantic_state
from tests.conftest import DEFAULT_LIMITS, WHEN, FakeUnitOfWork, Scene


@dataclass
class _PullRepository:
    work: GoodNotesPageWork
    disposition: Disposition = Disposition.ACCEPT
    assignments: dict[str, PullAssignment] = field(default_factory=dict)
    client_states: dict[str, PullWorkState] = field(default_factory=dict)
    sessions: dict[str, tuple[str, int, int]] = field(default_factory=dict)
    now: datetime = WHEN

    @property
    def attempts(self) -> int:
        return sum(state.attempts for state in self.client_states.values())

    @property
    def completed(self) -> bool:
        return any(state.completed for state in self.client_states.values())

    material_proposal_sha256: str | None = None

    @property
    def proposal_sha256(self) -> str:
        return hashlib.sha256(b"full-semantic-proposal-identity").hexdigest()

    @property
    def result_sha256(self) -> str:
        value = (
            b"canonical-corrected-semantic-payload"
            if self.disposition is Disposition.CORRECT_AND_ACCEPT
            else b"semantic-payload-only"
        )
        return hashlib.sha256(value).hexdigest()

    def lock_session(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        *,
        max_attempts: int,
        lease_seconds: int,
    ) -> datetime:
        assert principal_id == self.work.principal_id
        policy = (context_id, max_attempts, lease_seconds)
        if self.sessions.setdefault(client_id, policy) != policy:
            raise PullRepositoryConflictError
        return self.now

    def work_states(self, principal_id: str, client_id: str) -> tuple[PullWorkState, ...]:
        if principal_id != self.work.principal_id:
            return ()
        return (self.client_states.get(client_id, PullWorkState(self.work)),)

    def claim_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        assignments: tuple[PullAssignment, ...],
        expected_attempts: tuple[int, ...],
        *,
        max_attempts: int,
        lease_seconds: int,
    ) -> tuple[PullAssignment, ...]:
        self.lock_session(
            principal_id,
            client_id,
            context_id,
            max_attempts=max_attempts,
            lease_seconds=lease_seconds,
        )
        if assignments:
            assert principal_id == self.work.principal_id
            state = self.client_states.get(client_id, PullWorkState(self.work))
            assert expected_attempts == (state.attempts,)
            assert state.assigned_at is None or self.now >= state.assigned_at + timedelta(
                seconds=lease_seconds
            )
            self.client_states[client_id] = replace(
                state,
                attempts=state.attempts + 1,
                latest_assignment=assignments[0],
                assigned_at=self.now,
            )
            self.assignments[assignments[0].assignment_id] = assignments[0]
            assert assignments[0].client_id == client_id
        return assignments

    def assignment(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> PullAssignment | None:
        held = self.assignments.get(assignment_id)
        if held is None or principal_id != self.work.principal_id or held.client_id != client_id:
            return None
        return held

    def completion_material(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> GoodNotesPullCompletionMaterial | None:
        held = self.assignment(principal_id, client_id, assignment_id)
        if held is None:
            return None
        return GoodNotesPullCompletionMaterial(
            assignment_id=assignment_id,
            proposal_id=issue_stable_id("gnprp", assignment_id),
            run_id=held.work.run_id,
            page_version_id=held.work.page_version_id,
            content_sha256=held.work.content_sha256,
            proposal_sha256=self.material_proposal_sha256 or self.proposal_sha256,
            result_sha256=self.result_sha256,
        )

    def complete_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        del context_id
        values: list[PullCompletionReceipt] = []
        for admission in admissions:
            completion = admission.completion
            assert self.assignment(principal_id, client_id, completion.assignment_id) is not None
            values.append(
                PullCompletionReceipt(
                    completion_id=hashlib.sha256(completion.assignment_id.encode()).hexdigest(),
                    assignment_id=completion.assignment_id,
                    idempotency_key=completion.idempotency_key,
                    request_fingerprint=admission.request_fingerprint,
                    result_sha256=completion.result_sha256,
                )
            )
        self.client_states[client_id] = replace(self.client_states[client_id], completed=True)
        return tuple(values)

    def status(
        self,
        principal_id: str,
        client_id: str,
        *,
        context_id: str,
        max_attempts: int,
        lease_seconds: int,
    ) -> GoodNotesPullStatusRecord:
        assert principal_id == self.work.principal_id
        if client_id in self.sessions and self.sessions[client_id] != (
            context_id,
            max_attempts,
            lease_seconds,
        ):
            raise PullRepositoryConflictError
        state = self.client_states.get(client_id, PullWorkState(self.work))
        active = state.assigned_at is not None and self.now < state.assigned_at + timedelta(
            seconds=lease_seconds
        )
        return GoodNotesPullStatusRecord(
            pending=int(not state.completed and not active and state.attempts < max_attempts),
            assigned=int(not state.completed and active),
            completed=int(state.completed),
            exhausted=int(not state.completed and not active and state.attempts >= max_attempts),
        )

    def semantic_review_evidence(
        self, principal_id: str, run_id: str, proposal_sha256s: tuple[str, ...]
    ) -> tuple[GoodNotesSemanticPromotionEvidenceRecord, ...]:
        assert principal_id == self.work.principal_id
        assert run_id == self.work.run_id
        return tuple(
            GoodNotesSemanticPromotionEvidenceRecord(
                principal_id=principal_id,
                run_id=run_id,
                proposal_sha256=digest,
                disposition=self.disposition,
                corrected_payload=(
                    {"segments": []} if self.disposition is Disposition.CORRECT_AND_ACCEPT else None
                ),
                result_sha256=(
                    self.result_sha256
                    if self.disposition is Disposition.CORRECT_AND_ACCEPT
                    else None
                ),
            )
            for digest in proposal_sha256s
            if digest == self.proposal_sha256
        )


class _PullUnitOfWork(FakeUnitOfWork):
    def __init__(self, scene: Scene, repository: _PullRepository) -> None:
        super().__init__(scene.world)
        self._repository = repository

    @property
    def goodnotes_pull(self) -> object:
        return self._repository


def _metadata(capability: Capability, purpose: Purpose) -> RequestMetadata:
    return RequestMetadata(
        request_id="req_aaaaaaaaaaaaaaaaaaaaaaaa",
        principal_id="prn_aaaaaaaaaaaaaaaaaaaaaaaa",
        capability=capability,
        purpose=purpose,
        requested_at=WHEN,
    )


def _service(scene: Scene, repository: _PullRepository) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: _PullUnitOfWork(scene, repository),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        goodnotes_pull_enabled=True,
        goodnotes_pull_cursor_signing_key=b"k" * 32,
    )


def _repository(scene: Scene) -> _PullRepository:
    return _PullRepository(
        GoodNotesPageWork(
            run_id=issue_stable_id("gnrun", "phase-c"),
            page_version_id=issue_stable_id("gnver", "phase-c"),
            principal_id=scene.principal.principal_id,
            content_sha256=hashlib.sha256(b"synthetic-page").hexdigest(),
        )
    )


@pytest.mark.parametrize("disposition", [Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT])
def test_pull_complete_and_status_use_authenticated_client_and_review(
    scene: Scene, disposition: Disposition
) -> None:
    repository = _repository(scene)
    repository.disposition = disposition
    assert repository.proposal_sha256 != repository.result_sha256
    service = _service(scene, repository)
    pulled = service.invoke(
        _metadata(Capability.GOODNOTES_PULL, Purpose.GOODNOTES_PULL),
        PullGoodNotesWork(batch_size=1, cursor=None),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )
    assert pulled.error is None
    assignment_id = pulled.result["assignments"][0]["assignment_id"]  # type: ignore[index]

    completed = service.invoke(
        _metadata(Capability.GOODNOTES_COMPLETE, Purpose.GOODNOTES_PULL),
        CompleteGoodNotesPull((assignment_id,)),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )
    assert completed.error is None
    assert completed.result["completions"][0]["assignment_id"] == assignment_id  # type: ignore[index]
    assert repository.completed is True


@pytest.mark.parametrize(
    ("disposition", "state"),
    [
        (Disposition.ACCEPT, ProposalState.ACCEPTED),
        (Disposition.CORRECT_AND_ACCEPT, ProposalState.CORRECTED_ACCEPTED),
        (Disposition.REJECT, ProposalState.REJECTED),
        (Disposition.DEFER, ProposalState.DEFERRED),
        (Disposition.MARK_UNRESOLVED, ProposalState.UNRESOLVED),
        (Disposition.REPROCESS, ProposalState.SUPERSEDED),
        (Disposition.ESCALATE, ProposalState.NEEDS_REVIEW),
        (Disposition.INVALIDATE, ProposalState.INVALIDATED),
    ],
)
def test_every_durable_semantic_review_action_projects_to_a_public_state(
    disposition: Disposition, state: ProposalState
) -> None:
    assert _semantic_state(disposition) is state


def test_canonical_correction_detaches_from_mutable_request_containers() -> None:
    supplied: dict[str, object] = {"segments": [{"transcription": "corrected"}]}
    stored = _canonical_payload(supplied)
    supplied["segments"] = []

    assert stored == {"segments": [{"transcription": "corrected"}]}


def test_persisted_and_in_memory_promotion_evidence_share_exact_binding() -> None:
    principal_id = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
    run_id = issue_stable_id("gnrun", "promotion-binding")
    proposal = (
        issue_stable_id("gnver", "promotion-binding"),
        "note-unit.v1",
        "synthetic",
        "1",
        {
            "segments": [],
            "candidate_tags": [],
            "ranked_candidates": [],
            "confidence": None,
        },
    )
    proposal_sha256 = semantic_proposal_sha256(*proposal)
    values = (
        GoodNotesSemanticPromotionEvidence(
            principal_id=principal_id,
            run_id=run_id,
            proposal_sha256=proposal_sha256,
            disposition=Disposition.ACCEPT,
        ),
        GoodNotesSemanticPromotionEvidenceRecord(
            principal_id=principal_id,
            run_id=run_id,
            proposal_sha256=proposal_sha256,
            disposition=Disposition.ACCEPT,
        ),
    )

    for evidence in values:
        assert evidence.is_bound_to(principal_id, run_id)
        assert not evidence.is_bound_to("prn_bbbbbbbbbbbbbbbbbbbbbbbb", run_id)
        assert not evidence.is_bound_to(principal_id, issue_stable_id("gnrun", "other"))

    # Both structurally bound record types remain untrusted caller data.
    # Replace the removed helper's acceptance assertion with canonical refusal.
    from my_pa.infrastructure.goodnotes.pdf import split_admitted_pdf
    from my_pa.infrastructure.goodnotes.render import production_page_renderer
    from tests.unit.goodnotes_durable_note_memory import MemoryDurableNoteStore
    from tests.unit.test_goodnotes_orchestrator import (
        COVER,
        _orchestrator,
        _propose,
        _request,
    )
    from tests.unit.test_goodnotes_orchestrator import (
        WHEN as ORCHESTRATOR_WHEN,
    )
    from tests.unit.vector_pdf import vector_pdf

    store = MemoryDurableNoteStore()
    request = _request(vector_pdf((COVER,)), "phase-c-forged-promotion")
    first = _orchestrator().run(
        request,
        renderer=production_page_renderer(),
        splitter=split_admitted_pdf,
        store=store,
        clock=lambda: ORCHESTRATOR_WHEN,
    )
    _propose(store, first.run.run_id)
    stored = store.semantic_proposals_for_run(principal_id, first.run.run_id)[0]
    for evidence_type in (
        GoodNotesSemanticPromotionEvidence,
        GoodNotesSemanticPromotionEvidenceRecord,
    ):
        forged = evidence_type(
            principal_id=principal_id,
            run_id=first.run.run_id,
            proposal_sha256=semantic_proposal_sha256(*stored),
            disposition=Disposition.ACCEPT,
        )
        with pytest.raises(ValueError, match="caller promotion evidence"):
            GoodNotesOccurrenceReconciler().reconcile(
                principal_id,
                first.run.run_id,
                repository=store,
                promotion_evidence=(forged,),
                clock=lambda: ORCHESTRATOR_WHEN,
            )
    assert not store._notes and not store._occurrences and not store._revisions
    assert not store._changes and not store._promotions


def test_completion_refuses_material_not_bound_to_reviewed_proposal(scene: Scene) -> None:
    repository = _repository(scene)
    repository.material_proposal_sha256 = "0" * 64
    service = _service(scene, repository)
    pulled = service.invoke(
        _metadata(Capability.GOODNOTES_PULL, Purpose.GOODNOTES_PULL),
        PullGoodNotesWork(batch_size=1, cursor=None),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )
    assignment_id = pulled.result["assignments"][0]["assignment_id"]  # type: ignore[index]

    refused = service.invoke(
        _metadata(Capability.GOODNOTES_COMPLETE, Purpose.GOODNOTES_PULL),
        CompleteGoodNotesPull((assignment_id,)),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )

    assert refused.error is not None
    assert refused.error.code.value == "conflict"
    assert repository.completed is False


def test_completion_rejects_unreviewed_and_cross_client_handles(scene: Scene) -> None:
    repository = _repository(scene)
    service = _service(scene, repository)
    pulled = service.invoke(
        _metadata(Capability.GOODNOTES_PULL, Purpose.GOODNOTES_PULL),
        PullGoodNotesWork(batch_size=1, cursor=None),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )
    assignment_id = pulled.result["assignments"][0]["assignment_id"]  # type: ignore[index]

    for client_id, disposition in (
        ("oauth-client-a", Disposition.REJECT),
        ("oauth-client-a", Disposition.REPROCESS),
        ("oauth-client-a", Disposition.INVALIDATE),
        ("oauth-client-b", Disposition.ACCEPT),
    ):
        repository.disposition = disposition
        refused = service.invoke(
            _metadata(Capability.GOODNOTES_COMPLETE, Purpose.GOODNOTES_PULL),
            CompleteGoodNotesPull((assignment_id,)),
            principal=scene.principal,
            authenticated_client_id=client_id,
        )
        assert refused.error is not None
        assert refused.error.code.value == "conflict"
        assert repository.completed is False


def test_feature_and_missing_client_fail_closed(scene: Scene) -> None:
    repository = _repository(scene)
    disabled = ApplicationService(
        unit_of_work=lambda: _PullUnitOfWork(scene, repository),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )
    assert Capability.GOODNOTES_PULL not in disabled.available_capabilities

    enabled = _service(scene, repository)
    assert {
        Capability.GOODNOTES_PULL,
        Capability.GOODNOTES_COMPLETE,
        Capability.GOODNOTES_STATUS,
    } <= enabled.available_capabilities
    refused = enabled.invoke(
        _metadata(Capability.GOODNOTES_PULL, Purpose.GOODNOTES_PULL),
        PullGoodNotesWork(batch_size=1, cursor=None),
        principal=scene.principal,
    )
    assert refused.error is not None
    assert refused.error.code.value == "unsupported"
    assert repository.attempts == 0


def test_remote_mcp_passes_only_server_authenticated_client_context(scene: Scene) -> None:
    repository = _repository(scene)
    service = _service(scene, repository)
    grants = frozenset({(Capability.GOODNOTES_PULL, Purpose.GOODNOTES_PULL)})
    _text, failed, _image = _answer(
        service,
        scene.principal,
        Capability.GOODNOTES_PULL.value,
        {"payload": {"batch_size": 1}},
        CaptureTransport.REMOTE_CLIENT,
        grants,
        lambda: WHEN,
        None,
        "oauth-client-a",
    )
    assert failed is False, _text
    assert next(iter(repository.assignments.values())).client_id == "oauth-client-a"

    other = _repository(scene)
    _text, failed, _image = _answer(
        _service(scene, other),
        scene.principal,
        Capability.GOODNOTES_PULL.value,
        {"payload": {"batch_size": 1}},
        CaptureTransport.REMOTE_CLIENT,
        grants,
        lambda: WHEN,
    )
    assert failed is True
    assert other.attempts == 0


def test_public_restart_and_configured_lease_resume_stable_context(scene: Scene) -> None:
    repository = _repository(scene)

    def service(lease: int) -> ApplicationService:
        return ApplicationService(
            unit_of_work=lambda: _PullUnitOfWork(scene, repository),
            limits=DEFAULT_LIMITS,
            clock=lambda: WHEN,
            goodnotes_pull_enabled=True,
            goodnotes_pull_cursor_signing_key=b"k" * 32,
            goodnotes_pull_assignment_lease_seconds=lease,
        )

    def pull(lease: int) -> ResponseEnvelope:
        return service(lease).invoke(
            _metadata(Capability.GOODNOTES_PULL, Purpose.GOODNOTES_PULL),
            PullGoodNotesWork(batch_size=1, cursor=None),
            principal=scene.principal,
            authenticated_client_id="oauth-client-a",
        )

    first = pull(60)
    assert first.error is None
    policy = repository.sessions["oauth-client-a"]
    assert policy[2] == 60
    repository.now += timedelta(seconds=59)
    restarted = pull(60)
    assert restarted.error is None and restarted.result == first.result
    assert repository.sessions["oauth-client-a"] == policy
    changed = pull(61)
    assert changed.error is not None and changed.error.code == "conflict"
    status = service(61).invoke(
        _metadata(Capability.GOODNOTES_STATUS, Purpose.GOODNOTES_PULL_OBSERVATION),
        GetGoodNotesPullStatus(),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )
    assert status.error is not None and status.error.code == "conflict"
    assert repository.attempts == 1
    repository.now += timedelta(seconds=1)
    successor = pull(60)
    assert successor.error is None and successor.result != first.result
    assert repository.attempts == 2


def test_public_status_before_discovery_does_not_create_session(scene: Scene) -> None:
    repository = _repository(scene)
    result = _service(scene, repository).invoke(
        _metadata(Capability.GOODNOTES_STATUS, Purpose.GOODNOTES_PULL_OBSERVATION),
        GetGoodNotesPullStatus(),
        principal=scene.principal,
        authenticated_client_id="oauth-client-a",
    )
    assert result.error is None
    assert result.result == {"pending": 1, "assigned": 0, "completed": 0, "exhausted": 0}
    assert repository.sessions == {}
