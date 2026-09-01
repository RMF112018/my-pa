"""`EntityRecordFamilyService` against real PostgreSQL (RI-ENT-WP-08, service tier).

The repository tier already has its own database module for these six families,
and the service has its own unit module against the in-memory double. This one
holds only what neither of those can decide — the properties that exist because
a real schema is underneath the service's *ordering*:

* **The active partial uniques.** A correction is two statements, and the order
  the service issues them in (write the successor, then supersede the
  predecessor) is a claim about what the database will accept in between.
  `an_active_entity_name_has_one_preferred_per_type` is a unique index over
  `(principal_id, entity_id, name_type_code) WHERE state = 'active' AND
  is_preferred = true`, and a unique *index* is not deferrable: whatever is true
  between the two statements is checked at the first one. A double with no
  indexes cannot see this at all.
* **A real optimistic-version conflict.** Two corrections built from the same
  read, the second one refused by the guarded `UPDATE`'s own `rowcount` rather
  than by a version this service re-read for itself.
* **A composite foreign key the assertion write has to satisfy.**
  `an_assertion_names_a_name_of_its_principal` references
  `entity_names (entity_name_id, principal_id)`, so an assertion the service
  attaches is only writable if the row it names was genuinely written first, by
  this Principal. That the key is real — and therefore that the passing case
  means something — is proved by an assertion naming a row that does not exist.
* **A released preferred slot.** A retirement through the service has to leave
  the partial unique free for the next preferred row, which is a fact about
  `state` and `is_preferred` together rather than about either alone.

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
from sqlalchemy import Connection, Engine, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.application.entity_record_families import (
    CorrectCommunicationMethod,
    CorrectEntityAddress,
    CorrectEntityName,
    EntityRecordFamilyService,
    RecordAffiliation,
    RecordCommunicationMethod,
    RecordEntityAddress,
    RecordEntityName,
    RecordOrganizationProfile,
    RecordProjectParticipation,
    RetireCommunicationMethod,
    RetireEntityAddress,
    RetireEntityName,
    ReviseOrganizationProfile,
    StatedAssertion,
    StatedEvidence,
)
from my_pa.application.errors import ErrorCode, InvalidRequestError, SafeDetail
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    Entity,
    EntityAddressState,
    EntityCommunicationMethodState,
    EntityNameState,
    EntityStatus,
    EntityType,
    LegalIdentityStatusCode,
    NameTypeCode,
    OrganizationKindCode,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    StaleDirectedVersionError,
)
from my_pa.domain.relationship.governance import (
    DEFAULT_MUTATION_AUTHORITY,
    AssertionStatus,
    EntityObservation,
    EvidenceRole,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.tables import (
    entity_assertion_evidence,
    entity_assertions,
    entity_names,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_entity_record_family_service_write_path_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"

PERSON: Final = "ent_aaaa0001aaaa0001"
ORGANIZATION: Final = "ent_bbbb0002bbbb0002"
PROJECT: Final = "ent_cccc0003cccc0003"

WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
LATER_STILL: Final = WHEN + timedelta(hours=2)

ABSENT_NAME: Final = "enam_ffff0009ffff0009"
ABSENT_ASSERTION: Final = "east_ffff0009ffff0009"
OBSERVATION: Final = "eobs_aaaa0001aaaa0001"
SOURCE: Final = "src_aaaa0001aaaa0001"
SOURCE_OBJECT: Final = "obj_aaaa0001aaaa0001"
SOURCE_VERSION: Final = "ver_aaaa0001aaaa0001"


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


def _entity(entity_id: str, name: str, entity_type: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL_A,
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
    """A person, an organization, a project, and one observation for an evidence
    row to cite -- and nothing else. Every record family row this module reads
    back was written by the service under test.

    The observation is here because `assertion_evidence_cites_an_observation_of_
    its_principal` is a composite foreign key into `entity_observations`, so
    evidence the service attaches is only writable against something that
    genuinely exists. Staged rather than written by the service, because the
    observation plane is not one of the six families this service writes."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, _entity(PERSON, "Alice Synthetic", EntityType.PERSON))
        repository.create(
            PRINCIPAL_A, _entity(ORGANIZATION, "Synthetic Org", EntityType.ORGANIZATION)
        )
        repository.create(PRINCIPAL_A, _entity(PROJECT, "Harbour Tower", EntityType.PROJECT))
        repository.record_observation(
            PRINCIPAL_A,
            EntityObservation(
                observation_id=OBSERVATION,
                principal_id=PRINCIPAL_A,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="Synthetic Org LLC",
                normalized_value=normalize_name("Synthetic Org LLC"),
                source_id=SOURCE,
                source_object_id=SOURCE_OBJECT,
                source_version_id=SOURCE_VERSION,
                observed_at=WHEN,
                recorded_at=WHEN,
                entity_id=ORGANIZATION,
            ),
        )
    return migrated_engine


