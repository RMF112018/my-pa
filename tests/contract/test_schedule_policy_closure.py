"""CPM Workbench S5b-2: the 7 Schedule names on every closed policy surface (FAST).

Worker and capabilities contract sections 3.1, 3.12 and 3.13 (I7-B):

* each closed surface classifies the 7 names exactly -- the enums, the operator
  set, the purposes, the write and additive sets, the scopeless set, the
  requested scope, the command union, the builders, the handlers, the
  `SafeDetail` tokens, the remote write purposes, the ChatLLM policy and planes,
  the gateway family map, the service switch sets and the audit vocabulary --
  one parametrized case per surface, so a red names the surface;
* the 6 reads are scopeless and the import is scoped to the source of the
  caller's own enrollment;
* the surfaces the contract keeps unchanged are unchanged;
* the ChatLLM `chatllm-data-v11` targets, the `SCHEDULE` prerequisite, the
  import's exclusion and the planner's switch dependence;
* the import is never remote-published, never remote-idempotent, and no
  Schedule name joins an MCP database profile ceiling or opt-in;
* with the switch off every Schedule name is withheld and every handler answers
  `unsupported` after the authorization audit row.

Expected sets are written out from the contract, never read from the sets under
test. Every value is synthetic.
"""

from __future__ import annotations

import ast
import inspect
import itertools
from collections.abc import Callable, Mapping
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.adapters.mcp import TOOLS
from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.remote import (
    _REMOTE_OPERATOR_IDENTITY_CAPABILITIES,
    _WRITE_PURPOSES,
    is_remote_write,
    remote_tool_names,
)
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.normalization import _BUILDERS
from my_pa.adapters.remote_request import (
    _IDEMPOTENT_REMOTE_CAPABILITIES,
    _SERVER_REPLAY_REMOTE_CAPABILITIES,
    CANONICAL_REMOTE_PURPOSES,
    is_remote_idempotent,
)
from my_pa.application import commands as commands_module
from my_pa.application.authorization import _requested_scope
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
)
from my_pa.application.commands import (
    GetCapabilities,
    ImportSchedulePublication,
    ListScheduleActivities,
    ListScheduleChanges,
    ListSchedulePublications,
    ListScheduleSeries,
    ReadScheduleActivityHistory,
    ReadSchedulePublication,
)
from my_pa.application.errors import SafeDetail
from my_pa.application.service import (
    _HANDLERS,
    _SCHEDULE_CAPABILITIES,
    _SCHEDULE_READ_CAPABILITIES,
)
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
    SCHEDULE_DATA_NAMES,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.persistence import tables

ROOT: Final = Path(__file__).resolve().parents[2]

#: Contract section 3.5, in declaration order: `(member, value, command, handler)`.
_TABLE: Final[tuple[tuple[str, str, type, str], ...]] = (
    (
        "SCHEDULE_PUBLICATIONS_IMPORT",
        "schedule_publications.import",
        ImportSchedulePublication,
        "_schedule_publications_import",
    ),
    ("SCHEDULE_SERIES_LIST", "schedule_series.list", ListScheduleSeries, "_schedule_series_list"),
    (
        "SCHEDULE_PUBLICATIONS_LIST",
        "schedule_publications.list",
        ListSchedulePublications,
        "_schedule_publications_list",
    ),
    (
        "SCHEDULE_PUBLICATIONS_READ",
        "schedule_publications.read",
        ReadSchedulePublication,
        "_schedule_publications_read",
    ),
    (
        "SCHEDULE_ACTIVITIES_LIST",
        "schedule_activities.list",
        ListScheduleActivities,
        "_schedule_activities_list",
    ),
    (
        "SCHEDULE_ACTIVITIES_HISTORY",
        "schedule_activities.history",
        ReadScheduleActivityHistory,
        "_schedule_activities_history",
    ),
    (
        "SCHEDULE_CHANGES_LIST",
        "schedule_changes.list",
        ListScheduleChanges,
        "_schedule_changes_list",
    ),
)
IMPORT: Final = Capability.SCHEDULE_PUBLICATIONS_IMPORT
SEVEN: Final[tuple[Capability, ...]] = tuple(Capability(value) for _, value, _, _ in _TABLE)
READS: Final[frozenset[Capability]] = frozenset(SEVEN) - {IMPORT}
#: Contract section 4.5: the 14 new `SafeDetail` tokens.
_SAFE_DETAILS: Final[dict[str, str]] = {
    "SERIES_ID": "series_id",
    "SERIES_NAME": "series_name",
    "PUBLICATION_ID": "publication_id",
    "PUBLICATION_ROLE": "publication_role",
    "BASELINE_KIND": "baseline_kind",
    "EXPECTED_DATA_DATE": "expected_data_date",
    "SUPERSEDES_PUBLICATION_ID": "supersedes_publication_id",
    "SCHEDULE_ACTIVITY_ID": "schedule_activity_id",
    "FROM_PUBLICATION_ID": "from_publication_id",
    "TO_PUBLICATION_ID": "to_publication_id",
    "CHANGE_KIND": "change_kind",
    "HIERARCHY_PREFIX": "hierarchy_prefix",
    "ROW_TYPE": "row_type",
    "DATE_RANGE": "date_range",
}
_IMPORT_RATIONALE: Final = (
    "operator-only schedule source admission (local operator surface; source designation OD-06)"
)
NOW: Final = datetime(2026, 10, 28, 12, tzinfo=UTC)
RESOURCE: Final = "https://my-pa.example/mcp"
SCOPE: Final = "my-pa.read"
IMPLEMENTED: Final = frozenset(_HANDLERS)
_PLANE_FLAGS: Final = tuple(field.name for field in fields(ChatLLMCompositionPlanes))
_FULL: Final = {
    "managed_documents": True,
    "relationship_intelligence": True,
    "relationship_intelligence_writes": True,
    "relationship_memory": True,
    "constraints": True,
}


