"""The program-scale corpus, loaded into PostgreSQL and answered by the resolver.

`RI-AC-031` asks for a fixture at program scale; `RI-AC-032` asks for the
acceptance suite to pass **against that fixture, under PostgreSQL**. The fixture
has existed since `d4d6d40` and until now nothing read it: no test imported
either module, `fixtures/__init__.py` did not export them, and three separate
comments cited a `tests/evaluation/test_program_scale_acceptance.py` that had
never been written. A fixture no test reads proves the same amount as no
fixture.

**Why the database tier and not the evaluation tier.** The small hand-labelled
corpus is answered through `_CorpusRepository`, an in-memory double that
subclasses the real port. That is the right shape for measuring the *resolver*:
it cannot pass against a row shape production could not supply. It is the wrong
shape for this criterion, which is about scale and about SQL — the partition
predicates, the joins, the `LIMIT` clauses and the candidate cap only exist in
`SqlEntityRepository`, and a cap that never binds at twenty entities is a cap
nothing has measured. So the corpus is written to a disposable database and read
back through the production repository.

**What this suite is not.** It is not a benchmark. `RI-AC-033` asks for p50/p95
figures for six operations and none exist; nothing here times anything, and
adding a wall-clock assertion to a shared, contended database would produce a
number that measures the machine rather than the code.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from tests.evaluation.fixtures.program_scale_cases import PROGRAM_SCALE_CASES
from tests.evaluation.fixtures.program_scale_corpus import (
    ACTIVE_PERSONS,
    COLLISION_GROUP_COUNT,
    HISTORICAL_EMPLOYMENT_CHANGES,
    ORGANIZATIONS,
    PROGRAM_SCALE_CORPUS,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_program_scale_acceptance_test"

#: The floors `RI-AC-031` states. Asserted against the built corpus rather than
#: against the builder's constants, because the constants are the intent and the
#: built rows are the fixture.
MINIMUM_PERSONS: Final = 500
MINIMUM_ORGANIZATIONS: Final = 100
MINIMUM_COMBINED_RECORDS: Final = 5_000
MINIMUM_COLLISION_GROUPS: Final = 50
MINIMUM_HISTORICAL_CHANGES: Final = 50


@pytest.fixture(scope="module")
def loaded_database(module_cloned_database_url: str) -> Iterator[Engine]:
    """A disposable database holding the whole program-scale corpus.

    Module-scoped: loading 5,262 records is the expensive part, and every test
    here reads the same immutable fixture.
    """
    engine = create_database_engine(module_cloned_database_url)
    try:
        with engine.begin() as connection:
            repository = SqlEntityRepository(connection)
            redirects = {
                redirect.merged_entity_id: redirect
                for redirect in PROGRAM_SCALE_CORPUS.merged_redirects
            }
            for entity in PROGRAM_SCALE_CORPUS.entities:
                # The corpus describes final state, but its children are
                # historical facts written before a merge. Reproduce that
                # history: admit each future redirect as current, load every
                # child through the guarded public repository, then apply the
                # intended redirect below.
                repository.create(
                    entity.principal_id,
                    (
                        replace(
                            entity,
                            status=EntityStatus.ACTIVE,
                            superseded_by_entity_id=None,
                        )
                        if entity.entity_id in redirects
                        else entity
                    ),
                )
            for alias in PROGRAM_SCALE_CORPUS.aliases:
                repository.record_alias(alias.principal_id, alias)
            for identifier in PROGRAM_SCALE_CORPUS.identifiers:
                repository.bind_identifier(
                    identifier.principal_id, identifier.entity_id, identifier
                )
            for assignment in PROGRAM_SCALE_CORPUS.assignments:
                repository.record_assignment(assignment.principal_id, assignment)
            for relationship in PROGRAM_SCALE_CORPUS.relationships:
                repository.record_relationship(relationship.principal_id, relationship)
            for observation in PROGRAM_SCALE_CORPUS.observations:
                repository.record_observation(observation.principal_id, observation)
            entities_by_id = {entity.entity_id: entity for entity in PROGRAM_SCALE_CORPUS.entities}
            for redirect in PROGRAM_SCALE_CORPUS.merged_redirects:
                merged = entities_by_id[redirect.merged_entity_id]
                repository.redirect_entity(
                    merged.principal_id,
                    redirect.merged_entity_id,
                    redirect.survivor_entity_id,
                    expected_version=merged.version,
                )
        yield engine
    finally:
        engine.dispose()


def test_the_corpus_clears_every_stated_floor() -> None:
    """`RI-AC-031`, measured on the built rows rather than the builder's intent."""
    kinds = [entity.entity_type for entity in PROGRAM_SCALE_CORPUS.entities]
    persons = kinds.count(EntityType.PERSON)
    organizations = kinds.count(EntityType.ORGANIZATION)
    combined = sum(
        len(collection)
        for collection in (
            PROGRAM_SCALE_CORPUS.aliases,
            PROGRAM_SCALE_CORPUS.identifiers,
            PROGRAM_SCALE_CORPUS.assignments,
            PROGRAM_SCALE_CORPUS.relationships,
            PROGRAM_SCALE_CORPUS.observations,
        )
    )
    assert persons >= MINIMUM_PERSONS, persons
    assert organizations >= MINIMUM_ORGANIZATIONS, organizations
    assert combined >= MINIMUM_COMBINED_RECORDS, combined
    assert COLLISION_GROUP_COUNT >= MINIMUM_COLLISION_GROUPS
    assert HISTORICAL_EMPLOYMENT_CHANGES >= MINIMUM_HISTORICAL_CHANGES
    # The builder's constants and the built rows are different claims, and the
    # gap between them is where the plan's own figures were wrong: `persons` is
    # 565 while `ACTIVE_PERSONS` is 500, because merged duplicates and the
    # second Principal's people are persons too.
    assert persons > ACTIVE_PERSONS
    assert organizations > ORGANIZATIONS


