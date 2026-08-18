"""`SqlEntityRepository` against a real PostgreSQL server.

`tests/unit/test_entity_repository.py` drives the in-memory fake and proves the
*contract*. This drives the SQL and proves the contract holds where it has to:
against real statements, real foreign keys, a real unique constraint, and a
partition predicate that is either in the WHERE clause or is not.

The claim that carries the plane is the cross-Principal one, and it is asserted
in both directions each time: a foreign row must be answered exactly as an
absent one -- not distinguished from it, not merely filtered out of a list -- and
a write naming a foreign entity must be refused before it is written rather than
written and hidden later.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.entity import (
    AliasType,
    Assignment,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.normalization import normalize_identifier, normalize_name
from my_pa.domain.relationship.resolution import (
    ResolutionBasis,
    ResolutionOutcome,
    ResolutionWarning,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable
#: database, so this suite can run alongside them without one dropping the
#: database another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_entity_repository_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

ALICE: Final = "ent_aaaa0001aaaa0001"
ACME: Final = "ent_bbbb0002bbbb0002"
TOWER: Final = "ent_cccc0003cccc0003"
BOB: Final = "ent_dddd0004dddd0004"

WHEN: Final = datetime(2026, 8, 17, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def an_entity(
    entity_id: str,
    principal_id: str,
    display_name: str = "Alice Synthetic",
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=display_name.casefold(),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def two_principals(migrated_engine: Engine) -> Engine:
    """Alice and Acme belong to A; Bob belongs to B. Every read below has a decoy."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.create(an_entity(ACME, PRINCIPAL_A, "Acme Synthetic", EntityType.ORGANIZATION))
        repository.create(an_entity(BOB, PRINCIPAL_B, "Bob Synthetic"))
    return migrated_engine


def _row_count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )


# --- reads answer a foreign row exactly as an absent one ---------------------


def test_a_get_cannot_reach_another_principals_entity(two_principals: Engine) -> None:
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        held = repository.get(PRINCIPAL_A, ALICE)
        foreign = repository.get(PRINCIPAL_A, BOB)
        absent = repository.get(PRINCIPAL_A, "ent_eeee0005eeee0005")
    assert held is not None
    assert held.display_name == "Alice Synthetic"
    assert foreign is None
    assert foreign == absent


def test_a_search_cannot_reach_another_principals_entity(two_principals: Engine) -> None:
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.search(PRINCIPAL_A, "synthetic")
        theirs = repository.search(PRINCIPAL_B, "synthetic")
    assert sorted(summary.entity_id for summary in mine) == sorted([ALICE, ACME])
    assert [summary.entity_id for summary in theirs] == [BOB]


def test_a_search_matches_the_display_name_case_insensitively(two_principals: Engine) -> None:
    with two_principals.connect() as connection:
        found = SqlEntityRepository(connection).search(PRINCIPAL_A, "ALICE")
    assert [summary.entity_id for summary in found] == [ALICE]


