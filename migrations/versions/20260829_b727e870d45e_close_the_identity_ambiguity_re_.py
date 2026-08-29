"""Close the identity-ambiguity, re-enrichment `partial` and review-ledger gaps.

Five corrections, one revision, because they are the persistence half of one
remediation and a reviewer reading four separate files could not tell that the
`partial` state and the `limitations` column arrived together.

**`entity_identity_preview_ambiguities`** records what a merge preview could not
decide: which record, why it is ambiguous, and which dispositions an operator may
choose from. It hangs off the preview by the composite `(preview_id,
principal_id)` identity `d38e6b2fa715` already declared, and cascades with it --
a preview expires fifteen minutes after it was created and the questions it could
not answer expire with it.

**`entity_identity_ambiguity_settlements`** records what the operator chose, per
ambiguity, on the operation that carried the choice out. It is append-only by
trigger on its own per-plane function, for the reason `2fe4e13fb449` gives for
not reusing `f1c6b904a2d7`'s: dropping one plane's trigger must not silently
disarm another's. `(disposition = 'assign_to_entity') = (target_entity_id IS NOT
NULL)` is stated as an equivalence rather than as two implications so that
neither a target without an assignment nor an assignment without a target is
storable.

**`entity_reenrichment_work` gains `partial`.** `8e1c4a7b2d90` admitted five
states, and a re-enrichment that produced some of its intended effects had to
report one of `succeeded` or `failed` -- both of which are false. `partial` is
terminal, so it joins `terminal_reenrichment_records_completion`, and
`partial_reenrichment_states_its_limitations` mirrors `stale_reenrichment_states_why`
exactly: the state and the column that explains it are true together or neither
is written.

**`worker_heartbeats` admits `reenrichment`.** The re-enrichment worker is a
third queue plane and its liveness was unrecordable, so an absent re-enrichment
worker and a working one were the same observation.

**`entity_proposal_review_decisions` becomes append-only.** Its sibling
`relationship_memory_review_decisions` has carried
`relationship_memory_decisions_are_append_only` since `f1c6b904a2d7`; the entity
plane's review ledger carried no such trigger, so a reviewer's disposition was
editable by anything holding the connection. The new function is per-plane rather
than a reuse of `entity_ledger_rows_stay_as_written`, which
`tests/schema/test_capture_schema_migration.py` asserts as a convention.

Every closed set below is spelled out as a literal rather than joined from a live
enum, which is the standing rule `9c6b4a18ed72` states and
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces: a constraint that read a Python enum would change meaning the day the
enum did, against rows already stored under the old one.

Revision ID: b727e870d45e
Revises: 8e1c4a7b2d90
Created: 2026-08-29 09:01:27.084899
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "b727e870d45e"
down_revision: str | None = "8e1c4a7b2d90"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The suffix rule `domain.common.identifiers.validate_identifier` enforces,
#: restated as the POSIX form the server can check, exactly as `d38e6b2fa715`
#: restates it.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

# --- the frozen vocabularies -------------------------------------------------

#: The twelve families `entity_identity_effects.record_family` admits at
#: `8e1c4a7b2d90`, spelled in that revision's own order so a reader comparing the
#: two constraints is comparing texts rather than sorted sets.
_RECORD_FAMILY_VALUES: Final = (
    "'entity','alias','identifier','assignment','relationship',"
    "'observation','proposal','review_case','relationship_memory',"
    "'memory_proposal','memory_context_link','derived_context'"
)

#: Why one record could not be attributed by the preview alone.
_AMBIGUITY_REASON_VALUES: Final = (
    "'post_merge_modified','post_merge_created','conflicting_lineage',"
    "'shared_evidence','ownership_indeterminate'"
)

#: What an operator may do about one ambiguity.
_DISPOSITION_VALUES: Final = "'assign_to_entity','preserve_shared','leave_unresolved'"

#: How many dispositions one ambiguity may offer -- the whole vocabulary, at
#: most, and at least one, because an ambiguity offering no choice is a question
#: nobody can answer.
_MAX_ALLOWED_DISPOSITIONS: Final = 3

#: How many entities one ambiguity may name as assignment targets: the survivor
#: plus the ten `d38e6b2fa715` bounds a merge's merged-away set at.
_MAX_ALLOWED_TARGETS: Final = 11

#: Its own function rather than a reuse of `identity_effect_rows_stay_as_written`
#: or `entity_ledger_rows_stay_as_written`, on the argument `2fe4e13fb449` makes:
#: dropping one plane's trigger must not silently disarm another plane's.
_SETTLEMENT_IMMUTABILITY_FUNCTION: Final = "identity_ambiguity_settlement_rows_stay_as_written"
_SETTLEMENT_IMMUTABILITY_TRIGGER: Final = "identity_ambiguity_settlements_are_append_only"
_SETTLEMENT_TABLE: Final = "entity_identity_ambiguity_settlements"

_REVIEW_IMMUTABILITY_FUNCTION: Final = "entity_review_decision_rows_stay_as_written"
_REVIEW_IMMUTABILITY_TRIGGER: Final = "entity_proposal_review_decisions_are_append_only"
_REVIEW_TABLE: Final = "entity_proposal_review_decisions"

#: The two `entity_reenrichment_work` CHECKs `8e1c4a7b2d90` wrote inline on the
#: column and as a table constraint respectively. The first carries PostgreSQL's
#: generated name because that is the name the server holds; re-adding it under
#: the declaration's own name is what makes `tables.py` and the database agree.
_GENERATED_STATE_CONSTRAINT: Final = "entity_reenrichment_work_state_check"
_DECLARED_STATE_CONSTRAINT: Final = "a_reenrichment_state_is_known"
_GENERATED_PLANE_CONSTRAINT: Final = "worker_heartbeats_plane_check"
_DECLARED_PLANE_CONSTRAINT: Final = "worker_plane_is_known"


def _immutability_function(name: str) -> str:
    return (
        f"CREATE FUNCTION {SCHEMA}.{name}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_identity_preview_ambiguities (
          preview_id text NOT NULL,
          ambiguity_id text NOT NULL,
          principal_id text NOT NULL,
          record_family text NOT NULL,
          record_id text NOT NULL,
          ambiguity_reason text NOT NULL,
          allowed_dispositions text[] NOT NULL,
          allowed_target_entity_ids text[] NOT NULL,
          evidence_summary jsonb NOT NULL,
          created_at timestamptz NOT NULL,
          CONSTRAINT one_ambiguity_per_preview_and_identifier
            PRIMARY KEY (preview_id, ambiguity_id),
          CONSTRAINT preview_id_is_an_opaque_identifier
            CHECK (preview_id ~ '^eipv_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT ambiguity_id_is_an_opaque_identifier
            CHECK (ambiguity_id ~ '^eiam_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_preview_ambiguity_family_is_known
            CHECK (record_family IN ({_RECORD_FAMILY_VALUES})),
          CONSTRAINT a_preview_ambiguity_record_id_is_an_opaque_identifier
            CHECK (record_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_preview_ambiguity_reason_is_known
            CHECK (ambiguity_reason IN ({_AMBIGUITY_REASON_VALUES})),
          CONSTRAINT a_preview_ambiguity_offers_a_bounded_choice
            CHECK (
              cardinality(allowed_dispositions) BETWEEN 1 AND {_MAX_ALLOWED_DISPOSITIONS}
              AND allowed_dispositions <@ ARRAY[{_DISPOSITION_VALUES}]::text[]
            ),
          CONSTRAINT a_preview_ambiguity_names_bounded_targets
            CHECK (cardinality(allowed_target_entity_ids) BETWEEN 0 AND {_MAX_ALLOWED_TARGETS}),
          CONSTRAINT a_preview_ambiguity_evidence_summary_is_an_object
            CHECK (jsonb_typeof(evidence_summary) = 'object'),
          CONSTRAINT a_preview_ambiguity_belongs_to_a_preview_of_its_principal
            FOREIGN KEY (preview_id, principal_id)
            REFERENCES {SCHEMA}.entity_identity_previews (preview_id, principal_id)
            ON DELETE CASCADE
        );
        CREATE INDEX entity_identity_preview_ambiguities_by_principal
          ON {SCHEMA}.entity_identity_preview_ambiguities (principal_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.{_SETTLEMENT_TABLE} (
          identity_operation_id text NOT NULL,
          ambiguity_id text NOT NULL,
          principal_id text NOT NULL,
          record_family text NOT NULL,
          record_id text NOT NULL,
          disposition text NOT NULL,
          target_entity_id text,
          settled_at timestamptz NOT NULL,
          CONSTRAINT one_settlement_per_operation_and_ambiguity
            PRIMARY KEY (identity_operation_id, ambiguity_id),
          CONSTRAINT identity_operation_id_is_an_opaque_identifier
            CHECK (identity_operation_id ~ '^eiop_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT ambiguity_id_is_an_opaque_identifier
            CHECK (ambiguity_id ~ '^eiam_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_ambiguity_settlement_family_is_known
            CHECK (record_family IN ({_RECORD_FAMILY_VALUES})),
          CONSTRAINT an_ambiguity_settlement_record_id_is_an_opaque_identifier
            CHECK (record_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_ambiguity_settlement_disposition_is_known
            CHECK (disposition IN ({_DISPOSITION_VALUES})),
          CONSTRAINT an_ambiguity_settlement_names_a_target_exactly_when_it_assigns
            CHECK ((disposition = 'assign_to_entity') = (target_entity_id IS NOT NULL)),
          CONSTRAINT an_ambiguity_settlement_records_an_operation_of_its_principal
            FOREIGN KEY (identity_operation_id, principal_id)
            REFERENCES {SCHEMA}.entity_identity_operations
              (identity_operation_id, principal_id)
            ON DELETE CASCADE,
          CONSTRAINT an_ambiguity_settlement_assigns_an_entity_of_its_principal
            FOREIGN KEY (target_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
        );
        CREATE INDEX entity_identity_ambiguity_settlements_by_principal
          ON {SCHEMA}.{_SETTLEMENT_TABLE} (principal_id);
        """
    )
    op.execute(_immutability_function(_SETTLEMENT_IMMUTABILITY_FUNCTION))
    op.execute(
        f"CREATE TRIGGER {_SETTLEMENT_IMMUTABILITY_TRIGGER} BEFORE UPDATE OR DELETE "
        f"ON {SCHEMA}.{_SETTLEMENT_TABLE} FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_SETTLEMENT_IMMUTABILITY_FUNCTION}()"
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_reenrichment_work
          ADD COLUMN limitations text[],
          DROP CONSTRAINT {_GENERATED_STATE_CONSTRAINT},
          DROP CONSTRAINT terminal_reenrichment_records_completion,
          ADD CONSTRAINT {_DECLARED_STATE_CONSTRAINT}
            CHECK (state IN ('queued','running','succeeded','partial','stale','failed')),
          ADD CONSTRAINT terminal_reenrichment_records_completion
            CHECK ((state IN ('succeeded','partial','stale','failed'))
                   = (completed_at IS NOT NULL)),
          ADD CONSTRAINT partial_reenrichment_states_its_limitations
            CHECK ((state = 'partial') = (coalesce(cardinality(limitations),0) > 0));

        ALTER TABLE {SCHEMA}.worker_heartbeats
          DROP CONSTRAINT {_GENERATED_PLANE_CONSTRAINT},
          ADD CONSTRAINT {_DECLARED_PLANE_CONSTRAINT}
            CHECK (plane IN ('capture','enrollment','reenrichment'));
        """
    )

    op.execute(_immutability_function(_REVIEW_IMMUTABILITY_FUNCTION))
    op.execute(
        f"CREATE TRIGGER {_REVIEW_IMMUTABILITY_TRIGGER} BEFORE UPDATE OR DELETE "
        f"ON {SCHEMA}.{_REVIEW_TABLE} FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_REVIEW_IMMUTABILITY_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER {_REVIEW_IMMUTABILITY_TRIGGER} ON {SCHEMA}.{_REVIEW_TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_REVIEW_IMMUTABILITY_FUNCTION}()")

    # Restored verbatim as `8e1c4a7b2d90` and `b4e8d2c7a613` left them, under the
    # names PostgreSQL generated for their inline column CHECKs: a downgrade that
    # restored the same predicate under a different name would leave a database
    # that came back down holding a constraint a freshly built one does not, and
    # `tests/schema/test_every_revision_denotes_one_schema.py` compares both.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.worker_heartbeats
          DROP CONSTRAINT {_DECLARED_PLANE_CONSTRAINT},
          ADD CONSTRAINT {_GENERATED_PLANE_CONSTRAINT}
            CHECK (plane IN ('capture', 'enrollment'));

        ALTER TABLE {SCHEMA}.entity_reenrichment_work
          DROP CONSTRAINT partial_reenrichment_states_its_limitations,
          DROP CONSTRAINT terminal_reenrichment_records_completion,
          DROP CONSTRAINT {_DECLARED_STATE_CONSTRAINT},
          DROP COLUMN limitations,
          ADD CONSTRAINT {_GENERATED_STATE_CONSTRAINT}
            CHECK (state IN ('queued','running','succeeded','stale','failed')),
          ADD CONSTRAINT terminal_reenrichment_records_completion
            CHECK ((state IN ('succeeded','stale','failed')) = (completed_at IS NOT NULL));
        """
    )

    op.execute(f"DROP TRIGGER {_SETTLEMENT_IMMUTABILITY_TRIGGER} ON {SCHEMA}.{_SETTLEMENT_TABLE}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_SETTLEMENT_IMMUTABILITY_FUNCTION}()")
    op.execute(
        f"""
        DROP TABLE {SCHEMA}.{_SETTLEMENT_TABLE};
        DROP TABLE {SCHEMA}.entity_identity_preview_ambiguities;
        """
    )
