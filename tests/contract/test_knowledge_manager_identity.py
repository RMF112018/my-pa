"""The Knowledge Manager client identity at the service boundary (KLP Step 8).

FAST, synthetic client ids only. A Knowledge Manager is an ordinary broad ChatLLM
client that the server -- never the request -- additionally binds to Knowledge
control-plane authority through `MY_PA_KNOWLEDGE_MANAGER_OAUTH_CLIENT_IDS`:

* **Overlay.** `remote_access_context` hands a manager its full broad grant set,
  submit and checkpoint included only when granted; an ordinary ChatLLM client
  with the same grants still loses submit and checkpoint.
* **Second service gate.** `_knowledge_discovery_gate` admits the remote
  transport plus a client in discovery OR manager; a manager submit and a
  manager checkpoint succeed end to end over the canned plane. Ordinary ChatLLM,
  operator-review, local and client-less remote compositions are still refused
  `unsupported` before any read. A manager without the grant never reaches the
  plane.
* **Identity from OAuth only.** The gate and the Review derivation read
  `authenticated_client_id` from the authorization; a remote payload naming a
  manager's client id is refused and never reaches the plane.
* **Review authority.** A manager's Knowledge `review.decide` is
  `remote_operator_attested` / `remote_operator_review` -- the existing persisted
  class, no new vocabulary -- and may accept a `requires_operator` case; an
  ordinary remote client is still `ordinary_reviewer` / `remote_interactive` and
  denied on that case; the operator-review client is unchanged.
"""

from __future__ import annotations

import json
from dataclasses import fields
from types import SimpleNamespace
from typing import Any, Final

import pytest
from apps.gateway import remote_access_context
from tests.conftest import DEFAULT_LIMITS, WHEN, Scene, World, metadata_for
from tests.contract.test_knowledge_assertion_capabilities import (
    _SIGNING_KEY,
    _CannedKnowledge,
    _discovery_commands,
    _gate_authorization,
    _KnowledgeUnitOfWork,
)
from tests.contract.test_knowledge_review_operator_authority import (
    OPERATOR_CASE,
    REVIEW_CASE,
    _authority,
    _code,
    _decide,
    _ReviewPlane,
    _UnitOfWork,
)

from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.adapters.mcp.server import _answer
from my_pa.application.commands import CheckpointKnowledgeDiscovery, SubmitKnowledgeAssertion
from my_pa.application.errors import UnsupportedError
from my_pa.application.service import ApplicationService
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeDecisionChannel,
    KnowledgeReviewAuthorityClass,
)
from my_pa.domain.policy.knowledge_review_authority import derive_knowledge_review_authority

MANAGER: Final = "synthetic-knowledge-manager-client"
DISCOVERY_CLIENT: Final = "synthetic-discovery-client"
REVIEW_CLIENT: Final = "synthetic-operator-review-client"
CHAT_CLIENT: Final = "synthetic-chatllm-client"
SUBMIT: Final = Capability.KNOWLEDGE_ASSERTIONS_SUBMIT
CHECKPOINT: Final = Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT
PAIR: Final = (SUBMIT, CHECKPOINT)
OBSERVATION: Final = Purpose.KNOWLEDGE_ASSERTION_OBSERVATION
REMOTE: Final = CaptureTransport.REMOTE_CLIENT
LOCAL: Final = CaptureTransport.LOCAL


def _gate_service(
    world: World, repository: _CannedKnowledge, *, manager: frozenset[str] = frozenset({MANAGER})
) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: _KnowledgeUnitOfWork(world, repository),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=True,
        knowledge_discovery_client_ids=frozenset({DISCOVERY_CLIENT}),
        knowledge_operator_review_client_ids=frozenset({REVIEW_CLIENT}),
        knowledge_manager_client_ids=manager,
        knowledge_checkpoint_signing_key=_SIGNING_KEY,
    )


