"""`QC-AC-035`(a): replaying a completed stage returns the prior output.

**This module discharges a condition rather than restating a design.**
`capture_stage_results` deliberately stores no output blob — a stored blob would
make "returns the prior output" a comparison of one stored value against another,
which passes whenever the two were written together, including when both are
wrong. That is the same argument `capture_spans` makes for not storing
`quoted_text`. What it costs is that the criterion is no longer true by
construction: it holds **only if** every stage is deterministically re-derivable
from the immutable version plus the recorded pipeline version.

So it is proved, per stage, for all nine — and the comparison is shown to be able
to fail. `test_a_stage_that_reads_the_clock_stops_replaying` plants a derivation
that reads something the version does not carry and watches the same comparison
report a mismatch, which is what makes the nine agreements a measurement.

`11_…:212` also requires that a *changed* pipeline or configuration create a new
attempt rather than silently overwriting. That is the control on the idempotency
key: without it, "no second row was written" would be satisfied by a pipeline
that never runs twice at all.

Synthetic fixtures throughout (`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, Table, func, select
from sqlalchemy.engine import Connection
from tests.pipeline.conftest import RICH_NOTE, drain, save

from my_pa.domain.capture.pipeline import PipelineStage, stage_config_digest, stage_identity
from my_pa.infrastructure.jobs import capture_pipeline
from my_pa.infrastructure.jobs.capture_pipeline import PIPELINE_ORDER, replay_stage
from my_pa.infrastructure.persistence.proposals import record_stage_result, stage_result_for
from my_pa.infrastructure.persistence.tables import (
    capture_jobs,
    capture_proposals,
    capture_stage_results,
)

pytestmark = [pytest.mark.database, pytest.mark.recovery]


def test_every_stage_replays_to_the_digest_it_stored(engine: Engine) -> None:
    """All nine, re-derived from the version and compared against what was stored.

    The assertion is on a non-empty set of stages *and* on each comparison: a
    loop over an empty `PIPELINE_ORDER` would agree with every claim below, and a
    stage that recorded no digest is refused by `replay_stage` rather than
    skipped.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    run = drain(engine)
    assert run.completed == 1, f"the pipeline did not complete: {run}"

    assert len(PIPELINE_ORDER) == 9, "the nine stages are what this test is about"
    compared: list[PipelineStage] = []
    with engine.connect() as connection:
        for stage in PIPELINE_ORDER:
            stored, rederived = replay_stage(connection, version_id=saved.version_id, stage=stage)
            assert stored == rederived, (
                f"{stage.value} stored {stored} and re-derives to {rederived}. With no "
                "output blob, `a completed stage returns the prior output` is only true "
                "while the stage is a function of the immutable version and the recorded "
                "pipeline version; this one reads something else"
            )
            compared.append(stage)
    assert compared == list(PIPELINE_ORDER)


def test_a_stage_that_reads_the_clock_stops_replaying(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The plant: the comparison above can fail, so its nine agreements mean something.

    A derivation that mixes in a value the version does not carry is exactly the
    defect the replay proof exists to catch — a stage that looks correct, is
    useful, and answers differently tomorrow for the same immutable text. Here it
    is `P-03`'s language digest, chosen because it is the cheapest to displace
    and because nothing else depends on its value.

    **The control is in the same test**: every *other* stage still replays. A
    plant that reddened all nine would prove the comparison is sensitive to
    something, not that it is sensitive to this.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    assert drain(engine).completed == 1

    monkeypatch.setattr(
        capture_pipeline,
        "_language_digest",
        lambda derivation: stage_config_digest(derivation.language, "a-value-the-version-lacks"),
    )
    with engine.connect() as connection:
        stored, rederived = replay_stage(
            connection, version_id=saved.version_id, stage=PipelineStage.DETECT_LANGUAGE
        )
        assert stored != rederived, (
            "a derivation reading a value outside the version replayed to the same "
            "digest, so the comparison in the test above cannot distinguish anything"
        )

        surviving = [
            stage
            for stage in PIPELINE_ORDER
            if stage is not PipelineStage.DETECT_LANGUAGE
            and (lambda pair: pair[0] == pair[1])(
                replay_stage(connection, version_id=saved.version_id, stage=stage)
            )
        ]
        assert len(surviving) == len(PIPELINE_ORDER) - 1, (
            "the plant reddened stages it did not displace, so it isolates nothing"
        )


def test_replaying_a_completed_stage_writes_no_second_proposal(engine: Engine) -> None:
    """The same job run twice writes one set of rows, and reads the first back.

    The worker is driven a second time over the same version after the job is
    returned to `queued`, which is what a released attempt or a re-enqueue would
    do. `record_stage_result`'s `ON CONFLICT DO NOTHING` against
    `a_stage_key_admits_one_result` is what makes the second run read rather than
    write, and `_run_stage` is what makes it skip the persistence beside it.

    **The control is `11_…:212`'s other half**, in this test: a stage recorded
    under a *different* pipeline version does create a new attempt. Without it,
    "no second row" is satisfied by a pipeline that never ran twice.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    assert drain(engine).completed == 1

    with engine.connect() as connection:
        stages = _count(connection, capture_stage_results, saved.version_id)
        proposals = _count(connection, capture_proposals, saved.version_id)
    assert stages == len(PIPELINE_ORDER)
    assert proposals >= 1, "the fixture produced no proposal, so a duplicate could not show"

    with engine.begin() as connection:
        # Return the job to the queue, which is what a released attempt or a
        # re-enqueue leaves behind. The claim, the lease, and the completion are
        # then the real ones on the second pass too.
        connection.execute(
            capture_jobs.update().values(state="queued", lease_owner=None, lease_expires_at=None)
        )
    assert drain(engine).completed == 1

    with engine.connect() as connection:
        assert _count(connection, capture_stage_results, saved.version_id) == stages
        assert _count(connection, capture_proposals, saved.version_id) == proposals

        # The control: a different pipeline version is a different key, so it is
        # a new attempt rather than a replay.
        prior = stage_result_for(
            connection,
            capture_pipeline._stage_key(
                saved.version_id,
                PipelineStage.VALIDATE,
                capture_pipeline._stage_config(PipelineStage.VALIDATE),
            ),
        )
        assert prior is not None and prior.created is False

    config = capture_pipeline._stage_config(PipelineStage.VALIDATE)
    later = stage_identity(
        version_id=saved.version_id,
        stage=PipelineStage.VALIDATE,
        pipeline_version="capture-pipeline-v2",
        stage_config_hash=config,
    )
    assert later != capture_pipeline._stage_key(saved.version_id, PipelineStage.VALIDATE, config), (
        "changing the pipeline version did not change the replay key, so a new "
        "pipeline would silently replay the old one's results"
    )
    with engine.begin() as connection:
        outcome = record_stage_result(
            connection,
            version_id=saved.version_id,
            operation_id=saved.operation_id,
            stage=PipelineStage.VALIDATE,
            pipeline_version="capture-pipeline-v2",
            stage_config_sha256=config,
            idempotency_key=later,
            processing_state=prior.processing_state,
        )
        assert outcome.created is True, (
            "a stage under a different pipeline version did not create a new attempt, "
            "so the replay assertions above are satisfied by a key nothing can vary"
        )
        assert _count(connection, capture_stage_results, saved.version_id) == stages + 1


def _count(connection: Connection, table: Table, version_id: str) -> int:
    return int(
        connection.execute(
            select(func.count()).select_from(table).where(table.c.version_id == version_id)
        ).scalar_one()
    )
