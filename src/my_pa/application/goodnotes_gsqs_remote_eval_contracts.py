"""Contracts for the GSQS ChatLLM remote-evaluation session (Phase A).

Transport, OAuth, MCP, PNG staging, and durable disclosure journaling are out
of scope. Identity hashing uses a dedicated canonical dump (UTF-8,
``ensure_ascii=False``); it does not call or alter ``canonical_dumps`` in
``goodnotes_gsqs_corpus``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from my_pa.domain.common.time import format_rfc3339

SCHEMA_SESSION_V1 = "gsqs-remote-eval-session-v1"
SCHEMA_SESSION_MANIFEST_V1 = "gsqs-remote-eval-session-manifest-v1"
SCHEMA_STATE_V1 = "gsqs-remote-eval-state-v1"
SCHEMA_EVALUATION_CASE_STATE_V1 = "gsqs-remote-eval-case-state-v1"
SCHEMA_DISCLOSURE_JOURNAL_V2 = "gsqs-b0-disclosure-journal-v2"
SCHEMA_CAPTURE_ENTRY_V1 = "gsqs-remote-eval-capture-entry-v1"
SCHEMA_TERMINAL_RECEIPT_V1 = "gsqs-remote-eval-terminal-receipt-v1"

EVENT_OUTBOUND_ATTEMPT_STARTED = "OUTBOUND_ATTEMPT_STARTED"
EVENT_DISCLOSED_TO_TRANSPORT = "DISCLOSED_TO_TRANSPORT"
EVENT_NOT_DISCLOSED = "NOT_DISCLOSED"

PARTITION = "B"
CASES_PER_REPETITION = 73
REPETITIONS_REQUIRED = 3
# 900s failed a ChatLLM visual next-to-submit of ~1097s. Default 3600s
# covers that observed latency with bound headroom; settings may vary it.
MIN_LEASE_DURATION_SECONDS = 900
LEASE_DURATION_SECONDS = 3600
MAX_LEASE_DURATION_SECONDS = 7200
MAX_CAPTURE_SEGMENTS_BYTES = 1_048_576

ERROR_EVAL_DISABLED = "EVAL_DISABLED"
ERROR_UNAUTHENTICATED = "UNAUTHENTICATED"
ERROR_FORBIDDEN_SCOPE = "FORBIDDEN_SCOPE"
ERROR_NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
ERROR_SESSION_EXPIRED = "SESSION_EXPIRED"
ERROR_SESSION_BLOCKED = "SESSION_BLOCKED"
ERROR_SESSION_NOT_IN_PROGRESS = "SESSION_NOT_IN_PROGRESS"
ERROR_INVALID_TRANSITION = "INVALID_TRANSITION"
ERROR_LEASE_CONFLICT = "LEASE_CONFLICT"
ERROR_LEASE_EXPIRED = "LEASE_EXPIRED"
ERROR_INVALID_ANALYZER_OUTPUT = "INVALID_ANALYZER_OUTPUT"
ERROR_CAPTURE_CONFLICT = "CAPTURE_CONFLICT"
ERROR_RASTER_INTEGRITY_FAILURE = "RASTER_INTEGRITY_FAILURE"
ERROR_DISCLOSURE_UNCERTAIN = "DISCLOSURE_UNCERTAIN"
ERROR_RESULT_TOO_LARGE = "RESULT_TOO_LARGE"
ERROR_STATE_INTEGRITY_FAILURE = "STATE_INTEGRITY_FAILURE"
ERROR_INTERNAL_FAIL_CLOSED = "INTERNAL_FAIL_CLOSED"

REMOTE_EVAL_ERROR_CODES = frozenset(
    {
        ERROR_EVAL_DISABLED,
        ERROR_UNAUTHENTICATED,
        ERROR_FORBIDDEN_SCOPE,
        ERROR_NO_ACTIVE_SESSION,
        ERROR_SESSION_EXPIRED,
        ERROR_SESSION_BLOCKED,
        ERROR_SESSION_NOT_IN_PROGRESS,
        ERROR_INVALID_TRANSITION,
        ERROR_LEASE_CONFLICT,
        ERROR_LEASE_EXPIRED,
        ERROR_INVALID_ANALYZER_OUTPUT,
        ERROR_CAPTURE_CONFLICT,
        ERROR_RASTER_INTEGRITY_FAILURE,
        ERROR_DISCLOSURE_UNCERTAIN,
        ERROR_RESULT_TOO_LARGE,
        ERROR_STATE_INTEGRITY_FAILURE,
        ERROR_INTERNAL_FAIL_CLOSED,
    }
)

MANIFEST_FORBIDDEN_KEYS = frozenset(
    {
        "diagnostics",
        "expected",
        "expected_result",
        "gold",
        "label",
        "label_sha256",
        "path",
        "private_gold",
        "private_label",
        "private_label_sha256",
        "source_path",
    }
)

_SHA256_HEX = frozenset("0123456789abcdef")


class RemoteEvalError(ValueError):
    """Fail-closed remote-eval error with a stable ``code`` for CLI ``ValueError`` handlers."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class RemoteEvalMode(StrEnum):
    SYNTHETIC_CANARY = "SYNTHETIC_CANARY"
    PHASE_C = "PHASE_C"


