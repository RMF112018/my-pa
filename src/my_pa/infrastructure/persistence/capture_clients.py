"""Minting, revoking, listing, and authenticating one registered capture client.

Four operations over `knowledge.capture_clients`, and the split between them is
the whole design of this module.

**Three are principal-scoped and one cannot be.** `register_client`,
`revoke_client` and `clients_of` all run for a Principal the caller has already
established, so each reaches the partition through
`infrastructure.persistence.principal_scope` — `principal_bound_values` stamps
the insert and `partition_criterion`/`principal_scoped` constrain the update and
the read. `authenticate_client` is the exception and it is the same exception
`jobs.job_principal` is: it *derives* the Principal from a credential, so a
partition predicate there would be circular — it would need the answer in order
to ask the question. It is registered as such in
`tests/architecture/test_principal_partition_is_reached_through_the_guard.py`
rather than left as an unexplained unscoped read.

**The secret digest never leaves this module.** `authenticate_client` takes the
presented secret, compares it against the stored digest inside its own function
body, and returns a `RegisteredCaptureClient`, which has no field a digest could
occupy. Returning the digest to a composition root and comparing it there would
have worked identically and would have put a credential-derived value into a
second module for no gain.

**A refusal is one refusal.** An unknown client, a wrong secret, and a revoked
client all return `None`. The caller turns that into one 401 with one body, so
none of the three is distinguishable to whoever is guessing — which matters most
for the revoked case, since "this credential used to work" is exactly what an
attacker holding a leaked one wants to learn.

**Nothing here logs.** The package emits no log records at all (`apps/gateway.py`
states it and `tests/security` holds it), and this module is where a helpful
`logger.info("client %s authenticated", client_id)` would have been most
tempting.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Connection, Row, select

from my_pa.domain.capture.client import (
    ClientState,
    RegisteredCaptureClient,
    secret_matches,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
    require_principal_context,
)
from my_pa.infrastructure.persistence.tables import capture_clients

__all__ = [
    "authenticate_client",
    "clients_of",
    "register_client",
    "revoke_client",
]

#: The columns a client is rebuilt from. Written out rather than
#: `select(capture_clients)` so that `secret_sha256` has to be asked for by name
#: — which is what keeps it out of every read except the one that verifies it.
_CLIENT_COLUMNS = (
    capture_clients.c.client_id,
    capture_clients.c.principal_id,
    capture_clients.c.state,
    capture_clients.c.created_at,
    capture_clients.c.revoked_at,
)


def _to_client(row: Row[tuple[object, ...]]) -> RegisteredCaptureClient:
    mapping = row._mapping
    return RegisteredCaptureClient(
        client_id=str(mapping["client_id"]),
        principal_id=str(mapping["principal_id"]),
        state=ClientState(mapping["state"]),
        created_at=mapping["created_at"],
        revoked_at=mapping["revoked_at"],
    )


def register_client(
    connection: Connection,
    *,
    secret_sha256: str,
    at: datetime,
    context: PrincipalContext,
) -> RegisteredCaptureClient:
    """Mint one client bound to the context's Principal.

    The Principal is not a parameter, and that is deliberate: it comes from the
    context through `principal_bound_values`, which refuses values that already
    name the partition column. A caller cannot ask for a client bound to somebody
    else, because there is no argument through which to ask.

    `secret_sha256` is the digest and never the secret. The plaintext exists only
    in the return value of `domain.capture.client.issue_client_secret`, in the
    operator command that prints it once, and nowhere else.
    """
    resolved = require_principal_context(context)
    client_id = issue_identifier(IdKind.CAPTURE_CLIENT)
    connection.execute(
        capture_clients.insert().values(
            principal_bound_values(
                {
                    "client_id": client_id,
                    "secret_sha256": secret_sha256,
                    "state": ClientState.ACTIVE.value,
                    "created_at": at,
                    "revoked_at": None,
                },
                capture_clients,
                resolved,
            )
        )
    )
    return RegisteredCaptureClient(
        client_id=client_id,
        principal_id=str(resolved.capture_principal_id),
        state=ClientState.ACTIVE,
        created_at=at,
    )


def revoke_client(
    connection: Connection, client_id: str, *, at: datetime, context: PrincipalContext
) -> bool:
    """Revoke one of the context's own clients. Returns whether a row changed.

    Scoped and idempotent in the two ways that matter. Scoped, so a `client_id`
    belonging to another Principal answers exactly what an unknown one answers —
    `False` — and the refusal is not an existence oracle. Idempotent, because the
    predicate names the `active` state, so revoking twice reports `False` the
    second time without rewriting `revoked_at` and losing when it first happened.
    """
    resolved = require_principal_context(context)
    result = connection.execute(
        capture_clients.update()
        .where(
            partition_criterion(capture_clients, resolved),
            capture_clients.c.client_id == client_id,
            capture_clients.c.state == ClientState.ACTIVE.value,
        )
        .values(state=ClientState.REVOKED.value, revoked_at=at)
    )
    return result.rowcount == 1


def clients_of(
    connection: Connection, *, context: PrincipalContext
) -> tuple[RegisteredCaptureClient, ...]:
    """Every client the context's Principal holds, oldest first, without secrets."""
    resolved = require_principal_context(context)
    rows = connection.execute(
        principal_scoped(select(*_CLIENT_COLUMNS), capture_clients, resolved).order_by(
            capture_clients.c.created_at, capture_clients.c.client_id
        )
    ).all()
    return tuple(_to_client(row) for row in rows)


def authenticate_client(
    connection: Connection, *, client_id: str, secret: str
) -> RegisteredCaptureClient | None:
    """The active client this credential names, or `None` for every other outcome.

    **Unscoped by necessity, not by omission.** This is the read that *derives*
    the Principal a remote submission runs as, so there is no context to scope it
    by — the same shape `persistence.jobs.job_principal` has, and registered in
    the architecture guard on the same terms. It fails closed: an unknown
    identifier, a wrong secret and a revoked client are one `None`.

    The state test runs *after* the secret comparison and both always run, so the
    three refusals do the same work. That ordering is not decoration: returning
    early on `state = 'revoked'` would answer a holder of a revoked credential
    faster than a holder of a wrong one, which tells them their secret is right.
    """
    row = connection.execute(
        select(*_CLIENT_COLUMNS, capture_clients.c.secret_sha256).where(
            capture_clients.c.client_id == client_id
        )
    ).one_or_none()
    stored = None if row is None else str(row._mapping["secret_sha256"])
    presented_matches = secret_matches(secret, stored)
    if row is None or not presented_matches:
        return None
    client = _to_client(row)
    return client if client.usable else None
