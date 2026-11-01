"""Read-only CPM Workbench pre-deploy checks (worker contract section 3.16).

The S5b-1 operator gates (foundation contract section 9.3) and the S5b-2
vocabulary revision, as catalog reads an operator runs before and after the two
CPM revisions (`6c2306330ceb`, `621ef6786c64`). Every statement in
`STATEMENTS` is a `SELECT` over system catalogs or catalog functions. The run is
one transaction whose first statement is `SET TRANSACTION READ ONLY` and which
is always rolled back, so nothing here can write, grant, revoke or lock beyond
`ACCESS SHARE` on a catalog. Nothing prints; results never carry a connection
string, a row of application data or an exception text.

What the checks cannot do: decide whether a default-privilege entry belongs to
the role that will run the migration (every matching entry is a stop, so the
operator judges it), or replace the operator's quiet-window decision (P3 is
reported, never a stop). No check was run against any persistent database by
the change that added it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import Connection, text

__all__ = [
    "CPM_TABLES",
    "PROFILE_ROLES",
    "STATEMENTS",
    "CheckStatus",
    "PredeployCheck",
    "PredeployPhase",
    "run_predeploy_checks",
]

SCHEMA: Final = "knowledge"

#: The 7 S5b-1 tables (foundation contract section 4).
CPM_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_rows",
    "schedule_import_issues",
)

#: Tables the worker and the import capability update (or lock `FOR UPDATE`).
_UPDATED_TABLES: Final = frozenset(
    {"schedule_publications", "schedule_jobs", "schedule_parser_runs", "schedule_rows"}
)

#: The 2 live tables whose ACL the S5b-1 revision must leave byte-identical.
ACL_TABLES: Final = ("enrollments", "source_object_versions")

#: Live tables whose locks the 2 revisions take (P3 sizing).
LOCKED_TABLES: Final = (
    "enrollments",
    "source_object_versions",
    "audit_events",
    "worker_heartbeats",
)

#: The MCP database profile roles that must hold nothing on the CPM tables.
PROFILE_ROLES: Final = ("my_pa_mcp_ro", "my_pa_mcp_rw")
_FORBIDDEN_GRANTEES: Final = frozenset({"PUBLIC", *PROFILE_ROLES})

#: Vocabulary migration #2 must admit (literals, never derived from the enums).
_SCHEDULE_CAPABILITIES: Final = (
    "schedule_activities.history",
    "schedule_activities.list",
    "schedule_changes.list",
    "schedule_publications.import",
    "schedule_publications.list",
    "schedule_publications.read",
    "schedule_series.list",
)
_SCHEDULE_PURPOSES: Final = ("schedule_import", "schedule_read")
_VOCABULARY: Final[Mapping[str, tuple[str, tuple[str, ...]]]] = {
    "capability_is_known": ("audit_events", _SCHEDULE_CAPABILITIES),
    "purpose_is_known": ("audit_events", _SCHEDULE_PURPOSES),
    "worker_plane_is_known": ("worker_heartbeats", ("schedule",)),
}

#: The only non-`SELECT` statement, always the transaction's first.
READ_ONLY: Final = "SET TRANSACTION READ ONLY"

#: Every statement the checks issue after `READ_ONLY`. Each is a `SELECT`.
STATEMENTS: Final[Mapping[str, str]] = {
    "read_only": "SELECT pg_catalog.current_setting('transaction_read_only')",
    "default_privileges": (
        "SELECT pg_catalog.pg_get_userbyid(d.defaclrole) AS role, "
        "COALESCE(n.nspname, '') AS namespace, "
        "CASE WHEN a.grantee = 0 THEN 'PUBLIC' "
        "ELSE pg_catalog.pg_get_userbyid(a.grantee) END AS grantee, "
        "a.privilege_type AS privilege "
        "FROM pg_catalog.pg_default_acl d "
        "LEFT JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a "
        "WHERE d.defaclobjtype = 'r' "
        "ORDER BY 1, 2, 3, 4"
    ),
    "primary_keys": (
        "SELECT c.relname AS table_name, pg_catalog.array_length(k.conkey, 1) AS columns "
        "FROM pg_catalog.pg_constraint k "
        "JOIN pg_catalog.pg_class c ON c.oid = k.conrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE k.contype = 'p' AND n.nspname = :schema AND c.relname = ANY(:tables) "
        "ORDER BY 1"
    ),
    "lock_sizing": (
        "SELECT c.relname AS table_name, c.reltuples::bigint AS estimated_rows, "
        "pg_catalog.pg_relation_size(c.oid) AS size_bytes "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = ANY(:tables) AND c.relkind = 'r' "
        "ORDER BY 1"
    ),
    "runtime_identity": "SELECT current_user AS current_role, session_user AS session_role",
    "lineage_reach": (
        "SELECT pg_catalog.pg_get_userbyid(c.relowner) AS owner, "
        "pg_catalog.has_table_privilege(c.oid, 'SELECT') AS can_select, "
        "pg_catalog.has_table_privilege(c.oid, 'INSERT') AS can_insert "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = 'record_links'"
    ),
    "acl_digest": (
        "SELECT pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to("
        "pg_catalog.string_agg(c.relname || '=' || COALESCE(c.relacl::text, '<default>'), "
        "';' ORDER BY c.relname), 'UTF8')), 'hex') AS digest, "
        "pg_catalog.count(*) AS tables "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = ANY(:tables) AND c.relkind = 'r'"
    ),
    "present_tables": (
        "SELECT c.relname AS table_name FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = ANY(:tables) AND c.relkind = 'r' "
        "ORDER BY 1"
    ),
    "present_roles": (
        "SELECT r.rolname FROM pg_catalog.pg_roles r WHERE r.rolname = ANY(:roles) ORDER BY 1"
    ),
    "grantee_reach": (
        "SELECT pg_catalog.has_table_privilege(:role, c.oid, "
        "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE') AS reaches "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :table AND c.relkind = 'r'"
    ),
    "constraint_text": (
        "SELECT pg_catalog.pg_get_constraintdef(k.oid) AS definition "
        "FROM pg_catalog.pg_constraint k "
        "JOIN pg_catalog.pg_class c ON c.oid = k.conrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :table AND k.conname = :name"
    ),
    "runtime_reach": (
        "SELECT pg_catalog.has_table_privilege(c.oid, :privilege) AS holds "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :table AND c.relkind = 'r'"
    ),
}


class PredeployPhase(StrEnum):
    BEFORE = "before"
    AFTER = "after"


class CheckStatus(StrEnum):
    #: The gate holds.
    HOLDS = "pass"
    #: The gate does not hold: the operator stops and reports.
    STOP = "stop"
    #: Information for the operator's decision; never a stop by itself.
    REPORT = "report"


@dataclass(frozen=True, slots=True)
class PredeployCheck:
    """One gate's outcome. `detail` holds catalog names and counts only."""

    check_id: str
    name: str
    status: CheckStatus
    detail: str


