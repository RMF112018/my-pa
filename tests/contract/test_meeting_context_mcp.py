"""WP5-S5: `meetings.context.read` at the canonical boundary (FAST).

Communications contract sections 15-16, WP5-W1 design sections 3.1-3.7 and
3.15, Manager rulings D2, D9, D-6 and B-1. The name is declared, dispatched,
built and published as a read (`read_only_hint`) under `communications_read`
only (ruling D2: no purpose of its own); scopeless and not operator-only;
`DATA_CONDITIONAL` on the existing `COMMUNICATIONS` prerequisite at
`chatllm-data-v21` (v20 plus this one name; with the switch off, exactly v20).
It has no switch of its own: with `MY_PA_COMMUNICATIONS_ENABLED` off (the
default) it is withheld from `capabilities.get`, the tool list and the remote
publication and answers the standard `unsupported` -- also when only the
project-report switch is on (ruling Q4) -- never an empty result. On, an
unknown or foreign Meeting is `not_found` and never fails the batch, and the
project-report switch is passed through to the `pulse` section.

Every statement a client must read lives in the published field descriptions
(MCP publishes only the docstring's first line; the WP4P C-1 lesson, ruling
D-6): the inert-data statement, every section, state and missing code, that
`matched_by` explains each row, and that a snippet is a 300-character derived
prefix, never a raw body. Every value is synthetic. The database evidence of
the wired read is `tests/database/test_meeting_context_wired.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, get_args

import pytest
from tests.conftest import Scene, World, build_service
from tests.contract.test_transport_parity import document
from tests.meeting_context_samples import MEETING_CONTEXT_CAPABILITIES, meeting_context_payloads
from tests.unit.communications_ingest_fakes import IngestUnitOfWork, IngestWorld
from tests.unit.project_report_reads_scene import RFI_PROJECT, build_world, fast_scene
from tests.unit.project_reports_reads_service_cases import extend_world, service

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label
from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.adapters.remote_request import resolve_remote_purpose
from my_pa.application import meeting_context
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.commands import Command, ReadMeetingContext
from my_pa.application.communications_search import Flags, Lane, LaneState, RangeCoverageView
from my_pa.application.errors import ErrorCode, InvalidRequestError, SafeDetail, UnsupportedError
from my_pa.application.meeting_context import (
    CONTEXT_TIERS,
    RECALL_NOTES,
    CommunicationsContext,
    ContextAttendee,
    ContextIdentifierInput,
    ContextInputs,
    ContextMessage,
    ContextState,
    ContextVersions,
    MatchReason,
    MeetingContext,
    MeetingContextAnswer,
    MissingInput,
    ProjectNumberUse,
    ProviderBindingState,
    PulseContext,
    PulseState,
    RfiSource,
    SelfAddresses,
    SelfAddressState,
    _pulse,
    context_payload,
)
from my_pa.application.meetings import MeetingApplication
from my_pa.application.project_reports_reads import (
    AVAILABILITY_REASONS,
    MEASURE_VALUE_STATES,
    RFI_MATCH_STATES,
    ContextSummary,
    RfiNumberMatch,
)
from my_pa.application.service import _COMMUNICATIONS_CAPABILITIES, _HANDLERS, ApplicationService
from my_pa.contracts.mcp_database_profiles import (
    MCP_PROFILE_OPT_IN_CAPABILITY_NAMES,
    MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
    MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    MCP_PROFILE_READ_CAPABILITIES,
    MCP_PROFILE_WRITE_CAPABILITIES,
)
from my_pa.contracts.ports import MeetingContextInput
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.meetings import MeetingProviderBindingView
from my_pa.domain.communications.corpus import Interval
from my_pa.domain.communications.coverage import RangeState
from my_pa.domain.communications.model import (
    BodyState,
    CoverageState,
    FolderRole,
    LaneVerification,
    SourceLane,
)
from my_pa.domain.communications.search_text import SearchTextFlag
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    COMMUNICATIONS_DATA_NAMES,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.meeting.context import ContextTextSource, ContextWindow
from my_pa.domain.meeting.model import (
    AttendeeResponseStatus,
    MeetingCreateRequest,
    MeetingStatus,
    normalize_attendee,
)
from my_pa.domain.meeting_sync.model import ProviderBindingState as ProviderState
from my_pa.domain.meeting_sync.model import ProviderEventIdFormat
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.project_reports.catalogue import StatusBasis
from my_pa.domain.project_reports.model import (
    CompletenessClass,
    DerivationState,
    FamilyView,
    FilterSemantics,
    NotReportableReason,
    QuarantineReason,
    RecordFamily,
    ReportQualifier,
    StatusClass,
)
from my_pa.domain.project_reports.reads import MeasureScope

CONTEXT: Final = Capability.MEETINGS_CONTEXT_READ
P: Final = "prn_ctxmcpfast00001"
OTHER: Final = "prn_ctxmcpstranger01"
NOW: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
START: Final = NOW - timedelta(hours=3)
OPERATOR: Final = Principal(P, PrincipalKind.OPERATOR, authenticated=True)
STRANGER: Final = Principal(OTHER, PrincipalKind.OPERATOR, authenticated=True)
GRANTS: Final = frozenset({(CONTEXT, Purpose.COMMUNICATIONS_READ)})
UNKNOWN: Final = "mtg_" + "0" * 26
ROOT: Final = Path(__file__).resolve().parents[2]
DIGESTS: Final = ROOT / "tests" / "contract" / "v1_payload_digests.json"


def _descriptions() -> dict[str, str]:
    """What a client reads of a tool: its description and its published schema."""
    return {
        tool.name: f"{tool.description or ''} {json.dumps(tool.input_schema)}" for tool in TOOLS
    }


def _payload_schema() -> Mapping[str, Any]:
    (tool,) = [tool for tool in TOOLS if tool.name == CONTEXT.value]
    schema: Mapping[str, Any] = tool.input_schema["properties"]["payload"]
    return schema


# ---- declaration, policy and publication --------------------------------------------------


def test_the_name_is_declared_dispatched_built_and_published_as_a_read() -> None:
    assert CONTEXT.value == "meetings.context.read"
    assert frozenset({CONTEXT}) == MEETING_CONTEXT_CAPABILITIES
    commands = {member.capability: member for member in get_args(Command.__value__)}
    assert commands[CONTEXT] is ReadMeetingContext
    assert _HANDLERS[CONTEXT].__name__ == "_meetings_context"
    assert CONTEXT in _BUILDERS
    # Ruling D2: the communications read purpose, reused; no purpose of its own.
    assert permitted_purposes(CONTEXT) == {Purpose.COMMUNICATIONS_READ}
    assert not [p for p in Purpose if "meeting_context" in p.value or "context_read" in p.value]
    assert CONTEXT in _SCOPELESS
    assert not is_write_capability(CONTEXT)
    assert not is_destructive_capability(CONTEXT)
    assert not is_operator_only(CONTEXT)
    (tool,) = [tool for tool in TOOLS if tool.name == CONTEXT.value]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.destructive_hint is False
    assert facade_kind(CONTEXT) == "read"
    assert feature_label(CONTEXT.value) == "meetings"
    # Ruling D2: no switch of its own -- withheld with the communications reads.
    assert CONTEXT in _COMMUNICATIONS_CAPABILITIES
    assert _COMMUNICATIONS_CAPABILITIES == COMMUNICATIONS_DATA_NAMES


def test_no_mcp_database_profile_names_it() -> None:
    """The restricted MCP database roles hold no privilege on the tables it reads."""
    for ceiling in (
        MCP_PROFILE_READ_CAPABILITIES,
        MCP_PROFILE_WRITE_CAPABILITIES,
        MCP_PROFILE_OPT_IN_READ_CAPABILITIES,
        MCP_PROFILE_OPT_IN_WRITE_CAPABILITIES,
    ):
        assert CONTEXT not in set(ceiling)
    assert CONTEXT.value not in set(MCP_PROFILE_OPT_IN_CAPABILITY_NAMES)


# ---- ChatLLM chatllm-data-v21 ----------------------------------------------------------------


def test_chatllm_classifies_it_conditional_on_communications_at_v21() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v21"
    policy = CHATLLM_CAPABILITY_POLICY[CONTEXT]
    assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
    assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.COMMUNICATIONS
    assert policy.family == "meetings"
    assert CONTEXT in COMMUNICATIONS_DATA_NAMES
    # No prerequisite of its own (ruling D2).
    assert not [p for p in ChatLLMCompositionPrerequisite if "MEETING" in p.value]


@pytest.mark.parametrize("others", [False, True])
@pytest.mark.parametrize("project_reports", [False, True])
def test_with_the_switch_off_v21_desires_exactly_the_v20_set(
    others: bool, project_reports: bool
) -> None:
    """v21 is v20 plus this one name: off desires exactly v20; on adds exactly it.

    The other plane flags (the project-report switch among them) are varied so
    the equality holds whatever v20 itself composes; the project-report switch
    alone never adds it (ruling Q4).
    """
    planes: dict[str, bool] = {
        "managed_documents": others,
        "relationship_intelligence": others,
        "relationship_intelligence_writes": others,
        "relationship_memory": others,
        "constraints": True,
        "knowledge_assertions": others,
        "lineage": others,
        "program_reporting": others,
        "schedule": others,
        "schedule_scenarios": others,
        "files_workspace": others,
        "schedule_p6": others,
        "project_reports": project_reports,
    }
    implemented = frozenset(CHATLLM_CAPABILITY_POLICY)
    v20 = implemented - {CONTEXT}

    def desired(names: frozenset[Capability], communications: bool) -> frozenset[Capability]:
        composed = composed_capabilities(
            names, ChatLLMCompositionPlanes(**planes, communications=communications)
        )
        return frozenset(desired_effective_capabilities(composed))

    off = desired(implemented, communications=False)
    on = desired(implemented, communications=True)
    assert CONTEXT not in off
    assert off == desired(v20, communications=False)
    assert on - desired(v20, communications=True) == {CONTEXT}
    assert on == off | COMMUNICATIONS_DATA_NAMES


def test_the_remote_planner_reads_the_communications_switch() -> None:
    from apps.cli.remote_mcp import _planes_from_settings

    from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings

    url = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"
    implemented = frozenset(CHATLLM_CAPABILITY_POLICY)

    def desired(settings: Settings) -> frozenset[Capability]:
        planes = _planes_from_settings(settings)
        return frozenset(desired_effective_capabilities(composed_capabilities(implemented, planes)))

    assert CONTEXT not in desired(Settings(database_url=url))
    assert CONTEXT not in desired(Settings(database_url=url, project_reports_enabled=True))
    assert CONTEXT in desired(Settings(database_url=url, communications_enabled=True))


# ---- the published schema and bounds --------------------------------------------------------


def test_the_tool_schema_publishes_the_design_bounds() -> None:
    schema = _payload_schema()
    assert schema["required"] == ["meeting_ids"]
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    # No cursor: a cut Meeting says `truncated`; the full set is communications.search's.
    assert set(properties) == {"meeting_ids", "lookback_days", "per_meeting_limit"}
    ids = properties["meeting_ids"]
    assert (ids["type"], ids["minItems"], ids["maxItems"], ids["uniqueItems"]) == (
        "array",
        1,
        10,
        True,
    )
    assert ids["items"]["pattern"] == "^mtg_[A-Za-z0-9]{8,64}$"
    lookback = properties["lookback_days"]
    assert (lookback["minimum"], lookback["maximum"], lookback["default"]) == (1, 90, 14)
    limit = properties["per_meeting_limit"]
    assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 15)


def test_the_tool_digest_is_recorded_as_new() -> None:
    """`regen --accept-new` recorded the new tool once; nothing else moved."""
    digests = json.loads(DIGESTS.read_text(encoding="utf-8"))
    assert CONTEXT.value in digests["tools"]
    added = [
        entry
        for entry in digests["ledger"]
        if entry["kind"] == "added" and CONTEXT.value in entry.get("names", ())
    ]
    assert len(added) == 1
    assert added[0]["names"] == [CONTEXT.value]
    assert added[0]["section"] == "tools"


def _sample_answer() -> MeetingContextAnswer:
    """A synthetic answer that renders every field: each pulse state and every list filled."""
    scene, *_ = fast_scene()
    build_world(scene)
    extend_world(scene)
    project = RFI_PROJECT[1]
    summary = service(scene).project_summary(scene.principal, project)
    assert summary.counts and summary.versions
    match = RfiNumberMatch(None, 174, "ambiguous_prefix", (("A", 174, "rec_x"), (None, 174, None)))
    available = _pulse(
        ContextSummary(project, summary.availability, summary, (match,)),
        ((174, RfiSource.MEETING),),
        1,
    )
    unavailable = PulseContext(PulseState.UNAVAILABLE, reason="unbound", project_id=project)
    window = ContextWindow(START - timedelta(days=14), START, clipped_to_now=False)
    span = Interval(START - timedelta(days=2), START - timedelta(days=1))
    coverage = RangeCoverageView(
        state="partial",
        start=window.start,
        end=window.end,
        intervals=(span,),
        intervals_total=1,
        gaps=(span,),
        gaps_total=1,
        freshness_seconds=1,
        earliest_covered=span.start,
        latest_covered=span.end,
        snapshot_count=1,
        lanes=(LaneState("folder", "inbox", "mail", "complete", latest_authorized=True),),
    )
    message = ContextMessage(
        message_id="cmsg_ctxsample000001",
        message_time=START,
        subject="Synthetic",
        sender_address="sender.sample@example.test",
        conversation_id=None,
        conversation_hits=1,
        has_attachments=False,
        body_state="present",
        tier=1,
        participant_overlap=1,
        rank=0,
        matched_by=(MatchReason.PARTICIPANTS,),
        matched_attendee_ids=("mat_sample",),
        matched_identifiers=("rfi:174",),
        snippet="synthetic",
        search_text_version="comms_search_text_v2",
        flags=Flags(False, False, False, False, ("text_capped",)),
        lanes=(Lane("inbox", "verified"),),
    )
    communications = CommunicationsContext(
        state=ContextState.OK,
        window=window,
        inputs=ContextInputs(
            attendee_keys=1,
            attendees_without_address=0,
            self_attendees=0,
            identifiers=(ContextIdentifierInput("rfi:174", ("title",)),),
            identifier_scan_truncated=False,
            bridge_truncated=False,
            title_terms=1,
            project_number=ProjectNumberUse.USED,
        ),
        missing=(MissingInput.PROVIDER_UNBOUND,),
        matched_total=1,
        truncated=False,
        messages=(message,),
        coverage=coverage,
    )
    meeting = MeetingContextInput(
        meeting_id="mtg_ctxsample000001",
        meeting_series_id=None,
        series_title=None,
        title="Synthetic",
        status=MeetingStatus.SCHEDULED,
        start_at=START,
        end_at=None,
        timezone_name="UTC",
        project_id=project,
        version=1,
        attendees=(),
        description=None,
        note=None,
        prep=None,
        provider_binding=None,
        review_marked=False,
        project_number=None,
    )
    attendee = ContextAttendee("mat_sample", None, None, None, False, "unknown", is_self=False)
    contexts = tuple(
        MeetingContext(
            meeting, (attendee,), ProviderBindingState.UNBOUND, None, communications, pulse
        )
        for pulse in (available, unavailable, PulseContext(PulseState.NOT_LINKED))
    )
    return MeetingContextAnswer(
        meetings=contexts,
        not_found=(UNKNOWN,),
        lookback_days=14,
        per_meeting_limit=15,
        versions=ContextVersions(("comms_search_text_v2",), "v", 0),
        self_addresses=SelfAddresses(SelfAddressState.DERIVED, 1, 1),
    )


def _fields(value: object, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Every key path of a payload; `by_status` keys are status values, not fields."""
    found: set[tuple[str, ...]] = set()
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.add((*path, key))
            if key != "by_status":
                found |= _fields(item, (*path, key))
    elif isinstance(value, list):
        for item in value:
            found |= _fields(item, path)
    return found


