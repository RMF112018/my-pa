"""The backfill dry run, record lineage S3 (S3 contract sections 4.2, 5, 6 and 8.3).

`plan_backfill` (`records.backfill.plan`) and `report_backfill`
(`records.backfill.report`) take the unit of work `ApplicationService.invoke`
has **already opened** and the authenticated `principal_id` as a plain
parameter. They open no transaction: a plan call is one transaction, so an
interrupted call leaves the previous checkpoint and calling again resumes.

**A plan writes ledger rows only.** It writes no link, no fact and no commit
mark (section 6.2 step 1b exempts it), and nothing here materializes an item:
`source_backed_accepted` is a classification in the report only, and the
review path for a `review_candidate` is the operator's own attested assert
(section 12, D-07). The apply is a later, operator-gated package (section 11).

**Order of `records.backfill.plan`** (section 6.3): request digest;
reservation (a replay answers from the run and the items classified up to the
stored checkpoint, which never change once classified); then

* *without `run_id`*: the run and its whole population in one statement
  (`LineageBackfillRepository.enumerate_run`), state `enumerated`, checkpoint 0;
* *with `run_id`*: the run `FOR UPDATE` (`not_found` / `run_id` when absent or
  foreign); `expected_checkpoint` must equal its `classified_count`
  (`conflict` / `checkpoint`); the next `batch_size` items in `item_no` order,
  each first re-deriving its source digest in SQL -- a different digest is
  `unresolved` / `source_changed`, quarantined, whatever it would otherwise be
  -- and otherwise classified by `domain.lineage.backfill.classify`, a pure
  function of its stored source document; each candidate's existing link (any
  context, any state) at the run's `commit_seq_cutoff`; the settlements; the
  checkpoint; and, when every item is classified, the plan digest and state
  `classified`.

So a resumed run and an uninterrupted one classify identical items and reach
the same `plan_digest` (AT-025): nothing here reads wall time into a class.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from my_pa.application.errors import ConflictError, NotFoundError, SafeDetail
from my_pa.contracts.ports import (
    BackfillItemRecord,
    BackfillLinkEndpoints,
    BackfillPendingSource,
    BackfillRunRecord,
    BackfillSettlement,
    LineageWriteRequestRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.lineage_backfill import BackfillItemView, BackfillRunView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.backfill import (
    BackfillClassification,
    CaptureVersionPin,
    classify,
    lineage_family_of_reference,
    plan_digest,
)
from my_pa.domain.lineage.canonical import request_digest
from my_pa.domain.lineage.vocabulary import ExistingLinkState, RecordFamily, RelationType
from my_pa.domain.lineage_backfill.vocabulary import (
    BackfillClass,
    BackfillReason,
    BackfillRunState,
    BackfillSourceKind,
)
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    from my_pa.application.lineage_authority import LineageAuthority

__all__ = [
    "DEFAULT_BACKFILL_BATCH",
    "BackfillPlanRequest",
    "BackfillPlanResult",
    "BackfillReportRequest",
    "BackfillReportResult",
    "plan_backfill",
    "plan_document",
    "report_backfill",
]

_PLAN: Final = Capability.RECORDS_BACKFILL_PLAN.value
#: Section 8.3: a plan classifies 200 items per call unless told otherwise.
DEFAULT_BACKFILL_BATCH: Final = 200


@dataclass(frozen=True, slots=True)
class BackfillPlanRequest:
    """`records.backfill.plan`, parsed: enumerate (no `run_id`) or classify a batch."""

    run_id: str | None
    expected_checkpoint: int | None
    batch_size: int | None


@dataclass(frozen=True, slots=True)
class BackfillReportRequest:
    """`records.backfill.report`, parsed."""

    run_id: str
    page_size: int
    after: int | None
    classification: BackfillClass | None


@dataclass(frozen=True, slots=True)
class BackfillPlanResult:
    """One plan call's run and the items it classified (none for an enumeration)."""

    run: BackfillRunView
    items: tuple[BackfillItemView, ...]
    replayed: bool

    def to_payload(self) -> dict[str, Any]:
        """The section 8.3 answer."""
        return {
            "run": self.run.to_canonical_dict(),
            "items": [item.to_canonical_dict() for item in self.items],
            "replayed": self.replayed,
        }


