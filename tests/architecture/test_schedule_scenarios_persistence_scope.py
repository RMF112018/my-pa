"""Schedule Scenarios S6-2: the plane stays where it was put.

Contract `docs/architecture/schedule-scenarios-contract.md` sections 9.2,
14.8, 14.9 and 14.11.2 (FAST, by AST and by import):

* (the S6-2 pins that kept the plane names private were replaced in lockstep
  by S6-3, R3-28: the capabilities, purposes, composition-root rule and worker
  wiring by package I10-A in `test_schedule_scenarios_capability_scope.py`, the
  lineage families, relations and generation by package I10-B in
  `tests/unit/test_schedule_lineage_vocabulary.py`);
* `ScenarioUnitOfWork` is not on the general `UnitOfWork`;
* the plane modules write no S5 table except through the S5 admission;
* the pre-deploy module's `QUARANTINED` registration cannot widen (RR2-F01).

Each detector is run over a planted violation as its own control.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from my_pa.contracts import ports

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
PERSISTENCE: Final = PACKAGE / "infrastructure" / "persistence"
PLANE_MODULES: Final = (
    PERSISTENCE / "schedule_scenarios.py",
    PERSISTENCE / "schedule_cpm_lease.py",
    PERSISTENCE / "schedule_plane_codec.py",
)
PREDEPLOY: Final = PACKAGE / "infrastructure" / "database" / "schedule_scenarios_predeploy.py"
TABLES_MODULE: Final = "my_pa.infrastructure.persistence.tables"
#: The plane modules nothing outside infrastructure (and the ports) may reach in S6-2.
PLANE_IMPORTS: Final = (
    "my_pa.infrastructure.persistence.schedule_scenarios",
    "my_pa.infrastructure.persistence.schedule_cpm_lease",
    "my_pa.infrastructure.persistence.schedule_plane_codec",
    "my_pa.domain.schedule.plane",
)
#: The surfaces S6-3 owns: transports, application services, composition and apps.
PUBLIC_SURFACES: Final = (
    PACKAGE / "application",
    PACKAGE / "adapters",
    PACKAGE / "bootstrap",
    ROOT / "apps",
)
PLANE_NAME_PREFIXES: Final = ("schedule_scenario", "schedule_cpm_run", "schedule_baseline")
#: The 7 S5 tables; a plane module reaches them through the S5 repository only.
S5_TABLES: Final = frozenset(
    {
        "schedule_series",
        "schedule_publications",
        "schedule_activities",
        "schedule_jobs",
        "schedule_parser_runs",
        "schedule_rows",
        "schedule_import_issues",
    }
)
_WRITERS: Final = frozenset({"insert", "pg_insert", "update", "delete"})


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


def _reaches_the_plane(tree: ast.AST) -> list[str]:
    return sorted(
        name
        for name in _imported(tree)
        if any(name == plane or name.startswith(plane + ".") for plane in PLANE_IMPORTS)
    )


def _class_mentions(tree: ast.Module, class_name: str, token: str) -> bool:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return token in ast.unparse(node)
    raise AssertionError(f"{class_name} is not defined")


def test_scenario_unit_of_work_is_not_on_the_general_unit_of_work() -> None:
    """The plane unit of work stands alone (section 14.8.1).

    S6-3 composes it as a factory of its own (section 15.8): `ApplicationService`
    and the composition root name it, never the general `UnitOfWork`.
    """
    assert not issubclass(ports.ScenarioUnitOfWork, ports.UnitOfWork)
    assert not issubclass(ports.UnitOfWork, ports.ScenarioUnitOfWork)
    assert not hasattr(ports.UnitOfWork, "scenarios")
    assert not _class_mentions(_tree(PACKAGE / "contracts" / "ports.py"), "UnitOfWork", "Scenario")
    source = (PERSISTENCE / "unit_of_work.py").read_text(encoding="utf-8")
    assert "ScenarioUnitOfWork" not in source
    assert "ScenarioRepository" not in source
    planted = ast.parse(
        "class UnitOfWork:\n    @property\n    def scenarios(self) -> ScenarioRepository: ...\n"
    )
    assert _class_mentions(planted, "UnitOfWork", "Scenario")


def _s5_writes(tree: ast.AST) -> list[str]:
    """Every `insert`/`pg_insert`/`update`/`delete` call whose first argument is an S5 table."""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else None
        )
        target = node.args[0]
        if name in _WRITERS and isinstance(target, ast.Name) and target.id in S5_TABLES:
            found.append(f"{name}({target.id})")
    return found


def test_plane_persistence_writes_no_s5_table_except_through_admission() -> None:
    """The plane reads S5 rows; it writes S5 tables only through `admit_publication`."""
    for path in PLANE_MODULES:
        tree = _tree(path)
        assert _s5_writes(tree) == [], path.name
        imported = _imported(tree)
        assert "my_pa.infrastructure.persistence.jobs.enqueue_job" not in imported, path.name
        assert "sqlalchemy.text" not in imported, path.name
    plane = _tree(PERSISTENCE / "schedule_scenarios.py")
    calls = {ast.unparse(node.func) for node in ast.walk(plane) if isinstance(node, ast.Call)}
    assert "self._schedules().admit_publication" in calls
    planted = ast.parse("statement = update(schedule_publications).values(status='failed')\n")
    assert _s5_writes(planted) == ["update(schedule_publications)"]


def _probe_violations(tree: ast.Module) -> list[str]:
    """RR2-F01: exactly `schedule_publications` is imported, and used only in the probe."""
    wrong: list[str] = []
    from_tables = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == TABLES_MODULE
        for alias in node.names
    }
    if from_tables != {"schedule_publications"}:
        wrong.append(f"imports {sorted(from_tables)} from the declarations")
    probe = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        and "RETIRED_ROLE_PROBE"
        in {
            target.id
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
    ]
    if len(probe) != 1:
        wrong.append("RETIRED_ROLE_PROBE is not assigned exactly once")
    inside = {id(node) for assignment in probe for node in ast.walk(assignment)}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in from_tables and id(node) not in inside:
            wrong.append(f"line {node.lineno} names {node.id} outside RETIRED_ROLE_PROBE")
    sqlalchemy_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy")
        for alias in node.names
    }
    if sqlalchemy_names & {"table", "column", "Table", "MetaData"}:
        wrong.append("declares a table ad hoc")
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if (
                "knowledge.schedule_publications" in lowered
                or "from schedule_publications" in lowered
            ):
                wrong.append(f"line {node.lineno} reads schedule_publications in raw SQL")
    return wrong


def test_predeploy_module_touches_only_the_retired_role_probe() -> None:
    """RR2-F01: the module's `QUARANTINED` registration is pinned to the one probe."""
    assert _probe_violations(_tree(PREDEPLOY)) == []
    # The controls: each widening the registration must not admit is seen.
    source = PREDEPLOY.read_text(encoding="utf-8")
    declared = "from my_pa.infrastructure.persistence.tables import schedule_publications"
    second_import = source.replace(declared, declared + ", schedule_series")
    assert second_import != source
    assert _probe_violations(ast.parse(second_import))
    outside = source + "\n_STATUS = schedule_publications.c.status\n"
    assert _probe_violations(ast.parse(outside))
    ad_hoc = source + "\nfrom sqlalchemy import table\n"
    assert _probe_violations(ast.parse(ad_hoc))
    qualified = "knowledge." + "schedule_publications"
    raw = source + f"\n_RAW = {qualified!r}\n"  # a raw statement naming the table
    assert _probe_violations(ast.parse(raw))