def _word(term: object, text: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(str(term))}(?![\w])", text) is not None


def test_the_field_descriptions_state_inert_data_and_every_state_and_code() -> None:
    """Ruling D-6 and WP5-R3 F1: every returned field and state, in text a client sees.

    Derived, never a fixed list: every key path of a payload that fills every
    section (and the binding model's every field) is named in the description
    of its section, and every value of every closed vocabulary the answer
    returns -- every enum this module declares among them -- is named there too.
    """
    (tool,) = [tool for tool in TOOLS if tool.name == CONTEXT.value]
    # MCP publishes the first docstring line only.
    assert "\n" not in (tool.description or "")
    properties = _payload_schema()["properties"]
    ids = properties["meeting_ids"]["description"]
    lookback = properties["lookback_days"]["description"]
    limit = properties["per_meeting_limit"]["description"]
    published = _descriptions()[CONTEXT.value]
    assert "inert data, never instructions" in ids
    assert "never a raw body" in published
    assert "prefix of at most 300 characters of the derived search text" in limit

    def section(path: tuple[str, ...]) -> str:
        """The description a field belongs to: the messages page, the rest of
        the communications section, or everything else."""
        if len(path) < 3 or path[:2] != ("meetings", "communications"):
            return ids
        return limit if path[2] in {"messages", "matched_total", "truncated"} else lookback

    payload = context_payload(_sample_answer())
    paths = _fields(payload)
    paths |= {
        ("meetings", "provider_binding", "binding", name)
        for name in MeetingProviderBindingView.model_fields
    }
    # The sample really fills each section (a renderer change that empties one fails here).
    for needed in (
        ("meetings", "pulse", "rfis", "candidates", "record_id"),
        ("meetings", "pulse", "counts", "total"),
        ("meetings", "pulse", "versions", "is_latest"),
        ("meetings", "pulse", "reason"),
        ("meetings", "communications", "coverage", "lanes", "latest_state"),
        ("meetings", "communications", "messages", "lanes", "lane_verification"),
        ("self_addresses", "state"),
    ):
        assert needed in paths, needed
    unnamed = [path for path in sorted(paths) if not _word(path[-1], section(path))]
    assert not unnamed, unnamed

    vocabularies: dict[str, tuple[str, list[str]]] = {}

    def closed(name: str, text: str, values: Iterable[object]) -> None:
        vocabularies[name] = (text, [str(getattr(v, "value", v)) for v in values])

    own = {
        value
        for value in vars(meeting_context).values()
        if isinstance(value, type)
        and issubclass(value, StrEnum)
        and value.__module__ == meeting_context.__name__
    }
    placed = {
        ContextState: lookback,
        MissingInput: lookback,
        ProjectNumberUse: lookback,
        MatchReason: limit,
        ProviderBindingState: ids,
        PulseState: ids,
        RfiSource: ids,
        SelfAddressState: ids,
    }
    # A new enum of the context answer must be placed (and so published) here.
    assert own == set(placed), own ^ set(placed)
    for enum, text in placed.items():
        closed(enum.__name__, text, enum)
    for enum in (
        MeetingStatus,
        AttendeeResponseStatus,
        ProviderState,
        ProviderEventIdFormat,
        ReportQualifier,
        NotReportableReason,
        MeasureScope,
        StatusBasis,
        StatusClass,
        RecordFamily,
        FamilyView,
        FilterSemantics,
        CompletenessClass,
        DerivationState,
        QuarantineReason,
    ):
        closed(enum.__name__, ids, enum)
    closed("AVAILABILITY_REASONS", ids, AVAILABILITY_REASONS)
    closed("RFI_MATCH_STATES", ids, RFI_MATCH_STATES)
    closed("MEASURE_VALUE_STATES", ids, MEASURE_VALUE_STATES)
    closed("RECALL_NOTES", ids, RECALL_NOTES)
    for enum in (ContextTextSource, RangeState, FolderRole, SourceLane, CoverageState):
        closed(enum.__name__, lookback, enum)
    for enum in (BodyState, FolderRole, LaneVerification, SearchTextFlag):
        closed(f"{enum.__name__} (messages)", limit, enum)
    # What the sample's counts state of themselves: their basis and unit.
    meetings: list[dict[str, Any]] = payload["meetings"]  # type: ignore[assignment]
    counts = [entry for context in meetings for entry in context["pulse"].get("counts", ())]
    closed("count basis and unit", ids, {c[k] for c in counts for k in ("basis", "unit")})
    unstated = [
        (name, value)
        for name, (text, values) in vocabularies.items()
        for value in values
        if not _word(value, text)
    ]
    assert not unstated, unstated
    # Each tier is stated with its meaning.
    for tier in CONTEXT_TIERS:
        assert f"{tier} (" in limit, tier
    assert re.search(r"tier: 1 \(", limit)


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"meeting_ids": []}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": [f"mtg_bounds{n:08d}" for n in range(11)]}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": ["mtg_boundsdup00001", "mtg_boundsdup00001"]}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": ["not-an-id"]}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": ["mser_boundsseries01"]}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": [7]}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": "mtg_boundsstring01"}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": [UNKNOWN], "lookback_days": 0}, SafeDetail.LOOKBACK_DAYS),
        ({"meeting_ids": [UNKNOWN], "lookback_days": 91}, SafeDetail.LOOKBACK_DAYS),
        ({"meeting_ids": [UNKNOWN], "lookback_days": True}, SafeDetail.LOOKBACK_DAYS),
        ({"meeting_ids": [UNKNOWN], "lookback_days": "7"}, SafeDetail.LOOKBACK_DAYS),
        ({"meeting_ids": [UNKNOWN], "per_meeting_limit": 0}, SafeDetail.PER_MEETING_LIMIT),
        ({"meeting_ids": [UNKNOWN], "per_meeting_limit": 51}, SafeDetail.PER_MEETING_LIMIT),
        ({"meeting_ids": [UNKNOWN], "per_meeting_limit": 2.5}, SafeDetail.PER_MEETING_LIMIT),
    ],
)
def test_a_payload_outside_its_bounds_is_refused_naming_only_its_field(
    payload: Mapping[str, Any], detail: SafeDetail
) -> None:
    """Refused at normalization, before any switch or read, with one SafeDetail token."""
    with pytest.raises(InvalidRequestError) as raised:
        normalize(CONTEXT.value, document(CONTEXT, P, payload))
    assert tuple(raised.value.safe_details) == (detail,)
    rendered = repr(raised.value) + str(raised.value)
    for value in ("not-an-id", "mser_boundsseries01", "mtg_boundsdup00001"):
        assert value not in rendered


