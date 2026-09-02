"""`RI-ENT-WP-10`'s five record-family reads, through the application service.

The six Entity-bound record families -- typed names, the organization profile,
addresses, communication methods, project participations and person/organization
affiliations -- have been stored since `RI-ENT-WP-02`..`WP-06b` and were reachable
through no capability at all. This file proves the names that reach them: that
each answers with the rows that are there, that each bounds what it answers
and says so, that a page continues where the last one stopped, and that the
refusals survive the trip out to a payload.

**The evidence for the paged reads comes from the in-memory double.** Each
`*_page` method has a SQL implementation in `infrastructure.persistence.entity`
and an in-memory one in `tests/conftest`, and only the second is exercised here:
the first is database-gated. What this file therefore proves is the contract --
the keyset, the disclosure, the refusal of a foreign cursor -- against the double
that is written to the same contract, and `tests/database` is where the SQL half
is measured against a real table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.application.commands import (
    GetEntityProfile,
    ListEntityAddresses,
    ListEntityCommunicationMethods,
    ListEntityNames,
    ListEntityParticipations,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import (
    ENTITY_PROFILE_COLLECTION_LIMIT,
    AddressTypeCode,
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityAddress,
    EntityCommunicationMethod,
    EntityName,
    EntityOrganizationProfile,
    EntityProjectParticipation,
    EntityStatus,
    EntityType,
    LegalIdentityStatusCode,
    NameTypeCode,
    OrganizationKindCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    normalize_address,
    normalize_communication_value,
)
from my_pa.domain.relationship.normalization import normalize_name

WHEN: Final = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)

PERSON: Final = "ent_recfam0001person01"
ORGANIZATION: Final = "ent_recfam0002orgn001"
PROJECT: Final = "ent_recfam0003proj001"
STRANGER: Final = "ent_recfam0009absent01"


def _entity(entity_id: str, display_name: str, principal_id: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type=kind,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        principal_id=principal_id,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _name(index: int, principal_id: str) -> EntityName:
    """One typed name form, numbered so the keyset order is the written order."""
    value = f"Recorded Name {index:02d}"
    return EntityName(
        entity_name_id=f"enam_recfam{index:04d}name01",
        entity_id=PERSON,
        principal_id=principal_id,
        name_type_code=NameTypeCode.DISPLAY,
        display_value=value,
        normalized_value=normalize_name(value),
        is_preferred=index == 0,
        version=1,
        updated_at=WHEN,
    )


def _address(index: int, principal_id: str) -> EntityAddress:
    raw = f"{index} Harbour Row, Bristol"
    return EntityAddress(
        entity_address_id=f"eadr_recfam{index:04d}addr01",
        entity_id=PERSON,
        principal_id=principal_id,
        address_type_code=AddressTypeCode.PROJECT,
        raw_value=raw,
        normalized_address_value=normalize_address(
            line1=f"{index} Harbour Row",
            line2=None,
            city="Bristol",
            region=None,
            postal_code=None,
            country=None,
            raw_value=raw,
        ),
        line1=f"{index} Harbour Row",
        city="Bristol",
        version=1,
        updated_at=WHEN,
    )


def _method(index: int, principal_id: str) -> EntityCommunicationMethod:
    value = f"recorded.{index:02d}@example.invalid"
    return EntityCommunicationMethod(
        communication_method_id=f"ecmm_recfam{index:04d}comm01",
        entity_id=PERSON,
        principal_id=principal_id,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.CORPORATE,
        normalized_value=normalize_communication_value(CommunicationMethodTypeCode.EMAIL, value),
        display_value=value,
        verification_status_code=CommunicationVerificationStatusCode.UNRESOLVED,
        version=1,
        updated_at=WHEN,
    )


def _participation(
    index: int, principal_id: str, *, participant: str, project: str
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=f"eppt_recfam{index:04d}part01",
        principal_id=principal_id,
        project_entity_id=project,
        participant_entity_id=participant,
        project_display_name="Harbour Tower",
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        role_text="structural engineer",
        version=1,
        updated_at=WHEN,
    )


def _affiliation(index: int, principal_id: str) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=f"poaf_recfam{index:04d}affl01",
        principal_id=principal_id,
        person_entity_id=PERSON,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        organization_entity_id=ORGANIZATION,
        job_title="Associate",
        version=1,
        updated_at=WHEN,
    )


@pytest.fixture
def staged(scene: Scene) -> Scene:
    """A person, an organization, a project, and one row of each family.

    One row per family rather than none, because an empty collection is the
    answer a handler that never read anything would also give.
    """
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(
            principal_id, _entity(PERSON, "Rowan Vale", principal_id, EntityType.PERSON)
        )
        entities.create(
            principal_id,
            _entity(ORGANIZATION, "Meridian Works", principal_id, EntityType.ORGANIZATION),
        )
        entities.create(
            principal_id, _entity(PROJECT, "Harbour Tower", principal_id, EntityType.PROJECT)
        )
        entities.record_entity_name(principal_id, _name(0, principal_id))
        entities.record_entity_address(principal_id, _address(0, principal_id))
        entities.record_communication_method(principal_id, _method(0, principal_id))
        entities.record_project_participation(
            principal_id,
            _participation(0, principal_id, participant=PERSON, project=PROJECT),
        )
        entities.record_person_organization_affiliation(principal_id, _affiliation(0, principal_id))
        entities.record_organization_profile(
            principal_id,
            EntityOrganizationProfile(
                entity_id=ORGANIZATION,
                principal_id=principal_id,
                organization_kind_code=OrganizationKindCode.COMPANY,
                legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            ),
        )
    return scene


def _fill(scene: Scene, count: int) -> None:
    """`count` further name rows on `PERSON`, so a bound has something to bite."""
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        for index in range(1, count + 1):
            unit_of_work.entities.record_entity_name(principal_id, _name(index, principal_id))


def _invoke(scene: Scene, capability: Capability, command: object) -> dict[str, object]:
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(capability, Purpose.ENTITY_READ, scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    return envelope.to_canonical_dict()


def _payload(scene: Scene, capability: Capability, command: object) -> dict[str, Any]:
    body = _invoke(scene, capability, command)
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    return result


def _disclosure(scene: Scene, capability: Capability, command: object) -> dict[str, Any]:
    body = _invoke(scene, capability, command)
    assert body.get("error") is None, body.get("error")
    disclosure = body["disclosure"]
    assert isinstance(disclosure, dict)
    return disclosure


# --- entities.profile -------------------------------------------------------


def test_the_profile_carries_every_record_family_around_the_entity(staged: Scene) -> None:
    """One row of each family, reached through one capability."""
    result = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))
    profile = result["profile"]
    assert profile["entity"]["entity_id"] == PERSON
    assert [row["display_value"] for row in profile["names"]] == ["Recorded Name 00"]
    assert [row["city"] for row in profile["addresses"]] == ["Bristol"]
    assert [row["display_value"] for row in profile["communication_methods"]] == [
        "recorded.00@example.invalid"
    ]
    assert [row["participation_id"] for row in profile["participations_as_participant"]] == [
        "eppt_recfam0000part01"
    ]
    assert profile["participations_as_project"] == []
    assert [row["organization_entity_id"] for row in profile["affiliations_as_person"]] == [
        ORGANIZATION
    ]
    assert profile["affiliations_as_organization"] == []
    assert profile["organization_profile"] is None
    assert profile["is_complete"] is True
    assert profile["limitations"] == []


def test_the_profile_reads_both_ends_of_the_two_double_ended_families(staged: Scene) -> None:
    """The project sees its participant; the organization sees its affiliate.

    The pairing is the point: a handler that read one end and reported it under
    both names would pass a test that only ever asked one entity.
    """
    project = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PROJECT))[
        "profile"
    ]
    assert [row["participant_entity_id"] for row in project["participations_as_project"]] == [
        PERSON
    ]
    assert project["participations_as_participant"] == []

    organization = _payload(
        staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=ORGANIZATION)
    )["profile"]
    assert [row["person_entity_id"] for row in organization["affiliations_as_organization"]] == [
        PERSON
    ]
    assert organization["affiliations_as_person"] == []


def test_the_organization_profile_is_a_row_or_a_null_and_never_a_list(staged: Scene) -> None:
    """Singular because `entity_id` is that table's primary key."""
    organization = _payload(
        staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=ORGANIZATION)
    )["profile"]
    assert organization["organization_profile"]["entity_id"] == ORGANIZATION
    assert organization["organization_profile"]["organization_kind_code"] == "company"


