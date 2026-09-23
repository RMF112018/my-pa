"""GitHub Actions failure annotations remain bounded and failure-safe."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from my_pa.bootstrap.settings import load_settings

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "tests" / "conftest.py"


def _hook_module() -> ModuleType:
    for module in sys.modules.values():
        path = getattr(module, "__file__", None)
        if path is not None and Path(path).resolve() == HOOK_PATH:
            return module
    raise AssertionError("pytest did not load the root annotation hook")


def _reset(hook: ModuleType) -> None:
    hook.pytest_sessionstart(SimpleNamespace())


def _fast_run_script(name: str) -> str:
    """Extract one checked-in literal Actions run block without a YAML dependency."""
    lines = (
        (ROOT / ".github/workflows/repository-checks.yml").read_text(encoding="utf-8").splitlines()
    )
    start = lines.index(f"      - name: {name}")
    run = lines.index("        run: |", start)
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.startswith("          "):
            body.append(line[10:])
        elif not line:
            body.append("")
        else:
            break
    return "\n".join(body)


def _synthetic_ledger(tmp_path: Path) -> tuple[Path, Path]:
    """Model a permissive runner temp with one protected 0700 child."""
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    runner_temp.chmod(0o777)
    private = runner_temp / "my-pa-fast-ledger.ABCDEFGH"
    private.mkdir(mode=0o700)
    ledger = private / "failures.ABCDEFGH"
    ledger.touch(mode=0o600)
    ledger.chmod(0o600)
    return runner_temp, ledger


@pytest.fixture(autouse=True)
def _clear_synthetic_annotation_queue_between_tests(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep direct hook exercises isolated from this module's outer session."""
    monkeypatch.delenv("CI_PYTEST_FAILURE_LEDGER", raising=False)
    hook = _hook_module()
    hook._GITHUB_ACTIONS_FAILURES.clear()
    hook._GITHUB_ACTIONS_FAILURE_KEYS.clear()
    try:
        yield
    finally:
        hook._GITHUB_ACTIONS_FAILURES.clear()
        hook._GITHUB_ACTIONS_FAILURE_KEYS.clear()


@pytest.mark.parametrize("value", [None, "", "false", "TRUE", "1"])
def test_annotations_are_silent_when_github_actions_is_not_exactly_true(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str | None
) -> None:
    hook = _hook_module()
    _reset(hook)
    if value is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", value)

    hook.pytest_runtest_logreport(
        SimpleNamespace(failed=True, when="call", nodeid="tests/unit/test_example.py::test_case")
    )
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == ""
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_failed_reports_emit_immediately_and_replay_once_at_session_finish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    for phase in ("setup", "call", "teardown"):
        hook.pytest_runtest_logreport(
            SimpleNamespace(
                failed=True,
                when=phase,
                nodeid=f"tests/unit/test_example.py::test_{phase}",
            )
        )
    hook.pytest_collectreport(
        SimpleNamespace(failed=True, nodeid="tests/unit/test_collection_failure.py")
    )

    expected = (
        "::error title=pytest failed::phase=setup; "
        "nodeid=tests/unit/test_example.py::test_setup\n"
        "::error title=pytest failed::phase=call; "
        "nodeid=tests/unit/test_example.py::test_call\n"
        "::error title=pytest failed::phase=teardown; "
        "nodeid=tests/unit/test_example.py::test_teardown\n"
        "::error title=pytest failed::phase=collection; "
        "nodeid=tests/unit/test_collection_failure.py\n"
    )
    assert capsys.readouterr().out == expected
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == expected
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_duplicate_failed_reports_emit_one_immediate_and_one_final_annotation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    report = SimpleNamespace(
        failed=True, when="call", nodeid="tests/unit/test_example.py::test_duplicate"
    )

    hook.pytest_runtest_logreport(report)
    hook.pytest_runtest_logreport(report)
    expected = (
        "::error title=pytest failed::phase=call; "
        "nodeid=tests/unit/test_example.py::test_duplicate\n"
    )
    assert capsys.readouterr().out == expected
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == expected


