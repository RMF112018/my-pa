"""The search query is data, and is proved to be data twice over.

`docs/specs` section 9.7: "Query is data and safely parameterized; no raw
SQL/parser control." That is one sentence covering two different hazards, and a
test for either alone would report a guarantee nobody checked.

**The SQL hazard.** A query concatenated into a statement is arbitrary SQL. The
first half of this file compiles the statements `search` actually sends — not
equivalent statements the test built, which would prove something about the
test — and asserts that each payload appears among the *bound parameters* and
nowhere in the SQL text.

**The parser hazard.** A query handed to `to_tsquery` is not SQL injection, but
it is still control: the caller's string becomes the query's operator tree, and
a malformed one becomes `ERROR: syntax error in tsquery`, which reaches the
caller as a database failure instead of an answer about their request.
`test_the_parser_control_this_module_refuses_is_real` demonstrates that hazard
against the live server before the tests beside it assert that
`websearch_to_tsquery` does not have it, so "we chose the safe form" is
performed rather than argued.

**Non-vacuity is performed, not asserted.** `test_the_injection_payload_is_live`
runs the same payload through an *interpolated* statement against a canary table
in a disposable database and requires the canary to be destroyed. If that fails,
the payload is inert and every "the canary survived" assertion beside it would
be meaningless. This is the same discipline as
`tests/security/test_containment_denial.py`, where an escape that stopped
escaping would make the denial tests pass while proving nothing.

Every database test runs against a disposable database created and dropped by
its fixture, never the configured one, and every value inserted is synthetic.
"""

from __future__ import annotations

import io
import os
import secrets
import traceback
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    InterfaceError,
    OperationalError,
    ProgrammingError,
)
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.extraction.text import extract_text
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import (
    MAX_QUERY_CHARACTERS,
    EmptySearchQueryError,
    SearchQuery,
    SearchQueryError,
    SearchRequest,
)
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import capture_search as capture_search_module
from my_pa.infrastructure.persistence import search as search_module
from my_pa.infrastructure.persistence.capture_search import (
    CAPTURE_VERSIONS,
    CaptureSearchInternalError,
    CaptureSearchUnavailableError,
    SearchPlane,
    document_vector,
)
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.extraction import record_outcome
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.search import (
    SEARCH_CONFIG,
    SearchInternalError,
    SearchUnavailableError,
    context_statement,
    match_statement,
    search_extractions,
)

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name, so a run interrupted before teardown is cleaned up by the next
#: one. Distinct from every other suite's disposable database.
DISPOSABLE_DATABASE = "my_pa_search_injection_test"

#: The canary. A table whose only purpose is to be destroyed by an interpolated
#: payload and to survive a bound one. In `public`, not `knowledge`, so that
#: creating it cannot interfere with the schema under test or with the
#: `RESTRICT` drop the knowledge revision's downgrade performs.
CANARY = "public.injection_canary"

#: The payload that destroys the canary. Written once and used in both
#: directions: interpolated, to prove it works, and bound, to prove it does not.
DROP_PAYLOAD = f"x'; DROP TABLE {CANARY}; --"

#: The injection that actually applies at *this* site, and the reason it is
#: written out separately from the one above. What follows was measured, because
#: the first version of this comment guessed and guessed wrong.
#:
#: A statement terminator needs the simple query protocol to reach a second
#: statement, and search never uses it: SQLAlchemy binds the enrollment
#: identifier whatever happens to the query, so psycopg sends the extended
#: protocol, which permits exactly one statement. Interpolated, `DROP_PAYLOAD`
#: at this site is a syntax error and not a dropped table. The reachable damage
#: is not defacement but disclosure — a `WHERE` clause that becomes true for
#: every row returns the whole scope's extracted text to a caller who asked for
#: something else.
#:
#: This payload does that. It closes the `websearch_to_tsquery` call, disjoins a
#: true predicate, and reopens a call so the tail still parses.
#: `test_the_argument_escape_is_live` runs it interpolated against the real
#: table and requires every row back.
#:
#: One honest complication, which matters because it would otherwise look like a
#: defence. Planting the interpolation in `_tsquery` does not produce a widened
#: search: the same text is embedded in two places, and the other one is
#: `numnode(...)`, which requires a `tsquery` and fails with "argument of OR must
#: be type boolean" before the match statement ever runs. So the *observed*
#: failure under that plant is an error rather than a disclosure. That is an
#: accident of which statement runs first, not a barrier — the predicate itself
#: widens, as the test proves directly — and the thing standing between this
#: payload and the corpus is the bind, nothing else.
ARGUMENT_ESCAPE = (
    "y') OR (true) OR to_tsvector('english', text) @@ websearch_to_tsquery('english', 'z"
)

WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/injection/corpus"

#: One document, so that "the corpus is intact" is a count with a value.
DOCUMENT = b"The northern division filed a quarterly revenue report on Friday."

