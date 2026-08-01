#!/usr/bin/env python3
"""Validate the terminal, closed Phase 00 governance state.

Standard-library only and deterministic. Every problem is reported as one
`FAIL <reason>` line and a missing or wrongly typed field is a failure, never a
traceback. Exit 0 means the recorded terminal state still matches the tree.

Phase 00 is closed: both work items are `CLOSED`, no work item or authorization
is active, and the closeout merged as PR #12. The previous revision of this
script instead asserted the mid-flight `WP-P00-02` state -- one active work
item, a specific active authorization, three criteria still pending review --
so once the phase closed it could only crash or fail. That defect is the real
content of finding `MYPA-PHASE-00-COMPLETION-IR-F-002`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

GOAL_STATE = "docs/migration/governance/goal-state.json"
WORK_ITEM_LEDGER = "docs/migration/governance/work-item-ledger.json"
AUTHORIZATION_LEDGER = "docs/migration/governance/authorization-ledger.json"
ACCEPTANCE_REGISTER = "docs/migration/governance/acceptance-criteria-register.json"
WP_P00_02_EVIDENCE = "evidence/migration/WP-P00-02/00_EVIDENCE_INDEX.json"

LOGGING_STANDARD = "docs/migration/governance/logging-and-audit-standard.md"
BRANCH_STRATEGY = "docs/migration/governance/branch-and-worktree-strategy.md"
NAMING_RULE = "docs/migration/governance/target-surface-naming-rule.md"

EXPECTED_FILES = (
    "docs/migration/00_MIGRATION_INDEX.md",
    "docs/migration/governance/GOAL-MYPA-POSTGRESQL-MIGRATION-001.md",
    GOAL_STATE,
    WORK_ITEM_LEDGER,
    AUTHORIZATION_LEDGER,
    ACCEPTANCE_REGISTER,
    BRANCH_STRATEGY,
    LOGGING_STANDARD,
    NAMING_RULE,
    "evidence/migration/WP-P00-01/00_EVIDENCE_INDEX.json",
    WP_P00_02_EVIDENCE,
    "evidence/migration/WP-P00-02/closeout/00_CLOSEOUT_INDEX.json",
    "evidence/migration/WP-P00-02/closeout/PHASE-00-FINAL-CLOSEOUT.md",
    "evidence/migration/phase-00-final/CLOSEOUT.md",
)

EXPECTED_WORK_ITEMS = ("WP-P00-01", "WP-P00-02")
EXPECTED_CRITERIA = tuple(f"P00-AC-{index:02d}" for index in range(1, 9))

CLOSEOUT_PULL_REQUEST = 12
CLOSEOUT_MERGE_SHA = "2672898530916c3657d6e5fef47b401c219a61da"

# The attestation is scoped to what Phase 00's own governance work did. It is
# deliberately not a claim about the repository's future: Phase 01 onward
# provisions PostgreSQL and reads the legacy source by design.
ATTESTATION_SCOPE_KEY = "attestation_scope"
ATTESTATION_SCOPE = "PHASE_00_WORK_ONLY"
ATTESTATION_FLAG_PREFIX = "phase_00_"
EXPECTED_ATTESTATION_FLAGS = (
    "phase_00_database_accessed",
    "phase_00_sqlite_accessed",
    "phase_00_snapshot_accessed",
    "phase_00_postgresql_accessed",
    "phase_00_source_data_processed",
    "phase_00_personal_data_processed",
    "phase_00_runtime_code_modified",
    "phase_00_dependencies_modified",
    "phase_00_ci_workflows_modified",
    "phase_00_deployment_performed",
    "phase_00_production_activated",
)

STALE_LEDGER_FIELD = "required_base_for_future_authorization"

LOGGING_PHRASES = (
    "message bodies",
    "document contents",
    "personal contact details",
    "access or refresh tokens",
    "connection strings",
    "raw JSON",
    "sensitive query text",
    "stable non-content identifiers",
    "bounded error categories",
)

BRANCH_PHRASES = (
    "one-work-item / one-branch",
    "Later commit invalidates",
    "Squash-merge validation",
    "Destructive cleanup authority",
    "PENDING_CONNECTOR_CAPABILITY",
)

NAMING_PHRASES = (
    "public APIs",
    "MCP server",
    "environment variables",
    "new repository paths",
    "HISTORICAL_EVIDENCE",
)

PUBLIC_SCAN_ROOTS = (
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "README.md",
    "pyproject.toml",
    "src",
    "docs/architecture",
    "docs/specs",
    "docs/decisions",
)

FORBIDDEN_PUBLIC_PATTERNS = (
    "hb_",
    "HB_",
    "hb-",
    "HB-",
    "hb personal",
    "HB Personal",
    "hb-personal-assistant",
)


def read_json(relative: str, failures: list[str]) -> dict[str, Any]:
    """Parse one governance record, recording a failure instead of raising."""
    try:
        parsed: object = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        failures.append(f"json-parse:{relative}:{type(error).__name__}")
        return {}
    if not isinstance(parsed, dict):
        failures.append(f"json-shape:{relative}:expected-object")
        return {}
    return parsed


def field(record: dict[str, Any], *path: str) -> object:
    """Return a nested value, or None if any step is absent or not an object."""
    node: object = record
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def expect(failures: list[str], label: str, actual: object, wanted: object) -> None:
    if actual != wanted:
        failures.append(f"{label}:expected={wanted!r}:actual={actual!r}")


def read_text(relative: str, failures: list[str]) -> str:
    try:
        return (ROOT / relative).read_text(encoding="utf-8")
    except OSError as error:
        failures.append(f"unreadable:{relative}:{type(error).__name__}")
        return ""


def walk_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(walk_keys(child))
    return keys


def work_item_states(work: dict[str, Any]) -> dict[str, object]:
    items = field(work, "work_items")
    states: dict[str, object] = {}
    if not isinstance(items, list):
        return states
    for entry in items:
        if isinstance(entry, dict):
            identifier = entry.get("work_item_id")
            if isinstance(identifier, str):
                states[identifier] = entry.get("state")
    return states


def check_files(failures: list[str]) -> None:
    for relative in EXPECTED_FILES:
        if not (ROOT / relative).is_file():
            failures.append(f"missing-file:{relative}")


def check_lifecycle(
    failures: list[str],
    goal: dict[str, Any],
    work: dict[str, Any],
    auth: dict[str, Any],
) -> None:
    expect(failures, "goal:phase_00.state", field(goal, "phase_00", "state"), "COMPLETE")
    expect(failures, "goal:active_work_item_count", field(goal, "active_work_item_count"), 0)
    expect(failures, "goal:active_work_item_id", field(goal, "active_work_item_id"), None)
    expect(
        failures,
        "goal:phase_00.closeout_merge.pull_request",
        field(goal, "phase_00", "closeout_merge", "pull_request"),
        CLOSEOUT_PULL_REQUEST,
    )
    expect(
        failures,
        "goal:phase_00.closeout_merge.merge_sha",
        field(goal, "phase_00", "closeout_merge", "merge_sha"),
        CLOSEOUT_MERGE_SHA,
    )
    expect(
        failures,
        "goal:phase_00.closeout_merge.state",
        field(goal, "phase_00", "closeout_merge", "state"),
        "MERGED",
    )

    expect(failures, "work-ledger:active_work_item_count", field(work, "active_work_item_count"), 0)
    expect(failures, "work-ledger:active_work_item_id", field(work, "active_work_item_id"), None)
    states = work_item_states(work)
    for identifier in EXPECTED_WORK_ITEMS:
        expect(failures, f"work-item:{identifier}", states.get(identifier), "CLOSED")
    for identifier in sorted(set(states) - set(EXPECTED_WORK_ITEMS)):
        failures.append(f"work-item-unexpected:{identifier}")
    if STALE_LEDGER_FIELD in walk_keys(work):
        failures.append(f"stale-ledger-field:{STALE_LEDGER_FIELD}")

    expect(
        failures,
        "auth-ledger:active_authorization_count",
        field(auth, "active_authorization_count"),
        0,
    )
    expect(failures, "auth-ledger:active_authorization", field(auth, "active_authorization"), None)


def check_criteria(failures: list[str], register: dict[str, Any]) -> None:
    criteria = field(register, "criteria")
    if not isinstance(criteria, dict):
        failures.append("criteria:missing-or-not-an-object")
        return
    for identifier in EXPECTED_CRITERIA:
        entry = criteria.get(identifier)
        if not isinstance(entry, dict):
            failures.append(f"criterion-missing:{identifier}")
            continue
        if entry.get("accepted") is not True:
            failures.append(f"criterion-not-accepted:{identifier}:{entry.get('accepted')!r}")
        status = entry.get("status")
        if not isinstance(status, str) or not status:
            failures.append(f"criterion-status-missing:{identifier}")
    expect(
        failures,
        "criteria:summary.accepted_count",
        field(register, "summary", "accepted_count"),
        len(EXPECTED_CRITERIA),
    )


def check_cleanup(failures: list[str], goal: dict[str, Any]) -> None:
    expect(failures, "cleanup:status", field(goal, "cleanup", "status"), "COMPLETE")
    expect(
        failures, "cleanup:deletion_performed", field(goal, "cleanup", "deletion_performed"), True
    )
    expect(failures, "cleanup:cleanup_closed", field(goal, "cleanup", "cleanup_closed"), True)


def check_attestation(failures: list[str], goal: dict[str, Any], evidence: dict[str, Any]) -> None:
    attestation = field(goal, "access_attestation")
    if not isinstance(attestation, dict):
        failures.append("attestation:missing-or-not-an-object")
        return
    expect(
        failures,
        f"attestation:{ATTESTATION_SCOPE_KEY}",
        attestation.get(ATTESTATION_SCOPE_KEY),
        ATTESTATION_SCOPE,
    )
    for flag in EXPECTED_ATTESTATION_FLAGS:
        if flag not in attestation:
            failures.append(f"attestation-flag-missing:{flag}")
    for key, value in sorted(attestation.items()):
        if key.startswith(ATTESTATION_FLAG_PREFIX) and value is not False:
            failures.append(f"attestation-flag-not-false:{key}:{value!r}")
    if field(evidence, "access_attestation") != attestation:
        failures.append("attestation-drift:evidence-index-differs-from-goal-state")


def check_phrases(
    failures: list[str], relative: str, label: str, phrases: tuple[str, ...], *, fold_case: bool
) -> None:
    text = read_text(relative, failures)
    haystack = text.lower() if fold_case else text
    for phrase in phrases:
        if (phrase.lower() if fold_case else phrase) not in haystack:
            failures.append(f"{label}:{phrase}")


def scan_public_surfaces() -> tuple[list[str], int]:
    hits: list[str] = []
    roots_seen = 0
    for item in PUBLIC_SCAN_ROOTS:
        path = ROOT / item
        if not path.exists():
            continue
        roots_seen += 1
        files = [path] if path.is_file() else sorted(p for p in path.rglob("*") if p.is_file())
        for file in files:
            try:
                text = file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for pattern in FORBIDDEN_PUBLIC_PATTERNS:
                if pattern in text:
                    hits.append(f"{file.relative_to(ROOT)}:{pattern}")
    return hits, roots_seen


def report(failures: list[str]) -> int:
    for failure in failures:
        print(f"FAIL {failure}")
    return 1


def main(argv: list[str]) -> int:
    failures: list[str] = []

    check_files(failures)
    if failures:
        return report(failures)

    goal = read_json(GOAL_STATE, failures)
    work = read_json(WORK_ITEM_LEDGER, failures)
    auth = read_json(AUTHORIZATION_LEDGER, failures)
    register = read_json(ACCEPTANCE_REGISTER, failures)
    evidence = read_json(WP_P00_02_EVIDENCE, failures)
    if failures:
        return report(failures)

    check_lifecycle(failures, goal, work, auth)
    check_criteria(failures, register)
    check_cleanup(failures, goal)
    check_attestation(failures, goal, evidence)
    check_phrases(failures, LOGGING_STANDARD, "logging-contract", LOGGING_PHRASES, fold_case=False)
    check_phrases(failures, BRANCH_STRATEGY, "branch-contract", BRANCH_PHRASES, fold_case=True)
    check_phrases(failures, NAMING_RULE, "naming-contract", NAMING_PHRASES, fold_case=False)

    hits, roots_seen = scan_public_surfaces()
    allow_partial = "--allow-partial-checkout" in argv
    if roots_seen == 0 and not allow_partial:
        failures.append("public-surface-roots-unavailable")
    failures.extend(f"public-name-hit:{hit}" for hit in hits)

    if failures:
        return report(failures)

    print(f"PASS governance-files count={len(EXPECTED_FILES)}")
    print("PASS json-parse records=5")
    print(f"PASS phase-00-terminal-lifecycle closed={len(EXPECTED_WORK_ITEMS)} active=0")
    print(f"PASS phase-00-closeout-merge pr={CLOSEOUT_PULL_REQUEST} sha={CLOSEOUT_MERGE_SHA}")
    print(f"PASS acceptance-criteria accepted={len(EXPECTED_CRITERIA)}")
    print("PASS cleanup-closed")
    print("PASS P00-AC-06-branch-contract")
    print("PASS P00-AC-07-logging-contract")
    print("PASS naming-contract")
    if roots_seen:
        print(f"PASS P00-AC-08-public-surface-scan roots={roots_seen}")
    else:
        print("SKIP P00-AC-08-public-surface-scan partial-checkout; require repository scan")
    print(f"PASS access-attestation scope={ATTESTATION_SCOPE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
