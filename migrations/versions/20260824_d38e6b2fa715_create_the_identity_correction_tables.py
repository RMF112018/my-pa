"""Create the three identity-correction tables.

`WP-RI-06` (`MYPA-RI-COMP-04`). Three tables are created and nothing existing is
altered: `entity_identity_previews`, `entity_identity_operations` and the
append-only `entity_identity_effects`. No column, constraint or index of any
table this revision does not create is touched, so it composes with the other
Phase B revisions in any order the integration owner lands them.

**What these three are for.** `entity_merge_records` -- the lineage an accepted
merge proposal leaves behind -- records only that one entity now redirects to
another. That is enough to follow a pointer and not enough to undo anything: it
does not say which alias moved, which identifier was folded into which, which
edge became a self-edge, or which pending proposal the identity change
invalidated. `WP-07` is required to invert a governed merge, and inverting one
from a redirect alone is guesswork. These three tables are what a merge has to
leave behind instead: what the operator was shown and at which versions, what was
performed and under which key, and one before/after row per record the operation
touched.

**`entity_identity_previews` persists a control row for a capability that reads
canonical state and changes none of it.** That is why `entities.merge.preview` is
classified a write: the classification follows persistence behaviour, and this
table is the behaviour. `expires_at` carries a CHECK against `created_at` rather
than a default, because a preview whose lifetime the writer chose is a preview
whose fifteen-minute bound means nothing -- and the interval is written out here
rather than derived from `IDENTITY_PREVIEW_LIFETIME` for the reason the closed
sets below are written out.

**`entity_identity_operations` holds two mechanisms that are deliberately not one
mechanism.** `preview_digest` is a claim about the world (these entities held
these versions) and `idempotency_key` is a claim about the request (this is the
call I made before); the frozen contract states it as a rule -- the preview token
is not the mutation idempotency key -- and `UNIQUE (principal_id,
idempotency_key)` plus `request_digest` are where the rule becomes structural. The
unique carries no `capability` column, unlike
`one_entity_mutation_per_key_and_capability`: that key is shared by the whole
entity plane, and this table is written by exactly one capability, so a constant
column inside the index would only look like it was deciding something.

This table is **not** append-only, and the asymmetry with the effects beside it is
deliberate: an operation is written before the work and updated when the work
ends, which is what makes a crashed apply legible as `in_progress` rather than
indistinguishable from a completed merge.

**`entity_identity_effects` is append-only by trigger, not by convention.** No
CHECK can express "no UPDATE", and a rule enforced only by the current writer is a
rule the next writer does not inherit. This is the mechanism `f1c6b904a2d7`
installs on `relationship_memory_versions` and `2fe4e13fb449` reuses for
`entity_mutation_events` and `entity_resolution_decisions`, reused here with its
own function so that dropping one plane's trigger cannot silently disarm
another's.

Both states are `NOT NULL` on that table and the pair is the point. Recording only
redirects is what the contract calls faking invertibility, and a row holding only
the state after the change is the same failure one row at a time. No effect kind
this plane declares creates or destroys a row -- every one transforms an existing
one -- so requiring both costs nothing a real effect would have to omit.

**The closed sets below are frozen literals**, per the standing rule
`9c6b4a18ed72` states and `D-69` records: no revision derives a closed-set
constraint from a domain enum. A database migrated to this revision holds the
vocabulary this revision describes, whatever the domain says on the day it runs.
`operation_type` admits `merge` alone, because `WP-06` does not implement split;
`WP-07` widens it with the code that writes the value.

**No capability and no purpose is admitted here.** `entities.merge.preview`,
`entities.merge` and `entity_identity_correction` are admitted to
`knowledge.audit_events`' `capability_is_known` and `purpose_is_known` by the
single Phase B vocabulary revision, on the same argument `823e23b6cc63` records:
one closed CHECK restated by several branches produces several heads and lets
whichever merges last decide what the others admitted.

`downgrade` drops the trigger, the function and the three tables in dependency
order, so empty -> head -> empty leaves no residue.

Revision ID: d38e6b2fa715
Revises: c7a1f04b9e63
Create Date: 2026-08-24
"""

from __future__ import annotations

from typing import Final

from alembic import op

# Second in the Phase B chain. It creates three tables and alters nothing, so it
# composes with its neighbours in any order; it is placed after the proposal
# widening because that is the order the chain was exercised in.
revision: str = "d38e6b2fa715"
down_revision: str | None = "c7a1f04b9e63"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The suffix rule `domain.common.identifiers.validate_identifier` enforces,
#: restated as the POSIX form the server can check.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

#: Longest a stored explanation of one change may be, matching the bound
#: `2fe4e13fb449` carries for the same kind of column.
_REASON_LIMIT: Final = 500

#: Longest an idempotency key may be, matching the bound the capture, managed and
#: entity-mutation tables already carry.
_IDEMPOTENCY_KEY_LIMIT: Final = 128

#: How many entities one merge may merge away.
_MAX_MERGED_AWAY: Final = 10

# --- the frozen vocabularies, sorted -----------------------------------------

