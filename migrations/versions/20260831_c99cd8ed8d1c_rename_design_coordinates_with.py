"""Rename entity_relationship_types.design_coordinates_with (WP-08 blocker close).

Revision ID: c99cd8ed8d1c
Revises: 1cda4d536268
Create Date: 2026-08-31

Authorized per `AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository
root); see `docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full
campaign record. This is the WP-08 blocker-clearing rename the campaign
document's "WP-08 blocker cleared: `EntityRelationshipType` widened to 34 of
35 codes" section (and `EntityRelationshipType`'s own prior docstring,
`src/my_pa/domain/relationship/entity.py`) left as a disclosed, unresolved
gap: `8dc3619891bb` (RI-ENT-WP-06a) seeded `entity_relationship_types` with
thirty-five codes, one of which -- `design_coordinates_with` -- could not be
added as an `EntityRelationshipType` `StrEnum` member because
`tests/architecture/test_relationship_scoring_surface_is_denied.py` (an
operator-reserved guard this campaign is forbidden from touching, weakening,
or reasoning around) tokenizes the name to `design`, `coordinates`, `with`
and `coordinates` fullmatches that guard's
`latitude|longitude|geolocation|coordinates|whereabouts|tracking` ->
"location tracking" denial pattern -- a correct-as-designed mechanical match
and a false positive at the semantic level, since the taxonomy entry actually
means design-discipline coordination between two project participants (an
architect and a structural engineer coordinating design, say), not
geolocation. The campaign owner's ruling (binding): rename the taxonomy code
to a token-clean equivalent, add it to the enum, and close the gap to 35/35,
rather than touch the guard or ship a write path that can emit a code the
read path rejects.

**Chosen replacement: `design_coordination_with`.** Verified, not assumed,
against the guard's own `tokens()`/`denials()` functions before committing to
it in code:

    >>> import tests.architecture.test_relationship_scoring_surface_is_denied as guard
    >>> guard.tokens("design_coordination_with")
    ('design', 'coordination', 'with')
    >>> guard.denials("design_coordination_with")
    ()

None of the three tokens (`design`, `coordination`, `with`) `fullmatch` any
pattern in the guard's `DENIED` tuple -- not just the location-tracking
pattern, the whole list (score/rating/rank/tier/grade/weight/confidence/
priority/quality/strength/closeness/engagement/influence/health/risk/trust/
reputation/loyalty/compatibility/affinity/sentiment/personality/segment, and
the protected-trait list). `coordination` is a distinct token from
`coordinates`; the guard matches whole tokens (`fullmatch`), not substrings,
by its own design (see that module's docstring, "Matching is on snake_case
tokens, not substrings").

**What this migration does, in one sentence.** It renames the one seeded
`entity_relationship_types` row whose `relationship_type_code` is
`design_coordinates_with` to `design_coordination_with`, changing no other
column of that row, and repoints any `entity_relationships` row or other
taxonomy row that might reference the old code (defensively -- see below).

**Why this is additive-safe even though it is a primary-key rename.**
`entity_relationship_types.relationship_type_code` is this table's primary
key, and `entity_relationships.relationship_type` references it by a
validated (non-deferrable, `NO ACTION`) foreign key
(`an_entity_relationship_type_is_seeded`, added by `8dc3619891bb`). A bare
`UPDATE ... SET relationship_type_code = ...` on the referenced row would be
refused by Postgres if any child row still pointed at the old value at
constraint-check time, and even where none do, updating the key in place
gives no safe point at which a hypothetical child row could be repointed.
This migration instead: (1) inserts a **new** row carrying the new code,
copying every other column from the old row via `INSERT ... SELECT` (not
hand-restated literals) so `directed`, `inverse_type_code`,
`source_entity_type`, `target_entity_type`, `allows_project_scope`,
`cardinality_rule`, `status`, and `label` are carried over exactly as
`8dc3619891bb` set them, whatever they are; (2) repoints any
`entity_relationships.relationship_type` row and any other
`entity_relationship_types.inverse_type_code` row that references the old
code to the new code; (3) only then deletes the old row, once nothing
references it. Every step is idempotent-safe to reason about: step (1) fails
loudly (see below) unless exactly one old row exists, and steps (2)-(3)
operate on however many rows actually exist, not an assumed zero.

**Nothing could have written `design_coordinates_with` to
`entity_relationships.relationship_type` before this revision** --
`EntityRelationshipType` never admitted it as a member, and every write-path
gate (`CreateEntityRelationship.__post_init__`,
`proposal_validation._member`, `adapters/normalization.py`,
`application/entity_promotion.py`) tests membership against that enum, not a
separately frozen literal list (see `EntityRelationshipType`'s own docstring
for the full call-site audit). This migration does not *assume* that,
though: step (1) queries the actual row count for the old code and raises
`RuntimeError` if it is not exactly 1 (something other than the expected
single seeded row -- zero, meaning the code was already renamed or never
seeded, or more than one, meaning something wrote a duplicate no schema here
permits), and steps (2)-(3) act on whatever rows a live query finds rather
than a hardcoded "there are none" assumption.

**Label is deliberately left as `8dc3619891bb` set it.** The seeded label
for this code, `"Design Coordinates With"`, is copied verbatim by the
`INSERT ... SELECT` along with every other column -- this is a rename of the
`relationship_type_code` value only, per the campaign owner's ruling ("this
is a rename, not a new taxonomy decision"), not a new taxonomy decision about
the human-readable label. The label is display text read by nothing this
guard scans (`tests/architecture/test_relationship_scoring_surface_is_denied.py`
reads live SQLAlchemy column/dataclass-field/enum-member declarations and
this test module's own allow-list source, never a `entity_relationship_types`
row's `label` value), so leaving it unchanged is not itself a route back
through the guard; a future revision may relabel it if the campaign owner
wants the label's English to track the code's new spelling.

**Domain layer, updated in the same PR (not this migration file).**
`EntityRelationshipType.DESIGN_COORDINATION_WITH = "design_coordination_with"`
is added as the enum's thirty-fifth member in
`src/my_pa/domain/relationship/entity.py`, closing the enum to genuinely
35-of-35 parity with this table -- see that file's own updated docstring for
the full account, including why `design_coordination_with` (unlike
`design_coordinates_with`) passes the guard.

**Historical migration left untouched.** `8dc3619891bb`'s own module
docstring and inline seed data (`_NEW_CODES`) still read
`"design_coordinates_with"` -- that migration is history and is not rewritten
to reflect a later rename, per this campaign's own convention of not editing
merged migrations to restate later facts. This docstring is where that note
belongs instead.

DDL is written out rather than imported from `tables.py` (`D-48`, `D-69`), on
the same convention `8dc3619891bb` and every other hand-written-DDL migration
on this chain follows.
"""

