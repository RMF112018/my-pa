"""Composition root for the operator CLI.

    .venv/bin/python apps/cli/invoke.py capabilities.get \
        --request-id req-0001 --purpose status_observation \
        --principal-id prn_00000000000000000000000000 \
        --requested-at 2026-08-02T12:00:00Z

This is the third transport's entry point and the only place in it allowed to
choose an implementation (`module-boundaries.md` section 5.10). It loads
validated configuration, asks `bootstrap.gateway` for the runtime — the
application, the local principal, and the two connection pools that keep the
audit sink from starving the work it records — and hands both to
`adapters.cli`.

**It sits beside `migration.py` rather than replacing it.** `apps/cli/` already
held one operator command, and the two are different planes: `migration.py`
drives the legacy-to-PostgreSQL migration control plane, which is an operation
on the database, while this invokes a public capability, which is a request
against the application. They share `apps/cli/` because section 5.10 puts
operator commands there, and they share nothing else — no options, no runtime,
no output shape. Merging them under one program would have made a migration
phase look like a ninth capability.

**The same runtime as the gateway, deliberately.** A CLI that composed its own
`ApplicationService` could differ from the served one in a limit, a clock, or a
principal kind, and the difference would be invisible until it mattered.
`build_gateway_runtime` is what the HTTP and MCP transports are handed, so
"the CLI is not a privileged bypass" is a fact about the wiring rather than a
sentence in a review.

**No credential, no network** (`D-30`). This process opens the database
connection `MY_PA_DATABASE_URL` names and nothing else. It binds no port,
issues no token, and takes no `--principal` option: the acting principal is a
property of the process, and a flag that could change it would be the bypass
this file exists not to be.
"""

from __future__ import annotations

import sys

from my_pa.adapters.cli import run
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import load_settings


def main(argv: list[str] | None = None) -> int:
    """Invoke one capability and return the process exit status.

    The runtime is released on every path, including a refusal: an entry point
    that leaked a connection pool per invocation would exhaust the server one
    command at a time.
    """
    runtime = build_gateway_runtime(load_settings())
    try:
        return run(
            sys.argv[1:] if argv is None else argv,
            runtime.service,
            principal=runtime.principal,
            out=sys.stdout,
        )
    finally:
        runtime.close()


if __name__ == "__main__":
    sys.exit(main())
