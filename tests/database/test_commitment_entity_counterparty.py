"""A Commitment names a locally-created Entity as its counterparty (real database).

The hazard: a Commitment's counterparty was `IdKind.PERSON`, an identity only the
Graph-sourced identity-resolution pipeline can mint into
`knowledge.relationship_people`, which this deployment never populates — so the
public `commitments.create` could never succeed. The counterparty is now an
`IdKind.ENTITY` naming a current (`active`) `person` or `organization` row of
`knowledge.entities` in the caller's own Principal, which `entities.create` can
mint locally. Everything here runs through `ApplicationService.invoke`.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert

from my_pa.application.commands import (
    ArchiveEntity,
    CreateCapture,
    CreateCommitment,
    CreateEntity,
    ReadCommitment,
    UpdateCommitment,
)
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.relationship.entity import EntityStatus, EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.situation.continuity import CommitmentDirection
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import entities
from tests.database.test_record_event_routing import WHEN, Runtime

pytestmark = pytest.mark.database

PRINCIPAL = "prn_cmtentitycpty0001"
OTHER_PRINCIPAL = "prn_cmtentitycpty0002"


def seed_counterparty_entity(
    engine: Engine,
    principal_id: str,
    *,
    entity_type: EntityType = EntityType.PERSON,
    display_name: str = "Synthetic Counterparty",
    entity_id: str | None = None,
) -> str:
    """Insert one `active` Entity a Commitment may name, and return its identifier.

    For database tests that drive `CommitmentManagementService` (or insert a
    Commitment row) directly: `knowledge.commitments` now carries a composite
    foreign key onto `knowledge.entities`, so a counterparty has to exist in
    the same Principal. The public path mints one through `entities.create`.
    A caller that needs the same counterparty on every call (an idempotent
    replay binds it into the request digest) passes a fixed `entity_id`; a
    second insert of it is a no-op.
    """
    entity_id = entity_id or issue_identifier(IdKind.ENTITY)
    with engine.begin() as connection:
        connection.execute(
            insert(entities)
            .values(
                entity_id=entity_id,
                principal_id=principal_id,
                entity_type=entity_type.value,
                canonical_name=normalize_name(display_name),
                display_name=display_name,
                status=EntityStatus.ACTIVE.value,
                created_at=WHEN,
                updated_at=WHEN,
                version=1,
            )
            .on_conflict_do_nothing(index_elements=["entity_id"])
        )
    return entity_id


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _refused(rt: Runtime, command: Any, principal_id: str = PRINCIPAL) -> dict[str, Any]:  # noqa: ANN401
    envelope = rt.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=command.capability,
            purpose=sorted(permitted_purposes(command.capability))[0],
            principal_id=principal_id,
            requested_at=WHEN,
        ),
        command,
        principal=Principal(
            principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
    )
    assert envelope.error is not None
    error = envelope.to_canonical_dict()["error"]
    assert isinstance(error, dict)
    return error


def _entity(rt: Runtime, entity_type: EntityType, key: str, principal_id: str = PRINCIPAL) -> str:
    return str(
        rt.ok(
            CreateEntity(
                entity_type=entity_type,
                display_name=f"Synthetic {entity_type.value} {key}",
                idempotency_key=f"cmt-cpty-entity-{key}",
            ),
            principal_id,
        )["entity_id"]
    )


def _capture(rt: Runtime, key: str) -> str:
    return str(
        rt.ok(
            CreateCapture(
                text=f"Synthetic commitment origin {key}", idempotency_key=f"cmt-cap-{key}"
            ),
            PRINCIPAL,
        )["capture_id"]
    )


def _create(entity_id: str, capture: str, key: str) -> CreateCommitment:
    return CreateCommitment(
        counterparty_entity_id=entity_id,
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send the synthetic report",
        origin_evidence_ref=capture,
        idempotency_key=f"cmt-cpty-create-{key}",
    )


@pytest.mark.parametrize("entity_type", [EntityType.ORGANIZATION, EntityType.PERSON])
def test_a_commitment_names_a_locally_created_entity_as_its_counterparty(
    runtime: Runtime, entity_type: EntityType
) -> None:
    key = entity_type.value
    entity_id = _entity(runtime, entity_type, key)
    created = runtime.ok(_create(entity_id, _capture(runtime, key), key), PRINCIPAL)["commitment"]
    assert created["counterparty_entity_id"] == entity_id
    assert created["counterparty"] == {
        "entity_id": entity_id,
        "display_name": f"Synthetic {key} {key}",
    }
    read = runtime.ok(ReadCommitment(commitment_id=created["commitment_id"]), PRINCIPAL)
    assert read["commitment"]["counterparty_entity_id"] == entity_id
    assert read["commitment"]["counterparty"]["entity_id"] == entity_id
    options = read["counterparty_options"]
    assert {"entity_id": entity_id, "display_name": f"Synthetic {key} {key}"} in options


def test_a_non_current_wrong_type_or_foreign_entity_is_refused_as_absent(
    runtime: Runtime,
) -> None:
    capture = _capture(runtime, "refuse")
    archived = _entity(runtime, EntityType.ORGANIZATION, "archived")
    runtime.ok(
        ArchiveEntity(
            entity_id=archived,
            expected_version=1,
            reason="Synthetic archive",
            idempotency_key="cmt-cpty-archive-0001",
        ),
        PRINCIPAL,
    )
    wrong_type = _entity(runtime, EntityType.TEAM_OR_GROUP, "team")
    foreign = _entity(runtime, EntityType.PERSON, "foreign", OTHER_PRINCIPAL)
    for index, entity_id in enumerate((archived, wrong_type, foreign)):
        error = _refused(runtime, _create(entity_id, capture, f"refuse-{index}"))
        assert error["code"] == "not_found", error
        assert "counterparty_entity_id" in str(error), error


def test_a_counterparty_that_stops_being_current_is_unprojected_and_cannot_be_named_again(
    runtime: Runtime,
) -> None:
    capture = _capture(runtime, "lapse")
    first = _entity(runtime, EntityType.PERSON, "lapse-first")
    second = _entity(runtime, EntityType.ORGANIZATION, "lapse-second")
    created = runtime.ok(_create(first, capture, "lapse"), PRINCIPAL)["commitment"]
    runtime.ok(
        ArchiveEntity(
            entity_id=first,
            expected_version=1,
            reason="Synthetic archive",
            idempotency_key="cmt-cpty-archive-0002",
        ),
        PRINCIPAL,
    )
    read = runtime.ok(ReadCommitment(commitment_id=created["commitment_id"]), PRINCIPAL)
    assert read["commitment"]["counterparty_entity_id"] == first
    assert read["commitment"]["counterparty"] is None
    error = _refused(
        runtime,
        UpdateCommitment(
            commitment_id=created["commitment_id"],
            expected_version=1,
            idempotency_key="cmt-cpty-update-0001",
            counterparty_entity_id=first,
        ),
    )
    assert error["code"] == "not_found", error
    updated = runtime.ok(
        UpdateCommitment(
            commitment_id=created["commitment_id"],
            expected_version=1,
            idempotency_key="cmt-cpty-update-0002",
            counterparty_entity_id=second,
        ),
        PRINCIPAL,
    )["commitment"]
    assert updated["counterparty_entity_id"] == second
    assert updated["counterparty"]["entity_id"] == second
