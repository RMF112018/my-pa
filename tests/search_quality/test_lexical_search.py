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

import io
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.disclosure import CoverageState, FreshnessState
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.extraction.coverage import LimitationReason
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import extract_text
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.search.query import (
    MAX_SNIPPET_CHARACTERS,
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
from my_pa.infrastructure.persistence.enrollment import accept_enrollment
from my_pa.infrastructure.persistence.extraction import (
    quarantine_object,
    record_limitation,
    record_outcome,
)
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.search import (
    SearchPage,
    UnknownEnrollmentError,
    search_extractions,
)

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


def administer(maintenance: Engine, *statements: object) -> None:
    """Run statements that cannot be inside a transaction, such as CREATE DATABASE."""
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes.

    Module-scoped: creating a database and running eight revisions is most of
    this file's runtime, and every test below either only reads or writes into
    its own enrollment. `monkeypatch` is function-scoped and cannot be used
    here, so the one environment variable Alembic needs is set and restored by
    hand.
    """
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture(scope="module")
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


def enrol(
    engine: Engine,
    *,
    key: str,
    documents: dict[str, tuple[str, bytes]],
    extract: frozenset[str] | None = None,
) -> Corpus:
    """Build one source, one enrollment, and extract the named subset.

    `extract` is what makes the coverage tests possible: the objects outside it
    are enrolled and observed but never reach an outcome, which is exactly the
    state that must not be reported as "nothing matched".
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
                media_types=("text/markdown", "text/plain"),
                policy_version="mcv-1",
                idempotency_key=f"search-{key}-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
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
def test_a_root_selector_enrollment_cannot_claim_complete_coverage(engine: Engine) -> None:
    """The denominator nothing persists, disclosed rather than invented.

    An enrollment that named a root has an eligible total only enumeration
    knows. Search says so instead of dividing by the rows that happen to exist,
    which would report complete coverage of a scope nobody measured.
    """
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Rooted corpus",
            classification=Classification.SYNTHETIC_TEST,
            native_root=f"{NATIVE_ROOT}/rooted",
        )
        root = observe_object(
            connection,
            source_id=source.source_id,
            native_locator=f"{NATIVE_ROOT}/rooted",
            kind=ObjectKind.CONTAINER,
            fingerprint="fingerprint-rooted",
            modified_at=WHEN,
        )
        accepted = accept_enrollment(
            connection,
            EnrollmentRequest(
                source_id=source.source_id,
                principal_id=issue_identifier(IdKind.PRINCIPAL),
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(root_object_id=root.source_object_id, depth=1),
                media_types=("text/markdown",),
                policy_version="mcv-1",
                idempotency_key=f"search-rooted-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
        )
    rooted = Corpus(
        engine=engine,
        source_id=source.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        object_ids={},
    )
    page = search(rooted, "revenue")

    assert "eligible_total_not_persisted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


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
    """`INV-PKL-003`: extracted text never carries source authority."""
    page = search(corpus, "revenue")
    assert page.disclosure.trust.level is TrustLevel.SOURCE_BOUND_DERIVED
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


@pytest.mark.database
def test_the_search_predicate_uses_the_functional_index_and_not_a_sequential_scan(
    engine: Engine, corpus: Corpus
) -> None:
    """The index and the predicate must agree as expressions, not merely in intent.

    A functional GIN index is matched by expression tree. If the index says
    `to_tsvector('english', text)` and the predicate says anything else — a
    different text-search configuration, a cast, a coalesce — PostgreSQL silently
    plans a sequential scan. The rows come back correct either way, so no
    result-comparing test can tell the difference. Only the plan can.

    Asserting the plan rather than a duration also keeps this deterministic:
    a timing threshold on a six-row fixture would be noise.

    `enable_seqscan=off` is required and does not weaken the test. On a fixture
    this small the planner will not choose any index, so without it the test
    fails whether or not the expressions agree. It is also not a way to force a
    pass: measured on this server, an index on `to_tsvector('english', text)`
    against a predicate using `simple` still plans a sequential scan, because a
    functional index that does not match the expression cannot be used at any
    cost. The setting removes the size effect, not the correctness check.
    """
    with engine.begin() as connection:
        connection.execute(text("ANALYZE knowledge.extractions"))
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            row[0]
            for row in connection.execute(
                text(
                    "EXPLAIN SELECT extraction_id FROM knowledge.extractions "
                    "WHERE to_tsvector('english', text) "
                    "@@ websearch_to_tsquery('english', :q)"
                ),
                {"q": "revenue"},
            )
        )

    assert "extractions_full_text" in plan, f"the functional index was not chosen:\n{plan}"
    assert "Seq Scan" not in plan, f"the predicate fell back to a sequential scan:\n{plan}"
