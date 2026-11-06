"""Reports Modernization WP05b Part C layers 7-9: the custody names never reach a client (FAST).

The four operator custody capabilities (`reports.hold.place`,
`reports.hold.release`, `reports.retention.set`, `reports.retention.get`) are
operator-only and attested to the local operator surface (operator decision
2026-11-05, H1):

* `remote_tool_names` never publishes them, with the process write gate on or
  off and under every remote publication profile (layer 7);
* the ChatLLM capability policy classifies each `CONTROL_PLANE_EXCLUDED` with
  the custody rationale, and the planner desires none of them under any
  composition or the knowledge-manager role (layer 8);
* an active grant on any one of them is `UNEXPECTED_CONTROL_PLANE_GRANT` in
  the profile diff, which is then unhealthy (layer 9).

The facade half (describe, read, write, forged grants) is in
`tests/security/test_reports_custody_facade_adversarial.py`. Every value is
synthetic.
"""

from __future__ import annotations

import itertools
from dataclasses import fields
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final

import pytest

from my_pa.adapters.mcp.chatllm_gateway import facade_kind
from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
)
from my_pa.application.service import _HANDLERS
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose

CUSTODY: Final = (
    Capability.REPORTS_HOLD_PLACE,
    Capability.REPORTS_HOLD_RELEASE,
    Capability.REPORTS_RETENTION_SET,
    Capability.REPORTS_RETENTION_GET,
)
_RATIONALE: Final = (
    "operator-only report holds and retention; attested to the local operator surface "
    "(operator decision 2026-11-05)"
)
IMPLEMENTED: Final = frozenset(_HANDLERS)
ALL: Final = frozenset(Capability)
NOW: Final = datetime(2026, 11, 6, 12, tzinfo=UTC)
RESOURCE: Final = "https://my-pa.example/mcp"
SCOPE: Final = "my-pa.read"
_PROFILES: Final[dict[str, dict[str, Any]]] = {
    "default": {},
    "remote_operator": {"relationship_grant_profile": "remote.operator"},
    "compact_operator": {"compact_operator_publication": True},
}
_PLANE_FLAGS: Final = tuple(field.name for field in fields(ChatLLMCompositionPlanes))


def _every_composition() -> list[ChatLLMCompositionPlanes]:
    return [
        ChatLLMCompositionPlanes(**dict(zip(_PLANE_FLAGS, bits, strict=True)))
        for bits in itertools.product((False, True), repeat=len(_PLANE_FLAGS))
    ]


def _grant(capability: Capability) -> ChatLLMGrantRecord:
    if is_chatllm_data_management(capability):
        purpose = chatllm_grant_purpose(capability)
    else:
        (purpose,) = permitted_purposes(capability)
    return ChatLLMGrantRecord(
        capability=capability,
        purpose=purpose,
        is_write=is_write_capability(capability),
        resource=RESOURCE,
        scope=SCOPE,
        expires_at=None,
        revoked_at=None,
    )


def test_the_custody_names_are_implemented_operator_only_and_operator_kind() -> None:
    for capability in CUSTODY:
        assert capability in IMPLEMENTED, capability
        assert is_operator_only(capability), capability
        assert facade_kind(capability) == "operator", capability
    assert {permitted_purposes(capability) for capability in CUSTODY} == {
        frozenset({Purpose.REPORT_HOLD}),
        frozenset({Purpose.REPORT_RETENTION}),
    }


@pytest.mark.parametrize("profile", sorted(_PROFILES))
@pytest.mark.parametrize("writes_enabled", [True, False], ids=["writes_on", "writes_off"])
def test_remote_tool_names_never_publish_a_custody_name(profile: str, writes_enabled: bool) -> None:
    names = remote_tool_names(
        SimpleNamespace(available_capabilities=ALL),  # type: ignore[arg-type]
        writes_enabled=writes_enabled,
        **_PROFILES[profile],
    )
    assert not {capability.value for capability in CUSTODY} & names
    # Non-vacuous: the ordinary report read is published to the same profile.
    assert Capability.REPORTS_READ.value in names
    assert (Capability.REPORTS_DELETE.value in names) is writes_enabled


def test_the_chatllm_policy_excludes_every_custody_name_with_its_rationale() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v13"
    for capability in CUSTODY:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED, capability
        assert policy.exclusion_rationale == _RATIONALE, capability


def test_no_composition_desires_a_custody_name() -> None:
    for planes in _every_composition():
        composed = composed_capabilities(IMPLEMENTED, planes)
        for knowledge_manager in (False, True):
            desired = desired_effective_capabilities(composed, knowledge_manager=knowledge_manager)
            assert not desired & set(CUSTODY), planes
            # Non-vacuous: the ordinary report names are desired.
            assert Capability.REPORTS_DELETE in desired, planes


def test_an_active_grant_on_a_custody_name_is_an_unexpected_control_plane_grant() -> None:
    planes = ChatLLMCompositionPlanes(**dict.fromkeys(_PLANE_FLAGS, True))
    composed = composed_capabilities(IMPLEMENTED, planes)
    desired = desired_effective_capabilities(composed)
    healthy = tuple(_grant(capability) for capability in desired)
    baseline = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=healthy,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert baseline.is_healthy()
    for capability in CUSTODY:
        for knowledge_manager in (False, True):
            diff = diff_chatllm_data_profile(
                implemented=IMPLEMENTED,
                composed=composed,
                grants=(*healthy, _grant(capability)),
                now=NOW,
                resource=RESOURCE,
                scope=SCOPE,
                knowledge_manager=knowledge_manager,
            )
            assert (
                diff.outcomes[capability] is ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
            ), capability
            assert diff.unexpected_control_plane == {capability}
            assert not diff.is_healthy()
