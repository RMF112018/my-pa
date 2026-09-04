"""Two synthetic Principals; zero relationship-identity leakage (WP-04, MU-AC-01/02/04).

Database tier, over a disposable database this module creates and drops.

`SqlRelationshipRepository` stamped `principal_id` on every INSERT and carried
the partition on exactly two of its reads. Seven UPDATEs and the rest of its
SELECTs named a `person_id`, an `observation_id`, or a `resolution_id` and
nothing else, so a Principal holding another's identifier could read that
person's profile, rebind their aliases, affiliations, and evidence, and merge or
split their canonical people. The module had no behavioural test at all, so
nothing said otherwise.

What is asserted here is the property the fix has to have, in both directions
and at every operation that reaches a durable row:

* **a foreign identifier is exactly an absent one.** Every negative below is run
  twice — once against an identifier Principal A really owns, once against one
  that exists nowhere — and the two outcomes are compared as a pair. Equal
  return value, equal exception type, equal message. A refusal that named the
  identifier, or that failed differently for a real record than for an invented
  one, would be an oracle for whether the record exists, so "same class" is
  asserted rather than "raises";
* **a write that would cross the partition writes nothing.** Every relationship
  table is snapshotted before B's attempts and compared after them, so an
  UPDATE that matched no row and an UPDATE that matched the wrong row are told
  apart by the rows rather than by the absence of an exception;
* **the isolation is not an outage.** A does the same operations B was refused,
  successfully, in the same test — the control that stops "everything raises"
  from reading as "isolation holds".

Every identity, source, and person here is synthetic and invented; no path is
opened and no source is reached.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, select, text

from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.relationship.identity import (
    DuplicateCandidateSet,
    IdentityCandidateSet,
    IdentityObservation,
    IdentityResolution,
    ResolutionAction,
    UnresolvedMention,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.relationships import SqlRelationshipRepository
from my_pa.infrastructure.persistence.tables import (
    relationship_affiliations,
    relationship_aliases,
    relationship_conversation_observations,
    relationship_conversation_participants,
    relationship_duplicate_members,
    relationship_duplicate_sets,
    relationship_evidence,
    relationship_evidence_observations,
    relationship_identity_observations,
    relationship_identity_resolutions,
    relationship_identity_review_cases,
    relationship_identity_review_decisions,
    relationship_observation_links,
    relationship_organizations,
    relationship_people,
    relationship_resolution_observations,
    relationship_unresolved_mentions,
)

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_relationship_isolation_test"

#: Two synthetic Principals in the bound form `binding.capture_principal_id`
#: renders — 32 lowercase hex after `prn_`.
PRINCIPAL_A: Final = "prn_aaaa0004aaaaaaaaaaaaaaaa00000004"
PRINCIPAL_B: Final = "prn_bbbb0004bbbbbbbbbbbbbbbb00000004"

WHEN: Final = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)

#: Every relationship table the repository writes. Snapshotted whole, so a
#: cross-partition write is caught wherever it lands rather than only in the
#: table a particular assertion thought to look at.
PARTITIONED_TABLES: Final = (
    relationship_people,
    relationship_organizations,
    relationship_identity_observations,
    relationship_unresolved_mentions,
    relationship_duplicate_sets,
    relationship_duplicate_members,
    relationship_identity_review_cases,
    relationship_identity_review_decisions,
    relationship_identity_resolutions,
    relationship_resolution_observations,
    relationship_observation_links,
    relationship_aliases,
    relationship_affiliations,
    relationship_evidence,
    relationship_evidence_observations,
    relationship_conversation_participants,
    relationship_conversation_observations,
)

pytestmark = pytest.mark.database


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.relationship_people, "
                    "knowledge.relationship_organizations, "
                    "knowledge.relationship_identity_observations, "
                    "knowledge.relationship_unresolved_mentions, "
                    "knowledge.relationship_duplicate_sets CASCADE"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _id(prefix: str, ordinal: int) -> str:
    return f"{prefix}_{ordinal:016d}"


def _observation(ordinal: int, *, source_ordinal: int) -> IdentityObservation:
    """One synthetic observation, on a source the owning Principal alone enrolled.

    The `source_id` differs per Principal because
    `an_observed_source_version_is_recorded_once` is a table-wide unique
    constraint over `(source_id, source_object_id, source_version)` rather than
    a per-Principal one. That residual is registered in
    `tests/architecture/test_user_owned_tables_are_partitioned.py`; it is not
    what this module measures, so the fixtures stay clear of it.
    """
    return IdentityObservation(
        observation_id=_id("iobs", ordinal),
        source_id=_id("src", source_ordinal),
        source_object_id=_id("obj", ordinal),
        source_version=_id("ver", ordinal),
        observed_at=WHEN,
        display_name=f"Synthetic Person {ordinal}",
    )


def _link_person(
    repository: SqlRelationshipRepository,
    *,
    principal_id: str,
    person_ordinal: int,
    observations: tuple[IdentityObservation, ...],
) -> str:
    """Take one Principal's observations all the way to a canonical person."""
    candidate = IdentityCandidateSet(
        candidate_set_id=_id("dups", person_ordinal),
        person_ids=(),
        observation_ids=tuple(row.observation_id for row in observations),
        created_at=WHEN,
    )
    review_id = repository.open_identity_review(candidate, ResolutionAction.LINK_OBSERVATION)
    decision_id = repository.decide_identity_review(
        review_id, disposition="accept", principal_id=principal_id, decided_at=WHEN
    )
    person_id = _id("per", person_ordinal)
    repository.apply_resolution(
        IdentityResolution(
            resolution_id=_id("ires", person_ordinal),
            action=ResolutionAction.LINK_OBSERVATION,
            review_case_id=review_id,
            decision_id=decision_id,
            retained_person_id=person_id,
            prior_person_id=None,
            observation_ids=tuple(row.observation_id for row in observations),
            decided_at=WHEN,
        ),
        display_name=f"Synthetic Person {person_ordinal}",
    )
    return person_id


