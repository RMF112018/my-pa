"""The six record families' write path against real PostgreSQL (RI-ENT-WP-08).

Every property the earlier work packages deferred on the argument "nothing
writes to these tables yet" becomes load-bearing here, because this is the
work package that writes to them. So this module proves the four things the
audit's WP-08 objective names, each against a live database rather than a
double:

* **Principal scoping** -- a row written by one Principal is unreadable by
  another, and a write handed a record stamped with somebody else's
  `principal_id` is refused before it reaches the database.
* **Lifecycle** -- `record_*` inserts, `supersede_*` marks SUPERSEDED, inserts
  the successor and names it, `retire_*` marks RETIRED with a `retired_at`. A
  supersession is proven non-destructive: every other column on the
  superseded row is byte-identical afterwards.
* **The order a correction is issued in** -- reviewer finding D1. Each of the
  five temporal families carries at least one partial unique index over
  `state = 'active'`, so a successor inserted while its own predecessor is
  still active collides with its own predecessor. `supersede_*` releases the
  predecessor first, and the tests below write, for every family, exactly the
  successor the old successor-first ordering could not write. They are here,
  at this tier, rather than beside the service's unit tests, because the
  in-memory double those run against carries no unique index at all: it
  accepted every one of these collisions silently, which is how the defect
  reached review.
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
from sqlalchemy.exc import IntegrityError

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
from my_pa.infrastructure.persistence.tables import entity_names, entity_organization_profiles
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
NAME_THREE: Final = "enam_cccc0003cccc0003"
ADDRESS_ONE: Final = "eadr_aaaa0001aaaa0001"
ADDRESS_TWO: Final = "eadr_bbbb0002bbbb0002"
ADDRESS_THREE: Final = "eadr_cccc0003cccc0003"
METHOD_ONE: Final = "ecmm_aaaa0001aaaa0001"
METHOD_TWO: Final = "ecmm_bbbb0002bbbb0002"
METHOD_THREE: Final = "ecmm_cccc0003cccc0003"
PARTICIPATION_ONE: Final = "eppt_aaaa0001aaaa0001"
PARTICIPATION_TWO: Final = "eppt_bbbb0002bbbb0002"
PARTICIPATION_THREE: Final = "eppt_cccc0003cccc0003"
AFFILIATION_ONE: Final = "poaf_aaaa0001aaaa0001"
AFFILIATION_TWO: Final = "poaf_bbbb0002bbbb0002"
AFFILIATION_THREE: Final = "poaf_cccc0003cccc0003"

ABSENT_NAME: Final = "enam_ffff0009ffff0009"

#: A seeded `entity_role_types.role_code`. Participation's active-uniqueness
#: index keys on `role_code`, and PostgreSQL's default `NULLS DISTINCT`
#: behaviour means a null `role_code` never collides with anything -- so every
#: test in this module that means to exercise
#: `an_active_project_participation_is_unique_per_project_and_role` states a
#: real code rather than leaving it null.
ROLE_OF_RECORD: Final = "ARCHITECT_OF_RECORD"
ROLE_CONSULTANT: Final = "CONSULTANT"


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
    effective_from: datetime | None = None,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=principal_id,
        name_type_code=name_type_code,
        display_value=display_value,
        normalized_value=normalize_name(display_value),
        is_preferred=is_preferred,
        effective_from=effective_from,
        updated_at=WHEN,
    )


def _address(
    entity_address_id: str = ADDRESS_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    entity_id: str = ORGANIZATION,
    line1: str = "1 Synthetic Way",
    city: str = "Springfield",
    label: str | None = None,
    is_preferred: bool = False,
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
        label=label,
        is_preferred=is_preferred,
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
    is_preferred: bool = False,
    verification_status_code: CommunicationVerificationStatusCode = (
        CommunicationVerificationStatusCode.UNRESOLVED
    ),
) -> EntityCommunicationMethod:
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=principal_id,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.CORPORATE,
        normalized_value=value,
        display_value=value,
        is_preferred=is_preferred,
        verification_status_code=verification_status_code,
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
    scope_text: str | None = None,
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
        scope_text=scope_text,
        updated_at=WHEN,
    )


def _affiliation(
    affiliation_id: str = AFFILIATION_ONE,
    *,
    principal_id: str = PRINCIPAL_A,
    person_entity_id: str = PERSON,
    organization_entity_id: str | None = ORGANIZATION,
    job_title: str | None = "Principal Architect",
    effective_to: datetime | None = None,
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=principal_id,
        person_entity_id=person_entity_id,
        organization_entity_id=organization_entity_id,
        job_title=job_title,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        effective_to=effective_to,
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
    which is the whole reason this family has a `superseded_by_*` column.

    The successor is no longer pre-recorded here and then named by id:
    `supersede_entity_name` takes the successor *record* and inserts it
    itself, between the two `UPDATE`s on the predecessor. That is the whole
    point of the ordering -- so the setup writes one row, not two, and the
    successor arrives through the verb under test rather than beside it. The
    claim is unchanged, and is now made about a predecessor the same
    statement sequence also inserted a successor after."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name())
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
            successor=_name(NAME_TWO, display_value="Synthetic Organisation LLC"),
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
    (
        "write",
        "arguments",
        "read",
        "subject",
        "superseded_state",
        "successor_field",
        "successor_id",
    ),
    [
        (
            "supersede_entity_address",
            {
                "entity_address_id": ADDRESS_ONE,
                "successor": _address(ADDRESS_TWO, line1="2 Synthetic Way"),
            },
            "addresses",
            ORGANIZATION,
            EntityAddressState.SUPERSEDED,
            "superseded_by_entity_address_id",
            ADDRESS_TWO,
        ),
        (
            "supersede_communication_method",
            {
                "communication_method_id": METHOD_ONE,
                "successor": _method(METHOD_TWO, value="other@example.invalid"),
            },
            "communication_methods",
            ORGANIZATION,
            EntityCommunicationMethodState.SUPERSEDED,
            "superseded_by_communication_method_id",
            METHOD_TWO,
        ),
        (
            "supersede_project_participation",
            {
                "participation_id": PARTICIPATION_ONE,
                "successor": _participation(PARTICIPATION_TWO, role_code=ROLE_OF_RECORD),
            },
            "project_participations_as_project",
            PROJECT,
            EntityProjectParticipationState.SUPERSEDED,
            "superseded_by_participation_id",
            PARTICIPATION_TWO,
        ),
        (
            "supersede_person_organization_affiliation",
            {
                "affiliation_id": AFFILIATION_ONE,
                "successor": _affiliation(AFFILIATION_TWO, job_title="Managing Principal"),
            },
            "person_organization_affiliations_as_person",
            PERSON,
            PersonOrganizationAffiliationState.SUPERSEDED,
            "superseded_by_affiliation_id",
            AFFILIATION_TWO,
        ),
    ],
)
def test_every_family_supersedes_and_names_its_successor(
    staged: Engine,
    write: str,
    arguments: dict[str, object],
    read: str,
    subject: str,
    superseded_state: object,
    successor_field: str,
    successor_id: str,
) -> None:
    """One predecessor per family, superseded by a successor the verb inserts.

    The setup no longer pre-records the successor. It cannot: every
    `superseded_by_*` column is a real composite foreign key back into its own
    table (`an_entity_address_is_superseded_within_its_principal` and its four
    siblings), NOT DEFERRABLE, so the successor has to exist before the
    predecessor names it -- and every one of these families also carries a
    partial unique over `state = 'active'` that the pre-recorded successor
    would have collided with while its predecessor was still active. Both
    facts are satisfied by the same three statements, which is what
    `supersede_*` now issues, so the successor is written by the verb under
    test rather than staged beside it.

    The affiliation case is the sharpest: its successor is the *same person's*
    affiliation, which `an_open_ended_affiliation_is_unique_per_person` refuses
    outright while the predecessor is active. Before this ordering that
    parameter had to name `SECOND_PERSON` to write at all, which meant the
    row it was proving lineage for was not the row a correction produces."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_address(PRINCIPAL_A, _address())
        repo.record_communication_method(PRINCIPAL_A, _method())
        repo.record_project_participation(PRINCIPAL_A, _participation(role_code=ROLE_OF_RECORD))
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())
    with staged.begin() as connection:
        getattr(SqlEntityRepository(connection), write)(
            PRINCIPAL_A, expected_version=1, at=LATER, **arguments
        )
    with staged.connect() as connection:
        rows = getattr(SqlEntityRepository(connection), read)(PRINCIPAL_A, subject)
    (row,) = [entry for entry in rows if entry.version == 2]
    assert row.state is superseded_state
    assert row.version == 2
    assert getattr(row, successor_field) == successor_id
    # The successor the verb inserted is present, active, and at version 1 --
    # a supersession is one version bump on the predecessor and a fresh row,
    # not a bump on both.
    (successor,) = [entry for entry in rows if entry.version == 1]
    assert successor.state.value == "active"
    assert getattr(successor, successor_field) is None


