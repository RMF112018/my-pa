#!/usr/bin/env python3
"""Deterministic Phase 00 governance validation. Standard-library only."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

EXPECTED = {
    "docs/migration/governance/goal-state.json",
    "docs/migration/governance/work-item-ledger.json",
    "docs/migration/governance/authorization-ledger.json",
    "docs/migration/governance/acceptance-criteria-register.json",
    "docs/migration/governance/branch-and-worktree-strategy.md",
    "docs/migration/governance/logging-and-audit-standard.md",
    "docs/migration/governance/target-surface-naming-rule.md",
    "evidence/migration/WP-P00-02/00_EVIDENCE_INDEX.json",
}

PUBLIC_SCAN_ROOTS = [
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "README.md",
    "pyproject.toml",
    "src",
    "docs/architecture",
    "docs/specs",
    "docs/decisions",
]

FORBIDDEN_PUBLIC_PATTERNS = (
    "hb_",
    "HB_",
    "hb-",
    "HB-",
    "hb personal",
    "HB Personal",
    "hb-personal-assistant",
)


def load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


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


def scan_public_surfaces() -> tuple[list[str], int]:
    hits: list[str] = []
    roots_seen = 0
    for item in PUBLIC_SCAN_ROOTS:
        path = ROOT / item
        if not path.exists():
            continue
        roots_seen += 1
        files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
        for file in files:
            try:
                text = file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for pattern in FORBIDDEN_PUBLIC_PATTERNS:
                if pattern in text:
                    hits.append(f"{file.relative_to(ROOT)}:{pattern}")
    return hits, roots_seen


def main() -> int:
    failures: list[str] = []
    for path in sorted(EXPECTED):
        if not (ROOT / path).is_file():
            failures.append(f"missing:{path}")

    if failures:
        print("\n".join(failures))
        return 1

    goal = load_json("docs/migration/governance/goal-state.json")
    work = load_json("docs/migration/governance/work-item-ledger.json")
    auth = load_json("docs/migration/governance/authorization-ledger.json")
    ac = load_json("docs/migration/governance/acceptance-criteria-register.json")
    evidence = load_json("evidence/migration/WP-P00-02/00_EVIDENCE_INDEX.json")

    if work["active_work_item_count"] != 1:
        failures.append("work-item-count")
    if work["work_items"][0]["state"] != "CLOSED":
        failures.append("wp-p00-01-not-closed")
    if work["work_items"][1]["state"] != "IMPLEMENTED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW":
        failures.append("wp-p00-02-state")
    if "required_base_for_future_authorization" in walk_keys(work):
        failures.append("stale-required-base-field")
    if goal["active_work_item_id"] != "WP-P00-02":
        failures.append("goal-active-work-item")
    if (
        auth["active_authorization"]["authorization_id"]
        != "AUTH-MYPA-MIGRATION-PHASE-00-COMPLETION-20260801-001"
    ):
        failures.append("authorization-id")
    if auth["active_authorization_count"] != 1:
        failures.append("authorization-count")

    for criterion in ("P00-AC-06", "P00-AC-07", "P00-AC-08"):
        status = ac["criteria"][criterion]["status"]
        if status != "DEMONSTRATED_PENDING_ROLE_SEPARATED_EXACT_HEAD_REVIEW":
            failures.append(f"criterion:{criterion}:{status}")

    logging = (ROOT / "docs/migration/governance/logging-and-audit-standard.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "message bodies",
        "document contents",
        "personal contact details",
        "access or refresh tokens",
        "connection strings",
        "raw JSON",
        "sensitive query text",
        "stable non-content identifiers",
        "bounded error categories",
    ):
        if phrase not in logging:
            failures.append(f"logging-contract:{phrase}")

    branch = (ROOT / "docs/migration/governance/branch-and-worktree-strategy.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "one-work-item / one-branch",
        "Later commit invalidates",
        "Squash-merge validation",
        "Destructive cleanup authority",
        "PENDING_CONNECTOR_CAPABILITY",
    ):
        if phrase.lower() not in branch.lower():
            failures.append(f"branch-contract:{phrase}")

    naming = (ROOT / "docs/migration/governance/target-surface-naming-rule.md").read_text(
        encoding="utf-8"
    )
    for phrase in (
        "public APIs",
        "MCP server",
        "environment variables",
        "new repository paths",
        "HISTORICAL_EVIDENCE",
    ):
        if phrase not in naming:
            failures.append(f"naming-contract:{phrase}")

    hits, roots_seen = scan_public_surfaces()
    allow_partial = "--allow-partial-checkout" in sys.argv[1:]
    if roots_seen == 0 and not allow_partial:
        failures.append("public-surface-roots-unavailable")
    failures.extend(f"public-name-hit:{hit}" for hit in hits)

    attestation = goal["access_attestation"]
    if any(attestation.values()):
        failures.append("access-attestation-not-all-false")
    if evidence["access_attestation"] != attestation:
        failures.append("access-attestation-drift")

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1

    print("PASS json-parse")
    print("PASS lifecycle-consistency")
    print("PASS stale-base-field-absent")
    print("PASS P00-AC-06-contract")
    print("PASS P00-AC-07-contract")
    if roots_seen:
        print(f"PASS P00-AC-08-public-surface-scan roots={roots_seen}")
    else:
        print("SKIP P00-AC-08-public-surface-scan partial-checkout; require repository scan")
    print("PASS access-attestation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
