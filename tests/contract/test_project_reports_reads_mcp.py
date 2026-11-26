"""WP4P-S4: the five `project_reports.*` reads at the canonical boundary (FAST).

WP4P-W1 design sections 2.1-2.10 and the Manager's rulings: the 5 names are
declared, dispatched, built and published as reads (`read_only_hint`) under
`project_reports_read` only; scopeless and not operator-only;
`DATA_CONDITIONAL` on the `PROJECT_REPORTS` prerequisite at
`chatllm-data-v18` (AC-15). With `MY_PA_PROJECT_REPORTS_ENABLED` off (the
default) every one is withheld from `capabilities.get` and the tool list and
answers the standard `unsupported`, never an empty result. The measure enum
is frozen from the ruling A1 names and holds no non-additive column (the
PULSE-AC-08 contract). The tool text states that exported values are inert
data, the qualifier, `measure_scope`, that reconciliation judges the whole
version, `changed_fields` / `changed_since_version` on the version's first
line, and the closed answer vocabularies (ruling F1-5). On, the answers
carry their versions; a cursor of another Principal or request is
`conflict` `cursor`; a changed grant set answers `cursor_state:
scope_changed_restart_required`; refusals name only SafeDetail tokens. Every
value is synthetic. The database evidence is
`tests/database/test_project_reports_reads_service.py` and
`tests/database/test_project_reports_reads_wired.py`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, get_args

import pytest
from tests.conftest import DEFAULT_LIMITS, Scene, build_service
from tests.contract.test_transport_parity import document
from tests.project_reports_reads_samples import (
    PROJECT_REPORTS_READ_CAPABILITIES,
    project_reports_payloads,
)
from tests.unit.project_report_reads_scene import (
    RFI_PROJECT,
    ReadsScene,
    build_world,
    fast_scene,
)

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
)
from my_pa.application.commands import (
    PROJECT_REPORTS_MEASURE_NAMES,
    Command,
    CompareProjectReports,
    ProjectReportRecordHistory,
    ProjectReportsCatalog,
    ProjectReportsCoverage,
    QueryProjectReports,
)
from my_pa.application.errors import ErrorCode, InvalidRequestError, SafeDetail
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    PROJECT_REPORTS_DATA_NAMES,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.project_reports.catalogue import VIEW_FIELDS, field_entry
from my_pa.domain.project_reports.model import (
    Additivity,
    FamilyView,
    NotReportableReason,
    VersionPresence,
)

CATALOG: Final = Capability.PROJECT_REPORTS_CATALOG
QUERY: Final = Capability.PROJECT_REPORTS_QUERY
HISTORY: Final = Capability.PROJECT_REPORTS_RECORD_HISTORY
COMPARE: Final = Capability.PROJECT_REPORTS_COMPARE
COVERAGE: Final = Capability.PROJECT_REPORTS_COVERAGE
READS: Final = (CATALOG, QUERY, HISTORY, COMPARE, COVERAGE)
NOW: Final = datetime(2026, 11, 25, 12, tzinfo=UTC)
GRANTS: Final = frozenset((capability, Purpose.PROJECT_REPORTS_READ) for capability in READS)

#: The measure names of ruling A1, frozen here: a measure the catalogue adds or
#: drops changes the published enum and must be reviewed against AC-08.
FROZEN_MEASURES: Final = (
    "buyout_summary.budget_change_line.amount",
    "buyout_summary.budget_line.original_amount",
    "buyout_summary.commitment_co_line.approved_amount_with_markup",
    "buyout_summary.commitment_line.amount",
    "buyout_summary.prime_co_line.approved_amount",
    "by_code.adjustment.amount",
    "by_status.record_count",
    "grouped_by_change.adjustment.amount",
    "linked_to_drawings.record_count",
    "linked_to_drawings.row_count",
    "manpower.manpower.hours",
    "manpower.manpower.total_hours",
    "manpower.manpower.workers",
    "oac.record_count",
    "open_by_vendor.record_count",
    "open_outstanding.record_count",
    "open_outstanding.row_count",
    "recently_closed.record_count",
    "recently_closed.row_count",
    "reconciliation.commitment_co_line.amount",
    "reconciliation.prime_co_line.amount",
    "with_date_closed.record_count",
)


def _tools() -> dict[str, dict[str, Any]]:
    return {tool.name: tool.input_schema["properties"]["payload"] for tool in TOOLS}


def _descriptions() -> dict[str, str]:
    """What a client reads of each tool: its description and its published schema."""
    return {
        tool.name: f"{tool.description or ''} {json.dumps(tool.input_schema)}" for tool in TOOLS
    }


# ---- declaration, policy and publication (AC-15) ---------------------------------------


def test_the_five_are_declared_dispatched_built_and_published_as_reads() -> None:
    assert [c.value for c in READS] == [
        "project_reports.catalog",
        "project_reports.query",
        "project_reports.record_history",
        "project_reports.compare",
        "project_reports.coverage",
    ]
    assert frozenset(READS) == PROJECT_REPORTS_READ_CAPABILITIES == PROJECT_REPORTS_DATA_NAMES
    commands = {member.capability: member for member in get_args(Command.__value__)}
    assert commands[CATALOG] is ProjectReportsCatalog
    assert commands[QUERY] is QueryProjectReports
    assert commands[HISTORY] is ProjectReportRecordHistory
    assert commands[COMPARE] is CompareProjectReports
    assert commands[COVERAGE] is ProjectReportsCoverage
    tools = {tool.name: tool for tool in TOOLS}
    for capability in READS:
        assert _HANDLERS[capability].__name__ == "_project_reports"
        assert capability in _BUILDERS
        assert permitted_purposes(capability) == {Purpose.PROJECT_REPORTS_READ}
        assert capability in _SCOPELESS
        assert not is_write_capability(capability)
        assert not is_operator_only(capability)
        annotations = tools[capability.value].annotations
        assert annotations is not None and annotations.read_only_hint is True
        assert facade_kind(capability) == "read"
        assert feature_label(capability.value) == "project_reports"
    users = {c for c in Capability if Purpose.PROJECT_REPORTS_READ in permitted_purposes(c)}
    assert users == set(READS)
    # No client write: nothing under the purpose writes, and no other name is a
    # project-report capability.
    assert {c for c in Capability if c.value.startswith("project_reports.")} == set(READS)


def test_chatllm_classifies_the_five_conditional_on_project_reports() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v18"
    for capability in READS:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.PROJECT_REPORTS
    base: dict[str, bool] = {
        "managed_documents": False,
        "relationship_intelligence": False,
        "relationship_intelligence_writes": False,
        "relationship_memory": False,
        "constraints": True,
    }
    everything = frozenset(Capability)
    off = composed_capabilities(everything, ChatLLMCompositionPlanes(**base))
    on = composed_capabilities(everything, ChatLLMCompositionPlanes(**base, project_reports=True))
    assert not off & set(READS)
    assert on - off == set(READS)
    # The communications plane alone composes none of them.
    other = composed_capabilities(everything, ChatLLMCompositionPlanes(**base, communications=True))
    assert not other & set(READS)


def test_the_tool_schemas_publish_the_design_bounds() -> None:
    tools = _tools()
    catalog = tools[CATALOG.value]
    assert catalog["required"] == [] and catalog["additionalProperties"] is False
    assert catalog["properties"]["project_ids"]["maxItems"] == 50
    query = tools[QUERY.value]
    assert query["required"] == ["project_id", "record_family"]
    properties = query["properties"]
    assert (properties["limit"]["minimum"], properties["limit"]["maximum"]) == (1, 100)
    assert properties["limit"]["default"] == 25
    assert properties["text"]["maxLength"] == 200
    for name in ("status_classes", "statuses", "identifiers", "group_keys", "measures"):
        assert properties[name]["maxItems"] == 20, name
    assert properties["series_id"]["pattern"] == "^prser_[0-9a-f]{32}$"
    assert properties["date_from"]["format"] == "date"
    history = tools[HISTORY.value]["properties"]
    assert (history["record_ids"]["minItems"], history["record_ids"]["maxItems"]) == (1, 25)
    compare = tools[COMPARE.value]
    assert compare["required"] == ["series_id"]
    limit = compare["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 500, 500)
    # The cursor bound the service enforces, on both paged reads.
    for cursor in (properties["cursor"], compare["properties"]["cursor"]):
        assert (cursor["minLength"], cursor["maxLength"]) == (1, 2048)
    assert set(tools[COVERAGE.value]["properties"]) == {"project_ids", "record_family"}


# ---- AC-08: the measure enum -------------------------------------------------------


def _is_additive_measure(name: str) -> bool:
    """A count of a view, or an additive money/number column of that view."""
    view_name, _, rest = name.partition(".")
    view = FamilyView(view_name)
    if rest in {"record_count", "row_count"}:
        return True
    entry = field_entry(view, rest)
    return entry is not None and entry.additivity is Additivity.ADDITIVE


def test_the_measure_enum_is_frozen_and_holds_no_non_additive_column() -> None:
    """PULSE-AC-08: a non-additive column (a count, a balance, a percent) is never a measure."""
    published = _tools()[QUERY.value]["properties"]["measures"]["items"]["enum"]
    assert tuple(published) == FROZEN_MEASURES == PROJECT_REPORTS_MEASURE_NAMES
    assert all(_is_additive_measure(name) for name in published)
    non_additive = {
        f"{view.value}.{entry.field_key}"
        for view, entries in VIEW_FIELDS.items()
        for entry in entries
        if entry.additivity is Additivity.NON_ADDITIVE
    }
    assert non_additive, "the catalogue declares non-additive columns"
    assert not non_additive & set(published)


# ---- the tool text --------------------------------------------------------------------


def test_the_tool_text_states_inert_data_scope_and_the_closed_vocabularies() -> None:
    descriptions = _descriptions()
    for capability in (CATALOG, QUERY, COMPARE):
        assert "inert data" in descriptions[capability.value], capability
    query = descriptions[QUERY.value]
    for phrase in (
        "measure_scope",
        "reconciliation_scope: version",
        "always judge the whole version",
        "reconciliation_mismatch",
        "qualifier",
    ):
        assert phrase in query, phrase
    # Ruling F1-5: every not-reportable reason a client may meet is named.
    for reason in NotReportableReason:
        assert reason.value in query, reason
    history = descriptions[HISTORY.value]
    for phrase in ("changed_fields", "changed_since_version", "first line"):
        assert phrase in history, phrase
    for presence in VersionPresence:
        assert presence.value in history, presence
    assert "currency_mixed" in descriptions[COMPARE.value]
    assert "filter_semantics_unknown" in descriptions[CATALOG.value]


@pytest.mark.parametrize(
    ("capability", "payload", "detail"),
    [
        (CATALOG, {"project_ids": ["not-a-project"]}, SafeDetail.PROJECT_IDS),
        (CATALOG, {"record_family": "pulses"}, SafeDetail.RECORD_FAMILY),
        (
            QUERY,
            {"project_id": "prj_synreads0001x", "record_family": "x"},
            SafeDetail.RECORD_FAMILY,
        ),
        (
            QUERY,
            {"project_id": "prj_synreads0001x", "record_family": "rfis", "limit": 101},
            SafeDetail.LIMIT,
        ),
        (
            QUERY,
            {"project_id": "prj_synreads0001x", "record_family": "rfis", "text": "x" * 201},
            SafeDetail.TEXT,
        ),
        (
            QUERY,
            {
                "project_id": "prj_synreads0001x",
                "record_family": "rfis",
                "measures": ["oac.observation.count"],
            },
            SafeDetail.MEASURES,
        ),
        (
            QUERY,
            {"project_id": "prj_synreads0001x", "record_family": "rfis", "date_from": "11/1/26"},
            SafeDetail.DATE_FROM,
        ),
        (
            QUERY,
            {"project_id": "prj_synreads0001x", "record_family": "rfis", "cursor": "x" * 2049},
            SafeDetail.CURSOR,
        ),
        (HISTORY, {}, SafeDetail.RECORD_IDS),
        (HISTORY, {"record_ids": ["prrec_synthetic0001"] * 26}, SafeDetail.RECORD_IDS),
        (COMPARE, {"series_id": "prser_nothex"}, SafeDetail.SERIES_ID),
        (COMPARE, {"series_id": "prser_" + "0" * 32, "limit": 501}, SafeDetail.LIMIT),
        (COVERAGE, {"project_ids": ["prj_synreads0001x"] * 2}, SafeDetail.PROJECT_IDS),
    ],
)
def test_a_payload_outside_its_bounds_is_refused_naming_only_its_field(
    capability: Capability, payload: Mapping[str, Any], detail: SafeDetail
) -> None:
    """Refused at normalization, before any switch or read, with one SafeDetail token."""
    with pytest.raises(InvalidRequestError) as raised:
        normalize(capability.value, document(capability, "prn_synreads0001", payload))
    assert tuple(raised.value.safe_details) == (detail,)
    rendered = repr(raised.value) + str(raised.value)
    for value in ("x" * 40, "not-a-project", "pulses", "11/1/26", "nothex"):
        assert value not in rendered


# ---- the switch -----------------------------------------------------------------------------


def test_switch_off_withholds_the_five_and_answers_unsupported(scene: Scene) -> None:
    """The standard disabled refusal, not an empty result; absent from every list."""
    service = build_service(scene.world, scene.providers)
    assert not set(READS) & service.available_capabilities
    manifest = _invoke(service, scene.principal, Capability.CAPABILITIES_GET, {})
    assert manifest.error is None and manifest.result is not None
    availability = {
        entry["name"]: entry["availability"]
        for entry in manifest.result["manifest"]["capabilities"]
    }
    assert {availability[c.value] for c in READS} == {"not_implemented"}
    for capability, payload in project_reports_payloads("switch").items():
        answer = _invoke(service, scene.principal, capability, payload)
        assert answer.error is not None
        assert answer.error.code is ErrorCode.UNSUPPORTED, capability
        # And a transport dispatching straight into the handler meets the same.
        with pytest.raises(Exception) as raised:
            _HANDLERS[capability](service, None, None, None)
        assert type(raised.value).__name__ == "UnsupportedError"


def test_switch_on_serves_the_five() -> None:
    reads, _ingest, _world = fast_scene()
    on = _service(reads, enabled=True)
    off = _service(reads, enabled=False)
    assert set(READS) <= on.available_capabilities
    assert on.available_capabilities - off.available_capabilities == set(READS)


# ---- answers with the switch on ---------------------------------------------------------


@pytest.fixture
def reads_world() -> ReadsScene:
    built, _ingest, _world = fast_scene()
    build_world(built)
    return built


def _principal(scene: ReadsScene) -> Principal:
    return Principal(scene.principal, PrincipalKind.OPERATOR, authenticated=True)


def test_each_read_answers_through_the_service(reads_world: ReadsScene) -> None:
    service = _service(reads_world, enabled=True)
    me = _principal(reads_world)
    catalog = _invoke(service, me, CATALOG, {"project_ids": [RFI_PROJECT[1]]}, grants=GRANTS)
    assert catalog.error is None and catalog.result is not None
    (project,) = catalog.result["projects"]
    series = [s["series_id"] for s in project["series"]]
    assert series and all(s.startswith("prser_") for s in series)
    query = _invoke(
        service,
        me,
        QUERY,
        {"project_id": RFI_PROJECT[1], "record_family": "rfis", "limit": 2},
        grants=GRANTS,
    )
    assert query.error is None and query.result is not None
    assert query.result["rows"] and query.result["versions"]
    assert "qualifiers" in query.result and query.result["cursor_state"] is None
    history = _invoke(
        service,
        me,
        HISTORY,
        {"project_id": RFI_PROJECT[1], "record_family": "rfis", "identity_key": "rfi:GMP-174"},
    )
    assert history.error is None and history.result is not None
    (record,) = history.result["records"]
    assert all("changed_since_version" in o for o in record["observations"])
    compare = _invoke(service, me, COMPARE, {"series_id": series[0]}, grants=GRANTS)
    assert compare.error is None and compare.result is not None
    coverage = _invoke(service, me, COVERAGE, {"project_ids": [RFI_PROJECT[1]]})
    assert coverage.error is None and coverage.result is not None


def test_a_query_cursor_binds_to_its_principal_request_and_grants(reads_world: ReadsScene) -> None:
    service = _service(reads_world, enabled=True)
    me = _principal(reads_world)
    request = {"project_id": RFI_PROJECT[1], "record_family": "rfis", "limit": 1}
    first = _invoke(service, me, QUERY, request, grants=GRANTS)
    assert first.error is None and first.result is not None
    cursor = first.result["next_cursor"]
    assert cursor is not None
    assert first.disclosure is not None
    assert first.disclosure.truncation.next_cursor == cursor
    following = _invoke(service, me, QUERY, {**request, "cursor": cursor}, grants=GRANTS)
    assert following.error is None and following.result is not None
    stranger = Principal("prn_synreadsstranger1", PrincipalKind.OPERATOR, authenticated=True)
    for principal, payload in (
        (stranger, {**request, "cursor": cursor}),
        (me, {**request, "text": "other", "cursor": cursor}),
    ):
        refused = _invoke(service, principal, QUERY, payload, grants=GRANTS)
        assert refused.error is not None
        assert refused.error.code is ErrorCode.CONFLICT
        assert list(refused.error.safe_details) == [SafeDetail.CURSOR.value]
        assert cursor not in refused.model_dump_json()
    # A changed grant set: the scope-changed answer, with nothing else.
    narrowed = frozenset({(QUERY, Purpose.PROJECT_REPORTS_READ)})
    restart = _invoke(service, me, QUERY, {**request, "cursor": cursor}, grants=narrowed)
    assert restart.error is None and restart.result is not None
    assert restart.result["cursor_state"] == "scope_changed_restart_required"
    assert restart.result["rows"] == []
    assert restart.result["next_cursor"] is None


def test_a_foreign_project_is_not_found_as_an_unknown_one(reads_world: ReadsScene) -> None:
    service = _service(reads_world, enabled=True)
    stranger = Principal("prn_synreadsstranger1", PrincipalKind.OPERATOR, authenticated=True)
    answers = [
        _invoke(service, principal, QUERY, {"project_id": project, "record_family": "rfis"})
        for principal, project in (
            (stranger, RFI_PROJECT[1]),
            (_principal(reads_world), "prj_synreadsunknown1"),
        )
    ]
    for answer in answers:
        assert answer.error is not None
        assert answer.error.code is ErrorCode.NOT_FOUND
    assert answers[0].error is not None and answers[1].error is not None
    assert answers[0].error.safe_details == answers[1].error.safe_details


# ---- helpers ------------------------------------------------------------------------------


def _service(scene: ReadsScene, *, enabled: bool) -> ApplicationService:
    return ApplicationService(
        unit_of_work=scene.unit,
        limits=DEFAULT_LIMITS,
        clock=lambda: NOW,
        project_reports_enabled=enabled,
    )


def _invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
    *,
    grants: frozenset[tuple[Capability, Purpose | None]] | None = None,
) -> ResponseEnvelope:
    metadata, command = normalize(
        capability.value, document(capability, principal.principal_id, payload)
    )
    return service.invoke(metadata, command, principal=principal, capability_grants=grants)
