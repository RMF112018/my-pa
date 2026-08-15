"""Deterministic ranking, dedup, diversity, packing, and contradiction flags.

Public contract is reason codes plus ordering. Nothing here publishes a float
relevance score. PINNED_FOCUS and SEMANTIC_MATCH are never assigned in this
work package.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from typing import Final

from my_pa.domain.context.prepared import (
    ContextLimitationCode,
    ContextPlane,
    ContextTruncation,
    ContradictionCode,
    PreparedContextEvidence,
    SelectionReasonCode,
)

__all__ = [
    "PackedEvidence",
    "identity_key",
    "rank_and_pack",
]

_PLANE_ORDER: Final[dict[ContextPlane, int]] = {
    ContextPlane.KNOWLEDGE: 0,
    ContextPlane.CAPTURE: 1,
    ContextPlane.CONTINUITY: 2,
    ContextPlane.RELATIONSHIP: 3,
    ContextPlane.MANAGED_DOCUMENT: 4,
}

#: Lower is better. EXPLICIT_SUBJECT and EXACT_IDENTIFIER share first place.
_REASON_PRIORITY: Final[dict[SelectionReasonCode, int]] = {
    SelectionReasonCode.EXPLICIT_SUBJECT: 0,
    SelectionReasonCode.EXACT_IDENTIFIER: 0,
    SelectionReasonCode.CONFIRMED_ALIAS: 1,
    SelectionReasonCode.PROJECT_LINK: 1,
    SelectionReasonCode.SITUATION_LINK: 1,
    SelectionReasonCode.RELATIONSHIP_LINK: 1,
    SelectionReasonCode.ACCEPTED_RECORD: 2,
    SelectionReasonCode.LEXICAL_STRONG: 3,
    SelectionReasonCode.LEXICAL_MODERATE: 4,
    SelectionReasonCode.RECENT_EVIDENCE: 5,
    SelectionReasonCode.PINNED_FOCUS: 6,
    SelectionReasonCode.SEMANTIC_MATCH: 7,
}

_MISSING_FRESHNESS: Final = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class PackedEvidence:
    """Ranked, packed evidence plus the truncation and conflict disclosures."""

    items: tuple[PreparedContextEvidence, ...]
    truncation: ContextTruncation
    contradictions: tuple[ContradictionCode, ...]
    limitations: tuple[ContextLimitationCode, ...]


def identity_key(item: PreparedContextEvidence) -> str:
    """The version-or-product identity used for dedup."""
    return (
        item.source_version_id
        or item.capture_version_id
        or item.product_id
        or item.managed_document_version_id
        or item.reference_id
    )


def _excerpt_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _group_key(item: PreparedContextEvidence) -> str:
    """Parent identity a diversity cap applies to."""
    return (
        item.source_id
        or item.capture_id
        or item.product_id
        or item.managed_document_id
        or item.reference_id
    )


def _best_priority(item: PreparedContextEvidence) -> int:
    if not item.reason_codes:
        return max(_REASON_PRIORITY.values()) + 1
    return min(_REASON_PRIORITY[code] for code in item.reason_codes)


def _sort_key(item: PreparedContextEvidence) -> tuple[object, ...]:
    freshness = item.freshness
    missing = freshness is None
    stamp = _MISSING_FRESHNESS if freshness is None else freshness
    return (
        _best_priority(item),
        missing,
        -stamp.timestamp(),
        _PLANE_ORDER[item.plane],
        item.reference_id,
    )


def _diversity_cap(max_items: int) -> int:
    return max(2, ceil(max_items / 3))


def _detect_conflicts(items: tuple[PreparedContextEvidence, ...]) -> bool:
    """True when packed items disclose conflicting versions or content."""
    by_product: dict[str, set[str]] = {}
    by_source_object: dict[str, set[str]] = {}
    by_capture: dict[str, set[str]] = {}
    for item in items:
        if item.product_id is not None:
            by_product.setdefault(item.product_id, set()).add(_excerpt_fingerprint(item.text))
        if item.source_object_id is not None and item.source_version_id is not None:
            by_source_object.setdefault(item.source_object_id, set()).add(item.source_version_id)
        if item.capture_id is not None:
            by_capture.setdefault(item.capture_id, set()).add(_excerpt_fingerprint(item.text))
    return (
        any(len(values) > 1 for values in by_product.values())
        or any(len(values) > 1 for values in by_source_object.values())
        or any(len(values) > 1 for values in by_capture.values())
    )


def rank_and_pack(
    items: tuple[PreparedContextEvidence, ...],
    *,
    max_items: int,
    max_bytes: int,
) -> PackedEvidence:
    """Order, dedup, diversity-cap, and pack. Deterministic for the same inputs."""
    ranked = tuple(sorted(items, key=_sort_key))
    seen: set[tuple[ContextPlane, str, str]] = set()
    unique: list[PreparedContextEvidence] = []
    for item in ranked:
        key = (item.plane, identity_key(item), _excerpt_fingerprint(item.text))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    cap = _diversity_cap(max_items)
    packed: list[PreparedContextEvidence] = []
    group_counts: dict[str, int] = {}
    total_bytes = 0
    dropped_item = False
    dropped_byte = False
    dropped_diversity = False
    for item in unique:
        group = _group_key(item)
        if group_counts.get(group, 0) >= cap:
            dropped_diversity = True
            continue
        size = len(item.text.encode())
        if len(packed) >= max_items:
            dropped_item = True
            continue
        if total_bytes + size > max_bytes:
            dropped_byte = True
            continue
        packed.append(item)
        group_counts[group] = group_counts.get(group, 0) + 1
        total_bytes += size

    truncated = dropped_item or dropped_byte or dropped_diversity
    reason: str | None = None
    if truncated:
        if dropped_item:
            reason = "item_budget"
        elif dropped_byte:
            reason = "byte_budget"
        else:
            reason = "diversity_budget"

    packed_items = tuple(packed)
    contradictions: tuple[ContradictionCode, ...] = ()
    if _detect_conflicts(packed_items):
        contradictions = (ContradictionCode.CONFLICTING_EVIDENCE,)
    limitations: tuple[ContextLimitationCode, ...] = ()
    if truncated:
        limitations = (ContextLimitationCode.RESULT_TRUNCATED,)
    return PackedEvidence(
        items=packed_items,
        truncation=ContextTruncation(is_truncated=truncated, reason=reason),
        contradictions=contradictions,
        limitations=limitations,
    )
