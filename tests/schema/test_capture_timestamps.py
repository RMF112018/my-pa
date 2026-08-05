"""`QC-AC-012`: five timestamps, stored separately, none defaulting from another.

**Five, not three.** The plan's `QC-AC-012` bullet, in section 12's WP-6 entry,
paraphrased this criterion as `client_created_at`, `server_received_at` and
`recorded_at`, silently dropping *occurred* and *accepted*.
`docs/specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:191` requires
"**device, server, occurred, processed, and accepted** timestamps remain
distinct", and `D-75` rules that the spec governs and the plan is corrected.
Taking the paraphrase would have narrowed the criterion by two columns, which is
why the number is asserted here as well as the distinctness.

The five columns are `client_created_at` (device), `server_received_at`
(server), `occurred_at`, `recorded_at` (processed) and `accepted_at`. Four are
supplied by the caller and the admitting layer; `recorded_at` is written by the
**server's own clock inside the statement**, which is what makes it a genuinely
different reading rather than a copy of one of the others.

**The control is a row that legitimately has fewer.** A transport with no device
clock supplies no `client_created_at`, and a note about no particular moment has
no `occurred_at`. Those store `NULL`. Inventing a value — the request clock
wearing a device's name — would be laundering an absence into a fact, and it is
the failure a five-distinct-values assertion on its own would not notice,
because five invented values are still five distinct values.

The database is disposable, created and dropped by its fixture, and never the
configured one. Every value is synthetic; no path is opened.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import CaptureAdmissionRequest
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture import admit_capture
from my_pa.infrastructure.persistence.principal_scope import capture_context

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_capture_timestamps_test"

#: The five columns the criterion names, in the spec's own order: device,
#: server, occurred, processed, accepted. Written out so that a column dropped
#: from the table is a failure here rather than a criterion quietly satisfied by
#: four.
TIMESTAMP_COLUMNS: Final = (
    "client_created_at",
    "server_received_at",
    "occurred_at",
    "recorded_at",
    "accepted_at",
)

#: Four distinct moments, one per caller-supplied column, far enough apart that
#: no rounding could make two of them equal and all safely in the past so that
#: the server's own clock cannot coincide with one.
DEVICE: Final = datetime(2026, 8, 3, 9, 0, 0, tzinfo=UTC)
SERVER: Final = datetime(2026, 8, 3, 9, 1, 0, tzinfo=UTC)
OCCURRED: Final = datetime(2026, 8, 1, 17, 30, 0, tzinfo=UTC)
ACCEPTED: Final = datetime(2026, 8, 3, 9, 2, 0, tzinfo=UTC)


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
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


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.captures, knowledge.capture_versions, "
                    "knowledge.capture_receipts, knowledge.capture_submissions, "
                    "knowledge.capture_jobs CASCADE"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _admit(
    engine: Engine,
    *,
    key: str,
    client_created_at: datetime | None,
    occurred_at: datetime | None,
) -> str:
    """Store one capture through the production writer. Returns its version."""
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    with engine.begin() as connection:
        admission = admit_capture(
            connection,
            CaptureAdmissionRequest(
                capture_id=None,
                content=CaptureContent("a note whose five times are the subject"),
                idempotency_key=key,
                request_id=f"req-{key}",
                correlation_id=issue_identifier(IdKind.CORRELATION),
                principal_id=principal_id,
                audit_id=issue_identifier(IdKind.AUDIT),
                classification=Classification.PRIVATE_LOCAL,
                processing_policy=ProcessingPolicy.LOCAL_ONLY,
                server_received_at=SERVER,
                accepted_at=ACCEPTED,
                client_created_at=client_created_at,
                occurred_at=occurred_at,
            ),
            context=capture_context(principal_id),
        )
    return admission.receipt.version_id


def _times(engine: Engine, version_id: str) -> dict[str, datetime | None]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                # S608: the column names are literals in `TIMESTAMP_COLUMNS`.
                f"SELECT {', '.join(TIMESTAMP_COLUMNS)} FROM knowledge.capture_versions "  # noqa: S608
                "WHERE version_id = :id"
            ),
            {"id": version_id},
        ).one()
    return dict(zip(TIMESTAMP_COLUMNS, row, strict=True))


@pytest.mark.database
def test_all_five_timestamps_are_stored_separately_and_none_equals_another(
    engine: Engine,
) -> None:
    """The criterion at its spec strength: five columns, five distinct values.

    Each supplied value is required back out of the store *as supplied*, which
    is what says the columns are stored separately rather than derived. The
    distinctness is then asserted over the set, so a build that defaulted any
    one of them from any other fails whichever pair it collapsed.
    """
    version_id = _admit(engine, key="times-1", client_created_at=DEVICE, occurred_at=OCCURRED)
    stored = _times(engine, version_id)

    assert len(stored) == 5, (
        f"the version carries {len(stored)} timestamp columns. The spec requires "
        "five — device, server, occurred, processed and accepted — and the plan's "
        "paraphrase named three"
    )
    assert all(value is not None for value in stored.values()), stored

    # Each caller-supplied value survives as itself.
    assert stored["client_created_at"] == DEVICE
    assert stored["server_received_at"] == SERVER
    assert stored["occurred_at"] == OCCURRED
    assert stored["accepted_at"] == ACCEPTED

    # And the fifth is the server's own reading, taken inside the statement, so
    # it is a different clock rather than a copy of one that arrived.
    recorded = stored["recorded_at"]
    assert recorded is not None
    assert recorded > ACCEPTED, (
        "`recorded_at` is not later than the moment the admission decided, so it "
        "is not being written from the server's own clock"
    )

    assert len(set(stored.values())) == 5, (
        f"two of the five timestamps are equal: {stored}. Each has its own origin "
        "and none is defaulted from another; a collapse here is the criterion "
        "narrowed to however many distinct clocks the writer happens to read"
    )


@pytest.mark.database
def test_a_genuinely_absent_client_time_is_stored_as_null_and_not_invented(
    engine: Engine,
) -> None:
    """The control: an absence is preserved rather than filled in.

    Five distinct values would still be five distinct values if two of them had
    been invented from the request clock, so the assertion above cannot see this
    failure. A transport with no device clock and a note about no particular
    moment store `NULL` in both columns, and the three that are always known are
    required to be present and distinct in the same row — so this is an absence
    beside a presence rather than an empty row.
    """
    version_id = _admit(engine, key="times-2", client_created_at=None, occurred_at=None)
    stored = _times(engine, version_id)

    assert stored["client_created_at"] is None, (
        f"a request that supplied no device time stored {stored['client_created_at']!r}. "
        "Inventing one would be a fact about this process wearing a device's name"
    )
    assert stored["occurred_at"] is None

    present = {
        name: value
        for name, value in stored.items()
        if name not in {"client_created_at", "occurred_at"}
    }
    assert all(value is not None for value in present.values()), present
    assert len(set(present.values())) == 3, (
        f"the three timestamps this row does have are not distinct: {present}"
    )

    # And the two rows differ in exactly the two nullable columns, which is what
    # makes the nulls above a property of the request rather than of the table.
    with_times = _times(
        engine, _admit(engine, key="times-3", client_created_at=DEVICE, occurred_at=OCCURRED)
    )
    assert with_times["client_created_at"] == DEVICE
    assert with_times["occurred_at"] == OCCURRED
