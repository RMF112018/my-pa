"""Admit Commitment/Task/Follow-Up integration (WP-TM-05), additively.

Operator-confirmed scope: canonical Commitment support for task management,
`OWED_TO_PRINCIPAL` semantics, Task<->Commitment linkage, `WAITING` Task
integration, Follow-Up as a Task role (never a separate root entity), and
derived "Waiting On" reads. This revision is the schema half of that scope.

**Purely additive**, on the same terms `3d7a2a3e8277` states for its own
extension of `knowledge.tasks`: every existing row in `knowledge.commitments`
and `knowledge.tasks` survives this revision unchanged in every column either
revision already defined.

* `knowledge.commitments.version` — `integer NOT NULL DEFAULT 1`, the
  optimistic-concurrency counter `knowledge.commitment_history` reads before
  and after every attempted mutation, the same shape `knowledge.tasks.version`
  already carries.
* `knowledge.commitment_history` — one append-only mutation receipt per
  Commitment write, the identical shape `knowledge.task_history` already
  establishes for the Task plane.
* `knowledge.tasks.commitment_id` — nullable `FOREIGN KEY` to
  `knowledge.commitments`, naming the Commitment a Task is linked to, if any.
  A Task still names at most one Commitment, never the reverse: this is not a
  link table, and "Waiting On" stays a derived read over both tables rather
  than a third one.
* `knowledge.tasks.role` — nullable, restricted to `('follow_up')` today. A
  Task with no `role` is not tagged with any purpose beyond ordinary work.
* `knowledge.task_history`'s `a_task_history_action_is_known` CHECK is dropped
  and recreated to admit two new values, `link_commitment` and `set_role` —
  both are writes to the Task row alone, recorded on this table rather than on
  a new one.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states.
Checked against `my_pa.domain.task.role`, `my_pa.domain.task.history`, and
`my_pa.domain.task.commitment_history` at head by
`tests/schema/test_commitment_schema_migration.py`.

**Raw SQL**, exactly as `3d7a2a3e8277` and every revision since `d2e3f4a5b6c7`
do: this revision imports no table object.

Revision ID: a1c9e6f2b834
Revises: d15c0dc14d09
Create Date: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "a1c9e6f2b834"
down_revision: str | None = "d15c0dc14d09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"
_SUFFIX: Final = "[A-Za-z0-9]{8,64}"


def _extend_commitments() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.commitments ADD COLUMN version integer NOT NULL DEFAULT 1")
    op.execute(
        f"ALTER TABLE {SCHEMA}.commitments ADD CONSTRAINT a_commitment_version_is_positive "
        "CHECK (version >= 1)"
    )


def _create_commitment_history() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.commitment_history (
          history_id text PRIMARY KEY
            CONSTRAINT history_id_is_an_opaque_identifier
            CHECK (history_id ~ '^cmthst_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          commitment_id text NOT NULL
            REFERENCES {SCHEMA}.commitments (commitment_id)
            CONSTRAINT commitment_id_is_an_opaque_identifier
            CHECK (commitment_id ~ '^cmt_{_SUFFIX}$'),
          action text NOT NULL
            CONSTRAINT a_commitment_history_action_is_known
            CHECK (action IN ('close', 'create')),
          actor text NOT NULL
            CONSTRAINT a_commitment_history_actor_is_known
            CHECK (actor IN ('assistant', 'principal', 'system')),
          outcome text NOT NULL
            CONSTRAINT a_commitment_history_outcome_is_known
            CHECK (outcome IN ('applied', 'no_op', 'rejected')),
          before_version integer NOT NULL
            CONSTRAINT a_commitment_history_before_version_is_non_negative
            CHECK (before_version >= 0),
          after_version integer NOT NULL,
          idempotency_key text
            CONSTRAINT a_commitment_history_idempotency_key_is_bounded
            CHECK (idempotency_key IS NULL OR idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'),
          client_context text
            CONSTRAINT a_commitment_history_client_context_is_bounded
            CHECK (client_context IS NULL
                   OR length(trim(client_context)) BETWEEN 1 AND 128),
          occurred_at timestamptz NOT NULL,
          recorded_at timestamptz NOT NULL,
          CONSTRAINT an_applied_commitment_mutation_advances_its_version
            CHECK ((outcome = 'applied') = (after_version > before_version)),
          CONSTRAINT an_unapplied_commitment_mutation_records_no_version_change
            CHECK (outcome = 'applied' OR after_version = before_version)
        )
        """
    )
    op.execute(
        f"CREATE INDEX commitment_history_by_principal "
        f"ON {SCHEMA}.commitment_history (principal_id)"
    )
    op.execute(
        f"CREATE INDEX commitment_history_by_principal_commitment "
        f"ON {SCHEMA}.commitment_history (principal_id, commitment_id)"
    )
    op.execute(
        f"CREATE UNIQUE INDEX commitment_history_idempotency_key_is_unique_per_principal "
        f"ON {SCHEMA}.commitment_history (principal_id, idempotency_key) "
        f"WHERE idempotency_key IS NOT NULL"
    )


def _extend_tasks() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN commitment_id text")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN role text")
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT a_task_commitment_is_an_opaque_identifier "
        f"CHECK (commitment_id IS NULL OR commitment_id ~ '^cmt_{_SUFFIX}$')"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT a_task_role_is_known "
        "CHECK (role IS NULL OR role IN ('follow_up'))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD CONSTRAINT tasks_commitment_id_fkey "
        f"FOREIGN KEY (commitment_id) REFERENCES {SCHEMA}.commitments (commitment_id)"
    )
    op.execute(f"CREATE INDEX tasks_by_commitment ON {SCHEMA}.tasks (commitment_id)")


def _extend_task_history_actions() -> None:
    op.execute(f"ALTER TABLE {SCHEMA}.task_history DROP CONSTRAINT a_task_history_action_is_known")
    op.execute(
        f"ALTER TABLE {SCHEMA}.task_history ADD CONSTRAINT a_task_history_action_is_known "
        "CHECK (action IN ('archive', 'cancel_recurrence', 'create', 'defer', 'link_commitment', "
        "'schedule', 'set_priority', 'set_recurrence', 'set_role', 'transition_lifecycle', "
        "'unarchive', 'update_title'))"
    )


def upgrade() -> None:
    _extend_commitments()
    _create_commitment_history()
    _extend_tasks()
    _extend_task_history_actions()


def downgrade() -> None:
    """Reverse every change; every legacy `commitments`/`tasks` column and row survives intact."""
    op.execute(f"ALTER TABLE {SCHEMA}.task_history DROP CONSTRAINT a_task_history_action_is_known")
    op.execute(
        f"ALTER TABLE {SCHEMA}.task_history ADD CONSTRAINT a_task_history_action_is_known "
        "CHECK (action IN ('archive', 'cancel_recurrence', 'create', 'defer', 'schedule', "
        "'set_priority', 'set_recurrence', 'transition_lifecycle', 'unarchive', 'update_title'))"
    )

    op.execute(f"DROP INDEX {SCHEMA}.tasks_by_commitment")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT tasks_commitment_id_fkey")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_role_is_known")
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_commitment_is_an_opaque_identifier"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN role")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN commitment_id")

    op.execute(f"DROP TABLE {SCHEMA}.commitment_history")

    op.execute(f"ALTER TABLE {SCHEMA}.commitments DROP CONSTRAINT a_commitment_version_is_positive")
    op.execute(f"ALTER TABLE {SCHEMA}.commitments DROP COLUMN version")
