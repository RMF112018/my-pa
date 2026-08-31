"""Widen the identity-correction family vocabulary for RI-ENT-WP-06b.

Revision ID: 9a3f6c1e8d24
Revises: 8dc3619891bb
Create Date: 2026-08-31

RI-ENT-WP-06b (merge/split wiring for the six deferred Entity-bound record
families). Authorized per `AUTH-RI-ENT-20260830-OPERATOR-001` (untracked,
repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record and the "Merge/split disposition (RULING 2)" section this revision
closes for six of the eight families that section named.

**Purely additive: three `CHECK` constraints widened, nothing else touched.**
`entity_identity_effects.record_family`, `entity_identity_preview_
ambiguities.record_family`, and `entity_identity_ambiguity_settlements.
record_family` each carry a `CHECK (record_family IN (...))` that closes the
vocabulary `IdentityEffectFamily`
(`my_pa.domain.relationship.identity_correction`) is allowed to write. All
three constraints admit the same twelve values as of `8e1c4a7b2d90`
(`'entity','alias','identifier','assignment','relationship','observation',
'proposal','review_case','relationship_memory','memory_proposal',
'memory_context_link','derived_context'`), which is fewer than
`IdentityEffectFamily`'s current eighteen members: RI-ENT-WP-06b added six —
`NAME`, `ORGANIZATION_PROFILE`, `ADDRESS`, `COMMUNICATION_METHOD`,
`PROJECT_PARTICIPATION`, `PERSON_ORGANIZATION_AFFILIATION` — and the
`IdentityCorrectionService`'s own `_write`/`preview`/`split_preview` paths
raise `CheckViolation` the moment any of the six is actually written, which is
how this gap was found (a real `INSERT` into `entity_identity_effects`
against a disposable test database, not a code review). `DROP CONSTRAINT` /
`ADD CONSTRAINT` under the same names, on `8e1c4a7b2d90`'s own precedent for
widening exactly this vocabulary the first time, rather than a new
migration-scoped name for a constraint that already exists.

This is genuinely additive DDL even though it is written as `DROP`/`ADD`
rather than an in-place `ALTER ... ADD CHECK`: PostgreSQL has no syntax to
widen a named `CHECK`'s own value list in place, and the drop-then-add pair
is atomic inside this migration's transaction, so there is no window in which
either table lacks the constraint. No existing row is touched — the widened
list is a strict superset of the twelve values already admitted, so every row
written before this revision continues to satisfy it unchanged. `downgrade()`
restores the twelve-value list exactly, which is fine to run only while no
row in any of the three tables names one of the six new families; RI-ENT-
WP-06b's own database test suite does not leave any such row behind a
`downgrade()` could not already handle by construction, since every disposable
test database this revision's tests create is dropped at the end of its own
test.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`);
these three constraints are not represented in `tables.py`'s Core `Table`
definitions at all (they are enforced only at the database), so there is
nothing there to import from in either direction.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "9a3f6c1e8d24"
down_revision: str | None = "8dc3619891bb"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

_PRIOR_FAMILY_VALUES: Final = (
    "'entity','alias','identifier','assignment','relationship',"
    "'observation','proposal','review_case','relationship_memory',"
    "'memory_proposal','memory_context_link','derived_context'"
)

#: RI-ENT-WP-06b's six additions, appended rather than interleaved so a
#: future reader can see exactly what this revision added versus what it
#: inherited unchanged.
_WIDENED_FAMILY_VALUES: Final = _PRIOR_FAMILY_VALUES + (
    ",'name','organization_profile','address','communication_method',"
    "'project_participation','person_organization_affiliation'"
)


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_effects
          DROP CONSTRAINT an_identity_effect_family_is_known,
          ADD CONSTRAINT an_identity_effect_family_is_known
            CHECK (record_family IN ({_WIDENED_FAMILY_VALUES}));
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_preview_ambiguities
          DROP CONSTRAINT a_preview_ambiguity_family_is_known,
          ADD CONSTRAINT a_preview_ambiguity_family_is_known
            CHECK (record_family IN ({_WIDENED_FAMILY_VALUES}));
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_ambiguity_settlements
          DROP CONSTRAINT an_ambiguity_settlement_family_is_known,
          ADD CONSTRAINT an_ambiguity_settlement_family_is_known
            CHECK (record_family IN ({_WIDENED_FAMILY_VALUES}));
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_ambiguity_settlements
          DROP CONSTRAINT an_ambiguity_settlement_family_is_known,
          ADD CONSTRAINT an_ambiguity_settlement_family_is_known
            CHECK (record_family IN ({_PRIOR_FAMILY_VALUES}));
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_preview_ambiguities
          DROP CONSTRAINT a_preview_ambiguity_family_is_known,
          ADD CONSTRAINT a_preview_ambiguity_family_is_known
            CHECK (record_family IN ({_PRIOR_FAMILY_VALUES}));
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_identity_effects
          DROP CONSTRAINT an_identity_effect_family_is_known,
          ADD CONSTRAINT an_identity_effect_family_is_known
            CHECK (record_family IN ({_PRIOR_FAMILY_VALUES}));
        """
    )