def test_a_search_term_containing_a_wildcard_stays_literal(migrated_engine: Engine) -> None:
    """A caller who typed `%` gets the entities whose names contain `%`, not all of them."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.create(an_entity(ACME, PRINCIPAL_A, "100% Synthetic"))
    with migrated_engine.connect() as connection:
        wildcard = SqlEntityRepository(connection).search(PRINCIPAL_A, "%")
    assert [summary.entity_id for summary in wildcard] == [ACME]


def test_a_search_filters_by_entity_type(two_principals: Engine) -> None:
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        people = repository.search(PRINCIPAL_A, "synthetic", entity_type=EntityType.PERSON)
        orgs = repository.search(PRINCIPAL_A, "synthetic", entity_type=EntityType.ORGANIZATION)
    assert [summary.entity_id for summary in people] == [ALICE]
    assert [summary.entity_id for summary in orgs] == [ACME]


def test_a_search_is_bounded_by_its_limit(two_principals: Engine) -> None:
    with two_principals.connect() as connection:
        assert len(SqlEntityRepository(connection).search(PRINCIPAL_A, "synthetic", limit=1)) == 1


def test_enumerations_of_a_foreign_entity_are_empty_not_populated(
    two_principals: Engine,
) -> None:
    """Every enumeration answers the same emptiness a missing entity answers."""
    with two_principals.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.external_identifiers(PRINCIPAL_A, BOB) == []
        assert repository.assignments(PRINCIPAL_A, BOB) == []
        assert repository.relationships(PRINCIPAL_A, BOB) == []


# --- writes refuse a foreign reference before writing ------------------------


def test_binding_an_identifier_to_a_foreign_entity_writes_nothing(
    two_principals: Engine,
) -> None:
    identifier = ExternalIdentifier(
        identifier_id="xid_aaaa0001aaaa0001",
        entity_id=BOB,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value="bob@example.test",
        display_value="bob@example.test",
        principal_id=PRINCIPAL_A,
    )
    with pytest.raises(UnknownScopeError), two_principals.begin() as connection:
        SqlEntityRepository(connection).bind_identifier(PRINCIPAL_A, BOB, identifier)
    assert _row_count(two_principals, "entity_external_identifiers") == 0


def test_an_assignment_whose_scope_is_foreign_writes_nothing(two_principals: Engine) -> None:
    """The scope is checked, not only the subject: a foreign key is not a partition."""
    assignment = Assignment(
        assignment_id="asn_aaaa0001aaaa0001",
        entity_id=ALICE,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL_A,
        scope_entity_id=BOB,
    )
    with pytest.raises(UnknownScopeError), two_principals.begin() as connection:
        SqlEntityRepository(connection).record_assignment(PRINCIPAL_A, assignment)
    assert _row_count(two_principals, "entity_assignments") == 0


def test_a_relationship_reaching_into_another_partition_writes_nothing(
    two_principals: Engine,
) -> None:
    relationship = EntityRelationship(
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ALICE,
        relationship_type=EntityRelationshipType.AFFILIATED_WITH,
        to_entity_id=BOB,
        principal_id=PRINCIPAL_A,
    )
    with pytest.raises(UnknownScopeError), two_principals.begin() as connection:
        SqlEntityRepository(connection).record_relationship(PRINCIPAL_A, relationship)
    assert _row_count(two_principals, "entity_relationships") == 0


def test_a_record_stamped_with_another_principal_writes_nothing(
    two_principals: Engine,
) -> None:
    """The record's own `principal_id` is checked against the acting one, never trusted."""
    assignment = Assignment(
        assignment_id="asn_aaaa0001aaaa0001",
        entity_id=ALICE,
        assignment_type=AssignmentType.EMPLOYMENT,
        principal_id=PRINCIPAL_B,
    )
    with (
        pytest.raises(ValueError, match="belongs to the acting Principal"),
        two_principals.begin() as connection,
    ):
        SqlEntityRepository(connection).record_assignment(PRINCIPAL_A, assignment)
    assert _row_count(two_principals, "entity_assignments") == 0


# --- writes that succeed, and their idempotency ------------------------------


