"""WP-MTG-04: the six Meeting records capabilities, admitted at the canonical boundary.

Two halves.

**FAST** (no marker): the admission itself -- the six names are declared,
dispatched, built and published together; their purposes, write, additive,
scopeless, operator-only and remote-write classifications; the generated
canonical MCP schemas with every package section 35.8 overlay; the remote
publication that strips envelope fields and `idempotency_key`; the section
35.16 error translation (including `not_found`/`conditional`, a port failure as
`internal_error`, and no caller text in any detail); the token mappings WP-MTG-01
review F-02/F-03 carried; the R3-03 refusal of text that cannot be stored; and
the R3-02 clear-wins rule, which is unchanged. The in-memory Meeting fake
(`tests/conftest.py`, plan D-31) serves the service-level cases; it is test
infrastructure and is not database evidence for any acceptance criterion.

**database + e2e** (routed to database-e2e): scenarios E-01 to E-15, each a
synthetic canonical request through the real MCP server over the real
`ApplicationService` and the general `SqlAlchemyUnitOfWork` on a disposable
current-head database. Each is keyed to the acceptance criteria it evidences
(plan section 12).

Every identifier, title, name, address and link here is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, get_args

import jsonschema
import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.engine import Connection
from tests.conftest import DEFAULT_LIMITS, Scene, _Meetings, build_service, operator
from tests.contract.test_transport_parity import a_forbidden_purpose, document
from tests.transports import McpTransport, mcp_transport

from my_pa.adapters.mcp.remote import is_remote_write
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import TOOLS, input_schema_for, payload_schema_for
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.adapters.remote_request import (
    REMOTE_OWNED_PAYLOAD_FIELDS,
    SERVER_OWNED_REMOTE_FIELDS,
    remote_tool_schema,
)
from my_pa.application.commands import (
    Command,
    CreateMeeting,
    ListMeetings,
    ReadMeeting,
    SearchMeetings,
    UpdateMeeting,
    UpdateMeetingSeries,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.contracts.ports import RepositoryFailureError
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode, RetryGuidance
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.meeting.model import (
    MEETINGS_CREATE_NAME,
    MEETINGS_SERIES_UPDATE_NAME,
    MEETINGS_UPDATE_NAME,
    MeetingErrorField,
    MeetingSortDirection,
    MeetingTimeScope,
)
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import (
    entities,
    managed_document_lifecycle_events,
    managed_document_versions,
    managed_documents,
    meeting_series,
    meeting_write_requests,
    projects,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

# --------------------------------------------------------------------------- shared

READS: Final = (Capability.MEETINGS_READ, Capability.MEETINGS_LIST, Capability.MEETINGS_SEARCH)
WRITES: Final = (
    Capability.MEETINGS_CREATE,
    Capability.MEETINGS_UPDATE,
    Capability.MEETINGS_SERIES_UPDATE,
)
MEETING_CAPABILITIES: Final = frozenset((*READS, *WRITES))

COMMANDS: Final[Mapping[Capability, type]] = {
    Capability.MEETINGS_CREATE: CreateMeeting,
    Capability.MEETINGS_READ: ReadMeeting,
    Capability.MEETINGS_LIST: ListMeetings,
    Capability.MEETINGS_SEARCH: SearchMeetings,
    Capability.MEETINGS_UPDATE: UpdateMeeting,
    Capability.MEETINGS_SERIES_UPDATE: UpdateMeetingSeries,
}

_ID_SUFFIX: Final = "_[A-Za-z0-9]{8,64}$"


def _id_pattern(kind: IdKind) -> str:
    return f"^{kind.value}{_ID_SUFFIX}"


def _request(capability: Capability, payload: Mapping[str, Any]) -> dict[str, Any]:
    return document(capability, "prn_meetingmcp00000001", payload)


def _refusal(capability: Capability, payload: Mapping[str, Any]) -> tuple[str, ...]:
    """The safe details `normalize` refuses `payload` with."""
    with pytest.raises(InvalidRequestError) as refused:
        normalize(capability.value, _request(capability, payload))
    return tuple(detail.value for detail in refused.value.safe_details)


CREATE_MINIMUM: Final[dict[str, Any]] = {
    "title": "A synthetic meeting",
    "start_at": "2026-09-28T13:00:00Z",
    "timezone_name": "UTC",
    "idempotency_key": "meeting-mcp-create-0001",
}


# ------------------------------------------------------------------ admission


def test_the_six_capabilities_are_declared_dispatched_built_and_published() -> None:
    declared = {capability for capability in Capability if capability.value.startswith("meetings.")}
    assert declared == MEETING_CAPABILITIES
    assert set(_HANDLERS) >= MEETING_CAPABILITIES
    assert set(_BUILDERS) >= MEETING_CAPABILITIES
    commands = {member.capability: member for member in get_args(Command.__value__)}
    assert {capability: commands[capability] for capability in MEETING_CAPABILITIES} == COMMANDS
    handlers = {capability: _HANDLERS[capability].__name__ for capability in MEETING_CAPABILITIES}
    assert handlers == {
        Capability.MEETINGS_CREATE: "_meetings_create",
        Capability.MEETINGS_READ: "_meetings_read",
        Capability.MEETINGS_LIST: "_meetings_list",
        Capability.MEETINGS_SEARCH: "_meetings_search",
        Capability.MEETINGS_UPDATE: "_meetings_update",
        Capability.MEETINGS_SERIES_UPDATE: "_meetings_series_update",
    }
    assert {capability.value for capability in MEETING_CAPABILITIES} <= {
        tool.name for tool in TOOLS
    }


def test_the_write_capability_values_are_the_wp01_name_constants() -> None:
    """Plan D-21: the migration's frozen CHECK literals and the enum cannot drift."""
    assert Capability.MEETINGS_CREATE.value == MEETINGS_CREATE_NAME
    assert Capability.MEETINGS_UPDATE.value == MEETINGS_UPDATE_NAME
    assert Capability.MEETINGS_SERIES_UPDATE.value == MEETINGS_SERIES_UPDATE_NAME


