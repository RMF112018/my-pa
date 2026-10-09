"""KLP Step 8 (spec item 8): the ChatLLM grant tooling is Knowledge-Manager aware.

`knowledge.assertions.submit` and `knowledge.discovery.checkpoint` stay
`CONTROL_PLANE_EXCLUDED` in `CHATLLM_CAPABILITY_POLICY`, so every ordinary
ChatLLM client is unchanged: an active grant for either is still an
`UNEXPECTED_CONTROL_PLANE_GRANT` and neither is ever desired or planned. A
client bound as Knowledge Manager is an exact-client exception applied by the
profile tooling (`knowledge_manager=True`): with the Knowledge plane composed
the pair is desired, an active durable grant is `IMPLEMENTED_COMPOSED_GRANTED`,
a missing one is planned as an `add` under `knowledge_assertion_observation`
(write). Every other control-plane name stays unexpected for a manager too, and
omitting the flag fails closed to the ordinary profile.

Every identity here is synthetic.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.application.chatllm_data_profile import (
    KNOWLEDGE_MANAGER_GRANT_EXCEPTIONS,
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    ChatLLMProfileDiff,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
    profile_diff_as_json,
)
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.knowledge_discovery_profiles import KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
)
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.purpose import Purpose

NOW: Final = datetime(2026, 10, 9, 12, tzinfo=UTC)
RESOURCE: Final = "https://my-pa.example/mcp"
SCOPE: Final = "my-pa.read"
IMPLEMENTED: Final = frozenset(_HANDLERS)
PAIR: Final = frozenset(
    {Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT}
)
_KNOWLEDGE_ON: Final = ChatLLMCompositionPlanes(
    managed_documents=True,
    relationship_intelligence=True,
    relationship_intelligence_writes=True,
    relationship_memory=True,
    constraints=True,
    knowledge_assertions=True,
)
_KNOWLEDGE_OFF: Final = replace(_KNOWLEDGE_ON, knowledge_assertions=False)
#: Every other control-plane-excluded name: never a manager exception.
OTHER_CONTROL_PLANE: Final = (
    frozenset(
        capability
        for capability, policy in CHATLLM_CAPABILITY_POLICY.items()
        if policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
    )
    - PAIR
)


def _grant(capability: Capability) -> ChatLLMGrantRecord:
    return ChatLLMGrantRecord(
        capability=capability,
        purpose=chatllm_grant_purpose(capability),
        is_write=is_write_capability(capability),
        resource=RESOURCE,
        scope=SCOPE,
        expires_at=None,
        revoked_at=None,
    )


def _converged(planes: ChatLLMCompositionPlanes) -> tuple[ChatLLMGrantRecord, ...]:
    """Durable grants for every ordinary desired name under `planes`."""
    desired = desired_effective_capabilities(composed_capabilities(IMPLEMENTED, planes))
    return tuple(_grant(capability) for capability in sorted(desired, key=lambda c: c.value))


def _diff(
    grants: tuple[ChatLLMGrantRecord, ...],
    *,
    planes: ChatLLMCompositionPlanes = _KNOWLEDGE_ON,
    knowledge_manager: bool,
) -> ChatLLMProfileDiff:
    return diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed_capabilities(IMPLEMENTED, planes),
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
        knowledge_manager=knowledge_manager,
    )


def test_the_manager_exception_set_is_exactly_the_discovery_pair() -> None:
    """The application restatement equals the bootstrap overlay's pair, and both stay excluded."""
    assert KNOWLEDGE_MANAGER_GRANT_EXCEPTIONS == KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES == PAIR
    for capability in PAIR:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        assert chatllm_grant_purpose(capability) is Purpose.KNOWLEDGE_ASSERTION_OBSERVATION
        assert is_write_capability(capability)
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v8"


