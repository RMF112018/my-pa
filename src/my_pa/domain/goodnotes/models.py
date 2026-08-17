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

_ID_PREFIXES = frozenset(
    {
        "gnpg",
        "gnver",
        "gnreg",
        "gnrec",
        "gnnb",
        "gnsnap",
        "gnlp",
        "gnrun",
        "gnnt",
        "gnocc",
        "gnrev",
        "gnlink",
        "gnchg",
        "gnprp",
        "gndlv",
        "gnent",
    }
)
_ID = re.compile(
    r"\A(?:gnpg|gnver|gnreg|gnrec|gnnb|gnsnap|gnlp|gnrun|"
    r"gnnt|gnocc|gnrev|gnlink|gnchg|gnprp|gndlv|gnent)_[a-f0-9]{24}\Z"
)
_SHA256 = re.compile(r"\A[a-f0-9]{64}\Z")
_GEOMETRY_KEY = re.compile(
    r"\A[0-9]\.[0-9]{4},[0-9]\.[0-9]{4},[0-9]\.[0-9]{4},[0-9]\.[0-9]{4}"
    r":(?:none|[a-f0-9]{64})\Z"
)
_NOTE_TRANSCRIPTION_MAX = 20_000
_ANALYZER_TEXT_MAX = 100
_SCHEMA_VERSION_MAX = 40
_GEOMETRY_KEY_MAX = 96
_TARGET_KEY_MAX = 80
_CHANGE_REASON_MAX = 64
_DESTINATION_MAX = 64
_CANDIDATE_MAX = 200
_DELIVERY_BODY_MAX = 200_000
_DESTINATION = re.compile(r"\A[a-z][a-z0-9-]{0,62}\Z")
#: Fail-closed cap on persisted visual raster PNG bytes. Documented bound, ≤ 2 MiB.
MAX_GOODNOTES_RASTER_BYTES = 2 * 1_048_576
GOODNOTES_RASTER_MEDIA_TYPE = "image/png"


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


class GoodNotesPipelineStage(StrEnum):
    """Repository-side durable-note stages. Terminal success lives on the run."""

    OBSERVE = "OBSERVE"
    SETTLE = "SETTLE"
    SPLIT_RENDER = "SPLIT_RENDER"
    LINEAGE = "LINEAGE"
    CONTENT_READY = "CONTENT_READY"
    WAITING_PROPOSAL = "WAITING_PROPOSAL"
    RECONCILE = "RECONCILE"
    PREVIEW = "PREVIEW"


class GoodNotesStageStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


PIPELINE_STAGES: tuple[GoodNotesPipelineStage, ...] = tuple(GoodNotesPipelineStage)


class GoodNotesNoteClass(StrEnum):
    MEETING = "MEETING"
    PROJECT = "PROJECT"
    RELATIONSHIP = "RELATIONSHIP"
    GENERAL = "GENERAL"


class GoodNotesNoteLinkKind(StrEnum):
    NOTE_TO_NOTE = "NOTE_TO_NOTE"
    NOTE_TO_LOGICAL_PAGE = "NOTE_TO_LOGICAL_PAGE"
    NOTE_TO_SOURCE_CONTEXT = "NOTE_TO_SOURCE_CONTEXT"
    OCCURRENCE_TO_OCCURRENCE = "OCCURRENCE_TO_OCCURRENCE"


class GoodNotesNoteChangeState(StrEnum):
    NEW = "NEW"
    UNCHANGED = "UNCHANGED"
    REVISED = "REVISED"
    REMOVED_OR_NO_LONGER_PRESENT = "REMOVED_OR_NO_LONGER_PRESENT"
    AMBIGUOUS = "AMBIGUOUS"


class GoodNotesEntityResolution(StrEnum):
    ASSOCIATED = "ASSOCIATED"
    UNRESOLVED = "UNRESOLVED"


class GoodNotesEntityKind(StrEnum):
    PROJECT = "PROJECT"
    PERSON = "PERSON"
    NOTE = "NOTE"


def occurrence_geometry_key(
    x_min: float,
    y_min: float,
    width: float,
    height: float,
    crop_sha256: str | None,
) -> str:
    """Canonical occurrence identity. Floats are not the unique key."""
    crop = "none" if crop_sha256 is None else crop_sha256
    return f"{x_min:.4f},{y_min:.4f},{width:.4f},{height:.4f}:{crop}"


