"""One logical request, expressed three ways, answered three ways.

`SPEC-AC-001` asks that HTTP, MCP, and the CLI produce byte-equivalent
normalised requests and semantically identical answers. A test can only make
that comparison if it can say "this request" once and send it over all three, so
this module is what turns one document into three protocols and three answers
back into one comparable shape.

**What is deliberately *not* shared.** Each transport is driven the way a real
caller drives it — a socket and a real uvicorn server for HTTP, the SDK's own
client session over a real JSON-RPC exchange for MCP, an argument vector for the
CLI. Nothing calls `normalize` on a transport's behalf and nothing bypasses a
protocol, because a harness that shortcut the protocol would be comparing three
copies of the same call rather than three transports.

**What each transport's `Answer` flattens.** The three carry success differently
— an HTTP status, MCP's `isError`, an exit status — so `failed` is each
transport's own signal, normalised to a boolean, and the parity assertions
compare it. `rendered` is everything a caller could see: for HTTP the status
line, every header, and the body; for MCP the whole `CallToolResult` including
its error flag and content blocks; for the CLI standard output *and* standard
error together, because a leak into either is a leak.

**The MCP session runs on its own loop in its own thread.** The SDK is async and
`Answer`-returning `send` is not, which is the same boundary `adapters/mcp`
crosses in production and is crossed here the same way: the loop is owned for the
length of the block and requests are scheduled onto it. The streams are the
SDK's in-memory pair rather than a subprocess, so the JSON-RPC framing,
`initialize`, `tools/list` and `tools/call` are all real while a test costs no
process spawn. `tests/contract/test_mcp_transport.py` runs the real stdio
transport in a real child process once, which is the claim this harness does not
make.

Everything is synthetic. No live source, no real path, no real person.
"""

from __future__ import annotations

import asyncio
import io
import json
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager, redirect_stderr, suppress
from dataclasses import dataclass
from typing import Any, Protocol

from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import CallToolResult, InitializeResult, ListToolsResult
from tests.wire import serve

from my_pa.adapters.cli import EXIT_OK, run
from my_pa.adapters.http import create_http_app
from my_pa.adapters.mcp import create_mcp_server
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.principal import Principal

#: How long one request may take, and how long the MCP session has to start.
#: Generous for an in-memory exchange, finite so a hang fails a test rather than
#: the run.
TIMEOUT_SECONDS = 20.0

#: The command-line option that supplies each envelope field. The CLI's own
#: mapping is in `adapters/cli/app.py`; this is the caller's side of it, and
#: `test_the_harness_offers_every_option_the_cli_declares` compares the two so a
#: field the CLI grows cannot go untested here.
CLI_OPTIONS: Mapping[str, str] = {
    "request_id": "--request-id",
    "purpose": "--purpose",
    "principal_id": "--principal-id",
    "requested_at": "--requested-at",
    "contract_version": "--contract-version",
}

#: The repeatable options that rebuild the declared scope from a flat shell.
CLI_SCOPE_OPTIONS: Mapping[str, str] = {
    "source_ids": "--scope-source-id",
    "enrollment_ids": "--scope-enrollment-id",
}


@dataclass(frozen=True, slots=True)
class Answer:
    """One transport's complete answer to one request."""

    #: The response document, decoded. A `ResponseEnvelope` for a request that
    #: reached the application, a bare `ProblemDetail` for one that did not.
    document: dict[str, Any]
    #: The transport's own success signal, normalised.
    failed: bool
    #: Everything a caller could see, as one string to scan for a leak.
    rendered: str


class Transport(Protocol):
    """One way of reaching the eight capabilities."""

    name: str

    def send(self, capability: str, document: Mapping[str, Any] | None = None) -> Answer:
        """Send one request and read the whole answer."""


def _decode(body: str, where: str) -> dict[str, Any]:
    try:
        decoded = json.loads(body)
    except ValueError as exc:  # pragma: no cover - a failure path for a failing test
        raise AssertionError(f"{where} answered {len(body)} characters that are not JSON") from exc
    assert isinstance(decoded, dict), f"{where} answered a JSON value that is not an object"
    return decoded


class HttpTransport:
    """The HTTP gateway, over a real loopback socket."""

    name = "http"

    def __init__(self, wire: Any) -> None:  # noqa: ANN401 - tests.wire.Wire
        self._wire = wire

    def send(self, capability: str, document: Mapping[str, Any] | None = None) -> Answer:
        reply = self._wire.send(capability, dict(document or {}))
        return Answer(
            document=_decode(reply.body, "http"),
            failed=reply.status != 200,
            rendered=reply.rendered(),
        )


class McpTransport:
    """The MCP server, over the SDK's own client and a real JSON-RPC exchange."""

    name = "mcp"

    def __init__(self, loop: asyncio.AbstractEventLoop, session: ClientSession) -> None:
        self._loop = loop
        self._session = session

    def _call(self, coroutine: Any) -> Any:  # noqa: ANN401 - any SDK result
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(TIMEOUT_SECONDS)

    def initialize_result(self) -> InitializeResult:
        """What the server said in the handshake. Read from the client's own record."""
        result = self._session.initialize_result
        assert result is not None, "the session was not initialized"
        return result

    def list_tools(self) -> ListToolsResult:
        """`tools/list`, over the protocol."""
        result = self._call(self._session.list_tools())
        assert isinstance(result, ListToolsResult)
        return result

    def call(self, capability: str, document: Mapping[str, Any] | None = None) -> CallToolResult:
        """`tools/call`, returning the SDK's own result object."""
        result = self._call(self._session.call_tool(capability, dict(document or {})))
        assert isinstance(result, CallToolResult)
        return result

    def send(self, capability: str, document: Mapping[str, Any] | None = None) -> Answer:
        result = self.call(capability, document)
        blocks = [getattr(block, "text", "") for block in result.content]
        assert len(blocks) == 1, f"mcp answered {len(blocks)} content blocks"
        return Answer(
            document=_decode(blocks[0], "mcp"),
            failed=bool(result.is_error),
            rendered=repr(result),
        )