def test_a_missing_meeting_ids_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        normalize(CONTEXT.value, document(CONTEXT, P, {"lookback_days": 7}))


def test_ten_ids_and_the_defaults_normalize() -> None:
    ids = [f"mtg_bounds{n:08d}" for n in range(10)]
    _, command = normalize(CONTEXT.value, document(CONTEXT, P, {"meeting_ids": ids}))
    assert isinstance(command, ReadMeetingContext)
    assert command.meeting_ids == tuple(ids)
    assert (command.lookback_days, command.per_meeting_limit) == (14, 15)


# ---- the switch -------------------------------------------------------------------------------


def test_switch_off_withholds_it_and_answers_unsupported(scene: Scene) -> None:
    """Ruling D2: the standard disabled refusal, not an empty result; absent from every list."""
    service = build_service(scene.world, scene.providers)
    assert CONTEXT not in service.available_capabilities
    manifest = _invoke(service, scene.principal, Capability.CAPABILITIES_GET, {})
    assert manifest.error is None and manifest.result is not None
    availability = {
        entry["name"]: entry["availability"]
        for entry in manifest.result["manifest"]["capabilities"]
    }
    assert availability[CONTEXT.value] == "not_implemented"
    assert CONTEXT.value not in {
        tool.name for tool in published_tools(service, authenticated_client_present=True)
    }
    assert CONTEXT.value not in remote_tool_names(service, writes_enabled=True)
    audited = len(scene.world.audit)
    payload = meeting_context_payloads("switch")[CONTEXT]
    answer = _invoke(service, scene.principal, CONTEXT, payload)
    assert answer.error is not None
    assert answer.error.code is ErrorCode.UNSUPPORTED
    # Refused after the authorization audit, as every withheld name is.
    assert [event.capability for event in scene.world.audit[audited:]] == [CONTEXT]
    # And a transport dispatching straight into the handler meets the same.
    with pytest.raises(UnsupportedError):
        _HANDLERS[CONTEXT](service, None, None, None)  # type: ignore[arg-type]


