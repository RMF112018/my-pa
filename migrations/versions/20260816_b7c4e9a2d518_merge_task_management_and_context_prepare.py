"""Merge task-management and context-prepare Alembic heads.

Local `main` carried task-management through DDL-free merge `7504585e3ca5`.
`origin/main` carried context.prepare/feedback through `c6f1a8d3e204`. Both
lineages revise `knowledge.audit_events.capability_is_known` and
`purpose_is_known`, so a pass-only merge would leave whichever parent Alembic
applied last as the stored vocabulary. This revision restates the union as
frozen literals (`D-69`) and does no other DDL.

Revision ID: b7c4e9a2d518
Revises: 7504585e3ca5, c6f1a8d3e204
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "b7c4e9a2d518"
down_revision: str | tuple[str, ...] | None = ("7504585e3ca5", "c6f1a8d3e204")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Union of `d15c0dc14d09` (task-management / commitments) and `c6f1a8d3e204`
#: (context.prepare / context.feedback), sorted.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
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
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

#: Vocabulary `c6f1a8d3e204` installed, restated rather than derived. Named
#: second in `down_revision`; restoring it undoes only this merge's ALTER.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
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

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'knowledge_read', "
    "'knowledge_search', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'context_preference', 'context_preparation', "
    "'continuity_authoring', 'document_authoring', 'document_read', "
    "'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation')"
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
