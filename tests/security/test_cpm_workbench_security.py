"""CPM Workbench S5b-2 security guards (worker contract 3.15, 3.16, 6.2 section 40, 7).

FAST, no database. Each guard names what it can and cannot prove.

* **No content in errors** (R2 section 40, AC-034). No exception the S5b-2
  modules raise interpolates a value (`f"..."`, `.format`, `%`), and the two
  error types a hostile input reaches -- a schedule cursor and a canonical
  parse frame -- carry nothing of that input. It cannot prove a value never
  reaches an error through a constant built elsewhere; the database tier's
  disclosure and refusal tests cover the served answers.
* **A job error is a public code.** Every `JobExecutionError` the handler raises
  is built from an `ErrorCode` (the 11 codes `schedule_jobs.last_error_code`
  admits), and its message is that code's value only.
* **Nothing logs or prints** in the S5b-2 modules (the I7-A worker guard covers
  the 3 worker modules; this one covers the read service, delta, cursor and the
  pre-deploy checks too), and the parser child's `stderr` is discarded: a child
  writing a secret to fd 2 reaches neither this process's fd 2 nor the frame.
* **The pre-deploy checks are catalog reads only** (contract 3.16, Q59): every
  statement is a `SELECT`, the transaction's first statement is
  `SET TRANSACTION READ ONLY`, and the module executes nothing else.
* **AC-035:** no cross-domain link, frontend surface or legacy write -- the
  schedule modules write only schedule tables, import no lineage, Record Event
  or relationship persistence, never open SQLite, and `web/src` names a schedule
  capability only in the generated decoder fixture.
* **AC-001 / AC-002:** the S5b-2 modules carry no denylisted research-corpus token
  and import no XER/XML/P6 runtime.
"""

from __future__ import annotations

import ast
import re
import sys
import typing
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from tests.architecture.test_cpm_full_parser_scope import _denylisted

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.schedule.canonical import ParseResultDecodeError, parse_result_from_object
from my_pa.domain.schedule.cursor import (
    ScheduleCursorError,
    ScheduleCursorOrder,
    decode_schedule_cursor,
)
from my_pa.infrastructure.database.cpm_workbench_predeploy import READ_ONLY, STATEMENTS
from my_pa.infrastructure.jobs import schedule_parser_process as process
from my_pa.infrastructure.jobs.schedule_parser_process import TransientFailure
from my_pa.infrastructure.jobs.worker import JobExecutionError

ROOT: Final = Path(__file__).resolve().parents[2]
SRC: Final = ROOT / "src" / "my_pa"
HANDLER: Final = SRC / "infrastructure/jobs/schedule.py"
PARENT: Final = SRC / "infrastructure/jobs/schedule_parser_process.py"
CHILD: Final = SRC / "infrastructure/jobs/schedule_parser_child.py"
SERVICE: Final = SRC / "application/schedules.py"
COMPARE: Final = SRC / "domain/schedule/compare.py"
CURSOR: Final = SRC / "domain/schedule/cursor.py"
PREDEPLOY: Final = SRC / "infrastructure/database/cpm_workbench_predeploy.py"
PERSISTENCE: Final = SRC / "infrastructure/persistence/schedule.py"
RUNNER: Final = ROOT / "ops/postgres/cpm_workbench_predeploy_check.py"
#: Migration #2, found by its slug so this module does not pin the head revision.
(MIGRATION,) = sorted((ROOT / "migrations/versions").glob("*_cpm_workbench_vocabulary.py"))

#: The modules S5b-2 added (contract 3.15's "new modules" plus the I7-D checks).
NEW_MODULES: Final = (HANDLER, PARENT, CHILD, SERVICE, COMPARE, CURSOR, PREDEPLOY)
#: Every S5b-2 source file, new or changed, the scope guards read.
SCHEDULE_SOURCES: Final = (*NEW_MODULES, PERSISTENCE, RUNNER, MIGRATION)

SENTINEL: Final = "SENTINEL-S5B2-ACTIVITY-NAME-7f3c"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


# ---- R2 section 40, AC-034 -----------------------------------------------------------


def _interpolates(node: ast.AST) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.JoinedStr) and any(
            isinstance(part, ast.FormattedValue) for part in inner.values
        ):
            return True
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "format"
        ):
            return True
        if (
            isinstance(inner, ast.BinOp)
            and isinstance(inner.op, ast.Mod)
            and isinstance(inner.left, ast.Constant)
            and isinstance(inner.left.value, str)
        ):
            return True
    return False


