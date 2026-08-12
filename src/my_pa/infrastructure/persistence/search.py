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
converts any exception at all into one of this module's own errors — *raised
outside the `except` block*, so the original is not left in `__context__` where a
traceback would render it. That makes the redaction a property of this module
rather than of a setting in a file this module does not own. `_execute` also
materializes the rows *inside* its own handler rather than returning a cursor for
the caller to unpack afterwards, which is what makes "every failure of a read"
mean the whole read and not the part before the dot.

There is no longer an exception for the read this module *delegates*. The
coverage read runs `coverage_for`'s statements rather than `_execute`'s, and
`_coverage` now classifies them with the same handler set, so a failure there
leaves as `SearchUnavailableError` or `SearchInternalError` like every other.
The rule this states is not held by this paragraph:
`tests/architecture/test_search_reads_leave_through_the_redaction_path.py`
derives every connection-touching call from this file's syntax tree — the
delegated one counts exactly as much as `connection.execute` — and fails if one
is written outside that shape, or if a `raise` moves back inside an `except`.
Prose is what let the delegated read stay open for a whole work package.

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
scale. That index's second column is `status`, and both this module and
`coverage_for` filter on it, because both take their scope from the one
definition `match_statement` names. The index removes the sequential scan as the
only possibility; it does not bound what a query can cost, and nothing in this
module ever did. What does is `MY_PA_STATEMENT_TIMEOUT_MS`, set as a connection
option by `create_database_engine` on every engine the gateway builds, so a
statement this module sends is cancelled by the server rather than run until it
finishes. A cancelled statement arrives as an `OperationalError` and leaves
through `_execute` as `SearchUnavailableError`, which is the honest answer: it is
retryable, and it is the one failure in the retryable set that says the query was
too expensive rather than that the server was unreachable.

**What a search returns is bounded by the enrollment's scope, both selectors.**
This was the largest of the things this module used to disclaim. A root-selector
enrollment was bounded by its *source* rather than by its root, because nothing
persisted the objects under a root, so an extraction stored for an object of the
same source outside the root was returned with an honest `source_object_id` and a
scope the caller had no way to check it against — and every such search carried
two limitation tokens, `_SCOPE_IS_SOURCE_WIDE` beside `_ELIGIBLE_UNKNOWN`, to say
so. Their literal values are deliberately not written anywhere in this file any
more: `test_no_disclosure_can_emit_the_two_removed_tokens` scans `src/` for them,
and a scan that tolerated prose would be a scan with an exception in it.
`knowledge.enrollment_objects` is the one fact that closed both:
`authorized_object` is now membership of the enumerated set, and the size of that
set is the eligible total `coverage_for` reads for itself. Two tokens, a state
clamp, and a `context_statement` column were deleted rather than reworded,
because a token nothing can emit is a vocabulary entry that can never fire.

Now claimed, where it was not: **every database read this function performs
leaves as one of this module's own errors** — the context read, the page, the
limitation tokens, and the coverage read it delegates. The last was the hole.
`_coverage` caught `ValueError` and nothing else, so a `ProgrammingError` from
`coverage_for` escaped as a `SQLAlchemyError` whose message carried the
statement and its bound `enrollment_id`. A schema fault rather than a query
fault, and no caller's text reached it, which is why it was disclosed here and
scheduled rather than fixed — and it was then carried into a work package that
shipped without closing it, which is the argument against keeping a guarantee in
a paragraph. `test_no_database_failure_in_any_read_a_search_performs_discloses_a_statement`
breaks a table under the delegated read and under one of this module's own, and
reads the rendered traceback rather than the message, because `__context__` is
where the leak was.

Still not claimed, and both are narrower than that sentence sounds. It is a
claim about *database* failures: a stored row that fails `validate_identifier`
or `Classification` still raises `ValueError` out of this function unwrapped,
carrying an identifier prefix rather than a statement or any caller text.
And `UnknownEnrollmentError` carries the enrollment identifier deliberately —
a caller that named a scope is entitled to be told which one was not found.

