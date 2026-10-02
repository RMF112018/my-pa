"""Run the Record Event privilege gate as the application runtime principal.

The connection is ``MY_PA_DATABASE_URL`` only. Output is a single status line
and, on failure, the gate's reason. Neither includes a connection string.
"""

from __future__ import annotations

import sys

from my_pa.bootstrap.settings import SettingsError, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.database.record_event_privilege_gate import (
    PrivilegeGateError,
    verify_record_event_privileges,
)


def main() -> int:
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"record_event_privilege_gate=refused {exc}")
        return 1
    engine = create_database_engine(settings.parsed_database_url())
    try:
        with engine.connect() as connection:
            verify_record_event_privileges(connection)
    except PrivilegeGateError as exc:
        print(f"record_event_privilege_gate=refused {exc}")
        return 1
    finally:
        engine.dispose()
    print("record_event_privilege_gate=pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