def note_link_target_key(
    *,
    link_kind: GoodNotesNoteLinkKind,
    target_note_id: str | None,
    target_logical_page_id: str | None,
    target_occurrence_id: str | None,
    target_context_anchor_sha256: str | None,
) -> str:
    if link_kind is GoodNotesNoteLinkKind.NOTE_TO_NOTE and target_note_id is not None:
        return f"note:{target_note_id}"
    if (
        link_kind is GoodNotesNoteLinkKind.NOTE_TO_LOGICAL_PAGE
        and target_logical_page_id is not None
    ):
        return f"page:{target_logical_page_id}"
    if (
        link_kind is GoodNotesNoteLinkKind.OCCURRENCE_TO_OCCURRENCE
        and target_occurrence_id is not None
    ):
        return f"occ:{target_occurrence_id}"
    if (
        link_kind is GoodNotesNoteLinkKind.NOTE_TO_SOURCE_CONTEXT
        and target_context_anchor_sha256 is not None
    ):
        return f"ctx:{target_context_anchor_sha256}"
    raise ValueError("a note link target must match its kind")


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
    exact_render_sha256: str | None = None
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
    """Versioned page render. Production identity is the pinned visual raster, not raw bytes."""

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


def _unit_interval(value: float, *, what: str, positive: bool = False) -> None:
    if positive:
        if not 0 < value <= 1:
            raise ValueError(f"{what} must be in (0, 1]")
        return
    if not 0 <= value <= 1:
        raise ValueError(f"{what} must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class GoodNotesNote:
    """Durable NOTE_UNIT identity. A PDF is not a note; a page is not a note."""

    note_id: str
    principal_id: str
    notebook_id: str
    identity_status: GoodNotesIdentityStatus
    created_at: datetime
    last_seen_at: datetime
    primary_class: GoodNotesNoteClass | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.note_id, "gnnt")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.notebook_id, "gnnb")
        ensure_utc(self.created_at)
        ensure_utc(self.last_seen_at)
        if self.last_seen_at < self.created_at:
            raise ValueError("a note cannot be seen before it was created")


@dataclass(frozen=True, slots=True)
class GoodNotesNoteOccurrence:
    """One physical appearance. Transcription is not part of occurrence identity."""

    occurrence_id: str
    principal_id: str
    note_id: str
    logical_page_id: str
    x_min: float
    y_min: float
    width: float
    height: float
    identity_status: GoodNotesIdentityStatus
    created_at: datetime
    last_seen_at: datetime
    page_version_id: str | None = None
    snapshot_id: str | None = None
    run_id: str | None = None
    crop_sha256: str | None = None
    context_anchor_sha256: str | None = None
    geometry_key: str = field(init=False)

    def __post_init__(self) -> None:
        _goodnotes_id(self.occurrence_id, "gnocc")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.note_id, "gnnt")
        _goodnotes_id(self.logical_page_id, "gnlp")
        _unit_interval(self.x_min, what="x_min")
        _unit_interval(self.y_min, what="y_min")
        _unit_interval(self.width, what="width", positive=True)
        _unit_interval(self.height, what="height", positive=True)
        if self.x_min + self.width > 1 or self.y_min + self.height > 1:
            raise ValueError("occurrence coordinates are normalized to the page")
        ensure_utc(self.created_at)
        ensure_utc(self.last_seen_at)
        if self.last_seen_at < self.created_at:
            raise ValueError("an occurrence cannot be seen before it was created")
        if self.page_version_id is not None:
            _goodnotes_id(self.page_version_id, "gnver")
        if self.snapshot_id is not None:
            _goodnotes_id(self.snapshot_id, "gnsnap")
        if self.run_id is not None:
            _goodnotes_id(self.run_id, "gnrun")
        if self.crop_sha256 is not None:
            _sha256(self.crop_sha256, what="crop digest")
        if self.context_anchor_sha256 is not None:
            _sha256(self.context_anchor_sha256, what="context anchor digest")
        key = occurrence_geometry_key(
            self.x_min, self.y_min, self.width, self.height, self.crop_sha256
        )
        if not _GEOMETRY_KEY.fullmatch(key) or len(key) > _GEOMETRY_KEY_MAX:
            raise ValueError("geometry_key must be the canonical 4-decimal box")
        object.__setattr__(self, "geometry_key", key)


