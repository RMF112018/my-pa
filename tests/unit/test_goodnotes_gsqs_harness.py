"""B0 harness dry-run, interchange, and side-effect-free evaluation boundary."""

from __future__ import annotations

import json

import pytest

from my_pa.application import goodnotes_gsqs as evaluator_mod
from my_pa.application import goodnotes_gsqs_harness as harness_mod
from my_pa.application.goodnotes_gsqs import (
    AUTOMATIC_PROMOTION_DISABLED,
    GATE_B_STATE,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
)
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    dry_run_b0,
    gate_b_state_matrix,
    gold_as_output,
    harness_status,
    interchange_document,
    parse_interchange,
    planned_variance,
)
from my_pa.application.goodnotes_gsqs_v1_freeze import freeze_v1_corpus
from my_pa.application.goodnotes_semantics import submit_proposal


def test_gate_b_state_ceiling() -> None:
    state = gate_b_state_matrix()
    assert state == dict(GATE_B_STATE)
    assert state["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED
    assert state["SELF_IMPROVEMENT_EVALUATION"] == SELF_IMPROVEMENT_NOT_YET_ACTIVATED
    assert state["AUTOMATIC_PROMOTION"] == AUTOMATIC_PROMOTION_DISABLED
    assert state["FIXED_LABELED_CORPUS"] == "READY_FOR_OPERATOR_REVIEW"
    assert state["INDEPENDENT_EVALUATOR"] == "VALIDATED"
    assert state["B0_HARNESS"] == "READY"
    status = harness_status()
    assert status.ready is True
    assert status.measured_b0 == MEASURED_B0_NOT_YET_ESTABLISHED
    assert status.incumbent_name == INCUMBENT_ANALYZER_NAME


def test_dry_run_refuses_to_fake_incumbent_and_does_not_call_propose() -> None:
    cases, manifest = freeze_v1_corpus()
    with pytest.raises(ValueError, match="not authorized"):
        dry_run_b0(
            cases,
            manifest,
            analyzer_name=INCUMBENT_ANALYZER_NAME,
            analyzer_version="sit-1.0",
        )
    records, plan = dry_run_b0(cases, manifest, repetitions=3)
    assert len(records) == 3
    assert all(item.measurement_valid for item in records)
    assert all(item.analyzer_name != INCUMBENT_ANALYZER_NAME for item in records)
    assert plan.mean_gsqs is not None
    assert plan.stdev_gsqs == 0.0
    assert "empirical" in plan.threshold_policy
    first = json.dumps(records[0].canonical_dict(), sort_keys=True)
    second = json.dumps(records[0].canonical_dict(), sort_keys=True)
    assert first == second
    assert "submit_proposal" in submit_proposal.__name__
    assert planned_variance().mean_gsqs is None
    assert "submit_proposal" not in evaluator_mod.__dict__
    assert "submit_proposal" not in harness_mod.__dict__


def test_interchange_round_trip_and_gold_replay() -> None:
    cases, _manifest = freeze_v1_corpus()
    case = next(item for item in cases if item.scoreable)
    output = gold_as_output(case, analyzer_name="deterministic-gold-replay", analyzer_version="1")
    document = interchange_document(case, output)
    parsed = parse_interchange(document)
    assert parsed.case_id == case.case_id
    assert parsed.schema_version == output.schema_version
    assert len(parsed.segments) == len(output.segments)
    with pytest.raises(ValueError, match="unsupported"):
        parse_interchange({**document, "schema_version": "other"})
