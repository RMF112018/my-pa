"""Deterministic ranking, dedup, diversity, packing, and contradiction flags.

Public contract is reason codes plus ordering. Nothing here publishes a float
relevance score. SEMANTIC_MATCH is never assigned in this work package.
PINNED_FOCUS and CONFIRMED_ALIAS are assigned only from explicit preferences.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from math import ceil
from typing import Final

from my_pa.domain.context.preference import (
    ContextPreferenceAction,
    ContextPreferenceCurrent,
)
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
    "apply_preferences",
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
#: PINNED_FOCUS ranks with CONFIRMED_ALIAS: above ordinary lexical, never
#: above EXPLICIT_SUBJECT, and never a substitute for authorization.
_REASON_PRIORITY: Final[dict[SelectionReasonCode, int]] = {
    SelectionReasonCode.EXPLICIT_SUBJECT: 0,
    SelectionReasonCode.EXACT_IDENTIFIER: 0,
    SelectionReasonCode.CONFIRMED_ALIAS: 1,
    SelectionReasonCode.PROJECT_LINK: 1,
    SelectionReasonCode.SITUATION_LINK: 1,
    SelectionReasonCode.RELATIONSHIP_LINK: 1,
    SelectionReasonCode.PINNED_FOCUS: 1,
    SelectionReasonCode.ACCEPTED_RECORD: 2,
    SelectionReasonCode.LEXICAL_STRONG: 3,
    SelectionReasonCode.LEXICAL_MODERATE: 4,
    SelectionReasonCode.RECENT_EVIDENCE: 5,
    SelectionReasonCode.SEMANTIC_MATCH: 6,
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


def _item_identities(item: PreparedContextEvidence) -> frozenset[str]:
    return frozenset(
        value
        for value in (
            item.reference_id,
            item.knowledge_id,
            item.source_id,
            item.source_object_id,
            item.source_version_id,
            item.capture_id,
            item.capture_version_id,
            item.product_id,
            item.managed_document_id,
            item.managed_document_version_id,
            item.reveal_subject_id,
        )
        if value is not None
    )


def _with_reasons(
    item: PreparedContextEvidence, *codes: SelectionReasonCode
) -> PreparedContextEvidence:
    seen: dict[SelectionReasonCode, None] = dict.fromkeys((*item.reason_codes, *codes))
    return replace(item, reason_codes=tuple(seen))


def _folded_query(query: str, conversation_context: str | None) -> str:
    parts = [query]
    if conversation_context:
        parts.append(conversation_context)
    return " ".join(parts).casefold()


def apply_preferences(
    items: tuple[PreparedContextEvidence, ...],
    preferences: tuple[ContextPreferenceCurrent, ...],
    *,
    query: str,
    conversation_context: str | None,
) -> tuple[tuple[PreparedContextEvidence, ...], tuple[str, ...], tuple[ContextLimitationCode, ...]]:
    """Apply the current projection. Never invents evidence or widens authorization."""
    if not preferences:
        return items, (), ()
    folded_query = _folded_query(query, conversation_context)
    dropped = False
    applied: list[str] = []
    adjusted: list[PreparedContextEvidence] = []
    for item in items:
        identities = _item_identities(item)
        codes: list[SelectionReasonCode] = []
        exclude = False
        for preference in preferences:
            matches_identity = preference.target_id in identities
            matches_source = (
                preference.source_id is not None and item.source_id == preference.source_id
            )
            if preference.action is ContextPreferenceAction.MARK_IRRELEVANT and matches_identity:
                exclude = True
                applied.append(preference.target_id)
                break
            if _boosts_focus(preference.action, matches_identity, matches_source):
                codes.append(SelectionReasonCode.PINNED_FOCUS)
                applied.append(preference.target_id)
            elif (
                preference.action is ContextPreferenceAction.CONFIRM_ALIAS
                and preference.alias is not None
                and preference.alias.casefold() in folded_query
                and matches_identity
            ):
                codes.extend(
                    (SelectionReasonCode.EXPLICIT_SUBJECT, SelectionReasonCode.CONFIRMED_ALIAS)
                )
                applied.append(preference.target_id)
        if exclude:
            dropped = True
            continue
        adjusted.append(_with_reasons(item, *codes) if codes else item)
    limitations: tuple[ContextLimitationCode, ...] = ()
    if dropped:
        limitations = (ContextLimitationCode.PREFERENCE_FILTERED,)
    seen_applied: dict[str, None] = dict.fromkeys(applied)
    return tuple(adjusted), tuple(seen_applied), limitations


def _boosts_focus(
    action: ContextPreferenceAction, matches_identity: bool, matches_source: bool
) -> bool:
    if action is ContextPreferenceAction.PIN and matches_identity:
        return True
    if action is ContextPreferenceAction.MARK_RELEVANT and matches_identity:
        return True
    return action is ContextPreferenceAction.PREFER_SOURCE and (matches_source or matches_identity)
