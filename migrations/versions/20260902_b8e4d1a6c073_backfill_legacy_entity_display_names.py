"""Backfill legacy entity display names into entity_names (RI-ENT-WP-12).

Revision ID: b8e4d1a6c073
Revises: 16f05c46b8c3
Create Date: 2026-09-02

RI-ENT-WP-12 (conservative legacy backfill). Authorized per
`AUTH-RI-ENT-20260830-OPERATOR-001` (untracked, repository root); see
`docs/campaign/ROBUST-ENTITY-DATA-MODEL-20260830.md` for the full campaign
record, finding IDs, and disposition rulings. **This revision runs against
disposable test databases only.** Applying it to the persistent `my_pa`
database is a destructive data operation and is operator-reserved by
`AGENTS.md` 8.2; nothing in this file may be read as authorization to do so.

**What this migration copies, and the one thing it must never do.** It copies
one fact, and one fact only, out of the legacy entity plane and into the new
typed-name family: for each `knowledge.entities` row whose `status` is
`'active'`, it writes exactly one `knowledge.entity_names` row of
`name_type_code = 'display'`, carrying `entities.display_name` as that row's
`display_value` and `entities.canonical_name` as its `normalized_value`.
**Neither value ever becomes a `legal` name.** The campaign's founding
finding `ENTITY-SCHEMA-001` exists precisely because the legacy plane
conflated "the string we show for this entity" with "what this entity is
legally called", and `7e114f822af2` created `entity_names` to end that
conflation. A display name is evidence of how an entity has been rendered in
a UI or an import; it is not evidence of a legal, brand, DBA, operating,
acronym, or historical name, and this revision does not let a later reader
mistake one for the other. Every wrong inference a backfill lands becomes
indistinguishable from evidence the moment it is written, so the whole design
below is organized around writing less rather than more.

**`normalized_value` takes `canonical_name`, `display_value` takes
`display_name` -- one row, not two.** `entities.canonical_name` is already
the stored normalized form of the same name `entities.display_name` renders,
and `entity_names` is shaped to hold exactly that pair in a single row (the
column pair it inherits from `entity_aliases`). Writing two rows, or writing
the display string into both columns, would either invent a second name that
never existed or discard the normalization the legacy row already did. There
is no third possibility to weigh: the legacy row carries one name in two
representations, and the target row holds one name in two representations.

**`name_type_code` is `'display'`, never `'legal'`.** See above; this is
`RULING-M10` rule 1 and the reason this work package exists.

**`is_preferred` is `false`.** Whether one display name is preferred over
another is a fact the legacy schema does not record anywhere -- `entities`
has a single `display_name` column and no preference marker -- so `true`
would be an invention. `false` is also the column's own DEFAULT in
`7e114f822af2`, and it is the value that cannot collide with the partial
unique index `an_active_entity_name_has_one_preferred_per_type`
(`(principal_id, entity_id, name_type_code) WHERE state = 'active' AND
is_preferred = true`), leaving a later writer free to elect a preferred
display name deliberately rather than inheriting one by accident.

**`effective_from` and `effective_to` are NULL.** The legacy `entities` row
carries `created_at`/`updated_at` for the *row*, not a dating for the *name*:
nothing there says when this display name came into use or left it, and
`created_at` is the moment the entity record was written, which is a
different fact. Both columns are nullable in `7e114f822af2` for exactly this
case, and the `an_entity_name_ends_after_it_starts` CHECK is satisfied
trivially by two NULLs.

**Only `status = 'active'` entities are backfilled -- a deliberate,
disclosed narrowing.** `entities.status` admits five values (`'active'`,
`'archived'`, `'historical'`, `'inactive'`, `'merged_redirect'`; see
`9def3c2e63bb`'s `_ENTITY_STATUS_VALUES`). An `entity_names` row written with
`state = 'active'` is an assertion that the name is *currently in service*,
and that assertion is not supported for an entity that has been archived,
retired to `historical`/`inactive`, or merged away behind a redirect.
Inserting one anyway would resurrect a retired name into the typed-name
search path RI-ENT-WP-09 reads. The conservative reading of the audit's
"backfill only what the legacy row actually evidences" is therefore to narrow
the scope rather than to invent a `state` for the other four statuses, and
this migration narrows it. Nothing is lost that cannot be added later by a
revision that decides, deliberately, what `state` a non-active entity's
historical display name should carry.

**The `entity_name_id` is derived deterministically**, as
`'enam_' || md5(<salt> || e.entity_id)` with the frozen salt
`ri-ent-wp-12:display:`. `md5()` renders 32 lowercase hex characters, so the
result matches the `entity_name_id_is_an_opaque_identifier` CHECK
(`^enam_[A-Za-z0-9]{8,64}$`) by construction. Deriving an opaque identifier
in SQL inside a migration on this chain has precedent:
`3d07af4dc513` (RI identity recovery) backfills
`'rcpt_' || md5(identity_operation_id || ':' || principal_id)`. Determinism
is not a convenience here -- it is what makes `downgrade()` exact, because it
lets the reverse statement recompute the identity of every row this revision
wrote without keeping a side ledger of them.

**Why the `downgrade()` DELETE cannot reach data this migration did not
create.** Every other writer of `entity_names` -- the application write path
and any future revision -- issues a server-generated random opaque identifier
for a new row. A random `enam_` identifier cannot equal
`'enam_' || md5('ri-ent-wp-12:display:' || entity_id)` for that same row's
own `entity_id` other than by an md5 preimage coincidence, so the predicate
`n.entity_name_id = 'enam_' || md5(<salt> || n.entity_id)` is satisfied by
this revision's rows and by nothing else. The `name_type_code = 'display'`
conjunct narrows it further. The delete is therefore exact rather than
approximate, which is the standard this campaign holds a reversible data
migration to.

**Fail-closed before any write.** `upgrade()` runs three ambiguity guards,
all of them before the INSERT, so an ambiguous database is refused whole
rather than half-written:

- **Guard A -- an entity already has an active `display` name.** If any
  in-scope entity already carries a `knowledge.entity_names` row with
  `name_type_code = 'display' AND state = 'active'`, this migration cannot
  decide whether that row or the legacy `entities` value is the truth. It
  refuses. Silently skipping those entities would be a guess dressed as
  caution (it asserts the existing row wins), and overwriting would be the
  same guess in the other direction.
- **Guard B -- derived identity collision.** If any `entity_name_id` this
  migration would generate already exists in `knowledge.entity_names`, the
  derivation is not injective against this database and both the INSERT and
  the `downgrade()` DELETE would act on a row this revision did not author.
  It refuses rather than deduplicate.
- **Guard C -- source value unusable.** If any in-scope `entities` row has
  `length(trim(canonical_name)) = 0` or `length(trim(display_name)) = 0`, it
  refuses. `9def3c2e63bb` installed
  `an_entity_canonical_name_is_not_blank`/`an_entity_display_name_is_not_blank`
  on the source table and `7e114f822af2` installed the matching CHECKs on the
  target, so this should be unreachable -- which is the reason to assert it
  rather than assume it. A violation must surface as this migration's own,
  named refusal, not as a raw constraint error from the INSERT with no
  statement of what the migration believed.

Every guard raises with the **count** of offending rows and up to five
offending `entity_id` values, and with nothing else. `AGENTS.md` section 5
requires logs to carry stable identifiers and redacted metadata rather than
contact details or content, so no name, display value, canonical value, or
other free text appears in any message this file can emit -- an
`ent_`-prefixed opaque identifier is exactly the kind of value that section
permits, and a display name is exactly the kind it does not.

**Everything here is set-based SQL or a `DO $$ ... $$` block**, deliberately.
No row is read into Python, no value is computed application-side, and no
result is interrogated, so this revision renders identically in offline
(`--sql`) mode and needs no `context.is_offline_mode()` branch at all --
unlike `c99cd8ed8d1c`, which has one only because it reads
`Result.rowcount`. The guards are server-side `RAISE EXCEPTION`s for the same
reason: they are part of the emitted script, so a reviewer reading the
offline SQL sees the same refusals the online path enforces.

**What this migration deliberately does not touch, and why for each.**

- **`knowledge.entity_aliases`** -- not read, not written, not migrated, not
  deprecated. `entity_names` is an *additional* record family, not a
  replacement, and `entity_aliases` keeps the semantics `b7f4d1a92c36` gave
  it. Consolidating the two is audit decision R.1, which remains open for a
  later work package; a backfill is not the place to settle it.
- **`knowledge.entity_project_participations`** -- **zero rows written. This
  is rule 3 of `RULING-M10` correctly applied, not skipped.** The audit
  authorizes backfilling participation "only for directly representable
  values". `f5b06925857e` declares `project_display_name text NOT NULL` with
  `a_project_participation_display_name_is_not_blank`, so every participation
  row requires a name; the legacy source, `knowledge.entity_assignments`
  (`9def3c2e63bb`), carries no name-bearing column at all -- only `role`,
  `discipline`, and `responsibility_class`. The one place a name could be
  found is `entities.display_name`/`canonical_name`, and reading either into
  `project_display_name` is expressly forbidden by that column's own DDL
  comment ("project-scoped fact, never global identity ... nothing may read
  either of those columns into this one"), because a participant's name *on a
  project* is a different fact from its global identity. No legacy row is
  therefore directly representable, and the correct output of rule 3 is the
  empty set. **This file contains no INSERT against that table**, and the
  absence is the rule's result, not its omission.
- **`knowledge.entity_addresses` and
  `knowledge.entity_communication_methods`** -- zero rows written. Both are
  typed by a closed vocabulary (`address_type_code`, `method_type_code`), and
  the only way a backfill could supply a type is by inferring it from a
  string's position or shape. `RULING-M10` rule 4 forbids that outright, and
  correctly: an inferred type is unfalsifiable once stored.
- **`knowledge.entity_external_identifiers`** -- untouched. Rule 5 preserves
  `entity_id` and renumbers nothing; this migration reads `entities.entity_id`
  and writes it through unchanged, and has no reason to visit the identifier
  table.

DDL and data statements are written out rather than imported from
`tables.py` (`D-48`, `D-69`); the two vocabulary literals this file uses --
the name type `'display'` and the states `'active'` -- are frozen here as
module constants and are **not** derived from `NameTypeCode`,
`EntityNameState`, or `EntityStatus`. `D-69` forbids a revision deriving a
closed set from a domain enum, and this revision emits no closed-set
constraint at all.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "b8e4d1a6c073"
down_revision: str | None = "16f05c46b8c3"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The `entity_names.name_type_code` this backfill writes. **Frozen literal,
#: NOT derived from `NameTypeCode`** (`D-69`). It is `'display'` and it is
#: never `'legal'`: a legacy display name is not evidence of a legal name,
#: which is finding `ENTITY-SCHEMA-001` itself.
_NAME_TYPE_CODE: Final = "display"

#: The `entity_names.state` this backfill writes. Frozen literal, NOT derived
#: from any domain enum. Paired with the source-status filter below: a row
#: asserting "in service" is written only for an entity that is in service.
_NAME_STATE: Final = "active"

#: The `entities.status` this backfill reads. Frozen literal, NOT derived
#: from `EntityStatus`. The other four admitted statuses (`archived`,
#: `historical`, `inactive`, `merged_redirect`) are deliberately out of
#: scope -- see the module docstring.
_SOURCE_ENTITY_STATUS: Final = "active"

#: The salt for the derived `entity_name_id`. Frozen literal, NOT derived
#: from anything: it names this work package and this backfill, so no other
#: revision on this chain can generate the same identifiers, and
#: `downgrade()` can recompute them exactly.
_ID_SALT: Final = "ri-ent-wp-12:display:"

#: How many offending identifiers a guard names in its message. Identifiers
#: only, never names or values -- `AGENTS.md` section 5.
_SAMPLE_LIMIT: Final = 5


def _derived_entity_name_id(alias: str) -> str:
    """The SQL expression for this backfill's derived `entity_name_id`.

    Written once and reused by the INSERT, by guard B, and by the
    `downgrade()` DELETE so the three cannot drift apart -- drift between the
    identity that is written and the identity that is deleted is exactly what
    would make the reverse statement inexact.

    `md5()` renders 32 lowercase hex characters, so the result always
    satisfies `entity_name_id_is_an_opaque_identifier`
    (`^enam_[A-Za-z0-9]{8,64}$`).
    """
    return f"'enam_' || md5('{_ID_SALT}' || {alias}.entity_id)"


def _sql_escaped(value: str) -> str:
    """`value` with single quotes doubled, for embedding in a SQL literal.

    On `c99cd8ed8d1c`'s convention: quoting is applied uniformly rather than
    trusted to be unnecessary for the particular English these guard messages
    happen to contain today.
    """
    return value.replace("'", "''")


def _guard(*, name: str, offending_sql: str, message: str) -> str:
    """A fail-closed `DO` block over a query yielding offending `entity_id`s.

    `offending_sql` must be a `SELECT` of one `entity_id` column. The block
    counts every offending row and samples up to `_SAMPLE_LIMIT` identifiers
    in a stable order, then raises with the count and the sample and nothing
    else. Emitting this server-side rather than checking it in Python is what
    lets the whole revision render unchanged in offline (`--sql`) mode.
    """
    return f"""
        DO $$
        DECLARE
          offending_count integer;
          offending_sample text;
        BEGIN
          WITH offending AS (
            {offending_sql}
          ), sampled AS (
            SELECT entity_id FROM offending ORDER BY entity_id LIMIT {_SAMPLE_LIMIT}
          )
          SELECT
            (SELECT count(*) FROM offending),
            (SELECT coalesce(string_agg(entity_id, ', ' ORDER BY entity_id), '(none)')
               FROM sampled)
          INTO offending_count, offending_sample;

          IF offending_count > 0 THEN
            RAISE EXCEPTION
              'RI-ENT-WP-12 ({_sql_escaped(name)}): % offending row(s). '
              'First up to {_SAMPLE_LIMIT} entity_id: %. {_sql_escaped(message)}',
              offending_count, offending_sample;
          END IF;
        END $$
        """  # noqa: S608


def upgrade() -> None:
    # --- guard A: an in-scope entity already has an active display name -----
    # Refusing, rather than skipping or overwriting, is the point: both of
    # those are decisions about which value is the truth, and this migration
    # has no evidence with which to make one.
    op.execute(
        _guard(
            name="guard A: an active display name already exists",
            offending_sql=f"""
            SELECT DISTINCT n.entity_id
              FROM {SCHEMA}.entity_names n
              JOIN {SCHEMA}.entities e ON e.entity_id = n.entity_id
             WHERE n.name_type_code = '{_NAME_TYPE_CODE}'
               AND n.state = '{_NAME_STATE}'
               AND e.status = '{_SOURCE_ENTITY_STATUS}'
            """,  # noqa: S608
            message=(
                "An in-scope entity already carries an active display name row. This "
                "migration cannot decide whether that row or the legacy entities value "
                "is the truth, so it refuses rather than guess, skip, or overwrite. "
                "Resolve the existing rows and re-run."
            ),
        )
    )

    # --- guard B: the derived identity collides with an existing row --------
    # If this fires, the derivation is not injective against this database and
    # both the INSERT below and the downgrade() DELETE would touch a row this
    # revision did not author.
    op.execute(
        _guard(
            name="guard B: derived entity_name_id collision",
            offending_sql=f"""
            SELECT e.entity_id
              FROM {SCHEMA}.entities e
              JOIN {SCHEMA}.entity_names n
                ON n.entity_name_id = {_derived_entity_name_id("e")}
             WHERE e.status = '{_SOURCE_ENTITY_STATUS}'
            """,  # noqa: S608
            message=(
                "An entity_name_id this migration would derive already exists. Writing "
                "would collide and downgrading would delete a row this migration did "
                "not create, so it refuses rather than deduplicate."
            ),
        )
    )

    # --- guard C: the source value is unusable ------------------------------
    # Should be unreachable: 9def3c2e63bb constrains both source columns to be
    # non-blank and 7e114f822af2 constrains both target columns the same way.
    # Asserted rather than assumed, so a violation surfaces as this
    # migration's explicit refusal instead of a raw constraint error.
    op.execute(
        _guard(
            name="guard C: unusable source value",
            offending_sql=f"""
            SELECT e.entity_id
              FROM {SCHEMA}.entities e
             WHERE e.status = '{_SOURCE_ENTITY_STATUS}'
               AND (
                 length(trim(e.canonical_name)) = 0
                 OR length(trim(e.display_name)) = 0
               )
            """,  # noqa: S608
            message=(
                "An in-scope entities row has a blank canonical_name or display_name, "
                "which its own CHECK constraints should make impossible. Refusing to "
                "backfill from a source that violates its declared invariants."
            ),
        )
    )

    # --- the one write: one display name row per active entity --------------
    # Set-based, every column listed explicitly, no Python-side loop, so this
    # renders identically in offline (--sql) mode. See the module docstring
    # for the reason behind each literal below.
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.entity_names (entity_name_id, entity_id, name_type_code,
          normalized_value, display_value, is_preferred, effective_from, effective_to,
          principal_id, state, version, updated_at, retired_at, superseded_by_entity_name_id)
        SELECT {_derived_entity_name_id("e")},
               e.entity_id, '{_NAME_TYPE_CODE}', e.canonical_name, e.display_name,
               false, NULL, NULL, e.principal_id, '{_NAME_STATE}', 1, NULL, NULL, NULL
          FROM {SCHEMA}.entities e
         WHERE e.status = '{_SOURCE_ENTITY_STATUS}';
        """  # noqa: S608
    )


