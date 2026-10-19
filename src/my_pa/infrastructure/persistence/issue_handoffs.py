"""The record lineage S2 handoff ledger, behind `contracts.ports.IssueHandoffRepository`.

S2 contract sections 3.4, 4.2 and 6.2. Written here and nowhere else:
`issue_responsibility_events`. Read, never written: the evidence anchor each
event cites (`lineage_evidence_anchors`, the Issue repository's).

**The partition is reached through the guard.** Every SELECT composes
`principal_scoped` or `_mine` (`partition_criterion`), every INSERT `_bound`
(`principal_bound_values`), and every join `matching_partition_criterion`. The
Principal is only ever a parameter.

**Locks** are section 6.2 step 4's and the application sequences them: the
chain's advisory key `principal_id || ':handoff:' || issue_id || ':' ||
commitment_id` on the lineage namespace (`LINEAGE_ADVISORY_NAMESPACE`, the
two-key form) is taken after every `FOR SHARE` and before the chain's last
event is read, so two writers of one chain never both read the same last
event. Reads take no locks. Every statement runs through `issues._run`, so a
deadlock or serialization victim is `TransactionConflictError`; an insert that
loses the chain's sequence number anyway (`one_handoff_per_sequence`) is
`HandoffSequenceConflictError`, `conflict` / `stale_version`.

**S3** (S3 contract sections 3.3, 3.4 and 4.2) also writes
`issue_responsibility_corrections` (append-only; the commit mark is stamped by
the `a_lineage_fact_takes_its_commit_mark` trigger, never by this module) and
reads events and corrections as known at a cut: a row with a mark is known
when `commit_seq <= W(T)`, a pre-S3 row when its `recorded_at <= T`.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any, Final

from sqlalchemy import ColumnElement, Table, and_, false, insert, or_, select, text, tuple_
from sqlalchemy.engine import Connection, Row
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import (
    HandoffCorrectionRecord,
    HandoffPage,
    HandoffRecord,
    HandoffSequenceConflictError,
    IssueCursorError,
    IssueHandoffRepository,
    LineageLinkEvidence,
)
from my_pa.domain.lineage.model import EvidenceAnchor
from my_pa.domain.lineage.vocabulary import (
    EvidenceRole,
    EvidenceSourceFamily,
    SituationKind,
    SourceVersionKind,
)
from my_pa.infrastructure.persistence.issues import _run
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    matching_partition_criterion,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.record_lineage import LINEAGE_ADVISORY_NAMESPACE
from my_pa.infrastructure.persistence.tables import (
    issue_responsibility_corrections,
    issue_responsibility_events,
    lineage_evidence_anchors,
)

__all__ = ["SqlIssueHandoffRepository"]

#: The unique constraint a lost sequence number violates.
_SEQUENCE_CONSTRAINT: Final = "one_handoff_per_sequence"


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


_EVENTS: Final = issue_responsibility_events
_ANCHORS: Final = lineage_evidence_anchors
_CORRECTIONS: Final = issue_responsibility_corrections

_COLUMNS: Final = (
    _EVENTS.c.handoff_id,
    _EVENTS.c.issue_id,
    _EVENTS.c.commitment_id,
    _EVENTS.c.sequence_no,
    _EVENTS.c.predecessor_sequence_no,
    _EVENTS.c.from_holder_kind,
    _EVENTS.c.from_entity_id,
    _EVENTS.c.to_holder_kind,
    _EVENTS.c.to_entity_id,
    _EVENTS.c.effective_at,
    _EVENTS.c.recorded_at,
    _EVENTS.c.evidence_anchor_id,
    _EVENTS.c.reason,
    _EVENTS.c.acceptance_basis,
    _EVENTS.c.authority_class,
    _EVENTS.c.decision_channel,
    _EVENTS.c.source_capability,
    _EVENTS.c.commit_seq,
    _ANCHORS.c.source_family,
    _ANCHORS.c.source_root_id,
    _ANCHORS.c.source_version_kind,
    _ANCHORS.c.source_version_id,
    _ANCHORS.c.source_version_no,
    _ANCHORS.c.source_sha256,
    _ANCHORS.c.passage_start_cp,
    _ANCHORS.c.passage_end_cp,
    _ANCHORS.c.passage_sha256,
)


def _with_anchor() -> Any:  # noqa: ANN401 - a SQLAlchemy join
    return _EVENTS.join(
        _ANCHORS,
        and_(
            matching_partition_criterion(_ANCHORS, _EVENTS),
            _ANCHORS.c.anchor_id == _EVENTS.c.evidence_anchor_id,
        ),
    )


def _known(table: Table, watermark: int | None, at: datetime | None) -> ColumnElement[bool]:
    """S3 section 3.4: a row is known at the cut by its mark, or (pre-S3) its `recorded_at`."""
    if at is None:
        return false()
    known = and_(table.c.commit_seq.is_(None), table.c.recorded_at <= at)
    if watermark is not None:
        known = or_(table.c.commit_seq <= watermark, known)
    return known


def _anchor_of(row: Row[Any], role: EvidenceRole) -> EvidenceAnchor:
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
        role=role,
    )


_CORRECTION_COLUMNS: Final = (
    _CORRECTIONS.c.correction_id,
    _CORRECTIONS.c.handoff_id,
    _CORRECTIONS.c.correction_no,
    _CORRECTIONS.c.predecessor_correction_no,
    _CORRECTIONS.c.action,
    _CORRECTIONS.c.corrected_effective_at,
    _CORRECTIONS.c.evidence_anchor_id,
    _CORRECTIONS.c.evidence_role,
    _CORRECTIONS.c.reason,
    _CORRECTIONS.c.acceptance_basis,
    _CORRECTIONS.c.authority_class,
    _CORRECTIONS.c.decision_channel,
    _CORRECTIONS.c.source_capability,
    _CORRECTIONS.c.recorded_at,
    _CORRECTIONS.c.commit_seq,
    _ANCHORS.c.source_family,
    _ANCHORS.c.source_root_id,
    _ANCHORS.c.source_version_kind,
    _ANCHORS.c.source_version_id,
    _ANCHORS.c.source_version_no,
    _ANCHORS.c.source_sha256,
    _ANCHORS.c.passage_start_cp,
    _ANCHORS.c.passage_end_cp,
    _ANCHORS.c.passage_sha256,
)


def _correction_with_anchor() -> Any:  # noqa: ANN401 - a SQLAlchemy join
    return _CORRECTIONS.join(
        _ANCHORS,
        and_(
            matching_partition_criterion(_ANCHORS, _CORRECTIONS),
            _ANCHORS.c.anchor_id == _CORRECTIONS.c.evidence_anchor_id,
        ),
    )


def _to_correction(row: Row[Any]) -> HandoffCorrectionRecord:
    return HandoffCorrectionRecord(
        correction_id=row.correction_id,
        handoff_id=row.handoff_id,
        correction_no=row.correction_no,
        predecessor_correction_no=row.predecessor_correction_no,
        action=row.action,
        corrected_effective_at=row.corrected_effective_at,
        evidence=LineageLinkEvidence(
            anchor_id=row.evidence_anchor_id,
            anchor=_anchor_of(row, EvidenceRole(row.evidence_role)),
        ),
        reason=row.reason,
        acceptance_basis=row.acceptance_basis,
        authority_class=row.authority_class,
        decision_channel=row.decision_channel,
        source_capability=row.source_capability,
        recorded_at=row.recorded_at,
        commit_seq=row.commit_seq,
    )


def _to_record(row: Row[Any]) -> HandoffRecord:
    anchor = EvidenceAnchor(
        source_family=EvidenceSourceFamily(row.source_family),
        source_root_id=row.source_root_id,
        source_version_kind=SourceVersionKind(row.source_version_kind),
        source_version_id=row.source_version_id,
        source_version_no=row.source_version_no,
        source_sha256=row.source_sha256,
        passage_start_cp=row.passage_start_cp,
        passage_end_cp=row.passage_end_cp,
        passage_sha256=row.passage_sha256,
        # A handoff cites exactly one anchor, always in the `handoff` role.
        role=EvidenceRole.HANDOFF,
    )
    return HandoffRecord(
        handoff_id=row.handoff_id,
        issue_id=row.issue_id,
        commitment_id=row.commitment_id,
        sequence_no=row.sequence_no,
        predecessor_sequence_no=row.predecessor_sequence_no,
        from_holder_kind=row.from_holder_kind,
        from_entity_id=row.from_entity_id,
        to_holder_kind=row.to_holder_kind,
        to_entity_id=row.to_entity_id,
        effective_at=row.effective_at,
        recorded_at=row.recorded_at,
        evidence=LineageLinkEvidence(anchor_id=row.evidence_anchor_id, anchor=anchor),
        reason=row.reason,
        acceptance_basis=row.acceptance_basis,
        authority_class=row.authority_class,
        decision_channel=row.decision_channel,
        source_capability=row.source_capability,
        commit_seq=row.commit_seq,
    )


def _lost_the_sequence(error: IntegrityError) -> bool:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", None) == _SEQUENCE_CONSTRAINT


class SqlIssueHandoffRepository(IssueHandoffRepository):
    """`IssueHandoffRepository`, over the general unit of work's `Connection`."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def lock_chain(self, principal_id: str, issue_id: str, commitment_id: str) -> None:
        _run(
            lambda: self._connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock(CAST(:namespace AS integer), "
                    "hashtext(CAST(:principal_id AS text) || ':handoff:' || "
                    "CAST(:issue_id AS text) || ':' || CAST(:commitment_id AS text)))"
                ),
                {
                    "namespace": LINEAGE_ADVISORY_NAMESPACE,
                    "principal_id": principal_id,
                    "issue_id": issue_id,
                    "commitment_id": commitment_id,
                },
            )
        )

    def latest_event(
        self, principal_id: str, issue_id: str, commitment_id: str
    ) -> HandoffRecord | None:
        row = _run(
            lambda: self._connection.execute(
                select(*_COLUMNS)
                .select_from(_with_anchor())
                .where(
                    _mine(_EVENTS, principal_id),
                    _EVENTS.c.issue_id == issue_id,
                    _EVENTS.c.commitment_id == commitment_id,
                )
                .order_by(_EVENTS.c.sequence_no.desc())
                .limit(1)
            ).one_or_none()
        )
        return None if row is None else _to_record(row)

    def insert_event(self, principal_id: str, event: HandoffRecord) -> None:
        statement = insert(_EVENTS).values(
            _bound(
                _EVENTS,
                principal_id,
                {
                    "handoff_id": event.handoff_id,
                    "issue_id": event.issue_id,
                    "issue_kind": SituationKind.ISSUE_WORKSTREAM.value,
                    "commitment_id": event.commitment_id,
                    "sequence_no": event.sequence_no,
                    "predecessor_sequence_no": event.predecessor_sequence_no,
                    "from_holder_kind": event.from_holder_kind,
                    "from_entity_id": event.from_entity_id,
                    "to_holder_kind": event.to_holder_kind,
                    "to_entity_id": event.to_entity_id,
                    "effective_at": event.effective_at,
                    "recorded_at": event.recorded_at,
                    "evidence_anchor_id": event.evidence.anchor_id,
                    "reason": event.reason,
                    "acceptance_basis": event.acceptance_basis,
                    "authority_class": event.authority_class,
                    "decision_channel": event.decision_channel,
                    "source_capability": event.source_capability,
                },
            )
        )
        lost = False
        try:
            # The refusal rolls the whole transaction back with it.
            _run(lambda: self._connection.execute(statement))
        except IntegrityError as error:
            if not _lost_the_sequence(error):
                raise
            lost = True
        if lost:
            raise HandoffSequenceConflictError("another handoff took this sequence number")

    def read_event(self, principal_id: str, handoff_id: str) -> HandoffRecord | None:
        row = _run(
            lambda: self._connection.execute(
                select(*_COLUMNS)
                .select_from(_with_anchor())
                .where(_mine(_EVENTS, principal_id), _EVENTS.c.handoff_id == handoff_id)
            ).one_or_none()
        )
        return None if row is None else _to_record(row)

    def list_events(
        self,
        principal_id: str,
        issue_id: str,
        *,
        commitment_id: str | None,
        page_size: int,
        after: str | None,
    ) -> HandoffPage:
        return self._page(
            principal_id,
            issue_id,
            commitment_id=commitment_id,
            page_size=page_size,
            after=after,
            known=None,
        )

    def known_events(
        self,
        principal_id: str,
        issue_id: str,
        *,
        commitment_id: str | None,
        page_size: int,
        after: str | None,
        watermark: int | None,
        at: datetime | None,
    ) -> HandoffPage:
        return self._page(
            principal_id,
            issue_id,
            commitment_id=commitment_id,
            page_size=page_size,
            after=after,
            known=_known(_EVENTS, watermark, at),
        )

    def _page(
        self,
        principal_id: str,
        issue_id: str,
        *,
        commitment_id: str | None,
        page_size: int,
        after: str | None,
        known: ColumnElement[bool] | None,
    ) -> HandoffPage:
        within: list[ColumnElement[bool]] = [
            _mine(_EVENTS, principal_id),
            _EVENTS.c.issue_id == issue_id,
        ]
        if known is not None:
            within.append(known)
        if commitment_id is not None:
            within.append(_EVENTS.c.commitment_id == commitment_id)
        if after is not None:
            anchor = _run(
                lambda: self._connection.execute(
                    select(_EVENTS.c.recorded_at, _EVENTS.c.handoff_id).where(
                        *within, _EVENTS.c.handoff_id == after
                    )
                ).one_or_none()
            )
            if anchor is None:
                raise IssueCursorError()
            within.append(
                tuple_(_EVENTS.c.recorded_at, _EVENTS.c.handoff_id)
                > tuple_(anchor.recorded_at, anchor.handoff_id)
            )
        rows = _run(
            lambda: self._connection.execute(
                select(*_COLUMNS)
                .select_from(_with_anchor())
                .where(*within)
                .order_by(_EVENTS.c.recorded_at, _EVENTS.c.handoff_id)
                .limit(page_size + 1)
            ).all()
        )
        return HandoffPage(
            handoffs=tuple(_to_record(row) for row in rows[:page_size]),
            has_more=len(rows) > page_size,
        )

    # --- S3: corrections (S3 contract sections 3.3 and 4.2) ----------------------

    def chain_events(
        self, principal_id: str, issue_id: str, commitment_id: str
    ) -> tuple[HandoffRecord, ...]:
        rows = _run(
            lambda: self._connection.execute(
                select(*_COLUMNS)
                .select_from(_with_anchor())
                .where(
                    _mine(_EVENTS, principal_id),
                    _EVENTS.c.issue_id == issue_id,
                    _EVENTS.c.commitment_id == commitment_id,
                )
                .order_by(_EVENTS.c.sequence_no)
            ).all()
        )
        return tuple(_to_record(row) for row in rows)

    def corrections_of(
        self,
        principal_id: str,
        handoff_ids: Collection[str],
        *,
        watermark: int | None = None,
        at: datetime | None = None,
        current: bool = False,
    ) -> Mapping[str, tuple[HandoffCorrectionRecord, ...]]:
        if not handoff_ids:
            return {}
        within: list[ColumnElement[bool]] = [
            _mine(_CORRECTIONS, principal_id),
            _CORRECTIONS.c.handoff_id.in_(sorted(set(handoff_ids))),
        ]
        if not current:
            within.append(_known(_CORRECTIONS, watermark, at))
        rows = _run(
            lambda: self._connection.execute(
                select(*_CORRECTION_COLUMNS)
                .select_from(_correction_with_anchor())
                .where(*within)
                .order_by(_CORRECTIONS.c.handoff_id, _CORRECTIONS.c.correction_no)
            ).all()
        )
        found: dict[str, list[HandoffCorrectionRecord]] = {}
        for row in rows:
            found.setdefault(row.handoff_id, []).append(_to_correction(row))
        return {handoff_id: tuple(items) for handoff_id, items in found.items()}

    def read_correction(
        self, principal_id: str, correction_id: str
    ) -> HandoffCorrectionRecord | None:
        row = _run(
            lambda: self._connection.execute(
                select(*_CORRECTION_COLUMNS)
                .select_from(_correction_with_anchor())
                .where(
                    _mine(_CORRECTIONS, principal_id),
                    _CORRECTIONS.c.correction_id == correction_id,
                )
            ).one_or_none()
        )
        return None if row is None else _to_correction(row)

    def insert_correction(self, principal_id: str, correction: HandoffCorrectionRecord) -> None:
        _run(
            lambda: self._connection.execute(
                insert(_CORRECTIONS).values(
                    _bound(
                        _CORRECTIONS,
                        principal_id,
                        {
                            "correction_id": correction.correction_id,
                            "handoff_id": correction.handoff_id,
                            "correction_no": correction.correction_no,
                            "predecessor_correction_no": correction.predecessor_correction_no,
                            "action": correction.action,
                            "corrected_effective_at": correction.corrected_effective_at,
                            "evidence_anchor_id": correction.evidence.anchor_id,
                            "evidence_role": correction.evidence.anchor.role.value,
                            "reason": correction.reason,
                            "acceptance_basis": correction.acceptance_basis,
                            "authority_class": correction.authority_class,
                            "decision_channel": correction.decision_channel,
                            "source_capability": correction.source_capability,
                            "recorded_at": correction.recorded_at,
                        },
                    )
                )
            )
        )
