"""A client credential binds to one Principal, and stops working when revoked.

WP-10's second and sixth controls, against real PostgreSQL and through the real
composition root — `bootstrap.gateway.remote_client_authenticator`, the same
callable `build_gateway_runtime` hands the transport.

**Two Principals, at the level this build permits, stated honestly.** `D-15` pins
the web tier to exactly one admissible Principal under `local_operator` and this
package deliberately does not widen that, so there is no reachable configuration
in which two Principals both hold sessions *and* the backend serves. What is
therefore proved here is at the **composition-root and persistence level**: two
client rows are written for two distinct Principals on a live server, and each
credential resolves to its own Principal and to no other — plus the refusal that
keeps the second Principal from existing at all under `local_operator`. It is not
an end-to-end two-identity claim and is not to be restated as one.

**Revocation is proved by the difference it makes**, not by a flag: the same
credential is presented before and after, and the answers differ. A test that
only asserted the refusal would pass against a build where nothing ever
authenticated.

**Every refusal is the same refusal.** Unknown client, wrong secret, revoked
client and foreign binding are one `TokenClaimsError` and one `401`, and the
tests assert that they are indistinguishable rather than merely that each is
refused — because "which of these four failed" is exactly what an attacker
holding a leaked identifier wants to know.

The database is disposable, created and dropped by this module's fixture, and
never the configured one. Every identifier and secret is synthetic.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.wire import Wire, serve

from my_pa.adapters.http import REMOTE_CAPTURE_CAPABILITY, REMOTE_CAPTURE_PATH, create_http_app
from my_pa.bootstrap.gateway import (
    GatewayRuntime,
    build_gateway_runtime,
    local_principal,
    remote_client_authenticator,
)
from my_pa.bootstrap.settings import ENV_PREFIX, AuthMode, Settings, load_settings
from my_pa.domain.capture.client import ClientState, issue_client_secret
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture_clients import (
    clients_of,
    register_client,
    revoke_client,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_remote_client_test"

#: Two synthetic Principals. `synthetic-a` is the local operator this process
#: serves; `synthetic-b` exists only as rows, because no reachable configuration
#: lets a second Principal hold a session (`D-15`).
PRINCIPAL_B: Final = "prn_syntheticbprincipalfortestsonly0"

WHEN_WIRE: Final = "2026-08-10T12:00:00Z"

#: The entra-mode settings, whose only role here is to make
#: `admissible_client_principal_id()` answer `None`. Every value is obviously
#: synthetic and nothing in this module verifies a token or opens a network
#: connection — `remote_client_authenticator` reads the settings and the database
#: and nothing else.
_ENTRA: Final = {
    "auth_mode": AuthMode.ENTRA,
    "entra_tenant_id": "synthetic-tenant",
    "entra_client_id": "synthetic-client",
    "entra_issuer": "https://example.invalid/synthetic/v2.0",
    "entra_jwks_uri": "https://example.invalid/synthetic/keys",
}


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    """The composition with the ingress on, over an emptied database."""
    built = build_gateway_runtime(
        Settings(database_url=disposable_database, remote_ingress_enabled=True)
    )
    try:
        with built.work_engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.captures, knowledge.capture_versions, "
                    "knowledge.capture_receipts, knowledge.capture_submissions, "
                    "knowledge.capture_jobs, knowledge.capture_clients, "
                    "knowledge.audit_events CASCADE"
                )
            )
        yield built
    finally:
        built.close()


def mint(engine: Engine, principal_id: str) -> tuple[str, str]:
    """One client for `principal_id`, as `(client_id, secret)`."""
    secret, digest = issue_client_secret()
    with engine.begin() as connection:
        client = register_client(
            connection,
            secret_sha256=digest,
            at=datetime.now(UTC),
            context=capture_context(principal_id),
        )
    return client.client_id, secret


def credential(client_id: str, secret: str) -> str:
    return f"ClientCredential {client_id}:{secret}"


def submit(wire: Wire, header: str, key: str) -> Any:  # noqa: ANN401 - the wire's own Reply
    return wire.send(
        REMOTE_CAPTURE_CAPABILITY,
        {
            "request_id": f"req-{key}",
            "purpose": Purpose.CAPTURE_AUTHORING.value,
            "requested_at": WHEN_WIRE,
            "payload": {"text": "a synthetic note", "idempotency_key": key},
        },
        path=REMOTE_CAPTURE_PATH,
        extra_headers={"authorization": header},
    )


# ---- control 2: the binding ---------------------------------------------------


@pytest.mark.database
def test_each_credential_resolves_to_its_own_principal_and_no_other(
    runtime: GatewayRuntime, disposable_database: str
) -> None:
    """Two client rows for two Principals; each credential answers with its own.

    The authenticator is composed **unpinned** — `entra`'s posture, where a
    client binds to whichever Principal was authenticated when it was minted — so
    that both rows are admissible and the question is genuinely "which Principal
    does this credential name". Under `local_operator` the second one is refused
    outright, which the next test proves; that refusal would have made this one
    vacuous.

    **Level: composition root plus live PostgreSQL.** Not end to end: no
    reachable configuration admits two Principals holding sessions while the
    backend serves (`D-15`), so a two-identity end-to-end claim is not
    constructible at this head and is not made.
    """
    operator_id = local_principal().principal_id
    first_id, first_secret = mint(runtime.work_engine, operator_id)
    second_id, second_secret = mint(runtime.work_engine, PRINCIPAL_B)
    assert first_id != second_id

    unpinned = remote_client_authenticator(
        Settings(database_url=disposable_database, remote_ingress_enabled=True, **_ENTRA),
        runtime.work_engine,
    )

    assert unpinned(credential(first_id, first_secret)).principal_id == operator_id
    assert unpinned(credential(second_id, second_secret)).principal_id == PRINCIPAL_B

    # The crossing attempt: the other client's secret under this client's
    # identifier. Refused, so a credential is a pair rather than two independent
    # facts one of which could be swapped.
    with pytest.raises(TokenClaimsError):
        unpinned(credential(first_id, second_secret))
    with pytest.raises(TokenClaimsError):
        unpinned(credential(second_id, first_secret))


@pytest.mark.database
def test_a_pinned_process_refuses_a_client_bound_to_another_principal(
    runtime: GatewayRuntime, disposable_database: str
) -> None:
    """The WP-08 NOTE 1 avoidance, at authentication and against a real row.

    The row for `synthetic-b` exists — written directly, which is the worst case:
    a database somebody edited, or a client minted before a mode change. Under
    `local_operator` the composed authenticator refuses it anyway, so a remote
    credential cannot introduce a second Principal holding real data into a tier
    `D-15` pins to one.

    The control is the operator's own client in the same call, which is admitted:
    without it the refusal could be a broken authenticator refusing everything.
    """
    operator_id = local_principal().principal_id
    mine_id, mine_secret = mint(runtime.work_engine, operator_id)
    theirs_id, theirs_secret = mint(runtime.work_engine, PRINCIPAL_B)

    assert runtime.remote_client is not None
    assert runtime.remote_client(credential(mine_id, mine_secret)).principal_id == operator_id

    with pytest.raises(TokenClaimsError):
        runtime.remote_client(credential(theirs_id, theirs_secret))


@pytest.mark.database
def test_a_refused_binding_is_indistinguishable_from_a_wrong_secret(
    runtime: GatewayRuntime,
) -> None:
    """Four refusals, one message, and no exception type a caller could tell apart.

    "This client is real but belongs to somebody else" is an existence fact about
    another Principal's credential. It is answered with the same error and the
    same text as a credential that names nothing at all.
    """
    theirs_id, theirs_secret = mint(runtime.work_engine, PRINCIPAL_B)
    mine_id, _ = mint(runtime.work_engine, local_principal().principal_id)
    assert runtime.remote_client is not None

    messages = set()
    for presented in (
        credential(theirs_id, theirs_secret),
        credential(mine_id, "a-synthetic-value-that-is-not-the-secret"),
        credential("cclt_nosuchclientexistsanywhereatall0", "synthetic"),
        "ClientCredential not-a-credential",
    ):
        with pytest.raises(TokenClaimsError) as refused:
            runtime.remote_client(presented)
        messages.add(str(refused.value))
    assert len(messages) == 1, f"the refusals differ: {messages}"


@pytest.mark.database
def test_a_submission_lands_in_the_credentials_partition(runtime: GatewayRuntime) -> None:
    """Whose capture it is is the credential's answer, read out of the row.

    The document names no Principal. The stored version's `owner_principal_id` is
    the one the credential resolved to, which is what "bound" means when it
    reaches the durable record.
    """
    operator_id = local_principal().principal_id
    client_id, secret = mint(runtime.work_engine, operator_id)
    with serve(
        create_http_app(
            runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
        )
    ) as wire:
        answer = submit(wire, credential(client_id, secret), "bound-key")
    assert answer.status == 200, answer.body

    with runtime.work_engine.connect() as connection:
        owners = list(
            connection.execute(text("SELECT owner_principal_id FROM knowledge.capture_versions"))
        )
    assert [row[0] for row in owners] == [operator_id]


# ---- control 6: the lifecycle -------------------------------------------------


@pytest.mark.database
def test_a_revoked_client_is_refused_where_it_previously_worked(
    runtime: GatewayRuntime,
) -> None:
    """The whole of revocation, as a difference rather than as a flag.

    The same credential, the same process, the same database: admitted, revoked,
    refused. Asserting only the refusal would pass against a build in which the
    credential never worked at all.
    """
    operator_id = local_principal().principal_id
    client_id, secret = mint(runtime.work_engine, operator_id)
    presented = credential(client_id, secret)
    assert runtime.remote_client is not None

    assert runtime.remote_client(presented).principal_id == operator_id

    with runtime.work_engine.begin() as connection:
        assert revoke_client(
            connection, client_id, at=datetime.now(UTC), context=capture_context(operator_id)
        )

    with pytest.raises(TokenClaimsError):
        runtime.remote_client(presented)


@pytest.mark.database
def test_a_revoked_client_stores_nothing_over_the_wire(runtime: GatewayRuntime) -> None:
    """And the refusal is the transport's `401`, with no row behind it."""
    operator_id = local_principal().principal_id
    client_id, secret = mint(runtime.work_engine, operator_id)
    presented = credential(client_id, secret)

    with serve(
        create_http_app(
            runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
        )
    ) as wire:
        # Bound to a local rather than asserted inline: pytest renders the
        # operands of a failing assertion, and one of them would be the
        # credential. The same discipline `bootstrap.settings` applies to the
        # DSN with `repr=False`.
        admitted = submit(wire, presented, "before-revocation")
        assert admitted.status == 200
        with runtime.work_engine.begin() as connection:
            revoke_client(
                connection, client_id, at=datetime.now(UTC), context=capture_context(operator_id)
            )
        refused = submit(wire, presented, "after-revocation")

    assert refused.status == 401
    assert refused.headers["www-authenticate"] == "ClientCredential"
    with runtime.work_engine.connect() as connection:
        stored = connection.execute(
            text("SELECT count(*) FROM knowledge.capture_versions")
        ).scalar_one()
    assert stored == 1, "the revoked submission was admitted"


