"""Connected-MCP B0 workflow: start, status, idempotency, fail-closed real data."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from my_pa.application.errors import ConflictError, DeniedError, InvalidRequestError
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_REAL,
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_ROUTELLM_HTTP,
    MODEL_CLIENT_SYNTHETIC,
    REAL_HANDWRITING_ACQUISITION_ADMITTED,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import (
    RouteLLMHttpB0ModelClient,
    TimeoutB0ModelClient,
)
from my_pa.application.goodnotes_gsqs_b0_workflow import (
    ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
    ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
    STATE_COMPLETE,
    STATE_INTERRUPTED,
    STATE_PREPARED,
    STATE_RUNNING,
    DiskContentSession,
    WorkflowPorts,
    default_repository_root,
    gsqs_b0_wait_in_process,
    start_workflow,
    status_workflow,
)
from my_pa.application.goodnotes_gsqs_live_b0 import repo_root
from my_pa.infrastructure.gsqs_routellm_transport import RouteLLMHttpResult
from tests.unit.test_gsqs_b0_routellm_activation import load_valid_activation, write_activation
from tests.unit.test_gsqs_b0_routellm_http_client import ORIGIN, SENTINEL_KEY, _success_payload

FAKE_PORTS = WorkflowPorts(
    session_factory=lambda rasters: DiskContentSession(rasters),
    case_count=2,
)


def _start(tmp_path: Path, **overrides: object) -> dict[str, object]:
    params: dict[str, object] = {
        "workflow_root": tmp_path / "workflow",
        "repository_root": default_repository_root(),
        "authorization_id": ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
        "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
        "repetition": 1,
        "idempotency_key": "cmcp-start-0001",
        "ports": FAKE_PORTS,
    }
    params.update(overrides)
    return start_workflow(**params)  # type: ignore[arg-type]


def test_synthetic_start_captures_two_cases_without_gold_or_score(tmp_path: Path) -> None:
    result = _start(tmp_path)
    assert result["state"] == STATE_COMPLETE
    assert result["campaign_class"] == CAMPAIGN_CLASS_SYNTHETIC
    assert result["expected_cases"] == 2
    assert result["captured"] == 2
    assert result["missing"] == 0
    assert result["duplicates"] == 0
    assert result["scoring"] == "NOT_RUN"
    assert result["gold"] == "NOT_ACCESSED"
    assert result["automatic_next_repetition"] is False
    artifact = result["capture_artifact"]
    assert isinstance(artifact, dict)
    assert artifact["filename"] == "repetition-001.json"
    assert artifact["schema_version"] == "gsqs-analyzer-capture-v1"
    status = status_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=str(result["run_id"]),
    )
    assert status["run_id"] == result["run_id"]
    assert status["state"] == STATE_COMPLETE


def test_seventy_three_synthetic_cases_complete(tmp_path: Path) -> None:
    result = _start(
        tmp_path,
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=73,
        ),
    )
    assert result["state"] == STATE_COMPLETE
    assert result["expected_cases"] == 73
    assert result["captured"] == 73
    assert result["missing"] == 0
    assert result["duplicates"] == 0


def test_duplicate_start_reuses_the_existing_run(tmp_path: Path) -> None:
    first = _start(tmp_path)
    second = _start(tmp_path)
    assert second["run_id"] == first["run_id"]
    assert second["state"] == STATE_COMPLETE
    runs = list((tmp_path / "workflow" / "runs").iterdir())
    assert len(runs) == 1


def test_conflicting_idempotency_key_is_rejected(tmp_path: Path) -> None:
    _start(tmp_path, idempotency_key="cmcp-start-0001")
    with pytest.raises(ConflictError):
        _start(tmp_path, idempotency_key="cmcp-start-0002")


def test_real_handwriting_campaign_is_denied(tmp_path: Path) -> None:
    assert REAL_HANDWRITING_ACQUISITION_ADMITTED is False
    with pytest.raises(DeniedError):
        _start(tmp_path, campaign_class=CAMPAIGN_CLASS_REAL)


def test_unknown_authorization_is_denied(tmp_path: Path) -> None:
    with pytest.raises(DeniedError):
        _start(tmp_path, authorization_id="not-admitted")


def test_repetition_two_is_denied(tmp_path: Path) -> None:
    with pytest.raises(DeniedError):
        _start(tmp_path, repetition=2)


def test_unknown_campaign_class_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(InvalidRequestError):
        _start(tmp_path, campaign_class="SOMETHING_ELSE")


def test_model_timeout_is_interrupted_and_preserved(tmp_path: Path) -> None:
    result = _start(
        tmp_path,
        ports=WorkflowPorts(
            model_client=TimeoutB0ModelClient(),
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=2,
        ),
    )
    assert result["state"] == STATE_INTERRUPTED
    assert result["failure_class"] == "TIMEOUT"
    status = status_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=str(result["run_id"]),
    )
    assert status["state"] == STATE_INTERRUPTED


def test_stdio_workflow_acquires_two_synthetic_cases(tmp_path: Path) -> None:
    result = start_workflow(
        workflow_root=tmp_path / "workflow",
        repository_root=repo_root(),
        authorization_id=ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
        campaign_class=CAMPAIGN_CLASS_SYNTHETIC,
        repetition=1,
        idempotency_key="cmcp-stdio-0001",
        python=__import__("sys").executable,
        ports=WorkflowPorts(case_count=2),
    )
    assert result["state"] == STATE_COMPLETE
    assert result["captured"] == 2
    assert result["missing"] == 0


def test_detached_start_returns_before_completion_and_status_reaches_complete(
    tmp_path: Path,
) -> None:
    result = _start(tmp_path, wait=False)
    assert result["state"] in {STATE_PREPARED, STATE_RUNNING, STATE_COMPLETE}
    run_id = str(result["run_id"])
    status = result
    for _ in range(200):
        status = status_workflow(workflow_root=tmp_path / "workflow", run_id=run_id)
        if status["state"] == STATE_COMPLETE:
            break
        time.sleep(0.05)
    assert status["state"] == STATE_COMPLETE
    assert status["captured"] == 2
    assert status["missing"] == 0
    assert status["scoring"] == "NOT_RUN"


def test_dead_owner_pid_marks_running_interrupted(tmp_path: Path) -> None:
    result = _start(tmp_path)
    run_dir = tmp_path / "workflow" / "runs" / str(result["run_id"])
    path = run_dir / "WORKFLOW_STATE.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["state"] = STATE_RUNNING
    payload["owner_pid"] = 2_147_483_647
    payload["completed_at"] = None
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    status = status_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=str(result["run_id"]),
    )
    assert status["state"] == STATE_INTERRUPTED
    assert status["failure_class"] == "WORKER_CRASH"


def _routellm_ports(tmp_path: Path) -> WorkflowPorts:
    activation = load_valid_activation(tmp_path / "activation")

    def poster(
        *,
        origin: str,
        api_key: str,
        body: dict[str, object],
        **_kwargs: object,
    ) -> RouteLLMHttpResult:
        del origin, api_key, body
        return RouteLLMHttpResult(status=200, payload=_success_payload())

    client = RouteLLMHttpB0ModelClient(
        activation=activation,
        origin="https://route.example",
        api_key=SENTINEL_KEY,
        poster=poster,
    )
    return WorkflowPorts(
        model_client=client,
        session_factory=lambda rasters: DiskContentSession(rasters),
        case_count=73,
        activation=activation,
    )


def test_synthetic_b0_commissioning_ignores_routellm_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", "https://route.example")
    result = _start(tmp_path)
    assert result["state"] == STATE_COMPLETE
    assert result["model_client"] == MODEL_CLIENT_SYNTHETIC
    assert result["scoring"] == "NOT_RUN"
    dumped = json.dumps(result)
    assert SENTINEL_KEY not in dumped
    assert "https://route.example" not in dumped


def test_synthetic_routellm_requires_activation_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", raising=False)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", "https://route.example")
    with pytest.raises(DeniedError):
        _start(
            tmp_path,
            authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
        )


def test_synthetic_routellm_wrong_schema_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_activation(tmp_path / "act", schema_version="other")
    monkeypatch.setenv("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", str(path))
    with pytest.raises(DeniedError):
        _start(
            tmp_path,
            authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
            ports=WorkflowPorts(
                session_factory=lambda rasters: DiskContentSession(rasters),
                case_count=2,
            ),
        )


def test_synthetic_routellm_candidate_mismatch_is_denied(tmp_path: Path) -> None:
    activation = load_valid_activation(tmp_path, candidate_identity="other-candidate")
    with pytest.raises(DeniedError):
        _start(
            tmp_path,
            authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
            ports=WorkflowPorts(
                session_factory=lambda rasters: DiskContentSession(rasters),
                case_count=2,
                activation=activation,
            ),
        )


def test_real_campaign_with_synthetic_routellm_auth_is_denied(tmp_path: Path) -> None:
    assert REAL_HANDWRITING_ACQUISITION_ADMITTED is False
    with pytest.raises(DeniedError):
        _start(
            tmp_path,
            authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
            campaign_class=CAMPAIGN_CLASS_REAL,
            ports=_routellm_ports(tmp_path / "ports"),
        )


def test_synthetic_routellm_repetition_two_is_denied(tmp_path: Path) -> None:
    with pytest.raises(DeniedError):
        _start(
            tmp_path,
            authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
            repetition=2,
            ports=_routellm_ports(tmp_path / "ports"),
        )


def test_synthetic_routellm_workflow_completes_without_gold_or_score(
    tmp_path: Path,
) -> None:
    result = _start(
        tmp_path,
        authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
        ports=_routellm_ports(tmp_path / "ports"),
        idempotency_key="cmcp-routellm-0001",
    )
    assert result["state"] == STATE_COMPLETE
    assert result["model_client"] == MODEL_CLIENT_ROUTELLM_HTTP
    assert result["expected_cases"] == 1
    assert result["captured"] == 1
    assert result["missing"] == 0
    assert result["scoring"] == "NOT_RUN"
    assert result["gold"] == "NOT_ACCESSED"
    dumped = json.dumps(result)
    assert SENTINEL_KEY not in dumped
    assert "https://route.example" not in dumped
    assert "MY_PA_ROUTELLM" not in dumped
    status = status_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=str(result["run_id"]),
    )
    assert status["model_client"] == MODEL_CLIENT_ROUTELLM_HTTP
    assert status["scoring"] == "NOT_RUN"


def test_poster_only_ports_do_not_force_in_process_wait() -> None:
    assert gsqs_b0_wait_in_process(None) is False
    assert gsqs_b0_wait_in_process(WorkflowPorts(poster=lambda **_k: None)) is False
    assert gsqs_b0_wait_in_process(FAKE_PORTS) is True


def test_routellm_workflow_uses_injected_poster_without_prebuilt_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation = load_valid_activation(tmp_path / "activation")
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    calls = {"n": 0}

    def poster(*, origin: str, api_key: str, body: object) -> RouteLLMHttpResult:
        del origin, api_key, body
        calls["n"] += 1
        return RouteLLMHttpResult(status=200, payload=_success_payload())

    result = _start(
        tmp_path,
        authorization_id=ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=73,
            activation=activation,
            poster=poster,
        ),
    )
    assert result["state"] == STATE_COMPLETE
    assert result["model_client"] == MODEL_CLIENT_ROUTELLM_HTTP
    assert result["captured"] == 1
    assert calls["n"] == 1
    assert result["scoring"] == "NOT_RUN"
