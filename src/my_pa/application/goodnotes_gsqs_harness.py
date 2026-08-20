"""Side-effect-free Gate B / B0 evaluation harness.

Does not call production `goodnotes.propose`, persist proposals, or grade the
production worker from inside the worker. ChatLLM output is an interchange
artifact scored by `evaluate_gsqs`.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from my_pa.application.goodnotes_gsqs import (
    AUTOMATIC_PROMOTION_DISABLED,
    EVALUATOR_NAME,
    EVALUATOR_VERSION,
    GATE_B_STATE,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    NOTE_UNIT_V2,
    SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
    AnalyzerOutput,
    CorpusPartition,
    EvaluationResult,
    GoldRegion,
    MeasurementRecord,
    PredictedSegment,
    evaluate_gsqs,
    evaluator_code_identity,
    parse_predicted_segment,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    CorpusCase,
    CorpusManifest,
    gold_for_partition,
)
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

INCUMBENT_ANALYZER_NAME = "chatllm-goodnotes-semantic"
INCUMBENT_ANALYZER_VERSION = "sit-1.0"
B0_MIN_REPETITIONS = 3
INTERCHANGE_SCHEMA_VERSION = "gsqs-analyzer-output-v1"

AnalyzerFn = Callable[[CorpusCase], AnalyzerOutput]


@dataclass(frozen=True, slots=True)
class VariancePlan:
    repetitions: int
    mean_gsqs: float | None
    median_gsqs: float | None
    stdev_gsqs: float | None
    component_means: dict[str, float] | None
    critical_error_frequency: float | None
    threshold_policy: str

    def as_dict(self) -> dict[str, object]:
        return {
            "repetitions": self.repetitions,
            "mean_gsqs": self.mean_gsqs,
            "median_gsqs": self.median_gsqs,
            "stdev_gsqs": self.stdev_gsqs,
            "component_means": self.component_means,
            "critical_error_frequency": self.critical_error_frequency,
            "threshold_policy": self.threshold_policy,
            "MEASURED_B0": MEASURED_B0_NOT_YET_ESTABLISHED,
        }


@dataclass(frozen=True, slots=True)
class B0HarnessStatus:
    implemented: bool
    ready: bool
    measured_b0: str
    self_improvement: str
    automatic_promotion: str
    incumbent_name: str
    incumbent_version: str
    min_repetitions: int


def harness_status() -> B0HarnessStatus:
    return B0HarnessStatus(
        implemented=True,
        ready=True,
        measured_b0=MEASURED_B0_NOT_YET_ESTABLISHED,
        self_improvement=SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
        automatic_promotion=AUTOMATIC_PROMOTION_DISABLED,
        incumbent_name=INCUMBENT_ANALYZER_NAME,
        incumbent_version=INCUMBENT_ANALYZER_VERSION,
        min_repetitions=B0_MIN_REPETITIONS,
    )


def planned_variance() -> VariancePlan:
    return VariancePlan(
        repetitions=B0_MIN_REPETITIONS,
        mean_gsqs=None,
        median_gsqs=None,
        stdev_gsqs=None,
        component_means=None,
        critical_error_frequency=None,
        threshold_policy=(
            "Do not activate a promotion threshold until empirical Corpus B "
            "variance exists. Future improvement must exceed measured noise, "
            "not an arbitrary constant."
        ),
    )


def interchange_document(case: CorpusCase, output: AnalyzerOutput) -> dict[str, object]:
    return {
        "schema_version": INTERCHANGE_SCHEMA_VERSION,
        "corpus_version": case.corpus_version,
        "case_id": case.case_id,
        "content_sha256": case.content_sha256,
        "analyzer_name": output.analyzer_name,
        "analyzer_version": output.analyzer_version,
        "proposal_schema_version": output.schema_version,
        "segments": [_segment_dict(segment) for segment in output.segments],
    }


def parse_interchange(document: dict[str, object]) -> AnalyzerOutput:
    if document.get("schema_version") != INTERCHANGE_SCHEMA_VERSION:
        raise ValueError("unsupported analyzer interchange schema")
    segments_raw = document.get("segments")
    if not isinstance(segments_raw, list):
        raise ValueError("interchange segments must be a list")
    extra = {
        key: value
        for key, value in document.items()
        if key
        not in {
            "schema_version",
            "corpus_version",
            "case_id",
            "content_sha256",
            "analyzer_name",
            "analyzer_version",
            "proposal_schema_version",
            "segments",
        }
    }
    corpus_version = document.get("corpus_version")
    return AnalyzerOutput(
        case_id=str(document["case_id"]),
        schema_version=str(document.get("proposal_schema_version") or NOTE_UNIT_V2),
        analyzer_name=str(document["analyzer_name"]),
        analyzer_version=str(document["analyzer_version"]),
        segments=tuple(
            parse_predicted_segment(item) for item in segments_raw if isinstance(item, dict)
        ),
        extra=extra,
        corpus_version=str(corpus_version) if corpus_version is not None else None,
    )


def gold_as_output(
    case: CorpusCase, *, analyzer_name: str, analyzer_version: str
) -> AnalyzerOutput:
    """Deterministic fake analyzer for harness dry-run. Not ChatLLM output."""
    segments = tuple(_gold_to_predicted(region) for region in case.regions)
    return AnalyzerOutput(
        case_id=case.case_id,
        schema_version=NOTE_UNIT_V2,
        analyzer_name=analyzer_name,
        analyzer_version=analyzer_version,
        segments=segments,
        corpus_version=case.corpus_version,
    )


def score_partition(
    cases: Sequence[CorpusCase],
    outputs: Sequence[AnalyzerOutput],
    *,
    partition: CorpusPartition,
    manifest: CorpusManifest,
    analyzer_name: str,
    analyzer_version: str,
    run_repetition: int,
    measured_at: datetime | None = None,
    model_identity: str | None = None,
    prompt_config_identity: str | None = None,
    path_includes_reconciliation: bool = False,
) -> tuple[EvaluationResult, MeasurementRecord]:
    selected = tuple(case for case in cases if case.partition is partition and case.scoreable)
    gold = gold_for_partition(cases, partition)
    claimed = {item.corpus_version or "missing" for item in outputs}
    output_version = claimed.pop() if len(claimed) == 1 else "mismatch"
    result = evaluate_gsqs(
        gold,
        outputs,
        path_includes_reconciliation=path_includes_reconciliation,
        expected_corpus_version=manifest.corpus_version,
        output_corpus_version=output_version,
    )
    if {item.case_id for item in selected} != {item.case_id for item in outputs}:
        raise ValueError("outputs must cover the selected partition exactly")
    config = {
        "analyzer_name": analyzer_name,
        "analyzer_version": analyzer_version,
        "partition": partition.value,
        "corpus_manifest_digest": manifest.manifest_digest,
        "evaluator": evaluator_code_identity(),
    }
    digest = sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    stamp = measured_at or datetime.now(UTC)
    measurement_id = sha256(f"{digest}:{run_repetition}:{stamp.isoformat()}".encode()).hexdigest()[
        :32
    ]
    record = MeasurementRecord(
        measurement_id=f"gsqm_{measurement_id}",
        measured_at=stamp,
        corpus_version=manifest.corpus_version,
        corpus_manifest_digest=manifest.manifest_digest,
        partition=partition.value,
        evaluator_name=EVALUATOR_NAME,
        evaluator_version=EVALUATOR_VERSION,
        evaluator_code_identity=evaluator_code_identity(),
        analyzer_name=analyzer_name,
        analyzer_version=analyzer_version,
        candidate_config_digest=digest,
        model_identity=model_identity,
        prompt_config_identity=prompt_config_identity,
        run_repetition=run_repetition,
        case_count=result.case_count,
        note_unit_count=result.note_unit_count,
        scores=result.scores,
        gsqs=result.gsqs,
        critical_errors=result.critical_errors,
        database_integrity=result.database_integrity,
        measurement_valid=result.measurement_valid,
        invalid_reason=result.invalid_reason,
        evidence_ref=f"diagnostics:{result.case_count}",
    )
    return result, record


def dry_run_b0(
    cases: Sequence[CorpusCase],
    manifest: CorpusManifest,
    *,
    analyzer: AnalyzerFn | None = None,
    repetitions: int = B0_MIN_REPETITIONS,
    analyzer_name: str = "deterministic-gold-replay",
    analyzer_version: str = "harness-dry-run",
) -> tuple[tuple[MeasurementRecord, ...], VariancePlan]:
    """Score Corpus B with a local analyzer callback. Does not invoke ChatLLM."""
    if analyzer_name == INCUMBENT_ANALYZER_NAME:
        raise ValueError("live incumbent B0 is not authorized in this harness invocation")
    selected = [case for case in cases if case.partition is CorpusPartition.B and case.scoreable]
    callback = analyzer or (
        lambda case: gold_as_output(
            case, analyzer_name=analyzer_name, analyzer_version=analyzer_version
        )
    )
    records: list[MeasurementRecord] = []
    for repetition in range(1, repetitions + 1):
        outputs = []
        for case in selected:
            output = callback(case)
            if output.analyzer_name == INCUMBENT_ANALYZER_NAME:
                raise ValueError("do not fake ChatLLM incumbent output")
            outputs.append(output)
        _result, record = score_partition(
            cases,
            tuple(outputs),
            partition=CorpusPartition.B,
            manifest=manifest,
            analyzer_name=analyzer_name,
            analyzer_version=analyzer_version,
            run_repetition=repetition,
        )
        records.append(record)
    scores = [item.gsqs for item in records]
    plan = VariancePlan(
        repetitions=repetitions,
        mean_gsqs=statistics.fmean(scores),
        median_gsqs=statistics.median(scores),
        stdev_gsqs=statistics.pstdev(scores) if len(scores) > 1 else 0.0,
        component_means={
            "boundary": statistics.fmean(item.scores.boundary for item in records),
            "transcription": statistics.fmean(item.scores.transcription for item in records),
            "transcription_status": statistics.fmean(
                item.scores.transcription_status for item in records
            ),
            "primary_class": statistics.fmean(item.scores.primary_class for item in records),
            "secondary_tag": statistics.fmean(item.scores.secondary_tag for item in records),
            "candidate_ranking": statistics.fmean(
                item.scores.candidate_ranking for item in records
            ),
            "confidence_calibration": statistics.fmean(
                item.scores.confidence_calibration for item in records
            ),
        },
        critical_error_frequency=statistics.fmean(
            1.0 if item.critical_errors else 0.0 for item in records
        ),
        threshold_policy=planned_variance().threshold_policy,
    )
    return tuple(records), plan


def gate_b_state_matrix() -> dict[str, str]:
    return dict(GATE_B_STATE)


def _gold_to_predicted(region: GoldRegion) -> PredictedSegment:
    note = region.kind is GoodNotesSegmentKind.NOTE_UNIT
    return PredictedSegment(
        kind=region.kind,
        geometry=region.geometry,
        transcription=region.transcription or None,
        transcription_status=region.transcription_status if note else None,
        primary_class=region.primary_class if note else None,
        candidate_tags=region.candidate_tags if note else (),
        ranked_candidates=region.ranked_candidates if note else (),
        confidence=region.reference_confidence if note else None,
    )


def _segment_dict(segment: PredictedSegment) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": segment.kind.value,
        "geometry": {
            "x_min": segment.geometry.x_min,
            "y_min": segment.geometry.y_min,
            "width": segment.geometry.width,
            "height": segment.geometry.height,
        },
        "transcription": segment.transcription,
        "transcription_status": (
            None if segment.transcription_status is None else segment.transcription_status.value
        ),
        "primary_class": None if segment.primary_class is None else segment.primary_class.value,
        "candidate_tags": list(segment.candidate_tags),
        "ranked_candidates": [
            {"rank": item.rank, "candidate": item.candidate} for item in segment.ranked_candidates
        ],
    }
    if segment.confidence is not None:
        payload["confidence"] = {
            "transcription": segment.confidence.transcription,
            "segmentation": segment.confidence.segmentation,
            "classification": segment.confidence.classification,
            "linking": segment.confidence.linking,
            "uncertainty": segment.confidence.uncertainty,
        }
    payload.update(dict(segment.extra))
    return payload
