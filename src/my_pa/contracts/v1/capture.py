"""The public shapes of a capture answer.

Three models, one per kind of answer the four capture capabilities produce: a
receipt for `capture.create` and `capture.revise`, a version for `capture.read`,
and a listing entry for `capture.list`. They are models rather than dictionaries
assembled in the use case for the reason `CapabilityManifest` is: the shape of a
public answer is a contract, and a contract that only exists as the code that
happened to build it cannot be checked against anything.

**Only one of the three carries text.** `CaptureVersionView` does, because
reading a capture back is what `capture.read` is for and `QC-AC-010` requires
the original to be independently retrievable. `CaptureReceiptView` and
`CaptureListEntry` carry identifiers, a digest, counts, times, and — on the
listing only — an optional `display_label` that is caller-supplied metadata,
not a snippet of the note. Neither model has a field capture text could go in.
`QC-AC-041` says no capture text appears in logs, telemetry, event payloads,
URL parameters, or lock-screen notifications; a receipt is the thing a caller
keeps and a listing is the thing a caller sees most often, so those are the
two answers most worth making incapable of carrying it.

**The digest is published and the text is not, on the receipt.** That is what
lets a caller verify that what was stored is what it sent — `QC-AC-031`'s
idempotent replay returns the same receipt and therefore the same digest —
without the acknowledgement quoting the content back.
"""

from __future__ import annotations

from typing import Final

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleOperation,
    CaptureLifecycleOutcome,
    CaptureLifecycleState,
    CaptureReasonCategory,
)
from my_pa.domain.capture.version import DIGEST_PATTERN
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "CaptureLifecycleEventView",
    "CaptureLifecycleReceiptView",
    "CaptureListEntry",
    "CaptureReceiptView",
    "CaptureVersionView",
]

#: A SHA-256 as it is published: 64 lowercase hexadecimal characters, the same
#: shape `domain.capture.version` produces and the table constrains.
#:
#: Derived from the domain's own pattern rather than written out again, with the
#: same anchor translation `tables.py:_matches` performs for PostgreSQL: pydantic
#: compiles patterns with Rust's `regex`, which does not accept Python's `\A` and
#: `\Z`. The length bounds beside it are not belt and braces — they are what
#: makes the translated anchors exact regardless of how the engine treats a
#: trailing newline.
_DIGEST_PATTERN: Final = DIGEST_PATTERN.pattern.replace(r"\A", "^").replace(r"\Z", "$")
_Digest = Field(pattern=_DIGEST_PATTERN, min_length=64, max_length=64)


class CaptureReceiptView(StrictModel):
    """Safe evidence that one capture version was accepted and stored."""

    receipt_id: str
    capture_id: str
    version_id: str
    version_number: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    content_sha256: str = _Digest
    project_id: str | None = None
    issued_at: UtcDatetime
    #: False when this answer is the replay of an earlier identical request.
    #: A caller retrying after a lost response needs to be able to tell that its
    #: retry stored nothing new, and `QC-AC-031` is the criterion that says the
    #: two answers must otherwise be the same receipt.
    created: bool

    @model_validator(mode="after")
    def _check(self) -> CaptureReceiptView:
        validate_identifier(self.receipt_id, IdKind.RECEIPT)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        return self


class CaptureLifecycleEventView(StrictModel):
    """One historical lifecycle transition, as the opt-in history publishes it.

    A historical fact, never the current state: the root's current lifecycle is
    the three fields on the version view itself (CW-013). No reason, digest,
    key, correlation or audit reference -- the category is the only trace of
    the reason the owner gave (CW-018).
    """

    event_id: str
    lifecycle_revision: int = Field(ge=1)
    operation: CaptureLifecycleOperation
    resulting_state: CaptureLifecycleState
    transitioned_at: UtcDatetime
    reason_category: CaptureReasonCategory

    @model_validator(mode="after")
    def _check(self) -> CaptureLifecycleEventView:
        validate_identifier(self.event_id, IdKind.CAPTURE_LIFECYCLE_EVENT)
        return self


