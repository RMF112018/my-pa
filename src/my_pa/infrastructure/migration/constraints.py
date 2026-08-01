"""Validating the foreign keys the load could not assume.

SQLite does not enforce a declared foreign key unless `PRAGMA foreign_keys=ON`,
which the legacy application never set. Its 270 declared constraints are
therefore declarations about intent, not guarantees about content, and the corpus
may hold rows whose parent is missing.

So the migration adds every foreign key `NOT VALID` — binding on new rows,
silent about old ones — and then tries to validate each one here. A constraint
that validates becomes an ordinary enforced foreign key. One that does not is
left `NOT VALID`, and its orphan count is reported.

Nothing is deleted and nothing is invented to make a constraint pass. A missing
parent is a fact about the source that predates this migration, and the
migration's job is to surface it (OD-017).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.migration.identifiers import qualify, quote

_UNVALIDATED = """
SELECT n.nspname, c.relname, con.conname,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum),
       pn.nspname, p.relname,
       (SELECT array_agg(a.attname ORDER BY k.ord)
          FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum)
  FROM pg_constraint con
  JOIN pg_class c ON c.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN pg_class p ON p.oid = con.confrelid
  JOIN pg_namespace pn ON pn.oid = p.relnamespace
 WHERE con.contype = 'f' AND NOT con.convalidated AND n.nspname = ANY(:schemas)
 ORDER BY n.nspname, c.relname, con.conname
"""


@dataclass(frozen=True)
class ForeignKeyOutcome:
    """One constraint's result. Names and counts only."""

    schema: str
    table: str
    constraint: str
    referenced: str
    validated: bool
    orphan_rows: int
    error_class: str | None


@dataclass(frozen=True)
class _Unvalidated:
    schema: str
    table: str
    constraint: str
    columns: tuple[str, ...]
    parent_schema: str
    parent_table: str
    parent_columns: tuple[str, ...]


def _pending(connection: Connection, schemas: Sequence[str]) -> tuple[_Unvalidated, ...]:
    rows = connection.execute(text(_UNVALIDATED), {"schemas": list(schemas)}).all()
    return tuple(
        _Unvalidated(
            schema=str(row[0]),
            table=str(row[1]),
            constraint=str(row[2]),
            columns=tuple(str(name) for name in row[3]),
            parent_schema=str(row[4]),
            parent_table=str(row[5]),
            parent_columns=tuple(str(name) for name in row[6]),
        )
        for row in rows
    )


def _orphan_count(connection: Connection, pending: _Unvalidated) -> int:
    """Count child rows whose parent is missing, under MATCH SIMPLE semantics.

    A row with any NULL in the key is exempt from the constraint, so it is not an
    orphan and is not counted.
    """
    child = qualify(pending.schema, pending.table)
    parent = qualify(pending.parent_schema, pending.parent_table)
    present = " AND ".join(f"c.{quote(column)} IS NOT NULL" for column in pending.columns)
    joined = " AND ".join(
        f"p.{quote(parent_column)} = c.{quote(column)}"
        for column, parent_column in zip(pending.columns, pending.parent_columns, strict=True)
    )
    # S608: every identifier is a quoted catalogue name; there is no input here.
    statement = (
        f"SELECT count(*) FROM {child} AS c WHERE {present} "  # noqa: S608
        f"AND NOT EXISTS (SELECT 1 FROM {parent} AS p WHERE {joined})"
    )
    return int(connection.execute(text(statement)).scalar_one())


def validate_foreign_keys(engine: Engine, schemas: Sequence[str]) -> tuple[ForeignKeyOutcome, ...]:
    """Try to validate every `NOT VALID` foreign key, reporting what will not.

    Each constraint is attempted in its own transaction so one failure does not
    take the rest with it.
    """
    with engine.connect() as connection:
        pending = _pending(connection, schemas)

    outcomes: list[ForeignKeyOutcome] = []
    for constraint in pending:
        relation = qualify(constraint.schema, constraint.table)
        referenced = f"{constraint.parent_schema}.{constraint.parent_table}"
        statement = f"ALTER TABLE {relation} VALIDATE CONSTRAINT {quote(constraint.constraint)}"
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except DBAPIError as exc:
            with engine.connect() as connection:
                orphans = _orphan_count(connection, constraint)
            outcomes.append(
                ForeignKeyOutcome(
                    schema=constraint.schema,
                    table=constraint.table,
                    constraint=constraint.constraint,
                    referenced=referenced,
                    validated=False,
                    orphan_rows=orphans,
                    # Only the class name: a driver message quotes the offending
                    # key value, which may be personal data.
                    error_class=type(exc.orig).__name__ if exc.orig else type(exc).__name__,
                )
            )
        else:
            outcomes.append(
                ForeignKeyOutcome(
                    schema=constraint.schema,
                    table=constraint.table,
                    constraint=constraint.constraint,
                    referenced=referenced,
                    validated=True,
                    orphan_rows=0,
                    error_class=None,
                )
            )
    return tuple(outcomes)
