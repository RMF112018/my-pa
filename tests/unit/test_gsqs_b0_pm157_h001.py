"""PM-157-H-001: production-safe one-case disclosure bound to ChatLLM.

The bound is which synthetic case ChatLLM may see (`synth-b0-001` only), not a
NAS RouteLLM HTTP POST count. Client-driven GSQS never calls the HTTP poster.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from my_pa.application.commands import StartGsqsB0
from my_pa.application.errors import DeniedError
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_REAL,
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_CHATLLM,
    MODEL_CLIENT_SYNTHETIC,
    REAL_HANDWRITING_ACQUISITION_ADMITTED,
)
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import (
    ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS,
    SYNTHETIC_CASE_COUNT,
)
from my_pa.application.goodnotes_gsqs_b0_workflow import (
    ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
    ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
    STATE_COMPLETE,
    STATE_PREPARED,
    DiskContentSession,
    WorkflowPorts,
    gsqs_b0_wait_in_process,
    start_workflow,
    status_workflow,
    step_workflow,
)
from my_pa.application.goodnotes_gsqs_live_b0 import repo_root
from my_pa.infrastructure.gsqs_routellm_transport import IMAGE_POST_RETRY_MAX, RouteLLMHttpResult

SEGMENT = {
    "candidate_tags": [],
    "geometry": {"height": 0.1, "width": 0.3, "x_min": 0.1, "y_min": 0.2},
    "kind": "NOTE_UNIT",
    "primary_class": "GENERAL",
    "ranked_candidates": [],
    "transcription": "synthetic synth-b0-001",
    "transcription_status": "CLEAR",
}


def _count_poster() -> tuple[dict[str, int], Callable[..., RouteLLMHttpResult]]:
    calls = {"n": 0}

    def poster(*, origin: str, api_key: str, body: object) -> RouteLLMHttpResult:
        del origin, api_key, body
        calls["n"] += 1
        raise AssertionError("NAS RouteLLM HTTP must not be called")

    return calls, poster


def _start_client(
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
        "ports": ports,
        "wait": wait,
    }
    params.update(overrides)
    return start_workflow(**params)  # type: ignore[arg-type]


def _complete_one_case(tmp_path: Path, run_id: str) -> dict[str, object]:
    served = step_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=run_id,
        repository_root=repo_root(),
    )
    assert served["case_id"] == "synth-b0-001"
    return step_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=run_id,
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
        repository_root=repo_root(),
    )


def test_pm157_h001_case_a_start_does_not_load_activation_or_call_poster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", raising=False)
    calls, poster = _count_poster()
    result = _start_client(tmp_path, ports=WorkflowPorts(poster=poster))
    assert result["state"] == STATE_PREPARED
    assert result["model_client"] == MODEL_CLIENT_CHATLLM
    assert result["expected_cases"] == 1
    assert calls["n"] == 0


def test_pm157_h001_case_b_one_eligible_case_disclosed_to_chatllm(
    tmp_path: Path,
) -> None:
    calls, poster = _count_poster()
    ports = WorkflowPorts(poster=poster)
    assert ports.case_count is None
    assert gsqs_b0_wait_in_process(ports) is False
    assert IMAGE_POST_RETRY_MAX == 0
    result = _start_client(tmp_path, ports=ports, wait=False)
    assert result["state"] == STATE_PREPARED
    run_id = str(result["run_id"])
    done = _complete_one_case(tmp_path, run_id)
    assert done["state"] == STATE_COMPLETE
    assert done["expected_cases"] == 1
    assert done["captured"] == 1
    assert done["missing"] == 0
    assert done["duplicates"] == 0
    assert done["model_client"] == MODEL_CLIENT_CHATLLM
    assert calls["n"] == 0
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
    with pytest.raises(DeniedError):
        step_workflow(
            workflow_root=tmp_path / "workflow",
            run_id=run_id,
            repository_root=repo_root(),
        )


def test_pm157_h001_case_count_seam_cannot_expand_client_driven_census(
    tmp_path: Path,
) -> None:
    calls, poster = _count_poster()
    result = _start_client(
        tmp_path,
        ports=WorkflowPorts(case_count=SYNTHETIC_CASE_COUNT, poster=poster),
    )
    assert result["expected_cases"] == 1
    run_id = str(result["run_id"])
    served = step_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=run_id,
        repository_root=repo_root(),
    )
    assert served["case_id"] == "synth-b0-001"
    assert calls["n"] == 0


def test_pm157_h001_case_c_real_expansion_denied(tmp_path: Path) -> None:
    calls, poster = _count_poster()
    assert REAL_HANDWRITING_ACQUISITION_ADMITTED is False
    with pytest.raises(DeniedError):
        _start_client(
            tmp_path / "real-campaign",
            ports=WorkflowPorts(poster=poster),
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


def test_pm157_h001_idempotency_distinguishes_fake_and_client_driven_census(
    tmp_path: Path,
) -> None:
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
    calls, poster = _count_poster()
    client = _start_client(
        tmp_path,
        ports=WorkflowPorts(poster=poster),
        idempotency_key="shared-key",
    )
    assert fake["run_id"] != client["run_id"]
    assert fake["expected_cases"] == 73
    assert client["expected_cases"] == 1
    assert client["model_client"] == MODEL_CLIENT_CHATLLM
    assert calls["n"] == 0


def test_pm157_h001_activation_env_is_not_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("MY_PA_GSQS_B0_ROUTELLM_ACTIVATION", raising=False)
    calls, poster = _count_poster()
    result = _start_client(tmp_path, ports=WorkflowPorts(poster=poster))
    assert result["state"] == STATE_PREPARED
    assert calls["n"] == 0
    status = status_workflow(workflow_root=tmp_path / "workflow", run_id=str(result["run_id"]))
    assert status["expected_cases"] == 1


def test_pm157_h001_public_start_schema_has_no_census_control() -> None:
    fields = StartGsqsB0.__dataclass_fields__
    assert "case_count" not in fields
    assert "eligible_case_ids" not in fields
    assert "model_client" not in fields
    assert "activation" not in fields
