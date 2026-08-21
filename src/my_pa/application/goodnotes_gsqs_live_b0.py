"""Governed live MEASURED_B0 orchestration. Does not score and does not disclose.

This module prepares Partition-B handwriting measurement, validates execution
authorization, and scores injected analyzer interchange through the existing
independent evaluator. It does not call ChatLLM, mutate GATE_B_STATE, or
establish MEASURED_B0.
"""

from __future__ import annotations

import json
import shutil
import statistics
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from my_pa.application.goodnotes_gsqs import (
    AUTOMATIC_PROMOTION_DISABLED,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
    AnalyzerOutput,
    CorpusPartition,
    MeasurementRecord,
    evaluator_code_identity,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    LABEL_PROVENANCE_OPERATOR,
    CorpusCase,
    CorpusManifest,
    ReviewState,
    canonical_dumps,
)
from my_pa.application.goodnotes_gsqs_harness import (
    B0_MIN_REPETITIONS,
    INCUMBENT_ANALYZER_NAME,
    INCUMBENT_ANALYZER_VERSION,
    INTERCHANGE_SCHEMA_VERSION,
    parse_interchange,
    require_live_b0_identities,
    require_live_b0_repository_identity,
    score_partition,
)
from my_pa.application.goodnotes_gsqs_hw_corpus import (
    HANDWRITING_CORPUS_VERSION,
    load_public_catalog,
)

EXECUTE_MEASURED_B0 = "EXECUTE_MEASURED_B0"
APPROVED_MANIFEST_DIGEST = "636d671348cfba5b12b9e5032d5b3daee74f884aea101198ba69ed608ee40f22"
APPROVED_COMBINED_IDENTITY = "c3eb81e3fedb9590e6c33a38154722c0d9b697c7059d995c513c355a3143e070"
EXPECTED_SCOREABLE_B = 73
PROMPT_RELATIVE_PATH = Path("ops/goodnotes/gsqs/b0/incumbent-prompt-v1.txt")
CATALOG_RELATIVE_PATH = Path("ops/goodnotes/gsqs/hw-combined-v1/public_catalog.json")
_FORBIDDEN_ANALYZER_KEYS = frozenset(
    {
        "transcription_gold",
        "gold",
        "regions",
        "label",
        "label_sha256",
        "private_label",
        "expected_score",
        "diagnostics",
    }
)


class B0RunState(StrEnum):
    PREPARED = "PREPARED"
    AUTHORIZED = "AUTHORIZED"
    RUNNING = "RUNNING"
    EVALUATING = "EVALUATING"
    COMPLETE = "COMPLETE"
    INVALID = "INVALID"
    ABORTED = "ABORTED"


@dataclass(frozen=True, slots=True)
class RepositoryIdentity:
    commit: str
    tree: str
    dirty: bool


@dataclass(frozen=True, slots=True)
class AnalyzerCaseInput:
    case_id: str
    corpus_version: str
    raster_sha256: str
    interchange_schema_version: str
    image_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class FrozenAnalyzerConfig:
    analyzer_name: str
    analyzer_version: str
    model_identity: str
    prompt_config_identity: str
    prompt_text: str


@dataclass(frozen=True, slots=True)
class B0CensusMember:
    case_id: str
    raster_sha256: str
    case_digest: str
    file_sha256: str


@dataclass(frozen=True, slots=True)
class B0Census:
    corpus_version: str
    manifest_digest: str
    combined_identity: str
    partition: str
    members: tuple[B0CensusMember, ...]
    census_digest: str


@dataclass(frozen=True, slots=True)
class ExecutionAuthorization:
    authorization_id: str
    operation: str
    corpus_version: str
    corpus_manifest_digest: str
    combined_identity: str
    partition: str
    expected_case_count: int
    repetitions: int
    analyzer_name: str
    analyzer_version: str
    model_identity: str
    prompt_config_identity: str
    evaluator_behavior_identity: str
    repository_commit: str
    repository_tree: str
    decided_at: str
    operator_evidence_id: str
    prohibit_corpus_c: bool
    prohibit_self_improvement: bool
    prohibit_automatic_promotion: bool
    prohibit_deployment: bool


