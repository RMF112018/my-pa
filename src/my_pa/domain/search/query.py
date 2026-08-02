"""The search query, its bounds, its cursor, and one result.

`docs/specs` section 9.7 gives this module one rule above all others: **the query
is data**. Nothing here builds SQL, and nothing here hands the query to anything
that could read it as syntax. What this module does is decide what a query *is*
before it becomes a bound parameter — which characters it may contain, how long
it may be, and what two spellings of the same query are.

**The query text is sensitive and this module is where that is enforced.**
Section 13 requires it kept out of default logs, and section 10 excludes it from
every error. Both are easy to promise and easy to lose to one `f"{request}"` in a
log line or one "rejected query {value}" in an exception, so `SearchQuery`
redacts itself: its `__repr__` reports a length and not a string, and every
error raised here names the rule that was broken and never the value that broke
it. `__str__` follows `__repr__` by Python's own fallback, so an f-string,
`print`, `logging`'s `%s`, and a dataclass that holds one all redact too. That is
the property worth having — not that callers remember, but that forgetting is
harmless.

**Normalization decides what "the same query" means.** Three things are folded,
and each is folded for a stated reason rather than for tidiness:

- **NFC**, so that a query typed with a precomposed `é` and one typed with `e` +
  U+0301 are one query. This is *canonical* equivalence: the two spellings are
  the same abstract characters. NFKC is deliberately not used — it is
  *compatibility* equivalence and would rewrite `ﬁ` to `fi` and fullwidth forms
  to ASCII, which is a decision about matching that belongs to PostgreSQL's text
  search dictionary, where it can be seen and changed, rather than being applied
  invisibly here.
- **Whitespace runs collapse to one space**, so that a pasted multi-line query
  and the same words on one line are one query. This also removes tabs,
  newlines, and vertical tabs before the character check below, which is why
  that check can reject the whole control class without rejecting ordinary
  pasted text.
- **Control and formatting characters are refused, not stripped.** `Cc` is the
  C0/C1 controls; `Cf` is where the bidirectional overrides and zero-width
  joiners live, which are exactly the characters that make two visually
  identical queries different strings; `Cs`, `Co`, and `Cn` are surrogates,
  private use, and unassigned. Stripping them would silently answer a different
  question than the one asked. A null byte is called out separately because it
  cannot survive the wire to PostgreSQL at all, and a caller deserves a typed
  error here rather than a driver error later.

  The order of the two steps decides one case that is worth stating rather than
  leaving to be discovered. Some `Cc` characters *are* whitespace — U+0085 NEL,
  the vertical tab, the form feed, and the four information separators are all
  `str.isspace()` — so the collapse above reaches them first and they become a
  space, exactly as a newline does. That is the right answer for them: they are
  line and field separators, and refusing a query because it was pasted with a
  NEL in it would be refusing a legitimate paste. Every control character that
  is *not* whitespace survives the collapse and is refused. Both halves are
  asserted, so the boundary is a decision rather than an artefact of the order.

**The cursor is bound, not signed.** Section 8.5 requires cursors to be opaque,
short-lived, scope-bound, and tamper-evident, and it is worth being exact about
which of those this delivers. The cursor carries a digest of the request it was
issued for — enrollment, query *fingerprint*, page size, snippet width, and the
result order — and `search` refuses a cursor whose digest does not match the
request presented with it. That makes a materially changed request a `conflict`
rather than a silently wrong page. It is not a MAC and does not claim to be:
there is no key here, so a caller can forge a cursor. What that buys is nothing,
and the reason is structural rather than lucky — a cursor names a *position*
within a scope, and the scope is re-supplied and re-authorized on every request,
so a forged position only skips results the caller was already entitled to. A
key would be required the moment a cursor carried authority; this one carries
none.

The digest is over the query's *fingerprint* and never the query, so a cursor
handed back to a caller — or logged, or pasted into an issue — discloses no
search text. That is the reason the fingerprint exists at all.

Section 8.5 also lists principal, purpose, and policy version among the things a
cursor invalidates on. None of the three is part of a search request at this
layer, so none is bound here. That is a stated gap rather than an oversight:
`test_the_cursor_binds_exactly_these_inputs` pins the current inputs, so the
transport work package that introduces principal and purpose has to extend the
binding deliberately and cannot forget it.

**One enrollment per search.** Coverage is stated "for a stated
enrollment/snapshot and never inferred globally" (section 12), and merging two
enrollments' coverage into one set of counts is exactly that global inference.
So the scope of a search is one enrollment, and a caller wanting two makes two
requests and keeps the two disclosures apart, which is the only way the counts
stay true.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "CURSOR_TTL_SECONDS",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_SNIPPET_WORDS",
    "MAX_PAGE_SIZE",
    "MAX_QUERY_CHARACTERS",
    "MAX_SNIPPET_CHARACTERS",
    "MAX_SNIPPET_WORDS",
    "MIN_SNIPPET_WORDS",
    "RESULT_ORDER",
    "EmptySearchQueryError",
    "RankCategory",
    "SearchCursor",
    "SearchCursorError",
    "SearchMatch",
    "SearchQuery",
    "SearchQueryError",
    "SearchRequest",
    "binding_digest",
    "bound_snippet",
    "label_for_media_type",
    "rank_category",
    "validate_result_label",
]

#: Longest query accepted. Long enough for a sentence a person would type,
#: short enough that neither normalization nor the text-search parser is handed
#: unbounded work — section 15 requires bounded work and an unbounded query is
#: the cheapest way to spend a backend's time from outside.
MAX_QUERY_CHARACTERS: Final = 512

#: Page sizes. Section 8.5 requires bounded pages and forbids limits that
#: produce "unmarked complete-looking responses", so a page that hits the
#: ceiling is reported as truncated rather than returned as if it were all there
#: was.
DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100

#: Snippet width, in words, as `ts_headline` counts them. The word bound is what
#: a caller asks for; the character bound below is the one that actually holds,
#: because a "word" in a document can be a base64 blob.
MIN_SNIPPET_WORDS: Final = 5
DEFAULT_SNIPPET_WORDS: Final = 30
MAX_SNIPPET_WORDS: Final = 80

#: Hard ceiling on a snippet, whatever the word count produced. A snippet is a
#: window into personal content, so its size is bounded by something that cannot
#: be argued with by the content itself.
MAX_SNIPPET_CHARACTERS: Final = 400

#: Longest result label.
MAX_LABEL_CHARACTERS: Final = 128

#: How long a cursor stays usable. Section 8.5 says short-lived; five minutes is
#: long enough to page through a result set at reading speed and short enough
#: that a cursor found later refers to a position nobody should still be at.
CURSOR_TTL_SECONDS: Final = 300

#: Longest cursor token accepted before it is decoded. Decoding an unbounded
#: string is work an outsider chooses the size of.
MAX_CURSOR_CHARACTERS: Final = 512

#: The one result order there is, named so that the cursor binds it. If a second
#: order is ever offered, this value changes and every cursor issued under the
#: old one stops validating, which is what section 8.5 requires of an order
#: change.
RESULT_ORDER: Final = "rank_desc_then_knowledge_id_desc"

#: Unicode general categories a query may not contain, after whitespace has been
#: folded. See the module docstring for what each one is and why refusing beats
#: stripping.
_FORBIDDEN_CATEGORIES: Final[frozenset[str]] = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})

#: A result label is for a human reading a list of hits. Bounded to printable
#: word characters, spaces, dots, hyphens, and underscores, so a path, a URI, a
#: host, or an address cannot be one: `/`, `\`, `:`, and `@` are outside the
#: class. As in `domain.source.registry` this catches shape and not meaning.
_LABEL_PATTERN: Final = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9 ._-]{0,127}\Z")

#: What a result is called when the only thing known about it is its media type.
#: The MCV stores no title for an extracted object, so a label is derived from
#: what exists rather than invented. `search` discloses this as a limitation, so
#: nobody reads "Markdown document" as a document's name.
_MEDIA_TYPE_LABELS: Final[dict[str, str]] = {
    "text/markdown": "Markdown document",
    "text/plain": "Plain text document",
}
_UNLABELLED: Final = "Extracted document"

#: Where the three rank categories divide, and what the two numbers mean.
#:
#: The score is `ts_rank_cd` under normalization 32 — `rank / (rank + 1)`, which
#: bounds it to [0, 1). Measured against the synthetic corpus in
#: `tests/search_quality`, a document containing a query term exactly once
#: scores 0.0909, two occurrences 0.1667, and four 0.2857; a document that
#: satisfies a query without matching any positive term — which is what a
#: negation-only query does — scores 0. So the split reads as: `STRONG` is more
#: than a passing mention, `MODERATE` is at least one real hit, and `WEAK` is a
#: document the query admitted rather than found.
#:
#: A coarse three-way split, and not a calibrated relevance model. What the
#: contract requires is that a caller receives a category rather than a score,
#: so that nothing is built on a number this system has not promised to keep
#: stable across a change of ranking function, dictionary, or corpus.
STRONG_RANK_THRESHOLD: Final = 0.15
MODERATE_RANK_THRESHOLD: Final = 0.05


class SearchQueryError(ValueError):
    """A query is malformed, unbounded, or contains something it may not.

    Every message names the rule and never the value. This is the one error in
    the system most likely to be handed the private string that caused it, so
    the discipline is structural: there is no code path here that interpolates
    the query into a message.
    """


class EmptySearchQueryError(SearchQueryError):
    """A query that normalizes to nothing, or that yields no search terms.

    Distinct from a query that simply matched nothing. "You gave me no terms to
    search for" and "I searched and found nothing" are different answers, and
    section 9.7's rule against a false no-match claim starts here.
    """


class SearchCursorError(Exception):
    """A cursor is unreadable, expired, or bound to a different request.

    Section 10 puts all three under `conflict`: the caller refreshes and asks
    again from the start. It carries no cursor, no request, and no query — a
    message that echoed the token would put a request digest into a log for no
    benefit.
    """


class RankCategory(StrEnum):
    """How well a result matched, as a category rather than a score.

    A score is an implementation detail of whichever ranking function is in use;
    publishing one invites a caller to build on a number that changes when the
    function, the dictionary, or the corpus does.
    """

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


def rank_category(score: float) -> RankCategory:
    """Bucket a normalized rank into one of three categories.

    Monotone by construction: a higher score never yields a weaker category.
    That is the only property a caller may rely on, and it is the one tested.
    """
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise TypeError("a rank must be a number")
    if not score == score or score < 0:  # a NaN is never equal to itself
        raise ValueError("a rank must be a non-negative number")
    if score >= STRONG_RANK_THRESHOLD:
        return RankCategory.STRONG
    if score >= MODERATE_RANK_THRESHOLD:
        return RankCategory.MODERATE
    return RankCategory.WEAK


def _normalize_query(value: str) -> str:
    """Fold `value` to its canonical form, or refuse it.

    The length is checked *before* normalization as well as after, because
    normalizing an unbounded string is the work the bound exists to prevent.
    """
    if not isinstance(value, str):
        raise SearchQueryError(f"a search query must be a string, got {type(value).__name__}")
    if len(value) > MAX_QUERY_CHARACTERS:
        raise SearchQueryError(f"a search query is at most {MAX_QUERY_CHARACTERS} characters")
    if "\x00" in value:
        # Called out before anything else: PostgreSQL text cannot hold a null
        # byte, so without this the caller receives a driver error from deep
        # inside a statement instead of a typed answer about their request.
        raise SearchQueryError("a search query cannot contain a null byte")
    folded = unicodedata.normalize("NFC", value)
    # `str.split()` splits on every Unicode whitespace character, so tabs,
    # newlines, form feeds, and U+00A0 alike are gone before the category check.
    collapsed = " ".join(folded.split())
    for character in collapsed:
        if unicodedata.category(character) in _FORBIDDEN_CATEGORIES:
            raise SearchQueryError(
                "a search query cannot contain control, formatting, surrogate, "
                "private-use, or unassigned characters"
            )
    if not collapsed:
        raise EmptySearchQueryError("a search query cannot be empty")
    if len(collapsed) > MAX_QUERY_CHARACTERS:
        raise SearchQueryError(f"a search query is at most {MAX_QUERY_CHARACTERS} characters")
    return collapsed


@dataclass(frozen=True, slots=True, repr=False)
class SearchQuery:
    """One normalized query, which redacts itself everywhere it is rendered.

    The text is here because it has to reach PostgreSQL as a bound parameter.
    Everywhere else — a log, an error, a cursor, a repr — it is a length or a
    digest.
    """

    text: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "text", _normalize_query(self.text))

    def __repr__(self) -> str:
        """Report the shape, never the value.

        Python falls back to `__repr__` for `__str__`, `format`, and `%s`, so
        this one definition covers every way a query can end up in a string. The
        length is disclosed deliberately: it is useful when debugging and it is
        not the content.
        """
        return f"SearchQuery(<redacted: {len(self.text)} characters>)"

    @property
    def fingerprint(self) -> str:
        """A stable digest of the normalized text.

        This is what a cursor binds to, so that "is this the same query" can be
        answered without the query being carried anywhere.
        """
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def binding_digest(
    *, query: SearchQuery, enrollment_id: str, page_size: int, snippet_words: int
) -> str:
    """The digest a cursor carries: everything a page's meaning depends on.

    Canonical JSON — sorted keys, no incidental whitespace — so the digest is a
    function of the values rather than of how a mapping was built. The query
    enters as its fingerprint and never as its text.
    """
    canonical = json.dumps(
        {
            "enrollment_id": enrollment_id,
            "order": RESULT_ORDER,
            "page_size": page_size,
            "query": query.fingerprint,
            "snippet_words": snippet_words,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class SearchCursor:
    """A position in one result set, bound to the request that produced it.

    Keyset rather than offset: the position is the last row's rank and knowledge
    identifier, which is what makes a page stable when rows are added between
    requests. An offset would silently repeat or skip rows instead.
    """

    binding: str
    rank: float
    knowledge_id: str
    issued_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        if not re.fullmatch(r"[0-9a-f]{64}", self.binding):
            raise SearchCursorError("a cursor binding is a sha-256 digest")
        rank = self.rank
        if isinstance(rank, bool) or not isinstance(rank, (int, float)):
            raise SearchCursorError("a cursor rank is a number")
        if not rank == rank or rank < 0:  # a NaN is never equal to itself
            raise SearchCursorError("a cursor rank is a non-negative number")
        object.__setattr__(self, "rank", float(rank))
        object.__setattr__(self, "issued_at", ensure_utc(self.issued_at))

    def encode(self) -> str:
        """Render the cursor as one opaque, URL-safe token.

        Base64 of compact JSON. Not encryption and not obfuscation — the point
        is that the token has no structure a caller is invited to construct by
        hand, and that it contains nothing private if one does take it apart:
        a request digest, a rank, an opaque identifier, and a time.
        """
        payload = json.dumps(
            {
                "b": self.binding,
                "k": self.knowledge_id,
                # `repr` of a float round-trips exactly in Python, and
                # `json.dumps` uses it, so the rank that comes back is the rank
                # that went in and the keyset comparison stays exact.
                "r": self.rank,
                "t": int(self.issued_at.timestamp()),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")

    @classmethod
    def decode(cls, token: str) -> SearchCursor:
        """Read a token, or raise `SearchCursorError`.

        Every failure is one error with one message. A cursor that reported
        *why* it was rejected would tell whoever supplied it how to build a
        better one, and there is no legitimate caller that needs to know: a
        cursor comes from this system or it does not.
        """
        # The type is checked where a cursor enters the system, in
        # `SearchRequest`, rather than again here: a `str` annotation mypy has
        # already proved is not a runtime check worth writing twice.
        if not token or len(token) > MAX_CURSOR_CHARACTERS:
            raise SearchCursorError("the cursor is not readable")
        padded = token + "=" * (-len(token) % 4)
        payload: dict[str, Any] | None = None
        try:
            decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        except (binascii.Error, UnicodeDecodeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            payload = decoded
        if payload is None or set(payload) != {"b", "k", "r", "t"}:
            raise SearchCursorError("the cursor is not readable")
        binding, knowledge_id, rank, issued = payload["b"], payload["k"], payload["r"], payload["t"]
        if (
            not isinstance(binding, str)
            or not isinstance(knowledge_id, str)
            or isinstance(rank, bool)
            or not isinstance(rank, (int, float))
            or isinstance(issued, bool)
            or not isinstance(issued, int)
        ):
            raise SearchCursorError("the cursor is not readable")
        cursor: SearchCursor | None = None
        try:
            cursor = cls(
                binding=binding,
                rank=float(rank),
                knowledge_id=knowledge_id,
                issued_at=datetime.fromtimestamp(issued, tz=UTC),
            )
        except (SearchCursorError, ValueError, OverflowError, OSError):
            cursor = None
        if cursor is None:
            # Raised outside the handler, so the original — which may render a
            # rejected identifier or timestamp — is not left in `__context__`.
            raise SearchCursorError("the cursor is not readable")
        return cursor

    def is_expired(self, now: datetime) -> bool:
        """Whether this cursor has outlived `CURSOR_TTL_SECONDS`.

        `now` is a parameter rather than a clock read, so that expiry is a
        property of the value and can be tested without waiting.
        """
        return ensure_utc(now) - self.issued_at > timedelta(seconds=CURSOR_TTL_SECONDS)


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """One `knowledge.search` request, bounded on construction.

    Every bound is enforced here rather than where the statement is built, so
    there is no code path that holds an unbounded request and checks it later.
    """

    enrollment_id: str
    query: SearchQuery
    page_size: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None
    snippet_words: int = DEFAULT_SNIPPET_WORDS

    def __post_init__(self) -> None:
        validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)
        if not isinstance(self.query, SearchQuery):
            raise SearchQueryError("a search request carries a normalized SearchQuery")
        _check_bound("page_size", self.page_size, 1, MAX_PAGE_SIZE)
        _check_bound("snippet_words", self.snippet_words, MIN_SNIPPET_WORDS, MAX_SNIPPET_WORDS)
        if self.cursor is not None and not isinstance(self.cursor, str):
            raise SearchCursorError("the cursor is not readable")

    @property
    def binding(self) -> str:
        """The digest a cursor issued for this request must carry."""
        return binding_digest(
            query=self.query,
            enrollment_id=self.enrollment_id,
            page_size=self.page_size,
            snippet_words=self.snippet_words,
        )

    def position(self, now: datetime) -> SearchCursor | None:
        """The validated position this request resumes from, or `None`.

        Three refusals, one error: unreadable, expired, and issued for a
        different request. The last is what makes the cursor scope-bound —
        changing the enrollment, the query, the page size, or the snippet width
        and reusing the cursor is a `conflict`, not a quietly wrong page.
        """
        if self.cursor is None:
            return None
        cursor = SearchCursor.decode(self.cursor)
        if cursor.is_expired(now) or cursor.binding != self.binding:
            raise SearchCursorError("the cursor does not belong to this request")
        return cursor


def _check_bound(field: str, value: int, low: int, high: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SearchQueryError(f"{field} must be an integer")
    if not low <= value <= high:
        raise SearchQueryError(f"{field} must be between {low} and {high}")


def validate_result_label(label: str) -> str:
    """Return `label` unchanged, or raise.

    Fails closed on a label that could be a path. A search result that displayed
    a filesystem location would defeat `INV-PKL-005` at the last step, after
    every layer beneath it had kept the location private, so a stored label that
    looks like one is refused rather than trimmed into shape.
    """
    if not isinstance(label, str):
        raise SearchQueryError(f"a result label must be a string, got {type(label).__name__}")
    if not _LABEL_PATTERN.fullmatch(label):
        raise SearchQueryError(
            f"a result label is 1-{MAX_LABEL_CHARACTERS} characters of letters, digits, "
            "spaces, dots, hyphens, or underscores and must not contain a path or address"
        )
    return label


def label_for_media_type(media_type: str | None) -> str:
    """The safe label for a result, given the only thing stored about it.

    The MCV records no title for an extracted object, so this is derived rather
    than invented, and `search` discloses that as a limitation on every result
    set. Deriving a label from the object's filename would be the leak this
    whole layer exists to prevent.
    """
    return _MEDIA_TYPE_LABELS.get(media_type or "", _UNLABELLED)


def bound_snippet(value: str) -> tuple[str, bool]:
    """Return `value` bounded and stripped of control characters, and whether it was cut.

    Two hazards, one function. The length bound is the contract's: a snippet is
    a window into personal content, and its size must not be decided by the
    content. The control-character strip is the terminal's: extracted text is
    whatever was in a document, and a document can contain escape sequences that
    a console renders as commands rather than as text.
    """
    cleaned = " ".join(
        "".join(
            character
            for character in value
            if unicodedata.category(character) not in _FORBIDDEN_CATEGORIES
        ).split()
    )
    if len(cleaned) <= MAX_SNIPPET_CHARACTERS:
        return cleaned, False
    return cleaned[:MAX_SNIPPET_CHARACTERS].rstrip(), True


@dataclass(frozen=True, slots=True)
class SearchMatch:
    """One result, carrying what section 9.7 says a result carries.

    No score, no locator, no filename, no extracted document — a bounded snippet
    of it. The three source identifiers are the binding section 9.8 requires, so
    a caller can ask for the record itself and get the same version this matched.
    """

    knowledge_id: str
    label: str
    snippet: str
    rank: RankCategory
    source_id: str
    source_object_id: str
    version_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.knowledge_id, IdKind.KNOWLEDGE)
        validate_identifier(self.source_id, IdKind.SOURCE)
        validate_identifier(self.source_object_id, IdKind.SOURCE_OBJECT)
        validate_identifier(self.version_id, IdKind.VERSION)
        validate_result_label(self.label)
        if not isinstance(self.snippet, str):
            raise SearchQueryError("a snippet must be a string")
        if len(self.snippet) > MAX_SNIPPET_CHARACTERS:
            raise SearchQueryError(f"a snippet is at most {MAX_SNIPPET_CHARACTERS} characters")
