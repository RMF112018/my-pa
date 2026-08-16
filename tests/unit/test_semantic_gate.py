"""FAST assertions for the frozen semantic-retrieval disposition."""

from __future__ import annotations

from my_pa.application.context.semantic_gate import (
    CONTEXT_SEMANTIC_GATE_DISPOSITION,
    SEMANTIC_GATE_FAIL,
    SEMANTIC_GATE_PASS,
)
from my_pa.application.model_gate import BoundedModelGate
from my_pa.domain.context.prepared import CONTEXT_RANKING_VERSION, RetrievalMode
from my_pa.domain.modeling.gate import ModelRoutePolicy, SemanticRetrievalGate


def test_frozen_disposition_is_a_gate_token() -> None:
    assert CONTEXT_SEMANTIC_GATE_DISPOSITION in {SEMANTIC_GATE_PASS, SEMANTIC_GATE_FAIL}


def test_semantic_retrieval_gate_defaults_disabled() -> None:
    gate = SemanticRetrievalGate()
    assert gate.benchmark_passed is False
    assert gate.security_review_passed is False
    assert gate.privacy_review_passed is False
    assert gate.enabled is False


def test_model_route_policy_is_only_disabled() -> None:
    assert tuple(ModelRoutePolicy) == (ModelRoutePolicy.DISABLED,)
    assert BoundedModelGate().route is ModelRoutePolicy.DISABLED


def test_production_ranking_stays_lexical_structured() -> None:
    assert CONTEXT_RANKING_VERSION == "lexical_structured.v1"
    assert RetrievalMode.LEXICAL_STRUCTURED.value == "lexical_structured"
