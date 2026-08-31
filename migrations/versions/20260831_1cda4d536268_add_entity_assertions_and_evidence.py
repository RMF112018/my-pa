"""Add entity_assertions and entity_assertion_evidence (RI-ENT-WP-07).

Revision ID: 1cda4d536268
Revises: 9a3f6c1e8d24
Create Date: 2026-08-31

RI-ENT-WP-07 (assertion/confidence/provenance binding). Closes
`ENTITY-PROVENANCE-001` ("no fact-level certainty/verification binding") for
the six Entity-bound record families RI-ENT-WP-02 through RI-ENT-WP-06 added
(`entity_names`, `entity_organization_profiles`, `entity_addresses`,
`entity_communication_methods`, `entity_project_participations`,
`entity_person_organization_affiliations`), none of which carried fact-level
provenance before this revision. Authorized per
`AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings.

**What this revision does, in one sentence.** It adds two new tables --
`entity_assertions` (one fact-level claim about a field or record of one of
the six families) and `entity_assertion_evidence` (what backs, supports, or
contradicts one assertion) -- and touches nothing else: no existing table,
column, or constraint is altered.

**Not a generic EAV store.** The source audit's own section D.10 is explicit
that this binding must not turn core storage into a generic key-value plane.
`entity_assertions` binds TO a normalized record already owned by one of the
six families above (exactly one nullable `target_*` column per family, a
`CHECK` enforcing exactly one is non-null -- the same shape
`entity_fact_evidence_links` (`WP-RI-A-01`) already uses for its own five
target columns, extended here to a family-of-six subject), never the
reverse; nothing here lets a caller store an arbitrary field name and value
pair with no owning table.

**`assertion_status` is a discrete, unordered epistemic vocabulary, never a
confidence score.** The source audit's own proposed field names for this
work package -- a numeric or banded "confidence" -- are not used anywhere in
this codebase.
`tests/architecture/test_relationship_scoring_surface_is_denied.py` denies
`confidence|certainty|probability|likelihood|propensity` outright, along
with graded-band tokens (`tier`, `grade`, `rank`, `percentile`) a
numeric-in-spirit vocabulary could hide behind. `AssertionStatus`
(`verified`/`best_supported`/`inferred`/`unresolved`/`awaiting_confirmation`/
`contradicted`/`superseded`) is the audit's own named alternative: seven
discrete, unordered categories, never sorted, compared, or weighted anywhere
in this codebase -- see `AssertionStatus`'s own docstring
(`my_pa.domain.relationship.governance`) for the full argument and the tests
that prove it behaviourally. This guard was run against this revision's
schema and domain additions before it landed and passed with zero denials
-- see the campaign document's "Test evidence" section for the exact
command and count.

**`asserted_by` reuses `MutationAuthority`, `role` (on the evidence table)
reuses `EvidenceRole` -- neither vocabulary is reinvented.**
`MutationAuthority`'s own docstring already states why: "Shared by
`entity_mutation_events` and `entity_fact_evidence_links` because they
answer the same question about the same act: what admitted this. Two
vocabularies would let the ledger and the evidence disagree about a single
write" -- restated here for a third record answering the identical
question. `EvidenceRole` is exactly the audit's own "evidence_role
direct/supporting/counterevidence" ask, already declared and already reused
by `entity_fact_evidence_links` and `entity_proposal_evidence_links`.

**`predicate_code` is free text and nullable.** It names which field of the
target record one assertion is about; `NULL` means the assertion is about
the whole record. A closed vocabulary across the dozens of heterogeneous
field names the six target families carry between them would need constant
widening for no safety benefit a free-text column does not already give.

**`supersedes_assertion_id` points backward** (the new row names the old one
it replaces), the opposite direction from the sibling families'
`superseded_by_*` columns, and the reversal is deliberate: the audit's own
D.10 text names the field `supersedes_assertion_id`, which only reads
correctly naming the new row's own reference. **No destructive replacement**
follows directly: superseding an assertion is an `INSERT` of the new row
plus an `UPDATE` of the old row's `state`/`assertion_status`/`version`/
`updated_at` alone -- nothing here ever deletes an assertion row or an
evidence row that cites one, and no application code this revision adds does
either (`tests/database/test_entity_assertion_provenance.py`'s supersession
test proves this against a real server, not by inspection alone).

**`target_organization_profile_entity_id` is a plain, single-column FK with
`ON UPDATE CASCADE`, not a composite `(id, principal_id)` one like the other
five targets.** `entity_organization_profiles.entity_id` is simultaneously
that table's primary key and its foreign key to `entities` (see
`EntityOrganizationProfile`'s own docstring); it carries no separate
`UNIQUE(entity_id, principal_id)` a composite reference could target. A
merge's reparenting of an organization profile is a literal `UPDATE
entity_organization_profiles SET entity_id = :survivor WHERE entity_id IN
(:merged_away)` (`reparent_entity_reference`,
`src/my_pa/infrastructure/persistence/entity.py`), and `ON UPDATE CASCADE`
is what lets Postgres carry an assertion's reference along automatically the
moment that `UPDATE` runs -- verified by a real database test
(`tests/database/test_entity_assertion_provenance.py::
test_an_assertion_bound_to_an_organization_profile_follows_the_profile_through_a_merge`),
not assumed. Same-Principal for this one branch is a stated residual the
writer must check, exactly as `entity_fact_evidence_links`' own docstring
already states for its `capture_span_id`/`knowledge_id` columns.

**Merge/split: `entity_assertions` and `entity_assertion_evidence` are
deliberately NOT added to `IdentityEffectFamily`/`MergeFamily`.** Confirmed
before this decision was made, not assumed: `entity_fact_evidence_links` --
the closest existing structural precedent, same shape (references a fact by
the fact's own surrogate key, cites evidence) -- is itself not a member of
`IdentityEffectFamily` either. Five of `entity_assertions`' six `target_*`
columns reference a sibling row by that row's own stable surrogate key
(`entity_name_id`, `entity_address_id`, `communication_method_id`,
`participation_id`, `affiliation_id`), which a merge's
`reparent_entity_reference` never rewrites -- only the `entity_id` column
*on the target row itself* changes, and a row a merge coalesces (state
flips to `superseded`) keeps its own surrogate key and stays resolvable
through its own `superseded_by_*` chain. The sixth,
`target_organization_profile_entity_id`, is handled by the `ON UPDATE
CASCADE` FK above rather than by `IdentityEffectFamily` membership.
`entity_assertion_evidence` carries no `entity_id` column of any kind --
its only references are `assertion_id` (opaque, not an entity) and the same
evidence-source trio `entity_fact_evidence_links` already carries unwired --
so there is no row for a merge to touch, on the exact
`entity_role_types`/`entity_discipline_types` argument the campaign
document's "Merge/split disposition" section already gives for those two
tables. See the campaign document's "Merge/split disposition" section for
the full ledger entry this revision adds.

**Downgrade.** Drops both tables. Purely additive DDL, so this is safe
whenever no row exists yet, which is true of every disposable test database
this revision's own tests create (each dropped at the end of its own test).
`tests/schema/test_entity_assertion_provenance_migration.py`'s downgrade
test proves the round trip: upgrade to head, downgrade one step, confirm
both tables and every constraint are gone and the schema matches the
pre-migration state, then re-upgrade.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`);
reflected in `src/my_pa/infrastructure/persistence/tables.py`'s
`entity_assertions`/`entity_assertion_evidence` `Table` declarations for
runtime ORM access only -- this migration does not read either.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "1cda4d536268"
down_revision: str | None = "9a3f6c1e8d24"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The opaque-identifier suffix shape `IdKind`'s own `_SUFFIX_PATTERN`
#: enforces in Python (`my_pa.domain.common.identifiers`), restated here
#: because this migration writes DDL out rather than importing it (`D-48`,
#: `D-69`) -- the same literal `17149a48fa30` and every sibling migration on
#: this chain already uses for their own `_is_an_opaque_identifier` CHECKs.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

_ASSERTION_STATUS_VALUES: Final = (
    "'verified', 'best_supported', 'inferred', 'unresolved', "
    "'awaiting_confirmation', 'contradicted', 'superseded'"
)
_MUTATION_AUTHORITY_VALUES: Final = (
    "'user_confirmed_assertion', 'review_accepted', 'system_deterministic'"
)
_ASSERTION_STATE_VALUES: Final = "'active', 'retired', 'superseded'"
_EVIDENCE_ROLE_VALUES: Final = "'direct', 'supporting', 'counterevidence'"

#: `ENTITY_CHANGE_REASON_LIMIT` (`my_pa.domain.relationship.governance`),
#: restated as a literal because this migration writes DDL out rather than
#: importing from application code (`D-48`, `D-69`); the two have to agree,
#: and a future widening of the constant must update this literal to match.
_REASON_LIMIT: Final = 500


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_assertions (
          assertion_id text PRIMARY KEY,
          principal_id text NOT NULL,
          target_entity_name_id text,
          target_entity_address_id text,
          target_communication_method_id text,
          target_participation_id text,
          target_affiliation_id text,
          target_organization_profile_entity_id text
            REFERENCES {SCHEMA}.entity_organization_profiles(entity_id)
            ON DELETE CASCADE ON UPDATE CASCADE,
          predicate_code text,
          assertion_status text NOT NULL,
          rationale text,
          asserted_by text NOT NULL,
          observed_at timestamptz,
          verified_at timestamptz,
          supersedes_assertion_id text,
          state text NOT NULL DEFAULT 'active',
          version integer NOT NULL DEFAULT 1,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz,
          retired_at timestamptz,
          CONSTRAINT assertion_id_is_an_opaque_identifier
            CHECK (assertion_id ~ '^east_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_assertion_status_is_known
            CHECK (assertion_status IN ({_ASSERTION_STATUS_VALUES})),
          CONSTRAINT an_assertion_authority_is_known
            CHECK (asserted_by IN ({_MUTATION_AUTHORITY_VALUES})),
          CONSTRAINT an_assertion_state_is_known
            CHECK (state IN ({_ASSERTION_STATE_VALUES})),
          CONSTRAINT an_assertion_version_is_positive
            CHECK (version >= 1),
          CONSTRAINT an_assertion_names_exactly_one_target
            CHECK (
              (target_entity_name_id IS NOT NULL)::int
              + (target_entity_address_id IS NOT NULL)::int
              + (target_communication_method_id IS NOT NULL)::int
              + (target_participation_id IS NOT NULL)::int
              + (target_affiliation_id IS NOT NULL)::int
              + (target_organization_profile_entity_id IS NOT NULL)::int = 1
            ),
          CONSTRAINT an_assertion_predicate_code_is_not_blank
            CHECK (predicate_code IS NULL OR length(trim(predicate_code)) > 0),
          CONSTRAINT an_assertion_rationale_is_not_blank
            CHECK (
              rationale IS NULL
              OR (length(trim(rationale)) > 0 AND length(rationale) <= {_REASON_LIMIT})
            ),
          CONSTRAINT an_assertion_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          CONSTRAINT an_assertion_does_not_supersede_itself
            CHECK (supersedes_assertion_id IS NULL OR supersedes_assertion_id <> assertion_id),
          CONSTRAINT an_assertion_is_identified_within_its_principal
            UNIQUE (assertion_id, principal_id)
        );
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertions
          ADD CONSTRAINT an_assertion_names_a_name_of_its_principal
          FOREIGN KEY (target_entity_name_id, principal_id)
          REFERENCES {SCHEMA}.entity_names (entity_name_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertions
          ADD CONSTRAINT an_assertion_names_an_address_of_its_principal
          FOREIGN KEY (target_entity_address_id, principal_id)
          REFERENCES {SCHEMA}.entity_addresses (entity_address_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertions
          ADD CONSTRAINT an_assertion_names_a_communication_method_of_its_principal
          FOREIGN KEY (target_communication_method_id, principal_id)
          REFERENCES {SCHEMA}.entity_communication_methods (communication_method_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertions
          ADD CONSTRAINT an_assertion_names_a_participation_of_its_principal
          FOREIGN KEY (target_participation_id, principal_id)
          REFERENCES {SCHEMA}.entity_project_participations (participation_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertions
          ADD CONSTRAINT an_assertion_names_an_affiliation_of_its_principal
          FOREIGN KEY (target_affiliation_id, principal_id)
          REFERENCES {SCHEMA}.entity_person_organization_affiliations (affiliation_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertions
          ADD CONSTRAINT an_assertion_supersedes_within_its_principal
          FOREIGN KEY (supersedes_assertion_id, principal_id)
          REFERENCES {SCHEMA}.entity_assertions (assertion_id, principal_id);
        """
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_principal "
        f"ON {SCHEMA}.entity_assertions (principal_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_supersedes "
        f"ON {SCHEMA}.entity_assertions (supersedes_assertion_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_entity_name "
        f"ON {SCHEMA}.entity_assertions (target_entity_name_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_entity_address "
        f"ON {SCHEMA}.entity_assertions (target_entity_address_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_communication_method "
        f"ON {SCHEMA}.entity_assertions (target_communication_method_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_participation "
        f"ON {SCHEMA}.entity_assertions (target_participation_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_affiliation "
        f"ON {SCHEMA}.entity_assertions (target_affiliation_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertions_by_organization_profile "
        f"ON {SCHEMA}.entity_assertions (target_organization_profile_entity_id);"
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_assertion_evidence (
          evidence_id text PRIMARY KEY,
          principal_id text NOT NULL,
          assertion_id text NOT NULL,
          entity_observation_id text,
          capture_span_id text,
          knowledge_id text,
          role text NOT NULL,
          source_locator text,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT evidence_id_is_an_opaque_identifier
            CHECK (evidence_id ~ '^easev_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_assertion_evidence_role_is_known
            CHECK (role IN ({_EVIDENCE_ROLE_VALUES})),
          CONSTRAINT assertion_evidence_names_exactly_one_record
            CHECK (
              (entity_observation_id IS NOT NULL)::int
              + (capture_span_id IS NOT NULL)::int
              + (knowledge_id IS NOT NULL)::int = 1
            ),
          CONSTRAINT assertion_evidence_source_locator_is_not_blank
            CHECK (source_locator IS NULL OR length(trim(source_locator)) > 0),
          CONSTRAINT assertion_evidence_source_locator_is_bounded
            CHECK (source_locator IS NULL OR length(source_locator) <= {_REASON_LIMIT})
        );
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertion_evidence
          ADD CONSTRAINT assertion_evidence_names_an_assertion_of_its_principal
          FOREIGN KEY (assertion_id, principal_id)
          REFERENCES {SCHEMA}.entity_assertions (assertion_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assertion_evidence
          ADD CONSTRAINT assertion_evidence_cites_an_observation_of_its_principal
          FOREIGN KEY (entity_observation_id, principal_id)
          REFERENCES {SCHEMA}.entity_observations (observation_id, principal_id)
          ON DELETE CASCADE;
        """
    )
    op.execute(
        f"CREATE INDEX entity_assertion_evidence_by_principal "
        f"ON {SCHEMA}.entity_assertion_evidence (principal_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertion_evidence_by_assertion "
        f"ON {SCHEMA}.entity_assertion_evidence (assertion_id);"
    )
    op.execute(
        f"CREATE INDEX entity_assertion_evidence_by_observation "
        f"ON {SCHEMA}.entity_assertion_evidence (entity_observation_id);"
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_assertion_evidence;")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_assertions;")