def test_the_profile_discloses_the_collection_it_could_not_carry_whole(staged: Scene) -> None:
    """The bound is observed one row past the ceiling, not inferred from a full page."""
    _fill(staged, ENTITY_PROFILE_COLLECTION_LIMIT)
    body = _invoke(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))
    profile = body["result"]["profile"]  # type: ignore[index]
    assert len(profile["names"]) == ENTITY_PROFILE_COLLECTION_LIMIT
    assert profile["is_complete"] is False
    assert profile["limitations"] == ["more_names_than_this_profile_carries"]
    # Only the collection that overflowed is named: a caller told "something was
    # truncated" would have to page all four families to find out which.
    truncation = body["disclosure"]["truncation"]  # type: ignore[index]
    assert truncation["is_truncated"] is True
    assert truncation["reason"] == "profile_collection_limit_reached"
    # No cursor, deliberately: a position into an assembly of seven collections
    # would have to mean seven positions at once. The paged reads are the
    # continuation.
    assert truncation["next_cursor"] is None


def test_a_profile_exactly_at_the_ceiling_reports_no_limitation(staged: Scene) -> None:
    """The control for the bound: `is_complete` is an observation, not a guess."""
    _fill(staged, ENTITY_PROFILE_COLLECTION_LIMIT - 1)
    profile = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))[
        "profile"
    ]
    assert len(profile["names"]) == ENTITY_PROFILE_COLLECTION_LIMIT
    assert profile["is_complete"] is True
    assert profile["limitations"] == []


