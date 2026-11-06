"""Legal custody of a general report: holds and their sealed preservation copy (WP05b).

Pure and stdlib only, as the rest of this package: nothing here reads or
writes a row, talks to a clock or a store.

**Holds (B1).** A hold is placed and released by the attested local operator
only (H1). `HoldRequest` is every caller field of one placement or release,
validated on construction; its `intent_digest` is the SHA-256 of the canonical
JSON of `operation`, `report_id`, `expected_hold_revision` and `reason`, the
receipt digest the hold ledger stores and an idempotent replay compares. A
hold blocks trashing (`reports.delete`) and nothing else (H2).

**The preservation seal (B5).** Placing a hold writes one preservation object
per distinct content object of the report and then one seal object: the
canonical JSON (`canonical_json`: sorted keys, compact, UTF-8) of
`preservation_seal_document`. The seal lists every version with its stored
manifest, every preserved object with the digests and sizes of its parts, and
every lifecycle event, so the copy can be re-verified from the seal alone
(`preservation_seal_parts`) once its own digest is known from the hold row.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Final, NamedTuple

from my_pa.domain.lineage.vocabulary import (
    ATTESTED_AUTHORITY_CLASSES,
    ATTESTED_DECISION_CHANNELS,
)
from my_pa.domain.reports.content import canonical_json
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.values import validate_change_reason

__all__ = [
    "PRESERVATION_SEAL_SCHEMA",
    "CustodyAuthority",
    "HoldOperation",
    "HoldPreservation",
    "HoldRequest",
    "HoldResult",
    "PreservationSealPart",
    "PreservedLifecycleEvent",
    "PreservedObject",
    "PreservedRoot",
    "PreservedVersion",
    "ReportHoldEventRecord",
    "preservation_seal",
    "preservation_seal_document",
    "preservation_seal_parts",
]

#: The `schema` member of every seal this build writes.
PRESERVATION_SEAL_SCHEMA: Final = "report_preservation_seal_v1"

_PART_DECODED: Final = "decoded"
_PART_ORIGINAL: Final = "original"


class HoldOperation(StrEnum):
    """The two hold ledger operations; they alternate, starting with `place`."""

    PLACE = "place"
    RELEASE = "release"


class CustodyAuthority(NamedTuple):
    """The attested operator pair a hold (or retention) event records.

    Supplied by the caller from the attested lineage authority of the request
    (`application.lineage_authority.attested_lineage_authority`), never from a
    payload. Only `local_operator` through `local_cli`/`local_web` exists: the
    schema's CHECKs restate the same two sets.
    """

    authority_class: str
    decision_channel: str

    def validated(self) -> CustodyAuthority:
        """This pair, or `ReportValidationError("authority", "attested")`."""
        if (
            type(self.authority_class) is not str
            or type(self.decision_channel) is not str
            or self.authority_class not in ATTESTED_AUTHORITY_CLASSES
            or self.decision_channel not in ATTESTED_DECISION_CHANNELS
        ):
            raise ReportValidationError("authority", "attested")
        return self


def _hold_reason(value: object) -> str:
    reason = validate_change_reason(value, "reason")
    if reason is None:
        raise ReportValidationError("reason", "required")
    return reason


@dataclass(frozen=True, slots=True)
class HoldRequest:
    """Every caller field of one `reports.hold.place` or `reports.hold.release`."""

    operation: HoldOperation
    report_id: str
    expected_hold_revision: int
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.operation, HoldOperation):
            raise ReportValidationError("hold_operation", "type")
        if type(self.report_id) is not str or not self.report_id:
            raise ReportValidationError("report_id", "type")
        if type(self.expected_hold_revision) is not int:
            raise ReportValidationError("expected_hold_revision", "type")
        if self.expected_hold_revision < 0:
            raise ReportValidationError("expected_hold_revision", "too_small")
        _hold_reason(self.reason)

    @property
    def intent_digest(self) -> str:
        """SHA-256 of the canonical JSON of the normalized caller payload."""
        payload = {
            "operation": self.operation.value,
            "report_id": self.report_id,
            "expected_hold_revision": self.expected_hold_revision,
            "reason": self.reason,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class HoldPreservation:
    """What a placement's sealed preservation copy is, as its hold row records it."""

    seal_object_id: str
    seal_sha256: str
    seal_byte_count: int
    object_count: int
    version_count: int
    head_version_number: int
    lifecycle_revision: int


@dataclass(frozen=True, slots=True)
class ReportHoldEventRecord:
    """One stored hold ledger event; a `place` names its preservation copy."""

    event_id: str
    report_id: str
    hold_revision: int
    operation: HoldOperation
    resulting_held: bool
    predecessor_event_id: str | None
    reason: str
    intent_digest: str
    idempotency_key: str
    authority: CustodyAuthority
    recorded_at: datetime
    correlation_id: str
    audit_id: str
    preservation: HoldPreservation | None


@dataclass(frozen=True, slots=True)
class HoldResult:
    """What a placement or release answers, the first time and on every replay.

    The event row is the receipt: a replay is rebuilt from it unchanged, with
    `replayed=True`.
    """

    report_id: str
    operation: HoldOperation
    held: bool
    hold_revision: int
    event_id: str
    preservation: HoldPreservation | None
    idempotency_key: str
    intent_digest: str
    recorded_at: datetime
    correlation_id: str
    audit_id: str
    replayed: bool

    @classmethod
    def of(cls, event: ReportHoldEventRecord, *, replayed: bool) -> HoldResult:
        return cls(
            report_id=event.report_id,
            operation=event.operation,
            held=event.resulting_held,
            hold_revision=event.hold_revision,
            event_id=event.event_id,
            preservation=event.preservation,
            idempotency_key=event.idempotency_key,
            intent_digest=event.intent_digest,
            recorded_at=event.recorded_at,
            correlation_id=event.correlation_id,
            audit_id=event.audit_id,
            replayed=replayed,
        )


