"""The durable audit sink, and the one transaction rule that makes it durable.

**The asymmetry this closes.** WP-4A opened one transaction around the decision
and the work. A *denied* request returned out of that block normally, so the
audit event recording the refusal committed; an *allowed* request whose handler
then failed raised out of it, so the audit event recording the authorization was
rolled back with the work. The result was that a failed security-relevant action
left no trace while a refused one did — the wrong way round, and the defect
`D-34` assigns here.

**How it closes.** `SqlAlchemyAuditSink.record` does not write on the caller's
connection. It takes its own connection from the engine, inserts, and commits,
before returning to the caller whose transaction is still open. PostgreSQL has
no autonomous transaction and a savepoint dies with the transaction that owns
it, so a second connection is not one implementation of "survives a rollback" —
it is the only one.

Two properties follow, and they are the two halves of
`module-boundaries.md` section 5.6.

*The audit survives the work.* The event is committed before the handler that
could fail has run, so no later rollback can reach it. What the row then says is
that this principal was **authorized** for this capability, which is the
security-relevant fact and remains true whether or not the work succeeded. It
does not claim the work committed, and nothing here writes a second event to say
whether it did — `sources.status` and the job plane are where that is recorded.

*A failed audit fails the request closed.* `record` raises rather than returning
on failure, and nothing between here and the caller swallows it: the exception
leaves the caller's `with` block, which rolls the work back, and
`ApplicationService.invoke` turns it into a failure response. An audit event
that cannot be written is a failure to surface, never a warning to swallow, so
there is no `try` around the insert that returns normally.

**Ordering, stated plainly.** Because the audit commits first, a work
transaction that fails to commit afterwards leaves an audit event describing an
authorization whose work never landed. That is the correct direction of the
trade: `module-boundaries.md` section 10 requires that a partial commit must not
create work without authority or evidence, and evidence without work satisfies
that strictly more than committing the two together did. The literal "one
transaction" wording of that section is what `D-34` overrides, not the invariant
behind it.

**What a caller has to give this.** An engine that can supply a connection while
another connection is already held. `create_database_engine` builds a pool of
five with no overflow, so a composition root running more than five requests
concurrently would find the audit write queued behind them and eventually
failing — closed, but unavailable. That bound belongs to whoever composes a
concurrent transport; the worker this package ships is single-threaded and holds
one connection at a time.
"""

from __future__ import annotations

from sqlalchemy import Connection, Engine
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError

from my_pa.contracts.ports import AuditSink, EvidenceUnavailableError, RepositoryFailureError
from my_pa.domain.audit.events import AuditEvent
from my_pa.infrastructure.persistence.tables import audit_events

__all__ = ["SqlAlchemyAuditSink", "record_audit_event"]


def record_audit_event(connection: Connection, event: AuditEvent) -> None:
    """Insert one audit event on `connection`, whose transaction the caller owns.

    A statement, like every other function in this package. The field mapping is
    written out rather than derived from the dataclass, so a field added to
    `AuditEvent` has to be considered here rather than silently dropped.

    Two of the event's fields are deliberately not stored. `item_count` and
    `duration_ms` have no writer anywhere — `authorize` sets neither and the
    mismatch branch sets none of the three — so a column for either would hold
    zero forever and could not be told apart from a measured zero. They are
    stored when something measures them.
    """
    connection.execute(
        audit_events.insert().values(
            audit_id=event.audit_id,
            correlation_id=event.correlation_id,
            principal_id=event.principal_id,
            capability=event.capability.value,
            purpose=event.purpose.value,
            outcome=event.outcome.value,
            policy_version=event.policy_version,
            denial_reason=None if event.denial_reason is None else event.denial_reason.value,
            scope_source_id_count=event.scope_source_id_count,
            recorded_at=event.recorded_at,
        )
    )


class SqlAlchemyAuditSink(AuditSink):
    """An `AuditSink` that commits each event in a transaction of its own.

    Constructed with an engine rather than a connection, which is the whole
    mechanism: a sink handed the caller's connection could only ever be as
    durable as the caller's transaction.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def record(self, event: AuditEvent) -> None:
        """Persist one redacted audit event, or raise.

        `engine.begin()` commits on a normal exit and rolls back on an
        exception, so there is no partially written event and no path that
        returns having written nothing.

        The failure is translated into the port's vocabulary for the reason the
        rest of this package translates: an application use case may not import
        `infrastructure`, so it cannot catch a `SQLAlchemyError`, and letting one
        out of here would carry the statement and its bound parameters — every
        one of which is an audit field — into whatever rendered the traceback.
        Classified by retryability and nothing else, and raised outside the
        handler so the driver's exception is not left in `__context__`.
        """
        try:
            with self._engine.begin() as connection:
                record_audit_event(connection, event)
        except (OperationalError, InterfaceError):
            # The server is unreachable or the connection died. Conditionally
            # retryable, and the request still fails: an audit that has not been
            # written is not an audit.
            failure: Exception = EvidenceUnavailableError("the audit event could not be recorded")
        except SQLAlchemyError:
            # A constraint refused the row, a column is missing, the table is not
            # there. Retrying writes the same row and fails the same way.
            failure = RepositoryFailureError("the audit event could not be recorded")
        else:
            return
        raise failure
