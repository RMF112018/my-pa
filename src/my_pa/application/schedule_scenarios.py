"""Schedule Scenarios S6-3: the 26 plane capabilities' behaviour.

Contract: `docs/architecture/schedule-scenarios-contract.md` section 15 (and
sections 6, 8.3, 12 it amends). `ApplicationService` asks the plane switch
(`_scenario_plane`, `unsupported`) and hands the authorized request here;
everything below runs on the dedicated `ScenarioUnitOfWork` and the injected
`ScenarioCpmRunner`, which the composition root (`bootstrap/gateway.py`) builds.
This module imports no plane persistence module.

**Order of one plane write** (section 15.10):

1. the switch (in the service; policy already ran in `authorize`);
2. the grant re-check (`require_write_grant` / `require_read_grant`);
3. the authority: an operator write is `attested_lineage_authority` (`denied`
   otherwise); every write derives its `PlaneProvenance` from
   `lineage_write_provenance` -- no request field carries the class, channel,
   client or basis;
4. the refusal bound (client channels only), before any heavy document is
   decoded. Refusals in steps 1-4 and normalization refusals are never counted
   (S6-3-D13, R10-F11);
5. decode and compute outside any write transaction (S6-2-D14);
6. the write transaction: `lock_principal`, `reserve_request` (a replay or a
   conflict answers here), the client budgets and quotas, the insert and
   `complete_request`.

Every refusal from step 5 on, by a client channel, rolls its transaction back
and is recorded by `record_refusal` in a transaction of its own. The attested
operator is never budgeted, never quota-limited, never held to the hourly
CPM-units bound and never recorded as refused (R10-F04).

**Reads** are hidden-is-absent (another Principal's row is `not_found`), page
immutable rows or verified stored documents with an S5 `ScheduleCursor`
(a refused cursor is `invalid_request(cursor)`), label every answer
non-authoritative and non-reportable (only an effective Baseline is
`authoritative: true`), and withhold `asserting_client_id` from a remote reader.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Final

from my_pa.application.authorization import Authorization
from my_pa.application.commands import (
    ApproveScheduleBaseline,
    CompareScheduleBaseline,
    CreateScheduleCpmRun,
    CreateScheduleScenario,
    CreateScheduleScenarioVersion,
    ListScheduleBaselines,
    ListScheduleChanges,
    ListScheduleCpmRunActivities,
    ListScheduleScenarioActivities,
    ListScheduleScenarioChanges,
    ListScheduleScenarioOutputs,
    ListScheduleScenarioRelationships,
    ListScheduleScenarios,
    ListScheduleSeriesMatchDecisions,
    ProposeScheduleBaseline,
    ReadGoverningScheduleBaseline,
    ReadScheduleBaseline,
    ReadScheduleCpmRun,
    ReadScheduleScenario,
    ReadScheduleScenarioOutput,
    ReadScheduleScenarioVersion,
    ReadScheduleSeriesCurrent,
    RecordScheduleScenarioOutput,
    RejectScheduleBaseline,
    RevokeScheduleBaseline,
    SetGoverningScheduleBaseline,
    WithdrawScheduleBaseline,
)
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    RateLimitedError,
    SafeDetail,
)
from my_pa.application.lineage_authority import (
    attested_lineage_authority,
    lineage_write_provenance,
)
from my_pa.application.lineage_visibility import (
    require_read_grant,
    require_write_grant,
    withhold_client_ids,
)
from my_pa.application.schedules import ScheduleApplication
from my_pa.contracts.ports import (
    BaselineWriteRefusedError,
    BaselineWritten,
    CpmComputeBusyError,
    NewScenario,
    NewScenarioVersion,
    PlaneReservation,
    PlaneReservationOutcome,
    PlaneSubjectAbsentError,
    ScenarioCpmRunner,
    ScenarioHeadMovedError,
    ScenarioIntegrityError,
    ScenarioRecordBuilders,
    ScenarioRepository,
    ScenarioUnitOfWork,
    ScheduleBaselineRaceError,
    ScheduleUnitOfWork,
    SeriesMatchRecord,
    StoredBaseline,
    StoredBaselineEvent,
    StoredCpmRun,
    StoredScenario,
    StoredScenarioOutput,
    StoredScenarioVersion,
)
from my_pa.contracts.v1.disclosure import (
    Coverage,
    CoverageState,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    SourceReference,
    Truncation,
    Trust,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.identity.operation import Capability
from my_pa.domain.schedule import (
    ScheduleImportApproval,
    SchedulePublicationStatus,
    ScheduleSourceBinding,
    normalize_display_text,
)
from my_pa.domain.schedule.baselines import (
    ApproveRequest,
    BaselineRefusal,
    BaselineRequest,
    BaselineStatus,
    BaselineType,
    BaselineView,
    ProposeRequest,
    RejectRequest,
    RevokeRequest,
    SetGoverningRequest,
    WithdrawRequest,
    baseline_status,
)
from my_pa.domain.schedule.currency import current_standard_update
from my_pa.domain.schedule.cursor import (
    DEFAULT_SCHEDULE_PAGE_SIZE,
    ScheduleCursorError,
    ScheduleCursorOrder,
    SchedulePosition,
    decode_schedule_cursor,
    encode_schedule_cursor,
    schedule_cursor_binding,
)
from my_pa.domain.schedule.plane import (
    OPERATOR_PROPOSAL_BUCKET,
    PLANE_ATTESTED_DECISION_CHANNELS,
    PlaneProvenance,
    writer_bucket,
)
from my_pa.domain.schedule.scenario.canonical import (
    ScenarioDecodeError,
    activity_object,
    calendar_from_object,
    content_bytes,
    content_object,
    scenario_request_digest,
)
from my_pa.domain.schedule.scenario.changeset import (
    ChangeSetRefusal,
    apply_change_set,
)
from my_pa.domain.schedule.scenario.cpm import ENGINE_VERSION, CpmStatus
from my_pa.domain.schedule.scenario.model import (
    MAX_CONTENT_BYTES,
    ScenarioCalendar,
    ScenarioContent,
    VersionLabel,
)
from my_pa.domain.schedule.scenario.outputs import (
    BaseRunBinding,
    OutputBinding,
    OutputRefusal,
    validate_output,
)
from my_pa.domain.schedule.scenario.snapshot import (
    SnapshotRefusalError,
    SnapshotRefusalReason,
    snapshot_from_publication,
)

__all__ = [
    "BUCKET_BYTES_PER_DAY",
    "BUCKET_WRITES_PER_DAY",
    "BUCKET_WRITES_PER_HOUR",
    "CPM_UNITS_PER_HOUR",
    "MAX_OUTPUTS_PER_VERSION",
    "MAX_SCENARIOS_PER_PRINCIPAL",
    "MAX_VERSIONS_PER_PRINCIPAL",
    "PRINCIPAL_BYTES_PER_DAY",
    "PRINCIPAL_BYTES_TOTAL",
    "PRINCIPAL_WRITES_PER_DAY",
    "REFUSALS_PER_HOUR",
    "ScenarioAnswer",
    "ScenarioWriteBuilders",
    "ScheduleScenarioApplication",
]

# ---- section 8.3 / 2.10 bounds (client channels; the attested operator is exempt) ----

#: The 6 client writes together, per writer bucket and per Principal.
BUCKET_WRITES_PER_HOUR: Final = 120
BUCKET_WRITES_PER_DAY: Final = 1_000
PRINCIPAL_WRITES_PER_DAY: Final = 2_000
#: Refused client writes per writer bucket per rolling hour (step 4).
REFUSALS_PER_HOUR: Final = 120
#: New canonical bytes per rolling day, and stored bytes in all.
BUCKET_BYTES_PER_DAY: Final = 134_217_728
PRINCIPAL_BYTES_PER_DAY: Final = 268_435_456
PRINCIPAL_BYTES_TOTAL: Final = 2_147_483_648
#: Stored rows per Principal and per version.
MAX_SCENARIOS_PER_PRINCIPAL: Final = 200
MAX_VERSIONS_PER_PRINCIPAL: Final = 20_000
MAX_OUTPUTS_PER_VERSION: Final = 100
#: CPM activity-units per Principal per rolling hour (`admit_compute`).
CPM_UNITS_PER_HOUR: Final = 2_500_000

_HOUR: Final = timedelta(hours=1)
_TRUNCATION_REASON: Final = "page_size_reached"
_NO_TRUNCATION: Final = Truncation()
_SERVED: Final = frozenset({SchedulePublicationStatus.COMPLETE, SchedulePublicationStatus.PARTIAL})
_ORIGIN_HOPS: Final = 1_000
#: Section 15.7.2: the governing-chain backstops; every other lost race names the Baseline.
_GOVERNING_RACES: Final = frozenset(
    {"a_schedule_governing_event_seq_is_used_once", "a_schedule_governing_event_extends_its_chain"}
)

#: Section 15.6.3: each answer's trust basis (`TrustLevel.MODEL_PROPOSED`).
_SCENARIO_BASIS: Final = ("schedule_scenario", "client_authored")
_RUN_BASIS: Final = (*_SCENARIO_BASIS, "schedule_cpm", ENGINE_VERSION, "server_computed")
_OUTPUT_BASIS: Final = (*_SCENARIO_BASIS, "schedule_scenario_output", "client_asserted")
_CURRENT_BASIS: Final = ("schedule_series", "currency-v1", "server_computed")
_MATCH_BASIS: Final = ("schedule_series", "series-match-v1", "server_computed")


def _labels(data_class: str, authority: str, *, authoritative: bool = False) -> dict[str, Any]:
    return {
        "data_class": data_class,
        "authority": authority,
        "authoritative": authoritative,
        "reportable": False,
    }


_SCENARIO_LABELS: Final = _labels("schedule_scenario", "client_authored")
_RUN_LABELS: Final = _labels("schedule_cpm_run", "server_computed")
_OUTPUT_LABELS: Final = _labels("schedule_scenario_output", "client_asserted")
_CURRENT_LABELS: Final = _labels("schedule_series_current", "server_computed")
_MATCH_LABELS: Final = _labels("schedule_match_decision", "server_computed")


@dataclass(frozen=True, slots=True)
class ScenarioAnswer:
    """One plane capability's payload and the disclosure that must accompany it."""

    payload: dict[str, Any]
    disclosure: Disclosure


