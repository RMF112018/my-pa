"""Add the bounded WP-12C application-admission control records.

Revision ID: 9d5e2f7b4c61
Revises: 8c4d1e7a2b90
Create Date: 2026-08-05

The eleven provider-neutral native-source commands widen audit vocabulary. The
three tables bind short-lived admission authority, durable content-free
preflight state, and proposal/Review lineage. They add no worker, watcher,
secret, service, or live-activation state. Downgrade removes them and
restores the prior audit vocabulary exactly.
"""

from __future__ import annotations

from alembic import op

revision: str = "9d5e2f7b4c61"
down_revision: str | None = "8c4d1e7a2b90"
branch_labels: str | None = None
depends_on: str | None = None

_WP12C_CAPABILITIES = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status')"
)

_PRIOR_CAPABILITIES = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)


def _replace(expression: str) -> None:
    op.execute('ALTER TABLE knowledge.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({expression})"
    )


def upgrade() -> None:
    _replace(_WP12C_CAPABILITIES)
    op.execute(
        """
        CREATE TABLE knowledge.native_preflight_observations (
          observation_id text PRIMARY KEY
            CHECK (observation_id ~ '^sobs_[A-Za-z0-9]{8,64}$'),
          configuration_id text NOT NULL,
          configuration_revision integer NOT NULL,
          bucket_id text NOT NULL,
          state text NOT NULL
            CONSTRAINT native_preflight_state_is_known
            CHECK (state IN ('reachable', 'permission_denied', 'unavailable', 'identity_drift')),
          failure text
            CONSTRAINT native_preflight_failure_is_known
            CHECK (failure IS NULL OR failure IN (
              'permission_denied', 'account_unavailable', 'bucket_unavailable',
              'transient_unavailable'
            )),
          observed_at timestamptz NOT NULL,
          CONSTRAINT native_preflight_requires_selected_bucket
            FOREIGN KEY (configuration_id, configuration_revision, bucket_id)
            REFERENCES knowledge.native_configuration_buckets
              (configuration_id, revision, bucket_id),
          CONSTRAINT native_preflight_state_and_failure_agree CHECK (
            (state = 'reachable' AND failure IS NULL) OR
            (state = 'permission_denied' AND failure = 'permission_denied') OR
            (state = 'unavailable' AND failure IN (
              'account_unavailable', 'bucket_unavailable', 'transient_unavailable'
            )) OR
            (state = 'identity_drift' AND failure = 'bucket_unavailable')
          )
        );
        CREATE INDEX native_preflight_latest_by_bucket
          ON knowledge.native_preflight_observations
          (configuration_id, configuration_revision, bucket_id, observed_at);

        CREATE TABLE knowledge.native_admission_authorities (
          authority_id text PRIMARY KEY
            CHECK (authority_id ~ '^nauth_[A-Za-z0-9]{8,64}$'),
          audit_id text NOT NULL REFERENCES knowledge.audit_events(audit_id),
          configuration_id text NOT NULL,
          configuration_revision integer NOT NULL,
          bridge_id text NOT NULL REFERENCES knowledge.native_bridges(bridge_id),
          bucket_id text NOT NULL,
          source_id text NOT NULL REFERENCES knowledge.sources(source_id),
          host_instance_id text NOT NULL
            CHECK (host_instance_id ~ '^nbrg_[A-Za-z0-9]{8,64}$'),
          envelope_id text NOT NULL UNIQUE,
          request_id text NOT NULL,
          issued_at timestamptz NOT NULL,
          expires_at timestamptz NOT NULL,
          consumed_at timestamptz,
          admission_sha256 text,
          CONSTRAINT native_authority_requires_selected_bucket
            FOREIGN KEY (configuration_id, configuration_revision, bucket_id)
            REFERENCES knowledge.native_configuration_buckets
              (configuration_id, revision, bucket_id),
          CONSTRAINT native_authority_binds_host CHECK (bridge_id = host_instance_id),
          CONSTRAINT native_authority_has_positive_lifetime CHECK (expires_at > issued_at),
          CONSTRAINT native_authority_lifetime_is_bounded
            CHECK (expires_at <= issued_at + interval '10 minutes'),
          CONSTRAINT native_authority_wire_ids_are_bounded
            CHECK (length(envelope_id) BETWEEN 1 AND 200
              AND length(request_id) BETWEEN 1 AND 200),
          CONSTRAINT native_authority_consumption_is_complete
            CHECK ((consumed_at IS NULL) = (admission_sha256 IS NULL)),
          CONSTRAINT native_authority_admission_digest_is_sha256
            CHECK (admission_sha256 IS NULL OR admission_sha256 ~ '^[0-9a-f]{64}$')
        );

        CREATE TABLE knowledge.native_source_review_routes (
          source_version_id text NOT NULL
            REFERENCES knowledge.source_object_versions(version_id)
            CHECK (source_version_id ~ '^ver_[A-Za-z0-9]{8,64}$'),
          proposal_id text NOT NULL UNIQUE
            REFERENCES knowledge.capture_proposals(proposal_id)
            CHECK (proposal_id ~ '^prop_[A-Za-z0-9]{8,64}$'),
          review_case_id text NOT NULL UNIQUE
            REFERENCES knowledge.capture_review_cases(review_case_id)
            CHECK (review_case_id ~ '^rvw_[A-Za-z0-9]{8,64}$'),
          routed_at timestamptz NOT NULL,
          PRIMARY KEY (source_version_id, proposal_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE knowledge.native_source_review_routes;
        DROP TABLE knowledge.native_admission_authorities;
        DROP TABLE knowledge.native_preflight_observations;
        """
    )
    _replace(_PRIOR_CAPABILITIES)
