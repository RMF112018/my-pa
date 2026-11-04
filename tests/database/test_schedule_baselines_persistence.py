"""Schedule Scenarios S6-2: baselines and governing chains (contract sections 12, 14.8.5).

`write_baseline` under the Project lock: the lifecycle transitions and their
typed refusals, the direct approval adopting a pending proposal (B11), the
governing chain, the as-recorded governing read with B5's `effective_from`
values (P43 obligation), Scenario-from-Baseline re-read under J, and the
import-time approval written inside the S5 admission transaction.

`database` tier (`database_clone` by default). Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import (
    BaselineWriteRefusedError,
    BaselineWritten,
    NewScenario,
    PlaneSubjectAbsentError,
    ScheduleAdmissionRejectedError,
)
from my_pa.domain.schedule import (
    ScheduleAdmissionOutcome,
    ScheduleAdmissionRefusal,
    ScheduleBaselineKind,
    ScheduleImportApproval,
    ScheduleImportRequest,
    SchedulePublicationRole,
    normalize_series_name,
    schedule_import_request_digest,
)
from my_pa.domain.schedule.baselines import (
    ApproveRequest,
    BaselineAction,
    BaselineRefusal,
    BaselineRequest,
    BaselineType,
    ProposeRequest,
    RejectRequest,
    RevokeRequest,
    SetGoverningRequest,
    WithdrawRequest,
)
from my_pa.domain.schedule.plane import PlaneProvenance, writer_bucket
from my_pa.infrastructure.persistence.schedule import SqlAlchemyScheduleUnitOfWork
from my_pa.infrastructure.persistence.schedule_scenarios import SqlAlchemyScenarioUnitOfWork
from tests.database.schedule_capability_harness import ScheduleRuntime
from tests.database.schedule_plane_world import (
    OPERATOR,
    PlaneWorld,
    client,
    count_rows,
    disposed_lease_engines,  # noqa: F401 - an autouse fixture
    first_version,
    seed_world,
)

pytestmark = pytest.mark.database

P: Final = "prn_s62base0001"
Q: Final = "prn_s62base0002"
CLIENT: Final = client("client-7")
OTHER_CLIENT: Final = client("client-8")
BUCKET: Final = writer_bucket(CLIENT.decision_channel, CLIENT.asserting_client_id)
OTHER_BUCKET: Final = writer_bucket(OTHER_CLIENT.decision_channel, OTHER_CLIENT.asserting_client_id)
RESTRICT_VIOLATION: Final = "23001"
APPROVAL: Final = ScheduleImportApproval("Approval ref", date(2027, 1, 1), "Approved")
CONTRACT: Final = BaselineType.CONTRACT
UPDATE: Final = BaselineType.APPROVED_UPDATE


@pytest.fixture
def w(db_engine: Engine) -> PlaneWorld:
    return seed_world(db_engine, P, "s62ba")


def _write(
    engine: Engine,
    request: BaselineRequest,
    *,
    writer: PlaneProvenance = OPERATOR,
    approval: ScheduleImportApproval | None = None,
    project_id: str | None = None,
    principal: str = P,
) -> BaselineWritten:
    with SqlAlchemyScenarioUnitOfWork(engine) as uow:
        return uow.scenarios.write_baseline(
            principal,
            request,
            reason="A synthetic reason",
            approval=approval,
            writer=writer,
            project_id=project_id,
        )


def _refused(engine: Engine, request: BaselineRequest, **options: Any) -> BaselineRefusal:  # noqa: ANN401
    with pytest.raises(BaselineWriteRefusedError) as refused:
        _write(engine, request, **options)
    return refused.value.refusal


def _propose(
    engine: Engine, publication: str, *, writer: PlaneProvenance = CLIENT
) -> BaselineWritten:
    bucket = writer_bucket(writer.decision_channel, writer.asserting_client_id)
    assert bucket is not None
    return _write(engine, ProposeRequest(publication, UPDATE, bucket), writer=writer)


def _approve(
    engine: Engine, publication: str, effective: date = date(2027, 1, 1)
) -> BaselineWritten:
    return _write(
        engine,
        ApproveRequest(type=CONTRACT, effective_from=effective, publication_id=publication),
        approval=APPROVAL,
    )


def test_baseline_lifecycle_transitions(db_engine: Engine, w: PlaneWorld) -> None:
    pubs = w.publications
    proposed = _propose(db_engine, pubs[0])
    assert (proposed.seq, proposed.label) == (1, None)
    approved = _write(
        db_engine,
        ApproveRequest(
            type=UPDATE, effective_from=date(2027, 1, 1), baseline_id=proposed.baseline_id
        ),
        approval=APPROVAL,
    )
    assert (approved.baseline_id, approved.seq, approved.label) == (proposed.baseline_id, 2, "BL-0")
    rejected = _propose(db_engine, pubs[1])
    _write(db_engine, RejectRequest(rejected.baseline_id))
    withdrawn = _propose(db_engine, pubs[2])
    _write(db_engine, WithdrawRequest(withdrawn.baseline_id, BUCKET), writer=CLIENT)
    pending = _propose(db_engine, pubs[3])
    assert (
        _refused(db_engine, WithdrawRequest(pending.baseline_id, OTHER_BUCKET), writer=OTHER_CLIENT)
        is BaselineRefusal.DENIED
    )
    # A rejected publication may be proposed again: its ordinal counts the decided proposal.
    again = _propose(db_engine, pubs[1])
    assert _approve(db_engine, pubs[4]).label == "BL-1"
    for request, refusal in (
        (
            ApproveRequest(type=CONTRACT, effective_from=date(2027, 1, 1), publication_id=pubs[0]),
            BaselineRefusal.CONFLICT_BASELINE_ID,
        ),
        (ProposeRequest(pubs[0], UPDATE, BUCKET or ""), BaselineRefusal.CONFLICT_BASELINE_ID),
        (ProposeRequest(w.queued, UPDATE, BUCKET or ""), BaselineRefusal.CONFLICT_STATUS),
        (RejectRequest(approved.baseline_id), BaselineRefusal.CONFLICT_BASELINE_ID),
    ):
        assert _refused(db_engine, request, approval=APPROVAL) is refusal
    with pytest.raises(PlaneSubjectAbsentError):
        _propose(db_engine, "spub_s62absent01")
    with pytest.raises(PlaneSubjectAbsentError):
        _write(db_engine, RejectRequest("sbl_s62absent001"))
    # An intake Series' publication cannot be a baseline (G12, section 11.2).
    assert (
        _refused(db_engine, ProposeRequest(w.intake_publication, UPDATE, BUCKET or ""))
        is BaselineRefusal.CONFLICT_STATUS
    )
    revoked = _write(db_engine, RevokeRequest(approved.baseline_id))
    assert (
        _refused(db_engine, RevokeRequest(approved.baseline_id))
        is BaselineRefusal.CONFLICT_BASELINE_ID
    )
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        chain = uow.scenarios.baseline_chain(P, w.project)
    assert [event.seq for event in chain.events] == list(range(1, revoked.seq + 1))
    assert [event.action for event in chain.events] == [
        BaselineAction.PROPOSE,
        BaselineAction.APPROVE,
        BaselineAction.PROPOSE,
        BaselineAction.REJECT,
        BaselineAction.PROPOSE,
        BaselineAction.WITHDRAW,
        BaselineAction.PROPOSE,
        BaselineAction.PROPOSE,
        BaselineAction.APPROVE,
        BaselineAction.REVOKE,
    ]
    by_seq = {event.seq: event for event in chain.events}
    assert by_seq[1].writer_bucket == BUCKET and by_seq[2].writer_bucket is None
    assert by_seq[again.seq].proposal_ordinal == 1
    with db_engine.connect() as connection:
        recorded = list(
            connection.execute(
                text(
                    "SELECT recorded_at FROM knowledge.schedule_baseline_events "
                    "WHERE principal_id = :p ORDER BY seq"
                ),
                {"p": P},
            ).scalars()
        )
    assert recorded == sorted(recorded)


def test_direct_approval_adopts_a_pending_proposal(db_engine: Engine, w: PlaneWorld) -> None:
    """B11 (RR1-F05): the operator's direct approval adopts the client's pending proposal."""
    proposed = _propose(db_engine, w.publications[0])
    approved = _approve(db_engine, w.publications[0])
    assert (approved.baseline_id, approved.label) == (proposed.baseline_id, "BL-0")
    assert count_rows(db_engine, "schedule_baselines") == 1
    assert (
        _refused(db_engine, WithdrawRequest(proposed.baseline_id, BUCKET), writer=CLIENT)
        is BaselineRefusal.CONFLICT_BASELINE_ID
    )
    with db_engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT b.type, e.type FROM knowledge.schedule_baselines b JOIN "
                "knowledge.schedule_baseline_events e ON e.baseline_id = b.baseline_id "
                "WHERE e.action = 'approve'"
            )
        ).one()
    assert tuple(stored) == ("approved_update", "contract")  # proposed type; effective type


def test_governing_events_are_append_only(db_engine: Engine, w: PlaneWorld) -> None:
    first = _approve(db_engine, w.publications[0])
    second = _approve(db_engine, w.publications[1])
    one = _write(db_engine, SetGoverningRequest(first.baseline_id, None), project_id=w.project)
    two = _write(
        db_engine, SetGoverningRequest(second.baseline_id, first.baseline_id), project_id=w.project
    )
    assert (one.governing, one.seq, two.seq) == (True, 1, 2)
    assert (
        _refused(db_engine, SetGoverningRequest(first.baseline_id, None), project_id=w.project)
        is BaselineRefusal.CONFLICT_GOVERNING
    )
    with pytest.raises(PlaneSubjectAbsentError):
        _write(
            db_engine,
            SetGoverningRequest(first.baseline_id, second.baseline_id),
            project_id="prj_s62absent001",
        )
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        chain = uow.scenarios.baseline_chain(P, w.project)
        assert [event.baseline_id for event in chain.governing] == [
            first.baseline_id,
            second.baseline_id,
        ]
        assert uow.scenarios.governing_as_of(P, w.project, None) == second.baseline_id
        assert uow.scenarios.governing_as_of(Q, w.project, None) is None
    for statement in (
        "UPDATE knowledge.schedule_governing_events SET reason = 'changed'",
        "DELETE FROM knowledge.schedule_governing_events",
    ):
        with pytest.raises(DBAPIError) as refused, db_engine.begin() as connection:
            connection.execute(text(statement))
        assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION


def test_revoking_the_governing_baseline_is_refused(db_engine: Engine, w: PlaneWorld) -> None:
    governing = _approve(db_engine, w.publications[0])
    _write(db_engine, SetGoverningRequest(governing.baseline_id, None), project_id=w.project)
    assert (
        _refused(db_engine, RevokeRequest(governing.baseline_id))
        is BaselineRefusal.CONFLICT_GOVERNING
    )
    assert count_rows(db_engine, "schedule_baseline_events") == 1


def _governing_at(engine: Engine, w: PlaneWorld, seq: int, baseline: str, recorded: str) -> None:
    with engine.begin() as connection:
        previous = connection.execute(
            text(
                "SELECT governing_event_id FROM knowledge.schedule_governing_events "
                "WHERE principal_id = :p AND project_id = :j AND seq = :s"
            ),
            {"p": P, "j": w.project, "s": seq - 1},
        ).scalar_one_or_none()
        connection.execute(
            text(
                "INSERT INTO knowledge.schedule_governing_events (governing_event_id, "
                "principal_id, project_id, baseline_id, seq, previous_governing_event_id, "
                "recorded_at, reason, authority_class, decision_channel, acceptance_basis) "
                "VALUES (:id, :p, :j, :b, :s, :prev, :at, 'B5', 'local_operator', 'local_cli', "
                "'user_confirmed')"
            ),
            {
                "id": f"sgov_s62b5gov{seq:04d}",
                "p": P,
                "j": w.project,
                "b": baseline,
                "s": seq,
                "prev": previous,
                "at": datetime.fromisoformat(recorded).replace(tzinfo=UTC),
            },
        )


def test_governing_as_of_reads_recorded_order_not_effective_from(
    db_engine: Engine, w: PlaneWorld
) -> None:
    """B5: `effective_from` disagrees with recording order; as-of follows `recorded_at`."""
    bl0 = _approve(db_engine, w.publications[0], effective=date(2027, 1, 1))
    bl1 = _approve(db_engine, w.publications[1], effective=date(2026, 12, 1))
    assert (bl0.label, bl1.label) == ("BL-0", "BL-1")
    _governing_at(db_engine, w, 1, bl0.baseline_id, "2027-02-01T10:00:00")
    _governing_at(db_engine, w, 2, bl1.baseline_id, "2027-03-01T10:00:00")
    answers = {}
    with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
        for moment in ("2027-01-15", "2027-02-15", "2027-03-15"):
            at = datetime.fromisoformat(moment).replace(tzinfo=UTC)
            answers[moment] = uow.scenarios.governing_as_of(P, w.project, at)
        answers["now"] = uow.scenarios.governing_as_of(P, w.project, None)
    assert answers == {
        "2027-01-15": None,
        "2027-02-15": bl0.baseline_id,
        "2027-03-15": bl1.baseline_id,
        "now": bl1.baseline_id,
    }


def test_a_scenario_starts_only_from_an_effective_baseline(
    db_engine: Engine, w: PlaneWorld
) -> None:
    """Section 14.8.2 (RR1-F04): effectiveness is re-read under J inside the write."""
    approved = _approve(db_engine, w.publications[0])
    pending = _propose(db_engine, w.publications[1])

    def create(publication: str, baseline: str) -> Any:  # noqa: ANN401
        with SqlAlchemyScenarioUnitOfWork(db_engine) as uow:
            return uow.scenarios.insert_scenario(
                P,
                NewScenario(
                    name="From a baseline",
                    origin_publication_id=publication,
                    origin_baseline_id=baseline,
                ),
                first_version(),
                CLIENT,
            )

    created = create(w.publications[0], approved.baseline_id)
    assert created.version_no == 1
    with pytest.raises(BaselineWriteRefusedError) as refused:
        create(w.publications[1], pending.baseline_id)
    assert refused.value.refusal is BaselineRefusal.CONFLICT_BASELINE_ID
    with pytest.raises(PlaneSubjectAbsentError):
        create(w.publications[1], approved.baseline_id)  # not this publication's Baseline
    _write(db_engine, RevokeRequest(approved.baseline_id))
    with pytest.raises(BaselineWriteRefusedError) as refused:
        create(w.publications[0], approved.baseline_id)
    assert refused.value.refusal is BaselineRefusal.CONFLICT_BASELINE_ID
    assert count_rows(db_engine, "schedule_scenarios") == 1


# ---- the import-time approval inside the S5 admission (section 14.8.5) -----------------


@pytest.fixture
def runtime(cloned_database_url: str) -> Iterator[ScheduleRuntime]:
    rt = ScheduleRuntime(cloned_database_url)
    try:
        yield rt
    finally:
        rt.close()


def _baseline_request(
    world: Any,  # noqa: ANN401 - the harness World
    object_id: str,
    version_id: str,
    key: str,
    approval: ScheduleImportApproval = APPROVAL,
) -> ScheduleImportRequest:
    return ScheduleImportRequest(
        project_id=world.project,
        series_id=None,
        series_name=normalize_series_name("Contract Baseline"),
        enrollment_id=world.enrollment,
        source_object_id=object_id,
        source_version_id=version_id,
        publication_role=SchedulePublicationRole.BASELINE,
        baseline_kind=ScheduleBaselineKind.CONTRACT,
        expected_data_date=None,
        supersedes_publication_id=None,
        idempotency_key=key,
        approval=approval,
    )


def _admit(
    engine: Engine, principal: str, request: ScheduleImportRequest, channel: str | None
) -> Any:  # noqa: ANN401
    digest = schedule_import_request_digest(principal, request)
    with SqlAlchemyScheduleUnitOfWork(engine) as uow:
        return uow.schedules.admit_publication(principal, request, digest, operator_channel=channel)


def test_import_time_approval_is_written_in_the_admission(runtime: ScheduleRuntime) -> None:
    world = runtime.world(P, "s62bi")
    object_id, version_id = runtime.source_object(world)
    request = _baseline_request(world, object_id, version_id, "baseline-key-0001")
    for channel in (None, "remote_interactive"):
        with pytest.raises(ValueError, match="attested operator channel"):
            _admit(runtime.engine, P, request, channel)
    admitted = _admit(runtime.engine, P, request, "local_web")
    assert admitted.outcome is ScheduleAdmissionOutcome.CREATED
    with runtime.engine.connect() as connection:
        event = connection.execute(
            text(
                "SELECT e.action, e.type, e.label, e.approval_reference, e.effective_from, "
                "e.reason, e.approved_at_import, e.authority_class, e.decision_channel, "
                "e.acceptance_basis, b.type, p.status FROM knowledge.schedule_baseline_events e "
                "JOIN knowledge.schedule_baselines b ON b.baseline_id = e.baseline_id "
                "JOIN knowledge.schedule_publications p ON p.publication_id = e.publication_id"
            )
        ).one()
    assert tuple(event) == (
        "approve",
        "contract",
        "BL-0",
        "Approval ref",
        date(2027, 1, 1),
        "Approved",
        True,
        "local_operator",
        "local_web",
        "user_confirmed",
        "contract",
        "queued",
    )
    replay = _admit(runtime.engine, P, request, "local_web")
    assert replay.outcome is ScheduleAdmissionOutcome.REPLAYED
    assert count_rows(runtime.engine, "schedule_baseline_events") == 1
    # An update import takes no approval and writes no baseline event.
    other_object, other_version = runtime.source_object(world)
    update = ScheduleImportRequest(
        project_id=world.project,
        series_id=None,
        series_name=normalize_series_name("Master"),
        enrollment_id=world.enrollment,
        source_object_id=other_object,
        source_version_id=other_version,
        publication_role=SchedulePublicationRole.UPDATE,
        baseline_kind=None,
        expected_data_date=None,
        supersedes_publication_id=None,
        idempotency_key="update-key-0001",
    )
    with pytest.raises(ValueError, match="attested operator channel"):
        _admit(runtime.engine, P, update, "local_cli")
    _admit(runtime.engine, P, update, None)
    assert count_rows(runtime.engine, "schedule_baseline_events") == 1


def test_baseline_reimport_with_other_approval_fields_conflicts(runtime: ScheduleRuntime) -> None:
    """P2-46: a role-`baseline` replay by source version compares the approval too."""
    world = runtime.world(P, "s62br")
    object_id, version_id = runtime.source_object(world)
    original = _admit(
        runtime.engine,
        P,
        _baseline_request(world, object_id, version_id, "baseline-key-0001"),
        "local_cli",
    )
    same = _admit(
        runtime.engine,
        P,
        _baseline_request(world, object_id, version_id, "baseline-key-0002"),
        "local_cli",
    )
    assert same.outcome is ScheduleAdmissionOutcome.REPLAYED
    assert same.publication.publication_id == original.publication.publication_id
    for changed in (
        ScheduleImportApproval("Another ref", APPROVAL.effective_from, APPROVAL.reason),
        ScheduleImportApproval(APPROVAL.approval_reference, date(2027, 2, 1), APPROVAL.reason),
        ScheduleImportApproval(APPROVAL.approval_reference, APPROVAL.effective_from, "Other"),
    ):
        request = _baseline_request(world, object_id, version_id, "baseline-key-0003", changed)
        with pytest.raises(ScheduleAdmissionRejectedError) as refused:
            _admit(runtime.engine, P, request, "local_cli")
        assert refused.value.reason is ScheduleAdmissionRefusal.SOURCE_VERSION_CONFLICT
    assert count_rows(runtime.engine, "schedule_baseline_events") == 1
