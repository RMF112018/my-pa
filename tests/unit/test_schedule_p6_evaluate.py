"""P6 XER S7-5: the real-corpus evaluation script `ops/schedule/p6_evaluate.py` (FAST).

Contract `docs/architecture/schedule-xer-import-contract.md` section 14 (S7-5).
The script prints one canonical JSON object per run and never a value from a
file: unique marker strings are planted in every text field and every optional
field of 2 consecutive exports that parse, snapshot and run, and none may
appear in the output (as acceptance A7 of S7-1 for the profiler). It is
read-only and maps outcomes to exit codes 1 (a `fail` verdict or an
unexpected error, by type only), 0 and 2 (usage).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from my_pa.domain.schedule.p6 import P6_LIMITS
from my_pa.domain.schedule.p6.catalogue import ValueType, catalogue_field
from my_pa.domain.schedule.p6_import import P6_IMPORT_FIELDS
from tests.fixtures import schedule_p6_oracle as cases
from tests.fixtures import schedule_p6_xer as fx

ROOT: Final = Path(__file__).resolve().parents[2]
SCRIPT: Final = ROOT / "ops" / "schedule" / "p6_evaluate.py"


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("p6_evaluate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(paths: list[Path], module: ModuleType | None = None, *flags: str) -> tuple[int, str, str]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = (module or _script()).main([*flags, *(str(path) for path in paths)])
    return code, stdout.getvalue(), stderr.getvalue()


def _files(tmp_path: Path, *models: fx.Model | bytes) -> list[Path]:
    paths: list[Path] = []
    for index, item in enumerate(models, start=1):
        path = tmp_path / f"export{index}.xer"
        path.write_bytes(item if isinstance(item, bytes) else fx.encode(fx.layout(item).lines))
        paths.append(path)
    return paths


class _Markers:
    def __init__(self) -> None:
        self.planted: list[str] = []

    def next(self) -> str:
        marker = f"Zq{len(self.planted):05d}Mk"  # never shaped like a P6 vocabulary token
        self.planted.append(marker)
        return marker


_TEXT_TYPES: Final = frozenset({ValueType.TEXT, ValueType.NAME})


def _marked(markers: _Markers, *, every_value: bool) -> fx.Model:
    """Markers in every text/name value and every optional value (or in every value)."""
    model = cases.exact_full()
    model.header = [model.header[0], model.header[1], *(markers.next() for _ in model.header[2:])]
    for table in model.tables:
        tiers = dict(fx.field_tiers(table.name)) if table.name in fx.FIELDS else {}
        for row in table.rows:
            for name in table.fields:
                field = catalogue_field(table.name, name)
                text = field is not None and field.value_type in _TEXT_TYPES
                if every_value or text or tiers.get(name, "O") in {"O", "N"}:
                    row[name] = markers.next()
    return model


def test_a_planted_value_never_reaches_the_output(tmp_path: Path) -> None:
    markers = _Markers()
    first = _marked(markers, every_value=False)
    second = _marked(markers, every_value=False)
    # The same project (by GUID: the short names are markers too) and one change.
    second.table("PROJECT").rows[0]["guid"] = first.table("PROJECT").rows[0]["guid"]
    second.table("TASK").rows[0]["target_drtn_hr_cnt"] = "6"
    code, printed, errors = _run(_files(tmp_path, first, second))
    assert code == 0, errors
    document = json.loads(printed)
    export = document["exports"][0]
    assert export["verdict"] == "pass_with_findings"
    assert export["oracle"]["status"] == "compared"
    assert export["oracle"]["quantities"]["early_start"]["compared"] == 4
    assert document["pairs"][0]["status"] == "compared"
    assert document["pairs"][0]["delta"]["changes"] > 0
    assert len(markers.planted) > 500
    leaked = [marker for marker in markers.planted if marker in printed or marker in errors]
    assert not leaked, leaked[:5]


def test_a_planted_value_in_a_failing_export_is_not_shown(tmp_path: Path) -> None:
    markers = _Markers()
    code, printed, errors = _run(_files(tmp_path, _marked(markers, every_value=True)))
    assert code == 1
    assert json.loads(printed)["exports"][0]["verdict"] == "fail"
    assert not [marker for marker in markers.planted if marker in printed or marker in errors]


def _document(tmp_path: Path, *names: str) -> tuple[int, dict[str, Any]]:
    code, printed, _ = _run(_files(tmp_path, *(cases.build(name) for name in names)))
    return code, json.loads(printed)


def test_the_output_shape_on_a_consecutive_pair(tmp_path: Path) -> None:
    code, document = _document(tmp_path, "exact", "mismatch")
    assert code == 0
    assert document["schema"] == "p6-evaluation-v1"
    assert [item["position"] for item in document["exports"]] == [1, 2]
    export = document["exports"][0]
    assert set(export) == {
        "counts",
        "export_version_tested",
        "issue_counts",
        "oracle",
        "position",
        "snapshot",
        "verdict",
    }
    assert export["counts"] == {
        "activities": {"equal": True, "file": 4, "parsed": 4},
        "calendars": {"equal": True, "file": 2, "parsed": 2},
        "relationships": {"equal": True, "file": 3, "parsed": 3},
        "wbs": {"equal": True, "file": 4, "parsed": 4},
    }
    snapshot = export["snapshot"]
    assert snapshot["refusal"] is None
    assert snapshot["counts"]["tasks"] == 4
    assert snapshot["standard_calendar_horizon_exceeded"] == 0
    assert document["exports"][1]["oracle"]["quantities"]["early_finish"]["equal"] == 3
    (pair,) = document["pairs"]
    assert (pair["from"], pair["to"], pair["status"]) == (1, 2, "compared")
    assert pair["same_project"] is True
    # The planted early finish moved: early_finish and the derived finish.
    assert pair["delta"]["counts_by_kind"]["dates_changed"] == 2
    assert pair["delta"]["changes"] == 2


def test_a_history_of_3_reports_a_returning_activity(tmp_path: Path) -> None:
    with_it = cases.CASES["exact"]()
    with_it.table("TASK").rows.append(
        cases.task("3005", "SYN-2050", "8", ("2030-01-11 08:00", "2030-01-11 17:00"))
    )
    code, printed, _ = _run(_files(tmp_path, with_it, cases.build("exact"), with_it))
    assert code == 0
    pairs = json.loads(printed)["pairs"]
    assert pairs[0]["delta"]["counts_by_kind"]["removed"] == 1
    assert pairs[1]["delta"]["counts_by_kind"]["reintroduced"] == 1
    assert pairs[1]["delta"]["counts_by_kind"]["added"] == 0


def test_exports_of_different_projects_are_not_compared(tmp_path: Path) -> None:
    other = cases.CASES["exact"]()
    other.table("PROJECT").rows[0].update(proj_short_name="SYN-OTHER", guid=fx.guid("SynOther"))
    code, printed, _ = _run(_files(tmp_path, cases.build("exact"), other))
    assert code == 0
    (pair,) = json.loads(printed)["pairs"]
    assert pair == {
        "delta": None,
        "from": 1,
        "same_project": False,
        "status": "different_project",
        "to": 2,
    }


def test_assume_same_project_compares_a_renamed_copy(tmp_path: Path) -> None:
    other = cases.CASES["exact"]()
    other.table("PROJECT").rows[0].update(proj_short_name="SYN-OTHER", guid=fx.guid("SynOther"))
    paths = _files(tmp_path, cases.build("exact"), other)
    code, printed, _ = _run(paths, None, "--assume-same-project")
    assert code == 0
    (pair,) = json.loads(printed)["pairs"]
    assert pair["status"] == "compared"
    assert pair["same_project"] is False
    assert pair["delta"]["changes"] == 0


def test_a_fatal_export_exits_1_and_its_pair_is_not_compared(tmp_path: Path) -> None:
    paths = _files(tmp_path, cases.build("exact"), fx.build("missing_required_field").data)
    before = [(path.stat().st_mtime_ns, path.read_bytes()) for path in paths]
    code, printed, _ = _run(paths)
    assert code == 1
    document = json.loads(printed)
    failed = document["exports"][1]
    assert failed["verdict"] == "fail"
    assert failed["oracle"] is None
    assert failed["issue_counts"]["p6_required_field_missing"] == 1
    assert document["pairs"][0]["status"] == "parse_failed"
    assert [(path.stat().st_mtime_ns, path.read_bytes()) for path in paths] == before


def test_usage_errors_exit_2(tmp_path: Path) -> None:
    module = _script()
    with redirect_stderr(io.StringIO()):
        assert module.main([]) == 2
        assert module.main([str(tmp_path / "absent.xer")]) == 2
        assert module.main([str(tmp_path)]) == 2


def test_a_special_file_is_refused_without_opening_it(tmp_path: Path) -> None:
    fifo = tmp_path / "export.xer"
    os.mkfifo(fifo)  # opening it for reading would block: the type is checked first
    code, printed, errors = _run([fifo])
    assert (code, printed) == (2, "")
    assert errors.strip() == "p6_evaluate=refused not a readable regular file"


def test_at_most_the_cap_plus_1_byte_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _script()
    data = cases.build("exact")
    monkeypatch.setattr(module, "P6_LIMITS", dataclasses.replace(P6_LIMITS, file_bytes=len(data)))
    (path,) = _files(tmp_path, data)
    assert module._read(path) == data
    code, printed, _ = _run([path], module)
    assert code == 0
    assert json.loads(printed)["exports"][0]["oracle"]["status"] == "compared"
    # 1 byte over the cap: cap + 1 bytes are read and the export fails as a bound.
    path.write_bytes(data + b"\r\n")
    assert module._read(path) == (data + b"\r\n")[: len(data) + 1]
    code, printed, _ = _run([path], module)
    assert code == 1
    failed = json.loads(printed)["exports"][0]
    assert failed["verdict"] == "fail"
    assert failed["issue_counts"] == {"p6_bound_exceeded": 1}


def test_an_unexpected_error_prints_its_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _script()

    def explode(_: object) -> None:
        raise ValueError("Zq77777Mk")

    monkeypatch.setattr(module, "oracle_report", explode)
    code, printed, errors = _run(_files(tmp_path, cases.build("exact")), module)
    assert code == 1
    assert printed == ""
    assert errors.strip() == "p6_evaluate=error ValueError"


RUNBOOK: Final = ROOT / "ops" / "runbooks" / "cpm-workbench.md"


def test_the_runbook_import_example_is_a_valid_request_shape() -> None:
    """Runbook section 10.5: the worked `import_p6` input names the request's fields."""
    text = RUNBOOK.read_text(encoding="utf-8")
    section = text[text.index("### 10.5 How a client imports") : text.index("### 10.6 Statuses")]
    block = section.split("```json", 1)[1].split("```", 1)[0]
    example = json.loads(block)
    assert set(example) <= P6_IMPORT_FIELDS
    assert set(example) >= {
        "project_id",
        "workspace_id",
        "path",
        "expected_version",
        "expected_sha256",
        "format",
        "idempotency_key",
    }
    assert sum(key in example for key in ("series_id", "series_name", "series_auto")) == 1
    assert example["format"] == "p6_xer"
    assert '"include_sha256": true' in section
    assert "`accept_project_identity_change`" in section
