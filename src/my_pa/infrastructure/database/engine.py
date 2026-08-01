"""Engine and health check for the canonical `my_pa` database.

Synchronous by design. The workload this serves is a batch load and its
verification queries: it is bounded by PostgreSQL's write path, not by waiting
on many concurrent sockets, so async would add lifecycle, testing, and debugging
cost for no throughput.

Nothing here reads process settings. The caller passes a URL, which keeps
configuration in bootstrap and makes a disposable test database a plain
argument rather than a special case.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from sqlalchemy import Engine, create_engine, text

__all__ = ["DatabaseHealth", "create_database_engine", "healthcheck"]

#: A single-user local bulk load runs a handful of long-lived connections, so
#: the pool is small and hard-bounded: overflow is disabled so that a leak
#: surfaces as a timeout here rather than as an unbounded number of backends on
#: a server sized for a fixed few.
_POOL_SIZE: Final = 5
_POOL_TIMEOUT_SECONDS: Final = 30

#: The container can be restarted between batches. One round trip per checkout
#: is far cheaper than losing a batch to a stale connection.
_POOL_PRE_PING: Final = True


@dataclass(frozen=True, slots=True)
class DatabaseHealth:
    """What a reachable server reported. Carries no row content."""

    server_version: str
    extensions: tuple[str, ...]


def create_database_engine(url: str) -> Engine:
    """Build the engine for `url`.

    Callers own the engine's lifetime and should `dispose()` it when finished.
    """
    return create_engine(
        url,
        pool_size=_POOL_SIZE,
        max_overflow=0,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
        pool_pre_ping=_POOL_PRE_PING,
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
