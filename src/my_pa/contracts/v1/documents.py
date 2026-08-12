"""The public shapes of a managed-document answer.

Three models, one per kind of answer the six `documents.` capabilities produce: a
receipt for `documents.create` and `documents.revise`, a version for
`documents.read`, and a listing entry for `documents.list`. Models rather than
dictionaries assembled in the use case, for the reason `contracts.v1.capture`
gives: the shape of a public answer is a contract, and a contract that exists
only as the code that happened to build it cannot be checked against anything.
`documents.archive` and `documents.restore` answer with a state and a boolean and
need no model of their own.

**What these models cannot carry is the point of them.**

*No location.* There is no path, filename, directory, shard, root or URI field on
any of the three, and there is nothing on the domain values behind them that
could fill one — `infrastructure.managed_document_stores.filesystem.store`
derives every location from the version identifier and exposes no location
concept at all. So "the MCP surface discloses no filesystem path" is a property
of the type rather than of a redaction step that could be forgotten.

*No owner.* `ManagedDocumentVersion` and `ManagedDocument` both carry
`owner_principal_id`, and neither view does. A caller reaches only its own
documents — every repository method filters by the authenticated partition — so
echoing the owner back would tell the caller nothing it did not already know
about itself, while making every answer a place another Principal's identifier
could appear if the filter ever broke. The safe direction is the one where the
field does not exist.

*No bytes on two of the three.* Only `ManagedDocumentVersionView` has a content
field, and it is populated only when the request asked for it. A listing carries
counts, identifiers, a digest and times; there is no field on it a document body
could go in.

**The digest is published and the bytes are not, on the receipt.** That is what
lets a caller verify that what was stored is what it sent — an idempotent replay
returns the same receipt and therefore the same digest — without the
acknowledgement quoting the document back.
"""

from __future__ import annotations

from typing import Final

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.capture.version import DIGEST_PATTERN
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.documents.managed import (
    MANAGED_MEDIA_TYPES,
    MAX_MANAGED_TITLE_CHARACTERS,
    DocumentState,
)

__all__ = [
    "ManagedDocumentListEntry",
    "ManagedDocumentReceiptView",
    "ManagedDocumentVersionView",
]

#: A SHA-256 as it is published, translated for pydantic's Rust engine exactly as
#: `contracts.v1.capture` translates it and for the same reason.
_DIGEST_PATTERN: Final = DIGEST_PATTERN.pattern.replace(r"\A", "^").replace(r"\Z", "$")
_Digest = Field(pattern=_DIGEST_PATTERN, min_length=64, max_length=64)


def _managed_media_type(value: str) -> str:
    """Refuse a media type outside the domain's closed set.

    Checked against `MANAGED_MEDIA_TYPES` itself rather than against a list
    written out here, so a media type the plane accepts and this refuses cannot
    exist. The refusal names no value: a contract model's `ValidationError` is
    rendered by pydantic and would carry the rejected string.
    """
    if value not in MANAGED_MEDIA_TYPES:
        raise ValueError("the managed plane does not store that media type")
    return value


class ManagedDocumentReceiptView(StrictModel):
    """Safe evidence that one managed document version was accepted and stored."""

    receipt_id: str
    document_id: str
    version_id: str
    version_number: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    content_sha256: str = _Digest
    byte_size: int = Field(ge=1)
    issued_at: UtcDatetime
    #: False when this answer is the replay of an earlier identical request. A
    #: caller retrying after a lost response needs to be able to tell that its
    #: retry stored nothing new.
    created: bool

    @model_validator(mode="after")
    def _check(self) -> ManagedDocumentReceiptView:
        validate_identifier(self.receipt_id, IdKind.MANAGED_RECEIPT)
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        return self


class ManagedDocumentVersionView(StrictModel):
    """One stored version, its place in the chain, and the state of its document.

    `content_base64` is the only field on any of these three models that can hold
    a document body, and it is `None` unless the request set `include_bytes`. The
    encoding is in the field's name rather than left to be inferred: JSON has no
    byte string, and a caller that does not know whether it is holding text or
    base64 will eventually guess.
    """

    document_id: str
    version_id: str
    version_number: int = Field(ge=1)
    supersedes_version_id: str | None = None
    title: str = Field(min_length=1, max_length=MAX_MANAGED_TITLE_CHARACTERS)
    media_type: str
    content_sha256: str = _Digest
    byte_size: int = Field(ge=1)
    recorded_at: UtcDatetime
    #: Whether this version is the document's head. Derived by the use case from
    #: the chain rather than read from a column, because there is no such column.
    is_current: bool
    state: DocumentState
    content_base64: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _check(self) -> ManagedDocumentVersionView:
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        validate_identifier(self.version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        _managed_media_type(self.media_type)
        if self.supersedes_version_id is not None:
            validate_identifier(self.supersedes_version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        return self


class ManagedDocumentListEntry(StrictModel):
    """One managed document as a listing presents it. Carries no bytes at all."""

    document_id: str
    state: DocumentState
    title: str = Field(min_length=1, max_length=MAX_MANAGED_TITLE_CHARACTERS)
    media_type: str
    version_count: int = Field(ge=1)
    latest_version_id: str
    latest_version_number: int = Field(ge=1)
    created_at: UtcDatetime
    latest_recorded_at: UtcDatetime

    @model_validator(mode="after")
    def _check(self) -> ManagedDocumentListEntry:
        validate_identifier(self.document_id, IdKind.MANAGED_DOCUMENT)
        validate_identifier(self.latest_version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        _managed_media_type(self.media_type)
        return self