def test_the_corpus_round_trips_through_postgresql(loaded_database: Engine) -> None:
    """Every record written is a record the schema accepts and the reader returns."""
    with loaded_database.connect() as connection:
        counted = {
            table: int(
                connection.execute(
                    text(f"SELECT count(*) FROM knowledge.{table}")  # noqa: S608
                ).scalar_one()
            )
            for table in (
                "entities",
                "entity_aliases",
                "entity_external_identifiers",
                "entity_assignments",
                "entity_relationships",
                "entity_observations",
            )
        }
        redirects = {
            (str(row.entity_id), str(row.superseded_by_entity_id))
            for row in connection.execute(
                text(
                    "SELECT entity_id, superseded_by_entity_id "
                    "FROM knowledge.entities WHERE status = 'merged_redirect'"
                )
            ).all()
        }
    assert counted["entities"] == len(PROGRAM_SCALE_CORPUS.entities)
    assert counted["entity_aliases"] == len(PROGRAM_SCALE_CORPUS.aliases)
    assert counted["entity_external_identifiers"] == len(PROGRAM_SCALE_CORPUS.identifiers)
    assert counted["entity_assignments"] == len(PROGRAM_SCALE_CORPUS.assignments)
    assert counted["entity_relationships"] == len(PROGRAM_SCALE_CORPUS.relationships)
    assert counted["entity_observations"] == len(PROGRAM_SCALE_CORPUS.observations)
    assert redirects == {
        (redirect.merged_entity_id, redirect.survivor_entity_id)
        for redirect in PROGRAM_SCALE_CORPUS.merged_redirects
    }


def test_every_labelled_case_answers_as_labelled(loaded_database: Engine) -> None:
    """`RI-AC-032`: the acceptance cases, against SQL rather than a double.

    The failure this measures is the one the plane exists to prevent — a case
    labelled "must not resolve" that resolves anyway, or one that resolves to
    the wrong entity. Both are reported by name, because "seven failures" is not
    an answer anyone can act on.
    """
    wrong_outcome: list[str] = []
    wrong_entity: list[str] = []
    leaked: list[str] = []
    forbidden: list[str] = []

    with loaded_database.connect() as connection:
        service = EntityResolutionService(SqlEntityRepository(connection))
        for case in PROGRAM_SCALE_CASES:
            answer = service.resolve(
                case.principal_id,
                ResolutionRequest(
                    raw_reference=case.reference,
                    namespace=case.namespace,
                    entity_type=case.entity_type,
                    scope_entity_id=case.scope_entity_id,
                    as_of=case.as_of,
                    at=case.at,
                ),
            )
            if answer.outcome is not case.expected_outcome:
                wrong_outcome.append(
                    f"{case.name}: expected {case.expected_outcome.value}, "
                    f"got {answer.outcome.value}"
                )
            if case.expected_entity_id is not None and (
                answer.resolved_entity_id != case.expected_entity_id
            ):
                wrong_entity.append(
                    f"{case.name}: expected {case.expected_entity_id}, "
                    f"got {answer.resolved_entity_id}"
                )
            offered = {candidate.entity_id for candidate in answer.candidates}
            if case.must_include and not case.must_include <= offered:
                leaked.append(f"{case.name}: missing {sorted(case.must_include - offered)}")
            if case.must_not_include and (case.must_not_include & offered):
                forbidden.append(f"{case.name}: offered {sorted(case.must_not_include & offered)}")

    assert PROGRAM_SCALE_CASES, "the corpus produced no cases, so this proves nothing"
    assert not wrong_outcome, wrong_outcome[:10]
    assert not wrong_entity, wrong_entity[:10]
    assert not forbidden, forbidden[:10]
    assert not leaked, leaked[:10]
