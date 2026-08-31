"""Add entity_person_organization_affiliations (RI-ENT-WP-05).

Revision ID: 17149a48fa30
Revises: f5b06925857e
Create Date: 2026-08-30

RI-ENT-WP-05 (person affiliation integration). Closes `ENTITY-PERSON-001`
("incomplete person affiliations"). Authorized per
`AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings (in particular "Merge/split
disposition (RULING 2)", extended by this revision to a sixth family).

One brand-new, purely additive table. Nothing existing is altered and no
legacy data is backfilled; `entity_assignments` is not touched, widened, or
migrated into, for the same reason `entity_project_participations` left it
alone (RI-ENT-WP-04): a dedicated table is warranted precisely because the
generic assignment record cannot carry these dimensions.

**Naming deviation, disclosed.** The audit's own text names this table
`person_organization_affiliations`. It is created here as
`entity_person_organization_affiliations` instead, for exactly the reason
`f5b06925857e`'s own module docstring gives for the same deviation:
`tests/architecture/test_relationship_scoring_surface_is_denied` (the
NO-CONFIDENCE deny-rule guard) scans exactly the tables whose name starts with
one of `RELATIONSHIP_TABLE_PREFIXES = ("relationship_", "entities",
"entity_")`. A table named `person_organization_affiliations` would not start
with any of those prefixes and would silently fall outside the deny rule's
scan -- and this family is the *most* exposed one yet to carry a smuggled
scoring field, since it is where the audit's own text discusses a person's
job title and organizational standing. Renaming to
`entity_person_organization_affiliations` -- still an accurate, conventional
name, matching every sibling family in this campaign's `entity_<something>`
shape -- brings it inside the existing scan surface with zero change to the
guard's scanning logic, which this revision does not touch. This is recorded
here, in `my_pa.domain.relationship.entity.PersonOrganizationAffiliation`'s
docstring, and in the campaign document's ledger, as a deliberate, disclosed
deviation from the audit's literal text, not a silent one. The primary-key
column is nonetheless literally `affiliation_id`, matching the audit's own
field name, not `entity_person_organization_affiliation_id`.

**`organization_entity_id` is NULLABLE, and that is the central requirement of
this work package.** The audit's own "Mike Fichera" case is an independent
consultant who does project work with no employer at all -- a real, common
AEC-industry fact, not a data-quality gap. This revision never creates, and no
writer built on this table may ever create, a placeholder or sentinel
organization entity merely to give this column something non-null to satisfy
a foreign key; a `NULL` here, paired with `affiliation_type_code =
'independent_consultant'`, states the absence directly. See
`PersonOrganizationAffiliation`'s docstring for the full reasoning, and
`tests/database/test_person_organization_affiliations_independent_consultant_fixture.py`
for the server-level proof that no such placeholder entity is ever created as
a side effect.

**`entities.entity_type == 'person'`/`'organization'` for
`person_entity_id`/`organization_entity_id` are domain invariants, not CHECK
constraints.** PostgreSQL cannot express a CHECK that reads another table's
row, so this revision's migration does not and cannot enforce either in SQL,
and does not infer either -- the same non-enforcement `entity_organization_
profiles` and `entity_project_participations` already accept for their own
entity references. The writer/repository layer that inserts a row here is
responsible for both invariants.

**"Current" is `effective_to IS NULL`, made unambiguous per person by a
partial unique index.** A person may accumulate many affiliation rows over a
career, and at most one of them may be the person's present, ongoing tie at
any one moment -- a specific product decision this revision makes explicit
rather than leaving implicit, following the open-ended-range convention
`entity_assignments` already uses for the same question rather than inventing
a second, independently-settable "is current" boolean that could disagree
with the date range. `an_open_ended_affiliation_is_unique_per_person` is the
constraint that makes this hold at the database: at most one row per
`(principal_id, person_entity_id)` may be simultaneously `state = 'active'`
and `effective_to IS NULL`. A second, already-closed (non-null `effective_to`)
affiliation for the same person freely coexists as history.

**`affiliation_type_code`** (`AffiliationTypeCode`) is a new, independent,
purely categorical closed vocabulary -- employment/principal_ownership/
independent_consultant/contractor/board_member/advisor/other -- with no
member that ranks, scores, or grades a person's tie to an organization
(RULING 1). `job_title` is independently nullable free text, carrying the
audit's own "Person job title" element; a blank-when-present CHECK mirrors
every sibling family's text-field convention. No assertion/confidence/
evidence dimension is added: the audit's own Record Element Inventory rows
for this family carry no such column this revision's scope covers (RI-ENT-
WP-07 owns assertion/provenance binding for every family on this plane,
including this one, and has not landed).

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`); the
closed-set literals are frozen at this revision.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "17149a48fa30"
down_revision: str | None = "f5b06925857e"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_AFFILIATION_TYPE_VALUES: Final = (
    "'advisor', 'board_member', 'contractor', 'employment', "
    "'independent_consultant', 'other', 'principal_ownership'"
)

_STATE_VALUES: Final = "'active', 'retired', 'superseded'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_person_organization_affiliations (
          affiliation_id text PRIMARY KEY,
          principal_id text NOT NULL,
          person_entity_id text NOT NULL
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          -- Nullable: an independent consultant has no organization at all,
          -- and this column must never be backed by a fabricated placeholder
          -- entity to avoid the NULL. See
          -- PersonOrganizationAffiliation's docstring.
          organization_entity_id text
            REFERENCES {SCHEMA}.entities(entity_id) ON DELETE CASCADE,
          job_title text,
          affiliation_type_code text NOT NULL,
          effective_from timestamptz,
          effective_to timestamptz,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          updated_at timestamptz,
          retired_at timestamptz,
          superseded_by_affiliation_id text
            REFERENCES {SCHEMA}.entity_person_organization_affiliations(affiliation_id),
          CONSTRAINT affiliation_id_is_an_opaque_identifier
            CHECK (affiliation_id ~ '^poaf_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_person_affiliation_job_title_is_not_blank
            CHECK (job_title IS NULL OR length(trim(job_title)) > 0),
          CONSTRAINT a_person_affiliation_type_is_known
            CHECK (affiliation_type_code IN ({_AFFILIATION_TYPE_VALUES})),
          CONSTRAINT a_person_affiliation_ends_after_it_starts
            CHECK (
              effective_to IS NULL
              OR effective_from IS NULL
              OR effective_to >= effective_from
            ),
          CONSTRAINT a_person_affiliation_state_is_known
            CHECK (state IN ({_STATE_VALUES})),
          CONSTRAINT a_person_affiliation_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT a_person_affiliation_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          CONSTRAINT a_person_affiliation_names_a_successor_only_when_superseded
            CHECK (superseded_by_affiliation_id IS NULL OR state = 'superseded'),
          CONSTRAINT a_person_affiliation_does_not_supersede_itself
            CHECK (
              superseded_by_affiliation_id IS NULL
              OR superseded_by_affiliation_id <> affiliation_id
            ),
          -- The one case SQL can see directly: a person cannot be affiliated
          -- with itself as its own organization. The domain invariant that
          -- person_entity_id/organization_entity_id name entities of
          -- entity_type 'person'/'organization' respectively is NOT
          -- expressible as a CHECK (it reads another table's row) and is
          -- enforced by the writer -- see PersonOrganizationAffiliation's
          -- docstring.
          CONSTRAINT a_person_affiliation_organization_is_not_the_person
            CHECK (
              organization_entity_id IS NULL
              OR organization_entity_id <> person_entity_id
            ),
          CONSTRAINT a_person_affiliation_is_identified_within_its_principal
            UNIQUE (affiliation_id, principal_id)
        );
        """
    )
    # Composite foreign keys, added after the table exists so both sides of
    # each reference are present: entity_person_organization_affiliations
    # (person_entity_id, principal_id) -> entities(entity_id, principal_id),
    # (organization_entity_id, principal_id) -> entities(entity_id,
    # principal_id) (nullable -- the FK is simply not checked for a NULL
    # value), and the self-referencing (superseded_by_affiliation_id,
    # principal_id) -> entity_person_organization_affiliations(...).
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_person_organization_affiliations
          ADD CONSTRAINT a_person_affiliation_names_a_person_of_its_principal
          FOREIGN KEY (person_entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_person_organization_affiliations
          ADD CONSTRAINT a_person_affiliation_names_an_organization_of_its_principal
          FOREIGN KEY (organization_entity_id, principal_id)
          REFERENCES {SCHEMA}.entities (entity_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_person_organization_affiliations
          ADD CONSTRAINT a_person_affiliation_is_superseded_within_its_principal
          FOREIGN KEY (superseded_by_affiliation_id, principal_id)
          REFERENCES {SCHEMA}.entity_person_organization_affiliations (
            affiliation_id, principal_id
          );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_person_organization_affiliations_by_principal
          ON {SCHEMA}.entity_person_organization_affiliations (principal_id);
        -- The (person, current state) index: the shape almost every read of
        -- this table takes ("this person's affiliation history" and
        -- similar).
        CREATE INDEX entity_person_organization_affiliations_by_person_state
          ON {SCHEMA}.entity_person_organization_affiliations (person_entity_id, state);
        """
    )
    op.execute(
        f"""
        -- At most one OPEN-ENDED (effective_to IS NULL) active affiliation
        -- per person: a person may accumulate many past affiliations, but at
        -- most one of them may be the person's present, ongoing tie at any
        -- moment -- a specific product decision (see the module docstring
        -- and PersonOrganizationAffiliation's docstring, "Current, defined
        -- one way"), not an obvious given, and this is what makes it
        -- unambiguous at the database. A second, already-closed (non-null
        -- effective_to) affiliation for the same person is unaffected by
        -- this index -- do not widen it to cover closed rows too.
        CREATE UNIQUE INDEX an_open_ended_affiliation_is_unique_per_person
          ON {SCHEMA}.entity_person_organization_affiliations (
            principal_id, person_entity_id
          )
          WHERE state = 'active' AND effective_to IS NULL;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_person_organization_affiliations;")
