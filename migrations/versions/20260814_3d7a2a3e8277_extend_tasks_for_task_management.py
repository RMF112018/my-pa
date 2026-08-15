"""Extend `knowledge.tasks` with the task-management foundation, additively.

WP-TM-01. `MYPA-PR104-TASK-MANAGEMENT-POST-IMPLEMENTATION-AUDIT-20260814-001`
found that open PR #104's own migration and lineage collide with current
`main` and must not be reused wholesale. This revision is native to `main`'s
history: it revises `4f6a9c2d8e17` directly, adds nothing PR #104's schema
did not also need, and carries none of that PR's migration identity.

**Additive, not a drop-and-recreate.** Every row `8f2b6c4d1a37` created in
`knowledge.tasks` survives this revision unchanged in every column that
revision defined. Nothing here drops a column, narrows a type, or replaces
`knowledge.tasks` — it gains seven nullable-or-defaulted columns, a foreign key
to a new satellite table, and two new tables. `knowledge.commitments` and
`knowledge.decisions` are untouched: the richer lifecycle this revision adds is
a Task-only concern, precisely because a Task is the one continuity object with
no counterparty and therefore the one this codebase executes step by step.

* `lifecycle_state` — `('open', 'in_progress', 'waiting', 'blocked',
  'completed', 'cancelled')`, `NOT NULL DEFAULT 'open'`. **The migration of
  existing `open`/`closed` semantics is explicit, not a guess dressed up as
  one.** Every existing `open` row already becomes `lifecycle_state = 'open'`
  by that same default; every existing `closed` row is backfilled to
  `'completed'` by the `UPDATE` below, because `completed` is the closest
  fact this schema ever held about a closed Task — there is no cancellation
  concept in the data this revision migrates forward, and inventing one to
  reclassify some existing rows as `cancelled` would be exactly the kind of
  fabricated distinction `8f2b6c4d1a37`'s own `pulse_items` refusal exists to
  rule out elsewhere in this same file's history. `tests/schema/
  test_task_schema_migration.py::test_the_backfill_maps_every_legacy_state_
  explicitly` seeds one row of each legacy state and checks the mapping is
  exactly this and nothing else.
* `a_task_lifecycle_state_matches_its_legacy_state` is the CHECK that keeps
  `lifecycle_state` and the untouched `state` column from drifting apart from
  this point forward: `lifecycle_state` is terminal
  (`completed`/`cancelled`) if and only if `state = 'closed'`.
* `priority` — nullable `('p1', 'p2', 'p3', 'p4')`, Principal-assigned and
  never written by a ranking derivation.
* `scheduled_at`, `deferred_until`, `archived_at` — nullable timestamps,
  orthogonal to `lifecycle_state`. None carries a CHECK relating it back to the
  lifecycle, because none of the three is a lifecycle transition.
* `version` — `integer NOT NULL DEFAULT 1`, the optimistic-concurrency counter
  `task_history` reads before and after every attempted mutation.
* `recurrence_id` — nullable, `FOREIGN KEY` to the new
  `knowledge.task_recurrences`, naming the series a generated occurrence
  belongs to.
* `knowledge.task_recurrences` — one row per recurring series, independent of
  any one occurrence Task. `next_occurrence_at` is the *one* actionable
  occurrence the series holds at a time; nothing here enumerates a calendar of
  future occurrences in advance.
* `knowledge.task_history` — one append-only mutation receipt per attempted
  Task write: what this build normalised the request into, who or what asked,
  the version before and after, and the outcome. Never the caller's raw
  request — `client_context` is a bounded client/tool label, not a request
  body, on the rule `AGENTS.md` section 5 states for every log in this
  codebase.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72`
states: no revision derives a closed-set constraint from a domain enum. The
vocabularies this revision writes are checked against
`my_pa.domain.task.lifecycle`, `my_pa.domain.task.recurrence`, and
`my_pa.domain.task.history` at head by
`tests/schema/test_task_schema_migration.py`.

**Raw SQL rather than a copy of the live declaration**, exactly as
`8f2b6c4d1a37` and every revision since `d2e3f4a5b6c7` do: this revision
imports no table object, so it cannot start meaning something else when
`tables.py` is next edited. The cost is drift, and it is paid by
`tests/schema/test_task_schema_migration.py`, which reads the created and
altered columns, constraints, and indexes out of `pg_catalog` and compares
them against `METADATA` on a live server.

Revision ID: 3d7a2a3e8277
Revises: 4f6a9c2d8e17
Create Date: 2026-08-14
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "3d7a2a3e8277"
down_revision: str | None = "4f6a9c2d8e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"

#: The identifier suffix rule every partitioned table restates.
_SUFFIX: Final = "[A-Za-z0-9]{8,64}"


def _create_task_recurrences() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.task_recurrences (
          recurrence_id text PRIMARY KEY
            CONSTRAINT recurrence_id_is_an_opaque_identifier
            CHECK (recurrence_id ~ '^trec_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          frequency text NOT NULL
            CONSTRAINT a_task_recurrence_frequency_is_known
            CHECK (frequency IN ('daily', 'monthly', 'selected_weekdays', 'weekdays', 'weekly')),
          interval integer NOT NULL DEFAULT 1
            CONSTRAINT a_task_recurrence_interval_is_positive
            CHECK (interval >= 1),
          weekdays jsonb NOT NULL DEFAULT '[]'::jsonb
            CONSTRAINT a_task_recurrence_weekdays_is_a_json_array_of_small_ints
            CHECK (jsonb_typeof(weekdays) = 'array'),
          timezone text NOT NULL
            CONSTRAINT a_task_recurrence_timezone_is_not_blank
            CHECK (length(trim(timezone)) > 0),
          anchor_at timestamptz NOT NULL,
          next_occurrence_at timestamptz,
          cancelled_at timestamptz,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT a_cancelled_task_recurrence_holds_no_next_occurrence
            CHECK (cancelled_at IS NULL OR next_occurrence_at IS NULL)
        )
        """
    )
    op.execute(
        f"CREATE INDEX task_recurrences_by_principal ON {SCHEMA}.task_recurrences (principal_id)"
    )


