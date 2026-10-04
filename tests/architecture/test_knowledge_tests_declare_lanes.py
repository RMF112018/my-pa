"""Every planned KLP test module runs in a real CI lane (KLP-WP-01).

AC-081, AC-127, AC-144. The R6 matrix records, for every planned test module,
the markers its nodes declare and the CI jobs that therefore run it
(`work_packages[*].test_lanes`). This lint derives those jobs independently,
from repository truth, and requires the two to agree:

- the marker vocabulary is `[tool.pytest.ini_options] markers` in
  `pyproject.toml` (with `--strict-markers`, so no other marker can exist);
- the effective markers of a node follow the auto-marking in
  `tests/db/fixtures.py` (`pytest_collection_modifyitems`), restated below and
  pinned against that file's text;
- each job's selection is the literal `python -m pytest -m <expression>` in
  `.github/workflows/repository-checks.yml`, parsed and evaluated here; job names
  are `repository-checks / <job id>` and the `name:` of each job in
  `frontend-quality.yml`.

It is written so later WPs need no edit: as each planned module appears on disk
its declared markers are checked against its lane automatically, and a module
whose markers no CI job selects (`evaluation`, `connector`, `network`, `slow`)
can only back an AC that is commissioning evidence.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any, Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
MATRIX_PATH: Final = ROOT / "tests" / "architecture" / "klp_implementation_matrix_r6.json"
REPOSITORY_CHECKS: Final = ROOT / ".github" / "workflows" / "repository-checks.yml"
FRONTEND_QUALITY: Final = ROOT / ".github" / "workflows" / "frontend-quality.yml"
FIXTURES: Final = ROOT / "tests" / "db" / "fixtures.py"

#: The repository-checks jobs that are pytest lanes (the others are web-security
#: and the database-tier aggregator, neither of which runs pytest).
PYTEST_JOBS: Final = frozenset(
    {
        "validate",
        "dependency-floor",
        "database-current-head",
        "database-recovery",
        "migration-empty-to-head",
        "migration-edge",
        "database-e2e",
    }
)
_NARROW: Final = frozenset(
    {
        "database_clone",
        "database_transactional",
        "recovery",
        "e2e",
        "migration_edge",
        "migration_empty_to_head",
        "migration_historical",
        "migration",
    }
)
_MIGRATION_MARKERS: Final = frozenset(
    {"migration", "migration_edge", "migration_empty_to_head", "migration_historical"}
)


# --- Repository truth -----------------------------------------------------------


@cache
def _matrix() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return loaded


@cache
def declared_markers() -> frozenset[str]:
    """The strict marker vocabulary from `pyproject.toml`."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    entries: list[str] = config["tool"]["pytest"]["ini_options"]["markers"]
    return frozenset(entry.split(":", 1)[0].strip() for entry in entries)


def effective_markers(path: str, declared: frozenset[str]) -> frozenset[str]:
    """Restatement of `tests/db/fixtures.py::pytest_collection_modifyitems`."""
    names = set(declared)
    slashed = f"/{path}"
    if path.endswith("test_head_round_trip.py"):
        names.add("migration_empty_to_head")
    elif "/tests/migration/" in slashed:
        if "database" in names and not names & {
            "migration",
            "migration_edge",
            "migration_empty_to_head",
        }:
            names.add("migration")
    elif path.endswith("_migration.py") or path.endswith(
        "test_every_revision_denotes_one_schema.py"
    ):
        if not names & _MIGRATION_MARKERS:
            names.add("migration_edge")
    elif "database" in names and not names & _NARROW:
        names.add("database_clone")
    return frozenset(names)


def _job_blocks(text: str) -> dict[str, str]:
    """Top-level job id -> the text of its block."""
    body = text[text.index("\njobs:\n") :]
    matches = list(re.finditer(r"^  ([A-Za-z0-9_-]+):\s*$", body, flags=re.MULTILINE))
    blocks: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        blocks[match.group(1)] = body[match.end() : end]
    return blocks


@cache
def repository_jobs() -> dict[str, str]:
    """`repository-checks / <id>` -> that job's block text."""
    workflow = re.search(r"^name:\s*(\S+)", REPOSITORY_CHECKS.read_text(encoding="utf-8"), re.M)
    assert workflow is not None
    prefix = workflow.group(1)
    blocks = _job_blocks(REPOSITORY_CHECKS.read_text(encoding="utf-8"))
    return {f"{prefix} / {job}": block for job, block in blocks.items()}


