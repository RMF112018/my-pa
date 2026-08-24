"""73x3 remote-eval orchestration on real filesystem ports and synthetic fixtures."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import asdict, is_dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from my_pa.application.goodnotes_gsqs import (
    GATE_B_STATE,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    CorpusPartition,
    evaluator_code_identity,
    evaluator_implementation_files,
)
from my_pa.application.goodnotes_gsqs_b0_mcp import CAPTURE_SCHEMA_VERSION
from my_pa.application.goodnotes_gsqs_corpus import freeze_manifest
from my_pa.application.goodnotes_gsqs_harness import parse_interchange, score_partition
from my_pa.application.goodnotes_gsqs_remote_eval import (
    RemoteEvalService,
    default_evaluator_behavior_sha256,
)
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_CAPTURE_CONFLICT,
    ERROR_DISCLOSURE_UNCERTAIN,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_INVALID_TRANSITION,
    ERROR_LEASE_CONFLICT,
    ERROR_LEASE_EXPIRED,
    EVENT_DISCLOSED_TO_TRANSPORT,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    LEASE_DURATION_SECONDS,
    MANIFEST_FORBIDDEN_KEYS,
    REPETITIONS_REQUIRED,
    RemoteEvalCreateRequest,
    RemoteEvalError,
    RemoteEvalMode,
    RemoteEvalSessionState,
    remote_eval_canonical_sha256,
)
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import (
    JOURNAL_FILENAME,
    FilesystemDisclosureJournal,
)
from my_pa.application.goodnotes_gsqs_remote_eval_staging import FilesystemRasterStaging
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    FilesystemRemoteEvalStore,
    session_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATE_PATH = REPO_ROOT / "ops/goodnotes/gsqs/fixtures/remote-eval/generate.py"
EXPECTED_CASE_IDS = tuple(f"syn-b-{index:03d}" for index in range(1, CASES_PER_REPETITION + 1))
FORBIDDEN_SPOOL_KEYS = frozenset(MANIFEST_FORBIDDEN_KEYS) | {"gold", "path", "private_label"}
EVALUATOR_CODE_IDENTITY = "d2bd088a098f99d31637069fd339a67d665b80eb7aa97b403367cce1011a3fb7"
ALTERNATE_SEGMENTS: list[dict[str, object]] = [
    {
        "kind": "SOURCE_CONTEXT",
        "geometry": {"x_min": 0.10, "y_min": 0.10, "width": 0.80, "height": 0.10},
    }
]


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta


def _load_generate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gsqs_remote_eval_generate", GENERATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hex(label: str) -> str:
    return remote_eval_canonical_sha256(label)


def _json_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys.update(str(key) for key in value)
        for item in value.values():
            keys.update(_json_keys(item))
    elif isinstance(value, list | tuple):
        for item in value:
            keys.update(_json_keys(item))
    elif is_dataclass(value) and not isinstance(value, type):
        keys.update(_json_keys(asdict(value)))
    return keys


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _assert_no_forbidden_keys(payload: object, *, where: str) -> None:
    found = FORBIDDEN_SPOOL_KEYS & _json_keys(payload)
    assert not found, f"{where} contains forbidden keys: {sorted(found)}"


def _assert_no_source_path(payload: object, source_root: Path, *, where: str) -> None:
    blob = json.dumps(payload, default=str)
    assert str(source_root) not in blob, f"{where} leaked source filesystem path"
    assert source_root.as_posix() not in blob, f"{where} leaked source filesystem path"


def _compose(
    tmp_path: Path, generate: ModuleType, clock: FakeClock | None = None
) -> tuple[RemoteEvalService, FilesystemRemoteEvalStore, FakeClock, Path, Path]:
    state_root = tmp_path / "state"
    source_root = tmp_path / "rasters"
    written = generate.write_rasters(source_root)
    assert len(written) == CASES_PER_REPETITION
    assert {path.suffix.lower() for path in source_root.iterdir()} == {".png"}
    assert not list(source_root.glob("*.json"))
    stamped = clock or FakeClock(datetime(2026, 8, 23, 12, 0, tzinfo=UTC))
    store = FilesystemRemoteEvalStore(state_root)
    staging = FilesystemRasterStaging(state_root, source_root)
    disclosure = FilesystemDisclosureJournal(state_root, clock=stamped)
    service = RemoteEvalService(
        store=store,
        clock=stamped,
        staging=staging,
        disclosure=disclosure,
    )
    return service, store, stamped, state_root, source_root


def _create_request(
    generate: ModuleType,
    clock: FakeClock,
    *,
    session_id: str = "orch-session-1",
    mode: RemoteEvalMode = RemoteEvalMode.SYNTHETIC_CANARY,
) -> RemoteEvalCreateRequest:
    cases = generate.manifest_cases()
    public_manifest_sha256 = remote_eval_canonical_sha256(
        [
            {
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "ordinal": case.ordinal,
            }
            for case in cases
        ]
    )
    evaluator_behavior = default_evaluator_behavior_sha256()
    combined_identity_sha256 = remote_eval_canonical_sha256(
        {
            "corpus_version": generate.CORPUS_VERSION,
            "evaluator_behavior_sha256": evaluator_behavior,
            "partition": "B",
            "public_manifest_sha256": public_manifest_sha256,
        }
    )
    return RemoteEvalCreateRequest(
        session_id=session_id,
        mode=mode,
        authorization_id="synthetic-canary",
        principal_id="principal-1",
        expires_at=clock.now() + timedelta(hours=2),
        repository_owner="RMF112018",
        repository_name="my-pa",
        repository_commit_sha="abc123",
        repository_tree_sha="def456",
        evaluator_id="goodnotes-gsqs-independent",
        evaluator_version="1.1",
        evaluator_behavior_sha256=evaluator_behavior,
        corpus_version=generate.CORPUS_VERSION,
        public_manifest_sha256=public_manifest_sha256,
        combined_identity_sha256=combined_identity_sha256,
        analyzer_id=generate.ANALYZER_ID,
        analyzer_version=generate.ANALYZER_VERSION,
        semantic_prompt_sha256=_hex("semantic"),
        conversation_prompt_sha256=_hex("conversation"),
        model_selection_label="synthetic-canary",
        cases=cases,
    )


def _ready_session(
    tmp_path: Path,
    generate: ModuleType,
    *,
    session_id: str = "orch-session-1",
    clock: FakeClock | None = None,
) -> tuple[RemoteEvalService, FilesystemRemoteEvalStore, FakeClock, Path, Path, str]:
    service, store, stamped, state_root, source_root = _compose(tmp_path, generate, clock)
    session = service.create_session(_create_request(generate, stamped, session_id=session_id))
    state = service.seal_ready(session.session_id)
    assert state.state is RemoteEvalSessionState.READY
    return service, store, stamped, state_root, source_root, session.session_id


def test_full_73x3_synthetic_session_completes_exports_and_scores(tmp_path: Path) -> None:
    generate = _load_generate()
    service, store, _clock, state_root, source_root, session_id = _ready_session(tmp_path, generate)
    segments = generate.synthetic_segments()
    session = store.load_session(session_id)
    assert session is not None
    assert tuple(generate.CASE_IDS) == EXPECTED_CASE_IDS

    with pytest.raises(RemoteEvalError) as skip_rep:
        service.open_repetition(session_id, 2)
    assert skip_rep.value.code == ERROR_INVALID_TRANSITION

    for repetition in range(1, REPETITIONS_REQUIRED + 1):
        opened = service.open_repetition(session_id, repetition)
        assert opened.state is RemoteEvalSessionState.IN_PROGRESS
        assert opened.active_repetition == repetition
        captured_ids: list[str] = []
        for expected_ordinal, expected_case_id in enumerate(EXPECTED_CASE_IDS, start=1):
            acquired = service.acquire_case(session_id)
            assert acquired.ordinal == expected_ordinal
            assert acquired.case_id == expected_case_id
            assert acquired.repetition == repetition
            receipt = service.submit_capture(session_id, acquired.lease.lease_id, segments)
            assert receipt.duplicate is False
            assert receipt.case_id == expected_case_id
            captured_ids.append(acquired.case_id)
            status = service.status(session_id)
            _assert_no_source_path(asdict(status), source_root, where="public status")
            if expected_ordinal < CASES_PER_REPETITION:
                assert status.state is RemoteEvalSessionState.IN_PROGRESS
                assert status.next_case_ordinal == expected_ordinal + 1
        assert captured_ids == list(EXPECTED_CASE_IDS)
        state = store.load_state(session_id)
        assert state is not None
        if repetition < REPETITIONS_REQUIRED:
            assert state.state is RemoteEvalSessionState.REPETITION_COMPLETE
            assert state.captures_accepted == repetition * CASES_PER_REPETITION
            with pytest.raises(RemoteEvalError) as skip_ahead:
                service.open_repetition(session_id, repetition + 2)
            assert skip_ahead.value.code == ERROR_INVALID_TRANSITION
        else:
            assert state.state is RemoteEvalSessionState.COMPLETE
            assert state.captures_accepted == CASES_PER_REPETITION * REPETITIONS_REQUIRED

    final_status = service.status(session_id)
    assert final_status.state is RemoteEvalSessionState.COMPLETE
    assert final_status.captures_accepted == 219
    _assert_no_source_path(asdict(final_status), source_root, where="public status")

    session_dir = session_directory(state_root, session_id)
    spool_files = [
        session_dir / "session.json",
        session_dir / "manifest.json",
        session_dir / "state.json",
        *sorted((session_dir / "captures").rglob("*.json")),
    ]
    for path in spool_files:
        assert path.is_file(), f"missing spool file {path}"
        _assert_no_forbidden_keys(_load_json(path), where=str(path.relative_to(session_dir)))
    _assert_no_source_path(_load_json(session_dir / "manifest.json"), source_root, where="manifest")

    export_dir = tmp_path / "export"
    written = store.write_canonical_export_dir(session_id, export_dir)
    assert [path.name for path in written] == [
        "repetition-001.json",
        "repetition-002.json",
        "repetition-003.json",
    ]
    cases = generate.synthetic_corpus_cases()
    frozen = freeze_manifest(
        cases,
        generator_version=generate.GENERATOR_VERSION,
        approval_status="APPROVED",
    )
    for path in written:
        payload = _load_json(path)
        assert isinstance(payload, dict)
        assert payload["schema_version"] == CAPTURE_SCHEMA_VERSION
        assert CAPTURE_SCHEMA_VERSION == "gsqs-analyzer-capture-v1"
        documents = payload["documents"]
        assert isinstance(documents, list)
        assert len(documents) == CASES_PER_REPETITION
        assert [item["case_id"] for item in documents] == list(EXPECTED_CASE_IDS)
        _assert_no_forbidden_keys(payload, where=path.name)
        outputs = [parse_interchange(document) for document in documents]
        _result, record = score_partition(
            cases,
            outputs,
            partition=CorpusPartition.B,
            manifest=frozen,
            analyzer_name=session.analyzer_id,
            analyzer_version=session.analyzer_version,
            run_repetition=int(path.stem.split("-")[1]),
        )
        assert record.case_count == CASES_PER_REPETITION
        assert GATE_B_STATE["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED
        assert MEASURED_B0_NOT_YET_ESTABLISHED == "NOT_YET_ESTABLISHED"

    assert evaluator_code_identity() == EVALUATOR_CODE_IDENTITY
    remote_eval_names = {
        path.name
        for path in evaluator_implementation_files()
        if "goodnotes_gsqs_remote_eval" in path.name
    }
    assert not remote_eval_names


def test_phase_c_create_is_fail_closed(tmp_path: Path) -> None:
    generate = _load_generate()
    service, _store, clock, _state_root, _source_root = _compose(tmp_path, generate)
    with pytest.raises(RemoteEvalError) as exc:
        service.create_session(
            _create_request(generate, clock, session_id="phase-c", mode=RemoteEvalMode.PHASE_C)
        )
    assert exc.value.code == ERROR_FORBIDDEN_SCOPE


def test_create_session_rejects_second_occupying_session(tmp_path: Path) -> None:
    generate = _load_generate()
    service, _store, clock, _state_root, _source_root, _session_id = _ready_session(
        tmp_path, generate, session_id="occupying"
    )
    with pytest.raises(RemoteEvalError) as exc:
        service.create_session(_create_request(generate, clock, session_id="second"))
    assert exc.value.code == ERROR_INTERNAL_FAIL_CLOSED


def test_create_session_allowed_when_existing_is_parked_repetition_complete(
    tmp_path: Path,
) -> None:
    generate = _load_generate()
    service, store, clock, _state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="parked-complete"
    )
    service.open_repetition(session_id, 1)
    current = store.load_state(session_id)
    assert current is not None
    store.save_state(replace(current, state=RemoteEvalSessionState.REPETITION_COMPLETE))
    created = service.create_session(
        _create_request(generate, clock, session_id="image-first-canary")
    )
    assert created.session_id == "image-first-canary"


def test_cannot_skip_case_or_repetition(tmp_path: Path) -> None:
    generate = _load_generate()
    service, _store, _clock, _state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="no-skip"
    )
    with pytest.raises(RemoteEvalError):
        service.acquire_case(session_id)
    service.open_repetition(session_id, 1)
    first = service.acquire_case(session_id)
    assert first.ordinal == 1
    assert first.case_id == "syn-b-001"
    service.submit_capture(session_id, first.lease.lease_id, generate.synthetic_segments())
    second = service.acquire_case(session_id)
    assert second.ordinal == 2
    assert second.case_id == "syn-b-002"
    with pytest.raises(RemoteEvalError) as skip_rep:
        service.open_repetition(session_id, 2)
    assert skip_rep.value.code == ERROR_INVALID_TRANSITION


def test_lease_acquire_duplicate_expire_replace_and_reject_old(tmp_path: Path) -> None:
    generate = _load_generate()
    service, store, clock, _state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="lease-session"
    )
    service.open_repetition(session_id, 1)
    first = service.acquire_case(session_id)
    duplicate = service.acquire_case(session_id)
    assert first.lease.lease_id == duplicate.lease.lease_id
    assert first.case_id == duplicate.case_id == "syn-b-001"
    clock.advance(timedelta(seconds=LEASE_DURATION_SECONDS + 1))
    replacement = service.acquire_case(session_id)
    assert replacement.lease.lease_id != first.lease.lease_id
    assert replacement.case_id == first.case_id
    assert replacement.ordinal == first.ordinal
    with pytest.raises(RemoteEvalError) as expired:
        service.submit_capture(session_id, first.lease.lease_id, generate.synthetic_segments())
    assert expired.value.code in {ERROR_LEASE_EXPIRED, ERROR_LEASE_CONFLICT}
    receipt = service.submit_capture(
        session_id, replacement.lease.lease_id, generate.synthetic_segments()
    )
    assert receipt.duplicate is False
    assert receipt.ordinal == 1
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 2


def test_duplicate_submit_is_idempotent_conflict_raises_capture_conflict(tmp_path: Path) -> None:
    generate = _load_generate()
    service, store, _clock, _state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="idempotent"
    )
    service.open_repetition(session_id, 1)
    acquired = service.acquire_case(session_id)
    first = service.submit_capture(
        session_id, acquired.lease.lease_id, generate.synthetic_segments()
    )
    replay = service.submit_capture(
        session_id, acquired.lease.lease_id, generate.synthetic_segments()
    )
    assert first.duplicate is False
    assert replay.duplicate is True
    assert replay.capture_identity_sha256 == first.capture_identity_sha256
    with pytest.raises(RemoteEvalError) as conflict:
        service.submit_capture(session_id, acquired.lease.lease_id, ALTERNATE_SEGMENTS)
    assert conflict.value.code == ERROR_CAPTURE_CONFLICT
    state = store.load_state(session_id)
    assert state is not None
    assert state.next_case_ordinal == 2


def test_reconcile_class_b_after_capture_without_state_write(tmp_path: Path) -> None:
    generate = _load_generate()
    service, store, _clock, _state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="class-b"
    )
    service.open_repetition(session_id, 1)
    acquired = service.acquire_case(session_id)
    service.submit_capture(session_id, acquired.lease.lease_id, generate.synthetic_segments())
    capture = store.load_capture(session_id, 1, acquired.case_id)
    assert capture is not None
    state = store.load_state(session_id)
    assert state is not None
    progress = next(item for item in state.repetitions if item.repetition == 1)
    rolled_progress = replace(
        progress,
        next_case_ordinal=1,
        captures_accepted=0,
        completed=False,
        capture_export_sha256=None,
    )
    store.save_state(
        replace(
            state,
            state=RemoteEvalSessionState.IN_PROGRESS,
            next_case_ordinal=1,
            active_lease=None,
            repetitions=tuple(
                rolled_progress if item.repetition == 1 else item for item in state.repetitions
            ),
            captures_accepted=0,
            capture_export_sha256=None,
        )
    )
    recovered = service.reconcile(session_id)
    assert recovered.next_case_ordinal == 2
    assert recovered.captures_accepted == 1
    assert len(store.list_captures(session_id, 1)) == 1


def test_started_is_durable_before_transport_callback(tmp_path: Path) -> None:
    generate = _load_generate()
    service, _store, _clock, state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="started-before"
    )
    journal = session_directory(state_root, session_id) / "journal" / JOURNAL_FILENAME
    seen: list[str] = []

    def _callback() -> str:
        body = journal.read_text(encoding="utf-8")
        assert EVENT_OUTBOUND_ATTEMPT_STARTED in body
        assert EVENT_DISCLOSED_TO_TRANSPORT not in body
        seen.append("callback")
        return "ok"

    result = service.with_transport_callback(
        session_id,
        repetition=1,
        case_id="syn-b-001",
        callback=_callback,
    )
    assert result == "ok"
    assert seen == ["callback"]
    assert EVENT_DISCLOSED_TO_TRANSPORT in journal.read_text(encoding="utf-8")


def test_crash_started_without_terminal_reconciles_blocked_disclosure_uncertain(
    tmp_path: Path,
) -> None:
    generate = _load_generate()
    service, store, _clock, _state_root, _source_root, session_id = _ready_session(
        tmp_path, generate, session_id="crash-started"
    )
    service.record_outbound_attempt(session_id, repetition=1, case_id="syn-b-001")
    state = service.reconcile(session_id)
    assert state.state is RemoteEvalSessionState.BLOCKED
    assert state.blocked_reason_code == ERROR_DISCLOSURE_UNCERTAIN
    receipt = store.load_terminal_receipt(session_id)
    assert receipt is not None
    assert receipt.terminal_state is RemoteEvalSessionState.BLOCKED


def test_evaluator_identity_excludes_remote_eval_modules() -> None:
    assert evaluator_code_identity() == EVALUATOR_CODE_IDENTITY
    names = [path.name for path in evaluator_implementation_files()]
    assert not any(name.startswith("goodnotes_gsqs_remote_eval") for name in names)
    assert "goodnotes_gsqs.py" in names
