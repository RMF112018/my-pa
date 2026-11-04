"""Schedule Scenarios S6-2: the plane tables behind `contracts.ports.ScenarioRepository`.

Contract: `docs/architecture/schedule-scenarios-contract.md` section 14.8. This
module is the whole of the S6-2 plane persistence: the idempotency and refusal
ledgers, Scenarios and versions (CAS), CPM runs and outputs (natural key,
digest verified on read), the per-Project baseline and governing chains under
the Project lock, the import-time approval the S5 admission calls, and the
worker's series-match finalization hook. There is no capability, handler or
policy here; S6-3 composes these methods.

**The partition is reached through the guard, never written by hand** -- the
`schedule.py` shape. Every statement over a partitioned table composes `_mine`
(over `partition_criterion`) or `_bound` (over `principal_bound_values`), and a
statement naming two partitioned tables also composes
`matching_partition_criterion`. The one `INSERT ... SELECT` (the fork's
byte-for-byte content copy) selects its partition column from a source row
already constrained by `_mine`.

**Locks** (section 14.8.4): P, the Principal plane lock, and J, the Project
lock, are `pg_advisory_xact_lock(int4, int4)` in the namespace
`SCHEDULE_PLANE_ADVISORY_NAMESPACE`, built with the expression language
(`func.pg_advisory_xact_lock`/`func.hashtext`), never `text()`. No path takes
P after J. The compute lease C lives in `schedule_cpm_lease.py`.

**The database is the final word.** Triggers G3-G15 and the section 12.1
uniques re-verify everything decided here; the reads exist to answer with a
typed, content-free error before a statement is refused. Every non-success
after `reserve_request` is raised (R9-F08), never returned.

`_seam` is a module seam the race and hook-defect tests replace; in
production it does nothing.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from types import TracebackType
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Engine,
    Integer,
    Table,
    Text,
    and_,
    cast,
    func,
    insert,
    literal,
    null,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, RowMapping
from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.sql.dml import Insert

from my_pa.contracts.ports import (
    BaselineChain,
    BaselineWriteRefusedError,
    BaselineWritten,
    NewCpmRun,
    NewScenario,
    NewScenarioChangeSet,
    NewScenarioOutput,
    NewScenarioVersion,
    PlaneByteCounts,
    PlaneReservation,
    PlaneReservationOutcome,
    PlaneSubjectAbsentError,
    PlaneWriteCounts,
    ScenarioHeadMovedError,
    ScenarioIntegrityError,
    ScenarioRepository,
    ScenarioSnapshotSource,
    ScenarioUnitOfWork,
    ScheduleAdmissionRejectedError,
    ScheduleBaselineRaceError,
    ScheduleIntegrityError,
    ScheduleLeaseLostError,
    ScheduleRepository,
    SeriesMatchRecord,
    SeriesMatchUndecided,
    StoredCpmRun,
    StoredScenario,
    StoredScenarioOutput,
    StoredScenarioVersion,
    VerifiedDocument,
    VerifiedScenarioContent,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.schedule import (
    ScheduleImportApproval,
    ScheduleImportRequest,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    ScheduleRowType,
    normalize_display_text,
    normalize_series_name,
    schedule_import_request_digest,
)
from my_pa.domain.schedule.baselines import (
    ApproveRequest,
    BaselineAction,
    BaselineEvent,
    BaselinePlan,
    BaselineRefusal,
    BaselineRequest,
    BaselineStatus,
    BaselineType,
    GoverningEvent,
    ProposeRequest,
    SetGoverningRequest,
    baseline_status,
    decide_baseline_write,
)
from my_pa.domain.schedule.canonical import canonical_json_bytes
from my_pa.domain.schedule.currency import (
    CurrencyPublication,
    current_standard_update,
)
from my_pa.domain.schedule.plane import (
    MATCH_INTEGRITY_REFUSAL,
    MAX_CPM_RESULT_BYTES,
    PLANE_ATTESTED_DECISION_CHANNELS,
    PLANE_CLIENT_DECISION_CHANNELS,
    PLANE_WRITE_CAPABILITIES,
    RESULT_KIND_BY_CAPABILITY,
    MatchAdmissionSkip,
    PlaneProvenance,
    PlaneResultKind,
    second_admission_key,
    writer_bucket,
)
from my_pa.domain.schedule.scenario.canonical import (
    CHANGE_SET_SCHEMA,
    CONTENT_SCHEMA,
    OUTPUT_SCHEMA,
    RESULT_SCHEMA,
    ScenarioDecodeError,
    change_set_bytes,
    change_set_sha256,
    content_bytes,
    content_from_object,
    content_sha256,
    distribution_spec_sha256,
    result_bytes,
    result_sha256,
)
from my_pa.domain.schedule.scenario.changeset import ApplicationReport
from my_pa.domain.schedule.scenario.cpm import CpmResult, CpmStatus, result_document
from my_pa.domain.schedule.scenario.model import (
    MAX_ACTIVITIES,
    MAX_CHANGE_SET_BYTES,
    MAX_CONTENT_BYTES,
    ScenarioContent,
    VersionLabel,
    content_problem,
)
from my_pa.domain.schedule.scenario.outputs import MAX_OUTPUT_BYTES, OutputKind, ValidatedOutput
from my_pa.domain.schedule.scenario.snapshot import SnapshotReport
from my_pa.domain.schedule.series_match import (
    MAX_MATCH_CANDIDATES,
    MatchCandidate,
    MatchDecision,
    MatchIncoming,
    MatchOutcome,
    MatchReason,
    NewSeriesName,
    SeriesCandidate,
    match_series,
)
from my_pa.domain.source.registry import issue_identifier

# The module, never a name from it: `schedule.py` imports this module back the
# same way, and 2 module imports are safe in either import order.
from my_pa.infrastructure.persistence import schedule as _s5
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.schedule_plane_codec import (
    compress_canonical,
    verified_canonical,
    verified_document,
)
from my_pa.infrastructure.persistence.tables import (
    schedule_baseline_events,
    schedule_baselines,
    schedule_cpm_runs,
    schedule_governing_events,
    schedule_intake_series,
    schedule_publications,
    schedule_rows,
    schedule_scenario_outputs,
    schedule_scenario_versions,
    schedule_scenario_write_refusals,
    schedule_scenario_write_requests,
    schedule_scenarios,
    schedule_series,
    schedule_series_match_decisions,
)

__all__ = [
    "SCHEDULE_PLANE_ADVISORY_NAMESPACE",
    "SqlAlchemyScenarioUnitOfWork",
    "SqlScenarioRepository",
    "lock_project",
    "new_cpm_run",
    "new_scenario_output",
    "new_scenario_version",
    "plane_lock_key",
    "record_import_approval",
    "stored_import_approval",
]

#: Section 14.8.4: the P and J namespace, "SSCP" (S6-2-D06).
SCHEDULE_PLANE_ADVISORY_NAMESPACE: Final = 0x53534350

_ELIGIBLE: Final = (
    SchedulePublicationStatus.COMPLETE.value,
    SchedulePublicationStatus.PARTIAL.value,
)
_LINKABLE: Final = (ScheduleRowType.ACTIVITY.value, ScheduleRowType.MILESTONE.value)
_PUBLICATION_ORIGIN: Final = "publication"
_VERSION_ORIGIN: Final = "version"
_HOUR: Final = timedelta(hours=1)
_DAY: Final = timedelta(days=1)
_UNIQUE_VIOLATION: Final = "23505"
_RESTRICT_VIOLATION: Final = "23001"
#: The trigger functions whose `restrict_violation` is a lost race (section 14.8.5).
_G12: Final = "a_schedule_baseline_names_an_admissible_publication"
_G14: Final = "a_schedule_baseline_event_extends_its_chain"
_G15: Final = "a_schedule_governing_event_extends_its_chain"
#: Section 14.8.7: only these propagate out of the hook (with non-`Exception` errors).
_TRANSIENT: Final = (OperationalError, InterfaceError, ScheduleLeaseLostError)
_DECIDED: Final = frozenset(
    {BaselineAction.APPROVE, BaselineAction.REJECT, BaselineAction.WITHDRAW}
)


def _seam(stage: str) -> None:
    """A test seam at `stage`; production does nothing here."""
    del stage


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


# ---- advisory locks (section 14.8.4) --------------------------------------------------


def plane_lock_key(kind: str, *parts: str) -> str:
    """The `hashtext` input of one plane lock: `principal:<p>` or `project:<p>:<j>`."""
    return kind + ":" + ":".join(parts)


def _advisory_xact_lock(connection: Connection, key: str) -> None:
    connection.execute(
        select(
            func.pg_advisory_xact_lock(
                cast(literal(SCHEDULE_PLANE_ADVISORY_NAMESPACE), Integer),
                func.hashtext(literal(key, Text)),
            )
        )
    ).all()


def lock_principal_plane(connection: Connection, principal_id: str) -> None:
    """P: every plane write transaction's first statement."""
    _advisory_xact_lock(connection, plane_lock_key("principal", principal_id))


def lock_project(connection: Connection, principal_id: str, project_id: str) -> None:
    """J: baseline and governing writes, the import approval and the intake hook."""
    _advisory_xact_lock(connection, plane_lock_key("project", principal_id, project_id))


