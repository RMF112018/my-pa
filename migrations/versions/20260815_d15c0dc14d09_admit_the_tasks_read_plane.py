"""Admit the `tasks.` read plane to the audited capability and purpose vocabularies.

WP-TM-03. `authorize()` writes an audit row in the request's own transaction on
every invocation, so `audit_events.capability_is_known` is not a description of
the capability set — it is the gate the first `tasks.read` request in the field
would meet. A member added to `domain.identity.operation.Capability` with no
forward `ALTER` leaves every test green, because every test builds its database
from scratch, and is refused by the stored constraint the moment a real
deployment serves the capability. The `ALTER` is therefore written with the
members rather than after them, which is the order `3c8f1e2a5b74` established and
`5e2c7b0a94f6`, `8f2b6c4d1a37`, `2d9f4a7c1e58` and `6b3d9a2f8c14` repeated.

**Four capabilities, one purpose.** `tasks.read`, `tasks.list`, `tasks.search`
and `tasks.history` are WP-TM-03's whole surface — the query/read plane over
WP-TM-01's task-management foundation, with no mutation capability admitted
here. All four share the single `task_read` purpose `domain/identity/purpose.py`
declares: a read is a read regardless of which of the four shapes it takes, and
`domain.policy.decision._SCOPELESS` already places all four capabilities outside
the scope matrix, exactly as the capture-plane reads are — a task belongs to no
enrollment for a scope to bind to.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states
and every widening revision since has repeated: no Alembic revision may derive a
closed-set constraint from a domain enum. The vocabularies this revision installs
are written out here, and the ones the revision below denotes are written out
beside them, so a database downgraded past this revision holds the vocabulary
that revision describes rather than whatever the domain says on the day the
downgrade runs. Both pairs are checked against the domain at head by
`tests/schema/test_task_read_capability_migration.py`.

This revision creates no table, adds no column, reads nothing from the migrated
corpus, and touches the shared declaration module not at all, so it emits no
closed set an enum could reach.

Revision ID: d15c0dc14d09
Revises: 3d7a2a3e8277
Create Date: 2026-08-15
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "d15c0dc14d09"
down_revision: str | None = "3d7a2a3e8277"
branch_labels: str | None = None
depends_on: str | None = None

#: The capability vocabulary as of this revision: the names `6b3d9a2f8c14`
#: left on this branch, plus the task/commitment names this TM lineage admits,
#: sorted. Continuity-authoring create names belong to sibling `7c2e9b4a1d80`,
#: not to parent `3d7a2a3e8277`, and must not appear here.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'commitments.close', "
    "'commitments.create', 'commitments.list', 'commitments.read', "
    "'commitments.waiting_on', 'continuity.projects', "
    "'continuity.pulse', 'continuity.situations', "
    "'documents.archive', 'documents.create', "
    "'documents.list', 'documents.read', 'documents.restore', 'documents.revise', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status', "
    "'tasks.bulk_confirm', 'tasks.bulk_preview', 'tasks.create', 'tasks.history', "
    "'tasks.list', 'tasks.read', 'tasks.search', 'tasks.transition', 'tasks.update')"
)

#: What parent `3d7a2a3e8277` denotes: the `6b3d9a2f8c14` vocabulary, because
#: neither `4f6a9c2d8e17` nor `3d7a2a3e8277` restates these CHECKs. Sibling
#: `7c2e9b4a1d80` is not an ancestor.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'continuity.projects', "
    "'continuity.pulse', 'continuity.situations', "
    "'documents.archive', 'documents.create', 'documents.list', "
    "'documents.read', 'documents.restore', 'documents.revise', "
    "'knowledge.coverage', 'knowledge.read', 'knowledge.reveal', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: The purpose vocabulary as of this revision: the names `6b3d9a2f8c14` left,
#: the one the task-read plane declares, and the three the task-management plane
#: (WP-TM-04 and WP-TM-05) declares, sorted. `continuity_authoring` is the
#: sibling branch's purpose, not this parent's.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'document_authoring', 'document_read', "
    "'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation', "
    "'task_authoring', 'task_read')"
)

#: What parent `3d7a2a3e8277` denotes, restated rather than derived.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'document_authoring', "
    "'document_read', 'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction.

    Dropped and recreated rather than altered in place: PostgreSQL has no "alter
    the expression of a check constraint", and doing it in two statements inside
    the revision's own transaction means there is no instant at which either
    column is unconstrained that another session could observe. `1a4c9e77b2d5`,
    `3c8f1e2a5b74` and `6b3d9a2f8c14` do the same for the same two.
    """
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