def test_the_project_report_switch_alone_never_serves_it() -> None:
    """Ruling Q4: not offered with only the PULSE switch on."""
    service = _service(IngestWorld(), World(), communications=False, project_reports=True)
    assert CONTEXT not in service.available_capabilities
    answer = _invoke(service, OPERATOR, CONTEXT, {"meeting_ids": [UNKNOWN]}, grants=GRANTS)
    assert answer.error is not None and answer.error.code is ErrorCode.UNSUPPORTED
    with pytest.raises(UnsupportedError):
        _HANDLERS[CONTEXT](service, None, None, None)  # type: ignore[arg-type]


def test_switch_on_serves_it_with_the_communications_reads() -> None:
    on = _service(IngestWorld(), World(), communications=True)
    off = _service(IngestWorld(), World(), communications=False)
    assert CONTEXT in on.available_capabilities
    assert on.available_capabilities - off.available_capabilities == COMMUNICATIONS_DATA_NAMES
    published = {tool.name for tool in published_tools(on, authenticated_client_present=True)}
    assert CONTEXT.value in published
    # Published remotely as a read; the remote boundary stamps its one purpose
    # for a client holding its grant and refuses one that does not.
    assert CONTEXT.value in remote_tool_names(on, writes_enabled=False)
    assert resolve_remote_purpose(CONTEXT, GRANTS) is Purpose.COMMUNICATIONS_READ
    with pytest.raises(UnsupportedError):
        resolve_remote_purpose(
            CONTEXT, frozenset({(Capability.COMMUNICATIONS_SEARCH, Purpose.COMMUNICATIONS_READ)})
        )


