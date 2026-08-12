"""Admit `knowledge.reveal` to the audited capability vocabulary.

`authorize()` writes an audit row in the request's own transaction on every
invocation, so `audit_events.capability_is_known` is not a description of the
capability set — it is the gate the first `knowledge.reveal` request in the field
would meet. A member added to `domain.identity.operation.Capability` with no
forward `ALTER` leaves every test green, because every test builds its database
from scratch, and is refused by the stored constraint the moment a real
deployment serves the capability. The `ALTER` is therefore written with the
member rather than after it, which is the order `3c8f1e2a5b74` established and
`9d5e2f7b4c61` repeated.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states
and `3c8f1e2a5b74` restates: no Alembic revision may derive a closed-set
constraint from a domain enum. The twenty-seven names are written out here, and
the twenty-six the revision below denotes are written out beside them, so a
database downgraded past this revision holds the vocabulary that revision
describes rather than whatever the domain says on the day the downgrade runs.

**No purpose is widened, and that is a decision rather than an omission.**
`knowledge.reveal` is permitted under `capture_review`, which
`domain/identity/purpose.py` already admits for `capture.read`, `capture.list`,
`capture.search` and `review.list`. Reveal reads exactly the rows those four
already return to the same Principal — captures, versions, spans, proposals,
review cases, decisions, assertions and receipts — and returns no capture text at
all, so the reuse widens no grant. That is the same test `D-91` applied to
`capture.search` and reached the same answer; `review.decide` reached the
opposite one because promotion is an escalation, and reveal promotes nothing.

This revision creates no table, reads nothing from the migrated corpus, and
touches the shared declaration module not at all, so it emits no closed set an
enum could reach.

Revision ID: 5e2c7b0a94f6
Revises: 4f1a8b6d92e3
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "5e2c7b0a94f6"
down_revision: str | None = "4f1a8b6d92e3"
branch_labels: str | None = None
depends_on: str | None = None

#: The capability vocabulary as of this revision: the sixteen public names and
#: the eleven native-source names, sorted, which is the order the declarative
#: helper produces so the two texts can be compared directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: What the revision below denotes, restated rather than derived.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', 'native_sources.pause', "
    "'native_sources.preflight', 'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'review.decide', 'review.list', 'sources.enroll', 'sources.fetch', "
    "'sources.list', 'sources.metadata', 'sources.status')"
)


def _replace(expression: str) -> None:
    """Drop and recreate the constraint inside this revision's own transaction.

    PostgreSQL has no "alter the expression of a check constraint", and doing it
    in two statements inside one transaction means there is no instant at which
    the column is unconstrained that another session could observe.
    """
    op.execute('ALTER TABLE knowledge.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        'ALTER TABLE knowledge.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({expression})"
    )


def upgrade() -> None:
    _replace(_CAPABILITIES_AT_THIS_REVISION)


def downgrade() -> None:
    _replace(_CAPABILITIES_BEFORE_THIS_REVISION)
