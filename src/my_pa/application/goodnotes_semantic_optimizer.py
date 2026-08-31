"""Pure, production-inert GoodNotes semantic optimizer policy.

This module performs no I/O, schedules no work, and cannot activate a
configuration. Durable history persistence remains deferred until the governed
post-R1 storage contract exists; ``OptimizerHistory`` is the immutable
application representation that such storage must preserve.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256

_MAX_TOKEN = 200
_MAX_TEXT = 20_000
_MAX_CUES = 32
_THRESHOLDS = frozenset(
    {"association_confidence", "classification_confidence", "transcription_confidence"}
)
_SEMANTIC_KEYS = frozenset({"prompt_text", "cue_order", "classification_wording"})
PROHIBITED_CHANGE_KEYS = frozenset(
    {
        "identity",
        "principal_id",
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
        "gold",
        "benchmark",
        "evaluator",
    }
)


def _token(value: str, what: str) -> None:
    if not value or len(value) > _MAX_TOKEN or "\x00" in value:
        raise ValueError(f"invalid {what}")


def _digest(value: str, what: str) -> None:
    if len(value) != 64 or set(value.lower()) - set("0123456789abcdef"):
        raise ValueError(f"invalid {what}")


def _text(value: str, what: str) -> None:
    if not value or len(value) > _MAX_TEXT or "\x00" in value:
        raise ValueError(f"invalid {what}")


def _canonical_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BenchmarkIdentity:
    benchmark_id: str
    version: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        _token(self.benchmark_id, "benchmark id")
        _token(self.version, "benchmark version")
        _digest(self.manifest_sha256, "benchmark manifest digest")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "benchmark_id": self.benchmark_id,
                "manifest_sha256": self.manifest_sha256,
                "version": self.version,
            }
        )


@dataclass(frozen=True, slots=True)
class EvaluatorIdentity:
    evaluator_id: str
    version: str
    behavior_sha256: str

    def __post_init__(self) -> None:
        _token(self.evaluator_id, "evaluator id")
        _token(self.version, "evaluator version")
        _digest(self.behavior_sha256, "evaluator behavior digest")

    @property
    def digest(self) -> str:
        return _canonical_digest(
            {
                "behavior_sha256": self.behavior_sha256,
                "evaluator_id": self.evaluator_id,
                "version": self.version,
            }
        )


@dataclass(frozen=True, slots=True)
class SemanticConfiguration:
    configuration_id: str
    version: str
    prompt_text: str
    cue_order: tuple[str, ...]
    classification_wording: str
    thresholds: tuple[tuple[str, float], ...]
    content_sha256: str

    def __post_init__(self) -> None:
        _token(self.configuration_id, "configuration id")
        _token(self.version, "configuration version")
        _text(self.prompt_text, "prompt text")
        _text(self.classification_wording, "classification wording")
        if not self.cue_order or len(self.cue_order) > _MAX_CUES:
            raise ValueError("invalid cue order")
        for cue in self.cue_order:
            _token(cue, "cue")
        if len(set(self.cue_order)) != len(self.cue_order):
            raise ValueError("cue order contains duplicates")
        threshold_names = tuple(name for name, _value in self.thresholds)
        if tuple(sorted(threshold_names)) != threshold_names or set(threshold_names) != _THRESHOLDS:
            raise ValueError("threshold set is not the closed semantic set")
        for _name, value in self.thresholds:
            if isinstance(value, bool) or not 0 <= value <= 1:
                raise ValueError("semantic thresholds must be between zero and one")
        _digest(self.content_sha256, "configuration content digest")
        if self.content_sha256 != self._calculated_digest():
            raise ValueError("configuration content digest mismatch")

    @classmethod
    def create(
        cls,
        *,
        configuration_id: str,
        version: str,
        prompt_text: str,
        cue_order: tuple[str, ...],
        classification_wording: str,
        thresholds: Mapping[str, float],
    ) -> SemanticConfiguration:
        ordered = tuple(sorted(thresholds.items()))
        content = {
            "classification_wording": classification_wording,
            "cue_order": list(cue_order),
            "prompt_text": prompt_text,
            "thresholds": [[name, value] for name, value in ordered],
            "version": version,
        }
        return cls(
            configuration_id=configuration_id,
            version=version,
            prompt_text=prompt_text,
            cue_order=cue_order,
            classification_wording=classification_wording,
            thresholds=ordered,
            content_sha256=_canonical_digest(content),
        )

    def _calculated_digest(self) -> str:
        return _canonical_digest(
            {
                "classification_wording": self.classification_wording,
                "cue_order": list(self.cue_order),
                "prompt_text": self.prompt_text,
                "thresholds": [[name, value] for name, value in self.thresholds],
                "version": self.version,
            }
        )


@dataclass(frozen=True, slots=True)
class SemanticChange:
    key: str
    value: object

    def __post_init__(self) -> None:
        if self.key in PROHIBITED_CHANGE_KEYS:
            raise ValueError("optimizer change targets a prohibited control-plane field")
        if self.key not in _SEMANTIC_KEYS and not self.key.startswith("threshold."):
            raise ValueError("optimizer change is outside the semantic allowlist")
        if (
            self.key.startswith("threshold.")
            and self.key.removeprefix("threshold.") not in _THRESHOLDS
        ):
            raise ValueError("optimizer threshold is outside the closed semantic set")


def admit_single_change(payload: Mapping[str, object]) -> SemanticChange:
    """Admit exactly one semantic change; arbitrary control-plane fields fail closed."""
    if len(payload) != 1:
        raise ValueError("an optimizer trial requires exactly one semantic change")
    key, value = next(iter(payload.items()))
    return SemanticChange(key=key, value=value)


def apply_change(
    incumbent: SemanticConfiguration,
    *,
    configuration_id: str,
    version: str,
    change: SemanticChange,
) -> SemanticConfiguration:
    values: dict[str, object] = {
        "prompt_text": incumbent.prompt_text,
        "cue_order": incumbent.cue_order,
        "classification_wording": incumbent.classification_wording,
        "thresholds": dict(incumbent.thresholds),
    }
    if change.key == "prompt_text":
        if not isinstance(change.value, str):
            raise ValueError("prompt change must be text")
        _text(change.value, "prompt text")
        values["prompt_text"] = change.value
    elif change.key == "cue_order":
        if not isinstance(change.value, (list, tuple)) or not all(
            isinstance(item, str) for item in change.value
        ):
            raise ValueError("cue-order change must be a string sequence")
        values["cue_order"] = tuple(change.value)
    elif change.key == "classification_wording":
        if not isinstance(change.value, str):
            raise ValueError("classification wording change must be text")
        _text(change.value, "classification wording")
        values["classification_wording"] = change.value
    else:
        if isinstance(change.value, bool) or not isinstance(change.value, int | float):
            raise ValueError("threshold change must be numeric")
        threshold = change.key.removeprefix("threshold.")
        thresholds = dict(incumbent.thresholds)
        thresholds[threshold] = float(change.value)
        values["thresholds"] = thresholds
    candidate = SemanticConfiguration.create(
        configuration_id=configuration_id,
        version=version,
        prompt_text=values["prompt_text"],  # type: ignore[arg-type]
        cue_order=values["cue_order"],  # type: ignore[arg-type]
        classification_wording=values["classification_wording"],  # type: ignore[arg-type]
        thresholds=values["thresholds"],  # type: ignore[arg-type]
    )
    incumbent_semantics = (
        incumbent.prompt_text,
        incumbent.cue_order,
        incumbent.classification_wording,
        incumbent.thresholds,
    )
    candidate_semantics = (
        candidate.prompt_text,
        candidate.cue_order,
        candidate.classification_wording,
        candidate.thresholds,
    )
    if candidate_semantics == incumbent_semantics:
        raise ValueError("optimizer trial did not change semantic configuration")
    return candidate


class HardGate(StrEnum):
    IDENTITY = "identity"
    AUTHORITY = "authority"
    GRANTS = "grants"
    MIGRATION_POLICY = "migration_policy"
    EVIDENCE_ELIGIBILITY = "evidence_eligibility"
    PRODUCTION_STATE = "production_state"
    SOURCE_AUTHORITY = "source_authority"
    REVIEW_REQUIREMENTS = "review_requirements"
    NON_DESTRUCTIVE = "non_destructive"
    CANONICAL_WRITE_AUTHORITY = "canonical_write_authority"
    EVALUATION_GOLD_ISOLATION = "evaluation_gold_isolation"


ALL_HARD_GATES = frozenset(HardGate)


@dataclass(frozen=True, slots=True)
class HardGateReport:
    passed: frozenset[HardGate]

    @property
    def failures(self) -> tuple[HardGate, ...]:
        return tuple(sorted(ALL_HARD_GATES - self.passed, key=str))


@dataclass(frozen=True, slots=True)
class TrialMeasurement:
    configuration_sha256: str
    benchmark_digest: str
    evaluator_digest: str
    score: float
    hard_gates: HardGateReport

    def __post_init__(self) -> None:
        for value, what in (
            (self.configuration_sha256, "trial configuration digest"),
            (self.benchmark_digest, "trial benchmark digest"),
            (self.evaluator_digest, "trial evaluator digest"),
        ):
            _digest(value, what)
        if isinstance(self.score, bool) or not 0 <= self.score <= 1:
            raise ValueError("trial score must be between zero and one")


@dataclass(frozen=True, slots=True)
class OptimizerPolicy:
    minimum_improvement: float
    plateau_limit: int

    def __post_init__(self) -> None:
        if isinstance(self.minimum_improvement, bool) or not 0 <= self.minimum_improvement <= 1:
            raise ValueError("minimum improvement must be between zero and one")
        if isinstance(self.plateau_limit, bool) or self.plateau_limit < 1:
            raise ValueError("plateau limit must be positive")


@dataclass(frozen=True, slots=True)
class OptimizerState:
    incumbent: SemanticConfiguration
    incumbent_score: float
    consecutive_non_improvements: int = 0
    paused: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.incumbent_score, bool) or not 0 <= self.incumbent_score <= 1:
            raise ValueError("incumbent score must be between zero and one")
        if self.consecutive_non_improvements < 0:
            raise ValueError("plateau count is not negative")


class TrialDisposition(StrEnum):
    ACCEPT_CANDIDATE = "ACCEPT_CANDIDATE"
    KEEP_INCUMBENT = "KEEP_INCUMBENT"
    RECOVER_INCUMBENT = "RECOVER_INCUMBENT"
    REJECT_HARD_GATE = "REJECT_HARD_GATE"
    PAUSED = "PAUSED"


@dataclass(frozen=True, slots=True)
class TrialDecision:
    disposition: TrialDisposition
    state: OptimizerState
    candidate_sha256: str
    selected_sha256: str
    hard_gate_failures: tuple[HardGate, ...]


def decide_trial(
    *,
    state: OptimizerState,
    candidate: SemanticConfiguration,
    measurement: TrialMeasurement,
    benchmark: BenchmarkIdentity,
    evaluator: EvaluatorIdentity,
    policy: OptimizerPolicy,
) -> TrialDecision:
    """Select configuration identity only; never activates or persists it."""
    if state.paused:
        return TrialDecision(
            disposition=TrialDisposition.PAUSED,
            state=state,
            candidate_sha256=candidate.content_sha256,
            selected_sha256=state.incumbent.content_sha256,
            hard_gate_failures=(),
        )
    if measurement.configuration_sha256 != candidate.content_sha256:
        raise ValueError("measurement is bound to another configuration")
    if measurement.benchmark_digest != benchmark.digest:
        raise ValueError("measurement is bound to another benchmark")
    if measurement.evaluator_digest != evaluator.digest:
        raise ValueError("measurement is bound to another evaluator")
    failures = measurement.hard_gates.failures
    if failures:
        disposition = TrialDisposition.REJECT_HARD_GATE
    elif measurement.score < state.incumbent_score:
        disposition = TrialDisposition.RECOVER_INCUMBENT
    elif measurement.score >= state.incumbent_score + policy.minimum_improvement:
        accepted = OptimizerState(incumbent=candidate, incumbent_score=measurement.score)
        return TrialDecision(
            disposition=TrialDisposition.ACCEPT_CANDIDATE,
            state=accepted,
            candidate_sha256=candidate.content_sha256,
            selected_sha256=candidate.content_sha256,
            hard_gate_failures=(),
        )
    else:
        disposition = TrialDisposition.KEEP_INCUMBENT
    plateau = state.consecutive_non_improvements + 1
    paused = plateau >= policy.plateau_limit
    next_state = replace(state, consecutive_non_improvements=plateau, paused=paused)
    reported = (
        TrialDisposition.PAUSED
        if paused and disposition is TrialDisposition.KEEP_INCUMBENT
        else disposition
    )
    return TrialDecision(
        disposition=reported,
        state=next_state,
        candidate_sha256=candidate.content_sha256,
        selected_sha256=state.incumbent.content_sha256,
        hard_gate_failures=failures,
    )


@dataclass(frozen=True, slots=True)
class OptimizerHistoryEntry:
    trial_id: str
    candidate: SemanticConfiguration
    benchmark_digest: str
    evaluator_digest: str
    disposition: TrialDisposition
    selected_sha256: str

    def __post_init__(self) -> None:
        _token(self.trial_id, "trial id")
        _digest(self.benchmark_digest, "history benchmark digest")
        _digest(self.evaluator_digest, "history evaluator digest")
        _digest(self.selected_sha256, "history selected configuration digest")


@dataclass(frozen=True, slots=True)
class OptimizerHistory:
    entries: tuple[OptimizerHistoryEntry, ...] = ()

    def append(self, entry: OptimizerHistoryEntry) -> OptimizerHistory:
        for held in self.entries:
            if held.trial_id == entry.trial_id:
                if held == entry:
                    return self
                raise ValueError("trial identity collided with different content")
            if (
                held.candidate.configuration_id == entry.candidate.configuration_id
                and held.candidate.content_sha256 != entry.candidate.content_sha256
            ):
                raise ValueError("configuration identity collided with different content")
        return OptimizerHistory(entries=(*self.entries, entry))
