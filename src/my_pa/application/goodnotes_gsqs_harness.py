"""Side-effect-free Gate B / B0 evaluation harness.

Does not call production `goodnotes.propose`, persist proposals, or grade the
production worker from inside the worker. ChatLLM output is an interchange
artifact scored by `evaluate_gsqs`.
"""

from __future__ import annotations

import json
import re
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
from my_pa.application.goodnotes_note_unit_contract import (
    MAX_GOODNOTES_ANALYZER,
    MAX_GOODNOTES_SCHEMA,
    admit_content_sha256,
    admit_v2_segment_list,
)
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

INCUMBENT_ANALYZER_NAME = "chatllm-goodnotes-semantic"
INCUMBENT_ANALYZER_VERSION = "sit-1.0"
B0_MIN_REPETITIONS = 3
INTERCHANGE_SCHEMA_VERSION = "gsqs-analyzer-output-v1"
GIT_OBJECT_ID = re.compile(r"^[0-9a-f]{40}$")

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
    case_id = _required_interchange_token(document, "case_id", maximum=MAX_GOODNOTES_ANALYZER)
    corpus_version = _required_interchange_token(
        document, "corpus_version", maximum=MAX_GOODNOTES_ANALYZER
    )
    analyzer_name = _required_interchange_token(
        document, "analyzer_name", maximum=MAX_GOODNOTES_ANALYZER
    )
    analyzer_version = _required_interchange_token(
        document, "analyzer_version", maximum=MAX_GOODNOTES_ANALYZER
    )
    proposal_schema = _required_interchange_token(
        document, "proposal_schema_version", maximum=MAX_GOODNOTES_SCHEMA
    )
    if proposal_schema != NOTE_UNIT_V2:
        raise ValueError("malformed proposal_schema_version")
    content_sha256 = admit_content_sha256(document.get("content_sha256"))
    segments_raw = document.get("segments")
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
    admitted = admit_v2_segment_list(segments_raw)
    return AnalyzerOutput(
        case_id=case_id,
        schema_version=proposal_schema,
        analyzer_name=analyzer_name,
        analyzer_version=analyzer_version,
        segments=tuple(parse_predicted_segment(item) for item in admitted),
        extra=extra,
        corpus_version=corpus_version,
        content_sha256=content_sha256,
    )


def _required_interchange_token(document: dict[str, object], key: str, *, maximum: int) -> str:
    if key not in document:
        raise ValueError(f"malformed interchange: missing {key}")
    value = document[key]
    if not isinstance(value, str) or not 1 <= len(value) <= maximum or "\x00" in value:
        raise ValueError(f"malformed interchange: {key}")
    return value


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
        content_sha256=case.content_sha256,
    )


