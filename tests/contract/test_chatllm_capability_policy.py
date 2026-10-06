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
from my_pa.domain.identity.purpose import Purpose

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
#: Meeting Records WP-MTG-05. All six are `DATA_REQUIRED` on the core plane
#: (no feature flag), which is why the profile identity moved to
#: `chatllm-data-v3`: the new catalog must not be applied under v2.
_MEETING_READS = frozenset(
    {
        Capability.MEETINGS_READ,
        Capability.MEETINGS_LIST,
        Capability.MEETINGS_SEARCH,
    }
)
_MEETING_WRITES = frozenset(
    {
        Capability.MEETINGS_CREATE,
        Capability.MEETINGS_UPDATE,
        Capability.MEETINGS_SERIES_UPDATE,
    }
)
_MEETINGS = _MEETING_READS | _MEETING_WRITES


def test_policy_covers_every_public_capability_exactly_once() -> None:
    assert set(CHATLLM_CAPABILITY_POLICY) == set(Capability)
    assert len(CHATLLM_CAPABILITY_POLICY) == 189
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v7"


def test_classification_counts_match_the_approved_plan() -> None:
    counts = dict.fromkeys(ChatLLMCapabilityClass, 0)
    for policy in CHATLLM_CAPABILITY_POLICY.values():
        counts[policy.classification] += 1
    assert counts[ChatLLMCapabilityClass.DATA_REQUIRED] == 72
    # KLP-WP-03 (chatllm-data-v6): the six Knowledge Assertion names, 90 -> 96.
    assert counts[ChatLLMCapabilityClass.DATA_CONDITIONAL] == 96
    assert counts[ChatLLMCapabilityClass.COMPATIBILITY_ONLY] == 2
    # KLP-WP-04 (chatllm-data-v7): submit and checkpoint are excluded, 15 -> 17.
    assert counts[ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED] == 17
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


def test_the_six_meeting_capabilities_are_data_required_on_the_core_plane() -> None:
    assert len(_MEETINGS) == 6
    named = {capability for capability in Capability if capability.value.startswith("meetings.")}
    assert named == _MEETINGS
    for capability in _MEETINGS:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
        assert is_chatllm_data_management(capability)
        assert policy.family == "meetings"
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.ALWAYS
        assert policy.compatibility_replacement is None
        assert policy.exclusion_rationale is None
        assert capability in _HANDLERS
    for capability in _MEETING_READS:
        assert permitted_purposes(capability) == frozenset({Purpose.MEETING_READ})
        assert not is_write_capability(capability)
    for capability in _MEETING_WRITES:
        assert permitted_purposes(capability) == frozenset({Purpose.MEETING_AUTHORING})
        assert is_write_capability(capability)


def test_record_events_list_is_data_required_on_the_core_plane() -> None:
    """WP-RE-06, OD-11 (i): the change feed is always composed and metadata only.

    Its introduction is why the profile identity moved to `chatllm-data-v4`: a
    client must not converge on the new catalog under v3.
    """
    named = {
        capability for capability in Capability if capability.value.startswith("record_events.")
    }
    assert named == {Capability.RECORD_EVENTS_LIST}
    policy = CHATLLM_CAPABILITY_POLICY[Capability.RECORD_EVENTS_LIST]
    assert policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
    assert is_chatllm_data_management(Capability.RECORD_EVENTS_LIST)
    assert policy.family == "record_events"
    assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.ALWAYS
    assert policy.compatibility_replacement is None
    assert policy.exclusion_rationale is None
    assert Capability.RECORD_EVENTS_LIST in _HANDLERS
    assert permitted_purposes(Capability.RECORD_EVENTS_LIST) == frozenset(
        {Purpose.RECORD_EVENT_READ}
    )
    assert not is_write_capability(Capability.RECORD_EVENTS_LIST)


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


# ---- KLP-WP-03 (KLP-AC-105) ---------------------------------------------------

_KNOWLEDGE = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
    }
)


def test_the_knowledge_names_are_conditional_on_their_own_plane_by_explicit_name() -> None:
    """An explicit name set, never a `knowledge.` prefix (KLP-AC-001, KLP-AC-105)."""
    for capability in _KNOWLEDGE:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is (
            ChatLLMCompositionPrerequisite.KNOWLEDGE_ASSERTIONS
        )
    for capability in (
        Capability.KNOWLEDGE_SEARCH,
        Capability.KNOWLEDGE_READ,
        Capability.KNOWLEDGE_REVEAL,
        Capability.KNOWLEDGE_COVERAGE,
    ):
        assert CHATLLM_CAPABILITY_POLICY[capability].composition_prerequisite is (
            ChatLLMCompositionPrerequisite.ALWAYS
        )
    # KLP-WP-04 (chatllm-data-v7): the discovery pair is declared and excluded
    # from the ordinary profile, so its ChatLLM prerequisite is `NONE`.
    for capability in (
        Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
        Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
    ):
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
        assert policy.exclusion_rationale
