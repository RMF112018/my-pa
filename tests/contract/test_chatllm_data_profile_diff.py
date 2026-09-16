"""Desired ChatLLM profile diffs distinguish grant gaps from unimplemented names."""

from datetime import UTC, datetime
from uuid import UUID

from apps.cli.remote_mcp import main

from my_pa.adapters.remote_request import resolve_remote_purpose
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
)
from my_pa.application.service import _HANDLERS
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_DATA_PROFILE_VERSION,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.purpose import Purpose

NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)
EXPIRED_AT = datetime(2026, 9, 13, 19, 48, 5, tzinfo=UTC)
RESOURCE = "https://my-pa.example/mcp"
SCOPE = "my-pa.read"
IMPLEMENTED = frozenset(_HANDLERS)

_FULL_PLANES = ChatLLMCompositionPlanes(
    managed_documents=True,
    relationship_intelligence=True,
    relationship_intelligence_writes=True,
    relationship_memory=True,
    constraints=True,
)
_DEFAULT_PLANES = ChatLLMCompositionPlanes(
    managed_documents=False,
    relationship_intelligence=False,
    relationship_intelligence_writes=False,
    relationship_memory=False,
    constraints=True,
)

_SEPTEMBER13_ACTIVE = frozenset(
    {
        Capability.COMMITMENTS_CLOSE,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_LIST,
        Capability.COMMITMENTS_READ,
        Capability.COMMITMENTS_WAITING_ON,
        Capability.CONTINUITY_PROJECTS_CLOSE,
        Capability.CONTINUITY_PROJECTS_READ,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_LIST,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_LIST,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_OBSERVATIONS_LIST,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        Capability.ENTITIES_UPDATE,
        Capability.GOODNOTES_CONTENT,
        Capability.GOODNOTES_PROPOSE,
        Capability.GOODNOTES_WORK,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.TASKS_BULK_CONFIRM,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_CREATE,
        Capability.TASKS_HISTORY,
        Capability.TASKS_LIST,
        Capability.TASKS_READ,
        Capability.TASKS_SEARCH,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_UPDATE,
    }
)

_SEPTEMBER13_EXPIRED = frozenset(
    {
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_REVISE,
        Capability.CAPTURE_SEARCH,
        Capability.CONTEXT_FEEDBACK,
        Capability.CONTEXT_PREPARE,
        Capability.CONTINUITY_PROJECTS,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_PULSE,
        Capability.CONTINUITY_SITUATIONS,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_LIST,
        Capability.DOCUMENTS_READ,
        Capability.DOCUMENTS_RESTORE,
        Capability.DOCUMENTS_REVISE,
        Capability.KNOWLEDGE_COVERAGE,
        Capability.KNOWLEDGE_READ,
        Capability.KNOWLEDGE_REVEAL,
        Capability.KNOWLEDGE_SEARCH,
        Capability.REVIEW_DECIDE,
        Capability.REVIEW_LIST,
        Capability.SOURCES_FETCH,
        Capability.SOURCES_LIST,
        Capability.SOURCES_METADATA,
        Capability.SOURCES_STATUS,
    }
)


def _grant(
    capability: Capability,
    *,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    purpose: Purpose | None = None,
    is_write: bool | None = None,
) -> ChatLLMGrantRecord:
    from my_pa.application.chatllm_data_profile import chatllm_grant_purpose

    return ChatLLMGrantRecord(
        capability=capability,
        purpose=chatllm_grant_purpose(capability) if purpose is None else purpose,
        is_write=is_write_capability(capability) if is_write is None else is_write,
        resource=RESOURCE,
        scope=SCOPE,
        expires_at=expires_at,
        revoked_at=revoked_at,
        grant_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )


def _september13_grants() -> tuple[ChatLLMGrantRecord, ...]:
    active = tuple(_grant(capability) for capability in _SEPTEMBER13_ACTIVE)
    expired = tuple(
        _grant(capability, expires_at=EXPIRED_AT) for capability in _SEPTEMBER13_EXPIRED
    )
    return active + expired