**What a search may match is one shared definition, not a list written twice.**
`match_statement`'s scope is `extraction.extracted_text_in_scope`, and so is
`coverage_for`'s `processed` count: one call, two uses. That is deliberately
structural: it shares predicates, not a transaction snapshot. This module
filtered on `enrollment_id` alone until recently, then grew a list of conditions
beside the coverage side's and asserted the two were equal — and they were not,
in two of six conditions, so a search could return a document's text under an
envelope reporting that the scope held none. A shared definition is the only
form of the predicate claim nothing has to re-check.

An enrollment whose allowlist names no type this extractor can read matches
nothing and reports `processed = 0`, which is the honest answer rather than a
case to special-case.

**`pg_trgm` is installed and deliberately unused.** `AGENTS.md` section 4 names
it alongside full-text search as an initial mechanism, and it answers a different
question — similarity, for fuzzy and misspelled input. Nothing in the accepted
objective asks for that, adding it would introduce a second relevance signal with
no benchmark to weigh it against the first, and `AGENTS.md` section 2 rules out
machinery with no current caller. It stays available.

**Coverage is read, not inferred, and this module no longer states a
denominator.** `coverage_for` reads its own eligible total from
`knowledge.enrollment_objects`, so search asks it for coverage and passes nothing
about the size of the scope. That is a deletion of machinery rather than a move
of it. Search used to supply the total in one case — an enrollment that named its
objects, where `cardinality(object_ids)` *is* the authorized scope — and `None`
in the other, which was `coverage_for`'s way of being told the denominator was
never measured. Before that it invented one: `max_items`, the enrollment's own
ceiling, which bounds what a single pass may do and not how many outcomes
accumulate across passes, so a long-lived enrollment exceeded it and the read
raised out of the coverage guard.

With `None` went everything built to keep it from being read as a measurement:
`_ELIGIBLE_UNKNOWN`, `_SCOPE_IS_SOURCE_WIDE`, `_claims_the_whole_scope`, and the
clamp that held a root-selector state at `partially_processed`. The clamp existed
because a total derived from the outcomes divides out to all of them, so "every
eligible object here was quarantined" was as available and as unfounded as "every
eligible object here was processed" — and it left the reported counts and the
reported state disagreeing with each other, which a consumer recomputing the
state from the counts would have noticed. A measured denominator makes both the
clamp and that contradiction unnecessary. `eligible` stays a required integer in
the v1 disclosure and is now always a true one, so `P00-OD-004` is untouched.

The identical logic was written out a second time in `application.disclosure`,
because the two layers may not import each other, and it is deleted there in the
same change. Deleting one and not the other is the defect class this package has
been blocked for; deletion is the only form of this fix that cannot leave a
divergence."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Final

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
    literal,
    literal_column,
    select,
    tuple_,
    union_all,
)
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
)
from sqlalchemy.exc import (
    TimeoutError as PoolTimeoutError,
)

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
    extracted_text_in_scope,
)
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollments,
    extractions,
    goodnotes_page_versions,
    goodnotes_pages,
    goodnotes_region_proposals,
    goodnotes_review_decisions,
    quarantine_records,
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
    "goodnotes_match_statement",
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
#:
#: `MinWords` earns its place by being strictly below `MaxWords` and by nothing
#: else, and both halves of that are measured. PostgreSQL raises `MinWords must
#: be less than MaxWords` when it is not — a `DataError`, which `_execute`
#: classifies as `SearchInternalError`. `MaxWords` is the caller's
#: `snippet_words`, whose floor is `MIN_SNIPPET_WORDS`, which is 5, so a constant
#: floor of 5 here made the narrowest snippet a caller may legally ask for fail
#: every query it was passed with;
#: `test_the_narrowest_snippet_a_request_may_ask_for_is_answerable` is that case.
#: What it does *not* do is change any snippet: in `MaxFragments` mode the window
#: is chosen by `MaxWords`, and across seven document shapes — match at the
#: start, at the end, a document shorter than the width, a one-word document —
#: varying `MinWords` changed no headline of a document that matched. It decides
#: only the fallback headline of a document that did *not*, which this module
#: never renders, because the `@@` predicate means every row it reaches matched.
#: So the ceiling is a bound on a value nothing else reads, and the reason it is
#: `snippet_words - 1` rather than a constant is the inequality above.
_HEADLINE_TEMPLATE: Final = (
    'StartSel="", StopSel="", MaxFragments=1, MaxWords={words}, MinWords={minimum}'
)

