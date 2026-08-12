"""Engine and health check for the canonical `my_pa` database.

Synchronous by design. The workload this serves is a batch load and its
verification queries: it is bounded by PostgreSQL's write path, not by waiting
on many concurrent sockets, so async would add lifecycle, testing, and debugging
cost for no throughput.

Nothing here reads process settings. The caller passes a URL and, where the
caller is one whose statements are bounded, a `statement_timeout`; both come from
`bootstrap.settings`, which keeps configuration in bootstrap and makes a
disposable test database a plain argument rather than a special case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import Engine, create_engine, text

__all__ = [
    "POOL_TIMEOUT_SECONDS",
    "DatabaseHealth",
    "create_database_engine",
    "healthcheck",
]

#: A single-user local bulk load runs a handful of long-lived connections, so
#: the pool is small and hard-bounded: overflow is disabled so that a leak
#: surfaces as a timeout here rather than as an unbounded number of backends on
#: a server sized for a fixed few.
_POOL_SIZE: Final = 5

#: How long a checkout may wait for a connection. Public, and the reason is
#: `bootstrap.settings`: `DEFAULT_STATEMENT_TIMEOUT_MS` is this number in
#: milliseconds, so a request's two waits — for a connection, then on the
#: server — have one ceiling. That equality was written in a comment and
#: nowhere else, which is the `D-24` shape the same package exists to correct;
#: it is now computed from this name, so the two cannot drift.
POOL_TIMEOUT_SECONDS: Final = 30

#: The container can be restarted between batches. One round trip per checkout
#: is far cheaper than losing a batch to a stale connection.
_POOL_PRE_PING: Final = True

#: The libpq option a `statement_timeout` is set through. A connection option
#: rather than a `SET` on each connection, so it is in force from the first
#: statement a checkout runs, including the pre-ping, and cannot be left behind
#: by a code path that forgot to issue the `SET`.
#:
#: **No default is written here, and that is the point.** The number is
#: `MY_PA_STATEMENT_TIMEOUT_MS`, which `bootstrap.settings` owns; a literal here
#: would be a second copy of it for the configured one to drift from, which is
#: the shape `D-24` already corrected once for the four limit fields.
_STATEMENT_TIMEOUT_OPTION: Final = "-c statement_timeout={milliseconds}"


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    """What a reachable server reported. Carries no row content."""

    server_version: str
    extensions: tuple[str, ...]


def create_database_engine(url: str, *, statement_timeout_ms: int | None = None) -> Engine:
    """Build the engine for `url`.

    Callers own the engine's lifetime and should `dispose()` it when finished.

    **`statement_timeout_ms` bounds what one statement may cost.** Without it the
    functional indexes remove the sequential scan as the *only* possibility
    without bounding anything: a query the planner gets wrong, or one over a
    corpus larger than the one it was measured on, runs until it finishes or the
    client goes away, holding a connection out of a pool of five with overflow
    disabled. The number comes from the caller because it comes from
    configuration — `MY_PA_STATEMENT_TIMEOUT_MS` — and this module reads no
    process settings, which is what lets a disposable test database be a plain
    argument.

    **`None` means no `statement_timeout` is set on this engine at all, and it is
    an exemption rather than an oversight.** Two kinds of caller need it, and
    both would be made *worse* by a bound:

    - **Alembic.** `migrations/env.py` builds its engine here and runs DDL
      through it. A `CREATE INDEX` over the full corpus, or a table rewrite, runs
      for as long as it runs; a timeout that cancels one leaves the database
      between revisions, which is a worse failure than the unbounded query it
      would be protecting against.
    - **The bulk corpus migration.** `apps/cli/migration.py` and
      `scripts/migration/reconcile.py` move and reconcile a 4.37 GB legacy
      corpus in statements sized to the corpus rather than to a request.

    Everything else — the gateway's two pools, the source CLI, the health probe
    and the worker — passes the configured value.
    `tests/architecture/test_every_engine_is_bounded_or_exempt.py` is what makes
    that a rule rather than a list: it derives every `create_database_engine`
    call in `src/`, `apps/`, `migrations/` and `scripts/` from the syntax tree
    and fails on one that neither passes the setting nor is named exempt.

    **One hazard, created here and closed in `bootstrap.settings`.** SQLAlchemy
    merges a URL's query parameters into the driver's connect arguments and lets
    `connect_args` win, so a `MY_PA_DATABASE_URL` carrying its own `options=`
    would be silently overridden here rather than combined — the operator's
    parameter discarded with no signal. `_validate_database_url` refuses such a
    URL at startup, which is the only place it can be refused: this function is
    handed a URL and does not know where it came from, and a check here would
    also refuse the disposable databases the tests build.
    """
    connect_args: dict[str, str] = {}
    if statement_timeout_ms is not None:
        connect_args["options"] = _STATEMENT_TIMEOUT_OPTION.format(
            milliseconds=statement_timeout_ms
        )
    return create_engine(
        url,
        pool_size=_POOL_SIZE,
        max_overflow=0,
        pool_timeout=POOL_TIMEOUT_SECONDS,
        pool_pre_ping=_POOL_PRE_PING,
        connect_args=connect_args,
    )


def healthcheck(engine: Engine) -> DatabaseHealth:
    """Prove the server is reachable and report what is installed on it.

    Raises whatever the driver raises when it is not reachable; a health check
    that swallows the reason is worse than no health check.
    """
    with engine.connect() as connection:
        version = connection.execute(text("SHOW server_version")).scalar_one()
        extensions = connection.execute(
            text("SELECT extname FROM pg_extension ORDER BY extname")
        ).scalars()
        return DatabaseHealth(server_version=str(version), extensions=tuple(extensions))
