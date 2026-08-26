"""Connected-MCP B0 prediction-acquisition workflow. No gold, no scoring.

ChatLLM may start and observe a repetition through production MCP tools. This
module owns durable workflow state and reuses `acquire_repetition`. It does not
replace the stdio analyzer plane. Real handwriting remains fail-closed.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import secrets
import threading
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    ACQUISITION_AUTH_SCHEMA,
    CAMPAIGN_CLASS_REAL,
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_CHATLLM,
    MODEL_CLIENT_SYNTHETIC,
    OPERATION_SYNTHETIC,
    OPERATION_SYNTHETIC_ROUTELLM,
    AcquisitionAuthorization,
    AcquisitionError,
    acquisition_from_mapping,
)
from my_pa.application.goodnotes_gsqs_b0_capture import (
    CaptureBinding,
    CaptureWriterError,
    repetition_filename,
    write_repetition_capture,
)
from my_pa.application.goodnotes_gsqs_b0_mcp import (
    MCP_BINDING_OPERATOR_LOCAL_STDIO,
    MCP_EVALUATION_SURFACE_STDIO,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import (
    B0ModelClient,
    B0ModelClientError,
    SyntheticB0ModelClient,
    bind_model_client,
)
from my_pa.application.goodnotes_gsqs_b0_orchestrator import (
    AcquisitionState,
    ContentSession,
    OrchestratorError,
    acquire_repetition,
)
from my_pa.application.goodnotes_gsqs_b0_routellm_activation import (
    RouteLLMClientActivation,
)
from my_pa.application.goodnotes_gsqs_b0_stdio_session import (
    StdioEvalSession,
    StdioHostError,
    serve_eval_mcp_command,
    stdio_env,
)
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import (
    ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS,
    SYNTHETIC_CAMPAIGN_ID,
    SYNTHETIC_CASE_COUNT,
    build_synthetic_campaign,
    build_synthetic_campaign_for_case_ids,
)
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    INCUMBENT_ANALYZER_VERSION,
    INTERCHANGE_SCHEMA_VERSION,
    parse_interchange,
)
from my_pa.application.goodnotes_gsqs_live_b0 import (
    AnalyzerCaseInput,
    B0Census,
    B0CensusMember,
    FrozenAnalyzerConfig,
    frozen_incumbent_config,
    load_frozen_prompt,
    prompt_config_identity,
    repo_root,
)
from my_pa.application.goodnotes_gsqs_routellm_candidate import (
    composite_model_identity,
    load_route_llm_candidate,
)
from my_pa.application.goodnotes_gsqs_routellm_envelope import assemble_authoritative_interchange
from my_pa.domain.common.time import format_rfc3339

WORKFLOW_SCHEMA = "gsqs-b0-workflow-v1"
WORKFLOW_ROOT_ENV = "MY_PA_GSQS_B0_WORKFLOW_ROOT"
ADMITTED_SYNTHETIC_AUTHORIZATION_ID = "synthetic-b0-commissioning"
ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID = "synthetic-routellm-commissioning"
CANDIDATE_RELATIVE = Path("ops/goodnotes/gsqs/b0/routellm-goodnotes-b0-v1.json")
STATE_NAME = "WORKFLOW_STATE.json"
INDEX_NAME = "IDEMPOTENCY_INDEX.json"
LOCK_NAME = "WORKFLOW.lock"

STATE_PREPARED = "PREPARED"
STATE_RUNNING = "RUNNING"
STATE_COMPLETE = "COMPLETE"
STATE_FAILED = "FAILED"
STATE_INTERRUPTED = "INTERRUPTED"
STATE_INVALID = "INVALID"
RASTER_ROLE = "gsqs-b0-case"
DRIVER_CLIENT_DRIVEN = "client-driven"

_ACQUISITION_TO_WORKFLOW = {
    AcquisitionState.IN_PROGRESS: STATE_RUNNING,
    AcquisitionState.COMPLETE: STATE_COMPLETE,
    AcquisitionState.INVALID: STATE_INVALID,
    AcquisitionState.INTERRUPTED: STATE_INTERRUPTED,
    AcquisitionState.NEVER_STARTED: STATE_PREPARED,
}

ContentSessionFactory = Callable[[Mapping[str, bytes]], ContentSession]


@dataclass(frozen=True, slots=True)
class WorkflowPorts:
    """Optional seams. Production supplies only `poster` from bootstrap."""

    model_client: B0ModelClient | None = None
    session_factory: ContentSessionFactory | None = None
    case_count: int | None = None
    activation: RouteLLMClientActivation | None = None
    poster: Callable[..., object] | None = None


def gsqs_b0_wait_in_process(ports: WorkflowPorts | None) -> bool:
    """True only for test seams that substitute stdio or census size.

    A production `WorkflowPorts(poster=...)` must not switch MCP `gsqs.start`
    from background execution to in-process wait.
    """

    if ports is None:
        return False
    return (
        ports.session_factory is not None
        or ports.model_client is not None
        or ports.case_count is not None
    )


class DiskContentSession:
    """Read campaign rasters from disk without spawning stdio. Tests only."""

    def __init__(self, rasters: Mapping[str, bytes]) -> None:
        self._rasters = dict(rasters)

    def initialize_and_list_tools(self) -> tuple[str, ...]:
        return ("goodnotes.content", "goodnotes.work")

    def fetch_png(self, *, case_id: str, expected_sha256: str) -> bytes:
        png = self._rasters[case_id]
        digest = sha256(png).hexdigest()
        if digest != expected_sha256:
            raise ValueError("raster hash mismatch")
        return png

    def close(self) -> None:
        return None


def workflow_root_from_env() -> Path:
    raw = os.environ.get(WORKFLOW_ROOT_ENV, "")
    if not raw or "\x00" in raw:
        raise InvalidRequestError(SafeDetail.RUN_ID)
    root = Path(raw)
    if root.is_symlink():
        raise InvalidRequestError(SafeDetail.RUN_ID)
    return root.resolve()


def start_workflow(
    *,
    workflow_root: Path,
    repository_root: Path,
    authorization_id: str,
    campaign_class: str,
    repetition: int,
    idempotency_key: str,
    python: str | None = None,
    ports: WorkflowPorts | None = None,
    wait: bool = True,
) -> dict[str, object]:
    """Start or reuse one synthetic B0 repetition. Real handwriting is denied.

    `wait=True` runs acquisition in-process (tests). Production MCP sets
    `wait=False` so the request can return while the server still owns the run.
    An MCP client timeout is not a workflow failure.
    """

    ports = ports or WorkflowPorts()
    if campaign_class == CAMPAIGN_CLASS_REAL:
        raise DeniedError()
    if campaign_class != CAMPAIGN_CLASS_SYNTHETIC:
        raise InvalidRequestError(SafeDetail.CAMPAIGN_CLASS)
    if repetition != 1:
        raise DeniedError()
    admitted_model_client, operation, activation = _admit_start_authorization(
        authorization_id=authorization_id,
        ports=ports,
        repository_root=repository_root,
    )
    census_token = _disclosure_census_token(
        model_client_identity=admitted_model_client,
        activation=activation,
        ports=ports,
    )
    root = _require_root(workflow_root)
    key = _idempotency_digest(authorization_id, repetition, idempotency_key, census_token)
    reuse_id: str | None = None
    run_dir: Path | None = None
    run_id = ""
    with _root_lock(root):
        existing = _lookup_idempotency(root, key)
        if existing is not None:
            reuse_id = str(existing["run_id"])
        else:
            conflict = _existing_subject(
                root,
                authorization_id=authorization_id,
                repetition=repetition,
                census_token=census_token,
            )
            if conflict is not None:
                raise ConflictError(SafeDetail.IDEMPOTENCY_CONFLICT)
            run_id = f"b0run_{uuid4().hex[:24]}"
            run_dir = root / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=False)
            started = _now()
            _write_state(
                run_dir,
                {
                    "schema_version": WORKFLOW_SCHEMA,
                    "run_id": run_id,
                    "authorization_id": authorization_id,
                    "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
                    "campaign_id": SYNTHETIC_CAMPAIGN_ID,
                    "repetition": repetition,
                    "idempotency_key_digest": key,
                    "census_token": census_token,
                    "state": STATE_PREPARED,
                    "expected_cases": 0,
                    "captured": 0,
                    "missing": 0,
                    "duplicates": 0,
                    "failure_class": None,
                    "capture_artifact": None,
                    "owner_pid": os.getpid(),
                    "started_at": started,
                    "updated_at": started,
                    "completed_at": None,
                    "scoring": "NOT_RUN",
                    "automatic_next_repetition": False,
                    "model_client": admitted_model_client,
                },
            )
            _record_idempotency(root, key, run_id)
    if reuse_id is not None:
        return status_workflow(workflow_root=root, run_id=reuse_id)
    if run_dir is None:
        raise InvalidRequestError(SafeDetail.RUN_ID)
    if admitted_model_client == MODEL_CLIENT_CHATLLM:
        return _prepare_client_driven_run(
            run_dir=run_dir,
            repository_root=repository_root,
        )
    if wait:
        return _execute_run(
            run_dir=run_dir,
            repository_root=repository_root,
            python=python,
            ports=ports,
            authorization_id=authorization_id,
            operation=operation,
            model_client_identity=admitted_model_client,
            activation=activation,
        )
    worker = threading.Thread(
        target=_execute_run,
        kwargs={
            "run_dir": run_dir,
            "repository_root": repository_root,
            "python": python,
            "ports": ports,
            "authorization_id": authorization_id,
            "operation": operation,
            "model_client_identity": admitted_model_client,
            "activation": activation,
        },
        name=f"gsqs-b0-{run_id}",
        daemon=False,
    )
    worker.start()
    return status_workflow(workflow_root=root, run_id=run_id)


def status_workflow(*, workflow_root: Path, run_id: str) -> dict[str, object]:
    root = _require_root(workflow_root)
    path = root / "runs" / run_id / STATE_NAME
    if path.is_symlink() or not path.is_file():
        raise NotFoundError(SafeDetail.RUN_ID)
    with _root_lock(root):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise NotFoundError(SafeDetail.RUN_ID)
        if payload.get("state") == STATE_RUNNING and not _owner_alive(payload.get("owner_pid")):
            payload["state"] = STATE_INTERRUPTED
            payload["failure_class"] = "WORKER_CRASH"
            payload["updated_at"] = _now()
            payload["completed_at"] = payload["updated_at"]
            _write_state(path.parent, payload)
    return _public_status(payload)


def step_workflow(
    *,
    workflow_root: Path,
    run_id: str,
    submission_token: str | None = None,
    segments: tuple[dict[str, object], ...] | None = None,
    repository_root: Path | None = None,
) -> dict[str, object]:
    """Serve the next client-driven case or accept ChatLLM semantic segments."""

    del repository_root
    root = _require_root(workflow_root)
    run_dir = root / "runs" / run_id
    with _root_lock(root):
        payload = _read_state(run_dir)
        if payload.get("workflow_driver") != DRIVER_CLIENT_DRIVEN:
            raise DeniedError()
        if payload.get("model_client") != MODEL_CLIENT_CHATLLM:
            raise DeniedError()
        if submission_token is None:
            return _serve_client_driven_case(run_dir=run_dir, payload=payload)
        return _accept_client_driven_segments(
            run_dir=run_dir,
            payload=payload,
            submission_token=submission_token,
            segments=segments or (),
        )


def _admit_start_authorization(
    *,
    authorization_id: str,
    ports: WorkflowPorts,
    repository_root: Path,
) -> tuple[str, str, RouteLLMClientActivation | None]:
    if authorization_id == ADMITTED_SYNTHETIC_AUTHORIZATION_ID:
        if ports.model_client is not None and ports.model_client.identity != MODEL_CLIENT_SYNTHETIC:
            raise DeniedError()
        return MODEL_CLIENT_SYNTHETIC, OPERATION_SYNTHETIC, None
    if authorization_id != ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID:
        raise DeniedError()
    if ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS != ("synth-b0-001",):
        raise DeniedError()
    if not ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS:
        raise DeniedError()
    return MODEL_CLIENT_CHATLLM, OPERATION_SYNTHETIC_ROUTELLM, None


def _bind_workflow_client(
    *,
    ports: WorkflowPorts,
    model_client_identity: str,
    activation: RouteLLMClientActivation | None,
) -> B0ModelClient:
    if model_client_identity == MODEL_CLIENT_SYNTHETIC:
        client = ports.model_client or SyntheticB0ModelClient()
        if client.identity != MODEL_CLIENT_SYNTHETIC:
            raise DeniedError()
        return client
    raise DeniedError()


def _execute_run(
    *,
    run_dir: Path,
    repository_root: Path,
    python: str | None,
    ports: WorkflowPorts,
    authorization_id: str,
    operation: str,
    model_client_identity: str,
    activation: RouteLLMClientActivation | None,
) -> dict[str, object]:
    state = _read_state(run_dir)
    campaign_dir = run_dir / "campaign"
    output_dir = run_dir / "output"
    case_count = ports.case_count if ports.case_count is not None else SYNTHETIC_CASE_COUNT
    campaign = build_synthetic_campaign(campaign_dir, case_count=case_count)
    rasters = {
        member.case_id: (campaign.raster_root / f"{member.case_id}.png").read_bytes()
        for member in campaign.census.members
    }
    candidate = load_route_llm_candidate(repository_root / CANDIDATE_RELATIVE)
    identity = composite_model_identity(candidate)
    prompt_id = prompt_config_identity(repository_root)
    config = frozen_incumbent_config(model_identity=identity, root=repository_root)
    authorization = acquisition_from_mapping(
        {
            "schema_version": ACQUISITION_AUTH_SCHEMA,
            "authorization_id": authorization_id,
            "operation": operation,
            "campaign_id": campaign.campaign_id,
            "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
            "repetition": 1,
            "corpus_version": campaign.corpus_version,
            "corpus_manifest_digest": campaign.manifest_digest,
            "combined_identity": campaign.combined_identity,
            "candidate_identity": identity,
            "model_identity": identity,
            "prompt_config_identity": prompt_id,
            "analyzer_name": INCUMBENT_ANALYZER_NAME,
            "analyzer_version": INCUMBENT_ANALYZER_VERSION,
            "model_client": model_client_identity,
            "mcp_evaluation_surface": MCP_EVALUATION_SURFACE_STDIO,
            "mcp_evaluation_binding_mode": MCP_BINDING_OPERATOR_LOCAL_STDIO,
            "mcp_evaluation_evidence_id": f"workflow-{state['run_id']}",
        }
    )
    client = _bind_workflow_client(
        ports=ports,
        model_client_identity=model_client_identity,
        activation=activation,
    )
    auth_path = run_dir / "authorization.json"
    auth_path.write_text(
        json.dumps(_authorization_payload(authorization), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    session: ContentSession
    if ports.session_factory is not None:
        session = ports.session_factory(rasters)
    else:
        evidence_dir = output_dir / "stdio-eval"
        session = StdioEvalSession(
            command=serve_eval_mcp_command(
                python=python or os.environ.get("PYTHON", "python3"),
                authorization=auth_path.resolve(),
                evidence_dir=evidence_dir,
                campaign_fixture=(campaign_dir / "campaign.json").resolve(),
            ),
            cwd=repository_root,
            env=stdio_env(
                raster_root=campaign.raster_root,
                pythonpath=(repository_root / "src", repository_root),
            ),
            evidence_dir=evidence_dir,
        )
    state["state"] = STATE_RUNNING
    state["expected_cases"] = len(campaign.census.members)
    state["campaign_id"] = campaign.campaign_id
    state["owner_pid"] = os.getpid()
    state["updated_at"] = _now()
    _write_state(run_dir, state)
    try:
        result = acquire_repetition(
            authorization=authorization,
            census=campaign.census,
            campaign_id=campaign.campaign_id,
            repetition=1,
            output_dir=output_dir,
            config=config,
            candidate_identity=identity,
            model_client=client,
            session=session,
        )
    except (
        OrchestratorError,
        StdioHostError,
        CaptureWriterError,
        B0ModelClientError,
        AcquisitionError,
        OSError,
    ) as error:
        mapped = STATE_INTERRUPTED
        failure = type(error).__name__
        if isinstance(error, B0ModelClientError):
            failure = error.error_class
        elif isinstance(error, AcquisitionError):
            mapped = STATE_INVALID
            failure = "ACQUISITION"
        elif isinstance(error, CaptureWriterError):
            mapped = STATE_FAILED
            failure = "CAPTURE_WRITE"
        state["state"] = mapped
        state["failure_class"] = failure
        state["updated_at"] = _now()
        state["completed_at"] = state["updated_at"]
        _write_state(run_dir, state)
        return _public_status(state)
    except Exception:
        state["state"] = STATE_FAILED
        state["failure_class"] = "WORKFLOW_EXECUTION"
        state["updated_at"] = _now()
        state["completed_at"] = state["updated_at"]
        _write_state(run_dir, state)
        raise
    finally:
        session.close()
    mapped = _ACQUISITION_TO_WORKFLOW.get(result.state, STATE_FAILED)
    state["state"] = mapped
    state["captured"] = result.captured
    state["missing"] = result.missing
    state["duplicates"] = result.duplicates
    state["updated_at"] = _now()
    if mapped in {STATE_COMPLETE, STATE_FAILED, STATE_INTERRUPTED, STATE_INVALID}:
        state["completed_at"] = state["updated_at"]
    if result.capture_path is not None:
        state["capture_artifact"] = {
            "filename": repetition_filename(1),
            "sha256": sha256(result.capture_path.read_bytes()).hexdigest(),
            "schema_version": "gsqs-analyzer-capture-v1",
        }
    if mapped != STATE_COMPLETE:
        state["failure_class"] = result.state.value
    _write_state(run_dir, state)
    return _public_status(state)


def _authorization_payload(authorization: AcquisitionAuthorization) -> dict[str, object]:
    return {
        "analyzer_name": authorization.analyzer_name,
        "analyzer_version": authorization.analyzer_version,
        "authorization_id": authorization.authorization_id,
        "campaign_class": authorization.campaign_class,
        "campaign_id": authorization.campaign_id,
        "candidate_identity": authorization.candidate_identity,
        "combined_identity": authorization.combined_identity,
        "corpus_manifest_digest": authorization.corpus_manifest_digest,
        "corpus_version": authorization.corpus_version,
        "mcp_evaluation_binding_mode": authorization.mcp_evaluation_binding_mode,
        "mcp_evaluation_evidence_id": authorization.mcp_evaluation_evidence_id,
        "mcp_evaluation_surface": authorization.mcp_evaluation_surface,
        "model_client": authorization.model_client,
        "model_identity": authorization.model_identity,
        "operation": authorization.operation,
        "prompt_config_identity": authorization.prompt_config_identity,
        "repetition": authorization.repetition,
        "schema_version": authorization.schema_version,
    }


def _public_status(payload: Mapping[str, object]) -> dict[str, object]:
    artifact = payload.get("capture_artifact")
    captured = payload.get("captured")
    accepted = payload.get("accepted_captures")
    if not isinstance(accepted, int) or isinstance(accepted, bool):
        accepted = captured
    return {
        "accepted_captures": accepted,
        "automatic_next_repetition": False,
        "campaign_class": payload.get("campaign_class"),
        "campaign_id": payload.get("campaign_id"),
        "capture_artifact": artifact if isinstance(artifact, dict) else None,
        "captured": captured,
        "completed_at": payload.get("completed_at"),
        "current_ordinal": payload.get("current_ordinal"),
        "duplicates": payload.get("duplicates"),
        "expected_cases": payload.get("expected_cases"),
        "failure_class": payload.get("failure_class"),
        "gold": "NOT_ACCESSED",
        "missing": payload.get("missing"),
        "model_client": payload.get("model_client"),
        "repetition": payload.get("repetition"),
        "run_id": payload.get("run_id"),
        "scoring": "NOT_RUN",
        "started_at": payload.get("started_at"),
        "state": payload.get("state"),
        "updated_at": payload.get("updated_at"),
    }


def _prepare_client_driven_run(*, run_dir: Path, repository_root: Path) -> dict[str, object]:
    if ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS != ("synth-b0-001",):
        raise DeniedError()
    if not ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS:
        raise DeniedError()
    campaign_dir = run_dir / "campaign"
    try:
        campaign = build_synthetic_campaign_for_case_ids(
            campaign_dir, ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS
        )
    except ValueError:
        raise DeniedError() from None
    candidate = load_route_llm_candidate(repository_root / CANDIDATE_RELATIVE)
    identity = composite_model_identity(candidate)
    prompt_id = prompt_config_identity(repository_root)
    prompt_text = load_frozen_prompt(repository_root)
    state = _read_state(run_dir)
    state["state"] = STATE_PREPARED
    state["workflow_driver"] = DRIVER_CLIENT_DRIVEN
    state["campaign_id"] = campaign.campaign_id
    state["expected_cases"] = len(campaign.census.members)
    state["accepted_captures"] = 0
    state["captured"] = 0
    state["missing"] = len(campaign.census.members)
    state["duplicates"] = 0
    state["current_ordinal"] = None
    state["prompt_config_identity"] = prompt_id
    state["candidate_identity"] = identity
    state["analyzer_name"] = INCUMBENT_ANALYZER_NAME
    state["analyzer_version"] = INCUMBENT_ANALYZER_VERSION
    state["prompt_text"] = prompt_text
    state["corpus_version"] = campaign.corpus_version
    state["combined_identity"] = campaign.combined_identity
    state["corpus_manifest_digest"] = campaign.manifest_digest
    state["census"] = [
        {
            "case_id": member.case_id,
            "raster_sha256": member.raster_sha256,
            "ordinal": index,
        }
        for index, member in enumerate(campaign.census.members, start=1)
    ]
    state["accepted_documents"] = []
    state["lease"] = None
    state["updated_at"] = _now()
    _write_state(run_dir, state)
    return _public_status(state)


def _serve_client_driven_case(*, run_dir: Path, payload: dict[str, object]) -> dict[str, object]:
    if payload.get("state") == STATE_COMPLETE:
        raise DeniedError()
    census = _census_rows(payload)
    if not census:
        raise DeniedError()
    lease = payload.get("lease")
    if isinstance(lease, dict) and lease.get("consumed") is not True:
        member = _census_row(census, _require_int(lease, "ordinal"))
        token = secrets.token_urlsafe(32)
        payload["lease"] = _lease_record(payload, member, token)
        payload["state"] = STATE_RUNNING
        payload["current_ordinal"] = member["ordinal"]
        _write_state(run_dir, payload)
        return _case_payload(run_dir=run_dir, payload=payload, member=member, token=token)
    accepted = payload.get("accepted_documents")
    accepted_count = len(accepted) if isinstance(accepted, list) else 0
    if accepted_count >= len(census):
        raise DeniedError()
    member = census[accepted_count]
    token = secrets.token_urlsafe(32)
    payload["lease"] = _lease_record(payload, member, token)
    payload["state"] = STATE_RUNNING
    payload["current_ordinal"] = member["ordinal"]
    payload["updated_at"] = _now()
    _write_state(run_dir, payload)
    return _case_payload(run_dir=run_dir, payload=payload, member=member, token=token)


def _accept_client_driven_segments(
    *,
    run_dir: Path,
    payload: dict[str, object],
    submission_token: str,
    segments: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    token_digest = sha256(submission_token.encode()).hexdigest()
    lease = payload.get("lease")
    accepted = payload.get("accepted_documents")
    if not isinstance(accepted, list):
        accepted = []
    census = _census_rows(payload)
    if isinstance(lease, dict) and lease.get("token_digest") == token_digest:
        if lease.get("consumed") is True:
            return _replay_or_conflict(
                payload=payload,
                lease=lease,
                segments=segments,
                accepted=accepted,
            )
        member = _census_row(census, _require_int(lease, "ordinal"))
        document = _stamp_interchange(payload=payload, member=member, segments=segments)
        try:
            parse_interchange(document)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SEGMENTS) from None
        accepted.append(document)
        payload["accepted_documents"] = accepted
        payload["accepted_captures"] = len(accepted)
        payload["captured"] = len(accepted)
        payload["missing"] = max(0, len(census) - len(accepted))
        payload["lease"] = {**lease, "consumed": True, "document": document}
        payload["updated_at"] = _now()
        if len(accepted) >= len(census):
            capture_path = _write_client_driven_capture(run_dir=run_dir, payload=payload)
            payload["state"] = STATE_COMPLETE
            payload["completed_at"] = payload["updated_at"]
            payload["capture_artifact"] = {
                "filename": repetition_filename(_require_int(payload, "repetition")),
                "sha256": sha256(capture_path.read_bytes()).hexdigest(),
                "schema_version": "gsqs-analyzer-capture-v1",
            }
            payload["current_ordinal"] = member["ordinal"]
            _write_state(run_dir, payload)
            status = _public_status(payload)
            status["accepted"] = True
            status["replayed"] = False
            status["ordinal"] = member["ordinal"]
            status["case_id"] = member["case_id"]
            return status
        payload["state"] = STATE_RUNNING
        _write_state(run_dir, payload)
        status = _public_status(payload)
        status["accepted"] = True
        status["replayed"] = False
        status["ordinal"] = member["ordinal"]
        status["case_id"] = member["case_id"]
        return status
    if isinstance(lease, dict) and lease.get("consumed") is True:
        if lease.get("token_digest") != token_digest:
            raise DeniedError()
        return _replay_or_conflict(
            payload=payload,
            lease=lease,
            segments=segments,
            accepted=accepted,
        )
    raise DeniedError()


def _replay_or_conflict(
    *,
    payload: Mapping[str, object],
    lease: Mapping[str, object],
    segments: Sequence[Mapping[str, object]],
    accepted: list[object],
) -> dict[str, object]:
    stored = lease.get("document")
    if not isinstance(stored, dict):
        if accepted:
            last = accepted[-1]
            stored = last if isinstance(last, dict) else None
        else:
            stored = None
    if not isinstance(stored, dict):
        raise DeniedError()
    census = _census_rows(payload)
    member = _census_row(census, _require_int(lease, "ordinal"))
    candidate = _stamp_interchange(payload=payload, member=member, segments=segments)
    if _canonical_bytes(candidate) == _canonical_bytes(stored):
        status = _public_status(payload)
        status["accepted"] = True
        status["replayed"] = True
        status["ordinal"] = member["ordinal"]
        status["case_id"] = member["case_id"]
        return status
    raise ConflictError()


def _stamp_interchange(
    *,
    payload: Mapping[str, object],
    member: Mapping[str, object],
    segments: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    case = AnalyzerCaseInput(
        case_id=str(member["case_id"]),
        corpus_version=str(payload["corpus_version"]),
        raster_sha256=str(member["raster_sha256"]),
        interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
        image_bytes=None,
    )
    stamped_config = FrozenAnalyzerConfig(
        analyzer_name=str(payload["analyzer_name"]),
        analyzer_version=str(payload["analyzer_version"]),
        model_identity=str(payload["candidate_identity"]),
        prompt_config_identity=str(payload["prompt_config_identity"]),
        prompt_text=str(payload["prompt_text"]),
    )
    return assemble_authoritative_interchange(
        case,
        stamped_config,
        {"segments": [dict(item) for item in segments]},
        provenance={"model_client": MODEL_CLIENT_CHATLLM},
    )


def _write_client_driven_capture(*, run_dir: Path, payload: Mapping[str, object]) -> Path:
    accepted = payload.get("accepted_documents")
    if not isinstance(accepted, list):
        raise DeniedError()
    census_rows = _census_rows(payload)
    members = tuple(
        B0CensusMember(
            case_id=str(row["case_id"]),
            raster_sha256=str(row["raster_sha256"]),
            case_digest=str(row["raster_sha256"]),
            file_sha256=str(row["raster_sha256"]),
        )
        for row in census_rows
    )
    census = B0Census(
        corpus_version=str(payload["corpus_version"]),
        manifest_digest=str(payload["corpus_manifest_digest"]),
        combined_identity=str(payload["combined_identity"]),
        partition="SYNTHETIC",
        members=members,
        census_digest=str(payload["corpus_manifest_digest"]),
    )
    binding = CaptureBinding(
        campaign_id=str(payload["campaign_id"]),
        corpus_version=str(payload["corpus_version"]),
        combined_identity=str(payload["combined_identity"]),
        repetition=_require_int(payload, "repetition"),
        candidate_identity=str(payload["candidate_identity"]),
        model_identity=str(payload["candidate_identity"]),
        analyzer_name=str(payload["analyzer_name"]),
        analyzer_version=str(payload["analyzer_version"]),
        prompt_config_identity=str(payload["prompt_config_identity"]),
    )
    documents = tuple(item for item in accepted if isinstance(item, Mapping))
    return write_repetition_capture(
        run_dir / "output",
        binding=binding,
        census=census,
        documents=documents,
    )


def _case_payload(
    *,
    run_dir: Path,
    payload: Mapping[str, object],
    member: Mapping[str, object],
    token: str,
) -> dict[str, object]:
    png = (run_dir / "campaign" / "rasters" / f"{member['case_id']}.png").read_bytes()
    encoded = base64.b64encode(png).decode("ascii")
    status = _public_status(payload)
    status.update(
        {
            "analyzer_name": payload.get("analyzer_name"),
            "analyzer_version": payload.get("analyzer_version"),
            "byte_length": len(png),
            "candidate_identity": payload.get("candidate_identity"),
            "case_id": member["case_id"],
            "content_base64": encoded,
            "content_sha256": member["raster_sha256"],
            "media_type": "image/png",
            "ordinal": member["ordinal"],
            "prompt_config_identity": payload.get("prompt_config_identity"),
            "prompt_text": payload.get("prompt_text"),
            "raster_role": RASTER_ROLE,
            "submission_token": token,
        }
    )
    return status


def _lease_record(
    payload: Mapping[str, object], member: Mapping[str, object], token: str
) -> dict[str, object]:
    return {
        "candidate_identity": payload.get("candidate_identity"),
        "case_id": member["case_id"],
        "consumed": False,
        "ordinal": member["ordinal"],
        "prompt_identity": payload.get("prompt_config_identity"),
        "raster_sha256": member["raster_sha256"],
        "repetition": payload.get("repetition"),
        "run_id": payload.get("run_id"),
        "token_digest": sha256(token.encode()).hexdigest(),
    }


def _census_rows(payload: Mapping[str, object]) -> list[dict[str, object]]:
    raw = payload.get("census")
    if not isinstance(raw, list) or not raw:
        return []
    rows: list[dict[str, object]] = []
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("case_id"), str):
            rows.append(item)
    return rows


def _census_row(census: Sequence[Mapping[str, object]], ordinal: int) -> dict[str, object]:
    for item in census:
        if item.get("ordinal") == ordinal:
            return dict(item)
    raise DeniedError()


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise DeniedError()
    return value


def _canonical_bytes(document: Mapping[str, object]) -> bytes:
    return (json.dumps(dict(document), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_root(root: Path) -> Path:
    if root.is_symlink():
        raise InvalidRequestError(SafeDetail.RUN_ID)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _disclosure_census_token(
    *,
    model_client_identity: str,
    activation: RouteLLMClientActivation | None,
    ports: WorkflowPorts,
) -> str:
    if model_client_identity == MODEL_CLIENT_CHATLLM:
        return "chatllm-routellm:" + ",".join(ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS)
    count = ports.case_count if ports.case_count is not None else SYNTHETIC_CASE_COUNT
    return f"synthetic-fake:{count}"


def _idempotency_digest(
    authorization_id: str, repetition: int, idempotency_key: str, census_token: str
) -> str:
    material = f"{authorization_id}\n{repetition}\n{idempotency_key}\n{census_token}"
    return sha256(material.encode()).hexdigest()


def _lookup_idempotency(root: Path, digest: str) -> dict[str, object] | None:
    index = _read_index(root)
    item = index.get(digest)
    if isinstance(item, dict) and isinstance(item.get("run_id"), str):
        return item
    return None


def _record_idempotency(root: Path, digest: str, run_id: str) -> None:
    index = _read_index(root)
    index[digest] = {"run_id": run_id}
    path = root / INDEX_NAME
    path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_index(root: Path) -> dict[str, object]:
    path = root / INDEX_NAME
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _existing_subject(
    root: Path, *, authorization_id: str, repetition: int, census_token: str
) -> str | None:
    runs = root / "runs"
    if not runs.is_dir():
        return None
    for child in runs.iterdir():
        if not child.is_dir():
            continue
        state_path = child / STATE_NAME
        if not state_path.is_file():
            continue
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        if payload.get("authorization_id") != authorization_id:
            continue
        if payload.get("repetition") != repetition:
            continue
        if payload.get("census_token") != census_token:
            continue
        run_id = payload.get("run_id")
        return str(run_id) if isinstance(run_id, str) else "existing"
    return None


def _read_state(run_dir: Path) -> dict[str, object]:
    path = run_dir / STATE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NotFoundError(SafeDetail.RUN_ID) from None
    if not isinstance(payload, dict):
        raise NotFoundError(SafeDetail.RUN_ID)
    return payload


def _write_state(run_dir: Path, payload: Mapping[str, object]) -> None:
    path = run_dir / STATE_NAME
    tmp = run_dir / f".{STATE_NAME}.tmp"
    tmp.write_text(
        json.dumps(dict(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


@contextmanager
def _root_lock(root: Path) -> Iterator[None]:
    path = root / LOCK_NAME
    path.touch(exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _owner_alive(pid: object) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _now() -> str:
    return format_rfc3339(datetime.now(tz=UTC))


def default_repository_root() -> Path:
    return repo_root()


def bind_synthetic_client() -> B0ModelClient:
    return bind_model_client(MODEL_CLIENT_SYNTHETIC)