@cache
def frontend_jobs() -> frozenset[str]:
    names = set()
    for block in _job_blocks(FRONTEND_QUALITY.read_text(encoding="utf-8")).values():
        named = re.search(r"^    name:\s*(.+?)\s*$", block, flags=re.MULTILINE)
        if named:
            names.add(named.group(1))
    return frozenset(names)


def all_job_names() -> frozenset[str]:
    return frozenset(repository_jobs()) | frontend_jobs()


@cache
def job_selectors() -> dict[str, str]:
    """Job name -> its pytest `-m` expression, for every pytest lane."""
    selectors: dict[str, str] = {}
    for name, block in repository_jobs().items():
        flat = " ".join(block.split())
        match = re.search(r'python -m pytest -m (?:"([^"]+)"|([a-z0-9_]+))', flat)
        if match:
            selectors[name] = match.group(1) or match.group(2)
    return selectors


@cache
def aggregator_needs() -> dict[str, frozenset[str]]:
    """Jobs that run no pytest but aggregate other jobs via `needs:`."""
    found: dict[str, frozenset[str]] = {}
    prefix = next(iter(repository_jobs())).split(" / ")[0]
    for name, block in repository_jobs().items():
        if name in job_selectors():
            continue
        needs = re.search(r"^    needs:\s*\n((?:      - .+\n)+)", block, flags=re.MULTILINE)
        if needs:
            jobs = re.findall(r"- (\S+)", needs.group(1))
            found[name] = frozenset(f"{prefix} / {job}" for job in jobs)
    return found


# --- A tiny evaluator for pytest's `-m` grammar (and / or / not / parentheses) ---


def _tokens(expression: str) -> list[str]:
    return re.findall(r"\(|\)|[A-Za-z_][A-Za-z0-9_]*", expression)


def selects(expression: str, markers: Iterable[str]) -> bool:
    present = set(markers)
    tokens = _tokens(expression)
    position = 0

    def peek() -> str | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> str:
        nonlocal position
        token = tokens[position]
        position += 1
        return token

    def disjunction() -> bool:
        value = conjunction()
        while peek() == "or":
            take()
            value = conjunction() or value
        return value

    def conjunction() -> bool:
        value = negation()
        while peek() == "and":
            take()
            value = negation() and value
        return value

    def negation() -> bool:
        if peek() == "not":
            take()
            return not negation()
        name = take()
        if name == "(":
            value = disjunction()
            assert take() == ")"
            return value
        assert name in declared_markers(), f"undeclared marker {name!r} in a job selector"
        return name in present

    result = disjunction()
    assert position == len(tokens), f"unparsed selector tail in {expression!r}"
    return result


# --- Matrix marker descriptions -> node classes ---------------------------------


def node_classes(description: str) -> list[frozenset[str]] | None:
    """Parse a matrix `markers` description into declared-marker classes.

    Returns None for helper/data modules that CI does not collect, and an empty
    list for frontend (vitest) modules, which have no pytest markers.
    """
    if description.startswith("none ("):
        return None
    if description.startswith("vitest ("):
        return []
    classes: list[frozenset[str]] = []
    auto_only = True
    for segment in (part.strip() for part in description.split(";")):
        explicit = frozenset(re.findall(r"@pytest\.mark\.([a-z0-9_]+)", segment))
        if segment.startswith("unmarked nodes"):
            classes.append(frozenset())
            auto_only = False
        elif explicit:
            classes.append(explicit)
            auto_only = False
        else:
            auto = re.fullmatch(r"([a-z0-9_]+) \(auto\b.*\)", segment)
            assert auto, f"unrecognised marker description segment: {segment!r}"
            assert auto.group(1) in declared_markers()
    if auto_only:
        # An auto-marked module: its nodes carry the `database` marker.
        classes.append(frozenset({"database"}))
    return classes


def auto_claims(description: str) -> frozenset[str]:
    return frozenset(re.findall(r"(?:^|; )([a-z0-9_]+) \(auto\b", description))


