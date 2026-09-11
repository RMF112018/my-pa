"""Admit Task origin_kind, direct closure, and append-only task_comments.

Revision ID: de5ec1c65857
Revises: c1a8e4d70b29
Create Date: 2026-09-11

WP-TUX-01 expands `knowledge.tasks` and adds `knowledge.task_comments`.

Expand-compatible upgrade sequence:

1. add `origin_kind` with a temporary server default of `evidence`;
2. backfill every existing row to `evidence` (origin_evidence_ref unchanged);
3. set `origin_kind` NOT NULL and drop the temporary default;
4. relax `origin_evidence_ref` nullability;
5. replace `a_task_cites_its_origin_evidence` with provenance pairing;
6. replace `a_closed_task_carries_closure_evidence` so terminal rows may omit
   closure evidence while nonterminal rows still refuse any reference;
7. add `(principal_id, task_id)` uniqueness so comments can take a same-Principal
   composite foreign key;
8. create `task_comments` with constraints, indexes, FK, and the capture_labels
   append-only trigger pattern.

Literals are frozen here rather than derived from domain enums (`D-48` /
architecture freeze). Downgrade refuses when any incompatible row exists:
direct_principal origins, terminal rows with null closure_evidence_ref, or any
task_comments. An empty or fully compatible schema still downgrades cleanly.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "de5ec1c65857"
down_revision: str | None = "c1a8e4d70b29"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"
_IMMUTABILITY_FUNCTION: Final = "task_comments_stay_as_written"
_IMMUTABILITY_TRIGGER: Final = "task_comments_are_append_only"

#: Frozen origin vocabulary for this revision. Do not import TaskOriginKind.
_ORIGIN_KIND_KNOWN: Final = "origin_kind IN ('direct_principal', 'evidence')"
_ORIGIN_PROVENANCE: Final = (
    "("
    "origin_kind = 'evidence' AND origin_evidence_ref IS NOT NULL "
    "AND length(trim(origin_evidence_ref)) > 0"
    ") OR ("
    "origin_kind = 'direct_principal' AND origin_evidence_ref IS NULL"
    ")"
)
_CLOSURE_MATCHES_STATE: Final = (
    "("
    "state <> 'closed' AND closure_evidence_ref IS NULL"
    ") OR ("
    "state = 'closed' AND ("
    "closure_evidence_ref IS NULL OR length(trim(closure_evidence_ref)) > 0"
    ")"
    ")"
)
#: The pre-revision closure CHECK, restored on downgrade when preflight passes.
_CLOSURE_REQUIRES_EVIDENCE: Final = (
    "state <> 'closed' OR length(trim(coalesce(closure_evidence_ref, ''))) > 0"
)
_CITE_ORIGIN: Final = "length(trim(origin_evidence_ref)) > 0"


def _refuse(*, name: str, offending_sql: str, message: str) -> None:
    """Fail closed when `offending_sql` yields any row.

    Emitting the guard as server SQL keeps offline `--sql` mode honest and
    keeps the refusal message free of row payloads beyond a count.
    """
    escaped_name = name.replace("'", "''")
    escaped_message = message.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
          offending_count integer;
        BEGIN
          WITH offending AS (
            {offending_sql}
          )
          SELECT count(*) INTO offending_count FROM offending;
          IF offending_count > 0 THEN
            RAISE EXCEPTION
              'WP-TUX-01 downgrade refused ({escaped_name}): % offending row(s). {escaped_message}',
              offending_count;
          END IF;
        END $$
        """  # noqa: S608
    )


