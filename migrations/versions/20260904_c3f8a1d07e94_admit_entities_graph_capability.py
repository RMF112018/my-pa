"""Admit `entities.graph` on `audit_events.capability_is_known`.

Revision ID: c3f8a1d07e94
Revises: b8e4d1a6c073
Create Date: 2026-09-04

`authorize` commits an `audit_events` row before the handler runs, and
`capability_is_known` is a closed CHECK. Until this revision the stored
vocabulary held one hundred and thirty-five names while the domain declared
`entities.graph`, so against a migrated database that capability would answer
`internal_error` after authorization and before any handler.

**Only the capability CHECK is widened.** `entities.graph` is an `entity_read`.
It writes no mutation-ledger row and accepts no proposal family, so
`a_mutated_record_family_is_known` and `an_accepted_proposal_record_family_is_known`
are unchanged.

**`purpose_is_known` is deliberately NOT widened.** The read carries
`entity_read`, admitted since `823e23b6cc63`.

**The literals below are frozen, not derived (`D-69`).** A revision that
imported `Capability` would agree with the enum on the day it was written and
silently change meaning every time the enum grew.
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces that rule by reading `Table` objects; this revision imports
`alembic.op` and nothing else.

The stored capability vocabulary holds one hundred and thirty-six values where
the live `Capability` enum holds one hundred and twenty-five, because the
stored set still admits the eleven retired `native_sources.*` names.

`downgrade` restores the vocabulary `b8e4d1a6c073` left, which is the same
capability CHECK `16f05c46b8c3` installed: `b8e4d1a6c073` backfills display
names and widens no closed set.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c3f8a1d07e94"
down_revision: str | None = "b8e4d1a6c073"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', 'entities.addresses.list', "
    "'entities.addresses.retire', 'entities.addresses.revise', 'entities.affiliations.create', "
    "'entities.affiliations.end', 'entities.affiliations.revise', 'entities.aliases.add', "
    "'entities.aliases.list', 'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.identifiers.bind', 'entities.identifiers.list', 'entities.identifiers.retire', "
    "'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', "
    "'entities.merge.preview', 'entities.names.add', 'entities.names.list', "
    "'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', "
    "'entities.observe', 'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', 'gsqs.start', 'gsqs.status', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', "
    "'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', "
    "'tasks.update')"
)

_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', 'entities.addresses.list', "
    "'entities.addresses.retire', 'entities.addresses.revise', 'entities.affiliations.create', "
    "'entities.affiliations.end', 'entities.affiliations.revise', 'entities.aliases.add', "
    "'entities.aliases.list', 'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', 'entities.assignments.end', "
    "'entities.assignments.list', 'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', "
    "'entities.identifiers.bind', 'entities.identifiers.list', 'entities.identifiers.retire', "
    "'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', "
    "'entities.merge.preview', 'entities.names.add', 'entities.names.list', "
    "'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', "
    "'entities.observe', 'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', 'gsqs.start', 'gsqs.status', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', "
    "'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', "
    "'tasks.update')"
)


def _restate(capability: str) -> None:
    op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({capability})"
    )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION)