def _snapshot(connection: Connection) -> dict[str, list[tuple[object, ...]]]:
    """Every row of every relationship table, ordered, as comparable tuples."""
    return {
        str(table.name): sorted(
            tuple(str(value) for value in row) for row in connection.execute(select(table)).all()
        )
        for table in PARTITIONED_TABLES
    }


def _attempt(
    engine: Engine, principal_id: str, action: Callable[[SqlRelationshipRepository], object]
) -> tuple[str, str]:
    """Run one operation on its own connection, roll it back, report what it did.

    The answer is a comparable pair: either `("returned", repr(value))` or
    `(exception class name, message)`. Making a return and a raise the same
    shape of answer is what turns "a foreign identifier is indistinguishable
    from an absent one" into an equality rather than two `pytest.raises` blocks
    that happen to agree.

    **Its own connection, and that is not tidiness.** Two attempts on one
    connection are not independent: the first one to fail aborts the
    transaction, and every attempt after it reports PostgreSQL's
    `InFailedSqlTransaction` instead of its own outcome. A controlled violation
    of the ownership check was caught by this file comparing an `IntegrityError`
    against exactly that contamination — a difference that was real but not the
    one the assertion claimed to be measuring. One connection per attempt, and
    a rollback after each, so every pair below compares two first failures.
    """
    with engine.connect() as connection:
        repository = SqlRelationshipRepository(connection, principal_id=principal_id)
        try:
            return ("returned", repr(action(repository)))
        except Exception as error:  # the class is the measurement
            return (type(error).__name__, str(error))
        finally:
            connection.rollback()


