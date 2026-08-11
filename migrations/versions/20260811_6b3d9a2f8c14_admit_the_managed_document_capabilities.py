"""Admit the `documents.` plane to the audited capability and purpose vocabularies.

WP-28. `authorize()` writes an audit row in the request's own transaction on
every invocation, so `audit_events.capability_is_known` is not a description of
the capability set — it is the gate the first `documents.create` request in the
field would meet. A member added to `domain.identity.operation.Capability` with
no forward `ALTER` leaves every test green, because every test builds its
database from scratch, and is refused by the stored constraint the moment a real
deployment serves the capability. The `ALTER` is therefore written with the
members rather than after them, which is the order `3c8f1e2a5b74` established and
`5e2c7b0a94f6`, `8f2b6c4d1a37` and `2d9f4a7c1e58` repeated.

**Why this revision is the precondition for the rest of WP-28.** WP-27 shipped
the managed-document write plane deliberately seatless: `ManagedDocumentService`
took a resolved Principal from a composition root, and a managed write — or a
managed *refusal* — left no `knowledge.audit_events` row anywhere. That was
bounded because nothing outside the process could reach the plane. WP-28 exposes
it over a transport, which removes the bound, so the seat and its audit land
before the transport does rather than beside it.

**Both closed sets move, and the purposes are new rather than reused.**
`document_authoring` and `document_read` are declared in
`domain/identity/purpose.py` with the argument for why neither the capture pair
nor the knowledge pair could carry a managed document without widening a grant
across custody planes. Two constraints therefore move here, in the shape
`3c8f1e2a5b74` set for moving both at once.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states
and every widening revision since has repeated: no Alembic revision may derive a
closed-set constraint from a domain enum. The vocabularies this revision installs
are written out here, and the ones the revision below denotes are written out
beside them, so a database downgraded past this revision holds the vocabulary
that revision describes rather than whatever the domain says on the day the
downgrade runs. Both pairs are checked against the domain at head by
`tests/schema/test_managed_document_capability_migration.py`.

This revision creates no table, adds no column, reads nothing from the migrated
corpus, and touches the shared declaration module not at all, so it emits no
closed set an enum could reach.

Revision ID: 6b3d9a2f8c14
Revises: 4c7b2e91d8a5
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "6b3d9a2f8c14"
down_revision: str | None = "4c7b2e91d8a5"
branch_labels: str | None = None
depends_on: str | None = None

#: The capability vocabulary as of this revision: the twenty-six public names and
#: the eleven native-source names, sorted, which is the order the declarative
#: helper produces so the two texts can be compared directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'continuity.projects', "
    "'continuity.pulse', 'continuity.situations', 'documents.archive', "
    "'documents.create', 'documents.list', 'documents.read', 'documents.restore', "
    "'documents.revise', 'knowledge.coverage', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', "
    "'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: What the revision below denotes, restated rather than derived.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'continuity.projects', "
    "'continuity.pulse', 'continuity.situations', 'knowledge.coverage', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: The purpose vocabulary as of this revision: the ten `3c8f1e2a5b74` left and the
#: two the managed-document plane declares, sorted.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'document_authoring', 'document_read', "
    "'knowledge_read', 'knowledge_search', 'review_disposition', "
    "'security_validation', 'source_inspection', 'status_observation')"
)

#: What the revision below denotes, restated rather than derived.
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation')"
)


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction.

    Dropped and recreated rather than altered in place: PostgreSQL has no "alter
    the expression of a check constraint", and doing it in two statements inside
    the revision's own transaction means there is no instant at which either
    column is unconstrained that another session could observe. `1a4c9e77b2d5`
    and `3c8f1e2a5b74` do the same for the same two.
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
