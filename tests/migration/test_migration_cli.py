"""The operator CLI, end to end against a disposable database.

The CLI is thin, but the wiring between it, the settings, the control plane, and
the loader is exactly what silently breaks, so it is exercised rather than
assumed. It is loaded from its file because `apps/` is not an importable
package.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, text

from conftest import build_source, prepare_target, synthetic_registry

ROOT = Path(__file__).resolve().parents[2]
CLI_PATH = ROOT / "apps" / "cli" / "migration.py"
REGISTRY = ROOT / "migrations" / "data" / "disposition_registry.json"

pytestmark = pytest.mark.database

ROWS = (("INSERT INTO widget_notes (note_id, body) VALUES (?, ?)", (1, "body")),)


@pytest.fixture(scope="module")
def cli() -> ModuleType:
    specification = importlib.util.spec_from_file_location("my_pa_migration_cli", CLI_PATH)
    if specification is None or specification.loader is None:  # pragma: no cover - import guard
        raise RuntimeError(f"cannot load {CLI_PATH}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_source(tmp_path / "synthetic.sqlite", ROWS)


def _run_id(output: str) -> str:
    for line in output.splitlines():
        if line.startswith("run_id"):
            return line.split()[1]
    raise AssertionError(f"no run_id in {output!r}")


def test_init_run_status_and_dry_run(
    cli: ModuleType,
    target: Engine,
    source: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prepare_target(target, source)
    registry = tmp_path / "registry.json"
    _write_registry(registry)

    assert cli.main(["init-run", "--source", str(source)]) == 0
    run_id = _run_id(capsys.readouterr().out)

    assert (
        cli.main(
            [
                "dry-run",
                "--run-id",
                run_id,
                "--source",
                str(source),
                "--registry",
                str(registry),
            ]
        )
        == 0
    )
    assert "dry run: nothing was committed" in capsys.readouterr().out

    assert (
        cli.main(
            [
                "load",
                "--run-id",
                run_id,
                "--source",
                str(source),
                "--registry",
                str(registry),
                "--table",
                "widget_notes",
            ]
        )
        == 0
    )
    assert "rows loaded 1" in capsys.readouterr().out

    assert cli.main(["status", "--run-id", run_id]) == 0
    status = capsys.readouterr().out
    assert "status      COMPLETED" in status
    assert "rows loaded 1" in status

    assert cli.main(["resume", "--run-id", run_id, "--source", str(source)]) == 0
    assert "nothing to resume" in capsys.readouterr().out

    with target.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM core.widget_notes")).scalar_one() == 1


def _write_registry(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "record_type": "SYNTHETIC",
                "entries": [
                    {
                        "legacy_object": entry.legacy_object,
                        "object_type": entry.object_type,
                        "target_schema": entry.target_schema,
                        "target_treatment": entry.target_treatment,
                        "planning_disposition": entry.planning_disposition,
                        "ordering_group": entry.ordering_group,
                    }
                    for entry in synthetic_registry().values()
                ],
            }
        ),
        encoding="utf-8",
    )
