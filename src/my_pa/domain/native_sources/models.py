"""Immutable native-source identities, ranges, memberships, and closed states.

Provider locators are deliberately absent. They belong to infrastructure and
cannot be copied into a public value, exception, audit record, or response by
using any model in this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from hashlib import sha256
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.source.registry import validate_source_label

__all__ = [
    "ContactMembership",
    "ExactBucketSelection",
    "LiveActivationGate",
    "LiveActivationGateState",
    "NativeAdmissionAuthority",
    "NativeAdmissionAuthorityError",
    "NativeBridge",
    "NativeCheckpoint",
    "NativeConfigurationRevision",
    "NativeRun",
    "NativeRunKind",
    "NativeRunState",
    "NativeSourceAccount",
    "NativeSourceBucket",
    "NativeSourceKind",
    "SimulationReceipt",
    "WatcherSimulation",
    "WatcherSimulationState",
]

_DIGEST: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_PROTOCOL_VERSION: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,31}\Z")
_ADAPTER_IDENTITY: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
CALENDAR_HORIZON_DAYS: Final = 90


class NativeSourceKind(StrEnum):
    MAIL = "mail"
    CALENDAR = "calendar"
    CONTACTS = "contacts"
    TASKS = "tasks"


class NativeRunKind(StrEnum):
    BASELINE = "baseline"
    BACKFILL = "backfill"
    RECONCILIATION = "reconciliation"


class NativeRunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class WatcherSimulationState(StrEnum):
    PENDING = "simulation_pending"
    RUNNING = "simulating"
    COMPLETE = "simulation_complete"
    FAILED = "simulation_failed"


class LiveActivationGateState(StrEnum):
    NOT_AUTHORIZED = "not_authorized"
    ATTESTATION_REQUIRED = "attestation_required"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class NativeBridge:
    bridge_id: str
    protocol_version: str
    label: str
    observed_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.bridge_id, IdKind.NATIVE_BRIDGE)
        if not _PROTOCOL_VERSION.fullmatch(self.protocol_version):
            raise ValueError("native bridge protocol version has an invalid shape")
        validate_source_label(self.label)
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class NativeSourceAccount:
    account_id: str
    bridge_id: str
    source_id: str
    kind: NativeSourceKind
    label: str
    observed_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.account_id, IdKind.NATIVE_ACCOUNT)
        validate_identifier(self.bridge_id, IdKind.NATIVE_BRIDGE)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_source_label(self.label)
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class NativeSourceBucket:
    bucket_id: str
    account_id: str
    parent_bucket_id: str | None
    kind: NativeSourceKind
    label: str
    selectable: bool
    observed_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.bucket_id, IdKind.NATIVE_BUCKET)
        validate_identifier(self.account_id, IdKind.NATIVE_ACCOUNT)
        if self.parent_bucket_id is not None:
            validate_identifier(self.parent_bucket_id, IdKind.NATIVE_BUCKET)
            if self.parent_bucket_id == self.bucket_id:
                raise ValueError("a native source bucket cannot parent itself")
        validate_source_label(self.label)
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class ExactBucketSelection:
    bucket_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.bucket_ids:
            raise ValueError("an exact native-source selection cannot be empty")
        for bucket_id in self.bucket_ids:
            validate_identifier(bucket_id, IdKind.NATIVE_BUCKET)
        if len(set(self.bucket_ids)) != len(self.bucket_ids):
            raise ValueError("an exact native-source selection cannot repeat a bucket")
        object.__setattr__(self, "bucket_ids", tuple(sorted(self.bucket_ids)))


@dataclass(frozen=True, slots=True)
class NativeConfigurationRevision:
    configuration_id: str
    revision: int
    bridge_id: str
    timezone_name: str
    start_date: date
    cutoff_at: datetime
    selection: ExactBucketSelection
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.configuration_id, IdKind.NATIVE_CONFIGURATION)
        validate_identifier(self.bridge_id, IdKind.NATIVE_BRIDGE)
        if self.revision < 1:
            raise ValueError("a native configuration revision starts at one")
        try:
            zone = ZoneInfo(self.timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("native configuration timezone is unknown") from exc
        cutoff = ensure_utc(self.cutoff_at)
        created = ensure_utc(self.created_at)
        local_start = datetime.combine(self.start_date, time.min, tzinfo=zone).astimezone(UTC)
        if local_start > cutoff:
            raise ValueError("native configuration start must not follow its cutoff")
        object.__setattr__(self, "cutoff_at", cutoff)
        object.__setattr__(self, "created_at", created)

    @property
    def start_at(self) -> datetime:
        return datetime.combine(
            self.start_date,
            time.min,
            tzinfo=ZoneInfo(self.timezone_name),
        ).astimezone(UTC)

    @property
    def calendar_horizon_at(self) -> datetime:
        return self.cutoff_at + timedelta(days=CALENDAR_HORIZON_DAYS)

    @property
    def selection_sha256(self) -> str:
        """Digest the canonical sorted bucket set persisted by the database seal."""
        return sha256("\n".join(self.selection.bucket_ids).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ContactMembership:
    membership_id: str
    group_bucket_id: str
    contact_object_id: str
    version_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.membership_id, IdKind.SOURCE_MEMBERSHIP)
        validate_identifier(self.group_bucket_id, IdKind.NATIVE_BUCKET)
        validate_identifier(self.contact_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.version_id, IdKind.VERSION)
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))


@dataclass(frozen=True, slots=True)
class NativeRun:
    run_id: str
    configuration_id: str
    configuration_revision: int
    bridge_id: str
    adapter_identity: str
    kind: NativeRunKind
    state: NativeRunState
    start_at: datetime
    cutoff_at: datetime
    calendar_horizon_at: datetime
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.run_id, IdKind.NATIVE_RUN)
        validate_identifier(self.configuration_id, IdKind.NATIVE_CONFIGURATION)
        validate_identifier(self.bridge_id, IdKind.NATIVE_BRIDGE)
        if self.configuration_revision < 1:
            raise ValueError("a native run requires a configuration revision")
        if not _ADAPTER_IDENTITY.fullmatch(self.adapter_identity):
            raise ValueError("a native run adapter identity has an invalid shape")
        start = ensure_utc(self.start_at)
        cutoff = ensure_utc(self.cutoff_at)
        horizon = ensure_utc(self.calendar_horizon_at)
        recorded = ensure_utc(self.recorded_at)
        if start > cutoff or horizon != cutoff + timedelta(days=CALENDAR_HORIZON_DAYS):
            raise ValueError("a native run has inconsistent temporal bounds")
        object.__setattr__(self, "start_at", start)
        object.__setattr__(self, "cutoff_at", cutoff)
        object.__setattr__(self, "calendar_horizon_at", horizon)
        object.__setattr__(self, "recorded_at", recorded)


@dataclass(frozen=True, slots=True)
class NativeCheckpoint:
    checkpoint_id: str
    bucket_id: str
    sequence: int
    previous_checkpoint_id: str | None
    cursor_digest: str
    recorded_at: datetime
    job_id: str | None = None
    admission_authority_id: str | None = None
    terminal: bool = False
    item_count: int = 0

    def __post_init__(self) -> None:
        validate_identifier(self.checkpoint_id, IdKind.NATIVE_CHECKPOINT)
        validate_identifier(self.bucket_id, IdKind.NATIVE_BUCKET)
        if self.job_id is not None:
            validate_identifier(self.job_id, IdKind.NATIVE_JOB)
        if self.admission_authority_id is not None:
            validate_identifier(self.admission_authority_id, IdKind.NATIVE_AUTHORITY)
        if (self.job_id is None) != (self.admission_authority_id is None):
            raise ValueError("a baseline checkpoint binds both job and admission authority")
        if self.sequence < 1:
            raise ValueError("a native checkpoint sequence starts at one")
        if self.previous_checkpoint_id is not None:
            validate_identifier(self.previous_checkpoint_id, IdKind.NATIVE_CHECKPOINT)
        if (self.sequence == 1) != (self.previous_checkpoint_id is None):
            raise ValueError("a native checkpoint predecessor must match its sequence")
        if not _DIGEST.fullmatch(self.cursor_digest):
            raise ValueError("a native checkpoint cursor digest must be lowercase SHA-256")
        if self.item_count < 0:
            raise ValueError("a native checkpoint item count cannot be negative")
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))


@dataclass(frozen=True, slots=True)
class WatcherSimulation:
    simulation_id: str
    bucket_id: str
    state: WatcherSimulationState
    sequence: int
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.simulation_id, IdKind.NATIVE_SIMULATION)
        validate_identifier(self.bucket_id, IdKind.NATIVE_BUCKET)
        if self.sequence < 1:
            raise ValueError("a simulation sequence starts at one")
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))

    def transition(self, state: WatcherSimulationState, *, at: datetime) -> WatcherSimulation:
        allowed = {
            WatcherSimulationState.PENDING: {WatcherSimulationState.RUNNING},
            WatcherSimulationState.RUNNING: {
                WatcherSimulationState.COMPLETE,
                WatcherSimulationState.FAILED,
            },
            WatcherSimulationState.COMPLETE: set(),
            WatcherSimulationState.FAILED: set(),
        }
        if state not in allowed[self.state]:
            raise ValueError("native watcher simulation transition is not permitted")
        return replace(self, state=state, sequence=self.sequence + 1, recorded_at=ensure_utc(at))


@dataclass(frozen=True, slots=True)
class SimulationReceipt:
    receipt_id: str
    simulation_id: str
    terminal_state: WatcherSimulationState
    checkpoint_id: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.receipt_id, IdKind.NATIVE_SIMULATION_RECEIPT)
        validate_identifier(self.simulation_id, IdKind.NATIVE_SIMULATION)
        validate_identifier(self.checkpoint_id, IdKind.NATIVE_CHECKPOINT)
        if self.terminal_state not in {
            WatcherSimulationState.COMPLETE,
            WatcherSimulationState.FAILED,
        }:
            raise ValueError("a simulation receipt requires a terminal simulation state")
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))


@dataclass(frozen=True, slots=True)
class LiveActivationGate:
    gate_id: str
    bucket_id: str
    state: LiveActivationGateState
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.gate_id, IdKind.NATIVE_LIVE_GATE)
        validate_identifier(self.bucket_id, IdKind.NATIVE_BUCKET)
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))


class NativeAdmissionAuthorityError(RuntimeError):
    """A durable native admission grant was absent, stale, or mismatched."""


@dataclass(frozen=True, slots=True)
class NativeAdmissionAuthority:
    """One application-issued handle for a durable exact admission grant."""

    authority_id: str
    configuration_id: str
    configuration_revision: int
    bridge_id: str
    bucket_id: str
    source_id: str
    audit_id: str
    envelope_id: str
    request_id: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.authority_id, IdKind.NATIVE_AUTHORITY)
        validate_identifier(self.configuration_id, IdKind.NATIVE_CONFIGURATION)
        validate_identifier(self.bridge_id, IdKind.NATIVE_BRIDGE)
        validate_identifier(self.bucket_id, IdKind.NATIVE_BUCKET)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        if self.configuration_revision < 1:
            raise ValueError("native authority requires a configuration revision")
        for name, value in (("envelope", self.envelope_id), ("request", self.request_id)):
            if not value or len(value) > 200:
                raise ValueError(f"native authority requires a bounded {name} identifier")
        object.__setattr__(self, "issued_at", ensure_utc(self.issued_at))
        object.__setattr__(self, "expires_at", ensure_utc(self.expires_at))
        if not self.issued_at < self.expires_at <= self.issued_at + timedelta(minutes=10):
            raise ValueError("native authority lifetime must be positive and bounded")
