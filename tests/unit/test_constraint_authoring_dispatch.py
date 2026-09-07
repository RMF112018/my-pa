"""Dispatch and composition for the authoring plane (PC-CM-IMP-WP07, T07-04).

Every authoring capability has a command, a `_HANDLERS` entry and a composed
handler, and **availability tracks composition rather than a constant**. The
distinction the last claim rests on is already in the taxonomy and is easy to
lose: a capability this build implements but this process was not composed for
answers `unsupported` — a fact about the build — and never `denied`, which is a
policy refusal about the request. A process that returned `denied` for an
unwired plane would be telling a caller their grant was wrong.

`bootstrap.gateway` hands the Constraint unit-of-work factory over under every
settings shape, so a real build always serves these twelve. What is asserted
here is the floor beneath that: the one composition input they need, absent.
"""

from __future__ import annotations

from typing import Final

import pytest

from my_pa.adapters.normalization import _BUILDERS
from my_pa.application.service import (
    _CONSTRAINT_AUTHORING_CAPABILITIES,
    _CONSTRAINT_CAPABILITIES,
    _HANDLERS,
    ApplicationService,
)
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from tests.conftest import Scene, build_service

AUTHORING: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CONSTRAINTS_CREATE,
        Capability.CONSTRAINTS_PUBLISH,
        Capability.CONSTRAINTS_UPDATE,
        Capability.CONSTRAINTS_TRANSITION,
        Capability.CONSTRAINTS_CLOSE,
        Capability.CONSTRAINTS_CLOSE_FOLLOW_UP,
        Capability.CONSTRAINTS_VOID,
        Capability.CONSTRAINTS_REOPEN,
        Capability.CONSTRAINT_CATEGORIES_CREATE,
        Capability.CONSTRAINT_CATEGORIES_UPDATE,
        Capability.CONSTRAINT_CATEGORIES_DEACTIVATE,
        Capability.CONSTRAINT_CATEGORIES_REORDER,
    }
)


def _uncomposed(scene: Scene) -> ApplicationService:
    """The same build, handed no Constraint unit-of-work factory."""
    return build_service(scene.world, scene.providers, constraint_management_unit_of_work=None)


# ---- the wiring --------------------------------------------------------------


def test_the_declared_authoring_set_is_the_twelve() -> None:
    assert _CONSTRAINT_AUTHORING_CAPABILITIES == AUTHORING


def test_the_authoring_set_and_the_read_set_are_disjoint() -> None:
    """Two sets rather than one, because they answer two different questions."""
    assert not (_CONSTRAINT_AUTHORING_CAPABILITIES & _CONSTRAINT_CAPABILITIES)


@pytest.mark.parametrize("capability", sorted(AUTHORING, key=lambda c: c.value), ids=str)
def test_every_authoring_capability_has_a_command_and_a_handler(capability: Capability) -> None:
    assert capability in _BUILDERS, "no transport can build this capability's command"
    assert capability in _HANDLERS, "this build implements no handler for it"


@pytest.mark.parametrize("capability", sorted(AUTHORING, key=lambda c: c.value), ids=str)
def test_a_composed_process_serves_every_authoring_capability(
    capability: Capability, scene: Scene
) -> None:
    service = build_service(scene.world, scene.providers)
    assert capability in service.available_capabilities


# ---- availability follows composition ---------------------------------------


def test_an_uncomposed_process_withholds_the_whole_constraint_plane(scene: Scene) -> None:
    served = _uncomposed(scene).available_capabilities
    assert not (served & AUTHORING)
    assert not (served & _CONSTRAINT_CAPABILITIES)


def test_a_composed_process_serves_both_halves(scene: Scene) -> None:
    served = build_service(scene.world, scene.providers).available_capabilities
    assert served >= AUTHORING
    assert served >= _CONSTRAINT_CAPABILITIES


@pytest.mark.parametrize("capability", sorted(AUTHORING, key=lambda c: c.value), ids=str)
def test_an_uncomposed_process_answers_unsupported_and_never_denied(
    capability: Capability, scene: Scene
) -> None:
    """`UNSUPPORTED` is "this build does not compose it"; `DENIED` is a policy refusal.

    The request carries the purpose the capability *does* permit and a Principal
    that holds it, so a `denied` here could only mean the two taxonomies had been
    conflated.
    """
    purpose = next(iter(permitted_purposes(capability)))
    assert purpose is Purpose.CONSTRAINT_AUTHORING
    metadata, command = _request(capability, scene)
    envelope = _uncomposed(scene).invoke(metadata, command, principal=scene.principal)
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.UNSUPPORTED


def _request(capability: Capability, scene: Scene) -> tuple[RequestMetadata, object]:
    from my_pa.adapters.normalization import normalize
    from tests.conftest import staged_record
    from tests.contract.test_transport_parity import document, payloads_for

    record = staged_record(scene, text="a synthetic record")
    payload = payloads_for(scene, record)[capability]
    return normalize(capability.value, document(capability, scene.principal.principal_id, payload))
