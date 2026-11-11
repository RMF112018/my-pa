"""Read-only Schedule Scenarios revision-A and revision-B pre-deploy checks.

Contract sections 14.9 and 15.13: Q0-Q9 gate revision A (`2a90f91dd786`); Q10
(before, reported) sizes the live `knowledge.audit_events` that revision B
(`b77334135653`) locks `ACCESS EXCLUSIVE`, and Q11 (after) proves the restated
audit CHECKs name the 26 Schedule Scenarios capabilities and their 3 purposes.

The S6-2 operator gates (contract section 14.12.4) as reads an operator runs,
as the runtime role the gateway and worker connect as, before and after
revision `2a90f91dd786`. The run is one transaction whose first statement is
`SET TRANSACTION READ ONLY` and which is always rolled back, so nothing here
can write, grant, revoke or lock beyond `ACCESS SHARE`. Nothing prints;
results never carry a connection string, a row of application data or an
exception text.

Every statement in `STATEMENTS` is a `SELECT` over system catalogs or catalog
functions. The one exception is Q2's retired-role probe, a deliberate
operator-wide, cross-Principal boolean (R9-F09): an `EXISTS` over
`schedule_publications` that returns no row and no identifier. It is built
with the expression language over the table declaration
(`RETIRED_ROLE_PROBE`), never a raw string, and this module is registered in
`QUARANTINED` of the Principal-partition guard for exactly that one probe;
`test_predeploy_module_touches_only_the_retired_role_probe` pins the
registration so it cannot widen (RR2-F01).

What the checks cannot do: decide whether a default-privilege entry belongs to
the role that will run the migration (every matching entry is a stop), or
replace the operator's quiet-window decision (Q3 is reported, never a stop).
No check was run against any persistent database by the change that added it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import Connection, exists, select, text

from my_pa.infrastructure.persistence.tables import schedule_publications

__all__ = [
    "PLANE_FUNCTIONS",
    "PLANE_TABLES",
    "PROFILE_ROLES",
    "RETIRED_ROLE_PROBE",
    "STATEMENTS",
    "CheckStatus",
    "PredeployCheck",
    "PredeployPhase",
    "run_predeploy_checks",
]

SCHEMA: Final = "knowledge"

#: The 7 S5 tables revision A requires (`621ef6786c64` applied first).
S5_TABLES: Final = (
    "schedule_series",
    "schedule_publications",
    "schedule_activities",
    "schedule_jobs",
    "schedule_parser_runs",
    "schedule_rows",
    "schedule_import_issues",
)

#: The 11 plane tables of revision A (contract section 14.3).
PLANE_TABLES: Final = (
    "schedule_intake_series",
    "schedule_series_match_decisions",
    "schedule_baselines",
    "schedule_baseline_events",
    "schedule_governing_events",
    "schedule_scenarios",
    "schedule_scenario_versions",
    "schedule_cpm_runs",
    "schedule_scenario_outputs",
    "schedule_scenario_write_requests",
    "schedule_scenario_write_refusals",
)
#: The one plane table a runtime write updates (the idempotency ledger's completion).
_UPDATED_TABLE: Final = "schedule_scenario_write_requests"
#: The refusal ledger's identity sequence (Q6).
_REFUSAL_TABLE: Final = "schedule_scenario_write_refusals"
_REFUSAL_COLUMN: Final = "refusal_no"

#: G1-G15 (contract section 14.4), frozen.
PLANE_FUNCTIONS: Final = (
    "schedule_plane_rows_are_append_only",
    "schedule_plane_relations_refuse_truncate",
    "a_schedule_scenario_starts_from_an_admissible_origin",
    "a_schedule_scenario_has_its_first_version",
    "a_scenario_version_extends_its_chain",
    "a_scenario_output_binds_a_computed_run",
    "a_plane_write_request_completes_once",
    "a_plane_write_request_is_never_left_reserved",
    "an_intake_series_holds_only_its_publication",
    "a_schedule_intake_series_admits_no_other_publication",
    "a_series_match_decision_follows_its_intake",
    "a_schedule_baseline_names_an_admissible_publication",
    "a_schedule_baseline_has_its_first_event",
    "a_schedule_baseline_event_extends_its_chain",
    "a_schedule_governing_event_extends_its_chain",
)
#: G10, the one plane trigger on an existing table.
_G10: Final = ("schedule_publications", "a_schedule_intake_series_admits_no_other_publication")

#: The 3 live tables whose ACL revision A must leave byte-identical (Q5).
ACL_TABLES: Final = ("record_links", "schedule_publications", "schedule_series")
#: The live tables revision A locks (Q3 sizing).
LOCKED_TABLES: Final = ("record_links", "schedule_publications", "schedule_series")

#: The MCP database profile roles that must hold nothing on a plane table.
PROFILE_ROLES: Final = ("my_pa_mcp_ro", "my_pa_mcp_rw")
_FORBIDDEN_GRANTEES: Final = frozenset({"PUBLIC", *PROFILE_ROLES})

#: Q7: what the restated CHECKs must (and must not) name at head (frozen literals).
_S6_RELATIONS: Final = ("concerns", "delays", "mitigates")
_S6_FAMILIES: Final = (
    "schedule_publication",
    "schedule_activity",
    "schedule_baseline",
    "scenario",
    "scenario_version",
    "scenario_output",
)
_HEAD_TEXTS: Final[Mapping[str, tuple[str, tuple[str, ...], tuple[str, ...]]]] = {
    "a_record_link_pair_is_admitted": ("record_links", _S6_RELATIONS, ()),
    "a_record_link_from_family_is_known": ("record_links", _S6_FAMILIES, ()),
    "a_schedule_publication_role_is_known": ("schedule_publications", (), ("reference",)),
}

#: Q10/Q11 (contract section 15.13): the live table revision B locks, and what its
#: restated audit CHECKs must name at head (frozen literals).
AUDIT_TABLE: Final = "audit_events"
_S63_CAPABILITIES: Final = (
    "schedule_baselines.approve",
    "schedule_baselines.compare",
    "schedule_baselines.governing",
    "schedule_baselines.list",
    "schedule_baselines.propose",
    "schedule_baselines.read",
    "schedule_baselines.reject",
    "schedule_baselines.revoke",
    "schedule_baselines.set_governing",
    "schedule_baselines.withdraw",
    "schedule_cpm_runs.activities",
    "schedule_cpm_runs.create",
    "schedule_cpm_runs.read",
    "schedule_scenario_outputs.list",
    "schedule_scenario_outputs.read",
    "schedule_scenario_outputs.record",
    "schedule_scenario_versions.activities",
    "schedule_scenario_versions.changes",
    "schedule_scenario_versions.create",
    "schedule_scenario_versions.read",
    "schedule_scenario_versions.relationships",
    "schedule_scenarios.create",
    "schedule_scenarios.list",
    "schedule_scenarios.read",
    "schedule_series.current",
    "schedule_series.match_decisions",
)
_S63_PURPOSES: Final = (
    "schedule_analysis_authoring",
    "schedule_analysis_read",
    "schedule_baseline_approval",
)
_AUDIT_TEXTS: Final[Mapping[str, tuple[str, ...]]] = {
    "capability_is_known": _S63_CAPABILITIES,
    "purpose_is_known": _S63_PURPOSES,
}

#: The only non-`SELECT` statement, always the transaction's first.
READ_ONLY: Final = "SET TRANSACTION READ ONLY"

#: Q2's operator-wide, cross-Principal boolean (R9-F09, RR1-F02): one `EXISTS`
#: over the declaration, returning no row and no identifier.
RETIRED_ROLE_PROBE: Final = select(
    exists().where(schedule_publications.c.publication_role.in_(("baseline", "reference")))
)

#: Every catalog statement the checks issue after `READ_ONLY`. Each is a `SELECT`.
STATEMENTS: Final[Mapping[str, str]] = {
    "read_only": "SELECT pg_catalog.current_setting('transaction_read_only')",
    "default_privileges": (
        "SELECT pg_catalog.pg_get_userbyid(d.defaclrole) AS role, "
        "COALESCE(n.nspname, '') AS namespace, d.defaclobjtype AS object_type, "
        "CASE WHEN a.grantee = 0 THEN 'PUBLIC' "
        "ELSE pg_catalog.pg_get_userbyid(a.grantee) END AS grantee "
        "FROM pg_catalog.pg_default_acl d "
        "LEFT JOIN pg_catalog.pg_namespace n ON n.oid = d.defaclnamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(d.defaclacl) a "
        "WHERE d.defaclobjtype IN ('r', 'S') "
        "ORDER BY 1, 2, 3, 4"
    ),
    "present_tables": (
        "SELECT c.relname AS table_name FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = ANY(:tables) AND c.relkind = 'r' "
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
    "sequence_acl": (
        "SELECT s.relacl IS NULL AS owner_only FROM pg_catalog.pg_class s "
        "JOIN pg_catalog.pg_depend d ON d.objid = s.oid "
        "AND d.classid = 'pg_catalog.pg_class'::pg_catalog.regclass AND d.deptype = 'i' "
        "JOIN pg_catalog.pg_class t ON t.oid = d.refobjid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace "
        "JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid "
        "WHERE s.relkind = 'S' AND n.nspname = :schema AND t.relname = :table "
        "AND a.attname = :column"
    ),
    "probe_reach": (
        "SELECT pg_catalog.has_schema_privilege(:schema, 'USAGE') "
        "AND pg_catalog.has_table_privilege(c.oid, 'SELECT') AS readable "
        "FROM pg_catalog.pg_class c "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = 'schedule_publications' AND c.relkind = 'r'"
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
    "present_functions": (
        "SELECT p.proname AS function_name FROM pg_catalog.pg_proc p "
        "JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = :schema AND p.proname = ANY(:functions) AND p.pronargs = 0 "
        "ORDER BY 1"
    ),
    "present_trigger": (
        "SELECT pg_catalog.count(*) AS triggers FROM pg_catalog.pg_trigger t "
        "JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid "
        "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :schema AND c.relname = :table AND t.tgname = :name "
        "AND NOT t.tgisinternal"
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
    """One gate's outcome. `detail` holds catalog names, counts and booleans only."""

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

    Before: Q0-Q5, Q10. After: Q0, Q5-Q9, Q11. `before_acl_sha256` is the Q5 digest the
    `before` run reported; the `after` run stops without it. An open
    transaction on `connection` is refused, so the `READ ONLY` statement is
    always the transaction's first.
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
                _retired_roles(connection),
                _lock_sizing(connection),
                _runtime_role_reach(connection),
                _acl_snapshot(connection, phase, before_acl_sha256),
                _audit_sizing(connection),
            ]
        else:
            checks += [
                _acl_snapshot(connection, phase, before_acl_sha256),
                _no_extra_grant(connection),
                _vocabulary_at_head(connection),
                _runtime_reach(connection),
                _plane_objects(connection),
                _audit_vocabulary(connection),
            ]
        return tuple(checks)
    finally:
        transaction.rollback()


