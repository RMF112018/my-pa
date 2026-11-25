"""S7-1 acceptance A7 and the conformance script (contract section 12) (FAST).

The profiler's output never contains a value: unique marker strings are
planted in every value of a fixture (and in the `ERMHDR` metadata) and none
may appear in the report, whether the parse fails or completes. The script
`ops/schedule/p6_export_profile.py` is read-only and maps verdicts to exit
codes 1 (fail), 0 (pass, pass with findings) and 2 (usage).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from my_pa.domain.schedule.p6 import export_profile
from tests.fixtures import schedule_p6_xer as fixtures

ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = ROOT / "ops" / "schedule" / "p6_export_profile.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p6_export_profile", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Markers:
    def __init__(self) -> None:
        self.planted: list[str] = []

    def next(self) -> str:
        # No underscore: never shaped like a P6 vocabulary token, so the one
        # deliberate disclosure (unknown enum tokens) cannot apply to it.
        marker = f"Zq{len(self.planted):05d}Mk"
        self.planted.append(marker)
        return marker


def _marked_model(markers: _Markers, *, every_value: bool) -> fixtures.Model:
    model = fixtures.base_model("full")
    model.header = [model.header[0], model.header[1], *(markers.next() for _ in model.header[2:])]
    model.tables.append(fixtures.Table("SYNEXTRA", ["syn_note"], [{"syn_note": ""}]))
    model.table("TASK").fields.append("syn_extra_field")
    for table in model.tables:
        tiers = dict(fixtures.field_tiers(table.name)) if table.name in fixtures.FIELDS else {}
        for row in table.rows:
            for name in table.fields:
                if every_value or tiers.get(name, "O") in {"O", "N"}:
                    row[name] = markers.next()
    return model


def _report_text(data: bytes) -> str:
    return json.dumps(export_profile(data), sort_keys=True)


@pytest.mark.parametrize("every_value", [True, False])
def test_profile_output_never_contains_a_planted_value(every_value: bool, tmp_path: Path) -> None:
    markers = _Markers()
    data = fixtures.encode(fixtures.layout(_marked_model(markers, every_value=every_value)).lines)
    report = export_profile(data)
    assert report["verdict"] == ("fail" if every_value else "pass_with_findings")
    text = json.dumps(report, sort_keys=True)
    assert "task_code" in text  # the report is real: names and stats are there
    path = tmp_path / "marked.xer"
    path.write_bytes(data)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        _script().main([str(path)])
    printed = stdout.getvalue()
    leaked = [marker for marker in markers.planted if marker in text or marker in printed]
    assert len(markers.planted) > 300
    assert not leaked, leaked[:5]


def test_a_marker_in_the_version_or_a_bad_name_is_not_shown() -> None:
    model = fixtures.base_model("standard")
    model.header[1] = "Zq99999Mk"
    assert "Zq99999Mk" not in _report_text(fixtures.encode(fixtures.layout(model).lines))
    model = fixtures.base_model("standard")
    model.table("TASK").fields.append("Zq-88888-Mk")
    report = _report_text(fixtures.encode(fixtures.layout(model).lines))
    assert "88888" not in report
    assert "p6_unknown_field_unnamed" in report


@pytest.mark.parametrize(
    ("name", "code"),
    [
        ("no_optional_tables", 0),
        ("unknown_table", 0),
        ("missing_required_field", 1),
        ("over_length_tolerated", 1),
    ],
)
def test_script_exit_codes_follow_the_verdict(name: str, code: int, tmp_path: Path) -> None:
    case = fixtures.build(name)
    path = tmp_path / "export.xer"
    path.write_bytes(case.data)
    before = (path.stat().st_mtime_ns, path.read_bytes())
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        assert _script().main([str(path)]) == code
    assert json.loads(stdout.getvalue())["verdict"] == case.truth.verdict
    assert (path.stat().st_mtime_ns, path.read_bytes()) == before


def test_script_usage_errors_exit_2(tmp_path: Path) -> None:
    module = _script()
    assert module.main([str(tmp_path / "absent.xer")]) == 2
    assert module.main([str(tmp_path)]) == 2
    if hasattr(os, "mkfifo"):
        fifo = tmp_path / "pipe.xer"
        os.mkfifo(fifo)
        assert module.main([str(fifo)]) == 2
    with redirect_stdout(io.StringIO()):
        assert module.main(["--help"]) == 0
    assert module.main([]) == 2


def test_script_reads_at_most_the_cap_plus_one(tmp_path: Path) -> None:
    data, _ = fixtures.cap_case("file_bytes", past=True)
    path = tmp_path / "large.xer"
    path.write_bytes(data + b"z" * 1024)
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        assert _script().main([str(path)]) == 1
    report = json.loads(stdout.getvalue())
    assert report["issues"][0]["bound"] == "file_bytes"


def test_script_runs_from_the_repository_root(tmp_path: Path) -> None:
    path = tmp_path / "export.xer"
    path.write_bytes(fixtures.build("version_8_4").data)
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, str(SCRIPT), str(path)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert (report["verdict"], report["export_version_tested"]) == ("pass_with_findings", False)
