"""The six record families' write path against real PostgreSQL (RI-ENT-WP-08).

Every property the earlier work packages deferred on the argument "nothing
writes to these tables yet" becomes load-bearing here, because this is the
work package that writes to them. So this module proves the four things the
audit's WP-08 objective names, each against a live database rather than a
double:

* **Principal scoping** -- a row written by one Principal is unreadable by
  another, and a write handed a record stamped with somebody else's
  `principal_id` is refused before it reaches the database.
* **Lifecycle** -- `record_*` inserts, `supersede_*` marks SUPERSEDED and
  names a successor, `retire_*` marks RETIRED with a `retired_at`. A
  supersession is proven non-destructive: every other column on the
  superseded row is byte-identical afterwards.
* **Optimistic versions** -- a stale `expected_version` raises
  `StaleDirectedVersionError` and writes nothing; an identifier this
  Principal cannot reach raises `UnknownScopeError`. The two are separate
  because an optimistic-version conflict and a mistyped identifier are
  different facts about the world.
* **No guessing** -- an affiliation with no organization keeps none rather
  than acquiring an invented one; an organization profile refuses a
  non-organization entity instead of reclassifying it; a revision that
  clears `jurisdiction_code` clears it rather than carrying the old value
  forward.

And one property that is not in that list but is the reason this program's
merge/split wiring landed before its write path: **a row written through this
write path survives a real merge of the entity it belongs to**, proven by
writing it and then merging, not by asserting that RI-ENT-WP-06b's plan
covers the family.

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
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.engine import make_url

from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityAddress,
    EntityAddressState,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityOrganizationProfile,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityStatus,
    EntityType,
    LegalIdentityStatusCode,
    MergedEndpointError,
    NameTypeCode,
    OrganizationKindCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    StaleDirectedVersionError,
    normalize_address,
)
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository
from my_pa.infrastructure.persistence.tables import entity_names
from my_pa.infrastructure.persistence.unit_of_work import UnknownScopeError

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_entity_record_family_write_path_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

PERSON: Final = "ent_aaaa0001aaaa0001"
ORGANIZATION: Final = "ent_bbbb0002bbbb0002"
PROJECT: Final = "ent_cccc0003cccc0003"
SECOND_PERSON: Final = "ent_ffff0006ffff0006"
SURVIVOR: Final = "ent_dddd0004dddd0004"
MERGED_ONE: Final = "ent_eeee0005eeee0005"

WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
OPERATOR: Final = PRINCIPAL_A
CORRELATION: Final = "corr_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
REASON: Final = "two synthetic records describe one synthetic org"

NAME_ONE: Final = "enam_aaaa0001aaaa0001"
NAME_TWO: Final = "enam_bbbb0002bbbb0002"
ADDRESS_ONE: Final = "eadr_aaaa0001aaaa0001"
ADDRESS_TWO: Final = "eadr_bbbb0002bbbb0002"
METHOD_ONE: Final = "ecmm_aaaa0001aaaa0001"
METHOD_TWO: Final = "ecmm_bbbb0002bbbb0002"
PARTICIPATION_ONE: Final = "eppt_aaaa0001aaaa0001"
PARTICIPATION_TWO: Final = "eppt_bbbb0002bbbb0002"
AFFILIATION_ONE: Final = "poaf_aaaa0001aaaa0001"
AFFILIATION_TWO: Final = "poaf_bbbb0002bbbb0002"

ABSENT_NAME: Final = "enam_ffff0009ffff0009"


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
    status: EntityStatus = EntityStatus.ACTIVE,
    superseded_by_entity_id: str | None = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(name),
        display_name=name,
        status=status,
        superseded_by_entity_id=superseded_by_entity_id,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    """A person, an organization, and a project -- and nothing else. Every row
    this module reads back was written by the write path under test."""
    with migrated_engine.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(PERSON, "Alice Synthetic", EntityType.PERSON))
        repo.create(PRINCIPAL_A, _entity(ORGANIZATION, "Synthetic Org", EntityType.ORGANIZATION))
        repo.create(PRINCIPAL_A, _entity(PROJECT, "Harbour Tower", EntityType.PROJECT))
        # A second person, so a test needing two simultaneously active
        # affiliations has somewhere to put the other one:
        # `an_open_ended_affiliation_is_unique_per_person` is a partial unique
        # over `state = 'active' AND effective_to IS NULL`, and two open-ended
        # affiliations for one person is exactly what it refuses.
        repo.create(PRINCIPAL_A, _entity(SECOND_PERSON, "Bob Synthetic", EntityType.PERSON))
    return migrated_engine


def _name(
    entity_name_id: str = NAME_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    entity_id: str = ORGANIZATION,
    display_value: str = "Synthetic Org LLC",
    name_type_code: NameTypeCode = NameTypeCode.LEGAL,
    is_preferred: bool = False,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=principal_id,
        name_type_code=name_type_code,
        display_value=display_value,
        normalized_value=normalize_name(display_value),
        is_preferred=is_preferred,
        updated_at=WHEN,
    )


def _address(
    entity_address_id: str = ADDRESS_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    entity_id: str = ORGANIZATION,
    line1: str = "1 Synthetic Way",
    city: str = "Springfield",
) -> EntityAddress:
    raw = f"{line1}, {city}"
    return EntityAddress(
        entity_address_id=entity_address_id,
        entity_id=entity_id,
        principal_id=principal_id,
        address_type_code=AddressTypeCode.HEADQUARTERS,
        raw_value=raw,
        line1=line1,
        city=city,
        normalized_address_value=normalize_address(
            line1=line1,
            line2=None,
            city=city,
            region=None,
            postal_code=None,
            country=None,
            raw_value=raw,
        ),
        updated_at=WHEN,
    )


def _method(
    communication_method_id: str = METHOD_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    entity_id: str = ORGANIZATION,
    value: str = "synthetic@example.invalid",
) -> EntityCommunicationMethod:
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=principal_id,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.CORPORATE,
        normalized_value=value,
        display_value=value,
        verification_status_code=CommunicationVerificationStatusCode.UNRESOLVED,
        updated_at=WHEN,
    )


def _participation(
    participation_id: str = PARTICIPATION_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    project_entity_id: str = PROJECT,
    participant_entity_id: str = ORGANIZATION,
    role_code: str | None = None,
    role_text: str | None = None,
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=participation_id,
        principal_id=principal_id,
        project_entity_id=project_entity_id,
        participant_entity_id=participant_entity_id,
        project_display_name="Harbour Tower",
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.CONSULTANT,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        role_code=role_code,
        role_text=role_text,
        updated_at=WHEN,
    )


def _affiliation(
    affiliation_id: str = AFFILIATION_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    person_entity_id: str = PERSON,
    organization_entity_id: str | None = ORGANIZATION,
    job_title: str | None = "Principal Architect",
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=principal_id,
        person_entity_id=person_entity_id,
        organization_entity_id=organization_entity_id,
        job_title=job_title,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        updated_at=WHEN,
    )


def _profile(
    *,
    entity_id: str = ORGANIZATION,
    principal_id: str = PRINCIPAL_A,
    jurisdiction_code: str | None = "us-fl",
) -> EntityOrganizationProfile:
    return EntityOrganizationProfile(
        entity_id=entity_id,
        principal_id=principal_id,
        organization_kind_code=OrganizationKindCode.COMPANY,
        legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
        jurisdiction_code=jurisdiction_code,
        registration_identifier="P26000012345",
        created_at=WHEN,
        updated_at=WHEN,
    )


# --- Each family round-trips through its own write and its own read ---------


def test_every_family_round_trips_through_the_write_path(staged: Engine) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_name(PRINCIPAL_A, _name())
        repo.record_organization_profile(PRINCIPAL_A, _profile())
        repo.record_entity_address(PRINCIPAL_A, _address())
        repo.record_communication_method(PRINCIPAL_A, _method())
        repo.record_project_participation(PRINCIPAL_A, _participation())
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())

    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        assert repo.names(PRINCIPAL_A, ORGANIZATION) == [_name()]
        assert repo.organization_profile(PRINCIPAL_A, ORGANIZATION) == _profile()
        assert repo.addresses(PRINCIPAL_A, ORGANIZATION) == [_address()]
        assert repo.communication_methods(PRINCIPAL_A, ORGANIZATION) == [_method()]
        assert repo.project_participations_as_project(PRINCIPAL_A, PROJECT) == [_participation()]
        assert repo.project_participations_as_participant(PRINCIPAL_A, ORGANIZATION) == [
            _participation()
        ]
        assert repo.person_organization_affiliations_as_person(PRINCIPAL_A, PERSON) == [
            _affiliation()
        ]
        assert repo.person_organization_affiliations_as_organization(PRINCIPAL_A, ORGANIZATION) == [
            _affiliation()
        ]


# --- Principal scoping ------------------------------------------------------


def test_a_written_row_is_unreadable_by_another_principal(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name())
    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        assert repo.names(PRINCIPAL_A, ORGANIZATION) != []
        assert repo.names(PRINCIPAL_B, ORGANIZATION) == []


@pytest.mark.parametrize(
    ("method_name", "record"),
    [
        ("record_entity_name", _name(principal_id=PRINCIPAL_B)),
        ("record_entity_address", _address(principal_id=PRINCIPAL_B)),
        ("record_communication_method", _method(principal_id=PRINCIPAL_B)),
        ("record_project_participation", _participation(principal_id=PRINCIPAL_B)),
        ("record_person_organization_affiliation", _affiliation(principal_id=PRINCIPAL_B)),
        ("record_organization_profile", _profile(principal_id=PRINCIPAL_B)),
    ],
)
def test_a_write_refuses_a_record_stamped_with_another_principal(
    staged: Engine, method_name: str, record: object
) -> None:
    """The record carries its own `principal_id` and the caller states one.
    They have to agree, checked before the statement rather than left to the
    `_bound` stamp to silently overwrite -- an overwrite would file another
    Principal's record under this one and report success."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(ValueError, match="acting Principal"):
            getattr(repo, method_name)(PRINCIPAL_A, record)


