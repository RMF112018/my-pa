"""Record lineage persistence, Slice S1 (S1 contract sections 4.2, 6.2, 7.2 and 9).

Two things live here.

**`SqlRecordLineageRepository`**, behind `contracts.ports.RecordLineageRepository`:
the endpoint shares, the identity advisory lock, the head locks and the
root/revision/evidence/head writes of the five S1 link writes
(`issues.memberships.*`, `records.associations.*`), and the lock-free reads of
`records.lineage` and `issues.read`'s memberships. Written here and nowhere
else: `record_links`, `record_link_revisions`, `record_link_revision_evidence`
and `record_link_heads`. Read and shared, never written: `situations`,
`meetings`, `meeting_note_versions`, `tasks`, `commitments`,
`project_constraints`, `capture_versions`, and the Capture lifecycle
projection. The request rows and the evidence anchors are the Issue
repository's (`infrastructure.persistence.issues`), on the same connection.

**`rebuild_link_heads`** -- `record_link_heads` is a derived projection with no
in-place repair: its trigger admits only the next revision and refuses every
delete. What makes it trustworthy is that it can be rebuilt. The function
derives every head of one Principal from the immutable roots and revisions
alone and reads nothing from `record_link_heads`, so comparing the two is a
real parity check. A mismatch is a defect to report, never something to
rewrite: repair is an operator-gated migration.

**The partition is reached through the guard**: every SELECT composes
`principal_scoped` or `_mine` (`partition_criterion`), every INSERT `_bound`
(`principal_bound_values`), every UPDATE `_mine`, and every join
`matching_partition_criterion`. The Principal is only ever a parameter.

**Locks** are section 6.2's and the application sequences them: endpoints and
Capture versions `FOR SHARE`; the identity advisory lock
(`LINEAGE_ADVISORY_NAMESPACE`, the two-key form, so it shares no key space with
any single-key advisory lock in `src/`); S2's `principal_id || ':blocks'` key
on the same namespace, which every `blocks` assert takes before its cycle
search (`blocks_successors` is that search's one step); the head `FOR UPDATE`.
Reads take no
locks. Every statement runs through `issues._run`, so a deadlock or
serialization victim is `TransactionConflictError` and answers `conflict`.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import (
    ColumnElement,
    Table,
    and_,
    false,
    func,
    insert,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import (
    LineageEndpoint,
    LineageFactCut,
    LineageIssueAsOf,
    LineageLinkEvidence,
    LineageNoteVersionRef,
    LineageReadTimeoutError,
    LineageResolvedRecord,
    LinkHeadRecord,
    LinkRevisionRecord,
    RecordLineageRepository,
    RecordLinkRecord,
    RepositoryFailureError,
)
from my_pa.domain.capture.lifecycle import CaptureLifecycleState
from my_pa.domain.common.classification import Classification
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import (
    LIVE_LINK_STATES,
    MANDATORY_MEMBER_ROLES,
    AcceptanceBasis,
    LinkLifecycleState,
    LinkRevisionAction,
    MemberRole,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SituationKind,
)
from my_pa.infrastructure.persistence.capture_lifecycle import latest_lifecycles
from my_pa.infrastructure.persistence.issues import _run, anchor_from_row
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
    principal_scoped,
)
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    commitments,
    issue_revisions,
    lineage_commit_marks,
    lineage_commit_sequences,
    lineage_evidence_anchors,
    meeting_note_versions,
    meetings,
    project_constraints,
    record_link_heads,
    record_link_revision_evidence,
    record_link_revisions,
    record_links,
    situations,
    tasks,
)

__all__ = [
    "LINEAGE_ADVISORY_NAMESPACE",
    "LinkHeadRow",
    "SqlRecordLineageRepository",
    "rebuild_link_heads",
]

#: The first key of the two-key `pg_advisory_xact_lock(int, int)` an S1
#: association or membership write takes on `principal_id || ':' ||
#: normalized_identity` (S1 contract section 6.2 step 4). ASCII "LINE". Every
#: other advisory lock in `src/` uses the single 64-bit key form, which
#: PostgreSQL keeps in a separate key space, so no existing key can collide.
LINEAGE_ADVISORY_NAMESPACE: Final = 0x4C494E45

#: The native table, identifier column and partition column of each S1 family.
_NATIVE: Final[Mapping[RecordFamily, tuple[Table, str]]] = {
    RecordFamily.SITUATION: (situations, "situation_id"),
    RecordFamily.MEETING: (meetings, "meeting_id"),
    RecordFamily.MEETING_NOTE_VERSION: (meeting_note_versions, "note_version_id"),
    RecordFamily.TASK: (tasks, "task_id"),
    RecordFamily.COMMITMENT: (commitments, "commitment_id"),
    RecordFamily.CONSTRAINT: (project_constraints, "constraint_id"),
    RecordFamily.CAPTURE_VERSION: (capture_versions, "version_id"),
}


#: S3 section 3: the head states that hold an identity and are traversed, as
#: stored tokens in a fixed order.
_LIVE_STATES: Final = tuple(sorted(state.value for state in LIVE_LINK_STATES))


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


#: PostgreSQL's `query_canceled`: a statement that outran `statement_timeout`.
_QUERY_CANCELED: Final = "57014"


def _bounded[ResultT](statement: Callable[[], ResultT]) -> ResultT:
    """`_run`, and a statement cancelled by its timeout is `LineageReadTimeoutError`.

    S3 section 7.2 step 5: a bounded read's statement timeout answers
    `unavailable`; any other store failure propagates as `_run` lets it.
    """
    timed_out = False
    try:
        return _run(statement)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != _QUERY_CANCELED:
            raise
        timed_out = True
    if timed_out:
        raise LineageReadTimeoutError("a bounded lineage read timed out")
    raise AssertionError("unreachable")  # pragma: no cover


def _known(table: Table, cut: LineageFactCut) -> ColumnElement[bool]:
    """S3 section 3.4: a fact row known at the cut (by its mark, or a pre-S3 row by time)."""
    if cut.at is None:
        return and_(false())
    known: ColumnElement[bool] = and_(table.c.commit_seq.is_(None), table.c.recorded_at <= cut.at)
    if cut.watermark is not None:
        known = or_(table.c.commit_seq <= cut.watermark, known)
    return known


_LINK_COLUMNS: Final = (
    record_links.c.link_id,
    record_links.c.kind,
    record_links.c.from_family,
    record_links.c.from_id,
    record_links.c.to_family,
    record_links.c.to_id,
    record_links.c.relation_type,
    record_links.c.member_role,
    record_links.c.context_issue_id,
    record_links.c.normalized_identity,
    record_links.c.authority_class,
    record_links.c.decision_channel,
    record_links.c.source_capability,
    record_links.c.created_at,
)


def _to_link(row: Row[Any]) -> RecordLinkRecord:
    return RecordLinkRecord(
        link_id=row.link_id,
        kind=RecordLinkKind(row.kind),
        from_ref=RecordRef(family=RecordFamily(row.from_family), record_id=row.from_id),
        to_ref=RecordRef(family=RecordFamily(row.to_family), record_id=row.to_id),
        relation_type=RelationType(row.relation_type),
        member_role=None if row.member_role is None else MemberRole(row.member_role),
        context_issue_id=row.context_issue_id,
        normalized_identity=row.normalized_identity,
        authority_class=row.authority_class,
        decision_channel=row.decision_channel,
        source_capability=row.source_capability,
        created_at=row.created_at,
    )


def _to_head(row: Row[Any]) -> LinkHeadRecord:
    return LinkHeadRecord(
        link=_to_link(row),
        revision_no=row.head_revision_no,
        lifecycle_state=LinkLifecycleState(row.head_lifecycle_state),
    )


def _heads_with_links() -> Any:  # noqa: ANN401 - a SQLAlchemy join
    return record_link_heads.join(
        record_links,
        and_(
            matching_partition_criterion(record_links, record_link_heads),
            record_links.c.link_id == record_link_heads.c.link_id,
        ),
    )


_HEAD_COLUMNS: Final = (
    *_LINK_COLUMNS,
    record_link_heads.c.revision_no.label("head_revision_no"),
    record_link_heads.c.lifecycle_state.label("head_lifecycle_state"),
)


def _endpoint_columns(family: RecordFamily) -> tuple[Any, ...]:
    """The native columns one endpoint family's `LineageEndpoint` carries."""
    if family is RecordFamily.SITUATION:
        return (situations.c.kind, situations.c.state)
    if family is RecordFamily.TASK:
        return (
            tasks.c.archived_at,
            tasks.c.lifecycle_state,
            tasks.c.evidence_state,
            tasks.c.version,
            tasks.c.created_at,
        )
    if family is RecordFamily.COMMITMENT:
        return (commitments.c.state, commitments.c.evidence_state, commitments.c.version)
    if family is RecordFamily.CONSTRAINT:
        return (
            project_constraints.c.lifecycle_state,
            project_constraints.c.version,
            project_constraints.c.created_at,
            project_constraints.c.project_id,
        )
    if family is RecordFamily.MEETING_NOTE_VERSION:
        return (meeting_note_versions.c.meeting_id,)
    if family is RecordFamily.CAPTURE_VERSION:
        return (capture_versions.c.capture_id, capture_versions.c.classification)
    return ()


