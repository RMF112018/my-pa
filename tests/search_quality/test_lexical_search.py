"""What lexical search returns, and what it says about what it did not search.

The corpus is synthetic and invented for this file: no personal data, no real
person, project, organisation, or address, and nothing from the migrated legacy
corpus or any live source. It is written so that the answers are decidable by
reading it — one document mentions a term four times and another mentions it
once, so "ranked higher" is a fact about the fixture rather than a hope about
the ranking function.

Two properties are worth more than the rest and are tested hardest.

**"We found nothing" and "we have not indexed this" are different answers.**
Section 9.7 forbids collapsing them, and the collapse is the natural bug: an
unindexed scope and an empty result set both produce zero rows. So there are
three cases here — a fully extracted scope that genuinely has no match, a scope
where some objects never reached extraction, and a scope where none did — and
each has to produce a different disclosure while returning the same number of
matches.

**A page boundary neither repeats nor loses a row.** Keyset pagination is exact
or it is silently wrong, so the pages are reassembled and compared against the
unpaged result as a set *and* as a sequence.

The database is disposable, created and dropped by its fixture, and never the
configured one: this suite writes, and pointing it at `my_pa` would put
synthetic rows in the schema that holds the migrated corpus.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import (
    ColumnElement,
    Connection,
    Engine,
    Executable,
    Insert,
    Select,
    Text,
    func,
    literal,
    literal_column,
    select,
    text,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError

from my_pa.contracts.ports import UnknownScopeError
from my_pa.contracts.v1.disclosure import CoverageState, FreshnessState
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.common.time import NaiveDatetimeError
from my_pa.domain.extraction.coverage import LimitationReason, SnapshotState
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import extract_text
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import (
    MAX_SNIPPET_CHARACTERS,
    MAX_SNIPPET_WORDS,
    MIN_SNIPPET_WORDS,
    EmptySearchQueryError,
    RankCategory,
    SearchCursorError,
    SearchQuery,
    SearchRequest,
)
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import IsolationLevelError
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.extraction import (
    UnauthorizedObjectError,
    authorized_media_type,
    authorized_object,
    coverage_for,
    quarantine_object,
    record_limitation,
    record_outcome,
)
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.search import (
    INDEXED_CONFIGURATIONS,
    SEARCH_CONFIG,
    SearchInternalError,
    SearchPage,
    SearchUnavailableError,
    UnknownEnrollmentError,
    _configuration,
    _coverage,
    _every_row,
    _execute,
    match_statement,
    search_extractions,
)
from my_pa.infrastructure.persistence.tables import enrollments, extractions, source_objects

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name, so a run interrupted before teardown is cleaned up by the next.
DISPOSABLE_DATABASE = "my_pa_search_quality_test"

WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/search/corpus"

#: The corpus. Every assertion below is decidable by reading it, which is the
#: only way a search test is about the search rather than about the fixture.
#:
#: * `revenue` appears four times in `ledger` and once in `minutes`, so their
#:   relative order is a property of the corpus and not a hope about ranking.
#: * `quarterly` and `report` both appear in `ledger` and in `charter`, but only
#:   `charter` has them adjacent. That is what separates a phrase search from a
#:   word search: the two queries must return different sets.
#: * `archive` appears in all four, so pagination has something to page.
#: * `almanac` shares no financial term with the rest, so it is the control that
#:   proves a query does not simply return everything.
#:
#: `the` is deliberately not used as a query anywhere: it is an English stop word
#: and produces an empty `tsquery`, which is a different test entirely.
CORPUS: dict[str, tuple[str, bytes]] = {
    "ledger": (
        "text/markdown",
        b"# Ledger\n\nThe quarterly revenue statement records revenue growth, revenue "
        b"targets, and revenue recognition for the northern division. A supplementary "
        b"report follows it in the archive.\n",
    ),
    "minutes": (
        "text/markdown",
        b"# Minutes\n\nThe northern division mentioned revenue once and then moved on "
        b"to scheduling, staffing, and the winter maintenance window. Filed in the "
        b"archive.\n",
    ),
    "almanac": (
        "text/plain",
        b"Packing and shipping timetables for the eastern warehouse, listing pallet "
        b"counts and dock assignments for each weekday. Kept in the archive.\n",
    ),
    "charter": (
        "text/markdown",
        b"# Charter\n\nThe quarterly report is due on Friday. Separately, report the "
        b"quarterly figures to the board whenever the board asks. Stored in the "
        b"archive.\n",
    ),
}

#: A document long enough that a snippet of it must be a window rather than the
#: whole thing. Repetitive on purpose: nothing here is meant to be read.
LONG_DOCUMENT = (
    b"# Warehouse manual\n\n" + b"The warehouse inventory procedure repeats itself. " * 120
)


@dataclass(frozen=True, slots=True)
class Corpus:
    """What a test needs to run a search, and nothing about how it was built."""

    engine: Engine
    source_id: str
    enrollment_id: str
    object_ids: dict[str, str]
    version_ids: dict[str, str]


def administer(maintenance: Engine, *statements: object) -> None:
    """Run statements that cannot be inside a transaction, such as CREATE DATABASE."""
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def engine(module_cloned_database_url: str) -> Iterator[Engine]:
    built = create_database_engine(module_cloned_database_url)
    try:
        yield built
    finally:
        built.dispose()


#: The allowlist every enrollment here uses unless a test is about the allowlist.
#: It holds both types `extract_text` can read, so the content dimension of the
#: authorization boundary admits everything and the object dimension is what the
#: rest of this file varies.
EVERY_READABLE_TYPE: tuple[str, ...] = ("text/markdown", "text/plain")


def enrol(
    engine: Engine,
    *,
    key: str,
    documents: dict[str, tuple[str, bytes]],
    extract: frozenset[str] | None = None,
    media_types: tuple[str, ...] = EVERY_READABLE_TYPE,
) -> Corpus:
    """Build one source, one enrollment, and extract the named subset.

    `extract` is what makes the coverage tests possible: the objects outside it
    are enrolled and observed but never reach an outcome, which is exactly the
    state that must not be reported as "nothing matched".

    `media_types` is the enrollment's content-type allowlist, and it is a
    parameter for the same reason `extract` is: it is one half of what an
    enrollment authorizes, so a test about that half has to be able to vary it
    while everything else stays constant.
    """
    chosen = frozenset(documents) if extract is None else extract
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=f"{NATIVE_ROOT}/{key}",
        )
        observed = {
            name: observe_object(
                connection,
                source_id=source.source_id,
                native_locator=f"{NATIVE_ROOT}/{key}/{name}",
                kind=ObjectKind.FILE,
                fingerprint=f"fingerprint-{key}-{name}",
                modified_at=WHEN,
                media_type=media_type,
                size_bytes=len(body),
            )
            for name, (media_type, body) in documents.items()
        }
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=source.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(
                    object_ids=tuple(entry.source_object_id for entry in observed.values())
                ),
                media_types=media_types,
                policy_version="mcv-1",
                idempotency_key=f"search-{key}-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
        )
        # The enumerated object set, which every read now restricts to and whose
        # size is the eligible total `coverage_for` reads for itself. Written
        # here because `sources.enroll` writes it there: an enrollment with no
        # such set authorizes nothing at all, which is a state the writer refuses
        # to create and no test should reach by omission.
        record_scope(
            connection,
            accepted.enrollment.enrollment_id,
            [entry.source_object_id for entry in observed.values()],
        )
        for name in sorted(chosen):
            media_type, body = documents[name]
            record_outcome(
                connection,
                enrollment_id=accepted.enrollment.enrollment_id,
                outcome=extract_text(
                    source_id=source.source_id,
                    source_object_id=observed[name].source_object_id,
                    observed_version_id=observed[name].version_id,
                    content_version_id=observed[name].version_id,
                    media_type=media_type,
                    content=body,
                    observed_at=WHEN,
                ),
            )
    return Corpus(
        engine=engine,
        source_id=source.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids={name: entry.source_object_id for name, entry in observed.items()},
        version_ids={name: entry.version_id for name, entry in observed.items()},
    )


def enrol_under_a_root(
    engine: Engine,
    *,
    key: str,
    documents: dict[str, tuple[str, bytes]],
    extract: frozenset[str] | None = None,
    max_items: int = 100,
) -> Corpus:
    """One enrollment that names a root and a depth, with `documents` extracted.

    The difference from `enrol` is the scope and nothing else. An enrollment that
    names its objects carries its own eligible total; one that names a root has
    an eligible total only enumeration knows and nothing persists, which is the
    condition every test using this exercises. `documents` may be empty, so both
    "no outcomes at all" and "outcomes, all of them successes" are reachable —
    the second is where a coverage claim could be made and must not be.

    `extract` names the subset that reaches an outcome, so an object can be
    enrolled and then quarantined with no extraction anywhere near it: that is
    the shape in which a derived denominator says "all of it was quarantined".
    `max_items` is settable because it is the number search used to invent a
    denominator from, and the case that broke was outcomes outnumbering it.
    """
    chosen = frozenset(documents) if extract is None else extract
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Rooted corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=f"{NATIVE_ROOT}/{key}",
        )
        root = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=f"{NATIVE_ROOT}/{key}",
            kind=ObjectKind.CONTAINER,
            fingerprint=f"fingerprint-{key}",
            modified_at=WHEN,
        )
        observed = {
            name: observe_object(
                connection,
                source_id=source.source_id,
                native_locator=f"{NATIVE_ROOT}/{key}/{name}",
                kind=ObjectKind.FILE,
                fingerprint=f"fingerprint-{key}-{name}",
                modified_at=WHEN,
                media_type=media_type,
                size_bytes=len(body),
            )
            for name, (media_type, body) in documents.items()
        }
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=source.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(root_object_id=root.source_object_id, depth=1),
                media_types=("text/markdown", "text/plain"),
                policy_version="mcv-1",
                idempotency_key=f"search-{key}-{secrets.token_hex(4)}",
                max_items=max_items,
                max_bytes=1_000_000,
            ),
        )
        # The enumerated object set, which every read now restricts to and whose
        # size is the eligible total `coverage_for` reads for itself. Written
        # here because `sources.enroll` writes it there: an enrollment with no
        # such set authorizes nothing at all, which is a state the writer refuses
        # to create and no test should reach by omission.
        record_scope(
            connection,
            accepted.enrollment.enrollment_id,
            [entry.source_object_id for entry in observed.values()],
        )
        for name in sorted(chosen):
            media_type, body = documents[name]
            record_outcome(
                connection,
                enrollment_id=accepted.enrollment.enrollment_id,
                outcome=extract_text(
                    source_id=source.source_id,
                    source_object_id=observed[name].source_object_id,
                    observed_version_id=observed[name].version_id,
                    content_version_id=observed[name].version_id,
                    media_type=media_type,
                    content=body,
                    observed_at=WHEN,
                ),
            )
    return Corpus(
        engine=engine,
        source_id=source.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids={name: entry.source_object_id for name, entry in observed.items()},
        version_ids={name: entry.version_id for name, entry in observed.items()},
    )


def enrol_beside(
    corpus: Corpus,
    *,
    key: str,
    documents: dict[str, tuple[str, bytes]],
    extract: frozenset[str] | None = None,
) -> Corpus:
    """A second enrollment over `corpus`'s own source, naming objects it does not.

    The only helper that holds the source constant, and the reason it exists is
    that nothing else can reach half the authorization boundary.
    `authorized_object` has two conditions — the object's source is the
    enrollment's, and where objects were named the object is one of them — and
    every object built by a separate `enrol` violates both at once, because
    `enrol` registers its own source. A refusal proved that way is proof of
    nothing about membership: the source condition alone accounts for it, and
    replacing the membership condition with a constant true leaves such a test
    green.

    Objects observed here belong to `corpus.source_id`, so the source condition
    is satisfied and only membership decides. That is the single-condition
    variation the membership half needs.
    """
    chosen = frozenset(documents) if extract is None else extract
    with corpus.engine.begin() as connection:
        observed = {
            name: observe_object(
                connection,
                source_id=corpus.source_id,
                native_locator=f"{NATIVE_ROOT}/{key}/{name}",
                kind=ObjectKind.FILE,
                fingerprint=f"fingerprint-{key}-{name}",
                modified_at=WHEN,
                media_type=media_type,
                size_bytes=len(body),
            )
            for name, (media_type, body) in documents.items()
        }
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=corpus.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(
                    object_ids=tuple(entry.source_object_id for entry in observed.values())
                ),
                media_types=("text/markdown", "text/plain"),
                policy_version="mcv-1",
                idempotency_key=f"beside-{key}-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
        )
        record_scope(
            connection,
            accepted.enrollment.enrollment_id,
            [entry.source_object_id for entry in observed.values()],
        )
        for name in sorted(chosen):
            media_type, body = documents[name]
            record_outcome(
                connection,
                enrollment_id=accepted.enrollment.enrollment_id,
                outcome=extract_text(
                    source_id=corpus.source_id,
                    source_object_id=observed[name].source_object_id,
                    observed_version_id=observed[name].version_id,
                    content_version_id=observed[name].version_id,
                    media_type=media_type,
                    content=body,
                    observed_at=WHEN,
                ),
            )
    return Corpus(
        engine=corpus.engine,
        source_id=corpus.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids={name: entry.source_object_id for name, entry in observed.items()},
        version_ids={name: entry.version_id for name, entry in observed.items()},
    )


def enrol_over(corpus: Corpus, *, key: str, names: tuple[str, ...]) -> Corpus:
    """A second enrollment naming objects `corpus`'s enrollment already names.

    `enrol_beside` holds the source constant and varies the objects, which is
    what the membership half of `authorized_object` needs. This holds the source
    *and the objects* constant and varies only the enrollment, which is what the
    three remaining `enrollment_id` filters need — the two precedence subqueries
    in `coverage_for` and the one in `match_statement`. Every object here is
    authorized by both enrollments, so nothing in the authorization boundary can
    account for a refusal and only the filter can.

    Nothing is extracted. What a test writes under this enrollment is the point
    of using it, so it writes it itself.
    """
    with corpus.engine.begin() as connection:
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=corpus.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(object_ids=tuple(corpus.object_ids[name] for name in names)),
                media_types=EVERY_READABLE_TYPE,
                policy_version="mcv-1",
                idempotency_key=f"over-{key}-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
        )
        record_scope(
            connection,
            accepted.enrollment.enrollment_id,
            [corpus.object_ids[name] for name in names],
        )
    return Corpus(
        engine=corpus.engine,
        source_id=corpus.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids={name: corpus.object_ids[name] for name in names},
        version_ids={name: corpus.version_ids[name] for name in names},
    )


@pytest.fixture(scope="module")
def corpus(engine: Engine) -> Corpus:
    """The whole corpus, fully extracted. The baseline every other case departs from."""
    return enrol(engine, key="full", documents=CORPUS)


def search(corpus: Corpus, query: str, **overrides: object) -> SearchPage:
    values: dict[str, object] = {"enrollment_id": corpus.enrollment_id, "query": SearchQuery(query)}
    values.update(overrides)
    with corpus.engine.connect() as connection:
        return search_extractions(connection, SearchRequest(**values))  # type: ignore[arg-type]


@pytest.mark.database
def test_the_corpus_is_the_one_these_tests_assume(corpus: Corpus) -> None:
    """Guards every assertion below.

    A fixture that failed to extract would make most of this file pass by
    returning nothing and finding nothing wrong with that.
    """
    assert set(corpus.object_ids) == set(CORPUS)
    with corpus.engine.connect() as connection:
        extracted = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.extractions "
                "WHERE enrollment_id = :enrollment AND status = 'extracted'"
            ),
            {"enrollment": corpus.enrollment_id},
        ).scalar_one()
    assert extracted == len(CORPUS)
    assert CORPUS["ledger"][1].count(b"revenue") == 4
    assert CORPUS["minutes"][1].count(b"revenue") == 1
    assert b"revenue" not in CORPUS["almanac"][1]
    # The phrase case: both words in two documents, adjacent in only one.
    for name in ("ledger", "charter"):
        assert b"quarterly" in CORPUS[name][1] and b"report" in CORPUS[name][1]
    assert b"quarterly report" in CORPUS["charter"][1]
    assert b"quarterly report" not in CORPUS["ledger"][1]
    # The pagination case.
    assert all(b"archive" in body for _, body in CORPUS.values())


@pytest.mark.database
def test_a_term_finds_the_documents_that_contain_it_and_no_others(corpus: Corpus) -> None:
    page = search(corpus, "revenue")
    assert len(page.matches) == 2
    assert {match.source_object_id for match in page.matches} == {
        corpus.object_ids["ledger"],
        corpus.object_ids["minutes"],
    }


@pytest.mark.database
def test_the_document_that_says_it_more_often_ranks_higher(corpus: Corpus) -> None:
    """Ordering, and the categories that go with it.

    Four occurrences against one is a difference the fixture guarantees, so this
    is a claim about the ranking rather than about the corpus. The categories
    are asserted alongside the order because a bucketing that collapsed every
    result into one category would satisfy the ordering assertion alone.
    """
    page = search(corpus, "revenue")
    assert page.matches[0].source_object_id == corpus.object_ids["ledger"]
    assert page.matches[0].rank is RankCategory.STRONG
    assert page.matches[1].rank is RankCategory.MODERATE


@pytest.mark.database
def test_a_query_is_stemmed_so_a_related_form_finds_the_document(corpus: Corpus) -> None:
    """`english`, not `simple`, and this is the difference it makes."""
    assert {match.source_object_id for match in search(corpus, "recorded").matches} == {
        corpus.object_ids["ledger"]
    }
    assert {match.source_object_id for match in search(corpus, "shipped").matches} == {
        corpus.object_ids["almanac"]
    }


@pytest.mark.database
def test_a_quoted_phrase_matches_adjacency_and_not_mere_co_occurrence(corpus: Corpus) -> None:
    """The capability `plainto_tsquery` could not express.

    `charter` contains "quarterly report" adjacent and also "report the
    quarterly figures" apart; `ledger` contains "quarterly" and "statement".
    The unquoted query and the quoted one therefore have to disagree, which is
    what makes this a test of phrase search rather than of word search.
    """
    unquoted = {match.source_object_id for match in search(corpus, "quarterly report").matches}
    quoted = {match.source_object_id for match in search(corpus, '"quarterly report"').matches}
    assert quoted == {corpus.object_ids["charter"]}
    assert quoted < unquoted, "the quoted and unquoted queries agree; this proves nothing"


@pytest.mark.database
def test_a_negated_term_excludes_the_documents_that_carry_it(corpus: Corpus) -> None:
    excluded = {match.source_object_id for match in search(corpus, "-revenue").matches}
    assert corpus.object_ids["ledger"] not in excluded
    assert corpus.object_ids["minutes"] not in excluded
    assert corpus.object_ids["almanac"] in excluded


@pytest.mark.database
def test_a_query_with_no_terms_is_an_error_and_not_an_empty_result(corpus: Corpus) -> None:
    """The first half of section 9.7's rule, at the query end.

    `!!!` is a well-formed request that names nothing to search for.
    `websearch_to_tsquery` turns it into an empty `tsquery` that matches
    nothing, and reporting that as "no results" would be a claim about the
    corpus made from a fact about the query.
    """
    for payload in ("!!!", "***", "-------"):
        with pytest.raises(EmptySearchQueryError):
            search(corpus, payload)


@pytest.mark.database
def test_a_fully_extracted_scope_may_honestly_report_no_match(corpus: Corpus) -> None:
    """The answer that is only available when coverage is complete.

    Everything in scope was extracted, so zero matches means the corpus does not
    contain the term. This is the one case where "we found nothing" is true, and
    the disclosure says so: complete coverage, not a partial result.
    """
    page = search(corpus, "zeppelin")
    assert page.matches == ()
    assert page.disclosure.coverage.state is CoverageState.PROCESSED
    assert page.disclosure.coverage.processed == page.disclosure.coverage.eligible == len(CORPUS)
    assert page.disclosure.partial_result is False


@pytest.mark.database
def test_an_unextracted_scope_is_partial_and_never_a_no_match_claim(engine: Engine) -> None:
    """The second half, and the defect the rule exists to prevent.

    This enrollment has the same documents and the same query, and returns the
    same zero matches as the test above. The only difference is that nothing was
    extracted — and the disclosure has to make that difference visible, because
    a caller told "no results" here would conclude something false about their
    own documents.
    """
    empty = enrol(engine, key="unextracted", documents=CORPUS, extract=frozenset())
    page = search(empty, "revenue")

    assert page.matches == ()
    assert page.disclosure.partial_result is True
    assert page.disclosure.coverage.processed == 0
    assert "no_extracted_text_in_scope" in page.disclosure.limitations
    assert page.disclosure.coverage.state is not CoverageState.PROCESSED


@pytest.mark.database
def test_a_partly_extracted_scope_says_which_part_is_missing_as_a_count(engine: Engine) -> None:
    """The middle case: real results, and an honest statement that they are not all."""
    partial = enrol(engine, key="partial", documents=CORPUS, extract=frozenset({"ledger"}))
    page = search(partial, "revenue")

    assert len(page.matches) == 1
    assert page.disclosure.partial_result is True
    assert page.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert page.disclosure.coverage.processed == 1
    assert page.disclosure.coverage.eligible == len(CORPUS)
    assert "scope_not_fully_extracted" in page.disclosure.limitations


@pytest.mark.database
def test_an_unsupported_object_is_counted_and_not_searchable(engine: Engine) -> None:
    """Section 12: unsupported media is reported, never silently skipped.

    The PDF is enrolled, observed, and given an outcome that says what it is. It
    contributes to the coverage counts and to nothing else, so a search neither
    returns it nor pretends the scope was smaller than it was.
    """
    documents = dict(CORPUS)
    documents["handbook"] = ("application/pdf", b"%PDF-1.7\nnot extracted here\n%%EOF\n")
    mixed = enrol(engine, key="unsupported", documents=documents)
    page = search(mixed, "revenue")

    assert len(page.matches) == 2
    assert page.disclosure.coverage.unsupported == 1
    assert page.disclosure.coverage.eligible == len(documents)
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_a_quarantined_object_is_counted_and_its_content_never_appears(engine: Engine) -> None:
    quarantined = enrol(
        engine, key="quarantined", documents=CORPUS, extract=frozenset({"ledger", "minutes"})
    )
    with quarantined.engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=quarantined.enrollment_id,
            source_object_id=quarantined.object_ids["charter"],
            # `None`, and the reason is the reason: containment failed, so no
            # version was ever proven, and recording one would attribute the
            # quarantine to bytes nobody saw.
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    page = search(quarantined, "quarterly")

    assert page.disclosure.coverage.quarantined == 1
    assert quarantined.object_ids["charter"] not in {
        match.source_object_id for match in page.matches
    }
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_an_object_that_was_both_extracted_and_quarantined_is_counted_once(engine: Engine) -> None:
    """The state two ledgers can be in at once, and it must not crash the read.

    An extraction is recorded per observed version and a quarantine is an
    append-only event, so one object can hold both: quarantined at one version
    and extracted at another, in either order. Nothing prevents it and nothing
    should — a containment failure after a successful pass is exactly the
    sequence `INV-PKL-007` cares about.

    Counted per row, that object is two outcomes in a scope of four objects, and
    `CoverageCounts` refuses counts that exceed their denominator: the whole read
    path raised `ValueError` and the caller got no disclosure at all. Counted per
    object, with quarantine taking precedence, it is one quarantined object and
    three processed ones. Quarantine wins deliberately: the opposite precedence
    would let a later success hide a quarantine, which is the one direction that
    turns a stopped object into a covered one.
    """
    both = enrol(engine, key="both", documents=CORPUS)
    with both.engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=both.enrollment_id,
            source_object_id=both.object_ids["ledger"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    page = search(both, "revenue")

    coverage = page.disclosure.coverage
    assert coverage.eligible == len(CORPUS)
    assert coverage.quarantined == 1
    assert coverage.processed == len(CORPUS) - 1
    assert coverage.processed + coverage.quarantined + coverage.unsupported <= coverage.eligible
    assert coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "scope_not_fully_extracted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True

    # The other side of the same state, which this test asserted nothing about
    # for six review rounds. `ledger` is the document that says "revenue" four
    # times, so a page that still holds it is a page of the text of an object the
    # coverage beside it reports as stopped.
    assert both.object_ids["ledger"] not in {match.source_object_id for match in page.matches}
    assert {match.source_object_id for match in page.matches} == {both.object_ids["minutes"]}


@pytest.mark.database
def test_an_object_extracted_at_one_version_and_unsupported_at_another_is_counted_once(
    engine: Engine,
) -> None:
    """The same double count without a quarantine anywhere near it.

    `extractions` holds one row per observed version, so an object whose media
    type changed between two passes has two rows with two different statuses. Per
    row that is two outcomes in a scope of one object, which `CoverageCounts`
    refuses in the same way. Per object it is one outcome, and it is the
    unsupported one for the same reason quarantine outranks extraction: the
    object's current bytes are not text this system can read, and reporting it as
    processed because an older version was would claim coverage the corpus no
    longer has.
    """
    reclassified = enrol(engine, key="reclassified", documents={"ledger": CORPUS["ledger"]})
    with engine.begin() as connection:
        changed = observe_object(
            connection,
            source_id=reclassified.source_id,
            native_locator=f"{NATIVE_ROOT}/reclassified/ledger",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-reclassified-ledger-as-pdf",
            modified_at=WHEN,
            media_type="application/pdf",
            size_bytes=32,
        )
        # The same object, a new version: object identity is the locator and
        # version identity is the fingerprint, so this is one object with two
        # versions and not two objects.
        assert changed.source_object_id == reclassified.object_ids["ledger"]
        record_outcome(
            connection,
            enrollment_id=reclassified.enrollment_id,
            outcome=extract_text(
                source_id=reclassified.source_id,
                source_object_id=changed.source_object_id,
                observed_version_id=changed.version_id,
                content_version_id=changed.version_id,
                media_type="application/pdf",
                content=b"%PDF-1.7\nnot extracted here\n%%EOF\n",
                observed_at=WHEN,
            ),
        )
    page = search(reclassified, "revenue")

    coverage = page.disclosure.coverage
    assert coverage.eligible == 1
    assert coverage.unsupported == 1
    assert coverage.processed == 0
    assert coverage.state is CoverageState.UNSUPPORTED
    assert page.disclosure.partial_result is True

    # And the page, which this test did not look at. `processed == 0` with
    # `no_extracted_text_in_scope` beside it is the token that means "we have not
    # indexed this"; returning the first version's text under it would be section
    # 9.7's forbidden collapse run backwards, and it is what this did.
    assert "no_extracted_text_in_scope" in page.disclosure.limitations
    assert page.matches == ()
    assert page.disclosure.source_references == ()


@pytest.mark.database
def test_a_quarantine_at_one_version_withholds_the_text_extracted_at_another(
    engine: Engine,
) -> None:
    """The page and the coverage beside it, on `coverage_for`'s own normal sequence.

    An object extracted at one version and quarantined afterwards is the sequence
    `coverage_for` documents and `INV-PKL-007` cares about, and it puts the two
    sides of one answer in direct contradiction. The coverage read excludes a
    quarantined object from `processed`; the match statement did not, so this
    scope reported `processed=0, quarantined=1, eligible=1`, state `quarantined`,
    and `no_extracted_text_in_scope` — the token that means "we have not indexed
    this" — attached to a page carrying the document's own words.

    One object, so nothing else can account for either side: there is no second
    document to keep the page non-empty and no root selector to clamp the state.
    Both halves are asserted because asserting either alone is how this survived.
    """
    stopped = enrol(
        engine, key="quarantined-after-extraction", documents={"ledger": CORPUS["ledger"]}
    )
    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=stopped.enrollment_id,
            source_object_id=stopped.object_ids["ledger"],
            version_id=stopped.version_ids["ledger"],
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    page = search(stopped, "revenue")

    coverage = page.disclosure.coverage
    assert coverage.eligible == 1
    assert coverage.quarantined == 1
    assert coverage.processed == 0
    assert coverage.state is CoverageState.QUARANTINED
    assert "no_extracted_text_in_scope" in page.disclosure.limitations

    assert page.matches == (), "a quarantined object's text was returned as a live hit"
    assert page.disclosure.source_references == ()

    # The paired control, without which the exclusion could be unconditional:
    # the same corpus and the same query with no quarantine on it still matches.
    unstopped = enrol(engine, key="not-quarantined", documents={"ledger": CORPUS["ledger"]})
    assert len(search(unstopped, "revenue").matches) == 1


@pytest.mark.database
def test_an_object_quarantined_and_recorded_unsupported_is_counted_once(engine: Engine) -> None:
    """The third pair of the precedence, and the one nothing reached.

    Two tests above hold quarantine above extracted and unsupported above
    extracted. The remaining pair is quarantine above *unsupported*, which is its
    own exclusion in its own statement: measured, deleting it alone left both
    tiers green. It is reachable in one object — a PDF that reached an outcome
    saying so, and then a containment failure — and per row that is two outcomes
    in a scope of one, which the denominator refuses outright.

    Quarantine wins here for the same reason it wins everywhere else in these
    counts: an object with a quarantine on it has stopped, and letting any other
    outcome rank above it would report a stopped object as accounted for.
    """
    stopped = enrol(
        engine,
        key="quarantined-unsupported",
        documents={"handbook": ("application/pdf", b"%PDF-1.7\nnot extracted here\n%%EOF\n")},
    )
    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=stopped.enrollment_id,
            source_object_id=stopped.object_ids["handbook"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

    coverage = search(stopped, "revenue").disclosure.coverage

    assert coverage.eligible == 1
    assert coverage.quarantined == 1
    assert coverage.unsupported == 0, "one object was counted as two outcomes"
    assert coverage.processed == 0
    assert coverage.state is CoverageState.QUARANTINED


@pytest.mark.database
def test_an_aggregate_limitation_reaches_the_disclosure_as_a_count(engine: Engine) -> None:
    """The plumbing `docs/plans/mcv-completion-plan.md` section 10 asked for.

    An object the provider refused is omitted from a listing with no signal at
    all. The count reaches the caller; nothing that says *which* object does,
    which is the boundary section 9.2 draws in the same sentence that permits
    the aggregate.
    """
    limited = enrol(engine, key="limited", documents=CORPUS)
    with limited.engine.begin() as connection:
        record_limitation(
            connection,
            enrollment_id=limited.enrollment_id,
            observed_at=WHEN,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=3,
        )
    page = search(limited, "revenue")

    assert f"{LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN.value}:3" in (
        page.disclosure.limitations
    )
    for limitation in page.disclosure.limitations:
        assert NATIVE_ROOT not in limitation
        assert not any(value in limitation for value in limited.object_ids.values())


@pytest.mark.database
def test_a_root_selector_reports_a_measured_eligible_total(engine: Engine) -> None:
    """The denominator a root selector never had, read from the stored set.

    Five tests stood here until WP-4B3, and all five pinned the same clamp: with
    no persisted object set, a root-selector enrollment's eligible total was
    derived from the outcomes it happened to hold, so whichever outcome dominated
    divided out to the whole scope. `processed`, `quarantined`, and `unsupported`
    were each reachable as a false whole-scope claim, and the fix was to hold the
    reported state at `partially_processed` and disclose two tokens saying why.

    `knowledge.enrollment_objects` replaces all of it with a measurement. Four
    objects were enumerated and two were extracted, so `eligible` is **4** — a
    number no arithmetic over the two outcomes produces, which is what makes this
    assertion about the stored set rather than about the counts beside it.

    The two deleted tokens are asserted absent *by value*, not through the enum
    that no longer holds them, so this test still means something if one is ever
    reintroduced under a new name in `Limitation`.
    """
    rooted = enrol_under_a_root(
        engine,
        key="rooted-measured",
        documents=CORPUS,
        extract=frozenset({"ledger", "minutes"}),
    )
    page = search(rooted, "revenue")

    assert page.disclosure.coverage.eligible == 4
    assert page.disclosure.coverage.processed == 2
    assert len(page.matches) == 2
    assert page.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "eligible_total_not_persisted" not in page.disclosure.limitations
    assert "scope_is_source_wide_not_root_bounded" not in page.disclosure.limitations
    # The honest incompleteness is still reported, and it is now the *only*
    # thing reported: two of four objects reached an outcome.
    assert "scope_not_fully_extracted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_the_coverage_state_of_a_fully_extracted_root_needs_no_clamp(engine: Engine) -> None:
    """The direction a clamp removal can be wrong in, asserted as the stronger state.

    Every object of the enumerated set was extracted, so `processed == eligible`
    and the honest state is `processed` with `partial_result` false. That is a
    claim the clamp made unsayable for a root selector however true it was, and a
    reinstated clamp turns it back into `partially_processed` — which is why this
    asserts the strong state and the false flag rather than merely a non-empty
    page.
    """
    rooted = enrol_under_a_root(
        engine, key="rooted-complete", documents={name: CORPUS[name] for name in ("ledger",)}
    )
    page = search(rooted, "revenue")

    assert len(page.matches) == 1
    assert page.disclosure.coverage.eligible == 1
    assert page.disclosure.coverage.processed == 1
    assert page.disclosure.coverage.state is CoverageState.PROCESSED
    assert page.disclosure.partial_result is False
    assert "scope_not_fully_extracted" not in page.disclosure.limitations
    assert "no_extracted_text_in_scope" not in page.disclosure.limitations


@pytest.mark.database
def test_search_finds_nothing_for_an_object_outside_the_enumerated_set(engine: Engine) -> None:
    """Containment for a root selector, in the shape that used to leak.

    An object of the enrollment's own source that the enumeration did not
    include, carrying text nothing else in the corpus holds. **At base this
    returned the text**: `authorized_object` restricted a root selector to its
    `source_id` and no further, so a sibling of the root was authorized, counted,
    and searchable.

    The zero is meaningless on its own — a mismatched identifier produces an
    empty result with no exception anywhere — so the control is in the same test
    and against the same enrollment: a query for an object the enumeration *did*
    include returns exactly one match, and the coverage denominator stays the
    enumerated one rather than growing by the stray.
    """
    rooted = enrol_under_a_root(
        engine, key="rooted-outside", documents={name: CORPUS[name] for name in ("ledger",)}
    )
    with rooted.engine.begin() as connection:
        stray = observe_object(
            connection,
            source_id=rooted.source_id,
            native_locator=f"{NATIVE_ROOT}/rooted-outside-sibling/schedule.md",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-rooted-outside-sibling",
            modified_at=WHEN,
            media_type="text/markdown",
            size_bytes=len(INTRUDER_DOCUMENT),
        )
    plant_an_extraction(
        engine,
        enrollment_id=rooted.enrollment_id,
        source_object_id=stray.source_object_id,
        version_id=stray.version_id,
        body=INTRUDER_DOCUMENT,
    )

    outside = search(rooted, INTRUDER)
    inside = search(rooted, "revenue")

    assert outside.matches == ()
    # The control, in the same test and under the same enrollment: the boundary
    # excludes the stray and nothing else.
    assert len(inside.matches) == 1
    assert inside.matches[0].source_object_id == rooted.object_ids["ledger"]
    assert inside.disclosure.coverage.eligible == 1
    assert inside.disclosure.coverage.processed == 1


@pytest.mark.database
def test_more_outcomes_than_the_enrollment_ceiling_is_still_a_searchable_scope(
    engine: Engine,
) -> None:
    """Search must not borrow `max_items` as a denominator, and this is why.

    `max_items` bounds what one pass over the tree is authorized to do. Outcomes
    are counted for the whole enrollment and are deliberately not time-filtered,
    so successive passes over a changing tree accumulate more of them than any
    single pass was allowed — three here against a ceiling of two, which is a
    lawful enrollment and not a corrupted one. Validating the counts against that
    ceiling raised `ValueError` out of the coverage guard, uncaught and untyped,
    and search stayed dead for the enrollment for as long as the rows existed.

    The denominator is now the enumerated set, which is three, so the ceiling is
    not a number this read can reach at all. That is a stronger answer than the
    unmeasured total that replaced it: the scope is complete and is reported
    complete, over a total nothing had to invent.
    """
    rooted = enrol_under_a_root(
        engine,
        key="rooted-past-ceiling",
        documents={name: CORPUS[name] for name in ("ledger", "minutes", "charter")},
        max_items=2,
    )
    page = search(rooted, "archive")

    assert len(page.matches) == 3
    assert page.disclosure.coverage.processed == 3
    assert page.disclosure.coverage.eligible == 3
    assert page.disclosure.coverage.state is CoverageState.PROCESSED
    assert page.disclosure.partial_result is False


def plant_an_extraction(
    engine: Engine,
    *,
    enrollment_id: str,
    source_object_id: str,
    version_id: str,
    body: str | None = None,
    status: str = "extracted",
    media_type: str = "text/markdown",
) -> None:
    """Store an extraction row by raw SQL, bypassing `record_outcome` entirely.

    Deliberately not going through the writer, because these tests are about the
    *read* side of the authorization boundary and the writer now refuses exactly
    the rows they need. A read that only held because the writer refused would be
    no boundary at all: rows already stored, written by hand, or written before
    the writer was checked would still be counted and returned. Raw SQL is how
    that state is reached now that the supported path cannot reach it.

    `status` is a parameter because the read side applies the boundary to three
    counts separately and a suite that only ever plants `extracted` rows exercises
    one of them. `text_exists_exactly_when_something_was_extracted` is why `body`
    and `status` move together: an unsupported row holds no text and an extracted
    one must.
    """
    if (body is not None) != (status == "extracted"):
        raise AssertionError("an extracted row carries text and any other row carries none")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.extractions (extraction_id, enrollment_id, "
                " source_object_id, version_id, status, media_type, extractor, "
                " extractor_version, text, observed_at, processed_at) "
                "VALUES (:kn, :enr, :obj, :ver, :status, :media_type, "
                " 'my_pa.text', '1', :body, :at, :at)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrollment_id,
                "obj": source_object_id,
                "ver": version_id,
                "status": status,
                "media_type": media_type,
                "body": body,
                "at": WHEN,
            },
        )


def plant_a_quarantine(
    engine: Engine, *, enrollment_id: str, source_object_id: str, version_id: str | None = None
) -> None:
    """Store a quarantine row by raw SQL, for the same reason as the extraction above.

    `quarantine_object` refuses exactly the rows the read-side tests need, so the
    quarantine half of the boundary has no other way to be exercised. Without one
    of these every stray the suite builds is an `extractions` row, and the
    boundary on the quarantine count is asserted by nothing.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.quarantine_records (quarantine_id, enrollment_id, "
                " source_object_id, version_id, reason, review_state, quarantined_at) "
                "VALUES (:kn, :enr, :obj, :ver, 'containment_unproven', 'pending_review', :at)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrollment_id,
                "obj": source_object_id,
                "ver": version_id,
                "at": WHEN,
            },
        )


