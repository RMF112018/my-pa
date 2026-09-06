"""Add the Constraint-management persistence plane.

Revision ID: 2774329487be
Revises: e8f2a6c9d104
Create Date: 2026-09-05

Fourteen additive, Principal-partitioned tables for the project-controls
Constraint plane: the record and its categories, the revision and receipt
ledgers behind it, the party rows either can carry, relationship and evidence
links, and the four tables that reconcile a Project's Constraints against one
external workbook. Nothing existing is altered: no column, no CHECK, no
capability or purpose vocabulary, which is why this revision emits no
`_restate`.

Written as frozen DDL text rather than against
`my_pa.infrastructure.persistence.tables`. A revision that imported the live
declaration would change meaning whenever that declaration evolved, and an old
revision whose meaning moves is a migration nobody can replay; the runtime
declaration and this text are compared instead, by
`tests/schema/test_constraint_management_migration.py` and by the metadata
correspondence tests on a migrated clone.

**Three foreign keys form one cycle and two more form a second**, so five are
added by `ALTER TABLE` after all fourteen tables exist and every one of them is
`DEFERRABLE INITIALLY DEFERRED`: a Constraint names its current revision, a
revision names the receipt that wrote it, a receipt names the revision it
produced, and a sync target names both its active and its last verified run
while a run names its target. Writing either side of such a pair means writing
both in one transaction, so the check belongs at `COMMIT` and not at the
statement.

Four ledgers are append-only at the server — revisions, revision parties, and
the two receipt tables — through the immutability trigger function
`knowledge.managed_document_rows_stay_as_written()` that `91d7b3e5a204` created
and every append-only plane since has reused. This revision does not own that
function and does not drop it.
"""

from __future__ import annotations

from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

revision: str = "2774329487be"
down_revision: str | None = "e8f2a6c9d104"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: Every closed set this revision's DDL admits, written out here as well so the
#: freeze is a declaration and not an accident of agreement. Sixteen of the
#: twenty-seven equal a live `my_pa.domain.project_controls` vocabulary today —
#: lifecycle state, record quality and origin on the record and on its
#: revisions, party kind on both party tables, category state, and the
#: operation, actor and outcome of both receipt ledgers, one of them the
#: terminal-state pair. The rest are this revision's own literals, and **all
#: twenty-seven are frozen**, because the point of `D-81` is that a literal
#: which happens to agree with an enum today is indistinguishable from a
#: derived one and carries the identical hazard: the next member added to that
#: enum is the moment they stop agreeing, and freezing only the sixteen would
#: leave the other eleven to become derived sites the day some later enum
#: happens to match them.
#: `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
#: restates these values independently and reads them through
#: `_historical_constraint_management_tables` below;
#: `tests/schema/test_constraint_management_migration.py` asserts that every
#: expression here is the expression the DDL actually emits.
_FROZEN: Final[dict[str, dict[str, str]]] = {
    "constraint_categories": {
        "a_constraint_category_state_is_known": ("state IN ('active', 'archived', 'inactive')"),
    },
    "project_constraints": {
        "a_project_constraint_lifecycle_state_is_known": (
            "lifecycle_state IN ('closed', 'draft', 'identified', 'in_progress', 'on_hold', "
            "'pending', 'void')"
        ),
        "a_project_constraint_record_quality_is_known": (
            "record_quality IN ('legacy_incomplete', 'normal')"
        ),
        "a_project_constraint_origin_is_known": ("origin IN ('legacy_workbook_import', 'product')"),
        "an_active_constraint_carries_no_terminal_fields": (
            "lifecycle_state IN ('closed', 'void') OR (completion_date IS NULL AND "
            "voided_date IS NULL AND void_reason IS NULL)"
        ),
    },
    "project_constraint_parties": {
        "a_constraint_party_role_is_known": "role IN ('bic', 'responsible')",
        "a_constraint_party_kind_is_known": ("party_kind IN ('entity', 'principal', 'unresolved')"),
    },
    "project_constraint_revisions": {
        "a_constraint_revision_lifecycle_state_is_known": (
            "lifecycle_state IN ('closed', 'draft', 'identified', 'in_progress', 'on_hold', "
            "'pending', 'void')"
        ),
        "a_constraint_revision_record_quality_is_known": (
            "record_quality IN ('legacy_incomplete', 'normal')"
        ),
        "a_constraint_revision_origin_is_known": (
            "origin IN ('legacy_workbook_import', 'product')"
        ),
    },
    "project_constraint_revision_parties": {
        "a_constraint_revision_party_role_is_known": "role IN ('bic', 'responsible')",
        "a_constraint_revision_party_kind_is_known": (
            "party_kind IN ('entity', 'principal', 'unresolved')"
        ),
    },
    "project_constraint_history": {
        "a_constraint_history_operation_is_known": (
            "operation IN ('close', 'create', 'publish', 'reopen', 'transition', 'update', 'void')"
        ),
        "a_constraint_history_actor_is_known": ("actor IN ('assistant', 'principal', 'system')"),
        "a_constraint_history_outcome_is_known": ("outcome IN ('applied', 'no_op', 'rejected')"),
    },
    "constraint_category_history": {
        "a_constraint_category_history_operation_is_known": (
            "operation IN ('archive', 'create', 'update')"
        ),
        "a_constraint_category_history_actor_is_known": (
            "actor IN ('assistant', 'principal', 'system')"
        ),
        "a_constraint_category_history_outcome_is_known": (
            "outcome IN ('applied', 'no_op', 'rejected')"
        ),
    },
    "project_constraint_relationships": {
        "a_constraint_relationship_type_is_known": "relationship_type IN ('follow_up_of')",
    },
    "project_constraint_evidence_links": {
        "a_constraint_evidence_kind_is_known": (
            "evidence_kind IN ('capture', 'capture_assertion', 'managed_document', "
            "'managed_document_version')"
        ),
        "a_constraint_evidence_role_is_known": "role IN ('closure', 'reference')",
    },
    "constraint_sync_targets": {
        "a_constraint_sync_external_kind_is_known": "external_kind IN ('excel_workbook')",
    },
    "constraint_sync_runs": {
        "a_constraint_sync_run_state_is_known": (
            "state IN ('acknowledged', 'applied', 'failed', 'previewed', 'started')"
        ),
        "a_constraint_sync_run_outcome_is_known": (
            "outcome IS NULL OR outcome IN ('applied', 'failed', 'no_change')"
        ),
        "a_finished_sync_run_records_when_it_finished": (
            "(state IN ('acknowledged', 'applied', 'failed')) = (finished_at IS NOT NULL)"
        ),
    },
    "constraint_sync_conflicts": {
        "a_constraint_sync_conflict_kind_is_known": (
            "conflict_kind IN ('both_changed', 'deleted_in_canonical', "
            "'deleted_in_external', 'new_in_external')"
        ),
        "a_constraint_sync_conflict_state_is_known": (
            "state IN ('open', 'resolved', 'superseded')"
        ),
    },
}
#: The four append-only ledgers, in creation order. The trigger name follows the
#: convention every append-only plane in this schema uses, so a reader grepping
#: `_are_immutable` finds all of them at once.
_IMMUTABLE_TABLES: Final = (
    "project_constraint_revisions",
    "project_constraint_revision_parties",
    "project_constraint_history",
    "constraint_category_history",
)