#: Everything a caller might try. Each entry is one payload and one reason it is
#: here; a payload with no stated reason is a payload nobody thought about.
PAYLOADS: dict[str, str] = {
    "statement terminator": DROP_PAYLOAD,
    "argument escape": ARGUMENT_ESCAPE,
    "quote escape": "' OR '1'='1",
    "doubled quote": "'' OR 1=1 --",
    "backslash quote": "\\' OR 1=1",
    "line comment": "revenue -- comment",
    "block comment": "revenue /* comment */ report",
    "psql meta command": "revenue \\g",
    "dollar quoting": "$$ ; DROP TABLE x; $$",
    "union select": "' UNION SELECT text FROM knowledge.extractions --",
    "copy to program": "'; COPY (SELECT 1) TO PROGRAM 'id'; --",
    "format specifier": "%s %(search_text)s :search_text",
    "tsquery and": "revenue & report",
    "tsquery or": "revenue | report",
    "tsquery not": "!revenue",
    "tsquery phrase operator": "revenue <-> report",
    "tsquery prefix": "revenu:*",
    "tsquery weight": "revenue:AB",
    "valid tsquery expression": "revenue & !report | (northern <-> division)",
    "tsquery syntax error": "revenue &",
    "unbalanced parenthesis": "((((revenue",
    "unbalanced quote": '"revenue',
    "nul escaped textually": "revenue\\0report",
    # Escaped rather than pasted, so a reader can see which characters these
    # are: fullwidth Latin, a decomposed and a composed accent, and a
    # right-to-left mark sitting between two ordinary words.
    "unicode fullwidth": "\uff52\uff45\uff56\uff45\uff4e\uff55\uff45",
    "unicode decomposed": "café revenue",
    "unicode composed": "caf\u00e9 revenue",
    # A Cyrillic homoglyph: a letter, so it is accepted, and it is a
    # different word from the Latin spelling, which is the honest answer.
    "cyrillic homoglyph": "r\u0435venue",
    "long": "revenue " * 60,
    "at the length ceiling": "r" * MAX_QUERY_CHARACTERS,
}

#: Payloads the domain layer refuses outright, so they never reach a statement.
#: Kept separate rather than dropped: "it is rejected earlier" is a claim that
#: has to be checked too, and a later relaxation of the domain rule would move a
#: payload from this list into the one above without anyone noticing.
REFUSED_PAYLOADS: dict[str, str] = {
    "embedded null byte": "revenue\x00report",
    "bell character": "revenue\x07report",
    "bidi override": "revenue\u202ereport",
    "right to left mark": "revenue\u200freport",
    "over the length ceiling": "r" * (MAX_QUERY_CHARACTERS + 1),
}


def identifier(kind: IdKind) -> str:
    return make_identifier(kind, secrets.token_hex(16))


def build_request(payload: str) -> SearchRequest:
    return SearchRequest(enrollment_id=identifier(IdKind.ENROLLMENT), query=SearchQuery(payload))


def compiled_pair(payload: str) -> list[tuple[str, dict[str, object]]]:
    """Both statements `search` sends, compiled for PostgreSQL.

    Compiled without `literal_binds`, because that is how they are executed: the
    driver receives the SQL and the parameters separately, and the whole claim
    is that the payload is only ever in the second.
    """
    request = build_request(payload)
    dialect = postgresql.dialect()
    return [
        (str(compiled), dict(compiled.params))
        for compiled in (
            context_statement(request).compile(dialect=dialect),
            match_statement(request, None).compile(dialect=dialect),
        )
    ]


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_no_payload_reaches_the_statement_text(name: str) -> None:
    """The core claim, against the statements that actually run.

    The normalized query is looked for rather than the raw payload, because
    normalization is what a statement would carry: asserting the raw form would
    let a payload pass simply because whitespace in it had been collapsed.
    """
    payload = PAYLOADS[name]
    normalized = SearchQuery(payload).text
    found_bound = False
    for sql, parameters in compiled_pair(payload):
        assert normalized not in sql, f"{name} reached the SQL"
        for fragment in ("DROP TABLE", "UNION SELECT", "COPY (", "$$"):
            assert fragment not in sql, f"{name} put {fragment!r} into the SQL"
        if "search_text" in parameters:
            assert parameters["search_text"] == normalized
            found_bound = True
    assert found_bound, "the payload was in neither the SQL nor the parameters"


@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_the_statement_carries_a_placeholder_where_the_query_would_be(name: str) -> None:
    """The paired positive.

    A statement that had dropped the query entirely would satisfy every "not in
    the SQL" assertion above. What must be there is a bind placeholder, and the
    query must be the value behind it.
    """
    for sql, parameters in compiled_pair(PAYLOADS[name]):
        assert "%(search_text)s" in sql
        assert "search_text" in parameters


