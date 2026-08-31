"""Production-inert semantic optimizer policy and adversarial boundaries."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from my_pa.application.goodnotes_semantic_optimizer import (
    ALL_HARD_GATES,
    BenchmarkIdentity,
    EvaluatorIdentity,
    HardGate,
    HardGateReport,
    OptimizerHistory,
    OptimizerHistoryEntry,
    OptimizerPolicy,
    OptimizerState,
    SemanticConfiguration,
    TrialDisposition,
    TrialMeasurement,
    admit_single_change,
    apply_change,
    decide_trial,
)


def _config(configuration_id: str = "semantic-v1", version: str = "1") -> SemanticConfiguration:
    return SemanticConfiguration.create(
        configuration_id=configuration_id,
        version=version,
        prompt_text="Extract only visually grounded note units.",
        cue_order=("visual", "geometry", "context"),
        classification_wording="Use the governed classification taxonomy.",
        thresholds={
            "association_confidence": 0.8,
            "classification_confidence": 0.75,
            "transcription_confidence": 0.7,
        },
    )


BENCHMARK = BenchmarkIdentity("synthetic-semantic", "1", "a" * 64)
EVALUATOR = EvaluatorIdentity("independent-gsqs", "1", "b" * 64)
POLICY = OptimizerPolicy(minimum_improvement=0.02, plateau_limit=2)


def _measurement(
    candidate: SemanticConfiguration,
    *,
    score: float,
    gates: frozenset[HardGate] = ALL_HARD_GATES,
) -> TrialMeasurement:
    return TrialMeasurement(
        configuration_sha256=candidate.content_sha256,
        benchmark_digest=BENCHMARK.digest,
        evaluator_digest=EVALUATOR.digest,
        score=score,
        hard_gates=HardGateReport(gates),
    )


def test_configuration_benchmark_and_evaluator_are_digest_bound() -> None:
    first = _config()
    assert first == _config()
    assert len(first.content_sha256) == len(BENCHMARK.digest) == len(EVALUATOR.digest) == 64
    with pytest.raises(ValueError, match="content digest mismatch"):
        replace(first, prompt_text="mutated without a new digest")


@pytest.mark.parametrize(
    "change",
    [
        {"prompt_text": "Prefer precise visual evidence."},
        {"cue_order": ["geometry", "visual", "context"]},
        {"classification_wording": "Apply only explicit governed labels."},
        {"threshold.classification_confidence": 0.8},
    ],
)
def test_exactly_one_bounded_semantic_change_is_applied(change: dict[str, object]) -> None:
    incumbent = _config()
    candidate = apply_change(
        incumbent,
        configuration_id="semantic-v2",
        version="2",
        change=admit_single_change(change),
    )
    assert candidate.content_sha256 != incumbent.content_sha256


def test_multiple_changes_and_unbounded_threshold_fail_closed() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        admit_single_change({"prompt_text": "new", "cue_order": ["visual"]})
    with pytest.raises(ValueError, match="between zero and one"):
        apply_change(
            _config(),
            configuration_id="bad",
            version="2",
            change=admit_single_change({"threshold.classification_confidence": 1.1}),
        )
    with pytest.raises(ValueError, match="did not change"):
        apply_change(
            _config(),
            configuration_id="no-op",
            version="2",
            change=admit_single_change({"threshold.classification_confidence": 0.75}),
        )


@pytest.mark.parametrize(
    "field",
    [
        "identity",
        "authority",
        "grants",
        "migration_policy",
        "evidence_eligibility",
        "production_state",
        "source_authority",
        "review_requirements",
        "destructive_behavior",
        "canonical_write_authority",
        "evaluation_gold",
    ],
)
def test_prohibited_control_plane_changes_fail_closed(field: str) -> None:
    with pytest.raises(ValueError, match="prohibited control-plane"):
        admit_single_change({field: "attacker-selected"})


def test_hard_gate_failure_cannot_be_compensated_by_a_perfect_score() -> None:
    incumbent = _config()
    candidate = apply_change(
        incumbent,
        configuration_id="semantic-v2",
        version="2",
        change=admit_single_change({"prompt_text": "candidate"}),
    )
    decision = decide_trial(
        state=OptimizerState(incumbent, incumbent_score=0.1),
        candidate=candidate,
        measurement=_measurement(
            candidate,
            score=1.0,
            gates=ALL_HARD_GATES - {HardGate.EVALUATION_GOLD_ISOLATION},
        ),
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    assert decision.disposition is TrialDisposition.REJECT_HARD_GATE
    assert decision.selected_sha256 == incumbent.content_sha256
    assert decision.hard_gate_failures == (HardGate.EVALUATION_GOLD_ISOLATION,)

    paused_rejection = decide_trial(
        state=OptimizerState(incumbent, incumbent_score=0.1, consecutive_non_improvements=1),
        candidate=candidate,
        measurement=_measurement(
            candidate,
            score=1.0,
            gates=ALL_HARD_GATES - {HardGate.EVALUATION_GOLD_ISOLATION},
        ),
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    assert paused_rejection.disposition is TrialDisposition.REJECT_HARD_GATE
    assert paused_rejection.state.paused is True


@pytest.mark.parametrize("unknown", ["unknown_gate", object()])
def test_hard_gate_report_rejects_unknown_member_added_to_complete_set(unknown: object) -> None:
    supplied = cast(frozenset[HardGate], frozenset({*ALL_HARD_GATES, unknown}))
    with pytest.raises(ValueError, match="unknown gate"):
        HardGateReport(supplied)


def test_hard_gate_report_rejects_string_lookalikes() -> None:
    lookalikes = cast(frozenset[HardGate], frozenset(item.value for item in ALL_HARD_GATES))
    with pytest.raises(ValueError, match="unknown gate"):
        HardGateReport(lookalikes)

    mixed = cast(
        frozenset[HardGate],
        frozenset({*(ALL_HARD_GATES - {HardGate.IDENTITY}), HardGate.IDENTITY.value}),
    )
    with pytest.raises(ValueError, match="unknown gate"):
        HardGateReport(mixed)


def test_improvement_accepts_and_regression_recovers_incumbent() -> None:
    incumbent = _config()
    candidate = apply_change(
        incumbent,
        configuration_id="semantic-v2",
        version="2",
        change=admit_single_change({"classification_wording": "candidate wording"}),
    )
    accepted = decide_trial(
        state=OptimizerState(incumbent, incumbent_score=0.7),
        candidate=candidate,
        measurement=_measurement(candidate, score=0.8),
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    assert accepted.disposition is TrialDisposition.ACCEPT_CANDIDATE
    assert accepted.state.incumbent == candidate

    regressed = decide_trial(
        state=accepted.state,
        candidate=incumbent,
        measurement=_measurement(incumbent, score=0.6),
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    assert regressed.disposition is TrialDisposition.RECOVER_INCUMBENT
    assert regressed.selected_sha256 == candidate.content_sha256
    assert regressed.state.incumbent == candidate


def test_plateau_pauses_deterministically() -> None:
    incumbent = _config()
    candidate = apply_change(
        incumbent,
        configuration_id="semantic-v2",
        version="2",
        change=admit_single_change({"prompt_text": "candidate"}),
    )
    first = decide_trial(
        state=OptimizerState(incumbent, incumbent_score=0.8),
        candidate=candidate,
        measurement=_measurement(candidate, score=0.81),
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    second = decide_trial(
        state=first.state,
        candidate=candidate,
        measurement=_measurement(candidate, score=0.81),
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    assert first.disposition is TrialDisposition.KEEP_INCUMBENT
    assert second.disposition is TrialDisposition.PAUSED
    assert second.state.paused is True


def test_already_paused_state_evaluates_no_trial_or_measurement_binding() -> None:
    incumbent = _config()
    candidate = apply_change(
        incumbent,
        configuration_id="semantic-v2",
        version="2",
        change=admit_single_change({"prompt_text": "candidate"}),
    )
    unconsumed = TrialMeasurement(
        configuration_sha256="c" * 64,
        benchmark_digest="d" * 64,
        evaluator_digest="e" * 64,
        score=1.0,
        hard_gates=HardGateReport(ALL_HARD_GATES),
    )
    decision = decide_trial(
        state=OptimizerState(incumbent, incumbent_score=0.8, paused=True),
        candidate=candidate,
        measurement=unconsumed,
        benchmark=BENCHMARK,
        evaluator=EVALUATOR,
        policy=POLICY,
    )
    assert decision.disposition is TrialDisposition.PAUSED
    assert decision.selected_sha256 == incumbent.content_sha256


def test_measurement_identity_mismatch_is_rejected() -> None:
    incumbent = _config()
    candidate = apply_change(
        incumbent,
        configuration_id="semantic-v2",
        version="2",
        change=admit_single_change({"prompt_text": "candidate"}),
    )
    measurement = _measurement(candidate, score=0.9)
    with pytest.raises(ValueError, match="another benchmark"):
        decide_trial(
            state=OptimizerState(incumbent, incumbent_score=0.8),
            candidate=candidate,
            measurement=replace(measurement, benchmark_digest="c" * 64),
            benchmark=BENCHMARK,
            evaluator=EVALUATOR,
            policy=POLICY,
        )


def test_history_is_append_only_and_rejects_identity_content_collision() -> None:
    first = _config()
    entry = OptimizerHistoryEntry(
        trial_id="trial-1",
        candidate=first,
        benchmark_digest=BENCHMARK.digest,
        evaluator_digest=EVALUATOR.digest,
        disposition=TrialDisposition.KEEP_INCUMBENT,
        selected_sha256=first.content_sha256,
    )
    history = OptimizerHistory().append(entry)
    assert OptimizerHistory().entries == ()
    assert history.append(entry) is history

    collision = apply_change(
        first,
        configuration_id=first.configuration_id,
        version="2",
        change=admit_single_change({"prompt_text": "different content"}),
    )
    with pytest.raises(ValueError, match="configuration identity collided"):
        history.append(replace(entry, trial_id="trial-2", candidate=collision))