#: The five foreign keys added after every table exists, in the order they are
#: added and the reverse of the order they are dropped.
_DEFERRED_FOREIGN_KEYS: Final = (
    ("project_constraints", "a_constraint_names_its_current_revision"),
    ("project_constraint_revisions", "a_constraint_revision_cites_the_receipt_that_wrote_it"),
    ("project_constraint_history", "a_constraint_receipt_names_the_revision_it_wrote"),
    ("constraint_sync_targets", "a_sync_target_names_a_verified_run_of_its_principal"),
    ("constraint_sync_targets", "a_sync_target_names_an_active_run_of_its_principal"),
)

#: The fourteen tables, in creation order; dropped in the reverse.
_CREATED_TABLES: Final = (
    "constraint_project_settings",
    "constraint_categories",
    "project_constraints",
    "project_constraint_parties",
    "project_constraint_revisions",
    "project_constraint_revision_parties",
    "project_constraint_history",
    "constraint_category_history",
    "project_constraint_relationships",
    "project_constraint_evidence_links",
    "constraint_sync_targets",
    "constraint_sync_runs",
    "constraint_sync_baselines",
    "constraint_sync_conflicts",
)


def _historical_constraint_management_tables() -> list[Table]:
    """The closed sets this revision emits, as objects the `D-81` guard reads.

    The DDL below is raw text, because this revision may not import the live
    declaration; `tests/architecture/test_no_revision_derives_a_closed_set_from_
    an_enum.py` reads a revision's emission as `Table` objects, and text is the
    one shape it cannot read. So the frozen vocabularies are handed to it here,
    carrying nothing but the constraints `_FROZEN` names — these tables are the
    *vocabulary* this revision emits and not a second statement of its columns,
    which would be a duplicate declaration that could drift from the DDL with
    nothing to catch it. That the two agree is asserted instead, over the
    rendered SQL, by `tests/schema/test_constraint_management_migration.py`.
    """
    metadata = MetaData(schema=SCHEMA)
    return [
        Table(
            name,
            metadata,
            *(
                CheckConstraint(expression, name=constraint)
                for constraint, expression in constraints.items()
            ),
        )
        for name, constraints in _FROZEN.items()
    ]