def test_purpose_write_additive_scopeless_and_operator_classification() -> None:
    assert Purpose.MEETING_READ.value == "meeting_read"
    assert Purpose.MEETING_AUTHORING.value == "meeting_authoring"
    for capability in READS:
        assert permitted_purposes(capability) == {Purpose.MEETING_READ}
        assert not is_write_capability(capability)
        assert not is_destructive_capability(capability)
    for capability in WRITES:
        assert permitted_purposes(capability) == {Purpose.MEETING_AUTHORING}
        assert is_write_capability(capability)
    # Only create is additive: update and series.update reach an existing row.
    assert not is_destructive_capability(Capability.MEETINGS_CREATE)
    assert is_destructive_capability(Capability.MEETINGS_UPDATE)
    assert is_destructive_capability(Capability.MEETINGS_SERIES_UPDATE)
    for capability in MEETING_CAPABILITIES:
        assert capability in _SCOPELESS
        assert not is_operator_only(capability)


def test_remote_write_classification_is_exactly_the_three_writes() -> None:
    """Plan D-06: without `meeting_authoring` in `_WRITE_PURPOSES` a write is a read."""
    assert {capability for capability in MEETING_CAPABILITIES if is_remote_write(capability)} == (
        set(WRITES)
    )


def test_tools_list_publishes_the_six_for_every_canonical_client(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    names = {capability.value for capability in MEETING_CAPABILITIES}
    assert names <= {tool.name for tool in published_tools(service)}
    assert names <= {
        tool.name for tool in published_tools(service, authenticated_client_present=True)
    }
    annotated = {tool.name: tool.annotations for tool in TOOLS if tool.name in names}
    for capability in READS:
        assert annotated[capability.value].read_only_hint is True
    for capability in WRITES:
        assert annotated[capability.value].read_only_hint is False
    assert annotated[Capability.MEETINGS_CREATE.value].destructive_hint is False
    assert annotated[Capability.MEETINGS_UPDATE.value].destructive_hint is True
    assert annotated[Capability.MEETINGS_SERIES_UPDATE.value].destructive_hint is True


# ------------------------------------------------------------ generated schemas


def test_create_schema_carries_every_section_35_8_overlay() -> None:
    schema = payload_schema_for(CreateMeeting)
    properties = schema["properties"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["title", "start_at", "timezone_name", "idempotency_key"]
    assert set(properties) == {
        "title",
        "start_at",
        "timezone_name",
        "idempotency_key",
        "end_at",
        "meeting_series_id",
        "series_title",
        "location_text",
        "virtual_meeting_url",
        "description",
        "project_id",
        "attendees",
        "attachment_document_ids",
        "notes_markdown",
    }
    assert (
        properties["title"].items() >= {"type": "string", "minLength": 1, "maxLength": 200}.items()
    )
    assert properties["series_title"]["minLength"] == 1
    assert properties["series_title"]["maxLength"] == 200
    assert properties["start_at"]["format"] == "date-time"
    assert properties["end_at"]["format"] == "date-time"
    assert (properties["timezone_name"]["minLength"], properties["timezone_name"]["maxLength"]) == (
        1,
        64,
    )
    assert properties["meeting_series_id"]["pattern"] == _id_pattern(IdKind.MEETING_SERIES)
    assert properties["project_id"]["pattern"] == _id_pattern(IdKind.PROJECT)
    assert properties["location_text"]["maxLength"] == 500
    url = properties["virtual_meeting_url"]
    assert (url["minLength"], url["maxLength"], url["format"]) == (1, 2048, "uri")
    assert properties["description"]["maxLength"] == 100_000
    assert (
        properties["notes_markdown"]["minLength"],
        properties["notes_markdown"]["maxLength"],
    ) == (1, 100_000)
    assert (
        properties["idempotency_key"]["minLength"],
        properties["idempotency_key"]["maxLength"],
    ) == (1, 128)
    attendees = properties["attendees"]
    assert (attendees["type"], attendees["maxItems"], attendees["uniqueItems"]) == (
        "array",
        100,
        True,
    )
    item = attendees["items"]
    assert item["type"] == "object"
    assert item["additionalProperties"] is False
    assert set(item["properties"]) == {
        "display_name",
        "email",
        "entity_id",
        "is_organizer",
        "response_status",
    }
    assert item["properties"]["display_name"]["maxLength"] == 200
    assert item["properties"]["email"]["maxLength"] == 320
    assert item["properties"]["entity_id"]["pattern"] == _id_pattern(IdKind.ENTITY)
    assert item["properties"]["is_organizer"]["type"] == "boolean"
    assert item["properties"]["response_status"]["enum"] == [
        "unknown",
        "needs_action",
        "accepted",
        "declined",
        "tentative",
    ]
    documents = properties["attachment_document_ids"]
    assert (documents["maxItems"], documents["uniqueItems"]) == (50, True)
    assert documents["items"]["pattern"] == _id_pattern(IdKind.MANAGED_DOCUMENT)
    assert len(schema["oneOf"]) == 3


@pytest.mark.parametrize(
    ("selector", "valid"),
    [
        ({}, True),
        ({"series_title": "A synthetic series"}, True),
        ({"meeting_series_id": make_identifier(IdKind.MEETING_SERIES, "schemaseries0001")}, True),
        (
            {
                "series_title": "A synthetic series",
                "meeting_series_id": make_identifier(IdKind.MEETING_SERIES, "schemaseries0001"),
            },
            False,
        ),
    ],
    ids=["standalone", "new-series", "existing-series", "both"],
)
def test_the_create_selector_admits_exactly_one_of_three_states(
    selector: dict[str, str], valid: bool
) -> None:
    schema = payload_schema_for(CreateMeeting)
    instance = {**CREATE_MINIMUM, **selector}
    if valid:
        jsonschema.validate(instance, schema)
    else:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance, schema)


def test_an_attendee_needs_one_identity_signal_and_may_carry_several() -> None:
    schema = payload_schema_for(CreateMeeting)
    jsonschema.validate(
        {**CREATE_MINIMUM, "attendees": [{"display_name": "A", "email": "a@example.invalid"}]},
        schema,
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**CREATE_MINIMUM, "attendees": [{"is_organizer": True}]}, schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {**CREATE_MINIMUM, "attendees": [{"display_name": "A", "x": 1}]}, schema
        )