def test_a_created_entity_reads_back_with_every_field(migrated_engine: Engine) -> None:
    entity = an_entity(ALICE, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        SqlEntityRepository(connection).create(entity)
    with migrated_engine.connect() as connection:
        stored = SqlEntityRepository(connection).get(PRINCIPAL_A, ALICE)
    assert stored == entity


def test_creating_the_same_entity_twice_writes_one_row(migrated_engine: Engine) -> None:
    entity = an_entity(ALICE, PRINCIPAL_A)
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        first = repository.create(entity)
        second = repository.create(entity)
    assert first == second
    assert _row_count(migrated_engine, "entities") == 1


def test_reusing_an_entity_identifier_for_different_values_is_refused(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        SqlEntityRepository(connection).create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
    with (
        pytest.raises(ValueError, match="cannot be rebound"),
        migrated_engine.begin() as connection,
    ):
        SqlEntityRepository(connection).create(an_entity(ALICE, PRINCIPAL_A, "Someone Else"))


def test_binding_the_same_external_identity_twice_writes_one_row(
    migrated_engine: Engine,
) -> None:
    """Idempotent against the natural key, whatever identifier the caller minted.

    Proved here rather than only against the fake, because the behaviour comes
    from the `an_external_identifier_is_recorded_once_per_namespace` constraint
    and `ON CONFLICT DO NOTHING`, neither of which a Python list has.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A))
        for identifier_id in ("xid_aaaa0001aaaa0001", "xid_bbbb0002bbbb0002"):
            repository.bind_identifier(
                PRINCIPAL_A,
                ALICE,
                ExternalIdentifier(
                    identifier_id=identifier_id,
                    entity_id=ALICE,
                    namespace=ExternalIdentifierNamespace.EMAIL,
                    normalized_value="alice@example.test",
                    display_value="Alice@Example.test",
                    principal_id=PRINCIPAL_A,
                ),
            )
    assert _row_count(migrated_engine, "entity_external_identifiers") == 1
    with migrated_engine.connect() as connection:
        stored = SqlEntityRepository(connection).external_identifiers(PRINCIPAL_A, ALICE)
    assert [identifier.identifier_id for identifier in stored] == ["xid_aaaa0001aaaa0001"]


def test_the_same_value_in_two_namespaces_is_two_identifiers(
    migrated_engine: Engine,
) -> None:
    """The natural key includes the namespace, so it does not conflate them."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A))
        for identifier_id, namespace in (
            ("xid_aaaa0001aaaa0001", ExternalIdentifierNamespace.EMAIL),
            ("xid_bbbb0002bbbb0002", ExternalIdentifierNamespace.VENDOR_SYSTEM_ID),
        ):
            repository.bind_identifier(
                PRINCIPAL_A,
                ALICE,
                ExternalIdentifier(
                    identifier_id=identifier_id,
                    entity_id=ALICE,
                    namespace=namespace,
                    normalized_value="alice@example.test",
                    display_value="alice@example.test",
                    principal_id=PRINCIPAL_A,
                ),
            )
    assert _row_count(migrated_engine, "entity_external_identifiers") == 2


def test_an_assignment_reads_back_and_respects_active_only(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A))
        repository.create(an_entity(TOWER, PRINCIPAL_A, "Alice Tower", EntityType.PROJECT))
        for assignment_id, status in (
            ("asn_aaaa0001aaaa0001", "active"),
            ("asn_bbbb0002bbbb0002", "ended"),
        ):
            repository.record_assignment(
                PRINCIPAL_A,
                Assignment(
                    assignment_id=assignment_id,
                    entity_id=ALICE,
                    assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                    principal_id=PRINCIPAL_A,
                    scope_entity_id=TOWER,
                    role="project executive",
                    status=status,
                ),
            )
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        active = repository.assignments(PRINCIPAL_A, ALICE)
        every = repository.assignments(PRINCIPAL_A, ALICE, active_only=False)
    assert [assignment.assignment_id for assignment in active] == ["asn_aaaa0001aaaa0001"]
    assert active[0].scope_entity_id == TOWER
    assert active[0].role == "project executive"
    assert len(every) == 2


def test_relationships_are_enumerated_by_direction(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A))
        repository.create(an_entity(ACME, PRINCIPAL_A, "Acme Synthetic", EntityType.ORGANIZATION))
        repository.record_relationship(
            PRINCIPAL_A,
            EntityRelationship(
                relationship_id="erel_aaaa0001aaaa0001",
                from_entity_id=ALICE,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=ACME,
                principal_id=PRINCIPAL_A,
            ),
        )
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        outgoing = repository.relationships(PRINCIPAL_A, ALICE, direction="outgoing")
        incoming = repository.relationships(PRINCIPAL_A, ALICE, direction="incoming")
        inbound_at_acme = repository.relationships(PRINCIPAL_A, ACME, direction="incoming")
        either = repository.relationships(PRINCIPAL_A, ALICE)
    assert [relationship.to_entity_id for relationship in outgoing] == [ACME]
    assert incoming == []
    assert [relationship.from_entity_id for relationship in inbound_at_acme] == [ALICE]
    assert len(either) == 1


def test_recording_the_same_relationship_twice_writes_one_row(migrated_engine: Engine) -> None:
    relationship = EntityRelationship(
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ALICE,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=ACME,
        principal_id=PRINCIPAL_A,
    )
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A))
        repository.create(an_entity(ACME, PRINCIPAL_A, "Acme Synthetic", EntityType.ORGANIZATION))
        repository.record_relationship(PRINCIPAL_A, relationship)
        repository.record_relationship(PRINCIPAL_A, relationship)
    assert _row_count(migrated_engine, "entity_relationships") == 1


