"""The Meeting context inputs: the pure half of `meetings.context.read` (WP5).

What a Meeting contributes to its communications context, decided without IO
(WP5-W1 design report sections 3.4 and 3.10; Manager rulings D4, D13, D14):

* **the bounds** of a request: at most `MAX_CONTEXT_MEETINGS` Meetings, a
  lookback of 1..`MAX_LOOKBACK_DAYS` days (default 14) and 1..`MAX_PER_MEETING_LIMIT`
  messages per Meeting (default 15);
* **the lookback window** (`lookback_window`): `[floor_s(start_at) - lookback,
  min(floor_s(start_at), floor_s(now))]`, inclusive at both ends and in whole
  seconds. An upcoming Meeting's window is clipped at the read instant, so the
  future never reads as a coverage gap (`clipped_to_now`);
* **the title terms** (`title_terms`, rule `meeting_title_terms_v1`): the
  title's words, case-folded, minus the closed `GENERIC_MEETING_TERMS`, minus
  the PostgreSQL `english` stop words (`ENGLISH_STOP_WORDS`, a byte copy of
  `tsearch_data/english.stop`, so a dropped word is exactly one the server would
  drop) and minus pure numbers; distinct, in first-occurrence order, at most
  `MAX_TITLE_TERMS`. Title terms are always a criterion, as the lowest tier
  (D13);
* **the identifier inputs** (`select_context_identifiers`): the technical
  identifiers in the title, the prep head, the note head and the description
  (contract section 15, and the description by ruling Q2), each field scanned
  only to its first `IDENTIFIER_SCAN_CHARACTERS` characters (D14, stated by
  `scan_truncated`). The bare project-wide kinds `gmp` and `fpl` are never
  context inputs (D4). They are ordered by their first source (title, prep,
  notes, description), then `(kind, value)`, and at most
  `MAX_CONTEXT_IDENTIFIERS` are kept.

Pure: no IO, no clock (`now` is a parameter), no persistence.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IdentifierKind,
    TechnicalIdentifier,
    extract_identifiers,
)

__all__ = [
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_PER_MEETING_LIMIT",
    "ENGLISH_STOP_WORDS",
    "EXCLUDED_IDENTIFIER_KINDS",
    "GENERIC_MEETING_TERMS",
    "IDENTIFIER_SCAN_CHARACTERS",
    "MAX_CONTEXT_IDENTIFIERS",
    "MAX_CONTEXT_MEETINGS",
    "MAX_LOOKBACK_DAYS",
    "MAX_PER_MEETING_LIMIT",
    "MAX_TITLE_TERMS",
    "TITLE_TERMS_RULE",
    "ContextIdentifier",
    "ContextIdentifiers",
    "ContextText",
    "ContextTextSource",
    "ContextWindow",
    "lookback_window",
    "select_context_identifiers",
    "title_terms",
]

# --------------------------------------------------------------------- bounds

#: Meetings per request (ruling D9: the contract value; the latency test also records 25).
MAX_CONTEXT_MEETINGS: Final = 10
DEFAULT_LOOKBACK_DAYS: Final = 14
MAX_LOOKBACK_DAYS: Final = 90
DEFAULT_PER_MEETING_LIMIT: Final = 15
MAX_PER_MEETING_LIMIT: Final = 50
#: Characters of each text field scanned for identifiers (ruling D14).
IDENTIFIER_SCAN_CHARACTERS: Final = 20_000
#: Identifier inputs per Meeting.
MAX_CONTEXT_IDENTIFIERS: Final = 20
#: Title terms per Meeting.
MAX_TITLE_TERMS: Final = 8

# --------------------------------------------------------------------- window

_SECOND: Final = timedelta(seconds=1)


def _floor_second(instant: datetime) -> datetime:
    return instant.replace(microsecond=0)


@dataclass(frozen=True, slots=True)
class ContextWindow:
    """One Meeting's lookback window, inclusive at both ends, in whole seconds."""

    start: datetime
    end: datetime
    clipped_to_now: bool


def lookback_window(start_at: datetime, lookback_days: int, now: datetime) -> ContextWindow:
    """The window of the `lookback_days` days before the Meeting starts, clipped at `now`.

    A Meeting that starts after `now` ends its window at `floor_s(now)`
    (`clipped_to_now`). One that starts more than the lookback after `now` has
    nothing before it yet: its window is the single instant `floor_s(now)`,
    never an inverted range.
    """
    if not 1 <= lookback_days <= MAX_LOOKBACK_DAYS:
        raise ValueError("lookback_days is out of bounds")
    anchor = _floor_second(start_at)
    read_at = _floor_second(now)
    end = min(anchor, read_at)
    start = min(anchor - timedelta(days=lookback_days), end)
    return ContextWindow(start=start, end=end, clipped_to_now=read_at < anchor)


# ---------------------------------------------------------------- title terms

