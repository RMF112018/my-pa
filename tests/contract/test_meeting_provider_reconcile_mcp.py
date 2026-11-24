"""WP3b-S4: `meetings.provider.review` and `.reconcile` at the canonical boundary (FAST).

Both are declared, dispatched, built and published: the review a read under
`meeting_read` only (MCP `read_only_hint`), the reconcile a destructive write
under `meeting_authoring` only, idempotency key required and remote-stamped;
both scopeless and not operator-only, and `DATA_REQUIRED` in chatllm-data-v16
(Manager ruling D13; grants stay operator-gated). The generated schemas
publish the closed item vocabulary; the payload normalizes to domain items; a
malformed item refuses the whole batch naming `items` and the field; over the
service, a review then a reconcile of marks and a staged-reference bind
completes the pass, and no refusal echoes a key value. The database evidence
is `tests/database/test_meeting_provider_reconcile.py`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, get_args

import jsonschema
import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service
from tests.contract.test_transport_parity import document

from my_pa.adapters.mcp.chatllm_gateway import facade_kind
from my_pa.adapters.mcp.remote import is_remote_write
from my_pa.adapters.mcp.tools import TOOLS, input_schema_for
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.adapters.remote_request import REMOTE_OWNED_PAYLOAD_FIELDS, remote_tool_schema
from my_pa.application.commands import Command, ReconcileMeetingProviders, ReviewMeetingProviders
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.contracts.ports import MeetingSyncEventRecord, MeetingSyncPublicationRecord
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
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
from my_pa.domain.meeting_sync.model import EventStatus, ProviderEventIdFormat
from my_pa.domain.meeting_sync.reconcile import ReconcileItemAction
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.source.registry import issue_identifier

REVIEW: Final = Capability.MEETINGS_PROVIDER_REVIEW
RECONCILE: Final = Capability.MEETINGS_PROVIDER_RECONCILE


def test_both_are_declared_dispatched_built_and_published() -> None:
    assert REVIEW.value == "meetings.provider.review"
    assert RECONCILE.value == "meetings.provider.reconcile"
    assert _HANDLERS[REVIEW].__name__ == "_meetings_provider_review"
    assert _HANDLERS[RECONCILE].__name__ == "_meetings_provider_reconcile"
    assert {REVIEW, RECONCILE} <= set(_BUILDERS)
    commands = {member.capability: member for member in get_args(Command.__value__)}
    assert commands[REVIEW] is ReviewMeetingProviders
    assert commands[RECONCILE] is ReconcileMeetingProviders
    tools = {tool.name: tool for tool in TOOLS}
    review, reconcile = tools[REVIEW.value], tools[RECONCILE.value]
    assert review.annotations is not None and reconcile.annotations is not None
    assert review.annotations.read_only_hint is True
    assert reconcile.annotations.read_only_hint is False
    assert reconcile.annotations.destructive_hint is True


def test_purposes_kinds_scope_and_remote_stamping() -> None:
    assert permitted_purposes(REVIEW) == {Purpose.MEETING_READ}
    assert permitted_purposes(RECONCILE) == {Purpose.MEETING_AUTHORING}
    assert not is_write_capability(REVIEW)
    assert is_write_capability(RECONCILE)
    assert is_destructive_capability(RECONCILE)
    assert {REVIEW, RECONCILE} <= _SCOPELESS
    assert not is_operator_only(REVIEW)
    assert not is_operator_only(RECONCILE)
    assert not is_remote_write(REVIEW)
    assert is_remote_write(RECONCILE)
    assert (facade_kind(REVIEW), facade_kind(RECONCILE)) == ("read", "write")


def test_the_chatllm_v16_classification() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v16"
    for capability, like in (
        (REVIEW, Capability.MEETINGS_READ),
        (RECONCILE, Capability.MEETINGS_PROVIDER_BIND),
    ):
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        model = CHATLLM_CAPABILITY_POLICY[like]
        assert policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
        assert (policy.family, policy.composition_prerequisite) == (
            model.family,
            model.composition_prerequisite,
        )


def test_the_schemas_publish_the_closed_item_vocabulary() -> None:
    review = input_schema_for(ReviewMeetingProviders)["properties"]["payload"]
    assert review["properties"]["page_size"]["maximum"] == 100
    assert not review.get("required")
    schema = input_schema_for(ReconcileMeetingProviders)
    payload = schema["properties"]["payload"]
    items = payload["properties"]["items"]
    assert (items["minItems"], items["maxItems"]) == (0, 50)
    item = items["items"]
    assert item["properties"]["action"]["enum"] == [m.value for m in ReconcileItemAction]
    assert item["properties"]["provider_event_id_format"]["enum"] == [
        m.value for m in ProviderEventIdFormat
    ]
    assert item["properties"]["adopt_provider_series"]["type"] == "boolean"
    assert set(item["required"]) == {"action", "meeting_id"}
    assert set(payload["required"]) == {"items", "idempotency_key"}
    jsonschema.validate(
        {
            "items": [{"action": "no_provider_event", "meeting_id": "mtg_reconcilemcp0001"}],
            "idempotency_key": "k",
        },
        payload,
    )
    remote = remote_tool_schema(schema)["properties"]["payload"]
    assert not REMOTE_OWNED_PAYLOAD_FIELDS & set(remote["properties"])
    assert "idempotency_key" not in remote["required"]


def test_the_payload_normalizes_to_domain_items() -> None:
    _metadata, command = normalize(
        RECONCILE.value,
        document(
            RECONCILE,
            "prn_reconcilemcp0001",
            {
                "items": [
                    {
                        "action": "bind",
                        "meeting_id": "mtg_reconcilemcp0001",
                        "expected_version": 3,
                        "calendar_ref": "cal-synthetic",
                        "ical_uid": "uid-series@example.invalid",
                        "series_ical_uid": "uid-series@example.invalid",
                        "occurrence_original_start_utc": "2026-12-02T09:00:00-05:00",
                        "adopt_provider_series": True,
                    },
                    {"action": "no_provider_event", "meeting_id": "mtg_reconcilemcp0002"},
                ],
                "idempotency_key": "batch-mcp-0001",
            },
        ),
    )
    assert isinstance(command, ReconcileMeetingProviders)
    first, second = command.reconcile_items()
    assert first.action is ReconcileItemAction.BIND
    assert first.occurrence_original_start_utc == datetime(2026, 12, 2, 14, tzinfo=UTC)
    assert first.adopt_provider_series
    assert second.action is ReconcileItemAction.NO_PROVIDER_EVENT


@pytest.mark.parametrize(
    ("item", "detail"),
    [
        ({"action": "rebind", "meeting_id": "mtg_reconcilemcp0001"}, "action"),
        ({"action": "bind", "meeting_id": "mser_reconcilemcp001"}, "meeting_id"),
        (
            {"action": "no_provider_event", "meeting_id": "mtg_reconcilemcp0001", "extra": 1},
            None,
        ),
        (
            {"action": "bind", "meeting_id": "mtg_reconcilemcp0001", "expected_version": 1},
            "provider_event_ref",
        ),
        (
            {
                "action": "bind",
                "meeting_id": "mtg_reconcilemcp0001",
                "expected_version": 1,
                "provider_event_ref": "mtg_reconcilemcp0001",
            },
            "provider_event_ref",
        ),
        (
            {
                "action": "bind",
                "meeting_id": "mtg_reconcilemcp0001",
                "expected_version": 1,
                "calendar_ref": "cal-secret-value",
                "ical_uid": "uid-secret-value",
                "series_ical_uid": "uid-secret-value",
            },
            "occurrence_original_start_utc",
        ),
    ],
)
def test_a_malformed_item_refuses_the_batch_naming_items_and_the_field(
    item: dict[str, Any], detail: str | None
) -> None:
    with pytest.raises(InvalidRequestError) as refused:
        normalize(
            RECONCILE.value,
            document(
                RECONCILE,
                "prn_reconcilemcp0001",
                {"items": [item], "idempotency_key": "batch-mcp-0001"},
            ),
        )
    details = tuple(d.value for d in refused.value.safe_details)
    assert details == (("items",) if detail is None else ("items", detail))
    assert "secret-value" not in str(refused.value)


def _invoke(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
) -> ResponseEnvelope:
    metadata, command = normalize(
        capability.value, document(capability, principal.principal_id, payload)
    )
    return service.invoke(metadata, command, principal=principal)


def _stage(scene: Scene) -> str:
    principal_id = scene.principal.principal_id
    snapshot_id = issue_identifier(IdKind.INGEST_SNAPSHOT)
    event_id = issue_identifier(IdKind.MEETING_SYNC_EVENT)
    at = datetime(2026, 8, 1, tzinfo=UTC)
    with FakeUnitOfWork(scene.world) as unit:
        unit.meeting_sync.insert_publication(
            principal_id,
            MeetingSyncPublicationRecord(
                snapshot_id=snapshot_id,
                ingest_source_id="isrc_reconcilemcp001",
                generated_at_utc=at,
                record_count=1,
                accepted_count=1,
                quarantined_count=0,
                staged_at=at,
            ),
        )
        unit.meeting_sync.insert_events(
            principal_id,
            [
                MeetingSyncEventRecord(
                    event_id=event_id,
                    snapshot_id=snapshot_id,
                    record_ordinal=0,
                    calendar_ref="cal-synthetic",
                    ical_uid="uid-reconcile-mcp@example.invalid",
                    series_ical_uid=None,
                    occurrence_original_start_utc=None,
                    start_utc=at,
                    end_utc=at,
                    timezone_name="UTC",
                    status=EventStatus.CONFIRMED,
                    title="Provider title",
                    location_text=None,
                    virtual_meeting_url=None,
                    provider_event_id=None,
                    provider_event_id_format=ProviderEventIdFormat.UNKNOWN,
                    staged_at=at,
                )
            ],
        )
    return event_id


def test_review_then_reconcile_over_the_service_completes_the_pass(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    ref = _stage(scene)
    reviewed = _invoke(service, scene.principal, REVIEW, {})
    assert reviewed.error is None, reviewed.error
    result = reviewed.result
    assert result is not None
    assert set(result) == {"pass", "unreviewed_meetings", "next_after", "unbound_provider_events"}
    assert result["pass"]["state"] == "pending"
    meetings = result["unreviewed_meetings"]
    assert {m["meeting_id"] for m in meetings} >= {scene.meeting_id}
    (event,) = result["unbound_provider_events"]
    assert event["provider_event_ref"] == ref
    assert event["suppressed"] is False
    assert not {"description", "attendees", "virtual_meeting_url"} & set(meetings[0])

    items: list[dict[str, Any]] = [
        {"action": "no_provider_event", "meeting_id": m["meeting_id"]}
        for m in meetings
        if m["meeting_id"] != scene.meeting_id
    ]
    target = next(m for m in meetings if m["meeting_id"] == scene.meeting_id)
    items.append(
        {
            "action": "bind",
            "meeting_id": scene.meeting_id,
            "expected_version": target["version"],
            "provider_event_ref": ref,
        }
    )
    reconciled = _invoke(
        service, scene.principal, RECONCILE, {"items": items, "idempotency_key": "batch-mcp-1"}
    )
    assert reconciled.error is None, reconciled.error
    answer = reconciled.result
    assert answer is not None
    assert set(answer) == {"items", "pass", "sync_enabled"}
    bound = answer["items"][-1]
    assert bound["outcome"] == "bound"
    assert bound["binding"]["ical_uid"] == "uid-reconcile-mcp@example.invalid"
    assert answer["pass"]["state"] == "complete"
    assert answer["sync_enabled"] is True

    # A stale item is refused with a token and never echoes the key.
    stale = _invoke(
        service,
        scene.principal,
        RECONCILE,
        {
            "items": [
                {
                    "action": "bind",
                    "meeting_id": scene.meeting_id,
                    "expected_version": 99,
                    "calendar_ref": "cal-synthetic",
                    "ical_uid": "uid-never-echoed@example.invalid",
                }
            ],
            "idempotency_key": "batch-mcp-2",
        },
    )
    assert stale.error is None
    assert stale.result is not None
    (refused,) = stale.result["items"]
    assert refused["outcome"] == "refused"
    assert refused["refusal"] == {"code": "conflict", "detail": "stale_version"}
    assert "uid-never-echoed" not in str(stale.result)