def _to_endpoint(family: RecordFamily, record_id: str, row: Row[Any]) -> LineageEndpoint:
    mapping = row._mapping
    if family is RecordFamily.SITUATION:
        return LineageEndpoint(
            family=family,
            record_id=record_id,
            situation_kind=SituationKind(mapping["kind"]),
            situation_state=mapping["state"],
        )
    if family is RecordFamily.TASK:
        return LineageEndpoint(
            family=family,
            record_id=record_id,
            task_archived=mapping["archived_at"] is not None,
            native_state=mapping["lifecycle_state"],
            evidence_state=mapping["evidence_state"],
            native_version=mapping["version"],
            created_at=mapping["created_at"],
        )
    if family is RecordFamily.COMMITMENT:
        return LineageEndpoint(
            family=family,
            record_id=record_id,
            native_state=mapping["state"],
            evidence_state=mapping["evidence_state"],
            native_version=mapping["version"],
        )
    if family is RecordFamily.CONSTRAINT:
        return LineageEndpoint(
            family=family,
            record_id=record_id,
            native_state=mapping["lifecycle_state"],
            native_version=mapping["version"],
            created_at=mapping["created_at"],
            project_id=mapping["project_id"],
        )
    if family is RecordFamily.MEETING_NOTE_VERSION:
        return LineageEndpoint(family=family, record_id=record_id, meeting_id=mapping["meeting_id"])
    if family is RecordFamily.CAPTURE_VERSION:
        return LineageEndpoint(
            family=family,
            record_id=record_id,
            capture_id=mapping["capture_id"],
            classification=mapping["classification"],
        )
    return LineageEndpoint(family=family, record_id=record_id)


