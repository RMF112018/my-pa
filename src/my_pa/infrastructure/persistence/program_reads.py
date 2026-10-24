"""The Program read unit of work: one read-only snapshot on its own pool (S4 6.3).

Record lineage S4 (ADR-015; S4 contract section 6.3, R4-F05). A Program read
-- `programs.members.resolve`, `programs.overview`, or the commit-time recompute
of a Program reference -- must read in **one** `REPEATABLE READ, READ ONLY`
transaction, and it cannot be the request's own: `ApplicationService._run`
opens that `UnitOfWork` at READ COMMITTED before authorization and keeps it, so
several statements on it are several snapshots. Nor can it be a second checkout
from the work pool, which deadlocks at `C = P` (`bootstrap/gateway.py`).

So it is drawn from a **third engine**, built by `bootstrap/gateway.py` only
while `MY_PA_PROGRAM_REPORTING_ENABLED` is on, from which nothing else draws.
A connection of that pool is held only by a request already holding a work
connection, never while waiting for a work or audit connection, and a READ ONLY
snapshot read never waits on a row lock, so the wait-for graph has no cycle.

The transaction never writes (PostgreSQL refuses a write in a read-only
transaction) and `__exit__` always rolls back. Every statement it issues is
Principal-scoped.
"""

from __future__ import annotations

from types import TracebackType
from typing import Final

from sqlalchemy import Connection, Engine, bindparam, text
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from my_pa.contracts.ports import (
    ConstraintManagementRepository,
    ProgramMembershipRepository,
    ProgramReadUnavailableError,
    ProgramReadUnitOfWork,
    ProgramSnapshot,
)
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.program_membership import (
    SqlProgramMembershipRepository,
    program_statement,
)

__all__ = ["SqlAlchemyProgramReadUnitOfWork"]

#: S4 section 3.4: the first query takes the snapshot, and reads its own instant
#: and the Principal's committed lineage horizon `H` in that one statement.
_SNAPSHOT: Final = text(
    "SELECT statement_timestamp() AS source_cutoff_at, "
    "(SELECT s.last_marked_at FROM knowledge.lineage_commit_sequences s "
    "WHERE s.principal_id = :principal_id) AS lineage_known_at"
).bindparams(bindparam("principal_id"))


class SqlAlchemyProgramReadUnitOfWork(ProgramReadUnitOfWork):
    """One read-only `REPEATABLE READ` transaction on the Program read engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Connection | None = None
        self._snapshot: ProgramSnapshot | None = None
        self._principal_id: str | None = None

    def __enter__(self) -> ProgramReadUnitOfWork:
        if self._connection is not None:
            raise RuntimeError("this unit of work is already inside a transaction")
        connection = self._checkout()
        try:
            connection.begin()
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        self._snapshot = None
        self._principal_id = None
        return self

    def _checkout(self) -> Connection:
        """A Program-pool connection, or `ProgramReadUnavailableError` (S4 section 6.3).

        A checkout that outwaits the Program engine's checkout timeout is
        `pool_unavailable`: the Program reads answer `unavailable`.
        """
        exhausted = False
        try:
            return self._engine.connect().execution_options(
                isolation_level="REPEATABLE READ", postgresql_readonly=True
            )
        except PoolTimeoutError:
            exhausted = True
        if exhausted:
            raise ProgramReadUnavailableError("pool_unavailable")
        raise AssertionError("unreachable")  # pragma: no cover

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        connection = self._connection
        self._connection = None
        self._snapshot = None
        self._principal_id = None
        if connection is None:
            return
        try:
            connection.rollback()
        finally:
            connection.close()

    @property
    def connection(self) -> Connection:
        """The snapshot connection (for the S4 repositories built on it)."""
        if self._connection is None:
            raise RuntimeError("the Program read unit of work is not inside a transaction")
        return self._connection

    def snapshot(self, principal_id: str) -> ProgramSnapshot:
        if self._snapshot is not None:
            if principal_id != self._principal_id:
                raise RuntimeError("one Program snapshot serves one Principal")
            return self._snapshot
        connection = self.connection
        row = program_statement(
            lambda: connection.execute(_SNAPSHOT, {"principal_id": principal_id}).one()
        )
        self._snapshot = ProgramSnapshot(
            source_cutoff_at=row.source_cutoff_at, lineage_known_at=row.lineage_known_at
        )
        self._principal_id = principal_id
        return self._snapshot

    def set_statement_timeout(self, milliseconds: int) -> None:
        if type(milliseconds) is not int or milliseconds <= 0:
            raise ValueError("a statement timeout is a positive number of milliseconds")
        # `SET LOCAL` takes no bind parameter; the value is a validated integer.
        self.connection.execute(text(f"SET LOCAL statement_timeout = {milliseconds}"))

    @property
    def constraints(self) -> ConstraintManagementRepository:
        return SqlConstraintManagementRepository(self.connection)

    @property
    def program_membership(self) -> ProgramMembershipRepository:
        return SqlProgramMembershipRepository(self.connection)