def _select(connection: Connection, key: str, **params: object) -> list[Mapping[str, object]]:
    return [dict(row) for row in connection.execute(text(STATEMENTS[key]), params).mappings()]


def _present(connection: Connection, tables: tuple[str, ...]) -> list[str]:
    return [
        str(row["table_name"])
        for row in _select(connection, "present_tables", schema=SCHEMA, tables=list(tables))
    ]


def _read_only(connection: Connection) -> PredeployCheck:
    setting = str(connection.execute(text(STATEMENTS["read_only"])).scalar_one())
    status = CheckStatus.HOLDS if setting == "on" else CheckStatus.STOP
    return PredeployCheck("Q0", "read_only_transaction", status, f"transaction_read_only={setting}")


def _default_privileges(connection: Connection) -> PredeployCheck:
    """Q1: no default privilege hands a new table or sequence to a forbidden grantee."""
    offending = sorted(
        {
            f"{row['role']}:{row['namespace'] or '<global>'}:{row['object_type']}:{row['grantee']}"
            for row in _select(connection, "default_privileges")
            if row["namespace"] in ("", SCHEMA) and row["grantee"] in _FORBIDDEN_GRANTEES
        }
    )
    if offending:
        return PredeployCheck("Q1", "default_privileges", CheckStatus.STOP, ",".join(offending))
    return PredeployCheck("Q1", "default_privileges", CheckStatus.HOLDS, "entries=0")


