"""The parts of a `communications.search` text query the application reads (WP4-S4).

Pure, standard library only. `websearch_to_tsquery` reads the query on the
server; two things are read here from the same websearch syntax:

* `quoted_phrases` -- the phrases the server reads as `"..."` segments, which
  the search confirms by exact substring (`strpos`, contract section 6) so that
  `"change orders"` does not match "changed ordering". A phrase negated with a
  leading `-` is excluded (it is not something a result contains). A quote left
  open runs to the end of the query, as on the server. An empty phrase is
  dropped.
* `unnegated_text` -- the query with every negated term (`-word`, `-"..."`)
  removed, the text whose identifiers are merged into the requested set (ruling
  R6): `-"RFI 12"` excludes, it does not ask.

A database-tier test pins the phrase parse against the server's.
"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["quoted_phrases", "unnegated_text"]

#: One websearch segment: an optional `-`, then a quoted phrase (closed, or
#: open to the end) or a bare word.
_SEGMENT: Final = re.compile(r'(?P<neg>-?)(?:"(?P<phrase>[^"]*)(?:"|\Z)|(?P<word>[^\s"]+))')
_SPACE: Final = re.compile(r"\s+")


def _segments(query: str) -> list[tuple[bool, str | None, str | None]]:
    found: list[tuple[bool, str | None, str | None]] = []
    position = 0
    while position < len(query):
        if query[position].isspace():
            position += 1
            continue
        match = _SEGMENT.match(query, position)
        if match is None:  # a lone quote character: skip it
            position += 1
            continue
        negated = match.group("neg") == "-" and (position == 0 or query[position - 1].isspace())
        found.append((negated, match.group("phrase"), match.group("word")))
        position = max(match.end(), position + 1)
    return found


def quoted_phrases(query: str) -> tuple[str, ...]:
    """The non-negated quoted phrases, whitespace-collapsed, in order, distinct."""
    phrases: list[str] = []
    for negated, phrase, _word in _segments(query):
        if negated or phrase is None:
            continue
        collapsed = _SPACE.sub(" ", phrase).strip()
        if collapsed and collapsed not in phrases:
            phrases.append(collapsed)
    return tuple(phrases)


def unnegated_text(query: str) -> str:
    """`query` without its negated terms and phrases, segments joined by a space."""
    kept: list[str] = []
    for negated, phrase, word in _segments(query):
        if negated:
            continue
        kept.append(phrase if phrase is not None else word or "")
    return " ".join(part for part in kept if part)
