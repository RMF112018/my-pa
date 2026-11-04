"""Run the read-only Schedule Scenarios revision-A pre-deploy checks (contract section 14.9).

Usage, from the repository root, by an operator only:

    python ops/postgres/schedule_scenarios_predeploy_check.py --phase before
    python ops/postgres/schedule_scenarios_predeploy_check.py --phase after \
        --before-acl-sha256 <the Q5 digest the before run printed>

Run it as the runtime role the gateway and worker connect as: Q4 and Q8 judge
that role as ``current_user``. The connection is ``MY_PA_DATABASE_URL`` only.
The checks run in one ``READ ONLY`` transaction that is rolled back; every
statement is a ``SELECT`` -- catalog reads, and Q2's one cross-Principal
``EXISTS`` boolean
(``src/my_pa/infrastructure/database/schedule_scenarios_predeploy.py``).
Output is one status line per check and never a connection string. Exit code 0
when no check stops, 1 when any check stops or settings are refused, 2 on a
usage error. Runbook: ``ops/runbooks/cpm-workbench.md`` ("Schedule Scenarios
revision A").
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from my_pa.bootstrap.settings import SettingsError, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.database.schedule_scenarios_predeploy import (
    CheckStatus,
    PredeployPhase,
    run_predeploy_checks,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schedule_scenarios_predeploy_check")
    parser.add_argument("--phase", required=True, choices=[phase.value for phase in PredeployPhase])
    parser.add_argument("--before-acl-sha256", default=None)
    arguments = parser.parse_args(argv)
    try:
        settings = load_settings()
    except SettingsError as exc:
        print(f"schedule_scenarios_predeploy=refused {exc}")
        return 1
    engine = create_database_engine(settings.parsed_database_url())
    try:
        with engine.connect() as connection:
            checks = run_predeploy_checks(
                connection,
                PredeployPhase(arguments.phase),
                before_acl_sha256=arguments.before_acl_sha256,
            )
    finally:
        engine.dispose()
    for check in checks:
        print(
            f"schedule_scenarios_predeploy {check.check_id} {check.name}={check.status} "
            f"{check.detail}"
        )
    stopped = any(check.status is CheckStatus.STOP for check in checks)
    result = "stop" if stopped else "pass"
    print(f"schedule_scenarios_predeploy phase={arguments.phase} result={result}")
    return 1 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
