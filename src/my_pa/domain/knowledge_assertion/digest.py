"""Canonical normalization, request digest and fingerprint v1 (KLP-WP-01).

Three frozen formulas of the R6 contract live here and nowhere else:

* **Value normalization** (plan section 4, `knowledge_normalization_rule`):
  text is Unicode NFC, stripped, with every internal whitespace run collapsed to
  one U+0020 and no case folding; a datetime is converted to UTC, truncated to
  microseconds and written in the RFC 3339 form `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
* **The request-digest object** (plan section 6.2), over which an explicit
  create or an autonomous submit replays: equal digest -> replay the stored
  result, different digest -> `idempotency_conflict`.
* **The fingerprint object v1** (plan section 6.5): the live/open uniqueness
  key shared by assertions and proposals.

All three use one encoding, frozen independently of the two JSON encodings in
`adapters/remote_request.py`: every string NFC-normalized first, then
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
encoded as UTF-8, then SHA-256 as lowercase hex. Null fields are present, never
absent. A different formula needs a new version number and a new schema
revision, because `fingerprint_version = 1` is frozen by CHECK; the golden
vectors in `tests/unit/test_knowledge_digest_vectors.py` hard-code the hex so a
silent change to this module fails there.

Pure functions: no I/O, no clock, no persistence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeNormalizationRule,
    KnowledgeOwnerRefKind,
    KnowledgeTemporalSemantics,
    KnowledgeValueType,
)

__all__ = [
    "DIGEST_OBJECT_VERSION",
    "FINGERPRINT_VERSION",
    "MAX_TEXT_VALUE_CHARACTERS",
    "DigestEvidence",
    "InvalidKnowledgeValueError",
    "OwnerRef",
    "assertion_fingerprint",
    "canonical_json_bytes",
    "fingerprint_object",
    "normalize_datetime",
    "normalize_text",
    "normalize_value",
    "normalized_value_sha256",
    "request_digest",
    "request_digest_object",
    "sha256_hex",
]

#: The `v` member of the request-digest object (section 6.2).
DIGEST_OBJECT_VERSION: Final = 1
#: `fingerprint_version`, frozen by CHECK on assertions, proposals and predicates.
FINGERPRINT_VERSION: Final = 1
#: `knowledge_assertion_text_is_bounded`: a normalized text value is 1..4000 characters.
MAX_TEXT_VALUE_CHARACTERS: Final = 4000

_WHITESPACE_RUN: Final = re.compile(r"\s+")

#: The normalization rule each value type must use (CHECK
#: `knowledge_predicate_normalization_follows_value_type`).
_RULE_FOR_TYPE: Final[Mapping[KnowledgeValueType, KnowledgeNormalizationRule]] = {
    KnowledgeValueType.TEXT: KnowledgeNormalizationRule.TEXT_NFC_TRIM_COLLAPSE_WHITESPACE,
    KnowledgeValueType.DATETIME: KnowledgeNormalizationRule.DATETIME_UTC_MICROSECOND,
}


class InvalidKnowledgeValueError(ValueError):
    """Raised when a value cannot be normalized under its declared rule.

    The message names the field, never the rejected value.
    """


def normalize_text(value: object) -> str:
    """Normalize a text value: NFC, strip, collapse whitespace runs to one space.

    No case folding: `ACME` and `Acme` are different statements. A value that is
    empty after normalization, or longer than `MAX_TEXT_VALUE_CHARACTERS`, is
    refused rather than stored as a fact.
    """
    if not isinstance(value, str):
        raise InvalidKnowledgeValueError("a text value must be a string")
    normalized = _WHITESPACE_RUN.sub(" ", unicodedata.normalize("NFC", value)).strip(" ")
    if not normalized:
        raise InvalidKnowledgeValueError("a text value must not be empty after normalization")
    if len(normalized) > MAX_TEXT_VALUE_CHARACTERS:
        raise InvalidKnowledgeValueError(
            f"a text value must be at most {MAX_TEXT_VALUE_CHARACTERS} characters"
        )
    return normalized


def normalize_datetime(value: object) -> str:
    """Normalize a datetime to RFC 3339 UTC with exactly six fractional digits.

    A naive datetime is refused (an unknown offset is not UTC). Python datetimes
    already carry microsecond resolution, so truncation to microseconds is exact.
    """
    if not isinstance(value, datetime):
        raise InvalidKnowledgeValueError("a datetime value must be a datetime")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise InvalidKnowledgeValueError("a datetime value must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def normalize_value(
    value_type: KnowledgeValueType, normalization_rule: KnowledgeNormalizationRule, value: object
) -> str:
    """Normalize `value` under the rule its predicate names.

    Refuses a rule that does not belong to the value type, so a text predicate
    can never be normalized as a datetime or the reverse.
    """
    if _RULE_FOR_TYPE.get(value_type) is not normalization_rule:
        raise InvalidKnowledgeValueError("normalization_rule does not follow value_type")
    if value_type is KnowledgeValueType.TEXT:
        return normalize_text(value)
    return normalize_datetime(value)


def _optional_instant(value: datetime | None) -> str | None:
    return None if value is None else normalize_datetime(value)


def _nfc(value: object) -> object:
    """Return `value` with every string (keys included) NFC-normalized."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {_nfc_key(key): _nfc(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_nfc(item) for item in value]
    if value is None or isinstance(value, bool | int):
        return value
    raise InvalidKnowledgeValueError(
        "canonical JSON holds only strings, integers, lists, objects and null"
    )