def derived_lanes(path: str, description: str) -> frozenset[str] | None:
    classes = node_classes(description)
    if classes is None:
        return None
    if not classes:
        frontend = re.fullmatch(r"vitest \((.+)\)", description)
        assert frontend
        return frozenset({frontend.group(1)})
    lanes: set[str] = set()
    for declared in classes:
        effective = effective_markers(path, declared)
        lanes |= {
            job for job, expression in job_selectors().items() if selects(expression, effective)
        }
    return frozenset(lanes)


def planned_lanes() -> list[tuple[str, str, str, list[str]]]:
    """(work package, path, markers description, matrix ci_jobs) for every lane row."""
    rows = []
    for package in _matrix()["work_packages"]:
        for lane in package.get("test_lanes", []):
            rows.append((package["id"], lane["path"], lane["markers"], list(lane["ci_jobs"])))
    return rows


def _lane_by_path() -> dict[str, tuple[str, list[str]]]:
    lanes: dict[str, tuple[str, list[str]]] = {}
    for _, path, description, jobs in planned_lanes():
        if path in lanes:
            assert lanes[path] == (description, jobs), f"{path} has two different lane rows"
        lanes[path] = (description, jobs)
    return lanes


# --- Pins on the restated repository rules -------------------------------------


def test_the_restated_auto_marking_matches_tests_db_fixtures() -> None:
    """If `pytest_collection_modifyitems` changes shape, this lint must be revisited."""
    text = FIXTURES.read_text(encoding="utf-8")
    for anchor in (
        'if path.endswith("test_head_round_trip.py"):',
        'if "/tests/migration/" in f"/{path}":',
        'if path.endswith("_migration.py") or path.endswith(',
        '"test_every_revision_denotes_one_schema.py"',
        'if "database" not in names:',
        "if names & _NARROW_MARKERS:",
        "item.add_marker(clone)",
    ):
        assert anchor in text, anchor
    narrow = re.search(r"_NARROW_MARKERS: Final = frozenset\(\s*\{(.*?)\}", text, flags=re.S)
    assert narrow is not None
    assert frozenset(re.findall(r'"([a-z0-9_]+)"', narrow.group(1))) == _NARROW


def test_the_pytest_lanes_and_aggregator_are_the_expected_jobs() -> None:
    prefix = "repository-checks"
    assert set(job_selectors()) == {f"{prefix} / {job}" for job in PYTEST_JOBS}
    assert aggregator_needs()[f"{prefix} / database-tier"] == {
        f"{prefix} / {job}"
        for job in (
            "database-current-head",
            "database-recovery",
            "migration-empty-to-head",
            "migration-edge",
            "database-e2e",
        )
    }
    fast = "not slow and not database and not network and not connector and not evaluation"
    for job in ("validate", "dependency-floor"):
        assert job_selectors()[f"{prefix} / {job}"].startswith(fast)
    assert {"frontend / unit", "frontend / contract"} <= frontend_jobs()


def test_the_selector_evaluator_agrees_with_known_cases() -> None:
    fast = job_selectors()["repository-checks / validate"]
    assert selects(fast, set())
    assert not selects(fast, {"database", "database_clone"})
    assert selects(fast, {"migration_edge"})  # unmarked *_migration.py nodes run in FAST too
    assert selects(
        job_selectors()["repository-checks / database-recovery"], {"database", "recovery"}
    )
    assert not selects(
        job_selectors()["repository-checks / database-current-head"], {"database", "recovery"}
    )


# --- The lint -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("package", "path", "description", "jobs"),
    planned_lanes(),
    ids=[f"{row[0]}:{row[1]}" for row in planned_lanes()],
)
def test_each_planned_module_lane_is_what_its_markers_select(
    package: str, path: str, description: str, jobs: list[str]
) -> None:
    """AC-144: the recorded CI jobs are exactly the jobs the markers select."""
    _ = package
    for job in jobs:
        assert job in all_job_names(), f"{path}: cites a job no workflow defines: {job}"
    derived = derived_lanes(path, description)
    if derived is None:
        assert jobs == [], f"{path}: a helper/data module claims CI jobs"
        return
    assert derived == set(jobs), (
        f"{path}: matrix says {sorted(jobs)}, markers select {sorted(derived)}"
    )
    classes = node_classes(description) or []
    for claimed in auto_claims(description):
        assert any(claimed in effective_markers(path, declared) for declared in classes), (
            f"{path}: claims auto marker {claimed} that tests/db/fixtures.py would not add"
        )


