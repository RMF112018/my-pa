"""KLP-WP-03/04: the Knowledge Assertion catalog, plane switch and scope (FAST).

* **KLP-AC-001** -- the extraction plane's `knowledge.search`/`read`/`reveal`/
  `coverage` keep their names, purposes and commands; `knowledge.reveal` answers
  a `kasr_` identifier as not found, and `knowledge.assertions.reveal` answers a
  capture-plane `asrt_` identifier as not found.
* **KLP-AC-015 (WP-03 slice)** -- each of the six names maps to exactly one
  permitted Purpose: the five reads to `knowledge_assertion_read`, create to
  `knowledge_assertion_authoring`.
* **KLP-AC-083** -- `MY_PA_KNOWLEDGE_ASSERTIONS_ENABLED` defaults off and requires
  Relationship Intelligence; off, the six are absent from
  `available_capabilities` and `capabilities.get`, and the ChatLLM profile does
  not demand their grants.
* **KLP-AC-104 (WP-03 slice)** -- all six are in `_SCOPELESS` and the scopeless
  arm of `_requested_scope`, and a granted `invoke()` succeeds end to end.
* **KLP-AC-105** -- an explicit name set (never a `knowledge.` prefix) maps the
  six to the `KNOWLEDGE_ASSERTIONS` prerequisite, and `composed_capabilities`
  raises on an unknown prerequisite.

KLP-WP-04 slice A adds the discovery pair:

* **KLP-AC-015 (whole)** -- submit and checkpoint each map to exactly one
  permitted Purpose, `knowledge_assertion_observation`, used by nothing else; with
  the WP-03 six the mapping is exhaustive over every Knowledge Assertion name.
* **KLP-AC-104 (catalog slice)** -- both are in `_SCOPELESS` and the scopeless arm
  of `_requested_scope`; a granted invoke is *allowed* by policy (audited
  `allowed`) and reaches the second service gate; slice B2: a granted submit
  succeeds end to end; slice B3: a granted checkpoint succeeds end to end (the
  binding read, the replay lookup, then the advance), and a build without a
  checkpoint signing key refuses every checkpoint before any read.
* **R6 section 6.1 second gate** -- `unsupported` unless the remote transport and
  a client in the exact discovery allowlist; the plane switch withholds both.

KLP-WP-05 adds `record_events.provenance`, the last KLP name:

* **KLP-AC-002** -- the KLP capability names are exactly the matrix's list
  (181 pre-KLP members plus that list), and `knowledge.assertions.propose` does
  not exist.
* **KLP-AC-015 (closed)** -- provenance maps to exactly one permitted Purpose,
  `record_event_provenance_read`, used by nothing else; with the WP-03/04 eight
  the mapping is exhaustive over all nine, each to its matrix purpose.
* **KLP-AC-104 (closed)** -- provenance is in `_SCOPELESS` and the scopeless arm
  of `_requested_scope`; a granted `invoke()` succeeds end to end through the
  feed reader, and the plane switch withholds and refuses it.
* **KLP-AC-105** -- the explicit name set is now the six data names plus
  provenance.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeUnitOfWork,
    Scene,
    World,
    build_service,
    metadata_for,
)
from tests.unit.test_knowledge_assertion_domain import SEEDS, _predicate_from_seed

from my_pa.application import chatllm_data_profile
from my_pa.application.authorization import Authorization, _requested_scope
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.commands import (
    CheckpointKnowledgeDiscovery,
    CreateKnowledgeAssertion,
    GetCapabilities,
    GetKnowledgeAssertionHistory,
    GetRecordEventProvenance,
    ListKnowledgeAssertions,
    ReadKnowledgeAssertion,
    RevealKnowledgeAssertion,
    RevealSubject,
    SearchKnowledgeAssertions,
    SubmitKnowledgeAssertion,
)
from my_pa.application.errors import UnsupportedError
from my_pa.application.service import ApplicationService, published_capabilities
from my_pa.bootstrap.settings import Settings, SettingsError
from my_pa.contracts.ports import (
    KnowledgeAssertionHistory,
    KnowledgeAssertionPage,
    KnowledgeAssertionRepository,
    KnowledgeAssertionReveal,
    KnowledgeAssertionRow,
    KnowledgeCheckpointRequest,
    KnowledgeCheckpointResult,
    KnowledgeCreateRequest,
    KnowledgeReviewCaseRow,
    KnowledgeReviewDecisionRequest,
    KnowledgeReviewDecisionResult,
    KnowledgeSourceBinding,
    KnowledgeSubmissionResult,
    KnowledgeSubmitRequest,
)
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    KNOWLEDGE_ASSERTION_DATA_NAMES,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeCheckpointKind,
    KnowledgeSubjectKind,
)
from my_pa.domain.policy.decision import _SCOPELESS, POLICY_VERSION, PolicyDecision
from my_pa.domain.record_events import RecordEventFamily
from my_pa.domain.source.registry import issue_identifier

KNOWLEDGE_READS: Final = (
    Capability.KNOWLEDGE_ASSERTIONS_READ,
    Capability.KNOWLEDGE_ASSERTIONS_LIST,
    Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
    Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
    Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
)
KNOWLEDGE: Final = frozenset({*KNOWLEDGE_READS, Capability.KNOWLEDGE_ASSERTIONS_CREATE})
DISCOVERY: Final = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
)
PROVENANCE: Final = Capability.RECORD_EVENTS_PROVENANCE
EXTRACTION: Final = {
    Capability.KNOWLEDGE_SEARCH: "knowledge.search",
    Capability.KNOWLEDGE_READ: "knowledge.read",
    Capability.KNOWLEDGE_REVEAL: "knowledge.reveal",
    Capability.KNOWLEDGE_COVERAGE: "knowledge.coverage",
}
MATRIX: Final = json.loads(
    (Path(__file__).parents[1] / "architecture" / "klp_implementation_matrix_r6.json").read_text(
        encoding="utf-8"
    )
)
_ROW = KnowledgeAssertionRow(
    assertion_id="kasr_fastworld00000001",
    subject_kind="principal",
    subject_id="prn_fastworld00000001",
    predicate_code="policy.requirement",
    predicate_version=1,
    value_type="text",
    value_text="Synthetic value",
    value_datetime=None,
    qualifier=None,
    effective_from=None,
    effective_to=None,
    epistemic_status="principal_asserted",
    classification="private_local",
    lifecycle="active",
    version=1,
    supersedes_assertion_id=None,
    created_at=datetime(2026, 10, 4, tzinfo=UTC),
    updated_at=datetime(2026, 10, 4, tzinfo=UTC),
)


class _CannedKnowledge(KnowledgeAssertionRepository):
    """A canned plane: proves routing, authorization and presentation, not SQL."""

    def __init__(self, *, seeded: bool = False) -> None:
        self.calls: list[str] = []
        self.seeded = seeded

    def predicate_head(self, predicate_code: str) -> object:
        self.calls.append("predicate_head")
        # KLP-WP-04 slice B2: the frozen seed head for a seeded code, so a granted
        # submit runs end to end; an unregistered code is still `None`.
        if self.seeded and predicate_code in SEEDS:
            return _predicate_from_seed(SEEDS[predicate_code])
        return None

    def read_assertion(
        self, principal_id: str, assertion_id: str, *, remote: bool
    ) -> KnowledgeAssertionRow | None:
        self.calls.append("read")
        return replace(_ROW, assertion_id=assertion_id)

    def page(self, principal_id: str, **_: object) -> KnowledgeAssertionPage:  # type: ignore[override]
        self.calls.append("page")
        return KnowledgeAssertionPage(rows=(_ROW,), has_more=False)

    def history(
        self, principal_id: str, assertion_id: str, *, remote: bool
    ) -> KnowledgeAssertionHistory | None:
        self.calls.append("history")
        return KnowledgeAssertionHistory(
            assertion=_ROW, mutations=(), predecessor_id=None, successor_id=None
        )

    def reveal(
        self, principal_id: str, assertion_id: str, *, remote: bool
    ) -> KnowledgeAssertionReveal | None:
        self.calls.append("reveal")
        return KnowledgeAssertionReveal(
            assertion=_ROW,
            submission_id="kasub_fastworld000001",
            submission_origin="explicit_create",
            evidence=(),
        )

    def create(
        self,
        principal_id: str,
        request: KnowledgeCreateRequest,
        *,
        at: datetime,
        correlation_id: str,
        remote: bool = False,
    ) -> KnowledgeSubmissionResult:
        raise AssertionError("an unregistered predicate never reaches create")

    def replay_create(
        self, principal_id: str, idempotency_key: str, request_digest: str, *, remote: bool
    ) -> KnowledgeSubmissionResult | None:
        self.calls.append("replay_create")
        return None

    def source_binding(
        self, principal_id: str, source_profile_id: str, authenticated_client_id: str
    ) -> KnowledgeSourceBinding | None:
        self.calls.append("source_binding")
        return KnowledgeSourceBinding(
            source_profile_id=source_profile_id,
            authenticated_client_id=authenticated_client_id,
            scope_digest="b" * 64,
            origin_system="synthetic",
            is_synthetic=True,
        )

    def replay_submission(  # type: ignore[override]
        self, principal_id: str, **_: object
    ) -> KnowledgeSubmissionResult | None:
        self.calls.append("replay_submission")
        return None

    def submit(  # type: ignore[override]
        self, principal_id: str, request: KnowledgeSubmitRequest, **_: object
    ) -> KnowledgeSubmissionResult:
        self.calls.append("submit")
        return KnowledgeSubmissionResult(
            submission_id="kasub_fastworld000002",
            outcome="review_queued",
            reason="requires_review",
            assertion_id=None,
            assertion_version=None,
            mutation_id=None,
            canonical_owner="knowledge_assertion",
            current_lifecycle=None,
            proposal_id="kaprp_fastworld000001",
            review_case_id="rvw_fastworld000001",
        )

    # KLP-WP-04 slice B3: a canned checkpoint plane (routing, not SQL).

    def replay_checkpoint(  # type: ignore[override]
        self, principal_id: str, **_: object
    ) -> KnowledgeCheckpointResult | None:
        self.calls.append("replay_checkpoint")
        return None

    def checkpoint(  # type: ignore[override]
        self, principal_id: str, request: KnowledgeCheckpointRequest, **_: object
    ) -> KnowledgeCheckpointResult:
        self.calls.append("checkpoint")
        return KnowledgeCheckpointResult(
            checkpoint_request_id="kdcpr_fastworld000001",
            outcome="advanced",
            reason="advanced",
            checkpoint_id="kdcp_fastworld000001",
            checkpoint_version=1,
            checkpoint_kind=request.checkpoint_kind,
            private_envelope=request.private_envelope,
            private_token_redacted=False,
        )

    # KLP-WP-04 slice C: a canned Review plane (routing, not SQL) -- no case.

    def review_cases(  # type: ignore[override]
        self, principal_id: str, **_: object
    ) -> tuple[KnowledgeReviewCaseRow, ...]:
        self.calls.append("review_cases")
        return ()

    def review_case(
        self, principal_id: str, review_case_id: str, *, remote: bool
    ) -> KnowledgeReviewCaseRow | None:
        self.calls.append("review_case")
        return None

    def decide_review(
        self, principal_id: str, request: KnowledgeReviewDecisionRequest, *, at: datetime
    ) -> KnowledgeReviewDecisionResult:
        raise AssertionError("no canned case reaches decide_review")


class _KnowledgeUnitOfWork(FakeUnitOfWork):
    def __init__(self, world: World, repository: _CannedKnowledge) -> None:
        super().__init__(world)
        self._repository = repository

    @property
    def knowledge_assertions(self) -> KnowledgeAssertionRepository:
        return self._repository


def _composed(world: World, repository: _CannedKnowledge) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: _KnowledgeUnitOfWork(world, repository),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=True,
    )


def _commands(principal_id: str) -> dict[Capability, object]:
    assertion = "kasr_fastworld00000001"
    return {
        Capability.KNOWLEDGE_ASSERTIONS_READ: ReadKnowledgeAssertion(assertion_id=assertion),
        Capability.KNOWLEDGE_ASSERTIONS_LIST: ListKnowledgeAssertions(),
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH: SearchKnowledgeAssertions(query="synthetic"),
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY: GetKnowledgeAssertionHistory(
            assertion_id=assertion
        ),
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL: RevealKnowledgeAssertion(assertion_id=assertion),
        Capability.KNOWLEDGE_ASSERTIONS_CREATE: CreateKnowledgeAssertion(
            subject_kind=KnowledgeSubjectKind.PRINCIPAL,
            subject_id=principal_id,
            predicate_code="policy.requirement",
            value="Synthetic value",
            idempotency_key="klp03-fast-create",
        ),
    }


# ---- KLP-AC-001 -----------------------------------------------------------------


def test_the_extraction_plane_names_purposes_and_commands_are_unchanged() -> None:
    for capability, name in EXTRACTION.items():
        assert capability.value == name
        assert capability not in KNOWLEDGE
        assert capability not in KNOWLEDGE_ASSERTION_DATA_NAMES
        assert (
            CHATLLM_CAPABILITY_POLICY[capability].composition_prerequisite
            is ChatLLMCompositionPrerequisite.ALWAYS
        )
    assert permitted_purposes(Capability.KNOWLEDGE_SEARCH) == {Purpose.KNOWLEDGE_SEARCH}
    assert permitted_purposes(Capability.KNOWLEDGE_READ) == {Purpose.KNOWLEDGE_READ}
    assert permitted_purposes(Capability.KNOWLEDGE_REVEAL) == {Purpose.CAPTURE_REVIEW}
    assert permitted_purposes(Capability.KNOWLEDGE_COVERAGE) == {Purpose.STATUS_OBSERVATION}
    assert RevealSubject.capability is Capability.KNOWLEDGE_REVEAL


def test_knowledge_reveal_answers_a_knowledge_assertion_id_as_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    response = service.invoke(
        metadata_for(Capability.KNOWLEDGE_REVEAL, Purpose.CAPTURE_REVIEW, scene.principal),
        RevealSubject(subject_id=issue_identifier(IdKind.KNOWLEDGE_ASSERTION)),
        principal=scene.principal,
    )
    assert response.error is not None
    assert response.error.code.value == "not_found"


def test_knowledge_assertions_reveal_answers_a_capture_assertion_id_as_not_found(
    scene: Scene,
) -> None:
    repository = _CannedKnowledge()
    service = _composed(scene.world, repository)
    response = service.invoke(
        metadata_for(
            Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
            Purpose.KNOWLEDGE_ASSERTION_READ,
            scene.principal,
        ),
        RevealKnowledgeAssertion(assertion_id=issue_identifier(IdKind.ASSERTION)),
        principal=scene.principal,
    )
    assert response.error is not None
    assert response.error.code.value == "not_found"
    assert repository.calls == []


# ---- KLP-AC-015 -----------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(KNOWLEDGE), ids=lambda c: c.value)
def test_each_knowledge_name_maps_to_exactly_one_permitted_purpose(capability: Capability) -> None:
    expected = (
        Purpose.KNOWLEDGE_ASSERTION_AUTHORING
        if capability is Capability.KNOWLEDGE_ASSERTIONS_CREATE
        else Purpose.KNOWLEDGE_ASSERTION_READ
    )
    assert permitted_purposes(capability) == {expected}


def test_the_two_purposes_are_declared_and_used_only_by_the_six() -> None:
    assert Purpose.KNOWLEDGE_ASSERTION_READ.value == "knowledge_assertion_read"
    assert Purpose.KNOWLEDGE_ASSERTION_AUTHORING.value == "knowledge_assertion_authoring"
    users = {
        capability
        for capability in Capability
        if permitted_purposes(capability)
        & {Purpose.KNOWLEDGE_ASSERTION_READ, Purpose.KNOWLEDGE_ASSERTION_AUTHORING}
    }
    assert users == KNOWLEDGE


def test_submit_checkpoint_and_provenance_are_not_declared_by_wp03() -> None:
    """At the KLP-WP-03 head the three names were admitted ahead of the domain.

    The node id is kept from KLP-WP-03 (KLP-AC-080). Its claim is about the WP-03
    head, which the schema-ahead gap row for `wp03` records: the database admitted
    submit, checkpoint and provenance (and their purposes) that the WP-03 domain
    did not declare; KLP-WP-04 declared the first two (`wp04` keeps provenance).
    """
    from tests.schema import knowledge_schema_ahead_contract as contract

    wp03 = contract.GAP_ROWS["wp03"]
    assert {
        "knowledge.assertions.submit",
        "knowledge.discovery.checkpoint",
        "record_events.provenance",
    } <= wp03["capability"]
    assert {"knowledge_assertion_observation", "record_event_provenance_read"} <= wp03["purpose"]
    assert contract.GAP_ROWS["wp04"]["capability"] == frozenset({"record_events.provenance"})


def test_provenance_is_not_declared_before_wp05() -> None:
    """At the KLP-WP-04 head provenance was admitted ahead of the domain; WP-05 declares it.

    The node id is kept from KLP-WP-04 (KLP-AC-080). Its claim is about the WP-04
    head, which the `wp04` gap row records (provenance and its purpose only);
    at the WP-05 head both are declared and the `wp05` capability and purpose
    rows are empty.
    """
    from tests.schema import knowledge_schema_ahead_contract as contract

    assert contract.GAP_ROWS["wp04"]["capability"] == frozenset({"record_events.provenance"})
    assert contract.GAP_ROWS["wp04"]["purpose"] == frozenset({"record_event_provenance_read"})
    assert contract.GAP_ROWS["wp05"]["capability"] == frozenset()
    assert contract.GAP_ROWS["wp05"]["purpose"] == frozenset()
    values = {capability.value for capability in Capability}
    assert "record_events.provenance" in values
    purposes = {purpose.value for purpose in Purpose}
    assert "record_event_provenance_read" in purposes


# ---- KLP-AC-083 -----------------------------------------------------------------


def test_the_switch_defaults_off_and_requires_relationship_intelligence() -> None:
    url = "postgresql+psycopg://synthetic@localhost:5432/synthetic"
    assert Settings(database_url=url).knowledge_assertions_enabled is False
    with pytest.raises((SettingsError, ValueError), match="KNOWLEDGE_ASSERTIONS_ENABLED"):
        Settings(database_url=url, knowledge_assertions_enabled=True)
    composed = Settings(
        database_url=url,
        knowledge_assertions_enabled=True,
        relationship_intelligence_enabled=True,
    )
    assert composed.knowledge_assertions_enabled is True


def test_off_withholds_the_six_from_the_service_and_the_manifest(scene: Scene) -> None:
    off = build_service(scene.world, scene.providers)
    assert not KNOWLEDGE & off.available_capabilities
    response = off.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    )
    assert response.result is not None
    published = {
        item["name"]
        for item in response.result["manifest"]["capabilities"]
        if item["availability"] == "available"
    }
    assert not {capability.value for capability in KNOWLEDGE} & published
    on = build_service(scene.world, scene.providers, knowledge_assertions_enabled=True)
    assert on.available_capabilities >= KNOWLEDGE


def test_on_without_relationship_intelligence_still_withholds(scene: Scene) -> None:
    service = build_service(
        scene.world,
        scene.providers,
        relationship_intelligence_enabled=False,
        knowledge_assertions_enabled=True,
    )
    assert not KNOWLEDGE & service.available_capabilities


@pytest.mark.parametrize("capability", sorted(KNOWLEDGE), ids=lambda c: c.value)
def test_off_refuses_every_handler_as_unsupported(scene: Scene, capability: Capability) -> None:
    """The HTTP transport routes straight into `_HANDLERS`; the floor still holds."""
    service = build_service(scene.world, scene.providers)
    command = _commands(scene.principal.principal_id)[capability]
    response = service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    assert response.error is not None
    assert response.error.code.value == "unsupported"


def test_the_chatllm_profile_does_not_demand_grants_with_the_plane_off() -> None:
    implemented = frozenset(Capability)
    planes = ChatLLMCompositionPlanes(
        managed_documents=True,
        relationship_intelligence=True,
        relationship_intelligence_writes=True,
        relationship_memory=True,
        constraints=True,
    )
    off = desired_effective_capabilities(composed_capabilities(implemented, planes))
    assert not KNOWLEDGE & off
    on = desired_effective_capabilities(
        composed_capabilities(implemented, replace(planes, knowledge_assertions=True))
    )
    assert on >= KNOWLEDGE
    no_entity_plane = composed_capabilities(
        implemented,
        replace(planes, knowledge_assertions=True, relationship_intelligence=False),
    )
    assert not KNOWLEDGE & no_entity_plane


# ---- KLP-AC-104 -----------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(KNOWLEDGE), ids=lambda c: c.value)
def test_every_name_is_scopeless_and_requests_no_scope(
    scene: Scene, capability: Capability
) -> None:
    assert capability in _SCOPELESS
    command = _commands(scene.principal.principal_id)[capability]
    with FakeUnitOfWork(scene.world) as unit_of_work:
        requested = _requested_scope(
            unit_of_work,
            command,  # type: ignore[arg-type]
            (),
            principal_id=scene.principal.principal_id,
        )
    assert requested == frozenset()


@pytest.mark.parametrize("capability", sorted(KNOWLEDGE_READS), ids=lambda c: c.value)
def test_a_granted_read_invoke_succeeds_end_to_end(scene: Scene, capability: Capability) -> None:
    repository = _CannedKnowledge()
    service = _composed(scene.world, repository)
    response = service.invoke(
        metadata_for(capability, Purpose.KNOWLEDGE_ASSERTION_READ, scene.principal),
        _commands(scene.principal.principal_id)[capability],  # type: ignore[arg-type]
        principal=scene.principal,
        capability_grants=frozenset({(capability, Purpose.KNOWLEDGE_ASSERTION_READ)}),
    )
    assert response.error is None, response.error
    assert repository.calls


def test_a_granted_create_reaches_the_plane_and_refuses_an_unregistered_predicate(
    scene: Scene,
) -> None:
    repository = _CannedKnowledge()
    service = _composed(scene.world, repository)
    capability = Capability.KNOWLEDGE_ASSERTIONS_CREATE
    response = service.invoke(
        metadata_for(capability, Purpose.KNOWLEDGE_ASSERTION_AUTHORING, scene.principal),
        _commands(scene.principal.principal_id)[capability],  # type: ignore[arg-type]
        principal=scene.principal,
        capability_grants=frozenset({(capability, Purpose.KNOWLEDGE_ASSERTION_AUTHORING)}),
    )
    assert repository.calls == ["predicate_head"]
    assert response.error is not None
    assert response.error.code.value == "invalid_request"


def test_a_read_grant_does_not_reach_the_plane_through_another_capability(scene: Scene) -> None:
    repository = _CannedKnowledge()
    service = _composed(scene.world, repository)
    response = service.invoke(
        metadata_for(
            Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ, scene.principal
        ),
        ReadKnowledgeAssertion(assertion_id="kasr_fastworld00000001"),
        principal=scene.principal,
        capability_grants=frozenset(
            {(Capability.KNOWLEDGE_ASSERTIONS_LIST, Purpose.KNOWLEDGE_ASSERTION_READ)}
        ),
    )
    assert response.error is not None
    assert response.error.code.value == "unsupported"
    assert repository.calls == []


# ---- KLP-AC-105 -----------------------------------------------------------------


def test_an_explicit_name_set_maps_exactly_the_six_to_the_knowledge_prerequisite() -> None:
    """KLP-WP-05: the six data names plus `record_events.provenance` (AC-105 set)."""
    assert KNOWLEDGE | {PROVENANCE} == KNOWLEDGE_ASSERTION_DATA_NAMES
    mapped = {
        capability
        for capability, policy in CHATLLM_CAPABILITY_POLICY.items()
        if policy.composition_prerequisite is ChatLLMCompositionPrerequisite.KNOWLEDGE_ASSERTIONS
    }
    assert mapped == KNOWLEDGE | {PROVENANCE}
    prefixed = {
        capability for capability in Capability if capability.value.startswith("knowledge.")
    }
    # KLP-WP-04: the discovery pair shares the prefix and is CONTROL_PLANE_EXCLUDED
    # (prerequisite NONE); the service withholds it with the switch off instead.
    assert prefixed - mapped == set(EXTRACTION) | DISCOVERY


def test_composed_capabilities_raises_on_an_unknown_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = CHATLLM_CAPABILITY_POLICY[Capability.KNOWLEDGE_ASSERTIONS_READ]
    rogue = replace(policy, composition_prerequisite="ROGUE_PLANE")  # type: ignore[arg-type]
    monkeypatch.setattr(
        chatllm_data_profile,
        "CHATLLM_CAPABILITY_POLICY",
        {**CHATLLM_CAPABILITY_POLICY, Capability.KNOWLEDGE_ASSERTIONS_READ: rogue},
    )
    planes = ChatLLMCompositionPlanes(
        managed_documents=True,
        relationship_intelligence=True,
        relationship_intelligence_writes=True,
        relationship_memory=True,
        constraints=True,
        knowledge_assertions=True,
    )
    with pytest.raises(RuntimeError, match="unknown ChatLLM composition prerequisite"):
        composed_capabilities(frozenset(Capability), planes)


# ---- KLP-WP-04: the discovery pair -------------------------------------------------

_BOUND: Final = "synthetic-discovery-client"


def _discovery_commands(principal_id: str) -> dict[Capability, object]:
    return {
        Capability.KNOWLEDGE_ASSERTIONS_SUBMIT: SubmitKnowledgeAssertion(
            source_profile_id="kdsp_fastworld00000001",
            external_run_id="run-1",
            external_candidate_id="candidate-1",
            subject_kind=KnowledgeSubjectKind.PRINCIPAL,
            subject_id=principal_id,
            predicate_code="policy.requirement",
            value="Synthetic observed value",
            evidence=(
                {
                    "identity_kind": "external_object",
                    "external_object_id": "object-1",
                    "content_hash": "a" * 64,
                    "role": "direct",
                },
            ),
        ),
        Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT: CheckpointKnowledgeDiscovery(
            source_profile_id="kdsp_fastworld00000001",
            expected_version=0,
            external_run_id="run-1",
            submitted_candidate_count=1,
            checkpoint_kind=KnowledgeCheckpointKind.SYNTHETIC,
            private_envelope="opaque",
            idempotency_key="klp04-fast-checkpoint",
        ),
    }


#: A synthetic 32-octet checkpoint signing key (never a real key).
_SIGNING_KEY: Final = b"klp04-synthetic-checkpoint-key-0"


def _discovery_service(
    world: World,
    *,
    bound: frozenset[str],
    signing_key: bytes | None = _SIGNING_KEY,
    repository: _CannedKnowledge | None = None,
) -> ApplicationService:
    canned = _CannedKnowledge(seeded=True) if repository is None else repository
    return ApplicationService(
        unit_of_work=lambda: _KnowledgeUnitOfWork(world, canned),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=True,
        knowledge_discovery_client_ids=bound,
        knowledge_checkpoint_signing_key=signing_key,
    )


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_each_discovery_name_maps_to_the_observation_purpose_only(capability: Capability) -> None:
    assert permitted_purposes(capability) == {Purpose.KNOWLEDGE_ASSERTION_OBSERVATION}


def test_the_observation_purpose_is_used_only_by_the_discovery_pair() -> None:
    assert Purpose.KNOWLEDGE_ASSERTION_OBSERVATION.value == "knowledge_assertion_observation"
    users = {
        capability
        for capability in Capability
        if Purpose.KNOWLEDGE_ASSERTION_OBSERVATION in permitted_purposes(capability)
    }
    assert users == DISCOVERY


def test_every_knowledge_assertion_name_is_exhaustively_mapped_to_one_purpose() -> None:
    """KLP-AC-015 over the matrix's capability rows that exist in this build."""
    import json
    from pathlib import Path

    matrix = json.loads(
        (
            Path(__file__).parents[1] / "architecture" / "klp_implementation_matrix_r6.json"
        ).read_text(encoding="utf-8")
    )
    declared = {capability.value for capability in Capability}
    rows = [row for row in matrix["capabilities"] if row["name"] in declared]
    # KLP-WP-05: every matrix row exists now -- the nine, provenance included.
    assert {row["name"] for row in rows} == {c.value for c in KNOWLEDGE | DISCOVERY | {PROVENANCE}}
    assert len(rows) == len(matrix["capabilities"])
    for row in rows:
        assert permitted_purposes(Capability(row["name"])) == {Purpose(row["purpose"])}


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_the_discovery_pair_is_scopeless_and_requests_no_scope(
    scene: Scene, capability: Capability
) -> None:
    assert capability in _SCOPELESS
    command = _discovery_commands(scene.principal.principal_id)[capability]
    with FakeUnitOfWork(scene.world) as unit_of_work:
        requested = _requested_scope(
            unit_of_work,
            command,  # type: ignore[arg-type]
            (),
            principal_id=scene.principal.principal_id,
        )
    assert requested == frozenset()