def test_chatllm_grant_purpose_matches_the_remote_canonical_stamp() -> None:
    for capability in Capability:
        if not is_chatllm_data_management(capability):
            continue
        assert chatllm_grant_purpose(capability) == resolve_remote_purpose(capability, None)


def test_full_plane_effective_target_is_one_hundred_forty_nine() -> None:
    """144 until PC-CM-RUN01-WP05 supplied the two Project Controls handlers.

    The target is derived — `implemented` intersected with what the policy
    already classifies as data management — so wiring a name the policy had
    already classified moves it without anything here being reclassified. The
    two Project Controls names and the three Report-authoring names landed on
    disjoint paths; the figure below was re-measured on the merged tree rather
    than summed from the two branches' deltas.
    """
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    assert len(desired) == 149
    assert Capability.PROJECT_CONTROLS_CONFIGURE in desired
    assert Capability.PROJECT_CONTROLS_STATUS in desired
    assert Capability.REPORTS_BEGIN_CYCLE in desired
    assert Capability.REPORTS_COMMIT in desired
    assert Capability.REPORTS_RECORD_RUN_STATE in desired
    assert all(capability in IMPLEMENTED for capability in desired)
    assert all(is_chatllm_data_management(capability) for capability in desired)


def test_default_plane_effective_target_is_eighty_three() -> None:
    composed = composed_capabilities(IMPLEMENTED, _DEFAULT_PLANES)
    desired = desired_effective_capabilities(composed)
    assert len(desired) == 83
    assert Capability.DOCUMENTS_READ not in desired
    assert Capability.ENTITIES_SEARCH not in desired
    assert Capability.CONSTRAINTS_LIST in desired


def test_unimplemented_run01_names_are_not_grant_failures() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=(),
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert Capability.CONSTRAINTS_PORTFOLIO_LIST in diff.policy_required_not_implemented
    assert (
        diff.outcomes[Capability.CONSTRAINTS_PORTFOLIO_LIST]
        is ChatLLMProfileOutcome.POLICY_REQUIRED_NOT_IMPLEMENTED
    )
    assert Capability.CONSTRAINTS_PORTFOLIO_LIST not in diff.add
    # PC-CM-RUN01-WP05. The two Project Controls names are no longer among the
    # unimplemented, so they are ordinary grants to add rather than policy-
    # required-not-implemented. Asserted both ways round so this row cannot
    # quietly become vacuous.
    assert Capability.PROJECT_CONTROLS_CONFIGURE in diff.add
    assert Capability.PROJECT_CONTROLS_STATUS in diff.add
    assert Capability.PROJECT_CONTROLS_CONFIGURE not in diff.policy_required_not_implemented