_OPERATION_TYPE_VALUES: Final = "'merge'"

_OPERATION_STATE_VALUES: Final = "'completed', 'failed', 'in_progress'"

_ACTOR_CLASS_VALUES: Final = "'review_promotion', 'system_deterministic', 'user'"

_EFFECT_FAMILY_VALUES: Final = (
    "'alias', 'assignment', 'derived_context', 'entity', 'identifier', "
    "'observation', 'proposal', 'relationship', 'review_case'"
)

_EFFECT_KIND_VALUES: Final = (
    "'dependent_invalidated', 'derived_state_invalidated', 'entity_redirected', "
    "'owner_reparented', 'row_coalesced', 'self_edge_superseded'"
)

#: Its own function rather than a reuse of `entity_ledger_rows_stay_as_written`,
#: so that dropping this plane's trigger cannot silently disarm the WP-RI-A-01
#: ledgers' -- the argument `2fe4e13fb449` makes for not reusing
#: `f1c6b904a2d7`'s.
_IMMUTABILITY_FUNCTION: Final = "identity_effect_rows_stay_as_written"
_IMMUTABLE_TABLES: Final = (("entity_identity_effects", "entity_identity_effects_are_append_only"),)


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_identity_previews (
          preview_id text PRIMARY KEY,
          principal_id text NOT NULL,
          operation_type text NOT NULL,
          survivor_entity_id text NOT NULL,
          expected_survivor_version integer NOT NULL,
          merged_away jsonb NOT NULL,
          preview_digest text NOT NULL,
          conflict_digest text NOT NULL,
          created_by text NOT NULL,
          actor_class text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          expires_at timestamptz NOT NULL,
          consumed_at timestamptz,
          CONSTRAINT preview_id_is_an_opaque_identifier
            CHECK (preview_id ~ '^eipv_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT survivor_entity_id_is_an_opaque_identifier
            CHECK (survivor_entity_id ~ '^ent_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_preview_operation_type_is_known
            CHECK (operation_type IN ({_OPERATION_TYPE_VALUES})),
          CONSTRAINT a_preview_actor_class_is_known
            CHECK (actor_class IN ({_ACTOR_CLASS_VALUES})),
          CONSTRAINT a_preview_digest_is_a_sha256_digest
            CHECK (preview_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_preview_conflict_digest_is_a_sha256_digest
            CHECK (conflict_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_preview_names_who_asked_for_it
            CHECK (length(trim(created_by)) > 0),
          CONSTRAINT a_preview_expects_a_survivor_version_that_could_exist
            CHECK (expected_survivor_version >= 1),
          CONSTRAINT a_preview_merges_away_a_bounded_set_of_entities
            CHECK (
              jsonb_typeof(merged_away) = 'array'
              AND jsonb_array_length(merged_away) BETWEEN 1 AND {_MAX_MERGED_AWAY}
            ),
          CONSTRAINT a_preview_expires_fifteen_minutes_after_it_was_created
            CHECK (expires_at = created_at + INTERVAL '15 minutes'),
          CONSTRAINT a_preview_is_not_consumed_before_it_was_created
            CHECK (consumed_at IS NULL OR consumed_at >= created_at),
          CONSTRAINT a_preview_is_identified_within_its_principal
            UNIQUE (preview_id, principal_id),
          CONSTRAINT a_preview_retains_an_entity_of_its_principal
            FOREIGN KEY (survivor_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
            ON DELETE CASCADE
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_identity_previews_by_principal
          ON {SCHEMA}.entity_identity_previews (principal_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_identity_operations (
          identity_operation_id text PRIMARY KEY,
          principal_id text NOT NULL,
          operation_type text NOT NULL,
          survivor_entity_id text NOT NULL,
          merged_entity_ids jsonb NOT NULL,
          preview_id text NOT NULL,
          preview_digest text NOT NULL,
          idempotency_key text NOT NULL,
          request_digest text NOT NULL,
          reason text,
          performed_by text NOT NULL,
          actor_class text NOT NULL,
          correlation_id text NOT NULL,
          audit_id text NOT NULL,
          receipt_id text,
          state text NOT NULL,
          started_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT identity_operation_id_is_an_opaque_identifier
            CHECK (identity_operation_id ~ '^eiop_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT survivor_entity_id_is_an_opaque_identifier
            CHECK (survivor_entity_id ~ '^ent_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT preview_id_is_an_opaque_identifier
            CHECK (preview_id ~ '^eipv_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT correlation_id_is_an_opaque_identifier
            CHECK (correlation_id ~ '^corr_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT audit_id_is_an_opaque_identifier
            CHECK (audit_id ~ '^audit_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_identity_operation_type_is_known
            CHECK (operation_type IN ({_OPERATION_TYPE_VALUES})),
          CONSTRAINT an_identity_operation_state_is_known
            CHECK (state IN ({_OPERATION_STATE_VALUES})),
          CONSTRAINT an_identity_operation_actor_class_is_known
            CHECK (actor_class IN ({_ACTOR_CLASS_VALUES})),
          CONSTRAINT an_identity_operation_receipt_id_is_an_opaque_identifier
            CHECK (receipt_id IS NULL OR receipt_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_identity_operation_preview_digest_is_a_sha256_digest
            CHECK (preview_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT an_identity_operation_request_digest_is_a_sha256_digest
            CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT an_identity_operation_idempotency_key_is_bounded
            CHECK (length(idempotency_key) BETWEEN 1 AND {_IDEMPOTENCY_KEY_LIMIT}),
          CONSTRAINT an_identity_operation_names_who_performed_it
            CHECK (length(trim(performed_by)) > 0),
          CONSTRAINT an_identity_operation_reason_is_bounded
            CHECK (
              reason IS NULL
              OR (length(trim(reason)) > 0 AND length(reason) <= {_REASON_LIMIT})
            ),
          CONSTRAINT an_identity_operation_merges_away_a_bounded_set_of_entities
            CHECK (
              jsonb_typeof(merged_entity_ids) = 'array'
              AND jsonb_array_length(merged_entity_ids) BETWEEN 1 AND {_MAX_MERGED_AWAY}
            ),
          CONSTRAINT an_identity_operation_is_finished_exactly_when_it_names_an_end
            CHECK ((state <> 'in_progress') = (completed_at IS NOT NULL)),
          CONSTRAINT an_identity_operation_does_not_end_before_it_started
            CHECK (completed_at IS NULL OR completed_at >= started_at),
          CONSTRAINT one_identity_operation_per_principal_and_key
            UNIQUE (principal_id, idempotency_key),
          CONSTRAINT an_identity_operation_is_identified_within_its_principal
            UNIQUE (identity_operation_id, principal_id),
          CONSTRAINT an_identity_operation_consumes_a_preview_of_its_principal
            FOREIGN KEY (preview_id, principal_id)
            REFERENCES {SCHEMA}.entity_identity_previews (preview_id, principal_id),
          CONSTRAINT an_identity_operation_retains_an_entity_of_its_principal
            FOREIGN KEY (survivor_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
            ON DELETE CASCADE
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_identity_operations_by_principal
          ON {SCHEMA}.entity_identity_operations (principal_id);
        CREATE INDEX entity_identity_operations_by_preview
          ON {SCHEMA}.entity_identity_operations (preview_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_identity_effects (
          effect_id text PRIMARY KEY,
          identity_operation_id text NOT NULL,
          principal_id text NOT NULL,
          sequence integer NOT NULL,
          record_family text NOT NULL,
          record_id text NOT NULL,
          effect_kind text NOT NULL,
          before_state jsonb NOT NULL,
          after_state jsonb NOT NULL,
          before_sha256 text NOT NULL,
          after_sha256 text NOT NULL,
          recorded_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT effect_id_is_an_opaque_identifier
            CHECK (effect_id ~ '^eief_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT identity_operation_id_is_an_opaque_identifier
            CHECK (identity_operation_id ~ '^eiop_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_identity_effect_family_is_known
            CHECK (record_family IN ({_EFFECT_FAMILY_VALUES})),
          CONSTRAINT an_identity_effect_kind_is_known
            CHECK (effect_kind IN ({_EFFECT_KIND_VALUES})),
          CONSTRAINT an_identity_effect_record_id_is_an_opaque_identifier
            CHECK (record_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_identity_effect_sequence_is_positive
            CHECK (sequence >= 1),
          CONSTRAINT an_identity_effect_before_state_says_something
            CHECK (jsonb_typeof(before_state) = 'object' AND before_state <> '{{}}'::jsonb),
          CONSTRAINT an_identity_effect_after_state_says_something
            CHECK (jsonb_typeof(after_state) = 'object' AND after_state <> '{{}}'::jsonb),
          CONSTRAINT an_identity_effect_records_a_change
            CHECK (before_state <> after_state),
          CONSTRAINT an_identity_effect_before_digest_is_a_sha256_digest
            CHECK (before_sha256 ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT an_identity_effect_after_digest_is_a_sha256_digest
            CHECK (after_sha256 ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT one_identity_effect_per_operation_and_sequence
            UNIQUE (identity_operation_id, sequence),
          CONSTRAINT one_identity_effect_per_operation_and_record
            UNIQUE (identity_operation_id, record_family, record_id),
          CONSTRAINT an_identity_effect_records_an_operation_of_its_principal
            FOREIGN KEY (identity_operation_id, principal_id)
            REFERENCES {SCHEMA}.entity_identity_operations
              (identity_operation_id, principal_id)
            ON DELETE CASCADE
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_identity_effects_by_principal
          ON {SCHEMA}.entity_identity_effects (principal_id);
        CREATE INDEX entity_identity_effects_by_operation
          ON {SCHEMA}.entity_identity_effects (identity_operation_id, sequence);
        """
    )

    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
        )


def downgrade() -> None:
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
    op.execute(
        f"""
        DROP TABLE {SCHEMA}.entity_identity_effects;
        DROP TABLE {SCHEMA}.entity_identity_operations;
        DROP TABLE {SCHEMA}.entity_identity_previews;
        """
    )