@pytest.mark.parametrize(
    ("write", "arguments"),
    [
        ("supersede_entity_name", {"entity_name_id": NAME_ONE, "successor": _name(NAME_ONE)}),
        (
            "supersede_entity_address",
            {"entity_address_id": ADDRESS_ONE, "successor": _address(ADDRESS_ONE)},
        ),
        (
            "supersede_communication_method",
            {"communication_method_id": METHOD_ONE, "successor": _method(METHOD_ONE)},
        ),
        (
            "supersede_project_participation",
            {"participation_id": PARTICIPATION_ONE, "successor": _participation(PARTICIPATION_ONE)},
        ),
        (
            "supersede_person_organization_affiliation",
            {"affiliation_id": AFFILIATION_ONE, "successor": _affiliation(AFFILIATION_ONE)},
        ),
    ],
)
def test_no_family_supersedes_itself(
    staged: Engine, write: str, arguments: dict[str, object]
) -> None:
    """Each family's `CHECK (superseded_by_X IS NULL OR superseded_by_X <> X)`,
    refused in the verb before any statement runs.

    The successor is now a whole record rather than an id, so the identity is
    read off `successor.<id field>` rather than off a keyword -- and the check
    has to happen before the first `UPDATE`, because that `UPDATE` would
    otherwise mark the predecessor SUPERSEDED and the insert that follows
    would then fail on the primary key instead, reporting a duplicate key
    where the truth is a record pointed at itself. Nothing is recorded first:
    the refusal precedes the read of any row, so an empty table is the
    strictest setup for it."""
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


