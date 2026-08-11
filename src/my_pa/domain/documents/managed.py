"""What a managed document is, and what may be said about one.

Managed documents are the product's **own** write plane. A source root is
authoritative and read-only; a managed document is a record this product created,
owns, and is allowed to write bytes for. The operating brief states the boundary
in one line — managed documents are a separate product-owned write plane, and
source roots remain read-only — and everything in this package exists to make
that a property of the structure rather than of a writer's restraint.

**A version is immutable, and a correction is a new version.** That is ADR-003
clause 3's shape applied to bytes: `ManagedContent` is a frozen value holding the
bytes and their digest, nothing here can produce a modified version of an
existing one, and the persistence layer refuses an `UPDATE` at the server. The
domain's contribution is that there is no operation with the shape "change this
version" for a writer to reach for.

**A title is metadata and only metadata.** It is bounded and refuses control
characters, and it is never joined to a filesystem path — not because it is
sanitised into safety, but because the byte store accepts no path at all. The
location of a version's bytes is derived by the store from the version's own
opaque identifier, so there is no parameter a title could travel in. Bounding it
here is about what a database column and a log line can hold, not about
traversal.

**Archive is a state, never destruction.** `LifecycleTransition` has two members
and neither removes anything: archiving withdraws a document from the active set
and restoring returns it. Hard deletion is deliberately absent from this module —
the register puts it out of scope and `AGENTS.md` section 8.2 reserves
irreversible destruction of canonical data to the operator — so there is no
domain vocabulary for it to be written against.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.extraction.text import MAX_EXTRACTED_CHARACTERS

__all__ = [
    "MANAGED_MEDIA_TYPES",
    "MAX_MANAGED_DOCUMENT_BYTES",
    "MAX_MANAGED_TITLE_CHARACTERS",
    "DocumentState",
    "EmptyDocumentError",
    "LifecycleTransition",
    "ManagedContent",
    "ManagedDocument",
    "ManagedDocumentBoundsError",
    "ManagedDocumentConflictError",
    "ManagedDocumentError",
    "ManagedDocumentReceipt",
    "ManagedDocumentVersion",
    "MediaTypeNotManagedError",
    "StaleExpectedVersionError",
    "UnmanageableTitleError",
]

#: Most bytes one managed version may carry, derived rather than chosen. It is
#: the same number `bootstrap.settings.MAX_FETCH_BYTES_CEILING` derives for a
#: single source read — four bytes per permitted extracted character, which is
#: the point past which no additional byte could belong to a document this build
#: can read at all. Expressed as the product and not as a round number so the two
#: cannot drift into disagreeing about how large a document this product handles.
#:
#: Derived from `domain.extraction.text` rather than imported from
#: `bootstrap.settings`, because a domain module may not depend on configuration;
#: both readings start from the same constant, so there is one number.
MAX_MANAGED_DOCUMENT_BYTES: Final = MAX_EXTRACTED_CHARACTERS * 4

#: Most characters a managed document's title may carry. A title is a caller
#: supplied string on a write path, and an unbounded caller-controlled column is
#: a payload channel whatever it is called — the same rule
#: `capture_submissions.request_id` is bounded under.
MAX_MANAGED_TITLE_CHARACTERS: Final = 200

#: The media types a managed document may declare. A closed set, so the column
#: carries a `CHECK` a hand-run statement meets too, and so that "what is stored
#: here" is a decision rather than whatever a caller wrote. `application/pdf` is
#: admitted for *storage* — storing bytes says nothing about extracting them, and
#: `P00-OD-003` gates extraction rather than custody.
MANAGED_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/json",
        "application/octet-stream",
        "application/pdf",
        "text/markdown",
        "text/plain",
    }
)

#: A title may not carry a control character. Newlines and terminal escapes are
#: the two shapes that turn a stored string into something a reader's own
#: renderer acts on, and `SECURITY.md` requires logs to carry safe metadata.
_CONTROL_CHARACTERS: Final = re.compile(r"[\x00-\x1f\x7f]")


class ManagedDocumentError(Exception):
    """Base class for every refusal this plane makes."""


class EmptyDocumentError(ManagedDocumentError):
    """A managed version carries bytes. Zero of them is not a document."""


class ManagedDocumentBoundsError(ManagedDocumentError):
    """The content is larger than this plane stores."""


class UnmanageableTitleError(ManagedDocumentError):
    """The title is absent, over-long, or carries a control character."""


class MediaTypeNotManagedError(ManagedDocumentError):
    """The declared media type is outside the closed managed set."""


class StaleExpectedVersionError(ManagedDocumentError):
    """The writer named a version that is no longer the document's head.

    Carries no version identifier and no number. A refusal that reported the
    current head would answer, for anyone who guessed a document identifier, a
    question they had not been authorized to ask; the writer refreshes and
    retries through the read path it already holds.
    """


class ManagedDocumentConflictError(ManagedDocumentError):
    """An idempotency key is already bound to a materially different request."""


class DocumentState(StrEnum):
    """Whether a managed document is in the active set.

    Two members, and there is deliberately no third. `deleted` would be a state
    whose only honest implementation removes bytes, and destruction of canonical
    data is reserved to the operator; a vocabulary that named it would be the
    first half of building it.
    """

    ACTIVE = "active"
    ARCHIVED = "archived"


class LifecycleTransition(StrEnum):
    """What one append-only lifecycle row records.

    The transition rather than the resulting state, because the row is an event:
    a document's state is the state the *latest* transition implies, read from
    the rows, so there is no state column anywhere that a second writer could
    leave disagreeing with the history.
    """

    ARCHIVED = "archived"
    RESTORED = "restored"

    def resulting_state(self) -> DocumentState:
        """The state a document is in immediately after this transition."""
        return (
            DocumentState.ARCHIVED if self is LifecycleTransition.ARCHIVED else DocumentState.ACTIVE
        )


@dataclass(frozen=True, slots=True)
class ManagedContent:
    """The bytes of one managed version, with the digest that identifies them.

    `bytes_` is `repr=False` for the reason `application.commands.CreateCapture`
    marks its text: a dataclass `repr` reaches a traceback, a log record and a
    pytest assertion message without anyone deciding it should, and this is the
    field that carries content.

    The digest is computed here and once. A caller-supplied digest would be a
    claim about bytes this object already holds, and reconciling the two is a
    branch nobody needs: everything downstream — the receipt, the integrity
    check, the backup round trip — compares against this one.
    """

    bytes_: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.bytes_, bytes | bytearray):
            raise EmptyDocumentError("a managed version carries bytes")
        if len(self.bytes_) == 0:
            raise EmptyDocumentError("a managed version carries at least one byte")
        if len(self.bytes_) > MAX_MANAGED_DOCUMENT_BYTES:
            raise ManagedDocumentBoundsError(
                f"a managed version carries at most {MAX_MANAGED_DOCUMENT_BYTES} bytes"
            )

    @property
    def digest(self) -> str:
        """The SHA-256 of the bytes, lowercase hexadecimal."""
        return hashlib.sha256(self.bytes_).hexdigest()

    @property
    def byte_size(self) -> int:
        return len(self.bytes_)


def validate_managed_title(title: str) -> str:
    """Return `title` unchanged, or refuse it.

    **Never reaches a path.** The byte store takes no path parameter at all, so
    there is nothing here to sanitise for traversal and nothing below that could
    be tricked by a title that looked like one. What this bounds is what a text
    column and a log line can be made to hold.
    """
    # Two statements rather than one `or`, and the split is deliberate: domain
    # models are plain dataclasses with no runtime type enforcement, so a
    # non-string really can reach here and must fail as a domain error rather
    # than as an incidental `AttributeError` from `strip()`. The same shape
    # `domain.common.identifiers.validate_identifier` uses.
    if not isinstance(title, str):
        raise UnmanageableTitleError("a managed document title is text")
    if not title.strip():
        raise UnmanageableTitleError("a managed document carries a non-blank title")
    if len(title) > MAX_MANAGED_TITLE_CHARACTERS:
        raise UnmanageableTitleError(
            f"a managed title is at most {MAX_MANAGED_TITLE_CHARACTERS} characters"
        )
    if _CONTROL_CHARACTERS.search(title):
        raise UnmanageableTitleError("a managed title carries no control character")
    return title


def validate_managed_media_type(media_type: str) -> str:
    """Return `media_type` unchanged, or refuse it as outside the closed set."""
    if media_type not in MANAGED_MEDIA_TYPES:
        raise MediaTypeNotManagedError("the managed plane does not store that media type")
    return media_type


@dataclass(frozen=True, slots=True)
class ManagedDocumentVersion:
    """One immutable version of one managed document.

    Holds no bytes. The bytes live in the byte store under this version's own
    identifier, and a version value that carried them would make every listing a
    read of every document. `content_sha256` is what binds the two, and it is the
    same digest the integrity check recomputes from the stored bytes.
    """

    version_id: str
    document_id: str
    version_number: int
    supersedes_version_id: str | None
    owner_principal_id: str
    title: str
    media_type: str
    content_sha256: str
    byte_size: int
    idempotency_key: str
    correlation_id: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        if self.supersedes_version_id is not None:
            validate_identifier(self.supersedes_version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        if self.version_number < 1:
            raise ManagedDocumentError("managed version numbers start at one")
        if (self.version_number == 1) is not (self.supersedes_version_id is None):
            raise ManagedDocumentError("only the first managed version supersedes nothing")
        validate_managed_title(self.title)
        validate_managed_media_type(self.media_type)
        if self.byte_size < 1:
            raise ManagedDocumentError("a stored managed version carries bytes")


@dataclass(frozen=True, slots=True)
class ManagedDocument:
    """One managed document as a listing presents it: identity, head, and state."""

    document_id: str
    owner_principal_id: str
    state: DocumentState
    title: str
    media_type: str
    version_count: int
    latest_version_id: str
    latest_version_number: int
    created_at: datetime
    latest_recorded_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.latest_version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        if self.version_count < 1:
            raise ManagedDocumentError("a managed document holds at least one version")


@dataclass(frozen=True, slots=True)
class ManagedDocumentReceipt:
    """What a caller is handed after a managed write commits.

    Issued after the transaction the write belongs to has committed, never
    before: a receipt is the product's statement that the record is durable, and
    one handed out inside the transaction would be a statement about work that
    can still disappear. The digest is on the receipt so a caller can verify the
    bytes it sent are the bytes the product now holds without reading them back.
    """

    receipt_id: str
    document_id: str
    version_id: str
    version_number: int
    idempotency_key: str
    content_sha256: str
    byte_size: int
    issued_at: datetime
    created: bool

    def __post_init__(self) -> None:
        validate_identifier(self.receipt_id, IdKind.MANAGED_RECEIPT)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)
