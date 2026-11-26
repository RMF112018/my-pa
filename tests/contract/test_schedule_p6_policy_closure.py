"""P6 XER S7-4a: every closed registry classifies the 7 P6 names (FAST; acceptance D1, D7).

Schedule XER import contract (`docs/architecture/schedule-xer-import-contract.md`)
sections 10.1, 10.2 and 10.7: the section 10.1 inventory, row by row, against
the `Capability` enum, the purpose map, the operator-only, write, additive and
scopeless sets, the audit vocabulary the S7-2 revision restated ahead of the
domain, the remote write purposes, the idempotent and client-bound remote key
sets, the MCP annotations, the facade kind and feature label, the `SafeDetail`
additions, the ChatLLM classification (`chatllm-data-v19`: `DATA_CONDITIONAL`
under `SCHEDULE_P6`; with the switch off the profile desires exactly the
previous profile's set), the remote planner's switch read, remote publication
(only with the switches on, `writes_enabled` for the 2 writes and a grant per
name; the PDF import stays unpublished), the MCP database profiles (no P6
name) and the switch: off, the 7 are withheld from `capabilities.get` and the
tool list and each handler answers `unsupported` after the authorization audit.

Expected values are written out from the contract, never read from the sets
under test. Every value is synthetic.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any, Final

import pytest
from tests.conftest import Scene, build_service, metadata_for

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.remote import _WRITE_PURPOSES, is_remote_write, remote_tool_names
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    _CLIENT_BOUND_KEY_CAPABILITIES,
    _CLIENT_BOUND_P6_WRITES,
    _IDEMPOTENT_REMOTE_CAPABILITIES,
    is_remote_idempotent,
    resolve_remote_purpose,
)
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.commands import (
    GetCapabilities,
    ImportScheduleP6Publication,
    ListScheduleP6Activities,
    ListScheduleP6AvailableFields,
    ListScheduleP6Calendars,
    ListScheduleP6FieldValues,
    ListScheduleP6Relationships,
    SetScheduleP6CapturedFields,
)
from my_pa.application.errors import SafeDetail, UnsupportedError
from my_pa.application.service import _HANDLERS, _SCHEDULE_P6_CAPABILITIES
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.mcp_database_profiles import (
    MCP_PROFILE_OPT_IN_CAPABILITY_NAMES,
    MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
    MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    MCP_PROFILE_READ_CAPABILITIES,
    MCP_PROFILE_WRITE_CAPABILITIES,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    SCHEDULE_P6_DATA_NAMES,
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

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = (
    ROOT / "migrations" / "versions" / "20261125_d8383150cf72_schedule_p6_xer_storage.py"
)

_I: Final = Purpose.SCHEDULE_P6_IMPORT
_C: Final = Purpose.SCHEDULE_P6_CONFIGURATION
_R: Final = Purpose.SCHEDULE_READ

#: Section 10.1: capability -> (kind, purpose, facade kind).
INVENTORY: Final[dict[Capability, tuple[str, Purpose, str]]] = {
    Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6: ("write", _I, "write"),
    Capability.SCHEDULE_P6_FIELDS_AVAILABLE: ("read", _R, "read"),
    Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED: ("write", _C, "write"),
    Capability.SCHEDULE_P6_ACTIVITIES_LIST: ("read", _R, "read"),
    Capability.SCHEDULE_P6_RELATIONSHIPS_LIST: ("read", _R, "read"),
    Capability.SCHEDULE_P6_CALENDARS_LIST: ("read", _R, "read"),
    Capability.SCHEDULE_P6_FIELD_VALUES_LIST: ("read", _R, "read"),
}
NAMES: Final = {
    "schedule_publications.import_p6",
    "schedule_p6_fields.available",
    "schedule_p6_fields.set_captured",
    "schedule_p6_activities.list",
    "schedule_p6_relationships.list",
    "schedule_p6_calendars.list",
    "schedule_p6_field_values.list",
}
WRITES: Final = frozenset(
    capability for capability, (kind, _, _) in INVENTORY.items() if kind == "write"
)
_SERIES: Final = "sser_sp6close001"
_PUBLICATION: Final = "spub_sp6close001"


def _commands() -> dict[Capability, Any]:
    return {
        Capability.SCHEDULE_PUBLICATIONS_IMPORT_P6: ImportScheduleP6Publication(
            project_id="prj_sp6close001",
            series_name="Synthetic Series",
            workspace_id="syn",
            path="exports/synthetic.xer",
            expected_version="fv1_" + "0" * 64,
            expected_sha256="0" * 64,
            format="p6_xer",
            idempotency_key="p6-close-import-0001",
        ),
        Capability.SCHEDULE_P6_FIELDS_AVAILABLE: ListScheduleP6AvailableFields(series_id=_SERIES),
        Capability.SCHEDULE_P6_FIELDS_SET_CAPTURED: SetScheduleP6CapturedFields(
            series_id=_SERIES,
            field_keys=(),
            expected_sequence=0,
            idempotency_key="p6-close-select-001",
        ),
        Capability.SCHEDULE_P6_ACTIVITIES_LIST: ListScheduleP6Activities(
            publication_id=_PUBLICATION
        ),
        Capability.SCHEDULE_P6_RELATIONSHIPS_LIST: ListScheduleP6Relationships(
            publication_id=_PUBLICATION
        ),
        Capability.SCHEDULE_P6_CALENDARS_LIST: ListScheduleP6Calendars(publication_id=_PUBLICATION),
        Capability.SCHEDULE_P6_FIELD_VALUES_LIST: ListScheduleP6FieldValues(
            publication_id=_PUBLICATION
        ),
    }


def test_the_inventory_is_the_7_names_appended_after_the_communications_reads() -> None:
    members = list(Capability)
    start = members.index(Capability.COMMUNICATIONS_COVERAGE) + 1
    assert members[start : start + len(INVENTORY)] == list(INVENTORY)
    assert {capability.value for capability in INVENTORY} == NAMES
    assert set(INVENTORY) == _SCHEDULE_P6_CAPABILITIES == SCHEDULE_P6_DATA_NAMES
    purposes = list(Purpose)
    start = purposes.index(Purpose.COMMUNICATIONS_READ) + 1
    assert purposes[start : start + 2] == [_I, _C]


@pytest.mark.parametrize("capability", list(INVENTORY), ids=lambda c: c.value)
def test_every_registry_classifies_the_row(capability: Capability) -> None:
    kind, purpose, facade = INVENTORY[capability]
    write = kind == "write"
    assert permitted_purposes(capability) == frozenset({purpose})
    assert capability in _SCOPELESS
    assert capability in _HANDLERS
    assert not is_operator_only(capability)
    assert capability not in _OPERATOR_ONLY
    assert is_write_capability(capability) is write
    assert (capability in _WRITE_CAPABILITIES) is write
    assert (capability in _ADDITIVE_WRITE_CAPABILITIES) is write
    assert not is_destructive_capability(capability)
    assert facade_kind(capability) == facade
    assert is_remote_write(capability) is write
    assert feature_label(capability.value) == "schedule"
    assert (capability in _IDEMPOTENT_REMOTE_CAPABILITIES) is write
    assert (capability in _CLIENT_BOUND_KEY_CAPABILITIES) is write
    assert (capability in _CLIENT_BOUND_P6_WRITES) is write
    assert is_remote_idempotent(capability) is write


def test_the_two_write_purposes_are_remote_writes_and_the_read_purpose_is_not() -> None:
    assert {_I, _C} <= _WRITE_PURPOSES
    assert _R not in _WRITE_PURPOSES


def test_the_tools_carry_their_hints_and_a_catalog_summary() -> None:
    tools = {tool.name: tool for tool in TOOLS}
    for capability, (kind, _, _) in INVENTORY.items():
        tool = tools[capability.value]
        annotations = tool.annotations
        assert annotations is not None
        assert annotations.idempotent_hint is (kind == "write"), capability.value
        assert annotations.read_only_hint is (kind == "read"), capability.value
        assert annotations.destructive_hint is False, capability.value
        assert (tool.description or "").endswith("."), capability.value


def test_the_audit_vocabulary_restated_by_s7_2_names_the_7_and_the_2() -> None:
    source = REVISION.read_text(encoding="utf-8")
    quoted = set(re.findall(r"'([a-z0-9_.]+)'", source)) | set(
        re.findall(r'"([a-z0-9_.]+)"', source)
    )
    assert quoted >= NAMES
    assert {_I.value, _C.value} <= quoted


def test_the_new_safe_details_exist() -> None:
    for name in ("FIELD_KEY", "FIELD_FILTER", "INCLUDE_PERSONAL", "ENTITY_KIND", "CALENDAR_ID"):
        assert SafeDetail[name].value == name.lower()
    # Reused from the head: the compare-and-swap, the quota and the S7-3 tokens.
    for name in (
        "SEQUENCE",
        "STORAGE_QUOTA",
        "WORKSPACE_ID",
        "PATH",
        "EXPECTED_VERSION",
        "EXPECTED_SHA256",
        "SOURCE_FORMAT",
        "FORMAT",
        "SERIES_FORMAT",
    ):
        assert SafeDetail[name]


def test_no_command_field_is_a_workspace_path_answer() -> None:
    """Section 10.4: `path` is an input of the import only, never of a read."""
    for command in _commands().values():
        names = {field.name for field in fields(command)}
        assert ("path" in names) is isinstance(command, ImportScheduleP6Publication)


# ---- ChatLLM (section 10.7) ---------------------------------------------------------------


def test_chatllm_classifies_the_7_at_v19() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v19"
    for capability in INVENTORY:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.SCHEDULE_P6


def _planes(**switches: bool) -> ChatLLMCompositionPlanes:
    return ChatLLMCompositionPlanes(
        managed_documents=switches.get("managed_documents", True),
        relationship_intelligence=switches.get("relationship_intelligence", True),
        relationship_intelligence_writes=switches.get("relationship_intelligence_writes", True),
        relationship_memory=switches.get("relationship_memory", True),
        constraints=True,
        knowledge_assertions=switches.get("knowledge_assertions", True),
        lineage=switches.get("lineage", True),
        program_reporting=switches.get("program_reporting", True),
        schedule=switches.get("schedule", True),
        schedule_scenarios=switches.get("schedule_scenarios", True),
        files_workspace=switches.get("files_workspace", True),
        communications=switches.get("communications", True),
        schedule_p6=switches.get("schedule_p6", False),
    )


def _desired(planes: ChatLLMCompositionPlanes) -> frozenset[Capability]:
    implemented = frozenset(CHATLLM_CAPABILITY_POLICY)
    return desired_effective_capabilities(composed_capabilities(implemented, planes))


@pytest.mark.parametrize(
    ("schedule", "others"), list(itertools.product((True, False), (True, False)))
)
def test_with_the_switch_off_v19_desires_exactly_the_previous_set(
    schedule: bool, others: bool
) -> None:
    """D1: v19 off equals v17 (v19 minus the 7); on adds exactly the 7, writes included."""
    base = {
        "schedule": schedule,
        "communications": others,
        "files_workspace": others,
        "lineage": others,
    }
    off = _desired(_planes(**base, schedule_p6=False))
    on = _desired(_planes(**base, schedule_p6=True))
    assert not off & SCHEDULE_P6_DATA_NAMES
    assert off == on - SCHEDULE_P6_DATA_NAMES
    if schedule:
        assert on - off == SCHEDULE_P6_DATA_NAMES
        assert on >= WRITES
    else:
        # The P6 switch widens nothing alone.
        assert on == off


def test_the_remote_planner_reads_the_p6_switch() -> None:
    from apps.cli.remote_mcp import _planes_from_settings

    url = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"
    assert _planes_from_settings(Settings(database_url=url)).schedule_p6 is False
    on = _planes_from_settings(
        Settings(database_url=url, schedule_enabled=True, schedule_p6_enabled=True)
    )
    assert on.schedule and on.schedule_p6
    assert _desired(on) >= SCHEDULE_P6_DATA_NAMES


def test_no_mcp_database_profile_names_a_p6_capability() -> None:
    """Section 10.7: no restricted MCP database role gains a privilege."""
    for ceiling in (
        MCP_PROFILE_READ_CAPABILITIES,
        MCP_PROFILE_WRITE_CAPABILITIES,
        MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
        MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    ):
        assert not set(INVENTORY) & set(ceiling)
    assert not NAMES & set(MCP_PROFILE_OPT_IN_CAPABILITY_NAMES)


# ---- remote publication (D7) and the switch (section 10.2) -------------------------------


def test_remote_publication_needs_the_switches_writes_enabled_and_a_grant(scene: Scene) -> None:
    on = build_service(
        scene.world, scene.providers, schedule_enabled=True, schedule_p6_enabled=True
    )
    published = remote_tool_names(on, writes_enabled=True)
    assert published >= NAMES
    # The PDF import is operator-only and stays unpublished.
    assert "schedule_publications.import" not in published
    reads_only = remote_tool_names(on, writes_enabled=False)
    assert {capability.value for capability in WRITES} & reads_only == set()
    assert NAMES - {capability.value for capability in WRITES} <= reads_only
    # A grant per name: the remote boundary refuses a name the client holds no
    # grant on, and stamps the one permitted purpose for a name it does.
    held = frozenset({(Capability.SCHEDULE_P6_ACTIVITIES_LIST, _R)})
    assert resolve_remote_purpose(Capability.SCHEDULE_P6_ACTIVITIES_LIST, held) is _R
    for capability in set(INVENTORY) - {Capability.SCHEDULE_P6_ACTIVITIES_LIST}:
        with pytest.raises(UnsupportedError):
            resolve_remote_purpose(capability, held)
    for switches in (
        {"schedule_enabled": False, "schedule_p6_enabled": True},
        {"schedule_enabled": True},
    ):
        off = build_service(scene.world, scene.providers, **switches)
        assert not NAMES & remote_tool_names(off, writes_enabled=True)


@pytest.mark.parametrize("capability", list(INVENTORY), ids=lambda capability: capability.value)
def test_switch_off_withholds_and_refuses_every_p6_capability(
    scene: Scene, capability: Capability
) -> None:
    service = build_service(scene.world, scene.providers, schedule_enabled=True)
    assert capability not in service.available_capabilities
    manifest = service.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    ).result
    assert manifest is not None
    rows: Mapping[str, Any] = {
        row["name"]: row
        for row in manifest["manifest"]["capabilities"]  # type: ignore[index]
    }
    assert rows[capability.value]["availability"] == "not_implemented"
    assert capability.value not in {
        tool.name for tool in published_tools(service, authenticated_client_present=True)
    }
    audited = len(scene.world.audit)
    (purpose,) = permitted_purposes(capability)
    envelope = service.invoke(
        metadata_for(capability, purpose, scene.principal),
        _commands()[capability],
        principal=scene.principal,
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.UNSUPPORTED
    assert [event.capability for event in scene.world.audit[audited:]] == [capability]


def test_switch_on_serves_the_7(scene: Scene) -> None:
    service = build_service(
        scene.world, scene.providers, schedule_enabled=True, schedule_p6_enabled=True
    )
    assert set(INVENTORY) <= service.available_capabilities
    published = {tool.name for tool in published_tools(service, authenticated_client_present=True)}
    assert published >= NAMES
