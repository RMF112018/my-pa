"""Schedule Scenarios S6-2: the plane repository and unit of work (contract section 14.8).

Every test drives `SqlAlchemyScenarioUnitOfWork` (and `compute_and_store_cpm_run`)
against a synthetic head clone: the idempotency ledger and its replay and
conflict answers, the CAS version append, Scenarios from a publication and by
fork, CPM runs under the two-layer compute lease with the natural-key insert,
outputs, digests verified on read, the bound reads, and the Principal
partition. Race tests synchronize on a seam plus an observed advisory-lock
wait or a barrier, never on a sleep (R9-F03).

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import threading
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.contracts.ports import (
    BaselineWriteRefusedError,
    CpmComputeBusyError,
    NewScenario,
    NewScenarioOutput,
    NewScenarioVersion,
    PlaneReservationOutcome,
    PlaneSubjectAbsentError,
    ScenarioHeadMovedError,
    ScenarioIntegrityError,
    ScenarioRepository,
)
from my_pa.domain.schedule import ScheduleImportApproval
from my_pa.domain.schedule.baselines import ApproveRequest, BaselineRefusal, BaselineType
from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.plane import PlaneProvenance
from my_pa.domain.schedule.scenario.canonical import (
    CONTENT_SCHEMA,
    OUTPUT_SCHEMA,
    content_object,
    output_payload_sha256,
)
from my_pa.domain.schedule.scenario.changeset import ApplicationReport
from my_pa.domain.schedule.scenario.cpm import ENGINE_VERSION, CpmResult, CpmStatus, run_cpm
from my_pa.domain.schedule.scenario.model import ScenarioContent, VersionLabel
from my_pa.domain.schedule.scenario.outputs import OutputKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import schedule_cpm_lease as lease_module
from my_pa.infrastructure.persistence.schedule_cpm_lease import (
    SCHEDULE_CPM_ADVISORY_NAMESPACE,
    compute_and_store_cpm_run,
)
from my_pa.infrastructure.persistence.schedule_plane_codec import compress_canonical
from my_pa.infrastructure.persistence.schedule_scenarios import (
    SqlAlchemyScenarioUnitOfWork,
    new_scenario_version,
)
from tests.database.schedule_plane_world import (
    CONTENT,
    OPERATOR,
    Interleaving,
    PlaneWorld,
    client,
    count_rows,
    disposed_lease_engines,  # noqa: F401 - an autouse fixture
    first_version,
    seed_world,
)
from tests.fixtures.schedule_scenario import link, network, task

pytestmark = pytest.mark.database

P: Final = "prn_s62pers0001"
Q: Final = "prn_s62pers0002"
CLIENT: Final = client("client-7")
SCENARIOS: Final = "schedule_scenarios.create"
VERSIONS: Final = "schedule_scenario_versions.create"
RUNS: Final = "schedule_cpm_runs.create"
OUTPUTS: Final = "schedule_scenario_outputs.record"
SECOND: Final = network(
    [task("A", 480), task("B", 960), task("C", 240)], [link("A", "B"), link("B", "C")]
)
OPS: Final = [{"op": "add_activity", "key": "x:C"}]


@pytest.fixture
def w(db_engine: Engine) -> PlaneWorld:
    return seed_world(db_engine, P, "s62pa")


@pytest.fixture
def other(db_engine: Engine) -> PlaneWorld:
    return seed_world(db_engine, Q, "s62pb")


def _digest(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode()).hexdigest()


def _write(
    engine: Engine,
    capability: str,
    key: str,
    action: Callable[[ScenarioRepository], Any],
    *,
    principal: str = P,
    writer: PlaneProvenance = CLIENT,
    digest: str | None = None,
    stored: Callable[[Any], int] = lambda _result: 0,
) -> tuple[PlaneReservationOutcome, Any]:
    """One plane write transaction: P, the reservation, the write, the completion."""
    with SqlAlchemyScenarioUnitOfWork(engine) as uow:
        repo = uow.scenarios
        repo.lock_principal(principal)
        reservation = repo.reserve_request(
            principal, capability, key, digest or _digest(capability, key), writer
        )
        if reservation.outcome is not PlaneReservationOutcome.RESERVED:
            return reservation.outcome, reservation
        result = action(repo)
        result_id = getattr(
            result, {SCENARIOS: "scenario_id", OUTPUTS: "output_id"}.get(capability, "version_id")
        )
        repo.complete_request(
            principal, capability, key, result_id, created=True, stored_bytes=stored(result)
        )
        return reservation.outcome, result


def _scenario(
    engine: Engine,
    w: PlaneWorld,
    key: str = "scenario-key-0001",
    *,
    content: ScenarioContent = CONTENT,
) -> Any:  # noqa: ANN401 - StoredScenarioVersion
    return _write(
        engine,
        SCENARIOS,
        key,
        lambda repo: repo.insert_scenario(
            P,
            NewScenario(name="What if", origin_publication_id=w.publications[0]),
            first_version(content),
            CLIENT,
        ),
        stored=lambda version: version.content_size_bytes,
    )[1]


def _second(head_no: int = 1) -> Any:  # noqa: ANN401 - NewScenarioVersion
    del head_no
    return new_scenario_version(
        SECOND,
        label=VersionLabel.UPDATE,
        ops=OPS,
        applied=ApplicationReport(ops_applied=1, relationships_removed=0, content_changed=True),
    )


def _append(engine: Engine, scenario_id: str, expected: int, key: str) -> Any:  # noqa: ANN401
    return _write(
        engine,
        VERSIONS,
        key,
        lambda repo: repo.append_version(P, scenario_id, expected, _second(), CLIENT),
    )[1]


def _ledger(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(
                    "SELECT capability, idempotency_key, completed_at IS NOT NULL, result_kind "
                    "FROM knowledge.schedule_scenario_write_requests ORDER BY 1, 2"
                )
            )
        ]


# ---- scenarios, versions and forks ---------------------------------------------------


def test_scenarios_versions_and_forks_round_trip(db_engine: Engine, w: PlaneWorld) -> None:
    v1 = _scenario(db_engine, w)
    assert (v1.version_no, v1.parent_version_id, v1.snapshot) == (1, None, first_version().snapshot)
    v2 = _append(db_engine, v1.scenario_id, 1, "version-key-0001")
    assert (v2.version_no, v2.parent_version_id, v2.content_changed) == (2, v1.version_id, True)
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        repo = uow.scenarios
        scenario = repo.get_scenario(P, v1.scenario_id)
        assert scenario is not None
        assert (scenario.origin_kind, scenario.origin_publication_id) == (
            "publication",
            w.publications[0],
        )
        assert repo.head_version(P, v1.scenario_id) == v2
        assert repo.version_by_number(P, v1.scenario_id, 1) == v1
        loaded = repo.load_content(P, v2.version_id)
        assert loaded is not None and loaded.content == SECOND
        change = repo.load_change_set(P, v2.version_id)
        assert change is not None and change.document["ops"] == OPS
        assert repo.load_change_set(P, v1.version_id) is None
    fork = _write(
        db_engine,
        SCENARIOS,
        "fork-key-0001",
        lambda repo: repo.fork_scenario(
            P, NewScenario(name="Forked"), v2.version_id, VersionLabel.WHAT_IF, "a note", CLIENT
        ),
    )[1]
    assert (fork.version_no, fork.snapshot, fork.content_sha256) == (1, None, v2.content_sha256)
    assert fork.series_id == v2.series_id and fork.note == "a note"
    with db_engine.connect() as connection:
        copied, source = connection.execute(
            text(
                "SELECT (SELECT content_zlib FROM knowledge.schedule_scenario_versions WHERE "
                "version_id = :f), (SELECT content_zlib FROM "
                "knowledge.schedule_scenario_versions WHERE version_id = :s)"
            ),
            {"f": fork.version_id, "s": v2.version_id},
        ).one()
    assert bytes(copied) == bytes(source)  # byte for byte, never re-compressed


def test_version_append_is_cas_guarded(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """Two appends naming head 1: one is version 2, the other is refused `head moved`."""
    v1 = _scenario(db_engine, w)
    race = Interleaving.install(monkeypatch, db_engine, "head_read")

    def append(key: str) -> Callable[[SqlAlchemyScenarioUnitOfWork], object]:
        def action(uow: SqlAlchemyScenarioUnitOfWork) -> object:
            repo = uow.scenarios
            repo.lock_principal(P)
            repo.reserve_request(P, VERSIONS, key, _digest(key), CLIENT)
            stored = repo.append_version(P, v1.scenario_id, 1, _second(), CLIENT)
            repo.complete_request(P, VERSIONS, key, stored.version_id, created=True, stored_bytes=0)
            return stored

        return action

    first, second = race.run(append("cas-key-0001"), append("cas-key-0002"))
    assert first[0] == "ok", first
    assert second[0] == "error" and isinstance(second[1], ScenarioHeadMovedError), second
    assert second[1].head_version_no == 2
    with db_engine.connect() as connection:
        numbers = connection.execute(
            text(
                "SELECT version_no FROM knowledge.schedule_scenario_versions WHERE scenario_id = "
                ":s ORDER BY 1"
            ),
            {"s": v1.scenario_id},
        ).scalars()
        assert list(numbers) == [1, 2]
    assert ("schedule_scenario_versions.create", "cas-key-0002", True, "version") not in _ledger(
        db_engine
    )


# ---- the idempotency ledger (section 6.3) ------------------------------------------------


def test_same_key_same_request_replays(db_engine: Engine, w: PlaneWorld) -> None:
    v1 = _scenario(db_engine, w, "scenario-key-0001")
    outcome, reservation = _write(
        db_engine, SCENARIOS, "scenario-key-0001", lambda _repo: pytest.fail("not replayed")
    )
    assert outcome is PlaneReservationOutcome.REPLAYED
    assert (reservation.result_kind.value, reservation.result_id, reservation.result_created) == (
        "scenario",
        v1.scenario_id,
        True,
    )
    assert count_rows(db_engine, "schedule_scenarios") == 1
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        probe = uow.scenarios.find_request(
            P, SCENARIOS, "scenario-key-0001", _digest(SCENARIOS, "scenario-key-0001")
        )
        assert probe is not None and probe.outcome is PlaneReservationOutcome.REPLAYED
        assert uow.scenarios.find_request(P, SCENARIOS, "unused-key-0001", "a" * 64) is None


def test_same_key_other_request_conflicts(db_engine: Engine, w: PlaneWorld) -> None:
    _scenario(db_engine, w, "scenario-key-0001")
    outcome, _ = _write(
        db_engine,
        SCENARIOS,
        "scenario-key-0001",
        lambda _repo: pytest.fail("a conflicting key wrote"),
        digest="f" * 64,
    )
    assert outcome is PlaneReservationOutcome.CONFLICT
    # The same key under another capability is another reservation.
    _append(
        db_engine, _scenario(db_engine, w, "scenario-key-0002").scenario_id, 1, "scenario-key-0001"
    )
    assert count_rows(db_engine, "schedule_scenarios") == 2


class _Seeded:
    def __init__(self, version: Any, pending_baseline: str) -> None:  # noqa: ANN401
        self.scenario_id = version.scenario_id
        self.pending_baseline = pending_baseline


def _refusal_cases(
    w: PlaneWorld, v1: _Seeded
) -> dict[str, tuple[Callable[[ScenarioRepository], object], type[BaseException]]]:
    def before_insert(_repo: ScenarioRepository) -> object:
        raise LookupError("an S6-3 policy refusal after the reservation")

    def head_moved(repo: ScenarioRepository) -> object:
        return repo.append_version(P, v1.scenario_id, 7, _second(), CLIENT)

    def subject_absent(repo: ScenarioRepository) -> object:
        return repo.insert_scenario(
            P,
            NewScenario(name="Absent", origin_publication_id="spub_s62absent01"),
            first_version(),
            CLIENT,
        )

    def baseline_refused(repo: ScenarioRepository) -> object:
        return repo.write_baseline(
            P,
            ApproveRequest(
                type=BaselineType.CONTRACT,
                effective_from=datetime(2027, 1, 1).date(),
                publication_id=w.queued,
            ),
            reason="Approve a queued publication",
            approval=ScheduleImportApproval("Ref", datetime(2027, 1, 1).date(), "Why"),
            writer=OPERATOR,
        )

    def baseline_not_effective(repo: ScenarioRepository) -> object:
        return repo.insert_scenario(
            P,
            NewScenario(
                name="From a pending baseline",
                origin_publication_id=w.publications[1],
                origin_baseline_id=v1.pending_baseline,
            ),
            first_version(),
            CLIENT,
        )

    return {
        "before_insert": (before_insert, LookupError),
        "head_moved": (head_moved, ScenarioHeadMovedError),
        "baseline_refused": (baseline_refused, BaselineWriteRefusedError),
        "subject_absent": (subject_absent, PlaneSubjectAbsentError),
        "baseline_not_effective": (baseline_not_effective, BaselineWriteRefusedError),
    }


@pytest.mark.parametrize(
    "case",
    ["before_insert", "head_moved", "baseline_refused", "subject_absent", "baseline_not_effective"],
)
def test_a_refused_write_leaves_no_reservation(db_engine: Engine, w: PlaneWorld, case: str) -> None:
    """R9-F08: every refusal after `reserve_request` is raised and rolls the reservation back."""
    v1 = _scenario(db_engine, w)
    from my_pa.domain.schedule.baselines import ProposeRequest

    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        proposed = uow.scenarios.write_baseline(
            P,
            ProposeRequest(
                w.publications[1], BaselineType.CONTRACT, "remote_interactive\x1fclient-7"
            ),
            reason="Propose",
            approval=None,
            writer=CLIENT,
        )
    action, expected = _refusal_cases(w, _Seeded(v1, proposed.baseline_id))[case]
    before = _ledger(db_engine)
    with pytest.raises(expected) as refused, SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        uow.scenarios.lock_principal(P)
        uow.scenarios.reserve_request(P, SCENARIOS, "refused-key-0001", "e" * 64, CLIENT)
        action(uow.scenarios)
    if case == "baseline_not_effective":
        assert refused.value.refusal is BaselineRefusal.CONFLICT_BASELINE_ID  # type: ignore[attr-defined]
    assert _ledger(db_engine) == before
    assert count_rows(db_engine, "schedule_scenarios") == 1


# ---- the Principal partition (section 8.2) -------------------------------------------


def test_other_principal_reads_none_and_writes_nothing(
    db_engine: Engine, w: PlaneWorld, other: PlaneWorld
) -> None:
    v1 = _scenario(db_engine, w)
    run = compute_and_store_cpm_run(
        db_engine,
        P,
        v1.version_id,
        capability_key="run-key-0001",
        request_digest="1" * 64,
        writer=CLIENT,
        admit_compute=lambda _used, _requested: None,
    ).cpm_run
    assert run is not None
    output = _record_output(db_engine, v1, run.cpm_run_id)
    before = {
        table: count_rows(db_engine, table)
        for table in (
            "schedule_scenarios",
            "schedule_scenario_versions",
            "schedule_cpm_runs",
            "schedule_scenario_outputs",
        )
    }
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        repo = uow.scenarios
        assert repo.get_scenario(Q, v1.scenario_id) is None
        assert repo.get_version(Q, v1.version_id) is None
        assert repo.head_version(Q, v1.scenario_id) is None
        assert repo.load_content(Q, v1.version_id) is None
        assert repo.load_change_set(Q, v1.version_id) is None
        assert repo.get_cpm_run(Q, v1.version_id, ENGINE_VERSION) is None
        assert repo.get_cpm_run_by_id(Q, run.cpm_run_id) is None
        assert repo.load_cpm_result(Q, run.cpm_run_id) is None
        assert repo.get_output(Q, output.output_id) is None
        assert repo.load_output(Q, output.output_id) is None
        assert repo.snapshot_source(Q, w.publications[0]) is None
        assert repo.baseline_chain(Q, w.project).events == ()
    for write in (
        lambda repo: repo.insert_scenario(
            Q,
            NewScenario(name="Theirs", origin_publication_id=w.publications[0]),
            first_version(),
            CLIENT,
        ),
        lambda repo: repo.fork_scenario(
            Q, NewScenario(name="Theirs"), v1.version_id, VersionLabel.WHAT_IF, None, CLIENT
        ),
        lambda repo: repo.append_version(Q, v1.scenario_id, 1, _second(), CLIENT),
    ):
        with pytest.raises(PlaneSubjectAbsentError), SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
            write(uow.scenarios)
    with pytest.raises(PlaneSubjectAbsentError):
        compute_and_store_cpm_run(
            db_engine,
            Q,
            v1.version_id,
            capability_key="run-key-0002",
            request_digest="2" * 64,
            writer=CLIENT,
            admit_compute=lambda _used, _requested: None,
        )
    after = {table: count_rows(db_engine, table) for table in before}
    assert after == before


# ---- CPM runs under the compute lease (sections 3.11, 14.8.4) --------------------------


def _run(
    engine: Engine,
    version_id: str,
    key: str,
    *,
    compute: Callable[[ScenarioContent], CpmResult] = run_cpm,
    principal: str = P,
) -> Any:  # noqa: ANN401 - CpmRunWritten
    return compute_and_store_cpm_run(
        engine,
        principal,
        version_id,
        capability_key=key,
        request_digest=_digest(RUNS, key, version_id),
        writer=CLIENT,
        admit_compute=lambda _used, _requested: None,
        compute=compute,
    )


def test_cpm_run_replays_by_natural_key(db_engine: Engine, w: PlaneWorld) -> None:
    """Section 3.11: one run per (version, engine); a second request computes nothing."""
    v1 = _scenario(db_engine, w)
    first = _run(db_engine, v1.version_id, "run-key-0001")
    assert first.created is True and first.cpm_run.status is CpmStatus.COMPUTED
    second = _run(
        db_engine, v1.version_id, "run-key-0002", compute=lambda _c: pytest.fail("recomputed")
    )
    assert (second.created, second.cpm_run.cpm_run_id) == (False, first.cpm_run.cpm_run_id)
    # The insert itself is the backstop: a second insert by the natural key returns the first.
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        content = uow.scenarios.load_content(P, v1.version_id)
        assert content is not None
        from my_pa.infrastructure.persistence.schedule_scenarios import new_cpm_run

        again, created = uow.scenarios.insert_cpm_run(
            P, new_cpm_run(v1.version_id, run_cpm(content.content)), CLIENT
        )
    assert (again.cpm_run_id, created) == (first.cpm_run.cpm_run_id, False)
    assert count_rows(db_engine, "schedule_cpm_runs") == 1
    with db_engine.connect() as connection:
        hits = connection.execute(
            text(
                "SELECT idempotency_key, result_created, result_bytes FROM "
                "knowledge.schedule_scenario_write_requests WHERE capability = :c ORDER BY 1"
            ),
            {"c": RUNS},
        ).all()
    assert [tuple(row) for row in hits] == [
        ("run-key-0001", True, first.cpm_run.result_size_bytes),
        ("run-key-0002", False, 0),
    ]
    replay = _run(db_engine, v1.version_id, "run-key-0001")
    assert replay.outcome is PlaneReservationOutcome.REPLAYED
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        document = uow.scenarios.load_cpm_result(P, first.cpm_run.cpm_run_id)
        assert document is not None and document.document["status"] == "computed"


def test_cpm_runs_only_on_verified_stored_content(db_engine: Engine, w: PlaneWorld) -> None:
    """FR8-F07: digest-correct content that fails `content_problem` is never computed."""
    duplicated = content_object(CONTENT)
    activities = duplicated["activities"]
    assert isinstance(activities, list)
    duplicated["activities"] = [*activities, activities[0]]
    canonical = canonical_json_bytes(duplicated)
    sneaked = NewScenarioVersion(
        label=VersionLabel.WHAT_IF,
        note=None,
        content_zlib=compress_canonical(canonical),
        content_sha256=hashlib.sha256(CONTENT_SCHEMA.encode() + b"\n" + canonical).hexdigest(),
        content_size_bytes=len(canonical),
        activity_count=3,
        relationship_count=1,
        calendar_count=1,
        distribution_spec_sha256=first_version().distribution_spec_sha256,
        snapshot=first_version().snapshot,
    )
    stored = _write(
        db_engine,
        SCENARIOS,
        "scenario-key-0009",
        lambda repo: repo.insert_scenario(
            P,
            NewScenario(name="Duplicated", origin_publication_id=w.publications[0]),
            sneaked,
            CLIENT,
        ),
    )[1]
    with pytest.raises(ScenarioIntegrityError) as refused:
        _run(db_engine, stored.version_id, "run-key-0001", compute=lambda _c: pytest.fail("ran"))
    assert refused.value.code == "content_decode"
    assert count_rows(db_engine, "schedule_cpm_runs") == 0


def _record_output(engine: Engine, version: Any, run_id: str | None) -> Any:  # noqa: ANN401
    document: dict[str, object] = {
        "schema": OUTPUT_SCHEMA,
        "version_id": version.version_id,
        "content_sha256": version.content_sha256,
        "base_cpm_run_id": run_id,
        "kind": "monte_carlo",
        "run_config": {"iterations": 100},
    }
    canonical = canonical_json_bytes(document)
    output = NewScenarioOutput(
        version_id=version.version_id,
        content_sha256=version.content_sha256,
        base_cpm_run_id=run_id,
        kind=OutputKind.MONTE_CARLO,
        iterations=100,
        distribution_spec_sha256=version.distribution_spec_sha256,
        payload_zlib=compress_canonical(canonical),
        payload_sha256=output_payload_sha256(document),
        payload_size_bytes=len(canonical),
    )
    return _write(
        engine,
        OUTPUTS,
        f"output-key-{version.version_id[-8:]}",
        lambda repo: repo.insert_output(P, output, CLIENT),
        stored=lambda stored: stored.payload_size_bytes,
    )[1]


_TAMPER: Final = {
    "content": ("schedule_scenario_versions", "content_zlib", "version_id"),
    "change_set": ("schedule_scenario_versions", "change_set_zlib", "version_id"),
    "result": ("schedule_cpm_runs", "result_zlib", "cpm_run_id"),
    "output": ("schedule_scenario_outputs", "payload_zlib", "output_id"),
}


@pytest.mark.parametrize("kind", sorted(_TAMPER))
def test_tampered_content_reads_as_an_integrity_error(
    db_engine: Engine, w: PlaneWorld, kind: str
) -> None:
    """Section 8.2: a stored stream whose canonical digest differs is never served."""
    v1 = _scenario(db_engine, w)
    v2 = _append(db_engine, v1.scenario_id, 1, "version-key-0001")
    run = _run(db_engine, v2.version_id, "run-key-0001").cpm_run
    output = _record_output(db_engine, v2, run.cpm_run_id)
    subject = {
        "content": v2.version_id,
        "change_set": v2.version_id,
        "result": run.cpm_run_id,
        "output": output.output_id,
    }[kind]
    readers: dict[str, Callable[[ScenarioRepository], object]] = {
        "content": lambda repo: repo.load_content(P, subject),
        "change_set": lambda repo: repo.load_change_set(P, subject),
        "result": lambda repo: repo.load_cpm_result(P, subject),
        "output": lambda repo: repo.load_output(P, subject),
    }
    table, column, key = _TAMPER[kind]
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        assert readers[kind](uow.scenarios) is not None
    with db_engine.connect() as connection:
        stored = bytes(
            connection.execute(
                text(f"SELECT {column} FROM knowledge.{table} WHERE {key} = :k"),  # noqa: S608
                {"k": subject},
            ).scalar_one()
        )
    canonical = zlib.decompress(stored)
    flipped = canonical.replace(b'"schema"', b'"schemA"', 1)
    assert len(flipped) == len(canonical) and flipped != canonical
    with db_engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(f"UPDATE knowledge.{table} SET {column} = :blob WHERE {key} = :k"),  # noqa: S608
            {"blob": zlib.compress(flipped), "k": subject},
        )
    with (
        pytest.raises(ScenarioIntegrityError) as refused,
        SqlAlchemyScenarioUnitOfWork(db_engine) as uow,
    ):
        readers[kind](uow.scenarios)
    assert refused.value.code == f"{kind}_digest"


def test_concurrent_cpm_runs_answer_busy_without_computing(
    db_engine: Engine, w: PlaneWorld
) -> None:
    """Declared layered (P2-24d): both lease layers together; the second never computes."""
    v1 = _scenario(db_engine, w)
    entered = threading.Event()
    release = threading.Event()
    computed: list[str] = []

    def blocking(content: ScenarioContent) -> CpmResult:
        computed.append("first")
        entered.set()
        assert release.wait(60)
        return run_cpm(content)

    outcome: dict[str, Any] = {}
    thread = threading.Thread(
        target=lambda: outcome.setdefault(
            "first", _run(db_engine, v1.version_id, "run-key-0001", compute=blocking)
        )
    )
    thread.start()
    try:
        assert entered.wait(60)
        with pytest.raises(CpmComputeBusyError):
            _run(
                db_engine,
                v1.version_id,
                "run-key-0002",
                compute=lambda c: computed.append("second") or run_cpm(c),
            )
    finally:
        release.set()
        thread.join(60)
    assert computed == ["first"] and outcome["first"].created is True
    assert count_rows(db_engine, "schedule_cpm_runs") == 1


def _hold_session_lease(engine: Engine, principal: str) -> Any:  # noqa: ANN401 - Connection
    holder = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    holder.execute(
        text("SELECT pg_advisory_lock(CAST(:ns AS integer), hashtext(:key))"),
        {"ns": SCHEDULE_CPM_ADVISORY_NAMESPACE, "key": lease_module.cpm_lease_key(principal)},
    )
    return holder


def test_a_held_session_lease_answers_busy(db_engine: Engine, w: PlaneWorld) -> None:
    """P2-24a: another session holds C while the process lock is free."""
    v1 = _scenario(db_engine, w)
    holder = _hold_session_lease(db_engine, P)
    try:
        with pytest.raises(CpmComputeBusyError):
            _run(db_engine, v1.version_id, "run-key-0001", compute=lambda _c: pytest.fail("ran"))
    finally:
        holder.invalidate()  # a session lock must never go back into a pool
        holder.close()
    assert count_rows(db_engine, "schedule_cpm_runs") == 0
    assert _run(db_engine, v1.version_id, "run-key-0001").created is True


def _advisory_holders(engine: Engine) -> list[int]:
    with engine.connect() as connection:
        return [
            int(pid)
            for pid in connection.execute(
                text(
                    "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted AND "
                    "classid = CAST(:ns AS oid)"
                ),
                {"ns": SCHEDULE_CPM_ADVISORY_NAMESPACE},
            ).scalars()
        ]


def test_cpm_lease_connection_is_never_returned_to_the_pool(
    db_engine: Engine, w: PlaneWorld
) -> None:
    """R9-F12: C is held off-pool; after the run its connection is gone and no lock remains."""
    v1 = _scenario(db_engine, w)
    observer = create_database_engine(db_engine.url)
    seen: dict[str, object] = {}

    def observing(content: ScenarioContent) -> CpmResult:
        seen["checked_out"] = db_engine.pool.checkedout()  # type: ignore[attr-defined]
        seen["holders"] = _advisory_holders(observer)
        return run_cpm(content)

    try:
        _run(db_engine, v1.version_id, "run-key-0001", compute=observing)
        holders = seen["holders"]
        assert seen["checked_out"] == 0, "the lease held a request-pool connection"
        assert isinstance(holders, list) and len(holders) == 1
        assert _advisory_holders(observer) == []
        with observer.connect() as connection:
            alive = connection.execute(
                text("SELECT count(*) FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": holders[0]},
            ).scalar_one()
        assert alive == 0, "the lease connection was kept"
    finally:
        observer.dispose()


def test_compute_lease_never_blocks_the_write_transaction(
    monkeypatch: pytest.MonkeyPatch, db_engine: Engine, w: PlaneWorld
) -> None:
    """P2-25: even with C's key text forced equal to P's, C's namespace keeps them apart."""
    v1 = _scenario(db_engine, w)
    monkeypatch.setattr(lease_module, "cpm_lease_key", lambda principal: "principal:" + principal)
    bounded = create_database_engine(db_engine.url, statement_timeout_ms=5_000)
    try:
        written = _run(bounded, v1.version_id, "run-key-0001")
    finally:
        bounded.dispose()
    assert written.created is True


