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
the 124 capabilities.

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

## The remote capture client

There is a **second credential plane** since WP-10, and calling it a second plane
rather than a second mode is the whole of its design. `MY_PA_AUTH_MODE` decides
how a *person* is established and has exactly two values; the remote ingress
decides how a *device* is established and is orthogonal to both — a
`local_operator` process may serve it and an `entra` process may serve it, and
neither one changes what the other does.

`MY_PA_REMOTE_INGRESS_ENABLED` is off by default, and off means
`remote_client=None`, and `None` means the ingress route refuses inside its own
handler. Nothing is inferred and nothing falls back.

The two planes are disjoint by construction rather than by convention:

* the schemes differ — `Bearer` for a person's token, `ClientCredential` for a
  device's secret — and each authenticator refuses the other's scheme before it
  reads the value, so a token presented at the ingress and a client secret
  presented at `/v1/{capability}` are both refused for what they are;
* the remote authenticator's signature takes the header and **not** the request
  document, so remote identity cannot be influenced by a payload at all;
* no browser session exists on this side. This process reads no cookie, mints
  none, and holds no session secret; the web tier's session plane is in
  `web/src/lib/auth` and this module imports nothing from it and could not.

Under `local_operator` a client binds to the one process Principal and a client
row naming another is refused at minting and at every authentication. That
refusal is deliberate and is recorded as such: `D-15` pins the web tier to
exactly one admissible Principal in that mode, and WP-08's NOTE 1 names "two
identities can hold sessions while the backend serves" as its release blocker.
Minting a credential for a second Principal is the cheapest way to create that
condition, so this composition refuses to.

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
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, Engine

