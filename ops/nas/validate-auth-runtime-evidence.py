#!/usr/bin/env python3
"""Offline, fail-closed validator for redacted authentication runtime evidence."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA = "my-pa.auth-runtime-evidence.v1"
CANONICAL_ORIGIN = "https://pa.bobby-fetting.me"
RP_ID = "pa.bobby-fetting.me"
FULL_COMMIT = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
FULL_TREE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256 = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
PLACEHOLDER = re.compile(r"^REQUIRED_[A-Z0-9_]+$")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")

TOP_FIELDS = {
    "schema",
    "status",
    "repository_commit",
    "repository_tree",
    "reviewed_commit",
    "reviewed_tree",
    "migration_head",
    "deployment_manifest_sha256",
    "deployed_at",
    "validated_at",
    "canonical_origin",
    "webauthn_rp_id",
    "device",
    "rollback",
    "case",
}
DEVICE_FIELDS = {
    "kind",
    "platform",
    "os_version",
    "browser",
    "browser_version",
    "installed_pwa",
}
ROLLBACK_FIELDS = {"status", "evidence_sha256", "validated_at"}
CASE_FIELDS = {"id", "status", "evidence_sha256", "executed_at", "notes"}
REQUIRED_CASES = {
    "bootstrap",
    "physical_safari_passkey",
    "installed_pwa_sign_in",
    "fresh_step_up_second_passkey",
    "ordinary_recovery",
    "operator_recovery",
    "session_revocation",
    "grant_expiry",
    "restart_persistence",
    "wrong_origin_refusal",
    "rollback",
}
STATUS_VALUES = {
    "NOT_PERFORMED_OPERATOR_GATED",
    "RUNTIME_VALIDATION_PENDING_OPERATOR_AUTHORITY",
    "PASS_VERIFIED",
    "FAILED",
    "BLOCKED",
}
SECRET_KEY_PARTS = {
    "secret",
    "password",
    "token",
    "cookie",
    "challenge",
    "private_key",
    "credential_id",
    "grant_value",
    "recovery_code",
    "session_id",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:authorization|cookie|set-cookie)\s*:", re.IGNORECASE),
    re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9+/=_-]+", re.IGNORECASE),
    re.compile(r"\b(?:bootstrap[_ -]?grant|recovery[_ -]?code|mypa_session)\s*[=:]", re.IGNORECASE),
    JWT,
)


def _unknown_fields(payload: Mapping[str, Any], allowed: set[str], scope: str) -> list[str]:
    return [f"unknown_field:{scope}.{name}" for name in sorted(set(payload) - allowed)]


def _missing_fields(payload: Mapping[str, Any], required: set[str], scope: str) -> list[str]:
    return [f"missing_field:{scope}.{name}" for name in sorted(required - set(payload))]


def _parse_time(value: object, field: str) -> tuple[datetime | None, str | None]:
    if not isinstance(value, str):
        return None, f"invalid_timestamp:{field}"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, f"invalid_timestamp:{field}"
    if parsed.tzinfo is None:
        return None, f"timestamp_not_utc:{field}"
    utc_offset = parsed.utcoffset()
    if utc_offset is None or utc_offset.total_seconds() != 0:
        return None, f"timestamp_not_utc:{field}"
    return parsed, None


def _secret_shape_errors(value: object, path: str = "root") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            if any(part in key for part in SECRET_KEY_PARTS):
                errors.append(f"secret_shaped_key:{path}.{raw_key}")
            errors.extend(_secret_shape_errors(child, f"{path}.{raw_key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_secret_shape_errors(child, f"{path}[{index}]"))
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
        errors.append(f"secret_shaped_value:{path}")
    return errors


def _is_template(payload: Mapping[str, Any]) -> bool:
    if payload.get("status") != "NOT_PERFORMED_OPERATOR_GATED":
        return False
    placeholder_fields = (
        "repository_commit",
        "repository_tree",
        "reviewed_commit",
        "reviewed_tree",
        "migration_head",
        "deployment_manifest_sha256",
        "deployed_at",
        "validated_at",
    )
    if not all(
        isinstance(payload.get(name), str) and PLACEHOLDER.fullmatch(str(payload[name]))
        for name in placeholder_fields
    ):
        return False
    cases = payload.get("case")
    rollback = payload.get("rollback")
    return (
        isinstance(cases, list)
        and all(
            isinstance(case, Mapping) and case.get("status") == "NOT_PERFORMED_OPERATOR_GATED"
            for case in cases
        )
        and isinstance(rollback, Mapping)
        and rollback.get("status") == "NOT_PERFORMED_OPERATOR_GATED"
    )


def validate(payload: Mapping[str, Any], *, allow_template: bool = False) -> list[str]:
    """Return stable refusal reasons; an empty list means the record is admissible."""

    errors = _missing_fields(payload, TOP_FIELDS, "root")
    errors.extend(_unknown_fields(payload, TOP_FIELDS, "root"))
    errors.extend(_secret_shape_errors(payload))

    template = _is_template(payload)
    if template and not allow_template:
        errors.append("template_requires_allow_template")
    if allow_template and not template:
        errors.append("allow_template_requires_inert_template")

    if payload.get("schema") != SCHEMA:
        errors.append("unsupported_schema")
    status = payload.get("status")
    if status not in STATUS_VALUES:
        errors.append("invalid_status:root")
    if payload.get("canonical_origin") != CANONICAL_ORIGIN:
        errors.append("canonical_origin_mismatch")
    if payload.get("webauthn_rp_id") != RP_ID:
        errors.append("webauthn_rp_id_mismatch")

    if not template:
        commit = payload.get("repository_commit")
        tree = payload.get("repository_tree")
        reviewed_commit = payload.get("reviewed_commit")
        reviewed_tree = payload.get("reviewed_tree")
        if not isinstance(commit, str) or FULL_COMMIT.fullmatch(commit) is None:
            errors.append("repository_commit_not_full_hex")
        if not isinstance(tree, str) or FULL_TREE.fullmatch(tree) is None:
            errors.append("repository_tree_not_full_hex")
        if not isinstance(reviewed_commit, str) or FULL_COMMIT.fullmatch(reviewed_commit) is None:
            errors.append("reviewed_commit_not_full_hex")
        if not isinstance(reviewed_tree, str) or FULL_TREE.fullmatch(reviewed_tree) is None:
            errors.append("reviewed_tree_not_full_hex")
        if reviewed_commit != commit:
            errors.append("reviewed_commit_mismatch")
        if reviewed_tree != tree:
            errors.append("reviewed_tree_mismatch")
        manifest_hash = payload.get("deployment_manifest_sha256")
        if not isinstance(manifest_hash, str) or SHA256.fullmatch(manifest_hash) is None:
            errors.append("deployment_manifest_hash_invalid")

        deployed_at, deployed_error = _parse_time(payload.get("deployed_at"), "deployed_at")
        validated_at, validated_error = _parse_time(payload.get("validated_at"), "validated_at")
        if deployed_error:
            errors.append(deployed_error)
        if validated_error:
            errors.append(validated_error)
        if deployed_at is not None and validated_at is not None and validated_at < deployed_at:
            errors.append("evidence_predates_deployment")

    device = payload.get("device")
    if not isinstance(device, Mapping):
        errors.append("device_not_table")
    else:
        errors.extend(_missing_fields(device, DEVICE_FIELDS, "device"))
        errors.extend(_unknown_fields(device, DEVICE_FIELDS, "device"))
        if not template:
            physical_text = " ".join(str(device.get(name, "")) for name in DEVICE_FIELDS).lower()
            if device.get("kind") != "physical":
                errors.append("physical_device_required")
            if any(word in physical_text for word in ("playwright", "virtual", "emulated")):
                errors.append("simulated_device_not_admissible")
            if device.get("installed_pwa") is not True:
                errors.append("installed_pwa_not_verified")

    rollback = payload.get("rollback")
    if not isinstance(rollback, Mapping):
        errors.append("rollback_not_table")
    else:
        errors.extend(_missing_fields(rollback, ROLLBACK_FIELDS, "rollback"))
        errors.extend(_unknown_fields(rollback, ROLLBACK_FIELDS, "rollback"))
        if rollback.get("status") not in STATUS_VALUES:
            errors.append("invalid_status:rollback")
        if not template:
            rollback_hash = rollback.get("evidence_sha256")
            if not isinstance(rollback_hash, str) or SHA256.fullmatch(rollback_hash) is None:
                errors.append("rollback_evidence_hash_invalid")
            _, timestamp_error = _parse_time(rollback.get("validated_at"), "rollback.validated_at")
            if timestamp_error:
                errors.append(timestamp_error)
            if rollback.get("status") != "PASS_VERIFIED":
                errors.append("rollback_not_verified")

    raw_cases = payload.get("case")
    seen: set[str] = set()
    if not isinstance(raw_cases, list):
        errors.append("cases_not_array")
        raw_cases = []
    for index, raw_case in enumerate(raw_cases):
        scope = f"case[{index}]"
        if not isinstance(raw_case, Mapping):
            errors.append(f"case_not_table:{index}")
            continue
        errors.extend(_missing_fields(raw_case, CASE_FIELDS, scope))
        errors.extend(_unknown_fields(raw_case, CASE_FIELDS, scope))
        case_id = raw_case.get("id")
        if not isinstance(case_id, str) or case_id not in REQUIRED_CASES:
            errors.append(f"unknown_case:{case_id}")
        elif case_id in seen:
            errors.append(f"duplicate_case:{case_id}")
        else:
            seen.add(case_id)
        case_status = raw_case.get("status")
        if case_status not in STATUS_VALUES:
            errors.append(f"invalid_status:{scope}")
        if not template:
            case_hash = raw_case.get("evidence_sha256")
            if not isinstance(case_hash, str) or SHA256.fullmatch(case_hash) is None:
                errors.append(f"case_evidence_hash_invalid:{case_id}")
            _, timestamp_error = _parse_time(raw_case.get("executed_at"), f"{scope}.executed_at")
            if timestamp_error:
                errors.append(timestamp_error)
            if case_status != "PASS_VERIFIED":
                errors.append(f"required_case_not_verified:{case_id}")

    for missing_case in sorted(REQUIRED_CASES - seen):
        errors.append(f"missing_case:{missing_case}")

    if not template and status != "PASS_VERIFIED":
        errors.append("runtime_status_not_pass_verified")
    return sorted(set(errors))


def load_and_validate(path: Path, *, allow_template: bool = False) -> list[str]:
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [f"input_unreadable:{exc}"]
    return validate(payload, allow_template=allow_template)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence",
        type=Path,
        default=HERE / "auth-runtime-evidence.example.toml",
    )
    parser.add_argument(
        "--allow-template",
        action="store_true",
        help="validate only the inert checked-in template; never establishes PASS_VERIFIED",
    )
    args = parser.parse_args(argv)
    errors = load_and_validate(args.evidence, allow_template=args.allow_template)
    if errors:
        print("auth-runtime-evidence refused: " + ", ".join(errors), file=sys.stderr)
        return 1
    if args.allow_template:
        print("auth-runtime-evidence: TEMPLATE_VALID_NOT_RUNTIME_EVIDENCE")
    else:
        print("auth-runtime-evidence: EVIDENCE_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