# ---- outputs and the bound reads (sections 4, 14.8.8) --------------------------------


def test_outputs_and_the_bound_reads(db_engine: Engine, w: PlaneWorld) -> None:
    v1 = _scenario(db_engine, w)
    run = _run(db_engine, v1.version_id, "run-key-0001").cpm_run
    output = _record_output(db_engine, v1, run.cpm_run_id)
    at = datetime.now(UTC)
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        repo = uow.scenarios
        assert repo.get_output(P, output.output_id) == output
        assert repo.output_count(P, v1.version_id) == 1
        assert repo.scenario_and_version_counts(P) == (1, 1)
        assert repo.cpm_units_since(P, at - timedelta(hours=1)) == 2
        assert repo.cpm_units_since(P, at + timedelta(hours=1)) == 0
        counts = repo.client_write_counts(P, CLIENT, at + timedelta(seconds=1))
        assert (counts.bucket_hour, counts.bucket_day, counts.principal_day) == (3, 3, 3)
        assert repo.client_write_counts(P, client("other"), at).bucket_hour == 0
        assert repo.client_write_counts(P, OPERATOR, at).bucket_hour == 0
        size = v1.content_size_bytes + run.result_size_bytes + output.payload_size_bytes
        stored = repo.plane_byte_counts(P, CLIENT, at)
        assert (stored.principal_total, stored.principal_day, stored.bucket_day) == (size,) * 3
        assert repo.plane_byte_counts(P, client("other"), at).bucket_day == 0
        repo.record_refusal(P, CLIENT, SCENARIOS, "rate_limited")
        repo.record_refusal(P, OPERATOR, SCENARIOS, "rate_limited")  # never kept
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        assert uow.scenarios.refusal_count(P, CLIENT, at - timedelta(hours=1)) == 1
        assert uow.scenarios.refusal_count(P, client("other"), at - timedelta(hours=1)) == 0
        assert uow.scenarios.refusal_count(P, OPERATOR, at - timedelta(hours=1)) == 0
    assert count_rows(db_engine, "schedule_scenario_write_refusals") == 1
