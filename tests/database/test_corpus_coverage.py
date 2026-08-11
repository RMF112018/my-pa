"""A corpus answer is bounded by one Principal, and says what it could not reach.

WP-23. Two claims, and they fail for different reasons.

**Isolation, at the repository/query boundary.** Two Principals are built over
disjoint sources, both seeded with enrollments, enumerated objects, extractions,
a quarantine and outstanding work, and each one's corpus answer is asserted to
count its own rows and none of the other's — by total, by enrollment identifier,
and by the unknown-territory counts, which are the numbers a leak would show up
in first because they are derived from `source_objects` rather than from
`enrollments`. **The level is stated exactly**: this is the repository/query
boundary, `corpus_coverage` against a real PostgreSQL at head. It is *not* an
end-to-end claim. The D-15 pin makes a second authenticated Principal
unconstructible through the transport, so an end-to-end two-Principal request
cannot be written here and is not claimed.

**Unknown territory is measured, not assumed.** An object nobody enrolled, an
enrolled object with no outcome yet, and a container the enumeration was never
going to record are three different things, and the counts have to tell them
apart: the first two are gaps a caller can act on and the third is structure, so
counting the container would report a gap nothing could ever close and would put
`processed` permanently out of reach.

The database is disposable, created and dropped by its fixture, and never the
configured one. Every value is synthetic: no such path exists and none is opened.
"""

from __future__ import annotations

import io
import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import extract_text
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.extraction import (
    coverage_for,
    quarantine_object,
    record_outcome,
)
from my_pa.infrastructure.persistence.knowledge import (
    corpus_coverage,
    pending_objects,
    scope_beyond_enrollment,
)
from my_pa.infrastructure.persistence.registry import observe_object, register_source

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name, so a run interrupted before teardown is cleaned up by the next.
DISPOSABLE_DATABASE = "my_pa_corpus_coverage_test"

WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/corpus-alpha"

READABLE = ("text/markdown", "text/plain")


def administer(maintenance: Engine, *statements: object) -> None:
    """Run statements that cannot be inside a transaction, such as CREATE DATABASE."""
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
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


class Holding:
    """One Principal, one source, and whatever of it that Principal enrolled.

    The source always holds four readable objects and one container. Which of
    the four the enrollment enumerates is the parameter, because the difference
    between "enrolled" and "observed but outside every grant" is the whole
    subject of this module.
    """

    def __init__(self, engine: Engine, key: str, *, enrolled: tuple[str, ...]) -> None:
        self.engine = engine
        self.key = key
        self.principal_id = issue_identifier(IdKind.PRINCIPAL)
        with engine.begin() as connection:
            source = register_source(
                connection,
                provider_kind=SourceProviderKind.FIXTURE,
                label=f"Synthetic corpus {key}",
                classification=Classification.SYNTHETIC_TEST,
                native_root=f"{NATIVE_ROOT}/{key}",
            )
            self.source_id = source.source_id
            self.objects = {
                name: observe_object(
                    connection,
                    source_id=source.source_id,
                    native_locator=f"{NATIVE_ROOT}/{key}/{name}",
                    kind=ObjectKind.FILE,
                    fingerprint=f"fingerprint-{key}-{name}",
                    modified_at=WHEN,
                    media_type="text/markdown",
                    size_bytes=32,
                )
                for name in ("alpha", "beta", "gamma", "delta")
            }
            # A container. The enumeration descends into one and never records
            # it, so it must not be counted as territory outside the grant.
            self.container = observe_object(
                connection,
                source_id=source.source_id,
                native_locator=f"{NATIVE_ROOT}/{key}/folder",
                kind=ObjectKind.CONTAINER,
                fingerprint=f"fingerprint-{key}-folder",
                modified_at=WHEN,
                media_type=None,
                size_bytes=None,
            )
            self.enrollment = self._enroll(connection, key, enrolled)

    def _enroll(self, connection: object, key: str, names: tuple[str, ...]) -> object:
        enrollment = accept_enrollment(
            connection,  # type: ignore[arg-type]
            EnrollmentRequest(
                source_id=self.source_id,
                principal_id=self.principal_id,
                purpose=Purpose.BOUNDED_ENROLLMENT,
                scope=EnrollmentScope(object_ids=tuple(self.object_id(n) for n in names)),
                media_types=READABLE,
                policy_version="mcv-1",
                idempotency_key=f"corpus-{key}-{secrets.token_hex(4)}",
                max_items=100,
                max_bytes=1_000_000,
            ),
        ).enrollment
        record_scope(
            connection,  # type: ignore[arg-type]
            enrollment.enrollment_id,
            [self.object_id(name) for name in names],
        )
        return enrollment

    def enroll_again(self, names: tuple[str, ...]) -> object:
        """A second enrollment of this Principal over the same source."""
        with self.engine.begin() as connection:
            return self._enroll(connection, f"{self.key}-second", names)

    @property
    def enrollment_id(self) -> str:
        return self.enrollment.enrollment_id  # type: ignore[attr-defined]

    def object_id(self, name: str) -> str:
        return self.objects[name].source_object_id

    def extract(self, name: str, *, enrollment_id: str | None = None) -> None:
        with self.engine.begin() as connection:
            record_outcome(
                connection,
                enrollment_id=enrollment_id or self.enrollment_id,
                outcome=extract_text(
                    source_id=self.source_id,
                    source_object_id=self.object_id(name),
                    observed_version_id=self.objects[name].version_id,
                    content_version_id=self.objects[name].version_id,
                    media_type="text/markdown",
                    content=b"# the alpha report\n\nsubject-alpha met person-alpha.\n",
                    observed_at=WHEN,
                ),
            )

    def quarantine(self, name: str) -> None:
        with self.engine.begin() as connection:
            quarantine_object(
                connection,
                enrollment_id=self.enrollment_id,
                source_object_id=self.object_id(name),
                version_id=self.objects[name].version_id,
                reason=QuarantineReason.CONTAINMENT_UNPROVEN,
            )

    def corpus(self) -> object:
        with self.engine.begin() as connection:
            return corpus_coverage(connection, self.principal_id, observed_at=WHEN)