@dataclass(frozen=True, slots=True)
class PreflightReport:
    go: bool
    state: B0RunState
    reasons: tuple[str, ...]
    corpus_version: str
    manifest_digest: str
    combined_identity: str
    scoreable_b: int
    census_digest: str
    analyzer_name: str
    analyzer_version: str
    prompt_config_identity: str
    evaluator_behavior_identity: str
    repository_commit: str
    repository_tree: str
    disclosure_would_occur: bool


@dataclass(frozen=True, slots=True)
class B0Summary:
    repetition_count: int
    gsqs_values: tuple[float, ...]
    mean_gsqs: float
    median_gsqs: float
    min_gsqs: float
    max_gsqs: float
    range_gsqs: float
    stdev_gsqs: float
    component_means: Mapping[str, float]
    component_stdevs: Mapping[str, float]
    total_critical_errors: int
    per_run_critical_errors: tuple[int, ...]
    measurement_valid: bool
    candidate_config_digest: str
    corpus_manifest_digest: str
    evaluator_code_identity: str
    analyzer_name: str
    model_identity: str
    prompt_config_identity: str
    repository_commit: str
    repository_tree: str
    measured_b0: str
    self_improvement: str
    automatic_promotion: str


class AnalyzerAdapter(Protocol):
    def analyze(
        self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig
    ) -> dict[str, object]: ...


class UnboundIncumbentAdapter:
    """Production-shaped adapter that cannot disclose until a transport is bound."""

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        del case, config
        raise ValueError("incumbent transport is not bound; refusing disclosure")


class RecordingFakeAdapter:
    """Test/local adapter. Never performs an external call."""

    def __init__(self, documents: Mapping[str, Mapping[str, object]] | None = None) -> None:
        self.seen: list[AnalyzerCaseInput] = []
        self._documents = {key: dict(value) for key, value in (documents or {}).items()}

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        self.seen.append(case)
        payload = analyzer_request_payload(case, config)
        if _FORBIDDEN_ANALYZER_KEYS & set(payload):
            raise ValueError("analyzer request leaked evaluator fields")
        document = self._documents.get(case.case_id)
        if document is None:
            raise ValueError(f"fake analyzer has no document for {case.case_id}")
        return dict(document)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def prompt_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / PROMPT_RELATIVE_PATH


def catalog_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / CATALOG_RELATIVE_PATH


def prompt_config_identity(root: Path | None = None) -> str:
    return sha256(prompt_path(root).read_bytes()).hexdigest()


def load_frozen_prompt(root: Path | None = None) -> str:
    return prompt_path(root).read_text(encoding="utf-8")


def inspect_repository_identity(root: Path | None = None) -> RepositoryIdentity:
    cwd = root or repo_root()
    commit = _git(cwd, "rev-parse", "HEAD")
    tree = _git(cwd, "rev-parse", "HEAD^{tree}")
    porcelain = _git(cwd, "status", "--porcelain")
    return RepositoryIdentity(commit=commit, tree=tree, dirty=bool(porcelain))


def load_execution_authorization(path: Path) -> ExecutionAuthorization:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("authorization must be a JSON object")
    return authorization_from_mapping(payload)


def authorization_from_mapping(payload: Mapping[str, object]) -> ExecutionAuthorization:
    return ExecutionAuthorization(
        authorization_id=_required_token(payload, "authorization_id"),
        operation=_required_token(payload, "operation"),
        corpus_version=_required_token(payload, "corpus_version"),
        corpus_manifest_digest=_required_token(payload, "corpus_manifest_digest"),
        combined_identity=_required_token(payload, "combined_identity"),
        partition=_required_token(payload, "partition"),
        expected_case_count=_required_int(payload, "expected_case_count"),
        repetitions=_required_int(payload, "repetitions"),
        analyzer_name=_required_token(payload, "analyzer_name"),
        analyzer_version=_required_token(payload, "analyzer_version"),
        model_identity=_required_token(payload, "model_identity"),
        prompt_config_identity=_required_token(payload, "prompt_config_identity"),
        evaluator_behavior_identity=_required_token(payload, "evaluator_behavior_identity"),
        repository_commit=_required_token(payload, "repository_commit"),
        repository_tree=_required_token(payload, "repository_tree"),
        decided_at=_required_token(payload, "decided_at"),
        operator_evidence_id=_required_token(payload, "operator_evidence_id"),
        prohibit_corpus_c=_required_true(payload, "prohibit_corpus_c"),
        prohibit_self_improvement=_required_true(payload, "prohibit_self_improvement"),
        prohibit_automatic_promotion=_required_true(payload, "prohibit_automatic_promotion"),
        prohibit_deployment=_required_true(payload, "prohibit_deployment"),
    )


