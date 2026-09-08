"""Admit the Constraint Management authoring vocabulary to the audited closed sets.

`PC-CM-IMP-WP07`. `authorize()` writes an `audit_events` row inside the request's
own transaction on every invocation, allowed or denied, so `capability_is_known`
and `purpose_is_known` are not descriptions of the enums -- they are the gates the
first `constraints.publish` request in the field would meet. A member added to
`domain.identity.operation.Capability` with no forward `ALTER` leaves every test
green, because every test builds its database from scratch, and is refused by the
stored constraint the moment a real deployment serves it. The `ALTER` is
therefore written with the members rather than after them, the order
`3c8f1e2a5b74` established and every widening since has repeated.

**Twelve capabilities and one purpose, and the arithmetic of that is the design.**
The six Constraint reads and the `constraint_read` purpose were admitted by
`c5b71e0a8d43` and are untouched here; what this revision adds is the authoring
half, so an audit row can be written for a Constraint write. The plane's
SharePoint synchronisation is still not admitted: no `constraint_sync.*`
capability and neither sync purpose appears below, because no such capability
exists in this build and the vocabulary a later package needs is a later
revision's, written with the members that need it.

`constraint_categories.create`, `.update`, `.deactivate` and `.reorder` carry an
underscore in their first segment where the `constraints.` values do not, for the
reason `c5b71e0a8d43` states about `constraint_categories.list`: a Category is the
Project's own classification scheme rather than a record filed under one, and
folding it under the `constraints.` prefix would make a grant issued to manage the
scheme look like one issued to change the records.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states:
no Alembic revision may derive a closed-set constraint from a domain enum. The
`BEFORE` texts are byte-for-byte copies of `c5b71e0a8d43`'s own `AT` texts, so a
database downgraded past this revision holds the vocabulary that revision
describes rather than whatever the domain says on the day the downgrade runs.
Both pairs are checked against the domain at head by
`tests/schema/test_constraint_authoring_capability_migration.py`.

This revision creates no table, adds no column, names no Constraint table, reads
nothing from the migrated corpus, and touches the shared declaration module not
at all.

Revision ID: f7a2c9d51e64
Revises: 4e9a1c7b2d60
Repointed: written against `c5b71e0a8d43`, then reparented onto `4e9a1c7b2d60`
when the auth-identity revision landed on the same parent during review. The
BEFORE literals below are still copies of `c5b71e0a8d43`'s AT texts, because
`4e9a1c7b2d60` states neither audited set and so did not move the vocabulary.
Create Date: 2026-09-07
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "f7a2c9d51e64"
down_revision: str | None = "4e9a1c7b2d60"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: Frozen copy of `c5b71e0a8d43._CAPABILITIES_AT_THIS_REVISION`.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
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

#: The same set with the twelve Constraint Management authoring names, sorted,
#: which is the order the declarative helper produces so the two texts compare
#: directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('canvas.workspace.get', 'canvas.workspace.put', 'capabilities.get', "
    "'capture.create', 'capture.list', 'capture.read', 'capture.revise', 'capture.search', "
    "'commitments.close', 'commitments.create', 'commitments.history', 'commitments.list', "
    "'commitments.read', 'commitments.search', 'commitments.update', 'commitments.waiting_on', "
    "'constraint_categories.create', 'constraint_categories.deactivate', "
    "'constraint_categories.list', 'constraint_categories.reorder', "
    "'constraint_categories.update', 'constraints.close', 'constraints.close_follow_up', "
    "'constraints.create', 'constraints.history', 'constraints.list', 'constraints.overview', "
    "'constraints.publish', 'constraints.read', 'constraints.reopen', 'constraints.search', "
    "'constraints.transition', 'constraints.update', 'constraints.void', 'context.feedback', "
    "'context.prepare', 'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.addresses.add', "
    "'entities.addresses.list', 'entities.addresses.retire', 'entities.addresses.revise', "
    "'entities.affiliations.create', 'entities.affiliations.end', 'entities.affiliations.revise', "
    "'entities.aliases.add', 'entities.aliases.list', 'entities.aliases.retire', "
    "'entities.aliases.supersede', 'entities.archive', 'entities.assignments.create', "
    "'entities.assignments.end', 'entities.assignments.list', 'entities.assignments.revise', "
    "'entities.communication.add', 'entities.communication.list', "
    "'entities.communication.retire', 'entities.communication.revise', 'entities.context', "
    "'entities.create', 'entities.get', 'entities.graph', 'entities.identifiers.bind', "
    "'entities.identifiers.list', 'entities.identifiers.retire', "
    "'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', "
    "'entities.merge.preview', 'entities.names.add', 'entities.names.list', "
    "'entities.names.retire', 'entities.names.supersede', 'entities.observations.list', "
    "'entities.observe', 'entities.participations.create', 'entities.participations.end', "
    "'entities.participations.list', 'entities.participations.revise', 'entities.profile', "
    "'entities.proposals.create', 'entities.relationships', 'entities.relationships.create', "
    "'entities.relationships.end', 'entities.relationships.revise', 'entities.resolve', "
    "'entities.restore', 'entities.search', 'entities.split', 'entities.split.preview', "
    "'entities.unresolved_mentions', 'entities.unresolved_mentions.resolve', 'entities.update', "
    "'goodnotes.complete', 'goodnotes.content', 'goodnotes.correct', 'goodnotes.notebooks.list', "
    "'goodnotes.pages.list', 'goodnotes.propose', 'goodnotes.pull', 'goodnotes.read', "
    "'goodnotes.runs.list', 'goodnotes.search', 'goodnotes.status', 'goodnotes.work', "
    "'gsqs.start', 'gsqs.status', 'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', 'relationship_memory.get', "
    "'relationship_memory.history', 'relationship_memory.list', 'relationship_memory.propose', "
    "'relationship_memory.restore', 'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', 'reports.list', 'reports.read', "
    "'reports.record_run_state', 'reports.resolve_set', 'reports.search', 'review.decide', "
    "'review.list', 'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', "
    "'tasks.history', 'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', "
    "'tasks.update')"
)

#: Frozen copy of `c5b71e0a8d43._PURPOSES_AT_THIS_REVISION`.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
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

#: The same set with `constraint_authoring`, and with no synchronisation purpose
#: beside it: this build serves Constraint reads and Constraint writes, and no
#: Constraint synchronisation.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'canvas_workspace_authoring', 'canvas_workspace_read', "
    "'capture_authoring', 'capture_review', 'commitment_authoring', 'commitment_read', "
    "'constraint_authoring', 'constraint_read', 'content_extraction', 'context_preference', "
    "'context_preparation', 'continuity_authoring', 'document_authoring', 'document_read', "
    "'entity_authoring', 'entity_identity_correction', 'entity_observation_ingest', "
    "'entity_proposal', 'entity_read', 'goodnotes_browse', 'goodnotes_content', "
    "'goodnotes_correction', 'goodnotes_proposal', 'goodnotes_pull', "
    "'goodnotes_pull_observation', 'goodnotes_read', 'goodnotes_work', 'gsqs_b0_execution', "
    "'gsqs_b0_observation', 'knowledge_read', 'knowledge_search', "
    "'relationship_memory_authoring', 'relationship_memory_proposal', 'relationship_memory_read', "
    "'report_authoring', 'report_read', 'review_disposition', 'security_validation', "
    "'source_inspection', 'status_observation', 'task_authoring', 'task_read')"
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