def run_predeploy_checks(
    connection: Connection,
    phase: PredeployPhase,
    *,
    before_acl_sha256: str | None = None,
) -> tuple[PredeployCheck, ...]:
    """The checks of `phase`, in one `READ ONLY` transaction that is rolled back.

    `before_acl_sha256` is the P5 digest the `before` run reported; the `after`
    run stops without it. An open transaction on `connection` is refused, so the
    `READ ONLY` statement is always the transaction's first.
    """
    if connection.in_transaction():
        raise ValueError("the pre-deploy checks refuse an open transaction")
    transaction = connection.begin()
    try:
        connection.execute(text(READ_ONLY))
        checks = [_read_only(connection)]
        if phase is PredeployPhase.BEFORE:
            checks += [
                _default_privileges(connection),
                _primary_keys(connection),
                _lock_sizing(connection),
                _runtime_role_reach(connection),
                _acl_snapshot(connection, phase, before_acl_sha256),
            ]
        else:
            checks += [
                _acl_snapshot(connection, phase, before_acl_sha256),
                _no_extra_grant(connection),
                _vocabulary_at_head(connection),
                _runtime_reach(connection),
            ]
        return tuple(checks)
    finally:
        transaction.rollback()


def _select(connection: Connection, key: str, **params: object) -> list[Mapping[str, object]]:
    return [dict(row) for row in connection.execute(text(STATEMENTS[key]), params).mappings()]


