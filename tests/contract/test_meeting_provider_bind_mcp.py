"""WP2-W3: `meetings.provider.bind` admitted at the canonical boundary (FAST).

The capability is declared, dispatched, built and published as one Meeting
write: purpose `meeting_authoring` only, a write, destructive (not additive),
scopeless, not operator-only, remote-stamped for its idempotency key, a `write`
in the compact facade's `meetings` family, and classified for the ChatLLM
profile exactly as `meetings.update` is (a proposal; grants stay operator-gated).
The generated schema publishes the closed `action` and format vocabularies;
the MCP payload normalizes to the domain request; refusals over the service
name a token and never a key value. `MeetingView`/`meetings.read` are unchanged
(Manager ruling D11). The in-memory Meeting fake serves the service cases; the
database evidence is `tests/database/test_meeting_provider_bind.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, get_args

import jsonschema
import pytest
from tests.conftest import Scene, build_service
from tests.contract.test_transport_parity import document

from my_pa.adapters.mcp.chatllm_gateway import facade_kind
from my_pa.adapters.mcp.remote import is_remote_write
from my_pa.adapters.mcp.tools import TOOLS, input_schema_for
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.adapters.remote_request import REMOTE_OWNED_PAYLOAD_FIELDS, remote_tool_schema
from my_pa.application.commands import BindMeetingProvider, Command, ReadMeeting
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.contracts.v1.meetings import MeetingView
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.meeting.model import MEETINGS_PROVIDER_BIND_NAME
from my_pa.domain.meeting_sync.binding import ProviderBindAction
from my_pa.domain.meeting_sync.model import ProviderEventIdFormat
from my_pa.domain.policy.decision import _SCOPELESS

BIND: Final = Capability.MEETINGS_PROVIDER_BIND
PAYLOAD: Final[dict[str, Any]] = {
    "action": "bind",
    "expected_version": 1,
    "idempotency_key": "bind-mcp-0001",
    "calendar_ref": "cal-synthetic",
    "ical_uid": "uid-series@example.invalid",
    "occurrence_original_start_utc": "2026-12-02T09:00:00-05:00",
    "series_ical_uid": "uid-series@example.invalid",
    "provider_event_id": "evt-0001",
    "provider_event_id_format": "mutable",
}


def test_the_capability_is_declared_dispatched_built_and_published() -> None:
    assert BIND.value == MEETINGS_PROVIDER_BIND_NAME == "meetings.provider.bind"
    assert _HANDLERS[BIND].__name__ == "_meetings_provider_bind"
    assert BIND in _BUILDERS
    commands = {member.capability: member for member in get_args(Command.__value__)}
    assert commands[BIND] is BindMeetingProvider
    (tool,) = [tool for tool in TOOLS if tool.name == BIND.value]
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.destructive_hint is True


def test_purpose_write_destructive_scopeless_and_not_operator_only() -> None:
    assert permitted_purposes(BIND) == {Purpose.MEETING_AUTHORING}
    assert is_write_capability(BIND)
    assert is_destructive_capability(BIND)
    assert BIND in _SCOPELESS
    assert not is_operator_only(BIND)
    assert is_remote_write(BIND)
    assert facade_kind(BIND) == "write"


def test_the_chatllm_classification_follows_meetings_update() -> None:
    """A proposal (WP2-W3): the grant and the profile activation stay operator-gated."""
    bind = CHATLLM_CAPABILITY_POLICY[BIND]
    update = CHATLLM_CAPABILITY_POLICY[Capability.MEETINGS_UPDATE]
    assert (bind.classification, bind.family, bind.composition_prerequisite) == (
        update.classification,
        update.family,
        update.composition_prerequisite,
    )
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v15"


def test_the_schema_publishes_the_closed_vocabularies() -> None:
    schema = input_schema_for(BindMeetingProvider)
    payload = schema["properties"]["payload"]
    properties = payload["properties"]
    assert properties["action"]["enum"] == [member.value for member in ProviderBindAction]
    assert properties["provider_event_id_format"]["enum"] == [
        member.value for member in ProviderEventIdFormat
    ]
    assert properties["calendar_ref"]["maxLength"] == 320
    assert properties["ical_uid"]["maxLength"] == 1024
    assert set(payload["required"]) == {
        "action",
        "meeting_id",
        "expected_version",
        "idempotency_key",
    }
    jsonschema.validate({"meeting_id": "mtg_bindmcp000000001", **PAYLOAD}, payload)
    remote = remote_tool_schema(schema)["properties"]["payload"]
    assert not REMOTE_OWNED_PAYLOAD_FIELDS & set(remote["properties"])
    assert "idempotency_key" not in remote["required"]


def test_the_payload_normalizes_to_the_domain_request() -> None:
    _metadata, command = normalize(
        BIND.value,
        document(BIND, "prn_bindmcp000000001", {"meeting_id": "mtg_bindmcp000000001", **PAYLOAD}),
    )
    assert isinstance(command, BindMeetingProvider)
    request = command.meeting_request()
    assert request.action is ProviderBindAction.BIND
    assert request.occurrence_original_start_utc == datetime(2026, 12, 2, 14, tzinfo=UTC)
    assert request.provider_event_id_format is ProviderEventIdFormat.MUTABLE


def test_meeting_view_and_meetings_read_are_unchanged() -> None:
    """Ruling D11: the binding is answered only by the new view."""
    assert not {name for name in MeetingView.model_fields if "provider" in name}
    assert "provider" not in str(input_schema_for(ReadMeeting))


def _invoke(
    service: ApplicationService, principal: Principal, payload: Mapping[str, Any]
) -> ResponseEnvelope:
    metadata, command = normalize(BIND.value, document(BIND, principal.principal_id, payload))
    return service.invoke(metadata, command, principal=principal)


def _problem(envelope: ResponseEnvelope) -> tuple[ErrorCode, tuple[str, ...]]:
    assert envelope.error is not None, envelope.result
    return envelope.error.code, envelope.error.safe_details


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"action": "rebind"}, "action"),
        ({"provider_event_id_format": "stable"}, "provider_event_id_format"),
        ({"series_ical_uid": None}, "series_ical_uid"),
        ({"occurrence_original_start_utc": "2026-12-02T14:00:00"}, "occurrence_original_start_utc"),
        ({"calendar_ref": "c" * 321}, "calendar_ref"),
    ],
)
def test_a_malformed_request_names_its_field_only(
    scene: Scene, overrides: dict[str, Any], detail: str
) -> None:
    payload = {"meeting_id": scene.meeting_id, **PAYLOAD, **overrides}
    payload = {name: value for name, value in payload.items() if value is not None}
    with pytest.raises(InvalidRequestError) as refused:
        normalize(BIND.value, document(BIND, scene.principal.principal_id, payload))
    assert tuple(item.value for item in refused.value.safe_details) == (detail,)
    assert "cal-synthetic" not in str(refused.value)


def test_a_bind_and_an_unbind_over_the_service_answer_ids_and_the_binding(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    single = {
        name: value
        for name, value in PAYLOAD.items()
        if name not in {"occurrence_original_start_utc", "series_ical_uid"}
    }
    bound = _invoke(service, scene.principal, {"meeting_id": scene.meeting_id, **single})
    assert bound.error is None, bound.error
    result = bound.result
    assert result is not None
    assert set(result) == {"meeting_id", "version", "action", "binding", "history", "replayed"}
    assert result["binding"]["ical_uid"] == PAYLOAD["ical_uid"]
    assert "principal_id" not in result["binding"]
    unbound = _invoke(
        service,
        scene.principal,
        {
            "action": "unbind",
            "meeting_id": scene.meeting_id,
            "expected_version": result["version"],
            "idempotency_key": "unbind-mcp-0001",
        },
    )
    assert unbound.error is None, unbound.error
    assert unbound.result is not None
    assert unbound.result["binding"] is None
    # The key value never reaches a refusal: a second unbind names the rule only.
    again = _invoke(
        service,
        scene.principal,
        {
            "action": "unbind",
            "meeting_id": scene.meeting_id,
            "expected_version": unbound.result["version"],
            "idempotency_key": "unbind-mcp-0002",
        },
    )
    assert _problem(again) == (ErrorCode.INVALID_REQUEST, ("meeting_not_provider_bound",))
    assert PAYLOAD["ical_uid"] not in str(again.error)