@pytest.mark.parametrize("name", sorted(REFUSED_PAYLOADS))
def test_a_payload_the_domain_refuses_never_becomes_a_statement(name: str) -> None:
    with pytest.raises(SearchQueryError):
        build_request(REFUSED_PAYLOADS[name])


def test_a_query_of_only_punctuation_is_a_well_formed_query_here() -> None:
    """Where the emptiness check can and cannot live, stated rather than assumed.

    `!!!` is a legal string by every rule this repository can apply in Python:
    it is short, it is printable, and it contains no control characters. Whether
    it yields any *lexemes* is a question only PostgreSQL's dictionary can
    answer, so the emptiness check is at the server and the corresponding
    assertion is in the database tier below. Writing it here would have produced
    a test that failed for the right reason and taught the wrong lesson.
    """
    for payload in ("!!!", "***", "--", "###"):
        assert SearchQuery(payload).text == payload


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """Create an empty database at head, and drop it when the module is done.

    Module-scoped deliberately. Creating a database and running eight
    revisions costs about two and a half seconds, and doing it once per test
    across the payload matrix put this file alone over the whole PR tier's
    budget. Every test below either only reads, or restores what it changed, so
    sharing the database costs no isolation that matters.

    `monkeypatch` is function-scoped and cannot be used here, so the environment
    is set and restored by hand. Only Alembic needs it: `create_database_engine`
    is handed the URL directly.
    """
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        administer(drop)
        maintenance.dispose()


@pytest.fixture(scope="module")
def corpus(disposable_database: str) -> Iterator[tuple[Engine, str]]:
    """A database at head holding one synthetic document, plus the canary."""
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            source = register_source(
                connection,
                provider_kind=SourceProviderKind.FIXTURE,
                label="Synthetic corpus",
                classification=Classification.SYNTHETIC_TEST,
                native_root=NATIVE_ROOT,
            )
            observed = observe_object(
                connection,
                source_id=source.source_id,
                native_locator=f"{NATIVE_ROOT}/report.md",
                kind=ObjectKind.FILE,
                fingerprint="fingerprint-one",
                modified_at=WHEN,
                media_type="text/markdown",
                size_bytes=len(DOCUMENT),
            )
            accepted = accept_enrollment(
                connection,
                EnrollmentRequest(
                    source_id=source.source_id,
                    principal_id=issue_identifier(IdKind.PRINCIPAL),
                    purpose=Purpose.BOUNDED_ENROLLMENT,
                    scope=EnrollmentScope(object_ids=(observed.source_object_id,)),
                    media_types=("text/markdown",),
                    policy_version="mcv-1",
                    idempotency_key="injection-000001",
                    max_items=10,
                    max_bytes=100_000,
                ),
            )
            # The enumerated object set, which every read restricts to and whose
            # size is the eligible total coverage reads for itself. An enrollment
            # without one authorizes nothing at all.
            record_scope(connection, accepted.enrollment.enrollment_id, [observed.source_object_id])
            record_outcome(
                connection,
                enrollment_id=accepted.enrollment.enrollment_id,
                outcome=extract_text(
                    source_id=source.source_id,
                    source_object_id=observed.source_object_id,
                    observed_version_id=observed.version_id,
                    content_version_id=observed.version_id,
                    media_type="text/markdown",
                    content=DOCUMENT,
                    observed_at=WHEN,
                ),
            )
        create_canary(engine)
        yield engine, accepted.enrollment.enrollment_id
    finally:
        engine.dispose()


def create_canary(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"CREATE TABLE {CANARY} (label text)"))
        connection.execute(text(f"INSERT INTO {CANARY} VALUES ('present')"))  # noqa: S608


def canary_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(text(f"SELECT to_regclass('{CANARY}')")).scalar_one_or_none()
        )


def extraction_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text("SELECT count(*) FROM knowledge.extractions")).scalar_one()
        )


@pytest.mark.database
def test_the_injection_payload_is_live(corpus: tuple[Engine, str]) -> None:
    """Non-vacuity. Interpolated, the payload destroys the canary.

    Without this, every "the canary survived" assertion below would also pass
    against a payload that does nothing, and the suite would report an injection
    defence it had never exercised. `exec_driver_sql` with no parameters is what
    makes it reachable: psycopg uses the simple query protocol when there is
    nothing to bind, and that protocol accepts more than one statement.

    The canary is recreated afterwards so the tests that follow have something
    to protect.
    """
    engine, _ = corpus
    assert canary_exists(engine)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            # The interpolation is the point of this test and of nothing else in
            # the repository.
            f"SELECT count(*) FROM {CANARY} WHERE label = '{DROP_PAYLOAD}'"  # noqa: S608
        )

    assert not canary_exists(engine), "the payload is inert; every test beside this proves nothing"
    create_canary(engine)
    assert canary_exists(engine)