def test_recovery_and_e2e_and_frontend_modules_map_to_their_dedicated_jobs() -> None:
    """AC-144's three named mappings."""
    for _, path, description, jobs in planned_lanes():
        classes = node_classes(description) or []
        if any("recovery" in declared for declared in classes):
            assert "repository-checks / database-recovery" in jobs, path
        if any({"database", "e2e"} <= declared for declared in classes):
            assert "repository-checks / database-e2e" in jobs, path
        if path.startswith("web/"):
            assert description.startswith("vitest ("), path
            assert set(jobs) <= {"frontend / unit", "frontend / contract"}, path


def test_database_tier_modules_declare_database() -> None:
    """AC-127: `concurrency`/`schema`/`database`/`recovery` DB modules carry `database`."""
    for _, path, description, _jobs in planned_lanes():
        classes = node_classes(description)
        if classes is None or path.startswith("web/"):
            continue
        directory = path.split("/")[1]
        if directory in {"database", "concurrency", "recovery", "end_to_end"}:
            assert classes and all("database" in declared for declared in classes), path
        if directory == "schema" and any(
            job != "repository-checks / validate" and job != "repository-checks / dependency-floor"
            for job in derived_lanes(path, description) or ()
        ):
            assert any("database" in declared for declared in classes), path


def test_every_active_ac_cites_exactly_the_lanes_of_its_modules() -> None:
    """AC-081 / AC-127: an AC's ci_jobs equal its modules' lanes (plus aggregators).

    An AC whose proof would need a marker no CI job selects (`evaluation`,
    `connector`, ...) has no lane, so it cannot be ACTIVE: it must be moved to
    commissioning evidence.
    """
    lanes = _lane_by_path()
    aggregators = aggregator_needs()
    for criterion in _matrix()["acceptance_criteria"]:
        if criterion["status"] != "ACTIVE_R6":
            continue
        union: set[str] = set()
        for module in criterion["tests"]:
            assert module in lanes, f"{criterion['id']}: {module} has no lane row"
            derived = derived_lanes(module, lanes[module][0])
            if derived is None:
                # A helper/data module (e.g. the schema-ahead contract) is cited
                # beside the module that imports it; it contributes no lane.
                continue
            assert derived, f"{criterion['id']}: {module} runs in no CI job"
            union |= derived
        assert union, f"{criterion['id']}: no cited module runs in any CI job"
        cited = set(criterion["ci_jobs"])
        extra = cited - union
        assert union <= cited, f"{criterion['id']}: missing {sorted(union - cited)}"
        for job in extra:
            assert job in aggregators, (
                f"{criterion['id']}: cites {job} that none of its modules run in"
            )


def _planned_modules_on_disk() -> list[str]:
    return sorted(
        path for path in _lane_by_path() if path.endswith(".py") and (ROOT / path).exists()
    )


def test_wp01s_planned_modules_are_on_disk_and_therefore_checked() -> None:
    wp01 = next(p for p in _matrix()["work_packages"] if p["id"] == "KLP-WP-01")
    assert set(wp01["tests"]) <= set(_planned_modules_on_disk())


@pytest.mark.parametrize("path", _planned_modules_on_disk())
def test_modules_on_disk_declare_markers_consistent_with_their_lane(path: str) -> None:
    """Checked automatically as each planned module lands.

    The parameter list is every planned module that exists, so a later WP's
    module joins this check the moment it is added. A FAST-only module declares
    no lane marker at all; otherwise the lane markers the module text declares
    are exactly the explicit markers its lane row describes.
    """
    description, _jobs = _lane_by_path()[path]
    classes = node_classes(description)
    text = (ROOT / path).read_text(encoding="utf-8")
    used = set(re.findall(r"pytest[.]mark[.]([a-z0-9_]+)", text)) & declared_markers()
    used |= set(re.findall(r"pytestmark\s*=.*?mark[.]([a-z0-9_]+)", text)) & declared_markers()
    if classes is None:
        assert not used, f"{path}: a helper/data module declares lane markers {sorted(used)}"
        return
    expected: set[str] = set().union(*classes) if classes else set()
    assert used == expected, (
        f"{path}: declares {sorted(used)}, lane row describes {sorted(expected)}"
    )
