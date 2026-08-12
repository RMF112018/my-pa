"""The user's evidence outlives the pipeline that failed to enrich it.

`tests/jobs/test_capture_pipeline_recovery.py` already proves the narrow storage
half: a failure injected inside `P-15`, after the proposal insert and before the
commit, leaves the capture row and its version byte-identical. What it does not
prove is the half a person actually experiences — that after the enrichment has
failed *for good*, the note can still be **read back and found**. A capture that
survives in a table nobody can reach through a capability is not evidence that
survived; it is data that was kept.

So this module asks the product through the capabilities a caller actually has —
`capture.create`, `capture.read` and `capture.search`:

* the pipeline is killed **hard and repeatedly** — every attempt raises, until
  the job's bounded retries are spent and it is terminal `failed`, which is a
  worse failure than the single mid-transaction one and is the one an operator
  would actually be looking at;
* the failure is then **visible**, not swallowed: a `failed` state, a public
  error code, and a spent attempt count, read from the row;
* `capture.read` returns the exact text, and `capture.search` finds it;
* and a **control** in the same test does a clean run over an identical note and
  produces proposals, so the absence of enrichment above is the kill's doing and
  not a pipeline that never worked.

**AI is not part of the save's success condition** (operating brief section 20),
and this is what that means when the AI half is not merely skipped but destroyed.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

import threading
from typing import Any, Final

import pytest
from sqlalchemy import Engine, Table, func, select
from tests.capture.conftest import invoke, succeeded

from my_pa.application.commands import CreateCapture, ReadCapture, SearchCaptures
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.infrastructure.jobs.capture_pipeline import process_capture_version
from my_pa.infrastructure.jobs.worker import (
    JobExecutionError,
    JobHandler,
    LeasedJob,
    WorkerRun,
    issue_worker_owner,
    run_worker,
)
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, job_for
from my_pa.infrastructure.persistence.tables import (
    DEFAULT_MAX_ATTEMPTS,
    JobState,
    capture_jobs,
    capture_proposals,
    capture_stage_results,
)

#: The note whose survival is the subject. Obviously synthetic, and carrying one
#: distinctive term so that "it is searchable" is a match on this note rather
#: than on whatever else a store might hold.
NOTE: Final = (
    "synthetic note alpha — quarterly widget review.\n"
    "I will send the flange tolerance summary by 2026-09-14.\n"
)

#: The term searched for. A word the note contains and the pipeline never
#: rewrites, because `capture.search` runs against the stored original.
TERM: Final = "flange"


def _explode(engine: Engine, job: LeasedJob, owner: str) -> None:
    """A handler that fails every attempt, classified rather than crashing.

    `JobExecutionError` rather than a bare `RuntimeError` so the recorded code is
    a chosen one and the assertion below is about what the pipeline reported, not
    about the catch-all. The unclassified path is already covered by
    `tests/jobs/test_capture_pipeline_recovery.py`.
    """
    raise JobExecutionError(ErrorCode.UNAVAILABLE)


def _save(runtime: GatewayRuntime, note: str, key: str, tag: str) -> dict[str, Any]:
    return succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=note, idempotency_key=key),
            tag,
        ),
        "capture.create",
    )


def _operation_id(engine: Engine, version_id: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(capture_jobs.c.operation_id).where(capture_jobs.c.version_id == version_id)
            ).scalar_one()
        )


def _drain(runtime: GatewayRuntime, *, handler: JobHandler, jobs: int) -> WorkerRun:
    """The real worker loop, on the real plane, with the handler this test chose."""
    return run_worker(
        runtime.work_engine,
        principal_id=runtime.principal.principal_id,
        owner=issue_worker_owner(),
        handler=handler,
        stop=threading.Event(),
        plane=CAPTURE_JOBS,
        max_iterations=jobs,
        poll_seconds=0.01,
    )


def _rows(engine: Engine, table: Table, version_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(table).where(table.c.version_id == version_id)
            ).scalar_one()
        )


@pytest.mark.database
@pytest.mark.recovery
def test_a_pipeline_that_fails_every_attempt_leaves_the_note_readable_and_searchable(
    runtime: GatewayRuntime,
) -> None:
    """The single most important claim in this package, reproduced rather than asserted."""
    engine = runtime.work_engine
    receipt = _save(runtime, NOTE, "enrichment-kill-0001", "kill")
    operation_id = _operation_id(engine, receipt["version_id"])

    # --- kill the enrichment, for good ----------------------------------------
    run = _drain(runtime, handler=_explode, jobs=DEFAULT_MAX_ATTEMPTS)
    assert run.released == DEFAULT_MAX_ATTEMPTS, (
        f"the pipeline did not fail every attempt: {run}. The kill has to be "
        "reproduced, not described"
    )
    assert run.completed == 0, "an attempt reported success while every one of them raised"

    # --- 1. the failure is visible, not swallowed -----------------------------
    with engine.connect() as connection:
        record = job_for(
            connection,
            operation_id,
            principal_id=runtime.principal.principal_id,
            plane=CAPTURE_JOBS,
        )
        spent = connection.execute(
            select(capture_jobs.c.last_error_code, capture_jobs.c.attempt_count).where(
                capture_jobs.c.operation_id == operation_id
            )
        ).one()
    assert record is not None and record.state is JobState.FAILED, (
        f"a job that failed its every attempt is in state {record.state if record else None}. "
        "A failure that leaves the queue looking healthy is a failure nobody will see"
    )
    assert spent.last_error_code == ErrorCode.UNAVAILABLE.value, (
        f"the job recorded {spent.last_error_code}, so the reported failure is not the "
        "one the handler declared"
    )
    assert spent.attempt_count == DEFAULT_MAX_ATTEMPTS

    # --- 2. nothing was enriched, which is what makes the rest a real question --
    assert _rows(engine, capture_proposals, receipt["version_id"]) == 0
    assert _rows(engine, capture_stage_results, receipt["version_id"]) == 0

    # --- 3. the note is still readable, through the capability, exactly ---------
    stored = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=receipt["capture_id"]),
            "read-after-kill",
        ),
        "capture.read",
    )
    assert stored["text"] == NOTE, (
        "the stored note is not what was written. The user's evidence must never be "
        "altered because a model or a job failed"
    )
    assert stored["content_sha256"] == receipt["content_sha256"], (
        "the digest the receipt acknowledged is not the digest of the stored text"
    )
    assert stored["version_id"] == receipt["version_id"]
    assert stored["is_current"] is True

    # --- 4. and still findable ------------------------------------------------
    found = succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_SEARCH,
            SearchCaptures(query=TERM),
            "search-after-kill",
        ),
        "capture.search",
    )
    assert [match["version_id"] for match in found["matches"]] == [receipt["version_id"]], (
        "the note stopped being searchable once its enrichment failed. Searchability "
        "is a property of the saved column, not of anything the pipeline writes, and "
        "a capture that a failed pipeline can hide is a capture the product lost"
    )

    # --- 5. the control: a clean run over an identical note does enrich ---------
    # Without it, "no proposals" above is satisfied by a pipeline that produces
    # none for this text at all, and the kill would be proving nothing.
    clean = _save(runtime, NOTE, "enrichment-kill-control", "control")
    assert _drain(runtime, handler=process_capture_version, jobs=1).completed == 1
    assert _rows(engine, capture_proposals, clean["version_id"]) >= 1, (
        "a clean run over the same note produced no proposal, so the zero asserted "
        "above says nothing about the kill"
    )
    # And the killed capture is still exactly where it was, untouched by the run
    # that succeeded beside it.
    assert _rows(engine, capture_proposals, receipt["version_id"]) == 0
