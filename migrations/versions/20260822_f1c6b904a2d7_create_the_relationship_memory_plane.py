"""Create the Relationship Memory plane and admit its capabilities.

Eight tables, one immutability trigger function with two triggers, and one
widening of the two closed-set constraints on `audit_events`.

**Why the capability widening travels with the tables rather than after them.**
`c1a7e4b93d58` split those two acts across revisions because the entity tables
already existed when their capabilities were admitted. Here they do not: this
revision is the first thing in the chain that knows the word
`relationship_memory`, and a build that could serve `relationship_memory.create`
against a database whose `capability_is_known` refuses the string would fail on
the *audit* insert, after the memory row, which is the one failure ordering
`AGENTS.md` section 5 rules out — a security-relevant event that cannot be
recorded is a write that must not happen.

**The two triggers are the structural half of `RM-P-AC-003`.** No `CHECK` can
express "no `UPDATE`", and a rule enforced only by the current writer is a rule
the next writer does not inherit, so `relationship_memory_versions` and
`relationship_memory_review_decisions` each carry a `BEFORE UPDATE OR DELETE`
trigger that raises. This is the mechanism `1a4c9e77b2d5` installed on
`capture_versions` and `4c7b2e91d8a5` on managed versions, and it is why the
version table has no `superseded_at` column: a mutable supersession stamp would
be an `UPDATE` this trigger refuses, so supersession is read from
`prior_version_id` instead, where it is the same fact with no second writer.

`relationship_memories` is deliberately *not* append-only. It is the mutable
pointer — current version, aggregate version, lifecycle, pinned — and the whole
design puts every immutable thing on the version table so that this one may
change under optimistic concurrency.

**The eighteen closed sets below are frozen**, per the standing rule
`9c6b4a18ed72` states and `D-69`/`D-81` enforce: no Alembic revision may derive a
closed-set constraint from a domain enum. Each is written out here, so a database
migrated to this revision holds the vocabulary this revision describes rather
than whatever the domain says on the day it runs. `tests/architecture/
test_no_revision_derives_a_closed_set_from_an_enum.py` holds all eighteen texts,
so a member added to any of those enums cannot silently move what this revision
emits.

**That guard does not redden when an enum grows, and an earlier draft of this
docstring said it did.** Freezing is precisely what stops it: this revision goes
on emitting the eighteen texts whatever the domain says later, which is the
whole point. What catches a member added *without* a forward `ALTER` is
`tests/unit/test_relationship_memory_domain.py`, which pins each vocabulary
against the domain, together with `tests/schema/test_capture_schema_migration.py`,
which compares the vocabulary a live database admits at head against the one the
domain declares. Naming the wrong control is the defect class this campaign
keeps finding, so the correction is recorded rather than quietly applied.

**Rebased onto `a4d9e7c2b615` rather than merged with it.** This revision was
written against `e9b2c4d7a150` and the WP-FE-03 Work contracts landed on that
same parent while it was unmerged, which is a fork: two heads, and
`tests/architecture/test_managed_writes_are_contained.py` pins one. An Alembic
merge revision would have recorded the fork permanently for no schema reason —
the two touch disjoint tables — so the unmerged side moved instead. The
consequence is in the two literals below: `_CAPABILITIES_BEFORE_THIS_REVISION`
is now the vocabulary `a4d9e7c2b615` leaves behind, which is
`e9b2c4d7a150`'s plus `commitments.history`, `commitments.search` and
`commitments.update`, and `_CAPABILITIES_AT_THIS_REVISION` is that plus this
plane's eight. `_PURPOSES_*` are unchanged, because `a4d9e7c2b615` restates only
`capability_is_known`.

Revision ID: f1c6b904a2d7
Revises: a4d9e7c2b615
Create Date: 2026-08-22
"""

from __future__ import annotations

from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    relationship_memories,
    relationship_memory_context_links,
    relationship_memory_evidence_links,
    relationship_memory_proposal_evidence,
    relationship_memory_proposals,
    relationship_memory_review_decisions,
    relationship_memory_submissions,
    relationship_memory_versions,
)

revision: str = "f1c6b904a2d7"
down_revision: str | None = "a4d9e7c2b615"
branch_labels: str | None = None
depends_on: str | None = None

#: The eight tables this revision creates. `create_all` sorts by foreign key
#: itself; the order here is for a reader.
_TABLES: Final[list[Table]] = [
    relationship_memories,
    relationship_memory_versions,
    relationship_memory_submissions,
    relationship_memory_context_links,
    relationship_memory_evidence_links,
    relationship_memory_proposals,
    relationship_memory_proposal_evidence,
    relationship_memory_review_decisions,
]