def candidate_config_digest(
    *,
    analyzer_name: str,
    analyzer_version: str,
    model_identity: str | None,
    prompt_config_identity: str | None,
    corpus_manifest_digest: str,
    partition: str,
    evaluator_behavior_identity: str,
) -> str:
    payload = {
        "analyzer_name": analyzer_name,
        "analyzer_version": analyzer_version,
        "model_identity": model_identity,
        "prompt_config_identity": prompt_config_identity,
        "corpus_manifest_digest": corpus_manifest_digest,
        "partition": partition,
        "evaluator_behavior_identity": evaluator_behavior_identity,
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_live_b0_identities(
    *,
    analyzer_name: str,
    model_identity: str | None,
    prompt_config_identity: str | None,
) -> None:
    if analyzer_name != INCUMBENT_ANALYZER_NAME:
        return
    if not isinstance(model_identity, str) or not model_identity:
        raise ValueError("live B0 requires explicit model_identity")
    if not isinstance(prompt_config_identity, str) or not prompt_config_identity:
        raise ValueError("live B0 requires explicit prompt_config_identity")


def require_live_b0_repository_identity(
    *,
    repository_commit: str | None,
    repository_tree: str | None,
) -> None:
    if not isinstance(repository_commit, str) or GIT_OBJECT_ID.fullmatch(repository_commit) is None:
        raise ValueError("live B0 requires exact repository_commit")
    if not isinstance(repository_tree, str) or GIT_OBJECT_ID.fullmatch(repository_tree) is None:
        raise ValueError("live B0 requires exact repository_tree")


def derive_analyzer_identity(outputs: Sequence[AnalyzerOutput]) -> tuple[str, str]:
    pairs = {(item.analyzer_name, item.analyzer_version) for item in outputs}
    if len(pairs) != 1:
        raise ValueError("analyzer identity is mixed")
    name, version = next(iter(pairs))
    for label, value in (("analyzer_name", name), ("analyzer_version", version)):
        if not 1 <= len(value) <= MAX_GOODNOTES_ANALYZER or "\x00" in value:
            raise ValueError(f"malformed {label}")
    return name, version


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
    repository_commit: str | None = None,
    repository_tree: str | None = None,
) -> tuple[EvaluationResult, MeasurementRecord]:
    selected = tuple(case for case in cases if case.partition is partition and case.scoreable)
    gold = gold_for_partition(cases, partition)
    claimed = {item.corpus_version or "missing" for item in outputs}
    output_version = claimed.pop() if len(claimed) == 1 else "mismatch"
    expected_content = {case.case_id: case.content_sha256 for case in selected}
    derived_name, derived_version = derive_analyzer_identity(outputs)
    if derived_name != analyzer_name or derived_version != analyzer_version:
        raise ValueError("analyzer identity disagrees with scored artifacts")
    require_live_b0_identities(
        analyzer_name=derived_name,
        model_identity=model_identity,
        prompt_config_identity=prompt_config_identity,
    )
    if derived_name == INCUMBENT_ANALYZER_NAME:
        require_live_b0_repository_identity(
            repository_commit=repository_commit,
            repository_tree=repository_tree,
        )
    result = evaluate_gsqs(
        gold,
        outputs,
        path_includes_reconciliation=path_includes_reconciliation,
        expected_corpus_version=manifest.corpus_version,
        output_corpus_version=output_version,
        expected_content_sha256=expected_content,
    )
    if {item.case_id for item in selected} != {item.case_id for item in outputs}:
        raise ValueError("outputs must cover the selected partition exactly")
    behavior_identity = evaluator_code_identity()
    digest = candidate_config_digest(
        analyzer_name=derived_name,
        analyzer_version=derived_version,
        model_identity=model_identity,
        prompt_config_identity=prompt_config_identity,
        corpus_manifest_digest=manifest.manifest_digest,
        partition=partition.value,
        evaluator_behavior_identity=behavior_identity,
    )
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
        evaluator_code_identity=behavior_identity,
        analyzer_name=derived_name,
        analyzer_version=derived_version,
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
        repository_commit=repository_commit,
        repository_tree=repository_tree,
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
    }
    if segment.crop_sha256 is not None:
        payload["crop_sha256"] = segment.crop_sha256
    if segment.transcription is not None:
        payload["transcription"] = segment.transcription
    if segment.primary_class is not None:
        payload["primary_class"] = segment.primary_class.value
    if segment.kind is GoodNotesSegmentKind.NOTE_UNIT:
        payload["candidate_tags"] = list(segment.candidate_tags)
        payload["ranked_candidates"] = [
            {"rank": item.rank, "candidate": item.candidate} for item in segment.ranked_candidates
        ]
        if segment.transcription_status is not None:
            payload["transcription_status"] = segment.transcription_status.value
        if segment.confidence is not None:
            payload["confidence"] = {
                "transcription": segment.confidence.transcription,
                "segmentation": segment.confidence.segmentation,
                "classification": segment.confidence.classification,
                "linking": segment.confidence.linking,
                "uncertainty": segment.confidence.uncertainty,
            }
    return payload
