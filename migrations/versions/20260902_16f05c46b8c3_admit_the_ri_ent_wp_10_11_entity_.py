"""Admit the RI-ENT-WP-10/11 entity capability names and their five record families.

Revision ID: 16f05c46b8c3
Revises: c99cd8ed8d1c
Create Date: 2026-09-02

**One revision for both work packages, and that is the point of it.**
`RI-ENT-WP-10` publishes five paged entity reads and `RI-ENT-WP-11` publishes
fifteen entity writes, and each was forbidden from adding a revision of its own,
because `audit_events`' `capability_is_known`, `entity_mutation_events`'
`a_mutated_record_family_is_known` and `entity_proposals`'
`an_accepted_proposal_record_family_is_known` are single closed-set CHECKs:
two branches restating one constraint would produce two Alembic heads and two
conflicting restatements of the same vocabulary, and whichever merged last would
silently decide what the other admitted. So the twenty capability names and the
five record families land here, together, once.

**What this closes.** `authorize` commits an `audit_events` row *before* the
handler runs, and `capability_is_known` is a closed CHECK. Until this revision
the stored vocabulary held one hundred and fifteen names while the domain
declared twenty capability names it had never heard of, so against a *migrated*
database every one of those twenty answered `internal_error` after
authorization and before any handler — the least informative answer this build
can give. Every test in the repository passed anyway, because every test builds
its database from scratch. That is the exact gap this revision exists to close,
and it is the last blocking item of both work packages.

**The three constraints, and what each moves from and to.**

1. `audit_events.capability_is_known`, one hundred and fifteen values to one
   hundred and thirty-five. The twenty added are `RI-ENT-WP-10`'s five reads
   (`entities.profile`, `entities.names.list`, `entities.addresses.list`,
   `entities.communication.list`, `entities.participations.list`) and
   `RI-ENT-WP-11`'s fifteen writes over names, addresses, communication methods,
   project participations and person-organization affiliations.
2. `entity_mutation_events.a_mutated_record_family_is_known`, six values to
   eleven. The five added are `address`, `communication_method`, `name`,
   `person_organization_affiliation` and `project_participation` — the families
   `RI-ENT-WP-11`'s writes record in the mutation ledger.
3. `entity_proposals.an_accepted_proposal_record_family_is_known`, six values to
   eleven, the same five added. **This third widening has no behavioural
   effect, and is here for metadata parity rather than for a new capability.**
   `infrastructure/persistence/tables.py` builds it from the same
   `_one_of(..., MutationRecordFamily, ...)` helper that builds the mutation
   ledger's, so a revision that widened the ledger and left the proposal
   constraint narrow would leave the declared metadata and the migrated DDL
   disagreeing about one column — a difference that shows up as a from-scratch
   database and a migrated one enforcing different rules. Nothing becomes
   promotable by it: `EntityProposalKind` is unchanged, and
   `application/entity_promotion.py`'s promotion table maps only the fifteen
   existing proposal kinds to the six pre-existing families, so no proposal can
   ever carry one of the five new values in `accepted_record_type`.

**`purpose_is_known` is deliberately NOT widened.** `RI-ENT-WP-10` and
`RI-ENT-WP-11` add no `Purpose` member: their reads carry `entity_read` and
their writes carry `entity_authoring`, both admitted since `823e23b6cc63`. Its
absence below is a decision, not an omission.

**No table is created or altered here, and no row is touched.** `upgrade`
widens three closed-set CHECK constraints and does nothing else, which is what
admitting a capability and a record family costs. Every table this vocabulary
writes landed in `7e114f822af2`, `441b071bf37b`, `f5b06925857e` and
`17149a48fa30`.

**The literals below are frozen, not derived (`D-69`) — and no test is watching
this file.** A revision that derived them would agree with the enum on the day
it was written and silently change meaning every time the enum grew.
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces that rule by reading the `Table` objects a revision hands to
`create_all`; this revision imports `alembic.op` and nothing else and holds no
`Table`, so that guard's `_emitted` returns `None` for it and it is skipped
rather than checked. Honouring `D-69` here is therefore the author's
responsibility rather than a property a control will catch, and a later reader
should not assume otherwise.

That distinction matters unevenly across the two vocabularies, so it is stated
rather than left to be inferred:

- the capability literal holds one hundred and thirty-five values where the live
  `Capability` enum holds one hundred and twenty-four, because the stored
  vocabulary is already a strict superset — it still admits the eleven retired
  `native_sources.*` names, carried forward unchanged here because removing them
  would be an unrelated narrowing and is out of scope. Not being equal to a live
  closed set, it does not carry the equality that the guard above treats as the
  signature of a derivation, and would be safe even if the guard did read it;
- the record-family literal, by contrast, **is** exactly equal to the live
  `MutationRecordFamily` — eleven values against eleven members. Equality is
  what that guard exists to refuse, and this literal escapes it only because the
  guard reads `Table` objects and this revision holds none. It is a hand-written
  literal that happens to agree today; the next member added to that enum is the
  moment it stops agreeing, and nothing here will say so.

`downgrade` restores `c99cd8ed8d1c`'s three vocabularies exactly, so
empty → head → empty leaves no residue and a database that went up and came back
down enforces the same closed sets as one built from empty to the revision below.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "16f05c46b8c3"
down_revision: str | None = "c99cd8ed8d1c"
branch_labels: str | None = None
depends_on: str | None = None

#: Restated rather than imported from the shared table declarations, for the
#: reason the literals are written out: a revision that read the live schema
#: name would change meaning if the name ever did, and a migration has to keep
#: emitting what it emitted on the day it merged.
SCHEMA: Final = "knowledge"

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

_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', 'capture.read', "
    "'capture.revise', 'capture.search', 'commitments.close', 'commitments.create', "
    "'commitments.history', 'commitments.list', 'commitments.read', 'commitments.search', "
    "'commitments.update', 'commitments.waiting_on', 'context.feedback', 'context.prepare', "
    "'continuity.projects', 'continuity.projects.create', 'continuity.pulse', "
    "'continuity.situations', 'continuity.situations.create', 'continuity.tasks.create', "
    "'documents.archive', 'documents.create', 'documents.list', 'documents.read', "
    "'documents.restore', 'documents.revise', 'entities.aliases.add', 'entities.aliases.list', "
    "'entities.aliases.retire', 'entities.aliases.supersede', 'entities.archive', "
    "'entities.assignments.create', 'entities.assignments.end', 'entities.assignments.list', "
    "'entities.assignments.revise', 'entities.context', 'entities.create', 'entities.get', "
    "'entities.identifiers.bind', 'entities.identifiers.list', 'entities.identifiers.retire', "
    "'entities.identifiers.supersede', 'entities.identity_history', 'entities.merge', "
    "'entities.merge.preview', 'entities.observations.list', 'entities.observe', "
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

#: The mutation ledger's families. Written out for the column it constrains
#: rather than shared with the proposal pair below: the two constraints sit on
#: different tables over differently named columns, and a shared fragment would
#: make one revision's restatement of one constraint depend on the other's.
_MUTATED_RECORD_FAMILIES_AT_THIS_REVISION: Final = (
    "record_family IN ('address', 'alias', 'assignment', 'communication_method', 'entity', "
    "'identifier', 'name', 'observation', 'person_organization_affiliation', "
    "'project_participation', 'relationship')"
)

_MUTATED_RECORD_FAMILIES_BEFORE_THIS_REVISION: Final = (
    "record_family IN ('alias', 'assignment', 'entity', 'identifier', 'observation', "
    "'relationship')"
)

_ACCEPTED_PROPOSAL_RECORD_FAMILIES_AT_THIS_REVISION: Final = (
    "accepted_record_type IN ('address', 'alias', 'assignment', 'communication_method', 'entity', "
    "'identifier', 'name', 'observation', 'person_organization_affiliation', "
    "'project_participation', 'relationship')"
)

_ACCEPTED_PROPOSAL_RECORD_FAMILIES_BEFORE_THIS_REVISION: Final = (
    "accepted_record_type IN ('alias', 'assignment', 'entity', 'identifier', 'observation', "
    "'relationship')"
)


def _restate(capability: str, mutated_family: str, accepted_family: str) -> None:
    """Replace the three closed-set constraints in one transaction.

    One transaction, because a widening that landed on the audit table and
    failed on the mutation ledger would leave a database admitting a capability
    whose writes it then refuses to record — the same half-open state a separate
    revision per constraint would risk, arrived at from the other direction.
    """
    for table, name, expression in (
        ("audit_events", "capability_is_known", capability),
        ("entity_mutation_events", "a_mutated_record_family_is_known", mutated_family),
        ("entity_proposals", "an_accepted_proposal_record_family_is_known", accepted_family),
    ):
        op.execute(f'ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT "{name}"')
        op.execute(f'ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT "{name}" CHECK ({expression})')


def upgrade() -> None:
    _restate(
        _CAPABILITIES_AT_THIS_REVISION,
        _MUTATED_RECORD_FAMILIES_AT_THIS_REVISION,
        _ACCEPTED_PROPOSAL_RECORD_FAMILIES_AT_THIS_REVISION,
    )


def downgrade() -> None:
    _restate(
        _CAPABILITIES_BEFORE_THIS_REVISION,
        _MUTATED_RECORD_FAMILIES_BEFORE_THIS_REVISION,
        _ACCEPTED_PROPOSAL_RECORD_FAMILIES_BEFORE_THIS_REVISION,
    )
