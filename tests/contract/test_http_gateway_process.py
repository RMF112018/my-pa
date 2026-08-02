"""The gateway is a process: it starts, it serves, and it stops without dropping work.

`apps/worker.py` earned this file's counterpart in WP-4B1 and the claim is the
same one: a composition root that cannot be started is a module, and a shutdown
that abandons a request in flight is a data-loss path wearing the word "clean".

Three things are asserted here that no request-level test can reach:

* a server binds, answers, and its thread ends — the loop stops rather than
  being left running by a daemon flag;
* a request that is *inside* the application when shutdown is asked for still
  receives its complete envelope, and the thread ends afterwards. The shutdown
  is requested by setting the flag uvicorn's own signal handlers set, so this
  exercises the operator's path and not a second one built for the test;
* the composition root binds loopback and offers no way not to (`D-30`), reads
  no credential, and configures no TLS.
"""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import apps.gateway as gateway
import pytest
import uvicorn
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeProviders,
    FakeUnitOfWork,
    Scene,
    World,
    operator,
)
from tests.wire import Reply, Wire, serve

import my_pa.adapters.http.app as app_module
from my_pa.adapters.http import create_http_app
from my_pa.application.commands import Command
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine

GATEWAY_SOURCE = Path(gateway.__file__).read_text(encoding="utf-8")


def document(capability: Capability, principal: Principal, purpose: Purpose) -> dict[str, Any]:
    return {
        "request_id": f"req-{capability.value}",
        "purpose": purpose.value,
        "principal_id": principal.principal_id,
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": {},
    }


class HeldService(ApplicationService):
    """The real service, held open inside `invoke` until a test lets it finish.

    The pause is *inside* the application, which is what makes the shutdown test
    about an in-flight request rather than about a request that had not started.
    """

    def __init__(self, world: World) -> None:
        super().__init__(
            unit_of_work=lambda: FakeUnitOfWork(world),
            providers=FakeProviders({}),
            limits=DEFAULT_LIMITS,
            clock=lambda: WHEN,
        )
        self.entered = threading.Event()
        self.release = threading.Event()

    def invoke(
        self, metadata: RequestMetadata, command: Command, *, principal: Principal
    ) -> ResponseEnvelope:
        self.entered.set()
        assert self.release.wait(timeout=10), "the test never released the request"
        return super().invoke(metadata, command, principal=principal)


@pytest.fixture
def wire(scene: Scene) -> Iterator[Wire]:
    from tests.conftest import build_service

    with serve(
        create_http_app(build_service(scene.world, scene.providers), principal=scene.principal)
    ) as client:
        yield client


def test_the_gateway_starts_serves_and_stops(scene: Scene, wire: Wire) -> None:
    """`serve` asserts the thread ended; this asserts it served first."""
    reply = wire.send(
        Capability.CAPABILITIES_GET.value,
        document(Capability.CAPABILITIES_GET, scene.principal, Purpose.STATUS_OBSERVATION),
    )
    assert reply.status == 200
    assert reply.document()["result"]["manifest"]["capabilities"]


# ---- a client that announces a body and does not send it ---------------------


class Stalled:
    """Open connections that declare a `content-length` and send no body.

    The shape an independent review used to take the gateway down: each costs
    about 130 bytes and no credential, and each pinned one thread of Starlette's
    pool for as long as the client cared to wait. `D-27` puts the endpoint in a
    thread, so the stall cannot be made to cost nothing; what it can be made is
    bounded, and these tests assert exactly that and not more.
    """

    def __init__(self, port: int, count: int) -> None:
        self._sockets: list[socket.socket] = []
        for _ in range(count):
            opened = socket.create_connection(("127.0.0.1", port), timeout=5)
            opened.sendall(
                b"POST /v1/capabilities.get HTTP/1.1\r\n"
                b"host: 127.0.0.1\r\n"
                b"content-type: application/json\r\n"
                b"content-length: 4096\r\n"
                b"\r\n"
            )
            self._sockets.append(opened)

    def close(self) -> None:
        for opened in self._sockets:
            opened.close()


#: More stalled clients than Starlette's default thread pool holds, so every
#: worker is occupied and the next request has nowhere to run. Forty is anyio's
#: default token count; forty-five is the reviewer's measurement.
STALLED_CLIENTS = 45