@dataclass(frozen=True, slots=True)
class BackfillReportResult:
    """One report page: the run, its census, counts, late sources and items."""

    run: BackfillRunView
    census: Mapping[str, object]
    counts: Mapping[str, object]
    late_source_count: int
    items: tuple[BackfillItemView, ...]
    next_cursor: int | None

    def to_payload(self) -> dict[str, Any]:
        """The section 8.3 answer."""
        return {
            "run": self.run.to_canonical_dict(),
            "census": dict(self.census),
            "counts": dict(self.counts),
            "late_source_count": self.late_source_count,
            "items": [item.to_canonical_dict() for item in self.items],
            "next_cursor": self.next_cursor,
        }


def plan_document(request: BackfillPlanRequest) -> dict[str, object]:
    """The request digest's document (section 5.4): optional fields `null` when omitted."""
    return {
        "run_id": request.run_id,
        "expected_checkpoint": request.expected_checkpoint,
        "batch_size": request.batch_size,
    }


def _run_view(
    run: BackfillRunRecord,
    *,
    classified_count: int | None = None,
) -> BackfillRunView:
    """The run's view; `classified_count` rebuilds it as it stood at that checkpoint.

    A checkpoint short of the population is a run still `enumerated` (a run is
    classified exactly when its checkpoint reaches its population, section 4.2).
    """
    count = run.classified_count if classified_count is None else classified_count
    classified = count == run.population_count and run.state == BackfillRunState.CLASSIFIED
    return BackfillRunView(
        run_id=run.run_id,
        state=BackfillRunState.CLASSIFIED if classified else BackfillRunState.ENUMERATED,
        validator_version=run.validator_version,
        population_count=run.population_count,
        classified_count=count,
        plan_digest=run.plan_digest if classified else None,
        source_cutoff_at=run.source_cutoff_at,
        created_at=run.created_at,
        classified_at=run.classified_at if classified else None,
    )


def _candidate_relation(candidate: str | None) -> RelationType | None:
    if candidate is None:
        return None
    loaded = json.loads(candidate)
    return RelationType(loaded["relation_type"])


def _item_view(item: BackfillItemRecord) -> BackfillItemView:
    return BackfillItemView(
        item_no=item.item_no,
        source_kind=BackfillSourceKind(item.source_kind),
        source_family=item.source_family,
        source_id=item.source_id,
        source_ref=item.source_ref,
        classification=None if item.classification is None else BackfillClass(item.classification),
        reason=None if item.reason is None else BackfillReason(item.reason),
        quarantined=item.quarantined,
        candidate_relation=_candidate_relation(item.candidate),
        existing_link_id=item.existing_link_id,
        existing_link_state=(
            None
            if item.existing_link_state is None
            else ExistingLinkState(item.existing_link_state)
        ),
    )


# --- records.backfill.plan ------------------------------------------------------------


def plan_backfill(
    uow: UnitOfWork,
    principal_id: str,
    request: BackfillPlanRequest,
    idempotency_key: str,
    authority: LineageAuthority,
    now: datetime,
) -> BackfillPlanResult:
    """Enumerate a new run, or classify the next batch of one (section 8.3)."""
    at = ensure_utc(now)
    issues = uow.issues
    digest = request_digest(_PLAN, principal_id, plan_document(request))
    prior = issues.reserve_write_request(
        principal_id,
        _PLAN,
        idempotency_key,
        digest,
        created_at=at,
        # S3.1 section 5.2: the writer, recorded on every later request row.
        decision_channel=authority.decision_channel.value,
    )
    if prior is not None:
        return _replayed(uow, principal_id, request, prior)
    # No commit mark: a plan writes no fact (section 6.2 step 1b).
    if request.run_id is None:
        run = uow.lineage_backfill.enumerate_run(
            principal_id,
            issue_identifier(IdKind.LINEAGE_BACKFILL_RUN),
            created_at=at,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
        )
        issues.complete_write_request(
            principal_id,
            _PLAN,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_backfill_run_id=run.run_id,
            result_backfill_checkpoint=0,
        )
        return BackfillPlanResult(run=_run_view(run), items=(), replayed=False)
    run, items = _classify_batch(uow, principal_id, request, request.run_id, at)
    issues.complete_write_request(
        principal_id,
        _PLAN,
        idempotency_key,
        request_digest=digest,
        completed_at=at,
        result_backfill_run_id=run.run_id,
        result_backfill_checkpoint=run.classified_count,
    )
    return BackfillPlanResult(
        run=_run_view(run), items=tuple(_item_view(item) for item in items), replayed=False
    )


