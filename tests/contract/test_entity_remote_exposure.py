"""Whether a remote client can reach the entity plane, and when.

**Why this file exists.** `adapters.mcp.remote.remote_tool_names` derives the
remote profile from `Capability` itself: every non-operator capability the
process has composed joins it, and there is no per-capability exclusion list to
leave one out. That is a reasonable design and a sharp edge — it means "this
build serves a capability" and "a remote client can reach it" are one decision,
made at composition, and a capability added without noticing joins the remote
surface silently.

The entity plane is the case where that matters most: these six read who a
person is. `tests/contract/test_remote_mcp_transport.py` checks the remote
profile by named membership, which cannot notice an *addition* — so nothing in
the suite would have failed if `entities.resolve` had appeared on the remote
surface before anything made it safe.

This file is that missing assertion, in both directions:

* a process that has not enabled the plane exposes none of the six, remotely or
  locally, however the write switch is set;
* a process that has enabled it exposes all six as **reads**, so they are
  reachable with `remote_writes_enabled` off — which is the correct
  classification, because none of them writes, and getting it wrong in the other
  direction would hide them behind a switch that has nothing to do with them.

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


def _service(*, enabled: bool) -> ApplicationService:
    """Two services whose only difference is the one switch.

    Both go through the shared builder, so "composed the same way except for
    this" is true by construction rather than by two hand-written compositions
    that might drift apart.
    """
    return build_service(World(), FakeProviders(), relationship_intelligence_enabled=enabled)


def test_the_six_names_are_the_family_this_file_is_about() -> None:
    """Guards the rest: an empty family would make every assertion below vacuous."""
    assert len(ENTITY_CAPABILITIES) == 6
    assert set(ENTITY_CAPABILITIES) == {
        "entities.context",
        "entities.get",
        "entities.relationships",
        "entities.resolve",
        "entities.search",
        "entities.unresolved_mentions",
    }


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
    """The gate withholds six names, not the process.

    Asserted because a gate that accidentally emptied the surface would satisfy
    every assertion above while breaking the build.
    """
    remote = remote_tool_names(_service(enabled=False), writes_enabled=False)
    assert len(remote) >= 20


def test_a_build_with_the_plane_exposes_all_six_as_reads() -> None:
    """Reachable with writes disabled, because none of the six writes."""
    remote = remote_tool_names(_service(enabled=True), writes_enabled=False)
    assert remote >= ENTITY_CAPABILITIES


def test_none_of_the_six_is_classified_as_a_write() -> None:
    """The classification the remote profile actually runs on.

    `remote_tool_names` decides read-versus-write by intersecting a capability's
    permitted purposes with `_WRITE_PURPOSES`. `entity_read` is not among them
    and must not become one: this plane has no write capability, so a write
    purpose here would be a grant nothing needs.
    """
    from my_pa.adapters.mcp.remote import _WRITE_PURPOSES

    for capability in Capability:
        if capability.value not in ENTITY_CAPABILITIES:
            continue
        assert permitted_purposes(capability) == frozenset({Purpose.ENTITY_READ})
        assert not permitted_purposes(capability) & _WRITE_PURPOSES


def test_none_of_the_five_is_operator_only() -> None:
    """Operator-only is about who may call one, not about whether this build has it.

    The two are different gates and the plane uses the second. Asserted so a
    future change cannot quietly swap them: making these operator-only would
    withhold them from the Principal whose own records they are.
    """
    for capability in Capability:
        if capability.value in ENTITY_CAPABILITIES:
            assert not is_operator_only(capability)