def test_update_schema_encodes_the_pairing_and_project_clear_rules() -> None:
    schema = payload_schema_for(UpdateMeeting)
    properties = schema["properties"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["meeting_id", "expected_version", "idempotency_key"]
    assert "meeting_series_id" not in properties
    assert "series_title" not in properties
    assert properties["expected_version"]["minimum"] == 1
    assert properties["clear_fields"]["items"]["enum"] == [
        "end_at",
        "location_text",
        "virtual_meeting_url",
        "description",
        "project_id",
    ]
    assert (properties["clear_fields"]["uniqueItems"], properties["clear_fields"]["maxItems"]) == (
        True,
        5,
    )
    assert properties["attendees_replace"]["maxItems"] == 100
    assert properties["attachment_add_document_ids"]["maxItems"] == 50
    assert properties["attachment_remove_ids"]["items"]["pattern"] == _id_pattern(
        IdKind.MEETING_ATTACHMENT
    )
    assert properties["notes_mode"]["enum"] == ["append", "replace"]
    base = {
        "meeting_id": make_identifier(IdKind.MEETING, "schemameeting001"),
        "expected_version": 1,
        "idempotency_key": "k",
    }
    jsonschema.validate({**base, "notes_mode": "append", "notes_markdown": "x"}, schema)
    for broken in (
        {"notes_mode": "append"},
        {"notes_markdown": "x"},
        {
            "project_id": make_identifier(IdKind.PROJECT, "schemaproject001"),
            "clear_fields": ["project_id"],
        },
        {"meeting_series_id": make_identifier(IdKind.MEETING_SERIES, "schemaseries0001")},
        {"series_title": "A synthetic series"},
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate({**base, **broken}, schema)


@pytest.mark.parametrize("field", ["meeting_series_id", "series_title"])
def test_an_update_naming_a_series_field_is_refused(field: str) -> None:
    """Series membership is immutable: the field does not exist on the command."""
    payload = {
        "meeting_id": make_identifier(IdKind.MEETING, "schemameeting001"),
        "expected_version": 1,
        "idempotency_key": "k",
        "title": "Retitled",
        field: make_identifier(IdKind.MEETING_SERIES, "schemaseries0001")
        if field == "meeting_series_id"
        else "A series",
    }
    assert _refusal(Capability.MEETINGS_UPDATE, payload) == ()


def test_the_read_list_search_and_series_schemas_are_exact() -> None:
    read = payload_schema_for(ReadMeeting)
    assert read["required"] == ["meeting_id"]
    assert read["properties"]["meeting_id"]["pattern"] == _id_pattern(IdKind.MEETING)
    listed = payload_schema_for(ListMeetings)
    assert listed["required"] == []
    assert listed["properties"]["status"]["enum"] == ["scheduled", "cancelled"]
    assert listed["properties"]["time_scope"]["enum"] == ["all", "upcoming", "past"]
    assert listed["properties"]["time_scope"]["default"] == "all"
    assert listed["properties"]["sort_direction"]["enum"] == ["asc", "desc"]
    assert listed["properties"]["sort_direction"]["default"] == "asc"
    assert (
        listed["properties"]["page_size"]["minimum"],
        listed["properties"]["page_size"]["maximum"],
    ) == (1, 100)
    assert listed["properties"]["after"]["pattern"] == _id_pattern(IdKind.MEETING)
    assert listed["properties"]["attendee_email"]["maxLength"] == 320
    searched = payload_schema_for(SearchMeetings)
    assert searched["required"] == ["query"]
    assert (
        searched["properties"]["query"]["minLength"],
        searched["properties"]["query"]["maxLength"],
    ) == (1, 512)
    assert set(searched["properties"]) == set(listed["properties"]) | {"query"}
    series = payload_schema_for(UpdateMeetingSeries)
    assert set(series["properties"]) == {
        "meeting_series_id",
        "expected_version",
        "idempotency_key",
        "title",
    }
    assert series["required"] == [
        "meeting_series_id",
        "expected_version",
        "idempotency_key",
        "title",
    ]
    for schema in (read, listed, searched, series):
        assert schema["additionalProperties"] is False


@pytest.mark.parametrize("capability", sorted(MEETING_CAPABILITIES), ids=lambda c: c.value)
def test_the_remote_schema_strips_envelope_fields_and_the_idempotency_key(
    capability: Capability,
) -> None:
    published = remote_tool_schema(input_schema_for(COMMANDS[capability]))
    assert not SERVER_OWNED_REMOTE_FIELDS & set(published["properties"])
    payload = published["properties"]["payload"]
    assert not REMOTE_OWNED_PAYLOAD_FIELDS & set(payload["properties"])
    assert "idempotency_key" not in payload["required"]
    if capability is Capability.MEETINGS_CREATE:
        assert len(payload["oneOf"]) == 3
    if capability is Capability.MEETINGS_UPDATE:
        assert len(payload["allOf"]) == 3


# ------------------------------------------------------------ error contract


def test_every_meeting_error_token_is_a_live_safe_detail() -> None:
    """WP-MTG-01 review F-03: checked against the live enum, not a literal."""
    live = {detail.value for detail in SafeDetail}
    assert {field.value for field in MeetingErrorField} <= live


def test_an_unknown_time_scope_or_sort_direction_names_the_field_it_governs() -> None:
    """WP-MTG-01 review F-02: documented, not remapped (`commands.py`)."""
    assert "bogus" not in {member.value for member in MeetingTimeScope}
    assert "bogus" not in {member.value for member in MeetingSortDirection}
    assert _refusal(Capability.MEETINGS_LIST, {"time_scope": "bogus"}) == ("start_at",)
    assert _refusal(Capability.MEETINGS_LIST, {"sort_direction": "bogus"}) == ("cursor",)


def _invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
    *,
    purpose: Purpose | None = None,
) -> ResponseEnvelope:
    metadata, command = normalize(
        capability.value, document(capability, principal.principal_id, payload, purpose=purpose)
    )
    return service.invoke(metadata, command, principal=principal)


def _problem(envelope: ResponseEnvelope) -> tuple[ErrorCode, RetryGuidance, tuple[str, ...]]:
    assert envelope.error is not None, envelope.result
    return envelope.error.code, envelope.error.retry, envelope.error.safe_details


def test_the_section_35_16_table_over_the_service(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    principal = scene.principal
    absent = make_identifier(IdKind.MEETING, "absentmeeting001")
    read = _invoke(service, principal, Capability.MEETINGS_READ, {"meeting_id": absent})
    assert _problem(read) == (ErrorCode.NOT_FOUND, RetryGuidance.CONDITIONAL, ("meeting_id",))

    stale = _invoke(
        service,
        principal,
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": scene.meeting_id,
            "expected_version": 7,
            "idempotency_key": "stale-0001",
            "title": "Stale",
        },
    )
    assert _problem(stale) == (ErrorCode.CONFLICT, RetryGuidance.AFTER_REFRESH, ("stale_version",))

    first = _invoke(service, principal, Capability.MEETINGS_CREATE, CREATE_MINIMUM)
    assert first.error is None
    reused = _invoke(
        service, principal, Capability.MEETINGS_CREATE, {**CREATE_MINIMUM, "title": "Different"}
    )
    assert _problem(reused) == (
        ErrorCode.CONFLICT,
        RetryGuidance.AFTER_REFRESH,
        ("idempotency_conflict",),
    )

    cursor = _invoke(service, principal, Capability.MEETINGS_LIST, {"after": absent})
    assert _problem(cursor) == (
        ErrorCode.INVALID_REQUEST,
        RetryGuidance.AFTER_CORRECTION,
        ("cursor",),
    )

    series = _invoke(
        service,
        principal,
        Capability.MEETINGS_CREATE,
        {
            **CREATE_MINIMUM,
            "idempotency_key": "absent-series-0001",
            "meeting_series_id": make_identifier(IdKind.MEETING_SERIES, "absentseries0001"),
        },
    )
    assert _problem(series) == (
        ErrorCode.NOT_FOUND,
        RetryGuidance.CONDITIONAL,
        ("meeting_series_id",),
    )

    denied = _invoke(
        service,
        principal,
        Capability.MEETINGS_READ,
        {"meeting_id": scene.meeting_id},
        purpose=a_forbidden_purpose(Capability.MEETINGS_READ),
    )
    assert _problem(denied) == (ErrorCode.DENIED, RetryGuidance.AFTER_AUTHORITY_CHANGE, ())


def test_no_caller_text_reaches_a_meeting_error(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    marker = "MARKERMEETINGTITLE"
    refused = _invoke(
        service,
        scene.principal,
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": scene.meeting_id,
            "expected_version": 9,
            "idempotency_key": "marker-0001",
            "title": marker,
            "virtual_meeting_url": f"https://{marker.lower()}.invalid/join",
        },
    )
    assert refused.error is not None
    assert marker.lower() not in refused.error.model_dump_json().lower()


def test_a_port_failure_inside_a_meeting_handler_is_an_internal_error(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-MTG-03 review R3-04: the handlers run inside `_translated`."""

    def failing(self: _Meetings, principal_id: str, meeting_id: str) -> None:
        raise RepositoryFailureError("synthetic invariant breach")

    monkeypatch.setattr(_Meetings, "read_meeting", failing)
    service = build_service(scene.world, scene.providers)
    envelope = _invoke(
        service, scene.principal, Capability.MEETINGS_READ, {"meeting_id": scene.meeting_id}
    )
    assert _problem(envelope) == (ErrorCode.INTERNAL_ERROR, RetryGuidance.CONDITIONAL, ())
    assert "synthetic invariant breach" not in envelope.model_dump_json()


# ------------------------------------------------------ R3-03: storable text


_NUL: Final = "text\x00after"
_SURROGATE: Final = "text\ud800after"

_UPDATE_BASE: Final[dict[str, Any]] = {
    "meeting_id": make_identifier(IdKind.MEETING, "storablemeeting1"),
    "expected_version": 1,
    "idempotency_key": "storable-update-0001",
    # A material selector, so the control below is accepted on every field.
    "status": "scheduled",
}
_SERIES_BASE: Final[dict[str, Any]] = {
    "meeting_series_id": make_identifier(IdKind.MEETING_SERIES, "storableseries01"),
    "expected_version": 1,
    "idempotency_key": "storable-series-0001",
    "title": "A synthetic series",
}

#: `(capability, base payload, field, how to place the bad value, token)`.
_STORABLE_CASES: Final[tuple[tuple[Capability, dict[str, Any], str, str, str], ...]] = (
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "title", "scalar", "title"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "series_title", "scalar", "title"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "timezone_name", "scalar", "timezone_name"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "location_text", "scalar", "location_text"),
    (
        Capability.MEETINGS_CREATE,
        CREATE_MINIMUM,
        "virtual_meeting_url",
        "scalar",
        "virtual_meeting_url",
    ),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "description", "scalar", "description"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "notes_markdown", "scalar", "notes"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "idempotency_key", "scalar", "idempotency_key"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "attendees", "display_name", "attendees"),
    (Capability.MEETINGS_CREATE, CREATE_MINIMUM, "attendees", "email", "attendees"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "title", "scalar", "title"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "timezone_name", "scalar", "timezone_name"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "location_text", "scalar", "location_text"),
    (
        Capability.MEETINGS_UPDATE,
        _UPDATE_BASE,
        "virtual_meeting_url",
        "scalar",
        "virtual_meeting_url",
    ),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "description", "scalar", "description"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "notes_markdown", "notes", "notes"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "idempotency_key", "scalar", "idempotency_key"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "attendees_replace", "display_name", "attendees"),
    (Capability.MEETINGS_UPDATE, _UPDATE_BASE, "attendees_replace", "email", "attendees"),
    (Capability.MEETINGS_SERIES_UPDATE, _SERIES_BASE, "title", "scalar", "title"),
    (
        Capability.MEETINGS_SERIES_UPDATE,
        _SERIES_BASE,
        "idempotency_key",
        "scalar",
        "idempotency_key",
    ),
    (Capability.MEETINGS_LIST, {}, "attendee_email", "scalar", "attendees"),
    (Capability.MEETINGS_SEARCH, {"query": "synthetic"}, "query", "scalar", "query"),
    (Capability.MEETINGS_SEARCH, {"query": "synthetic"}, "attendee_email", "scalar", "attendees"),
)


def _placed(base: Mapping[str, Any], field: str, how: str, value: str) -> dict[str, Any]:
    payload = dict(base)
    if how == "scalar":
        payload[field] = value
    elif how == "notes":
        payload["notes_mode"] = "replace"
        payload[field] = value
    elif how == "display_name":
        payload[field] = [{"display_name": value}]
    else:
        payload[field] = [{"email": value}]
    return payload


@pytest.mark.parametrize("bad", [_NUL, _SURROGATE], ids=["nul", "lone-surrogate"])
@pytest.mark.parametrize(
    ("capability", "base", "field", "how", "token"),
    _STORABLE_CASES,
    ids=[f"{case[0].value}-{case[2]}-{case[3]}" for case in _STORABLE_CASES],
)
def test_text_that_cannot_be_stored_is_refused_before_any_digest(
    capability: Capability, base: dict[str, Any], field: str, how: str, token: str, bad: str
) -> None:
    """R3-03: NUL and a lone surrogate are refused with the field's own token."""
    assert _refusal(capability, _placed(base, field, how, bad)) == (token,)


def test_the_same_text_without_the_bad_code_point_is_accepted() -> None:
    """The control: the refusal above is the code point, not the field."""
    clean = "text after"
    for capability, base, field, how, _token in _STORABLE_CASES:
        value = clean
        if field == "virtual_meeting_url":
            value = "https://meet.example.invalid/room"
        elif field == "timezone_name":
            value = "America/New_York"
        elif how == "email" or field == "attendee_email":
            value = "person@example.invalid"
        normalize(capability.value, _request(capability, _placed(base, field, how, value)))


# ------------------------------------------------------ R3-02: clear wins, unchanged


def test_an_explicit_clear_still_wins_and_a_project_clear_pair_is_still_refused(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    updated = _invoke(
        service,
        scene.principal,
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": scene.meeting_id,
            "expected_version": 1,
            "idempotency_key": "clear-wins-0001",
            "location_text": "Room 1",
            "clear_fields": ["location_text"],
        },
    )
    assert updated.error is None
    assert isinstance(updated.result, dict)
    assert updated.result["meeting"]["location_text"] is None
    assert _refusal(
        Capability.MEETINGS_UPDATE,
        {
            **_UPDATE_BASE,
            "project_id": make_identifier(IdKind.PROJECT, "clearproject0001"),
            "clear_fields": ["project_id"],
        },
    ) == ("clear_fields",)


# ======================================================================== E-nn
#
# database + e2e: the synthetic canonical path, through the real MCP server over
# the real service and the general unit of work, on a disposable database.

T0: Final = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
NOW: Final = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Partition:
    """One Principal's synthetic reference rows on the other planes."""

    principal: Principal
    project_id: str
    person_ids: tuple[str, str]
    document_id: str


def _insert_partition(connection: Connection) -> Partition:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    project_id = issue_identifier(IdKind.PROJECT)
    # Closed on purpose: a Meeting accepts a same-Principal Project in any state.
    connection.execute(
        insert(projects).values(
            project_id=project_id,
            principal_id=principal_id,
            name="Synthetic project",
            state="closed",
            participants=[],
            opened_at=T0,
            closed_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )
    people: list[str] = []
    for _ in range(2):
        entity_id = issue_identifier(IdKind.ENTITY)
        connection.execute(
            insert(entities).values(
                entity_id=entity_id,
                principal_id=principal_id,
                entity_type="person",
                canonical_name="synthetic person",
                display_name="Synthetic person",
                status="active",
                created_at=T0,
                updated_at=T0,
                version=1,
            )
        )
        people.append(entity_id)
    document_id = issue_identifier(IdKind.MANAGED_DOCUMENT)
    connection.execute(
        insert(managed_documents).values(
            document_id=document_id, owner_principal_id=principal_id, created_at=T0
        )
    )
    connection.execute(
        insert(managed_document_versions).values(
            version_id=issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION),
            document_id=document_id,
            version_number=1,
            supersedes_version_id=None,
            owner_principal_id=principal_id,
            title="Synthetic agenda",
            media_type="text/markdown",
            content_sha256=hashlib.sha256(document_id.encode()).hexdigest(),
            byte_size=16,
            idempotency_key=f"doc-{document_id}",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            recorded_at=T0,
        )
    )
    ordered = sorted(people)
    return Partition(
        principal=operator(principal_id),
        project_id=project_id,
        person_ids=(ordered[0], ordered[1]),
        document_id=document_id,
    )


@dataclass(frozen=True)
class Canonical:
    """An MCP client per Principal, the engine they reach, and both partitions.

    The composition root supplies the Principal, never the request document, so
    acting as the other Principal means a second server composed for it.
    """

    clients: Mapping[str, McpTransport]
    engine: Engine
    mine: Partition
    theirs: Partition

    def send(
        self, capability: Capability, payload: Mapping[str, Any], *, as_: Partition | None = None
    ) -> dict[str, Any]:
        owner = as_ or self.mine
        principal_id = owner.principal.principal_id
        answer = self.clients[principal_id].send(
            capability.value, document(capability, principal_id, payload)
        )
        return answer.document

    def ok(
        self, capability: Capability, payload: Mapping[str, Any], *, as_: Partition | None = None
    ) -> dict[str, Any]:
        answer = self.send(capability, payload, as_=as_)
        assert answer.get("error") is None, answer.get("error")
        result = answer["result"]
        assert isinstance(result, dict)
        return result

    def refused(
        self, capability: Capability, payload: Mapping[str, Any], *, as_: Partition | None = None
    ) -> dict[str, Any]:
        answer = self.send(capability, payload, as_=as_)
        problem = answer.get("error", answer)
        assert isinstance(problem, dict) and "code" in problem, answer
        return problem

    def count(self, table: Any, **where: object) -> int:  # noqa: ANN401 - a Table
        statement = select(func.count()).select_from(table)
        for column, value in where.items():
            statement = statement.where(table.c[column] == value)
        with self.engine.connect() as connection:
            return int(connection.execute(statement).scalar_one())


@pytest.fixture
def canonical(db_engine: Engine) -> Iterator[Canonical]:
    with db_engine.begin() as connection:
        mine = _insert_partition(connection)
        theirs = _insert_partition(connection)
    audit = SqlAlchemyAuditSink(db_engine)
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(db_engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: NOW,
    )
    with (
        mcp_transport(service, mine.principal) as my_client,
        mcp_transport(service, theirs.principal) as their_client,
    ):
        yield Canonical(
            clients={
                mine.principal.principal_id: my_client,
                theirs.principal.principal_id: their_client,
            },
            engine=db_engine,
            mine=mine,
            theirs=theirs,
        )


def _create(canonical: Canonical, key: str, **fields: object) -> dict[str, Any]:
    payload: dict[str, Any] = {**CREATE_MINIMUM, "idempotency_key": key, **fields}
    return canonical.ok(Capability.MEETINGS_CREATE, payload)


@pytest.mark.database
@pytest.mark.e2e
def test_e01_a_standalone_create_reads_back_with_no_series(canonical: Canonical) -> None:
    """AC-003, AC-004, AC-022."""
    created = _create(canonical, "e01-create")
    meeting = created["meeting"]
    assert created["replayed"] is False
    assert created["series"] is None and created["series_history"] is None
    assert meeting["meeting_series_id"] is None and meeting["series_title"] is None
    assert created["history"]["outcome"] == "applied" and created["history"]["after_version"] == 1
    read = canonical.ok(Capability.MEETINGS_READ, {"meeting_id": meeting["meeting_id"]})
    assert read["meeting"] == meeting
    assert canonical.count(meeting_series, principal_id=canonical.mine.principal.principal_id) == 0


@pytest.mark.database
@pytest.mark.e2e
def test_e02_a_series_title_creates_the_series_and_its_first_occurrence(
    canonical: Canonical,
) -> None:
    """AC-009, AC-022: one request identity names both receipts."""
    created = _create(canonical, "e02-create", series_title="A synthetic series")
    meeting = created["meeting"]
    series = created["series"]
    assert series is not None and series["title"] == "A synthetic series"
    assert meeting["meeting_series_id"] == series["meeting_series_id"]
    assert created["series_history"]["meeting_series_id"] == series["meeting_series_id"]
    principal_id = canonical.mine.principal.principal_id
    assert canonical.count(meeting_write_requests, principal_id=principal_id) == 1
    with canonical.engine.connect() as connection:
        row = (
            connection.execute(
                select(meeting_write_requests).where(
                    meeting_write_requests.c.principal_id == principal_id
                )
            )
            .mappings()
            .one()
        )
    assert row["meeting_series_id"] == series["meeting_series_id"]
    assert row["meeting_series_history_id"] == created["series_history"]["series_history_id"]


@pytest.mark.database
@pytest.mark.e2e
def test_e03_an_occurrence_of_an_existing_series_leaves_the_series_alone(
    canonical: Canonical,
) -> None:
    """AC-022."""
    first = _create(canonical, "e03-first", series_title="A synthetic series")
    series_id = first["series"]["meeting_series_id"]
    second = _create(canonical, "e03-second", meeting_series_id=series_id)
    assert second["meeting"]["meeting_series_id"] == series_id
    assert second["series"] == first["series"]
    assert second["series"]["version"] == 1
    assert second["series_history"] is None


@pytest.mark.database
@pytest.mark.e2e
def test_e04_an_aware_instant_keeps_its_zone_and_a_naive_one_is_refused(
    canonical: Canonical,
) -> None:
    """AC-005, AC-006: the offset need not match the zone; the instant is UTC."""
    created = _create(
        canonical,
        "e04-create",
        start_at="2026-11-01T01:30:00-04:00",
        timezone_name="America/Los_Angeles",
    )
    meeting = canonical.ok(
        Capability.MEETINGS_READ, {"meeting_id": created["meeting"]["meeting_id"]}
    )["meeting"]
    assert datetime.fromisoformat(meeting["start_at"]) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert meeting["timezone_name"] == "America/Los_Angeles"
    naive = canonical.refused(
        Capability.MEETINGS_CREATE,
        {**CREATE_MINIMUM, "idempotency_key": "e04-naive", "start_at": "2026-11-01T01:30:00"},
    )
    assert (naive["code"], naive["safe_details"]) == ("invalid_request", ["start_at"])


@pytest.mark.database
@pytest.mark.e2e
def test_e05_a_reschedule_keeps_identity_and_series_is_immutable(canonical: Canonical) -> None:
    """AC-007."""
    created = _create(canonical, "e05-create", series_title="A synthetic series")
    meeting = created["meeting"]
    moved = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting["meeting_id"],
            "expected_version": 1,
            "idempotency_key": "e05-move",
            "start_at": "2026-09-29T15:00:00Z",
        },
    )["meeting"]
    assert moved["meeting_id"] == meeting["meeting_id"]
    assert moved["meeting_series_id"] == meeting["meeting_series_id"]
    assert moved["version"] == 2
    refused = canonical.refused(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting["meeting_id"],
            "expected_version": 2,
            "idempotency_key": "e05-series",
            "meeting_series_id": meeting["meeting_series_id"],
        },
    )
    assert refused["code"] == "invalid_request"


