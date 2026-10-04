"""The committed R6 Knowledge Layer matrix stays byte-exact and traceable (KLP-WP-01).

AC-080 and the plan's section 14.1 lint. `tests/architecture/
klp_implementation_matrix_r6.json` is a byte-exact copy of the operator-authorized
R6 machine contract; every later KLP work package is checked against it.

What this FAST lint proves:
- the committed matrix is the authorized one (SHA-256 pin);
- every AC's per-WP proving modules are owned by that WP (owner_discharge is a
  subset of the WP's paths), and its tests are exactly those modules;
- every shared path's WP sequence is exactly the WPs that list it, in order;
- `per_wp_test_replacements` is well-formed: each entry names a module the WP
  owns and a replaced node and its replacement, and one of the two is defined in
  that module at every head;
- ACTIVE_R6 ACs have at least one test module and one CI job; commissioning
  ACs have no `tests/` path; the AC counts match `acceptance_counts`;
- every EXISTS path exists, and every one of KLP-WP-01's NEW paths now exists;
- no existing test module a KLP WP edits carries more slow/skip/xfail markers
  than it did at the R6 basis commit `3f575c02`.

What it cannot prove (AC-080 residual, recorded in the WP evidence): "collected
node ids at base minus head are empty except the replacement list" compares two
pytest collections at two commits. A FAST test sees one tree, so it cannot
enumerate base-only node ids; that clause is discharged by the per-WP
collection diff attached to each WP's evidence, against the replacement list
this lint validates. Likewise, a skip added through a fixture, a conftest hook
or a marker applied outside the module text is invisible to the static marker
census below.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any, Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
MATRIX_PATH: Final = ROOT / "tests" / "architecture" / "klp_implementation_matrix_r6.json"
#: SHA-256 of `MYPA_KNOWLEDGE_LAYER_IMPLEMENTATION_MATRIX_R6_20261004.json`.
MATRIX_SHA256: Final = "ee2f2f8fc81a3e5e3f73e618a18fbf296ecd2a752d50499bf2e725e21e60de6a"
#: Repository basis of the R6 contract.
R6_BASIS_COMMIT: Final = "3f575c02570c8fa733ecdc7bf0284fedc3c1d980"

#: The KLP work packages that have landed: their NEW paths must exist.
LANDED_WPS: Final = frozenset({"KLP-WP-01", "KLP-WP-02"})

#: The slow/skip/xfail census of every EXISTS test module a KLP WP edits, taken
#: at `R6_BASIS_COMMIT`. A WP may lower a count but never raise one (AC-080:
#: "no existing test gains a slow/skip marker"). Modules absent here had none.
#: A module a WP edits that the matrix does not list (a pin the plan's grep
#: missed) is added here with its basis count -- zero entries included -- so the
#: no-new-skip check covers it too (`git show 3f575c02:<path>`).
BASIS_SKIP_CENSUS: Final[dict[str, int]] = {
    "tests/schema/test_constraint_authoring_capability_migration.py": 1,
    "tests/schema/test_constraint_read_capability_migration.py": 2,
    # KLP-WP-02 edits outside the matrix path lists (pins the plan's grep missed).
    "tests/architecture/test_capture_project_binding.py": 0,
    "tests/architecture/test_record_events_are_never_rewritten.py": 0,
    "tests/schema/test_capture_lifecycle_migration.py": 0,
    "tests/database/test_record_event_role_privileges.py": 0,
    "tests/schema/test_audit_schema_migration.py": 0,
    "tests/schema/test_enrollment_objects_migration.py": 0,
    "tests/schema/test_entity_assertion_provenance_migration.py": 0,
    "tests/schema/test_entity_relationship_types_migration.py": 0,
    "tests/schema/test_entity_schema_migration.py": 0,
}
_SKIP_PATTERN: Final = re.compile(
    r"pytest\.mark\.(?:slow|skip|skipif|xfail)\b|pytest\.(?:skip|xfail)\(|importorskip\("
)
_REPLACEMENT: Final = re.compile(
    r"\A(?P<module>tests/[\w/]+\.py)::(?P<old>test_\w+) -> (?P<new>test_\w+) \(same module\)\Z"
)


@cache
def _matrix() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return loaded


def _packages() -> dict[str, dict[str, Any]]:
    return {package["id"]: package for package in _matrix()["work_packages"]}


def _criteria() -> list[dict[str, Any]]:
    criteria: list[dict[str, Any]] = _matrix()["acceptance_criteria"]
    return criteria


def test_the_committed_matrix_is_the_authorized_r6_matrix() -> None:
    assert hashlib.sha256(MATRIX_PATH.read_bytes()).hexdigest() == MATRIX_SHA256
    matrix = _matrix()
    assert (
        matrix["package_id"]
        == "MYPA-KNOWLEDGE-LAYER-IMPLEMENTATION-READINESS-R6-AMENDMENT-20261004-001"
    )
    assert matrix["repository_basis"]["commit"].startswith(R6_BASIS_COMMIT[:8])
    assert matrix["validation"]["errors"] == []


def test_acceptance_ids_are_unique_and_counted() -> None:
    criteria = _criteria()
    ids = [criterion["id"] for criterion in criteria]
    assert len(ids) == len(set(ids))
    counts = _matrix()["acceptance_counts"]
    statuses = Counter(criterion["status"] for criterion in criteria)
    assert counts["total"] == len(criteria)
    assert counts["active_repository"] == statuses["ACTIVE_R6"]
    assert counts["commissioning_evidence"] == statuses["COMMISSIONING_EVIDENCE_R6"]
    assert counts["retired_redundant"] == statuses["RETIRED_REDUNDANT"]
    assert set(statuses) == {"ACTIVE_R6", "COMMISSIONING_EVIDENCE_R6", "RETIRED_REDUNDANT"}


def test_each_wp_lists_its_acs_and_the_acs_list_their_wps() -> None:
    packages = _packages()
    for criterion in _criteria():
        for wp in criterion["work_packages"]:
            assert criterion["id"] in packages[wp]["acceptance_criteria"], (criterion["id"], wp)
        if criterion["status"] == "ACTIVE_R6":
            assert criterion["closing_wp"] in criterion["work_packages"], criterion["id"]
            assert (
                criterion["id"] in packages[criterion["closing_wp"]]["closing_acceptance_criteria"]
            )
    for wp, package in packages.items():
        for ac in package["acceptance_criteria"]:
            owner = next(c for c in _criteria() if c["id"] == ac)
            assert wp in owner["work_packages"], (wp, ac)


def test_owner_discharge_modules_are_owned_by_the_discharging_wp() -> None:
    packages = _packages()
    for criterion in _criteria():
        discharge: dict[str, list[str]] = criterion["owner_discharge"]
        for wp, modules in discharge.items():
            assert wp in criterion["work_packages"], (criterion["id"], wp)
            for module in modules:
                assert module in packages[wp]["paths"], (criterion["id"], wp, module)
                assert module in packages[wp]["tests"], (criterion["id"], wp, module)
        assert {m for modules in discharge.values() for m in modules} == set(criterion["tests"]), (
            criterion["id"]
        )


def test_shared_path_sequences_are_exactly_the_wps_that_list_them() -> None:
    packages = _matrix()["work_packages"]
    listed: dict[str, list[str]] = {}
    for package in packages:
        for path in package["paths"]:
            listed.setdefault(path, []).append(package["id"])
    sequences: dict[str, str] = _matrix()["shared_integration_path_sequence"]
    for path, sequence in sequences.items():
        assert [part.strip() for part in sequence.split("->")] == listed.get(path), path
    shared = {path for path, wps in listed.items() if len(wps) > 1}
    assert shared == set(sequences)


def test_per_wp_test_replacements_are_well_formed() -> None:
    packages = _packages()
    replacements: dict[str, list[str]] = _matrix()["per_wp_test_replacements"]
    assert set(replacements) <= set(packages)
    for wp, entries in replacements.items():
        assert packages[wp]["on_repository_critical_path"], wp
        for entry in entries:
            match = _REPLACEMENT.fullmatch(entry)
            assert match, f"{wp}: malformed replacement entry {entry!r}"
            module = match.group("module")
            assert module in packages[wp]["paths"], (wp, module)
            text = (ROOT / module).read_text(encoding="utf-8")
            defined = {
                name for name in (match.group("old"), match.group("new")) if f"def {name}(" in text
            }
            assert defined, f"{wp}: neither the replaced nor the replacing node is in {module}"


def test_active_acs_have_tests_and_jobs_and_commissioning_acs_have_no_test_path() -> None:
    for criterion in _criteria():
        if criterion["status"] == "ACTIVE_R6":
            assert criterion["tests"], criterion["id"]
            assert criterion["ci_jobs"], criterion["id"]
            assert criterion["proof_scope"] == "repository", criterion["id"]
        else:
            assert not any(test.startswith("tests/") for test in criterion["tests"]), criterion[
                "id"
            ]
            assert not criterion["ci_jobs"] or criterion["status"] != "COMMISSIONING_EVIDENCE_R6"


def test_wp_tests_are_owned_paths_with_lane_rows() -> None:
    for wp, package in _packages().items():
        assert [row["path"] for row in package["path_verification"]] == package["paths"], wp
        assert set(package["tests"]) <= set(package["paths"]), wp
        assert {lane["path"] for lane in package.get("test_lanes", [])} == set(package["tests"]), wp
        for lane in package.get("test_lanes", []):
            assert set(lane["ci_jobs"]) <= set(package["ci_jobs"]) or not lane["ci_jobs"], (
                wp,
                lane,
            )


@pytest.mark.parametrize(
    ("wp", "path", "status"),
    sorted(
        {
            (package["id"], row["path"], row["status"])
            for package in _matrix()["work_packages"]
            for row in package["path_verification"]
        }
    ),
)
def test_path_status_is_consistent_with_the_repository(wp: str, path: str, status: str) -> None:
    """EXISTS paths exist; the NEW paths of every landed KLP WP exist.

    A later WP's NEW path may or may not exist, depending on whether that WP has
    landed; the WP that creates it is the one that proves it. KLP-WP-01 and
    KLP-WP-02 have landed. A NEW_GENERATED path stays a template; once its WP has
    landed, exactly one file matches it (the one generated revision).
    """
    assert status in {"EXISTS", "NEW", "NEW_GENERATED"}
    if status == "EXISTS" or (status == "NEW" and wp in LANDED_WPS):
        assert (ROOT / path).exists(), f"{wp}: {status} path {path} is missing"
    if status == "NEW_GENERATED":
        assert "<" in path, "a generated path is a template, never a literal file name"
        if wp in LANDED_WPS:
            pattern = re.sub(r"<[^>]+>", "*", path)
            assert len(list(ROOT.glob(pattern))) == 1, f"{wp}: {pattern} must match one file"


def _existing_test_modules() -> list[str]:
    return sorted(
        {
            row["path"]
            for package in _matrix()["work_packages"]
            for row in package["path_verification"]
            if row["status"] == "EXISTS"
            and row["path"].startswith("tests/")
            and row["path"].endswith(".py")
        }
    )


def _censused_test_modules() -> list[str]:
    """The matrix's EXISTS test modules plus every census key (matrix-unlisted edits)."""
    return sorted(set(_existing_test_modules()) | set(BASIS_SKIP_CENSUS))


@pytest.mark.parametrize("path", _censused_test_modules())
def test_no_existing_klp_edited_test_module_gains_a_slow_or_skip_marker(path: str) -> None:
    count = len(_SKIP_PATTERN.findall((ROOT / path).read_text(encoding="utf-8")))
    assert count <= BASIS_SKIP_CENSUS.get(path, 0), (
        f"{path} has {count} slow/skip/xfail markers; the R6 basis had "
        f"{BASIS_SKIP_CENSUS.get(path, 0)} (AC-080)"
    )


def test_the_new_klp_modules_carry_no_slow_or_skip_marker() -> None:
    """Every landed WP's own new test modules are FAST/unconditionally collected."""
    for wp in sorted(LANDED_WPS):
        rows = [
            row
            for row in _packages()[wp]["path_verification"]
            if row["status"] == "NEW"
            and row["path"].endswith(".py")
            and row["path"].startswith("tests/")
        ]
        assert rows, wp
        for row in rows:
            text = (ROOT / row["path"]).read_text(encoding="utf-8")
            assert not _SKIP_PATTERN.findall(text), (wp, row["path"])