def test_the_profile_never_publishes_the_partition_column(staged: Scene) -> None:
    """`principal_id` is about the caller, not about the entity."""
    profile = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))[
        "profile"
    ]
    collections = (
        "names",
        "addresses",
        "communication_methods",
        "participations_as_project",
        "participations_as_participant",
        "affiliations_as_person",
        "affiliations_as_organization",
    )
    for collection in collections:
        for row in profile[collection]:
            assert "principal_id" not in row


def test_an_unknown_entity_is_not_found_rather_than_an_empty_profile(staged: Scene) -> None:
    """ "Nothing is recorded" and "there is no such person" are different answers."""
    body = _invoke(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=STRANGER))
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value  # type: ignore[index]


# --- the four paged reads ---------------------------------------------------


def test_each_paged_read_answers_the_family_it_names(staged: Scene) -> None:
    names = _payload(staged, Capability.ENTITIES_NAMES_LIST, ListEntityNames(entity_id=PERSON))
    assert names["entity_id"] == PERSON
    assert [row["display_value"] for row in names["names"]] == ["Recorded Name 00"]

    addresses = _payload(
        staged, Capability.ENTITIES_ADDRESSES_LIST, ListEntityAddresses(entity_id=PERSON)
    )
    assert [row["entity_address_id"] for row in addresses["addresses"]] == ["eadr_recfam0000addr01"]

    methods = _payload(
        staged,
        Capability.ENTITIES_COMMUNICATION_LIST,
        ListEntityCommunicationMethods(entity_id=PERSON),
    )
    assert [row["communication_method_id"] for row in methods["communication_methods"]] == [
        "ecmm_recfam0000comm01"
    ]

    participations = _payload(
        staged,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        ListEntityParticipations(entity_id=PERSON, perspective="participant"),
    )
    assert participations["perspective"] == "participant"
    assert [row["participation_id"] for row in participations["participations"]] == [
        "eppt_recfam0000part01"
    ]


def test_the_perspective_selects_the_end_and_is_echoed_back(staged: Scene) -> None:
    """A caller holding two pages needs each one to say which end it is."""
    as_project = _payload(
        staged,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        ListEntityParticipations(entity_id=PROJECT, perspective="project"),
    )
    assert as_project["perspective"] == "project"
    assert [row["participant_entity_id"] for row in as_project["participations"]] == [PERSON]

    empty = _payload(
        staged,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        ListEntityParticipations(entity_id=PROJECT, perspective="participant"),
    )
    assert empty["participations"] == []


