"""Operator-controlled handwriting corpus admission. No live GoodNotes ingest."""

from __future__ import annotations

from dataclasses import dataclass

from my_pa.application.goodnotes_gsqs import (
    CONTROLLED_HANDWRITING_READY_FOR_REVIEW,
    CorpusPartition,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
    FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
    ReviewState,
    SourceLayer,
    refuse_production_fixture,
)

HANDWRITING_STATE = CONTROLLED_HANDWRITING_READY_FOR_REVIEW
ALLOWED_HANDWRITING_CLASSES = frozenset(
    {
        FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
        FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
    }
)
ALLOWED_SAMPLE_PHRASES = (
    "Review agenda Monday",
    "Send crane plan Friday",
    "Call partner after meeting",
    "Buy spare markers",
    "Thank partner for intro",
)
REQUESTED_STYLES = (
    "print",
    "cursive",
    "mixed-print-cursive",
    "compact",
    "large",
    "slanted",
    "messy-readable",
    "uncertain",
    "genuinely-unreadable",
)


@dataclass(frozen=True, slots=True)
class HandwritingAdmission:
    case_id: str
    artifact_sha256: str
    external_ref: str
    fixture_classification: str
    phrases: tuple[str, ...]
    style: str
    leakage_group_id: str
    review_state: ReviewState
    partition: CorpusPartition | None
    source_layer: SourceLayer = SourceLayer.CONTROLLED_HANDWRITING


def handwriting_catalog() -> tuple[HandwritingAdmission, ...]:
    """No handwriting bytes are stored in the repository."""
    return ()


def admit_handwriting(record: HandwritingAdmission) -> HandwritingAdmission:
    refuse_production_fixture(record.fixture_classification)
    if record.fixture_classification not in ALLOWED_HANDWRITING_CLASSES:
        raise ValueError("handwriting admission requires an allowed fixture class")
    if record.source_layer is not SourceLayer.CONTROLLED_HANDWRITING:
        raise ValueError("handwriting admission requires CONTROLLED_HANDWRITING source layer")
    try:
        digest = bytes.fromhex(record.artifact_sha256)
    except ValueError as exc:
        raise ValueError("handwriting artifact digest must be sha256 hex") from exc
    if len(digest) != 32:
        raise ValueError("handwriting artifact digest must be sha256 hex")
    if not record.external_ref:
        raise ValueError("handwriting admission requires an external private artifact reference")
    return record
