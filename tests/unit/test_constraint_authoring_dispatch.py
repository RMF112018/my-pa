"""Dispatch and composition for the authoring plane (PC-CM-IMP-WP07, T07-04).

Every authoring capability has a command, a `_HANDLERS` entry and a composed
handler, and **availability tracks composition rather than a constant**. The
distinction the last claim rests on is already in the taxonomy and is easy to
lose: a capability this build implements but this process was not composed for
answers `unsupported` — a fact about the build — and never `denied`, which is a
policy refusal about the request. A process that returned `denied` for an
unwired plane would be telling a caller their grant was wrong.

`bootstrap.gateway` hands the Constraint unit-of-work factory over under every
settings shape, so a real build always serves these fourteen. What is asserted
here is the floor beneath that: the one composition input they need, absent.
"""

from __future__ import annotations

import dataclasses
from typing import Final

import pytest

from my_pa.adapters.normalization import _BUILDERS
from my_pa.application.service import (
    _CONSTRAINT_AUTHORING_CAPABILITIES,
    _CONSTRAINT_CAPABILITIES,
    _HANDLERS,
    ApplicationService,
)
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from tests.conftest import Scene, build_service

AUTHORING: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CONSTRAINTS_CREATE,
        # PC-CM-RUN01-WP07. The atomic create-and-publish is the fourteenth
        # authoring grant: one transaction that mints a Constraint and issues
        # its public code, composing the capabilities either side of it.
        Capability.CONSTRAINTS_CREATE_PUBLISHED,
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
        # PC-CM-RUN01-WP05. Stating a Project's calendar is an authoring grant
        # in its own right: it moves a settings version, writes a receipt, and
        # changes what every date-derived reading of that Project means.
        Capability.PROJECT_CONTROLS_CONFIGURE,
    }
)


def _uncomposed(scene: Scene) -> ApplicationService:
    """The same build, handed no Constraint unit-of-work factory."""
    return build_service(scene.world, scene.providers, constraint_management_unit_of_work=None)


# ---- the wiring --------------------------------------------------------------


def test_the_declared_authoring_set_is_the_fourteen() -> None:
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


# ---- what a *stored* Project timezone failure is classified as ---------------


def _invoke(capability: Capability, scene: Scene, payload: dict[str, object]) -> ResponseEnvelope:
    """One authoring request, normalized and invoked against a composed build."""
    from my_pa.adapters.normalization import normalize
    from tests.contract.test_transport_parity import document

    metadata, command = normalize(
        capability.value, document(capability, scene.principal.principal_id, payload)
    )
    return build_service(scene.world, scene.providers).invoke(
        metadata, command, principal=scene.principal
    )


def test_a_stored_project_timezone_the_database_refuses_is_unavailable_not_invalid(
    scene: Scene,
) -> None:
    """PC-CM-RUN01-WP05 corrective cycle, N6. `unavailable`, and pinned here.

    `_constraint_mutation_translated` wraps the twelve pre-existing authoring
    mutations as well as the two Project Controls ones, so admitting a
    `ProjectTimezoneError` clause for the configure path decided an answer for
    these twelve too. Fail-closed is right — this build never substitutes a
    calendar — but the value at fault is a *stored* one this caller neither sent
    nor can change from this request, so `invalid_request` would send it looking
    for a mistake in a field it does not have. `unavailable` naming the Project
    is the same answer `constraints._project_today` already gives the read plane
    for the same fact.

    Reached with `completion_date` omitted, which is the only way a close asks
    the Project's calendar anything: a request carrying the date never asks.
    """
    principal_id = scene.principal.principal_id
    project_id = scene.world.project_constraints[
        (principal_id, scene.constraint_close_id)
    ].project_id
    key = (principal_id, project_id)
    stored = scene.world.constraint_settings[key]
    scene.world.constraint_settings[key] = dataclasses.replace(
        stored, timezone_name="Mars/Olympus_Mons"
    )

    envelope = _invoke(
        Capability.CONSTRAINTS_CLOSE,
        scene,
        {
            "constraint_id": scene.constraint_close_id,
            "expected_version": 1,
            "closure_commentary": "Resolved on site.",
        },
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.UNAVAILABLE


def test_a_caller_supplied_timezone_the_database_refuses_is_still_invalid_request(
    scene: Scene,
) -> None:
    """The other half of the same narrowing, so neither can drift alone.

    `project_controls.configure` validates the caller's own string before it
    reads or locks anything, so here the fault genuinely is a request field and
    `invalid_request` is the truth. `_project_controls_timezone_translated` is
    nested inside the wider translator at that one call site to keep it so.
    """
    envelope = _invoke(
        Capability.PROJECT_CONTROLS_CONFIGURE,
        scene,
        {
            "project_id": scene.constraint_unconfigured_project_id,
            "timezone_name": "Mars/Olympus_Mons",
            "idempotency_key": "pc-wp05-corrective-01",
        },
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.INVALID_REQUEST
    # And never the value: the refused name is the caller's own string.
    assert "Mars/Olympus_Mons" not in envelope.model_dump_json()
