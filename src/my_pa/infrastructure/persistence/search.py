"""Lexical search over extracted text, with the query bound as a parameter.

One statement builder and one entry point. Everything difficult about this
module is a decision about what the query is allowed to do, so those are stated
first.

**`websearch_to_tsquery`, and why not the other two.** PostgreSQL offers three
ways to turn text into a `tsquery`, and only one of them is dangerous.
`to_tsquery` parses the *tsquery grammar*: the caller's string becomes operators,
and a malformed one raises `ERROR: syntax error in tsquery`, which reaches the
caller as a database failure rather than as an answer about their request. It
would not be SQL injection — the value is still bound — but it hands the caller
control of a parser and turns bad input into a 500. Both are refused.
`plainto_tsquery` is safe and treats the whole string as words ANDed together.
`websearch_to_tsquery` is equally safe and understands a small, closed,
web-search syntax: a quoted phrase, `or`, and a leading `-` for negation.

This module uses `websearch_to_tsquery`. Safety is not the tiebreak — both are
safe, and it was measured rather than assumed: `cat & !dog` parses to
`'cat' & 'dog'`, `foo <-> bar` to `'foo' & 'bar'`, and `foo:*` to `'foo'`, so
every tsquery operator arrives as ordinary text with no control at all. The
tiebreak is that a document corpus needs phrase search — "quarterly report" as
two adjacent words is a different question from those two words anywhere in a
file — and `plainto_tsquery` cannot express it. The cost is disclosed rather than
hidden: a query of nothing but negations (`-secret`) becomes `!'secret'`, which
matches almost everything. It cannot widen scope, cannot leak, and is bounded by
the page size, so it is a known limitation rather than a defect, and it is one
`plainto_tsquery` would not have.

A query that yields no lexemes at all — `!!!`, or nothing but stop words — is
*not* run as a search. `websearch_to_tsquery` returns an empty `tsquery` there,
which matches nothing, and returning "no results" for it would be exactly the
false no-match claim section 9.7 forbids. `numnode` is asked first and an empty
query is `EmptySearchQueryError`.

**The query never appears in an error, and that does not depend on the engine.**
SQLAlchemy renders bound parameters into `DBAPIError` messages unless the engine
was built with `hide_parameters=True`, and `create_database_engine` does not set
it. So every statement this module *builds* runs through `_execute`, which
converts any `SQLAlchemyError` into one of this module's own errors — *raised
outside the `except` block*, so the original is not left in `__context__` where a
traceback would render it. That makes the redaction a property of this module
rather than of a setting in a file this module does not own. The exception is
named where it is: the coverage read is `coverage_for`'s statements, not this
module's, and it is not inside `_execute`.

**The index exists, and the predicate has to stay equal to it as an expression.**
`knowledge.extractions` has no `tsvector` column and no trigger maintaining one.
What it has is a functional GIN index over the same expression this module
builds, created beside the table by revision `8b3f5c17d904`:

    CREATE INDEX extractions_full_text ON knowledge.extractions
      USING gin (to_tsvector('english', text));

PostgreSQL matches a functional index by expression tree, so that index and the
predicate below are one decision recorded in two files, and they must remain
equal *as expressions*. Not as text: the index is written over `text` and the
predicate compiles to `to_tsvector('english', knowledge.extractions.text)`, which
is a different string for the same tree and matches. The configuration is named
explicitly on both sides — which is also what makes the expression `IMMUTABLE`
and therefore indexable at all, since the one-argument form is only `STABLE` —
and it is written as a SQL literal rather than a bound parameter, for the reason
given at `_CONFIG`.

What breaks the match is anything that changes the tree, and it breaks silently:
the plan drops to a sequential scan and still returns correct rows, so no
result-comparing test can see it. A different text-search configuration does it,
and so does wrapping the column in a `coalesce`. A cast is the case worth stating
precisely, because it was measured against a twenty-thousand-row table and the
obvious reading is wrong: a cast the parser can erase is erased before planning
and the index is still used — `cast(text AS text)` and `cast(text AS varchar)`
both keep the `Bitmap Index Scan` — while `cast(text AS varchar(64))`, which
carries a length check the parser cannot drop, leaves a different tree and falls
to a sequential scan. So "no cast" is not the rule and never was; "nothing that
changes the expression" is.

That the expressions do agree was measured rather than assumed. Against a table
of twenty thousand synthetic rows the predicate built below produces
`Bitmap Index Scan on extractions_full_text` with
`Index Cond: (to_tsvector('english'::regconfig, text) @@ …)`, and
`test_the_search_predicate_uses_the_functional_index_and_not_a_sequential_scan`
holds that continuously: it takes the `@@` predicate out of the statement
`match_statement` compiles — rather than writing an equivalent one, which is how
the same test previously came to prove nothing — and asserts the plan.

What is not claimed: that every search uses the index. A search also filters on
`enrollment_id`, and where that is the more selective condition the planner will
use `extractions_by_enrollment` — whose leading column it is — and apply the
match as a filter, which is the right plan and is what it does at test-fixture
scale. That index's second column is `status`, which `match_statement` no longer
filters on and `coverage_for` does; `match_statement` says why. This module
also sets no statement timeout. The index removes the sequential scan as the
only possibility; it does not bound what a query can cost.

Also not claimed, and this is the largest of them: that what a search returns for
a root-selector enrollment is bounded by that enrollment's root. It is bounded by
its *source*. `authorized_object` restricts a root selector to the enrollment's
`source_id` and no further, because nothing persists the objects under a root, so
an extraction stored under that enrollment for an object of the same source
outside the root passes the boundary and its text is returned — with a
`source_object_id` and a `version_id` that are honest and a scope the caller has
no way to check them against. The same object is counted by `coverage_for`. This
module never states a denominator for a root selector so it cannot trip over that
itself, but a caller that *did* enumerate the root and states that count to
`coverage_for` gets counts larger than it, which `coverage_for` refuses and
`_coverage` reports as `SearchInternalError`: the truthful denominator is the one
that fails. Every root-selector search therefore carries
`scope_is_source_wide_not_root_bounded` beside `eligible_total_not_persisted`, so
the limit is readable from the envelope rather than from this file.

The two tokens are one missing fact and should be fixed once. Persisting the
enumerated object set at enrollment time supplies both the membership a root
selector cannot check and the eligible total nothing measured;
`persistence.extraction.authorized_object` records the same conclusion where the
predicate is. Both are carried into WP-4.

Also not claimed: that no database failure of any kind can carry detail out of
`search_extractions`. The coverage read runs `coverage_for`'s statements, which
this module does not wrap — `_coverage` catches `ValueError` and nothing else —
so a `ProgrammingError` raised there escapes as a `SQLAlchemyError` whose message
carries the statement and its bound `enrollment_id`. That is a schema fault
rather than a query fault and no caller's text reaches it, but it is a real hole
in the redaction and it is carried into WP-4 rather than described as closed.

**What a search returns is bounded by the enrollment's content-type allowlist.**
An enrollment is a selector and an allowlist, and this module read neither until
recently: it filtered on `enrollment_id`, which is what a row was written
against rather than what the grant covers. `match_statement` now applies both
halves — `authorized_object` and `authorized_media_type` — and they are the same
two predicates `coverage_for`'s `processed` count applies, so the page and the
coverage beside it cannot disagree about what is in scope. An enrollment whose
allowlist names no type this extractor can read matches nothing and reports
`processed = 0`, which is the honest answer rather than a case to special-case.

**`pg_trgm` is installed and deliberately unused.** `AGENTS.md` section 4 names
it alongside full-text search as an initial mechanism, and it answers a different
question — similarity, for fuzzy and misspelled input. Nothing in the accepted
objective asks for that, adding it would introduce a second relevance signal with
no benchmark to weigh it against the first, and `AGENTS.md` section 2 rules out
machinery with no current caller. It stays available.

**Coverage is read, not inferred, and the denominator is the hard part.**
`coverage_for` takes the eligible total from whoever enumerated the scope,
because deriving it from the rows that exist would report complete coverage of a
scope nobody measured. Search runs long after that enumeration and in another
process, so it can supply the total in exactly one case: an enrollment that named
its objects explicitly, where the count of `object_ids` *is* the authorized
scope. An enrollment selecting a root plus a depth has an eligible total that
only enumeration knows and that nothing persists, so search passes `eligible=None`
— which is `coverage_for`'s way of being told the denominator was never measured
— rather than quoting a number it would have had to invent. It invented one
before: `max_items`, the enrollment's own ceiling, which bounds what a single
pass may do and not how many outcomes accumulate across passes over a changing
tree, so a long-lived enrollment eventually exceeded it and the read raised
`ValueError` out of the coverage guard. A denominator nothing measured has no
valid stand-in, and the fix is to stop supplying one.

What search reports for that enrollment is a partial result carrying
`eligible_total_not_persisted`, and a coverage *state* held at
`partially_processed`. The clamp covers every state that asserts the whole scope
reached an outcome — `processed`, `quarantined`, `unsupported`, `unavailable` —
and not the states that assert nothing of the kind. All four are reachable the
same way and all four are the same false claim: with the total derived from the
outcomes, whichever outcome the enrollment happens to hold divides out to the
whole of it, so "every eligible object here was quarantined" is as available and
as unfounded as "every eligible object here was processed", and it is the more
dangerous of the two because a caller is likelier to act destructively on it. A
search cannot claim whole-scope coverage it cannot prove, and section 9.7 would
rather have a partial disclosure than a confident wrong one.

What that leaves, stated here rather than discovered later: for a root-selector
enrollment the reported counts and the reported state disagree, and the clamp is
what makes them disagree. `eligible == accounted` there, where `accounted` is
`CoverageCounts`' own four-term sum — `processed + quarantined + unsupported +
unavailable` — and the derived total is those four plus `queued`. They are equal
for this module's calls because it passes neither `queued` nor `unavailable`,
which is a fact about these two call sites and not a property of the arithmetic;
a caller that passed either would break the equality, and describing it as three
terms because the fourth is currently zero is the "currently unreachable"
reasoning this module has now rejected twice. So a consumer that
recomputes the state from the counts gets whichever whole-scope state the
outcomes happen to form, or `partially_processed` where they are mixed, and the
first case contradicts the state reported beside it. The clamp stops this module
from making the claim; it cannot stop a consumer from deriving it, because
`eligible` is a required integer in the v1 disclosure and no integer is true
here. The enumerated total is the one number that would be, and nothing persists
it. The three signals that do not lie — `eligible_total_not_persisted`,
`partial_result`, and the state — are what a consumer should read, and a consumer
reading the counts alone will be wrong.

Fixing it properly means either persisting the eligible total at enrollment or
letting `eligible` be absent in the contract, and the second is a v1 change
gated by `P00-OD-004`. Both are out of scope here and are carried into WP-4."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, assert_never

from sqlalchemy import (
    ColumnElement,
    Connection,
    CursorResult,
    Executable,
    Float,
    Row,
    Select,
    Text,
    bindparam,
    cast,
    func,
    literal_column,
    select,
    tuple_,
)
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from my_pa.contracts.v1.disclosure import (
    Coverage,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    SourceReference,
    Truncation,
    Trust,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.common.time import ensure_utc, utc_now
from my_pa.domain.extraction.coverage import (
    AggregateLimitation,
    CoverageCounts,
    LimitationReason,
)
from my_pa.domain.search.query import (
    EmptySearchQueryError,
    SearchCursor,
    SearchMatch,
    SearchRequest,
    bound_snippet,
    label_for_media_type,
    rank_category,
)
from my_pa.infrastructure.persistence.extraction import (
    authorized_media_type,
    authorized_object,
    coverage_for,
)
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollments,
    extractions,
    source_objects,
    sources,
)

__all__ = [
    "INDEXED_CONFIGURATIONS",
    "RANK_NORMALIZATION",
    "SEARCH_CONFIG",
    "SearchInternalError",
    "SearchPage",
    "SearchUnavailableError",
    "UnknownEnrollmentError",
    "context_statement",
    "match_statement",
    "search_extractions",
]

#: The text-search configuration, on both sides of the match. It is named
#: explicitly rather than left to `default_text_search_config` for two reasons:
#: the two-argument `to_tsvector` is `IMMUTABLE` and therefore indexable where
#: the one-argument form is only `STABLE`, and a session setting would let the
#: same query mean different things to two connections.
#:
#: `english` rather than `simple`, so that "reporting" finds "report". The
#: consequence is that this is an English-language index; a corpus in another
#: language wants a different configuration, which is a schema decision rather
#: than a search one.
SEARCH_CONFIG: Final = "english"

#: Every text-search configuration this module may compile into a statement.
#: Closed, and checked rather than trusted: `_configuration` interpolates the
#: name into SQL text, so the set of names that can reach that interpolation has
#: to be a set rather than whatever the module attribute happens to hold. A
#: configuration is in it only once `knowledge.extractions` carries a functional
#: index over that configuration — an unindexed one is not a syntax problem, it
#: is the silent sequential scan the module docstring describes.
INDEXED_CONFIGURATIONS: Final = frozenset({SEARCH_CONFIG})


def _configuration(name: str) -> ColumnElement[Any]:
    """The named text-search configuration as a SQL literal, if it is an indexed one.

    A literal and not a bound parameter, and the distinction is the difference
    between using the functional index and not using it. It was measured. Bound,
    the predicate compiles to `to_tsvector($1, text)`, and matching it against an
    index on `to_tsvector('english', text)` then depends on the server folding
    the parameter to a constant while planning: it does under a custom plan and
    it does not under `plan_cache_mode = force_generic_plan`, where the measured
    plan is a sequential scan even with `enable_seqscan = off`. A literal makes
    index matching a property of the expression rather than of which plan the
    server chose.

    Which is why this is a function with a guard rather than an f-string. Writing
    a name into SQL is safe here because the name came out of a closed set, not
    because of what `SEARCH_CONFIG` currently is: the comment above it already
    anticipates a corpus in another language wanting a different configuration,
    and the next person to write one should not have to notice that the value is
    also concatenated into a statement. The caller's query text is never treated
    this way at all — it is a `bindparam` in `_tsquery` and stays one.
    """
    if name not in INDEXED_CONFIGURATIONS:
        raise ValueError("unsupported text-search configuration")
    return literal_column(f"'{name}'", REGCONFIG)


#: The configuration as it is written into the SQL, resolved once at import.
#: That is the property that makes it safe, and it is a stronger one than "a
#: module constant nothing outside this file can set" — which is false, since
#: any importer can rebind `SEARCH_CONFIG`. Rebinding it after import changes
#: nothing: the literal below was built from the value that passed the closed-set
#: check at import time, and every statement in this module uses that object.
_CONFIG: Final = _configuration(SEARCH_CONFIG)

#: `ts_rank_cd` normalization 32: `rank / (rank + 1)`, which bounds the score to
#: [0, 1). Bounded matters because the score is bucketed into a category, and a
#: threshold against an unbounded number would drift with document length.
RANK_NORMALIZATION: Final = 32

#: `ts_headline` options. `StartSel` and `StopSel` are emptied on purpose: the
#: default wraps matches in `<b>` tags, and a snippet carrying markup is markup
#: this system injected into whatever renders it. `MaxFragments=1` keeps one
#: window rather than a stitched-together set with separators in it.
_HEADLINE_TEMPLATE: Final = (
    'StartSel="", StopSel="", MaxFragments=1, MaxWords={words}, MinWords={minimum}'
)

#: Limitation tokens this module can disclose. Closed values, like every other
#: token in the envelope, so `limitations` cannot become a free-text channel.
_NO_STORED_LABEL: Final = "result_label_is_media_type_only"
_ELIGIBLE_UNKNOWN: Final = "eligible_total_not_persisted"
#: Named after what it is rather than after the fix it is waiting for: for a
#: root-selector enrollment the searched scope is the enrollment's whole source,
#: not the subtree under its root. See the module docstring.
_SCOPE_IS_SOURCE_WIDE: Final = "scope_is_source_wide_not_root_bounded"
_SNIPPET_TRUNCATED: Final = "snippet_truncated"
_NO_INDEXED_COVERAGE: Final = "no_extracted_text_in_scope"
_COVERAGE_INCOMPLETE: Final = "scope_not_fully_extracted"


class UnknownEnrollmentError(LookupError):
    """The scope names no enrollment.

    Carries the opaque identifier and nothing else. Section 10 puts this under
    `not_found`, which is a different answer from "the search found nothing".
    """


class SearchUnavailableError(Exception):
    """The lexical index could not be read.

    Carries no statement, no parameter, and no driver detail — see the module
    docstring for why that is enforced here rather than left to engine
    configuration. Section 10's `unavailable`: conditionally retryable.
    """


class SearchInternalError(Exception):
    """The search failed for a reason that is this system's fault.

    Separated from `SearchUnavailableError` because telling a caller to retry a
    missing column would be a lie with a retry budget attached. Both carry
    nothing; only the classification differs.
    """


@dataclass(frozen=True, slots=True)
class SearchPage:
    """One page of results and the disclosure that must accompany it.

    The two are one value because section 8.3 makes the envelope mandatory:
    a caller that could hold the matches without the coverage could report
    "nothing found" for a scope that was never indexed.
    """

    matches: tuple[SearchMatch, ...]
    disclosure: Disclosure


def _execute(connection: Connection, statement: Executable) -> CursorResult[Any]:
    """Run `statement`, converting any database failure into a bare typed error.

    The `raise` statements are outside the `except` block on purpose. `raise …
    from None` clears `__cause__` and leaves the original in `__context__`,
    where a rendered traceback shows a `DBAPIError` whose message can contain
    the bound query text. Leaving the handler first is what actually empties it.
    """
    unavailable = False
    try:
        return connection.execute(statement)
    except (OperationalError, InterfaceError):
        # The server is unreachable, the connection died, or a statement
        # timeout fired. Conditionally retryable.
        unavailable = True
    except SQLAlchemyError:
        # A missing column, a type error, a programming mistake. Retrying will
        # not help and saying otherwise would be a false promise.
        unavailable = False
    if unavailable:
        raise SearchUnavailableError("the lexical index could not be read")
    raise SearchInternalError("the search could not be completed")


def _tsquery(request: SearchRequest) -> ColumnElement[Any]:
    """The parsed query, as one bound parameter and one named configuration.

    The query is a `bindparam` and nothing else touches it. It is never
    formatted, concatenated, or `literal_column`-ed — the configuration beside it
    is, and `_CONFIG` says why a module constant is a different question — and
    the compiled statement carries a placeholder where the text would be, which
    `tests/security/test_query_is_data_not_sql.py` asserts against the compiled
    SQL rather than against this sentence.
    """
    return func.websearch_to_tsquery(
        _CONFIG,
        bindparam("search_text", value=request.query.text, type_=Text),
    )


def _document_vector() -> ColumnElement[Any]:
    """The indexed side of the match.

    The same expression `extractions_full_text` is built over — the same tree,
    which is what PostgreSQL matches a functional index by, and not the same
    characters, which it does not. See the module docstring for what a divergence
    here costs and why nothing that compares rows would notice it.
    """
    return func.to_tsvector(_CONFIG, extractions.c.text)


def context_statement(request: SearchRequest) -> Select[Any]:
    """Everything about the scope that one row can answer, in one round trip.

    The enrollment's source and classification, whether its eligible total is
    knowable, and how many lexemes the query produced. The last is not an
    aggregate and the rest are plain columns, so they compose; asking for the
    lexeme count separately would be a second round trip for one integer.

    `max_items` is deliberately not among them. It was, as the denominator for a
    root-selector enrollment, and it was the wrong number: it bounds one pass's
    authorization rather than the outcomes an enrollment accumulates, so reading
    it here was reading a limit as if it were a measurement.

    Public, and the reason is a test rather than a caller. Building a statement
    and running it are separate acts, and separating them lets
    `tests/security/test_query_is_data_not_sql.py` compile *this* statement and
    inspect the SQL that will actually be sent. A test that rebuilt an
    equivalent statement of its own would prove something about the test.
    """
    return (
        select(
            enrollments.c.source_id,
            sources.c.classification,
            enrollments.c.root_object_id,
            func.cardinality(enrollments.c.object_ids).label("named_objects"),
            func.numnode(_tsquery(request)).label("lexemes"),
        )
        # An inner join, and nothing can tell: `enrollments.source_id` is `NOT
        # NULL` with a foreign key to `sources`, so no enrollment row exists
        # whose source is missing and an outer join would return the same rows
        # with the same values. It is written as an inner join because that is
        # the truthful shape of the relation, and it is recorded here rather
        # than pinned, because no arrangement of rows could pin it.
        .select_from(enrollments.join(sources, sources.c.source_id == enrollments.c.source_id))
        .where(enrollments.c.enrollment_id == request.enrollment_id)
    )


def _context(connection: Connection, request: SearchRequest) -> Row[Any]:
    """Run `context_statement`, or report that the scope names no enrollment."""
    row = _execute(connection, context_statement(request)).one_or_none()
    if row is None:
        raise UnknownEnrollmentError(f"no enrollment {request.enrollment_id}")
    return row


def _limitation_tokens(connection: Connection, enrollment_id: str) -> tuple[str, ...]:
    """The aggregate limitations recorded at the enrollment's latest snapshot.

    Read here rather than through `coverage_for`'s snapshot argument, and the
    difference matters. `coverage_for` matches limitations to the snapshot it is
    given *exactly* and counts outcomes up to it; search wants every outcome
    recorded so far, so it passes the current time, which no limitation row will
    ever equal. Asking for the newest snapshot separately keeps both answers
    right: all outcomes, and the omissions the most recent enumeration pass
    reported.
    """
    latest = select(func.max(coverage_limitations.c.observed_at)).where(
        coverage_limitations.c.enrollment_id == enrollment_id
    )
    rows = _execute(
        connection,
        select(coverage_limitations.c.reason, coverage_limitations.c.affected_count).where(
            coverage_limitations.c.enrollment_id == enrollment_id,
            coverage_limitations.c.observed_at == latest.scalar_subquery(),
        ),
    ).all()
    return tuple(
        sorted(
            AggregateLimitation(
                reason=LimitationReason(row[0]), affected_count=int(row[1])
            ).disclosure
            for row in rows
        )
    )


def match_statement(request: SearchRequest, position: SearchCursor | None) -> Select[Any]:
    """One page of matching rows, plus one, so truncation is a fact and not a guess.

    Keyset pagination on `(rank, knowledge_id)`, descending on both, which is
    the order the cursor binds. A row-value comparison is what makes the
    resumption exact where two rows share a rank: `(rank, id) < (r, k)` is one
    predicate over the pair rather than two predicates that would drop or repeat
    the ties.

    `LIMIT page_size + 1` is how truncation is known. Fetching exactly the page
    size leaves "is there more" unanswerable without a second query, and section
    8.5 forbids a limit that produces an unmarked complete-looking response.

    **`enrollment_id` is not the authorization, and it is not removable either.**
    It says which enrollment a row was written against, and nothing ties that to
    what the enrollment authorizes; a row stored for any object at all was
    matched, and its extracted text returned, because it carried the right
    `enrollment_id`. So the boundary is `authorized_object` and
    `authorized_media_type`, the same two predicates `coverage_for`'s `processed`
    count applies, which is what keeps what a search returns and what it claims
    coverage of from disagreeing about what is in scope. The `enrollment_id`
    filter stays beside them because neither replaces it: two enrollments over
    one source can authorize the same object, and without this filter a search
    under one would return rows the other wrote, for an object both authorize.
    `test_a_search_returns_only_the_rows_its_own_enrollment_wrote` holds all of
    that constant except the enrollment.

    **The content dimension is the enrollment's allowlist, applied to the row
    being returned.** `extractions.media_type` is what the text was read as, and
    `enrollments.media_types` is what the operator authorized reading. A row
    outside it is not returned, for the same reason its text is not counted as
    coverage: the grant did not cover it. `record_outcome` refuses to write one,
    so the rows this excludes are the ones written by hand or written before the
    check — the same two halves, for the same reason, as the object dimension.

    **No `status` filter, and that is the rule rather than an omission.** This
    selected only `extracted` rows until the condition was measured and found
    undecidable: `text_exists_exactly_when_something_was_extracted` makes `text`
    null for every row that is not `extracted`, `to_tsvector` of null is null,
    and `null @@ query` is null — so the `@@` predicate below already excludes
    every such row and no arrangement of rows can make the status test change an
    answer. `persistence.extraction` states the rule that removes it. The
    equivalent filter in `coverage_for`'s `processed` count is *not* removed,
    because there it does decide: a row filed in `extractions` with status
    `quarantined` carries no text, so nothing excludes it from a count, and
    `test_a_row_filed_in_extractions_as_quarantined_is_not_counted_as_processed`
    is what fails if it goes.

    **The source comes from the object.** `source_objects.source_id` is joined
    and selected rather than taken from the enrollment row, because those are two
    different facts and only one of them is a property of the row being returned.
    Reading it from the enrollment made every `SourceReference` assert the
    enrollment's source whatever the object's actually was. The boundary above
    now makes the two equal for every row this can return; the join is what makes
    that a derivation instead of an assumption, and
    `test_a_match_takes_its_source_from_the_matched_object` pins it.

    Public for the same reason as `context_statement`: the security suite
    compiles this and asserts that the query text appears among the bound
    parameters and nowhere in the SQL.
    """
    query = _tsquery(request)
    rank = cast(func.ts_rank_cd(_document_vector(), query, RANK_NORMALIZATION), Float)
    headline = func.ts_headline(
        _CONFIG,
        extractions.c.text,
        query,
        bindparam(
            "headline_options",
            value=_HEADLINE_TEMPLATE.format(
                words=request.snippet_words, minimum=min(request.snippet_words, 5)
            ),
            type_=Text,
        ),
    )

    statement = (
        select(
            extractions.c.extraction_id,
            source_objects.c.source_id,
            extractions.c.source_object_id,
            extractions.c.version_id,
            extractions.c.media_type,
            headline.label("snippet"),
            rank.label("rank"),
        )
        .select_from(
            extractions.join(
                source_objects,
                source_objects.c.source_object_id == extractions.c.source_object_id,
            )
        )
        .where(
            extractions.c.enrollment_id == request.enrollment_id,
            authorized_object(extractions.c.source_object_id, enrollment_id=request.enrollment_id),
            authorized_media_type(extractions.c.media_type, enrollment_id=request.enrollment_id),
            _document_vector().bool_op("@@")(query),
        )
        .order_by(rank.desc(), extractions.c.extraction_id.desc())
        .limit(request.page_size + 1)
    )
    if position is not None:
        statement = statement.where(
            tuple_(rank, extractions.c.extraction_id)
            < tuple_(
                bindparam("cursor_rank", value=position.rank, type_=Float),
                bindparam("cursor_knowledge_id", value=position.knowledge_id, type_=Text),
            )
        )
    return statement


def _matches(
    connection: Connection, request: SearchRequest, position: SearchCursor | None
) -> list[Row[Any]]:
    return list(_execute(connection, match_statement(request, position)).all())


def _claims_the_whole_scope(state: CoverageState) -> bool:
    """Whether `state` asserts that every eligible object reached an outcome.

    The partition is written out member by member, and exhaustively, because the
    question it answers is which states a search may not report when it has no
    measured denominator — and a state that escaped the classification would
    escape that rule silently, which is precisely how the `processed`-only clamp
    this replaces came to be wrong. `assert_never` makes a newly added
    `CoverageState` a type error here rather than a state nobody classified.

    The four in the first case all say "the whole scope ended this way", so all
    four are unsayable without a denominator someone measured. `unavailable` is
    among them although no call in this module can currently produce it: search
    passes no `unavailable` count today, and "currently unreachable" is exactly
    the reasoning that left `quarantined` and `unsupported` out of the first
    clamp.

    None of the six in the second case asserts anything of the kind, so an
    unmeasured total cannot make any of them false. `partially_processed` is the
    honest reading this function exists to fall back to; `eligible` and `queued`
    say work has not finished; `not_enrolled` says there is no scope; `stale` and
    `superseded` are about the snapshot rather than the counts and outrank them.
    """
    match state:
        case (
            CoverageState.PROCESSED
            | CoverageState.QUARANTINED
            | CoverageState.UNSUPPORTED
            | CoverageState.UNAVAILABLE
        ):
            return True
        case (
            CoverageState.NOT_ENROLLED
            | CoverageState.ELIGIBLE
            | CoverageState.QUEUED
            | CoverageState.PARTIALLY_PROCESSED
            | CoverageState.STALE
            | CoverageState.SUPERSEDED
        ):
            return False
    assert_never(state)


def _coverage(
    connection: Connection, enrollment_id: str, *, moment: datetime, eligible: int | None
) -> CoverageCounts:
    """Read coverage, or fail as this module's own error rather than a bare one.

    `coverage_for` raises `ValueError` when the counts do not fit inside a
    denominator the caller supplied, which for search means the enrollment's
    named `object_ids` and the stored outcomes disagree about what is in scope.
    That is a real inconsistency and it must be reported, but as a typed error:
    an uncaught `ValueError` is outside section 10's taxonomy, carries no
    envelope, and reaches whoever is above this layer as an unclassified crash
    that leaves search dead for that enrollment with nothing to act on.
    Classified as internal rather than unavailable because retrying reads the
    same rows and fails the same way.

    No call this module makes can currently reach it, and that is a change
    rather than a claim about the design. It was reachable: an outcome recorded
    for an object the enrollment never named was counted, so the counts could
    exceed `cardinality(object_ids)`. `coverage_for` now counts only objects the
    enrollment authorizes, and there cannot be more distinct such objects than
    the array naming them holds. The guard stays because the reachability
    argument is about this caller and `coverage_for` is public: any caller may
    state a denominator its rows do not fit inside, and this one must not turn
    that into an untyped crash if it ever states a different one.

    The `raise` is outside the `except` block for the same reason it is in
    `_execute`: leaving the handler first is what keeps the original off
    `__context__`, and while this particular `ValueError` carries no identifier,
    a traceback rendered through it exposes the frames and locals of a coverage
    read. The message says nothing but that the search did not complete.
    """
    try:
        return coverage_for(connection, enrollment_id, observed_at=moment, eligible=eligible)
    except ValueError:
        pass
    raise SearchInternalError("the search could not be completed")


def search_extractions(
    connection: Connection, request: SearchRequest, *, now: datetime | None = None
) -> SearchPage:
    """Search one enrollment's extracted text and disclose what was searched.

    The order of the steps is the contract. The scope is resolved first, so an
    unknown enrollment is `not_found` rather than an empty result set. The query
    is checked for lexemes second, so a query with no terms is a typed error
    rather than a no-match claim. Coverage is read before the page is described,
    so a scope with nothing extracted in it produces a partial disclosure
    whatever the matches say — which is the whole of section 9.7's rule that "we
    found nothing" and "we have not indexed this" are different answers.

    `now` is a parameter so that freshness, coverage snapshots, and cursor
    expiry all read one clock and a test can fix it.
    """
    moment = ensure_utc(now) if now is not None else utc_now()
    position = request.position(moment)

    context = _context(connection, request)
    source_id, classification, root_object_id, named_objects, lexemes = context
    validate_identifier(str(source_id), IdKind.SOURCE)
    if int(lexemes) == 0:
        # No terms, so nothing was searched. Reporting zero matches here would
        # be the false no-match claim section 9.7 exists to prevent.
        raise EmptySearchQueryError("the query yielded no search terms")

    eligible_is_known = root_object_id is None
    rows = _matches(connection, request, position)
    truncated = len(rows) > request.page_size
    page = rows[: request.page_size]

    matches: list[SearchMatch] = []
    snippet_truncated = False
    for row in page:
        snippet, was_cut = bound_snippet(str(row.snippet))
        snippet_truncated = snippet_truncated or was_cut
        matches.append(
            SearchMatch(
                knowledge_id=str(row.extraction_id),
                label=label_for_media_type(row.media_type),
                snippet=snippet,
                rank=rank_category(float(row.rank)),
                # The matched object's source, not the enrollment's. See
                # `match_statement`. Pinned at the statement level and only
                # there, which is the honest level rather than a gap left open:
                # the boundary makes `source_objects.source_id` and
                # `enrollments.source_id` equal for every row this can return, so
                # reading either produces identical values and no comparison of
                # returned data can tell them apart.
                # `test_a_match_takes_its_source_from_the_matched_object` asserts
                # which column the statement selects, which is where the two are
                # still distinguishable.
                source_id=str(row.source_id),
                source_object_id=str(row.source_object_id),
                version_id=str(row.version_id),
            )
        )

    # The denominator, and the whole difficulty of this function. An enrollment
    # that named its objects has one that is stored and authoritative. One that
    # named a root has none, and `None` is how that is said: `coverage_for`
    # derives the total from what it accounted for, which is honest arithmetic
    # only because the caller stated it was unmeasured rather than quoting a
    # number. Three things keep the derived total from being read as a measured
    # scope: `_ELIGIBLE_UNKNOWN` is disclosed, the result is partial whatever the
    # counts say, and the reported state is clamped immediately below.
    counts = _coverage(
        connection,
        request.enrollment_id,
        moment=moment,
        eligible=int(named_objects) if eligible_is_known else None,
    )
    state = counts.state()
    if not eligible_is_known and _claims_the_whole_scope(state):
        # A denominator taken from the numerator divides out to all of it, so
        # every whole-scope state is available here and none of them is earned.
        # Whichever it is — the scope was processed, quarantined, unsupported,
        # unavailable — it is the machine-readable claim that a total nobody
        # measured was fully accounted for. `PARTIALLY_PROCESSED` is the honest
        # reading: objects reached outcomes, and how many more there are is not
        # known. The counts themselves are left alone; inventing a larger
        # denominator to force the state would be the invention this branch just
        # removed, put back one line lower.
        state = CoverageState.PARTIALLY_PROCESSED

    limitations = [
        *_limitation_tokens(connection, request.enrollment_id),
        _NO_STORED_LABEL,
    ]
    if not eligible_is_known:
        # Two facts, disclosed separately because they are separately actionable:
        # the denominator was never measured, and the numerator was not gathered
        # from the root the caller asked about but from everything its source
        # holds. A caller told only the first would read the counts as a partial
        # measurement of the right scope.
        limitations.append(_ELIGIBLE_UNKNOWN)
        limitations.append(_SCOPE_IS_SOURCE_WIDE)
    if counts.processed == 0:
        limitations.append(_NO_INDEXED_COVERAGE)
    elif counts.processed != counts.eligible:
        limitations.append(_COVERAGE_INCOMPLETE)
    if snippet_truncated:
        limitations.append(_SNIPPET_TRUNCATED)

    # No `eligible > 0` guard. `eligible_is_known` means the enrollment named its
    # objects, `enrollment_names_exactly_one_selector` makes that array non-empty
    # whenever `root_object_id` is null, and the denominator is
    # `cardinality(object_ids)` — so no arrangement of rows reaches this line with
    # a zero. A condition nothing can exercise is a claim nothing checks, which is
    # the rule `persistence.extraction` states once and this applies.
    complete = eligible_is_known and counts.processed == counts.eligible
    next_cursor = (
        SearchCursor(
            binding=request.binding,
            rank=float(page[-1].rank),
            knowledge_id=str(page[-1].extraction_id),
            issued_at=moment,
        ).encode()
        if truncated and page
        else None
    )

    disclosure = Disclosure(
        scope=Scope(source_ids=(str(source_id),), enrollment_ids=(request.enrollment_id,)),
        coverage=Coverage(
            state=state,
            eligible=counts.eligible,
            processed=counts.processed,
            quarantined=counts.quarantined,
            unsupported=counts.unsupported,
        ),
        freshness=Freshness(
            observed_at=moment,
            # Each match binds the exact `ver_…` its text was extracted from, so
            # the result is current *for that version*. Whether the source has
            # moved on since is a question this layer cannot answer and does not
            # claim to: that is what the version binding is for.
            state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION,
        ),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=("lexical_index",)),
        truncation=Truncation(
            is_truncated=truncated,
            reason="page_size_reached" if truncated else None,
            next_cursor=next_cursor,
        ),
        limitations=tuple(limitations),
        source_references=tuple(
            SourceReference(
                source_id=match.source_id,
                source_object_id=match.source_object_id,
                version_id=match.version_id,
            )
            for match in matches
        ),
        partial_result=truncated or not complete,
        classification=Classification(str(classification)),
        # Never true from a search. Eligibility is a field-level decision made
        # with an explicit purpose and principal, and a search has neither.
        cloud_eligible=False,
    )
    return SearchPage(matches=tuple(matches), disclosure=disclosure)
