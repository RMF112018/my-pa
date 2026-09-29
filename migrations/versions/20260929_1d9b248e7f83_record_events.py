"""Admit the Record Event feed: two tables and one append-only trigger.

Revision ID: 1d9b248e7f83
Revises: 7d9a450dfd07
Create Date: 2026-09-29

WP-RE-01, the single Record Event revision (Gate-1 plan section 7.1). Generated
by `alembic revision` against the sole head `7d9a450dfd07` authenticated
immediately before generation; no identifier was preassigned and no merge
revision exists. Under operator ruling OD-4 (Option B) this revision is
generated in WP-RE-01 and **re-pointed** in WP-RE-06: immediately before
WP-RE-06 admission, and again before the pull request, the sole head is
re-authenticated and `down_revision` moves to it if main has advanced. WP-RE-06
also adds the audit-vocabulary restatement (`record_events.list`,
`record_event_read`); this revision deliberately restates no vocabulary yet.

It:

1. creates `knowledge.record_event_sequences`, the per-Principal allocator row
   (mutable, no timestamp, no trigger, no Principal foreign key);
2. creates `knowledge.record_events` with every key, check, the composite
   same-Principal NOT DEFERRABLE causation reference and the one index
   `tables.py` declares, as frozen DDL text (never the live `Table` objects,
   never an enum). The package's separate `(principal_id, sequence_number)`
   index is not created: the UNIQUE constraint's index already serves it
   (plan deviation D-13);
3. creates the append-only function and trigger over `record_events`, the
   repository's per-table PL/pgSQL pattern.

No backfill: this revision writes no row. `downgrade` refuses, deleting nothing,
while any Record Event or any allocator row exists; otherwise it drops the
trigger, the function and both tables with `RESTRICT`.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "1d9b248e7f83"
down_revision: str | None = "7d9a450dfd07"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The two Record Event tables in foreign-key dependency order, each with its
#: own indexes. Frozen text: a later edit to `tables.py` must never change what
#: this revision emits.
_TABLE_DDL: Final[tuple[tuple[str, str], ...]] = (
    (
        "record_event_sequences",
        """
        CREATE TABLE knowledge.record_event_sequences (
          principal_id TEXT NOT NULL,
          next_sequence BIGINT NOT NULL,
          PRIMARY KEY (principal_id),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
              '^prn_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT a_record_event_next_sequence_is_positive CHECK (next_sequence >= 1)
        )
        """,
    ),
    (
        "record_events",
        """
        CREATE TABLE knowledge.record_events (
          event_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          sequence_number BIGINT NOT NULL,
          record_family TEXT NOT NULL,
          record_id TEXT NOT NULL,
          event_kind TEXT NOT NULL,
          record_version INTEGER NOT NULL,
          changed_fields TEXT[] NOT NULL,
          source_capability TEXT NOT NULL,
          source_receipt_id TEXT,
          actor_class TEXT NOT NULL,
          authority TEXT,
          classification TEXT NOT NULL,
          correlation_id TEXT,
          causation_event_id TEXT,
          occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
          recorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
          PRIMARY KEY (event_id),
          CONSTRAINT event_id_is_an_opaque_identifier CHECK (event_id ~
              '^rcev_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
              '^prn_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT causation_event_id_is_an_opaque_identifier CHECK (causation_event_id ~
              '^rcev_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT correlation_id_is_an_opaque_identifier CHECK (correlation_id ~
              '^corr_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT a_record_event_record_id_is_an_opaque_identifier CHECK (record_id ~
              '^[a-z]+_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT a_record_event_receipt_id_is_an_opaque_identifier CHECK (source_receipt_id
              IS NULL OR source_receipt_id ~ '^[a-z]+_[A-Za-z0-9]{8,64}$'),
          CONSTRAINT a_record_event_family_is_known CHECK (record_family IN ('commitment',
              'constraint', 'constraint_category', 'entity', 'entity_address', 'entity_alias',
              'entity_assignment', 'entity_communication_method', 'entity_identifier',
              'entity_name', 'entity_observation', 'entity_project_participation',
              'entity_relationship', 'meeting', 'meeting_series',
              'person_organization_affiliation', 'project', 'project_controls_settings',
              'relationship_memory', 'task')),
          CONSTRAINT a_record_event_kind_is_known CHECK (event_kind IN ('created',
              'state_changed', 'updated')),
          CONSTRAINT a_record_event_actor_class_is_known CHECK (actor_class IN ('assistant',
              'principal', 'review_promotion', 'system')),
          CONSTRAINT a_record_event_classification_is_known CHECK (classification IN
              ('private_local', 'restricted_local', 'synthetic_test')),
          CONSTRAINT a_record_event_authority_is_known CHECK (authority IN ('public_assertion',
              'review_accepted', 'source_backed_assertion', 'system_deterministic',
              'user_authored_private_note', 'user_confirmed_assertion')),
          CONSTRAINT a_record_event_sequence_is_positive CHECK (sequence_number >= 1),
          CONSTRAINT a_record_event_version_is_positive CHECK (record_version >= 1),
          CONSTRAINT a_record_event_source_capability_is_bounded CHECK
              (length(source_capability) BETWEEN 1 AND 128 AND source_capability ~
              '^[a-z][a-z0-9_]*([.][a-z][a-z0-9_]*)*$'),
          CONSTRAINT a_record_event_changed_fields_are_bounded CHECK
              (cardinality(changed_fields) <= 64 AND coalesce(array_ndims(changed_fields), 1) = 1
              AND '' <> ALL (changed_fields) AND array_to_string(changed_fields, ',', '*') ~
              '^([a-z][a-z0-9_]{0,63}(,[a-z][a-z0-9_]{0,63})*)?$'),
          CONSTRAINT a_record_event_is_not_its_own_cause CHECK (causation_event_id IS NULL OR
              causation_event_id <> event_id),
          CONSTRAINT a_record_event_sequence_is_unique_within_its_principal UNIQUE
              (principal_id, sequence_number),
          CONSTRAINT a_record_event_is_identified_within_its_principal UNIQUE (event_id,
              principal_id),
          CONSTRAINT a_record_event_cause_is_an_event_of_its_principal FOREIGN
              KEY(causation_event_id, principal_id) REFERENCES knowledge.record_events
              (event_id, principal_id) ON DELETE RESTRICT NOT DEFERRABLE
        );
        CREATE INDEX record_events_by_principal_record ON knowledge.record_events
          (principal_id, record_family, record_id, sequence_number DESC)
        """,
    ),
)

#: The one immutable ledger: `(function, trigger, table)`. `record_event_sequences`
#: is intentionally mutable -- it is the allocator row.
_APPEND_ONLY: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "record_events_stay_append_only",
        "record_events_are_append_only",
        "record_events",
    ),
)

#: `downgrade` refuses while either table holds a row, rather than deleting user
#: data to make the downgrade pass. WP-RE-06 widens this to audit rows naming
#: the new capability or purpose when it adds the vocabulary restatement.
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM knowledge.record_events)
         OR EXISTS (SELECT 1 FROM knowledge.record_event_sequences) THEN
        RAISE EXCEPTION 'record events exist; refusing to downgrade 1d9b248e7f83'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def upgrade() -> None:
    for _table, ddl in _TABLE_DDL:
        op.execute(ddl)
    for function, trigger, table in _APPEND_ONLY:
        op.execute(
            f"""
            CREATE FUNCTION {SCHEMA}.{function}() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION '{table} is append-only'
                USING ERRCODE = 'restrict_violation';
            END; $$;
            CREATE TRIGGER {trigger}
              BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
              FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{function}()
            """
        )


def downgrade() -> None:
    op.execute(_REFUSE_DOWNGRADE)
    for function, trigger, table in reversed(_APPEND_ONLY):
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
        op.execute(f"DROP FUNCTION {SCHEMA}.{function}()")
    for table, _ddl in reversed(_TABLE_DDL):
        op.execute(f"DROP TABLE {SCHEMA}.{table} RESTRICT")
