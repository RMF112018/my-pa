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
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import ColumnElement, Engine, Select, select, text
from sqlalchemy.dialects import postgresql
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
    UnauthorizedObjectError,
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
    UnknownEnrollmentError,
    _claims_the_whole_scope,
    _configuration,
    _coverage,
    match_statement,
    search_extractions,
)
from my_pa.infrastructure.persistence.tables import extractions, source_objects

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

    Nothing is extracted here, so the counts are all zero and the branch that
    replaces the eligible total is reached with nothing in it. The test below
    covers the case that has outcomes in it, which is where the claim could
    actually have been made.
    """
    rooted = enrol_under_a_root(engine, key="rooted", documents={})
    page = search(rooted, "revenue")

    assert "eligible_total_not_persisted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_a_root_selector_enrollment_with_outcomes_still_cannot_report_processed(
    engine: Engine,
) -> None:
    """The same rule where it is actually reachable: every outcome a success.

    With an unknown eligible total the reported total is what was accounted for,
    so a scope whose every outcome is an extraction divides out to all of it and
    `state` was `processed` — the machine-readable claim that the whole eligible
    scope was covered, over a denominator taken from the numerator and never
    measured. A caller reading the state rather than the limitation token was
    told something false.

    `partially_processed` is the honest reading and is what must be reported:
    objects were processed, and how many more there are is not known. The counts
    are deliberately left alone; the fix is to stop making the claim, not to
    invent a bigger denominator to hide it behind.
    """
    rooted = enrol_under_a_root(
        engine, key="rooted-extracted", documents={"ledger": CORPUS["ledger"]}
    )
    page = search(rooted, "revenue")

    assert len(page.matches) == 1
    assert page.disclosure.coverage.processed == 1
    assert page.disclosure.coverage.eligible == 1
    assert page.disclosure.coverage.state is not CoverageState.PROCESSED
    assert page.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "eligible_total_not_persisted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_a_root_selector_enrollment_with_only_quarantines_cannot_report_quarantined(
    engine: Engine,
) -> None:
    """The same false claim as the test above, in its more dangerous form.

    Nothing was extracted and one object was quarantined, so the derived total is
    that one object and `quarantined == eligible` — "every eligible object in
    this scope was quarantined", about a scope nobody enumerated. It is the
    identical divide-the-numerator-by-itself construction as `processed`, and a
    clamp that covered only `processed` let this one through. It is worse than
    the `processed` case rather than milder: a caller acting on "all of it was
    quarantined" is likelier to act destructively.
    """
    rooted = enrol_under_a_root(
        engine,
        key="rooted-quarantined",
        documents={"charter": CORPUS["charter"]},
        extract=frozenset(),
    )
    with rooted.engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=rooted.enrollment_id,
            source_object_id=rooted.object_ids["charter"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )
    page = search(rooted, "quarterly")

    assert page.disclosure.coverage.quarantined == 1
    assert page.disclosure.coverage.eligible == 1
    assert page.disclosure.coverage.state is not CoverageState.QUARANTINED
    assert page.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "eligible_total_not_persisted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


@pytest.mark.database
def test_a_root_selector_enrollment_with_only_unsupported_media_cannot_report_unsupported(
    engine: Engine,
) -> None:
    """The third reachable form of the same claim.

    One object, its media type not text this system reads, so the derived total
    is one and `unsupported == eligible`. "Nothing in this scope could be
    extracted" is a statement about a whole scope, and the scope was never
    enumerated.
    """
    rooted = enrol_under_a_root(
        engine,
        key="rooted-unsupported",
        documents={"handbook": ("application/pdf", b"%PDF-1.7\nnot extracted here\n%%EOF\n")},
    )
    page = search(rooted, "revenue")

    assert page.matches == ()
    assert page.disclosure.coverage.unsupported == 1
    assert page.disclosure.coverage.eligible == 1
    assert page.disclosure.coverage.state is not CoverageState.UNSUPPORTED
    assert page.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "eligible_total_not_persisted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


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

    With the total stated as unmeasured there is no ceiling to violate. The
    scope is still one nobody enumerated, so everything the tests above require
    still holds.
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
    assert page.disclosure.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert "eligible_total_not_persisted" in page.disclosure.limitations
    assert page.disclosure.partial_result is True


def plant_an_extraction(
    engine: Engine, *, enrollment_id: str, source_object_id: str, version_id: str, body: str
) -> None:
    """Store an extraction row by raw SQL, bypassing `record_outcome` entirely.

    Deliberately not going through the writer, because these tests are about the
    *read* side of the authorization boundary and the writer now refuses exactly
    the rows they need. A read that only held because the writer refused would be
    no boundary at all: rows already stored, written by hand, or written before
    the writer was checked would still be counted and returned. Raw SQL is how
    that state is reached now that the supported path cannot reach it.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.extractions (extraction_id, enrollment_id, "
                " source_object_id, version_id, status, media_type, extractor, "
                " extractor_version, text, observed_at, processed_at) "
                "VALUES (:kn, :enr, :obj, :ver, 'extracted', 'text/markdown', "
                " 'my_pa.text', '1', :body, :at, :at)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrollment_id,
                "obj": source_object_id,
                "ver": version_id,
                "body": body,
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
    """The condition `object_ids` membership alone does not supply.

    Nothing validates that a named object belongs to the enrollment's source:
    `accept_enrollment` writes the array as given, and an array column cannot
    carry a foreign key to a row in another table's source. So an enrollment can
    name an object of a different source, membership passes, and without the
    source condition that object's extracted text would be returned under a
    disclosure whose `scope.source_ids` names only the enrollment's source.

    That is also what makes `SearchMatch.source_id` a real question rather than a
    style one: taken from the enrollment row it would have asserted the wrong
    source for this object, and taken from the object it is right. Both
    conditions are enforced, so the two are now equal for every row a search can
    return — proved by `test_every_match_names_the_source_its_object_belongs_to`
    rather than assumed here.
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
    assert page.disclosure.coverage.eligible == 2
    assert page.disclosure.coverage.processed == 1
    assert page.disclosure.partial_result is True
    assert search(crossed, INTRUDER).matches == ()


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
    """What the write side *can* check for the selector that stores no object set.

    An enrollment naming a root has no persisted list of authorized objects, so
    membership cannot be checked and nothing here pretends otherwise. Its
    `source_id` is persisted, though, and a root is an object of that source that
    depth walks within — no object of another source is reachable under it. That
    much is a stored fact rather than an invented one, and it is enforced.
    """
    rooted = enrol_under_a_root(engine, key="rooted-write-side", documents={})
    neighbour = enrol(
        engine, key="rooted-write-side-neighbour", documents={"ledger": CORPUS["ledger"]}
    )

    with pytest.raises(UnauthorizedObjectError), engine.begin() as connection:
        quarantine_object(
            connection,
            enrollment_id=rooted.enrollment_id,
            source_object_id=neighbour.object_ids["ledger"],
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )


@pytest.mark.database
def test_a_coverage_read_that_does_not_fit_its_denominator_is_a_typed_error(
    engine: Engine,
) -> None:
    """The floor under the coverage read, kept where `search_extractions` can no longer reach it.

    `coverage_for` raises `ValueError` when the counts do not fit inside a
    denominator the caller supplied. With the boundary enforced on both sides no
    call `search_extractions` makes can produce that any more — the counts are
    restricted to the objects `object_ids` names, and there cannot be more of
    those than the array holds. `coverage_for` is public and the guard is about
    any caller, so it is exercised directly rather than deleted along with the
    route that used to reach it.

    What it must not be is a bare `ValueError`: outside section 10's taxonomy,
    with no envelope, reaching the caller as an unclassified crash. It is
    `SearchInternalError` — this system's fault, not retryable — and it carries
    the same empty message as every other error this module raises. The
    assertions on `__cause__` and `__context__` are the module's own rule that a
    typed error is raised outside the handler, because a traceback rendered
    through the original is how redacted detail comes back.
    """
    scoped = enrol(engine, key="denominator", documents=CORPUS)

    with pytest.raises(SearchInternalError) as raised, engine.connect() as connection:
        _coverage(connection, scoped.enrollment_id, moment=WHEN, eligible=0)

    message = str(raised.value)
    assert message == "the search could not be completed"
    assert not any(character.isdigit() for character in message), "a count reached the message"
    for secret in (scoped.enrollment_id, NATIVE_ROOT, *scoped.object_ids.values()):
        assert secret not in message
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


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


def test_every_coverage_state_that_claims_a_whole_scope_is_classified_as_one() -> None:
    """The clamp's membership, stated over every state rather than the reachable ones.

    Not a database test, and that is the point of having it: `unavailable` cannot
    be produced through `search_extractions` today, because search passes no
    `unavailable` count. "Currently unreachable" is how the first clamp came to
    cover `processed` alone while `quarantined` and `unsupported` walked past it,
    so the state is classified here and will be clamped the moment a caller can
    reach it.

    The exhaustiveness assertion is a second lock on the same door. The partition
    in `search` is written with `assert_never`, so an eleventh `CoverageState`
    that nobody classified is a `mypy` error rather than a state that silently
    escapes the clamp; this asserts the same thing at runtime, where a suite that
    does not type-check its tests can still see it.
    """
    whole_scope = {
        CoverageState.PROCESSED,
        CoverageState.QUARANTINED,
        CoverageState.UNSUPPORTED,
        CoverageState.UNAVAILABLE,
    }
    partial = {
        CoverageState.NOT_ENROLLED,
        CoverageState.ELIGIBLE,
        CoverageState.QUEUED,
        CoverageState.PARTIALLY_PROCESSED,
        CoverageState.STALE,
        CoverageState.SUPERSEDED,
    }
    assert whole_scope | partial == set(CoverageState), "a coverage state is classified nowhere"
    assert not whole_scope & partial
    for state in whole_scope:
        assert _claims_the_whole_scope(state) is True
    for state in partial:
        assert _claims_the_whole_scope(state) is False


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
    full statement also filters on `enrollment_id` and `status`, which at fixture
    scale is far more selective than any term, so the planner chooses
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