# ---- policy: closed to everyone but the operator's own reads ---------------------------------


@pytest.mark.parametrize(
    "kind", [PrincipalKind.LOCAL_MODEL_GATEWAY, PrincipalKind.CLOUD_MODEL_PROVIDER]
)
def test_a_non_authoritative_principal_is_denied_before_any_read(kind: PrincipalKind) -> None:
    world = IngestWorld()
    service = _service(world, World(), communications=True)
    model = Principal(P, kind, authenticated=True)
    answer = _invoke(service, model, CONTEXT, {"meeting_ids": [UNKNOWN]})
    assert answer.error is not None and answer.error.code is ErrorCode.DENIED
    assert answer.result is None
    assert world.context_calls == []


def test_an_unauthenticated_principal_is_denied() -> None:
    world = IngestWorld()
    service = _service(world, World(), communications=True)
    anonymous = Principal(P, PrincipalKind.OPERATOR, authenticated=False)
    answer = _invoke(service, anonymous, CONTEXT, {"meeting_ids": [UNKNOWN]})
    assert answer.error is not None and answer.error.code is ErrorCode.DENIED
    assert answer.result is None


@pytest.mark.parametrize(
    "purpose", [Purpose.MEETING_READ, Purpose.PROJECT_REPORTS_READ, Purpose.STATUS_OBSERVATION]
)
def test_any_other_purpose_is_denied(purpose: Purpose) -> None:
    service = _service(IngestWorld(), World(), communications=True)
    metadata, command = normalize(
        CONTEXT.value,
        {**document(CONTEXT, P, {"meeting_ids": [UNKNOWN]}), "purpose": purpose.value},
    )
    answer = service.invoke(metadata, command, principal=OPERATOR)
    assert answer.error is not None and answer.error.code is ErrorCode.DENIED


