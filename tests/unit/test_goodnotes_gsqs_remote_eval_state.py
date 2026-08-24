"""Remote-eval session state machine: leases, captures, and transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
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
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_RESULT_TOO_LARGE,
    ERROR_SESSION_BLOCKED,
    ERROR_SESSION_EXPIRED,
    ERROR_UNAUTHENTICATED,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    LEASE_DURATION_SECONDS,
    LEGAL_TRANSITIONS,
    REPETITIONS_REQUIRED,
    CaptureEntry,
    DisclosureReconcileReport,
    ManifestCase,
    RemoteEvalCreateRequest,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSession,
    RemoteEvalSessionState,
    SessionManifest,
    SessionState,
    StagingSealResult,
    TerminalReceipt,
    remote_eval_canonical_sha256,
    validate_remote_eval_transition,
)

VALID_SEGMENTS: list[dict[str, object]] = [
    {
        "kind": "SOURCE_CONTEXT",
        "geometry": {"x_min": 0.08, "y_min": 0.08, "width": 0.84, "height": 0.10},
    }
]


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


class FakeStore:
    def __init__(self) -> None:
        self.sessions: dict[str, RemoteEvalSession] = {}
        self.manifests: dict[str, SessionManifest] = {}
        self.states: dict[str, SessionState] = {}
        self.captures: dict[tuple[str, int, str], CaptureEntry] = {}
        self.captures_by_lease: dict[tuple[str, str], CaptureEntry] = {}
        self.receipts: dict[str, TerminalReceipt] = {}

    def create_session(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
        state: SessionState,
    ) -> None:
        self.sessions[session.session_id] = session
        self.manifests[session.session_id] = manifest
        self.states[session.session_id] = state

    def load_session(self, session_id: str) -> RemoteEvalSession | None:
        return self.sessions.get(session_id)

    def load_manifest(self, session_id: str) -> SessionManifest | None:
        return self.manifests.get(session_id)

    def load_state(self, session_id: str) -> SessionState | None:
        return self.states.get(session_id)

    def save_state(self, state: SessionState) -> None:
        self.states[state.session_id] = state

    def save_manifest(self, manifest: SessionManifest) -> None:
        self.manifests[manifest.session_id] = manifest

    def commit_capture(
        self,
        *,
        state: SessionState,
        capture: CaptureEntry,
        terminal_receipt: TerminalReceipt | None = None,
    ) -> None:
        self.states[state.session_id] = state
        self.captures[(capture.session_id, capture.repetition, capture.case_id)] = capture
        self.captures_by_lease[(capture.session_id, capture.lease_id)] = capture
        if terminal_receipt is not None:
            self.receipts[terminal_receipt.session_id] = terminal_receipt

    def load_capture(self, session_id: str, repetition: int, case_id: str) -> CaptureEntry | None:
        return self.captures.get((session_id, repetition, case_id))

    def load_capture_by_lease(self, session_id: str, lease_id: str) -> CaptureEntry | None:
        return self.captures_by_lease.get((session_id, lease_id))

    def list_captures(self, session_id: str, repetition: int) -> tuple[CaptureEntry, ...]:
        rows = [
            item
            for (sid, rep, _case_id), item in self.captures.items()
            if sid == session_id and rep == repetition
        ]
        return tuple(sorted(rows, key=lambda item: item.ordinal))

    def save_terminal_receipt(self, receipt: TerminalReceipt) -> None:
        self.receipts[receipt.session_id] = receipt

    def load_terminal_receipt(self, session_id: str) -> TerminalReceipt | None:
        return self.receipts.get(session_id)

    def list_session_ids(self) -> tuple[str, ...]:
        return tuple(self.sessions)

    def find_non_terminal_session_id(self) -> str | None:
        terminal = {
            RemoteEvalSessionState.COMPLETE,
            RemoteEvalSessionState.BLOCKED,
            RemoteEvalSessionState.ABORTED,
            RemoteEvalSessionState.EXPIRED,
        }
        for session_id, state in self.states.items():
            if state.state not in terminal:
                return session_id
        return None


class FakeStaging:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def seal_authorized_rasters(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
    ) -> StagingSealResult:
        self.calls += 1
        _ = session
        if self.fail:
            return StagingSealResult(
                ok=False,
                manifest=manifest,
                reason_code=ERROR_RASTER_INTEGRITY_FAILURE,
            )
        return StagingSealResult(ok=True, manifest=manifest)


class FakeDisclosure:
    def __init__(self, *, uncertain: bool = False) -> None:
        self.uncertain = uncertain
        self.events: list[str] = []
        self.started: list[str] = []

    def start_outbound_attempt(
        self,
        *,
        session_id: str,
        repetition: int,
        case_id: str,
        content_sha256: str,
    ) -> str:
        _ = (session_id, repetition, case_id, content_sha256)
        self.events.append(EVENT_OUTBOUND_ATTEMPT_STARTED)
        attempt_id = f"attempt-{len(self.started) + 1}"
        self.started.append(attempt_id)
        return attempt_id

    def confirm_disclosed_to_transport(self, *, session_id: str, attempt_id: str) -> None:
        _ = (session_id, attempt_id)
        self.events.append("DISCLOSED_TO_TRANSPORT")

    def confirm_not_disclosed(self, *, session_id: str, attempt_id: str) -> None:
        _ = (session_id, attempt_id)
        self.events.append("NOT_DISCLOSED")

    def reconcile_on_restart(self, *, session_id: str) -> DisclosureReconcileReport:
        _ = session_id
        return DisclosureReconcileReport(
            uncertain=self.uncertain,
            journal_sha256="a" * 64,
            started_count=len(self.started),
            disclosed_count=self.events.count("DISCLOSED_TO_TRANSPORT"),
            not_disclosed_count=self.events.count("NOT_DISCLOSED"),
        )


def _hex(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _cases() -> tuple[ManifestCase, ...]:
    return tuple(
        ManifestCase(
            ordinal=index,
            case_id=f"syn-b-{index:03d}",
            content_sha256=_hex(f"syn-b-{index:03d}"),
            byte_length=256,
            staged_filename=f"syn-b-{index:03d}.png",
        )
        for index in range(1, CASES_PER_REPETITION + 1)
    )


def _request(
    clock: FakeClock, *, session_id: str = "sess-1", **changes: object
) -> RemoteEvalCreateRequest:
    kwargs: dict[str, object] = {
        "session_id": session_id,
        "mode": RemoteEvalMode.SYNTHETIC_CANARY,
        "authorization_id": "auth-1",
        "principal_id": "principal-1",
        "expires_at": clock.now() + timedelta(hours=2),
        "repository_owner": "RMF112018",
        "repository_name": "my-pa",
        "repository_commit_sha": "abc123",
        "repository_tree_sha": "def456",
        "evaluator_id": "goodnotes-gsqs-independent",
        "evaluator_version": "1.1",
        "evaluator_behavior_sha256": _hex("eval"),
        "corpus_version": "synthetic-b-1",
        "public_manifest_sha256": _hex("public"),
        "combined_identity_sha256": _hex("combined"),
        "analyzer_id": "chatllm-goodnotes-semantic",
        "analyzer_version": "sit-1.0",
        "semantic_prompt_sha256": _hex("semantic"),
        "conversation_prompt_sha256": _hex("conversation"),
        "model_selection_label": "route-llm",
        "cases": _cases(),
    }
    kwargs.update(changes)
    return RemoteEvalCreateRequest(**kwargs)  # type: ignore[arg-type]


def _harness(
    *,
    eval_enabled: bool = True,
    staging_fail: bool = False,
    uncertain: bool = False,
    lease_seconds: int = LEASE_DURATION_SECONDS,
) -> tuple[RemoteEvalService, FakeStore, FakeClock, FakeStaging, FakeDisclosure]:
    clock = FakeClock(datetime(2026, 8, 23, 12, 0, tzinfo=UTC))
    store = FakeStore()
    staging = FakeStaging(fail=staging_fail)
    disclosure = FakeDisclosure(uncertain=uncertain)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=staging,
        disclosure=disclosure,
        eval_enabled=eval_enabled,
        lease_seconds=lease_seconds,
    )
    return service, store, clock, staging, disclosure


def _prepared() -> tuple[RemoteEvalService, FakeStore, FakeClock, str]:
    service, store, clock, _staging, _disclosure = _harness()
    session = service.create_session(_request(clock))
    return service, store, clock, session.session_id


def _ready() -> tuple[RemoteEvalService, FakeStore, FakeClock, str]:
    service, store, clock, session_id = _prepared()
    service.seal_ready(session_id)
    return service, store, clock, session_id


def _in_progress() -> tuple[RemoteEvalService, FakeStore, FakeClock, str]:
    service, store, clock, session_id = _ready()
    service.open_repetition(session_id, 1)
    return service, store, clock, session_id


def _submit_remaining(service: RemoteEvalService, session_id: str) -> None:
    while True:
        state = service.status(session_id).state
        if state in {
            RemoteEvalSessionState.REPETITION_COMPLETE,
            RemoteEvalSessionState.COMPLETE,
        }:
            return
        acquired = service.acquire_case(session_id)
        service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)


def _illegal_pairs() -> list[tuple[RemoteEvalSessionState, RemoteEvalSessionState]]:
    pairs: list[tuple[RemoteEvalSessionState, RemoteEvalSessionState]] = []
    for source in RemoteEvalSessionState:
        allowed = LEGAL_TRANSITIONS[source]
        for target in RemoteEvalSessionState:
            if target not in allowed:
                pairs.append((source, target))
    return pairs


def _legal_pairs() -> list[tuple[RemoteEvalSessionState, RemoteEvalSessionState]]:
    pairs: list[tuple[RemoteEvalSessionState, RemoteEvalSessionState]] = []
    for source, targets in LEGAL_TRANSITIONS.items():
        for target in targets:
            pairs.append((source, target))
    return pairs


def test_create_synthetic_canary_session() -> None:
    service, store, clock, _staging, _disclosure = _harness()
    session = service.create_session(_request(clock))
    assert session.mode is RemoteEvalMode.SYNTHETIC_CANARY
    assert session.partition == "B"
    assert session.case_count == 73
    assert session.repetitions_required == 3
    state = store.load_state(session.session_id)
    assert state is not None
    assert state.state is RemoteEvalSessionState.PREPARED
    manifest = store.load_manifest(session.session_id)
    assert manifest is not None
    assert len(manifest.cases) == 73


def test_phase_c_create_is_fail_closed() -> None:
    service, _store, clock, _staging, _disclosure = _harness()
    with pytest.raises(RemoteEvalError) as exc:
        service.create_session(_request(clock, mode=RemoteEvalMode.PHASE_C))
    assert exc.value.code == ERROR_FORBIDDEN_SCOPE
    with pytest.raises(ValueError):
        service.create_session(_request(clock, mode=RemoteEvalMode.PHASE_C))


def test_session_identity_is_immutable_and_stable() -> None:
    from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
        compute_session_identity_sha256,
    )

    service, _store, clock, _staging, _disclosure = _harness()
    session = service.create_session(_request(clock))
    assert replace(session).session_identity_sha256 == session.session_identity_sha256
    mutated = replace(session, analyzer_id="changed")
    assert compute_session_identity_sha256(mutated) != session.session_identity_sha256


@pytest.mark.parametrize(("source", "target"), _legal_pairs())
def test_legal_transition_validator(
    source: RemoteEvalSessionState, target: RemoteEvalSessionState
) -> None:
    validate_remote_eval_transition(source, target)


@pytest.mark.parametrize(("source", "target"), _illegal_pairs())
def test_illegal_transition_validator(
    source: RemoteEvalSessionState, target: RemoteEvalSessionState
) -> None:
    with pytest.raises(RemoteEvalError) as exc:
        validate_remote_eval_transition(source, target)
    assert exc.value.code == ERROR_INVALID_TRANSITION


def test_legal_edges_through_the_service() -> None:
    service, store, _clock, session_id = _prepared()
    assert service.seal_ready(session_id).state is RemoteEvalSessionState.READY
    assert service.open_repetition(session_id, 1).state is RemoteEvalSessionState.IN_PROGRESS
    _submit_remaining(service, session_id)
    state = store.load_state(session_id)
    assert state is not None
    assert state.state is RemoteEvalSessionState.REPETITION_COMPLETE
    assert service.open_repetition(session_id, 2).state is RemoteEvalSessionState.IN_PROGRESS

    service_abort, store_abort, _clock_abort, sid_abort = _prepared()
    service_abort.abort(sid_abort, "operator-abort")
    aborted = store_abort.load_state(sid_abort)
    assert aborted is not None
    assert aborted.state is RemoteEvalSessionState.ABORTED

    service_exp, store_exp, clock_exp, sid_exp = _prepared()
    clock_exp.advance(timedelta(hours=3))
    service_exp.expire_if_due(sid_exp)
    expired = store_exp.load_state(sid_exp)
    assert expired is not None
    assert expired.state is RemoteEvalSessionState.EXPIRED

    service_block, store_block, clock_block, _staging, _disclosure = _harness(uncertain=True)
    blocked_id = service_block.create_session(
        _request(clock_block, session_id="sess-block")
    ).session_id
    service_block.reconcile(blocked_id)
    blocked = store_block.load_state(blocked_id)
    assert blocked is not None
    assert blocked.state is RemoteEvalSessionState.BLOCKED


def test_expiry_via_clock_advance() -> None:
    service, store, clock, session_id = _ready()
    clock.advance(timedelta(hours=3))
    status = service.status(session_id)
    assert status.state is RemoteEvalSessionState.EXPIRED
    with pytest.raises(RemoteEvalError) as exc:
        service.open_repetition(session_id, 1)
    assert exc.value.code == ERROR_SESSION_EXPIRED
    assert store.load_terminal_receipt(session_id) is not None


def test_abort_requires_reason_and_does_not_delete() -> None:
    service, store, _clock, session_id = _prepared()
    with pytest.raises(RemoteEvalError) as exc:
        service.abort(session_id, "   ")
    assert exc.value.code == ERROR_INVALID_TRANSITION
    state = service.abort(session_id, "operator stop")
    assert state.state is RemoteEvalSessionState.ABORTED
    assert state.terminal_reason_code == "operator stop"
    assert store.load_session(session_id) is not None
    assert store.load_manifest(session_id) is not None


def test_terminal_states_are_immutable() -> None:
    service, _store, _clock, session_id = _prepared()
    service.abort(session_id, "done")
    with pytest.raises(RemoteEvalError) as exc:
        service.open_repetition(session_id, 1)
    assert exc.value.code == ERROR_INVALID_TRANSITION
    with pytest.raises(RemoteEvalError):
        service.abort(session_id, "again")
    with pytest.raises(RemoteEvalError):
        service.acquire_case(session_id)


def test_one_active_non_terminal_session() -> None:
    service, _store, clock, _staging, _disclosure = _harness()
    service.create_session(_request(clock, session_id="a"))
    with pytest.raises(RemoteEvalError) as exc:
        service.create_session(_request(clock, session_id="b"))
    assert exc.value.code == ERROR_INTERNAL_FAIL_CLOSED
    service.abort("a", "clear")
    second = service.create_session(_request(clock, session_id="b"))
    assert second.session_id == "b"


def test_exact_73_case_order_cannot_skip() -> None:
    service, _store, _clock, session_id = _in_progress()
    seen: list[str] = []
    for expected in range(1, 6):
        acquired = service.acquire_case(session_id)
        assert acquired.ordinal == expected
        assert acquired.case_id == f"syn-b-{expected:03d}"
        seen.append(acquired.case_id)
        service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert seen == [f"syn-b-{n:03d}" for n in range(1, 6)]
    next_case = service.acquire_case(session_id)
    assert next_case.ordinal == 6


def test_cannot_skip_or_jump_repetition() -> None:
    service, _store, _clock, session_id = _ready()
    with pytest.raises(RemoteEvalError) as exc:
        service.open_repetition(session_id, 2)
    assert exc.value.code == ERROR_INVALID_TRANSITION
    service.open_repetition(session_id, 1)
    with pytest.raises(RemoteEvalError):
        service.open_repetition(session_id, 2)
    with pytest.raises(RemoteEvalError):
        service.open_repetition(session_id, 1)


def test_lease_issue_repeat_expiry_and_replacement() -> None:
    service, store, clock, session_id = _in_progress()
    first = service.acquire_case(session_id)
    second = service.acquire_case(session_id)
    assert first.lease.lease_id == second.lease.lease_id
    assert first.case_id == second.case_id
    clock.advance(timedelta(seconds=LEASE_DURATION_SECONDS + 1))
    replacement = service.acquire_case(session_id)
    assert replacement.lease.lease_id != first.lease.lease_id
    assert replacement.case_id == first.case_id
    assert replacement.ordinal == first.ordinal
    with pytest.raises(RemoteEvalError) as expired:
        service.submit_capture(session_id, first.lease.lease_id, VALID_SEGMENTS)
    assert expired.value.code in {ERROR_LEASE_EXPIRED, ERROR_LEASE_CONFLICT}
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 1
    service.submit_capture(session_id, replacement.lease.lease_id, VALID_SEGMENTS)
    advanced = store.load_state(session_id)
    assert advanced is not None
    assert advanced.next_case_ordinal == 2


def test_default_lease_survives_observed_chatllm_visual_delay() -> None:
    service, store, clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    clock.advance(timedelta(seconds=1097))
    receipt = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert receipt.duplicate is False
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 2


def test_configured_short_lease_expires_and_does_not_advance_case() -> None:
    service, store, clock, _staging, _disclosure = _harness(lease_seconds=900)
    session = service.create_session(_request(clock))
    service.seal_ready(session.session_id)
    service.open_repetition(session.session_id, 1)
    first = service.acquire_case(session.session_id)
    clock.advance(timedelta(seconds=901))
    with pytest.raises(RemoteEvalError) as expired:
        service.submit_capture(session.session_id, first.lease.lease_id, VALID_SEGMENTS)
    assert expired.value.code == ERROR_LEASE_EXPIRED
    replacement = service.acquire_case(session.session_id)
    assert replacement.lease.lease_id != first.lease.lease_id
    assert replacement.ordinal == 1
    state = store.load_state(session.session_id)
    assert state is not None
    assert state.next_case_ordinal == 1


def test_duplicate_and_conflicting_submit() -> None:
    service, store, _clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    first = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert first.duplicate is False
    replay = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert replay.duplicate is True
    assert replay.capture_identity_sha256 == first.capture_identity_sha256
    other = [
        {
            "kind": "SOURCE_CONTEXT",
            "geometry": {"x_min": 0.10, "y_min": 0.10, "width": 0.40, "height": 0.20},
        }
    ]
    with pytest.raises(RemoteEvalError) as exc:
        service.submit_capture(session_id, acquired.lease.lease_id, other)
    assert exc.value.code == ERROR_CAPTURE_CONFLICT
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 2


def _simulate_crash_after_capture(store: FakeStore, session_id: str, capture: CaptureEntry) -> None:
    """Leave the capture in the store but roll state back to still point at that case."""

    state = store.load_state(session_id)
    assert state is not None
    progress = next(item for item in state.repetitions if item.repetition == capture.repetition)
    rolled_progress = replace(
        progress,
        next_case_ordinal=capture.ordinal,
        captures_accepted=capture.ordinal - 1,
        completed=False,
        capture_export_sha256=None,
    )
    repetitions = tuple(
        rolled_progress if item.repetition == capture.repetition else item
        for item in state.repetitions
    )
    export = None
    for item in repetitions:
        if item.completed and item.capture_export_sha256 is not None:
            export = item.capture_export_sha256
    store.save_state(
        replace(
            state,
            state=RemoteEvalSessionState.IN_PROGRESS,
            next_case_ordinal=capture.ordinal,
            active_lease=None,
            repetitions=repetitions,
            captures_accepted=sum(item.captures_accepted for item in repetitions),
            capture_export_sha256=export,
            terminal_reason_code=None,
        )
    )


def _submit_n(service: RemoteEvalService, session_id: str, count: int) -> tuple[str, str]:
    lease_id = ""
    case_id = ""
    for _ in range(count):
        acquired = service.acquire_case(session_id)
        lease_id = acquired.lease.lease_id
        case_id = acquired.case_id
        service.submit_capture(session_id, lease_id, VALID_SEGMENTS)
    return lease_id, case_id


def test_crash_after_capture_same_digest_advances_once() -> None:
    service, store, _clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    first = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert first.duplicate is False
    capture = store.load_capture(session_id, 1, acquired.case_id)
    assert capture is not None
    _simulate_crash_after_capture(store, session_id, capture)
    crashed = store.load_state(session_id)
    assert crashed is not None
    assert crashed.next_case_ordinal == 1
    assert crashed.captures_accepted == 0
    recovered = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert recovered.duplicate is True
    advanced = store.load_state(session_id)
    assert advanced is not None
    assert advanced.next_case_ordinal == 2
    assert advanced.captures_accepted == 1
    assert len(store.list_captures(session_id, 1)) == 1
    replay = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    assert replay.duplicate is True
    again = store.load_state(session_id)
    assert again is not None
    assert again.next_case_ordinal == 2
    assert again.captures_accepted == 1
    assert again.revision == advanced.revision


def test_crash_after_ordinal_73_rep1_recovers_to_repetition_complete() -> None:
    service, store, _clock, session_id = _in_progress()
    lease_id, case_id = _submit_n(service, session_id, CASES_PER_REPETITION)
    completed = store.load_state(session_id)
    assert completed is not None
    assert completed.state is RemoteEvalSessionState.REPETITION_COMPLETE
    capture = store.load_capture(session_id, 1, case_id)
    assert capture is not None
    assert capture.ordinal == CASES_PER_REPETITION
    _simulate_crash_after_capture(store, session_id, capture)
    crashed = store.load_state(session_id)
    assert crashed is not None
    assert crashed.state is RemoteEvalSessionState.IN_PROGRESS
    assert crashed.next_case_ordinal == CASES_PER_REPETITION
    recovered = service.submit_capture(session_id, lease_id, VALID_SEGMENTS)
    assert recovered.duplicate is True
    assert recovered.state is RemoteEvalSessionState.REPETITION_COMPLETE
    final = store.load_state(session_id)
    assert final is not None
    assert final.state is RemoteEvalSessionState.REPETITION_COMPLETE
    assert final.next_case_ordinal == 1
    assert final.repetitions[0].completed is True
    assert final.repetitions[0].captures_accepted == CASES_PER_REPETITION
    assert final.repetitions[0].capture_export_sha256 is not None
    assert final.captures_accepted == CASES_PER_REPETITION


def test_crash_after_ordinal_73_rep3_recovers_to_complete() -> None:
    service, store, _clock, session_id = _ready()
    lease_id = ""
    case_id = ""
    for repetition in range(1, REPETITIONS_REQUIRED + 1):
        service.open_repetition(session_id, repetition)
        lease_id, case_id = _submit_n(service, session_id, CASES_PER_REPETITION)
    done = store.load_state(session_id)
    assert done is not None
    assert done.state is RemoteEvalSessionState.COMPLETE
    assert store.find_non_terminal_session_id() is None
    capture = store.load_capture(session_id, REPETITIONS_REQUIRED, case_id)
    assert capture is not None
    _simulate_crash_after_capture(store, session_id, capture)
    crashed = store.load_state(session_id)
    assert crashed is not None
    assert crashed.state is RemoteEvalSessionState.IN_PROGRESS
    assert crashed.next_case_ordinal == CASES_PER_REPETITION
    assert store.find_non_terminal_session_id() == session_id
    recovered = service.reconcile(session_id)
    assert recovered.state is RemoteEvalSessionState.COMPLETE
    assert recovered.captures_accepted == CASES_PER_REPETITION * REPETITIONS_REQUIRED
    assert recovered.repetitions[2].completed is True
    assert recovered.repetitions[2].capture_export_sha256 is not None
    receipt = store.load_terminal_receipt(session_id)
    assert receipt is not None
    assert receipt.terminal_state is RemoteEvalSessionState.COMPLETE
    assert store.find_non_terminal_session_id() is None
    replay = service.submit_capture(session_id, lease_id, VALID_SEGMENTS)
    assert replay.duplicate is True
    assert replay.state is RemoteEvalSessionState.COMPLETE
    again = store.load_state(session_id)
    assert again is not None
    assert again.captures_accepted == CASES_PER_REPETITION * REPETITIONS_REQUIRED


def test_crash_after_capture_conflicting_digest_preserves_original() -> None:
    service, store, _clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    first = service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    capture = store.load_capture(session_id, 1, acquired.case_id)
    assert capture is not None
    _simulate_crash_after_capture(store, session_id, capture)
    other = [
        {
            "kind": "SOURCE_CONTEXT",
            "geometry": {"x_min": 0.10, "y_min": 0.10, "width": 0.40, "height": 0.20},
        }
    ]
    with pytest.raises(RemoteEvalError) as exc:
        service.submit_capture(session_id, acquired.lease.lease_id, other)
    assert exc.value.code == ERROR_CAPTURE_CONFLICT
    stalled = store.load_state(session_id)
    assert stalled is not None
    assert stalled.next_case_ordinal == 1
    assert stalled.captures_accepted == 0
    original = store.load_capture(session_id, 1, acquired.case_id)
    assert original is not None
    assert original.capture_identity_sha256 == first.capture_identity_sha256
    assert original.idempotency_digest == first.idempotency_digest


def test_reconcile_class_b_advances_without_resubmit() -> None:
    service, store, _clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    service.submit_capture(session_id, acquired.lease.lease_id, VALID_SEGMENTS)
    capture = store.load_capture(session_id, 1, acquired.case_id)
    assert capture is not None
    _simulate_crash_after_capture(store, session_id, capture)
    recovered = service.reconcile(session_id)
    assert recovered.state is RemoteEvalSessionState.IN_PROGRESS
    assert recovered.next_case_ordinal == 2
    assert recovered.captures_accepted == 1
    assert recovered.active_lease is None
    assert len(store.list_captures(session_id, 1)) == 1


def test_malformed_payload_does_not_advance() -> None:
    service, store, _clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    with pytest.raises(RemoteEvalError) as exc:
        service.submit_capture(session_id, acquired.lease.lease_id, [{"kind": "NOPE"}])
    assert exc.value.code == ERROR_INVALID_ANALYZER_OUTPUT
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 1
    assert state.captures_accepted == 0


def test_full_three_repetitions_complete_219_captures() -> None:
    service, store, _clock, session_id = _ready()
    for repetition in range(1, REPETITIONS_REQUIRED + 1):
        opened = service.open_repetition(session_id, repetition)
        assert opened.state is RemoteEvalSessionState.IN_PROGRESS
        _submit_remaining(service, session_id)
        state = store.load_state(session_id)
        assert state is not None
        if repetition < REPETITIONS_REQUIRED:
            assert state.state is RemoteEvalSessionState.REPETITION_COMPLETE
        else:
            assert state.state is RemoteEvalSessionState.COMPLETE
    state = store.load_state(session_id)
    assert state is not None
    assert state.captures_accepted == 219
    assert sum(len(store.list_captures(session_id, rep)) for rep in range(1, 4)) == 219
    receipt = store.load_terminal_receipt(session_id)
    assert receipt is not None
    assert receipt.total_captures == 219
    assert receipt.terminal_state is RemoteEvalSessionState.COMPLETE
    with pytest.raises(RemoteEvalError):
        service.abort(session_id, "too late")


def test_started_recorded_before_transport_callback() -> None:
    service, _store, clock, _staging, disclosure = _harness()
    session = service.create_session(_request(clock))
    order: list[str] = []

    def _callback() -> str:
        order.append("callback")
        return "ok"

    original_start = disclosure.start_outbound_attempt

    def _start(
        *,
        session_id: str,
        repetition: int,
        case_id: str,
        content_sha256: str,
    ) -> str:
        order.append("started")
        return original_start(
            session_id=session_id,
            repetition=repetition,
            case_id=case_id,
            content_sha256=content_sha256,
        )

    disclosure.start_outbound_attempt = _start  # type: ignore[method-assign]
    result = service.with_transport_callback(
        session.session_id,
        repetition=1,
        case_id="syn-b-001",
        callback=_callback,
    )
    assert result == "ok"
    assert order == ["started", "callback"]
    assert disclosure.events[0] == EVENT_OUTBOUND_ATTEMPT_STARTED


def test_reconcile_uncertain_blocks() -> None:
    service, store, clock, _staging, _disclosure = _harness(uncertain=True)
    session = service.create_session(_request(clock))
    state = service.reconcile(session.session_id)
    assert state.state is RemoteEvalSessionState.BLOCKED
    assert state.blocked_reason_code == ERROR_DISCLOSURE_UNCERTAIN
    with pytest.raises(RemoteEvalError) as exc:
        service.seal_ready(session.session_id)
    assert exc.value.code == ERROR_SESSION_BLOCKED
    assert store.load_terminal_receipt(session.session_id) is not None


def test_eval_disabled() -> None:
    service, _store, clock, _staging, _disclosure = _harness(eval_enabled=False)
    with pytest.raises(RemoteEvalError) as exc:
        service.create_session(_request(clock))
    assert exc.value.code == ERROR_EVAL_DISABLED


def test_unauthenticated_empty_principal() -> None:
    service, _store, clock, _staging, _disclosure = _harness()
    with pytest.raises(RemoteEvalError) as exc:
        service.create_session(_request(clock, principal_id=""))
    assert exc.value.code == ERROR_UNAUTHENTICATED


def test_result_too_large() -> None:
    service, store, _clock, session_id = _in_progress()
    acquired = service.acquire_case(session_id)
    huge = [
        {
            "kind": "SOURCE_CONTEXT",
            "geometry": {"x_min": 0.08, "y_min": 0.08, "width": 0.84, "height": 0.10},
            "pad": "x" * 2_000_000,
        }
    ]
    with pytest.raises(RemoteEvalError) as exc:
        service.submit_capture(session_id, acquired.lease.lease_id, huge)
    assert exc.value.code == ERROR_RESULT_TOO_LARGE
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 1


def test_implementation_modules_do_not_call_datetime_now() -> None:
    root = Path("src/my_pa/application")
    for name in (
        "goodnotes_gsqs_remote_eval_contracts.py",
        "goodnotes_gsqs_remote_eval.py",
    ):
        text = (root / name).read_text(encoding="utf-8")
        assert "datetime.now" not in text
        assert "utc_now(" not in text


def test_staging_failure_stays_prepared() -> None:
    service, store, clock, _staging, _disclosure = _harness(staging_fail=True)
    session = service.create_session(_request(clock))
    with pytest.raises(RemoteEvalError) as exc:
        service.seal_ready(session.session_id)
    assert exc.value.code == ERROR_RASTER_INTEGRITY_FAILURE
    state = store.load_state(session.session_id)
    assert state is not None
    assert state.state is RemoteEvalSessionState.PREPARED


def test_case_order_sha256_matches_frozen_ids() -> None:
    service, store, clock, _staging, _disclosure = _harness()
    session = service.create_session(_request(clock))
    manifest = store.load_manifest(session.session_id)
    assert manifest is not None
    case_ids = [case.case_id for case in manifest.cases]
    assert session.case_order_sha256 == remote_eval_canonical_sha256(case_ids)
    assert case_ids == [f"syn-b-{i:03d}" for i in range(1, 74)]
