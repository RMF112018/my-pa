"""Authoritative GSQS ChatLLM remote-evaluation session state machine (Phase A).

This module owns session lifecycle, leases, capture admission, and transitions.
It does not perform network I/O, PNG staging, durable journaling, or filesystem
writes. Persistence, staging, disclosure, and time are injected ports.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import TypeVar
from uuid import uuid4

from my_pa.application.goodnotes_gsqs import (
    NOTE_UNIT_V2,
    AnalyzerOutput,
    PredictedSegment,
    admit_analyzer_output,
    evaluator_code_identity,
    parse_predicted_segment,
    predicted_segment_contract_payload,
)
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_CAPTURE_CONFLICT,
    ERROR_DISCLOSURE_UNCERTAIN,
    ERROR_EVAL_DISABLED,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_INVALID_ANALYZER_OUTPUT,
    ERROR_INVALID_TRANSITION,
    ERROR_LEASE_CONFLICT,
    ERROR_LEASE_EXPIRED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_RESULT_TOO_LARGE,
    ERROR_SESSION_BLOCKED,
    ERROR_SESSION_EXPIRED,
    ERROR_SESSION_NOT_IN_PROGRESS,
    ERROR_STATE_INTEGRITY_FAILURE,
    ERROR_UNAUTHENTICATED,
    LEASE_DURATION_SECONDS,
    MAX_CAPTURE_SEGMENTS_BYTES,
    REPETITIONS_REQUIRED,
    SCHEMA_CAPTURE_ENTRY_V1,
    SCHEMA_EVALUATION_CASE_STATE_V1,
    SCHEMA_SESSION_MANIFEST_V1,
    SCHEMA_STATE_V1,
    SCHEMA_TERMINAL_RECEIPT_V1,
    TERMINAL_STATES,
    AcquiredCase,
    CaptureEntry,
    CaptureReceipt,
    CaseDisposition,
    Clock,
    DisclosurePort,
    EvaluationCaseState,
    Lease,
    ManifestCase,
    RemoteEvalCreateRequest,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSession,
    RemoteEvalSessionState,
    RemoteEvalStore,
    RepetitionProgress,
    SessionManifest,
    SessionState,
    SessionStatus,
    StagingPort,
    TerminalReceipt,
    build_remote_eval_session,
    case_order_sha256,
    compute_capture_identity_sha256,
    compute_manifest_sha256,
    compute_receipt_sha256,
    compute_session_identity_sha256,
    compute_state_sha256,
    idempotency_digest,
    initial_repetition_progress,
    remote_eval_canonical_dumps,
    remote_eval_canonical_sha256,
    require_sha256_hex,
    validate_remote_eval_transition,
)
from my_pa.domain.common.time import NaiveDatetimeError, ensure_utc

T = TypeVar("T")


def default_evaluator_behavior_sha256() -> str:
    """Read-only reuse of the independent evaluator identity helper."""

    return evaluator_code_identity()


class RemoteEvalService:
    """Single authoritative domain service for remote-eval session orchestration."""

    def __init__(
        self,
        *,
        store: RemoteEvalStore,
        clock: Clock,
        staging: StagingPort,
        disclosure: DisclosurePort,
        eval_enabled: bool = True,
    ) -> None:
        self._store = store
        self._clock = clock
        self._staging = staging
        self._disclosure = disclosure
        self._eval_enabled = eval_enabled

    def create_session(self, request: RemoteEvalCreateRequest) -> RemoteEvalSession:
        self._require_enabled()
        if not request.principal_id.strip():
            raise RemoteEvalError(ERROR_UNAUTHENTICATED, "principal_id is required")
        if request.mode is RemoteEvalMode.PHASE_C:
            raise RemoteEvalError(
                ERROR_FORBIDDEN_SCOPE,
                "PHASE_C session creation is fail-closed in Phase A",
            )
        if request.mode is not RemoteEvalMode.SYNTHETIC_CANARY:
            raise RemoteEvalError(ERROR_FORBIDDEN_SCOPE, "unsupported remote-eval mode")
        now = self._now()
        self._expire_due_sessions()
        existing = self._store.find_non_terminal_session_id()
        if existing is not None:
            raise RemoteEvalError(
                ERROR_INTERNAL_FAIL_CLOSED,
                "one non-terminal remote-eval session is already active",
            )
        cases = self._admit_cases(request.cases)
        session = build_remote_eval_session(
            session_id=request.session_id,
            mode=request.mode,
            authorization_id=request.authorization_id,
            principal_id=request.principal_id,
            created_at=now,
            expires_at=ensure_utc(request.expires_at),
            repository_owner=request.repository_owner,
            repository_name=request.repository_name,
            repository_commit_sha=request.repository_commit_sha,
            repository_tree_sha=request.repository_tree_sha,
            evaluator_id=request.evaluator_id,
            evaluator_version=request.evaluator_version,
            evaluator_behavior_sha256=request.evaluator_behavior_sha256,
            corpus_version=request.corpus_version,
            public_manifest_sha256=request.public_manifest_sha256,
            combined_identity_sha256=request.combined_identity_sha256,
            case_count=CASES_PER_REPETITION,
            case_order_sha256=case_order_sha256(tuple(case.case_id for case in cases)),
            analyzer_id=request.analyzer_id,
            analyzer_version=request.analyzer_version,
            semantic_prompt_sha256=request.semantic_prompt_sha256,
            conversation_prompt_sha256=request.conversation_prompt_sha256,
            model_selection_label=request.model_selection_label,
        )
        if compute_session_identity_sha256(session) != session.session_identity_sha256:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session identity mismatch")
        manifest = SessionManifest(
            schema_version=SCHEMA_SESSION_MANIFEST_V1,
            session_id=session.session_id,
            session_identity_sha256=session.session_identity_sha256,
            cases=cases,
        )
        state = SessionState(
            schema_version=SCHEMA_STATE_V1,
            session_id=session.session_id,
            revision=1,
            state=RemoteEvalSessionState.PREPARED,
            active_repetition=None,
            next_case_ordinal=1,
            active_lease=None,
            repetitions=initial_repetition_progress(),
            captures_accepted=0,
            capture_export_sha256=None,
            last_event_id=self._event_id(),
            updated_at=now,
            blocked_reason_code=None,
            terminal_reason_code=None,
        )
        self._store.create_session(session, manifest, state)
        return session

    def seal_ready(self, session_id: str) -> SessionState:
        session, manifest, state = self._load_for_mutation(session_id)
        if state.state is not RemoteEvalSessionState.PREPARED:
            self._reject_non_prepared(state)
        sealed = self._staging.seal_authorized_rasters(session, manifest)
        if not sealed.ok:
            raise RemoteEvalError(
                sealed.reason_code or ERROR_RASTER_INTEGRITY_FAILURE,
                "staging refused to seal authorized rasters",
            )
        self._store.save_manifest(sealed.manifest)
        return self._transition(
            session,
            state,
            RemoteEvalSessionState.READY,
            persist_terminal=False,
        )

    def status(self, session_id: str) -> SessionStatus:
        self._require_enabled()
        session, _manifest, state = self._load(session_id)
        state = self._expire_if_due(session, state)
        return SessionStatus(
            session_id=session.session_id,
            mode=session.mode,
            state=state.state,
            session_identity_sha256=session.session_identity_sha256,
            active_repetition=state.active_repetition,
            next_case_ordinal=state.next_case_ordinal,
            captures_accepted=state.captures_accepted,
            case_count=session.case_count,
            repetitions_required=session.repetitions_required,
            expires_at=session.expires_at,
            blocked_reason_code=state.blocked_reason_code,
            terminal_reason_code=state.terminal_reason_code,
        )

    def open_repetition(self, session_id: str, repetition: int) -> SessionState:
        _session, _manifest, state = self._load_for_mutation(session_id)
        if repetition < 1 or repetition > REPETITIONS_REQUIRED:
            raise RemoteEvalError(ERROR_INVALID_TRANSITION, "repetition is out of range")
        progress = self._repetition(state, repetition)
        if progress.completed or (
            progress.opened and state.state is RemoteEvalSessionState.IN_PROGRESS
        ):
            raise RemoteEvalError(ERROR_INVALID_TRANSITION, "repetition cannot be reopened")
        if state.state is RemoteEvalSessionState.READY:
            if repetition != 1:
                raise RemoteEvalError(ERROR_INVALID_TRANSITION, "first open must be repetition 1")
        elif state.state is RemoteEvalSessionState.REPETITION_COMPLETE:
            expected = (state.active_repetition or 0) + 1
            if repetition != expected:
                raise RemoteEvalError(ERROR_INVALID_TRANSITION, "cannot skip or jump repetition")
        else:
            raise RemoteEvalError(
                ERROR_INVALID_TRANSITION, "repetition cannot be opened from this state"
            )
        now = self._now()
        validate_remote_eval_transition(state.state, RemoteEvalSessionState.IN_PROGRESS)
        opened = replace(progress, opened=True, next_case_ordinal=1)
        next_state = replace(
            state,
            revision=state.revision + 1,
            state=RemoteEvalSessionState.IN_PROGRESS,
            active_repetition=repetition,
            next_case_ordinal=1,
            active_lease=None,
            repetitions=self._replace_progress(state.repetitions, opened),
            last_event_id=self._event_id(),
            updated_at=now,
            blocked_reason_code=None,
            terminal_reason_code=None,
        )
        self._store.save_state(next_state)
        return next_state

    def acquire_case(self, session_id: str) -> AcquiredCase:
        _session, manifest, state = self._load_for_mutation(session_id)
        if state.state is not RemoteEvalSessionState.IN_PROGRESS:
            raise RemoteEvalError(ERROR_SESSION_NOT_IN_PROGRESS, "session is not IN_PROGRESS")
        if state.active_repetition is None:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "active repetition is missing")
        now = self._now()
        current = self._manifest_case(manifest, state.next_case_ordinal)
        lease = state.active_lease
        if lease is not None and now < lease.expires_at:
            if lease.ordinal != current.ordinal or lease.case_id != current.case_id:
                raise RemoteEvalError(
                    ERROR_STATE_INTEGRITY_FAILURE, "lease does not match current case"
                )
            if lease.repetition != state.active_repetition:
                raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "lease repetition mismatch")
            return self._acquired(lease, current)
        lease = Lease(
            lease_id=str(uuid4()),
            case_id=current.case_id,
            ordinal=current.ordinal,
            repetition=state.active_repetition,
            issued_at=now,
            expires_at=now + timedelta(seconds=LEASE_DURATION_SECONDS),
        )
        next_state = replace(
            state,
            revision=state.revision + 1,
            active_lease=lease,
            last_event_id=self._event_id(),
            updated_at=now,
        )
        self._store.save_state(next_state)
        return self._acquired(lease, current)

    def submit_capture(
        self,
        session_id: str,
        lease_id: str,
        segments: Sequence[object],
    ) -> CaptureReceipt:
        self._require_enabled()
        session, manifest, state = self._load(session_id)
        state = self._expire_if_due(session, state)
        payloads = self._admit_segment_payloads(segments)
        digest = idempotency_digest(
            session_id=session.session_id,
            repetition=self._digest_repetition(state, lease_id),
            case_id=self._digest_case_id(state, lease_id, manifest),
            lease_id=lease_id,
            segments=payloads,
        )
        existing = self._store.load_capture_by_lease(session.session_id, lease_id)
        if existing is not None:
            if existing.idempotency_digest != digest:
                raise RemoteEvalError(ERROR_CAPTURE_CONFLICT, "capture already committed")
            next_state = self._advance_after_verified_capture(session, manifest, state, existing)
            return self._capture_receipt(existing, next_state, duplicate=True)
        if state.state in TERMINAL_STATES:
            self._raise_terminal(state)
        if state.state is not RemoteEvalSessionState.IN_PROGRESS:
            raise RemoteEvalError(ERROR_SESSION_NOT_IN_PROGRESS, "session is not IN_PROGRESS")
        lease = state.active_lease
        if lease is None or lease.lease_id != lease_id:
            raise RemoteEvalError(
                ERROR_LEASE_CONFLICT, "lease does not match the outstanding lease"
            )
        now = self._now()
        if now >= lease.expires_at:
            raise RemoteEvalError(ERROR_LEASE_EXPIRED, "lease has expired")
        current = self._manifest_case(manifest, state.next_case_ordinal)
        if lease.case_id != current.case_id or lease.ordinal != current.ordinal:
            raise RemoteEvalError(ERROR_LEASE_CONFLICT, "lease is not for the current case")
        if state.active_repetition is None or lease.repetition != state.active_repetition:
            raise RemoteEvalError(ERROR_LEASE_CONFLICT, "lease repetition mismatch")
        prior = self._store.load_capture(session.session_id, lease.repetition, current.case_id)
        if prior is not None:
            raise RemoteEvalError(ERROR_CAPTURE_CONFLICT, "case already has an accepted capture")
        admitted = self._admit_analyzer_output(session, current, payloads)
        stored_segments = tuple(
            predicted_segment_contract_payload(segment) for segment in admitted.segments
        )
        capture = CaptureEntry(
            schema_version=SCHEMA_CAPTURE_ENTRY_V1,
            session_id=session.session_id,
            session_identity_sha256=session.session_identity_sha256,
            repetition=lease.repetition,
            case_id=current.case_id,
            ordinal=current.ordinal,
            content_sha256=current.content_sha256,
            corpus_version=session.corpus_version,
            public_manifest_sha256=session.public_manifest_sha256,
            combined_identity_sha256=session.combined_identity_sha256,
            analyzer_id=session.analyzer_id,
            analyzer_version=session.analyzer_version,
            semantic_prompt_sha256=session.semantic_prompt_sha256,
            conversation_prompt_sha256=session.conversation_prompt_sha256,
            model_selection_label=session.model_selection_label,
            captured_at=now,
            lease_id=lease.lease_id,
            idempotency_digest=digest,
            segments=stored_segments,
            capture_identity_sha256="",
        )
        capture = replace(
            capture,
            capture_identity_sha256=compute_capture_identity_sha256(capture),
        )
        # Persist the capture first, then advance state. A crash between these
        # writes is class B: the capture is authoritative and state still points
        # at the same case, so submit/reconcile can advance once.
        self._store.commit_capture(state=state, capture=capture, terminal_receipt=None)
        next_state = self._advance_after_verified_capture(session, manifest, state, capture)
        return self._capture_receipt(capture, next_state, duplicate=False)

    def abort(self, session_id: str, reason: str) -> SessionState:
        session, _manifest, state = self._load_for_mutation(session_id)
        if not reason.strip():
            raise RemoteEvalError(ERROR_INVALID_TRANSITION, "abort reason is required")
        return self._transition(
            session,
            state,
            RemoteEvalSessionState.ABORTED,
            terminal_reason_code=reason.strip(),
        )

    def expire_if_due(self, session_id: str) -> SessionState:
        self._require_enabled()
        session, _manifest, state = self._load(session_id)
        return self._expire_if_due(session, state)

    def reconcile(self, session_id: str) -> SessionState:
        self._require_enabled()
        session, manifest, state = self._load(session_id)
        state = self._expire_if_due(session, state)
        report = self._disclosure.reconcile_on_restart(session_id=session_id)
        if report.uncertain and state.state not in TERMINAL_STATES:
            return self._transition(
                session,
                state,
                RemoteEvalSessionState.BLOCKED,
                blocked_reason_code=ERROR_DISCLOSURE_UNCERTAIN,
                terminal_reason_code=ERROR_DISCLOSURE_UNCERTAIN,
            )
        state = self._reconcile_class_b_capture(session, manifest, state)
        self._assert_capture_consistency(session, manifest, state)
        return self._reconcile_terminal_receipt(session, manifest, state)

    def record_outbound_attempt(
        self,
        session_id: str,
        *,
        repetition: int,
        case_id: str,
    ) -> str:
        session, manifest, state = self._load_for_mutation(session_id)
        case = self._case_by_id(manifest, case_id)
        _ = session
        _ = state
        return self._disclosure.start_outbound_attempt(
            session_id=session_id,
            repetition=repetition,
            case_id=case.case_id,
            content_sha256=case.content_sha256,
        )

    def with_transport_callback(
        self,
        session_id: str,
        *,
        repetition: int,
        case_id: str,
        callback: Callable[[], T],
    ) -> T:
        attempt_id = self.record_outbound_attempt(
            session_id, repetition=repetition, case_id=case_id
        )
        try:
            result = callback()
        except Exception:
            raise
        else:
            self._disclosure.confirm_disclosed_to_transport(
                session_id=session_id, attempt_id=attempt_id
            )
            return result

    def evaluation_case_state(self, session_id: str, ordinal: int) -> EvaluationCaseState:
        self._require_enabled()
        session, manifest, state = self._load(session_id)
        state = self._expire_if_due(session, state)
        _ = session
        case = self._manifest_case(manifest, ordinal)
        capture_identity: str | None = None
        if state.active_repetition is not None:
            capture = self._store.load_capture(session_id, state.active_repetition, case.case_id)
            if capture is not None:
                capture_identity = capture.capture_identity_sha256
        disposition = CaseDisposition.PENDING
        active_lease = None
        if (
            state.active_lease is not None
            and state.active_lease.ordinal == ordinal
            and capture_identity is None
        ):
            disposition = CaseDisposition.LEASED
            active_lease = state.active_lease
        elif capture_identity is not None:
            disposition = CaseDisposition.CAPTURED
        return EvaluationCaseState(
            schema_version=SCHEMA_EVALUATION_CASE_STATE_V1,
            ordinal=case.ordinal,
            case_id=case.case_id,
            content_sha256=case.content_sha256,
            disposition=disposition,
            active_lease=active_lease,
            capture_identity_sha256=capture_identity,
        )

    def _require_enabled(self) -> None:
        if not self._eval_enabled:
            raise RemoteEvalError(ERROR_EVAL_DISABLED, "remote evaluation is disabled")

    def _now(self) -> datetime:
        try:
            return ensure_utc(self._clock.now())
        except NaiveDatetimeError as exc:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "clock must return UTC") from exc

    def _event_id(self) -> str:
        return str(uuid4())

    def _load(self, session_id: str) -> tuple[RemoteEvalSession, SessionManifest, SessionState]:
        session = self._store.load_session(session_id)
        manifest = self._store.load_manifest(session_id)
        state = self._store.load_state(session_id)
        if session is None or manifest is None or state is None:
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session not found")
        return session, manifest, state

    def _load_for_mutation(
        self, session_id: str
    ) -> tuple[RemoteEvalSession, SessionManifest, SessionState]:
        self._require_enabled()
        session, manifest, state = self._load(session_id)
        state = self._expire_if_due(session, state)
        if state.state in TERMINAL_STATES:
            self._raise_terminal(state)
        return session, manifest, state

    def _raise_terminal(self, state: SessionState) -> None:
        if state.state is RemoteEvalSessionState.EXPIRED:
            raise RemoteEvalError(ERROR_SESSION_EXPIRED, "session expired")
        if state.state is RemoteEvalSessionState.BLOCKED:
            raise RemoteEvalError(ERROR_SESSION_BLOCKED, "session blocked")
        raise RemoteEvalError(ERROR_INVALID_TRANSITION, "session is terminal")

    def _reject_non_prepared(self, state: SessionState) -> None:
        if state.state in TERMINAL_STATES:
            self._raise_terminal(state)
        raise RemoteEvalError(ERROR_INVALID_TRANSITION, "seal_ready requires PREPARED")

    def _expire_if_due(self, session: RemoteEvalSession, state: SessionState) -> SessionState:
        if state.state in TERMINAL_STATES:
            return state
        if self._now() >= session.expires_at:
            return self._transition(
                session,
                state,
                RemoteEvalSessionState.EXPIRED,
                terminal_reason_code=ERROR_SESSION_EXPIRED,
            )
        return state

    def _expire_due_sessions(self) -> None:
        for session_id in self._store.list_session_ids():
            session = self._store.load_session(session_id)
            state = self._store.load_state(session_id)
            if session is None or state is None:
                continue
            self._expire_if_due(session, state)

    def _transition(
        self,
        session: RemoteEvalSession,
        state: SessionState,
        target: RemoteEvalSessionState,
        *,
        blocked_reason_code: str | None = None,
        terminal_reason_code: str | None = None,
        persist_terminal: bool = True,
    ) -> SessionState:
        validate_remote_eval_transition(state.state, target)
        next_state = replace(
            state,
            revision=state.revision + 1,
            state=target,
            last_event_id=self._event_id(),
            updated_at=self._now(),
            blocked_reason_code=blocked_reason_code
            if target is RemoteEvalSessionState.BLOCKED
            else state.blocked_reason_code,
            terminal_reason_code=terminal_reason_code if target in TERMINAL_STATES else None,
        )
        self._store.save_state(next_state)
        if persist_terminal and target in TERMINAL_STATES:
            manifest = self._store.load_manifest(session.session_id)
            if manifest is None:
                raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "manifest missing")
            self._store.save_terminal_receipt(
                self._build_terminal_receipt(session, manifest, next_state)
            )
        return next_state

    def _admit_cases(self, cases: tuple[ManifestCase, ...]) -> tuple[ManifestCase, ...]:
        if len(cases) != CASES_PER_REPETITION:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "case_count must be 73")
        seen: set[str] = set()
        admitted: list[ManifestCase] = []
        for index, case in enumerate(cases, start=1):
            if case.ordinal != index:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "case ordinals must be 1..73")
            if case.case_id in seen:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "duplicate case_id")
            require_sha256_hex(case.content_sha256, what=f"content_sha256 for {case.case_id}")
            if not case.staged_filename or "/" in case.staged_filename:
                raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "staged_filename is invalid")
            seen.add(case.case_id)
            admitted.append(case)
        return tuple(admitted)

    def _repetition(self, state: SessionState, repetition: int) -> RepetitionProgress:
        for item in state.repetitions:
            if item.repetition == repetition:
                return item
        raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "unknown repetition")

    def _replace_progress(
        self,
        rows: tuple[RepetitionProgress, ...],
        updated: RepetitionProgress,
    ) -> tuple[RepetitionProgress, ...]:
        return tuple(updated if item.repetition == updated.repetition else item for item in rows)

    def _manifest_case(self, manifest: SessionManifest, ordinal: int) -> ManifestCase:
        if not 1 <= ordinal <= len(manifest.cases):
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "ordinal is out of range")
        case = manifest.cases[ordinal - 1]
        if case.ordinal != ordinal:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "manifest order is corrupt")
        return case

    def _case_by_id(self, manifest: SessionManifest, case_id: str) -> ManifestCase:
        for case in manifest.cases:
            if case.case_id == case_id:
                return case
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "unknown case_id")

    def _acquired(self, lease: Lease, case: ManifestCase) -> AcquiredCase:
        return AcquiredCase(
            lease=lease,
            ordinal=case.ordinal,
            case_id=case.case_id,
            content_sha256=case.content_sha256,
            byte_length=case.byte_length,
            staged_filename=case.staged_filename,
            repetition=lease.repetition,
        )

    def _admit_segment_payloads(self, segments: Sequence[object]) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for item in segments:
            if isinstance(item, PredictedSegment):
                payloads.append(predicted_segment_contract_payload(item))
            elif isinstance(item, Mapping):
                payloads.append(dict(item))
            else:
                raise RemoteEvalError(ERROR_INVALID_ANALYZER_OUTPUT, "malformed segments")
        encoded = remote_eval_canonical_dumps(payloads).encode("utf-8")
        if len(encoded) > MAX_CAPTURE_SEGMENTS_BYTES:
            raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "canonical segments exceed 1 MiB")
        return payloads

    def _admit_analyzer_output(
        self,
        session: RemoteEvalSession,
        case: ManifestCase,
        payloads: Sequence[Mapping[str, object]],
    ) -> AnalyzerOutput:
        try:
            parsed = tuple(parse_predicted_segment(item) for item in payloads)
            output = AnalyzerOutput(
                case_id=case.case_id,
                schema_version=NOTE_UNIT_V2,
                analyzer_name=session.analyzer_id,
                analyzer_version=session.analyzer_version,
                segments=parsed,
                corpus_version=session.corpus_version,
                content_sha256=case.content_sha256,
            )
            return admit_analyzer_output(output)
        except (ValueError, TypeError, KeyError) as exc:
            raise RemoteEvalError(
                ERROR_INVALID_ANALYZER_OUTPUT, "analyzer output is invalid"
            ) from exc

    def _digest_repetition(self, state: SessionState, lease_id: str) -> int:
        existing = self._store.load_capture_by_lease(state.session_id, lease_id)
        if existing is not None:
            return existing.repetition
        if state.active_lease is not None and state.active_lease.lease_id == lease_id:
            return state.active_lease.repetition
        return state.active_repetition or 0

    def _digest_case_id(self, state: SessionState, lease_id: str, manifest: SessionManifest) -> str:
        existing = self._store.load_capture_by_lease(state.session_id, lease_id)
        if existing is not None:
            return existing.case_id
        if state.active_lease is not None and state.active_lease.lease_id == lease_id:
            return state.active_lease.case_id
        if 1 <= state.next_case_ordinal <= len(manifest.cases):
            return manifest.cases[state.next_case_ordinal - 1].case_id
        return ""

    def _capture_receipt(
        self,
        capture: CaptureEntry,
        state: SessionState,
        *,
        duplicate: bool,
    ) -> CaptureReceipt:
        return CaptureReceipt(
            session_id=capture.session_id,
            repetition=capture.repetition,
            case_id=capture.case_id,
            ordinal=capture.ordinal,
            capture_identity_sha256=capture.capture_identity_sha256,
            idempotency_digest=capture.idempotency_digest,
            duplicate=duplicate,
            state=state.state,
        )

    def _advance_after_verified_capture(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
        capture: CaptureEntry,
    ) -> SessionState:
        if compute_capture_identity_sha256(capture) != capture.capture_identity_sha256:
            raise RemoteEvalError(ERROR_STATE_INTEGRITY_FAILURE, "capture identity hash mismatch")
        progress = self._repetition(state, capture.repetition)
        if progress.captures_accepted >= capture.ordinal:
            return state
        if (
            state.active_repetition != capture.repetition
            or state.next_case_ordinal != capture.ordinal
        ):
            raise RemoteEvalError(
                ERROR_STATE_INTEGRITY_FAILURE,
                "capture does not match the current case",
            )
        now = self._now()
        next_ordinal = capture.ordinal + 1
        captures_in_rep = progress.captures_accepted + 1
        session_captures = state.captures_accepted + 1
        completed_rep = capture.ordinal == CASES_PER_REPETITION
        export_sha: str | None = None
        target = state.state
        if completed_rep:
            export_sha = self._repetition_export_sha256(
                session.session_id, capture.repetition, capture
            )
            if capture.repetition == REPETITIONS_REQUIRED:
                target = RemoteEvalSessionState.COMPLETE
            else:
                target = RemoteEvalSessionState.REPETITION_COMPLETE
        if target is not state.state:
            validate_remote_eval_transition(state.state, target)
        updated_progress = replace(
            progress,
            next_case_ordinal=next_ordinal,
            captures_accepted=captures_in_rep,
            completed=completed_rep,
            capture_export_sha256=export_sha,
        )
        next_state = replace(
            state,
            revision=state.revision + 1,
            state=target,
            next_case_ordinal=1 if completed_rep else next_ordinal,
            active_lease=None,
            repetitions=self._replace_progress(state.repetitions, updated_progress),
            captures_accepted=session_captures,
            capture_export_sha256=export_sha if completed_rep else state.capture_export_sha256,
            last_event_id=self._event_id(),
            updated_at=now,
            terminal_reason_code=None
            if target is not RemoteEvalSessionState.COMPLETE
            else target.value,
        )
        self._store.save_state(next_state)
        if target in TERMINAL_STATES:
            self._store.save_terminal_receipt(
                self._build_terminal_receipt(session, manifest, next_state)
            )
        return next_state

    def _reconcile_class_b_capture(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> SessionState:
        if state.state is not RemoteEvalSessionState.IN_PROGRESS:
            return state
        if state.active_repetition is None:
            return state
        if not 1 <= state.next_case_ordinal <= CASES_PER_REPETITION:
            return state
        current = self._manifest_case(manifest, state.next_case_ordinal)
        capture = self._store.load_capture(
            session.session_id, state.active_repetition, current.case_id
        )
        if capture is None:
            return state
        if (
            capture.ordinal != state.next_case_ordinal
            or capture.repetition != state.active_repetition
            or capture.case_id != current.case_id
        ):
            raise RemoteEvalError(
                ERROR_STATE_INTEGRITY_FAILURE,
                "on-disk capture does not match the current case",
            )
        return self._advance_after_verified_capture(session, manifest, state, capture)

    def _reconcile_terminal_receipt(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> SessionState:
        receipt = self._store.load_terminal_receipt(session.session_id)
        if receipt is None or state.state in TERMINAL_STATES:
            return state
        expected_total = CASES_PER_REPETITION * REPETITIONS_REQUIRED
        all_complete = all(item.completed for item in state.repetitions)
        hashes_match = False
        if (
            state.captures_accepted == expected_total
            and all_complete
            and receipt.terminal_state is RemoteEvalSessionState.COMPLETE
            and receipt.total_captures == expected_total
        ):
            receipt_exports = dict(receipt.repetition_capture_exports)
            hashes_match = all(
                item.capture_export_sha256 is not None
                and receipt_exports.get(item.repetition) == item.capture_export_sha256
                for item in state.repetitions
            )
        if hashes_match:
            if state.state is RemoteEvalSessionState.COMPLETE:
                return state
            return self._transition(
                session,
                state,
                RemoteEvalSessionState.COMPLETE,
                terminal_reason_code=RemoteEvalSessionState.COMPLETE.value,
            )
        raise RemoteEvalError(
            ERROR_STATE_INTEGRITY_FAILURE,
            "terminal receipt disagrees with session evidence",
        )

    def _repetition_export_sha256(
        self, session_id: str, repetition: int, capture: CaptureEntry
    ) -> str:
        existing = [
            item
            for item in self._store.list_captures(session_id, repetition)
            if item.ordinal != capture.ordinal
        ]
        existing.append(capture)
        existing.sort(key=lambda item: item.ordinal)
        return remote_eval_canonical_sha256([item.capture_identity_sha256 for item in existing])

    def _assert_capture_consistency(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> None:
        _ = session
        _ = manifest
        total = 0
        for progress in state.repetitions:
            captured = self._store.list_captures(state.session_id, progress.repetition)
            if len(captured) != progress.captures_accepted:
                raise RemoteEvalError(
                    ERROR_STATE_INTEGRITY_FAILURE,
                    "capture count does not match session state",
                )
            total += len(captured)
        if total != state.captures_accepted:
            raise RemoteEvalError(
                ERROR_STATE_INTEGRITY_FAILURE,
                "session capture total does not match repetitions",
            )

    def _build_terminal_receipt(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> TerminalReceipt:
        report = self._disclosure.reconcile_on_restart(session_id=session.session_id)
        exports = tuple((item.repetition, item.capture_export_sha256) for item in state.repetitions)
        receipt = TerminalReceipt(
            schema_version=SCHEMA_TERMINAL_RECEIPT_V1,
            session_id=session.session_id,
            session_identity_sha256=session.session_identity_sha256,
            terminal_state=state.state,
            terminal_at=state.updated_at,
            manifest_sha256=compute_manifest_sha256(manifest),
            final_state_sha256=compute_state_sha256(state),
            disclosure_journal_sha256=report.journal_sha256,
            disclosure_counts={
                "disclosed": report.disclosed_count,
                "not_disclosed": report.not_disclosed_count,
                "started": report.started_count,
            },
            repetition_capture_exports=exports,
            total_captures=state.captures_accepted,
            cleanup_retention={
                "deletion_performed": False,
                "records_retained": True,
                "retention_class": "gsqs-remote-eval-session-v1",
            },
            receipt_sha256="",
        )
        return replace(receipt, receipt_sha256=compute_receipt_sha256(receipt))


__all__ = ["RemoteEvalService", "default_evaluator_behavior_sha256"]
