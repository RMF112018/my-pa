"""What `downgrade base` leaves behind, measured against what `CREATE DATABASE` made.

**This is not a fourth round trip.** Empty to head and back is already proven
three times at this head — `test_foundation_migration.py`'s
`test_upgrade_from_empty_and_downgrade_back_to_empty`,
`test_audit_schema_migration.py`'s
`test_the_audit_revision_runs_empty_to_head_and_head_to_empty`, and
`test_extraction_schema_migration.py`'s
`test_upgrade_from_empty_and_downgrade_back_to_empty` — and each of the three
makes a **content** claim about its own slice at the `base` end: the foundation
checks its nine schemas and two extensions, extraction checks that its schema is
gone, audit checks that its schema is gone.

What none of them asserts is the **union**. Each looks for the objects it knows
about, so an object *no revision's test enumerates* — a schema a later revision
added and an earlier one never knew, or a leftover extension — is invisible to
all three. This file makes the one claim that needs no list: after
`downgrade base` the database differs from the one `CREATE DATABASE` produced by
exactly one relation. Nothing is enumerated, so nothing can be forgotten.

**That one relation is `public.alembic_version`, and it is named rather than
excused.** Measured here rather than assumed: the schema and extension
dimensions round-trip exactly, and the version table is the sole residue.
Alembic keeps it in online mode by construction and no revision creates it, so
no revision's `downgrade` could drop it — it is not residue a revision left. The
exemption is bought back by asserting that the table is *empty*, which is the
part of "the database is at `base`" that its continued existence could otherwise
hide.

**The upgrade end is a control, not decoration.** Step 3 asserts the snapshot
*changed*. Without it, an `upgrade` that did nothing at all would satisfy the
final equality perfectly, which is this campaign's "the zero sits beside a
non-zero" rule applied to a comparison.

**What it detects that the upgrade half cannot.** `D-48`'s first half — a
declaration that retroactively changes what an earlier revision emits — fails
the *upgrade*, and three tests already run that. Its second half is the one
measured here: a later revision leaving an object behind that an earlier
revision's `downgrade` does not drop, so the earlier revision stops denoting one
schema. That asymmetry is unasserted at the `base` end anywhere else.

The database is disposable, created and dropped by this module's own fixture,
and is never the configured one: `downgrade base` deletes schemas.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one. Checked against the seventeen names the other database modules use; this
#: one belongs to no other module, and the names are server-global.
DISPOSABLE_DATABASE = "my_pa_head_round_trip_test"

#: The one relation that legitimately survives `downgrade base`, and the reason
#: it is exempted by name rather than by the snapshot being made blind to it.
#: Alembic drops its version table only in offline `--sql` mode
#: (`alembic/runtime/migration.py`, `if self.as_sql and not head_maintainer.heads`);
#: online it deletes the row and keeps the table. No revision in
#: `migrations/versions/` creates it, so no revision's `downgrade` can drop it,
#: and its presence is a fact about the library rather than residue any revision
#: left. Measured at `6660dbb`: this is the *only* difference between `base` and
#: `CREATE DATABASE`. What it holds is asserted separately below.
VERSION_TABLE = "public.alembic_version"

#: Every schema this database holds that PostgreSQL did not reserve for
#: itself. The system schemas are excluded by pattern rather than by name so
#: that a temporary schema a session creates cannot enter the snapshot and
#: make the comparison depend on which backend happened to run it. Written out
#: in full in both statements rather than interpolated, so neither is built by
#: string formatting.
_SCHEMAS = (
    "SELECT nspname FROM pg_namespace "
    "WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema'"
)

#: Every relation in those schemas, qualified by the schema holding it.
_RELATIONS = (
    "SELECT n.nspname, c.relname FROM pg_class c "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' "
    "AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')"
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _snapshot(engine: Engine) -> dict[str, tuple[str, ...]]:
    """Every schema, extension, and relation this database holds outside the system.

    Three dimensions rather than one, because the residue a downgrade can leave
    comes in three shapes: a schema its own revision did not drop, an extension
    dropped nowhere, and a relation inside a schema something else dropped.
    Relations are qualified by schema, so a table reappearing under a different
    schema is a difference rather than a match.
    """
    with engine.connect() as connection:
        schemas = tuple(sorted(str(name) for name in connection.execute(text(_SCHEMAS)).scalars()))
        extensions = tuple(
            sorted(
                str(name)
                for name in connection.execute(text("SELECT extname FROM pg_extension")).scalars()
            )
        )
        relations = tuple(
            sorted(f"{row[0]}.{row[1]}" for row in connection.execute(text(_RELATIONS)))
        )
    return {"schemas": schemas, "extensions": extensions, "relations": relations}


@pytest.fixture
def disposable_database() -> Iterator[str]:
    """An empty database exactly as `CREATE DATABASE` leaves it, dropped afterwards.

    Deliberately **not** migrated here. The whole subject of this module is the
    difference between this state and the state a full round trip returns to, so
    the fixture must hand the test the untouched original.
    """
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        # CREATE and DROP DATABASE cannot run inside a transaction block.
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(drop)
        maintenance.dispose()


@pytest.mark.database
def test_head_to_base_leaves_no_residue_of_any_revision(disposable_database: str) -> None:
    """`base` after `head` is the database `CREATE DATABASE` made, in every dimension.

    The three assertions are ordered so that each one's failure means something
    different. The first says the snapshot can see anything at all; the second
    says the upgrade did something, which is what stops an `upgrade` that ran no
    revision from satisfying the third; the third is the claim.
    """
    engine = create_database_engine(disposable_database)
    try:
        created = _snapshot(engine)

        # The snapshot is not empty on a database nothing has migrated: `public`
        # and `plpgsql` are what `CREATE DATABASE` itself leaves. Without this,
        # a `_snapshot` that returned three empty tuples for every state would
        # pass the equality below and prove nothing.
        assert "public" in created["schemas"], created
        assert "plpgsql" in created["extensions"], created

        command.upgrade(_config(), "head")

        at_head = _snapshot(engine)
        assert at_head != created, (
            "the snapshot did not change across `upgrade head`, so the final "
            "equality would be satisfied by a migration that ran nothing"
        )
        # Named rather than left to the inequality, so that a change in the wrong
        # dimension cannot stand in for the migration having run.
        assert "knowledge" in at_head["schemas"], at_head
        assert VERSION_TABLE in at_head["relations"], at_head
        assert set(created["relations"]) < set(at_head["relations"])

        command.downgrade(_config(), "base")

        at_base = _snapshot(engine)
        assert at_base["schemas"] == created["schemas"], (
            "a schema outlived the revision that created it, which is the half "
            "of `D-48` the upgrade end cannot detect"
        )
        assert at_base["extensions"] == created["extensions"], (
            "an extension outlived the revision that created it"
        )
        assert at_base["relations"] == (*created["relations"], VERSION_TABLE), (
            "a relation outlived the revision that created it. The only "
            f"relation permitted here is {VERSION_TABLE}, and it is permitted "
            "because Alembic keeps it and no revision owns it"
        )

        # The version table is the one permitted difference, so what it holds is
        # asserted rather than assumed: `downgrade base` must forget the chain,
        # and a table still naming a revision would make the next `upgrade head`
        # a no-op. This is the assertion the exemption above has to buy back.
        with engine.connect() as connection:
            recorded = connection.execute(
                text(f"SELECT count(*) FROM {VERSION_TABLE}")  # noqa: S608
            ).scalar_one()
        assert recorded == 0, (
            f"{VERSION_TABLE} still names {recorded} revision(s) after "
            "`downgrade base`, so the database is at `base` in its objects and "
            "not in its bookkeeping"
        )
    finally:
        engine.dispose()
