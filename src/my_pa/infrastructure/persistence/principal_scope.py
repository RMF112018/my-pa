"""The fail-closed Principal predicate every user-scoped query must pass through.

R0A's structural claim (MU-AC-01) is that a query cannot *accidentally* read
another Principal's rows. Accidents happen at call sites, so the guard lives
where statements are built, and it refuses rather than defaults:

* `require_principal_context` raises `MissingPrincipalContextError` when the
  context is absent. There is no anonymous fallback, no "all rows" mode, and
  no default Principal — no context means denied (fail closed).
* `principal_scoped` appends `table.c.principal_id == context.principal_id`
  to a SELECT and raises `UnpartitionedTableError` when the table has no
  `principal_id` column at all. A table that cannot be partitioned cannot be
  queried through the user-scoped path, which is how "every durable
  user-scoped table carries `principal_id`" becomes a property call sites
  cannot opt out of rather than a convention they are asked to follow.
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

from sqlalchemy import Select, Table

from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError

__all__ = [
    "MissingPrincipalContextError",
    "PrincipalContext",
    "UnpartitionedTableError",
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
    """The resolved Principal of one authenticated request."""

    principal_id: UUID


def require_principal_context(context: PrincipalContext | None) -> PrincipalContext:
    """Return the context, or refuse the request entirely."""
    if context is None:
        raise MissingPrincipalContextError()
    return context


def principal_scoped[SelectT: Select[tuple]](  # type: ignore[type-arg]
    statement: SelectT,
    table: Table,
    context: PrincipalContext | None,
) -> SelectT:
    """Constrain a SELECT to the context's `principal_id` partition."""
    resolved = require_principal_context(context)
    if "principal_id" not in table.c:
        raise UnpartitionedTableError(str(table.fullname))
    return statement.where(table.c.principal_id == resolved.principal_id)


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