#: Limitation tokens this module can disclose. Closed values, like every other
#: token in the envelope, so `limitations` cannot become a free-text channel.
_NO_STORED_LABEL: Final = "result_label_is_media_type_only"
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


def _one_or_none(result: CursorResult[Any]) -> Row[Any] | None:
    """The single row, or `None`. Raises `MultipleResultsFound` for more."""
    return result.one_or_none()


def _every_row(result: CursorResult[Any]) -> Sequence[Row[Any]]:
    """Every row the cursor holds."""
    return result.all()


def _execute[Rows](
    connection: Connection,
    statement: Executable,
    materialize: Callable[[CursorResult[Any]], Rows],
) -> Rows:
    """Run `statement`, materialize its rows, and convert any failure into a bare typed error.

    **`materialize` is an argument rather than something the caller applies to
    the returned cursor, and that is the only reason it exists.** This function
    used to return the `CursorResult` itself, so every caller wrote
    `_execute(…).one_or_none()` or `_execute(…).all()` — and the `try` had
    already been left by the time the dot ran. `MultipleResultsFound` from
    `.one_or_none()` would therefore have propagated raw: outside section 10's
    taxonomy, outside the envelope, and past the redaction this module's whole
    contract is. **This is a structural defect and not an exploitable one, and
    the difference is worth stating rather than blurring.** Nothing reaches it
    today: the only `one_or_none` read filters on a primary key, and psycopg
    buffers a result set, so `.all()` performs no I/O after the cursor is
    returned. What was false was the *guarantee*, which says every failure of a
    read leaves through here. Passing the shape in makes the guarantee true by
    construction rather than by an argument about today's predicates.

    **The retryable set is derived from the exception hierarchy, not from the two
    names a driver happens to raise most.** `OperationalError` and
    `InterfaceError` alone left three retryable failures classified as this
    system's fault, and one of them was not classified at all:

    - `DisconnectionError` is a direct subclass of `SQLAlchemyError` and of
      neither of those two. A dropped connection is the definition of retryable.
    - `TimeoutError` — SQLAlchemy's, imported here as `PoolTimeoutError` because
      the builtin of that name means something else — is raised when a pool
      checkout waits out `pool_timeout`. It is reachable by construction rather
      than in principle: `create_database_engine` builds a pool of five with
      overflow disabled, and `bootstrap.gateway` builds two of them.
    - The builtin `TimeoutError` is an `OSError`, so it is not a
      `SQLAlchemyError` at all and **escaped this function entirely**, taking
      the socket-level failures beside it — `ConnectionResetError`,
      `BrokenPipeError` — with it. `OSError` is the class those belong to and it
      is caught as the class.

    The second handler is `Exception` and not `SQLAlchemyError` for the same
    reason. The contract this module publishes is that *any* failure of a read
    becomes one of its two errors carrying nothing; a handler naming one library's
    base class promises that only for that library's failures, which is how the
    builtin `TimeoutError` got out. Everything not named above is this system's
    fault, retrying will not help, and saying otherwise would be a false promise.

    **The widening has a cost, and it is named here rather than left for a
    reader to discover.** `Exception` also catches the failures that are this
    module's own bugs — `TypeError`, `KeyError`, `AttributeError` — and turns
    each into `SearchInternalError`. The raise is outside the handler, so `__context__` is
    empty by design; `SqlAlchemyUnitOfWork` then flattens it to
    `RepositoryFailureError`; and this repository has no logging anywhere in
    `src/`. So a programming error inside a read now reaches an operator as an
    envelope with no diagnostic in it, where before the widening it reached them
    as a traceback. That is a real loss of debuggability and it is not a
    laundering of one: the alternative is a handler naming one library's base
    class, which is exactly how the builtin `TimeoutError` escaped this function
    entirely. The redaction contract requires the wide handler; the cost is the
    price of it.

    **What would close it** is a sink that records the original where the caller
    cannot see it — a logger, or an audit row carrying a correlation identifier
    the envelope also carries. Neither exists in `src/` today and adding one is a
    new mechanism rather than a fix to this one, so it is disclosed here and not
    built.

    `KeyboardInterrupt` and `SystemExit` are unaffected. Both derive from
    `BaseException` and not from `Exception`, so a cancelled process still dies
    at the read rather than reporting that the search could not be completed.

    The `raise` statements are outside the `except` block on purpose. `raise …
    from None` clears `__cause__` and leaves the original in `__context__`,
    where a rendered traceback shows a `DBAPIError` whose message can contain
    the bound query text. Leaving the handler first is what actually empties it.
    """
    unavailable = False
    try:
        return materialize(connection.execute(statement))
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
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

    The enrollment's source and classification, and how many lexemes the query
    produced. The last is not an aggregate and the rest are plain columns, so
    they compose; asking for the lexeme count separately would be a second round
    trip for one integer.

    Neither selector column is among them any more, and that is the point of the
    change rather than a tidy-up. `root_object_id` was here to decide whether the
    eligible total was knowable and `cardinality(object_ids)` was the total it
    supplied when it was; `coverage_for` reads the enumerated total for itself,
    for both selectors, so neither column decides anything here. `max_items` was
    here before either of them, as the denominator for a root selector, and it
    was the wrong number: it bounds one pass's authorization rather than the
    outcomes an enrollment accumulates.

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
    row = _execute(connection, context_statement(request), _one_or_none)
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

    The `sorted` is ordering and not a condition, and no arrangement of rows can
    show it: `LimitationReason` has one member and
    `one_limitation_per_reason_per_snapshot` allows one row per reason per
    snapshot, so this read returns at most one row today. It is kept rather than
    removed because the rule this module applies to unexercisable *conditions*
    is about predicates that decide which rows a caller is shown, and this
    decides the order of a tuple in a disclosure. Deleting it would buy nothing
    and would make the envelope's token order depend on the planner the day a
    second reason exists.
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
        _every_row,
    )
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

    **What may be matched is `extracted_text_in_scope`, and that is a call rather
    than a list repeated here.** Everything this page is allowed to see —
    `enrollment_id`, `status`, the object dimension, the content dimension, and
    the two precedence exclusions — comes from that one function in
    `persistence.extraction`, which is also what `coverage_for`'s `processed`
    count is built from. Within one statement snapshot they apply one predicate
    set structurally, so there is no second list to drift from the first. Across
    search's separate READ COMMITTED statements, concurrent changes can still
    produce `processed == 0` beside a non-empty page; `search_extractions`
    carries that window to WP-4 explicitly.
    Which matters because it happened. Two conditions lived on the coverage side
    only — an object quarantined at one version and extracted at a later one, or
    recorded unsupported at a later one, was excluded from the count and returned
    by the page, so a search answered with a document's own text while the
    envelope beside it said `no_extracted_text_in_scope`. That is the collapse of
    "we found nothing" into "we have not indexed this" that section 9.7 makes
    this module's reason for existing, inverted. The precedence is
    `coverage_for`'s and quarantine wins there on fail-closed grounds; this now
    honours it, so a stopped object's text is not returned as a live hit.
    `test_a_quarantine_at_one_version_withholds_the_text_extracted_at_another`
    and
    `test_an_object_extracted_at_one_version_and_unsupported_at_another_is_counted_once`
    build exactly that state and assert both sides of it.

    The one thing the two do not share is arithmetic. `coverage_for` counts
    distinct objects and this returns rows, so an object with two authorized
    extracted versions is one processed object and two matches; within one
    statement snapshot the predicate sets agree, the totals need not, and
    nothing here claims otherwise.

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
                words=request.snippet_words, minimum=min(request.snippet_words - 1, 5)
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
            *extracted_text_in_scope(request.enrollment_id),
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


