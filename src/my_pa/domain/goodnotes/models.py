"""Immutable identities and source-bound OCR proposals for one bounded page."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.domain.capture.proposal import ProposalState, RiskClass
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

_ID_PREFIXES = frozenset({"gnpg", "gnver", "gnreg", "gnrec", "gnnb", "gnsnap", "gnlp", "gnrun"})
_ID = re.compile(r"\A(?:gnpg|gnver|gnreg|gnrec|gnnb|gnsnap|gnlp|gnrun)_[a-f0-9]{24}\Z")
_SHA256 = re.compile(r"\A[a-f0-9]{64}\Z")


def issue_stable_id(prefix: str, *parts: str) -> str:
    if prefix not in _ID_PREFIXES:
        raise ValueError("unknown GoodNotes identity prefix")
    digest = hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _goodnotes_id(value: str, prefix: str) -> None:
    if not _ID.fullmatch(value) or not value.startswith(f"{prefix}_"):
        raise ValueError(f"invalid {prefix} identifier")


def _sha256(value: str, *, what: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{what} must be SHA-256")


def _bounded_text(value: str, *, what: str, maximum: int) -> None:
    if not 1 <= len(value) <= maximum or "\x00" in value:
        raise ValueError(f"{what} must be a bounded non-empty string")


def _root_alias(value: str) -> None:
    _bounded_text(value, what="source root alias", maximum=128)
    if "/" in value:
        raise ValueError("source_root_id is an opaque alias, not a filesystem path")


class GoodNotesIdentityStatus(StrEnum):
    ACTIVE = "ACTIVE"
    AMBIGUOUS = "AMBIGUOUS"
    RETIRED = "RETIRED"


class GoodNotesMatchMethod(StrEnum):
    EXACT_NORMALIZED_RENDER = "EXACT_NORMALIZED_RENDER"
    EXACT_CANONICAL_RENDER = "EXACT_CANONICAL_RENDER"
    STRONG_VISUAL_FINGERPRINT = "STRONG_VISUAL_FINGERPRINT"
    PERCEPTUAL_STRUCTURAL = "PERCEPTUAL_STRUCTURAL"
    SEQUENCE_TIEBREAK = "SEQUENCE_TIEBREAK"
    ORDINAL_WEAK = "ORDINAL_WEAK"
    UNRESOLVED = "UNRESOLVED"


class GoodNotesIngestionStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BUSY = "BUSY"
    REPLAYED = "REPLAYED"


class GoodNotesIngestionTrigger(StrEnum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"
    REPLAY = "REPLAY"


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
    logical_page_id: str | None = None
    normalized_render_sha256: str | None = None
    perceptual_hash: str | None = None
    render_width: int | None = None
    render_height: int | None = None
    renderer_name: str | None = None
    renderer_version: str | None = None
    render_profile_version: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.page_version_id, "gnver")
        _goodnotes_id(self.page_id, "gnpg")
        validate_identifier(self.source_version_id, IdKind.VERSION)
        _sha256(self.content_sha256, what="content digest")
        ensure_utc(self.observed_at)
        if self.logical_page_id is not None:
            _goodnotes_id(self.logical_page_id, "gnlp")
        if self.normalized_render_sha256 is not None:
            _sha256(self.normalized_render_sha256, what="normalized render digest")
        if self.perceptual_hash is not None:
            _bounded_text(self.perceptual_hash, what="perceptual hash", maximum=128)
        if self.render_width is not None and self.render_width < 1:
            raise ValueError("render width must be positive")
        if self.render_height is not None and self.render_height < 1:
            raise ValueError("render height must be positive")
        for name in ("renderer_name", "renderer_version", "render_profile_version"):
            value = getattr(self, name)
            if value is not None:
                _bounded_text(value, what=name.replace("_", " "), maximum=100)


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


@dataclass(frozen=True, slots=True, order=True)
class GoodNotesSourceBinding:
    """Exact registry identity a GoodNotes manifest must be enrolled to use."""

    source_id: str
    source_object_id: str
    source_version_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.source_version_id, IdKind.VERSION)


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


@dataclass(frozen=True, slots=True)
class GoodNotesReviewItem:
    region_id: str
    page_version_id: str
    source_version_id: str
    page_number: int
    transcription: str = field(repr=False)
    confidence: float


@dataclass(frozen=True, slots=True)
class GoodNotesReviewCase:
    """One OCR region exposed through the ordinary canonical Review surface."""

    review_case_id: str
    proposal_id: str
    region_id: str
    page_version_id: str
    principal_id: str
    confidence: float
    opened_at: datetime
    proposal_state: ProposalState = ProposalState.NEEDS_REVIEW
    risk_class: RiskClass = RiskClass.MODERATE
    review_version: int = 0
    latest_disposition: Disposition | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.review_case_id, IdKind.REVIEW_CASE)
        validate_identifier(self.proposal_id, IdKind.PROPOSAL)
        _goodnotes_id(self.region_id, "gnreg")
        _goodnotes_id(self.page_version_id, "gnver")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        ensure_utc(self.opened_at)
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if self.review_version < 0:
            raise ValueError("a review version is not negative")
        if (self.review_version == 0) is not (self.latest_disposition is None):
            raise ValueError("an undecided case has version zero and no disposition")


@dataclass(frozen=True, slots=True)
class GoodNotesNotebook:
    """Stable notebook identity. Path is not a field: it is history elsewhere."""

    notebook_id: str
    principal_id: str
    source_root_id: str
    identity_status: GoodNotesIdentityStatus
    created_at: datetime
    last_observed_at: datetime
    label: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.notebook_id, "gnnb")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _root_alias(self.source_root_id)
        ensure_utc(self.created_at)
        ensure_utc(self.last_observed_at)
        if self.last_observed_at < self.created_at:
            raise ValueError("a notebook cannot be observed before it was created")
        if self.label is not None:
            _bounded_text(self.label, what="notebook label", maximum=200)


@dataclass(frozen=True, slots=True)
class GoodNotesNotebookPath:
    """One observed path for a notebook. Path is history, not identity."""

    principal_id: str
    notebook_id: str
    path: str
    first_seen_at: datetime
    last_seen_at: datetime
    is_current: bool
    first_snapshot_id: str | None = None
    last_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.notebook_id, "gnnb")
        _bounded_text(self.path, what="observed path", maximum=1024)
        ensure_utc(self.first_seen_at)
        ensure_utc(self.last_seen_at)
        if self.last_seen_at < self.first_seen_at:
            raise ValueError("a path cannot be last seen before it was first seen")
        if self.first_snapshot_id is not None:
            _goodnotes_id(self.first_snapshot_id, "gnsnap")
        if self.last_snapshot_id is not None:
            _goodnotes_id(self.last_snapshot_id, "gnsnap")


@dataclass(frozen=True, slots=True)
class GoodNotesSourceSnapshot:
    snapshot_id: str
    principal_id: str
    notebook_id: str
    source_object_id: str
    observed_path: str
    raw_sha256: str
    size_bytes: int
    page_count: int
    observed_at: datetime
    settled_at: datetime
    run_id: str
    mtime_ns: int | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.snapshot_id, "gnsnap")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.notebook_id, "gnnb")
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        _bounded_text(self.observed_path, what="observed path", maximum=1024)
        _sha256(self.raw_sha256, what="raw digest")
        if self.size_bytes < 1:
            raise ValueError("snapshot size must be positive")
        if self.page_count < 0:
            raise ValueError("page count is not negative")
        ensure_utc(self.observed_at)
        ensure_utc(self.settled_at)
        if self.settled_at < self.observed_at:
            raise ValueError("a snapshot cannot settle before it was observed")
        _goodnotes_id(self.run_id, "gnrun")
        if self.mtime_ns is not None and self.mtime_ns < 0:
            raise ValueError("mtime_ns is observation-only and not negative")


@dataclass(frozen=True, slots=True)
class GoodNotesLogicalPage:
    """Stable page identity across regenerations. Position is not a field."""

    logical_page_id: str
    principal_id: str
    notebook_id: str
    created_at: datetime
    last_seen_at: datetime
    identity_status: GoodNotesIdentityStatus

    def __post_init__(self) -> None:
        _goodnotes_id(self.logical_page_id, "gnlp")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.notebook_id, "gnnb")
        ensure_utc(self.created_at)
        ensure_utc(self.last_seen_at)
        if self.last_seen_at < self.created_at:
            raise ValueError("a logical page cannot be seen before it was created")


@dataclass(frozen=True, slots=True)
class GoodNotesMatchEvidence:
    match_method: GoodNotesMatchMethod
    confidence: float | None = None
    prior_page_version_id: str | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if self.prior_page_version_id is not None:
            _goodnotes_id(self.prior_page_version_id, "gnver")


@dataclass(frozen=True, slots=True)
class GoodNotesPagePosition:
    principal_id: str
    snapshot_id: str
    page_number: int
    logical_page_id: str
    created_at: datetime
    match_method: GoodNotesMatchMethod
    page_version_id: str | None = None
    match_confidence: float | None = None
    prior_page_version_id: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.snapshot_id, "gnsnap")
        if self.page_number < 1:
            raise ValueError("page numbers start at one")
        _goodnotes_id(self.logical_page_id, "gnlp")
        ensure_utc(self.created_at)
        if self.page_version_id is not None:
            _goodnotes_id(self.page_version_id, "gnver")
        if self.match_confidence is not None and not 0 <= self.match_confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if self.prior_page_version_id is not None:
            _goodnotes_id(self.prior_page_version_id, "gnver")


@dataclass(frozen=True, slots=True)
class GoodNotesRenderFingerprint:
    normalized_render_sha256: str
    perceptual_hash: str
    render_width: int
    render_height: int
    renderer_name: str
    renderer_version: str
    render_profile_version: str

    def __post_init__(self) -> None:
        _sha256(self.normalized_render_sha256, what="normalized render digest")
        _bounded_text(self.perceptual_hash, what="perceptual hash", maximum=128)
        if self.render_width < 1 or self.render_height < 1:
            raise ValueError("render dimensions must be positive")
        _bounded_text(self.renderer_name, what="renderer name", maximum=100)
        _bounded_text(self.renderer_version, what="renderer version", maximum=100)
        _bounded_text(self.render_profile_version, what="render profile version", maximum=100)


@dataclass(frozen=True, slots=True)
class PageRender:
    """Versioned page render. PDF rasterization is deferred; bytes may be hashed as-is."""

    exact_render_sha256: str
    normalized_render_sha256: str
    renderer_name: str
    renderer_version: str
    render_profile_version: str
    perceptual_hash: str | None = None
    perceptual_algorithm: str = "none-v0"
    perceptual_algorithm_version: str = "0"
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        _sha256(self.exact_render_sha256, what="exact render digest")
        _sha256(self.normalized_render_sha256, what="normalized render digest")
        _bounded_text(self.renderer_name, what="renderer name", maximum=100)
        _bounded_text(self.renderer_version, what="renderer version", maximum=100)
        _bounded_text(self.render_profile_version, what="render profile version", maximum=100)
        _bounded_text(self.perceptual_algorithm, what="perceptual algorithm", maximum=100)
        _bounded_text(
            self.perceptual_algorithm_version, what="perceptual algorithm version", maximum=100
        )
        if self.perceptual_hash is not None:
            _bounded_text(self.perceptual_hash, what="perceptual hash", maximum=128)
        if self.width is not None and self.width < 1:
            raise ValueError("render width must be positive")
        if self.height is not None and self.height < 1:
            raise ValueError("render height must be positive")


@dataclass(frozen=True, slots=True)
class GoodNotesPriorPageEvidence:
    """Last known render evidence for one logical page. Page number is position only."""

    logical_page_id: str
    last_page_number: int
    last_page_version_id: str | None = None
    exact_render_sha256: str | None = None
    normalized_render_sha256: str | None = None
    perceptual_hash: str | None = None
    render_width: int | None = None
    render_height: int | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.logical_page_id, "gnlp")
        if self.last_page_number < 1:
            raise ValueError("page numbers start at one")
        if self.last_page_version_id is not None:
            _goodnotes_id(self.last_page_version_id, "gnver")
        if self.exact_render_sha256 is not None:
            _sha256(self.exact_render_sha256, what="exact render digest")
        if self.normalized_render_sha256 is not None:
            _sha256(self.normalized_render_sha256, what="normalized render digest")
        if self.perceptual_hash is not None:
            _bounded_text(self.perceptual_hash, what="perceptual hash", maximum=128)
        if self.render_width is not None and self.render_width < 1:
            raise ValueError("render width must be positive")
        if self.render_height is not None and self.render_height < 1:
            raise ValueError("render height must be positive")


@dataclass(frozen=True, slots=True)
class GoodNotesLogicalPageMatch:
    page_number: int
    logical_page_id: str
    is_new: bool
    identity_status: GoodNotesIdentityStatus
    match_method: GoodNotesMatchMethod
    match_confidence: float | None = None
    prior_page_version_id: str | None = None

    def __post_init__(self) -> None:
        if self.page_number < 1:
            raise ValueError("page numbers start at one")
        _goodnotes_id(self.logical_page_id, "gnlp")
        if self.match_confidence is not None and not 0 <= self.match_confidence <= 1:
            raise ValueError("confidence must be between zero and one")
        if self.prior_page_version_id is not None:
            _goodnotes_id(self.prior_page_version_id, "gnver")


@dataclass(frozen=True, slots=True)
class GoodNotesIngestionRun:
    run_id: str
    principal_id: str
    source_root_id: str
    trigger_type: GoodNotesIngestionTrigger
    request_id: str
    idempotency_key: str
    request_fingerprint: str
    started_at: datetime
    status: GoodNotesIngestionStatus
    ended_at: datetime | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    snapshot_count: int = 0
    page_count: int = 0
    new_logical_page_count: int = 0
    changed_page_count: int = 0
    ambiguous_page_count: int = 0
    error_code: str | None = None
    error_class: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.run_id, "gnrun")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _root_alias(self.source_root_id)
        _bounded_text(self.request_id, what="request id", maximum=200)
        _bounded_text(self.idempotency_key, what="idempotency key", maximum=200)
        _sha256(self.request_fingerprint, what="request fingerprint")
        ensure_utc(self.started_at)
        if self.ended_at is not None:
            ensure_utc(self.ended_at)
            if self.ended_at < self.started_at:
                raise ValueError("a run cannot end before it started")
        if self.lease_owner is not None:
            _bounded_text(self.lease_owner, what="lease owner", maximum=200)
        if self.lease_expires_at is not None:
            ensure_utc(self.lease_expires_at)
        for name in (
            "snapshot_count",
            "page_count",
            "new_logical_page_count",
            "changed_page_count",
            "ambiguous_page_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name.replace('_', ' ')} is not negative")
        if self.error_code is not None:
            _bounded_text(self.error_code, what="error code", maximum=64)
        if self.error_class is not None:
            _bounded_text(self.error_class, what="error class", maximum=64)
