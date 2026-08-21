"""`goodnotes.propose` nested segments must be discoverable from tools/list.

A fresh ChatLLM session constructs note-unit.v2 from the published MCP schema.
Runtime validation is unchanged: malformed nested contracts still fail closed.
The published schema must discriminate SOURCE_CONTEXT from NOTE_UNIT and
note-unit.v1 from note-unit.v2; a field-superset overlay is not sufficient.
"""

from __future__ import annotations

import json
from typing import Any, get_args

import jsonschema
import pytest
from tests.conftest import Scene, build_service
from tests.transports import mcp_transport

from my_pa.adapters.mcp.tools import TOOLS, payload_schema_for
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import REMOTE_OWNED_PAYLOAD_FIELDS, remote_tool_schema
from my_pa.application import commands as command_module
from my_pa.application.commands import Command, SubmitGoodNotesProposal
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.goodnotes.models import (
    NOTE_UNIT_SCHEMA_V1,
    NOTE_UNIT_SCHEMA_V2,
    GoodNotesNoteClass,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
)
from my_pa.domain.identity.operation import Capability

_COMMANDS = {member.capability: member for member in get_args(Command.__value__)}
PROPOSE_TOOL = next(tool for tool in TOOLS if tool.name == Capability.GOODNOTES_PROPOSE.value)
_GEOMETRY = {"x_min": 0.1, "y_min": 0.1, "width": 0.2, "height": 0.2}
_V2_NOTE_UNIT_EXTENSIONS = frozenset(
    {"candidate_tags", "ranked_candidates", "confidence", "transcription_status"}
)


def _payload_schema(schema: dict[str, Any]) -> dict[str, Any]:
    payload = schema["properties"]["payload"]
    assert isinstance(payload, dict)
    return payload


def _published_payload() -> dict[str, Any]:
    return _payload_schema(PROPOSE_TOOL.input_schema)


def _variant(items: dict[str, Any], kind: str) -> dict[str, Any]:
    matches = [
        branch
        for branch in items["oneOf"]
        if branch.get("properties", {}).get("kind", {}).get("const") == kind
    ]
    assert len(matches) == 1, f"expected one {kind} variant, got {len(matches)}"
    return matches[0]


