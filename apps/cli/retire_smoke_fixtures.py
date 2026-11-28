"""Preview or apply a narrowly scoped retirement using the local operator database route."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.settings import load_settings
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.cycle_scheduler import COMMS_INGEST_LOCK_KEY
from my_pa.infrastructure.persistence.smoke_fixture_retirement import (
    RetirementRefusalError,
    SmokeFixtureTarget,
    retire_smoke_fixtures,
)

_TARGETS = {
    "message": IdKind.COMMUNICATION_MESSAGE,
    "source": IdKind.INGEST_SOURCE,
    "publication": IdKind.SCHEDULE_PUBLICATION,
    "scenario": IdKind.SCHEDULE_SCENARIO,
}


def _require(valid: bool, reason: str) -> None:
    if not valid:
        raise RetirementRefusalError(reason)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-alembic-head", required=True)
    parser.add_argument("--expected-system-id", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-xer-sha256", required=True)
    for name in _TARGETS:
        parser.add_argument(f"--{name}-id", required=True)
    parser.add_argument("--apply-plan-sha256", help="Apply only this exact preview digest.")
    args = parser.parse_args(argv)
    try:
        for name, kind in _TARGETS.items():
            validate_identifier(getattr(args, f"{name}_id"), kind)
        settings = load_settings()
        expected = (args.expected_database, args.expected_system_id, args.expected_alembic_head)
        _require(
            settings.auth_mode.value == "local_operator"
            and settings.parsed_database_url().database == expected[0]
            and not settings.project_reports_enabled
            and not settings.project_reports_ingest_enabled
            and not settings.communications_ingest_enabled,
            "operator_runtime_mismatch",
        )
        principal = local_principal().principal_id
        engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30000)
        try:
            with (
                engine.connect().execution_options(isolation_level="SERIALIZABLE") as connection,
                connection.begin(),
            ):
                if args.apply_plan_sha256 is None:
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                actual = connection.execute(
                    text(
                        "SELECT current_database(), system_identifier::text, "
                        "(SELECT version_num FROM public.alembic_version) "
                        "FROM pg_control_system()"
                    )
                ).one()
                _require(tuple(actual) == expected, "database_identity_mismatch")
                if args.apply_plan_sha256 is not None:
                    connection.exec_driver_sql("SET LOCAL lock_timeout = '3s'")
                    got_lock = connection.execute(
                        text("SELECT pg_try_advisory_xact_lock(:key)"),
                        {"key": COMMS_INGEST_LOCK_KEY},
                    ).scalar_one()
                    _require(got_lock, "communications_ingestion_busy")
                outcome = retire_smoke_fixtures(
                    connection,
                    principal,
                    expected,
                    SmokeFixtureTarget(
                        args.message_id,
                        args.source_id,
                        args.publication_id,
                        args.scenario_id,
                        args.expected_source_sha256,
                        args.expected_xer_sha256,
                        args.apply_plan_sha256,
                    ),
                )
            print(json.dumps(outcome))
            return 0
        finally:
            engine.dispose()
    except RetirementRefusalError as error:
        print(json.dumps({"refused": str(error)}))
    except (ValueError, SQLAlchemyError):
        print(json.dumps({"refused": "invalid_input_or_database_failure"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