def _classify_batch(
    uow: UnitOfWork,
    principal_id: str,
    request: BackfillPlanRequest,
    run_id: str,
    at: datetime,
) -> tuple[BackfillRunRecord, tuple[BackfillItemRecord, ...]]:
    ledger = uow.lineage_backfill
    # Section 6.2 step 1a: the run row, before anything else of this call.
    run = ledger.read_run(principal_id, run_id, for_update=True)
    if run is None:
        raise NotFoundError(SafeDetail.RUN_ID)
    if request.expected_checkpoint != run.classified_count:
        raise ConflictError(SafeDetail.CHECKPOINT)
    size = DEFAULT_BACKFILL_BATCH if request.batch_size is None else request.batch_size
    pending = ledger.pending_sources(principal_id, run_id, after=run.classified_count, limit=size)
    settled = _settlements(uow, principal_id, run, pending)
    ledger.settle_items(principal_id, run_id, settled, classified_at=at)
    count = run.classified_count + len(settled)
    digest: str | None = None
    if count == run.population_count:
        every = ledger.items(principal_id, run_id, after=0)
        digest = plan_digest(
            run_id=run_id,
            validator_version=run.validator_version,
            items=[
                (
                    item.item_no,
                    item.source_digest,
                    str(item.classification),
                    str(item.reason),
                    item.candidate_identity,
                )
                for item in every
            ],
        )
    if run.state == BackfillRunState.ENUMERATED and (settled or digest is not None):
        ledger.advance_run(
            principal_id,
            run_id,
            classified_count=count,
            plan_digest=digest,
            classified_at=None if digest is None else at,
        )
    advanced = ledger.read_run(principal_id, run_id)
    if advanced is None:  # pragma: no cover - locked above
        raise RepositoryFailureError
    items = ledger.items(principal_id, run_id, after=run.classified_count, through=count)
    return advanced, items


def _settlements(
    uow: UnitOfWork,
    principal_id: str,
    run: BackfillRunRecord,
    pending: Sequence[BackfillPendingSource],
) -> list[BackfillSettlement]:
    """Classify each pending source; a changed source is quarantined first."""
    ledger = uow.lineage_backfill
    unchanged = [source for source in pending if source.current_digest == source.item.source_digest]
    documents = {source.item.item_no: json.loads(source.current_document) for source in unchanged}
    version_ids = {
        str(documents[source.item.item_no]["facts"]["version_id"])
        for source in unchanged
        if source.item.source_kind == BackfillSourceKind.WORK_ORIGIN_ASSERTION
        and documents[source.item.item_no]["facts"]["version_id"] is not None
    }
    pins: Mapping[str, CaptureVersionPin] = ledger.capture_version_pins(principal_id, version_ids)
    references: set[tuple[RecordFamily, str]] = set()
    for source in unchanged:
        if source.item.source_kind == BackfillSourceKind.SITUATION_OBJECT_REF:
            family = lineage_family_of_reference(source.item.source_ref)
            if family is not None:
                references.add((family, source.item.source_ref))
    owned = ledger.owned_references(principal_id, references)
    classified: dict[int, BackfillClassification] = {}
    for source in pending:
        item = source.item
        if source.current_digest != item.source_digest:
            classified[item.item_no] = BackfillClassification(
                classification=BackfillClass.UNRESOLVED, reason=BackfillReason.SOURCE_CHANGED
            )
            continue
        facts = documents[item.item_no]["facts"]
        version_id = facts.get("version_id") if isinstance(facts, dict) else None
        family = lineage_family_of_reference(item.source_ref)
        classified[item.item_no] = classify(
            source.current_document,
            principal_id=principal_id,
            pin=None if version_id is None else pins.get(str(version_id)),
            owned_reference=family is not None and (family, item.source_ref) in owned,
        )
    endpoints = {
        number: BackfillLinkEndpoints(
            from_family=chosen.candidate.from_ref.family.value,
            from_id=chosen.candidate.from_ref.record_id,
            relation_type=chosen.candidate.relation_type.value,
            to_family=chosen.candidate.to_ref.family.value,
            to_id=chosen.candidate.to_ref.record_id,
        )
        for number, chosen in classified.items()
        if chosen.candidate is not None
    }
    existing = ledger.existing_links(
        principal_id, set(endpoints.values()), cutoff=run.commit_seq_cutoff
    )
    settlements: list[BackfillSettlement] = []
    for source in pending:
        number = source.item.item_no
        chosen = classified[number]
        found = existing.get(endpoints[number]) if number in endpoints else None
        settlements.append(
            BackfillSettlement(
                item_no=number,
                classification=chosen.classification.value,
                reason=chosen.reason.value,
                candidate_identity=None if chosen.candidate is None else chosen.candidate.identity,
                candidate=None if chosen.candidate is None else chosen.candidate.document,
                existing_link_id=None if found is None else found.link_id,
                existing_link_state=(
                    ExistingLinkState.NONE.value if found is None else found.lifecycle_state
                ),
                quarantined=chosen.quarantined,
            )
        )
    return settlements