def _v2_items(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["properties"]["segments"]["items"]


def _v1_items(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["then"]["properties"]["segments"]["items"]


def _schema_admits(payload: dict[str, Any], document: dict[str, Any]) -> bool:
    return jsonschema.Draft202012Validator(payload).is_valid(document)


def _runtime_error(document: dict[str, Any]) -> InvalidRequestError | None:
    try:
        SubmitGoodNotesProposal(
            **{  # type: ignore[arg-type]
                **document,
                "segments": tuple(document["segments"]),
                "candidate_tags": tuple(document.get("candidate_tags", ())),
                "ranked_candidates": tuple(document.get("ranked_candidates", ())),
            }
        )
    except InvalidRequestError as error:
        return error
    return None


def _proposal_document(
    schema_version: str,
    segments: list[dict[str, Any]],
    *,
    suffix: str = "parity",
) -> dict[str, Any]:
    return {
        "run_id": "gnrun_aaaaaaaaaaaaaaaaaaaaaaaa",
        "page_version_id": "gnver_bbbbbbbbbbbbbbbbbbbbbbbb",
        "content_sha256": "a" * 64,
        "schema_version": schema_version,
        "analyzer_name": "synthetic",
        "analyzer_version": "1",
        "idempotency_key": f"schema-variant-goodnotes-propose-{suffix}",
        "segments": segments,
    }


def _source_context(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "kind": "SOURCE_CONTEXT",
        "geometry": dict(_GEOMETRY),
    }
    values.update(overrides)
    return values


def _note_unit(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "kind": "NOTE_UNIT",
        "geometry": dict(_GEOMETRY),
        "transcription": "synthetic handwriting",
        "primary_class": "MEETING",
    }
    values.update(overrides)
    return values


def test_published_segment_property_sets_match_runtime_constants() -> None:
    payload = _published_payload()
    source = _variant(_v2_items(payload), "SOURCE_CONTEXT")
    note_v2 = _variant(_v2_items(payload), "NOTE_UNIT")
    note_v1 = _variant(_v1_items(payload), "NOTE_UNIT")
    v1_source = _variant(_v1_items(payload), "SOURCE_CONTEXT")
    assert set(source["properties"]) == command_module._V1_SEGMENT_KEYS
    assert set(v1_source["properties"]) == command_module._V1_SEGMENT_KEYS
    assert set(note_v1["properties"]) == command_module._V1_SEGMENT_KEYS
    assert set(note_v2["properties"]) == command_module._V2_NOTE_UNIT_KEYS
    assert frozenset(command_module._SEGMENT_KEY_ORDER) == command_module._V2_NOTE_UNIT_KEYS
    assert source["properties"]["kind"]["const"] == GoodNotesSegmentKind.SOURCE_CONTEXT.value
    assert note_v2["properties"]["kind"]["const"] == GoodNotesSegmentKind.NOTE_UNIT.value
    assert note_v1["properties"]["kind"]["const"] == GoodNotesSegmentKind.NOTE_UNIT.value
    assert source is v1_source


def test_published_segments_are_kind_and_version_discriminated() -> None:
    payload = _published_payload()
    items = _v2_items(payload)
    source = _variant(items, "SOURCE_CONTEXT")
    note = _variant(items, "NOTE_UNIT")
    assert items["oneOf"]
    assert source["additionalProperties"] is False
    assert note["additionalProperties"] is False
    assert set(source["required"]) == {"kind", "geometry"}
    assert set(note["required"]) == {"kind", "geometry"}
    assert _V2_NOTE_UNIT_EXTENSIONS.isdisjoint(source["properties"])
    assert set(note["properties"]) >= _V2_NOTE_UNIT_EXTENSIONS
    geometry = source["properties"]["geometry"]
    assert set(geometry["required"]) == {"x_min", "y_min", "width", "height"}
    assert set(geometry["properties"]) == {"x_min", "y_min", "width", "height"}
    assert set(note["properties"]["primary_class"]["enum"]) == {
        member.value for member in GoodNotesNoteClass
    } | {None}
    assert set(note["properties"]["transcription_status"]["enum"]) == {
        member.value for member in GoodNotesTranscriptionStatus
    } | {None}
    assert note["properties"]["transcription"]["type"] == ["string", "null"]
    assert note["properties"]["crop_sha256"]["type"] == ["string", "null"]
    assert note["properties"]["confidence"]["type"] == ["object", "null"]
    ranked = note["properties"]["ranked_candidates"]["items"]["properties"]
    assert {"rank", "candidate"} <= set(ranked)
    confidence = note["properties"]["confidence"]["properties"]
    assert {"transcription", "segmentation", "classification", "linking"} <= set(confidence)
    assert payload["properties"]["schema_version"]["enum"] == ["note-unit.v1", "note-unit.v2"]
    assert payload["if"]["properties"]["schema_version"]["const"] == NOTE_UNIT_SCHEMA_V1
    v1_note = _variant(_v1_items(payload), "NOTE_UNIT")
    assert _V2_NOTE_UNIT_EXTENSIONS.isdisjoint(v1_note["properties"])
    description = PROPOSE_TOOL.description or ""
    assert "SOURCE_CONTEXT" in description
    assert "NOTE_UNIT" in description
    assert "segments[]" in description or "segments" in description


@pytest.mark.parametrize("schema_version", [NOTE_UNIT_SCHEMA_V1, NOTE_UNIT_SCHEMA_V2])
def test_source_context_geometry_only_is_admitted(schema_version: str) -> None:
    payload = _published_payload()
    document = _proposal_document(
        schema_version, [_source_context()], suffix=f"sc-geo-{schema_version}"
    )
    assert _schema_admits(payload, document)
    assert _runtime_error(document) is None


@pytest.mark.parametrize("schema_version", [NOTE_UNIT_SCHEMA_V1, NOTE_UNIT_SCHEMA_V2])
def test_source_context_transcription_is_admitted(schema_version: str) -> None:
    payload = _published_payload()
    document = _proposal_document(
        schema_version,
        [_source_context(transcription="Weekly Coordination Meeting")],
        suffix=f"sc-text-{schema_version}",
    )
    assert _schema_admits(payload, document)
    assert _runtime_error(document) is None


@pytest.mark.parametrize("schema_version", [NOTE_UNIT_SCHEMA_V1, NOTE_UNIT_SCHEMA_V2])
@pytest.mark.parametrize(
    "extra",
    [
        {"transcription_status": "CLEAR"},
        {"candidate_tags": ["FOLLOW_UP_CANDIDATE"]},
        {"ranked_candidates": [{"rank": 1, "candidate": "Weekly Coordination Meeting"}]},
        {"confidence": {"transcription": 0.9}},
    ],
)
def test_source_context_rejects_note_unit_v2_fields(
    schema_version: str, extra: dict[str, object]
) -> None:
    payload = _published_payload()
    document = _proposal_document(
        schema_version,
        [_source_context(transcription="Weekly Coordination Meeting", **extra)],
        suffix=f"sc-extra-{next(iter(extra))}-{schema_version}",
    )
    assert not _schema_admits(payload, document)
    error = _runtime_error(document)
    assert error is not None
    assert error.safe_details == (SafeDetail.SEGMENTS,)


def test_v1_note_unit_base_fields_are_admitted() -> None:
    payload = _published_payload()
    document = _proposal_document(NOTE_UNIT_SCHEMA_V1, [_note_unit()], suffix="nu-v1-base")
    assert _schema_admits(payload, document)
    assert _runtime_error(document) is None


@pytest.mark.parametrize(
    "extra",
    [
        {"transcription_status": "CLEAR"},
        {"candidate_tags": ["FOLLOW_UP_CANDIDATE"]},
        {"ranked_candidates": [{"rank": 1, "candidate": "Weekly Coordination Meeting"}]},
        {"confidence": {"transcription": 0.9}},
    ],
)
def test_v1_note_unit_rejects_v2_fields(extra: dict[str, object]) -> None:
    payload = _published_payload()
    document = _proposal_document(
        NOTE_UNIT_SCHEMA_V1,
        [_note_unit(**extra)],
        suffix=f"nu-v1-extra-{next(iter(extra))}",
    )
    assert not _schema_admits(payload, document)
    error = _runtime_error(document)
    assert error is not None
    assert error.safe_details == (SafeDetail.SEGMENTS,)


def test_v2_note_unit_admits_enrichment_fields() -> None:
    payload = _published_payload()
    document = _proposal_document(
        NOTE_UNIT_SCHEMA_V2,
        [
            _note_unit(
                candidate_tags=["FOLLOW_UP_CANDIDATE", "TASK_CANDIDATE"],
                ranked_candidates=[{"rank": 1, "candidate": "Weekly Coordination Meeting"}],
                confidence={
                    "transcription": 0.97,
                    "segmentation": 0.99,
                    "classification": 0.95,
                    "linking": 0.88,
                },
                transcription_status="CLEAR",
            )
        ],
        suffix="nu-v2-full",
    )
    assert _schema_admits(payload, document)
    assert _runtime_error(document) is None


def test_malformed_v2_nested_fields_remain_fail_closed() -> None:
    payload = _published_payload()
    document = _proposal_document(
        NOTE_UNIT_SCHEMA_V2,
        [_note_unit(ranked_candidates=[{"candidate": "Weekly Coordination Meeting"}])],
        suffix="nu-v2-malformed-rank",
    )
    assert not _schema_admits(payload, document)
    error = _runtime_error(document)
    assert error is not None
    assert error.safe_details == (SafeDetail.RANKED_CANDIDATES,)


def test_ranked_candidate_and_nested_exact_key_schema_runtime_parity() -> None:
    payload = _published_payload()
    note = _variant(_v2_items(payload), "NOTE_UNIT")
    ranked_items = note["properties"]["ranked_candidates"]["items"]
    assert ranked_items["additionalProperties"] is False
    assert set(ranked_items["required"]) == {"rank", "candidate"}
    assert note["properties"]["geometry"]["additionalProperties"] is False
    assert note["properties"]["confidence"]["additionalProperties"] is False
    valid = _proposal_document(
        NOTE_UNIT_SCHEMA_V2,
        [_note_unit(ranked_candidates=[{"rank": 1, "candidate": "Project Alpha"}])],
        suffix="ranked-exact",
    )
    assert _schema_admits(payload, valid)
    assert _runtime_error(valid) is None
    extra_ranked = _proposal_document(
        NOTE_UNIT_SCHEMA_V2,
        [
            _note_unit(
                ranked_candidates=[
                    {"rank": 1, "candidate": "Project Alpha", "extra": "runtime rejects this"}
                ]
            )
        ],
        suffix="ranked-extra",
    )
    assert not _schema_admits(payload, extra_ranked)
    extra_error = _runtime_error(extra_ranked)
    assert extra_error is not None
    assert extra_error.safe_details == (SafeDetail.RANKED_CANDIDATES,)
    extra_geometry = _proposal_document(
        NOTE_UNIT_SCHEMA_V2,
        [_note_unit(geometry={**_GEOMETRY, "extra": 0})],
        suffix="geometry-extra",
    )
    assert not _schema_admits(payload, extra_geometry)
    geometry_error = _runtime_error(extra_geometry)
    assert geometry_error is not None
    assert geometry_error.safe_details == (SafeDetail.GEOMETRY,)
    extra_confidence = _proposal_document(
        NOTE_UNIT_SCHEMA_V2,
        [_note_unit(confidence={"transcription": 0.9, "extra": 0.1})],
        suffix="confidence-extra",
    )
    assert not _schema_admits(payload, extra_confidence)
    confidence_error = _runtime_error(extra_confidence)
    assert confidence_error is not None
    assert confidence_error.safe_details == (SafeDetail.CONFIDENCE,)


def test_remote_schema_keeps_discriminated_segments_and_hides_idempotency() -> None:
    remote = remote_tool_schema(PROPOSE_TOOL.input_schema)
    payload = _payload_schema(remote)
    properties = payload["properties"]
    assert "idempotency_key" not in properties
    assert REMOTE_OWNED_PAYLOAD_FIELDS.isdisjoint(properties)
    source = _variant(_v2_items(payload), "SOURCE_CONTEXT")
    note = _variant(_v2_items(payload), "NOTE_UNIT")
    assert "transcription_status" not in source["properties"]
    assert "transcription_status" in note["properties"]
    assert payload["if"]["properties"]["schema_version"]["const"] == NOTE_UNIT_SCHEMA_V1
    assert _V2_NOTE_UNIT_EXTENSIONS.isdisjoint(
        _variant(_v1_items(payload), "NOTE_UNIT")["properties"]
    )


def _construct_clean_room_v2_from_public_schema(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a first proposal using only tools/list-visible schema structure."""
    items = _v2_items(payload)
    source_variant = _variant(items, "SOURCE_CONTEXT")
    note_variant = _variant(items, "NOTE_UNIT")
    source_example = source_variant["examples"][0]
    note_example = note_variant["examples"][0]
    assert isinstance(source_example, dict)
    assert isinstance(note_example, dict)
    source = {
        key: value for key, value in source_example.items() if key in source_variant["properties"]
    }
    note = {key: value for key, value in note_example.items() if key in note_variant["properties"]}
    versions = payload["properties"]["schema_version"]["enum"]
    schema_version = next(version for version in versions if str(version).endswith(".v2"))
    return _proposal_document(
        schema_version,
        [source, note],
        suffix="clean-room-valid",
    )


def test_fresh_client_can_build_valid_v2_request_from_published_schema_alone() -> None:
    payload = _published_payload()
    document = _construct_clean_room_v2_from_public_schema(payload)
    source, note = document["segments"]
    assert source["kind"] == "SOURCE_CONTEXT"
    assert set(source).isdisjoint(_V2_NOTE_UNIT_EXTENSIONS)
    assert note["kind"] == "NOTE_UNIT"
    assert "transcription_status" in note
    assert _schema_admits(payload, document)
    assert _runtime_error(document) is None


def test_public_schema_rejects_the_live_clean_room_source_context_status_shape() -> None:
    payload = _published_payload()
    valid = _construct_clean_room_v2_from_public_schema(payload)
    failed = {
        **valid,
        "segments": [
            {**valid["segments"][0], "transcription_status": "CLEAR"},
            valid["segments"][1],
        ],
    }
    assert not _schema_admits(payload, failed)
    error = _runtime_error(failed)
    assert error is not None
    assert error.safe_details == (SafeDetail.SEGMENTS,)


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
    assert published["properties"]["segments"]["items"] == overlay["segments"]["items"]
    assert published["if"] == overlay["if"]
    assert published["then"] == overlay["then"]


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


def test_tools_list_protocol_preserves_kind_and_version_discrimination(scene: Scene) -> None:
    with mcp_transport(build_service(scene.world, scene.providers), scene.principal) as session:
        listed = session.list_tools()
    tool = next(entry for entry in listed.tools if entry.name == Capability.GOODNOTES_PROPOSE.value)
    wire = json.loads(json.dumps(tool.input_schema))
    payload = _payload_schema(wire)
    items = _v2_items(payload)
    assert "oneOf" in items
    source = _variant(items, "SOURCE_CONTEXT")
    note = _variant(items, "NOTE_UNIT")
    assert source["properties"]["kind"]["const"] == "SOURCE_CONTEXT"
    assert note["properties"]["kind"]["const"] == "NOTE_UNIT"
    assert "transcription_status" not in source["properties"]
    assert "transcription_status" in note["properties"]
    assert payload["if"]["properties"]["schema_version"]["const"] == NOTE_UNIT_SCHEMA_V1
    assert "transcription_status" not in _variant(_v1_items(payload), "NOTE_UNIT")["properties"]
    remote = remote_tool_schema(wire)
    remote_payload = _payload_schema(remote)
    assert "idempotency_key" not in remote_payload["properties"]
    assert remote_payload["if"]["properties"]["schema_version"]["const"] == NOTE_UNIT_SCHEMA_V1
    assert not _schema_admits(
        payload,
        _proposal_document(
            NOTE_UNIT_SCHEMA_V2,
            [_source_context(transcription_status="CLEAR")],
            suffix="protocol-failed-shape",
        ),
    )
