"""Schedule Scenarios S6-3 package I10-A: the plane's public scope (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` sections 7, 15.8,
15.14 and 15.16 (by AST, by import and by driving `apps/worker.py`):

* OD-08: no Program reporting module reaches a plane module or table;
* the composition root (`bootstrap/gateway.py`) is the only module -- with
  `apps/worker.py` reaching the jobs module -- that imports the plane
  persistence; the application reaches it through injected ports;
* the S5 read service and delta still derive no baseline;
* the worker binds the series-match hook's effective-plane bit to both
  switches (it replaces S6-2's `test_worker_passes_no_effective_plane`);
* the S6-1/S6-2 plane write sets equal their `Capability` members.

The manifest's lineage pin is package I10-B's. Each detector is run over a
planted violation as its own control.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from tests.architecture.test_cpm_workbench_worker_scope import test_no_baseline_is_derived

from my_pa.domain.identity.operation import Capability, is_operator_only, is_write_capability
from my_pa.domain.schedule.plane import (
    PLANE_CLIENT_WRITE_CAPABILITIES,
    PLANE_OPERATOR_WRITE_CAPABILITIES,
    PLANE_WRITE_CAPABILITIES,
)
from my_pa.infrastructure.jobs.schedule import process_schedule_publication

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

#: Section 7: the Program reporting surfaces OD-08 keeps scenario data out of.
PROGRAM_SURFACES: Final = (
    *sorted((PACKAGE / "application").glob("program_*.py")),
    *sorted((PACKAGE / "domain" / "program").rglob("*.py")),
    PACKAGE / "contracts" / "v1" / "programs.py",
)
#: Every module that holds plane data or plane behaviour.
PLANE_MODULES: Final = (
    "my_pa.application.schedule_scenarios",
    "my_pa.infrastructure.persistence.schedule_scenarios",
    "my_pa.infrastructure.persistence.schedule_cpm_lease",
    "my_pa.infrastructure.persistence.schedule_plane_codec",
    "my_pa.domain.schedule.scenario",
    "my_pa.domain.schedule.plane",
    "my_pa.domain.schedule.baselines",
)
#: The 11 plane tables (section 14.3).
PLANE_TABLES: Final = frozenset(
    {
        "schedule_intake_series",
        "schedule_series_match_decisions",
        "schedule_baselines",
        "schedule_baseline_events",
        "schedule_governing_events",
        "schedule_scenarios",
        "schedule_scenario_versions",
        "schedule_cpm_runs",
        "schedule_scenario_outputs",
        "schedule_scenario_write_requests",
        "schedule_scenario_write_refusals",
    }
)
#: Section 15.14: the plane persistence the application never imports.
PLANE_PERSISTENCE: Final = (
    "my_pa.infrastructure.persistence.schedule_scenarios",
    "my_pa.infrastructure.persistence.schedule_cpm_lease",
    "my_pa.infrastructure.persistence.schedule_plane_codec",
)
#: The 2 modules allowed to import it (the worker reaches it through the jobs module).
COMPOSITION_ROOT: Final = frozenset({"src/my_pa/bootstrap/gateway.py"})
SURFACES: Final = (
    PACKAGE / "application",
    PACKAGE / "adapters",
    PACKAGE / "bootstrap",
    PACKAGE / "contracts",
    PACKAGE / "domain",
    ROOT / "apps",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _reaches(tree: ast.AST, modules: tuple[str, ...]) -> list[str]:
    return sorted(
        name
        for name in _imported(tree)
        if any(name == module or name.startswith(module + ".") for module in modules)
    )


def _names_a_plane_table(tree: ast.AST) -> list[str]:
    found = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    found |= {
        str(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    return sorted(found & PLANE_TABLES)


def _od08_violations(tree: ast.AST) -> list[str]:
    return _reaches(tree, PLANE_MODULES) + _names_a_plane_table(tree)


def test_scenario_data_reaches_no_program_surface() -> None:
    """OD-08 (section 7): no Program module imports a plane module or names a plane table."""
    assert len(PROGRAM_SURFACES) >= 3
    reaching = {
        str(path.relative_to(ROOT)): found
        for path in PROGRAM_SURFACES
        if (found := _od08_violations(_tree(path)))
    }
    assert reaching == {}, reaching
    planted = ast.parse("from my_pa.application import schedule_scenarios\n")
    assert _od08_violations(planted) == ["my_pa.application.schedule_scenarios"]
    planted_table = ast.parse("rows = select(schedule_cpm_runs)\n")
    assert _od08_violations(planted_table) == ["schedule_cpm_runs"]


def test_only_the_composition_root_imports_the_plane() -> None:
    """Section 15.14: the application reaches the plane persistence through ports only."""
    reaching = {
        str(path.relative_to(ROOT)): found
        for surface in SURFACES
        for path in sorted(surface.rglob("*.py"))
        if (found := _reaches(_tree(path), PLANE_PERSISTENCE))
    }
    assert set(reaching) == COMPOSITION_ROOT, reaching
    planted = ast.parse(
        "from my_pa.infrastructure.persistence.schedule_scenarios import SqlScenarioRepository\n"
    )
    assert _reaches(planted, PLANE_PERSISTENCE)
    # The worker reaches the jobs module, never the plane persistence directly.
    worker = _tree(ROOT / "apps" / "worker.py")
    assert "my_pa.infrastructure.jobs.schedule" in _imported(worker)
    assert not _reaches(worker, PLANE_PERSISTENCE)


def test_the_s5_read_service_still_derives_no_baseline() -> None:
    """Section 15.9: the plane gates key on `request.approval`, never a baseline literal."""
    test_no_baseline_is_derived()


class _BoundError(Exception):
    """Raised by the captured `functools.partial`: the handler is bound."""

    def __init__(self, function: object, keywords: dict[str, Any]) -> None:
        super().__init__("bound")
        self.function = function
        self.keywords = keywords


def _bound_handler(
    monkeypatch: pytest.MonkeyPatch, *, schedule: bool, scenarios: bool | None
) -> _BoundError | None:
    """Drive `apps/worker.py run --plane schedule` until the handler is bound."""
    from apps import worker as worker_app

    for key in [key for key in os.environ if key.startswith("MY_PA_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://someone@db.invalid:5432/x")
    monkeypatch.setenv("MY_PA_SCHEDULE_ENABLED", "true" if schedule else "false")
    if scenarios is not None:
        monkeypatch.setenv("MY_PA_SCHEDULE_SCENARIOS_ENABLED", "true" if scenarios else "false")
    monkeypatch.setattr(worker_app, "create_database_engine", lambda *_a, **_k: object())

    def partial(function: object, /, **keywords: Any) -> object:  # noqa: ANN401
        raise _BoundError(function, keywords)

    monkeypatch.setattr(worker_app, "functools", SimpleNamespace(partial=partial))

    def unbound(*_args: object, **_kwargs: object) -> str:
        raise _UnboundError

    monkeypatch.setattr(worker_app, "issue_worker_owner", unbound)
    try:
        worker_app.main(["run", "--plane", "schedule", "--once"])
    except _BoundError as bound:
        return bound
    except _UnboundError:
        return None
    return None


class _UnboundError(Exception):
    """The run went past the binding point without binding the handler."""


@pytest.mark.parametrize(
    ("scenarios", "effective"),
    [(None, False), (False, False), (True, True)],
    ids=["scenarios_unset", "scenarios_off", "scenarios_on"],
)
def test_worker_passes_the_effective_plane(
    monkeypatch: pytest.MonkeyPatch, scenarios: bool | None, effective: bool
) -> None:
    """Section 15.8 (S6-2-D12): the hook's bit is both switches, bound for the schedule plane."""
    bound = _bound_handler(monkeypatch, schedule=True, scenarios=scenarios)
    assert bound is not None, "the schedule plane's handler was not bound"
    assert bound.function is process_schedule_publication
    assert bound.keywords == {"scenario_plane_effective": effective}


def test_the_scenario_switch_alone_never_starts_a_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The plane refusal `plane schedule disabled` is unchanged by the scenario switch."""
    assert _bound_handler(monkeypatch, schedule=False, scenarios=True) is None
    assert capsys.readouterr().out == "plane schedule disabled\n"


def test_plane_write_sets_equal_their_capability_members() -> None:
    """Section 15.3: S6-3 pins the S6-1/S6-2 plane sets to the public names."""
    values = {member.value for member in Capability}
    assert values >= PLANE_WRITE_CAPABILITIES
    operator = {member.value for member in Capability if member.value in PLANE_WRITE_CAPABILITIES}
    assert {name for name in operator if is_operator_only(Capability(name))} == set(
        PLANE_OPERATOR_WRITE_CAPABILITIES
    )
    assert {name for name in operator if not is_operator_only(Capability(name))} == set(
        PLANE_CLIENT_WRITE_CAPABILITIES
    )
    assert all(is_write_capability(Capability(name)) for name in PLANE_WRITE_CAPABILITIES)
