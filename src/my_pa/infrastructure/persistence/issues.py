"""The record lineage S1 Issue plane, behind `contracts.ports.IssueRepository`.

Written here and nowhere else: Issue `situations` rows (`kind =
'issue_workstream'`), `issue_revisions` and (S2) their closure evidence
`issue_revision_evidence`, `project_situations` rows that name an Issue,
`issue_project_membership_events`, the `lineage_write_requests` rows, and the
evidence anchors every lineage write cites (`lineage_evidence_anchors`). Read
and locked, never written: `projects`, `meeting_note_versions`, `captures`,
`capture_versions` and the Capture lifecycle projection.

**The partition is reached through the guard.** Every SELECT is built through
`principal_scoped` or `_mine` (`partition_criterion`), every UPDATE composes
`_mine`, every INSERT composes `_bound` (`principal_bound_values`), and every
correlated predicate composes `matching_partition_criterion`. The Principal is
only ever a parameter.

**Locks are the section 6.2 order, and the caller sequences them.** The
Issue is locked `FOR UPDATE` only by a write that changes it; a Project, an
Issue a link write names, a note version, a Capture root (`share_capture_root`,
which an archive's `FOR NO KEY UPDATE` waits on) and a Capture version are
`FOR SHARE`; the `project_situations` triplet row is `FOR UPDATE` after an
`INSERT ... ON CONFLICT DO NOTHING`. Reads take no locks.

**A lost race is `TransactionConflictError`.** Every statement runs through
`_run`, which turns a deadlock or serialization failure (`is_transaction_conflict`)
into the port's conflict, so the application answers `conflict` (section 6.2).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any, Final, cast

from sqlalchemy import (
    ColumnElement,
    Table,
    and_,
    exists,
    func,
    insert,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import (
    IssueCursorError,
    IssueListPage,
    IssueRecord,
    IssueRepository,
    IssueRevisionRecord,
    LineageFactCut,
    LineageIdempotencyConflictError,
    LineageLinkEvidence,
    LineageReadTimeoutError,
    LineageSourceVersion,
    LineageWriterBudget,
    LineageWriteRequestRecord,
    ProjectLinkEventRecord,
    RepositoryFailureError,
    TransactionConflictError,
    is_transaction_conflict,
)
from my_pa.domain.capture.lifecycle import CaptureLifecycleState
from my_pa.domain.common.classification import Classification
from my_pa.domain.lineage.canonical import anchor_identity
from my_pa.domain.lineage.model import EvidenceAnchor
from my_pa.domain.lineage.vocabulary import (
    CLIENT_DECISION_CHANNELS,
    AcceptanceBasis,
    EvidenceRole,
    EvidenceSourceFamily,
    IssueProjectMembershipAction,
    IssueProjectMembershipState,
    IssueRevisionAction,
    SituationKind,
    SourceVersionKind,
)
from my_pa.domain.situation.situation import SituationState
from my_pa.infrastructure.persistence.capture_lifecycle import (
    latest_lifecycle,
    share_capture_root,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    issue_project_membership_events,
    issue_revision_evidence,
    issue_revisions,
    lineage_commit_marks,
    lineage_evidence_anchors,
    lineage_write_request_links,
    lineage_write_requests,
    meeting_note_versions,
    project_situations,
    projects,
    situations,
)

__all__ = ["SqlIssueRepository"]

_ISSUE: Final = SituationKind.ISSUE_WORKSTREAM.value

#: The named primary key of `lineage_write_requests`, the one conflict a
#: reservation absorbs; a conflict on any other constraint still raises.
_WRITE_REQUEST_KEY: Final = "lineage_write_requests_pkey"

#: A second reference to the event ledger, for the "no later event" test.
_LATER: Final = cast(Table, issue_project_membership_events.alias("later_event"))

_ISSUE_COLUMNS: Final = (
    situations.c.situation_id,
    situations.c.version,
    situations.c.state,
    situations.c.title,
    situations.c.description,
    situations.c.opened_at,
    situations.c.created_at,
    situations.c.updated_at,
    situations.c.closed_at,
    situations.c.outcome,
)

_EVENT_COLUMNS: Final = (
    issue_project_membership_events.c.membership_event_id,
    issue_project_membership_events.c.project_id,
    issue_project_membership_events.c.issue_id,
    issue_project_membership_events.c.revision_no,
    issue_project_membership_events.c.predecessor_revision_no,
    issue_project_membership_events.c.action,
    issue_project_membership_events.c.state,
    issue_project_membership_events.c.evidence_anchor_id,
    issue_project_membership_events.c.reason,
    issue_project_membership_events.c.acceptance_basis,
    issue_project_membership_events.c.authority_class,
    issue_project_membership_events.c.decision_channel,
    issue_project_membership_events.c.source_capability,
    issue_project_membership_events.c.recorded_at,
    issue_project_membership_events.c.asserting_client_id,
    issue_project_membership_events.c.user_directed_claim,
    project_situations.c.project_situation_id,
)


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


#: PostgreSQL's `query_canceled`: a statement that outran `statement_timeout`.
_QUERY_CANCELED: Final = "57014"


def _run[ResultT](statement: Callable[[], ResultT]) -> ResultT:
    """Run `statement`; a deadlock or serialization victim is `TransactionConflictError`.

    Any other store failure propagates unchanged. The `raise` is outside the
    handler, so the driver error is not left in `__context__`.
    """
    conflict = False
    timed_out = False
    try:
        return statement()
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == _QUERY_CANCELED:
            # S3 section 7.2 step 5 (FR3-F08): a lineage statement that outran
            # its `statement_timeout` answers `unavailable`, never a fault.
            timed_out = True
        elif not is_transaction_conflict(error):
            raise
        else:
            conflict = True
    if timed_out:
        raise LineageReadTimeoutError("a lineage statement timed out")
    if conflict:
        raise TransactionConflictError("the transaction lost a race")
    raise AssertionError("unreachable")  # pragma: no cover


def _to_issue(row: Row[Any]) -> IssueRecord:
    return IssueRecord(
        issue_id=row.situation_id,
        version=row.version,
        state=SituationState(row.state),
        title=row.title,
        description=row.description,
        opened_at=row.opened_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        outcome=row.outcome,
    )


def anchor_from_row(row: Row[Any]) -> EvidenceAnchor:
    """One stored anchor, with the role its evidence row gives it."""
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily(row.source_family),
        source_root_id=row.source_root_id,
        source_version_kind=SourceVersionKind(row.source_version_kind),
        source_version_id=row.source_version_id,
        source_version_no=row.source_version_no,
        source_sha256=row.source_sha256,
        passage_start_cp=row.passage_start_cp,
        passage_end_cp=row.passage_end_cp,
        passage_sha256=row.passage_sha256,
        role=EvidenceRole(row.role),
    )


def _to_revision(
    row: Row[Any], evidence: tuple[LineageLinkEvidence, ...] = ()
) -> IssueRevisionRecord:
    return IssueRevisionRecord(
        issue_id=row.issue_id,
        version=row.version,
        revision_id=row.revision_id,
        predecessor_version=row.predecessor_version,
        action=IssueRevisionAction(row.action),
        state=SituationState(row.state),
        title=row.title,
        description=row.description,
        authority_class=row.authority_class,
        decision_channel=row.decision_channel,
        source_capability=row.source_capability,
        recorded_at=row.recorded_at,
        closed_at=row.closed_at,
        outcome=row.outcome,
        reason=row.reason,
        evidence=evidence,
        evidence_set_digest=row.evidence_set_digest,
    )


def _to_event(row: Row[Any]) -> ProjectLinkEventRecord:
    return ProjectLinkEventRecord(
        membership_event_id=row.membership_event_id,
        project_id=row.project_id,
        issue_id=row.issue_id,
        project_situation_id=row.project_situation_id,
        revision_no=row.revision_no,
        predecessor_revision_no=row.predecessor_revision_no,
        action=IssueProjectMembershipAction(row.action),
        state=IssueProjectMembershipState(row.state),
        evidence_anchor_id=row.evidence_anchor_id,
        reason=row.reason,
        acceptance_basis=row.acceptance_basis,
        authority_class=row.authority_class,
        decision_channel=row.decision_channel,
        source_capability=row.source_capability,
        recorded_at=row.recorded_at,
        asserting_client_id=row.asserting_client_id,
        user_directed_claim=bool(row.user_directed_claim),
    )


def _is_issue(principal_id: str) -> list[ColumnElement[bool]]:
    return [_mine(situations, principal_id), situations.c.kind == _ISSUE]


def _events_with_link() -> Any:  # noqa: ANN401 - a SQLAlchemy join
    return issue_project_membership_events.join(
        project_situations,
        and_(
            matching_partition_criterion(project_situations, issue_project_membership_events),
            project_situations.c.project_id == issue_project_membership_events.c.project_id,
            project_situations.c.situation_id == issue_project_membership_events.c.issue_id,
        ),
    )


def _no_later_event() -> ColumnElement[bool]:
    """The event is its link's latest: no event of the same triplet follows it."""
    return ~exists(
        select(_LATER.c.membership_event_id).where(
            matching_partition_criterion(_LATER, issue_project_membership_events),
            _LATER.c.project_id == issue_project_membership_events.c.project_id,
            _LATER.c.issue_id == issue_project_membership_events.c.issue_id,
            _LATER.c.revision_no > issue_project_membership_events.c.revision_no,
        )
    )