#: A term that appears in no document of `CORPUS`, so a search for it can only
#: match text a test planted outside the searching enrollment's scope.
INTRUDER = "kestrel"

INTRUDER_DOCUMENT = (
    "The kestrel schedule records quarterly revenue for the archive of a source "
    "this enrollment never named.\n"
)


@pytest.mark.database
def test_an_outcome_stored_outside_the_named_scope_is_neither_counted_nor_returned(
    engine: Engine,
) -> None:
    """Complete coverage claimed over a scope two of whose objects reached no outcome.

    Four objects authorized, two of them extracted, and two extractions stored
    against this enrollment for objects belonging to an entirely different
    source. Counted by `enrollment_id` alone the strays fit *inside* the
    denominator rather than overflowing it, so the arithmetic came out to
    `processed == eligible == 4` and the read reported `processed`,
    `partial_result=False`, and not one limitation token — while `almanac` and
    `charter` had reached no outcome at all. That is section 9.7's conversion of
    a partial result into a complete one, and `INV-PKL-007` forbids it.

    The overflow direction of the same defect was closed a round earlier and
    this one was left open, which is why the sizes here are chosen so the strays
    fit: two in, two out, four named. A fix that only rejects counts too large
    for their denominator does not see this at all.

    The content half is asserted beside the counts because it is the same row.
    Those extractions hold text, and searching returned it: a document from a
    source outside this enrollment, with its `source_object_id` and `version_id`
    in the disclosure's `source_references`.

    The strays here are of another source *and* unnamed, so this pins neither
    condition of `authorized_object` on its own; what it pins is the arithmetic —
    strays that fit inside the denominator. The single-condition reads are
    `test_an_object_the_enrollment_names_but_another_source_owns_is_not_in_scope`
    for the source half and
    `test_an_object_of_the_enrollments_own_source_it_did_not_name_is_neither_counted_nor_returned`
    for membership.
    """
    scoped = enrol(engine, key="stray", documents=CORPUS, extract=frozenset({"ledger", "minutes"}))
    neighbour = enrol(
        engine,
        key="stray-neighbour",
        documents={name: CORPUS[name] for name in ("charter", "almanac")},
    )
    for name in ("charter", "almanac"):
        plant_an_extraction(
            engine,
            enrollment_id=scoped.enrollment_id,
            source_object_id=neighbour.object_ids[name],
            version_id=neighbour.version_ids[name],
            body=INTRUDER_DOCUMENT,
        )

    page = search(scoped, "revenue")
    coverage = page.disclosure.coverage

    assert coverage.eligible == len(CORPUS)
    assert coverage.processed == 2, "an outcome outside the authorized scope was counted"
    assert coverage.state is not CoverageState.PROCESSED
    assert coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert page.disclosure.partial_result is True
    assert "scope_not_fully_extracted" in page.disclosure.limitations

    # The content half: the planted text is not reachable, and nothing in the
    # result set or the disclosure names the source it belongs to.
    assert search(scoped, INTRUDER).matches == ()
    assert {match.source_object_id for match in page.matches} <= set(scoped.object_ids.values())
    assert not {match.source_object_id for match in page.matches} & set(
        neighbour.object_ids.values()
    )
    assert page.disclosure.scope.source_ids == (scoped.source_id,)
    for reference in page.disclosure.source_references:
        assert reference.source_id == scoped.source_id


