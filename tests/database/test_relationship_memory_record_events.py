"""WP-RE-04: Relationship Memory Record Events on a real database (RE-AC-050/051).

Marked `database` and routed to `database-current-head`. Each write goes through
`RelationshipMemoryService` over the production unit of work's
`relationship_memory` repository, whose stager is the unit of work's own:

* **M1-M4** -- create `created` (receipt the submission), revise `updated`,
  archive and restore `state_changed`, each at the aggregate `version`;
* **RE-AC-051 / OD-8** -- every event stores the classification of the
  version it commits, read from that version's row: a restricted memory's
  archive is restricted although the archive request carries no kind;
* **no statement** -- `changed_fields` never names the statement or the
  structured value;
* a replay stages nothing;
* the owning-memory read Phase 4B's context-link events use
  (`context_link_owner`, OD-2 (b)).

Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select

from my_pa.application.relationship_memory import (
    ArchiveMemoryCommand,
    CreateMemoryCommand,
    RelationshipMemoryService,
    ReviseMemoryCommand,
)
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.tables import (
    relationship_memories,
    relationship_memory_context_links,
    relationship_memory_submissions,
    relationship_memory_versions,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

PRINCIPAL: Final = "prn_rcevwp04cccc0001"
DANA: Final = "ent_rcevwp04cccc0001"
TOWER: Final = "ent_rcevwp04cccc0002"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
NOTE: Final = "Synthetic subject prefers written closeout updates."


def _entity(entity_id: str, name: str, kind: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=kind,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL, _entity(DANA, "Dana Synthetic", EntityType.PERSON))
        repository.create(PRINCIPAL, _entity(TOWER, "Synthetic Tower", EntityType.PROJECT))
    return migrated_engine


@contextmanager
def unit(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    with SqlAlchemyUnitOfWork(
        engine, audit=SqlAlchemyAuditSink(engine), relationship_memory_enabled=True
    ) as uow:
        yield uow  # type: ignore[misc]


def _create(engine: Engine, *, kind: MemoryKind, key: str, **extra: Any) -> str:  # noqa: ANN401
    fields: dict[str, Any] = {
        "principal_id": PRINCIPAL,
        "subject_entity_id": DANA,
        "memory_kind": kind,
        "statement": NOTE,
        "structured_value": None,
        "context_links": (),
        "pinned": False,
        "observed_at": None,
        "effective_from": None,
        "effective_to": None,
        "idempotency_key": key,
    }
    fields.update(extra)
    with unit(engine) as uow:
        admitted = RelationshipMemoryService().create(
            uow.relationship_memory, CreateMemoryCommand(**fields), at=WHEN
        )
    return admitted.receipt.memory_id


def _revise(engine: Engine, memory_id: str, *, expected: int, key: str, **extra: Any) -> None:  # noqa: ANN401
    fields: dict[str, Any] = {
        "principal_id": PRINCIPAL,
        "memory_id": memory_id,
        "expected_version": expected,
        "statement": NOTE + " Revised.",
        "memory_kind": None,
        "structured_value": None,
        "context_links": (),
        "pinned": None,
        "observed_at": None,
        "effective_from": None,
        "effective_to": None,
        "correction_reason": "reworded",
        "idempotency_key": key,
    }
    fields.update(extra)
    current_kind = extra.get("current_kind", MemoryKind.WORKING_PREFERENCE)
    fields.pop("current_kind", None)
    with unit(engine) as uow:
        RelationshipMemoryService().revise(
            uow.relationship_memory,
            ReviseMemoryCommand(**fields),
            at=WHEN,
            current_kind=current_kind,
        )


def _transition(engine: Engine, memory_id: str, *, expected: int, key: str, archive: bool) -> None:
    command = ArchiveMemoryCommand(
        principal_id=PRINCIPAL, memory_id=memory_id, expected_version=expected, idempotency_key=key
    )
    service = RelationshipMemoryService()
    with unit(engine) as uow:
        if archive:
            service.archive(uow.relationship_memory, command, at=WHEN)
        else:
            service.restore(uow.relationship_memory, command, at=WHEN)


def _committed_classifications(engine: Engine, memory_id: str) -> list[str]:
    with engine.connect() as connection:
        return [
            str(row.classification)
            for row in connection.execute(
                select(relationship_memory_versions.c.classification)
                .where(relationship_memory_versions.c.memory_id == memory_id)
                .order_by(relationship_memory_versions.c.version_number)
            )
        ]


def _submissions(engine: Engine, memory_id: str) -> list[str]:
    with engine.connect() as connection:
        return [
            str(row.submission_id)
            for row in connection.execute(
                select(relationship_memory_submissions.c.submission_id)
                .where(relationship_memory_submissions.c.memory_id == memory_id)
                .order_by(relationship_memory_submissions.c.aggregate_version)
            )
        ]


def test_the_memory_lifecycle_commits_one_event_per_write(staged: Engine) -> None:
    """M1-M4: created, updated, state_changed, state_changed, at the aggregate version."""
    memory_id = _create(staged, kind=MemoryKind.WORKING_PREFERENCE, key="rcev-wp04-memory-0001")
    _revise(staged, memory_id, expected=1, key="rcev-wp04-memory-revise", pinned=True)
    _transition(staged, memory_id, expected=2, key="rcev-wp04-memory-archive", archive=True)
    _transition(staged, memory_id, expected=3, key="rcev-wp04-memory-restore", archive=False)
    events = feed(staged, PRINCIPAL)
    assert [
        (e["record_family"], e["record_id"], e["event_kind"], e["record_version"]) for e in events
    ] == [
        ("relationship_memory", memory_id, "created", 1),
        ("relationship_memory", memory_id, "updated", 2),
        ("relationship_memory", memory_id, "state_changed", 3),
        ("relationship_memory", memory_id, "state_changed", 4),
    ]
    assert [e["changed_fields"] for e in events] == [
        [
            "current_version_id",
            "current_version_number",
            "lifecycle_state",
            "memory_kind",
            "pinned",
            "subject_entity_id",
        ],
        ["current_version_id", "current_version_number", "pinned", "version"],
        ["archived_at", "lifecycle_state", "version"],
        ["archived_at", "lifecycle_state", "version"],
    ]
    assert [e["source_capability"] for e in events] == [
        "relationship_memory.create",
        "relationship_memory.revise",
        "relationship_memory.archive",
        "relationship_memory.restore",
    ]
    assert [e["source_receipt_id"] for e in events] == _submissions(staged, memory_id)
    assert all(e["actor_class"] == "principal" for e in events)
    assert all(e["authority"] == "user_authored_private_note" for e in events)
    assert_gap_free(staged, PRINCIPAL)


def test_no_memory_event_names_the_statement(staged: Engine) -> None:
    """RE-AC-051: field-name tokens only, and never the narrative ones."""
    memory_id = _create(staged, kind=MemoryKind.WORKING_PREFERENCE, key="rcev-wp04-memory-0002")
    _revise(staged, memory_id, expected=1, key="rcev-wp04-memory-revise-2")
    for event in feed(staged, PRINCIPAL):
        assert not {"statement", "statement_text", "structured_value"} & set(
            event["changed_fields"]
        )
        assert NOTE not in str(event)


def test_every_memory_event_stores_its_committed_versions_classification(
    staged: Engine,
) -> None:
    """RE-AC-050/051 persistence (OD-8): the classification is the committed version's.

    A `sensitivity` memory is `restricted_local`; its archive request carries no
    kind (and so the least restrictive placeholder), and the event is still
    `restricted_local` because it is read from the version the archive leaves
    current. A revise to an ordinary kind commits a `private_local` version,
    and its event says so -- and names the classification as changed.
    """
    memory_id = _create(staged, kind=MemoryKind.SENSITIVITY, key="rcev-wp04-memory-0003")
    _transition(staged, memory_id, expected=1, key="rcev-wp04-memory-archive-3", archive=True)
    _transition(staged, memory_id, expected=2, key="rcev-wp04-memory-restore-3", archive=False)
    _revise(
        staged,
        memory_id,
        expected=3,
        key="rcev-wp04-memory-revise-3",
        memory_kind=MemoryKind.GENERAL_NOTE,
        current_kind=MemoryKind.SENSITIVITY,
    )
    events = feed(staged, PRINCIPAL)
    assert [e["classification"] for e in events] == [
        "restricted_local",
        "restricted_local",
        "restricted_local",
        "private_local",
    ]
    assert _committed_classifications(staged, memory_id) == ["restricted_local", "private_local"]
    assert events[3]["changed_fields"] == [
        "classification",
        "current_version_id",
        "current_version_number",
        "memory_kind",
        "version",
    ]


def test_a_memory_replay_commits_nothing(staged: Engine) -> None:
    _create(staged, kind=MemoryKind.WORKING_PREFERENCE, key="rcev-wp04-memory-replay")
    _create(staged, kind=MemoryKind.WORKING_PREFERENCE, key="rcev-wp04-memory-replay")
    assert len(feed(staged, PRINCIPAL)) == 1
    assert next_sequence(staged, PRINCIPAL) == 2


def test_a_context_links_owner_is_its_memory_at_its_current_version(staged: Engine) -> None:
    """The owning-memory read (link -> version -> memory) Phase 4B's link events use."""
    memory_id = _create(
        staged,
        kind=MemoryKind.WORKING_PREFERENCE,
        key="rcev-wp04-memory-context",
        context_links=({"target_type": "entity", "target_id": TOWER, "role": "applies_in"},),
    )
    _transition(staged, memory_id, expected=1, key="rcev-wp04-memory-context-a", archive=True)
    with staged.connect() as connection:
        link_id = connection.execute(
            select(relationship_memory_context_links.c.context_link_id).where(
                relationship_memory_context_links.c.target_id == TOWER
            )
        ).scalar_one()
        version = connection.execute(
            select(relationship_memories.c.version).where(
                relationship_memories.c.memory_id == memory_id
            )
        ).scalar_one()
    with unit(staged) as uow:
        owner = uow.relationship_memory.context_link_owner(PRINCIPAL, link_id)
        foreign = uow.relationship_memory.context_link_owner("prn_rcevwp04dddd0001", link_id)
    assert owner is not None
    assert (owner.memory_id, owner.version, owner.classification.value) == (
        memory_id,
        version,
        "private_local",
    )
    assert version == 2
    assert foreign is None
