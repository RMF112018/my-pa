"""Validators for every caller-supplied field of a general report version.

Each validator takes an untyped value (domain inputs arrive from a transport
with no runtime type enforcement), returns the normalized value it accepted,
and otherwise raises `ReportValidationError` naming the field and the rule --
never the value.

**Normalization is deliberately minimal.** Title, summary, topics and tags are
NFC-normalized and then measured in code points; nothing is trimmed, case
folded or rewritten. A reason is measured as given. Duplicate topics or tags
are compared by NFC-of-casefold and *refused*, not merged: silently dropping an
entry would store something other than what the caller sent. This is a recorded
WP01 decision against the investigation's proposal (B5, "casefolded duplicate
elimination"), which RM-AC-002 ("invalid/duplicate ... rejected") supports. A control
character is any Unicode `Cc` code point (C0, DEL, C1); only summary and
reason admit `\\n`. A string that cannot be encoded as UTF-8 (a lone
surrogate) is refused as malformed.
"""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.vocabulary import (
    MAX_ASSOCIATION_REF_CHARACTERS,
    MAX_ASSOCIATIONS_PER_VERSION,
    MAX_METADATA_BYTES,
    MAX_METADATA_DEPTH,
    MAX_METADATA_KEY_CHARACTERS,
    MAX_METADATA_KEYS,
    MAX_REASON_CHARACTERS,
    MAX_SUMMARY_CHARACTERS,
    MAX_TERM_CHARACTERS,
    MAX_TERMS,
    MAX_TITLE_CHARACTERS,
    RESERVED_METADATA_KEY_PREFIXES,
    RESERVED_TYPE_PREFIXES,
    TYPE_TOKEN_PATTERN,
    AssociationTargetKind,
    AssociationVerification,
)

__all__ = [
    "ReportAssociation",
    "validate_associations",
    "validate_change_reason",
    "validate_metadata",
    "validate_relation",
    "validate_summary",
    "validate_tags",
    "validate_title",
    "validate_topics",
    "validate_type_token",
]


