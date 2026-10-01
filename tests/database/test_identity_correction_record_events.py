"""WP-RE-04 Phase 4B (T-15): merge and split Record Events on a real database.

Marked `database` and routed to `database-current-head`. Every merge and split
runs through `IdentityCorrectionService` inside the production
`SqlAlchemyUnitOfWork`, built exactly as the handlers build it -- with the unit
of work's own stager -- so the feed checked here is the one the exit flush
committed with the canonical change (RE-AC-048/049, RE-AC-070):

* **the causation root** (S-001, T-007): the first staged event of a batch is
  the `entity` event of the lowest absorbed `entity_id` -- the redirect on a
  merge, its restore on a split -- and every other event names it; no
  `relationship_memory` event is ever a cause, including in a split whose
  source merge moved memories;
* **one event per changed record**, at the version the row now holds: a
  family at its new version, an observation at its unchanged feed version
  (T-002, OD-2 (a)), a memory once per batch with the union of what changed at
  its post-batch version (OD-2 (b), S-006) -- including a memory whose only
  change is a retargeted context link;
* **G1-EM-017**: a split restore's `record_version` is the row's value, which
  is the source merge's `after_state.version + 1` and not the split ledger's;
* **the reassignments** (S5, OD-2 (e), V-001), including a survivor
  self-assignment: version-only for a versioned family, nothing for an
  observation;
* **concurrency**: a merge racing a family write, and the split's deferred
  source-operation foreign key checked at COMMIT after the allocator;
* **the consumer rule** for equal-version events (OD-2).

Every identity is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import AddEntityName
from my_pa.application.entity_family_writes import EntityFamilyWriteService
from my_pa.application.errors import ConflictError
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
    SplitCommand,
    SplitDisposition,
    SplitPreviewCommand,
)
from my_pa.application.relationship_memory import (
    ArchiveMemoryCommand,
    CreateMemoryCommand,
    RelationshipMemoryService,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    NameTypeCode,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityObservation,
    ObservationKind,
)
from my_pa.domain.relationship.identity_correction import (
    AmbiguityDisposition,
    IdentityEffectFamily,
)
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

SCHEMA: Final = "knowledge"
PRINCIPAL: Final = "prn_rcevwp04eeee0001"
SURVIVOR: Final = "ent_rcevwp04eeee0001"
MERGED_ONE: Final = "ent_rcevwp04eeee0002"
MERGED_TWO: Final = "ent_rcevwp04eeee0003"
TOWER: Final = "ent_rcevwp04eeee0009"
ALIAS: Final = "eals_rcevwp04eeee0001"
MENTION: Final = "eobs_rcevwp04eeee0001"
LATER_MENTION: Final = "eobs_rcevwp04eeee0002"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
REASON: Final = "two synthetic records describe one synthetic person"
SPLIT_REASON: Final = "the synthetic identity correction was wrong"


# ---- fixtures -----------------------------------------------------------------


def _entity(entity_id: str, name: str, kind: EntityType = EntityType.PERSON) -> Entity:
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


def _observation(observation_id: str, entity_id: str) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Casey Synthetic",
        normalized_value=normalize_name("Casey Synthetic"),
        source_id="src_rcevwp04eeee0001",
        source_object_id="obj_rcevwp04eeee0001",
        source_version_id="ver_rcevwp04eeee0001",
        observed_at=WHEN,
        recorded_at=WHEN,
        entity_id=entity_id,
    )


def _memory(connection: Any, subject: str, key: str, link_to: str | None = None) -> str:  # noqa: ANN401
    return (
        RelationshipMemoryService()
        .create(
            SqlRelationshipMemoryRepository(connection),
            CreateMemoryCommand(
                principal_id=PRINCIPAL,
                subject_entity_id=subject,
                memory_kind=MemoryKind.GENERAL_NOTE,
                statement="Synthetic context-bound note.",
                structured_value=None,
                context_links=(
                    ({"target_type": "entity", "target_id": link_to, "role": "applies_in"},)
                    if link_to
                    else ()
                ),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                idempotency_key=key,
            ),
            at=WHEN,
        )
        .receipt.memory_id
    )


@pytest.fixture
def staged(migrated_engine: Engine) -> Iterator[dict[str, Any]]:
    """A bare survivor, two duplicates with children, and memories on both sides.

    Written without a feed (repositories outside a unit of work stage into a
    buffer nothing flushes), so every event below is one a merge or split
    committed.

    * `MERGED_ONE` holds an alias, a name and an observation;
    * memory A's subject is `MERGED_ONE` and its context link names
      `MERGED_TWO`, so a merge both reparents it and retargets its link;
    * memory B's subject is the unrelated `TOWER` and its only link names
      `MERGED_ONE`, so a merge changes nothing but that link.
    """
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL, _entity(SURVIVOR, "Casey Synthetic"))
        repository.create(PRINCIPAL, _entity(MERGED_ONE, "Casey Synthetic Two"))
        repository.create(PRINCIPAL, _entity(MERGED_TWO, "Casey Synthetic Three"))
        repository.create(PRINCIPAL, _entity(TOWER, "Synthetic Tower", EntityType.PROJECT))
        repository.record_alias(
            PRINCIPAL,
            EntityAlias(
                alias_id=ALIAS,
                entity_id=MERGED_ONE,
                alias_type=AliasType.NICKNAME,
                normalized_value=normalize_name("Cas"),
                display_value="Cas",
                principal_id=PRINCIPAL,
                state=AliasState.ACTIVE,
            ),
        )
        repository.record_observation(PRINCIPAL, _observation(MENTION, MERGED_ONE))
        name = EntityFamilyWriteService().add_name(
            repository,
            AddEntityName(
                entity_id=MERGED_ONE,
                name_type_code=NameTypeCode.LEGAL,
                display_value="Casey Synthetic Two",
                idempotency_key="rcev-wp04b-name",
            ),
            principal_id=PRINCIPAL,
            audit_id=issue_identifier(IdKind.AUDIT),
            at=WHEN,
        )
        memory_a = _memory(connection, MERGED_ONE, "rcev-wp04b-memory-a", link_to=MERGED_TWO)
        memory_b = _memory(connection, TOWER, "rcev-wp04b-memory-b", link_to=MERGED_ONE)
    assert feed(migrated_engine, PRINCIPAL) == []
    yield {
        "engine": migrated_engine,
        "name": name.record_id,
        "memory_a": memory_a,
        "memory_b": memory_b,
    }


@contextmanager
def unit(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    with SqlAlchemyUnitOfWork(
        engine, audit=SqlAlchemyAuditSink(engine), relationship_memory_enabled=True
    ) as uow:
        yield uow  # type: ignore[misc]


def _service(uow: SqlAlchemyUnitOfWork) -> IdentityCorrectionService:
    """Built exactly as `ApplicationService._entities_merge` builds it."""
    return IdentityCorrectionService(
        uow.entities, uow.relationship_memory, stager=uow.record_events
    )


def _merge(engine: Engine, merged: tuple[str, ...], *, key: str = "rcev-wp04b-merge") -> Any:  # noqa: ANN401
    with unit(engine) as uow:
        report = _service(uow).preview(
            MergePreviewCommand(
                principal_id=PRINCIPAL,
                survivor_entity_id=SURVIVOR,
                expected_survivor_version=1,
                merged_away=tuple((entity_id, 1) for entity_id in merged),
                reason=REASON,
            ),
            at=WHEN,
            requested_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with unit(engine) as uow:
        return _service(uow).apply(
            MergeCommand(
                principal_id=PRINCIPAL,
                preview_id=report.preview.preview_id,
                preview_digest=report.preview.preview_digest,
                idempotency_key=key,
                reason=REASON,
            ),
            at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            performed_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )


def _split_preview(engine: Engine, source_operation_id: str) -> Any:  # noqa: ANN401
    with unit(engine) as uow:
        return _service(uow).split_preview(
            SplitPreviewCommand(
                principal_id=PRINCIPAL,
                source_identity_operation_id=source_operation_id,
                reason=SPLIT_REASON,
            ),
            at=WHEN + timedelta(minutes=2),
            requested_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )


def _split_apply(
    engine: Engine,
    report: Any,  # noqa: ANN401
    dispositions: tuple[SplitDisposition, ...] = (),
) -> Any:  # noqa: ANN401
    with unit(engine) as uow:
        return _service(uow).split_apply(
            SplitCommand(
                principal_id=PRINCIPAL,
                preview_id=report.preview.preview_id,
                preview_digest=report.preview.preview_digest,
                idempotency_key="rcev-wp04b-split",
                reason=SPLIT_REASON,
                dispositions=dispositions,
            ),
            at=WHEN + timedelta(minutes=3),
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            performed_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )


_ROWS: Final = {
    "entity": ("entities", "entity_id", "version"),
    "entity_alias": ("entity_aliases", "alias_id", "version"),
    "entity_name": ("entity_names", "entity_name_id", "version"),
    "relationship_memory": ("relationship_memories", "memory_id", "version"),
    "entity_observation": ("entity_observations", "observation_id", "resolution_version"),
}


def _row_version(engine: Engine, family: str, record_id: str) -> int:
    table, column, version = _ROWS[family]
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT {version} FROM {SCHEMA}.{table} WHERE {column} = :id"),  # noqa: S608
                {"id": record_id},
            ).scalar_one()
        )


def _assert_rooted_batch(events: list[dict[str, Any]], root_id: str) -> None:
    """S-001/T-007: root first; every other event caused by it; no memory is a cause."""
    assert events, "the batch committed no event"
    root, *rest = events
    assert (root["record_family"], root["record_id"], root["event_kind"]) == (
        "entity",
        root_id,
        "state_changed",
    )
    assert root["causation_event_id"] is None
    assert all(event["causation_event_id"] == root["event_id"] for event in rest)
    memory_ids = {e["event_id"] for e in events if e["record_family"] == "relationship_memory"}
    assert not memory_ids & {event["causation_event_id"] for event in events}
    assert len({event["correlation_id"] for event in events}) == 1


def _assert_versions_are_the_rows(engine: Engine, events: list[dict[str, Any]]) -> None:
    """Every event names its record at the version the row holds now; an observation
    at its feed version, `resolution_version + 1` (T-002, the feed floor)."""
    for event in events:
        family = event["record_family"]
        if family not in _ROWS:
            continue
        held = _row_version(engine, family, event["record_id"])
        expected = held + 1 if family == "entity_observation" else held
        assert event["record_version"] == expected, (family, event["record_id"])


def _effect_ids(engine: Engine, operation_id: str) -> set[str]:
    with engine.connect() as connection:
        return {
            str(row[0])
            for row in connection.execute(
                text(
                    f"SELECT effect_id FROM {SCHEMA}.entity_identity_effects "  # noqa: S608
                    "WHERE identity_operation_id = :id"
                ),
                {"id": operation_id},
            )
        }


# ---- merge ------------------------------------------------------------------------


def test_a_multi_entity_merge_is_rooted_at_its_lowest_absorbed_redirect(
    staged: dict[str, Any],
) -> None:
    """T-007, M3-M7: the lowest redirect first, one event per changed record."""
    engine = staged["engine"]
    receipt = _merge(engine, (MERGED_TWO, MERGED_ONE))
    events = feed(engine, PRINCIPAL)
    _assert_rooted_batch(events, min(MERGED_ONE, MERGED_TWO))
    _assert_versions_are_the_rows(engine, events)
    by_record = {(e["record_family"], e["record_id"]): e for e in events}
    assert len(by_record) == len(events), "one event per changed record"
    assert set(by_record) == {
        ("entity", MERGED_ONE),
        ("entity", MERGED_TWO),
        ("entity_alias", ALIAS),
        ("entity_name", staged["name"]),
        ("entity_observation", MENTION),
        ("relationship_memory", staged["memory_a"]),
        ("relationship_memory", staged["memory_b"]),
    }
    assert by_record[("entity", MERGED_TWO)]["event_kind"] == "state_changed"
    assert by_record[("entity", MERGED_ONE)]["changed_fields"] == [
        "status",
        "superseded_by_entity_id",
        "version",
    ]
    assert by_record[("entity_alias", ALIAS)]["event_kind"] == "updated"
    assert by_record[("entity_alias", ALIAS)]["changed_fields"] == ["entity_id", "version"]
    observation = by_record[("entity_observation", MENTION)]
    assert (observation["event_kind"], observation["record_version"]) == ("updated", 1)
    assert observation["changed_fields"] == ["entity_id"]
    # S-006: memory A moved its subject and its link in one batch -- one event,
    # the union, at its post-batch version.
    memory_a = by_record[("relationship_memory", staged["memory_a"])]
    assert memory_a["changed_fields"] == ["context_links", "subject_entity_id", "version"]
    assert memory_a["record_version"] == 2
    # OD-2 (b): memory B's only change is its retargeted link -- an event at the
    # unchanged version.
    memory_b = by_record[("relationship_memory", staged["memory_b"])]
    assert (memory_b["changed_fields"], memory_b["record_version"]) == (["context_links"], 1)
    assert all(e["source_capability"] == "entities.merge" for e in events)
    assert all(e["actor_class"] == "principal" for e in events)
    assert {e["source_receipt_id"] for e in events} <= _effect_ids(
        engine, receipt.operation.identity_operation_id
    )
    assert_gap_free(engine, PRINCIPAL)


def test_a_merge_replay_commits_nothing(staged: dict[str, Any]) -> None:
    """The replay returns before `_perform`, so it stages nothing."""
    engine = staged["engine"]
    with unit(engine) as uow:
        report = _service(uow).preview(
            MergePreviewCommand(
                principal_id=PRINCIPAL,
                survivor_entity_id=SURVIVOR,
                expected_survivor_version=1,
                merged_away=((MERGED_ONE, 1),),
                reason=REASON,
            ),
            at=WHEN,
            requested_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    command = MergeCommand(
        principal_id=PRINCIPAL,
        preview_id=report.preview.preview_id,
        preview_digest=report.preview.preview_digest,
        idempotency_key="rcev-wp04b-merge-replay",
        reason=REASON,
    )
    receipts = []
    for _ in range(2):
        with unit(engine) as uow:
            receipts.append(
                _service(uow).apply(
                    command,
                    at=WHEN,
                    correlation_id=issue_identifier(IdKind.CORRELATION),
                    audit_id=issue_identifier(IdKind.AUDIT),
                    performed_by=PRINCIPAL,
                    actor_class=ActorClass.USER,
                    has_operator_authority=True,
                )
            )
        if not receipts[-1].replayed:
            committed = feed(engine, PRINCIPAL)
    assert [receipt.replayed for receipt in receipts] == [False, True]
    assert feed(engine, PRINCIPAL) == committed
    assert next_sequence(engine, PRINCIPAL) == len(committed) + 1


# ---- split ------------------------------------------------------------------------


def test_a_split_is_rooted_at_the_restore_matching_the_merge_root(
    staged: dict[str, Any],
) -> None:
    """S-001: the redirect-restore first although `_inverse_drafts` reverses the
    ledger (memory effects would otherwise lead); no memory event is a cause."""
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE, MERGED_TWO))
    merged_count = len(feed(engine, PRINCIPAL))
    receipt = _split_apply(engine, _split_preview(engine, merge.operation.identity_operation_id))
    events = feed(engine, PRINCIPAL)[merged_count:]
    _assert_rooted_batch(events, min(MERGED_ONE, MERGED_TWO))
    _assert_versions_are_the_rows(engine, events)
    by_record = {(e["record_family"], e["record_id"]): e for e in events}
    assert len(by_record) == len(events)
    assert ("relationship_memory", staged["memory_a"]) in by_record
    # S3c: the context-link restore alone is a memory `updated`.
    assert ("relationship_memory", staged["memory_b"]) in by_record
    memory_b = by_record[("relationship_memory", staged["memory_b"])]
    assert (memory_b["event_kind"], memory_b["changed_fields"]) == ("updated", ["context_links"])
    assert all(e["source_capability"] == "entities.split" for e in events)
    assert {e["source_receipt_id"] for e in events} <= _effect_ids(
        engine, receipt.operation.identity_operation_id
    )
    assert_gap_free(engine, PRINCIPAL)


def test_a_split_restore_names_the_rows_version_not_the_split_ledgers(
    staged: dict[str, Any],
) -> None:
    """G1-EM-017: a restored name advances from its post-merge version (2 -> 3).

    The split ledger's `after_state` restates the pre-merge version (1) for this
    family; the event must carry what the row holds.
    """
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE,))
    merged_count = len(feed(engine, PRINCIPAL))
    receipt = _split_apply(engine, _split_preview(engine, merge.operation.identity_operation_id))
    events = feed(engine, PRINCIPAL)[merged_count:]
    (name,) = [e for e in events if e["record_family"] == "entity_name"]
    assert name["record_version"] == _row_version(engine, "entity_name", staged["name"]) == 3
    (ledger,) = [
        effect
        for effect in receipt.effects
        if effect.family is IdentityEffectFamily.NAME and effect.record_id == staged["name"]
    ]
    assert ledger.after_state["version"] != name["record_version"]


def _disturb(engine: Engine) -> None:
    """A merged child changes and a new child appears while the identities are one."""
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.entity_aliases "  # noqa: S608
                "SET version = version + 1, updated_at = :at WHERE alias_id = :alias_id"
            ),
            {"at": WHEN + timedelta(minutes=1), "alias_id": ALIAS},
        )
        SqlEntityRepository(connection).record_observation(
            PRINCIPAL, _observation(LATER_MENTION, SURVIVOR)
        )


def _assign_all(report: Any, target: str) -> tuple[SplitDisposition, ...]:  # noqa: ANN401
    return tuple(
        SplitDisposition(
            ambiguity.ambiguity_id, AmbiguityDisposition.ASSIGN_TO_ENTITY, target_entity_id=target
        )
        for ambiguity in report.ambiguities
    )


def test_assign_to_entity_reassignments_follow_the_restores(staged: dict[str, Any]) -> None:
    """S5a/S5b (OD-2 (e), D-23): one event per reassigned row whose target differs --
    the alias at its new version, the observation at its feed version."""
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE,))
    _disturb(engine)
    merged_count = len(feed(engine, PRINCIPAL))
    report = _split_preview(engine, merge.operation.identity_operation_id)
    assert {a.record_id for a in report.ambiguities} >= {ALIAS, LATER_MENTION}
    receipt = _split_apply(engine, report, _assign_all(report, MERGED_ONE))
    events = feed(engine, PRINCIPAL)[merged_count:]
    _assert_rooted_batch(events, MERGED_ONE)
    _assert_versions_are_the_rows(engine, events)
    with unit(engine) as uow:
        asked = [
            ambiguity.record_id
            for ambiguity in uow.entities.preview_ambiguities(PRINCIPAL, report.preview.preview_id)
        ]
    tail = events[-2:]
    # After every restore, in the order the reassignments were resolved.
    assert [e["record_id"] for e in tail] == [r for r in asked if r in {ALIAS, LATER_MENTION}]
    alias = next(e for e in tail if e["record_id"] == ALIAS)
    assert (alias["event_kind"], alias["changed_fields"]) == ("updated", ["entity_id", "version"])
    mention = next(e for e in tail if e["record_id"] == LATER_MENTION)
    assert (mention["changed_fields"], mention["record_version"]) == (["entity_id"], 1)
    assert {e["source_receipt_id"] for e in tail} == {receipt.operation.identity_operation_id}


def test_a_survivor_self_assignment_is_version_only_or_nothing(staged: dict[str, Any]) -> None:
    """V-001: the alias's version still advances (a version-only `updated`); the
    observation changes nothing and emits nothing."""
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE,))
    _disturb(engine)
    merged_count = len(feed(engine, PRINCIPAL))
    report = _split_preview(engine, merge.operation.identity_operation_id)
    alias_version = _row_version(engine, "entity_alias", ALIAS)
    _split_apply(engine, report, _assign_all(report, SURVIVOR))
    events = feed(engine, PRINCIPAL)[merged_count:]
    reassigned = [e for e in events if e["record_id"] in {ALIAS, LATER_MENTION}]
    assert [(e["record_id"], e["changed_fields"], e["record_version"]) for e in reassigned] == [
        (ALIAS, ["version"], alias_version + 1)
    ]
    assert _row_version(engine, "entity_alias", ALIAS) == alias_version + 1


EDGE: Final = "erel_rcevwp04eeee0001"


def test_a_multi_column_reassignment_names_exactly_the_column_that_moved(
    staged: dict[str, Any],
) -> None:
    """MR-07: a relationship created against the survivor after the merge names it
    in `from_entity_id` only (its `to_entity_id` is `TOWER`). Reassigned, its event
    names exactly that column and `version` -- not every entity-reference column."""
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE,))
    with engine.begin() as connection:
        SqlEntityRepository(connection).record_relationship(
            PRINCIPAL,
            EntityRelationship(
                relationship_id=EDGE,
                from_entity_id=SURVIVOR,
                relationship_type=EntityRelationshipType.AFFILIATED_WITH,
                to_entity_id=TOWER,
                principal_id=PRINCIPAL,
            ),
        )
    merged_count = len(feed(engine, PRINCIPAL))
    report = _split_preview(engine, merge.operation.identity_operation_id)
    assert EDGE in {ambiguity.record_id for ambiguity in report.ambiguities}
    _split_apply(
        engine,
        report,
        tuple(
            SplitDisposition(
                ambiguity.ambiguity_id,
                AmbiguityDisposition.ASSIGN_TO_ENTITY,
                target_entity_id=MERGED_ONE,
            )
            if ambiguity.record_id == EDGE
            else SplitDisposition(ambiguity.ambiguity_id, AmbiguityDisposition.LEAVE_UNRESOLVED)
            for ambiguity in report.ambiguities
        ),
    )
    (edge,) = [e for e in feed(engine, PRINCIPAL)[merged_count:] if e["record_id"] == EDGE]
    assert (edge["record_family"], edge["event_kind"]) == ("entity_relationship", "updated")
    assert edge["changed_fields"] == ["from_entity_id", "version"]
    with engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT from_entity_id, to_entity_id, version FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE relationship_id = :id"
            ),
            {"id": EDGE},
        ).one()
    assert (row.from_entity_id, row.to_entity_id) == (MERGED_ONE, TOWER)
    assert edge["record_version"] == row.version


# ---- concurrency --------------------------------------------------------------------


def _timed_engine(engine: Engine, lock_timeout: str) -> Engine:
    return create_engine(
        engine.url.render_as_string(hide_password=False),
        connect_args={"options": f"-c lock_timeout={lock_timeout} -c timezone=UTC"},
    )


class _WriterAbandonedError(Exception):
    """Raised inside the family write's block to roll it back on purpose."""