@pytest.mark.database
@pytest.mark.e2e
def test_e06_cancel_then_reinstate(canonical: Canonical) -> None:
    """AC-008."""
    meeting_id = _create(canonical, "e06-create")["meeting"]["meeting_id"]
    cancelled = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 1,
            "idempotency_key": "e06-cancel",
            "status": "cancelled",
        },
    )["meeting"]
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"] is not None
    reinstated = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 2,
            "idempotency_key": "e06-reinstate",
            "status": "scheduled",
        },
    )["meeting"]
    assert reinstated["status"] == "scheduled" and reinstated["cancelled_at"] is None


@pytest.mark.database
@pytest.mark.e2e
def test_e07_a_snapshot_attendee_creates_no_entity(canonical: Canonical) -> None:
    """AC-011."""
    before = canonical.count(entities)
    created = _create(
        canonical,
        "e07-create",
        attendees=[{"display_name": "  Visiting Guest  ", "email": "Guest@Example.Invalid"}],
    )
    attendee = created["meeting"]["attendees"][0]
    assert attendee["entity_id"] is None
    assert attendee["display_name"] == "Visiting Guest"
    assert canonical.count(entities) == before


@pytest.mark.database
@pytest.mark.e2e
def test_e08_attach_then_detach_leaves_the_document_unchanged(canonical: Canonical) -> None:
    """AC-016, AC-017."""
    document_id = canonical.mine.document_id

    def document_rows() -> tuple[int, int, int]:
        return (
            canonical.count(managed_documents, document_id=document_id),
            canonical.count(managed_document_versions, document_id=document_id),
            canonical.count(managed_document_lifecycle_events, document_id=document_id),
        )

    before = document_rows()
    created = _create(canonical, "e08-create", attachment_document_ids=[document_id])
    attachment = created["meeting"]["attachments"][0]
    assert attachment["document_id"] == document_id
    assert attachment["availability"] == "active"
    detached = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": created["meeting"]["meeting_id"],
            "expected_version": 1,
            "idempotency_key": "e08-detach",
            "attachment_remove_ids": [attachment["attachment_id"]],
        },
    )["meeting"]
    assert detached["attachments"] == []
    assert document_rows() == before


