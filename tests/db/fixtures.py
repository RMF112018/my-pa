"""Pytest fixtures for disposable PostgreSQL provisioning.

Root ``tests/conftest.py`` remains the FAST fake world. These fixtures are
requested only by database-tier tests.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

import pytest
from sqlalchemy import Connection, Engine
from sqlalchemy.engine import URL

from my_pa.infrastructure.database.engine import create_database_engine
from tests.db.provisioning import (
    CLONE_KIND,
    COUNTERS,
    DATABASE_URL_VARIABLE,
    EMPTY_KIND,
    TEMPLATE_KIND,
    WorkerHeadTemplate,
    clone_database,
    configured_application_url,
    create_empty_database,
    disposable_database_name,
    force_drop_database,
    maintenance_url_from,
    new_run_id,
    protected_from,
    restored_environ,
    sanitize_worker_id,
    terminate_sessions,
    upgrade_head,
    url_for_database,
)

_NARROW_MARKERS: Final = frozenset(
    {
        "database_clone",
        "database_transactional",
        "recovery",
        "e2e",
        "migration_edge",
        "migration_empty_to_head",
        "migration_historical",
        "migration",
    }
)


def pytest_configure(config: pytest.Config) -> None:
    """Markers are declared in pyproject.toml; this hook exists for xdist copies."""

    _ = config


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Default ordinary database tests onto clone isolation unless already classified."""

    clone = pytest.mark.database_clone
    edge = pytest.mark.migration_edge
    empty = pytest.mark.migration_empty_to_head
    loader = pytest.mark.migration
    for item in items:
        names = {marker.name for marker in item.iter_markers()}
        path = str(getattr(item, "path", "")).replace("\\", "/")
        if path.endswith("test_head_round_trip.py"):
            if "migration_empty_to_head" not in names:
                item.add_marker(empty)
            continue
        if "/tests/migration/" in f"/{path}":
            if "database" in names and not names & {
                "migration",
                "migration_edge",
                "migration_empty_to_head",
            }:
                item.add_marker(loader)
            continue
        if path.endswith("_migration.py") or path.endswith(
            "test_every_revision_denotes_one_schema.py"
        ):
            if not names & {
                "migration_edge",
                "migration_empty_to_head",
                "migration_historical",
                "migration",
            }:
                item.add_marker(edge)
            continue
        if "database" not in names:
            continue
        if names & _NARROW_MARKERS:
            continue
        item.add_marker(clone)


@dataclass
class _Sequences:
    clone: int = 0
    empty: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def next_clone(self) -> int:
        with self.lock:
            self.clone += 1
            return self.clone

    def next_empty(self) -> int:
        with self.lock:
            self.empty += 1
            return self.empty


@pytest.fixture(scope="session")
def provisioning_worker_id(request: pytest.FixtureRequest) -> str:
    """``master`` or the xdist worker id, without depending on pytest-xdist."""

    workerinput = getattr(request.config, "workerinput", None)
    if not workerinput:
        return "master"
    return sanitize_worker_id(str(workerinput.get("workerid", "master")))


@pytest.fixture(scope="session")
def provisioning_run_id() -> str:
    return new_run_id()


@pytest.fixture(scope="session")
def postgres_admin_url() -> URL:
    """Maintenance URL on ``postgres``, derived from the disposable CI/test URL."""

    return maintenance_url_from(configured_application_url())


@pytest.fixture(scope="session")
def postgres_admin_engine(postgres_admin_url: URL) -> Iterator[Engine]:
    engine = create_database_engine(postgres_admin_url, statement_timeout_ms=None)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(scope="session")
def provisioning_sequences() -> _Sequences:
    return _Sequences()


@pytest.fixture(scope="session")
def worker_head_template(
    postgres_admin_engine: Engine,
    provisioning_run_id: str,
    provisioning_worker_id: str,
) -> Iterator[WorkerHeadTemplate]:
    """Empty database migrated to head exactly once for this worker."""

    configured = configured_application_url()
    protected = protected_from(configured)
    name = disposable_database_name(TEMPLATE_KIND, provisioning_run_id, provisioning_worker_id)
    url = url_for_database(configured, name)
    create_empty_database(postgres_admin_engine, name, protected=protected)
    try:
        upgrade_head(url)
        # Template must be connection-free before any CREATE DATABASE ... TEMPLATE.
        terminate_sessions(postgres_admin_engine, name)
        yield WorkerHeadTemplate(
            name=name,
            url=url,
            run_id=provisioning_run_id,
            worker_id=provisioning_worker_id,
        )
    finally:
        force_drop_database(postgres_admin_engine, name, protected=protected)