def _accepted_goodnotes_text() -> ColumnElement[Any]:
    return func.coalesce(
        goodnotes_review_decisions.c.corrected_text,
        goodnotes_region_proposals.c.transcription,
    )


def _goodnotes_scope(enrollment_id: str) -> tuple[ColumnElement[bool], ...]:
    return (
        goodnotes_review_decisions.c.disposition.in_(("accept", "correct_and_accept")),
        goodnotes_review_decisions.c.knowledge_id.is_not(None),
        authorized_object(
            goodnotes_pages.c.source_object_id,
            enrollment_id=enrollment_id,
        ),
        authorized_media_type(literal("text/plain", Text), enrollment_id=enrollment_id),
        goodnotes_pages.c.source_object_id.not_in(
            select(quarantine_records.c.source_object_id).where(
                quarantine_records.c.enrollment_id == enrollment_id
            )
        ),
        goodnotes_pages.c.source_object_id.not_in(
            select(extractions.c.source_object_id).where(
                extractions.c.enrollment_id == enrollment_id,
                extractions.c.status == "unsupported",
            )
        ),
    )


def goodnotes_match_statement(request: SearchRequest, position: SearchCursor | None) -> Select[Any]:
    """Accepted OCR regions in the exact enrollment searched by knowledge.search."""
    query = _tsquery(request)
    accepted_text = _accepted_goodnotes_text()
    document = func.to_tsvector(_CONFIG, accepted_text)
    rank = cast(func.ts_rank_cd(document, query, RANK_NORMALIZATION), Float)
    headline = func.ts_headline(
        _CONFIG,
        accepted_text,
        query,
        bindparam(
            "goodnotes_headline_options",
            value=_HEADLINE_TEMPLATE.format(
                words=request.snippet_words, minimum=min(request.snippet_words - 1, 5)
            ),
            type_=Text,
        ),
    )
    statement = (
        select(
            goodnotes_review_decisions.c.knowledge_id.label("extraction_id"),
            source_objects.c.source_id,
            goodnotes_pages.c.source_object_id,
            goodnotes_page_versions.c.source_version_id.label("version_id"),
            literal("text/plain", Text).label("media_type"),
            headline.label("snippet"),
            rank.label("rank"),
        )
        .select_from(
            goodnotes_review_decisions.join(
                goodnotes_region_proposals,
                tuple_(
                    goodnotes_region_proposals.c.principal_id,
                    goodnotes_region_proposals.c.region_id,
                )
                == tuple_(
                    goodnotes_review_decisions.c.principal_id,
                    goodnotes_review_decisions.c.region_id,
                ),
            )
            .join(
                goodnotes_page_versions,
                tuple_(
                    goodnotes_page_versions.c.principal_id,
                    goodnotes_page_versions.c.page_version_id,
                )
                == tuple_(
                    goodnotes_region_proposals.c.principal_id,
                    goodnotes_region_proposals.c.page_version_id,
                ),
            )
            .join(
                goodnotes_pages,
                tuple_(goodnotes_pages.c.principal_id, goodnotes_pages.c.page_id)
                == tuple_(
                    goodnotes_page_versions.c.principal_id,
                    goodnotes_page_versions.c.page_id,
                ),
            )
            .join(
                source_objects,
                source_objects.c.source_object_id == goodnotes_pages.c.source_object_id,
            )
        )
        .where(*_goodnotes_scope(request.enrollment_id), document.bool_op("@@")(query))
        .order_by(rank.desc(), goodnotes_review_decisions.c.knowledge_id.desc())
        .limit(request.page_size + 1)
    )
    if position is not None:
        statement = statement.where(
            tuple_(rank, goodnotes_review_decisions.c.knowledge_id)
            < tuple_(
                bindparam("cursor_rank", value=position.rank, type_=Float),
                bindparam("cursor_knowledge_id", value=position.knowledge_id, type_=Text),
            )
        )
    return statement


