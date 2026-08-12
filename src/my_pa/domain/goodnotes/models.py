"""Immutable identities and source-bound OCR proposals for one bounded page."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

_ID = re.compile(r"\A(?:gnpg|gnver|gnreg|gnrec)_[a-f0-9]{24}\Z")


def issue_stable_id(prefix: str, *parts: str) -> str:
    if prefix not in {"gnpg", "gnver", "gnreg", "gnrec"}:
        raise ValueError("unknown GoodNotes identity prefix")
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _goodnotes_id(value: str, prefix: str) -> None:
    if not _ID.fullmatch(value) or not value.startswith(f"{prefix}_"):
        raise ValueError(f"invalid {prefix} identifier")


@dataclass(frozen=True, slots=True)
class RegionBox:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if min(self.x, self.y, self.width, self.height) < 0 or self.width == 0 or self.height == 0:
            raise ValueError("a source region must have positive bounded dimensions")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("source region coordinates are normalized to the page")


@dataclass(frozen=True, slots=True)
class GoodNotesPage:
    page_id: str
    principal_id: str
    source_id: str
    source_object_id: str
    page_number: int

    def __post_init__(self) -> None:
        _goodnotes_id(self.page_id, "gnpg")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        if self.page_number < 1:
            raise ValueError("page numbers start at one")


@dataclass(frozen=True, slots=True)
class GoodNotesPageVersion:
    page_version_id: str
    page_id: str
    source_version_id: str
    content_sha256: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _goodnotes_id(self.page_version_id, "gnver")
        _goodnotes_id(self.page_id, "gnpg")
        validate_identifier(self.source_version_id, IdKind.VERSION)
        if not re.fullmatch(r"[a-f0-9]{64}", self.content_sha256):
            raise ValueError("content digest must be SHA-256")
        ensure_utc(self.observed_at)


@dataclass(frozen=True, slots=True)
class GoodNotesRegionProposal:
    region_id: str
    page_version_id: str
    ordinal: int
    box: RegionBox
    transcription: str = field(repr=False)
    confidence: float
    extractor: str
    extractor_version: str

    def __post_init__(self) -> None:
        _goodnotes_id(self.region_id, "gnreg")
        _goodnotes_id(self.page_version_id, "gnver")
        if self.ordinal < 0 or not self.transcription or len(self.transcription) > 20_000:
            raise ValueError("a bounded transcription is required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if not self.extractor or not self.extractor_version:
            raise ValueError("extractor provenance is required")


@dataclass(frozen=True, slots=True)
class SourcePage:
    principal_id: str
    source_id: str
    source_object_id: str
    source_version_id: str
    page_number: int
    observed_at: datetime
    content: bytes = field(repr=False)
    representation_media_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.source_version_id, IdKind.VERSION)
        if self.page_number < 1 or not self.content:
            raise ValueError("a non-empty source page is required")
        ensure_utc(self.observed_at)
        if self.representation_media_type not in {
            "application/pdf",
            "image/jpeg",
            "image/png",
            "application/octet-stream",
        }:
            raise ValueError("unsupported GoodNotes page representation")


@dataclass(frozen=True, slots=True)
class TranscribedRegion:
    box: RegionBox
    text: str = field(repr=False)
    confidence: float


@dataclass(frozen=True, slots=True)
class ReconciliationReceipt:
    receipt_id: str
    principal_id: str
    idempotency_key: str
    request_fingerprint: str
    page_version_ids: tuple[str, ...]
    created_regions: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class GoodNotesSearchHit:
    region_id: str
    page_version_id: str
    source_version_id: str
    page_number: int
    accepted_text: str = field(repr=False)
    corrected: bool
