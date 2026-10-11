"""The sixteen Continuity Project fields, from the wire through the service and back."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.situation.situation import (
    TYPE_TO_SECTOR,
    ProjectSector,
    ProjectType,
    is_storable_project_value,
)
from tests.conftest import Scene, build_service
from tests.contract.test_transport_parity import document

FULL: Mapping[str, Any] = {
    "aliases": ["NSP", "North slab"],
    "project_number": "2026-017",
    "sector": "education_civic_and_community",
    "type": "higher_education_and_academic_facilities",
    "address": "1 College Way",
    "city": "Tampa",
    "county": "Hillsborough",
    "address_state": "FL",
    "zip": "33620",
    "value": 1250000.5,
    "scheduled_start": "2026-11-02",
    "contract_start": "2026-11-09",
    "actual_start": "2026-11-16",
    "scheduled_finish": "2027-12-17",
    "contract_finish": "2027-12-31",
    "actual_finish": "2028-01-14",
}


def _call(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
) -> ResponseEnvelope:
    metadata, command = normalize(
        capability.value, document(capability, principal.principal_id, payload)
    )
    return service.invoke(metadata, command, principal=principal)


def _create(
    service: ApplicationService, principal: Principal, key: str, **fields: object
) -> ResponseEnvelope:
    return _call(
        service,
        principal,
        Capability.CONTINUITY_PROJECTS_CREATE,
        {"name": f"Project {key}", "idempotency_key": key, **fields},
    )


def _update(
    service: ApplicationService,
    principal: Principal,
    project_id: str,
    version: int,
    key: str,
    **fields: object,
) -> ResponseEnvelope:
    return _call(
        service,
        principal,
        Capability.CONTINUITY_PROJECTS_UPDATE,
        {
            "project_id": project_id,
            "expected_version": version,
            "idempotency_key": key,
            **fields,
        },
    )


def _read(service: ApplicationService, principal: Principal, project_id: str) -> dict[str, Any]:
    read = _call(
        service, principal, Capability.CONTINUITY_PROJECTS_READ, {"project_id": project_id}
    )
    assert read.error is None and read.result is not None
    return dict(read.result)


def _refusal(envelope: ResponseEnvelope) -> tuple[ErrorCode, list[str]]:
    assert envelope.error is not None and envelope.result is None
    return envelope.error.code, list(envelope.error.safe_details)


# ---- create echoes, and a read returns, exactly what was stored -----------------


def test_create_echoes_all_sixteen_fields_and_a_read_returns_the_same(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-full-0001", **FULL)
    assert created.error is None and created.result is not None
    expected = {**FULL, "value": "1250000.50"}
    for name, value in expected.items():
        assert created.result[name] == value, name
    read = _read(service, scene.principal, created.result["project_id"])
    for name, value in expected.items():
        assert read[name] == value, name


def test_a_project_created_without_the_fields_carries_their_empty_defaults(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-none-0001")
    assert created.error is None and created.result is not None
    assert created.result["aliases"] == []
    for name in FULL:
        if name != "aliases":
            assert created.result[name] is None, name


# ---- value: whole cents, finite, unsigned, below 10**12 ------------------------


@pytest.mark.parametrize(
    ("given", "stated"),
    [
        (12.5, "12.50"),
        (1e3, "1000.00"),
        (0, "0.00"),
        (999999999999.99, "999999999999.99"),
        (7, "7.00"),
        (1250000.05, "1250000.05"),
    ],
)
def test_an_exact_amount_is_echoed_in_whole_cents(scene: Scene, given: object, stated: str) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, f"fields-value-{stated}-01", value=given)
    assert created.error is None and created.result is not None
    assert created.result["value"] == stated
    assert _read(service, scene.principal, created.result["project_id"])["value"] == stated


@pytest.mark.parametrize(
    "given",
    [
        "12.50",
        "1E+3",
        "NaN",
        "Infinity",
        float("nan"),
        float("inf"),
        1e20,
        1000000000000,
        1.005,
        0.001,
        -1,
        -0.0,
        True,
        "abc",
        [12],
    ],
)
def test_an_amount_that_would_not_store_unchanged_is_invalid_request(given: object) -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CONTINUITY_PROJECTS_CREATE.value,
            document(
                Capability.CONTINUITY_PROJECTS_CREATE,
                "prn_aaaaaaaa11111111",
                {"name": "Valued", "idempotency_key": "fields-badvalue-0001", "value": given},
            ),
        )


def test_the_storable_amount_rule_is_exactly_numeric_14_2() -> None:
    assert is_storable_project_value(Decimal("0.00"))
    assert is_storable_project_value(Decimal("999999999999.99"))
    assert not is_storable_project_value(Decimal("1000000000000"))
    assert not is_storable_project_value(Decimal("0.001"))
    assert not is_storable_project_value(Decimal("-0"))
    assert not is_storable_project_value(Decimal("NaN"))
    assert not is_storable_project_value(1)


# ---- sector and type ----------------------------------------------------------


def test_every_type_names_exactly_one_known_sector() -> None:
    assert set(TYPE_TO_SECTOR) == set(ProjectType)
    assert set(TYPE_TO_SECTOR.values()) == set(ProjectSector)


@pytest.mark.parametrize(
    "pair",
    [
        {"sector": "housing_and_residential"},
        {"type": "single_family_housing"},
        {"sector": "transportation_and_mobility", "type": "single_family_housing"},
        {"sector": "not_a_sector", "type": "single_family_housing"},
    ],
)
def test_a_half_supplied_or_mismatched_pair_is_invalid_request(pair: dict[str, str]) -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CONTINUITY_PROJECTS_CREATE.value,
            document(
                Capability.CONTINUITY_PROJECTS_CREATE,
                "prn_aaaaaaaa11111111",
                {"name": "Typed", "idempotency_key": "fields-badpair-0001", **pair},
            ),
        )


@pytest.mark.parametrize("given", ["2026-13-01", "2026-11-02T00:00:00Z", "soon", 20261102])
def test_a_date_that_is_not_a_calendar_date_is_invalid_request(given: object) -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CONTINUITY_PROJECTS_CREATE.value,
            document(
                Capability.CONTINUITY_PROJECTS_CREATE,
                "prn_aaaaaaaa11111111",
                {"name": "Dated", "idempotency_key": "fields-baddate-0001", "actual_start": given},
            ),
        )


# ---- project_number: trimmed, unique per Principal, changeable and clearable ----


def test_a_project_number_is_trimmed(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-trim-0001", project_number="  P-12  ")
    assert created.error is None and created.result is not None
    assert created.result["project_number"] == "P-12"


def test_a_number_another_project_holds_is_conflict_on_create(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = _create(service, scene.principal, "fields-dup-a-0001", project_number="2026-017")
    assert first.error is None
    second = _create(service, scene.principal, "fields-dup-b-0001", project_number=" 2026-017 ")
    assert _refusal(second) == (ErrorCode.CONFLICT, ["project_number"])


def test_a_number_another_project_holds_is_conflict_on_update(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    held = _create(service, scene.principal, "fields-dupu-a-0001", project_number="2026-018")
    assert held.error is None
    other = _create(service, scene.principal, "fields-dupu-b-0001")
    assert other.error is None and other.result is not None
    refused = _update(
        service,
        scene.principal,
        other.result["project_id"],
        1,
        "fields-dupu-upd-0001",
        project_number="2026-018",
    )
    assert _refusal(refused) == (ErrorCode.CONFLICT, ["project_number"])
    assert _read(service, scene.principal, other.result["project_id"])["project_number"] is None


def test_every_field_can_be_changed_after_create_including_the_number(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-mut-0001", **FULL)
    assert created.error is None and created.result is not None
    project_id = created.result["project_id"]
    changed = {
        "aliases": ["Renamed alias"],
        "project_number": "2026-099",
        "sector": "transportation_and_mobility",
        "type": "roads_bridges_and_tunnels",
        "address": "2 Harbor Rd",
        "city": "Clearwater",
        "county": "Pinellas",
        "address_state": "Florida",
        "zip": "33755",
        "value": 980000,
        "scheduled_start": "2027-01-04",
        "contract_start": "2027-01-11",
        "actual_start": "2027-01-18",
        "scheduled_finish": "2028-06-30",
        "contract_finish": "2028-07-31",
        "actual_finish": "2028-08-15",
    }
    updated = _update(service, scene.principal, project_id, 1, "fields-mut-upd-0001", **changed)
    assert updated.error is None and updated.result is not None
    read = _read(service, scene.principal, project_id)
    for name, value in {**changed, "value": "980000.00"}.items():
        assert updated.result[name] == value, name
        assert read[name] == value, name
    renumbered = _update(
        service, scene.principal, project_id, 2, "fields-mut-renum-0001", project_number="2026-100"
    )
    assert renumbered.error is None and renumbered.result is not None
    assert renumbered.result["project_number"] == "2026-100"


def test_clear_fields_empties_the_named_fields_and_leaves_the_rest(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-clear-0001", **FULL)
    assert created.error is None and created.result is not None
    project_id = created.result["project_id"]
    cleared = _update(
        service,
        scene.principal,
        project_id,
        1,
        "fields-clear-upd-0001",
        clear_fields=["project_number", "value", "aliases", "sector", "type", "actual_finish"],
    )
    assert cleared.error is None
    read = _read(service, scene.principal, project_id)
    for name in ("project_number", "value", "sector", "type", "actual_finish"):
        assert read[name] is None, name
    assert read["aliases"] == []
    assert read["city"] == FULL["city"]
    assert read["contract_finish"] == FULL["contract_finish"]
    # A cleared number is free for another Project to take.
    assert (
        _create(service, scene.principal, "fields-clear-reuse-01", project_number="2026-017").error
        is None
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"clear_fields": ["sector"]},
        {"clear_fields": ["value"], "value": 5},
        {"clear_fields": ["name"]},
        {"clear_fields": ["state"]},
        {"clear_fields": ["not_a_field"]},
        {"clear_fields": ["city", "city"]},
        {"clear_fields": "city"},
        {"clear_fields": [None]},
    ],
)
def test_a_clear_that_is_unknown_split_duplicated_or_also_set_is_invalid_request(
    fields: dict[str, object],
) -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            Capability.CONTINUITY_PROJECTS_UPDATE.value,
            document(
                Capability.CONTINUITY_PROJECTS_UPDATE,
                "prn_aaaaaaaa11111111",
                {
                    "project_id": "prj_aaaaaaaa11111111",
                    "expected_version": 1,
                    "idempotency_key": "fields-badclear-0001",
                    **fields,
                },
            ),
        )


def test_a_replayed_key_with_different_clears_is_conflict(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-replay-0001", **FULL)
    assert created.error is None and created.result is not None
    project_id = created.result["project_id"]
    first = _update(
        service, scene.principal, project_id, 1, "fields-replay-upd-01", clear_fields=["city"]
    )
    assert first.error is None
    again = _update(
        service, scene.principal, project_id, 1, "fields-replay-upd-01", clear_fields=["city"]
    )
    assert again.error is None and again.result is not None
    assert again.result["replayed"] is True
    other = _update(
        service, scene.principal, project_id, 1, "fields-replay-upd-01", clear_fields=["county"]
    )
    assert _refusal(other) == (ErrorCode.CONFLICT, ["idempotency_key"])


def test_an_update_changes_only_the_fields_it_names(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    created = _create(service, scene.principal, "fields-partial-0001", **FULL)
    assert created.error is None and created.result is not None
    project_id = created.result["project_id"]
    updated = _update(
        service,
        scene.principal,
        project_id,
        1,
        "fields-partial-upd-0001",
        city="St. Petersburg",
        aliases=[],
    )
    assert updated.error is None
    read = _read(service, scene.principal, project_id)
    assert read["city"] == "St. Petersburg"
    assert read["aliases"] == []
    for name in ("project_number", "sector", "type", "address", "zip", "actual_finish"):
        assert read[name] == FULL[name], name
    assert read["value"] == "1250000.50"