# ---- answers with the switch on ---------------------------------------------------------------


def _meeting(
    meetings: World, mail: IngestWorld, principal_id: str, n: int, **fields: object
) -> str:
    request = MeetingCreateRequest(
        title=f"Synthetic coordination {n}",
        start_at=START,
        timezone_name="UTC",
        attendees=(normalize_attendee(email=f"attendee{n}.ctx@example.test"),),
        **fields,  # type: ignore[arg-type]
    )
    created = MeetingApplication().create_meeting(
        IngestUnitOfWork(mail, meetings=meetings), principal_id, request, f"ctxmcp-{n}", NOW
    )
    return created.meeting.meeting_id


def test_an_answer_lists_unknown_and_foreign_meetings_in_not_found_and_never_fails() -> None:
    mail, meetings = IngestWorld(), World()
    mine = _meeting(meetings, mail, P, 1)
    theirs = _meeting(meetings, mail, OTHER, 2)
    service = _service(mail, meetings, communications=True)
    answer = _invoke(
        service, OPERATOR, CONTEXT, {"meeting_ids": [theirs, mine, UNKNOWN]}, grants=GRANTS
    )
    assert answer.error is None and answer.result is not None
    payload = answer.result
    assert [m["meeting"]["meeting_id"] for m in payload["meetings"]] == [mine]
    # Unknown and foreign alike, in request order, indistinguishable.
    assert payload["not_found"] == [theirs, UNKNOWN]
    (context,) = payload["meetings"]
    assert context["communications"]["state"] == "ok"
    assert context["provider_binding"] == {"state": "unbound", "binding": None}
    assert "provider_unbound" in context["communications"]["missing"]
    assert payload["limits"] == {"lookback_days": 14, "per_meeting_limit": 15}
    assert payload["versions"]["identifier_version"] == "comms_identifiers_v2"
    assert answer.disclosure is not None
    assert answer.disclosure.trust.basis == ("principal_partition",)
    assert answer.disclosure.truncation.is_truncated is False
    # The stranger reads nothing of mine.
    foreign = _invoke(service, STRANGER, CONTEXT, {"meeting_ids": [mine]}, grants=GRANTS)
    assert foreign.error is None and foreign.result is not None
    assert foreign.result["meetings"] == []
    assert foreign.result["not_found"] == [mine]


