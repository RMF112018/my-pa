"""Shared note-unit.v2 admission for production propose and side-effect-free GSQS.

This module is the semantic contract for `note-unit.v2` segments. Production
`goodnotes.propose` and the B0 interchange parser must reject the same material
malformations. It does not persist proposals or invoke the worker.
"""

from __future__ import annotations

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.domain.goodnotes.models import (
    NOTE_UNIT_SCHEMA_V1,
    NOTE_UNIT_SCHEMA_V2,
    GoodNotesNoteClass,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
)

SHA256_HEX = frozenset("0123456789abcdef")
MAX_GOODNOTES_SEGMENTS = 50
MAX_GOODNOTES_TAGS = 32
MAX_GOODNOTES_CANDIDATES = 32
MAX_GOODNOTES_TRANSCRIPTION = 20_000
MAX_GOODNOTES_TAG = 80
MAX_GOODNOTES_CANDIDATE = 200
MAX_GOODNOTES_ANALYZER = 100
MAX_GOODNOTES_SCHEMA = 40
MAX_GOODNOTES_UNCERTAINTY = 500
FORBIDDEN_SEGMENT_KEYS = frozenset(
    {
        "change_state",
        "changestate",
        "disposition",
        "note_id",
        "occurrence_id",
        "principal_id",
        "canonical_state",
        "state",
    }
)
V1_SEGMENT_KEYS = frozenset(
    {
        "kind",
        "geometry",
        "crop_sha256",
        "transcription",
        "primary_class",
    }
)
V2_NOTE_UNIT_KEYS = V1_SEGMENT_KEYS | {
    "ranked_candidates",
    "candidate_tags",
    "confidence",
    "transcription_status",
}
NOTE_UNIT_SCHEMAS = frozenset({NOTE_UNIT_SCHEMA_V1, NOTE_UNIT_SCHEMA_V2})
SEGMENT_KEY_ORDER = (
    "kind",
    "geometry",
    "crop_sha256",
    "transcription",
    "primary_class",
    "candidate_tags",
    "ranked_candidates",
    "confidence",
    "transcription_status",
)
CONFIDENCE_KEYS = frozenset(
    {
        "transcription",
        "segmentation",
        "classification",
        "linking",
        "uncertainty",
    }
)
RANKED_CANDIDATE_KEYS = frozenset({"rank", "candidate"})


def sha256_digest(value: object, detail: SafeDetail) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in SHA256_HEX for ch in value):
        raise InvalidRequestError(detail)
    return value


def geometry(box: object) -> None:
    if not isinstance(box, dict):
        raise InvalidRequestError(SafeDetail.GEOMETRY)
    required = ("x_min", "y_min", "width", "height")
    if set(box) != set(required):
        raise InvalidRequestError(SafeDetail.GEOMETRY)
    values: list[float] = []
    for name in required:
        raw = box[name]
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise InvalidRequestError(SafeDetail.GEOMETRY)
        values.append(float(raw))
    x_min, y_min, width, height = values
    if min(x_min, y_min) < 0 or width <= 0 or height <= 0:
        raise InvalidRequestError(SafeDetail.GEOMETRY)
    if x_min + width > 1 or y_min + height > 1 or x_min > 1 or y_min > 1:
        raise InvalidRequestError(SafeDetail.GEOMETRY)


