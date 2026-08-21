"""Admit the relationship-intelligence entity capabilities and their purpose.

Revision ID: c1a7e4b93d58
Revises: b7f4d1a92c36
Create Date: 2026-08-18

WP-RI-05: the five `entities.*` capabilities and the `entity_read` purpose
become admissible values of `audit_events.capability` and
`audit_events.purpose`.

**No table is created or altered here.** The entity tables landed in
`9def3c2e63bb` and `b7f4d1a92c36`; this revision widens two closed-set CHECK
constraints and nothing else, which is what admitting a capability costs.

The four literals below are written out and frozen at this revision rather than
derived from the domain enums (`D-69`). A revision that derived them would agree
with the enum on the day it was written and silently change meaning every time
the enum grew -- and a build that widened the enum without a migration passes
every test, because every test constructs its database from scratch, then fails
in the field on the first audited request against a database that already
exists.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c1a7e4b93d58"
down_revision: str | None = "b7f4d1a92c36"
branch_labels: str | None = None
depends_on: str | None = None

_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.context', 'entities.get', "
    "'entities.relationships', 'entities.resolve', 'entities.search', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', "
    "'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', "
    "'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', "
    "'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', "
    "'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_read', "
    "'goodnotes_content', 'goodnotes_proposal', 'goodnotes_work', "
    "'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation', "
    "'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', "
    "'task_read')"
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