def _immutable(table: str) -> None:
    op.execute(
        f"CREATE TRIGGER {table}_are_immutable BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
        "FOR EACH ROW EXECUTE FUNCTION knowledge.managed_document_rows_stay_as_written()"
    )


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_project_settings (
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          timezone_name TEXT NOT NULL,
          version INTEGER DEFAULT 1 NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          CONSTRAINT one_constraint_setting_per_project PRIMARY KEY (principal_id, project_id),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_project_timezone_is_a_bare_name CHECK (length(trim(timezone_name))
            BETWEEN 1 AND 64 AND timezone_name !~ '\\s'),
          CONSTRAINT a_constraint_settings_version_is_positive CHECK (version >= 1),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_categories (
          category_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          prefix TEXT NOT NULL,
          title TEXT NOT NULL,
          description TEXT,
          display_order INTEGER DEFAULT 0 NOT NULL,
          state TEXT DEFAULT 'active' NOT NULL,
          next_sequence INTEGER DEFAULT 1 NOT NULL,
          issued_count INTEGER DEFAULT 0 NOT NULL,
          prefix_locked_at TIMESTAMP WITH TIME ZONE,
          version INTEGER DEFAULT 1 NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          archived_at TIMESTAMP WITH TIME ZONE,
          PRIMARY KEY (category_id),
          CONSTRAINT category_id_is_an_opaque_identifier CHECK (category_id ~
            '^ccat_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_category_state_is_known CHECK (state IN ('active', 'archived',
            'inactive')),
          CONSTRAINT a_constraint_category_prefix_is_well_formed CHECK (prefix ~
            '^[A-Za-z0-9][A-Za-z0-9_-]{{0,15}}$'),
          CONSTRAINT a_constraint_category_title_is_bounded CHECK (length(trim(title)) BETWEEN 1 AND
            200),
          CONSTRAINT a_constraint_category_sequence_is_positive CHECK (next_sequence >= 1),
          CONSTRAINT a_constraint_category_issue_count_is_non_negative CHECK (issued_count >= 0),
          CONSTRAINT a_constraint_category_version_is_positive CHECK (version >= 1),
          CONSTRAINT an_archived_constraint_category_records_when_it_was CHECK ((state = 'archived')
            = (archived_at IS NOT NULL)),
          CONSTRAINT a_constraint_category_prefix_locks_at_first_issue CHECK ((issued_count = 0) =
            (prefix_locked_at IS NULL)),
          CONSTRAINT constraint_categories_prefix_is_unique_per_project UNIQUE (project_id, prefix),
          CONSTRAINT constraint_categories_principal_category_is_unique UNIQUE (principal_id,
            category_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_categories_by_principal_project ON {SCHEMA}.constraint_categories
          (principal_id, project_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraints (
          constraint_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT,
          category_id TEXT,
          constraint_code TEXT,
          description TEXT,
          date_identified DATE,
          lifecycle_state TEXT NOT NULL,
          due_date DATE,
          reference TEXT,
          current_update TEXT,
          completion_date DATE,
          closure_commentary TEXT,
          voided_date DATE,
          void_reason TEXT,
          record_quality TEXT DEFAULT 'normal' NOT NULL,
          origin TEXT NOT NULL,
          published_at TIMESTAMP WITH TIME ZONE,
          version INTEGER DEFAULT 1 NOT NULL,
          current_revision_id TEXT,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (constraint_id),
          CONSTRAINT constraint_id_is_an_opaque_identifier CHECK (constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_project_is_an_opaque_identifier CHECK (project_id IS NULL OR
            project_id ~ '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_category_is_an_opaque_identifier CHECK (category_id IS NULL OR
            category_id ~ '^ccat_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_revision_link_is_an_opaque_identifier CHECK (current_revision_id
            IS NULL OR current_revision_id ~ '^crev_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_project_constraint_lifecycle_state_is_known CHECK (lifecycle_state IN
            ('closed', 'draft', 'identified', 'in_progress', 'on_hold', 'pending', 'void')),
          CONSTRAINT a_project_constraint_record_quality_is_known CHECK (record_quality IN
            ('legacy_incomplete', 'normal')),
          CONSTRAINT a_project_constraint_origin_is_known CHECK (origin IN
            ('legacy_workbook_import', 'product')),
          CONSTRAINT a_project_constraint_version_is_positive CHECK (version >= 1),
          CONSTRAINT a_legacy_incomplete_constraint_is_a_workbook_import CHECK (record_quality <>
            'legacy_incomplete' OR origin = 'legacy_workbook_import'),
          CONSTRAINT a_draft_constraint_carries_no_code CHECK ((lifecycle_state = 'draft') =
            (constraint_code IS NULL)),
          CONSTRAINT a_constraint_code_is_not_blank CHECK (constraint_code IS NULL OR
            length(trim(constraint_code)) BETWEEN 1 AND 32),
          CONSTRAINT a_published_constraint_records_when_it_published CHECK ((origin =
            'legacy_workbook_import' AND record_quality = 'legacy_incomplete') OR ((lifecycle_state
            = 'draft') = (published_at IS NULL))),
          CONSTRAINT a_published_constraint_is_complete CHECK ((origin = 'legacy_workbook_import'
            AND record_quality = 'legacy_incomplete') OR lifecycle_state = 'draft' OR (project_id IS
            NOT NULL AND category_id IS NOT NULL AND description IS NOT NULL AND date_identified IS
            NOT NULL AND due_date IS NOT NULL)),
          CONSTRAINT a_published_constraint_belongs_to_a_project CHECK (lifecycle_state = 'draft' OR
            project_id IS NOT NULL),
          CONSTRAINT a_closed_constraint_records_its_completion CHECK ((origin =
            'legacy_workbook_import' AND record_quality = 'legacy_incomplete') OR lifecycle_state <>
            'closed' OR completion_date IS NOT NULL),
          CONSTRAINT a_void_constraint_records_its_reason CHECK ((origin = 'legacy_workbook_import'
            AND record_quality = 'legacy_incomplete') OR lifecycle_state <> 'void' OR (voided_date
            IS NOT NULL AND length(trim(void_reason)) > 0)),
          CONSTRAINT a_closed_constraint_carries_no_void_fields CHECK (lifecycle_state <> 'closed'
            OR (voided_date IS NULL AND void_reason IS NULL)),
          CONSTRAINT a_void_constraint_carries_no_completion CHECK (lifecycle_state <> 'void' OR
            completion_date IS NULL),
          CONSTRAINT an_active_constraint_carries_no_terminal_fields CHECK (lifecycle_state IN
            ('closed', 'void') OR (completion_date IS NULL AND voided_date IS NULL AND void_reason
            IS NULL)),
          CONSTRAINT project_constraints_principal_constraint_is_unique UNIQUE (principal_id,
            constraint_id),
          CONSTRAINT a_constraint_belongs_to_a_category_of_its_principal FOREIGN KEY(principal_id,
            category_id) REFERENCES {SCHEMA}.constraint_categories (principal_id, category_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraints_by_principal ON {SCHEMA}.project_constraints (principal_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraints_by_principal_project_state ON {SCHEMA}.project_constraints
          (principal_id, project_id, lifecycle_state)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX project_constraints_code_is_unique_per_project ON
          {SCHEMA}.project_constraints (project_id, constraint_code) WHERE constraint_code IS NOT
          NULL
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraint_parties (
          party_assignment_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          constraint_id TEXT NOT NULL,
          role TEXT NOT NULL,
          ordinal INTEGER NOT NULL,
          party_kind TEXT NOT NULL,
          entity_id TEXT,
          display_label TEXT,
          original_label TEXT,
          resolved_at TIMESTAMP WITH TIME ZONE,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (party_assignment_id),
          CONSTRAINT party_assignment_id_is_an_opaque_identifier CHECK (party_assignment_id ~
            '^cpty_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT constraint_id_is_an_opaque_identifier CHECK (constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_party_entity_is_an_opaque_identifier CHECK (entity_id IS NULL OR
            entity_id ~ '^ent_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_party_role_is_known CHECK (role IN ('bic', 'responsible')),
          CONSTRAINT a_constraint_party_kind_is_known CHECK (party_kind IN ('entity', 'principal',
            'unresolved')),
          CONSTRAINT an_entity_constraint_party_names_its_entity CHECK ((party_kind = 'entity') =
            (entity_id IS NOT NULL)),
          CONSTRAINT an_unresolved_constraint_party_keeps_its_label CHECK (party_kind <>
            'unresolved' OR length(trim(coalesce(display_label, ''))) > 0),
          CONSTRAINT a_constraint_party_ordinal_is_non_negative CHECK (ordinal >= 0),
          CONSTRAINT a_constraint_party_display_label_is_bounded CHECK (display_label IS NULL OR
            length(trim(display_label)) BETWEEN 1 AND 512),
          CONSTRAINT a_constraint_party_original_label_is_bounded CHECK (original_label IS NULL OR
            length(trim(original_label)) BETWEEN 1 AND 512),
          CONSTRAINT project_constraint_parties_role_ordinal_is_unique UNIQUE (constraint_id, role,
            ordinal),
          CONSTRAINT a_constraint_party_belongs_to_a_constraint_of_its_principal FOREIGN
            KEY(principal_id, constraint_id) REFERENCES {SCHEMA}.project_constraints (principal_id,
            constraint_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_parties_by_principal_constraint ON
          {SCHEMA}.project_constraint_parties (principal_id, constraint_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraint_revisions (
          revision_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT,
          constraint_id TEXT NOT NULL,
          version INTEGER NOT NULL,
          history_id TEXT NOT NULL,
          category_id TEXT,
          constraint_code TEXT,
          description TEXT,
          date_identified DATE,
          lifecycle_state TEXT NOT NULL,
          due_date DATE,
          reference TEXT,
          current_update TEXT,
          completion_date DATE,
          closure_commentary TEXT,
          voided_date DATE,
          void_reason TEXT,
          record_quality TEXT NOT NULL,
          origin TEXT NOT NULL,
          published_at TIMESTAMP WITH TIME ZONE,
          recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (revision_id),
          CONSTRAINT revision_id_is_an_opaque_identifier CHECK (revision_id ~
            '^crev_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT constraint_id_is_an_opaque_identifier CHECK (constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT history_id_is_an_opaque_identifier CHECK (history_id ~
            '^chst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_revision_project_is_an_opaque_identifier CHECK (project_id IS NULL
            OR project_id ~ '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_revision_category_is_an_opaque_identifier CHECK (category_id IS
            NULL OR category_id ~ '^ccat_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_revision_lifecycle_state_is_known CHECK (lifecycle_state IN
            ('closed', 'draft', 'identified', 'in_progress', 'on_hold', 'pending', 'void')),
          CONSTRAINT a_constraint_revision_record_quality_is_known CHECK (record_quality IN
            ('legacy_incomplete', 'normal')),
          CONSTRAINT a_constraint_revision_origin_is_known CHECK (origin IN
            ('legacy_workbook_import', 'product')),
          CONSTRAINT a_constraint_revision_version_is_positive CHECK (version >= 1),
          CONSTRAINT project_constraint_revisions_version_is_unique UNIQUE (constraint_id, version),
          CONSTRAINT project_constraint_revisions_principal_revision_is_unique UNIQUE (principal_id,
            revision_id),
          CONSTRAINT a_constraint_revision_belongs_to_a_constraint_of_its_principal FOREIGN
            KEY(principal_id, constraint_id) REFERENCES {SCHEMA}.project_constraints (principal_id,
            constraint_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_revisions_by_principal_constraint ON
          {SCHEMA}.project_constraint_revisions (principal_id, constraint_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraint_revision_parties (
          revision_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          role TEXT NOT NULL,
          ordinal INTEGER NOT NULL,
          party_kind TEXT NOT NULL,
          entity_id TEXT,
          display_label TEXT,
          original_label TEXT,
          resolved_at TIMESTAMP WITH TIME ZONE,
          CONSTRAINT one_constraint_revision_party_position PRIMARY KEY (revision_id, role,
            ordinal),
          CONSTRAINT revision_id_is_an_opaque_identifier CHECK (revision_id ~
            '^crev_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_revision_party_entity_is_an_opaque_identifier CHECK (entity_id IS NULL OR
            entity_id ~ '^ent_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_revision_party_role_is_known CHECK (role IN ('bic',
            'responsible')),
          CONSTRAINT a_constraint_revision_party_kind_is_known CHECK (party_kind IN ('entity',
            'principal', 'unresolved')),
          CONSTRAINT an_entity_revision_party_names_its_entity CHECK ((party_kind = 'entity') =
            (entity_id IS NOT NULL)),
          CONSTRAINT an_unresolved_revision_party_keeps_its_label CHECK (party_kind <> 'unresolved'
            OR length(trim(coalesce(display_label, ''))) > 0),
          CONSTRAINT a_revision_party_ordinal_is_non_negative CHECK (ordinal >= 0),
          CONSTRAINT a_revision_party_display_label_is_bounded CHECK (display_label IS NULL OR
            length(trim(display_label)) BETWEEN 1 AND 512),
          CONSTRAINT a_revision_party_original_label_is_bounded CHECK (original_label IS NULL OR
            length(trim(original_label)) BETWEEN 1 AND 512),
          CONSTRAINT a_revision_party_belongs_to_a_revision_of_its_principal FOREIGN
            KEY(principal_id, revision_id) REFERENCES {SCHEMA}.project_constraint_revisions
            (principal_id, revision_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_revision_parties_by_principal ON
          {SCHEMA}.project_constraint_revision_parties (principal_id, revision_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraint_history (
          history_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT,
          constraint_id TEXT NOT NULL,
          operation TEXT NOT NULL,
          actor TEXT NOT NULL,
          outcome TEXT NOT NULL,
          before_version INTEGER NOT NULL,
          after_version INTEGER NOT NULL,
          occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
          recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
          idempotency_key TEXT,
          request_digest TEXT,
          client_context TEXT,
          revision_id TEXT,
          correlation_id TEXT,
          safe_failure_reason TEXT,
          PRIMARY KEY (history_id),
          CONSTRAINT history_id_is_an_opaque_identifier CHECK (history_id ~
            '^chst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT constraint_id_is_an_opaque_identifier CHECK (constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_history_project_is_an_opaque_identifier CHECK (project_id IS NULL
            OR project_id ~ '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_history_revision_is_an_opaque_identifier CHECK (revision_id IS
            NULL OR revision_id ~ '^crev_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_history_correlation_is_an_opaque_identifier CHECK (correlation_id
            IS NULL OR correlation_id ~ '^corr_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_history_operation_is_known CHECK (operation IN ('close', 'create',
            'publish', 'reopen', 'transition', 'update', 'void')),
          CONSTRAINT a_constraint_history_actor_is_known CHECK (actor IN ('assistant', 'principal',
            'system')),
          CONSTRAINT a_constraint_history_outcome_is_known CHECK (outcome IN ('applied', 'no_op',
            'rejected')),
          CONSTRAINT a_constraint_history_before_version_is_non_negative CHECK (before_version >=
            0),
          CONSTRAINT an_applied_constraint_mutation_advances_its_version CHECK ((outcome =
            'applied') = (after_version > before_version)),
          CONSTRAINT an_unapplied_constraint_mutation_changes_no_version CHECK (outcome = 'applied'
            OR after_version = before_version),
          CONSTRAINT an_applied_constraint_mutation_records_its_revision CHECK ((outcome =
            'applied') = (revision_id IS NOT NULL)),
          CONSTRAINT only_a_rejected_constraint_mutation_records_a_reason CHECK (outcome =
            'rejected' OR safe_failure_reason IS NULL),
          CONSTRAINT a_constraint_history_failure_reason_is_bounded CHECK (safe_failure_reason IS
            NULL OR length(trim(safe_failure_reason)) BETWEEN 1 AND 128),
          CONSTRAINT a_constraint_history_idempotency_key_is_bounded CHECK (idempotency_key IS NULL
            OR idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'),
          CONSTRAINT a_constraint_history_request_digest_is_sha256 CHECK (request_digest IS NULL OR
            request_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_constraint_history_client_context_is_bounded CHECK (client_context IS NULL OR
            length(trim(client_context)) BETWEEN 1 AND 128),
          CONSTRAINT project_constraint_history_principal_receipt_is_unique UNIQUE (principal_id,
            history_id),
          CONSTRAINT a_constraint_receipt_belongs_to_a_constraint_of_its_principal FOREIGN
            KEY(principal_id, constraint_id) REFERENCES {SCHEMA}.project_constraints (principal_id,
            constraint_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_history_by_principal ON {SCHEMA}.project_constraint_history
          (principal_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_history_by_principal_constraint ON
          {SCHEMA}.project_constraint_history (principal_id, constraint_id)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX project_constraint_history_key_is_unique_per_principal ON
          {SCHEMA}.project_constraint_history (principal_id, idempotency_key) WHERE idempotency_key
          IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_category_history (
          history_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          category_id TEXT NOT NULL,
          operation TEXT NOT NULL,
          actor TEXT NOT NULL,
          outcome TEXT NOT NULL,
          before_version INTEGER NOT NULL,
          after_version INTEGER NOT NULL,
          occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
          recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
          idempotency_key TEXT,
          request_digest TEXT,
          client_context TEXT,
          correlation_id TEXT,
          safe_failure_reason TEXT,
          PRIMARY KEY (history_id),
          CONSTRAINT history_id_is_an_opaque_identifier CHECK (history_id ~
            '^cchst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT category_id_is_an_opaque_identifier CHECK (category_id ~
            '^ccat_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_category_history_correlation_is_an_opaque_identifier CHECK (correlation_id IS
            NULL OR correlation_id ~ '^corr_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_category_history_operation_is_known CHECK (operation IN
            ('archive', 'create', 'update')),
          CONSTRAINT a_constraint_category_history_actor_is_known CHECK (actor IN ('assistant',
            'principal', 'system')),
          CONSTRAINT a_constraint_category_history_outcome_is_known CHECK (outcome IN ('applied',
            'no_op', 'rejected')),
          CONSTRAINT a_category_history_before_version_is_non_negative CHECK (before_version >= 0),
          CONSTRAINT an_applied_category_mutation_advances_its_version CHECK ((outcome = 'applied')
            = (after_version > before_version)),
          CONSTRAINT an_unapplied_category_mutation_changes_no_version CHECK (outcome = 'applied' OR
            after_version = before_version),
          CONSTRAINT only_a_rejected_category_mutation_records_a_reason CHECK (outcome = 'rejected'
            OR safe_failure_reason IS NULL),
          CONSTRAINT a_category_history_failure_reason_is_bounded CHECK (safe_failure_reason IS NULL
            OR length(trim(safe_failure_reason)) BETWEEN 1 AND 128),
          CONSTRAINT a_category_history_idempotency_key_is_bounded CHECK (idempotency_key IS NULL OR
            idempotency_key ~ '^[A-Za-z0-9_-]{{8,128}}$'),
          CONSTRAINT a_category_history_request_digest_is_sha256 CHECK (request_digest IS NULL OR
            request_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_category_history_client_context_is_bounded CHECK (client_context IS NULL OR
            length(trim(client_context)) BETWEEN 1 AND 128),
          CONSTRAINT constraint_category_history_principal_receipt_is_unique UNIQUE (principal_id,
            history_id),
          CONSTRAINT a_category_receipt_belongs_to_a_category_of_its_principal FOREIGN
            KEY(principal_id, category_id) REFERENCES {SCHEMA}.constraint_categories (principal_id,
            category_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_category_history_by_principal ON
          {SCHEMA}.constraint_category_history (principal_id)
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_category_history_by_principal_category ON
          {SCHEMA}.constraint_category_history (principal_id, category_id)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX constraint_category_history_key_is_unique_per_principal ON
          {SCHEMA}.constraint_category_history (principal_id, idempotency_key) WHERE idempotency_key
          IS NOT NULL
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraint_relationships (
          relationship_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          source_constraint_id TEXT NOT NULL,
          target_constraint_id TEXT NOT NULL,
          relationship_type TEXT NOT NULL,
          created_by_history_id TEXT NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (relationship_id),
          CONSTRAINT relationship_id_is_an_opaque_identifier CHECK (relationship_id ~
            '^crel_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT source_constraint_id_is_an_opaque_identifier CHECK (source_constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT target_constraint_id_is_an_opaque_identifier CHECK (target_constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT created_by_history_id_is_an_opaque_identifier CHECK (created_by_history_id ~
            '^chst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_relationship_type_is_known CHECK (relationship_type IN
            ('follow_up_of')),
          CONSTRAINT a_constraint_does_not_relate_to_itself CHECK (source_constraint_id <>
            target_constraint_id),
          CONSTRAINT one_constraint_relationship_per_pair_and_type UNIQUE (source_constraint_id,
            target_constraint_id, relationship_type),
          CONSTRAINT a_constraint_relationship_names_a_source_of_its_principal FOREIGN
            KEY(principal_id, source_constraint_id) REFERENCES {SCHEMA}.project_constraints
            (principal_id, constraint_id),
          CONSTRAINT a_constraint_relationship_names_a_target_of_its_principal FOREIGN
            KEY(principal_id, target_constraint_id) REFERENCES {SCHEMA}.project_constraints
            (principal_id, constraint_id),
          CONSTRAINT a_constraint_relationship_records_the_receipt_that_made_it FOREIGN
            KEY(principal_id, created_by_history_id) REFERENCES {SCHEMA}.project_constraint_history
            (principal_id, history_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_relationships_by_principal_project ON
          {SCHEMA}.project_constraint_relationships (principal_id, project_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.project_constraint_evidence_links (
          evidence_link_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          constraint_id TEXT NOT NULL,
          evidence_kind TEXT NOT NULL,
          evidence_ref TEXT NOT NULL,
          role TEXT NOT NULL,
          created_by_history_id TEXT NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (evidence_link_id),
          CONSTRAINT evidence_link_id_is_an_opaque_identifier CHECK (evidence_link_id ~
            '^cevd_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT constraint_id_is_an_opaque_identifier CHECK (constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT created_by_history_id_is_an_opaque_identifier CHECK (created_by_history_id ~
            '^chst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_evidence_kind_is_known CHECK (evidence_kind IN ('capture',
            'capture_assertion', 'managed_document', 'managed_document_version')),
          CONSTRAINT a_constraint_evidence_role_is_known CHECK (role IN ('closure', 'reference')),
          CONSTRAINT a_constraint_evidence_ref_matches_its_kind CHECK ((evidence_kind = 'capture'
            AND evidence_ref ~ '^cap_[A-Za-z0-9]{{8,64}}$') OR (evidence_kind = 'capture_assertion'
            AND evidence_ref ~ '^asrt_[A-Za-z0-9]{{8,64}}$') OR (evidence_kind = 'managed_document'
            AND evidence_ref ~ '^mdoc_[A-Za-z0-9]{{8,64}}$') OR (evidence_kind =
            'managed_document_version' AND evidence_ref ~ '^mdver_[A-Za-z0-9]{{8,64}}$')),
          CONSTRAINT one_constraint_evidence_link_per_reference UNIQUE (constraint_id,
            evidence_ref),
          CONSTRAINT a_constraint_evidence_link_belongs_to_its_principals_constraint FOREIGN
            KEY(principal_id, constraint_id) REFERENCES {SCHEMA}.project_constraints (principal_id,
            constraint_id),
          CONSTRAINT a_constraint_evidence_link_records_the_receipt_that_made_it FOREIGN
            KEY(principal_id, created_by_history_id) REFERENCES {SCHEMA}.project_constraint_history
            (principal_id, history_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX project_constraint_evidence_links_by_principal_constraint ON
          {SCHEMA}.project_constraint_evidence_links (principal_id, constraint_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_sync_targets (
          sync_target_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          external_kind TEXT NOT NULL,
          external_identity TEXT NOT NULL,
          normalization_contract_version TEXT NOT NULL,
          last_verified_provider_version TEXT,
          last_verified_workbook_digest TEXT,
          last_verified_at TIMESTAMP WITH TIME ZONE,
          last_verified_sync_run_id TEXT,
          active_run_id TEXT,
          active_run_lease_until TIMESTAMP WITH TIME ZONE,
          version INTEGER DEFAULT 1 NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (sync_target_id),
          CONSTRAINT sync_target_id_is_an_opaque_identifier CHECK (sync_target_id ~
            '^csyt_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_sync_target_active_run_is_an_opaque_identifier CHECK (active_run_id IS NULL
            OR active_run_id ~ '^csyr_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_sync_target_verified_run_is_an_opaque_identifier CHECK
            (last_verified_sync_run_id IS NULL OR last_verified_sync_run_id ~
            '^csyr_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_sync_external_kind_is_known CHECK (external_kind IN
            ('excel_workbook')),
          CONSTRAINT a_sync_target_external_identity_is_opaque CHECK
            (length(trim(external_identity)) BETWEEN 1 AND 1024 AND external_identity !~ '\\s'),
          CONSTRAINT a_sync_target_contract_version_is_bounded CHECK
            (length(trim(normalization_contract_version)) BETWEEN 1 AND 64),
          CONSTRAINT a_sync_target_provider_version_is_bounded CHECK (last_verified_provider_version
            IS NULL OR length(trim(last_verified_provider_version)) BETWEEN 1 AND 256),
          CONSTRAINT a_sync_target_workbook_digest_is_sha256 CHECK (last_verified_workbook_digest IS
            NULL OR last_verified_workbook_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT an_active_sync_run_holds_a_lease CHECK ((active_run_id IS NULL) =
            (active_run_lease_until IS NULL)),
          CONSTRAINT a_sync_target_version_is_positive CHECK (version >= 1),
          CONSTRAINT one_constraint_sync_target_per_external_workbook UNIQUE (project_id,
            external_kind, external_identity),
          CONSTRAINT constraint_sync_targets_principal_target_is_unique UNIQUE (principal_id,
            sync_target_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_sync_targets_by_principal_project ON
          {SCHEMA}.constraint_sync_targets (principal_id, project_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_sync_runs (
          sync_run_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          sync_target_id TEXT NOT NULL,
          state TEXT NOT NULL,
          started_at TIMESTAMP WITH TIME ZONE NOT NULL,
          finished_at TIMESTAMP WITH TIME ZONE,
          provider_version_before TEXT,
          provider_version_after TEXT,
          workbook_digest_before TEXT,
          workbook_digest_after TEXT,
          preview_digest TEXT,
          outcome TEXT,
          safe_failure_reason TEXT,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          PRIMARY KEY (sync_run_id),
          CONSTRAINT sync_run_id_is_an_opaque_identifier CHECK (sync_run_id ~
            '^csyr_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT sync_target_id_is_an_opaque_identifier CHECK (sync_target_id ~
            '^csyt_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_sync_run_state_is_known CHECK (state IN ('acknowledged',
            'applied', 'failed', 'previewed', 'started')),
          CONSTRAINT a_constraint_sync_run_outcome_is_known CHECK (outcome IS NULL OR outcome IN
            ('applied', 'failed', 'no_change')),
          CONSTRAINT a_finished_sync_run_records_when_it_finished CHECK ((state IN ('acknowledged',
            'applied', 'failed')) = (finished_at IS NOT NULL)),
          CONSTRAINT a_failed_sync_run_records_its_reason CHECK (state <> 'failed' OR
            safe_failure_reason IS NOT NULL),
          CONSTRAINT a_sync_run_failure_reason_is_bounded CHECK (safe_failure_reason IS NULL OR
            length(trim(safe_failure_reason)) BETWEEN 1 AND 128),
          CONSTRAINT a_sync_run_provider_version_before_is_bounded CHECK (provider_version_before IS
            NULL OR length(trim(provider_version_before)) BETWEEN 1 AND 256),
          CONSTRAINT a_sync_run_provider_version_after_is_bounded CHECK (provider_version_after IS
            NULL OR length(trim(provider_version_after)) BETWEEN 1 AND 256),
          CONSTRAINT a_sync_run_digest_before_is_sha256 CHECK (workbook_digest_before IS NULL OR
            workbook_digest_before ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_sync_run_digest_after_is_sha256 CHECK (workbook_digest_after IS NULL OR
            workbook_digest_after ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_sync_run_preview_digest_is_sha256 CHECK (preview_digest IS NULL OR
            preview_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT constraint_sync_runs_principal_run_is_unique UNIQUE (principal_id,
            sync_run_id),
          CONSTRAINT a_sync_run_belongs_to_a_target_of_its_principal FOREIGN KEY(principal_id,
            sync_target_id) REFERENCES {SCHEMA}.constraint_sync_targets (principal_id,
            sync_target_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_sync_runs_by_principal_target ON {SCHEMA}.constraint_sync_runs
          (principal_id, sync_target_id, started_at)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_sync_baselines (
          sync_target_id TEXT NOT NULL,
          constraint_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          baseline_revision_id TEXT NOT NULL,
          baseline_constraint_version INTEGER NOT NULL,
          baseline_field_digests JSONB NOT NULL,
          baseline_record_digest TEXT NOT NULL,
          workbook_row_identity TEXT NOT NULL,
          verified_provider_version TEXT,
          verified_at TIMESTAMP WITH TIME ZONE NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
          CONSTRAINT one_sync_baseline_per_constraint PRIMARY KEY (sync_target_id, constraint_id),
          CONSTRAINT sync_target_id_is_an_opaque_identifier CHECK (sync_target_id ~
            '^csyt_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT constraint_id_is_an_opaque_identifier CHECK (constraint_id ~
            '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT baseline_revision_id_is_an_opaque_identifier CHECK (baseline_revision_id ~
            '^crev_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_sync_baseline_version_is_positive CHECK (baseline_constraint_version >= 1),
          CONSTRAINT a_sync_baseline_holds_field_digests CHECK (jsonb_typeof(baseline_field_digests)
            = 'object'),
          CONSTRAINT a_sync_baseline_digest_object_is_bounded CHECK
            (pg_column_size(baseline_field_digests) <= 8192),
          CONSTRAINT a_sync_baseline_record_digest_is_sha256 CHECK (baseline_record_digest ~
            '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_sync_baseline_row_identity_is_opaque CHECK
            (length(trim(workbook_row_identity)) BETWEEN 1 AND 256 AND workbook_row_identity !~
            '\\s'),
          CONSTRAINT a_sync_baseline_provider_version_is_bounded CHECK (verified_provider_version IS
            NULL OR length(trim(verified_provider_version)) BETWEEN 1 AND 256),
          CONSTRAINT a_sync_baseline_belongs_to_a_target_of_its_principal FOREIGN KEY(principal_id,
            sync_target_id) REFERENCES {SCHEMA}.constraint_sync_targets (principal_id,
            sync_target_id),
          CONSTRAINT a_sync_baseline_names_a_constraint_of_its_principal FOREIGN KEY(principal_id,
            constraint_id) REFERENCES {SCHEMA}.project_constraints (principal_id, constraint_id),
          CONSTRAINT a_sync_baseline_names_a_revision_of_its_principal FOREIGN KEY(principal_id,
            baseline_revision_id) REFERENCES {SCHEMA}.project_constraint_revisions (principal_id,
            revision_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_sync_baselines_by_principal_target ON
          {SCHEMA}.constraint_sync_baselines (principal_id, sync_target_id)
        """
    )
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.constraint_sync_conflicts (
          sync_conflict_id TEXT NOT NULL,
          principal_id TEXT NOT NULL,
          project_id TEXT NOT NULL,
          sync_target_id TEXT NOT NULL,
          constraint_id TEXT,
          sync_run_id TEXT NOT NULL,
          conflict_kind TEXT NOT NULL,
          field_names JSONB NOT NULL,
          baseline_revision_id TEXT,
          db_version INTEGER,
          provider_version TEXT,
          external_candidate JSONB,
          external_candidate_digest TEXT,
          state TEXT DEFAULT 'open' NOT NULL,
          created_at TIMESTAMP WITH TIME ZONE NOT NULL,
          resolved_at TIMESTAMP WITH TIME ZONE,
          resolution_history_id TEXT,
          PRIMARY KEY (sync_conflict_id),
          CONSTRAINT sync_conflict_id_is_an_opaque_identifier CHECK (sync_conflict_id ~
            '^csyc_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
            '^prn_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
            '^prj_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT sync_target_id_is_an_opaque_identifier CHECK (sync_target_id ~
            '^csyt_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT sync_run_id_is_an_opaque_identifier CHECK (sync_run_id ~
            '^csyr_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_sync_conflict_constraint_is_an_opaque_identifier CHECK (constraint_id IS NULL
            OR constraint_id ~ '^cst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_sync_conflict_revision_is_an_opaque_identifier CHECK (baseline_revision_id IS
            NULL OR baseline_revision_id ~ '^crev_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_sync_conflict_resolution_is_an_opaque_identifier CHECK (resolution_history_id
            IS NULL OR resolution_history_id ~ '^chst_[A-Za-z0-9]{{8,64}}$'),
          CONSTRAINT a_constraint_sync_conflict_kind_is_known CHECK (conflict_kind IN
            ('both_changed', 'deleted_in_canonical', 'deleted_in_external', 'new_in_external')),
          CONSTRAINT a_constraint_sync_conflict_state_is_known CHECK (state IN ('open', 'resolved',
            'superseded')),
          CONSTRAINT a_sync_conflict_names_the_fields_that_diverged CHECK (jsonb_typeof(field_names)
            = 'array'),
          CONSTRAINT a_sync_conflict_field_list_is_bounded CHECK (pg_column_size(field_names) <=
            8192),
          CONSTRAINT a_sync_conflict_external_candidate_is_bounded CHECK (external_candidate IS NULL
            OR (jsonb_typeof(external_candidate) = 'object' AND pg_column_size(external_candidate)
            <= 8192)),
          CONSTRAINT a_sync_conflict_candidate_digest_is_sha256 CHECK (external_candidate_digest IS
            NULL OR external_candidate_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_sync_conflict_provider_version_is_bounded CHECK (provider_version IS NULL OR
            length(trim(provider_version)) BETWEEN 1 AND 256),
          CONSTRAINT a_resolved_sync_conflict_records_when_it_was CHECK ((state = 'resolved') =
            (resolved_at IS NOT NULL)),
          CONSTRAINT a_resolved_sync_conflict_names_its_receipt CHECK (state <> 'resolved' OR
            resolution_history_id IS NOT NULL),
          CONSTRAINT a_sync_conflict_db_version_is_positive CHECK (db_version IS NULL OR db_version
            >= 1),
          CONSTRAINT a_sync_conflict_belongs_to_a_target_of_its_principal FOREIGN KEY(principal_id,
            sync_target_id) REFERENCES {SCHEMA}.constraint_sync_targets (principal_id,
            sync_target_id),
          CONSTRAINT a_sync_conflict_names_a_run_of_its_principal FOREIGN KEY(principal_id,
            sync_run_id) REFERENCES {SCHEMA}.constraint_sync_runs (principal_id, sync_run_id),
          CONSTRAINT a_sync_conflict_names_a_constraint_of_its_principal FOREIGN KEY(principal_id,
            constraint_id) REFERENCES {SCHEMA}.project_constraints (principal_id, constraint_id),
          CONSTRAINT a_sync_conflict_names_a_revision_of_its_principal FOREIGN KEY(principal_id,
            baseline_revision_id) REFERENCES {SCHEMA}.project_constraint_revisions (principal_id,
            revision_id),
          CONSTRAINT a_sync_conflict_names_a_receipt_of_its_principal FOREIGN KEY(principal_id,
            resolution_history_id) REFERENCES {SCHEMA}.project_constraint_history (principal_id,
            history_id),
          FOREIGN KEY(project_id) REFERENCES {SCHEMA}.projects (project_id)
        )
        """
    )
    op.execute(
        f"""
        CREATE INDEX constraint_sync_conflicts_by_principal_target_state ON
          {SCHEMA}.constraint_sync_conflicts (principal_id, sync_target_id, state)
        """
    )
    op.execute(
        f"""
        CREATE UNIQUE INDEX one_open_constraint_sync_conflict_per_kind ON
          {SCHEMA}.constraint_sync_conflicts (sync_target_id, constraint_id, conflict_kind) WHERE
          state = 'open' AND constraint_id IS NOT NULL
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.project_constraints ADD CONSTRAINT
          a_constraint_names_its_current_revision FOREIGN KEY(principal_id, current_revision_id)
          REFERENCES {SCHEMA}.project_constraint_revisions (principal_id, revision_id) DEFERRABLE
          INITIALLY DEFERRED
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.project_constraint_revisions ADD CONSTRAINT
          a_constraint_revision_cites_the_receipt_that_wrote_it FOREIGN KEY(principal_id,
          history_id) REFERENCES {SCHEMA}.project_constraint_history (principal_id, history_id)
          DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.project_constraint_history ADD CONSTRAINT
          a_constraint_receipt_names_the_revision_it_wrote FOREIGN KEY(principal_id, revision_id)
          REFERENCES {SCHEMA}.project_constraint_revisions (principal_id, revision_id) DEFERRABLE
          INITIALLY DEFERRED
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.constraint_sync_targets ADD CONSTRAINT
          a_sync_target_names_a_verified_run_of_its_principal FOREIGN KEY(principal_id,
          last_verified_sync_run_id) REFERENCES {SCHEMA}.constraint_sync_runs (principal_id,
          sync_run_id) DEFERRABLE INITIALLY DEFERRED
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.constraint_sync_targets ADD CONSTRAINT
          a_sync_target_names_an_active_run_of_its_principal FOREIGN KEY(principal_id,
          active_run_id) REFERENCES {SCHEMA}.constraint_sync_runs (principal_id, sync_run_id)
          DEFERRABLE INITIALLY DEFERRED
        """
    )
    for table in _IMMUTABLE_TABLES:
        _immutable(table)


def downgrade() -> None:
    for table in reversed(_IMMUTABLE_TABLES):
        op.execute(f"DROP TRIGGER {table}_are_immutable ON {SCHEMA}.{table}")
    for table, name in reversed(_DEFERRED_FOREIGN_KEYS):
        op.execute(f'ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT "{name}"')
    for table in reversed(_CREATED_TABLES):
        op.execute(f"DROP TABLE {SCHEMA}.{table} RESTRICT")