@pytest.mark.database
def test_an_object_the_enrollment_names_but_another_source_owns_is_not_in_scope(
    engine: Engine,
) -> None:
    """The condition membership of the enumerated set does not supply.

    `accept_enrollment` writes `object_ids` as given and an array column cannot
    carry an element-level foreign key, so an enrollment can still *name* an
    object of another source. Two things then have to hold, and this test is both
    of them because a fix applied to one is this package's recurring defect.

    **The writer refuses it.** `record_scope` checks every identifier against the
    enrollment's own source before inserting, so the crossed object never becomes
    a row of `enrollment_objects` and the state is unreachable through the
    supported path. `UnknownScopeError`, naming no identifier.

    **The reader refuses it too.** `authorized_object` still tests the source
    beside the membership, and it has to: the two tables it joins have foreign
    keys to different parents and no constraint relates them, so a row written by
    hand — or before that writer existed — names an object of another source and
    passes membership. The row is planted by raw SQL here precisely because the
    writer can no longer produce it.

    That is also what makes `SearchMatch.source_id` a real question rather than a
    style one: taken from the enrollment row it would have asserted the wrong
    source for this object, and taken from the object it is right.
    """
    owner = enrol(engine, key="named-foreign", documents={"ledger": CORPUS["ledger"]})
    foreign = enrol(engine, key="named-foreign-other", documents={"minutes": CORPUS["minutes"]})
    with engine.begin() as connection:
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=owner.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(
                    object_ids=(owner.object_ids["ledger"], foreign.object_ids["minutes"])
                ),
                media_types=("text/markdown",),
                policy_version="mcv-1",
                idempotency_key=f"named-foreign-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
        )
    crossed = Corpus(
        engine=engine,
        source_id=owner.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids={"ledger": owner.object_ids["ledger"], "minutes": foreign.object_ids["minutes"]},
        version_ids={
            "ledger": owner.version_ids["ledger"],
            "minutes": foreign.version_ids["minutes"],
        },
    )

    # The writer's half: the crossed identifier is refused, and the refusal names
    # nothing, so a caller cannot use it to learn that an object it may not see
    # exists.
    with pytest.raises(UnknownScopeError) as refused, engine.begin() as connection:
        record_scope(
            connection,
            crossed.enrollment_id,
            [crossed.object_ids["ledger"], crossed.object_ids["minutes"]],
        )
    assert crossed.object_ids["minutes"] not in str(refused.value)

    # What the enumeration would legitimately have recorded, plus the crossed row
    # planted by hand — which is the only way to reach the state the reader has
    # to hold against now that the writer refuses it.
    with engine.begin() as connection:
        record_scope(connection, crossed.enrollment_id, [crossed.object_ids["ledger"]])
        connection.execute(
            text(
                "INSERT INTO knowledge.enrollment_objects (enrollment_id, source_object_id) "
                "VALUES (:enr, :obj)"
            ),
            {"enr": crossed.enrollment_id, "obj": crossed.object_ids["minutes"]},
        )

    media_type, body = CORPUS["ledger"]
    with engine.begin() as connection:
        record_outcome(
            connection,
            enrollment_id=crossed.enrollment_id,
            outcome=extract_text(
                source_id=owner.source_id,
                source_object_id=crossed.object_ids["ledger"],
                observed_version_id=crossed.version_ids["ledger"],
                content_version_id=crossed.version_ids["ledger"],
                media_type=media_type,
                content=body,
                observed_at=WHEN,
            ),
        )

    # Named, and still refused on the write path: the enrollment does not own it.
    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=crossed.enrollment_id,
            source_object_id=crossed.object_ids["minutes"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

    plant_an_extraction(
        engine,
        enrollment_id=crossed.enrollment_id,
        source_object_id=crossed.object_ids["minutes"],
        version_id=crossed.version_ids["minutes"],
        body=INTRUDER_DOCUMENT,
    )
    page = search(crossed, "revenue")

    assert {match.source_object_id for match in page.matches} == {crossed.object_ids["ledger"]}
    # Two rows in the enumerated set, one of them planted, and only the one whose
    # source matches is counted — so the denominator sees the planted row and the
    # numerator does not, which is the shape a source condition alone can produce.
    assert page.disclosure.coverage.eligible == 2
    assert page.disclosure.coverage.processed == 1
    assert page.disclosure.partial_result is True
    assert search(crossed, INTRUDER).matches == ()


def test_the_authorization_predicate_validates_the_enrollment_it_is_given() -> None:
    """`authorized_object` checks its own argument, and nothing else was checking it.

    Not a database test: the predicate is built before anything is executed, and
    this is where the check runs. Every caller in this package happens to validate
    the same identifier first, so deleting the check here left both tiers green —
    which is an accident of the current callers rather than a property of the
    function. It is public, it composes into other modules' statements, and an
    identifier it never looked at would compile into a predicate that silently
    matches nothing instead of being refused.
    """
    with pytest.raises(InvalidIdentifierError):
        authorized_object(literal("obj_x", Text), enrollment_id=f"{NATIVE_ROOT}/ledger")


def test_the_content_type_predicate_validates_the_enrollment_it_is_given() -> None:
    """The same check on the second predicate, for the same reason as the first.

    `authorized_media_type` is public and composes into other modules'
    statements, and deleting its `validate_identifier` left both tiers green:
    every caller in this package happens to validate the same identifier first,
    which is a fact about the callers rather than about the function. Without the
    check an identifier it never looked at compiles into a predicate that
    silently matches nothing.
    """
    with pytest.raises(InvalidIdentifierError):
        authorized_media_type(literal("text/plain", Text), enrollment_id=f"{NATIVE_ROOT}/ledger")


def test_a_match_takes_its_source_from_the_matched_object() -> None:
    """Which table the returned `source_id` is read out of, asserted on the statement.

    Not a database test, because this is decidable from the statement and the
    statement is where the decision lives. The two candidate columns hold
    different facts — `enrollments.source_id` is the source the enrollment was
    accepted against, `source_objects.source_id` is the source that owns the row
    being returned — and search used to fill every `SearchMatch` and every
    `SourceReference` from the first one, for every match, whatever the object's
    own source was.

    The boundary now makes the two equal for anything a search can return, which
    is precisely why this has to be asserted here: with them equal, no test that
    compares returned values can tell which column was read. This one can.
    """
    request = SearchRequest(
        enrollment_id=issue_identifier(IdKind.ENROLLMENT), query=SearchQuery("revenue")
    )
    statement = match_statement(request, None)

    selected = [column for column in statement.selected_columns if column.name == "source_id"]
    assert len(selected) == 1, "the statement selects no single source_id"
    assert selected[0].table is source_objects, "the source is read from the enrollment row"
    assert "JOIN knowledge.source_objects" in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.database
def test_every_match_names_the_source_its_object_belongs_to(corpus: Corpus) -> None:
    """The runtime half: the derived source and the enrollment's agree, and are checked to.

    The disclosure states one authorized scope and every `SourceReference` inside
    it has to belong to that scope. This asserts the agreement against the stored
    owner of each object rather than against the enrollment row, so it is a
    comparison of two independently obtained facts and not a restatement of one.
    """
    page = search(corpus, "archive")
    assert page.matches, "the fixture returned nothing; this would prove nothing"

    with corpus.engine.connect() as connection:
        for match in page.matches:
            owner = connection.execute(
                select(source_objects.c.source_id).where(
                    source_objects.c.source_object_id == match.source_object_id
                )
            ).scalar_one()
            assert match.source_id == owner
    assert {match.source_id for match in page.matches} == set(page.disclosure.scope.source_ids)
    assert {reference.source_id for reference in page.disclosure.source_references} == {
        corpus.source_id
    }


@pytest.mark.database
def test_a_quarantine_for_an_object_the_enrollment_does_not_authorize_is_refused(
    engine: Engine,
) -> None:
    """The write side of the boundary, on the path that had no membership check at all.

    `quarantine_object` used to validate identifier syntax and nothing else, so a
    quarantine could be filed against any object in the database under any
    enrollment, and the row it left was then counted as coverage of that
    enrollment's scope. Refusing it is what makes the inconsistent state
    impossible rather than merely unreported — the read side alone would decline
    to count the row while leaving it sitting there.

    The refusal is checked to be complete: nothing is written, so a caller
    retrying after fixing its scope is not competing with a half-recorded event.

    The neighbour is a separate source, so what refuses this call is the source
    condition; the membership condition is refused on the same writer by
    `test_an_object_of_the_enrollments_own_source_it_did_not_name_is_refused_by_both_writers`.
    """
    scoped = enrol(engine, key="unauthorized-quarantine", documents=CORPUS)
    neighbour = enrol(engine, key="unauthorized-neighbour", documents={"ledger": CORPUS["ledger"]})

    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=neighbour.object_ids["ledger"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT count(*) FROM knowledge.quarantine_records WHERE enrollment_id = :enr"),
            {"enr": scoped.enrollment_id},
        ).scalar_one()
    assert stored == 0

    # The control: the same call for an object the enrollment does name works.
    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=scoped.object_ids["charter"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    assert search(scoped, "revenue").disclosure.coverage.quarantined == 1


@pytest.mark.database
def test_an_extraction_outcome_for_an_object_the_enrollment_does_not_authorize_is_refused(
    engine: Engine,
) -> None:
    """The same boundary on the other writer, and it must be the other writer's too.

    `record_outcome` routes a quarantined outcome to `quarantine_object` and
    inserts everything else itself, so a check placed only on the quarantine path
    would leave the path that stores *text* unguarded — the worse of the two,
    because the row it writes is the one a search returns.

    Refused here by the source condition, the neighbour being its own source. The
    membership condition on this writer is
    `test_an_object_of_the_enrollments_own_source_it_did_not_name_is_refused_by_both_writers`.
    """
    scoped = enrol(engine, key="unauthorized-outcome", documents={"ledger": CORPUS["ledger"]})
    neighbour = enrol(
        engine, key="unauthorized-outcome-neighbour", documents={"minutes": CORPUS["minutes"]}
    )
    media_type, body = CORPUS["minutes"]

    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        record_outcome(
            connection,
            enrollment_id=scoped.enrollment_id,
            outcome=extract_text(
                source_id=neighbour.source_id,
                source_object_id=neighbour.object_ids["minutes"],
                observed_version_id=neighbour.version_ids["minutes"],
                content_version_id=neighbour.version_ids["minutes"],
                media_type=media_type,
                content=body,
                observed_at=WHEN,
            ),
        )

    page = search(scoped, "revenue")
    assert {match.source_object_id for match in page.matches} == {scoped.object_ids["ledger"]}
    assert page.disclosure.coverage.processed == 1
    assert page.disclosure.coverage.eligible == 1


@pytest.mark.database
def test_a_root_selector_enrollment_refuses_an_object_of_another_source(engine: Engine) -> None:
    """The write side, for the selector that used to store no object set.

    An enrollment naming a root now persists what its enumeration found, so
    `authorized_object` tests membership for it exactly as for a named list. Both
    of its conditions are therefore live here, and this test holds the *source*
    one: an object of another source is refused whatever the enumeration
    recorded.

    The control is in the same test and is what makes the refusal about the
    object rather than about the enrollment: the enumerated object of the
    enrollment's own source is quarantined successfully, in the same transaction
    shape, and the count moves.
    """
    rooted = enrol_under_a_root(
        engine, key="rooted-write-side", documents={"ledger": CORPUS["ledger"]}, extract=frozenset()
    )
    neighbour = enrol(
        engine, key="rooted-write-side-neighbour", documents={"minutes": CORPUS["minutes"]}
    )

    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=rooted.enrollment_id,
            source_object_id=neighbour.object_ids["minutes"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=rooted.enrollment_id,
            source_object_id=rooted.object_ids["ledger"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    coverage = search(rooted, "revenue").disclosure.coverage
    assert coverage.quarantined == 1
    assert coverage.eligible == 1


@pytest.mark.database
def test_an_object_of_the_enrollments_own_source_it_did_not_name_is_refused_by_both_writers(
    engine: Engine,
) -> None:
    """The membership half of the boundary, with the source half held constant.

    Every other refusal test above builds its unauthorized object with a separate
    `enrol`, which mints a separate source — so the object fails *both* conditions
    of `authorized_object` at once and the refusal proves neither. Measured:
    replacing the membership condition with a constant true leaves the whole suite
    green. A test that violates two conditions pins neither.

    Here one source carries two enrollments. `scoped` names `ledger`; `beside`
    names `minutes`; both objects belong to the same source, so the source
    condition is satisfied for both and membership is the only thing that can
    refuse. Both writers are exercised, because `record_outcome` routes
    quarantines to `quarantine_object` and inserts everything else itself, so a
    check on one path says nothing about the other.

    **The refusal is committed, not rolled back, and that is the whole of what
    makes the ordering checkable.** This test previously ran each refusal inside
    `engine.begin()` and then counted the rows, over a sentence claiming "nothing
    is written". The assertion could not fail: `begin()` rolls back when the block
    raises, so the counts were the fixture's own whether the check ran before the
    insert or after it — moving the refusal below the insert left it green. Here
    the transaction is opened by hand and *committed* after the refusal, which is
    lawful because an `UnauthorizedObjectError` is raised by Python with the
    transaction still valid. A check that ran after the insert therefore commits
    that insert and the counts below say so.
    """
    scoped = enrol(engine, key="member-write", documents={"ledger": CORPUS["ledger"]})
    beside = enrol_beside(
        scoped, key="member-write-beside", documents={"minutes": CORPUS["minutes"]}
    )
    assert beside.source_id == scoped.source_id, "the two enrollments must share one source"

    media_type, body = CORPUS["minutes"]
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(UnauthorizedObjectError):
            record_outcome(
                connection,
                enrollment_id=scoped.enrollment_id,
                outcome=extract_text(
                    source_id=scoped.source_id,
                    source_object_id=beside.object_ids["minutes"],
                    observed_version_id=beside.version_ids["minutes"],
                    content_version_id=beside.version_ids["minutes"],
                    media_type=media_type,
                    content=body,
                    observed_at=WHEN,
                ),
            )
        transaction.commit()
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(UnauthorizedObjectError):
            quarantine_object(
                connection,
                enrollment_id=scoped.enrollment_id,
                source_object_id=beside.object_ids["minutes"],
                version_id=None,
                reason=QuarantineReason.CONTAINMENT_UNPROVEN,
            )
        transaction.commit()

    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT (SELECT count(*) FROM knowledge.extractions WHERE enrollment_id = :enr), "
                " (SELECT count(*) FROM knowledge.quarantine_records WHERE enrollment_id = :enr)"
            ),
            {"enr": scoped.enrollment_id},
        ).one()
    # One extraction, the fixture's own. Each refusal ran and was then committed,
    # so a row either writer had already inserted would be in these counts.
    assert stored == (1, 0)

    # The control, on the same source and the same writers: the object this
    # enrollment did name is accepted, so what refused the other one is
    # membership and not something about the pair of enrollments.
    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=scoped.object_ids["ledger"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )


@pytest.mark.database
def test_an_object_of_the_enrollments_own_source_it_did_not_name_is_neither_counted_nor_returned(
    engine: Engine,
) -> None:
    """The same single-condition variation on the read side.

    `scoped` names one object of its source and has extracted it. Two more
    objects of *that same source* belong to a second enrollment, and extractions
    holding text are planted against `scoped` for both — the state the writer now
    refuses and that rows written by hand or written earlier still reach.

    With membership enforced the strays are outside the scope: they are not
    counted, and their text is not returned. Without it they are counted, and the
    counts then exceed `cardinality(object_ids)` — the denominator `search` takes
    from the enrollment itself — so `coverage_for` raises and search is dead for
    this enrollment rather than merely wrong about it. Both halves are asserted,
    because the count and the content are the same row.
    """
    scoped = enrol(engine, key="member-read", documents={"ledger": CORPUS["ledger"]})
    beside = enrol_beside(
        scoped,
        key="member-read-beside",
        documents={name: CORPUS[name] for name in ("minutes", "charter")},
    )
    for name in ("minutes", "charter"):
        plant_an_extraction(
            engine,
            enrollment_id=scoped.enrollment_id,
            source_object_id=beside.object_ids[name],
            version_id=beside.version_ids[name],
            body=INTRUDER_DOCUMENT,
        )

    page = search(scoped, "revenue")
    coverage = page.disclosure.coverage

    assert coverage.eligible == 1
    assert coverage.processed == 1, "an object of the source the enrollment never named was counted"
    assert coverage.state is CoverageState.PROCESSED
    assert {match.source_object_id for match in page.matches} == {scoped.object_ids["ledger"]}
    assert search(scoped, INTRUDER).matches == ()
    assert not {
        reference.source_object_id for reference in page.disclosure.source_references
    } & set(beside.object_ids.values())


@pytest.mark.database
def test_a_quarantine_outside_the_named_objects_of_the_same_source_is_not_counted(
    engine: Engine,
) -> None:
    """The boundary on the quarantine count, which no other test reaches.

    Every stray the rest of this file builds is an `extractions` row, so deleting
    the boundary from the quarantine count alone left both tiers green. The row
    is planted rather than written, because `quarantine_object` refuses it, and it
    names an object of the enrollment's *own* source that the enrollment did not
    name — one condition varied, not two.

    Counted, it would be a second outcome inside a scope of one object, which the
    denominator refuses outright: the read would raise rather than return a wrong
    number. Both are stated, since the count is the claim and the crash is only
    how this particular fixture happens to notice it.
    """
    scoped = enrol(engine, key="stray-quarantine", documents={"ledger": CORPUS["ledger"]})
    beside = enrol_beside(
        scoped, key="stray-quarantine-beside", documents={"minutes": CORPUS["minutes"]}
    )
    plant_a_quarantine(
        engine,
        enrollment_id=scoped.enrollment_id,
        source_object_id=beside.object_ids["minutes"],
        version_id=beside.version_ids["minutes"],
    )

    coverage = search(scoped, "revenue").disclosure.coverage

    assert coverage.quarantined == 0, "a quarantine outside the authorized scope was counted"
    assert coverage.processed == 1
    assert coverage.eligible == 1
    assert coverage.state is CoverageState.PROCESSED


@pytest.mark.database
def test_an_unsupported_row_outside_the_named_objects_of_the_same_source_is_not_counted(
    engine: Engine,
) -> None:
    """The boundary on the unsupported count, for the same reason and in the same shape.

    `coverage_for` applies the boundary at three counts and each is its own
    statement. A suite that plants only `extracted` rows exercises one of them, so
    this plants an `unsupported` one — no text, which is what
    `text_exists_exactly_when_something_was_extracted` requires of it — for an
    object of the enrollment's own source that it did not name.
    """
    scoped = enrol(engine, key="stray-unsupported", documents={"ledger": CORPUS["ledger"]})
    beside = enrol_beside(
        scoped, key="stray-unsupported-beside", documents={"minutes": CORPUS["minutes"]}
    )
    plant_an_extraction(
        engine,
        enrollment_id=scoped.enrollment_id,
        source_object_id=beside.object_ids["minutes"],
        version_id=beside.version_ids["minutes"],
        status="unsupported",
        media_type="application/pdf",
    )

    coverage = search(scoped, "revenue").disclosure.coverage

    assert coverage.unsupported == 0, "an unsupported row outside the authorized scope was counted"
    assert coverage.processed == 1
    assert coverage.eligible == 1
    assert coverage.state is CoverageState.PROCESSED


@pytest.mark.database
def test_an_extraction_of_a_content_type_the_enrollment_did_not_allow_is_refused(
    engine: Engine,
) -> None:
    """The write side of the dimension nothing enforced at all.

    `enrollments.media_types` is section 9.6's content-type allowlist. It was
    stored `NOT NULL`, kept non-empty by a check constraint, normalized and
    validated at acceptance — and then never read again by anything. An
    enrollment allowing `text/plain` could be handed an object of `text/markdown`
    and the writer took it, the coverage read counted it as processed, and a
    search returned a snippet of its text with nothing in the envelope saying so.

    Only the content type varies here. `ledger` is an object of the enrollment's
    own source that the enrollment names, so both conditions of
    `authorized_object` are satisfied and the object dimension cannot account for
    the refusal. `almanac`, the `text/plain` control, goes through the same writer
    in the same fixture.

    The transaction is committed after the refusal for the reason
    `test_an_object_of_the_enrollments_own_source_it_did_not_name_is_refused_by_both_writers`
    gives: rolling back would make the count true whatever order the check ran in.
    """
    scoped = enrol(
        engine,
        key="type-write",
        documents={name: CORPUS[name] for name in ("almanac", "ledger")},
        media_types=("text/plain",),
        extract=frozenset({"almanac"}),
    )

    media_type, body = CORPUS["ledger"]
    assert media_type == "text/markdown", "the refused type must not be the allowed one"
    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(UnauthorizedObjectError) as raised:
            record_outcome(
                connection,
                enrollment_id=scoped.enrollment_id,
                outcome=extract_text(
                    source_id=scoped.source_id,
                    source_object_id=scoped.object_ids["ledger"],
                    observed_version_id=scoped.version_ids["ledger"],
                    content_version_id=scoped.version_ids["ledger"],
                    media_type=media_type,
                    content=body,
                    observed_at=WHEN,
                ),
            )
        transaction.commit()

    # The message names the grant, the object, and which dimension refused. It
    # does not name the media type: the value stays out for the same reason a
    # locator does.
    message = str(raised.value)
    assert scoped.enrollment_id in message
    assert scoped.object_ids["ledger"] in message
    assert "content type" in message
    for withheld in ("text/markdown", "text/plain", NATIVE_ROOT, body.decode()):
        assert withheld not in message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None

    # Nothing was written, and the control was: one extraction, the `text/plain`
    # object's own.
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT count(*) FROM knowledge.extractions WHERE enrollment_id = :enr"),
            {"enr": scoped.enrollment_id},
        ).scalar_one()
    assert stored == 1
    assert search(scoped, "archive").disclosure.coverage.processed == 1


@pytest.mark.database
def test_an_extraction_of_a_content_type_outside_the_allowlist_is_neither_counted_nor_returned(
    engine: Engine,
) -> None:
    """The read side of the same dimension, on a row the writer now refuses.

    Planted rather than written, for the reason `plant_an_extraction` gives: the
    read side has to hold against rows already stored, written by hand, or
    written before the check existed, and the writer can no longer produce one.

    Two objects, both named by the enrollment and both of its source, so the
    object dimension admits both and only the media type separates them. The
    `text/markdown` row holds text and is planted against an enrollment that
    allows `text/plain` alone: it is not counted as processed and its text is not
    returned. The `text/plain` object beside it is, which is what makes this a
    statement about the allowlist rather than about the fixture.

    A `NULL` media type is not exercised and cannot be:
    `only_a_supported_media_type_is_extracted` forbids an extracted row without
    one, so no arrangement of rows reaches the predicate with a null. That it
    would fail closed is a property of `= ANY`, recorded at
    `authorized_media_type` rather than asserted here.
    """
    scoped = enrol(
        engine,
        key="type-read",
        documents={name: CORPUS[name] for name in ("almanac", "ledger")},
        media_types=("text/plain",),
        extract=frozenset({"almanac"}),
    )
    plant_an_extraction(
        engine,
        enrollment_id=scoped.enrollment_id,
        source_object_id=scoped.object_ids["ledger"],
        version_id=scoped.version_ids["ledger"],
        body=INTRUDER_DOCUMENT,
        media_type="text/markdown",
    )

    page = search(scoped, "archive")
    coverage = page.disclosure.coverage

    assert coverage.eligible == 2
    assert coverage.processed == 1, (
        "text of a content type the enrollment never allowed was counted"
    )
    assert coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert page.disclosure.partial_result is True
    assert {match.source_object_id for match in page.matches} == {scoped.object_ids["almanac"]}
    assert search(scoped, INTRUDER).matches == ()
    assert not {reference.source_object_id for reference in page.disclosure.source_references} & {
        scoped.object_ids["ledger"]
    }


@pytest.mark.database
def test_an_allowlist_naming_no_type_this_extractor_reads_authorizes_no_extracted_text(
    engine: Engine,
) -> None:
    """The allowlist entry that is outside `SUPPORTED_MEDIA_TYPES`, which is lawful.

    Nothing stops an operator allowing `application/pdf`: it is a bare
    `type/subtype`, `domain.source.enrollment` accepts it, and `P00-OD-003` is the
    open decision about whether anything will ever read one. An extracted row's
    media type is confined to the two types this extractor produces by
    `only_a_supported_media_type_is_extracted`, so such an enrollment authorizes
    no extracted text at all — and the honest report of that is zero processed
    objects and no matches, not an exception and not a special case.

    Both halves are asserted because they are separately deletable: the writer
    refuses, and a row planted past the writer is not returned either.
    """
    scoped = enrol(
        engine,
        key="type-pdf-only",
        documents={"ledger": CORPUS["ledger"]},
        media_types=("application/pdf",),
        extract=frozenset(),
    )

    media_type, body = CORPUS["ledger"]
    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        record_outcome(
            connection,
            enrollment_id=scoped.enrollment_id,
            outcome=extract_text(
                source_id=scoped.source_id,
                source_object_id=scoped.object_ids["ledger"],
                observed_version_id=scoped.version_ids["ledger"],
                content_version_id=scoped.version_ids["ledger"],
                media_type=media_type,
                content=body,
                observed_at=WHEN,
            ),
        )

    plant_an_extraction(
        engine,
        enrollment_id=scoped.enrollment_id,
        source_object_id=scoped.object_ids["ledger"],
        version_id=scoped.version_ids["ledger"],
        body=INTRUDER_DOCUMENT,
        media_type="text/markdown",
    )
    page = search(scoped, INTRUDER)

    assert page.matches == ()
    assert page.disclosure.coverage.processed == 0
    assert page.disclosure.coverage.eligible == 1
    assert "no_extracted_text_in_scope" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_the_allowlist_does_not_erase_the_report_of_a_type_it_excludes(engine: Engine) -> None:
    """The paired negative, and the reason the content dimension stops where it does.

    An allowlist that gated every count would be simpler and would be wrong.
    `unsupported` is the section 12 report that an object's media type is one this
    extractor does not read, and through `extract_text` that type is always
    outside the two it does — so gating that count by the allowlist would erase
    the report for exactly the objects it exists to make, and would leave an
    operator having to authorize PDF *content* in order to be told PDFs are
    there. `quarantined` cannot be gated at all: `quarantine_records` stores no
    media type and `quarantine_object` takes none.

    So this enrollment allows `text/plain` alone, holds a PDF, and must still
    report it — first as unsupported, then, once processing of it stops, as
    quarantined. Both counts fall to zero if the dimension is extended to them.
    """
    scoped = enrol(
        engine,
        key="type-negative",
        documents={
            "almanac": CORPUS["almanac"],
            "handbook": ("application/pdf", b"%PDF-1.7\nnot extracted here\n%%EOF\n"),
        },
        media_types=("text/plain",),
    )
    coverage = search(scoped, "archive").disclosure.coverage

    assert coverage.unsupported == 1, "an unsupported object was hidden by the content allowlist"
    assert coverage.processed == 1
    assert coverage.eligible == 2

    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=scoped.object_ids["handbook"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    coverage = search(scoped, "archive").disclosure.coverage

    assert coverage.quarantined == 1, "a quarantine was hidden by the content allowlist"
    assert coverage.unsupported == 0
    assert coverage.processed == 1


@pytest.mark.database
def test_a_root_selector_enrollment_no_longer_reaches_its_whole_source(
    engine: Engine,
) -> None:
    """The limit this suite used to assert *as a fact*, now closed and asserted closed.

    Until WP-4B3 this test was named
    `test_a_root_selector_enrollment_reaches_its_whole_source_and_the_envelope_says_so`
    and it required the opposite of what it requires now: an object of the same
    source that the depth walk would never have reached was accepted by both
    writers, counted by `coverage_for`, and returned by a search, and the test's
    obligation was that two limitation tokens disclosed it. Its own docstring said
    "when WP-4 persists the enumerated object set, the acceptances below become
    refusals and this test is the one that has to be rewritten". This is that
    rewrite.

    The sibling is refused by the writer and, planted past the writer, is still
    excluded by the reader — both halves, because the read side has to hold
    against rows already stored or written by hand and the write side is what
    stops new ones.

    Every assertion sits beside a control over the enumerated object in the same
    enrollment: one match, one processed, one eligible. A suite that only checked
    the sibling's absence would agree with an enrollment that authorized nothing.
    """
    rooted = enrol_under_a_root(
        engine, key="rooted-source-wide", documents={"ledger": CORPUS["ledger"]}
    )
    with engine.begin() as connection:
        # A sibling of the root, not under it, in the same source.
        outside = observe_object(
            connection,
            source_id=rooted.source_id,
            native_locator=f"{NATIVE_ROOT}/rooted-source-wide-sibling/payroll.md",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-rooted-source-wide-sibling",
            modified_at=WHEN,
            media_type="text/markdown",
            size_bytes=len(INTRUDER_DOCUMENT),
        )

    # Refused now. This was an acceptance, asserted as what happened.
    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        record_outcome(
            connection,
            enrollment_id=rooted.enrollment_id,
            outcome=extract_text(
                source_id=rooted.source_id,
                source_object_id=outside.source_object_id,
                observed_version_id=outside.version_id,
                content_version_id=outside.version_id,
                media_type="text/markdown",
                content=INTRUDER_DOCUMENT.encode("utf-8"),
                observed_at=WHEN,
            ),
        )

    # And past the writer, by hand, because the reader is a separate guarantee.
    plant_an_extraction(
        engine,
        enrollment_id=rooted.enrollment_id,
        source_object_id=outside.source_object_id,
        version_id=outside.version_id,
        body=INTRUDER_DOCUMENT,
    )
    page = search(rooted, INTRUDER)
    control = search(rooted, "revenue")

    assert page.matches == ()
    assert {match.source_object_id for match in control.matches} == {rooted.object_ids["ledger"]}
    assert control.disclosure.coverage.processed == 1
    assert control.disclosure.coverage.eligible == 1
    assert control.disclosure.coverage.state is CoverageState.PROCESSED
    assert "scope_is_source_wide_not_root_bounded" not in control.disclosure.limitations
    assert "eligible_total_not_persisted" not in control.disclosure.limitations


@pytest.mark.database
def test_an_enrollment_that_named_its_objects_makes_no_source_wide_disclosure(
    corpus: Corpus,
) -> None:
    """The paired negative for the test above, kept because the pair is the claim.

    Neither token may appear for either selector now. The named-objects case is
    where they never applied, so a token here would have been a limitation
    claimed where none applies; the root case above is where they did apply and
    no longer do. Asserting both is what makes "removed from the vocabulary"
    different from "moved to the other branch".
    """
    limitations = search(corpus, "revenue").disclosure.limitations
    assert "scope_is_source_wide_not_root_bounded" not in limitations
    assert "eligible_total_not_persisted" not in limitations


@pytest.mark.database
def test_the_authorization_predicate_answers_about_its_argument_and_not_the_enclosing_row(
    engine: Engine,
) -> None:
    """What `correlate_except` is for, at the only level where it is visible.

    `authorized_object` takes the object column as an argument, so both of its
    tables have to be resolved inside its own subquery. Left to SQLAlchemy's
    automatic correlation, `source_objects` binds to an enclosing statement that
    selects from it, and `source_objects.source_object_id == source_object_id`
    stops being a lookup of the argument and becomes a restriction on the
    enclosing row.

    `match_statement` cannot show this and it is worth saying why rather than
    picking a fixture that happens to work: it joins `source_objects` on exactly
    that equality, so the correlated and uncorrelated forms agree there for every
    row, and removing `correlate_except` leaves the whole suite green. The
    statement below is the general case the predicate is written for — an
    enclosing `FROM` that includes one of the two tables and does *not* constrain
    it to the argument. With the tables uncorrelated the predicate is a constant
    for the whole statement and every row of the source is returned; correlated,
    it collapses to the single row whose identifier happens to equal the argument.
    """
    scoped = enrol(
        engine,
        key="correlate",
        documents={name: CORPUS[name] for name in ("ledger", "minutes", "charter")},
    )
    authorized = authorized_object(
        literal(scoped.object_ids["ledger"], Text), enrollment_id=scoped.enrollment_id
    )
    with engine.connect() as connection:
        counted = connection.execute(
            select(func.count())
            .select_from(source_objects)
            .where(source_objects.c.source_id == scoped.source_id, authorized)
        ).scalar_one()

    assert counted == len(scoped.object_ids) == 3, (
        "the predicate answered about the enclosing row rather than about its argument"
    )


@pytest.mark.database
def test_the_authorization_predicate_resolves_its_enrollment_whatever_encloses_it(
    engine: Engine,
) -> None:
    """The other table `correlate_except` names, which the test above cannot reach.

    `authorized_object` protects two tables and the test above varies only one:
    its enclosing statement selects from `source_objects`, so dropping
    `enrollments` from the call leaves that assertion green. The enclosing
    statement here selects from `enrollments` instead, which is where that half
    decides — correlated away, `enrollments.enrollment_id = …` binds the
    enclosing row and the predicate answers about whichever enrollment the outer
    statement is looking at.

    Two enrollments over one source, asked about one of them. Resolved correctly
    the predicate is a constant for the statement and both rows are returned;
    correlated away it collapses to the one whose identifier equals the argument.
    """
    scoped = enrol(engine, key="object-correlate", documents={"ledger": CORPUS["ledger"]})
    enrol_over(scoped, key="object-correlate-other", names=("ledger",))
    predicate = authorized_object(
        literal(scoped.object_ids["ledger"], Text), enrollment_id=scoped.enrollment_id
    )

    with engine.connect() as connection:
        counted = connection.execute(
            select(func.count())
            .select_from(enrollments)
            .where(enrollments.c.source_id == scoped.source_id, predicate)
        ).scalar_one()

    assert counted == 2, (
        "the predicate answered about the enclosing enrollment rather than the one it was given"
    )


@pytest.mark.database
def test_the_content_type_predicate_answers_about_its_argument_and_not_the_enclosing_row(
    engine: Engine,
) -> None:
    """`correlate_except` on the content dimension, in the argument form that ships.

    This test previously passed `literal("text/plain")`, and under that argument
    the property holds whether or not the call is there: the subquery's only
    `FROM` is `enrollments`, which SQLAlchemy will not correlate away. Both read
    call sites pass `extractions.media_type`, which brings a second table, and
    then it is the enclosing statement that decides. Inside a statement over
    `extractions` — `coverage_for`'s shape and `match_statement`'s — the two
    forms still compile identically. Inside a statement over `enrollments` they
    do not: `enrollments` is correlated away, the subquery is left selecting from
    `extractions` alone, and `enrollments.enrollment_id = …` binds the enclosing
    row, so the predicate answers about whichever enrollment the outer statement
    is looking at rather than about the one it was given.

    That is what this builds, with rows. Two enrollments over one source, and the
    predicate is asked about one of them. Resolved correctly it is a constant for
    the statement — some extraction somewhere has a type this enrollment allows —
    and both rows are returned. Correlated away it collapses to the single
    enrollment whose identifier equals the argument, and one row is.
    """
    scoped = enrol(engine, key="content-correlate", documents={"ledger": CORPUS["ledger"]})
    enrol_over(scoped, key="content-correlate-other", names=("ledger",))
    predicate = authorized_media_type(extractions.c.media_type, enrollment_id=scoped.enrollment_id)

    sql = str(
        select(func.count())
        .select_from(enrollments)
        .where(predicate)
        .compile(dialect=postgresql.dialect())
    )
    inner = sql[sql.index("EXISTS (") :]
    assert "FROM knowledge.enrollments" in inner, (
        "the predicate was correlated to the enclosing statement instead of resolving its own table"
    )

    with engine.connect() as connection:
        counted = connection.execute(
            select(func.count())
            .select_from(enrollments)
            .where(enrollments.c.source_id == scoped.source_id, predicate)
        ).scalar_one()

    assert counted == 2, (
        "the predicate answered about the enclosing enrollment rather than about its argument"
    )


@pytest.mark.database
def test_quarantine_object_refuses_an_identifier_that_is_not_one(engine: Engine) -> None:
    """Two of `quarantine_object`'s three identifier checks, which nothing reached.

    Deleting either left both tiers green while changing what a caller is told.
    Without the object check a locator-shaped `source_object_id` reaches
    `authorized_object`, matches nothing, and comes back as
    `UnauthorizedObjectError` — a refusal on authorization grounds for a value
    that is not an identifier at all, which a caller would act on by fixing its
    scope. Without the version check the value reaches the insert and comes back
    as a foreign-key violation, whose driver message quotes the value: that is a
    locator in a database error, which is the leak `INV-PKL-005` exists to stop.

    The third, on `enrollment_id`, is deliberately not asserted here and cannot
    be: `authorized_object` validates the same identifier a few lines later and
    raises the same error. `persistence.extraction` states the rule that keeps it
    anyway.
    """
    scoped = enrol(engine, key="quarantine-identifiers", documents={"ledger": CORPUS["ledger"]})

    with pytest.raises(InvalidIdentifierError), engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=f"{NATIVE_ROOT}/ledger",
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    with pytest.raises(InvalidIdentifierError), engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=scoped.object_ids["ledger"],
            version_id=f"{NATIVE_ROOT}/ledger#1",
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

    # The control: the same call with well-formed identifiers is recorded.
    with engine.begin() as connection:
        record = quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=scoped.object_ids["ledger"],
            version_id=scoped.version_ids["ledger"],
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    assert record.version_id == scoped.version_ids["ledger"]


@pytest.mark.database
def test_a_limitation_is_refused_unless_it_is_a_positive_count_at_a_stated_instant(
    engine: Engine,
) -> None:
    """Three of `record_limitation`'s preconditions, none of which was reached.

    Each fails differently without its check, and each failure is worse than the
    refusal it replaces. A malformed `enrollment_id` reaches the insert and comes
    back as a foreign-key violation quoting the value. A count of zero is
    *written* and then rejected by `AggregateLimitation`, so the caller gets an
    error and the row stays — "nothing was omitted for this reason" is a claim
    about the source the layer cannot support, and it must not be storable. A
    naive `observed_at` is written into a `timestamptz` column, where the server
    reads it in whatever time zone the session happens to hold, so the snapshot
    the limitation is filed under is no longer the snapshot the caller named and
    `coverage_for` will not match it.

    The zero case is committed rather than rolled back, for the reason
    `test_an_object_of_the_enrollments_own_source_it_did_not_name_is_refused_by_both_writers`
    gives: a rolled-back count cannot tell a refusal from a write undone.
    """
    scoped = enrol(engine, key="limitation-preconditions", documents={"ledger": CORPUS["ledger"]})
    reason = LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN

    with pytest.raises(InvalidIdentifierError), engine.begin() as connection:
        record_limitation(
            connection,
            enrollment_id=f"{NATIVE_ROOT}/ledger",
            observed_at=WHEN,
            reason=reason,
            affected_count=1,
        )

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(ValueError, match="at least one object"):
            record_limitation(
                connection,
                enrollment_id=scoped.enrollment_id,
                observed_at=WHEN,
                reason=reason,
                affected_count=0,
            )
        transaction.commit()

    with pytest.raises(NaiveDatetimeError), engine.begin() as connection:
        record_limitation(
            connection,
            enrollment_id=scoped.enrollment_id,
            # Deliberately naive.
            observed_at=datetime(2026, 8, 1, 12, 0),
            reason=reason,
            affected_count=1,
        )

    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT count(*) FROM knowledge.coverage_limitations WHERE enrollment_id = :enr"),
            {"enr": scoped.enrollment_id},
        ).scalar_one()
    assert stored == 0, "a refused limitation was written"


@pytest.mark.database
def test_a_retry_reads_back_its_own_enrollments_row_and_not_a_neighbours(
    engine: Engine,
) -> None:
    """The `enrollment_id` filter on the fallback read after a conflicting insert.

    `record_outcome` inserts with `ON CONFLICT DO NOTHING` and, when that returns
    nothing, reads the row that must already exist. The unique constraint is per
    `(enrollment, version)`, so *two* enrollments may hold a row for one version —
    which is exactly what two grants over one object produce. Without the
    enrollment filter that read matches both, and `scalar_one_or_none` turns a
    lawful retry into a crash; if it matched one it would be worse, because the
    identifier handed back would be another grant's row.

    Nothing reached it: every fixture in the repository retries under the only
    enrollment that holds the version.
    """
    scoped = enrol(engine, key="retry-own", documents={"ledger": CORPUS["ledger"]})
    other = enrol_over(scoped, key="retry-own-other", names=("ledger",))
    media_type, body = CORPUS["ledger"]
    outcome = extract_text(
        source_id=scoped.source_id,
        source_object_id=scoped.object_ids["ledger"],
        observed_version_id=scoped.version_ids["ledger"],
        content_version_id=scoped.version_ids["ledger"],
        media_type=media_type,
        content=body,
        observed_at=WHEN,
    )
    with engine.begin() as connection:
        neighbours_row = record_outcome(
            connection, enrollment_id=other.enrollment_id, outcome=outcome
        )
    with engine.connect() as connection:
        own_row = connection.execute(
            text("SELECT extraction_id FROM knowledge.extractions WHERE enrollment_id = :enr"),
            {"enr": scoped.enrollment_id},
        ).scalar_one()
    assert own_row != neighbours_row

    with engine.begin() as connection:
        retried = record_outcome(connection, enrollment_id=scoped.enrollment_id, outcome=outcome)

    assert retried == own_row, "a retry returned a row written under another enrollment"


@pytest.mark.database
def test_a_retry_reads_back_the_version_it_offered_and_not_another_of_its_own(
    engine: Engine,
) -> None:
    """The `version_id` filter on the same fallback read, which nothing reached either.

    Its neighbour above holds the version constant and varies the enrollment.
    This holds the enrollment constant and varies the version, which is the other
    half of the unique constraint and the commoner state by far: `extractions`
    holds one row per observed version, so any object read twice has two rows
    under one grant. Without this filter the fallback read matches both of them
    and `scalar_one_or_none` raises, turning a lawful retry into a crash; had it
    matched one it would hand back the identifier of a different version's text.

    Nothing reached it because every fixture that retries has one version.
    """
    scoped = enrol(engine, key="retry-version", documents={"ledger": CORPUS["ledger"]})
    media_type, body = CORPUS["ledger"]
    first_offer = extract_text(
        source_id=scoped.source_id,
        source_object_id=scoped.object_ids["ledger"],
        observed_version_id=scoped.version_ids["ledger"],
        content_version_id=scoped.version_ids["ledger"],
        media_type=media_type,
        content=body,
        observed_at=WHEN,
    )
    with engine.begin() as connection:
        # The same object read again: same locator, different bytes, so one
        # object with two versions and two rows under one enrollment.
        again = observe_object(
            connection,
            source_id=scoped.source_id,
            native_locator=f"{NATIVE_ROOT}/retry-version/ledger",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-retry-version-ledger-second-pass",
            modified_at=WHEN,
            media_type=media_type,
            size_bytes=len(body),
        )
        assert again.source_object_id == scoped.object_ids["ledger"]
        assert again.version_id != scoped.version_ids["ledger"]
        second_row = record_outcome(
            connection,
            enrollment_id=scoped.enrollment_id,
            outcome=extract_text(
                source_id=scoped.source_id,
                source_object_id=again.source_object_id,
                observed_version_id=again.version_id,
                content_version_id=again.version_id,
                media_type=media_type,
                content=body,
                observed_at=WHEN,
            ),
        )
    with engine.connect() as connection:
        first_row = connection.execute(
            text(
                "SELECT extraction_id FROM knowledge.extractions "
                "WHERE enrollment_id = :enr AND version_id = :ver"
            ),
            {"enr": scoped.enrollment_id, "ver": scoped.version_ids["ledger"]},
        ).scalar_one()
    assert first_row != second_row

    with engine.begin() as connection:
        retried = record_outcome(
            connection, enrollment_id=scoped.enrollment_id, outcome=first_offer
        )

    assert retried == first_row, "a retry returned a row written for another version"


@pytest.mark.database
def test_the_schema_refuses_a_quarantined_outcome_filed_as_an_extraction(
    engine: Engine,
) -> None:
    """A quarantine filed in the wrong table is refused, not merely uncounted.

    This replaces `test_a_row_filed_in_extractions_as_quarantined_is_not_counted
    _as_processed`, and the replacement is the point rather than a consequence.
    That test planted a `quarantined` row in `extractions` by hand — the state
    `record_outcome` routes away from and no production path can produce — and
    then asserted the read side counted it nowhere. It was a *demonstration that
    a mis-filed row is not counted*. `9d4e7a3b1c62` narrowed
    `extraction_status_is_known` to the two statuses a writer can file, so the
    row can no longer be arranged at all, and the property is now an
    *impossibility* instead. The premise the old test needed is exactly what the
    schema now denies, which is why it could not be kept alongside.

    Planted with raw SQL for the same reason `plant_an_extraction` exists: the
    supported writer refuses this outcome before it reaches SQL, so only a
    hand-written statement reaches the server, which is where the claim is
    about. `record_outcome` is not the subject here and would prove nothing —
    it never emits this insert.

    The narrowing did not weaken the read side and this does not stop covering
    it. The `status` condition in `extracted_text_in_scope` is retained and now
    redundant; `extraction.py` says why, and the precedence exclusions that
    always did the real work are exercised by the sibling tests that plant
    `unsupported` rows and quarantine records.
    """
    scoped = enrol(
        engine,
        key="status-refused",
        documents={name: CORPUS[name] for name in ("ledger", "minutes")},
        extract=frozenset({"ledger"}),
    )

    with pytest.raises(IntegrityError) as refusal:
        plant_an_extraction(
            engine,
            enrollment_id=scoped.enrollment_id,
            source_object_id=scoped.object_ids["minutes"],
            version_id=scoped.version_ids["minutes"],
            status="quarantined",
        )

    # Named, so a row refused by some *other* constraint cannot pass as this
    # claim — which is how a refusal test quietly stops testing what it says.
    assert "extraction_status_is_known" in str(refusal.value)

    # And the refusal left nothing behind: the coverage beside it is the one an
    # enrollment with a single extracted object should report, with no trace of
    # the object whose row the server rejected.
    coverage = search(scoped, "revenue").disclosure.coverage

    assert coverage.processed == 1
    assert coverage.quarantined == 0
    assert coverage.unsupported == 0
    assert coverage.eligible == 2
    assert coverage.state is CoverageState.PARTIALLY_PROCESSED


@pytest.mark.database
def test_a_stated_snapshot_outranks_the_counts_it_was_taken_beside(engine: Engine) -> None:
    """`coverage_for`'s `snapshot` argument, which it accepted and could have dropped.

    Only the caller can compare the source against the instant the counts were
    taken at, so staleness is an input rather than something these rows can show.
    `CoverageCounts.state` puts it above every count for that reason: a complete
    count of a snapshot that no longer describes the source is not `processed`.

    Nothing reached it. `search_extractions` never passes the argument, so every
    read in this suite ran on the default, and replacing the parameter with that
    default changed no answer — the counts would have gone on reporting
    `processed` for a scope the caller had just said was stale.
    """
    scoped = enrol(engine, key="snapshot", documents={"ledger": CORPUS["ledger"]})
    with engine.connect() as connection:
        states = {
            snapshot: coverage_for(
                connection,
                scoped.enrollment_id,
                observed_at=WHEN,
                snapshot=snapshot,
            ).state()
            for snapshot in SnapshotState
        }

    assert states[SnapshotState.CURRENT] is CoverageState.PROCESSED
    assert states[SnapshotState.STALE] is CoverageState.STALE
    assert states[SnapshotState.SUPERSEDED] is CoverageState.SUPERSEDED


@pytest.mark.database
def test_coverage_counts_the_limitations_of_the_enrollment_it_was_asked_about(
    engine: Engine,
) -> None:
    """The `enrollment_id` filter on `coverage_for`'s limitation read.

    Unreachable through `search_extractions`, which passes the current time as
    its snapshot so that no stored limitation ever matches, and which is why
    deleting this left both tiers green. `coverage_for` is public and its
    snapshot argument is the whole point of it, so it is exercised directly:
    two enrollments, one instant, and each must report only its own omissions.
    """
    scoped = enrol(engine, key="limitation-scope", documents={"ledger": CORPUS["ledger"]})
    other = enrol_over(scoped, key="limitation-scope-other", names=("ledger",))
    reason = LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN
    with engine.begin() as connection:
        record_limitation(
            connection,
            enrollment_id=scoped.enrollment_id,
            observed_at=WHEN,
            reason=reason,
            affected_count=3,
        )
        record_limitation(
            connection,
            enrollment_id=other.enrollment_id,
            observed_at=WHEN,
            reason=reason,
            affected_count=7,
        )

    with engine.connect() as connection:
        counts = coverage_for(connection, scoped.enrollment_id, observed_at=WHEN)

    assert counts.disclosed_limitations == (f"{reason.value}:3",), (
        "another enrollment's omissions were counted as this one's"
    )


@pytest.mark.database
def test_a_refused_object_names_the_two_identifiers_its_caller_supplied(engine: Engine) -> None:
    """What `UnauthorizedObjectError` may carry, asserted rather than asserted to.

    Its docstring says the message is the two identifiers, no reason code and no
    content, and nothing checked it while `SearchInternalError`'s redaction was
    pinned twice over. The two errors make opposite decisions and both are
    deliberate: this one goes back to the writer that supplied both values and has
    to say which outcome of a batch was refused, so it names them.

    What it must not acquire is anything the caller did not hand it — a locator, a
    media type, the text of the outcome, or the reason the object is out of scope,
    which would say something about the enrollment's contents. `__cause__` and
    `__context__` are checked for the same reason they are on the search errors: a
    traceback rendered through a database error is how detail comes back after the
    message has been kept clean.
    """
    scoped = enrol(engine, key="refusal-message", documents={"ledger": CORPUS["ledger"]})
    beside = enrol_beside(
        scoped, key="refusal-message-beside", documents={"minutes": CORPUS["minutes"]}
    )

    with pytest.raises(UnauthorizedObjectError) as raised, engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=scoped.enrollment_id,
            source_object_id=beside.object_ids["minutes"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

    message = str(raised.value)
    assert scoped.enrollment_id in message
    assert beside.object_ids["minutes"] in message
    for withheld in (
        NATIVE_ROOT,
        "text/markdown",
        QuarantineReason.CONTAINMENT_UNPROVEN.value,
        CORPUS["minutes"][1].decode(),
        scoped.object_ids["ledger"],
        beside.version_ids["minutes"],
    ):
        assert withheld not in message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.database
def test_a_coverage_read_that_does_not_fit_its_denominator_is_a_typed_error(
    engine: Engine,
) -> None:
    """The floor under the coverage read, kept where `search_extractions` cannot reach it.

    `coverage_for` raises `ValueError` through `CoverageCounts` when the counts
    it assembles do not fit inside its own eligible total. No call
    `search_extractions` makes can produce that: every count is restricted to
    membership of `enrollment_objects` and the total is `count(*)` of those same
    rows, and this module declares neither `queued` nor `unavailable`. The
    remaining way to reach it is a broken store — outcome rows whose enumerated
    row has gone — and that is what is built here, by deleting the enumerated set
    out from under a stored extraction.

    What the failure must not be is a bare `ValueError`: outside section 10's
    taxonomy, with no envelope, reaching the caller as an unclassified crash. It
    is `SearchInternalError` — this system's fault, not retryable — and it carries
    the same empty message as every other error this module raises. The
    assertions on `__cause__` and `__context__` are the module's own rule that a
    typed error is raised outside the handler, because a traceback rendered
    through the original is how redacted detail comes back.

    The control is the same read before the deletion, in the same test: it
    returns counts, so what follows is about the broken state and not about the
    enrollment being unreadable.

    **What the broken store does, measured rather than assumed**, because it is
    not what it used to be: deleting the enumerated rows drops the denominator
    and every numerator together, since each count is restricted to membership
    of exactly those rows. The read reports a coherent zero rather than raising.
    That is the honest answer for a scope nothing describes, and it is asserted
    here so the deletion is a tested state rather than an untried one.

    The typed error is then exercised where a caller can still cause it — through
    `ensure_utc`, which raises a `ValueError` subclass, on a call that never
    reaches the connection. `queued` is the other route and it belongs to the
    port rather than to this module;
    `tests/schema/test_persistence_ports.py::test_a_broken_read_becomes_a_port_failure_and_carries_no_statement`
    holds that one.
    """
    scoped = enrol(engine, key="denominator", documents=CORPUS)

    with engine.connect() as connection:
        honest = _coverage(connection, scoped.enrollment_id, moment=WHEN)
    assert honest.eligible == len(CORPUS)
    assert honest.processed == len(CORPUS)

    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM knowledge.enrollment_objects WHERE enrollment_id = :enr"),
            {"enr": scoped.enrollment_id},
        )
    with engine.connect() as connection:
        emptied = _coverage(connection, scoped.enrollment_id, moment=WHEN)
    assert (emptied.eligible, emptied.processed) == (0, 0)
    assert emptied.state() is CoverageState.ELIGIBLE

    # Deliberately naive, which is what `coverage_for` refuses. The connection is
    # `None` to say that the refusal happens before anything is executed: a call
    # that reached the database would fail on the argument instead.
    with pytest.raises(SearchInternalError) as raised:
        _coverage(None, scoped.enrollment_id, moment=datetime(2026, 8, 1, 12, 0))  # type: ignore[arg-type]

    message = str(raised.value)
    assert message == "the search could not be completed"
    assert not any(character.isdigit() for character in message), "a count reached the message"
    for secret in (scoped.enrollment_id, NATIVE_ROOT, *scoped.object_ids.values()):
        assert secret not in message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


@pytest.mark.database
def test_two_rows_for_one_object_are_one_covered_object_in_every_count(engine: Engine) -> None:
    """`func.distinct`, on all three counts, which nothing exercised.

    `coverage_for` documents this outright — "an object quarantined twice is two
    rows and one uncovered object" — and every count is written
    `count(distinct source_object_id)` because of it. Deleting the `distinct`
    from any of the three left both tiers green: no fixture held two rows for one
    object in a scope small enough for the difference to show.

    Both tables record events, so all three states are reachable through the
    supported writers. A quarantine is documented non-idempotent, so two calls
    are two rows. `extractions` holds one row per observed version, so an object
    observed twice is two rows whichever status they carry — re-observing the
    same locator with a new fingerprint is a new version of the same object, not
    a second object, which `test_an_object_extracted_at_one_version_and_
    unsupported_at_another_is_counted_once` also relies on.

    Each scope holds exactly one object, so counting rows gives two against a
    denominator of one, `CoverageCounts` refuses it, and the read raises
    `SearchInternalError` rather than returning a number that is merely wrong.
    That is the round-1 crash class sitting behind an unpinned expression, which
    is why this asserts the count rather than the exception.
    """
    quarantined = enrol(engine, key="twice-quarantined", documents={"ledger": CORPUS["ledger"]})
    with engine.begin() as connection:
        for _ in range(2):
            quarantine_object(
                connection,
                enrollment_id=quarantined.enrollment_id,
                source_object_id=quarantined.object_ids["ledger"],
                version_id=None,
                reason=QuarantineReason.CONTAINMENT_UNPROVEN,
            )
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT count(*) FROM knowledge.quarantine_records WHERE enrollment_id = :enr"),
            {"enr": quarantined.enrollment_id},
        ).scalar_one()
    assert rows == 2, "the fixture holds one row; the count below would prove nothing"
    assert search(quarantined, "revenue").disclosure.coverage.quarantined == 1

    extracted = enrol(engine, key="twice-extracted", documents={"ledger": CORPUS["ledger"]})
    media_type, body = CORPUS["ledger"]
    with engine.begin() as connection:
        again = observe_object(
            connection,
            source_id=extracted.source_id,
            native_locator=f"{NATIVE_ROOT}/twice-extracted/ledger",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-twice-extracted-ledger-again",
            modified_at=WHEN,
            media_type=media_type,
            size_bytes=len(body),
        )
        assert again.source_object_id == extracted.object_ids["ledger"]
        record_outcome(
            connection,
            enrollment_id=extracted.enrollment_id,
            outcome=extract_text(
                source_id=extracted.source_id,
                source_object_id=again.source_object_id,
                observed_version_id=again.version_id,
                content_version_id=again.version_id,
                media_type=media_type,
                content=body,
                observed_at=WHEN,
            ),
        )
    assert search(extracted, "revenue").disclosure.coverage.processed == 1

    handbook = ("application/pdf", b"%PDF-1.7\nnot extracted here\n%%EOF\n")
    unsupported = enrol(engine, key="twice-unsupported", documents={"handbook": handbook})
    with engine.begin() as connection:
        again = observe_object(
            connection,
            source_id=unsupported.source_id,
            native_locator=f"{NATIVE_ROOT}/twice-unsupported/handbook",
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-twice-unsupported-handbook-again",
            modified_at=WHEN,
            media_type=handbook[0],
            size_bytes=len(handbook[1]),
        )
        assert again.source_object_id == unsupported.object_ids["handbook"]
        record_outcome(
            connection,
            enrollment_id=unsupported.enrollment_id,
            outcome=extract_text(
                source_id=unsupported.source_id,
                source_object_id=again.source_object_id,
                observed_version_id=again.version_id,
                content_version_id=again.version_id,
                media_type=handbook[0],
                content=handbook[1],
                observed_at=WHEN,
            ),
        )
    assert search(unsupported, "revenue").disclosure.coverage.unsupported == 1


