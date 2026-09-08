"""Admit the Constraint Management read vocabulary to the audited closed sets.

`PC-CM-IMP-WP04`. `authorize()` writes an `audit_events` row inside the request's
own transaction on every invocation, so `capability_is_known` and
`purpose_is_known` are not descriptions of the enums -- they are the gates the
first `constraints.read` request in the field would meet. A member added to
`domain.identity.operation.Capability` with no forward `ALTER` leaves every test
green, because every test builds its database from scratch, and is refused by the
stored constraint the moment a real deployment serves it. The `ALTER` is
therefore written with the members rather than after them, the order
`3c8f1e2a5b74` established and every widening since has repeated.

**Six capabilities and one purpose, and the arithmetic of that is the design.**
The plane's authoring and its SharePoint synchronisation are not admitted here,
so no value this revision installs can carry an audit row for a Constraint write:
the vocabulary a later package needs is a later revision's, written with the
members that need it.

`constraint_categories.list` carries an underscore in its first segment where
every other value in this set does not. A Category is the Project's own
classification scheme rather than a record filed under one -- readable when the
Register is empty, needing no Project calendar -- and folding it under the
`constraints.` prefix would make a grant issued to read the scheme look like one
issued to read the records.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states:
no Alembic revision may derive a closed-set constraint from a domain enum. The
`BEFORE` texts are byte-for-byte copies of `a1c9e4b72f80`'s own `AT` texts, so a
database downgraded past this revision holds the vocabulary that revision
describes rather than whatever the domain says on the day the downgrade runs.
Both pairs are checked against the domain at head by
`tests/schema/test_constraint_read_capability_migration.py`.

This revision creates no table, adds no column, names no Constraint table, reads
nothing from the migrated corpus, and touches the shared declaration module not
at all.

Revision ID: c5b71e0a8d43
Revises: a1c9e4b72f80
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c5b71e0a8d43"
down_revision: str | None = "a1c9e4b72f80"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: Frozen copy of `a1c9e4b72f80._CAPABILITIES_AT_THIS_REVISION`.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', "
    "'entities.get', 'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', "
    "'entities.profile', 'entities.proposals.create', 'entities.relationships', "
    "'entities.relationships.create', 'entities.relationships.end', "
    "'entities.relationships.revise', 'entities.resolve', 'entities.restore', "
    "'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.complete', 'goodnotes.content', "
    "'goodnotes.correct', 'goodnotes.notebooks.list', 'goodnotes.pages.list', "
    "'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', 'native_sources.retry', "
    "'native_sources.status', 'native_sources.sync', 'relationship_memory.archive', "
    "'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', "
    "'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status', 'tasks.bulk_confirm', "
    "'tasks.bulk_preview', 'tasks.create', 'tasks.history', 'tasks.list', "
    "'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)

#: The same set with the six Constraint Management read names, sorted, which is
#: the order the declarative helper produces so the two texts compare directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', 'capture.revise', 'capture.search', "
    "'commitments.close', 'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', 'commitments.waiting_on', "
    "'constraint_categories.list', 'constraints.history', 'constraints.list', "
    "'constraints.overview', 'constraints.read', 'constraints.search', 'context.feedback', "
    "'context.prepare', 'continuity.projects', 'continuity.projects.create', "
    "'continuity.pulse', 'continuity.situations', 'continuity.situations.create', "
    "'continuity.tasks.create', 'documents.archive', 'documents.create', 'documents.list', "
    "'documents.read', 'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', "
    "'entities.affiliations.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.communication.add', "
    "'entities.communication.list', 'entities.communication.retire', "
    "'entities.communication.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.graph', 'entities.identifiers.bind', 'entities.identifiers.list', "
    "'entities.identifiers.retire', 'entities.identifiers.supersede', "
    "'entities.identity_history', 'entities.merge', 'entities.merge.preview', "
    "'entities.names.add', 'entities.names.list', 'entities.names.retire', "
    "'entities.names.supersede', 'entities.observations.list', 'entities.observe', "
    "'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', "
    "'entities.update', 'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', "
    "'goodnotes.notebooks.list', 'goodnotes.pages.list', 'goodnotes.propose', "
    "'goodnotes.pull', 'goodnotes.read', 'goodnotes.runs.list', 'goodnotes.search', "
    "'goodnotes.status', 'goodnotes.work', 'gsqs.start', 'gsqs.status', 'knowledge.coverage', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', 'relationship_memory.list', "
    "'relationship_memory.propose', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', 'reports.begin_cycle', "
    "'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', "
    "'tasks.update')"
)

#: Frozen copy of `a1c9e4b72f80._PURPOSES_AT_THIS_REVISION`.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', "
    "'canvas_workspace_read', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', "
    "'goodnotes_proposal', 'goodnotes_pull', "
    "'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', "
    "'relationship_memory_read', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)

#: The same set with `constraint_read`, and with no authoring or synchronisation
#: purpose beside it: this build serves Constraint reads and no Constraint write.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', "
    "'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', "
    "'constraint_read', 'content_extraction', 'context_preference', 'context_preparation', "
    "'continuity_authoring', 'document_authoring', 'document_read', 'entity_authoring', "
    "'entity_identity_correction', 'entity_observation_ingest', 'entity_proposal', "
    "'entity_read', 'goodnotes_browse', 'goodnotes_content', 'goodnotes_correction', "
    "'goodnotes_proposal', 'goodnotes_pull', 'goodnotes_pull_observation', 'goodnotes_read', "
    "'goodnotes_work', 'gsqs_b0_execution', 'gsqs_b0_observation', 'knowledge_read', "
    "'knowledge_search', 'relationship_memory_authoring', 'relationship_memory_proposal', "
    "'relationship_memory_read', 'report_authoring', 'report_read', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation', 'task_authoring', "
    "'task_read')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction.

    Dropped and recreated rather than altered in place: PostgreSQL has no "alter
    the expression of a check constraint", and doing it in two statements inside
    the revision's own transaction means there is no instant at which either
    column is unconstrained that another session could observe.
    """
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
