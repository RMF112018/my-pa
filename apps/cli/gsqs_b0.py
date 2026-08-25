"""Operator control plane for governed GSQS live-B0 preflight and execute."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from uuid import uuid4

from my_pa.adapters.mcp.server import serve_stdio
from my_pa.application.goodnotes_gsqs import (
    EVALUATOR_NAME,
    EVALUATOR_VERSION,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    CorpusPartition,
    MeasurementRecord,
)
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    MODEL_CLIENT_SYNTHETIC,
    AcquisitionError,
    assert_acquisition_permitted,
    load_acquisition_authorization,
)
from my_pa.application.goodnotes_gsqs_b0_disclosure_journal import (
    EVENT_AUTH_PROBE_COMPLETED,
    DisclosureJournal,
    DisclosureState,
)
from my_pa.application.goodnotes_gsqs_b0_mcp import (
    CAPTURE_SCHEMA_VERSION,
    EVALUATION_MCP_PURPOSES,
    EVALUATION_MCP_TOOLS,
    MCP_EVALUATION_BINDING_MODES,
    MCP_EVALUATION_SURFACE_STDIO,
    CapturedAnalyzerAdapter,
    evaluation_handle_records,
    load_captured_repetitions,
    stage_evaluation_pages,
    validate_mcp_evaluation_bindings,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import (
    RouteLLMClientActivationError,
    bind_model_client,
)
from my_pa.application.goodnotes_gsqs_b0_orchestrator import (
    OrchestratorError,
    acquire_repetition,
)
from my_pa.application.goodnotes_gsqs_b0_stdio_session import (
    StdioEvalSession,
    serve_eval_mcp_command,
    stdio_env,
)
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import load_synthetic_campaign
from my_pa.application.goodnotes_gsqs_corpus import CorpusCase, CorpusManifest, freeze_manifest
from my_pa.application.goodnotes_gsqs_evaluator_binding import (
    AdmittedEvaluatorPlane,
    load_and_admit_evaluator_plane,
)
from my_pa.application.goodnotes_gsqs_harness import parse_interchange, score_partition
from my_pa.application.goodnotes_gsqs_hw_corpus import load_public_catalog
from my_pa.application.goodnotes_gsqs_live_b0 import (
    AnalyzerAdapter,
    AnalyzerCaseInput,
    B0Census,
    B0RunState,
    ExecutionAuthorization,
    FrozenAnalyzerConfig,
    PreflightReport,
    RepositoryIdentity,
    UnboundIncumbentAdapter,
    aggregate_b0_measurements,
    assert_evaluator_plane,
    catalog_path,
    execute_measured_b0,
    frozen_incumbent_config,
    inspect_repository_identity,
    load_execution_authorization,
    partition_b_census,
    preflight,
    prompt_config_identity,
    prompt_path,
    repo_root,
    validate_route_llm_execution_bindings,
    write_evaluation_handles,
    write_public_evidence,
)
from my_pa.application.goodnotes_gsqs_provider_model_mapping import (
    ProviderModelMapping,
    load_provider_model_mapping,
)
from my_pa.application.goodnotes_gsqs_remote_eval import (
    RemoteEvalService,
    default_evaluator_behavior_sha256,
)
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_INVALID_TRANSITION,
    ERROR_NO_ACTIVE_SESSION,
    TERMINAL_STATES,
    ManifestCase,
    RemoteEvalCreateRequest,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSession,
    SessionState,
    SessionStatus,
    remote_eval_canonical_sha256,
)
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import FilesystemDisclosureJournal
from my_pa.application.goodnotes_gsqs_remote_eval_staging import FilesystemRasterStaging
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    FilesystemRemoteEvalStore,
    atomic_write_json,
    session_directory,
)
from my_pa.application.goodnotes_gsqs_routellm_candidate import (
    composite_model_identity,
    load_route_llm_candidate,
)
from my_pa.application.goodnotes_gsqs_routellm_envelope import (
    assemble_authoritative_interchange,
    build_chat_completions_body,
    detect_image_mime,
    parse_semantic_content,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.goodnotes.models import GoodNotesPageRaster, GoodNotesPageWork
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.infrastructure.gsqs_b0_evaluation import GsqsB0EvaluationUnitOfWork
from my_pa.infrastructure.gsqs_routellm_transport import (
    RouteLLMHttpResult,
    RouteLLMPostResponseError,
    get_models_with_retry,
    origins_equal,
    parse_https_origin,
    post_chat_completion,
    validate_route_llm_models_probe,
)

EXIT_OK = 0
EXIT_REFUSED = 1
API_KEY_ENV = "MY_PA_ROUTELLM_API_KEY"
BASE_URL_ENV = "MY_PA_ROUTELLM_BASE_URL"
RASTER_ROOT_ENV = "MY_PA_GSQS_B0_RASTER_ROOT"
CANDIDATE_RELATIVE = Path("ops/goodnotes/gsqs/b0/routellm-goodnotes-b0-v1.json")


class RouteLLMIncumbentAdapter:
    """CLI composition of envelope assembly and RouteLLM HTTPS transport."""

    requires_durable_disclosure_journal = True

    def __init__(
        self,
        *,
        origin: str,
        api_key: str,
        poster: Callable[..., RouteLLMHttpResult] = post_chat_completion,
    ) -> None:
        self._origin = parse_https_origin(origin)
        self._api_key = api_key
        self._poster = poster

    def analyze(self, case: AnalyzerCaseInput, config: FrozenAnalyzerConfig) -> dict[str, object]:
        image = case.image_bytes
        if not image:
            raise ValueError("image bytes required for RouteLLM analyze")
        mime = detect_image_mime(image)
        body = build_chat_completions_body(case, config, image_bytes=image, mime=mime)
        result = self._poster(origin=self._origin, api_key=self._api_key, body=body)
        try:
            semantic = parse_semantic_content(result.payload)
        except ValueError as error:
            raise RouteLLMPostResponseError(
                "routellm request failed: malformed semantic payload",
                http_status=result.status,
                error_class="MALFORMED_SEMANTIC",
            ) from error
        try:
            observed = result.payload.get("model")
            return assemble_authoritative_interchange(
                case,
                config,
                semantic,
                provenance={
                    "http_status": result.status,
                    "selected_model": observed,
                },
            )
        except ValueError as error:
            raise RouteLLMPostResponseError(
                "routellm request failed: malformed interchange envelope",
                http_status=result.status,
                error_class="MALFORMED_ENVELOPE",
            ) from error


def _preflight(args: argparse.Namespace) -> int:
    root = Path(args.repository_root) if args.repository_root else repo_root()
    authorization = (
        load_execution_authorization(Path(args.authorization)) if args.authorization else None
    )
    report = preflight(
        root=root,
        catalog=load_public_catalog(catalog_path(root)),
        repository=inspect_repository_identity(root),
        authorization=authorization,
    )
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    if args.evidence_dir:
        write_public_evidence(Path(args.evidence_dir), report=report)
    return EXIT_OK if report.go else EXIT_REFUSED


def _execute(args: argparse.Namespace) -> int:
    if args.authorization is None:
        raise ValueError("execute requires --authorization")
    root = Path(args.repository_root) if args.repository_root else repo_root()
    authorization = load_execution_authorization(Path(args.authorization))
    if args.model_identity != authorization.model_identity:
        raise ValueError("model identity mismatch")
    prompt_id = prompt_config_identity(root)
    if not _prompt_matches(root, args.prompt_config, prompt_id):
        raise ValueError("prompt identity mismatch")
    if args.repetitions != authorization.repetitions:
        raise ValueError("wrong repetition scope")
    report = preflight(
        root=root,
        catalog=load_public_catalog(catalog_path(root)),
        repository=inspect_repository_identity(root),
        authorization=authorization,
    )
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    if not report.go:
        return EXIT_REFUSED
    if not _bindings_complete(args, authorization, root):
        _ = UnboundIncumbentAdapter
        raise ValueError("incumbent transport is not bound; refusing disclosure")
    validate_route_llm_execution_bindings(authorization)
    candidate = load_route_llm_candidate(root / CANDIDATE_RELATIVE)
    identity = composite_model_identity(candidate)
    if identity != args.model_identity or identity != authorization.model_identity:
        raise ValueError("model identity mismatch")
    origin = parse_https_origin(authorization.route_llm_endpoint_origin)
    runtime = parse_https_origin(os.environ[BASE_URL_ENV])
    if not origins_equal(origin, runtime):
        raise ValueError("RouteLLM origin mismatch")
    catalog = load_public_catalog(catalog_path(root))
    census = partition_b_census(catalog)
    if not args.evaluator_corpus:
        raise ValueError("execute requires --evaluator-corpus")
    evaluator_plane = load_and_admit_evaluator_plane(
        Path(args.evaluator_corpus), census=census, catalog=catalog
    )
    mapping = None
    if authorization.provider_model_mapping_evidence_id:
        if not args.provider_mapping:
            raise ValueError("provider mapping evidence is required")
        mapping = load_provider_model_mapping(
            Path(args.provider_mapping),
            expected_evidence_id=authorization.provider_model_mapping_evidence_id,
        )
    config = frozen_incumbent_config(model_identity=identity, root=root)
    adapter = RouteLLMIncumbentAdapter(origin=origin, api_key=os.environ[API_KEY_ENV])
    return run_bound_execute(
        authorization=authorization,
        report=report,
        census=census,
        evaluator_cases=evaluator_plane,
        manifest=_catalog_manifest(catalog, census),
        config=config,
        repository=inspect_repository_identity(root),
        adapter=adapter,
        evidence_dir=Path(args.evidence_dir).resolve(),
        identity=identity,
        origin=origin,
        api_key=os.environ[API_KEY_ENV],
        image_loader=lambda case_id: _load_raster(
            Path(os.environ[RASTER_ROOT_ENV]).resolve(), case_id
        ),
        mapping=mapping,
        catalog=catalog,
    )


def _score(args: argparse.Namespace) -> int:
    if args.authorization is None:
        raise ValueError("score requires --authorization")
    if not args.evaluator_corpus:
        raise ValueError("score requires --evaluator-corpus")
    if not args.analyzer_output_dir:
        raise ValueError("score requires --analyzer-output-dir")
    if not args.evidence_dir:
        raise ValueError("score requires --evidence-dir")
    root = Path(args.repository_root) if args.repository_root else repo_root()
    authorization = load_execution_authorization(Path(args.authorization))
    validate_mcp_evaluation_bindings(authorization)
    if args.model_identity != authorization.model_identity:
        raise ValueError("model identity mismatch")
    prompt_id = prompt_config_identity(root)
    if not _prompt_matches(root, args.prompt_config, prompt_id):
        raise ValueError("prompt identity mismatch")
    if args.repetitions != authorization.repetitions:
        raise ValueError("wrong repetition scope")
    report = preflight(
        root=root,
        catalog=load_public_catalog(catalog_path(root)),
        repository=inspect_repository_identity(root),
        authorization=authorization,
    )
    print(json.dumps(_report_dict(report), indent=2, sort_keys=True))
    if not report.go:
        return EXIT_REFUSED
    catalog = load_public_catalog(catalog_path(root))
    census = partition_b_census(catalog)
    evaluator_plane = load_and_admit_evaluator_plane(
        Path(args.evaluator_corpus), census=census, catalog=catalog
    )
    config = frozen_incumbent_config(model_identity=authorization.model_identity, root=root)
    captures = load_captured_repetitions(Path(args.analyzer_output_dir), census)
    adapter = CapturedAnalyzerAdapter(captures)
    evidence_dir = Path(args.evidence_dir).resolve()
    records, run_state = execute_measured_b0(
        authorization=authorization,
        census=census,
        evaluator_cases=evaluator_plane,
        manifest=_catalog_manifest(catalog, census),
        adapter=adapter,
        config=config,
        repository=inspect_repository_identity(root),
        image_loader=None,
        catalog=catalog,
    )
    summary = aggregate_b0_measurements(records)
    write_public_evidence(
        evidence_dir,
        report=report,
        records=records,
        summary=summary,
        analyzer_config={
            "model_identity": authorization.model_identity,
            "run_state": run_state.value,
        },
    )
    return EXIT_OK


def _local_operator() -> Principal:
    return Principal(
        principal_id=capture_principal_id(LOCAL_OPERATOR_UUID),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def compose_evaluation_service(
    pages: Sequence[tuple[GoodNotesPageWork, GoodNotesPageRaster]],
    *,
    clock: Callable[[], datetime] | None = None,
) -> ApplicationService:
    stamped = clock or (lambda: datetime.now(UTC))
    return ApplicationService(
        unit_of_work=lambda: GsqsB0EvaluationUnitOfWork(pages),
        limits=EffectiveLimits(
            max_page_size=200,
            default_page_size=50,
            max_fetch_bytes=8 * 1024 * 1024,
            max_enrollment_depth=0,
        ),
        clock=stamped,
        managed_store=None,
        relationship_intelligence_enabled=False,
    )


def _serve_eval_mcp(args: argparse.Namespace) -> int:
    if args.authorization is None:
        raise ValueError("serve-eval-mcp requires --authorization")
    root = Path(args.repository_root) if args.repository_root else repo_root()
    raster_root = os.environ.get(RASTER_ROOT_ENV)
    if not raster_root:
        raise ValueError("MY_PA_GSQS_B0_RASTER_ROOT is required")
    fixture = getattr(args, "campaign_fixture", None)
    if fixture:
        census = _synthetic_eval_census(Path(args.authorization), Path(fixture))
    else:
        authorization = load_execution_authorization(Path(args.authorization))
        validate_mcp_evaluation_bindings(authorization)
        report = preflight(
            root=root,
            catalog=load_public_catalog(catalog_path(root)),
            repository=inspect_repository_identity(root),
            authorization=authorization,
        )
        if not report.go:
            print(json.dumps(_report_dict(report), indent=2, sort_keys=True), file=sys.stderr)
            return EXIT_REFUSED
        catalog = load_public_catalog(catalog_path(root))
        census = partition_b_census(catalog)
    principal = _local_operator()
    created_at = datetime.now(UTC)
    pages = stage_evaluation_pages(
        census,
        raster_root=Path(raster_root).resolve(),
        principal_id=principal.principal_id,
        created_at=created_at,
    )
    if args.evidence_dir:
        write_evaluation_handles(
            Path(args.evidence_dir).resolve(),
            evaluation_handle_records(census, principal_id=principal.principal_id),
        )
    service = compose_evaluation_service(pages, clock=lambda: created_at)
    serve_stdio(
        service,
        principal=principal,
        allowed_tools=EVALUATION_MCP_TOOLS,
        allowed_capability_purposes=EVALUATION_MCP_PURPOSES,
    )
    return EXIT_OK


def _synthetic_eval_census(authorization_path: Path, fixture: Path) -> B0Census:
    authorization = load_acquisition_authorization(authorization_path)
    if authorization.mcp_evaluation_surface != MCP_EVALUATION_SURFACE_STDIO:
        raise ValueError("synthetic serve-eval-mcp requires stdio-isolated surface")
    if authorization.mcp_evaluation_binding_mode not in MCP_EVALUATION_BINDING_MODES:
        raise ValueError("synthetic serve-eval-mcp requires a local stdio binding")
    census, campaign_id = load_synthetic_campaign(fixture)
    assert_acquisition_permitted(
        authorization,
        repetition=authorization.repetition,
        corpus_version=census.corpus_version,
        combined_identity=census.combined_identity,
        model_identity=authorization.model_identity,
        prompt_config_identity=authorization.prompt_config_identity,
        candidate_identity=authorization.candidate_identity,
        model_client=authorization.model_client,
    )
    if authorization.campaign_id != campaign_id:
        raise ValueError("campaign_id mismatch")
    return census


def _acquire_repetition(args: argparse.Namespace) -> int:
    if args.authorization is None:
        raise ValueError("acquire-repetition requires --authorization")
    if args.output is None:
        raise ValueError("acquire-repetition requires --output")
    if args.campaign_fixture is None:
        raise ValueError("acquire-repetition requires --campaign-fixture")
    root = Path(args.repository_root) if args.repository_root else repo_root()
    authorization = load_acquisition_authorization(Path(args.authorization))
    census, campaign_id = load_synthetic_campaign(Path(args.campaign_fixture))
    raster_root = Path(args.raster_root).resolve() if args.raster_root else None
    if raster_root is None:
        env_root = os.environ.get(RASTER_ROOT_ENV)
        if not env_root:
            raise ValueError("MY_PA_GSQS_B0_RASTER_ROOT is required")
        raster_root = Path(env_root).resolve()
    candidate = load_route_llm_candidate(root / CANDIDATE_RELATIVE)
    identity = composite_model_identity(candidate)
    prompt_id = prompt_config_identity(root)
    if args.model_client != authorization.model_client:
        raise ValueError("model-client configuration mismatch")
    client = bind_model_client(args.model_client)
    config = frozen_incumbent_config(model_identity=identity, root=root)
    if config.prompt_config_identity != prompt_id:
        raise ValueError("prompt identity drift")
    output_dir = Path(args.output).resolve()
    evidence_dir = output_dir / "stdio-eval"
    session = StdioEvalSession(
        command=serve_eval_mcp_command(
            python=sys.executable,
            authorization=Path(args.authorization).resolve(),
            evidence_dir=evidence_dir,
            campaign_fixture=Path(args.campaign_fixture).resolve(),
        ),
        cwd=root,
        env=stdio_env(
            raster_root=raster_root,
            pythonpath=(root / "src", root),
        ),
        evidence_dir=evidence_dir,
    )
    result = acquire_repetition(
        authorization=authorization,
        census=census,
        campaign_id=campaign_id,
        repetition=args.repetition,
        output_dir=output_dir,
        config=config,
        candidate_identity=identity,
        model_client=client,
        session=session,
    )
    print(
        json.dumps(
            {
                "GSQS_B0_SCORING": "NOT_RUN",
                "MEASURED_B0": MEASURED_B0_NOT_YET_ESTABLISHED,
                "capture_path": str(result.capture_path) if result.capture_path else None,
                "captured": result.captured,
                "duplicates": result.duplicates,
                "missing": result.missing,
                "next_repetition_automatic": False,
                "repetition": result.repetition,
                "resumable": result.resumable,
                "state": result.state.value,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return EXIT_OK if result.state.value == "COMPLETE" else EXIT_REFUSED


def run_bound_execute(
    *,
    authorization: ExecutionAuthorization,
    report: PreflightReport,
    census: B0Census,
    evaluator_cases: Sequence[CorpusCase] | AdmittedEvaluatorPlane,
    manifest: CorpusManifest,
    config: FrozenAnalyzerConfig,
    repository: RepositoryIdentity,
    adapter: AnalyzerAdapter,
    evidence_dir: Path,
    identity: str,
    origin: str,
    api_key: str,
    image_loader: Callable[[str], bytes],
    mapping: ProviderModelMapping | None = None,
    probe: Callable[..., RouteLLMHttpResult] = get_models_with_retry,
    catalog: Mapping[str, object] | None = None,
) -> int:
    assert_evaluator_plane(evaluator_cases, census, catalog)
    journal = DisclosureJournal(evidence_dir, run_id=authorization.authorization_id or str(uuid4()))
    records: tuple[MeasurementRecord, ...] = ()
    run_state: B0RunState | None = None
    try:
        if journal.fold().unresolved_attempt_ids:
            raise ValueError("unresolved disclosure attempt; refusing to resume")
        probe_result = probe(origin=origin, api_key=api_key)
        validate_route_llm_models_probe(probe_result)
        journal.record_run_event(
            EVENT_AUTH_PROBE_COMPLETED,
            disclosure_state=DisclosureState.AUTHORIZED_NOT_YET_DISCLOSED,
        )
        records, run_state = execute_measured_b0(
            authorization=authorization,
            census=census,
            evaluator_cases=evaluator_cases,
            manifest=manifest,
            adapter=adapter,
            config=config,
            repository=repository,
            image_loader=image_loader,
            disclosure_journal=journal,
            provider_mapping=mapping,
            catalog=catalog,
        )
        return EXIT_OK
    finally:
        analyzer_config: dict[str, object] = {"model_identity": identity}
        if run_state is not None:
            analyzer_config["run_state"] = run_state.value
        write_public_evidence(
            evidence_dir,
            report=report,
            records=records or None,
            journal=journal,
            analyzer_config=analyzer_config,
        )


def _bindings_complete(args: argparse.Namespace, authorization: object, root: Path) -> bool:
    del root
    if not args.evidence_dir:
        return False
    if not os.environ.get(API_KEY_ENV) or not os.environ.get(BASE_URL_ENV):
        return False
    if not os.environ.get(RASTER_ROOT_ENV):
        return False
    origin = getattr(authorization, "route_llm_endpoint_origin", "")
    mode = getattr(authorization, "route_llm_server_side_binding_mode", "")
    evidence = getattr(authorization, "route_llm_server_side_evidence_id", "")
    return bool(origin and mode and evidence)


def _load_raster(root: Path, case_id: str) -> bytes:
    if not case_id or "/" in case_id or ".." in case_id:
        raise ValueError("case_id is invalid")
    for suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        candidate = root / f"{case_id}{suffix}"
        if candidate.is_symlink():
            raise ValueError("raster path must not be a symlink")
        if candidate.is_file():
            return candidate.read_bytes()
    raise ValueError("raster missing")


def _catalog_manifest(catalog: Mapping[str, object], census: B0Census) -> CorpusManifest:
    case_count = catalog.get("case_count")
    note_count = catalog.get("NOTE_UNIT_count")
    return CorpusManifest(
        corpus_version=str(catalog["corpus_version"]),
        generator_version="gsqs-hw-combined-v1",
        manifest_digest=str(catalog["manifest_digest"]),
        case_count=case_count if isinstance(case_count, int) else 0,
        note_unit_count=note_count if isinstance(note_count, int) else 0,
        partition_counts={"B": len(census.members)},
        case_digests={item.case_id: item.case_digest for item in census.members},
        approval_status="APPROVED",
        frozen=True,
        leakage_groups={},
    )


def _prompt_matches(root: Path, supplied: str, prompt_id: str) -> bool:
    if supplied in {prompt_id, str(prompt_path(root)), str(prompt_path(root).resolve())}:
        return True
    candidate = Path(supplied)
    return candidate.is_file() and sha256(candidate.read_bytes()).hexdigest() == prompt_id


def _report_dict(report: PreflightReport) -> dict[str, object]:
    payload: dict[str, object] = asdict(report)
    payload["state"] = report.state.value
    payload["verdict"] = "GO" if report.go else "NO-GO"
    payload["disclosure_would_occur"] = False
    return payload


REMOTE_EVAL_PROMPT_RELATIVE = Path("ops/goodnotes/gsqs/b0/chatllm-remote-eval-prompt-v1.txt")
REMOTE_EVAL_GENERATE_RELATIVE = Path("ops/goodnotes/gsqs/fixtures/remote-eval/generate.py")
REMOTE_EVAL_REPOSITORY_OWNER = "RMF112018"
REMOTE_EVAL_REPOSITORY_NAME = "my-pa"
REMOTE_EVAL_ANALYZER_ID = "gsqs-remote-eval-synthetic"
REMOTE_EVAL_ANALYZER_VERSION = "phase-a"


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _json_ready(value: object) -> object:
    if isinstance(value, datetime):
        return format_rfc3339(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_ready(item) for item in value]
    return value


def _print_json(payload: Mapping[str, object]) -> None:
    print(json.dumps(_json_ready(dict(payload)), indent=2, sort_keys=True))


def _remote_eval_guard(
    handler: Callable[[argparse.Namespace], Mapping[str, object]],
) -> Callable[[argparse.Namespace], int]:
    def wrapped(args: argparse.Namespace) -> int:
        try:
            payload = handler(args)
        except RemoteEvalError as error:
            _print_json({"ok": False, "code": error.code, "error": str(error)})
            return EXIT_REFUSED
        _print_json({"ok": True, **dict(payload)})
        return EXIT_OK

    return wrapped


def _cli_root(args: argparse.Namespace) -> Path:
    return Path(args.repository_root) if args.repository_root else repo_root()


def _load_generate_module(root: Path) -> ModuleType:
    path = root / REMOTE_EVAL_GENERATE_RELATIVE
    spec = importlib.util.spec_from_file_location("gsqs_remote_eval_generate", path)
    if spec is None or spec.loader is None:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "fixture generator is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prompt_path(args: argparse.Namespace, root: Path) -> Path:
    supplied = getattr(args, "prompt_config", None)
    if supplied:
        return Path(supplied)
    return root / REMOTE_EVAL_PROMPT_RELATIVE


def _prompt_sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "prompt file is missing")
    return sha256(path.read_bytes()).hexdigest()


def _compose_remote_eval(
    state_root: Path,
    source_root: Path | None = None,
    *,
    clock: UtcClock | None = None,
) -> tuple[RemoteEvalService, FilesystemRemoteEvalStore, UtcClock]:
    stamped = clock or UtcClock()
    store = FilesystemRemoteEvalStore(state_root)
    staging = FilesystemRasterStaging(state_root, source_root or state_root)
    disclosure = FilesystemDisclosureJournal(state_root, clock=stamped)
    service = RemoteEvalService(
        store=store,
        clock=stamped,
        staging=staging,
        disclosure=disclosure,
    )
    return service, store, stamped


def _require_session(
    store: FilesystemRemoteEvalStore, session_id: str
) -> tuple[RemoteEvalSession, SessionState]:
    session = store.load_session(session_id)
    state = store.load_state(session_id)
    if session is None or state is None:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session not found")
    return session, state


def _status_payload(status: SessionStatus) -> dict[str, object]:
    return {
        "active_repetition": status.active_repetition,
        "blocked_reason_code": status.blocked_reason_code,
        "captures_accepted": status.captures_accepted,
        "case_count": status.case_count,
        "expires_at": status.expires_at,
        "mode": status.mode,
        "next_case_ordinal": status.next_case_ordinal,
        "repetitions_required": status.repetitions_required,
        "session_id": status.session_id,
        "session_identity_sha256": status.session_identity_sha256,
        "state": status.state,
        "terminal_reason_code": status.terminal_reason_code,
    }


def _expected_raster_names() -> list[str]:
    return [f"syn-b-{index:03d}.png" for index in range(1, CASES_PER_REPETITION + 1)]


def _manifest_from_source(source_root: Path) -> tuple[ManifestCase, ...]:
    if not source_root.is_dir() or source_root.is_symlink():
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "source raster root is invalid")
    names = _expected_raster_names()
    present = {path.name for path in source_root.iterdir() if path.is_file()}
    if present != set(names):
        raise RemoteEvalError(
            ERROR_INTERNAL_FAIL_CLOSED,
            "source raster root must contain exactly syn-b-001.png .. syn-b-073.png",
        )
    cases: list[ManifestCase] = []
    for ordinal, name in enumerate(names, start=1):
        payload = (source_root / name).read_bytes()
        cases.append(
            ManifestCase(
                ordinal=ordinal,
                case_id=f"syn-b-{ordinal:03d}",
                content_sha256=sha256(payload).hexdigest(),
                byte_length=len(payload),
                staged_filename=name,
            )
        )
    return tuple(cases)


def _prepare_remote_eval(args: argparse.Namespace) -> Mapping[str, object]:
    root = _cli_root(args)
    state_root = Path(args.state_root)
    source_root = Path(args.source_raster_root)
    try:
        mode = RemoteEvalMode(args.mode)
    except ValueError as exc:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "unsupported remote-eval mode") from exc
    if mode is RemoteEvalMode.PHASE_C:
        raise RemoteEvalError(
            ERROR_FORBIDDEN_SCOPE,
            "PHASE_C session creation is fail-closed in Phase A",
        )
    prompt_path = _prompt_path(args, root)
    prompt_digest = _prompt_sha256(prompt_path)
    identity = inspect_repository_identity(root)
    cases = _manifest_from_source(source_root)
    public_manifest_sha256 = remote_eval_canonical_sha256(
        [
            {
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "ordinal": case.ordinal,
            }
            for case in cases
        ]
    )
    evaluator_behavior = default_evaluator_behavior_sha256()
    generate = _load_generate_module(root)
    combined_identity_sha256 = remote_eval_canonical_sha256(
        {
            "corpus_version": generate.CORPUS_VERSION,
            "evaluator_behavior_sha256": evaluator_behavior,
            "partition": "B",
            "public_manifest_sha256": public_manifest_sha256,
        }
    )
    clock = UtcClock()
    service, _store, stamped = _compose_remote_eval(state_root, source_root, clock=clock)
    session_id = args.session_id or uuid4().hex
    session = service.create_session(
        RemoteEvalCreateRequest(
            session_id=session_id,
            mode=mode,
            authorization_id=args.authorization_id,
            principal_id=capture_principal_id(LOCAL_OPERATOR_UUID),
            expires_at=stamped.now() + timedelta(seconds=args.expires_seconds),
            repository_owner=REMOTE_EVAL_REPOSITORY_OWNER,
            repository_name=REMOTE_EVAL_REPOSITORY_NAME,
            repository_commit_sha=identity.commit,
            repository_tree_sha=identity.tree,
            evaluator_id=EVALUATOR_NAME,
            evaluator_version=EVALUATOR_VERSION,
            evaluator_behavior_sha256=evaluator_behavior,
            corpus_version=generate.CORPUS_VERSION,
            public_manifest_sha256=public_manifest_sha256,
            combined_identity_sha256=combined_identity_sha256,
            analyzer_id=REMOTE_EVAL_ANALYZER_ID,
            analyzer_version=REMOTE_EVAL_ANALYZER_VERSION,
            semantic_prompt_sha256=prompt_digest,
            conversation_prompt_sha256=prompt_digest,
            model_selection_label=args.model_selection_label,
            cases=cases,
        )
    )
    service.seal_ready(session.session_id)
    status = service.status(session.session_id)
    return {
        **_status_payload(status),
        "conversation_prompt_sha256": prompt_digest,
        "semantic_prompt_sha256": prompt_digest,
    }


def _remote_eval_status(args: argparse.Namespace) -> Mapping[str, object]:
    service, _store, _clock = _compose_remote_eval(Path(args.state_root))
    return _status_payload(service.status(args.session_id))


def _open_repetition(args: argparse.Namespace) -> Mapping[str, object]:
    service, _store, _clock = _compose_remote_eval(Path(args.state_root))
    state = service.open_repetition(args.session_id, args.repetition)
    return {
        "active_repetition": state.active_repetition,
        "session_id": state.session_id,
        "state": state.state,
    }


def _export_remote_eval(args: argparse.Namespace) -> Mapping[str, object]:
    service, store, _clock = _compose_remote_eval(Path(args.state_root))
    _session, state = _require_session(store, args.session_id)
    _ = service
    completed = [item for item in state.repetitions if item.completed]
    if not completed:
        raise RemoteEvalError(ERROR_INVALID_TRANSITION, "no completed repetition to export")
    output_dir = Path(args.output_dir)
    written = store.write_canonical_export_dir(args.session_id, output_dir)
    if not written:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "export wrote no repetition files")
    for item in completed:
        store.write_repetition_export(args.session_id, item.repetition)
    return {
        "exported": [str(path) for path in written],
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "session_id": args.session_id,
    }


def _score_remote_eval(args: argparse.Namespace) -> Mapping[str, object]:
    root = _cli_root(args)
    service, store, clock = _compose_remote_eval(Path(args.state_root))
    session, state = _require_session(store, args.session_id)
    _ = service
    opened_incomplete = [item for item in state.repetitions if item.opened and not item.completed]
    completed = [item for item in state.repetitions if item.completed]
    if opened_incomplete:
        raise RemoteEvalError(ERROR_INVALID_TRANSITION, "an opened repetition is incomplete")
    if not completed:
        raise RemoteEvalError(ERROR_INVALID_TRANSITION, "no completed repetition to score")
    generate = _load_generate_module(root)
    cases = generate.synthetic_corpus_cases()
    session_cases = {case.case_id: case.content_sha256 for case in cases}
    manifest_cases = store.load_manifest(args.session_id)
    if manifest_cases is None:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "manifest not found")
    expected = {case.case_id: case.content_sha256 for case in manifest_cases.cases}
    if session_cases != expected:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "synthetic gold does not match session")
    frozen = freeze_manifest(
        cases,
        generator_version=generate.GENERATOR_VERSION,
        approval_status="APPROVED",
    )
    measurements: list[object] = []
    for item in completed:
        payload = store.export_repetition_documents(args.session_id, item.repetition)
        if payload.get("schema_version") != CAPTURE_SCHEMA_VERSION:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "capture schema mismatch")
        documents = payload.get("documents")
        if not isinstance(documents, list) or len(documents) != CASES_PER_REPETITION:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "incomplete capture export")
        outputs = [parse_interchange(document) for document in documents]
        _result, record = score_partition(
            cases,
            outputs,
            partition=CorpusPartition.B,
            manifest=frozen,
            analyzer_name=session.analyzer_id,
            analyzer_version=session.analyzer_version,
            run_repetition=item.repetition,
            measured_at=clock.now(),
            prompt_config_identity=session.semantic_prompt_sha256,
            repository_commit=session.repository_commit_sha,
            repository_tree=session.repository_tree_sha,
        )
        measurements.append(record.canonical_dict())
    body: dict[str, object] = {
        "MEASURED_B0": MEASURED_B0_NOT_YET_ESTABLISHED,
        "measurements": measurements,
        "session_id": args.session_id,
    }
    if args.evidence_dir:
        atomic_write_json(Path(args.evidence_dir) / "remote-eval-score.json", body)
    return body


def _abort_remote_eval(args: argparse.Namespace) -> Mapping[str, object]:
    service, _store, _clock = _compose_remote_eval(Path(args.state_root))
    state = service.abort(args.session_id, args.reason)
    return {"session_id": state.session_id, "state": state.state, "reason": args.reason}


def _clean_remote_eval(args: argparse.Namespace) -> Mapping[str, object]:
    _service, store, _clock = _compose_remote_eval(Path(args.state_root))
    _session, state = _require_session(store, args.session_id)
    if state.state not in TERMINAL_STATES:
        raise RemoteEvalError(ERROR_INVALID_TRANSITION, "session is not terminal")
    session_dir = session_directory(Path(args.state_root), args.session_id)
    for item in state.repetitions:
        if not item.completed:
            continue
        capture = session_dir / "captures" / f"repetition-{item.repetition:03d}.capture.json"
        if not capture.is_file():
            raise RemoteEvalError(
                ERROR_INVALID_TRANSITION,
                "completed repetition has no exported capture file",
            )
    store.remove_staged_rasters(args.session_id)
    _ = args.discard_captures
    return {
        "captures_discarded": False,
        "rasters_removed": True,
        "session_id": args.session_id,
        "state": state.state,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gsqs-b0", allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--repository-root", default=None)
    shared.add_argument("--authorization", default=None)
    shared.add_argument("--evidence-dir", default=None)
    preflight_cmd = commands.add_parser("preflight", parents=[shared])
    preflight_cmd.set_defaults(handler=_preflight)
    execute = commands.add_parser("execute", parents=[shared])
    execute.add_argument("--model-identity", required=True)
    execute.add_argument("--prompt-config", required=True)
    execute.add_argument("--repetitions", type=int, required=True)
    execute.add_argument("--provider-mapping", default="")
    execute.add_argument("--evaluator-corpus", default=None)
    execute.set_defaults(handler=_execute)
    score = commands.add_parser("score", parents=[shared])
    score.add_argument("--model-identity", required=True)
    score.add_argument("--prompt-config", required=True)
    score.add_argument("--repetitions", type=int, required=True)
    score.add_argument("--evaluator-corpus", required=True)
    score.add_argument("--analyzer-output-dir", required=True)
    score.set_defaults(handler=_score)
    serve_eval = commands.add_parser("serve-eval-mcp", parents=[shared])
    serve_eval.add_argument("--campaign-fixture", default=None)
    serve_eval.set_defaults(handler=_serve_eval_mcp)
    acquire = commands.add_parser("acquire-repetition", parents=[shared])
    acquire.add_argument("--repetition", type=int, required=True)
    acquire.add_argument("--output", required=True)
    acquire.add_argument("--campaign-fixture", required=True)
    acquire.add_argument("--model-client", default=MODEL_CLIENT_SYNTHETIC)
    acquire.add_argument("--raster-root", default=None)
    acquire.set_defaults(handler=_acquire_repetition)
    prepare_remote = commands.add_parser("prepare-remote-eval", parents=[shared])
    prepare_remote.add_argument("--state-root", required=True)
    prepare_remote.add_argument("--source-raster-root", required=True)
    prepare_remote.add_argument("--mode", default=RemoteEvalMode.SYNTHETIC_CANARY.value)
    prepare_remote.add_argument("--session-id", default=None)
    prepare_remote.add_argument("--authorization-id", default="synthetic-canary")
    prepare_remote.add_argument("--expires-seconds", type=int, default=86400)
    prepare_remote.add_argument("--model-selection-label", default="synthetic-canary")
    prepare_remote.add_argument("--prompt-config", default=None)
    prepare_remote.set_defaults(handler=_remote_eval_guard(_prepare_remote_eval))
    status_remote = commands.add_parser("remote-eval-status", parents=[shared])
    status_remote.add_argument("--state-root", required=True)
    status_remote.add_argument("--session-id", required=True)
    status_remote.set_defaults(handler=_remote_eval_guard(_remote_eval_status))
    open_rep = commands.add_parser("remote-eval-open-repetition", parents=[shared])
    open_rep.add_argument("--state-root", required=True)
    open_rep.add_argument("--session-id", required=True)
    open_rep.add_argument("--repetition", type=int, required=True, choices=(1, 2, 3))
    open_rep.set_defaults(handler=_remote_eval_guard(_open_repetition))
    export_remote = commands.add_parser("remote-eval-export", parents=[shared])
    export_remote.add_argument("--state-root", required=True)
    export_remote.add_argument("--session-id", required=True)
    export_remote.add_argument("--output-dir", required=True)
    export_remote.set_defaults(handler=_remote_eval_guard(_export_remote_eval))
    score_remote = commands.add_parser("score-remote-eval", parents=[shared])
    score_remote.add_argument("--state-root", required=True)
    score_remote.add_argument("--session-id", required=True)
    score_remote.set_defaults(handler=_remote_eval_guard(_score_remote_eval))
    abort_remote = commands.add_parser("remote-eval-abort", parents=[shared])
    abort_remote.add_argument("--state-root", required=True)
    abort_remote.add_argument("--session-id", required=True)
    abort_remote.add_argument("--reason", required=True)
    abort_remote.set_defaults(handler=_remote_eval_guard(_abort_remote_eval))
    clean_remote = commands.add_parser("remote-eval-clean", parents=[shared])
    clean_remote.add_argument("--state-root", required=True)
    clean_remote.add_argument("--session-id", required=True)
    clean_remote.add_argument("--discard-captures", action="store_true")
    clean_remote.set_defaults(handler=_remote_eval_guard(_clean_remote_eval))
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        AcquisitionError,
        OrchestratorError,
        RouteLLMClientActivationError,
    ) as error:
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
