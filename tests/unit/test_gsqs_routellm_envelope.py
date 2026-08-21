"""Local envelope assembly. Model JSON cannot rewrite trusted identity."""

from __future__ import annotations

import json

import pytest

from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION, parse_interchange
from my_pa.application.goodnotes_gsqs_live_b0 import AnalyzerCaseInput, FrozenAnalyzerConfig
from my_pa.application.goodnotes_gsqs_routellm_envelope import (
    assemble_authoritative_interchange,
    build_chat_completions_body,
    detect_image_mime,
    parse_semantic_content,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8


def _case() -> AnalyzerCaseInput:
    return AnalyzerCaseInput(
        case_id="trusted-case",
        corpus_version="gsqs-hw-combined-v1",
        raster_sha256="ab" * 32,
        interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
        image_bytes=PNG,
    )


def _config() -> FrozenAnalyzerConfig:
    return FrozenAnalyzerConfig(
        analyzer_name="chatllm-goodnotes-semantic",
        analyzer_version="sit-1.0",
        model_identity="routellm-goodnotes-b0-v1@sha256:deadbeef",
        prompt_config_identity="prompt-sha",
        prompt_text="semantic only",
    )


def test_hostile_identity_is_discarded() -> None:
    semantic = {
        "analyzer_name": "evil",
        "analyzer_version": "0",
        "case_id": "attacker",
        "content_sha256": "ff" * 32,
        "corpus_version": "other",
        "model_identity": "attacker-model",
        "prompt_config_identity": "attacker-prompt",
        "schema_version": "gsqs-analyzer-output-v1",
        "segments": [
            {
                "candidate_tags": [],
                "geometry": {"height": 0.1, "width": 0.3, "x_min": 0.1, "y_min": 0.2},
                "kind": "NOTE_UNIT",
                "primary_class": "GENERAL",
                "ranked_candidates": [],
                "transcription": "synthetic follow up monday",
                "transcription_status": "CLEAR",
            }
        ],
    }
    document = assemble_authoritative_interchange(_case(), _config(), semantic)
    parsed = parse_interchange(document)
    assert parsed.case_id == "trusted-case"
    assert parsed.corpus_version == "gsqs-hw-combined-v1"
    assert parsed.content_sha256 == "ab" * 32
    assert parsed.analyzer_name == "chatllm-goodnotes-semantic"
    assert parsed.extra["model_identity"] == "routellm-goodnotes-b0-v1@sha256:deadbeef"
    assert parsed.extra["prompt_config_identity"] == "prompt-sha"
    assert document["model_emitted_identity_fields"] == [
        "analyzer_name",
        "analyzer_version",
        "case_id",
        "content_sha256",
        "corpus_version",
        "model_identity",
        "prompt_config_identity",
        "schema_version",
    ]


def test_malformed_segments_do_not_retry() -> None:
    with pytest.raises(ValueError, match="missing semantic segments"):
        assemble_authoritative_interchange(_case(), _config(), {"not": "segments"})


def test_http_body_omits_gold_and_generation() -> None:
    body = build_chat_completions_body(_case(), _config(), image_bytes=PNG, mime="png")
    dumped = json.dumps(body)
    assert "temperature" not in body
    assert "top_p" not in body
    assert "max_tokens" not in body
    assert "response_format" not in body
    assert "gold" not in dumped
    assert "transcription_gold" not in dumped
    assert body["model"] == "route-llm"
    assert detect_image_mime(PNG) == "png"


def test_parse_semantic_content_rejects_tool_calls() -> None:
    with pytest.raises(ValueError, match="tool_calls"):
        parse_semantic_content(
            {
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {"content": "{}", "tool_calls": [{"id": "1"}]},
                    }
                ]
            }
        )