def _invoke(
    service: ApplicationService,
    scene: Scene,
    capability: Capability,
    *,
    transport: CaptureTransport = REMOTE,
    client: str | None = MANAGER,
    grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
) -> str | None:
    response = service.invoke(
        metadata_for(capability, OBSERVATION, scene.principal),
        _discovery_commands(scene.principal.principal_id)[capability],  # type: ignore[arg-type]
        principal=scene.principal,
        transport=transport,
        capability_grants=frozenset({(capability, OBSERVATION)}) if grants is None else grants,
        authenticated_client_id=client,
    )
    return None if response.error is None else response.error.code.value


# ---- the overlay as the gateway applies it ------------------------------------------


def _pairs(capabilities: frozenset[Capability]) -> frozenset[tuple[Capability, Purpose | None]]:
    pairs: set[tuple[Capability, Purpose | None]] = set()
    for capability in capabilities:
        pairs.add((capability, None))
        pairs.update((capability, purpose) for purpose in permitted_purposes(capability))
    return frozenset(pairs)


#: A broad synthetic ChatLLM grant set, plus the two control-plane grants.
_BROAD: Final = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        Capability.RECORD_EVENTS_LIST,
        Capability.RECORD_EVENTS_PROVENANCE,
        Capability.CONTEXT_PREPARE,
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        *(capability for capability in Capability if capability.value.startswith("entities.")),
    }
)
_SETTINGS: Final = SimpleNamespace(
    knowledge_discovery_oauth_client_id_set=lambda: frozenset({DISCOVERY_CLIENT}),
    knowledge_operator_review_oauth_client_id_set=lambda: frozenset({REVIEW_CLIENT}),
    chatllm_gateway_oauth_client_id_set=lambda: frozenset({CHAT_CLIENT, MANAGER}),
    knowledge_manager_oauth_client_id_set=lambda: frozenset({MANAGER}),
    compact_publication_for_client=lambda _client: False,
)


def _context(
    scene: Scene, service: ApplicationService, client: str, granted: frozenset[Capability]
) -> RemoteAccessContext:
    authenticated = SimpleNamespace(
        principal=scene.principal,
        client_id=client,
        capabilities=granted,
        capability_purposes=_pairs(granted),
        write_allowed=True,
    )
    return remote_access_context(_SETTINGS, service, authenticated)  # type: ignore[arg-type]


def test_the_gateway_hands_a_manager_its_full_grant_set_with_submit_and_checkpoint(
    scene: Scene,
) -> None:
    service = _gate_service(scene.world, _CannedKnowledge(seeded=True))
    granted = _BROAD | set(PAIR)
    context = _context(scene, service, MANAGER, granted)
    assert context.allowed_capabilities == frozenset(capability.value for capability in granted)
    assert context.capability_purposes == _pairs(granted)
    assert context.authenticated_client_id == MANAGER


def test_the_gateway_strips_submit_and_checkpoint_from_an_ordinary_chatllm_client(
    scene: Scene,
) -> None:
    service = _gate_service(scene.world, _CannedKnowledge(seeded=True))
    context = _context(scene, service, CHAT_CLIENT, _BROAD | set(PAIR))
    assert context.allowed_capabilities == frozenset(capability.value for capability in _BROAD)
    assert context.capability_purposes is not None
    assert not any(capability in PAIR for capability, _ in context.capability_purposes)


# ---- the second service gate ----------------------------------------------------------


@pytest.mark.parametrize("capability", PAIR, ids=str)
def test_the_gate_admits_a_remote_manager_client(scene: Scene, capability: Capability) -> None:
    service = _gate_service(scene.world, _CannedKnowledge(seeded=True))
    service._knowledge_discovery_gate(
        _gate_authorization(scene, capability, transport=REMOTE, client=MANAGER), capability
    )