def test_the_switch_withholds_the_discovery_pair(scene: Scene) -> None:
    off = build_service(scene.world, scene.providers)
    assert not DISCOVERY & off.available_capabilities
    on = build_service(scene.world, scene.providers, knowledge_assertions_enabled=True)
    assert on.available_capabilities >= DISCOVERY
    assert not DISCOVERY & published_capabilities(on, authenticated_client_present=False)
    assert published_capabilities(on, authenticated_client_present=True) >= DISCOVERY


def _invoke_discovery(
    service: ApplicationService,
    scene: Scene,
    capability: Capability,
    *,
    transport: CaptureTransport,
    client: str | None,
) -> str | None:
    response = service.invoke(
        metadata_for(capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION, scene.principal),
        _discovery_commands(scene.principal.principal_id)[capability],  # type: ignore[arg-type]
        principal=scene.principal,
        transport=transport,
        capability_grants=frozenset({(capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION)}),
        authenticated_client_id=client,
    )
    return None if response.error is None else response.error.code.value


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_a_granted_invoke_is_allowed_by_policy_and_reaches_the_service_gate(
    scene: Scene, capability: Capability
) -> None:
    service = _discovery_service(scene.world, bound=frozenset({_BOUND}))
    before = len(scene.world.audit)
    code = _invoke_discovery(
        service, scene, capability, transport=CaptureTransport.REMOTE_CLIENT, client=_BOUND
    )
    decisions = scene.world.audit[before:]
    assert [event.capability for event in decisions] == [capability]
    assert decisions[0].outcome.value == "allowed"
    # KLP-AC-104: a granted submit (slice B2) and checkpoint (slice B3) succeed
    # end to end.
    assert code is None


