"""Canvas workspace commands and overlay handlers (UI-IMP-WP17)."""

from __future__ import annotations

import json
import math
from types import MappingProxyType

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import Command, GetCanvasWorkspace, PutCanvasWorkspace
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.canvas_workspace import _json_positions
from tests.conftest import FakeProviders, World, build_service, metadata_for, operator

FOCUS = make_identifier(IdKind.ENTITY, "canvasfocus01canvasfocus01")
SCOPE = make_identifier(IdKind.ENTITY, "canvasscope01canvasscope01")
MOVED = make_identifier(IdKind.ENTITY, "canvasmoved01canvasmoved01")


def _put(
    *,
    expected_version: int = 0,
    positions: dict[str, dict[str, float]] | None = None,
    focus_entity_id: str | None = FOCUS,
    scope_entity_id: str | None = None,
) -> PutCanvasWorkspace:
    return PutCanvasWorkspace(
        expected_version=expected_version,
        positions=positions if positions is not None else {MOVED: {"x": 12.5, "y": -4.0}},
        focus_entity_id=focus_entity_id,
        scope_entity_id=scope_entity_id,
    )


def _invoke(
    service: ApplicationService, principal: Principal, command: Command
) -> ResponseEnvelope:
    purpose = next(iter(permitted_purposes(command.capability)))
    return service.invoke(
        metadata_for(command.capability, purpose, principal), command, principal=principal
    )


def test_get_missing_returns_empty_overlay_version_zero() -> None:
    world = World()
    principal = operator()
    service = build_service(world, FakeProviders())
    envelope = _invoke(
        service, principal, GetCanvasWorkspace(focus_entity_id=FOCUS, scope_entity_id=SCOPE)
    )
    assert envelope.error is None
    assert envelope.result == {
        "focus_entity_id": FOCUS,
        "scope_entity_id": SCOPE,
        "version": 0,
        "positions": {},
        "updated_at": None,
    }


def test_put_creates_first_stored_version() -> None:
    world = World()
    principal = operator()
    service = build_service(world, FakeProviders())
    envelope = _invoke(service, principal, _put())
    assert envelope.error is None
    assert envelope.result is not None
    assert envelope.result["version"] == 1
    assert envelope.result["focus_entity_id"] == FOCUS
    assert envelope.result["updated_at"] is not None
    stored = world.canvas_workspaces[(principal.principal_id, FOCUS, None)]
    assert stored.version == 1


def test_principals_do_not_share_an_overlay() -> None:
    world = World()
    alice = operator()
    bob = operator()
    service = build_service(world, FakeProviders())
    created = _invoke(service, alice, _put())
    assert created.error is None
    alice_read = _invoke(service, alice, GetCanvasWorkspace(focus_entity_id=FOCUS))
    bob_read = _invoke(service, bob, GetCanvasWorkspace(focus_entity_id=FOCUS))
    assert alice_read.error is None and alice_read.result is not None
    assert alice_read.result["version"] == 1
    assert bob_read.error is None
    assert bob_read.result == {
        "focus_entity_id": FOCUS,
        "scope_entity_id": None,
        "version": 0,
        "positions": {},
        "updated_at": None,
    }


def test_put_is_idempotent_for_the_same_positions_and_version() -> None:
    world = World()
    principal = operator()
    service = build_service(world, FakeProviders())
    first = _invoke(service, principal, _put())
    second = _invoke(service, principal, _put(expected_version=1))
    assert first.error is None and second.error is None
    assert first.result == second.result
    assert world.canvas_workspaces[(principal.principal_id, FOCUS, None)].version == 1


def test_put_stale_expected_version_conflicts_and_leaves_the_row() -> None:
    world = World()
    principal = operator()
    service = build_service(world, FakeProviders())
    created = _invoke(service, principal, _put())
    assert created.error is None
    refused = _invoke(
        service,
        principal,
        _put(expected_version=0, positions={MOVED: {"x": 99.0, "y": 99.0}}),
    )
    assert refused.error is not None
    assert refused.error.code.value == "conflict"
    assert refused.error.safe_details == ("stale_version",)
    stored = world.canvas_workspaces[(principal.principal_id, FOCUS, None)]
    assert stored.version == 1
    assert stored.positions[MOVED]["x"] == 12.5


def test_extra_position_fields_are_rejected() -> None:
    with pytest.raises(InvalidRequestError) as refused:
        PutCanvasWorkspace(
            expected_version=0,
            focus_entity_id=FOCUS,
            positions={MOVED: {"x": 1.0, "y": 2.0, "z": 3.0}},
        )
    assert refused.value.safe_details == (SafeDetail.POSITIONS,)
    with pytest.raises(InvalidRequestError):
        PutCanvasWorkspace(
            expected_version=0,
            focus_entity_id=FOCUS,
            positions={MOVED: {"x": math.inf, "y": 0.0}},
        )


def test_frozen_command_positions_are_json_serializable_for_jsonb() -> None:
    frozen = MappingProxyType({MOVED: MappingProxyType({"x": 12.5, "y": -4.0})})
    payload = _json_positions(frozen)
    assert json.dumps(payload) == json.dumps({MOVED: {"x": 12.5, "y": -4.0}})
    assert type(payload[MOVED]) is dict


def test_a_seed_is_required() -> None:
    with pytest.raises(InvalidRequestError) as missing:
        GetCanvasWorkspace()
    assert missing.value.safe_details == (SafeDetail.FOCUS_ENTITY_ID,)
    with pytest.raises(InvalidRequestError):
        PutCanvasWorkspace(expected_version=0, positions={})


def test_extra_authority_fields_fail_closed() -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CANVAS_WORKSPACE_PUT.value,
            {
                "request_id": "req-canvas-put",
                "purpose": Purpose.CANVAS_WORKSPACE_AUTHORING.value,
                "principal_id": operator().principal_id,
                "requested_at": "2026-09-05T12:00:00Z",
                "payload": {
                    "focus_entity_id": FOCUS,
                    "expected_version": 0,
                    "positions": {},
                    "owner_principal_id": "prn_other0001other0001other0001",
                },
            },
        )