@pytest.fixture
def seeded(engine: Engine) -> tuple[str, str, str]:
    """Principal A owns *two* canonical people, one organization, one mention.

    Two, not one, and the reason is a controlled violation this fixture had to
    survive. With one person, every merge B could attempt named A's person and
    one that exists nowhere, so the refusal fired on the invented half and an
    implementation with no partition on its ownership check passed the test
    unchanged. Two of A's own people let B attempt a merge in which *every*
    identifier is real and none is B's, which is the case that distinguishes a
    partitioned ownership check from an unpartitioned one.
    """
    with engine.begin() as connection:
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        observations = (_observation(1, source_ordinal=1), _observation(2, source_ordinal=1))
        a.record_observations("contacts", observations)
        person_id = _link_person(
            a, principal_id=PRINCIPAL_A, person_ordinal=1, observations=observations
        )
        a.record_source_affiliation(
            organization_id=_id("org", 1),
            organization_name="Synthetic Organization One",
            affiliation_id=_id("aff", 1),
            person_id=person_id,
            observation_id=observations[0].observation_id,
            role="member",
            effective_from=WHEN,
            effective_to=None,
        )
        a.record_unresolved_mention(
            UnresolvedMention(
                unresolved_mention_id=_id("umen", 1),
                source_object_id=_id("obj", 9),
                source_version=_id("ver", 9),
                observed_at=WHEN,
            )
        )
        second = (_observation(3, source_ordinal=1),)
        a.record_observations("email", second)
        second_person_id = _link_person(
            a, principal_id=PRINCIPAL_A, person_ordinal=2, observations=second
        )
    return person_id, second_person_id, _id("org", 1)