def _commands(scene: Scene) -> dict[Capability, object]:
    """One valid command per Schedule capability, inside `scene`'s own scope."""
    return {
        IMPORT: ImportSchedulePublication(
            project_id="prj_schedclosure001",
            series_name="Closure master schedule",
            enrollment_id=scene.enrollment.enrollment_id,
            source_object_id="obj_schedclosure001",
            source_version_id="ver_schedclosure001",
            publication_role="update",
            idempotency_key="schedule-closure-0001",
        ),
        Capability.SCHEDULE_SERIES_LIST: ListScheduleSeries(project_id="prj_schedclosure001"),
        Capability.SCHEDULE_PUBLICATIONS_LIST: ListSchedulePublications(
            series_id="sser_schedclosure001"
        ),
        Capability.SCHEDULE_PUBLICATIONS_READ: ReadSchedulePublication(
            publication_id="spub_schedclosure01"
        ),
        Capability.SCHEDULE_ACTIVITIES_LIST: ListScheduleActivities(
            publication_id="spub_schedclosure01"
        ),
        Capability.SCHEDULE_ACTIVITIES_HISTORY: ReadScheduleActivityHistory(
            schedule_activity_id="sact_schedclosure01"
        ),
        Capability.SCHEDULE_CHANGES_LIST: ListScheduleChanges(
            from_publication_id="spub_schedclosure01", to_publication_id="spub_schedclosure02"
        ),
    }


# ---- every closed surface ---------------------------------------------------------


def _capability_enum(scene: Scene) -> None:
    del scene
    members = list(Capability)
    assert [(member.name, member.value) for member in members[-7:]] == [
        (name, value) for name, value, _, _ in _TABLE
    ]
    # Reports Modernization WP03 declares its five beside `reports.publish`, and
    # WP05b its four custody names after them.
    assert len(members) == 250


def _purpose_enum(scene: Scene) -> None:
    del scene
    members = list(Purpose)
    # Reports Modernization WP03 appends `report_lifecycle` after the two, and
    # WP05b `report_hold` and `report_retention` after it.
    assert [(member.name, member.value) for member in members[-5:-3]] == [
        ("SCHEDULE_IMPORT", "schedule_import"),
        ("SCHEDULE_READ", "schedule_read"),
    ]
    assert members[-3:] == [Purpose.REPORT_LIFECYCLE, Purpose.REPORT_HOLD, Purpose.REPORT_RETENTION]
    assert len(members) == 65


def _operator_only(scene: Scene) -> None:
    del scene
    assert [capability for capability in SEVEN if is_operator_only(capability)] == [IMPORT]


def _purposes(scene: Scene) -> None:
    del scene
    assert permitted_purposes(IMPORT) == frozenset({Purpose.SCHEDULE_IMPORT})
    for capability in READS:
        assert permitted_purposes(capability) == frozenset({Purpose.SCHEDULE_READ}), capability
    for capability in Capability:
        if capability not in SEVEN:
            assert not permitted_purposes(capability) & {
                Purpose.SCHEDULE_IMPORT,
                Purpose.SCHEDULE_READ,
            }, capability


