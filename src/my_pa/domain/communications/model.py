"""Closed vocabularies and immutable records for parsed communications evidence.

Every enumeration here is provider-neutral: the parser in
`my_pa.infrastructure.communications.evidence_v2` translates the producer's
vocabulary (folder roles, id formats, body completeness, timestamp field names)
onto these members, and anything it does not recognise onto an explicit
`UNKNOWN`/`OTHER` member with a diagnostic rather than a free string.

Identity rules (goal design implications, ratified by the WP1 ADR):

* the canonical key of a message is `(mailbox_ref, internet_message_id)` when
  the internet message id was provider-returned (`IdentityState.PROVIDER_RETURNED`);
* when it is absent the record falls back to `(mailbox_ref, provider_id)` and its
  identity state is `PROVIDER_ID_ONLY` -- a weaker key that can never be merged
  with an internet-message-id key;
* a producer `dedup_key`, a body hash or a subject is never an identity.

A mailbox item (provider id + folder) is an *observation* of a message; Inbox and
Sent copies of one internet message are two observations of one identity.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Final

from my_pa.domain.communications.diagnostics import ReasonCode

__all__ = [
    "BodyCompleteness",
    "BodyPart",
    "BodyState",
    "CanonicalKey",
    "ContentType",
    "ConversationState",
    "CoverageState",
    "Dialect",
    "FolderRole",
    "IdentityState",
    "IntegrityOutcome",
    "MessageTimestamps",
    "NormalizedMessage",
    "ParticipantField",
    "ParticipantState",
    "ProducerDerivedText",
    "ProviderIdFormat",
    "Publication",
    "QuarantinedRecord",
    "RecordClassification",
    "RecordOutcome",
    "SchemaVersion",
    "SourceCoverage",
    "SourceLane",
    "TimestampField",
    "Window",
    "WindowRule",
]

#: The one schema name this contract parses.
SCHEMA_NAME: Final = "communications_evidence_v2"
#: The one major version this contract accepts; any other major is refused.
SUPPORTED_MAJOR: Final = 2

#: The window end bound is inclusive: a message at exactly `end_utc` is in it.
#: One second is the producer's resolution (backfill windows end at `:59:59`),
#: so two windows whose bounds are at most this far apart are contiguous.
WINDOW_RESOLUTION: Final = timedelta(seconds=1)


class Dialect(StrEnum):
    """The two producer dialects of one schema name/version."""

    LEAN = "lean"
    RICH = "rich"


class RecordClassification(StrEnum):
    """What a single message record became. Exactly one per record ordinal."""

    ACCEPTED = "accepted"
    ACCEPTED_DEGRADED = "accepted_degraded"
    DUPLICATE_OBSERVATION = "duplicate_observation"
    OUT_OF_WINDOW = "out_of_window"
    QUARANTINED = "quarantined"


class IdentityState(StrEnum):
    PROVIDER_RETURNED = "provider_returned"
    PROVIDER_ID_ONLY = "provider_id_only"


class ProviderIdFormat(StrEnum):
    """Stability of the provider's item id. A mutable id changes when the item moves."""

    MUTABLE = "mutable"
    IMMUTABLE_VERIFIED = "immutable_verified"
    UNKNOWN = "unknown"


class FolderRole(StrEnum):
    INBOX = "inbox"
    SENT = "sent"
    OTHER = "other"


class SourceLane(StrEnum):
    MAIL = "mail"
    PROJECT_SYSTEM = "project_system"
    OTHER = "other"


class ConversationState(StrEnum):
    PROVIDER_RETURNED = "provider_returned"
    ABSENT = "absent"


class ParticipantState(StrEnum):
    PROVIDER_RETURNED = "provider_returned"
    NOT_EXPOSED = "not_exposed"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class TimestampField(StrEnum):
    """Which provider timestamp the producer selected as the message's time."""

    RECEIVED = "received"
    SENT = "sent"


class ContentType(StrEnum):
    HTML = "html"
    TEXT = "text"


class BodyState(StrEnum):
    """`withheld`: a privacy screen removed the content; sha/bytes describe the original."""

    PRESENT = "present"
    WITHHELD = "withheld"
    EMPTY = "empty"
    TRUNCATED = "truncated"


class BodyCompleteness(StrEnum):
    COMPLETE = "complete"
    TRUNCATED_UNKNOWN = "truncated_unknown"
    UNKNOWN = "unknown"


class IntegrityOutcome(StrEnum):
    """Result of checking stored content against its declared SHA-256 and byte count."""

    VERIFIED = "verified"
    MISMATCH = "mismatch"
    NOT_VERIFIABLE_WITHHELD = "not_verifiable_withheld"
    NOT_DECLARED = "not_declared"


class CoverageState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_AUTHORIZED = "not_authorized"
    FAILED = "failed"
    UNKNOWN = "unknown"


class WindowRule(StrEnum):
    """The producer's window-selection rule. `hours` is a nominal label under every rule."""

    WEEKDAY_PRIOR_24H = "weekday_prior_24h"
    FRIDAY_PRIOR_24H = "friday_prior_24h"
    EXPLICIT_UTC_BOUNDS = "explicit_utc_bounds"
    OTHER = "other"


