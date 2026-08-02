"""Composition root for the gateway process.

    .venv/bin/python apps/gateway.py run
    .venv/bin/python apps/gateway.py run --port 9000

This is the only place in the gateway that chooses an implementation
(`module-boundaries.md` section 5.10). It loads validated configuration, asks
`bootstrap.gateway` for the runtime — the application, the local principal, and
the two connection pools that keep the audit sink from starving the work it
records — builds the ASGI application over them, and runs it.

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
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import load_settings

#: The only address this process binds. See the module docstring; `D-30`.
HOST: Final = "127.0.0.1"

#: An unassigned high port, changeable with `--port`. Nothing depends on the
#: number; it is here so that starting the process needs no arguments.
DEFAULT_PORT: Final = 8765

#: What this gateway cannot do, said by the gateway itself at startup rather
#: than left for an operator to infer from an `unavailable` answer. Nothing
#: registers a source in production yet — `D-37` gives that to WP-4B3 — and no
#: provider root is authorized, because `P00-OD-009` requires the operator to
#: name one by exact path. So the three source-reading capabilities answer
#: `unavailable` for every source, truthfully.
_NO_PROVIDER_NOTICE = (
    "notice      no source provider is configured; sources.list, sources.metadata and "
    "sources.fetch answer 'unavailable' until a source is registered and a root authorized"
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
        )
    )
    print(f"serving     http://{HOST}:{args.port}/v1/<capability>")
    print(_NO_PROVIDER_NOTICE, flush=True)
    try:
        server.run()
    finally:
        # Reached when `run` returns rather than when a signal ends the process;
        # see the module docstring for why those are different paths.
        runtime.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the my-pa HTTP gateway on loopback.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="serve the eight capabilities over HTTP")
    run.add_argument("--port", type=int, default=DEFAULT_PORT)
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
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


if __name__ == "__main__":
    sys.exit(main())