def test_a_client_that_never_sends_its_body_does_not_take_the_gateway_down(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stall is bounded and self-clearing, and the gateway keeps answering.

    The bound is shortened for the test rather than waited out: five seconds
    times two rounds of forty-five clients is a slow test proving the same
    property a fast one proves. `test_the_body_timeout_is_the_servers_own_idle_bound`
    is what holds the production value.
    """
    from tests.conftest import build_service

    monkeypatch.setattr(app_module, "BODY_TIMEOUT_SECONDS", 0.5)
    with serve(
        create_http_app(build_service(scene.world, scene.providers), principal=scene.principal)
    ) as client:
        stalled = Stalled(client.port, STALLED_CLIENTS)
        try:
            started = time.monotonic()
            reply = client.send(
                Capability.CAPABILITIES_GET.value,
                document(Capability.CAPABILITIES_GET, scene.principal, Purpose.STATUS_OBSERVATION),
            )
            elapsed = time.monotonic() - started
        finally:
            stalled.close()

    assert reply.status == 200, reply.body
    # Every stalled worker is released within the bound, so the honest claim is
    # that a real request waits for at most the rounds it takes to clear them —
    # not that it is unaffected, which a synchronous endpoint cannot promise.
    assert elapsed < 10, f"a real request waited {elapsed:.1f}s behind stalled clients"


def test_a_stalled_body_is_refused_as_an_incomplete_request(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The refusal is the transport's own vocabulary, and it arrives on time.

    Timed to the first byte rather than to the close, which is a distinction
    worth keeping: reading to EOF measures `BODY_TIMEOUT_SECONDS` *plus*
    uvicorn's keep-alive idle, because a connection whose request body was never
    consumed cannot be reused and is closed only after that. Measuring the close
    would have read as a bound twice its real size, and did once.
    """
    from tests.conftest import build_service

    bound = 0.5
    monkeypatch.setattr(app_module, "BODY_TIMEOUT_SECONDS", bound)
    with serve(
        create_http_app(build_service(scene.world, scene.providers), principal=scene.principal)
    ) as client:
        opened = socket.create_connection(("127.0.0.1", client.port), timeout=10)
        try:
            opened.sendall(
                b"POST /v1/capabilities.get HTTP/1.1\r\n"
                b"host: 127.0.0.1\r\n"
                b"content-type: application/json\r\n"
                b"content-length: 4096\r\n"
                b"\r\n"
            )
            started = time.monotonic()
            received = opened.recv(4096)
            answered = time.monotonic() - started
            # The body may share the first packet with the headers or follow in
            # a second one; read on only while it has not arrived, because an
            # unconditional second `recv` blocks whenever it already has.
            opened.settimeout(5)
            while b'"invalid_request"' not in received:
                chunk = opened.recv(4096)
                if not chunk:
                    break
                received += chunk
            answer = received.decode()
        finally:
            opened.close()

    assert "400" in answer.splitlines()[0], answer.splitlines()[0]
    assert '"invalid_request"' in answer
    assert "Traceback" not in answer
    assert bound <= answered < bound + 2, (
        f"the refusal arrived after {answered:.2f}s against a {bound}s bound"
    )


def test_a_shutdown_completes_with_stalled_clients_attached(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The promise `apps/gateway.py` and the runbook make to an operator.

    It did not hold: with stalled clients attached the server did not stop after
    `should_exit`. Two things now make it hold — the body timeout releases the
    workers, and `timeout_graceful_shutdown` bounds the wait for anything it
    does not cover. `serve` asserts the thread ended, so leaving the block *is*
    the assertion; the elapsed bound is what distinguishes "stopped" from
    "stopped eventually".
    """
    from tests.conftest import build_service

    monkeypatch.setattr(app_module, "BODY_TIMEOUT_SECONDS", 0.5)
    started = time.monotonic()
    with serve(
        create_http_app(build_service(scene.world, scene.providers), principal=scene.principal)
    ) as client:
        stalled = Stalled(client.port, STALLED_CLIENTS)
    stalled.close()
    elapsed = time.monotonic() - started
    assert elapsed < gateway.GRACEFUL_SHUTDOWN_SECONDS, (
        f"shutdown took {elapsed:.1f}s with {STALLED_CLIENTS} stalled clients attached"
    )


def test_the_body_timeout_is_the_servers_own_idle_bound() -> None:
    """The derivation, checked rather than trusted.

    `adapters/http` may not import uvicorn — running a server is the composition
    root's act — so the number is restated there. A restated constant is a claim,
    and this is the check: the transport waits for an unfinished request exactly
    as long as the server already waits for an idle connection.
    """
    idle = uvicorn.Config(app=None).timeout_keep_alive
    assert idle == app_module.BODY_TIMEOUT_SECONDS, (
        f"the body timeout is {app_module.BODY_TIMEOUT_SECONDS}s and uvicorn's idle "
        f"bound is {idle}s; the derivation in `app.py` no longer holds"
    )


def test_the_shutdown_bound_is_the_pools_own_checkout_timeout() -> None:
    """The other derivation, checked the same way, against a real engine."""
    engine = create_database_engine("postgresql+psycopg://someone@db.invalid:5432/somewhere")
    try:
        assert engine.pool._timeout == gateway.GRACEFUL_SHUTDOWN_SECONDS
    finally:
        engine.dispose()


def test_a_request_in_flight_is_not_abandoned_by_a_shutdown(world: World) -> None:
    """Shutdown waits for the request that is already inside the application."""
    principal = operator()
    service = HeldService(world)
    replies: list[Reply] = []
    failures: list[BaseException] = []

    with serve(create_http_app(service, principal=principal)) as client:

        def call() -> None:
            try:
                replies.append(
                    client.send(
                        Capability.CAPABILITIES_GET.value,
                        document(
                            Capability.CAPABILITIES_GET, principal, Purpose.STATUS_OBSERVATION
                        ),
                    )
                )
            except BaseException as error:
                failures.append(error)

        caller = threading.Thread(target=call, name="in-flight-caller")
        caller.start()
        assert service.entered.wait(timeout=10), "the request never reached the application"

        # The request is inside `invoke`. Ask the server to stop, exactly as a
        # signal would, and only then let the request finish.
        client.request_stop()
        service.release.set()
        caller.join(timeout=20)

    assert not failures, f"the in-flight request failed: {failures}"
    assert not caller.is_alive()
    assert len(replies) == 1
    assert replies[0].status == 200, replies[0].body
    envelope = replies[0].document()
    assert envelope["error"] is None
    assert envelope["disclosure"] is not None, "the answer arrived incomplete"


def test_a_request_that_starts_after_a_shutdown_is_refused_rather_than_half_served(
    scene: Scene,
) -> None:
    """The other side of the same guarantee: a stopped server is stopped.

    Not "returns an error" — a stopped server has no answer to give and the
    connection is refused or closed. The property is that nothing half-serves.
    """
    from tests.conftest import build_service

    with serve(
        create_http_app(build_service(scene.world, scene.providers), principal=scene.principal)
    ) as client:
        assert (
            client.send(
                Capability.CAPABILITIES_GET.value,
                document(Capability.CAPABILITIES_GET, scene.principal, Purpose.STATUS_OBSERVATION),
            ).status
            == 200
        )
        stopped = client
    with pytest.raises(OSError):
        stopped.send(
            Capability.CAPABILITIES_GET.value,
            document(Capability.CAPABILITIES_GET, scene.principal, Purpose.STATUS_OBSERVATION),
        )


# ---- the composition root ----------------------------------------------------


def test_the_gateway_binds_loopback_and_offers_no_way_not_to() -> None:
    """`D-30`, as a property of the source rather than of a default.

    A `--host` flag with a loopback default would satisfy "binds loopback" on
    every run until the one where it does not.
    """
    assert gateway.HOST == "127.0.0.1"
    args = gateway.build_parser().parse_args(["run"])
    assert not hasattr(args, "host"), "the gateway grew a way to bind elsewhere"
    assert args.port == gateway.DEFAULT_PORT
    with pytest.raises(SystemExit):
        gateway.build_parser().parse_args(["run", "--host", "127.0.0.2"])

    addresses = set(re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", GATEWAY_SOURCE))
    assert addresses == {"127.0.0.1"}, f"the composition root names {addresses}"


def test_the_gateway_issues_reads_and_requires_no_credential() -> None:
    """`P00-OD-010` is open, so no authentication mechanism is selected."""
    forbidden = (
        "ssl_",
        "certfile",
        "keyfile",
        "ssl_certfile",
        "password",
        "token",
        "api_key",
        "Authorization",
        "authenticate",
    )
    for name in forbidden:
        assert name not in GATEWAY_SOURCE, f"the gateway names {name!r}"


def test_the_gateway_configures_the_server_the_harness_mirrors() -> None:
    """The redaction tests run against `tests/wire.py`'s configuration.

    That is only evidence about the real process while the two agree, so the
    three settings that matter are asserted to be present here as well.
    """
    for setting in ("log_config=None", "access_log=False", "server_header=False"):
        assert setting in GATEWAY_SOURCE, f"the gateway no longer sets {setting}"


def test_the_gateway_parser_requires_a_subcommand() -> None:
    with pytest.raises(SystemExit):
        gateway.build_parser().parse_args([])
    args = gateway.build_parser().parse_args(["run"])
    assert args.command == "run"
    assert args.port == gateway.DEFAULT_PORT


# ---- the process itself ------------------------------------------------------


def _free_port() -> int:
    """A port nothing is listening on. The gateway takes a number, not a zero."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_the_gateway_process_starts_serves_and_exits_by_its_signal(tmp_path: Path) -> None:
    """`apps/gateway.py` as an operator runs it: a process, a socket, a signal.

    No database is reachable, which is deliberate rather than a compromise.
    `create_engine` does not connect, so the process starts and serves, and the
    request then fails because the store cannot be reached — a classified,
    redacted answer from a real process, which is what proves the composition
    root is wired. The claim here is about the process; `tests/concurrency` is
    where the store is real.

    **It fails `503 unavailable`, and the code is half the point of the test.**
    An unreachable server is `unavailable` in the contract's taxonomy:
    conditionally retryable, and a statement about the store rather than about
    the product. It answered `500 internal_error` until WP-4B2a, because opening
    the transaction was the one path in `SqlAlchemyUnitOfWork` that skipped the
    translation every read goes through, so a connect failure reached `invoke`'s
    terminal catch as an unclassified exception. Nothing leaked either way —
    that catch is what stopped the connection string reaching the caller, and
    the assertions below still require it — but a caller told the product is
    broken does something different from one told the database is down.

    The exit status is the assertion that caught a wrong docstring: uvicorn
    re-raises the signal it captured after shutting down gracefully, so the
    process exits *by* `SIGTERM` — status `-15` as Python reports it — rather
    than returning zero. A test that only asserted "it stopped" would have let
    the claim that the pools are disposed on that path survive.
    """
    port = _free_port()
    environment = {
        **os.environ,
        "MY_PA_DATABASE_URL": "postgresql+psycopg://someone@127.0.0.1:1/nothing",
    }
    process = subprocess.Popen(  # noqa: S603 - fixed argument list, no shell
        [sys.executable, str(Path(gateway.__file__)), "run", "--port", str(port)],
        cwd=Path(gateway.__file__).resolve().parents[1],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        client = Wire(port)
        deadline = time.monotonic() + 30
        while True:
            assert process.poll() is None, "the gateway exited before it served"
            assert time.monotonic() < deadline, "the gateway never bound its port"
            try:
                reply = client.send(
                    Capability.CAPABILITIES_GET.value,
                    document(
                        Capability.CAPABILITIES_GET,
                        operator(),
                        Purpose.STATUS_OBSERVATION,
                    ),
                )
            except OSError:
                time.sleep(0.05)
                continue
            break
        assert reply.status == 503, reply.body
        assert reply.document()["error"]["code"] == "unavailable"
        assert reply.document()["error"]["retry"] == "conditional"
        # And the URL it failed to reach is not in the answer.
        for fragment in ("127.0.0.1:1", "psycopg", "OperationalError", "Traceback"):
            assert fragment not in reply.rendered(), f"the answer disclosed {fragment!r}"

        process.send_signal(signal.SIGTERM)
        output = process.communicate(timeout=30)[0]
    finally:
        if process.poll() is None:  # pragma: no cover - only on a hung server
            process.kill()
            process.communicate(timeout=10)

    assert process.returncode == -signal.SIGTERM, f"exit {process.returncode}: {output}"
    assert f"serving     http://127.0.0.1:{port}" in output
    assert "no source provider is configured" in output
    # Nothing per-request was written: the process prints two lines and logs none.
    assert "capabilities.get" not in output
    assert "Traceback" not in output
