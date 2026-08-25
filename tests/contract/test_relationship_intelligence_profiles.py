"""Frozen Relationship Intelligence profiles are bounded and dormant."""

from my_pa.bootstrap.relationship_intelligence_profiles import RELATIONSHIP_GRANT_PROFILES
from my_pa.domain.identity.operation import Capability


def test_named_local_and_remote_profiles_are_frozen_and_exact() -> None:
    assert set(RELATIONSHIP_GRANT_PROFILES) == {
        f"{transport}.{role}"
        for transport in ("local", "remote")
        for role in ("standard", "producer", "reviewer", "operator")
    }


def test_only_producer_profiles_can_raise_proposals() -> None:
    proposal_writes = {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
    }
    for key, profile in RELATIONSHIP_GRANT_PROFILES.items():
        assert proposal_writes <= profile.capabilities if key.endswith(".producer") else not (
            proposal_writes & profile.capabilities
        )


def test_only_operator_profiles_can_reach_identity_mutation() -> None:
    identity = {Capability.ENTITIES_MERGE_PREVIEW, Capability.ENTITIES_MERGE}
    for key, profile in RELATIONSHIP_GRANT_PROFILES.items():
        if key.endswith(".operator"):
            assert identity <= profile.capabilities
            assert not profile.denied
        else:
            assert not identity & profile.capabilities
            assert identity <= profile.denied