# --- A correction is ordered as the schema admits (reviewer finding D1) -----
#
# Five temporal families, each carrying at least one partial unique index whose
# `WHERE` is `state = 'active'`. A successor inserted while its own predecessor
# is still active therefore collides *with its own predecessor*, and the plain
# `IntegrityError` that produced escaped untranslated -- which is what the
# reviewer's finding D1 named. `supersede_*` releases the predecessor first, so
# each of the tests below writes exactly the successor the old successor-first
# ordering could not.
#
# Each names the index it is standing on, and each picks a successor that
# changes *nothing the index keys on*, because that is the case the old
# ordering failed on unconditionally rather than by coincidence of values:
#
# * `an_active_entity_name_is_unique_per_entity_and_type`
#   `(principal_id, entity_id, name_type_code, normalized_value)`
# * `an_active_entity_address_is_unique_per_entity_and_type`
#   `(principal_id, entity_id, address_type_code, normalized_address_value)`
# * `an_active_communication_method_is_unique_per_entity_and_type`
#   `(principal_id, entity_id, method_type_code, normalized_value)`
# * `an_active_project_participation_is_unique_per_project_and_role`
#   `(principal_id, project_entity_id, participant_entity_id, role_code)`
# * `an_open_ended_affiliation_is_unique_per_person`
#   `(principal_id, person_entity_id)` `WHERE ... AND effective_to IS NULL`
#
# None of this is visible to the in-memory double the service's unit tests use.
# That double enforces no unique index at all, so it accepted every collision
# below silently; a database is the only place these claims can be made.


