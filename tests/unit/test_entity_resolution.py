"""Exact resolution, against the in-memory entity plane.

Organized around the failure this work package exists to prevent rather than
around the code that prevents it. Every test below names a way a resolver could
join two different people into one, and asserts that this one does not.

The type-level half is first: `EntityResolution` refuses to be constructed in a
shape that would let a caller read an entity identifier out of an unresolved
answer. That matters more than any single branch of the service, because it
holds for every future branch too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.contracts.ports import EntitiesRepository
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
from my_pa.domain.relationship.normalization import (
    NormalizationError,
    normalize_identifier,
    normalize_name,
)
from my_pa.domain.relationship.resolution import (
    RESOLUTION_CANDIDATE_LIMIT,
    ContextualSignal,
    EntityResolution,
    ResolutionBasis,
    ResolutionCandidate,
    ResolutionEvidence,
    ResolutionOutcome,
    ResolutionWarning,
)
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"

ALICE = "ent_aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002"
TOWER = "ent_dddd0004dddd0004"
THIRD = "ent_eeee0005eeee0005"
SECOND_ORG = "ent_ffff0006ffff0006"

WHEN = datetime(2026, 8, 17, 12, tzinfo=UTC)
BEFORE = WHEN - timedelta(days=365)
AFTER = WHEN + timedelta(days=365)


# --- normalization ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Alice Synthetic", "alice synthetic"),
        ("  Alice   Synthetic  ", "alice synthetic"),
        ("José Ángel", "jose angel"),
        ("O'Brien", "o brien"),
        ("Smith-Jones", "smith jones"),
        ("STRASSE", "strasse"),
        ("Straße", "strasse"),
    ],
)
def test_a_name_normalizes_to_its_comparable_form(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_name_normalization_is_idempotent() -> None:
    """A stored canonical name is already normalized, so normalizing again is a no-op."""
    once = normalize_name("José  O'Brien-Smith")
    assert normalize_name(once) == once


@pytest.mark.parametrize("blank", ["", "   ", "...", "—"])
def test_a_name_that_normalizes_to_nothing_is_refused(blank: str) -> None:
    """An empty normalized value would match nothing or everything by accident."""
    with pytest.raises(NormalizationError):
        normalize_name(blank)


def test_punctuation_separates_rather_than_disappears() -> None:
    """`O'Brien` must not become `obrien` and collide with a different person."""
    assert normalize_name("O'Brien") != normalize_name("OBrien")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Alice@Example.TEST", "alice@example.test"),
        ("  alice@example.test  ", "alice@example.test"),
    ],
)
def test_an_email_lowercases_both_halves(raw: str, expected: str) -> None:
    assert normalize_identifier(ExternalIdentifierNamespace.EMAIL, raw) == expected


def test_an_email_local_part_is_not_rewritten() -> None:
    """Dot and plus folding is one provider's rule and a false join everywhere else."""
    namespace = ExternalIdentifierNamespace.EMAIL
    assert normalize_identifier(namespace, "a.b@example.test") != normalize_identifier(
        namespace, "ab@example.test"
    )
    assert normalize_identifier(namespace, "a+tag@example.test") != normalize_identifier(
        namespace, "a@example.test"
    )


@pytest.mark.parametrize("malformed", ["alice", "@example.test", "alice@", "a b@example.test"])
def test_a_malformed_email_is_refused(malformed: str) -> None:
    with pytest.raises(NormalizationError):
        normalize_identifier(ExternalIdentifierNamespace.EMAIL, malformed)


def test_an_opaque_vendor_identifier_keeps_its_case() -> None:
    """Its issuer may treat case as significant; folding it could collide two records."""
    namespace = ExternalIdentifierNamespace.VENDOR_SYSTEM_ID
    assert normalize_identifier(namespace, "AbC123") == "AbC123"
    assert normalize_identifier(namespace, "AbC123") != normalize_identifier(namespace, "abc123")


def test_an_entra_object_id_is_case_folded() -> None:
    """A UUID's hexadecimal is case-insensitive by its own specification."""
    namespace = ExternalIdentifierNamespace.ENTRA_OBJECT_ID
    assert normalize_identifier(namespace, "ABCD-1234") == normalize_identifier(
        namespace, "abcd-1234"
    )


# --- the type refuses to be read as a resolution when it is not one ---------


def an_evidence(basis: ResolutionBasis = ResolutionBasis.ALIAS) -> ResolutionEvidence:
    return ResolutionEvidence(basis=basis, matched_value="alice synthetic")


def a_candidate(
    entity_id: str = ALICE,
    status: EntityStatus = EntityStatus.ACTIVE,
    basis: ResolutionBasis = ResolutionBasis.ALIAS,
) -> ResolutionCandidate:
    return ResolutionCandidate(
        entity_id=entity_id,
        entity_type=EntityType.PERSON,
        display_name="Alice Synthetic",
        status=status,
        evidence=(an_evidence(basis),),
        superseded_by_entity_id=ALICE_TWO if status is EntityStatus.MERGED_REDIRECT else None,
    )


@pytest.mark.parametrize(
    "outcome",
    [
        ResolutionOutcome.AMBIGUOUS,
        ResolutionOutcome.NOT_FOUND,
        ResolutionOutcome.CONFLICTED_IDENTIFIER,
        ResolutionOutcome.HISTORICAL_MATCH,
    ],
)
def test_an_unresolved_outcome_yields_no_entity_identifier(
    outcome: ResolutionOutcome,
) -> None:
    """The safety rule as a property of the type, for every outcome that is not a match."""
    if outcome is ResolutionOutcome.NOT_FOUND:
        resolution = EntityResolution(outcome=outcome)
    elif outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER:
        resolution = EntityResolution(
            outcome=outcome,
            candidates=(a_candidate(ALICE), a_candidate(ALICE_TWO)),
            warnings=(ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES,),
        )
    elif outcome is ResolutionOutcome.HISTORICAL_MATCH:
        resolution = EntityResolution(
            outcome=outcome, candidates=(a_candidate(status=EntityStatus.INACTIVE),)
        )
    else:
        resolution = EntityResolution(outcome=outcome, candidates=(a_candidate(),))
    assert resolution.resolved_entity_id is None
    assert resolution.is_resolved is False


