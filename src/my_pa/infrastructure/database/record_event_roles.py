"""Record Event role names and the idempotent, credential-free provisioner.

Cluster roles are control-plane state. This module creates three ``NOLOGIN``
roles, transfers ownership of the Record Event relations and refusal functions
to the owner role, and grants the runtime role only the privileges the feed's
existing statements use. It does not invent a credential, and it does not
change a preexisting role whose attributes or membership already disagree.

Applying it to a live, shared, or production cluster is an operator action.
Nothing in this module performs that action by itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from sqlalchemy import Connection, text

from my_pa.infrastructure.persistence.record_events import feed_reader_memory_relation_names

__all__ = [
    "FEED_READER_SELECT_TABLES",
    "MIGRATOR_ROLE",
    "OWNER_ROLE",
    "RECORD_EVENT_FUNCTIONS",
    "RECORD_EVENT_TABLES",
    "RUNTIME_ROLE",
    "TRUNCATE_TRIGGERS",
    "RoleProvisionError",
    "provision_record_event_roles",
]

OWNER_ROLE: Final = "my_pa_owner"
MIGRATOR_ROLE: Final = "my_pa_migrator"
RUNTIME_ROLE: Final = "my_pa_runtime"
SCHEMA: Final = "knowledge"

RECORD_EVENT_TABLES: Final = ("record_events", "record_event_sequences")
RECORD_EVENT_FUNCTIONS: Final = (
    "record_events_stay_append_only",
    "record_event_relations_refuse_truncate",
)
TRUNCATE_TRIGGERS: Final = {
    "record_events": "record_events_refuse_truncate",
    "record_event_sequences": "record_event_sequences_refuse_truncate",
}

#: Tables the feed reader names besides the two Record Event relations.
#: ``page`` plans every routing branch and, for a remote read, the capture and
#: memory predicates, so runtime listing needs ``SELECT`` on each of them.
FEED_READER_SELECT_TABLES: Final = (
    "task_comments",
    "constraint_categories",
    "entity_external_identifiers",
    "entity_aliases",
    "entity_assignments",
    "entity_relationships",
    "entity_observations",
    "entity_names",
    "entity_addresses",
    "entity_communication_methods",
    "entity_project_participations",
    "entity_person_organization_affiliations",
    *feed_reader_memory_relation_names(),
    "capture_versions",
)

_ROLE_NAME: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_LOCK_KEY: Final = 87421002

_RUNTIME_TABLE_PRIVILEGES: Final = {
    "record_events": ("SELECT", "INSERT"),
    "record_event_sequences": ("SELECT", "INSERT", "UPDATE"),
}


class RoleProvisionError(RuntimeError):
    """The cluster refused the Record Event role contract. No privilege was widened."""


@dataclass(frozen=True, slots=True)
class _RoleSpec:
    name: str
    inherit: bool


_ROLES: Final = (
    _RoleSpec(OWNER_ROLE, inherit=False),
    _RoleSpec(MIGRATOR_ROLE, inherit=False),
    _RoleSpec(RUNTIME_ROLE, inherit=False),
)


def _check_name(name: str) -> str:
    if _ROLE_NAME.fullmatch(name) is None:
        raise RoleProvisionError("a Record Event role name is not a PostgreSQL identifier")
    return name


def _scalar(connection: Connection, statement: str, params: Mapping[str, object]) -> object:
    return connection.execute(text(statement), dict(params)).scalar_one_or_none()


def _exists(connection: Connection, name: str) -> Mapping[str, object] | None:
    row = (
        connection.execute(
            text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolcanlogin, "
                "rolinherit FROM pg_roles WHERE rolname = :name"
            ),
            {"name": name},
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


def _require_compatible(name: str, inherit: bool, row: Mapping[str, object]) -> None:
    expected = {
        "rolsuper": False,
        "rolcreaterole": False,
        "rolcreatedb": False,
        "rolbypassrls": False,
        "rolcanlogin": False,
        "rolinherit": inherit,
    }
    mismatched = sorted(key for key, value in expected.items() if bool(row[key]) is not value)
    if mismatched:
        raise RoleProvisionError(
            f"{name} already exists with incompatible attributes: {', '.join(mismatched)}"
        )


def _member(connection: Connection, member: str, role: str) -> bool:
    return bool(
        _scalar(
            connection,
            "SELECT pg_has_role(:member, :role, 'MEMBER')",
            {"member": member, "role": role},
        )
    )


def _relation_exists(connection: Connection, name: str) -> bool:
    return (
        _scalar(
            connection,
            "SELECT to_regclass(:qualified)",
            {"qualified": f"{SCHEMA}.{name}"},
        )
        is not None
    )


def _function_exists(connection: Connection, name: str) -> bool:
    found = _scalar(
        connection,
        "SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = :schema AND p.proname = :name",
        {"schema": SCHEMA, "name": name},
    )
    return found is not None


def _exec(connection: Connection, statement: str) -> None:
    connection.execute(text(statement))


def provision_record_event_roles(connection: Connection) -> bool:
    """Create the three roles and, when the feed exists, its grants.

    Returns whether relation grants were applied. Role creation without the
    feed tables is intentional: the privilege gate then fails closed until the
    schema migration and a later provision run.

    The connection must be outside a transaction. ``CREATE ROLE`` cannot run
    inside one, and a transactional grant would hide a failure from the caller.
    """
    if connection.in_transaction():
        raise RoleProvisionError("Record Event role provisioning refuses an open transaction")
    for spec in _ROLES:
        _check_name(spec.name)
    _exec(connection, f"SELECT pg_advisory_lock({_LOCK_KEY})")
    try:
        return _provision_locked(connection)
    finally:
        _exec(connection, f"SELECT pg_advisory_unlock({_LOCK_KEY})")


def _provision_locked(connection: Connection) -> bool:
    for spec in _ROLES:
        existing = _exists(connection, spec.name)
        if existing is None:
            inherit = "INHERIT" if spec.inherit else "NOINHERIT"
            _exec(
                connection,
                f"CREATE ROLE {spec.name} NOLOGIN {inherit} "
                "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS",
            )
        else:
            _require_compatible(spec.name, spec.inherit, existing)
    if _member(connection, RUNTIME_ROLE, OWNER_ROLE) or _member(
        connection, RUNTIME_ROLE, MIGRATOR_ROLE
    ):
        raise RoleProvisionError(
            f"{RUNTIME_ROLE} is already a member of {OWNER_ROLE} or {MIGRATOR_ROLE}"
        )
    if not _member(connection, MIGRATOR_ROLE, OWNER_ROLE):
        _exec(connection, f"GRANT {OWNER_ROLE} TO {MIGRATOR_ROLE}")
    tables_present = [_relation_exists(connection, name) for name in RECORD_EVENT_TABLES]
    if not any(tables_present):
        return False
    if not all(tables_present):
        raise RoleProvisionError("the Record Event relations are only partly present")
    for name in RECORD_EVENT_FUNCTIONS:
        if not _function_exists(connection, name):
            raise RoleProvisionError(f"{SCHEMA}.{name} is absent; refusing a partial grant")
    for name in FEED_READER_SELECT_TABLES:
        if not _relation_exists(connection, name):
            raise RoleProvisionError(f"{SCHEMA}.{name} is absent; refusing a partial grant")
    for name in (*RECORD_EVENT_TABLES, *RECORD_EVENT_FUNCTIONS):
        kind = "FUNCTION" if name in RECORD_EVENT_FUNCTIONS else "TABLE"
        target = f"{SCHEMA}.{name}()" if kind == "FUNCTION" else f"{SCHEMA}.{name}"
        _exec(connection, f"ALTER {kind} {target} OWNER TO {OWNER_ROLE}")
    for table, privileges in _RUNTIME_TABLE_PRIVILEGES.items():
        qualified = f"{SCHEMA}.{table}"
        _exec(connection, f"REVOKE ALL ON TABLE {qualified} FROM PUBLIC")
        _exec(connection, f"REVOKE ALL ON TABLE {qualified} FROM {RUNTIME_ROLE}")
        _exec(connection, f"REVOKE TRUNCATE ON TABLE {qualified} FROM PUBLIC")
        _exec(connection, f"REVOKE TRUNCATE ON TABLE {qualified} FROM {RUNTIME_ROLE}")
        granted = ", ".join(privileges)
        _exec(connection, f"GRANT {granted} ON TABLE {qualified} TO {RUNTIME_ROLE}")
    for table in FEED_READER_SELECT_TABLES:
        qualified = f"{SCHEMA}.{table}"
        _exec(connection, f"REVOKE ALL ON TABLE {qualified} FROM {RUNTIME_ROLE}")
        _exec(connection, f"GRANT SELECT ON TABLE {qualified} TO {RUNTIME_ROLE}")
    _exec(connection, f"REVOKE CREATE ON SCHEMA {SCHEMA} FROM PUBLIC")
    _exec(connection, f"REVOKE CREATE ON SCHEMA {SCHEMA} FROM {RUNTIME_ROLE}")
    # Owner and migrator need USAGE to reach the relations they administer.
    # CREATE stays with the historical schema owner; runtime receives USAGE only.
    for role in (OWNER_ROLE, MIGRATOR_ROLE, RUNTIME_ROLE):
        _exec(connection, f"GRANT USAGE ON SCHEMA {SCHEMA} TO {role}")
    return True