def test_a_name_correction_keeping_its_normalized_value_succeeds(staged: Engine) -> None:
    """Correcting a name's `effective_from` and nothing else.

    `an_active_entity_name_is_unique_per_entity_and_type` keys on
    `(principal_id, entity_id, name_type_code, normalized_value)` and the
    successor restates all four unchanged, so under a successor-first ordering
    this row collides with the row it is replacing -- not with a rival, with
    its own predecessor. Correcting the *validity window* of a name is an
    ordinary thing to want, and it is the shape of correction for which no
    choice of successor values could have avoided the collision.

    The predecessor's single version bump is asserted exactly, not as `>= 2`:
    `supersede_entity_name` issues two `UPDATE`s against the same row, and the
    second guards on `state`/`superseded_by_* IS NULL` rather than bumping
    again. A second bump would silently invalidate the version every caller
    holding a receipt for this correction would go on to use.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name())
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            successor=_name(NAME_TWO, effective_from=WHEN),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = {
            row.entity_name_id: row
            for row in SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
        }
    assert set(rows) == {NAME_ONE, NAME_TWO}
    predecessor, successor = rows[NAME_ONE], rows[NAME_TWO]
    assert predecessor.state is EntityNameState.SUPERSEDED
    assert predecessor.superseded_by_entity_name_id == NAME_TWO
    assert predecessor.version == 2
    assert predecessor.updated_at == LATER
    assert successor.state is EntityNameState.ACTIVE
    assert successor.version == 1
    assert successor.effective_from == WHEN
    assert successor.normalized_value == predecessor.normalized_value


def test_an_address_correction_keeping_its_normalized_value_succeeds(staged: Engine) -> None:
    """Correcting an address's `label` and nothing else.

    `an_active_entity_address_is_unique_per_entity_and_type` keys on
    `(principal_id, entity_id, address_type_code, normalized_address_value)`.
    A label is the one part of an address row that is purely how a reader
    files it, so a correction to it necessarily leaves all four key columns
    alone -- and therefore necessarily collided under the old ordering.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_address(PRINCIPAL_A, _address())
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_address(
            PRINCIPAL_A,
            entity_address_id=ADDRESS_ONE,
            successor=_address(ADDRESS_TWO, label="Registered office"),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = {
            row.entity_address_id: row
            for row in SqlEntityRepository(connection).addresses(PRINCIPAL_A, ORGANIZATION)
        }
    assert set(rows) == {ADDRESS_ONE, ADDRESS_TWO}
    predecessor, successor = rows[ADDRESS_ONE], rows[ADDRESS_TWO]
    assert predecessor.state is EntityAddressState.SUPERSEDED
    assert predecessor.superseded_by_entity_address_id == ADDRESS_TWO
    assert predecessor.version == 2
    assert predecessor.label is None
    assert successor.state is EntityAddressState.ACTIVE
    assert successor.version == 1
    assert successor.label == "Registered office"
    assert successor.normalized_address_value == predecessor.normalized_address_value


def test_a_channel_correction_keeping_its_normalized_value_succeeds(staged: Engine) -> None:
    """Correcting a channel's `verification_status_code` and nothing else.

    `an_active_communication_method_is_unique_per_entity_and_type` keys on
    `(principal_id, entity_id, method_type_code, normalized_value)`. Promoting
    a channel from UNRESOLVED to VERIFIED is the commonest correction this
    family will ever see and it touches none of those four, so the old
    ordering refused the entire verification workflow, not an edge of it.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_communication_method(PRINCIPAL_A, _method())
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_communication_method(
            PRINCIPAL_A,
            communication_method_id=METHOD_ONE,
            successor=_method(
                METHOD_TWO,
                verification_status_code=CommunicationVerificationStatusCode.VERIFIED,
            ),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = {
            row.communication_method_id: row
            for row in SqlEntityRepository(connection).communication_methods(
                PRINCIPAL_A, ORGANIZATION
            )
        }
    assert set(rows) == {METHOD_ONE, METHOD_TWO}
    predecessor, successor = rows[METHOD_ONE], rows[METHOD_TWO]
    assert predecessor.state is EntityCommunicationMethodState.SUPERSEDED
    assert predecessor.superseded_by_communication_method_id == METHOD_TWO
    assert predecessor.version == 2
    assert predecessor.verification_status_code is CommunicationVerificationStatusCode.UNRESOLVED
    assert successor.state is EntityCommunicationMethodState.ACTIVE
    assert successor.version == 1
    assert successor.verification_status_code is CommunicationVerificationStatusCode.VERIFIED
    assert successor.normalized_value == predecessor.normalized_value


def test_a_participation_correction_keeping_its_role_code_succeeds(staged: Engine) -> None:
    """Correcting a participation's `scope_text` while its `role_code` stands.

    `an_active_project_participation_is_unique_per_project_and_role` keys on
    `(principal_id, project_entity_id, participant_entity_id, role_code)`, and
    the successor restates all four. `role_code` is stated rather than left
    null on purpose: PostgreSQL's default `NULLS DISTINCT` means a null
    `role_code` never collides with anything, so a test that left it null
    would pass under the broken ordering too and would prove nothing about
    this index at all.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_project_participation(
            PRINCIPAL_A, _participation(role_code=ROLE_OF_RECORD, scope_text="core and shell")
        )
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_project_participation(
            PRINCIPAL_A,
            participation_id=PARTICIPATION_ONE,
            successor=_participation(
                PARTICIPATION_TWO,
                role_code=ROLE_OF_RECORD,
                scope_text="core, shell and interiors",
            ),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = {
            row.participation_id: row
            for row in SqlEntityRepository(connection).project_participations_as_project(
                PRINCIPAL_A, PROJECT
            )
        }
    assert set(rows) == {PARTICIPATION_ONE, PARTICIPATION_TWO}
    predecessor, successor = rows[PARTICIPATION_ONE], rows[PARTICIPATION_TWO]
    assert predecessor.state is EntityProjectParticipationState.SUPERSEDED
    assert predecessor.superseded_by_participation_id == PARTICIPATION_TWO
    assert predecessor.version == 2
    assert predecessor.scope_text == "core and shell"
    assert successor.state is EntityProjectParticipationState.ACTIVE
    assert successor.version == 1
    assert successor.role_code == ROLE_OF_RECORD == predecessor.role_code
    assert successor.scope_text == "core, shell and interiors"


def test_a_current_affiliation_is_correctable_at_all(staged: Engine) -> None:
    """**The case finding D1 was actually about.**

    `an_open_ended_affiliation_is_unique_per_person` is
    `(principal_id, person_entity_id) WHERE state = 'active' AND effective_to
    IS NULL`. It keys on the person *alone* -- not the job title, not the
    organization, not the affiliation type -- so under the old successor-first
    ordering *every* correction of a person's current affiliation collided,
    whatever field was being corrected. Not intermittently and not for some
    values: `correct_affiliation` was unusable for any current affiliation.

    So the correction here changes only the job title, which is as far from
    the index's key columns as this family allows a correction to be, and the
    successor stays open-ended (`effective_to is None`) rather than quietly
    acquiring an end date -- closing the window would also release the index,
    and would be the schema-satisfying answer that invents a fact the caller
    never stated.

    This family had no database-tier coverage at all before this test, which
    is how the defect survived to review: the double the service's unit tests
    run against enforces no unique index, so it wrote both rows happily.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_person_organization_affiliation(
            PRINCIPAL_A, _affiliation()
        )
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_person_organization_affiliation(
            PRINCIPAL_A,
            affiliation_id=AFFILIATION_ONE,
            successor=_affiliation(AFFILIATION_TWO, job_title="Managing Principal"),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = {
            row.affiliation_id: row
            for row in SqlEntityRepository(connection).person_organization_affiliations_as_person(
                PRINCIPAL_A, PERSON
            )
        }
    assert set(rows) == {AFFILIATION_ONE, AFFILIATION_TWO}
    predecessor, successor = rows[AFFILIATION_ONE], rows[AFFILIATION_TWO]
    assert predecessor.state is PersonOrganizationAffiliationState.SUPERSEDED
    assert predecessor.superseded_by_affiliation_id == AFFILIATION_TWO
    assert predecessor.version == 2
    assert predecessor.job_title == "Principal Architect"
    assert successor.state is PersonOrganizationAffiliationState.ACTIVE
    assert successor.version == 1
    assert successor.job_title == "Managing Principal"
    assert successor.person_entity_id == predecessor.person_entity_id
    assert successor.effective_to is None
    assert predecessor.effective_to is None


def test_a_name_correction_may_claim_the_preferred_slot_its_predecessor_held(
    staged: Engine,
) -> None:
    """The preferred slot passes from predecessor to successor in one call.

    `an_active_entity_name_has_one_preferred_per_type` is
    `(principal_id, entity_id, name_type_code) WHERE state = 'active' AND
    is_preferred = true`, so two active preferred legal names for one entity
    are refused outright. The correction below is refused nowhere, because the
    predecessor leaves `state = 'active'` -- and therefore leaves this index --
    before the successor claiming the slot is inserted.

    The slot is then counted rather than merely observed on the successor: a
    predecessor left active with `is_preferred` still set would satisfy
    "the successor is preferred" and would still be a second holder of a slot
    the schema admits one holder of.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name(is_preferred=True))
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            successor=_name(
                NAME_TWO, display_value="Synthetic Org Holdings LLC", is_preferred=True
            ),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
    holders = [row for row in rows if row.state is EntityNameState.ACTIVE and row.is_preferred]
    assert [row.entity_name_id for row in holders] == [NAME_TWO]
    predecessor = next(row for row in rows if row.entity_name_id == NAME_ONE)
    assert predecessor.state is EntityNameState.SUPERSEDED
    assert predecessor.superseded_by_entity_name_id == NAME_TWO
    assert predecessor.version == 2
    # The predecessor keeps saying it was the preferred name while it stood:
    # `is_preferred` is cleared by retirement, which withdraws a name, and not
    # by supersession, which replaces one. Erasing it here would rewrite what
    # the superseded row said, which is what `superseded_by_*` exists to avoid.
    assert predecessor.is_preferred is True


def test_an_address_correction_may_claim_the_preferred_slot_its_predecessor_held(
    staged: Engine,
) -> None:
    """`an_active_entity_address_has_one_preferred_per_type`, same shape."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_address(
            PRINCIPAL_A, _address(is_preferred=True)
        )
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_address(
            PRINCIPAL_A,
            entity_address_id=ADDRESS_ONE,
            successor=_address(ADDRESS_TWO, line1="2 Synthetic Way", is_preferred=True),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).addresses(PRINCIPAL_A, ORGANIZATION)
    holders = [row for row in rows if row.state is EntityAddressState.ACTIVE and row.is_preferred]
    assert [row.entity_address_id for row in holders] == [ADDRESS_TWO]
    predecessor = next(row for row in rows if row.entity_address_id == ADDRESS_ONE)
    assert predecessor.state is EntityAddressState.SUPERSEDED
    assert predecessor.superseded_by_entity_address_id == ADDRESS_TWO
    assert predecessor.version == 2


def test_a_channel_correction_may_claim_the_preferred_slot_its_predecessor_held(
    staged: Engine,
) -> None:
    """`an_active_communication_method_has_one_preferred_per_type`, same shape."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_communication_method(
            PRINCIPAL_A, _method(is_preferred=True)
        )
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_communication_method(
            PRINCIPAL_A,
            communication_method_id=METHOD_ONE,
            successor=_method(METHOD_TWO, value="other@example.invalid", is_preferred=True),
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).communication_methods(PRINCIPAL_A, ORGANIZATION)
    holders = [
        row
        for row in rows
        if row.state is EntityCommunicationMethodState.ACTIVE and row.is_preferred
    ]
    assert [row.communication_method_id for row in holders] == [METHOD_TWO]
    predecessor = next(row for row in rows if row.communication_method_id == METHOD_ONE)
    assert predecessor.state is EntityCommunicationMethodState.SUPERSEDED
    assert predecessor.superseded_by_communication_method_id == METHOD_TWO
    assert predecessor.version == 2