@dataclass(frozen=True, slots=True)
class GoodNotesNoteRevision:
    """Append-only semantic interpretation. Corrections supersede; they do not erase."""

    revision_id: str
    principal_id: str
    note_id: str
    schema_version: str
    analyzer_name: str
    analyzer_version: str
    transcription: str = field(repr=False)
    created_at: datetime
    occurrence_id: str | None = None
    supersedes_revision_id: str | None = None
    primary_class: GoodNotesNoteClass | None = None
    page_version_id: str | None = None
    snapshot_id: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.revision_id, "gnrev")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.note_id, "gnnt")
        _bounded_text(self.schema_version, what="schema version", maximum=_SCHEMA_VERSION_MAX)
        _bounded_text(self.analyzer_name, what="analyzer name", maximum=_ANALYZER_TEXT_MAX)
        _bounded_text(self.analyzer_version, what="analyzer version", maximum=_ANALYZER_TEXT_MAX)
        _bounded_text(self.transcription, what="transcription", maximum=_NOTE_TRANSCRIPTION_MAX)
        ensure_utc(self.created_at)
        if self.occurrence_id is not None:
            _goodnotes_id(self.occurrence_id, "gnocc")
        if self.supersedes_revision_id is not None:
            _goodnotes_id(self.supersedes_revision_id, "gnrev")
            if self.supersedes_revision_id == self.revision_id:
                raise ValueError("a revision cannot supersede itself")
        if self.page_version_id is not None:
            _goodnotes_id(self.page_version_id, "gnver")
        if self.snapshot_id is not None:
            _goodnotes_id(self.snapshot_id, "gnsnap")


@dataclass(frozen=True, slots=True)
class GoodNotesNoteLink:
    """Structural link only. Entity resolution is a later slice."""

    link_id: str
    principal_id: str
    note_id: str
    link_kind: GoodNotesNoteLinkKind
    created_at: datetime
    target_note_id: str | None = None
    target_logical_page_id: str | None = None
    target_occurrence_id: str | None = None
    target_context_anchor_sha256: str | None = None
    target_key: str = field(init=False)

    def __post_init__(self) -> None:
        _goodnotes_id(self.link_id, "gnlink")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.note_id, "gnnt")
        ensure_utc(self.created_at)
        if self.target_note_id is not None:
            _goodnotes_id(self.target_note_id, "gnnt")
        if self.target_logical_page_id is not None:
            _goodnotes_id(self.target_logical_page_id, "gnlp")
        if self.target_occurrence_id is not None:
            _goodnotes_id(self.target_occurrence_id, "gnocc")
        if self.target_context_anchor_sha256 is not None:
            _sha256(self.target_context_anchor_sha256, what="context anchor digest")
        expected = {
            GoodNotesNoteLinkKind.NOTE_TO_NOTE: (
                self.target_note_id is not None,
                self.target_logical_page_id is None,
                self.target_occurrence_id is None,
                self.target_context_anchor_sha256 is None,
            ),
            GoodNotesNoteLinkKind.NOTE_TO_LOGICAL_PAGE: (
                self.target_note_id is None,
                self.target_logical_page_id is not None,
                self.target_occurrence_id is None,
                self.target_context_anchor_sha256 is None,
            ),
            GoodNotesNoteLinkKind.NOTE_TO_SOURCE_CONTEXT: (
                self.target_note_id is None,
                self.target_logical_page_id is None,
                self.target_occurrence_id is None,
                self.target_context_anchor_sha256 is not None,
            ),
            GoodNotesNoteLinkKind.OCCURRENCE_TO_OCCURRENCE: (
                self.target_note_id is None,
                self.target_logical_page_id is None,
                self.target_occurrence_id is not None,
                self.target_context_anchor_sha256 is None,
            ),
        }[self.link_kind]
        if expected != (True, True, True, True):
            raise ValueError("a note link target must match its kind")
        key = note_link_target_key(
            link_kind=self.link_kind,
            target_note_id=self.target_note_id,
            target_logical_page_id=self.target_logical_page_id,
            target_occurrence_id=self.target_occurrence_id,
            target_context_anchor_sha256=self.target_context_anchor_sha256,
        )
        if len(key) > _TARGET_KEY_MAX:
            raise ValueError("target_key must be a bounded canonical string")
        object.__setattr__(self, "target_key", key)