def _retired_roles(connection: Connection) -> PredeployCheck:
    """Q2: the S5 tables exist, and no publication holds a retired role (S6-U13)."""
    missing = sorted(set(S5_TABLES) - set(_present(connection, S5_TABLES)))
    if missing:
        return PredeployCheck(
            "Q2", "retired_roles", CheckStatus.STOP, f"absent={','.join(missing)}"
        )
    # The probe reads the table: a role that cannot is a stop, never an aborted run.
    readable = _select(connection, "probe_reach", schema=SCHEMA)
    if not readable or not readable[0]["readable"]:
        return PredeployCheck(
            "Q2", "retired_roles", CheckStatus.STOP, "retired_role_rows=unreadable"
        )
    retired = bool(connection.execute(RETIRED_ROLE_PROBE).scalar_one())
    status = CheckStatus.STOP if retired else CheckStatus.HOLDS
    return PredeployCheck(
        "Q2", "retired_roles", status, f"retired_role_rows={str(retired).lower()}"
    )


def _lock_sizing(connection: Connection) -> PredeployCheck:
    """Q3: estimated rows and size of every live table the revision locks (reported)."""
    rows = _select(connection, "lock_sizing", schema=SCHEMA, tables=list(LOCKED_TABLES))
    detail = ",".join(
        f"{row['table_name']}:rows~{row['estimated_rows']}:bytes={row['size_bytes']}"
        for row in rows
    )
    return PredeployCheck("Q3", "lock_sizing", CheckStatus.REPORT, detail)