def test_a_versioned_write_cannot_reach_another_principals_row(staged: Engine) -> None:
    """The same `UnknownScopeError` an absent row gets, so the answer does not
    distinguish "not yours" from "not there"."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name())
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(UnknownScopeError):
            repo.retire_entity_name(
                PRINCIPAL_B, entity_name_id=NAME_ONE, expected_version=1, at=LATER
            )
    with staged.connect() as connection:
        after = SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
    assert after == [_name()]


# --- Optimistic versions ----------------------------------------------------


def test_a_stale_expected_version_is_refused_and_writes_nothing(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name())
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.retire_entity_name(PRINCIPAL_A, entity_name_id=NAME_ONE, expected_version=1, at=LATER)
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(StaleDirectedVersionError):
            repo.retire_entity_name(
                PRINCIPAL_A, entity_name_id=NAME_ONE, expected_version=1, at=LATER
            )
    with staged.connect() as connection:
        (row,) = SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
    assert row.version == 2
    assert row.state is EntityNameState.RETIRED


def test_an_absent_identifier_is_refused_as_out_of_scope(staged: Engine) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(UnknownScopeError):
            repo.retire_entity_name(
                PRINCIPAL_A, entity_name_id=ABSENT_NAME, expected_version=1, at=LATER
            )


@pytest.mark.parametrize(
    ("write", "arguments"),
    [
        ("retire_entity_address", {"entity_address_id": ADDRESS_ONE}),
        ("retire_communication_method", {"communication_method_id": METHOD_ONE}),
        ("retire_project_participation", {"participation_id": PARTICIPATION_ONE}),
        ("retire_person_organization_affiliation", {"affiliation_id": AFFILIATION_ONE}),
    ],
)
def test_every_family_reports_a_stale_version_the_same_way(
    staged: Engine, write: str, arguments: dict[str, str]
) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_address(PRINCIPAL_A, _address())
        repo.record_communication_method(PRINCIPAL_A, _method())
        repo.record_project_participation(PRINCIPAL_A, _participation())
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        getattr(repo, write)(PRINCIPAL_A, expected_version=1, at=LATER, **arguments)
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(StaleDirectedVersionError):
            getattr(repo, write)(PRINCIPAL_A, expected_version=1, at=LATER, **arguments)


def test_a_stale_organization_profile_revision_is_refused(staged: Engine) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_organization_profile(PRINCIPAL_A, _profile())
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(StaleDirectedVersionError):
            repo.revise_organization_profile(
                PRINCIPAL_A,
                entity_id=ORGANIZATION,
                organization_kind_code=OrganizationKindCode.LLC_OR_SPV,
                legal_identity_status_code=LegalIdentityStatusCode.VERIFIED,
                jurisdiction_code=None,
                registration_identifier=None,
                expected_version=7,
                at=LATER,
            )
    with staged.connect() as connection:
        assert (
            SqlEntityRepository(connection).organization_profile(PRINCIPAL_A, ORGANIZATION)
            == _profile()
        )


# --- Lifecycle --------------------------------------------------------------


def test_a_supersession_is_non_destructive(staged: Engine) -> None:
    """Everything the superseded row carried other than its state, successor,
    version and `updated_at` is byte-identical afterwards. A correction that
    rewrote `display_value` in place would erase what the record said before,
    which is the whole reason this family has a `superseded_by_*` column."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_name(PRINCIPAL_A, _name())
        repo.record_entity_name(
            PRINCIPAL_A, _name(NAME_TWO, display_value="Synthetic Organisation LLC")
        )
    with staged.connect() as connection:
        before = connection.execute(
            select(entity_names).where(
                entity_names.c.principal_id == PRINCIPAL_A,
                entity_names.c.entity_name_id == NAME_ONE,
            )
        ).one()

    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            superseded_by_entity_name_id=NAME_TWO,
            expected_version=1,
            at=LATER,
        )

    with staged.connect() as connection:
        after = connection.execute(
            select(entity_names).where(
                entity_names.c.principal_id == PRINCIPAL_A,
                entity_names.c.entity_name_id == NAME_ONE,
            )
        ).one()
    changed = {
        column: (getattr(before, column), getattr(after, column))
        for column in before._mapping
        if getattr(before, column) != getattr(after, column)
    }
    assert set(changed) == {"state", "superseded_by_entity_name_id", "version", "updated_at"}
    assert after.state == EntityNameState.SUPERSEDED.value
    assert after.superseded_by_entity_name_id == NAME_TWO
    assert after.version == 2


