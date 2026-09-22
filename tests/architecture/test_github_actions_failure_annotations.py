"""GitHub Actions failure annotations remain deferred and failure-safe."""

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


def _reset(hook: ModuleType) -> None:
    hook.pytest_sessionstart(SimpleNamespace())


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


def test_failed_reports_queue_until_sessionfinish_then_flush_once(
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

    assert capsys.readouterr().out == ""
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == (
        "::error title=pytest failed::phase=setup; "
        "nodeid=tests/unit/test_example.py::test_setup\n"
        "::error title=pytest failed::phase=call; "
        "nodeid=tests/unit/test_example.py::test_call\n"
        "::error title=pytest failed::phase=teardown; "
        "nodeid=tests/unit/test_example.py::test_teardown\n"
        "::error title=pytest failed::phase=collection; "
        "nodeid=tests/unit/test_collection_failure.py\n"
    )
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_duplicate_failed_reports_emit_one_deferred_annotation(
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
    assert capsys.readouterr().out == ""
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == (
        "::error title=pytest failed::phase=call; "
        "nodeid=tests/unit/test_example.py::test_duplicate\n"
    )


def test_session_failure_without_reports_emits_numeric_status_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=2)

    assert capsys.readouterr().out == "::error title=pytest failed::phase=session; exitstatus=2\n"
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_session_start_and_finish_clear_queued_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    hook._GITHUB_ACTIONS_FAILURES.append(("stale-nodeid", "call"))
    hook._GITHUB_ACTIONS_FAILURE_KEYS.add(("stale-nodeid", "call"))

    _reset(hook)
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS

    hook._queue_github_actions_failure("tests/unit/test_example.py::test_case", "call")
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    expected = (
        "::error title=pytest failed::phase=call; "
        + "nodeid=tests/unit/test_example.py::test_case\n"
    )
    assert capsys.readouterr().out == expected
    assert not hook._GITHUB_ACTIONS_FAILURES
    assert not hook._GITHUB_ACTIONS_FAILURE_KEYS


def test_deferred_annotation_escapes_github_command_delimiters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    _reset(hook)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    hook._queue_github_actions_failure(
        "tests/unit/test_example.py::test_case[%\r\nmarker]", "call%\r\n"
    )
    assert capsys.readouterr().out == ""
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

    assert capsys.readouterr().out == (
        "::error title=pytest failed::phase=call%25%0D%0A; "
        "nodeid=tests/unit/test_example.py::test_case[%25%0D%0Amarker]\n"
    )


def test_deferred_annotation_never_renders_report_details_or_environment_payloads(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hook = _hook_module()
    _reset(hook)
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
    assert capsys.readouterr().out == ""
    hook.pytest_sessionfinish(SimpleNamespace(), exitstatus=1)

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
