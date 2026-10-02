"""The Record Event feed tables, behind the WP-RE-01 stager and writer ports.

Two tables are reached here and nowhere else: `record_event_sequences` (the
per-Principal allocator row) and `record_events` (the append-only feed).

**What a unit of work owns.** Each SQL unit of work holds one
`RecordEventBuffer` -- the transaction-local, in-memory, ordered list of drafts
its emitters stage. Nothing touches the database while a draft is staged. When
the unit of work leaves its block normally with a non-empty buffer, it calls
`flush_record_events` *before* it clears its connection: that is one allocator
statement and then the inserts, in stage order, as the last database work
before COMMIT (G1-TX-001; TRANSACTION matrix section 5). A block that raised
never reaches the flush, and the buffer is discarded with the transaction.

**The allocator is one row lock, never an advisory lock** (G1-TX-008).
`INSERT ... ON CONFLICT (principal_id) DO UPDATE SET next_sequence =
next_sequence + n RETURNING next_sequence - n` either creates the Principal's row
at `n + 1` (so the first batch starts at 1) or advances it under the row lock
PostgreSQL takes for the update, which is held to COMMIT. A second transaction
for the same Principal waits on that row and then reads the advanced value, so
two batches can never overlap, and a rolled-back batch leaves no advance behind.
`tests/architecture/test_record_event_allocator_uses_no_advisory_lock.py` holds
this module to that.

**The partition is reached through the guard.** Both INSERTs stamp the
Principal through `principal_bound_values` (`_bound`); the Principal is a
parameter taken from the buffer, never a value a draft writes for itself.

**The read half is one statement per question** (WP-RE-06). `page` returns a
keyset page *and* the high watermark from a single SQL statement -- two
`LATERAL` subqueries over the base table under one outer SELECT -- so under READ
COMMITTED both see one snapshot and the watermark can never pass an event the
page did not see (G1-TX-004, plan D-01). Every predicate is scoped through
`partition_criterion`, and a remote read (`include_restricted_memory=False`)
appends the OD-8 restricted-memory predicate -- the stored classification *or*
the memory's current version -- and its WP-RE-08 capture analogue (the stored
classification *or* the capture's current version) to both subqueries, so a withheld event cannot
reach a row, a truncation flag or the watermark. The sequence number orders the
page and never leaves this module.

**Routing is read by the same statement** (RECR-1, MR-R01). For the families
whose `record_id` is a child row, the outer SELECT adds `routing_record_id`: a
`CASE` over the page's family, each branch a keyed scalar subquery on that child
table's primary key, under the caller's partition, selecting only its owner
column. It adds no statement and no lock, reads the page's own snapshot, and
names the *current* owner -- an Entity merge that reparents a child moves the
routing of its earlier events too. Only the key and owner columns of those
tables are named (MR-R09).

**Failures are translated** exactly as `unit_of_work._read` translates a
statement failure: an unreachable server or a timeout is
`EvidenceUnavailableError`, anything else the store refused is
`RepositoryFailureError`. A buffer holding two Principals is refused before any
statement runs.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Final, cast

from sqlalchemy import (
    ColumnElement,
    Connection,
    FromClause,
    Row,
    Table,
    and_,
    case,
    exists,
    insert,
    literal,
    not_,
    null,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from my_pa.contracts.ports import (
    EvidenceUnavailableError,
    RecordEventFeedItem,
    RecordEventPage,
    RecordEventReader,
    RecordEventStager,
    RecordEventWriter,
    RepositoryFailureError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.record_events import (
    RECORD_EVENT_ROUTING,
    RecordEventActorClass,
    RecordEventAuthority,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.infrastructure.persistence import IsolationLevelError
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    constraint_categories,
    entity_addresses,
    entity_aliases,
    entity_assignments,
    entity_communication_methods,
    entity_external_identifiers,
    entity_names,
    entity_observations,
    entity_person_organization_affiliations,
    entity_project_participations,
    entity_relationships,
    record_event_sequences,
    record_events,
    relationship_memories,
    relationship_memory_versions,
    task_comments,
)

__all__ = [
    "RecordEventBuffer",
    "SqlRecordEventReader",
    "SqlRecordEventWriter",
    "feed_reader_memory_relation_names",
    "flush_record_events",
]

#: The allocator's one conflict target: the Principal's own sequence row.
_SEQUENCE_KEY: Final = (record_event_sequences.c.principal_id,)


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


def feed_reader_memory_relation_names() -> tuple[str, str]:
    """SQL names of the two memory relations `_restricted_memory` reaches.

    The Record Event role provisioner grants runtime ``SELECT`` on these names.
    The names stay here so that grant does not import the tables into the
    control-plane module.
    """
    return (relationship_memories.name, relationship_memory_versions.name)


class RecordEventBuffer(RecordEventStager):
    """One transaction's staged drafts, in stage order.

    Held by a unit of work and reset by its `__enter__`; `drain` hands the
    drafts to the flush and empties the buffer in one step, so every exit --
    committed, rolled back or failed -- leaves it empty.
    """

    def __init__(self) -> None:
        self._drafts: list[RecordEventDraft] = []

    def stage(self, draft: RecordEventDraft) -> None:
        if not isinstance(draft, RecordEventDraft):
            raise TypeError("only a RecordEventDraft can be staged")
        self._drafts.append(draft)

    @property
    def pending_count(self) -> int:
        return len(self._drafts)

    def reset(self) -> None:
        """Forget every staged draft (a new transaction begins)."""
        self._drafts.clear()

    def drain(self) -> tuple[RecordEventDraft, ...]:
        """Return the staged drafts in order and empty the buffer."""
        drafts = tuple(self._drafts)
        self._drafts.clear()
        return drafts


class SqlRecordEventWriter(RecordEventWriter):
    """The allocator and the ordered insert, on one transaction's connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def allocate(self, principal_id: str, count: int) -> int:
        if isinstance(count, bool) or count < 1:
            raise ValueError("an allocator batch holds at least one event")
        statement = (
            pg_insert(record_event_sequences)
            .values(_bound(record_event_sequences, principal_id, {"next_sequence": count + 1}))
            .on_conflict_do_update(
                index_elements=_SEQUENCE_KEY,
                set_={"next_sequence": record_event_sequences.c.next_sequence + count},
            )
            .returning(record_event_sequences.c.next_sequence - count)
        )
        first = self._connection.execute(statement).scalar_one()
        return int(first)

    def insert(self, first_sequence_number: int, drafts: Sequence[RecordEventDraft]) -> None:
        principal_id = _single_principal(drafts)
        for offset, draft in enumerate(drafts):
            self._connection.execute(
                insert(record_events).values(
                    _bound(
                        record_events,
                        principal_id,
                        {
                            "event_id": draft.event_id,
                            "sequence_number": first_sequence_number + offset,
                            "record_family": draft.record_family.value,
                            "record_id": draft.record_id,
                            "event_kind": draft.event_kind.value,
                            "record_version": draft.record_version,
                            "changed_fields": list(draft.changed_fields),
                            "source_capability": draft.source_capability,
                            "source_receipt_id": draft.source_receipt_id,
                            "actor_class": draft.actor_class.value,
                            "authority": (
                                None if draft.authority is None else draft.authority.value
                            ),
                            "classification": draft.classification.value,
                            "correlation_id": draft.correlation_id,
                            "causation_event_id": draft.causation_event_id,
                            "occurred_at": draft.occurred_at,
                        },
                    )
                )
            )


