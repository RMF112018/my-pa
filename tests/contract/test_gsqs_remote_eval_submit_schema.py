"""tools/list must publish enough note-unit.v2 schema to submit without repo knowledge."""

from __future__ import annotations

import jsonschema

from my_pa.adapters.gsqs_remote_eval_mcp import EVAL_TOOL_SUBMIT, gsqs_eval_tools
from my_pa.application.goodnotes_gsqs import parse_predicted_segment


def _submit_schema() -> dict[str, object]:
    tools = {tool.name: tool for tool in gsqs_eval_tools()}
    schema = tools[EVAL_TOOL_SUBMIT].input_schema
    assert isinstance(schema, dict)
    return schema


def _published_example_segment(schema: dict[str, object]) -> dict[str, object]:
    items = schema["properties"]["segments"]["items"]
    examples = items["examples"]
    assert examples, "submit schema must publish a constructible segment example"
    example = examples[0]
    assert isinstance(example, dict)
    return dict(example)


def test_tools_list_schema_is_enough_to_build_a_valid_submission() -> None:
    schema = _submit_schema()
    segment = _published_example_segment(schema)
    payload = {"lease_id": "lease-from-next", "segments": [segment]}
    jsonschema.Draft202012Validator(schema).validate(payload)
    parsed = parse_predicted_segment(segment)
    assert parsed.kind.value == "NOTE_UNIT"
    assert parsed.geometry.x_min == segment["geometry"]["x_min"]
    assert parsed.transcription_status is not None
    assert parsed.primary_class is not None
    assert parsed.confidence is not None


def test_published_schema_rejects_numeric_confidence_and_axis_aligned_aliases() -> None:
    schema = _submit_schema()
    validator = jsonschema.Draft202012Validator(schema)
    segment = _published_example_segment(schema)
    numeric = dict(segment)
    numeric["confidence"] = 0.9
    assert not validator.is_valid({"lease_id": "lease-from-next", "segments": [numeric]})
    aliased = dict(segment)
    aliased["geometry"] = {"x_min": 0.1, "y_min": 0.1, "x_max": 0.5, "y_max": 0.4}
    assert not validator.is_valid({"lease_id": "lease-from-next", "segments": [aliased]})
