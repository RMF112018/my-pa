"""In-memory durable-note store: lineage, stages, rasters, proposals, notes, preview."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass

from my_pa.application.goodnotes_occurrences import semantic_proposal_sha256
from my_pa.contracts.ports import GoodNotesSemanticProposalMaterial
from my_pa.domain.capture.review import Disposition
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
    issue_stable_id,
)
from tests.unit.goodnotes_lineage_memory import MemoryLineageRepository


@dataclass(frozen=True)
class MemorySemanticReview:
    proposal_id: str
    original_digest: str
    decision_id: str
    sequence: int
    disposition: Disposition
    payload: dict[str, object]


class MemoryDurableNoteStore(MemoryLineageRepository):
    def __init__(self) -> None:
        super().__init__()
        self._reviews: dict[tuple[str, str, str], MemorySemanticReview] = {}
        self._promotions: dict[tuple[str, str], str] = {}
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

    def review_semantic_proposal(
        self,
        principal_id: str,
        run_id: str,
        page_version_id: str,
        disposition: Disposition = Disposition.ACCEPT,
        corrected_payload: dict[str, object] | None = None,
    ) -> None:
        """Explicit synthetic Review ledger append, independent of caller evidence."""
        if (principal_id, run_id) in self._promotions:
            raise ValueError("promoted Review is terminal")
        proposal = next(
            row
            for row in self.semantic_proposals_for_run(principal_id, run_id)
            if row[0] == page_version_id
        )
        key = (principal_id, run_id, page_version_id)
        prior = self._reviews.get(key)
        sequence = 1 if prior is None else prior.sequence + 1
        digest = semantic_proposal_sha256(*proposal)
        self._reviews[key] = MemorySemanticReview(
            issue_stable_id("gnrun", principal_id, run_id, page_version_id),
            digest,
            issue_stable_id("gnrun", principal_id, run_id, page_version_id, str(sequence)),
            sequence,
            disposition,
            deepcopy(proposal[4] if corrected_payload is None else corrected_payload),
        )

    def accepted_semantic_material(
        self, principal_id: str, run_id: str, *, require_promoted: bool = False
    ) -> tuple[GoodNotesSemanticProposalMaterial, ...] | None:
        proposals = self.semantic_proposals_for_run(principal_id, run_id)
        snapshots = self.snapshots_for_run(principal_id, run_id)
        positions = tuple(
            position
            for snapshot in snapshots
            for position in self.page_positions(principal_id, snapshot.snapshot_id)
        )
        expected = {position.page_version_id for position in positions}
        if (
            not snapshots
            or not positions
            or None in expected
            or len(proposals) != len(expected)
            or {row[0] for row in proposals} != expected
        ):
            return None
        material = []
        bindings = []
        for proposal in sorted(proposals, key=lambda row: row[0]):
            page_id = proposal[0]
            raster = self.page_raster(principal_id, page_id)
            if raster is None or raster.run_id != run_id:
                return None
            review = self._reviews.get((principal_id, run_id, page_id))
            if review is None:
                return None
            if review.original_digest != semantic_proposal_sha256(*proposal):
                raise ValueError("semantic proposal digest changed")
            if review.disposition not in {Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT}:
                raise ValueError("semantic proposal is not eligible for promotion")
            accepted_digest = semantic_proposal_sha256(*proposal[:4], review.payload)
            bindings.append(
                (
                    page_id,
                    review.proposal_id,
                    review.original_digest,
                    review.decision_id,
                    review.sequence,
                    accepted_digest,
                )
            )
            material.append(
                GoodNotesSemanticProposalMaterial(
                    proposal_id=review.proposal_id,
                    run_id=run_id,
                    page_version_id=page_id,
                    content_sha256=raster.png_sha256,
                    schema_version=proposal[1],
                    analyzer_name=proposal[2],
                    analyzer_version=proposal[3],
                    payload=deepcopy(review.payload),
                )
            )
        binding = hashlib.sha256(json.dumps(bindings, sort_keys=True).encode()).hexdigest()
        held = self._promotions.get((principal_id, run_id))
        if held is not None and held != binding:
            raise ValueError("semantic promotion binding changed")
        if require_promoted and held is None:
            return None
        return tuple(material)

    def record_semantic_promotion(self, principal_id: str, run_id: str) -> str:
        material = self.accepted_semantic_material(principal_id, run_id)
        if material is None:
            raise ValueError("semantic run lacks complete server review evidence")
        bindings = []
        for item in material:
            review = self._reviews[(principal_id, run_id, item.page_version_id)]
            bindings.append(
                (
                    item.page_version_id,
                    review.proposal_id,
                    review.original_digest,
                    review.decision_id,
                    review.sequence,
                    semantic_proposal_sha256(
                        item.page_version_id,
                        item.schema_version,
                        item.analyzer_name,
                        item.analyzer_version,
                        item.payload,
                    ),
                )
            )
        self._promotions[(principal_id, run_id)] = hashlib.sha256(
            json.dumps(bindings, sort_keys=True).encode()
        ).hexdigest()
        return issue_stable_id("gnrun", principal_id, run_id)

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