def _nfc_object(obj: Mapping[str, object]) -> dict[str, object]:
    return {_nfc_key(key): _nfc(item) for key, item in obj.items()}


def _nfc_key(key: object) -> str:
    if not isinstance(key, str):
        raise InvalidKnowledgeValueError("canonical JSON object keys must be strings")
    return unicodedata.normalize("NFC", key)


def canonical_json_bytes(obj: object) -> bytes:
    """The one frozen encoding: NFC strings, sorted keys, no spaces, UTF-8."""
    return json.dumps(_nfc(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256."""
    return hashlib.sha256(data).hexdigest()


def normalized_value_sha256(normalized_value: str) -> str:
    """`normalized_value_sha256`: SHA-256 hex of the NFC UTF-8 normalized value."""
    return sha256_hex(unicodedata.normalize("NFC", normalized_value).encode("utf-8"))


@dataclass(frozen=True, slots=True)
class OwnerRef:
    """A typed owner reference (`knowledge_owner_ref_kind` plus the owner id)."""

    kind: KnowledgeOwnerRefKind
    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, KnowledgeOwnerRefKind):
            raise InvalidKnowledgeValueError("owner_ref.kind must be a KnowledgeOwnerRefKind")
        owner_id: object = self.id
        if not isinstance(owner_id, str) or not owner_id:
            raise InvalidKnowledgeValueError("owner_ref.id must be a non-empty string")


@dataclass(frozen=True, slots=True)
class DigestEvidence:
    """One cited evidence entry of the request-digest object.

    `identity` is `[source_profile_id, external_object_id, external_version_id or
    ""]` for external evidence, `[cap_ id]` for capture evidence and
    `[mem_ id]` for memory evidence. Raw excerpt text is never
    part of the digest; only its SHA-256 is.
    """

    identity_kind: KnowledgeEvidenceIdentityKind
    identity: tuple[str, ...]
    content_hash: str
    excerpt_sha256: str | None
    role: KnowledgeEvidenceRole

    def __post_init__(self) -> None:
        if not isinstance(self.identity_kind, KnowledgeEvidenceIdentityKind):
            raise InvalidKnowledgeValueError("evidence.identity_kind must be a closed token")
        if not isinstance(self.role, KnowledgeEvidenceRole):
            raise InvalidKnowledgeValueError("evidence.role must be a closed token")
        expected = 3 if self.identity_kind is KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT else 1
        identity: object = self.identity
        if not isinstance(identity, tuple) or len(identity) != expected:
            raise InvalidKnowledgeValueError("evidence.identity has the wrong shape for its kind")
        if not all(isinstance(part, str) for part in self.identity):
            raise InvalidKnowledgeValueError("evidence.identity members must be strings")
        content_hash: object = self.content_hash
        if not isinstance(content_hash, str) or not content_hash:
            raise InvalidKnowledgeValueError("evidence.content_hash must be a non-empty string")
        if self.excerpt_sha256 is not None and not isinstance(self.excerpt_sha256, str):
            raise InvalidKnowledgeValueError("evidence.excerpt_sha256 must be a string or null")

    def as_object(self) -> dict[str, object]:
        return {
            "identity_kind": self.identity_kind.value,
            "identity": list(self.identity),
            "content_hash": self.content_hash,
            "excerpt_sha256": self.excerpt_sha256,
            "role": self.role.value,
        }


def _evidence_sort_key(entry: Mapping[str, object]) -> tuple[object, ...]:
    return (entry["identity_kind"], entry["identity"], entry["content_hash"], entry["role"])


def request_digest_object(
    *,
    subject_kind: str,
    subject_id: str,
    predicate_code: str,
    value_type: KnowledgeValueType,
    normalized_value: str,
    qualifier: Mapping[str, object] | None,
    effective_from: datetime | None,
    effective_to: datetime | None,
    owner_ref: OwnerRef | None,
    source_profile_id: str | None,
    scope_digest: str | None,
    trigger_event_ids: Iterable[str],
    evidence: Iterable[DigestEvidence],
) -> dict[str, object]:
    """Build the frozen section 6.2 digest object, NFC-normalized and ordered.

    `trigger_event_ids` are sorted and de-duplicated; evidence is sorted by
    (identity_kind, identity, content_hash, role) after NFC normalization.
    Excluded by construction: `retrieved_at`, `access_last_verified_at`, the
    transport idempotency key, raw excerpt text and any caller-declared
    classification or epistemic hint.
    """
    triggers = sorted({unicodedata.normalize("NFC", event_id) for event_id in trigger_event_ids})
    entries = [_nfc_object(entry.as_object()) for entry in evidence]
    ordered = sorted(entries, key=_evidence_sort_key)
    obj: dict[str, object] = {
        "v": DIGEST_OBJECT_VERSION,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "predicate_code": predicate_code,
        "value_type": KnowledgeValueType(value_type).value,
        "normalized_value": normalized_value,
        "qualifier": None if qualifier is None else dict(qualifier),
        "effective_from": _optional_instant(effective_from),
        "effective_to": _optional_instant(effective_to),
        "owner_ref": None
        if owner_ref is None
        else {"kind": owner_ref.kind.value, "id": owner_ref.id},
        "source_profile_id": source_profile_id,
        "scope_digest": scope_digest,
        "trigger_event_ids": triggers,
        "evidence": ordered,
    }
    return _nfc_object(obj)


def request_digest(digest_object: Mapping[str, object]) -> str:
    """`request_digest = sha256_hex(canonical_json_bytes(digest_object))`."""
    return sha256_hex(canonical_json_bytes(digest_object))


def fingerprint_object(
    *,
    subject_kind: str,
    subject_id: str,
    predicate_code: str,
    value_type: KnowledgeValueType,
    normalized_value: str,
    qualifier: Mapping[str, object] | None,
    temporal_semantics: KnowledgeTemporalSemantics,
    effective_from: datetime | None,
    effective_to: datetime | None,
) -> dict[str, object]:
    """Build the frozen section 6.5 fingerprint object v1.

    Excluded by construction: predicate_version, owner_ref, evidence, source
    profile and scope, trigger events, classification and epistemic status.
    """
    obj: dict[str, object] = {
        "v": FINGERPRINT_VERSION,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "predicate_code": predicate_code,
        "value_type": KnowledgeValueType(value_type).value,
        "normalized_value": normalized_value,
        "qualifier": None if qualifier is None else dict(qualifier),
        "temporal_semantics": KnowledgeTemporalSemantics(temporal_semantics).value,
        "effective_from": _optional_instant(effective_from),
        "effective_to": _optional_instant(effective_to),
    }
    return _nfc_object(obj)


def assertion_fingerprint(obj: Mapping[str, object]) -> str:
    """`assertion_fingerprint = proposal_fingerprint = sha256_hex(canonical(obj))`."""
    return sha256_hex(canonical_json_bytes(obj))