def test_a_granted_checkpoint_returns_the_advanced_receipt_end_to_end(scene: Scene) -> None:
    """KLP-AC-104 (checkpoint, slice B3): binding read, replay lookup, then the advance."""
    repository = _CannedKnowledge(seeded=True)
    service = _discovery_service(scene.world, bound=frozenset({_BOUND}), repository=repository)
    capability = Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT
    response = service.invoke(
        metadata_for(capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION, scene.principal),
        _discovery_commands(scene.principal.principal_id)[capability],  # type: ignore[arg-type]
        principal=scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT,
        capability_grants=frozenset({(capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION)}),
        authenticated_client_id=_BOUND,
    )
    assert response.error is None
    assert response.result is not None
    assert dict(response.result) == {
        "checkpoint_request_id": "kdcpr_fastworld000001",
        "outcome": "advanced",
        "reason": "advanced",
        "checkpoint_id": "kdcp_fastworld000001",
        "checkpoint_version": 1,
        "checkpoint_kind": "synthetic",
        "private_envelope": "opaque",
        "private_token_redacted": False,
    }
    assert repository.calls == ["source_binding", "replay_checkpoint", "checkpoint"]


def test_a_build_without_a_signing_key_refuses_every_checkpoint(scene: Scene) -> None:
    """R6 section 7: no key, no checkpoint -- refused before any read."""
    repository = _CannedKnowledge(seeded=True)
    service = _discovery_service(
        scene.world, bound=frozenset({_BOUND}), signing_key=None, repository=repository
    )
    code = _invoke_discovery(
        service,
        scene,
        Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
        transport=CaptureTransport.REMOTE_CLIENT,
        client=_BOUND,
    )
    assert code == "unsupported"
    assert repository.calls == []


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
@pytest.mark.parametrize(
    ("transport", "client", "bound"),
    [
        (CaptureTransport.LOCAL, None, frozenset({_BOUND})),
        (CaptureTransport.LOCAL, _BOUND, frozenset({_BOUND})),
        (CaptureTransport.REMOTE_CLIENT, None, frozenset({_BOUND})),
        (CaptureTransport.REMOTE_CLIENT, "synthetic-chatllm", frozenset({_BOUND})),
        (CaptureTransport.REMOTE_CLIENT, _BOUND, frozenset()),
        (CaptureTransport.REMOTE_CLIENT, f"{_BOUND}-x", frozenset({_BOUND})),
    ],
    ids=[
        "local",
        "local-with-client",
        "remote-capture-route",
        "unbound-client",
        "empty-allowlist",
        "prefix",
    ],
)
def test_the_second_gate_refuses_every_unbound_composition(
    scene: Scene,
    capability: Capability,
    transport: CaptureTransport,
    client: str | None,
    bound: frozenset[str],
) -> None:
    service = _discovery_service(scene.world, bound=bound)
    authorization = _gate_authorization(scene, capability, transport=transport, client=client)
    with pytest.raises(UnsupportedError):
        service._knowledge_discovery_gate(authorization, capability)
    code = _invoke_discovery(service, scene, capability, transport=transport, client=client)
    assert code == "unsupported"


