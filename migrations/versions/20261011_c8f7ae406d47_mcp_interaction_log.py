"""Create the append-only MCP interaction log in its own `observability` schema.

Revision ID: c8f7ae406d47
Revises: a591b81f10a2
Create Date: 2026-10-11

Written against the then sole head `a591b81f10a2` (authenticated with
`alembic heads` immediately before writing); no merge revision exists. It:

1. creates the schema `observability`. The log is operational telemetry of the
   remote OAuth MCP gateway, deliberately **not** placed in `knowledge` or
   `audit`: it is not the audit ledger, it stores redacted request and response
   bodies that the audit design forbids there, and a separate schema is a
   separate `USAGE`/grant boundary that leaves the closed-set guards over the
   `knowledge` and `audit` schemas untouched;
2. creates `observability.mcp_interactions`, one row per HTTP exchange on the
   remote `/mcp` route, with its CHECKs and six lookup indexes, as frozen DDL
   text (no package import, no live declaration, no enum: `D-48`, `D-69`);
3. installs four triggers that bind every role, the owner included:
   - `BEFORE INSERT` assigns `recorded_at := clock_timestamp()`, so a caller
     can never backdate a row past the retention window it is keyed on;
   - `BEFORE UPDATE` always refuses with `restrict_violation`;
   - `BEFORE DELETE` refuses with `restrict_violation` unless the transaction
     set `my_pa.mcp_interaction_purge = 'on'` **and** the row is older than
     the fixed 14-day retention (`recorded_at < clock_timestamp() - 14 days`).
     That is the only deletion the table admits, and the operator purge is its
     only caller;
   - `BEFORE TRUNCATE` (statement level) always refuses.

It grants nothing and creates no role. Cluster roles and grants are provisioned
outside Alembic, by the idempotent operator provisioner pattern of
`src/my_pa/infrastructure/database/record_event_roles.py`; the append-only
guarantee here is the triggers, which hold regardless of which role writes. A
table owner can still drop a trigger; the triggers are defence in depth.

`downgrade` drops, in reverse order, the four triggers, their functions, the
table (with its indexes) and the schema. **It discards the interaction log**:
the rows are bounded-retention operational telemetry, not user-authored or
evidential records, and nothing else references them. That is the one
deliberate difference from the refuse-while-rows-exist downgrades of the
ledgers in `knowledge`.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c8f7ae406d47"
down_revision: str | None = "a591b81f10a2"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "observability"
TABLE: Final = "mcp_interactions"

#: Fixed retention, in days. The purge in
#: `my_pa.infrastructure.persistence.mcp_interactions` keys on the same figure.
RETENTION: Final = "interval '14 days'"

_TABLE_DDL: Final = f"""
    CREATE TABLE {SCHEMA}.{TABLE} (
      interaction_id text NOT NULL,
      recorded_at timestamptz NOT NULL,
      started_at timestamptz NOT NULL,
      latency_ms double precision NOT NULL,
      http_method text NOT NULL,
      http_status integer,
      oauth_client_id text,
      principal_id text,
      principal_kind text,
      mcp_session_id text,
      jsonrpc_method text,
      jsonrpc_id text,
      tool_name text,
      capability text,
      correlation_id text,
      outcome text NOT NULL,
      error_code text,
      request_bytes bigint NOT NULL,
      response_bytes bigint NOT NULL,
      request_sha256 text NOT NULL,
      response_sha256 text NOT NULL,
      request_truncated boolean NOT NULL,
      response_truncated boolean NOT NULL,
      request_body jsonb,
      response_body jsonb,
      request_body_text text,
      response_body_text text,
      request_headers jsonb NOT NULL,
      diagnostics jsonb NOT NULL,
      CONSTRAINT mcp_interactions_pkey PRIMARY KEY (interaction_id),
      CONSTRAINT mcp_interaction_id_is_an_opaque_identifier
        CHECK (interaction_id ~ '^mcpi_[0-9a-f]{{32}}$'),
      CONSTRAINT mcp_interaction_latency_is_not_negative CHECK (latency_ms >= 0),
      CONSTRAINT mcp_interaction_outcome_is_known CHECK (outcome IN (
        'ok', 'tool_error', 'jsonrpc_error', 'http_error', 'auth_refused',
        'unavailable', 'unparsed'
      )),
      CONSTRAINT mcp_interaction_request_bytes_are_not_negative CHECK (request_bytes >= 0),
      CONSTRAINT mcp_interaction_response_bytes_are_not_negative CHECK (response_bytes >= 0),
      CONSTRAINT mcp_interaction_request_sha256_is_a_digest
        CHECK (request_sha256 ~ '^[0-9a-f]{{64}}$'),
      CONSTRAINT mcp_interaction_response_sha256_is_a_digest
        CHECK (response_sha256 ~ '^[0-9a-f]{{64}}$'),
      CONSTRAINT mcp_interaction_request_body_is_one_form
        CHECK (request_body IS NULL OR request_body_text IS NULL),
      CONSTRAINT mcp_interaction_response_body_is_one_form
        CHECK (response_body IS NULL OR response_body_text IS NULL),
      CONSTRAINT mcp_interaction_truncated_request_has_no_json_body
        CHECK (NOT request_truncated OR request_body IS NULL),
      CONSTRAINT mcp_interaction_truncated_response_has_no_json_body
        CHECK (NOT response_truncated OR response_body IS NULL)
    )
    """

#: `(name, definition)`; dropped with the table on downgrade.
_INDEXES: Final = (
    ("mcp_interactions_by_recorded_at", "(recorded_at)"),
    ("mcp_interactions_by_client", "(oauth_client_id, recorded_at)"),
    ("mcp_interactions_by_capability", "(capability, recorded_at)"),
    ("mcp_interactions_by_tool", "(tool_name, recorded_at)"),
    ("mcp_interactions_by_correlation", "(correlation_id) WHERE correlation_id IS NOT NULL"),
    ("mcp_interactions_by_outcome", "(outcome, recorded_at)"),
)

#: `(function, body)`, in creation order.
_FUNCTIONS: Final = (
    (
        "mcp_interactions_stamp_recorded_at",
        """
        BEGIN
          NEW.recorded_at := clock_timestamp();
          RETURN NEW;
        END;
        """,
    ),
    (
        "mcp_interactions_refuse_change",
        """
        BEGIN
          RAISE EXCEPTION '% refuses %', TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'restrict_violation';
          RETURN NULL;
        END;
        """,
    ),
    (
        "mcp_interactions_guard_delete",
        f"""
        BEGIN
          IF current_setting('my_pa.mcp_interaction_purge', true) = 'on'
             AND OLD.recorded_at < clock_timestamp() - {RETENTION} THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION '% refuses DELETE outside the retention purge', TG_TABLE_NAME
            USING ERRCODE = 'restrict_violation';
        END;
        """,
    ),
)

#: `(trigger, timing, level, function)`, in creation order.
_TRIGGERS: Final = (
    (
        "mcp_interactions_stamp_recorded_at",
        "BEFORE INSERT",
        "ROW",
        "mcp_interactions_stamp_recorded_at",
    ),
    ("mcp_interactions_refuse_update", "BEFORE UPDATE", "ROW", "mcp_interactions_refuse_change"),
    ("mcp_interactions_guard_delete", "BEFORE DELETE", "ROW", "mcp_interactions_guard_delete"),
    (
        "mcp_interactions_refuse_truncate",
        "BEFORE TRUNCATE",
        "STATEMENT",
        "mcp_interactions_refuse_change",
    ),
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    op.execute(_TABLE_DDL)
    for name, definition in _INDEXES:
        op.execute(f"CREATE INDEX {name} ON {SCHEMA}.{TABLE} {definition}")
    for function, body in _FUNCTIONS:
        op.execute(
            f"CREATE FUNCTION {SCHEMA}.{function}() RETURNS trigger LANGUAGE plpgsql AS $${body}$$"
        )
    for trigger, timing, level, function in _TRIGGERS:
        op.execute(
            f"CREATE TRIGGER {trigger} {timing} ON {SCHEMA}.{TABLE} "
            f"FOR EACH {level} EXECUTE FUNCTION {SCHEMA}.{function}()"
        )


def downgrade() -> None:
    # Discards the interaction log (see the module docstring).
    for trigger, _timing, _level, _function in reversed(_TRIGGERS):
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{TABLE}")
    for function, _body in reversed(_FUNCTIONS):
        op.execute(f"DROP FUNCTION {SCHEMA}.{function}()")
    op.execute(f"DROP TABLE {SCHEMA}.{TABLE} RESTRICT")
    op.execute(f"DROP SCHEMA {SCHEMA} RESTRICT")
