"""Admit the unresolved-mention read capability (WP-RI-05 successor).

Revision ID: e4d7b2f9a316
Revises: d2b8f5c04e71
Create Date: 2026-08-20

One capability, `entities.unresolved_mentions`, added to the `audit_events`
capability closed set. No table, no column, no index: the queue it serves is
`entity_observations` rows that no entity claims, which `d2b8f5c04e71` already
created. What was missing was a way to ask for them.

The purpose set is untouched. `entity_read` already covers every read on this
plane and this is another read.

The literals below are written out and frozen at this revision rather than
derived from the domain enums (`D-69`): a revision that derived them would agree
with the code forever and therefore prove nothing about what the server accepted
on the day it ran.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "e4d7b2f9a316"
down_revision: str | None = "d2b8f5c04e71"
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
    "'entities.unresolved_mentions', "
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


def _restate(capability: str) -> None:
    """Replace the capability closed-set constraint on `audit_events`."""
    op.execute('ALTER TABLE knowledge.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({capability})"
    )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION)