@pytest.mark.database
@pytest.mark.e2e
def test_e09_notes_append_replace_and_identical_replace(canonical: Canonical) -> None:
    """AC-019."""
    meeting_id = _create(canonical, "e09-create", notes_markdown="First line.")["meeting"][
        "meeting_id"
    ]
    appended = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 1,
            "idempotency_key": "e09-append",
            "notes_mode": "append",
            "notes_markdown": "Second line.",
        },
    )["meeting"]
    assert appended["notes"]["body_markdown"] == "First line.\n\nSecond line."
    assert appended["notes"]["version_number"] == 2
    replaced = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 2,
            "idempotency_key": "e09-replace",
            "notes_mode": "replace",
            "notes_markdown": "Replaced.",
        },
    )
    assert replaced["meeting"]["notes"]["body_markdown"] == "Replaced."
    identical = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 3,
            "idempotency_key": "e09-identical",
            "notes_mode": "replace",
            "notes_markdown": "Replaced.",
        },
    )
    assert identical["history"]["outcome"] == "no_op"
    assert identical["meeting"]["version"] == 3
    assert identical["meeting"]["notes"]["version_number"] == 3


@pytest.mark.database
@pytest.mark.e2e
def test_e10_a_closed_own_project_is_accepted_and_a_foreign_one_is_not_found(
    canonical: Canonical,
) -> None:
    """AC-020."""
    created = _create(canonical, "e10-own", project_id=canonical.mine.project_id)
    assert created["meeting"]["project_id"] == canonical.mine.project_id
    foreign = canonical.refused(
        Capability.MEETINGS_CREATE,
        {
            **CREATE_MINIMUM,
            "idempotency_key": "e10-foreign",
            "project_id": canonical.theirs.project_id,
        },
    )
    assert (foreign["code"], foreign["retry"], foreign["safe_details"]) == (
        "not_found",
        "conditional",
        ["project_id"],
    )


