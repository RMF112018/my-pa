"""Read-only Record Event privilege gate for the configured runtime principal.

Every probe runs in one transaction that is rolled back, including the
allocator and feed insert that prove the ordinary write path. The gate prints
nothing and never includes a connection string in an error.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.record_event_roles import (
    MIGRATOR_ROLE,
    OWNER_ROLE,
    RECORD_EVENT_TABLES,
    RUNTIME_ROLE,
    SCHEMA,
    TRUNCATE_TRIGGERS,
)
from my_pa.infrastructure.persistence.record_events import (
    SqlRecordEventReader,
    SqlRecordEventWriter,
)

__all__ = ["PrivilegeGateError", "verify_record_event_privileges"]

_WHEN: Final = datetime(2026, 10, 2, 12, tzinfo=UTC)
_INSUFFICIENT: Final = "42501"


class PrivilegeGateError(RuntimeError):
    """The runtime principal does not meet the Record Event privilege contract."""


def verify_record_event_privileges(connection: Connection) -> None:
    """Fail unless ``current_user`` is the restricted runtime principal."""
    if connection.in_transaction():
        raise PrivilegeGateError("the privilege gate refuses an open transaction")
    transaction = connection.begin()
    try:
        _verify(connection)
    finally:
        transaction.rollback()


def _verify(connection: Connection) -> None:
    current = str(connection.execute(text("SELECT current_user")).scalar_one())
    if current != RUNTIME_ROLE:
        raise PrivilegeGateError(f"current_user is {current}, expected {RUNTIME_ROLE}")
    row = (
        connection.execute(
            text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls "
                "FROM pg_roles WHERE rolname = :name"
            ),
            {"name": current},
        )
        .mappings()
        .one()
    )
    for flag in ("rolsuper", "rolcreaterole", "rolcreatedb", "rolbypassrls"):
        if bool(row[flag]):
            raise PrivilegeGateError(f"{current} has {flag}")
    for table in RECORD_EVENT_TABLES:
        owner = connection.execute(
            text(
                "SELECT pg_get_userbyid(c.relowner) FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :table"
            ),
            {"schema": SCHEMA, "table": table},
        ).scalar_one_or_none()
        if owner is None:
            raise PrivilegeGateError(f"{SCHEMA}.{table} is absent")
        if str(owner) == current:
            raise PrivilegeGateError(f"{current} owns {SCHEMA}.{table}")
    if _schema_privilege(connection, current, "CREATE"):
        raise PrivilegeGateError(f"{current} has CREATE on schema {SCHEMA}")
    _forbid_table(connection, current, "record_events", "UPDATE")
    _forbid_table(connection, current, "record_events", "DELETE")
    _forbid_table(connection, current, "record_events", "TRUNCATE")
    _forbid_table(connection, current, "record_events", "REFERENCES")
    _forbid_table(connection, current, "record_events", "TRIGGER")
    _forbid_table(connection, current, "record_event_sequences", "DELETE")
    _forbid_table(connection, current, "record_event_sequences", "TRUNCATE")
    _forbid_table(connection, current, "record_event_sequences", "REFERENCES")
    _forbid_table(connection, current, "record_event_sequences", "TRIGGER")
    for privilege in ("SELECT", "INSERT"):
        _require_table(connection, current, "record_events", privilege)
    for privilege in ("SELECT", "INSERT", "UPDATE"):
        _require_table(connection, current, "record_event_sequences", privilege)
    for role in (OWNER_ROLE, MIGRATOR_ROLE):
        if _has_role(connection, current, role, "MEMBER") or _can_set_role(
            connection, current, role
        ):
            raise PrivilegeGateError(f"{current} can assume {role}")
        _expect_sqlstate(connection, f"SET LOCAL ROLE {role}", _INSUFFICIENT)
    for table, trigger in TRUNCATE_TRIGGERS.items():
        enabled = connection.execute(
            text(
                "SELECT t.tgenabled FROM pg_trigger t "
                "JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :schema AND c.relname = :table AND t.tgname = :trigger "
                "AND NOT t.tgisinternal"
            ),
            {"schema": SCHEMA, "table": table, "trigger": trigger},
        ).scalar_one_or_none()
        if enabled != "O":
            raise PrivilegeGateError(f"{trigger} is not an enabled origin trigger")
    _expect_sqlstate(connection, "TRUNCATE TABLE knowledge.record_events", _INSUFFICIENT)
    _expect_sqlstate(connection, "TRUNCATE TABLE knowledge.record_event_sequences", _INSUFFICIENT)
    _expect_sqlstate(
        connection,
        "UPDATE knowledge.record_events SET record_version = record_version",
        _INSUFFICIENT,
    )
    _expect_sqlstate(connection, "DELETE FROM knowledge.record_events", _INSUFFICIENT)
    _expect_sqlstate(
        connection,
        "CREATE TABLE knowledge.record_event_privilege_probe (id integer)",
        _INSUFFICIENT,
    )
    _prove_product_path(connection)


def _table_privilege(connection: Connection, role: str, table: str, privilege: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT has_table_privilege(:role, :qualified, :privilege)"),
            {"role": role, "qualified": f"{SCHEMA}.{table}", "privilege": privilege},
        ).scalar_one()
    )


def _schema_privilege(connection: Connection, role: str, privilege: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT has_schema_privilege(:role, :schema, :privilege)"),
            {"role": role, "schema": SCHEMA, "privilege": privilege},
        ).scalar_one()
    )


def _has_role(connection: Connection, member: str, role: str, privilege: str) -> bool:
    return bool(
        connection.execute(
            text("SELECT pg_has_role(:member, :role, :privilege)"),
            {"member": member, "role": role, "privilege": privilege},
        ).scalar_one()
    )


def _can_set_role(connection: Connection, member: str, role: str) -> bool:
    """Whether ``member`` may ``SET ROLE`` to ``role``.

    PostgreSQL 16 added ``pg_has_role(..., 'SET')``. On PostgreSQL 15, membership
    itself is the ``SET ROLE`` right, which the caller already rejects.
    """
    version = int(connection.execute(text("SHOW server_version_num")).scalar_one())
    if version < 160000:
        return False
    return _has_role(connection, member, role, "SET")


def _forbid_table(connection: Connection, role: str, table: str, privilege: str) -> None:
    if _table_privilege(connection, role, table, privilege):
        raise PrivilegeGateError(f"{role} has {privilege} on {SCHEMA}.{table}")


def _require_table(connection: Connection, role: str, table: str, privilege: str) -> None:
    if not _table_privilege(connection, role, table, privilege):
        raise PrivilegeGateError(f"{role} lacks {privilege} on {SCHEMA}.{table}")


def _expect_sqlstate(connection: Connection, statement: str, sqlstate: str) -> None:
    connection.execute(text("SAVEPOINT record_event_privilege_probe"))
    try:
        connection.execute(text(statement))
    except DBAPIError as exc:
        connection.execute(text("ROLLBACK TO SAVEPOINT record_event_privilege_probe"))
        observed = getattr(exc.orig, "sqlstate", None)
        if observed != sqlstate:
            raise PrivilegeGateError(
                f"{statement.split()[0]} failed with {observed}, expected {sqlstate}"
            ) from None
        return
    connection.execute(text("ROLLBACK TO SAVEPOINT record_event_privilege_probe"))
    raise PrivilegeGateError(f"{statement.split()[0]} was accepted")


def _prove_product_path(connection: Connection) -> None:
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    draft = RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=RecordEventFamily.MEETING_SERIES,
        record_id=issue_identifier(IdKind.MEETING_SERIES),
        event_kind=RecordEventKind.UPDATED,
        record_version=2,
        changed_fields=("title",),
        source_capability="meetings.series.update",
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=Classification.PRIVATE_LOCAL,
        occurred_at=_WHEN,
    )
    writer = SqlRecordEventWriter(connection)
    first = writer.allocate(principal_id, 1)
    writer.insert(first, (draft,))
    page = SqlRecordEventReader(connection).page(
        principal_id=principal_id,
        after_sequence=0,
        families=frozenset({RecordEventFamily.MEETING_SERIES}),
        include_restricted_memory=False,
        limit=10,
    )
    if len(page.rows) != 1 or page.rows[0].event_id != draft.event_id:
        raise PrivilegeGateError("the runtime feed path did not read the appended event")
    if page.high_watermark_event_id != draft.event_id:
        raise PrivilegeGateError("the runtime feed listing did not report the appended event")