@pytest.mark.parametrize(
    ("project_reports", "expected"),
    [
        (False, {"state": "unavailable", "reason": "reads_disabled"}),
        (True, {"state": "not_linked"}),
    ],
)
def test_the_project_report_switch_is_passed_through_to_the_pulse_section(
    project_reports: bool, expected: dict[str, str]
) -> None:
    mail, meetings = IngestWorld(), World()
    mine = _meeting(meetings, mail, P, 1)
    service = _service(mail, meetings, communications=True, project_reports=project_reports)
    answer = _invoke(service, OPERATOR, CONTEXT, {"meeting_ids": [mine]}, grants=GRANTS)
    assert answer.error is None and answer.result is not None
    (context,) = answer.result["meetings"]
    assert context["pulse"] == expected


def test_a_meeting_cut_at_its_limit_is_disclosed_as_truncated() -> None:
    from tests.unit.test_meeting_context_assembly import _row

    mail, meetings = IngestWorld(), World()
    mine = _meeting(meetings, mail, P, 1)
    mail.context_rows = [_row(0, n, matched_total=3) for n in range(1, 4)]
    service = _service(mail, meetings, communications=True)
    answer = _invoke(
        service, OPERATOR, CONTEXT, {"meeting_ids": [mine], "per_meeting_limit": 2}, grants=GRANTS
    )
    assert answer.error is None and answer.result is not None
    (context,) = answer.result["meetings"]
    assert (context["communications"]["matched_total"], context["communications"]["truncated"]) == (
        3,
        True,
    )
    assert len(context["communications"]["messages"]) == 2
    assert answer.disclosure is not None
    truncation = answer.disclosure.truncation
    assert (truncation.is_truncated, truncation.reason, truncation.next_cursor) == (
        True,
        "page_size_reached",
        None,
    )


# ---- helpers ------------------------------------------------------------------------------


def _service(
    mail: IngestWorld, meetings: World, *, communications: bool, project_reports: bool = False
) -> ApplicationService:
    from tests.conftest import DEFAULT_LIMITS

    return ApplicationService(
        unit_of_work=lambda: IngestUnitOfWork(mail, meetings=meetings),
        limits=DEFAULT_LIMITS,
        clock=lambda: NOW,
        communications_enabled=communications,
        project_reports_enabled=project_reports,
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
