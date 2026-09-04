"""`MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` off, on every transport.

The entity plane has two switches. `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED`
decides whether the plane exists at all, and
`MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` decides whether its thirty-eight
writes do. This file is about the second one, and it exists for the reason
`_entity_plane`'s own docstring gives about the first: **a capability set is not
a gate.**

`ApplicationService.available_capabilities` subtracts the withheld names, and
two things read it — `capabilities.get` and the MCP tool list. The HTTP
transport reads neither. `/v1/{capability}` is a path parameter, so dispatch
reaches `_HANDLERS` directly and executes whatever it finds there. That is
exactly how the entity plane came to answer with entity rows on a build that
reported it as `not_implemented`, and it is why the write switch is enforced in
two places rather than one: subtracted from the published set, *and* asked again
by every write handler through `_entity_writes`.

So the claim here is deliberately stated as **"cannot be called by its known
tool name"** rather than "is not published". A surface that is merely unlisted
is still reachable by a caller that already knows the name, and every one of
these names is in a public enum.

**Three states, and all three are asserted**, because a gate that refused in
every state would satisfy a one-sided test:

* plane off — all fifty-five `entities.` names refuse, reads included;
* plane on, writes off — the seventeen reads answer and the thirty-eight writes refuse;
* plane on, writes on — all fifty-four are served.

Every one of those four figures is derived from a live set rather than written
down twice, and every one of them has been wrong here at some point: `sixteen`
and `thirty-eight` are `_ENTITY_CAPABILITIES` split by the purpose map, and the
other two are the whole plane. `RI-ENT-WP-10` moved the read half from eleven to
sixteen without moving the write half, which is what a work package that adds
only reads should do -- and `thirty-one`, `twenty-one` and the ordinal below had
been stale since before it, because the sweep that reads these words checks a
count against `Capability` and not against a *subset* one clause of a sentence
names while its neighbour names another.

The write population is derived from the purpose map rather than listed here, so
a thirty-ninth write mapped to `entity_authoring` joins this sweep on arrival. It
is then compared against `_ENTITY_WRITE_CAPABILITIES`, which is the set the
service actually subtracts, so the two statements of the same fact cannot drift.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.conftest import FakeProviders, Scene, World, build_service, metadata_for

from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.mcp.server import published_tools
from my_pa.application.producer_origin import ProducerOrigin, ProducerOriginRegistry
from my_pa.application.service import (
    _ENTITY_CAPABILITIES,
    _ENTITY_WRITE_CAPABILITIES,
    ApplicationService,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import PrincipalKind
from my_pa.domain.identity.purpose import Purpose

#: The purposes that mean "this capability changes something", read off the
#: transport that already decides read-versus-write with them.
WRITE_PURPOSES: Final[frozenset[Purpose]] = frozenset(
    {
        Purpose.ENTITY_AUTHORING,
        Purpose.ENTITY_OBSERVATION_INGEST,
        # `WP-RI-B-05` and `WP-RI-B-06`. A proposal writes a request rather than
        # a canonical fact and a preview writes a control row rather than either,
        # and both are still writes -- so both purposes belong here, and a
        # read-only build withholds every capability that carries them.
        Purpose.ENTITY_PROPOSAL,
        Purpose.ENTITY_IDENTITY_CORRECTION,
    }
)


def _is_entity_write(capability: Capability) -> bool:
    if not capability.value.startswith("entities."):
        return False
    return bool(permitted_purposes(capability) & WRITE_PURPOSES)


ENTITY_WRITES: Final[frozenset[Capability]] = frozenset(
    capability for capability in Capability if _is_entity_write(capability)
)

ENTITY_READS: Final[frozenset[Capability]] = _ENTITY_CAPABILITIES - ENTITY_WRITES


def _service(*, plane: bool, writes: bool, identity: bool = True) -> ApplicationService:
    """One build per state, through the shared builder so only the flags differ.

    `identity` defaults to *on* so that the four governed identity-correction names are inside
    every assertion below rather than withheld by a third gate this file is not
    about. `test_the_identity_correction_gate_is_a_third_narrowing` is where that
    gate is the subject.
    """
    return build_service(
        World(),
        FakeProviders(),
        relationship_intelligence_enabled=plane,
        relationship_intelligence_writes_enabled=writes,
        relationship_identity_correction_enabled=identity,
        producer_origins=ProducerOriginRegistry(
            {
                "prn_entity_write_gate": ProducerOrigin(
                    principal_id="prn_entity_write_gate",
                    principal_kind=PrincipalKind.OPERATOR,
                    method="rule",
                    method_version="entity-write-gate.1",
                )
            }
        ),
    )


def test_the_write_set_the_service_subtracts_is_the_set_with_a_write_purpose() -> None:
    """Two statements of one fact, compared rather than trusted.

    `_ENTITY_WRITE_CAPABILITIES` is written out in `application.service` so that
    admitting a write is a decision made there. This is the derivation that
    keeps the decision honest: a name added to the purpose map as a write and
    forgotten in that set would be published by a read-only build, and reddens
    here instead.
    """
    assert ENTITY_WRITES == _ENTITY_WRITE_CAPABILITIES
    # Thirty-eight after `RI-ENT-WP-11`'s five record families: the
    # twenty-three that final identity recovery left plus three verbs per family.
    assert len(ENTITY_WRITES) == 38
    assert ENTITY_WRITES < _ENTITY_CAPABILITIES
    assert not ENTITY_READS & ENTITY_WRITES


def test_a_read_only_build_publishes_the_reads_and_withholds_the_writes() -> None:
    """`capabilities.get` and the MCP tool list read the same answer."""
    served = _service(plane=True, writes=False).available_capabilities
    assert served >= ENTITY_READS
    assert not served & ENTITY_WRITES


def test_a_read_only_build_withholds_the_writes_from_the_local_tool_list() -> None:
    """The published names, over the transport a client actually reads."""
    names = {tool.name for tool in published_tools(_service(plane=True, writes=False))}
    assert {capability.value for capability in ENTITY_READS} <= names
    assert not names & {capability.value for capability in ENTITY_WRITES}


@pytest.mark.parametrize("remote_writes", [False, True])
def test_a_read_only_build_withholds_the_writes_from_the_remote_profile(
    remote_writes: bool,
) -> None:
    """Both settings of the remote switch, because this gate is not that gate.

    `MY_PA_REMOTE_WRITES_ENABLED` withholds a write from a *remote* client on a
    build that still serves it locally. This one withholds it from the build. A
    remote profile that published an entity write because remote writes were on
    would be reading the wrong switch, and the parametrisation is what catches
    it in the direction that matters.
    """
    remote = remote_tool_names(_service(plane=True, writes=False), writes_enabled=remote_writes)
    assert not remote & {capability.value for capability in ENTITY_WRITES}


def test_a_fully_composed_build_serves_the_whole_plane() -> None:
    """The non-vacuity control: the assertions above are about a switch.

    Without this, a gate that withheld the writes unconditionally — or a
    `_ENTITY_WRITE_CAPABILITIES` that had grown to cover the reads — would
    satisfy every test above and break the plane.
    """
    served = _service(plane=True, writes=True).available_capabilities
    assert served >= _ENTITY_CAPABILITIES
    names = {tool.name for tool in published_tools(_service(plane=True, writes=True))}
    assert {capability.value for capability in _ENTITY_CAPABILITIES} <= names


def test_the_identity_correction_gate_is_a_third_narrowing_of_the_same_plane() -> None:
    """`MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED`, on its own axis.

    The plane switch withholds the whole `entities.` family; the write switch
    withholds its write half; this one withholds governed merge and split out of
    that half. Asserted
    as a strict subset relation rather than as three memberships, because the
    failure this prevents is a gate that turned into the gate beside it -- a
    build with writes on and identity correction off must serve every other
    write, and a build with identity correction off must serve no merge or split
    capability whatever the other two switches say.
    """
    from my_pa.application.service import _IDENTITY_CORRECTION_CAPABILITIES

    assert _IDENTITY_CORRECTION_CAPABILITIES < _ENTITY_WRITE_CAPABILITIES
    without = _service(plane=True, writes=True, identity=False).available_capabilities
    assert not without & _IDENTITY_CORRECTION_CAPABILITIES
    assert without >= _ENTITY_WRITE_CAPABILITIES - _IDENTITY_CORRECTION_CAPABILITIES
    names = {
        tool.name for tool in published_tools(_service(plane=True, writes=True, identity=False))
    }
    assert not names & {capability.value for capability in _IDENTITY_CORRECTION_CAPABILITIES}
    for plane, writes in ((False, False), (True, False)):
        served = _service(plane=plane, writes=writes, identity=True).available_capabilities
        assert not served & _IDENTITY_CORRECTION_CAPABILITIES


def test_a_build_without_the_plane_withholds_the_reads_too() -> None:
    """The other state, so "withheld" is not read as "withheld by this switch"."""
    served = _service(plane=False, writes=False).available_capabilities
    assert not served & _ENTITY_CAPABILITIES
    # And the contradictory composition cannot arise from configuration:
    # `bootstrap.settings` refuses to start a process that sets the write switch
    # without the plane. Constructed directly here, the write switch narrows an
    # absent plane rather than reviving it, which is the fail-closed direction.
    contradictory = _service(plane=False, writes=True).available_capabilities
    assert not contradictory & _ENTITY_CAPABILITIES


@pytest.mark.parametrize(
    "capability", sorted(ENTITY_WRITES, key=lambda item: item.value), ids=lambda item: item.value
)
def test_every_withheld_write_refuses_when_called_by_its_known_name(
    scene: Scene, capability: Capability
) -> None:
    """The claim this file is named for, made against the execution floor.

    Driven through `ApplicationService.invoke`, which is the method the HTTP
    transport reaches after routing by path segment — so this is the path that
    bypasses `available_capabilities` entirely. A handler that answered here
    would answer over HTTP on a build whose manifest says the capability is not
    implemented.

    The command is the one `tests/contract/test_entity_capabilities.py` stages
    for the plane's own off-switch sweep, so the request is well formed and the
    refusal is the gate rather than a malformed payload. The purpose is derived
    from the capability: sending `entity_read` for a write would meet `denied`
    before the gate and read as a pass.
    """
    from tests.contract.test_entity_capabilities import _OFF_SWITCH_COMMANDS

    command = _OFF_SWITCH_COMMANDS[capability]
    service = build_service(
        scene.world,
        scene.providers,
        relationship_intelligence_enabled=True,
        relationship_intelligence_writes_enabled=False,
    )
    envelope = service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    document = envelope.to_canonical_dict()
    assert document["result"] is None
    error = document["error"]
    assert isinstance(error, dict)
    assert error["code"] == ErrorCode.UNSUPPORTED.value


@pytest.mark.parametrize(
    "capability", sorted(ENTITY_READS, key=lambda item: item.value), ids=lambda item: item.value
)
def test_every_read_still_answers_on_a_read_only_build(
    scene: Scene, capability: Capability
) -> None:
    """The control for the sweep above: the switch narrows, it does not close.

    A read that answered `unsupported` here would mean the write gate had been
    applied to the wrong population, which is the failure a one-sided sweep
    cannot see.
    """
    from tests.contract.test_entity_capabilities import _OFF_SWITCH_COMMANDS

    command = _OFF_SWITCH_COMMANDS[capability]
    service = build_service(
        scene.world,
        scene.providers,
        relationship_intelligence_enabled=True,
        relationship_intelligence_writes_enabled=False,
    )
    envelope = service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        command,  # type: ignore[arg-type]
        principal=scene.principal,
    )
    document = envelope.to_canonical_dict()
    error = document["error"]
    if error is not None:
        assert isinstance(error, dict)
        assert error["code"] != ErrorCode.UNSUPPORTED.value