# ---- the preservation seal ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PreservedRoot:
    report_id: str
    owner_principal_id: str
    head_version_id: str
    head_version_number: int
    lifecycle_state: str
    lifecycle_revision: int
    created_by_kind: str
    created_by_id: str


@dataclass(frozen=True, slots=True)
class PreservedObject:
    """One preserved copy of one distinct content object, by the digests of its parts.

    `original_*` is `None` for identity content (no separate original part).
    """

    preservation_object_id: str
    content_id: str
    format: str
    encoding: str
    storage_kind: str
    decoded_sha256: str
    decoded_byte_count: int
    original_sha256: str | None
    original_byte_count: int | None


@dataclass(frozen=True, slots=True)
class PreservedVersion:
    version_id: str
    version_number: int
    change_kind: str
    recorded_at: datetime
    manifest_sha256: str
    manifest: Mapping[str, Any]
    content_id: str
    preservation_object_id: str


@dataclass(frozen=True, slots=True)
class PreservedLifecycleEvent:
    event_id: str
    lifecycle_revision: int
    operation: str
    prior_state: str
    resulting_state: str
    reason: str | None
    transitioned_at: datetime


def _instant(value: datetime) -> str:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ReportValidationError("sealed_at", "naive")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _digest_and_size(sha256: str | None, byte_count: int | None) -> dict[str, object] | None:
    if sha256 is None or byte_count is None:
        return None
    return {"sha256": sha256, "byte_count": byte_count}


def preservation_seal_document(
    *,
    root: PreservedRoot,
    hold_event_id: str,
    sealed_at: datetime,
    versions: Sequence[PreservedVersion],
    objects: Sequence[PreservedObject],
    lifecycle_events: Sequence[PreservedLifecycleEvent],
) -> dict[str, Any]:
    """The seal of one placement (contract B5), as a JSON-ready document."""
    return {
        "schema": PRESERVATION_SEAL_SCHEMA,
        "report_id": root.report_id,
        "owner_principal_id": root.owner_principal_id,
        "hold_event_id": hold_event_id,
        "sealed_at": _instant(sealed_at),
        "root": {
            "head_version_id": root.head_version_id,
            "head_version_number": root.head_version_number,
            "lifecycle_state": root.lifecycle_state,
            "lifecycle_revision": root.lifecycle_revision,
            "created_by_kind": root.created_by_kind,
            "created_by_id": root.created_by_id,
        },
        "versions": [
            {
                "version_id": version.version_id,
                "version_number": version.version_number,
                "change_kind": version.change_kind,
                "recorded_at": _instant(version.recorded_at),
                "manifest_sha256": version.manifest_sha256,
                "manifest": dict(version.manifest),
                "content_id": version.content_id,
                "preservation_object_id": version.preservation_object_id,
            }
            for version in versions
        ],
        "objects": [
            {
                "preservation_object_id": item.preservation_object_id,
                "content_id": item.content_id,
                "format": item.format,
                "encoding": item.encoding,
                "storage_kind": item.storage_kind,
                "decoded": _digest_and_size(item.decoded_sha256, item.decoded_byte_count),
                "original": _digest_and_size(item.original_sha256, item.original_byte_count),
            }
            for item in objects
        ],
        "lifecycle_events": [
            {
                "event_id": event.event_id,
                "lifecycle_revision": event.lifecycle_revision,
                "operation": event.operation,
                "prior_state": event.prior_state,
                "resulting_state": event.resulting_state,
                "reason": event.reason,
                "transitioned_at": _instant(event.transitioned_at),
            }
            for event in lifecycle_events
        ],
    }


def preservation_seal(document: Mapping[str, Any]) -> bytes:
    """The seal's bytes: the canonical JSON of its document."""
    return canonical_json(document)


class PreservationSealPart(NamedTuple):
    """One stored part a seal lists, with the digest and size it must have."""

    preservation_object_id: str
    part: str
    sha256: str
    byte_count: int


def preservation_seal_parts(seal: bytes) -> tuple[PreservationSealPart, ...]:
    """Every part of every object a seal lists, or `ValueError` for a malformed seal.

    The caller has already verified the seal's own bytes against the digest
    its hold row records, so this only reads the listing.
    """
    try:
        document = json.loads(seal.decode("utf-8"))
        if not isinstance(document, dict) or document.get("schema") != PRESERVATION_SEAL_SCHEMA:
            raise ValueError("schema")
        parts: list[PreservationSealPart] = []
        for item in document["objects"]:
            object_id = item["preservation_object_id"]
            for name in (_PART_DECODED, _PART_ORIGINAL):
                facts = item[name]
                if facts is None:
                    if name == _PART_DECODED:
                        raise ValueError("decoded")
                    continue
                sha256, byte_count = facts["sha256"], facts["byte_count"]
                if (
                    type(object_id) is not str
                    or type(sha256) is not str
                    or type(byte_count) is not int
                ):
                    raise ValueError("facts")
                parts.append(PreservationSealPart(object_id, name, sha256, byte_count))
    except (KeyError, TypeError, ValueError) as error:  # JSON and UTF-8 errors too
        raise ValueError("the preservation seal is malformed") from error
    if not parts:
        raise ValueError("the preservation seal lists no object")
    return tuple(parts)
