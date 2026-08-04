"""What a lost lease and a mid-transaction failure leave behind, narrowly.

Two criteria, and each is proved in its **narrow** form because `D-45`(e) records
that this campaign already shipped one property that passed its coarse test and
failed its narrow one.

**`QC-AC-035`(b), "a lost lease cannot commit".** The coarse test — kill the
worker mid-pipeline, assert no duplicate proposal — passes with `hold_lease`
deleted, because the transaction rolls back on the exception anyway. It proves
nothing about lease *ownership*. The narrow test steals the lease from a
**second connection** between stage *k* and stage *k+1*, then lets stage *k+1*
run, and asserts both halves: stage *k+1* wrote nothing, **and** stages 1…*k* are
still there. `D-55` is why the second half is not optional — "stage *k+1* wrote
nothing" is satisfied by a pipeline that wrote nothing at all, so without the
control the plant fails both ends of the bridge and distinguishes neither.

**`QC-AC-034`, "processing failure never loses the source capture".** The failure
is injected inside `P-15`'s transaction, **after** the proposal `INSERT` and
before the commit, because that is the only instant at which rows exist and are
not yet durable. A failure before the transaction risks nothing and a failure
after it risks nothing either. Five things are then asserted, including a control
— a clean run over the same fixture *does* produce proposals — because "no
proposals" is otherwise indistinguishable from "the pipeline is broken".

Every fixture is synthetic (`QC-AC-073`, `AGENTS.md` section 5); no source is
reached and no path is opened.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, Table, func, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from tests.pipeline.conftest import RICH_NOTE, drain, save

from my_pa.domain.capture.pipeline import PipelineStage
from my_pa.infrastructure.jobs import capture_pipeline
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, hold_lease, job_for
from my_pa.infrastructure.persistence.proposals import proposal_count
from my_pa.infrastructure.persistence.tables import (
    JobState,
    capture_jobs,
    capture_spans,
    capture_stage_results,
    capture_versions,
    captures,
)

pytestmark = [pytest.mark.database, pytest.mark.recovery]

#: The stage after which the lease is stolen. `P-09` rather than an earlier one,
#: so that **both** ends of the bridge are about rows: the stage that follows it
#: is `P-15`, which writes proposals, and the stages before it have written a
#: processing text, spans, classifications and mentions. Stealing after a stage
#: whose successor writes nothing would make "committed nothing" a claim about a
#: stage-result row and not about the work.
STOLEN_AFTER = PipelineStage.WORK_OBJECT_EXTRACTION

#: `restrict_violation`, as PostgreSQL's own `SQLSTATE`. Matched on the code
#: rather than on the message, because the message is prose the revision writes
#: and a reworded one would silently stop this assertion from meaning anything.
RESTRICT_VIOLATION = "23001"


def test_a_stage_that_lost_its_lease_commits_nothing_and_the_earlier_stages_remain(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The narrow proof, from a second connection that actually steals the lease.

    The steal happens **between** transactions and not inside one, and that is
    forced rather than convenient: `hold_lease` takes the job row `FOR UPDATE`,
    so a second connection updating it while a stage is open would block until
    that stage committed. The interposition is therefore on the *next* stage's
    `hold_lease` call — the earlier stage has committed, the next one's
    transaction has opened, and nothing holds the row yet.

    What reddens this if `hold_lease` goes: stage *k+1* is inside a transaction
    that nothing rolls back, so its rows commit under a lease another worker
    holds, and the first assertion fails while the second still passes.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)

    stolen = {"done": False}
    real_hold_lease = capture_pipeline.hold_lease

    def stealing_hold_lease(connection: Connection, operation_id: str, **kwargs: object) -> bool:
        if not stolen["done"] and _completed(engine, saved.version_id) > _index_of(STOLEN_AFTER):
            stolen["done"] = True
            with engine.begin() as thief:
                thief.execute(
                    capture_jobs.update()
                    .where(capture_jobs.c.operation_id == operation_id)
                    .values(lease_owner="worker-a-different-one")
                )
        return real_hold_lease(connection, operation_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(capture_pipeline, "hold_lease", stealing_hold_lease)
    run = drain(engine)
    assert stolen["done"], "the lease was never stolen, so this test measured a clean run"
    assert run.lost == 1, f"the worker did not report a lost lease: {run}"
    assert run.completed == 0, "a worker that lost its lease wrote `succeeded`"

    with engine.connect() as connection:
        reached = _stages(connection, saved.version_id)
        after = capture_pipeline.PIPELINE_ORDER[_index_of(STOLEN_AFTER) + 1]

        # --- End one: the stage that lost the lease committed nothing. ---
        assert after.value not in reached, (
            f"{after.value} recorded a result after its lease was taken by another "
            "worker. `hold_lease` is the first statement in that transaction "
            "precisely so it cannot"
        )
        assert proposal_count(connection, saved.version_id) == 0, (
            f"{after.value} committed proposals under a lease it no longer held"
        )

        # --- End two, which `D-55` makes mandatory: the pipeline was running. ---
        # Asserted as a *subset* rather than as an equality, deliberately. An
        # equality would fail for a build that ran too far as well as for one
        # that ran too little, so a plant that let the stolen stage write would
        # break both ends at once and distinguish neither. This end fails only
        # when the earlier stages are missing.
        expected = {
            stage.value for stage in capture_pipeline.PIPELINE_ORDER[: _index_of(STOLEN_AFTER) + 1]
        }
        assert expected <= reached, (
            f"stages 1..k are not all present: {sorted(reached)}. The end above is "
            "then satisfied by a pipeline that never ran"
        )
        assert _count(connection, capture_spans, saved.version_id) > 0, (
            "the surviving stages wrote no rows, so `committed nothing` distinguishes "
            "nothing from nothing"
        )


def test_a_failure_inside_proposal_persistence_leaves_the_capture_and_its_version_intact(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`QC-AC-034`, injected at the one instant where rows exist and are not durable.

    Five assertions and a control, and the control is what makes the third one a
    measurement: a second, clean run over the same fixture produces proposals, so
    "no proposal row" is the failure's doing rather than the pipeline's.

    The fifth is structural rather than behavioural. "Never loses the source
    capture" is a property of the schema — `capture_versions_are_append_only` is
    a `BEFORE UPDATE OR DELETE` trigger raising `restrict_violation` — and not of
    whichever code happened to be running when the failure arrived. Asserting it
    here is what stops the criterion resting on this pipeline's good behaviour.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
        before = connection.execute(
            select(capture_versions.c.content, capture_versions.c.content_sha256).where(
                capture_versions.c.version_id == saved.version_id
            )
        ).one()

    real_record_proposal = capture_pipeline.record_proposal

    def failing_record_proposal(connection: Connection, *args: object, **kwargs: object) -> str:
        # The insert happens, and *then* the attempt fails. A raise before it
        # would leave nothing at risk, which proves nothing.
        real_record_proposal(connection, *args, **kwargs)  # type: ignore[arg-type]
        raise RuntimeError("the attempt failed with the proposal inserted and not committed")

    monkeypatch.setattr(capture_pipeline, "record_proposal", failing_record_proposal)
    run = drain(engine)
    assert run.released == 1, f"the attempt did not end as a released failure: {run}"

    with engine.connect() as connection:
        # 1. The capture and its version are still there, and are unchanged.
        assert _count(connection, captures) == 1
        after = connection.execute(
            select(capture_versions.c.content, capture_versions.c.content_sha256).where(
                capture_versions.c.version_id == saved.version_id
            )
        ).one()
        assert after == before, "the failure path changed the stored version"
        assert after.content == RICH_NOTE

        # 2. No proposal survived the rollback.
        assert proposal_count(connection, saved.version_id) == 0

        # 3. The job is retryable, with a public error code, and attempts spent.
        record = job_for(connection, saved.operation_id, plane=CAPTURE_JOBS)
        assert record is not None and record.state is JobState.QUEUED
        code = connection.execute(
            select(capture_jobs.c.last_error_code, capture_jobs.c.attempt_count).where(
                capture_jobs.c.operation_id == saved.operation_id
            )
        ).one()
        assert code.last_error_code == "internal_error"
        assert code.attempt_count == 1

    # 4. The control. Without the injection the same fixture does produce
    # proposals, so the zero above is the failure's doing.
    monkeypatch.undo()
    assert drain(engine).completed == 1
    with engine.connect() as connection:
        assert proposal_count(connection, saved.version_id) >= 1, (
            "a clean run over the same fixture produced no proposal, so `no proposal "
            "row` above says nothing about the failure"
        )

    # 5. The schema's half: the version cannot be changed or removed at all.
    for statement in (
        capture_versions.update()
        .where(capture_versions.c.version_id == saved.version_id)
        .values(content="rewritten"),
        capture_versions.delete().where(capture_versions.c.version_id == saved.version_id),
    ):
        with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
            connection.execute(statement)
        assert refused.value.orig.sqlstate == RESTRICT_VIOLATION, (  # type: ignore[union-attr]
            "the refusal was not `restrict_violation`, so the version is protected by "
            f"something other than `capture_versions_are_append_only`: {refused.value}"
        )


def test_the_lease_check_is_what_refuses_the_write(engine: Engine) -> None:
    """The control on the mechanism the first test rests on.

    `hold_lease` returning `False` for a stolen lease is the whole of "a lost
    lease cannot commit"; a `hold_lease` that always answered `True` would leave
    the first test asserting that a pipeline stopped for some other reason. This
    asks it directly, both ways, in one test — the owner that holds the lease
    gets `True` and the one that does not gets `False`.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    with engine.begin() as connection:
        connection.execute(
            capture_jobs.update()
            .where(capture_jobs.c.operation_id == saved.operation_id)
            .values(
                state=JobState.RUNNING.value,
                lease_owner="worker-holds-the-lease",
                lease_expires_at=text("now() + interval '5 minutes'"),
            )
        )
    with engine.begin() as connection:
        assert (
            hold_lease(
                connection, saved.operation_id, owner="worker-holds-the-lease", plane=CAPTURE_JOBS
            )
            is True
        )
    with engine.begin() as connection:
        assert (
            hold_lease(
                connection, saved.operation_id, owner="worker-holds-it-not", plane=CAPTURE_JOBS
            )
            is False
        )


def _index_of(stage: PipelineStage) -> int:
    return capture_pipeline.PIPELINE_ORDER.index(stage)


def _stages(connection: Connection, version_id: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            select(capture_stage_results.c.stage).where(
                capture_stage_results.c.version_id == version_id
            )
        ).all()
    }


def _completed(engine: Engine, version_id: str) -> int:
    with engine.connect() as connection:
        return len(_stages(connection, version_id))


def _count(connection: Connection, table: Table, version_id: str | None = None) -> int:
    statement = select(func.count()).select_from(table)
    if version_id is not None:
        statement = statement.where(table.c.version_id == version_id)
    return int(connection.execute(statement).scalar_one())