@pytest.mark.database
def test_another_enrollments_outcomes_do_not_suppress_this_ones_coverage(engine: Engine) -> None:
    """The `enrollment_id` filter in both precedence subqueries.

    `quarantined_objects` and `unsupported_objects` are subtracted from the
    counts that rank below them, and after the boundary was removed from them
    last round the `enrollment_id` filter is the only condition either carries.
    Nothing exercised it: every fixture in this file that holds a quarantine and
    an extraction of one object holds them under one enrollment, where the filter
    cannot decide anything.

    Two enrollments over one source, both naming both objects, so every row is
    authorized for both and the boundary can account for nothing here. The second
    enrollment quarantines one object and records the other as unsupported.
    Without the filter each of those suppresses the first enrollment's own
    extraction of the same object, and its coverage falls from two processed
    objects to one — a grant reporting less coverage than it has because another
    grant stopped on the same file.
    """
    scoped = enrol(
        engine,
        key="precedence-scope",
        documents={name: CORPUS[name] for name in ("ledger", "minutes")},
    )
    other = enrol_over(scoped, key="precedence-other", names=("ledger", "minutes"))

    with engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=other.enrollment_id,
            source_object_id=other.object_ids["ledger"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
        record_outcome(
            connection,
            enrollment_id=other.enrollment_id,
            outcome=extract_text(
                source_id=other.source_id,
                source_object_id=other.object_ids["minutes"],
                observed_version_id=other.version_ids["minutes"],
                content_version_id=other.version_ids["minutes"],
                # The provider now reports a type this extractor does not read,
                # so the outcome is `unsupported` for the same version.
                media_type="application/pdf",
                content=b"%PDF-1.7\nnot extracted here\n%%EOF\n",
                observed_at=WHEN,
            ),
        )

    coverage = search(scoped, "revenue").disclosure.coverage
    assert coverage.processed == 2, "another enrollment's outcome suppressed this one's"
    assert coverage.quarantined == 0
    assert coverage.unsupported == 0
    assert coverage.state is CoverageState.PROCESSED

    # The control: the outcomes are real, and they are that enrollment's.
    neighbour = search(other, "revenue").disclosure.coverage
    assert neighbour.quarantined == 1
    assert neighbour.unsupported == 1
    assert neighbour.processed == 0


@pytest.mark.database
def test_a_search_returns_only_the_rows_its_own_enrollment_wrote(engine: Engine) -> None:
    """`match_statement`'s own `enrollment_id` filter, with nothing else varying.

    `test_a_search_never_reaches_outside_its_enrollment` builds its two
    enrollments over two sources, so `authorized_object` refuses the foreign rows
    on its own and the filter is never asked anything; deleting it leaves that
    test green.

    Here one source carries two enrollments and both name `minutes`. The row is
    written under the second, for an object the first authorizes, of a media type
    the first allows — so every condition of the boundary passes and the only
    thing that can keep the row out of the first enrollment's page is the filter
    that says which enrollment wrote it.
    """
    scoped = enrol(
        engine,
        key="own-rows",
        documents={name: CORPUS[name] for name in ("ledger", "minutes")},
        extract=frozenset({"ledger"}),
    )
    other = enrol_over(scoped, key="own-rows-other", names=("minutes",))
    with engine.begin() as connection:
        record_outcome(
            connection,
            enrollment_id=other.enrollment_id,
            outcome=extract_text(
                source_id=other.source_id,
                source_object_id=other.object_ids["minutes"],
                observed_version_id=other.version_ids["minutes"],
                content_version_id=other.version_ids["minutes"],
                media_type="text/markdown",
                content=INTRUDER_DOCUMENT.encode("utf-8"),
                observed_at=WHEN,
            ),
        )

    assert search(scoped, INTRUDER).matches == (), "a row another enrollment wrote was returned"
    assert search(scoped, "revenue").disclosure.coverage.processed == 1
    assert {match.source_object_id for match in search(scoped, "revenue").matches} == {
        scoped.object_ids["ledger"]
    }

    # The control: the row exists and is returned to the enrollment that wrote it.
    assert {match.source_object_id for match in search(other, INTRUDER).matches} == {
        other.object_ids["minutes"]
    }


@pytest.mark.database
def test_a_cancelled_read_is_unavailable_and_a_broken_statement_is_internal(
    engine: Engine,
) -> None:
    """`_execute`'s two handlers, which no test in this repository separated.

    `SearchUnavailableError` appeared in no test at all, so collapsing both
    handlers into one — everything `unavailable`, or everything internal — left
    both tiers green while the module's docstring claimed the separation matters:
    "telling a caller to retry a missing column would be a lie with a retry
    budget attached". Section 10 makes them different answers, one conditionally
    retryable and one not.

    Both failures are real rather than stubbed. A statement cancelled by
    `statement_timeout` is the retryable case and arrives as a DBAPI
    `OperationalError`; a statement naming a column that does not exist is the
    programming case and arrives as a `ProgrammingError`, which is a
    `SQLAlchemyError` and not an `OperationalError`. What must be true of both is
    asserted beside the type: the message carries no statement, no parameter and
    no driver text, and the original is on neither `__cause__` nor `__context__`,
    because a traceback rendered through a `DBAPIError` is how the bound query
    comes back after the message has been kept clean.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text("SET LOCAL statement_timeout = '1ms'"))
        with pytest.raises(SearchUnavailableError) as unavailable:
            _execute(connection, select(func.pg_sleep(3)), _every_row)
        transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(SearchInternalError) as internal:
            _execute(connection, select(literal_column("no_such_column")), _every_row)
        transaction.rollback()

    assert str(unavailable.value) == "the lexical index could not be read"
    assert str(internal.value) == "the search could not be completed"
    for raised in (unavailable, internal):
        message = str(raised.value)
        for withheld in ("SELECT", "pg_sleep", "no_such_column", "statement_timeout", "psycopg"):
            assert withheld not in message
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None


class DeletingConnection:
    """A `Connection` that deletes the conflicting row between the two statements.

    The one interleaving `conflicting_row` exists for, and the only way to reach
    it. `record_outcome` inserts with `ON CONFLICT DO NOTHING` and, when that
    returns nothing, reads the row that must already exist; between those two
    statements the row can be deleted, and `READ COMMITTED` then shows the second
    statement an empty result. Nothing a test can do from outside orders itself
    between two statements of one call, so this stands in the connection's place
    and does the deletion when the insert has just run.

    It delegates everything and detects the insert by type rather than by
    counting calls, so adding or removing a check before the insert does not
    silently move the deletion somewhere it proves nothing. `ON CONFLICT DO
    NOTHING` takes no lock on the row it conflicted with, which is why the
    deletion can commit on another connection while this one is still open.
    """

    def __init__(self, connection: Connection, engine: Engine, *, enrollment_id: str) -> None:
        self._connection = connection
        self._engine = engine
        self._enrollment_id = enrollment_id
        self._insert_has_run = False

    def execute(self, statement: Executable, *args: object, **kwargs: object) -> CursorResult[Any]:
        if self._insert_has_run:
            self._insert_has_run = False
            with self._engine.begin() as deleting:
                deleting.execute(
                    text("DELETE FROM knowledge.extractions WHERE enrollment_id = :enr"),
                    {"enr": self._enrollment_id},
                )
        if isinstance(statement, Insert):
            self._insert_has_run = True
        return self._connection.execute(statement, *args, **kwargs)  # type: ignore[arg-type]


@pytest.mark.database
def test_a_conflict_whose_row_has_vanished_is_reported_and_not_returned(engine: Engine) -> None:
    """`conflicting_row`, which `str(existing)` replaced without failing anything.

    The fallback in `record_outcome` reads the row its insert conflicted with.
    Where that row has been deleted in between, the read returns `None`, and the
    two candidate behaviours are indistinguishable everywhere except there:
    `conflicting_row` raises `IsolationLevelError`, and `str(existing)` returns
    the string `"None"` as if it were an extraction identifier — a `kn_…` that is
    not one, handed back to a caller as the row it just stored.

    `IsolationLevelError` names the defect and the table and no stored value,
    which is asserted rather than trusted: the message travels the same way an
    identifier would.
    """
    scoped = enrol(engine, key="vanished", documents={"ledger": CORPUS["ledger"]})
    media_type, body = CORPUS["ledger"]
    retry = extract_text(
        source_id=scoped.source_id,
        source_object_id=scoped.object_ids["ledger"],
        observed_version_id=scoped.version_ids["ledger"],
        content_version_id=scoped.version_ids["ledger"],
        media_type=media_type,
        content=body,
        observed_at=WHEN,
    )

    with pytest.raises(IsolationLevelError) as raised, engine.begin() as connection:
        record_outcome(
            DeletingConnection(connection, engine, enrollment_id=scoped.enrollment_id),  # type: ignore[arg-type]
            enrollment_id=scoped.enrollment_id,
            outcome=retry,
        )

    message = str(raised.value)
    assert "knowledge.extractions" in message
    for withheld in (scoped.enrollment_id, scoped.version_ids["ledger"], NATIVE_ROOT):
        assert withheld not in message


def test_the_coverage_read_validates_its_enrollment_before_anything_else() -> None:
    """`coverage_for`'s own `validate_identifier`, which its callee repeats.

    Deleting it leaves the same exception raised from `authorized_object` a few
    lines later, so nothing that only watches the error type can see the
    difference. What it does decide is order: the identifier is checked before
    the snapshot, before a predicate is built, and before the connection is
    touched at all. This passes `None` where a `Connection` goes to say that
    last part rather than describe it — a call that reached the database would
    fail on the argument rather than raise.

    The paired negative is what makes the ordering the claim: with a well-formed
    identifier the same call reaches the snapshot and fails there instead.
    """
    # Deliberately naive: it is what the paired case fails on.
    naive = datetime(2026, 8, 1, 12, 0)

    with pytest.raises(InvalidIdentifierError):
        coverage_for(None, f"{NATIVE_ROOT}/ledger", observed_at=naive)  # type: ignore[arg-type]

    with pytest.raises(NaiveDatetimeError):
        coverage_for(None, issue_identifier(IdKind.ENROLLMENT), observed_at=naive)  # type: ignore[arg-type]


@pytest.mark.database
def test_a_stored_source_identifier_that_is_not_one_never_reaches_the_envelope(
    engine: Engine,
) -> None:
    """The read-back check on `source_id`, which nothing could reach.

    `search_extractions` validates the `source_id` it read out of the enrollment
    row. Every source this suite builds goes through `register_source`, which
    issues a `src_…`, so no fixture can make that check decide anything and
    deleting it left both tiers green.

    A row written by hand can. The source below carries a locator where its
    identifier belongs, which is exactly the shape `INV-PKL-005` exists to keep
    out of a result, and that value would otherwise travel into
    `Disclosure.scope.source_ids`. Without the check it does not reach a caller
    either — `Scope` refuses it — but it reaches there as a validation error
    raised after the whole search ran, outside section 10's taxonomy, instead of
    as the identifier failure this layer names before it reads a row. Which error
    a caller gets, and when, is the difference being pinned.
    """
    forged_source = f"{NATIVE_ROOT}/forged"
    enrollment_id = issue_identifier(IdKind.ENROLLMENT)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.sources (source_id, provider_kind, label, "
                " classification, native_root, configured_at) "
                "VALUES (:sid, :kind, 'Forged', :classification, :root, :at)"
            ),
            {
                "sid": forged_source,
                "kind": SourceProviderKind.FIXTURE.value,
                "classification": Classification.SYNTHETIC_TEST.value,
                "root": f"{NATIVE_ROOT}/forged-root",
                "at": WHEN,
            },
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                " purpose, policy_version, idempotency_key, request_fingerprint, object_ids, "
                " depth, media_types, max_items, max_bytes, accepted_at) "
                "VALUES (:enr, :sid, :principal, :purpose, 'mcv-1', :key, 'forged', "
                " ARRAY[:obj], 0, ARRAY['text/markdown'], 100, 1000000, :at)"
            ),
            {
                "enr": enrollment_id,
                "sid": forged_source,
                "principal": issue_identifier(IdKind.PRINCIPAL),
                "purpose": Purpose.BOUNDED_ENROLLMENT.value,
                "key": f"forged-{secrets.token_hex(4)}",
                "obj": issue_identifier(IdKind.SOURCE_OBJECT),
                "at": WHEN,
            },
        )

    with pytest.raises(InvalidIdentifierError), engine.connect() as connection:
        search_extractions(
            connection, SearchRequest(enrollment_id=enrollment_id, query=SearchQuery("revenue"))
        )


@pytest.mark.database
def test_a_rank_is_bounded_below_one_however_often_a_term_repeats(engine: Engine) -> None:
    """`RANK_NORMALIZATION`, whose whole claim is a bound nothing measured.

    The constant is `ts_rank_cd` normalization 32, `rank / (rank + 1)`, and it is
    documented as bounding the score to `[0, 1)` because the score is bucketed
    into a category and a threshold against an unbounded number would drift with
    document length. Removing it changed no test: the categories are coarse and
    every fixture document is short.

    The document here repeats its term a hundred and twenty times, which is what
    makes the bound decidable. Measured on this server, the same document ranks
    `0.92` normalized and `12.0` unnormalized, so the assertion below separates
    them by an order of magnitude rather than by a rounding. The rank is read off
    `match_statement`'s own column, because `SearchMatch` carries the bucket and
    the bucket is what the bound exists to protect.
    """
    long_corpus = enrol(engine, key="rank", documents={"manual": ("text/markdown", LONG_DOCUMENT)})
    request = SearchRequest(enrollment_id=long_corpus.enrollment_id, query=SearchQuery("inventory"))
    with engine.connect() as connection:
        ranks = [float(row.rank) for row in connection.execute(match_statement(request, None))]

    assert ranks, "the fixture matched nothing; the bound below would prove nothing"
    assert all(0.0 <= rank < 1.0 for rank in ranks), f"a rank left the unit interval: {ranks}"
    assert max(ranks) > 0.5, "the fixture ranks too low to distinguish a bound from a small number"
    assert search(long_corpus, "inventory").matches[0].rank is RankCategory.STRONG


@pytest.mark.database
def test_a_search_discloses_its_own_enrollments_latest_omissions_and_no_others(
    engine: Engine,
) -> None:
    """All three conditions of `_limitation_tokens`, none of which anything reached.

    A limitation is a property of one enumeration pass rather than a running
    total, so the omissions a search discloses are its own enrollment's most
    recent pass's. Three separate conditions say that — the outer enrollment
    filter, the snapshot equality, and the enrollment filter inside the
    `max(observed_at)` subquery — and no fixture recorded limitations at two
    snapshots or under two enrollments, so all three were free.

    The fixture is built so that each condition alone decides an assertion. The
    searching enrollment reports at two snapshots; a neighbour reports at the
    same two and at a third, later one. Dropping the snapshot equality discloses
    the enrollment's earlier pass as well; dropping the outer filter discloses
    the neighbour's count at the same instant; dropping the inner one moves the
    "latest" to the neighbour's third snapshot, where this enrollment has
    nothing, and the disclosure goes silent about omissions that happened.
    """
    limited = enrol(engine, key="two-snapshots", documents=CORPUS)
    neighbour = enrol_over(limited, key="two-snapshots-neighbour", names=("ledger",))
    reason = LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN
    later = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)
    latest = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
    with engine.begin() as connection:
        for enrollment_id, moment, count in (
            (limited.enrollment_id, WHEN, 3),
            (limited.enrollment_id, later, 5),
            (neighbour.enrollment_id, WHEN, 7),
            (neighbour.enrollment_id, later, 9),
            (neighbour.enrollment_id, latest, 11),
        ):
            record_limitation(
                connection,
                enrollment_id=enrollment_id,
                observed_at=moment,
                reason=reason,
                affected_count=count,
            )

    limitations = search(limited, "revenue").disclosure.limitations
    code = reason.value

    assert f"{code}:5" in limitations, "the enrollment's latest omissions were not disclosed"
    assert f"{code}:3" not in limitations, "an earlier snapshot's omissions were disclosed too"
    assert f"{code}:9" not in limitations, "another enrollment's omissions were disclosed"
    assert f"{code}:7" not in limitations
    assert f"{code}:11" not in limitations


#: A document whose words are long enough that a thirty-word window of it cannot
#: fit inside `MAX_SNIPPET_CHARACTERS`. Nothing here is meant to be read; the
#: point is that the character bound, not the word bound, is what binds.
WIDE_WORD_DOCUMENT = ("The warehouse inventory record follows. " + ("z" * 40 + " ") * 60).encode(
    "utf-8"
)


@pytest.mark.database
def test_a_snippet_cut_to_its_character_bound_is_disclosed_as_cut(engine: Engine) -> None:
    """The `snippet_truncated` token, which nothing asserted.

    `bound_snippet` cuts a snippet at `MAX_SNIPPET_CHARACTERS` because a window
    into personal content must not have its size decided by the content. That the
    cut *happened* is a fact about the answer a caller is holding — the snippet
    it was shown is not the window it asked for — and section 8.5 forbids a limit
    that produces an unmarked complete-looking response. Deleting the disclosure
    left both tiers green: the existing snippet tests assert the bound and never
    the token, and every other fixture document has short words, so no snippet
    they produce is ever cut.
    """
    wide = enrol(
        engine, key="snippet-cut", documents={"manual": ("text/plain", WIDE_WORD_DOCUMENT)}
    )
    page = search(wide, "inventory")

    assert len(page.matches) == 1
    assert len(page.matches[0].snippet) <= MAX_SNIPPET_CHARACTERS
    assert "snippet_truncated" in page.disclosure.limitations

    # The paired negative, without which the token could be unconditional.
    short = enrol(engine, key="snippet-uncut", documents={"ledger": CORPUS["ledger"]})
    assert "snippet_truncated" not in search(short, "revenue").disclosure.limitations


@pytest.mark.database
def test_a_search_names_the_scope_it_ran_in(corpus: Corpus) -> None:
    page = search(corpus, "revenue")
    assert page.disclosure.scope.enrollment_ids == (corpus.enrollment_id,)
    assert page.disclosure.scope.source_ids == (corpus.source_id,)


@pytest.mark.database
def test_a_search_never_reaches_outside_its_enrollment(engine: Engine) -> None:
    """Two enrollments, the same term, and neither sees the other's documents."""
    first = enrol(engine, key="scope-a", documents={"ledger": CORPUS["ledger"]})
    second = enrol(engine, key="scope-b", documents={"minutes": CORPUS["minutes"]})

    from_first = {match.source_object_id for match in search(first, "revenue").matches}
    from_second = {match.source_object_id for match in search(second, "revenue").matches}

    assert from_first == {first.object_ids["ledger"]}
    assert from_second == {second.object_ids["minutes"]}
    assert not from_first & from_second


@pytest.mark.database
def test_an_unknown_enrollment_is_not_found_rather_than_an_empty_result(corpus: Corpus) -> None:
    with pytest.raises(UnknownEnrollmentError):
        search(corpus, "revenue", enrollment_id=issue_identifier(IdKind.ENROLLMENT))


@pytest.mark.database
def test_every_result_binds_the_version_its_text_came_from(corpus: Corpus) -> None:
    """Section 9.8's mandatory binding, and the freshness claim that rests on it."""
    page = search(corpus, "revenue")
    references = {
        (reference.source_object_id, reference.version_id)
        for reference in page.disclosure.source_references
    }
    assert references == {(match.source_object_id, match.version_id) for match in page.matches}
    with corpus.engine.connect() as connection:
        for match in page.matches:
            stored = connection.execute(
                text(
                    "SELECT version_id FROM knowledge.extractions "
                    "WHERE extraction_id = :knowledge_id"
                ),
                {"knowledge_id": match.knowledge_id},
            ).scalar_one()
            assert stored == match.version_id
    assert page.disclosure.freshness.state is FreshnessState.CURRENT_FOR_OBSERVED_VERSION


@pytest.mark.database
def test_a_result_carries_derived_trust_and_no_cloud_eligibility(corpus: Corpus) -> None:
    """`INV-PKL-003`: extracted text never carries source authority.

    The basis is asserted as well as the level. It is the machine-readable claim
    about *where* the trust comes from, and nothing checked it: any string at all
    survived there, including one naming a mechanism this search does not use.
    """
    page = search(corpus, "revenue")
    assert page.disclosure.trust.level is TrustLevel.SOURCE_BOUND_DERIVED
    assert page.disclosure.trust.basis == ("lexical_index",)
    assert page.disclosure.cloud_eligible is False
    assert page.disclosure.classification is Classification.SYNTHETIC_TEST


@pytest.mark.database
def test_a_snippet_is_a_bounded_window_that_carries_no_markup(engine: Engine) -> None:
    """Bounded, relevant, and free of the `<b>` tags `ts_headline` emits by default.

    The markup matters more than it looks. A snippet carrying tags is markup
    this system injected into whatever renders it, from content this system does
    not control.
    """
    long_corpus = enrol(engine, key="long", documents={"manual": ("text/markdown", LONG_DOCUMENT)})
    page = search(long_corpus, "inventory")

    assert len(page.matches) == 1
    snippet = page.matches[0].snippet
    assert 0 < len(snippet) <= MAX_SNIPPET_CHARACTERS
    assert len(snippet) < len(LONG_DOCUMENT.decode())
    assert "inventori" not in snippet, "the snippet is lexemes, not the document"
    assert "inventory" in snippet, "the snippet is not a window onto the match"
    for fragment in ("<b>", "</b>", "<", ">"):
        assert fragment not in snippet


@pytest.mark.database
def test_a_narrower_snippet_is_narrower(engine: Engine) -> None:
    """The paired control: the requested width is used and not ignored."""
    long_corpus = enrol(engine, key="width", documents={"manual": ("text/markdown", LONG_DOCUMENT)})
    wide = search(long_corpus, "inventory", snippet_words=60).matches[0].snippet
    narrow = search(long_corpus, "inventory", snippet_words=8).matches[0].snippet
    assert len(narrow) < len(wide)


#: Two matches with forty words of filler between them, so `MaxFragments` decides
#: whether the snippet is one window or two stitched together.
TWO_WINDOW_DOCUMENT = (
    "The inventory procedure opens the manual. "
    + "Filler words follow here and there. " * 40
    + "The inventory audit closes it."
).encode("utf-8")


@pytest.mark.database
def test_a_snippet_is_one_window_and_not_two_stitched_together(engine: Engine) -> None:
    """`MaxFragments=1`, which the module claims and nothing checked.

    Above one, `ts_headline` returns the best *n* windows joined by a separator,
    and a caller handed `... " is holding two disjoint quotations presented as one
    passage — text that reads as contiguous and is not. Every fixture document
    matched in one place, so raising the fragment count changed no snippet any
    test looked at.
    """
    two = enrol(
        engine, key="two-windows", documents={"manual": ("text/plain", TWO_WINDOW_DOCUMENT)}
    )
    snippet = search(two, "inventory", snippet_words=20).matches[0].snippet

    assert "inventory" in snippet
    assert "..." not in snippet, "the snippet stitched two windows together"


@pytest.mark.database
def test_the_narrowest_snippet_a_request_may_ask_for_is_answerable(engine: Engine) -> None:
    """`MIN_SNIPPET_WORDS`, which nothing ever asked for and which did not work.

    `ts_headline` requires `MinWords` strictly below `MaxWords` and raises
    `MinWords must be less than MaxWords` otherwise. `MaxWords` is the caller's
    `snippet_words` and `MinWords` was `min(snippet_words, 5)`, so at
    `snippet_words = MIN_SNIPPET_WORDS` the two were both 5 and every search
    carrying that width failed — as a `DataError`, which `_execute` classifies
    as `SearchInternalError`: "the search could not be completed", not
    retryable, for a request the contract says is valid.

    Nothing reached it because no test and no fixture had ever asked for the
    narrowest legal snippet; `SearchRequest` validates the bound and then
    nothing exercised it. Both ends of the range are asserted here so the
    boundary is covered from the side that broke.
    """
    narrow_corpus = enrol(
        engine, key="narrowest", documents={"manual": ("text/markdown", LONG_DOCUMENT)}
    )

    narrowest = search(narrow_corpus, "inventory", snippet_words=MIN_SNIPPET_WORDS)
    assert len(narrowest.matches) == 1
    assert narrowest.matches[0].snippet, "the narrowest legal request returned an empty window"

    widest = search(narrow_corpus, "inventory", snippet_words=MAX_SNIPPET_WORDS)
    assert len(widest.matches) == 1
    assert len(narrowest.matches[0].snippet) < len(widest.matches[0].snippet)


@pytest.mark.database
def test_a_naive_moment_is_refused_rather_than_mixed_into_the_envelope(corpus: Corpus) -> None:
    """`ensure_utc` on the clock a caller may supply, which nothing passed badly.

    `now` reaches the freshness stamp, the coverage snapshot, and the instant a
    cursor is issued at. A naive datetime carries no offset, so admitting one
    would put an unanchored instant in the disclosure beside timestamps the
    database stores with one, and would make cursor expiry compare two things
    that are not comparable. Every fixture passes an aware datetime or none at
    all, so dropping the call changed no answer any test looked at.
    """
    request = SearchRequest(enrollment_id=corpus.enrollment_id, query=SearchQuery("revenue"))
    with corpus.engine.connect() as connection, pytest.raises(NaiveDatetimeError):
        search_extractions(connection, request, now=datetime(2026, 8, 1, 12, 0))

    # The control: the same call with the offset present is answered.
    with corpus.engine.connect() as connection:
        assert search_extractions(connection, request, now=WHEN).matches


@pytest.mark.database
def test_a_full_page_is_reported_as_truncated_and_offers_a_cursor(corpus: Corpus) -> None:
    """Section 8.5: a limit never produces an unmarked complete-looking response."""
    page = search(corpus, "archive", page_size=1)
    assert len(page.matches) == 1
    assert page.disclosure.truncation.is_truncated is True
    assert page.disclosure.truncation.reason == "page_size_reached"
    assert page.disclosure.truncation.next_cursor
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_paging_through_a_result_set_neither_repeats_nor_loses_a_row(corpus: Corpus) -> None:
    """Keyset pagination is exact or it is silently wrong.

    The pages are reassembled and compared against the unpaged answer as a
    sequence as well as a set: comparing sets alone would accept pages that
    returned the right rows in the wrong order, which is the failure a rank tie
    produces.
    """
    whole = [match.knowledge_id for match in search(corpus, "archive", page_size=50).matches]
    assert len(whole) >= 3, "too few documents match; paging would not be exercised"

    collected: list[str] = []
    cursor: str | None = None
    for _ in range(len(whole) + 1):
        page = search(corpus, "archive", page_size=1, cursor=cursor)
        collected.extend(match.knowledge_id for match in page.matches)
        cursor = page.disclosure.truncation.next_cursor
        if cursor is None:
            break

    assert cursor is None, "paging did not terminate"
    assert collected == whole
    assert len(set(collected)) == len(collected)


@pytest.mark.database
def test_a_cursor_resumes_after_the_last_row_of_the_page_and_not_the_first(
    corpus: Corpus,
) -> None:
    """The row the cursor is built from, which no page size above one can show.

    Keyset resumption binds `(rank, knowledge_id)` of the *last* row of the page,
    because that is the boundary the next page starts below. Every paging test
    above uses `page_size=1`, where the first row of the page and its last row
    are the same row, so building the cursor from `page[0]` returns the identical
    answer and the whole suite stays green.

    At `page_size=2` they are different rows, and the wrong one re-serves the
    page's own second row at the top of the next page — pagination that repeats
    rather than pagination that fails, which is the silent kind.
    """
    whole = [match.knowledge_id for match in search(corpus, "archive", page_size=50).matches]
    assert len(whole) >= 4, "too few documents match; a two-row page would not be exercised"

    first = search(corpus, "archive", page_size=2)
    cursor = first.disclosure.truncation.next_cursor
    assert len(first.matches) == 2
    assert cursor

    second = search(corpus, "archive", page_size=2, cursor=cursor)
    collected = [match.knowledge_id for match in (*first.matches, *second.matches)]

    assert len(set(collected)) == len(collected), "a page repeated a row the previous page held"
    assert collected == whole[: len(collected)]


@pytest.mark.database
def test_a_cursor_from_a_different_query_is_refused(corpus: Corpus) -> None:
    """Scope-bound, proved against a real cursor rather than a constructed one."""
    first = search(corpus, "archive", page_size=1)
    cursor = first.disclosure.truncation.next_cursor
    assert cursor

    with pytest.raises(SearchCursorError):
        search(corpus, "revenue", page_size=1, cursor=cursor)
    with pytest.raises(SearchCursorError):
        search(corpus, "archive", page_size=2, cursor=cursor)

    # The control: the cursor still works for the request it was issued for.
    assert search(corpus, "archive", page_size=1, cursor=cursor).matches


@pytest.mark.database
def test_a_short_page_is_not_reported_as_truncated(corpus: Corpus) -> None:
    page = search(corpus, "revenue", page_size=50)
    assert page.disclosure.truncation.is_truncated is False
    assert page.disclosure.truncation.next_cursor is None


@pytest.mark.database
def test_a_page_holding_exactly_its_limit_is_not_truncated(corpus: Corpus) -> None:
    """The one row count at which `>` and `>=` disagree, which nothing reached.

    Truncation is `len(rows) > page_size` over a `LIMIT page_size + 1`, so the
    comparison can only decide at exactly `page_size` matches: below it every
    test above already passes, above it the extra row is there under either
    reading. `archive` is in all four documents and no test asked for four.

    What the wrong reading costs is section 8.5 in reverse. Rather than an
    unmarked complete response it is a marked incomplete one: a caller told the
    answer was cut when it was whole, and handed a cursor whose page is empty.
    """
    page = search(corpus, "archive", page_size=len(CORPUS))

    assert len(page.matches) == len(CORPUS), "the fixture no longer sits on the boundary"
    assert page.disclosure.truncation.is_truncated is False
    assert page.disclosure.truncation.reason is None
    assert page.disclosure.truncation.next_cursor is None
    assert page.disclosure.partial_result is False


@pytest.mark.database
def test_a_result_label_is_the_media_type_and_says_so(corpus: Corpus) -> None:
    """The MCV stores no title, so the label is derived and the derivation is disclosed.

    Without the limitation a caller would read "Markdown document" as a
    document's name. Deriving the label from the filename instead would be the
    locator leak every layer beneath this one exists to prevent.
    """
    page = search(corpus, "revenue")
    assert {match.label for match in page.matches} == {"Markdown document"}
    assert "result_label_is_media_type_only" in page.disclosure.limitations
    for match in page.matches:
        assert NATIVE_ROOT not in match.label
        assert "ledger" not in match.label


def test_only_an_indexed_text_search_configuration_can_be_written_into_the_sql() -> None:
    """The configuration is interpolated, so what may be interpolated is a closed set.

    `SEARCH_CONFIG` is written into the statement text rather than bound, for the
    index-matching reason the module records, and the safety of that has to be a
    property of the construction rather than of the value that happens to be
    there today. A name outside the set is refused before it can reach an
    f-string — including one that is a real PostgreSQL configuration, because an
    unindexed configuration is the silent sequential scan rather than a syntax
    error, and including one that is not a name at all.
    """
    assert SEARCH_CONFIG in INDEXED_CONFIGURATIONS
    assert str(_configuration(SEARCH_CONFIG).compile()) == f"'{SEARCH_CONFIG}'"

    for refused in ("french", "simple", "english' || (SELECT current_user) || '", "'; SELECT 1--"):
        with pytest.raises(ValueError, match="unsupported text-search configuration"):
            _configuration(refused)


def test_the_configuration_is_a_literal_and_only_the_query_is_a_parameter() -> None:
    """Which half of the predicate is planned as a constant, and which is data.

    Not a database test: it compiles the statement and reads the SQL, which is
    where this is decidable.

    A bound configuration compiles to `to_tsvector($1, text)`, and whether that
    matches an index on `to_tsvector('english', text)` then depends on the server
    folding the parameter into a constant while planning. Measured: it does under
    a custom plan and it does not under `plan_cache_mode = force_generic_plan`,
    where the plan drops to a sequential scan while returning the same rows. So
    the configuration has to be in the SQL text, and this asserts it is.

    The paired negative is the more important half. `SEARCH_CONFIG` is a module
    constant and may be written into the statement; the caller's query never may,
    and the assertions below say both — the configuration is not among the
    parameters, and the query text is nothing but a parameter.
    """
    request = SearchRequest(
        enrollment_id=issue_identifier(IdKind.ENROLLMENT), query=SearchQuery("revenue")
    )
    compiled = match_statement(request, None).compile(dialect=postgresql.dialect())
    sql = str(compiled)

    assert f"to_tsvector('{SEARCH_CONFIG}', knowledge.extractions.text)" in sql
    assert SEARCH_CONFIG not in compiled.params.values(), "the configuration is a bound parameter"
    assert "%(search_text)s" in sql, "the query text left the parameters"
    assert compiled.params["search_text"] == "revenue"
    assert "revenue" not in sql


def full_text_predicate(statement: Select[Any]) -> ColumnElement[Any]:
    """The `@@` clause of a statement `search` built, taken out of its own tree.

    Not rebuilt, and that is the entire point of this function. A test that
    writes the predicate out by hand tests the string it wrote: the previous
    version of the test below did exactly that, and planting
    `coalesce(text, '')` inside `_document_vector` — which really does drop the
    plan to a sequential scan — left the whole database tier green.

    The guard is part of the extraction. If the statement ever stops carrying
    exactly one `@@` predicate this fails loudly instead of quietly explaining
    something else.
    """
    where = statement.whereclause
    clauses = getattr(where, "clauses", (where,))
    found = [
        clause
        for clause in clauses
        if getattr(getattr(clause, "operator", None), "opstring", None) == "@@"
    ]
    assert len(found) == 1, f"expected one `@@` predicate in the statement, found {len(found)}"
    return found[0]


@pytest.mark.database
def test_the_search_predicate_uses_the_functional_index_and_not_a_sequential_scan(
    engine: Engine, corpus: Corpus
) -> None:
    """The index and the predicate must agree as expressions, not merely in intent.

    A functional GIN index is matched by expression tree. If the index says
    `to_tsvector('english', text)` and the predicate builds a different tree — a
    different text-search configuration, a `coalesce`, a cast the parser cannot
    erase such as `varchar(64)` — PostgreSQL silently plans a sequential scan.
    The rows come back correct either way, so no result-comparing test can tell
    the difference. Only the plan can. A cast that *is* erasable, `text` to
    `text` or to unbounded `varchar`, is folded away and keeps the index, which
    is why the rule is "the same expression" and not "no cast".

    Asserting the plan rather than a duration also keeps this deterministic:
    a timing threshold on a six-row fixture would be noise.

    The predicate comes out of `match_statement`, so what is explained is the
    expression the module sends and not one the test composed. What is explained
    is only that predicate, and the reason is measured rather than preferred: the
    full statement also filters on `enrollment_id`, which at fixture scale is far
    more selective than any term, so the planner chooses
    `extractions_by_enrollment` and applies the match as a filter. That plan is
    correct and says nothing either way about whether the two `to_tsvector`
    expressions agree. Isolating the predicate is what makes the plan answer that
    question, and a corpus large enough to make the whole statement prefer the
    GIN index would be a performance fixture, not this one.

    `enable_seqscan=off` is required and does not weaken the test. On a fixture
    this small the planner will not choose any index, so without it the test
    fails whether or not the expressions agree. It is also not a way to force a
    pass: measured on this server, an index on `to_tsvector('english', text)`
    against a predicate using `simple` still plans a sequential scan, because a
    functional index that does not match the expression cannot be used at any
    cost. The setting removes the size effect, not the correctness check.

    `paramstyle="named"` is what lets the compiled predicate be wrapped in
    `EXPLAIN` by `text()`: the placeholders stay placeholders and the values
    still travel as parameters, so nothing here interpolates a query.
    """
    request = SearchRequest(enrollment_id=corpus.enrollment_id, query=SearchQuery("revenue"))
    probe = select(extractions.c.extraction_id).where(
        full_text_predicate(match_statement(request, None))
    )
    compiled = probe.compile(
        dialect=postgresql.dialect(paramstyle="named"),
        compile_kwargs={"render_postcompile": True},
    )
    with engine.begin() as connection:
        connection.execute(text("ANALYZE knowledge.extractions"))
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0] for row in connection.execute(text(f"EXPLAIN {compiled}"), dict(compiled.params))
        )

    assert "extractions_full_text" in plan, f"the functional index was not chosen:\n{plan}"
    assert "Seq Scan" not in plan, f"the predicate fell back to a sequential scan:\n{plan}"
