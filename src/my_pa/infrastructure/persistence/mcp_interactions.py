"""Persisting and reading the MCP interaction log (`observability.mcp_interactions`).

The table is append-only at the database (revision `c8f7ae406d47`): a trigger
assigns `recorded_at`, UPDATE and TRUNCATE always refuse, and DELETE refuses
unless the transaction set `my_pa.mcp_interaction_purge = 'on'` *and* the row is
older than the fixed retention. `purge_expired` is the only code path that sets
that switch and the only DELETE against the table in the source tree
(`tests/architecture/test_mcp_interactions_have_one_delete.py` holds that).

This module is the sink for the gateway's capture middleware and the reader for
the operator CLI. It takes a caller-owned `Connection` and never commits: the
caller decides the transaction. Nothing here logs a row, a body, or a header.

The table is declared here on its own `MetaData` rather than in `tables.py`,
for the reason `user_accounts.py` gives for the `identity` schema: the
`observability` schema has a different writer (the gateway's background
recorder), a different lifetime (14-day retention) and no Principal partition,
and the frozen revision names the table explicitly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Connection,
    DateTime,
    Double,
    Integer,
    MetaData,
    Row,
    Select,
    Table,
    Text,
    insert,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

__all__ = [
    "BODY_CAP_BYTES",
    "COLUMNS",
    "INSERT_COLUMNS",
    "MAX_PAGE",
    "MAX_PURGE_BATCH",
    "OBSERVABILITY_METADATA",
    "OUTCOMES",
    "RETENTION_DAYS",
    "Interaction",
    "InteractionSummary",
    "PurgeResult",
    "get_interaction",
    "insert_interaction",
    "list_interactions",
    "mcp_interactions",
    "purge_expired",
    "search_interactions",
]

#: Fixed retention, in days. The revision's DELETE trigger holds the same figure.
RETENTION_DAYS: Final = 14
#: Per-body ceiling applied by the capture side to the redacted serialization.
#: Exported for readers; this module does not re-measure bodies.
BODY_CAP_BYTES: Final = 262_144
#: Largest page `list_interactions` / `search_interactions` return.
MAX_PAGE: Final = 1_000
#: Largest single purge batch.
MAX_PURGE_BATCH: Final = 10_000
#: The revision's closed outcome set, mirrored for argument validation.
OUTCOMES: Final = frozenset(
    {"ok", "tool_error", "jsonrpc_error", "http_error", "auth_refused", "unavailable", "unparsed"}
)

OBSERVABILITY_METADATA = MetaData(schema="observability")

mcp_interactions = Table(
    "mcp_interactions",
    OBSERVABILITY_METADATA,
    Column("interaction_id", Text, primary_key=True),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("latency_ms", Double, nullable=False),
    Column("http_method", Text, nullable=False),
    Column("http_status", Integer),
    Column("oauth_client_id", Text),
    Column("principal_id", Text),
    Column("principal_kind", Text),
    Column("mcp_session_id", Text),
    Column("jsonrpc_method", Text),
    Column("jsonrpc_id", Text),
    Column("tool_name", Text),
    Column("capability", Text),
    Column("correlation_id", Text),
    Column("outcome", Text, nullable=False),
    Column("error_code", Text),
    Column("request_bytes", BigInteger, nullable=False),
    Column("response_bytes", BigInteger, nullable=False),
    Column("request_sha256", Text, nullable=False),
    Column("response_sha256", Text, nullable=False),
    Column("request_truncated", Boolean, nullable=False),
    Column("response_truncated", Boolean, nullable=False),
    # Bare `JSONB`, not `JSONB(none_as_null=True)`: `JSONB.__init__` is untyped at
    # the declared SQLAlchemy floor, so the call form fails `no-untyped-call` in
    # the `dependency-floor` job alone (the trap `tables.py` records at
    # `structured_content`), and a `# type: ignore` is itself an error at the
    # installed version under `warn_unused_ignores`. Bare `JSONB` binds a Python
    # `None` as the JSON value `null`, so `insert_interaction` omits an absent
    # body from the statement and the server writes SQL NULL instead.
    Column("request_body", JSONB),
    Column("response_body", JSONB),
    Column("request_body_text", Text),
    Column("response_body_text", Text),
    Column("request_headers", JSONB, nullable=False),
    Column("diagnostics", JSONB, nullable=False),
)

#: Every column, in table order.
COLUMNS: Final = tuple(column.name for column in mcp_interactions.columns)
#: What a caller supplies: every column except the DB-assigned `recorded_at`.
INSERT_COLUMNS: Final = frozenset(COLUMNS) - {"recorded_at"}
#: Nullable JSONB columns whose `None` must reach the server as SQL NULL.
_NULLABLE_JSON_BODIES: Final = frozenset({"request_body", "response_body"})

_SUMMARY_COLUMNS: Final = (
    "interaction_id",
    "recorded_at",
    "started_at",
    "latency_ms",
    "http_method",
    "http_status",
    "oauth_client_id",
    "principal_id",
    "principal_kind",
    "mcp_session_id",
    "jsonrpc_method",
    "jsonrpc_id",
    "tool_name",
    "capability",
    "correlation_id",
    "outcome",
    "error_code",
    "request_bytes",
    "response_bytes",
    "request_truncated",
    "response_truncated",
)


@dataclass(frozen=True, slots=True)
class InteractionSummary:
    """One exchange without its bodies, headers or diagnostics (list/search)."""

    interaction_id: str
    recorded_at: datetime
    started_at: datetime
    latency_ms: float
    http_method: str
    http_status: int | None
    oauth_client_id: str | None
    principal_id: str | None
    principal_kind: str | None
    mcp_session_id: str | None
    jsonrpc_method: str | None
    jsonrpc_id: str | None
    tool_name: str | None
    capability: str | None
    correlation_id: str | None
    outcome: str
    error_code: str | None
    request_bytes: int
    response_bytes: int
    request_truncated: bool
    response_truncated: bool


@dataclass(frozen=True, slots=True)
class Interaction:
    """One exchange in full (show)."""

    interaction_id: str
    recorded_at: datetime
    started_at: datetime
    latency_ms: float
    http_method: str
    http_status: int | None
    oauth_client_id: str | None
    principal_id: str | None
    principal_kind: str | None
    mcp_session_id: str | None
    jsonrpc_method: str | None
    jsonrpc_id: str | None
    tool_name: str | None
    capability: str | None
    correlation_id: str | None
    outcome: str
    error_code: str | None
    request_bytes: int
    response_bytes: int
    request_sha256: str
    response_sha256: str
    request_truncated: bool
    response_truncated: bool
    request_body: object
    response_body: object
    request_body_text: str | None
    response_body_text: str | None
    request_headers: Mapping[str, object]
    diagnostics: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """`deleted` rows this call removed (0 on a dry run); `remaining` expired rows after it."""

    deleted: int
    remaining: int


def insert_interaction(connection: Connection, row: Mapping[str, object]) -> None:
    """Append one exchange. `row` must carry exactly `INSERT_COLUMNS`.

    `recorded_at` is refused here and, if supplied by any other path, overwritten
    by the database. JSONB columns take Python mappings, sequences or scalars and
    are bound as JSON, never interpolated.

    A `None` body (`request_body` / `response_body`) is omitted from the
    statement, so the column is SQL NULL -- never the JSON value `null`, which is
    what bare `JSONB` would bind and which the body-form and truncation CHECKs
    would read as a present body. **A wire body that is literally the JSON
    `null` is therefore stored as SQL NULL too**, deliberately: the store has one
    representation of "no JSON body", and that wire case stays distinguishable by
    `diagnostics.capture.<side>_parse == "json"` with a non-zero byte count and
    its digest. The key set is still validated on the caller's mapping.
    """
    keys = frozenset(row)
    if keys != INSERT_COLUMNS:
        missing = sorted(INSERT_COLUMNS - keys)
        unexpected = sorted(keys - INSERT_COLUMNS)
        raise ValueError(
            f"interaction row columns differ: missing={missing} unexpected={unexpected}"
        )
    values = {
        key: value
        for key, value in row.items()
        if not (key in _NULLABLE_JSON_BODIES and value is None)
    }
    connection.execute(insert(mcp_interactions).values(values))


def purge_expired(connection: Connection, *, batch_size: int, dry_run: bool) -> PurgeResult:
    """Delete at most `batch_size` rows older than `RETENTION_DAYS`, oldest first.

    Sets the transaction-local purge switch, deletes one bounded batch, and turns
    the switch off again before returning, so no later statement in the same
    transaction inherits the exemption. The age test uses the database clock, as
    the trigger does. A dry run deletes nothing and reports every expired row as
    remaining. The caller commits.
    """
    if not 1 <= batch_size <= MAX_PURGE_BATCH:
        raise ValueError(f"batch_size must be between 1 and {MAX_PURGE_BATCH}")
    deleted = 0
    if not dry_run:
        connection.execute(text("SET LOCAL my_pa.mcp_interaction_purge = 'on'"))
        result = connection.execute(
            text(
                "DELETE FROM observability.mcp_interactions AS doomed "
                "USING ("
                "  SELECT interaction_id FROM observability.mcp_interactions "
                "  WHERE recorded_at < clock_timestamp() - make_interval(days => :days) "
                "  ORDER BY recorded_at, interaction_id "
                "  LIMIT :batch FOR UPDATE SKIP LOCKED"
                ") AS expired "
                "WHERE doomed.interaction_id = expired.interaction_id"
            ),
            {"days": RETENTION_DAYS, "batch": batch_size},
        )
        deleted = int(result.rowcount or 0)
        # Not in a `finally`: a failed DELETE aborts the transaction, which
        # discards the LOCAL setting with it, and a reset there would mask the error.
        connection.execute(text("SET LOCAL my_pa.mcp_interaction_purge = 'off'"))
    remaining = int(
        connection.scalar(
            text(
                "SELECT count(*) FROM observability.mcp_interactions "
                "WHERE recorded_at < clock_timestamp() - make_interval(days => :days)"
            ),
            {"days": RETENTION_DAYS},
        )
        or 0
    )
    return PurgeResult(deleted=deleted, remaining=remaining)


def get_interaction(connection: Connection, interaction_id: str) -> Interaction | None:
    """The full row, or `None` when no such interaction exists."""
    row = connection.execute(
        select(mcp_interactions).where(mcp_interactions.c.interaction_id == interaction_id)
    ).one_or_none()
    return None if row is None else Interaction(**row._asdict())


def list_interactions(connection: Connection, *, limit: int) -> tuple[InteractionSummary, ...]:
    """The newest `limit` exchanges, newest first."""
    return search_interactions(connection, limit=limit)


def search_interactions(
    connection: Connection,
    *,
    client_id: str | None = None,
    tool: str | None = None,
    capability: str | None = None,
    correlation_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    outcome: str | None = None,
    limit: int,
) -> tuple[InteractionSummary, ...]:
    """Exchanges matching every given filter, newest first.

    `since` is inclusive and `until` exclusive, both on `recorded_at`. Filters
    are exact matches; `outcome` must be one of `OUTCOMES`.
    """
    if not 1 <= limit <= MAX_PAGE:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE}")
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError("unknown outcome")
    for bound in (since, until):
        if bound is not None and bound.tzinfo is None:
            raise ValueError("time bounds must be timezone-aware")
    table = mcp_interactions
    statement: Select[tuple[object, ...]] = select(*(table.c[name] for name in _SUMMARY_COLUMNS))
    if client_id is not None:
        statement = statement.where(table.c.oauth_client_id == client_id)
    if tool is not None:
        statement = statement.where(table.c.tool_name == tool)
    if capability is not None:
        statement = statement.where(table.c.capability == capability)
    if correlation_id is not None:
        statement = statement.where(table.c.correlation_id == correlation_id)
    if since is not None:
        statement = statement.where(table.c.recorded_at >= since)
    if until is not None:
        statement = statement.where(table.c.recorded_at < until)
    if outcome is not None:
        statement = statement.where(table.c.outcome == outcome)
    statement = statement.order_by(table.c.recorded_at.desc(), table.c.interaction_id.desc()).limit(
        limit
    )
    return tuple(_summary(row) for row in connection.execute(statement))


def _summary(row: Row[tuple[object, ...]]) -> InteractionSummary:
    return InteractionSummary(**row._asdict())