class SqlIssueRepository(IssueRepository):
    """`IssueRepository`, over the general unit of work's `Connection`.

    Takes the connection rather than opening one: the caller owns the
    transaction, and this class only issues statements on it.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    # --- write-request arbitration ---------------------------------------

    def reserve_write_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        request_digest: str,
        *,
        created_at: datetime,
        decision_channel: str | None = None,
        asserting_client_id: str | None = None,
    ) -> LineageWriteRequestRecord | None:
        request = lineage_write_requests
        inserted = _run(
            lambda: self._connection.execute(
                pg_insert(request)
                .values(
                    _bound(
                        request,
                        principal_id,
                        {
                            "capability": capability,
                            "idempotency_key": idempotency_key,
                            "request_digest": request_digest,
                            "created_at": created_at,
                            # S3.1 section 5.2: the writer, immutable from here.
                            "decision_channel": decision_channel,
                            "asserting_client_id": asserting_client_id,
                        },
                    )
                )
                .on_conflict_do_nothing(constraint=_WRITE_REQUEST_KEY)
                .returning(request.c.capability)
            ).first()
        )
        if inserted is not None:
            return None
        # `ON CONFLICT` waited for the transaction holding the key, so this
        # read sees its committed outcome.
        winner = _run(
            lambda: self._connection.execute(
                select(
                    request.c.capability,
                    request.c.request_digest,
                    request.c.completed_at,
                    request.c.result_issue_id,
                    request.c.result_issue_version,
                    request.c.result_membership_event_id,
                    request.c.result_link_id,
                    request.c.result_link_revision_no,
                    request.c.result_created,
                    request.c.result_handoff_id,
                    request.c.result_record_family,
                    request.c.result_record_id,
                    request.c.result_handoff_correction_id,
                    request.c.result_backfill_run_id,
                    request.c.result_backfill_checkpoint,
                    request.c.commit_seq,
                ).where(
                    _mine(request, principal_id),
                    request.c.capability == capability,
                    request.c.idempotency_key == idempotency_key,
                )
            ).one_or_none()
        )
        if winner is None:
            raise RepositoryFailureError
        if winner.request_digest != request_digest:
            raise LineageIdempotencyConflictError()
        if winner.completed_at is None:
            # Never committed reserved (`a_lineage_write_request_is_never_left_reserved`).
            raise RepositoryFailureError
        return LineageWriteRequestRecord(
            capability=winner.capability,
            request_digest=winner.request_digest,
            completed_at=winner.completed_at,
            result_issue_id=winner.result_issue_id,
            result_issue_version=winner.result_issue_version,
            result_membership_event_id=winner.result_membership_event_id,
            result_link_id=winner.result_link_id,
            result_link_revision_no=winner.result_link_revision_no,
            result_created=winner.result_created,
            result_handoff_id=winner.result_handoff_id,
            result_record_family=winner.result_record_family,
            result_record_id=winner.result_record_id,
            result_handoff_correction_id=winner.result_handoff_correction_id,
            result_backfill_run_id=winner.result_backfill_run_id,
            result_backfill_checkpoint=winner.result_backfill_checkpoint,
            commit_seq=winner.commit_seq,
        )

    def complete_write_request(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        *,
        request_digest: str,
        completed_at: datetime,
        result_issue_id: str | None = None,
        result_issue_version: int | None = None,
        result_membership_event_id: str | None = None,
        result_link_id: str | None = None,
        result_link_revision_no: int | None = None,
        result_created: bool | None = None,
        result_handoff_id: str | None = None,
        result_record_family: str | None = None,
        result_record_id: str | None = None,
        result_handoff_correction_id: str | None = None,
        result_backfill_run_id: str | None = None,
        result_backfill_checkpoint: int | None = None,
    ) -> None:
        request = lineage_write_requests
        marks = lineage_commit_marks
        # S3 section 4.1: the mark this transaction took for the Principal, if any
        # (`take_commit_mark`); none for a backfill plan, which writes no fact.
        held_mark = (
            select(marks.c.commit_seq)
            .where(
                _mine(marks, principal_id),
                marks.c.recorded_xact == func.pg_current_xact_id(),
            )
            .scalar_subquery()
        )
        completed = _run(
            lambda: self._connection.execute(
                update(request)
                .where(
                    _mine(request, principal_id),
                    request.c.capability == capability,
                    request.c.idempotency_key == idempotency_key,
                    request.c.request_digest == request_digest,
                    request.c.completed_at.is_(None),
                )
                .values(
                    result_issue_id=result_issue_id,
                    result_issue_version=result_issue_version,
                    result_membership_event_id=result_membership_event_id,
                    result_link_id=result_link_id,
                    result_link_revision_no=result_link_revision_no,
                    result_created=result_created,
                    result_handoff_id=result_handoff_id,
                    result_record_family=result_record_family,
                    result_record_id=result_record_id,
                    result_handoff_correction_id=result_handoff_correction_id,
                    result_backfill_run_id=result_backfill_run_id,
                    result_backfill_checkpoint=result_backfill_checkpoint,
                    commit_seq=held_mark,
                    completed_at=completed_at,
                )
                .returning(request.c.capability)
            ).first()
        )
        if completed is None:
            raise RepositoryFailureError

    # --- the Issue row and its revisions -----------------------------------

    def insert_issue(
        self, principal_id: str, issue: IssueRecord, revision: IssueRevisionRecord
    ) -> None:
        _run(
            lambda: self._connection.execute(
                insert(situations).values(
                    _bound(
                        situations,
                        principal_id,
                        {
                            "situation_id": issue.issue_id,
                            "title": issue.title,
                            "description": issue.description,
                            "state": issue.state.value,
                            "object_refs": [],
                            "opened_at": issue.opened_at,
                            "closed_at": None,
                            "outcome": None,
                            "created_at": issue.created_at,
                            "updated_at": issue.updated_at,
                            "kind": _ISSUE,
                            "version": issue.version,
                        },
                    )
                )
            )
        )
        self._insert_revision(principal_id, revision)

    def lock_issue(
        self, principal_id: str, issue_id: str, *, for_update: bool
    ) -> IssueRecord | None:
        statement = select(*_ISSUE_COLUMNS).where(
            *_is_issue(principal_id), situations.c.situation_id == issue_id
        )
        locked = statement.with_for_update() if for_update else statement.with_for_update(read=True)
        row = _run(lambda: self._connection.execute(locked).one_or_none())
        return None if row is None else _to_issue(row)

    def update_issue(
        self, principal_id: str, issue: IssueRecord, revision: IssueRevisionRecord
    ) -> None:
        updated = _run(
            lambda: self._connection.execute(
                update(situations)
                .where(
                    *_is_issue(principal_id),
                    situations.c.situation_id == issue.issue_id,
                    situations.c.version == issue.version - 1,
                )
                .values(
                    title=issue.title,
                    description=issue.description,
                    state=issue.state.value,
                    version=issue.version,
                    updated_at=issue.updated_at,
                    closed_at=issue.closed_at,
                    outcome=issue.outcome,
                )
                .returning(situations.c.situation_id)
            ).first()
        )
        if updated is None:
            raise RepositoryFailureError
        self._insert_revision(principal_id, revision)

    def _insert_revision(self, principal_id: str, revision: IssueRevisionRecord) -> None:
        _run(
            lambda: self._connection.execute(
                insert(issue_revisions).values(
                    _bound(
                        issue_revisions,
                        principal_id,
                        {
                            "issue_id": revision.issue_id,
                            "version": revision.version,
                            "issue_kind": _ISSUE,
                            "revision_id": revision.revision_id,
                            "predecessor_version": revision.predecessor_version,
                            "action": revision.action.value,
                            "state": revision.state.value,
                            "title": revision.title,
                            "description": revision.description,
                            "authority_class": revision.authority_class,
                            "decision_channel": revision.decision_channel,
                            "source_capability": revision.source_capability,
                            "recorded_at": revision.recorded_at,
                            "closed_at": revision.closed_at,
                            "outcome": revision.outcome,
                            "reason": revision.reason,
                            "evidence_count": len(revision.evidence),
                            "evidence_set_digest": revision.evidence_set_digest,
                        },
                    )
                )
            )
        )
        rows = [
            _bound(
                issue_revision_evidence,
                principal_id,
                {
                    "issue_id": revision.issue_id,
                    "version": revision.version,
                    "ordinal": ordinal,
                    "anchor_id": cited.anchor_id,
                    "role": cited.anchor.role.value,
                },
            )
            for ordinal, cited in enumerate(revision.evidence, start=1)
        ]
        if rows:
            _run(lambda: self._connection.execute(insert(issue_revision_evidence), rows))

    def _revision_evidence(
        self, principal_id: str, issue_id: str, version: int
    ) -> tuple[LineageLinkEvidence, ...]:
        evidence = issue_revision_evidence
        anchors = lineage_evidence_anchors
        cited = _run(
            lambda: self._connection.execute(
                select(
                    evidence.c.anchor_id,
                    evidence.c.role,
                    anchors.c.source_family,
                    anchors.c.source_root_id,
                    anchors.c.source_version_kind,
                    anchors.c.source_version_id,
                    anchors.c.source_version_no,
                    anchors.c.source_sha256,
                    anchors.c.passage_start_cp,
                    anchors.c.passage_end_cp,
                    anchors.c.passage_sha256,
                )
                .select_from(
                    evidence.join(
                        anchors,
                        and_(
                            matching_partition_criterion(anchors, evidence),
                            anchors.c.anchor_id == evidence.c.anchor_id,
                        ),
                    )
                )
                .where(
                    _mine(evidence, principal_id),
                    evidence.c.issue_id == issue_id,
                    evidence.c.version == version,
                )
                .order_by(evidence.c.ordinal)
            ).all()
        )
        return tuple(
            LineageLinkEvidence(anchor_id=item.anchor_id, anchor=anchor_from_row(item))
            for item in cited
        )

    def read_issue(self, principal_id: str, issue_id: str) -> IssueRecord | None:
        row = _run(
            lambda: self._connection.execute(
                select(*_ISSUE_COLUMNS).where(
                    *_is_issue(principal_id), situations.c.situation_id == issue_id
                )
            ).one_or_none()
        )
        return None if row is None else _to_issue(row)

    def read_issue_revision(
        self, principal_id: str, issue_id: str, version: int
    ) -> IssueRevisionRecord | None:
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(*issue_revisions.c).where(
                        issue_revisions.c.issue_id == issue_id,
                        issue_revisions.c.version == version,
                    ),
                    issue_revisions,
                    capture_context(principal_id),
                )
            ).one_or_none()
        )
        if row is None:
            return None
        return _to_revision(row, self._revision_evidence(principal_id, issue_id, version))

    def latest_closing_revision(
        self, principal_id: str, issue_id: str, *, at_or_below: int
    ) -> IssueRevisionRecord | None:
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(*issue_revisions.c)
                    .where(
                        issue_revisions.c.issue_id == issue_id,
                        issue_revisions.c.action == IssueRevisionAction.CLOSED.value,
                        issue_revisions.c.version <= at_or_below,
                    )
                    .order_by(issue_revisions.c.version.desc())
                    .limit(1),
                    issue_revisions,
                    capture_context(principal_id),
                )
            ).one_or_none()
        )
        if row is None:
            return None
        return _to_revision(row, self._revision_evidence(principal_id, issue_id, row.version))

    def issue_revisions_known_at(
        self,
        principal_id: str,
        issue_id: str,
        cut: LineageFactCut,
        *,
        after: int | None,
        limit: int,
    ) -> tuple[IssueRevisionRecord, ...]:
        if cut.at is None:
            return ()
        revisions = issue_revisions
        # S3 section 3.4: known by its mark, or (a pre-S3 row) by its own time.
        known: ColumnElement[bool] = and_(
            revisions.c.commit_seq.is_(None), revisions.c.recorded_at <= cut.at
        )
        if cut.watermark is not None:
            known = or_(revisions.c.commit_seq <= cut.watermark, known)
        statement = select(*revisions.c).where(
            _mine(revisions, principal_id), revisions.c.issue_id == issue_id, known
        )
        if after is not None:
            statement = statement.where(revisions.c.version > after)
        rows = _run(
            lambda: self._connection.execute(
                statement.order_by(revisions.c.version).limit(limit)
            ).all()
        )
        return tuple(
            _to_revision(row, self._revision_evidence(principal_id, issue_id, row.version))
            for row in rows
        )

    def list_issues(
        self,
        principal_id: str,
        *,
        page_size: int,
        after: str | None,
        state: SituationState | None,
        project_id: str | None,
    ) -> IssueListPage:
        criteria: list[ColumnElement[bool]] = _is_issue(principal_id)
        if state is not None:
            criteria.append(situations.c.state == state.value)
        if project_id is not None:
            criteria.append(
                exists(
                    select(issue_project_membership_events.c.membership_event_id).where(
                        matching_partition_criterion(issue_project_membership_events, situations),
                        issue_project_membership_events.c.issue_id == situations.c.situation_id,
                        issue_project_membership_events.c.project_id == project_id,
                        issue_project_membership_events.c.state
                        == IssueProjectMembershipState.ACTIVE.value,
                        _no_later_event(),
                    )
                )
            )
        page_criteria = list(criteria)
        if after is not None:
            anchor = _run(
                lambda: self._connection.execute(
                    select(situations.c.created_at, situations.c.situation_id).where(
                        *criteria, situations.c.situation_id == after
                    )
                ).one_or_none()
            )
            if anchor is None:
                raise IssueCursorError()
            page_criteria.append(
                tuple_(situations.c.created_at, situations.c.situation_id)
                < tuple_(anchor.created_at, anchor.situation_id)
            )
        rows = _run(
            lambda: self._connection.execute(
                select(*_ISSUE_COLUMNS)
                .where(*page_criteria)
                .order_by(situations.c.created_at.desc(), situations.c.situation_id.desc())
                .limit(page_size + 1)
            ).all()
        )
        return IssueListPage(
            entries=tuple(_to_issue(row) for row in rows[:page_size]),
            has_more=len(rows) > page_size,
        )

    # --- Project links --------------------------------------------------------

    def project_links(
        self, principal_id: str, issue_id: str, *, limit: int
    ) -> tuple[ProjectLinkEventRecord, ...]:
        events = issue_project_membership_events
        rows = _run(
            lambda: self._connection.execute(
                select(*_EVENT_COLUMNS)
                .select_from(_events_with_link())
                .where(
                    _mine(events, principal_id), events.c.issue_id == issue_id, _no_later_event()
                )
                .order_by(
                    (events.c.state != IssueProjectMembershipState.ACTIVE.value),
                    events.c.project_id,
                )
                .limit(limit)
            ).all()
        )
        return tuple(_to_event(row) for row in rows)

    def share_project(self, principal_id: str, project_id: str) -> bool:
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(projects.c.project_id).where(projects.c.project_id == project_id),
                    projects,
                    capture_context(principal_id),
                ).with_for_update(read=True)
            ).one_or_none()
        )
        return row is not None

    def claim_project_link(
        self,
        principal_id: str,
        *,
        project_id: str,
        issue_id: str,
        project_situation_id: str,
        linked_at: datetime,
        association_evidence_ref: str | None,
    ) -> str:
        _run(
            lambda: self._connection.execute(
                pg_insert(project_situations)
                .values(
                    _bound(
                        project_situations,
                        principal_id,
                        {
                            "project_situation_id": project_situation_id,
                            "project_id": project_id,
                            "situation_id": issue_id,
                            "linked_at": linked_at,
                            "association_evidence_ref": association_evidence_ref,
                        },
                    )
                )
                .on_conflict_do_nothing()
            )
        )
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(project_situations.c.project_situation_id).where(
                        project_situations.c.project_id == project_id,
                        project_situations.c.situation_id == issue_id,
                    ),
                    project_situations,
                    capture_context(principal_id),
                ).with_for_update()
            ).one_or_none()
        )
        if row is None:
            # The conflicting row belongs to another Principal: the triplet unique
            # and the same-Principal foreign keys make that unreachable.
            raise RepositoryFailureError
        return str(row.project_situation_id)

    def latest_membership_event(
        self, principal_id: str, project_id: str, issue_id: str
    ) -> ProjectLinkEventRecord | None:
        events = issue_project_membership_events
        row = _run(
            lambda: self._connection.execute(
                select(*_EVENT_COLUMNS)
                .select_from(_events_with_link())
                .where(
                    _mine(events, principal_id),
                    events.c.project_id == project_id,
                    events.c.issue_id == issue_id,
                )
                .order_by(events.c.revision_no.desc())
                .limit(1)
            ).one_or_none()
        )
        return None if row is None else _to_event(row)

    def insert_membership_event(self, principal_id: str, event: ProjectLinkEventRecord) -> None:
        _run(
            lambda: self._connection.execute(
                insert(issue_project_membership_events).values(
                    _bound(
                        issue_project_membership_events,
                        principal_id,
                        {
                            "membership_event_id": event.membership_event_id,
                            "project_id": event.project_id,
                            "issue_id": event.issue_id,
                            "issue_kind": _ISSUE,
                            "revision_no": event.revision_no,
                            "predecessor_revision_no": event.predecessor_revision_no,
                            "action": event.action.value,
                            "state": event.state.value,
                            "evidence_anchor_id": event.evidence_anchor_id,
                            "reason": event.reason,
                            "acceptance_basis": event.acceptance_basis,
                            "authority_class": event.authority_class,
                            "decision_channel": event.decision_channel,
                            "source_capability": event.source_capability,
                            "recorded_at": event.recorded_at,
                            "asserting_client_id": event.asserting_client_id,
                            "user_directed_claim": event.user_directed_claim,
                        },
                    )
                )
            )
        )

    def read_membership_event(
        self, principal_id: str, membership_event_id: str
    ) -> ProjectLinkEventRecord | None:
        events = issue_project_membership_events
        row = _run(
            lambda: self._connection.execute(
                select(*_EVENT_COLUMNS)
                .select_from(_events_with_link())
                .where(
                    _mine(events, principal_id),
                    events.c.membership_event_id == membership_event_id,
                )
            ).one_or_none()
        )
        return None if row is None else _to_event(row)

    # --- evidence sources and anchors -----------------------------------------

    def share_note_version(
        self, principal_id: str, meeting_id: str, note_version_id: str
    ) -> LineageSourceVersion | None:
        notes = meeting_note_versions
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(
                        notes.c.version_number, notes.c.content_sha256, notes.c.content_markdown
                    ).where(
                        notes.c.note_version_id == note_version_id,
                        notes.c.meeting_id == meeting_id,
                    ),
                    notes,
                    capture_context(principal_id),
                ).with_for_update(read=True)
            ).one_or_none()
        )
        if row is None:
            return None
        return LineageSourceVersion(
            version_number=row.version_number,
            content_sha256=row.content_sha256,
            body=row.content_markdown,
        )

    def share_capture_root(self, principal_id: str, capture_id: str) -> bool:
        return _run(
            lambda: share_capture_root(
                self._connection, capture_id, context=capture_context(principal_id)
            )
        )

    def share_capture_version(
        self, principal_id: str, capture_id: str, version_id: str
    ) -> LineageSourceVersion | None:
        versions = capture_versions
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(
                        versions.c.version_number,
                        versions.c.content_sha256,
                        versions.c.content,
                        versions.c.classification,
                    ).where(
                        versions.c.version_id == version_id,
                        versions.c.capture_id == capture_id,
                    ),
                    versions,
                    capture_context(principal_id),
                ).with_for_update(read=True)
            ).one_or_none()
        )
        if row is None:
            return None
        return LineageSourceVersion(
            version_number=row.version_number,
            content_sha256=row.content_sha256,
            body=row.content,
            classification=row.classification,
        )

    def capture_root_is_archived(self, principal_id: str, capture_id: str) -> bool:
        projection = _run(
            lambda: latest_lifecycle(
                self._connection, capture_id, context=capture_context(principal_id)
            )
        )
        return projection.state is CaptureLifecycleState.ARCHIVED

    def capture_root_has_restricted_version(self, principal_id: str, capture_id: str) -> bool:
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(capture_versions.c.version_id)
                    .where(
                        capture_versions.c.capture_id == capture_id,
                        capture_versions.c.classification == Classification.RESTRICTED_LOCAL.value,
                    )
                    .limit(1),
                    capture_versions,
                    capture_context(principal_id),
                )
            ).first()
        )
        return row is not None

    def admit_anchor(
        self, principal_id: str, anchor: EvidenceAnchor, *, anchor_id: str, recorded_at: datetime
    ) -> str:
        anchors = lineage_evidence_anchors
        identity = anchor_identity(anchor)
        note = anchor.source_family.value == "meeting_note_version"
        capture_version = anchor.source_family.value == "capture_version"
        _run(
            lambda: self._connection.execute(
                pg_insert(anchors)
                .values(
                    _bound(
                        anchors,
                        principal_id,
                        {
                            "anchor_id": anchor_id,
                            "source_family": anchor.source_family.value,
                            "source_root_id": anchor.source_root_id,
                            "source_version_kind": anchor.source_version_kind.value,
                            "source_version_id": anchor.source_version_id,
                            "source_version_no": anchor.source_version_no,
                            "source_sha256": anchor.source_sha256,
                            "passage_start_cp": anchor.passage_start_cp,
                            "passage_end_cp": anchor.passage_end_cp,
                            "passage_sha256": anchor.passage_sha256,
                            "meeting_id": anchor.source_root_id if note else None,
                            "note_version_id": anchor.source_version_id if note else None,
                            "capture_id": None if note else anchor.source_root_id,
                            "capture_version_id": (
                                anchor.source_version_id if capture_version else None
                            ),
                            "anchor_identity": identity,
                            "recorded_at": recorded_at,
                        },
                    )
                )
                .on_conflict_do_nothing(constraint="a_lineage_anchor_is_identified_by_its_identity")
            )
        )
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(anchors.c.anchor_id).where(anchors.c.anchor_identity == identity),
                    anchors,
                    capture_context(principal_id),
                )
            ).one_or_none()
        )
        if row is None:
            raise RepositoryFailureError
        return str(row.anchor_id)

    # --- record lineage S2: Project qualification and composite request links --

    def share_active_project_link(self, principal_id: str, project_id: str, issue_id: str) -> bool:
        triplet = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(project_situations.c.project_situation_id).where(
                        project_situations.c.project_id == project_id,
                        project_situations.c.situation_id == issue_id,
                    ),
                    project_situations,
                    capture_context(principal_id),
                ).with_for_update(read=True)
            ).one_or_none()
        )
        if triplet is None:
            return False
        latest = self.latest_membership_event(principal_id, project_id, issue_id)
        return latest is not None and latest.state is IssueProjectMembershipState.ACTIVE

    def insert_write_request_links(
        self,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        links: Sequence[tuple[int, str, int]],
    ) -> None:
        if not links:
            return
        rows = [
            _bound(
                lineage_write_request_links,
                principal_id,
                {
                    "capability": capability,
                    "idempotency_key": idempotency_key,
                    "ordinal": ordinal,
                    "link_id": link_id,
                    "revision_no": revision_no,
                },
            )
            for ordinal, link_id, revision_no in links
        ]
        _run(lambda: self._connection.execute(insert(lineage_write_request_links), rows))

    # --- record lineage S3.1 (S3.1 contract sections 4.4 and 4.8) -------------

    def client_write_budget(
        self,
        principal_id: str,
        *,
        decision_channel: str,
        asserting_client_id: str | None,
        hour_since: datetime,
        day_since: datetime,
    ) -> LineageWriterBudget:
        request = lineage_write_requests
        client = request.c.decision_channel.in_(sorted(CLIENT_DECISION_CHANNELS))
        bucket = and_(
            request.c.decision_channel == decision_channel,
            request.c.asserting_client_id.is_(None)
            if asserting_client_id is None
            else request.c.asserting_client_id == asserting_client_id,
        )
        row = _run(
            lambda: self._connection.execute(
                select(
                    func.count().filter(and_(bucket, request.c.created_at > hour_since)),
                    func.count().filter(bucket),
                    func.count(),
                ).where(
                    _mine(request, principal_id),
                    request.c.completed_at.is_not(None),
                    client,
                    request.c.created_at > day_since,
                )
            ).one()
        )
        return LineageWriterBudget(
            bucket_hour=int(row[0]), bucket_day=int(row[1]), principal_day=int(row[2])
        )

    def project_link_confirmed(self, principal_id: str, project_id: str, issue_id: str) -> bool:
        events = issue_project_membership_events
        return bool(
            _run(
                lambda: self._connection.execute(
                    select(
                        exists().where(
                            _mine(events, principal_id),
                            events.c.project_id == project_id,
                            events.c.issue_id == issue_id,
                            events.c.acceptance_basis == AcceptanceBasis.USER_CONFIRMED.value,
                        )
                    )
                ).scalar_one()
            )
        )

    def write_request_links(
        self, principal_id: str, capability: str, idempotency_key: str
    ) -> tuple[tuple[int, str, int], ...]:
        links = lineage_write_request_links
        rows = _run(
            lambda: self._connection.execute(
                select(links.c.ordinal, links.c.link_id, links.c.revision_no)
                .where(
                    _mine(links, principal_id),
                    links.c.capability == capability,
                    links.c.idempotency_key == idempotency_key,
                )
                .order_by(links.c.ordinal)
            ).all()
        )
        return tuple((int(row.ordinal), str(row.link_id), int(row.revision_no)) for row in rows)