def _extend_tasks() -> None:
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN lifecycle_state text NOT NULL DEFAULT 'open'"
    )
    # The explicit backfill this revision's docstring commits to: every
    # existing `closed` row becomes `completed`, the closest fact this schema
    # ever held about it. Every existing `open` row already carries the
    # column default and needs no further statement.
    op.execute(
        f"UPDATE {SCHEMA}.tasks SET lifecycle_state = 'completed' WHERE state = 'closed'"  # noqa: S608
    )
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN priority text")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN scheduled_at timestamptz")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN deferred_until timestamptz")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN archived_at timestamptz")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN version integer NOT NULL DEFAULT 1")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN recurrence_id text")

    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT a_task_lifecycle_state_is_known "
        "CHECK (lifecycle_state IN "
        "('blocked', 'cancelled', 'completed', 'in_progress', 'open', 'waiting'))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        "ADD CONSTRAINT a_task_lifecycle_state_matches_its_legacy_state "
        "CHECK ((lifecycle_state IN ('completed', 'cancelled')) = (state = 'closed'))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT a_task_priority_is_known "
        "CHECK (priority IS NULL OR priority IN ('p1', 'p2', 'p3', 'p4'))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT a_task_version_is_positive CHECK (version >= 1)"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT a_task_recurrence_is_an_opaque_identifier "
        f"CHECK (recurrence_id IS NULL OR recurrence_id ~ '^trec_{_SUFFIX}$')"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT tasks_recurrence_id_fkey "
        f"FOREIGN KEY (recurrence_id) REFERENCES {SCHEMA}.task_recurrences (recurrence_id)"
    )

    op.execute(
        f"CREATE INDEX tasks_by_principal_lifecycle_state "
        f"ON {SCHEMA}.tasks (principal_id, lifecycle_state)"
    )
    op.execute(f"CREATE INDEX tasks_by_recurrence ON {SCHEMA}.tasks (recurrence_id)")