# ---- builders run outside any transaction (S6-2-D14) -----------------------------------


def new_scenario_version(
    content: ScenarioContent,
    *,
    label: VersionLabel,
    note: str | None = None,
    snapshot: SnapshotReport | None = None,
    ops: Sequence[object] | None = None,
    applied: ApplicationReport | None = None,
) -> NewScenarioVersion:
    """Canonicalize, bound and compress one version (version 1 carries no change set)."""
    if content_problem(content) is not None:
        raise ValueError("a stored scenario content passes content_problem")
    if (ops is None) != (applied is None):
        raise ValueError("a change set is stored with its application report")
    canonical = content_bytes(content)
    if len(canonical) > MAX_CONTENT_BYTES:
        raise ValueError("a scenario content is at most 33554432 canonical bytes")
    change_set = None
    if ops is not None and applied is not None:
        ops_bytes = change_set_bytes(ops)
        if len(ops_bytes) > MAX_CHANGE_SET_BYTES:
            raise ValueError("a change set is at most 4194304 canonical bytes")
        change_set = NewScenarioChangeSet(
            zlib=compress_canonical(ops_bytes),
            sha256=change_set_sha256(ops),
            size_bytes=len(ops_bytes),
            op_count=len(ops),
            ops_applied=applied.ops_applied,
            relationships_removed=applied.relationships_removed,
            content_changed=applied.content_changed,
        )
    return NewScenarioVersion(
        label=label,
        note=note,
        content_zlib=compress_canonical(canonical),
        content_sha256=content_sha256(content),
        content_size_bytes=len(canonical),
        activity_count=len(content.activities),
        relationship_count=len(content.relationships),
        calendar_count=len(content.calendars),
        distribution_spec_sha256=distribution_spec_sha256(content),
        change_set=change_set,
        snapshot=snapshot,
    )


def new_cpm_run(version_id: str, result: CpmResult) -> NewCpmRun:
    """One run's stored form; a result over 64 MiB is refused (`result_bound`, section 3.11)."""
    document = result_document(result)
    canonical = result_bytes(document)
    if len(canonical) > MAX_CPM_RESULT_BYTES:
        raise ScenarioIntegrityError("result_bound")
    summary = result.summary
    finish = document["summary"]
    project_finish = finish.get("project_finish") if isinstance(finish, dict) else None
    return NewCpmRun(
        version_id=version_id,
        engine_version=result.engine_version,
        input_content_sha256=result.input_content_sha256,
        status=result.status,
        result_zlib=compress_canonical(canonical),
        result_sha256=result_sha256(document),
        result_size_bytes=len(canonical),
        activity_count=summary.activity_count,
        relationship_count=summary.relationship_count,
        project_finish=(
            None
            if result.status is not CpmStatus.COMPUTED or project_finish is None
            else str(project_finish)
        ),
    )


def new_scenario_output(validated: ValidatedOutput, *, distribution_spec: str) -> NewScenarioOutput:
    """One validated output's stored form (the binding is the validated document's)."""
    document = validated.document
    canonical = canonical_json_bytes(dict(document))
    if len(canonical) > MAX_OUTPUT_BYTES:
        raise ValueError("an output is at most 1048576 canonical bytes")
    config = document["run_config"]
    if not isinstance(config, Mapping):
        raise ValueError("a validated output carries its run configuration")
    base = document.get("base_cpm_run_id")
    return NewScenarioOutput(
        version_id=str(document["version_id"]),
        content_sha256=str(document["content_sha256"]),
        base_cpm_run_id=None if base is None else str(base),
        kind=validated.kind,
        iterations=int(str(config["iterations"])),
        distribution_spec_sha256=distribution_spec,
        payload_zlib=compress_canonical(canonical),
        payload_sha256=validated.payload_sha256,
        payload_size_bytes=len(canonical),
    )


# ---- hydrators (the Principal is the authenticated parameter, never the row's) -------


def _provenance_values(writer: PlaneProvenance) -> dict[str, object]:
    return {
        "authority_class": writer.authority_class,
        "decision_channel": writer.decision_channel,
        "asserting_client_id": writer.asserting_client_id,
        "acceptance_basis": writer.acceptance_basis,
        "user_directed_claim": writer.user_directed_claim,
    }


def _provenance(row: RowMapping) -> PlaneProvenance:
    return PlaneProvenance(
        authority_class=row["authority_class"],
        decision_channel=row["decision_channel"],
        asserting_client_id=row["asserting_client_id"],
        acceptance_basis=row["acceptance_basis"],
        user_directed_claim=row["user_directed_claim"],
    )


def _to_scenario(row: RowMapping) -> StoredScenario:
    return StoredScenario(
        scenario_id=row["scenario_id"],
        project_id=row["project_id"],
        series_id=row["series_id"],
        name=row["name"],
        description=row["description"],
        origin_kind=row["origin_kind"],
        origin_publication_id=row["origin_publication_id"],
        origin_baseline_id=row["origin_baseline_id"],
        origin_version_id=row["origin_version_id"],
        provenance=_provenance(row),
        created_at=row["created_at"],
    )


def _to_version(row: RowMapping) -> StoredScenarioVersion:
    snapshot = (
        None
        if row["snapshot_activities"] is None
        else SnapshotReport(
            activities=row["snapshot_activities"],
            milestones=row["snapshot_milestones"],
            durations_quantized=row["snapshot_durations_quantized"],
            durations_out_of_range=row["snapshot_durations_out_of_range"],
            original_missing=row["snapshot_original_missing"],
            remaining_missing=row["snapshot_remaining_missing"],
        )
    )
    return StoredScenarioVersion(
        version_id=row["version_id"],
        scenario_id=row["scenario_id"],
        project_id=row["project_id"],
        series_id=row["series_id"],
        version_no=row["version_no"],
        parent_version_id=row["parent_version_id"],
        label=VersionLabel(row["label"]),
        note=row["note"],
        content_sha256=row["content_sha256"],
        content_size_bytes=row["content_size_bytes"],
        change_set_sha256=row["change_set_sha256"],
        change_set_size_bytes=row["change_set_size_bytes"],
        change_set_op_count=row["change_set_op_count"],
        ops_applied=row["ops_applied"],
        relationships_removed=row["relationships_removed"],
        content_changed=row["content_changed"],
        snapshot=snapshot,
        activity_count=row["activity_count"],
        relationship_count=row["relationship_count"],
        calendar_count=row["calendar_count"],
        distribution_spec_sha256=row["distribution_spec_sha256"],
        provenance=_provenance(row),
        created_at=row["created_at"],
    )


def _to_run(row: RowMapping) -> StoredCpmRun:
    return StoredCpmRun(
        cpm_run_id=row["cpm_run_id"],
        version_id=row["version_id"],
        engine_version=row["engine_version"],
        input_content_sha256=row["input_content_sha256"],
        status=CpmStatus(row["status"]),
        result_sha256=row["result_sha256"],
        result_size_bytes=row["result_size_bytes"],
        activity_count=row["activity_count"],
        relationship_count=row["relationship_count"],
        project_finish=row["project_finish"],
        provenance=_provenance(row),
        created_at=row["created_at"],
    )


def _to_output(row: RowMapping) -> StoredScenarioOutput:
    return StoredScenarioOutput(
        output_id=row["output_id"],
        version_id=row["version_id"],
        content_sha256=row["content_sha256"],
        base_cpm_run_id=row["base_cpm_run_id"],
        kind=OutputKind(row["kind"]),
        iterations=row["iterations"],
        distribution_spec_sha256=row["distribution_spec_sha256"],
        payload_sha256=row["payload_sha256"],
        payload_size_bytes=row["payload_size_bytes"],
        provenance=_provenance(row),
        created_at=row["created_at"],
    )


def _to_event(row: RowMapping) -> BaselineEvent:
    kind = row["type"]
    return BaselineEvent(
        seq=row["seq"],
        baseline_id=row["baseline_id"],
        publication_id=row["publication_id"],
        action=BaselineAction(row["action"]),
        recorded_at=row["recorded_at"],
        type=None if kind is None else BaselineType(kind),
        label=row["label"],
        effective_from=row["effective_from"],
        supersedes_baseline_id=row["supersedes_baseline_id"],
        proposal_ordinal=row["proposal_ordinal"],
        writer_bucket=writer_bucket(row["decision_channel"], row["asserting_client_id"]),
    )


def _candidate_object(candidate: MatchCandidate) -> dict[str, object]:
    return {
        "series_id": candidate.series_id,
        "publication_id": candidate.publication_id,
        "data_date": candidate.data_date.isoformat(),
        "score": candidate.score,
        "data_date_coherent": candidate.data_date_coherent,
        "name_agreement_permille": candidate.name_agreement_permille,
        "title_equal": candidate.title_equal,
    }


def _candidate_from(value: Mapping[str, Any]) -> MatchCandidate:
    return MatchCandidate(
        series_id=str(value["series_id"]),
        publication_id=str(value["publication_id"]),
        data_date=date.fromisoformat(str(value["data_date"])),
        score=int(value["score"]),
        data_date_coherent=bool(value["data_date_coherent"]),
        name_agreement_permille=int(value["name_agreement_permille"]),
        title_equal=bool(value["title_equal"]),
    )