def test_a_resolved_outcome_yields_exactly_one_identifier() -> None:
    resolution = EntityResolution(
        outcome=ResolutionOutcome.RESOLVED_EXACT, candidates=(a_candidate(),)
    )
    assert resolution.resolved_entity_id == ALICE
    assert resolution.is_resolved is True


def test_a_resolved_outcome_cannot_name_two_entities() -> None:
    with pytest.raises(ValueError, match="names exactly one entity"):
        EntityResolution(
            outcome=ResolutionOutcome.RESOLVED_EXACT,
            candidates=(a_candidate(ALICE), a_candidate(ALICE_TWO)),
        )


def test_a_not_found_outcome_cannot_carry_a_candidate() -> None:
    with pytest.raises(ValueError, match="names no entity"):
        EntityResolution(outcome=ResolutionOutcome.NOT_FOUND, candidates=(a_candidate(),))


def test_an_ambiguous_outcome_names_what_it_could_not_choose_between() -> None:
    with pytest.raises(ValueError, match="could not choose between"):
        EntityResolution(outcome=ResolutionOutcome.AMBIGUOUS)


def test_a_conflicted_identifier_needs_more_than_one_claimant() -> None:
    with pytest.raises(ValueError, match="claimed by more than one entity"):
        EntityResolution(
            outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
            candidates=(a_candidate(),),
            warnings=(ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES,),
        )


def test_a_conflicted_identifier_must_say_so_in_its_warnings() -> None:
    with pytest.raises(ValueError, match="says the identifier is conflicted"):
        EntityResolution(
            outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
            candidates=(a_candidate(ALICE), a_candidate(ALICE_TWO)),
        )


def test_a_name_alone_cannot_be_a_resolved_outcome() -> None:
    """The type refuses it, so no future branch of the service can produce it."""
    with pytest.raises(ValueError, match="a name alone does not resolve"):
        EntityResolution(
            outcome=ResolutionOutcome.RESOLVED_EXACT,
            candidates=(a_candidate(basis=ResolutionBasis.CANONICAL_NAME),),
        )


def test_a_resolved_outcome_cannot_name_a_stale_entity() -> None:
    with pytest.raises(ValueError, match="names a current entity"):
        EntityResolution(
            outcome=ResolutionOutcome.RESOLVED_EXACT,
            candidates=(a_candidate(status=EntityStatus.ARCHIVED),),
        )


def test_a_historical_match_cannot_name_a_current_entity() -> None:
    with pytest.raises(ValueError, match="names an entity that is not current"):
        EntityResolution(outcome=ResolutionOutcome.HISTORICAL_MATCH, candidates=(a_candidate(),))


def test_a_candidate_states_why_it_is_a_candidate() -> None:
    with pytest.raises(ValueError, match="states why it is a candidate"):
        ResolutionCandidate(
            entity_id=ALICE,
            entity_type=EntityType.PERSON,
            display_name="Alice Synthetic",
            status=EntityStatus.ACTIVE,
            evidence=(),
        )


def test_evidence_does_not_carry_a_matched_value_into_a_repr() -> None:
    """A normalized email in a traceback is the disclosure section 5 forbids."""
    assert "alice@example.test" not in repr(
        ResolutionEvidence(
            basis=ResolutionBasis.EXTERNAL_IDENTIFIER, matched_value="alice@example.test"
        )
    )


# --- the service ------------------------------------------------------------


def an_entity(
    entity_id: str,
    display_name: str,
    principal_id: str = PRINCIPAL,
    entity_type: EntityType = EntityType.PERSON,
    status: EntityStatus = EntityStatus.ACTIVE,
    superseded_by: str | None = None,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=status,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
        superseded_by_entity_id=superseded_by,
    )