def _runtime_role_reach(connection: Connection) -> PredeployCheck:
    """Q4: the connecting role reaches `record_links` the way it will reach the plane tables."""
    identity = _select(connection, "runtime_identity")[0]
    lineage = _select(connection, "lineage_reach", schema=SCHEMA)
    who = f"current={identity['current_role']},session={identity['session_role']}"
    if not lineage:
        return PredeployCheck(
            "Q4", "runtime_role_reach", CheckStatus.STOP, f"{who},record_links=absent"
        )
    row = lineage[0]
    owner = f"owner={row['owner']}"
    if row["owner"] == identity["current_role"]:
        reach = "owner"
    elif row["can_select"] and row["can_insert"]:
        reach = "granted"
    else:
        return PredeployCheck(
            "Q4", "runtime_role_reach", CheckStatus.STOP, f"{who},{owner},reach=none"
        )
    return PredeployCheck(
        "Q4", "runtime_role_reach", CheckStatus.HOLDS, f"{who},{owner},reach={reach}"
    )


def _acl_snapshot(
    connection: Connection, phase: PredeployPhase, before_acl_sha256: str | None
) -> PredeployCheck:
    """Q5: one digest over the ACL text of the 3 live tables, compared after the deploy."""
    row = _select(connection, "acl_digest", schema=SCHEMA, tables=list(ACL_TABLES))[0]
    digest = str(row["digest"]) if row["digest"] is not None else ""
    if row["tables"] != len(ACL_TABLES):
        return PredeployCheck("Q5", "acl_snapshot", CheckStatus.STOP, f"tables={row['tables']}")
    if phase is PredeployPhase.BEFORE:
        return PredeployCheck("Q5", "acl_snapshot", CheckStatus.REPORT, f"sha256={digest}")
    if before_acl_sha256 is None:
        return PredeployCheck(
            "Q5", "acl_snapshot", CheckStatus.STOP, f"sha256={digest},before=missing"
        )
    status = CheckStatus.HOLDS if before_acl_sha256 == digest else CheckStatus.STOP
    return PredeployCheck("Q5", "acl_snapshot", status, f"sha256={digest}")


def _absent_plane_tables(connection: Connection) -> list[str]:
    return sorted(set(PLANE_TABLES) - set(_present(connection, PLANE_TABLES)))


def _no_extra_grant(connection: Connection) -> PredeployCheck:
    """Q6: `PUBLIC` and the MCP roles hold nothing on a plane table; the sequence is owner-only."""
    missing = _absent_plane_tables(connection)
    if missing:
        return PredeployCheck(
            "Q6", "no_extra_grant", CheckStatus.STOP, f"absent={','.join(missing)}"
        )
    roles = ["public"] + [
        str(row["rolname"])
        for row in _select(connection, "present_roles", roles=list(PROFILE_ROLES))
    ]
    reached = sorted(
        f"{role}:{table}"
        for role in roles
        for table in PLANE_TABLES
        if _select(connection, "grantee_reach", role=role, schema=SCHEMA, table=table)[0]["reaches"]
    )
    sequence = _select(
        connection, "sequence_acl", schema=SCHEMA, table=_REFUSAL_TABLE, column=_REFUSAL_COLUMN
    )
    if not sequence or not sequence[0]["owner_only"]:
        reached.append(f"sequence:{_REFUSAL_TABLE}.{_REFUSAL_COLUMN}")
    if reached:
        return PredeployCheck("Q6", "no_extra_grant", CheckStatus.STOP, ",".join(reached))
    return PredeployCheck("Q6", "no_extra_grant", CheckStatus.HOLDS, f"roles={','.join(roles)}")