@dataclass(frozen=True, slots=True, order=True)
class SchemaVersion:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True, slots=True)
class Window:
    """The declared collection window. Both bounds are aware UTC; `end_utc` is inclusive."""

    start_utc: datetime
    end_utc: datetime
    declared_hours: float | None
    rule: WindowRule
    tz: str | None
    backfill: bool | None
    dst_change_declared: bool | None
    dst_change_computed: bool | None

    @property
    def actual_seconds(self) -> int:
        return int((self.end_utc - self.start_utc).total_seconds())

    @property
    def actual_hours(self) -> float:
        return round(self.actual_seconds / 3600, 2)

    def contains(self, moment: datetime) -> bool:
        """Inclusive at both ends: `start_utc <= moment <= end_utc`."""
        return self.start_utc <= moment <= self.end_utc


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    """One declared source in a publication's coverage block.

    `key` is the producer's source key, kept so later work can join folder keys
    to their coverage; it is never printed (the aggregate CLI prints `key_kind`).
    """

    key: str | None
    role: FolderRole
    lane: SourceLane
    authorized: bool | None
    state: CoverageState
    raw_messages: int | None
    pages: int
    pages_not_ok: int
    errors: int
    warnings: int


@dataclass(frozen=True, slots=True)
class ParticipantField:
    """One participant field (from, sender, to, cc, bcc, reply_to).

    `addresses` are normalized: surrounding whitespace removed and lower-cased.
    Display names are deliberately not carried.
    """

    state: ParticipantState
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MessageTimestamps:
    selected_utc: datetime
    selected_field: TimestampField
    received_utc: datetime | None
    sent_utc: datetime | None


@dataclass(frozen=True, slots=True)
class BodyPart:
    """A stored body (`body` or `unique_body`).

    `content` is `None` exactly when `state` is `WITHHELD` (or the producer marked
    it withheld by policy and the parser discarded it). `sha256`/`utf8_bytes` are
    the producer's declared values; for a withheld body they describe the original.
    """

    state: BodyState
    content_type: ContentType
    content: str | None
    sha256: str
    utf8_bytes: int
    completeness: BodyCompleteness
    integrity: IntegrityOutcome


@dataclass(frozen=True, slots=True)
class ProducerDerivedText:
    """The producer's own derived plain text, when it supplied one.

    `usable` is true only when the text is non-empty, the producer marked it
    derived, and its declared SHA-256 verified (see `search_text.py`).
    """

    text: str | None
    integrity: IntegrityOutcome
    usable: bool


@dataclass(frozen=True, slots=True)
class CanonicalKey:
    """A message identity. `kind` separates the two key spaces so they never merge."""

    mailbox_ref: str
    kind: IdentityState
    value: str


@dataclass(frozen=True, slots=True)
class NormalizedMessage:
    """One provider-neutral message observation at `ordinal` in its publication."""

    ordinal: int
    provider_id: str
    provider_id_format: ProviderIdFormat
    mailbox_ref: str
    folder_key: str | None
    folder_role: FolderRole
    identity_state: IdentityState
    internet_message_id: str | None
    conversation_state: ConversationState
    conversation_id: str | None
    subject: str | None
    participants: Mapping[str, ParticipantField]
    timestamps: MessageTimestamps
    body: BodyPart
    unique_body: BodyPart | None
    derived_text: ProducerDerivedText | None
    has_attachments: bool | None
    declared_in_window: bool | None
    degraded_reasons: tuple[ReasonCode, ...]

    @property
    def canonical_key(self) -> CanonicalKey:
        if self.identity_state is IdentityState.PROVIDER_RETURNED:
            if self.internet_message_id is None:  # parser invariant; never true when parsed
                raise ValueError("provider_returned identity without an internet message id")
            return CanonicalKey(self.mailbox_ref, self.identity_state, self.internet_message_id)
        return CanonicalKey(self.mailbox_ref, self.identity_state, self.provider_id)

    @property
    def sender_address(self) -> str | None:
        """First `from` address, the value identity-conflict checks compare."""
        field = self.participants.get("from")
        return field.addresses[0] if field is not None and field.addresses else None


@dataclass(frozen=True, slots=True)
class QuarantinedRecord:
    """A record the parser could not normalize, with its reason codes (no content)."""

    ordinal: int
    reasons: tuple[ReasonCode, ...]


@dataclass(frozen=True, slots=True)
class RecordOutcome:
    """The classification of one record. `message` is `None` only when quarantined
    before normalization; a record quarantined afterwards (identity or integrity
    conflict) keeps its message so counts can be taken, but it must not be used."""

    ordinal: int
    classification: RecordClassification
    reasons: tuple[ReasonCode, ...]
    message: NormalizedMessage | None


@dataclass(frozen=True, slots=True)
class Publication:
    """An accepted publication: its envelope plus every record's outcome."""

    dialect: Dialect
    schema_version: SchemaVersion
    business_date: date
    mailbox_ref: str
    window: Window
    coverage_overall: CoverageState
    sources: tuple[SourceCoverage, ...]
    cycle_run_id_present: bool
    records: tuple[RecordOutcome, ...]
    unknown_top_level_keys: int
    unknown_record_keys: int
