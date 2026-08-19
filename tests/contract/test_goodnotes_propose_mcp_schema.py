"""`goodnotes.propose` nested segments must be discoverable from tools/list.

A fresh ChatLLM session constructs note-unit.v2 from the published MCP schema.
Runtime validation is unchanged: malformed nested contracts still fail closed.
"""

from __future__ import annotations

from typing import Any, get_args

import pytest
from tests.conftest import Scene, build_service
from tests.transports import mcp_transport

from my_pa.adapters.mcp.tools import TOOLS, payload_schema_for
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import REMOTE_OWNED_PAYLOAD_FIELDS, remote_tool_schema
from my_pa.application.commands import Command, SubmitGoodNotesProposal
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.goodnotes.models import (
    NOTE_UNIT_SCHEMA_V2,
    GoodNotesNoteClass,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
)
from my_pa.domain.identity.operation import Capability

_COMMANDS = {member.capability: member for member in get_args(Command.__value__)}
PROPOSE_TOOL = next(tool for tool in TOOLS if tool.name == Capability.GOODNOTES_PROPOSE.value)


def _payload_schema(schema: dict[str, Any]) -> dict[str, Any]:
    payload = schema["properties"]["payload"]
    assert isinstance(payload, dict)
    return payload


def test_published_segments_items_are_typed_objects_not_bare_dicts() -> None:
    payload = _payload_schema(PROPOSE_TOOL.input_schema)
    segments = payload["properties"]["segments"]
    items = segments["items"]
    properties = items["properties"]
    assert segments["type"] == "array"
    assert segments["minItems"] == 1
    assert items["type"] == "object"
    assert items["additionalProperties"] is False
    assert set(items["required"]) == {"kind", "geometry"}
    assert properties["kind"]["enum"] == [member.value for member in GoodNotesSegmentKind]
    assert set(properties["primary_class"]["enum"]) == {
        member.value for member in GoodNotesNoteClass
    } | {None}
    assert set(properties["transcription_status"]["enum"]) == {
        member.value for member in GoodNotesTranscriptionStatus
    } | {None}
    assert properties["transcription"]["type"] == ["string", "null"]
    assert properties["crop_sha256"]["type"] == ["string", "null"]
    assert properties["confidence"]["type"] == ["object", "null"]
    geometry = properties["geometry"]
    assert set(geometry["required"]) == {"x_min", "y_min", "width", "height"}
    assert set(geometry["properties"]) == {"x_min", "y_min", "width", "height"}
    assert "candidate_tags" in properties
    assert "ranked_candidates" in properties
    ranked = properties["ranked_candidates"]["items"]["properties"]
    assert {"rank", "candidate"} <= set(ranked)
    confidence = properties["confidence"]["properties"]
    assert {"transcription", "segmentation", "classification", "linking"} <= set(confidence)
    assert payload["properties"]["schema_version"]["enum"] == ["note-unit.v1", "note-unit.v2"]
    assert "segments[]" in (PROPOSE_TOOL.description or "")


def test_remote_schema_keeps_nested_segments_and_hides_idempotency() -> None:
    remote = remote_tool_schema(PROPOSE_TOOL.input_schema)
    payload = _payload_schema(remote)
    properties = payload["properties"]
    assert "idempotency_key" not in properties
    assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(properties)
    items = properties["segments"]["items"]["properties"]
    assert "kind" in items
    assert "geometry" in items
    assert "transcription_status" in items


def test_fresh_client_can_build_note_unit_v2_from_published_schema_alone() -> None:
    payload = _payload_schema(PROPOSE_TOOL.input_schema)
    segment_fields = payload["properties"]["segments"]["items"]["properties"]
    geometry_fields = segment_fields["geometry"]["properties"]
    ranked_fields = segment_fields["ranked_candidates"]["items"]["properties"]
    confidence_fields = segment_fields["confidence"]["properties"]
    assert set(geometry_fields) == {"x_min", "y_min", "width", "height"}
    assert {"rank", "candidate"} <= set(ranked_fields)
    assert {"transcription", "segmentation", "classification", "linking"} <= set(confidence_fields)

    document = {
        "run_id": "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
        "page_version_id": "gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
        "content_sha256": "a" * 64,
        "schema_version": NOTE_UNIT_SCHEMA_V2,
        "analyzer_name": "chatllm-goodnotes-semantic",
        "analyzer_version": "sit-1.0",
        "idempotency_key": "schema-discoverability-goodnotes-propose-0001",
        "segments": [
            {
                "kind": "NOTE_UNIT",
                "geometry": {
                    "x_min": 0.0874,
                    "y_min": 0.3428,
                    "width": 0.6871,
                    "height": 0.1143,
                },
                "transcription": "Follow up on crane plan Friday",
                "primary_class": "MEETING",
                "candidate_tags": ["FOLLOW_UP_CANDIDATE", "TASK_CANDIDATE"],
                "ranked_candidates": [{"rank": 1, "candidate": "Weekly Coordination Meeting"}],
                "confidence": {
                    "transcription": 0.97,
                    "segmentation": 0.99,
                    "classification": 0.95,
                    "linking": 0.88,
                },
                "transcription_status": "CLEAR",
            }
        ],
    }
    unknown = set(document["segments"][0]) - set(segment_fields)
    assert not unknown
    command = SubmitGoodNotesProposal(
        **{  # type: ignore[arg-type]
            **document,
            "segments": tuple(document["segments"]),
            "candidate_tags": (),
            "ranked_candidates": (),
        }
    )
    assert command.schema_version == NOTE_UNIT_SCHEMA_V2
    assert command.segments[0]["kind"] == "NOTE_UNIT"
    assert command.segments[0]["transcription_status"] == "CLEAR"


