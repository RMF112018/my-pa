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

**Retention and purge eligibility (B1, WP05b W3).** Retention is an
operator-modifiable policy of an owner Principal, UNSET by default: nothing
here or anywhere hardcodes a period. `RetentionPeriod` is a count of calendar
`days` (1..36525) or `years` (1..100); `RetentionSetRequest` sets one or unsets
the policy (`period=None`) against the policy revision the caller last saw,
and its `intent_digest` is the receipt digest the append-only policy history
stores. `purge_eligibility` is a PURE function that says whether a report
*would* be eligible for purge, evaluated in exactly this reason order:
`no_policy`, `held`, `not_trashed`, `retention_running`, `eligible`.

* **The clock start is an OPEN OPERATOR DECISION.** It is isolated as one
  named strategy, `RetentionClockStart`, with one member today,
  `most_recent_trash_event`: the `transitioned_at` of the newest `delete`
  lifecycle event of a report that is currently trashed (a report restored
  and trashed again restarts its clock). Another strategy is a new member
  and a new branch of `retention_clock_start`, nothing else.
* `years` adds calendar years (Feb 29 lands on Feb 28 of a non-leap year);
  `days` adds whole days. Eligible iff `now >= eligible_at`.
* **Informational only.** NOTHING consumes eligibility to delete anything:
  purge is not implemented, and retention never blocks an update, archive,
  restore or trash.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import MAXYEAR, UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final, NamedTuple

from my_pa.domain.lineage.vocabulary import (
    ATTESTED_AUTHORITY_CLASSES,
    ATTESTED_DECISION_CHANNELS,
)
from my_pa.domain.reports.content import canonical_json
from my_pa.domain.reports.errors import ReportRetentionOverflowError, ReportValidationError
from my_pa.domain.reports.records import ReportLifecycleEventRecord
from my_pa.domain.reports.values import validate_change_reason
from my_pa.domain.reports.vocabulary import LifecycleOperation, LifecycleState