def _single_principal(drafts: Sequence[RecordEventDraft]) -> str:
    """The one Principal a batch belongs to, or a refusal.

    The only read of a draft's `principal_id` in this module. Every emitter
    builds its drafts from the server-resolved `Authorization`, and every row is
    then stamped through `principal_bound_values` from this single value, so a
    batch naming two Principals is refused rather than written across both.
    """
    principals = {draft.principal_id for draft in drafts}
    if len(principals) != 1:
        raise RepositoryFailureError("a record event batch must belong to exactly one Principal")
    return next(iter(principals))


def flush_record_events(writer: RecordEventWriter, drafts: Sequence[RecordEventDraft]) -> None:
    """Sequence `drafts` in one batch and insert them in stage order, translated.

    Called only from a unit of work's `__exit__` (and, in WP-RE-04, the one
    re-enrichment worker transaction), before the connection is cleared. An
    empty batch is a caller error: the unit of work skips the flush instead.
    """
    if not drafts:
        raise ValueError("an empty buffer is not flushed")
    principal_id = _single_principal(drafts)
    try:
        first = writer.allocate(principal_id, len(drafts))
        writer.insert(first, drafts)
    except (OperationalError, InterfaceError):
        failure: Exception = EvidenceUnavailableError("the store could not be written")
    except (SQLAlchemyError, IsolationLevelError):
        failure = RepositoryFailureError("the request could not be completed")
    else:
        return
    raise failure


