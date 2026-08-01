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
it. So every statement here runs through `_execute`, which converts any
`SQLAlchemyError` into one of this module's own errors — *raised outside the
`except` block*, so the original is not left in `__context__` where a traceback
would render it. That makes the redaction a property of this module rather than
of a setting in a file this module does not own.

**The index exists, and the predicate has to stay identical to it.**
`knowledge.extractions` has no `tsvector` column and no trigger maintaining one.
What it has is a functional GIN index over the same expression this module
builds, created beside the table by revision `8b3f5c17d904`:

    CREATE INDEX extractions_full_text ON knowledge.extractions
      USING gin (to_tsvector('english', text));

PostgreSQL matches a functional index by expression tree, so that index and the
predicate below are one decision recorded in two files, and they must remain
character-identical. The configuration is named explicitly on both sides — which
is also what makes the expression `IMMUTABLE` and therefore indexable at all,
since the one-argument form is only `STABLE` — and it is written as a SQL
literal rather than a bound parameter, for the reason given at `_CONFIG`. Any
divergence at all, a different configuration or a cast or a `coalesce`, silently
plans a sequential scan that still returns correct rows, so no result-comparing
test can see it.

That the expressions do agree was measured rather than assumed. Against a table
of twenty thousand synthetic rows the predicate built below produces
`Bitmap Index Scan on extractions_full_text` with
`Index Cond: (to_tsvector('english'::regconfig, text) @@ …)`, and
`test_the_search_predicate_uses_the_functional_index_and_not_a_sequential_scan`
holds that continuously: it takes the `@@` predicate out of the statement
`match_statement` compiles — rather than writing an equivalent one, which is how
the same test previously came to prove nothing — and asserts the plan.

What is not claimed: that every search uses the index. A search also filters on
`enrollment_id` and `status`, and where that is the more selective pair the
planner will use `extractions_by_enrollment` and apply the match as a filter —
which is the right plan and is what it does at test-fixture scale. This module
also sets no statement timeout. The index removes the sequential scan as the
only possibility; it does not bound what a query can cost.

**`pg_trgm` is installed and deliberately unused.** `AGENTS.md` section 4 names
it alongside full-text search as an initial mechanism, and it answers a different
question — similarity, for fuzzy and misspelled input. Nothing in the accepted
objective asks for that, adding it would introduce a second relevance signal with
no benchmark to weigh it against the first, and `AGENTS.md` section 2 rules out
machinery with no current caller. It stays available.

**Coverage is read, not inferred, and the denominator is the hard part.**
`coverage_for` requires the eligible total from whoever enumerated the scope,
because deriving it from the rows that exist would report complete coverage of a
scope nobody measured. Search runs long after that enumeration and in another
process, so it can supply the total in exactly one case: an enrollment that named
its objects explicitly, where the count of `object_ids` *is* the authorized
scope. An enrollment selecting a root plus a depth has an eligible total that
only enumeration knows and that nothing persists, so search says so — the result
is partial, it carries `eligible_total_not_persisted`, and the coverage *state*
it reports is held below `processed`, because a state is machine-readable and
"the whole eligible scope was processed" is exactly the claim an unmeasured
denominator cannot support. A search cannot claim complete coverage it cannot
prove, and section 9.7 would rather have a partial disclosure than a confident
wrong one.

What that leaves, stated here rather than discovered later: for a root-selector
enrollment the reported counts and the reported state disagree. `eligible` is
set to what was accounted for, so `processed == eligible`, while the state is
held at `partially_processed`. A consumer that recomputes the state from the
counts therefore gets `processed` and contradicts the state beside it. That is
not an oversight in the clamp — it is the whole problem surfacing in the only
place the contract still allows it. `eligible` is a required integer in the v1
disclosure and no integer is true here: the enumerated total is the one number
that would be, and nothing persists it. The three signals that do not lie —
`eligible_total_not_persisted`, `partial_result`, and the state — are what a
consumer should read, and a consumer reading the counts alone will be wrong.