def test_a_perspective_the_family_has_no_end_for_is_refused(staged: Scene) -> None:
    """Refused rather than defaulted: the other end is a different question."""
    with pytest.raises(InvalidRequestError):
        ListEntityParticipations(entity_id=PROJECT, perspective="either")


def test_a_page_discloses_its_bound_and_continues_from_its_own_cursor(staged: Scene) -> None:
    """The keyset walk: the cursor is a position, and it is issued only when real."""
    _fill(staged, 3)
    first = _invoke(
        staged, Capability.ENTITIES_NAMES_LIST, ListEntityNames(entity_id=PERSON, page_size=2)
    )
    page = first["result"]["names"]  # type: ignore[index]
    truncation = first["disclosure"]["truncation"]  # type: ignore[index]
    assert [row["entity_name_id"] for row in page] == [
        "enam_recfam0000name01",
        "enam_recfam0001name01",
    ]
    assert truncation["is_truncated"] is True
    assert truncation["reason"] == "page_size_reached"
    assert truncation["next_cursor"] == "enam_recfam0001name01"

    second = _invoke(
        staged,
        Capability.ENTITIES_NAMES_LIST,
        ListEntityNames(entity_id=PERSON, page_size=2, after=truncation["next_cursor"]),
    )
    assert [row["entity_name_id"] for row in second["result"]["names"]] == [  # type: ignore[index]
        "enam_recfam0002name01",
        "enam_recfam0003name01",
    ]
    # The walk ends without a continuation, and `Truncation` refuses one anyway.
    assert second["disclosure"]["truncation"]["is_truncated"] is False  # type: ignore[index]
    assert second["disclosure"]["truncation"]["next_cursor"] is None  # type: ignore[index]


def test_a_last_page_that_exactly_fills_issues_no_cursor(staged: Scene) -> None:
    """A full page and a cut page are different facts; only one has a successor."""
    _fill(staged, 1)
    disclosure = _disclosure(
        staged, Capability.ENTITIES_NAMES_LIST, ListEntityNames(entity_id=PERSON, page_size=2)
    )
    assert disclosure["truncation"]["is_truncated"] is False
    assert disclosure["truncation"]["next_cursor"] is None


def test_a_cursor_naming_no_record_of_this_entity_is_refused(staged: Scene) -> None:
    """Refused rather than silently restarted: an empty page reads as the end."""
    body = _invoke(
        staged,
        Capability.ENTITIES_NAMES_LIST,
        ListEntityNames(entity_id=PERSON, after="enam_recfam9999name99"),
    )
    assert body["error"] is not None


@pytest.mark.parametrize(
    ("capability", "command"),
    [
        (Capability.ENTITIES_NAMES_LIST, ListEntityNames(entity_id=STRANGER)),
        (Capability.ENTITIES_ADDRESSES_LIST, ListEntityAddresses(entity_id=STRANGER)),
        (
            Capability.ENTITIES_COMMUNICATION_LIST,
            ListEntityCommunicationMethods(entity_id=STRANGER),
        ),
        (
            Capability.ENTITIES_PARTICIPATIONS_LIST,
            ListEntityParticipations(entity_id=STRANGER, perspective="participant"),
        ),
    ],
    ids=lambda value: value.value if isinstance(value, Capability) else "",
)
def test_every_paged_read_reads_the_entity_first(
    staged: Scene, capability: Capability, command: object
) -> None:
    """An unknown entity is `not_found`, not an empty collection."""
    body = _invoke(staged, capability, command)
    assert body["error"]["code"] == ErrorCode.NOT_FOUND.value  # type: ignore[index]


# --- the shapes these five publish ------------------------------------------
#
# Exhaustive key-set equality, not named-key membership. A response that grew a
# field would satisfy `"x" in row` and is exactly the change a consumer has to
# be told about, so these compare the whole set.


def test_the_profile_publishes_exactly_the_keys_it_publishes(staged: Scene) -> None:
    profile = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))[
        "profile"
    ]
    assert list(profile) == [
        "entity",
        "assembled_at",
        "limitations",
        "is_complete",
        "organization_profile",
        "names",
        "addresses",
        "communication_methods",
        "participations_as_project",
        "participations_as_participant",
        "affiliations_as_person",
        "affiliations_as_organization",
    ]


