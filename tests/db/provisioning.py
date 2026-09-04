"""Shared disposable-PostgreSQL allocation for the test suite.

The configured application database is never created, dropped, migrated, or
cloned. Every name this module mutates must match the disposable prefix and
must not equal a protected catalog name.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import URL, make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings

ROOT: Final = Path(__file__).resolve().parents[2]
DATABASE_URL_VARIABLE: Final = f"{ENV_PREFIX}DATABASE_URL"

#: Disposable names this helper is allowed to create or drop. Anything else is
#: treated as a canonical or foreign catalog and refused.
DISPOSABLE_NAME_PREFIX: Final = "my_pa_p_"
TEMPLATE_KIND: Final = "t"
CLONE_KIND: Final = "c"
EMPTY_KIND: Final = "e"

_NAME_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_WORKER_RE: Final = re.compile(r"[^a-z0-9]+")

PROTECTED_CATALOGS: Final = frozenset({"postgres", "template0", "template1", "my_pa"})

#: Workstation variables that can opt a migration into a legacy import. Routine
#: current-schema provisioning must not inherit them accidentally.
LEGACY_IMPORT_VARIABLES: Final = (
    "MY_PA_LEGACY_SQLITE_PATH",
    "MY_PA_LEGACY_EXPORT_PATH",
    "MY_PA_LEGACY_CORPUS_PATH",
    "HB_PA_SQLITE_PATH",
    "HB_PA_EXPORT_PATH",
)

POSTGRESQL_IDENTIFIER_LIMIT: Final = 63


class ProvisioningError(RuntimeError):
    """A disposable-database operation was refused or could not complete."""


@dataclass
class ProvisioningCounters:
    """Process-local counts of provisioning operations."""

    upgrade_head: int = 0
    database_create: int = 0
    database_drop: int = 0
    clone_create: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def bump(self, field_name: str, amount: int = 1) -> None:
        with self.lock:
            setattr(self, field_name, getattr(self, field_name) + amount)

    def snapshot(self) -> dict[str, int]:
        with self.lock:
            return {
                "upgrade_head": self.upgrade_head,
                "database_create": self.database_create,
                "database_drop": self.database_drop,
                "clone_create": self.clone_create,
            }


COUNTERS: Final = ProvisioningCounters()


def reset_counters() -> None:
    """Return the process counters to zero. Tests of the helper itself use this."""

    with COUNTERS.lock:
        COUNTERS.upgrade_head = 0
        COUNTERS.database_create = 0
        COUNTERS.database_drop = 0
        COUNTERS.clone_create = 0


def new_run_id() -> str:
    """Eight lowercase hex characters identifying one pytest process."""

    return uuid.uuid4().hex[:8]


def sanitize_worker_id(worker_id: str) -> str:
    """Collapse an xdist worker id (or ``master``) into a PostgreSQL-safe token."""

    token = _WORKER_RE.sub("", worker_id.strip().lower()) or "master"
    return token[:16]


def disposable_database_name(
    kind: str, run_id: str, worker_id: str, sequence: int | None = None
) -> str:
    """Build a unique disposable catalog name at or under 63 bytes."""

    if kind not in {TEMPLATE_KIND, CLONE_KIND, EMPTY_KIND}:
        raise ProvisioningError(f"unknown disposable kind {kind!r}")
    worker = sanitize_worker_id(worker_id)
    run = run_id.lower()
    if not re.fullmatch(r"[a-z0-9]{1,16}", run):
        raise ProvisioningError(f"run id {run_id!r} is not a bounded token")
    if sequence is None:
        name = f"{DISPOSABLE_NAME_PREFIX}{kind}_{run}_{worker}"
    else:
        if sequence < 0:
            raise ProvisioningError("sequence must be non-negative")
        name = f"{DISPOSABLE_NAME_PREFIX}{kind}_{run}_{worker}_{sequence}"
    return require_disposable_name(name)


def require_disposable_name(name: str) -> str:
    """Refuse a catalog name that is not this helper's disposable vocabulary."""

    if len(name.encode("ascii", "strict")) > POSTGRESQL_IDENTIFIER_LIMIT:
        raise ProvisioningError(
            f"database name exceeds {POSTGRESQL_IDENTIFIER_LIMIT} bytes: {name!r}"
        )
    if not _NAME_RE.fullmatch(name):
        raise ProvisioningError(f"database name is not a PostgreSQL-safe identifier: {name!r}")
    if name in PROTECTED_CATALOGS or not name.startswith(DISPOSABLE_NAME_PREFIX):
        raise ProvisioningError(f"refusing to operate on non-disposable database {name!r}")
    return name


def maintenance_url_from(configured: URL) -> URL:
    """Admin URL on the same server, always targeting ``postgres``.

    The configured database name is the application catalog and is never the
    maintenance target.
    """

    if configured.database in {None, "", "postgres"}:
        raise ProvisioningError("configured URL does not name a distinct application database")
    return configured.set(database="postgres")