@pytest.mark.database
@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_no_payload_executes_anything_through_search(corpus: tuple[Engine, str], name: str) -> None:
    """The same payloads, through the real path, against a live server.

    Compiling a statement proves the text is not in it. Running one proves the
    server agrees: the canary survives, the corpus is untouched, and whatever
    the search returns it returns as a result rather than as a side effect.
    """
    engine, enrollment_id = corpus
    before = extraction_count(engine)

    with engine.connect() as connection:
        request = SearchRequest(enrollment_id=enrollment_id, query=SearchQuery(PAYLOADS[name]))
        try:
            page = search_extractions(connection, request)
        except EmptySearchQueryError:
            # A payload that reduces to no lexemes. A typed answer about the
            # request, which is the point; not a database failure.
            page = None

    assert canary_exists(engine), f"{name} destroyed the canary"
    assert extraction_count(engine) == before, f"{name} changed the corpus"
    if page is not None:
        for match in page.matches:
            assert PAYLOADS[name] not in match.snippet


@pytest.mark.database
def test_the_argument_escape_is_live(corpus: tuple[Engine, str]) -> None:
    """Non-vacuity for the test below, on the real predicate and the real table.

    The `WHERE` clause search uses is written out here with the payload
    interpolated into it, and it has to return *every* row — including the rows
    the payload matches nothing in. If it did not, the test below would be
    asserting that an inert string is inert.
    """
    engine, _ = corpus
    with engine.connect() as connection:
        total = connection.execute(
            text("SELECT count(*) FROM knowledge.extractions WHERE status = 'extracted'")
        ).scalar_one()
        widened = connection.exec_driver_sql(
            # The interpolation is the point of this test and of nothing else.
            "SELECT count(*) FROM knowledge.extractions WHERE status = 'extracted' "  # noqa: S608
            "AND to_tsvector('english', text) @@ "
            f"websearch_to_tsquery('english', '{ARGUMENT_ESCAPE}')"
        ).scalar_one()

    assert total >= 1, "there is nothing to widen onto; this proves nothing"
    assert widened == total, "the escape is inert; the test beside it would be vacuous"


@pytest.mark.database
def test_an_argument_escape_cannot_widen_the_match(corpus: tuple[Engine, str]) -> None:
    """The same payload through the real path returns what it honestly matches.

    Bound, it is a phrase, and the corpus does not contain it. The control
    beneath is what keeps this from passing on a search that had stopped
    returning anything at all.
    """
    engine, enrollment_id = corpus
    with engine.connect() as connection:
        page = search_extractions(
            connection,
            SearchRequest(enrollment_id=enrollment_id, query=SearchQuery(ARGUMENT_ESCAPE)),
        )
    assert page.matches == (), "the query matched a document that does not contain it"

    with engine.connect() as connection:
        found = search_extractions(
            connection, SearchRequest(enrollment_id=enrollment_id, query=SearchQuery("revenue"))
        )
    assert len(found.matches) == 1


@pytest.mark.database
@pytest.mark.parametrize("name", sorted(PAYLOADS))
def test_no_payload_produces_a_database_failure(corpus: tuple[Engine, str], name: str) -> None:
    """A malformed query is a typed error about the request, never a driver error.

    This is the half `to_tsquery` would fail. `DBAPIError` is what a caller
    would see as a 500; every payload here has to produce either a result or one
    of this system's own errors.
    """
    engine, enrollment_id = corpus
    with engine.connect() as connection:
        try:
            search_extractions(
                connection,
                SearchRequest(enrollment_id=enrollment_id, query=SearchQuery(PAYLOADS[name])),
            )
        except (EmptySearchQueryError, SearchQueryError):
            pass
        except DBAPIError as failure:  # pragma: no cover - the failure this forbids
            pytest.fail(f"{name} reached the driver: {type(failure).__name__}")


@pytest.mark.database
def test_the_parser_control_this_module_refuses_is_real(corpus: tuple[Engine, str]) -> None:
    """`to_tsquery` would turn a malformed query into a server error; this does not.

    Performed against the live server rather than argued, because the module
    docstring's justification for choosing `websearch_to_tsquery` rests on it.
    The same string is put through both functions: one raises, one returns a
    query. If PostgreSQL ever stopped raising, this test would fail and the
    justification would have to be rewritten rather than quietly becoming false.
    """
    engine, _ = corpus
    malformed = "revenue &"
    with engine.connect() as connection, pytest.raises(ProgrammingError):
        connection.execute(
            text(f"SELECT to_tsquery('{SEARCH_CONFIG}', :value)"), {"value": malformed}
        )
    with engine.connect() as connection:
        parsed = connection.execute(
            text(f"SELECT websearch_to_tsquery('{SEARCH_CONFIG}', :value)::text"),
            {"value": malformed},
        ).scalar_one()
    assert parsed == "'revenu'"


