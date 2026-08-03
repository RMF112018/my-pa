"""The admission record and the receipt: facts about the request, not the text.

`CaptureSubmission` is the canonical package's transport-neutral admission
object. It records how one capture arrived and that it was accepted; the content
it admitted lives on the version, once, and is not copied here. `CaptureReceipt`
is what the caller gets back, and it carries an identifier, a digest, and times —
never the text it acknowledges (`09_LOGICAL_DATA_MODEL.md:271`).

**Four of the vocabularies below admit exactly one value in this build, and that
is a deliberate structural claim rather than an unfinished enumeration.** The
precedent and the argument are `extractions.trust_level`'s, which also permits
one value: a column that *can* only say one thing means no writer, no hand-run
statement, and no later revision can make it say another without changing this
enum and the frozen literal in the migration that mirrors it. Each pins an open
decision into the schema:

* `CaptureTransport.LOCAL` — `D-30` issues no credential and the gateway has no
  ingress, so nothing remote can submit. A row claiming a remote transport
  cannot be stored while that stands.
* `CaptureMethod.TYPED_TEXT` — `QC-AC-044` requires that no audio or call
  recording exists in the MVP, and no photo, voice, or share-sheet path is
  built. A row claiming one of those cannot be stored.
* `TrustState.LOCAL_PRINCIPAL` — `P00-OD-010` has selected no authentication
  mechanism, so the only principal is the local one the composition root
  establishes. A row claiming an authenticated remote client cannot be stored.
* `AdmissionResult.ACCEPTED` — a conflicting key fails the request closed and
  rolls the transaction back, so it stores nothing (`QC-AC-032`), and an
  identical replay reuses the row the unique key already holds rather than
  inserting a second. A stored submission is therefore an accepted one, and this
  is what keeps that true.

`registered_client_id` is **absent** rather than nullable and never written, by
the rule that keeps `item_count` out of `audit_events`: `RegisteredCaptureClient`
is deferred (`D-74`) because `D-30`, `O-21` and `P00-OD-010` leave nothing that
could populate it, and a permanently null column reads as "no client" rather
than as "no such concept here yet".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.errors import CaptureBoundsError, CaptureError
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "MAX_IDEMPOTENCY_KEY_CHARACTERS",
    "MAX_REQUEST_ID_CHARACTERS",
    "AdmissionResult",
    "CaptureMethod",
    "CaptureReceipt",
    "CaptureSubmission",
    "CaptureTransport",
    "TrustState",
]

#: Bounds on the two caller-supplied strings an admission record stores. Both
#: are correlation input the caller controls, so both are bounded here and by a
#: server-side constraint: an unbounded caller-supplied column is a payload
#: channel, whatever it is named.
MAX_REQUEST_ID_CHARACTERS: Final = 128
MAX_IDEMPOTENCY_KEY_CHARACTERS: Final = 128


class CaptureTransport(StrEnum):
    """How a submission reached this process."""

    LOCAL = "local"


class CaptureMethod(StrEnum):
    """How the content was produced by the person who wrote it."""

    TYPED_TEXT = "typed_text"


class TrustState(StrEnum):
    """What is known about the submitting client."""

    LOCAL_PRINCIPAL = "local_principal"


class AdmissionResult(StrEnum):
    """What the admission decided about a submission that was stored."""

    ACCEPTED = "accepted"


def _bounded(value: object, name: str, ceiling: int) -> str:
    if not isinstance(value, str) or not value:
        raise CaptureError(f"{name} must be a non-empty string")
    if len(value) > ceiling:
        raise CaptureBoundsError(f"{name} may carry at most {ceiling} characters")
    return value


@dataclass(frozen=True, slots=True)
class CaptureSubmission:
    """One admitted submission: how a capture arrived, and that it was accepted.

    The payload digest is stored and the payload is not. It is what makes an
    idempotent replay decidable — the same key with the same bytes is a retry,
    the same key with different bytes is a conflict — without this record
    holding a second copy of the text the version already owns.
    """

    submission_id: str
    idempotency_key: str
    request_id: str
    correlation_id: str
    principal_id: str
    transport: CaptureTransport
    capture_method: CaptureMethod
    trust_state: TrustState
    payload_sha256: str
    server_received_at: datetime
    admission_result: AdmissionResult
    version_id: str
    receipt_id: str
    client_created_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.submission_id, IdKind.SUBMISSION)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.receipt_id, IdKind.RECEIPT)
        _bounded(self.request_id, "request_id", MAX_REQUEST_ID_CHARACTERS)
        _bounded(self.idempotency_key, "idempotency_key", MAX_IDEMPOTENCY_KEY_CHARACTERS)
        ensure_utc(self.server_received_at)
        if self.client_created_at is not None:
            ensure_utc(self.client_created_at)


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    """Safe evidence that one version was accepted and stored.

    Carries no content and no hash the version does not already hold. A receipt
    that quoted the text would put it in the one place `QC-AC-041` most expects
    to find it: the acknowledgement a caller keeps.
    """

    receipt_id: str
    capture_id: str
    version_id: str
    version_number: int
    idempotency_key: str
    content_sha256: str
    issued_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.receipt_id, IdKind.RECEIPT)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if isinstance(self.version_number, bool) or not isinstance(self.version_number, int):
            raise CaptureError("a receipt names an integer version number")
        if self.version_number < 1:
            raise CaptureError("version numbers start at one")
        _bounded(self.idempotency_key, "idempotency_key", MAX_IDEMPOTENCY_KEY_CHARACTERS)
        ensure_utc(self.issued_at)