def test_a_retirement_releases_the_preferred_slot(staged: Engine) -> None:
    """`an_active_entity_name_has_one_preferred_per_type` is a partial unique
    over `state = 'active' AND is_preferred = true`. A retirement that left
    `is_preferred` set would still release the slot through `state` alone;
    clearing it too means a reader of the retired row is not told the entity
    still prefers a name it has withdrawn."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_name(PRINCIPAL_A, _name(is_preferred=True))
    with staged.begin() as connection:
        SqlEntityRepository(connection).retire_entity_name(
            PRINCIPAL_A, entity_name_id=NAME_ONE, expected_version=1, at=LATER
        )
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(
            PRINCIPAL_A, _name(NAME_TWO, display_value="Synthetic Org Holdings", is_preferred=True)
        )
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
    retired = next(row for row in rows if row.entity_name_id == NAME_ONE)
    assert retired.state is EntityNameState.RETIRED
    assert retired.is_preferred is False
    assert retired.retired_at == LATER


@pytest.mark.parametrize(
    ("write", "arguments", "read", "subject", "retired_state"),
    [
        (
            "retire_entity_address",
            {"entity_address_id": ADDRESS_ONE},
            "addresses",
            ORGANIZATION,
            EntityAddressState.RETIRED,
        ),
        (
            "retire_communication_method",
            {"communication_method_id": METHOD_ONE},
            "communication_methods",
            ORGANIZATION,
            EntityCommunicationMethodState.RETIRED,
        ),
        (
            "retire_project_participation",
            {"participation_id": PARTICIPATION_ONE},
            "project_participations_as_project",
            PROJECT,
            EntityProjectParticipationState.RETIRED,
        ),
        (
            "retire_person_organization_affiliation",
            {"affiliation_id": AFFILIATION_ONE},
            "person_organization_affiliations_as_person",
            PERSON,
            PersonOrganizationAffiliationState.RETIRED,
        ),
    ],
)
def test_every_family_retires_to_its_own_terminal_state(
    staged: Engine,
    write: str,
    arguments: dict[str, str],
    read: str,
    subject: str,
    retired_state: object,
) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_address(PRINCIPAL_A, _address())
        repo.record_communication_method(PRINCIPAL_A, _method())
        repo.record_project_participation(PRINCIPAL_A, _participation())
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())
    with staged.begin() as connection:
        getattr(SqlEntityRepository(connection), write)(
            PRINCIPAL_A, expected_version=1, at=LATER, **arguments
        )
    with staged.connect() as connection:
        (row,) = getattr(SqlEntityRepository(connection), read)(PRINCIPAL_A, subject)
    assert row.state is retired_state
    assert row.version == 2
    assert row.retired_at == LATER


@pytest.mark.parametrize(
    ("write", "arguments", "read", "subject", "superseded_state", "successor_field"),
    [
        (
            "supersede_entity_address",
            {"entity_address_id": ADDRESS_ONE, "superseded_by_entity_address_id": ADDRESS_TWO},
            "addresses",
            ORGANIZATION,
            EntityAddressState.SUPERSEDED,
            "superseded_by_entity_address_id",
        ),
        (
            "supersede_communication_method",
            {
                "communication_method_id": METHOD_ONE,
                "superseded_by_communication_method_id": METHOD_TWO,
            },
            "communication_methods",
            ORGANIZATION,
            EntityCommunicationMethodState.SUPERSEDED,
            "superseded_by_communication_method_id",
        ),
        (
            "supersede_project_participation",
            {
                "participation_id": PARTICIPATION_ONE,
                "superseded_by_participation_id": PARTICIPATION_TWO,
            },
            "project_participations_as_project",
            PROJECT,
            EntityProjectParticipationState.SUPERSEDED,
            "superseded_by_participation_id",
        ),
        (
            "supersede_person_organization_affiliation",
            {"affiliation_id": AFFILIATION_ONE, "superseded_by_affiliation_id": AFFILIATION_TWO},
            "person_organization_affiliations_as_person",
            PERSON,
            PersonOrganizationAffiliationState.SUPERSEDED,
            "superseded_by_affiliation_id",
        ),
    ],
)
def test_every_family_supersedes_and_names_its_successor(
    staged: Engine,
    write: str,
    arguments: dict[str, str],
    read: str,
    subject: str,
    superseded_state: object,
    successor_field: str,
) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_address(PRINCIPAL_A, _address())
        repo.record_communication_method(PRINCIPAL_A, _method())
        repo.record_project_participation(PRINCIPAL_A, _participation())
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())
        # The successor each supersession names has to exist: every
        # `superseded_by_*` column is a real composite foreign key back into
        # its own table, which is what makes the lineage followable rather
        # than a dangling string.
        repo.record_entity_address(PRINCIPAL_A, _address(ADDRESS_TWO, line1="2 Synthetic Way"))
        repo.record_communication_method(
            PRINCIPAL_A, _method(METHOD_TWO, value="other@example.invalid")
        )
        repo.record_project_participation(
            PRINCIPAL_A, _participation(PARTICIPATION_TWO, role_code="ARCHITECT_OF_RECORD")
        )
        repo.record_person_organization_affiliation(
            PRINCIPAL_A,
            _affiliation(AFFILIATION_TWO, person_entity_id=SECOND_PERSON),
        )
    with staged.begin() as connection:
        getattr(SqlEntityRepository(connection), write)(
            PRINCIPAL_A, expected_version=1, at=LATER, **arguments
        )
    with staged.connect() as connection:
        rows = getattr(SqlEntityRepository(connection), read)(PRINCIPAL_A, subject)
    (row,) = [entry for entry in rows if entry.version == 2]
    assert row.state is superseded_state
    assert row.version == 2
    assert getattr(row, successor_field) == list(arguments.values())[1]


@pytest.mark.parametrize(
    ("write", "arguments"),
    [
        (
            "supersede_entity_name",
            {"entity_name_id": NAME_ONE, "superseded_by_entity_name_id": NAME_ONE},
        ),
        (
            "supersede_entity_address",
            {"entity_address_id": ADDRESS_ONE, "superseded_by_entity_address_id": ADDRESS_ONE},
        ),
        (
            "supersede_communication_method",
            {
                "communication_method_id": METHOD_ONE,
                "superseded_by_communication_method_id": METHOD_ONE,
            },
        ),
        (
            "supersede_project_participation",
            {
                "participation_id": PARTICIPATION_ONE,
                "superseded_by_participation_id": PARTICIPATION_ONE,
            },
        ),
        (
            "supersede_person_organization_affiliation",
            {"affiliation_id": AFFILIATION_ONE, "superseded_by_affiliation_id": AFFILIATION_ONE},
        ),
    ],
)
def test_no_family_supersedes_itself(staged: Engine, write: str, arguments: dict[str, str]) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(ValueError, match="not superseded by itself"):
            getattr(repo, write)(PRINCIPAL_A, expected_version=1, at=LATER, **arguments)


def test_an_affiliation_retirement_closes_its_window_only_when_told_to(staged: Engine) -> None:
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())
        repo.record_person_organization_affiliation(
            PRINCIPAL_A,
            _affiliation(AFFILIATION_TWO, person_entity_id=SECOND_PERSON, job_title="Associate"),
        )
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.retire_person_organization_affiliation(
            PRINCIPAL_A, affiliation_id=AFFILIATION_ONE, expected_version=1, at=LATER
        )
        repo.retire_person_organization_affiliation(
            PRINCIPAL_A,
            affiliation_id=AFFILIATION_TWO,
            expected_version=1,
            at=LATER,
            effective_to=LATER,
        )
    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        rows = {
            row.affiliation_id: row
            for person in (PERSON, SECOND_PERSON)
            for row in repo.person_organization_affiliations_as_person(PRINCIPAL_A, person)
        }
    assert rows[AFFILIATION_ONE].effective_to is None
    assert rows[AFFILIATION_TWO].effective_to == LATER


# --- No guessing ------------------------------------------------------------


def test_an_affiliation_without_an_organization_keeps_none(staged: Engine) -> None:
    """RI-ENT-WP-05's independent-consultant case, proven through the write
    path rather than through a raw insert: the write does not manufacture an
    organization entity to satisfy the nullable foreign key."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_person_organization_affiliation(
            PRINCIPAL_A,
            _affiliation(organization_entity_id=None, job_title="Independent Consultant"),
        )
    with staged.connect() as connection:
        (row,) = SqlEntityRepository(connection).person_organization_affiliations_as_person(
            PRINCIPAL_A, PERSON
        )
        assert (
            SqlEntityRepository(connection).person_organization_affiliations_as_organization(
                PRINCIPAL_A, ORGANIZATION
            )
            == []
        )
    assert row.organization_entity_id is None