#: The closed sets as this revision emits them, written out rather than derived.
_FROZEN: Final[dict[str, dict[str, str]]] = {
    "relationship_memories": {
        "a_memory_kind_is_known": (
            "memory_kind IN ('communication_preference', 'concern', 'follow_up_context', "
            "'general_note', 'important_date', 'interest', 'personal_detail', "
            "'sensitivity', 'user_pinned_context', 'working_preference')"
        ),
        "a_memory_lifecycle_state_is_known": "lifecycle_state IN ('active', 'archived')",
    },
    "relationship_memory_versions": {
        "a_memory_version_kind_is_known": (
            "memory_kind IN ('communication_preference', 'concern', 'follow_up_context', "
            "'general_note', 'important_date', 'interest', 'personal_detail', "
            "'sensitivity', 'user_pinned_context', 'working_preference')"
        ),
        "a_memory_authority_is_known": (
            "authority IN ('public_assertion', 'source_backed_assertion', "
            "'user_authored_private_note', 'user_confirmed_assertion')"
        ),
        "a_memory_classification_is_known": (
            "classification IN ('private_local', 'restricted_local', 'synthetic_test')"
        ),
        "a_memory_actor_class_is_known": (
            "created_by_actor IN ('review_promotion', 'system_deterministic', 'user')"
        ),
    },
    "relationship_memory_submissions": {
        "a_memory_submission_operation_is_known": (
            "operation IN ('archive', 'create', 'restore', 'revise')"
        ),
        "a_memory_submission_lifecycle_state_is_known": (
            "lifecycle_state IN ('active', 'archived')"
        ),
    },
    "relationship_memory_context_links": {
        "a_memory_context_target_type_is_known": (
            "target_type IN ('commitment', 'entity', 'situation', 'task')"
        ),
        "a_memory_context_role_is_known": ("role IN ('applies_in', 'arose_from', 'related_to')"),
        "a_memory_context_authority_is_known": (
            "authority IN ('deterministic', 'review_accepted', 'user_confirmed')"
        ),
    },
    "relationship_memory_evidence_links": {
        "a_memory_evidence_role_is_known": ("role IN ('counterevidence', 'direct', 'supporting')"),
    },
    "relationship_memory_proposals": {
        "a_memory_proposal_kind_is_known": (
            "proposed_kind IN ('communication_preference', 'concern', 'follow_up_context', "
            "'general_note', 'important_date', 'interest', 'personal_detail', "
            "'sensitivity', 'user_pinned_context', 'working_preference')"
        ),
        "a_memory_proposal_state_is_known": (
            "state IN ('accepted', 'corrected_accepted', 'deferred', 'invalidated', "
            "'needs_review', 'proposed', 'rejected', 'superseded')"
        ),
        "a_memory_proposal_method_is_known": ("method IN ('deterministic', 'local_model', 'rule')"),
        "a_memory_proposal_classification_is_known": (
            "classification IN ('private_local', 'restricted_local', 'synthetic_test')"
        ),
    },
    "relationship_memory_proposal_evidence": {
        "a_memory_proposal_evidence_role_is_known": (
            "role IN ('counterevidence', 'direct', 'supporting')"
        ),
    },
    "relationship_memory_review_decisions": {
        "a_memory_review_disposition_is_known": (
            "disposition IN ('accept', 'correct_and_accept', 'defer', 'escalate', "
            "'mark_unresolved', 'reject', 'reprocess')"
        ),
    },
}

#: The function and the triggers that make the two append-only tables append only.
_IMMUTABILITY_FUNCTION: Final = "relationship_memory_rows_stay_as_written"
_IMMUTABLE_TABLES: Final = (
    ("relationship_memory_versions", "relationship_memory_versions_are_append_only"),
    (
        "relationship_memory_review_decisions",
        "relationship_memory_decisions_are_append_only",
    ),
)

_PHASE_B_PROPOSAL_CONSTRAINTS: Final = frozenset(
    {
        "a_memory_proposal_expected_subject_version_is_positive",
        "a_memory_proposal_dedupe_is_a_sha256_digest",
        "a_superseded_memory_proposal_records_when",
        "a_memory_proposal_is_not_superseded_before_it_was_proposed",
        "only_a_superseded_memory_proposal_names_its_successor",
        "a_memory_proposal_is_not_its_own_successor",
        "a_memory_proposal_is_superseded_within_its_principal",
    }
)


