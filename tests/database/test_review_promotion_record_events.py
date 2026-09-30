"""WP-RE-04: review promotion's Record Events on a real database (RE-AC-047).

Marked `database` and routed to `database-current-head`. OD-6: every event a
review promotion causes names `review.decide` as its `source_capability`, with
actor `review_promotion` -- whichever canonical writer performed the change:

* **RP2** -- the memory branch of `review.decide`: an accepted Relationship
  Memory proposal commits one `relationship_memory` `created` event, receipt
  the review decision, with the promoted version's authority and
  classification. A non-accepting disposition commits none.
* **RP1** -- the entity branch routes through the canonical writers, so the
  `review_promotion` / `review_accepted` stamp `_execute` puts on the request
  reaches each seam: S-A (authoring), S-B (directed), S-C (family writes) and
  `resolve_mention`'s create (G1-EM-002).

Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select

from my_pa.application.commands import AddEntityName, CreateEntityAssignment
from my_pa.application.entity_authoring import EntityAuthoringService
from my_pa.application.entity_directed import EntityDirectedService
from my_pa.application.entity_family_writes import EntityFamilyWriteService
from my_pa.application.entity_governance import EntityGovernanceService, ResolveMentionCommand
from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import (
    AssignmentType,
    Entity,
    EntityStatus,
    EntityType,
    NameTypeCode,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityObservation,
    MutationAuthority,
    ObservationKind,
    ResolutionDisposition,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.resolution import EntityResolution
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.tables import (
    relationship_memory_proposals,
    relationship_memory_versions,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_relationship_memory_review import (
    PRINCIPAL_A,
    _decision,
    _open_proposal,
    two_principals,
)
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

__all__ = ["two_principals"]

WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
REVIEWED_PERSON: Final = "ent_rcevwp04bbbb0001"
REVIEWED_PROJECT: Final = "ent_rcevwp04bbbb0002"
MENTION: Final = "eobs_rcevwp04bbbb0001"
PROMOTION: Final[dict[str, Any]] = {
    "authority": MutationAuthority.REVIEW_ACCEPTED,
    "actor_class": ActorClass.REVIEW_PROMOTION,
}


@contextmanager
def unit(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    with SqlAlchemyUnitOfWork(
        engine, audit=SqlAlchemyAuditSink(engine), relationship_memory_enabled=True
    ) as uow:
        yield uow  # type: ignore[misc]


def _assert_promoted(event: dict[str, Any], *, authority: str = "review_accepted") -> None:
    assert event["source_capability"] == "review.decide"
    assert event["actor_class"] == "review_promotion"
    assert event["authority"] == authority


# ---- RP2: the memory branch ---------------------------------------------------


def test_an_accepted_memory_proposal_commits_one_promoted_created_event(
    two_principals: Engine,
) -> None:
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection, evidence=1)
    request = _decision(review_case_id, Disposition.ACCEPT)
    with unit(two_principals) as uow:
        decision = uow.reviews.decide(request)
    assert decision is not None
    events = feed(two_principals, PRINCIPAL_A)
    assert len(events) == 1
    (event,) = events
    with two_principals.connect() as connection:
        stamped = connection.execute(
            select(
                relationship_memory_proposals.c.accepted_memory_id,
                relationship_memory_proposals.c.accepted_memory_version_id,
            ).where(relationship_memory_proposals.c.memory_proposal_id == proposal_id)
        ).one()
        version = connection.execute(
            select(
                relationship_memory_versions.c.authority,
                relationship_memory_versions.c.classification,
                relationship_memory_versions.c.idempotency_key,
            ).where(
                relationship_memory_versions.c.memory_version_id
                == stamped.accepted_memory_version_id
            )
        ).one()
    assert (event["record_family"], event["record_id"], event["event_kind"]) == (
        "relationship_memory",
        stamped.accepted_memory_id,
        "created",
    )
    assert event["record_version"] == 1
    _assert_promoted(event, authority=version.authority)
    assert event["classification"] == version.classification
    # The receipt is the review decision, which is also the version's key.
    assert event["source_receipt_id"] == version.idempotency_key
    assert event["correlation_id"] == request.correlation_id
    assert event["changed_fields"] == [
        "current_version_id",
        "current_version_number",
        "lifecycle_state",
        "memory_kind",
        "subject_entity_id",
    ]
    assert_gap_free(two_principals, PRINCIPAL_A)


@pytest.mark.parametrize("disposition", [Disposition.REJECT, Disposition.DEFER])
def test_a_non_accepting_disposition_commits_no_event(
    two_principals: Engine, disposition: Disposition
) -> None:
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection, evidence=1)
    with unit(two_principals) as uow:
        uow.reviews.decide(_decision(review_case_id, disposition))
    assert feed(two_principals, PRINCIPAL_A) == []
    assert next_sequence(two_principals, PRINCIPAL_A) is None


# ---- RP1: the entity branch reaches every seam with the promotion stamp -------


def _entity_of(entity_id: str, name: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL_A,
        entity_type=kind,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def reviewed(two_principals: Engine) -> Engine:
    with two_principals.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(
            PRINCIPAL_A, _entity_of(REVIEWED_PERSON, "Reviewed Person", EntityType.PERSON)
        )
        repository.create(
            PRINCIPAL_A, _entity_of(REVIEWED_PROJECT, "Reviewed Project", EntityType.PROJECT)
        )
        repository.record_observation(
            PRINCIPAL_A,
            EntityObservation(
                observation_id=MENTION,
                principal_id=PRINCIPAL_A,
                kind=ObservationKind.MESSAGE_PARTICIPANT,
                observed_value="Wholly Unmatched Person",
                normalized_value=normalize_name("Wholly Unmatched Person"),
                mention_display_name="Wholly Unmatched Person",
                source_id="src_rcevwp04bbbb0001",
                source_object_id="obj_rcevwp04bbbb0001",
                source_version_id="ver_rcevwp04bbbb0001",
                observed_at=WHEN,
                recorded_at=WHEN,
            ),
        )
    return two_principals


def _context() -> dict[str, Any]:
    return {
        "principal_id": PRINCIPAL_A,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": WHEN,
    }


def test_a_promoted_authoring_write_names_review_decide_on_every_event(
    reviewed: Engine,
) -> None:
    """S-A: the primary and its derived Entity event both carry the stamp."""
    with unit(reviewed) as uow:
        EntityAuthoringService().archive(
            uow.entities,
            entity_id=REVIEWED_PERSON,
            expected_version=1,
            reason="accepted",
            idempotency_key="rcev-wp04-review-archive",
            **_context(),
            **PROMOTION,
        )
    (event,) = feed(reviewed, PRINCIPAL_A)
    _assert_promoted(event)


def test_a_promoted_directed_write_names_review_decide(reviewed: Engine) -> None:
    """S-B."""
    with unit(reviewed) as uow:
        EntityDirectedService().create_assignment(
            uow.entities,
            CreateEntityAssignment(
                entity_id=REVIEWED_PERSON,
                expected_entity_version=1,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                scope_entity_id=REVIEWED_PROJECT,
                expected_scope_version=1,
                idempotency_key="rcev-wp04-review-assignment",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=issue_identifier(IdKind.AUDIT),
            at=WHEN,
            **PROMOTION,
        )
    (event,) = feed(reviewed, PRINCIPAL_A)
    assert event["record_family"] == "entity_assignment"
    _assert_promoted(event)


def test_a_promoted_family_write_names_review_decide(reviewed: Engine) -> None:
    """S-C."""
    with unit(reviewed) as uow:
        EntityFamilyWriteService().add_name(
            uow.entities,
            AddEntityName(
                entity_id=REVIEWED_PERSON,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Reviewed Person",
                idempotency_key="rcev-wp04-review-name",
            ),
            principal_id=PRINCIPAL_A,
            audit_id=issue_identifier(IdKind.AUDIT),
            at=WHEN,
            **PROMOTION,
        )
    (event,) = feed(reviewed, PRINCIPAL_A)
    assert event["record_family"] == "entity_name"
    _assert_promoted(event)


def test_a_promoted_mention_creation_names_review_decide_on_both_events(
    reviewed: Engine,
) -> None:
    """G1-EM-002 under promotion: the Entity and the observation both carry the stamp."""
    with unit(reviewed) as uow:
        resolver = EntityResolutionService(uow.entities)

        def resolve(
            observation: EntityObservation, refused: frozenset[str], at: datetime
        ) -> EntityResolution:
            return resolver.resolve(
                observation.principal_id,
                ResolutionRequest(
                    raw_reference=observation.observed_value, at=at, refused_entity_ids=refused
                ),
            )

        EntityGovernanceService(uow.entities).resolve_mention(
            ResolveMentionCommand(
                principal_id=PRINCIPAL_A,
                observation_id=MENTION,
                expected_resolution_version=0,
                disposition=ResolutionDisposition.CREATE_NEW,
                idempotency_key="rcev-wp04-review-resolve",
                entity_type=EntityType.PERSON,
                canonical_name="Wholly Unmatched Person",
            ),
            resolve=resolve,
            at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            decided_by=PRINCIPAL_A,
            actor_class=ActorClass.REVIEW_PROMOTION,
        )
    created, observed = feed(reviewed, PRINCIPAL_A)
    assert (created["record_family"], observed["record_family"]) == (
        "entity",
        "entity_observation",
    )
    _assert_promoted(created)
    _assert_promoted(observed)
    assert observed["causation_event_id"] == created["event_id"]