def test_an_organization_profile_refuses_a_non_organization_entity(staged: Engine) -> None:
    """The cross-table invariant `EntityOrganizationProfile`'s docstring names
    the writer as responsible for. Enforced rather than assumed: a profile on
    a person entity would classify a person as a company."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(ValueError, match="organization entity"):
            repo.record_organization_profile(PRINCIPAL_A, _profile(entity_id=PERSON))


def test_a_profile_revision_clears_a_nullable_field_rather_than_carrying_it(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_organization_profile(PRINCIPAL_A, _profile())
    with staged.begin() as connection:
        SqlEntityRepository(connection).revise_organization_profile(
            PRINCIPAL_A,
            entity_id=ORGANIZATION,
            organization_kind_code=OrganizationKindCode.LLC_OR_SPV,
            legal_identity_status_code=LegalIdentityStatusCode.VERIFIED,
            jurisdiction_code=None,
            registration_identifier=None,
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        after = SqlEntityRepository(connection).organization_profile(PRINCIPAL_A, ORGANIZATION)
    assert after is not None
    assert after.jurisdiction_code is None
    assert after.registration_identifier is None
    assert after.organization_kind_code is OrganizationKindCode.LLC_OR_SPV
    assert after.legal_identity_status_code is LegalIdentityStatusCode.VERIFIED
    assert after.version == 2
    assert after.updated_at == LATER


def test_a_participation_keeps_free_text_role_without_inventing_a_code(staged: Engine) -> None:
    """`role_text` is what a source wrote; `role_code` is a taxonomy claim.
    The write path carries the first and leaves the second null rather than
    guessing a code from prose."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_project_participation(
            PRINCIPAL_A, _participation(role_text="lead design architect", role_code=None)
        )
    with staged.connect() as connection:
        (row,) = SqlEntityRepository(connection).project_participations_as_project(
            PRINCIPAL_A, PROJECT
        )
    assert row.role_text == "lead design architect"
    assert row.role_code is None


