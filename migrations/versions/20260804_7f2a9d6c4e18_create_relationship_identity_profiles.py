"""Create the WP-9 relationship identity and profile substrate.

Revision ID: 7f2a9d6c4e18
Revises: 3c8f1e2a5b74
Create Date: 2026-08-04

The SQL is frozen in this revision rather than derived from live domain enums.
Source observations and canonical identities are separate tables. Deferred and
governed triggers make a person insert, an observation link, or a person merge
impossible unless its exact accepted relationship-identity review and resolution
are present in the same transaction.
"""

from __future__ import annotations

from alembic import op

revision: str = "7f2a9d6c4e18"
down_revision: str | None = "3c8f1e2a5b74"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "knowledge"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE knowledge.relationship_people (
          person_id text PRIMARY KEY CHECK (person_id ~ '^per_[A-Za-z0-9]{8,64}$'),
          display_name text NOT NULL CHECK (length(trim(display_name)) > 0),
          created_at timestamptz NOT NULL DEFAULT now(),
          superseded_by_person_id text UNIQUE
            REFERENCES knowledge.relationship_people(person_id),
          state_resolution_id text UNIQUE
        );
        CREATE TABLE knowledge.relationship_organizations (
          organization_id text PRIMARY KEY CHECK (organization_id ~ '^org_[A-Za-z0-9]{8,64}$'),
          display_name text NOT NULL CHECK (length(trim(display_name)) > 0),
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE knowledge.relationship_identity_observations (
          observation_id text PRIMARY KEY CHECK (observation_id ~ '^iobs_[A-Za-z0-9]{8,64}$'),
          source_id text NOT NULL CHECK (source_id ~ '^src_[A-Za-z0-9]{8,64}$'),
          source_object_id text NOT NULL CHECK (source_object_id ~ '^obj_[A-Za-z0-9]{8,64}$'),
          source_version text NOT NULL CHECK (length(source_version) BETWEEN 1 AND 72),
          source_domain text NOT NULL
            CHECK (source_domain IN ('calendar', 'contacts', 'email')),
          display_name text,
          observed_at timestamptz NOT NULL,
          CONSTRAINT an_observed_source_version_is_recorded_once
            UNIQUE (source_id, source_object_id, source_version)
        );
        CREATE TABLE knowledge.relationship_unresolved_mentions (
          unresolved_mention_id text PRIMARY KEY
            CHECK (unresolved_mention_id ~ '^umen_[A-Za-z0-9]{8,64}$'),
          source_object_id text NOT NULL CHECK (source_object_id ~ '^obj_[A-Za-z0-9]{8,64}$'),
          source_version text NOT NULL CHECK (length(source_version) BETWEEN 1 AND 72),
          observed_at timestamptz NOT NULL
        );
        CREATE TABLE knowledge.relationship_duplicate_sets (
          duplicate_set_id text PRIMARY KEY CHECK (duplicate_set_id ~ '^dups_[A-Za-z0-9]{8,64}$'),
          candidate_kind text NOT NULL
            CHECK (candidate_kind IN ('identity_resolution', 'duplicate')),
          created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE knowledge.relationship_duplicate_members (
          duplicate_set_id text NOT NULL
            REFERENCES knowledge.relationship_duplicate_sets(duplicate_set_id),
          person_id text REFERENCES knowledge.relationship_people(person_id),
          observation_id text
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          CONSTRAINT a_duplicate_member_names_one_candidate_kind
            CHECK ((person_id IS NULL) <> (observation_id IS NULL)),
          CONSTRAINT a_person_occurs_once_in_a_duplicate_set UNIQUE (duplicate_set_id, person_id),
          CONSTRAINT an_observation_occurs_once_in_a_duplicate_set
            UNIQUE (duplicate_set_id, observation_id)
        );
        CREATE TABLE knowledge.relationship_identity_review_cases (
          review_case_id text PRIMARY KEY CHECK (review_case_id ~ '^rvw_[A-Za-z0-9]{8,64}$'),
          duplicate_set_id text NOT NULL UNIQUE
            REFERENCES knowledge.relationship_duplicate_sets(duplicate_set_id),
          requested_action text NOT NULL
            CHECK (requested_action IN ('link_observation', 'merge_person', 'split_person')),
          retained_person_id text REFERENCES knowledge.relationship_people(person_id),
          prior_person_id text REFERENCES knowledge.relationship_people(person_id),
          opened_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT a_merge_or_split_review_names_both_people CHECK (
            (requested_action IN ('merge_person', 'split_person')) =
            (retained_person_id IS NOT NULL AND prior_person_id IS NOT NULL)
          ),
          CONSTRAINT an_identity_review_names_distinct_people CHECK (
            retained_person_id IS NULL OR retained_person_id <> prior_person_id
          )
        );
        CREATE TABLE knowledge.relationship_identity_review_decisions (
          decision_id text PRIMARY KEY CHECK (decision_id ~ '^rdec_[A-Za-z0-9]{8,64}$'),
          review_case_id text NOT NULL
            REFERENCES knowledge.relationship_identity_review_cases(review_case_id),
          sequence integer NOT NULL CHECK (sequence >= 1),
          disposition text NOT NULL CHECK (disposition IN ('accept', 'defer', 'reject')),
          principal_id text NOT NULL CHECK (principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'),
          decided_at timestamptz NOT NULL,
          CONSTRAINT one_identity_decision_per_sequence UNIQUE (review_case_id, sequence)
        );
        CREATE TABLE knowledge.relationship_identity_resolutions (
          resolution_id text PRIMARY KEY CHECK (resolution_id ~ '^ires_[A-Za-z0-9]{8,64}$'),
          resolution_sequence bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
          action text NOT NULL
            CHECK (action IN ('link_observation', 'merge_person', 'split_person')),
          review_case_id text NOT NULL
            REFERENCES knowledge.relationship_identity_review_cases(review_case_id),
          decision_id text NOT NULL UNIQUE
            REFERENCES knowledge.relationship_identity_review_decisions(decision_id),
          retained_person_id text NOT NULL REFERENCES knowledge.relationship_people(person_id),
          prior_person_id text REFERENCES knowledge.relationship_people(person_id),
          decided_at timestamptz NOT NULL,
          CONSTRAINT a_merge_or_split_retains_both_people
            CHECK ((action = 'link_observation') = (prior_person_id IS NULL)),
          CONSTRAINT an_identity_resolution_names_distinct_people CHECK (
            prior_person_id IS NULL OR retained_person_id <> prior_person_id
          )
        );
        ALTER TABLE knowledge.relationship_people
          ADD CONSTRAINT relationship_people_state_resolution_id_fkey
          FOREIGN KEY (state_resolution_id)
          REFERENCES knowledge.relationship_identity_resolutions(resolution_id);
        CREATE TABLE knowledge.relationship_resolution_observations (
          resolution_id text NOT NULL
            REFERENCES knowledge.relationship_identity_resolutions(resolution_id),
          observation_id text NOT NULL
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          PRIMARY KEY (resolution_id, observation_id)
        );
        CREATE TABLE knowledge.relationship_observation_links (
          observation_id text PRIMARY KEY
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          person_id text NOT NULL REFERENCES knowledge.relationship_people(person_id),
          resolution_id text NOT NULL
            REFERENCES knowledge.relationship_identity_resolutions(resolution_id)
        );
        CREATE TABLE knowledge.relationship_aliases (
          alias_id text PRIMARY KEY CHECK (alias_id ~ '^alias_[A-Za-z0-9]{8,64}$'),
          person_id text NOT NULL REFERENCES knowledge.relationship_people(person_id),
          observation_id text NOT NULL
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          value text NOT NULL CHECK (length(trim(value)) > 0),
          CONSTRAINT one_source_bound_alias_per_observation UNIQUE (observation_id)
        );
        CREATE TABLE knowledge.relationship_affiliations (
          affiliation_id text PRIMARY KEY CHECK (affiliation_id ~ '^aff_[A-Za-z0-9]{8,64}$'),
          person_id text NOT NULL REFERENCES knowledge.relationship_people(person_id),
          organization_id text NOT NULL
            REFERENCES knowledge.relationship_organizations(organization_id),
          observation_id text NOT NULL
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          role text,
          effective_from timestamptz,
          effective_to timestamptz,
          CONSTRAINT an_affiliation_ends_after_it_starts CHECK (
            effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from
          )
        );
        CREATE TABLE knowledge.relationship_evidence (
          evidence_id text PRIMARY KEY,
          person_id text NOT NULL REFERENCES knowledge.relationship_people(person_id),
          authority text NOT NULL CHECK (authority IN (
            'source_observation', 'accepted_assertion', 'user_authored_private_note',
            'public_assertion', 'model_inference', 'unresolved_claim', 'contradiction',
            'stale_assertion'
          )),
          effective_at timestamptz,
          recorded_at timestamptz NOT NULL
        );
        CREATE TABLE knowledge.relationship_evidence_observations (
          evidence_id text NOT NULL REFERENCES knowledge.relationship_evidence(evidence_id),
          observation_id text NOT NULL
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          PRIMARY KEY (evidence_id, observation_id)
        );
        CREATE TABLE knowledge.relationship_conversation_participants (
          participant_id text PRIMARY KEY CHECK (participant_id ~ '^cpart_[A-Za-z0-9]{8,64}$'),
          conversation_id text NOT NULL
            REFERENCES knowledge.capture_conversations(conversation_id),
          person_id text REFERENCES knowledge.relationship_people(person_id),
          unresolved_mention_id text
            REFERENCES knowledge.relationship_unresolved_mentions(unresolved_mention_id),
          CONSTRAINT a_conversation_participant_names_one_identity_target
            CHECK ((person_id IS NULL) <> (unresolved_mention_id IS NULL))
        );
        CREATE UNIQUE INDEX a_conversation_names_a_person_once
          ON knowledge.relationship_conversation_participants (conversation_id, person_id)
          WHERE person_id IS NOT NULL;
        CREATE UNIQUE INDEX a_conversation_names_an_unresolved_mention_once
          ON knowledge.relationship_conversation_participants
          (conversation_id, unresolved_mention_id)
          WHERE unresolved_mention_id IS NOT NULL;
        CREATE TABLE knowledge.relationship_conversation_observations (
          participant_id text NOT NULL
            REFERENCES knowledge.relationship_conversation_participants(participant_id),
          observation_id text NOT NULL
            REFERENCES knowledge.relationship_identity_observations(observation_id),
          PRIMARY KEY (participant_id, observation_id)
        );
        """
    )
    op.execute(
        """
        CREATE FUNCTION knowledge.identity_review_has_honest_candidate_set() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE candidate_kind text; candidate_count integer;
        BEGIN
          SELECT s.candidate_kind, count(m.duplicate_set_id)
            INTO candidate_kind, candidate_count
          FROM knowledge.relationship_duplicate_sets s
          LEFT JOIN knowledge.relationship_duplicate_members m
            ON m.duplicate_set_id = s.duplicate_set_id
          WHERE s.duplicate_set_id = NEW.duplicate_set_id
          GROUP BY s.candidate_kind;
          IF candidate_count < 1 OR (
            NEW.requested_action IN ('merge_person', 'split_person')
            AND (candidate_kind <> 'duplicate' OR candidate_count < 2)
          ) OR (
            NEW.requested_action IN ('merge_person', 'split_person')
            AND (
              EXISTS (
                (SELECT m.person_id
                 FROM knowledge.relationship_duplicate_members m
                 WHERE m.duplicate_set_id = NEW.duplicate_set_id AND m.person_id IS NOT NULL)
                EXCEPT
                (SELECT candidate FROM (VALUES
                  (NEW.retained_person_id), (NEW.prior_person_id)
                ) AS reviewed(candidate))
              )
              OR EXISTS (
                (SELECT candidate FROM (VALUES
                  (NEW.retained_person_id), (NEW.prior_person_id)
                ) AS reviewed(candidate))
                EXCEPT
                (SELECT m.person_id
                 FROM knowledge.relationship_duplicate_members m
                 WHERE m.duplicate_set_id = NEW.duplicate_set_id AND m.person_id IS NOT NULL)
              )
            )
          ) THEN
            RAISE EXCEPTION 'identity review requires an honest candidate set'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER identity_review_requires_candidates
          BEFORE INSERT ON knowledge.relationship_identity_review_cases
          FOR EACH ROW EXECUTE FUNCTION knowledge.identity_review_has_honest_candidate_set();

        CREATE FUNCTION knowledge.identity_resolution_is_reviewed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM knowledge.relationship_identity_review_cases c
            JOIN knowledge.relationship_identity_review_decisions d
              ON d.review_case_id = c.review_case_id
            WHERE c.review_case_id = NEW.review_case_id
              AND d.decision_id = NEW.decision_id
              AND d.disposition = 'accept'
              AND d.sequence = (
                SELECT max(latest.sequence)
                FROM knowledge.relationship_identity_review_decisions latest
                WHERE latest.review_case_id = c.review_case_id
              )
              AND c.requested_action = NEW.action
              AND (NEW.action = 'link_observation' OR (
                c.retained_person_id = NEW.retained_person_id
                AND c.prior_person_id = NEW.prior_person_id
              ))
          ) THEN
            RAISE EXCEPTION 'identity resolution requires its exact accepted review'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER identity_resolution_requires_review
          BEFORE INSERT ON knowledge.relationship_identity_resolutions
          FOR EACH ROW EXECUTE FUNCTION knowledge.identity_resolution_is_reviewed();

        CREATE FUNCTION knowledge.identity_resolution_has_exact_observations() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF EXISTS (
            (SELECT m.observation_id
             FROM knowledge.relationship_duplicate_members m
             JOIN knowledge.relationship_identity_review_cases c
               ON c.duplicate_set_id = m.duplicate_set_id
             WHERE c.review_case_id = NEW.review_case_id
               AND m.observation_id IS NOT NULL)
            EXCEPT
            (SELECT ro.observation_id
             FROM knowledge.relationship_resolution_observations ro
             WHERE ro.resolution_id = NEW.resolution_id)
          ) OR EXISTS (
            (SELECT ro.observation_id
             FROM knowledge.relationship_resolution_observations ro
             WHERE ro.resolution_id = NEW.resolution_id)
            EXCEPT
            (SELECT m.observation_id
             FROM knowledge.relationship_duplicate_members m
             JOIN knowledge.relationship_identity_review_cases c
               ON c.duplicate_set_id = m.duplicate_set_id
             WHERE c.review_case_id = NEW.review_case_id
               AND m.observation_id IS NOT NULL)
          ) OR NOT EXISTS (
            SELECT 1 FROM knowledge.relationship_resolution_observations ro
            WHERE ro.resolution_id = NEW.resolution_id
          ) THEN
            RAISE EXCEPTION 'identity resolution requires its exact reviewed observation set'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NULL;
        END; $$;
        CREATE CONSTRAINT TRIGGER identity_resolution_requires_exact_observations
          AFTER INSERT ON knowledge.relationship_identity_resolutions
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
          EXECUTE FUNCTION knowledge.identity_resolution_has_exact_observations();

        CREATE FUNCTION knowledge.canonical_person_is_reviewed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM knowledge.relationship_people p
            JOIN knowledge.relationship_identity_resolutions r
              ON r.resolution_id = p.state_resolution_id
            WHERE p.person_id = NEW.person_id
              AND r.retained_person_id = p.person_id
              AND r.action IN ('link_observation', 'split_person')
          ) THEN
            RAISE EXCEPTION 'a canonical person requires a governed resolution'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NULL;
        END; $$;
        CREATE CONSTRAINT TRIGGER canonical_person_requires_resolution
          AFTER INSERT ON knowledge.relationship_people
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
          EXECUTE FUNCTION knowledge.canonical_person_is_reviewed();

        CREATE FUNCTION knowledge.person_merge_is_reviewed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.person_id IS DISTINCT FROM OLD.person_id
             OR NEW.display_name IS DISTINCT FROM OLD.display_name
             OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
            RAISE EXCEPTION 'canonical person identity fields are immutable'
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF OLD.state_resolution_id IS NULL THEN
            IF NEW.state_resolution_id IS NULL
               OR NEW.superseded_by_person_id IS DISTINCT FROM OLD.superseded_by_person_id
               OR NOT EXISTS (
                 SELECT 1 FROM knowledge.relationship_identity_resolutions r
                 WHERE r.resolution_id = NEW.state_resolution_id
                   AND r.action = 'link_observation'
                   AND r.retained_person_id = NEW.person_id
               ) THEN
              RAISE EXCEPTION 'initial person state requires its link resolution'
                USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
          END IF;
          IF NEW.state_resolution_id IS NOT DISTINCT FROM OLD.state_resolution_id
             OR NEW.superseded_by_person_id IS NOT DISTINCT FROM OLD.superseded_by_person_id
             OR NOT EXISTS (
               SELECT 1 FROM knowledge.relationship_identity_resolutions r
               WHERE r.resolution_id = NEW.state_resolution_id
                 AND r.resolution_sequence = (
                   SELECT max(latest.resolution_sequence)
                   FROM knowledge.relationship_identity_resolutions latest
                   WHERE (latest.retained_person_id = r.retained_person_id
                          AND latest.prior_person_id = r.prior_person_id)
                      OR (latest.retained_person_id = r.prior_person_id
                          AND latest.prior_person_id = r.retained_person_id)
                 )
                 AND ((r.action = 'merge_person'
                       AND r.retained_person_id = NEW.superseded_by_person_id
                       AND r.prior_person_id = NEW.person_id)
                   OR (r.action = 'split_person'
                       AND r.retained_person_id = NEW.person_id
                       AND r.prior_person_id = OLD.superseded_by_person_id
                       AND NEW.superseded_by_person_id IS NULL))
             ) THEN
            RAISE EXCEPTION 'a person merge requires a governed resolution'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER person_merge_requires_resolution
          BEFORE UPDATE ON knowledge.relationship_people
          FOR EACH ROW EXECUTE FUNCTION knowledge.person_merge_is_reviewed();

        CREATE FUNCTION knowledge.observation_link_is_current_resolution() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM knowledge.relationship_identity_resolutions r
            JOIN knowledge.relationship_resolution_observations ro
              ON ro.resolution_id = r.resolution_id
            WHERE r.resolution_id = NEW.resolution_id
              AND r.retained_person_id = NEW.person_id
              AND ro.observation_id = NEW.observation_id
              AND r.resolution_sequence = (
                SELECT max(latest.resolution_sequence)
                FROM knowledge.relationship_identity_resolutions latest
                JOIN knowledge.relationship_resolution_observations latest_ro
                  ON latest_ro.resolution_id = latest.resolution_id
                WHERE latest_ro.observation_id = NEW.observation_id
              )
          ) THEN
            RAISE EXCEPTION 'an observation link requires its current exact resolution'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER observation_link_requires_current_resolution
          BEFORE INSERT OR UPDATE ON knowledge.relationship_observation_links
          FOR EACH ROW EXECUTE FUNCTION knowledge.observation_link_is_current_resolution();

        CREATE FUNCTION knowledge.identity_resolution_stays_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'identity resolution lineage is append-only'
            USING ERRCODE = 'restrict_violation';
        END; $$;
        CREATE TRIGGER identity_resolutions_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_identity_resolutions
          FOR EACH ROW EXECUTE FUNCTION knowledge.identity_resolution_stays_append_only();

        CREATE FUNCTION knowledge.relationship_organization_stays_as_observed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'relationship organization identity is append-only'
            USING ERRCODE = 'restrict_violation';
        END; $$;
        CREATE TRIGGER relationship_organizations_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_organizations
          FOR EACH ROW EXECUTE FUNCTION knowledge.relationship_organization_stays_as_observed();

        CREATE FUNCTION knowledge.relationship_identity_evidence_stays_append_only()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'relationship identity evidence is append-only'
            USING ERRCODE = 'restrict_violation';
        END; $$;
        CREATE TRIGGER identity_observations_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_identity_observations
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();
        CREATE TRIGGER unresolved_mentions_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_unresolved_mentions
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();
        CREATE TRIGGER identity_candidate_sets_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_duplicate_sets
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();
        CREATE TRIGGER identity_candidate_members_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_duplicate_members
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();
        CREATE TRIGGER identity_review_cases_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_identity_review_cases
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();
        CREATE TRIGGER identity_review_decisions_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_identity_review_decisions
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();
        CREATE TRIGGER resolution_observations_are_append_only
          BEFORE UPDATE OR DELETE ON knowledge.relationship_resolution_observations
          FOR EACH ROW EXECUTE FUNCTION
            knowledge.relationship_identity_evidence_stays_append_only();

        CREATE FUNCTION knowledge.relationship_alias_matches_observation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM knowledge.relationship_identity_observations o
            JOIN knowledge.relationship_observation_links l
              ON l.observation_id = o.observation_id
            WHERE o.observation_id = NEW.observation_id
              AND o.display_name IS NOT NULL
              AND length(trim(o.display_name)) > 0
              AND o.display_name = NEW.value
              AND l.person_id = NEW.person_id
          ) THEN
            RAISE EXCEPTION 'a source-bound alias requires its exact current observation'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER relationship_aliases_match_observations
          BEFORE INSERT OR UPDATE ON knowledge.relationship_aliases
          FOR EACH ROW EXECUTE FUNCTION knowledge.relationship_alias_matches_observation();

        CREATE FUNCTION knowledge.conversation_support_matches_participant() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE participant record;
        BEGIN
          SELECT * INTO participant
          FROM knowledge.relationship_conversation_participants p
          WHERE p.participant_id = NEW.participant_id;
          IF participant.person_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM knowledge.relationship_observation_links l
            WHERE l.observation_id = NEW.observation_id
              AND l.person_id = participant.person_id
          ) THEN
            RAISE EXCEPTION 'conversation support must identify its resolved participant'
              USING ERRCODE = 'restrict_violation';
          END IF;
          IF participant.unresolved_mention_id IS NOT NULL AND NOT EXISTS (
            SELECT 1
            FROM knowledge.relationship_unresolved_mentions m
            JOIN knowledge.relationship_identity_observations o
              ON o.source_object_id = m.source_object_id
             AND o.source_version = m.source_version
            WHERE m.unresolved_mention_id = participant.unresolved_mention_id
              AND o.observation_id = NEW.observation_id
          ) THEN
            RAISE EXCEPTION 'conversation support must match its unresolved source identity'
              USING ERRCODE = 'restrict_violation';
          END IF;
          RETURN NEW;
        END; $$;
        CREATE TRIGGER conversation_support_matches_participant
          BEFORE INSERT OR UPDATE ON knowledge.relationship_conversation_observations
          FOR EACH ROW EXECUTE FUNCTION knowledge.conversation_support_matches_participant();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER conversation_support_matches_participant
          ON knowledge.relationship_conversation_observations;
        DROP FUNCTION knowledge.conversation_support_matches_participant();
        DROP TRIGGER relationship_aliases_match_observations
          ON knowledge.relationship_aliases;
        DROP FUNCTION knowledge.relationship_alias_matches_observation();
        DROP TRIGGER person_merge_requires_resolution ON knowledge.relationship_people;
        DROP FUNCTION knowledge.person_merge_is_reviewed();
        DROP TRIGGER observation_link_requires_current_resolution
          ON knowledge.relationship_observation_links;
        DROP FUNCTION knowledge.observation_link_is_current_resolution();
        DROP TRIGGER identity_resolutions_are_append_only
          ON knowledge.relationship_identity_resolutions;
        DROP FUNCTION knowledge.identity_resolution_stays_append_only();
        DROP TRIGGER relationship_organizations_are_append_only
          ON knowledge.relationship_organizations;
        DROP FUNCTION knowledge.relationship_organization_stays_as_observed();
        DROP TRIGGER identity_observations_are_append_only
          ON knowledge.relationship_identity_observations;
        DROP TRIGGER unresolved_mentions_are_append_only
          ON knowledge.relationship_unresolved_mentions;
        DROP TRIGGER identity_candidate_sets_are_append_only
          ON knowledge.relationship_duplicate_sets;
        DROP TRIGGER identity_candidate_members_are_append_only
          ON knowledge.relationship_duplicate_members;
        DROP TRIGGER identity_review_cases_are_append_only
          ON knowledge.relationship_identity_review_cases;
        DROP TRIGGER identity_review_decisions_are_append_only
          ON knowledge.relationship_identity_review_decisions;
        DROP TRIGGER resolution_observations_are_append_only
          ON knowledge.relationship_resolution_observations;
        DROP FUNCTION knowledge.relationship_identity_evidence_stays_append_only();
        DROP TRIGGER canonical_person_requires_resolution ON knowledge.relationship_people;
        DROP FUNCTION knowledge.canonical_person_is_reviewed();
        DROP TRIGGER identity_review_requires_candidates
          ON knowledge.relationship_identity_review_cases;
        DROP FUNCTION knowledge.identity_review_has_honest_candidate_set();
        DROP TRIGGER identity_resolution_requires_review
          ON knowledge.relationship_identity_resolutions;
        DROP FUNCTION knowledge.identity_resolution_is_reviewed();
        DROP TRIGGER identity_resolution_requires_exact_observations
          ON knowledge.relationship_identity_resolutions;
        DROP FUNCTION knowledge.identity_resolution_has_exact_observations();
        DROP TABLE knowledge.relationship_conversation_observations;
        DROP TABLE knowledge.relationship_conversation_participants;
        DROP TABLE knowledge.relationship_evidence_observations;
        DROP TABLE knowledge.relationship_evidence;
        DROP TABLE knowledge.relationship_affiliations;
        DROP TABLE knowledge.relationship_aliases;
        DROP TABLE knowledge.relationship_observation_links;
        DROP TABLE knowledge.relationship_resolution_observations;
        ALTER TABLE knowledge.relationship_people
          DROP CONSTRAINT relationship_people_state_resolution_id_fkey;
        DROP TABLE knowledge.relationship_identity_resolutions;
        DROP TABLE knowledge.relationship_identity_review_decisions;
        DROP TABLE knowledge.relationship_identity_review_cases;
        DROP TABLE knowledge.relationship_duplicate_members;
        DROP TABLE knowledge.relationship_duplicate_sets;
        DROP TABLE knowledge.relationship_unresolved_mentions;
        DROP TABLE knowledge.relationship_identity_observations;
        DROP TABLE knowledge.relationship_organizations;
        DROP TABLE knowledge.relationship_people;
        """
    )