def test_v1_geometry_only_segment_still_admits() -> None:
    command = SubmitGoodNotesProposal(
        run_id="gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_version_id="gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
        content_sha256="b" * 64,
        schema_version="note-unit.v1",
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key="schema-discoverability-goodnotes-propose-v1",
        segments=(
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
                "transcription": "synthetic note",
            },
        ),
    )
    assert command.schema_version == "note-unit.v1"
    assert "transcription_status" not in command.segments[0]


def test_malformed_top_level_tags_without_nested_segment_fields_still_fail_closed() -> None:
    with pytest.raises(InvalidRequestError):
        SubmitGoodNotesProposal(
            run_id="gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
            page_version_id="gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
            content_sha256="c" * 64,
            schema_version=NOTE_UNIT_SCHEMA_V2,
            analyzer_name="synthetic",
            analyzer_version="1",
            idempotency_key="schema-discoverability-goodnotes-propose-malformed",
            segments=("Follow up on crane plan Friday",),  # type: ignore[arg-type]
        )


def test_normalize_accepts_json_arrays_for_the_published_nested_shape() -> None:
    metadata, command = normalize(
        Capability.GOODNOTES_PROPOSE.value,
        {
            "contract_version": "v1",
            "request_id": "req-schema-discoverability-001",
            "purpose": "goodnotes_proposal",
            "principal_id": "prn_24abf5d2d0c25e1c82f6e72425e9ed37",
            "requested_at": "2026-08-19T19:00:00.000Z",
            "scope": {"source_ids": [], "enrollment_ids": []},
            "payload": {
                "run_id": "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
                "page_version_id": "gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
                "content_sha256": "d" * 64,
                "schema_version": NOTE_UNIT_SCHEMA_V2,
                "analyzer_name": "chatllm-goodnotes-semantic",
                "analyzer_version": "sit-1.0",
                "idempotency_key": "schema-discoverability-goodnotes-propose-normalize",
                "segments": [
                    {
                        "kind": "NOTE_UNIT",
                        "geometry": {
                            "x_min": 0.1,
                            "y_min": 0.2,
                            "width": 0.3,
                            "height": 0.1,
                        },
                        "transcription": "Follow up on crane plan Friday",
                        "primary_class": "MEETING",
                        "candidate_tags": ["FOLLOW_UP_CANDIDATE"],
                        "ranked_candidates": [
                            {"rank": 1, "candidate": "Weekly Coordination Meeting"}
                        ],
                        "confidence": {"transcription": 0.97},
                        "transcription_status": "CLEAR",
                    }
                ],
            },
        },
    )
    assert metadata.capability is Capability.GOODNOTES_PROPOSE
    assert isinstance(command, SubmitGoodNotesProposal)
    assert command.segments[0]["primary_class"] == "MEETING"


def test_command_overlay_is_the_same_mapping_payload_schema_uses() -> None:
    published = payload_schema_for(_COMMANDS[Capability.GOODNOTES_PROPOSE])
    overlay = vars(SubmitGoodNotesProposal)["mcp_payload_properties"]
    assert (
        published["properties"]["segments"]["items"]["properties"]["kind"]
        == overlay["segments"]["items"]["properties"]["kind"]
    )


def test_explicit_null_optional_fields_still_admit() -> None:
    command = SubmitGoodNotesProposal(
        run_id="gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
        page_version_id="gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
        content_sha256="e" * 64,
        schema_version=NOTE_UNIT_SCHEMA_V2,
        analyzer_name="synthetic",
        analyzer_version="1",
        idempotency_key="schema-discoverability-goodnotes-propose-nulls",
        segments=(
            {
                "kind": "NOTE_UNIT",
                "geometry": {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2},
                "crop_sha256": None,
                "transcription": None,
                "primary_class": None,
                "confidence": None,
                "transcription_status": None,
            },
        ),
        confidence=None,
    )
    assert command.segments[0]["transcription"] is None
    assert command.confidence is None


def test_tools_list_protocol_publishes_nested_segments(scene: Scene) -> None:
    with mcp_transport(build_service(scene.world, scene.providers), scene.principal) as session:
        listed = session.list_tools()
    tool = next(entry for entry in listed.tools if entry.name == Capability.GOODNOTES_PROPOSE.value)
    payload = _payload_schema(tool.input_schema)
    items = payload["properties"]["segments"]["items"]["properties"]
    assert items["kind"]["enum"] == [member.value for member in GoodNotesSegmentKind]
    assert "geometry" in items
    assert "transcription_status" in items
    remote = remote_tool_schema(tool.input_schema)
    assert "idempotency_key" not in remote["properties"]["payload"]["properties"]