def test_every_record_view_publishes_exactly_its_own_columns(staged: Scene) -> None:
    """One assertion per family, so a field added to any of them reddens by name."""
    person = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))[
        "profile"
    ]
    organization = _payload(
        staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=ORGANIZATION)
    )["profile"]

    assert set(person["names"][0]) == {
        "entity_name_id",
        "entity_id",
        "name_type_code",
        "display_value",
        "normalized_value",
        "is_preferred",
        "effective_from",
        "effective_to",
        "state",
        "version",
        "updated_at",
        "retired_at",
        "superseded_by_entity_name_id",
    }
    assert set(person["addresses"][0]) == {
        "entity_address_id",
        "entity_id",
        "address_type_code",
        "raw_value",
        "normalized_address_value",
        "line1",
        "line2",
        "city",
        "region",
        "postal_code",
        "country",
        "label",
        "is_preferred",
        "effective_from",
        "effective_to",
        "state",
        "version",
        "updated_at",
        "retired_at",
        "superseded_by_entity_address_id",
    }
    assert set(person["communication_methods"][0]) == {
        "communication_method_id",
        "entity_id",
        "method_type_code",
        "usage_context_code",
        "display_value",
        "normalized_value",
        "verification_status_code",
        "is_preferred",
        "effective_from",
        "effective_to",
        "state",
        "version",
        "updated_at",
        "retired_at",
        "superseded_by_communication_method_id",
        "linked_external_identifier_id",
    }
    assert set(person["participations_as_participant"][0]) == {
        "participation_id",
        "project_entity_id",
        "participant_entity_id",
        "project_display_name",
        "role_basis_code",
        "stakeholder_side_code",
        "stakeholder_class_code",
        "relationship_status_code",
        "role_code",
        "role_text",
        "discipline_code",
        "discipline_text",
        "scope_text",
        "effective_from",
        "effective_to",
        "state",
        "version",
        "updated_at",
        "retired_at",
        "superseded_by_participation_id",
    }
    assert set(person["affiliations_as_person"][0]) == {
        "affiliation_id",
        "person_entity_id",
        "affiliation_type_code",
        "organization_entity_id",
        "job_title",
        "effective_from",
        "effective_to",
        "state",
        "version",
        "updated_at",
        "retired_at",
        "superseded_by_affiliation_id",
    }
    assert set(organization["organization_profile"]) == {
        "entity_id",
        "organization_kind_code",
        "legal_identity_status_code",
        "jurisdiction_code",
        "registration_identifier",
        "version",
        "created_at",
        "updated_at",
    }


def test_each_paged_read_publishes_exactly_its_own_envelope(staged: Scene) -> None:
    """The page's own keys, which are not the record's."""
    assert set(
        _payload(staged, Capability.ENTITIES_NAMES_LIST, ListEntityNames(entity_id=PERSON))
    ) == {"entity_id", "names"}
    assert set(
        _payload(staged, Capability.ENTITIES_ADDRESSES_LIST, ListEntityAddresses(entity_id=PERSON))
    ) == {"entity_id", "addresses"}
    assert set(
        _payload(
            staged,
            Capability.ENTITIES_COMMUNICATION_LIST,
            ListEntityCommunicationMethods(entity_id=PERSON),
        )
    ) == {"entity_id", "communication_methods"}
    assert set(
        _payload(
            staged,
            Capability.ENTITIES_PARTICIPATIONS_LIST,
            ListEntityParticipations(entity_id=PERSON, perspective="participant"),
        )
    ) == {"entity_id", "perspective", "participations"}


def test_a_paged_record_is_the_same_shape_the_profile_publishes(staged: Scene) -> None:
    """One view function per family, proved rather than stated.

    Two rendering paths for one record family is how a page and a composite come
    to disagree about a field name, so this compares the two answers directly.
    """
    profile = _payload(staged, Capability.ENTITIES_PROFILE, GetEntityProfile(entity_id=PERSON))[
        "profile"
    ]
    paged = _payload(staged, Capability.ENTITIES_NAMES_LIST, ListEntityNames(entity_id=PERSON))[
        "names"
    ]
    assert profile["names"] == paged