def _writes(scene: Scene) -> None:
    del scene
    assert [capability for capability in SEVEN if is_write_capability(capability)] == [IMPORT]
    assert not is_destructive_capability(IMPORT)


def _scopeless(scene: Scene) -> None:
    del scene
    assert READS <= _SCOPELESS
    assert IMPORT not in _SCOPELESS


def _requested(scene: Scene) -> None:
    commands = _commands(scene)
    with FakeUnitOfWork(scene.world) as unit_of_work:
        for capability, command in commands.items():
            requested = _requested_scope(
                unit_of_work,
                command,  # type: ignore[arg-type]
                (scene.enrollment,),
                principal_id=scene.principal.principal_id,
            )
            expected = (
                frozenset({scene.enrollment.source_id}) if capability is IMPORT else frozenset()
            )
            assert requested == expected, capability


def _command_union(scene: Scene) -> None:
    del scene
    union = {member.capability: member for member in commands_module.Command.__value__.__args__}
    for _, value, command, _ in _TABLE:
        assert union[Capability(value)] is command, value
    by_name = {tool.name: tool for tool in TOOLS}
    for _, value, command, _ in _TABLE:
        assert by_name[value].description == (command.__doc__ or "").strip().splitlines()[0]


def _builders(scene: Scene) -> None:
    del scene
    assert set(SEVEN) <= set(_BUILDERS)


def _handlers(scene: Scene) -> None:
    del scene
    for _, value, _, handler in _TABLE:
        assert _HANDLERS[Capability(value)].__name__ == handler, value


def _safe_details(scene: Scene) -> None:
    del scene
    for name, value in _SAFE_DETAILS.items():
        assert SafeDetail[name].value == value, name


def _remote_write(scene: Scene) -> None:
    del scene
    assert Purpose.SCHEDULE_IMPORT in _WRITE_PURPOSES
    assert Purpose.SCHEDULE_READ not in _WRITE_PURPOSES
    assert is_remote_write(IMPORT)
    assert not any(is_remote_write(capability) for capability in READS)


def _chatllm_policy(scene: Scene) -> None:
    del scene
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v13"
    for capability in READS:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL, capability
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.SCHEDULE
        assert policy.exclusion_rationale is None
    policy = CHATLLM_CAPABILITY_POLICY[IMPORT]
    assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
    assert policy.exclusion_rationale == _IMPORT_RATIONALE


def _chatllm_planes(scene: Scene) -> None:
    del scene
    from apps.cli.remote_mcp import _planes_from_settings

    assert ChatLLMCompositionPlanes.__dataclass_fields__["schedule"].default is False
    url = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"
    assert _planes_from_settings(Settings(database_url=url)).schedule is False
    assert _planes_from_settings(Settings(database_url=url, schedule_enabled=True)).schedule


def _gateway_family(scene: Scene) -> None:
    del scene
    for capability in SEVEN:
        assert feature_label(capability.value) == "schedule", capability
        assert facade_kind(capability) == ("operator" if capability is IMPORT else "read")


def _service_sets(scene: Scene) -> None:
    del scene
    assert frozenset(SEVEN) == _SCHEDULE_CAPABILITIES
    assert READS == _SCHEDULE_READ_CAPABILITIES == SCHEDULE_DATA_NAMES


def _audit_vocabulary(scene: Scene) -> None:
    del scene
    assert {capability.value for capability in SEVEN} <= tables._CURRENT_AUDIT_CAPABILITIES


_SURFACES: Final[dict[str, Callable[[Scene], None]]] = {
    "capability_enum": _capability_enum,
    "purpose_enum": _purpose_enum,
    "operator_only": _operator_only,
    "permitted_purposes": _purposes,
    "write_additive": _writes,
    "scopeless": _scopeless,
    "requested_scope": _requested,
    "command_union": _command_union,
    "builders": _builders,
    "handlers": _handlers,
    "safe_details": _safe_details,
    "remote_write": _remote_write,
    "chatllm_policy": _chatllm_policy,
    "chatllm_planes": _chatllm_planes,
    "gateway_family": _gateway_family,
    "service_sets": _service_sets,
    "audit_vocabulary": _audit_vocabulary,
}


@pytest.mark.parametrize("surface", sorted(_SURFACES))
def test_every_closed_surface_classifies_the_seven(scene: Scene, surface: str) -> None:
    _SURFACES[surface](scene)


