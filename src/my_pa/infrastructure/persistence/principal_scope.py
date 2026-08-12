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
* `principal_bound_values` stamps INSERT values with the context's
  `principal_id` and raises `CallerSuppliedPrincipalError` if the values
  already carry one — a write path must never accept identity from payload
  (MU-AC-02), including from its own composition bugs.

The context object is deliberately tiny. It is constructed by the identity
service after claim validation and carried per request; nothing else is
allowed to mint one from a raw request field.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, Select, Table
from sqlalchemy import Uuid as SqlUuid

from my_pa.domain.identity.binding import durable_principal_uuid
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError

__all__ = [
    "MissingPrincipalContextError",
    "PrincipalContext",
    "UnpartitionedTableError",
    "capture_context",
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


def partition_criterion(table: Table, context: PrincipalContext | None) -> ColumnElement[bool]:
    """The one predicate that constrains `table` to the context's partition.

    Public because a statement builder that composes its own WHERE list
    (`persistence.capture_search`) needs the predicate itself rather than a
    wrapped SELECT — and a second, hand-written owner comparison there would be
    the drift `principal_scoped` exists to prevent. Fails closed three times
    over: no context is refused, a table carrying neither partition column
    cannot be queried through this path at all, and a text-partitioned table
    under a context that carries no capture-plane identifier is refused rather
    than compared against nothing.
    """
    resolved = require_principal_context(context)
    for name in ("principal_id", "owner_principal_id"):
        if name not in table.c:
            continue
        column = table.c[name]
        if isinstance(column.type, SqlUuid):
            return column == resolved.principal_id
        if resolved.capture_principal_id is None:
            raise MissingPrincipalContextError()
        return column == resolved.capture_principal_id
    raise UnpartitionedTableError(str(table.fullname))


def principal_scoped[SelectT: Select[tuple]](  # type: ignore[type-arg]
    statement: SelectT,
    table: Table,
    context: PrincipalContext | None,
) -> SelectT:
    """Constrain a SELECT to the context's principal partition."""
    return statement.where(partition_criterion(table, context))


def principal_bound_values(
    values: dict[str, object],
    context: PrincipalContext | None,
) -> dict[str, object]:
    """Stamp INSERT/UPDATE values with the context's `principal_id`.

    Raises when the values already carry a `principal_id`: a write path that
    lets its payload name a partition is exactly the defect MU-AC-02 excludes.
    """
    resolved = require_principal_context(context)
    if "principal_id" in values:
        raise CallerSuppliedPrincipalError("principal_id")
    return {**values, "principal_id": resolved.principal_id}
