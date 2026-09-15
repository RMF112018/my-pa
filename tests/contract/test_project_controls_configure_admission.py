"""PC-CM-RUN01-WP05: the two Project Controls names, as the interface publishes them.

Capability, manifest, availability, MCP tool and the exact wire payload. The
payload assertions are the contract a browser decoder is written against, so
they name every key rather than checking a subset: a field added or renamed
here is a decoder that stops matching, and this is where that has to fail.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.conftest import Scene, build_service
from tests.contract.test_application_capabilities import run, succeeded
from tests.contract.test_capabilities_and_readiness import LIMITS

from my_pa.adapters.mcp import TOOLS
from my_pa.adapters.normalization import _BUILDERS, normalize
from my_pa.application.capabilities import build_capability_manifest
from my_pa.application.service import (
    _CONSTRAINT_AUTHORING_CAPABILITIES,
    _CONSTRAINT_CAPABILITIES,
    _HANDLERS,
    ApplicationService,
)
from my_pa.contracts.v1.capabilities import Availability
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.situation import Project, ProjectState

CONFIGURE: Final = Capability.PROJECT_CONTROLS_CONFIGURE
STATUS: Final = Capability.PROJECT_CONTROLS_STATUS
ZONE: Final = "America/Chicago"


def _service(scene: Scene) -> ApplicationService:
    return build_service(scene.world, scene.providers)


# --- admission ----------------------------------------------------------------


def test_both_names_are_wired_end_to_end() -> None:
    """A command builder, a handler, and an MCP tool, for each of the two."""
    published = {tool.name for tool in TOOLS}
    for capability in (CONFIGURE, STATUS):
        assert capability in _BUILDERS
        assert capability in _HANDLERS
        assert capability.value in published


def test_the_two_names_land_in_the_two_availability_sets() -> None:
    """The write with the authoring grants, the read with the read grants."""
    assert CONFIGURE in _CONSTRAINT_AUTHORING_CAPABILITIES
    assert STATUS in _CONSTRAINT_CAPABILITIES
    assert not (_CONSTRAINT_AUTHORING_CAPABILITIES & _CONSTRAINT_CAPABILITIES)


def test_the_purposes_are_the_accepted_ones() -> None:
    assert permitted_purposes(CONFIGURE) == frozenset({Purpose.CONSTRAINT_AUTHORING})
    assert permitted_purposes(STATUS) == frozenset({Purpose.CONSTRAINT_READ})


def test_the_manifest_reports_both_as_available_without_being_edited() -> None:
    """The manifest is derived from `implemented`, so wiring is all it took.

    `build_capability_manifest` names no capability of its own — it walks
    `Capability` and asks whether each is in the set it was handed — which is
    why this work package edits `application.capabilities` not at all. Proved
    from both directions: available when the handler is present, and
    `not_implemented` when it is not.
    """
    manifest = build_capability_manifest(implemented=frozenset(_HANDLERS), limits=LIMITS)
    states = {status.name: status.availability for status in manifest.capabilities}
    assert states[CONFIGURE] is Availability.AVAILABLE
    assert states[STATUS] is Availability.AVAILABLE
    without = build_capability_manifest(
        implemented=frozenset(_HANDLERS) - {CONFIGURE, STATUS}, limits=LIMITS
    )
    absent = {status.name: status.availability for status in without.capabilities}
    assert absent[CONFIGURE] is Availability.NOT_IMPLEMENTED
    assert absent[STATUS] is Availability.NOT_IMPLEMENTED


def test_a_process_with_no_constraint_factory_withholds_both(scene: Scene) -> None:
    served = build_service(
        scene.world, scene.providers, constraint_management_unit_of_work=None
    ).available_capabilities
    assert CONFIGURE not in served
    assert STATUS not in served


def test_a_composed_process_serves_both(scene: Scene) -> None:
    served = _service(scene).available_capabilities
    assert {CONFIGURE, STATUS} <= served


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        (STATUS, {"project_id": "prj_aaaaaaaa11111111"}),
        (
            CONFIGURE,
            {
                "project_id": "prj_aaaaaaaa11111111",
                "timezone_name": ZONE,
                "idempotency_key": "admission-key-0001",
            },
        ),
    ],
    ids=lambda value: getattr(value, "value", "payload"),
)
def test_the_normalizer_builds_the_command_the_capability_declares(
    capability: Capability, payload: dict[str, object]
) -> None:
    command = _BUILDERS[capability](payload)
    assert command.capability is capability


@pytest.mark.parametrize("capability", [CONFIGURE, STATUS], ids=lambda c: c.value)
def test_the_normalizer_is_closed_over_its_declared_fields(capability: Capability) -> None:
    """An unknown key is refused rather than ignored, and a Principal is unknown."""
    payload = {
        "project_id": "prj_aaaaaaaa11111111",
        "timezone_name": ZONE,
        "idempotency_key": "admission-key-0001",
        "principal_id": "prn_24abf5d2d0c25e1c82f6e72425e9ed37",
    }
    with pytest.raises(Exception):  # noqa: B017 - the boundary's own refusal type
        normalize(capability.value, _document(capability, payload))


def _document(capability: Capability, payload: dict[str, object]) -> dict[str, object]:
    from tests.contract.test_transport_parity import document

    return document(capability, "prn_24abf5d2d0c25e1c82f6e72425e9ed37", payload)


# --- the wire payload contract ------------------------------------------------


_STATUS_KEYS: Final = {
    "project_id",
    "state",
    "timezone_name",
    "settings_version",
    "settings_updated_at",
}


def test_status_reports_a_configured_project_in_the_declared_shape(scene: Scene) -> None:
    result = succeeded(
        run(
            _service(scene),
            scene,
            STATUS,
            Purpose.CONSTRAINT_READ,
            _BUILDERS[STATUS]({"project_id": scene.constraint_project_id}),
        )
    )
    assert set(result) == {"project_controls"}
    controls = result["project_controls"]
    assert isinstance(controls, dict)
    assert set(controls) == _STATUS_KEYS
    assert controls["project_id"] == scene.constraint_project_id
    assert controls["state"] == "configured"
    assert controls["timezone_name"] == "UTC"
    assert controls["settings_version"] == 1
    assert isinstance(controls["settings_updated_at"], str)
    assert "principal_id" not in controls


def test_status_reports_an_unconfigured_project_with_the_same_keys(scene: Scene) -> None:
    """Same object, same keys, four nulls. A client branches on `state` alone."""
    result = succeeded(
        run(
            _service(scene),
            scene,
            STATUS,
            Purpose.CONSTRAINT_READ,
            _BUILDERS[STATUS]({"project_id": scene.constraint_unconfigured_project_id}),
        )
    )
    controls = result["project_controls"]
    assert isinstance(controls, dict)
    assert set(controls) == _STATUS_KEYS
    assert controls["state"] == "not_configured"
    assert controls["timezone_name"] is None
    assert controls["settings_version"] is None
    assert controls["settings_updated_at"] is None


def test_configure_reports_the_declared_shape(scene: Scene) -> None:
    result = succeeded(
        run(
            _service(scene),
            scene,
            CONFIGURE,
            Purpose.CONSTRAINT_AUTHORING,
            _BUILDERS[CONFIGURE](
                {
                    "project_id": scene.constraint_unconfigured_project_id,
                    "timezone_name": ZONE,
                    "idempotency_key": "admission-configure-0001",
                }
            ),
        )
    )
    assert set(result) == {"disposition", "project_controls"}
    assert result["disposition"] == "applied"
    controls = result["project_controls"]
    assert isinstance(controls, dict)
    assert set(controls) == _STATUS_KEYS
    assert controls["project_id"] == scene.constraint_unconfigured_project_id
    assert controls["state"] == "configured"
    assert controls["timezone_name"] == ZONE
    assert controls["settings_version"] == 1
    assert isinstance(controls["settings_updated_at"], str)
    assert "principal_id" not in controls
    assert "receipt" not in result


def test_a_replayed_configure_carries_the_same_object_and_a_replayed_disposition(
    scene: Scene,
) -> None:
    service = _service(scene)
    payload = {
        "project_id": scene.constraint_unconfigured_project_id,
        "timezone_name": ZONE,
        "idempotency_key": "admission-replay-0001",
    }
    first = succeeded(
        run(service, scene, CONFIGURE, Purpose.CONSTRAINT_AUTHORING, _BUILDERS[CONFIGURE](payload))
    )
    second = succeeded(
        run(service, scene, CONFIGURE, Purpose.CONSTRAINT_AUTHORING, _BUILDERS[CONFIGURE](payload))
    )
    assert first["disposition"] == "applied"
    assert second["disposition"] == "replayed"
    assert second["project_controls"] == first["project_controls"]


def test_an_unknown_and_a_foreign_project_answer_identically(scene: Scene) -> None:
    """Nondisclosure at the transport boundary, on both capabilities.

    The two identifiers are well-formed and neither names a Project in this
    Principal's partition, so the envelopes must be equal in everything the
    caller can read.
    """
    service = _service(scene)
    unknown = "prj_zzzzzzzz99999999"
    foreign = "prj_yyyyyyyy88888888"
    scene.world.projects.append(_foreign_project(foreign))
    for capability, purpose, extra in (
        (STATUS, Purpose.CONSTRAINT_READ, {}),
        (
            CONFIGURE,
            Purpose.CONSTRAINT_AUTHORING,
            {"timezone_name": ZONE, "idempotency_key": "admission-nondisclosure-01"},
        ),
    ):
        answers = []
        for project_id in (unknown, foreign):
            envelope = run(
                service,
                scene,
                capability,
                purpose,
                _BUILDERS[capability]({"project_id": project_id, **extra}),
            )
            assert envelope.error is not None
            answers.append(
                (
                    envelope.error.code,
                    tuple(envelope.error.safe_details),
                    envelope.error.message,
                    envelope.result,
                )
            )
        assert answers[0] == answers[1], capability


def _foreign_project(project_id: str) -> Project:
    from tests.conftest import WHEN

    return Project(
        project_id=project_id,
        principal_id="prn_ffffffffffffffffffffffffffffffff",
        name="Another Principal's Project",
        state=ProjectState.ACTIVE,
        opened_at=WHEN,
        created_at=WHEN,
        updated_at=WHEN,
    )