@pytest.mark.parametrize("capability", sorted(DISCOVERY), ids=lambda c: c.value)
def test_the_second_gate_admits_a_bound_remote_client(scene: Scene, capability: Capability) -> None:
    """The control: the gate itself passes for a bound remote client."""
    service = _discovery_service(scene.world, bound=frozenset({_BOUND}))
    authorization = _gate_authorization(
        scene, capability, transport=CaptureTransport.REMOTE_CLIENT, client=_BOUND
    )
    service._knowledge_discovery_gate(authorization, capability)


def _gate_authorization(
    scene: Scene, capability: Capability, *, transport: CaptureTransport, client: str | None
) -> Authorization:
    return Authorization(
        principal=scene.principal,
        capability=capability,
        purpose=Purpose.KNOWLEDGE_ASSERTION_OBSERVATION,
        correlation_id="corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        request_id="req-klp04-gate",
        audit_id="aud_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        at=WHEN,
        decision=PolicyDecision(allowed=True, policy_version=POLICY_VERSION),
        requested_source_ids=frozenset(),
        enrollments=(),
        transport=transport,
        capability_grants=frozenset({(capability, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION)}),
        authenticated_client_id=client,
    )


# ---- KLP-WP-05: `record_events.provenance`, the last KLP name -----------------------