def _matches(
    connection: Connection, request: SearchRequest, position: SearchCursor | None
) -> list[Row[Any]]:
    ordinary = _execute(connection, match_statement(request, position), _every_row)
    goodnotes = _execute(connection, goodnotes_match_statement(request, position), _every_row)
    return sorted(
        (*ordinary, *goodnotes),
        key=lambda row: (float(row.rank), str(row.extraction_id)),
        reverse=True,
    )[: request.page_size + 1]


def _coverage(connection: Connection, enrollment_id: str, *, moment: datetime) -> CoverageCounts:
    """Read coverage, or fail as this module's own error rather than a bare one.

    **This is the delegated read, and it is classified exactly like the
    statements this module builds.** `coverage_for` runs its own statements on
    this connection, so `_execute` never sees them; until this guard caught a
    `SQLAlchemyError`, a `ProgrammingError` from the coverage read left
    `search_extractions` as a `DBAPIError` whose message carried the SQL and the
    bound `enrollment_id`. Not the query-leak path — nothing on this side binds
    the caller's text — but the same class of hole, and it is the one thing the
    module docstring used to carry as open. The handler set is `_execute`'s, name
    for name, so the retryable set stays retryable and everything else stays
    internal; `_execute` argues that set, and
    `tests/architecture/test_search_reads_leave_through_the_redaction_path.py`
    is what fails if a future read is added outside this shape or if either
    handler drops a name.

    `coverage_for` also raises `ValueError` — through `CoverageCounts` — when the
    counts it assembles do not fit inside its own eligible total. It is no longer
    named in the handler, because the second one is `Exception` and names
    nothing: a `ValueError` is not a database failure, and the point of the wider
    handler is that this function does not have to enumerate the ways a delegated
    read can fail in order to keep classifying them.

    **`ValueError` is no longer the only non-database failure caught here, and
    saying only that it is still caught would understate the change.**
    `TypeError`, `KeyError` and `AttributeError` — every programming error inside
    `coverage_for` — join it, and each now becomes `SearchInternalError` with an
    empty `__context__` instead of a traceback. `_execute` states that cost in
    full and it applies here identically; the delegated read is the larger
    surface of the two, because `coverage_for` is a whole function rather than
    one `connection.execute`. That is a real
    inconsistency and it must be reported, but as a typed error: an uncaught
    `ValueError` is outside section 10's taxonomy, carries no envelope, and
    reaches whoever is above this layer as an unclassified crash that leaves
    search dead for that enrollment with nothing to act on. Classified as
    internal rather than unavailable because retrying reads the same rows and
    fails the same way.

    No call this module makes can reach it. Every count `coverage_for` takes is
    restricted to `enrollment_objects` membership and the total is `count(*)` of
    those same rows, and this module declares neither `queued` nor `unavailable`,
    which are the only two terms a caller still contributes. The guard stays
    because the reachability argument is about this caller and `coverage_for` is
    public: another caller may declare queued work against a scope smaller than
    it, and a broken store — outcome rows whose enumerated row has gone — is the
    other arrangement that produces it. This one must not turn either into an
    untyped crash.

    The `raise` statements are outside the `except` block for the same reason
    they are in `_execute`: leaving the handler first is what keeps the original
    off `__context__`, where a rendered traceback would print the `DBAPIError`
    and its parameters. The `ValueError` carries no identifier of its own, but a
    traceback rendered through either exposes the frames and locals of a
    coverage read. The messages say nothing but that the search did not
    complete, and they are `_execute`'s two messages so that a caller cannot
    tell which read failed.
    """
    unavailable = False
    try:
        counts = coverage_for(connection, enrollment_id, observed_at=moment)
        processed_objects = union_all(
            select(extractions.c.source_object_id).where(*extracted_text_in_scope(enrollment_id)),
            select(goodnotes_pages.c.source_object_id)
            .select_from(
                goodnotes_review_decisions.join(
                    goodnotes_region_proposals,
                    tuple_(
                        goodnotes_region_proposals.c.principal_id,
                        goodnotes_region_proposals.c.region_id,
                    )
                    == tuple_(
                        goodnotes_review_decisions.c.principal_id,
                        goodnotes_review_decisions.c.region_id,
                    ),
                )
                .join(
                    goodnotes_page_versions,
                    tuple_(
                        goodnotes_page_versions.c.principal_id,
                        goodnotes_page_versions.c.page_version_id,
                    )
                    == tuple_(
                        goodnotes_region_proposals.c.principal_id,
                        goodnotes_region_proposals.c.page_version_id,
                    ),
                )
                .join(
                    goodnotes_pages,
                    tuple_(goodnotes_pages.c.principal_id, goodnotes_pages.c.page_id)
                    == tuple_(
                        goodnotes_page_versions.c.principal_id,
                        goodnotes_page_versions.c.page_id,
                    ),
                )
            )
            .where(*_goodnotes_scope(enrollment_id)),
        ).subquery()
        processed = int(
            connection.execute(
                select(func.count(func.distinct(processed_objects.c.source_object_id)))
            ).scalar_one()
        )
        return replace(counts, processed=processed)
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
        unavailable = False
    if unavailable:
        raise SearchUnavailableError("the lexical index could not be read")
    raise SearchInternalError("the search could not be completed")


