"""ChatLLM capability policy is exhaustive and fail-closed."""

from my_pa.application.service import _HANDLERS
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_write_capability,
    permitted_purposes,
)

_RUN01 = frozenset(
    {
        Capability.CONSTRAINTS_PORTFOLIO_LIST,
        Capability.CONSTRAINTS_PORTFOLIO_SEARCH,
        Capability.CONSTRAINTS_PORTFOLIO_OVERVIEW,
        Capability.CONSTRAINTS_CREATE_PUBLISHED,
        Capability.PROJECT_CONTROLS_CONFIGURE,
        Capability.PROJECT_CONTROLS_STATUS,
    }
)
#: PC-CM-RUN01-WP05, extended by PC-CM-RUN01-WP06 and completed by
#: PC-CM-RUN01-WP07. All six now have handlers. Kept as its own set rather than
#: collapsed into `_RUN01`, because the set's other claim — that all six are
#: `DATA_CONDITIONAL` — is unchanged and is what `_RUN01` is for, and because a
#: future package declaring a name ahead of wiring it needs the distinction back.
_RUN01_WIRED = frozenset(
    {
        Capability.PROJECT_CONTROLS_CONFIGURE,
        Capability.PROJECT_CONTROLS_STATUS,
        Capability.CONSTRAINTS_PORTFOLIO_LIST,
        Capability.CONSTRAINTS_PORTFOLIO_SEARCH,
        Capability.CONSTRAINTS_PORTFOLIO_OVERVIEW,
        Capability.CONSTRAINTS_CREATE_PUBLISHED,
    }
)
_ODR = frozenset(
    {
        Capability.GSQS_START,
        Capability.GSQS_STATUS,
    }
)
_REPORT_WRITES = frozenset(
    {
        Capability.REPORTS_BEGIN_CYCLE,
        Capability.REPORTS_COMMIT,
        Capability.REPORTS_RECORD_RUN_STATE,
    }
)


def test_policy_covers_every_public_capability_exactly_once() -> None:
    assert set(CHATLLM_CAPABILITY_POLICY) == set(Capability)
    assert len(CHATLLM_CAPABILITY_POLICY) == 172
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v2"


def test_classification_counts_match_the_approved_plan() -> None:
    counts = dict.fromkeys(ChatLLMCapabilityClass, 0)
    for policy in CHATLLM_CAPABILITY_POLICY.values():
        counts[policy.classification] += 1
    assert counts[ChatLLMCapabilityClass.DATA_REQUIRED] == 63
    assert counts[ChatLLMCapabilityClass.DATA_CONDITIONAL] == 90
    assert counts[ChatLLMCapabilityClass.COMPATIBILITY_ONLY] == 2
    assert counts[ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED] == 15
    assert counts[ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED] == 2
    assert counts[ChatLLMCapabilityClass.RETIRED] == 0


def test_control_plane_and_odr_are_never_data_management() -> None:
    for capability, policy in CHATLLM_CAPABILITY_POLICY.items():
        if policy.classification in {
            ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED,
            ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED,
            ChatLLMCapabilityClass.COMPATIBILITY_ONLY,
            ChatLLMCapabilityClass.RETIRED,
        }:
            assert not is_chatllm_data_management(capability)
            assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
            assert policy.exclusion_rationale


def test_run01_names_are_conditional_and_every_wired_one_is_implemented() -> None:
    """All six stay `DATA_CONDITIONAL`; all six now have handlers.

    PC-CM-RUN01-WP05 supplied `project_controls.configure` and
    `project_controls.status`, WP06 the three cross-Project reads, and WP07
    `constraints.create_published`. No classification changed and none was
    changed here — each was already `DATA_CONDITIONAL` when the name landed, and
    what a classification says is what a name *is*, not whether this build has
    got round to serving it. Both halves are still asserted, so a future package
    that declares a name ahead of wiring it is measured the same way.
    """
    assert set(Capability) - set(_HANDLERS) == _RUN01 - _RUN01_WIRED
    for capability in _RUN01:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
    assert all(capability not in _HANDLERS for capability in _RUN01 - _RUN01_WIRED)
    assert all(capability in _HANDLERS for capability in _RUN01_WIRED)


def test_odr_holdout_is_explicit() -> None:
    for capability in _ODR:
        assert (
            CHATLLM_CAPABILITY_POLICY[capability].classification
            is ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED
        )


def test_report_authoring_writes_are_data_required() -> None:
    for capability in _REPORT_WRITES:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
        assert is_chatllm_data_management(capability)
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.ALWAYS
        assert policy.exclusion_rationale is None


def test_continuity_tasks_create_names_the_work_plane_replacement() -> None:
    policy = CHATLLM_CAPABILITY_POLICY[Capability.CONTINUITY_TASKS_CREATE]
    assert policy.classification is ChatLLMCapabilityClass.COMPATIBILITY_ONLY
    assert policy.compatibility_replacement is Capability.TASKS_CREATE


def test_policy_agrees_with_canonical_purpose_and_write_maps() -> None:
    for capability in Capability:
        CHATLLM_CAPABILITY_POLICY[capability]
        assert permitted_purposes(capability)
        if is_write_capability(capability):
            assert capability in _HANDLERS or capability in _RUN01
        is_destructive_capability(capability)


def test_project_controls_configure_is_application_data_not_system_admin() -> None:
    configure = CHATLLM_CAPABILITY_POLICY[Capability.PROJECT_CONTROLS_CONFIGURE]
    status = CHATLLM_CAPABILITY_POLICY[Capability.PROJECT_CONTROLS_STATUS]
    assert configure.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
    assert status.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
    assert configure.family == "project_controls"
    assert is_write_capability(Capability.PROJECT_CONTROLS_CONFIGURE)
    assert not is_write_capability(Capability.PROJECT_CONTROLS_STATUS)
