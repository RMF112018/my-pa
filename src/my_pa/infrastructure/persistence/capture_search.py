"""Exact lexical search over user-authored capture text.

A **second** plane, beside the extraction plane in `persistence.search`, and the
reason is not convenience. `knowledge.extractions.enrollment_id` is `NOT NULL`
with a foreign key created by an already-merged revision, and a capture has no
enrollment; relaxing that column is `D-76` on the identical column shape and was
already refused, while synthesising an enrollment per capture would fabricate a
grant that `extracted_text_in_scope`'s `authorized_object` condition would then
be satisfied by. `domain.identity.purpose` gives the other half of the argument:
one grant spanning both planes would let a knowledge-shaped request return raw
user-authored capture text.

**`simple`, not `english`, and it is measured rather than stylistic** (`D-90`).
`QC-AC-050` asks for *exact* original text to be searchable, and `english` fails
that in two ways that were measured on a live server:

- it stems, so `to_tsvector('english', '…running…')` stores `run` and a query
  for `run` matches a capture that never contains the word;
- it discards stop words, so `to_tsvector('english', 'a the of and')` is
  **empty** — a capture of nothing but stop words is saved, satisfies
  `a_capture_version_carries_text`, and is then unfindable by any query **with
  no exception anywhere**, which is the silent failure this plane exists to
  refuse.

`simple` keeps stop words and does not stem, so it is exact at word
granularity. **The cost is real and is disclosed rather than smoothed over**: a
search for `meetings` does not find `meeting`. That is the price of exactness,
it is the price the criterion asks for, and it belongs in the disclosure
envelope as a limitation rather than in a comment. This module publishes the
counts that limitation is built from; the envelope is assembled above it.

**The exact-substring confirmation** covers the residue `simple` still splits.
`RFI-0421` and `$12,500.00` are both broken into lexemes by the parser, so the
`@@` predicate matches them as adjacent lexemes rather than as the literal
string, and a document reading `12 500.00` matches a query for `$12,500.00`.
**Measured, because the example this docstring first carried was false**: the
money pair matches, but `RFI 0421` does *not* match a query for `RFI-0421`,
because `websearch_to_tsquery` keeps the hyphen in the second lexeme
(`'rfi' <-> '-0421'`) while the spaced document yields `'rfi','0421'`. The rule
is real; that illustration of it was not. A
query the server reports as one contiguous run of text is therefore confirmed
with `strpos(content, …) > 0` over the candidate rows, which is exact at
character granularity. It is a confirmation and never a substitute: `strpos`
cannot use the index, so it runs *after* the indexed predicate has narrowed the
page and never instead of it.

**What the confirmation tests, and what decides it, are both read from
PostgreSQL** — see `_NEEDLE_SQL`. Neither the syntax the query text carries nor
the punctuation the parser discards is decided here, because deciding either
here is how this filter came to remove correct rows twice. What it *cannot* see
is stated in `_exact_confirmation` and in the matrix that guards it.

**The index and the predicate must stay equal as expressions.**
`knowledge.capture_versions` has no `tsvector` column and no trigger maintaining
one. What it has is a functional GIN index over the same expression this module
builds, created by revision `2b7e9f4c1a83`:

    CREATE INDEX capture_versions_full_text ON knowledge.capture_versions
      USING gin (to_tsvector('simple', content));

PostgreSQL matches a functional index by expression tree, so that index and the
predicate below are one decision recorded in two files. A divergence — a
different configuration, most likely — **breaks silently**: the query drops back
to a sequential scan and still returns correct rows.
`tests/schema/test_capture_schema_migration.py` reads the index's stored
definition back against this module's configuration, so the equality is checked
rather than assumed.

**One predicate function and one statement builder** (`D-90`). `coverage_for`
and `match_statement` on the extraction plane diverged for six review rounds
because two predicate lists were *asserted equal* rather than *built once*.
Here `capture_text_in_scope` is written once and splatted by both the page
statement and the totals statement, and both are built by functions
parameterised over a `SearchPlane` — agreement by construction rather than by
comparison. The extraction plane is **not** instantiated as a second
`SearchPlane` here: `persistence.search` owns its own builder, with a join, a
rank, a headline and a keyset cursor that this plane has none of, and unifying
the two is a change to a merged module rather than a part of this package.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import (
    Column,
    ColumnElement,
    Row,
    Select,
    String,
    Table,
    and_,
    bindparam,
    case,
    column,
    func,
    literal_column,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.engine import Connection, CursorResult
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    OperationalError,
)
from sqlalchemy.exc import (
    TimeoutError as PoolTimeoutError,
)

from my_pa.contracts.ports import (
    CaptureSearchMatch,
    CaptureSearchOutcome,
    CaptureSearchRequest,
)
from my_pa.infrastructure.persistence.tables import capture_receipts, capture_versions

__all__ = [
    "CAPTURE_VERSIONS",
    "INDEXED_CONFIGURATIONS",
    "SEARCH_CONFIG",
    "SEARCH_INDEX",
    "CaptureSearchUnavailableError",
    "SearchPlane",
    "capture_text_in_scope",
    "document_vector",
    "match_statement",
    "search_captures",
    "totals_statement",
]

#: The text-search configuration, on both sides of the match. Named explicitly
#: rather than left to `default_text_search_config` for the two reasons
#: `persistence.search` gives: the two-argument `to_tsvector` is `IMMUTABLE` and
#: therefore indexable where the one-argument form is only `STABLE`, and a
#: session setting would let the same query mean different things to two
#: connections.
SEARCH_CONFIG: Final = "simple"

#: Every text-search configuration this module may compile into a statement.
#: Closed and checked rather than trusted, because `_configuration` interpolates
#: the name into SQL text. A configuration belongs here only once
#: `knowledge.capture_versions` carries a functional index over it — an
#: unindexed one is not a syntax error, it is the silent sequential scan the
#: module docstring describes.
INDEXED_CONFIGURATIONS: Final = frozenset({SEARCH_CONFIG})

#: The index revision `2b7e9f4c1a83` creates. Named here so the schema test can
#: ask the server for its definition and compare it against this module rather
#: than against the revision that wrote it.
SEARCH_INDEX: Final = "capture_versions_full_text"


class CaptureSearchUnavailableError(Exception):
    """The capture index could not be read.

    Carries no statement, no parameter, and no driver detail, for the reason
    `persistence.search` states at length: SQLAlchemy renders bound parameters
    into `DBAPIError` messages unless the engine hides them, and the bound
    parameter here is the caller's query text.
    """


class CaptureSearchInternalError(Exception):
    """The capture search failed for a reason that is this system's fault.

    Separated from unavailability because telling a caller to retry a missing
    column would be a lie with a retry budget attached.
    """


def _checked_configuration(name: str) -> str:
    """`name`, if it is one this module may compile into SQL.

    **Called once, at import, by `_PLANE_CONFIGURATIONS`.** It used to be called
    from three statement builders instead, and it reads `INDEXED_CONFIGURATIONS`
    — a module attribute — so the set that approved a name was whatever the
    attribute held when the statement was built rather than what the module
    declared. `Final` stops `mypy --strict` rebinding it inside the checked tree
    and stops nothing outside it. Resolving here means the check ran against the
    declared set, once, before any caller existed.
    """
    if name not in INDEXED_CONFIGURATIONS:
        raise ValueError("unsupported text-search configuration")
    return name


def _superseded_version_ids() -> Select[Any]:
    """The versions some later version supersedes, as a subquery.

    `supersedes_version_id` is `UNIQUE`, so a chain is a line and this is
    exactly the set of versions that are not the head of their capture.
    """
    return select(capture_versions.c.supersedes_version_id).where(
        capture_versions.c.supersedes_version_id.is_not(None)
    )


def _acknowledged_version_ids() -> Select[Any]:
    """The versions a receipt was issued for, as a subquery."""
    return select(capture_receipts.c.version_id)


def capture_text_in_scope() -> tuple[ColumnElement[bool], ...]:
    """Which rows of `capture_versions` hold text a capture search may return.

    One list, used by the page statement and by the totals beside it. When
    evaluated against one statement snapshot the two apply the same conditions
    because they are built from this call and not because two lists were
    compared and found to agree — the divergence that stood for six review
    rounds on the extraction plane and was false for two of six conditions.

    The two, and what each decides:

    * **Not superseded.** A revised capture's earlier version is history, and
      returning it as a match would present text the user replaced as text the
      user holds. It is still readable by `capture.read`, which is
      `QC-AC-010`'s "independently retrievable"; it is not *found*.
      `test_a_revised_capture_is_found_at_its_current_version_only` is what
      fails if this goes.
    * **Acknowledged.** A version with no receipt was never acknowledged to the
      caller that wrote it. Search is a read of what the product told someone it
      had kept, so a row that no receipt names is not in scope — and because
      both are written in one transaction, the only way to produce one is to
      write it past the writer, which is exactly the fault injection the
      quarantine tests use.

    **There is no owner condition, and its absence is structural** (`D-72`,
    `D-67`). Capture authorization is capability plus purpose; identity in this
    build is process-scoped, so owner equality would make the capability
    unusable across two processes while enforcing a distinction a
    single-local-principal deployment cannot make.
    `tests/capture/test_owner_is_not_authorization.py` fails the moment someone
    adds one here.

    **There is no processing-policy condition either.** `local_only` is the only
    value the column can hold, so a condition on it could never exclude a row —
    a condition nothing can exercise, which the extraction plane's own predicate
    docstring rules out. The policy is read where it decides something, which is
    `P-01`.
    """
    return (
        capture_versions.c.version_id.not_in(_superseded_version_ids()),
        capture_versions.c.version_id.in_(_acknowledged_version_ids()),
    )


@dataclass(frozen=True, slots=True)
class SearchPlane:
    """One searchable text column, and everything a statement over it needs.

    The shape `D-76`/`D-77` established for `JobPlane`: one implementation, and
    the plane says which table it runs against. What differs between planes is
    the table, the column, the configuration its index was built over, and the
    scope predicate; what does not differ is the statement, which is why the
    statement is written once below.
    """

    table: Table
    text_column: Column[str]
    configuration: str
    index_name: str


#: The capture plane. The only instance, and the module docstring says why the
#: extraction plane is not a second one.
CAPTURE_VERSIONS: Final = SearchPlane(
    table=capture_versions,
    text_column=capture_versions.c.content,
    configuration=SEARCH_CONFIG,
    index_name=SEARCH_INDEX,
)

#: Every plane this module will compile a statement for, beside the configuration
#: name it may write, checked once at import.
#:
#: This is `persistence.search`'s `_CONFIG`, carried across the one thing that
#: differs: this module is parameterised over a plane, so the name that reaches
#: `literal_column` arrives through a *parameter* of three public functions —
#: `document_vector`, `match_statement` and `totals_statement` all take
#: `plane: SearchPlane`. That is a live path from a caller's value to interpolated
#: SQL text, and until now the only thing on it was a check that re-read a module
#: attribute every time it ran. Resolving the pair here makes the admissible names
#: exactly the ones that passed the check at import, and makes them a property of
#: this table rather than of what any attribute holds later.
#:
#: A tuple of pairs compared by identity, not a mapping. `SearchPlane` holds a
#: `Column`, whose `__eq__` builds a SQL expression rather than answering a
#: question, so `plane in some_dict` is a comparison this module should not be
#: making. Identity is also the stricter rule and the honest one: the constant
#: above says there is one instance, and a caller holding a plane this module did
#: not construct is not a caller whose configuration name should be written into
#: a statement.
_PLANE_CONFIGURATIONS: Final = (
    (CAPTURE_VERSIONS, _checked_configuration(CAPTURE_VERSIONS.configuration)),
)


def _configuration_name(plane: SearchPlane) -> str:
    """The plane's configuration name, as it was checked at import.

    The only way a name reaches statement text, so it is also the only place an
    unregistered plane is refused. The message names the defect and not the
    value: a `SearchPlane`'s repr carries a `Table`.
    """
    for registered, name in _PLANE_CONFIGURATIONS:
        if plane is registered:
            return name
    raise ValueError("unsupported text-search configuration")


def _configuration(plane: SearchPlane) -> ColumnElement[Any]:
    """The plane's configuration as a SQL literal.

    A literal and not a bound parameter, and the distinction is the difference
    between using the functional index and not using it: bound, the predicate
    compiles to `to_tsvector($1, content)`, and matching that against an index
    over `to_tsvector('simple', content)` then depends on the server folding the
    parameter while planning, which it does not do under a generic plan. Writing
    a name into SQL is safe here because the name came out of the table above —
    not because of what `SEARCH_CONFIG` or `INDEXED_CONFIGURATIONS` currently is.
    """
    return literal_column(f"'{_configuration_name(plane)}'", REGCONFIG)


def document_vector(plane: SearchPlane = CAPTURE_VERSIONS) -> ColumnElement[Any]:
    """The indexed side of the match.

    The same expression the plane's functional index is built over — the same
    tree, which is what PostgreSQL matches an index by, and not the same
    characters, which it does not.
    """
    return func.to_tsvector(_configuration(plane), plane.text_column)


def _tsquery(request: CaptureSearchRequest) -> ColumnElement[Any]:
    """The parsed query, as one bound parameter and one named configuration.

    `websearch_to_tsquery` for the reason `persistence.search` measured: it
    understands a small, closed web-search syntax — a quoted phrase, `or`, and a
    leading `-` — and every `tsquery` operator a caller writes arrives as
    ordinary text. The query is a `bindparam` and nothing else touches it.
    """
    return func.websearch_to_tsquery(
        _configuration(CAPTURE_VERSIONS),
        bindparam("capture_search_text", value=request.query.text),
    )


#: The needle the exact confirmation tests for, or `NULL` where no character-
#: granularity test is meaningful. **Everything this decides is decided by
#: PostgreSQL**, and that is the point: the first two versions of the
#: confirmation asked Python questions about the *raw* query text, and the raw
#: text is not what the predicate means by the query.
#:
#: Two steps, both server-side.
#:
#: 1. **Trim the query to its literal content.** `websearch_to_tsquery` treats
#:    a double quote as syntax and a trailing full stop as nothing at all, so
#:    neither belongs in a substring test. What may be trimmed is not a
#:    character class written here — it is whatever the configuration's *own*
#:    parser reports as a `blank` token at the query's first or last position,
#:    read from `pg_ts_config` and `ts_token_type` rather than typed. Consecutive
#:    blanks arrive as one token, so first and last are the whole of each run.
#: 2. **Refuse the test unless the trimmed literal means what the query means.**
#:    `phraseto_tsquery` reads its whole argument as one adjacent run;
#:    `websearch_to_tsquery` produces `&`, `|` or `!` the moment the caller asked
#:    for something a contiguous substring cannot express. The two are equal
#:    exactly when the query *is* one run of text — which is exactly when a
#:    substring test is the right question — so the eligibility rule is an
#:    equality between two of the server's own parsers rather than a list of
#:    syntax elements somebody remembered.
#:
#: `NULL` is returned rather than a flag because the call site folds it with
#: `coalesce(…, '')` and `strpos(anything, '') = 1`, so an ineligible query
#: yields one statement with one always-true condition rather than a second
#: statement shape.
_NEEDLE_SQL: Final = """(
  SELECT CASE
           WHEN websearch_to_tsquery({configuration}, source.raw)
                = phraseto_tsquery({configuration}, trimmed.needle)
           THEN trimmed.needle
         END
    FROM (SELECT CAST(:capture_search_literal AS text) AS raw) AS source
    CROSS JOIN LATERAL (
      SELECT parser.prsname AS name,
             (SELECT kind.tokid FROM ts_token_type(parser.prsname) AS kind
               WHERE kind.alias = 'blank') AS blank
        FROM pg_ts_parser AS parser
        JOIN pg_ts_config AS configured ON configured.cfgparser = parser.oid
       WHERE configured.oid = CAST({configuration} AS regconfig)
    ) AS grammar
    CROSS JOIN LATERAL (
      SELECT COALESCE(MAX(CASE WHEN token.ord = 1 AND token.tokid = grammar.blank
                               THEN length(token.token) END), 0) AS lead,
             COALESCE(MAX(CASE WHEN token.ord = counted.total AND token.ord > 1
                                AND token.tokid = grammar.blank
                               THEN length(token.token) END), 0) AS trail
        FROM ts_parse(grammar.name, source.raw)
             WITH ORDINALITY AS token(tokid, token, ord)
        CROSS JOIN (SELECT count(*) AS total
                      FROM ts_parse(grammar.name, source.raw)) AS counted
    ) AS ends
    CROSS JOIN LATERAL (
      SELECT substring(source.raw
                       FROM CAST(1 + ends.lead AS int)
                       FOR CAST(length(source.raw) - ends.lead - ends.trail AS int)) AS needle
    ) AS trimmed
)"""


def _confirmation_needle(
    request: CaptureSearchRequest, plane: SearchPlane = CAPTURE_VERSIONS
) -> ColumnElement[Any]:
    """`_NEEDLE_SQL` as a scalar subquery, with the query text bound.

    A scalar subquery and not an inline expression, so the server evaluates it
    once as an initialisation plan rather than once per candidate row: nothing
    in it depends on the row.
    """
    configuration = f"'{_configuration_name(plane)}'"
    return (
        text(_NEEDLE_SQL.format(configuration=configuration))
        .bindparams(bindparam("capture_search_literal", value=request.query.text))
        .columns(column("needle", String))
        .scalar_subquery()
    )


def _exact_confirmation(
    request: CaptureSearchRequest, plane: SearchPlane = CAPTURE_VERSIONS
) -> tuple[ColumnElement[bool], ...]:
    """The character-granularity confirmation, on the query's literal content.

    One condition, always, so the statement below is one statement with one
    `where` however the query is shaped. Where the confirmation does not apply
    the needle is `NULL`, `coalesce` makes it the empty string, and
    `strpos(anything, '') = 1` — an always-true condition rather than an absent
    one.

    **This confirmation has now been wrong twice, in the same direction, and the
    direction is what matters.** Both times it removed a row the indexed
    predicate had correctly matched, and a removed row is an absence: there is
    no exception, no limitation token, and nothing in the answer that
    distinguishes "no capture says that" from "a capture says exactly that and
    this filter dropped it". Both times the cause was the same — **the
    confirmation and the predicate disagreed about what the query text means**:

    * **Case.** `to_tsvector('simple','Buyout review') @@
      websearch_to_tsquery('simple','buyout')` is true, because `simple`
      lowercases every lexeme, while `strpos('Buyout review','buyout') > 0` is
      false, because `strpos` compares bytes. Closed by folding both sides.
    * **Syntax.** The predicate reads `"buyout"` as the lexeme `buyout` and
      `buyout.` as the lexeme `buyout`, while a test against the *raw* text
      hunted the quotes and the full stop as content. Measured over query forms
      generated from the server's own character classification, **328 of 402**
      index-matching cells were dropped this way. Closed by asking the server
      what the query's literal content is, which is `_NEEDLE_SQL`.

    The confirmation still exists, and still removes rows, because the parser
    splits `$12,500.00` into adjacent lexemes and the indexed predicate
    therefore matches a document that says `12 500.00`. That removal is
    the whole purpose and is asserted as such in
    `tests/search_quality/test_exact_confirmation_matrix.py`. `lower` on the
    column is not an index concern: this condition runs after the indexed
    predicate has narrowed the page, never instead of it.
    """
    return (
        func.strpos(
            func.lower(plane.text_column),
            func.lower(func.coalesce(_confirmation_needle(request, plane), "")),
        )
        > 0,
    )


def match_statement(
    request: CaptureSearchRequest, plane: SearchPlane = CAPTURE_VERSIONS
) -> Select[Any]:
    """One bounded page of capture versions whose text matches `request`.

    Public, and the reason is a test rather than a caller: building a statement
    and running it are separate acts, and separating them lets a security test
    compile *this* statement and inspect the SQL that will actually be sent. A
    test that rebuilt an equivalent statement of its own would prove something
    about the test.

    **No snippet and no rank.** A snippet is capture content, and this answer is
    deliberately incapable of carrying any: identifiers, a version number, and a
    character count. `capture.read` is how a caller obtains the text, under its
    own capability and its own audit event. Ordering is newest-first by recorded
    time, which needs no score. The consequence — a caller cannot tell *why* a
    capture matched from the answer alone — is a limitation the envelope
    carries, not a silence.
    """
    return (
        select(
            plane.table.c.capture_id,
            plane.table.c.version_id,
            plane.table.c.version_number,
            func.length(plane.text_column).label("character_count"),
            plane.table.c.recorded_at,
        )
        .where(
            *capture_text_in_scope(),
            document_vector(plane).bool_op("@@")(_tsquery(request)),
            *_exact_confirmation(request, plane),
        )
        .order_by(plane.table.c.recorded_at.desc(), plane.table.c.version_id.desc())
        .limit(request.limit + 1)
    )


def totals_statement(plane: SearchPlane = CAPTURE_VERSIONS) -> Select[Any]:
    """How many versions the scope holds, and how many exist at all.

    Two counts in one statement and one snapshot, because a page beside a
    coverage figure read from a second snapshot is how a search reports "nothing
    found" for a scope that held something. The scoped count uses the same
    `capture_text_in_scope` the page does, so the two cannot disagree about
    which rows are in scope.

    **`count(CASE …)` rather than `count(*) FILTER (WHERE …)`, and not by
    preference.** `FunctionElement.filter` is untyped in SQLAlchemy's stubs at
    the declared floor (`2.0.20`) and typed by `2.0.51`, so the `FILTER` form is
    green on every local gate and fails `no-untyped-call` in the
    `dependency-floor` job alone. `# type: ignore[no-untyped-call]` is not the
    way out: `strict = true` enables `warn_unused_ignores`, so the ignore is
    itself an error at the installed version — a red floor job traded for a red
    `validate` job. The two aggregates are equivalent: `count(x)` counts
    non-NULL `x`, and a `CASE` with no `ELSE` yields NULL when the condition is
    FALSE *or* NULL, so both count exactly the rows the condition holds TRUE
    for. `and_` is load-bearing — the predicate arrives as a tuple and `FILTER`
    ANDs it, so anything less would widen the scope this count shares with the
    page.
    """
    scoped = func.count(case((and_(*capture_text_in_scope()), 1)))
    return select(scoped.label("searchable"), func.count().label("stored")).select_from(plane.table)


def _exactly_one(result: CursorResult[Any]) -> Row[Any]:
    """The single row. Raises for none and for more than one."""
    return result.one()


def _every_row(result: CursorResult[Any]) -> Sequence[Row[Any]]:
    """Every row the cursor holds."""
    return result.all()


def _execute[Rows](
    connection: Connection,
    statement: Select[Any],
    materialize: Callable[[CursorResult[Any]], Rows],
) -> Rows:
    """Run `statement`, materialize its rows, and convert any failure into a bare typed error.

    The classification and the materialization argument are `persistence.search`'s
    `_execute`, name for name and reason for reason, and that module argues both
    at length. The short form, because a reader here should not have to go and
    find it:

    - `materialize` is passed in rather than applied to a returned cursor, so
      the row-shape errors — `.one()` on an empty or a doubled result — are
      raised *inside* the handler instead of after it has been left. Structural
      rather than exploitable: `totals_statement` is an ungrouped aggregate and
      always returns exactly one row. What was false was the guarantee.
    - The retryable set is the exception hierarchy's and not a driver's habits.
      `DisconnectionError` and SQLAlchemy's `TimeoutError` (a pool checkout that
      waited out `pool_timeout`) are `SQLAlchemyError` subclasses that are
      neither `OperationalError` nor `InterfaceError`, and the builtin
      `TimeoutError` is an `OSError` — not a `SQLAlchemyError` at all, so it and
      the socket failures beside it escaped this function entirely.
    - The second handler is `Exception` for that last reason: a handler naming
      one library's base class cannot carry a promise about *any* failure.

    **The widening has a cost, and it is named here rather than left for a
    reader to discover.** `Exception` also catches the failures that are this
    module's own bugs — `TypeError`, `KeyError`, `AttributeError` — and turns
    each into `CaptureSearchInternalError`. The raise is outside the handler, so `__context__` is
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

    The `raise` statements are outside the `except` block on purpose: `raise …
    from None` clears `__cause__` and leaves the original in `__context__`,
    where a rendered traceback shows a `DBAPIError` whose message can contain
    the bound query text.
    """
    unavailable = False
    try:
        return materialize(connection.execute(statement))
    except (OperationalError, InterfaceError, DisconnectionError, PoolTimeoutError, OSError):
        unavailable = True
    except Exception:
        unavailable = False
    if unavailable:
        raise CaptureSearchUnavailableError("the capture index could not be read")
    raise CaptureSearchInternalError("the capture search could not be completed")


def search_captures(connection: Connection, request: CaptureSearchRequest) -> CaptureSearchOutcome:
    """One page of capture matches, with the counts a disclosure is built from.

    `truncated` is decided by asking for one row more than the page holds, which
    is how `capture.list` decides it too: a page that happens to be exactly full
    is not a truncated one, and a count-then-page would answer from two
    snapshots.
    """
    rows = list(_execute(connection, match_statement(request), _every_row))
    truncated = len(rows) > request.limit
    totals = _execute(connection, totals_statement(), _exactly_one)
    return CaptureSearchOutcome(
        matches=tuple(
            CaptureSearchMatch(
                capture_id=str(row.capture_id),
                version_id=str(row.version_id),
                version_number=int(row.version_number),
                character_count=int(row.character_count),
                recorded_at=row.recorded_at,
            )
            for row in rows[: request.limit]
        ),
        searchable_versions=int(totals.searchable),
        stored_versions=int(totals.stored),
        truncated=truncated,
    )