@dataclass(frozen=True, slots=True)
class GoodNotesRunNoteChange:
    """Exact per-run change ledger. The caller supplies the state; this does not decide it."""

    change_id: str
    principal_id: str
    run_id: str
    note_id: str | None
    occurrence_id: str | None
    change_state: GoodNotesNoteChangeState
    created_at: datetime
    page_version_id: str | None = None
    geometry_key: str | None = None
    reason: str | None = None
    revision_id: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.change_id, "gnchg")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.run_id, "gnrun")
        ensure_utc(self.created_at)
        note_id = self.note_id
        occurrence_id = self.occurrence_id
        identified = note_id is not None and occurrence_id is not None
        anonymous = note_id is None and occurrence_id is None
        if identified == anonymous:
            raise ValueError("a run note change names both identities or neither")
        if note_id is not None and occurrence_id is not None:
            _goodnotes_id(note_id, "gnnt")
            _goodnotes_id(occurrence_id, "gnocc")
        elif self.change_state is not GoodNotesNoteChangeState.AMBIGUOUS:
            raise ValueError("only an AMBIGUOUS run note change may omit occurrence identity")
        elif self.page_version_id is None or self.geometry_key is None:
            raise ValueError("a current-only AMBIGUOUS change requires page version and geometry")
        if self.page_version_id is not None:
            _goodnotes_id(self.page_version_id, "gnver")
        if self.geometry_key is not None and (
            not _GEOMETRY_KEY.fullmatch(self.geometry_key)
            or len(self.geometry_key) > _GEOMETRY_KEY_MAX
        ):
            raise ValueError("geometry_key must be the canonical 4-decimal box")
        if self.reason is not None:
            _bounded_text(self.reason, what="change reason", maximum=_CHANGE_REASON_MAX)
        if self.revision_id is not None:
            _goodnotes_id(self.revision_id, "gnrev")
        if self.revision_id is not None and anonymous:
            raise ValueError("a current-only AMBIGUOUS change cannot name a revision")


class GoodNotesSegmentKind(StrEnum):
    NOTE_UNIT = "NOTE_UNIT"
    SOURCE_CONTEXT = "SOURCE_CONTEXT"


@dataclass(frozen=True, slots=True)
class GoodNotesPageWork:
    """Immutable page-version work a semantic analyzer may inspect.

    The digest is the handle. Page bytes and live transcription are not here.
    """

    run_id: str
    page_version_id: str
    principal_id: str
    content_sha256: str
    logical_page_id: str | None = None
    renderer_name: str | None = None
    renderer_version: str | None = None
    render_profile_version: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.run_id, "gnrun")
        _goodnotes_id(self.page_version_id, "gnver")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _sha256(self.content_sha256, what="content digest")
        if self.logical_page_id is not None:
            _goodnotes_id(self.logical_page_id, "gnlp")
        for name in ("renderer_name", "renderer_version", "render_profile_version"):
            value = getattr(self, name)
            if value is not None:
                _bounded_text(value, what=name.replace("_", " "), maximum=100)


@dataclass(frozen=True, slots=True)
class GoodNotesSemanticProposal:
    """A Principal-bound semantic proposal receipt. Not reconciled truth."""

    proposal_id: str
    principal_id: str
    run_id: str
    page_version_id: str
    content_sha256: str
    schema_version: str
    analyzer_name: str
    analyzer_version: str
    idempotency_key: str
    request_fingerprint: str
    payload_sha256: str
    created_at: datetime
    replayed: bool = False

    def __post_init__(self) -> None:
        _goodnotes_id(self.proposal_id, "gnprp")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.run_id, "gnrun")
        _goodnotes_id(self.page_version_id, "gnver")
        _sha256(self.content_sha256, what="content digest")
        _bounded_text(self.schema_version, what="schema version", maximum=_SCHEMA_VERSION_MAX)
        _bounded_text(self.analyzer_name, what="analyzer name", maximum=_ANALYZER_TEXT_MAX)
        _bounded_text(self.analyzer_version, what="analyzer version", maximum=_ANALYZER_TEXT_MAX)
        _bounded_text(self.idempotency_key, what="idempotency key", maximum=128)
        _sha256(self.request_fingerprint, what="request fingerprint")
        _sha256(self.payload_sha256, what="payload digest")
        ensure_utc(self.created_at)


def _destination(value: str) -> None:
    if not _DESTINATION.fullmatch(value) or len(value) > _DESTINATION_MAX:
        raise ValueError("destination must be a bounded explicit token")


@dataclass(frozen=True, slots=True)
class GoodNotesEntityDirectoryRecord:
    """Existing Principal-partitioned Project, person, or note a candidate may match."""

    entity_id: str
    kind: GoodNotesEntityKind
    normalized_name: str | None = None