def test_ordinary_active_submit_and_checkpoint_grants_stay_unexpected() -> None:
    grants = _converged(_KNOWLEDGE_ON) + tuple(_grant(capability) for capability in PAIR)
    diff = _diff(grants, knowledge_manager=False)
    assert not PAIR & diff.desired_effective
    assert diff.unexpected_control_plane == PAIR
    for capability in PAIR:
        assert diff.outcomes[capability] is ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
    assert diff.is_healthy() is False
    assert not PAIR & diff.add
    assert profile_diff_as_json(diff)["knowledge_role"] == "ordinary"


def test_the_flag_defaults_to_the_ordinary_profile() -> None:
    """Omitting `knowledge_manager` fails closed: identical to passing False."""
    grants = _converged(_KNOWLEDGE_ON) + tuple(_grant(capability) for capability in PAIR)
    composed = composed_capabilities(IMPLEMENTED, _KNOWLEDGE_ON)
    omitted = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert omitted == _diff(grants, knowledge_manager=False)
    assert not PAIR & desired_effective_capabilities(composed)


def test_manager_active_durable_grants_are_composed_granted_and_healthy() -> None:
    grants = _converged(_KNOWLEDGE_ON) + tuple(_grant(capability) for capability in PAIR)
    diff = _diff(grants, knowledge_manager=True)
    assert diff.desired_effective >= PAIR
    for capability in PAIR:
        assert diff.outcomes[capability] is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANTED
    assert diff.unexpected_control_plane == frozenset()
    assert diff.add == diff.renew == frozenset()
    assert diff.is_healthy() is True
    rendered = profile_diff_as_json(diff)
    assert rendered["knowledge_role"] == "manager"
    assert rendered["healthy"] is True
    ordinary = _diff(grants, knowledge_manager=False)
    assert diff.desired_effective - ordinary.desired_effective == PAIR


def test_manager_missing_grants_are_reported_as_add() -> None:
    diff = _diff(_converged(_KNOWLEDGE_ON), knowledge_manager=True)
    assert diff.add == PAIR
    for capability in PAIR:
        assert diff.outcomes[capability] is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
    assert diff.is_healthy() is False


@pytest.mark.parametrize("capability", sorted(OTHER_CONTROL_PLANE, key=lambda c: c.value), ids=str)
def test_every_other_control_plane_name_stays_unexpected_for_a_manager(
    capability: Capability,
) -> None:
    grants = _converged(_KNOWLEDGE_ON) + tuple(_grant(member) for member in PAIR | {capability})
    diff = _diff(grants, knowledge_manager=True)
    assert diff.outcomes[capability] is ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
    assert diff.unexpected_control_plane == {capability}
    assert capability not in diff.desired_effective
    assert diff.is_healthy() is False


def test_the_other_control_plane_names_are_the_known_set() -> None:
    """The parametrisation above covers the names the Orchestrator listed, among others."""
    assert {
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT,
        Capability.GOODNOTES_PULL,
        Capability.SOURCES_ENROLL,
        Capability.CONSTRAINT_SYNC_APPLY,
    } <= OTHER_CONTROL_PLANE
    assert not PAIR & OTHER_CONTROL_PLANE


def test_non_data_names_outside_the_pair_are_identical_for_manager_and_ordinary() -> None:
    """capabilities.get, GSQS and the other non-data names: the manager flag changes nothing."""
    every = tuple(_grant(capability) for capability in IMPLEMENTED - PAIR)
    manager = _diff(every, knowledge_manager=True)
    ordinary = _diff(every, knowledge_manager=False)
    for capability in CHATLLM_CAPABILITY_POLICY:
        if capability in PAIR:
            continue
        assert manager.outcomes[capability] is ordinary.outcomes[capability], capability
    assert manager.outcomes[Capability.CAPABILITIES_GET] is ChatLLMProfileOutcome.EXCLUDED
    assert manager.outcomes[Capability.GSQS_START] is ChatLLMProfileOutcome.EXCLUDED