def test_two_principals_may_hold_entities_with_the_same_name(migrated_engine: Engine) -> None:
    """Names are not identities, so a shared name is two rows rather than a conflict."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.create(an_entity(BOB, PRINCIPAL_B, "Alice Synthetic"))
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        mine = repository.search(PRINCIPAL_A, "Alice Synthetic")
        theirs = repository.search(PRINCIPAL_B, "Alice Synthetic")
    assert [summary.entity_id for summary in mine] == [ALICE]
    assert [summary.entity_id for summary in theirs] == [BOB]


def test_one_principal_may_hold_two_entities_with_the_same_name(
    migrated_engine: Engine,
) -> None:
    """Same-name protection starts here: two real people may share a name.

    The schema must not make that a conflict, because resolving between them is
    exactly the job WP-RI-03 and WP-RI-04 exist to do carefully.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.create(an_entity(BOB, PRINCIPAL_A, "Alice Synthetic"))
    with migrated_engine.connect() as connection:
        found = SqlEntityRepository(connection).search(PRINCIPAL_A, "Alice Synthetic")
    assert sorted(summary.entity_id for summary in found) == sorted([ALICE, BOB])


# --- the joined resolution lookups, against real SQL ------------------------
#
# These four exist because `entities_by_identifier` and `entities_by_alias`
# SELECT two tables that both declare `entity_id` and `principal_id`, and the
# row mappers read those by attribute. Whether that resolves to the column the
# mapper meant is a property of the driver and the statement, not of the Python
# — so it is asserted here rather than reasoned about.


def _an_alias(alias_id: str, entity_id: str, name: str) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=AliasType.NICKNAME,
        normalized_value=normalize_name(name),
        display_value=name,
        principal_id=PRINCIPAL_A,
    )


def _an_email(
    identifier_id: str, entity_id: str, address: str, verified: bool
) -> ExternalIdentifier:
    return ExternalIdentifier(
        identifier_id=identifier_id,
        entity_id=entity_id,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
        display_value=address,
        principal_id=PRINCIPAL_A,
        verified=verified,
    )


