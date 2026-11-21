"""Searchable-text derivation `comms_search_text_v1` (pure, standard library only).

**Basis, in order of preference** (`derive_search_text`):

1. a withheld body (privacy screen) or a withheld unique body yields **no text**
   (`withheld`, `metadata_only`): the message is indexed by metadata only;
2. a truncated body (`truncated_unknown` completeness) yields **no text**
   (`truncated`, `metadata_only`): a partial body is not presented as the message;
3. `unique_body` when present and non-empty (the provider's own "new content
   only" body), converted html->text or passed through;
4. the producer's derived plain text when it is non-empty, marked derived, and
   its declared SHA-256 verified (`ProducerDerivedText.usable`); text without a
   declared digest is not used, because then it cannot be shown to come from
   this body;
5. otherwise the stored `body.content`, converted html->text or passed through;
6. an empty result yields no text (`empty`, `metadata_only`).

**Then** quoted reply chains are cut and signature/disclaimer blocks removed
(`strip_quoted_chain`, `strip_disclaimer`), so thread repetition does not
dominate ranking.

**Quoted-chain markers** (a cut at the first one; everything after it goes):
a `-----Original Message-----` line; an `On ... wrote:` line (or `On ...`
followed by a line ending in `wrote:`); a `From:` line followed within six
lines by at least two of `Sent:`/`Date:`/`To:`/`Cc:`/`Subject:` (an underscore
rule directly above it goes too). Every remaining line starting with `>` is
dropped. If cutting would leave no text at all (a bare forward), the
unstripped text is kept and flagged `quoted_chain_retained`.

**Disclaimer / signature markers** (heuristic; a cut from the start of the
paragraph holding the first marker to the end, never leaving the text empty):
a signature delimiter line `--`/`-- `; a line starting `Disclaimer`;
`confidentiality notice`; `if you are not the intended recipient`;
`if you have received this (e-mail|email|message|communication) in error`;
`this (e-mail|email|message|communication|transmission) ... confidential|privileged`
within one line.

**Content is inert data.** HTML is parsed with `html.parser` and only text
nodes are kept: no attribute value (an `onerror=`, a `javascript:` href, a
`src`) is ever output, comments and processing instructions are dropped, and
the contents of `script`, `style`, `head`, `title`, `noscript`, `template`,
`iframe`, `object`, `svg` and `math` are dropped (`markup_dropped`).
`blockquote` contents are quoted material and are dropped as a quoted chain.
Prompt-injection-like text is ordinary text: it is never evaluated or followed.
Output is capped at `MAX_SEARCH_TEXT_CHARS` (`text_capped`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from typing import Final

from my_pa.domain.communications.model import BodyState, ContentType, NormalizedMessage

__all__ = [
    "MAX_SEARCH_TEXT_CHARS",
    "SEARCH_TEXT_VERSION",
    "SearchText",
    "SearchTextBasis",
    "SearchTextFlag",
    "derive_search_text",
    "html_to_text",
    "normalize_plain_text",
    "strip_disclaimer",
    "strip_quoted_chain",
]

SEARCH_TEXT_VERSION: Final = "comms_search_text_v1"
MAX_SEARCH_TEXT_CHARS: Final = 262_144


class SearchTextBasis(StrEnum):
    UNIQUE_BODY = "unique_body"
    PRODUCER_DERIVED_TEXT = "producer_derived_text"
    BODY_CONTENT = "body_content"
    NONE = "none"


class SearchTextFlag(StrEnum):
    QUOTED_CHAIN_REMOVED = "quoted_chain_removed"
    QUOTED_CHAIN_RETAINED = "quoted_chain_retained"
    DISCLAIMER_REMOVED = "disclaimer_removed"
    MARKUP_DROPPED = "markup_dropped"
    WITHHELD = "withheld"
    TRUNCATED = "truncated"
    EMPTY = "empty"
    METADATA_ONLY = "metadata_only"
    TEXT_CAPPED = "text_capped"


@dataclass(frozen=True, slots=True)
class SearchText:
    version: str
    basis: SearchTextBasis
    text: str | None
    flags: frozenset[SearchTextFlag]


_DROP_CONTENT: Final = frozenset(
    {"script", "style", "head", "title", "noscript", "template", "iframe", "object", "svg", "math"}
)
_BLOCK: Final = frozenset(
    {
        "address", "article", "br", "dd", "div", "dl", "dt", "footer", "h1", "h2", "h3",
        "h4", "h5", "h6", "header", "hr", "li", "ol", "p", "pre", "section", "table",
        "tbody", "thead", "tfoot", "tr", "ul",
    }
)  # fmt: skip
_CELL: Final = frozenset({"td", "th"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.drop_depth = 0
        self.quote_depth = 0
        self.dropped_markup = False
        self.dropped_quote = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # `attrs` is deliberately never read: no attribute value is ever output.
        if tag in _DROP_CONTENT:
            self.drop_depth += 1
            self.dropped_markup = True
        elif tag == "blockquote":
            self.quote_depth += 1
            self.parts.append("\n")
        elif tag in _BLOCK:
            self.parts.append("\n")
        elif tag in _CELL:
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _DROP_CONTENT:
            self.drop_depth = max(0, self.drop_depth - 1)
        elif tag == "blockquote":
            self.quote_depth = max(0, self.quote_depth - 1)
            self.parts.append("\n")
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.drop_depth:
            return
        if self.quote_depth:
            if data.strip():
                self.dropped_quote = True
            return
        self.parts.append(data)


def html_to_text(html: str) -> tuple[str, bool, bool]:
    """Text nodes of `html`, normalized. Returns `(text, markup_dropped, quote_dropped)`."""
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    return (
        normalize_plain_text("".join(extractor.parts)),
        extractor.dropped_markup,
        extractor.dropped_quote,
    )


_INLINE_SPACE: Final = re.compile("[ \t\f\v\u00a0\u2000-\u200b\u202f\u205f\u3000\ufeff]+")
_BLANK_RUN: Final = re.compile(r"\n{3,}")


def normalize_plain_text(text: str) -> str:
    """Unify newlines, collapse inline whitespace, trim lines, and collapse blank runs."""
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_INLINE_SPACE.sub(" ", line).strip() for line in unified.split("\n")]
    return _BLANK_RUN.sub("\n\n", "\n".join(lines)).strip()


_ORIGINAL_MESSAGE: Final = re.compile(r"-{2,}\s*original message\s*-{2,}", re.I)
_ON_WROTE: Final = re.compile(r"on\b.{1,300}\bwrote:", re.I)
_ON_START: Final = re.compile(r"on\s", re.I)
_WROTE_END: Final = re.compile(r".*\bwrote:", re.I)
_HEADER_FROM: Final = re.compile(r"from:\s*\S", re.I)
_HEADER_OTHER: Final = re.compile(r"(sent|date|to|cc|subject):", re.I)
_UNDERSCORE_RULE: Final = re.compile(r"_{5,}")
_QUOTED_LINE: Final = re.compile(r"\s*>")
_HEADER_LOOKAHEAD: Final = 6


def _quoted_chain_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if _ORIGINAL_MESSAGE.fullmatch(line) or _ON_WROTE.fullmatch(line):
            return index
        if (
            _ON_START.match(line)
            and index + 1 < len(lines)
            and _WROTE_END.fullmatch(lines[index + 1])
            and len(line) + len(lines[index + 1]) <= 300
        ):
            return index
        if _HEADER_FROM.match(line):
            following = lines[index + 1 : index + 1 + _HEADER_LOOKAHEAD]
            if sum(1 for other in following if _HEADER_OTHER.match(other)) >= 2:
                if index > 0 and _UNDERSCORE_RULE.fullmatch(lines[index - 1]):
                    return index - 1
                return index
    return None


def strip_quoted_chain(text: str) -> tuple[str, SearchTextFlag | None]:
    """Cut the first quoted-chain marker onward and drop `>` lines (see module docstring)."""
    lines = text.split("\n")
    start = _quoted_chain_start(lines)
    kept = lines if start is None else lines[:start]
    unquoted = [line for line in kept if not _QUOTED_LINE.match(line)]
    if len(unquoted) == len(lines):
        return text, None
    result = normalize_plain_text("\n".join(unquoted))
    if not result:
        return text, SearchTextFlag.QUOTED_CHAIN_RETAINED
    return result, SearchTextFlag.QUOTED_CHAIN_REMOVED


_SIGNATURE_DELIMITER: Final = re.compile(r"--\s?")
_DISCLAIMER_MARKERS: Final = (
    re.compile(r"disclaimer\b", re.I),
    re.compile(r".*\bconfidentiality notice\b", re.I),
    re.compile(r".*\bif you are not the intended recipient\b", re.I),
    re.compile(r".*\bif you have received this (?:e-?mail|message|communication) in error\b", re.I),
    re.compile(
        r".*\bthis (?:e-?mail|message|communication|transmission)\b"
        r".*\b(?:confidential|privileged)\b",
        re.I,
    ),
)


def strip_disclaimer(text: str) -> tuple[str, bool]:
    """Cut from the paragraph holding the first disclaimer/signature marker to the end."""
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not any(part.strip() for part in lines[:index]):
            continue
        if _SIGNATURE_DELIMITER.fullmatch(line):
            cut = index
        elif any(marker.match(line) for marker in _DISCLAIMER_MARKERS):
            cut = index
            while cut > 0 and lines[cut - 1].strip():
                cut -= 1
            if not any(part.strip() for part in lines[:cut]):
                cut = index
        else:
            continue
        return normalize_plain_text("\n".join(lines[:cut])), True
    return text, False


def _metadata_only(*flags: SearchTextFlag) -> SearchText:
    return SearchText(
        SEARCH_TEXT_VERSION,
        SearchTextBasis.NONE,
        None,
        frozenset({*flags, SearchTextFlag.METADATA_ONLY}),
    )


def _to_text(content: str, content_type: ContentType, flags: set[SearchTextFlag]) -> str:
    if content_type is ContentType.TEXT:
        return normalize_plain_text(content)
    text, markup_dropped, quote_dropped = html_to_text(content)
    if markup_dropped:
        flags.add(SearchTextFlag.MARKUP_DROPPED)
    if quote_dropped:
        flags.add(SearchTextFlag.QUOTED_CHAIN_REMOVED)
    return text


def derive_search_text(message: NormalizedMessage) -> SearchText:
    """The `comms_search_text_v1` text for one normalized message (module docstring)."""
    body, unique = message.body, message.unique_body
    if body.state is BodyState.WITHHELD or (
        unique is not None and unique.state is BodyState.WITHHELD
    ):
        return _metadata_only(SearchTextFlag.WITHHELD)
    if body.state is BodyState.TRUNCATED:
        return _metadata_only(SearchTextFlag.TRUNCATED)

    flags: set[SearchTextFlag] = set()
    derived = message.derived_text
    if unique is not None and unique.state is BodyState.PRESENT and unique.content:
        basis = SearchTextBasis.UNIQUE_BODY
        text = _to_text(unique.content, unique.content_type, flags)
    elif derived is not None and derived.usable and derived.text:
        basis = SearchTextBasis.PRODUCER_DERIVED_TEXT
        text = normalize_plain_text(derived.text)
    elif body.state is BodyState.PRESENT and body.content:
        basis = SearchTextBasis.BODY_CONTENT
        text = _to_text(body.content, body.content_type, flags)
    else:
        return _metadata_only(SearchTextFlag.EMPTY)

    text, quote_flag = strip_quoted_chain(text)
    if quote_flag is not None:
        flags.add(quote_flag)
    text, disclaimer_removed = strip_disclaimer(text)
    if disclaimer_removed:
        flags.add(SearchTextFlag.DISCLAIMER_REMOVED)
    if not text:
        return _metadata_only(SearchTextFlag.EMPTY, *flags)
    if len(text) > MAX_SEARCH_TEXT_CHARS:
        text = text[:MAX_SEARCH_TEXT_CHARS]
        flags.add(SearchTextFlag.TEXT_CAPPED)
    return SearchText(SEARCH_TEXT_VERSION, basis, text, frozenset(flags))
