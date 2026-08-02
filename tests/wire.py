"""A real server on a real loopback socket, and a client made of the stdlib.

Every HTTP test in this repository goes through this. Two choices are worth
stating, because both were available and the other options were worse.

**A real uvicorn server rather than an in-process ASGI call.** The claims these
tests make are about what a caller receives: a status, a header set, and a body.
An in-process call would exercise the endpoint and skip the server that frames
the response, so "no header leaks" and "the process shuts down without
abandoning a request" would be asserted about something no client ever talks to.

**`http.client` rather than Starlette's `TestClient`.** `TestClient` needs
`httpx`, and this package does not depend on it; adding a dependency so that a
test can reach a loopback socket would be the tail wagging the dog when the
standard library already opens one. The bytes therefore pass through a socket
and uvicorn's HTTP parser in both directions, which is more of the path than a
test client covers.

**These are FAST tests, and the `network` marker does not apply.** That marker
means "requires network access": a test wearing it needs a name resolved, a
route out, and something on the other end that this repository does not control.
A server this process started, on `127.0.0.1`, on a port the kernel chose, needs
none of those — it runs with the machine offline, it depends on nothing outside
the test, and it is deterministic. What FAST forbids is a *database*, a network,
a connector, a model, or an end-to-end path; a loopback socket to an application
composed with in-memory fakes is none of them. The one HTTP test that needs
PostgreSQL is marked `database`, and it is marked for the database rather than
for the socket.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import apps.gateway as gateway
import uvicorn

#: How long to wait for the server to bind, and for it to stop again. Generous
#: for a loopback bind, and finite so a hung server fails the test rather than
#: the run.
_LIFECYCLE_TIMEOUT_SECONDS = 10.0

#: How long a client waits for one answer.
_REQUEST_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class Reply:
    """One HTTP answer, as the client received it."""

    status: int
    headers: Mapping[str, str]
    body: str

    def document(self) -> dict[str, Any]:
        """The body as JSON, or a failure that names the body's length only."""
        try:
            decoded = json.loads(self.body)
        except ValueError as exc:  # pragma: no cover - a failure path for a failing test
            raise AssertionError(f"the reply was not JSON ({len(self.body)} characters)") from exc
        assert isinstance(decoded, dict), "a reply is a JSON object"
        return decoded

    def rendered(self) -> str:
        """Status, every header, and the body, as one string to scan.

        The header names and values are included deliberately: a leak into a
        header is a leak, and a scan of the body alone would not see it.
        """
        headers = " ".join(f"{name}: {value}" for name, value in self.headers.items())
        return f"{self.status} {headers} {self.body}"


class Wire:
    """A client for one running gateway, and the handle that stops it."""

    def __init__(self, port: int, server: uvicorn.Server | None = None) -> None:
        self.port = port
        self._server = server

    def request_stop(self) -> None:
        """Ask the server to shut down, as a signal would.

        Uvicorn's own `SIGINT` and `SIGTERM` handlers set exactly this flag, so a
        test that sets it is exercising the shutdown an operator triggers rather
        than a second path built for testing.
        """
        assert self._server is not None, "this client was not given a server to stop"
        self._server.should_exit = True

    def send(
        self,
        capability: str,
        document: Mapping[str, Any] | None = None,
        *,
        raw: str | None = None,
        method: str = "POST",
        path: str | None = None,
        content_type: str | None = "application/json",
        omit_content_length: bool = False,
    ) -> Reply:
        """Send one request and read the whole answer.

        `raw` replaces the encoded document, so a test can send bytes that are
        not JSON at all. `omit_content_length` sends the body with chunked
        framing instead, which is the case the transport refuses.
        """
        body = raw if raw is not None else json.dumps(dict(document or {}))
        headers: dict[str, str] = {}
        if content_type is not None:
            headers["content-type"] = content_type
        if not omit_content_length:
            headers["content-length"] = str(len(body.encode()))
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.port, timeout=_REQUEST_TIMEOUT_SECONDS
        )
        try:
            if omit_content_length:
                connection.putrequest(method, path or f"/v1/{capability}")
                for name, value in headers.items():
                    connection.putheader(name, value)
                connection.putheader("transfer-encoding", "chunked")
                connection.endheaders()
                encoded = body.encode()
                connection.send(f"{len(encoded):x}\r\n".encode() + encoded + b"\r\n0\r\n\r\n")
            else:
                connection.request(method, path or f"/v1/{capability}", body=body, headers=headers)
            response = connection.getresponse()
            return Reply(
                status=response.status,
                headers={name.lower(): value for name, value in response.getheaders()},
                body=response.read().decode(),
            )
        finally:
            connection.close()


@contextmanager
def serve(application: object) -> Iterator[Wire]:
    """Run `application` on a kernel-chosen loopback port for the block.

    Port zero rather than a fixed number, so two tests never collide and a
    developer's own gateway is never talked to by mistake. The bound port is
    read back from the socket uvicorn opened.

    Configured exactly as `apps/gateway.py` configures it — no logging
    configuration, no access log, no server header, and the same bounded
    graceful shutdown, imported from the composition root rather than restated.
    A test that asserted a redaction or a shutdown property against a different
    configuration would be asserting it about a process nobody runs.
    """
    config = uvicorn.Config(
        application,
        host="127.0.0.1",
        port=0,
        log_config=None,
        access_log=False,
        server_header=False,
        timeout_graceful_shutdown=gateway.GRACEFUL_SHUTDOWN_SECONDS,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="gateway-under-test", daemon=True)
    thread.start()
    deadline = time.monotonic() + _LIFECYCLE_TIMEOUT_SECONDS
    while not server.started:
        assert time.monotonic() < deadline, "the gateway did not start"
        assert thread.is_alive(), "the gateway thread stopped before it started serving"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield Wire(int(port), server)
    finally:
        server.should_exit = True
        thread.join(timeout=_LIFECYCLE_TIMEOUT_SECONDS)
        assert not thread.is_alive(), "the gateway did not stop"
