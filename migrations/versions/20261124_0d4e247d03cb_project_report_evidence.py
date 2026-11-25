"""Project report evidence: raw exports, derivations and bindings (project reports WP3P-S3).

Revision ID: 0d4e247d03cb
Revises: 61fafdfd2986
Create Date: 2026-11-24

The one additive revision of project reports WP3P, on the sole head
`61fafdfd2986` (Manager rulings D1, D2, D6, D10, D11 and D13; design report
section 3.2). It alters nothing that existed before it. In order it:

1. sets `lock_timeout` to 10 s for this revision's transaction only
   (`SET LOCAL`), so a lock that cannot be taken aborts the whole revision with
   `55P03` and leaves the database at `61fafdfd2986`; then takes every lock the
   revision needs up front, in one fixed order (the downgrade's order for the
   tables both lock): `SHARE ROW EXCLUSIVE` on `ingest_sources`,
   `ingest_snapshots` and `projects`, the only existing tables it touches, and
   only as foreign-key targets;
2. creates twelve Principal-partitioned tables in `knowledge`:
   * `project_report_binding_revisions` -- one append-only revision of one
     folder's binding to one Project (`prbnd_`): the declared project number,
     `active` or `retired`, the currency, the change set's SHA-256, the reason
     code and `recorded_by = operator_cli` (D6: the revisions are the audit).
     `supersedes_revision_id` names the revision of the same source it
     replaces, at most once, and only one that already exists when the row is
     inserted (a BEFORE INSERT trigger: the B1 cycle fix); each source has one
     first revision (a partial unique index), so each source's chain is
     linear and acyclic and exactly one revision of it is unsuperseded;
   * `project_report_filter_declarations` -- an operator's declaration of what
     one saved report filters, against one revision (append-only);
   * `project_report_bindings` -- the one binding pointer per source. Only
     `binding_revision_id`, `project_id` and `state` change, and only to the
     revision that supersedes the current one; the pointer always equals the
     revision it names (one composite foreign key); DELETE is refused; at most
     one `active` pointer per Project (a partial unique index); a new pointer
     names a revision nothing supersedes (a BEFORE INSERT trigger, N2). As the
     chain is acyclic the pointer can only ever move forward, never oscillate;
   * `project_report_snapshots` -- Layer A head (D1): the byte-exact header and
     reconstruction facts of one lifecycle snapshot, whose `file_sha256` is the
     lifecycle digest through `(snapshot_id, principal_id, file_sha256)` and
     whose `reconstruction_sha256` must equal it;
   * `project_report_rows` -- Layer A raw rows, classification-free: the exact
     record text, its terminator and its cells;
   * `project_report_derivations` -- one append-only, rebuildable derivation of
     a snapshot (`prdrv_`) under one adapter and one binding revision;
     `classified` or `quarantined` (D11), superseded at most once by a later
     derivation of the same snapshot, and only by one inserted after it (a
     BEFORE INSERT trigger: the B1 cycle fix). "Current" is the one nothing
     supersedes (D10: no mutable latest pointer). Each snapshot has one first
     derivation (a partial unique index), so its chain is linear and acyclic
     and exactly one derivation of it is current;
   * `project_report_row_roles` -- each data row's role in one derivation;
     each `group_path` step is `[level (1 or 2), key text, header ordinal >= 1]`
     (a CHECK). That a quarantined derivation holds no row roles is enforced
     by the application, not here;
   * `project_report_records` -- the family-local record identities
     (`prrec_`), keyed by Project, family, identity key and identity version;
   * `project_report_lines` -- Layer B head (D2): one generic line per detail
     row of a derivation;
   * `project_report_line_values` -- the typed cells of a line over a closed
     per-family field catalogue: the raw text always, and exactly the column of
     its value kind (money and numbers `NUMERIC(20,4)`) or none;
   * `project_report_stated_totals` -- each group or grand total cell with its
     recomputed detail sum and its reconciliation outcome;
   * `project_report_cross_checks` -- one cross-report check between two
     derivations of one Project, in fixed roles: the left side is the buyout
     summary derivation and the right the change-order reconciliation (a
     BEFORE INSERT trigger, N1), so `(A, B)` and `(B, A)` cannot both exist.
     A `mismatch` may carry two equal values (a refused part is excluded from
     the computed sum, the domain `compare` rule), as may a stated total's, so
     no CHECK requires a mismatch's values to differ;
3. creates the indexes of design section 3.2 and the foreign-key lookups. No
   trigram index (the WP3a M1 precedent: the text index belongs to the read
   package);
4. creates the view `project_report_current_derivations`: every derivation no
   later derivation supersedes, so a reader cannot count a superseded one;
5. creates the guards: the pointer's named-mutable guard; the two
   supersede-an-existing-row guards (binding revisions and derivations); the
   pointer's insert guard; the cross-check role guard; one shared append-only
   refusal on the eleven tables other than the binding pointer; and
   `TRUNCATE` refusal on all twelve (the `c8e4a1b70d35` precedent). Every
   refusal is `restrict_violation`; the four insert guards name themselves as
   the error's constraint.

Every foreign key is composite with `principal_id` and `ON DELETE RESTRICT`.
Raw export text (names, descriptions, minutes) is held in the Layer A rows and
in the line values as source evidence; no capability reads it in this package.
Money is source evidence only: nothing here writes a value to any
product-owned record (D13).

Every bound is a frozen literal and this revision imports nothing from the live
domain. No capability, no purpose, no audit vocabulary restatement and no
lifecycle vocabulary change. No `GRANT`, no `REVOKE`, no backfill.

`downgrade` locks the twelve tables and the three referenced tables `ACCESS
EXCLUSIVE` (a dropped foreign key takes that lock on its target) and refuses
with `restrict_violation`, deleting nothing, while any of the twelve holds a
row; otherwise it drops exactly what `upgrade` created, in reverse order.

Applying this revision to a persistent, shared or production database requires
separate operator authority; nothing here grants it.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "0d4e247d03cb"
down_revision: str | None = "61fafdfd2986"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_LOCK_TIMEOUT: Final = "SET LOCAL lock_timeout = '10s'"

#: The existing tables the new foreign keys reference, in the downgrade's order.
#: Creating a foreign key takes `SHARE ROW EXCLUSIVE` on its target; taking it
#: first means no lock is added mid-revision.
_LOCK_REFERENCED: Final = (
    "LOCK TABLE knowledge.ingest_sources, knowledge.ingest_snapshots, knowledge.projects "
    "IN SHARE ROW EXCLUSIVE MODE"
)

# ---- step 2: the tables ---------------------------------------------------------

#: Not f-strings: the regex quantifiers `{8,64}` must reach the server verbatim.
_BINDING_REVISIONS_DDL: Final = """
    CREATE TABLE knowledge.project_report_binding_revisions (
      binding_revision_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      project_id TEXT NOT NULL,
      declared_project_number TEXT NOT NULL,
      state TEXT NOT NULL,
      supersedes_revision_id TEXT,
      currency TEXT NOT NULL,
      recorded_at TIMESTAMP WITH TIME ZONE NOT NULL,
      recorded_by TEXT NOT NULL,
      change_set_sha256 TEXT NOT NULL,
      reason_code TEXT NOT NULL,
      PRIMARY KEY (binding_revision_id),
      CONSTRAINT binding_revision_id_is_an_opaque_identifier CHECK (binding_revision_id ~
          '^prbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
          '^prj_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT supersedes_revision_id_is_an_opaque_identifier CHECK (supersedes_revision_id
          ~ '^prbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_binding_revision_project_number_is_bounded CHECK
          (length(declared_project_number) BETWEEN 1 AND 200 AND
          length(trim(declared_project_number)) > 0),
      CONSTRAINT a_binding_revision_state_is_known CHECK (state IN ('active', 'retired')),
      CONSTRAINT a_binding_revision_does_not_supersede_itself CHECK (supersedes_revision_id
          IS NULL OR supersedes_revision_id <> binding_revision_id),
      CONSTRAINT a_retired_binding_revision_supersedes_one CHECK (state <> 'retired' OR
          supersedes_revision_id IS NOT NULL),
      CONSTRAINT a_binding_revision_currency_is_a_code CHECK (currency ~ '^[A-Z]{3}$'),
      CONSTRAINT a_binding_revision_is_recorded_by_the_operator_cli CHECK (recorded_by =
          'operator_cli'),
      CONSTRAINT a_binding_revision_change_set_is_sha256 CHECK (change_set_sha256 ~
          '^[0-9a-f]{64}$'),
      CONSTRAINT a_binding_revision_reason_is_known CHECK (reason_code IN ('add',
          'correction', 'filter_update', 'initial', 'retire')),
      CONSTRAINT one_binding_revision_supersedes_each UNIQUE (principal_id,
          supersedes_revision_id),
      CONSTRAINT a_binding_revision_is_identified_within_its_principal UNIQUE
          (binding_revision_id, principal_id),
      CONSTRAINT a_binding_revision_is_identified_within_its_source UNIQUE
          (binding_revision_id, principal_id, ingest_source_id),
      CONSTRAINT a_binding_revision_is_identified_within_its_project UNIQUE
          (binding_revision_id, principal_id, ingest_source_id, project_id),
      CONSTRAINT a_binding_revision_is_identified_with_its_state UNIQUE
          (binding_revision_id, principal_id, ingest_source_id, project_id, state),
      CONSTRAINT a_binding_revision_names_a_source_of_its_principal FOREIGN
          KEY(ingest_source_id, principal_id) REFERENCES knowledge.ingest_sources
          (ingest_source_id, principal_id) ON DELETE RESTRICT,
      CONSTRAINT a_binding_revision_names_a_project_of_its_principal FOREIGN KEY(project_id,
          principal_id) REFERENCES knowledge.projects (project_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT a_binding_revision_supersedes_a_revision_of_its_source FOREIGN
          KEY(supersedes_revision_id, principal_id, ingest_source_id) REFERENCES
          knowledge.project_report_binding_revisions (binding_revision_id, principal_id,
          ingest_source_id) ON DELETE RESTRICT
    )
    """

_FILTER_DECLARATIONS_DDL: Final = """
    CREATE TABLE knowledge.project_report_filter_declarations (
      principal_id TEXT NOT NULL,
      binding_revision_id TEXT NOT NULL,
      slug_label TEXT NOT NULL,
      description TEXT NOT NULL,
      declared_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT project_report_filter_declarations_pkey PRIMARY KEY (principal_id,
          binding_revision_id, slug_label),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT binding_revision_id_is_an_opaque_identifier CHECK (binding_revision_id ~
          '^prbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_filter_declaration_slug_is_bounded CHECK (length(slug_label) BETWEEN 1 AND
          200 AND strpos(slug_label, '/') = 0 AND slug_label !~ '[[:cntrl:]]'),
      CONSTRAINT a_filter_declaration_description_is_bounded CHECK (char_length(description)
          BETWEEN 1 AND 500 AND length(trim(description)) > 0),
      CONSTRAINT a_filter_declaration_names_a_revision_of_its_principal FOREIGN
          KEY(binding_revision_id, principal_id) REFERENCES
          knowledge.project_report_binding_revisions (binding_revision_id, principal_id) ON
          DELETE RESTRICT
    )
    """

_BINDINGS_DDL: Final = """
    CREATE TABLE knowledge.project_report_bindings (
      principal_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      binding_revision_id TEXT NOT NULL,
      project_id TEXT NOT NULL,
      state TEXT NOT NULL,
      CONSTRAINT project_report_bindings_pkey PRIMARY KEY (principal_id, ingest_source_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT binding_revision_id_is_an_opaque_identifier CHECK (binding_revision_id ~
          '^prbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
          '^prj_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_binding_state_is_known CHECK (state IN ('active', 'retired')),
      CONSTRAINT a_binding_names_a_source_of_its_principal FOREIGN KEY(ingest_source_id,
          principal_id) REFERENCES knowledge.ingest_sources (ingest_source_id, principal_id) ON
          DELETE RESTRICT,
      CONSTRAINT a_binding_names_a_project_of_its_principal FOREIGN KEY(project_id,
          principal_id) REFERENCES knowledge.projects (project_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT a_binding_equals_the_revision_it_names FOREIGN KEY(binding_revision_id,
          principal_id, ingest_source_id, project_id, state) REFERENCES
          knowledge.project_report_binding_revisions (binding_revision_id, principal_id,
          ingest_source_id, project_id, state) ON DELETE RESTRICT
    )
    """

_SNAPSHOTS_DDL: Final = """
    CREATE TABLE knowledge.project_report_snapshots (
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      file_sha256 TEXT NOT NULL,
      bom_present BOOLEAN NOT NULL,
      header_raw_record TEXT NOT NULL,
      header_terminator TEXT NOT NULL,
      header_cells JSONB NOT NULL,
      header_signature TEXT NOT NULL,
      signature_version TEXT NOT NULL,
      reader_version TEXT NOT NULL,
      data_row_count INTEGER NOT NULL,
      embedded_line_break_count INTEGER NOT NULL,
      reconstruction_sha256 TEXT NOT NULL,
      CONSTRAINT project_report_snapshots_pkey PRIMARY KEY (principal_id, snapshot_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_report_snapshot_digest_is_sha256 CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
      CONSTRAINT a_report_snapshot_signature_is_sha256 CHECK (header_signature ~
          '^[0-9a-f]{64}$'),
      CONSTRAINT a_report_snapshot_reconstruction_is_sha256 CHECK (reconstruction_sha256 ~
          '^[0-9a-f]{64}$'),
      CONSTRAINT a_report_snapshot_reconstructs_its_file CHECK (reconstruction_sha256 =
          file_sha256),
      CONSTRAINT a_report_snapshot_header_is_not_empty CHECK (length(header_raw_record) >= 1),
      CONSTRAINT a_report_snapshot_header_terminator_is_known CHECK (header_terminator IN
          ('cr', 'crlf', 'lf', 'none')),
      CONSTRAINT only_a_header_only_report_snapshot_lacks_a_terminator CHECK
          (header_terminator <> 'none' OR data_row_count = 0),
      CONSTRAINT a_report_snapshot_header_cells_is_a_non_empty_array CHECK
          (jsonb_typeof(header_cells) = 'array' AND jsonb_array_length(header_cells) >= 1),
      CONSTRAINT a_report_snapshot_signature_version_is_a_token CHECK (signature_version ~
          '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_report_snapshot_reader_version_is_a_token CHECK (reader_version ~
          '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_report_snapshot_count_is_non_negative CHECK (data_row_count >= 0 AND
          embedded_line_break_count >= 0),
      CONSTRAINT a_report_snapshot_is_identified_within_its_source UNIQUE (principal_id,
          snapshot_id, ingest_source_id),
      CONSTRAINT a_report_snapshot_names_a_lifecycle_snapshot_of_its_digest FOREIGN
          KEY(snapshot_id, principal_id, file_sha256) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id, file_sha256) ON DELETE RESTRICT,
      CONSTRAINT a_report_snapshot_names_a_lifecycle_snapshot_of_its_source FOREIGN
          KEY(snapshot_id, principal_id, ingest_source_id) REFERENCES knowledge.ingest_snapshots
          (snapshot_id, principal_id, ingest_source_id) ON DELETE RESTRICT
    )
    """

_ROWS_DDL: Final = """
    CREATE TABLE knowledge.project_report_rows (
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      row_ordinal INTEGER NOT NULL,
      raw_record TEXT NOT NULL,
      terminator TEXT NOT NULL,
      cells JSONB NOT NULL,
      width_matches BOOLEAN NOT NULL,
      CONSTRAINT project_report_rows_pkey PRIMARY KEY (principal_id, snapshot_id,
          row_ordinal),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_report_row_ordinal_is_positive CHECK (row_ordinal >= 1),
      CONSTRAINT a_report_row_terminator_is_known CHECK (terminator IN ('cr', 'crlf', 'lf',
          'none')),
      CONSTRAINT a_report_row_cells_is_a_non_empty_array CHECK (jsonb_typeof(cells) = 'array'
          AND jsonb_array_length(cells) >= 1),
      CONSTRAINT a_report_row_names_a_snapshot_of_its_principal FOREIGN KEY(principal_id,
          snapshot_id) REFERENCES knowledge.project_report_snapshots (principal_id,
          snapshot_id) ON DELETE RESTRICT
    )
    """

_DERIVATIONS_DDL: Final = """
    CREATE TABLE knowledge.project_report_derivations (
      derivation_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      snapshot_id TEXT NOT NULL,
      ingest_source_id TEXT NOT NULL,
      binding_revision_id TEXT NOT NULL,
      project_id TEXT NOT NULL,
      state TEXT NOT NULL,
      quarantine_reason TEXT,
      record_family TEXT,
      family_view TEXT,
      adapter_version TEXT,
      identity_version TEXT NOT NULL,
      status_map_version TEXT NOT NULL,
      completeness_class TEXT,
      role_counts JSONB NOT NULL,
      reconciliation JSONB,
      trigger TEXT NOT NULL,
      supersedes_derivation_id TEXT,
      derived_at TIMESTAMP WITH TIME ZONE NOT NULL,
      PRIMARY KEY (derivation_id),
      CONSTRAINT derivation_id_is_an_opaque_identifier CHECK (derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT ingest_source_id_is_an_opaque_identifier CHECK (ingest_source_id ~
          '^isrc_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT binding_revision_id_is_an_opaque_identifier CHECK (binding_revision_id ~
          '^prbnd_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
          '^prj_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT supersedes_derivation_id_is_an_opaque_identifier CHECK
          (supersedes_derivation_id ~ '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_derivation_state_is_known CHECK (state IN ('classified', 'quarantined')),
      CONSTRAINT a_derivation_quarantine_reason_is_known CHECK (quarantine_reason IS NULL OR
          quarantine_reason IN ('binding_project_number_mismatch', 'malformed_ratio_exceeded',
          'unknown_header_signature')),
      CONSTRAINT a_quarantined_derivation_names_its_reason CHECK ((state = 'quarantined') =
          (quarantine_reason IS NOT NULL)),
      CONSTRAINT a_derivation_family_is_known CHECK (record_family IS NULL OR record_family IN
          ('budget_changes', 'buyout', 'change_order_reconciliation', 'coordination_issues',
          'daily_log', 'meeting_items', 'observations', 'rfis')),
      CONSTRAINT a_derivation_view_is_known CHECK (family_view IS NULL OR family_view IN
          ('buyout_summary', 'by_code', 'by_status', 'delays', 'grouped_by_change',
          'linked_to_drawings', 'manpower', 'notes', 'oac', 'open_by_vendor',
          'open_outstanding', 'recently_closed', 'reconciliation', 'weather',
          'with_date_closed')),
      CONSTRAINT a_derivation_view_belongs_to_its_family CHECK (family_view IS NULL OR
          (record_family, family_view) IN (('meeting_items', 'oac'), ('observations',
          'with_date_closed'), ('observations', 'open_by_vendor'), ('coordination_issues',
          'by_status'), ('rfis', 'linked_to_drawings'), ('rfis', 'open_outstanding'), ('rfis',
          'recently_closed'), ('budget_changes', 'grouped_by_change'), ('budget_changes',
          'by_code'), ('buyout', 'buyout_summary'), ('change_order_reconciliation',
          'reconciliation'), ('daily_log', 'delays'), ('daily_log', 'manpower'), ('daily_log',
          'notes'), ('daily_log', 'weather'))),
      CONSTRAINT a_derivation_adapter_is_whole CHECK ((record_family IS NULL) = (family_view
          IS NULL) AND (family_view IS NULL) = (adapter_version IS NULL)),
      CONSTRAINT a_derivation_names_its_adapter_unless_its_signature_is_unknown CHECK
          ((record_family IS NULL) = coalesce(quarantine_reason = 'unknown_header_signature',
          false)),
      CONSTRAINT a_derivation_adapter_version_is_a_token CHECK (adapter_version IS NULL OR
          adapter_version ~ '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_derivation_identity_version_is_a_token CHECK (identity_version ~
          '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_derivation_status_map_version_is_a_token CHECK (status_map_version ~
          '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_derivation_completeness_is_known CHECK (completeness_class IS NULL OR
          completeness_class IN ('grouping_only', 'populated', 'valid_empty')),
      CONSTRAINT a_classified_derivation_names_its_completeness CHECK ((completeness_class IS
          NULL) = (state = 'quarantined')),
      CONSTRAINT a_derivation_role_counts_are_counts CHECK (jsonb_typeof(role_counts) =
          'object' AND NOT jsonb_path_exists(role_counts, '$.* ? (@.type() != "number" || @ <
          0 || @ != @.floor())')),
      CONSTRAINT a_derivation_role_counts_name_its_roles CHECK ((state = 'quarantined' AND
          role_counts ? 'unclassified' AND role_counts - 'unclassified' = '{}'::jsonb) OR
          (state = 'classified' AND role_counts - ARRAY['detail', 'grand_total',
          'group_header', 'grouping_only', 'malformed', 'spacer']::text[] = '{}'::jsonb)),
      CONSTRAINT a_derivation_reconciliation_is_an_object_when_classified CHECK
          ((reconciliation IS NULL) = (state = 'quarantined') AND (reconciliation IS NULL OR
          jsonb_typeof(reconciliation) = 'object')),
      CONSTRAINT a_derivation_trigger_is_known CHECK (trigger IN ('ingest',
          'operator_rebuild', 'rederive_adapter', 'rederive_binding', 'rederive_version')),
      CONSTRAINT only_a_first_derivation_is_an_ingest CHECK ((supersedes_derivation_id IS
          NULL) = (trigger = 'ingest')),
      CONSTRAINT a_derivation_does_not_supersede_itself CHECK (supersedes_derivation_id IS
          NULL OR supersedes_derivation_id <> derivation_id),
      CONSTRAINT one_derivation_supersedes_each UNIQUE (principal_id,
          supersedes_derivation_id),
      CONSTRAINT a_derivation_is_identified_within_its_principal UNIQUE (derivation_id,
          principal_id),
      CONSTRAINT a_derivation_is_identified_within_its_snapshot UNIQUE (derivation_id,
          principal_id, snapshot_id),
      CONSTRAINT a_derivation_is_identified_within_its_project UNIQUE (derivation_id,
          principal_id, project_id),
      CONSTRAINT a_derivation_is_identified_with_its_view UNIQUE (derivation_id,
          principal_id, project_id, record_family, family_view),
      CONSTRAINT a_derivation_names_a_report_snapshot_of_its_source FOREIGN KEY(principal_id,
          snapshot_id, ingest_source_id) REFERENCES knowledge.project_report_snapshots
          (principal_id, snapshot_id, ingest_source_id) ON DELETE RESTRICT,
      CONSTRAINT a_derivation_names_a_binding_revision_of_its_source FOREIGN
          KEY(binding_revision_id, principal_id, ingest_source_id, project_id) REFERENCES
          knowledge.project_report_binding_revisions (binding_revision_id, principal_id,
          ingest_source_id, project_id) ON DELETE RESTRICT,
      CONSTRAINT a_derivation_supersedes_a_derivation_of_its_snapshot FOREIGN
          KEY(supersedes_derivation_id, principal_id, snapshot_id) REFERENCES
          knowledge.project_report_derivations (derivation_id, principal_id, snapshot_id) ON
          DELETE RESTRICT
    )
    """

_ROW_ROLES_DDL: Final = """
    CREATE TABLE knowledge.project_report_row_roles (
      principal_id TEXT NOT NULL,
      derivation_id TEXT NOT NULL,
      row_ordinal INTEGER NOT NULL,
      snapshot_id TEXT NOT NULL,
      row_role TEXT NOT NULL,
      row_reason TEXT,
      group_level SMALLINT,
      group_key TEXT,
      group_path JSONB NOT NULL,
      parent_header_ordinal INTEGER,
      CONSTRAINT project_report_row_roles_pkey PRIMARY KEY (principal_id, derivation_id,
          row_ordinal),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT derivation_id_is_an_opaque_identifier CHECK (derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT snapshot_id_is_an_opaque_identifier CHECK (snapshot_id ~
          '^isnp_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_row_role_ordinal_is_positive CHECK (row_ordinal >= 1),
      CONSTRAINT a_row_role_is_known CHECK (row_role IN ('detail', 'grand_total',
          'group_header', 'grouping_only', 'malformed', 'spacer')),
      CONSTRAINT a_row_role_reason_is_a_malformed_width CHECK (row_reason IS NULL OR (row_role
          = 'malformed' AND row_reason IN ('width_mismatch'))),
      CONSTRAINT a_row_role_group_level_is_one_or_two CHECK (group_level IS NULL OR
          group_level IN (1, 2)),
      CONSTRAINT a_row_role_header_names_its_level_and_key CHECK ((group_level IS NOT NULL) =
          (row_role IN ('group_header', 'grouping_only')) AND (group_key IS NOT NULL) =
          (row_role IN ('group_header', 'grouping_only'))),
      CONSTRAINT a_row_role_group_path_is_an_array CHECK (jsonb_typeof(group_path) =
          'array'),
      CONSTRAINT a_row_role_group_path_steps_are_level_key_and_header CHECK (NOT
          jsonb_path_exists(group_path, 'strict $[*] ? (@.type() != "array" || @.size() != 3
          || @[0].type() != "number" || @[1].type() != "string" || @[2].type() != "number" ||
          (@[0] != 1 && @[0] != 2) || @[2] < 1 || @[2] != @[2].floor())', '{}', true)),
      CONSTRAINT a_row_role_parent_header_precedes_it CHECK (parent_header_ordinal IS NULL OR
          (parent_header_ordinal >= 1 AND parent_header_ordinal < row_ordinal)),
      CONSTRAINT a_row_role_is_identified_with_its_role UNIQUE (principal_id, derivation_id,
          row_ordinal, row_role),
      CONSTRAINT a_row_role_names_a_derivation_of_its_snapshot FOREIGN KEY(derivation_id,
          principal_id, snapshot_id) REFERENCES knowledge.project_report_derivations
          (derivation_id, principal_id, snapshot_id) ON DELETE RESTRICT,
      CONSTRAINT a_row_role_names_a_raw_row_of_its_snapshot FOREIGN KEY(principal_id,
          snapshot_id, row_ordinal) REFERENCES knowledge.project_report_rows (principal_id,
          snapshot_id, row_ordinal) ON DELETE RESTRICT
    )
    """

_RECORDS_DDL: Final = """
    CREATE TABLE knowledge.project_report_records (
      record_id TEXT NOT NULL,
      principal_id TEXT NOT NULL,
      project_id TEXT NOT NULL,
      record_family TEXT NOT NULL,
      identity_key TEXT NOT NULL,
      identity_version TEXT NOT NULL,
      identity_basis TEXT NOT NULL,
      created_by_derivation_id TEXT NOT NULL,
      PRIMARY KEY (record_id),
      CONSTRAINT record_id_is_an_opaque_identifier CHECK (record_id ~
          '^prrec_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
          '^prj_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT created_by_derivation_id_is_an_opaque_identifier CHECK
          (created_by_derivation_id ~ '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_report_record_family_is_known CHECK (record_family IN ('budget_changes',
          'buyout', 'change_order_reconciliation', 'coordination_issues', 'daily_log',
          'meeting_items', 'observations', 'rfis')),
      CONSTRAINT a_report_record_identity_key_is_bounded CHECK (length(identity_key) BETWEEN 3
          AND 2000 AND identity_key ~ '^[a-z][a-z_]{0,31}[:]'),
      CONSTRAINT a_report_record_identity_version_is_a_token CHECK (identity_version ~
          '^[a-z0-9][a-z0-9_.-]{0,63}$'),
      CONSTRAINT a_report_record_identity_basis_is_known CHECK (identity_basis IN
          ('exported_composite', 'exported_number', 'exported_number_normalized')),
      CONSTRAINT one_report_record_per_identity UNIQUE (principal_id, project_id,
          record_family, identity_key, identity_version),
      CONSTRAINT a_report_record_is_identified_within_its_project UNIQUE (record_id,
          principal_id, project_id, record_family),
      CONSTRAINT a_report_record_names_a_project_of_its_principal FOREIGN KEY(project_id,
          principal_id) REFERENCES knowledge.projects (project_id, principal_id) ON DELETE
          RESTRICT,
      CONSTRAINT a_report_record_names_a_derivation_of_its_project FOREIGN
          KEY(created_by_derivation_id, principal_id, project_id) REFERENCES
          knowledge.project_report_derivations (derivation_id, principal_id, project_id) ON
          DELETE RESTRICT
    )
    """

_LINES_DDL: Final = """
    CREATE TABLE knowledge.project_report_lines (
      principal_id TEXT NOT NULL,
      derivation_id TEXT NOT NULL,
      row_ordinal INTEGER NOT NULL,
      row_role TEXT NOT NULL,
      project_id TEXT NOT NULL,
      record_family TEXT NOT NULL,
      family_view TEXT NOT NULL,
      line_kind TEXT NOT NULL,
      record_id TEXT,
      identity_state TEXT NOT NULL,
      identity_reason TEXT,
      observation_state TEXT NOT NULL,
      degraded_reasons TEXT[] NOT NULL,
      status_raw TEXT,
      status_class TEXT,
      identifier_prefix TEXT,
      identifier_numeric_suffix BIGINT,
      CONSTRAINT project_report_lines_pkey PRIMARY KEY (principal_id, derivation_id,
          row_ordinal),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT derivation_id_is_an_opaque_identifier CHECK (derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
          '^prj_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT record_id_is_an_opaque_identifier CHECK (record_id ~
          '^prrec_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_report_line_is_a_detail_row CHECK (row_role = 'detail'),
      CONSTRAINT a_report_line_family_is_known CHECK (record_family IN ('budget_changes',
          'buyout', 'change_order_reconciliation', 'coordination_issues', 'daily_log',
          'meeting_items', 'observations', 'rfis')),
      CONSTRAINT a_report_line_view_is_known CHECK (family_view IN ('buyout_summary',
          'by_code', 'by_status', 'delays', 'grouped_by_change', 'linked_to_drawings',
          'manpower', 'notes', 'oac', 'open_by_vendor', 'open_outstanding', 'recently_closed',
          'reconciliation', 'weather', 'with_date_closed')),
      CONSTRAINT a_report_line_kind_is_known CHECK (line_kind IN ('budget_change',
          'budget_change_line', 'budget_line', 'commitment', 'commitment_change_order',
          'commitment_co_line', 'delay', 'issue', 'item', 'manpower', 'note', 'observation',
          'prime_change_order', 'prime_pco_line', 'rfi_drawing_link', 'rfi_row',
          'vendor_only', 'weather')),
      CONSTRAINT a_report_line_identity_state_is_known CHECK (identity_state IN
          ('ambiguous_identity', 'identified', 'identity_missing', 'snapshot_scoped')),
      CONSTRAINT a_report_line_identity_reason_is_known CHECK (identity_reason IS NULL OR
          identity_reason IN ('ambiguous_commitment_co', 'ambiguous_identity',
          'identity_missing')),
      CONSTRAINT an_identified_report_line_names_its_record CHECK ((record_id IS NOT NULL) =
          (identity_state = 'identified')),
      CONSTRAINT a_report_line_observation_state_is_known CHECK (observation_state IN
          ('degraded', 'typed')),
      CONSTRAINT a_report_line_degraded_reason_is_known CHECK (degraded_reasons <@
          ARRAY['more_than_4_decimals', 'type_error']),
      CONSTRAINT a_degraded_report_line_names_its_reasons CHECK ((observation_state =
          'degraded') = (cardinality(degraded_reasons) > 0)),
      CONSTRAINT a_report_line_status_class_is_known CHECK (status_class IS NULL OR
          status_class IN ('approved', 'closed', 'open', 'pending', 'unknown', 'void')),
      CONSTRAINT a_report_line_status_text_has_a_class CHECK (status_raw IS NULL OR
          status_class IS NOT NULL),
      CONSTRAINT a_report_line_identifier_suffix_is_non_negative CHECK
          (identifier_numeric_suffix IS NULL OR identifier_numeric_suffix >= 0),
      CONSTRAINT a_report_line_identifier_prefix_has_a_suffix CHECK (identifier_prefix IS
          NULL OR identifier_numeric_suffix IS NOT NULL),
      CONSTRAINT a_report_line_names_a_detail_row_of_its_derivation FOREIGN KEY(principal_id,
          derivation_id, row_ordinal, row_role) REFERENCES knowledge.project_report_row_roles
          (principal_id, derivation_id, row_ordinal, row_role) ON DELETE RESTRICT,
      CONSTRAINT a_report_line_names_a_derivation_of_its_view FOREIGN KEY(derivation_id,
          principal_id, project_id, record_family, family_view) REFERENCES
          knowledge.project_report_derivations (derivation_id, principal_id, project_id,
          record_family, family_view) ON DELETE RESTRICT,
      CONSTRAINT a_report_line_names_a_record_of_its_project FOREIGN KEY(record_id,
          principal_id, project_id, record_family) REFERENCES knowledge.project_report_records
          (record_id, principal_id, project_id, record_family) ON DELETE RESTRICT
    )
    """

_LINE_VALUES_DDL: Final = """
    CREATE TABLE knowledge.project_report_line_values (
      principal_id TEXT NOT NULL,
      derivation_id TEXT NOT NULL,
      row_ordinal INTEGER NOT NULL,
      field_key TEXT NOT NULL,
      value_kind TEXT NOT NULL,
      raw_text TEXT NOT NULL,
      value_reason TEXT,
      value_decimal NUMERIC(20, 4),
      value_date DATE,
      value_boolean BOOLEAN,
      value_text TEXT,
      CONSTRAINT project_report_line_values_pkey PRIMARY KEY (principal_id, derivation_id,
          row_ordinal, field_key),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT derivation_id_is_an_opaque_identifier CHECK (derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_line_value_field_key_is_a_catalogue_key CHECK (field_key ~
          '^[a-z][a-z0-9_]{0,63}[.][a-z][a-z0-9_]{0,63}$'),
      CONSTRAINT a_line_value_kind_is_known CHECK (value_kind IN ('boolean', 'date',
          'identifier', 'money', 'number', 'text')),
      CONSTRAINT a_line_value_reason_is_known CHECK (value_reason IS NULL OR value_reason IN
          ('more_than_4_decimals', 'type_error')),
      CONSTRAINT a_line_value_reason_needs_its_text CHECK (value_reason IS NULL OR raw_text <>
          ''),
      CONSTRAINT a_line_value_is_held_only_by_its_kinds_column CHECK ((value_kind IN ('money',
          'number') OR value_decimal IS NULL) AND (value_kind = 'date' OR value_date IS NULL)
          AND (value_kind = 'boolean' OR value_boolean IS NULL) AND (value_kind IN
          ('identifier', 'text') OR value_text IS NULL)),
      CONSTRAINT a_line_value_is_typed_exactly_when_its_text_parses CHECK
          ((num_nonnulls(value_decimal, value_date, value_boolean, value_text) = 1) = (raw_text
          <> '' AND value_reason IS NULL)),
      CONSTRAINT a_line_text_value_is_its_raw_text CHECK (value_text IS NULL OR value_text =
          raw_text),
      CONSTRAINT a_line_value_names_a_line_of_its_derivation FOREIGN KEY(principal_id,
          derivation_id, row_ordinal) REFERENCES knowledge.project_report_lines (principal_id,
          derivation_id, row_ordinal) ON DELETE RESTRICT
    )
    """

_STATED_TOTALS_DDL: Final = """
    CREATE TABLE knowledge.project_report_stated_totals (
      principal_id TEXT NOT NULL,
      derivation_id TEXT NOT NULL,
      row_ordinal INTEGER NOT NULL,
      column_index INTEGER NOT NULL,
      row_role TEXT NOT NULL,
      scope TEXT NOT NULL,
      group_level SMALLINT,
      group_key TEXT,
      field_key TEXT NOT NULL,
      raw_text TEXT NOT NULL,
      value NUMERIC(20, 4),
      additivity TEXT NOT NULL,
      computed_value NUMERIC(20, 4),
      outcome TEXT NOT NULL,
      CONSTRAINT project_report_stated_totals_pkey PRIMARY KEY (principal_id, derivation_id,
          row_ordinal, column_index),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT derivation_id_is_an_opaque_identifier CHECK (derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_stated_total_row_is_a_total_row CHECK (row_role IN ('grand_total',
          'group_header')),
      CONSTRAINT a_stated_total_scope_is_known CHECK (scope IN ('grand', 'group')),
      CONSTRAINT a_stated_total_scope_matches_its_row CHECK ((scope = 'grand') = (row_role =
          'grand_total')),
      CONSTRAINT a_stated_total_names_its_group_exactly_in_group_scope CHECK ((group_level IS
          NOT NULL) = (scope = 'group') AND (group_key IS NOT NULL) = (scope = 'group') AND
          (group_level IS NULL OR group_level IN (1, 2))),
      CONSTRAINT a_stated_total_column_is_non_negative CHECK (column_index >= 0),
      CONSTRAINT a_stated_total_field_key_is_a_catalogue_key CHECK (field_key ~
          '^[a-z][a-z0-9_]{0,63}[.][a-z][a-z0-9_]{0,63}$'),
      CONSTRAINT a_stated_total_additivity_is_known CHECK (additivity IN ('additive',
          'non_additive', 'unknown')),
      CONSTRAINT a_stated_total_outcome_is_known CHECK (outcome IN ('both_empty', 'match',
          'mismatch', 'not_checked')),
      CONSTRAINT a_stated_total_is_checked_exactly_when_additive CHECK ((additivity =
          'additive') = (outcome <> 'not_checked')),
      CONSTRAINT a_matched_stated_total_equals_its_sum CHECK (outcome <> 'match' OR (value IS
          NOT NULL AND computed_value = value)),
      CONSTRAINT a_both_empty_stated_total_holds_no_value CHECK (outcome <> 'both_empty' OR
          (value IS NULL AND computed_value IS NULL)),
      CONSTRAINT an_unchecked_stated_total_holds_no_sum CHECK (outcome <> 'not_checked' OR
          computed_value IS NULL),
      CONSTRAINT a_stated_total_names_a_total_row_of_its_derivation FOREIGN KEY(principal_id,
          derivation_id, row_ordinal, row_role) REFERENCES knowledge.project_report_row_roles
          (principal_id, derivation_id, row_ordinal, row_role) ON DELETE RESTRICT
    )
    """

_CROSS_CHECKS_DDL: Final = """
    CREATE TABLE knowledge.project_report_cross_checks (
      principal_id TEXT NOT NULL,
      check_kind TEXT NOT NULL,
      left_derivation_id TEXT NOT NULL,
      right_derivation_id TEXT NOT NULL,
      project_id TEXT NOT NULL,
      date_label TEXT,
      left_value NUMERIC(20, 4),
      right_value NUMERIC(20, 4),
      outcome TEXT NOT NULL,
      checked_at TIMESTAMP WITH TIME ZONE NOT NULL,
      CONSTRAINT project_report_cross_checks_pkey PRIMARY KEY (principal_id, check_kind,
          left_derivation_id, right_derivation_id),
      CONSTRAINT principal_id_is_an_opaque_identifier CHECK (principal_id ~
          '^prn_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT left_derivation_id_is_an_opaque_identifier CHECK (left_derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT right_derivation_id_is_an_opaque_identifier CHECK (right_derivation_id ~
          '^prdrv_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT project_id_is_an_opaque_identifier CHECK (project_id ~
          '^prj_[A-Za-z0-9]{8,64}$'),
      CONSTRAINT a_cross_check_kind_is_known CHECK (check_kind IN
          ('buyout_prime_co_vs_co_reconciliation_v1')),
      CONSTRAINT a_cross_check_date_label_is_a_date_prefix CHECK (date_label IS NULL OR
          date_label ~ '^[0-9]{8}$'),
      CONSTRAINT a_cross_check_outcome_is_known CHECK (outcome IN ('both_empty', 'match',
          'mismatch', 'not_checked')),
      CONSTRAINT a_cross_check_names_two_derivations CHECK (left_derivation_id <>
          right_derivation_id),
      CONSTRAINT a_matched_cross_check_agrees CHECK (outcome <> 'match' OR (left_value IS NOT
          NULL AND left_value = right_value)),
      CONSTRAINT an_unchecked_cross_check_holds_no_value CHECK (outcome NOT IN ('both_empty',
          'not_checked') OR (left_value IS NULL AND right_value IS NULL)),
      CONSTRAINT a_cross_check_left_names_a_derivation_of_its_project FOREIGN
          KEY(left_derivation_id, principal_id, project_id) REFERENCES
          knowledge.project_report_derivations (derivation_id, principal_id, project_id) ON
          DELETE RESTRICT,
      CONSTRAINT a_cross_check_right_names_a_derivation_of_its_project FOREIGN
          KEY(right_derivation_id, principal_id, project_id) REFERENCES
          knowledge.project_report_derivations (derivation_id, principal_id, project_id) ON
          DELETE RESTRICT
    )
    """

#: `(table, DDL)` in creation order, parent before child.
_TABLES: Final = (
    ("project_report_binding_revisions", _BINDING_REVISIONS_DDL),
    ("project_report_filter_declarations", _FILTER_DECLARATIONS_DDL),
    ("project_report_bindings", _BINDINGS_DDL),
    ("project_report_snapshots", _SNAPSHOTS_DDL),
    ("project_report_rows", _ROWS_DDL),
    ("project_report_derivations", _DERIVATIONS_DDL),
    ("project_report_row_roles", _ROW_ROLES_DDL),
    ("project_report_records", _RECORDS_DDL),
    ("project_report_lines", _LINES_DDL),
    ("project_report_line_values", _LINE_VALUES_DDL),
    ("project_report_stated_totals", _STATED_TOTALS_DDL),
    ("project_report_cross_checks", _CROSS_CHECKS_DDL),
)

# ---- step 3: the indexes ----------------------------------------------------------

_INDEXES: Final = (
    (
        "one_first_binding_revision_per_source",
        """
        CREATE UNIQUE INDEX one_first_binding_revision_per_source ON
          knowledge.project_report_binding_revisions (principal_id, ingest_source_id) WHERE
          supersedes_revision_id IS NULL
        """,
    ),
    (
        "project_report_binding_revisions_by_source",
        """
        CREATE INDEX project_report_binding_revisions_by_source ON
          knowledge.project_report_binding_revisions (principal_id, ingest_source_id,
          recorded_at)
        """,
    ),
    (
        "project_report_binding_revisions_by_project",
        """
        CREATE INDEX project_report_binding_revisions_by_project ON
          knowledge.project_report_binding_revisions (principal_id, project_id)
        """,
    ),
    (
        "one_active_project_report_binding_per_project",
        """
        CREATE UNIQUE INDEX one_active_project_report_binding_per_project ON
          knowledge.project_report_bindings (principal_id, project_id) WHERE state = 'active'
        """,
    ),
    (
        "project_report_bindings_by_revision",
        """
        CREATE INDEX project_report_bindings_by_revision ON knowledge.project_report_bindings
          (principal_id, binding_revision_id)
        """,
    ),
    (
        "project_report_snapshots_by_source",
        """
        CREATE INDEX project_report_snapshots_by_source ON knowledge.project_report_snapshots
          (principal_id, ingest_source_id)
        """,
    ),
    (
        "one_first_derivation_per_report_snapshot",
        """
        CREATE UNIQUE INDEX one_first_derivation_per_report_snapshot ON
          knowledge.project_report_derivations (principal_id, snapshot_id) WHERE
          supersedes_derivation_id IS NULL
        """,
    ),
    (
        "project_report_derivations_by_snapshot",
        """
        CREATE INDEX project_report_derivations_by_snapshot ON
          knowledge.project_report_derivations (principal_id, snapshot_id)
        """,
    ),
    (
        "project_report_derivations_by_view",
        """
        CREATE INDEX project_report_derivations_by_view ON knowledge.project_report_derivations
          (principal_id, project_id, record_family, family_view)
        """,
    ),
    (
        "project_report_derivations_by_state",
        """
        CREATE INDEX project_report_derivations_by_state ON
          knowledge.project_report_derivations (principal_id, state, quarantine_reason)
        """,
    ),
    (
        "project_report_derivations_by_revision",
        """
        CREATE INDEX project_report_derivations_by_revision ON
          knowledge.project_report_derivations (principal_id, binding_revision_id)
        """,
    ),
    (
        "project_report_row_roles_by_role",
        """
        CREATE INDEX project_report_row_roles_by_role ON knowledge.project_report_row_roles
          (principal_id, derivation_id, row_role)
        """,
    ),
    (
        "project_report_row_roles_by_raw_row",
        """
        CREATE INDEX project_report_row_roles_by_raw_row ON knowledge.project_report_row_roles
          (principal_id, snapshot_id, row_ordinal)
        """,
    ),
    (
        "project_report_records_by_derivation",
        """
        CREATE INDEX project_report_records_by_derivation ON knowledge.project_report_records
          (principal_id, created_by_derivation_id)
        """,
    ),
    (
        "project_report_lines_by_record",
        """
        CREATE INDEX project_report_lines_by_record ON knowledge.project_report_lines
          (principal_id, record_id, derivation_id)
        """,
    ),
    (
        "project_report_lines_by_status",
        """
        CREATE INDEX project_report_lines_by_status ON knowledge.project_report_lines
          (principal_id, project_id, record_family, status_class)
        """,
    ),
    (
        "project_report_lines_by_identifier",
        """
        CREATE INDEX project_report_lines_by_identifier ON knowledge.project_report_lines
          (principal_id, project_id, identifier_numeric_suffix, identifier_prefix)
        """,
    ),
    (
        "project_report_line_values_by_date",
        """
        CREATE INDEX project_report_line_values_by_date ON knowledge.project_report_line_values
          (principal_id, field_key, value_date)
        """,
    ),
    (
        "project_report_line_values_by_decimal",
        """
        CREATE INDEX project_report_line_values_by_decimal ON
          knowledge.project_report_line_values (principal_id, field_key, value_decimal)
        """,
    ),
    (
        "project_report_cross_checks_by_project",
        """
        CREATE INDEX project_report_cross_checks_by_project ON
          knowledge.project_report_cross_checks (principal_id, project_id, date_label)
        """,
    ),
    (
        "project_report_cross_checks_by_right",
        """
        CREATE INDEX project_report_cross_checks_by_right ON
          knowledge.project_report_cross_checks (principal_id, right_derivation_id)
        """,
    ),
)

# ---- step 4: the current-derivations view -------------------------------------------

_VIEW: Final = "project_report_current_derivations"

#: A derivation is current when no derivation of its Principal supersedes it.
#: The view names every derivation column, in table order.
_VIEW_DDL: Final = """
    CREATE VIEW knowledge.project_report_current_derivations AS
      SELECT d.derivation_id, d.principal_id, d.snapshot_id, d.ingest_source_id,
             d.binding_revision_id, d.project_id, d.state, d.quarantine_reason,
             d.record_family, d.family_view, d.adapter_version, d.identity_version,
             d.status_map_version, d.completeness_class, d.role_counts, d.reconciliation,
             d.trigger, d.supersedes_derivation_id, d.derived_at
        FROM knowledge.project_report_derivations d
       WHERE NOT EXISTS (
             SELECT 1 FROM knowledge.project_report_derivations n
              WHERE n.principal_id = d.principal_id
                AND n.supersedes_derivation_id = d.derivation_id)
    """

# ---- step 5: the guards ---------------------------------------------------------

_BINDING_FUNCTION: Final = "project_report_bindings_move_only_forward"
_BINDING_TRIGGER: Final = "project_report_bindings_move_only_forward"
_BINDING_MUTABLE: Final = ("binding_revision_id", "project_id", "state")

#: DELETE is refused; an UPDATE changes only the three named columns (compared as
#: JSONB minus those keys, so a column added later is immutable without editing
#: this guard), and moves the pointer only to the revision that supersedes the
#: one it names. The composite foreign key keeps `project_id` and `state` equal
#: to the revision named.
_BINDING_GUARD: Final = """
    CREATE FUNCTION knowledge.project_report_bindings_move_only_forward() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'project_report_bindings rows are never deleted'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF (to_jsonb(NEW) - ARRAY['binding_revision_id', 'project_id', 'state']::text[])
         IS DISTINCT FROM
         (to_jsonb(OLD) - ARRAY['binding_revision_id', 'project_id', 'state']::text[]) THEN
        RAISE EXCEPTION 'project_report_bindings changes only its named mutable columns'
          USING ERRCODE = 'restrict_violation';
      END IF;
      IF NEW.binding_revision_id IS DISTINCT FROM OLD.binding_revision_id
         AND NOT EXISTS (
           SELECT 1 FROM knowledge.project_report_binding_revisions r
            WHERE r.principal_id = OLD.principal_id
              AND r.binding_revision_id = NEW.binding_revision_id
              AND r.supersedes_revision_id = OLD.binding_revision_id) THEN
        RAISE EXCEPTION 'project_report_bindings moves only to the revision superseding its own'
          USING ERRCODE = 'restrict_violation';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER project_report_bindings_move_only_forward
      BEFORE UPDATE OR DELETE ON knowledge.project_report_bindings
      FOR EACH ROW EXECUTE FUNCTION knowledge.project_report_bindings_move_only_forward()
    """

#: B1: a row supersedes only a row that already exists, of its Principal and
#: source (a revision) or snapshot (a derivation), so no INSERT -- not even one
#: multi-row statement -- can close a cycle. A self-referencing foreign key
#: is checked at the end of its statement, so `(X supersedes Y), (Y supersedes
#: X)` in one INSERT satisfies both keys; a row-level BEFORE INSERT trigger runs
#: per row and sees exactly the rows the statement inserted before it (the
#: function is VOLATILE), so a first-then-successor chain in one statement is
#: still accepted. By induction every row names an earlier row: each chain is
#: acyclic, and its head -- the one row nothing supersedes -- always exists.
_REVISION_SUPERSEDES: Final = "project_report_binding_revisions_supersede_an_existing_one"
_DERIVATION_SUPERSEDES: Final = "project_report_derivations_supersede_an_existing_one"

_REVISION_SUPERSEDES_GUARD: Final = """
    CREATE FUNCTION knowledge.project_report_binding_revisions_supersede_an_existing_one()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.supersedes_revision_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM knowledge.project_report_binding_revisions o
            WHERE o.principal_id = NEW.principal_id
              AND o.binding_revision_id = NEW.supersedes_revision_id
              AND o.ingest_source_id = NEW.ingest_source_id) THEN
        RAISE EXCEPTION 'project_report_binding_revisions supersedes only an existing revision'
          USING ERRCODE = 'restrict_violation',
                CONSTRAINT = 'project_report_binding_revisions_supersede_an_existing_one';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER project_report_binding_revisions_supersede_an_existing_one
      BEFORE INSERT ON knowledge.project_report_binding_revisions
      FOR EACH ROW EXECUTE FUNCTION
        knowledge.project_report_binding_revisions_supersede_an_existing_one()
    """

_DERIVATION_SUPERSEDES_GUARD: Final = """
    CREATE FUNCTION knowledge.project_report_derivations_supersede_an_existing_one()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.supersedes_derivation_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM knowledge.project_report_derivations o
            WHERE o.principal_id = NEW.principal_id
              AND o.derivation_id = NEW.supersedes_derivation_id
              AND o.snapshot_id = NEW.snapshot_id) THEN
        RAISE EXCEPTION 'project_report_derivations supersedes only an existing derivation'
          USING ERRCODE = 'restrict_violation',
                CONSTRAINT = 'project_report_derivations_supersede_an_existing_one';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER project_report_derivations_supersede_an_existing_one
      BEFORE INSERT ON knowledge.project_report_derivations
      FOR EACH ROW EXECUTE FUNCTION
        knowledge.project_report_derivations_supersede_an_existing_one()
    """


#: N2: a new pointer names a revision nothing supersedes yet (an UPDATE is held
#: to the superseding revision by `_BINDING_GUARD`).
_POINTER_INSERT: Final = "project_report_bindings_name_an_unsuperseded_revision"

_POINTER_INSERT_GUARD: Final = """
    CREATE FUNCTION knowledge.project_report_bindings_name_an_unsuperseded_revision()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (
           SELECT 1 FROM knowledge.project_report_binding_revisions r
            WHERE r.principal_id = NEW.principal_id
              AND r.supersedes_revision_id = NEW.binding_revision_id) THEN
        RAISE EXCEPTION 'project_report_bindings names only an unsuperseded revision'
          USING ERRCODE = 'restrict_violation',
                CONSTRAINT = 'project_report_bindings_name_an_unsuperseded_revision';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER project_report_bindings_name_an_unsuperseded_revision
      BEFORE INSERT ON knowledge.project_report_bindings
      FOR EACH ROW EXECUTE FUNCTION
        knowledge.project_report_bindings_name_an_unsuperseded_revision()
    """

#: N1: a cross-check's sides have fixed roles -- the left side is the buyout
#: summary derivation, the right the change-order reconciliation derivation
#: (the S2 `pair_cross_report(buyout, reconciliation)` order) -- so `(A, B)` and
#: `(B, A)` cannot both be recorded. A side that names no derivation is left to
#: its foreign key; an unknown kind to `a_cross_check_kind_is_known`.
_CROSS_CHECK_ROLES: Final = "project_report_cross_checks_keep_their_roles"

_CROSS_CHECK_ROLES_GUARD: Final = """
    CREATE FUNCTION knowledge.project_report_cross_checks_keep_their_roles()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.check_kind = 'buyout_prime_co_vs_co_reconciliation_v1' AND (
           EXISTS (SELECT 1 FROM knowledge.project_report_derivations d
                    WHERE d.principal_id = NEW.principal_id
                      AND d.derivation_id = NEW.left_derivation_id
                      AND d.family_view IS DISTINCT FROM 'buyout_summary')
           OR EXISTS (SELECT 1 FROM knowledge.project_report_derivations d
                       WHERE d.principal_id = NEW.principal_id
                         AND d.derivation_id = NEW.right_derivation_id
                         AND d.family_view IS DISTINCT FROM 'reconciliation')) THEN
        RAISE EXCEPTION 'project_report_cross_checks keeps its sides in their roles'
          USING ERRCODE = 'restrict_violation',
                CONSTRAINT = 'project_report_cross_checks_keep_their_roles';
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER project_report_cross_checks_keep_their_roles
      BEFORE INSERT ON knowledge.project_report_cross_checks
      FOR EACH ROW EXECUTE FUNCTION knowledge.project_report_cross_checks_keep_their_roles()
    """

_APPEND_ONLY_FUNCTION: Final = "project_reports_rows_are_append_only"
_APPEND_ONLY_TABLES: Final = (
    "project_report_binding_revisions",
    "project_report_filter_declarations",
    "project_report_snapshots",
    "project_report_rows",
    "project_report_derivations",
    "project_report_row_roles",
    "project_report_records",
    "project_report_lines",
    "project_report_line_values",
    "project_report_stated_totals",
    "project_report_cross_checks",
)

_APPEND_ONLY: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% is append-only', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
    END; $$
    """

_TRUNCATE_FUNCTION: Final = "project_reports_refuse_truncate"

_TRUNCATE: Final = f"""
    CREATE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION '% refuses %', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'restrict_violation';
      RETURN NULL;
    END; $$
    """

# ---- downgrade -------------------------------------------------------------------

#: `downgrade` locks every table it checks or changes before it checks them, so
#: no row can commit between the refusal check and the drops: the twelve tables,
#: child before parent, then the three referenced tables in the upgrade's order
#: (`DROP TABLE` takes `ACCESS EXCLUSIVE` on each foreign-key target).
_LOCK_TABLES: Final = (
    "LOCK TABLE knowledge.project_report_cross_checks, knowledge.project_report_stated_totals, "
    "knowledge.project_report_line_values, knowledge.project_report_lines, "
    "knowledge.project_report_records, knowledge.project_report_row_roles, "
    "knowledge.project_report_derivations, knowledge.project_report_rows, "
    "knowledge.project_report_snapshots, knowledge.project_report_bindings, "
    "knowledge.project_report_filter_declarations, knowledge.project_report_binding_revisions, "
    "knowledge.ingest_sources, knowledge.ingest_snapshots, knowledge.projects "
    "IN ACCESS EXCLUSIVE MODE"
)

#: `downgrade` refuses while any table holds a row rather than deleting
#: evidence to make the downgrade pass (the `7d9a450dfd07` precedent).
_REFUSE_DOWNGRADE: Final = """
    DO $$
    BEGIN
      IF EXISTS (SELECT 1 FROM knowledge.project_report_binding_revisions)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_filter_declarations)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_bindings)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_snapshots)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_rows)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_derivations)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_row_roles)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_records)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_lines)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_line_values)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_stated_totals)
         OR EXISTS (SELECT 1 FROM knowledge.project_report_cross_checks) THEN
        RAISE EXCEPTION 'project report rows exist; refusing to downgrade 0d4e247d03cb'
          USING ERRCODE = 'restrict_violation';
      END IF;
    END $$
    """


def upgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_REFERENCED)
    for _table, ddl in _TABLES:
        op.execute(ddl)
    for _name, ddl in _INDEXES:
        op.execute(ddl)
    op.execute(_VIEW_DDL)
    op.execute(_BINDING_GUARD)
    op.execute(_REVISION_SUPERSEDES_GUARD)
    op.execute(_DERIVATION_SUPERSEDES_GUARD)
    op.execute(_POINTER_INSERT_GUARD)
    op.execute(_CROSS_CHECK_ROLES_GUARD)
    op.execute(_APPEND_ONLY)
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_are_append_only
              BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
              FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()
            """
        )
    op.execute(_TRUNCATE)
    for table, _ddl in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER {table}_refuse_truncate
              BEFORE TRUNCATE ON {SCHEMA}.{table}
              FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()
            """
        )


def downgrade() -> None:
    op.execute(_LOCK_TIMEOUT)
    op.execute(_LOCK_TABLES)
    op.execute(_REFUSE_DOWNGRADE)
    for table, _ddl in reversed(_TABLES):
        op.execute(f"DROP TRIGGER {table}_refuse_truncate ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_TRUNCATE_FUNCTION}()")
    for table in reversed(_APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER {table}_are_append_only ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_APPEND_ONLY_FUNCTION}()")
    op.execute(f"DROP TRIGGER {_CROSS_CHECK_ROLES} ON {SCHEMA}.project_report_cross_checks")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_CROSS_CHECK_ROLES}()")
    op.execute(f"DROP TRIGGER {_POINTER_INSERT} ON {SCHEMA}.project_report_bindings")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_POINTER_INSERT}()")
    op.execute(f"DROP TRIGGER {_DERIVATION_SUPERSEDES} ON {SCHEMA}.project_report_derivations")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_DERIVATION_SUPERSEDES}()")
    op.execute(f"DROP TRIGGER {_REVISION_SUPERSEDES} ON {SCHEMA}.project_report_binding_revisions")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_REVISION_SUPERSEDES}()")
    op.execute(f"DROP TRIGGER {_BINDING_TRIGGER} ON {SCHEMA}.project_report_bindings")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_BINDING_FUNCTION}()")
    op.execute(f"DROP VIEW {SCHEMA}.{_VIEW} RESTRICT")
    for name, _ddl in reversed(_INDEXES):
        op.execute(f"DROP INDEX {SCHEMA}.{name}")
    for table, _ddl in reversed(_TABLES):
        op.execute(f"DROP TABLE {SCHEMA}.{table} RESTRICT")
