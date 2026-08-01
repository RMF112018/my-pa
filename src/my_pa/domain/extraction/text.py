"""Text and Markdown extraction, and the three things it can honestly return.

`docs/specs` section 12 makes safely decoded `text/plain` and Markdown the
mandatory baseline and everything else explicit: "Unsupported/malformed media is
explicit, not empty text." So `extract_text` never returns an empty string to
mean a failure. It returns one of three outcomes, and which one it is is a field
rather than something a caller infers from a length.

* `EXTRACTED` — the bytes decoded, and the text is bound to the version they
  came from.
* `UNSUPPORTED` — the media type is not one this extractor handles. That
  includes `application/pdf`, which is *reported*, not skipped: `P00-OD-003` is
  an open operator decision and no PDF library is a dependency of this
  repository. It also includes a media type of `None`, which means "not
  identified", which is not the same as "text".
* `QUARANTINED` — processing stopped for one of the section 12 triggers, and the
  reason says which. A decode failure lands here, never in an empty string.

**Provenance is built here, not accepted here.** A caller that supplied a
`Provenance` could name an extractor that did not run, or a trust level of
`SOURCE_ORIGINAL` for text this module derived. Taking the source binding and
constructing the provenance means the recorded extractor is the one that
executed and the trust level is `SOURCE_BOUND_DERIVED` by construction
(`INV-PKL-003`).

**Attribution.** The caller passes both the version it observed and the version
the bytes came back bound to. When they differ, the output cannot be attributed
to the observed version and is quarantined rather than stored against either —
section 12's last trigger, and the reason the two are separate parameters
instead of one.

**The extracted text is personal data.** It is in exactly one place, the `text`
field of an `EXTRACTED` outcome, and `__repr__` reports its length rather than
its content so that logging or asserting on an outcome cannot disclose it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.common.time import ensure_utc, utc_now
from my_pa.domain.extraction.quarantine import QuarantineReason

__all__ = [
    "EXTRACTOR",
    "EXTRACTOR_VERSION",
    "MAX_EXTRACTED_CHARACTERS",
    "SUPPORTED_MEDIA_TYPES",
    "ExtractionOutcome",
    "ExtractionStatus",
    "extract_text",
]

#: The mandatory baseline of section 12, and the whole of it. `application/pdf`
#: is deliberately absent: it is decision-gated on `P00-OD-003`, and admitting it
#: here would be the silent coercion the same section forbids.
SUPPORTED_MEDIA_TYPES: Final = frozenset({"text/markdown", "text/plain"})

#: Recorded in every provenance this module produces. The version is bumped when
#: the decoded output could differ for the same bytes, because that is the
#: question a stored value has to be able to answer later.
EXTRACTOR: Final = "my_pa.text"
EXTRACTOR_VERSION: Final = "1"

#: Most characters one object may yield. Section 12 requires a bounded output for
#: a decision-gated extractor and section 15 requires bounded work generally; for
#: UTF-8 this can only bind below the byte ceiling the fetch already applied, so
#: it is a second, cheaper ceiling rather than the only one. Four million
#: characters is far past any document in a personal corpus and far below
#: anything that would strain a single row.
MAX_EXTRACTED_CHARACTERS: Final = 1 << 22

#: A UTF-8 byte-order mark. Stripped rather than decoded, because it is an
#: encoding marker and not a character of the document.
_UTF8_BOM: Final = b"\xef\xbb\xbf"

#: Leading bytes that identify content as something other than the text it is
#: labelled as. Not an attempt at general type detection: each entry is a
#: well-known magic number, and matching one means the declared media type and
#: the bytes disagree, which is a section 12 trigger in its own right and a more
#: precise answer than "malformed".
#:
#: The two UTF-16 byte-order marks are here rather than under malformed input for
#: the same reason: text in another encoding is a media-type conflict, not
#: damaged UTF-8, and a caller told the difference can act on it.
_BINARY_SIGNATURES: Final = (
    b"%PDF-",
    b"PK\x03\x04",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF8",
    b"\x1f\x8b",
    b"\xfe\xff",
    b"\xff\xfe",
)

#: Longest UTF-8 sequence, and therefore the furthest back a truncated read can
#: have cut one.
_MAX_UTF8_SEQUENCE: Final = 4


class ExtractionStatus(StrEnum):
    """What happened to one object. Distinct outcomes, never an empty string."""

    EXTRACTED = "extracted"
    UNSUPPORTED = "unsupported"
    QUARANTINED = "quarantined"


@dataclass(frozen=True, slots=True, repr=False)
class ExtractionOutcome:
    """One object's extraction result, bound to the version it was read from.

    The invariants below are what keep the three outcomes from blurring: text
    exists exactly when something was extracted, a reason exists exactly when
    something was quarantined, and a quarantined outcome carries no text at all,
    so a caller that persists outcomes indiscriminately still cannot store a
    payload against a quarantine.
    """

    status: ExtractionStatus
    provenance: Provenance
    media_type: str | None
    text: str | None = None
    is_truncated: bool = False
    quarantine_reason: QuarantineReason | None = None

    def __post_init__(self) -> None:
        if self.provenance.trust_level is not TrustLevel.SOURCE_BOUND_DERIVED:
            raise ValueError("derived text is source-bound derived, never source original")
        if self.status is ExtractionStatus.EXTRACTED:
            if self.text is None:
                raise ValueError("an extracted outcome carries text")
            if self.media_type not in SUPPORTED_MEDIA_TYPES:
                raise ValueError("an extracted outcome names a supported media type")
        elif self.text is not None:
            raise ValueError(f"a {self.status} outcome carries no text")
        if (self.quarantine_reason is not None) != (self.status is ExtractionStatus.QUARANTINED):
            raise ValueError("a reason accompanies a quarantined outcome and only that")

    @property
    def character_count(self) -> int:
        """Characters extracted; zero when nothing was."""
        return 0 if self.text is None else len(self.text)

    def __repr__(self) -> str:
        """Report the shape of the outcome, never the text.

        Extracted text is personal data by default (`AGENTS.md` section 5), and
        the default dataclass `repr` would put it into any log line, assertion
        message, or debugger frame that touched an outcome. The length is
        disclosed because it is a count, which section 13 permits.
        """
        reason = None if self.quarantine_reason is None else self.quarantine_reason.value
        return (
            f"ExtractionOutcome(status={self.status.value}, "
            f"media_type={self.media_type!r}, characters={self.character_count}, "
            f"is_truncated={self.is_truncated}, quarantine_reason={reason}, "
            f"version_id={self.provenance.version_id})"
        )


def _drop_incomplete_tail(content: bytes) -> bytes:
    """Drop a trailing UTF-8 sequence the read cut in half.

    Only ever called for a read the provider reported as truncated. A bounded
    read that stops mid-character leaves bytes that are not a valid encoding of
    anything, and quarantining that would report a defect in the document when
    the only thing that happened is that the caller asked for fewer bytes than
    the document has. At most three bytes are removed, so this cannot swallow
    content.
    """
    for back in range(1, min(_MAX_UTF8_SEQUENCE, len(content)) + 1):
        byte = content[-back]
        if byte < 0x80:
            # A complete single-byte character: nothing after it is incomplete.
            return content
        if byte >= 0xC0:
            width = 2 if byte < 0xE0 else 3 if byte < 0xF0 else 4
            return content[:-back] if back < width else content
        # A continuation byte; keep walking back to its lead byte.
    return content


def _conflicting_signature(content: bytes) -> bool:
    return any(content.startswith(signature) for signature in _BINARY_SIGNATURES)


def extract_text(
    *,
    source_id: str,
    source_object_id: str,
    observed_version_id: str,
    content_version_id: str,
    media_type: str | None,
    content: bytes,
    observed_at: datetime,
    processed_at: datetime | None = None,
    is_truncated: bool = False,
    max_characters: int = MAX_EXTRACTED_CHARACTERS,
) -> ExtractionOutcome:
    """Decode `content` as text, or say explicitly why it is not text.

    The two version parameters are separate on purpose: `observed_version_id` is
    what the caller asked about and `content_version_id` is what the provider
    returned. Collapsing them would remove the only evidence that the output
    belongs to a different observation than the one it would be filed under.

    Never raises for bad content. A caller that had to catch an exception to
    learn that a document was unreadable would be one `except` clause away from
    turning a quarantine into a skip.
    """
    validate_identifier(source_id, IdKind.SOURCE)
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
    validate_identifier(observed_version_id, IdKind.VERSION)
    validate_identifier(content_version_id, IdKind.VERSION)
    if max_characters < 1:
        raise ValueError("max_characters must be at least 1")

    provenance = Provenance(
        source_id=source_id,
        source_object_id=source_object_id,
        version_id=observed_version_id,
        extractor=EXTRACTOR,
        extractor_version=EXTRACTOR_VERSION,
        observed_at=ensure_utc(observed_at),
        processed_at=utc_now() if processed_at is None else ensure_utc(processed_at),
        trust_level=TrustLevel.SOURCE_BOUND_DERIVED,
    )

    def quarantined(reason: QuarantineReason) -> ExtractionOutcome:
        return ExtractionOutcome(
            status=ExtractionStatus.QUARANTINED,
            provenance=provenance,
            media_type=media_type,
            quarantine_reason=reason,
        )

    if content_version_id != observed_version_id:
        return quarantined(QuarantineReason.OUTPUT_NOT_ATTRIBUTABLE_TO_VERSION)

    if media_type not in SUPPORTED_MEDIA_TYPES:
        # Reported, not skipped, and not coerced into text. `application/pdf`
        # arrives here until `P00-OD-003` is resolved by the operator.
        return ExtractionOutcome(
            status=ExtractionStatus.UNSUPPORTED,
            provenance=provenance,
            media_type=media_type,
            is_truncated=is_truncated,
        )

    if _conflicting_signature(content):
        return quarantined(QuarantineReason.MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE)

    body = content.removeprefix(_UTF8_BOM)
    if is_truncated:
        body = _drop_incomplete_tail(body)
    if b"\x00" in body:
        # A NUL byte is legal UTF-8 and illegal in a document labelled as text.
        # It is the cheapest evidence that the bytes are not what the media type
        # claims, and it is checked before decoding because decoding would
        # succeed and hand back a string with a NUL in it.
        return quarantined(QuarantineReason.MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE)

    try:
        decoded = body.decode("utf-8")
    except UnicodeDecodeError:
        # Deliberately no fallback encoding and no `errors="replace"`. Guessing
        # an encoding, or substituting replacement characters, would produce
        # text that looks extracted and is not attributable to the bytes.
        return quarantined(QuarantineReason.MALFORMED_INPUT)

    if len(decoded) > max_characters:
        return quarantined(QuarantineReason.RESOURCE_LIMIT_EXCEEDED)

    return ExtractionOutcome(
        status=ExtractionStatus.EXTRACTED,
        provenance=provenance,
        media_type=media_type,
        text=decoded,
        is_truncated=is_truncated,
    )
