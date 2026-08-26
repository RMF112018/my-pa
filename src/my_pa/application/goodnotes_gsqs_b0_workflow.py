"""Connected-MCP B0 prediction-acquisition workflow. No gold, no scoring.

ChatLLM may start and observe a repetition through production MCP tools. This
module owns durable workflow state and reuses `acquire_repetition`. It does not
replace the stdio analyzer plane. Real handwriting remains fail-closed.
"""

from __future__ import annotations

import fcntl
import json
import os
import threading
from collections.abc import Callable, Iterator, Mapping
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
    MODEL_CLIENT_SYNTHETIC,
    OPERATION_SYNTHETIC,
    AcquisitionAuthorization,
    AcquisitionError,
    acquisition_from_mapping,
)
from my_pa.application.goodnotes_gsqs_b0_capture import CaptureWriterError, repetition_filename
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
from my_pa.application.goodnotes_gsqs_b0_stdio_session import (
    StdioEvalSession,
    StdioHostError,
    serve_eval_mcp_command,
    stdio_env,
)
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import (
    SYNTHETIC_CAMPAIGN_ID,
    build_synthetic_campaign,
)
from my_pa.application.goodnotes_gsqs_harness import (
    INCUMBENT_ANALYZER_NAME,
    INCUMBENT_ANALYZER_VERSION,
)
from my_pa.application.goodnotes_gsqs_live_b0 import (
    frozen_incumbent_config,
    prompt_config_identity,
    repo_root,
)
from my_pa.application.goodnotes_gsqs_routellm_candidate import (
    composite_model_identity,
    load_route_llm_candidate,
)
from my_pa.domain.common.time import format_rfc3339

WORKFLOW_SCHEMA = "gsqs-b0-workflow-v1"
WORKFLOW_ROOT_ENV = "MY_PA_GSQS_B0_WORKFLOW_ROOT"
ADMITTED_SYNTHETIC_AUTHORIZATION_ID = "synthetic-b0-commissioning"
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
    """Optional test seams. Production leaves every field defaulted."""

    model_client: B0ModelClient | None = None
    session_factory: ContentSessionFactory | None = None
    case_count: int | None = None


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
    if authorization_id != ADMITTED_SYNTHETIC_AUTHORIZATION_ID:
        raise DeniedError()
    if repetition != 1:
        raise DeniedError()
    root = _require_root(workflow_root)
    key = _idempotency_digest(authorization_id, repetition, idempotency_key)
    reuse_id: str | None = None
    run_dir: Path | None = None
    run_id = ""
    with _root_lock(root):
        existing = _lookup_idempotency(root, key)
        if existing is not None:
            reuse_id = str(existing["run_id"])
        else:
            conflict = _existing_subject(
                root, authorization_id=authorization_id, repetition=repetition
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
                    "model_client": MODEL_CLIENT_SYNTHETIC,
                },
            )
            _record_idempotency(root, key, run_id)
    if reuse_id is not None:
        return status_workflow(workflow_root=root, run_id=reuse_id)
    if run_dir is None:
        raise InvalidRequestError(SafeDetail.RUN_ID)
    if wait:
        return _execute_run(
            run_dir=run_dir,
            repository_root=repository_root,
            python=python,
            ports=ports,
        )
    worker = threading.Thread(
        target=_execute_run,
        kwargs={
            "run_dir": run_dir,
            "repository_root": repository_root,
            "python": python,
            "ports": ports,
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


def _execute_run(
    *,
    run_dir: Path,
    repository_root: Path,
    python: str | None,
    ports: WorkflowPorts,
) -> dict[str, object]:
    state = _read_state(run_dir)
    campaign_dir = run_dir / "campaign"
    output_dir = run_dir / "output"
    case_count = ports.case_count if ports.case_count is not None else 73
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
            "authorization_id": ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
            "operation": OPERATION_SYNTHETIC,
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
            "model_client": MODEL_CLIENT_SYNTHETIC,
            "mcp_evaluation_surface": MCP_EVALUATION_SURFACE_STDIO,
            "mcp_evaluation_binding_mode": MCP_BINDING_OPERATOR_LOCAL_STDIO,
            "mcp_evaluation_evidence_id": f"workflow-{state['run_id']}",
        }
    )
    client = ports.model_client or SyntheticB0ModelClient()
    if client.identity != MODEL_CLIENT_SYNTHETIC:
        raise DeniedError()
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
    return {
        "automatic_next_repetition": False,
        "campaign_class": payload.get("campaign_class"),
        "campaign_id": payload.get("campaign_id"),
        "capture_artifact": artifact if isinstance(artifact, dict) else None,
        "captured": payload.get("captured"),
        "completed_at": payload.get("completed_at"),
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


def _require_root(root: Path) -> Path:
    if root.is_symlink():
        raise InvalidRequestError(SafeDetail.RUN_ID)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _idempotency_digest(authorization_id: str, repetition: int, idempotency_key: str) -> str:
    material = f"{authorization_id}\n{repetition}\n{idempotency_key}"
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


def _existing_subject(root: Path, *, authorization_id: str, repetition: int) -> str | None:
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
        run_id = payload.get("run_id")
        return str(run_id) if isinstance(run_id, str) else "existing"
    return None


def _read_state(run_dir: Path) -> dict[str, object]:
    payload = json.loads((run_dir / STATE_NAME).read_text(encoding="utf-8"))
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