def test_errors_carry_no_content() -> None:
    """No raise interpolates a value; hostile cursor and frame inputs stay out of errors."""
    wrong = [
        f"{path.relative_to(ROOT)}:{node.lineno}"
        for path in NEW_MODULES
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Raise) and node.exc is not None and _interpolates(node.exc)
    ]
    assert not wrong, f"an exception interpolates a value: {wrong}"

    with pytest.raises(ScheduleCursorError) as cursor_error:
        decode_schedule_cursor(
            SENTINEL,
            binding="0" * 64,
            order=ScheduleCursorOrder.ACTIVITIES,
            now=datetime(2026, 10, 31, tzinfo=UTC),
        )
    assert SENTINEL not in str(cursor_error.value)
    assert cursor_error.value.args == ("the schedule cursor cannot continue this request",)

    frame = {"schema": SENTINEL, "rows": [{"activity_name": SENTINEL}]}
    with pytest.raises(ParseResultDecodeError) as decode_error:
        parse_result_from_object(frame, typing.cast("typing.Any", None), {})
    assert SENTINEL not in str(decode_error.value)
    assert decode_error.value.args == ("not a canonical parse result",)


def test_job_error_is_a_public_code() -> None:
    """The handler's `JobExecutionError` arguments are `ErrorCode` members or typed codes."""
    arguments = [
        ast.unparse(node.args[0])
        for node in ast.walk(_tree(HANDLER))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "JobExecutionError"
    ]
    assert arguments, "the handler raises no JobExecutionError?"
    for argument in arguments:
        member = argument.removeprefix("ErrorCode.")
        if member != argument:
            assert member in ErrorCode.__members__, argument
        else:
            assert argument.endswith(".error_code"), argument
    assert typing.get_type_hints(TransientFailure)["error_code"] is ErrorCode
    assert len(ErrorCode) == 11
    for code in ErrorCode:
        assert str(JobExecutionError(code)) == f"the attempt failed with {code.value}"


def _calls(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.append(ast.unparse(node.func))
    return names


def test_new_modules_neither_log_nor_print() -> None:
    """No `print`, `logging`, `warnings`, `traceback` or stream write but the child's frame."""
    for path in NEW_MODULES:
        tree = _tree(path)
        roots = {name.split(".")[0] for name in _imports(tree)}
        assert not roots & {"logging", "warnings", "traceback"}, path.name
        calls = _calls(tree)
        assert "print" not in calls, path.name
        writes = [call for call in calls if call.startswith(("sys.stdout", "sys.stderr"))]
        expected = ["sys.stdout.buffer.write", "sys.stdout.buffer.flush"] if path == CHILD else []
        assert writes == expected, f"{path.name}: {writes}"


def test_child_stderr_is_discarded(capfd: pytest.CaptureFixture[str]) -> None:
    """A child's fd 2 is `DEVNULL`: a secret written there reaches no one."""
    spawn = next(
        node
        for node in ast.walk(_tree(PARENT))
        if isinstance(node, ast.FunctionDef) and node.name == "_spawn"
    )
    keywords = {
        keyword.arg: ast.unparse(keyword.value)
        for node in ast.walk(spawn)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
    }
    assert keywords["stderr"] == "subprocess.DEVNULL"
    capfd.readouterr()
    body = (
        "import sys, os\n"
        f"os.write(2, b'{SENTINEL}-fd2\\n')\n"
        f"sys.stderr.write('{SENTINEL}-stream\\n'); sys.stderr.flush()\n"
        "raise RuntimeError('" + SENTINEL + "-traceback')"
    )
    command = (
        sys.executable,
        "-I",
        "-B",
        "-c",
        "import sys; sys.path.insert(0, sys.argv[1])\n" + body,
    )
    outcome = process.run_isolated_parse(
        b"%PDF-", expected_data_date=None, wall_seconds=10.0, command=command
    )
    assert outcome == TransientFailure(ErrorCode.INTERNAL_ERROR)
    captured = capfd.readouterr()
    assert SENTINEL not in captured.err
    assert SENTINEL not in captured.out


# ---- contract 3.16, Q59 -------------------------------------------------------------------

_WRITE_WORDS: Final = re.compile(
    r"\b(INSERT|UPDATE|DELETE|TRUNCATE|MERGE|GRANT|REVOKE|CREATE|ALTER|DROP|COPY|LOCK|"
    r"COMMENT|VACUUM|ANALYZE|REINDEX|CLUSTER|REFRESH|CALL|DO|EXECUTE|PREPARE|LISTEN|NOTIFY|"
    r"SECURITY|RESET|SET)\b",
    re.IGNORECASE,
)
_WRITE_FUNCTIONS: Final = re.compile(
    r"\b(set_config|nextval|setval|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|"
    r"pg_rotate_logfile|pg_advisory\w*|pg_try_advisory\w*|lo_\w+|dblink\w*|"
    r"pg_switch_wal|pg_create\w*|pg_drop\w*|pg_promote|pg_stat_reset\w*|txid_current|"
    r"pg_current_xact_id|pg_notify|pg_sleep\w*)\s*\(",
    re.IGNORECASE,
)


def test_predeploy_sql_is_select_only() -> None:
    """Every statement is a `SELECT`; the module executes nothing else but `READ ONLY` first."""
    assert READ_ONLY == "SET TRANSACTION READ ONLY"
    assert STATEMENTS
    for key, sql in STATEMENTS.items():
        assert sql.startswith("SELECT "), key
        # Quoted literals are data (privilege names for `has_table_privilege`).
        statement = re.sub(r"'[^']*'", "''", sql)
        assert ";" not in statement, key
        assert not _WRITE_WORDS.search(statement), (key, _WRITE_WORDS.search(statement))
        assert not _WRITE_FUNCTIONS.search(statement), (key, _WRITE_FUNCTIONS.search(statement))
        assert not re.search(r"\bFOR\s+(UPDATE|SHARE|NO\s+KEY|KEY)\b", statement, re.I), key

    tree = _tree(PREDEPLOY)
    texts = [
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "text"
    ]
    assert texts, "the checks build no statement?"
    for argument in texts:
        assert argument == "READ_ONLY" or argument.startswith("STATEMENTS["), argument
    # `READ_ONLY` is the transaction's first statement, right after `begin()`.
    run = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_predeploy_checks"
    )
    executes = [
        ast.unparse(node)
        for node in ast.walk(run)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"execute", "begin", "commit", "exec_driver_sql"}
    ]
    assert executes[:2] == ["connection.begin()", "connection.execute(text(READ_ONLY))"], executes
    assert "commit" not in " ".join(_calls(tree)), "the checks never commit"
    assert "exec_driver_sql" not in " ".join(_calls(tree))
    runner = _calls(_tree(RUNNER))
    assert not [call for call in runner if call.endswith(("execute", "text", "exec_driver_sql"))]


