"""Exercise an exact release in one isolated synthetic PostgreSQL 17 catalog."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

COMMIT = "cbf57bf3823a8f4399c67282f91c1596b1713d24"
TREE = "c503df2b844e8d87e053d98ea6060117eee4371d"
BASE = "4d1069a7d84f"
HEAD = "859e93b47a21"
ROLE = "combined_rehearsal"
CATALOG = "combined_rehearsal_app"
FLAG_NAMES = ("COMMUNICATIONS", "PROJECT_REPORTS", "SCHEDULE", "SCHEDULE_P6", "SCHEDULE_SCENARIOS")
PLAN = (
    ("all_off", (False, False, False, False, False)),
    ("reports_only", (False, True, False, False, False)),
    ("wp5_only", (True, True, False, False, False)),
    ("p6_without_schedule", (False, False, False, True, False)),
    ("schedule_only", (False, False, True, True, True)),
    ("all_on", (True, True, True, True, True)),
)
WP5 = {"meetings.context.read"}
PULSE = {
    "project_reports.catalog",
    "project_reports.query",
    "project_reports.record_history",
    "project_reports.compare",
    "project_reports.coverage",
}
P6 = {
    "schedule_publications.import_p6",
    "schedule_p6_fields.available",
    "schedule_p6_fields.set_captured",
    "schedule_p6_activities.list",
    "schedule_p6_relationships.list",
    "schedule_p6_calendars.list",
    "schedule_p6_field_values.list",
}
SCENARIO = {"schedule_scenarios.create"}


class RefusalError(Exception):
    """A closed refusal reason produced by this driver."""


def emit(stage: str, status: str, **attributes: object) -> None:
    payload = json.dumps(
        {"stage": stage, "status": status, **attributes}, sort_keys=True, separators=(",", ":")
    )
    annotation = "notice" if status == "pass" else "error"
    print(f"::{annotation} title=Combined release rehearsal::{payload}", flush=True)


def public_git(repo: Path, *args: str) -> str:
    return subprocess.check_output(  # noqa: S603 - fixed public Git queries
        ["/usr/bin/git", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=15,
    ).strip()


def check_source(repo: Path) -> None:
    if (
        public_git(repo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines() != [COMMIT, TREE]
        or Path(public_git(repo, "rev-parse", "--show-toplevel")).resolve() != repo
        or public_git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    ):
        raise RefusalError("release_checkout_mismatch")


def check_fixture(port: int, system_id: str) -> str | None:
    import psycopg

    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user=ROLE,
            dbname=CATALOG,
            sslmode="disable",
            passfile="/dev/null",
            connect_timeout=5,
            options="-c statement_timeout=5000 -c default_transaction_read_only=on",
        ) as conn:
            ident = conn.execute(
                "SELECT system_identifier::text, current_user, current_database(), "
                "current_setting('server_version_num')::integer, pg_is_in_recovery() "
                "FROM pg_catalog.pg_control_system()"
            ).fetchone()
            if (
                ident is None
                or ident[:3] != (system_id, ROLE, CATALOG)
                or not (170000 <= ident[3] < 180000 and ident[4] is False)
            ):
                raise RefusalError("fixture_identity_mismatch")
            names = conn.execute("SELECT datname FROM pg_catalog.pg_database").fetchall()
            if {row[0] for row in names} != {"postgres", "template0", "template1", CATALOG}:
                raise RefusalError("fixture_catalog_set_mismatch")
            version_table = conn.execute(
                "SELECT pg_catalog.to_regclass('public.alembic_version') IS NOT NULL"
            ).fetchone()
            if version_table == (False,):
                user_objects = conn.execute(
                    "SELECT count(*) FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON c.relnamespace = n.oid "
                    "WHERE n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\' "
                    "AND n.nspname <> 'information_schema'"
                ).fetchone()
                if user_objects != (0,):
                    raise RefusalError("fixture_not_empty")
                return None
            if version_table != (True,):
                raise RefusalError("fixture_version_table_unreadable")
            revisions = conn.execute("SELECT version_num FROM public.alembic_version").fetchall()
            if len(revisions) != 1 or revisions[0][0] not in {BASE, HEAD}:
                raise RefusalError("fixture_revision_not_expected")
            return revisions[0][0]
    except psycopg.Error as exc:
        raise RefusalError("fixture_verification_failed") from exc


def environment(repo: Path, port: int) -> dict[str, str]:
    url = (
        f"postgresql+psycopg://{ROLE}@127.0.0.1:{port}/{CATALOG}"
        "?sslmode=disable&passfile=%2Fdev%2Fnull"
    )
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(repo), str(repo / "src"))),
        "MY_PA_DATABASE_URL": url,
        "MY_PA_MIGRATION_DATABASE_URL": url,
        "MY_PA_AUTH_MODE": "local_operator",
    }


def run(repo: Path, env: dict[str, str], args: list[str]) -> tuple[int, str]:
    result = subprocess.run(  # noqa: S603 - fixed release CLI invocations
        [sys.executable, *args],
        cwd=repo,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=150,
        check=False,
    )
    if len(result.stdout) > 1_048_576:
        raise RefusalError("child_output_too_large")
    return result.returncode, result.stdout.decode("utf-8", errors="strict")


def upgrade(repo: Path, env: dict[str, str], revision: str) -> None:
    code, _ = run(repo, env, ["-m", "alembic", "-c", "alembic.ini", "upgrade", revision])
    if code != 0:
        raise RefusalError("forward_migration_failed")


def check_health(repo: Path, env: dict[str, str], revision: str, *, ready: bool) -> None:
    code, output = run(repo, env, ["apps/cli/health.py"])
    lines = output.splitlines()
    expected = {
        "state": "ready" if ready else "not_at_head",
        "revision": revision,
        "head": HEAD,
    }
    if code != (0 if ready else 1) or any(
        [line.split(maxsplit=1)[1] for line in lines if line.startswith(f"{key} ")] != [value]
        for key, value in expected.items()
    ):
        raise RefusalError("application_readiness_mismatch")


def checked_catalog(
    repo: Path, env: dict[str, str], principal: str, stage: str, flags: tuple[bool, ...]
) -> dict[str, int]:
    fixture_env = {
        **env,
        **{
            f"MY_PA_{name}_ENABLED": str(flag).lower()
            for name, flag in zip(FLAG_NAMES, flags, strict=True)
        },
    }
    code, output = run(
        repo,
        fixture_env,
        [
            "apps/cli/invoke.py",
            "capabilities.get",
            "--request-id",
            f"combined-{stage}",
            "--purpose",
            "status_observation",
            "--principal-id",
            principal,
            "--requested-at",
            datetime.now(UTC).isoformat(),
        ],
    )
    if code != 0:
        raise RefusalError("catalog_invocation_failed")
    envelope = json.loads(output)
    if envelope.get("error") is not None:
        raise RefusalError("catalog_invocation_failed")
    entries = envelope["result"]["manifest"]["capabilities"]
    observed = {entry["name"]: entry["availability"] for entry in entries}
    if len(observed) != len(entries):
        raise RefusalError("duplicate_catalog_names")
    communications, reports, schedule, p6, scenarios = flags
    targets = (
        ("wp5", WP5, communications),
        ("pulse", PULSE, reports),
        ("p6", P6, schedule and p6),
        ("scenario_create", SCENARIO, schedule and scenarios),
    )
    counts: dict[str, int] = {}
    for label, names, expected in targets:
        state = "available" if expected else "not_implemented"
        if any(observed.get(name) != state for name in names):
            raise RefusalError("cross_plane_catalog_mismatch")
        counts[label] = len(names) if expected else 0
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--expected-system-identifier", required=True)
    parser.add_argument("--port", type=int, default=5432)
    options = parser.parse_args()
    stage = "preflight"
    try:
        if (
            sys.platform != "linux"
            or not 1024 <= options.port <= 65535
            or re.fullmatch(r"[0-9]{1,20}", options.expected_system_identifier) is None
            or any(key.startswith("PG") for key in os.environ)
        ):
            raise RefusalError("linux_private_fixture_required")
        repo = options.release.resolve()
        env = environment(repo, options.port)
        check_source(repo)

        def fixture(expected: str | None) -> None:
            if check_fixture(options.port, options.expected_system_identifier) != expected:
                raise RefusalError("unexpected_rehearsal_revision")

        fixture(None)
        emit(stage, "pass", commit=COMMIT, tree=TREE, fixture="private_pg17")
        stage = "seed_archived_schema"
        upgrade(repo, env, BASE)
        fixture(BASE)
        check_health(repo, env, BASE, ready=False)
        emit(stage, "pass", revision=BASE, release_ready=False)
        stage = "upgrade_release"
        check_source(repo)
        fixture(BASE)
        upgrade(repo, env, "head")
        fixture(HEAD)
        check_health(repo, env, HEAD, ready=True)
        emit(stage, "pass", revision=HEAD, release_ready=True)
        stage = "synthetic_operator"
        code, raw = run(
            repo,
            env,
            [
                "-c",
                "from my_pa.bootstrap.gateway import local_principal; "
                "print(local_principal().principal_id)",
            ],
        )
        principal = raw.strip()
        if code != 0 or re.fullmatch(r"prn_[a-z0-9]{10,64}", principal) is None:
            raise RefusalError("fixture_principal_mismatch")
        for stage, flags in PLAN:
            fixture(HEAD)
            counts = checked_catalog(repo, env, principal, stage, flags)
            emit(stage, "pass", **counts)
        stage = "complete"
        fixture(HEAD)
        check_source(repo)
        emit(stage, "pass", revision=HEAD)
        return 0
    except RefusalError as exc:
        emit(stage, "refused", code=str(exc))
        return 1
    except (
        ImportError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
        IndexError,
    ):
        emit(stage, "refused", code="rehearsal_execution_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