def downgrade() -> None:
    # --- guard: a backfilled row is entangled in a supersession chain -------
    # Deleting a row another writer has named as a successor would dangle
    # `an_entity_name_is_superseded_within_its_principal`, and deleting one
    # that has itself been superseded would destroy the head of a chain a
    # later writer built on this migration's output. Neither is a reversal of
    # what this migration did, so downgrade refuses instead.
    op.execute(
        _guard(
            name="downgrade guard: backfilled row is entangled in supersession",
            offending_sql=f"""
            WITH backfilled AS (
              SELECT n.entity_name_id, n.entity_id, n.superseded_by_entity_name_id
                FROM {SCHEMA}.entity_names n
               WHERE n.name_type_code = '{_NAME_TYPE_CODE}'
                 AND n.entity_name_id = {_derived_entity_name_id("n")}
            )
            SELECT b.entity_id
              FROM backfilled b
             WHERE b.superseded_by_entity_name_id IS NOT NULL
            UNION
            SELECT b.entity_id
              FROM backfilled b
              JOIN {SCHEMA}.entity_names o
                ON o.superseded_by_entity_name_id = b.entity_name_id
            """,  # noqa: S608
            message=(
                "A row this migration inserted is referenced as a successor by another "
                "row, or has itself been superseded. Deleting it would destroy a later "
                "writer's data or dangle a foreign key, so downgrade refuses."
            ),
        )
    )

    # --- the exact reverse: only the rows this migration derived ------------
    # A row written by any other writer carries a server-issued random opaque
    # identifier and cannot equal this derived value for its own entity_id, so
    # this delete cannot reach data this migration did not create.
    op.execute(
        f"""
        DELETE FROM {SCHEMA}.entity_names n
         WHERE n.name_type_code = '{_NAME_TYPE_CODE}'
           AND n.entity_name_id = {_derived_entity_name_id("n")};
        """  # noqa: S608
    )
