"""Admit `context.prepare` and `context_preparation` to the audited vocabulary.

Revision ID: 8a1c4e7b2d90
Revises: 7c2e9b4a1d80
Create Date: 2026-08-15

WP-KC-05. The live enums already hold these names (WP-KC-01); this revision is
the forward `ALTER` that lets `authorize()` persist an audit row for them.
Rollback of the capability is revoke (AC-KC-037), not a vocabulary delete that
would leave stored audit rows unnameable — the downgrade still restores the
prior closed set because that is how this chain records historical vocabulary.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "8a1c4e7b2d90"
down_revision: str | None = "7c2e9b4a1d80"
branch_labels: str | None = None
depends_on: str | None = None

#: The capability vocabulary as of this revision: what `7c2e9b4a1d80` installed,
#: plus `context.prepare`, sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
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

#: What `7c2e9b4a1d80` installed, restated rather than derived.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', "
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

#: The purpose vocabulary as of this revision: thirteen prior names plus
#: `context_preparation`, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation')"
)

#: What `7c2e9b4a1d80` installed, restated rather than derived.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'continuity_authoring', 'document_authoring', "
    "'document_read', 'knowledge_read', 'knowledge_search', "
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


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