def _replayed(
    uow: UnitOfWork,
    principal_id: str,
    request: BackfillPlanRequest,
    prior: LineageWriteRequestRecord,
) -> BackfillPlanResult:
    """Section 6.3 replay: the run and the items this call classified, as they stood."""
    run_id, checkpoint = prior.result_backfill_run_id, prior.result_backfill_checkpoint
    if run_id is None or checkpoint is None:
        raise RepositoryFailureError
    ledger = uow.lineage_backfill
    run = ledger.read_run(principal_id, run_id)
    if run is None:
        raise RepositoryFailureError
    if request.run_id is None:
        # An enumeration classified nothing: the run as it was enumerated.
        enumerated = BackfillRunView(
            run_id=run.run_id,
            state=BackfillRunState.ENUMERATED,
            validator_version=run.validator_version,
            population_count=run.population_count,
            classified_count=0,
            plan_digest=None,
            source_cutoff_at=run.source_cutoff_at,
            created_at=run.created_at,
            classified_at=None,
        )
        return BackfillPlanResult(run=enumerated, items=(), replayed=True)
    start = request.expected_checkpoint or 0
    items = ledger.items(principal_id, run_id, after=start, through=checkpoint)
    return BackfillPlanResult(
        run=_run_view(run, classified_count=checkpoint),
        items=tuple(_item_view(item) for item in items),
        replayed=True,
    )


# --- records.backfill.report ----------------------------------------------------------


def _counts(uow: UnitOfWork, principal_id: str, run_id: str) -> dict[str, object]:
    """Per class, per reason, quarantined and per existing-link state: every token present."""
    by_class = {member.value: 0 for member in BackfillClass}
    by_reason = {member.value: 0 for member in BackfillReason}
    by_link = {member.value: 0 for member in ExistingLinkState}
    quarantined = 0
    for row in uow.lineage_backfill.count_rows(principal_id, run_id):
        by_class[row.classification] += row.count
        by_reason[row.reason] += row.count
        by_link[row.existing_link_state] += row.count
        if row.quarantined:
            quarantined += row.count
    return {
        "classification": by_class,
        "reason": by_reason,
        "quarantined": quarantined,
        "existing_link_state": by_link,
    }


def report_backfill(
    uow: UnitOfWork, principal_id: str, request: BackfillReportRequest
) -> BackfillReportResult:
    """One run's census, counts, late sources and a page of its items (section 8.3)."""
    ledger = uow.lineage_backfill
    run = ledger.read_run(principal_id, request.run_id)
    if run is None:
        raise NotFoundError(SafeDetail.RUN_ID)
    size = request.page_size
    page = ledger.items(
        principal_id,
        run.run_id,
        after=request.after or 0,
        limit=size + 1,
        classification=None if request.classification is None else request.classification.value,
    )
    shown = page[:size]
    return BackfillReportResult(
        run=_run_view(run),
        census=run.census,
        counts=_counts(uow, principal_id, run.run_id),
        late_source_count=ledger.late_source_count(principal_id, run.run_id),
        items=tuple(_item_view(item) for item in shown),
        next_cursor=shown[-1].item_no if len(page) > size else None,
    )