def _vocabulary_at_head(connection: Connection) -> PredeployCheck:
    """Q7: the widened lineage CHECKs name the S6 vocabulary; the role CHECK is retired."""
    missing: list[str] = []
    for name, (table, required, forbidden) in _HEAD_TEXTS.items():
        rows = _select(connection, "constraint_text", schema=SCHEMA, table=table, name=name)
        if not rows:
            missing.append(f"{name}:absent")
            continue
        definition = str(rows[0]["definition"])
        missing += [f"{name}:{token}" for token in required if f"'{token}'" not in definition]
        missing += [f"{name}:!{token}" for token in forbidden if f"'{token}'" in definition]
    if missing:
        return PredeployCheck("Q7", "vocabulary_at_head", CheckStatus.STOP, ",".join(missing))
    return PredeployCheck("Q7", "vocabulary_at_head", CheckStatus.HOLDS, ",".join(_HEAD_TEXTS))


def _runtime_reach(connection: Connection) -> PredeployCheck:
    """Q8: the connecting role holds `SELECT, INSERT` on the 11 tables, `UPDATE` on the ledger."""
    missing = _absent_plane_tables(connection)
    if missing:
        return PredeployCheck(
            "Q8", "runtime_reach", CheckStatus.STOP, f"absent={','.join(missing)}"
        )
    lacking = [
        f"{table}:{privilege}"
        for table in PLANE_TABLES
        for privilege in (
            ("SELECT", "INSERT", "UPDATE") if table == _UPDATED_TABLE else ("SELECT", "INSERT")
        )
        if not _select(
            connection, "runtime_reach", privilege=privilege, schema=SCHEMA, table=table
        )[0]["holds"]
    ]
    if lacking:
        return PredeployCheck("Q8", "runtime_reach", CheckStatus.STOP, ",".join(lacking))
    return PredeployCheck("Q8", "runtime_reach", CheckStatus.HOLDS, f"tables={len(PLANE_TABLES)}")


def _plane_objects(connection: Connection) -> PredeployCheck:
    """Q9: the 11 tables, the 15 functions and trigger G10 exist."""
    absent = [f"table:{table}" for table in _absent_plane_tables(connection)]
    present = {
        str(row["function_name"])
        for row in _select(
            connection, "present_functions", schema=SCHEMA, functions=list(PLANE_FUNCTIONS)
        )
    }
    absent += [f"function:{name}" for name in PLANE_FUNCTIONS if name not in present]
    table, trigger = _G10
    found = _select(connection, "present_trigger", schema=SCHEMA, table=table, name=trigger)
    if not found or found[0]["triggers"] != 1:
        absent.append(f"trigger:{trigger}")
    if absent:
        return PredeployCheck("Q9", "plane_objects", CheckStatus.STOP, ",".join(absent))
    return PredeployCheck(
        "Q9",
        "plane_objects",
        CheckStatus.HOLDS,
        f"tables={len(PLANE_TABLES)},functions={len(PLANE_FUNCTIONS)},trigger=1",
    )


def _audit_sizing(connection: Connection) -> PredeployCheck:
    """Q10: estimated rows and size of `knowledge.audit_events`, which revision B locks."""
    rows = _select(connection, "lock_sizing", schema=SCHEMA, tables=[AUDIT_TABLE])
    if not rows:
        return PredeployCheck("Q10", "audit_sizing", CheckStatus.STOP, f"absent={AUDIT_TABLE}")
    row = rows[0]
    detail = f"{AUDIT_TABLE}:rows~{row['estimated_rows']},bytes={row['size_bytes']}"
    return PredeployCheck("Q10", "audit_sizing", CheckStatus.REPORT, detail)


def _audit_vocabulary(connection: Connection) -> PredeployCheck:
    """Q11: the restated audit CHECKs name the 26 plane capabilities and the 3 purposes."""
    missing: list[str] = []
    for name, required in _AUDIT_TEXTS.items():
        rows = _select(connection, "constraint_text", schema=SCHEMA, table=AUDIT_TABLE, name=name)
        if not rows:
            missing.append(f"{name}:absent")
            continue
        definition = str(rows[0]["definition"])
        missing += [f"{name}:{token}" for token in required if f"'{token}'" not in definition]
    if missing:
        return PredeployCheck("Q11", "audit_vocabulary", CheckStatus.STOP, ",".join(missing))
    return PredeployCheck(
        "Q11",
        "audit_vocabulary",
        CheckStatus.HOLDS,
        f"capabilities={len(_S63_CAPABILITIES)},purposes={len(_S63_PURPOSES)}",
    )