from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.application.apple_machine import AppleBridgeIdentity, AppleMachineControl
from my_pa.application.entity_reenrichment import (
    ProductionReenrichmentCaller,
    ReenrichmentWork,
)
from my_pa.application.goodnotes_gsqs_b0_workflow import WorkflowPorts
from my_pa.application.native_sources import NativeSourceController
from my_pa.application.producer_origin import ProducerOrigin, ProducerOriginRegistry
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.apple_machine_control import SqlAppleMachineControl
from my_pa.bootstrap.settings import AuthMode, Settings
from my_pa.contracts.ports import ManagedByteStore, UnitOfWork
from my_pa.domain.capture.client import admit_client_binding, parse_client_credential
from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.domain.policy.decision import POLICY_VERSION
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.gsqs_routellm_transport import post_chat_completion
from my_pa.infrastructure.jobs.reenrichment import (
    claim_reenrichment_work,
    settle_reenrichment_work,
)
from my_pa.infrastructure.managed_document_stores.filesystem.store import (
    FilesystemManagedByteStore,
)
from my_pa.infrastructure.persistence.apple_bridge_credentials import (
    authenticate_apple_bridge_credential,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.capture_clients import authenticate_client, clients_of
from my_pa.infrastructure.persistence.commitment_management import (
    SqlAlchemyCommitmentManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.entity_reenrichment import (
    ReenrichmentTables,
    SqlReenrichmentWorkRepository,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.registry import configured_source_roots
from my_pa.infrastructure.persistence.tables import (
    entity_reenrichment_subjects,
    entity_reenrichment_version_watermarks,
    entity_reenrichment_work,
)
from my_pa.infrastructure.persistence.task_management import SqlAlchemyTaskManagementUnitOfWork
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.security.entra_token import EntraTokenVerifier, jwks_signing_key_source
from my_pa.infrastructure.security.principal_identity import PrincipalIdentityService

__all__ = [
    "Authenticator",
    "GatewayRuntime",
    "RemoteClientAuthenticator",
    "build_gateway_runtime",
    "entra_authenticator",
    "local_principal",
    "remote_client_authenticator",
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

#: How the remote capture ingress asks the composition root who is calling. One
#: argument — the raw `Authorization` header value, or `None` — and no request
#: document, deliberately: a remote submission's identity comes from the
#: credential and from nothing the caller wrote in a body, and a signature that
#: cannot see the body is a stronger statement of that than a rule saying so.
RemoteClientAuthenticator = Callable[[str | None], Principal]

#: The scheme a bearer credential is presented under, per RFC 6750.
_BEARER = "bearer"

#: The scheme a registered capture client presents its credential under. Not
#: `Bearer` and not `Basic`, and that is the point: the two credential planes
#: must be impossible to confuse, so each refuses the other's scheme before it
#: reads a single byte of the value. RFC 7235 permits a private scheme name; a
#: shared one would have made "a browser session cannot authenticate the ingress"
#: an argument about what happens next instead of a fact about the header.
_CLIENT_CREDENTIAL_SCHEME = "clientcredential"


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


def relationship_producer_origins(principal: Principal | None) -> ProducerOriginRegistry:
    """Trusted producer registration for this process composition.

    Local-operator mode has one durable authenticated identity and registers it
    as the gateway's rule producer. Entra mode has no single process Principal;
    until trusted producer identities are configured, the empty registry makes
    the application withhold producer capabilities instead of publishing an
    unusable surface.
    """
    if principal is None:
        return ProducerOriginRegistry()
    return ProducerOriginRegistry(
        {
            principal.principal_id: ProducerOrigin(
                principal_id=principal.principal_id,
                principal_kind=principal.kind,
                method="rule",
                method_version="gateway.relationship-producer.1",
            )
        }
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


def _client_credential(credential: str | None) -> str:
    """The value inside an `Authorization: ClientCredential …` header, or a refusal.

    Refuses an absent header, a different scheme — including `Bearer`, which is
    the one that matters — and an empty value, all as the same `CaptureError`
    the rest of the client path raises, so the caller cannot tell which.
    """
    if credential is None:
        raise CaptureError("a client credential is required; access is denied")
    scheme, _, presented = credential.partition(" ")
    if scheme.strip().lower() != _CLIENT_CREDENTIAL_SCHEME or not presented.strip():
        raise CaptureError("a client credential is required; access is denied")
    return presented.strip()


def _observe_reenrichment_versions(
    connection: Connection,
    *,
    principal_id: str,
    cause: str,
    at: datetime,
) -> tuple[ReenrichmentWork, ...]:
    """Observe server versions on the caller's already-open transaction."""
    tables = ReenrichmentTables(
        entity_reenrichment_work,
        entity_reenrichment_subjects,
        entity_reenrichment_version_watermarks,
    )
    return ProductionReenrichmentCaller(
        SqlReenrichmentWorkRepository(connection, tables),
        principal_id=principal_id,
        policy_version=POLICY_VERSION,
    ).observe_process_versions(principal_id, cause=cause, at=at)


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
        moment = datetime.now(UTC)
        with work_engine.begin() as connection:
            authenticated = identity.authenticate(
                connection, claims=claims, payload=payload, now=moment
            )
            principal = Principal(
                principal_id=capture_principal_id(authenticated.account.principal_id),
                kind=PrincipalKind.OPERATOR,
                authenticated=True,
            )
            _observe_reenrichment_versions(
                connection,
                principal_id=principal.principal_id,
                cause=issue_identifier(IdKind.OPERATION),
                at=moment,
            )
            return principal

    return authenticate


def remote_client_authenticator(
    settings: Settings, work_engine: Engine
) -> RemoteClientAuthenticator:
    """Compose the per-request authentication the remote capture ingress performs.

    **A second credential plane, and disjoint from the first by construction.**
    The credential is `Authorization: ClientCredential <client_id>:<secret>` — a
    scheme neither `_bearer_token` nor any browser produces — so an Entra bearer
    token presented here is refused for its scheme before anything is read, and a
    client credential presented at `/v1/{capability}` is refused by
    `_bearer_token` for the same reason. Nothing in this function reads a cookie,
    mints a session, or touches the web tier's signing secret, and nothing in the
    web tier can obtain a client credential: they are minted by an operator
    command onto a terminal.

    Four refusals and one answer, and the four are indistinguishable. A malformed
    credential, an unknown client, a wrong secret, and a revoked client all raise
    `TokenClaimsError`, which the transport renders as one `401` with one body.
    The fifth refusal is `admit_client_binding`'s and is the same error for the
    same reason: a caller learns that it is not authenticated, never which of the
    five ways.

    **The binding check is the WP-08 NOTE 1 avoidance, applied at authentication
    and not only at minting.** Under `local_operator` this process may act as
    exactly one Principal, so a stored client row naming another one — written
    before a mode change, or by hand against the database — is refused rather
    than served. Minting applies the same rule (`apps/cli/clients.py`), and
    applying it twice is deliberate: a rule enforced only where rows are created
    is a rule that a row created another way does not inherit.

    **The transaction is this function's, not the request's**, exactly as
    `entra_authenticator`'s is and for the same reason: `ApplicationService.invoke`
    opens the request's transaction after it has been given a Principal. It takes
    one work connection and returns it before the request takes its own, so no
    request ever holds two at once and the pool arithmetic above is unchanged.
    Unlike the Entra path it writes nothing at all — the client row already
    exists, and authenticating does not update it.
    """
    admissible = settings.admissible_client_principal_id()

    def authenticate(credential: str | None) -> Principal:
        """Resolve one presented client credential, or refuse it identically.

        The signature takes **only** the header, and that is the property rather
        than an omission: `entra_authenticator` receives the request document
        because it has to refuse an identity field inside it, and this one cannot
        receive it at all — so remote identity structurally cannot be influenced
        by anything the caller sent in a body. `metadata.principal_id` stays read
        nowhere (`D-13`/`D-14`) on this plane for a reason a reader can check
        from the type.
        """
        resolved: Principal | None = None
        try:
            parsed = parse_client_credential(_client_credential(credential))
            with work_engine.begin() as connection:
                client = authenticate_client(
                    connection, client_id=parsed.client_id, secret=parsed.secret
                )
            if client is not None:
                # Refused here rather than at the row, and refused as the same
                # error as everything else: a caller must not be able to tell a
                # rejected *binding* from a rejected *credential*, because the
                # difference is "this client is real but belongs to another
                # Principal", which is exactly the existence fact the refusal
                # exists to withhold.
                admit_client_binding(bound=client.principal_id, admissible=admissible)
                resolved = Principal(
                    principal_id=client.principal_id,
                    kind=PrincipalKind.OPERATOR,
                    authenticated=True,
                )
        except CaptureError:
            # A malformed credential and a refused binding are both `CaptureError`
            # and both become the one refusal. Raised below rather than here, as
            # everywhere else in this repository: the original would otherwise sit
            # on `__context__` for a rendered traceback to read, and a malformed
            # credential's message is a caller-supplied string.
            resolved = None
        if resolved is None:
            raise TokenClaimsError("a registered capture client is required; access is denied")
        return resolved

    return authenticate


def managed_byte_store(settings: Settings, work_engine: Engine) -> ManagedByteStore | None:
    """The managed-document byte store, or `None` when no managed root is configured.

    **`None` is the fail-closed default and the only inference made here.** An
    unset, blank or mistyped `MY_PA_MANAGED_DOCUMENT_ROOT` produces an empty
    string, an empty string produces `None`, and `None` means
    `ApplicationService.available_capabilities` withholds all six `documents.`
    names from `capabilities.get` and from the MCP tool list. A process that was
    never told where managed bytes go therefore serves no managed capability at
    all rather than serving one into a directory this function guessed.

    **The overlap check runs at composition and refuses to start.** The store's
    constructor resolves the root, compares it against every configured source
    root — after full path resolution and through symbolic links — and raises
    when the two trees intersect. Reading `knowledge.sources` here is what makes
    that check real: a store built without the source roots would be a store that
    had checked nothing. Raising rather than returning `None` is deliberate: an
    overlapping managed root is a misconfiguration an operator must fix, and
    quietly disabling the plane would hide it.
    """
    configured = settings.managed_document_root.strip()
    if not configured:
        return None
    with work_engine.begin() as connection:
        source_roots = configured_source_roots(connection)
    return FilesystemManagedByteStore(
        Path(configured), source_roots=[Path(root) for root in source_roots]
    )


def mcp_surface_enabled(
    settings: Settings, work_engine: Engine, principal: Principal | None
) -> bool:
    """Whether the MCP surface serves at all, decided once at composition (WP-28).

    Two independent reasons to answer `False`, and both fail closed:

    * **The kill switch is engaged.** `MY_PA_MCP_SURFACE_DISABLED` is off by
      default and the surface serves; engaging it withdraws the surface from a
      client already using it, without stopping the gateway. `adapters.mcp.server`
      then publishes no tool *and* refuses every `tools/call`.
    * **The bound client is gone or revoked.** `MY_PA_MCP_CLIENT_ID` names a row
      in `knowledge.capture_clients` — WP-10's registry, and the same one
      `revoke_client` writes to. An identifier naming no client, one belonging to
      another Principal, and one that has been revoked are **one answer**, on the
      registry's own rule that "this credential used to work" is exactly what a
      refusal must not disclose. Empty means no client is bound, which is every
      process this build has run so far.

    **Binding is identification, not authentication, and the difference is not
    cosmetic.** stdio carries no credential (`D-30`), so this process presents no
    secret and verifies none; what it does is refuse to serve *as* a client the
    operator has withdrawn. Authenticating an external MCP client needs an ingress
    that carries a credential, which is EXT-07/EXT-08 and does not exist. Nothing
    here should be read as per-client authentication.

    In `entra` mode there is no process principal, so there is no partition to
    look a bound client up in; a bound client is refused rather than resolved
    against a guess. The surface itself is unaffected when nothing is bound.
    """
    if settings.mcp_surface_disabled:
        return False
    bound = settings.mcp_client_id.strip()
    if not bound:
        return True
    if principal is None:
        return False
    with work_engine.connect() as connection:
        held = clients_of(connection, context=capture_context(principal.principal_id))
    return any(client.client_id == bound and client.usable for client in held)


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
    #: How a *remote capture client* is authenticated, and `None` whenever
    #: `MY_PA_REMOTE_INGRESS_ENABLED` is off — which is its default and therefore
    #: the state of every process that has not deliberately turned it on. It is
    #: independent of the two fields above rather than a third alternative to
    #: them: the ingress is a second credential plane and either mode may run
    #: with or without it.
    #:
    #: `None` is not the whole kill switch, only the composition half. The
    #: transport mounts the ingress route unconditionally and refuses inside the
    #: handler when this is `None`, so "disabled" is something a request meets
    #: rather than something a routing table hides.
    remote_client: RemoteClientAuthenticator | None
    apple_authenticate: Callable[[str | None], AppleBridgeIdentity] | None
    apple_control: AppleMachineControl | None
    #: Whether the MCP surface serves at all (WP-28). Decided once at
    #: composition by `mcp_surface_enabled`, which reads the kill switch and the
    #: bound client's state; `apps/gateway.py mcp` passes it straight through and
    #: the transport holds a boolean and no configuration.
    mcp_enabled: bool
    work_engine: Engine
    audit_engine: Engine

    def close(self) -> None:
        """Release both pools. Safe to call after a failed start."""
        self.work_engine.dispose()
        self.audit_engine.dispose()

    def run_reenrichment_once(
        self,
        *,
        owner: str,
        at: datetime | None = None,
    ) -> str | None:
        """Claim and settle at most one bounded work item; name the state it reached.

        The one-shot form of the re-enrichment plane, and it is a *delegation*
        rather than a second implementation. Until WP-03 this method built the
        claim and the apply itself and had no caller anywhere in the repository
        (`RI-P3-BLK-001`), which meant the protocol it spelled was never
        executed and could drift from any protocol that later was. It now runs
        the same two steps `infrastructure.jobs.reenrichment` runs in its loop,
        so an operator running one item and the worker running a thousand are
        exercising the same code.

        Returns the terminal state -- `"succeeded"`, `"partial"`, `"stale"` or
        `"failed"` -- or `None` when there was nothing claimable. A boolean
        could not distinguish an item that settled `partial` from one that
        settled `succeeded`, which is exactly the distinction WP-05 exists to
        preserve.
        """
        moment = datetime.now(UTC) if at is None else at
        work = claim_reenrichment_work(self.work_engine, owner=owner, at=moment)
        if work is None:
            return None
        state, _outcome = settle_reenrichment_work(self.work_engine, work, owner=owner, at=moment)
        return state

    def observe_reenrichment_versions(
        self,
        *,
        principal_id: str,
        cause: str,
        at: datetime | None = None,
    ) -> tuple[ReenrichmentWork, ...]:
        """Observe server-owned versions and register only real advances."""
        moment = datetime.now(UTC) if at is None else at
        with self.work_engine.begin() as connection:
            return _observe_reenrichment_versions(
                connection,
                principal_id=principal_id,
                cause=cause,
                at=moment,
            )

    def observe_authenticated_principal(
        self,
        principal: Principal,
        *,
        cause: str,
        at: datetime | None = None,
    ) -> tuple[ReenrichmentWork, ...]:
        """Observe versions for exactly one identity established by authentication."""
        if not principal.authenticated:
            raise TokenClaimsError("an authenticated Principal is required; access is denied")
        return self.observe_reenrichment_versions(
            principal_id=principal.principal_id,
            cause=cause,
            at=at,
        )


def build_gateway_runtime(settings: Settings) -> GatewayRuntime:
    """Compose the gateway from validated configuration.

    Two engines against the same database, for the reason the module docstring
    derives. The unit of work is built per invocation, as `ApplicationService`
    requires: one transaction per request, never a shared open one.
    """
    work_engine = create_database_engine(
        settings.parsed_database_url(), statement_timeout_ms=30_000
    )
    audit_engine = create_database_engine(
        settings.parsed_database_url(), statement_timeout_ms=30_000
    )
    audit = SqlAlchemyAuditSink(audit_engine)

    # The same conjunction `ApplicationService.available_capabilities` applies,
    # spelled once here so the review surface turns on with the plane's own
    # capability names rather than separately. A memory binds its subject to an
    # Entity, so the memory switch alone does not compose the plane — and a
    # review surface that offered a memory case in a build whose
    # `relationship_memory.` names are withheld would be the one route into the
    # plane that the manifest denies exists.
    relationship_memory_composed = (
        settings.relationship_intelligence_enabled and settings.relationship_memory_enabled
    )

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(
            work_engine,
            audit=audit,
            relationship_memory_enabled=relationship_memory_composed,
            # The Entity half of the Review surface, and it is the same one
            # switch `ApplicationService` is given below rather than a
            # conjunction: an Entity proposal's subject is an entity of this
            # plane and nothing else, so the plane's own flag is the whole
            # composition. Until `WP-RI-B-07` this argument was not passed at
            # all, so `_Reviews` defaulted closed and `review.list` returned no
            # Entity case in any real build however the flag was set — a silent
            # failure rather than a loud one, which is why
            # `tests/contract/test_review_capabilities.py` now proves the wiring
            # end to end through `build_gateway_runtime` instead of by reading
            # this line.
            relationship_intelligence_enabled=settings.relationship_intelligence_enabled,
        )

    def task_management_unit_of_work() -> SqlAlchemyTaskManagementUnitOfWork:
        return SqlAlchemyTaskManagementUnitOfWork(work_engine)

    def commitment_management_unit_of_work() -> SqlAlchemyCommitmentManagementUnitOfWork:
        return SqlAlchemyCommitmentManagementUnitOfWork(work_engine)

    entra = settings.auth_mode is AuthMode.ENTRA
    principal = None if entra else local_principal()
    producer_origins = relationship_producer_origins(principal)

    class _NoRemoteHost:
        def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - refusing protocol sentinel
            raise RuntimeError(f"remote Apple control cannot call a local host: {name}")

    class _NoProposals:
        def open_review_proposals(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
            del version_ids
            return ()

    def apple_controller(store: Any) -> NativeSourceController:  # noqa: ANN401 - callback protocol
        return NativeSourceController(
            store=store, host=_NoRemoteHost(), audit=audit, proposals=_NoProposals()
        )

    apple_control = (
        SqlAppleMachineControl(work_engine, apple_controller)
        if settings.apple_ingress_enabled
        else None
    )
    return GatewayRuntime(
        service=ApplicationService(
            unit_of_work=unit_of_work,
            limits=settings.effective_limits(),
            managed_store=managed_byte_store(settings, work_engine),
            task_management_unit_of_work=task_management_unit_of_work,
            commitment_management_unit_of_work=commitment_management_unit_of_work,
            relationship_intelligence_enabled=settings.relationship_intelligence_enabled,
            relationship_intelligence_writes_enabled=(
                settings.relationship_intelligence_writes_enabled
            ),
            relationship_memory_enabled=settings.relationship_memory_enabled,
            relationship_identity_correction_enabled=(
                settings.relationship_identity_correction_enabled
            ),
            relationship_reenrichment_enabled=(
                settings.relationship_intelligence_enabled
                and settings.relationship_intelligence_writes_enabled
            ),
            producer_origins=producer_origins,
            gsqs_b0_ports=WorkflowPorts(poster=post_chat_completion),
        ),
        principal=principal,
        authenticate=entra_authenticator(settings, work_engine) if entra else None,
        # Composed only when the operator turned the ingress on. There is no
        # `or`, no fallback and no third state: an unset variable produces
        # `False` and `False` produces `None`, so a process that was never
        # configured for remote capture cannot serve it.
        remote_client=(
            remote_client_authenticator(settings, work_engine)
            if settings.remote_ingress_enabled
            else None
        ),
        apple_authenticate=(
            (lambda header: authenticate_apple_bridge_credential(work_engine, header))
            if settings.apple_ingress_enabled
            else None
        ),
        apple_control=apple_control,
        mcp_enabled=mcp_surface_enabled(settings, work_engine, principal),
        work_engine=work_engine,
        audit_engine=audit_engine,
    )