@pytest.mark.database
@pytest.mark.e2e
def test_e11_an_absent_and_a_foreign_meeting_read_the_same(canonical: Canonical) -> None:
    """AC-023, AC-032."""
    theirs = canonical.ok(
        Capability.MEETINGS_CREATE,
        {**CREATE_MINIMUM, "idempotency_key": "e11-theirs"},
        as_=canonical.theirs,
    )["meeting"]["meeting_id"]
    absent = make_identifier(IdKind.MEETING, "e11absentmeeting")
    answers = [
        canonical.refused(Capability.MEETINGS_READ, {"meeting_id": identifier})
        for identifier in (absent, theirs)
    ]
    for answer in answers:
        answer.pop("correlation_id")
    assert answers[0] == answers[1]
    assert (answers[0]["code"], answers[0]["retry"], answers[0]["safe_details"]) == (
        "not_found",
        "conditional",
        ["meeting_id"],
    )


@pytest.mark.database
@pytest.mark.e2e
def test_e12_list_pages_by_cursor_and_search_matches_the_current_note_only(
    canonical: Canonical,
) -> None:
    """AC-024, AC-025."""
    project_id = canonical.mine.project_id
    for index in range(3):
        _create(
            canonical,
            f"e12-{index}",
            project_id=project_id,
            start_at=f"2026-10-0{index + 1}T09:00:00Z",
        )
    _create(canonical, "e12-other", start_at="2026-10-05T09:00:00Z")
    first = canonical.send(Capability.MEETINGS_LIST, {"project_id": project_id, "page_size": 2})
    assert first["disclosure"]["truncation"]["is_truncated"] is True
    cursor = first["disclosure"]["truncation"]["next_cursor"]
    second = canonical.ok(
        Capability.MEETINGS_LIST, {"project_id": project_id, "page_size": 2, "after": cursor}
    )
    listed = [entry["start_at"] for entry in first["result"]["meetings"]] + [
        entry["start_at"] for entry in second["meetings"]
    ]
    assert [datetime.fromisoformat(value).day for value in listed] == [1, 2, 3]
    noted = _create(canonical, "e12-noted", notes_markdown="alpha zebra")["meeting"]["meeting_id"]
    canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": noted,
            "expected_version": 1,
            "idempotency_key": "e12-replace",
            "notes_mode": "replace",
            "notes_markdown": "beta yak",
        },
    )
    current = canonical.ok(Capability.MEETINGS_SEARCH, {"query": "yak"})
    historical = canonical.ok(Capability.MEETINGS_SEARCH, {"query": "zebra"})
    assert [entry["meeting_id"] for entry in current["meetings"]] == [noted]
    assert historical["meetings"] == []