@dataclass(frozen=True, slots=True)
class ScenarioWriteBuilders:
    """The pure decode seams (section 15.16.3 P3-11, P3-12); tests replace them."""

    apply_change_set: Callable[..., Any] = apply_change_set
    decode_calendar: Callable[[object], ScenarioCalendar] = calendar_from_object


# ---- rendering -------------------------------------------------------------------------


def _instant(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _provenance(provenance: PlaneProvenance) -> dict[str, Any]:
    return {
        "authority_class": provenance.authority_class,
        "decision_channel": provenance.decision_channel,
        "acceptance_basis": provenance.acceptance_basis,
        "user_directed_claim": provenance.user_directed_claim,
        "asserting_client_id": provenance.asserting_client_id,
    }


def _scenario(scenario: StoredScenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id,
        "project_id": scenario.project_id,
        "series_id": scenario.series_id,
        "name": scenario.name,
        "description": scenario.description,
        "origin": {
            "kind": scenario.origin_kind,
            "publication_id": scenario.origin_publication_id,
            "baseline_id": scenario.origin_baseline_id,
            "version_id": scenario.origin_version_id,
        },
        "provenance": _provenance(scenario.provenance),
        "created_at": _instant(scenario.created_at),
    }


def _snapshot_report(version: StoredScenarioVersion) -> dict[str, Any] | None:
    report = version.snapshot
    if report is None:
        return None
    return {
        "activities": report.activities,
        "milestones": report.milestones,
        "durations_quantized": report.durations_quantized,
        "durations_out_of_range": report.durations_out_of_range,
        "original_missing": report.original_missing,
        "remaining_missing": report.remaining_missing,
    }


def _change_report(version: StoredScenarioVersion) -> dict[str, Any] | None:
    if version.change_set_op_count is None:
        return None
    return {
        "op_count": version.change_set_op_count,
        "ops_applied": version.ops_applied,
        "relationships_removed": version.relationships_removed,
        "content_changed": version.content_changed,
    }


def _content_fields(version: StoredScenarioVersion) -> dict[str, Any]:
    return {
        "content_sha256": version.content_sha256,
        "content_size_bytes": version.content_size_bytes,
        "activity_count": version.activity_count,
        "relationship_count": version.relationship_count,
        "calendar_count": version.calendar_count,
        "distribution_spec_sha256": version.distribution_spec_sha256,
    }


def _version(version: StoredScenarioVersion) -> dict[str, Any]:
    return {
        "version_id": version.version_id,
        "scenario_id": version.scenario_id,
        "project_id": version.project_id,
        "series_id": version.series_id,
        "version_no": version.version_no,
        "parent_version_id": version.parent_version_id,
        "label": version.label.value,
        "note": version.note,
        **_content_fields(version),
        "change_set_sha256": version.change_set_sha256,
        "change_set_size_bytes": version.change_set_size_bytes,
        "change_report": _change_report(version),
        "snapshot_report": _snapshot_report(version),
        "provenance": _provenance(version.provenance),
        "created_at": _instant(version.created_at),
    }


def _run(run: StoredCpmRun) -> dict[str, Any]:
    return {
        "cpm_run_id": run.cpm_run_id,
        "version_id": run.version_id,
        "engine_version": run.engine_version,
        "input_content_sha256": run.input_content_sha256,
        "status": run.status.value,
        "project_finish": run.project_finish,
        "result_sha256": run.result_sha256,
        "result_size_bytes": run.result_size_bytes,
        "activity_count": run.activity_count,
        "relationship_count": run.relationship_count,
        "provenance": _provenance(run.provenance),
        "created_at": _instant(run.created_at),
    }


def _output(output: StoredScenarioOutput) -> dict[str, Any]:
    return {
        "output_id": output.output_id,
        "version_id": output.version_id,
        "content_sha256": output.content_sha256,
        "base_cpm_run_id": output.base_cpm_run_id,
        "kind": output.kind.value,
        "iterations": output.iterations,
        "distribution_spec_sha256": output.distribution_spec_sha256,
        "payload_sha256": output.payload_sha256,
        "payload_size_bytes": output.payload_size_bytes,
        "provenance": _provenance(output.provenance),
        "created_at": _instant(output.created_at),
    }


def _proposer(provenance: PlaneProvenance) -> dict[str, Any]:
    """Section 15.4: who proposed -- the operator or a client channel."""
    if provenance.decision_channel in PLANE_ATTESTED_DECISION_CHANNELS:
        return {"kind": "operator", "channel": provenance.decision_channel}
    return {
        "kind": "client",
        "channel": provenance.decision_channel,
        "client_id": provenance.asserting_client_id,
    }


def _event(event: StoredBaselineEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "seq": event.seq,
        "action": event.action.value,
        "publication_id": event.publication_id,
        "recorded_at": _instant(event.recorded_at),
        "reason": event.reason,
        "type": None if event.type is None else event.type.value,
        "label": event.label,
        "approval_reference": event.approval_reference,
        "effective_from": _day(event.effective_from),
        "supersedes_baseline_id": event.supersedes_baseline_id,
        "approved_at_import": event.approved_at_import,
        "provenance": _provenance(event.provenance),
    }


def _baseline_labels(view: BaselineView) -> dict[str, Any]:
    """Section 15.6.3: `authoritative` only on an effective Baseline; a proposal is `proposed`."""
    approved = view.effective_type is not None
    return _labels(
        "schedule_baseline",
        "operator_approved" if approved else "proposed",
        authoritative=view.effective,
    )


def _baseline(
    stored: StoredBaseline,
    view: BaselineView,
    *,
    governing: str | None,
    history: bool,
) -> dict[str, Any]:
    first = stored.events[0] if stored.events else None
    approval = next((event for event in stored.events if event.action.value == "approve"), None)
    rendered: dict[str, Any] = {
        "baseline_id": stored.baseline_id,
        "project_id": stored.project_id,
        "series_id": stored.series_id,
        "publication_id": stored.publication_id,
        "status": view.status.value,
        "proposed_type": None if view.proposed_type is None else view.proposed_type.value,
        "effective_type": None if view.effective_type is None else view.effective_type.value,
        "label": view.label,
        "effective_from": _day(view.effective_from),
        "superseded": view.superseded,
        "governing": governing == stored.baseline_id,
        "proposer": (
            None
            if first is None or first.action.value != "propose"
            else _proposer(first.provenance)
        ),
        "approver": None if approval is None else _proposer(approval.provenance),
        "provenance": None if first is None else _provenance(first.provenance),
        "created_at": _instant(stored.created_at),
        "labels": _baseline_labels(view),
    }
    if history:
        rendered["events"] = [_event(event) for event in stored.events]
    return rendered


def _decision(record: SeriesMatchRecord) -> dict[str, Any]:
    return {
        "decision_id": record.decision_id,
        "intake_publication_id": record.intake_publication_id,
        "intake_series_id": record.intake_series_id,
        "outcome": record.outcome.value,
        "reason": None if record.reason is None else record.reason.value,
        "threshold_version": record.threshold_version,
        "incoming_id_count": record.incoming_id_count,
        "candidates": [
            {
                "series_id": candidate.series_id,
                "publication_id": candidate.publication_id,
                "data_date": candidate.data_date.isoformat(),
                "score": candidate.score,
                "data_date_coherent": candidate.data_date_coherent,
                "name_agreement_permille": candidate.name_agreement_permille,
                "title_equal": candidate.title_equal,
            }
            for candidate in record.candidates
        ],
        "target_series_id": record.target_series_id,
        "resulting_publication_id": record.resulting_publication_id,
        "admission_refusal": record.admission_refusal,
        "admission_skipped": record.admission_skipped,
        "created_at": _instant(record.created_at),
        "labels": _MATCH_LABELS,
    }


# ---- disclosure ------------------------------------------------------------------------


def _coverage(statuses: Sequence[SchedulePublicationStatus]) -> Coverage:
    if not statuses:
        return Coverage(state=CoverageState.ELIGIBLE)
    processed = sum(1 for status in statuses if status in _SERVED)
    state = (
        CoverageState.PROCESSED if processed == len(statuses) else CoverageState.PARTIALLY_PROCESSED
    )
    return Coverage(state=state, eligible=len(statuses), processed=processed)


def _disclosure(
    roots: Sequence[tuple[ScheduleSourceBinding, SchedulePublicationStatus]],
    *,
    observed_at: datetime,
    basis: tuple[str, ...],
    truncation: Truncation = _NO_TRUNCATION,
) -> Disclosure:
    """Section 15.6.3: the scope and sources of the answer's root publications."""
    coverage = _coverage([status for _, status in roots])
    bindings = [binding for binding, _ in roots]
    return Disclosure(
        scope=Scope(
            source_ids=tuple(sorted({binding.source_id for binding in bindings})),
            enrollment_ids=tuple(sorted({binding.enrollment_id for binding in bindings})),
        ),
        coverage=coverage,
        freshness=Freshness(
            observed_at=observed_at, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.MODEL_PROPOSED, basis=basis),
        truncation=truncation,
        source_references=tuple(
            SourceReference(source_id=s, source_object_id=o, version_id=v)
            for s, o, v in sorted(
                {
                    (binding.source_id, binding.source_object_id, binding.source_version_id)
                    for binding in bindings
                }
            )
        ),
        partial_result=truncation.is_truncated
        or coverage.state is CoverageState.PARTIALLY_PROCESSED,
        classification=Classification.PRIVATE_LOCAL,
        cloud_eligible=False,
    )


# ---- cursor plumbing (the S5 `ScheduleCursor`, section 15.6.2) -------------------------


@dataclass(frozen=True, slots=True)
class _Paging:
    page_size: int
    binding: str
    order: ScheduleCursorOrder
    position: SchedulePosition | None
    issued_at: datetime

    def truncation(self, more: bool, last: SchedulePosition | None) -> Truncation:
        if not more or last is None:
            return _NO_TRUNCATION
        return Truncation(
            is_truncated=True,
            reason=_TRUNCATION_REASON,
            next_cursor=encode_schedule_cursor(
                binding=self.binding, order=self.order, position=last, issued_at=self.issued_at
            ),
        )


def _request_fields(command: object) -> dict[str, object]:
    return {
        name: list(value) if isinstance(value, tuple) else value
        for name, value in asdict(command).items()  # type: ignore[call-overload]
        if name not in {"cursor", "page_size"}
    }


def _paging(
    authorization: Authorization,
    command: Any,  # noqa: ANN401 - a plane list command (has `page_size`, `cursor`)
    order: ScheduleCursorOrder,
) -> _Paging:
    """Bind and decode before any read: a refused cursor is `invalid_request(cursor)`."""
    size = command.page_size or DEFAULT_SCHEDULE_PAGE_SIZE
    binding = schedule_cursor_binding(
        capability=command.capability.value,
        principal_id=authorization.principal.principal_id,
        purpose=authorization.purpose.value,
        request=_request_fields(command),
        page_size=size,
        order=order,
    )
    position: SchedulePosition | None = None
    if command.cursor is not None:
        refused = False
        try:
            position = decode_schedule_cursor(
                command.cursor, binding=binding, order=order, now=authorization.at
            ).position
        except ScheduleCursorError:
            refused = True
        if refused:
            raise InvalidRequestError(SafeDetail.CURSOR)
    return _Paging(size, binding, order, position, authorization.at)


def _keyset(paging: _Paging) -> tuple[datetime, str] | None:
    if paging.position is None:
        return None
    at, identifier = paging.position
    if not isinstance(at, datetime) or not isinstance(identifier, str):  # pragma: no cover
        raise InternalError()
    return at, identifier


def _offset(paging: _Paging) -> int:
    if paging.position is None:
        return 0
    (offset,) = paging.position
    if not isinstance(offset, int):  # pragma: no cover - the cursor module typed it
        raise InternalError()
    return offset


def _page_offset[T](paging: _Paging, items: Sequence[T]) -> tuple[Sequence[T], Truncation]:
    """An offset page of a canonical sorted array; an offset past its end is a bad cursor."""
    offset = _offset(paging)
    if offset > len(items):
        raise InvalidRequestError(SafeDetail.CURSOR)
    end = offset + paging.page_size
    return items[offset:end], paging.truncation(end < len(items), (end,))


# ---- the application ---------------------------------------------------------------------


def _plane_provenance(authorization: Authorization, *, user_directed: bool) -> PlaneProvenance:
    """Step 3: the server-derived provenance of every plane row (S6-3-D24)."""
    derived = lineage_write_provenance(authorization, user_directed=user_directed)
    return PlaneProvenance(
        authority_class=derived.authority_class.value,
        decision_channel=derived.decision_channel.value,
        asserting_client_id=derived.asserting_client_id,
        acceptance_basis=derived.acceptance_basis.value,
        user_directed_claim=derived.user_directed_claim,
    )


def _is_operator(writer: PlaneProvenance) -> bool:
    return writer.decision_channel in PLANE_ATTESTED_DECISION_CHANNELS


def _text(value: str | None) -> str | None:
    return None if value is None else normalize_display_text(value)


def _digest_request(command: object, *, normalized: Iterable[str]) -> dict[str, object]:
    """Section 15.5: the command's fields after normalization, the key excluded."""
    fields: dict[str, object] = dict(asdict(command))  # type: ignore[call-overload]
    for name in normalized:
        value = fields.get(name)
        if isinstance(value, str):
            fields[name] = normalize_display_text(value)
    fields.pop("idempotency_key", None)
    return fields


_SNAPSHOT_REFUSALS: Final[Mapping[SnapshotRefusalReason, ApplicationError]] = {
    SnapshotRefusalReason.MINUTES_PER_SOURCE_UNIT: InvalidRequestError(
        SafeDetail.MINUTES_PER_SOURCE_UNIT
    ),
    SnapshotRefusalReason.CALENDAR: InvalidRequestError(SafeDetail.CALENDAR),
    SnapshotRefusalReason.DATA_DATE: InvalidRequestError(SafeDetail.DATA_DATE_TIME),
    SnapshotRefusalReason.ROWS: ConflictError(SafeDetail.FROM_PUBLICATION_ID),
}


def _snapshot_refusal(reason: SnapshotRefusalReason) -> ApplicationError:
    template = _SNAPSHOT_REFUSALS[reason]
    return type(template)(*template.safe_details)


def _baseline_refusal(refusal: BaselineRefusal) -> ApplicationError:
    """Section 15.7.2: a `BaselineWriteRefusedError` carried refusal and its answer."""
    match refusal:
        case BaselineRefusal.CONFLICT_BASELINE_ID:
            return ConflictError(SafeDetail.BASELINE_ID)
        case BaselineRefusal.CONFLICT_GOVERNING:
            return ConflictError(SafeDetail.GOVERNING)
        case BaselineRefusal.CONFLICT_STATUS:
            return ConflictError(SafeDetail.STATUS)
        case BaselineRefusal.RATE_LIMITED_BASELINE_ID:
            return RateLimitedError(SafeDetail.BASELINE_ID)
        case BaselineRefusal.INVALID_TO_PUBLICATION_ID:
            return InvalidRequestError(SafeDetail.TO_PUBLICATION_ID)
        case BaselineRefusal.DENIED:
            return DeniedError(SafeDetail.BASELINE_ID)
    raise InternalError()  # pragma: no cover - the refusal set is closed


def _race(code: str) -> ApplicationError:
    detail = SafeDetail.GOVERNING if code in _GOVERNING_RACES else SafeDetail.BASELINE_ID
    return ConflictError(detail)


class ScheduleScenarioApplication:
    """The 26 plane use cases on the plane unit of work (contract section 15)."""

    def __init__(
        self,
        unit_of_work: Callable[[], ScenarioUnitOfWork],
        cpm_runner: ScenarioCpmRunner,
        records: ScenarioRecordBuilders,
        schedule_unit_of_work: Callable[[], ScheduleUnitOfWork],
        *,
        builders: ScenarioWriteBuilders | None = None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._cpm_runner = cpm_runner
        self._records = records
        self._schedule_unit_of_work = schedule_unit_of_work
        self._builders = builders or ScenarioWriteBuilders()

    # ---- the write prologue (steps 2-4) and the refusal record (step 7) ----------------

    def _client_writer(self, authorization: Authorization, command: Any) -> PlaneProvenance:  # noqa: ANN401
        """Steps 2-4 of a client-usable write: grant, provenance, refusal bound."""
        require_write_grant(authorization.capability_grants, command.capability)
        writer = _plane_provenance(authorization, user_directed=command.user_directed)
        self._refusal_bound(authorization, writer)
        return writer

    def _operator_writer(self, authorization: Authorization, command: Any) -> PlaneProvenance:  # noqa: ANN401
        """Steps 2-3 of an operator write: grant, attestation (`denied`), provenance."""
        require_write_grant(authorization.capability_grants, command.capability)
        attested_lineage_authority(authorization)
        return _plane_provenance(authorization, user_directed=False)

    def _refusal_bound(self, authorization: Authorization, writer: PlaneProvenance) -> None:
        """Step 4: a short read; the bound is answered before any document is decoded."""
        if _is_operator(writer):
            return
        principal_id = authorization.principal.principal_id
        with self._unit_of_work() as work:
            refused = work.scenarios.refusal_count(principal_id, writer, authorization.at - _HOUR)
        if refused >= REFUSALS_PER_HOUR:
            raise RateLimitedError(SafeDetail.SCENARIO_REFUSAL_BUDGET)

    def _counted[T](
        self,
        authorization: Authorization,
        capability: Capability,
        writer: PlaneProvenance,
        body: Callable[[], T],
    ) -> T:
        """Steps 5-7: run `body`; a client channel's refusal is recorded, then re-raised."""
        failure: ApplicationError | None = None
        try:
            return body()
        except ApplicationError as error:
            failure = error
        except (PlaneSubjectAbsentError, CpmComputeBusyError) as error:  # pragma: no cover
            raise InternalError() from error
        except ScenarioIntegrityError:
            failure = InternalError()
        if failure is None:  # pragma: no cover - the body returned or raised
            raise InternalError()
        if not _is_operator(writer) and not isinstance(failure, InternalError):
            with self._unit_of_work() as work:
                work.scenarios.record_refusal(
                    authorization.principal.principal_id,
                    writer,
                    capability.value,
                    failure.code.value,
                )
        raise failure

    def _admit_write(
        self,
        scenarios: ScenarioRepository,
        principal_id: str,
        writer: PlaneProvenance,
        at: datetime,
        new_bytes: int | None,
    ) -> None:
        """Section 15.10 step 6: the client write budgets and byte quotas, under P.

        `new_bytes` is the canonical bytes this write stores (0 for a CPM
        natural-key hit, which consumes a write and no bytes, so no byte quota
        refuses it), or `None` for the CPM pre-check before the leased compute
        (R10-F02, R10-N01): nothing is stored yet, so it refuses only a client
        already at or over a write budget or a byte quota.
        """
        if _is_operator(writer):
            return
        writes = scenarios.client_write_counts(principal_id, writer, at)
        if (
            writes.bucket_hour >= BUCKET_WRITES_PER_HOUR
            or writes.bucket_day >= BUCKET_WRITES_PER_DAY
            or writes.principal_day >= PRINCIPAL_WRITES_PER_DAY
        ):
            raise RateLimitedError(SafeDetail.SCENARIO_WRITE_BUDGET)
        if new_bytes == 0:
            return
        stored = scenarios.plane_byte_counts(principal_id, writer, at)
        totals = (
            (stored.principal_total, PRINCIPAL_BYTES_TOTAL),
            (stored.principal_day, PRINCIPAL_BYTES_PER_DAY),
            (stored.bucket_day, BUCKET_BYTES_PER_DAY),
        )
        if new_bytes is None:
            over = any(used >= quota for used, quota in totals)
        else:
            over = any(used + new_bytes > quota for used, quota in totals)
        if over:
            raise RateLimitedError(SafeDetail.STORAGE_QUOTA)

    def _reserve(
        self,
        scenarios: ScenarioRepository,
        principal_id: str,
        capability: Capability,
        key: str,
        digest: str,
        writer: PlaneProvenance,
    ) -> PlaneReservation:
        scenarios.lock_principal(principal_id)
        reservation = scenarios.reserve_request(principal_id, capability.value, key, digest, writer)
        if reservation.outcome is PlaneReservationOutcome.CONFLICT:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        return reservation

    # ---- roots and disclosure ----------------------------------------------------------

    def _root_publication(
        self, scenarios: ScenarioRepository, principal_id: str, scenario: StoredScenario
    ) -> str:
        """The origin publication of a Scenario; a fork's is its source Scenario's."""
        current = scenario
        for _ in range(_ORIGIN_HOPS):
            if current.origin_publication_id is not None:
                return current.origin_publication_id
            source_id = current.origin_version_id
            source = None if source_id is None else scenarios.get_version(principal_id, source_id)
            parent = (
                None if source is None else scenarios.get_scenario(principal_id, source.scenario_id)
            )
            if parent is None:
                raise InternalError()
            current = parent
        raise InternalError()  # pragma: no cover - a fork chain is acyclic and bounded

    def _roots(
        self, work: ScenarioUnitOfWork, principal_id: str, publication_ids: Iterable[str]
    ) -> list[tuple[ScheduleSourceBinding, SchedulePublicationStatus]]:
        found = []
        for publication_id in sorted(set(publication_ids)):
            detail = work.schedules.get_publication_detail(principal_id, publication_id)
            if detail is not None:
                found.append((detail.source, detail.effective_status))
        return found

    def _version_root(
        self, work: ScenarioUnitOfWork, principal_id: str, version: StoredScenarioVersion
    ) -> str:
        scenario = work.scenarios.get_scenario(principal_id, version.scenario_id)
        if scenario is None:  # pragma: no cover - a version names an owned Scenario
            raise InternalError()
        return self._root_publication(work.scenarios, principal_id, scenario)

    @staticmethod
    def _reader(authorization: Authorization, payload: dict[str, Any]) -> dict[str, Any]:
        """Section 15.6.4: a remote reader never sees which OAuth client wrote a row."""
        if authorization.capability_grants is not None:
            withheld: dict[str, Any] = _without_proposer_clients(withhold_client_ids(payload))
            return withheld
        return payload

    def _answer(
        self,
        authorization: Authorization,
        payload: dict[str, Any],
        roots: Sequence[tuple[ScheduleSourceBinding, SchedulePublicationStatus]],
        basis: tuple[str, ...],
        truncation: Truncation = _NO_TRUNCATION,
    ) -> ScenarioAnswer:
        return ScenarioAnswer(
            payload=self._reader(authorization, payload),
            disclosure=_disclosure(
                roots, observed_at=authorization.at, basis=basis, truncation=truncation
            ),
        )

    # ---- schedule_scenarios.create ------------------------------------------------------

    def create_scenario(
        self, authorization: Authorization, command: CreateScheduleScenario
    ) -> ScenarioAnswer:
        writer = self._client_writer(authorization, command)
        capability = command.capability
        return self._counted(
            authorization, capability, writer, lambda: self._create(authorization, command, writer)
        )

    def _calendars(self, raw: object) -> tuple[ScenarioCalendar, ...]:
        if not isinstance(raw, list):
            raise InvalidRequestError(SafeDetail.CALENDAR)
        decoded: list[ScenarioCalendar] = []
        refused = False
        for item in raw:
            try:
                decoded.append(self._builders.decode_calendar(item))
            except (ScenarioDecodeError, ValueError, TypeError, KeyError):
                refused = True
                break
        if refused:
            raise InvalidRequestError(SafeDetail.CALENDAR)
        return tuple(decoded)

    def _eligible_baseline(
        self, scenarios: ScenarioRepository, principal_id: str, baseline_id: str, detail: SafeDetail
    ) -> tuple[StoredBaseline, BaselineView]:
        """Section 15.7.2 (R10-F13): not effective is `conflict(baseline_id)`.

        An approved Baseline whose publication is not effective is `conflict(status)`.
        """
        stored = scenarios.get_baseline(principal_id, baseline_id)
        if stored is None:
            raise NotFoundError(detail)
        chain = scenarios.baseline_chain(principal_id, stored.project_id)
        views = baseline_status(
            chain.events,
            eligible_publication_ids=scenarios.eligible_publication_ids(
                principal_id, stored.project_id
            ),
        )
        view = views.get(baseline_id)
        if view is None:  # pragma: no cover - a Baseline row has its first event
            raise InternalError()
        if view.status is BaselineStatus.INELIGIBLE:
            raise ConflictError(SafeDetail.STATUS)
        if not view.effective:
            raise ConflictError(SafeDetail.BASELINE_ID)
        return stored, view

    def _create(
        self, authorization: Authorization, command: CreateScheduleScenario, writer: PlaneProvenance
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        capability = command.capability
        digest = scenario_request_digest(
            principal_id,
            capability.value,
            _digest_request(command, normalized=("name", "description", "note")),
        )
        label = VersionLabel(command.label)
        scenario = NewScenario(
            name=normalize_display_text(command.name),
            description=_text(command.description),
        )
        note = _text(command.note)
        # Step 1 of 15.10's ledger: a replay answers before any decode.
        with self._unit_of_work() as work:
            replay = work.scenarios.find_request(
                principal_id, capability.value, command.idempotency_key, digest
            )
            _refuse_a_conflict(replay)
        if replay is not None:
            return self._replayed_scenario(authorization, replay)
        if command.from_version_id is not None:
            return self._fork(authorization, command, writer, scenario, label, note, digest)
        # Step 5: the snapshot source, then the decode, outside any write transaction.
        publication_id = command.from_publication_id
        with self._unit_of_work() as work:
            if command.from_baseline_id is not None:
                stored, _ = self._eligible_baseline(
                    work.scenarios,
                    principal_id,
                    command.from_baseline_id,
                    SafeDetail.FROM_BASELINE_ID,
                )
                publication_id = stored.publication_id
            if publication_id is None:  # pragma: no cover - the command named one origin
                raise InternalError()
            source = work.scenarios.snapshot_source(principal_id, publication_id)
            state = (
                None
                if source is not None
                else work.scenarios.publication_state(principal_id, publication_id)
            )
        if source is None:
            # S6-3-D19: absent, foreign or intake reads as absent; else not eligible.
            if state is None or state[1]:
                raise NotFoundError(SafeDetail.FROM_PUBLICATION_ID)
            raise ConflictError(SafeDetail.STATUS)
        calendars = self._calendars(command.calendars)
        snapshot = None
        refusal: SnapshotRefusalReason | None = None
        try:
            snapshot = snapshot_from_publication(
                publication_id=publication_id,
                data_date=source.data_date,
                rows=source.rows,
                minutes_per_source_unit=int(command.minutes_per_source_unit or 0),
                calendars=calendars,
                default_calendar=str(command.default_calendar),
                data_date_time=command.data_date_time or "00:00",
            )
        except SnapshotRefusalError as refused:
            refusal = refused.reason
        if refusal is not None:
            raise _snapshot_refusal(refusal)
        if snapshot is None:  # pragma: no cover
            raise InternalError()
        version = self._new_version(
            snapshot.content, label=label, note=note, snapshot=snapshot.report
        )
        scenario = NewScenario(
            name=scenario.name,
            description=scenario.description,
            origin_publication_id=publication_id,
            origin_baseline_id=command.from_baseline_id,
        )
        # Step 6: the write transaction.
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            reservation = self._reserve(
                scenarios, principal_id, capability, command.idempotency_key, digest, writer
            )
            if reservation.outcome is PlaneReservationOutcome.RESERVED:
                self._admit_write(
                    scenarios,
                    principal_id,
                    writer,
                    authorization.at,
                    version.content_size_bytes,
                )
                self._admit_rows(scenarios, principal_id, writer, scenario=True)
                stored_version = self._absent(
                    lambda: scenarios.insert_scenario(principal_id, scenario, version, writer),
                    SafeDetail.FROM_BASELINE_ID
                    if command.from_baseline_id is not None
                    else SafeDetail.FROM_PUBLICATION_ID,
                )
                scenarios.complete_request(
                    principal_id,
                    capability.value,
                    command.idempotency_key,
                    stored_version.scenario_id,
                    created=True,
                    stored_bytes=version.content_size_bytes,
                )
                return self._scenario_answer(authorization, work, stored_version, replayed=False)
        return self._replayed_scenario(authorization, reservation)

    @staticmethod
    def _absent[T](body: Callable[[], T], detail: SafeDetail) -> T:
        """`PlaneSubjectAbsentError` is `not_found(detail)`; the baseline refusals map."""
        failure: ApplicationError | None = None
        try:
            return body()
        except PlaneSubjectAbsentError:
            failure = NotFoundError(detail)
        except BaselineWriteRefusedError as refused:
            failure = _baseline_refusal(refused.refusal)
        except ScenarioHeadMovedError:
            failure = ConflictError(SafeDetail.EXPECTED_VERSION)
        except ScheduleBaselineRaceError as race:
            failure = _race(race.code)
        raise failure

    def _new_version(self, content: ScenarioContent, **fields: Any) -> NewScenarioVersion:  # noqa: ANN401
        """Canonicalize and compress outside any transaction (S6-2-D14).

        A new canonical content over `MAX_CONTENT_BYTES` is
        `invalid_request(content_size)`; it is measured before the builder runs.
        """
        if len(content_bytes(content)) > MAX_CONTENT_BYTES:
            raise InvalidRequestError(SafeDetail.CONTENT_SIZE)
        return self._records.new_version(content, **fields)

    def _admit_rows(
        self,
        scenarios: ScenarioRepository,
        principal_id: str,
        writer: PlaneProvenance,
        *,
        scenario: bool,
    ) -> None:
        """Section 2.10: 200 Scenarios and 20,000 versions per Principal (client channels)."""
        if _is_operator(writer):
            return
        scenario_count, version_count = scenarios.scenario_and_version_counts(principal_id)
        if (scenario and scenario_count >= MAX_SCENARIOS_PER_PRINCIPAL) or (
            version_count >= MAX_VERSIONS_PER_PRINCIPAL
        ):
            raise RateLimitedError(SafeDetail.STORAGE_QUOTA)

    def _fork(
        self,
        authorization: Authorization,
        command: CreateScheduleScenario,
        writer: PlaneProvenance,
        scenario: NewScenario,
        label: VersionLabel,
        note: str | None,
        digest: str,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        capability = command.capability
        source_id = str(command.from_version_id)
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            reservation = self._reserve(
                scenarios, principal_id, capability, command.idempotency_key, digest, writer
            )
            if reservation.outcome is PlaneReservationOutcome.RESERVED:
                source = scenarios.get_version(principal_id, source_id)
                if source is None:
                    raise NotFoundError(SafeDetail.FROM_VERSION_ID)
                # S6-U08: a fork counts its copied bytes.
                self._admit_write(
                    scenarios, principal_id, writer, authorization.at, source.content_size_bytes
                )
                self._admit_rows(scenarios, principal_id, writer, scenario=True)
                stored_version = self._absent(
                    lambda: scenarios.fork_scenario(
                        principal_id, scenario, source_id, label, note, writer
                    ),
                    SafeDetail.FROM_VERSION_ID,
                )
                scenarios.complete_request(
                    principal_id,
                    capability.value,
                    command.idempotency_key,
                    stored_version.scenario_id,
                    created=True,
                    stored_bytes=stored_version.content_size_bytes,
                )
                return self._scenario_answer(authorization, work, stored_version, replayed=False)
        return self._replayed_scenario(authorization, reservation)

    def _scenario_answer(
        self,
        authorization: Authorization,
        work: ScenarioUnitOfWork,
        version: StoredScenarioVersion,
        *,
        replayed: bool,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        scenario = work.scenarios.get_scenario(principal_id, version.scenario_id)
        if scenario is None:  # pragma: no cover - written in this transaction or earlier
            raise InternalError()
        root = self._root_publication(work.scenarios, principal_id, scenario)
        payload = {
            "scenario_id": scenario.scenario_id,
            "version_id": version.version_id,
            "version_no": version.version_no,
            "origin": _scenario(scenario)["origin"],
            **_content_fields(version),
            "snapshot_report": _snapshot_report(version),
            "replayed": replayed,
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(
            authorization, payload, self._roots(work, principal_id, [root]), _SCENARIO_BASIS
        )

    def _replayed_scenario(
        self, authorization: Authorization, reservation: PlaneReservation
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        with self._unit_of_work() as work:
            scenario_id = reservation.result_id
            first = (
                None
                if scenario_id is None
                else work.scenarios.version_by_number(principal_id, scenario_id, 1)
            )
            if first is None:
                raise InternalError()
            return self._scenario_answer(authorization, work, first, replayed=True)

    # ---- schedule_scenario_versions.create --------------------------------------------

    def append_version(
        self, authorization: Authorization, command: CreateScheduleScenarioVersion
    ) -> ScenarioAnswer:
        writer = self._client_writer(authorization, command)
        return self._counted(
            authorization,
            command.capability,
            writer,
            lambda: self._append(authorization, command, writer),
        )

    def _append(
        self,
        authorization: Authorization,
        command: CreateScheduleScenarioVersion,
        writer: PlaneProvenance,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        capability = command.capability
        digest = scenario_request_digest(
            principal_id, capability.value, _digest_request(command, normalized=("note",))
        )
        with self._unit_of_work() as work:
            replay = work.scenarios.find_request(
                principal_id, capability.value, command.idempotency_key, digest
            )
            _refuse_a_conflict(replay)
            if replay is None:
                # The CAS pre-check (P3-11): a moved head never reaches the change set.
                head = work.scenarios.head_version(principal_id, command.scenario_id)
                if head is None:
                    raise NotFoundError(SafeDetail.SCENARIO_ID)
                if head.version_no != command.expected_head_version_no:
                    raise ConflictError(SafeDetail.EXPECTED_VERSION)
                parent = work.scenarios.load_content(principal_id, head.version_id)
        if replay is not None:
            return self._replayed_version(authorization, replay)
        if parent is None:  # pragma: no cover - the head was just read
            raise InternalError()
        ops = command.change_set
        if not isinstance(ops, list):  # pragma: no cover - the command checked it
            raise InvalidRequestError(SafeDetail.CHANGE_SET)
        applied = self._builders.apply_change_set(parent.content, ops)
        if isinstance(applied, ChangeSetRefusal):
            # S6-U09: the op index is not disclosed.
            raise InvalidRequestError(SafeDetail(f"change_set_{applied.op_error.value}"))
        version = self._new_version(
            applied.content,
            label=VersionLabel(command.label),
            note=_text(command.note),
            ops=ops,
            applied=applied.report,
        )
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            reservation = self._reserve(
                scenarios, principal_id, capability, command.idempotency_key, digest, writer
            )
            if reservation.outcome is PlaneReservationOutcome.RESERVED:
                self._admit_write(
                    scenarios, principal_id, writer, authorization.at, version.content_size_bytes
                )
                self._admit_rows(scenarios, principal_id, writer, scenario=False)
                stored = self._absent(
                    lambda: scenarios.append_version(
                        principal_id,
                        command.scenario_id,
                        command.expected_head_version_no,
                        version,
                        writer,
                    ),
                    SafeDetail.SCENARIO_ID,
                )
                scenarios.complete_request(
                    principal_id,
                    capability.value,
                    command.idempotency_key,
                    stored.version_id,
                    created=True,
                    stored_bytes=version.content_size_bytes,
                )
                return self._version_answer(authorization, work, stored, replayed=False)
        return self._replayed_version(authorization, reservation)

    def _version_answer(
        self,
        authorization: Authorization,
        work: ScenarioUnitOfWork,
        version: StoredScenarioVersion,
        *,
        replayed: bool,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        payload = {
            "scenario_id": version.scenario_id,
            "version_id": version.version_id,
            "version_no": version.version_no,
            "parent_version_id": version.parent_version_id,
            **_content_fields(version),
            "change_report": _change_report(version),
            "replayed": replayed,
            "labels": _SCENARIO_LABELS,
        }
        root = self._version_root(work, principal_id, version)
        return self._answer(
            authorization, payload, self._roots(work, principal_id, [root]), _SCENARIO_BASIS
        )

    def _replayed_version(
        self, authorization: Authorization, reservation: PlaneReservation
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        with self._unit_of_work() as work:
            version = (
                None
                if reservation.result_id is None
                else work.scenarios.get_version(principal_id, reservation.result_id)
            )
            if version is None:
                raise InternalError()
            return self._version_answer(authorization, work, version, replayed=True)

    # ---- schedule_cpm_runs.create -------------------------------------------------------

    def create_cpm_run(
        self, authorization: Authorization, command: CreateScheduleCpmRun
    ) -> ScenarioAnswer:
        writer = self._client_writer(authorization, command)
        return self._counted(
            authorization,
            command.capability,
            writer,
            lambda: self._cpm(authorization, command, writer),
        )

    def _cpm(
        self, authorization: Authorization, command: CreateScheduleCpmRun, writer: PlaneProvenance
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        capability = command.capability
        digest = scenario_request_digest(
            principal_id, capability.value, _digest_request(command, normalized=())
        )
        operator = _is_operator(writer)

        def admit_compute(used: int, requested: int) -> None:
            # R10-F04: the attested operator is admitted whatever `used` is.
            if not operator and used + requested > CPM_UNITS_PER_HOUR:
                raise RateLimitedError(SafeDetail.CPM_RUN)

        def admit_write(scenarios: ScenarioRepository, owner: str, new_bytes: int | None) -> None:
            self._admit_write(scenarios, owner, writer, authorization.at, new_bytes)

        failure: ApplicationError | None = None
        written = None
        try:
            written = self._cpm_runner(
                principal_id,
                command.version_id,
                capability_key=command.idempotency_key,
                request_digest=digest,
                writer=writer,
                admit_compute=admit_compute,
                admit_write=admit_write,
            )
        except PlaneSubjectAbsentError:
            failure = NotFoundError(SafeDetail.VERSION_ID)
        except CpmComputeBusyError:
            failure = ConflictError(SafeDetail.CPM_RUN)
        if failure is not None:
            raise failure
        if written is None:  # pragma: no cover
            raise InternalError()
        if written.outcome is PlaneReservationOutcome.CONFLICT:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        run = written.cpm_run
        if run is None:
            raise InternalError()
        replayed = written.outcome is PlaneReservationOutcome.REPLAYED
        with self._unit_of_work() as work:
            version = work.scenarios.get_version(principal_id, run.version_id)
            if version is None:  # pragma: no cover - a run names an owned version
                raise InternalError()
            root = self._version_root(work, principal_id, version)
            roots = self._roots(work, principal_id, [root])
        payload = {
            "cpm_run_id": run.cpm_run_id,
            "version_id": run.version_id,
            "engine_version": run.engine_version,
            "status": run.status.value,
            "project_finish": run.project_finish,
            "result_sha256": run.result_sha256,
            "created": bool(written.created),
            "replayed": replayed,
            "labels": _RUN_LABELS,
        }
        return self._answer(authorization, payload, roots, _RUN_BASIS)

    # ---- schedule_scenario_outputs.record -----------------------------------------------

    def record_output(
        self, authorization: Authorization, command: RecordScheduleScenarioOutput
    ) -> ScenarioAnswer:
        writer = self._client_writer(authorization, command)
        return self._counted(
            authorization,
            command.capability,
            writer,
            lambda: self._record(authorization, command, writer),
        )

    def _record(
        self,
        authorization: Authorization,
        command: RecordScheduleScenarioOutput,
        writer: PlaneProvenance,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        capability = command.capability
        digest = scenario_request_digest(
            principal_id, capability.value, _digest_request(command, normalized=())
        )
        document = command.document
        if not isinstance(document, dict):  # pragma: no cover - the command checked it
            raise InvalidRequestError(SafeDetail.OUTPUT)
        version_id = document.get("version_id")
        if not isinstance(version_id, str):
            raise InvalidRequestError(SafeDetail.OUTPUT)
        version: StoredScenarioVersion | None = None
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            replay = scenarios.find_request(
                principal_id, capability.value, command.idempotency_key, digest
            )
            _refuse_a_conflict(replay)
            if replay is None:
                version = _owned_version(scenarios, principal_id, version_id)
                if version is None:
                    raise InvalidRequestError(SafeDetail.OUTPUT)
                content = scenarios.load_content(principal_id, version.version_id)
                base_run = None
                base_id = document.get("base_cpm_run_id")
                if isinstance(base_id, str):
                    run = _owned_run(scenarios, principal_id, base_id)
                    if (
                        run is not None
                        and run.version_id == version.version_id
                        and run.status is CpmStatus.COMPUTED
                        and run.project_finish is not None
                    ):
                        base_run = BaseRunBinding(
                            run_id=run.cpm_run_id, project_finish=run.project_finish
                        )
        if replay is not None:
            return self._replayed_output(authorization, replay)
        if content is None or version is None:  # pragma: no cover - the version was just read
            raise InternalError()
        binding = OutputBinding(
            version_id=version.version_id,
            content_sha256=version.content_sha256,
            activity_keys=frozenset(activity.key for activity in content.content.activities),
            distribution_spec_sha256=version.distribution_spec_sha256,
            base_run=base_run,
        )
        validated = validate_output(document, binding)
        if isinstance(validated, OutputRefusal):
            raise InvalidRequestError(SafeDetail.OUTPUT)
        output = self._records.new_output(
            validated, distribution_spec=version.distribution_spec_sha256
        )
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            reservation = self._reserve(
                scenarios, principal_id, capability, command.idempotency_key, digest, writer
            )
            if reservation.outcome is PlaneReservationOutcome.RESERVED:
                self._admit_write(
                    scenarios, principal_id, writer, authorization.at, output.payload_size_bytes
                )
                if (
                    not _is_operator(writer)
                    and scenarios.output_count(principal_id, version.version_id)
                    >= MAX_OUTPUTS_PER_VERSION
                ):
                    raise RateLimitedError(SafeDetail.STORAGE_QUOTA)
                stored = scenarios.insert_output(principal_id, output, writer)
                scenarios.complete_request(
                    principal_id,
                    capability.value,
                    command.idempotency_key,
                    stored.output_id,
                    created=True,
                    stored_bytes=output.payload_size_bytes,
                )
                return self._output_answer(authorization, work, stored, replayed=False)
        return self._replayed_output(authorization, reservation)

    def _output_answer(
        self,
        authorization: Authorization,
        work: ScenarioUnitOfWork,
        output: StoredScenarioOutput,
        *,
        replayed: bool,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        version = work.scenarios.get_version(principal_id, output.version_id)
        if version is None:  # pragma: no cover
            raise InternalError()
        root = self._version_root(work, principal_id, version)
        payload = {
            "output_id": output.output_id,
            "version_id": output.version_id,
            "kind": output.kind.value,
            "iterations": output.iterations,
            "payload_sha256": output.payload_sha256,
            "base_cpm_run_id": output.base_cpm_run_id,
            "replayed": replayed,
            "labels": _OUTPUT_LABELS,
        }
        return self._answer(
            authorization, payload, self._roots(work, principal_id, [root]), _OUTPUT_BASIS
        )

    def _replayed_output(
        self, authorization: Authorization, reservation: PlaneReservation
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        with self._unit_of_work() as work:
            output = (
                None
                if reservation.result_id is None
                else work.scenarios.get_output(principal_id, reservation.result_id)
            )
            if output is None:
                raise InternalError()
            return self._output_answer(authorization, work, output, replayed=True)

    # ---- the 6 baseline writes (sections 12.4, 15.4) ------------------------------------

    def propose_baseline(
        self, authorization: Authorization, command: ProposeScheduleBaseline
    ) -> ScenarioAnswer:
        writer = self._client_writer(authorization, command)
        # S6-3-D24: the bucket derives only from server provenance; the operator's
        # proposals count in a bucket no client can equal.
        bucket = writer_bucket(writer.decision_channel, writer.asserting_client_id)
        request = ProposeRequest(
            publication_id=command.publication_id,
            type=BaselineType(command.type),
            writer_bucket=bucket if bucket is not None else OPERATOR_PROPOSAL_BUCKET,
        )
        return self._baseline_write(
            authorization, command, writer, request, SafeDetail.PUBLICATION_ID, approval=None
        )

    def withdraw_baseline(
        self, authorization: Authorization, command: WithdrawScheduleBaseline
    ) -> ScenarioAnswer:
        writer = self._client_writer(authorization, command)
        request = WithdrawRequest(
            baseline_id=command.baseline_id,
            writer_bucket=writer_bucket(writer.decision_channel, writer.asserting_client_id),
        )
        return self._baseline_write(
            authorization, command, writer, request, SafeDetail.BASELINE_ID, approval=None
        )

    def approve_baseline(
        self, authorization: Authorization, command: ApproveScheduleBaseline
    ) -> ScenarioAnswer:
        writer = self._operator_writer(authorization, command)
        approval = ScheduleImportApproval(
            approval_reference=normalize_display_text(command.approval_reference),
            effective_from=date.fromisoformat(command.effective_from),
            reason=normalize_display_text(command.reason),
        )
        kind = command.type
        if kind is None and command.baseline_id is not None:
            with self._unit_of_work() as work:
                stored = work.scenarios.get_baseline(
                    authorization.principal.principal_id, command.baseline_id
                )
            if stored is None:
                raise NotFoundError(SafeDetail.BASELINE_ID)
            baseline_type = stored.type
        else:
            baseline_type = BaselineType(str(kind))
        request = ApproveRequest(
            type=baseline_type,
            effective_from=approval.effective_from,
            baseline_id=command.baseline_id,
            publication_id=command.publication_id,
            supersedes_baseline_id=command.supersedes_baseline_id,
        )
        detail = SafeDetail.BASELINE_ID if command.baseline_id else SafeDetail.PUBLICATION_ID
        return self._baseline_write(
            authorization, command, writer, request, detail, approval=approval
        )

    def reject_baseline(
        self, authorization: Authorization, command: RejectScheduleBaseline
    ) -> ScenarioAnswer:
        writer = self._operator_writer(authorization, command)
        return self._baseline_write(
            authorization,
            command,
            writer,
            RejectRequest(baseline_id=command.baseline_id),
            SafeDetail.BASELINE_ID,
            approval=None,
        )

    def revoke_baseline(
        self, authorization: Authorization, command: RevokeScheduleBaseline
    ) -> ScenarioAnswer:
        writer = self._operator_writer(authorization, command)
        return self._baseline_write(
            authorization,
            command,
            writer,
            RevokeRequest(baseline_id=command.baseline_id),
            SafeDetail.BASELINE_ID,
            approval=None,
        )

    def set_governing(
        self, authorization: Authorization, command: SetGoverningScheduleBaseline
    ) -> ScenarioAnswer:
        writer = self._operator_writer(authorization, command)
        return self._baseline_write(
            authorization,
            command,
            writer,
            SetGoverningRequest(
                baseline_id=command.baseline_id,
                expected_governing_baseline_id=command.expected_governing_baseline_id,
            ),
            SafeDetail.PROJECT_ID,
            approval=None,
            project_id=command.project_id,
        )

    def _baseline_write(
        self,
        authorization: Authorization,
        command: Any,  # noqa: ANN401 - one of the 6 baseline write commands
        writer: PlaneProvenance,
        request: BaselineRequest,
        absent: SafeDetail,
        *,
        approval: ScheduleImportApproval | None,
        project_id: str | None = None,
    ) -> ScenarioAnswer:
        return self._counted(
            authorization,
            command.capability,
            writer,
            lambda: self._write_baseline(
                authorization,
                command,
                writer,
                request,
                absent,
                approval=approval,
                project_id=project_id,
            ),
        )

    def _write_baseline(
        self,
        authorization: Authorization,
        command: Any,  # noqa: ANN401
        writer: PlaneProvenance,
        request: BaselineRequest,
        absent: SafeDetail,
        *,
        approval: ScheduleImportApproval | None,
        project_id: str | None,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        capability = command.capability
        digest = scenario_request_digest(
            principal_id,
            capability.value,
            _digest_request(command, normalized=("reason", "approval_reference")),
        )
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            reservation = self._reserve(
                scenarios, principal_id, capability, command.idempotency_key, digest, writer
            )
            if reservation.outcome is PlaneReservationOutcome.RESERVED:
                self._admit_write(scenarios, principal_id, writer, authorization.at, 0)
                written: BaselineWritten = self._absent(
                    lambda: scenarios.write_baseline(
                        principal_id,
                        request,
                        reason=normalize_display_text(command.reason),
                        approval=approval,
                        writer=writer,
                        project_id=project_id,
                    ),
                    absent,
                )
                scenarios.complete_request(
                    principal_id,
                    capability.value,
                    command.idempotency_key,
                    written.event_id,
                    created=True,
                    stored_bytes=0,
                )
                return self._baseline_written(authorization, work, written, request, replayed=False)
        return self._replayed_baseline(authorization, command, request, reservation)

    def _baseline_written(
        self,
        authorization: Authorization,
        work: ScenarioUnitOfWork,
        written: BaselineWritten,
        request: BaselineRequest,
        *,
        replayed: bool,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        stored = work.scenarios.get_baseline(principal_id, written.baseline_id)
        if stored is None:  # pragma: no cover - written or replayed above
            raise InternalError()
        views, governing = self._views(work.scenarios, principal_id, stored.project_id)
        view = views[stored.baseline_id]
        payload: dict[str, Any] = {
            "baseline_id": written.baseline_id,
            "governing_event_id" if written.governing else "event_id": written.event_id,
            "action": "set_governing" if written.governing else _action_of(request),
            "seq": written.seq,
            "status": view.status.value,
            "governing": governing == stored.baseline_id,
            "replayed": replayed,
            "labels": _baseline_labels(view),
        }
        if isinstance(request, ApproveRequest):
            payload["label"] = written.label
        return self._answer(
            authorization,
            payload,
            self._roots(work, principal_id, [stored.publication_id]),
            _baseline_basis(view),
        )

    def _replayed_baseline(
        self,
        authorization: Authorization,
        command: Any,  # noqa: ANN401
        request: BaselineRequest,
        reservation: PlaneReservation,
    ) -> ScenarioAnswer:
        principal_id = authorization.principal.principal_id
        event_id = reservation.result_id
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            if event_id is None:
                raise InternalError()
            if isinstance(request, SetGoverningRequest):
                governing = scenarios.get_governing_event(principal_id, event_id)
                if governing is None:
                    raise InternalError()
                written = BaselineWritten(
                    baseline_id=governing.baseline_id,
                    event_id=event_id,
                    label=None,
                    seq=governing.seq,
                    governing=True,
                )
            else:
                stored = scenarios.get_baseline_event(principal_id, event_id)
                event = (
                    None
                    if stored is None
                    else next((item for item in stored.events if item.event_id == event_id), None)
                )
                if stored is None or event is None:
                    raise InternalError()
                written = BaselineWritten(
                    baseline_id=stored.baseline_id,
                    event_id=event_id,
                    label=event.label,
                    seq=event.seq,
                )
            return self._baseline_written(authorization, work, written, request, replayed=True)

    def _views(
        self, scenarios: ScenarioRepository, principal_id: str, project_id: str
    ) -> tuple[dict[str, BaselineView], str | None]:
        chain = scenarios.baseline_chain(principal_id, project_id)
        views = baseline_status(
            chain.events,
            eligible_publication_ids=scenarios.eligible_publication_ids(principal_id, project_id),
        )
        return views, scenarios.governing_as_of(principal_id, project_id, None)

    # ---- reads (section 15.6.2) ---------------------------------------------------------

    def _read(self, authorization: Authorization, capability: Capability) -> str:
        require_read_grant(authorization.capability_grants, capability)
        return authorization.principal.principal_id

    def list_scenarios(
        self, authorization: Authorization, command: ListScheduleScenarios
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.SCENARIOS)
        with self._unit_of_work() as work:
            if not work.schedules.owns_project(principal_id, command.project_id):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            found = work.scenarios.list_scenarios(
                principal_id,
                command.project_id,
                command.series_id,
                after=_keyset(paging),
                limit=paging.page_size + 1,
            )
            page = found[: paging.page_size]
            roots = self._roots(
                work,
                principal_id,
                [self._root_publication(work.scenarios, principal_id, item) for item in page],
            )
        last = None if not page else (page[-1].created_at, page[-1].scenario_id)
        payload = {
            "project_id": command.project_id,
            "series_id": command.series_id,
            "scenarios": [_scenario(item) for item in page],
            "page_size": paging.page_size,
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(
            authorization,
            payload,
            roots,
            _SCENARIO_BASIS,
            paging.truncation(len(found) > paging.page_size, last),
        )

    def read_scenario(
        self, authorization: Authorization, command: ReadScheduleScenario
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.VERSIONS)
        before = None if paging.position is None else _offset(paging)
        with self._unit_of_work() as work:
            scenario = work.scenarios.get_scenario(principal_id, command.scenario_id)
            if scenario is None:
                raise NotFoundError(SafeDetail.SCENARIO_ID)
            found = work.scenarios.list_versions(
                principal_id,
                command.scenario_id,
                before_version_no=before,
                limit=paging.page_size + 1,
            )
            roots = self._roots(
                work,
                principal_id,
                [self._root_publication(work.scenarios, principal_id, scenario)],
            )
        page = found[: paging.page_size]
        last = None if not page else (page[-1].version_no,)
        payload = {
            **_scenario(scenario),
            "versions": [_version(item) for item in page],
            "page_size": paging.page_size,
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(
            authorization,
            payload,
            roots,
            _SCENARIO_BASIS,
            paging.truncation(len(found) > paging.page_size, last),
        )

    def _content(
        self, work: ScenarioUnitOfWork, principal_id: str, version_id: str
    ) -> tuple[
        StoredScenarioVersion, Any, list[tuple[ScheduleSourceBinding, SchedulePublicationStatus]]
    ]:
        version = work.scenarios.get_version(principal_id, version_id)
        content = None if version is None else work.scenarios.load_content(principal_id, version_id)
        if version is None or content is None:
            raise NotFoundError(SafeDetail.VERSION_ID)
        root = self._version_root(work, principal_id, version)
        return version, content.content, self._roots(work, principal_id, [root])

    def read_version(
        self, authorization: Authorization, command: ReadScheduleScenarioVersion
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        with self._unit_of_work() as work:
            version, content, roots = self._content(work, principal_id, command.version_id)
        document = content_object(content)
        payload = {
            **_version(version),
            "data_date": document["data_date"],
            "settings": document["settings"],
            "calendars": document["calendars"],
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(authorization, payload, roots, _SCENARIO_BASIS)

    def list_version_activities(
        self, authorization: Authorization, command: ListScheduleScenarioActivities
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.SCENARIO_CONTENT)
        with self._unit_of_work() as work:
            version, content, roots = self._content(work, principal_id, command.version_id)
        ordered = sorted(content.activities, key=lambda activity: activity.key)
        page, truncation = _page_offset(paging, ordered)
        payload = {
            "version_id": version.version_id,
            "activities": [activity_object(activity) for activity in page],
            "page_size": paging.page_size,
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(authorization, payload, roots, _SCENARIO_BASIS, truncation)

    def list_version_relationships(
        self, authorization: Authorization, command: ListScheduleScenarioRelationships
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.SCENARIO_CONTENT)
        with self._unit_of_work() as work:
            version, content, roots = self._content(work, principal_id, command.version_id)
        ordered = sorted(content.relationships, key=lambda item: (item.pred, item.succ))
        page, truncation = _page_offset(paging, ordered)
        payload = {
            "version_id": version.version_id,
            "relationships": [
                {
                    "pred": item.pred,
                    "succ": item.succ,
                    "type": item.type.value,
                    "lag_minutes": item.lag_minutes,
                }
                for item in page
            ],
            "page_size": paging.page_size,
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(authorization, payload, roots, _SCENARIO_BASIS, truncation)

    def list_version_changes(
        self, authorization: Authorization, command: ListScheduleScenarioChanges
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.SCENARIO_CONTENT)
        with self._unit_of_work() as work:
            version = work.scenarios.get_version(principal_id, command.version_id)
            if version is None:
                raise NotFoundError(SafeDetail.VERSION_ID)
            verified = work.scenarios.load_change_set(principal_id, command.version_id)
            root = self._version_root(work, principal_id, version)
            roots = self._roots(work, principal_id, [root])
        ops = [] if verified is None else verified.document.get("ops", [])
        if not isinstance(ops, list):  # pragma: no cover - verified on read
            raise InternalError()
        page, truncation = _page_offset(paging, ops)
        payload = {
            "version_id": version.version_id,
            "change_report": _change_report(version),
            "ops": list(page),
            "page_size": paging.page_size,
            "labels": _SCENARIO_LABELS,
        }
        return self._answer(authorization, payload, roots, _SCENARIO_BASIS, truncation)

    def _run_document(
        self, work: ScenarioUnitOfWork, principal_id: str, cpm_run_id: str
    ) -> tuple[StoredCpmRun, Mapping[str, object], list[Any]]:
        run = work.scenarios.get_cpm_run_by_id(principal_id, cpm_run_id)
        verified = None if run is None else work.scenarios.load_cpm_result(principal_id, cpm_run_id)
        if run is None or verified is None:
            raise NotFoundError(SafeDetail.CPM_RUN_ID)
        version = work.scenarios.get_version(principal_id, run.version_id)
        if version is None:  # pragma: no cover
            raise InternalError()
        root = self._version_root(work, principal_id, version)
        return run, verified.document, self._roots(work, principal_id, [root])

    def read_cpm_run(
        self, authorization: Authorization, command: ReadScheduleCpmRun
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        with self._unit_of_work() as work:
            run, document, roots = self._run_document(work, principal_id, command.cpm_run_id)
        payload = {
            **_run(run),
            "summary": document.get("summary"),
            "issue_counts": document.get("issue_counts"),
            "issues": document.get("issues"),
            "open_starts": document.get("open_starts"),
            "open_finishes": document.get("open_finishes"),
            "critical_paths": document.get("critical_paths"),
            "labels": _RUN_LABELS,
        }
        return self._answer(authorization, payload, roots, _RUN_BASIS)

    def list_cpm_run_activities(
        self, authorization: Authorization, command: ListScheduleCpmRunActivities
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.SCENARIO_CONTENT)
        with self._unit_of_work() as work:
            run, document, roots = self._run_document(work, principal_id, command.cpm_run_id)
        rows = document.get("activities") or []
        if not isinstance(rows, list):  # pragma: no cover - verified on read
            raise InternalError()
        ordered = sorted(
            (row for row in rows if isinstance(row, dict)), key=lambda row: str(row.get("key"))
        )
        if command.critical_only:
            ordered = [row for row in ordered if row.get("critical") is True]
        page, truncation = _page_offset(paging, ordered)
        payload = {
            "cpm_run_id": run.cpm_run_id,
            "version_id": run.version_id,
            "critical_only": command.critical_only,
            "activities": list(page),
            "page_size": paging.page_size,
            "labels": _RUN_LABELS,
        }
        return self._answer(authorization, payload, roots, _RUN_BASIS, truncation)

    def list_outputs(
        self, authorization: Authorization, command: ListScheduleScenarioOutputs
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.OUTPUTS)
        with self._unit_of_work() as work:
            version = work.scenarios.get_version(principal_id, command.version_id)
            if version is None:
                raise NotFoundError(SafeDetail.VERSION_ID)
            found = work.scenarios.list_outputs(
                principal_id, command.version_id, after=_keyset(paging), limit=paging.page_size + 1
            )
            root = self._version_root(work, principal_id, version)
            roots = self._roots(work, principal_id, [root])
        page = found[: paging.page_size]
        last = None if not page else (page[-1].created_at, page[-1].output_id)
        payload = {
            "version_id": command.version_id,
            "outputs": [_output(item) for item in page],
            "page_size": paging.page_size,
            "labels": _OUTPUT_LABELS,
        }
        return self._answer(
            authorization,
            payload,
            roots,
            _OUTPUT_BASIS,
            paging.truncation(len(found) > paging.page_size, last),
        )

    def read_output(
        self, authorization: Authorization, command: ReadScheduleScenarioOutput
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        with self._unit_of_work() as work:
            output = work.scenarios.get_output(principal_id, command.output_id)
            verified = (
                None
                if output is None
                else work.scenarios.load_output(principal_id, command.output_id)
            )
            if output is None or verified is None:
                raise NotFoundError(SafeDetail.OUTPUT_ID)
            version = work.scenarios.get_version(principal_id, output.version_id)
            if version is None:  # pragma: no cover
                raise InternalError()
            root = self._version_root(work, principal_id, version)
            roots = self._roots(work, principal_id, [root])
        payload = {**_output(output), "document": dict(verified.document), "labels": _OUTPUT_LABELS}
        return self._answer(authorization, payload, roots, _OUTPUT_BASIS)

    def series_current(
        self, authorization: Authorization, command: ReadScheduleSeriesCurrent
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        with self._unit_of_work() as work:
            publications = work.scenarios.currency_publications(principal_id, command.series_id)
            series = work.schedules.get_series(principal_id, command.series_id)
            if publications is None or series is None:
                raise NotFoundError(SafeDetail.SERIES_ID)
            views, _ = self._views(work.scenarios, principal_id, series.project_id)
            effective = {view.publication_id for view in views.values() if view.effective}
            current = current_standard_update(publications, effective)
            chosen = next(
                (item for item in publications if item.publication_id == current.publication_id),
                None,
            )
            roots = self._roots(
                work,
                principal_id,
                [] if current.publication_id is None else [current.publication_id],
            )
        payload = {
            "series_id": command.series_id,
            "current_publication_id": current.publication_id,
            "same_data_date_ambiguity": current.same_data_date_ambiguity,
            "data_date": None if chosen is None else _day(chosen.data_date),
            "order_key": (
                None
                if chosen is None
                else [_day(chosen.data_date), _instant(chosen.admitted_at), chosen.publication_id]
            ),
            "labels": _CURRENT_LABELS,
        }
        return self._answer(authorization, payload, roots, _CURRENT_BASIS)

    def list_match_decisions(
        self, authorization: Authorization, command: ListScheduleSeriesMatchDecisions
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.MATCH_DECISIONS)
        with self._unit_of_work() as work:
            if not work.schedules.owns_project(principal_id, command.project_id):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            found = work.scenarios.list_match_decisions(
                principal_id, command.project_id, after=_keyset(paging), limit=paging.page_size + 1
            )
            page = found[: paging.page_size]
            roots = self._roots(
                work,
                principal_id,
                [
                    publication
                    for record in page
                    for publication in (
                        record.intake_publication_id,
                        record.resulting_publication_id,
                    )
                    if publication is not None
                ],
            )
        last = (
            None
            if not page or page[-1].created_at is None
            else (page[-1].created_at, page[-1].decision_id)
        )
        payload = {
            "project_id": command.project_id,
            "decisions": [_decision(record) for record in page],
            "page_size": paging.page_size,
            "labels": _MATCH_LABELS,
        }
        return self._answer(
            authorization,
            payload,
            roots,
            _MATCH_BASIS,
            paging.truncation(len(found) > paging.page_size, last),
        )

    def list_baselines(
        self, authorization: Authorization, command: ListScheduleBaselines
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        paging = _paging(authorization, command, ScheduleCursorOrder.BASELINES)
        wanted = None if command.status is None else BaselineStatus(command.status)
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            if not work.schedules.owns_project(principal_id, command.project_id):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            views, governing = self._views(scenarios, principal_id, command.project_id)
            page: list[StoredBaseline] = []
            after = _keyset(paging)
            more = False
            while True:
                found = scenarios.list_baselines(
                    principal_id,
                    command.project_id,
                    command.series_id,
                    after=after,
                    limit=paging.page_size + 1,
                )
                for item in found:
                    if wanted is None or views[item.baseline_id].status is wanted:
                        if len(page) == paging.page_size:
                            more = True
                            break
                        page.append(item)
                if more or len(found) <= paging.page_size:
                    break
                after = (found[-1].created_at, found[-1].baseline_id)
            roots = self._roots(work, principal_id, [item.publication_id for item in page])
        last = None if not page else (page[-1].created_at, page[-1].baseline_id)
        payload = {
            "project_id": command.project_id,
            "series_id": command.series_id,
            "status": command.status,
            "governing_baseline_id": governing,
            "baselines": [
                _baseline(item, views[item.baseline_id], governing=governing, history=False)
                for item in page
            ],
            "page_size": paging.page_size,
        }
        return self._answer(
            authorization,
            payload,
            roots,
            ("schedule_baseline", "operator_approved", "proposed"),
            paging.truncation(more, last),
        )

    def read_baseline(
        self, authorization: Authorization, command: ReadScheduleBaseline
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        with self._unit_of_work() as work:
            stored = work.scenarios.get_baseline(principal_id, command.baseline_id)
            if stored is None:
                raise NotFoundError(SafeDetail.BASELINE_ID)
            views, governing = self._views(work.scenarios, principal_id, stored.project_id)
            roots = self._roots(work, principal_id, [stored.publication_id])
        view = views[stored.baseline_id]
        payload = _baseline(stored, view, governing=governing, history=True)
        return self._answer(authorization, payload, roots, _baseline_basis(view))

    def governing(
        self, authorization: Authorization, command: ReadGoverningScheduleBaseline
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        as_of = None if command.as_of is None else datetime.fromisoformat(command.as_of)
        with self._unit_of_work() as work:
            scenarios = work.scenarios
            if not work.schedules.owns_project(principal_id, command.project_id):
                raise NotFoundError(SafeDetail.PROJECT_ID)
            baseline_id = scenarios.governing_as_of(principal_id, command.project_id, as_of)
            views, now = self._views(scenarios, principal_id, command.project_id)
            stored = (
                None if baseline_id is None else scenarios.get_baseline(principal_id, baseline_id)
            )
            roots = self._roots(
                work, principal_id, [] if stored is None else [stored.publication_id]
            )
        payload: dict[str, Any] = {
            "project_id": command.project_id,
            "baseline_id": baseline_id,
            "as_of": command.as_of,
            "basis": "as_recorded",
            "baseline": (
                None
                if stored is None
                else _baseline(stored, views[stored.baseline_id], governing=now, history=False)
            ),
        }
        basis = (
            ("schedule_baseline", "operator_approved")
            if stored is not None
            else ("schedule_baseline",)
        )
        return self._answer(authorization, payload, roots, basis)

    def compare(
        self, authorization: Authorization, command: CompareScheduleBaseline
    ) -> ScenarioAnswer:
        principal_id = self._read(authorization, command.capability)
        with self._unit_of_work() as work:
            stored, view = self._eligible_baseline(
                work.scenarios, principal_id, command.baseline_id, SafeDetail.BASELINE_ID
            )
            target = work.schedules.get_publication_detail(principal_id, command.to_publication_id)
            if target is None:
                raise NotFoundError(SafeDetail.TO_PUBLICATION_ID)
            if target.publication.series_id != stored.series_id:
                raise InvalidRequestError(SafeDetail.TO_PUBLICATION_ID)
        delta = ScheduleApplication(self._schedule_unit_of_work).list_changes(
            authorization,
            ListScheduleChanges(
                from_publication_id=stored.publication_id,
                to_publication_id=command.to_publication_id,
                change_kind=command.change_kind,
                page_size=command.page_size,
                cursor=command.cursor,
            ),
        )
        approval = next((event for event in stored.events if event.action.value == "approve"), None)
        payload = {
            **delta.payload,
            "baseline": {
                "baseline_id": stored.baseline_id,
                "label": view.label,
                "effective_type": None
                if view.effective_type is None
                else view.effective_type.value,
                "effective_from": _day(view.effective_from),
                "provenance": None if approval is None else _provenance(approval.provenance),
            },
            "labels": _baseline_labels(view),
        }
        disclosure = delta.disclosure.model_copy(
            update={
                "trust": Trust(
                    level=delta.disclosure.trust.level,
                    basis=(*delta.disclosure.trust.basis, "schedule_baseline", "operator_approved"),
                )
            }
        )
        return ScenarioAnswer(payload=self._reader(authorization, payload), disclosure=disclosure)


# ---- module helpers --------------------------------------------------------------------


def _without_proposer_clients(document: Any) -> Any:  # noqa: ANN401
    """Section 15.4: a proposer's or approver's `client_id`, withheld like the rows'."""
    if isinstance(document, dict):
        return {
            key: (
                {**value, "client_id": None}
                if key in {"proposer", "approver"}
                and isinstance(value, dict)
                and "client_id" in value
                else _without_proposer_clients(value)
            )
            for key, value in document.items()
        }
    if isinstance(document, list):
        return [_without_proposer_clients(item) for item in document]
    return document


def _refuse_a_conflict(replay: PlaneReservation | None) -> None:
    """A probed key held by another request digest is `conflict(idempotency_key)`."""
    if replay is not None and replay.outcome is PlaneReservationOutcome.CONFLICT:
        raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)


def _owned_version(
    scenarios: ScenarioRepository, principal_id: str, version_id: str
) -> StoredScenarioVersion | None:
    try:
        return scenarios.get_version(principal_id, version_id)
    except ValueError:
        return None


def _owned_run(
    scenarios: ScenarioRepository, principal_id: str, cpm_run_id: str
) -> StoredCpmRun | None:
    try:
        return scenarios.get_cpm_run_by_id(principal_id, cpm_run_id)
    except ValueError:
        return None


def _action_of(request: BaselineRequest) -> str:
    match request:
        case ProposeRequest():
            return "propose"
        case ApproveRequest():
            return "approve"
        case RejectRequest():
            return "reject"
        case WithdrawRequest():
            return "withdraw"
        case RevokeRequest():
            return "revoke"
    return "set_governing"


def _baseline_basis(view: BaselineView) -> tuple[str, ...]:
    approved = view.effective_type is not None
    return ("schedule_baseline", "operator_approved" if approved else "proposed")