from __future__ import annotations

from typing import Final

from alembic import op
from sqlalchemy import text

revision: str = "c99cd8ed8d1c"
down_revision: str | None = "1cda4d536268"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The code being retired, and its token-clean replacement. Restated here as
#: literals -- not derived from `EntityRelationshipType`, which by design
#: does not (and, before this migration and its companion domain-layer edit,
#: could not) carry the old value -- so this migration is a fixed, auditable
#: fact about what changed, independent of what the enum says today.
_OLD_CODE: Final = "design_coordinates_with"
_NEW_CODE: Final = "design_coordination_with"


def upgrade() -> None:
    bind = op.get_bind()

    # --- step 1: create the new row, copying every other column verbatim ----
    # INSERT ... SELECT rather than restated literals, so directed,
    # inverse_type_code, source_entity_type, target_entity_type,
    # allows_project_scope, cardinality_rule, status, and label are carried
    # over exactly as 8dc3619891bb (or any later revision) actually set them
    # for this row -- a rename, not a re-statement of a taxonomy decision.
    inserted = bind.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.entity_relationship_types
              (relationship_type_code, label, directed, inverse_type_code,
               source_entity_type, target_entity_type, allows_project_scope,
               cardinality_rule, status)
            SELECT :new_code, label, directed, inverse_type_code,
                   source_entity_type, target_entity_type, allows_project_scope,
                   cardinality_rule, status
            FROM {SCHEMA}.entity_relationship_types
            WHERE relationship_type_code = :old_code
            """  # noqa: S608
        ),
        {"new_code": _NEW_CODE, "old_code": _OLD_CODE},
    )
    if inserted.rowcount != 1:
        raise RuntimeError(
            f"expected exactly one {SCHEMA}.entity_relationship_types row with "
            f"relationship_type_code = {_OLD_CODE!r} to rename; found "
            f"{inserted.rowcount}. Refusing to guess -- this migration does not "
            "silently rename zero, more than one, or an already-migrated row."
        )

    # --- step 2: repoint any row that references the old code ---------------
    # Nothing could have written entity_relationships.relationship_type =
    # 'design_coordinates_with' before this revision (EntityRelationshipType
    # never admitted it as a member, and every write-path gate tests
    # membership against that enum -- see the module docstring's call-site
    # audit reference). This does not assume that: it repoints however many
    # rows an actual query finds, including zero.
    bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.entity_relationships
              SET relationship_type = :new_code
              WHERE relationship_type = :old_code
            """  # noqa: S608
        ),
        {"new_code": _NEW_CODE, "old_code": _OLD_CODE},
    )
    # No seeded row declares design_coordinates_with as its inverse_type_code
    # (8dc3619891bb wires only parent_of/subsidiary_of and manages/managed_by
    # as inverse pairs), but the same defensive repoint applies if one ever
    # did, rather than assuming it does not.
    bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.entity_relationship_types
              SET inverse_type_code = :new_code
              WHERE inverse_type_code = :old_code
            """  # noqa: S608
        ),
        {"new_code": _NEW_CODE, "old_code": _OLD_CODE},
    )

    # --- step 3: only now delete the old row, once nothing references it ----
    bind.execute(
        text(
            f"""
            DELETE FROM {SCHEMA}.entity_relationship_types
              WHERE relationship_type_code = :old_code
            """  # noqa: S608
        ),
        {"old_code": _OLD_CODE},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # The exact reverse, in the exact reverse order: recreate the old row
    # (copying every column from the new one), repoint any referencing rows
    # back to the old code, then delete the new row. Lossless both
    # directions -- a plain rename, not destructive DDL.
    inserted = bind.execute(
        text(
            f"""
            INSERT INTO {SCHEMA}.entity_relationship_types
              (relationship_type_code, label, directed, inverse_type_code,
               source_entity_type, target_entity_type, allows_project_scope,
               cardinality_rule, status)
            SELECT :old_code, label, directed, inverse_type_code,
                   source_entity_type, target_entity_type, allows_project_scope,
                   cardinality_rule, status
            FROM {SCHEMA}.entity_relationship_types
            WHERE relationship_type_code = :new_code
            """  # noqa: S608
        ),
        {"old_code": _OLD_CODE, "new_code": _NEW_CODE},
    )
    if inserted.rowcount != 1:
        raise RuntimeError(
            f"expected exactly one {SCHEMA}.entity_relationship_types row with "
            f"relationship_type_code = {_NEW_CODE!r} to restore; found "
            f"{inserted.rowcount}. Refusing to guess."
        )

    bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.entity_relationships
              SET relationship_type = :old_code
              WHERE relationship_type = :new_code
            """  # noqa: S608
        ),
        {"old_code": _OLD_CODE, "new_code": _NEW_CODE},
    )
    bind.execute(
        text(
            f"""
            UPDATE {SCHEMA}.entity_relationship_types
              SET inverse_type_code = :old_code
              WHERE inverse_type_code = :new_code
            """  # noqa: S608
        ),
        {"old_code": _OLD_CODE, "new_code": _NEW_CODE},
    )

    bind.execute(
        text(
            f"""
            DELETE FROM {SCHEMA}.entity_relationship_types
              WHERE relationship_type_code = :new_code
            """  # noqa: S608
        ),
        {"new_code": _NEW_CODE},
    )