@pytest.mark.database
def test_revocation_is_scoped_and_idempotent(runtime: GatewayRuntime) -> None:
    """Another Principal's client cannot be revoked, and the answer is the same one.

    An unknown identifier, a foreign one and an already-revoked one all report
    "nothing changed", so an operator cannot use the revoke command to learn
    whether another Principal holds a given client.
    """
    operator_id = local_principal().principal_id
    theirs_id, _ = mint(runtime.work_engine, PRINCIPAL_B)
    mine_id, _ = mint(runtime.work_engine, operator_id)
    mine = capture_context(operator_id)

    with runtime.work_engine.begin() as connection:
        assert revoke_client(connection, theirs_id, at=datetime.now(UTC), context=mine) is False
        assert (
            revoke_client(
                connection,
                "cclt_nosuchclientexistsanywhereatall0",
                at=datetime.now(UTC),
                context=mine,
            )
            is False
        )
        assert revoke_client(connection, mine_id, at=datetime.now(UTC), context=mine) is True
        assert revoke_client(connection, mine_id, at=datetime.now(UTC), context=mine) is False

    # And the foreign client is untouched, which is what "scoped" has to mean.
    with runtime.work_engine.connect() as connection:
        theirs = clients_of(connection, context=capture_context(PRINCIPAL_B))
    assert [client.state for client in theirs] == [ClientState.ACTIVE]


