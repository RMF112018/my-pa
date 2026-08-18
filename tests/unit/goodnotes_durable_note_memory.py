"""In-memory durable-note store: lineage, stages, rasters, proposals, notes, preview."""

from __future__ import annotations

from my_pa.domain.goodnotes.models import (
    GoodNotesDeliveryAttempt,
    GoodNotesDeliveryReceipt,
    GoodNotesEntityAssociation,
    GoodNotesEntityDirectoryRecord,
    GoodNotesNote,
    GoodNotesNoteLink,
    GoodNotesNoteOccurrence,
    GoodNotesNoteRevision,
    GoodNotesPageRaster,
    GoodNotesRunNoteChange,
    GoodNotesRunStage,
    GoodNotesSourceSnapshot,
)
from tests.unit.goodnotes_lineage_memory import MemoryLineageRepository


class MemoryDurableNoteStore(MemoryLineageRepository):
    def __init__(self) -> None:
        super().__init__()
        self._stages: dict[tuple[str, str, str], GoodNotesRunStage] = {}
        self._rasters: dict[tuple[str, str], GoodNotesPageRaster] = {}
        self._proposals: list[tuple[str, str, str, str, str, str, dict[str, object]]] = []
        self._notes: dict[tuple[str, str], GoodNotesNote] = {}
        self._occurrences: dict[tuple[str, str], GoodNotesNoteOccurrence] = {}
        self._revisions: dict[tuple[str, str], GoodNotesNoteRevision] = {}
        self._links: dict[tuple[str, str], GoodNotesNoteLink] = {}
        self._changes: dict[tuple[str, str], GoodNotesRunNoteChange] = {}
        self._receipts: dict[tuple[str, str, str, str], GoodNotesDeliveryReceipt] = {}
        self._attempts: list[GoodNotesDeliveryAttempt] = []
        self._associations: list[GoodNotesEntityAssociation] = []

    def snapshots_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesSourceSnapshot, ...]:
        found = [
            item
            for item in self._snapshots.values()
            if item.principal_id == principal_id and item.run_id == run_id
        ]
        return tuple(sorted(found, key=lambda item: item.observed_at))

    def try_lock_source_root(self, principal_id: str, source_root_id: str) -> bool:
        del principal_id, source_root_id
        return True

    def record_stage(self, stage: GoodNotesRunStage) -> GoodNotesRunStage:
        self._stages[(stage.principal_id, stage.run_id, stage.stage.value)] = stage
        return stage

    def stages(self, principal_id: str, run_id: str) -> tuple[GoodNotesRunStage, ...]:
        found = [
            item
            for (owner, stored_run, _), item in self._stages.items()
            if owner == principal_id and stored_run == run_id
        ]
        return tuple(sorted(found, key=lambda item: item.started_at))

    def store_page_raster(self, raster: GoodNotesPageRaster) -> GoodNotesPageRaster:
        self._rasters[(raster.principal_id, raster.page_version_id)] = raster
        return raster

    def page_raster(self, principal_id: str, page_version_id: str) -> GoodNotesPageRaster | None:
        return self._rasters.get((principal_id, page_version_id))

    def store_semantic_proposal(
        self,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        schema_version: str,
        analyzer_name: str,
        analyzer_version: str,
        payload: dict[str, object],
    ) -> None:
        self._proposals.append(
            (
                principal_id,
                run_id,
                page_version_id,
                schema_version,
                analyzer_name,
                analyzer_version,
                payload,
            )
        )

    def semantic_proposals_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[tuple[str, str, str, str, dict[str, object]], ...]:
        return tuple(
            row[2:] for row in self._proposals if row[0] == principal_id and row[1] == run_id
        )

    def occurrences_for_logical_pages(
        self, principal_id: str, logical_page_ids: tuple[str, ...]
    ) -> tuple[GoodNotesNoteOccurrence, ...]:
        wanted = set(logical_page_ids)
        return tuple(
            item
            for item in self._occurrences.values()
            if item.principal_id == principal_id and item.logical_page_id in wanted
        )

    def occurrences_for_notebook(
        self, principal_id: str, notebook_id: str
    ) -> tuple[GoodNotesNoteOccurrence, ...]:
        pages = {
            item.logical_page_id
            for item in self._logical.values()
            if item.principal_id == principal_id and item.notebook_id == notebook_id
        }
        return tuple(
            item
            for item in self._occurrences.values()
            if item.principal_id == principal_id and item.logical_page_id in pages
        )

    def latest_revision_for_occurrence(
        self, principal_id: str, occurrence_id: str
    ) -> GoodNotesNoteRevision | None:
        found = [
            item
            for item in self._revisions.values()
            if item.principal_id == principal_id and item.occurrence_id == occurrence_id
        ]
        if not found:
            return None
        return max(found, key=lambda item: item.created_at)

    def revision(self, principal_id: str, revision_id: str) -> GoodNotesNoteRevision | None:
        return self._revisions.get((principal_id, revision_id))

    def run_note_changes(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesRunNoteChange, ...]:
        return tuple(
            item
            for item in self._changes.values()
            if item.principal_id == principal_id and item.run_id == run_id
        )

    def note(self, principal_id: str, note_id: str) -> GoodNotesNote | None:
        return self._notes.get((principal_id, note_id))

    def store_note(self, note: GoodNotesNote) -> GoodNotesNote:
        self._notes[(note.principal_id, note.note_id)] = note
        return note

    def store_occurrence(self, occurrence: GoodNotesNoteOccurrence) -> GoodNotesNoteOccurrence:
        self._occurrences[(occurrence.principal_id, occurrence.occurrence_id)] = occurrence
        return occurrence

    def occurrence(self, principal_id: str, occurrence_id: str) -> GoodNotesNoteOccurrence | None:
        return self._occurrences.get((principal_id, occurrence_id))

    def store_revision(self, revision: GoodNotesNoteRevision) -> GoodNotesNoteRevision:
        self._revisions[(revision.principal_id, revision.revision_id)] = revision
        return revision

    def store_note_link(self, link: GoodNotesNoteLink) -> GoodNotesNoteLink:
        self._links[(link.principal_id, link.link_id)] = link
        return link

    def store_run_note_change(self, change: GoodNotesRunNoteChange) -> GoodNotesRunNoteChange:
        self._changes[(change.principal_id, change.change_id)] = change
        return change

    def entity_directory(self, principal_id: str) -> tuple[GoodNotesEntityDirectoryRecord, ...]:
        del principal_id
        return ()

    def store_entity_association(
        self, association: GoodNotesEntityAssociation
    ) -> GoodNotesEntityAssociation:
        self._associations.append(association)
        return association

    def entity_associations_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesEntityAssociation, ...]:
        return tuple(
            item
            for item in self._associations
            if item.principal_id == principal_id and item.run_id == run_id
        )

    def store_delivery_receipt(self, receipt: GoodNotesDeliveryReceipt) -> GoodNotesDeliveryReceipt:
        self._receipts[
            (receipt.principal_id, receipt.run_id, receipt.destination, receipt.summary_hash)
        ] = receipt
        return receipt

    def delivery_receipt_by_key(
        self,
        principal_id: str,
        run_id: str,
        destination: str,
        summary_hash: str,
    ) -> GoodNotesDeliveryReceipt | None:
        return self._receipts.get((principal_id, run_id, destination, summary_hash))

    def delivery_receipts_for_run(
        self, principal_id: str, run_id: str
    ) -> tuple[GoodNotesDeliveryReceipt, ...]:
        found = [
            item
            for item in self._receipts.values()
            if item.principal_id == principal_id and item.run_id == run_id
        ]
        return tuple(sorted(found, key=lambda item: item.created_at))

    def store_delivery_attempt(self, attempt: GoodNotesDeliveryAttempt) -> GoodNotesDeliveryAttempt:
        for existing in self._attempts:
            if existing.attempt_id == attempt.attempt_id:
                return existing
            if (
                existing.idempotency_token == attempt.idempotency_token
                and existing.state is attempt.state
            ):
                return existing
        self._attempts.append(attempt)
        return attempt

    def delivery_attempt(
        self, principal_id: str, attempt_id: str
    ) -> GoodNotesDeliveryAttempt | None:
        for item in self._attempts:
            if item.principal_id == principal_id and item.attempt_id == attempt_id:
                return item
        return None

    def delivery_attempts_for_token(
        self, principal_id: str, idempotency_token: str
    ) -> tuple[GoodNotesDeliveryAttempt, ...]:
        return tuple(
            item
            for item in self._attempts
            if item.principal_id == principal_id and item.idempotency_token == idempotency_token
        )
