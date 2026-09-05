"""Bounded GoodNotes date evidence and canonical serialization."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

_MAX_DATE_LITERAL_LENGTH = 200
_MAX_DATE_EVIDENCE_REF_LENGTH = 200
_MAX_DATE_EVIDENCE_REFS = 32


class GoodNotesDateScope(StrEnum):
    """Meaning of a proposed date; page identity is never an event date."""

    PAGE = "PAGE"
    EVENT = "EVENT"
    BODY = "BODY"


class GoodNotesPageDateStatus(StrEnum):
    """Explicit outcome for the singular notebook-page date."""

    ABSENT = "ABSENT"
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class GoodNotesDateEvidence:
    """One client-proposed ISO date with its unmodified evidence metadata."""

    scope: GoodNotesDateScope
    value: date
    literal: str
    evidence_refs: tuple[str, ...]
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.scope, GoodNotesDateScope):
            raise TypeError("date scope must be a GoodNotesDateScope")
        if isinstance(self.value, datetime) or not isinstance(self.value, date):
            raise TypeError("date value must be a date without a time")
        _bounded_date_text(self.literal, what="date literal", maximum=_MAX_DATE_LITERAL_LENGTH)
        if not self.evidence_refs or len(self.evidence_refs) > _MAX_DATE_EVIDENCE_REFS:
            raise ValueError("date evidence references are outside their bound")
        if len(set(self.evidence_refs)) != len(self.evidence_refs):
            raise ValueError("date evidence references must be unique")
        for evidence_ref in self.evidence_refs:
            _bounded_date_text(
                evidence_ref,
                what="date evidence reference",
                maximum=_MAX_DATE_EVIDENCE_REF_LENGTH,
            )
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, int | float):
                raise TypeError("date confidence must be numeric")
            if not math.isfinite(float(self.confidence)) or not 0 <= self.confidence <= 1:
                raise ValueError("date confidence must be between zero and one")


def admit_date_evidence(
    *,
    scope: GoodNotesDateScope,
    value: str,
    literal: str,
    evidence_refs: tuple[str, ...],
    confidence: float | None = None,
) -> GoodNotesDateEvidence:
    """Validate a client-proposed date without parsing prose or calling a model."""

    if not isinstance(value, str):
        raise TypeError("date value must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("date value must be a valid ISO calendar date") from None
    if parsed.isoformat() != value:
        raise ValueError("date value must use canonical ISO format")
    return GoodNotesDateEvidence(
        scope=scope,
        value=parsed,
        literal=literal,
        evidence_refs=evidence_refs,
        confidence=confidence,
    )


@dataclass(frozen=True, slots=True)
class GoodNotesDateSemantics:
    """Page date and zero-or-more event/body dates kept on separate planes."""

    page_candidates: tuple[GoodNotesDateEvidence, ...] = ()
    event_dates: tuple[GoodNotesDateEvidence, ...] = ()
    body_dates: tuple[GoodNotesDateEvidence, ...] = ()

    def __post_init__(self) -> None:
        _require_date_scope(self.page_candidates, GoodNotesDateScope.PAGE)
        _require_date_scope(self.event_dates, GoodNotesDateScope.EVENT)
        _require_date_scope(self.body_dates, GoodNotesDateScope.BODY)

    @property
    def page_date_status(self) -> GoodNotesPageDateStatus:
        distinct = {candidate.value for candidate in self.page_candidates}
        if not distinct:
            return GoodNotesPageDateStatus.ABSENT
        if len(distinct) == 1:
            return GoodNotesPageDateStatus.RESOLVED
        return GoodNotesPageDateStatus.AMBIGUOUS

    @property
    def page_date(self) -> date | None:
        """Return the page date only when the submitted evidence is unambiguous."""

        if self.page_date_status is not GoodNotesPageDateStatus.RESOLVED:
            return None
        return self.page_candidates[0].value


def _require_date_scope(values: object, expected: GoodNotesDateScope) -> None:
    if not isinstance(values, tuple) or any(
        not isinstance(value, GoodNotesDateEvidence) or value.scope is not expected
        for value in values
    ):
        raise ValueError(f"{expected.value.casefold()} dates contain a wrong-scope value")


def _bounded_date_text(value: object, *, what: str, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"invalid {what}")


def canonical_date_evidence(value: object) -> dict[str, object]:
    """Validate and serialize the optional JSON date plane; empty means absent."""
    scopes = {
        "page_candidates": GoodNotesDateScope.PAGE,
        "event_dates": GoodNotesDateScope.EVENT,
        "body_dates": GoodNotesDateScope.BODY,
    }
    if not isinstance(value, dict) or value.keys() - scopes.keys():
        raise ValueError("invalid date evidence object")
    result: dict[str, object] = {}
    required = {"scope", "value", "literal", "evidence_refs"}
    for name, scope in scopes.items():
        items = value.get(name, [])
        if not isinstance(items, list) or len(items) > 32:
            raise ValueError("invalid date evidence collection")
        serialized: list[dict[str, object]] = []
        seen: set[str] = set()
        for item in items:
            if (
                not isinstance(item, dict)
                or not required <= item.keys()
                or item.keys() - (required | {"confidence"})
                or item["scope"] != scope.value
            ):
                raise ValueError("invalid date evidence item")
            refs = item["evidence_refs"]
            if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs):
                raise ValueError("invalid date evidence references")
            confidence = item.get("confidence")
            if "confidence" in item and (
                isinstance(confidence, bool) or not isinstance(confidence, int | float)
            ):
                raise ValueError("invalid date evidence confidence")
            evidence = admit_date_evidence(
                scope=scope,
                value=item["value"],
                literal=item["literal"],
                evidence_refs=tuple(refs),
                confidence=confidence,
            )
            entry: dict[str, object] = {
                "scope": scope.value,
                "value": evidence.value.isoformat(),
                "literal": evidence.literal,
                "evidence_refs": list(evidence.evidence_refs),
            }
            if confidence is not None:
                entry["confidence"] = float(confidence)
            identity = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            if identity in seen:
                raise ValueError("duplicate date evidence item")
            seen.add(identity)
            serialized.append(entry)
        if serialized:
            result[name] = serialized
    return result