@pytest.mark.parametrize(
    "writer_commits", [True, False], ids=["writer-commits", "writer-rolls-back"]
)
def test_a_merge_racing_a_family_write_serialises_without_deadlock(
    staged: dict[str, Any], writer_commits: bool
) -> None:
    """P2a T-15: a family write on a merge participant is open when the merge
    applies; the merge waits on it (serialised, never 40P01 or a lock timeout).

    If the write commits, the merge then sees a world its preview did not show
    and is refused -- committing no event. If the write rolls back, the merge
    proceeds and commits its rooted batch. Either way the feed is gap-free."""
    engine = staged["engine"]
    timed = _timed_engine(engine, "20s")
    try:
        with unit(timed) as uow:
            report = _service(uow).preview(
                MergePreviewCommand(
                    principal_id=PRINCIPAL,
                    survivor_entity_id=SURVIVOR,
                    expected_survivor_version=1,
                    merged_away=((MERGED_ONE, 1),),
                    reason=REASON,
                ),
                at=WHEN,
                requested_by=PRINCIPAL,
                actor_class=ActorClass.USER,
                has_operator_authority=True,
            )
        opened = threading.Event()
        release = threading.Event()
        failures: list[BaseException] = []

        def family_write() -> None:
            try:
                with unit(timed) as uow:
                    EntityFamilyWriteService().add_name(
                        uow.entities,
                        AddEntityName(
                            entity_id=MERGED_ONE,
                            name_type_code=NameTypeCode.DISPLAY,
                            display_value="Casey Racing",
                            idempotency_key="rcev-wp04b-race-name",
                        ),
                        principal_id=PRINCIPAL,
                        audit_id=issue_identifier(IdKind.AUDIT),
                        at=WHEN,
                    )
                    opened.set()
                    release.wait(timeout=30)
                    if not writer_commits:
                        raise _WriterAbandonedError
            except _WriterAbandonedError:
                pass
            except BaseException as failure:
                failures.append(failure)
                opened.set()

        writer = threading.Thread(target=family_write)
        writer.start()
        assert opened.wait(timeout=30)
        merged: list[Any] = []

        def merge() -> None:
            try:
                with unit(timed) as uow:
                    merged.append(
                        _service(uow).apply(
                            MergeCommand(
                                principal_id=PRINCIPAL,
                                preview_id=report.preview.preview_id,
                                preview_digest=report.preview.preview_digest,
                                idempotency_key="rcev-wp04b-race-merge",
                                reason=REASON,
                            ),
                            at=WHEN,
                            correlation_id=issue_identifier(IdKind.CORRELATION),
                            audit_id=issue_identifier(IdKind.AUDIT),
                            performed_by=PRINCIPAL,
                            actor_class=ActorClass.USER,
                            has_operator_authority=True,
                        )
                    )
            except BaseException as failure:
                failures.append(failure)

        merger = threading.Thread(target=merge)
        merger.start()
        merger.join(timeout=2)
        blocked = merger.is_alive()
        release.set()
        writer.join(timeout=60)
        merger.join(timeout=60)
        assert not writer.is_alive() and not merger.is_alive()
    finally:
        timed.dispose()
    assert blocked, "the merge did not wait for the open family write"
    for failure in failures:
        assert isinstance(failure, ConflictError), repr(failure)  # never 40P01 or a timeout
    assert len(merged) + len(failures) == 1
    events = feed(engine, PRINCIPAL)
    capabilities = [e["source_capability"] for e in events]
    assert ("entities.names.add" in capabilities) is writer_commits
    assert bool(merged) is not writer_commits
    if merged:
        _assert_rooted_batch(
            [e for e in events if e["source_capability"] == "entities.merge"], MERGED_ONE
        )
    else:
        assert not [e for e in events if e["source_capability"] == "entities.merge"]
    assert_gap_free(engine, PRINCIPAL)


