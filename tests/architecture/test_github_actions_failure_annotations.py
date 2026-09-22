"""GitHub Actions failure annotations remain minimal and failure-safe."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "tests" / "conftest.py"


def _hook_module() -> ModuleType:
    for module in sys.modules.values():
        path = getattr(module, "__file__", None)
        if path is not None and Path(path).resolve() == HOOK_PATH:
            return module
    raise AssertionError("pytest did not load the root annotation hook")


@pytest.mark.parametrize("value", [None, "", "false", "TRUE", "1"])
def test_annotation_hook_is_silent_off_github_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], value: str | None
) -> None:
    hook = _hook_module()
    if value is None:
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    else:
        monkeypatch.setenv("GITHUB_ACTIONS", value)

    hook._annotate_github_actions_failure("tests/unit/test_example.py::test_case", "call")

    assert capsys.readouterr().out == ""


def test_annotation_hook_escapes_the_github_command_delimiters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    nodeid = "tests/unit/test_example.py::test_case[%\r\nmarker]"

    hook._annotate_github_actions_failure(nodeid, "call")

    assert capsys.readouterr().out == (
        "::error title=pytest failed::phase=call; "
        "nodeid=tests/unit/test_example.py::test_case[%25%0D%0Amarker]\n"
    )


@pytest.mark.parametrize("phase", ["setup", "call", "teardown"])
def test_failed_runtime_reports_emit_only_the_phase_and_nodeid(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], phase: str
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    report = SimpleNamespace(
        failed=True,
        when=phase,
        nodeid="tests/unit/test_example.py::test_failure",
    )

    hook.pytest_runtest_logreport(report)

    assert capsys.readouterr().out == (
        f"::error title=pytest failed::phase={phase}; "
        "nodeid=tests/unit/test_example.py::test_failure\n"
    )


def test_failed_collection_reports_use_the_collection_phase(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook.pytest_collectreport(SimpleNamespace(failed=True, nodeid="tests/unit/test_example.py"))

    assert capsys.readouterr().out == (
        "::error title=pytest failed::phase=collection; nodeid=tests/unit/test_example.py\n"
    )


def test_annotation_hook_never_renders_failure_details_or_environment_payloads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("ANNOTATION_TEST_UNRELATED_VALUE", "synthetic-environment-value")
    report = SimpleNamespace(
        failed=True,
        when="call",
        nodeid="tests/unit/test_example.py::test_failure",
        longrepr="synthetic exception payload",
        capstdout="synthetic captured output",
        capstderr="synthetic captured error",
        user_properties=[("payload", "synthetic report payload")],
    )

    hook.pytest_runtest_logreport(report)

    output = capsys.readouterr().out
    expected = (
        "::error title=pytest failed::phase=call; "
        + "nodeid=tests/unit/test_example.py::test_failure\n"
    )
    assert output == expected
    for forbidden in (
        "synthetic exception payload",
        "synthetic captured output",
        "synthetic captured error",
        "synthetic report payload",
        "synthetic-environment-value",
    ):
        assert forbidden not in output


@pytest.mark.parametrize(
    ("failed", "when"),
    [(False, "setup"), (False, "call"), (False, "teardown"), (True, "logreport")],
)
def test_successful_skipped_and_nonruntime_reports_remain_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed: bool,
    when: str,
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook.pytest_runtest_logreport(
        SimpleNamespace(
            failed=failed,
            skipped=not failed,
            when=when,
            nodeid="tests/unit/test_example.py::test_nonfailure",
        )
    )
    hook.pytest_collectreport(
        SimpleNamespace(
            failed=False,
            skipped=True,
            nodeid="tests/unit/test_example.py",
        )
    )

    assert capsys.readouterr().out == ""
