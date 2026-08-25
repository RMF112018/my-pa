"""Filesystem JSONL v2 disclosure journal for GSQS ChatLLM remote evaluation.

Implements ``DisclosurePort``. ``OUTBOUND_ATTEMPT_STARTED`` is append-fsynced
(and the journal directory is fsynced) before ``start_outbound_attempt``
returns, so it is durable before any later transport callback.

``journal_sha256`` is the SHA-256 of the raw journal file bytes (lowercase hex).
It is not a canonical-event digest. An empty missing journal yields ``None``.

A STARTED event without a later ``DISCLOSED_TO_TRANSPORT`` or ``NOT_DISCLOSED``
for that ``request_attempt_id`` is UNCERTAIN. This module never infers
``NOT_DISCLOSED`` from a crash. ``confirm_not_disclosed`` is the explicit
pre-send abort path only.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_INTERNAL_FAIL_CLOSED,
    EVENT_DISCLOSED_TO_TRANSPORT,
    EVENT_NOT_DISCLOSED,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    SCHEMA_DISCLOSURE_JOURNAL_V2,
    Clock,
    DisclosurePort,
    DisclosureReconcileReport,
    RemoteEvalError,
    remote_eval_canonical_dumps,
    require_sha256_hex,
)
from my_pa.domain.common.time import NaiveDatetimeError, format_rfc3339

JOURNAL_FILENAME = "disclosure.jsonl"
_FORBIDDEN_EVENT_KEYS = frozenset(
    {
        "authorization",
        "data_uri",
        "gold",
        "image",
        "image_bytes",
        "path",
        "raster_path",
        "secret",
        "transcription",
    }
)
_TERMINAL_EVENTS = frozenset({EVENT_DISCLOSED_TO_TRANSPORT, EVENT_NOT_DISCLOSED})


@dataclass(frozen=True, slots=True)
class _JournalPaths:
    sessions_dir: Path
    session_dir: Path
    journal_dir: Path
    journal_file: Path


class FilesystemDisclosureJournal:
    """Append-only v2 disclosure journal under ``state_root/sessions/<id>/journal``."""

    def __init__(self, state_root: Path, *, clock: Clock) -> None:
        self._state_root = Path(state_root)
        self._clock = clock

    def start_outbound_attempt(
        self,
        *,
        session_id: str,
        repetition: int,
        case_id: str,
        content_sha256: str,
    ) -> str:
        require_sha256_hex(content_sha256, what="content_sha256")
        if not case_id or not isinstance(repetition, int):
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "outbound attempt fields are invalid")
        attempt_id = str(uuid.uuid4())
        self._append(
            self._ensure_journal(session_id),
            {
                "case_id": case_id,
                "content_sha256": content_sha256,
                "event_type": EVENT_OUTBOUND_ATTEMPT_STARTED,
                "journal_schema_version": SCHEMA_DISCLOSURE_JOURNAL_V2,
                "recorded_at": self._recorded_at(),
                "repetition": repetition,
                "request_attempt_id": attempt_id,
                "session_id": session_id,
            },
        )
        return attempt_id

    def confirm_disclosed_to_transport(self, *, session_id: str, attempt_id: str) -> None:
        self._confirm_terminal(
            session_id=session_id,
            attempt_id=attempt_id,
            event_type=EVENT_DISCLOSED_TO_TRANSPORT,
        )

    def confirm_not_disclosed(self, *, session_id: str, attempt_id: str) -> None:
        self._confirm_terminal(
            session_id=session_id,
            attempt_id=attempt_id,
            event_type=EVENT_NOT_DISCLOSED,
        )

    def reconcile_on_restart(self, *, session_id: str) -> DisclosureReconcileReport:
        paths = self._paths(session_id)
        self._refuse_symlinks(paths)
        if not paths.journal_file.exists():
            return DisclosureReconcileReport(
                uncertain=False,
                journal_sha256=None,
                started_count=0,
                disclosed_count=0,
                not_disclosed_count=0,
            )
        events, digest = self._read_events(paths.journal_file)
        started: dict[str, dict[str, object]] = {}
        disclosed: set[str] = set()
        not_disclosed: set[str] = set()
        for event in events:
            if event.get("session_id") != session_id:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal session_id mismatch")
            kind = event.get("event_type")
            attempt = event.get("request_attempt_id")
            if not isinstance(attempt, str) or not attempt:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal attempt_id is invalid")
            if kind == EVENT_OUTBOUND_ATTEMPT_STARTED:
                started[attempt] = event
            elif kind == EVENT_DISCLOSED_TO_TRANSPORT:
                disclosed.add(attempt)
            elif kind == EVENT_NOT_DISCLOSED:
                not_disclosed.add(attempt)
            else:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal event_type is unknown")
        unresolved = any(
            attempt not in disclosed and attempt not in not_disclosed for attempt in started
        )
        return DisclosureReconcileReport(
            uncertain=unresolved,
            journal_sha256=digest,
            started_count=len(started),
            disclosed_count=len(disclosed),
            not_disclosed_count=len(not_disclosed),
        )

    def _confirm_terminal(self, *, session_id: str, attempt_id: str, event_type: str) -> None:
        if not attempt_id:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "attempt is missing")
        paths = self._paths(session_id)
        self._refuse_symlinks(paths)
        if not paths.journal_file.exists():
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "attempt is missing")
        events, _digest = self._read_events(paths.journal_file)
        started = self._require_open_attempt(events, session_id=session_id, attempt_id=attempt_id)
        payload: dict[str, object] = {
            "case_id": started["case_id"],
            "event_type": event_type,
            "journal_schema_version": SCHEMA_DISCLOSURE_JOURNAL_V2,
            "recorded_at": self._recorded_at(),
            "repetition": started["repetition"],
            "request_attempt_id": attempt_id,
            "session_id": session_id,
        }
        content = started.get("content_sha256")
        if isinstance(content, str) and content:
            payload["content_sha256"] = content
        self._append(paths.journal_file, payload)

    def _require_open_attempt(
        self,
        events: list[dict[str, object]],
        *,
        session_id: str,
        attempt_id: str,
    ) -> dict[str, object]:
        started: dict[str, object] | None = None
        terminal = False
        for event in events:
            if event.get("request_attempt_id") != attempt_id:
                continue
            if event.get("session_id") != session_id:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "attempt session mismatch")
            kind = event.get("event_type")
            if kind == EVENT_OUTBOUND_ATTEMPT_STARTED:
                started = event
            elif kind in _TERMINAL_EVENTS:
                terminal = True
        if started is None:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "attempt is missing")
        if terminal:
            raise RemoteEvalError(
                ERROR_INTERNAL_FAIL_CLOSED, "attempt already has a terminal event"
            )
        return started

    def _recorded_at(self) -> str:
        try:
            return format_rfc3339(self._clock.now())
        except NaiveDatetimeError as exc:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "clock must return UTC") from exc

    def _paths(self, session_id: str) -> _JournalPaths:
        self._validate_session_id(session_id)
        sessions_dir = self._state_root / "sessions"
        session_dir = sessions_dir / session_id
        journal_dir = session_dir / "journal"
        journal_file = journal_dir / JOURNAL_FILENAME
        self._assert_contained(sessions_dir, journal_file)
        return _JournalPaths(
            sessions_dir=sessions_dir,
            session_dir=session_dir,
            journal_dir=journal_dir,
            journal_file=journal_file,
        )

    def _ensure_journal(self, session_id: str) -> Path:
        paths = self._paths(session_id)
        self._refuse_symlinks(paths)
        for directory in (paths.sessions_dir, paths.session_dir, paths.journal_dir):
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink():
                raise RemoteEvalError(
                    ERROR_INTERNAL_FAIL_CLOSED, "journal path must not be a symlink"
                )
            directory.chmod(0o700)
            self._sync_directory(directory)
        self._refuse_symlinks(paths)
        self._assert_contained(paths.sessions_dir, paths.journal_file)
        if not paths.journal_file.exists():
            descriptor = os.open(paths.journal_file, os.O_CREAT | os.O_RDONLY, 0o600)
            os.close(descriptor)
            paths.journal_file.chmod(0o600)
            self._sync_directory(paths.journal_dir)
        else:
            paths.journal_file.chmod(0o600)
        return paths.journal_file

    def _append(self, path: Path, payload: Mapping[str, object]) -> None:
        if path.is_symlink():
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal path must not be a symlink")
        if _FORBIDDEN_EVENT_KEYS & set(payload):
            raise RemoteEvalError(
                ERROR_INTERNAL_FAIL_CLOSED, "journal event contains forbidden keys"
            )
        line = remote_eval_canonical_dumps(dict(payload)) + "\n"
        descriptor = os.open(path, os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        path.chmod(0o600)
        self._sync_directory(path.parent)

    def _read_events(self, path: Path) -> tuple[list[dict[str, object]], str]:
        if path.is_symlink():
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal path must not be a symlink")
        raw = path.read_bytes() if path.exists() else b""
        digest = sha256(raw).hexdigest()
        events: list[dict[str, object]] = []
        if not raw:
            return events, digest
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal is not UTF-8") from exc
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RemoteEvalError(
                    ERROR_INTERNAL_FAIL_CLOSED, "journal line is not JSON"
                ) from exc
            if not isinstance(parsed, dict):
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "journal line is not an object")
            if _FORBIDDEN_EVENT_KEYS & set(parsed):
                raise RemoteEvalError(
                    ERROR_INTERNAL_FAIL_CLOSED, "journal event contains forbidden keys"
                )
            events.append(parsed)
        return events, digest

    def _sync_directory(self, directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _validate_session_id(self, session_id: str) -> None:
        if not session_id or "/" in session_id or "\x00" in session_id or ".." in session_id:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session_id is invalid")

    def _refuse_symlinks(self, paths: _JournalPaths) -> None:
        for candidate in (
            paths.sessions_dir,
            paths.session_dir,
            paths.journal_dir,
            paths.journal_file,
        ):
            if candidate.exists() and candidate.is_symlink():
                raise RemoteEvalError(
                    ERROR_INTERNAL_FAIL_CLOSED, "journal path must not be a symlink"
                )

    def _assert_contained(self, sessions_dir: Path, journal_file: Path) -> None:
        sessions_resolved = sessions_dir.resolve()
        file_resolved = journal_file.resolve()
        if not file_resolved.is_relative_to(sessions_resolved):
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session_id is invalid")


def wrap_transport[T](
    journal: DisclosurePort,
    session_id: str,
    repetition: int,
    case_id: str,
    content_sha256: str,
    callback: Callable[[], T],
) -> T:
    """Write STARTED, invoke ``callback``, then confirm disclosure on success.

    Callback exceptions are re-raised without writing ``NOT_DISCLOSED``. A failed
    or interrupted send after STARTED stays UNCERTAIN. Pre-send abort must call
    ``confirm_not_disclosed`` explicitly.
    """

    attempt_id = journal.start_outbound_attempt(
        session_id=session_id,
        repetition=repetition,
        case_id=case_id,
        content_sha256=content_sha256,
    )
    try:
        result = callback()
    except Exception:
        raise
    else:
        journal.confirm_disclosed_to_transport(session_id=session_id, attempt_id=attempt_id)
        return result


__all__ = ["JOURNAL_FILENAME", "FilesystemDisclosureJournal", "wrap_transport"]
