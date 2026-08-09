"""Two ways to be at a revision must produce one schema, measured against a server.

**The claim.** For every revision in the chain: a database built from empty up to
that revision's parent, and a database that went one revision further and came
back down, hold *the same constraints*. If they do not, the revision's `downgrade`
does not restore what the revision below it denotes, and "the database is at
`X`" stops naming one thing.

`9d4e7a3b1c62` is why this exists. Its `downgrade` restored
`status IN ('extracted', 'quarantined', 'unsupported')` while `8b3f5c17d904` —
which builds `extractions` from the *live* declaration — had been narrowed to
two, so a database that went up to head and back down to `7f2a9d6c4e18` admitted
`quarantined` and a freshly built one at the same revision refused it.

**Why this is executed rather than parsed, which is the part worth reading.** The
first four attempts at this guard read Alembic's rendered `--sql` output with a
regular expression, and independent review broke every one of them:

1. the landing text was keyed on constraint *name*, and names are not unique
   here — `state_is_known` sits on `knowledge.jobs` and on
   `migration_control.table_progress` with different vocabularies;
2. the reader silently skipped shapes it could not match — `CHECK(` without the
   space, an unnamed `ADD CHECK`, lower case, a newline before `CHECK`;
3. the revision-boundary pattern assumed hexadecimal revision ids, so a revision
   created with `--rev-id wp13_start` had its whole block discarded;
4. the "independent auditor" added to catch (2) recognised a `CHECK` by the same
   sub-pattern as the reader, so it could not disagree with it — a tautology. A
   `CHECK` written `CHECK/*restore*/(` was invisible to both, and a wrong
   `purpose_is_known` restoration on `3c8f1e2a5b74` passed the whole repository
   green while two real databases diverged.

Each fix was correct about the shape it had been shown and wrong about the class,
because the class is *"a text I did not anticipate"* and no regular expression
closes it. **A parser can only ever enumerate what it knows; the server parses
everything by definition.** So this module runs the migrations and asks
PostgreSQL what it ended up holding, and the only shape that matters is the one
the server accepted. That is also where `README.md` puts migration
behaviour: applied and rolled back in the database tier, with only SQL generation
checked by FAST. Siting the claim in FAST was the mistake underneath all four
rounds.

**What it compares.** Four kinds of fact about every table in every non-system
schema, straight out of the catalogue: constraints
(`pg_get_constraintdef`), columns (type, `NOT NULL`, and `DEFAULT`), indexes
(`pg_get_indexdef`), and non-internal triggers (`pg_get_triggerdef`). So a
`UNIQUE` a downgrade forgot, a `FOREIGN KEY` it restored over different columns,
a `NOT NULL` it dropped, a default it changed, an index it left behind and a
trigger it failed to remove all fail the same comparison. Nothing inside those
four kinds is enumerated, so nothing inside them can be forgotten — the property
`test_head_round_trip.py` establishes at `base`, held at every revision instead of
only the last one.

**What it does NOT compare**, at demonstrated capability and no higher, and
listed because the first version of this module claimed a default was covered
when a plant showed it was not. The four kinds above are what it reads, so
everything else about a database is outside it: table and column *comments*,
privileges and ownership, collations, sequence parameters, functions and
procedures other than the triggers that call them, row-level security policies,
publications, and anything about *rows*. Two databases at one revision can still
differ in any of those and this test will pass.

**`public.alembic_version` is excluded by name, for the reason
`test_head_round_trip.py` gives**: Alembic creates it and no revision owns it, so
it appears the moment the first `upgrade` runs and no `downgrade` can drop it.
Measured rather than asserted, and the earlier version of this sentence
overstated it: without the exclusion exactly **one** revision's comparison
differs — the first, where the table does not exist in the "fresh" snapshot and
does afterwards. From the second revision on it is in both sides and cancels. The
only fact the exclusion hides is that table's own primary key.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

ROOT = Path(__file__).resolve().parents[2]
VERSIONS = ROOT / "migrations" / "versions"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one,
#: and belonging to no other module: these names are server-global and every
#: database module in this tree owns exactly one.
DISPOSABLE_DATABASE = "my_pa_revision_denotation_test"

#: The relation Alembic owns and no revision creates, excluded for the same
#: reason `test_head_round_trip.py` excludes it. Its primary key would otherwise
#: appear in every comparison after the first `upgrade` and in none before.
VERSION_TABLE: Final = ("public", "alembic_version")

#: Everything about a table this comparison can reach, as one comparable line
#: each, in four kinds: constraints, columns (type, nullability and default),
#: indexes, and non-internal triggers.
#:
#: **Four kinds rather than one, because a review found the one.** The first
#: version read `pg_constraint` alone, and the reviewer measured what that misses:
#: `NOT NULL` lives in `pg_attribute.attnotnull` and a default in `pg_attrdef`,
#: neither of which produces a `pg_constraint` row. A `downgrade` that dropped a
#: `NOT NULL` left two databases at one revision disagreeing about whether a
#: column could be null — the identical shape as `D-109`'s own defect — with the
#: whole tier green. A stray index survived the same way. All three now fail.
#:
#: System schemas are excluded by pattern rather than by name so a session's
#: temporary schema cannot enter the snapshot and make the result depend on which
#: backend happened to run it. Columns are read only for relations that have
#: them; `attisdropped` columns are skipped because a dropped column leaves a
#: tombstone whose name is not stable.
_SNAPSHOT = text(
    "WITH visible AS ("
    "  SELECT c.oid, n.nspname, c.relname, c.relkind"
    "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    "  WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'"
    "    AND NOT (n.nspname = :version_schema AND c.relname = :version_table)"
    ") "
    "SELECT 'constraint ' || v.nspname||'.'||v.relname||'.'||con.conname"
    "       ||' = '||pg_get_constraintdef(con.oid) "
    "FROM pg_constraint con JOIN visible v ON v.oid = con.conrelid "
    "UNION ALL "
    "SELECT 'column ' || v.nspname||'.'||v.relname||'.'||a.attname"
    "       ||' = '||format_type(a.atttypid, a.atttypmod)"
    "       ||' notnull='||a.attnotnull"
    "       ||' default='||coalesce(pg_get_expr(d.adbin, d.adrelid), '<none>') "
    "FROM pg_attribute a JOIN visible v ON v.oid = a.attrelid "
    "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attnum > 0 AND NOT a.attisdropped AND v.relkind IN ('r', 'p', 'm', 'f') "
    "UNION ALL "
    "SELECT 'index ' || v.nspname||'.'||v.relname||' = '||pg_get_indexdef(i.indexrelid) "
    "FROM pg_index i JOIN visible v ON v.oid = i.indrelid "
    "UNION ALL "
    "SELECT 'trigger ' || v.nspname||'.'||v.relname||'.'||t.tgname"
    "       ||' = '||pg_get_triggerdef(t.oid) "
    "FROM pg_trigger t JOIN visible v ON v.oid = t.tgrelid WHERE NOT t.tgisinternal "
    "ORDER BY 1"
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _schema_facts(engine: Engine) -> tuple[str, ...]:
    with engine.connect() as connection:
        rows = connection.execute(
            _SNAPSHOT,
            {"version_schema": VERSION_TABLE[0], "version_table": VERSION_TABLE[1]},
        ).scalars()
        return tuple(str(row) for row in rows)


@pytest.fixture
def disposable_database() -> Iterator[str]:
    """An empty database, pointed at by the settings, dropped afterwards.

    Never the configured one: this module downgrades to `base` repeatedly, which
    deletes schemas.
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
def test_every_revision_returns_the_database_to_what_the_one_below_it_denotes(
    disposable_database: str,
) -> None:
    """The claim, one revision at a time, against a server.

    The chain is walked once. At each revision the database is already sitting at
    that revision's parent, so the snapshot taken there *is* the freshly-built
    state — no second database and no second migration run is needed, which is
    what keeps a whole-chain claim down to a few seconds.

    Three controls, because a comparison of two identical nothings passes
    perfectly. The walk must cover every revision file; the snapshot must grow from
    nothing to something real, which is what proves it can see anything at all;
    and each revision's comparison is reported with the exact facts that differ
    rather than as a count.
    """
    engine = create_database_engine(disposable_database)
    revisions = list(reversed(list(ScriptDirectory(str(ROOT / "migrations")).walk_revisions())))
    try:
        assert len(revisions) == len(list(VERSIONS.glob("*.py"))), (
            "the chain Alembic walks and the revision files on disk disagree, so "
            "this walk would silently skip a revision"
        )

        empty = _schema_facts(engine)
        assert empty == (), (
            f"a database nothing has migrated already holds {len(empty)} constraints"
        )

        for revision in revisions:
            parent = revision.down_revision or "base"
            assert isinstance(parent, str)

            fresh = _schema_facts(engine)
            command.upgrade(_config(), revision.revision)
            command.downgrade(_config(), parent)
            returned = _schema_facts(engine)

            assert returned == fresh, (
                f"{revision.revision}'s downgrade does not return the database to "
                f"what {parent} denotes, so two databases at {parent} would differ "
                "depending on how each arrived.\n"
                f"  only after the round trip: {sorted(set(returned) - set(fresh))}\n"
                f"  only in the fresh build  : {sorted(set(fresh) - set(returned))}"
            )

            command.upgrade(_config(), revision.revision)

        at_head = _schema_facts(engine)
        assert len(at_head) > len(empty), (
            "the chain added no schema fact at all, so every comparison above "
            "compared two empty sets and proved nothing"
        )

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()