def url_for_database(configured: URL, name: str) -> str:
    """Render a connection string that names ``name`` on the configured server."""

    require_disposable_name(name)
    return configured.set(database=name).render_as_string(hide_password=False)


def configured_application_url() -> URL:
    """The process settings URL. Used only to derive maintenance and clone URLs."""

    return make_url(load_settings().database_url)


def protected_from(configured: URL) -> frozenset[str]:
    """Catalogs this helper must never create, drop, or clone onto."""

    names = set(PROTECTED_CATALOGS)
    if configured.database:
        names.add(configured.database)
    return frozenset(names)


def _assert_not_protected(
    name: str, protected: Mapping[str, object] | set[str] | frozenset[str]
) -> None:
    require_disposable_name(name)
    if name in protected:
        raise ProvisioningError(f"refusing to mutate protected database {name!r}")


def administer(engine: Engine, statements: Sequence[object]) -> None:
    """Run DDL that cannot live inside a transaction block."""

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def terminate_sessions(engine: Engine, database: str) -> None:
    """Disconnect every backend using ``database`` except this connection."""

    require_disposable_name(database)
    administer(
        engine,
        (
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ).bindparams(name=database),
        ),
    )


def force_drop_database(engine: Engine, name: str, *, protected: frozenset[str]) -> None:
    """Drop a disposable database, terminating leftover sessions first."""

    _assert_not_protected(name, protected)
    terminate_sessions(engine, name)
    administer(engine, (text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'),))
    COUNTERS.bump("database_drop")


def create_empty_database(engine: Engine, name: str, *, protected: frozenset[str]) -> None:
    """Create an empty disposable database. Drops a stale same-name catalog first."""

    _assert_not_protected(name, protected)
    force_drop_database(engine, name, protected=protected)
    COUNTERS.bump("database_drop", -1)
    administer(engine, (text(f'CREATE DATABASE "{name}"'),))
    COUNTERS.bump("database_create")


def clone_database(
    engine: Engine,
    name: str,
    template: str,
    *,
    protected: frozenset[str],
) -> None:
    """Create ``name`` as a copy of an immutable worker template."""

    _assert_not_protected(name, protected)
    require_disposable_name(template)
    if template in protected:
        raise ProvisioningError(f"refusing to clone protected template {template!r}")
    force_drop_database(engine, name, protected=protected)
    COUNTERS.bump("database_drop", -1)
    terminate_sessions(engine, template)
    administer(engine, (text(f'CREATE DATABASE "{name}" TEMPLATE "{template}"'),))
    COUNTERS.bump("database_create")
    COUNTERS.bump("clone_create")


def drop_stale_for_run(
    engine: Engine, run_id: str, *, protected: frozenset[str]
) -> tuple[str, ...]:
    """Force-drop leftover disposable catalogs from this run identity."""

    token = f"{DISPOSABLE_NAME_PREFIX}%_{run_id.lower()}_%"
    with engine.connect() as connection:
        names = tuple(
            str(row[0])
            for row in connection.execute(
                text("SELECT datname FROM pg_database WHERE datname LIKE :token"),
                {"token": token},
            )
        )
    dropped: list[str] = []
    for name in names:
        if name in protected:
            continue
        force_drop_database(engine, name, protected=protected)
        dropped.append(name)
    return tuple(dropped)


@contextmanager
def restored_environ(
    updates: Mapping[str, str | None],
) -> Iterator[None]:
    """Apply ``updates`` and restore the previous mapping, including unset keys.

    A value of ``None`` unsets the variable for the duration of the block.
    """

    previous: dict[str, str | None] = {}
    try:
        for key, value in updates.items():
            previous[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def sanitized_migration_environ(database_url: str) -> dict[str, str | None]:
    """Point Alembic at ``database_url`` and clear accidental legacy-import opts."""

    updates: dict[str, str | None] = {DATABASE_URL_VARIABLE: database_url}
    for name in LEGACY_IMPORT_VARIABLES:
        updates[name] = None
    return updates


def alembic_config() -> Config:
    """The repository Alembic config, with Alembic's own stdout discarded."""

    import io

    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def upgrade_head(database_url: str) -> None:
    """Run ``alembic upgrade head`` against ``database_url`` only."""

    require_disposable_name(make_url(database_url).database or "")
    with restored_environ(sanitized_migration_environ(database_url)):
        command.upgrade(alembic_config(), "head")
    COUNTERS.bump("upgrade_head")


@dataclass(frozen=True, slots=True)
class WorkerHeadTemplate:
    """Immutable current-head catalog owned by one pytest worker."""

    name: str
    url: str
    run_id: str
    worker_id: str