class RemoteEvalSessionState(StrEnum):
    PREPARED = "PREPARED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    REPETITION_COMPLETE = "REPETITION_COMPLETE"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"
    ABORTED = "ABORTED"
    EXPIRED = "EXPIRED"


class CaseDisposition(StrEnum):
    PENDING = "PENDING"
    LEASED = "LEASED"
    CAPTURED = "CAPTURED"


TERMINAL_STATES = frozenset(
    {
        RemoteEvalSessionState.COMPLETE,
        RemoteEvalSessionState.BLOCKED,
        RemoteEvalSessionState.ABORTED,
        RemoteEvalSessionState.EXPIRED,
    }
)

# Occupies the control plane so a new session cannot be created. REPETITION_COMPLETE
# is parked (waiting for an explicit later repetition) and does not occupy.
OCCUPYING_STATES = frozenset(
    {
        RemoteEvalSessionState.PREPARED,
        RemoteEvalSessionState.READY,
        RemoteEvalSessionState.IN_PROGRESS,
    }
)

LEGAL_TRANSITIONS: dict[RemoteEvalSessionState, frozenset[RemoteEvalSessionState]] = {
    RemoteEvalSessionState.PREPARED: frozenset(
        {
            RemoteEvalSessionState.READY,
            RemoteEvalSessionState.BLOCKED,
            RemoteEvalSessionState.ABORTED,
            RemoteEvalSessionState.EXPIRED,
        }
    ),
    RemoteEvalSessionState.READY: frozenset(
        {
            RemoteEvalSessionState.IN_PROGRESS,
            RemoteEvalSessionState.BLOCKED,
            RemoteEvalSessionState.ABORTED,
            RemoteEvalSessionState.EXPIRED,
        }
    ),
    RemoteEvalSessionState.IN_PROGRESS: frozenset(
        {
            RemoteEvalSessionState.REPETITION_COMPLETE,
            RemoteEvalSessionState.COMPLETE,
            RemoteEvalSessionState.BLOCKED,
            RemoteEvalSessionState.ABORTED,
            RemoteEvalSessionState.EXPIRED,
        }
    ),
    RemoteEvalSessionState.REPETITION_COMPLETE: frozenset(
        {
            RemoteEvalSessionState.IN_PROGRESS,
            RemoteEvalSessionState.BLOCKED,
            RemoteEvalSessionState.ABORTED,
            RemoteEvalSessionState.EXPIRED,
        }
    ),
    RemoteEvalSessionState.COMPLETE: frozenset(),
    RemoteEvalSessionState.BLOCKED: frozenset(),
    RemoteEvalSessionState.ABORTED: frozenset(),
    RemoteEvalSessionState.EXPIRED: frozenset(),
}


def validate_remote_eval_transition(
    current: RemoteEvalSessionState,
    target: RemoteEvalSessionState,
) -> None:
    """Central transition validator. Terminal states do not leave."""

    allowed = LEGAL_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise RemoteEvalError(
            ERROR_INVALID_TRANSITION,
            f"illegal transition {current} -> {target}",
        )


def remote_eval_canonical_dumps(value: object) -> str:
    """UTF-8 canonical JSON: sorted keys, compact separators, ``ensure_ascii=False``."""

    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def remote_eval_canonical_sha256(value: object) -> str:
    return sha256(remote_eval_canonical_dumps(value).encode("utf-8")).hexdigest()


def require_sha256_hex(value: str, *, what: str) -> str:
    if len(value) != 64 or any(ch not in _SHA256_HEX for ch in value):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, f"invalid {what}")
    return value


