"""`entity_assertions`/`entity_assertion_evidence` against real PostgreSQL
(RI-ENT-WP-07).

`tests/unit/test_entity_assertion_domain.py` proves the dataclasses refuse a
bad value; `tests/schema/test_entity_assertion_provenance_migration.py`
proves the server refuses it too, and that every constraint name matches the
`tables.py` declaration. This module proves the record works end-to-end
against a live database: writes and reads through `SqlEntityRepository`'s new
helpers for all six target families, non-destructive supersession (the audit's
own "no destructive replacement" requirement, proven rather than asserted),
Principal-partitioned reads, and RULING 2's two merge/split claims --

* the organization-profile branch's `ON UPDATE CASCADE` FK actually follows a
  real merge's reparenting `UPDATE`;
* the other five branches' composite-FK references (by the target row's own
  stable surrogate key) stay resolvable, unmodified, after a merge reparents
  the *entity_id* on the row they point at.

Every identity here is synthetic and every address is `example.invalid`.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, insert, text
from sqlalchemy.engine import make_url

from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    ActorClass,
    AssertionStatus,
    EntityAssertion,
    EntityAssertionEvidence,
    EvidenceRole,
    MutationAuthority,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository
from my_pa.infrastructure.persistence.tables import (
    entity_addresses,
    entity_communication_methods,
    entity_names,
    entity_observations,
    entity_organization_profiles,
    entity_person_organization_affiliations,
    entity_project_participations,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_entity_assertion_provenance_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

PERSON: Final = "ent_aaaa0001aaaa0001"
ORGANIZATION: Final = "ent_bbbb0002bbbb0002"
PROJECT: Final = "ent_cccc0003cccc0003"
SURVIVOR: Final = "ent_dddd0004dddd0004"
MERGED_ONE: Final = "ent_eeee0005eeee0005"

WHEN: Final = datetime(2026, 8, 31, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
OPERATOR: Final = PRINCIPAL_A
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
REASON: Final = "two synthetic records describe one synthetic org"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
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
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _entity(
    entity_id: str,
    name: str,
    entity_type: EntityType,
    *,
    principal_id: str = PRINCIPAL_A,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """A person, an organization, a project, and one seeded row of each of the
    six WP-02-WP-06 target families, all bound to the organization entity
    (addresses/communication methods/names) or to the person/project
    (affiliation/participation) -- plus one observation this module's evidence
    rows cite."""
    with migrated_engine.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(PERSON, "Alice Synthetic", EntityType.PERSON))
        repo.create(PRINCIPAL_A, _entity(ORGANIZATION, "Synthetic Org", EntityType.ORGANIZATION))
        repo.create(PRINCIPAL_A, _entity(PROJECT, "Harbour Tower", EntityType.PROJECT))

        connection.execute(
            insert(entity_names).values(
                entity_name_id="enam_aaaa0001aaaa0001",
                entity_id=ORGANIZATION,
                principal_id=PRINCIPAL_A,
                name_type_code="legal",
                normalized_value=normalize_name("Synthetic Org LLC"),
                display_value="Synthetic Org LLC",
                version=1,
            )
        )
        connection.execute(
            insert(entity_addresses).values(
                entity_address_id="eadr_aaaa0001aaaa0001",
                entity_id=ORGANIZATION,
                principal_id=PRINCIPAL_A,
                address_type_code="headquarters",
                raw_value="123 Main St, Springfield",
                normalized_address_value="123 main st, springfield",
                version=1,
            )
        )
        connection.execute(
            insert(entity_communication_methods).values(
                communication_method_id="ecmm_aaaa0001aaaa0001",
                entity_id=ORGANIZATION,
                principal_id=PRINCIPAL_A,
                method_type_code="email",
                usage_context_code="corporate",
                normalized_value="synthetic@example.invalid",
                display_value="synthetic@example.invalid",
                version=1,
            )
        )
        connection.execute(
            insert(entity_project_participations).values(
                participation_id="eppt_aaaa0001aaaa0001",
                principal_id=PRINCIPAL_A,
                project_entity_id=PROJECT,
                participant_entity_id=ORGANIZATION,
                project_display_name="Synthetic Participant",
                role_basis_code="contractual",
                stakeholder_side_code="consultant",
                stakeholder_class_code="core",
                relationship_status_code="active",
                version=1,
            )
        )
        connection.execute(
            insert(entity_person_organization_affiliations).values(
                affiliation_id="poaf_aaaa0001aaaa0001",
                principal_id=PRINCIPAL_A,
                person_entity_id=PERSON,
                organization_entity_id=ORGANIZATION,
                affiliation_type_code="employment",
                version=1,
            )
        )
        connection.execute(
            insert(entity_organization_profiles).values(
                entity_id=ORGANIZATION,
                principal_id=PRINCIPAL_A,
                organization_kind_code="company",
                legal_identity_status_code="unresolved",
                version=1,
            )
        )
        connection.execute(
            insert(entity_observations).values(
                observation_id="eobs_aaaa0001aaaa0001",
                principal_id=PRINCIPAL_A,
                kind="document_mention",
                observed_value="Synthetic Org LLC",
                normalized_value=normalize_name("Synthetic Org LLC"),
                source_id="src_aaaa0001aaaa0001",
                source_object_id="obj_aaaa0001aaaa0001",
                source_version_id="ver_aaaa0001aaaa0001",
                observed_at=WHEN,
                recorded_at=WHEN,
                entity_id=ORGANIZATION,
            )
        )
    return migrated_engine


TARGET_CASES: Final = (
    ("target_entity_name_id", "enam_aaaa0001aaaa0001", "east_target0001aaaa0001"),
    ("target_entity_address_id", "eadr_aaaa0001aaaa0001", "east_target0002aaaa0001"),
    ("target_communication_method_id", "ecmm_aaaa0001aaaa0001", "east_target0003aaaa0001"),
    ("target_participation_id", "eppt_aaaa0001aaaa0001", "east_target0004aaaa0001"),
    ("target_affiliation_id", "poaf_aaaa0001aaaa0001", "east_target0005aaaa0001"),
    ("target_organization_profile_entity_id", ORGANIZATION, "east_target0006aaaa0001"),
)


@pytest.mark.parametrize(("field", "target_id", "assertion_id"), TARGET_CASES)
def test_an_assertion_round_trips_against_each_of_the_six_targets(
    staged: Engine, field: str, target_id: str, assertion_id: str
) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        assertion = EntityAssertion(
            assertion_id=assertion_id,
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            predicate_code="a_synthetic_field",
            **{field: target_id},  # type: ignore[arg-type]
        )
        repo.record_assertion(PRINCIPAL_A, assertion)
        read_back = repo.assertion(PRINCIPAL_A, assertion.assertion_id)
    assert read_back == assertion


def test_recording_an_assertion_for_a_different_principal_is_refused(staged: Engine) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        assertion = EntityAssertion(
            assertion_id="east_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_entity_name_id="enam_aaaa0001aaaa0001",
        )
        with pytest.raises(ValueError, match="belongs to the acting Principal"):
            repo.record_assertion(PRINCIPAL_B, assertion)


# --- non-destructive supersession -------------------------------------------


def test_superseding_an_assertion_leaves_the_old_row_and_its_evidence_intact(
    staged: Engine,
) -> None:
    """The audit's own "no destructive replacement" requirement, proven, not
    just asserted. The old row's every column other than
    `state`/`assertion_status`/`version`/`updated_at` is byte-identical to
    what it was before the supersession, and the evidence row that cited it
    is still present, unmodified, and still resolves."""
    old_id = "east_aaaa0001aaaa0001"
    new_id = "east_bbbb0002bbbb0002"
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        old = EntityAssertion(
            assertion_id=old_id,
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_entity_name_id="enam_aaaa0001aaaa0001",
            predicate_code="display_value",
            rationale="a synthetic source document names this value",
        )
        repo.record_assertion(PRINCIPAL_A, old)
        evidence = EntityAssertionEvidence(
            evidence_id="easev_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            assertion_id=old_id,
            role=EvidenceRole.DIRECT,
            created_at=WHEN,
            entity_observation_id="eobs_aaaa0001aaaa0001",
        )
        repo.record_assertion_evidence(PRINCIPAL_A, evidence)

    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        new = EntityAssertion(
            assertion_id=new_id,
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.VERIFIED,
            asserted_by=MutationAuthority.REVIEW_ACCEPTED,
            created_at=LATER,
            target_entity_name_id="enam_aaaa0001aaaa0001",
            predicate_code="display_value",
            supersedes_assertion_id=old_id,
        )
        repo.record_assertion(PRINCIPAL_A, new)
        repo.supersede_assertion(
            PRINCIPAL_A,
            assertion_id=old_id,
            superseded_by_assertion_id=new_id,
            expected_version=1,
            at=LATER,
        )

    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        after = repo.assertion(PRINCIPAL_A, old_id)
        assert after is not None
        assert after.state.value == "superseded"
        assert after.assertion_status is AssertionStatus.SUPERSEDED
        assert after.version == 2
        assert after.updated_at == LATER
        # Everything else is untouched.
        assert after.target_entity_name_id == old.target_entity_name_id
        assert after.predicate_code == old.predicate_code
        assert after.rationale == old.rationale
        assert after.asserted_by == old.asserted_by
        assert after.created_at == old.created_at

        # The evidence row is present, unmodified, and still resolves.
        still_there = repo.assertion_evidence(PRINCIPAL_A, old_id)
        assert still_there == [evidence]


def test_superseding_names_a_version_conflict_when_stale(staged: Engine) -> None:
    from my_pa.contracts.ports import UnknownScopeError

    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        old = EntityAssertion(
            assertion_id="east_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_entity_name_id="enam_aaaa0001aaaa0001",
        )
        repo.record_assertion(PRINCIPAL_A, old)
        with pytest.raises(UnknownScopeError):
            repo.supersede_assertion(
                PRINCIPAL_A,
                assertion_id=old.assertion_id,
                superseded_by_assertion_id="east_bbbb0002bbbb0002",
                expected_version=99,
                at=LATER,
            )


# --- Principal partition isolation -------------------------------------------


def test_reads_are_partitioned_by_principal(staged: Engine) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        assertion = EntityAssertion(
            assertion_id="east_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_entity_name_id="enam_aaaa0001aaaa0001",
        )
        repo.record_assertion(PRINCIPAL_A, assertion)

    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        assert repo.assertion(PRINCIPAL_B, assertion.assertion_id) is None
        assert (
            repo.assertions_targeting(PRINCIPAL_B, target_entity_name_id="enam_aaaa0001aaaa0001")
            == []
        )


# --- RULING 2: the organization-profile branch's ON UPDATE CASCADE ----------


def _service(connection: Connection) -> IdentityCorrectionService:
    return IdentityCorrectionService(
        SqlEntityRepository(connection), SqlRelationshipMemoryRepository(connection)
    )


def test_an_assertion_bound_to_an_organization_profile_follows_the_profile_through_a_merge(
    migrated_engine: Engine,
) -> None:
    """RULING 2, path (a), proven rather than assumed: a real merge that
    reparents an organization profile (a literal `UPDATE ... SET entity_id =
    :survivor WHERE entity_id IN (:merged_away)`) carries an assertion's
    `target_organization_profile_entity_id` along automatically, because that
    column is a genuine FK with `ON UPDATE CASCADE`."""
    with migrated_engine.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(SURVIVOR, "Survivor Org", EntityType.ORGANIZATION))
        repo.create(PRINCIPAL_A, _entity(MERGED_ONE, "Merged-Away Org", EntityType.ORGANIZATION))
        connection.execute(
            insert(entity_organization_profiles).values(
                entity_id=MERGED_ONE,
                principal_id=PRINCIPAL_A,
                organization_kind_code="company",
                legal_identity_status_code="unresolved",
                version=1,
            )
        )
        assertion = EntityAssertion(
            assertion_id="east_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_organization_profile_entity_id=MERGED_ONE,
            predicate_code="organization_kind_code",
        )
        repo.record_assertion(PRINCIPAL_A, assertion)

    with migrated_engine.begin() as connection:
        preview = _service(connection).preview(
            MergePreviewCommand(
                principal_id=PRINCIPAL_A,
                survivor_entity_id=SURVIVOR,
                expected_survivor_version=1,
                merged_away=((MERGED_ONE, 1),),
                reason=REASON,
            ),
            at=WHEN,
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with migrated_engine.begin() as connection:
        _service(connection).apply(
            MergeCommand(
                principal_id=PRINCIPAL_A,
                preview_id=preview.preview.preview_id,
                preview_digest=preview.preview.preview_digest,
                idempotency_key="merge-assertion-org-profile",
                reason=REASON,
                choices=(),
            ),
            at=WHEN,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )

    with migrated_engine.connect() as connection:
        repo = SqlEntityRepository(connection)
        after = repo.assertion(PRINCIPAL_A, assertion.assertion_id)
    assert after is not None
    assert after.target_organization_profile_entity_id == SURVIVOR


# --- RULING 2: the other five branches stay resolvable via their own PK -----


def test_an_assertion_bound_to_a_name_stays_resolvable_after_the_name_is_reparented(
    staged: Engine,
) -> None:
    """RULING 2's central claim for the five surrogate-key-referencing
    branches, proven for one representative family (`entity_names`; the
    mechanism -- `reparent_entity_reference`'s generic entity-column
    substitution -- is the same generic function for all five, per
    `_ChildSubject`, `src/my_pa/infrastructure/persistence/entity.py`).

    A merge reparents `entity_names.entity_id` on the row an assertion
    targets; the row's own `entity_name_id` (what the assertion actually
    references) is untouched, so the assertion's `target_entity_name_id`
    needs no wiring at all to remain valid -- it still names the same row,
    which now belongs to the survivor.
    """
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(SURVIVOR, "Survivor Org", EntityType.ORGANIZATION))
        assertion = EntityAssertion(
            assertion_id="east_aaaa0001aaaa0001",
            principal_id=PRINCIPAL_A,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=MutationAuthority.USER_CONFIRMED_ASSERTION,
            created_at=WHEN,
            target_entity_name_id="enam_aaaa0001aaaa0001",
            predicate_code="display_value",
        )
        repo.record_assertion(PRINCIPAL_A, assertion)

    with staged.begin() as connection:
        preview = _service(connection).preview(
            MergePreviewCommand(
                principal_id=PRINCIPAL_A,
                survivor_entity_id=SURVIVOR,
                expected_survivor_version=1,
                merged_away=((ORGANIZATION, 1),),
                reason=REASON,
            ),
            at=WHEN,
            requested_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with staged.begin() as connection:
        _service(connection).apply(
            MergeCommand(
                principal_id=PRINCIPAL_A,
                preview_id=preview.preview.preview_id,
                preview_digest=preview.preview.preview_digest,
                idempotency_key="merge-assertion-name",
                reason=REASON,
                choices=(),
            ),
            at=WHEN,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            performed_by=OPERATOR,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )

    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        after = repo.assertion(PRINCIPAL_A, assertion.assertion_id)
        # The assertion's own reference is untouched...
        assert after is not None
        assert after.target_entity_name_id == "enam_aaaa0001aaaa0001"
        # ...and now resolves to a name row bound to the survivor.
        name_row = connection.execute(
            entity_names.select().where(entity_names.c.entity_name_id == "enam_aaaa0001aaaa0001")
        ).one()
    assert name_row.entity_id == SURVIVOR
