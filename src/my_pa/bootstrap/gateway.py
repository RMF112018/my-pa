"""What a transport process is made of, and why it has two connection pools.

Composition, in the one place allowed to choose an implementation
(`module-boundaries.md` section 5.10). Nothing here parses a protocol and
nothing here decides a request; it builds the objects the transport is handed
and hands back the handles the process has to dispose.

**All three transports compose from here**, and the name stays `gateway` because
that is what this composition is — the gateway process serving HTTP under
`apps/gateway.py run` and MCP under `apps/gateway.py mcp`, and `apps/cli/invoke.py`
running one request through the same objects. A CLI that composed its own
`ApplicationService` could differ from the served one in a limit, a clock, or a
principal kind, and the difference would be invisible until it mattered; sharing
this function is what makes "the CLI is not a privileged bypass"
(`module-boundaries.md` section 5.7) a fact about the wiring rather than a
sentence in a review. The pool arithmetic below is derived for the concurrent
case and is simply generous for the CLI, which makes one request and exits.

## The pool

`create_database_engine` builds a pool of five with no overflow. WP-4B1's audit
sink takes a **second** connection per request, by design: an event that has to
outlive the rollback of the work it describes cannot be written on the
connection doing the work, and PostgreSQL has no autonomous transaction. Both
connections come from an engine, and until now there was one engine.

The arithmetic, with one shared pool of size `P` and `C` requests in flight:

* each request takes a work connection and holds it for its whole life;
* while still holding it, it needs an audit connection;
* free connections are `P - C`, so the audit checkout succeeds only while
  `P - C >= 1`;
* at `C >= P` there are none free, and no work connection can be released
  before its own audit completes. Every request waits for a connection that only
  another waiting request can return. That is a deadlock, and `pool_timeout` is
  what ends it — thirty seconds later, every one of them fails closed.

So the shared-pool composition breaks at exactly five concurrent requests, and
"fails closed" is the *good* half of what it does. Failing after thirty seconds
of a circular wait is not a bound; it is a bound that has already been violated.

**The fix is two pools, not a bigger one.** A single pool of ten with
concurrency held at five satisfies the arithmetic — five work plus five audit is
ten — but only for as long as the concurrency bound holds, and it is enforced
somewhere else: in a thread-pool size, a server flag, a number nobody re-derives
when it changes. Give the audit sink its own engine and the cycle cannot form at
all: a work connection can never occupy the pool an audit draws from, so a
request that holds a work connection always finishes, at any concurrency. The
concurrency bound stops being a correctness argument and becomes what it should
be, a resource decision.

**The sizes are derived, not round.** The work pool stays at
`create_database_engine`'s five, which is what bounds requests in flight: a
sixth waits for a work connection, which is an ordinary queue that ends in a
connection or in a bounded, closed failure. The audit pool is five for a reason
that follows from that number and not from symmetry — the sink needs at most one
connection per request that is holding a work connection, at most five requests
can hold one at once, so five is the smallest audit pool at which an audit never
waits behind another audit, and a sixth audit connection could never be used.
Ten backends in total, against a server whose other declared consumers are the
worker and the migration CLI.

`tests/concurrency/test_gateway_connection_pool.py` proves both halves: five
concurrent requests all complete here, and the same five against one shared pool
all fail.

## The principal

**Two modes, selected by configuration and never inferred**
(`MY_PA_AUTH_MODE`). Activating authentication is an edit to an environment
variable, not to this file.

`local_operator` is `D-30` unchanged and is the default: one `Principal`, issued
at startup, `OPERATOR`, authenticated. Loopback is the trust boundary and a local
principal is the only principal; no credential is issued, read, or required.
`OPERATOR` rather than `GATEWAY` because the process *is* the operator's local
transport — a `GATEWAY` principal cannot invoke `sources.enroll`, so the choice
is between naming what this is and shipping a transport that cannot reach one of
the sixteen capabilities.

`entra` composes `entra_authenticator` instead and issues **no** process
principal. Every request presents a bearer token, the token's validated
`(tid, oid)` resolves through `PrincipalIdentityService` to that person's durable
`principal_id`, and the `Principal` handed to the application is `OPERATOR` and
authenticated — the same kind, for the same reason, so authorization semantics
are identical to the loopback mode and only the identifier differs. Widening or
narrowing authority was not part of turning authentication on, and a different
kind would have done one or the other silently.

`P00-OD-010` — which mechanism authenticates — is answered for the mechanism and
still open for the activation: no tenant, application registration, or credential
is configured here, and an unconfigured `entra` refuses to start rather than
falling back (see `bootstrap.settings`).

`entra` composes `entra_authenticator` instead and issues **no** process
principal. Every request presents a bearer token, the token's validated
`(tid, oid)` resolves through `PrincipalIdentityService` to that person's durable
`principal_id`, and the `Principal` handed to the application is `OPERATOR` and
authenticated — the same kind, for the same reason, so authorization semantics
are identical to the loopback mode and only the identifier differs. Widening or
narrowing authority was not part of turning authentication on, and a different
kind would have done one or the other silently.

`P00-OD-010` — which mechanism authenticates — is answered for the mechanism and
still open for the activation: no tenant, application registration, or credential
is configured here, and an unconfigured `entra` refuses to start rather than
falling back (see `bootstrap.settings`).

The identifier is durable across process runs (`PKL-MYPA-D-WP03-001`): it is
derived from a fixed namespace UUID in `my_pa.domain.identity.binding`, not
issued per run and not derived from the host or the account — so no personal
value sits inside the opaque identifier (`INV-PKL-005`) and no stored capture is
stranded behind a principal that died with its process. What `P00-OD-010` still
settles is authentication of *multiple* principals; the single local operator's
name is no longer a per-run accident.

## The providers

Nothing is wired here, and that is a stronger statement than the one it replaces
rather than a weaker one. This module used to hand `ApplicationService` a
`NoConfiguredSources` that answered `None` to everything, because nothing
registered a source and no root was authorized. The lookup is now
`UnitOfWork.providers` — `infrastructure.providers.RegisteredSourceProviders`
over the caller's own transaction — so which sources are served is read from
`knowledge.sources` rows, and the row exists exactly when an operator registered
one by exact path.

A build with no registered source therefore still answers `None`, and the
application still reports `unavailable` for the source it cannot serve. **The
same truth, now derived from rows rather than hard-coded**: this composition
names no root, holds no default, and has nothing left to invent a corpus with.
`P00-OD-009` is untouched — which roots are legitimate is still the operator's
decision, made by running the registration command and not by editing this file.

The lookup moved into the transaction for a reason this module's pool arithmetic
already derives: a provider resolves `obj_…` against `knowledge.source_objects`,
and one holding its own connection while a request holds a work connection is
exactly the cycle above, at exactly five concurrent requests.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine

from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import AuthMode, Settings
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.security.entra_token import EntraTokenVerifier, jwks_signing_key_source
from my_pa.infrastructure.security.principal_identity import PrincipalIdentityService

__all__ = [
    "Authenticator",
    "GatewayRuntime",
    "build_gateway_runtime",
    "entra_authenticator",
    "local_principal",
]

#: How a transport asks the composition root who is calling. The first argument
#: is the raw `Authorization` header value as the transport received it, or
#: `None`; the second is the request document. It returns the acting `Principal`
#: or raises `TokenClaimsError`, which is the only outcome a transport is
#: allowed to distinguish.
#:
#: A plain callable rather than a protocol or a port: there is one implementation
#: and one caller, and `AGENTS.md` section 2 says that is the point at which an
#: interface would be the defect.
Authenticator = Callable[[str | None, Mapping[str, Any]], Principal]

#: The scheme a bearer credential is presented under, per RFC 6750.
_BEARER = "bearer"


def local_principal() -> Principal:
    """The one principal this process acts as — the same one every process acts as.

    The identifier is derived, not minted (`PKL-MYPA-D-WP03-001`): it is the
    durable local-operator binding from `my_pa.domain.identity.binding`, so two
    gateway processes — or one process before and after a restart — present the
    same `principal_id`. Capture ownership is partitioned by that identifier,
    and a per-process random identifier here would strand every stored capture
    behind a principal that no longer exists the moment the process exits.
    """
    return Principal(
        principal_id=capture_principal_id(LOCAL_OPERATOR_UUID),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def _bearer_token(credential: str | None) -> str:
    """The token inside an `Authorization: Bearer …` value, or a refusal.

    Refuses an absent header, a different scheme, and an empty token, all as the
    same error: a caller learns that it is not authenticated, not which of the
    three ways it failed to present a credential.
    """
    if credential is None:
        raise TokenClaimsError("a bearer token is required; access is denied")
    scheme, _, presented = credential.partition(" ")
    if scheme.strip().lower() != _BEARER or not presented.strip():
        raise TokenClaimsError("a bearer token is required; access is denied")
    return presented.strip()


def entra_authenticator(settings: Settings, work_engine: Engine) -> Authenticator:
    """Compose the per-request authentication `entra` mode performs.

    Three steps, in an order a caller cannot reshuffle: verify the token against
    the configured issuer and audience, then hand its claims to
    `PrincipalIdentityService`, which rejects a payload carrying identity,
    validates the home tenant, and resolves the durable `principal_id`.

    **Which payload is checked, and why it is the payload rather than the whole
    document.** `contracts.v1.RequestMetadata` makes `principal_id` a *required*
    envelope field on every public request and its own docstring says what it is:
    correlation input the application does not read. So the envelope always names
    a principal, and refusing every document that does so would refuse every
    legal request. `adapters.normalization.PAYLOAD_KEY` is where a capability's
    own arguments live and is what MU-AC-02 means by a request payload — an
    identity field there is a caller trying to name the partition its request
    runs in, and it is refused. The envelope's stated `principal_id` cannot shift
    the resolved Principal either, and that is a stronger property than refusing
    it: it is proved by the resolution never reading it.

    **The transaction is this function's, not the request's.** The resolution
    runs in its own short transaction and commits before the request begins,
    because `ApplicationService.invoke` opens the request's transaction *after*
    it has been given a Principal, and there is no Principal until this has run.
    The consequence is small and worth naming: a request that then fails leaves
    the account row behind. That is the correct direction — an account seen is an
    account seen, and the alternative would be re-minting a `principal_id` on
    every failed request.

    It takes one work connection and returns it before the request takes its own,
    so no request ever holds two at once and the pool arithmetic in this module's
    docstring is unchanged.
    """
    verifier = EntraTokenVerifier(
        audience=settings.entra_client_id,
        issuer=settings.entra_issuer,
        signing_key=jwks_signing_key_source(settings.entra_jwks_uri),
    )
    identity = PrincipalIdentityService(home_tenant_id=settings.entra_tenant_id)

    def authenticate(credential: str | None, document: Mapping[str, Any]) -> Principal:
        claims = verifier.claims(_bearer_token(credential))
        declared = document.get(PAYLOAD_KEY)
        payload = declared if isinstance(declared, Mapping) else {}
        with work_engine.begin() as connection:
            authenticated = identity.authenticate(
                connection, claims=claims, payload=payload, now=datetime.now(UTC)
            )
        return Principal(
            principal_id=capture_principal_id(authenticated.account.principal_id),
            kind=PrincipalKind.OPERATOR,
            authenticated=True,
        )

    return authenticate


@dataclass(frozen=True, slots=True)
class GatewayRuntime:
    """The application, the principal, and the two engines behind them.

    Both engines are exposed rather than hidden, because the reason there are
    two is a claim that has to be testable: a test that could not reach them
    could only assert that requests succeed, which a lucky ordering also does.
    """

    service: ApplicationService
    #: The one process principal, in `local_operator` mode, and `None` in
    #: `entra` mode — where there is no process principal at all, because every
    #: request carries its own. `None` rather than a leftover local operator, so
    #: a transport composed with the wrong field in the authenticated mode fails
    #: at composition instead of serving every caller as the operator.
    principal: Principal | None
    #: How a request is authenticated, in `entra` mode, and `None` in
    #: `local_operator` mode. Exactly one of this and `principal` is set.
    authenticate: Authenticator | None
    work_engine: Engine
    audit_engine: Engine

    def close(self) -> None:
        """Release both pools. Safe to call after a failed start."""
        self.work_engine.dispose()
        self.audit_engine.dispose()


def build_gateway_runtime(settings: Settings) -> GatewayRuntime:
    """Compose the gateway from validated configuration.

    Two engines against the same database, for the reason the module docstring
    derives. The unit of work is built per invocation, as `ApplicationService`
    requires: one transaction per request, never a shared open one.
    """
    work_engine = create_database_engine(settings.parsed_database_url())
    audit_engine = create_database_engine(settings.parsed_database_url())
    audit = SqlAlchemyAuditSink(audit_engine)

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(work_engine, audit=audit)

    entra = settings.auth_mode is AuthMode.ENTRA
    return GatewayRuntime(
        service=ApplicationService(
            unit_of_work=unit_of_work,
            limits=settings.effective_limits(),
        ),
        principal=None if entra else local_principal(),
        authenticate=entra_authenticator(settings, work_engine) if entra else None,
        work_engine=work_engine,
        audit_engine=audit_engine,
    )