def partition_b_census(catalog: Mapping[str, object]) -> B0Census:
    if catalog.get("corpus_version") != HANDWRITING_CORPUS_VERSION:
        raise ValueError("catalog corpus_version is not gsqs-hw-combined-v1")
    members: list[B0CensusMember] = []
    raw_cases = catalog.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("catalog cases missing")
    for raw in raw_cases:
        if not isinstance(raw, Mapping):
            raise ValueError("catalog case is not an object")
        if raw.get("excluded") or raw.get("partition") != CorpusPartition.B.value:
            continue
        if raw.get("review_state") != ReviewState.APPROVED.value:
            continue
        if raw.get("label_provenance") != LABEL_PROVENANCE_OPERATOR:
            continue
        members.append(
            B0CensusMember(
                case_id=str(raw["case_id"]),
                raster_sha256=str(raw["raster_sha256"]),
                case_digest=str(raw["case_digest"]),
                file_sha256=str(raw["file_sha256"]),
            )
        )
    members.sort(key=lambda item: item.case_id)
    ids = [item.case_id for item in members]
    if len(ids) != len(set(ids)):
        raise ValueError("Partition B census has duplicate case ids")
    if len(members) != EXPECTED_SCOREABLE_B:
        raise ValueError(
            f"Partition B scoreable census is {len(members)}, not {EXPECTED_SCOREABLE_B}"
        )
    digest = sha256(
        canonical_dumps(
            {
                "case_digests": [item.case_digest for item in members],
                "case_ids": ids,
                "partition": CorpusPartition.B.value,
                "raster_sha256": [item.raster_sha256 for item in members],
            }
        ).encode()
    ).hexdigest()
    return B0Census(
        corpus_version=str(catalog["corpus_version"]),
        manifest_digest=str(catalog["manifest_digest"]),
        combined_identity=str(catalog["combined_identity"]),
        partition=CorpusPartition.B.value,
        members=tuple(members),
        census_digest=digest,
    )


def analyzer_request_payload(
    case: AnalyzerCaseInput, config: FrozenAnalyzerConfig
) -> dict[str, object]:
    return {
        "analyzer_name": config.analyzer_name,
        "analyzer_version": config.analyzer_version,
        "case_id": case.case_id,
        "content_sha256": case.raster_sha256,
        "corpus_version": case.corpus_version,
        "has_image": case.image_bytes is not None,
        "image_byte_count": 0 if case.image_bytes is None else len(case.image_bytes),
        "interchange_schema_version": case.interchange_schema_version,
        "model_identity": config.model_identity,
        "prompt_config_identity": config.prompt_config_identity,
        "prompt_text": config.prompt_text,
    }


