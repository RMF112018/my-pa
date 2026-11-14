"""Schedule Scenarios S6-3: every closed registry classifies the 26 plane names (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 15.2, 15.3
and 15.12: the section 15.3 inventory, row by row, against the `Capability`
enum, the purpose map, the operator-only, write, additive and scopeless sets,
the audit vocabulary at head, the remote write purposes, the idempotent and
client-bound remote key sets, the MCP annotations, the façade kind and feature
label, the cursor orders and the `SafeDetail` additions; and package I10-C's
final ChatLLM classification (`chatllm-data-v13`, section 15.12.1), which
replaced package I10-A's holding classification (S6-3-D17, R10-F08): the
executed planner targets, both-switch composition, the never-desired operator
names, old-client compatibility (DV-01) and the remote planner's switch read.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import fields
from datetime import UTC, datetime
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
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
)
from my_pa.application.errors import SafeDetail
from my_pa.application.service import _HANDLERS, _SCHEDULE_SCENARIO_CAPABILITIES
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.mcp_database_profiles import (
    MCP_PROFILE_OPT_IN_CAPABILITY_NAMES,
    MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
    MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    MCP_PROFILE_READ_CAPABILITIES,
    MCP_PROFILE_WRITE_CAPABILITIES,
)
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    SCHEDULE_DATA_NAMES,
    SCHEDULE_SCENARIO_DATA_NAMES,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
    is_chatllm_data_management,
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


def test_the_inventory_is_the_26_appended_names() -> None:
    members = list(Capability)
    # The files workspace WP5 appends its 17 names (and 2 purposes) after these.
    assert members[-43:-17] == list(INVENTORY)
    assert set(INVENTORY) == _SCHEDULE_SCENARIO_CAPABILITIES == set(SCHEDULE_SCENARIO_COMMAND_TYPES)
    assert list(Purpose)[-5:-2] == [_W, _R, _A]
    assert (len(Capability), len(Purpose)) == (298, 70)


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
    # Files workspace WP5: its 11 reason tokens and 10 field details, 396 -> 417.
    assert len(SafeDetail) == 417
    for error in ChangeOpError:
        assert SafeDetail(f"change_set_{error.value}").name == f"CHANGE_SET_{error.name}"


# ---- ChatLLM chatllm-data-v13 (section 15.12.1) and the remote planner (15.12.2) ----

_CLIENT_USABLE: Final[frozenset[Capability]] = frozenset(
    capability for capability, (kind, *_rest) in INVENTORY.items() if kind != "operator"
)
_OPERATOR_NAMES: Final[frozenset[Capability]] = frozenset(INVENTORY) - _CLIENT_USABLE
_APPROVAL_RATIONALE: Final = (
    "attested operator baseline approval; the attested local operator only "
    "(operator decision 2026-11-03)"
)
_IMPLEMENTED: Final = frozenset(_HANDLERS)
_PLANE_FLAGS: Final = tuple(field.name for field in fields(ChatLLMCompositionPlanes))
_FULL: Final = {
    "managed_documents": True,
    "relationship_intelligence": True,
    "relationship_intelligence_writes": True,
    "relationship_memory": True,
    "constraints": True,
}
_NOW: Final = datetime(2026, 11, 11, 12, tzinfo=UTC)
_RESOURCE: Final = "https://my-pa.example/mcp"
_SCOPE: Final = "my-pa.read"


def _planes(**flags: bool) -> ChatLLMCompositionPlanes:
    return ChatLLMCompositionPlanes(
        **{name: flags.get(name, False) for name in _PLANE_FLAGS}  # type: ignore[arg-type]
    )


def _every_composition() -> list[ChatLLMCompositionPlanes]:
    return [
        ChatLLMCompositionPlanes(**dict(zip(_PLANE_FLAGS, bits, strict=True)))  # type: ignore[arg-type]
        for bits in itertools.product((False, True), repeat=len(_PLANE_FLAGS))
    ]


def _desired(planes: ChatLLMCompositionPlanes) -> frozenset[Capability]:
    return desired_effective_capabilities(composed_capabilities(_IMPLEMENTED, planes))


def _grant(capability: Capability) -> ChatLLMGrantRecord:
    if is_chatllm_data_management(capability):
        purpose = chatllm_grant_purpose(capability)
    else:
        (purpose,) = permitted_purposes(capability)
    return ChatLLMGrantRecord(
        capability=capability,
        purpose=purpose,
        is_write=is_write_capability(capability),
        resource=_RESOURCE,
        scope=_SCOPE,
        expires_at=None,
        revoked_at=None,
    )


def test_chatllm_classifies_the_26_at_v13() -> None:
    """Sections 15.3 and 15.12.1: 22 `DATA_CONDITIONAL`, the 4 operator names excluded."""
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v14"
    assert _CLIENT_USABLE == SCHEDULE_SCENARIO_DATA_NAMES
    assert (len(_CLIENT_USABLE), len(_OPERATOR_NAMES)) == (22, 4)
    for capability in _CLIENT_USABLE:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL, capability
        assert policy.composition_prerequisite is (
            ChatLLMCompositionPrerequisite.SCHEDULE_SCENARIOS
        )
        assert policy.exclusion_rationale is None
        assert chatllm_grant_purpose(capability) is INVENTORY[capability][1]
    for capability in _OPERATOR_NAMES:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
        assert policy.exclusion_rationale == _APPROVAL_RATIONALE
        assert not is_chatllm_data_management(capability)
    assert {
        policy.capability
        for policy in CHATLLM_CAPABILITY_POLICY.values()
        if policy.composition_prerequisite is ChatLLMCompositionPrerequisite.SCHEDULE_SCENARIOS
    } == _CLIENT_USABLE
    counts = dict.fromkeys(ChatLLMCapabilityClass, 0)
    for policy in CHATLLM_CAPABILITY_POLICY.values():
        counts[policy.classification] += 1
    # Files workspace WP5 (chatllm-data-v14): the 17 `files.*` names, 159 -> 176.
    assert len(CHATLLM_CAPABILITY_POLICY) == 298
    assert counts[ChatLLMCapabilityClass.DATA_REQUIRED] == 85
    assert counts[ChatLLMCapabilityClass.DATA_CONDITIONAL] == 176
    assert counts[ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED] == 33
    assert ChatLLMCompositionPlanes.__dataclass_fields__["schedule_scenarios"].default is False


def test_v13_targets() -> None:
    """Section 15.2 (S6-3-D04): the planner targets, executed at v13."""
    full = _desired(_planes(**_FULL))
    assert len(full) == 175
    assert len(_desired(_planes(constraints=True))) == 109
    # The scenario switch alone (without the Schedule switch) composes nothing.
    assert _desired(_planes(**_FULL, schedule_scenarios=True)) == full
    with_schedule = _desired(_planes(**_FULL, schedule=True))
    assert len(with_schedule) == 181
    with_scenarios = _desired(_planes(**_FULL, schedule=True, schedule_scenarios=True))
    assert len(with_scenarios) == 203
    assert with_scenarios - with_schedule == _CLIENT_USABLE
    everything = {"lineage": True, "program_reporting": True, "schedule": True}
    assert len(_desired(_planes(**_FULL, **everything))) == 215
    assert len(_desired(_planes(**_FULL, **everything, schedule_scenarios=True))) == 237
    assert len(_desired(_planes(constraints=True, **everything))) == 147
    assert len(_desired(_planes(constraints=True, **everything, schedule_scenarios=True))) == 169
    # Files workspace WP5 (chatllm-data-v14): its own flag, 1,024 -> 2,048.
    assert len(_every_composition()) == 2048


def test_planner_desires_the_22_only_with_both_switches() -> None:
    """P3-30: every composition desires the 22 exactly when both switches hold."""
    for planes in _every_composition():
        desired = _desired(planes)
        both = planes.schedule and planes.schedule_scenarios
        for capability in _CLIENT_USABLE:
            assert (capability in desired) is both, (capability, planes)
    assert _desired(_planes(schedule=True, schedule_scenarios=True)) >= _CLIENT_USABLE


def test_planner_never_desires_the_4() -> None:
    """P3-31: no composition desires an operator baseline decision; a grant is unexpected."""
    for planes in _every_composition():
        assert not _desired(planes) & _OPERATOR_NAMES, planes
    planes = _planes(**_FULL, schedule=True, schedule_scenarios=True)
    composed = composed_capabilities(_IMPLEMENTED, planes)
    assert composed >= _OPERATOR_NAMES
    healthy = tuple(_grant(capability) for capability in desired_effective_capabilities(composed))
    for capability in sorted(_OPERATOR_NAMES):
        diff = diff_chatllm_data_profile(
            implemented=_IMPLEMENTED,
            composed=composed,
            grants=(*healthy, _grant(capability)),
            now=_NOW,
            resource=_RESOURCE,
            scope=_SCOPE,
        )
        assert diff.outcomes[capability] is ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
        assert not diff.is_healthy()


@pytest.mark.parametrize("held", ["v12_applied", "v12_without_schedule", "v11", "v10"])
def test_old_client_stays_healthy_while_the_plane_is_off(held: str) -> None:
    """Section 15.12.1 (DV-01): an older client keeps its grants and stays healthy while off.

    With the plane on, `profile-diff` reports as missing exactly the 22 plus the
    6 S5b-2 reads and the 11 v12 Reports names the client does not hold yet
    (22, 28, 33 or 39; the section 15.17 set rule). No removal is ever planned.
    """
    reports = frozenset(
        Capability(name)
        for name in (
            "reports.publish",
            "reports.update",
            "reports.history",
            "reports.archive",
            "reports.delete",
            "reports.restore",
            "reports.transfer.begin",
            "reports.transfer.append",
            "reports.transfer.finalize",
            "reports.transfer.abort",
            "reports.transfer.read_chunk",
        )
    )
    assert reports <= _desired(_planes(**_FULL))
    schedule_reads = SCHEDULE_DATA_NAMES
    assert (len(reports), len(schedule_reads)) == (11, 6)
    off = _planes(**_FULL, lineage=True, program_reporting=True, schedule=True)
    on = _planes(
        **_FULL, lineage=True, program_reporting=True, schedule=True, schedule_scenarios=True
    )
    held_set = {
        "v12_applied": _desired(off),
        "v12_without_schedule": _desired(off) - schedule_reads,
        "v11": _desired(off) - reports,
        "v10": _desired(off) - reports - schedule_reads,
    }[held]
    expected_missing = {"v12_applied": 22, "v12_without_schedule": 28, "v11": 33, "v10": 39}[held]
    grants = tuple(_grant(capability) for capability in held_set)
    healthy_off = diff_chatllm_data_profile(
        implemented=_IMPLEMENTED,
        composed=composed_capabilities(_IMPLEMENTED, off),
        grants=tuple(_grant(capability) for capability in _desired(off)),
        now=_NOW,
        resource=_RESOURCE,
        scope=_SCOPE,
    )
    assert healthy_off.is_healthy()
    assert healthy_off.profile_version == "chatllm-data-v14"
    diff = diff_chatllm_data_profile(
        implemented=_IMPLEMENTED,
        composed=composed_capabilities(_IMPLEMENTED, on),
        grants=grants,
        now=_NOW,
        resource=_RESOURCE,
        scope=_SCOPE,
    )
    assert diff.add <= _CLIENT_USABLE | schedule_reads | reports
    assert diff.add >= _CLIENT_USABLE
    assert len(diff.add) == expected_missing
    assert not diff.unexpected_control_plane
    if held == "v12_applied":
        # The v12 set is exactly v13 with the scenario switch off.
        assert held_set == _desired(on) - _CLIENT_USABLE
    # No MCP database profile ceiling or opt-in names a plane capability (DV-01).
    names = {capability.value for capability in INVENTORY}
    for ceiling in (
        MCP_PROFILE_READ_CAPABILITIES,
        MCP_PROFILE_WRITE_CAPABILITIES,
        MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
        MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    ):
        assert not set(INVENTORY) & set(ceiling)
    assert not names & set(MCP_PROFILE_OPT_IN_CAPABILITY_NAMES)


def test_remote_planner_reads_the_scenario_switch() -> None:
    """P3-34: `_planes_from_settings` composes the plane from the serving switches."""
    from apps.cli.remote_mcp import _planes_from_settings

    url = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"
    assert _planes_from_settings(Settings(database_url=url)).schedule_scenarios is False
    on = _planes_from_settings(
        Settings(database_url=url, schedule_enabled=True, schedule_scenarios_enabled=True)
    )
    assert on.schedule and on.schedule_scenarios
    assert _desired(on) >= _CLIENT_USABLE
