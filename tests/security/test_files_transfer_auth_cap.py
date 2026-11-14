"""Files workspace: the byte routes' pre-slot authentication cap (contract section 10.1).

FAST: a real uvicorn on loopback (`tests/wire.py`) in front of the real route
module, over a stub gate whose `authenticate` blocks on an event -- the shape of
a slow ticket lookup under a flood of well-formed bogus tickets. No database.
It proves:

* with every authentication permit in use, a further HEAD, PATCH or GET is 503
  `unavailable` with `Retry-After: 1` at once -- the slot-cap answer -- and no
  further `authenticate` call starts (nothing queues on the default executor);
* once the blocked checks return, the permits are back and a valid request runs;
* a request cancelled mid-check keeps its permit charged until its worker
  thread returns, then gives it back: none released early, none leaked.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import threading
import time
from collections.abc import MutableMapping
from types import SimpleNamespace
from typing import Any, cast

from starlette.applications import Starlette
from tests.wire import serve

from my_pa.adapters.http.files_transfer import build_file_transfer_routes
from my_pa.application.file_transfer import FileTransferGate
from my_pa.contracts.ports import FileTransferKind

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


def _app(gate: _BlockingGate, **options: Any) -> Starlette:  # noqa: ANN401
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
