"""Frozen Relationship Intelligence profiles are bounded and dormant."""

from typing import Final

from my_pa.bootstrap.relationship_intelligence_profiles import (
    RELATIONSHIP_GRANT_PROFILES,
    RELATIONSHIP_ROLE_PROFILES,
)
from my_pa.domain.identity.operation import Capability

#: The capability families a Relationship Intelligence profile is answerable
#: for. A profile is a ceiling over the relationship plane, so every capability
#: whose name begins with one of these is either granted by some profile or
#: withheld from all of them on purpose. `tasks.`, `knowledge.` and the rest are
#: other planes' business and are deliberately out of scope here.
GOVERNED_FAMILIES: Final = ("entities", "relationship_memory", "review")

#: Governed capabilities that **no** profile grants, and that is a decision
#: rather than an omission.
#:
#: `RI-ENT-WP-10` and `RI-ENT-WP-11` added the 20 names below and wired them
#: through authorization, but widening a grant profile to admit them is grant
#: mutation, which `AUTH-RI-ENT-20260830-OPERATOR-001` excludes from this
#: campaign in terms and AGENTS.md 8.2 reserves to the operator. So the
#: contracts ship and the dormant ceilings stay closed: the capabilities are
#: reachable through the authorization path, and no profile grants them until an
#: operator deliberately says so. Fail-closed is the right default for a surface
#: whose SQL page bodies have never run against a server (`RULING-M12`).
#:
#: **This list is the point of the test below, not bookkeeping beside it.** The
#: ceiling constants in the module under test and their restatement above can
#: agree with each other forever while a capability exists that neither has
#: heard of; that is exactly what happened here, and nothing went red. Naming
#: the withheld set makes the omission a written decision that a reader can
#: disagree with, and makes the *next* unaccounted capability fail rather than
#: disappear.
WITHHELD_FROM_EVERY_PROFILE: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_PROFILE,
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_LIST,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_LIST,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_LIST,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_AFFILIATIONS_CREATE,
        Capability.ENTITIES_AFFILIATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
    }
)


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
            Capability.ENTITIES_GRAPH,
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
        Capability.ENTITIES_GRAPH,
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


def test_every_governed_capability_is_granted_or_deliberately_withheld() -> None:
    """The ceilings, against `Capability` itself rather than against a copy.

    **The test above this one cannot fail for the reason this one exists.** It
    restates the module's ceiling constants by hand, which is deliberate and
    stays: a test that imported `_ENTITY_READS` would read `x == x` and pass
    however that constant changed, so the restatement is what catches an edit to
    the ceilings. What it cannot catch is the opposite direction -- a capability
    that exists and that *no* profile has an opinion about -- because nothing in
    either the module or its restatement mentions a name neither has heard of.

    That gap was real and it was occupied: `RI-ENT-WP-10` and `RI-ENT-WP-11`
    added 20 governed capabilities, no ceiling moved, and every test in this
    module stayed green. A guard that cannot fail is not a guard; it is
    decoration standing where one would go, and it made the gap invisible
    instead of leaving it merely open.

    So this reads the enum and partitions it. Every governed capability is
    granted by some profile or named in `WITHHELD_FROM_EVERY_PROFILE`, never
    both and never neither. Adding a capability under a governed family without
    deciding about it reddens here, and the decision -- either way -- has to be
    written down before this passes again.
    """
    governed = {
        capability
        for capability in Capability
        if capability.value.split(".", 1)[0] in GOVERNED_FAMILIES
    }
    granted = {
        capability
        for profile in RELATIONSHIP_GRANT_PROFILES.values()
        for capability in profile.capabilities
    }

    assert not (granted & WITHHELD_FROM_EVERY_PROFILE), (
        "a capability is both granted by a profile and recorded as withheld from "
        f"every profile: {sorted(c.value for c in granted & WITHHELD_FROM_EVERY_PROFILE)}. "
        "One of the two statements is wrong; the profile module is the fact."
    )
    assert granted | WITHHELD_FROM_EVERY_PROFILE == governed, (
        "every capability in a governed family must be granted by some profile or "
        "named in WITHHELD_FROM_EVERY_PROFILE, and these are neither: "
        f"{sorted(c.value for c in governed - granted - WITHHELD_FROM_EVERY_PROFILE)}"
        "; and these are claimed but are not governed capabilities at all: "
        f"{sorted(c.value for c in (granted | WITHHELD_FROM_EVERY_PROFILE) - governed)}. "
        "Decide: widen a ceiling (operator-reserved, AGENTS.md 8.2) or record the "
        "capability as deliberately withheld, with the reason."
    )


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
