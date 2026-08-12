"""The fail-closed Principal predicate every user-scoped query must pass through.

R0A's structural claim (MU-AC-01) is that a query cannot *accidentally* read
another Principal's rows. Accidents happen at call sites, so the guard lives
where statements are built, and it refuses rather than defaults:

* `require_principal_context` raises `MissingPrincipalContextError` when the
  context is absent. There is no anonymous fallback, no "all rows" mode, and
  no default Principal — no context means denied (fail closed).
* `principal_scoped` appends the partition predicate to a SELECT and raises
  `UnpartitionedTableError` when the table has no partition column at all. A
  table that cannot be partitioned cannot be queried through the user-scoped
  path, which is how "every durable user-scoped table carries a principal
  partition" becomes a property call sites cannot opt out of rather than a
  convention they are asked to follow. Two partition vocabularies exist and
  both are recognized: the identity plane's `principal_id` (UUID, WP-01) and
  the knowledge schema's text `principal_id`/`owner_principal_id`
  (`prn_...`, predating it). A text partition is compared against the
  context's capture-plane identifier, which `capture_context` derives through
  `domain.identity.binding` — and a context that carries no capture-plane
  identifier fails a text-partitioned query closed rather than matching
  nothing or everything.
* `principal_bound_values` stamps INSERT/UPDATE values with the context's
  identity in the partition column the *table* declares, and raises
  `CallerSuppliedPrincipalError` if the values already carry one — a write path
  must never accept identity from payload (MU-AC-02), including from its own
  composition bugs. It takes the table for the same reason
  `partition_criterion` does: the column name and the vocabulary are the
  table's to state, and a write path that named either itself would be the
  hand-written drift this module exists to remove.

The context object is deliberately tiny. It is constructed by the identity
service after claim validation and carried per request; nothing else is
allowed to mint one from a raw request field.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Column, ColumnElement, Select, Table
from sqlalchemy import Uuid as SqlUuid

from my_pa.domain.identity.binding import durable_principal_uuid
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError

__all__ = [
    "MissingPrincipalContextError",
    "PrincipalContext",
    "UnpartitionedTableError",
    "capture_context",
    "matching_partition_criterion",
    "partition_criterion",
    "principal_bound_values",
    "principal_scoped",
    "require_principal_context",
]


class MissingPrincipalContextError(Exception):
    """A data-access path was reached without a Principal context. Denied."""

    def __init__(self) -> None:
        super().__init__("no principal context: user-scoped data access is denied")


class UnpartitionedTableError(Exception):
    """A user-scoped query targeted a table without a `principal_id` column."""

    def __init__(self, table: str) -> None:
        super().__init__(
            f"table '{table}' carries no principal_id column and cannot be "
            "queried through the principal-scoped path"
        )
        self.table = table


@dataclass(frozen=True, slots=True)
class PrincipalContext:
    """The resolved Principal of one authenticated request.

    `capture_principal_id` is the same person in the knowledge schema's text
    vocabulary (`prn_...`), present when the context was derived from a
    capture-plane identifier via `capture_context`. It is `None` on a context
    built from the identity plane alone, and a text-partitioned query under
    such a context is refused rather than guessed at.
    """

    principal_id: UUID
    capture_principal_id: str | None = None


def capture_context(principal_id: str) -> PrincipalContext:
    """The context of one authenticated request, from its capture-plane identifier.

    The durable UUID is derived through `domain.identity.binding`, which is
    exact for the bound form and a stable digest otherwise — so the same
    identifier always lands in the same partition, and two identifiers never
    share one. This is a translation of an identity the composition root has
    already authenticated, never a validation of one.
    """
    return PrincipalContext(
        principal_id=durable_principal_uuid(principal_id),
        capture_principal_id=principal_id,
    )


def require_principal_context(context: PrincipalContext | None) -> PrincipalContext:
    """Return the context, or refuse the request entirely."""
    if context is None:
        raise MissingPrincipalContextError()
    return context


def _partition_binding(
    table: Table, context: PrincipalContext | None
) -> tuple[Column[str] | Column[UUID], UUID | str]:
    """The table's partition column and the value this context occupies it with.

    One resolver, used by every helper below, so the two partition vocabularies
    are recognised in exactly one place. Fails closed three times over: no
    context is refused, a table carrying neither partition column cannot be
    reached through this path at all, and a text-partitioned table under a
    context that carries no capture-plane identifier is refused rather than
    compared against — or stamped with — nothing.
    """
    resolved = require_principal_context(context)
    for name in ("principal_id", "owner_principal_id"):
        if name not in table.c:
            continue
        column = table.c[name]
        if isinstance(column.type, SqlUuid):
            return column, resolved.principal_id
        if resolved.capture_principal_id is None:
            raise MissingPrincipalContextError()
        return column, resolved.capture_principal_id
    raise UnpartitionedTableError(str(table.fullname))


def partition_criterion(table: Table, context: PrincipalContext | None) -> ColumnElement[bool]:
    """The one predicate that constrains `table` to the context's partition.

    Public because a statement builder that composes its own WHERE list
    (`persistence.capture_search`, `persistence.relationships`) needs the
    predicate itself rather than a wrapped SELECT — and a second, hand-written
    owner comparison there would be the drift `principal_scoped` exists to
    prevent. An UPDATE or DELETE reaches the partition through this function
    too, because neither is a `Select` and both are exactly as capable of
    rewriting another Principal's rows as a SELECT is of reading them.
    """
    column, value = _partition_binding(table, context)
    return column == value


def matching_partition_criterion(left: Table, right: Table) -> ColumnElement[bool]:
    """Require two user-scoped tables to occupy the same Principal partition."""
    left_column = next(
        (left.c[name] for name in ("principal_id", "owner_principal_id") if name in left.c),
        None,
    )
    right_column = next(
        (right.c[name] for name in ("principal_id", "owner_principal_id") if name in right.c),
        None,
    )
    if left_column is None:
        raise UnpartitionedTableError(str(left.fullname))
    if right_column is None:
        raise UnpartitionedTableError(str(right.fullname))
    if isinstance(left_column.type, SqlUuid) != isinstance(right_column.type, SqlUuid):
        raise UnpartitionedTableError(
            f"{left.fullname} and {right.fullname} use different Principal vocabularies"
        )
    return left_column == right_column


def principal_scoped[SelectT: Select[tuple]](  # type: ignore[type-arg]
    statement: SelectT,
    table: Table,
    context: PrincipalContext | None,
) -> SelectT:
    """Constrain a SELECT to the context's principal partition."""
    return statement.where(partition_criterion(table, context))


def principal_bound_values(
    values: dict[str, object],
    table: Table,
    context: PrincipalContext | None,
) -> dict[str, object]:
    """Stamp INSERT values with the context's identity in `table`'s partition column.

    Raises when the values already name the partition column: a write path that
    lets its payload name a partition is exactly the defect MU-AC-02 excludes,
    and "the caller passed it" and "this module composed it twice" are the same
    defect from the row's point of view.

    The table is a parameter rather than an assumption because the two partition
    vocabularies name their column differently (`principal_id` on the identity
    and relationship planes, `owner_principal_id` on the capture plane) and
    carry different types. Resolving both here is what stops a caller from
    writing the resolution out a second time.
    """
    column, value = _partition_binding(table, context)
    if column.name in values:
        raise CallerSuppliedPrincipalError(column.name)
    return {**values, column.name: value}