@dataclass(frozen=True, slots=True)
class GoodNotesEntityAssociation:
    """Principal-bound candidate association or unresolved literal. Not a note link."""

    association_id: str
    principal_id: str
    run_id: str
    note_id: str
    candidate: str
    rank: int
    resolution: GoodNotesEntityResolution
    created_at: datetime
    entity_kind: GoodNotesEntityKind | None = None
    resolved_id: str | None = None

    def __post_init__(self) -> None:
        _goodnotes_id(self.association_id, "gnent")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.run_id, "gnrun")
        _goodnotes_id(self.note_id, "gnnt")
        _bounded_text(self.candidate, what="candidate", maximum=_CANDIDATE_MAX)
        if type(self.rank) is not int or self.rank < 1:
            raise ValueError("rank must be a positive integer")
        ensure_utc(self.created_at)
        associated = self.resolution is GoodNotesEntityResolution.ASSOCIATED
        if associated != (self.entity_kind is not None) or associated != (
            self.resolved_id is not None
        ):
            raise ValueError(
                "an association must carry a resolved identity exactly when associated"
            )
        if self.resolved_id is not None:
            _bounded_text(self.resolved_id, what="resolved identity", maximum=72)


@dataclass(frozen=True, slots=True)
class GoodNotesDeliveryReceipt:
    """Immutable NEW-only delivery receipt. Replay is the same row, not a send."""

    receipt_id: str
    principal_id: str
    run_id: str
    destination: str
    summary_hash: str
    suppressed: bool
    created_at: datetime
    body: str | None = field(default=None, repr=False)
    replayed: bool = False

    def __post_init__(self) -> None:
        _goodnotes_id(self.receipt_id, "gndlv")
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.run_id, "gnrun")
        _destination(self.destination)
        _sha256(self.summary_hash, what="summary digest")
        ensure_utc(self.created_at)
        if self.suppressed:
            if self.body is not None:
                raise ValueError("a suppressed delivery has no user-facing body")
            return
        if self.body is None:
            raise ValueError("an unsuppressed delivery requires a user-facing body")
        _bounded_text(self.body, what="delivery body", maximum=_DELIVERY_BODY_MAX)


@dataclass(frozen=True, slots=True)
class GoodNotesRunStage:
    """One additive stage row on an existing ingestion-run identity."""

    principal_id: str
    run_id: str
    stage: GoodNotesPipelineStage
    status: GoodNotesStageStatus
    started_at: datetime
    attempt: int = 1
    ended_at: datetime | None = None
    error_code: str | None = None
    error_class: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.run_id, "gnrun")
        ensure_utc(self.started_at)
        if self.attempt < 1:
            raise ValueError("stage attempts start at one")
        if self.ended_at is not None:
            ensure_utc(self.ended_at)
            if self.ended_at < self.started_at:
                raise ValueError("a stage cannot end before it started")
        if self.error_code is not None:
            _bounded_text(self.error_code, what="error code", maximum=64)
        if self.error_class is not None:
            _bounded_text(self.error_class, what="error class", maximum=64)


@dataclass(frozen=True, slots=True)
class GoodNotesPageRaster:
    """Principal-bound pinned visual raster used for page identity.

    Bytes are the PNG encoding of the grayscale raster whose digest is
    `exact_render_sha256`. Paths are not stored. Size is fail-closed at
    `MAX_GOODNOTES_RASTER_BYTES`.
    """

    principal_id: str
    page_version_id: str
    run_id: str
    exact_render_sha256: str
    png_sha256: str
    byte_length: int
    png_bytes: bytes = field(repr=False)
    renderer_name: str
    renderer_version: str
    render_profile_version: str
    created_at: datetime
    media_type: str = GOODNOTES_RASTER_MEDIA_TYPE

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        _goodnotes_id(self.page_version_id, "gnver")
        _goodnotes_id(self.run_id, "gnrun")
        _sha256(self.exact_render_sha256, what="exact render digest")
        _sha256(self.png_sha256, what="png digest")
        if self.media_type != GOODNOTES_RASTER_MEDIA_TYPE:
            raise ValueError("GoodNotes content is a PNG raster")
        if not 1 <= self.byte_length <= MAX_GOODNOTES_RASTER_BYTES:
            raise ValueError("GoodNotes visual raster exceeds the admitted size cap")
        if len(self.png_bytes) != self.byte_length:
            raise ValueError("GoodNotes visual raster length does not match the stored bytes")
        if hashlib.sha256(self.png_bytes).hexdigest() != self.png_sha256:
            raise ValueError("GoodNotes visual raster digest does not match the stored bytes")
        _bounded_text(self.renderer_name, what="renderer name", maximum=100)
        _bounded_text(self.renderer_version, what="renderer version", maximum=100)
        _bounded_text(self.render_profile_version, what="render profile version", maximum=100)
        ensure_utc(self.created_at)
