"""Searchable-text derivation `comms_search_text_v2` (pure, standard library only).

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

* the RFC 3676 signature delimiter: a line that is exactly `-- ` (dash, dash,
  space -- `normalize_plain_text` keeps that one line's trailing space) with at
  most `SIGNATURE_TAIL_LINES` non-blank lines after it; the cut is at the
  delimiter itself. A bare `--` line is ordinary text;
* a *paragraph-start* line in the *trailing region* that starts with
  `disclaimer`, `if you have received this (e-mail|email|message|communication)
  in error`, `confidentiality notice` or `if you are not the intended
  recipient`, or with
  `this` / `the information (contained) in this`, then
  `e-mail|email|message|communication|transmission`, then
  `confidential|privileged` within the line. The trailing region is at most
  `SIGNATURE_TAIL_LINES` non-blank lines from that line to the end. A line
  starts a paragraph when the line above it is blank, or is a signature break
  that itself lies in the trailing region -- exactly `-- `, or a rule of five
  or more `-`. Nothing else is a break (not a bare `--`, not an `_` rule), and a
  break earlier in the text never lifts the trailing-region limit. When the
  marker line sits directly under a break, the cut is at the break line itself
  (as for `-- `), so the body paragraph above the break is kept. A
  mid-paragraph sentence such as "... this message includes confidential
  pricing ..." or "If you are not the intended recipient of the GMP, tell me"
  directly under a greeting never truncates body text.

**Version.** `comms_search_text_v2` (communications WP4, contract section 6)
anchors the two markers v1 honoured on *any* line -- a line starting
`Disclaimer`, and a line holding `if you have received this ... in error`
anywhere -- to the trailing-paragraph rule above; v1 cut a whole body at a
mid-body "Disclaimer language for the contract ..." line. Nothing else moved:
v2's candidate cut lines are a subset of v1's and the cut placement is the
same, so the v1 text of a message is always a prefix of its v2 text and
neither ever cuts to empty (the projection-selection key is unchanged).
`derive_search_text_v1` keeps v1 callable for the measurement and that
property test; ingestion writes v2 only.

The v1 rules were pre-merge corrections of `comms_search_text_v1`
(WP1 fix F1 after review R1, fix F2 after review R2, and fix F3 after review
R3): the identifier stays `v1` because no searchable text has been persisted
or published under it, so no stored output changes meaning. Corpus counts
measured before a correction (spec §7: `ac0d06ae` before F1, `184ac6ca` before
F2) used the earlier, broader markers. F3 moves only where a cut under a break
falls, never whether a cut happens, so it does not change `disclaimer_removed`
counts.

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
    "SEARCH_TEXT_VERSION_V1",
    "SEARCH_TEXT_VERSION_V2",
    "SIGNATURE_TAIL_LINES",
    "SearchText",
    "SearchTextBasis",
    "SearchTextFlag",
    "derive_search_text",
    "derive_search_text_v1",
    "html_to_text",
    "normalize_plain_text",
    "strip_disclaimer",
    "strip_quoted_chain",
    "unstripped_text",
]

SEARCH_TEXT_VERSION_V1: Final = "comms_search_text_v1"
SEARCH_TEXT_VERSION_V2: Final = "comms_search_text_v2"
#: The version ingestion and rederive write (WP4 ruling R10: the current one only).
SEARCH_TEXT_VERSION: Final = SEARCH_TEXT_VERSION_V2
#: The RFC 3676 signature delimiter line (`-- `, with its trailing space).
_SIGNATURE_DELIMITER: Final = "-- "
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
    """Unify newlines, collapse inline whitespace, trim lines, and collapse blank runs.

    A line that is exactly `-- ` (the RFC 3676 signature delimiter) is kept as is.
    """
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [
        # The RFC 3676 signature delimiter `-- ` keeps its significant space.
        _SIGNATURE_DELIMITER
        if line == _SIGNATURE_DELIMITER
        else _INLINE_SPACE.sub(" ", line).strip()
        for line in unified.split("\n")
    ]
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


#: A signature delimiter, a break, or a trailing-paragraph marker counts only
#: when at most this many non-blank lines follow from it to the end of the text.
SIGNATURE_TAIL_LINES: Final = 15
#: A signature break: the RFC 3676 delimiter or a rule of five or more dashes.
_SIGNATURE_BREAK: Final = re.compile(r"-- |-{5,}")
#: `comms_search_text_v1` only: markers that count on any line, wherever it sits.
_V1_LINE_MARKERS: Final = (
    re.compile(r"disclaimer\b", re.I),
    re.compile(r".*\bif you have received this (?:e-?mail|message|communication) in error\b", re.I),
)
#: Markers that count only on a paragraph-start line in the trailing region (v1).
_V1_TAIL_PARAGRAPH_MARKERS: Final = (
    re.compile(r"confidentiality notice\b", re.I),
    re.compile(r"if you are not the intended recipient\b", re.I),
    re.compile(
        r"(?:this|the information (?:contained )?in this) "
        r"(?:e-?mail|message|communication|transmission)\b"
        r".*\b(?:confidential|privileged)\b",
        re.I,
    ),
)
#: `comms_search_text_v2` (WP4, contract section 6): no marker counts on any
#: line. The two v1 line markers are anchored like the others -- a
#: paragraph-start line in the trailing region -- and the in-error marker must
#: start that line (no leading `.*`). Their phrases are not widened.
_V2_LINE_MARKERS: Final[tuple[re.Pattern[str], ...]] = ()
_V2_TAIL_PARAGRAPH_MARKERS: Final = (
    *_V1_TAIL_PARAGRAPH_MARKERS,
    re.compile(r"disclaimer\b", re.I),
    re.compile(r"if you have received this (?:e-?mail|message|communication) in error\b", re.I),
)
#: Version -> (any-line markers, trailing-paragraph markers).
_MARKERS: Final = {
    SEARCH_TEXT_VERSION_V1: (_V1_LINE_MARKERS, _V1_TAIL_PARAGRAPH_MARKERS),
    SEARCH_TEXT_VERSION_V2: (_V2_LINE_MARKERS, _V2_TAIL_PARAGRAPH_MARKERS),
}


def _in_tail(lines: list[str], index: int) -> bool:
    return sum(1 for line in lines[index:] if line.strip()) <= SIGNATURE_TAIL_LINES


def _starts_paragraph(lines: list[str], index: int) -> bool:
    """The line above is blank, or is a signature break lying in the trailing region."""
    above = lines[index - 1]
    if not above.strip():
        return True
    return _SIGNATURE_BREAK.fullmatch(above) is not None and _in_tail(lines, index - 1)


def _is_disclaimer_start(lines: list[str], index: int, version: str) -> bool:
    line_markers, tail_markers = _MARKERS[version]
    line = lines[index]
    if any(marker.match(line) for marker in line_markers):
        return True
    return (
        any(marker.match(line) for marker in tail_markers)
        and _in_tail(lines, index)
        and _starts_paragraph(lines, index)
    )


def strip_disclaimer(text: str, *, version: str = SEARCH_TEXT_VERSION) -> tuple[str, bool]:
    """Cut from the paragraph holding the first disclaimer/signature marker to the end.

    `version` selects the marker set (`comms_search_text_v1` or `_v2`); the cut
    placement is the same in both.
    """
    if version not in _MARKERS:
        raise ValueError("unknown search text version")
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if not any(part.strip() for part in lines[:index]):
            continue
        if line == _SIGNATURE_DELIMITER and _in_tail(lines, index + 1):
            cut = index
        elif _is_disclaimer_start(lines, index, version):
            cut = index
            if _SIGNATURE_BREAK.fullmatch(lines[index - 1]):
                # The paragraph starts under a break: cut at the break itself,
                # never through it into the body paragraph above (review R3-1).
                cut = index - 1
            else:
                while cut > 0 and lines[cut - 1].strip():
                    cut -= 1
            if not any(part.strip() for part in lines[:cut]):
                cut = index
        else:
            continue
        return normalize_plain_text("\n".join(lines[:cut])), True
    return text, False


def _metadata_only(version: str, *flags: SearchTextFlag) -> SearchText:
    return SearchText(
        version,
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


def _basis_text(
    message: NormalizedMessage, version: str, flags: set[SearchTextFlag]
) -> SearchText | tuple[SearchTextBasis, str]:
    """The chosen basis and its text before any cut, or the metadata-only result."""
    body, unique = message.body, message.unique_body
    if body.state is BodyState.WITHHELD or (
        unique is not None and unique.state is BodyState.WITHHELD
    ):
        return _metadata_only(version, SearchTextFlag.WITHHELD)
    if body.state is BodyState.TRUNCATED:
        return _metadata_only(version, SearchTextFlag.TRUNCATED)
    derived = message.derived_text
    if unique is not None and unique.state is BodyState.PRESENT and unique.content:
        return SearchTextBasis.UNIQUE_BODY, _to_text(unique.content, unique.content_type, flags)
    if derived is not None and derived.usable and derived.text:
        return SearchTextBasis.PRODUCER_DERIVED_TEXT, normalize_plain_text(derived.text)
    if body.state is BodyState.PRESENT and body.content:
        return SearchTextBasis.BODY_CONTENT, _to_text(body.content, body.content_type, flags)
    return _metadata_only(version, SearchTextFlag.EMPTY)


def unstripped_text(message: NormalizedMessage) -> str | None:
    """The basis text before the quoted chain and disclaimer are cut; `None` without one.

    For the counts-only identifier measurement (`measurement.py`), which asks how
    many identifiers live only in quoted or trailing text. Never stored.
    """
    selected = _basis_text(message, SEARCH_TEXT_VERSION, set())
    return None if isinstance(selected, SearchText) else selected[1]


def derive_search_text(
    message: NormalizedMessage, *, version: str = SEARCH_TEXT_VERSION
) -> SearchText:
    """The searchable text for one normalized message (module docstring).

    `version` is the current `comms_search_text_v2` unless a caller names
    `comms_search_text_v1`, which only the measurement and the prefix property
    test do (`derive_search_text_v1`); ingestion writes the current version only.
    """
    if version not in _MARKERS:
        raise ValueError("unknown search text version")
    flags: set[SearchTextFlag] = set()
    selected = _basis_text(message, version, flags)
    if isinstance(selected, SearchText):
        return selected
    basis, text = selected
    text, quote_flag = strip_quoted_chain(text)
    if quote_flag is not None:
        flags.add(quote_flag)
    text, disclaimer_removed = strip_disclaimer(text, version=version)
    if disclaimer_removed:
        flags.add(SearchTextFlag.DISCLAIMER_REMOVED)
    if not text:
        return _metadata_only(version, SearchTextFlag.EMPTY, *flags)
    if len(text) > MAX_SEARCH_TEXT_CHARS:
        text = text[:MAX_SEARCH_TEXT_CHARS]
        flags.add(SearchTextFlag.TEXT_CAPPED)
    return SearchText(version, basis, text, frozenset(flags))


def derive_search_text_v1(message: NormalizedMessage) -> SearchText:
    """The frozen `comms_search_text_v1` text: for the measurement and the prefix property only."""
    return derive_search_text(message, version=SEARCH_TEXT_VERSION_V1)
