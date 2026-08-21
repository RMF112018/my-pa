"""Class-1 RouteLLM inference candidate identity. No endpoint, mapping, or secrets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from my_pa.application.goodnotes_gsqs_corpus import canonical_dumps

ROUTE_LLM_CANDIDATE_RELATIVE_PATH = Path("ops/goodnotes/gsqs/b0/routellm-goodnotes-b0-v1.json")
ROUTE_LLM_SCHEMA_VERSION = "routellm-goodnotes-b0-v1"
ROUTE_LLM_IDENTITY_LABEL = "routellm-goodnotes-b0-v1"
OPERATOR_DISPLAY_POOL = (
    "GPT-5.6 Terra",
    "Gemini 3.1 Pro",
    "Kimi K3",
    "Claude Sonnet 4.6",
    "Deepseek V4 Pro",
)
_OMITTED = {"mode": "OMITTED_PLATFORM_DEFAULT"}
_GENERATION_KEYS = (
    "frequency_penalty",
    "max_tokens",
    "modalities",
    "presence_penalty",
    "stop",
    "stream",
    "temperature",
    "tools",
    "top_p",
)


def load_route_llm_candidate(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RouteLLM candidate must be a JSON object")
    validate_route_llm_candidate(payload)
    return payload


def validate_route_llm_candidate(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != ROUTE_LLM_SCHEMA_VERSION:
        raise ValueError("wrong RouteLLM candidate schema")
    if payload.get("identity_label") != ROUTE_LLM_IDENTITY_LABEL:
        raise ValueError("wrong RouteLLM identity label")
    if payload.get("inference_strategy") != "RouteLLM":
        raise ValueError("inference strategy must be RouteLLM")
    if payload.get("router_model_id") != "route-llm":
        raise ValueError("router_model_id must be route-llm")
    if payload.get("analyzer_name") != "chatllm-goodnotes-semantic":
        raise ValueError("wrong analyzer_name")
    if payload.get("analyzer_version") != "sit-1.0":
        raise ValueError("wrong analyzer_version")
    if payload.get("prompt_artifact") != "ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt":
        raise ValueError("wrong prompt artifact path")
    if payload.get("fallback_policy") != "none":
        raise ValueError("fallback_policy must be none")
    if payload.get("routing_policy_id") is not None:
        raise ValueError("routing_policy_id must be null")
    if payload.get("routing_policy_version") is not None:
        raise ValueError("routing_policy_version must be null")
    vision = payload.get("vision")
    if not isinstance(vision, Mapping) or vision.get("input_mode") != "image_url_data_uri":
        raise ValueError("vision.input_mode must be image_url_data_uri")
    structured = payload.get("structured_output")
    if not isinstance(structured, Mapping) or structured.get("mode") != "OMITTED_PLATFORM_DEFAULT":
        raise ValueError("structured_output must be omitted platform default")
    generation = payload.get("generation")
    if not isinstance(generation, Mapping):
        raise ValueError("generation settings missing")
    for key in _GENERATION_KEYS:
        value = generation.get(key)
        if not isinstance(value, Mapping) or value.get("mode") not in {
            "OMITTED_PLATFORM_DEFAULT",
            "EXPLICIT",
        }:
            raise ValueError(f"generation.{key} must be omitted or explicit")
        if value.get("mode") == "EXPLICIT" and "value" not in value:
            raise ValueError(f"generation.{key} explicit setting missing value")
        if "api_id" in value:
            raise ValueError("generation settings must not carry api_id")
    pool = payload.get("eligible_model_pool")
    if not isinstance(pool, list) or len(pool) != 5:
        raise ValueError("eligible_model_pool must contain exactly five models")
    names: list[str] = []
    for item in pool:
        if not isinstance(item, Mapping):
            raise ValueError("eligible_model_pool entry must be an object")
        if "api_id" in item:
            raise ValueError("eligible_model_pool must not contain api_id")
        name = item.get("display_name")
        if not isinstance(name, str) or not name:
            raise ValueError("eligible_model_pool display_name missing")
        names.append(name)
    if set(names) != set(OPERATOR_DISPLAY_POOL):
        raise ValueError("eligible_model_pool display names are not the operator pool")
    if names != sorted(names):
        raise ValueError("eligible_model_pool must be sorted by display_name")
    forbidden = {
        "endpoint",
        "origin",
        "origin_allowlist",
        "api_id",
        "server_side_invariants",
        "path_a",
        "path_b",
        "provider_model_mapping",
    }
    if forbidden & set(payload):
        raise ValueError("RouteLLM candidate contains non-inference identity fields")


def route_config_digest(payload: Mapping[str, Any]) -> str:
    validate_route_llm_candidate(payload)
    return sha256(canonical_dumps(dict(payload)).encode()).hexdigest()


def composite_model_identity(payload: Mapping[str, Any]) -> str:
    return f"{ROUTE_LLM_IDENTITY_LABEL}@sha256:{route_config_digest(payload)}"


def omitted_generation_keys_in_http_body(body: Mapping[str, Any]) -> tuple[str, ...]:
    present = tuple(key for key in _GENERATION_KEYS if key in body)
    if "response_format" in body:
        present = (*present, "response_format")
    return present
