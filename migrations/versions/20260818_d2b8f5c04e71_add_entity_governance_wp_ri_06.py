"""Add entity observations, proposals, and merge lineage.

Revision ID: d2b8f5c04e71
Revises: c1a7e4b93d58
Create Date: 2026-08-18

WP-RI-06: the three records that make a change to the entity plane governed
rather than merely performed.

* `entity_observations` — what a source said. `entity_id` is nullable, which is
  the record's most important property: an observation nothing has linked is an
  unresolved mention (specification section 13.1), not a failed write.
* `entity_proposals` — what something wants to change, and nothing applies
  itself. The two decision columns are NULL exactly while the proposal is open,
  and `a_proposal_is_decided_exactly_when_something_decided_it` says so, so
  "nothing has decided this" is a shape a reader can trust rather than a
  convention a writer has to remember.
* `entity_merge_records` — the lineage an accepted merge leaves behind (section
  15.3). `merged_entity_id` is UNIQUE because an entity is merged away once; a
  redirect with two targets resolves to neither. `retained_entity_id` is
  deliberately not unique, because many duplicates may be merged into one
  survivor.

Additive. Nothing here alters a table the earlier revisions created. DDL is
written out rather than imported from `tables.py` (`D-48`, `D-69`), closed-set
literals are frozen at this revision, and every constraint is named to match the
declaration.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "d2b8f5c04e71"
down_revision: str | None = "c1a7e4b93d58"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_OBSERVATION_KIND_VALUES: Final = (
    "'calendar_attendee', 'contact_record', 'document_mention', "
    "'message_participant', 'user_statement'"
)

_PROPOSAL_KIND_VALUES: Final = (
    "'bind_identifier', 'create_entity', 'merge_entities', 'record_alias', "
    "'record_assignment', 'record_relationship'"
)

_PROPOSAL_STATE_VALUES: Final = "'accepted', 'proposed', 'rejected', 'superseded'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_observations (
          observation_id text PRIMARY KEY,
          principal_id text NOT NULL,
          kind text NOT NULL,
          observed_value text NOT NULL,
          normalized_value text NOT NULL,
          source_id text NOT NULL,
          source_object_id text NOT NULL,
          source_version_id text NOT NULL,
          observed_at timestamptz NOT NULL,
          recorded_at timestamptz NOT NULL,
          entity_id text
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE SET NULL,
          CONSTRAINT observation_id_is_an_opaque_identifier
            CHECK (observation_id ~ '^eobs_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_observation_kind_is_known
            CHECK (kind IN ({_OBSERVATION_KIND_VALUES})),
          CONSTRAINT an_observation_records_what_was_observed
            CHECK (length(trim(observed_value)) > 0),
          CONSTRAINT an_observation_records_the_form_it_is_matched_by
            CHECK (length(trim(normalized_value)) > 0),
          CONSTRAINT an_observation_is_not_recorded_before_it_was_observed
            CHECK (recorded_at >= observed_at)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_observations_by_principal
          ON {SCHEMA}.entity_observations (principal_id);
        CREATE INDEX entity_observations_by_normalized_value
          ON {SCHEMA}.entity_observations (principal_id, normalized_value);
        CREATE INDEX entity_observations_by_entity
          ON {SCHEMA}.entity_observations (entity_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_proposals (
          proposal_id text PRIMARY KEY,
          principal_id text NOT NULL,
          kind text NOT NULL,
          state text NOT NULL DEFAULT 'proposed',
          payload jsonb NOT NULL,
          observation_ids jsonb NOT NULL,
          proposed_at timestamptz NOT NULL,
          proposed_by text NOT NULL,
          decided_by text,
          decided_at timestamptz,
          decision_reason text,
          CONSTRAINT proposal_id_is_an_opaque_identifier
            CHECK (proposal_id ~ '^eprp_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_proposal_kind_is_known
            CHECK (kind IN ({_PROPOSAL_KIND_VALUES})),
          CONSTRAINT a_proposal_state_is_known
            CHECK (state IN ({_PROPOSAL_STATE_VALUES})),
          CONSTRAINT a_proposal_names_what_proposed_it
            CHECK (length(trim(proposed_by)) > 0),
          CONSTRAINT a_proposal_is_decided_exactly_when_something_decided_it
            CHECK ((state IN ('accepted', 'rejected')) = (decided_by IS NOT NULL)),
          CONSTRAINT a_proposal_decision_has_both_an_actor_and_a_moment
            CHECK ((decided_by IS NULL) = (decided_at IS NULL)),
          CONSTRAINT a_proposal_is_not_decided_before_it_was_proposed
            CHECK (decided_at IS NULL OR decided_at >= proposed_at)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_proposals_by_principal
          ON {SCHEMA}.entity_proposals (principal_id);
        CREATE INDEX entity_proposals_by_state
          ON {SCHEMA}.entity_proposals (principal_id, state);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_merge_records (
          merge_id text PRIMARY KEY,
          principal_id text NOT NULL,
          retained_entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          merged_entity_id text NOT NULL UNIQUE
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          proposal_id text NOT NULL
            REFERENCES {SCHEMA}.entity_proposals(proposal_id),
          decided_by text NOT NULL,
          reason text NOT NULL,
          decided_at timestamptz NOT NULL,
          CONSTRAINT merge_id_is_an_opaque_identifier
            CHECK (merge_id ~ '^emrg_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_merge_joins_two_distinct_entities
            CHECK (retained_entity_id <> merged_entity_id),
          CONSTRAINT a_merge_names_who_decided_it
            CHECK (length(trim(decided_by)) > 0),
          CONSTRAINT a_merge_records_why_it_was_accepted
            CHECK (length(trim(reason)) > 0)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_merge_records_by_principal
          ON {SCHEMA}.entity_merge_records (principal_id);
        CREATE INDEX entity_merge_records_by_retained
          ON {SCHEMA}.entity_merge_records (retained_entity_id);
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TABLE IF EXISTS {SCHEMA}.entity_merge_records;
        DROP TABLE IF EXISTS {SCHEMA}.entity_proposals;
        DROP TABLE IF EXISTS {SCHEMA}.entity_observations;
        """
    )