def _read_only(connection: Connection) -> PredeployCheck:
    setting = str(connection.execute(text(STATEMENTS["read_only"])).scalar_one())
    status = CheckStatus.HOLDS if setting == "on" else CheckStatus.STOP
    return PredeployCheck("P0", "read_only_transaction", status, f"transaction_read_only={setting}")


def _default_privileges(connection: Connection) -> PredeployCheck:
    """P1: no default privilege would hand a new `knowledge` table to a forbidden grantee."""
    offending = sorted(
        {
            f"{row['role']}:{row['namespace'] or '<global>'}:{row['grantee']}"
            for row in _select(connection, "default_privileges")
            if row["namespace"] in ("", SCHEMA) and row["grantee"] in _FORBIDDEN_GRANTEES
        }
    )
    if offending:
        return PredeployCheck("P1", "default_privileges", CheckStatus.STOP, ",".join(offending))
    return PredeployCheck("P1", "default_privileges", CheckStatus.HOLDS, "entries=0")


def _primary_keys(connection: Connection) -> PredeployCheck:
    """P2: `enrollments` and `source_object_versions` each have a single-column PK."""
    found = {
        str(row["table_name"]): row["columns"]
        for row in _select(connection, "primary_keys", schema=SCHEMA, tables=list(ACL_TABLES))
    }
    wrong = [table for table in ACL_TABLES if found.get(table) != 1]
    if wrong:
        return PredeployCheck("P2", "primary_keys", CheckStatus.STOP, ",".join(wrong))
    return PredeployCheck("P2", "primary_keys", CheckStatus.HOLDS, ",".join(ACL_TABLES))


def _lock_sizing(connection: Connection) -> PredeployCheck:
    """P3: estimated rows and size of every table the revisions lock (reported)."""
    rows = _select(connection, "lock_sizing", schema=SCHEMA, tables=list(LOCKED_TABLES))
    detail = ",".join(
        f"{row['table_name']}:rows~{row['estimated_rows']}:bytes={row['size_bytes']}"
        for row in rows
    )
    return PredeployCheck("P3", "lock_sizing", CheckStatus.REPORT, detail)


def _runtime_role_reach(connection: Connection) -> PredeployCheck:
    """P4: the connecting role reaches a lineage table the way it will reach the CPM ones.

    A stop here is a stop for enabling the schedule plane, not for the schema-only deploy.
    """
    identity = _select(connection, "runtime_identity")[0]
    lineage = _select(connection, "lineage_reach", schema=SCHEMA)
    who = f"current={identity['current_role']},session={identity['session_role']}"
    if not lineage:
        return PredeployCheck(
            "P4", "runtime_role_reach", CheckStatus.STOP, f"{who},record_links=absent"
        )
    row = lineage[0]
    if row["owner"] == identity["current_role"]:
        reach = "owner"
    elif row["can_select"] and row["can_insert"]:
        reach = "granted"
    else:
        return PredeployCheck("P4", "runtime_role_reach", CheckStatus.STOP, f"{who},reach=none")
    return PredeployCheck("P4", "runtime_role_reach", CheckStatus.HOLDS, f"{who},reach={reach}")