# --- WP-RE-06: the feed reader ------------------------------------------------

#: The two aliases the one `page` statement reads the feed through.
_PAGE: Final = cast(Table, record_events.alias("feed_page"))
_WATERMARK: Final = cast(Table, record_events.alias("feed_watermark"))

#: WP-RE-08: the two aliases the capture predicate reads `capture_versions`
#: through -- a restricted version, and a later version that would supersede it.
#: MR-12: only `capture_id`, `version_number` and `classification` (plus the
#: partition) are ever named on either.
_CAPTURE_VERSION: Final = cast(Table, capture_versions.alias("capture_version"))
_LATER_CAPTURE_VERSION: Final = cast(Table, capture_versions.alias("later_capture_version"))

#: The public columns of a feed item, in the order `_item` reads them.
_ITEM_COLUMNS: Final = (
    "event_id",
    "record_family",
    "record_id",
    "event_kind",
    "record_version",
    "changed_fields",
    "source_capability",
    "source_receipt_id",
    "actor_class",
    "authority",
    "occurred_at",
    "recorded_at",
    "causation_event_id",
)


#: RECR-1 (MR-R01): where each routed family's owner lives -- the child table,
#: its primary key (what the event's `record_id` names) and the one owner column
#: the routing reference is read from. Keys only (MR-R09): no other column of
#: these tables is ever named here, and
#: `tests/security/test_record_events_carry_no_payload.py` holds the reader to
#: that. An affiliation routes to its person end (MR-R05 (i)).
_ROUTING_OWNERS: Final = (
    (RecordEventFamily.TASK_COMMENT, task_comments.c.comment_id, task_comments.c.task_id),
    (
        RecordEventFamily.CONSTRAINT_CATEGORY,
        constraint_categories.c.category_id,
        constraint_categories.c.project_id,
    ),
    (
        RecordEventFamily.ENTITY_IDENTIFIER,
        entity_external_identifiers.c.identifier_id,
        entity_external_identifiers.c.entity_id,
    ),
    (RecordEventFamily.ENTITY_ALIAS, entity_aliases.c.alias_id, entity_aliases.c.entity_id),
    (
        RecordEventFamily.ENTITY_ASSIGNMENT,
        entity_assignments.c.assignment_id,
        entity_assignments.c.entity_id,
    ),
    (
        RecordEventFamily.ENTITY_RELATIONSHIP,
        entity_relationships.c.relationship_id,
        entity_relationships.c.from_entity_id,
    ),
    (
        RecordEventFamily.ENTITY_OBSERVATION,
        entity_observations.c.observation_id,
        entity_observations.c.entity_id,
    ),
    (RecordEventFamily.ENTITY_NAME, entity_names.c.entity_name_id, entity_names.c.entity_id),
    (
        RecordEventFamily.ENTITY_ADDRESS,
        entity_addresses.c.entity_address_id,
        entity_addresses.c.entity_id,
    ),
    (
        RecordEventFamily.ENTITY_COMMUNICATION_METHOD,
        entity_communication_methods.c.communication_method_id,
        entity_communication_methods.c.entity_id,
    ),
    (
        RecordEventFamily.ENTITY_PROJECT_PARTICIPATION,
        entity_project_participations.c.participation_id,
        entity_project_participations.c.participant_entity_id,
    ),
    (
        RecordEventFamily.PERSON_ORGANIZATION_AFFILIATION,
        entity_person_organization_affiliations.c.affiliation_id,
        entity_person_organization_affiliations.c.person_entity_id,
    ),
)


