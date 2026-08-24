"""Admit Phase B's four capability names and its three purposes.

Revision ID: b64e29a0f7c1
Revises: a1f7d3c85e40
Create Date: 2026-08-24

**One revision for the whole of Phase B**, on exactly the argument
`823e23b6cc63` makes for Phase A. `knowledge.audit_events`' `capability_is_known`
and `purpose_is_known` are single closed-set CHECKs, and several branches
restating one constraint produce several heads and several conflicting
restatements of the same vocabulary, with whichever merged last silently deciding
what the others admitted. So `WP-RI-B-05`'s two producer capabilities and
`WP-RI-B-06`'s two identity-correction capabilities land here, together, once —
and none of the four Phase B revisions below this one touches either constraint.

The four: `entities.proposals.create` and `relationship_memory.propose`, the two
producer paths, and `entities.merge.preview` and `entities.merge`, the two
operator-only halves of the governed merge. The three purposes are
`entity_proposal`, `relationship_memory_proposal` and
`entity_identity_correction` — one per plane and one for the pair, each a purpose
of its own so that a grant issued to raise candidates cannot also author what it
proposed, and a reviewer's grant is not an identity-correction grant.

`entities.identity_history` is deliberately absent. The frozen MCP contract
assigns it to `WP-02`, and Phase B implements no later-WP surface, so a governed
merge can be performed and its lineage cannot yet be read back over MCP. That is
recorded as a carried gap rather than closed here.

**Why admitting the vocabulary is not optional and not cosmetic.**
`ApplicationService.invoke` commits an audit row *before* the handler runs, so a
capability present in the `Capability` enum and absent from this stored CHECK
answers `internal_error` against a migrated database while every from-scratch
test passes — because every from-scratch test builds its database from this same
revision. That is the failure `823e23b6cc63` was written to end, and it is why
the acceptance evidence for Phase B has to include a migrated database and not
only empty → head.

The four literals below are written out and frozen at this revision rather than
derived from `Capability` and `Purpose` (`D-69`). A database migrated to this
revision holds the vocabulary this revision describes, whatever the enums say on
the day it runs.

`downgrade` restores `823e23b6cc63`'s vocabulary exactly, so empty → head → empty
leaves no residue.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "b64e29a0f7c1"
down_revision: str | None = "a1f7d3c85e40"
branch_labels: str | None = None
depends_on: str | None = None

#: Restated rather than imported from `infrastructure.persistence.tables`, for
#: the reason the literals are written out: a revision that read the live schema
#: name would change meaning if the name ever did.
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
    "'entities.merge', 'entities.merge.preview', 'entities.observations.list', "
    "'entities.observe', 'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.unresolved_mentions', "
    "'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.content', 'goodnotes.propose', 'goodnotes.work', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.propose', "
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

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', "
    "'entity_proposal', 'entity_read', 'goodnotes_content', "
    "'goodnotes_proposal', 'goodnotes_work', 'knowledge_read', "
    "'knowledge_search', 'relationship_memory_authoring', "
    "'relationship_memory_proposal', 'relationship_memory_read', "
    "'report_authoring', 'report_read', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation', "
    "'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
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
    # No audit row is removed to make the narrower vocabulary fit. `audit_events`
    # is append-only by trigger, so a database that has recorded one Phase B
    # request refuses to come back down — loudly, which is the correct answer:
    # the row records a decision that was made, and rewriting it to fit an older
    # vocabulary would be falsifying the audit to satisfy a migration.
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