def test_a_name_write_refuses_an_unnormalized_normalized_value(staged: Engine) -> None:
    """`EntityName.__post_init__` refuses it first, so this proves the
    repository does not accept one built around the domain either."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(ValueError):
            repo.record_entity_name(
                PRINCIPAL_A,
                EntityName(
                    entity_name_id=NAME_ONE,
                    entity_id=ORGANIZATION,
                    principal_id=PRINCIPAL_A,
                    name_type_code=NameTypeCode.LEGAL,
                    display_value="Synthetic Org LLC",
                    normalized_value="Synthetic Org LLC",
                ),
            )


# --- Merged endpoints -------------------------------------------------------


@pytest.mark.parametrize(
    ("write", "record"),
    [
        ("record_entity_name", _name(entity_id=MERGED_ONE)),
        ("record_entity_address", _address(entity_id=MERGED_ONE)),
        ("record_communication_method", _method(entity_id=MERGED_ONE)),
        ("record_project_participation", _participation(participant_entity_id=MERGED_ONE)),
        ("record_person_organization_affiliation", _affiliation(organization_entity_id=MERGED_ONE)),
        ("record_organization_profile", _profile(entity_id=MERGED_ONE)),
    ],
)
def test_no_family_writes_against_a_merged_away_entity(
    staged: Engine, write: str, record: object
) -> None:
    """Following the redirect would bind the row to a different identity than
    the caller chose, so every write refuses instead."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(SURVIVOR, "Survivor Org", EntityType.ORGANIZATION))
        repo.create(
            PRINCIPAL_A,
            _entity(
                MERGED_ONE,
                "Merged-Away Org",
                EntityType.ORGANIZATION,
                status=EntityStatus.MERGED_REDIRECT,
                superseded_by_entity_id=SURVIVOR,
            ),
        )
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(MergedEndpointError):
            getattr(repo, write)(PRINCIPAL_A, record)