def upgrade() -> None:
    # --- origin_kind: add, backfill, harden, drop temporary default ----------
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks ADD COLUMN origin_kind text NOT NULL DEFAULT 'evidence'"
    )
    op.execute(
        f"UPDATE {SCHEMA}.tasks SET origin_kind = 'evidence' "  # noqa: S608
        "WHERE origin_kind IS DISTINCT FROM 'evidence'"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        "ALTER COLUMN origin_kind SET NOT NULL, "
        "ALTER COLUMN origin_kind DROP DEFAULT"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        f"ADD CONSTRAINT a_task_origin_kind_is_known CHECK ({_ORIGIN_KIND_KNOWN})"
    )

    # --- origin_evidence_ref: nullable, then provenance CHECK ---------------
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ALTER COLUMN origin_evidence_ref DROP NOT NULL")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_task_cites_its_origin_evidence")
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        f"ADD CONSTRAINT a_task_origin_matches_its_provenance CHECK ({_ORIGIN_PROVENANCE})"
    )

    # --- terminal closure may omit evidence ---------------------------------
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT a_closed_task_carries_closure_evidence")
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        f"ADD CONSTRAINT a_task_closure_evidence_matches_its_state "
        f"CHECK ({_CLOSURE_MATCHES_STATE})"
    )

    # --- same-Principal unique for composite comment FK ---------------------
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        "ADD CONSTRAINT tasks_principal_task_is_unique UNIQUE (principal_id, task_id)"
    )

    # --- task_comments ------------------------------------------------------
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.task_comments (
          comment_id text NOT NULL,
          principal_id text NOT NULL,
          task_id text NOT NULL,
          body text NOT NULL,
          author_kind text NOT NULL,
          author_id text NOT NULL,
          created_at timestamp with time zone NOT NULL,
          idempotency_key text NOT NULL,
          request_digest text NOT NULL,
          PRIMARY KEY (comment_id),
          CONSTRAINT comment_id_is_an_opaque_identifier
            CHECK (comment_id ~ '^tcm_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT task_id_is_an_opaque_identifier
            CHECK (task_id ~ '^tsk_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_task_comment_author_kind_is_known
            CHECK (author_kind IN ('principal', 'assistant', 'system')),
          CONSTRAINT a_task_comment_body_is_bounded
            CHECK (length(trim(body)) > 0 AND char_length(body) <= 4000),
          CONSTRAINT a_task_comment_author_id_is_an_opaque_identifier
            CHECK (author_id ~ '^[a-z]+_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_task_comment_idempotency_key_is_bounded
            CHECK (idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'),
          CONSTRAINT a_task_comment_request_digest_is_sha256
            CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT task_comments_task_is_same_principal
            FOREIGN KEY (principal_id, task_id)
            REFERENCES {SCHEMA}.tasks (principal_id, task_id)
            ON DELETE RESTRICT,
          CONSTRAINT task_comments_idempotency_key_is_unique_per_principal
            UNIQUE (principal_id, idempotency_key)
        )
        """
    )
    op.execute(
        f"CREATE INDEX task_comments_by_principal_task_created "
        f"ON {SCHEMA}.task_comments (principal_id, task_id, created_at, comment_id)"
    )
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'knowledge.task_comments is append only; % is refused', TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    op.execute(
        f"CREATE TRIGGER {_IMMUTABILITY_TRIGGER} "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.task_comments "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
    )


def downgrade() -> None:
    _refuse(
        name="direct_principal origin rows",
        offending_sql=(
            f"SELECT task_id FROM {SCHEMA}.tasks WHERE origin_kind = 'direct_principal'"  # noqa: S608
        ),
        message=(
            "Restoring evidence-required origin would falsify direct-Principal "
            "creates; remove or reclassify those rows before downgrade."
        ),
    )
    _refuse(
        name="terminal rows with null closure_evidence_ref",
        offending_sql=(
            f"SELECT task_id FROM {SCHEMA}.tasks "  # noqa: S608
            "WHERE state = 'closed' AND closure_evidence_ref IS NULL"
        ),
        message=(
            "Restoring mandatory closure evidence would refuse these rows; "
            "supply closure_evidence_ref or reopen them before downgrade."
        ),
    )
    _refuse(
        name="task_comments rows",
        offending_sql=f"SELECT comment_id FROM {SCHEMA}.task_comments",  # noqa: S608
        message=(
            "Dropping task_comments would destroy append-only receipts; "
            "empty the table before downgrade."
        ),
    )

    op.execute(f"DROP TRIGGER IF EXISTS {_IMMUTABILITY_TRIGGER} ON {SCHEMA}.task_comments")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.task_comments")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")

    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT IF EXISTS tasks_principal_task_is_unique"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        "DROP CONSTRAINT IF EXISTS a_task_closure_evidence_matches_its_state"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        f"ADD CONSTRAINT a_closed_task_carries_closure_evidence "
        f"CHECK ({_CLOSURE_REQUIRES_EVIDENCE})"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT IF EXISTS a_task_origin_matches_its_provenance"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.tasks "
        f"ADD CONSTRAINT a_task_cites_its_origin_evidence CHECK ({_CITE_ORIGIN})"
    )
    # Every surviving row is evidence-origin with a non-null reference after the
    # guards above; restore NOT NULL and drop the column this revision added.
    op.execute(f"ALTER TABLE {SCHEMA}.tasks ALTER COLUMN origin_evidence_ref SET NOT NULL")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP CONSTRAINT IF EXISTS a_task_origin_kind_is_known")
    op.execute(f"ALTER TABLE {SCHEMA}.tasks DROP COLUMN IF EXISTS origin_kind")
