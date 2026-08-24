"""Admit the Phase A entity capability names and their two write purposes.

Revision ID: 823e23b6cc63
Revises: 2fe4e13fb449
Create Date: 2026-08-23

**One revision for the whole of Phase A, and that is the point of it.** Three
work packages — `WP-RI-A-02`, `WP-RI-A-03` and `WP-RI-A-04` — each added
`entities.` capabilities to the domain and each was forbidden from adding a
revision, because `knowledge.audit_events`' `capability_is_known` and
`purpose_is_known` are single closed-set CHECKs: three branches restating one
constraint would produce three heads and three conflicting restatements of the
same vocabulary, and whichever merged last would silently decide what the other
two admitted. So the twenty-two capability names and the two purposes land here,
together, once.

The twenty-two: the ten identity and identifier/alias writes and two paged child
reads (`WP-RI-A-02`), the six directed writes over assignments and typed edges
and their listing (`WP-RI-A-03`), and the observation listing, `entities.observe`
and `entities.unresolved_mentions.resolve` (`WP-RI-A-04`). The two purposes are
`entity_authoring`, which every write but one permits, and
`entity_observation_ingest`, which `entities.observe` permits and nothing else
does — the separation that keeps an ingest path from deciding an identity.

**No table is created or altered here.** Every table this vocabulary writes
landed in `9def3c2e63bb`, `b7f4d1a92c36`, `d2b8f5c04e71` and `2fe4e13fb449`.
This revision widens two closed-set CHECK constraints and nothing else, which is
what admitting a capability costs.

The four literals below are written out and frozen at this revision rather than
derived from the domain enums (`D-69`). A revision that derived them would agree
with the enum on the day it was written and silently change meaning every time
the enum grew — and a build that widened the enum without a migration passes
every test, because every test constructs its database from scratch, then fails
in the field on the first audited request against a database that already
exists. That is exactly what the three packages above were doing until this
revision: every `entities.` write they declared answered `internal_error`
against a migrated database, because `authorize` commits an audit row before the
handler runs and the stored CHECK refused the capability name.

`downgrade` restores `2fe4e13fb449`'s vocabulary exactly, so empty → head →
empty leaves no residue and a database that went up and came back down enforces
the same closed sets as one built from empty to the revision below.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "823e23b6cc63"
down_revision: str | None = "2fe4e13fb449"
branch_labels: str | None = None
depends_on: str | None = None

#: Restated rather than imported from `infrastructure.persistence.tables`, for
#: the reason the literals are written out: a revision that read the live schema
#: name would change meaning if the name ever did, and a migration has to keep
#: emitting what it emitted on the day it merged.
SCHEMA: Final = "knowledge"

_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', "
    "'entities.archive', 'entities.assignments.create', "
    "'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.context', 'entities.create', "
    "'entities.get', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.observations.list', 'entities.observe', "
    "'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', "
    "'entities.resolve', 'entities.restore', 'entities.search', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.restore', 'relationship_memory.revise', "
    "'relationship_memory.search', 'reports.begin_cycle', 'reports.commit', "
    "'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', "
    "'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'entities.context', 'entities.get', "
    "'entities.relationships', 'entities.resolve', 'entities.search', "
    "'entities.unresolved_mentions', 'goodnotes.content', 'goodnotes.propose', "
    "'goodnotes.work', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.restore', 'relationship_memory.revise', "
    "'relationship_memory.search', 'reports.begin_cycle', 'reports.commit', "
    "'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', "
    "'tasks.transition', 'tasks.update')"
)

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_observation_ingest', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'relationship_memory_authoring', "
    "'relationship_memory_read', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'relationship_memory_authoring', "
    "'relationship_memory_read', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction."""
    for name, expression in (
        ("capability_is_known", capability),
        ("purpose_is_known", purpose),
    ):
        op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "{name}"')
        op.execute(
            f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "{name}" CHECK ({expression})'
        )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
