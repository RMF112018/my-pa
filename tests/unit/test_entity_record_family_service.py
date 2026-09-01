"""`EntityRecordFamilyService` against the in-memory double: what it writes, and
what it will not decide for a caller (RI-ENT-WP-08, application tier).

The repository tier already has its own database-backed module for these six
families. This one is about the layer above it — the service that turns a
command into a record — and it asserts the four things that layer is the only
place able to get wrong:

* **Absence as scoping.** No command dataclass declares `principal_id`,
  `version`, `state`, a `superseded_by_*`, `retired_at` or `updated_at`, so
  there is no field a later change could start honouring. That is asserted
  structurally over `dataclasses.fields`, because a prose promise about a field
  that does not exist is exactly the promise a new field breaks silently.
* **A correction is two rows.** The predecessor is still there afterwards, its
  content byte-identical, marked SUPERSEDED and naming its successor. The
  assertion that matters is the *survival* of the old row: a test that only read
  the new one would pass just as happily against a service that rewrote the old
  row in place, which is the failure the whole temporal shape exists to prevent.
* **The four no-guess rules, each as a refusal a caller can reach.** A name with
  no stated type, an affiliation with a blank organization, a participation with
  a blank taxonomy code, and every closed vocabulary that carries no default.
  Each is asserted at the exact helper that makes the refusal, and the legal-name
  rule additionally walks the service module's own syntax tree for any reference
  to a `NameTypeCode` member — because "there is no code path that chooses one"
  is a claim about the code, and reading the code is the only way to check it.
* **Normalization, and only normalization.** The written key is recomputed here
  from the display form the caller gave, with the domain's own normalizer, so a
  service that derived it from anything else reddens.

The last section is about the double rather than the service: `_Entities`'
write-path refusals, including the deliberate collapse in `supersede_assertion`
that makes its stale case and its unreachable case indistinguishable. That
parity is a property of the *double*, not of the service, and it is asserted
here rather than in a module of its own because it is proved with the same
`World` fixture and the same seeded entities every test above uses — a third
module would duplicate the whole staging apparatus to hold nine assertions.

Every identity here is synthetic and every address is `example.invalid`.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from dataclasses import MISSING, dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.application import entity_record_families as service_module
from my_pa.application.entity_record_families import (
    CorrectAffiliation,
    CorrectCommunicationMethod,
    CorrectedFact,
    CorrectEntityAddress,
    CorrectEntityName,
    CorrectProjectParticipation,
    EntityRecordFamily,
    EntityRecordFamilyService,
    RecordAffiliation,
    RecordCommunicationMethod,
    RecordedFact,
    RecordEntityAddress,
    RecordEntityName,
    RecordOrganizationProfile,
    RecordProjectParticipation,
    RetireAffiliation,
    RetireCommunicationMethod,
    RetiredFact,
    RetireEntityAddress,
    RetireEntityName,
    RetireProjectParticipation,
    RevisedFact,
    ReviseOrganizationProfile,
    StatedAssertion,
    StatedEvidence,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.ports import EntitiesRepository, UnknownScopeError
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityAddressState,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityProjectParticipationState,
    EntityStatus,
    EntityType,
    LegalIdentityStatusCode,
    MergedEndpointError,
    NameTypeCode,
    OrganizationKindCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliationState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    StaleDirectedVersionError,
    normalize_address,
    normalize_communication_value,
)
from my_pa.domain.relationship.governance import (
    DEFAULT_MUTATION_AUTHORITY,
    AssertionStatus,
    EntityAssertion,
    EvidenceRole,
    MutationAuthority,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER: Final = "prn_ffff0009ffff0009ffff0009"

PERSON: Final = "ent_aaaa0001aaaa0001"
ORGANIZATION: Final = "ent_bbbb0002bbbb0002"
PROJECT: Final = "ent_cccc0003cccc0003"
#: The other Principal's own entity. Distinct because `entity_id` is a global
#: primary key and no two rows may share one, whoever holds them.
THEIRS: Final = "ent_dddd0004dddd0004"
MERGED: Final = "ent_eeee0005eeee0005"

OBSERVATION: Final = "eobs_aaaa0001aaaa0001"
ABSENT_NAME: Final = "enam_ffff0009ffff0009"
ABSENT_ASSERTION: Final = "east_ffff0009ffff0009"
SECOND_ASSERTION: Final = "east_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 9, 1, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

#: Every command dataclass this module publishes, spelled out rather than
#: derived, so a seventeenth verb arriving with a `principal_id` on it has to be
#: added here before the structural assertions below will look at it — and
#: `test_the_command_surface_is_exactly_these_seventeen` reddens until it is.
COMMANDS: Final = (
    RecordEntityName,
    CorrectEntityName,
    RetireEntityName,
    RecordOrganizationProfile,
    ReviseOrganizationProfile,
    RecordEntityAddress,
    CorrectEntityAddress,
    RetireEntityAddress,
    RecordCommunicationMethod,
    CorrectCommunicationMethod,
    RetireCommunicationMethod,
    RecordProjectParticipation,
    CorrectProjectParticipation,
    RetireProjectParticipation,
    RecordAffiliation,
    CorrectAffiliation,
    RetireAffiliation,
)

#: The columns a caller may never state, because stating one is how a payload
#: starts deciding whose row it is or what lifecycle stage it is in.
#: `expected_version` is deliberately *not* here and is matched exactly rather
#: than by substring: it is the caller's own optimistic guard and is required.
REFUSED_FIELD_NAMES: Final = frozenset(
    {"principal_id", "version", "state", "retired_at", "updated_at"}
)


def _entity(
    entity_id: str,
    name: str,
    entity_type: EntityType,
    *,
    principal_id: str = PRINCIPAL,
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
def repository(world: World) -> EntitiesRepository:
    """A person, an organization, a project, one merged-away organization, and
    one entity belonging to a different Principal entirely."""
    entities = FakeUnitOfWork(world).entities
    entities.create(PRINCIPAL, _entity(PERSON, "Alice Synthetic", EntityType.PERSON))
    entities.create(PRINCIPAL, _entity(ORGANIZATION, "Synthetic Org", EntityType.ORGANIZATION))
    entities.create(PRINCIPAL, _entity(PROJECT, "Harbour Tower", EntityType.PROJECT))
    entities.create(
        PRINCIPAL,
        _entity(
            MERGED,
            "Merged Away Org",
            EntityType.ORGANIZATION,
            status=EntityStatus.MERGED_REDIRECT,
            superseded_by_entity_id=ORGANIZATION,
        ),
    )
    entities.create(OTHER, _entity(THEIRS, "Bob Synthetic", EntityType.PERSON, principal_id=OTHER))
    return entities


@pytest.fixture
def service() -> EntityRecordFamilyService:
    return EntityRecordFamilyService()


# --- Commands: the five families that carry a full record shape -------------


def _name_command(**overrides: object) -> RecordEntityName:
    stated: dict[str, Any] = {
        "entity_id": ORGANIZATION,
        "display_value": "Synthetic Org LLC",
        "name_type_code": NameTypeCode.LEGAL,
    }
    stated.update(overrides)
    return RecordEntityName(**stated)


def _address_command(**overrides: object) -> RecordEntityAddress:
    stated: dict[str, Any] = {
        "entity_id": ORGANIZATION,
        "address_type_code": AddressTypeCode.HEADQUARTERS,
        "raw_value": "1 Synthetic Way, Springfield",
        "line1": "1 Synthetic Way",
        "city": "Springfield",
    }
    stated.update(overrides)
    return RecordEntityAddress(**stated)


def _channel_command(**overrides: object) -> RecordCommunicationMethod:
    stated: dict[str, Any] = {
        "entity_id": ORGANIZATION,
        "method_type_code": CommunicationMethodTypeCode.EMAIL,
        "usage_context_code": CommunicationUsageContextCode.CORPORATE,
        "display_value": "Reception@Example.Invalid",
    }
    stated.update(overrides)
    return RecordCommunicationMethod(**stated)


def _participation_command(**overrides: object) -> RecordProjectParticipation:
    stated: dict[str, Any] = {
        "project_entity_id": PROJECT,
        "participant_entity_id": ORGANIZATION,
        "project_display_name": "Harbour Tower",
        "role_basis_code": RoleBasisCode.CONTRACTUAL,
        "stakeholder_side_code": StakeholderSideCode.CONSULTANT,
        "stakeholder_class_code": StakeholderClassCode.CORE,
        "relationship_status_code": ParticipationStatusCode.ACTIVE,
    }
    stated.update(overrides)
    return RecordProjectParticipation(**stated)


def _affiliation_command(**overrides: object) -> RecordAffiliation:
    stated: dict[str, Any] = {
        "person_entity_id": PERSON,
        "affiliation_type_code": AffiliationTypeCode.EMPLOYMENT,
        "organization_entity_id": ORGANIZATION,
        "job_title": "Principal Architect",
    }
    stated.update(overrides)
    return RecordAffiliation(**stated)


def _profile_command(**overrides: object) -> RecordOrganizationProfile:
    stated: dict[str, Any] = {
        "entity_id": ORGANIZATION,
        "organization_kind_code": OrganizationKindCode.COMPANY,
        "legal_identity_status_code": LegalIdentityStatusCode.UNRESOLVED,
        "jurisdiction_code": "us-fl",
        "registration_identifier": "P26000012345",
    }
    stated.update(overrides)
    return RecordOrganizationProfile(**stated)


# --- One description per temporal family, so a lifecycle claim is asserted
#     about all five rather than about whichever one a test happened to pick ---


@dataclass(frozen=True)
class _Family:
    """How to record, correct and retire one of the five temporal families, and
    where its rows land in the `World`."""

    label: str
    rows: Callable[[World], list[Any]]
    key: str
    successor_key: str
    superseded_state: Any
    retired_state: Any
    family: EntityRecordFamily
    record: Callable[[EntityRecordFamilyService, EntitiesRepository], RecordedFact]
    correct: Callable[[EntityRecordFamilyService, EntitiesRepository, str, int], CorrectedFact]
    retire: Callable[[EntityRecordFamilyService, EntitiesRepository, str, int], RetiredFact]


def _held[RowT](rows: list[RowT], key: str, identifier: str) -> RowT:
    return next(row for row in rows if getattr(row, key) == identifier)


FAMILIES: Final = (
    _Family(
        label="name",
        rows=lambda world: world.entity_names,
        key="entity_name_id",
        successor_key="superseded_by_entity_name_id",
        superseded_state=EntityNameState.SUPERSEDED,
        retired_state=EntityNameState.RETIRED,
        family=EntityRecordFamily.NAME,
        record=lambda service, repository: service.record_name(
            repository, _name_command(), principal_id=PRINCIPAL, at=WHEN
        ),
        correct=lambda service, repository, record_id, version: service.correct_name(
            repository,
            CorrectEntityName(
                entity_name_id=record_id,
                expected_version=version,
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
        retire=lambda service, repository, record_id, version: service.retire_name(
            repository,
            RetireEntityName(entity_name_id=record_id, expected_version=version),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
    ),
    _Family(
        label="address",
        rows=lambda world: world.entity_addresses,
        key="entity_address_id",
        successor_key="superseded_by_entity_address_id",
        superseded_state=EntityAddressState.SUPERSEDED,
        retired_state=EntityAddressState.RETIRED,
        family=EntityRecordFamily.ADDRESS,
        record=lambda service, repository: service.record_address(
            repository, _address_command(), principal_id=PRINCIPAL, at=WHEN
        ),
        correct=lambda service, repository, record_id, version: service.correct_address(
            repository,
            CorrectEntityAddress(
                entity_address_id=record_id,
                expected_version=version,
                entity_id=ORGANIZATION,
                address_type_code=AddressTypeCode.HEADQUARTERS,
                raw_value="2 Synthetic Way, Springfield",
                line1="2 Synthetic Way",
                city="Springfield",
            ),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
        retire=lambda service, repository, record_id, version: service.retire_address(
            repository,
            RetireEntityAddress(entity_address_id=record_id, expected_version=version),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
    ),
    _Family(
        label="communication method",
        rows=lambda world: world.entity_communication_methods,
        key="communication_method_id",
        successor_key="superseded_by_communication_method_id",
        superseded_state=EntityCommunicationMethodState.SUPERSEDED,
        retired_state=EntityCommunicationMethodState.RETIRED,
        family=EntityRecordFamily.COMMUNICATION_METHOD,
        record=lambda service, repository: service.record_communication_method(
            repository, _channel_command(), principal_id=PRINCIPAL, at=WHEN
        ),
        correct=lambda service, repository, record_id, version: (
            service.correct_communication_method(
                repository,
                CorrectCommunicationMethod(
                    communication_method_id=record_id,
                    expected_version=version,
                    entity_id=ORGANIZATION,
                    method_type_code=CommunicationMethodTypeCode.EMAIL,
                    usage_context_code=CommunicationUsageContextCode.CORPORATE,
                    display_value="Desk@Example.Invalid",
                ),
                principal_id=PRINCIPAL,
                at=LATER,
            )
        ),
        retire=lambda service, repository, record_id, version: service.retire_communication_method(
            repository,
            RetireCommunicationMethod(communication_method_id=record_id, expected_version=version),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
    ),
    _Family(
        label="project participation",
        rows=lambda world: world.entity_project_participations,
        key="participation_id",
        successor_key="superseded_by_participation_id",
        superseded_state=EntityProjectParticipationState.SUPERSEDED,
        retired_state=EntityProjectParticipationState.RETIRED,
        family=EntityRecordFamily.PROJECT_PARTICIPATION,
        record=lambda service, repository: service.record_project_participation(
            repository, _participation_command(), principal_id=PRINCIPAL, at=WHEN
        ),
        correct=lambda service, repository, record_id, version: (
            service.correct_project_participation(
                repository,
                CorrectProjectParticipation(
                    participation_id=record_id,
                    expected_version=version,
                    project_entity_id=PROJECT,
                    participant_entity_id=ORGANIZATION,
                    project_display_name="Harbour Tower",
                    role_basis_code=RoleBasisCode.CONTRACTUAL,
                    stakeholder_side_code=StakeholderSideCode.CONSULTANT,
                    stakeholder_class_code=StakeholderClassCode.CORE,
                    relationship_status_code=ParticipationStatusCode.ACTIVE,
                    scope_text="the north elevation",
                ),
                principal_id=PRINCIPAL,
                at=LATER,
            )
        ),
        retire=lambda service, repository, record_id, version: service.retire_project_participation(
            repository,
            RetireProjectParticipation(participation_id=record_id, expected_version=version),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
    ),
    _Family(
        label="affiliation",
        rows=lambda world: world.entity_person_organization_affiliations,
        key="affiliation_id",
        successor_key="superseded_by_affiliation_id",
        superseded_state=PersonOrganizationAffiliationState.SUPERSEDED,
        retired_state=PersonOrganizationAffiliationState.RETIRED,
        family=EntityRecordFamily.PERSON_ORGANIZATION_AFFILIATION,
        record=lambda service, repository: service.record_affiliation(
            repository, _affiliation_command(), principal_id=PRINCIPAL, at=WHEN
        ),
        correct=lambda service, repository, record_id, version: service.correct_affiliation(
            repository,
            CorrectAffiliation(
                affiliation_id=record_id,
                expected_version=version,
                person_entity_id=PERSON,
                affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
                organization_entity_id=ORGANIZATION,
                job_title="Associate Principal",
            ),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
        retire=lambda service, repository, record_id, version: service.retire_affiliation(
            repository,
            RetireAffiliation(affiliation_id=record_id, expected_version=version),
            principal_id=PRINCIPAL,
            at=LATER,
        ),
    ),
)

_FAMILY_CASES: Final = [pytest.param(family, id=family.label) for family in FAMILIES]


# --- A1. Principal scoping is absence, not validation ------------------------


def test_the_command_surface_is_exactly_these_seventeen() -> None:
    """`COMMANDS` is the set every structural claim below quantifies over, so a
    new command that is not in it would be a command nothing here inspects."""
    published = {
        name
        for name in service_module.__all__
        if name.startswith(("Record", "Correct", "Retire", "Revise")) and not name.endswith("Fact")
    }
    assert published == {command.__name__ for command in COMMANDS}


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.__name__)
def test_no_command_declares_a_principal_or_a_lifecycle_column(command: type) -> None:
    """A field that can be sent is a field a later change can start honouring.
    Asserted over `dataclasses.fields` rather than in prose, so adding one
    reddens here instead of being noticed in review."""
    named = {declared.name for declared in fields(command)}
    assert named & REFUSED_FIELD_NAMES == set()
    assert [name for name in named if name.startswith("superseded_by")] == []


@pytest.mark.parametrize(
    "carried", [StatedAssertion, StatedEvidence], ids=["assertion", "evidence"]
)
def test_no_carried_claim_declares_a_principal_an_authority_or_a_target(carried: type) -> None:
    """The two things a command may attach are scoped by the same absence: the
    subject is the row the service just wrote and the authority is the method's
    own, so neither is a field a payload can reach."""
    named = {declared.name for declared in fields(carried)}
    assert named & REFUSED_FIELD_NAMES == set()
    assert "asserted_by" not in named
    assert [name for name in named if name.startswith("target")] == []


def test_a_written_record_carries_the_principal_the_caller_passed(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The keyword argument is the only place a Principal enters, and it is what
    lands on the row."""
    service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    (written,) = world.entity_names
    assert written.principal_id == PRINCIPAL


