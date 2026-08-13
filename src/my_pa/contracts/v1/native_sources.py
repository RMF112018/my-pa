"""Closed v1 contracts for the native-source application boundary.

The wire models deliberately mirror the source-built host's protocol-v1 JSON.
They reject unknown fields, non-canonical selection order, inconsistent scope,
and payload bytes outside ``0...255``.  Ordinary status models contain only
opaque identifiers, closed state, and counts; source content can exist only in
the admission envelope consumed by the application.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Final

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel

__all__ = [
    "NATIVE_SOURCE_MAX_CURSOR_BYTES",
    "NATIVE_SOURCE_MAX_PAGE_SIZE",
    "NATIVE_SOURCE_PROTOCOL_V1",
    "AppleAdmissionReceipt",
    "AppleReadGrant",
    "NativeAccountView",
    "NativeAdmissionEnvelope",
    "NativeBucketProgress",
    "NativeBucketSelection",
    "NativeBucketView",
    "NativeCoverageState",
    "NativeDiscoveryEnvelope",
    "NativeDiscoverySnapshot",
    "NativeEnvelopeMetadata",
    "NativePreflightEnvelope",
    "NativePreflightResult",
    "NativePreflightState",
    "NativeProviderFailure",
    "NativeSourceKind",
    "NativeSourceRecord",
]

NATIVE_SOURCE_PROTOCOL_V1: Final = "my-pa.native-source.v1"

#: The frozen page ceiling, held identical to ``NativeSourceProtocolV1.maximumPageSize``
#: in ``native/apple-source-host/Sources/AppleSourceHost/NativeSourceProtocolV1.swift``.
#: The host's bound is what stops an unbounded page becoming an unbounded spool
#: item; this one is what stops the application admitting a page the host would
#: never have produced. If the two drift, the pair stops being a bound at all, so
#: an architecture test compares the literals.
NATIVE_SOURCE_MAX_PAGE_SIZE: Final = 100

#: The frozen cursor ceiling, held identical to
#: ``NativeSourceProtocolV1.maximumCursorBytes``. Counted in UTF-8 bytes, as the
#: host counts it: a character ceiling would admit a multi-byte cursor the host
#: refuses, which is the drift this pair exists to prevent.
NATIVE_SOURCE_MAX_CURSOR_BYTES: Final = 512

_OPAQUE_ID: Final = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._:-]{0,198}[A-Za-z0-9])?$")
_REVISION: Final = re.compile(r"\A[^\s]{1,256}\Z")

OpaqueNativeID = Annotated[str, Field(pattern=_OPAQUE_ID.pattern, min_length=1, max_length=200)]
PayloadByte = Annotated[int, Field(ge=0, le=255)]


class NativeSourceKind(StrEnum):
    MAIL = "mail"
    CALENDAR = "calendar"
    CONTACTS = "contacts"
    TASKS = "tasks"


class NativeProviderFailure(StrEnum):
    PERMISSION_DENIED = "permission_denied"
    ACCOUNT_UNAVAILABLE = "account_unavailable"
    BUCKET_UNAVAILABLE = "bucket_unavailable"
    TRANSIENT_UNAVAILABLE = "transient_unavailable"
    INVALID_CURSOR = "invalid_cursor"
    UNSUPPORTED_VERSION = "unsupported_version"
    MALFORMED_REQUEST = "malformed_request"
    CAPACITY_EXCEEDED = "capacity_exceeded"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    INTEGRITY_FAILURE = "integrity_failure"


class NativePreflightState(StrEnum):
    REACHABLE = "reachable"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"
    IDENTITY_DRIFT = "identity_drift"


class NativeCoverageState(StrEnum):
    """Why a count is zero, or whether admitted evidence exists."""

    NOT_MEASURED = "not_measured"
    EMPTY = "empty"
    EVIDENCE_PRESENT = "evidence_present"
    PERMISSION_DENIED = "permission_denied"
    UNAVAILABLE = "unavailable"


class NativeEnvelopeMetadata(StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    envelope_id: OpaqueNativeID = Field(alias="envelopeID")
    host_instance_id: OpaqueNativeID = Field(alias="hostInstanceID")
    emitted_at_unix_milliseconds: int = Field(alias="emittedAtUnixMilliseconds")

    @model_validator(mode="after")
    def _version(self) -> NativeEnvelopeMetadata:
        if self.protocol_version != NATIVE_SOURCE_PROTOCOL_V1:
            raise ValueError("the native-source protocol version is unsupported")
        return self


class NativeAccountView(StrictModel):
    id: OpaqueNativeID
    kind: NativeSourceKind
    display_label: str = Field(alias="displayLabel", min_length=1, max_length=64)


class NativeBucketView(StrictModel):
    id: OpaqueNativeID
    account_id: OpaqueNativeID = Field(alias="accountID")
    parent_id: OpaqueNativeID | None = Field(default=None, alias="parentID")
    kind: NativeSourceKind
    display_label: str = Field(alias="displayLabel", min_length=1, max_length=64)
    is_selectable: bool = Field(alias="isSelectable")


class NativeDiscoverySnapshot(StrictModel):
    protocol_version: str = Field(alias="protocolVersion")
    kind: NativeSourceKind
    accounts: tuple[NativeAccountView, ...]
    buckets: tuple[NativeBucketView, ...]

    @model_validator(mode="after")
    def _consistent(self) -> NativeDiscoverySnapshot:
        if self.protocol_version != NATIVE_SOURCE_PROTOCOL_V1:
            raise ValueError("the native-source protocol version is unsupported")
        account_ids = tuple(account.id for account in self.accounts)
        bucket_ids = tuple(bucket.id for bucket in self.buckets)
        if account_ids != tuple(sorted(account_ids)) or len(account_ids) != len(set(account_ids)):
            raise ValueError("native accounts must be unique and canonically ordered")
        if bucket_ids != tuple(sorted(bucket_ids)) or len(bucket_ids) != len(set(bucket_ids)):
            raise ValueError("native buckets must be unique and canonically ordered")
        account_set = set(account_ids)
        if any(account.kind is not self.kind for account in self.accounts):
            raise ValueError("native discovery account kind is inconsistent")
        if any(
            bucket.kind is not self.kind or bucket.account_id not in account_set
            for bucket in self.buckets
        ):
            raise ValueError("native discovery bucket scope is inconsistent")
        return self


class NativeDiscoveryEnvelope(StrictModel):
    metadata: NativeEnvelopeMetadata
    snapshot: NativeDiscoverySnapshot

    @model_validator(mode="after")
    def _same_version(self) -> NativeDiscoveryEnvelope:
        if self.metadata.protocol_version != self.snapshot.protocol_version:
            raise ValueError("native discovery versions disagree")
        return self


class NativeBucketSelection(StrictModel):
    kind: NativeSourceKind
    account_id: OpaqueNativeID = Field(alias="accountID")
    bucket_id: OpaqueNativeID = Field(alias="bucketID")


class AppleReadGrant(StrictModel):
    """One NAS-issued, bounded instruction the Mac may execute but never mint."""

    schema_name: str = Field(alias="schema")
    authority_id: str = Field(alias="authorityID", min_length=1, max_length=72)
    principal_id: str = Field(alias="principalID", min_length=1, max_length=72)
    configuration_id: str = Field(alias="configurationID", min_length=1, max_length=72)
    configuration_revision: int = Field(alias="configurationRevision", ge=1)
    bridge_id: OpaqueNativeID = Field(alias="bridgeID")
    request_id: OpaqueNativeID = Field(alias="requestID")
    envelope_id: OpaqueNativeID = Field(alias="envelopeID")
    selection: NativeBucketSelection
    authorization: str
    expires_at_unix_milliseconds: int = Field(alias="expiresAtUnixMilliseconds", gt=0)
    page_limit: int = Field(alias="pageLimit", ge=1, le=NATIVE_SOURCE_MAX_PAGE_SIZE)
    time_range_start_unix_milliseconds: int = Field(alias="timeRangeStartUnixMilliseconds")
    time_range_end_unix_milliseconds: int = Field(alias="timeRangeEndUnixMilliseconds")
    cursor: str | None = Field(default=None, max_length=NATIVE_SOURCE_MAX_CURSOR_BYTES)

    @model_validator(mode="after")
    def _frozen_contract(self) -> AppleReadGrant:
        if self.schema_name != "my-pa.apple-source-read-grant.v1":
            raise ValueError("the Apple read grant schema is unsupported")
        if self.authorization != "AUTHORIZED_LIVE_PERSONAL_DATA_READ":
            raise ValueError("the Apple read grant is not authorized")
        if self.time_range_start_unix_milliseconds > self.time_range_end_unix_milliseconds:
            raise ValueError("the Apple read grant range is not ordered")
        if self.cursor is not None and len(self.cursor.encode()) > NATIVE_SOURCE_MAX_CURSOR_BYTES:
            raise ValueError("the Apple read grant cursor is outside its byte bound")
        return self


class AppleAdmissionReceipt(StrictModel):
    """Durable NAS answer which permits one exact local spool acknowledgement."""

    schema_name: str = Field(alias="schema")
    principal_id: str = Field(alias="principalID", min_length=1, max_length=72)
    bridge_id: OpaqueNativeID = Field(alias="bridgeID")
    authority_id: str = Field(alias="authorityID", min_length=1, max_length=72)
    request_id: OpaqueNativeID = Field(alias="requestID")
    envelope_id: OpaqueNativeID = Field(alias="envelopeID")
    admission_digest: str = Field(alias="admissionDigest", pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _schema(self) -> AppleAdmissionReceipt:
        if self.schema_name != "my-pa.apple-admission-receipt.v1":
            raise ValueError("the Apple admission receipt schema is unsupported")
        return self


class NativePreflightResult(StrictModel):
    selection: NativeBucketSelection
    state: NativePreflightState
    failure: NativeProviderFailure | None = None

    @model_validator(mode="after")
    def _consistent(self) -> NativePreflightResult:
        valid: dict[NativePreflightState, frozenset[NativeProviderFailure | None]] = {
            NativePreflightState.REACHABLE: frozenset({None}),
            NativePreflightState.PERMISSION_DENIED: frozenset(
                {NativeProviderFailure.PERMISSION_DENIED}
            ),
            NativePreflightState.UNAVAILABLE: frozenset(
                {
                    NativeProviderFailure.ACCOUNT_UNAVAILABLE,
                    NativeProviderFailure.BUCKET_UNAVAILABLE,
                    NativeProviderFailure.TRANSIENT_UNAVAILABLE,
                }
            ),
            NativePreflightState.IDENTITY_DRIFT: frozenset(
                {NativeProviderFailure.BUCKET_UNAVAILABLE}
            ),
        }
        if self.failure not in valid[self.state]:
            raise ValueError("native preflight state and failure disagree")
        return self


class NativePreflightEnvelope(StrictModel):
    metadata: NativeEnvelopeMetadata
    request_id: OpaqueNativeID = Field(alias="requestID")
    results: tuple[NativePreflightResult, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _canonical(self) -> NativePreflightEnvelope:
        keys = tuple(
            (result.selection.kind.value, result.selection.account_id, result.selection.bucket_id)
            for result in self.results
        )
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("native preflight results must be exact and canonically ordered")
        return self


class NativeSourceRecord(StrictModel):
    id: OpaqueNativeID
    bucket_id: OpaqueNativeID = Field(alias="bucketID")
    kind: NativeSourceKind
    source_revision: str = Field(alias="sourceRevision", min_length=1, max_length=256)
    source_modified_unix_milliseconds: int | None = Field(alias="sourceModifiedUnixMilliseconds")
    payload: tuple[PayloadByte, ...]

    @model_validator(mode="after")
    def _revision(self) -> NativeSourceRecord:
        if not _REVISION.fullmatch(self.source_revision):
            raise ValueError("native source revision has an invalid shape")
        return self


class NativeAdmissionEnvelope(StrictModel):
    metadata: NativeEnvelopeMetadata
    request_id: OpaqueNativeID = Field(alias="requestID")
    kind: NativeSourceKind
    account_id: OpaqueNativeID = Field(alias="accountID")
    bucket_id: OpaqueNativeID = Field(alias="bucketID")
    records: tuple[NativeSourceRecord, ...] = Field(max_length=NATIVE_SOURCE_MAX_PAGE_SIZE)
    next_cursor: str | None = Field(
        default=None, alias="nextCursor", max_length=NATIVE_SOURCE_MAX_CURSOR_BYTES
    )

    @model_validator(mode="after")
    def _exact_scope(self) -> NativeAdmissionEnvelope:
        if self.next_cursor is not None and (
            not self.next_cursor
            or any(character.isspace() for character in self.next_cursor)
            or len(self.next_cursor.encode()) > NATIVE_SOURCE_MAX_CURSOR_BYTES
        ):
            raise ValueError("native admission cursor has an invalid shape")
        if any(
            record.kind is not self.kind or record.bucket_id != self.bucket_id
            for record in self.records
        ):
            raise ValueError("native admission records escape the envelope scope")
        identities = tuple((record.id, record.source_revision) for record in self.records)
        if len(identities) != len(set(identities)):
            raise ValueError("native admission envelope repeats an immutable version")
        return self


class NativeBucketProgress(StrictModel):
    """Content-free status for one opaque configured bucket."""

    bucket_id: str
    state: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z_]{0,31}$")
    coverage: NativeCoverageState
    admitted_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    failure: NativeProviderFailure | None = None

    @model_validator(mode="after")
    def _coverage(self) -> NativeBucketProgress:
        if self.coverage is NativeCoverageState.EMPTY and self.admitted_count != 0:
            raise ValueError("empty native coverage cannot report admitted records")
        if self.coverage is NativeCoverageState.EVIDENCE_PRESENT and self.admitted_count == 0:
            raise ValueError("present native coverage requires admitted evidence")
        if self.coverage is NativeCoverageState.PERMISSION_DENIED:
            if self.failure is not NativeProviderFailure.PERMISSION_DENIED:
                raise ValueError("permission-denied coverage requires its closed failure")
        elif self.coverage is NativeCoverageState.UNAVAILABLE:
            if self.failure not in {
                NativeProviderFailure.ACCOUNT_UNAVAILABLE,
                NativeProviderFailure.BUCKET_UNAVAILABLE,
                NativeProviderFailure.TRANSIENT_UNAVAILABLE,
            }:
                raise ValueError("unavailable coverage requires a closed availability failure")
        elif self.failure is not None:
            raise ValueError("only denied or unavailable coverage carries a provider failure")
        return self
