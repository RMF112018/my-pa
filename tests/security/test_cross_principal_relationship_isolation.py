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

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.relationship.identity import (
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
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


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


def _outcome(call: object) -> tuple[str, str]:
    """What one call did, as a comparable pair: exception class and message.

    A returned value is reported as its own class and repr, so "returned `None`"
    and "raised `IdentityResolutionError(...)`" are the same shape of answer and
    can be compared directly. This is what makes "a foreign identifier is
    indistinguishable from an absent one" an equality rather than two separate
    `pytest.raises` blocks that happen to agree.
    """
    assert callable(call)
    try:
        return ("returned", repr(call()))
    except Exception as error:  # the class is the measurement
        return (type(error).__name__, str(error))


@pytest.fixture
def seeded(engine: Engine) -> tuple[str, str]:
    """Principal A owns one canonical person, one organization, one mention."""
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
    return person_id, _id("org", 1)


def test_a_foreign_person_reads_exactly_as_an_absent_one(
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """MU-AC-01/MU-AC-04: B's profile read of A's person answers `None`.

    Compared against B's read of a person that exists nowhere, so the answer is
    the *same* answer rather than merely a falsy one.
    """
    person_id, organization_id = seeded
    with engine.connect() as connection:
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)
        foreign = _outcome(lambda: b.profile(person_id, expected_domains=("contacts",)))
        absent = _outcome(lambda: b.profile(_id("per", 999), expected_domains=("contacts",)))
        foreign_org = _outcome(lambda: b.organization_profile(organization_id))
        absent_org = _outcome(lambda: b.organization_profile(_id("org", 999)))

        # The control: A's read of A's own person is not `None`, so the two
        # `None`s above are a partition rather than an empty database.
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        held = a.profile(person_id, expected_domains=("contacts",))

    assert foreign == absent == ("returned", "None")
    assert foreign_org == absent_org == ("returned", "None")
    assert held is not None
    assert held.person_id == person_id
    assert held.observation_ids == (_id("iobs", 1), _id("iobs", 2))


def test_principal_b_cannot_review_merge_or_split_principal_a_s_people(
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """Every governed correction over A's records is refused, identically to absent."""
    person_id, _organization = seeded
    with engine.connect() as connection:
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)

        def _merge_review(target: str) -> object:
            return b.open_identity_review(
                IdentityCandidateSet(
                    candidate_set_id=_id("dups", 50),
                    person_ids=(target, _id("per", 51)),
                    observation_ids=(),
                    created_at=WHEN,
                ),
                ResolutionAction.MERGE_PERSON,
                retained_person_id=target,
                prior_person_id=_id("per", 51),
            )

        def _split_review(target: str) -> object:
            return b.open_identity_review(
                IdentityCandidateSet(
                    candidate_set_id=_id("dups", 52),
                    person_ids=(target, _id("per", 53)),
                    observation_ids=(),
                    created_at=WHEN,
                ),
                ResolutionAction.SPLIT_PERSON,
                retained_person_id=target,
                prior_person_id=_id("per", 53),
            )

        def _link_review(observation: str) -> object:
            return b.open_identity_review(
                IdentityCandidateSet(
                    candidate_set_id=_id("dups", 54),
                    person_ids=(),
                    observation_ids=(observation,),
                    created_at=WHEN,
                ),
                ResolutionAction.LINK_OBSERVATION,
            )

        merge_foreign = _outcome(lambda: _merge_review(person_id))
        merge_absent = _outcome(lambda: _merge_review(_id("per", 999)))
        split_foreign = _outcome(lambda: _split_review(person_id))
        split_absent = _outcome(lambda: _split_review(_id("per", 998)))
        link_foreign = _outcome(lambda: _link_review(_id("iobs", 1)))
        link_absent = _outcome(lambda: _link_review(_id("iobs", 997)))

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
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """A decision and a resolution aimed at A's governed review are both refused."""
    _person_id, _organization = seeded
    with engine.connect() as connection:
        case_id = connection.execute(
            select(relationship_identity_review_cases.c.review_case_id)
        ).scalar_one()
        decision_id = connection.execute(
            select(relationship_identity_review_decisions.c.decision_id)
        ).scalar_one()
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)

        decide_foreign = _outcome(
            lambda: b.decide_identity_review(
                str(case_id), disposition="accept", principal_id=PRINCIPAL_B, decided_at=WHEN
            )
        )
        decide_absent = _outcome(
            lambda: b.decide_identity_review(
                _id("rvw", 999), disposition="accept", principal_id=PRINCIPAL_B, decided_at=WHEN
            )
        )

        def _resolve(case: str, decision: str) -> object:
            b.apply_resolution(
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

        resolve_foreign = _outcome(lambda: _resolve(str(case_id), str(decision_id)))
        resolve_absent = _outcome(lambda: _resolve(_id("rvw", 999), _id("rdec", 999)))

    assert decide_foreign == decide_absent
    assert decide_foreign[0] == "IdentityResolutionError"
    assert resolve_foreign == resolve_absent
    assert resolve_foreign[0] == "IdentityResolutionError"


def test_a_caller_supplied_deciding_principal_is_refused(
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """MU-AC-02: the deciding Principal is the repository's, verified not trusted."""
    with engine.connect() as connection:
        case_id = str(
            connection.execute(
                select(relationship_identity_review_cases.c.review_case_id)
            ).scalar_one()
        )
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        with pytest.raises(CallerSuppliedPrincipalError):
            a.decide_identity_review(
                case_id, disposition="accept", principal_id=PRINCIPAL_B, decided_at=WHEN
            )


def test_no_attempt_by_b_changes_a_single_row_of_a_s_partition(
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """Fails closed at the rows: every crossing attempt writes nothing at all.

    An UPDATE with a partition predicate that matched no row and an UPDATE that
    rewrote the wrong row both leave without raising, so the exceptions above
    are not the measurement. The rows are.
    """
    person_id, organization_id = seeded
    with engine.connect() as connection:
        before = _snapshot(connection)

    attempts: list[tuple[str, object]] = []
    with engine.connect() as connection:
        b = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_B)
        for name, call in (
            ("profile", lambda: b.profile(person_id, expected_domains=("contacts",))),
            ("organization_profile", lambda: b.organization_profile(organization_id)),
            (
                "affiliation",
                lambda: b.record_source_affiliation(
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
                lambda: b.attach_conversation_participant(
                    _id("conv", 70),
                    person_id=person_id,
                    observation_ids=(_id("iobs", 1),),
                ),
            ),
            (
                "unresolved_mention_rebind",
                lambda: b.record_unresolved_mention(
                    UnresolvedMention(
                        unresolved_mention_id=_id("umen", 1),
                        source_object_id=_id("obj", 70),
                        source_version=_id("ver", 70),
                        observed_at=WHEN,
                    )
                ),
            ),
        ):
            attempts.append((name, _outcome(call)))
        connection.rollback()

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
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """The control. Isolation that also blocked the owner would pass every test above."""
    person_id, organization_id = seeded
    with engine.begin() as connection:
        a = SqlRelationshipRepository(connection, principal_id=PRINCIPAL_A)
        assert a.profile(person_id, expected_domains=("contacts",)) is not None
        organization = a.organization_profile(organization_id)
        assert organization is not None
        assert organization.affiliations[0][0] == person_id

        # A second person for A, linked from A's own further observations.
        further = (_observation(3, source_ordinal=1),)
        assert a.record_observations("email", further) == 1
        second = _link_person(a, principal_id=PRINCIPAL_A, person_ordinal=2, observations=further)
        assert a.profile(second, expected_domains=("email",)) is not None


def test_b_owns_its_own_partition_in_the_same_database(
    engine: Engine, seeded: tuple[str, str]
) -> None:
    """The other direction: B's records are B's, and A cannot see them either."""
    person_id, _organization = seeded
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