def test_import_is_operator_only_write_additive_with_one_purpose() -> None:
    assert is_operator_only(IMPORT)
    assert is_write_capability(IMPORT)
    assert not is_destructive_capability(IMPORT)  # write minus additive
    assert permitted_purposes(IMPORT) == frozenset({Purpose.SCHEDULE_IMPORT})


def test_reads_are_scopeless_and_import_is_not() -> None:
    for capability in sorted(READS):
        assert capability in _SCOPELESS, capability
        assert not is_operator_only(capability) and not is_write_capability(capability)
    assert IMPORT not in _SCOPELESS


def test_import_scope_is_its_own_enrollment_source(scene: Scene) -> None:
    """The source of the caller's own enrollment; another enrollment is empty (denied)."""
    command = _commands(scene)[IMPORT]
    assert isinstance(command, ImportSchedulePublication)
    with FakeUnitOfWork(scene.world) as unit_of_work:
        own = _requested_scope(
            unit_of_work, command, (scene.enrollment,), principal_id=scene.principal.principal_id
        )
        foreign = _requested_scope(
            unit_of_work, command, (), principal_id=scene.principal.principal_id
        )
    assert own == frozenset({scene.enrollment.source_id})
    assert foreign == frozenset()


def _source(module: str) -> str:
    return (ROOT / "src" / "my_pa" / module).read_text(encoding="utf-8")


def test_unchanged_surfaces_are_unchanged() -> None:
    """Contract section 3.12's unchanged rows hold no Schedule name."""
    assert {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    } == _REMOTE_OPERATOR_IDENTITY_CAPABILITIES
    assert not set(SEVEN) & _IDEMPOTENT_REMOTE_CAPABILITIES
    assert not set(SEVEN) & _SERVER_REPLAY_REMOTE_CAPABILITIES
    assert not set(SEVEN) & set(CANONICAL_REMOTE_PURPOSES)
    assert not any("schedule" in family.value for family in RecordEventFamily)
    for module in (
        "bootstrap/relationship_intelligence_profiles.py",
        "bootstrap/knowledge_discovery_profiles.py",
        "application/context/providers.py",
        "contracts/mcp_database_witness.py",
        "domain/record_events.py",
    ):
        text = _source(module)
        assert "SCHEDULE_" not in text and "schedule_" not in text, module


# ---- ChatLLM (section 3.13.1) ----------------------------------------------------


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
    return desired_effective_capabilities(composed_capabilities(IMPLEMENTED, planes))


def test_every_data_required_policy_is_always_composed() -> None:
    """Ruling O-1: `DATA_REQUIRED` means always composed; every gated plane is conditional."""
    required = [
        policy
        for policy in CHATLLM_CAPABILITY_POLICY.values()
        if policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
    ]
    assert required
    for policy in required:
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.ALWAYS, (
            policy.capability
        )


def test_v11_reads_are_data_conditional_under_schedule() -> None:
    for capability in sorted(READS):
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL, capability
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.SCHEDULE
        assert policy.family == capability.value.split(".", 1)[0]
        assert is_chatllm_data_management(capability)
        assert chatllm_grant_purpose(capability) is Purpose.SCHEDULE_READ
    assert {
        policy.capability
        for policy in CHATLLM_CAPABILITY_POLICY.values()
        if policy.composition_prerequisite is ChatLLMCompositionPrerequisite.SCHEDULE
    } == READS


def test_import_is_control_plane_excluded() -> None:
    policy = CHATLLM_CAPABILITY_POLICY[IMPORT]
    assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
    assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
    assert policy.exclusion_rationale == _IMPORT_RATIONALE
    assert not is_chatllm_data_management(IMPORT)


def test_v11_targets() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v13"
    assert len(CHATLLM_CAPABILITY_POLICY) == 250
    # chatllm-data-v12: `reports.publish` (`DATA_REQUIRED`) adds 1 everywhere;
    # chatllm-data-v13: the 5 report management names add 5 everywhere.
    full = _desired(_planes(**_FULL))
    assert len(full) == 170
    assert len(_desired(_planes(constraints=True))) == 104
    with_schedule = _desired(_planes(**_FULL, schedule=True))
    assert len(with_schedule) == 176
    assert with_schedule - full == READS
    assert len(_desired(_planes(**_FULL, lineage=True, program_reporting=True, schedule=True))) == (
        210
    )
    default_all = _planes(constraints=True, lineage=True, program_reporting=True, schedule=True)
    assert len(_desired(default_all)) == 142
    assert len(_every_composition()) == 512


