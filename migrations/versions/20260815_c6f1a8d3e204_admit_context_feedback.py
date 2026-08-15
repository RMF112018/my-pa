"""Admit `context.feedback` and create preference event and projection tables.

Revision ID: c6f1a8d3e204
Revises: 9b2d5f8c3e01
Create Date: 2026-08-15

WP-KC-06. The forward `ALTER` admits `context.feedback` and `context_preference`
to the audited vocabulary, then creates the append-only event table and the
current projection table. DDL is written out rather than imported from
`tables.py` (`D-48`, `D-69`). Closed-set literals are frozen at this revision.
Events are never deleted; reversal appends. The projection is folded in the
same transaction as the append.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c6f1a8d3e204"
down_revision: str | None = "9b2d5f8c3e01"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The capability vocabulary as of this revision: what `8a1c4e7b2d90` installed,
#: plus `context.feedback`, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'context.feedback', "
    "'context.prepare', 'continuity.projects', 'continuity.projects.create', "
    "'continuity.pulse', 'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: What `8a1c4e7b2d90` installed, restated rather than derived.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: The purpose vocabulary as of this revision: fourteen prior names plus
#: `context_preference`, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'context_preference', 'context_preparation', "
    "'continuity_authoring', 'document_authoring', 'document_read', "
    "'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation')"
)

#: What `8a1c4e7b2d90` installed, restated rather than derived.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction."""
    for name, expression in (
        ("capability_is_known", capability),
        ("purpose_is_known", purpose),
    ):
        op.execute(f'ALTER TABLE knowledge.audit_events DROP CONSTRAINT "{name}"')
        op.execute(
            f'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "{name}" CHECK ({expression})'
        )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.context_preference_events (
          event_id text NOT NULL
            CHECK (event_id ~ '^cpref_[A-Za-z0-9]{{8,64}}$'),
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          action text NOT NULL
            CHECK (action IN (
              'clear', 'confirm_alias', 'deprefer_source', 'mark_irrelevant',
              'mark_relevant', 'pin', 'prefer_source', 'remove_alias', 'unpin'
            )),
          target_id text NOT NULL
            CHECK (target_id ~ '^[a-z]+_[A-Za-z0-9]{{8,64}}$'),
          alias text
            CHECK (alias IS NULL OR length(alias) BETWEEN 1 AND 64),
          source_id text
            CHECK (
              source_id IS NULL OR source_id ~ '^src_[A-Za-z0-9]{{8,64}}$'
            ),
          idempotency_key text NOT NULL
            CHECK (length(idempotency_key) BETWEEN 1 AND 128),
          event_number integer NOT NULL
            CHECK (event_number >= 1),
          created_at timestamptz NOT NULL,
          superseded_at timestamptz,
          correlation_id text NOT NULL
            CHECK (correlation_id ~ '^corr_[A-Za-z0-9]{{8,64}}$'),
          audit_id text
            CHECK (
              audit_id IS NULL OR audit_id ~ '^audit_[A-Za-z0-9]{{8,64}}$'
            ),
          request_id text NOT NULL
            CHECK (length(request_id) BETWEEN 1 AND 128),
          CONSTRAINT context_preference_events_pkey PRIMARY KEY (event_id),
          CONSTRAINT one_preference_key_per_principal
            UNIQUE (principal_id, idempotency_key)
        );

        CREATE INDEX context_preference_events_by_principal
          ON {SCHEMA}.context_preference_events (principal_id, event_number);

        CREATE TABLE {SCHEMA}.context_preference_current (
          principal_id text NOT NULL
            CHECK (principal_id ~ '^prn_[A-Za-z0-9]{{8,64}}$'),
          target_id text NOT NULL
            CHECK (target_id ~ '^[a-z]+_[A-Za-z0-9]{{8,64}}$'),
          preference_class text NOT NULL
            CHECK (preference_class IN ('alias', 'focus', 'relevance', 'source')),
          action text NOT NULL
            CHECK (action IN (
              'clear', 'confirm_alias', 'deprefer_source', 'mark_irrelevant',
              'mark_relevant', 'pin', 'prefer_source', 'remove_alias', 'unpin'
            )),
          event_id text NOT NULL
            CHECK (event_id ~ '^cpref_[A-Za-z0-9]{{8,64}}$'),
          alias text
            CHECK (alias IS NULL OR length(alias) BETWEEN 1 AND 64),
          source_id text
            CHECK (
              source_id IS NULL OR source_id ~ '^src_[A-Za-z0-9]{{8,64}}$'
            ),
          CONSTRAINT one_current_preference_per_target_class
            PRIMARY KEY (principal_id, target_id, preference_class),
          CONSTRAINT context_preference_current_cites_an_event
            FOREIGN KEY (event_id)
            REFERENCES {SCHEMA}.context_preference_events (event_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.context_preference_current")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.context_preference_events")
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
