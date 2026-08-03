"""Operator command: is the configured database able to serve this build?

    .venv/bin/python apps/cli/health.py

Three answers and three exit statuses, and the point of the command is that they
are **distinguishable**:

    state  ready         reachable, and at the migration head        exit 0
    state  not_at_head   reachable, but not carrying head's schema   exit 1
    state  unreachable   no server answered                          exit 1

**Why this exists, and why reachability alone would not have earned it.**
`healthcheck` had been in `my_pa.infrastructure.database` since Phase 01 with no
caller anywhere in `src/`, `apps/`, or `migrations/` at `bcdbf6d` — a working
probe nothing could reach. This file is that caller, so the claim is written in
the past tense on purpose. But a probe that reported only reachability would call
the canonical `my_pa` database **healthy** while it cannot serve a single
capability: it carries no `knowledge` schema, so it has no
`knowledge.audit_events` for the audit row every served request commits, every
request through `ApplicationService` fails inside the unit of work, and the caller
is told `internal_error` — "the request could not be completed", with nothing to
say why. Reporting the database's revision against the migration head is what
turns that into an answer an operator can act on. `D-61`, `D-62`.

**`not_at_head` is per-build, not per-capability, and the difference is not
academic.** Measured by stepping a disposable database through the whole chain:
below `9c6b4a18ed72`, which creates `knowledge.audit_events`, *every* capability
answers `internal_error`, because a request that cannot commit its audit row
fails rather than being served unaudited. At `9c6b4a18ed72` itself — one revision
behind head `af3d35efb9c0` — `capabilities.get` and `sources.list` answer exactly
as they do at head, so this command's refusal there is **not** a claim that every
capability fails. It is still correct: at that same revision `sources.enroll`
answers `internal_error`, because head creates `enrollment_objects`. Exiting `1`
below head is an operational policy (`D-62`) that the measurement supports.

**It diagnoses that condition; it does not reclassify it.** Correcting the
application's error taxonomy so a request that cannot record its audit row
answers something better than `internal_error` is a separate change against
`my_pa.application.errors` and the three transports' negative-evidence matrices.
`D-65` names it and defers it; this command is how an operator finds out, not the
fix.

**It is not a ninth capability, and not a route.** It builds no
`ApplicationService`, no `Principal`, and no `SourceProviders`, exactly as
`apps/cli/sources.py` does not, and
`tests/architecture/test_operator_commands_are_not_capabilities.py` decides that
by reading this file rather than by trusting this paragraph. A health *route*
was rejected for a stronger reason than taste: `adapters/http/app.py` declares
exactly one `Route`, every request that reaches the application commits an audit
row, and a route outside that envelope would make "every served request is
audited" false — while disclosing the server version, the extension list, and the
schema revision to any loopback caller, which is a decision `P00-OD-010` reserves
to the operator.

**Nothing it prints identifies where it looked.** No URL, no host, no port, no
database name, on any path including a failure. The target is
`MY_PA_DATABASE_URL` and there is deliberately no option to override it: an
operator asking "is my configured database serving" must not be able to answer it
about a different one by accident, and an evidence file capturing this output must
not acquire a connection string. The unreachable path prints the *fact* and not
the driver's message, because the driver's message renders with the host and port
it failed on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import OperationalError

from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database.engine import create_database_engine, healthcheck

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_CONFIG = REPOSITORY_ROOT / "alembic.ini"

#: What a refusal is worth to a shell, the same two values `sources.py` uses.
#: `0` means the configured database can serve this build and nothing finer is
#: offered, because the three states are already distinguished by the `state`
#: line and a third exit status would be a vocabulary nobody asked for.
EXIT_OK = 0
EXIT_REFUSED = 1

#: The closed set of answers. `not_at_head` rather than `behind_head` on purpose:
#: it is also the honest name for an empty database that carries no
#: `alembic_version` row at all, and for one stamped with a revision this
#: repository does not contain. All three are "cannot serve this build", and
#: calling them `behind_head` would name a direction that has not been measured.
STATE_READY = "ready"
STATE_NOT_AT_HEAD = "not_at_head"
STATE_UNREACHABLE = "unreachable"

#: Printed when the database carries no Alembic revision at all. A literal, so
#: the `revision` line always has a value and a parser never sees a blank field.
NO_REVISION = "none"


def _engine() -> Engine:
    return create_database_engine(load_settings().database_url)


def migration_heads() -> tuple[str, ...]:
    """The revisions this repository's Alembic chain ends at.

    A tuple rather than one string because `ScriptDirectory` can legitimately
    report more than one head, and a probe that assumed one would report a
    branched chain as if it were a single revision. There is one today; the
    comparison below is set equality either way, so this stays true if a branch
    is ever created.
    """
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    return tuple(sorted(script.get_heads()))


def database_revisions(connection: Connection) -> tuple[str, ...]:
    """What the database says it is at — `()` when it says nothing.

    `MigrationContext` rather than a `SELECT` on `public.alembic_version`,
    because an empty database has no such table and asking it directly turns
    "this database has never been migrated" into a driver error. That state is
    an answer, not a failure, and it is the state a fresh disposable database is
    in.
    """
    return tuple(sorted(MigrationContext.configure(connection).get_current_heads()))


def _probe() -> int:
    """Reach the database, report what it is, and decide the exit status.

    Reachability first, through `healthcheck`, so that the version and extension
    lines come from the same function the runbook already documents rather than
    from a second query written here. The revision then comes from a second
    connection on the same engine: `healthcheck` owns and closes its own, and
    widening its signature to hand one back would change a Phase 01 contract to
    save one checkout from a five-connection pool.
    """
    heads = migration_heads()
    engine = _engine()
    try:
        health = healthcheck(engine)
        with engine.connect() as connection:
            revisions = database_revisions(connection)
    except OperationalError:
        # Deliberately not `{refusal}`. `OperationalError` renders with the host
        # and port the driver could not reach, and this command names no target.
        print(f"state            {STATE_UNREACHABLE}")
        print("the configured database did not answer; no server, or no such database")
        return EXIT_REFUSED
    finally:
        engine.dispose()

    at_head = set(revisions) == set(heads)
    print(f"state            {STATE_READY if at_head else STATE_NOT_AT_HEAD}")
    print(f"server_version   {health.server_version}")
    print(f"extensions       {', '.join(health.extensions)}")
    print(f"revision         {', '.join(revisions) if revisions else NO_REVISION}")
    print(f"head             {', '.join(heads)}")
    if at_head:
        return EXIT_OK
    print("the configured database is not at the migration head and cannot serve this build")
    return EXIT_REFUSED


def build_parser() -> argparse.ArgumentParser:
    """One command, no options, and that is the surface.

    `sources.py` and `migration.py` put their options behind subcommands because
    they have several things to do. This has one, and it takes no input at all:
    the target is configuration and there is nothing else to decide.
    """
    return argparse.ArgumentParser(
        prog="health",
        description="Report whether the configured database can serve this build.",
    )


def main(argv: list[str] | None = None) -> int:
    """Parse, probe, and turn a configuration refusal into an exit status.

    `SettingsError` is a `ValueError`, and an unset or malformed
    `MY_PA_DATABASE_URL` is the refusal an operator running this first is most
    likely to meet. Its message never echoes the value — `bootstrap.settings`
    guarantees that — so printing it here discloses nothing.

    Anything else propagates. A driver failure that is not `OperationalError` is
    not a refusal, and reporting it as one would tell an operator their
    configuration is wrong when the truth is something else.
    """
    build_parser().parse_args(argv)
    try:
        return _probe()
    except ValueError as refusal:
        print(f"refused          {refusal}")
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