def test_a_corpus_answer_counts_this_principals_rows_and_none_of_another_principals(
    engine: Engine,
) -> None:
    """The two-Principal negative, at the repository/query boundary.

    Both Principals are seeded to the same shape over disjoint sources, so a
    predicate that had been dropped would not merely change one number: it would
    double every one of them, name the other Principal's enrollment in the scope,
    and count the other source's objects as this Principal's unknown territory.
    Each of those is asserted separately, because a single total is a single
    thing to get accidentally right.

    **This is not an end-to-end claim.** The D-15 pin means a second
    authenticated Principal cannot be constructed through the transport, so no
    request-level two-Principal test is available to write and none is implied
    here.
    """
    alpha = Holding(engine, "alpha", enrolled=("alpha", "beta", "gamma"))
    beta = Holding(engine, "beta", enrolled=("alpha", "beta"))
    alpha.extract("alpha")
    alpha.quarantine("beta")
    beta.extract("alpha")
    beta.extract("beta")

    mine = alpha.corpus()
    theirs = beta.corpus()

    assert [counts.enrollment_id for counts in mine.enrollments] == [alpha.enrollment_id]
    assert [counts.enrollment_id for counts in theirs.enrollments] == [beta.enrollment_id]
    assert alpha.enrollment_id not in {c.enrollment_id for c in theirs.enrollments}

    # Alpha holds one source with four readable objects; three are enumerated,
    # one is not, and of the three one is extracted, one quarantined and one
    # still owed an outcome.
    assert (mine.held_sources, mine.objects_in_held_sources) == (1, 4)
    assert mine.objects_outside_every_enrollment == 1
    assert mine.objects_awaiting_an_outcome == 1
    assert (mine.stated_eligible, mine.stated_processed, mine.stated_quarantined) == (3, 1, 1)

    # Beta holds one source with four readable objects, two enumerated and both
    # extracted. Different numbers, from the same shape, which is what makes the
    # comparison a measurement rather than two copies of one answer.
    assert (theirs.held_sources, theirs.objects_in_held_sources) == (1, 4)
    assert theirs.objects_outside_every_enrollment == 2
    assert theirs.objects_awaiting_an_outcome == 0
    assert (theirs.stated_eligible, theirs.stated_processed, theirs.stated_quarantined) == (2, 2, 0)

    # And the sum of the two is not what either of them says, so a corpus read
    # that had lost its partition would fail every assertion above rather than
    # coincidentally satisfying one.
    assert mine.stated_eligible + theirs.stated_eligible == 5
    assert mine.objects_in_held_sources + theirs.objects_in_held_sources == 8


