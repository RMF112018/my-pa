"""PM-157-H-001: production-safe one-case RouteLLM external disclosure bound."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from my_pa.application.commands import StartGsqsB0
from my_pa.application.errors import DeniedError
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_REAL,
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_ROUTELLM_HTTP,
    MODEL_CLIENT_SYNTHETIC,
    REAL_HANDWRITING_ACQUISITION_ADMITTED,
)
from my_pa.application.goodnotes_gsqs_b0_routellm_activation import RouteLLMActivationError
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import (
    ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS,
    SYNTHETIC_CASE_COUNT,
)
from my_pa.application.goodnotes_gsqs_b0_workflow import (
    ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
    ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
    STATE_COMPLETE,
    DiskContentSession,
    WorkflowPorts,
    gsqs_b0_wait_in_process,
    start_workflow,
    status_workflow,
)
from my_pa.application.goodnotes_gsqs_live_b0 import repo_root
from my_pa.infrastructure.gsqs_routellm_transport import IMAGE_POST_RETRY_MAX, RouteLLMHttpResult
from tests.unit.test_gsqs_b0_routellm_activation import (
    activation_payload,
    load_valid_activation,
    write_activation,
)
from tests.unit.test_gsqs_b0_routellm_http_client import ORIGIN, SENTINEL_KEY, _success_payload


def _count_poster() -> tuple[dict[str, int], Callable[..., RouteLLMHttpResult]]:
    calls = {"n": 0}

    def poster(*, origin: str, api_key: str, body: object) -> RouteLLMHttpResult:
        del origin, api_key, body
        calls["n"] += 1
        return RouteLLMHttpResult(status=200, payload=_success_payload("synth-b0-001"))

    return calls, poster


def _start_routellm(
    tmp_path: Path,
    *,
    ports: WorkflowPorts,
    wait: bool = True,
    **overrides: object,
) -> dict[str, object]:
    params: dict[str, object] = {
        "workflow_root": tmp_path / "workflow",
        "repository_root": repo_root(),
        "authorization_id": ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
        "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
        "repetition": 1,
        "idempotency_key": "pm157-h001-0001",
        "python": sys.executable,
        "ports": ports,
        "wait": wait,
    }
    params.update(overrides)
    return start_workflow(**params)  # type: ignore[arg-type]


def test_pm157_h001_case_a_missing_bound_refuses_before_poster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = activation_payload()
    del payload["eligible_case_ids"]
    path = tmp_path / "activation.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", str(path))
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    calls, poster = _count_poster()
    with pytest.raises(DeniedError):
        _start_routellm(
            tmp_path,
            ports=WorkflowPorts(
                session_factory=lambda rasters: DiskContentSession(rasters),
                poster=poster,
            ),
        )
    assert calls["n"] == 0


def test_pm157_h001_case_b_one_eligible_async_production_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation = load_valid_activation(tmp_path / "activation")
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    calls, poster = _count_poster()
    ports = WorkflowPorts(poster=poster, activation=activation)
    assert ports.case_count is None
    assert gsqs_b0_wait_in_process(ports) is False
    assert IMAGE_POST_RETRY_MAX == 0
    result = _start_routellm(tmp_path, ports=ports, wait=False)
    assert result["state"] in {"PREPARED", "RUNNING", "COMPLETE"}
    run_id = str(result["run_id"])
    status = result
    for _ in range(400):
        status = status_workflow(workflow_root=tmp_path / "workflow", run_id=run_id)
        if status["state"] == STATE_COMPLETE:
            break
        time.sleep(0.05)
    assert status["state"] == STATE_COMPLETE
    assert status["expected_cases"] == 1
    assert status["captured"] == 1
    assert status["missing"] == 0
    assert status["duplicates"] == 0
    assert status["model_client"] == MODEL_CLIENT_ROUTELLM_HTTP
    assert calls["n"] == 1
    campaign = json.loads(
        (tmp_path / "workflow" / "runs" / run_id / "campaign" / "campaign.json").read_text(
            encoding="utf-8"
        )
    )
    members = campaign["members"]
    assert [item["case_id"] for item in members] == list(ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS)
    capture = json.loads(
        (tmp_path / "workflow" / "runs" / run_id / "output" / "repetition-001.json").read_text(
            encoding="utf-8"
        )
    )
    assert capture["schema_version"] == "gsqs-analyzer-capture-v1"
    assert len(capture["documents"]) == 1
    assert capture["documents"][0]["case_id"] == "synth-b0-001"
    assert (
        tmp_path / "workflow" / "runs" / run_id / "output" / "repetition-002.json"
    ).exists() is False


def test_pm157_h001_case_count_seam_cannot_expand_routellm_census(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activation = load_valid_activation(tmp_path / "activation")
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    calls, poster = _count_poster()
    result = _start_routellm(
        tmp_path,
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=SYNTHETIC_CASE_COUNT,
            activation=activation,
            poster=poster,
        ),
    )
    assert result["expected_cases"] == 1
    assert result["captured"] == 1
    assert calls["n"] == 1


def test_pm157_h001_case_c_multi_case_and_real_expansion_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, poster = _count_poster()
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    two = load_valid_activation(
        tmp_path / "two", eligible_case_ids=["synth-b0-001", "synth-b0-002"]
    )
    with pytest.raises(DeniedError):
        _start_routellm(tmp_path / "two-run", ports=WorkflowPorts(poster=poster, activation=two))
    seventy_three = [f"synth-b0-{ordinal:03d}" for ordinal in range(1, 74)]
    all_cases = load_valid_activation(tmp_path / "all", eligible_case_ids=seventy_three)
    with pytest.raises(DeniedError):
        _start_routellm(
            tmp_path / "all-run", ports=WorkflowPorts(poster=poster, activation=all_cases)
        )
    unknown = load_valid_activation(tmp_path / "unknown", eligible_case_ids=["synth-b0-999"])
    with pytest.raises(DeniedError):
        _start_routellm(
            tmp_path / "unknown-run", ports=WorkflowPorts(poster=poster, activation=unknown)
        )
    with pytest.raises(RouteLLMActivationError, match="not synthetic"):
        load_valid_activation(tmp_path / "unknown-token", eligible_case_ids=["synth-unknown"])
    with pytest.raises(RouteLLMActivationError, match="not synthetic"):
        load_valid_activation(tmp_path / "wildcard", eligible_case_ids=["*"])
    with pytest.raises(RouteLLMActivationError, match="not synthetic"):
        load_valid_activation(tmp_path / "real-id", eligible_case_ids=["gsqs-hw-001"])
    assert REAL_HANDWRITING_ACQUISITION_ADMITTED is False
    admitted = load_valid_activation(tmp_path / "admitted")
    with pytest.raises(DeniedError):
        _start_routellm(
            tmp_path / "real-campaign",
            ports=WorkflowPorts(poster=poster, activation=admitted),
            campaign_class=CAMPAIGN_CLASS_REAL,
        )
    assert calls["n"] == 0


def test_pm157_h001_synthetic_fake_path_still_uses_seventy_three(tmp_path: Path) -> None:
    calls, poster = _count_poster()
    result = start_workflow(
        workflow_root=tmp_path / "workflow",
        repository_root=repo_root(),
        authorization_id=ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
        campaign_class=CAMPAIGN_CLASS_SYNTHETIC,
        repetition=1,
        idempotency_key="pm157-h001-fake-73",
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=SYNTHETIC_CASE_COUNT,
            poster=poster,
        ),
    )
    assert result["state"] == STATE_COMPLETE
    assert result["model_client"] == MODEL_CLIENT_SYNTHETIC
    assert result["expected_cases"] == 73
    assert result["captured"] == 73
    assert calls["n"] == 0
    assert result["scoring"] == "NOT_RUN"
    assert result["gold"] == "NOT_ACCESSED"
    assert result["automatic_next_repetition"] is False


def test_pm157_h001_idempotency_distinguishes_fake_and_routellm_census(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    fake = start_workflow(
        workflow_root=tmp_path / "workflow",
        repository_root=repo_root(),
        authorization_id=ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
        campaign_class=CAMPAIGN_CLASS_SYNTHETIC,
        repetition=1,
        idempotency_key="shared-key",
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=SYNTHETIC_CASE_COUNT,
        ),
    )
    activation = load_valid_activation(tmp_path / "activation")
    calls, poster = _count_poster()
    routellm = _start_routellm(
        tmp_path,
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            activation=activation,
            poster=poster,
        ),
        idempotency_key="shared-key",
    )
    assert fake["run_id"] != routellm["run_id"]
    assert fake["expected_cases"] == 73
    assert routellm["expected_cases"] == 1
    assert calls["n"] == 1


def test_pm157_h001_missing_bound_file_via_env_has_zero_posts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_activation(tmp_path / "act")
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["eligible_case_ids"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", str(path))
    monkeypatch.setenv("MY_PA_ROUTELLM_BASE_URL", ORIGIN)
    monkeypatch.setenv("MY_PA_ROUTELLM_API_KEY", SENTINEL_KEY)
    calls, poster = _count_poster()
    with pytest.raises(DeniedError):
        _start_routellm(tmp_path, ports=WorkflowPorts(poster=poster))
    assert calls["n"] == 0


def test_pm157_h001_public_start_schema_has_no_census_control() -> None:
    fields = StartGsqsB0.__dataclass_fields__
    assert "case_count" not in fields
    assert "eligible_case_ids" not in fields
    assert "model_client" not in fields
    assert "activation" not in fields
