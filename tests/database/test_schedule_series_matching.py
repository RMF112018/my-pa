"""Schedule Scenarios S6-2: intake admission and the worker's series-match hook (14.8.6-7).

Publications are admitted through the real S5 repository and processed by the
real `process_schedule_publication` handler under `run_worker`, with the
provider and the contained parse replaced by the capability harness's seams.
An automatic import gets its own intake Series; finalization decides its
Series under the Project lock and records exactly one decision, admitting the
match in a savepoint only while the plane is effective. A deterministic hook
defect commits the finalization with no decision; a transient one propagates.

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

import functools
import hashlib
import threading
from collections.abc import Iterator
from datetime import date
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, text
from sqlalchemy.exc import OperationalError

from my_pa.contracts.ports import (
    ScenarioIntegrityError,
    ScheduleAdmissionRejectedError,
    SeriesMatchRecord,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule import (
    ScheduleAdmission,
    ScheduleAdmissionRefusal,
    ScheduleImportRequest,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    normalize_series_name,
    schedule_import_request_digest,
)
from my_pa.domain.schedule.plane import intake_series_name, second_admission_key
from my_pa.domain.schedule.series_match import MatchOutcome, MatchReason
from my_pa.infrastructure.jobs.schedule import process_schedule_publication
from my_pa.infrastructure.jobs.schedule_parser_process import ParsedResult
from my_pa.infrastructure.jobs.worker import WorkerRun, run_worker
from my_pa.infrastructure.persistence import schedule as s5_module
from my_pa.infrastructure.persistence import schedule_scenarios as plane_module
from my_pa.infrastructure.persistence.jobs import SCHEDULE_JOBS, claim_job, release_job
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_scenarios import SqlAlchemyScenarioUnitOfWork
from tests.database.schedule_capability_harness import (
    OWNER,
    Activity,
    ScheduleRuntime,
    World,
    build_result,
)
from tests.database.schedule_plane_world import (
    count_rows,
    disposed_lease_engines,  # noqa: F401 - an autouse fixture
    seed_publication,
)

pytestmark = pytest.mark.database

P: Final = "prn_s62match001"
ACTIVITIES: Final = tuple(Activity(f"A-{n:03d}", name=f"Activity {n}") for n in range(1, 26))
MASTER_DATE: Final = date(2026, 5, 4)
LATER: Final = date(2026, 5, 11)


@pytest.fixture
def rt(cloned_database_url: str) -> Iterator[ScheduleRuntime]:
    runtime = ScheduleRuntime(cloned_database_url)
    try:
        yield runtime
    finally:
        runtime.close()


@pytest.fixture
def world(rt: ScheduleRuntime) -> World:
    return rt.world(P, "s62ma")


_COUNTER = {"n": 0}


def _register(
    rt: ScheduleRuntime,
    world: World,
    activities: tuple[Activity, ...],
    data_date: date,
    outcome: SchedulePublicationStatus = SchedulePublicationStatus.COMPLETE,
) -> tuple[str, str]:
    object_id, version_id = rt.source_object(world)
    data = rt.objects[object_id][1]
    rt.results[hashlib.sha256(data).hexdigest()] = ParsedResult(
        build_result(data, activities, data_date=data_date, outcome=outcome)
    )
    return object_id, version_id


def _request(
    world: World,
    object_id: str,
    version_id: str,
    *,
    auto: bool = False,
    series_name: str | None = None,
    series_id: str | None = None,
    if_new: str | None = None,
) -> ScheduleImportRequest:
    _COUNTER["n"] += 1
    return ScheduleImportRequest(
        project_id=world.project,
        series_id=series_id,
        series_name=None if series_name is None else normalize_series_name(series_name),
        enrollment_id=world.enrollment,
        source_object_id=object_id,
        source_version_id=version_id,
        publication_role=SchedulePublicationRole.UPDATE,
        baseline_kind=None,
        expected_data_date=None,
        supersedes_publication_id=None,
        idempotency_key=f"match-import-{_COUNTER['n']:05d}",
        series_auto=auto,
        series_name_if_new=None if if_new is None else normalize_series_name(if_new),
    )


def _admit(engine: Engine, principal: str, request: ScheduleImportRequest) -> ScheduleAdmission:
    digest = schedule_import_request_digest(principal, request)
    with SqlAlchemyScheduleUnitOfWork(engine) as uow:
        return uow.schedules.admit_publication(principal, request, digest)


def _process(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World, *, plane: bool
) -> WorkerRun:
    rt.serve(monkeypatch, world)
    return run_worker(
        rt.engine,
        owner=OWNER,
        handler=functools.partial(process_schedule_publication, scenario_plane_effective=plane),
        stop=threading.Event(),
        principal_id=world.principal,
        plane=SCHEDULE_JOBS,
        max_iterations=1,
        lease_seconds=300,
    )


def _master(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> ScheduleAdmission:
    object_id, version_id = _register(rt, world, ACTIVITIES, MASTER_DATE)
    admitted = _admit(
        rt.engine, world.principal, _request(world, object_id, version_id, series_name="Master")
    )
    assert _process(rt, monkeypatch, world, plane=False).completed == 1
    return admitted


def _auto(
    rt: ScheduleRuntime,
    world: World,
    *,
    activities: tuple[Activity, ...] = ACTIVITIES,
    data_date: date = LATER,
    if_new: str | None = None,
    outcome: SchedulePublicationStatus = SchedulePublicationStatus.COMPLETE,
    object_and_version: tuple[str, str] | None = None,
) -> ScheduleAdmission:
    object_id, version_id = object_and_version or _register(
        rt, world, activities, data_date, outcome
    )
    return _admit(
        rt.engine, world.principal, _request(world, object_id, version_id, auto=True, if_new=if_new)
    )


def _decision(rt: ScheduleRuntime, publication_id: str) -> SeriesMatchRecord | None:
    with SqlAlchemyScenarioUnitOfWork(rt.engine) as uow:
        return uow.scenarios.get_match_decision(P, publication_id)


def _status(rt: ScheduleRuntime, publication_id: str) -> str:
    return str(
        rt.scalar(
            "SELECT status FROM knowledge.schedule_publications WHERE publication_id = :p",
            p=publication_id,
        )
    )


def _series_publications(rt: ScheduleRuntime, series_id: str) -> int:
    return int(
        rt.scalar(
            "SELECT count(*) FROM knowledge.schedule_publications WHERE series_id = :s", s=series_id
        )
    )


# ---- intake admission (section 14.8.6) -------------------------------------------------


def test_each_auto_import_gets_its_own_intake_series(rt: ScheduleRuntime, world: World) -> None:
    """P39: no two automatic imports share a Series; an intake Series is never named explicitly."""
    first = _auto(rt, world)
    second = _auto(rt, world)
    assert first.series.series_id != second.series.series_id
    for admission in (first, second):
        assert admission.series_created
        expected = intake_series_name(admission.publication.request_digest)
        assert (admission.series.name, admission.series.name_key) == (expected.name, expected.key)
    assert count_rows(rt.engine, "schedule_intake_series") == 2
    object_id, version_id = _register(rt, world, ACTIVITIES, LATER)
    for request in (
        _request(world, object_id, version_id, series_id=first.series.series_id),
        _request(world, object_id, version_id, series_name=first.series.name),
    ):
        with pytest.raises(ScheduleAdmissionRejectedError) as refused:
            _admit(rt.engine, P, request)
        assert refused.value.reason is ScheduleAdmissionRefusal.SERIES_NOT_FOUND
    replay = _auto(
        rt,
        world,
        object_and_version=(
            first.publication.source_object_id,
            first.publication.source_version_id,
        ),
    )
    assert replay.publication.publication_id == first.publication.publication_id


def test_explicit_series_never_matches(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """P29: an explicit Series wins; the matcher is never consulted and nothing is decided."""
    _master(rt, monkeypatch, world)
    object_id, version_id = _register(rt, world, ACTIVITIES, LATER)
    explicit = _admit(rt.engine, P, _request(world, object_id, version_id, series_name="Other"))
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    assert _status(rt, explicit.publication.publication_id) == "complete"
    assert (
        explicit.series.name == "Other" and _series_publications(rt, explicit.series.series_id) == 1
    )
    assert count_rows(rt.engine, "schedule_intake_series") == 0
    assert count_rows(rt.engine, "schedule_series_match_decisions") == 0


# ---- the hook (section 14.8.7) ---------------------------------------------------------


def test_auto_import_records_a_match_decision(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    master = _master(rt, monkeypatch, world)
    intake = _auto(rt, world)
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    decision = _decision(rt, intake.publication.publication_id)
    assert decision is not None
    assert (decision.outcome, decision.reason, decision.incoming_id_count) == (
        MatchOutcome.MATCHED,
        None,
        25,
    )
    assert decision.target_series_id == master.series.series_id
    assert [(item.series_id, item.score) for item in decision.candidates] == [
        (master.series.series_id, 1000)
    ]
    resulting = decision.resulting_publication_id
    assert resulting is not None and _status(rt, resulting) == "queued"
    with rt.engine.connect() as connection:
        key, series = connection.execute(
            text(
                "SELECT idempotency_key, series_id FROM knowledge.schedule_publications "
                "WHERE publication_id = :p"
            ),
            {"p": resulting},
        ).one()
    assert (key, series) == (second_admission_key(decision.decision_id), master.series.series_id)
    assert _status(rt, intake.publication.publication_id) == "complete"
    # The second admission is an ordinary update: its own job parses it.
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    assert _status(rt, resulting) == "complete"
    assert _decision(rt, resulting) is None


def test_plane_off_records_the_decision_without_admitting(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """S6-O15 / S6-2-D12: the decision is evidence only; nothing is admitted."""
    master = _master(rt, monkeypatch, world)
    intake = _auto(rt, world)
    assert _process(rt, monkeypatch, world, plane=False).completed == 1
    decision = _decision(rt, intake.publication.publication_id)
    assert decision is not None
    assert (decision.outcome, decision.admission_skipped) == (
        MatchOutcome.MATCHED,
        "plane_disabled",
    )
    assert (decision.target_series_id, decision.resulting_publication_id) == (
        master.series.series_id,
        None,
    )
    assert _series_publications(rt, master.series.series_id) == 1
    assert count_rows(rt.engine, "schedule_publications") == 2


def test_every_other_outcome_is_recorded(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """`needs_series`, `created`, `not_eligible` and `already_present`, each recorded once."""
    unnamed = _auto(rt, world)
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    needs = _decision(rt, unnamed.publication.publication_id)
    assert needs is not None and needs.outcome is MatchOutcome.NEEDS_SERIES
    named = _auto(rt, world, if_new="Phase Two")
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    created = _decision(rt, named.publication.publication_id)
    assert created is not None and created.outcome is MatchOutcome.CREATED
    assert created.target_series_id is not None and created.resulting_publication_id is not None
    assert (
        rt.scalar(
            "SELECT name FROM knowledge.schedule_series WHERE series_id = :s",
            s=created.target_series_id,
        )
        == "Phase Two"
    )
    assert _process(rt, monkeypatch, world, plane=True).completed == 1  # the created one parses
    review = _auto(rt, world, outcome=SchedulePublicationStatus.REVIEW_REQUIRED)
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    not_eligible = _decision(rt, review.publication.publication_id)
    assert not_eligible is not None and not_eligible.outcome is MatchOutcome.NOT_ELIGIBLE
    # The same source version auto-imported again: the matched Series already holds it.
    present = _auto(
        rt,
        world,
        object_and_version=(
            named.publication.source_object_id,
            named.publication.source_version_id,
        ),
    )
    assert present.series.series_id != named.series.series_id  # a new intake Series (new key)
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    already = _decision(rt, present.publication.publication_id)
    assert already is not None and already.outcome is MatchOutcome.ALREADY_PRESENT
    assert already.resulting_publication_id == created.resulting_publication_id


def test_match_admission_refusal_is_recorded_not_raised(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """P40: a refused second admission rolls back only its savepoint; finalization commits."""
    master = _master(rt, monkeypatch, world)
    intake = _auto(rt, world)
    original = s5_module.SqlScheduleRepository.admit_publication

    def refusing(
        self: s5_module.SqlScheduleRepository,
        principal_id: str,
        request: ScheduleImportRequest,
        digest: str,
        **options: str | None,
    ) -> ScheduleAdmission:
        admitted = original(self, principal_id, request, digest, **options)
        if request.match_decision_id is not None:  # written, then refused: the savepoint undoes it
            raise ScheduleAdmissionRejectedError(ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT)
        return admitted

    monkeypatch.setattr(s5_module.SqlScheduleRepository, "admit_publication", refusing)
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    decision = _decision(rt, intake.publication.publication_id)
    assert decision is not None
    assert (decision.outcome, decision.admission_refusal, decision.resulting_publication_id) == (
        MatchOutcome.ADMISSION_REFUSED,
        "source_version_conflict",
        None,
    )
    assert decision.target_series_id == master.series.series_id
    assert _series_publications(rt, master.series.series_id) == 1
    assert _status(rt, intake.publication.publication_id) == "complete"
    assert count_rows(rt.engine, "schedule_jobs") == 2


def _seed_series(rt: ScheduleRuntime, world: World, count: int, *, without_eligible: int) -> None:
    with rt.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        for index in range(count):
            series = f"sser_s62many{index:04d}"
            c.execute(
                text(
                    "INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, "
                    "name, name_key) VALUES (:s, :p, :j, :n, lower(:n))"
                ),
                {"s": series, "p": P, "j": world.project, "n": f"Series {index:04d}"},
            )
            status = "queued" if index < without_eligible else "complete"
            seed_publication(c, P, f"spub_s62many{index:04d}", series, world.project, status, 0)


@pytest.mark.parametrize("without_eligible", [0, 3], ids=["all_eligible", "three_without"])
def test_more_than_fifty_series_is_candidate_bound(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World, without_eligible: int
) -> None:
    """R9-F07: 51 non-intake Series (raw) -> `candidate_bound`, read with `LIMIT 51`, unscored."""
    _seed_series(rt, world, 51, without_eligible=without_eligible)
    intake = _auto(rt, world)
    statements: list[tuple[str, Any]] = []

    def capture(_conn: Any, _cursor: Any, statement: str, parameters: Any, *_: Any) -> None:  # noqa: ANN401
        statements.append((statement, parameters))

    event.listen(rt.engine, "before_cursor_execute", capture)
    try:
        assert _process(rt, monkeypatch, world, plane=True).completed == 1
    finally:
        event.remove(rt.engine, "before_cursor_execute", capture)
    decision = _decision(rt, intake.publication.publication_id)
    assert decision is not None
    assert (decision.outcome, decision.reason, decision.candidates, decision.incoming_id_count) == (
        MatchOutcome.AMBIGUOUS,
        MatchReason.CANDIDATE_BOUND,
        (),
        25,
    )
    bounded = [
        parameters
        for statement, parameters in statements
        if "FROM knowledge.schedule_series" in statement and "LIMIT" in statement
    ]
    assert bounded and all(51 in dict(parameters).values() for parameters in bounded), bounded


def _defect(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if kind == "integrity_error":  # the decision insert breaks its candidates CHECK
        monkeypatch.setattr(plane_module, "_candidate_object", lambda _c: {"pad": "x" * 70_000})
    elif kind == "data_error":  # jsonb refuses a NUL escape (SQLSTATE 22P05)
        monkeypatch.setattr(plane_module, "_candidate_object", lambda _c: {"bad": "\u0000"})
    else:
        error: Exception = (
            ValueError("seam") if kind == "value_error" else ScenarioIntegrityError("seam")
        )

        def seam(stage: str) -> None:
            if stage == "decision":
                raise error

        monkeypatch.setattr(plane_module, "_seam", seam)


@pytest.mark.parametrize(
    "kind", ["integrity_error", "scenario_integrity_error", "value_error", "data_error"]
)
def test_hook_defect_commits_finalization_without_a_decision(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World, kind: str
) -> None:
    """R9-F01 / RR1-F01: a deterministic hook defect never fails a parsed publication."""
    _master(rt, monkeypatch, world)
    intake = _auto(rt, world)
    _defect(kind, monkeypatch)
    ran = _process(rt, monkeypatch, world, plane=False)
    assert ran.completed == 1, ran
    assert _status(rt, intake.publication.publication_id) == "complete"
    assert _decision(rt, intake.publication.publication_id) is None
    assert (
        rt.scalar(
            "SELECT state FROM knowledge.schedule_jobs WHERE publication_id = :p",
            p=intake.publication.publication_id,
        )
        == "succeeded"
    )


def test_transient_hook_error_still_propagates(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """RR1-F01: a transient error rolls the whole finalization back and releases the attempt."""
    _master(rt, monkeypatch, world)
    intake = _auto(rt, world)

    def seam(stage: str) -> None:
        if stage == "decision":
            raise OperationalError("SELECT 1", {}, RuntimeError("canceling statement"))

    monkeypatch.setattr(plane_module, "_seam", seam)
    ran = _process(rt, monkeypatch, world, plane=False)
    assert ran.completed == 0, ran
    assert _status(rt, intake.publication.publication_id) == "processing"
    assert _decision(rt, intake.publication.publication_id) is None
    with rt.engine.connect() as connection:
        state, attempts, error = connection.execute(
            text(
                "SELECT state, attempt_count, last_error_code FROM knowledge.schedule_jobs "
                "WHERE publication_id = :p"
            ),
            {"p": intake.publication.publication_id},
        ).one()
    assert (state, attempts, error) == ("queued", 1, ErrorCode.INTERNAL_ERROR.value)


def test_exhausted_intake_job_has_no_decision_and_breaks_nothing(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """S6-2-U09: the job dead-letters before H8; the operator imports the file explicitly."""
    intake = _auto(rt, world)
    for _ in range(3):
        with rt.engine.begin() as c:
            leased = claim_job(
                c, owner=OWNER, lease_seconds=300, principal_id=P, plane=SCHEDULE_JOBS
            )
        assert leased is not None
        with rt.engine.begin() as c:
            release_job(
                c,
                leased.operation_id,
                owner=OWNER,
                error_code=ErrorCode.UNAVAILABLE,
                plane=SCHEDULE_JOBS,
            )
    with SqlAlchemyScheduleUnitOfWork(rt.engine) as uow:
        assert uow.schedules.get_effective_status(P, intake.publication.publication_id) is (
            SchedulePublicationStatus.FAILED
        )
    assert _decision(rt, intake.publication.publication_id) is None
    explicit = _admit(
        rt.engine,
        P,
        _request(
            world,
            intake.publication.source_object_id,
            intake.publication.source_version_id,
            series_name="Recovered",
        ),
    )
    assert explicit.series_created
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    assert _status(rt, explicit.publication.publication_id) == "complete"


def test_created_never_joins_a_series_created_after_the_free_read(
    rt: ScheduleRuntime, monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    """R9-F02: a same-named Series committed after the `FREE` read is never joined."""
    intake = _auto(rt, world, if_new="Phase Two")
    object_id, version_id = _register(rt, world, ACTIVITIES[:5], LATER)
    operators: dict[str, ScheduleAdmission] = {}

    def seam(stage: str) -> None:
        if stage == "new_series_name_read" and not operators:
            # The S5 explicit import takes no Project lock: it commits in between.
            operators["series"] = _admit(
                rt.engine, P, _request(world, object_id, version_id, series_name="Phase Two")
            )

    monkeypatch.setattr(plane_module, "_seam", seam)
    assert _process(rt, monkeypatch, world, plane=True).completed == 1
    decision = _decision(rt, intake.publication.publication_id)
    assert decision is not None
    assert (decision.outcome, decision.reason) == (
        MatchOutcome.AMBIGUOUS,
        MatchReason.NAME_CONFLICT,
    )
    assert (decision.target_series_id, decision.resulting_publication_id) == (None, None)
    operator_series = operators["series"].series.series_id
    assert _series_publications(rt, operator_series) == 1
    assert _status(rt, intake.publication.publication_id) == "complete"
