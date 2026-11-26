"""Read only the approved synthetic timings from a paired WP4 PG17 replay."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

MAIN = (
    "f1136b2a09332b8ce939b5b56d71200a12ce3cf1",
    "770f4fc5eaf97f9b00cfa6591e5617f3ff690ee9",
)
WP5 = (
    "d63ad9fb062a8c5910f2c4b478e6351dcd40d903",
    "2b0d95b120b50423aaf7f0b6225519d943950ebf",
)
ROLE = "wp4_diagnostic"
APP_DB = "wp4_diagnostic_app"
BENCHMARK = (
    "tests/database/test_communications_search_latency.py"
    "::test_the_latency_record_at_real_corpus_size"
)
PREFIX = (
    "tests/database/test_communications_measure_context_cli.py"
    "::test_measure_context_on_the_seed"
)
PLAN = ("main", "wp5", "wp5_prefix", "wp5_prefix", "wp5", "main")
SHAPES = (
    "search_20_english",
    "search_20_fallback",
    "search_20_identifier",
    "search_20_browse",
    "read_25_ids",
)
TIMING = re.compile(r"p50=([0-9]{1,9}\.[0-9])ms p95=([0-9]{1,9}\.[0-9])ms")
LOCALE = re.compile(r"[A-Za-z0-9_.@-]{1,32}")
SYSTEM_ID = re.compile(r"[0-9]{1,20}")
PHASES = ("setup", "call", "teardown")
OUTCOMES = ("passed", "failed", "skipped")
CURRENT_HEAD = (
    "(database_clone or database_transactional) and not recovery and not e2e "
    "and not migration_edge and not migration_empty_to_head and not migration"
)


class Refusal(Exception):
    """A closed diagnostic refusal code safe to include in an annotation."""


def emit(title: str, value: dict[str, Any]) -> None:
    """Publish bounded, structured output only."""
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).replace(
        "%", "%25"
    )
    print(f"::notice title={title}::{payload}", flush=True)


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=15,
    ).strip()


def check_source(repo: Path, expected: tuple[str, str]) -> None:
    try:
        observed = git(repo, "rev-parse", "HEAD", "HEAD^{tree}").splitlines()
        top = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
        dirty = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as exc:
        raise Refusal("checkout_verification_failed") from exc
    if tuple(observed) != expected or top != repo or dirty:
        raise Refusal("checkout_identity_or_cleanliness_mismatch")


def verify_database(port: int, system_identifier: str) -> dict[str, Any]:
    """Admit only the named private fixture. Inspect catalogs after checking server identity."""
    import psycopg

    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user=ROLE,
            dbname="postgres",
            passfile="/dev/null",
            sslmode="disable",
            connect_timeout=5,
            options="-c statement_timeout=5000 -c default_transaction_read_only=on",
        ) as conn:
            identity = conn.execute(
                "SELECT system_identifier::text, current_user, current_database(), "
                "current_setting('server_version_num')::integer, pg_is_in_recovery() "
                "FROM pg_catalog.pg_control_system()"
            ).fetchone()
            if (
                identity is None
                or identity[:3] != (system_identifier, ROLE, "postgres")
                or not 170000 <= identity[3] < 180000
                or identity[4]
            ):
                raise Refusal("fixture_identity_mismatch")

            application = conn.execute(
                "SELECT datcollate, datctype, datlocprovider::text, "
                "pg_catalog.pg_encoding_to_char(encoding) "
                "FROM pg_catalog.pg_database WHERE datname = %s",
                (APP_DB,),
            ).fetchone()
            template = conn.execute(
                "SELECT datcollate, datctype, datlocprovider::text, "
                "pg_catalog.pg_encoding_to_char(encoding) "
                "FROM pg_catalog.pg_database WHERE datname = 'template0'"
            ).fetchone()
            pristine = conn.execute(
                "SELECT count(*) = 4 AND bool_and(datname::text = ANY (%s::text[])) "
                "FROM pg_catalog.pg_database",
                (["postgres", "template0", "template1", APP_DB],),
            ).fetchone()
            settings = conn.execute(
                "SELECT pg_catalog.pg_size_bytes(current_setting('shared_buffers')), "
                "pg_catalog.pg_size_bytes(current_setting('work_mem')), "
                "current_setting('max_parallel_workers_per_gather')::integer, "
                "current_setting('jit') = 'on', "
                "pg_catalog.to_tsvector('english', 'ÄRGER') @@ "
                "pg_catalog.to_tsquery('english', 'ärger')"
            ).fetchone()
            if (
                pristine != (True,)
                or application is None
                or application != template
                or application[2] not in {"b", "c", "i"}
                or application[3] != "UTF8"
                or not all(LOCALE.fullmatch(part) for part in application[:2])
                or settings is None
                or settings[4] is not True
            ):
                raise Refusal("fixture_catalog_locale_or_cleanliness_mismatch")
            return {
                "server_version_num": identity[3],
                "datcollate": application[0],
                "datctype": application[1],
                "locale_provider": application[2],
                "encoding": application[3],
                "shared_buffers_bytes": settings[0],
                "work_mem_bytes": settings[1],
                "max_parallel_workers_per_gather": settings[2],
                "jit": settings[3],
            }
    except psycopg.Error as exc:
        raise Refusal("fixture_verification_failed") from exc


class Reports:
    """Reduce pytest reports to allowlisted phases and synthetic timing properties."""

    def __init__(self) -> None:
        self.phases: dict[str, dict[str, str]] = {}
        self.timings: dict[str, dict[str, float]] = {}
        self.call_order: list[str] = []

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.nodeid == BENCHMARK:
            role = "benchmark"
        elif report.nodeid == PREFIX:
            role = "prefix"
        else:
            return
        if report.when not in PHASES or report.outcome not in OUTCOMES:
            return
        self.phases.setdefault(role, {})[report.when] = report.outcome
        if report.when != "call":
            return
        self.call_order.append(role)
        if role == "benchmark":
            for name, value in report.user_properties:
                if (
                    name in SHAPES
                    and isinstance(value, str)
                    and (match := TIMING.fullmatch(value))
                ):
                    p50, p95 = map(float, match.groups())
                    if p50 <= p95:
                        self.timings[name] = {"p50_ms": p50, "p95_ms": p95}


def capture_benchmark(arm: str, output: str) -> int:
    """Run originals unchanged. Subprocess output is discarded by its parent."""
    import pytest

    report = Reports()
    cases = [PREFIX, BENCHMARK] if arm == "wp5_prefix" else [BENCHMARK]
    code = int(
        pytest.main(
            ["-q", "-p", "no:cacheprovider", "--tb=no", "-m", CURRENT_HEAD, *cases],
            plugins=[report],
        )
    )
    Path(output).write_text(
        json.dumps(
            {
                "pytest_exit": code,
                "phases": report.phases,
                "call_order": report.call_order,
                "timings_ms": report.timings,
            },
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return code


def trial_env(repo: Path, port: int) -> dict[str, str]:
    """Do not carry the runner's application, pytest, or PostgreSQL settings."""
    url = (
        f"postgresql+psycopg://{ROLE}@127.0.0.1:{port}/{APP_DB}"
        "?sslmode=disable&passfile=%2Fdev%2Fnull"
    )
    return {
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": os.pathsep.join((str(repo), str(repo / "src"))),
        "MY_PA_DATABASE_URL": url,
        "MY_PA_MIGRATION_DATABASE_URL": url,
    }