def preflight(
    *,
    root: Path | None = None,
    catalog: Mapping[str, object] | None = None,
    repository: RepositoryIdentity | None = None,
    authorization: ExecutionAuthorization | None = None,
    expected_manifest_digest: str = APPROVED_MANIFEST_DIGEST,
    expected_combined_identity: str = APPROVED_COMBINED_IDENTITY,
    require_clean: bool = True,
) -> PreflightReport:
    reasons: list[str] = []
    base = root or repo_root()
    payload = catalog or load_public_catalog(catalog_path(base))
    identity = repository or inspect_repository_identity(base)
    if require_clean and identity.dirty:
        reasons.append("repository worktree is dirty")
    require_live_b0_repository_identity(
        repository_commit=identity.commit, repository_tree=identity.tree
    )
    if payload.get("FIXED_LABELED_CORPUS_APPROVED") is not True:
        reasons.append("FIXED_LABELED_CORPUS_APPROVED is not true")
    if payload.get("CONTROLLED_HANDWRITING_CORPUS") != "APPROVED":
        reasons.append("CONTROLLED_HANDWRITING_CORPUS is not APPROVED")
    if payload.get("b0_suitable") is not True:
        reasons.append("b0_suitable is not true")
    if str(payload.get("manifest_digest")) != expected_manifest_digest:
        reasons.append("corpus manifest digest mismatch")
    if str(payload.get("combined_identity")) != expected_combined_identity:
        reasons.append("combined identity mismatch")
    census = partition_b_census(payload)
    behavior = evaluator_code_identity()
    prompt_id = prompt_config_identity(base)
    if authorization is not None:
        reasons.extend(_authorization_defects(authorization, census, identity, behavior, prompt_id))
    go = not reasons
    return PreflightReport(
        go=go,
        state=B0RunState.PREPARED,
        reasons=tuple(reasons),
        corpus_version=census.corpus_version,
        manifest_digest=census.manifest_digest,
        combined_identity=census.combined_identity,
        scoreable_b=len(census.members),
        census_digest=census.census_digest,
        analyzer_name=INCUMBENT_ANALYZER_NAME,
        analyzer_version=INCUMBENT_ANALYZER_VERSION,
        prompt_config_identity=prompt_id,
        evaluator_behavior_identity=behavior,
        repository_commit=identity.commit,
        repository_tree=identity.tree,
        disclosure_would_occur=False,
    )


def validate_authorization(
    authorization: ExecutionAuthorization,
    *,
    census: B0Census,
    repository: RepositoryIdentity,
    evaluator_behavior: str,
    prompt_id: str,
) -> None:
    defects = _authorization_defects(
        authorization, census, repository, evaluator_behavior, prompt_id
    )
    if defects:
        raise ValueError(defects[0])


def admit_repetition_outputs(
    documents: Sequence[Mapping[str, object]],
    *,
    census: B0Census,
    config: FrozenAnalyzerConfig,
) -> tuple[AnalyzerOutput, ...]:
    if len(documents) != len(census.members):
        raise ValueError("outputs must cover the Partition B census exactly")
    expected = {item.case_id: item for item in census.members}
    seen: set[str] = set()
    outputs: list[AnalyzerOutput] = []
    for document in documents:
        parsed = parse_interchange(dict(document))
        if parsed.case_id in seen:
            raise ValueError("duplicate analyzer output")
        if parsed.case_id not in expected:
            raise ValueError("unknown analyzer output case")
        member = expected[parsed.case_id]
        if parsed.corpus_version != census.corpus_version:
            raise ValueError("wrong corpus_version")
        if parsed.content_sha256 != member.raster_sha256:
            raise ValueError("content/raster binding mismatch")
        if parsed.analyzer_name != config.analyzer_name:
            raise ValueError("analyzer name mismatch")
        if parsed.analyzer_version != config.analyzer_version:
            raise ValueError("analyzer version mismatch")
        extra = dict(parsed.extra)
        claimed_model = extra.get("model_identity") or document.get("model_identity")
        claimed_prompt = extra.get("prompt_config_identity") or document.get(
            "prompt_config_identity"
        )
        if str(claimed_model) != config.model_identity:
            raise ValueError("model identity mismatch")
        if str(claimed_prompt) != config.prompt_config_identity:
            raise ValueError("prompt identity mismatch")
        seen.add(parsed.case_id)
        outputs.append(parsed)
    missing = set(expected) - seen
    if missing:
        raise ValueError("missing expected analyzer output")
    derive_pairs = {(item.analyzer_name, item.analyzer_version) for item in outputs}
    if len(derive_pairs) != 1:
        raise ValueError("mixed analyzer identity")
    require_live_b0_identities(
        analyzer_name=config.analyzer_name,
        model_identity=config.model_identity,
        prompt_config_identity=config.prompt_config_identity,
    )
    return tuple(
        next(item for item in outputs if item.case_id == member.case_id)
        for member in census.members
    )