def _routing_record_id(page: FromClause, principal_id: str) -> ColumnElement[Any]:
    """RECR-1: the routed event's current owner id, or NULL, inside the page statement.

    One `CASE` branch per routed family, each a keyed scalar subquery on the
    child's primary key under the caller's partition, selecting only the owner
    column. No row lock, no second statement: it reads the page's own snapshot.
    A missing child or a NULL owner (an unresolved observation) is NULL.
    """
    context = capture_context(principal_id)
    return case(
        *(
            (
                page.c.record_family == family.value,
                select(owner)
                .where(
                    partition_criterion(owner.table, context),
                    key == page.c.record_id,
                )
                .scalar_subquery(),
            )
            for family, key, owner in _ROUTING_OWNERS
        ),
        else_=null(),
    )


def _restricted_memory(event: Table, principal_id: str) -> ColumnElement[bool]:
    """OD-8 (i): the event is a memory event a remote caller must not see.

    Either its stored classification is `restricted_local`, or the memory it
    names is *currently* restricted: an `EXISTS` from the memory's
    `current_version_id` to that version's classification. Both memory tables
    are reached through the caller's own partition.
    """
    context = capture_context(principal_id)
    restricted = Classification.RESTRICTED_LOCAL.value
    currently_restricted = exists(
        select(literal(1))
        .select_from(relationship_memories)
        .join(
            relationship_memory_versions,
            relationship_memory_versions.c.memory_version_id
            == relationship_memories.c.current_version_id,
        )
        .where(
            partition_criterion(relationship_memories, context),
            partition_criterion(relationship_memory_versions, context),
            relationship_memories.c.memory_id == event.c.record_id,
            relationship_memory_versions.c.classification == restricted,
        )
    )
    return and_(
        event.c.record_family == RecordEventFamily.RELATIONSHIP_MEMORY.value,
        or_(event.c.classification == restricted, currently_restricted),
    )


def _restricted_capture(event: Table, principal_id: str) -> ColumnElement[bool]:
    """WP-RE-08 (the OD-8 (i) analogue, OD-W8-4/MR-12): a capture event withheld remotely.

    Either its stored classification is `restricted_local`, or the capture it
    names is *currently* restricted: its current version -- the one no later
    version supersedes in number -- is `restricted_local`. Both aliases are
    reached through the caller's own partition, and name only the join keys and
    `classification`: never the text, a digest or the whole row.
    """
    context = capture_context(principal_id)
    restricted = Classification.RESTRICTED_LOCAL.value
    later = exists(
        select(literal(1))
        .select_from(_LATER_CAPTURE_VERSION)
        .where(
            partition_criterion(_LATER_CAPTURE_VERSION, context),
            _LATER_CAPTURE_VERSION.c.capture_id == _CAPTURE_VERSION.c.capture_id,
            _LATER_CAPTURE_VERSION.c.version_number > _CAPTURE_VERSION.c.version_number,
        )
    )
    currently_restricted = exists(
        select(literal(1))
        .select_from(_CAPTURE_VERSION)
        .where(
            partition_criterion(_CAPTURE_VERSION, context),
            _CAPTURE_VERSION.c.capture_id == event.c.record_id,
            _CAPTURE_VERSION.c.classification == restricted,
            not_(later),
        )
    )
    return and_(
        event.c.record_family == RecordEventFamily.CAPTURE.value,
        or_(event.c.classification == restricted, currently_restricted),
    )


def _withheld_remotely(event: Table, principal_id: str) -> ColumnElement[bool]:
    """Everything a remote caller must not see: the memory and capture predicates."""
    return or_(_restricted_memory(event, principal_id), _restricted_capture(event, principal_id))


def _visible(
    event: Table,
    principal_id: str,
    families: frozenset[RecordEventFamily],
    include_restricted_memory: bool,
) -> list[ColumnElement[bool]]:
    """The one visibility predicate every feed read applies to `event`.

    `include_restricted_memory` keeps its name (OD-W8-10) and now also gates
    restricted captures: false for a remote caller.
    """
    criteria: list[ColumnElement[bool]] = [
        partition_criterion(event, capture_context(principal_id)),
        event.c.record_family.in_(sorted(family.value for family in families)),
    ]
    if not include_restricted_memory:
        criteria.append(not_(_withheld_remotely(event, principal_id)))
    return criteria