def test_a_principal_holding_no_enrollment_is_not_enrolled_rather_than_empty(
    engine: Engine,
) -> None:
    """`not_enrolled` with nothing measured beside it, which is the honest answer.

    A Principal with no grant is not a Principal whose corpus is empty: nothing
    was searched because there was no scope to search inside, and section 12
    forbids collapsing the one into the other.
    """
    with engine.begin() as connection:
        answer = corpus_coverage(connection, issue_identifier(IdKind.PRINCIPAL), observed_at=WHEN)
    assert answer.state() is CoverageState.NOT_ENROLLED
    assert answer.enrollment_count == 0
    assert answer.held_sources == 0
    assert answer.objects_in_held_sources == 0
    assert answer.disclosed_limitations == ()


def test_a_container_is_never_counted_as_territory_outside_the_enrollments(
    engine: Engine,
) -> None:
    """The whole source is enrolled, so the only object left over is the container.

    Counting it would make `processed` unreachable for any source that has a
    folder in it — a permanent gap nothing could close — which is why the count
    subtracts exactly the kinds `ENUMERABLE_KINDS` excludes and no others.
    """
    whole = Holding(engine, "container", enrolled=("alpha", "beta", "gamma", "delta"))
    for name in ("alpha", "beta", "gamma", "delta"):
        whole.extract(name)

    answer = whole.corpus()
    assert answer.objects_in_held_sources == 4, "the container is not in the denominator either"
    assert answer.objects_outside_every_enrollment == 0
    assert answer.objects_awaiting_an_outcome == 0
    assert answer.state() is CoverageState.PROCESSED
    assert answer.disclosed_limitations == ()


@pytest.mark.parametrize(
    ("leave_unenrolled", "leave_pending"),
    [(True, False), (False, True), (True, True)],
    ids=["an object outside every enrollment", "work awaiting an outcome", "both"],
)
def test_no_arrangement_short_of_everything_reports_a_processed_corpus(
    engine: Engine, leave_unenrolled: bool, leave_pending: bool
) -> None:
    """Every way of being incomplete, against the store rather than against a fixture.

    The unit test over `CorpusCoverage` proves the type refuses to report a
    complete corpus; this proves the *reads* produce the counts that make it
    refuse, which is a different claim and the one a leak or an off-by-one in a
    subquery would break.
    """
    names = ("alpha", "beta", "gamma") if leave_unenrolled else ("alpha", "beta", "gamma", "delta")
    holding = Holding(
        engine,
        f"partial-{int(leave_unenrolled)}{int(leave_pending)}",
        enrolled=names,
    )
    extracted = names[:-1] if leave_pending else names
    for name in extracted:
        holding.extract(name)

    answer = holding.corpus()
    assert answer.state() is CoverageState.PARTIALLY_PROCESSED
    assert (answer.objects_outside_every_enrollment > 0) is leave_unenrolled
    assert (answer.objects_awaiting_an_outcome > 0) is leave_pending
    tokens = answer.disclosed_limitations
    assert ("objects_outside_every_enrollment:1" in tokens) is leave_unenrolled
    assert ("objects_awaiting_an_outcome:1" in tokens) is leave_pending
    # A limitation token is a reason and a count, and nothing that could name a
    # thing. The identifiers are checked against the tokens directly, because
    # the type having no field for one is a different claim from the read never
    # putting one there.
    rendered = " ".join(tokens)
    for object_id in (holding.object_id(name) for name in ("alpha", "beta", "gamma", "delta")):
        assert object_id not in rendered
    assert holding.source_id not in rendered
    assert holding.enrollment_id not in rendered


def test_the_members_are_the_same_values_the_per_enrollment_read_reports(
    engine: Engine,
) -> None:
    """The anti-divergence claim: this composes `coverage_for`, it does not restate it.

    A corpus-wide aggregate query over the outcome tables would be a second
    definition of processed, quarantined and unsupported, and the two would drift
    exactly as the count and the page in `persistence.search` once did. Asserted
    by equality against the very function every other surface calls.
    """
    holding = Holding(engine, "composition", enrolled=("alpha", "beta", "gamma"))
    holding.extract("alpha")
    holding.quarantine("beta")

    with engine.begin() as connection:
        stated = coverage_for(connection, holding.enrollment_id, observed_at=WHEN)
        answer = corpus_coverage(connection, holding.principal_id, observed_at=WHEN)
    assert answer.enrollments == (stated,)
    assert answer.stated_processed == stated.processed
    assert answer.stated_quarantined == stated.quarantined


