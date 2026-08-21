"""Append-only crash-safe GSQS B0 disclosure journal."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

JOURNAL_FILENAME = "disclosure_journal.jsonl"
JOURNAL_SCHEMA_VERSION = "gsqs-b0-disclosure-journal-v1"
EVENT_STARTED = "OUTBOUND_ATTEMPT_STARTED"
EVENT_RECONCILED = "ATTEMPT_RECONCILED"
EVENT_RUN_PREPARED = "RUN_PREPARED"
EVENT_AUTH_PROBE_COMPLETED = "AUTH_PROBE_COMPLETED"
EVENT_RUN_ABORTED = "RUN_ABORTED"
EVENT_RUN_INVALID = "RUN_INVALID"
EVENT_RUN_COMPLETE = "RUN_COMPLETE"
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


class DisclosureState(StrEnum):
    NONE = "NONE"
    AUTHORIZED_NOT_YET_DISCLOSED = "AUTHORIZED_NOT_YET_DISCLOSED"
    MAY_HAVE_OCCURRED = "MAY_HAVE_OCCURRED"
    CONFIRMED_DISCLOSED = "CONFIRMED_DISCLOSED"
    CONFIRMED_NOT_DISCLOSED = "CONFIRMED_NOT_DISCLOSED"
    INVALID = "INVALID"
    ABORTED = "ABORTED"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class JournalFold:
    external_model_disclosure: DisclosureState
    started_count: int
    confirmed_disclosed_count: int
    indeterminate_count: int
    unresolved_attempt_ids: tuple[str, ...]
    selected_model_states: tuple[str, ...]


class DisclosureJournal:
    """One append-only JSONL file. STARTED is never rewritten."""

    def __init__(self, directory: Path, *, run_id: str) -> None:
        if not run_id or "/" in run_id or "\x00" in run_id:
            raise ValueError("run_id is invalid")
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory.chmod(0o700)
        self.directory = directory
        self.run_id = run_id
        self.path = directory / JOURNAL_FILENAME
        if not self.path.exists():
            descriptor = os.open(self.path, os.O_CREAT | os.O_RDONLY, 0o600)
            os.close(descriptor)
            self.path.chmod(0o600)
            self._sync_directory()

    def refuse_if_unresolved(self) -> None:
        fold = self.fold()
        if fold.unresolved_attempt_ids:
            raise ValueError("unresolved disclosure attempt; refusing to resume")

    def record_started(
        self,
        *,
        repetition: int,
        case_id: str,
        raster_sha256: str,
    ) -> str:
        attempt_id = str(uuid.uuid4())
        self._append(
            {
                "case_id": case_id,
                "disclosure_state": DisclosureState.MAY_HAVE_OCCURRED.value,
                "endpoint_path": "/v1/chat/completions",
                "event_type": EVENT_STARTED,
                "journal_schema_version": JOURNAL_SCHEMA_VERSION,
                "raster_sha256": raster_sha256,
                "recorded_at": _now(),
                "repetition": repetition,
                "request_attempt_id": attempt_id,
                "router_model_id": "route-llm",
                "run_id": self.run_id,
            }
        )
        return attempt_id

    def record_reconciled(
        self,
        *,
        request_attempt_id: str,
        repetition: int,
        case_id: str,
        raster_sha256: str,
        disclosure_state: DisclosureState,
        http_status: int | None = None,
        error_class: str | None = None,
        selected_model_observation: str | None = None,
        selected_model_class: str | None = None,
    ) -> None:
        if disclosure_state in {DisclosureState.NONE, DisclosureState.CONFIRMED_NOT_DISCLOSED}:
            raise ValueError("STARTED attempts cannot reconcile to NONE or CONFIRMED_NOT_DISCLOSED")
        payload: dict[str, object] = {
            "case_id": case_id,
            "disclosure_state": disclosure_state.value,
            "error_class": error_class,
            "event_type": EVENT_RECONCILED,
            "http_status": http_status,
            "journal_schema_version": JOURNAL_SCHEMA_VERSION,
            "raster_sha256": raster_sha256,
            "recorded_at": _now(),
            "repetition": repetition,
            "request_attempt_id": request_attempt_id,
            "run_id": self.run_id,
            "selected_model_class": selected_model_class,
            "selected_model_observation": selected_model_observation,
        }
        self._append(payload)

    def record_run_event(self, event_type: str, *, disclosure_state: DisclosureState) -> None:
        self._append(
            {
                "disclosure_state": disclosure_state.value,
                "event_type": event_type,
                "journal_schema_version": JOURNAL_SCHEMA_VERSION,
                "recorded_at": _now(),
                "run_id": self.run_id,
            }
        )

    def fold(self) -> JournalFold:
        events = self._read_events()
        started: dict[str, dict[str, object]] = {}
        reconciled: dict[str, dict[str, object]] = {}
        selected: list[str] = []
        for event in events:
            kind = event.get("event_type")
            attempt = event.get("request_attempt_id")
            if kind == EVENT_STARTED and isinstance(attempt, str):
                started[attempt] = event
            elif kind == EVENT_RECONCILED and isinstance(attempt, str):
                reconciled[attempt] = event
                observed = event.get("selected_model_class")
                if isinstance(observed, str) and observed:
                    selected.append(observed)
        unresolved = tuple(attempt for attempt in started if attempt not in reconciled)
        confirmed = 0
        indeterminate = 0
        for attempt in started:
            later = reconciled.get(attempt)
            if later is None:
                indeterminate += 1
                continue
            state = later.get("disclosure_state")
            if state == DisclosureState.CONFIRMED_DISCLOSED.value:
                confirmed += 1
            elif state == DisclosureState.MAY_HAVE_OCCURRED.value:
                indeterminate += 1
            else:
                indeterminate += 1
        if unresolved or indeterminate:
            disclosure = DisclosureState.MAY_HAVE_OCCURRED
        elif any(event.get("event_type") == EVENT_RUN_INVALID for event in events):
            disclosure = DisclosureState.INVALID
        elif any(event.get("event_type") == EVENT_RUN_ABORTED for event in events):
            disclosure = DisclosureState.ABORTED
        elif any(event.get("event_type") == EVENT_RUN_COMPLETE for event in events) and confirmed:
            disclosure = DisclosureState.COMPLETE
        elif confirmed:
            disclosure = DisclosureState.CONFIRMED_DISCLOSED
        elif any(event.get("event_type") == EVENT_AUTH_PROBE_COMPLETED for event in events):
            disclosure = DisclosureState.AUTHORIZED_NOT_YET_DISCLOSED
        else:
            disclosure = DisclosureState.NONE
        return JournalFold(
            external_model_disclosure=disclosure,
            started_count=len(started),
            confirmed_disclosed_count=confirmed,
            indeterminate_count=indeterminate,
            unresolved_attempt_ids=unresolved,
            selected_model_states=tuple(selected),
        )

    def public_control_fields(self) -> dict[str, object]:
        fold = self.fold()
        return {
            "EXTERNAL_MODEL_DISCLOSURE": fold.external_model_disclosure.value,
            "confirmed_disclosed_count": fold.confirmed_disclosed_count,
            "disclosure_would_occur": fold.started_count > 0,
            "indeterminate_request_count": fold.indeterminate_count,
            "started_request_count": fold.started_count,
        }

    def _append(self, payload: Mapping[str, object]) -> None:
        if _FORBIDDEN_EVENT_KEYS & set(payload):
            raise ValueError("journal event contains forbidden keys")
        line = json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n"
        descriptor = os.open(self.path, os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, line.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.path.chmod(0o600)
        self._sync_directory()

    def _read_events(self) -> list[dict[str, object]]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        events: list[dict[str, object]] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("journal line is not an object")
            events.append(parsed)
        return events

    def _sync_directory(self) -> None:
        descriptor = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _now() -> str:
    return datetime.now(UTC).isoformat()