@pytest.fixture
def service() -> EntityRecordFamilyService:
    return EntityRecordFamilyService()


def _repository(connection: Connection) -> SqlEntityRepository:
    return SqlEntityRepository(connection)


# --- The service reaches a real repository at all ----------------------------


def test_every_family_reaches_a_real_repository_through_the_service(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """One record per family, written through the service rather than assembled
    and handed to the repository, so every column the service populates has to
    satisfy the real table's CHECKs and foreign keys."""
    with staged.begin() as connection:
        repository = _repository(connection)
        service.record_name(
            repository,
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
        service.record_organization_profile(
            repository,
            RecordOrganizationProfile(
                entity_id=ORGANIZATION,
                organization_kind_code=OrganizationKindCode.COMPANY,
                legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
                jurisdiction_code="us-fl",
                registration_identifier="P26000012345",
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
        service.record_address(
            repository,
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="1 Synthetic Way, Springfield",
                line1="1 Synthetic Way",
                city="Springfield",
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
        service.record_communication_method(
            repository,
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Reception@Example.Invalid",
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
        service.record_project_participation(
            repository,
            RecordProjectParticipation(
                project_entity_id=PROJECT,
                participant_entity_id=ORGANIZATION,
                project_display_name="Harbour Tower",
                role_basis_code=RoleBasisCode.CONTRACTUAL,
                stakeholder_side_code=StakeholderSideCode.CONSULTANT,
                stakeholder_class_code=StakeholderClassCode.CORE,
                relationship_status_code=ParticipationStatusCode.ACTIVE,
                role_text="structural engineer of record",
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
        service.record_affiliation(
            repository,
            RecordAffiliation(
                person_entity_id=PERSON,
                affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
                organization_entity_id=ORGANIZATION,
                job_title="Principal Architect",
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )

    with staged.connect() as connection:
        repository = _repository(connection)
        (written_name,) = repository.names(PRINCIPAL_A, ORGANIZATION)
        assert written_name.normalized_value == normalize_name("Synthetic Org LLC")
        assert written_name.name_type_code is NameTypeCode.LEGAL
        profile = repository.organization_profile(PRINCIPAL_A, ORGANIZATION)
        assert profile is not None
        assert profile.jurisdiction_code == "us-fl"
        assert len(repository.addresses(PRINCIPAL_A, ORGANIZATION)) == 1
        assert len(repository.communication_methods(PRINCIPAL_A, ORGANIZATION)) == 1
        (participation,) = repository.project_participations_as_project(PRINCIPAL_A, PROJECT)
        assert participation.role_code is None
        assert participation.role_text == "structural engineer of record"
        (affiliation,) = repository.person_organization_affiliations_as_person(PRINCIPAL_A, PERSON)
        assert affiliation.organization_entity_id == ORGANIZATION


def test_a_profile_revision_through_the_service_clears_a_nullable_column(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """The in-place family, against a real `UPDATE` and a real version guard."""
    with staged.begin() as connection:
        service.record_organization_profile(
            _repository(connection),
            RecordOrganizationProfile(
                entity_id=ORGANIZATION,
                organization_kind_code=OrganizationKindCode.COMPANY,
                legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
                jurisdiction_code="us-fl",
                registration_identifier="P26000012345",
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.begin() as connection:
        service.revise_organization_profile(
            _repository(connection),
            ReviseOrganizationProfile(
                entity_id=ORGANIZATION,
                expected_version=1,
                organization_kind_code=OrganizationKindCode.COMPANY,
                legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
                jurisdiction_code=None,
                registration_identifier=None,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.connect() as connection:
        revised = _repository(connection).organization_profile(PRINCIPAL_A, ORGANIZATION)
    assert revised is not None
    assert revised.jurisdiction_code is None
    assert revised.registration_identifier is None
    assert revised.version == 2


# --- A preferred row cannot be corrected, and the refusal is a schema fact ---
#
# The three families that carry `is_preferred` each hold two constraints a
# correction would have to satisfy at once and cannot, and both are checked per
# statement:
#
# * `an_active_<family>_has_one_preferred_per_type` -- a partial unique INDEX
#   admitting one active preferred row per `(principal_id, entity_id, type)`.
#   Writing the successor first, the order every `correct_*` uses, trips it,
#   because the predecessor has not yet left `state = 'active'`. A unique index
#   cannot be deferred at all; only a unique constraint can.
# * `an_<family>_is_superseded_within_its_principal` -- the self-referencing
#   `(superseded_by_*, principal_id)` foreign key. Superseding first trips that
#   instead, because the successor the supersession names does not exist yet.
#
# So `_refuse_preferred_correction` refuses the command before any write. These
# tests hold three things about that: the refusal happens and nothing is
# written, the two constraints it exists for are real and fire against this live
# schema, and the retire-then-record path a caller has instead actually works --
# together with what that path costs, which is the `superseded_by_*` lineage
# link.


def test_a_preferred_name_correction_is_refused_and_retiring_is_the_path_that_works(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """Refused before any write, and then the documented alternative, end to end.

    The row count and the predecessor's `version`, `state` and `is_preferred`
    are read back after the refusal: a service that wrote the successor and
    *then* refused would raise the same exception and fail here.

    `SafeDetail.PINNED` is a documented approximation rather than a precise
    token -- `errors.py` carries no `is_preferred` member and is outside this
    work package's scope -- so a later, more precise token replacing it is a
    correction and not a regression.
    """
    with staged.begin() as connection:
        recorded = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )

    with pytest.raises(InvalidRequestError) as refused, staged.begin() as connection:
        service.correct_name(
            _repository(connection),
            CorrectEntityName(
                entity_name_id=recorded.record_id,
                expected_version=1,
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert refused.value.safe_details == (SafeDetail.PINNED,)

    with staged.connect() as connection:
        untouched = _repository(connection).names(PRINCIPAL_A, ORGANIZATION)
    assert [row.entity_name_id for row in untouched] == [recorded.record_id]
    assert untouched[0].version == 1
    assert untouched[0].state is EntityNameState.ACTIVE
    assert untouched[0].is_preferred is True
    assert untouched[0].display_value == "Synthetic Org LLC"
    assert untouched[0].superseded_by_entity_name_id is None

    with staged.begin() as connection:
        service.retire_name(
            _repository(connection),
            RetireEntityName(entity_name_id=recorded.record_id, expected_version=1),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        replacement = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )
    with staged.connect() as connection:
        rows = {
            row.entity_name_id: row
            for row in _repository(connection).names(PRINCIPAL_A, ORGANIZATION)
        }
    predecessor = rows[recorded.record_id]
    assert predecessor.state is EntityNameState.RETIRED
    assert predecessor.state is not EntityNameState.SUPERSEDED
    assert predecessor.is_preferred is False
    assert predecessor.retired_at == LATER
    assert rows[replacement.record_id].is_preferred is True
    # The cost the refusal's own docstring names out loud: retirement writes no
    # lineage. A reader following the supersession chain from the retired row
    # will not arrive at its replacement, because no column relates them.
    assert {row.superseded_by_entity_name_id for row in rows.values()} == {None}


def test_a_preferred_address_correction_is_refused_and_retiring_is_the_path_that_works(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """`an_active_entity_address_has_one_preferred_per_type` and
    `an_entity_address_is_superseded_within_its_principal`, same shape and same
    arc as the name case above."""
    with staged.begin() as connection:
        recorded = service.record_address(
            _repository(connection),
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="1 Synthetic Way, Springfield",
                line1="1 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )

    with pytest.raises(InvalidRequestError) as refused, staged.begin() as connection:
        service.correct_address(
            _repository(connection),
            CorrectEntityAddress(
                entity_address_id=recorded.record_id,
                expected_version=1,
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="2 Synthetic Way, Springfield",
                line1="2 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert refused.value.safe_details == (SafeDetail.PINNED,)

    with staged.connect() as connection:
        untouched = _repository(connection).addresses(PRINCIPAL_A, ORGANIZATION)
    assert [row.entity_address_id for row in untouched] == [recorded.record_id]
    assert untouched[0].version == 1
    assert untouched[0].state is EntityAddressState.ACTIVE
    assert untouched[0].is_preferred is True
    assert untouched[0].raw_value == "1 Synthetic Way, Springfield"
    assert untouched[0].superseded_by_entity_address_id is None

    with staged.begin() as connection:
        service.retire_address(
            _repository(connection),
            RetireEntityAddress(entity_address_id=recorded.record_id, expected_version=1),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        replacement = service.record_address(
            _repository(connection),
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="2 Synthetic Way, Springfield",
                line1="2 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )
    with staged.connect() as connection:
        rows = {
            row.entity_address_id: row
            for row in _repository(connection).addresses(PRINCIPAL_A, ORGANIZATION)
        }
    assert rows[recorded.record_id].state is EntityAddressState.RETIRED
    assert rows[recorded.record_id].is_preferred is False
    assert rows[replacement.record_id].is_preferred is True
    assert {row.superseded_by_entity_address_id for row in rows.values()} == {None}


def test_a_preferred_channel_correction_is_refused_and_retiring_is_the_path_that_works(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """`an_active_communication_method_has_one_preferred_per_type` and
    `a_communication_method_is_superseded_within_its_principal`, same again."""
    with staged.begin() as connection:
        recorded = service.record_communication_method(
            _repository(connection),
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Reception@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )

    with pytest.raises(InvalidRequestError) as refused, staged.begin() as connection:
        service.correct_communication_method(
            _repository(connection),
            CorrectCommunicationMethod(
                communication_method_id=recorded.record_id,
                expected_version=1,
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Desk@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert refused.value.safe_details == (SafeDetail.PINNED,)

    with staged.connect() as connection:
        untouched = _repository(connection).communication_methods(PRINCIPAL_A, ORGANIZATION)
    assert [row.communication_method_id for row in untouched] == [recorded.record_id]
    assert untouched[0].version == 1
    assert untouched[0].state is EntityCommunicationMethodState.ACTIVE
    assert untouched[0].is_preferred is True
    assert untouched[0].display_value == "Reception@Example.Invalid"
    assert untouched[0].superseded_by_communication_method_id is None

    with staged.begin() as connection:
        service.retire_communication_method(
            _repository(connection),
            RetireCommunicationMethod(
                communication_method_id=recorded.record_id, expected_version=1
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        replacement = service.record_communication_method(
            _repository(connection),
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Desk@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )
    with staged.connect() as connection:
        rows = {
            row.communication_method_id: row
            for row in _repository(connection).communication_methods(PRINCIPAL_A, ORGANIZATION)
        }
    assert rows[recorded.record_id].state is EntityCommunicationMethodState.RETIRED
    assert rows[recorded.record_id].is_preferred is False
    assert rows[replacement.record_id].is_preferred is True
    assert {row.superseded_by_communication_method_id for row in rows.values()} == {None}


def test_a_preferred_correction_answers_with_a_refusal_and_not_a_driver_error(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """The actual improvement, locked. Before the refusal existed the caller got
    a `psycopg` `UniqueViolation` wrapped in `sqlalchemy.exc.IntegrityError` out
    of the repository -- an opaque driver error naming an index. Now it gets a
    stable application refusal, raised before any statement runs.

    Both are admitted by `pytest.raises` and then the type is asserted, so
    removing the refusal does not merely change which exception is caught: the
    test goes red on the exception it gets back. The empty `__cause__` and
    `__context__` are what say the refusal was *raised*, not translated from a
    driver error that had already happened."""
    with staged.begin() as connection:
        recorded = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with (
        pytest.raises((InvalidRequestError, IntegrityError)) as raised,
        staged.begin() as connection,
    ):
        service.correct_name(
            _repository(connection),
            CorrectEntityName(
                entity_name_id=recorded.record_id,
                expected_version=1,
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert type(raised.value) is InvalidRequestError
    assert raised.value.code is ErrorCode.INVALID_REQUEST
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_the_names_one_preferred_partial_unique_is_real(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """The anti-vacuity half. Two ACTIVE preferred names of one type for one
    entity are refused by the index against this live schema, so the refusal
    above is guarding a rule that exists rather than an imaginary one."""
    with staged.begin() as connection:
        service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert "an_active_entity_name_has_one_preferred_per_type" in str(violated.value)


def test_the_addresses_one_preferred_partial_unique_is_real(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    with staged.begin() as connection:
        service.record_address(
            _repository(connection),
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="1 Synthetic Way, Springfield",
                line1="1 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        service.record_address(
            _repository(connection),
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="2 Synthetic Way, Springfield",
                line1="2 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert "an_active_entity_address_has_one_preferred_per_type" in str(violated.value)


def test_the_channels_one_preferred_partial_unique_is_real(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    with staged.begin() as connection:
        service.record_communication_method(
            _repository(connection),
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Reception@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        service.record_communication_method(
            _repository(connection),
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Desk@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    assert "an_active_communication_method_has_one_preferred_per_type" in str(violated.value)


#: The three named self-referencing `(superseded_by_*, principal_id)` foreign
#: keys the other horn of the refusal is about. Each column additionally carries
#: the single-column key its own `REFERENCES` clause created, which the query
#: below finds as well and which is why that query matches on the column rather
#: than on this list.
SUPERSESSION_FOREIGN_KEYS: Final = (
    "an_entity_name_is_superseded_within_its_principal",
    "an_entity_address_is_superseded_within_its_principal",
    "a_communication_method_is_superseded_within_its_principal",
)

#: The three tables that carry a `superseded_by_*` column and a preferred slot.
SUPERSEDING_TABLES: Final = (
    "entity_names",
    "entity_addresses",
    "entity_communication_methods",
)


def test_no_supersession_foreign_key_is_deferrable(staged: Engine) -> None:
    """The second horn, read off the live catalogue rather than off a migration
    file. "Supersede first, then write the successor" would be a way out only if
    these could be postponed to commit; `pg_constraint.condeferrable` says they
    cannot, so the successor has to exist before any row names it.

    Matched by column rather than by name, so the single-column keys the three
    `REFERENCES` clauses created are covered too -- a deferrable key added to one
    of these columns under any name would redden here."""
    with staged.connect() as connection:
        found = connection.execute(
            text(
                "SELECT c.conname, c.condeferrable, c.condeferred "
                "FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                "WHERE c.contype = 'f' AND t.relname = ANY(:tables) "
                "AND pg_get_constraintdef(c.oid) LIKE '%superseded_by%'"
            ),
            {"tables": list(SUPERSEDING_TABLES)},
        ).all()
    assert set(SUPERSESSION_FOREIGN_KEYS) <= {row.conname for row in found}
    # Two per column: the composite named one and the single-column one the
    # column's own `REFERENCES` clause created.
    assert len(found) == 6
    assert [row.condeferrable for row in found] == [False] * 6
    assert [row.condeferred for row in found] == [False] * 6


def test_a_supersession_naming_an_absent_successor_is_refused_at_the_statement(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """The behavioural half of the claim above, for the family the other two are
    declared identically to. The `UPDATE` naming a successor that does not exist
    raises where it is issued, inside an open transaction and before any commit
    -- which is what "checked per statement" means and why superseding first is
    not an ordering the service could have chosen instead.

    The assertion names the column, not one constraint: two foreign keys guard
    it -- the composite `an_entity_name_is_superseded_within_its_principal` and
    the single-column key its own `REFERENCES` clause created -- and PostgreSQL
    reports whichever it happens to check first. Either firing is the same
    fact."""
    with staged.begin() as connection:
        recorded = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError) as violated:
            _repository(connection).supersede_entity_name(
                PRINCIPAL_A,
                entity_name_id=recorded.record_id,
                superseded_by_entity_name_id=ABSENT_NAME,
                expected_version=1,
                at=LATER,
            )
        transaction.rollback()
    detail = str(violated.value)
    assert "ForeignKeyViolation" in detail
    assert "superseded_by_entity_name_id" in detail


def test_a_retired_row_cannot_also_name_a_successor(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """Why retire-then-record costs the lineage link, as a schema fact rather
    than a service choice. `an_entity_name_names_a_successor_only_when_superseded`
    admits `superseded_by_entity_name_id` only on a row whose `state` is
    `superseded`, so a retired predecessor cannot carry a pointer to its
    replacement even if a later writer wanted to add one. The cost the refusal
    documents is therefore structural, and the three tests above assert an
    absence the database is enforcing rather than one the service merely
    happens to leave."""
    with staged.begin() as connection:
        retired = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.begin() as connection:
        replacement = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        service.retire_name(
            _repository(connection),
            RetireEntityName(entity_name_id=retired.record_id, expected_version=1),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError) as violated:
            connection.execute(
                update(entity_names)
                .where(entity_names.c.entity_name_id == retired.record_id)
                .values(superseded_by_entity_name_id=replacement.record_id)
            )
        transaction.rollback()
    assert "an_entity_name_names_a_successor_only_when_superseded" in str(violated.value)


# --- A real optimistic-version conflict --------------------------------------


def test_a_second_correction_built_from_the_same_read_is_refused(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """Two corrections composed against the same observed version. The first
    commits and moves the row to version 2; the second is refused by the guarded
    `UPDATE`'s own `rowcount`, not by a version this service re-read for itself.

    Serialized rather than threaded on purpose: the two writes contend for the
    same row lock, so a genuinely concurrent second call would block until the
    first committed and would then evaluate exactly this predicate against
    exactly this row. Threading the test would add a scheduler to the evidence
    without adding a fact to it."""
    with staged.begin() as connection:
        recorded = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )

    def _correction(display_value: str) -> CorrectEntityName:
        return CorrectEntityName(
            entity_name_id=recorded.record_id,
            expected_version=1,
            entity_id=ORGANIZATION,
            display_value=display_value,
            name_type_code=NameTypeCode.LEGAL,
        )

    with staged.begin() as connection:
        service.correct_name(
            _repository(connection),
            _correction("Synthetic Org Holdings LLC"),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with pytest.raises(StaleDirectedVersionError), staged.begin() as connection:
        service.correct_name(
            _repository(connection),
            _correction("Synthetic Org Group LLC"),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )

    with staged.connect() as connection:
        rows = _repository(connection).names(PRINCIPAL_A, ORGANIZATION)
    predecessor = next(row for row in rows if row.entity_name_id == recorded.record_id)
    assert predecessor.state is EntityNameState.SUPERSEDED
    assert predecessor.version == 2
    assert {row.display_value for row in rows} == {
        "Synthetic Org LLC",
        "Synthetic Org Holdings LLC",
    }


# --- The assertion's composite foreign key -----------------------------------


def test_an_assertion_the_service_attached_satisfies_the_composite_foreign_key(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """`an_assertion_names_a_name_of_its_principal` references
    `entity_names (entity_name_id, principal_id)`. The assertion is written in
    the same statement sequence as the row it names, after it, so the key
    resolves -- and the evidence row resolves to the assertion in turn."""
    with staged.begin() as connection:
        recorded = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
                assertion=StatedAssertion(
                    assertion_status=AssertionStatus.BEST_SUPPORTED,
                    predicate_code="display_value",
                    evidence=(
                        StatedEvidence(
                            role=EvidenceRole.COUNTEREVIDENCE,
                            entity_observation_id=OBSERVATION,
                        ),
                    ),
                ),
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    assert recorded.assertion_id is not None
    assert len(recorded.evidence_ids) == 1

    with staged.connect() as connection:
        repository = _repository(connection)
        held = repository.assertion(PRINCIPAL_A, recorded.assertion_id)
        cited = repository.assertion_evidence(PRINCIPAL_A, recorded.assertion_id)
    assert held is not None
    assert held.target_entity_name_id == recorded.record_id
    assert held.assertion_status is AssertionStatus.BEST_SUPPORTED
    assert held.asserted_by is DEFAULT_MUTATION_AUTHORITY
    assert [row.role for row in cited] == [EvidenceRole.COUNTEREVIDENCE]
    assert [row.evidence_id for row in cited] == list(recorded.evidence_ids)


def test_the_assertions_composite_foreign_key_is_real(staged: Engine) -> None:
    """The anti-vacuity half. An assertion naming a name row that does not exist
    is refused by the database, so the test above is a fact about the service
    having written the row first rather than about an unenforced column."""
    with pytest.raises(IntegrityError), staged.begin() as connection:
        connection.execute(
            insert(entity_assertions).values(
                assertion_id=ABSENT_ASSERTION,
                principal_id=PRINCIPAL_A,
                assertion_status=AssertionStatus.UNRESOLVED.value,
                asserted_by=DEFAULT_MUTATION_AUTHORITY.value,
                created_at=WHEN,
                target_entity_name_id=ABSENT_NAME,
                state="active",
                version=1,
            )
        )


def test_a_command_carrying_no_assertion_writes_no_assertion_row(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """Counted against the real tables: "no error was raised" and "nothing was
    written" are different facts, and only the second is the claim."""
    with staged.begin() as connection:
        service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.connect() as connection:
        assertions = connection.execute(select(entity_assertions.c.assertion_id)).scalars().all()
        evidence = (
            connection.execute(select(entity_assertion_evidence.c.evidence_id)).scalars().all()
        )
    assert list(assertions) == []
    assert list(evidence) == []


# --- A retirement releases the preferred slot the schema is guarding ---------


def test_retiring_a_name_through_the_service_releases_the_preferred_slot(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    """A retirement has to leave the partial unique free for the next preferred
    row. That is a fact about `state` and `is_preferred` together: leaving
    `is_preferred` set would still release the index through `state` alone, and
    a reader of the retired row would then be told the entity still prefers a
    name it has withdrawn."""
    with staged.begin() as connection:
        recorded = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.begin() as connection:
        service.retire_name(
            _repository(connection),
            RetireEntityName(entity_name_id=recorded.record_id, expected_version=1),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        successor = service.record_name(
            _repository(connection),
            RecordEntityName(
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )
    with staged.connect() as connection:
        rows = {
            row.entity_name_id: row
            for row in _repository(connection).names(PRINCIPAL_A, ORGANIZATION)
        }
    retired = rows[recorded.record_id]
    assert retired.state is EntityNameState.RETIRED
    assert retired.is_preferred is False
    assert retired.retired_at == LATER
    assert rows[successor.record_id].is_preferred is True


def test_retiring_an_address_through_the_service_releases_the_preferred_slot(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    with staged.begin() as connection:
        recorded = service.record_address(
            _repository(connection),
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="1 Synthetic Way, Springfield",
                line1="1 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.begin() as connection:
        service.retire_address(
            _repository(connection),
            RetireEntityAddress(entity_address_id=recorded.record_id, expected_version=1),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        successor = service.record_address(
            _repository(connection),
            RecordEntityAddress(
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="2 Synthetic Way, Springfield",
                line1="2 Synthetic Way",
                city="Springfield",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )
    with staged.connect() as connection:
        rows = {
            row.entity_address_id: row
            for row in _repository(connection).addresses(PRINCIPAL_A, ORGANIZATION)
        }
    assert rows[recorded.record_id].state is EntityAddressState.RETIRED
    assert rows[recorded.record_id].is_preferred is False
    assert rows[successor.record_id].is_preferred is True


def test_retiring_a_channel_through_the_service_releases_the_preferred_slot(
    staged: Engine, service: EntityRecordFamilyService
) -> None:
    with staged.begin() as connection:
        recorded = service.record_communication_method(
            _repository(connection),
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Reception@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=WHEN,
        )
    with staged.begin() as connection:
        service.retire_communication_method(
            _repository(connection),
            RetireCommunicationMethod(
                communication_method_id=recorded.record_id, expected_version=1
            ),
            principal_id=PRINCIPAL_A,
            at=LATER,
        )
    with staged.begin() as connection:
        successor = service.record_communication_method(
            _repository(connection),
            RecordCommunicationMethod(
                entity_id=ORGANIZATION,
                method_type_code=CommunicationMethodTypeCode.EMAIL,
                usage_context_code=CommunicationUsageContextCode.CORPORATE,
                display_value="Desk@Example.Invalid",
                is_preferred=True,
            ),
            principal_id=PRINCIPAL_A,
            at=LATER_STILL,
        )
    with staged.connect() as connection:
        rows = {
            row.communication_method_id: row
            for row in _repository(connection).communication_methods(PRINCIPAL_A, ORGANIZATION)
        }
    assert rows[recorded.record_id].state is EntityCommunicationMethodState.RETIRED
    assert rows[recorded.record_id].is_preferred is False
    assert rows[successor.record_id].is_preferred is True
