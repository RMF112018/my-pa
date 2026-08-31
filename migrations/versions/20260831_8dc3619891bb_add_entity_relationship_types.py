"""Add entity_relationship_types (RI-ENT-WP-06a).

Revision ID: 8dc3619891bb
Revises: 17149a48fa30
Create Date: 2026-08-31

RI-ENT-WP-06a (relationship taxonomy expansion). Closes `ENTITY-REL-001`
("closed relationship vocabulary (15 of 22 required codes)"). Authorized per
`AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings. This is PR1 of a two-PR
increment; PR2 (merge/split wiring for the six deferred WP-02/WP-04/WP-05
record families) is separate, later, independent work this revision does not
touch.

**What this revision does, in one sentence.** It replaces the frozen,
Alembic-CHECK-closed `entity_relationships.relationship_type` vocabulary
(`9def3c2e63bb`'s `an_entity_relationship_type_is_known`, fifteen values) with
a table-backed, genuinely extensible taxonomy (`entity_relationship_types`,
global and Principal-independent, the same shape `entity_role_types`/
`entity_discipline_types` already established for RI-ENT-WP-04), seeded with
the original fifteen codes plus twenty new ones the audit's Record Element
Inventory names for corporate lineage, brand/DBA identity, and project
technical-review/coordination relationships -- and re-points
`entity_relationships.relationship_type` at that table by foreign key instead
of by CHECK.

**Why a table and not a wider CHECK.** The audit's own operator-decision
section (R.3) recommends "table-backed extensible taxonomy (recommended)
versus continuing Alembic-frozen CHECK enums" -- precisely because a CHECK
requires a migration (and a matching, disclosed application release) every
time the vocabulary needs one more code, which is the defect `ENTITY-REL-001`
names. `entity_role_types`/`entity_discipline_types` already proved this
pattern out for two other closed-in-effect vocabularies in `f5b06925857e`;
this revision applies the same pattern to relationship types, the family
their own docstrings explicitly flagged as "one representation family early"
(`EntityRoleType`'s docstring, `src/my_pa/domain/relationship/entity.py`).

**Migration safety, the three (four) ordered steps.** Order matters here for
reviewability and for an automatic proof that nothing existing breaks:

1. **Seed the fifteen EXISTING codes first**, character-for-character
   identical to `EntityRelationshipType`'s current members -- no renumbering,
   renaming, reordering, or dropping.
2. **Swap the constraint**: `DROP CONSTRAINT an_entity_relationship_type_is_known`
   (the CHECK `9def3c2e63bb` installed) and add a new
   `FOREIGN KEY (relationship_type) REFERENCES entity_relationship_types
   (relationship_type_code)`, validated (no `NOT VALID`). Because step 1 has
   already seeded exactly the fifteen values the old CHECK admitted, and
   nothing before this revision could have written any other value, adding
   this FK **validated** is the proof mechanism that every existing
   `entity_relationships` row survives: if any row's `relationship_type` were
   not among the seeded codes, Postgres would refuse this `ALTER TABLE`
   outright and the migration would abort here, before touching anything
   else. `tests/schema/test_entity_relationship_types_migration.py` seeds
   representative old-code rows against the predecessor revision and proves
   they read back unchanged after this upgrade.
3. **Only then insert the twenty new codes** as additional taxonomy rows --
   harmless to add after the FK swap since nothing yet references them from
   `entity_relationships`.
4. **Wire the two definitional inverse pairs** discovered purely from the
   code names (see "Inverse pairing" below), by `UPDATE` after all
   thirty-five rows exist -- avoids an insert-order FK problem where a code's
   inverse has not been inserted yet.

**Table shape.** `entity_relationship_types` is global and Principal-
independent (no `principal_id`), matching `entity_role_types`/
`entity_discipline_types` exactly -- see
`tests/architecture/test_user_owned_tables_are_partitioned.py`'s
`UNPARTITIONED_USER_OWNED` entry for the same reasoning restated for this
table. `status` reuses the shared `TaxonomyEntryStatus` (`active`/
`deprecated`) `entity_role_types`/`entity_discipline_types` already
established, rather than inventing a fourth status vocabulary for the same
"open to new writes or not" question (RI-ENT-WP-04's own `TaxonomyEntryStatus`
docstring explains why this is shared and the record-lifecycle `state` enums
elsewhere on this plane are not).

**Every code is directed (`directed = true` for all thirty-five).**
`EntityRelationshipType`'s own docstring already describes "the kinds of
DIRECTED relationship between two entities" -- there is no undirected code in
the frozen fifteen or the audit's twenty, and this revision does not invent
one.

**Allowed source/target entity type -- descriptive metadata, not an enforced
constraint.** `source_entity_type`/`target_entity_type` are nullable `text`
columns constrained by CHECK to `'person'`/`'organization'` (matching
`EntityType`'s two identity-plane members) when the audit's own text states
the pair unambiguously and universally for a code; left `NULL` otherwise
rather than guessed (RULING 3: "never infer, never guess" -- restated here as
"never guess a type pair the audit does not state"). A two-nullable-column
design was chosen over a junction table because every code in this
vocabulary that has an audit-stated type pair states exactly one pair, never
several admissible combinations per side -- the simplest normalized shape
that is faithful to what the audit actually recommends, with no array, no
JSONB (RULING 3). **This is deliberately not database-enforced against
`entity_relationships` rows**: PostgreSQL cannot check that `from_entity_id`/
`to_entity_id` name entities of a particular `entity_type` without reading
another table's row (the same non-enforcement every sibling family on this
plane already accepts for its own entity-type expectations), so these two
columns describe the taxonomy entry, not a live constraint on edges written
against it.

Nine of the twenty new codes get an explicit organization/organization pair,
directly off the audit's own framing of each as a corporate-identity or
corporate-lineage edge (`brand_of`, `operates_as`, `dba_of`,
`historical_identity_of`, `parent_of`, `subsidiary_of`, `acquired_by`,
`practice_of`, `contracting_entity_for`). Two get an organization-only
*source* with no stated target (`utility_provider_for`,
`permitting_authority_for` -- a utility provider or a permitting authority is
always an organization, per `OrganizationKindCode.UTILITY`/
`GOVERNMENT_AUTHORITY`, but the audit does not state what it targets
narrowly enough to commit a value). The remaining nine new codes
(`managed_by`, `owner_representative_for`, `project_controls_advisor_to`,
`technical_reviewer_of`, `peer_reviewer_of`, `design_coordinates_with`,
`seller_developer_for`, `sales_marketing_agent_for`,
`sequence_interfaces_with`) get `NULL`/`NULL` -- the audit's text describes
each as a project-facing role without stating a single admissible type pair,
and a guess here would be exactly the kind of invention RULING 3 forbids. All
fifteen pre-existing codes also get `NULL`/`NULL`: this revision does not
retroactively assert a type pair for a code it did not design, on the same
"never guess" basis.

**`allows_project_scope`.** `true` for the fifteen of the twenty new codes
the audit frames as inherently project-facing (`brand_of`, `operates_as`,
`dba_of` -- audit: "brand may itself be project-facing identity";
`contracting_entity_for`, `technical_reviewer_of`, `peer_reviewer_of` --
audit: explicitly "project-scoped"; and `managed_by`,
`owner_representative_for`, `project_controls_advisor_to`,
`design_coordinates_with`, `utility_provider_for`,
`permitting_authority_for`, `seller_developer_for`,
`sales_marketing_agent_for`, `sequence_interfaces_with` -- each names a role
that, per the audit's TBR walkthroughs (section L), is ordinarily exercised
in a specific project's context via `entity_relationships.scope_entity_id`,
the column that already carries project scope for any relationship type,
untouched by this revision). `false` for the five pure corporate-lineage
codes whose fact is independent of any one project
(`historical_identity_of`, `parent_of`, `subsidiary_of`, `acquired_by`,
`practice_of`) and for all fifteen pre-existing codes (unchanged from their
current, already-live behavior).

**`cardinality_rule` is left `NULL` for every one of the thirty-five rows
this revision seeds.** The audit is explicit for `parent_of` that "active
corporate parent may be constrained by evidence/business rules rather than
DB singleton assumptions" (audit section L) -- i.e. the audit itself warns
against assuming a DB-enforced single-current-parent rule, which is exactly
what leaving this column empty avoids asserting. No other code's cardinality
is stated narrowly enough in the audit text to populate here. The column
exists for a future revision to populate deliberately, per code, once a
concrete rule is approved -- not guessed now to fill the column.

**Inverse pairing -- only two pairs, both self-evident from the code names
alone, both members already in the final thirty-five-code vocabulary
(RULING 2: never infer a relationship type from a name or string position,
extended here to never invent an unauthorized semantic pairing).**

- `parent_of` <-> `subsidiary_of`: A `parent_of` B if and only if B
  `subsidiary_of` A -- a textbook structural inverse pair, and the audit's
  own text pairs them directly ("`parent_of`: directed parent -> subsidiary").
- `manages` (one of the fifteen pre-existing codes) <-> `managed_by` (one of
  the twenty new codes): A `manages` B if and only if B `managed_by` A --
  equally self-evident from the names, and the reason `managed_by` is in
  this revision's required list in the first place (the audit's own
  Record Element Inventory names it as a new code, not as a rename of
  `manages`).

No other pair is wired. The audit's own text states an explicit inverse for
`technical_reviewer_of` ("inverse `reviewed_by`", audit section L) -- but
`reviewed_by` is not one of the twenty required codes for this revision, so
per RULING 2 this revision does **not** invent it; `technical_reviewer_of.
inverse_type_code` stays `NULL`. `peer_reviewer_of`, `design_coordinates_with`,
and `sequence_interfaces_with` read as mutual/symmetric relationships in
English, but nothing in the audit or the required code list states a
declared inverse (or that a code may be its own inverse), so all three stay
`NULL` rather than guessed.

**Downgrade.** Drops the FK, restores `9def3c2e63bb`'s original fifteen-value
CHECK constraint verbatim (`_RELATIONSHIP_TYPE_VALUES`, copied faithfully,
not paraphrased), then drops `entity_relationship_types`. This is destructive
DDL and belongs only in `downgrade()` (RULING 2). **If any `entity_relationships`
row uses one of the twenty new codes when downgrade runs, the restored CHECK
correctly refuses it and the downgrade aborts with an IntegrityError.** This
is intended, safe behavior, not a bug: the old schema genuinely cannot
represent the new codes, and a downgrade that silently deleted or rewrote
such a row to "succeed" would be the actual hazard.  "No orphaning" here means
what it means throughout this campaign: no row is left pointing at a deleted
taxonomy row and no foreign key is left broken -- not "every downgrade always
succeeds regardless of the data it would have to discard invisibly."
`tests/schema/test_entity_relationship_types_migration.py`'s downgrade test
seeds only pre-existing-code data, downgrades, and proves the original
fifteen-code CHECK is back with the data intact -- the case this revision
promises to support without loss.

**Domain layer.** `EntityRelationshipType` (the frozen fifteen-member
`StrEnum` application code keys off) is **not widened** by this revision --
see its own docstring for why: it is deeply threaded through live
application code (`application/commands.py`'s directed-write validation,
`contracts/ports.py`, `infrastructure/persistence/entity.py`,
`adapters/normalization.py`, the HTTP/MCP transport and capability
surfaces) in a way none of WP-02/03/04/05's six deferred record families
are, so widening it here would be a second, much larger surface change this
single-purpose revision does not need to make in order to close
`ENTITY-REL-001` at the schema/taxonomy level. `entity_relationship_types` is
the new, authoritative, DB-level source of truth listing all thirty-five
codes (the fifteen well-known ones and the twenty new ones);
`EntityRelationshipType` remains the closed set of well-known constants the
existing, already-shipped application write path validates against. A
caller cannot yet create an `entity_relationships` row through the existing
typed command path using one of the twenty new codes -- that is disclosed
here, in the enum's own docstring, and in the campaign document, not left
implicit -- and is exactly the kind of follow-on wiring this campaign already
defers by the same pattern for the six WP-02/04/05 families (see
"Merge/split disposition").

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`);
the closed-set literals are frozen at this revision. Reflected in
`src/my_pa/infrastructure/persistence/tables.py`'s `entity_relationship_types`
`Table` declaration and its rewritten `entity_relationships` declaration
(the old `_one_of(relationship_type, EntityRelationshipType, ...)` CHECK
replaced by the matching `ForeignKeyConstraint`), for runtime ORM access
only -- this migration does not read either.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "8dc3619891bb"
down_revision: str | None = "17149a48fa30"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: `9def3c2e63bb`'s original CHECK literal, copied verbatim for `downgrade()`.
#: Not derived from `EntityRelationshipType` -- a hand-written literal frozen
#: at that revision, restated here character-for-character so the downgrade
#: recreates exactly what existed before this revision, not what the enum
#: happens to say today.
_RELATIONSHIP_TYPE_VALUES: Final = (
    "'affiliated_with', 'approver_for', 'consultant_to', 'contractor_on', "
    "'decision_maker_for', 'leads', 'manages', 'member_of', "
    "'primary_contact_for', 'reports_to', 'represents', 'responsible_for', "
    "'subcontractor_to', 'vendor_for', 'works_for'"
)

_TAXONOMY_STATUS_VALUES: Final = "'active', 'deprecated'"

_ENTITY_TYPE_VALUES: Final = "'organization', 'person'"

#: The fifteen pre-existing `EntityRelationshipType` codes, seeded first and
#: character-for-character identical to the enum -- see the module docstring,
#: step 1. `(code, label)`; every other column takes its table default
#: (`directed = true` is set explicitly since it is NOT NULL with no default).
_EXISTING_CODES: Final = (
    ("works_for", "Works For"),
    ("reports_to", "Reports To"),
    ("represents", "Represents"),
    ("manages", "Manages"),
    ("leads", "Leads"),
    ("responsible_for", "Responsible For"),
    ("approver_for", "Approver For"),
    ("decision_maker_for", "Decision Maker For"),
    ("primary_contact_for", "Primary Contact For"),
    ("member_of", "Member Of"),
    ("consultant_to", "Consultant To"),
    ("contractor_on", "Contractor On"),
    ("subcontractor_to", "Subcontractor To"),
    ("vendor_for", "Vendor For"),
    ("affiliated_with", "Affiliated With"),
)

#: The twenty new codes this revision adds, closing `ENTITY-REL-001`.
#: `(code, label, source_entity_type, target_entity_type, allows_project_scope)`.
#: See the module docstring for the reasoning behind each column's value,
#: per code.
_NEW_CODES: Final = (
    ("brand_of", "Brand Of", "organization", "organization", True),
    ("operates_as", "Operates As", "organization", "organization", True),
    ("dba_of", "DBA Of", "organization", "organization", True),
    (
        "historical_identity_of",
        "Historical Identity Of",
        "organization",
        "organization",
        False,
    ),
    ("parent_of", "Parent Of", "organization", "organization", False),
    ("subsidiary_of", "Subsidiary Of", "organization", "organization", False),
    ("acquired_by", "Acquired By", "organization", "organization", False),
    ("practice_of", "Practice Of", "organization", "organization", False),
    (
        "contracting_entity_for",
        "Contracting Entity For",
        "organization",
        "organization",
        True,
    ),
    ("managed_by", "Managed By", None, None, True),
    (
        "owner_representative_for",
        "Owner's Representative For",
        None,
        None,
        True,
    ),
    (
        "project_controls_advisor_to",
        "Project Controls Advisor To",
        None,
        None,
        True,
    ),
    ("technical_reviewer_of", "Technical Reviewer Of", None, None, True),
    ("peer_reviewer_of", "Peer Reviewer Of", None, None, True),
    ("design_coordinates_with", "Design Coordinates With", None, None, True),
    ("utility_provider_for", "Utility Provider For", "organization", None, True),
    (
        "permitting_authority_for",
        "Permitting Authority For",
        "organization",
        None,
        True,
    ),
    ("seller_developer_for", "Seller/Developer For", None, None, True),
    (
        "sales_marketing_agent_for",
        "Sales/Marketing Agent For",
        None,
        None,
        True,
    ),
    (
        "sequence_interfaces_with",
        "Sequence Interfaces With",
        None,
        None,
        True,
    ),
)

#: The two definitional inverse pairs -- see the module docstring, "Inverse
#: pairing". Each tuple is (code, its inverse code), and both directions are
#: written so the update below is symmetric.
_INVERSE_PAIRS: Final = (
    ("parent_of", "subsidiary_of"),
    ("subsidiary_of", "parent_of"),
    ("manages", "managed_by"),
    ("managed_by", "manages"),
)


def _sql_literal(value: str | None) -> str:
    """A single-quoted SQL string literal, `NULL` for `None`.

    The seed values below are fixed, hand-written literals (never user
    input), and some carry an apostrophe (`Owner's Representative For`) that
    would otherwise terminate the literal early, so quoting/escaping is
    applied uniformly rather than trusted to be unnecessary for any one row.
    """
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_relationship_types (
          relationship_type_code text PRIMARY KEY,
          label text NOT NULL,
          directed boolean NOT NULL,
          inverse_type_code text
            REFERENCES {SCHEMA}.entity_relationship_types(relationship_type_code),
          source_entity_type text,
          target_entity_type text,
          allows_project_scope boolean NOT NULL DEFAULT false,
          cardinality_rule text,
          status text NOT NULL DEFAULT 'active',
          CONSTRAINT a_relationship_type_code_is_not_blank
            CHECK (length(trim(relationship_type_code)) > 0),
          CONSTRAINT a_relationship_type_label_is_not_blank
            CHECK (length(trim(label)) > 0),
          CONSTRAINT a_relationship_type_cardinality_rule_is_not_blank
            CHECK (cardinality_rule IS NULL OR length(trim(cardinality_rule)) > 0),
          CONSTRAINT a_relationship_type_source_entity_type_is_known
            CHECK (source_entity_type IS NULL OR source_entity_type IN ({_ENTITY_TYPE_VALUES})),
          CONSTRAINT a_relationship_type_target_entity_type_is_known
            CHECK (target_entity_type IS NULL OR target_entity_type IN ({_ENTITY_TYPE_VALUES})),
          CONSTRAINT a_relationship_type_status_is_known
            CHECK (status IN ({_TAXONOMY_STATUS_VALUES})),
          -- The one case SQL can see directly: a code is never its own
          -- declared inverse. Nothing in this revision's seed data trips
          -- this; it guards a future row.
          CONSTRAINT a_relationship_type_does_not_invert_itself
            CHECK (inverse_type_code IS NULL OR inverse_type_code <> relationship_type_code)
        );
        """
    )

    # --- step 1: seed the fifteen EXISTING codes first ----------------------
    # Character-for-character identical to EntityRelationshipType's current
    # members. This has to land before the constraint swap below: the FK add
    # is only a genuine proof that every existing entity_relationships row
    # survives if the values it can already hold are already present here.
    for code, label in _EXISTING_CODES:
        op.execute(
            f"""
            INSERT INTO {SCHEMA}.entity_relationship_types
              (relationship_type_code, label, directed)
            VALUES ({_sql_literal(code)}, {_sql_literal(label)}, true);
            """  # noqa: S608
        )

    # --- step 2: swap the constraint -----------------------------------------
    # Drop 9def3c2e63bb's CHECK and replace it with a validated (not NOT
    # VALID) foreign key. Because step 1 already seeded exactly the fifteen
    # values the old CHECK admitted, this ALTER TABLE is the proof mechanism:
    # if any existing row's relationship_type were not among them, Postgres
    # refuses the ALTER outright and this migration aborts here.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          DROP CONSTRAINT an_entity_relationship_type_is_known;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          ADD CONSTRAINT an_entity_relationship_type_is_seeded
          FOREIGN KEY (relationship_type)
          REFERENCES {SCHEMA}.entity_relationship_types (relationship_type_code);
        """
    )

    # --- step 3: only now insert the twenty new codes ------------------------
    # Harmless to add after the FK swap: nothing in entity_relationships
    # references any of these yet, since nothing before this revision could.
    for code, label, source_type, target_type, allows_project_scope in _NEW_CODES:
        op.execute(
            f"""
            INSERT INTO {SCHEMA}.entity_relationship_types
              (relationship_type_code, label, directed, source_entity_type,
               target_entity_type, allows_project_scope)
            VALUES (
              {_sql_literal(code)}, {_sql_literal(label)}, true,
              {_sql_literal(source_type)}, {_sql_literal(target_type)},
              {"true" if allows_project_scope else "false"}
            );
            """  # noqa: S608
        )

    # --- step 4: wire the two definitional inverse pairs ---------------------
    # By UPDATE, after all thirty-five rows exist -- inserting the inverse
    # pointer inline would fail for whichever side is inserted first, since
    # its partner does not exist yet at that point.
    for code, inverse_code in _INVERSE_PAIRS:
        op.execute(
            f"""
            UPDATE {SCHEMA}.entity_relationship_types
              SET inverse_type_code = {_sql_literal(inverse_code)}
              WHERE relationship_type_code = {_sql_literal(code)};
            """  # noqa: S608
        )


def downgrade() -> None:
    # Drop the FK and restore 9def3c2e63bb's original CHECK verbatim. If any
    # entity_relationships row carries one of the twenty new codes, this
    # restored CHECK correctly refuses it and the downgrade aborts here --
    # intended, safe behavior (the old schema cannot represent the new
    # codes), not orphaning. See the module docstring, "Downgrade".
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          DROP CONSTRAINT an_entity_relationship_type_is_seeded;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          ADD CONSTRAINT an_entity_relationship_type_is_known
          CHECK (relationship_type IN ({_RELATIONSHIP_TYPE_VALUES}));
        """
    )
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_relationship_types;")