def test_a_joined_identifier_lookup_hydrates_both_records(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.bind_identifier(
            PRINCIPAL_A, ALICE, _an_email("xid_aaaa0001aaaa0001", ALICE, "alice@example.test", True)
        )
    with migrated_engine.connect() as connection:
        found = SqlEntityRepository(connection).entities_by_identifier(
            PRINCIPAL_A, ExternalIdentifierNamespace.EMAIL, "alice@example.test"
        )
    assert len(found) == 1
    entity, identifier = found[0]
    assert entity.entity_id == ALICE
    assert entity.display_name == "Alice Synthetic"
    assert identifier.identifier_id == "xid_aaaa0001aaaa0001"
    assert identifier.entity_id == ALICE
    assert identifier.verified is True
    assert identifier.namespace is ExternalIdentifierNamespace.EMAIL


def test_a_joined_alias_lookup_hydrates_both_records(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.record_alias(PRINCIPAL_A, _an_alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    with migrated_engine.connect() as connection:
        found = SqlEntityRepository(connection).entities_by_alias(PRINCIPAL_A, "ali")
    assert len(found) == 1
    entity, alias = found[0]
    assert entity.entity_id == ALICE
    assert entity.display_name == "Alice Synthetic"
    assert alias.alias_id == "eals_aaaa0001aaaa0001"
    assert alias.display_value == "Ali"
    assert alias.alias_type is AliasType.NICKNAME


def test_a_joined_lookup_cannot_reach_another_principals_entity(
    migrated_engine: Engine,
) -> None:
    """The partition is applied to both sides of the join, not only to the entity."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(BOB, PRINCIPAL_B, "Bob Synthetic"))
        repository.record_alias(
            PRINCIPAL_B,
            EntityAlias(
                alias_id="eals_bbbb0002bbbb0002",
                entity_id=BOB,
                alias_type=AliasType.NICKNAME,
                normalized_value="bob",
                display_value="Bob",
                principal_id=PRINCIPAL_B,
            ),
        )
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        assert repository.entities_by_alias(PRINCIPAL_A, "bob") == []
        assert repository.entities_by_canonical_name(PRINCIPAL_A, "bob synthetic") == []


def test_a_canonical_name_lookup_is_an_equality_not_a_substring(
    migrated_engine: Engine,
) -> None:
    """`search` answers "who is like this"; resolution answers "who is this"."""
    with migrated_engine.begin() as connection:
        SqlEntityRepository(connection).create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
    with migrated_engine.connect() as connection:
        repository = SqlEntityRepository(connection)
        found = repository.entities_by_canonical_name(PRINCIPAL_A, "alice synthetic")
        assert [entity.entity_id for entity in found] == [ALICE]
        assert repository.entities_by_canonical_name(PRINCIPAL_A, "alice") == []


# --- resolution end to end, over real SQL -----------------------------------


def test_resolution_resolves_a_verified_identifier_over_real_sql(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.bind_identifier(
            PRINCIPAL_A, ALICE, _an_email("xid_aaaa0001aaaa0001", ALICE, "alice@example.test", True)
        )
    with migrated_engine.connect() as connection:
        answer = EntityResolutionService(SqlEntityRepository(connection)).resolve(
            PRINCIPAL_A,
            ResolutionRequest(
                raw_reference="Alice@Example.TEST",
                namespace=ExternalIdentifierNamespace.EMAIL,
            ),
        )
    assert answer.outcome is ResolutionOutcome.RESOLVED_EXACT
    assert answer.resolved_entity_id == ALICE
    assert answer.candidates[0].strongest_basis is ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER


def test_resolution_refuses_two_people_who_share_a_name_over_real_sql(
    migrated_engine: Engine,
) -> None:
    """The false join, attempted against the store that would have to hold it."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.create(an_entity(BOB, PRINCIPAL_A, "Alice Synthetic"))
    with migrated_engine.connect() as connection:
        answer = EntityResolutionService(SqlEntityRepository(connection)).resolve(
            PRINCIPAL_A, ResolutionRequest(raw_reference="Alice Synthetic")
        )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert {candidate.entity_id for candidate in answer.candidates} == {ALICE, BOB}
    assert ResolutionWarning.SEVERAL_ENTITIES_SHARE_THIS_NAME in answer.warnings


def test_resolution_stops_on_a_conflicted_identifier_over_real_sql(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(ALICE, PRINCIPAL_A, "Alice Synthetic"))
        repository.create(an_entity(BOB, PRINCIPAL_A, "Bob Synthetic"))
        for identifier_id, entity_id in (
            ("xid_aaaa0001aaaa0001", ALICE),
            ("xid_bbbb0002bbbb0002", BOB),
        ):
            repository.bind_identifier(
                PRINCIPAL_A,
                entity_id,
                _an_email(identifier_id, entity_id, "shared@example.test", True),
            )
    with migrated_engine.connect() as connection:
        answer = EntityResolutionService(SqlEntityRepository(connection)).resolve(
            PRINCIPAL_A,
            ResolutionRequest(
                raw_reference="shared@example.test",
                namespace=ExternalIdentifierNamespace.EMAIL,
            ),
        )
    assert answer.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER
    assert answer.resolved_entity_id is None


def test_resolution_cannot_cross_the_partition_over_real_sql(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(an_entity(BOB, PRINCIPAL_B, "Bob Synthetic"))
        repository.bind_identifier(
            PRINCIPAL_B,
            BOB,
            ExternalIdentifier(
                identifier_id="xid_bbbb0002bbbb0002",
                entity_id=BOB,
                namespace=ExternalIdentifierNamespace.EMAIL,
                normalized_value="bob@example.test",
                display_value="bob@example.test",
                principal_id=PRINCIPAL_B,
                verified=True,
            ),
        )
    with migrated_engine.connect() as connection:
        answer = EntityResolutionService(SqlEntityRepository(connection)).resolve(
            PRINCIPAL_A,
            ResolutionRequest(
                raw_reference="bob@example.test", namespace=ExternalIdentifierNamespace.EMAIL
            ),
        )
    assert answer.outcome is ResolutionOutcome.NOT_FOUND