#: The capability count before the Knowledge layer (README/matrix pin: 181).
_PRE_KLP_CAPABILITIES: Final = 181
_EVENT: Final = "rcev_fastworld000000001"


def test_the_nine_new_capabilities_are_exactly_the_matrix_nine() -> None:
    """KLP-AC-002: exactly the matrix's KLP names, no other new member, no `propose`."""
    nine = {row["name"] for row in MATRIX["capabilities"]}
    assert len(nine) == 9
    assert nine == {capability.value for capability in KNOWLEDGE | DISCOVERY | {PROVENANCE}}
    assert nine <= {capability.value for capability in Capability}
    assert len(Capability) == _PRE_KLP_CAPABILITIES + 9
    assert "knowledge.assertions.propose" not in {capability.value for capability in Capability}
    assert not any(
        capability.value.endswith(".propose") and "knowledge" in capability.value
        for capability in Capability
    )


def test_provenance_maps_to_its_own_purpose_only() -> None:
    """KLP-AC-015: exactly `record_event_provenance_read`, used by nothing else."""
    assert Purpose.RECORD_EVENT_PROVENANCE_READ.value == "record_event_provenance_read"
    assert permitted_purposes(PROVENANCE) == {Purpose.RECORD_EVENT_PROVENANCE_READ}
    users = {
        capability
        for capability in Capability
        if Purpose.RECORD_EVENT_PROVENANCE_READ in permitted_purposes(capability)
    }
    assert users == {PROVENANCE}
    assert Purpose.RECORD_EVENT_READ not in permitted_purposes(PROVENANCE)


