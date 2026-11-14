"""Files workspace: the byte routes' pre-slot authentication cap (contract section 10.1).

FAST: a real uvicorn on loopback (`tests/wire.py`) in front of the real route
module, over stub gates: one whose `authenticate` blocks on an event -- the shape
of a slow ticket lookup under a flood of well-formed bogus tickets -- and one
that counts the download readers it opens and their closes. No database.
It proves:

* with every authentication permit in use, a further HEAD, PATCH or GET is 503
  `unavailable` with `Retry-After: 1` at once -- the slot-cap answer -- and no
  further `authenticate` call starts (nothing queues on the default executor);
* once the blocked checks return, the permits are back and a valid request runs;
* a request cancelled mid-check keeps its permit charged until its worker
  thread returns, then gives it back: none released early, none leaked;
* every GET exit -- 200, 206, 416 (past the end, or any range of a zero-byte
  file), a read refused after the open, and a request cancelled while its
  open or its first read is on a thread -- closes the download reader exactly
  once.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import threading
import time
from collections.abc import Callable, Iterator, MutableMapping
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.applications import Starlette
from tests.wire import serve

from my_pa.adapters.http.files_transfer import build_file_transfer_routes
from my_pa.application.file_transfer import FileTransferGate
from my_pa.contracts.ports import FileTransferKind
from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import FilesReason

TOKEN = "gfwtk_" + "b" * 64
UPLOAD = "/files/v1/uploads/fwup_synthetic"
DOWNLOAD = "/files/v1/downloads/fwdl_synthetic"
BUSY = b'{"error":"unavailable","reason":null}'


class _BlockingGate:
    """Just enough of `FileTransferGate` for HEAD; `authenticate` waits on `opened`."""

    def __init__(self) -> None:
        self.opened = threading.Event()
        self.lock = threading.Lock()
        self.entered = 0
        self.returned = 0

    @staticmethod
    def parse_id(_kind: FileTransferKind, path_id: object) -> str | None:
        return path_id if isinstance(path_id, str) and path_id else None

    def authenticate(
        self, _kind: FileTransferKind, _path_id: object, _authorization: object
    ) -> object:
        with self.lock:
            self.entered += 1
        try:
            assert self.opened.wait(timeout=30), "the test never opened the gate"
        finally:
            with self.lock:
                self.returned += 1
        return SimpleNamespace(ticket=SimpleNamespace(declared_size=None))

    @staticmethod
    def upload_offset(_access: object) -> int:
        return 0

    def wait_entered(self, count: int) -> None:
        deadline = time.monotonic() + 10
        while self.entered < count:
            assert time.monotonic() < deadline, f"only {self.entered} of {count} checks started"
            time.sleep(0.01)


def _app(gate: object, **options: Any) -> Starlette:  # noqa: ANN401
    routes = build_file_transfer_routes(cast(FileTransferGate, gate), **options)
    return Starlette(routes=list(routes))


def _request(
    port: int, method: str, path: str, *, timeout: float = 3.0, body: bytes | None = None
) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        if method == "PATCH":
            headers["Upload-Offset"] = "0"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        headers = {name.lower(): value for name, value in response.getheaders()}
        return response.status, headers, response.read()
    finally:
        connection.close()


def test_exhausted_auth_permits_are_503_at_once_and_come_back() -> None:
    gate = _BlockingGate()
    answers: list[int] = []

    def blocked_head(port: int) -> None:
        answers.append(_request(port, "HEAD", UPLOAD, timeout=20)[0])

    with serve(_app(gate, max_concurrent=4, max_concurrent_authentications=2)) as wire:
        holders = [threading.Thread(target=blocked_head, args=(wire.port,)) for _ in range(2)]
        try:
            for holder in holders:
                holder.start()
            gate.wait_entered(2)
            started = time.monotonic()
            for method, path, body in (
                ("HEAD", UPLOAD, None),
                ("PATCH", UPLOAD, b"x"),
                ("GET", DOWNLOAD, None),
            ):
                status, headers, content = _request(wire.port, method, path, body=body)
                assert status == 503, method
                assert headers["retry-after"] == "1", method
                assert content == (b"" if method == "HEAD" else BUSY), method
            assert time.monotonic() - started < 2, "a capped request waited"
            assert gate.entered == 2, "a refused request still started a ticket lookup"
        finally:
            gate.opened.set()
            for holder in holders:
                holder.join(timeout=20)
        assert sorted(answers) == [204, 204]
        # The permits came back: a valid request runs, twice over the cap.
        for _ in range(3):
            assert _request(wire.port, "HEAD", UPLOAD)[0] == 204


def _scope() -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "HEAD",
        "scheme": "http",
        "path": UPLOAD,
        "raw_path": UPLOAD.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"authorization", f"Bearer {TOKEN}".encode())],
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 80),
    }


async def _head(app: Starlette) -> int:
    statuses: list[int] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            statuses.append(message["status"])

    await app(_scope(), receive, send)
    return statuses[0]


def test_a_cancelled_check_keeps_its_permit_until_its_thread_returns() -> None:
    gate = _BlockingGate()
    app = _app(gate, max_concurrent=4, max_concurrent_authentications=1)

    async def scenario() -> None:
        first = asyncio.create_task(_head(app))
        while gate.entered < 1:
            await asyncio.sleep(0.01)
        first.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await first
        # Cancelled, but its lookup is still running: the permit stays charged.
        assert gate.returned == 0
        # At once, not after a wait: the permit is taken without queueing.
        assert await asyncio.wait_for(_head(app), timeout=2) == 503
        assert gate.entered == 1
        gate.opened.set()
        deadline = time.monotonic() + 10
        while gate.returned < 1:
            assert time.monotonic() < deadline, "the cancelled check never returned"
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)  # the done-callback runs on the next loop turn
        # Returned, and given back exactly once: one permit, so one at a time.
        assert await _head(app) == 204
        assert await _head(app) == 204

    asyncio.run(scenario())


# ---- the download reader is closed on every exit ----------------------------------


class _Reader:
    """A held-open download reader that counts its closes."""

    def __init__(
        self, body: bytes, *, fail: bool = False, block: threading.Event | None = None
    ) -> None:
        self.size = len(body)
        self.version = "v1"
        self.body = body
        self.fail = fail
        self.block = block
        self.reading = threading.Event()
        self.closes = 0

    def read_range(self, start: int, length: int) -> Iterator[bytes]:
        self.reading.set()
        if self.block is not None:
            assert self.block.wait(timeout=30), "the test never released the read"
        if self.fail:
            raise FilesRefusal("version", FilesReason.EXTERNAL_CHANGE_DETECTED)
        return iter([self.body[start : start + length]] if length else [])

    def close(self) -> None:
        self.closes += 1


class _ReaderGate:
    """Enough of `FileTransferGate` for GET; every `open_download` is recorded."""

    def __init__(self, make: Callable[[], _Reader], opening: threading.Event | None = None) -> None:
        self.make = make
        self.opening = opening
        self.entered = threading.Event()
        self.readers: list[_Reader] = []

    @staticmethod
    def parse_id(_kind: FileTransferKind, path_id: object) -> str | None:
        return path_id if isinstance(path_id, str) and path_id else None

    @staticmethod
    def authenticate(_kind: FileTransferKind, _path_id: object, _authorization: object) -> object:
        return SimpleNamespace(ticket=SimpleNamespace(expected_version="v1", declared_sha256=None))

    def open_download(self, _access: object) -> _Reader:
        self.entered.set()
        if self.opening is not None:
            assert self.opening.wait(timeout=30), "the test never released the open"
        reader = self.make()
        self.readers.append(reader)
        return reader


def _get(port: int, range_header: str | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        if range_header is not None:
            headers["Range"] = range_header
        connection.request("GET", DOWNLOAD, headers=headers)
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    finally:
        connection.close()


def _all_closed_once(readers: list[_Reader], count: int) -> None:
    deadline = time.monotonic() + 10
    while len(readers) < count or any(reader.closes == 0 for reader in readers):
        assert time.monotonic() < deadline, [reader.closes for reader in readers]
        time.sleep(0.01)
    time.sleep(0.05)  # a late second close would land here
    assert len(readers) == count
    assert [reader.closes for reader in readers] == [1] * count


def test_every_download_exit_closes_its_reader_exactly_once() -> None:
    body = b"0123456789"
    cases: list[tuple[bytes, bool, str | None, int]] = [
        (body, False, f"bytes={len(body)}-", 416),  # past the end
        (b"", False, "bytes=0-", 416),  # any range of a zero-byte file
        (body, False, None, 200),
        (body, False, "bytes=2-4", 206),
        (body, True, None, 412),  # the read refused after the open
    ]
    pending = list(cases)

    def make() -> _Reader:
        content, fail, _range, _status = pending.pop(0)
        return _Reader(content, fail=fail)

    gate = _ReaderGate(make)
    rounds = 20
    with serve(_app(gate, max_concurrent=1)) as wire:
        for _ in range(rounds):
            pending[:] = cases
            for content, _fail, range_header, status in cases:
                answer, headers, _payload = _get(wire.port, range_header)
                assert answer == status, (range_header, answer)
                if status == 416:
                    assert headers["content-range"] == f"bytes */{len(content)}"
        _all_closed_once(gate.readers, rounds * len(cases))
        # One slot, and every request above gave it back: none kept it.
        pending[:] = cases[2:3]
        assert _get(wire.port)[0] == 200
        _all_closed_once(gate.readers, rounds * len(cases) + 1)


@pytest.mark.parametrize("moment", ["opening", "reading"])
def test_a_download_cancelled_after_its_open_closes_the_reader(moment: str) -> None:
    release = threading.Event()
    gate = _ReaderGate(
        lambda: _Reader(b"abc", block=release if moment == "reading" else None),
        opening=release if moment == "opening" else None,
    )
    app = _app(gate, max_concurrent=1)

    async def get() -> None:
        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(_message: MutableMapping[str, Any]) -> None:
            return None

        scope = {**_scope(), "method": "GET", "path": DOWNLOAD, "raw_path": DOWNLOAD.encode()}
        await app(scope, receive, send)

    async def scenario() -> None:
        task = asyncio.create_task(get())
        entered = gate.entered if moment == "opening" else None
        deadline = time.monotonic() + 10
        while not (
            entered.is_set()
            if entered is not None
            else gate.readers and gate.readers[0].reading.is_set()
        ):
            assert time.monotonic() < deadline, "the request never reached its thread"
            await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        release.set()
        while not gate.readers or gate.readers[0].closes == 0:
            assert time.monotonic() < deadline, "the cancelled download never closed its reader"
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        assert [reader.closes for reader in gate.readers] == [1]

    asyncio.run(scenario())