def _require_str(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ReportValidationError(field, "type")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ReportValidationError(field, "malformed") from None
    return value


def _refuse_controls(value: str, field: str, *, allow_newline: bool) -> None:
    for char in value:
        if unicodedata.category(char) == "Cc" and not (allow_newline and char == "\n"):
            raise ReportValidationError(field, "control_character")


def _bounded(value: str, field: str, maximum: int) -> None:
    if not value:
        raise ReportValidationError(field, "too_short")
    if len(value) > maximum:
        raise ReportValidationError(field, "too_long")


def validate_type_token(value: object, field: str = "report_type") -> str:
    """A report type: the token regex, outside every reserved namespace."""
    token = _require_str(value, field)
    if not TYPE_TOKEN_PATTERN.fullmatch(token):
        raise ReportValidationError(field, "pattern")
    if token.startswith(RESERVED_TYPE_PREFIXES):
        raise ReportValidationError(field, "reserved")
    return token


def validate_relation(value: object) -> str:
    """An association relation token: the type regex only (no reserved check)."""
    token = _require_str(value, "relation")
    if not TYPE_TOKEN_PATTERN.fullmatch(token):
        raise ReportValidationError("relation", "pattern")
    return token


def validate_title(value: object) -> str:
    """1..256 code points after NFC, no control character, not all whitespace."""
    title = unicodedata.normalize("NFC", _require_str(value, "title"))
    _bounded(title, "title", MAX_TITLE_CHARACTERS)
    _refuse_controls(title, "title", allow_newline=False)
    if title.isspace():
        raise ReportValidationError("title", "blank")
    return title


def validate_summary(value: object) -> str | None:
    """Optional; 1..2000 code points after NFC; `\\n` is the only control admitted."""
    if value is None:
        return None
    summary = unicodedata.normalize("NFC", _require_str(value, "summary"))
    _bounded(summary, "summary", MAX_SUMMARY_CHARACTERS)
    _refuse_controls(summary, "summary", allow_newline=True)
    return summary


def validate_change_reason(value: object, field: str = "change_reason") -> str | None:
    """Optional change or lifecycle reason: 1..500 code points, `\\n` admitted."""
    if value is None:
        return None
    reason = _require_str(value, field)
    _bounded(reason, field, MAX_REASON_CHARACTERS)
    _refuse_controls(reason, field, allow_newline=True)
    return reason


def _validate_terms(value: object, field: str) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise ReportValidationError(field, "type")
    if len(value) > MAX_TERMS:
        raise ReportValidationError(field, "too_many")
    accepted: list[str] = []
    seen: set[str] = set()
    for entry in value:
        term = unicodedata.normalize("NFC", _require_str(entry, field))
        _bounded(term, field, MAX_TERM_CHARACTERS)
        _refuse_controls(term, field, allow_newline=False)
        folded = unicodedata.normalize("NFC", term.casefold())
        if folded in seen:
            raise ReportValidationError(field, "duplicate")
        seen.add(folded)
        accepted.append(term)
    return tuple(accepted)


def validate_topics(value: object) -> tuple[str, ...]:
    """At most 24 entries of 1..64 code points; order kept, duplicates refused."""
    return _validate_terms(value, "topics")


def validate_tags(value: object) -> tuple[str, ...]:
    """At most 24 entries of 1..64 code points; order kept, duplicates refused."""
    return _validate_terms(value, "tags")


def _metadata_key(key: object) -> str:
    if not isinstance(key, str):
        raise ReportValidationError("metadata", "key_type")
    try:
        key.encode("utf-8")
    except UnicodeEncodeError:
        raise ReportValidationError("metadata", "malformed") from None
    if not key:
        raise ReportValidationError("metadata", "key_too_short")
    if len(key) > MAX_METADATA_KEY_CHARACTERS:
        raise ReportValidationError("metadata", "key_too_long")
    if any(unicodedata.category(char) == "Cc" for char in key):
        raise ReportValidationError("metadata", "control_character")
    if key.startswith(RESERVED_METADATA_KEY_PREFIXES):
        raise ReportValidationError("metadata", "reserved_key")
    return key


def _metadata_value(value: object, depth: int) -> object:
    # `bool` is tested before `int` and by exact type throughout: `True` is an
    # `int` subclass and an `IntEnum` or a `str` subclass would otherwise pass
    # as a plain scalar and serialize as something other than what it is.
    kind = type(value)
    if value is None or kind is bool or kind is int:
        return value
    if isinstance(value, float) and kind is float:
        if not math.isfinite(value):
            raise ReportValidationError("metadata", "non_finite")
        return value
    if isinstance(value, str) and kind is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ReportValidationError("metadata", "malformed") from None
        return value
    if (isinstance(value, list) and kind is list) or (isinstance(value, dict) and kind is dict):
        if depth + 1 > MAX_METADATA_DEPTH:
            raise ReportValidationError("metadata", "too_deep")
        if isinstance(value, list):
            return [_metadata_value(item, depth + 1) for item in value]
        return {_metadata_key(key): _metadata_value(item, depth + 1) for key, item in value.items()}
    raise ReportValidationError("metadata", "value_type")


def validate_metadata(value: object) -> dict[str, Any]:
    """A JSON object within every metadata bound; returns a plain deep copy.

    Every key at every depth obeys the key rules (1..64 code points, no control
    character, no reserved prefix); only top-level keys are counted against
    the 32-key bound. The byte bound is measured on the canonical
    serialization the manifest will hash.
    """
    if type(value) is not dict:
        raise ReportValidationError("metadata", "type")
    if len(value) > MAX_METADATA_KEYS:
        raise ReportValidationError("metadata", "too_many_keys")
    accepted = {_metadata_key(key): _metadata_value(item, 1) for key, item in value.items()}
    encoded = json.dumps(
        accepted, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    if len(encoded) > MAX_METADATA_BYTES:
        raise ReportValidationError("metadata", "too_large")
    return accepted


def _association_ref(value: object, field: str) -> str:
    ref = _require_str(value, field)
    _bounded(ref, field, MAX_ASSOCIATION_REF_CHARACTERS)
    _refuse_controls(ref, field, allow_newline=False)
    return ref


@dataclass(frozen=True, slots=True)
class ReportAssociation:
    """One typed association, frozen to the version that carries it.

    An `external_source` target can never be `verified`: nothing in the
    product can check a reference into a system it does not hold.
    """

    target_kind: AssociationTargetKind
    target_ref: str
    relation: str
    verification: AssociationVerification
    target_version_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target_kind, AssociationTargetKind):
            raise ReportValidationError("target_kind", "type")
        if not isinstance(self.verification, AssociationVerification):
            raise ReportValidationError("verification", "type")
        _association_ref(self.target_ref, "target_ref")
        validate_relation(self.relation)
        if self.target_version_ref is not None:
            _association_ref(self.target_version_ref, "target_version_ref")
        if (
            self.target_kind is AssociationTargetKind.EXTERNAL_SOURCE
            and self.verification is not AssociationVerification.ASSERTED
        ):
            raise ReportValidationError("verification", "external_source_unverifiable")


def validate_associations(value: object) -> tuple[ReportAssociation, ...]:
    """At most 64 associations, no two with one (kind, target_ref, relation).

    The tuple order is the ordinal the schema stores (0..63).
    """
    if isinstance(value, str | bytes | Mapping) or not isinstance(value, Sequence):
        raise ReportValidationError("associations", "type")
    if len(value) > MAX_ASSOCIATIONS_PER_VERSION:
        raise ReportValidationError("associations", "too_many")
    seen: set[tuple[AssociationTargetKind, str, str]] = set()
    for association in value:
        if not isinstance(association, ReportAssociation):
            raise ReportValidationError("associations", "type")
        key = (association.target_kind, association.target_ref, association.relation)
        if key in seen:
            raise ReportValidationError("associations", "duplicate")
        seen.add(key)
    return tuple(value)