def _freeze_out_phase_b_memory_columns(copy: Table) -> None:
    """Keep this historical copy at the schema its revision introduced."""
    if copy.name == "relationship_memory_proposals":
        for constraint in [
            candidate
            for candidate in copy.constraints
            if candidate.name in _PHASE_B_PROPOSAL_CONSTRAINTS
        ]:
            copy.constraints.discard(constraint)
        for index in [
            candidate
            for candidate in copy.indexes
            if candidate.name == "an_open_equivalent_memory_proposal_is_raised_once"
        ]:
            copy.indexes.discard(index)
        for name in (
            "expected_subject_version",
            "dedupe_sha256",
            "superseded_at",
            "superseded_by_memory_proposal_id",
        ):
            copy._columns.remove(copy.c[name])
    elif copy.name == "relationship_memory_proposal_evidence":
        for index in [
            candidate
            for candidate in copy.indexes
            if candidate.name
            in {
                "one_observation_role_per_memory_proposal",
                "one_capture_span_role_per_memory_proposal",
                "one_knowledge_role_per_memory_proposal",
            }
        ]:
            copy.indexes.discard(index)
    elif copy.name == "relationship_memory_review_decisions":
        for constraint in [
            candidate
            for candidate in copy.constraints
            if candidate.name
            in {
                "a_memory_review_reason_explains_a_departure",
                "a_memory_escalation_or_invalidation_states_why",
                "a_memory_review_reason_is_bounded",
            }
        ]:
            copy.constraints.discard(constraint)
        copy._columns.remove(copy.c.reason)


def _historical_relationship_memory_tables() -> list[Table]:
    """The eight tables as this revision emits them, with the eighteen sets frozen.

    Copies into a throwaway `MetaData` rather than restating the declarations,
    which is the pattern `9c6b4a18ed72` establishes and for the reason it gives:
    a duplicated column list here would be a second statement of each table and
    would drift from the first in a way nothing checks. All eight are copied into
    the *same* throwaway metadata, so the foreign keys among them — including
    `relationship_memory_versions.prior_version_id`, which points at its own
    table, and the deferred cycle between `relationship_memories` and its
    versions — resolve inside the copy rather than back at the shared declaration.
    """
    frozen = MetaData(schema=SCHEMA)
    copies = [table.to_metadata(frozen) for table in _TABLES]
    for copy in copies:
        _freeze_out_phase_b_memory_columns(copy)
        replacements = _FROZEN.get(copy.name, {})
        for constraint in [
            candidate for candidate in copy.constraints if candidate.name in replacements
        ]:
            copy.constraints.discard(constraint)
        for name, expression in replacements.items():
            copy.append_constraint(CheckConstraint(expression, name=name))
    return copies


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
    "'documents.revise', 'entities.context', 'entities.get', "
    "'entities.relationships', 'entities.resolve', 'entities.search', "
    "'entities.unresolved_mentions', 'goodnotes.content', "
    "'goodnotes.propose', 'goodnotes.work', 'knowledge.coverage', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'relationship_memory.archive', 'relationship_memory.create', "
    "'relationship_memory.get', 'relationship_memory.history', "
    "'relationship_memory.list', 'relationship_memory.restore', "
    "'relationship_memory.revise', 'relationship_memory.search', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', "
    "'reports.list', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
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
    "'entities.unresolved_mentions', 'goodnotes.content', "
    "'goodnotes.propose', 'goodnotes.work', 'knowledge.coverage', "
    "'knowledge.read', 'knowledge.reveal', 'knowledge.search', "
    "'native_sources.backfill', 'native_sources.configure', "
    "'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', "
    "'native_sources.reconcile', 'native_sources.resume', "
    "'native_sources.retry', 'native_sources.status', 'native_sources.sync', "
    "'reports.begin_cycle', 'reports.commit', 'reports.latest', "
    "'reports.list', 'reports.read', 'reports.record_run_state', "
    "'reports.resolve_set', 'reports.search', 'review.decide', 'review.list', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status', 'tasks.bulk_confirm', 'tasks.bulk_preview', "
    "'tasks.create', 'tasks.history', 'tasks.list', 'tasks.read', "
    "'tasks.search', 'tasks.transition', 'tasks.update')"
)

_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_read', "
    "'goodnotes_content', 'goodnotes_proposal', 'goodnotes_work', "
    "'knowledge_read', 'knowledge_search', 'relationship_memory_authoring', "
    "'relationship_memory_read', 'report_authoring', 'report_read', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation', 'task_authoring', 'task_read')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'commitment_authoring', 'commitment_read', 'content_extraction', "
    "'context_preference', 'context_preparation', 'continuity_authoring', "
    "'document_authoring', 'document_read', 'entity_read', "
    "'goodnotes_content', 'goodnotes_proposal', 'goodnotes_work', "
    "'knowledge_read', 'knowledge_search', 'report_authoring', 'report_read', "
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
    frozen = _historical_relationship_memory_tables()
    frozen[0].metadata.create_all(op.get_bind(), tables=frozen)
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
        )
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
    frozen = _historical_relationship_memory_tables()
    frozen[0].metadata.drop_all(op.get_bind(), tables=frozen)