def test_a_foreign_person_reads_exactly_as_an_absent_one(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """MU-AC-01/MU-AC-04: B's profile read of A's person answers `None`.

    Compared against B's read of a person that exists nowhere, so the answer is
    the *same* answer rather than merely a falsy one.
    """
    person_id, _second_person_id, organization_id = seeded
    foreign = _attempt(
        engine, PRINCIPAL_B, lambda r: r.profile(person_id, expected_domains=("contacts",))
    )
    absent = _attempt(
        engine, PRINCIPAL_B, lambda r: r.profile(_id("per", 999), expected_domains=("contacts",))
    )
    foreign_org = _attempt(engine, PRINCIPAL_B, lambda r: r.organization_profile(organization_id))
    absent_org = _attempt(engine, PRINCIPAL_B, lambda r: r.organization_profile(_id("org", 999)))

    # The control: A's read of A's own person is not `None`, so the two `None`s
    # above are a partition rather than an empty database.
    with engine.connect() as connection:
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        held = a.profile(person_id, expected_domains=("contacts",))

    assert foreign == absent == ("returned", "None")
    assert foreign_org == absent_org == ("returned", "None")
    assert held is not None
    assert held.person_id == person_id
    assert held.observation_ids == (_id("iobs", 1), _id("iobs", 2))


def test_principal_b_cannot_review_merge_or_split_principal_a_s_people(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """Every governed correction over A's records is refused, identically to absent."""
    person_id, second_person_id, _organization = seeded

    def _review(
        action: ResolutionAction, *, people: tuple[str, ...], observations: tuple[str, ...]
    ) -> Callable[[SqlRelationshipRepository], object]:
        def _run(repository: SqlRelationshipRepository) -> object:
            return repository.open_identity_review(
                IdentityCandidateSet(
                    candidate_set_id=_id("dups", 50),
                    person_ids=people,
                    observation_ids=observations,
                    created_at=WHEN,
                ),
                action,
                retained_person_id=people[0] if people else None,
                prior_person_id=people[1] if len(people) > 1 else None,
            )

        return _run

    # Both halves of the merge are people A really owns, so nothing in this
    # candidate set is absent: the only thing wrong with it is whose records
    # they are. This is the case an unpartitioned ownership check passes.
    merge = ResolutionAction.MERGE_PERSON
    split = ResolutionAction.SPLIT_PERSON
    link = ResolutionAction.LINK_OBSERVATION
    merge_foreign = _attempt(
        engine, PRINCIPAL_B, _review(merge, people=(person_id, second_person_id), observations=())
    )
    merge_absent = _attempt(
        engine,
        PRINCIPAL_B,
        _review(merge, people=(_id("per", 999), _id("per", 998)), observations=()),
    )
    split_foreign = _attempt(
        engine, PRINCIPAL_B, _review(split, people=(person_id, second_person_id), observations=())
    )
    split_absent = _attempt(
        engine,
        PRINCIPAL_B,
        _review(split, people=(_id("per", 997), _id("per", 996)), observations=()),
    )
    link_foreign = _attempt(
        engine, PRINCIPAL_B, _review(link, people=(), observations=(_id("iobs", 1),))
    )
    link_absent = _attempt(
        engine, PRINCIPAL_B, _review(link, people=(), observations=(_id("iobs", 997),))
    )

    assert merge_foreign == merge_absent
    assert split_foreign == split_absent
    assert link_foreign == link_absent
    assert merge_foreign[0] == "IdentityResolutionError"
    assert link_foreign[0] == "IdentityResolutionError"
    # The refusal says nothing about whose record it was, and names no identifier.
    for outcome in (merge_foreign, split_foreign, link_foreign):
        assert person_id not in outcome[1]
        assert PRINCIPAL_A not in outcome[1]


def test_principal_b_cannot_decide_or_resolve_principal_a_s_review(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """A decision and a resolution aimed at A's governed review are both refused."""
    _person_id, _second, _organization = seeded
    with engine.connect() as connection:
        case_id = connection.execute(
            select(relationship_identity_review_cases.c.review_case_id)
            .order_by(relationship_identity_review_cases.c.review_case_id)
            .limit(1)
        ).scalar_one()
        decision_id = connection.execute(
            select(relationship_identity_review_decisions.c.decision_id)
            .order_by(relationship_identity_review_decisions.c.decision_id)
            .limit(1)
        ).scalar_one()

    def _decide(case: str) -> Callable[[SqlRelationshipRepository], object]:
        def _run(repository: SqlRelationshipRepository) -> object:
            return repository.decide_identity_review(
                case, disposition="accept", principal_id=PRINCIPAL_B, decided_at=WHEN
            )

        return _run

    def _resolve(case: str, decision: str) -> Callable[[SqlRelationshipRepository], object]:
        def _run(repository: SqlRelationshipRepository) -> object:
            repository.apply_resolution(
                IdentityResolution(
                    resolution_id=_id("ires", 60),
                    action=ResolutionAction.LINK_OBSERVATION,
                    review_case_id=case,
                    decision_id=decision,
                    retained_person_id=_id("per", 60),
                    prior_person_id=None,
                    observation_ids=(_id("iobs", 1),),
                    decided_at=WHEN,
                ),
                display_name="Synthetic Person 60",
            )
            return None

        return _run

    decide_foreign = _attempt(engine, PRINCIPAL_B, _decide(str(case_id)))
    decide_absent = _attempt(engine, PRINCIPAL_B, _decide(_id("rvw", 999)))
    resolve_foreign = _attempt(engine, PRINCIPAL_B, _resolve(str(case_id), str(decision_id)))
    resolve_absent = _attempt(engine, PRINCIPAL_B, _resolve(_id("rvw", 999), _id("rdec", 999)))

    assert decide_foreign == decide_absent
    assert decide_foreign[0] == "IdentityResolutionError"
    assert resolve_foreign == resolve_absent
    assert resolve_foreign[0] == "IdentityResolutionError"


def test_a_caller_supplied_deciding_principal_is_refused(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """MU-AC-02: the deciding Principal is the repository's, verified not trusted."""
    with engine.connect() as connection:
        case_id = str(
            connection.execute(
                select(relationship_identity_review_cases.c.review_case_id)
                .order_by(relationship_identity_review_cases.c.review_case_id)
                .limit(1)
            ).scalar_one()
        )
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        with pytest.raises(CallerSuppliedPrincipalError):
            a.decide_identity_review(
                case_id, disposition="accept", principal_id=PRINCIPAL_B, decided_at=WHEN
            )


def test_no_attempt_by_b_changes_a_single_row_of_a_s_partition(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """Fails closed at the rows: every crossing attempt writes nothing at all.

    An UPDATE with a partition predicate that matched no row and an UPDATE that
    rewrote the wrong row both leave without raising, so the exceptions above
    are not the measurement. The rows are.
    """
    person_id, _second_person_id, organization_id = seeded
    with engine.connect() as connection:
        before = _snapshot(connection)

    crossings: tuple[tuple[str, Callable[[SqlRelationshipRepository], object]], ...] = (
        ("profile", lambda r: r.profile(person_id, expected_domains=("contacts",))),
        ("organization_profile", lambda r: r.organization_profile(organization_id)),
        (
            "affiliation",
            lambda r: r.record_source_affiliation(
                organization_id=organization_id,
                organization_name="Renamed By Another Principal",
                affiliation_id=_id("aff", 70),
                person_id=person_id,
                observation_id=_id("iobs", 1),
                role="member",
                effective_from=WHEN,
                effective_to=None,
            ),
        ),
        (
            "conversation_participant",
            lambda r: r.attach_conversation_participant(
                _id("conv", 70), person_id=person_id, observation_ids=(_id("iobs", 1),)
            ),
        ),
        (
            "unresolved_mention_rebind",
            lambda r: r.record_unresolved_mention(
                UnresolvedMention(
                    unresolved_mention_id=_id("umen", 1),
                    source_object_id=_id("obj", 70),
                    source_version=_id("ver", 70),
                    observed_at=WHEN,
                )
            ),
        ),
    )
    attempts = [(name, _attempt(engine, PRINCIPAL_B, call)) for name, call in crossings]

    with engine.connect() as connection:
        after = _snapshot(connection)

    assert after == before
    # Not one of the five silently succeeded: a crossing attempt that returned
    # normally would leave the snapshot equal for the wrong reason.
    for name, outcome in attempts:
        assert outcome[0] != "returned" or outcome[1] == "None", (
            f"{name} crossed the partition without refusing: {outcome}"
        )


def test_the_owning_principal_can_still_do_everything_b_was_refused(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """The control. Isolation that also blocked the owner would pass every test above."""
    person_id, _second_person_id, organization_id = seeded
    with engine.begin() as connection:
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        assert a.profile(person_id, expected_domains=("contacts",)) is not None
        organization = a.organization_profile(organization_id)
        assert organization is not None
        assert organization.affiliations[0][0] == person_id

        # A third person for A, linked from A's own further observations.
        further = (_observation(4, source_ordinal=1),)
        assert a.record_observations("email", further) == 1
        third = _link_person(a, principal_id=PRINCIPAL_A, person_ordinal=3, observations=further)
        assert a.profile(third, expected_domains=("email",)) is not None


def test_b_owns_its_own_partition_in_the_same_database(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """The other direction: B's records are B's, and A cannot see them either."""
    person_id, _second_person_id, _organization = seeded
    with engine.begin() as connection:
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)
        observations = (_observation(11, source_ordinal=2),)
        assert b.record_observations("calendar", observations) == 1
        b_person = _link_person(
            b, principal_id=PRINCIPAL_B, person_ordinal=11, observations=observations
        )

    with engine.connect() as connection:
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        assert a.profile(b_person, expected_domains=("calendar",)) is None
        assert a.profile(person_id, expected_domains=("contacts",)) is not None
        b_again = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)
        assert b_again.profile(b_person, expected_domains=("calendar",)) is not None
        assert b_again.profile(person_id, expected_domains=("contacts",)) is None


def test_an_accepted_decision_from_another_principal_cannot_authorize_b_s_own_merge(
    engine: Engine, seeded: tuple[str, str, str]
) -> None:
    """The governance authority does not cross the partition either (WP-12).

    Every other negative in this module has B reaching for A's *records*. This
    one has B reaching for A's *authority*: B opens a perfectly legitimate merge
    review over two people B genuinely owns, and then names one of A's real,
    accepting identity-review decisions as the thing that authorized it.

    That is the shape of the defect WP-11 reviewer NOTE 2 records against the
    continuity acceptance gate — a decision trusted because it exists, accepted,
    and belongs to *a* Principal, rather than because it decided this case. Here
    the decision belongs to a *different* Principal and decided a different
    case, so it fails both bindings at once, and the refusal must be the same
    one a decision that exists nowhere produces.

    The control at the end is what stops this reading as "B cannot merge": B's
    own decision, on B's own case, does authorize the merge.
    """
    _person_id, _second, _organization = seeded

    # One of A's decisions: real, accepting, and already used to link A's people.
    with engine.connect() as connection:
        foreign_decision = str(
            connection.execute(
                select(relationship_identity_review_decisions.c.decision_id)
                .where(relationship_identity_review_decisions.c.principal_id == PRINCIPAL_A)
                .order_by(relationship_identity_review_decisions.c.decision_id)
                .limit(1)
            ).scalar_one()
        )

    # B's own people and B's own merge review, opened legitimately.
    b_observations = (_observation(21, source_ordinal=2), _observation(22, source_ordinal=2))
    with engine.begin() as connection:
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)
        b.record_observations("contacts", b_observations)
        b_first = _link_person(
            b, principal_id=PRINCIPAL_B, person_ordinal=21, observations=(b_observations[0],)
        )
        b_second = _link_person(
            b, principal_id=PRINCIPAL_B, person_ordinal=22, observations=(b_observations[1],)
        )
        b_case = b.open_identity_review(
            DuplicateCandidateSet(
                candidate_set_id=_id("dups", 23),
                person_ids=(b_first, b_second),
                observation_ids=(b_observations[1].observation_id,),
                created_at=WHEN,
            ),
            ResolutionAction.MERGE_PERSON,
            retained_person_id=b_first,
            prior_person_id=b_second,
        )

    def _merge(decision_id: str) -> Callable[[SqlRelationshipRepository], object]:
        def _run(repository: SqlRelationshipRepository) -> object:
            repository.apply_resolution(
                IdentityResolution(
                    resolution_id=_id("ires", 23),
                    action=ResolutionAction.MERGE_PERSON,
                    review_case_id=b_case,
                    decision_id=decision_id,
                    retained_person_id=b_first,
                    prior_person_id=b_second,
                    observation_ids=(b_observations[1].observation_id,),
                    decided_at=WHEN,
                ),
                display_name="unused",
            )
            return None

        return _run

    with engine.connect() as connection:
        before = _snapshot(connection)

    borrowed = _attempt(engine, PRINCIPAL_B, _merge(foreign_decision))
    absent = _attempt(engine, PRINCIPAL_B, _merge(_id("rdec", 999)))

    assert borrowed == absent
    assert borrowed[0] == "IdentityResolutionError"
    # The refusal names neither the decision nor whose it was.
    assert foreign_decision not in borrowed[1]
    assert PRINCIPAL_A not in borrowed[1]

    with engine.connect() as connection:
        assert _snapshot(connection) == before

    # The control: B's own accepting decision, on B's own case, does authorize
    # it. Without this the two refusals above would be satisfied by a merge that
    # never works for anyone.
    with engine.begin() as connection:
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)
        own_decision = b.decide_identity_review(
            b_case, disposition="accept", principal_id=PRINCIPAL_B, decided_at=WHEN
        )
        _merge(own_decision)(b)
        assert b.profile(b_second, expected_domains=("contacts",)) is None
        merged = b.profile(b_first, expected_domains=("contacts",))
        assert merged is not None
        assert merged.observation_ids == tuple(
            sorted(observation.observation_id for observation in b_observations)
        )

    # And none of it reached A: A's partition is byte-identical to before.
    with engine.connect() as connection:
        after = _snapshot(connection)
    for name, rows in before.items():
        a_rows = [row for row in rows if PRINCIPAL_A in row]
        assert [row for row in after[name] if PRINCIPAL_A in row] == a_rows
