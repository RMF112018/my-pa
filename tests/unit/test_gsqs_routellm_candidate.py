"""Class-1 RouteLLM candidate digest. Generation omission is identity-bearing."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from my_pa.application.goodnotes_gsqs_live_b0 import repo_root
from my_pa.application.goodnotes_gsqs_routellm_candidate import (
    ROUTE_LLM_CANDIDATE_RELATIVE_PATH,
    composite_model_identity,
    load_route_llm_candidate,
    route_config_digest,
    validate_route_llm_candidate,
)


def test_committed_candidate_is_class_one_only() -> None:
    payload = load_route_llm_candidate(repo_root() / ROUTE_LLM_CANDIDATE_RELATIVE_PATH)
    digest = route_config_digest(payload)
    identity = composite_model_identity(payload)
    assert identity.startswith("routellm-goodnotes-b0-v1@sha256:")
    assert digest == identity.split(":", 1)[1]
    assert "api_id" not in str(payload)
    assert "endpoint" not in payload
    assert payload["generation"]["temperature"]["mode"] == "OMITTED_PLATFORM_DEFAULT"


def test_explicit_temperature_changes_digest() -> None:
    payload = load_route_llm_candidate(repo_root() / ROUTE_LLM_CANDIDATE_RELATIVE_PATH)
    omitted = route_config_digest(payload)
    mutated = deepcopy(payload)
    mutated["generation"]["temperature"] = {"mode": "EXPLICIT", "value": 0.0}
    validate_route_llm_candidate(mutated)
    assert route_config_digest(mutated) != omitted


def test_candidate_file_exists() -> None:
    path = Path(repo_root() / ROUTE_LLM_CANDIDATE_RELATIVE_PATH)
    assert path.is_file()
