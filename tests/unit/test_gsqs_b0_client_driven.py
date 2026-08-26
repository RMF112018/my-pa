"""ChatLLM-client-driven GSQS B0: gsqs.start / gsqs.step / gsqs.status.

No live ChatLLM, RouteLLM, gold, or scoring. Poster sentinel stays at zero.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from mcp.types import ImageContent

from my_pa.adapters.mcp.server import _image_from_result
from my_pa.application.commands import StepGsqsB0
from my_pa.application.errors import ConflictError, DeniedError
from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    CAMPAIGN_CLASS_REAL,
    CAMPAIGN_CLASS_SYNTHETIC,
    MODEL_CLIENT_CHATLLM,
    MODEL_CLIENT_SYNTHETIC,
)
from my_pa.application.goodnotes_gsqs_b0_synthetic_campaign import (
    ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS,
)
from my_pa.application.goodnotes_gsqs_b0_workflow import (
    ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
    ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
    RASTER_ROLE,
    STATE_COMPLETE,
    STATE_PREPARED,
    STATE_RUNNING,
    DiskContentSession,
    WorkflowPorts,
    start_workflow,
    status_workflow,
    step_workflow,
)
from my_pa.application.goodnotes_gsqs_live_b0 import repo_root
from my_pa.infrastructure.gsqs_routellm_transport import RouteLLMHttpResult

PROMPT_SHA = "a43f9286d298221eac8eac68964369be9a9c12943e719bcbf2f893eeac8d3dae"
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
    nas_routellm_http_call_count = {"n": 0}

    def poster(*, origin: str, api_key: str, body: object) -> RouteLLMHttpResult:
        del origin, api_key, body
        nas_routellm_http_call_count["n"] += 1
        raise AssertionError("NAS RouteLLM HTTP must not be called")

    return nas_routellm_http_call_count, poster


def _start_client(
    tmp_path: Path,
    *,
    ports: WorkflowPorts | None = None,
    **overrides: object,
) -> tuple[dict[str, object], dict[str, int]]:
    calls, poster = _count_poster()
    params: dict[str, object] = {
        "workflow_root": tmp_path / "workflow",
        "repository_root": repo_root(),
        "authorization_id": ADMITTED_SYNTHETIC_ROUTELLM_AUTHORIZATION_ID,
        "campaign_class": CAMPAIGN_CLASS_SYNTHETIC,
        "repetition": 1,
        "idempotency_key": "client-driven-0001",
        "ports": ports or WorkflowPorts(poster=poster),
        "wait": True,
    }
    params.update(overrides)
    return start_workflow(**params), calls  # type: ignore[arg-type]


def _step(
    tmp_path: Path,
    run_id: str,
    *,
    submission_token: str | None = None,
    segments: tuple[dict[str, object], ...] | None = None,
) -> dict[str, object]:
    return step_workflow(
        workflow_root=tmp_path / "workflow",
        run_id=run_id,
        submission_token=submission_token,
        segments=segments,
        repository_root=repo_root(),
    )


def test_a_start_is_prepared_without_provider_or_thread(tmp_path: Path) -> None:
    before = {thread.name for thread in threading.enumerate()}
    result, calls = _start_client(tmp_path)
    after = {thread.name for thread in threading.enumerate()}
    assert result["state"] == STATE_PREPARED
    assert result["model_client"] == MODEL_CLIENT_CHATLLM
    assert result["expected_cases"] == 1
    assert result["accepted_captures"] == 0
    assert result["gold"] == "NOT_ACCESSED"
    assert result["scoring"] == "NOT_RUN"
    assert result["automatic_next_repetition"] is False
    assert not any(name.startswith("gsqs-b0-") for name in after - before)
    assert calls["n"] == 0


def test_b_initial_step_serves_imagecontent_fields_and_bound_prompt(
    tmp_path: Path,
) -> None:
    started, calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    assert served["case_id"] == "synth-b0-001"
    assert served["raster_role"] == RASTER_ROLE
    assert served["media_type"] == "image/png"
    assert isinstance(served["content_base64"], str) and served["content_base64"]
    assert isinstance(served["content_sha256"], str) and len(served["content_sha256"]) == 64
    assert served["byte_length"] == len(
        __import__("base64").b64decode(str(served["content_base64"]))
    )
    assert len(str(served["content_base64"])) == ((int(served["byte_length"]) + 2) // 3) * 4
    assert served["prompt_config_identity"] == PROMPT_SHA
    assert isinstance(served["prompt_text"], str) and served["prompt_text"]
    token = served["submission_token"]
    assert isinstance(token, str) and token
    assert "token_digest" not in served
    assert served["analyzer_name"] == "chatllm-goodnotes-semantic"
    assert served["analyzer_version"] == "sit-1.0"
    assert list(ROUTELLM_EXTERNAL_ELIGIBLE_CASE_IDS) == ["synth-b0-001"]
    projected = _image_from_result(served)
    assert isinstance(projected, ImageContent)
    assert projected.mime_type == "image/png"
    assert projected.data == served["content_base64"]
    assert calls["n"] == 0


def test_c_submit_completes_with_one_capture(tmp_path: Path) -> None:
    started, calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    done = _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
    )
    assert done["state"] == STATE_COMPLETE
    assert done["accepted_captures"] == 1
    assert done["captured"] == 1
    assert done["accepted"] is True
    artifact = done["capture_artifact"]
    assert isinstance(artifact, dict)
    assert artifact["schema_version"] == "gsqs-analyzer-capture-v1"
    capture = json.loads(
        (
            tmp_path
            / "workflow"
            / "runs"
            / str(started["run_id"])
            / "output"
            / "repetition-001.json"
        ).read_text(encoding="utf-8")
    )
    assert len(capture["documents"]) == 1
    assert capture["documents"][0]["case_id"] == "synth-b0-001"
    assert capture["documents"][0]["prompt_config_identity"] == PROMPT_SHA
    assert calls["n"] == 0


def test_d_identical_replay_is_idempotent_and_conflict_is_refused(tmp_path: Path) -> None:
    started, _calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    token = str(served["submission_token"])
    first = _step(tmp_path, str(started["run_id"]), submission_token=token, segments=(SEGMENT,))
    replay = _step(tmp_path, str(started["run_id"]), submission_token=token, segments=(SEGMENT,))
    assert replay["replayed"] is True
    assert replay["accepted"] is True
    conflicting = {**SEGMENT, "transcription": "different text"}
    with pytest.raises(ConflictError):
        _step(
            tmp_path,
            str(started["run_id"]),
            submission_token=token,
            segments=(conflicting,),
        )
    assert first["state"] == STATE_COMPLETE


def test_e_skip_future_and_wrong_token_are_denied(tmp_path: Path) -> None:
    started, _calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    with pytest.raises(DeniedError):
        _step(
            tmp_path,
            str(started["run_id"]),
            submission_token="not-the-lease-token",  # noqa: S106
            segments=(SEGMENT,),
        )
    done = _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
    )
    assert done["state"] == STATE_COMPLETE
    with pytest.raises(DeniedError):
        _step(tmp_path, str(started["run_id"]))
    with pytest.raises(DeniedError):
        _step(
            tmp_path,
            str(started["run_id"]),
            submission_token="future-or-skip-token",  # noqa: S106
            segments=(SEGMENT,),
        )


def test_f_one_case_campaign_completes(tmp_path: Path) -> None:
    started, calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    done = _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
    )
    assert done["expected_cases"] == 1
    assert done["accepted_captures"] == 1
    assert done["missing"] == 0
    assert "content_base64" not in done
    assert "submission_token" not in done
    assert calls["n"] == 0


def test_g_second_synthetic_case_is_impossible(tmp_path: Path) -> None:
    started, _calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    assert served["case_id"] == "synth-b0-001"
    spoofed = {**SEGMENT}
    done = _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(spoofed,),
    )
    capture = json.loads(
        (
            tmp_path
            / "workflow"
            / "runs"
            / str(started["run_id"])
            / "output"
            / "repetition-001.json"
        ).read_text(encoding="utf-8")
    )
    assert [item["case_id"] for item in capture["documents"]] == ["synth-b0-001"]
    assert done["state"] == STATE_COMPLETE
    with pytest.raises(DeniedError):
        _step(tmp_path, str(started["run_id"]))


def test_h_real_campaign_is_denied(tmp_path: Path) -> None:
    with pytest.raises(DeniedError):
        _start_client(tmp_path, campaign_class=CAMPAIGN_CLASS_REAL)


def test_i_synthetic_fake_path_still_completes(tmp_path: Path) -> None:
    calls, poster = _count_poster()
    result = start_workflow(
        workflow_root=tmp_path / "workflow",
        repository_root=repo_root(),
        authorization_id=ADMITTED_SYNTHETIC_AUTHORIZATION_ID,
        campaign_class=CAMPAIGN_CLASS_SYNTHETIC,
        repetition=1,
        idempotency_key="client-driven-fake",
        ports=WorkflowPorts(
            session_factory=lambda rasters: DiskContentSession(rasters),
            case_count=2,
            poster=poster,
        ),
    )
    assert result["state"] == STATE_COMPLETE
    assert result["model_client"] == MODEL_CLIENT_SYNTHETIC
    assert result["expected_cases"] == 2
    assert result["captured"] == 2
    assert calls["n"] == 0


def test_j_status_states_cover_prepared_running_and_complete(tmp_path: Path) -> None:
    started, _calls = _start_client(tmp_path)
    prepared = status_workflow(workflow_root=tmp_path / "workflow", run_id=str(started["run_id"]))
    assert prepared["state"] == STATE_PREPARED
    assert prepared["current_ordinal"] is None
    assert prepared["accepted_captures"] == 0
    assert prepared["gold"] == "NOT_ACCESSED"
    assert prepared["scoring"] == "NOT_RUN"
    served = _step(tmp_path, str(started["run_id"]))
    running = status_workflow(workflow_root=tmp_path / "workflow", run_id=str(started["run_id"]))
    assert running["state"] == STATE_RUNNING
    assert running["current_ordinal"] == 1
    assert "content_base64" not in running
    assert "submission_token" not in running
    _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
    )
    complete = status_workflow(workflow_root=tmp_path / "workflow", run_id=str(started["run_id"]))
    assert complete["state"] == STATE_COMPLETE
    assert complete["accepted_captures"] == 1
    assert isinstance(complete["capture_artifact"], dict)


def test_k_server_restart_does_not_interrupt_a_client_driven_run(
    tmp_path: Path,
) -> None:
    started, _calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    state_path = tmp_path / "workflow" / "runs" / str(started["run_id"]) / "WORKFLOW_STATE.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    payload["owner_pid"] = 1_000_000_000
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    observed = status_workflow(workflow_root=tmp_path / "workflow", run_id=str(started["run_id"]))
    assert observed["state"] == STATE_RUNNING
    assert observed["failure_class"] is None
    done = _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
    )
    assert done["state"] == STATE_COMPLETE


def test_k_resume_re_serves_the_pending_case(tmp_path: Path) -> None:
    started, _calls = _start_client(tmp_path)
    first = _step(tmp_path, str(started["run_id"]))
    second = _step(tmp_path, str(started["run_id"]))
    assert first["case_id"] == second["case_id"] == "synth-b0-001"
    assert first["ordinal"] == second["ordinal"] == 1
    with pytest.raises(DeniedError):
        _step(
            tmp_path,
            str(started["run_id"]),
            submission_token=str(first["submission_token"]),
            segments=(SEGMENT,),
        )
    done = _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(second["submission_token"]),
        segments=(SEGMENT,),
    )
    assert done["state"] == STATE_COMPLETE


def test_l_poster_sentinel_is_never_called(tmp_path: Path) -> None:
    started, calls = _start_client(tmp_path)
    served = _step(tmp_path, str(started["run_id"]))
    _step(
        tmp_path,
        str(started["run_id"]),
        submission_token=str(served["submission_token"]),
        segments=(SEGMENT,),
    )
    assert calls["n"] == 0
    nas_routellm_http_call_count = calls["n"]
    assert nas_routellm_http_call_count == 0


def test_gsqs_step_command_has_no_idempotency_key() -> None:
    fields = StepGsqsB0.__dataclass_fields__
    assert "idempotency_key" not in fields
    command = StepGsqsB0(run_id="b0run_" + "a" * 24)
    assert command.submission_token is None
    assert command.segments is None


def test_mcp_projector_emits_imagecontent_for_gsqs_raster_role() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 12
    encoded = __import__("base64").b64encode(png).decode("ascii")
    projected = _image_from_result(
        {
            "raster_role": "gsqs-b0-case",
            "media_type": "image/png",
            "content_base64": encoded,
            "content_sha256": "ab" * 32,
            "byte_length": len(png),
            "prompt_text": "frozen",
            "submission_token": "secret-must-not-block-projection",
        }
    )
    assert isinstance(projected, ImageContent)
    assert projected.data == encoded