def _acl_snapshot(
    connection: Connection, phase: PredeployPhase, before_acl_sha256: str | None
) -> PredeployCheck:
    """P5: one digest over the ACL text of the 2 live tables, compared after the deploy."""
    row = _select(connection, "acl_digest", schema=SCHEMA, tables=list(ACL_TABLES))[0]
    digest = str(row["digest"]) if row["digest"] is not None else ""
    if row["tables"] != len(ACL_TABLES):
        return PredeployCheck("P5", "acl_snapshot", CheckStatus.STOP, f"tables={row['tables']}")
    if phase is PredeployPhase.BEFORE:
        return PredeployCheck("P5", "acl_snapshot", CheckStatus.REPORT, f"sha256={digest}")
    if before_acl_sha256 is None:
        return PredeployCheck(
            "P5", "acl_snapshot", CheckStatus.STOP, f"sha256={digest},before=missing"
        )
    status = CheckStatus.HOLDS if before_acl_sha256 == digest else CheckStatus.STOP
    return PredeployCheck("P5", "acl_snapshot", status, f"sha256={digest}")


def _present_tables(connection: Connection) -> list[str]:
    return [
        str(row["table_name"])
        for row in _select(connection, "present_tables", schema=SCHEMA, tables=list(CPM_TABLES))
    ]


def _no_extra_grant(connection: Connection) -> PredeployCheck:
    """P6: `PUBLIC` and the existing MCP profile roles hold no privilege on a CPM table."""
    present = _present_tables(connection)
    missing = sorted(set(CPM_TABLES) - set(present))
    if missing:
        return PredeployCheck(
            "P6", "no_extra_grant", CheckStatus.STOP, f"absent={','.join(missing)}"
        )
    roles = ["public"] + [
        str(row["rolname"])
        for row in _select(connection, "present_roles", roles=list(PROFILE_ROLES))
    ]
    reached = sorted(
        f"{role}:{table}"
        for role in roles
        for table in CPM_TABLES
        if _select(connection, "grantee_reach", role=role, schema=SCHEMA, table=table)[0]["reaches"]
    )
    if reached:
        return PredeployCheck("P6", "no_extra_grant", CheckStatus.STOP, ",".join(reached))
    return PredeployCheck("P6", "no_extra_grant", CheckStatus.HOLDS, f"roles={','.join(roles)}")


def _vocabulary_at_head(connection: Connection) -> PredeployCheck:
    """P7: the 3 restated CHECKs name every Schedule capability, purpose and the plane."""
    missing: list[str] = []
    for name, (table, literals) in _VOCABULARY.items():
        rows = _select(connection, "constraint_text", schema=SCHEMA, table=table, name=name)
        if not rows:
            missing.append(f"{name}:absent")
            continue
        definition = str(rows[0]["definition"])
        missing += [f"{name}:{literal}" for literal in literals if f"'{literal}'" not in definition]
    if missing:
        return PredeployCheck("P7", "vocabulary_at_head", CheckStatus.STOP, ",".join(missing))
    return PredeployCheck("P7", "vocabulary_at_head", CheckStatus.HOLDS, ",".join(_VOCABULARY))


def _runtime_reach(connection: Connection) -> PredeployCheck:
    """P8: the connecting role can read and write the 7 tables as the worker and reads must."""
    present = _present_tables(connection)
    missing = sorted(set(CPM_TABLES) - set(present))
    if missing:
        return PredeployCheck(
            "P8", "runtime_reach", CheckStatus.STOP, f"absent={','.join(missing)}"
        )
    lacking = [
        f"{table}:{privilege}"
        for table in CPM_TABLES
        for privilege in (
            ("SELECT", "INSERT", "UPDATE") if table in _UPDATED_TABLES else ("SELECT", "INSERT")
        )
        if not _select(
            connection, "runtime_reach", privilege=privilege, schema=SCHEMA, table=table
        )[0]["holds"]
    ]
    if lacking:
        return PredeployCheck("P8", "runtime_reach", CheckStatus.STOP, ",".join(lacking))
    return PredeployCheck("P8", "runtime_reach", CheckStatus.HOLDS, f"tables={len(CPM_TABLES)}")
