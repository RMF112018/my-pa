"""Schedule Scenarios S6-3: every closed registry classifies the 26 plane names (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 15.2, 15.3
and 15.12: the section 15.3 inventory, row by row, against the `Capability`
enum, the purpose map, the operator-only, write, additive and scopeless sets,
the audit vocabulary at head, the remote write purposes, the idempotent and
client-bound remote key sets, the MCP annotations, the façade kind and feature
label, the cursor orders and the `SafeDetail` additions; and package I10-A's
ChatLLM holding classification (S6-3-D17, R10-F08), which package I10-C
replaces with the final v13 classes.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest
from tests.schedule_scenario_samples import SCHEDULE_SCENARIO_COMMAND_TYPES

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.remote import _WRITE_PURPOSES, is_remote_write
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    _CLIENT_BOUND_KEY_CAPABILITIES,
    _CLIENT_BOUND_SCENARIO_WRITES,
    _IDEMPOTENT_REMOTE_CAPABILITIES,
    is_remote_idempotent,
)
from my_pa.application.errors import SafeDetail
from my_pa.application.service import _HANDLERS, _SCHEDULE_SCENARIO_CAPABILITIES
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import (
    _ADDITIVE_WRITE_CAPABILITIES,
    _OPERATOR_ONLY,
    _WRITE_CAPABILITIES,
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.schedule.cursor import ScheduleCursorOrder
from my_pa.domain.schedule.scenario.changeset import ChangeOpError

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION_B: Final = (
    ROOT / "migrations" / "versions" / ("20261111_b77334135653_schedule_scenarios_vocabulary.py")
)

_W: Final = Purpose.SCHEDULE_ANALYSIS_AUTHORING
_R: Final = Purpose.SCHEDULE_ANALYSIS_READ
_A: Final = Purpose.SCHEDULE_BASELINE_APPROVAL

#: Section 15.3 rows 11-26: the 16 plane reads.
_READS: Final = (
    Capability.SCHEDULE_SCENARIOS_LIST,
    Capability.SCHEDULE_SCENARIOS_READ,
    Capability.SCHEDULE_SCENARIO_VERSIONS_READ,
    Capability.SCHEDULE_SCENARIO_VERSIONS_ACTIVITIES,
    Capability.SCHEDULE_SCENARIO_VERSIONS_RELATIONSHIPS,
    Capability.SCHEDULE_SCENARIO_VERSIONS_CHANGES,
    Capability.SCHEDULE_CPM_RUNS_READ,
    Capability.SCHEDULE_CPM_RUNS_ACTIVITIES,
    Capability.SCHEDULE_SCENARIO_OUTPUTS_LIST,
    Capability.SCHEDULE_SCENARIO_OUTPUTS_READ,
    Capability.SCHEDULE_SERIES_CURRENT,
    Capability.SCHEDULE_SERIES_MATCH_DECISIONS,
    Capability.SCHEDULE_BASELINES_LIST,
    Capability.SCHEDULE_BASELINES_READ,
    Capability.SCHEDULE_BASELINES_GOVERNING,
    Capability.SCHEDULE_BASELINES_COMPARE,
)
#: Section 15.3: capability -> (kind, purpose, facade kind, additive, keyed).
INVENTORY: Final[dict[Capability, tuple[str, Purpose, str, bool, bool]]] = {
    Capability.SCHEDULE_SCENARIOS_CREATE: ("client", _W, "write", True, True),
    Capability.SCHEDULE_SCENARIO_VERSIONS_CREATE: ("client", _W, "write", True, True),
    Capability.SCHEDULE_CPM_RUNS_CREATE: ("client", _W, "write", True, True),
    Capability.SCHEDULE_SCENARIO_OUTPUTS_RECORD: ("client", _W, "write", True, True),
    Capability.SCHEDULE_BASELINES_PROPOSE: ("client", _W, "write", True, True),
    Capability.SCHEDULE_BASELINES_WITHDRAW: ("client", _W, "write", False, True),
    Capability.SCHEDULE_BASELINES_APPROVE: ("operator", _A, "operator", False, False),
    Capability.SCHEDULE_BASELINES_REJECT: ("operator", _A, "operator", False, False),
    Capability.SCHEDULE_BASELINES_REVOKE: ("operator", _A, "operator", False, False),
    Capability.SCHEDULE_BASELINES_SET_GOVERNING: ("operator", _A, "operator", False, False),
    **dict.fromkeys(_READS, ("read", _R, "read", False, False)),
}
_PENDING: Final = "Schedule Scenarios S6-3 pending exposure (I10-C)"


def test_the_inventory_is_the_26_appended_names() -> None:
    members = list(Capability)
    assert members[-26:] == list(INVENTORY)
    assert set(INVENTORY) == _SCHEDULE_SCENARIO_CAPABILITIES == set(SCHEDULE_SCENARIO_COMMAND_TYPES)
    assert list(Purpose)[-3:] == [_W, _R, _A]
    assert (len(Capability), len(Purpose)) == (281, 68)


@pytest.mark.parametrize("capability", list(INVENTORY), ids=lambda c: c.value)
def test_every_registry_classifies_the_row(capability: Capability) -> None:
    kind, purpose, facade, additive, keyed = INVENTORY[capability]
    assert permitted_purposes(capability) == frozenset({purpose})
    assert capability in _SCOPELESS
    assert capability in _HANDLERS
    assert is_operator_only(capability) is (kind == "operator")
    assert (capability in _OPERATOR_ONLY) is (kind == "operator")
    assert is_write_capability(capability) is (kind != "read")
    assert (capability in _WRITE_CAPABILITIES) is (kind != "read")
    assert (capability in _ADDITIVE_WRITE_CAPABILITIES) is additive
    assert is_destructive_capability(capability) is (kind != "read" and not additive)
    assert facade_kind(capability) == facade
    assert is_remote_write(capability) is (kind != "read")
    assert feature_label(capability.value) == "schedule"
    assert (capability in _IDEMPOTENT_REMOTE_CAPABILITIES) is keyed
    assert (capability in _CLIENT_BOUND_KEY_CAPABILITIES) is keyed
    assert (capability in _CLIENT_BOUND_SCENARIO_WRITES) is keyed
    assert is_remote_idempotent(capability) is keyed


def test_the_write_purposes_are_remote_writes_and_the_read_purpose_is_not() -> None:
    assert {_W, _A} <= _WRITE_PURPOSES
    assert _R not in _WRITE_PURPOSES


def test_scenario_tools_carry_the_idempotent_hint() -> None:
    """Section 15.12.2 (S6-3-D06): the 6 client writes' tools are idempotent-hinted (P3-10)."""
    tools = {tool.name: tool for tool in TOOLS}
    for capability, (kind, *_rest) in INVENTORY.items():
        annotations = tools[capability.value].annotations
        assert annotations is not None
        assert annotations.idempotent_hint is (kind == "client"), capability.value
        assert annotations.read_only_hint is (kind == "read"), capability.value