# --- The write path meets the merge/split machinery -------------------------


def _service(connection: Connection) -> IdentityCorrectionService:
    return IdentityCorrectionService(
        SqlEntityRepository(connection), SqlRelationshipMemoryRepository(connection)
    )


def test_a_row_written_through_the_write_path_is_reparented_by_a_real_merge(
    migrated_engine: Engine,
) -> None:
    """The claim RI-ENT-WP-06b could only make in the abstract, made concrete:
    write a name through `record_entity_name`, merge the entity it belongs to
    away, and read it back under the survivor. Nothing here writes the row by
    raw insert, so the merge is being asked about the same row the production
    write path produces."""
    with migrated_engine.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(SURVIVOR, "Survivor Org", EntityType.ORGANIZATION))
        repo.create(PRINCIPAL_A, _entity(MERGED_ONE, "Merged-Away Org", EntityType.ORGANIZATION))
        repo.record_entity_name(PRINCIPAL_A, _name(entity_id=MERGED_ONE))

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
                idempotency_key="merge-wp08-written-name",
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
        survivor_names = repo.names(PRINCIPAL_A, SURVIVOR)
        assert repo.names(PRINCIPAL_A, MERGED_ONE) == []
    assert [row.entity_name_id for row in survivor_names] == [NAME_ONE]
    assert survivor_names[0].entity_id == SURVIVOR