@pytest.mark.database
@pytest.mark.parametrize(
    ("name", "payload", "expected"),
    [
        ("and", "revenue & report", "'revenu' & 'report'"),
        ("or", "revenue | report", "'revenu' & 'report'"),
        ("not", "!revenue", "'revenu'"),
        ("phrase operator", "revenue <-> report", "'revenu' & 'report'"),
        ("prefix", "revenu:*", "'revenu'"),
        ("weights", "revenue:AB", "'revenu' & 'ab'"),
    ],
)
def test_every_tsquery_operator_arrives_as_text_and_not_as_control(
    corpus: tuple[Engine, str], name: str, payload: str, expected: str
) -> None:
    """The parser hazard, enumerated. Not one operator survives as an operator.

    The expected parses are pinned rather than merely asserted to be
    "operator-free", because a future PostgreSQL that started honouring one of
    these inside `websearch_to_tsquery` would be a change in what a query can
    do, and it must fail here rather than pass unremarked.
    """
    engine, _ = corpus
    with engine.connect() as connection:
        parsed = connection.execute(
            text(f"SELECT websearch_to_tsquery('{SEARCH_CONFIG}', :value)::text"),
            {"value": SearchQuery(payload).text},
        ).scalar_one()
    assert parsed == expected


@pytest.mark.database
def test_the_web_search_syntax_that_is_honoured_is_exactly_this(
    corpus: tuple[Engine, str],
) -> None:
    """The paired positive: a closed, documented syntax, and nothing beyond it.

    A quoted phrase, `or`, and a leading `-`. Enumerating what *is* honoured is
    what keeps the test above from being satisfied by a form that honours
    nothing at all, which `plainto_tsquery` would be.
    """
    engine, _ = corpus
    cases = {
        '"quarterly report"': "'quarter' <-> 'report'",
        "revenue or report": "'revenu' | 'report'",
        "-revenue": "!'revenu'",
    }
    with engine.connect() as connection:
        for payload, expected in cases.items():
            parsed = connection.execute(
                text(f"SELECT websearch_to_tsquery('{SEARCH_CONFIG}', :value)::text"),
                {"value": payload},
            ).scalar_one()
            assert parsed == expected, payload


@pytest.mark.database
def test_a_database_failure_during_a_search_discloses_no_query_text(
    corpus: tuple[Engine, str],
) -> None:
    """The leak that engine configuration would otherwise decide.

    SQLAlchemy renders bound parameters into `DBAPIError` messages unless the
    engine sets `hide_parameters=True`, and `create_database_engine` does not.
    The failure is produced for real -- the table the search reads is renamed
    out from under it -- and the resulting exception is rendered with its
    arguments and its whole chain and searched for the query.
    """
    engine, enrollment_id = corpus
    private = "zephyrine ledger reconciliation"

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE knowledge.extractions RENAME TO extractions_moved"))
    try:
        with engine.connect() as connection, pytest.raises(Exception) as raised:
            search_extractions(
                connection,
                SearchRequest(enrollment_id=enrollment_id, query=SearchQuery(private)),
            )
        failure = raised.value
        assert not isinstance(failure, DBAPIError), "a driver error reached the caller"
        rendered = f"{failure!r} {failure.args} {failure.__cause__} {failure.__context__}"
        for fragment in (private, "zephyrine", "search_text"):
            assert fragment not in rendered
        assert failure.__cause__ is None
        assert failure.__context__ is None
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE knowledge.extractions_moved RENAME TO extractions")
            )


#: The two tables a search reads through, one on each side of the redaction
#: boundary as it stood. `extractions` is read by a statement
#: `persistence.search` builds and runs through `_execute`, so a failure there
#: was always converted. `coverage_limitations` is read only by `coverage_for`,
#: which `persistence.search` delegates to — and, until this change, did not
#: wrap. Both are broken the same way and the same assertions are made about
#: both, which is what makes this a discriminating check rather than one that
#: reports every failure as a leak. `coverage_limitations` is also the last
#: statement `coverage_for` runs, so the three counts before it succeed and the
#: failure is unambiguously the delegated read.
BROKEN_READS: dict[str, str] = {
    "the delegated coverage read": "coverage_limitations",
    "this module's own page read": "extractions",
}