def candidate_tags(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise InvalidRequestError(SafeDetail.CANDIDATE_TAGS)
    if len(value) > MAX_GOODNOTES_TAGS:
        raise InvalidRequestError(SafeDetail.CANDIDATE_TAGS)
    tags: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= MAX_GOODNOTES_TAG or "\x00" in item:
            raise InvalidRequestError(SafeDetail.CANDIDATE_TAGS)
        if item in seen:
            raise InvalidRequestError(SafeDetail.CANDIDATE_TAGS)
        seen.add(item)
        tags.append(item)
    return tuple(tags)


def ranked_candidates(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, tuple):
        raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
    if len(value) > MAX_GOODNOTES_CANDIDATES:
        raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
    ranks: set[int] = set()
    cleaned: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
        if set(item) != RANKED_CANDIDATE_KEYS:
            raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
        rank = item.get("rank")
        candidate = item.get("candidate")
        if type(rank) is not int or rank < 1 or rank in ranks:
            raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
        if (
            not isinstance(candidate, str)
            or not 1 <= len(candidate) <= MAX_GOODNOTES_CANDIDATE
            or "\x00" in candidate
        ):
            raise InvalidRequestError(SafeDetail.RANKED_CANDIDATES)
        ranks.add(rank)
        cleaned.append({"rank": rank, "candidate": candidate})
    return tuple(cleaned)


def confidence(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InvalidRequestError(SafeDetail.CONFIDENCE)
    if set(value) - CONFIDENCE_KEYS:
        raise InvalidRequestError(SafeDetail.CONFIDENCE)
    for name in ("transcription", "segmentation", "classification", "linking"):
        raw = value.get(name)
        if raw is None:
            continue
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise InvalidRequestError(SafeDetail.CONFIDENCE)
        if not 0 <= float(raw) <= 1:
            raise InvalidRequestError(SafeDetail.CONFIDENCE)
    note = value.get("uncertainty")
    if note is not None and (
        not isinstance(note, str) or len(note) > MAX_GOODNOTES_UNCERTAINTY or "\x00" in note
    ):
        raise InvalidRequestError(SafeDetail.CONFIDENCE)
    return value


def segments(value: object, *, schema_version: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, tuple) or not 1 <= len(value) <= MAX_GOODNOTES_SEGMENTS:
        raise InvalidRequestError(SafeDetail.SEGMENTS)
    cleaned: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidRequestError(SafeDetail.SEGMENTS)
        keys = {str(key).casefold() for key in item}
        if keys & FORBIDDEN_SEGMENT_KEYS:
            raise InvalidRequestError(SafeDetail.SEGMENTS)
        kind = item.get("kind")
        if not isinstance(kind, str):
            raise InvalidRequestError(SafeDetail.SEGMENTS)
        try:
            parsed_kind = GoodNotesSegmentKind(kind)
        except ValueError:
            raise InvalidRequestError(SafeDetail.SEGMENTS) from None
        allowed = V1_SEGMENT_KEYS
        if schema_version == NOTE_UNIT_SCHEMA_V2 and parsed_kind is GoodNotesSegmentKind.NOTE_UNIT:
            allowed = V2_NOTE_UNIT_KEYS
        if set(item) - allowed:
            raise InvalidRequestError(SafeDetail.SEGMENTS)
        geometry(item.get("geometry"))
        crop = item.get("crop_sha256")
        if crop is not None:
            sha256_digest(crop, SafeDetail.SEGMENTS)
        transcription = item.get("transcription")
        if transcription is not None and (
            not isinstance(transcription, str)
            or len(transcription) > MAX_GOODNOTES_TRANSCRIPTION
            or "\x00" in transcription
        ):
            raise InvalidRequestError(SafeDetail.TRANSCRIPTION)
        primary = item.get("primary_class")
        if primary is not None:
            if not isinstance(primary, str):
                raise InvalidRequestError(SafeDetail.SEGMENTS)
            try:
                GoodNotesNoteClass(primary)
            except ValueError:
                raise InvalidRequestError(SafeDetail.SEGMENTS) from None
        admitted = dict(item)
        if "candidate_tags" in admitted:
            tags = admitted["candidate_tags"]
            if isinstance(tags, list):
                tags = tuple(tags)
            admitted["candidate_tags"] = candidate_tags(tags)
        if "ranked_candidates" in admitted:
            ranked = admitted["ranked_candidates"]
            if isinstance(ranked, list):
                ranked = tuple(ranked)
            admitted["ranked_candidates"] = ranked_candidates(ranked)
        if "confidence" in admitted:
            admitted["confidence"] = confidence(admitted["confidence"])
        status = admitted.get("transcription_status")
        if status is not None:
            if not isinstance(status, str):
                raise InvalidRequestError(SafeDetail.SEGMENTS)
            try:
                parsed_status = GoodNotesTranscriptionStatus(status)
            except ValueError:
                raise InvalidRequestError(SafeDetail.SEGMENTS) from None
            if parsed_status is GoodNotesTranscriptionStatus.CLEAR and (
                not isinstance(transcription, str) or not transcription
            ):
                raise InvalidRequestError(SafeDetail.TRANSCRIPTION)
        cleaned.append(admitted)
    return tuple(cleaned)


def admit_v2_segment_list(value: object) -> tuple[dict[str, object], ...]:
    """Fail-closed B0 admission. Does not call production propose."""
    if isinstance(value, list):
        value = tuple(value)
    try:
        return segments(value, schema_version=NOTE_UNIT_SCHEMA_V2)
    except InvalidRequestError as exc:
        detail = exc.safe_details[0].value if exc.safe_details else "proposal"
        raise ValueError(f"malformed {detail}") from exc


def admit_content_sha256(value: object) -> str:
    try:
        return sha256_digest(value, SafeDetail.CONTENT_SHA256)
    except InvalidRequestError as exc:
        raise ValueError("malformed content_sha256") from exc