class SqlRecordLineageRepository(RecordLineageRepository):
    """`RecordLineageRepository`, over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _rows(self, statement: Any) -> Sequence[Row[Any]]:  # noqa: ANN401 - a SQLAlchemy select
        return _bounded(lambda: self._connection.execute(statement).all())

    # --- endpoints (section 3.2 step 2, section 6.2 step 3) -----------------

    def capture_version_root(self, principal_id: str, version_id: str) -> str | None:
        row = _run(
            lambda: self._connection.execute(
                principal_scoped(
                    select(capture_versions.c.capture_id).where(
                        capture_versions.c.version_id == version_id
                    ),
                    capture_versions,
                    capture_context(principal_id),
                )
            ).one_or_none()
        )
        return None if row is None else str(row.capture_id)

    def share_endpoint(
        self, principal_id: str, family: RecordFamily, record_id: str
    ) -> LineageEndpoint | None:
        table, column = _NATIVE[family]
        statement = principal_scoped(
            select(table.c[column], *_endpoint_columns(family)).where(table.c[column] == record_id),
            table,
            capture_context(principal_id),
        ).with_for_update(read=True)
        row = _run(lambda: self._connection.execute(statement).one_or_none())
        if row is None:
            return None
        return _to_endpoint(family, record_id, row)

    def native_members(
        self, principal_id: str, refs: Collection[RecordRef]
    ) -> Mapping[RecordRef, LineageEndpoint]:
        found: dict[RecordRef, LineageEndpoint] = {}
        by_family: dict[RecordFamily, set[str]] = {}
        for ref in refs:
            by_family.setdefault(ref.family, set()).add(ref.record_id)
        for family, identifiers in sorted(by_family.items()):
            table, column = _NATIVE[family]
            rows = self._rows(
                principal_scoped(
                    select(table.c[column], *_endpoint_columns(family)).where(
                        table.c[column].in_(sorted(identifiers))
                    ),
                    table,
                    capture_context(principal_id),
                )
            )
            for row in rows:
                record_id = str(row._mapping[column])
                found[RecordRef(family=family, record_id=record_id)] = _to_endpoint(
                    family, record_id, row
                )
        return found

    # --- identity and head locks (section 6.2 steps 4 and 5) ------------------

    def lock_identity(self, principal_id: str, normalized_identity: str) -> None:
        _run(
            lambda: self._connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), "
                    "hashtext(CAST(:principal_id AS text) || ':' || CAST(:identity AS text)))"
                ),
                {
                    "namespace": LINEAGE_ADVISORY_NAMESPACE,
                    "principal_id": principal_id,
                    "identity": normalized_identity,
                },
            )
        )

    def lock_blocks(self, principal_id: str) -> None:
        _run(
            lambda: self._connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), "
                    "hashtext(CAST(:principal_id AS text) || CAST(:suffix AS text)))"
                ),
                {
                    "namespace": LINEAGE_ADVISORY_NAMESPACE,
                    "principal_id": principal_id,
                    "suffix": ":blocks",
                },
            )
        )

    def blocks_successors(
        self, principal_id: str, refs: Collection[RecordRef]
    ) -> tuple[RecordRef, ...]:
        if not refs:
            return ()
        pairs = sorted({(ref.family.value, ref.record_id) for ref in refs})
        rows = self._rows(
            select(record_links.c.to_family, record_links.c.to_id)
            .select_from(_heads_with_links())
            .where(
                _mine(record_link_heads, principal_id),
                # S3 section 6.2 step 6: contested `blocks` heads stay in the search.
                record_link_heads.c.lifecycle_state.in_(_LIVE_STATES),
                record_links.c.relation_type == RelationType.BLOCKS.value,
                tuple_(record_links.c.from_family, record_links.c.from_id).in_(pairs),
            )
            .distinct()
            .order_by(record_links.c.to_family, record_links.c.to_id)
        )
        return tuple(
            RecordRef(family=RecordFamily(row.to_family), record_id=row.to_id) for row in rows
        )

    def active_head_by_identity(
        self, principal_id: str, normalized_identity: str
    ) -> LinkHeadRecord | None:
        row = _run(
            lambda: self._connection.execute(
                select(*_HEAD_COLUMNS)
                .select_from(_heads_with_links())
                .where(
                    _mine(record_link_heads, principal_id),
                    record_link_heads.c.normalized_identity == normalized_identity,
                    # S3 section 3.1: a contested head still holds its identity.
                    record_link_heads.c.lifecycle_state.in_(_LIVE_STATES),
                )
                .with_for_update(of=record_link_heads)
            ).one_or_none()
        )
        return None if row is None else _to_head(row)

    def lock_head(self, principal_id: str, link_id: str) -> LinkHeadRecord | None:
        row = _run(
            lambda: self._connection.execute(
                select(*_HEAD_COLUMNS)
                .select_from(_heads_with_links())
                .where(
                    _mine(record_link_heads, principal_id), record_link_heads.c.link_id == link_id
                )
                .with_for_update(of=record_link_heads)
            ).one_or_none()
        )
        return None if row is None else _to_head(row)

    # --- writes (section 6.3 step 4) -------------------------------------------

    def insert_link(
        self, principal_id: str, link: RecordLinkRecord, revision: LinkRevisionRecord
    ) -> None:
        _run(
            lambda: self._connection.execute(
                insert(record_links).values(
                    _bound(
                        record_links,
                        principal_id,
                        {
                            "link_id": link.link_id,
                            "kind": link.kind.value,
                            "from_family": link.from_ref.family.value,
                            "from_id": link.from_ref.record_id,
                            "to_family": link.to_ref.family.value,
                            "to_id": link.to_ref.record_id,
                            "relation_type": link.relation_type.value,
                            "member_role": (
                                None if link.member_role is None else link.member_role.value
                            ),
                            "context_issue_id": link.context_issue_id,
                            "context_issue_kind": (
                                None
                                if link.context_issue_id is None
                                else SituationKind.ISSUE_WORKSTREAM.value
                            ),
                            "normalized_identity": link.normalized_identity,
                            "authority_class": link.authority_class,
                            "decision_channel": link.decision_channel,
                            "source_capability": link.source_capability,
                            "created_at": link.created_at,
                        },
                    )
                )
            )
        )
        self._insert_revision(principal_id, revision)
        _run(
            lambda: self._connection.execute(
                insert(record_link_heads).values(
                    _bound(
                        record_link_heads,
                        principal_id,
                        {
                            "link_id": link.link_id,
                            "revision_no": revision.revision_no,
                            "lifecycle_state": revision.lifecycle_state.value,
                            "normalized_identity": link.normalized_identity,
                        },
                    )
                )
            )
        )

    def append_revision(self, principal_id: str, revision: LinkRevisionRecord) -> None:
        self._insert_revision(principal_id, revision)
        advanced = _run(
            lambda: self._connection.execute(
                update(record_link_heads)
                .where(
                    _mine(record_link_heads, principal_id),
                    record_link_heads.c.link_id == revision.link_id,
                    record_link_heads.c.revision_no == revision.revision_no - 1,
                )
                .values(
                    revision_no=revision.revision_no,
                    lifecycle_state=revision.lifecycle_state.value,
                )
                .returning(record_link_heads.c.link_id)
            ).first()
        )
        if advanced is None:
            raise RepositoryFailureError

    def _insert_revision(self, principal_id: str, revision: LinkRevisionRecord) -> None:
        _run(
            lambda: self._connection.execute(
                insert(record_link_revisions).values(
                    _bound(
                        record_link_revisions,
                        principal_id,
                        {
                            "link_id": revision.link_id,
                            "revision_no": revision.revision_no,
                            "revision_id": revision.revision_id,
                            "predecessor_revision_no": revision.predecessor_revision_no,
                            "action": revision.action.value,
                            "lifecycle_state": revision.lifecycle_state.value,
                            "acceptance_basis": revision.acceptance_basis.value,
                            "authority_class": revision.authority_class,
                            "decision_channel": revision.decision_channel,
                            "source_capability": revision.source_capability,
                            "reason": revision.reason,
                            "evidence_count": len(revision.evidence),
                            "evidence_set_digest": revision.evidence_set_digest,
                            "recorded_at": revision.recorded_at,
                            "member_native_version": revision.member_native_version,
                        },
                    )
                )
            )
        )
        rows = [
            _bound(
                record_link_revision_evidence,
                principal_id,
                {
                    "link_id": revision.link_id,
                    "revision_no": revision.revision_no,
                    "ordinal": ordinal,
                    "anchor_id": cited.anchor_id,
                    "role": cited.anchor.role.value,
                },
            )
            for ordinal, cited in enumerate(revision.evidence, start=1)
        ]
        if rows:
            _run(lambda: self._connection.execute(insert(record_link_revision_evidence), rows))

    # --- immutable reads --------------------------------------------------------

    def read_link(self, principal_id: str, link_id: str) -> RecordLinkRecord | None:
        row = _bounded(
            lambda: self._connection.execute(
                select(*_LINK_COLUMNS).where(
                    _mine(record_links, principal_id), record_links.c.link_id == link_id
                )
            ).one_or_none()
        )
        return None if row is None else _to_link(row)

    def read_revision(
        self, principal_id: str, link_id: str, revision_no: int
    ) -> LinkRevisionRecord | None:
        revisions = record_link_revisions
        row = _bounded(
            lambda: self._connection.execute(
                select(*revisions.c).where(
                    _mine(revisions, principal_id),
                    revisions.c.link_id == link_id,
                    revisions.c.revision_no == revision_no,
                )
            ).one_or_none()
        )
        if row is None:
            return None
        evidence = record_link_revision_evidence
        anchors = lineage_evidence_anchors
        cited = _bounded(
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
                    evidence.c.link_id == link_id,
                    evidence.c.revision_no == revision_no,
                )
                .order_by(evidence.c.ordinal)
            ).all()
        )
        return LinkRevisionRecord(
            link_id=row.link_id,
            revision_no=row.revision_no,
            revision_id=row.revision_id,
            predecessor_revision_no=row.predecessor_revision_no,
            action=LinkRevisionAction(row.action),
            lifecycle_state=LinkLifecycleState(row.lifecycle_state),
            acceptance_basis=AcceptanceBasis(row.acceptance_basis),
            authority_class=row.authority_class,
            decision_channel=row.decision_channel,
            source_capability=row.source_capability,
            reason=row.reason,
            evidence_set_digest=row.evidence_set_digest,
            recorded_at=row.recorded_at,
            evidence=tuple(
                LineageLinkEvidence(anchor_id=item.anchor_id, anchor=anchor_from_row(item))
                for item in cited
            ),
            member_native_version=row.member_native_version,
        )

    def archived_capture_roots(
        self, principal_id: str, capture_ids: Collection[str]
    ) -> frozenset[str]:
        if not capture_ids:
            return frozenset()
        projections = _bounded(
            lambda: latest_lifecycles(
                self._connection, capture_ids, context=capture_context(principal_id)
            )
        )
        return frozenset(
            capture_id
            for capture_id, projection in projections.items()
            if projection.state is CaptureLifecycleState.ARCHIVED
        )

    # --- the reverse read (section 7.2) -------------------------------------------

    def active_links_incident(
        self, principal_id: str, refs: Collection[RecordRef]
    ) -> tuple[LinkHeadRecord, ...]:
        if not refs:
            return ()
        pairs = sorted({(ref.family.value, ref.record_id) for ref in refs})
        rows = _bounded(
            lambda: self._connection.execute(
                select(*_HEAD_COLUMNS)
                .select_from(_heads_with_links())
                .where(
                    _mine(record_link_heads, principal_id),
                    # S3 section 9: live heads, so a contested link is followed and shown.
                    record_link_heads.c.lifecycle_state.in_(_LIVE_STATES),
                    or_(
                        tuple_(record_links.c.from_family, record_links.c.from_id).in_(pairs),
                        tuple_(record_links.c.to_family, record_links.c.to_id).in_(pairs),
                    ),
                )
                .order_by(record_links.c.created_at, record_links.c.link_id)
            ).all()
        )
        return tuple(_to_head(row) for row in rows)

    def issue_memberships(
        self, principal_id: str, issue_id: str, *, limit: int
    ) -> tuple[LinkHeadRecord, ...]:
        rows = _bounded(
            lambda: self._connection.execute(
                select(*_HEAD_COLUMNS)
                .select_from(_heads_with_links())
                .where(
                    _mine(record_link_heads, principal_id),
                    record_link_heads.c.lifecycle_state == LinkLifecycleState.ACTIVE.value,
                    record_links.c.kind == RecordLinkKind.ISSUE_MEMBERSHIP.value,
                    record_links.c.from_family == RecordFamily.SITUATION.value,
                    record_links.c.from_id == issue_id,
                )
                .order_by(record_links.c.created_at, record_links.c.link_id)
                .limit(limit)
            ).all()
        )
        return tuple(_to_head(row) for row in rows)

    def mandatory_memberships(
        self, principal_id: str, issue_id: str, *, share: bool
    ) -> tuple[LinkHeadRecord, ...]:
        statement = (
            select(*_HEAD_COLUMNS)
            .select_from(_heads_with_links())
            .where(
                _mine(record_link_heads, principal_id),
                record_link_heads.c.lifecycle_state == LinkLifecycleState.ACTIVE.value,
                record_links.c.kind == RecordLinkKind.ISSUE_MEMBERSHIP.value,
                record_links.c.from_family == RecordFamily.SITUATION.value,
                record_links.c.from_id == issue_id,
                record_links.c.member_role.in_(
                    sorted(role.value for role in MANDATORY_MEMBER_ROLES)
                ),
            )
            .order_by(record_link_heads.c.link_id)
        )
        if share:
            statement = statement.with_for_update(read=True, of=record_link_heads)
        rows = self._rows(statement)
        return tuple(_to_head(row) for row in rows)

    def active_membership(
        self, principal_id: str, issue_id: str, member: RecordRef
    ) -> LinkHeadRecord | None:
        rows = self._rows(
            select(*_HEAD_COLUMNS)
            .select_from(_heads_with_links())
            .where(
                _mine(record_link_heads, principal_id),
                record_link_heads.c.lifecycle_state == LinkLifecycleState.ACTIVE.value,
                record_links.c.kind == RecordLinkKind.ISSUE_MEMBERSHIP.value,
                record_links.c.from_family == RecordFamily.SITUATION.value,
                record_links.c.from_id == issue_id,
                record_links.c.to_family == member.family.value,
                record_links.c.to_id == member.record_id,
            )
            .order_by(record_links.c.created_at, record_links.c.link_id)
            .limit(1)
        )
        return _to_head(rows[0]) if rows else None

    def resolve_records(
        self, principal_id: str, refs: Collection[RecordRef]
    ) -> Mapping[RecordRef, LineageResolvedRecord]:
        resolved: dict[RecordRef, LineageResolvedRecord] = {}
        by_family: dict[RecordFamily, list[str]] = {}
        for ref in refs:
            by_family.setdefault(ref.family, []).append(ref.record_id)
        context = capture_context(principal_id)
        for family, identifiers in sorted(by_family.items()):
            table, column = _NATIVE[family]
            wanted = sorted(set(identifiers))
            columns: list[Any] = [table.c[column]]
            if family is RecordFamily.SITUATION:
                columns += [situations.c.kind, situations.c.title, situations.c.state]
            elif family is RecordFamily.MEETING_NOTE_VERSION:
                columns.append(meeting_note_versions.c.meeting_id)
            elif family is RecordFamily.CAPTURE_VERSION:
                columns.append(capture_versions.c.capture_id)
            statement = principal_scoped(
                select(*columns).where(table.c[column].in_(wanted)), table, context
            )
            rows = self._rows(statement)
            for row in rows:
                mapping = row._mapping
                ref = RecordRef(family=family, record_id=mapping[column])
                if family is RecordFamily.SITUATION:
                    resolved[ref] = LineageResolvedRecord(
                        ref=ref,
                        situation_kind=SituationKind(mapping["kind"]),
                        title=mapping["title"],
                        state=mapping["state"],
                    )
                elif family is RecordFamily.MEETING_NOTE_VERSION:
                    resolved[ref] = LineageResolvedRecord(ref=ref, meeting_id=mapping["meeting_id"])
                elif family is RecordFamily.CAPTURE_VERSION:
                    resolved[ref] = LineageResolvedRecord(ref=ref, capture_id=mapping["capture_id"])
                else:
                    resolved[ref] = LineageResolvedRecord(ref=ref)
        roots = {record.capture_id for record in resolved.values() if record.capture_id}
        archived = self.archived_capture_roots(principal_id, roots)
        for ref, record in list(resolved.items()):
            if record.capture_id is not None and record.capture_id in archived:
                resolved[ref] = LineageResolvedRecord(
                    ref=ref, capture_id=record.capture_id, capture_archived=True
                )
        return resolved

    def note_versions_of(
        self, principal_id: str, meeting_ids: Collection[str]
    ) -> Mapping[str, tuple[LineageNoteVersionRef, ...]]:
        if not meeting_ids:
            return {}
        notes = meeting_note_versions
        rows = _bounded(
            lambda: self._connection.execute(
                select(notes.c.note_version_id, notes.c.meeting_id, notes.c.version_number)
                .where(_mine(notes, principal_id), notes.c.meeting_id.in_(sorted(set(meeting_ids))))
                .order_by(notes.c.meeting_id, notes.c.version_number)
            ).all()
        )
        found: dict[str, list[LineageNoteVersionRef]] = {}
        for row in rows:
            found.setdefault(row.meeting_id, []).append(
                LineageNoteVersionRef(
                    note_version_id=row.note_version_id,
                    meeting_id=row.meeting_id,
                    version_number=row.version_number,
                )
            )
        return {meeting_id: tuple(versions) for meeting_id, versions in found.items()}

    def links_in_issue_context(
        self, principal_id: str, issue_id: str, inside: Collection[RecordRef]
    ) -> tuple[LinkHeadRecord, ...]:
        pairs = sorted(
            {(ref.family.value, ref.record_id) for ref in inside}
            | {(RecordFamily.SITUATION.value, issue_id)}
        )
        rows = self._rows(
            select(*_HEAD_COLUMNS)
            .select_from(_heads_with_links())
            .where(
                _mine(record_link_heads, principal_id),
                record_link_heads.c.lifecycle_state.in_(_LIVE_STATES),
                record_links.c.kind == RecordLinkKind.SEMANTIC.value,
                or_(
                    record_links.c.context_issue_id == issue_id,
                    tuple_(record_links.c.from_family, record_links.c.from_id).in_(pairs),
                    tuple_(record_links.c.to_family, record_links.c.to_id).in_(pairs),
                ),
            )
            .order_by(record_links.c.link_id.collate("C"))
        )
        return tuple(_to_head(row) for row in rows)

    # --- the knowledge clock (S3 contract sections 3.4, 4.2 and 6.2) -------------

    def take_commit_mark(self, principal_id: str) -> int:
        # The allocator row stays locked until this transaction ends; a second
        # call in the same transaction returns the mark it already holds.
        mark = _run(
            lambda: self._connection.execute(
                text("SELECT knowledge.lineage_commit_mark(CAST(:principal_id AS text))"),
                {"principal_id": principal_id},
            ).scalar_one()
        )
        return int(mark)

    def commit_horizon(self, principal_id: str) -> datetime | None:
        sequences = lineage_commit_sequences
        return _bounded(
            lambda: self._connection.execute(
                select(sequences.c.last_marked_at).where(_mine(sequences, principal_id))
            ).scalar_one_or_none()
        )

    def commit_watermark(self, principal_id: str, at: datetime) -> int | None:
        marks = lineage_commit_marks
        found = _bounded(
            lambda: self._connection.execute(
                select(func.max(marks.c.commit_seq)).where(
                    _mine(marks, principal_id), marks.c.marked_at <= at
                )
            ).scalar_one()
        )
        return None if found is None else int(found)

    def link_states_known_at(
        self,
        principal_id: str,
        link_ids: Collection[str],
        *,
        watermark: int | None,
        at: datetime | None,
    ) -> Mapping[str, tuple[int, LinkLifecycleState]]:
        if not link_ids or at is None:
            return {}
        revisions = record_link_revisions
        known = and_(revisions.c.commit_seq.is_(None), revisions.c.recorded_at <= at)
        if watermark is not None:
            known = or_(revisions.c.commit_seq <= watermark, known)
        rows = self._rows(
            select(revisions.c.link_id, revisions.c.revision_no, revisions.c.lifecycle_state)
            .where(
                _mine(revisions, principal_id),
                revisions.c.link_id.in_(sorted(set(link_ids))),
                known,
            )
            .distinct(revisions.c.link_id)
            .order_by(revisions.c.link_id, revisions.c.revision_no.desc())
        )
        return {
            row.link_id: (int(row.revision_no), LinkLifecycleState(row.lifecycle_state))
            for row in rows
        }

    # --- the as-of read core (S3 contract sections 3.4, 6.4 and 7.2) --------------

    def bound_read_statements(self, timeout_ms: int) -> None:
        _run(
            lambda: self._connection.execute(
                text(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
            )
        )

    def live_links_incident(
        self, principal_id: str, refs: Collection[RecordRef], cut: LineageFactCut
    ) -> tuple[LinkHeadRecord, ...]:
        if not refs or cut.at is None:
            return ()
        pairs = sorted({(ref.family.value, ref.record_id) for ref in refs})
        revisions = record_link_revisions
        selected = (
            select(
                *_LINK_COLUMNS,
                revisions.c.revision_no.label("head_revision_no"),
                revisions.c.lifecycle_state.label("head_lifecycle_state"),
            )
            .select_from(
                record_links.join(
                    revisions,
                    and_(
                        matching_partition_criterion(revisions, record_links),
                        revisions.c.link_id == record_links.c.link_id,
                    ),
                )
            )
            .where(
                _mine(record_links, principal_id),
                or_(
                    tuple_(record_links.c.from_family, record_links.c.from_id).in_(pairs),
                    tuple_(record_links.c.to_family, record_links.c.to_id).in_(pairs),
                ),
                _known(revisions, cut),
            )
            # Section 7.2 step 2: the latest revision of each link known at the cut.
            .distinct(record_links.c.link_id)
            .order_by(record_links.c.link_id, revisions.c.revision_no.desc())
            .subquery("selected")
        )
        rows = self._rows(
            select(selected)
            .where(selected.c.head_lifecycle_state.in_(_LIVE_STATES))
            .order_by(selected.c.created_at, selected.c.link_id.collate("C"))
        )
        return tuple(_to_head(row) for row in rows)

    def links_in_issue_context_at(
        self,
        principal_id: str,
        issue_id: str,
        inside: Collection[RecordRef],
        cut: LineageFactCut,
    ) -> tuple[LinkHeadRecord, ...]:
        if cut.at is None:
            return ()
        pairs = sorted(
            {(ref.family.value, ref.record_id) for ref in inside}
            | {(RecordFamily.SITUATION.value, issue_id)}
        )
        revisions = record_link_revisions
        selected = (
            select(
                *_LINK_COLUMNS,
                revisions.c.revision_no.label("head_revision_no"),
                revisions.c.lifecycle_state.label("head_lifecycle_state"),
            )
            .select_from(
                record_links.join(
                    revisions,
                    and_(
                        matching_partition_criterion(revisions, record_links),
                        revisions.c.link_id == record_links.c.link_id,
                    ),
                )
            )
            .where(
                _mine(record_links, principal_id),
                or_(
                    record_links.c.context_issue_id == issue_id,
                    tuple_(record_links.c.from_family, record_links.c.from_id).in_(pairs),
                    tuple_(record_links.c.to_family, record_links.c.to_id).in_(pairs),
                ),
                _known(revisions, cut),
            )
            # S3 section 3.2 at a read cut: the latest revision of each link known then.
            .distinct(record_links.c.link_id)
            .order_by(record_links.c.link_id, revisions.c.revision_no.desc())
            .subquery("selected")
        )
        rows = self._rows(select(selected).order_by(selected.c.link_id.collate("C")))
        return tuple(_to_head(row) for row in rows)

    def issues_known_at(
        self, principal_id: str, issue_ids: Collection[str], cut: LineageFactCut
    ) -> Mapping[str, LineageIssueAsOf]:
        if not issue_ids or cut.at is None:
            return {}
        rows = self._rows(
            select(
                issue_revisions.c.issue_id,
                issue_revisions.c.version,
                issue_revisions.c.title,
                issue_revisions.c.state,
            )
            .where(
                _mine(issue_revisions, principal_id),
                issue_revisions.c.issue_id.in_(sorted(set(issue_ids))),
                _known(issue_revisions, cut),
            )
            .distinct(issue_revisions.c.issue_id)
            .order_by(issue_revisions.c.issue_id, issue_revisions.c.version.desc())
        )
        return {
            row.issue_id: LineageIssueAsOf(
                issue_id=row.issue_id, version=int(row.version), title=row.title, state=row.state
            )
            for row in rows
        }

    def note_versions_until(
        self, principal_id: str, meeting_ids: Collection[str], recorded_at_most: datetime
    ) -> Mapping[str, tuple[LineageNoteVersionRef, ...]]:
        if not meeting_ids:
            return {}
        notes = meeting_note_versions
        rows = self._rows(
            select(notes.c.note_version_id, notes.c.meeting_id, notes.c.version_number)
            .where(
                _mine(notes, principal_id),
                notes.c.meeting_id.in_(sorted(set(meeting_ids))),
                notes.c.recorded_at <= recorded_at_most,
            )
            .order_by(notes.c.meeting_id, notes.c.version_number)
        )
        found: dict[str, list[LineageNoteVersionRef]] = {}
        for row in rows:
            found.setdefault(row.meeting_id, []).append(
                LineageNoteVersionRef(
                    note_version_id=row.note_version_id,
                    meeting_id=row.meeting_id,
                    version_number=row.version_number,
                )
            )
        return {meeting_id: tuple(versions) for meeting_id, versions in found.items()}

    def note_version_recorded_at(
        self, principal_id: str, note_version_ids: Collection[str]
    ) -> Mapping[str, datetime]:
        if not note_version_ids:
            return {}
        notes = meeting_note_versions
        rows = self._rows(
            select(notes.c.note_version_id, notes.c.recorded_at).where(
                _mine(notes, principal_id),
                notes.c.note_version_id.in_(sorted(set(note_version_ids))),
            )
        )
        return {row.note_version_id: row.recorded_at for row in rows}

    def link_revisions_known_at(
        self,
        principal_id: str,
        link_id: str,
        cut: LineageFactCut,
        *,
        after: int | None,
        limit: int,
    ) -> tuple[LinkRevisionRecord, ...]:
        if cut.at is None:
            return ()
        revisions = record_link_revisions
        statement = select(revisions.c.revision_no).where(
            _mine(revisions, principal_id),
            revisions.c.link_id == link_id,
            _known(revisions, cut),
        )
        if after is not None:
            statement = statement.where(revisions.c.revision_no > after)
        numbers = [
            int(row.revision_no)
            for row in self._rows(statement.order_by(revisions.c.revision_no).limit(limit))
        ]
        found: list[LinkRevisionRecord] = []
        for number in numbers:
            revision = self.read_revision(principal_id, link_id, number)
            if revision is None:
                raise RepositoryFailureError
            found.append(revision)
        return tuple(found)

    def restricted_capture_roots(
        self, principal_id: str, capture_ids: Collection[str]
    ) -> frozenset[str]:
        if not capture_ids:
            return frozenset()
        rows = self._rows(
            principal_scoped(
                select(capture_versions.c.capture_id)
                .where(
                    capture_versions.c.capture_id.in_(sorted(set(capture_ids))),
                    capture_versions.c.classification == Classification.RESTRICTED_LOCAL.value,
                )
                .distinct(),
                capture_versions,
                capture_context(principal_id),
            )
        )
        return frozenset(str(row.capture_id) for row in rows)


# --- head rebuild parity ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LinkHeadRow:
    """One `record_link_heads` row, as stored or as rebuilt."""

    principal_id: str
    link_id: str
    revision_no: int
    lifecycle_state: LinkLifecycleState
    normalized_identity: str


def rebuild_link_heads(
    connection: Connection, context: PrincipalContext | None
) -> tuple[LinkHeadRow, ...]:
    """Every head of the context's Principal, derived from roots and revisions.

    Ordered by `link_id`. A root with no revision yields no head, as the head
    table would hold none for it.
    """
    statement = principal_scoped(
        select(
            record_links.c.principal_id,
            record_links.c.link_id,
            record_links.c.normalized_identity,
            record_link_revisions.c.revision_no,
            record_link_revisions.c.lifecycle_state,
        )
        .select_from(record_links)
        .join(
            record_link_revisions,
            and_(
                matching_partition_criterion(record_links, record_link_revisions),
                record_link_revisions.c.link_id == record_links.c.link_id,
            ),
        )
        .order_by(record_links.c.link_id, record_link_revisions.c.revision_no),
        record_links,
        context,
    )
    latest: dict[str, LinkHeadRow] = {}
    for row in connection.execute(statement):
        latest[row.link_id] = LinkHeadRow(
            principal_id=row.principal_id,
            link_id=row.link_id,
            revision_no=row.revision_no,
            lifecycle_state=LinkLifecycleState(row.lifecycle_state),
            normalized_identity=row.normalized_identity,
        )
    return tuple(latest[link_id] for link_id in sorted(latest))
