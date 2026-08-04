"""Composition root for the gateway process.

    .venv/bin/python apps/gateway.py run
    .venv/bin/python apps/gateway.py run --port 9000
    .venv/bin/python apps/gateway.py mcp

This is the only place in the gateway that chooses an implementation
(`module-boundaries.md` section 5.10). It loads validated configuration, asks
`bootstrap.gateway` for the runtime — the application, the local principal, and
the two connection pools that keep the audit sink from starving the work it
records — builds a transport over them, and runs it.

**Two surfaces, one root.** Section 5.10 gives `apps.gateway` the HTTP *and*
MCP surfaces, and they are one program because they are one composition: the
same settings, the same application, the same principal, the same pools. `run`
serves HTTP on a loopback socket; `mcp` serves the Model Context Protocol on
standard input and output (`D-26`) and opens nothing. A third file would have
been a third place for the composition to drift.

**Loopback, and nothing else** (`D-30`). The host is a constant rather than a
flag. There is no option to bind elsewhere, because a flag that can be set wrong
is the mechanism by which a service reaches a network nobody authorized, and
`P00-OD-010` — which authentication mechanism this uses — is open and reserved
to the operator. No credential is issued, read, or required, and there is no TLS
or ingress path to configure.

**Shutdown, and what actually happens.** Uvicorn installs its own `SIGINT` and
`SIGTERM` handlers when the server runs on the main thread, and its shutdown
waits for the requests already in flight before the loop stops. That is the
behaviour this process wants, so it installs nothing of its own; a second
handler would race the one that already does the right thing.

What follows the graceful shutdown is worth stating rather than assuming,
because it was assumed once and measured wrong. Uvicorn restores the original
handlers and then **re-raises the signal it captured**, which is correct POSIX
behaviour — a process stopped by `SIGTERM` should exit *by* `SIGTERM`, status
143, not by returning zero — and it means `server.run()` does not return on that
path. The `finally` below therefore covers the paths where it does return, such
as a port already in use, and on a signal the pools are released by process exit
after the graceful shutdown has already finished. There is no line after `run`
claiming otherwise, because a line that cannot be reached is worse than none.

**And "waits" now has a bound.** Uvicorn's graceful shutdown is unbounded by
default, so a request that never finishes is a process that never stops — which
an independent review demonstrated with clients that announced a body and never
sent it. The transport bounds those itself now, and
`timeout_graceful_shutdown` is the backstop for everything it does not: after
it, uvicorn stops waiting and the process goes. A promise in a runbook that a
signal completes has to be a promise the process can keep.

**Logging.** Uvicorn is configured with no logging configuration and no access
log, and the application emits no log records at all — `tests/security` holds
that to be true rather than stated. What an operator sees is the two lines this
module prints at startup: what it is serving, and what it cannot serve. A
per-request log would be the one place a path, a query, or a principal could
reach a file, and this process does not have one.
"""

from __future__ import annotations

import argparse
import sys
from typing import Final

import uvicorn

from my_pa.adapters.http import create_http_app
from my_pa.adapters.mcp import serve_stdio
from my_pa.adapters.mcp.server import SERVER_NAME
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import load_settings

#: The only address this process binds. See the module docstring; `D-30`.
HOST: Final = "127.0.0.1"

#: An unassigned high port, changeable with `--port`. Nothing depends on the
#: number; it is here so that starting the process needs no arguments.
DEFAULT_PORT: Final = 8765

#: How long shutdown waits for the requests already in flight.
#:
#: Derived rather than chosen: it is the database engine's own connection
#: checkout timeout, which is the longest wait this process already accepts for
#: one request on a resource it bounds. A request still unfinished after that is
#: waiting on something that has itself already failed closed, so waiting longer
#: buys an operator nothing and costs them a process that will not stop.
#: Restated here because the engine's value is private to the module that builds
#: it; `test_the_shutdown_bound_is_the_pools_own_checkout_timeout` reads it off a
#: real engine, so the restatement is a checked claim rather than a guess.
GRACEFUL_SHUTDOWN_SECONDS: Final = 30

#: What the three source-reading capabilities will and will not answer, said by
#: the gateway itself at startup rather than left for an operator to infer from
#: an `unavailable` answer.
#:
#: **It states the condition; it does not assert an absence.** This line is
#: printed unconditionally on both surfaces and reads no store, so a sentence
#: asserting that no source is configured would be a claim this process has not
#: checked — and `apps/cli/sources.py register` makes it one an operator can
#: falsify. It is true whether or not a source has been registered, which is
#: what lets it stay unconditional and keeps a database read out of startup.
#: The defect it avoids is the one `application.disclosure` removed in this same
#: package: a sentence that outlived its condition because nothing connected the
#: two.
#:
#: `P00-OD-009` is untouched, and that half of the old sentence survives intact:
#: this composition configures no root and holds no default, so a source is
#: served only at the exact path an operator names when registering it.
_SOURCE_PROVIDER_NOTICE = (
    "notice      sources.list, sources.metadata and sources.fetch answer 'unavailable' for "
    "every source no operator has registered; registration names the source's root by exact "
    "path, and this process configures none"
)


def _run(args: argparse.Namespace) -> int:
    settings = load_settings()
    runtime = build_gateway_runtime(settings)
    application = create_http_app(runtime.service, principal=runtime.principal)
    server = uvicorn.Server(
        uvicorn.Config(
            application,
            host=HOST,
            port=args.port,
            # No logging configuration, no access log: see the module docstring.
            log_config=None,
            access_log=False,
            # The framework and its version are not this process's to announce.
            server_header=False,
            # Shutdown waits for work in flight, and no longer.
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        )
    )
    print(f"serving     http://{HOST}:{args.port}/v1/<capability>")
    print(_SOURCE_PROVIDER_NOTICE, flush=True)
    try:
        server.run()
    finally:
        # Reached when `run` returns rather than when a signal ends the process;
        # see the module docstring for why those are different paths.
        runtime.close()
    return 0


def _mcp(args: argparse.Namespace) -> int:
    """Serve the same capabilities over MCP, on standard input and output.

    **Standard output is the wire**, so the notice below goes to standard error
    and nothing else is printed at all. A startup line on the wrong stream is
    not a cosmetic problem here: it is a JSON-RPC parse failure on the client's
    first read, before `initialize` has been answered.

    No signal handler and no shutdown bound, because there is nothing to bind.
    The connection ends when the client closes the read side or when the process
    is signalled, and either way there is no socket to drain and no in-flight
    request the operating system will not end with the process. Uvicorn's
    graceful shutdown exists because a listening server outlives its clients;
    this one is the client's child.
    """
    settings = load_settings()
    runtime = build_gateway_runtime(settings)
    print(f"serving     mcp on stdio as {SERVER_NAME}", file=sys.stderr)
    print(_SOURCE_PROVIDER_NOTICE, file=sys.stderr, flush=True)
    try:
        serve_stdio(runtime.service, principal=runtime.principal)
    finally:
        runtime.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the my-pa gateway on loopback HTTP or on MCP over stdio."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="serve the fifteen capabilities over HTTP")
    run.add_argument("--port", type=int, default=DEFAULT_PORT)

    subcommands.add_parser("mcp", help="serve the fifteen capabilities over MCP on stdio")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse and dispatch.

    Dispatched by name rather than through a callable stored on the namespace,
    so that adding a subcommand without wiring it is a `match` that does not
    compile rather than an `AttributeError` at run time.
    """
    args = build_parser().parse_args(argv)
    match args.command:
        case "run":
            return _run(args)
        case "mcp":
            return _mcp(args)
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


if __name__ == "__main__":
    sys.exit(main())