def test_a_versioned_write_still_reaches_a_row_a_merge_reparented(
    migrated_engine: Engine,
) -> None:
    """A reparented row keeps its own surrogate key, and the lifecycle verbs
    still address it after the merge.

    **Reparenting bumps the row's `version`, and this test states that rather
    than working around it.** `reparent_entity_reference` writes
    `version = version + 1` alongside the substituted entity reference, so a
    caller holding a version read before the merge is legitimately stale
    afterwards -- the optimistic-version contract is doing exactly its job.
    What matters is that the row is still reachable by its own
    `entity_name_id` and still retires cleanly at its current version."""
    with migrated_engine.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.create(PRINCIPAL_A, _entity(SURVIVOR, "Survivor Org", EntityType.ORGANIZATION))
        repo.create(PRINCIPAL_A, _entity(MERGED_ONE, "Merged-Away Org", EntityType.ORGANIZATION))
        repo.record_entity_name(PRINCIPAL_A, _name(entity_id=MERGED_ONE))

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
                idempotency_key="merge-wp08-then-retire",
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
        (reparented,) = SqlEntityRepository(connection).names(PRINCIPAL_A, SURVIVOR)
    assert reparented.entity_name_id == NAME_ONE
    assert reparented.version == 2

    with migrated_engine.begin() as connection:
        repo = SqlEntityRepository(connection)
        with pytest.raises(StaleDirectedVersionError):
            repo.retire_entity_name(
                PRINCIPAL_A, entity_name_id=NAME_ONE, expected_version=1, at=LATER
            )
    with migrated_engine.begin() as connection:
        SqlEntityRepository(connection).retire_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            expected_version=reparented.version,
            at=LATER,
        )
    with migrated_engine.connect() as connection:
        (row,) = SqlEntityRepository(connection).names(PRINCIPAL_A, SURVIVOR)
    assert row.state is EntityNameState.RETIRED
    assert row.version == 3
