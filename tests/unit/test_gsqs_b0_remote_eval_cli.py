"""CLI remote-eval Phase A: prepare, status, export, score, abort, clean."""

from __future__ import annotations

import importlib.util
import inspect
import json
import socket
import urllib.request
from hashlib import sha256
from pathlib import Path
from types import ModuleType

import apps.cli.gsqs_b0 as cli
import pytest

from my_pa.application.goodnotes_gsqs import MEASURED_B0_NOT_YET_ESTABLISHED
from my_pa.application.goodnotes_gsqs_b0_mcp import CAPTURE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import ERROR_FORBIDDEN_SCOPE

GENERATE_PATH = Path("ops/goodnotes/gsqs/fixtures/remote-eval/generate.py")
PROMPT_PATH = Path("ops/goodnotes/gsqs/b0/chatllm-remote-eval-prompt-v1.txt")
SESSION_ID = "remoteevalphaseasession01"


def _load_generate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gsqs_remote_eval_generate", GENERATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, dict[str, object]]:
    code = cli.main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out) if captured.out.strip() else {}
    return code, payload


def _prepare(
    tmp_path: Path, generate: ModuleType, capsys: pytest.CaptureFixture[str]
) -> dict[str, object]:
    rasters = tmp_path / "rasters"
    generate.write_rasters(rasters)
    code, payload = _run(
        capsys,
        [
            "prepare-remote-eval",
            "--state-root",
            str(tmp_path / "state"),
            "--source-raster-root",
            str(rasters),
            "--session-id",
            SESSION_ID,
        ],
    )
    assert code == cli.EXIT_OK
    assert payload["ok"] is True
    return payload


def _fill_repetition(tmp_path: Path, generate: ModuleType, repetition: int) -> None:
    service, _store, _clock = cli._compose_remote_eval(tmp_path / "state", tmp_path / "rasters")
    segments = generate.synthetic_segments()
    for _ in range(generate.CASE_COUNT):
        acquired = service.acquire_case(SESSION_ID)
        assert acquired.repetition == repetition
        service.submit_capture(SESSION_ID, acquired.lease.lease_id, segments)


def test_existing_commands_still_parse() -> None:
    args = cli.build_parser().parse_args(["preflight"])
    assert args.command == "preflight"
    choices = cli.build_parser()._subparsers._group_actions[0].choices
    assert {"preflight", "execute", "score", "serve-eval-mcp"} <= set(choices)


def test_prepare_does_not_import_routellm_transport() -> None:
    source = inspect.getsource(cli._prepare_remote_eval)
    assert "gsqs_routellm_transport" not in source
    assert "execute_measured_b0" not in source
    assert "load_public_catalog" not in source