def test_planner_desires_schedule_reads_only_with_the_switch() -> None:
    for planes in _every_composition():
        desired = _desired(planes)
        for capability in READS:
            assert (capability in desired) is planes.schedule, (capability, planes)
        assert IMPORT not in desired, planes
    # The switch alone, with no other plane, plans the 6 reads.
    assert _desired(_planes(schedule=True)) >= READS


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


def test_active_import_grant_is_unexpected_control_plane() -> None:
    planes = _planes(**_FULL, schedule=True)
    composed = composed_capabilities(IMPLEMENTED, planes) | {IMPORT}
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
    diff = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=(*healthy, _grant(IMPORT)),
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert diff.outcomes[IMPORT] is ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
    assert diff.unexpected_control_plane == {IMPORT}
    assert not diff.is_healthy()


# ---- remote and MCP database profiles (sections 3.13.2, 3.13.4) ------------------


_PROFILES: Final[dict[str, dict[str, Any]]] = {
    "default": {},
    "remote_operator": {"relationship_grant_profile": "remote.operator"},
    "compact_operator": {"compact_operator_publication": True},
}


@pytest.mark.parametrize("profile", sorted(_PROFILES))
def test_import_is_never_remote_published(scene: Scene, profile: str) -> None:
    service = build_service(scene.world, scene.providers, schedule_enabled=True)
    assert IMPORT in service.available_capabilities
    published = remote_tool_names(service, writes_enabled=True, **_PROFILES[profile])
    assert IMPORT.value not in published
    # Non-vacuous: the 6 reads are published to the same profile.
    assert {capability.value for capability in READS} <= published


def test_import_is_not_remote_idempotent() -> None:
    assert IMPORT not in _IDEMPOTENT_REMOTE_CAPABILITIES
    assert not is_remote_idempotent(IMPORT)
    by_name = {tool.name: tool for tool in TOOLS}
    annotations = by_name[IMPORT.value].annotations
    assert annotations is not None
    assert (
        annotations.read_only_hint,
        annotations.destructive_hint,
        annotations.idempotent_hint,
    ) == (False, False, False)


def test_schedule_names_join_no_profile_ceiling_or_opt_in() -> None:
    names = {capability.value for capability in SEVEN}
    for ceiling in (
        MCP_PROFILE_READ_CAPABILITIES,
        MCP_PROFILE_WRITE_CAPABILITIES,
        MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
        MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    ):
        assert not set(SEVEN) & set(ceiling)
    assert not names & set(MCP_PROFILE_OPT_IN_CAPABILITY_NAMES)


# ---- the switch (section 3.1) -----------------------------------------------------


def _purpose_of(capability: Capability) -> Purpose:
    (purpose,) = permitted_purposes(capability)
    return purpose


@pytest.mark.parametrize("capability", SEVEN, ids=lambda capability: capability.value)
def test_switch_off_withholds_and_refuses_every_schedule_capability(
    scene: Scene, capability: Capability
) -> None:
    """Off by default: absent everywhere, and the handler answers `unsupported`.

    FAST over the in-memory composition: absent from `available_capabilities`,
    reported `not_implemented` by `capabilities.get`, absent from the MCP tool
    list, and the handler refuses after the authorization audit row `invoke`
    writes before any handler (R7-F09) -- and writes nothing else.
    """
    service = build_service(scene.world, scene.providers)
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
    envelope = service.invoke(
        metadata_for(capability, _purpose_of(capability), scene.principal),
        _commands(scene)[capability],  # type: ignore[arg-type]
        principal=scene.principal,
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.UNSUPPORTED
    assert envelope.result is None
    written = scene.world.audit[audited:]
    assert [event.capability for event in written] == [capability]


def test_every_schedule_handler_asks_the_switch_first() -> None:
    """Each handler's first statement after `del` is `self._schedule_plane()`."""
    for _, value, _, _ in _TABLE:
        function = _HANDLERS[Capability(value)]
        body = ast.parse(inspect.cleandoc("\n" + inspect.getsource(function))).body[0]
        assert isinstance(body, ast.FunctionDef)
        statements = [
            statement
            for statement in body.body
            if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
            and not isinstance(statement, ast.Delete)
        ]
        first = ast.unparse(statements[0])
        assert first == "self._schedule_plane()", (value, first)
