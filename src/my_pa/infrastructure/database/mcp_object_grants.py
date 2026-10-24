"""Creator-bound grants for explicitly reviewed future migration objects.

Use inside the existing migration revision transaction, immediately around one
CREATE. It never scans/regrants existing objects, changes default privileges,
creates roles or elevates the migration principal. No live migration calls it
until that exact migration is separately reviewed and authorized.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection, text

_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_SCHEMAS = frozenset(
    {
        "calendar",
        "construction",
        "contacts",
        "core",
        "email",
        "financial",
        "knowledge",
        "procore",
        "schedule",
    }
)
_PROTECTED = frozenset(
    {
        ("knowledge", "audit_events"),
        ("knowledge", "record_events"),
        ("knowledge", "record_event_sequences"),
        ("knowledge", "native_apple_bridge_credentials"),
        ("knowledge", "goodnotes_pull_sessions"),
        ("knowledge", "native_admission_authorities"),
        ("knowledge", "native_live_activation_gates"),
        ("knowledge", "native_apple_read_grants"),
        ("core", "schema_migrations"),
        ("core", "raw_content_policy_state"),
        ("core", "interactive_chat_sessions"),
        ("core", "second_brain_mcp_claude_desktop_config_previews"),
        ("core", "second_brain_mcp_server_config_snapshots"),
        ("construction", "construction_delta_tokens"),
    }
)


@dataclass(frozen=True)
class McpObjectGrant:
    schema: str
    name: str
    creator: str
    classification: Literal["application_read", "application_write", "excluded"]
    kind: Literal["r", "p", "v", "m", "S"]
    review_id: str
    # Sequence declarations must identify an existing, already approved writable table.
    sequence_table: tuple[str, str] | None = None


class McpObjectGrantError(ValueError):
    def __init__(self) -> None:
        super().__init__("creator-bound MCP object grant refused")


def _qualified(schema: str, name: str) -> str:
    if not _IDENTIFIER.fullmatch(schema) or not _IDENTIFIER.fullmatch(name):
        raise McpObjectGrantError()
    return f'"{schema}"."{name}"'


@contextmanager
def grant_created_mcp_object(connection: Connection, spec: McpObjectGrant) -> Iterator[None]:
    """Keep CREATE and grants atomic even if a caller catches a validation error."""
    if not connection.in_transaction():
        raise McpObjectGrantError()
    with connection.begin_nested(), _grant_created_mcp_object(connection, spec):
        yield


@contextmanager
def _grant_created_mcp_object(connection: Connection, spec: McpObjectGrant) -> Iterator[None]:
    """Declare before CREATE; grant and check after CREATE, before owner transfer.

    The reviewed CREATE body must not switch roles or transfer ownership. This
    observes the effective creator at both boundaries, not a catalog creation
    timestamp/provenance field (which PostgreSQL does not provide).
    """
    qualified = _qualified(spec.schema, spec.name)
    if (
        not connection.in_transaction()
        or not _IDENTIFIER.fullmatch(spec.creator)
        or not spec.review_id.strip()
        or spec.kind not in {"r", "p", "v", "m", "S"}
        or spec.classification not in {"application_read", "application_write", "excluded"}
    ):
        raise McpObjectGrantError()
    protected = (
        spec.schema not in _SCHEMAS
        or (spec.schema, spec.name) in _PROTECTED
        or spec.name.startswith("intelligence_")
    )
    if protected and spec.classification != "excluded":
        raise McpObjectGrantError()
    transaction = connection.get_transaction()
    creator = connection.exec_driver_sql("SELECT current_user").scalar_one()
    if (
        creator != spec.creator
        or connection.execute(
            text("SELECT to_regclass(:object)"), {"object": qualified}
        ).scalar_one()
        is not None
    ):
        raise McpObjectGrantError()
    yield
    if (
        connection.get_transaction() is not transaction
        or connection.exec_driver_sql("SELECT current_user").scalar_one() != creator
    ):
        raise McpObjectGrantError()
    row = connection.execute(
        text(
            "SELECT c.relkind, pg_get_userbyid(c.relowner) FROM pg_class c "
            "WHERE c.oid=to_regclass(:object)"
        ),
        {"object": qualified},
    ).one_or_none()
    if row is None or row[0] != spec.kind or row[1] != creator:
        raise McpObjectGrantError()
    writable = spec.classification == "application_write"
    excluded = spec.classification == "excluded"
    if spec.kind == "S" and not excluded:
        if not writable or spec.sequence_table is None:
            raise McpObjectGrantError()
        parent_schema, parent_name = spec.sequence_table
        if (
            parent_schema not in _SCHEMAS
            or spec.sequence_table in _PROTECTED
            or parent_name.startswith("intelligence_")
        ):
            raise McpObjectGrantError()
        parent = _qualified(*spec.sequence_table)
        eligible = connection.execute(
            text(
                "SELECT EXISTS(SELECT 1 FROM pg_depend WHERE classid='pg_class'::regclass "
                "AND objid=to_regclass(:object) AND refclassid='pg_class'::regclass "
                "AND refobjid=to_regclass(:parent) AND deptype IN ('a','i')) "
                "AND has_table_privilege('my_pa_mcp_rw',:parent,'INSERT')"
            ),
            {"object": qualified, "parent": parent},
        ).scalar_one()
        if not eligible:
            raise McpObjectGrantError()
        connection.exec_driver_sql(f"GRANT USAGE ON SEQUENCE {qualified} TO my_pa_mcp_rw")
    elif not excluded:
        if writable and spec.kind not in {"r", "p"}:
            raise McpObjectGrantError()
        connection.exec_driver_sql(
            f"GRANT SELECT ON TABLE {qualified} TO my_pa_mcp_ro, my_pa_mcp_rw"
        )
        if writable:
            connection.exec_driver_sql(
                f"GRANT INSERT, UPDATE, DELETE ON TABLE {qualified} TO my_pa_mcp_rw"
            )
    # Check effective permissions, including PUBLIC/default grants. Never repair
    # shared policies here: an unexpected permission aborts the revision instead.
    for role in ("my_pa_mcp_ro", "my_pa_mcp_rw"):
        if spec.kind == "S":
            permissions = {
                "USAGE": writable and not excluded and role == "my_pa_mcp_rw",
                "SELECT": False,
                "UPDATE": False,
            }
            predicate = "has_sequence_privilege"
        else:
            permissions = {
                "SELECT": not excluded,
                "INSERT": writable and not excluded and role == "my_pa_mcp_rw",
                "UPDATE": writable and not excluded and role == "my_pa_mcp_rw",
                "DELETE": writable and not excluded and role == "my_pa_mcp_rw",
                "TRUNCATE": False,
                "REFERENCES": False,
                "TRIGGER": False,
                "MAINTAIN": False,
            }
            predicate = "has_table_privilege"
        for privilege, expected in permissions.items():
            expression = f"{predicate}(:role,:object,:privilege)"
            if spec.kind != "S" and privilege in {"SELECT", "INSERT", "UPDATE", "REFERENCES"}:
                expression += " OR has_any_column_privilege(:role,:object,:privilege)"
            actual = connection.execute(
                text(f"SELECT {expression}"),
                {"role": role, "object": qualified, "privilege": privilege},
            ).scalar_one()
            if actual is not expected:
                raise McpObjectGrantError()