def _to_decision(row: RowMapping) -> SeriesMatchRecord:
    reason = row["reason"]
    return SeriesMatchRecord(
        decision_id=row["decision_id"],
        intake_publication_id=row["intake_publication_id"],
        intake_series_id=row["intake_series_id"],
        outcome=MatchOutcome(row["outcome"]),
        reason=None if reason is None else MatchReason(reason),
        threshold_version=row["threshold_version"],
        incoming_id_count=row["incoming_id_count"],
        candidates=tuple(_candidate_from(item) for item in row["candidates"]),
        target_series_id=row["target_series_id"],
        resulting_publication_id=row["resulting_publication_id"],
        admission_refusal=row["admission_refusal"],
        admission_skipped=row["admission_skipped"],
    )


def _sqlstate(error: IntegrityError) -> str | None:
    state = getattr(error.orig, "sqlstate", None)
    return None if state is None else str(state)


def _constraint_name(error: Exception) -> str | None:
    diag = getattr(getattr(error, "orig", None), "diag", None)
    name = getattr(diag, "constraint_name", None)
    return None if name is None else str(name)


def _defect_code(error: Exception) -> str:
    """The hook's undecided code: the driver's constraint name, else the class name."""
    return _constraint_name(error) or type(error).__name__


class _HookDefectError(Exception):
    """A deterministic hook defect, carried out of the outer savepoint (section 14.8.7)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _NameRacedError(Exception):
    """A `created` admission joined a Series it did not create (R9-F02)."""


class SqlScenarioRepository(ScenarioRepository):
    """The plane tables on one connection; never commits."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _schedules(self) -> ScheduleRepository:
        return _s5.SqlScheduleRepository(self._connection)

    # ---- prologue (section 14.8.2) ---------------------------------------------------

    def lock_principal(self, principal_id: str) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        lock_principal_plane(self._connection, principal_id)

    @staticmethod
    def _capability(capability: str) -> str:
        if capability not in PLANE_WRITE_CAPABILITIES:
            raise ValueError("a plane write names one of the 10 plane capabilities")
        return capability

    def _ledger_row(self, principal_id: str, capability: str, key: str) -> RowMapping | None:
        ledger = schedule_scenario_write_requests
        return (
            self._connection.execute(
                select(ledger).where(
                    _mine(ledger, principal_id),
                    ledger.c.capability == capability,
                    ledger.c.idempotency_key == key,
                )
            )
            .mappings()
            .one_or_none()
        )

    @staticmethod
    def _answer(row: RowMapping, request_digest: str) -> PlaneReservation:
        if row["request_digest"] != request_digest:
            return PlaneReservation(PlaneReservationOutcome.CONFLICT)
        kind = row["result_kind"]
        return PlaneReservation(
            PlaneReservationOutcome.REPLAYED,
            result_kind=None if kind is None else PlaneResultKind(kind),
            result_id=row["result_id"],
            result_created=row["result_created"],
        )

    def reserve_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        request_digest: str,
        writer: PlaneProvenance,
    ) -> PlaneReservation:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        ledger = schedule_scenario_write_requests
        inserted = self._connection.execute(
            pg_insert(ledger)
            .values(
                _bound(
                    ledger,
                    principal_id,
                    {
                        "capability": self._capability(capability),
                        "idempotency_key": idempotency_key,
                        "request_digest": request_digest,
                        "decision_channel": writer.decision_channel,
                        "asserting_client_id": writer.asserting_client_id,
                    },
                )
            )
            .on_conflict_do_nothing(
                index_elements=[
                    ledger.c.principal_id,
                    ledger.c.capability,
                    ledger.c.idempotency_key,
                ]
            )
            .returning(ledger.c.idempotency_key)
        ).first()
        if inserted is not None:
            return PlaneReservation(PlaneReservationOutcome.RESERVED)
        existing = self._ledger_row(principal_id, capability, idempotency_key)
        if existing is None:
            raise ScenarioIntegrityError("ledger_race_unresolved")
        return self._answer(existing, request_digest)

    def find_request(
        self, principal_id: str, capability: str, idempotency_key: str, request_digest: str
    ) -> PlaneReservation | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        existing = self._ledger_row(principal_id, self._capability(capability), idempotency_key)
        return None if existing is None else self._answer(existing, request_digest)

    def complete_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        result_id: str,
        *,
        created: bool,
        stored_bytes: int,
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        ledger = schedule_scenario_write_requests
        completed = self._connection.execute(
            update(ledger)
            .where(
                _mine(ledger, principal_id),
                ledger.c.capability == self._capability(capability),
                ledger.c.idempotency_key == idempotency_key,
                ledger.c.completed_at.is_(None),
            )
            .values(
                completed_at=func.now(),
                result_kind=RESULT_KIND_BY_CAPABILITY[capability].value,
                result_id=result_id,
                result_created=created,
                result_bytes=stored_bytes,
            )
        ).rowcount
        if completed != 1:
            raise ScenarioIntegrityError("ledger_not_reserved")

    # ---- bound reads (section 14.8.8) -------------------------------------------------

    def _bucket(self, table: Table, writer: PlaneProvenance) -> ColumnElement[bool]:
        return and_(
            table.c.decision_channel == writer.decision_channel,
            table.c.asserting_client_id.is_not_distinct_from(writer.asserting_client_id),
        )

    def client_write_counts(
        self, principal_id: str, writer: PlaneProvenance, at: datetime
    ) -> PlaneWriteCounts:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        ledger = schedule_scenario_write_requests
        client = ledger.c.decision_channel.in_(sorted(PLANE_CLIENT_DECISION_CHANNELS))
        bucket = and_(client, self._bucket(ledger, writer))
        counted = (
            self._connection.execute(
                select(
                    func.count().filter(bucket, ledger.c.completed_at > at - _HOUR).label("hour"),
                    func.count().filter(bucket, ledger.c.completed_at > at - _DAY).label("day"),
                    func.count().filter(client, ledger.c.completed_at > at - _DAY).label("all"),
                ).where(_mine(ledger, principal_id), ledger.c.completed_at.is_not(None))
            )
            .mappings()
            .one()
        )
        attested = writer.decision_channel in PLANE_ATTESTED_DECISION_CHANNELS
        return PlaneWriteCounts(
            bucket_hour=0 if attested else int(counted["hour"]),
            bucket_day=0 if attested else int(counted["day"]),
            principal_day=int(counted["all"]),
        )

    def plane_byte_counts(
        self, principal_id: str, writer: PlaneProvenance, at: datetime
    ) -> PlaneByteCounts:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        total = day = bucket = 0
        attested = writer.decision_channel in PLANE_ATTESTED_DECISION_CHANNELS
        for table, size in (
            (schedule_scenario_versions, schedule_scenario_versions.c.content_size_bytes),
            (schedule_cpm_runs, schedule_cpm_runs.c.result_size_bytes),
            (schedule_scenario_outputs, schedule_scenario_outputs.c.payload_size_bytes),
        ):
            recent = table.c.created_at > at - _DAY
            summed = (
                self._connection.execute(
                    select(
                        func.coalesce(func.sum(size), 0).label("total"),
                        func.coalesce(func.sum(size).filter(recent), 0).label("day"),
                        func.coalesce(
                            func.sum(size).filter(recent, self._bucket(table, writer)), 0
                        ).label("bucket"),
                    ).where(_mine(table, principal_id))
                )
                .mappings()
                .one()
            )
            total += int(summed["total"])
            day += int(summed["day"])
            bucket += 0 if attested else int(summed["bucket"])
        return PlaneByteCounts(principal_total=total, principal_day=day, bucket_day=bucket)

    def scenario_and_version_counts(self, principal_id: str) -> tuple[int, int]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        scenarios = self._connection.execute(
            select(func.count())
            .select_from(schedule_scenarios)
            .where(_mine(schedule_scenarios, principal_id))
        ).scalar_one()
        versions = self._connection.execute(
            select(func.count())
            .select_from(schedule_scenario_versions)
            .where(_mine(schedule_scenario_versions, principal_id))
        ).scalar_one()
        return int(scenarios), int(versions)

    def output_count(self, principal_id: str, version_id: str) -> int:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        outputs = schedule_scenario_outputs
        return int(
            self._connection.execute(
                select(func.count())
                .select_from(outputs)
                .where(_mine(outputs, principal_id), outputs.c.version_id == version_id)
            ).scalar_one()
        )

    def cpm_units_since(self, principal_id: str, since: datetime) -> int:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        runs = schedule_cpm_runs
        return int(
            self._connection.execute(
                select(func.coalesce(func.sum(runs.c.activity_count), 0)).where(
                    _mine(runs, principal_id), runs.c.created_at >= since
                )
            ).scalar_one()
        )

    def refusal_count(self, principal_id: str, writer: PlaneProvenance, since: datetime) -> int:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if writer.decision_channel in PLANE_ATTESTED_DECISION_CHANNELS:
            return 0
        refusals = schedule_scenario_write_refusals
        return int(
            self._connection.execute(
                select(func.count())
                .select_from(refusals)
                .where(
                    _mine(refusals, principal_id),
                    self._bucket(refusals, writer),
                    refusals.c.refused_at >= since,
                )
            ).scalar_one()
        )

    def record_refusal(
        self, principal_id: str, writer: PlaneProvenance, capability: str, error_code: str
    ) -> None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if writer.decision_channel in PLANE_ATTESTED_DECISION_CHANNELS:
            return  # section 14.3.11: never written for an attested operator
        refusals = schedule_scenario_write_refusals
        self._connection.execute(
            insert(refusals).values(
                _bound(
                    refusals,
                    principal_id,
                    {
                        "capability": self._capability(capability),
                        "decision_channel": writer.decision_channel,
                        "asserting_client_id": writer.asserting_client_id,
                        "error_code": error_code,
                    },
                )
            )
        )

    # ---- shared reads -------------------------------------------------------------------

    def _publication(self, principal_id: str, publication_id: str) -> RowMapping | None:
        pubs = schedule_publications
        return (
            self._connection.execute(
                select(pubs).where(
                    _mine(pubs, principal_id), pubs.c.publication_id == publication_id
                )
            )
            .mappings()
            .one_or_none()
        )

    def _not_intake(self, principal_id: str) -> ColumnElement[bool]:
        """The publication's Series holds no intake row (correlated, both partitioned)."""
        intake = schedule_intake_series
        pubs = schedule_publications
        return ~(
            select(intake.c.series_id)
            .where(
                _mine(intake, principal_id),
                matching_partition_criterion(intake, pubs),
                intake.c.series_id == pubs.c.series_id,
            )
            .exists()
        )

    def _eligible(self, principal_id: str, publication_ids: Iterable[str]) -> frozenset[str]:
        """The named publications whose stored status is complete/partial, not intake."""
        named = sorted(set(publication_ids))
        if not named:
            return frozenset()
        pubs = schedule_publications
        found = self._connection.execute(
            select(pubs.c.publication_id).where(
                _mine(pubs, principal_id),
                pubs.c.publication_id.in_(named),
                pubs.c.status.in_(_ELIGIBLE),
                self._not_intake(principal_id),
            )
        ).scalars()
        return frozenset(str(value) for value in found)

    # ---- scenarios and versions ---------------------------------------------------------

    def snapshot_source(
        self, principal_id: str, publication_id: str
    ) -> ScenarioSnapshotSource | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        pubs = schedule_publications
        found = (
            self._connection.execute(
                select(pubs).where(
                    _mine(pubs, principal_id),
                    pubs.c.publication_id == publication_id,
                    pubs.c.status.in_(_ELIGIBLE),
                    self._not_intake(principal_id),
                )
            )
            .mappings()
            .one_or_none()
        )
        if found is None or found["data_date"] is None:
            return None
        rows = self._schedules().list_activity_rows(
            principal_id,
            publication_id,
            row_type=None,
            hierarchy_prefix=None,
            start_range=(None, None),
            finish_range=(None, None),
            after=None,
            limit=MAX_ACTIVITIES + 1,
        )
        return ScenarioSnapshotSource(
            publication_id=publication_id,
            project_id=found["project_id"],
            series_id=found["series_id"],
            data_date=found["data_date"],
            rows=rows,
        )

    def _require_effective_baseline(
        self, principal_id: str, baseline_id: str, publication: RowMapping
    ) -> None:
        """Section 14.8.2 (RR1-F04): re-read under J that the origin Baseline is effective."""
        baselines = schedule_baselines
        found = self._connection.execute(
            select(baselines.c.baseline_id).where(
                _mine(baselines, principal_id),
                baselines.c.baseline_id == baseline_id,
                baselines.c.publication_id == publication["publication_id"],
            )
        ).scalar_one_or_none()
        if found is None:
            raise PlaneSubjectAbsentError()
        events = schedule_baseline_events
        actions = {
            str(action)
            for action in self._connection.execute(
                select(events.c.action).where(
                    _mine(events, principal_id), events.c.baseline_id == baseline_id
                )
            ).scalars()
        }
        if BaselineAction.APPROVE.value not in actions or BaselineAction.REVOKE.value in actions:
            raise BaselineWriteRefusedError(BaselineRefusal.CONFLICT_BASELINE_ID)
        if publication["status"] not in _ELIGIBLE:
            raise BaselineWriteRefusedError(BaselineRefusal.CONFLICT_STATUS)

    def _insert_scenario_row(
        self,
        principal_id: str,
        *,
        project_id: str,
        series_id: str,
        scenario: NewScenario,
        origin_kind: str,
        origin_version_id: str | None,
        writer: PlaneProvenance,
    ) -> str:
        scenario_id = issue_identifier(IdKind.SCHEDULE_SCENARIO)
        self._connection.execute(
            insert(schedule_scenarios).values(
                _bound(
                    schedule_scenarios,
                    principal_id,
                    {
                        "scenario_id": scenario_id,
                        "project_id": project_id,
                        "series_id": series_id,
                        "name": scenario.name,
                        "description": scenario.description,
                        "origin_kind": origin_kind,
                        "origin_publication_id": scenario.origin_publication_id,
                        "origin_baseline_id": scenario.origin_baseline_id,
                        "origin_version_id": origin_version_id,
                        **_provenance_values(writer),
                    },
                )
            )
        )
        return scenario_id

    def _insert_version(
        self,
        principal_id: str,
        *,
        scenario_id: str,
        project_id: str,
        series_id: str,
        version_no: int,
        parent_version_id: str | None,
        version: NewScenarioVersion,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion:
        change = version.change_set
        snapshot = version.snapshot
        values: dict[str, object] = {
            "version_id": issue_identifier(IdKind.SCHEDULE_SCENARIO_VERSION),
            "project_id": project_id,
            "series_id": series_id,
            "scenario_id": scenario_id,
            "version_no": version_no,
            "parent_version_id": parent_version_id,
            "label": version.label.value,
            "note": version.note,
            "content_zlib": version.content_zlib,
            "content_sha256": version.content_sha256,
            "content_size_bytes": version.content_size_bytes,
            "activity_count": version.activity_count,
            "relationship_count": version.relationship_count,
            "calendar_count": version.calendar_count,
            "distribution_spec_sha256": version.distribution_spec_sha256,
            **_provenance_values(writer),
        }
        if change is not None:
            values.update(
                change_set_zlib=change.zlib,
                change_set_sha256=change.sha256,
                change_set_size_bytes=change.size_bytes,
                change_set_op_count=change.op_count,
                ops_applied=change.ops_applied,
                relationships_removed=change.relationships_removed,
                content_changed=change.content_changed,
            )
        if snapshot is not None:
            values.update(
                snapshot_activities=snapshot.activities,
                snapshot_milestones=snapshot.milestones,
                snapshot_durations_quantized=snapshot.durations_quantized,
                snapshot_durations_out_of_range=snapshot.durations_out_of_range,
                snapshot_original_missing=snapshot.original_missing,
                snapshot_remaining_missing=snapshot.remaining_missing,
            )
        versions = schedule_scenario_versions
        stored = (
            self._connection.execute(
                insert(versions)
                .values(_bound(versions, principal_id, values))
                .returning(*_version_columns())
            )
            .mappings()
            .one()
        )
        return _to_version(stored)

    def insert_scenario(
        self,
        principal_id: str,
        scenario: NewScenario,
        first_version: NewScenarioVersion,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        publication_id = scenario.origin_publication_id
        if publication_id is None:
            raise ValueError("a scenario from a publication names its publication")
        if first_version.snapshot is None or first_version.change_set is not None:
            raise ValueError("version 1 of a publication scenario carries its snapshot only")
        publication = self._publication(principal_id, publication_id)
        if publication is None:
            raise PlaneSubjectAbsentError()
        if scenario.origin_baseline_id is not None:
            lock_project(self._connection, principal_id, publication["project_id"])
            self._require_effective_baseline(principal_id, scenario.origin_baseline_id, publication)
        scenario_id = self._insert_scenario_row(
            principal_id,
            project_id=publication["project_id"],
            series_id=publication["series_id"],
            scenario=scenario,
            origin_kind=_PUBLICATION_ORIGIN,
            origin_version_id=None,
            writer=writer,
        )
        return self._insert_version(
            principal_id,
            scenario_id=scenario_id,
            project_id=publication["project_id"],
            series_id=publication["series_id"],
            version_no=1,
            parent_version_id=None,
            version=first_version,
            writer=writer,
        )

    def _version_row(self, principal_id: str, version_id: str) -> RowMapping | None:
        versions = schedule_scenario_versions
        return (
            self._connection.execute(
                select(*_version_columns()).where(
                    _mine(versions, principal_id), versions.c.version_id == version_id
                )
            )
            .mappings()
            .one_or_none()
        )

    def fork_scenario(
        self,
        principal_id: str,
        scenario: NewScenario,
        source_version_id: str,
        label: VersionLabel,
        note: str | None,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if scenario.origin_publication_id is not None or scenario.origin_baseline_id is not None:
            raise ValueError("a fork names its source version only")
        source = self._version_row(principal_id, source_version_id)
        if source is None:
            raise PlaneSubjectAbsentError()
        scenario_id = self._insert_scenario_row(
            principal_id,
            project_id=source["project_id"],
            series_id=source["series_id"],
            scenario=scenario,
            origin_kind=_VERSION_ORIGIN,
            origin_version_id=source_version_id,
            writer=writer,
        )
        versions = schedule_scenario_versions
        version_id = issue_identifier(IdKind.SCHEDULE_SCENARIO_VERSION)
        provenance = _provenance_values(writer)
        # Section 14.8.2: `INSERT ... SELECT`, so the copy is byte for byte and never
        # decompressed; the partition column is the `_mine` source row's own.
        copied = select(
            literal(version_id, Text),
            versions.c.principal_id,
            versions.c.project_id,
            versions.c.series_id,
            literal(scenario_id, Text),
            literal(1, Integer),
            literal(label.value, Text),
            literal(note, Text) if note is not None else null(),
            versions.c.content_zlib,
            versions.c.content_sha256,
            versions.c.content_size_bytes,
            versions.c.activity_count,
            versions.c.relationship_count,
            versions.c.calendar_count,
            versions.c.distribution_spec_sha256,
            *(literal(value) if value is not None else null() for value in provenance.values()),
        ).where(_mine(versions, principal_id), versions.c.version_id == source_version_id)
        self._connection.execute(
            insert(versions).from_select(
                [
                    "version_id",
                    "principal_id",
                    "project_id",
                    "series_id",
                    "scenario_id",
                    "version_no",
                    "label",
                    "note",
                    "content_zlib",
                    "content_sha256",
                    "content_size_bytes",
                    "activity_count",
                    "relationship_count",
                    "calendar_count",
                    "distribution_spec_sha256",
                    *provenance,
                ],
                copied,
            )
        )
        stored = self._version_row(principal_id, version_id)
        if stored is None:
            raise ScenarioIntegrityError("fork_not_copied")
        return _to_version(stored)

    def head_version(self, principal_id: str, scenario_id: str) -> StoredScenarioVersion | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        versions = schedule_scenario_versions
        found = (
            self._connection.execute(
                select(*_version_columns())
                .where(_mine(versions, principal_id), versions.c.scenario_id == scenario_id)
                .order_by(versions.c.version_no.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_version(found)

    def version_by_number(
        self, principal_id: str, scenario_id: str, version_no: int
    ) -> StoredScenarioVersion | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        versions = schedule_scenario_versions
        found = (
            self._connection.execute(
                select(*_version_columns()).where(
                    _mine(versions, principal_id),
                    versions.c.scenario_id == scenario_id,
                    versions.c.version_no == version_no,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_version(found)

    def append_version(
        self,
        principal_id: str,
        scenario_id: str,
        expected_head_version_no: int,
        version: NewScenarioVersion,
        writer: PlaneProvenance,
    ) -> StoredScenarioVersion:
        if version.change_set is None or version.snapshot is not None:
            raise ValueError("an appended version carries its change set and no snapshot")
        head = self.head_version(principal_id, scenario_id)
        _seam("head_read")
        if head is None:
            raise PlaneSubjectAbsentError()
        if head.version_no != expected_head_version_no:
            raise ScenarioHeadMovedError(head.version_no)
        return self._insert_version(
            principal_id,
            scenario_id=scenario_id,
            project_id=head.project_id,
            series_id=head.series_id,
            version_no=expected_head_version_no + 1,
            parent_version_id=head.version_id,
            version=version,
            writer=writer,
        )

    def get_scenario(self, principal_id: str, scenario_id: str) -> StoredScenario | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        scenarios = schedule_scenarios
        found = (
            self._connection.execute(
                select(scenarios).where(
                    _mine(scenarios, principal_id), scenarios.c.scenario_id == scenario_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_scenario(found)

    def get_version(self, principal_id: str, version_id: str) -> StoredScenarioVersion | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        found = self._version_row(principal_id, version_id)
        return None if found is None else _to_version(found)

    def load_content(self, principal_id: str, version_id: str) -> VerifiedScenarioContent | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        versions = schedule_scenario_versions
        found = self._connection.execute(
            select(
                versions.c.content_zlib, versions.c.content_sha256, versions.c.content_size_bytes
            ).where(_mine(versions, principal_id), versions.c.version_id == version_id)
        ).one_or_none()
        if found is None:
            return None
        canonical = verified_canonical(
            bytes(found.content_zlib),
            kind="content",
            schema=CONTENT_SCHEMA,
            sha256=found.content_sha256,
            size_bytes=found.content_size_bytes,
            limit=MAX_CONTENT_BYTES,
        )
        try:
            content = content_from_object(json.loads(canonical))
        except (ValueError, ScenarioDecodeError):
            raise ScenarioIntegrityError("content_decode") from None
        if content_problem(content) is not None:
            raise ScenarioIntegrityError("content_decode")
        return VerifiedScenarioContent(content=content, canonical=canonical, size=len(canonical))

    def load_change_set(self, principal_id: str, version_id: str) -> VerifiedDocument | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        versions = schedule_scenario_versions
        found = self._connection.execute(
            select(
                versions.c.change_set_zlib,
                versions.c.change_set_sha256,
                versions.c.change_set_size_bytes,
            ).where(_mine(versions, principal_id), versions.c.version_id == version_id)
        ).one_or_none()
        if found is None or found.change_set_zlib is None:
            return None
        document, canonical = verified_document(
            bytes(found.change_set_zlib),
            kind="change_set",
            schema=CHANGE_SET_SCHEMA,
            sha256=found.change_set_sha256,
            size_bytes=found.change_set_size_bytes,
            limit=MAX_CHANGE_SET_BYTES,
        )
        return VerifiedDocument(document=document, canonical=canonical)

    # ---- CPM runs -----------------------------------------------------------------------

    def get_cpm_run(
        self, principal_id: str, version_id: str, engine_version: str
    ) -> StoredCpmRun | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        runs = schedule_cpm_runs
        found = (
            self._connection.execute(
                select(*_run_columns()).where(
                    _mine(runs, principal_id),
                    runs.c.version_id == version_id,
                    runs.c.engine_version == engine_version,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_run(found)

    def get_cpm_run_by_id(self, principal_id: str, cpm_run_id: str) -> StoredCpmRun | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        runs = schedule_cpm_runs
        found = (
            self._connection.execute(
                select(*_run_columns()).where(
                    _mine(runs, principal_id), runs.c.cpm_run_id == cpm_run_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_run(found)

    def insert_cpm_run(
        self, principal_id: str, run: NewCpmRun, writer: PlaneProvenance
    ) -> tuple[StoredCpmRun, bool]:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        runs = schedule_cpm_runs
        inserted = (
            self._connection.execute(
                pg_insert(runs)
                .values(
                    _bound(
                        runs,
                        principal_id,
                        {
                            "cpm_run_id": issue_identifier(IdKind.SCHEDULE_CPM_RUN),
                            "version_id": run.version_id,
                            "engine_version": run.engine_version,
                            "input_content_sha256": run.input_content_sha256,
                            "status": run.status.value,
                            "result_zlib": run.result_zlib,
                            "result_sha256": run.result_sha256,
                            "result_size_bytes": run.result_size_bytes,
                            "activity_count": run.activity_count,
                            "relationship_count": run.relationship_count,
                            "project_finish": run.project_finish,
                            **_provenance_values(writer),
                        },
                    )
                )
                .on_conflict_do_nothing(
                    index_elements=[runs.c.principal_id, runs.c.version_id, runs.c.engine_version]
                )
                .returning(*_run_columns())
            )
            .mappings()
            .one_or_none()
        )
        if inserted is not None:
            return _to_run(inserted), True
        existing = self.get_cpm_run(principal_id, run.version_id, run.engine_version)
        if existing is None:
            raise ScenarioIntegrityError("cpm_run_race_unresolved")
        return existing, False

    def load_cpm_result(self, principal_id: str, cpm_run_id: str) -> VerifiedDocument | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        runs = schedule_cpm_runs
        found = self._connection.execute(
            select(runs.c.result_zlib, runs.c.result_sha256, runs.c.result_size_bytes).where(
                _mine(runs, principal_id), runs.c.cpm_run_id == cpm_run_id
            )
        ).one_or_none()
        if found is None:
            return None
        document, canonical = verified_document(
            bytes(found.result_zlib),
            kind="result",
            schema=RESULT_SCHEMA,
            sha256=found.result_sha256,
            size_bytes=found.result_size_bytes,
            limit=MAX_CPM_RESULT_BYTES,
        )
        return VerifiedDocument(document=document, canonical=canonical)

    # ---- outputs ------------------------------------------------------------------------

    def insert_output(
        self, principal_id: str, output: NewScenarioOutput, writer: PlaneProvenance
    ) -> StoredScenarioOutput:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        outputs = schedule_scenario_outputs
        stored = (
            self._connection.execute(
                insert(outputs)
                .values(
                    _bound(
                        outputs,
                        principal_id,
                        {
                            "output_id": issue_identifier(IdKind.SCHEDULE_SCENARIO_OUTPUT),
                            "version_id": output.version_id,
                            "content_sha256": output.content_sha256,
                            "base_cpm_run_id": output.base_cpm_run_id,
                            "kind": output.kind.value,
                            "iterations": output.iterations,
                            "distribution_spec_sha256": output.distribution_spec_sha256,
                            "payload_zlib": output.payload_zlib,
                            "payload_sha256": output.payload_sha256,
                            "payload_size_bytes": output.payload_size_bytes,
                            **_provenance_values(writer),
                        },
                    )
                )
                .returning(*_output_columns())
            )
            .mappings()
            .one()
        )
        return _to_output(stored)

    def get_output(self, principal_id: str, output_id: str) -> StoredScenarioOutput | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        outputs = schedule_scenario_outputs
        found = (
            self._connection.execute(
                select(*_output_columns()).where(
                    _mine(outputs, principal_id), outputs.c.output_id == output_id
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_output(found)

    def load_output(self, principal_id: str, output_id: str) -> VerifiedDocument | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        outputs = schedule_scenario_outputs
        found = self._connection.execute(
            select(
                outputs.c.payload_zlib, outputs.c.payload_sha256, outputs.c.payload_size_bytes
            ).where(_mine(outputs, principal_id), outputs.c.output_id == output_id)
        ).one_or_none()
        if found is None:
            return None
        document, canonical = verified_document(
            bytes(found.payload_zlib),
            kind="output",
            schema=OUTPUT_SCHEMA,
            sha256=found.payload_sha256,
            size_bytes=found.payload_size_bytes,
            limit=MAX_OUTPUT_BYTES,
        )
        return VerifiedDocument(document=document, canonical=canonical)

    # ---- baselines and governing (section 14.8.5) ---------------------------------------

    def _chain_rows(
        self, principal_id: str, project_id: str
    ) -> tuple[list[RowMapping], list[RowMapping]]:
        events = schedule_baseline_events
        governing = schedule_governing_events
        event_rows = list(
            self._connection.execute(
                select(events)
                .where(_mine(events, principal_id), events.c.project_id == project_id)
                .order_by(events.c.seq)
            ).mappings()
        )
        governing_rows = list(
            self._connection.execute(
                select(governing)
                .where(_mine(governing, principal_id), governing.c.project_id == project_id)
                .order_by(governing.c.seq)
            ).mappings()
        )
        return event_rows, governing_rows

    def baseline_chain(self, principal_id: str, project_id: str) -> BaselineChain:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        event_rows, governing_rows = self._chain_rows(principal_id, project_id)
        return BaselineChain(
            events=tuple(_to_event(row) for row in event_rows),
            governing=tuple(
                GoverningEvent(
                    seq=row["seq"], baseline_id=row["baseline_id"], recorded_at=row["recorded_at"]
                )
                for row in governing_rows
            ),
        )

    def governing_as_of(
        self, principal_id: str, project_id: str, as_of: datetime | None
    ) -> str | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        governing = schedule_governing_events
        statement = select(governing.c.baseline_id).where(
            _mine(governing, principal_id), governing.c.project_id == project_id
        )
        if as_of is not None:
            statement = statement.where(governing.c.recorded_at <= as_of)
        found = self._connection.execute(
            statement.order_by(governing.c.seq.desc()).limit(1)
        ).scalar_one_or_none()
        return None if found is None else str(found)

    def _baseline_row(self, principal_id: str, baseline_id: str) -> RowMapping | None:
        baselines = schedule_baselines
        return (
            self._connection.execute(
                select(baselines).where(
                    _mine(baselines, principal_id), baselines.c.baseline_id == baseline_id
                )
            )
            .mappings()
            .one_or_none()
        )

    def _baseline_project(
        self, principal_id: str, request: BaselineRequest, project_id: str | None
    ) -> str:
        """Step 1: the Project, from the request's immutable subject, partitioned."""
        if isinstance(request, SetGoverningRequest):
            if project_id is None:
                raise ValueError("a governing write names its Project")
            if not self._schedules().owns_project(principal_id, project_id):
                raise PlaneSubjectAbsentError()
            return project_id
        publication_id = (
            request.publication_id
            if isinstance(request, ProposeRequest)
            or (isinstance(request, ApproveRequest) and request.baseline_id is None)
            else None
        )
        if publication_id is not None:
            publication = self._publication(principal_id, publication_id)
            if publication is None:
                raise PlaneSubjectAbsentError()
            return str(publication["project_id"])
        baseline_id = getattr(request, "baseline_id", None)
        baseline = None if baseline_id is None else self._baseline_row(principal_id, baseline_id)
        if baseline is None:
            raise PlaneSubjectAbsentError()
        return str(baseline["project_id"])

    def write_baseline(
        self,
        principal_id: str,
        request: BaselineRequest,
        *,
        reason: str,
        approval: ScheduleImportApproval | None,
        writer: PlaneProvenance,
        project_id: str | None = None,
    ) -> BaselineWritten:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        project = self._baseline_project(principal_id, request, project_id)
        lock_project(self._connection, principal_id, project)
        event_rows, governing_rows = self._chain_rows(principal_id, project)
        _seam("chain_read")
        plan = self._decide(principal_id, event_rows, governing_rows, request)
        return self._append(
            principal_id,
            project,
            event_rows,
            governing_rows,
            plan,
            request,
            reason=reason,
            approval=approval,
            writer=writer,
        )

    def _decide(
        self,
        principal_id: str,
        event_rows: Sequence[RowMapping],
        governing_rows: Sequence[RowMapping],
        request: BaselineRequest,
    ) -> BaselinePlan:
        events = [_to_event(row) for row in event_rows]
        governing = [
            GoverningEvent(
                seq=row["seq"], baseline_id=row["baseline_id"], recorded_at=row["recorded_at"]
            )
            for row in governing_rows
        ]
        named = {event.publication_id for event in events}
        publication_id = getattr(request, "publication_id", None)
        if publication_id is not None:
            named.add(publication_id)
        decided = decide_baseline_write(
            events,
            governing,
            request,
            eligible_publication_ids=self._eligible(principal_id, named),
        )
        if isinstance(decided, BaselineRefusal):
            raise BaselineWriteRefusedError(decided)
        return decided

    def _guarded(self, statement: Insert, trigger: str) -> None:
        """One backstopped insert: a lost race surfaces as `ScheduleBaselineRaceError`."""
        try:
            self._connection.execute(statement)
        except IntegrityError as error:
            state = _sqlstate(error)
            if state == _UNIQUE_VIOLATION:
                raise ScheduleBaselineRaceError(_constraint_name(error) or "unique") from None
            if state == _RESTRICT_VIOLATION:
                raise ScheduleBaselineRaceError(trigger) from None
            raise

    def _append(
        self,
        principal_id: str,
        project_id: str,
        event_rows: Sequence[RowMapping],
        governing_rows: Sequence[RowMapping],
        plan: BaselinePlan,
        request: BaselineRequest,
        *,
        reason: str,
        approval: ScheduleImportApproval | None,
        writer: PlaneProvenance,
    ) -> BaselineWritten:
        if plan.governing:
            return self._append_governing(
                principal_id, project_id, governing_rows, plan, reason=reason, writer=writer
            )
        if plan.action is None or plan.publication_id is None:
            raise ScenarioIntegrityError("baseline_plan_incomplete")
        baseline_id = plan.baseline_id
        if baseline_id is None:
            baseline_id = self._new_baseline(principal_id, plan.publication_id, request)
        values: dict[str, object] = {
            "event_id": issue_identifier(IdKind.SCHEDULE_BASELINE_EVENT),
            "project_id": project_id,
            "baseline_id": baseline_id,
            "publication_id": plan.publication_id,
            "action": plan.action.value,
            "seq": len(event_rows) + 1,
            "previous_event_id": event_rows[-1]["event_id"] if event_rows else None,
            "recorded_at": func.clock_timestamp(),
            "reason": reason,
            **_provenance_values(writer),
        }
        if isinstance(request, ProposeRequest):
            values.update(type=request.type.value, proposal_ordinal=plan.proposal_ordinal)
        elif isinstance(request, ApproveRequest):
            if approval is None:
                raise ValueError("an approval carries its approval reference")
            values.update(
                type=request.type.value,
                label=plan.label,
                approval_reference=approval.approval_reference,
                effective_from=request.effective_from,
                supersedes_baseline_id=request.supersedes_baseline_id,
                approved_at_import=request.at_import,
            )
        events = schedule_baseline_events
        self._guarded(insert(events).values(_bound(events, principal_id, values)), _G14)
        return BaselineWritten(
            baseline_id=baseline_id,
            event_id=str(values["event_id"]),
            label=plan.label if plan.action is BaselineAction.APPROVE else None,
            seq=int(str(values["seq"])),
        )

    def _new_baseline(
        self, principal_id: str, publication_id: str, request: BaselineRequest
    ) -> str:
        if not isinstance(request, ProposeRequest | ApproveRequest):
            raise ScenarioIntegrityError("baseline_plan_incomplete")
        publication = self._publication(principal_id, publication_id)
        if publication is None:
            raise PlaneSubjectAbsentError()
        baseline_id = issue_identifier(IdKind.SCHEDULE_BASELINE)
        baselines = schedule_baselines
        self._guarded(
            insert(baselines).values(
                _bound(
                    baselines,
                    principal_id,
                    {
                        "baseline_id": baseline_id,
                        "project_id": publication["project_id"],
                        "series_id": publication["series_id"],
                        "publication_id": publication_id,
                        "type": request.type.value,
                    },
                )
            ),
            _G12,
        )
        return baseline_id

    def _append_governing(
        self,
        principal_id: str,
        project_id: str,
        governing_rows: Sequence[RowMapping],
        plan: BaselinePlan,
        *,
        reason: str,
        writer: PlaneProvenance,
    ) -> BaselineWritten:
        if plan.baseline_id is None:
            raise ScenarioIntegrityError("baseline_plan_incomplete")
        governing = schedule_governing_events
        event_id = issue_identifier(IdKind.SCHEDULE_GOVERNING_EVENT)
        seq = len(governing_rows) + 1
        self._guarded(
            insert(governing).values(
                _bound(
                    governing,
                    principal_id,
                    {
                        "governing_event_id": event_id,
                        "project_id": project_id,
                        "baseline_id": plan.baseline_id,
                        "seq": seq,
                        "previous_governing_event_id": (
                            governing_rows[-1]["governing_event_id"] if governing_rows else None
                        ),
                        "recorded_at": func.clock_timestamp(),
                        "reason": reason,
                        **_provenance_values(writer),
                    },
                )
            ),
            _G15,
        )
        return BaselineWritten(
            baseline_id=plan.baseline_id, event_id=event_id, label=None, seq=seq, governing=True
        )

    def record_import_approval(
        self,
        principal_id: str,
        *,
        project_id: str,
        publication_id: str,
        baseline_type: BaselineType,
        approval: ScheduleImportApproval,
        operator_channel: str,
    ) -> BaselineWritten:
        """Section 14.8.5: the approval of a publication this transaction just admitted.

        A refusal is impossible by construction; any refusal or backstop error
        here is an integrity error, never an admission refusal (RR1-F04).
        """
        writer = PlaneProvenance(
            authority_class="local_operator",
            decision_channel=operator_channel,
            asserting_client_id=None,
            acceptance_basis="user_confirmed",
        )
        request = ApproveRequest(
            type=baseline_type,
            effective_from=approval.effective_from,
            publication_id=publication_id,
            at_import=True,
        )
        lock_project(self._connection, principal_id, project_id)
        event_rows, governing_rows = self._chain_rows(principal_id, project_id)
        try:
            plan = self._decide(principal_id, event_rows, governing_rows, request)
            return self._append(
                principal_id,
                project_id,
                event_rows,
                governing_rows,
                plan,
                request,
                reason=approval.reason,
                approval=approval,
                writer=writer,
            )
        except (BaselineWriteRefusedError, ScheduleBaselineRaceError, IntegrityError):
            raise ScheduleIntegrityError("import_approval") from None

    def stored_import_approval(
        self, principal_id: str, publication_id: str
    ) -> tuple[str, str, date, str] | None:
        """The publication's `approve` event as `(type, reference, effective_from, reason)`."""
        events = schedule_baseline_events
        found = self._connection.execute(
            select(
                events.c.type, events.c.approval_reference, events.c.effective_from, events.c.reason
            ).where(
                _mine(events, principal_id),
                events.c.publication_id == publication_id,
                events.c.action == BaselineAction.APPROVE.value,
            )
        ).one_or_none()
        if found is None:
            return None
        return (
            str(found.type),
            str(found.approval_reference),
            found.effective_from,
            str(found.reason),
        )

    # ---- the worker's series-match hook (section 14.8.7) --------------------------------

    def get_match_decision(
        self, principal_id: str, intake_publication_id: str
    ) -> SeriesMatchRecord | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        decisions = schedule_series_match_decisions
        found = (
            self._connection.execute(
                select(decisions).where(
                    _mine(decisions, principal_id),
                    decisions.c.intake_publication_id == intake_publication_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if found is None else _to_decision(found)

    def finalize_intake(
        self, principal_id: str, publication_id: str, *, plane_effective: bool
    ) -> SeriesMatchRecord | SeriesMatchUndecided | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        intake = schedule_intake_series
        marked = (
            self._connection.execute(
                select(intake).where(
                    _mine(intake, principal_id), intake.c.publication_id == publication_id
                )
            )
            .mappings()
            .one_or_none()
        )
        if marked is None:
            return None  # step 1: not an intake publication; no lock, no further read
        # Step 2 (R9-F01, RR1-F01, RR2-F02): steps 3-10 inside the outer savepoint.
        # Only transient errors propagate; every other `Exception` rolls back to the
        # savepoint and the finalization commits with no decision. A failed rollback
        # of the savepoint itself replaces `_HookDefectError` and propagates.
        try:
            with self._connection.begin_nested():
                try:
                    return self._decide_intake(principal_id, marked, plane_effective)
                except _TRANSIENT:
                    raise
                except Exception as defect:
                    raise _HookDefectError(_defect_code(defect)) from defect
        except _HookDefectError as defect:
            return SeriesMatchUndecided(defect.code)

    def _decide_intake(
        self, principal_id: str, marked: RowMapping, plane_effective: bool
    ) -> SeriesMatchRecord:
        project_id = str(marked["project_id"])
        lock_project(self._connection, principal_id, project_id)
        existing = self.get_match_decision(principal_id, marked["publication_id"])
        if existing is not None:
            return existing
        publication = self._publication(principal_id, marked["publication_id"])
        if publication is None:
            raise ScenarioIntegrityError("intake_publication_not_found")
        if publication["status"] not in _ELIGIBLE:
            return self._record(
                principal_id, marked, MatchDecision(MatchOutcome.NOT_ELIGIBLE, None, 0)
            )
        # Step 5 (R9-F07): the bound on the raw count, before any skip or row read.
        series = schedule_series
        raw = self._connection.execute(
            select(series.c.series_id, series.c.created_at)
            .where(
                _mine(series, principal_id),
                series.c.project_id == project_id,
                ~(
                    select(schedule_intake_series.c.series_id)
                    .where(
                        _mine(schedule_intake_series, principal_id),
                        matching_partition_criterion(schedule_intake_series, series),
                        schedule_intake_series.c.series_id == series.c.series_id,
                    )
                    .exists()
                ),
            )
            .order_by(series.c.created_at, series.c.series_id)
            .limit(MAX_MATCH_CANDIDATES + 1)
        ).all()
        if len(raw) > MAX_MATCH_CANDIDATES:
            return self._record(
                principal_id,
                marked,
                MatchDecision(
                    MatchOutcome.AMBIGUOUS,
                    MatchReason.CANDIDATE_BOUND,
                    int(publication["activity_count"] or 0),
                ),
            )
        data_date = publication["data_date"]
        if data_date is None:
            raise ScenarioIntegrityError("eligible_without_data_date")
        incoming = MatchIncoming(
            activities=self._activity_names(principal_id, marked["publication_id"]),
            data_date=data_date,
            title=publication["published_schedule_title"],
        )
        candidates = self._candidates(
            principal_id, project_id, raw, publication["source_version_id"]
        )
        name_state = self._new_series_name(principal_id, project_id, marked)
        _seam("new_series_name_read")
        decision = match_series(incoming, candidates, new_series_name=name_state)
        if decision.outcome not in (MatchOutcome.MATCHED, MatchOutcome.CREATED):
            return self._record(principal_id, marked, decision)
        if not plane_effective:
            # Step 9, S6-O15: evidence only; a skipped `created` names no Series.
            return self._record(
                principal_id,
                marked,
                decision,
                target_series_id=(
                    decision.series_id if decision.outcome is MatchOutcome.MATCHED else None
                ),
                admission_skipped=MatchAdmissionSkip.PLANE_DISABLED.value,
            )
        return self._admit_matched(principal_id, marked, publication, decision)

    def _activity_names(self, principal_id: str, publication_id: str) -> dict[str, str]:
        """The accepted run's published Activity ID -> normalized name (at most 25,000)."""
        rows = schedule_rows
        pubs = schedule_publications
        found = self._connection.execute(
            select(rows.c.published_activity_id, rows.c.activity_name)
            .select_from(
                rows.join(
                    pubs,
                    and_(
                        pubs.c.publication_id == rows.c.publication_id,
                        pubs.c.accepted_parser_run_id == rows.c.parser_run_id,
                    ),
                )
            )
            .where(
                _mine(rows, principal_id),
                _mine(pubs, principal_id),
                matching_partition_criterion(rows, pubs),
                pubs.c.publication_id == publication_id,
                pubs.c.status.in_(_ELIGIBLE),
                rows.c.row_type.in_(_LINKABLE),
            )
            .limit(MAX_ACTIVITIES + 1)
        ).all()
        if len(found) > MAX_ACTIVITIES:
            raise ScenarioIntegrityError("match_rows_bound")
        return {
            str(row.published_activity_id): normalize_display_text(str(row.activity_name or ""))
            for row in found
        }

    def _effective_baseline_publications(
        self, principal_id: str, project_id: str
    ) -> frozenset[str]:
        event_rows, _ = self._chain_rows(principal_id, project_id)
        events = [_to_event(row) for row in event_rows]
        views = baseline_status(
            events,
            eligible_publication_ids=self._eligible(
                principal_id, {event.publication_id for event in events}
            ),
        )
        return frozenset(
            view.publication_id for view in views.values() if view.status is BaselineStatus.APPROVED
        )

    def _candidates(
        self,
        principal_id: str,
        project_id: str,
        raw: Sequence[Any],
        source_version_id: str,
    ) -> list[SeriesCandidate]:
        """Step 6: per Series its current (or newest eligible) publication and ID map."""
        baselines = self._effective_baseline_publications(principal_id, project_id)
        pubs = schedule_publications
        found: list[SeriesCandidate] = []
        for series_id, created_at in raw:
            rows = self._connection.execute(
                select(
                    pubs.c.publication_id,
                    pubs.c.status,
                    pubs.c.data_date,
                    pubs.c.admitted_at,
                    pubs.c.supersedes_publication_id,
                    pubs.c.source_version_id,
                    pubs.c.published_schedule_title,
                ).where(_mine(pubs, principal_id), pubs.c.series_id == series_id)
            ).all()
            currency = [
                CurrencyPublication(
                    publication_id=row.publication_id,
                    status=SchedulePublicationStatus(row.status),
                    data_date=row.data_date,
                    admitted_at=row.admitted_at,
                    supersedes_publication_id=row.supersedes_publication_id,
                )
                for row in rows
            ]
            chosen = current_standard_update(currency, baselines).publication_id
            if chosen is None:
                eligible = [item for item in currency if item.eligible]
                if not eligible:
                    continue
                chosen = max(eligible, key=CurrencyPublication.order_key).publication_id
            row = next(item for item in rows if item.publication_id == chosen)
            holding = next(
                (
                    item.publication_id
                    for item in rows
                    if item.source_version_id == source_version_id
                ),
                None,
            )
            found.append(
                SeriesCandidate(
                    series_id=series_id,
                    created_at=created_at,
                    publication_id=chosen,
                    data_date=row.data_date,
                    activities=self._activity_names(principal_id, chosen),
                    title=row.published_schedule_title,
                    holds_source_version=holding is not None,
                    existing_publication_id=holding,
                )
            )
        return found

    def _new_series_name(
        self, principal_id: str, project_id: str, marked: RowMapping
    ) -> NewSeriesName:
        """Step 7: `TAKEN`/`FREE` by a `name_key` read under J (I8's resolution)."""
        key = marked["series_name_if_new_key"]
        if key is None:
            return NewSeriesName.ABSENT
        series = schedule_series
        taken = self._connection.execute(
            select(series.c.series_id).where(
                _mine(series, principal_id),
                series.c.project_id == project_id,
                series.c.name_key == key,
            )
        ).first()
        return NewSeriesName.FREE if taken is None else NewSeriesName.TAKEN

    def _admit_matched(
        self,
        principal_id: str,
        marked: RowMapping,
        publication: RowMapping,
        decision: MatchDecision,
    ) -> SeriesMatchRecord:
        """Step 9: the second admission in an inner savepoint."""
        decision_id = issue_identifier(IdKind.SCHEDULE_SERIES_MATCH)
        matched = decision.outcome is MatchOutcome.MATCHED
        new_name = marked["series_name_if_new"]
        request = ScheduleImportRequest(
            project_id=str(marked["project_id"]),
            series_id=decision.series_id if matched else None,
            series_name=None if matched else normalize_series_name(str(new_name)),
            enrollment_id=publication["enrollment_id"],
            source_object_id=publication["source_object_id"],
            source_version_id=publication["source_version_id"],
            publication_role=SchedulePublicationRole.UPDATE,
            baseline_kind=None,
            expected_data_date=publication["expected_data_date"],
            supersedes_publication_id=None,
            idempotency_key=second_admission_key(decision_id),
            match_decision_id=decision_id,
        )
        digest = schedule_import_request_digest(principal_id, request)
        refused_target = decision.series_id if matched else None
        try:
            with self._connection.begin_nested():
                admission = self._schedules().admit_publication(principal_id, request, digest)
                if not matched and admission.series_created is not True:
                    raise _NameRacedError()
        except ScheduleAdmissionRejectedError as refused:
            return self._record(
                principal_id,
                marked,
                decision,
                outcome=MatchOutcome.ADMISSION_REFUSED,
                target_series_id=refused_target,
                admission_refusal=refused.reason.value,
                decision_id=decision_id,
            )
        except IntegrityError:
            return self._record(
                principal_id,
                marked,
                decision,
                outcome=MatchOutcome.ADMISSION_REFUSED,
                target_series_id=refused_target,
                admission_refusal=MATCH_INTEGRITY_REFUSAL,
                decision_id=decision_id,
            )
        except _NameRacedError:
            return self._record(
                principal_id,
                marked,
                decision,
                outcome=MatchOutcome.AMBIGUOUS,
                reason=MatchReason.NAME_CONFLICT,
                decision_id=decision_id,
            )
        return self._record(
            principal_id,
            marked,
            decision,
            target_series_id=admission.series.series_id,
            resulting_publication_id=admission.publication.publication_id,
            decision_id=decision_id,
        )

    def _record(
        self,
        principal_id: str,
        marked: RowMapping,
        decision: MatchDecision,
        *,
        outcome: MatchOutcome | None = None,
        reason: MatchReason | None = None,
        target_series_id: str | None = None,
        resulting_publication_id: str | None = None,
        admission_refusal: str | None = None,
        admission_skipped: str | None = None,
        decision_id: str | None = None,
    ) -> SeriesMatchRecord:
        """Step 10: the one decision row of this intake publication."""
        final = outcome or decision.outcome
        if final is MatchOutcome.ALREADY_PRESENT:
            target_series_id = decision.series_id
            resulting_publication_id = decision.existing_publication_id
        if outcome is None:
            reason = decision.reason
        _seam("decision")
        decisions = schedule_series_match_decisions
        stored = (
            self._connection.execute(
                insert(decisions)
                .values(
                    _bound(
                        decisions,
                        principal_id,
                        {
                            "decision_id": decision_id
                            or issue_identifier(IdKind.SCHEDULE_SERIES_MATCH),
                            "project_id": marked["project_id"],
                            "intake_series_id": marked["series_id"],
                            "intake_publication_id": marked["publication_id"],
                            "outcome": final.value,
                            "reason": None if reason is None else reason.value,
                            "threshold_version": decision.threshold_version,
                            "incoming_id_count": decision.incoming_id_count,
                            "candidates": [_candidate_object(item) for item in decision.candidates],
                            "target_series_id": target_series_id,
                            "resulting_publication_id": resulting_publication_id,
                            "admission_refusal": admission_refusal,
                            "admission_skipped": admission_skipped,
                        },
                    )
                )
                .returning(*schedule_series_match_decisions.c)
            )
            .mappings()
            .one()
        )
        return _to_decision(stored)


def _version_columns() -> tuple[Any, ...]:
    """Every version column but the stored compressed bytes."""
    versions = schedule_scenario_versions
    return tuple(
        column for column in versions.c if column.name not in ("content_zlib", "change_set_zlib")
    )


def _run_columns() -> tuple[Any, ...]:
    return tuple(column for column in schedule_cpm_runs.c if column.name != "result_zlib")


def _output_columns() -> tuple[Any, ...]:
    return tuple(column for column in schedule_scenario_outputs.c if column.name != "payload_zlib")


# ---- the S5 admission's plane functions (section 14.8.5) ------------------------------


def record_import_approval(
    connection: Connection,
    principal_id: str,
    *,
    project_id: str,
    publication_id: str,
    baseline_type: BaselineType,
    approval: ScheduleImportApproval,
    operator_channel: str,
) -> BaselineWritten:
    """The import-time Baseline and its `approve` event, in the admission's transaction."""
    return SqlScenarioRepository(connection).record_import_approval(
        principal_id,
        project_id=project_id,
        publication_id=publication_id,
        baseline_type=baseline_type,
        approval=approval,
        operator_channel=operator_channel,
    )


def stored_import_approval(
    connection: Connection, principal_id: str, publication_id: str
) -> tuple[str, str, date, str] | None:
    """A role-`baseline` replay's comparison fields (section 14.8.5)."""
    return SqlScenarioRepository(connection).stored_import_approval(principal_id, publication_id)


class SqlAlchemyScenarioUnitOfWork(ScenarioUnitOfWork):
    """One PostgreSQL transaction over the plane tables and the S5 tables.

    The `SqlAlchemyScheduleUnitOfWork` shape: the unit of work owns
    `engine.begin()`, refuses re-entry, and hands out repositories on that
    connection that never commit. Isolation is the engine default, READ
    COMMITTED (RR2-F03): every count and head is read in a statement after the
    lock that serializes it.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._context: AbstractContextManager[Connection] | None = None
        self._connection: Connection | None = None

    def __enter__(self) -> ScenarioUnitOfWork:
        if self._context is not None:
            raise RuntimeError("this unit of work is already inside a transaction")
        context = self._engine.begin()
        self._connection = context.__enter__()
        self._context = context
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        context = self._context
        self._context = None
        self._connection = None
        if context is not None:
            context.__exit__(exc_type, exc, traceback)

    def _require(self) -> Connection:
        connection = self._connection
        if connection is None:
            raise RuntimeError("this unit of work is not inside a transaction")
        return connection

    @property
    def scenarios(self) -> ScenarioRepository:
        return SqlScenarioRepository(self._require())

    @property
    def schedules(self) -> ScheduleRepository:
        return _s5.SqlScheduleRepository(self._require())