@pytest.mark.database
@pytest.mark.e2e
def test_e13_a_combined_update_under_its_version_then_a_stale_one(canonical: Canonical) -> None:
    """AC-026, AC-030."""
    mine = canonical.mine
    meeting_id = _create(canonical, "e13-create")["meeting"]["meeting_id"]
    updated = canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 1,
            "idempotency_key": "e13-combined",
            "attendees_replace": [
                {"entity_id": mine.person_ids[0], "is_organizer": True},
                {"entity_id": mine.person_ids[1], "response_status": "accepted"},
            ],
            "attachment_add_document_ids": [mine.document_id],
            "notes_mode": "append",
            "notes_markdown": "Decisions.",
        },
    )["meeting"]
    assert updated["version"] == 2
    assert updated["attendees"][0]["entity_id"] == mine.person_ids[0]
    assert len(updated["attachments"]) == 1 and updated["notes"]["version_number"] == 1
    stale = canonical.refused(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 1,
            "idempotency_key": "e13-stale",
            "title": "Too late",
        },
    )
    assert (stale["code"], stale["retry"], stale["safe_details"]) == (
        "conflict",
        "after_refresh",
        ["stale_version"],
    )


@pytest.mark.database
@pytest.mark.e2e
def test_e14_a_series_retitle_leaves_every_occurrence_title_alone(canonical: Canonical) -> None:
    """AC-009, AC-027."""
    first = _create(canonical, "e14-first", series_title="Old series title", title="Occurrence")
    series_id = first["series"]["meeting_series_id"]
    second = _create(canonical, "e14-second", meeting_series_id=series_id, title="Occurrence 2")
    retitled = canonical.ok(
        Capability.MEETINGS_SERIES_UPDATE,
        {
            "meeting_series_id": series_id,
            "expected_version": 1,
            "idempotency_key": "e14-retitle",
            "title": "New series title",
        },
    )
    assert retitled["series"]["title"] == "New series title"
    assert retitled["series"]["version"] == 2
    for created, title in ((first, "Occurrence"), (second, "Occurrence 2")):
        read = canonical.ok(
            Capability.MEETINGS_READ, {"meeting_id": created["meeting"]["meeting_id"]}
        )["meeting"]
        assert read["title"] == title
        assert read["version"] == 1
        assert read["series_title"] == "New series title"


@pytest.mark.database
@pytest.mark.e2e
def test_e15_same_key_replays_and_a_different_request_conflicts(canonical: Canonical) -> None:
    """AC-029."""
    original = _create(canonical, "e15-create")
    meeting_id = original["meeting"]["meeting_id"]
    canonical.ok(
        Capability.MEETINGS_UPDATE,
        {
            "meeting_id": meeting_id,
            "expected_version": 1,
            "idempotency_key": "e15-later",
            "title": "Changed later",
        },
    )
    replayed = _create(canonical, "e15-create")
    assert replayed["replayed"] is True
    assert replayed["history"] == original["history"]
    assert replayed["meeting"]["meeting_id"] == meeting_id
    assert replayed["meeting"]["title"] == "Changed later"
    conflict = canonical.refused(
        Capability.MEETINGS_CREATE,
        {**CREATE_MINIMUM, "idempotency_key": "e15-create", "title": "Different"},
    )
    assert (conflict["code"], conflict["safe_details"]) == ("conflict", ["idempotency_conflict"])