def case_order_sha256(case_ids: Sequence[str]) -> str:
    return remote_eval_canonical_sha256(list(case_ids))


@dataclass(frozen=True, slots=True)
class RemoteEvalSession:
    schema_version: str
    session_id: str
    mode: RemoteEvalMode
    authorization_id: str
    principal_id: str
    created_at: datetime
    expires_at: datetime
    repository_owner: str
    repository_name: str
    repository_commit_sha: str
    repository_tree_sha: str
    evaluator_id: str
    evaluator_version: str
    evaluator_behavior_sha256: str
    corpus_version: str
    public_manifest_sha256: str
    combined_identity_sha256: str
    partition: str
    case_count: int
    case_order_sha256: str
    analyzer_id: str
    analyzer_version: str
    semantic_prompt_sha256: str
    conversation_prompt_sha256: str
    model_selection_label: str
    repetitions_required: int
    session_identity_sha256: str


@dataclass(frozen=True, slots=True)
class ManifestCase:
    ordinal: int
    case_id: str
    content_sha256: str
    byte_length: int
    staged_filename: str


@dataclass(frozen=True, slots=True)
class SessionManifest:
    schema_version: str
    session_id: str
    session_identity_sha256: str
    cases: tuple[ManifestCase, ...]


@dataclass(frozen=True, slots=True)
class Lease:
    lease_id: str
    case_id: str
    ordinal: int
    repetition: int
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RepetitionProgress:
    repetition: int
    opened: bool
    completed: bool
    next_case_ordinal: int
    captures_accepted: int
    capture_export_sha256: str | None


@dataclass(frozen=True, slots=True)
class SessionState:
    schema_version: str
    session_id: str
    revision: int
    state: RemoteEvalSessionState
    active_repetition: int | None
    next_case_ordinal: int
    active_lease: Lease | None
    repetitions: tuple[RepetitionProgress, ...]
    captures_accepted: int
    capture_export_sha256: str | None
    last_event_id: str | None
    updated_at: datetime
    blocked_reason_code: str | None
    terminal_reason_code: str | None


@dataclass(frozen=True, slots=True)
class EvaluationCaseState:
    schema_version: str
    ordinal: int
    case_id: str
    content_sha256: str
    disposition: CaseDisposition
    active_lease: Lease | None
    capture_identity_sha256: str | None


@dataclass(frozen=True, slots=True)
class CaptureEntry:
    schema_version: str
    session_id: str
    session_identity_sha256: str
    repetition: int
    case_id: str
    ordinal: int
    content_sha256: str
    corpus_version: str
    public_manifest_sha256: str
    combined_identity_sha256: str
    analyzer_id: str
    analyzer_version: str
    semantic_prompt_sha256: str
    conversation_prompt_sha256: str
    model_selection_label: str
    captured_at: datetime
    lease_id: str
    idempotency_digest: str
    segments: tuple[dict[str, object], ...]
    capture_identity_sha256: str


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    session_id: str
    repetition: int
    case_id: str
    ordinal: int
    capture_identity_sha256: str
    idempotency_digest: str
    duplicate: bool
    state: RemoteEvalSessionState


@dataclass(frozen=True, slots=True)
class TerminalReceipt:
    schema_version: str
    session_id: str
    session_identity_sha256: str
    terminal_state: RemoteEvalSessionState
    terminal_at: datetime
    manifest_sha256: str
    final_state_sha256: str
    disclosure_journal_sha256: str | None
    disclosure_counts: Mapping[str, int]
    repetition_capture_exports: tuple[tuple[int, str | None], ...]
    total_captures: int
    cleanup_retention: Mapping[str, object]
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class SessionStatus:
    session_id: str
    mode: RemoteEvalMode
    state: RemoteEvalSessionState
    session_identity_sha256: str
    active_repetition: int | None
    next_case_ordinal: int
    captures_accepted: int
    case_count: int
    repetitions_required: int
    expires_at: datetime
    blocked_reason_code: str | None
    terminal_reason_code: str | None


@dataclass(frozen=True, slots=True)
class AcquiredCase:
    lease: Lease
    ordinal: int
    case_id: str
    content_sha256: str
    byte_length: int
    staged_filename: str
    repetition: int