def test_prepare_does_not_use_network(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    generate = _load_generate()

    def _fail_urlopen(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is forbidden")

    def _fail_socket(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network is forbidden")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_urlopen)
    monkeypatch.setattr(socket, "create_connection", _fail_socket)
    payload = _prepare(tmp_path, generate, capsys)
    assert payload["state"] == "READY"
    assert payload["case_count"] == 73
    assert payload["mode"] == "SYNTHETIC_CANARY"
    prompt_digest = sha256(PROMPT_PATH.read_bytes()).hexdigest()
    assert payload["semantic_prompt_sha256"] == prompt_digest
    assert payload["conversation_prompt_sha256"] == prompt_digest
    assert payload["session_identity_sha256"]
    assert (tmp_path / "rasters" / "syn-b-001.png").is_file()
    assert (tmp_path / "rasters" / "syn-b-073.png").is_file()
    assert len(list((tmp_path / "rasters").glob("syn-b-*.png"))) == 73


def test_prepare_phase_c_fail_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(
        capsys,
        [
            "prepare-remote-eval",
            "--state-root",
            str(tmp_path / "state"),
            "--source-raster-root",
            str(tmp_path / "rasters"),
            "--mode",
            "PHASE_C",
        ],
    )
    assert code == cli.EXIT_REFUSED
    assert payload["ok"] is False
    assert payload["code"] == ERROR_FORBIDDEN_SCOPE


def test_abort_requires_reason() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "remote-eval-abort",
                "--state-root",
                "state",
                "--session-id",
                SESSION_ID,
            ]
        )


def test_clean_refuses_active_session(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    generate = _load_generate()
    _prepare(tmp_path, generate, capsys)
    code, payload = _run(
        capsys,
        [
            "remote-eval-clean",
            "--state-root",
            str(tmp_path / "state"),
            "--session-id",
            SESSION_ID,
        ],
    )
    assert code == cli.EXIT_REFUSED
    assert payload["ok"] is False


def test_prompt_file_exists_and_is_hashed() -> None:
    assert PROMPT_PATH.is_file()
    digest = sha256(PROMPT_PATH.read_bytes()).hexdigest()
    assert len(digest) == 64


def test_generate_requires_output_dir() -> None:
    generate = _load_generate()
    with pytest.raises(SystemExit):
        generate.main([])


def test_remote_eval_cli_success_path(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    generate = _load_generate()
    prepared = _prepare(tmp_path, generate, capsys)
    state_root = tmp_path / "state"
    export_dir = tmp_path / "export"
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    code, status = _run(
        capsys,
        [
            "remote-eval-status",
            "--state-root",
            str(state_root),
            "--session-id",
            SESSION_ID,
        ],
    )
    assert code == cli.EXIT_OK
    assert status["ok"] is True
    assert status["state"] == "READY"
    assert status["session_identity_sha256"] == prepared["session_identity_sha256"]
    assert "gold" not in json.dumps(status)
    assert "source" not in json.dumps(status)

    for repetition in (1, 2, 3):
        code, opened = _run(
            capsys,
            [
                "remote-eval-open-repetition",
                "--state-root",
                str(state_root),
                "--session-id",
                SESSION_ID,
                "--repetition",
                str(repetition),
            ],
        )
        assert code == cli.EXIT_OK
        assert opened["ok"] is True
        _fill_repetition(tmp_path, generate, repetition)

    code, exported = _run(
        capsys,
        [
            "remote-eval-export",
            "--state-root",
            str(state_root),
            "--session-id",
            SESSION_ID,
            "--output-dir",
            str(export_dir),
        ],
    )
    assert code == cli.EXIT_OK
    assert exported["ok"] is True
    assert exported["schema_version"] == CAPTURE_SCHEMA_VERSION
    first = export_dir / "repetition-001.json"
    assert first.is_file()
    body = json.loads(first.read_text(encoding="utf-8"))
    assert body["schema_version"] == CAPTURE_SCHEMA_VERSION
    assert len(body["documents"]) == 73

    code, scored = _run(
        capsys,
        [
            "score-remote-eval",
            "--state-root",
            str(state_root),
            "--session-id",
            SESSION_ID,
            "--evidence-dir",
            str(evidence_dir),
        ],
    )
    assert code == cli.EXIT_OK
    assert scored["ok"] is True
    assert scored["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED
    assert scored["MEASURED_B0"] == "NOT_YET_ESTABLISHED"
    assert len(scored["measurements"]) == 3
    assert (evidence_dir / "remote-eval-score.json").is_file()

    abort_id = "remoteevalphaseaabort0001"
    generate.write_rasters(tmp_path / "rasters")
    code, aborted_prepare = _run(
        capsys,
        [
            "prepare-remote-eval",
            "--state-root",
            str(tmp_path / "abort-state"),
            "--source-raster-root",
            str(tmp_path / "rasters"),
            "--session-id",
            abort_id,
        ],
    )
    assert code == cli.EXIT_OK
    assert aborted_prepare["ok"] is True
    code, aborted = _run(
        capsys,
        [
            "remote-eval-abort",
            "--state-root",
            str(tmp_path / "abort-state"),
            "--session-id",
            abort_id,
            "--reason",
            "operator-stop",
        ],
    )
    assert code == cli.EXIT_OK
    assert aborted["ok"] is True
    assert aborted["state"] == "ABORTED"

    code, cleaned = _run(
        capsys,
        [
            "remote-eval-clean",
            "--state-root",
            str(state_root),
            "--session-id",
            SESSION_ID,
        ],
    )
    assert code == cli.EXIT_OK
    assert cleaned["ok"] is True
    assert cleaned["captures_discarded"] is False
    assert cleaned["rasters_removed"] is True
    session_dir = cli.session_directory(state_root, SESSION_ID)
    assert not (session_dir / "rasters").exists()
    assert (session_dir / "captures" / "repetition-001.capture.json").is_file()
