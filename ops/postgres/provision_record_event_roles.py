"""Provision the Record Event owner, migrator, and runtime roles.

The connection is ``MY_PA_MIGRATION_DATABASE_URL``. This command does not read
the application URL and does not create a credential. Without ``--apply`` it
exits before connecting. Applying it to a live cluster is a separate operator
action; this work package does not perform that action.
"""

from __future__ import annotations

import argparse
import sys

from my_pa.bootstrap.migration_authority import load_migration_authority
from my_pa.bootstrap.settings import SettingsError
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.database.record_event_roles import (
    RoleProvisionError,
    provision_record_event_roles,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="connect with the migration URL and provision roles",
    )
    args = parser.parse_args(argv)
    if not args.apply:
        print("record_event_role_provision=not_applied")
        print("pass --apply to provision; no connection was opened")
        return 2
    try:
        authority = load_migration_authority()
    except SettingsError as exc:
        print(f"record_event_role_provision=refused {exc}")
        return 1
    engine = create_database_engine(authority.parsed_database_url(), statement_timeout_ms=None)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            granted = provision_record_event_roles(connection)
    except RoleProvisionError as exc:
        print(f"record_event_role_provision=refused {exc}")
        return 1
    finally:
        engine.dispose()
    state = "granted" if granted else "roles_only"
    print(f"record_event_role_provision={state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