@pytest.mark.parametrize("capability", PAIR, ids=str)
@pytest.mark.parametrize(
    ("transport", "client", "manager"),
    [
        (REMOTE, CHAT_CLIENT, frozenset({MANAGER})),
        (REMOTE, REVIEW_CLIENT, frozenset({MANAGER})),
        (LOCAL, MANAGER, frozenset({MANAGER})),
        (LOCAL, None, frozenset({MANAGER})),
        (REMOTE, None, frozenset({MANAGER})),
        (REMOTE, MANAGER, frozenset()),
        (REMOTE, f"{MANAGER}-x", frozenset({MANAGER})),
    ],
    ids=[
        "ordinary-chatllm",
        "operator-review",
        "local-with-manager",
        "local",
        "remote-capture-route",
        "empty-manager-allowlist",
        "prefix",
    ],
)
def test_the_gate_still_refuses_every_other_composition_before_any_read(
    scene: Scene,
    capability: Capability,
    transport: CaptureTransport,
    client: str | None,
    manager: frozenset[str],
) -> None:
    repository = _CannedKnowledge(seeded=True)
    service = _gate_service(scene.world, repository, manager=manager)
    with pytest.raises(UnsupportedError):
        service._knowledge_discovery_gate(
            _gate_authorization(scene, capability, transport=transport, client=client), capability
        )
    assert _invoke(service, scene, capability, transport=transport, client=client) == (
        "unsupported"
    )
    assert repository.calls == []


def test_a_manager_submits_a_synthetic_source_backed_assertion_end_to_end(scene: Scene) -> None:
    repository = _CannedKnowledge(seeded=True)
    service = _gate_service(scene.world, repository)
    assert _invoke(service, scene, SUBMIT) is None
    assert repository.calls[0] == "source_binding"
    assert repository.calls[-1] == "submit"


def test_a_manager_advances_a_checkpoint_end_to_end(scene: Scene) -> None:
    repository = _CannedKnowledge(seeded=True)
    service = _gate_service(scene.world, repository)
    assert _invoke(service, scene, CHECKPOINT) is None
    assert repository.calls == ["source_binding", "replay_checkpoint", "checkpoint"]


@pytest.mark.parametrize("capability", PAIR, ids=str)
def test_a_manager_without_the_grant_never_reaches_the_plane(
    scene: Scene, capability: Capability
) -> None:
    repository = _CannedKnowledge(seeded=True)
    service = _gate_service(scene.world, repository)
    other = CHECKPOINT if capability is SUBMIT else SUBMIT
    code = _invoke(service, scene, capability, grants=frozenset({(other, OBSERVATION)}))
    assert code is not None
    assert repository.calls == []


# ---- identity comes from OAuth, never the payload ---------------------------------------


@pytest.mark.parametrize("command", [SubmitKnowledgeAssertion, CheckpointKnowledgeDiscovery])
def test_no_command_carries_a_client_identity_field(command: type) -> None:
    names = {field.name for field in fields(command)}
    assert not {"authenticated_client_id", "client_id", "oauth_client_id"} & names


@pytest.mark.parametrize("smuggled", ["authenticated_client_id", "client_id"])
def test_a_payload_naming_a_manager_client_never_passes_the_gate(
    scene: Scene, smuggled: str
) -> None:
    """An ordinary ChatLLM client cannot claim manager identity in the request body."""
    repository = _CannedKnowledge(seeded=True)
    service = _gate_service(scene.world, repository)
    payload = {
        "source_profile_id": "kdsp_fastworld00000001",
        "external_run_id": "run-1",
        "external_candidate_id": "candidate-1",
        "subject_kind": "principal",
        "subject_id": scene.principal.principal_id,
        "predicate_code": "policy.requirement",
        "value": "Synthetic observed value",
        "evidence": [
            {
                "identity_kind": "external_object",
                "external_object_id": "object-1",
                "content_hash": "a" * 64,
                "role": "direct",
            }
        ],
    }
    grants = frozenset({(SUBMIT, OBSERVATION)})

    def call(client: str, body: dict[str, Any]) -> dict[str, Any]:
        text, failed, _image = _answer(
            service,
            scene.principal,
            SUBMIT.value,
            {"payload": body},
            transport=REMOTE,
            allowed_capability_purposes=grants,
            authenticated_client_id=client,
        )
        return {"failed": failed, **json.loads(text)}

    # Control: the same well-formed payload from the OAuth-bound manager passes.
    assert call(MANAGER, payload)["failed"] is False
    repository.calls.clear()
    smuggling = call(CHAT_CLIENT, {**payload, smuggled: MANAGER})
    assert smuggling["failed"] is True
    assert _code(smuggling) == "invalid_request"
    plain = call(CHAT_CLIENT, payload)
    assert plain["failed"] is True
    assert _code(plain) == "unsupported"
    assert repository.calls == []


