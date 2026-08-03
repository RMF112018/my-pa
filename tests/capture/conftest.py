"""One disposable database and one composed runtime for the capture-plane suite.

Every module in this package proves a `QC-AC-` criterion against the **real**
composition — `bootstrap.gateway.build_gateway_runtime`, the same one
`apps/gateway.py` and `apps/cli/invoke.py` are handed — over a PostgreSQL
database this package creates and drops. Nothing here is a fake: the criteria
are about a transaction, a unique index, and a trigger, and none of those exists
in a Python dictionary. `tests/conftest.py`'s `FakeUnitOfWork` reproduces the
*rule* for the FAST tier and says so; this is where the rule is checked against
the thing that enforces it.

**One database for the package, truncated per test.** The alternative — one per
module — pays for a full `alembic upgrade head` four times over to prove nothing
extra, and the database tier is already the slow one. The truncation is
enumerated rather than a `CASCADE` from `captures` alone, so a table added to the
capture plane has to be acknowledged here rather than silently accumulating rows
across tests.

**The database is never the configured one.** These fixtures repoint
`MY_PA_DATABASE_URL` for their own lifetime and restore it afterwards; the
canonical `my_pa` corpus is not migrated, truncated, or opened.

Every value in this package is synthetic. No path is opened, no source is
reached, no credential is used, and the only socket bound is a loopback one.
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

from my_pa.application.commands import Command
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one. Distinct from every other suite's disposable database, so they cannot
#: collide — the database tier runs serially and these names are server-global.
DISPOSABLE_DATABASE: Final = "my_pa_capture_plane_test"

#: The five capture tables plus the audit table, emptied between tests. Named
#: rather than cascaded, so a sixth table is a decision rather than an omission.
_EMPTIED: Final = (
    "knowledge.captures",
    "knowledge.capture_versions",
    "knowledge.capture_receipts",
    "knowledge.capture_submissions",
    "knowledge.capture_jobs",
    "knowledge.audit_events",
)

#: The request clock every module in this package uses, so a stored
#: `server_received_at` is a value a test chose rather than whenever it ran.
WHEN: Final = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

#: Which purpose each capture capability is authorized under. Read from the
#: domain's own map rather than restated, so a purpose renamed in
#: `domain.identity.operation` is a failure here rather than a silent denial.
CAPTURE_PURPOSE: Final[dict[Capability, Purpose]] = {
    Capability.CAPTURE_CREATE: Purpose.CAPTURE_AUTHORING,
    Capability.CAPTURE_REVISE: Purpose.CAPTURE_AUTHORING,
    Capability.CAPTURE_READ: Purpose.CAPTURE_REVIEW,
    Capability.CAPTURE_LIST: Purpose.CAPTURE_REVIEW,
}


def _administer(maintenance: Engine, *statements: object) -> None:
    """CREATE and DROP DATABASE, which cannot run inside a transaction block."""
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="package")
def capture_database() -> Iterator[str]:
    """An empty database at head, dropped when the package finishes."""
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


def empty(engine: Engine) -> None:
    """Empty the capture plane and the audit table, without dropping anything."""
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {', '.join(_EMPTIED)} CASCADE"))


@pytest.fixture
def runtime(capture_database: str) -> Iterator[GatewayRuntime]:
    """The composition every transport is handed, over the disposable database."""
    built = build_gateway_runtime(Settings(database_url=capture_database))
    try:
        empty(built.work_engine)
        yield built
    finally:
        built.close()


def invoke(
    runtime: GatewayRuntime,
    capability: Capability,
    request: Command,
    tag: str,
    *,
    at: datetime = WHEN,
) -> ResponseEnvelope:
    """One request through the real application, as a transport would make it.

    The purpose is derived from the capability rather than passed, because every
    capture capability has exactly one and a test that chose its own would be
    able to prove a policy the domain does not hold.
    """
    return runtime.service.invoke(
        RequestMetadata(
            request_id=f"req-capture-{tag}",
            capability=capability,
            purpose=CAPTURE_PURPOSE[capability],
            principal_id=runtime.principal.principal_id,
            requested_at=at,
        ),
        request,
        principal=runtime.principal,
    )


def succeeded(envelope: ResponseEnvelope, what: str) -> dict[str, Any]:
    """The result payload, or a failure that names which step refused.

    An empty payload is a failure here rather than a pass: the slice's failure
    mode is silent, and "it did not raise" is the assertion this repository does
    not accept.
    """
    assert envelope.error is None, (
        f"{what} refused with {envelope.error.code if envelope.error else None}"
    )
    assert isinstance(envelope.result, dict) and envelope.result, (
        f"{what} succeeded with an empty payload, which is the silent failure to catch"
    )
    return envelope.result


def counts(engine: Engine) -> dict[str, int]:
    """How many rows each capture table holds. The measurement, not a guess."""
    with engine.connect() as connection:
        return {
            # S608: every name is a literal in `_EMPTIED`; nothing here is input.
            table: int(
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()  # noqa: S608
            )
            for table in _EMPTIED
        }
