"""SPECIALIZED: recompute the frozen semantic gate and refuse a rotting report."""

from __future__ import annotations

import pytest

from my_pa.application.context.semantic_gate import CONTEXT_SEMANTIC_GATE_DISPOSITION
from my_pa.domain.context.prepared import RetrievalMode
from my_pa.domain.modeling.gate import ModelRoutePolicy, SemanticRetrievalGate
from tests.evaluation.harness import compute_gate_record, load_frozen_record

pytestmark = pytest.mark.evaluation


def test_frozen_report_matches_the_computed_gate() -> None:
    computed = compute_gate_record()
    frozen = load_frozen_record()
    assert computed == frozen
    assert computed["disposition"] == CONTEXT_SEMANTIC_GATE_DISPOSITION
    assert computed["date"] == "2026-08-15"
    assert computed["production_semantic_authorized"] is False


def test_evaluation_does_not_enable_production_semantic() -> None:
    assert SemanticRetrievalGate().enabled is False
    assert tuple(ModelRoutePolicy) == (ModelRoutePolicy.DISABLED,)
    assert RetrievalMode.HYBRID_SEMANTIC.value == "hybrid_semantic"
