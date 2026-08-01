"""Persistence for the `knowledge` schema: sources, objects, enrollment, jobs.

Several writers here insert with `ON CONFLICT DO NOTHING` and, when that returns
no row, select the row that must already exist. That works because a READ
COMMITTED statement takes a fresh snapshot: once the insert has conflicted, the
conflicting row was committed by someone else, and the select that follows can
see it.

`create_database_engine` sets no `isolation_level`, so connections run at
PostgreSQL's default, which is READ COMMITTED. The dependency is satisfied by
configuration rather than by anything these modules do, which is why it is named
here and again at each call site.

What a higher isolation level does was measured rather than assumed, against
PostgreSQL 17, in
`tests/schema/test_knowledge_schema_migration.py::test_raising_the_isolation_level_breaks_the_retry_rather_than_corrupting_it`.
It is not the silent wrong answer one might expect. Under REPEATABLE READ, when
the conflicting row was committed *after* this transaction's snapshot,
PostgreSQL refuses the `ON CONFLICT DO NOTHING` itself with a serialization
failure and the select is never reached; the retry path is broken, but loudly
and retryably rather than incorrectly. When the row predates the snapshot,
nothing serializes and the fallback returns it normally. So the sensitivity is
to snapshot age, not to the isolation level on its own.

`conflicting_row` guards what is left: an insert that conflicted against a row
which is then not readable a statement later. Under READ COMMITTED that means
the row was deleted in between. Letting `.one()` raise a bare `NoResultFound`
there would report it as an absent enrollment, which is precisely what it is
not.
"""

from __future__ import annotations

__all__ = ["IsolationLevelError", "conflicting_row"]


class IsolationLevelError(RuntimeError):
    """An insert conflicted, and the row it conflicted with is not readable.

    Names the defect and the table, never a stored value. Under READ COMMITTED
    this means the row was deleted between the two statements. It is a
    `RuntimeError` rather than a lookup failure because nothing the caller did
    is wrong.
    """


def conflicting_row[T](row: T | None, subject: str) -> T:
    """Return `row`, or raise `IsolationLevelError` naming `subject`.

    `subject` is a table name, never a value from the request.
    """
    if row is None:
        raise IsolationLevelError(
            f"an insert into {subject} conflicted but the conflicting row is not "
            "readable; this fallback assumes READ COMMITTED, which is PostgreSQL's "
            "default and which create_database_engine does not override"
        )
    return row