def an_email(
    identifier_id: str,
    entity_id: str,
    address: str,
    verified: bool = False,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> ExternalIdentifier:
    return ExternalIdentifier(
        identifier_id=identifier_id,
        entity_id=entity_id,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value=normalize_identifier(ExternalIdentifierNamespace.EMAIL, address),
        display_value=address,
        principal_id=PRINCIPAL,
        verified=verified,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def an_alias(alias_id: str, entity_id: str, name: str, **dates: object) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=AliasType.NICKNAME,
        normalized_value=normalize_name(name),
        display_value=name,
        principal_id=PRINCIPAL,
        **dates,  # type: ignore[arg-type]
    )


@pytest.fixture
def resolving(world: World) -> EntityResolutionService:
    return EntityResolutionService(_Entities(world))


def _Entities(world: World):  # noqa: ANN202, N802
    """The plane's fake, reached the way production reaches it."""
    return FakeUnitOfWork(world).entities


def test_a_verified_identifier_resolves_exactly(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.bind_identifier(
        PRINCIPAL, ALICE, an_email("xid_aaaa0001aaaa0001", ALICE, "alice@example.test", True)
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="Alice@Example.TEST", namespace=ExternalIdentifierNamespace.EMAIL
        ),
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_EXACT
    assert answer.resolved_entity_id == ALICE
    assert answer.candidates[0].strongest_basis is ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER
    assert answer.warnings == ()


def test_an_unverified_identifier_resolves_but_says_so(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.bind_identifier(
        PRINCIPAL, ALICE, an_email("xid_aaaa0001aaaa0001", ALICE, "alice@example.test")
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="alice@example.test", namespace=ExternalIdentifierNamespace.EMAIL
        ),
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_EXACT
    assert ResolutionWarning.MATCHED_IDENTIFIER_IS_UNVERIFIED in answer.warnings


def test_one_identifier_claimed_by_two_entities_is_a_stop(
    world: World, resolving: EntityResolutionService
) -> None:
    """Section 15.2: conflicting identifiers prevent an automatic join."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Other"))
    for identifier_id, entity_id in (
        ("xid_aaaa0001aaaa0001", ALICE),
        ("xid_bbbb0002bbbb0002", ALICE_TWO),
    ):
        entities.bind_identifier(
            PRINCIPAL, entity_id, an_email(identifier_id, entity_id, "shared@example.test", True)
        )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="shared@example.test", namespace=ExternalIdentifierNamespace.EMAIL
        ),
    )
    assert answer.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER
    assert answer.resolved_entity_id is None
    assert ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES in answer.warnings
    assert {candidate.entity_id for candidate in answer.candidates} == {ALICE, ALICE_TWO}


def test_an_identifier_outside_its_effective_dates_does_not_resolve(
    world: World, resolving: EntityResolutionService
) -> None:
    """A mailbox someone else has since been given must not still name its old holder."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.bind_identifier(
        PRINCIPAL,
        ALICE,
        an_email(
            "xid_aaaa0001aaaa0001",
            ALICE,
            "alice@example.test",
            True,
            effective_from=BEFORE,
            effective_to=BEFORE + timedelta(days=1),
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="alice@example.test",
            namespace=ExternalIdentifierNamespace.EMAIL,
            as_of=WHEN,
        ),
    )
    assert answer.resolved_entity_id is None
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_identifier_within_its_effective_dates_resolves(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.bind_identifier(
        PRINCIPAL,
        ALICE,
        an_email(
            "xid_aaaa0001aaaa0001",
            ALICE,
            "alice@example.test",
            True,
            effective_from=BEFORE,
            effective_to=AFTER,
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="alice@example.test",
            namespace=ExternalIdentifierNamespace.EMAIL,
            as_of=WHEN,
        ),
    )
    assert answer.resolved_entity_id == ALICE


def test_an_identifier_on_a_merged_entity_is_a_historical_match(
    world: World, resolving: EntityResolutionService
) -> None:
    """The caller is told the record is not current rather than handed it as live."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Survivor"))
    entities.create(
        PRINCIPAL,
        an_entity(
            ALICE,
            "Alice Synthetic",
            status=EntityStatus.MERGED_REDIRECT,
            superseded_by=ALICE_TWO,
        ),
    )
    entities.bind_identifier(
        PRINCIPAL, ALICE, an_email("xid_aaaa0001aaaa0001", ALICE, "alice@example.test", True)
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="alice@example.test", namespace=ExternalIdentifierNamespace.EMAIL
        ),
    )
    assert answer.outcome is ResolutionOutcome.HISTORICAL_MATCH
    assert answer.resolved_entity_id is None
    assert ResolutionWarning.ENTITY_HAS_BEEN_MERGED_AWAY in answer.warnings
    assert answer.candidates[0].superseded_by_entity_id == ALICE_TWO


def test_a_lone_name_match_is_ambiguous_not_resolved(
    world: World, resolving: EntityResolutionService
) -> None:
    """The single most important refusal here.

    One entity carries this name and no other does, and that is still not
    evidence that this reference means that entity. Uniqueness is a fact about
    the database, not about the person.
    """
    _Entities(world).create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic"))
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert [candidate.entity_id for candidate in answer.candidates] == [ALICE]


def test_two_entities_sharing_a_name_are_ambiguous(
    world: World, resolving: EntityResolutionService
) -> None:
    """Same-name protection: neither is chosen, and both are shown."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="alice synthetic"))
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert {candidate.entity_id for candidate in answer.candidates} == {ALICE, ALICE_TWO}
    assert ResolutionWarning.SEVERAL_ENTITIES_SHARE_THIS_NAME in answer.warnings


def test_an_alias_match_resolves(world: World, resolving: EntityResolutionService) -> None:
    """An alias is a recorded fact about the entity; a bare canonical name is not."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.record_alias(PRINCIPAL, an_alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Ali"))
    assert answer.outcome is ResolutionOutcome.RESOLVED_EXACT
    assert answer.resolved_entity_id == ALICE
    assert answer.candidates[0].strongest_basis is ResolutionBasis.ALIAS


def test_two_entities_sharing_an_alias_are_ambiguous(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alicia Other"))
    entities.record_alias(PRINCIPAL, an_alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    entities.record_alias(PRINCIPAL, an_alias("eals_bbbb0002bbbb0002", ALICE_TWO, "Ali"))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Ali"))
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None


def test_an_alias_outside_its_effective_dates_is_excluded(
    world: World, resolving: EntityResolutionService
) -> None:
    """A former name matches history, not the present, when a moment was asked about."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.record_alias(
        PRINCIPAL,
        an_alias(
            "eals_aaaa0001aaaa0001",
            ALICE,
            "Ali",
            effective_from=BEFORE,
            effective_to=BEFORE + timedelta(days=1),
        ),
    )
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Ali", as_of=WHEN))
    assert answer.outcome is ResolutionOutcome.NOT_FOUND
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_entity_type_filter_excludes_a_same_named_entity_of_another_kind(
    world: World, resolving: EntityResolutionService
) -> None:
    """A caller asking for a project does not want the person who shares its name."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Tower"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Tower", entity_type=EntityType.PROJECT))
    entities.record_alias(PRINCIPAL, an_alias("eals_aaaa0001aaaa0001", TOWER, "Tower"))
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Tower", entity_type=EntityType.PROJECT)
    )
    assert answer.resolved_entity_id == TOWER


def test_a_scope_narrows_two_same_named_people_to_one(
    world: World, resolving: EntityResolutionService
) -> None:
    """Contextual resolution, and it is reported as contextual rather than exact."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(
        PRINCIPAL,
        Assignment(
            assignment_id="asn_aaaa0001aaaa0001",
            entity_id=ALICE,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            principal_id=PRINCIPAL,
            scope_entity_id=TOWER,
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.resolved_entity_id == ALICE
    assert ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE in answer.warnings


def test_a_scope_that_narrows_nothing_leaves_the_answer_ambiguous(
    world: World, resolving: EntityResolutionService
) -> None:
    """A hint that excluded nobody has not resolved anything.

    Both candidates are on the project, so the scope is true of both and
    distinguishes neither. Crediting it with the answer would report
    `RESOLVED_CONTEXTUAL` for a coin flip.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    for assignment_id, entity_id in (
        ("asn_aaaa0001aaaa0001", ALICE),
        ("asn_bbbb0002bbbb0002", ALICE_TWO),
    ):
        entities.record_assignment(
            PRINCIPAL,
            Assignment(
                assignment_id=assignment_id,
                entity_id=entity_id,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                principal_id=PRINCIPAL,
                scope_entity_id=TOWER,
            ),
        )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None


def test_a_scope_that_excludes_everyone_leaves_the_answer_ambiguous(
    world: World, resolving: EntityResolutionService
) -> None:
    """Narrowing to nothing is not evidence; the unnarrowed candidates are returned."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert len(answer.candidates) == 2


def test_nothing_matching_is_not_found(world: World, resolving: EntityResolutionService) -> None:
    _Entities(world).create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Nobody At All"))
    assert answer.outcome is ResolutionOutcome.NOT_FOUND
    assert answer.candidates == ()


def test_an_identifier_that_matches_nothing_falls_through_to_the_name(
    world: World, resolving: EntityResolutionService
) -> None:
    """A reference that matched no mailbox may still be a name."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "alice@example.test"))
    entities.record_alias(PRINCIPAL, an_alias("eals_aaaa0001aaaa0001", ALICE, "alice@example.test"))
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="alice@example.test", namespace=ExternalIdentifierNamespace.EMAIL
        ),
    )
    assert answer.resolved_entity_id == ALICE
    assert answer.candidates[0].strongest_basis is ResolutionBasis.ALIAS


def test_resolution_cannot_reach_another_principals_entity(
    world: World, resolving: EntityResolutionService
) -> None:
    """The partition holds through resolution, not only through the repository."""
    entities = _Entities(world)
    entities.create(OTHER, an_entity(ALICE, "Alice Synthetic", principal_id=OTHER))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic"))
    assert answer.outcome is ResolutionOutcome.NOT_FOUND


def test_every_candidate_carries_the_evidence_for_it(
    world: World, resolving: EntityResolutionService
) -> None:
    """Explainability: an answer no one can check is an answer no one should act on."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.record_alias(PRINCIPAL, an_alias("eals_aaaa0001aaaa0001", ALICE, "Alice Synthetic"))
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic"))
    assert answer.candidates
    for candidate in answer.candidates:
        assert candidate.evidence
        assert {evidence.basis for evidence in candidate.evidence} == {
            ResolutionBasis.ALIAS,
            ResolutionBasis.CANONICAL_NAME,
        }


def test_candidates_are_presented_strongest_evidence_first(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.record_alias(
        PRINCIPAL, an_alias("eals_bbbb0002bbbb0002", ALICE_TWO, "Alice Synthetic")
    )
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic"))
    assert [candidate.entity_id for candidate in answer.candidates] == [ALICE_TWO, ALICE]
    assert answer.resolved_entity_id is None


def test_a_blank_reference_is_refused_before_it_becomes_a_query() -> None:
    with pytest.raises(ValueError, match="names something to resolve"):
        ResolutionRequest(raw_reference="   ")


# --- WP-RI-04: bounded ranking, signals, and truncation ---------------------


def test_a_contextual_resolution_carries_the_signal_that_selected_it(
    world: World, resolving: EntityResolutionService
) -> None:
    """An unexplained selection is not explainable, whatever else it is."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(
        PRINCIPAL,
        Assignment(
            assignment_id="asn_aaaa0001aaaa0001",
            entity_id=ALICE,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            principal_id=PRINCIPAL,
            scope_entity_id=TOWER,
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.candidates[0].signals == (ContextualSignal.ASSIGNED_TO_THE_NAMED_SCOPE,)
    assert answer.candidates[0].is_corroborated is True


def test_a_relationship_reaching_the_scope_is_its_own_signal(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(SECOND_ORG, "Acme", entity_type=EntityType.ORGANIZATION))
    entities.record_relationship(
        PRINCIPAL,
        EntityRelationship(
            relationship_id="erel_aaaa0001aaaa0001",
            from_entity_id=ALICE,
            relationship_type=EntityRelationshipType.WORKS_FOR,
            to_entity_id=SECOND_ORG,
            principal_id=PRINCIPAL,
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=SECOND_ORG)
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.candidates[0].signals == (ContextualSignal.RELATED_TO_THE_NAMED_SCOPE,)


def test_context_true_of_everyone_is_disclosed_as_having_distinguished_nobody(
    world: World, resolving: EntityResolutionService
) -> None:
    """Noticing and declining is a different disclosure from never looking."""
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    for assignment_id, entity_id in (
        ("asn_aaaa0001aaaa0001", ALICE),
        ("asn_bbbb0002bbbb0002", ALICE_TWO),
    ):
        entities.record_assignment(
            PRINCIPAL,
            Assignment(
                assignment_id=assignment_id,
                entity_id=entity_id,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                principal_id=PRINCIPAL,
                scope_entity_id=TOWER,
            ),
        )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert ResolutionWarning.CONTEXT_DID_NOT_DISTINGUISH_THE_CANDIDATES in answer.warnings
    assert all(candidate.signals for candidate in answer.candidates)


def test_narrowing_to_two_is_still_ambiguous(
    world: World, resolving: EntityResolutionService
) -> None:
    """Narrowing is not choosing.

    Three people share the name and two are on the project. The scope excluded
    the third, which is real work, and the answer is still `AMBIGUOUS` because
    two remain. A resolver that treated "the context narrowed something" as
    "the context decided" would answer here, and would be wrong half the time.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(THIRD, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    for assignment_id, entity_id in (
        ("asn_aaaa0001aaaa0001", ALICE),
        ("asn_bbbb0002bbbb0002", ALICE_TWO),
    ):
        entities.record_assignment(
            PRINCIPAL,
            Assignment(
                assignment_id=assignment_id,
                entity_id=entity_id,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                principal_id=PRINCIPAL,
                scope_entity_id=TOWER,
            ),
        )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert {candidate.entity_id for candidate in answer.candidates} == {ALICE, ALICE_TWO}
    assert all(candidate.signals for candidate in answer.candidates)
    assert ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE in answer.warnings


def test_an_answer_carrying_more_candidates_than_the_bound_is_truncated_and_says_so(
    world: World, resolving: EntityResolutionService
) -> None:
    """A truncated list that reads as complete is the failure section 26.4 names."""
    entities = _Entities(world)
    for index in range(RESOLUTION_CANDIDATE_LIMIT + 3):
        entities.create(
            PRINCIPAL, an_entity(f"ent_crowd{index:04d}crowd{index:04d}", "Alice Synthetic")
        )
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic"))
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert len(answer.candidates) == RESOLUTION_CANDIDATE_LIMIT
    assert answer.candidates_were_truncated is True
    assert ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES in answer.warnings


def test_a_truncated_answer_can_never_be_a_resolution(
    world: World, resolving: EntityResolutionService
) -> None:
    """A resolution drawn from a list that dropped someone never saw them."""
    entities = _Entities(world)
    for index in range(RESOLUTION_CANDIDATE_LIMIT + 1):
        entity_id = f"ent_crowd{index:04d}crowd{index:04d}"
        entities.create(PRINCIPAL, an_entity(entity_id, "Alice Synthetic"))
        entities.record_alias(
            PRINCIPAL, an_alias(f"eals_crowd{index:04d}crowd{index:04d}", entity_id, "Ali")
        )
    answer = resolving.resolve(PRINCIPAL, ResolutionRequest(raw_reference="Ali"))
    assert answer.resolved_entity_id is None
    assert answer.candidates_were_truncated is True


def test_the_type_refuses_a_resolution_that_admits_it_was_truncated() -> None:
    with pytest.raises(ValueError, match="not one candidate out of an unknown many"):
        EntityResolution(
            outcome=ResolutionOutcome.RESOLVED_EXACT,
            candidates=(a_candidate(),),
            warnings=(ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES,),
            candidates_were_truncated=True,
        )


def test_the_type_refuses_more_candidates_than_the_bound() -> None:
    crowd = tuple(
        a_candidate(f"ent_crowd{index:04d}crowd{index:04d}")
        for index in range(RESOLUTION_CANDIDATE_LIMIT + 1)
    )
    with pytest.raises(ValueError, match="bounded candidate list"):
        EntityResolution(outcome=ResolutionOutcome.AMBIGUOUS, candidates=crowd)


def test_a_signal_outside_the_closed_vocabulary_is_refused() -> None:
    with pytest.raises(ValueError, match="closed vocabulary"):
        ResolutionCandidate(
            entity_id=ALICE,
            entity_type=EntityType.PERSON,
            display_name="Alice Synthetic",
            status=EntityStatus.ACTIVE,
            evidence=(an_evidence(),),
            signals=("assigned_to_the_named_scope",),  # type: ignore[arg-type]
        )


# --- regressions found by adversarial review --------------------------------


def test_an_entity_type_filter_cannot_collapse_a_conflicted_identifier(
    world: World, resolving: EntityResolutionService
) -> None:
    """A conflict is a property of the data, not of the question asked about it.

    The shape that found this: one shared mailbox recorded against a person and
    against the organization. Filtering by type before counting claimants made
    each filtered view see exactly one, so the same address resolved *exactly*
    to the person for one caller and to the organization for the next, with no
    warning at all. Both callers would have been told a confident wrong answer.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Office Manager"))
    entities.create(PRINCIPAL, an_entity(SECOND_ORG, "Acme", entity_type=EntityType.ORGANIZATION))
    for identifier_id, entity_id in (
        ("xid_aaaa0001aaaa0001", ALICE),
        ("xid_bbbb0002bbbb0002", SECOND_ORG),
    ):
        entities.bind_identifier(
            PRINCIPAL, entity_id, an_email(identifier_id, entity_id, "info@acme.test", True)
        )
    for entity_type in (None, EntityType.PERSON, EntityType.ORGANIZATION):
        answer = resolving.resolve(
            PRINCIPAL,
            ResolutionRequest(
                raw_reference="info@acme.test",
                namespace=ExternalIdentifierNamespace.EMAIL,
                entity_type=entity_type,
            ),
        )
        assert answer.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER, entity_type
        assert answer.resolved_entity_id is None, entity_type
        assert ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES in answer.warnings


def test_a_lone_corroborated_candidate_resolves_without_needing_a_rival(
    world: World, resolving: EntityResolutionService
) -> None:
    """More evidence must not produce a weaker answer.

    Keying the decision on "did the scope exclude anyone" meant that *adding a
    duplicate row* upgraded a refusal into a resolution: one Alice on the named
    project answered `AMBIGUOUS`, and the same Alice with a same-named stranger
    beside her answered `RESOLVED_CONTEXTUAL`. Non-uniqueness was licensing the
    join — the inverse of this plane's own rule.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(
        PRINCIPAL,
        Assignment(
            assignment_id="asn_aaaa0001aaaa0001",
            entity_id=ALICE,
            assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
            principal_id=PRINCIPAL,
            scope_entity_id=TOWER,
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.resolved_entity_id == ALICE
    assert answer.candidates[0].signals == (ContextualSignal.ASSIGNED_TO_THE_NAMED_SCOPE,)


def test_a_scope_true_of_nobody_is_disclosed_rather_than_silent(
    world: World, resolving: EntityResolutionService
) -> None:
    """A scope that matched nobody used to be indistinguishable from silence.

    The warning fired only when some candidate carried a signal, so the case
    where the scope fit none of them — the likeliest sign the caller named the
    wrong scope — was the one case that said nothing.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER)
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert ResolutionWarning.CONTEXT_DID_NOT_DISTINGUISH_THE_CANDIDATES in answer.warnings


def test_a_record_cannot_store_a_value_resolution_would_never_match(
    world: World, resolving: EntityResolutionService
) -> None:
    """The write-side half of the matching policy.

    A single entity whose `canonical_name` was stored unnormalized removed
    *itself* from the candidate set and thereby promoted its same-named
    neighbour from an ambiguous refusal to a confident wrong answer. The records
    refuse it now, so the rules in `relationship.normalization` bind the writer
    as well as the query.
    """
    with pytest.raises(ValueError, match="already normalized"):
        Entity(
            entity_id=ALICE_TWO,
            principal_id=PRINCIPAL,
            entity_type=EntityType.PERSON,
            canonical_name="Alice Synthetic",
            display_name="Alice Synthetic",
            status=EntityStatus.ACTIVE,
            created_at=WHEN,
            updated_at=WHEN,
            version=1,
        )
    with pytest.raises(ValueError, match="already normalized"):
        an_alias("eals_aaaa0001aaaa0001", ALICE, "Ali").__class__(
            alias_id="eals_bbbb0002bbbb0002",
            entity_id=ALICE,
            alias_type=AliasType.NICKNAME,
            normalized_value="O'Brien",
            display_value="O'Brien",
            principal_id=PRINCIPAL,
        )
    with pytest.raises(ValueError, match="already normalized"):
        ExternalIdentifier(
            identifier_id="xid_cccc0003cccc0003",
            entity_id=ALICE,
            namespace=ExternalIdentifierNamespace.EMAIL,
            normalized_value="Alice@Example.TEST",
            display_value="Alice@Example.TEST",
            principal_id=PRINCIPAL,
        )


# --- a signal has to be current to corroborate ------------------------------
#
# Every test below names a way a *stale* connection to the named scope used to
# lift a bare canonical name into `RESOLVED_CONTEXTUAL` -- a confident answer,
# carrying an entity identifier, with no warning on it at all. The guards are
# `_is_in_force` and the `state`/`active_only` filters, and each of them survived
# deletion against the whole suite before these tests existed.


def _scope(entities: EntitiesRepository) -> None:
    """One person and the project every test in this section names as the scope."""
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Harbour Tower", entity_type=EntityType.PROJECT))


def _edge(relationship_id: str, **kwargs: object) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=relationship_id,
        from_entity_id=ALICE,
        relationship_type=EntityRelationshipType.CONTRACTOR_ON,
        to_entity_id=TOWER,
        principal_id=PRINCIPAL,
        **kwargs,  # type: ignore[arg-type]
    )


def _assignment(assignment_id: str, **kwargs: object) -> Assignment:
    return Assignment(
        assignment_id=assignment_id,
        entity_id=ALICE,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL,
        scope_entity_id=TOWER,
        **kwargs,  # type: ignore[arg-type]
    )


def _by_name(resolving: EntityResolutionService, **kwargs: object) -> EntityResolution:
    return resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER, **kwargs),  # type: ignore[arg-type]
    )


def test_a_relationship_that_has_ended_does_not_corroborate(
    world: World, resolving: EntityResolutionService
) -> None:
    """`relationships()` takes no `active_only`, so this filter is the only one.

    An ended assignment already stopped corroborating and an ended relationship
    did not, which made a confident answer depend on which of two tables the
    same fact had been written to.
    """
    entities = _Entities(world)
    _scope(entities)
    entities.record_relationship(PRINCIPAL, _edge("erel_aaaa0001aaaa0001", state="ended"))
    answer = _by_name(resolving)
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert answer.candidates[0].signals == ()


def test_an_unrecognised_relationship_state_does_not_corroborate(
    world: World, resolving: EntityResolutionService
) -> None:
    """`state` is free text on the record, so anything but active reads as not live."""
    entities = _Entities(world)
    _scope(entities)
    entities.record_relationship(PRINCIPAL, _edge("erel_aaaa0001aaaa0001", state="disputed"))
    assert _by_name(resolving).outcome is ResolutionOutcome.AMBIGUOUS


def test_a_relationship_whose_dates_are_over_does_not_corroborate_without_a_moment(
    world: World, resolving: EntityResolutionService
) -> None:
    """The default request asks no temporal question, and used to get a stale yes.

    `as_of=None` means "do not filter by time" for the evidence the reference
    matched. It must not mean it for a signal, which claims the candidate *is*
    on the named project.
    """
    entities = _Entities(world)
    _scope(entities)
    entities.record_relationship(
        PRINCIPAL, _edge("erel_aaaa0001aaaa0001", effective_from=BEFORE, effective_to=BEFORE)
    )
    answer = _by_name(resolving)
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_assignment_whose_dates_are_over_does_not_corroborate_without_a_moment(
    world: World, resolving: EntityResolutionService
) -> None:
    """`active_only` is not enough: a status nobody updated is the other stale shape."""
    entities = _Entities(world)
    _scope(entities)
    entities.record_assignment(
        PRINCIPAL, _assignment("asn_aaaa0001aaaa0001", effective_from=BEFORE, effective_to=BEFORE)
    )
    answer = _by_name(resolving)
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_assignment_that_is_not_active_does_not_corroborate(
    world: World, resolving: EntityResolutionService
) -> None:
    entities = _Entities(world)
    _scope(entities)
    entities.record_assignment(PRINCIPAL, _assignment("asn_aaaa0001aaaa0001", status="ended"))
    assert _by_name(resolving).outcome is ResolutionOutcome.AMBIGUOUS


def test_a_relationship_still_running_corroborates(
    world: World, resolving: EntityResolutionService
) -> None:
    """The other half of the trade: a rule that refused everything is not a fix."""
    entities = _Entities(world)
    _scope(entities)
    entities.record_relationship(
        PRINCIPAL, _edge("erel_aaaa0001aaaa0001", effective_from=BEFORE, effective_to=None)
    )
    answer = _by_name(resolving)
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.resolved_entity_id == ALICE


def test_an_ended_relationship_still_corroborates_at_a_moment_it_covered(
    world: World, resolving: EntityResolutionService
) -> None:
    """A caller who names a moment gets that moment's answer rather than today's."""
    entities = _Entities(world)
    _scope(entities)
    entities.record_relationship(
        PRINCIPAL, _edge("erel_aaaa0001aaaa0001", effective_from=BEFORE, effective_to=AFTER)
    )
    answer = _by_name(resolving, as_of=WHEN)
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.candidates[0].signals == (ContextualSignal.RELATED_TO_THE_NAMED_SCOPE,)


def test_only_an_outgoing_edge_corroborates(
    world: World, resolving: EntityResolutionService
) -> None:
    """`direction="outgoing"` is a constraint, not a default nobody checked.

    The edge below reaches the scope -- it is *scoped by* the tower project --
    but it is somebody else's edge, pointing at this candidate. A signal is
    something recorded about the candidate, and widening the direction would let
    a claim another entity made be read as one she made about herself.
    """
    entities = _Entities(world)
    _scope(entities)
    entities.create(PRINCIPAL, an_entity(SECOND_ORG, "Acme", entity_type=EntityType.ORGANIZATION))
    entities.record_relationship(
        PRINCIPAL,
        EntityRelationship(
            relationship_id="erel_aaaa0001aaaa0001",
            from_entity_id=SECOND_ORG,
            relationship_type=EntityRelationshipType.CONTRACTOR_ON,
            to_entity_id=ALICE,
            principal_id=PRINCIPAL,
            scope_entity_id=TOWER,
        ),
    )
    answer = _by_name(resolving)
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.candidates[0].signals == ()


def test_a_contextual_resolution_that_rested_on_the_scope_says_so(
    world: World, resolving: EntityResolutionService
) -> None:
    """The lone-corroborated answer used to carry no warning at all.

    `NARROWED_BY_SUPPLIED_SCOPE` is defined as "the answer would have been
    `AMBIGUOUS` without it", which is exactly this answer -- and the one outcome
    that most needs the disclosure was the one that made it silently.
    """
    entities = _Entities(world)
    _scope(entities)
    entities.record_assignment(PRINCIPAL, _assignment("asn_aaaa0001aaaa0001"))
    answer = _by_name(resolving)
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE in answer.warnings


def test_an_alias_match_does_not_credit_the_scope_with_the_decision(
    world: World, resolving: EntityResolutionService
) -> None:
    """The alias resolved it and the scope only agreed; saying otherwise overstates the hint."""
    entities = _Entities(world)
    _scope(entities)
    entities.record_alias(PRINCIPAL, an_alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    entities.record_assignment(PRINCIPAL, _assignment("asn_aaaa0001aaaa0001"))
    answer = resolving.resolve(
        PRINCIPAL, ResolutionRequest(raw_reference="Ali", scope_entity_id=TOWER)
    )
    assert ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE not in answer.warnings


NOW = datetime(2026, 8, 19, 12, tzinfo=UTC)


def test_an_assignment_that_has_not_begun_does_not_corroborate(
    world: World, resolving: EntityResolutionService
) -> None:
    """A role starting in 2030 must not lift a bare name today.

    Currency used to be inferred from `effective_to is None` -- "nobody wrote an
    end date" -- so an assignment that had not started read as in force and
    corroborated a bare canonical name into `RESOLVED_CONTEXTUAL`. The residual
    recorded against this said detecting it needed a clock the module did not
    have; the clock is `authorization.at`, and `ResolutionRequest.at` carries it.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(
        PRINCIPAL,
        _assignment("asn_aaaa0001aaaa0001", effective_from=datetime(2030, 1, 1, tzinfo=UTC)),
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER, at=NOW),
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_assignment_running_to_a_future_end_date_still_corroborates(
    world: World, resolving: EntityResolutionService
) -> None:
    """The other half, and the one that made the old rule wrong for ordinary data.

    A contract with a recorded end date in 2030 is in force today. Reading
    "somebody wrote an end date" as "over" meant every dated employment --
    the ordinary case -- corroborated nothing, and said so with a warning whose
    every clause was false for it.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(
        PRINCIPAL,
        _assignment(
            "asn_aaaa0001aaaa0001",
            effective_from=datetime(2025, 1, 1, tzinfo=UTC),
            effective_to=datetime(2030, 1, 1, tzinfo=UTC),
        ),
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER, at=NOW),
    )
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.candidates[0].signals == (ContextualSignal.ASSIGNED_TO_THE_NAMED_SCOPE,)
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT not in answer.warnings


def test_a_supplied_as_of_outranks_the_request_moment(
    world: World, resolving: EntityResolutionService
) -> None:
    """When both moments are given, the one the caller asked *about* decides.

    `at` says when the question is being asked and `as_of` says when it is being
    asked about. A caller reconstructing what was true in 2027 must get the
    assignment that was live in 2027, not the one live at the moment they typed
    it — otherwise `as_of` is decorative for signals while it decides evidence.

    Untested until now: flipping the precedence left the whole suite green, so
    the ordering was correct and unpinned.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(
        PRINCIPAL,
        _assignment(
            "asn_aaaa0001aaaa0001",
            effective_from=datetime(2027, 1, 1, tzinfo=UTC),
            effective_to=datetime(2028, 1, 1, tzinfo=UTC),
        ),
    )
    request = ResolutionRequest(
        raw_reference="Alice Synthetic",
        scope_entity_id=TOWER,
        as_of=datetime(2027, 6, 1, tzinfo=UTC),
        at=NOW,
    )
    answer = resolving.resolve(PRINCIPAL, request)
    assert answer.outcome is ResolutionOutcome.RESOLVED_CONTEXTUAL
    assert answer.resolved_entity_id == ALICE
    # The mirror: at `at` alone the same assignment is over, so it cannot
    # corroborate and the shared name stays ambiguous.
    later = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER, at=NOW),
    )
    assert later.outcome is ResolutionOutcome.AMBIGUOUS


def test_a_cancelled_assignment_does_not_corroborate_at_the_earliest_moment(
    world: World, resolving: EntityResolutionService
) -> None:
    """The status exclusion must not depend on a date comparison at all.

    The first attempt encoded "over however you date it" as a sentinel window
    ending at `datetime.min`. `_is_effective` closes its end bound with
    `moment > effective_to`, which is false when the moment *is* `datetime.min`
    -- so at `as_of="0001-01-01T00:00:00Z"`, which the transport parses and
    accepts, a **cancelled** assignment read as in force, corroborated a bare
    canonical name, narrowed away the rival who shared it, and named an entity
    with no staleness warning at all.

    Liveness is a property of the record, so it is carried as one rather than
    encoded into dates a comparison can undo.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(PRINCIPAL, _assignment("asn_aaaa0001aaaa0001", status="cancelled"))
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="Alice Synthetic",
            scope_entity_id=TOWER,
            as_of=datetime.min.replace(tzinfo=UTC),
        ),
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.resolved_entity_id is None
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_assignment_ended_by_its_status_is_disclosed_not_silent(
    world: World, resolving: EntityResolutionService
) -> None:
    """Excluded by `status`, and the caller is told -- as for excluded by date.

    `active_only=True` dropped ended assignments in the query, so they never
    reached the fold and never set `withheld`: a row recorded as ended produced
    an `AMBIGUOUS` answer with no warning at all, while the same row left active
    and date-expired produced one. `RI-AC-014`'s duty does not care which column
    recorded that the evidence is not current.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(PRINCIPAL, an_entity(TOWER, "Alice Tower", entity_type=EntityType.PROJECT))
    entities.record_assignment(PRINCIPAL, _assignment("asn_aaaa0001aaaa0001", status="ended"))
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(raw_reference="Alice Synthetic", scope_entity_id=TOWER, at=NOW),
    )
    assert answer.outcome is ResolutionOutcome.AMBIGUOUS
    assert answer.candidates[0].signals == ()
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_an_identifier_whose_rows_are_all_expired_is_not_found(
    world: World, resolving: EntityResolutionService
) -> None:
    """The sibling branch of the fall-through above, and it was open.

    An identifier that matched rows which are *out of date* used to return
    `None`, which sent the same string to `_by_name` -- so an expired
    `source_participant_id` of "Smith, John" answered `RESOLVED_EXACT` naming a
    *different* person whose alias is "Smith John". `RI-I-003` puts stable
    external identifiers above lexical matching; discarding the identifier
    evidence to try the weaker one inverts that.

    The `entity_type` branch beside this one was fixed first and this one was
    left, which is why the rule is now stated once on the method: falling
    through means "not an identifier here, or matched nothing". Once a row
    matched, every exit is an answer.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "John Smith"))
    entities.create(PRINCIPAL, an_entity(ALICE_TWO, "Jonathan Smith"))
    entities.bind_identifier(
        PRINCIPAL,
        ALICE,
        an_email(
            "xid_aaaa0001aaaa0001",
            ALICE,
            "john.smith@example.test",
            verified=True,
            effective_to=datetime(2025, 1, 1, tzinfo=UTC),
        ),
    )
    entities.record_alias(
        PRINCIPAL, an_alias("eals_dddd0004dddd0004", ALICE_TWO, "john smith example test")
    )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="john.smith@example.test",
            namespace=ExternalIdentifierNamespace.EMAIL,
            as_of=datetime(2026, 8, 17, tzinfo=UTC),
        ),
    )
    assert answer.outcome is ResolutionOutcome.NOT_FOUND
    assert answer.resolved_entity_id is None
    assert ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT in answer.warnings


def test_a_conflicted_identifier_past_the_candidate_limit_still_answers(
    world: World, resolving: EntityResolutionService
) -> None:
    """The safety outcome must not fail when the data is most conflicted.

    `EntityResolution` refuses more candidates than `RESOLUTION_CANDIDATE_LIMIT`,
    and this path passed every claimant, so a shared mailbox bound to eleven
    entities raised `ValueError` and reached the caller as `internal_error` --
    the refusal failing in exactly the case it exists for. It is bounded on the
    same terms the name path is, and says that it is.
    """
    entities = _Entities(world)
    claimants = RESOLUTION_CANDIDATE_LIMIT + 1
    for index in range(claimants):
        entity_id = f"ent_{index:04d}shared{index:04d}"
        entities.create(PRINCIPAL, an_entity(entity_id, f"Team {index} Synthetic"))
        entities.bind_identifier(
            PRINCIPAL,
            entity_id,
            an_email(f"xid_{index:04d}shared{index:04d}", entity_id, "info@example.test"),
        )
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="info@example.test", namespace=ExternalIdentifierNamespace.EMAIL
        ),
    )
    assert answer.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER
    assert answer.resolved_entity_id is None
    assert len(answer.candidates) == RESOLUTION_CANDIDATE_LIMIT
    assert answer.candidates_were_truncated
    assert ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES in answer.warnings
    assert ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES in answer.warnings


def test_an_identifier_held_by_the_wrong_kind_of_entity_is_not_found(
    world: World, resolving: EntityResolutionService
) -> None:
    """A matched identifier must not be re-read as a name.

    Falling through here answered `RESOLVED_EXACT` naming a *project* whose alias
    happened to be spelled the way `normalize_name` spells that address, throwing
    away identifier evidence that pointed at a person in order to do it. The
    fall-through above it -- an identifier that matched nothing at all -- is
    still a fall-through, and the test beside this one holds it.
    """
    entities = _Entities(world)
    entities.create(PRINCIPAL, an_entity(ALICE, "Alice Synthetic"))
    entities.create(
        PRINCIPAL, an_entity(TOWER, "alice example test", entity_type=EntityType.PROJECT)
    )
    entities.bind_identifier(
        PRINCIPAL,
        ALICE,
        an_email("xid_aaaa0001aaaa0001", ALICE, "alice@example.test", verified=True),
    )
    entities.record_alias(PRINCIPAL, an_alias("eals_dddd0004dddd0004", TOWER, "alice example test"))
    answer = resolving.resolve(
        PRINCIPAL,
        ResolutionRequest(
            raw_reference="alice@example.test",
            namespace=ExternalIdentifierNamespace.EMAIL,
            entity_type=EntityType.PROJECT,
        ),
    )
    assert answer.outcome is ResolutionOutcome.NOT_FOUND
    assert answer.resolved_entity_id is None