#: The versioned title-terms rule an answer states (`versions.title_terms_rule`).
TITLE_TERMS_RULE: Final = "meeting_title_terms_v1"

#: Words that name the kind of meeting, not its subject (design section 3.10).
#: Closed and versioned with `TITLE_TERMS_RULE`.
GENERIC_MEETING_TERMS: Final = frozenset(
    {
        "agenda",
        "biweekly",
        "call",
        "catchup",
        "check",
        "checkin",
        "daily",
        "discussion",
        "external",
        "internal",
        "invite",
        "meeting",
        "meetings",
        "minutes",
        "monthly",
        "prep",
        "project",
        "recurring",
        "review",
        "standup",
        "status",
        "sync",
        "team",
        "teams",
        "touchbase",
        "update",
        "weekly",
        "zoom",
    }
)

#: The words of PostgreSQL 15's `tsearch_data/english.stop` (127): what
#: `to_tsvector('english', ...)` drops. Versioned with `TITLE_TERMS_RULE`.
ENGLISH_STOP_WORDS: Final = frozenset(
    (
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "yourself",
        "yourselves",
        "he",
        "him",
        "his",
        "himself",
        "she",
        "her",
        "hers",
        "herself",
        "it",
        "its",
        "itself",
        "they",
        "them",
        "their",
        "theirs",
        "themselves",
        "what",
        "which",
        "who",
        "whom",
        "this",
        "that",
        "these",
        "those",
        "am",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "a",
        "an",
        "the",
        "and",
        "but",
        "if",
        "or",
        "because",
        "as",
        "until",
        "while",
        "of",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "to",
        "from",
        "up",
        "down",
        "in",
        "out",
        "on",
        "off",
        "over",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "s",
        "t",
        "can",
        "will",
        "just",
        "don",
        "should",
        "now",
    )
)

_WORD: Final = re.compile(r"[^\W_]+")


def title_terms(title: str) -> tuple[str, ...]:
    """The subject words of a Meeting title, at most `MAX_TITLE_TERMS` (rule v1)."""
    terms: list[str] = []
    for word in _WORD.findall(title.casefold()):
        if word.isdigit() or word in GENERIC_MEETING_TERMS or word in ENGLISH_STOP_WORDS:
            continue
        if word not in terms:
            terms.append(word)
            if len(terms) == MAX_TITLE_TERMS:
                break
    return tuple(terms)


# ---------------------------------------------------------------- identifiers


class ContextTextSource(StrEnum):
    """A Meeting text field scanned for identifiers, in the order they rank."""

    TITLE = "title"
    PREP = "prep"
    NOTES = "notes"
    DESCRIPTION = "description"


_SOURCE_ORDER: Final = tuple(ContextTextSource)

#: Project-wide kinds that would match most messages (ruling D4).
EXCLUDED_IDENTIFIER_KINDS: Final = frozenset({IdentifierKind.GMP, IdentifierKind.FPL})


@dataclass(frozen=True, slots=True)
class ContextText:
    """A text field as read for the identifier scan.

    `text` is at most `IDENTIFIER_SCAN_CHARACTERS` long when the reader caps it
    (`left(content, 20000)`); `truncated` says the stored field was longer.
    """

    text: str
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class ContextIdentifier:
    """One identifier input and the fields it was found in, in source order."""

    identifier: TechnicalIdentifier
    sources: tuple[ContextTextSource, ...]


@dataclass(frozen=True, slots=True)
class ContextIdentifiers:
    """A Meeting's identifier inputs and whether any field was scanned only in part."""

    identifiers: tuple[ContextIdentifier, ...]
    scan_truncated: bool


def select_context_identifiers(
    texts: Mapping[ContextTextSource, ContextText | None],
    *,
    version: str = IDENTIFIER_VERSION,
) -> ContextIdentifiers:
    """The identifier inputs of one Meeting (D4, D14; design section 3.4)."""
    found: dict[TechnicalIdentifier, list[ContextTextSource]] = {}
    truncated = False
    for source in _SOURCE_ORDER:
        text = texts.get(source)
        if text is None:
            continue
        scanned = text.text[:IDENTIFIER_SCAN_CHARACTERS]
        truncated = truncated or text.truncated or len(text.text) > IDENTIFIER_SCAN_CHARACTERS
        for identifier in extract_identifiers(scanned, version=version):
            if identifier.kind in EXCLUDED_IDENTIFIER_KINDS:
                continue
            found.setdefault(identifier, []).append(source)
    ranked = sorted(
        found.items(),
        key=lambda item: (_SOURCE_ORDER.index(item[1][0]), item[0].kind.value, item[0].value),
    )
    return ContextIdentifiers(
        identifiers=tuple(
            ContextIdentifier(identifier=identifier, sources=tuple(sources))
            for identifier, sources in ranked[:MAX_CONTEXT_IDENTIFIERS]
        ),
        scan_truncated=truncated,
    )