def _item(row: Row[Any]) -> RecordEventFeedItem:
    mapping = row._mapping
    authority = mapping["authority"]
    family = RecordEventFamily(mapping["record_family"])
    routing = mapping["routing_record_id"]
    return RecordEventFeedItem(
        event_id=mapping["event_id"],
        record_family=family,
        record_id=mapping["record_id"],
        event_kind=RecordEventKind(mapping["event_kind"]),
        record_version=mapping["record_version"],
        changed_fields=tuple(mapping["changed_fields"]),
        source_capability=mapping["source_capability"],
        source_receipt_id=mapping["source_receipt_id"],
        actor_class=RecordEventActorClass(mapping["actor_class"]),
        authority=None if authority is None else RecordEventAuthority(authority),
        occurred_at=mapping["occurred_at"],
        recorded_at=mapping["recorded_at"],
        causation_event_id=mapping["causation_event_id"],
        routing_family=None if routing is None else RECORD_EVENT_ROUTING[family],
        routing_record_id=routing,
    )


def _translated[ResultT](work: Callable[[], ResultT]) -> ResultT:
    """Run one read, translating a store failure as `flush_record_events` does."""
    try:
        return work()
    except (OperationalError, InterfaceError):
        failure: Exception = EvidenceUnavailableError("the store could not be read")
    except (SQLAlchemyError, IsolationLevelError):
        failure = RepositoryFailureError("the request could not be completed")
    raise failure


class SqlRecordEventReader(RecordEventReader):
    """The feed reader, on one transaction's connection."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def page(
        self,
        *,
        principal_id: str,
        after_sequence: int,
        families: frozenset[RecordEventFamily],
        include_restricted_memory: bool,
        limit: int,
    ) -> RecordEventPage:
        if not families:
            raise ValueError("an empty family set is answered without a statement")
        if isinstance(limit, bool) or limit < 1:
            raise ValueError("a page holds at least one event")
        page = (
            select(*(_PAGE.c[name] for name in _ITEM_COLUMNS), _PAGE.c.sequence_number)
            .where(
                *_visible(_PAGE, principal_id, families, include_restricted_memory),
                _PAGE.c.sequence_number > after_sequence,
            )
            .order_by(_PAGE.c.sequence_number.asc())
            .limit(limit + 1)
            .lateral("page")
        )
        watermark = (
            select(_WATERMARK.c.event_id.label("high_watermark_event_id"))
            .where(*_visible(_WATERMARK, principal_id, families, include_restricted_memory))
            .order_by(_WATERMARK.c.sequence_number.desc())
            .limit(1)
            .lateral("watermark")
        )
        anchor = select(literal(1).label("anchor")).subquery("anchor")
        statement = (
            select(
                watermark.c.high_watermark_event_id,
                *(page.c[name] for name in _ITEM_COLUMNS),
                _routing_record_id(page, principal_id).label("routing_record_id"),
            )
            .select_from(
                anchor.outerjoin(watermark, true()).outerjoin(page, true()),
            )
            .order_by(page.c.sequence_number.asc())
        )
        rows = _translated(lambda: self._connection.execute(statement).all())
        high_watermark = rows[0]._mapping["high_watermark_event_id"] if rows else None
        return RecordEventPage(
            rows=tuple(_item(row) for row in rows if row._mapping["event_id"] is not None),
            high_watermark_event_id=high_watermark,
        )

    def resolve_position(self, *, principal_id: str, event_id: str) -> int | None:
        statement = select(record_events.c.sequence_number).where(
            partition_criterion(record_events, capture_context(principal_id)),
            record_events.c.event_id == event_id,
        )
        position = _translated(lambda: self._connection.execute(statement).scalar_one_or_none())
        return None if position is None else int(position)

    def visible_event_ids(
        self,
        *,
        principal_id: str,
        event_ids: frozenset[str],
        families: frozenset[RecordEventFamily],
        include_restricted_memory: bool,
    ) -> frozenset[str]:
        if not event_ids or not families:
            return frozenset()
        statement = select(record_events.c.event_id).where(
            *_visible(record_events, principal_id, families, include_restricted_memory),
            record_events.c.event_id.in_(sorted(event_ids)),
        )
        found = _translated(lambda: self._connection.execute(statement).scalars().all())
        return frozenset(found)
