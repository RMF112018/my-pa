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

**Failures are translated** exactly as `unit_of_work._read` translates a
statement failure: an unreachable server or a timeout is
`EvidenceUnavailableError`, anything else the store refused is
`RepositoryFailureError`. A buffer holding two Principals is refused before any
statement runs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from sqlalchemy import Connection, Table, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from my_pa.contracts.ports import (
    EvidenceUnavailableError,
    RecordEventStager,
    RecordEventWriter,
    RepositoryFailureError,
)
from my_pa.domain.record_events import RecordEventDraft
from my_pa.infrastructure.persistence import IsolationLevelError
from my_pa.infrastructure.persistence.principal_scope import (
    capture_context,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import record_event_sequences, record_events

__all__ = [
    "RecordEventBuffer",
    "SqlRecordEventWriter",
    "flush_record_events",
]

#: The allocator's one conflict target: the Principal's own sequence row.
_SEQUENCE_KEY: Final = (record_event_sequences.c.principal_id,)


def _bound(table: Table, principal_id: str, values: dict[str, object]) -> dict[str, object]:
    return principal_bound_values(values, table, capture_context(principal_id))


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
