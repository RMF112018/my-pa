"""Whether a remote client can reach the entity plane, and when.

**Why this file exists.** `adapters.mcp.remote.remote_tool_names` derives the
remote profile from `Capability` itself: every non-operator capability the
process has composed joins it, and there is no per-capability exclusion list to
leave one out. That is a reasonable design and a sharp edge — it means "this
build serves a capability" and "a remote client can reach it" are one decision,
made at composition, and a capability added without noticing joins the remote
surface silently.

The entity plane is the case where that matters most: its reads return who a
person is, and since `WP-RI-A-02` its writes *decide* who a person is.
`tests/contract/test_remote_mcp_transport.py` checks the remote profile by named
membership, which cannot notice an *addition* — so nothing in the suite would
have failed if `entities.resolve` had appeared on the remote surface before
anything made it safe.

This file is that missing assertion, in three directions:

* a process that has not enabled the plane exposes none of the family, remotely
  or locally, however the write switch is set;
* a process that has enabled it exposes every `entities.` read as a **read**, so
  each is reachable with `remote_writes_enabled` off — which is the correct
  classification, because none of them writes, and getting it wrong in the other
  direction would hide them behind a switch that has nothing to do with them;
* and it exposes every `entities.` write only with `remote_writes_enabled` on.
  That half arrived with the writes and is the one this file would otherwise
  have been silent about: the profile derives read-versus-write from the
  purposes a capability permits, so a write mapped to a read purpose would reach
  a remote client that was never granted one.

`tests/contract/test_mcp_transport.py` proves the same withholding against a
real child process. This proves it about the remote profile specifically, which
that test does not reach.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.conftest import FakeProviders, World, build_service

from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.mcp.server import published_tools
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.purpose import Purpose

ENTITY_CAPABILITIES: Final[frozenset[str]] = frozenset(
    capability.value for capability in Capability if capability.value.startswith("entities.")
)

#: The plane's two halves, derived from the purpose each capability permits
#: rather than listed. Derived, because that is the same decision
#: `remote_tool_names` makes: a write mis-mapped to the read purpose would move
#: between these two sets and the assertions below would follow it, which is
#: exactly the change this file must not absorb quietly.
ENTITY_READS: Final[frozenset[str]] = frozenset(
    capability.value
    for capability in Capability
    if capability.value in ENTITY_CAPABILITIES
    and permitted_purposes(capability) == frozenset({Purpose.ENTITY_READ})
)
ENTITY_WRITES: Final[frozenset[str]] = ENTITY_CAPABILITIES - ENTITY_READS


#: The two names that are *also* operator-only, and so never join a remote
#: profile at all. `remote_tool_names` drops an operator-only capability before it
#: classifies read from write, so every assertion below about the remote surface
#: has to subtract them: they are withheld by a gate that is not the one this file
#: is about, and asserting they appear when writes are enabled would be asserting
#: the operator boundary away.
OPERATOR_ONLY_WRITES: Final[frozenset[str]] = frozenset(
    {"entities.merge.preview", "entities.merge"}
)

#: The write half a remote client can ever reach, which is the write half less
#: the two above.
REMOTE_REACHABLE_WRITES: Final[frozenset[str]] = ENTITY_WRITES - OPERATOR_ONLY_WRITES


def _service(*, enabled: bool) -> ApplicationService:
    """Two services whose only difference is the one switch.

    Both go through the shared builder, so "composed the same way except for
    this" is true by construction rather than by two hand-written compositions
    that might drift apart.
    """
    return build_service(World(), FakeProviders(), relationship_intelligence_enabled=enabled)


def test_the_names_this_file_is_about_are_the_family() -> None:
    """Guards the rest: an empty family would make every assertion below vacuous.

    Both halves are named exactly, so a capability that moves between them —
    which is what a purpose mis-mapping looks like from here — reddens rather
    than sliding from one assertion to the other.
    """
    assert set(ENTITY_READS) == {
        "entities.aliases.list",
        "entities.assignments.list",
        "entities.context",
        "entities.get",
        "entities.identifiers.list",
        "entities.observations.list",
        "entities.relationships",
        "entities.resolve",
        "entities.search",
        "entities.unresolved_mentions",
    }
    assert set(ENTITY_WRITES) == {
        "entities.aliases.add",
        "entities.aliases.retire",
        "entities.aliases.supersede",
        "entities.archive",
        "entities.assignments.create",
        "entities.assignments.end",
        "entities.assignments.revise",
        "entities.create",
        "entities.identifiers.bind",
        "entities.identifiers.retire",
        "entities.identifiers.supersede",
        "entities.observe",
        "entities.relationships.create",
        "entities.relationships.end",
        "entities.relationships.revise",
        "entities.restore",
        "entities.unresolved_mentions.resolve",
        "entities.update",
        # Phase B's three. A proposal writes a request, a preview writes a
        # durable control row, and a merge rewrites canonical rows -- so all
        # three carry a write purpose and land in this half.
        "entities.proposals.create",
        "entities.merge.preview",
        "entities.merge",
    }
    assert ENTITY_READS | ENTITY_WRITES == ENTITY_CAPABILITIES


def test_the_write_half_is_the_half_with_a_write_purpose() -> None:
    """The split this file asserts against is derived, not asserted twice.

    `ENTITY_WRITES` is this module's own subtraction, which is the shape this
    suite keeps catching: a set that drifts from the thing it names. So it is
    checked against the only definition that decides anything -- whether a
    capability's permitted purposes intersect `_WRITE_PURPOSES`, which is what
    `remote_tool_names` itself runs on.
    """
    from my_pa.adapters.mcp.remote import _WRITE_PURPOSES

    derived = {
        capability.value
        for capability in Capability
        if capability.value in ENTITY_CAPABILITIES
        and permitted_purposes(capability) & _WRITE_PURPOSES
    }
    assert derived == ENTITY_WRITES


@pytest.mark.parametrize("writes_enabled", [False, True])
def test_a_build_without_the_plane_exposes_none_of_it_remotely(writes_enabled: bool) -> None:
    """Both write settings, because the gate must not depend on the write switch."""
    remote = remote_tool_names(_service(enabled=False), writes_enabled=writes_enabled)
    assert remote & ENTITY_CAPABILITIES == frozenset()


def test_a_build_without_the_plane_publishes_none_of_it_locally_either() -> None:
    """The local tool list and the remote profile agree about what does not exist."""
    local = {tool.name for tool in published_tools(_service(enabled=False))}
    assert local & ENTITY_CAPABILITIES == frozenset()


def test_a_build_without_the_plane_still_serves_everything_else() -> None:
    """The gate withholds the `entities.` family, not the process.

    Asserted because a gate that accidentally emptied the surface would satisfy
    every assertion above while breaking the build.
    """
    remote = remote_tool_names(_service(enabled=False), writes_enabled=False)
    assert len(remote) >= 20


def test_a_build_with_the_plane_exposes_every_read_as_a_read() -> None:
    """Reachable with writes disabled, because none of these writes."""
    remote = remote_tool_names(_service(enabled=True), writes_enabled=False)
    assert remote >= ENTITY_READS


def test_a_build_with_the_plane_withholds_every_write_until_writes_are_enabled() -> None:
    """The half `WP-RI-A-02` added, and the one this file existed to be ready for.

    A remote client with `remote_writes_enabled` off can read who a person is
    and cannot decide it. The gate is the purpose mapping rather than a name
    list, so this fails the moment one of the ten is mapped to `entity_read`.
    """
    withheld = remote_tool_names(_service(enabled=True), writes_enabled=False)
    assert withheld & ENTITY_WRITES == frozenset()
    granted = remote_tool_names(_service(enabled=True), writes_enabled=True)
    assert granted >= REMOTE_REACHABLE_WRITES
    # And the two operator-only writes are still absent with writes enabled,
    # which is the second gate rather than this one.
    assert not granted & OPERATOR_ONLY_WRITES


def test_the_read_half_is_classified_as_a_read_and_the_write_half_as_a_write() -> None:
    """The classification the remote profile actually runs on.

    `remote_tool_names` decides read-versus-write by intersecting a capability's
    permitted purposes with `_WRITE_PURPOSES`. `entity_read` is not among them
    and must not become one; `entity_authoring` is, and must stay so.
    """
    from my_pa.adapters.mcp.remote import _WRITE_PURPOSES

    for capability in Capability:
        if capability.value in ENTITY_READS:
            assert permitted_purposes(capability) == frozenset({Purpose.ENTITY_READ})
            assert not permitted_purposes(capability) & _WRITE_PURPOSES
        elif capability.value in ENTITY_WRITES:
            assert not permitted_purposes(capability) & {Purpose.ENTITY_READ}
            assert permitted_purposes(capability) & _WRITE_PURPOSES


def test_the_three_purposes_do_not_overlap() -> None:
    """Three grants, three reaches, and no overlap.

    A grant issued so an ingest path can record what a mailbox said must not
    also decide who somebody is, and neither must let anything read the plane.
    Stated as a disjointness rather than as three memberships, because the
    failure this prevents is an *overlap* somebody adds later.
    """
    read = permitted_purposes(Capability.ENTITIES_SEARCH)
    ingest = permitted_purposes(Capability.ENTITIES_OBSERVE)
    authoring = permitted_purposes(Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE)
    assert read == frozenset({Purpose.ENTITY_READ})
    assert ingest == frozenset({Purpose.ENTITY_OBSERVATION_INGEST})
    assert authoring == frozenset({Purpose.ENTITY_AUTHORING})
    assert not read & ingest
    assert not read & authoring
    assert not ingest & authoring


def test_only_the_governed_merge_is_operator_only_on_this_family() -> None:
    """Operator-only is about who may call one, not about whether this build has it.

    The two are different gates and most of this plane uses only the second.
    **This test used to say none of the family was operator-only**, and that was
    true of every name until `WP-RI-B-06`. It is corrected rather than deleted,
    because the reasoning it carried is still the reasoning that keeps the other
    twenty-nine out: making an ordinary entity read or write operator-only would
    withhold it from the Principal whose own records they are, and none of them
    widens the scope a later request is evaluated against.

    The governed merge does widen it -- afterwards every child of a merged-away
    entity is reached through the survivor -- which is the test `_OPERATOR_ONLY`
    applies, and operator section 24 states the conclusion independently.
    """
    for capability in Capability:
        if capability.value in ENTITY_CAPABILITIES:
            assert is_operator_only(capability) == (
                capability.value in OPERATOR_ONLY_WRITES
            )
