"""Filesystem JSONL v2 disclosure journal: durability, crash uncertainty, containment."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_DISCLOSURE_UNCERTAIN,
    ERROR_INTERNAL_FAIL_CLOSED,
    EVENT_DISCLOSED_TO_TRANSPORT,
    EVENT_NOT_DISCLOSED,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    SCHEMA_DISCLOSURE_JOURNAL_V2,
    RemoteEvalError,
    RemoteEvalSessionState,
)
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import (
    JOURNAL_FILENAME,
    FilesystemDisclosureJournal,
    wrap_transport,
)
from tests.unit.test_goodnotes_gsqs_remote_eval_state import (
    FakeClock,
    FakeStaging,
    FakeStore,
    _request,
)

SESSION_ID = "sess-1"
CASE_ID = "syn-b-001"
CONTENT_SHA256 = sha256(b"synthetic-raster").hexdigest()


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 8, 23, 12, 0, tzinfo=UTC))


def _journal(tmp_path: Path, clock: FakeClock | None = None) -> FilesystemDisclosureJournal:
    return FilesystemDisclosureJournal(tmp_path, clock=clock or _clock())


def _journal_file(tmp_path: Path, session_id: str = SESSION_ID) -> Path:
    return tmp_path / "sessions" / session_id / "journal" / JOURNAL_FILENAME


def _events(tmp_path: Path, session_id: str = SESSION_ID) -> list[dict[str, object]]:
    lines = _journal_file(tmp_path, session_id).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_started_is_durable_before_simulated_send(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    seen: list[str] = []

    def _callback() -> str:
        body = _journal_file(tmp_path).read_text(encoding="utf-8")
        assert EVENT_OUTBOUND_ATTEMPT_STARTED in body
        parsed = json.loads(body.splitlines()[0])
        assert parsed["event_type"] == EVENT_OUTBOUND_ATTEMPT_STARTED
        assert parsed["journal_schema_version"] == SCHEMA_DISCLOSURE_JOURNAL_V2
        seen.append(body)
        return "ok"

    result = wrap_transport(
        journal,
        SESSION_ID,
        1,
        CASE_ID,
        CONTENT_SHA256,
        _callback,
    )
    assert result == "ok"
    assert seen
    types = [event["event_type"] for event in _events(tmp_path)]
    assert types == [EVENT_OUTBOUND_ATTEMPT_STARTED, EVENT_DISCLOSED_TO_TRANSPORT]


def test_successful_disclosed_reconcile_is_certain(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )
    journal.confirm_disclosed_to_transport(session_id=SESSION_ID, attempt_id=attempt_id)
    report = journal.reconcile_on_restart(session_id=SESSION_ID)
    raw = _journal_file(tmp_path).read_bytes()
    assert report.uncertain is False
    assert report.started_count == 1
    assert report.disclosed_count == 1
    assert report.not_disclosed_count == 0
    assert report.journal_sha256 == sha256(raw).hexdigest()
    assert report.journal_sha256 is not None
    assert len(report.journal_sha256) == 64


def test_explicit_pre_send_not_disclosed_is_not_uncertain(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )
    journal.confirm_not_disclosed(session_id=SESSION_ID, attempt_id=attempt_id)
    report = journal.reconcile_on_restart(session_id=SESSION_ID)
    assert report.uncertain is False
    assert report.started_count == 1
    assert report.disclosed_count == 0
    assert report.not_disclosed_count == 1
    types = [event["event_type"] for event in _events(tmp_path)]
    assert types == [EVENT_OUTBOUND_ATTEMPT_STARTED, EVENT_NOT_DISCLOSED]


def test_crash_after_started_reconciles_uncertain_on_new_instance(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )
    body = _journal_file(tmp_path).read_text(encoding="utf-8")
    assert EVENT_OUTBOUND_ATTEMPT_STARTED in body
    assert EVENT_DISCLOSED_TO_TRANSPORT not in body
    assert EVENT_NOT_DISCLOSED not in body
    restarted = _journal(tmp_path)
    report = restarted.reconcile_on_restart(session_id=SESSION_ID)
    assert report.uncertain is True
    assert report.started_count == 1
    assert report.disclosed_count == 0
    assert report.not_disclosed_count == 0
    assert EVENT_NOT_DISCLOSED not in _journal_file(tmp_path).read_text(encoding="utf-8")


def test_service_reconcile_blocks_when_filesystem_journal_is_uncertain(tmp_path: Path) -> None:
    clock = _clock()
    store = FakeStore()
    staging = FakeStaging()
    disclosure = FilesystemDisclosureJournal(tmp_path, clock=clock)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=staging,
        disclosure=disclosure,
    )
    session = service.create_session(_request(clock, session_id=SESSION_ID))
    seen: list[str] = []

    def _callback() -> str:
        body = _journal_file(tmp_path, session.session_id).read_text(encoding="utf-8")
        assert EVENT_OUTBOUND_ATTEMPT_STARTED in body
        seen.append(body)
        raise RuntimeError("transport interrupted after STARTED")

    with pytest.raises(RuntimeError, match="interrupted"):
        service.with_transport_callback(
            session.session_id,
            repetition=1,
            case_id=CASE_ID,
            callback=_callback,
        )
    assert seen
    state = service.reconcile(session.session_id)
    assert state.state is RemoteEvalSessionState.BLOCKED
    assert state.blocked_reason_code == ERROR_DISCLOSURE_UNCERTAIN
    stored = store.load_state(session.session_id)
    assert stored is not None
    assert stored.state is RemoteEvalSessionState.BLOCKED
    assert stored.blocked_reason_code == ERROR_DISCLOSURE_UNCERTAIN
    report = disclosure.reconcile_on_restart(session_id=session.session_id)
    assert report.uncertain is True
    assert EVENT_NOT_DISCLOSED not in _journal_file(tmp_path, session.session_id).read_text(
        encoding="utf-8"
    )


def test_uncertain_disclosure_is_not_auto_retried_or_inferred(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )
    second = journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id="syn-b-002",
        content_sha256=sha256(b"second").hexdigest(),
    )
    report = journal.reconcile_on_restart(session_id=SESSION_ID)
    assert report.uncertain is True
    assert report.started_count == 2
    assert report.disclosed_count == 0
    assert report.not_disclosed_count == 0
    body = _journal_file(tmp_path).read_text(encoding="utf-8")
    assert EVENT_NOT_DISCLOSED not in body
    assert body.count(EVENT_OUTBOUND_ATTEMPT_STARTED) == 2
    journal.confirm_not_disclosed(session_id=SESSION_ID, attempt_id=second)
    still = journal.reconcile_on_restart(session_id=SESSION_ID)
    assert still.uncertain is True
    assert still.started_count == 2
    assert still.not_disclosed_count == 1
    assert still.disclosed_count == 0


def test_forbidden_keys_rejected_and_absent_from_journal_body(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )
    with pytest.raises(RemoteEvalError) as exc:
        journal._append(
            _journal_file(tmp_path),
            {"event_type": "X", "gold": "secret-label", "image": "bytes", "path": "nope"},
        )
    assert exc.value.code == ERROR_INTERNAL_FAIL_CLOSED
    body = _journal_file(tmp_path).read_text(encoding="utf-8")
    assert "gold" not in body
    assert "image" not in body
    assert "path" not in body
    assert "authorization" not in body
    assert "secret" not in body
    payload = _events(tmp_path)[0]
    assert not {"gold", "image", "path", "authorization", "secret"} & set(payload)


def test_journal_permissions_are_restrictive(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )
    path = _journal_file(tmp_path)
    assert (path.stat().st_mode & 0o777) == 0o600
    assert (path.parent.stat().st_mode & 0o777) == 0o700


def test_v1_module_is_not_the_implementation() -> None:
    source = Path("src/my_pa/application/goodnotes_gsqs_remote_eval_disclosure.py").read_text(
        encoding="utf-8"
    )
    assert "goodnotes_gsqs_b0_disclosure_journal" not in source
    assert "datetime.now" not in source
    assert "utc_now(" not in source
    assert "FilesystemDisclosureJournal" in source


def test_invalid_session_id_and_missing_attempt(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    for invalid in ("sess/1", "sess-1/../x", "has..dots", "nul\x00id", ""):
        with pytest.raises(RemoteEvalError) as exc:
            journal.start_outbound_attempt(
                session_id=invalid,
                repetition=1,
                case_id=CASE_ID,
                content_sha256=CONTENT_SHA256,
            )
        assert exc.value.code == ERROR_INTERNAL_FAIL_CLOSED
    with pytest.raises(RemoteEvalError) as missing:
        journal.confirm_disclosed_to_transport(session_id=SESSION_ID, attempt_id="missing")
    assert missing.value.code == ERROR_INTERNAL_FAIL_CLOSED
    assert not _journal_file(tmp_path).exists()


def test_symlink_session_dir_is_refused(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (tmp_path / "outside").mkdir()
    (sessions / SESSION_ID).symlink_to(tmp_path / "outside")
    journal = _journal(tmp_path)
    with pytest.raises(RemoteEvalError) as exc:
        journal.start_outbound_attempt(
            session_id=SESSION_ID,
            repetition=1,
            case_id=CASE_ID,
            content_sha256=CONTENT_SHA256,
        )
    assert exc.value.code == ERROR_INTERNAL_FAIL_CLOSED


def test_wrap_transport_exception_does_not_write_not_disclosed(tmp_path: Path) -> None:
    journal = _journal(tmp_path)

    def _callback() -> str:
        raise TimeoutError("send failed after STARTED")

    with pytest.raises(TimeoutError):
        wrap_transport(journal, SESSION_ID, 1, CASE_ID, CONTENT_SHA256, _callback)
    body = _journal_file(tmp_path).read_text(encoding="utf-8")
    assert EVENT_OUTBOUND_ATTEMPT_STARTED in body
    assert EVENT_NOT_DISCLOSED not in body
    assert EVENT_DISCLOSED_TO_TRANSPORT not in body
    assert journal.reconcile_on_restart(session_id=SESSION_ID).uncertain is True
