"""The WP27 all-250 protection ledger must be complete, unique, and honest.

This is not a coverage-percentage gate. It proves:

* exactly the IDs PFE-AC-001..250 appear once;
* required fields are populated;
* referenced test paths exist unless the protection status is one that may have
  no automated file;
* SUPERSEDED records cite current supersession authority;
* PROTECTION_MISSING is explicit rather than a blank default.

It does not prove the listed tests are strong. That remains a review claim.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[2] / "docs/plans/frontend-protection-ledger.json"
REPO = Path(__file__).resolve().parents[2]

REQUIRED_FIELDS = (
    "criterion_id",
    "domain",
    "owning_implementation_wps",
    "acceptance_disposition",
    "evidence_class",
    "implementation_evidence",
    "protection_status",
    "protection_layers",
    "test_files",
    "test_names",
    "ci_jobs",
    "assertion_quality",
    "fixture_fidelity",
    "negative_path_coverage",
    "principal_isolation",
    "concurrency_idempotency",
    "manual_evidence_remaining",
    "runtime_evidence_remaining",
    "known_gaps",
    "wp28_action",
    "wp30_action",
)

ACCEPTANCE = {
    "PASS_VERIFIED",
    "IMPLEMENTATION_REQUIRED",
    "VALIDATION_REQUIRED",
    "SUPERSEDED",
    "JUSTIFIED_NA",
    "UNRECONCILED",
}

EVIDENCE_CLASS = {
    "CI_PROVABLE",
    "CI_PARTIAL",
    "MANUAL_REQUIRED",
    "RUNTIME_REQUIRED",
    "CI_NOT_APPLICABLE",
}

PROTECTION_STATUS = {
    "PROTECTED_STRONG",
    "PROTECTED_PARTIAL",
    "PROTECTED_WRONG_LAYER",
    "PROTECTED_WEAK_ASSERTION",
    "FIXTURE_ONLY",
    "MANUAL_ONLY",
    "RUNTIME_ONLY",
    "PROTECTION_MISSING",
    "SUPERSEDED",
    "JUSTIFIED_NA",
}

NO_TEST_FILE_STATUSES = {
    "SUPERSEDED",
    "JUSTIFIED_NA",
    "MANUAL_ONLY",
    "RUNTIME_ONLY",
    "PROTECTION_MISSING",
}

SUPERSESSION_NEEDLE = "frontend-implementation-authority.md"

BLANK = {"", "NOT_YET_RECORDED", "TODO", "unknown"}


def _load() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def test_ledger_file_exists() -> None:
    assert LEDGER.is_file(), LEDGER


def test_exactly_250_unique_pfe_ids() -> None:
    payload = _load()
    records = payload["records"]
    ids = [row["criterion_id"] for row in records]
    expected = [f"PFE-AC-{n:03d}" for n in range(1, 251)]
    assert ids == expected
    assert len(set(ids)) == 250


def test_required_fields_are_populated() -> None:
    repo = REPO
    for row in _load()["records"]:
        cid = row["criterion_id"]
        for field in REQUIRED_FIELDS:
            assert field in row, f"{cid} missing {field}"
            value = row[field]
            if field in {
                "owning_implementation_wps",
                "protection_layers",
                "test_files",
                "test_names",
                "ci_jobs",
            }:
                assert isinstance(value, list), f"{cid}.{field} must be a list"
                continue
            assert isinstance(value, str), f"{cid}.{field} must be a string"
            assert value.strip() not in BLANK, f"{cid}.{field} is blank"

        assert row["acceptance_disposition"] in ACCEPTANCE, cid
        assert row["evidence_class"] in EVIDENCE_CLASS, cid
        assert row["protection_status"] in PROTECTION_STATUS, cid

        if row["protection_status"] not in NO_TEST_FILE_STATUSES:
            assert row["test_files"], f"{cid} claims automated protection but lists no files"
            for path in row["test_files"]:
                assert (repo / path).is_file(), f"{cid} references missing {path}"

        if row["protection_status"] == "SUPERSEDED":
            assert row["acceptance_disposition"] == "SUPERSEDED", cid
            cited = row["implementation_evidence"] + row["known_gaps"]
            assert SUPERSESSION_NEEDLE in cited
            assert row["evidence_class"] == "CI_NOT_APPLICABLE"


def test_no_unknown_or_duplicate_ids_in_meta() -> None:
    payload = _load()
    assert payload["schema_version"] == 1
    assert payload["universe"] == "PFE-AC-001..250"
    assert int(payload["record_count"]) == 250


def _e2e_critical_specs() -> set[str]:
    """Specs named on the required e2e-critical npm command, as web/ paths."""
    workflow = REPO / ".github" / "workflows" / "frontend-quality.yml"
    text = workflow.read_text(encoding="utf-8")
    match = re.search(
        r"name: frontend / e2e-critical[\s\S]*?npm run e2e -- ([^\n]+)",
        text,
    )
    assert match is not None, "could not read the frontend / e2e-critical command"
    return {
        f"web/{token}"
        for token in match.group(1).split()
        if token.startswith("e2e/") and token.endswith(".spec.ts")
    }


def test_e2e_critical_ci_jobs_name_a_spec_that_job_runs() -> None:
    """A criterion must not claim the required e2e job for a spec that job excludes.

    PFE-AC-123..129 listed failure-states.spec.ts and frontend / e2e-critical
    after that spec was kept off the required gate. known_gaps is not a
    substitute for an honest ci_jobs list.
    """
    required = _e2e_critical_specs()
    assert required, "e2e-critical command named no specs"
    dishonest: list[str] = []
    for row in _load()["records"]:
        if "frontend / e2e-critical" not in row["ci_jobs"]:
            continue
        e2e_files = [
            path
            for path in row["test_files"]
            if path.startswith("web/e2e/") and path.endswith(".spec.ts")
        ]
        if e2e_files and not any(path in required for path in e2e_files):
            dishonest.append(row["criterion_id"])
    assert dishonest == [], (
        "ci_jobs lists frontend / e2e-critical but none of the listed e2e specs "
        f"are in that job: {dishonest}"
    )