# --- What the ordering does *not* close, stated rather than hidden ----------
#
# Releasing the predecessor releases exactly one row from the active-uniqueness
# index. A successor that collides with some *other* active row is a real
# conflict about the world -- two rows claiming one slot -- and it is still
# reported the way the plain `record_*` path reports it: as the driver's
# `IntegrityError`, naming the index, untranslated. That is a disclosed
# limitation of RI-ENT-WP-08 and not a defect closed here, so each family pins
# it by name, and a later work package that translates these into typed
# refusals will find these tests waiting rather than the behaviour unrecorded.


def test_a_name_correction_colliding_with_another_active_row_is_still_refused(
    staged: Engine,
) -> None:
    """Two active legal names; correcting the first *into* the second."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_name(PRINCIPAL_A, _name())
        repo.record_entity_name(
            PRINCIPAL_A, _name(NAME_TWO, display_value="Synthetic Org Holdings LLC")
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            successor=_name(NAME_THREE, display_value="Synthetic Org Holdings LLC"),
            expected_version=1,
            at=LATER,
        )
    assert "an_active_entity_name_is_unique_per_entity_and_type" in str(violated.value)
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
    assert {row.entity_name_id for row in rows} == {NAME_ONE, NAME_TWO}
    assert {row.version for row in rows} == {1}


def test_an_address_correction_colliding_with_another_active_row_is_still_refused(
    staged: Engine,
) -> None:
    """`an_active_entity_address_is_unique_per_entity_and_type`, same disclosure."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_entity_address(PRINCIPAL_A, _address())
        repo.record_entity_address(PRINCIPAL_A, _address(ADDRESS_TWO, line1="2 Synthetic Way"))
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_address(
            PRINCIPAL_A,
            entity_address_id=ADDRESS_ONE,
            successor=_address(ADDRESS_THREE, line1="2 Synthetic Way"),
            expected_version=1,
            at=LATER,
        )
    assert "an_active_entity_address_is_unique_per_entity_and_type" in str(violated.value)
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).addresses(PRINCIPAL_A, ORGANIZATION)
    assert {row.entity_address_id for row in rows} == {ADDRESS_ONE, ADDRESS_TWO}
    assert {row.version for row in rows} == {1}


