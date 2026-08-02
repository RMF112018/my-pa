"""What the gateway is composed of, checked without a server or a database.

`bootstrap.gateway` makes four decisions, and three of them can be read off the
objects it returns without anything connecting: which principal the process
acts as, which source providers it has, and how many connection pools it holds.
The fourth — that two pools are what keeps the audit sink from starving the work
it records — needs a real server to demonstrate and lives in
`tests/concurrency/test_gateway_connection_pool.py`.

The URL below is well formed and unreachable, the same device
`tests/unit/test_settings.py` uses: `create_engine` does not connect, so a pool
can be inspected without one.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from my_pa.bootstrap.gateway import (
    GatewayRuntime,
    NoConfiguredSources,
    build_gateway_runtime,
    local_principal,
)
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import PrincipalKind
from my_pa.domain.source.registry import issue_identifier

A_URL = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"


@pytest.fixture
def runtime() -> Iterator[GatewayRuntime]:
    built = build_gateway_runtime(Settings(database_url=A_URL))
    try:
        yield built
    finally:
        built.close()


def test_the_work_and_audit_pools_are_two_pools(runtime: GatewayRuntime) -> None:
    """The whole of the deadlock fix, as a property of the composition.

    Two engines mean the audit sink draws from a pool that no work connection
    can occupy. One engine — however large — reintroduces the cycle as soon as
    the concurrency bound that made the arithmetic work stops holding.
    """
    assert runtime.work_engine is not runtime.audit_engine
    assert runtime.work_engine.pool is not runtime.audit_engine.pool
    assert runtime.work_engine.url == runtime.audit_engine.url


def test_each_pool_admits_one_connection_per_request_in_flight(runtime: GatewayRuntime) -> None:
    """The sizes, derived: the audit pool matches the work pool and no more.

    The sink needs at most one connection per request that is holding a work
    connection, and at most `work.size()` requests can hold one at a time. An
    audit pool smaller than that would queue audits behind each other; a larger
    one holds connections that could never all be used.
    """
    assert runtime.audit_engine.pool.size() == runtime.work_engine.pool.size()
    for engine in (runtime.work_engine, runtime.audit_engine):
        # No overflow: the bound is a bound, and a leak surfaces as a timeout
        # rather than as an unbounded number of backends.
        assert engine.pool._max_overflow == 0


def test_the_process_acts_as_one_authenticated_local_operator(runtime: GatewayRuntime) -> None:
    """`D-30`: loopback is the trust boundary and the principal is the process.

    `OPERATOR` rather than `GATEWAY` is load-bearing rather than incidental: a
    `GATEWAY` principal may not invoke `sources.enroll`, so the alternative is a
    transport that cannot reach one of the eight capabilities.
    """
    assert runtime.principal.kind is PrincipalKind.OPERATOR
    assert runtime.principal.authenticated is True
    assert runtime.principal.principal_id.startswith("prn_")


def test_two_runs_are_two_principals(runtime: GatewayRuntime) -> None:
    """Stated rather than hidden: the identifier names a run, not a person.

    A stable local identity is part of what `P00-OD-010` settles. Deriving one
    from the host or the account would put a personal value inside an opaque
    identifier, which `INV-PKL-005` forbids.
    """
    assert local_principal().principal_id != runtime.principal.principal_id


def test_no_source_provider_is_configured() -> None:
    """Truthful rather than convenient. See `bootstrap.gateway`'s docstring.

    Nothing registers a source in production (`D-37`) and no provider root is
    authorized (`P00-OD-009`), so the lookup answers `None` and the application
    reports `unavailable` for a source it cannot serve. A fixture root wired
    into a composition root would be an invented corpus.
    """
    providers = NoConfiguredSources()
    assert providers.for_source(issue_identifier(IdKind.SOURCE)) is None


def test_the_runtime_releases_both_pools() -> None:
    """`close` is what `apps/gateway.py` calls in its `finally`."""
    built = build_gateway_runtime(Settings(database_url=A_URL))
    built.close()
    # `dispose` replaces the pool; a second call must stay safe, because a
    # failed start calls it on the way out too.
    built.close()


def test_the_composition_reads_the_configured_limits() -> None:
    """The published limits are the configured ones, through the gateway too."""
    settings = Settings(database_url=A_URL, max_page_size=25, default_page_size=10)
    built = build_gateway_runtime(settings)
    try:
        assert built.service._limits.max_page_size == 25
        assert built.service._limits.default_page_size == 10
    finally:
        built.close()