def test_the_docstrings_are_the_catalog_summaries() -> None:
    """Section 15.3: the revoke summary carries the finality warning (S6-U15)."""
    tools = {tool.name: tool for tool in TOOLS}
    assert tools["schedule_baselines.revoke"].description == (
        "Revoke an approved, non-governing baseline; final for its publication, which can "
        "never be approved again (attested local operator only)."
    )
    assert tools["schedule_baselines.propose"].description == (
        "Propose one eligible publication as a Project baseline; a proposal is not a "
        "baseline until the operator approves it."
    )
    for capability, (kind, *_rest) in INVENTORY.items():
        description = tools[capability.value].description or ""
        assert description.endswith(".")
        assert ("(attested local operator only)" in description) is (kind == "operator")


def test_the_audit_vocabulary_at_head_names_the_26_and_the_3() -> None:
    namespace: dict[str, object] = {}
    exec(compile(REVISION_B.read_text(encoding="utf-8"), str(REVISION_B), "exec"), namespace)  # noqa: S102
    capabilities = set(re.findall(r"'([^']+)'", str(namespace["_CAPABILITIES_AT_THIS_REVISION"])))
    purposes = set(re.findall(r"'([^']+)'", str(namespace["_PURPOSES_AT_THIS_REVISION"])))
    assert {capability.value for capability in INVENTORY} <= capabilities
    assert {_W.value, _R.value, _A.value} <= purposes


def test_the_six_plane_cursor_orders_and_the_37_details_exist() -> None:
    assert [order.value for order in list(ScheduleCursorOrder)[-6:]] == [
        "scenarios_created_desc_id_desc",
        "versions_no_desc",
        "scenario_content_offset",
        "outputs_created_desc_id_desc",
        "match_decisions_created_desc_id_desc",
        "baselines_created_desc_id_desc",
    ]
    assert len(ScheduleCursorOrder) == 11
    assert len(SafeDetail) == 396
    for error in ChangeOpError:
        assert SafeDetail(f"change_set_{error.value}").name == f"CHANGE_SET_{error.name}"


def test_chatllm_holds_the_26_excluded_at_v12() -> None:
    """S6-3-D17 (R10-F08): no exposure and no version bump at package I10-A."""
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v12"
    for capability in INVENTORY:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
        assert policy.exclusion_rationale == _PENDING
    counts = dict.fromkeys(ChatLLMCapabilityClass, 0)
    for policy in CHATLLM_CAPABILITY_POLICY.values():
        counts[policy.classification] += 1
    assert len(CHATLLM_CAPABILITY_POLICY) == 281
    assert counts[ChatLLMCapabilityClass.DATA_REQUIRED] == 85
    assert counts[ChatLLMCapabilityClass.DATA_CONDITIONAL] == 137
    assert counts[ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED] == 55