def test_a_channel_correction_colliding_with_another_active_row_is_still_refused(
    staged: Engine,
) -> None:
    """`an_active_communication_method_is_unique_per_entity_and_type`, same disclosure."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_communication_method(PRINCIPAL_A, _method())
        repo.record_communication_method(
            PRINCIPAL_A, _method(METHOD_TWO, value="other@example.invalid")
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        SqlEntityRepository(connection).supersede_communication_method(
            PRINCIPAL_A,
            communication_method_id=METHOD_ONE,
            successor=_method(METHOD_THREE, value="other@example.invalid"),
            expected_version=1,
            at=LATER,
        )
    assert "an_active_communication_method_is_unique_per_entity_and_type" in str(violated.value)
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).communication_methods(PRINCIPAL_A, ORGANIZATION)
    assert {row.communication_method_id for row in rows} == {METHOD_ONE, METHOD_TWO}
    assert {row.version for row in rows} == {1}


def test_a_participation_correction_colliding_with_another_active_row_is_still_refused(
    staged: Engine,
) -> None:
    """One participant holding two concurrent roles on one project -- which
    `an_active_project_participation_is_unique_per_project_and_role` admits,
    deliberately, by keying on `role_code` -- and a correction of the first
    that moves it onto the second's role."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_project_participation(PRINCIPAL_A, _participation(role_code=ROLE_OF_RECORD))
        repo.record_project_participation(
            PRINCIPAL_A, _participation(PARTICIPATION_TWO, role_code=ROLE_CONSULTANT)
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        SqlEntityRepository(connection).supersede_project_participation(
            PRINCIPAL_A,
            participation_id=PARTICIPATION_ONE,
            successor=_participation(PARTICIPATION_THREE, role_code=ROLE_CONSULTANT),
            expected_version=1,
            at=LATER,
        )
    assert "an_active_project_participation_is_unique_per_project_and_role" in str(violated.value)
    with staged.connect() as connection:
        rows = SqlEntityRepository(connection).project_participations_as_project(
            PRINCIPAL_A, PROJECT
        )
    assert {row.participation_id for row in rows} == {PARTICIPATION_ONE, PARTICIPATION_TWO}
    assert {row.version for row in rows} == {1}


def test_an_affiliation_correction_colliding_with_another_active_row_is_still_refused(
    staged: Engine,
) -> None:
    """Two people, each with a current affiliation, and a correction that
    re-points the second person's affiliation at the first person.

    `an_open_ended_affiliation_is_unique_per_person` keys on the person, so
    this is a genuine conflict -- that person already has a current
    affiliation -- rather than the self-collision the ordering closes. It is
    the one shape of affiliation correction that is still refused, and it is
    refused by the index rather than by anything this program wrote."""
    with staged.begin() as connection:
        repo = SqlEntityRepository(connection)
        repo.record_person_organization_affiliation(PRINCIPAL_A, _affiliation())
        repo.record_person_organization_affiliation(
            PRINCIPAL_A,
            _affiliation(AFFILIATION_TWO, person_entity_id=SECOND_PERSON, job_title="Associate"),
        )
    with pytest.raises(IntegrityError) as violated, staged.begin() as connection:
        SqlEntityRepository(connection).supersede_person_organization_affiliation(
            PRINCIPAL_A,
            affiliation_id=AFFILIATION_TWO,
            successor=_affiliation(AFFILIATION_THREE, job_title="Associate"),
            expected_version=1,
            at=LATER,
        )
    assert "an_open_ended_affiliation_is_unique_per_person" in str(violated.value)
    with staged.connect() as connection:
        repo = SqlEntityRepository(connection)
        rows = [
            row
            for person in (PERSON, SECOND_PERSON)
            for row in repo.person_organization_affiliations_as_person(PRINCIPAL_A, person)
        ]
    assert {row.affiliation_id for row in rows} == {AFFILIATION_ONE, AFFILIATION_TWO}
    assert {row.version for row in rows} == {1}


def test_correcting_an_already_superseded_row_aborts_rather_than_leaving_it_unnamed(
    staged: Engine,
) -> None:
    """Superseding a row that already names a successor, characterised as found.

    The predecessor is at version 2, SUPERSEDED, and already carries
    `superseded_by_entity_name_id`. A second supersession quoting that version
    passes the first `UPDATE` -- which guards on the version alone -- and
    passes the insert, and then the third statement, which guards on
    `state = 'superseded' AND superseded_by_entity_name_id IS NULL`, matches
    nothing. `_refuse_unnamed_successor` raises `RuntimeError` there.

    That is deliberately neither of the two typed refusals: the row is
    present, so `UnknownScopeError` would be a lie, and the version it was
    quoted at was current, so `StaleDirectedVersionError` would be one too.
    This test pins what the code does rather than what a reader might prefer
    it did, and pins the consequence that matters more than the type -- the
    transaction aborts, so the second successor is not committed and the
    predecessor keeps naming the first. The alternative outcome, a superseded
    row whose successor pointer silently stayed at the older row while a
    newer orphan sat active beside it, is what raising here prevents.
    """
    with staged.begin() as connection:
        SqlEntityRepository(connection).record_entity_name(PRINCIPAL_A, _name())
    with staged.begin() as connection:
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            successor=_name(NAME_TWO, display_value="Synthetic Org Holdings LLC"),
            expected_version=1,
            at=LATER,
        )
    with (
        pytest.raises(RuntimeError, match="could not be pointed at its successor") as raised,
        staged.begin() as connection,
    ):
        SqlEntityRepository(connection).supersede_entity_name(
            PRINCIPAL_A,
            entity_name_id=NAME_ONE,
            successor=_name(NAME_THREE, display_value="Synthetic Org Group LLC"),
            expected_version=2,
            at=LATER,
        )
    assert type(raised.value) is RuntimeError
    assert not isinstance(raised.value, StaleDirectedVersionError | UnknownScopeError)

    with staged.connect() as connection:
        rows = {
            row.entity_name_id: row
            for row in SqlEntityRepository(connection).names(PRINCIPAL_A, ORGANIZATION)
        }
    assert set(rows) == {NAME_ONE, NAME_TWO}
    assert rows[NAME_ONE].state is EntityNameState.SUPERSEDED
    assert rows[NAME_ONE].superseded_by_entity_name_id == NAME_TWO
    assert rows[NAME_ONE].version == 2


