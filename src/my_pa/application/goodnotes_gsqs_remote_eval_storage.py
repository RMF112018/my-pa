"""Filesystem spool for GSQS ChatLLM remote-eval sessions (Phase A).

Persists session, manifest, state, captures, and terminal receipts under an
explicit caller-supplied state root. It does not write private gold, source
paths, or managed-document bytes. Persistence is bytes; this module does not
sample a clock.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, is_dataclass, replace
from datetime import datetime
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs import NOTE_UNIT_V2
from my_pa.application.goodnotes_gsqs_b0_mcp import CAPTURE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_harness import INTERCHANGE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_STATE_INTEGRITY_FAILURE,
    MANIFEST_FORBIDDEN_KEYS,
    SCHEMA_CAPTURE_ENTRY_V1,
    SCHEMA_SESSION_MANIFEST_V1,
    SCHEMA_SESSION_V1,
    SCHEMA_STATE_V1,
    SCHEMA_TERMINAL_RECEIPT_V1,
    TERMINAL_STATES,
    CaptureEntry,
    Lease,
    ManifestCase,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSession,
    RemoteEvalSessionState,
    RepetitionProgress,
    SessionManifest,
    SessionState,
    TerminalReceipt,
    compute_capture_identity_sha256,
    compute_receipt_sha256,
    compute_session_identity_sha256,
    remote_eval_canonical_dumps,
)
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_CAPTURE_FILE_RE = re.compile(r"^(\d{3})-([A-Za-z0-9][A-Za-z0-9._-]*)\.json$")
_TEMP_PREFIX = ".tmp-"
_FORBIDDEN_EXPORT_KEYS = MANIFEST_FORBIDDEN_KEYS | {
    "gold",
    "path",
    "private_gold",
    "raster_path",
    "source_path",
}

__all__ = [
    "CaptureRecoveryReport",
    "FilesystemRemoteEvalStore",
    "atomic_write_bytes",
    "fsync_directory",
    "mkdir_private",
    "reject_symlink",
    "resolve_under_root",
    "session_directory",
    "validate_session_id",
]


@dataclass(frozen=True, slots=True)
class CaptureRecoveryReport:
    classification: str
    session_id: str
    recoverable_forward: bool
    capture: CaptureEntry | None
    detail: str


def validate_session_id(session_id: str) -> str:
    if not session_id or "\x00" in session_id or "/" in session_id or "\\" in session_id:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session_id is invalid")
    if ".." in session_id or not _SESSION_ID_RE.fullmatch(session_id):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session_id is invalid")
    return session_id


def validate_case_id(case_id: str) -> str:
    if not case_id or "\x00" in case_id or "/" in case_id or "\\" in case_id:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "case_id is invalid")
    if ".." in case_id or not _CASE_ID_RE.fullmatch(case_id):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "case_id is invalid")
    return case_id


def reject_symlink(path: Path, *, what: str) -> None:
    if path.is_symlink():
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{what} is a symlink")


def resolve_under_root(root: Path, candidate: Path) -> Path:
    reject_symlink(root, what="root")
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "path escapes root") from exc
    return resolved


def session_directory(state_root: Path, session_id: str) -> Path:
    validate_session_id(session_id)
    reject_symlink(state_root, what="state_root")
    candidate = state_root / "sessions" / session_id
    reject_symlink(candidate, what="session directory")
    if candidate.exists():
        return resolve_under_root(state_root, candidate)
    resolved_root = state_root.resolve()
    resolved = resolved_root / "sessions" / session_id
    try:
        resolved.relative_to(resolved_root / "sessions")
    except ValueError as exc:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session_id escapes root") from exc
    return resolved


def mkdir_private(path: Path) -> None:
    reject_symlink(path, what="directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    reject_symlink(path, what="directory")
    path.chmod(0o700)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    directory = path.parent
    mkdir_private(directory)
    reject_symlink(path, what="destination")
    descriptor, tmp_name = tempfile.mkstemp(prefix=_TEMP_PREFIX, dir=directory)
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        written = tmp_path.read_bytes()
        if written != data or sha256(written).digest() != sha256(data).digest():
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "temp write hash mismatch")
        tmp_path.replace(path)
        replaced = True
        path.chmod(0o600)
        fsync_directory(directory)
    except Exception:
        if not replaced and tmp_path.exists():
            tmp_path.unlink()
        raise


def atomic_write_json(path: Path, value: object) -> None:
    payload = remote_eval_canonical_dumps(value) + "\n"
    atomic_write_bytes(path, payload.encode("utf-8"))


def _load_json_object(path: Path) -> dict[str, object]:
    reject_symlink(path, what="json file")
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "JSON is corrupt") from exc
    if not isinstance(parsed, dict):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "JSON is not an object")
    return parsed


def _require_str(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return value


def _require_optional_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return value


def _require_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return value


def _require_optional_int(payload: Mapping[str, object], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return value


def _require_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return value


def _require_mapping(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return dict(value)


def _require_list(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{key} is invalid")
    return value


def _parse_rfc3339(value: object) -> datetime:
    if not isinstance(value, str):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "timestamp is not a string")
    try:
        parsed = datetime.fromisoformat(value)
        return ensure_utc(parsed)
    except (ValueError, NaiveDatetimeError) as exc:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "timestamp is invalid") from exc


def _parse_mode(value: object) -> RemoteEvalMode:
    if not isinstance(value, str):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "mode is invalid")
    try:
        return RemoteEvalMode(value)
    except ValueError as exc:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "mode is invalid") from exc


def _parse_session_state(value: object) -> RemoteEvalSessionState:
    if not isinstance(value, str):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "state is invalid")
    try:
        return RemoteEvalSessionState(value)
    except ValueError as exc:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "state is invalid") from exc


def _require_keys(payload: Mapping[str, object], cls: type[object]) -> None:
    if not is_dataclass(cls):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{cls.__name__} is not a dataclass")
    expected = set(cls.__dataclass_fields__)
    if set(payload) != expected:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, f"{cls.__name__} keys mismatch")


def _session_from_dict(payload: Mapping[str, object]) -> RemoteEvalSession:
    _require_keys(payload, RemoteEvalSession)
    session = RemoteEvalSession(
        schema_version=_require_str(payload, "schema_version"),
        session_id=_require_str(payload, "session_id"),
        mode=_parse_mode(payload.get("mode")),
        authorization_id=_require_str(payload, "authorization_id"),
        principal_id=_require_str(payload, "principal_id"),
        created_at=_parse_rfc3339(payload.get("created_at")),
        expires_at=_parse_rfc3339(payload.get("expires_at")),
        repository_owner=_require_str(payload, "repository_owner"),
        repository_name=_require_str(payload, "repository_name"),
        repository_commit_sha=_require_str(payload, "repository_commit_sha"),
        repository_tree_sha=_require_str(payload, "repository_tree_sha"),
        evaluator_id=_require_str(payload, "evaluator_id"),
        evaluator_version=_require_str(payload, "evaluator_version"),
        evaluator_behavior_sha256=_require_str(payload, "evaluator_behavior_sha256"),
        corpus_version=_require_str(payload, "corpus_version"),
        public_manifest_sha256=_require_str(payload, "public_manifest_sha256"),
        combined_identity_sha256=_require_str(payload, "combined_identity_sha256"),
        partition=_require_str(payload, "partition"),
        case_count=_require_int(payload, "case_count"),
        case_order_sha256=_require_str(payload, "case_order_sha256"),
        analyzer_id=_require_str(payload, "analyzer_id"),
        analyzer_version=_require_str(payload, "analyzer_version"),
        semantic_prompt_sha256=_require_str(payload, "semantic_prompt_sha256"),
        conversation_prompt_sha256=_require_str(payload, "conversation_prompt_sha256"),
        model_selection_label=_require_str(payload, "model_selection_label"),
        repetitions_required=_require_int(payload, "repetitions_required"),
        session_identity_sha256=_require_str(payload, "session_identity_sha256"),
    )
    if session.schema_version != SCHEMA_SESSION_V1:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "session schema_version mismatch")
    if compute_session_identity_sha256(session) != session.session_identity_sha256:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "session identity hash mismatch")
    return session


def _manifest_case_from_dict(payload: object) -> ManifestCase:
    if not isinstance(payload, dict):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "manifest case is invalid")
    _require_keys(payload, ManifestCase)
    case = ManifestCase(
        ordinal=_require_int(payload, "ordinal"),
        case_id=_require_str(payload, "case_id"),
        content_sha256=_require_str(payload, "content_sha256"),
        byte_length=_require_int(payload, "byte_length"),
        staged_filename=_require_str(payload, "staged_filename"),
    )
    validate_case_id(case.case_id)
    name = case.staged_filename
    if "/" in name or "\\" in name or ".." in name or "\x00" in name or name != Path(name).name:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "staged_filename is invalid")
    return case


def _manifest_from_dict(payload: Mapping[str, object]) -> SessionManifest:
    _require_keys(payload, SessionManifest)
    manifest = SessionManifest(
        schema_version=_require_str(payload, "schema_version"),
        session_id=_require_str(payload, "session_id"),
        session_identity_sha256=_require_str(payload, "session_identity_sha256"),
        cases=tuple(_manifest_case_from_dict(item) for item in _require_list(payload, "cases")),
    )
    if manifest.schema_version != SCHEMA_SESSION_MANIFEST_V1:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "manifest schema_version mismatch")
    return manifest


def _lease_from_dict(payload: object) -> Lease | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "lease is invalid")
    _require_keys(payload, Lease)
    return Lease(
        lease_id=_require_str(payload, "lease_id"),
        case_id=_require_str(payload, "case_id"),
        ordinal=_require_int(payload, "ordinal"),
        repetition=_require_int(payload, "repetition"),
        issued_at=_parse_rfc3339(payload.get("issued_at")),
        expires_at=_parse_rfc3339(payload.get("expires_at")),
    )


def _progress_from_dict(payload: object) -> RepetitionProgress:
    if not isinstance(payload, dict):
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "repetition progress is invalid")
    _require_keys(payload, RepetitionProgress)
    return RepetitionProgress(
        repetition=_require_int(payload, "repetition"),
        opened=_require_bool(payload, "opened"),
        completed=_require_bool(payload, "completed"),
        next_case_ordinal=_require_int(payload, "next_case_ordinal"),
        captures_accepted=_require_int(payload, "captures_accepted"),
        capture_export_sha256=_require_optional_str(payload, "capture_export_sha256"),
    )


def _state_from_dict(payload: Mapping[str, object]) -> SessionState:
    _require_keys(payload, SessionState)
    state = SessionState(
        schema_version=_require_str(payload, "schema_version"),
        session_id=_require_str(payload, "session_id"),
        revision=_require_int(payload, "revision"),
        state=_parse_session_state(payload.get("state")),
        active_repetition=_require_optional_int(payload, "active_repetition"),
        next_case_ordinal=_require_int(payload, "next_case_ordinal"),
        active_lease=_lease_from_dict(payload.get("active_lease")),
        repetitions=tuple(
            _progress_from_dict(item) for item in _require_list(payload, "repetitions")
        ),
        captures_accepted=_require_int(payload, "captures_accepted"),
        capture_export_sha256=_require_optional_str(payload, "capture_export_sha256"),
        last_event_id=_require_optional_str(payload, "last_event_id"),
        updated_at=_parse_rfc3339(payload.get("updated_at")),
        blocked_reason_code=_require_optional_str(payload, "blocked_reason_code"),
        terminal_reason_code=_require_optional_str(payload, "terminal_reason_code"),
    )
    if state.schema_version != SCHEMA_STATE_V1:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "state schema_version mismatch")
    return state


def _capture_from_dict(payload: Mapping[str, object]) -> CaptureEntry:
    _require_keys(payload, CaptureEntry)
    segments_raw = _require_list(payload, "segments")
    segments: list[dict[str, object]] = []
    for item in segments_raw:
        if not isinstance(item, dict):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "segment is invalid")
        segments.append(dict(item))
    capture = CaptureEntry(
        schema_version=_require_str(payload, "schema_version"),
        session_id=_require_str(payload, "session_id"),
        session_identity_sha256=_require_str(payload, "session_identity_sha256"),
        repetition=_require_int(payload, "repetition"),
        case_id=_require_str(payload, "case_id"),
        ordinal=_require_int(payload, "ordinal"),
        content_sha256=_require_str(payload, "content_sha256"),
        corpus_version=_require_str(payload, "corpus_version"),
        public_manifest_sha256=_require_str(payload, "public_manifest_sha256"),
        combined_identity_sha256=_require_str(payload, "combined_identity_sha256"),
        analyzer_id=_require_str(payload, "analyzer_id"),
        analyzer_version=_require_str(payload, "analyzer_version"),
        semantic_prompt_sha256=_require_str(payload, "semantic_prompt_sha256"),
        conversation_prompt_sha256=_require_str(payload, "conversation_prompt_sha256"),
        model_selection_label=_require_str(payload, "model_selection_label"),
        captured_at=_parse_rfc3339(payload.get("captured_at")),
        lease_id=_require_str(payload, "lease_id"),
        idempotency_digest=_require_str(payload, "idempotency_digest"),
        segments=tuple(segments),
        capture_identity_sha256=_require_str(payload, "capture_identity_sha256"),
    )
    if capture.schema_version != SCHEMA_CAPTURE_ENTRY_V1:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture schema_version mismatch")
    if compute_capture_identity_sha256(capture) != capture.capture_identity_sha256:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture identity hash mismatch")
    return capture


def _receipt_from_dict(payload: Mapping[str, object]) -> TerminalReceipt:
    _require_keys(payload, TerminalReceipt)
    exports: list[tuple[int, str | None]] = []
    for item in _require_list(payload, "repetition_capture_exports"):
        if isinstance(item, list) and len(item) == 2:
            repetition, digest = item
        elif isinstance(item, dict):
            repetition = item.get("repetition")
            digest = item.get("capture_export_sha256")
        else:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "export pair is invalid")
        if isinstance(repetition, bool) or not isinstance(repetition, int):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "export pair is invalid")
        if digest is not None and not isinstance(digest, str):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "export digest is invalid")
        exports.append((repetition, digest))
    counts_raw = _require_mapping(payload, "disclosure_counts")
    counts: dict[str, int] = {}
    for key, value in counts_raw.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "disclosure_counts is invalid")
        counts[str(key)] = value
    receipt = TerminalReceipt(
        schema_version=_require_str(payload, "schema_version"),
        session_id=_require_str(payload, "session_id"),
        session_identity_sha256=_require_str(payload, "session_identity_sha256"),
        terminal_state=_parse_session_state(payload.get("terminal_state")),
        terminal_at=_parse_rfc3339(payload.get("terminal_at")),
        manifest_sha256=_require_str(payload, "manifest_sha256"),
        final_state_sha256=_require_str(payload, "final_state_sha256"),
        disclosure_journal_sha256=_require_optional_str(payload, "disclosure_journal_sha256"),
        disclosure_counts=counts,
        repetition_capture_exports=tuple(exports),
        total_captures=_require_int(payload, "total_captures"),
        cleanup_retention=_require_mapping(payload, "cleanup_retention"),
        receipt_sha256=_require_str(payload, "receipt_sha256"),
    )
    if receipt.schema_version != SCHEMA_TERMINAL_RECEIPT_V1:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "receipt schema_version mismatch")
    if compute_receipt_sha256(receipt) != receipt.receipt_sha256:
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "receipt hash mismatch")
    return receipt


def _capture_path(session_dir: Path, repetition: int, ordinal: int, case_id: str) -> Path:
    validate_case_id(case_id)
    if repetition < 1 or ordinal < 1:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "invalid capture coordinates")
    return (
        session_dir / "captures" / f"repetition-{repetition:03d}" / f"{ordinal:03d}-{case_id}.json"
    )


def _final_capture_files(repetition_dir: Path) -> tuple[Path, ...]:
    if not repetition_dir.exists():
        return ()
    reject_symlink(repetition_dir, what="capture directory")
    found: list[Path] = []
    for path in sorted(repetition_dir.iterdir()):
        if path.is_symlink():
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture path is a symlink")
        if not path.is_file() or path.name.startswith(_TEMP_PREFIX) or path.name.startswith("."):
            continue
        if _CAPTURE_FILE_RE.match(path.name) is None:
            continue
        found.append(path)
    return tuple(found)


def _temp_capture_files(repetition_dir: Path) -> tuple[Path, ...]:
    if not repetition_dir.exists():
        return ()
    return tuple(
        path
        for path in sorted(repetition_dir.iterdir())
        if path.is_file() and path.name.startswith(_TEMP_PREFIX)
    )


def _load_capture_file(path: Path) -> CaptureEntry:
    return _capture_from_dict(_load_json_object(path))


def _interchange_document(capture: CaptureEntry) -> dict[str, object]:
    document: dict[str, object] = {
        "analyzer_name": capture.analyzer_id,
        "analyzer_version": capture.analyzer_version,
        "case_id": capture.case_id,
        "content_sha256": capture.content_sha256,
        "corpus_version": capture.corpus_version,
        "proposal_schema_version": NOTE_UNIT_V2,
        "schema_version": INTERCHANGE_SCHEMA_VERSION,
        "segments": [dict(item) for item in capture.segments],
    }
    if _FORBIDDEN_EXPORT_KEYS & set(document):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "export contains forbidden keys")
    return document


def _rmtree_private(path: Path) -> None:
    reject_symlink(path, what="removal target")
    for child in path.iterdir():
        reject_symlink(child, what="removal target")
        if child.is_dir():
            _rmtree_private(child)
        else:
            child.unlink()
    path.rmdir()


class FilesystemRemoteEvalStore:
    """Durable filesystem implementation of ``RemoteEvalStore``."""

    def __init__(self, state_root: Path) -> None:
        self._state_root = Path(state_root)
        if self._state_root.exists():
            reject_symlink(self._state_root, what="state_root")
            if not self._state_root.is_dir():
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "state_root is not a directory")

    def create_session(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> None:
        if session.session_id != manifest.session_id or session.session_id != state.session_id:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session identity mismatch")
        mkdir_private(self._state_root)
        session_dir = session_directory(self._state_root, session.session_id)
        if session_dir.exists():
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session already exists")
        mkdir_private(session_dir)
        mkdir_private(session_dir / "journal")
        mkdir_private(session_dir / "captures")
        mkdir_private(session_dir / "receipts")
        atomic_write_json(session_dir / "session.json", session)
        atomic_write_json(session_dir / "manifest.json", manifest)
        atomic_write_json(session_dir / "state.json", state)
        fsync_directory(session_dir)

    def load_session(self, session_id: str) -> RemoteEvalSession | None:
        path = session_directory(self._state_root, session_id) / "session.json"
        if not path.exists():
            return None
        session = _session_from_dict(_load_json_object(path))
        if session.session_id != session_id:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "session_id mismatch")
        return session

    def load_manifest(self, session_id: str) -> SessionManifest | None:
        path = session_directory(self._state_root, session_id) / "manifest.json"
        if not path.exists():
            return None
        manifest = _manifest_from_dict(_load_json_object(path))
        if manifest.session_id != session_id:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "manifest session_id mismatch")
        return manifest

    def load_state(self, session_id: str) -> SessionState | None:
        path = session_directory(self._state_root, session_id) / "state.json"
        if not path.exists():
            return None
        state = _state_from_dict(_load_json_object(path))
        if state.session_id != session_id:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "state session_id mismatch")
        return state

    def save_state(self, state: SessionState) -> None:
        session_dir = session_directory(self._state_root, state.session_id)
        if not session_dir.is_dir():
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session directory missing")
        atomic_write_json(session_dir / "state.json", state)

    def save_manifest(self, manifest: SessionManifest) -> None:
        session_dir = session_directory(self._state_root, manifest.session_id)
        if not session_dir.is_dir():
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session directory missing")
        atomic_write_json(session_dir / "manifest.json", manifest)

    def commit_capture(
        self,
        *,
        state: SessionState,
        capture: CaptureEntry,
        terminal_receipt: TerminalReceipt | None = None,
    ) -> None:
        if state.session_id != capture.session_id:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "capture session mismatch")
        if compute_capture_identity_sha256(capture) != capture.capture_identity_sha256:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture identity hash mismatch")
        session_dir = session_directory(self._state_root, capture.session_id)
        if not session_dir.is_dir():
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session directory missing")
        dest = _capture_path(session_dir, capture.repetition, capture.ordinal, capture.case_id)
        existing = self.load_capture(capture.session_id, capture.repetition, capture.case_id)
        if (
            existing is not None
            and existing.capture_identity_sha256 != capture.capture_identity_sha256
        ):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "conflicting capture files")
        atomic_write_json(dest, capture)
        if terminal_receipt is not None:
            if terminal_receipt.session_id != capture.session_id:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "receipt session mismatch")
            self.save_terminal_receipt(terminal_receipt)
        self.save_state(state)

    def load_capture(self, session_id: str, repetition: int, case_id: str) -> CaptureEntry | None:
        validate_case_id(case_id)
        session_dir = session_directory(self._state_root, session_id)
        repetition_dir = session_dir / "captures" / f"repetition-{repetition:03d}"
        matches: list[CaptureEntry] = []
        for path in _final_capture_files(repetition_dir):
            parsed = _load_capture_file(path)
            if parsed.case_id == case_id:
                matches.append(parsed)
        if len(matches) > 1:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "conflicting capture files")
        if not matches:
            return None
        capture = matches[0]
        if capture.session_id != session_id or capture.repetition != repetition:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture does not match session")
        return capture

    def load_capture_by_lease(self, session_id: str, lease_id: str) -> CaptureEntry | None:
        session_dir = session_directory(self._state_root, session_id)
        captures_root = session_dir / "captures"
        if not captures_root.exists():
            return None
        found: list[CaptureEntry] = []
        for repetition_dir in sorted(captures_root.iterdir()):
            if not repetition_dir.is_dir() or repetition_dir.name.startswith("."):
                continue
            for path in _final_capture_files(repetition_dir):
                capture = _load_capture_file(path)
                if capture.lease_id == lease_id:
                    found.append(capture)
        if len(found) > 1:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "conflicting capture files")
        if not found:
            return None
        if found[0].session_id != session_id:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture does not match session")
        return found[0]

    def list_captures(self, session_id: str, repetition: int) -> tuple[CaptureEntry, ...]:
        session_dir = session_directory(self._state_root, session_id)
        repetition_dir = session_dir / "captures" / f"repetition-{repetition:03d}"
        captures: list[CaptureEntry] = []
        seen: set[str] = set()
        for path in _final_capture_files(repetition_dir):
            capture = _load_capture_file(path)
            if capture.case_id in seen:
                raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "conflicting capture files")
            seen.add(capture.case_id)
            if capture.session_id != session_id or capture.repetition != repetition:
                raise RemoteEvalError(
                    ERROR_STATE_INTEGRITY_FAILURE,
                    "capture does not match session",
                )
            captures.append(capture)
        captures.sort(key=lambda item: item.ordinal)
        ordinals = [item.ordinal for item in captures]
        if len(ordinals) != len(set(ordinals)):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "conflicting capture files")
        return tuple(captures)

    def save_terminal_receipt(self, receipt: TerminalReceipt) -> None:
        if compute_receipt_sha256(receipt) != receipt.receipt_sha256:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "receipt hash mismatch")
        session_dir = session_directory(self._state_root, receipt.session_id)
        if not session_dir.is_dir():
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session directory missing")
        atomic_write_json(session_dir / "receipts" / "terminal.json", receipt)

    def load_terminal_receipt(self, session_id: str) -> TerminalReceipt | None:
        path = session_directory(self._state_root, session_id) / "receipts" / "terminal.json"
        if not path.exists():
            return None
        receipt = _receipt_from_dict(_load_json_object(path))
        if receipt.session_id != session_id:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "receipt session_id mismatch")
        return receipt

    def list_session_ids(self) -> tuple[str, ...]:
        sessions_root = self._state_root / "sessions"
        if not sessions_root.exists():
            return ()
        reject_symlink(sessions_root, what="sessions root")
        found: list[str] = []
        for path in sorted(sessions_root.iterdir()):
            if not path.is_dir():
                continue
            try:
                validate_session_id(path.name)
            except RemoteEvalError:
                continue
            reject_symlink(path, what="session directory")
            found.append(path.name)
        return tuple(found)

    def find_non_terminal_session_id(self) -> str | None:
        for session_id in self.list_session_ids():
            state = self.load_state(session_id)
            if state is None:
                continue
            if state.state not in TERMINAL_STATES:
                return session_id
        return None

    def inspect_capture_recovery(self, session_id: str) -> CaptureRecoveryReport:
        state = self.load_state(session_id)
        if state is None:
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session not found")
        session_dir = session_directory(self._state_root, session_id)
        captures_root = session_dir / "captures"
        grouped: dict[tuple[int, str], list[CaptureEntry]] = {}
        temps: list[Path] = []
        if captures_root.exists():
            reject_symlink(captures_root, what="captures directory")
            for repetition_dir in sorted(captures_root.iterdir()):
                if not repetition_dir.is_dir():
                    continue
                temps.extend(_temp_capture_files(repetition_dir))
                for path in _final_capture_files(repetition_dir):
                    capture = _load_capture_file(path)
                    if capture.session_id != session_id:
                        raise RemoteEvalError(
                            ERROR_STATE_INTEGRITY_FAILURE,
                            "final capture does not match session",
                        )
                    grouped.setdefault((capture.repetition, capture.case_id), []).append(capture)
        for rows in grouped.values():
            if len(rows) > 1:
                raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "conflicting capture files")
        current_case_id: str | None = None
        current_rep = state.active_repetition
        if current_rep is not None:
            manifest = self.load_manifest(session_id)
            if manifest is None:
                raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "manifest missing")
            if 1 <= state.next_case_ordinal <= len(manifest.cases):
                current_case_id = manifest.cases[state.next_case_ordinal - 1].case_id
        if current_rep is not None and current_case_id is not None:
            rows = grouped.get((current_rep, current_case_id), [])
            if len(rows) == 1:
                capture = rows[0]
                if (
                    capture.ordinal != state.next_case_ordinal
                    or capture.repetition != current_rep
                    or capture.case_id != current_case_id
                    or capture.session_id != session_id
                ):
                    raise RemoteEvalError(
                        ERROR_STATE_INTEGRITY_FAILURE,
                        "final capture does not match state",
                    )
                return CaptureRecoveryReport(
                    classification="B",
                    session_id=session_id,
                    recoverable_forward=True,
                    capture=capture,
                    detail="valid final capture exists; state still points at the same case",
                )
            case_temps = [
                path
                for path in temps
                if current_case_id in path.name and f"repetition-{current_rep:03d}" in str(path)
            ]
            if case_temps:
                for path in case_temps:
                    if path.name.startswith(_TEMP_PREFIX):
                        path.unlink()
                return CaptureRecoveryReport(
                    classification="C",
                    session_id=session_id,
                    recoverable_forward=False,
                    capture=None,
                    detail="temporary capture exists only; not accepted",
                )
        return CaptureRecoveryReport(
            classification="A",
            session_id=session_id,
            recoverable_forward=False,
            capture=None,
            detail="capture absent and state says not captured",
        )

    def apply_verified_forward_capture(self, session_id: str) -> SessionState:
        """Mid-repetition class-B helper: increment ordinal and counts only.

        Completion at ordinal 73 (repetition flag, export hash, REPETITION_COMPLETE
        / COMPLETE, terminal receipt) is owned by RemoteEvalService.
        """
        report = self.inspect_capture_recovery(session_id)
        if report.classification != "B" or report.capture is None:
            raise RemoteEvalError(
                ERROR_STATE_INTEGRITY_FAILURE,
                "capture is not a verified forward recovery",
            )
        capture = report.capture
        if compute_capture_identity_sha256(capture) != capture.capture_identity_sha256:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture identity hash mismatch")
        state = self.load_state(session_id)
        if state is None:
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session not found")
        if (
            state.active_repetition != capture.repetition
            or state.next_case_ordinal != capture.ordinal
        ):
            raise RemoteEvalError(
                ERROR_STATE_INTEGRITY_FAILURE,
                "state no longer points at capture",
            )
        updated_progress = tuple(
            replace(
                item,
                next_case_ordinal=capture.ordinal + 1,
                captures_accepted=item.captures_accepted + 1,
            )
            if item.repetition == capture.repetition
            else item
            for item in state.repetitions
        )
        next_state = replace(
            state,
            revision=state.revision + 1,
            next_case_ordinal=capture.ordinal + 1,
            active_lease=None,
            repetitions=updated_progress,
            captures_accepted=state.captures_accepted + 1,
        )
        self.save_state(next_state)
        return next_state

    def export_repetition_documents(self, session_id: str, repetition: int) -> dict[str, object]:
        captures = self.list_captures(session_id, repetition)
        payload: dict[str, object] = {
            "documents": [_interchange_document(item) for item in captures],
            "schema_version": CAPTURE_SCHEMA_VERSION,
        }
        encoded = json.dumps(payload)
        for key in _FORBIDDEN_EXPORT_KEYS:
            if f'"{key}"' in encoded:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "export contains forbidden keys")
        return payload

    def write_repetition_export(self, session_id: str, repetition: int) -> Path:
        session_dir = session_directory(self._state_root, session_id)
        dest = session_dir / "captures" / f"repetition-{repetition:03d}.capture.json"
        atomic_write_json(dest, self.export_repetition_documents(session_id, repetition))
        return dest

    def write_canonical_export_dir(self, session_id: str, dest_dir: Path) -> tuple[Path, ...]:
        reject_symlink(dest_dir, what="export directory")
        mkdir_private(dest_dir)
        written: list[Path] = []
        state = self.load_state(session_id)
        if state is None:
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session not found")
        for progress in state.repetitions:
            captures = self.list_captures(session_id, progress.repetition)
            if len(captures) != CASES_PER_REPETITION:
                continue
            dest = dest_dir / f"repetition-{progress.repetition:03d}.json"
            atomic_write_json(
                dest, self.export_repetition_documents(session_id, progress.repetition)
            )
            written.append(dest)
        return tuple(written)

    def remove_staged_rasters(self, session_id: str) -> None:
        session_dir = session_directory(self._state_root, session_id)
        if not session_dir.is_dir():
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session directory missing")
        rasters = session_dir / "rasters"
        reject_symlink(rasters, what="rasters directory")
        if not rasters.exists():
            return
        if not rasters.is_dir():
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "rasters path is not a directory")
        _rmtree_private(rasters)