@dataclass(frozen=True, slots=True)
class RemoteEvalCreateRequest:
    session_id: str
    mode: RemoteEvalMode
    authorization_id: str
    principal_id: str
    expires_at: datetime
    repository_owner: str
    repository_name: str
    repository_commit_sha: str
    repository_tree_sha: str
    evaluator_id: str
    evaluator_version: str
    evaluator_behavior_sha256: str
    corpus_version: str
    public_manifest_sha256: str
    combined_identity_sha256: str
    analyzer_id: str
    analyzer_version: str
    semantic_prompt_sha256: str
    conversation_prompt_sha256: str
    model_selection_label: str
    cases: tuple[ManifestCase, ...]


@dataclass(frozen=True, slots=True)
class StagingSealResult:
    ok: bool
    manifest: SessionManifest
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class DisclosureReconcileReport:
    uncertain: bool
    journal_sha256: str | None
    started_count: int
    disclosed_count: int
    not_disclosed_count: int


class Clock(Protocol):
    def now(self) -> datetime: ...


class StagingPort(Protocol):
    def seal_authorized_rasters(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
    ) -> StagingSealResult: ...


class DisclosurePort(Protocol):
    def start_outbound_attempt(
        self,
        *,
        session_id: str,
        repetition: int,
        case_id: str,
        content_sha256: str,
    ) -> str: ...

    def confirm_disclosed_to_transport(self, *, session_id: str, attempt_id: str) -> None: ...

    def confirm_not_disclosed(self, *, session_id: str, attempt_id: str) -> None: ...

    def reconcile_on_restart(self, *, session_id: str) -> DisclosureReconcileReport: ...