@pytest.mark.parametrize(
    "planes",
    [
        _KNOWLEDGE_OFF,
        # The Knowledge plane needs Relationship Intelligence; alone it composes nothing.
        replace(_KNOWLEDGE_ON, relationship_intelligence=False),
    ],
    ids=["knowledge-off", "knowledge-without-entities"],
)
def test_with_the_knowledge_plane_off_the_manager_does_not_desire_the_pair(
    planes: ChatLLMCompositionPlanes,
) -> None:
    composed = composed_capabilities(IMPLEMENTED, planes)
    assert not PAIR & composed
    assert not PAIR & desired_effective_capabilities(composed, knowledge_manager=True)
    diff = _diff(_converged(planes), planes=planes, knowledge_manager=True)
    assert not PAIR & diff.desired_effective
    assert not PAIR & diff.add
    assert diff.is_healthy() is True
    actions = plan_chatllm_grant_actions(
        diff, _converged(planes), now=NOW, resource=RESOURCE, scope=SCOPE, knowledge_manager=True
    )
    assert not PAIR & {action.capability for action in actions}


def test_ordinary_desired_sets_are_unchanged_across_every_composition() -> None:
    """The manager gate never moves an ordinary desired count; manager adds exactly the pair."""
    for bits in range(64):
        planes = ChatLLMCompositionPlanes(
            managed_documents=bool(bits & 1),
            relationship_intelligence=bool(bits & 2),
            relationship_intelligence_writes=bool(bits & 4),
            relationship_memory=bool(bits & 8),
            constraints=bool(bits & 16),
            knowledge_assertions=bool(bits & 32),
        )
        composed = composed_capabilities(frozenset(Capability), planes)
        ordinary = desired_effective_capabilities(composed)
        assert all(
            CHATLLM_CAPABILITY_POLICY[capability].classification
            in {ChatLLMCapabilityClass.DATA_REQUIRED, ChatLLMCapabilityClass.DATA_CONDITIONAL}
            for capability in ordinary
        ), planes
        manager = desired_effective_capabilities(composed, knowledge_manager=True)
        knowledge = planes.knowledge_assertions and planes.relationship_intelligence
        assert manager - ordinary == (PAIR if knowledge else frozenset()), planes
        assert ordinary <= manager, planes


def test_the_manager_plan_adds_exactly_the_pair_as_observation_writes() -> None:
    grants = _converged(_KNOWLEDGE_ON)
    diff = _diff(grants, knowledge_manager=True)
    actions = plan_chatllm_grant_actions(
        diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE, knowledge_manager=True
    )
    added = [action for action in actions if action.kind != "noop"]
    assert {action.capability for action in added} == PAIR
    for action in added:
        assert action.kind == "add"
        assert action.purpose is Purpose.KNOWLEDGE_ASSERTION_OBSERVATION
        assert action.is_write is True
        assert action.grant_id is None


def test_the_manager_plan_is_noop_once_the_pair_is_granted() -> None:
    grants = _converged(_KNOWLEDGE_ON) + tuple(_grant(capability) for capability in PAIR)
    diff = _diff(grants, knowledge_manager=True)
    actions = plan_chatllm_grant_actions(
        diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE, knowledge_manager=True
    )
    assert all(action.kind == "noop" for action in actions)
    assert {action.capability for action in actions} >= PAIR


def test_the_ordinary_plan_never_includes_the_pair() -> None:
    grants = _converged(_KNOWLEDGE_ON)
    ordinary = _diff(grants, knowledge_manager=False)
    for actions in (
        plan_chatllm_grant_actions(ordinary, grants, now=NOW, resource=RESOURCE, scope=SCOPE),
        # A manager diff planned without the flag still fails closed to ordinary.
        plan_chatllm_grant_actions(
            _diff(grants, knowledge_manager=True),
            grants,
            now=NOW,
            resource=RESOURCE,
            scope=SCOPE,
        ),
    ):
        assert not PAIR & {action.capability for action in actions}
