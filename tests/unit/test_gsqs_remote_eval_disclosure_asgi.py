"""ASGI send-path binding for GSQS remote-eval disclosure (Phase B Worker E).

DISCLOSED_TO_TRANSPORT is recorded only after a successful final
``http.response.body`` that carried image bytes. Tool return is not disclosure.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from mcp.types import ImageContent

from my_pa.adapters.gsqs_remote_eval_mcp import (
    EVAL_TOOL_NEXT,
    GsqsDisclosureAttempt,
    gsqs_eval_disclosure_attempt,
    invoke_gsqs_eval_tool,
    wrap_eval_asgi_send,
)
from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_DISCLOSURE_UNCERTAIN,
    EVENT_DISCLOSED_TO_TRANSPORT,
    EVENT_NOT_DISCLOSED,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    RemoteEvalError,
    RemoteEvalSessionState,
)
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import (
    JOURNAL_FILENAME,
    FilesystemDisclosureJournal,
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
ONE_BY_ONE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _clock() -> FakeClock:
    return FakeClock(datetime(2026, 8, 23, 12, 0, tzinfo=UTC))


def _journal(tmp_path: Path, clock: FakeClock | None = None) -> FilesystemDisclosureJournal:
    return FilesystemDisclosureJournal(tmp_path, clock=clock or _clock())


def _journal_file(tmp_path: Path, session_id: str = SESSION_ID) -> Path:
    return tmp_path / "sessions" / session_id / "journal" / JOURNAL_FILENAME


def _events(tmp_path: Path, session_id: str = SESSION_ID) -> list[dict[str, object]]:
    path = _journal_file(tmp_path, session_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _types(tmp_path: Path, session_id: str = SESSION_ID) -> list[str]:
    return [str(event["event_type"]) for event in _events(tmp_path, session_id)]


def _start(journal: FilesystemDisclosureJournal) -> str:
    return journal.start_outbound_attempt(
        session_id=SESSION_ID,
        repetition=1,
        case_id=CASE_ID,
        content_sha256=CONTENT_SHA256,
    )


def _wrap(send: object, journal: FilesystemDisclosureJournal) -> object:
    return wrap_eval_asgi_send(
        send,  # type: ignore[arg-type]
        confirm_disclosed=lambda session_id, attempt_id: journal.confirm_disclosed_to_transport(
            session_id=session_id, attempt_id=attempt_id
        ),
        confirm_not_disclosed=lambda session_id, attempt_id: journal.confirm_not_disclosed(
            session_id=session_id, attempt_id=attempt_id
        ),
    )


def _finalize(wrapped: object) -> None:
    closer = getattr(wrapped, "finalize", None)
    if callable(closer):
        closer()


def _image_json_body() -> bytes:
    data = base64.standard_b64encode(ONE_BY_ONE_PNG).decode("ascii")
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"mime_type": "image/png"}, separators=(",", ":")),
                    },
                    {"type": "image", "data": data, "mimeType": "image/png"},
                ]
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _error_json_body() -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "denied"}}
    ).encode("utf-8")


async def _identity_send(message: Mapping[str, object]) -> None:
    _ = message


class _RecordingSend:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def __call__(self, message: Mapping[str, object]) -> None:
        self.messages.append(dict(message))


class _RaiseOnBody:
    def __init__(self, *, on_body: int = 1) -> None:
        self.messages: list[dict[str, object]] = []
        self._on_body = on_body
        self._bodies = 0

    async def __call__(self, message: Mapping[str, object]) -> None:
        self.messages.append(dict(message))
        if message.get("type") == "http.response.body":
            self._bodies += 1
            if self._bodies == self._on_body:
                raise OSError("send failed")


class _FailOnStartJournal(FilesystemDisclosureJournal):
    def start_outbound_attempt(
        self,
        *,
        session_id: str,
        repetition: int,
        case_id: str,
        content_sha256: str,
    ) -> str:
        _ = (session_id, repetition, case_id, content_sha256)
        raise OSError("STARTED write failed")


class _FailOnDisclosedJournal(FilesystemDisclosureJournal):
    def confirm_disclosed_to_transport(self, *, session_id: str, attempt_id: str) -> None:
        _ = (session_id, attempt_id)
        raise OSError("DISCLOSED persist failed")


class _FailDuringDisclosedAppendJournal(FilesystemDisclosureJournal):
    def _append(self, path: Path, payload: Mapping[str, object]) -> None:
        if payload.get("event_type") == EVENT_DISCLOSED_TO_TRANSPORT:
            raise OSError("fsync failed during DISCLOSED")
        super()._append(path, payload)


@dataclass
class _Principal:
    principal_id: str = "principal-1"


class _RasterReader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read_png(
        self,
        *,
        session_id: str,
        staged_filename: str,
        content_sha256: str,
        byte_length: int,
    ) -> bytes:
        _ = (session_id, staged_filename, content_sha256, byte_length)
        return self.payload


class _SendAssertingStarted:
    def __init__(self, tmp_path: Path, session_id: str) -> None:
        self.tmp_path = tmp_path
        self.session_id = session_id
        self.checked_image_body = False
        self.messages: list[dict[str, object]] = []

    async def __call__(self, message: Mapping[str, object]) -> None:
        self.messages.append(dict(message))
        if message.get("type") == "http.response.body":
            types = _types(self.tmp_path, self.session_id)
            assert EVENT_OUTBOUND_ATTEMPT_STARTED in types
            assert EVENT_DISCLOSED_TO_TRANSPORT not in types
            self.checked_image_body = True


def _in_progress_service(tmp_path: Path) -> tuple[RemoteEvalService, FakeStore, str, bytes]:
    clock = _clock()
    store = FakeStore()
    journal = FilesystemDisclosureJournal(tmp_path, clock=clock)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=FakeStaging(),
        disclosure=journal,
    )
    session = service.create_session(_request(clock, session_id=SESSION_ID))
    service.seal_ready(session.session_id)
    service.open_repetition(session.session_id, 1)
    png = ONE_BY_ONE_PNG
    digest = sha256(png).hexdigest()
    manifest = store.manifests[session.session_id]
    cases = list(manifest.cases)
    cases[0] = replace(cases[0], content_sha256=digest, byte_length=len(png))
    store.manifests[session.session_id] = replace(manifest, cases=tuple(cases))
    return service, store, session.session_id, png


async def _send_response(
    wrapped: object,
    body: bytes,
    *,
    more_body: bool = False,
    start: bool = True,
) -> None:
    sender = wrapped  # wrap_eval_asgi_send result
    if start:
        await sender({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[misc]
    await sender(  # type: ignore[misc]
        {"type": "http.response.body", "body": body, "more_body": more_body}
    )


def test_wrap_without_callbacks_remains_identity() -> None:
    async def send(message: object) -> None:
        _ = message

    assert wrap_eval_asgi_send(send) is send
    wrapped = wrap_eval_asgi_send(send, disclosure_journal=object(), attempt_getter=lambda: None)
    assert wrapped is send


def test_before_started_write_no_started_no_image_send(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    token = gsqs_eval_disclosure_attempt.set(None)
    try:

        async def _run() -> None:
            wrapped = _wrap(_identity_send, journal)
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert not _journal_file(tmp_path).exists()
    assert _types(tmp_path) == []


def test_during_started_write_fail_closed_no_disclosed(tmp_path: Path) -> None:
    journal = _FailOnStartJournal(tmp_path, clock=_clock())
    recorder = _RecordingSend()
    with pytest.raises(OSError, match="STARTED write failed"):
        journal.start_outbound_attempt(
            session_id=SESSION_ID,
            repetition=1,
            case_id=CASE_ID,
            content_sha256=CONTENT_SHA256,
        )
    token = gsqs_eval_disclosure_attempt.set(None)
    try:

        async def _run() -> None:
            wrapped = _wrap(recorder, journal)
            with pytest.raises(RuntimeError, match="without outbound attempt"):
                await _send_response(wrapped, _image_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert not _journal_file(tmp_path).exists()
    assert EVENT_DISCLOSED_TO_TRANSPORT not in _types(tmp_path)
    assert EVENT_OUTBOUND_ATTEMPT_STARTED not in _types(tmp_path)
    assert not any(message.get("type") == "http.response.body" for message in recorder.messages)


def test_after_started_before_http_body_not_disclosed_when_send_skipped(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_identity_send, journal)
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED, EVENT_NOT_DISCLOSED]


def test_disconnect_after_start_without_body_is_unreconciled(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_identity_send, journal)
            await wrapped({"type": "http.response.start", "status": 200, "headers": []})
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    assert journal.reconcile_on_restart(session_id=SESSION_ID).uncertain is True


def test_send_raises_on_first_image_chunk_leaves_started_unreconciled(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_RaiseOnBody(on_body=1), journal)
            with pytest.raises(OSError, match="send failed"):
                await _send_response(wrapped, _image_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    assert journal.reconcile_on_restart(session_id=SESSION_ID).uncertain is True


def test_partial_body_then_raise_leaves_started_unreconciled(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_RaiseOnBody(on_body=2), journal)
            await wrapped({"type": "http.response.start", "status": 200, "headers": []})
            await wrapped(
                {"type": "http.response.body", "body": _image_json_body(), "more_body": True}
            )
            with pytest.raises(OSError, match="send failed"):
                await wrapped({"type": "http.response.body", "body": b"", "more_body": False})
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    assert journal.reconcile_on_restart(session_id=SESSION_ID).uncertain is True


def test_confirm_disclosed_persist_raises_after_final_body_leaves_unreconciled(
    tmp_path: Path,
) -> None:
    journal = _FailOnDisclosedJournal(tmp_path, clock=_clock())
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_identity_send, journal)
            with pytest.raises(OSError, match="DISCLOSED persist failed"):
                await _send_response(wrapped, _image_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    assert journal.reconcile_on_restart(session_id=SESSION_ID).uncertain is True


def test_confirm_disclosed_during_persistence_leaves_unreconciled(tmp_path: Path) -> None:
    journal = _FailDuringDisclosedAppendJournal(tmp_path, clock=_clock())
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_identity_send, journal)
            with pytest.raises(OSError, match="fsync failed during DISCLOSED"):
                await _send_response(wrapped, _image_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    assert EVENT_DISCLOSED_TO_TRANSPORT not in _journal_file(tmp_path).read_text(encoding="utf-8")
    assert journal.reconcile_on_restart(session_id=SESSION_ID).uncertain is True


def test_restart_reconcile_unresolved_started_blocks_session(tmp_path: Path) -> None:
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
    attempt_id = service.record_outbound_attempt(session.session_id, repetition=1, case_id=CASE_ID)
    assert attempt_id
    assert _types(tmp_path, session.session_id) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    restarted = RemoteEvalService(
        store=store,
        clock=clock,
        staging=staging,
        disclosure=FilesystemDisclosureJournal(tmp_path, clock=clock),
    )
    state = restarted.reconcile(session.session_id)
    assert state.state is RemoteEvalSessionState.BLOCKED
    assert state.blocked_reason_code == ERROR_DISCLOSURE_UNCERTAIN
    report = disclosure.reconcile_on_restart(session_id=session.session_id)
    assert report.uncertain is True
    assert EVENT_NOT_DISCLOSED not in _journal_file(tmp_path, session.session_id).read_text(
        encoding="utf-8"
    )


def test_started_is_durable_before_image_bytes_are_handed_to_asgi_send(tmp_path: Path) -> None:
    clock = _clock()
    store = FakeStore()
    journal = FilesystemDisclosureJournal(tmp_path, clock=clock)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=FakeStaging(),
        disclosure=journal,
    )
    session = service.create_session(_request(clock, session_id=SESSION_ID))
    attempt_id = service.record_outbound_attempt(session.session_id, repetition=1, case_id=CASE_ID)
    assert _types(tmp_path, session.session_id) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=session.session_id, attempt_id=attempt_id)
    )
    spy = _SendAssertingStarted(tmp_path, session.session_id)
    try:

        async def _run() -> None:
            wrapped = wrap_eval_asgi_send(spy, service=service)
            await _send_response(wrapped, _image_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert spy.checked_image_body is True
    assert _types(tmp_path, session.session_id) == [
        EVENT_OUTBOUND_ATTEMPT_STARTED,
        EVENT_DISCLOSED_TO_TRANSPORT,
    ]


def test_happy_path_final_image_body_records_disclosed(tmp_path: Path) -> None:
    clock = _clock()
    store = FakeStore()
    staging = FakeStaging()
    journal = FilesystemDisclosureJournal(tmp_path, clock=clock)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=staging,
        disclosure=journal,
    )
    session = service.create_session(_request(clock, session_id=SESSION_ID))
    attempt_id = service.record_outbound_attempt(session.session_id, repetition=1, case_id=CASE_ID)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=session.session_id, attempt_id=attempt_id)
    )
    recorder = _RecordingSend()
    try:

        async def _run() -> None:
            wrapped = wrap_eval_asgi_send(recorder, service=service)
            await _send_response(wrapped, _image_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert recorder.messages[-1]["type"] == "http.response.body"
    assert _types(tmp_path, session.session_id) == [
        EVENT_OUTBOUND_ATTEMPT_STARTED,
        EVENT_DISCLOSED_TO_TRANSPORT,
    ]
    report = journal.reconcile_on_restart(session_id=session.session_id)
    assert report.uncertain is False
    assert report.disclosed_count == 1


def test_text_only_error_body_after_started_is_not_disclosed(tmp_path: Path) -> None:
    journal = _journal(tmp_path)
    attempt_id = _start(journal)
    token = gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=SESSION_ID, attempt_id=attempt_id)
    )
    try:

        async def _run() -> None:
            wrapped = _wrap(_identity_send, journal)
            await _send_response(wrapped, _error_json_body())
            _finalize(wrapped)

        asyncio.run(_run())
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert _types(tmp_path) == [EVENT_OUTBOUND_ATTEMPT_STARTED, EVENT_NOT_DISCLOSED]


def test_tool_imagecontent_without_asgi_send_is_not_disclosed_to_transport(tmp_path: Path) -> None:
    service, store, session_id, png = _in_progress_service(tmp_path)
    token = gsqs_eval_disclosure_attempt.set(None)
    try:
        result = invoke_gsqs_eval_tool(
            EVAL_TOOL_NEXT,
            {},
            principal=_Principal(),
            service=service,
            store=store,
            raster_reader=_RasterReader(png),
        )
        assert result.is_error is False
        assert isinstance(result.content[1], ImageContent)
        assert _types(tmp_path, session_id) == [EVENT_OUTBOUND_ATTEMPT_STARTED]
        wrapped = wrap_eval_asgi_send(  # type: ignore[arg-type]
            _identity_send,
            service=service,
        )
        _finalize(wrapped)
    finally:
        gsqs_eval_disclosure_attempt.reset(token)
    assert EVENT_DISCLOSED_TO_TRANSPORT not in _types(tmp_path, session_id)
    assert _types(tmp_path, session_id) == [
        EVENT_OUTBOUND_ATTEMPT_STARTED,
        EVENT_NOT_DISCLOSED,
    ]


def test_service_confirm_helpers_do_not_change_capture_logic(tmp_path: Path) -> None:
    clock = _clock()
    store = FakeStore()
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=FakeStaging(),
        disclosure=_journal(tmp_path, clock),
    )
    session = service.create_session(_request(clock, session_id=SESSION_ID))
    attempt_id = service.record_outbound_attempt(session.session_id, repetition=1, case_id=CASE_ID)
    service.confirm_not_disclosed(session.session_id, attempt_id)
    with pytest.raises(RemoteEvalError):
        service.confirm_disclosed_to_transport(session.session_id, attempt_id)
    assert _types(tmp_path, session.session_id) == [
        EVENT_OUTBOUND_ATTEMPT_STARTED,
        EVENT_NOT_DISCLOSED,
    ]
    status = service.status(session.session_id)
    assert status.state is not RemoteEvalSessionState.BLOCKED