def _source_operation_row_lock(engine: Engine, operation_id: str, mode: str) -> Any:  # noqa: ANN401
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(
        text(
            f"SELECT 1 FROM {SCHEMA}.entity_identity_operations "  # noqa: S608
            f"WHERE identity_operation_id = :id FOR {mode}"
        ),
        {"id": operation_id},
    )
    return connection, transaction


def test_the_splits_deferred_source_fk_takes_only_a_key_share_at_commit(
    staged: dict[str, Any],
) -> None:
    """P2a §4.4: the deferred `a_split_names_a_source_operation_of_its_principal`
    is checked at COMMIT, after the allocator. A reader holding KEY SHARE on the
    source merge does not block it."""
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE,))
    report = _split_preview(engine, merge.operation.identity_operation_id)
    connection, transaction = _source_operation_row_lock(
        engine, merge.operation.identity_operation_id, "KEY SHARE"
    )
    timed = _timed_engine(engine, "5s")
    try:
        receipt = _split_apply(timed, report)
    finally:
        transaction.rollback()
        connection.close()
        timed.dispose()
    assert receipt.operation.source_identity_operation_id == merge.operation.identity_operation_id
    assert [e for e in feed(engine, PRINCIPAL) if e["source_capability"] == "entities.split"]
    assert_gap_free(engine, PRINCIPAL)