__all__ = [
    "DEFAULT_RETENTION_HISTORY",
    "MAX_RETENTION_DAYS",
    "MAX_RETENTION_HISTORY",
    "MAX_RETENTION_YEARS",
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
    "PurgeEligibility",
    "PurgeEligibilityReason",
    "ReportEligibilityInputs",
    "ReportHoldEventRecord",
    "RetentionClockStart",
    "RetentionPeriod",
    "RetentionPolicyEventRecord",
    "RetentionPolicyView",
    "RetentionResult",
    "RetentionSetRequest",
    "RetentionUnit",
    "preservation_seal",
    "preservation_seal_document",
    "preservation_seal_parts",
    "purge_eligibility",
    "retention_clock_start",
    "retention_eligible_at",
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


# ---- retention and purge eligibility (WP05b W3) -----------------------------------

#: The bounds the schema's `a_report_retention_period_is_bounded` restates.
MAX_RETENTION_DAYS: Final = 36525
MAX_RETENTION_YEARS: Final = 100
#: `retention_policy` history page bounds (newest first).
DEFAULT_RETENTION_HISTORY: Final = 20
MAX_RETENTION_HISTORY: Final = 50


class RetentionUnit(StrEnum):
    """The unit of a retention period: calendar days or calendar years."""

    DAYS = "days"
    YEARS = "years"


_UNIT_MAXIMUM: Final[Mapping[RetentionUnit, int]] = {
    RetentionUnit.DAYS: MAX_RETENTION_DAYS,
    RetentionUnit.YEARS: MAX_RETENTION_YEARS,
}


@dataclass(frozen=True, slots=True)
class RetentionPeriod:
    """A retention period: `count` (days 1..36525, years 1..100) of `unit`."""

    count: int
    unit: RetentionUnit

    def __post_init__(self) -> None:
        if not isinstance(self.unit, RetentionUnit):
            raise ReportValidationError("period.unit", "type")
        if type(self.count) is not int:
            raise ReportValidationError("period.count", "type")
        if not 1 <= self.count <= _UNIT_MAXIMUM[self.unit]:
            raise ReportValidationError("period.count", "bounds")

    def as_dict(self) -> dict[str, object]:
        return {"count": self.count, "unit": self.unit.value}

    def added_to(self, start: datetime) -> datetime:
        """`start` plus this period, in UTC; calendar years land Feb 29 on Feb 28.

        A result past year 9999 raises `ReportRetentionOverflowError` (a
        `ReportValidationError`), never a bare `OverflowError`/`ValueError`.
        """
        aware = _aware(start, "clock_start")
        try:
            instant = aware.astimezone(UTC)
            if self.unit is RetentionUnit.DAYS:
                return instant + timedelta(days=self.count)
        except OverflowError as error:
            raise ReportRetentionOverflowError() from error
        year = instant.year + self.count
        if year > MAXYEAR:
            raise ReportRetentionOverflowError()
        try:
            return instant.replace(year=year)
        except ValueError:  # Feb 29 in a year that has none
            return instant.replace(year=year, day=28)


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ReportValidationError(field, "type")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ReportValidationError(field, "naive")
    return value


@dataclass(frozen=True, slots=True)
class RetentionSetRequest:
    """Every caller field of one `reports.retention.set`; `period=None` unsets the policy."""

    period: RetentionPeriod | None
    expected_policy_revision: int
    reason: str

    def __post_init__(self) -> None:
        if self.period is not None and not isinstance(self.period, RetentionPeriod):
            raise ReportValidationError("period", "type")
        if type(self.expected_policy_revision) is not int:
            raise ReportValidationError("expected_policy_revision", "type")
        if self.expected_policy_revision < 0:
            raise ReportValidationError("expected_policy_revision", "too_small")
        _hold_reason(self.reason)

    @property
    def intent_digest(self) -> str:
        """SHA-256 of the canonical JSON of the normalized caller payload."""
        payload = {
            "period": None if self.period is None else self.period.as_dict(),
            "expected_policy_revision": self.expected_policy_revision,
            "reason": self.reason,
        }
        return hashlib.sha256(canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class RetentionPolicyEventRecord:
    """One stored retention policy event: who changed the policy, when, from what to what."""

    event_id: str
    policy_revision: int
    #: The policy after this event; `None` = unset.
    period: RetentionPeriod | None
    #: The policy before it (its predecessor's `period`); `None` = unset.
    previous_period: RetentionPeriod | None
    predecessor_event_id: str | None
    reason: str
    intent_digest: str
    idempotency_key: str
    authority: CustodyAuthority
    recorded_at: datetime
    correlation_id: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class RetentionResult:
    """What `set_retention` answers, first time and on replay (the event is the receipt)."""

    policy_revision: int
    period: RetentionPeriod | None
    previous_period: RetentionPeriod | None
    event_id: str
    idempotency_key: str
    intent_digest: str
    recorded_at: datetime
    correlation_id: str
    audit_id: str
    replayed: bool

    @classmethod
    def of(cls, event: RetentionPolicyEventRecord, *, replayed: bool) -> RetentionResult:
        return cls(
            policy_revision=event.policy_revision,
            period=event.period,
            previous_period=event.previous_period,
            event_id=event.event_id,
            idempotency_key=event.idempotency_key,
            intent_digest=event.intent_digest,
            recorded_at=event.recorded_at,
            correlation_id=event.correlation_id,
            audit_id=event.audit_id,
            replayed=replayed,
        )


@dataclass(frozen=True, slots=True)
class RetentionPolicyView:
    """An owner's current retention policy and its newest-first history page.

    `current` is the newest event (`None`: never set); its `period` `None`
    means the policy was explicitly unset. Either way no period applies.
    """

    current: RetentionPolicyEventRecord | None
    history: tuple[RetentionPolicyEventRecord, ...]

    @property
    def policy_revision(self) -> int:
        return 0 if self.current is None else self.current.policy_revision

    @property
    def period(self) -> RetentionPeriod | None:
        return None if self.current is None else self.current.period


@dataclass(frozen=True, slots=True)
class ReportEligibilityInputs:
    """What purge eligibility reads of one report: its state, hold cache and lifecycle ledger."""

    report_id: str
    lifecycle_state: LifecycleState
    held: bool
    #: Every lifecycle event, oldest first.
    lifecycle_events: tuple[ReportLifecycleEventRecord, ...]


class RetentionClockStart(StrEnum):
    """When a report's retention clock starts: an OPEN OPERATOR DECISION, one strategy today."""

    MOST_RECENT_TRASH_EVENT = "most_recent_trash_event"


def retention_clock_start(
    strategy: RetentionClockStart,
    lifecycle_state: LifecycleState,
    lifecycle_events: Sequence[ReportLifecycleEventRecord],
) -> datetime | None:
    """The instant `strategy` starts the clock at, or `None` (no clock running).

    `most_recent_trash_event`: the `transitioned_at` of the newest `delete`
    event when the report is currently `trashed`; otherwise `None`. A trashed
    report whose ledger has no `delete` event is inconsistent and refused.
    """
    if not isinstance(strategy, RetentionClockStart):
        raise ReportValidationError("clock_start_strategy", "type")
    if lifecycle_state is not LifecycleState.TRASHED:
        return None
    deletes = [event for event in lifecycle_events if event.operation is LifecycleOperation.DELETE]
    if not deletes:
        raise ReportValidationError("lifecycle_events", "inconsistent")
    newest = max(deletes, key=lambda event: event.lifecycle_revision)
    return _aware(newest.transitioned_at, "clock_start")


def retention_eligible_at(period: RetentionPeriod, clock_start: datetime) -> datetime:
    """The first instant a report whose clock started at `clock_start` is past `period`."""
    return period.added_to(clock_start)


class PurgeEligibilityReason(StrEnum):
    """Why a report is or is not purge-eligible; evaluated in exactly this order."""

    NO_POLICY = "no_policy"
    HELD = "held"
    NOT_TRASHED = "not_trashed"
    RETENTION_RUNNING = "retention_running"
    ELIGIBLE = "eligible"


@dataclass(frozen=True, slots=True)
class PurgeEligibility:
    """Whether a report would be purge-eligible. Informational: nothing purges."""

    eligible: bool
    reason: PurgeEligibilityReason
    clock_start: datetime | None
    eligible_at: datetime | None
    clock_start_strategy: RetentionClockStart


def purge_eligibility(
    *,
    period: RetentionPeriod | None,
    held: bool,
    lifecycle_state: LifecycleState,
    clock_start: datetime | None,
    now: datetime,
    strategy: RetentionClockStart = RetentionClockStart.MOST_RECENT_TRASH_EVENT,
) -> PurgeEligibility:
    """PURE: the eligibility of one report, by the first reason that applies.

    `no_policy` (no period set), `held`, `not_trashed`, `retention_running`
    (`now < eligible_at`), else `eligible`. `eligible_at` is reported
    whenever a period and a clock start are both known.
    """
    if period is not None and not isinstance(period, RetentionPeriod):
        raise ReportValidationError("period", "type")
    if type(held) is not bool:
        raise ReportValidationError("held", "type")
    if not isinstance(lifecycle_state, LifecycleState):
        raise ReportValidationError("lifecycle_state", "type")
    if not isinstance(strategy, RetentionClockStart):
        raise ReportValidationError("clock_start_strategy", "type")
    instant = _aware(now, "now")
    if clock_start is not None:
        _aware(clock_start, "clock_start")
    if (lifecycle_state is LifecycleState.TRASHED) != (clock_start is not None):
        # The one strategy starts a clock exactly for a trashed report.
        raise ReportValidationError("clock_start", "inconsistent")
    eligible_at = None if period is None or clock_start is None else period.added_to(clock_start)

    def answer(reason: PurgeEligibilityReason) -> PurgeEligibility:
        return PurgeEligibility(
            eligible=reason is PurgeEligibilityReason.ELIGIBLE,
            reason=reason,
            clock_start=clock_start,
            eligible_at=eligible_at,
            clock_start_strategy=strategy,
        )

    if period is None:
        return answer(PurgeEligibilityReason.NO_POLICY)
    if held:
        return answer(PurgeEligibilityReason.HELD)
    if eligible_at is None:
        return answer(PurgeEligibilityReason.NOT_TRASHED)
    if instant < eligible_at:
        return answer(PurgeEligibilityReason.RETENTION_RUNNING)
    return answer(PurgeEligibilityReason.ELIGIBLE)