class CliTransport:
    """The operator CLI, driven by an argument vector.

    Standard error is captured as well as standard output, and the assertion
    that it stayed empty is `tests/security`'s. Here it is folded into
    `rendered`, so a marker written to the wrong stream is still found.
    """

    name = "cli"

    def __init__(self, service: ApplicationService, principal: Principal) -> None:
        self._service = service
        self._principal = principal

    @staticmethod
    def argv(capability: str, document: Mapping[str, Any] | None = None) -> list[str]:
        """The command line an operator would type for `document`.

        A field the CLI does not declare becomes the option an operator would
        have typed for it — `not_a_field` becomes `--not-a-field`. Dropping it
        instead would have made the CLI unable to express a request the other
        two transports refuse, and a refusal nobody can send is not a refusal
        the parity matrix has compared.
        """
        fields = dict(document or {})
        argv = [capability]
        for field, value in fields.items():
            if field in {"payload", "scope"}:
                continue
            option = CLI_OPTIONS.get(field, f"--{field.replace('_', '-')}")
            argv += [option, str(value)]
        for field, option in CLI_SCOPE_OPTIONS.items():
            for value in dict(fields.get("scope") or {}).get(field, ()):
                argv += [option, str(value)]
        if "payload" in fields:
            argv += ["--payload", json.dumps(fields["payload"])]
        return argv

    def run(self, argv: Sequence[str]) -> Answer:
        """Run one argument vector, whatever it says. Used for malformed input."""
        out, err = io.StringIO(), io.StringIO()
        with redirect_stderr(err):
            status = run(argv, self._service, principal=self._principal, out=out)
        body = out.getvalue()
        return Answer(
            document=_decode(body, "cli"),
            failed=status != EXIT_OK,
            rendered=f"exit {status} stdout {body} stderr {err.getvalue()}",
        )

    def send(self, capability: str, document: Mapping[str, Any] | None = None) -> Answer:
        return self.run(self.argv(capability, document))


@contextmanager
def http_transport(service: ApplicationService, principal: Principal) -> Iterator[HttpTransport]:
    with serve(create_http_app(service, principal=principal)) as wire:
        yield HttpTransport(wire)


@contextmanager
def mcp_transport(service: ApplicationService, principal: Principal) -> Iterator[McpTransport]:
    """A running MCP server and an initialized client, on a private event loop.

    The server is configured exactly as `serve_stdio` configures it — the same
    `create_mcp_server`, the same initialization options, and `raise_exceptions`
    left at its production default, so a handler that raised would produce the
    protocol error a real client would see rather than a traceback a test could
    read. A harness that turned exceptions into assertions would be asserting
    about a server nobody runs.
    """
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="mcp-under-test", daemon=True)
    thread.start()
    ready = threading.Event()
    stopping = asyncio.Event()
    connected: list[McpTransport] = []

    async def session() -> None:
        async with create_client_server_memory_streams() as (client_streams, server_streams):
            server = create_mcp_server(service, principal=principal)
            serving = asyncio.create_task(
                server.run(
                    server_streams[0], server_streams[1], server.create_initialization_options()
                )
            )
            try:
                async with ClientSession(client_streams[0], client_streams[1]) as client:
                    await client.initialize()
                    connected.append(McpTransport(loop, client))
                    ready.set()
                    await stopping.wait()
            finally:
                ready.set()
                serving.cancel()

    running = asyncio.run_coroutine_threadsafe(session(), loop)
    try:
        assert ready.wait(TIMEOUT_SECONDS), "the mcp session did not start"
        assert connected, "the mcp session failed before it was initialized"
        yield connected[0]
    finally:
        loop.call_soon_threadsafe(stopping.set)
        # The serving task is cancelled as the session closes, so its own
        # cancellation is the expected way this ends rather than a failure.
        with suppress(asyncio.CancelledError):
            running.result(TIMEOUT_SECONDS)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=TIMEOUT_SECONDS)
        assert not thread.is_alive(), "the mcp session did not stop"
        loop.close()


@contextmanager
def cli_transport(service: ApplicationService, principal: Principal) -> Iterator[CliTransport]:
    yield CliTransport(service, principal)


#: Every transport, in the order the parity assertions report them. A test
#: parametrised over this covers a fourth transport by its being added here.
TRANSPORTS = (http_transport, mcp_transport, cli_transport)


@contextmanager
def all_transports(
    service: ApplicationService, principal: Principal
) -> Iterator[tuple[Transport, ...]]:
    """All three, over the same application and the same principal."""
    with ExitStack() as stack:
        yield tuple(stack.enter_context(build(service, principal)) for build in TRANSPORTS)