class CaptureLifecycleReceiptView(StrictModel):
    """The public answer to `capture.archive` and `capture.restore`.

    CW-009's binding, and nothing else: the root, the operation, the original
    outcome, both revisions, the event when one exists, the server time, and
    the correlation and audit references. `replayed` says this is the original
    receipt rather than the root's current state (CW-008). No reason, no
    digest and no capture text.
    """

    receipt_id: str
    capture_id: str
    owner_principal_id: str
    operation: CaptureLifecycleOperation
    outcome: CaptureLifecycleOutcome
    expected_lifecycle_revision: int = Field(ge=0)
    resulting_lifecycle_revision: int = Field(ge=0)
    event_id: str | None = None
    issued_at: UtcDatetime
    correlation_id: str
    audit_id: str
    idempotency_key: str = Field(min_length=1, max_length=128)
    replayed: bool

    @model_validator(mode="after")
    def _check(self) -> CaptureLifecycleReceiptView:
        validate_identifier(self.receipt_id, IdKind.CAPTURE_LIFECYCLE_RECEIPT)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        if self.event_id is not None:
            validate_identifier(self.event_id, IdKind.CAPTURE_LIFECYCLE_EVENT)
        return self


class CaptureVersionView(StrictModel):
    """One stored version, its place in the chain, and its five timestamps.

    `is_current` is derived by the use case from the chain rather than read from
    a column, because there is no such column: `captures` stores no
    current-version pointer, so nothing can say "current" and be out of step
    with the versions themselves.
    """

    capture_id: str
    version_id: str
    version_number: int = Field(ge=1)
    supersedes_version_id: str | None = None
    is_current: bool
    owner_principal_id: str
    project_id: str | None = None
    classification: Classification
    processing_policy: str
    content_sha256: str = _Digest
    character_count: int = Field(ge=1)
    text: str
    is_truncated: bool = False
    client_created_at: UtcDatetime | None = None
    server_received_at: UtcDatetime
    occurred_at: UtcDatetime | None = None
    accepted_at: UtcDatetime
    recorded_at: UtcDatetime
    #: CRL-WP-03 (D-4, CW-013): the root's *current* lifecycle, whichever
    #: version was read. `archived_at` opens the current archived interval and
    #: is null while active.
    lifecycle_state: CaptureLifecycleState = CaptureLifecycleState.ACTIVE
    lifecycle_revision: int = Field(default=0, ge=0)
    archived_at: UtcDatetime | None = None
    #: Present only when the read opted in (`include_lifecycle_history`): the
    #: most recent events, oldest first, and whether older ones were left out.
    lifecycle_history: tuple[CaptureLifecycleEventView, ...] | None = None
    lifecycle_history_truncated: bool | None = None

    @model_validator(mode="after")
    def _check(self) -> CaptureVersionView:
        if (self.lifecycle_state is CaptureLifecycleState.ARCHIVED) != (
            self.archived_at is not None
        ):
            raise ValueError("only an archived capture carries an archive time")
        if (self.lifecycle_history is None) != (self.lifecycle_history_truncated is None):
            raise ValueError("a lifecycle history states whether it was truncated")
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.supersedes_version_id is not None:
            validate_identifier(self.supersedes_version_id, IdKind.CAPTURE_VERSION)
        if (self.version_number == 1) is not (self.supersedes_version_id is None):
            raise ValueError(
                "the first version supersedes nothing and every later one supersedes a predecessor"
            )
        return self


class CaptureListEntry(StrictModel):
    """One capture in a listing: identity, owner, and where its chain has got to.

    `display_label` is the latest append-only label for this capture, or `null`
    when none has been recorded. It is not capture text and is never derived
    from `capture.read`.
    """

    capture_id: str
    owner_principal_id: str
    created_at: UtcDatetime
    version_count: int = Field(ge=1)
    latest_version_id: str
    latest_version_number: int = Field(ge=1)
    latest_recorded_at: UtcDatetime
    display_label: str | None = Field(default=None, min_length=1, max_length=120)
    project_id: str | None = None
    #: CRL-WP-03 (D-4): the root's current lifecycle.
    lifecycle_state: CaptureLifecycleState = CaptureLifecycleState.ACTIVE
    lifecycle_revision: int = Field(default=0, ge=0)
    archived_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _check(self) -> CaptureListEntry:
        if (self.lifecycle_state is CaptureLifecycleState.ARCHIVED) != (
            self.archived_at is not None
        ):
            raise ValueError("only an archived capture carries an archive time")
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.latest_version_id, IdKind.CAPTURE_VERSION)
        if self.project_id is not None:
            validate_identifier(self.project_id, IdKind.PROJECT)
        if self.latest_version_number > self.version_count:
            raise ValueError("a capture cannot have fewer versions than its highest version number")
        return self