def test_a_record_for_an_entity_another_principal_holds_is_refused(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The same `UnknownScopeError` an absent entity gets, and nothing written."""
    with pytest.raises(UnknownScopeError):
        service.record_name(
            repository, _name_command(entity_id=THEIRS), principal_id=PRINCIPAL, at=WHEN
        )
    assert world.entity_names == []


def test_a_record_written_as_another_principal_cannot_reach_this_ones_entity(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """Scoping is applied to the entity, not merely stamped on the row: acting as
    `OTHER` against this Principal's organization is refused rather than filed
    under `OTHER`."""
    with pytest.raises(UnknownScopeError):
        service.record_name(repository, _name_command(), principal_id=OTHER, at=WHEN)
    assert world.entity_names == []


# --- A2. A correction is a new row plus a supersession -----------------------


@pytest.mark.parametrize("family", _FAMILY_CASES)
def test_a_correction_writes_a_new_row_and_leaves_the_old_one_standing(
    world: World,
    repository: EntitiesRepository,
    service: EntityRecordFamilyService,
    family: _Family,
) -> None:
    """The predecessor's *survival* is the assertion. A service that rewrote the
    old row in place would satisfy every claim about the successor and fail
    here, which is the only reason this test reads the old row at all.

    Every content column is compared by reconstruction: the predecessor after
    the correction, with only its four lifecycle columns put back, must equal
    exactly what it was before. So a correction that quietly edited a display
    value, a code or a window while superseding reddens too.
    """
    recorded = family.record(service, repository)
    rows = family.rows(world)
    before = _held(rows, family.key, recorded.record_id)

    corrected = family.correct(service, repository, recorded.record_id, 1)

    assert isinstance(corrected, CorrectedFact)
    assert corrected.family is family.family
    assert corrected.superseded_record_id == recorded.record_id
    assert corrected.record_id != recorded.record_id
    assert corrected.recorded_at == LATER

    rows = family.rows(world)
    assert len(rows) == 2
    successor = _held(rows, family.key, corrected.record_id)
    assert getattr(successor, family.successor_key) is None
    assert successor.version == 1

    survivor = _held(rows, family.key, recorded.record_id)
    assert survivor.state is family.superseded_state
    assert getattr(survivor, family.successor_key) == corrected.record_id
    assert survivor.version == 2
    assert survivor.updated_at == LATER
    restored = replace(
        survivor,
        state=before.state,
        version=before.version,
        updated_at=before.updated_at,
        **{family.successor_key: getattr(before, family.successor_key)},
    )
    assert restored == before


@pytest.mark.parametrize("family", _FAMILY_CASES)
def test_a_retirement_keeps_the_row_and_marks_it(
    world: World,
    repository: EntitiesRepository,
    service: EntityRecordFamilyService,
    family: _Family,
) -> None:
    """Retirement withdraws a record from service; it does not remove it."""
    recorded = family.record(service, repository)
    retired = family.retire(service, repository, recorded.record_id, 1)

    assert isinstance(retired, RetiredFact)
    assert retired.family is family.family
    assert retired.record_id == recorded.record_id
    assert retired.retired_at == LATER

    rows = family.rows(world)
    assert len(rows) == 1
    held = _held(rows, family.key, recorded.record_id)
    assert held.state is family.retired_state
    assert held.retired_at == LATER


def test_a_receipt_names_a_record_and_never_the_value_it_recorded(
    repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """`RecordedFact` acknowledges durability. A receipt that echoed the fact
    would put a name on a second surface for no gain."""
    named = {declared.name for declared in fields(RecordedFact)}
    assert named == {"family", "record_id", "recorded_at", "assertion_id", "evidence_ids"}
    recorded = service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    assert recorded.family is EntityRecordFamily.NAME
    assert recorded.recorded_at == WHEN


# --- A3. `EntityOrganizationProfile` is the singleton exception ---------------


def test_the_organization_profile_has_no_retirement_verb() -> None:
    """One row per entity, no `state`, no `superseded_by_*` -- nowhere to retire
    to and nothing a supersession could name. This module declares no verb the
    port has none of, and that is checked rather than described."""
    assert not hasattr(EntityRecordFamilyService, "retire_organization_profile")
    assert not hasattr(EntityRecordFamilyService, "correct_organization_profile")
    assert hasattr(EntityRecordFamilyService, "revise_organization_profile")


def test_a_profile_revision_corrects_in_place_under_its_version(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """One row before, one row after, at the next version -- not a successor and
    a supersession, which is what the other five families do."""
    service.record_organization_profile(
        repository, _profile_command(), principal_id=PRINCIPAL, at=WHEN
    )
    revised = service.revise_organization_profile(
        repository,
        ReviseOrganizationProfile(
            entity_id=ORGANIZATION,
            expected_version=1,
            organization_kind_code=OrganizationKindCode.NONPROFIT,
            legal_identity_status_code=LegalIdentityStatusCode.VERIFIED,
            jurisdiction_code="us-ny",
            registration_identifier="N26000099999",
        ),
        principal_id=PRINCIPAL,
        at=LATER,
    )
    assert isinstance(revised, RevisedFact)
    assert revised.family is EntityRecordFamily.ORGANIZATION_PROFILE
    assert revised.record_id == ORGANIZATION
    assert revised.revised_at == LATER

    (held,) = world.entity_organization_profiles
    assert held.entity_id == ORGANIZATION
    assert held.version == 2
    assert held.organization_kind_code is OrganizationKindCode.NONPROFIT
    assert held.legal_identity_status_code is LegalIdentityStatusCode.VERIFIED
    assert held.jurisdiction_code == "us-ny"
    assert held.registration_identifier == "N26000099999"


def test_a_profile_revision_that_omits_a_nullable_field_clears_it(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The quiet-carry-forward failure, proved to be absent. Both nullable
    columns are set, both are then revised to `None`, and both are `None`
    afterwards -- a revision that preserved them would leave a jurisdiction the
    caller believes it cleared."""
    service.record_organization_profile(
        repository,
        _profile_command(jurisdiction_code="us-fl", registration_identifier="P26000012345"),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (before,) = world.entity_organization_profiles
    assert before.jurisdiction_code == "us-fl"
    assert before.registration_identifier == "P26000012345"

    service.revise_organization_profile(
        repository,
        ReviseOrganizationProfile(
            entity_id=ORGANIZATION,
            expected_version=1,
            organization_kind_code=OrganizationKindCode.COMPANY,
            legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
            jurisdiction_code=None,
            registration_identifier=None,
        ),
        principal_id=PRINCIPAL,
        at=LATER,
    )
    (after,) = world.entity_organization_profiles
    assert after.jurisdiction_code is None
    assert after.registration_identifier is None


def test_a_profile_revision_states_both_nullable_columns_with_no_default() -> None:
    """A revision that *could* omit them would be unable to distinguish
    "unchanged" from "cleared", so neither carries a default."""
    stated = {declared.name: declared for declared in fields(ReviseOrganizationProfile)}
    for name in ("jurisdiction_code", "registration_identifier"):
        declared = stated[name]
        assert declared.default is MISSING


# --- A4. Optimistic versions -------------------------------------------------


@pytest.mark.parametrize("family", _FAMILY_CASES)
def test_a_correction_at_a_stale_version_is_refused(
    repository: EntitiesRepository, service: EntityRecordFamilyService, family: _Family
) -> None:
    """The repository's own classification surfaces unchanged: this service
    translates neither error, so a second place could not disagree with the
    first."""
    recorded = family.record(service, repository)
    with pytest.raises(StaleDirectedVersionError):
        family.correct(service, repository, recorded.record_id, 99)


@pytest.mark.parametrize("family", _FAMILY_CASES)
def test_a_retirement_at_a_stale_version_is_refused(
    repository: EntitiesRepository, service: EntityRecordFamilyService, family: _Family
) -> None:
    recorded = family.record(service, repository)
    with pytest.raises(StaleDirectedVersionError):
        family.retire(service, repository, recorded.record_id, 99)


def test_an_unreachable_row_gets_exactly_the_answer_an_absent_row_gets(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """Two refusals, indistinguishable by type and by message, so a caller cannot
    use a retirement to learn that a row exists in another partition."""
    other_entities = FakeUnitOfWork(world).entities
    other_entities.create(
        OTHER,
        _entity("ent_777700077777000a", "Their Org", EntityType.ORGANIZATION, principal_id=OTHER),
    )
    service.record_name(
        repository,
        _name_command(entity_id="ent_777700077777000a"),
        principal_id=OTHER,
        at=WHEN,
    )
    (theirs,) = world.entity_names

    with pytest.raises(UnknownScopeError) as unreachable:
        service.retire_name(
            repository,
            RetireEntityName(entity_name_id=theirs.entity_name_id, expected_version=1),
            principal_id=PRINCIPAL,
            at=LATER,
        )
    with pytest.raises(UnknownScopeError) as absent:
        service.retire_name(
            repository,
            RetireEntityName(entity_name_id=ABSENT_NAME, expected_version=1),
            principal_id=PRINCIPAL,
            at=LATER,
        )
    assert type(unreachable.value) is type(absent.value)
    assert str(unreachable.value) == str(absent.value)


def test_a_correction_that_fails_at_the_supersession_leaves_the_successor_written(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The module's own stated limitation, locked so it cannot become an
    undisclosed one. The service holds no compensating write: outside a
    transaction, a `record_*` that succeeded followed by a `supersede_*` that
    raised leaves the successor row written and the predecessor still ACTIVE,
    and both remain correctable by their own identifiers. The guarantee belongs
    to the caller's transaction, and this asserts that the service does not
    quietly claim it."""
    recorded = service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    with pytest.raises(StaleDirectedVersionError):
        service.correct_name(
            repository,
            CorrectEntityName(
                entity_name_id=recorded.record_id,
                expected_version=99,
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=NameTypeCode.LEGAL,
            ),
            principal_id=PRINCIPAL,
            at=LATER,
        )
    assert len(world.entity_names) == 2
    predecessor = _held(world.entity_names, "entity_name_id", recorded.record_id)
    assert predecessor.state is EntityNameState.ACTIVE
    assert predecessor.superseded_by_entity_name_id is None


# --- A5. Normalization is performed, and is only normalization ---------------


def test_a_name_is_written_with_the_key_its_own_display_form_normalizes_to(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """Recomputed here from the display value the caller gave, with the domain's
    own normalizer -- so a service deriving the key from anything else reddens."""
    display = "  Álvaro   O'Brien  &  Partners, LLC  "
    service.record_name(
        repository, _name_command(display_value=display), principal_id=PRINCIPAL, at=WHEN
    )
    (written,) = world.entity_names
    assert written.display_value == display
    assert written.normalized_value == normalize_name(display)


def test_an_address_is_normalized_over_exactly_the_structure_the_caller_stated(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """`raw_value` is never split to invent a structure, and the key is computed
    over the fields that are actually present."""
    service.record_address(
        repository,
        _address_command(
            raw_value="Suite 9, 1 Synthetic Way, Springfield, 40404",
            line1="1 Synthetic Way",
            line2="Suite 9",
            city="Springfield",
            postal_code="40404",
        ),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_addresses
    assert written.normalized_address_value == normalize_address(
        line1="1 Synthetic Way",
        line2="Suite 9",
        city="Springfield",
        region=None,
        postal_code="40404",
        country=None,
        raw_value="Suite 9, 1 Synthetic Way, Springfield, 40404",
    )
    assert written.region is None
    assert written.country is None


def test_a_channel_is_normalized_for_the_method_type_the_caller_stated(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The type is the caller's; the normalizer dispatches on it rather than
    reading the string's shape and concluding what kind of channel it is."""
    service.record_communication_method(
        repository,
        _channel_command(display_value="Reception@Example.Invalid"),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_communication_methods
    assert written.display_value == "Reception@Example.Invalid"
    assert written.normalized_value == normalize_communication_value(
        CommunicationMethodTypeCode.EMAIL, "Reception@Example.Invalid"
    )


def test_a_display_value_that_normalizes_to_nothing_matchable_is_refused(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """Refused as the malformed request it is, rather than reaching the domain as
    an unclassified `ValueError` or being stored as a key that matches nothing."""
    with pytest.raises(InvalidRequestError) as refused:
        service.record_name(
            repository,
            _name_command(display_value="  ... --- ,,, "),
            principal_id=PRINCIPAL,
            at=WHEN,
        )
    assert refused.value.safe_details == (SafeDetail.DISPLAY_VALUE,)
    assert world.entity_names == []


def test_a_channel_value_that_is_not_of_its_stated_type_is_refused(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """Validation against a type the caller committed to -- never detection of an
    unstated one."""
    with pytest.raises(InvalidRequestError) as refused:
        service.record_communication_method(
            repository,
            _channel_command(display_value="not-a-mailbox"),
            principal_id=PRINCIPAL,
            at=WHEN,
        )
    assert refused.value.safe_details == (SafeDetail.DISPLAY_VALUE,)
    assert world.entity_communication_methods == []


# --- A6. The four no-guess rules --------------------------------------------


def test_a_name_with_no_stated_type_is_refused(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """`_stated_name_type`, reached through `record_name`. The whole of the
    "never infer a legal name" rule on the write side."""
    with pytest.raises(InvalidRequestError) as refused:
        service.record_name(
            repository, _name_command(name_type_code=None), principal_id=PRINCIPAL, at=WHEN
        )
    assert refused.value.safe_details == (SafeDetail.NAME,)
    assert world.entity_names == []


def test_a_correction_with_no_stated_name_type_is_refused_too(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The correction path reaches the same helper, so a caller cannot get an
    unstated name type in through the second door."""
    recorded = service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    with pytest.raises(InvalidRequestError) as refused:
        service.correct_name(
            repository,
            CorrectEntityName(
                entity_name_id=recorded.record_id,
                expected_version=1,
                entity_id=ORGANIZATION,
                display_value="Synthetic Org Holdings LLC",
                name_type_code=None,
            ),
            principal_id=PRINCIPAL,
            at=LATER,
        )
    assert refused.value.safe_details == (SafeDetail.NAME,)
    assert len(world.entity_names) == 1


def test_a_legal_name_row_exists_only_because_a_caller_said_legal(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The positive half, and the sharp end of the rule. The identical display
    form is recorded twice: once as `LEGAL` because the caller said `LEGAL`, and
    once as `DISPLAY` because the caller said `DISPLAY`. The second row stays
    `DISPLAY` -- the display form is never folded into the legal one."""
    service.record_name(
        repository,
        _name_command(display_value="Synthetic Org LLC", name_type_code=NameTypeCode.LEGAL),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    service.record_name(
        repository,
        _name_command(display_value="Synthetic Org LLC", name_type_code=NameTypeCode.DISPLAY),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    written = {row.name_type_code for row in world.entity_names}
    assert written == {NameTypeCode.LEGAL, NameTypeCode.DISPLAY}
    assert len(world.entity_names) == 2


def test_the_service_module_names_no_name_type_member_anywhere_in_its_code() -> None:
    """ "There is no code path in this module that chooses a `NameTypeCode`" is a
    claim about the code, so this reads the code. The module's syntax tree is
    walked for any `NameTypeCode.<member>` reference; a fallback added tomorrow
    reddens here even if every refusal test above still passes, because a
    fallback in a branch no test reaches is exactly the shape that would."""
    tree = ast.parse(inspect.getsource(service_module))
    reached = [
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "NameTypeCode"
    ]
    assert reached == []


def test_an_affiliation_with_no_organization_creates_or_selects_none(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """`_stated_identifier` passes `None` through untouched. Nothing here creates
    an organization entity, selects one by name, or substitutes a placeholder to
    satisfy the nullable foreign key -- so the entity store is the same size
    afterwards as it was before."""
    before = len(world.entities)
    service.record_affiliation(
        repository,
        _affiliation_command(organization_entity_id=None, job_title="Independent Consultant"),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_person_organization_affiliations
    assert written.organization_entity_id is None
    assert len(world.entities) == before


def test_an_affiliation_with_a_blank_organization_is_refused(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """A blank string is refused rather than read as "work out who belongs
    here"."""
    with pytest.raises(InvalidRequestError) as refused:
        service.record_affiliation(
            repository,
            _affiliation_command(organization_entity_id="   "),
            principal_id=PRINCIPAL,
            at=WHEN,
        )
    assert refused.value.safe_details == (SafeDetail.ENTITY_ID,)
    assert world.entity_person_organization_affiliations == []


def test_a_participation_keeps_its_text_and_leaves_the_codes_absent(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """`_stated_code` maps neither direction. A caller that knows only the words
    a source used supplies the text; the codes stay `None`, which is the honest
    record of what was known."""
    service.record_project_participation(
        repository,
        _participation_command(
            role_text="structural engineer of record", discipline_text="structural"
        ),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_project_participations
    assert written.role_text == "structural engineer of record"
    assert written.discipline_text == "structural"
    assert written.role_code is None
    assert written.discipline_code is None


@pytest.mark.parametrize(
    ("field_name", "detail"),
    [("role_code", SafeDetail.ROLE), ("discipline_code", SafeDetail.DISCIPLINE)],
    ids=["role", "discipline"],
)
def test_a_blank_taxonomy_code_is_refused_naming_its_own_taxonomy(
    world: World,
    repository: EntitiesRepository,
    service: EntityRecordFamilyService,
    field_name: str,
    detail: SafeDetail,
) -> None:
    """Refused rather than read as "derive it from the text beside it", and the
    refusal names which taxonomy the caller should quote instead."""
    with pytest.raises(InvalidRequestError) as refused:
        service.record_project_participation(
            repository,
            _participation_command(**{field_name: "   "}),
            principal_id=PRINCIPAL,
            at=WHEN,
        )
    assert refused.value.safe_details == (detail,)
    assert world.entity_project_participations == []


def test_no_closed_vocabulary_a_caller_must_decide_carries_a_default() -> None:
    """Unknown stays unresolved. Every closed vocabulary on every command is a
    field with no default, so omitting one is refused by the constructor rather
    than filled in -- with exactly one exception, which is the vocabulary's own
    name for "not yet known" rather than an affirmative value.

    `name_type_code` is optional in the type and required in fact: its absence
    is answered by `_stated_name_type`'s refusal, which a caller can read and act
    on, rather than by a `TypeError` from a constructor.
    """
    permitted = {
        ("RecordCommunicationMethod", "verification_status_code"): (
            CommunicationVerificationStatusCode.UNRESOLVED
        ),
        ("CorrectCommunicationMethod", "verification_status_code"): (
            CommunicationVerificationStatusCode.UNRESOLVED
        ),
        ("RecordEntityName", "name_type_code"): None,
        ("CorrectEntityName", "name_type_code"): None,
    }
    inspected: list[tuple[str, str]] = []
    for command in COMMANDS:
        for declared in fields(command):
            if "Code" not in str(declared.type) and "Status" not in str(declared.type):
                continue
            inspected.append((command.__name__, declared.name))
            if declared.default is MISSING:
                continue
            key = (command.__name__, declared.name)
            assert key in permitted, (
                f"{command.__name__}.{declared.name} defaults to a closed vocabulary "
                "member no caller stated"
            )
            assert declared.default == permitted[key]
    # The anti-vacuity half. A scan that matched nothing -- because a type was
    # renamed out of the `Code`/`Status` shape this reads, or because a command
    # left `COMMANDS` -- would pass every assertion above while checking
    # nothing at all, which is the failure this whole module is written against.
    assert len(inspected) == 24
    assert set(permitted) <= set(inspected)


@pytest.mark.parametrize(
    ("command", "stated"),
    [
        (RecordEntityAddress, {"entity_id": ORGANIZATION, "raw_value": "1 Synthetic Way"}),
        (
            RecordCommunicationMethod,
            {"entity_id": ORGANIZATION, "display_value": "reception@example.invalid"},
        ),
        (RecordAffiliation, {"person_entity_id": PERSON}),
        (
            RecordOrganizationProfile,
            {"entity_id": ORGANIZATION, "organization_kind_code": OrganizationKindCode.COMPANY},
        ),
    ],
    ids=["address", "communication method", "affiliation", "organization profile"],
)
def test_a_command_omitting_a_closed_vocabulary_is_refused_by_its_constructor(
    command: type, stated: dict[str, Any]
) -> None:
    """The behavioural half of the rule above: omitting one of these is a
    `TypeError` at construction, never a substantive value chosen here."""
    with pytest.raises(TypeError):
        command(**stated)


# --- A7. Assertions ----------------------------------------------------------


def test_a_command_carrying_an_assertion_writes_one_naming_the_row_just_written(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The target is the row this call wrote, and the status is the one the
    caller stated -- nothing here derives a status from the evidence cited, from
    the target row, or from the absence of either."""
    recorded = service.record_name(
        repository,
        _name_command(
            assertion=StatedAssertion(
                assertion_status=AssertionStatus.BEST_SUPPORTED,
                predicate_code="display_value",
                rationale="two synthetic sources agree",
                observed_at=WHEN,
            )
        ),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_assertions
    assert written.assertion_id == recorded.assertion_id
    assert written.target_entity_name_id == recorded.record_id
    assert written.assertion_status is AssertionStatus.BEST_SUPPORTED
    assert written.predicate_code == "display_value"
    assert written.principal_id == PRINCIPAL
    assert written.created_at == WHEN
    assert [
        getattr(written, declared.name)
        for declared in fields(written)
        if declared.name.startswith("target_") and getattr(written, declared.name) is not None
    ] == [recorded.record_id]


def test_a_command_carrying_no_assertion_writes_no_assertion_row(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """Counted rather than merely unraised: "no error" and "nothing written" are
    different facts, and only the second is the claim."""
    recorded = service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    assert recorded.assertion_id is None
    assert recorded.evidence_ids == ()
    assert len(world.entity_assertions) == 0
    assert len(world.entity_assertion_evidence) == 0


def test_a_correction_carrying_an_assertion_targets_the_successor(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The subject of the claim is the row that now says the thing, not the one
    it replaced."""
    recorded = service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    corrected = service.correct_name(
        repository,
        CorrectEntityName(
            entity_name_id=recorded.record_id,
            expected_version=1,
            entity_id=ORGANIZATION,
            display_value="Synthetic Org Holdings LLC",
            name_type_code=NameTypeCode.LEGAL,
            assertion=StatedAssertion(assertion_status=AssertionStatus.VERIFIED),
        ),
        principal_id=PRINCIPAL,
        at=LATER,
    )
    (written,) = world.entity_assertions
    assert written.target_entity_name_id == corrected.record_id
    assert written.target_entity_name_id != recorded.record_id


def test_counterevidence_is_recorded_and_changes_no_assertion_status(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """A status is a claim its own writer makes. Nothing recomputes one from the
    evidence that accumulates against it, so an assertion cited against stays
    exactly the status the caller stated."""
    recorded = service.record_name(
        repository,
        _name_command(
            assertion=StatedAssertion(
                assertion_status=AssertionStatus.BEST_SUPPORTED,
                evidence=(
                    StatedEvidence(
                        role=EvidenceRole.COUNTEREVIDENCE, entity_observation_id=OBSERVATION
                    ),
                    StatedEvidence(role=EvidenceRole.DIRECT, entity_observation_id=OBSERVATION),
                ),
            )
        ),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_assertions
    assert written.assertion_status is AssertionStatus.BEST_SUPPORTED

    assert len(recorded.evidence_ids) == 2
    cited = sorted(world.entity_assertion_evidence, key=lambda row: row.evidence_id)
    assert {row.role for row in cited} == {EvidenceRole.COUNTEREVIDENCE, EvidenceRole.DIRECT}
    assert {row.assertion_id for row in cited} == {recorded.assertion_id}
    assert {row.evidence_id for row in cited} == set(recorded.evidence_ids)
    assert {row.created_at for row in cited} == {WHEN}


def test_a_profile_assertion_names_the_profile_by_its_entity(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The singleton family's target is its `entity_id`, because that is both its
    primary key and its foreign key."""
    recorded = service.record_organization_profile(
        repository,
        _profile_command(
            assertion=StatedAssertion(assertion_status=AssertionStatus.AWAITING_CONFIRMATION)
        ),
        principal_id=PRINCIPAL,
        at=WHEN,
    )
    (written,) = world.entity_assertions
    assert written.target_organization_profile_entity_id == ORGANIZATION
    assert recorded.record_id == ORGANIZATION


# --- A8. Authority is the method's, and no command can reach it --------------


AUTHORITY_BEARING: Final = (
    "record_name",
    "correct_name",
    "record_organization_profile",
    "record_address",
    "correct_address",
    "record_communication_method",
    "correct_communication_method",
    "record_project_participation",
    "correct_project_participation",
    "record_affiliation",
    "correct_affiliation",
)


@pytest.mark.parametrize("method_name", AUTHORITY_BEARING)
def test_authority_is_keyword_only_and_defaulted(method_name: str) -> None:
    """A payload able to name its own authority could name any of them, including
    the one that would claim a person confirmed what a rule produced. So it is
    an argument on the method, keyword-only, with the default the rest of this
    plane uses."""
    parameter = inspect.signature(getattr(EntityRecordFamilyService, method_name)).parameters[
        "authority"
    ]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is DEFAULT_MUTATION_AUTHORITY


@pytest.mark.parametrize("command", COMMANDS, ids=lambda command: command.__name__)
def test_no_command_can_name_an_authority(command: type) -> None:
    named = {declared.name: str(declared.type) for declared in fields(command)}
    assert "authority" not in named
    assert "asserted_by" not in named
    assert [name for name, kind in named.items() if "MutationAuthority" in kind] == []


def test_the_stated_authority_is_what_lands_on_the_assertion(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """A caller that has one passes it as the method's own argument, and it is
    written unchanged."""
    service.record_name(
        repository,
        _name_command(assertion=StatedAssertion(assertion_status=AssertionStatus.INFERRED)),
        principal_id=PRINCIPAL,
        at=WHEN,
        authority=MutationAuthority.SYSTEM_DETERMINISTIC,
    )
    (written,) = world.entity_assertions
    assert written.asserted_by is MutationAuthority.SYSTEM_DETERMINISTIC


@pytest.mark.parametrize(
    "method_name",
    (
        *AUTHORITY_BEARING,
        "retire_name",
        "revise_organization_profile",
        "retire_address",
        "retire_communication_method",
        "retire_project_participation",
        "retire_affiliation",
    ),
)
def test_the_principal_and_the_moment_are_keyword_only_on_every_method(
    method_name: str,
) -> None:
    """Both come from the composition root rather than from a payload, and both
    are keyword-only so neither can be supplied positionally by accident."""
    parameters = inspect.signature(getattr(EntityRecordFamilyService, method_name)).parameters
    assert parameters["principal_id"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["at"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["principal_id"].default is inspect.Parameter.empty
    assert parameters["at"].default is inspect.Parameter.empty


# --- B. The in-memory double's own write-path refusals -----------------------
#
# The subject here is `_Entities`, not the service. A double that cannot refuse
# teaches a caller that refusals do not exist, so each refusal the double claims
# to reproduce is exercised -- and the one place it deliberately reproduces a
# *coarser* answer than it could is locked against being quietly improved.


def test_the_double_refuses_a_record_stamped_with_another_principal(
    repository: EntitiesRepository,
) -> None:
    """The record carries its own `principal_id` and the caller states one. They
    have to agree; an overwrite would file another Principal's record under this
    one and report success."""
    with pytest.raises(ValueError, match="acting Principal"):
        repository.record_entity_name(
            PRINCIPAL,
            EntityName(
                entity_name_id="enam_aaaa0001aaaa0001",
                entity_id=ORGANIZATION,
                principal_id=OTHER,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Synthetic Org LLC",
                normalized_value=normalize_name("Synthetic Org LLC"),
                updated_at=WHEN,
            ),
        )


def test_the_double_refuses_a_write_against_a_merged_away_entity(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """ "The row exists" and "the row is writable" are different questions, and a
    merged-away endpoint answers the first and not the second."""
    with pytest.raises(MergedEndpointError):
        service.record_name(
            repository, _name_command(entity_id=MERGED), principal_id=PRINCIPAL, at=WHEN
        )
    assert world.entity_names == []


def test_the_double_refuses_an_organization_profile_on_a_non_organization(
    world: World, repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """The writer's own invariant, reproduced rather than left to a trigger the
    schema deliberately does not carry."""
    with pytest.raises(ValueError, match="organization entity"):
        service.record_organization_profile(
            repository, _profile_command(entity_id=PERSON), principal_id=PRINCIPAL, at=WHEN
        )
    assert world.entity_organization_profiles == []


@pytest.mark.parametrize("family", _FAMILY_CASES)
def test_the_double_refuses_a_self_supersession(
    repository: EntitiesRepository, service: EntityRecordFamilyService, family: _Family
) -> None:
    """A row that names itself as its own successor is a cycle of one, and it is
    refused before the version guard rather than written and then reasoned
    about."""
    recorded = family.record(service, repository)
    supersede = getattr(
        repository,
        {
            "name": "supersede_entity_name",
            "address": "supersede_entity_address",
            "communication method": "supersede_communication_method",
            "project participation": "supersede_project_participation",
            "affiliation": "supersede_person_organization_affiliation",
        }[family.label],
    )
    with pytest.raises(ValueError, match="superseded by itself"):
        supersede(
            PRINCIPAL,
            **{family.key: recorded.record_id, family.successor_key: recorded.record_id},
            expected_version=1,
            at=LATER,
        )


def test_the_double_refuses_a_stale_version_and_an_unreachable_row_differently(
    repository: EntitiesRepository, service: EntityRecordFamilyService
) -> None:
    """For the six record families the split is the server's own: an
    optimistic-version conflict and a mistyped identifier are different facts
    about the world."""
    recorded = service.record_name(repository, _name_command(), principal_id=PRINCIPAL, at=WHEN)
    with pytest.raises(StaleDirectedVersionError):
        repository.retire_entity_name(
            PRINCIPAL, entity_name_id=recorded.record_id, expected_version=99, at=LATER
        )
    with pytest.raises(UnknownScopeError):
        repository.retire_entity_name(
            PRINCIPAL, entity_name_id=ABSENT_NAME, expected_version=1, at=LATER
        )


#: The one refusal `supersede_assertion` gives, on the server and therefore in
#: the double. Spelled here so both halves of the parity claim below compare
#: against the same string rather than against each other.
ASSERTION_SUPERSESSION_REFUSAL: Final = (
    "a supersession names an assertion this write read unchanged"
)


def _record_assertion(repository: EntitiesRepository, assertion_id: str) -> None:
    repository.record_assertion(
        PRINCIPAL,
        EntityAssertion(
            assertion_id=assertion_id,
            principal_id=PRINCIPAL,
            assertion_status=AssertionStatus.BEST_SUPPORTED,
            asserted_by=DEFAULT_MUTATION_AUTHORITY,
            created_at=WHEN,
            target_organization_profile_entity_id=ORGANIZATION,
        ),
    )


def test_the_double_collapses_both_assertion_supersession_failures_into_one_answer(
    repository: EntitiesRepository,
) -> None:
    """Deliberate, and locked so it cannot be quietly improved on. A double that
    refused more precisely than production would teach a caller a distinction
    production never makes: code written against a stale-version branch here
    would pass every test and then never take that branch against the server,
    whose only failure branch is `rowcount == 0`.

    Both the stale case and the unreachable case are asserted to give the same
    exception type *and* the same words, and the words are asserted to be the
    server's own."""
    _record_assertion(repository, SECOND_ASSERTION)

    with pytest.raises(UnknownScopeError) as stale:
        repository.supersede_assertion(
            PRINCIPAL,
            assertion_id=SECOND_ASSERTION,
            superseded_by_assertion_id=ABSENT_ASSERTION,
            expected_version=99,
            at=LATER,
        )
    with pytest.raises(UnknownScopeError) as unreachable:
        repository.supersede_assertion(
            PRINCIPAL,
            assertion_id=ABSENT_ASSERTION,
            superseded_by_assertion_id=SECOND_ASSERTION,
            expected_version=1,
            at=LATER,
        )
    assert type(stale.value) is type(unreachable.value)
    assert str(stale.value) == str(unreachable.value) == ASSERTION_SUPERSESSION_REFUSAL


def test_the_servers_assertion_supersession_gives_those_exact_words() -> None:
    """The other half of the parity claim. The double's message is only "the
    server's own, verbatim" for as long as the server says it, so this reads the
    server's source and reddens if either side moves."""
    source = inspect.getsource(SqlEntityRepository.supersede_assertion)
    assert ASSERTION_SUPERSESSION_REFUSAL in source
    assert "StaleDirectedVersionError" not in source


def test_the_double_refuses_an_assertion_stamped_with_another_principal(
    repository: EntitiesRepository,
) -> None:
    with pytest.raises(ValueError, match="acting Principal"):
        repository.record_assertion(
            PRINCIPAL,
            EntityAssertion(
                assertion_id=SECOND_ASSERTION,
                principal_id=OTHER,
                assertion_status=AssertionStatus.UNRESOLVED,
                asserted_by=DEFAULT_MUTATION_AUTHORITY,
                created_at=WHEN,
                target_organization_profile_entity_id=ORGANIZATION,
            ),
        )


def test_the_double_refuses_a_profile_assertion_against_another_principals_entity(
    repository: EntitiesRepository,
) -> None:
    """Only the sixth target is checked, for the reason the server gives: the
    other five carry a composite `(id, principal_id)` foreign key and are
    same-Principal by construction, while this one is a plain single-column
    reference the writer has to check itself."""
    with pytest.raises(UnknownScopeError):
        repository.record_assertion(
            PRINCIPAL,
            EntityAssertion(
                assertion_id=SECOND_ASSERTION,
                principal_id=PRINCIPAL,
                assertion_status=AssertionStatus.UNRESOLVED,
                asserted_by=DEFAULT_MUTATION_AUTHORITY,
                created_at=WHEN,
                target_organization_profile_entity_id=THEIRS,
            ),
        )
