"""KLP-WP-03: the Knowledge Assertion catalog, plane switch and scope (FAST).

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
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

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

from my_pa.application import chatllm_data_profile
from my_pa.application.authorization import _requested_scope
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.commands import (
    CreateKnowledgeAssertion,
    GetCapabilities,
    GetKnowledgeAssertionHistory,
    ListKnowledgeAssertions,
    ReadKnowledgeAssertion,
    RevealKnowledgeAssertion,
    RevealSubject,
    SearchKnowledgeAssertions,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import Settings, SettingsError
from my_pa.contracts.ports import (
    KnowledgeAssertionHistory,
    KnowledgeAssertionPage,
    KnowledgeAssertionRepository,
    KnowledgeAssertionReveal,
    KnowledgeAssertionRow,
    KnowledgeCreateRequest,
    KnowledgeSubmissionResult,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    KNOWLEDGE_ASSERTION_DATA_NAMES,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.source.registry import issue_identifier

KNOWLEDGE_READS: Final = (
    Capability.KNOWLEDGE_ASSERTIONS_READ,
    Capability.KNOWLEDGE_ASSERTIONS_LIST,
    Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
    Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
    Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
)
KNOWLEDGE: Final = frozenset({*KNOWLEDGE_READS, Capability.KNOWLEDGE_ASSERTIONS_CREATE})
EXTRACTION: Final = {
    Capability.KNOWLEDGE_SEARCH: "knowledge.search",
    Capability.KNOWLEDGE_READ: "knowledge.read",
    Capability.KNOWLEDGE_REVEAL: "knowledge.reveal",
    Capability.KNOWLEDGE_COVERAGE: "knowledge.coverage",
}
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

    def __init__(self) -> None:
        self.calls: list[str] = []

    def predicate_head(self, predicate_code: str) -> object:
        self.calls.append("predicate_head")
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
    ) -> KnowledgeSubmissionResult:
        raise AssertionError("an unregistered predicate never reaches create")


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
    values = {capability.value for capability in Capability}
    assert "knowledge.assertions.submit" not in values
    assert "knowledge.discovery.checkpoint" not in values
    assert "record_events.provenance" not in values
    purposes = {purpose.value for purpose in Purpose}
    assert "knowledge_assertion_observation" not in purposes
    assert "record_event_provenance_read" not in purposes


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
    assert KNOWLEDGE_ASSERTION_DATA_NAMES == KNOWLEDGE
    mapped = {
        capability
        for capability, policy in CHATLLM_CAPABILITY_POLICY.items()
        if policy.composition_prerequisite is ChatLLMCompositionPrerequisite.KNOWLEDGE_ASSERTIONS
    }
    assert mapped == KNOWLEDGE
    prefixed = {
        capability for capability in Capability if capability.value.startswith("knowledge.")
    }
    assert prefixed - mapped == set(EXTRACTION)


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
