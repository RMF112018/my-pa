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

One `Principal`, issued at startup, `OPERATOR`, authenticated. Loopback is the
trust boundary and a local principal is the only principal (`D-30`); no
credential is issued, read, or required, and no authentication mechanism is
selected, because `P00-OD-010` is open and that choice is the operator's.
`OPERATOR` rather than `GATEWAY` because the process *is* the operator's local
transport — a `GATEWAY` principal cannot invoke `sources.enroll`, so the choice
is between naming what this is and shipping a transport that cannot reach one of
the fifteen capabilities.

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

from dataclasses import dataclass

from sqlalchemy import Engine

from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = ["GatewayRuntime", "build_gateway_runtime", "local_principal"]


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


@dataclass(frozen=True, slots=True)
class GatewayRuntime:
    """The application, the principal, and the two engines behind them.

    Both engines are exposed rather than hidden, because the reason there are
    two is a claim that has to be testable: a test that could not reach them
    could only assert that requests succeed, which a lucky ordering also does.
    """

    service: ApplicationService
    principal: Principal
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
    work_engine = create_database_engine(
        settings.database_url, statement_timeout_ms=settings.statement_timeout_ms
    )
    audit_engine = create_database_engine(
        settings.database_url, statement_timeout_ms=settings.statement_timeout_ms
    )
    audit = SqlAlchemyAuditSink(audit_engine)

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(work_engine, audit=audit)

    return GatewayRuntime(
        service=ApplicationService(
            unit_of_work=unit_of_work,
            limits=settings.effective_limits(),
        ),
        principal=local_principal(),
        work_engine=work_engine,
        audit_engine=audit_engine,
    )