def test_pending_work_is_the_same_predicate_the_executors_work_list_uses(
    engine: Engine,
) -> None:
    """`pending_objects` and the corpus count are one definition with two callers.

    They answer different shapes — a list for one enrollment, a count across
    every enrollment a Principal holds — and they must never disagree about which
    objects are outstanding, because a work list and a coverage report that
    disagree are the broken store section 12 names.
    """
    holding = Holding(engine, "pending", enrolled=("alpha", "beta", "gamma"))
    holding.extract("alpha")
    holding.quarantine("beta")

    with engine.begin() as connection:
        outstanding = pending_objects(connection, holding.enrollment_id)
        answer = corpus_coverage(connection, holding.principal_id, observed_at=WHEN)
    assert outstanding == (holding.object_id("gamma"),)
    assert answer.objects_awaiting_an_outcome == len(outstanding)


def test_two_enrollments_over_one_source_are_stated_separately_and_only_summed(
    engine: Engine,
) -> None:
    """The composition's honest cost, measured rather than asserted in prose.

    Two enrollments can enumerate the same object, so the sums count it twice.
    The type does not deduplicate — a distinct-object corpus total is a different
    measurement and inventing one out of numbers taken for another scope is the
    global inference section 12 forbids — and it raises the flag that obliges the
    layer above to publish the caveat.
    """
    holding = Holding(engine, "overlap", enrolled=("alpha", "beta"))
    second = holding.enroll_again(("beta", "gamma"))
    second_id = second.enrollment_id  # type: ignore[attr-defined]
    for name in ("alpha", "beta"):
        holding.extract(name)
    for name in ("beta", "gamma"):
        holding.extract(name, enrollment_id=second_id)

    answer = holding.corpus()
    assert [counts.enrollment_id for counts in answer.enrollments] == sorted(
        {holding.enrollment_id, second_id}
    )
    assert answer.enrollment_count == 2
    assert answer.held_sources == 1
    # Four enumerated (enrollment, object) pairs over three distinct objects.
    assert answer.stated_eligible == 4
    assert answer.stated_processed == 4
    assert answer.totals_are_per_enrollment_sums is True
    # And the distinct-object view, which the corpus deliberately does not
    # publish as a denominator: one of the four readable objects is enrolled by
    # neither enrollment.
    assert answer.objects_in_held_sources == 4
    assert answer.objects_outside_every_enrollment == 1
    assert answer.objects_awaiting_an_outcome == 0


def test_scope_beyond_an_enrollment_is_this_principals_own_and_no_one_elses(
    engine: Engine,
) -> None:
    """The boolean a search carries its caveat from, at the query boundary.

    Three arrangements, and the third is the one a lost partition predicate would
    turn true. A Principal whose single enrollment covers its whole source holds
    nothing outside it; the same Principal with an object left unenrolled does;
    and a Principal whose corpus is complete must not be told "there is more"
    because *another* Principal holds something.
    """
    whole = Holding(engine, "beyond-whole", enrolled=("alpha", "beta", "gamma", "delta"))
    partial = Holding(engine, "beyond-partial", enrolled=("alpha", "beta"))

    with engine.begin() as connection:
        assert (
            scope_beyond_enrollment(
                connection, whole.principal_id, enrollment_id=whole.enrollment_id
            )
            is False
        ), "another Principal's unenrolled objects are not this Principal's unknown territory"
        assert (
            scope_beyond_enrollment(
                connection, partial.principal_id, enrollment_id=partial.enrollment_id
            )
            is True
        )

    second = whole.enroll_again(("alpha",))
    with engine.begin() as connection:
        assert (
            scope_beyond_enrollment(
                connection, whole.principal_id, enrollment_id=whole.enrollment_id
            )
            is True
        ), "a second enrollment of this Principal is scope the first does not cover"
        assert (
            scope_beyond_enrollment(
                connection,
                whole.principal_id,
                enrollment_id=second.enrollment_id,  # type: ignore[attr-defined]
            )
            is True
        )