def test_all_nine_map_to_exactly_their_matrix_purpose() -> None:
    """KLP-AC-015 (closed): exhaustive over the nine, each to one matrix Purpose."""
    for row in MATRIX["capabilities"]:
        assert permitted_purposes(Capability(row["name"])) == {Purpose(row["purpose"])}, row
    matrix_purposes = {row["name"] for row in MATRIX["purposes"]}
    assert matrix_purposes <= {purpose.value for purpose in Purpose}


def test_provenance_is_scopeless_and_requests_no_scope(scene: Scene) -> None:
    """KLP-AC-104: `_SCOPELESS` and the scopeless arm of `_requested_scope`."""
    assert PROVENANCE in _SCOPELESS
    with FakeUnitOfWork(scene.world) as unit_of_work:
        requested = _requested_scope(
            unit_of_work,
            GetRecordEventProvenance(event_id=_EVENT),
            (),
            principal_id=scene.principal.principal_id,
        )
    assert requested == frozenset()


def _canned_provenance(principal_id: str) -> object:
    from my_pa.contracts.ports import (
        RecordEventProvenance,
        RecordEventProvenanceSubmission,
    )
    from my_pa.domain.record_events import RecordEventActorClass, RecordEventFamily

    del principal_id
    return RecordEventProvenance(
        event_id=_EVENT,
        record_family=RecordEventFamily.KNOWLEDGE_ASSERTION,
        record_id="kasr_fastworld00000001",
        source_receipt_id="kamut_fastworld0000001",
        mutation_kind="create",
        actor_class=RecordEventActorClass.ASSISTANT,
        submission=RecordEventProvenanceSubmission(
            submission_id="kasub_fastworld0000001",
            origin="autonomous_submit",
            authenticated_client_id=_BOUND,
            external_run_id="run-1",
            external_candidate_id="candidate-1",
            causal_depth=0,
            causal_root_submission_id="kasub_fastworld0000001",
            root_authenticated_client_id=_BOUND,
        ),
        trigger_event_ids=(),
        review=None,
    )


