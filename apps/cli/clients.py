"""Operator command: mint, revoke, and observe remote capture client credentials.

    .venv/bin/python apps/cli/clients.py register
    .venv/bin/python apps/cli/clients.py list
    .venv/bin/python apps/cli/clients.py revoke --client-id cclt_...
    .venv/bin/python apps/cli/clients.py status

**Minting a credential is reserved to the operator** (`AGENTS.md` section 8.2:
"credential creation, disclosure, rotation, or mutation"), so this is a command
an operator runs on their own machine and not an HTTP capability anybody can
reach. That is not a stylistic preference. A registration *capability* would have
to be admitted to `Capability`, to `audit_events.capability_is_known`, and to the
policy decision — and the thing it would authorize is the minting of credentials
that authenticate future requests, which is the one grant a compromised caller
would want most. `D-42` already rules that configuration is not a capability;
this is the same ruling applied to something sharper than configuration.

**The secret is printed once and never stored.** `issue_client_secret` produces
the plaintext and its digest in one expression, `register_client` stores only the
digest, and the plaintext exists in this process only long enough to be written
to standard output. There is no command to read it back, because there is no
column holding it. An operator who loses it revokes the client and mints another.

**The binding is the mode's, not the operator's.** Under
`MY_PA_AUTH_MODE=local_operator` — the default — this process serves exactly one
Principal, and a client minted here is bound to that Principal by
`principal_bound_values` reading the context. There is no `--principal-id` flag
and there will not be one: a flag naming the Principal a credential acts for is
caller-supplied identity with a longer lifetime than a request, and `D-13`/`D-14`
keep that out of this tree. Under `entra` this command **refuses**, for the
reason `apps/gateway.py mcp` refuses there: a shell carries no bearer token, so
there is no authenticated Principal to bind to, and binding to the local operator
instead would be exactly the silent downgrade that mode exists to prevent.

**`status` reads and states; it does not enable.** It reports whether the ingress
is configured to serve, at which address, and how many clients are active — and
it says plainly that serving is on loopback and that publishing the address is an
operator act this repository does not perform.

**It is not a further capability.** It builds no `ApplicationService`, no
`Principal`, and no transport, exactly as `sources.py` and `health.py` do not,
and `tests/architecture/test_operator_commands_are_not_capabilities.py` decides
that by reading this file. It writes no audit event for the same reason
`sources.py` writes none: the row is its own evidence, `created_at` and
`revoked_at` are `NOT NULL` exactly when they mean something, and recording a
registration in `audit_events` would need a capability name this command must not
have.

**Nothing is echoed that was not asked for.** A refusal names the defect and
never a value; the listing prints identifiers, states and times and holds no
secret, no digest, and no note.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import Engine

from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.domain.capture.client import issue_client_secret
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture_clients import (
    clients_of,
    register_client,
    revoke_client,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context

#: What a refusal is worth to a shell. `0` and `1` and nothing finer, exactly as
#: `sources.py` decides it: a caller scripting this needs "did it work".
EXIT_OK = 0
EXIT_REFUSED = 1

#: The address the ingress serves at, restated rather than imported. Importing it
#: would mean importing `my_pa.adapters`, which is the package this command is
#: forbidden to reach — and being able to name a capability path is how an
#: operator command starts becoming a transport. `test_remote_ingress_status_names_the_real_path`
#: compares the two, so the restatement is a checked claim.
INGRESS_PATH = "/remote/v1/capture.create"


def _engine() -> Engine:
    return create_database_engine(
        load_settings().parsed_database_url(), statement_timeout_ms=30_000
    )


def _bound_principal(settings: Settings) -> str:
    """The Principal a client minted by this process is bound to, or a refusal.

    `None` means the process authenticates real people per request and there is
    no Principal a shell can speak for. Refused rather than defaulted: the only
    default available is the local operator, and silently binding a credential to
    it in a mode configured to authenticate somebody else is the downgrade that
    mode exists to prevent.
    """
    admissible = settings.admissible_client_principal_id()
    if admissible is None:
        raise ValueError(
            f"{ENV_PREFIX}AUTH_MODE authenticates each request and a shell carries "
            "no credential, so there is no authenticated Principal to bind a "
            "capture client to. Mint clients from a process configured for the "
            "local operator, deliberately"
        )
    return admissible


def _register(args: argparse.Namespace) -> int:
    """Mint one client bound to this process's Principal, and print its secret once."""
    context = capture_context(_bound_principal(load_settings()))
    secret, digest = issue_client_secret()
    engine = _engine()
    try:
        with engine.begin() as connection:
            client = register_client(
                connection, secret_sha256=digest, at=datetime.now(UTC), context=context
            )
    finally:
        engine.dispose()

    print(f"client_id        {client.client_id}")
    print(f"principal_id     {client.principal_id}")
    print(f"state            {client.state.value}")
    print(f"registered       {client.created_at.isoformat()}")
    print(f"credential       {client.client_id}:{secret}")
    print(
        "notice           the credential above is shown once and is stored only as "
        "a SHA-256 digest. Copy it now; there is no command that reads it back. "
        "Present it as `Authorization: ClientCredential <credential>`"
    )
    return EXIT_OK