@pytest.fixture
def cloned_database_url(
    worker_head_template: WorkerHeadTemplate,
    postgres_admin_engine: Engine,
    provisioning_sequences: _Sequences,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Per-test catalog cloned from the worker's current-head template."""

    configured = configured_application_url()
    protected = protected_from(configured)
    name = disposable_database_name(
        CLONE_KIND,
        worker_head_template.run_id,
        worker_head_template.worker_id,
        provisioning_sequences.next_clone(),
    )
    clone_database(
        postgres_admin_engine,
        name,
        worker_head_template.name,
        protected=protected,
    )
    url = url_for_database(configured, name)
    monkeypatch.setenv("MY_PA_DATABASE_URL", url)
    try:
        yield url
    finally:
        force_drop_database(postgres_admin_engine, name, protected=protected)


@pytest.fixture(scope="module")
def module_cloned_database_url(
    worker_head_template: WorkerHeadTemplate,
    postgres_admin_engine: Engine,
    provisioning_sequences: _Sequences,
) -> Iterator[str]:
    """One current-head clone per module, for expensive shared seed data."""

    configured = configured_application_url()
    protected = protected_from(configured)
    name = disposable_database_name(
        CLONE_KIND,
        worker_head_template.run_id,
        worker_head_template.worker_id,
        provisioning_sequences.next_clone(),
    )
    clone_database(
        postgres_admin_engine,
        name,
        worker_head_template.name,
        protected=protected,
    )
    url = url_for_database(configured, name)
    with restored_environ({DATABASE_URL_VARIABLE: url}):
        yield url
    force_drop_database(postgres_admin_engine, name, protected=protected)


@pytest.fixture
def disposable_database(cloned_database_url: str) -> str:
    """Current-head clone URL under the historic fixture name.

    Migration modules that still need an empty catalog keep a local fixture of
    the same name, which overrides this one.
    """

    return cloned_database_url


@pytest.fixture
def db_engine(cloned_database_url: str) -> Iterator[Engine]:
    engine = create_database_engine(cloned_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def migrated_engine(db_engine: Engine) -> Engine:
    """Current-head engine. Does not invoke Alembic."""

    return db_engine


@pytest.fixture
def empty_database_url(
    postgres_admin_engine: Engine,
    provisioning_run_id: str,
    provisioning_worker_id: str,
    provisioning_sequences: _Sequences,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[str]:
    """Empty disposable catalog for migration-contract tests."""

    configured = configured_application_url()
    protected = protected_from(configured)
    name = disposable_database_name(
        EMPTY_KIND,
        provisioning_run_id,
        provisioning_worker_id,
        provisioning_sequences.next_empty(),
    )
    create_empty_database(postgres_admin_engine, name, protected=protected)
    url = url_for_database(configured, name)
    monkeypatch.setenv("MY_PA_DATABASE_URL", url)
    try:
        yield url
    finally:
        force_drop_database(postgres_admin_engine, name, protected=protected)


@pytest.fixture(scope="session")
def worker_transactional_url(
    worker_head_template: WorkerHeadTemplate,
    postgres_admin_engine: Engine,
) -> Iterator[str]:
    """One current-head clone per worker for savepoint-rollback tests."""

    configured = configured_application_url()
    protected = protected_from(configured)
    name = disposable_database_name(
        CLONE_KIND,
        worker_head_template.run_id,
        worker_head_template.worker_id,
        0,
    )
    clone_database(
        postgres_admin_engine,
        name,
        worker_head_template.name,
        protected=protected,
    )
    url = url_for_database(configured, name)
    try:
        yield url
    finally:
        force_drop_database(postgres_admin_engine, name, protected=protected)


@pytest.fixture
def transactional_connection(worker_transactional_url: str) -> Iterator[Connection]:
    """One connection whose transaction is rolled back after the test.

    Not for tests of commit visibility, DDL, or multiple independent engines.
    """

    engine = create_database_engine(worker_transactional_url)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        yield connection
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Emit provisioning counters when a report was requested."""

    _ = session
    _ = exitstatus
    import os

    if os.environ.get("PYTEST_PROVISIONING_REPORT") != "1":
        return
    snapshot = COUNTERS.snapshot()
    print(
        "provisioning_counters " + " ".join(f"{key}={value}" for key, value in snapshot.items()),
        flush=True,
    )


# Imported by migration tests that opt into sanitised Alembic against an empty DB.
__all__ = [
    "cloned_database_url",
    "db_engine",
    "disposable_database",
    "empty_database_url",
    "migrated_engine",
    "postgres_admin_url",
    "transactional_connection",
    "worker_head_template",
]
