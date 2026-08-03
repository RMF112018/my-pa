"""Exact, validated traces from a derived record back to the text it came from.

`docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md:167-185` calls this record
`EvidenceSpan` and `docs/specs/canonical-product-definition/
09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:67` calls it `SourceSpan`. The canonical
name is used here, on the ruling `docs/plans/mcv-completion-plan.md:920` makes
for state vocabularies — canonical over quick-capture where the two disagree.

**Offsets are code points, and the basis is stored rather than assumed.**
`10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:82` fixes the scheme name
`unicode_code_point_v1`. Python string indexing is already code-point indexing,
so `text[start:end]` *is* the quote — which is exactly why the basis has to be
recorded: a later reader in another language, or a repair script written against
UTF-8 byte offsets, would silently take a different substring of the same text.

**The quote is not stored, and that is what makes validation mean something.**
The spec's field list carries `quoted_text` beside `quoted_text_sha256`. Storing
both would make "validation re-derives the quoted text from the immutable source
version" (`09_LOGICAL_DATA_MODEL.md:185`) a comparison of one stored value
against another stored value, which passes whenever the two were written
together — including when both are wrong. Re-deriving from
`capture_versions.content`, which a `BEFORE UPDATE OR DELETE` trigger makes
immutable, is the only form of that check that can fail for the reason the
criterion names. It also keeps the schema's content columns enumerable: a
`quoted_text` column would be a fourth place a document body can sit.

**Line and column are stored as well as offsets**, because `10:84` requires
both. They are derived from the same text by `line_column_of` rather than
supplied, so they cannot disagree with the offsets beside them.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "MAX_MAPPING_VERSION_CHARACTERS",
    "OffsetBasis",
    "SourceSpan",
    "SpanError",
    "SpanRole",
    "line_column_of",
    "quote_of",
    "quoted_digest_of",
]

#: A mapping version is an opaque token naming which `P-02` normalization
#: produced the processing text a span was measured against. Bounded for the
#: reason `capture_submissions.request_id` is: an unbounded column a writer
#: controls is a payload channel whatever it is called.
MAX_MAPPING_VERSION_CHARACTERS: Final = 64


class SpanError(CaptureError):
    """A span could not be built, or does not re-derive against its version.

    Names the rule and never the text. A message quoting the substring that
    failed to match would put capture content into a traceback, which is the one
    thing `AGENTS.md` section 5 keeps out of logs.
    """


class OffsetBasis(StrEnum):
    """How a span's offsets are counted.

    One member, and it is the specification's own name rather than this
    repository's (`10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:82`). A second
    basis — UTF-8 bytes, UTF-16 units — is a different way of pointing at the
    same text, so the two could never be compared without knowing which was
    meant; recording the basis is what makes that knowable.
    """

    UNICODE_CODE_POINT_V1 = "unicode_code_point_v1"


class SpanRole(StrEnum):
    """What a span is evidence *for*.

    The three `09_LOGICAL_DATA_MODEL.md:184` names. `counterevidence` is the one
    that matters for honesty: a proposal that cites only the text supporting it
    is a proposal that has hidden the sentence contradicting it, and there is no
    way to record that objection without a role for it.
    """

    DIRECT = "direct"
    CONTEXT = "context"
    COUNTEREVIDENCE = "counterevidence"


def quote_of(text: str, *, start_offset: int, end_offset: int) -> str:
    """Return the code-point slice `[start_offset, end_offset)` of `text`.

    Raises rather than clamping. A slice past the end of a Python string returns
    a short string instead of failing, so a span written against a different
    version would silently quote whatever happened to be there — the laundering
    `AGENTS.md` section 5 forbids, in its quietest form.
    """
    if start_offset < 0:
        raise SpanError("a span starts at or after the beginning of the text")
    if end_offset <= start_offset:
        raise SpanError("a span ends after it starts")
    if end_offset > len(text):
        raise SpanError("a span ends at or before the end of the text")
    return text[start_offset:end_offset]


def quoted_digest_of(text: str, *, start_offset: int, end_offset: int) -> str:
    """The SHA-256 of the quoted slice's UTF-8 bytes, lowercase hexadecimal.

    The same function `domain.capture.version.digest_of` applies to a whole
    capture, applied to a part of one, so a span's digest and a version's digest
    are the same kind of value and can be compared with the same pattern.
    """
    quoted = quote_of(text, start_offset=start_offset, end_offset=end_offset)
    return hashlib.sha256(quoted.encode("utf-8")).hexdigest()


def line_column_of(text: str, offset: int) -> tuple[int, int]:
    """The one-based `(line, column)` of code-point `offset` in `text`.

    Lines are separated by `\\n`; a `\\r\\n` document has already been through
    `P-02`'s line-ending normalization by the time a span is measured against
    processing text, and an original-text span counts the `\\r` as a character
    on the line it ends, which is what a code-point offset means.
    """
    if offset < 0 or offset > len(text):
        raise SpanError("an offset lies inside the text it is measured against")
    prefix = text[:offset]
    line = prefix.count("\n") + 1
    column = offset - (prefix.rfind("\n") + 1) + 1
    return line, column


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """One exact, validated trace from a derived record to a capture version.

    Built by `over`, never by hand in a writer: the four line and column values
    are derived from the same text the offsets index, and the digest is derived
    from the same slice, so a span cannot be constructed whose parts disagree
    with each other. What it *can* still be is a span that disagrees with a
    *different* version's text, which is the failure `QC-AC-011` is about and
    which `re_derives_against` is the check for.
    """

    version_id: str
    start_offset: int
    end_offset: int
    offset_basis: OffsetBasis
    line_start: int
    column_start: int
    line_end: int
    column_end: int
    quoted_text_sha256: str
    span_role: SpanRole
    mapping_version: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        if self.start_offset < 0:
            raise SpanError("a span starts at or after the beginning of the text")
        if self.end_offset <= self.start_offset:
            raise SpanError("a span ends after it starts")
        for value in (self.line_start, self.column_start, self.line_end, self.column_end):
            if isinstance(value, bool) or value < 1:
                raise SpanError("line and column numbers start at one")
        if (self.line_end, self.column_end) <= (self.line_start, self.column_start):
            raise SpanError("a span ends after it starts")
        if self.mapping_version is not None and (
            not self.mapping_version or len(self.mapping_version) > MAX_MAPPING_VERSION_CHARACTERS
        ):
            raise SpanError("a mapping version is a bounded token")

    @property
    def character_count(self) -> int:
        """How many code points the span covers. A count, never the quote."""
        return self.end_offset - self.start_offset

    @classmethod
    def over(
        cls,
        text: str,
        *,
        version_id: str,
        start_offset: int,
        end_offset: int,
        span_role: SpanRole = SpanRole.DIRECT,
        mapping_version: str | None = None,
    ) -> SourceSpan:
        """The span covering `[start_offset, end_offset)` of `text`.

        `text` is the version's stored content — the thing offsets are counted
        in and the thing the digest is taken over. Passing processing text here
        and storing the result against a version would produce a span that
        cannot re-derive, which is why `mapping_version` exists: a span measured
        against processing text names the mapping that carries it back.
        """
        digest = quoted_digest_of(text, start_offset=start_offset, end_offset=end_offset)
        line_start, column_start = line_column_of(text, start_offset)
        line_end, column_end = line_column_of(text, end_offset)
        return cls(
            version_id=version_id,
            start_offset=start_offset,
            end_offset=end_offset,
            offset_basis=OffsetBasis.UNICODE_CODE_POINT_V1,
            line_start=line_start,
            column_start=column_start,
            line_end=line_end,
            column_end=column_end,
            quoted_text_sha256=digest,
            span_role=span_role,
            mapping_version=mapping_version,
        )

    def re_derives_against(self, content: str) -> bool:
        """Whether this span's digest is what `content` produces at its offsets.

        Returns `False` rather than raising for a span whose offsets fall
        outside `content`, because "this span does not belong to this version"
        and "this span's quote has changed" are the same answer to the caller
        and both quarantine the proposal that cites it
        (`09_LOGICAL_DATA_MODEL.md:185`). The distinction between them is
        recorded in the quarantine reason, not here.
        """
        try:
            derived = quoted_digest_of(
                content, start_offset=self.start_offset, end_offset=self.end_offset
            )
        except SpanError:
            return False
        return derived == self.quoted_text_sha256