class _ProvenanceReader:
    """The FAST feed reader plus a canned `provenance` answer (the SQL is DB-tested)."""

    def __init__(self, world: World, calls: list[dict[str, object]]) -> None:
        from tests.conftest import FakeRecordEventReader

        self._inner = FakeRecordEventReader(world.record_events)
        self._calls = calls

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def event_provenance(self, **arguments: object) -> object:
        """As the SQL reader: no visible Knowledge family answers `None` with no statement."""
        self._calls.append(arguments)
        if not arguments["event_families"]:
            return None
        return _canned_provenance(str(arguments["principal_id"]))


class _ProvenanceUnitOfWork(_KnowledgeUnitOfWork):
    def __init__(
        self, world: World, repository: _CannedKnowledge, calls: list[dict[str, object]]
    ) -> None:
        super().__init__(world, repository)
        self._calls = calls

    @property
    def record_event_reader(self) -> Any:  # noqa: ANN401 - a duck-typed reader
        return _ProvenanceReader(self._world, self._calls)


def _provenance_service(
    world: World, calls: list[dict[str, object]], *, enabled: bool = True
) -> ApplicationService:
    repository = _CannedKnowledge()
    return ApplicationService(
        unit_of_work=lambda: _ProvenanceUnitOfWork(world, repository, calls),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=enabled,
    )


