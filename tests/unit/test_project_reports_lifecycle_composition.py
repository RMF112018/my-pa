"""WP3P-S4 (ruling D5): the project-reports lifecycle is its own; the generic admit refuses it.

FAST tier. The two composition roots are built exactly as the operator CLIs
and the cycles plane build them (lazily: no workspace root and no database is
touched). Proved here:

* the communications lifecycle (`bootstrap.communications_ingest`) holds no
  project-report handler, so `communications_ingest.py admit --consumer
  pulse_csv_export` refuses `consumer_not_registered` and admits nothing --
  a project-report source is admitted only by `bindings apply`, beside its
  binding;
* the project-reports lifecycle (`bootstrap.project_reports`) holds only the
  `pulse_csv_export` handler;
* the two lifecycles contend for two distinct advisory locks, and the
  project-reports key is derived like the communications key from its own
  neutral label.

The end-to-end refusal of the generic command on PostgreSQL is in
`tests/database/test_project_reports_bindings.py`.
"""

from __future__ import annotations

import os
from typing import Final

import pytest
from sqlalchemy import create_engine

from my_pa.application.ingestion import IngestRefusalCode, IngestRefusedError
from my_pa.bootstrap.communications_ingest import ingestion_lifecycle
from my_pa.bootstrap.project_reports import project_reports_lifecycle
from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import IngestConsumer
from my_pa.infrastructure.jobs.cycle_scheduler import (
    COMMS_INGEST_LOCK_KEY,
    CYCLE_SCHEDULER_LOCK_KEY,
    PROJECT_REPORTS_POLL_LOCK_KEY,
    advisory_lock_key,
)
from tests.unit.communications_ingest_fakes import IngestWorld, unit_of_work_factory

DSN: Final = "postgresql+psycopg://synthetic@localhost.invalid:1/synthetic_catalog"


@pytest.fixture
def composed(monkeypatch: pytest.MonkeyPatch) -> tuple[object, object]:
    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", DSN)
    settings = load_settings()
    engine = create_engine(DSN)  # lazy: never connects here
    return ingestion_lifecycle(settings, engine), project_reports_lifecycle(settings, engine)


def test_the_communications_lifecycle_holds_no_project_report_handler(
    composed: tuple[object, object],
) -> None:
    communications, _ = composed
    consumers = communications.consumers  # type: ignore[attr-defined]
    assert IngestConsumer.PULSE_CSV_EXPORT not in consumers
    assert consumers == {IngestConsumer.COMMUNICATIONS_EVIDENCE_V2, IngestConsumer.MEETING_SYNC_V1}


def test_the_project_reports_lifecycle_holds_only_its_consumer(
    composed: tuple[object, object],
) -> None:
    _, project_reports = composed
    assert project_reports.consumers == {IngestConsumer.PULSE_CSV_EXPORT}  # type: ignore[attr-defined]


def test_the_generic_admit_refuses_the_project_report_consumer_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The communications composition, over the FAST lifecycle rows."""
    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", DSN)
    lifecycle = ingestion_lifecycle(load_settings(), create_engine(DSN))
    world = IngestWorld()
    monkeypatch.setattr(lifecycle, "_unit_of_work", unit_of_work_factory(world))
    with pytest.raises(IngestRefusedError) as refused:
        lifecycle.admit(
            "prn_syncomposed0001",
            consumer=IngestConsumer.PULSE_CSV_EXPORT,
            workspace_id="mcp",
            path_prefix="Synthetic Area/Alpha/",
            file_pattern="*.csv",
        )
    assert refused.value.code is IngestRefusalCode.CONSUMER_NOT_REGISTERED
    assert world.sources == {}
    assert world.commits == world.rollbacks == 0


def test_the_project_reports_lock_is_its_own_neutral_key() -> None:
    assert advisory_lock_key(b"my-pa-project-reports-poll") == PROJECT_REPORTS_POLL_LOCK_KEY
    assert (
        len({PROJECT_REPORTS_POLL_LOCK_KEY, COMMS_INGEST_LOCK_KEY, CYCLE_SCHEDULER_LOCK_KEY}) == 3
    )
