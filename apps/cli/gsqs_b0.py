"""Operator control plane for governed GSQS live-B0 preflight and execute."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from my_pa.application.goodnotes_gsqs import MeasurementRecord
from my_pa.application.goodnotes_gsqs_b0_disclosure_journal import (
    EVENT_AUTH_PROBE_COMPLETED,
    DisclosureJournal,
    DisclosureState,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    CorpusCase,
    CorpusManifest,
    load_evaluator_plane_cases,
)
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
    validate_evaluator_plane,
    validate_route_llm_execution_bindings,
    write_public_evidence,
)
from my_pa.application.goodnotes_gsqs_provider_model_mapping import (
    ProviderModelMapping,
    load_provider_model_mapping,
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
    evaluator_cases = load_evaluator_plane_cases(Path(args.evaluator_corpus))
    validate_evaluator_plane(evaluator_cases, census)
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
        evaluator_cases=evaluator_cases,
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
    )


def run_bound_execute(
    *,
    authorization: ExecutionAuthorization,
    report: PreflightReport,
    census: B0Census,
    evaluator_cases: Sequence[CorpusCase],
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
) -> int:
    validate_evaluator_plane(evaluator_cases, census)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
