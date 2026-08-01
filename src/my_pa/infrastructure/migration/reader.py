"""Read-only access to the legacy SQLite source.

The source is never written to, at any phase (OD-003). Every connection is
opened with ``immutable=1``, which is both a promise and an enforcement: SQLite
refuses writes on an immutable database and creates no journal, no WAL, and no
lock file beside it. A plain path or ``mode=ro`` open is not used, because
``mode=ro`` still permits SQLite to create a hot journal during recovery.

Rows come out in ``rowid`` order, in batches. That ordering is what makes resume
exact: ``rowid`` is a stable, monotonic integer on every table this migration
loads (the source has no ``WITHOUT ROWID`` table among them), so the last rowid
of a committed batch is a watermark the next batch can start strictly after.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from my_pa.infrastructure.migration.identifiers import quote

#: OD-019. Small enough that a failed batch is cheap to redo, large enough that
#: the per-batch round trips do not dominate. 3.3M rows does not need more.
DEFAULT_BATCH_SIZE = 5_000


class SourceError(RuntimeError):
    """The source database cannot be read as this migration requires."""


@dataclass(frozen=True)
class SourceColumnShape:
    """One column as SQLite declares it. No values."""

    name: str
    declared_type: str
    not_null: bool
    pk_position: int


@dataclass(frozen=True)
class SourceTableShape:
    """One table as SQLite declares it, plus its row count."""

    name: str
    columns: tuple[SourceColumnShape, ...]
    primary_key: tuple[str, ...]
    without_rowid: bool

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)


@dataclass(frozen=True)
class Batch:
    """One batch of source rows, in ``rowid`` order.

    ``watermark`` is the rowid of the last row, which the next batch starts
    strictly after. ``rows`` holds values in the order of the requested columns.
    """

    batch_key: int
    rows: tuple[tuple[object, ...], ...]
    watermark: int


@contextmanager
def open_source(path: Path) -> Iterator[sqlite3.Connection]:
    """Open the legacy database read-only and close it afterwards."""
    if not path.is_file():
        raise SourceError(f"source database not found at {path}")
    # `immutable=1` on a URI path. The path is a local file, not user input.
    connection = sqlite3.connect(f"file:{path}?immutable=1", uri=True)
    try:
        yield connection
    finally:
        connection.close()


def schema_version(connection: sqlite3.Connection) -> int:
    """Return the source's `schema_migrations` high-water mark."""
    try:
        row = connection.execute("SELECT max(version) FROM schema_migrations").fetchone()
    except sqlite3.OperationalError as exc:
        raise SourceError("source has no schema_migrations table") from exc
    if row is None or row[0] is None:
        raise SourceError("source schema_migrations table is empty")
    return int(row[0])


def read_shape(connection: sqlite3.Connection, table: str) -> SourceTableShape:
    """Introspect one table with PRAGMAs.

    Read from the live source rather than from a stored profile: the plan then
    describes the file actually being loaded, and cannot be stale.
    """
    rows = connection.execute(f"PRAGMA table_info({quote(table)})").fetchall()
    if not rows:
        raise SourceError(f"source table {table!r} does not exist or has no columns")
    columns = tuple(
        SourceColumnShape(
            name=str(row[1]),
            declared_type=str(row[2] or ""),
            not_null=bool(row[3]),
            pk_position=int(row[5]),
        )
        for row in rows
    )
    keyed = sorted(
        (column for column in columns if column.pk_position > 0),
        key=lambda column: column.pk_position,
    )
    primary_key = tuple(column.name for column in keyed)
    # `PRAGMA table_list` columns: schema, name, type, ncol, wr, strict.
    listing = connection.execute("PRAGMA table_list").fetchall()
    without_rowid = any(str(row[1]) == table and bool(row[4]) for row in listing)
    return SourceTableShape(table, columns, primary_key, without_rowid)


def count_rows(connection: sqlite3.Connection, table: str) -> int:
    """Return the exact row count of one source table."""
    # S608: a table name cannot be a bound parameter. `table` is quoted and comes
    # from `sqlite_master` in a local read-only file, never from user input.
    row = connection.execute(f"SELECT count(*) FROM {quote(table)}").fetchone()  # noqa: S608
    return int(row[0])


def iter_batches(
    connection: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    *,
    after_rowid: int,
    first_batch_key: int,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> Iterator[Batch]:
    """Yield batches of `columns` from `table`, starting after `after_rowid`.

    Keyset pagination on ``rowid`` rather than ``OFFSET``: the cost per batch
    stays flat, and the resume point is a value in the data rather than a
    position that shifts if anything else changes.
    """
    projection = ", ".join(quote(column) for column in columns)
    # S608: identifiers cannot be bound parameters. Every one here is quoted and
    # comes from `sqlite_master` in a local read-only file; the two values the
    # statement takes are bound.
    relation = quote(table)
    statement = (
        f"SELECT rowid, {projection} FROM {relation} "  # noqa: S608
        "WHERE rowid > ? ORDER BY rowid LIMIT ?"
    )
    watermark = after_rowid
    batch_key = first_batch_key
    while True:
        rows = connection.execute(statement, (watermark, batch_size)).fetchall()
        if not rows:
            return
        watermark = int(rows[-1][0])
        yield Batch(
            batch_key=batch_key,
            rows=tuple(tuple(row[1:]) for row in rows),
            watermark=watermark,
        )
        batch_key += 1