def _create_task_history() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.task_history (
          history_id text PRIMARY KEY
            CONSTRAINT history_id_is_an_opaque_identifier
            CHECK (history_id ~ '^thst_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          task_id text NOT NULL
            REFERENCES {SCHEMA}.tasks (task_id)
            CONSTRAINT task_id_is_an_opaque_identifier
            CHECK (task_id ~ '^tsk_{_SUFFIX}$'),
          action text NOT NULL
            CONSTRAINT a_task_history_action_is_known
            CHECK (action IN ('archive', 'cancel_recurrence', 'create', 'defer',
                              'schedule', 'set_priority', 'set_recurrence',
                              'transition_lifecycle', 'unarchive', 'update_title')),
          actor text NOT NULL
            CONSTRAINT a_task_history_actor_is_known
            CHECK (actor IN ('assistant', 'principal', 'system')),
          outcome text NOT NULL
            CONSTRAINT a_task_history_outcome_is_known
            CHECK (outcome IN ('applied', 'no_op', 'rejected')),
          before_version integer NOT NULL
            CONSTRAINT a_task_history_before_version_is_non_negative
            CHECK (before_version >= 0),
          after_version integer NOT NULL,
          idempotency_key text
            CONSTRAINT a_task_history_idempotency_key_is_bounded
            CHECK (idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'),
          client_context text
            CONSTRAINT a_task_history_client_context_is_bounded
            CHECK (client_context IS NULL
                   OR length(trim(client_context)) BETWEEN 1 AND 128),
          occurred_at timestamptz NOT NULL,
          recorded_at timestamptz NOT NULL,
          CONSTRAINT an_applied_task_mutation_advances_its_version
            CHECK ((outcome = 'applied') = (after_version > before_version)),
          CONSTRAINT an_unapplied_task_mutation_records_no_version_change
            CHECK (outcome = 'applied' OR after_version = before_version)
        )
        """
    )
    op.execute(f"CREATE INDEX task_history_by_principal ON {SCHEMA}.task_history (principal_id)")
    op.execute(
        f"CREATE INDEX task_history_by_principal_task "
        f"ON {SCHEMA}.task_history (principal_id, task_id)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX task_history_idempotency_key_is_unique_per_principal "
        f"ON {SCHEMA}.task_history (principal_id, idempotency_key) "
        f"WHERE idempotency_key IS NOT NULL"
    )


def upgrade() -> None:
    _create_task_recurrences()
    _extend_tasks()
    _create_task_history()


def downgrade() -> None:
    """Reverse every change; every legacy `tasks` column and row survives intact.

    Dropping `lifecycle_state`, `priority`, `scheduled_at`, `deferred_until`,
    `archived_at`, `version`, and `recurrence_id` discards only what this
    revision added — `state`, `closed_at`, and every other `8f2b6c4d1a37`
    column, and every row, are untouched. `task_history` and
    `task_recurrences` go with the tables that name them; a downgrade past
    this revision is a decision to stop holding the richer task-management
    facts at all, not a decision that loses a single existing Task.
    """
    op.execute(f"DROP TABLE {SCHEMA}.task_history")

    op.execute(f"DROP INDEX {SCHEMA}.tasks_by_recurrence")
    op.execute(f"DROP INDEX {SCHEMA}.tasks_by_principal_lifecycle_state")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT tasks_recurrence_id_fkey")
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_recurrence_is_an_opaque_identifier"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_version_is_positive")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_priority_is_known")
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        "DROP CONSTRAINT a_task_lifecycle_state_matches_its_legacy_state"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_lifecycle_state_is_known")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN recurrence_id")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN version")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN archived_at")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN deferred_until")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN scheduled_at")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN priority")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN lifecycle_state")

    op.execute(f"DROP TABLE {SCHEMA}.task_recurrences")