def execute_measured_b0(
    *,
    authorization: ExecutionAuthorization,
    census: B0Census,
    evaluator_cases: Sequence[CorpusCase],
    manifest: CorpusManifest,
    adapter: AnalyzerAdapter,
    config: FrozenAnalyzerConfig,
    repository: RepositoryIdentity,
    image_loader: Callable[[str], bytes] | None = None,
    measured_at: datetime | None = None,
) -> tuple[tuple[MeasurementRecord, ...], B0RunState]:
    if repository.dirty:
        raise ValueError("repository worktree is dirty")
    validate_authorization(
        authorization,
        census=census,
        repository=repository,
        evaluator_behavior=evaluator_code_identity(),
        prompt_id=config.prompt_config_identity,
    )
    if isinstance(adapter, UnboundIncumbentAdapter):
        raise ValueError("incumbent transport is not bound; refusing disclosure")
    _assert_evaluator_plane(evaluator_cases, census)
    records: list[MeasurementRecord] = []
    stamp = measured_at or datetime.now(UTC)
    for repetition in range(1, authorization.repetitions + 1):
        documents: list[dict[str, object]] = []
        for member in census.members:
            image = None if image_loader is None else image_loader(member.case_id)
            request = AnalyzerCaseInput(
                case_id=member.case_id,
                corpus_version=census.corpus_version,
                raster_sha256=member.raster_sha256,
                interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
                image_bytes=image,
            )
            raw = adapter.analyze(request, config)
            documents.append(dict(raw))
        try:
            outputs = admit_repetition_outputs(documents, census=census, config=config)
            _result, record = score_partition(
                evaluator_cases,
                outputs,
                partition=CorpusPartition.B,
                manifest=manifest,
                analyzer_name=config.analyzer_name,
                analyzer_version=config.analyzer_version,
                run_repetition=repetition,
                measured_at=stamp,
                model_identity=config.model_identity,
                prompt_config_identity=config.prompt_config_identity,
                repository_commit=repository.commit,
                repository_tree=repository.tree,
            )
        except ValueError as error:
            raise ValueError(f"repetition {repetition} invalid: {error}") from error
        records.append(record)
    return tuple(records), B0RunState.COMPLETE


def aggregate_b0_measurements(records: Sequence[MeasurementRecord]) -> B0Summary:
    if len(records) < B0_MIN_REPETITIONS:
        raise ValueError("fewer than minimum repetitions cannot establish aggregate B0")
    if any(not item.measurement_valid for item in records):
        raise ValueError("invalid measurement rejected")
    first = records[0]
    fields = (
        "candidate_config_digest",
        "corpus_manifest_digest",
        "partition",
        "evaluator_code_identity",
        "analyzer_name",
        "analyzer_version",
        "model_identity",
        "prompt_config_identity",
        "repository_commit",
        "repository_tree",
    )
    for field in fields:
        values = {getattr(item, field) for item in records}
        if len(values) != 1:
            raise ValueError(f"mixed {field}")
    gsqs = tuple(item.gsqs for item in records)
    components = (
        "boundary",
        "transcription",
        "transcription_status",
        "primary_class",
        "secondary_tag",
        "candidate_ranking",
        "confidence_calibration",
    )
    means = {
        name: statistics.fmean(getattr(item.scores, name) for item in records)
        for name in components
    }
    stdevs = {
        name: (
            statistics.pstdev(getattr(item.scores, name) for item in records)
            if len(records) > 1
            else 0.0
        )
        for name in components
    }
    critical = tuple(len(item.critical_errors) for item in records)
    return B0Summary(
        repetition_count=len(records),
        gsqs_values=gsqs,
        mean_gsqs=statistics.fmean(gsqs),
        median_gsqs=statistics.median(gsqs),
        min_gsqs=min(gsqs),
        max_gsqs=max(gsqs),
        range_gsqs=max(gsqs) - min(gsqs),
        stdev_gsqs=statistics.pstdev(gsqs) if len(gsqs) > 1 else 0.0,
        component_means=means,
        component_stdevs=stdevs,
        total_critical_errors=sum(critical),
        per_run_critical_errors=critical,
        measurement_valid=True,
        candidate_config_digest=first.candidate_config_digest,
        corpus_manifest_digest=first.corpus_manifest_digest,
        evaluator_code_identity=first.evaluator_code_identity,
        analyzer_name=first.analyzer_name,
        model_identity=str(first.model_identity),
        prompt_config_identity=str(first.prompt_config_identity),
        repository_commit=str(first.repository_commit),
        repository_tree=str(first.repository_tree),
        measured_b0=MEASURED_B0_NOT_YET_ESTABLISHED,
        self_improvement=SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
        automatic_promotion=AUTOMATIC_PROMOTION_DISABLED,
    )