_PROVENANCE_GRANTS: Final = frozenset(
    {
        (PROVENANCE, Purpose.RECORD_EVENT_PROVENANCE_READ),
        (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)


def _invoke_provenance(
    service: ApplicationService,
    scene: Scene,
    *,
    grants: frozenset[tuple[Capability, Purpose | None]] | None = _PROVENANCE_GRANTS,
    client: str | None = _BOUND,
) -> Any:  # noqa: ANN401 - a response envelope
    return service.invoke(
        metadata_for(PROVENANCE, Purpose.RECORD_EVENT_PROVENANCE_READ, scene.principal),
        GetRecordEventProvenance(event_id=_EVENT),
        principal=scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT if client is not None else CaptureTransport.LOCAL,
        capability_grants=grants,
        authenticated_client_id=client,
    )


def test_a_granted_provenance_invoke_succeeds_end_to_end(scene: Scene) -> None:
    """KLP-AC-104 (closed): allowed by policy, through the feed reader, to the view."""
    calls: list[dict[str, object]] = []
    service = _provenance_service(scene.world, calls)
    before = len(scene.world.audit)
    response = _invoke_provenance(service, scene)
    assert response.error is None, response.error
    decisions = scene.world.audit[before:]
    assert [event.capability for event in decisions] == [PROVENANCE]
    assert decisions[0].outcome.value == "allowed"
    provenance = dict(response.result)["provenance"]
    assert provenance["submission"]["external_run_id"] == "run-1"
    assert provenance["submission"]["self_caused"] is True
    (call,) = calls
    assert call["event_id"] == _EVENT
    assert call["principal_id"] == scene.principal.principal_id
    assert call["include_restricted_memory"] is False
    assert call["event_families"] == {RecordEventFamily.KNOWLEDGE_ASSERTION}


def test_another_client_gets_the_same_shape_without_external_ids(scene: Scene) -> None:
    calls: list[dict[str, object]] = []
    service = _provenance_service(scene.world, calls)
    response = _invoke_provenance(service, scene, client="synthetic-other-client")
    submission = dict(response.result)["provenance"]["submission"]
    assert submission["external_run_id"] is None
    assert submission["external_candidate_id"] is None
    assert submission["self_caused"] is False


def test_a_local_caller_reads_with_restricted_disclosure_and_external_ids(scene: Scene) -> None:
    calls: list[dict[str, object]] = []
    service = _provenance_service(scene.world, calls)
    response = _invoke_provenance(service, scene, grants=None, client=None)
    submission = dict(response.result)["provenance"]["submission"]
    assert submission["external_run_id"] == "run-1"
    assert calls[0]["include_restricted_memory"] is True


def test_a_grant_ceiling_without_the_provenance_grant_is_unsupported(scene: Scene) -> None:
    calls: list[dict[str, object]] = []
    service = _provenance_service(scene.world, calls)
    response = _invoke_provenance(
        service,
        scene,
        grants=frozenset(
            {(Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ)}
        ),
    )
    assert response.error is not None
    assert response.error.code.value == "unsupported"
    assert calls == []


def test_no_visible_knowledge_family_answers_not_found_before_the_reader(scene: Scene) -> None:
    """Without a granted Knowledge read the family is invisible: not_found, no statement."""
    calls: list[dict[str, object]] = []
    service = _provenance_service(scene.world, calls)
    response = _invoke_provenance(
        service, scene, grants=frozenset({(PROVENANCE, Purpose.RECORD_EVENT_PROVENANCE_READ)})
    )
    assert response.error is not None
    assert response.error.code.value == "not_found"
    assert calls == []


def test_the_plane_switch_withholds_and_refuses_provenance(scene: Scene) -> None:
    calls: list[dict[str, object]] = []
    off = _provenance_service(scene.world, calls, enabled=False)
    assert PROVENANCE not in off.available_capabilities
    response = _invoke_provenance(off, scene, grants=None, client=None)
    assert response.error is not None
    assert response.error.code.value == "unsupported"
    assert calls == []
    on = _provenance_service(scene.world, calls)
    assert PROVENANCE in on.available_capabilities