def _revoke(args: argparse.Namespace) -> int:
    """Revoke one of this Principal's clients. Refuses if it changed nothing.

    "Changed nothing" covers an unknown identifier, another Principal's client,
    and one that was already revoked, and they are reported as one line for the
    reason the ingress answers them as one refusal: distinguishing them here
    would be an operator-facing existence oracle over a table an operator can
    already list.
    """
    context = capture_context(_bound_principal(load_settings()))
    engine = _engine()
    try:
        with engine.begin() as connection:
            revoked = revoke_client(
                connection, args.client_id, at=datetime.now(UTC), context=context
            )
    finally:
        engine.dispose()

    if not revoked:
        print("refused          no active client of this Principal carries that identifier")
        return EXIT_REFUSED
    print(f"client_id        {args.client_id}")
    print("state            revoked")
    print("notice           the credential is refused from the next request onward")
    return EXIT_OK


def _list(args: argparse.Namespace) -> int:
    """Print one line per client of this Principal, and no secret."""
    context = capture_context(_bound_principal(load_settings()))
    engine = _engine()
    try:
        with engine.connect() as connection:
            registered = clients_of(connection, context=context)
    finally:
        engine.dispose()

    for client in registered:
        revoked = "-" if client.revoked_at is None else client.revoked_at.isoformat()
        print(
            f"{client.client_id}  {client.state.value:<8s}  "
            f"{client.created_at.isoformat()}  {revoked}"
        )
    print(f"clients     {len(registered)}")
    return EXIT_OK


def _status(args: argparse.Namespace) -> int:
    """State whether the ingress serves, where, and how many clients are active.

    Read-only, and honest about what "serving" means: the process binds loopback
    and nothing else, so an enabled ingress is reachable from this machine.
    Publishing it is a deployment act this repository does not perform.
    """
    settings = load_settings()
    admissible = settings.admissible_client_principal_id()
    print(f"ingress          {'enabled' if settings.remote_ingress_enabled else 'disabled'}")
    print(f"path             {INGRESS_PATH}")
    print("credential       Authorization: ClientCredential <client_id>:<secret>")
    print(f"auth_mode        {settings.auth_mode.value}")
    print(
        f"binds_to         {admissible if admissible is not None else 'the authenticated caller'}"
    )
    if admissible is None:
        print("clients          not counted; this process binds no Principal a shell can name")
        return EXIT_OK
    engine = _engine()
    try:
        with engine.connect() as connection:
            registered = clients_of(connection, context=capture_context(admissible))
    finally:
        engine.dispose()
    active = sum(1 for client in registered if client.usable)
    print(f"clients          {active} active of {len(registered)} registered")
    print(
        "notice           the gateway binds 127.0.0.1 only. Reaching this ingress "
        "from another device needs a TLS-terminating proxy or tunnel the operator "
        "runs; nothing in this repository publishes it"
    )
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clients", description="Mint and revoke my-pa remote capture client credentials."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("register", help="mint one client credential and print it once")
    revoke = commands.add_parser("revoke", help="refuse one client credential from now on")
    revoke.add_argument("--client-id", required=True, help="the client to revoke, by identifier")
    commands.add_parser("list", help="print this Principal's clients, without secrets")
    commands.add_parser("status", help="print whether the remote ingress serves, and where")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse, dispatch, and turn a refusal into an exit status.

    The refusals this command produces are a mode that cannot bind a Principal
    and a malformed identifier, both `ValueError`, and both messages name the
    defect rather than the value. Anything else propagates: a driver failure is
    not a refusal, and reporting it as one would tell an operator to fix their
    arguments.
    """
    args = build_parser().parse_args(argv)
    try:
        match args.command:
            case "register":
                return _register(args)
            case "revoke":
                return _revoke(args)
            case "list":
                return _list(args)
            case "status":
                return _status(args)
            case unknown:  # pragma: no cover - argparse rejects an unknown command first
                raise SystemExit(f"unhandled command {unknown!r}")
    except ValueError as refusal:
        print(f"refused     {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
