"""Principal-partitioned GoodNotes NEW-only delivery receipts and associations."""

from __future__ import annotations

from sqlalchemy import ColumnElement, Table, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection

from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryReceipt,
    GoodNotesEntityAssociation,
    GoodNotesEntityDirectoryRecord,
    GoodNotesEntityKind,
    GoodNotesEntityResolution,
    GoodNotesIngestionRun,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesRunNoteChange,
)
from my_pa.infrastructure.persistence.goodnotes import PostgresGoodNotesRepository
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    goodnotes_delivery_receipts,
    goodnotes_entity_associations,
    goodnotes_notes,
    projects,
    relationship_people,
)


def _mine(table: Table, principal_id: str) -> ColumnElement[bool]:
    return partition_criterion(table, capture_context(principal_id))


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


class PostgresGoodNotesDeliveryRepository:
    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self._notes = PostgresGoodNotesRepository(connection)

    def run(self, principal_id: str, run_id: str) -> GoodNotesIngestionRun | None:
        return self._notes.run(principal_id, run_id)

    def run_note_changes(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesRunNoteChange, ...]:
        return self._notes.run_note_changes(principal_id, run_id)

    def occurrence(self, principal_id: str, occurrence_id: str) -> GoodNotesNoteOccurrence | None:
        return self._notes.occurrence(principal_id, occurrence_id)

    def latest_revision_for_occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteRevision | None:
        return self._notes.latest_revision_for_occurrence(principal_id, occurrence_id)

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]:
        return self._notes.semantic_proposals_for_run(principal_id, run_id)

    def entity_directory(self, principal_id: str) -> tuple[GoodNotesEntityDirectoryRecord, ...]:
        records: list[GoodNotesEntityDirectoryRecord] = []
        for row in (
            self.connection.execute(
                select(projects.c.project_id, projects.c.name).where(_mine(projects, principal_id))
            )
            .mappings()
            .all()
        ):
            records.append(
                GoodNotesEntityDirectoryRecord(
                    entity_id=str(row["project_id"]),
                    kind=GoodNotesEntityKind.PROJECT,
                    normalized_name=" ".join(str(row["name"]).casefold().split()),
                )
            )
        for row in (
            self.connection.execute(
                select(relationship_people.c.person_id, relationship_people.c.display_name).where(
                    _mine(relationship_people, principal_id),
                    relationship_people.c.superseded_by_person_id.is_(None),
                )
            )
            .mappings()
            .all()
        ):
            records.append(
                GoodNotesEntityDirectoryRecord(
                    entity_id=str(row["person_id"]),
                    kind=GoodNotesEntityKind.PERSON,
                    normalized_name=" ".join(str(row["display_name"]).casefold().split()),
                )
            )
        for row in (
            self.connection.execute(
                select(goodnotes_notes.c.note_id).where(_mine(goodnotes_notes, principal_id))
            )
            .mappings()
            .all()
        ):
            records.append(
                GoodNotesEntityDirectoryRecord(
                    entity_id=str(row["note_id"]),
                    kind=GoodNotesEntityKind.NOTE,
                )
            )
        return tuple(records)

    def store_entity_association(
        self, association: GoodNotesEntityAssociation
    ) -> GoodNotesEntityAssociation:
        expected = _bound(
            goodnotes_entity_associations,
            association.principal_id,
            {
                "association_id": association.association_id,
                "run_id": association.run_id,
                "note_id": association.note_id,
                "candidate": association.candidate,
                "rank": association.rank,
                "resolution": association.resolution.value,
                "entity_kind": None
                if association.entity_kind is None
                else association.entity_kind.value,
                "resolved_id": association.resolved_id,
                "created_at": association.created_at,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_entity_associations)
            .values(expected)
            .on_conflict_do_nothing(index_elements=["principal_id", "association_id"])
        )
        stored = self.entity_association(association.principal_id, association.association_id)
        if stored is None:
            raise ValueError("the GoodNotes entity association could not be stored")
        if (
            stored.run_id != association.run_id
            or stored.note_id != association.note_id
            or stored.candidate != association.candidate
            or stored.rank != association.rank
            or stored.resolution != association.resolution
            or stored.entity_kind != association.entity_kind
            or stored.resolved_id != association.resolved_id
        ):
            raise ValueError(
                "the stable GoodNotes entity association identity collided with other content"
            )
        return stored

    def entity_association(
        self, principal_id: str, association_id: str
    ) -> GoodNotesEntityAssociation | None:
        row = (
            self.connection.execute(
                select(goodnotes_entity_associations).where(
                    _mine(goodnotes_entity_associations, principal_id),
                    goodnotes_entity_associations.c.association_id == association_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _association(row)

    def entity_associations_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesEntityAssociation, ...]:
        rows = (
            self.connection.execute(
                select(goodnotes_entity_associations)
                .where(
                    _mine(goodnotes_entity_associations, principal_id),
                    goodnotes_entity_associations.c.run_id == run_id,
                )
                .order_by(
                    goodnotes_entity_associations.c.created_at,
                    goodnotes_entity_associations.c.association_id,
                )
            )
            .mappings()
            .all()
        )
        return tuple(_association(row) for row in rows)

    def store_delivery_receipt(self, receipt: GoodNotesDeliveryReceipt) -> GoodNotesDeliveryReceipt:
        expected = _bound(
            goodnotes_delivery_receipts,
            receipt.principal_id,
            {
                "receipt_id": receipt.receipt_id,
                "run_id": receipt.run_id,
                "destination": receipt.destination,
                "summary_hash": receipt.summary_hash,
                "suppressed": receipt.suppressed,
                "body": receipt.body,
                "created_at": receipt.created_at,
            },
        )
        self.connection.execute(
            pg_insert(goodnotes_delivery_receipts)
            .values(expected)
            .on_conflict_do_nothing(index_elements=["principal_id", "receipt_id"])
        )
        stored = self.delivery_receipt(receipt.principal_id, receipt.receipt_id)
        if stored is None:
            by_key = self.delivery_receipt_by_key(
                receipt.principal_id,
                receipt.run_id,
                receipt.destination,
                receipt.summary_hash,
            )
            if by_key is None:
                raise ValueError("the GoodNotes delivery receipt could not be stored")
            stored = by_key
        if (
            stored.run_id != receipt.run_id
            or stored.destination != receipt.destination
            or stored.summary_hash != receipt.summary_hash
            or stored.suppressed != receipt.suppressed
            or stored.body != receipt.body
        ):
            raise ValueError(
                "the stable GoodNotes delivery receipt identity collided with other content"
            )
        return stored

    def delivery_receipt(
        self, principal_id: str, receipt_id: str
    ) -> GoodNotesDeliveryReceipt | None:
        row = (
            self.connection.execute(
                select(goodnotes_delivery_receipts).where(
                    _mine(goodnotes_delivery_receipts, principal_id),
                    goodnotes_delivery_receipts.c.receipt_id == receipt_id,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _delivery_receipt(row)

    def delivery_receipt_by_key(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        summary_hash: str,
    ) -> GoodNotesDeliveryReceipt | None:
        row = (
            self.connection.execute(
                select(goodnotes_delivery_receipts).where(
                    _mine(goodnotes_delivery_receipts, principal_id),
                    goodnotes_delivery_receipts.c.run_id == run_id,
                    goodnotes_delivery_receipts.c.destination == destination,
                    goodnotes_delivery_receipts.c.summary_hash == summary_hash,
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _delivery_receipt(row)


def _association(row: object) -> GoodNotesEntityAssociation:
    values = row
    kind = values["entity_kind"]  # type: ignore[index]
    return GoodNotesEntityAssociation(
        association_id=values["association_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        run_id=values["run_id"],  # type: ignore[index]
        note_id=values["note_id"],  # type: ignore[index]
        candidate=values["candidate"],  # type: ignore[index]
        rank=int(values["rank"]),  # type: ignore[index]
        resolution=GoodNotesEntityResolution(values["resolution"]),  # type: ignore[index]
        created_at=values["created_at"],  # type: ignore[index]
        entity_kind=None if kind is None else GoodNotesEntityKind(str(kind)),
        resolved_id=values["resolved_id"],  # type: ignore[index]
    )


def _delivery_receipt(row: object) -> GoodNotesDeliveryReceipt:
    values = row
    return GoodNotesDeliveryReceipt(
        receipt_id=values["receipt_id"],  # type: ignore[index]
        principal_id=values["principal_id"],  # type: ignore[index]
        run_id=values["run_id"],  # type: ignore[index]
        destination=values["destination"],  # type: ignore[index]
        summary_hash=values["summary_hash"],  # type: ignore[index]
        suppressed=bool(values["suppressed"]),  # type: ignore[index]
        created_at=values["created_at"],  # type: ignore[index]
        body=values["body"],  # type: ignore[index]
    )