@pytest.mark.database
@pytest.mark.parametrize("read", sorted(BROKEN_READS))
def test_no_database_failure_in_any_read_a_search_performs_discloses_a_statement(
    corpus: tuple[Engine, str], read: str
) -> None:
    """The leak the module's own docstring used to carry as open, in both reads.

    The failure is produced for real — the table is renamed out from under the
    search — and what is inspected is the *rendered traceback*, not `str(exc)`.
    That distinction is the whole point: `raise … from None` clears `__cause__`
    and leaves the original in `__context__`, so an exception whose own message
    says nothing still prints a `DBAPIError` carrying the statement and its
    bound parameters when anything formats it. `format_exception` is what a log
    handler does.

    What leaks here is SQL text and a bound `enrollment_id`, not the caller's
    query: nothing on the coverage side binds query text. The identifier is
    asserted against anyway, because it is the parameter this path actually
    carries and it is the one an envelope must not disclose through an error.
    """
    engine, enrollment_id = corpus
    table = BROKEN_READS[read]
    private = "zephyrine ledger reconciliation"

    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE knowledge.{table} RENAME TO {table}_moved"))
    try:
        with (
            engine.connect() as connection,
            pytest.raises((SearchUnavailableError, SearchInternalError)) as raised,
        ):
            search_extractions(
                connection,
                SearchRequest(enrollment_id=enrollment_id, query=SearchQuery(private)),
            )
        failure = raised.value
        assert not isinstance(failure, DBAPIError), "a driver error reached the caller"
        rendered = "".join(traceback.format_exception(failure))
        chain = f"{failure!r} {failure.args} {failure.__cause__!r} {failure.__context__!r}"
        # The table is named schema-qualified, which is how a statement writes
        # it. The bare name would be matched by `search_extractions` in the
        # traceback's own source lines and would fail for a reason that is not
        # a leak — measured, not guessed: it is what the first run of this test
        # did.
        leaks = (private, "zephyrine", "search_text", enrollment_id, f"knowledge.{table}", "SELECT")
        for fragment in leaks:
            assert fragment not in rendered, f"{fragment!r} reached the rendered traceback"
            assert fragment not in chain, f"{fragment!r} reached the exception chain"
        assert failure.__cause__ is None
        assert failure.__context__ is None
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"ALTER TABLE knowledge.{table}_moved RENAME TO {table}"))


#: A statement and a parameter set shaped like the ones `coverage_for` runs.
#: SQLAlchemy renders both into a `DBAPIError`'s message, which is what makes
#: an unwrapped delegated read a disclosure rather than merely an unclassified
#: crash.
LEAKED_STATEMENT = (
    "SELECT knowledge.coverage_limitations.reason FROM knowledge.coverage_limitations "
    "WHERE knowledge.coverage_limitations.enrollment_id = %(enrollment_id_1)s"
)
LEAKED_IDENTIFIER = "enr_c0ffee0000000000000000000000000000000000000000000000000000000000"


@pytest.mark.parametrize(
    ("name", "failure", "expected"),
    [
        ("the server went away", OperationalError, SearchUnavailableError),
        ("the connection broke", InterfaceError, SearchUnavailableError),
        ("the schema is wrong", ProgrammingError, SearchInternalError),
    ],
)
def test_the_delegated_coverage_read_keeps_the_unavailable_internal_discrimination(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    failure: type[DBAPIError],
    expected: type[Exception],
) -> None:
    """Wrapping the delegated read must not flatten what it is wrapped into.

    Telling a caller to retry a missing column is a lie with a retry budget
    attached, so the delegated read has to keep the same split the statements
    this module builds already keep. The database tier above breaks a schema,
    which is one classification; the retryable pair cannot be produced that way
    without killing a server, so it is produced by substituting the failure the
    delegated call raises. What is asserted is the classification and the
    emptiness of the chain, both of which are `_coverage`'s to get right.
    """

    def raise_it(*arguments: object, **keywords: object) -> object:
        raise failure(LEAKED_STATEMENT, {"enrollment_id_1": LEAKED_IDENTIFIER}, Exception("orig"))

    monkeypatch.setattr(search_module, "coverage_for", raise_it)
    with pytest.raises(expected) as raised:
        search_module._coverage(None, LEAKED_IDENTIFIER, moment=WHEN)  # type: ignore[arg-type]

    caught = raised.value
    rendered = "".join(traceback.format_exception(caught))
    for fragment in ("coverage_limitations", LEAKED_IDENTIFIER, "SELECT"):
        assert fragment not in rendered, f"{fragment!r} reached the rendered traceback"
    assert caught.__cause__ is None
    assert caught.__context__ is None


