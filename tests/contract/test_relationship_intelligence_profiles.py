"""Frozen Relationship Intelligence profiles are bounded and dormant."""

from my_pa.bootstrap.relationship_intelligence_profiles import (
    RELATIONSHIP_GRANT_PROFILES,
    RELATIONSHIP_ROLE_PROFILES,
)
from my_pa.domain.identity.operation import Capability


def test_named_local_and_remote_profiles_are_frozen_and_exact() -> None:
    assert set(RELATIONSHIP_GRANT_PROFILES) == {
        f"{transport}.{role}"
        for transport in ("local", "remote")
        for role in ("standard", "producer", "reviewer", "operator")
    }


def test_each_role_has_exactly_its_governed_capability_ceiling() -> None:
    entity_reads = frozenset(
        {
            Capability.ENTITIES_SEARCH,
            Capability.ENTITIES_GET,
            Capability.ENTITIES_RESOLVE,
            Capability.ENTITIES_CONTEXT,
            Capability.ENTITIES_IDENTIFIERS_LIST,
            Capability.ENTITIES_ALIASES_LIST,
            Capability.ENTITIES_ASSIGNMENTS_LIST,
            Capability.ENTITIES_RELATIONSHIPS,
            Capability.ENTITIES_OBSERVATIONS_LIST,
            Capability.ENTITIES_UNRESOLVED_MENTIONS,
            Capability.ENTITIES_IDENTITY_HISTORY,
        }
    )
    routine_entity_authoring = frozenset(
        {
            Capability.ENTITIES_CREATE,
            Capability.ENTITIES_UPDATE,
            Capability.ENTITIES_ARCHIVE,
            Capability.ENTITIES_RESTORE,
            Capability.ENTITIES_IDENTIFIERS_BIND,
            Capability.ENTITIES_IDENTIFIERS_RETIRE,
            Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
            Capability.ENTITIES_ALIASES_ADD,
            Capability.ENTITIES_ALIASES_RETIRE,
            Capability.ENTITIES_ALIASES_SUPERSEDE,
            Capability.ENTITIES_ASSIGNMENTS_CREATE,
            Capability.ENTITIES_ASSIGNMENTS_REVISE,
            Capability.ENTITIES_ASSIGNMENTS_END,
            Capability.ENTITIES_RELATIONSHIPS_CREATE,
            Capability.ENTITIES_RELATIONSHIPS_REVISE,
            Capability.ENTITIES_RELATIONSHIPS_END,
            Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        }
    )
    relationship_memory = frozenset(
        {
            Capability.RELATIONSHIP_MEMORY_CREATE,
            Capability.RELATIONSHIP_MEMORY_LIST,
            Capability.RELATIONSHIP_MEMORY_GET,
            Capability.RELATIONSHIP_MEMORY_SEARCH,
            Capability.RELATIONSHIP_MEMORY_HISTORY,
            Capability.RELATIONSHIP_MEMORY_REVISE,
            Capability.RELATIONSHIP_MEMORY_ARCHIVE,
            Capability.RELATIONSHIP_MEMORY_RESTORE,
            Capability.RELATIONSHIP_MEMORY_PROPOSE,
        }
    )
    standard = (
        entity_reads
        | routine_entity_authoring
        | relationship_memory
        | {Capability.ENTITIES_PROPOSALS_CREATE, Capability.REVIEW_LIST}
    )
    producer = {
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.REVIEW_LIST,
    }
    expected = {
        "standard": standard,
        "producer": producer,
        "reviewer": standard | {Capability.REVIEW_DECIDE},
        "operator": standard
        | {
            Capability.REVIEW_DECIDE,
            Capability.ENTITIES_MERGE_PREVIEW,
            Capability.ENTITIES_MERGE,
            Capability.ENTITIES_SPLIT_PREVIEW,
            Capability.ENTITIES_SPLIT,
        },
    }
    for profile in RELATIONSHIP_GRANT_PROFILES.values():
        assert profile.capabilities == expected[profile.name]


def test_standard_and_producer_profiles_can_raise_proposals() -> None:
    proposal_writes = {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
    }
    for profile in RELATIONSHIP_GRANT_PROFILES.values():
        assert proposal_writes <= profile.capabilities


def test_authority_separation_is_load_bearing_in_each_profile() -> None:
    for key, profile in RELATIONSHIP_GRANT_PROFILES.items():
        if key.endswith(".producer"):
            assert Capability.ENTITIES_OBSERVE in profile.capabilities
            assert Capability.REVIEW_LIST in profile.capabilities
            assert Capability.ENTITIES_CREATE not in profile.capabilities
            assert Capability.RELATIONSHIP_MEMORY_CREATE not in profile.capabilities
        else:
            assert Capability.ENTITIES_OBSERVE not in profile.capabilities

        assert (Capability.REVIEW_DECIDE in profile.capabilities) == key.endswith(
            (".reviewer", ".operator")
        )


def test_only_operator_profiles_can_reach_identity_mutation() -> None:
    identity = {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
    for key, profile in RELATIONSHIP_GRANT_PROFILES.items():
        if key.endswith(".operator"):
            assert identity <= profile.capabilities
            assert not profile.denied
        else:
            assert not identity & profile.capabilities
            assert identity <= profile.denied


def test_canonical_role_names_are_transport_independent_and_compatible() -> None:
    assert set(RELATIONSHIP_ROLE_PROFILES) == {
        "relationship_standard",
        "relationship_producer",
        "relationship_reviewer",
        "relationship_operator",
    }
    for role in ("standard", "producer", "reviewer", "operator"):
        assert RELATIONSHIP_ROLE_PROFILES[f"relationship_{role}"] == (
            RELATIONSHIP_GRANT_PROFILES[f"local.{role}"].capabilities
        )
        assert RELATIONSHIP_GRANT_PROFILES[f"local.{role}"].capabilities == (
            RELATIONSHIP_GRANT_PROFILES[f"remote.{role}"].capabilities
        )
