"""Canonical gsqs-analyzer-capture-v1 writer. No gold, no silent overwrite."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs_b0_mcp import CAPTURE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION, parse_interchange
from my_pa.application.goodnotes_gsqs_live_b0 import B0Census

_FORBIDDEN_CAPTURE_KEYS = frozenset(
    {
        "controlled_handwriting",
        "expected_score",
        "gold",
        "label_sha256",
        "private_label",
        "transcription_gold",
    }
)


@dataclass(frozen=True, slots=True)
class CaptureBinding:
    campaign_id: str
    corpus_version: str
    combined_identity: str
    repetition: int
    candidate_identity: str
    model_identity: str
    analyzer_name: str
    analyzer_version: str
    prompt_config_identity: str


class CaptureWriterError(ValueError):
    """Capture persistence refused."""


def repetition_filename(repetition: int) -> str:
    if repetition < 1 or repetition > 99:
        raise CaptureWriterError("repetition out of range")
    return f"repetition-{repetition:03d}.json"


def capture_payload(
    *,
    binding: CaptureBinding,
    census: B0Census,
    documents: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if len(documents) != len(census.members):
        raise CaptureWriterError("captured analyzer documents do not match census")
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for item, member in zip(documents, census.members, strict=True):
        if not isinstance(item, Mapping):
            raise CaptureWriterError("captured analyzer document is not an object")
        document = dict(item)
        _reject_gold(document)
        if str(document.get("case_id")) != member.case_id:
            raise CaptureWriterError("captured analyzer documents do not match census")
        if str(document.get("content_sha256")) != member.raster_sha256:
            raise CaptureWriterError("capture content_sha256 does not match census")
        if str(document.get("corpus_version")) != census.corpus_version:
            raise CaptureWriterError("capture corpus_version mismatch")
        if str(document.get("schema_version")) != INTERCHANGE_SCHEMA_VERSION:
            raise CaptureWriterError("wrong analyzer interchange schema")
        if str(document.get("model_identity")) != binding.model_identity:
            raise CaptureWriterError("model identity drift")
        if str(document.get("prompt_config_identity")) != binding.prompt_config_identity:
            raise CaptureWriterError("prompt identity drift")
        if str(document.get("analyzer_name")) != binding.analyzer_name:
            raise CaptureWriterError("analyzer identity drift")
        parse_interchange(document)
        if member.case_id in seen:
            raise CaptureWriterError("duplicate canonical case")
        seen.add(member.case_id)
        validated.append(document)
    payload: dict[str, object] = {
        "analyzer_name": binding.analyzer_name,
        "analyzer_version": binding.analyzer_version,
        "campaign_id": binding.campaign_id,
        "candidate_identity": binding.candidate_identity,
        "combined_identity": binding.combined_identity,
        "corpus_version": binding.corpus_version,
        "documents": validated,
        "model_identity": binding.model_identity,
        "prompt_config_identity": binding.prompt_config_identity,
        "repetition": binding.repetition,
        "schema_version": CAPTURE_SCHEMA_VERSION,
    }
    _reject_gold(payload)
    return payload


def canonical_capture_bytes(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def capture_sha256(payload: Mapping[str, object]) -> str:
    return sha256(canonical_capture_bytes(payload)).hexdigest()


def write_repetition_capture(
    directory: Path,
    *,
    binding: CaptureBinding,
    census: B0Census,
    documents: Sequence[Mapping[str, object]],
) -> Path:
    if directory.is_symlink():
        raise CaptureWriterError("capture directory must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True)
    payload = capture_payload(binding=binding, census=census, documents=documents)
    body = canonical_capture_bytes(payload)
    target = directory / repetition_filename(binding.repetition)
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise CaptureWriterError("captured analyzer output is missing")
        existing = target.read_bytes()
        if existing == body:
            return target
        raise CaptureWriterError("conflicting capture record")
    tmp = directory / f".{repetition_filename(binding.repetition)}.tmp"
    if tmp.exists():
        tmp.unlink()
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        written = 0
        while written < len(body):
            written += os.write(fd, body[written:])
        os.fsync(fd)
    except OSError as error:
        os.close(fd)
        tmp.unlink(missing_ok=True)
        raise CaptureWriterError("writer I/O failure") from error
    os.close(fd)
    tmp.replace(target)
    return target


def _reject_gold(payload: object) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in _FORBIDDEN_CAPTURE_KEYS or any(
                token in lowered for token in ("gold", "controlled_handwriting")
            ):
                raise CaptureWriterError("gold must not appear in capture records")
            _reject_gold(value)
    elif isinstance(payload, list):
        for item in payload:
            _reject_gold(item)