def test_a_split_refused_at_its_deferred_fk_commits_no_event(staged: dict[str, Any]) -> None:
    """The deferred check waits on a conflicting lock at COMMIT; the refusal rolls
    the whole split back, its staged events with it, and advances no sequence."""
    engine = staged["engine"]
    merge = _merge(engine, (MERGED_ONE,))
    report = _split_preview(engine, merge.operation.identity_operation_id)
    before = feed(engine, PRINCIPAL)
    sequence = next_sequence(engine, PRINCIPAL)
    connection, transaction = _source_operation_row_lock(
        engine, merge.operation.identity_operation_id, "UPDATE"
    )
    timed = _timed_engine(engine, "2s")
    try:
        with pytest.raises((DBAPIError, Exception)):
            _split_apply(timed, report)
    finally:
        transaction.rollback()
        connection.close()
        timed.dispose()
    assert feed(engine, PRINCIPAL) == before
    assert next_sequence(engine, PRINCIPAL) == sequence


# ---- the consumer rule (OD-2) --------------------------------------------------------


def test_equal_version_events_are_distinct_and_only_the_sequence_orders_them(
    staged: dict[str, Any],
) -> None:
    """OD-2 (published consumer rule): a memory whose only change is a retargeted
    link is re-announced at its unchanged version. The two events share a
    `(record_id, record_version)` and differ in identity and sequence -- so a
    consumer that dedup-skipped an equal version would miss a real change. It
    must reread on every event, ordered by `sequence_number` alone."""
    engine = staged["engine"]
    memory_b = staged["memory_b"]
    with unit(engine) as uow:
        RelationshipMemoryService().archive(
            uow.relationship_memory,
            ArchiveMemoryCommand(
                principal_id=PRINCIPAL,
                memory_id=memory_b,
                expected_version=1,
                idempotency_key="rcev-wp04b-consumer-archive",
            ),
            at=WHEN,
        )
    _merge(engine, (MERGED_ONE,))
    announced = [e for e in feed(engine, PRINCIPAL) if e["record_id"] == memory_b]
    assert [(e["event_kind"], e["record_version"]) for e in announced] == [
        ("state_changed", 2),
        ("updated", 2),
    ]
    first, second = announced
    assert first["event_id"] != second["event_id"]
    assert first["sequence_number"] < second["sequence_number"]
    assert first["changed_fields"] != second["changed_fields"]