def write_public_evidence(
    directory: Path,
    *,
    report: PreflightReport,
    records: Sequence[MeasurementRecord] | None = None,
    summary: B0Summary | None = None,
) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    control = {
        "AUTOMATIC_PROMOTION": AUTOMATIC_PROMOTION_DISABLED,
        "EXTERNAL_MODEL_DISCLOSURE": "NONE",
        "MEASURED_B0": MEASURED_B0_NOT_YET_ESTABLISHED,
        "SELF_IMPROVEMENT_EVALUATION": SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
        "census_digest": report.census_digest,
        "combined_identity": report.combined_identity,
        "corpus_version": report.corpus_version,
        "disclosure_would_occur": False,
        "evaluator_behavior_identity": report.evaluator_behavior_identity,
        "manifest_digest": report.manifest_digest,
        "prompt_config_identity": report.prompt_config_identity,
        "repository_commit": report.repository_commit,
        "repository_tree": report.repository_tree,
        "scoreable_b": report.scoreable_b,
        "state": report.state.value,
    }
    members = {
        "RUN_CONTROL.json": json.dumps(control, indent=2, sort_keys=True) + "\n",
        "ANALYZER_CONFIG.json": json.dumps(
            {
                "analyzer_name": report.analyzer_name,
                "analyzer_version": report.analyzer_version,
                "prompt_config_identity": report.prompt_config_identity,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    if records:
        for record in records:
            name = f"MEASUREMENT-{record.run_repetition:03d}.json"
            members[name] = json.dumps(record.canonical_dict(), indent=2, sort_keys=True) + "\n"
    if summary is not None:
        members["B0_SUMMARY.json"] = (
            json.dumps(_summary_dict(summary), indent=2, sort_keys=True) + "\n"
        )
    written: dict[str, str] = {}
    for name, body in members.items():
        target = directory / name
        target.write_text(body, encoding="utf-8")
        written[name] = sha256(body.encode()).hexdigest()
    index = {
        "MEASURED_B0": MEASURED_B0_NOT_YET_ESTABLISHED,
        "digests": written,
    }
    index_body = json.dumps(index, indent=2, sort_keys=True) + "\n"
    (directory / "EVIDENCE_INDEX.json").write_text(index_body, encoding="utf-8")
    written["EVIDENCE_INDEX.json"] = sha256(index_body.encode()).hexdigest()
    return written


def frozen_incumbent_config(
    *,
    model_identity: str,
    root: Path | None = None,
) -> FrozenAnalyzerConfig:
    return FrozenAnalyzerConfig(
        analyzer_name=INCUMBENT_ANALYZER_NAME,
        analyzer_version=INCUMBENT_ANALYZER_VERSION,
        model_identity=model_identity,
        prompt_config_identity=prompt_config_identity(root),
        prompt_text=load_frozen_prompt(root),
    )


def _authorization_defects(
    authorization: ExecutionAuthorization,
    census: B0Census,
    repository: RepositoryIdentity,
    evaluator_behavior: str,
    prompt_id: str,
) -> list[str]:
    defects: list[str] = []
    if authorization.operation != EXECUTE_MEASURED_B0:
        defects.append("wrong operation")
    if authorization.corpus_version != census.corpus_version:
        defects.append("wrong corpus version")
    if authorization.corpus_manifest_digest != census.manifest_digest:
        defects.append("wrong corpus digest")
    if authorization.combined_identity != census.combined_identity:
        defects.append("wrong combined identity")
    if authorization.partition != CorpusPartition.B.value:
        defects.append("wrong partition")
    if authorization.expected_case_count != len(census.members):
        defects.append("wrong expected case count")
    if authorization.corpus_version == HANDWRITING_CORPUS_VERSION and (
        authorization.expected_case_count != EXPECTED_SCOREABLE_B
        or len(census.members) != EXPECTED_SCOREABLE_B
    ):
        defects.append("wrong expected case count")
    if authorization.repetitions < B0_MIN_REPETITIONS:
        defects.append("wrong repetition scope")
    if authorization.analyzer_name != INCUMBENT_ANALYZER_NAME:
        defects.append("wrong analyzer")
    if authorization.analyzer_version != INCUMBENT_ANALYZER_VERSION:
        defects.append("wrong analyzer version")
    if authorization.prompt_config_identity != prompt_id:
        defects.append("wrong prompt identity")
    if authorization.evaluator_behavior_identity != evaluator_behavior:
        defects.append("wrong evaluator identity")
    if authorization.repository_commit != repository.commit:
        defects.append("wrong commit")
    if authorization.repository_tree != repository.tree:
        defects.append("wrong tree")
    if not authorization.prohibit_corpus_c:
        defects.append("authorization cannot enable C")
    if not authorization.prohibit_self_improvement:
        defects.append("authorization cannot enable self-improvement")
    if not authorization.prohibit_automatic_promotion:
        defects.append("authorization cannot enable promotion")
    if not authorization.prohibit_deployment:
        defects.append("authorization cannot enable deployment")
    require_live_b0_identities(
        analyzer_name=authorization.analyzer_name,
        model_identity=authorization.model_identity,
        prompt_config_identity=authorization.prompt_config_identity,
    )
    return defects


def _assert_evaluator_plane(cases: Sequence[CorpusCase], census: B0Census) -> None:
    selected = [case for case in cases if case.partition is CorpusPartition.B and case.scoreable]
    ids = [case.case_id for case in selected]
    if ids != [member.case_id for member in census.members]:
        raise ValueError("evaluator cases do not match Partition B census")
    content = {case.case_id: case.content_sha256 for case in selected}
    for member in census.members:
        if content[member.case_id] != member.raster_sha256:
            raise ValueError("evaluator raster binding mismatch")


def _summary_dict(summary: B0Summary) -> dict[str, object]:
    return {
        "AUTOMATIC_PROMOTION": summary.automatic_promotion,
        "MEASURED_B0": summary.measured_b0,
        "SELF_IMPROVEMENT_EVALUATION": summary.self_improvement,
        "analyzer_name": summary.analyzer_name,
        "candidate_config_digest": summary.candidate_config_digest,
        "component_means": dict(summary.component_means),
        "component_stdevs": dict(summary.component_stdevs),
        "corpus_manifest_digest": summary.corpus_manifest_digest,
        "evaluator_code_identity": summary.evaluator_code_identity,
        "gsqs_values": list(summary.gsqs_values),
        "max_gsqs": summary.max_gsqs,
        "mean_gsqs": summary.mean_gsqs,
        "measurement_valid": summary.measurement_valid,
        "median_gsqs": summary.median_gsqs,
        "min_gsqs": summary.min_gsqs,
        "model_identity": summary.model_identity,
        "per_run_critical_errors": list(summary.per_run_critical_errors),
        "prompt_config_identity": summary.prompt_config_identity,
        "range_gsqs": summary.range_gsqs,
        "repetition_count": summary.repetition_count,
        "repository_commit": summary.repository_commit,
        "repository_tree": summary.repository_tree,
        "stdev_gsqs": summary.stdev_gsqs,
        "total_critical_errors": summary.total_critical_errors,
    }


def _required_token(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"authorization missing {key}")
    return value


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"authorization missing {key}")
    return value


def _required_true(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if value is not True:
        raise ValueError(f"authorization missing required prohibition {key}")
    return True


def _git(cwd: Path, *args: str) -> str:
    git = shutil.which("git")
    if git is None:
        raise ValueError("git identity inspection failed")
    completed = subprocess.run(  # noqa: S603
        [git, *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise ValueError("git identity inspection failed")
    return completed.stdout.strip()