def test_session_failure_without_reports_emits_numeric_status_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=2)

    assert capsys.readouterr().out == "::error title=pytest failed::phase=session; exitstatus=2\n"
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS

    python = tmp_path / "python"
    python.write_text(
        "#!/bin/sh\n"
        'if [ "$1" != "-m" ] || [ "$2" != "pytest" ]; then\n'
        '  exec "$SYNTHETIC_REAL_PYTHON" "$@"\n'
        "fi\n"
        'if [ -n "${SYNTHETIC_PYTEST_ANNOTATION-}" ]; then\n'
        '  printf "%s\\n" "$SYNTHETIC_PYTEST_ANNOTATION" >> "$CI_PYTEST_FAILURE_LEDGER"\n'
        "fi\n"
        'if [ "${SYNTHETIC_PYTEST_NUL-}" = 1 ]; then\n'
        "  printf '::error title=pytest failed::phase=call; "
        "nodeid=tests/unit/test_bad\\000synthetic-secret-marker\\n' "
        '>> "$CI_PYTEST_FAILURE_LEDGER"\n'
        "fi\n"
        'if [ -n "${SYNTHETIC_PYTEST_UNTERMINATED-}" ]; then\n'
        '  printf "%s" "$SYNTHETIC_PYTEST_UNTERMINATED" >> "$CI_PYTEST_FAILURE_LEDGER"\n'
        "fi\n"
        'if [ "${SYNTHETIC_PROBE_FD9-}" = 1 ]; then\n'
        "  if ( IFS= read -r _ <&9 ) 2>/dev/null; then exit 98; fi\n"
        "fi\n"
        'exit "$SYNTHETIC_PYTEST_EXIT"\n',
        encoding="ascii",
    )
    python.chmod(0o700)
    runner_temp = tmp_path / "permissive-runner-temp"
    runner_temp.mkdir()
    runner_temp.chmod(0o777)
    marker = (
        'python -m pytest -m "not slow and not database and not network and not connector '
        'and not evaluation and not e2e and not recovery"'
    )
    ledger_name = "CI_PYTEST_FAILURE_LEDGER"
    assert f'os.environ.get("{ledger_name}", "")' in HOOK_PATH.read_text(encoding="utf-8")
    load_settings(
        {
            "MY_PA_DATABASE_URL": "postgresql+psycopg://localhost/my_pa",
            ledger_name: "synthetic-ledger-path",
        }
    )
    for name in ("Test Python FAST tier", "Test Python FAST tier at the declared floor"):
        script = _fast_run_script(name)
        assert f'export {ledger_name}="$ledger"' in script
        assert script.count(marker) == 1
        environment = {
            "PATH": os.pathsep.join((str(tmp_path), "/usr/bin", "/bin")),
            "GITHUB_ACTIONS": "true",
            "RUNNER_TEMP": str(runner_temp),
            "SYNTHETIC_REAL_PYTHON": sys.executable,
            "SYNTHETIC_PYTEST_EXIT": "37",
            "SYNTHETIC_PROBE_FD9": "1",
            "SYNTHETIC_PYTEST_ANNOTATION": (
                "::error title=pytest failed::phase=call; "
                "nodeid=tests/unit/test_synthetic.py::test_failure"
            ),
            "UNRELATED_SYNTHETIC_SECRET": "synthetic-secret-marker",
        }
        failed = subprocess.run(  # noqa: S603 - checked-in workflow with synthetic Python only
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert failed.returncode == 37
        assert failed.stdout == (
            "::error title=pytest failed::phase=call; "
            "nodeid=tests/unit/test_synthetic.py::test_failure\n"
            "::error title=pytest failed::phase=process; exitstatus=37\n"
        )
        assert failed.stderr == ""
        assert "synthetic-secret-marker" not in failed.stdout
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        passed = subprocess.run(  # noqa: S603 - checked-in workflow with synthetic Python only
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={
                **environment,
                "SYNTHETIC_PYTEST_EXIT": "0",
                "SYNTHETIC_PYTEST_ANNOTATION": "",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert passed.returncode == 0
        assert passed.stdout == passed.stderr == ""
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        inconsistent = subprocess.run(  # noqa: S603 - synthetic Python shim
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={**environment, "SYNTHETIC_PYTEST_EXIT": "0"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert inconsistent.returncode == 1
        assert inconsistent.stdout == "::error title=pytest failed::phase=ledger; exitstatus=1\n"
        assert inconsistent.stderr == ""
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        not_actions = subprocess.run(  # noqa: S603 - checked-in workflow with synthetic Python only
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={key: value for key, value in environment.items() if key != "GITHUB_ACTIONS"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert not_actions.returncode == 1
        assert not_actions.stdout == not_actions.stderr == ""
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        tampered = subprocess.run(  # noqa: S603 - checked-in workflow with synthetic Python only
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={
                **environment,
                "SYNTHETIC_PYTEST_ANNOTATION": (
                    "::error title=pytest failed::phase=call; "
                    "nodeid=tests/unit/test_synthetic.py::test_first\n"
                    "::error title=pytest failed::phase=call; "
                    "nodeid=tests/unit/test_synthetic.py::test_bad;synthetic-secret-marker"
                ),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert tampered.returncode == 37
        assert tampered.stdout == (
            "::error title=pytest failed::phase=ledger; exitstatus=1\n"
            "::error title=pytest failed::phase=process; exitstatus=37\n"
        )
        assert "synthetic-secret-marker" not in tampered.stdout + tampered.stderr
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        nul_with_passing_pytest = subprocess.run(  # noqa: S603 - synthetic Python shim
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={
                **environment,
                "SYNTHETIC_PYTEST_EXIT": "0",
                "SYNTHETIC_PYTEST_NUL": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert nul_with_passing_pytest.returncode == 1
        assert nul_with_passing_pytest.stdout == (
            "::error title=pytest failed::phase=ledger; exitstatus=1\n"
        )
        assert nul_with_passing_pytest.stderr == ""
        assert "test_synthetic.py::test_failure" not in nul_with_passing_pytest.stdout
        assert "synthetic-secret-marker" not in nul_with_passing_pytest.stdout
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        unterminated = subprocess.run(  # noqa: S603 - checked-in workflow with synthetic Python only
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={
                **environment,
                "SYNTHETIC_PYTEST_UNTERMINATED": (
                    "::error title=pytest failed::phase=call; "
                    "nodeid=tests/unit/test_partial_synthetic-secret-marker"
                ),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert unterminated.returncode == 37
        assert unterminated.stdout == tampered.stdout
        assert unterminated.stderr == ""
        assert "test_synthetic.py::test_failure" not in unterminated.stdout
        assert "synthetic-secret-marker" not in unterminated.stdout
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        overflow = subprocess.run(  # noqa: S603 - checked-in workflow with synthetic Python only
            ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
            env={
                **environment,
                "SYNTHETIC_PYTEST_ANNOTATION": "\n".join(
                    "::error title=pytest failed::phase=call; "
                    f"nodeid=tests/unit/test_synthetic.py::test_{index}"
                    for index in range(11)
                ),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        assert overflow.returncode == 37
        assert overflow.stdout == tampered.stdout
        assert overflow.stderr == ""
        assert not list(runner_temp.glob("my-pa-fast-ledger.*"))

        for malformed_line in (
            "::error title=pytest failed::phase=call; nodeid=tests/" + "x" * 1100,
            "::error title=pytest failed::phase=call; nodeid=tests/test_é",
            "::error title=pytest failed::phase=call; nodeid=tests/test_%GG",
        ):
            malformed = subprocess.run(  # noqa: S603 - synthetic Python shim
                ["/bin/bash", "-e", "-o", "pipefail", "-c", script],
                env={**environment, "SYNTHETIC_PYTEST_ANNOTATION": malformed_line},
                capture_output=True,
                text=True,
                check=False,
            )
            assert malformed.returncode == 37
            assert malformed.stdout == tampered.stdout
            assert malformed.stderr == ""
            assert not list(runner_temp.glob("my-pa-fast-ledger.*"))


def test_session_start_and_finish_clear_queued_state_with_bounded_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    hook._GITHUB_ACTIONS_FAILURES.append(("stale-nodeid", "call"))
    hook._GITHUB_ACTIONS_FAILURE_KEYS.add(("stale-nodeid", "call"))

    _reset(hook)
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS

    runner_temp, ledger = _synthetic_ledger(tmp_path)
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("CI_PYTEST_FAILURE_LEDGER", str(ledger))
    for index in range(hook._GITHUB_ACTIONS_FAILURE_LIMIT + 3):
        hook._queue_github_actions_failure(f"tests/unit/test_example.py::test_case_{index}", "call")
    immediate = capsys.readouterr().out
    assert immediate.count("::error title=pytest failed::phase=call;") == 10
    assert ledger.read_text(encoding="utf-8") == immediate
    assert "test_case_0\n" in immediate
    assert "test_case_10\n" not in immediate
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    final = capsys.readouterr().out
    assert final.startswith(immediate)
    assert final.endswith(
        "::error title=pytest failed::phase=summary; additional_unique_failures=3\n"
    )
    assert final.count("::error title=pytest failed::phase=call;") == 10
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_fixture_teardown_discards_a_synthetic_queue_before_outer_sessionfinish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Immediate evidence survives even when fixture teardown clears the queue."""
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook._queue_github_actions_failure("tests/unit/test_nested.py::test_failure", "call")
    assert capsys.readouterr().out == (
        "::error title=pytest failed::phase=call; nodeid=tests/unit/test_nested.py::test_failure\n"
    )
    assert hook._GITHUB_ACTIONS_FAILURES
    assert hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_fixture_cleanup_leaves_no_annotation_for_outer_sessionfinish(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The preceding synthetic queue was cleared by the module fixture teardown."""
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=0)
    assert capsys.readouterr().out == ""


def test_immediate_and_final_annotations_escape_github_command_delimiters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook._queue_github_actions_failure(
        "tests/unit/test_example.py::test_case[%\r\nmarker]", "call%\r\n"
    )
    expected = (
        "::error title=pytest failed::phase=call%25%0D%0A; "
        "nodeid=tests/unit/test_example.py::test_case%5B%25%0D%0Amarker%5D\n"
    )
    assert capsys.readouterr().out == expected
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == expected


def test_deferred_annotation_never_renders_report_details_or_environment_payloads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ANNOTATION_TEST_UNRELATED_VALUE", "synthetic-environment-value")
    runner_temp, ledger = _synthetic_ledger(tmp_path)
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    monkeypatch.setenv("CI_PYTEST_FAILURE_LEDGER", str(ledger))
    report = SimpleNamespace(
        failed=True,
        when="call",
        nodeid="tests/unit/test_example.py::test_failure",
        longrepr="synthetic exception payload",
        capstdout="synthetic captured output",
        capstderr="synthetic captured error",
        user_properties=[("payload", "synthetic report payload")],
    )

    def hostile_os_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("patched os callable used by the ledger hook")

    with monkeypatch.context() as hostile:
        for name in ("open", "lstat", "fstat", "write", "close", "geteuid"):
            hostile.setattr(os, name, hostile_os_call)
        hook.pytest_runtest_logreport(report)
    immediate = capsys.readouterr().out
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    output = capsys.readouterr().out
    expected = (
        "::error title=pytest failed::phase=call; "
        + "nodeid=tests/unit/test_example.py::test_failure\n"
    )
    assert immediate == output == expected
    assert ledger.read_text(encoding="utf-8") == expected
    for forbidden in (
        "synthetic exception payload",
        "synthetic captured output",
        "synthetic captured error",
        "synthetic report payload",
        "synthetic-environment-value",
    ):
        assert forbidden not in output + ledger.read_text(encoding="utf-8")

    ledger.chmod(0o644)
    _reset(hook)
    hook.pytest_runtest_logreport(report)
    assert capsys.readouterr().out == expected
    assert ledger.read_text(encoding="utf-8") == expected

    ledger.chmod(0o600)
    ledger.parent.chmod(0o755)
    _reset(hook)
    hook.pytest_runtest_logreport(report)
    assert capsys.readouterr().out == expected
    assert ledger.read_text(encoding="utf-8") == expected

    ledger.parent.chmod(0o700)
    target = tmp_path / "kept-regular-ledger"
    ledger.rename(target)
    target.chmod(0o600)
    ledger.symlink_to(target)
    _reset(hook)
    hook.pytest_runtest_logreport(report)
    assert capsys.readouterr().out == expected
    assert target.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize(
    ("failed", "when", "skipped"),
    [(False, "setup", False), (False, "call", False), (False, "teardown", True)],
)
def test_successful_and_skipped_reports_remain_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: bool,
    when: str,
    skipped: bool,
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook.pytest_runtest_logreport(
        SimpleNamespace(
            failed=failed,
            skipped=skipped,
            when=when,
            nodeid="tests/unit/test_example.py::test_nonfailure",
        )
    )
    hook.pytest_collectreport(
        SimpleNamespace(
            failed=False,
            skipped=True,
            nodeid="tests/unit/test_collection_nonfailure.py",
        )
    )
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=0)

    assert capsys.readouterr().out == ""