# ---- Review authority ---------------------------------------------------------------------


def _review_service(world: World, plane: _ReviewPlane) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: _UnitOfWork(world, plane),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        knowledge_assertions_enabled=True,
        knowledge_discovery_client_ids=frozenset({DISCOVERY_CLIENT}),
        knowledge_operator_review_client_ids=frozenset({REVIEW_CLIENT}),
        knowledge_manager_client_ids=frozenset({MANAGER}),
    )


_REVIEW_GRANTS: Final = frozenset(
    {
        (Capability.REVIEW_DECIDE, None),
        (Capability.REVIEW_LIST, None),
        (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)


def _remote(client: str) -> dict[str, Any]:
    return {
        "transport": REMOTE,
        "capability_grants": _REVIEW_GRANTS,
        "authenticated_client_id": client,
    }


@pytest.mark.parametrize(
    "case", [OPERATOR_CASE, REVIEW_CASE], ids=["requires_operator", "ordinary"]
)
def test_a_manager_decides_knowledge_review_as_remote_operator_attested(
    scene: Scene, case: str
) -> None:
    plane = _ReviewPlane()
    accepted = _decide(
        _review_service(scene.world, plane), scene.principal, case, **_remote(MANAGER)
    )
    assert accepted.error is None, accepted.error
    assert _authority(plane) == ("remote_operator_attested", "remote_operator_review", MANAGER)


def test_the_operator_review_client_is_unchanged(scene: Scene) -> None:
    plane = _ReviewPlane()
    service = _review_service(scene.world, plane)
    accepted = _decide(service, scene.principal, OPERATOR_CASE, **_remote(REVIEW_CLIENT))
    assert accepted.error is None, accepted.error
    assert _authority(plane) == (
        "remote_operator_attested",
        "remote_operator_review",
        REVIEW_CLIENT,
    )


def test_an_ordinary_remote_client_still_cannot_promote_a_requires_operator_case(
    scene: Scene,
) -> None:
    plane = _ReviewPlane()
    service = _review_service(scene.world, plane)
    denied = _decide(service, scene.principal, OPERATOR_CASE, **_remote(CHAT_CLIENT))
    assert denied.error is not None and denied.error.code.value == "denied"
    assert plane.requests == []
    accepted = _decide(service, scene.principal, REVIEW_CASE, **_remote(CHAT_CLIENT))
    assert accepted.error is None, accepted.error
    assert _authority(plane) == ("ordinary_reviewer", "remote_interactive", CHAT_CLIENT)


def _derive(client: str | None, *, transport: CaptureTransport = REMOTE) -> tuple[Any, Any]:
    return derive_knowledge_review_authority(
        operator_surface=None,
        transport=transport,
        principal_is_operator=True,
        authenticated_client_id=client,
        operator_review_allowlist=frozenset({REVIEW_CLIENT}),
        manager_allowlist=frozenset({MANAGER}),
    )


def test_the_derivation_attests_a_remote_manager() -> None:
    attested = (
        KnowledgeReviewAuthorityClass.REMOTE_OPERATOR_ATTESTED,
        KnowledgeDecisionChannel.REMOTE_OPERATOR_REVIEW,
    )
    assert _derive(MANAGER) == attested
    assert _derive(REVIEW_CLIENT) == attested
    ordinary = (
        KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER,
        KnowledgeDecisionChannel.REMOTE_INTERACTIVE,
    )
    for client in (CHAT_CLIENT, DISCOVERY_CLIENT, f"{MANAGER}-x", MANAGER[:-1]):
        assert _derive(client) == ordinary
    # A manager client on the LOCAL transport is never attested.
    assert _derive(MANAGER, transport=LOCAL) == (
        KnowledgeReviewAuthorityClass.ORDINARY_REVIEWER,
        KnowledgeDecisionChannel.LOCAL_UNATTESTED,
    )