# ---- AC-035 --------------------------------------------------------------------------------

_SCHEDULE_CAPABILITY_NAMES: Final = (
    "schedule_publications.import",
    "schedule_series.list",
    "schedule_publications.list",
    "schedule_publications.read",
    "schedule_activities.list",
    "schedule_activities.history",
    "schedule_changes.list",
)
_GENERATED_FIXTURE: Final = ROOT / "web/src/lib/api/decode/fixtures/python/success.json"
#: Live tables the schedule persistence may read (ownership, admission) and never write.
_READ_ONLY_TABLES: Final = frozenset(
    {"enrollment_objects", "enrollments", "projects", "source_object_versions"}
)
#: The only persistence modules a schedule source may import: its own repository,
#: the job plane, the table registry and the Principal partition helper. Every
#: other persistence module (lineage, Record Events, Tasks, Commitments,
#: Constraints, relationships, Situations, Knowledge Assertions...) is another domain.
_PERSISTENCE_ALLOWED: Final = frozenset(
    {
        "my_pa.infrastructure.persistence.schedule",
        "my_pa.infrastructure.persistence.jobs",
        "my_pa.infrastructure.persistence.tables",
        "my_pa.infrastructure.persistence.principal_scope",
        # Schedule Scenarios S6-2 (schedule scenarios contract sections 14.8.5 and
        # 14.8.7): the admission writes its import-time approval through the plane
        # module, and the worker's H8 and fail paths run in the plane's unit of
        # work. The plane is the schedule evidence plane's own successor, not
        # another domain; the cross-domain prefixes below stay refused.
        "my_pa.infrastructure.persistence.schedule_scenarios",
    }
)
_CROSS_DOMAIN_PREFIXES: Final = (
    "my_pa.domain.lineage",
    "my_pa.domain.record_events",
    "my_pa.domain.relationship",
    "my_pa.domain.situation",
    "my_pa.domain.task",
    "my_pa.domain.project_controls",
    "my_pa.domain.knowledge_assertion",
    "my_pa.domain.meeting",
    "my_pa.domain.program",
    "my_pa.application.record_events",
)


