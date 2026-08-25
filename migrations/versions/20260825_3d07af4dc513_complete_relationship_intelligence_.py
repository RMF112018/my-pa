"""Complete Relationship Intelligence Phase B schema.

One additive child of the Phase-B vocabulary revision.  Closed vocabularies
are frozen literals here; this migration does not import live domain enums or
table metadata.

Revision ID: 3d07af4dc513
Revises: b64e29a0f7c1
Created: 2026-08-25 05:25:54.244890
"""

# ruff: noqa: S608 -- all interpolation below is frozen migration-owned literals.

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

revision: str = "3d07af4dc513"
down_revision: str | None = "b64e29a0f7c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"
SUFFIX: Final = "[A-Za-z0-9]{8,64}"


def _frozen_memory_proposal_digest(
    *,
    principal_id: str,
    subject_entity_id: str,
    proposed_kind: str,
    proposed_statement_sha256: str,
    structured_value: dict[str, object] | None,
) -> str:
    """Frozen open-equivalence algorithm; do not replace with a live import."""
    material = {
        "kind": proposed_kind,
        "principal_id": principal_id,
        "statement_sha256": proposed_statement_sha256,
        "structured_value": structured_value,
        "subject_entity_id": subject_entity_id,
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _reconcile_open_memory_proposals(bind: Connection) -> None:
    """Collapse legacy semantic duplicates without deleting historical rows."""
    duplicates = tuple(
        bind.execute(
            text(
            f"""
            SELECT principal_id, memory_proposal_id,
                   first_value(memory_proposal_id) OVER (
                     PARTITION BY principal_id, dedupe_sha256
                     ORDER BY proposed_at, memory_proposal_id
                   ) AS winner_id
              FROM {SCHEMA}.relationship_memory_proposals
             WHERE state IN ('proposed', 'needs_review', 'deferred')
             ORDER BY principal_id, dedupe_sha256, proposed_at, memory_proposal_id
            """
            )
        ).mappings()
    )
    move_missing_evidence = text(
        f"""
        UPDATE {SCHEMA}.relationship_memory_proposal_evidence loser_evidence
           SET memory_proposal_id = :winner_id
         WHERE loser_evidence.principal_id = :principal_id
           AND loser_evidence.memory_proposal_id = :loser_id
           AND NOT EXISTS (
             SELECT 1
               FROM {SCHEMA}.relationship_memory_proposal_evidence winner_evidence
              WHERE winner_evidence.principal_id = loser_evidence.principal_id
                AND winner_evidence.memory_proposal_id = :winner_id
                AND winner_evidence.role = loser_evidence.role
                AND winner_evidence.entity_observation_id IS NOT DISTINCT FROM
                    loser_evidence.entity_observation_id
                AND winner_evidence.capture_span_id IS NOT DISTINCT FROM
                    loser_evidence.capture_span_id
                AND winner_evidence.knowledge_id IS NOT DISTINCT FROM
                    loser_evidence.knowledge_id
           )
        """
    )
    supersede_loser = text(
        f"""
        UPDATE {SCHEMA}.relationship_memory_proposals
           SET state = 'superseded',
               superseded_at = GREATEST(CURRENT_TIMESTAMP, proposed_at),
               superseded_by_memory_proposal_id = :winner_id
         WHERE principal_id = :principal_id
           AND memory_proposal_id = :loser_id
           AND state IN ('proposed', 'needs_review', 'deferred')
        """
    )
    for duplicate in duplicates:
        if duplicate["memory_proposal_id"] == duplicate["winner_id"]:
            continue
        parameters = {
            "principal_id": duplicate["principal_id"],
            "loser_id": duplicate["memory_proposal_id"],
            "winner_id": duplicate["winner_id"],
        }
        bind.execute(move_missing_evidence, parameters)
        bind.execute(supersede_loser, parameters)


def upgrade() -> None:
    # B1/B2: bind existing-target proposal kinds to the exact version read.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT a_proposal_expected_target_version_is_positive,
          DROP CONSTRAINT IF EXISTS a_proposal_expected_target_version_matches_kind,
          ADD CONSTRAINT a_proposal_expected_target_version_matches_kind CHECK (
            (kind IN (
              'update_entity', 'retire_identifier', 'supersede_identifier',
              'retire_alias', 'supersede_alias', 'revise_assignment',
              'end_assignment', 'revise_relationship', 'end_relationship'
            ) AND expected_target_version >= 1)
            OR (kind = 'resolve_mention' AND expected_target_version >= 0)
            OR (kind IN (
              'create_entity', 'bind_identifier', 'record_alias',
              'record_assignment', 'record_relationship', 'merge_entities',
              'split_identity'
            ) AND expected_target_version IS NULL)
          )
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposal_review_decisions
          DROP CONSTRAINT IF EXISTS an_entity_review_decision_names_its_proposal,
          DROP CONSTRAINT IF EXISTS an_entity_review_decision_names_a_proposal_of_its_principal,
          DROP CONSTRAINT IF EXISTS an_entity_review_decision_names_its_proposals_own_case;
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT IF EXISTS an_entity_proposal_review_case_is_bound_to_its_subject,
          ADD CONSTRAINT an_entity_proposal_review_case_is_bound_to_its_subject
            UNIQUE (review_case_id, proposal_id, principal_id);
        ALTER TABLE {SCHEMA}.entity_proposal_review_decisions
          ADD CONSTRAINT an_entity_review_decision_names_its_proposals_own_case
            FOREIGN KEY (review_case_id, proposal_id, principal_id)
            REFERENCES {SCHEMA}.entity_proposals
              (review_case_id, proposal_id, principal_id) ON DELETE CASCADE;
        """
    )

    # B4: legacy candidate memories bind the current subject version once; new
    # writers always supply it. Existing provenance remains first-origin-wins.
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid = '{SCHEMA}.relationship_memory_proposals'::regclass
               AND conname = 'a_memory_proposal_is_identified_within_its_principal'
          ) THEN
            ALTER TABLE {SCHEMA}.relationship_memory_proposals
              ADD CONSTRAINT a_memory_proposal_is_identified_within_its_principal
              UNIQUE (memory_proposal_id, principal_id);
          END IF;
        END $$;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.relationship_memory_proposals
          ADD COLUMN IF NOT EXISTS expected_subject_version integer,
          ADD COLUMN IF NOT EXISTS dedupe_sha256 text,
          ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
          ADD COLUMN IF NOT EXISTS superseded_by_memory_proposal_id text;
        UPDATE {SCHEMA}.relationship_memory_proposals p
           SET expected_subject_version = e.version
          FROM {SCHEMA}.entities e
         WHERE e.entity_id = p.subject_entity_id
           AND e.principal_id = p.principal_id
           AND p.expected_subject_version IS NULL;
        """
    )
    bind = op.get_bind()
    legacy = bind.execute(
        text(
            f"SELECT memory_proposal_id, principal_id, subject_entity_id, proposed_kind, "
            f"proposed_statement_sha256, structured_value "
            f"FROM {SCHEMA}.relationship_memory_proposals WHERE dedupe_sha256 IS NULL"
        )
    ).mappings()
    update_legacy = text(
        f"UPDATE {SCHEMA}.relationship_memory_proposals SET dedupe_sha256 = :digest "
        "WHERE memory_proposal_id = :proposal_id AND dedupe_sha256 IS NULL"
    )
    for row in legacy:
        bind.execute(
            update_legacy,
            {
                "proposal_id": row["memory_proposal_id"],
                "digest": _frozen_memory_proposal_digest(
                    principal_id=row["principal_id"],
                    subject_entity_id=row["subject_entity_id"],
                    proposed_kind=row["proposed_kind"],
                    proposed_statement_sha256=row["proposed_statement_sha256"],
                    structured_value=row["structured_value"],
                ),
            },
        )
    _reconcile_open_memory_proposals(bind)
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.relationship_memory_proposals
          DROP CONSTRAINT IF EXISTS a_memory_proposal_expected_subject_version_is_positive,
          DROP CONSTRAINT IF EXISTS a_memory_proposal_dedupe_is_a_sha256_digest,
          DROP CONSTRAINT IF EXISTS a_superseded_memory_proposal_records_when,
          DROP CONSTRAINT IF EXISTS a_memory_proposal_is_not_superseded_before_it_was_proposed,
          DROP CONSTRAINT IF EXISTS only_a_superseded_memory_proposal_names_its_successor,
          DROP CONSTRAINT IF EXISTS a_memory_proposal_is_not_its_own_successor,
          DROP CONSTRAINT IF EXISTS a_memory_proposal_is_superseded_within_its_principal,
          ALTER COLUMN expected_subject_version SET NOT NULL,
          ALTER COLUMN dedupe_sha256 SET NOT NULL,
          ADD CONSTRAINT a_memory_proposal_expected_subject_version_is_positive
            CHECK (expected_subject_version >= 1),
          ADD CONSTRAINT a_memory_proposal_dedupe_is_a_sha256_digest
            CHECK (dedupe_sha256 ~ '^[0-9a-f]{{64}}$'),
          ADD CONSTRAINT a_superseded_memory_proposal_records_when
            CHECK ((state = 'superseded') = (superseded_at IS NOT NULL)),
          ADD CONSTRAINT a_memory_proposal_is_not_superseded_before_it_was_proposed
            CHECK (superseded_at IS NULL OR superseded_at >= proposed_at),
          ADD CONSTRAINT only_a_superseded_memory_proposal_names_its_successor
            CHECK (superseded_by_memory_proposal_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT a_memory_proposal_is_not_its_own_successor
            CHECK (superseded_by_memory_proposal_id IS NULL OR
                   superseded_by_memory_proposal_id <> memory_proposal_id),
          ADD CONSTRAINT a_memory_proposal_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_memory_proposal_id, principal_id)
            REFERENCES {SCHEMA}.relationship_memory_proposals
              (memory_proposal_id, principal_id)
            DEFERRABLE INITIALLY DEFERRED;
        CREATE UNIQUE INDEX IF NOT EXISTS an_open_equivalent_memory_proposal_is_raised_once
          ON {SCHEMA}.relationship_memory_proposals (principal_id, dedupe_sha256)
          WHERE state IN ('proposed', 'needs_review', 'deferred');
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.relationship_memory_review_decisions
          ADD COLUMN IF NOT EXISTS reason text,
          DROP CONSTRAINT IF EXISTS a_memory_review_reason_explains_a_departure,
          DROP CONSTRAINT IF EXISTS a_memory_escalation_or_invalidation_states_why,
          DROP CONSTRAINT IF EXISTS a_memory_review_reason_is_bounded,
          ADD CONSTRAINT a_memory_review_reason_explains_a_departure CHECK (
            reason IS NULL OR disposition IN
              ('reject', 'defer', 'mark_unresolved', 'escalate', 'invalidate')
          ),
          ADD CONSTRAINT a_memory_escalation_or_invalidation_states_why CHECK (
            disposition NOT IN ('escalate', 'invalidate') OR reason IS NOT NULL
          ),
          ADD CONSTRAINT a_memory_review_reason_is_bounded CHECK (
            reason IS NULL OR length(trim(reason)) BETWEEN 1 AND 500
          );
        """
    )

    # B5: expire legacy previews by giving them a deliberately legacy digest;
    # recomputation at apply makes them stale. Receipts are stable opaque IDs.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_previews
          ADD COLUMN IF NOT EXISTS plan_digest text;
        UPDATE {SCHEMA}.entity_identity_previews
           SET plan_digest = encode(sha256(convert_to('legacy-preview:' || preview_id,
                                                      'UTF8')), 'hex')
         WHERE plan_digest IS NULL;
        ALTER TABLE {SCHEMA}.entity_identity_previews
          DROP CONSTRAINT IF EXISTS a_preview_plan_digest_is_a_sha256_digest,
          ALTER COLUMN plan_digest SET NOT NULL,
          ADD CONSTRAINT a_preview_plan_digest_is_a_sha256_digest
            CHECK (plan_digest ~ '^[0-9a-f]{{64}}$');
        UPDATE {SCHEMA}.entity_identity_operations
           SET receipt_id = 'rcpt_' || md5(identity_operation_id || ':' || principal_id)
         WHERE receipt_id IS NULL;
        ALTER TABLE {SCHEMA}.entity_identity_operations
          DROP CONSTRAINT an_identity_operation_receipt_id_is_an_opaque_identifier,
          DROP CONSTRAINT IF EXISTS one_receipt_per_identity_operation,
          ALTER COLUMN receipt_id SET NOT NULL,
          ADD CONSTRAINT an_identity_operation_receipt_id_is_an_opaque_identifier
            CHECK (receipt_id ~ '^rcpt_{SUFFIX}$'),
          ADD CONSTRAINT one_receipt_per_identity_operation UNIQUE (receipt_id);
        """
    )

    # B7: Principal-scoped, content-free replay receipt and its exact evidence.
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.relationship_write_requests (
          principal_id text NOT NULL,
          capability text NOT NULL,
          request_id text NOT NULL,
          request_digest text NOT NULL,
          result_family text,
          result_id text,
          result_secondary_id text,
          result_version integer,
          result_state text,
          result_subtype text,
          result_requirement text,
          result_disposition text,
          result_assertion_id text,
          result_classification text,
          result_method text,
          result_at timestamptz,
          result_digest text,
          result_count integer,
          result_created boolean,
          receipt_id text,
          audit_id text,
          created_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT one_relationship_write_request_identity
            PRIMARY KEY (principal_id, capability, request_id),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{SUFFIX}$'),
          CONSTRAINT a_relationship_write_request_id_is_bounded
            CHECK (length(trim(request_id)) BETWEEN 1 AND 200),
          CONSTRAINT a_relationship_write_request_capability_is_replay_covered
            CHECK (capability IN ('entities.proposals.create',
                                  'relationship_memory.propose', 'review.decide')),
          CONSTRAINT a_relationship_write_request_digest_is_sha256
            CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_relationship_write_result_digest_is_sha256
            CHECK (result_digest IS NULL OR result_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_relationship_write_result_version_is_not_negative
            CHECK (result_version IS NULL OR result_version >= 0),
          CONSTRAINT a_relationship_write_result_count_is_not_negative
            CHECK (result_count IS NULL OR result_count >= 0),
          CONSTRAINT a_relationship_write_result_family_is_known
            CHECK (result_family IS NULL OR result_family IN
              ('entity_proposal', 'memory_proposal', 'review_decision',
               'review_invalidated')),
          CONSTRAINT a_relationship_write_request_is_completed_once
            CHECK ((completed_at IS NULL) = (result_family IS NULL)),
          CONSTRAINT a_completed_relationship_write_names_its_result
            CHECK (result_family IS NULL OR result_id IS NOT NULL),
          CONSTRAINT a_replayed_review_decision_preserves_its_public_identity
            CHECK (result_family <> 'review_decision' OR
                   (result_disposition IS NOT NULL AND result_version IS NOT NULL)),
          CONSTRAINT a_replayed_invalidation_has_no_invented_decision
            CHECK (result_family <> 'review_invalidated' OR
                   (result_state = 'invalidated' AND result_disposition IS NULL))
        );
        CREATE INDEX relationship_write_requests_by_result
          ON {SCHEMA}.relationship_write_requests
             (principal_id, result_family, result_id);
        CREATE TABLE {SCHEMA}.relationship_write_request_evidence (
          principal_id text NOT NULL,
          capability text NOT NULL,
          request_id text NOT NULL,
          sequence integer NOT NULL,
          role text NOT NULL,
          entity_observation_id text,
          capture_span_id text,
          knowledge_id text,
          CONSTRAINT one_evidence_position_per_relationship_write_request
            PRIMARY KEY (principal_id, capability, request_id, sequence),
          CONSTRAINT relationship_write_evidence_names_its_request
            FOREIGN KEY (principal_id, capability, request_id)
            REFERENCES {SCHEMA}.relationship_write_requests
              (principal_id, capability, request_id) ON DELETE CASCADE,
          CONSTRAINT relationship_write_evidence_sequence_is_positive
            CHECK (sequence >= 1),
          CONSTRAINT relationship_write_evidence_role_is_known
            CHECK (role IN ('direct', 'supporting', 'counterevidence')),
          CONSTRAINT relationship_write_evidence_names_exactly_one_record
            CHECK (num_nonnulls(entity_observation_id, capture_span_id, knowledge_id) = 1)
        );
        """
    )
    for table, prefix, proposal_column in (
        ("entity_proposal_evidence_links", "entity", "proposal_id"),
        ("relationship_memory_proposal_evidence", "memory", "memory_proposal_id"),
    ):
        for source in ("entity_observation_id", "capture_span_id", "knowledge_id"):
            short = source.removesuffix("_id").replace("entity_", "")
            op.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS one_{short}_role_per_{prefix}_proposal "
                f"ON {SCHEMA}.{table} ({proposal_column}, role, {source}) "
                f"WHERE {source} IS NOT NULL"
            )

    # The reservation may transition pending -> completed exactly once. Every
    # later UPDATE and every DELETE is rejected; evidence rows remain governed
    # by their FK and transaction.
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.relationship_write_request_completes_once()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'relationship write requests cannot be deleted';
          END IF;
          IF OLD.completed_at IS NOT NULL OR NEW.completed_at IS NULL OR
             NEW.principal_id <> OLD.principal_id OR
             NEW.capability <> OLD.capability OR NEW.request_id <> OLD.request_id OR
             NEW.request_digest <> OLD.request_digest OR
             NEW.created_at <> OLD.created_at THEN
            RAISE EXCEPTION 'relationship write request transition is immutable';
          END IF;
          RETURN NEW;
        END;
        $$;
        CREATE TRIGGER relationship_write_requests_complete_once
          BEFORE UPDATE OR DELETE ON {SCHEMA}.relationship_write_requests
          FOR EACH ROW EXECUTE FUNCTION
            {SCHEMA}.relationship_write_request_completes_once();
        CREATE FUNCTION {SCHEMA}.relationship_write_request_is_complete_at_commit()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          PERFORM 1 FROM {SCHEMA}.relationship_write_requests
           WHERE principal_id = NEW.principal_id
             AND capability = NEW.capability
             AND request_id = NEW.request_id
             AND completed_at IS NULL;
          IF FOUND THEN
            RAISE EXCEPTION 'relationship write request remained pending at commit';
          END IF;
          RETURN NULL;
        END;
        $$;
        CREATE CONSTRAINT TRIGGER relationship_write_requests_finish_in_transaction
          AFTER INSERT OR UPDATE ON {SCHEMA}.relationship_write_requests
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW EXECUTE FUNCTION
            {SCHEMA}.relationship_write_request_is_complete_at_commit();
        CREATE FUNCTION {SCHEMA}.relationship_write_evidence_stays_as_written()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'relationship write evidence is immutable';
        END;
        $$;
        CREATE TRIGGER relationship_write_request_evidence_is_append_only
          BEFORE UPDATE OR DELETE ON {SCHEMA}.relationship_write_request_evidence
          FOR EACH ROW EXECUTE FUNCTION
            {SCHEMA}.relationship_write_evidence_stays_as_written();
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DROP TRIGGER IF EXISTS relationship_write_requests_complete_once
          ON {SCHEMA}.relationship_write_requests;
        DROP TRIGGER IF EXISTS relationship_write_requests_finish_in_transaction
          ON {SCHEMA}.relationship_write_requests;
        DROP TRIGGER IF EXISTS relationship_write_request_evidence_is_append_only
          ON {SCHEMA}.relationship_write_request_evidence;
        DROP FUNCTION IF EXISTS {SCHEMA}.relationship_write_evidence_stays_as_written();
        DROP FUNCTION IF EXISTS {SCHEMA}.relationship_write_request_is_complete_at_commit();
        DROP FUNCTION IF EXISTS {SCHEMA}.relationship_write_request_completes_once();
        DROP TABLE IF EXISTS {SCHEMA}.relationship_write_request_evidence;
        DROP TABLE IF EXISTS {SCHEMA}.relationship_write_requests;
        DROP INDEX IF EXISTS {SCHEMA}.one_observation_role_per_entity_proposal;
        DROP INDEX IF EXISTS {SCHEMA}.one_capture_span_role_per_entity_proposal;
        DROP INDEX IF EXISTS {SCHEMA}.one_knowledge_role_per_entity_proposal;
        DROP INDEX IF EXISTS {SCHEMA}.one_observation_role_per_memory_proposal;
        DROP INDEX IF EXISTS {SCHEMA}.one_capture_span_role_per_memory_proposal;
        DROP INDEX IF EXISTS {SCHEMA}.one_knowledge_role_per_memory_proposal;
        ALTER TABLE {SCHEMA}.entity_identity_operations
          DROP CONSTRAINT one_receipt_per_identity_operation,
          DROP CONSTRAINT an_identity_operation_receipt_id_is_an_opaque_identifier,
          ALTER COLUMN receipt_id DROP NOT NULL,
          ADD CONSTRAINT an_identity_operation_receipt_id_is_an_opaque_identifier
            CHECK (receipt_id IS NULL OR receipt_id ~ '^[a-z]+_{SUFFIX}$');
        ALTER TABLE {SCHEMA}.entity_identity_previews
          DROP CONSTRAINT a_preview_plan_digest_is_a_sha256_digest,
          DROP COLUMN plan_digest;
        DROP INDEX IF EXISTS {SCHEMA}.an_open_equivalent_memory_proposal_is_raised_once;
        ALTER TABLE {SCHEMA}.relationship_memory_proposals
          DROP CONSTRAINT a_memory_proposal_is_superseded_within_its_principal,
          DROP CONSTRAINT a_memory_proposal_is_not_its_own_successor,
          DROP CONSTRAINT only_a_superseded_memory_proposal_names_its_successor,
          DROP CONSTRAINT a_memory_proposal_is_not_superseded_before_it_was_proposed,
          DROP CONSTRAINT a_superseded_memory_proposal_records_when,
          DROP CONSTRAINT a_memory_proposal_dedupe_is_a_sha256_digest,
          DROP CONSTRAINT a_memory_proposal_expected_subject_version_is_positive,
          DROP COLUMN superseded_by_memory_proposal_id,
          DROP COLUMN superseded_at,
          DROP COLUMN dedupe_sha256,
          DROP COLUMN expected_subject_version;
        ALTER TABLE {SCHEMA}.relationship_memory_review_decisions
          DROP CONSTRAINT a_memory_review_reason_explains_a_departure,
          DROP CONSTRAINT a_memory_escalation_or_invalidation_states_why,
          DROP CONSTRAINT a_memory_review_reason_is_bounded,
          DROP COLUMN reason;
        ALTER TABLE {SCHEMA}.entity_proposal_review_decisions
          DROP CONSTRAINT an_entity_review_decision_names_its_proposals_own_case,
          ADD CONSTRAINT an_entity_review_decision_names_a_proposal_of_its_principal
            FOREIGN KEY (proposal_id, principal_id)
            REFERENCES {SCHEMA}.entity_proposals(proposal_id, principal_id)
            ON DELETE CASCADE;
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT an_entity_proposal_review_case_is_bound_to_its_subject;
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT a_proposal_expected_target_version_matches_kind,
          ADD CONSTRAINT a_proposal_expected_target_version_is_positive
            CHECK (expected_target_version IS NULL OR expected_target_version > 0);
        """
    )