class RemoteEvalStore(Protocol):
    def create_session(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> None: ...

    def load_session(self, session_id: str) -> RemoteEvalSession | None: ...

    def load_manifest(self, session_id: str) -> SessionManifest | None: ...

    def load_state(self, session_id: str) -> SessionState | None: ...

    def save_state(self, state: SessionState) -> None: ...

    def save_manifest(self, manifest: SessionManifest) -> None: ...

    def commit_capture(
        self,
        *,
        state: SessionState,
        capture: CaptureEntry,
        terminal_receipt: TerminalReceipt | None = None,
    ) -> None: ...

    def load_capture(
        self, session_id: str, repetition: int, case_id: str
    ) -> CaptureEntry | None: ...

    def load_capture_by_lease(self, session_id: str, lease_id: str) -> CaptureEntry | None: ...

    def list_captures(self, session_id: str, repetition: int) -> tuple[CaptureEntry, ...]: ...

    def save_terminal_receipt(self, receipt: TerminalReceipt) -> None: ...

    def load_terminal_receipt(self, session_id: str) -> TerminalReceipt | None: ...

    def list_session_ids(self) -> tuple[str, ...]: ...

    def find_non_terminal_session_id(self) -> str | None: ...


def session_identity_payload(session: RemoteEvalSession) -> dict[str, object]:
    """Canonical identity dict. Excludes ``session_identity_sha256``."""

    return {
        "analyzer_id": session.analyzer_id,
        "analyzer_version": session.analyzer_version,
        "authorization_id": session.authorization_id,
        "case_count": session.case_count,
        "case_order_sha256": session.case_order_sha256,
        "combined_identity_sha256": session.combined_identity_sha256,
        "conversation_prompt_sha256": session.conversation_prompt_sha256,
        "corpus_version": session.corpus_version,
        "created_at": format_rfc3339(session.created_at),
        "evaluator_behavior_sha256": session.evaluator_behavior_sha256,
        "evaluator_id": session.evaluator_id,
        "evaluator_version": session.evaluator_version,
        "expires_at": format_rfc3339(session.expires_at),
        "mode": session.mode.value,
        "model_selection_label": session.model_selection_label,
        "partition": session.partition,
        "principal_id": session.principal_id,
        "public_manifest_sha256": session.public_manifest_sha256,
        "repetitions_required": session.repetitions_required,
        "repository_commit_sha": session.repository_commit_sha,
        "repository_name": session.repository_name,
        "repository_owner": session.repository_owner,
        "repository_tree_sha": session.repository_tree_sha,
        "schema_version": session.schema_version,
        "semantic_prompt_sha256": session.semantic_prompt_sha256,
        "session_id": session.session_id,
    }


def compute_session_identity_sha256(session: RemoteEvalSession) -> str:
    return remote_eval_canonical_sha256(session_identity_payload(session))


def build_remote_eval_session(
    *,
    session_id: str,
    mode: RemoteEvalMode,
    authorization_id: str,
    principal_id: str,
    created_at: datetime,
    expires_at: datetime,
    repository_owner: str,
    repository_name: str,
    repository_commit_sha: str,
    repository_tree_sha: str,
    evaluator_id: str,
    evaluator_version: str,
    evaluator_behavior_sha256: str,
    corpus_version: str,
    public_manifest_sha256: str,
    combined_identity_sha256: str,
    case_count: int,
    case_order_sha256: str,
    analyzer_id: str,
    analyzer_version: str,
    semantic_prompt_sha256: str,
    conversation_prompt_sha256: str,
    model_selection_label: str,
    partition: str = PARTITION,
    repetitions_required: int = REPETITIONS_REQUIRED,
    schema_version: str = SCHEMA_SESSION_V1,
) -> RemoteEvalSession:
    require_sha256_hex(evaluator_behavior_sha256, what="evaluator_behavior_sha256")
    require_sha256_hex(public_manifest_sha256, what="public_manifest_sha256")
    require_sha256_hex(combined_identity_sha256, what="combined_identity_sha256")
    require_sha256_hex(case_order_sha256, what="case_order_sha256")
    require_sha256_hex(semantic_prompt_sha256, what="semantic_prompt_sha256")
    require_sha256_hex(conversation_prompt_sha256, what="conversation_prompt_sha256")
    session = RemoteEvalSession(
        schema_version=schema_version,
        session_id=session_id,
        mode=mode,
        authorization_id=authorization_id,
        principal_id=principal_id,
        created_at=created_at,
        expires_at=expires_at,
        repository_owner=repository_owner,
        repository_name=repository_name,
        repository_commit_sha=repository_commit_sha,
        repository_tree_sha=repository_tree_sha,
        evaluator_id=evaluator_id,
        evaluator_version=evaluator_version,
        evaluator_behavior_sha256=evaluator_behavior_sha256,
        corpus_version=corpus_version,
        public_manifest_sha256=public_manifest_sha256,
        combined_identity_sha256=combined_identity_sha256,
        partition=partition,
        case_count=case_count,
        case_order_sha256=case_order_sha256,
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        semantic_prompt_sha256=semantic_prompt_sha256,
        conversation_prompt_sha256=conversation_prompt_sha256,
        model_selection_label=model_selection_label,
        repetitions_required=repetitions_required,
        session_identity_sha256="",
    )
    identity = compute_session_identity_sha256(session)
    return RemoteEvalSession(
        schema_version=session.schema_version,
        session_id=session.session_id,
        mode=session.mode,
        authorization_id=session.authorization_id,
        principal_id=session.principal_id,
        created_at=session.created_at,
        expires_at=session.expires_at,
        repository_owner=session.repository_owner,
        repository_name=session.repository_name,
        repository_commit_sha=session.repository_commit_sha,
        repository_tree_sha=session.repository_tree_sha,
        evaluator_id=session.evaluator_id,
        evaluator_version=session.evaluator_version,
        evaluator_behavior_sha256=session.evaluator_behavior_sha256,
        corpus_version=session.corpus_version,
        public_manifest_sha256=session.public_manifest_sha256,
        combined_identity_sha256=session.combined_identity_sha256,
        partition=session.partition,
        case_count=session.case_count,
        case_order_sha256=session.case_order_sha256,
        analyzer_id=session.analyzer_id,
        analyzer_version=session.analyzer_version,
        semantic_prompt_sha256=session.semantic_prompt_sha256,
        conversation_prompt_sha256=session.conversation_prompt_sha256,
        model_selection_label=session.model_selection_label,
        repetitions_required=session.repetitions_required,
        session_identity_sha256=identity,
    )


def manifest_public_dict(manifest: SessionManifest) -> dict[str, object]:
    return {
        "cases": [
            {
                "byte_length": case.byte_length,
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "ordinal": case.ordinal,
                "staged_filename": case.staged_filename,
            }
            for case in manifest.cases
        ],
        "schema_version": manifest.schema_version,
        "session_id": manifest.session_id,
        "session_identity_sha256": manifest.session_identity_sha256,
    }


def capture_identity_payload(entry: CaptureEntry) -> dict[str, object]:
    return {
        "analyzer_id": entry.analyzer_id,
        "analyzer_version": entry.analyzer_version,
        "captured_at": format_rfc3339(entry.captured_at),
        "case_id": entry.case_id,
        "combined_identity_sha256": entry.combined_identity_sha256,
        "content_sha256": entry.content_sha256,
        "conversation_prompt_sha256": entry.conversation_prompt_sha256,
        "corpus_version": entry.corpus_version,
        "idempotency_digest": entry.idempotency_digest,
        "lease_id": entry.lease_id,
        "model_selection_label": entry.model_selection_label,
        "ordinal": entry.ordinal,
        "public_manifest_sha256": entry.public_manifest_sha256,
        "repetition": entry.repetition,
        "schema_version": entry.schema_version,
        "semantic_prompt_sha256": entry.semantic_prompt_sha256,
        "segments": list(entry.segments),
        "session_id": entry.session_id,
        "session_identity_sha256": entry.session_identity_sha256,
    }


def compute_capture_identity_sha256(entry: CaptureEntry) -> str:
    return remote_eval_canonical_sha256(capture_identity_payload(entry))


def idempotency_digest(
    *,
    session_id: str,
    repetition: int,
    case_id: str,
    lease_id: str,
    segments: Sequence[Mapping[str, object]],
) -> str:
    return remote_eval_canonical_sha256(
        {
            "case_id": case_id,
            "lease_id": lease_id,
            "repetition": repetition,
            "segments": list(segments),
            "session_id": session_id,
        }
    )


def lease_payload(lease: Lease) -> dict[str, object]:
    return {
        "case_id": lease.case_id,
        "expires_at": format_rfc3339(lease.expires_at),
        "issued_at": format_rfc3339(lease.issued_at),
        "lease_id": lease.lease_id,
        "ordinal": lease.ordinal,
        "repetition": lease.repetition,
    }


def session_state_payload(state: SessionState) -> dict[str, object]:
    return {
        "active_lease": None if state.active_lease is None else lease_payload(state.active_lease),
        "active_repetition": state.active_repetition,
        "blocked_reason_code": state.blocked_reason_code,
        "capture_export_sha256": state.capture_export_sha256,
        "captures_accepted": state.captures_accepted,
        "last_event_id": state.last_event_id,
        "next_case_ordinal": state.next_case_ordinal,
        "repetitions": [
            {
                "capture_export_sha256": item.capture_export_sha256,
                "captures_accepted": item.captures_accepted,
                "completed": item.completed,
                "next_case_ordinal": item.next_case_ordinal,
                "opened": item.opened,
                "repetition": item.repetition,
            }
            for item in state.repetitions
        ],
        "revision": state.revision,
        "schema_version": state.schema_version,
        "session_id": state.session_id,
        "state": state.state.value,
        "terminal_reason_code": state.terminal_reason_code,
        "updated_at": format_rfc3339(state.updated_at),
    }


def compute_state_sha256(state: SessionState) -> str:
    return remote_eval_canonical_sha256(session_state_payload(state))


def compute_manifest_sha256(manifest: SessionManifest) -> str:
    return remote_eval_canonical_sha256(manifest_public_dict(manifest))


def terminal_receipt_payload(receipt: TerminalReceipt) -> dict[str, object]:
    return {
        "cleanup_retention": dict(receipt.cleanup_retention),
        "disclosure_counts": dict(receipt.disclosure_counts),
        "disclosure_journal_sha256": receipt.disclosure_journal_sha256,
        "final_state_sha256": receipt.final_state_sha256,
        "manifest_sha256": receipt.manifest_sha256,
        "repetition_capture_exports": [
            {"capture_export_sha256": item[1], "repetition": item[0]}
            for item in receipt.repetition_capture_exports
        ],
        "schema_version": receipt.schema_version,
        "session_id": receipt.session_id,
        "session_identity_sha256": receipt.session_identity_sha256,
        "terminal_at": format_rfc3339(receipt.terminal_at),
        "terminal_state": receipt.terminal_state.value,
        "total_captures": receipt.total_captures,
    }


def compute_receipt_sha256(receipt: TerminalReceipt) -> str:
    return remote_eval_canonical_sha256(terminal_receipt_payload(receipt))


def initial_repetition_progress() -> tuple[RepetitionProgress, ...]:
    return tuple(
        RepetitionProgress(
            repetition=index,
            opened=False,
            completed=False,
            next_case_ordinal=1,
            captures_accepted=0,
            capture_export_sha256=None,
        )
        for index in range(1, REPETITIONS_REQUIRED + 1)
    )


def _jsonable(value: object) -> object:
    if isinstance(value, datetime):
        return format_rfc3339(value)
    if isinstance(value, StrEnum):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value