def test_no_cross_domain_link_frontend_or_legacy_write() -> None:
    wrong: list[str] = []
    for path in SCHEDULE_SOURCES:
        tree = _tree(path)
        for name in _imports(tree):
            other_persistence = (
                name.startswith("my_pa.infrastructure.persistence.")
                and name not in _PERSISTENCE_ALLOWED
            )
            if (
                other_persistence
                or name.startswith(_CROSS_DOMAIN_PREFIXES)
                or name.split(".")[0] == "sqlite3"
            ):
                wrong.append(f"{path.name} imports {name}")
    persistence = _tree(PERSISTENCE)
    imported_tables = {
        alias.name
        for node in ast.walk(persistence)
        if isinstance(node, ast.ImportFrom)
        and node.module == "my_pa.infrastructure.persistence.tables"
        for alias in node.names
    }
    unexpected = {
        name
        for name in imported_tables
        if not name.startswith("schedule_") and name not in _READ_ONLY_TABLES | {"JobState"}
    }
    assert not unexpected, f"schedule persistence reaches other tables: {sorted(unexpected)}"
    for node in ast.walk(persistence):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"insert", "update", "delete", "pg_insert"}
            and node.args
            and ast.unparse(node.args[0]) in _READ_ONLY_TABLES
        ):
            wrong.append(f"schedule persistence writes {ast.unparse(node.args[0])}:{node.lineno}")
    migration = MIGRATION.read_text(encoding="utf-8")
    for token in (
        "CREATE TABLE",
        "REFERENCES",
        "FOREIGN KEY",
        "create_table",
        "create_foreign_key",
    ):
        if token in migration:
            wrong.append(f"migration #2 holds {token}")
    web = ROOT / "web" / "src"
    assert web.is_dir()
    for path in sorted(web.rglob("*")):
        if not path.is_file() or path == _GENERATED_FIXTURE or "node_modules" in path.parts:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        wrong += [
            f"{path.relative_to(ROOT)} names {name}"
            for name in _SCHEDULE_CAPABILITY_NAMES
            if name in content
        ]
    assert not wrong, wrong


# ---- AC-001, AC-002 ----------------------------------------------------------------------------


def test_s5b2_files_carry_no_denylisted_token() -> None:
    """The S5a neutral-naming denylist over every S5b-2 source, test and document."""
    targets = [
        *SCHEDULE_SOURCES,
        ROOT / "tests/unit/test_schedule_parser_isolation.py",
        ROOT / "tests/unit/test_schedule_compare.py",
        ROOT / "tests/unit/test_schedule_cursor.py",
        ROOT / "tests/unit/test_schedule_commands.py",
        ROOT / "tests/database/test_cpm_workbench_worker.py",
        ROOT / "tests/database/test_schedule_capabilities.py",
        ROOT / "tests/database/schedule_capability_harness.py",
        ROOT / "tests/database/test_cpm_workbench_change_performance.py",
        ROOT / "tests/database/test_cpm_workbench_predeploy.py",
        ROOT / "tests/integration/test_schedule_compact_facade.py",
        ROOT / "tests/schema/test_cpm_workbench_vocabulary_migration.py",
        ROOT / "docs/architecture/cpm-workbench-worker-capabilities-contract.md",
        ROOT / "docs/architecture/cpm-workbench.md",
        ROOT / "ops/runbooks/cpm-workbench.md",
        ROOT / "docs/decisions/ADR-016-cpm-workbench-schedule-evidence.md",
    ]
    missing = [str(path.relative_to(ROOT)) for path in targets if not path.is_file()]
    assert not missing, missing
    offending = {
        str(path.relative_to(ROOT)): sorted(found)
        for path in targets
        if (found := _denylisted(path.read_bytes()))
    }
    assert not offending, f"denylisted research-corpus tokens: {offending}"


_XER_XML_RUNTIME: Final = frozenset(
    {"xml", "lxml", "defusedxml", "xmltodict", "openpyxl", "xlrd", "sqlite3", "jpype", "py4j"}
)


def test_no_xer_or_xml_runtime_in_the_schedule_plane() -> None:
    """R2 AC-002: the schedule plane reads only the P6 PDF profile (lineage WP-05B is not built)."""
    wrong = [
        f"{path.name} imports {name}"
        for path in SCHEDULE_SOURCES
        for name in _imports(_tree(path))
        if name.split(".")[0] in _XER_XML_RUNTIME
    ]
    assert not wrong, wrong
