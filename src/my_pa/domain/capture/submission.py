"""The admission record and the receipt: facts about the request, not the text.

`CaptureSubmission` is the canonical package's transport-neutral admission
object. It records how one capture arrived and that it was accepted; the content
it admitted lives on the version, once, and is not copied here. `CaptureReceipt`
is what the caller gets back, and it carries an identifier, a digest, and times —
never the text it acknowledges (`09_LOGICAL_DATA_MODEL.md:271`).

**Two of the vocabularies below admit exactly one value in this build, and that
is a deliberate structural claim rather than an unfinished enumeration.** The
precedent and the argument are `extractions.trust_level`'s, which also permits
one value: a column that *can* only say one thing means no writer, no hand-run
statement, and no later revision can make it say another without changing this
enum and the frozen literal in the migration that mirrors it. Each pins an open
decision into the schema:

* `CaptureMethod.TYPED_TEXT` — `QC-AC-044` requires that no audio or call
  recording exists in the MVP, and no photo, voice, or share-sheet path is
  built. A row claiming one of those cannot be stored.
* `AdmissionResult.ACCEPTED` — a conflicting key fails the request closed and
  rolls the transaction back, so it stores nothing (`QC-AC-032`), and an
  identical replay reuses the row the unique key already holds rather than
  inserting a second. A stored submission is therefore an accepted one, and this
  is what keeps that true.

**The other two widened in WP-10, by exactly the forward `ALTER` this docstring
promised.** `CaptureTransport` and `TrustState` each said "one value now, and a
later transport widens it by a forward `ALTER` in its own revision rather than by
editing `1a4c9e77b2d5`". That is what happened, so the prior wording is corrected
here rather than left standing:

* `CaptureTransport` — `LOCAL` is the loopback gateway, the CLI and MCP, all of
  which the composition root authenticates as the process principal (`D-30`).
  `REMOTE_CLIENT` is an authenticated remote submission over the HTTPS ingress,
  presented by a client credential the operator minted
  (`domain.capture.client`).
* `TrustState` — `LOCAL_PRINCIPAL` is what is known about a caller the process
  itself vouches for. `REGISTERED_CLIENT` is what is known about a caller that
  presented a credential bound to exactly one Principal.

**The transport is provenance, and it is established by the transport rather
than declared by the caller.** It arrives through `ApplicationService.invoke`'s
own parameter — the same trust channel the acting `Principal` arrives on — and
there is no field on any command, payload, or envelope that could carry it. A
remote submission therefore lands in the same tables, in the same transaction,
through the same capability, and differs from a local one in two recorded columns
and in nothing else.

`registered_client_id` is still **absent** rather than nullable and never
written, and that is now a bounded residual rather than an impossibility: the
submission records *that* a registered client submitted it (`trust_state`) and
not *which*. Naming the client would be a column and a foreign key on a merged
table; the binding a reader needs — client to Principal — is on the client row
itself, and the audit event records the Principal. Recorded so the gap is
legible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.capture.errors import CaptureBoundsError, CaptureError
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "MAX_IDEMPOTENCY_KEY_CHARACTERS",
    "MAX_REQUEST_ID_CHARACTERS",
    "AdmissionResult",
    "CaptureKind",
    "CaptureMethod",
    "CaptureReceipt",
    "CaptureSubmission",
    "CaptureTransport",
    "TrustState",
    "trust_state_for",
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
    REMOTE_CLIENT = "remote_client"


class CaptureMethod(StrEnum):
    """How the content was produced by the person who wrote it."""

    TYPED_TEXT = "typed_text"


class CaptureKind(StrEnum):
    """The explicit source class selected by the author.

    A conversation log may seed a skeletal Conversation. A quick note never
    does so merely because its text looks conversational.
    """

    QUICK_NOTE = "quick_note"
    CONVERSATION_LOG = "conversation_log"


class TrustState(StrEnum):
    """What is known about the submitting client."""

    LOCAL_PRINCIPAL = "local_principal"
    REGISTERED_CLIENT = "registered_client"


#: Which trust state each transport implies.
#:
#: A mapping rather than a second value threaded beside the transport: the two
#: columns describe one fact from two angles, and a writer that could set them
#: independently is a writer that could store `remote_client` beside
#: `local_principal`. `trust_state_for` reads it rather than defaulting, so a
#: third transport added without a decision fails loudly here instead of quietly
#: claiming the local principal's trust.
_TRUST_STATE_OF: Final[Mapping[CaptureTransport, TrustState]] = MappingProxyType(
    {
        CaptureTransport.LOCAL: TrustState.LOCAL_PRINCIPAL,
        CaptureTransport.REMOTE_CLIENT: TrustState.REGISTERED_CLIENT,
    }
)


def trust_state_for(transport: CaptureTransport) -> TrustState:
    """What is known about a caller that reached this process by `transport`."""
    try:
        return _TRUST_STATE_OF[transport]
    except KeyError:
        raise CaptureError(
            "no trust state is declared for this transport; declare one beside it"
        ) from None


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