def test_the_organization_profile_family_revises_in_place_because_it_is_not_temporal(
    staged: Engine,
) -> None:
    """The sixth family, covered for what it is rather than by analogy.

    `entity_organization_profiles` has no `state`, no `superseded_by_*` and no
    `retired_at`; `entity_id` is its whole primary key, so an organization has
    exactly one profile row and there is nowhere for a superseded one to live.
    That is why it carries `revise_organization_profile`, an in-place
    `UPDATE` under the row's version, and no `correct_*` verb at all -- and
    why none of the active-uniqueness ordering above applies to it. The three
    facts are read off the live catalogue rather than off the migration file,
    so a later migration that gave this table a `state` column would redden
    here instead of leaving the reasoning silently stale.

    Then the behaviour those facts imply: a revision leaves one row, at the
    same primary key, with the classification replaced and the version bumped
    once. A revision that inserted a second row would be caught by the count,
    not merely by the values.
    """
    with staged.connect() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'entity_organization_profiles'"
                )
            )
            .scalars()
            .all()
        )
        primary_key = (
            connection.execute(
                text(
                    "SELECT a.attname FROM pg_index i "
                    "JOIN pg_class t ON t.oid = i.indrelid "
                    "JOIN pg_attribute a ON a.attrelid = t.oid "
                    "AND a.attnum = ANY(i.indkey) "
                    "WHERE t.relname = 'entity_organization_profiles' AND i.indisprimary"
                )
            )
            .scalars()
            .all()
        )
    assert "state" not in columns
    assert "retired_at" not in columns
    assert not [column for column in columns if column.startswith("superseded_by")]
    assert list(primary_key) == ["entity_id"]
    assert not hasattr(SqlEntityRepository, "supersede_organization_profile")

    with staged.begin() as connection:
        SqlEntityRepository(connection).record_organization_profile(PRINCIPAL_A, _profile())
    with staged.begin() as connection:
        SqlEntityRepository(connection).revise_organization_profile(
            PRINCIPAL_A,
            entity_id=ORGANIZATION,
            organization_kind_code=OrganizationKindCode.LLC_OR_SPV,
            legal_identity_status_code=LegalIdentityStatusCode.VERIFIED,
            jurisdiction_code="us-fl",
            registration_identifier="P26000012345",
            expected_version=1,
            at=LATER,
        )
    with staged.connect() as connection:
        held = connection.execute(
            select(entity_organization_profiles).where(
                entity_organization_profiles.c.principal_id == PRINCIPAL_A
            )
        ).all()
        revised = SqlEntityRepository(connection).organization_profile(PRINCIPAL_A, ORGANIZATION)
    assert len(held) == 1
    assert revised is not None
    assert revised.entity_id == ORGANIZATION
    assert revised.organization_kind_code is OrganizationKindCode.LLC_OR_SPV
    assert revised.legal_identity_status_code is LegalIdentityStatusCode.VERIFIED
    assert revised.version == 2
    assert revised.created_at == WHEN
    assert revised.updated_at == LATER


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
