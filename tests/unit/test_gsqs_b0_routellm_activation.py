"""Activation artifact for the internal RouteLLM B0 client."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_ROUTELLM_HTTP,
)
from my_pa.application.goodnotes_gsqs_b0_routellm_activation import (
    ACTIVATION_OPERATION,
    ACTIVATION_SCHEMA,
    RouteLLMActivationError,
    RouteLLMClientActivation,
    admit_activation,
    load_activation,
    parse_https_origin,
)
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    INCUMBENT_ANALYZER_VERSION,
)
from my_pa.application.goodnotes_gsqs_live_b0 import prompt_config_identity, repo_root
from my_pa.application.goodnotes_gsqs_routellm_candidate import (
    composite_model_identity,
    load_route_llm_candidate,
)

COMMIT_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
COMMIT_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
ORIGIN = "https://route.example"
ROOT = repo_root()


def live_identities() -> tuple[str, str]:
    candidate = load_route_llm_candidate(
        ROOT / "ops/goodnotes/gsqs/b0/routellm-goodnotes-b0-v1.json"
    )
    return composite_model_identity(candidate), prompt_config_identity(ROOT)


def activation_payload(**overrides: object) -> dict[str, object]:
    identity, prompt = live_identities()
    payload: dict[str, object] = {
        "analyzer_name": INCUMBENT_ANALYZER_NAME,
        "analyzer_version": INCUMBENT_ANALYZER_VERSION,
        "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
        "candidate_identity": identity,
        "external_synthetic_commissioning_status": "NOT_RUN",
        "fallback_policy": "none",
        "https_required": True,
        "invalidation_rule": "any identity or origin change invalidates this activation",
        "model_client": MODEL_CLIENT_ROUTELLM_HTTP,
        "model_identity": identity,
        "operation": ACTIVATION_OPERATION,
        "prompt_config_identity": prompt,
        "real_handwriting_admitted": False,
        "repository_commit": COMMIT_A,
        "repository_tree": COMMIT_B,
        "route_llm_endpoint_origin": ORIGIN,
        "schema_version": ACTIVATION_SCHEMA,
    }
    payload.update(overrides)
    return payload


def write_activation(directory: Path, **overrides: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "activation.json"
    target.write_text(json.dumps(activation_payload(**overrides)), encoding="utf-8")
    return target


def load_valid_activation(directory: Path, **overrides: object) -> RouteLLMClientActivation:
    return load_activation(write_activation(directory, **overrides))


def _admit(activation: RouteLLMClientActivation, **overrides: str) -> None:
    params = {
        "expected_commit": activation.repository_commit,
        "expected_tree": activation.repository_tree,
        "expected_candidate": activation.candidate_identity,
        "expected_prompt": activation.prompt_config_identity,
        "expected_analyzer_name": activation.analyzer_name,
        "expected_analyzer_version": activation.analyzer_version,
    }
    params.update(overrides)
    admit_activation(activation, **params)


def test_load_activation_refuses_symlink(tmp_path: Path) -> None:
    target = write_activation(tmp_path / "real")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(RouteLLMActivationError, match="missing"):
        load_activation(link)


def test_load_activation_requires_json_object(tmp_path: Path) -> None:
    path = tmp_path / "activation.json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(RouteLLMActivationError, match="JSON object"):
        load_activation(path)


def test_wrong_schema_is_rejected(tmp_path: Path) -> None:
    path = write_activation(tmp_path, schema_version="other")
    with pytest.raises(RouteLLMActivationError, match="schema"):
        load_activation(path)


def test_forbidden_secret_and_gold_fields_are_rejected(tmp_path: Path) -> None:
    for key, value in (
        ("api_key", "TEST-SENTINEL-API-KEY-NOT-A-SECRET"),
        ("bearer", "x"),
        ("authorization", "Bearer x"),
        ("gold", "nope"),
        ("private_gold", "nope"),
    ):
        path = write_activation(tmp_path / key, **{key: value})
        with pytest.raises(RouteLLMActivationError, match="forbidden"):
            load_activation(path)


def test_non_https_origin_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RouteLLMActivationError, match="HTTPS origin"):
        load_activation(
            write_activation(tmp_path, route_llm_endpoint_origin="http://route.example")
        )
    with pytest.raises(RouteLLMActivationError, match="HTTPS origin"):
        parse_https_origin("https://user:pass@route.example")


def test_admit_implementation_identity_mismatch(tmp_path: Path) -> None:
    activation = load_valid_activation(tmp_path)
    with pytest.raises(RouteLLMActivationError, match="implementation identity") as raised:
        _admit(activation, expected_commit="cccccccccccccccccccccccccccccccccccccccc")
    assert raised.value.error_class == "IMPLEMENTATION_IDENTITY"


def test_admit_candidate_and_prompt_mismatch(tmp_path: Path) -> None:
    activation = load_valid_activation(tmp_path)
    with pytest.raises(RouteLLMActivationError, match="candidate identity") as raised:
        _admit(activation, expected_candidate="other-candidate")
    assert raised.value.error_class == "CANDIDATE_IDENTITY"
    with pytest.raises(RouteLLMActivationError, match="prompt identity") as raised:
        _admit(activation, expected_prompt="other-prompt")
    assert raised.value.error_class == "PROMPT_IDENTITY"


def test_admit_model_client_mismatch(tmp_path: Path) -> None:
    activation = load_valid_activation(tmp_path, model_client="synthetic-fake")
    with pytest.raises(RouteLLMActivationError, match="model-client") as raised:
        _admit(activation)
    assert raised.value.error_class == "MODEL_CLIENT_MISMATCH"


def test_admit_rejects_real_handwriting_and_http_policy(tmp_path: Path) -> None:
    handwriting = load_valid_activation(tmp_path / "hw", real_handwriting_admitted=True)
    with pytest.raises(RouteLLMActivationError, match="real handwriting"):
        _admit(handwriting)
    fallback = load_valid_activation(tmp_path / "fb", fallback_policy="synthetic-fake")
    with pytest.raises(RouteLLMActivationError, match="fallback_policy"):
        _admit(fallback)
    https = load_valid_activation(tmp_path / "https", https_required=False)
    with pytest.raises(RouteLLMActivationError, match="https_required"):
        _admit(https)


def test_valid_activation_is_admitted(tmp_path: Path) -> None:
    activation = load_valid_activation(tmp_path)
    _admit(activation)
    identity, prompt = live_identities()
    admit_activation(
        activation,
        expected_commit=COMMIT_A,
        expected_tree=COMMIT_B,
        expected_candidate=identity,
        expected_prompt=prompt,
        expected_analyzer_name=INCUMBENT_ANALYZER_NAME,
        expected_analyzer_version=INCUMBENT_ANALYZER_VERSION,
    )
    assert activation.route_llm_endpoint_origin == ORIGIN
    assert activation.real_handwriting_admitted is False
    assert activation.https_required is True