def evaluate(result: dict[str, Any], arm: str) -> str:
    expect_order = ["prefix", "benchmark"] if arm == "wp5_prefix" else ["benchmark"]
    if result["call_order"] != expect_order:
        return "incomplete"
    phases = result["phases"]
    for expected in expect_order:
        observed = phases.get(expected, {})
        if observed.get("setup") != "passed" or observed.get("teardown") != "passed":
            return "incomplete"
        if expected == "prefix" and observed.get("call") != "passed":
            return "prefix_failed"
    timings = result["timings_ms"]
    if set(timings) != set(SHAPES):
        return "incomplete"
    over_ceiling = any(timing["p95_ms"] >= 1000 for timing in timings.values())
    benchmark = phases["benchmark"]["call"]
    if benchmark == "passed" and result["pytest_exit"] == 0:
        return "pass"
    if benchmark == "failed" and result["pytest_exit"] == 1 and over_ceiling:
        return "p95_ceiling_failed"
    return "unexpected_test_outcome"


def run_trial(repo: Path, arm: str, port: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="wp4-pg17-trial-") as tmp:
        output = Path(tmp) / "result.json"
        child = (
            "import runpy, sys; "
            "entry = runpy.run_path(sys.argv[1])['capture_benchmark']; "
            "raise SystemExit(entry(sys.argv[2], sys.argv[3]))"
        )
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    child,
                    str(Path(__file__).resolve()),
                    arm,
                    str(output),
                ],
                cwd=repo,
                env=trial_env(repo, port),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=480,
                check=False,
            )
            if not output.is_file() or output.stat().st_size > 16_384:
                return {"status": "incomplete"}
            result = json.loads(output.read_text(encoding="utf-8"))
            if result["pytest_exit"] != process.returncode:
                return {"status": "incomplete"}
            return {
                "status": evaluate(result, arm),
                "pytest_exit": result["pytest_exit"],
                "phases": result["phases"],
                "timings_ms": result["timings_ms"],
            }
        except subprocess.TimeoutExpired:
            return {"status": "timed_out"}
        except (OSError, ValueError, KeyError):
            return {"status": "incomplete"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--expected-system-identifier", required=True)
    options = parser.parse_args()
    try:
        if (
            sys.platform != "linux"
            or not 1024 <= options.port <= 65535
            or not SYSTEM_ID.fullmatch(options.expected_system_identifier)
            or any(key.startswith("PG") for key in os.environ)
        ):
            raise Refusal("linux_and_explicit_isolated_fixture_required")
        repos = {
            "main": (options.base.resolve(), MAIN),
            "wp5": (options.candidate.resolve(), WP5),
            "wp5_prefix": (options.candidate.resolve(), WP5),
        }
        for repo, ref in set(repos.values()):
            check_source(repo, ref)
        fixture = verify_database(options.port, options.expected_system_identifier)
        emit(
            "WP4 PostgreSQL 17 fixtures",
            {
                "base_head": MAIN[0],
                "base_tree": MAIN[1],
                "candidate_head": WP5[0],
                "candidate_tree": WP5[1],
                "fixture": fixture,
                "trial_order": PLAN,
            },
        )
        all_passed = True
        for number, arm in enumerate(PLAN, start=1):
            repo, ref = repos[arm]
            check_source(repo, ref)
            if (
                verify_database(options.port, options.expected_system_identifier)
                != fixture
            ):
                raise Refusal("fixture_settings_drifted")
            result = run_trial(repo, arm, options.port)
            emit("WP4 PostgreSQL 17 trial", {"trial": number, "arm": arm, **result})
            all_passed &= result["status"] == "pass"
            if (
                verify_database(options.port, options.expected_system_identifier)
                != fixture
            ):
                raise Refusal("fixture_settings_drifted")
        emit(
            "WP4 PostgreSQL 17 outcome",
            {
                "trials": len(PLAN),
                "all_original_assertions_passed": all_passed,
            },
        )
        return 0 if all_passed else 1
    except Refusal as exc:
        emit("WP4 PostgreSQL 17 refusal", {"status": str(exc)})
        return 2
    except (ImportError, OSError, subprocess.SubprocessError):
        emit("WP4 PostgreSQL 17 refusal", {"status": "diagnostic_setup_failed"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
