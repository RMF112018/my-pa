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
the eight capabilities.

The identifier is issued per process run, so an audit trail identifies a run
rather than a person. A stable local identity is part of what `P00-OD-010`
settles; deriving one from the host or the account would put a personal value in
an opaque identifier, which `INV-PKL-005` forbids.

## The providers

There are none, and that is stated rather than papered over. Nothing registers a
source in production — `register_source` and `observe_object` still have no
production caller, which is the hole `D-37` gives to WP-4B3 — and no provider
root is authorized, because `P00-OD-009` requires the operator to name one by
exact path and that has not happened. So the lookup answers `None`, and the
application reports `unavailable` for the source it cannot serve, which is the
truth. A fixture root wired here would be this module inventing a corpus.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import SourceProviders, UnitOfWork
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.source.provider import SourceProvider
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

__all__ = ["GatewayRuntime", "NoConfiguredSources", "build_gateway_runtime", "local_principal"]


class NoConfiguredSources(SourceProviders):
    """The source lookup of a build that has no source to look up.

    Not a placeholder that pretends: `for_source` answering `None` is what makes
    `sources.list`, `sources.metadata`, and `sources.fetch` report `unavailable`
    for a source whose adapter is not wired, which is exactly the state this
    build is in. See this module's docstring for why there is nothing to wire.
    """

    def for_source(self, source_id: str) -> SourceProvider | None:
        return None


def local_principal() -> Principal:
    """The one principal this process acts as. See the module docstring."""
    return Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
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
    work_engine = create_database_engine(settings.database_url)
    audit_engine = create_database_engine(settings.database_url)
    audit = SqlAlchemyAuditSink(audit_engine)

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(work_engine, audit=audit)

    return GatewayRuntime(
        service=ApplicationService(
            unit_of_work=unit_of_work,
            providers=NoConfiguredSources(),
            limits=settings.effective_limits(),
        ),
        principal=local_principal(),
        work_engine=work_engine,
        audit_engine=audit_engine,
    )