Fixing it properly means either persisting the eligible total at enrollment or
letting `eligible` be absent in the contract, and the second is a v1 change
gated by `P00-OD-004`. Both are out of scope here and are carried into WP-4."""

from __future__ import annotations

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
from my_pa.domain.extraction.coverage import AggregateLimitation, LimitationReason
from my_pa.domain.extraction.text import ExtractionStatus
from my_pa.domain.search.query import (
    EmptySearchQueryError,
    SearchCursor,
    SearchMatch,
    SearchRequest,
    bound_snippet,
    label_for_media_type,
    rank_category,
)
from my_pa.infrastructure.persistence.extraction import coverage_for
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollments,
    extractions,
    sources,
)

__all__ = [
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

#: The same configuration as it is written into the SQL: a literal, not a bound
#: parameter. The distinction is the difference between using the functional
#: index and not using it, and it was measured. Bound, the predicate compiles to
#: `to_tsvector($1, text)`, and matching it against an index on
#: `to_tsvector('english', text)` then depends on the server folding the
#: parameter to a constant while planning: it does under a custom plan and it
#: does not under `plan_cache_mode = force_generic_plan`, where the measured
#: plan is a sequential scan even with `enable_seqscan = off`. A literal makes
#: index matching a property of the expression rather than of which plan the
#: server chose.
#:
#: Safe here for one reason and no other: `SEARCH_CONFIG` is a module constant
#: that nothing outside this file can set. The caller's query text is never
#: treated this way — it is a `bindparam` in `_tsquery` and stays one.
_CONFIG: Final = literal_column(f"'{SEARCH_CONFIG}'", REGCONFIG)

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

    Character-identical to the expression `extractions_full_text` is built over.
    See the module docstring for what a divergence here costs and why nothing
    that compares rows would notice it.
    """
    return func.to_tsvector(_CONFIG, extractions.c.text)


def context_statement(request: SearchRequest) -> Select[Any]:
    """Everything about the scope that one row can answer, in one round trip.

    The enrollment's source and classification, whether its eligible total is
    knowable, and how many lexemes the query produced. The last is not an
    aggregate and the rest are plain columns, so they compose; asking for the
    lexeme count separately would be a second round trip for one integer.

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
            enrollments.c.max_items,
            func.numnode(_tsquery(request)).label("lexemes"),
        )
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
            extractions.c.source_object_id,
            extractions.c.version_id,
            extractions.c.media_type,
            headline.label("snippet"),
            rank.label("rank"),
        )
        .where(
            extractions.c.enrollment_id == request.enrollment_id,
            extractions.c.status == ExtractionStatus.EXTRACTED.value,
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
    source_id, classification, root_object_id, named_objects, ceiling, lexemes = context
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
                source_id=str(source_id),
                source_object_id=str(row.source_object_id),
                version_id=str(row.version_id),
            )
        )

    # The denominator, and the whole difficulty of this function. An enrollment
    # that named its objects has one that is stored and authoritative. One that
    # named a root has none, so `max_items` -- the ceiling the enrollment itself
    # authorizes, and therefore an upper bound `coverage_for` will accept -- is
    # used to obtain the counts, and the eligible total is then replaced by what
    # was actually accounted for. That replacement is not a measured scope, and
    # three things keep it from being presented as one: `_ELIGIBLE_UNKNOWN` is
    # disclosed, the result is partial whatever the counts say, and the reported
    # state is held below `PROCESSED` immediately below.
    counts = coverage_for(
        connection,
        request.enrollment_id,
        observed_at=moment,
        eligible=int(named_objects) if eligible_is_known else int(ceiling),
    )
    if not eligible_is_known:
        counts = replace(counts, eligible=counts.accounted)
    state = counts.state()
    if not eligible_is_known and state is CoverageState.PROCESSED:
        # A denominator taken from the numerator can only ever divide out to all
        # of it, so `PROCESSED` here would be the machine-readable claim that the
        # whole eligible scope was covered — over a total nobody measured, which
        # is the one claim this branch exists to avoid. `PARTIALLY_PROCESSED` is
        # the honest reading: objects were processed, and how many more there are
        # is not known. The counts themselves are left alone; inventing a larger
        # denominator to force the state would be a second invention on top of
        # the first.
        state = CoverageState.PARTIALLY_PROCESSED

    limitations = [
        *_limitation_tokens(connection, request.enrollment_id),
        _NO_STORED_LABEL,
    ]
    if not eligible_is_known:
        limitations.append(_ELIGIBLE_UNKNOWN)
    if counts.processed == 0:
        limitations.append(_NO_INDEXED_COVERAGE)
    elif counts.processed != counts.eligible:
        limitations.append(_COVERAGE_INCOMPLETE)
    if snippet_truncated:
        limitations.append(_SNIPPET_TRUNCATED)

    complete = eligible_is_known and counts.eligible > 0 and counts.processed == counts.eligible
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