def test_the_coverage_guard_still_reports_an_impossible_count_as_internal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ValueError` was the one failure `_coverage` already classified, and it stays.

    `coverage_for` raises it through `CoverageCounts` when the counts do not fit
    inside the eligible total. That is not a database failure and it must not
    become retryable now that database failures are handled beside it.
    """

    def raise_it(*arguments: object, **keywords: object) -> object:
        raise ValueError("accounted exceeds eligible")

    monkeypatch.setattr(search_module, "coverage_for", raise_it)
    with pytest.raises(SearchInternalError) as raised:
        search_module._coverage(None, LEAKED_IDENTIFIER, moment=WHEN)  # type: ignore[arg-type]
    assert raised.value.__context__ is None


@pytest.mark.database
def test_the_query_text_is_not_in_the_statement_the_server_logs(
    corpus: tuple[Engine, str],
) -> None:
    """What the server sees, asked of the server.

    `pg_stat_statements` is not installed, so the check is made where it can be:
    the prepared statement text PostgreSQL reports for this session. A parameter
    is a `$1` there; an interpolated query would be the query.
    """
    engine, enrollment_id = corpus
    private = "zephyrine ledger reconciliation"
    with engine.connect() as connection:
        search_extractions(
            connection,
            SearchRequest(enrollment_id=enrollment_id, query=SearchQuery(private)),
        )
        prepared = connection.execute(
            text("SELECT statement FROM pg_prepared_statements")
        ).scalars()
        for statement in prepared:
            assert private not in statement


#: Every failure a read can produce, beside the classification it must get.
#:
#: **The first three rows are the ones the handler set was missing**, and each
#: was verified against the installed SQLAlchemy rather than read off a
#: docstring. `DisconnectionError` and SQLAlchemy's `TimeoutError` are direct
#: subclasses of `SQLAlchemyError` and of neither `OperationalError` nor
#: `InterfaceError`, so both were classified as this system's fault — a dropped
#: connection and an exhausted pool, told not to retry. The builtin
#: `TimeoutError` is an `OSError` and not a `SQLAlchemyError` at all, so it
#: escaped the handler entirely: no classification, no envelope, and a rendered
#: traceback through frames that hold the bound query.
#:
#: The pool timeout is reachable by construction rather than in principle.
#: `create_database_engine` sets `pool_size=5, max_overflow=0, pool_timeout=30`
#: and `bootstrap.gateway` builds two such pools.
CLASSIFICATIONS = [
    ("a dropped connection", DisconnectionError("gone"), True),
    ("an exhausted pool", PoolTimeoutError("no connection available"), True),
    ("a socket timeout", TimeoutError("timed out"), True),
    ("a reset socket", ConnectionResetError("reset by peer"), True),
    ("the server went away", OperationalError("SELECT 1", {}, Exception("orig")), True),
    ("the connection broke", InterfaceError("SELECT 1", {}, Exception("orig")), True),
    ("the schema is wrong", ProgrammingError("SELECT 1", {}, Exception("orig")), False),
    ("an impossible count", ValueError("accounted exceeds eligible"), False),
    ("a programming mistake", TypeError("not a statement"), False),
]


class FailingConnection:
    """A `Connection` that fails the way this case says, and holds no server.

    Substituted rather than provoked, because four of the nine cases cannot be
    produced against a live server without killing one: a pool cannot be
    exhausted by a test that holds no connections, and a builtin `TimeoutError`
    is raised by the socket layer under conditions a test cannot arrange. The
    live half of this question is the database tier above, which breaks a real
    schema under a real search.
    """

    def __init__(self, failure: BaseException) -> None:
        self._failure = failure

    def execute(self, statement: object) -> object:
        raise self._failure


@pytest.mark.parametrize(
    ("module", "unavailable_error", "internal_error"),
    [
        (search_module, SearchUnavailableError, SearchInternalError),
        (capture_search_module, CaptureSearchUnavailableError, CaptureSearchInternalError),
    ],
    ids=["search", "capture_search"],
)
@pytest.mark.parametrize(
    ("name", "failure", "retryable"),
    CLASSIFICATIONS,
    ids=[case[0] for case in CLASSIFICATIONS],
)
def test_every_failure_of_a_read_is_classified_and_carries_nothing(
    module: object,
    unavailable_error: type[Exception],
    internal_error: type[Exception],
    name: str,
    failure: BaseException,
    retryable: bool,
) -> None:
    """`_execute`'s classification, over the whole set rather than over two names.

    Applied to both modules from one table, because the defect was the same
    defect twice and a fix that closed one would be exactly the shape seven
    review rounds of this campaign have blocked: a correction that closes the
    case its finding named and leaves the adjacent one open.

    Three things are asserted of every case and the third is the one that fails
    when a class is *missing* rather than misclassified: the error is one of the
    two the module publishes at all. A failure outside the handler set does not
    arrive misclassified — it arrives as itself.
    """
    expected = unavailable_error if retryable else internal_error
    with pytest.raises((unavailable_error, internal_error)) as raised:
        module._execute(FailingConnection(failure), object(), lambda result: result)

    assert isinstance(raised.value, expected), f"{name} was classified as {type(raised.value)}"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    rendered = "".join(traceback.format_exception(raised.value))
    for fragment in ("SELECT 1", "accounted exceeds eligible", "reset by peer"):
        assert fragment not in rendered, f"{fragment!r} reached the rendered traceback"


@pytest.mark.parametrize(
    ("name", "failure", "retryable"),
    CLASSIFICATIONS,
    ids=[case[0] for case in CLASSIFICATIONS],
)
def test_the_delegated_read_is_classified_over_the_same_set(
    monkeypatch: pytest.MonkeyPatch, name: str, failure: BaseException, retryable: bool
) -> None:
    """`_coverage`'s handler set is `_execute`'s, asserted rather than described.

    The two were written out separately and stayed equal by inspection. They are
    now checked against one table, so a name added to one and not the other is a
    failure here rather than a divergence a reviewer has to notice.
    """

    def raise_it(*arguments: object, **keywords: object) -> object:
        raise failure

    monkeypatch.setattr(search_module, "coverage_for", raise_it)
    expected = SearchUnavailableError if retryable else SearchInternalError
    with pytest.raises((SearchUnavailableError, SearchInternalError)) as raised:
        search_module._coverage(None, LEAKED_IDENTIFIER, moment=WHEN)  # type: ignore[arg-type]

    assert isinstance(raised.value, expected), f"{name} was classified as {type(raised.value)}"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_no_configuration_reaches_the_sql_except_the_one_checked_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The text-search configuration is the one value that is *written* into SQL.

    Everything else a caller supplies is a bound parameter; the configuration
    name cannot be, because a bound one does not match the functional index —
    which `persistence.search` measured and both modules record. So the set of
    names that can reach `literal_column` is the whole of the guard, and it was
    a module attribute re-read at statement-build time. `Final` stops
    `mypy --strict` rebinding it inside the checked tree; it stops nothing
    outside one, and `document_vector` is public and takes the plane whose
    `configuration` it would then compile.

    Rebinding the set is how that is demonstrated without inventing an attacker:
    the check now runs once, at import, so a wider set installed afterwards
    changes nothing. **Before this package the assertion below was false** — a
    plane carrying `evil` compiled to `to_tsvector('evil', content)`.

    The control is the second half: the registered plane still compiles, so this
    is a test of the boundary and not of a module that refuses everything.
    """
    monkeypatch.setattr(
        capture_search_module, "INDEXED_CONFIGURATIONS", frozenset({"simple", "evil"})
    )
    forged = SearchPlane(
        table=CAPTURE_VERSIONS.table,
        text_column=CAPTURE_VERSIONS.text_column,
        configuration="evil",
        index_name=CAPTURE_VERSIONS.index_name,
    )
    with pytest.raises(ValueError, match="unsupported text-search configuration"):
        document_vector(forged)

    compiled = str(document_vector().compile(dialect=postgresql.dialect()))
    assert "'simple'" in compiled
    assert "evil" not in compiled


def test_a_plane_this_module_did_not_construct_compiles_nothing() -> None:
    """Identity, not equality, and the reason is `Column.__eq__`.

    A `SearchPlane` holds a `Column`, whose `__eq__` builds a SQL expression
    rather than answering a question, so membership of a mapping keyed by plane
    is a comparison this module should not be making. Identity is also the
    stricter rule: the module says there is one instance, and a caller holding a
    plane it did not construct is not a caller whose configuration name should
    be interpolated — even when that name is the admissible one, which is what
    this asserts.
    """
    twin = SearchPlane(
        table=CAPTURE_VERSIONS.table,
        text_column=CAPTURE_VERSIONS.text_column,
        configuration=CAPTURE_VERSIONS.configuration,
        index_name=CAPTURE_VERSIONS.index_name,
    )
    with pytest.raises(ValueError, match="unsupported text-search configuration"):
        document_vector(twin)


@pytest.mark.parametrize(
    ("module", "unavailable_error", "internal_error"),
    [
        (search_module, SearchUnavailableError, SearchInternalError),
        (capture_search_module, CaptureSearchUnavailableError, CaptureSearchInternalError),
    ],
    ids=["search", "capture_search"],
)
@pytest.mark.parametrize("failure", [KeyboardInterrupt(), SystemExit(1)], ids=["ctrl-c", "exit"])
def test_a_cancelled_process_is_not_reported_as_a_failed_search(
    module: object,
    unavailable_error: type[Exception],
    internal_error: type[Exception],
    failure: BaseException,
) -> None:
    """The boundary of the wide handler, asserted rather than described.

    `_execute`'s second handler is `Exception`, which is deliberately wide enough
    to catch this module's own bugs — the cost that docstring names. It must not
    be wide enough to catch a cancellation: `BaseException` is where the line
    is, and `Ctrl-C` during a long read has to kill the process rather than be
    reported to the caller as "the search could not be completed" while the
    interpreter carries on.

    Written as a test because it is the one half of that disclosure a test can
    hold. The rest — that a `TypeError` now arrives with no diagnostic anywhere —
    is a property of the *absence* of a logging sink, and there is nothing to
    assert against.
    """
    with pytest.raises(type(failure)):
        module._execute(FailingConnection(failure), object(), lambda result: result)
