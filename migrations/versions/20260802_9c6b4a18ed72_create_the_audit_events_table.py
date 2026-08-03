"""create the audit events table

Adds one table to the existing `knowledge` schema: `audit_events`. It creates no
schema, touches no table an earlier revision created, and reads nothing from the
migrated legacy corpus.

This is the durable store `D-34` assigns to WP-4B. WP-4A defined `AuditSink` and
calls it on every authorization decision, but it had no migration authority, so
until this revision the only implementations were test doubles and a process
that authorized left no durable trace at all.

The table is named explicitly rather than taken from the shared `MetaData`, for
the reason `8b3f5c17d904` states: `my_pa.infrastructure.persistence.tables`
declares every table in this schema in one module, so an unqualified
`create_all` here would also create the eight that earlier revisions own — and
would then start creating whatever a later revision declares, which would make
this file's meaning depend on code written after it.
`tests/schema/test_extraction_schema_migration.py` asserts that each revision
emits exactly the tables it names.

The downgrade drops only `audit_events`. It leaves the `knowledge` schema in
place because this revision did not create it. Note what that downgrade is: it
destroys the audit trail. It exists because a migration must be reversible
against a disposable database, and it is the one operation in this schema that
an operator should never run against a database holding real decisions.

**Standing rule: no Alembic revision may derive a closed-set constraint from a
domain enum.** All four closed-set constraints this revision emits —
`capability_is_known`, `purpose_is_known`, `audit_outcome_is_known` and
`denial_reason_is_known` — are written out below as frozen literals. They used
to be `_one_of(...)` calls read off the shared declaration. That is a
retroactive-DDL defect of the same class as `D-48`, and it was measured rather
than argued: with a ninth `Capability` member present, a disposable database
stopped at *this already-merged revision* received
`capability IN (…, 'zzprobe.create')` where the baseline received the historical
eight, and the independent reviewer reproduced the identical result for
`denial_reason` with a planted `DenialReason` member. A revision whose meaning
changes when a later one is written is not a revision, and the harm is not
hypothetical — a build that widens the enum without a migration passes every
test, because every test constructs its database from scratch, and then fails in
the field on the first audited request against a database that already exists.

The first pass at this freeze covered `capability` and `purpose` only, because
those are the two enums WP-6 changed. That was the defect this rule exists to
forbid, written into the file that states the rule: `outcome` and `denial_reason`
are the same mechanism on the same table in the same revision, and a rule
observed on half a file is a rule nothing enforces. All four are frozen, and
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` is the
control that now enforces the rule mechanically across every revision rather than
leaving it as prose here.

The freeze is **meaning-preserving**. After it this revision emits DDL
byte-identical to what it emitted on the day it merged, so no deployed schema
moves and any database already at this revision is already in the post-edit
state. This is checked at the whole-schema level rather than constraint by
constraint: a dump of every schema, table, column, constraint, index, trigger,
routine and view of a database stopped at this revision was taken on `main` and
on this branch and compared for byte identity, because a per-constraint
comparison cannot see a change the freeze made somewhere else.

Widening happens forward, by an explicit `ALTER` in the revision that needs the
new vocabulary — `1a4c9e77b2d5` is the first — which carries its own frozen
literals for the same reason. What the freeze costs is the enum-to-CHECK
coupling that used to guarantee the domain and the database could not drift;
that guarantee is replaced by a checked claim, in
`tests/schema/test_capture_schema_migration.py`, which asserts that head admits
exactly the domain's declaration for **all four** of these constraints —
`Capability`, `Purpose`, `AuditOutcome` and `DenialReason` — and not only for the
two WP-6 widened. Checking two of four would have left the coupling replaced by
nothing on the other two. The precedent for replacing a copy with a checked
restatement is `tables.py:_IDENTIFIER_SUFFIX`.

Revision ID: 9c6b4a18ed72
Revises: 8b3f5c17d904
Created: 2026-08-02 14:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import SCHEMA, audit_events

revision: str = "9c6b4a18ed72"
down_revision: str | None = "8b3f5c17d904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The vocabulary this revision emitted on the day it merged, written out. The
#: order is the order `tables.py:_literals` produces — sorted — so the emitted
#: text is identical to the derived text it replaces, not merely equivalent.
_HISTORICAL_CAPABILITY_CHECK: Final = (
    "capability IN ('capabilities.get', 'knowledge.read', 'knowledge.search', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status')"
)
_HISTORICAL_PURPOSE_CHECK: Final = (
    "purpose IN ('bounded_enrollment', 'content_extraction', 'knowledge_read', "
    "'knowledge_search', 'security_validation', 'source_inspection', "
    "'status_observation')"
)
_HISTORICAL_OUTCOME_CHECK: Final = "outcome IN ('allowed', 'denied', 'failed')"
_HISTORICAL_DENIAL_REASON_CHECK: Final = (
    "denial_reason IN ('destination_not_eligible', 'operator_required', "
    "'principal_may_not_hold_authority', 'principal_not_authenticated', "
    "'purpose_not_permitted_for_capability', 'scope_not_authorized')"
)

#: Every constraint on this table that was derived from a domain enum, now
#: frozen. All four, not the two WP-6 happened to widen: `AuditOutcome` and
#: `DenialReason` carry the identical hazard on the same table in this same
#: revision, and freezing the two that moved while leaving the two that did not
#: is the "half a fix is a live bug" failure applied to the file that states the
#: rule against it. `AuditOutcome` and `DenialReason` are unchanged since this
#: revision merged, so writing their historical text out is meaning-preserving by
#: inspection as well as by measurement.
_FROZEN: Final[dict[str, str]] = {
    "capability_is_known": _HISTORICAL_CAPABILITY_CHECK,
    "purpose_is_known": _HISTORICAL_PURPOSE_CHECK,
    "audit_outcome_is_known": _HISTORICAL_OUTCOME_CHECK,
    "denial_reason_is_known": _HISTORICAL_DENIAL_REASON_CHECK,
}


def _historical_audit_events() -> Table:
    """`audit_events` as this revision emitted it, with its four checks frozen.

    A copy into a throwaway `MetaData` rather than a second hand-written
    declaration. Everything except the two constraints stays declaration-driven,
    which is the pattern `tables.py` states and `8b3f5c17d904` relies on; a
    duplicated column list here would be a second statement of the table and
    would drift from the first in a way nothing checks. What is replaced is
    exactly the part that must not change when a later package adds a member.
    """
    table = audit_events.to_metadata(MetaData(schema=SCHEMA))
    for constraint in [candidate for candidate in table.constraints if candidate.name in _FROZEN]:
        table.constraints.discard(constraint)
    for name, expression in _FROZEN.items():
        table.append_constraint(CheckConstraint(expression, name=name))
    return table


def upgrade() -> None:
    table = _historical_audit_events()
    table.metadata.create_all(op.get_bind(), tables=[table])


def downgrade() -> None:
    table = _historical_audit_events()
    table.metadata.drop_all(op.get_bind(), tables=[table])