def test_september13_partial_regrant_fails_attestation() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=_september13_grants(),
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert not diff.is_healthy()
    assert (
        diff.outcomes[Capability.CONTINUITY_PROJECTS_READ]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANTED
    )
    assert (
        diff.outcomes[Capability.CONTINUITY_PROJECTS_UPDATE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANTED
    )
    assert (
        diff.outcomes[Capability.CONTINUITY_PROJECTS_CLOSE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANTED
    )
    assert (
        diff.outcomes[Capability.CONTINUITY_PROJECTS]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
    )
    assert (
        diff.outcomes[Capability.CONTINUITY_PROJECTS_CREATE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
    )
    assert (
        diff.outcomes[Capability.CAPTURE_CREATE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
    )
    assert (
        diff.outcomes[Capability.CONTEXT_PREPARE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
    )
    assert (
        diff.outcomes[Capability.CONTINUITY_SITUATIONS_CREATE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
    )
    assert (
        diff.outcomes[Capability.DOCUMENTS_READ]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
    )
    assert diff.outcomes[Capability.CONTINUITY_TASKS_CREATE] is ChatLLMProfileOutcome.EXCLUDED
    assert (
        diff.outcomes[Capability.REPORTS_BEGIN_CYCLE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
    )
    assert (
        diff.outcomes[Capability.REPORTS_COMMIT]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
    )
    assert (
        diff.outcomes[Capability.REPORTS_RECORD_RUN_STATE]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
    )


def test_documents_not_composed_is_excluded_not_a_grant_gap() -> None:
    composed = composed_capabilities(IMPLEMENTED, _DEFAULT_PLANES)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=(),
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert diff.outcomes[Capability.DOCUMENTS_READ] is ChatLLMProfileOutcome.EXCLUDED
    assert Capability.DOCUMENTS_READ not in diff.add


def test_unexpected_control_plane_grant_fails() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=(_grant(Capability.SOURCES_ENROLL),),
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert not diff.is_healthy()
    assert Capability.SOURCES_ENROLL in diff.unexpected_control_plane
    actions = plan_chatllm_grant_actions(
        diff, (_grant(Capability.SOURCES_ENROLL),), now=NOW, resource=RESOURCE, scope=SCOPE
    )
    assert all(action.capability is not Capability.SOURCES_ENROLL for action in actions)
    assert all(
        action.kind != "add" or is_chatllm_data_management(action.capability) for action in actions
    )


def test_converged_profile_is_a_noop() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    grants = tuple(_grant(capability) for capability in desired)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert diff.is_healthy()
    actions = plan_chatllm_grant_actions(diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE)
    assert {action.kind for action in actions} == {"noop"}


def test_expired_required_grant_is_renewed_without_expiry() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    grants = tuple(
        _grant(
            capability,
            expires_at=EXPIRED_AT if capability is Capability.CONTEXT_PREPARE else None,
        )
        for capability in desired
    )
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert not diff.is_healthy()
    assert Capability.CONTEXT_PREPARE in diff.renew
    actions = plan_chatllm_grant_actions(diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE)
    renew = [action for action in actions if action.kind == "renew"]
    assert [action.capability for action in renew] == [Capability.CONTEXT_PREPARE]


def test_profile_commands_are_named_in_help() -> None:
    import pytest

    for command in ("profile-diff", "profile-plan", "profile-apply"):
        with pytest.raises(SystemExit) as raised:
            main([command, "--help"])
        assert raised.value.code == 0


def test_no_path_grants_every_capability_enum_member() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    assert desired != set(Capability)
    assert Capability.SOURCES_ENROLL not in desired
    assert Capability.GSQS_START not in desired
    assert Capability.CONTINUITY_TASKS_CREATE not in desired
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v2"


def test_mismatched_purpose_or_write_is_add_not_noop() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    grants = tuple(
        _grant(capability, purpose=Purpose.STATUS_OBSERVATION)
        if capability is Capability.TASKS_LIST
        else _grant(capability, is_write=True)
        if capability is Capability.TASKS_READ
        else _grant(capability)
        for capability in desired
    )
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    for capability in (Capability.TASKS_LIST, Capability.TASKS_READ):
        assert (
            diff.outcomes[capability] is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISMATCHED
        )
    actions = plan_chatllm_grant_actions(diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE)
    mismatched = [
        action.kind
        for action in actions
        if action.capability in {Capability.TASKS_LIST, Capability.TASKS_READ}
    ]
    assert mismatched == ["add", "add"]


def test_revoked_desired_grant_is_added() -> None:
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    grants = tuple(
        _grant(capability, revoked_at=EXPIRED_AT)
        if capability is Capability.TASKS_LIST
        else _grant(capability)
        for capability in desired
    )
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert (
        diff.outcomes[Capability.TASKS_LIST]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_REVOKED
    )
    assert Capability.TASKS_LIST in diff.add
    actions = plan_chatllm_grant_actions(diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE)
    revoked = [action for action in actions if action.capability is Capability.TASKS_LIST]
    assert [action.kind for action in revoked] == ["add"]


def test_active_finite_expiry_matching_desired_is_renewed_not_noop() -> None:
    """Finite-expiry grants matching purpose/write must be renewed, not noop."""
    from datetime import timedelta

    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    future_expiry = NOW + timedelta(days=30)
    grants = tuple(
        _grant(capability, expires_at=future_expiry)
        if capability is Capability.TASKS_LIST
        else _grant(capability)
        for capability in desired
    )
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert not diff.is_healthy()
    assert (
        diff.outcomes[Capability.TASKS_LIST]
        is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY
    )
    assert Capability.TASKS_LIST in diff.renew
    assert Capability.TASKS_LIST not in diff.add
    actions = plan_chatllm_grant_actions(diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE)
    finite_actions = [action for action in actions if action.capability is Capability.TASKS_LIST]
    assert len(finite_actions) == 1
    assert finite_actions[0].kind == "renew"


def test_plan_actions_sorted_by_capability_value_stable_with_finite_renews() -> None:
    """Plan actions are deterministically ordered by capability.value, including renewals."""
    from datetime import timedelta

    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    future_expiry = NOW + timedelta(days=30)
    grants = tuple(
        _grant(capability, expires_at=future_expiry)
        if capability
        in {
            Capability.TASKS_LIST,
            Capability.ENTITIES_SEARCH,
            Capability.CAPTURE_CREATE,
        }
        else _grant(capability)
        if capability
        in {
            Capability.TASKS_READ,
            Capability.ENTITIES_GET,
            Capability.CONTINUITY_PROJECTS_READ,
        }
        else None
        for capability in desired
    )
    grants_present = tuple(g for g in grants if g is not None)
    actions = plan_chatllm_grant_actions(
        diff_chatllm_data_profile(
            implemented=IMPLEMENTED,
            composed=composed,
            grants=grants_present,
            now=NOW,
            resource=RESOURCE,
            scope=SCOPE,
        ),
        grants_present,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert actions == tuple(sorted(actions, key=lambda a: a.capability.value))
    action_kinds = {action.capability: action.kind for action in actions}
    assert action_kinds[Capability.TASKS_LIST] == "renew"
    assert action_kinds[Capability.ENTITIES_SEARCH] == "renew"
    assert action_kinds[Capability.CAPTURE_CREATE] == "renew"
    assert action_kinds[Capability.TASKS_READ] == "noop"
    assert action_kinds[Capability.ENTITIES_GET] == "noop"
    assert action_kinds[Capability.CONTINUITY_PROJECTS_READ] == "noop"
    missing_cap = next(
        cap for cap in desired if cap not in {action.capability for action in actions}
    )
    missing_actions = [action for action in actions if action.capability == missing_cap]
    if missing_actions:
        assert missing_actions[0].kind == "add"


def test_after_finite_renew_and_adds_plan_is_all_noop() -> None:
    """After applying renew/add to clear expires_at, second plan has only noop actions."""
    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    durable_grants = tuple(_grant(capability) for capability in desired)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=durable_grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert diff.is_healthy()
    assert len(diff.renew) == 0
    assert len(diff.add) == 0
    actions = plan_chatllm_grant_actions(
        diff, durable_grants, now=NOW, resource=RESOURCE, scope=SCOPE
    )
    assert {action.kind for action in actions} == {"noop"}


def test_no_revoke_when_normalizing_finite_expiry() -> None:
    """Finite-expiry active grants never produce revoke actions."""
    from datetime import timedelta

    composed = composed_capabilities(IMPLEMENTED, _FULL_PLANES)
    desired = desired_effective_capabilities(composed)
    future_expiry = NOW + timedelta(days=30)
    grants = tuple(_grant(capability, expires_at=future_expiry) for capability in desired)
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=grants,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert not diff.is_healthy()
    assert all(
        outcome is ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY
        for capability, outcome in diff.outcomes.items()
        if capability in desired
    )
    actions = plan_chatllm_grant_actions(diff, grants, now=NOW, resource=RESOURCE, scope=SCOPE)
    action_kinds = {action.kind for action in actions}
    assert "revoke" not in action_kinds
    assert action_kinds == {"renew"}
