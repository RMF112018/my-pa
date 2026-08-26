"""Deterministic B0 repetition orchestrator. One explicit repetition; no scoring."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from my_pa.application.goodnotes_gsqs_b0_acquisition import (
    AcquisitionAuthorization,
    AcquisitionError,
    assert_acquisition_permitted,
)
from my_pa.application.goodnotes_gsqs_b0_capture import (
    CaptureBinding,
    CaptureWriterError,
    write_repetition_capture,
)
from my_pa.application.goodnotes_gsqs_b0_model_client import B0ModelClient, B0ModelClientError
from my_pa.application.goodnotes_gsqs_b0_stdio_session import StdioHostError
from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION, parse_interchange
from my_pa.application.goodnotes_gsqs_live_b0 import (
    AnalyzerCaseInput,
    B0Census,
    FrozenAnalyzerConfig,
)

STATE_SCHEMA = "gsqs-b0-acquisition-state-v1"
JOURNAL_NAME = "accepted-cases.jsonl"
STATE_NAME = "ACQUISITION_STATE.json"


class AcquisitionState(StrEnum):
    NEVER_STARTED = "NEVER_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    INVALID = "INVALID"
    INTERRUPTED = "INTERRUPTED"


class ContentSession(Protocol):
    def initialize_and_list_tools(self) -> tuple[str, ...]: ...

    def fetch_png(self, *, case_id: str, expected_sha256: str) -> bytes: ...

    def close(self) -> None: ...


class OrchestratorError(ValueError):
    """Repetition acquisition refused or invalidated."""


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    state: AcquisitionState
    repetition: int
    captured: int
    missing: int
    duplicates: int
    capture_path: Path | None
    resumable: bool


def acquire_repetition(
    *,
    authorization: AcquisitionAuthorization,
    census: B0Census,
    campaign_id: str,
    repetition: int,
    output_dir: Path,
    config: FrozenAnalyzerConfig,
    candidate_identity: str,
    model_client: B0ModelClient,
    session: ContentSession,
) -> AcquisitionResult:
    assert_acquisition_permitted(
        authorization,
        repetition=repetition,
        corpus_version=census.corpus_version,
        combined_identity=census.combined_identity,
        model_identity=config.model_identity,
        prompt_config_identity=config.prompt_config_identity,
        candidate_identity=candidate_identity,
        model_client=model_client.identity,
    )
    if authorization.campaign_id != campaign_id:
        raise AcquisitionError("campaign_id mismatch")
    if model_client.identity != authorization.model_client:
        raise OrchestratorError("model-client identity drift")
    if output_dir.is_symlink():
        raise OrchestratorError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    prior = _read_state(output_dir)
    if prior is not None:
        raise OrchestratorError(
            f"output directory already holds {prior['state']}; fresh repetition required"
        )
    _write_state(
        output_dir,
        state=AcquisitionState.IN_PROGRESS,
        repetition=repetition,
        accepted=(),
        session_id=model_client.session_id(),
        resumable=False,
    )
    documents: list[dict[str, object]] = []
    accepted: list[str] = []
    try:
        tools = session.initialize_and_list_tools()
        expected = ("goodnotes.content", "goodnotes.work")
        if tuple(sorted(tools)) != expected:
            raise OrchestratorError("tools/list mismatch")
        for member in census.members:
            png = session.fetch_png(case_id=member.case_id, expected_sha256=member.raster_sha256)
            digest = sha256(png).hexdigest()
            if digest != member.raster_sha256:
                raise OrchestratorError("raster hash mismatch")
            request = AnalyzerCaseInput(
                case_id=member.case_id,
                corpus_version=census.corpus_version,
                raster_sha256=member.raster_sha256,
                interchange_schema_version=INTERCHANGE_SCHEMA_VERSION,
                image_bytes=png,
            )
            document = dict(model_client.analyze(request, config))
            parse_interchange(document)
            documents.append(document)
            accepted.append(member.case_id)
            _append_journal(output_dir, member.case_id)
            _write_state(
                output_dir,
                state=AcquisitionState.IN_PROGRESS,
                repetition=repetition,
                accepted=tuple(accepted),
                session_id=model_client.session_id(),
                resumable=False,
            )
        binding = CaptureBinding(
            campaign_id=campaign_id,
            corpus_version=census.corpus_version,
            combined_identity=census.combined_identity,
            repetition=repetition,
            candidate_identity=candidate_identity,
            model_identity=config.model_identity,
            analyzer_name=config.analyzer_name,
            analyzer_version=config.analyzer_version,
            prompt_config_identity=config.prompt_config_identity,
        )
        path = write_repetition_capture(
            output_dir, binding=binding, census=census, documents=documents
        )
        _write_state(
            output_dir,
            state=AcquisitionState.COMPLETE,
            repetition=repetition,
            accepted=tuple(accepted),
            session_id=model_client.session_id(),
            resumable=False,
        )
        return AcquisitionResult(
            state=AcquisitionState.COMPLETE,
            repetition=repetition,
            captured=len(documents),
            missing=0,
            duplicates=0,
            capture_path=path,
            resumable=False,
        )
    except (
        OrchestratorError,
        StdioHostError,
        CaptureWriterError,
        B0ModelClientError,
        AcquisitionError,
        OSError,
    ):
        _write_state(
            output_dir,
            state=AcquisitionState.INTERRUPTED if accepted else AcquisitionState.INVALID,
            repetition=repetition,
            accepted=tuple(accepted),
            session_id=model_client.session_id(),
            resumable=False,
        )
        raise
    finally:
        session.close()


def _append_journal(directory: Path, case_id: str) -> None:
    path = directory / JOURNAL_NAME
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        os.write(fd, (json.dumps({"case_id": case_id}, sort_keys=True) + "\n").encode())
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_state(directory: Path) -> dict[str, object] | None:
    path = directory / STATE_NAME
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OrchestratorError("acquisition state is malformed")
    return payload


def _write_state(
    directory: Path,
    *,
    state: AcquisitionState,
    repetition: int,
    accepted: tuple[str, ...],
    session_id: str,
    resumable: bool,
) -> None:
    payload: dict[str, object] = {
        "accepted_case_ids": list(accepted),
        "repetition": repetition,
        "resumable": resumable,
        "schema_version": STATE_SCHEMA,
        "session_id": session_id,
        "state": state.value,
    }
    body = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path = directory / STATE_NAME
    tmp = directory / f".{STATE_NAME}.tmp"
    if tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        written = 0
        while written < len(body):
            written += os.write(fd, body[written:])
        os.fsync(fd)
    except OSError:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    os.close(fd)
    tmp.replace(path)
