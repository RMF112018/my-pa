"""Canonical encodings of record lineage, Slice S1 (S1 contract section 5).

Pure functions with golden vectors (`tests/fixtures/lineage_canonical_vectors.json`,
shared by `tests/unit/test_lineage_canonical.py` and the SQL parity test).

"Canonical JSON" is ADR-014 decision 6: NFC-normalized strings,
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`,
UTF-8, no floats, every fixed key present (`null` when absent). The anchor,
evidence-set and identity objects hold only identifiers, closed tokens,
integers, hex and `null` -- all ASCII -- so NFC is the identity on them and the
S1 revision's two SQL functions (`knowledge.lineage_record_link_identity`,
`knowledge.lineage_anchor_identity`) rebuild the identity strings byte for byte
(section 5.5).

The request digest (section 5.4) is deliberately **not** NFC-normalized,
matching the Meetings request digest (`application/meetings.py`): free text is
hashed as the exact code points received, so an NFD and an NFC title under one
key are two requests.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Final

from my_pa.domain.lineage.model import EvidenceAnchor, InvalidLineageValueError, RecordRef
from my_pa.domain.lineage.vocabulary import (
    MemberRole,
    RecordLinkKind,
    RelationType,
    Selector,
)

__all__ = [
    "ANCHOR_KEYS",
    "EVIDENCE_SET_DOMAIN",
    "REQUEST_DOMAIN",
    "DuplicateAnchorIdentityError",
    "anchor_identity",
    "anchor_object",
    "anchor_order_key",
    "canonical_evidence",
    "canonical_json",
    "evidence_set_digest",
    "normalized_identity",
    "passage_sha256",
    "request_digest",
]

#: The anchor object's keys, in the order section 5.1 sorts anchors by.
ANCHOR_KEYS: Final = (
    "source_family",
    "source_root_id",
    "source_version_kind",
    "source_version_id",
    "source_version_no",
    "source_sha256",
    "passage_start_cp",
    "passage_end_cp",
    "passage_sha256",
    "role",
)

#: Domain separator of the evidence-set digest (section 5.1).
EVIDENCE_SET_DOMAIN: Final = b"lineage-evidence-set-v1\n"
#: Domain separator of the request digest (section 5.4).
REQUEST_DOMAIN: Final = b"lineage-request-v1\n"

_SCHEMA_VERSION: Final = 1


class DuplicateAnchorIdentityError(InvalidLineageValueError):
    """Two anchors of one evidence set share an `anchor_identity` (any roles)."""


def _checked(value: object, *, nfc: bool) -> object:
    """`value` with every string NFC-normalized when asked; refuse non-JSON shapes."""
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value) if nfc else value
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, Mapping):
        checked: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidLineageValueError("canonical JSON object keys are strings")
            checked[unicodedata.normalize("NFC", key) if nfc else key] = _checked(item, nfc=nfc)
        return checked
    if isinstance(value, list | tuple):
        return [_checked(item, nfc=nfc) for item in value]
    raise InvalidLineageValueError(
        "canonical JSON holds only strings, integers, booleans, lists, objects and null"
    )


def _dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_json(obj: object) -> str:
    """ADR-014 decision 6 canonical JSON, as text (encode it UTF-8 to hash it)."""
    return _dumps(_checked(obj, nfc=True))


def _plain(value: object) -> object:
    """A `StrEnum` member as its plain string value, anything else unchanged."""
    return str(value) if isinstance(value, str) else value


def anchor_object(anchor: EvidenceAnchor) -> dict[str, object]:
    """The section 5.1 anchor object: exactly the ten keys, `null` when absent."""
    return {key: _plain(getattr(anchor, key)) for key in ANCHOR_KEYS}


def anchor_identity(anchor: EvidenceAnchor) -> str:
    """`anchor_identity`: the canonical anchor object without `role`."""
    identity = anchor_object(anchor)
    del identity["role"]
    return canonical_json(identity)


def anchor_order_key(anchor: EvidenceAnchor) -> tuple[tuple[int, object], ...]:
    """Order by the ten values in key order, `null` before any value.

    Each position holds one type (a token, an identifier, hex or an integer), so
    integers compare numerically and strings by code point.
    """
    return tuple(
        (0, 0) if value is None else (1, value) for value in anchor_object(anchor).values()
    )


def canonical_evidence(anchors: Iterable[EvidenceAnchor]) -> tuple[EvidenceAnchor, ...]:
    """The set in canonical order; refuse two anchors sharing an identity."""
    ordered = tuple(sorted(anchors, key=anchor_order_key))
    seen: set[str] = set()
    for anchor in ordered:
        identity = anchor_identity(anchor)
        if identity in seen:
            raise DuplicateAnchorIdentityError("an evidence set repeats an anchor identity")
        seen.add(identity)
    return ordered


def evidence_set_digest(anchors: Iterable[EvidenceAnchor]) -> str:
    """`evidence_set_digest` of section 5.1; the empty set is legal."""
    document = {
        "schema_version": _SCHEMA_VERSION,
        "anchors": [anchor_object(anchor) for anchor in canonical_evidence(anchors)],
    }
    return hashlib.sha256(
        EVIDENCE_SET_DOMAIN + canonical_json(document).encode("utf-8")
    ).hexdigest()


def passage_sha256(body: str, start_cp: int, end_cp: int) -> str:
    """SHA-256 of `body[start:end]` in code points, UTF-8; the body is never normalized.

    Raises `InvalidLineageValueError` for `start >= end`, a negative start or an
    end beyond the body.
    """
    if (
        isinstance(start_cp, bool)
        or isinstance(end_cp, bool)
        or not 0 <= start_cp < end_cp <= len(body)
    ):
        raise InvalidLineageValueError("a passage lies inside its body and is not empty")
    return hashlib.sha256(body[start_cp:end_cp].encode("utf-8")).hexdigest()


def _endpoint(ref: RecordRef) -> dict[str, object]:
    return {"family": str(ref.family), "record_id": ref.record_id, "selector": str(Selector.ROOT)}


def normalized_identity(
    *,
    kind: RecordLinkKind,
    relation_type: RelationType,
    from_ref: RecordRef,
    to_ref: RecordRef,
    member_role: MemberRole | None,
    context_issue_id: str | None,
) -> str:
    """`normalized_identity` of section 5.3, stored in full (never hashed)."""
    return canonical_json(
        {
            "schema_version": _SCHEMA_VERSION,
            "kind": str(kind),
            "relation_type": str(relation_type),
            "from": _endpoint(from_ref),
            "to": _endpoint(to_ref),
            "member_role": None if member_role is None else str(member_role),
            "context_issue_id": context_issue_id,
        }
    )


def request_digest(capability: str, principal_id: str, request: Mapping[str, object]) -> str:
    """`request_digest` of section 5.4: no NFC, so free text hashes as received.

    `request` is the parsed payload without `idempotency_key`, optional fields
    present as `null`, anchors in canonical order and `clear_fields` sorted; the
    caller builds it, this function only encodes it.
    """
    document = _checked(
        {"capability": capability, "principal_id": principal_id, "request": request}, nfc=False
    )
    return hashlib.sha256(REQUEST_DOMAIN + _dumps(document).encode("utf-8")).hexdigest()
