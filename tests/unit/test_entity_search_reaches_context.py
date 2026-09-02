"""`entities.search` matches an entity by its context, not only by its two names.

`RI-ENT-WP-09`, acceptance ledger `RI-AC-038`. Before this, `entities.search`
was a substring match over `entities.canonical_name` and `entities.display_name`
and nothing else, so the organization whose canonical name is one thing and
whose trading name is another was unreachable by the name anybody actually uses
for it -- the GS4 problem audit section M raises.

Five match paths are added, and each one is exercised here **by a query that the
entity's own two name columns could not have answered**. A test that searched
for a word already present in `canonical_name` would pass against the old code
and prove nothing.

Three boundaries are pinned as hard as the paths themselves, because each is a
place where widening a browse query becomes a disclosure nobody asked for:

* **`WP09-DECISION-1`.** `NameTypeCode.ALIAS` and `NameTypeCode.HISTORICAL_NAME`
  stay unreachable. `contracts/ports.py::EntitiesRepository.search` records the
  reason -- a browse result must not hand back an identity somebody no longer
  uses -- and this file is what makes the record enforced rather than merely
  written down.
* **State.** Only `active` child rows match. A retired name, a superseded
  affiliation and an ended relationship all record what an entity *used to* be.
* **Partition.** Every added subquery is correlated on `entity_id` *and* scoped
  by `principal_id`. A subquery correlated on `entity_id` alone would let
  another Principal's child row decide that this Principal's entity matches.

**What this file cannot prove.** It drives the in-memory `_Entities` fake, which
mirrors `SqlEntityRepository.search`'s matching in Python. That the *server*
performs the same match is `tests/database`'s claim, made by
`tests/database/test_entity_search_reaches_context.py`; nothing here opens a
connection. The fake carries one deliberate divergence, documented at its own
site: the server matches a relationship type's seeded `label` and the fake
matches its `relationship_type_code`, because this `World` holds no taxonomy
rows at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.entity import (
    AffiliationTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    Entity,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    NameTypeCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
    RelationshipState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"

#: One entity per match path, each named something the query never spells.
NAMED = "ent_named0001named001"
ADDRESSED = "ent_addr0002addr0002"
EMPLOYED = "ent_empl0003empl0003"
STAFFED = "ent_staf0004staf0004"
CONNECTED = "ent_conn0005conn0005"
EMPLOYER = "ent_orga0006orga0006"
COUNTERPARTY = "ent_ctpy0007ctpy0007"
WITHHELD = "ent_hidn0008hidn0008"
LITERAL = "ent_ltrl0009ltrl0009"
DECOY = "ent_dcoy0010dcoy0010"
FOREIGN = "ent_frgn0011frgn0011"
FOREIGN_PEER = "ent_frgp0013frgp0013"
PROJECT = "ent_proj0012proj0012"

WHEN = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _entity(
    entity_id: str,
    name: str,
    *,
    principal_id: str = PRINCIPAL,
    entity_type: EntityType = EntityType.PERSON,
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


def _typed_name(
    entity_name_id: str,
    entity_id: str,
    value: str,
    name_type_code: NameTypeCode,
    *,
    principal_id: str = PRINCIPAL,
    state: EntityNameState = EntityNameState.ACTIVE,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=principal_id,
        name_type_code=name_type_code,
        display_value=value,
        normalized_value=normalize_name(value),
        state=state,
        retired_at=WHEN if state is not EntityNameState.ACTIVE else None,
    )


def _communication(
    communication_method_id: str,
    entity_id: str,
    value: str,
    *,
    principal_id: str = PRINCIPAL,
    state: EntityCommunicationMethodState = EntityCommunicationMethodState.ACTIVE,
) -> EntityCommunicationMethod:
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=principal_id,
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        usage_context_code=CommunicationUsageContextCode.OFFICE,
        normalized_value=value,
        display_value=value,
        verification_status_code=CommunicationVerificationStatusCode.UNRESOLVED,
        state=state,
        retired_at=WHEN if state is not EntityCommunicationMethodState.ACTIVE else None,
    )


def _affiliation(
    affiliation_id: str,
    person_entity_id: str,
    organization_entity_id: str | None,
    *,
    job_title: str | None = None,
    principal_id: str = PRINCIPAL,
    state: PersonOrganizationAffiliationState = PersonOrganizationAffiliationState.ACTIVE,
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=principal_id,
        person_entity_id=person_entity_id,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        organization_entity_id=organization_entity_id,
        job_title=job_title,
        state=state,
        retired_at=WHEN if state is PersonOrganizationAffiliationState.RETIRED else None,
        superseded_by_affiliation_id=(
            "poaf_succes0002succes"
            if state is PersonOrganizationAffiliationState.SUPERSEDED
            else None
        ),
    )


def _participation(
    participation_id: str,
    participant_entity_id: str,
    *,
    role_text: str | None = None,
    project_display_name: str = "Harbour Tower",
    principal_id: str = PRINCIPAL,
    state: EntityProjectParticipationState = EntityProjectParticipationState.ACTIVE,
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=participation_id,
        principal_id=principal_id,
        project_entity_id=PROJECT,
        participant_entity_id=participant_entity_id,
        project_display_name=project_display_name,
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        role_text=role_text,
        state=state,
        retired_at=WHEN if state is EntityProjectParticipationState.RETIRED else None,
        superseded_by_participation_id=(
            "eppt_succes0002succe" if state is EntityProjectParticipationState.SUPERSEDED else None
        ),
    )


def _relationship(
    relationship_id: str,
    from_entity_id: str,
    to_entity_id: str,
    relationship_type: EntityRelationshipType,
    *,
    principal_id: str = PRINCIPAL,
    state: RelationshipState = RelationshipState.ACTIVE,
) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=relationship_id,
        from_entity_id=from_entity_id,
        relationship_type=relationship_type,
        to_entity_id=to_entity_id,
        principal_id=principal_id,
        state=state,
        ended_at=WHEN if state is RelationshipState.ENDED else None,
    )


@pytest.fixture
def world() -> World:
    """A partition whose entities are all named for nothing anyone will search.

    Every canonical and display name here is a nonsense surname, so any hit in
    the tests below came through one of the five added paths and could not have
    come through the two original name columns. That is the whole design of this
    fixture and it is why the names look the way they do.
    """
    world = World()
    world.entities.extend(
        (
            _entity(NAMED, "Kalvedge"),
            _entity(ADDRESSED, "Morrowin"),
            _entity(EMPLOYED, "Threndal"),
            _entity(STAFFED, "Oskarven"),
            _entity(CONNECTED, "Piltravon"),
            _entity(EMPLOYER, "Vasqueline", entity_type=EntityType.ORGANIZATION),
            _entity(COUNTERPARTY, "Wendrilo", entity_type=EntityType.ORGANIZATION),
            _entity(WITHHELD, "Zorrandel"),
            _entity(LITERAL, "Quillmara"),
            _entity(DECOY, "Bexforden"),
            _entity(PROJECT, "Undercroft", entity_type=EntityType.PROJECT),
            _entity(FOREIGN, "Yalvenmar", principal_id=OTHER),
            _entity(FOREIGN_PEER, "Xantheria", principal_id=OTHER),
        )
    )
    world.entity_names.extend(
        (
            # The trading name that reaches an entity its canonical name cannot.
            _typed_name("enam_trade0001trade01", NAMED, "Harbour Ironworks", NameTypeCode.DBA),
            # The two `WP09-DECISION-1` withholds, on an entity nothing else reaches.
            _typed_name("enam_alias0002alias0", WITHHELD, "Sunset Consulting", NameTypeCode.ALIAS),
            _typed_name(
                "enam_hist0003histori",
                WITHHELD,
                "Sunrise Partners",
                NameTypeCode.HISTORICAL_NAME,
            ),
            # Retired, so the state filter is measurable rather than assumed.
            _typed_name(
                "enam_retir0004retire",
                WITHHELD,
                "Meadowlark Group",
                NameTypeCode.LEGAL,
                state=EntityNameState.RETIRED,
            ),
            # The other Principal's typed name, colliding on purpose.
            _typed_name(
                "enam_forei0005foreig",
                FOREIGN,
                "Harbour Ironworks",
                NameTypeCode.DBA,
                principal_id=OTHER,
            ),
            # A literal `%` and `_`, so the escaping claim has something to bite.
            _typed_name("enam_liter0006litera", LITERAL, "50%_off", NameTypeCode.BRAND),
            # The near miss the wildcard would have swept in.
            _typed_name("enam_decoy0007decoy0", DECOY, "50XYoff", NameTypeCode.BRAND),
        )
    )
    world.entity_communication_methods.extend(
        (
            _communication("ecmm_mail0001mail001", ADDRESSED, "rowan@ferrybridge.test"),
            _communication(
                "ecmm_gone0002gone0002",
                WITHHELD,
                "old@driftwood.test",
                state=EntityCommunicationMethodState.SUPERSEDED,
            ),
            _communication(
                "ecmm_forei0003foreig",
                FOREIGN,
                "rowan@ferrybridge.test",
                principal_id=OTHER,
            ),
        )
    )
    world.entity_person_organization_affiliations.extend(
        (
            _affiliation(
                "poaf_empl0001empl001",
                EMPLOYED,
                EMPLOYER,
                job_title="Chief Millwright",
            ),
            _affiliation(
                "poaf_gone0002gone0002",
                WITHHELD,
                COUNTERPARTY,
                job_title="Former Sailmaker",
                state=PersonOrganizationAffiliationState.SUPERSEDED,
            ),
            _affiliation(
                "poaf_forei0003foreig",
                FOREIGN,
                None,
                job_title="Chief Millwright",
                principal_id=OTHER,
            ),
        )
    )
    world.entity_project_participations.extend(
        (
            _participation(
                "eppt_staf0001staf001",
                STAFFED,
                role_text="Commissioning Lead",
                project_display_name="Saltmarsh Depot",
            ),
            _participation(
                "eppt_gone0002gone0002",
                WITHHELD,
                role_text="Commissioning Lead",
                project_display_name="Saltmarsh Depot",
                state=EntityProjectParticipationState.SUPERSEDED,
            ),
            _participation(
                "eppt_forei0003foreig",
                FOREIGN,
                role_text="Commissioning Lead",
                principal_id=OTHER,
            ),
        )
    )
    world.entity_relationships.extend(
        (
            _relationship(
                "erel_conn0001conn001",
                CONNECTED,
                COUNTERPARTY,
                EntityRelationshipType.SUBCONTRACTOR_TO,
            ),
            _relationship(
                "erel_gone0002gone0002",
                WITHHELD,
                COUNTERPARTY,
                EntityRelationshipType.PERMITTING_AUTHORITY_FOR,
                state=RelationshipState.ENDED,
            ),
            _relationship(
                "erel_forei0003foreig",
                FOREIGN,
                FOREIGN_PEER,
                EntityRelationshipType.SUBCONTRACTOR_TO,
                principal_id=OTHER,
            ),
        )
    )
    return world


def _found(world: World, query: str, **kwargs: object) -> set[str]:
    unit_of_work = FakeUnitOfWork(world)
    with unit_of_work:
        return {
            summary.entity_id
            for summary in unit_of_work.entities.search(PRINCIPAL, query, **kwargs)  # type: ignore[arg-type]
        }


# --- the five paths: each reaches an entity its own two names cannot ---------


def test_a_typed_name_reaches_an_entity_its_canonical_name_does_not(world: World) -> None:
    """`WP09-DECISION-1`'s constructive half, and audit section M's GS4 case.

    Nothing about "Kalvedge" contains "Ironworks". The only route from the query
    to the row is `entity_names`.
    """
    assert _found(world, "Ironworks") == {NAMED}
    assert _found(world, "Kalvedge") == {NAMED}


def test_a_communication_value_reaches_an_entity_and_so_does_its_domain(world: World) -> None:
    """Domain matching falls out of the substring match; no parser, no column.

    Both halves are asserted because only the second is new information: an
    exact-value match would satisfy the first while leaving "who else is at this
    company's mail domain" unanswerable, which is the question the audit asks.
    """
    assert _found(world, "rowan@ferrybridge.test") == {ADDRESSED}
    assert _found(world, "ferrybridge.test") == {ADDRESSED}


def test_an_affiliation_reaches_a_person_by_job_title_and_by_employer(world: World) -> None:
    """Both columns of the affiliation path, and the organization is the harder one.

    The employer's name is not on the person's row at all -- it is on a second
    entity, reached through `organization_entity_id`. The organization itself
    matches its own name directly, so both entities come back and the assertion
    says so rather than picking one.
    """
    assert _found(world, "Millwright") == {EMPLOYED}
    assert _found(world, "Vasqueline") == {EMPLOYED, EMPLOYER}


def test_a_project_role_reaches_a_participant_by_role_and_by_project(world: World) -> None:
    assert _found(world, "Commissioning") == {STAFFED}
    assert _found(world, "Saltmarsh") == {STAFFED}


def test_a_relationship_type_reaches_both_ends_of_the_edge(world: World) -> None:
    """The edge is undirected for the purposes of a browse query.

    A caller searching a relationship type is asking who stands in it, and both
    endpoints do. `COUNTERPARTY` is reached because it is the `to` side.
    """
    assert _found(world, "subcontractor") == {CONNECTED, COUNTERPARTY}


# --- WP09-DECISION-1: the boundary, enforced rather than described -----------


def test_an_alias_typed_name_is_not_reachable_through_search(world: World) -> None:
    """The recorded alias decision, extended to `entity_names` rather than reversed.

    `entities.resolve` matches aliases and discloses that it did.
    `entities.search` does not, and this is the assertion that keeps it so: the
    row exists, the query is its exact value, and the answer is empty.
    """
    assert _found(world, "Sunset Consulting") == set()
    assert _found(world, "Sunset") == set()


def test_a_historical_typed_name_is_not_reachable_through_search(world: World) -> None:
    """The second withheld type, for the reason the first is withheld.

    A former legal name is precisely "an identity somebody no longer uses", so
    the alias decision's own reason covers it without extension.
    """
    assert _found(world, "Sunrise Partners") == set()


def test_the_withheld_entity_is_reachable_by_its_own_name(world: World) -> None:
    """Anti-vacuity: the two assertions above would pass on an unreachable row.

    If `WITHHELD` were simply absent from the partition, every "not reachable"
    claim in this file would be true for the wrong reason. It is present, and
    its own display name finds it.
    """
    assert _found(world, "Zorrandel") == {WITHHELD}


# --- state: a row that records the past does not answer the present ----------


@pytest.mark.parametrize(
    ("query", "family"),
    [
        ("Meadowlark", "a retired typed name"),
        ("driftwood.test", "a superseded communication method"),
        ("Sailmaker", "a superseded affiliation"),
        ("Wendrilo", "a superseded affiliation's organization"),
        ("permitting", "an ended relationship"),
    ],
)
def test_a_child_row_outside_active_state_matches_nothing(
    world: World, query: str, family: str
) -> None:
    """Every added path filters on `active`, and each one is measured separately.

    A single query proving one family would leave the other four able to lose
    the filter silently. `Wendrilo` is the organization on the superseded
    affiliation and is itself an entity in the partition -- it is reachable by
    its own name, which is why the assertion below is written against `WITHHELD`
    rather than against emptiness.
    """
    assert WITHHELD not in _found(world, query), family


def test_the_superseded_affiliations_organization_is_still_found_by_its_own_name(
    world: World,
) -> None:
    """The complement of the parametrized case above, so it cannot pass vacuously."""
    assert _found(world, "Wendrilo") == {COUNTERPARTY}


# --- partition: a foreign child row decides nothing --------------------------


@pytest.mark.parametrize(
    "query",
    ["Ironworks", "rowan@ferrybridge.test", "Millwright", "Commissioning", "subcontractor"],
)
def test_another_principals_child_rows_never_reach_this_partition(world: World, query: str) -> None:
    """Each added subquery is scoped, not merely correlated on `entity_id`.

    The other Principal holds a colliding row on every one of the five families.
    A subquery that correlated on `entity_id` alone would still exclude it here,
    because the entity is foreign too -- so the assertion is made from the other
    side as well: searching as `OTHER` finds the foreign entity and nothing of
    this Principal's.
    """
    assert FOREIGN not in _found(world, query)
    unit_of_work = FakeUnitOfWork(world)
    with unit_of_work:
        theirs = {row.entity_id for row in unit_of_work.entities.search(OTHER, query)}
    assert theirs <= {FOREIGN, FOREIGN_PEER}


# --- escaping: a LIKE metacharacter in a query is a character ----------------


def test_a_percent_in_the_query_stays_literal(world: World) -> None:
    """`_contains` escapes against a stated ESCAPE character; the fake has none to escape.

    Both implementations must answer the same question, so the claim is written
    as a match rather than as a mechanism. Three assertions, and the third is
    the one a wildcard reading fails: under `LIKE` semantics `5_%off` matches
    both `50%_off` and `50XYoff`, because `_` is any character and `%` is any
    run of them. Read literally it matches neither, and neither is what comes
    back.

    A bare `%` is the sharpest form of the same claim: unescaped it selects the
    whole partition, which is a browse query answering a question nobody asked.
    """
    assert _found(world, "50XYoff") == {DECOY}
    assert _found(world, "50%_off") == {LITERAL}
    assert _found(world, "%") == {LITERAL}
    assert _found(world, "5_%off") == set()


# --- the keyset and its cursor survive the widening --------------------------


def test_the_widened_match_still_pages_by_the_keyset_it_orders_by(world: World) -> None:
    """One page, then its continuation, over rows reached through five paths.

    The page boundary is the part a widened `WHERE` is most likely to break: the
    keyset is `(canonical_name, entity_id)` and the cursor names an entity, so a
    match path that changed the ordering would make the walk skip or repeat.
    """
    unit_of_work = FakeUnitOfWork(world)
    with unit_of_work:
        first = unit_of_work.entities.search(PRINCIPAL, "e", limit=3)
        assert len(first) == 3
        following = unit_of_work.entities.search(
            PRINCIPAL, "e", limit=3, after_entity_id=first[-1].entity_id
        )
        walked = [summary.entity_id for summary in (*first, *following)]
        whole = [
            summary.entity_id for summary in unit_of_work.entities.search(PRINCIPAL, "e", limit=50)
        ]
    assert len(walked) == len(set(walked))
    assert walked == whole[: len(walked)]


def test_a_cursor_naming_another_principals_entity_is_refused(world: World) -> None:
    """`UnknownScopeError`, not an empty page: a caller cannot tell the two apart.

    Reporting completeness on a cursor that was never a position in this
    Principal's ordering is the shape of wrong answer the plane refuses
    everywhere else, and widening the match did not soften it.
    """
    unit_of_work = FakeUnitOfWork(world)
    with unit_of_work, pytest.raises(UnknownScopeError):
        unit_of_work.entities.search(PRINCIPAL, "e", after_entity_id=FOREIGN)


def test_an_entity_type_filter_still_narrows_a_context_match(world: World) -> None:
    """The optional filter composes with the new paths rather than being bypassed.

    "Vasqueline" reaches a person through their employer and the organization
    through its own name; asking for organizations must leave the person out.
    """
    assert _found(world, "Vasqueline", entity_type=EntityType.ORGANIZATION) == {EMPLOYER}
