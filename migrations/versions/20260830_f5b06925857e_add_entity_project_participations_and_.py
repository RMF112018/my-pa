"""Add entity_project_participations and role/discipline taxonomies (RI-ENT-WP-04).

Revision ID: f5b06925857e
Revises: 441b071bf37b
Create Date: 2026-08-30

RI-ENT-WP-04 (project participation model). Closes `ENTITY-PROJECT-001`
("incomplete project participation"). Authorized per
`AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings (in particular "Merge/split
disposition (RULING 2)").

Three brand-new, purely additive tables. Nothing existing is altered and no
legacy data is backfilled. `entity_role_types` and `entity_discipline_types`
are seeded with a modest, generic, industry-standard set of AEC role and
discipline codes so `entity_project_participations` has something to
reference; `entity_project_participations` itself is empty at every
environment this revision reaches, and nothing here writes to
`entity_assignments`, which this revision does not touch, widen, or migrate
data into.

**Naming deviation, disclosed.** The audit's own text names this table
`project_entity_participations`. It is created here as
`entity_project_participations` instead. Reason:
`tests/architecture/test_relationship_scoring_surface_is_denied` (the
NO-CONFIDENCE deny-rule guard) scans exactly the tables whose name starts
with one of `RELATIONSHIP_TABLE_PREFIXES = ("relationship_", "entities",
"entity_")`. A table named `project_entity_participations` would not start
with any of those prefixes and would silently fall outside the deny rule's
scan -- exactly the hazard the guard exists to prevent, for the one table in
this work package where the audit's own suggested field names
("participation confidence", "role confidence", "scope confidence") are
explicitly forbidden (RULING 1). Renaming to `entity_project_participations`
-- still an accurate, conventional name, matching every sibling family in
this campaign's `entity_<something>` shape -- brings it inside the existing
scan surface with zero change to the guard's scanning logic, which this
revision does not touch. This is recorded here, in
`my_pa.domain.relationship.entity.EntityProjectParticipation`'s docstring,
and in the campaign document's ledger, as a deliberate, disclosed deviation
from the audit's literal text, not a silent one. The primary-key column is
nonetheless literally `participation_id`, not
`entity_project_participation_id`, per the authorizing instruction.

**`entity_role_types` and `entity_discipline_types`** are global, Principal-
independent reference vocabularies -- shared lookup tables, not per-Principal
records, the same way `ExternalIdentifierNamespace` values are not
per-Principal. `role_code`/`discipline_code` are stable business codes, not
generated ids (`IdKind.ENTITY_PROJECT_PARTICIPATION` names only the
participation row itself; see `domain.common.identifiers.IdKind`'s
docstring). `category`/`broader_family` are deliberately free text, not
closed vocabularies: both catalogs are meant to grow by a new row, not a
schema change. The seeded codes here are generic, industry-standard AEC
terms only (OWNER, GENERAL_CONTRACTOR, ARCHITECT_OF_RECORD, CIVIL_ENGINEERING,
and so on) -- never anything derived from or resembling any specific
register's content, which is explicitly out of scope for this campaign
("TBR register import").

**`entity_project_participations`** mirrors `entity_addresses`'s shape
(composite `(entity, principal)` FKs to `entities`, principal-scoped
self-supersession, three-state lifecycle, `version`, `updated_at`,
`retired_at`) with two entity references instead of one:
`project_entity_id` (expected `entity_type = 'project'` -- a **domain
invariant the writer enforces, not a CHECK**, since PostgreSQL cannot express
a CHECK that reads another table's row; the same non-enforcement
`entity_organization_profiles` already accepts for
`entity_type = 'organization'`) and `participant_entity_id` (a person or
organization entity, no `entity_type` restriction). A CHECK
(`project_entity_id <> participant_entity_id`) refuses the one case SQL can
see: a project cannot meaningfully participate in itself.

`project_display_name` is **project-scoped fact, never global identity**: the
name a participant is known by on this specific project, which this
migration, the domain layer, and every future writer must never copy into
`entities.display_name` or `entities.canonical_name`, and vice versa. This is
the single most important semantic boundary in this work package; see
`my_pa.domain.relationship.entity.EntityProjectParticipation`'s docstring for
the full statement of it.

`role_basis_code`, `stakeholder_side_code`, `stakeholder_class_code`, and
`relationship_status_code` are four new, independent closed vocabularies
(`RoleBasisCode`, `StakeholderSideCode`, `StakeholderClassCode`,
`ParticipationStatusCode`), none of them a numeric confidence: this is the
audit's own "participation confidence" / "role confidence" / "scope
confidence" dimensions represented as discrete, named states instead
(RULING 1), and RULING 3 binds `role_basis_code` specifically -- it is never
inferred from a name or string position, and `unresolved` is the correct
value when the basis is unknown, never a guess. `relationship_status_code` is
a new vocabulary scoped to this table only; no existing relationship-status
vocabulary was found elsewhere in the codebase to reuse (confirmed by grep
before this revision was authored), and it is distinct from the
record-lifecycle `state` column below -- see `ParticipationStatusCode`'s
docstring for how the two differ.

**Active uniqueness is keyed on `(principal, project, participant, role)`,
deliberately including `role_code`.** One entity may hold two concurrently
active roles on the same project (e.g. both `CONSULTANT` and
`OWNER_REPRESENTATIVE`), and `role_code` being part of the key is what
permits that without weakening the guard against a literal duplicate under
one role -- the same shape of reasoning `entity_addresses` gives for
including `address_type_code` in its own active-uniqueness key, restated
here for a different axis.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`); the
closed-set literals are frozen at this revision.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "f5b06925857e"
down_revision: str | None = "441b071bf37b"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_TAXONOMY_STATUS_VALUES: Final = "'active', 'deprecated'"

_ROLE_BASIS_VALUES: Final = (
    "'contractual', 'inferred', 'project_observed', 'source_verified', 'unresolved'"
)

_STAKEHOLDER_SIDE_VALUES: Final = (
    "'adjacent_interface', 'authority', 'consultant', 'contractor', 'design', "
    "'developer', 'other', 'owner', 'sales_marketing', 'utility', 'vendor'"
)

_STAKEHOLDER_CLASS_VALUES: Final = "'adjacent', 'core', 'transactional', 'unresolved'"

_PARTICIPATION_STATUS_VALUES: Final = "'active', 'completed', 'on_hold', 'terminated', 'unresolved'"

#: Generic, industry-standard AEC project roles (audit's Record Element
#: Inventory), never anything derived from or resembling any specific
#: register's content -- that content is explicitly out of scope for this
#: campaign. `(role_code, label, category)`.
_SEED_ROLE_TYPES: Final = (
    ("OWNER", "Owner", "ownership"),
    ("OWNER_REPRESENTATIVE", "Owner's Representative", "ownership"),
    ("DEVELOPER", "Developer", "ownership"),
    ("GENERAL_CONTRACTOR", "General Contractor", "construction"),
    ("SUBCONTRACTOR", "Subcontractor", "construction"),
    ("CONSTRUCTION_MANAGER", "Construction Manager", "construction"),
    ("ARCHITECT_OF_RECORD", "Architect of Record", "design"),
    ("PROJECT_MANAGER", "Project Manager", "consulting"),
    ("CONSULTANT", "Consultant", "consulting"),
    ("SURVEYOR", "Surveyor", "consulting"),
    ("PERMITTING_AUTHORITY", "Permitting Authority", "authority"),
    ("UTILITY_PROVIDER", "Utility Provider", "authority"),
    ("LENDER", "Lender", "finance"),
    ("SALES_AGENT", "Sales Agent", "finance"),
)

#: Generic, industry-standard AEC disciplines. `(discipline_code, label,
#: broader_family)`.
_SEED_DISCIPLINE_TYPES: Final = (
    ("CIVIL_ENGINEERING", "Civil Engineering", "engineering"),
    ("STRUCTURAL_ENGINEERING", "Structural Engineering", "engineering"),
    ("GEOTECHNICAL_ENGINEERING", "Geotechnical Engineering", "engineering"),
    ("MEP_ENGINEERING", "MEP Engineering", "engineering"),
    ("ARCHITECTURE", "Architecture", "design"),
    ("LANDSCAPE_ARCHITECTURE", "Landscape Architecture", "design"),
    ("INTERIOR_DESIGN", "Interior Design", "design"),
    ("SURVEYING", "Surveying", "professional_services"),
    ("CONSTRUCTION_MANAGEMENT", "Construction Management", "management"),
    ("LEGAL", "Legal", "professional_services"),
    ("FINANCE", "Finance", "professional_services"),
)


def _sql_literal(value: str) -> str:
    """A single-quoted SQL string literal, with embedded quotes doubled.

    The seed values below are fixed, hand-written literals (never user input),
    but `"Owner's Representative"` still carries an apostrophe that would
    otherwise terminate the literal early, so this is applied uniformly rather
    than trusted to be unnecessary for any one row.
    """
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_role_types (
          role_code text PRIMARY KEY,
          label text NOT NULL,
          category text,
          status text NOT NULL DEFAULT 'active',
          CONSTRAINT a_role_type_code_is_not_blank
            CHECK (length(trim(role_code)) > 0),
          CONSTRAINT a_role_type_label_is_not_blank
            CHECK (length(trim(label)) > 0),
          CONSTRAINT a_role_type_category_is_not_blank
            CHECK (category IS NULL OR length(trim(category)) > 0),
          CONSTRAINT a_role_type_status_is_known
            CHECK (status IN ({_TAXONOMY_STATUS_VALUES}))
        );
        """
    )
    # The suppression below is deliberate: every interpolation is either
    # `SCHEMA` (a module constant) or a value from `_SEED_ROLE_TYPES` -- a
    # fixed, hand-written tuple of literals above, never a caller or request
    # value -- passed through `_sql_literal`, which quotes and escapes it.
    for role_code, label, category in _SEED_ROLE_TYPES:
        op.execute(
            f"""
            INSERT INTO {SCHEMA}.entity_role_types (role_code, label, category)
            VALUES (
              {_sql_literal(role_code)}, {_sql_literal(label)}, {_sql_literal(category)}
            );
            """  # noqa: S608
        )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_discipline_types (
          discipline_code text PRIMARY KEY,
          label text NOT NULL,
          broader_family text,
          status text NOT NULL DEFAULT 'active',
          CONSTRAINT a_discipline_type_code_is_not_blank
            CHECK (length(trim(discipline_code)) > 0),
          CONSTRAINT a_discipline_type_label_is_not_blank
            CHECK (length(trim(label)) > 0),
          CONSTRAINT a_discipline_type_broader_family_is_not_blank
            CHECK (broader_family IS NULL OR length(trim(broader_family)) > 0),
          CONSTRAINT a_discipline_type_status_is_known
            CHECK (status IN ({_TAXONOMY_STATUS_VALUES}))
        );
        """
    )
    # Same suppression, same reason: every interpolation is `SCHEMA` or a
    # value from the fixed `_SEED_DISCIPLINE_TYPES` tuple above, passed
    # through the quoting/escaping `_sql_literal`.
    for discipline_code, label, broader_family in _SEED_DISCIPLINE_TYPES:
        op.execute(
            f"""
            INSERT INTO {SCHEMA}.entity_discipline_types
              (discipline_code, label, broader_family)
            VALUES (
              {_sql_literal(discipline_code)}, {_sql_literal(label)},
              {_sql_literal(broader_family)}
            );
            """  # noqa: S608
        )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_project_participations (
          participation_id text PRIMARY KEY,
          principal_id text NOT NULL,
          project_entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          participant_entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          -- The name this participant is known by ON THIS PROJECT --
          -- project-scoped fact, never global identity. Nothing may ever
          -- write this value to entities.display_name or
          -- entities.canonical_name, and nothing may read either of those
          -- columns into this one. See EntityProjectParticipation's
          -- docstring for the full statement of this boundary.
          project_display_name text NOT NULL,
          role_code text
            REFERENCES {SCHEMA}.entity_role_types(role_code),
          role_text text,
          discipline_code text
            REFERENCES {SCHEMA}.entity_discipline_types(discipline_code),
          discipline_text text,
          scope_text text,
          role_basis_code text NOT NULL,
          stakeholder_side_code text NOT NULL,
          stakeholder_class_code text NOT NULL,
          relationship_status_code text NOT NULL,
          effective_from timestamptz,
          effective_to timestamptz,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          updated_at timestamptz,
          retired_at timestamptz,
          superseded_by_participation_id text
            REFERENCES {SCHEMA}.entity_project_participations(participation_id),
          CONSTRAINT participation_id_is_an_opaque_identifier
            CHECK (participation_id ~ '^eppt_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_project_participation_display_name_is_not_blank
            CHECK (length(trim(project_display_name)) > 0),
          CONSTRAINT a_project_participation_role_text_is_not_blank
            CHECK (role_text IS NULL OR length(trim(role_text)) > 0),
          CONSTRAINT a_project_participation_discipline_text_is_not_blank
            CHECK (discipline_text IS NULL OR length(trim(discipline_text)) > 0),
          CONSTRAINT a_project_participation_scope_text_is_not_blank
            CHECK (scope_text IS NULL OR length(trim(scope_text)) > 0),
          CONSTRAINT a_project_participation_role_basis_is_known
            CHECK (role_basis_code IN ({_ROLE_BASIS_VALUES})),
          CONSTRAINT a_project_participation_stakeholder_side_is_known
            CHECK (stakeholder_side_code IN ({_STAKEHOLDER_SIDE_VALUES})),
          CONSTRAINT a_project_participation_stakeholder_class_is_known
            CHECK (stakeholder_class_code IN ({_STAKEHOLDER_CLASS_VALUES})),
          CONSTRAINT a_project_participation_status_is_known
            CHECK (relationship_status_code IN ({_PARTICIPATION_STATUS_VALUES})),
          CONSTRAINT a_project_participation_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT a_project_participation_state_is_known
            CHECK (state IN ('active', 'retired', 'superseded')),
          CONSTRAINT a_project_participation_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT a_project_participation_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          CONSTRAINT a_project_participation_names_a_successor_only_when_superseded
            CHECK (superseded_by_participation_id IS NULL OR state = 'superseded'),
          CONSTRAINT a_project_participation_does_not_supersede_itself
            CHECK (
              superseded_by_participation_id IS NULL
              OR superseded_by_participation_id <> participation_id
            ),
          -- A project cannot meaningfully participate in itself. The domain
          -- invariant that project_entity_id names an entity whose
          -- entity_type is 'project' is NOT expressible as a CHECK (it reads
          -- another table's row) and is enforced by the writer -- see
          -- EntityProjectParticipation's docstring. This CHECK only rules
          -- out the one case SQL can see.
          CONSTRAINT a_project_participation_project_is_not_the_participant
            CHECK (project_entity_id <> participant_entity_id),
          CONSTRAINT a_project_participation_is_identified_within_its_principal
            UNIQUE (participation_id, principal_id)
        );
        """
    )
    # Composite foreign keys, added after the table exists so both sides of
    # each reference are present: entity_project_participations(project_entity_id,
    # principal_id) -> entities(entity_id, principal_id),
    # (participant_entity_id, principal_id) -> entities(entity_id, principal_id),
    # and the self-referencing (superseded_by_participation_id, principal_id)
    # -> entity_project_participations(...). entity_role_types/
    # entity_discipline_types are global taxonomies with no principal_id, so
    # role_code/discipline_code are plain (non-composite) foreign keys,
    # already declared inline above.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_project_participations
          ADD CONSTRAINT a_project_participation_names_a_project_of_its_principal
          FOREIGN KEY (project_entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_project_participations
          ADD CONSTRAINT a_project_participation_names_a_participant_of_its_principal
          FOREIGN KEY (participant_entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_project_participations
          ADD CONSTRAINT a_project_participation_is_superseded_within_its_principal
          FOREIGN KEY (superseded_by_participation_id, principal_id)
          REFERENCES {SCHEMA}.entity_project_participations (
            participation_id, principal_id
          );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_project_participations_by_principal
          ON {SCHEMA}.entity_project_participations (principal_id);
        -- The (project, current state) index: the shape almost every read of
        -- this table takes ("this project's active participants" and
        -- similar).
        CREATE INDEX entity_project_participations_by_project_state
          ON {SCHEMA}.entity_project_participations (project_entity_id, state);
        """
    )
    op.execute(
        f"""
        -- Per *project, participant, and role*, deliberately including
        -- role_code: one entity legitimately holds two concurrently active
        -- roles on the same project (e.g. both CONSULTANT and
        -- OWNER_REPRESENTATIVE), and role_code being part of this key is
        -- what permits that rather than a coincidence a future reader
        -- should "fix" by dropping it -- do not drop it.
        CREATE UNIQUE INDEX an_active_project_participation_is_unique_per_project_and_role
          ON {SCHEMA}.entity_project_participations (
            principal_id, project_entity_id, participant_entity_id, role_code
          )
          WHERE state = 'active';
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_project_participations;")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_discipline_types;")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_role_types;")
