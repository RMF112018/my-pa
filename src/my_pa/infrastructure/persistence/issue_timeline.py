"""The record lineage S3 Issue timeline, behind `contracts.ports.IssueTimelineRepository`.

S3 contract section 7.3. Lock-free reads, one statement each, every one through
the lineage persistence `_bounded` runner, so a statement that outruns the
read's `statement_timeout` is `LineageReadTimeoutError` (`unavailable`):

* **the lineage plane** -- an Issue's revisions, its Project link events and the
  revisions of named links, each selecting only the facts known at a
  `LineageFactCut` (section 3.4: by the row's commit mark, or a pre-S3 row by
  its own `recorded_at`);
* **the native plane** -- the Record Events of an Issue's member records, read
  by the feed module's own `issue_member_events` under the feed's one
  visibility predicate (never copied, R3-F03): the reader's family set and, for
  a remote reader, every withholding clause, so a withheld event never reaches
  an entry or the watermark;
* **Constraint revision snapshots** -- the immutable state and stored
  ball-in-court parties of one applied Constraint version (S3 section 12,
  D-13), and the Entity names a party label falls back to.

The partition is reached through the guard: every SELECT composes
`partition_criterion` (`_mine`) or `principal_scoped`, and every join
`matching_partition_criterion`. The Principal is only ever a parameter.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Table, and_, select, tuple_
from sqlalchemy.engine import Connection, Row

from my_pa.contracts.ports import (
    ConstraintRevisionSnapshot,
    IssueRevisionRecord,
    IssueTimelineRepository,
    LineageFactCut,
    ProjectLinkEventRecord,
    TimelineLinkRevision,
    TimelineNativeEvent,
)
from my_pa.domain.lineage.vocabulary import LinkLifecycleState, LinkRevisionAction
from my_pa.domain.project_controls.party import PartyKind
from my_pa.domain.project_controls.read_models import ConstraintPartyRow
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.persistence.issues import (
    _EVENT_COLUMNS,
    _events_with_link,
    _to_event,
    _to_revision,
)
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_scoped,
)
from my_pa.infrastructure.persistence.record_events import issue_member_events
from my_pa.infrastructure.persistence.record_lineage import _bounded, _known
from my_pa.infrastructure.persistence.tables import (
    entities,
    issue_project_membership_events,
    issue_revisions,
    project_constraint_revision_parties,
    project_constraint_revisions,
    record_link_revisions,
)

__all__ = ["SqlIssueTimelineRepository"]

#: The stored role of a ball-in-court party (`project_constraint_revision_parties`).
_BIC_ROLE = "bic"


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


class SqlIssueTimelineRepository(IssueTimelineRepository):
    """`IssueTimelineRepository`, over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _rows(self, statement: Any) -> Sequence[Row[Any]]:  # noqa: ANN401 - a SQLAlchemy select
        return _bounded(lambda: self._connection.execute(statement).all())

    # --- the lineage plane --------------------------------------------------------

    def issue_revisions(
        self, principal_id: str, issue_id: str, cut: LineageFactCut
    ) -> tuple[IssueRevisionRecord, ...]:
        if cut.at is None:
            return ()
        rows = self._rows(
            select(*issue_revisions.c)
            .where(
                _mine(issue_revisions, principal_id),
                issue_revisions.c.issue_id == issue_id,
                _known(issue_revisions, cut),
            )
            .order_by(issue_revisions.c.version)
        )
        return tuple(_to_revision(row) for row in rows)

    def project_link_events(
        self, principal_id: str, issue_id: str, cut: LineageFactCut
    ) -> tuple[ProjectLinkEventRecord, ...]:
        if cut.at is None:
            return ()
        events = issue_project_membership_events
        rows = self._rows(
            select(*_EVENT_COLUMNS)
            .select_from(_events_with_link())
            .where(_mine(events, principal_id), events.c.issue_id == issue_id, _known(events, cut))
            .order_by(events.c.recorded_at, events.c.membership_event_id.collate("C"))
        )
        return tuple(_to_event(row) for row in rows)

    def link_revisions(
        self, principal_id: str, link_ids: Collection[str], cut: LineageFactCut
    ) -> Mapping[str, tuple[TimelineLinkRevision, ...]]:
        if not link_ids or cut.at is None:
            return {}
        revisions = record_link_revisions
        rows = self._rows(
            select(
                revisions.c.link_id,
                revisions.c.revision_no,
                revisions.c.revision_id,
                revisions.c.action,
                revisions.c.lifecycle_state,
                revisions.c.recorded_at,
            )
            .where(
                _mine(revisions, principal_id),
                revisions.c.link_id.in_(sorted(set(link_ids))),
                _known(revisions, cut),
            )
            .order_by(revisions.c.link_id, revisions.c.revision_no)
        )
        found: dict[str, list[TimelineLinkRevision]] = {}
        for row in rows:
            found.setdefault(row.link_id, []).append(
                TimelineLinkRevision(
                    link_id=row.link_id,
                    revision_no=int(row.revision_no),
                    revision_id=row.revision_id,
                    action=LinkRevisionAction(row.action),
                    lifecycle_state=LinkLifecycleState(row.lifecycle_state),
                    recorded_at=row.recorded_at,
                )
            )
        return {link_id: tuple(items) for link_id, items in found.items()}

    # --- the native plane (section 7.3, R3-F03, R3-F04) ----------------------------

    def native_events(
        self,
        principal_id: str,
        records: Collection[tuple[RecordEventFamily, str]],
        *,
        families: frozenset[RecordEventFamily],
        include_restricted_memory: bool,
        occurred_at_most: datetime | None,
        sequence_at_most: int | None,
    ) -> tuple[TimelineNativeEvent, ...]:
        # The feed module's own read, under its own predicate (R3-F03).
        return _bounded(
            lambda: issue_member_events(
                self._connection,
                principal_id,
                records,
                families=families,
                include_restricted_memory=include_restricted_memory,
                occurred_at_most=occurred_at_most,
                sequence_at_most=sequence_at_most,
            )
        )

    # --- Constraint revision snapshots (S3 section 12, D-13) ------------------------

    def constraint_snapshots(
        self, principal_id: str, versions: Collection[tuple[str, int]]
    ) -> Mapping[tuple[str, int], ConstraintRevisionSnapshot]:
        wanted = sorted(set(versions))
        if not wanted:
            return {}
        revisions = project_constraint_revisions
        parties = project_constraint_revision_parties
        rows = self._rows(
            select(
                revisions.c.revision_id,
                revisions.c.constraint_id,
                revisions.c.version,
                revisions.c.lifecycle_state,
            ).where(
                _mine(revisions, principal_id),
                tuple_(revisions.c.constraint_id, revisions.c.version).in_(wanted),
            )
        )
        if not rows:
            return {}
        by_revision = {row.revision_id: row for row in rows}
        party_rows = self._rows(
            select(
                parties.c.revision_id,
                parties.c.ordinal,
                parties.c.party_kind,
                parties.c.entity_id,
                parties.c.display_label,
                parties.c.original_label,
            )
            .select_from(
                parties.join(
                    revisions,
                    and_(
                        matching_partition_criterion(revisions, parties),
                        revisions.c.revision_id == parties.c.revision_id,
                    ),
                )
            )
            .where(
                _mine(parties, principal_id),
                parties.c.revision_id.in_(sorted(by_revision)),
                parties.c.role == _BIC_ROLE,
            )
            .order_by(parties.c.revision_id, parties.c.ordinal)
        )
        bic: dict[str, list[ConstraintPartyRow]] = {}
        for party in party_rows:
            owner = by_revision[party.revision_id]
            bic.setdefault(party.revision_id, []).append(
                ConstraintPartyRow(
                    constraint_id=owner.constraint_id,
                    role=_BIC_ROLE,
                    ordinal=int(party.ordinal),
                    party_kind=PartyKind(party.party_kind),
                    entity_id=party.entity_id,
                    display_label=party.display_label,
                    original_label=party.original_label,
                )
            )
        return {
            (row.constraint_id, int(row.version)): ConstraintRevisionSnapshot(
                constraint_id=row.constraint_id,
                version=int(row.version),
                lifecycle_state=row.lifecycle_state,
                bic=tuple(bic.get(row.revision_id, ())),
            )
            for row in rows
        }

    def entity_labels(self, principal_id: str, entity_ids: Collection[str]) -> Mapping[str, str]:
        wanted = sorted(set(entity_ids))
        if not wanted:
            return {}
        rows = self._rows(
            principal_scoped(
                select(entities.c.entity_id, entities.c.display_name),
                entities,
                capture_context(principal_id),
            ).where(entities.c.entity_id.in_(wanted))
        )
        return {row.entity_id: row.display_name for row in rows}