@pytest.mark.database
def test_a_listing_returns_only_this_principals_clients_and_no_secret(
    runtime: GatewayRuntime,
) -> None:
    """The read path is partitioned, and holds nothing a listing could disclose."""
    operator_id = local_principal().principal_id
    mine_id, mine_secret = mint(runtime.work_engine, operator_id)
    mint(runtime.work_engine, PRINCIPAL_B)

    with runtime.work_engine.connect() as connection:
        mine = clients_of(connection, context=capture_context(operator_id))
    assert [client.client_id for client in mine] == [mine_id]
    rendered = repr(mine)
    assert mine_secret not in rendered
    assert "sha" not in rendered.lower()


@pytest.mark.database
def test_the_operator_command_mints_a_credential_that_the_ingress_admits(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """The operator lifecycle end to end, through the command an operator runs.

    `register` prints a credential; that exact credential authenticates a real
    submission; `list` shows the client without its secret; `revoke` refuses it
    from the next request on; `status` reports the change. Driven through
    `apps/cli/clients.py:main`, so what is proved is the path an operator takes
    rather than the writers underneath it.

    The command reads `MY_PA_DATABASE_URL`, which this module's fixture points at
    the disposable database for its own lifetime.
    """
    import apps.cli.clients as clients

    assert clients.main(["register"]) == 0
    printed = capsys.readouterr().out
    credential_line = next(line for line in printed.splitlines() if line.startswith("credential "))
    presented = f"ClientCredential {credential_line.split(maxsplit=1)[1].strip()}"
    client_id = presented.split()[1].split(":", 1)[0]

    with serve(
        create_http_app(
            runtime.service, principal=runtime.principal, remote_client=runtime.remote_client
        )
    ) as wire:
        admitted = submit(wire, presented, "operator-minted")
        assert admitted.status == 200

        assert clients.main(["list"]) == 0
        listing = capsys.readouterr().out
        assert client_id in listing
        assert presented.split(":", 1)[1] not in listing, "the listing printed the secret"

        assert clients.main(["revoke", "--client-id", client_id]) == 0
        capsys.readouterr()
        after = submit(wire, presented, "after-operator-revocation")
        assert after.status == 401

    assert clients.main(["status"]) == 0
    status = capsys.readouterr().out
    assert "ingress          disabled" in status, (
        "status reads the process environment, where the ingress switch is off; "
        "the runtime under test enables it explicitly"
    )
    assert "clients          0 active of 1 registered" in status
    assert clients.INGRESS_PATH in status


@pytest.mark.database
def test_the_stored_row_holds_a_digest_and_never_the_secret(runtime: GatewayRuntime) -> None:
    """Read straight out of the table: the plaintext is nowhere in the database.

    The sweep is over every column of every row rather than over
    `secret_sha256` alone, so a secret written into a second column — a label, an
    audit row, a note — is found rather than assumed absent.
    """
    operator_id = local_principal().principal_id
    client_id, secret = mint(runtime.work_engine, operator_id)

    with runtime.work_engine.connect() as connection:
        rows = [
            str(row[0])
            for table in ("knowledge.capture_clients", "knowledge.audit_events")
            # S608: both names are literals above; nothing here is input.
            for row in connection.execute(text(f"SELECT row_to_json(t)::text FROM {table} t"))  # noqa: S608
        ]
    assert rows, "no client row was written, so its silence about the secret proves nothing"
    assert any(client_id in row for row in rows), "the client row is not the one being swept"
    assert not any(secret in row for row in rows), "the plaintext secret reached the database"