def search_extractions(
    connection: Connection, request: SearchRequest, *, now: datetime | None = None
) -> SearchPage:
    """Search one enrollment's extracted text and disclose what was searched.

    The order of the steps is the contract. The scope is resolved first, so an
    unknown enrollment is `not_found` rather than an empty result set. The query
    is checked for lexemes second, so a query with no terms is a typed error
    rather than a no-match claim. The page and coverage are separate READ
    COMMITTED statements: their shared predicate set makes them agree only
    within one statement snapshot. A quarantine committed between them can make
    the later coverage read contradict the page; that cross-statement window is
    a named WP-4 item rather than an impossible state claimed here.

    `now` is a parameter so that freshness, coverage snapshots, and cursor
    expiry all read one clock and a test can fix it.
    """
    moment = ensure_utc(now) if now is not None else utc_now()
    position = request.position(moment)

    context = _context(connection, request)
    source_id, classification, lexemes = context
    validate_identifier(str(source_id), IdKind.SOURCE)
    if int(lexemes) == 0:
        # No terms, so nothing was searched. Reporting zero matches here would
        # be the false no-match claim section 9.7 exists to prevent.
        raise EmptySearchQueryError("the query yielded no search terms")

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

    # The denominator was the whole difficulty of this function and is now
    # nobody's argument to pass: `coverage_for` reads the enumerated total of
    # this enrollment's own objects, for a root selector exactly as for a named
    # one. There is no unmeasured case left to disclose and no state to hold
    # down, so the state is the counts' own.
    counts = _coverage(connection, request.enrollment_id, moment=moment)
    state = counts.state()

    limitations = [
        *_limitation_tokens(connection, request.enrollment_id),
        _NO_STORED_LABEL,
    ]
    if counts.processed == 0:
        limitations.append(_NO_INDEXED_COVERAGE)
    elif counts.processed != counts.eligible:
        limitations.append(_COVERAGE_INCOMPLETE)
    if snippet_truncated:
        limitations.append(_SNIPPET_TRUNCATED)

    # No `eligible > 0` guard. `record_scope` refuses an empty set and rolls the
    # accepting transaction back with it, so an enrollment that exists holds at
    # least one object and no arrangement of rows reaches this line with a zero
    # denominator. A condition nothing can exercise is a claim nothing checks,
    # which is the rule `persistence.extraction` states once and this applies.
    complete = counts.processed == counts.eligible
    # No `and page`. `page_size` is bounded below by one, `truncated` means more
    # rows came back than that, and `page` is the first `page_size` of them — so
    # a truncated result cannot have an empty page and the test decided nothing.
    # It is the same rule `persistence.extraction` states and the same rule that
    # removed the `eligible > 0` guard above; applying it at one site and not at
    # its neighbour is what this branch has been blocked for before.
    next_cursor = (
        SearchCursor(
            binding=request.binding,
            rank=float(page[-1].rank),
            knowledge_id=str(page[-1].extraction_id),
            issued_at=moment,
        ).encode()
        if truncated
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
