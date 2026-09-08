"""AUTH-IMP-WP10 offline runtime-evidence contract tests."""

from __future__ import annotations

import copy
import importlib.util
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "ops" / "nas" / "validate-auth-runtime-evidence.py"
TEMPLATE = ROOT / "ops" / "nas" / "auth-runtime-evidence.example.toml"
RUNBOOK = ROOT / "ops" / "runbooks" / "auth-runtime-validation.md"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validate_auth_runtime_evidence", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _template() -> dict[str, Any]:
    return tomllib.loads(TEMPLATE.read_text(encoding="utf-8"))


def _valid_evidence() -> dict[str, Any]:
    payload = _template()
    commit = "a" * 40
    tree = "b" * 40
    payload.update(
        {
            "status": "PASS_VERIFIED",
            "repository_commit": commit,
            "repository_tree": tree,
            "reviewed_commit": commit,
            "reviewed_tree": tree,
            "migration_head": "c5b71e0a8d43",
            "deployment_manifest_sha256": "c" * 64,
            "deployed_at": "2026-09-07T14:00:00Z",
            "validated_at": "2026-09-07T15:00:00Z",
        }
    )
    payload["device"] = {
        "kind": "physical",
        "platform": "iPhone",
        "os_version": "example-version",
        "browser": "Safari",
        "browser_version": "example-version",
        "installed_pwa": True,
    }
    payload["rollback"] = {
        "status": "PASS_VERIFIED",
        "evidence_sha256": "d" * 64,
        "validated_at": "2026-09-07T14:30:00Z",
    }
    for index, case in enumerate(payload["case"]):
        case.update(
            {
                "status": "PASS_VERIFIED",
                "evidence_sha256": f"{index + 1:064x}",
                "executed_at": "2026-09-07T14:30:00Z",
                "notes": "Redacted result; evidence retained in the authorized boundary.",
            }
        )
    return payload


def test_checked_in_template_is_inert_and_requires_explicit_template_mode() -> None:
    validator = _module()
    payload = _template()
    assert validator.validate(payload, allow_template=True) == []
    assert "template_requires_allow_template" in validator.validate(payload)
    assert payload["status"] == "NOT_PERFORMED_OPERATOR_GATED"
    assert all(case["status"] != "PASS_VERIFIED" for case in payload["case"])


def test_template_cli_never_reports_runtime_pass() -> None:
    completed = subprocess.run(  # noqa: S603
        [str(VALIDATOR), "--evidence", str(TEMPLATE), "--allow-template"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "auth-runtime-evidence: TEMPLATE_VALID_NOT_RUNTIME_EVIDENCE"
    assert "PASS_VERIFIED" not in completed.stdout


def test_complete_redacted_physical_evidence_validates() -> None:
    validator = _module()
    assert validator.validate(_valid_evidence()) == []


def test_validator_refuses_identity_time_case_and_rollback_failures() -> None:
    validator = _module()
    payload = _valid_evidence()
    payload["repository_commit"] = "short"
    payload["reviewed_tree"] = "e" * 40
    payload["canonical_origin"] = "https://private.invalid"
    payload["webauthn_rp_id"] = "private.invalid"
    payload["validated_at"] = "2026-09-07T13:00:00Z"
    payload["rollback"]["status"] = "FAILED"
    payload["case"][0]["status"] = "BLOCKED"
    errors = validator.validate(payload)
    assert "repository_commit_not_full_hex" in errors
    assert "reviewed_commit_mismatch" in errors
    assert "reviewed_tree_mismatch" in errors
    assert "canonical_origin_mismatch" in errors
    assert "webauthn_rp_id_mismatch" in errors
    assert "evidence_predates_deployment" in errors
    assert "rollback_not_verified" in errors
    assert "required_case_not_verified:bootstrap" in errors


def test_validator_refuses_missing_duplicate_unknown_and_invalid_status() -> None:
    validator = _module()
    payload = _valid_evidence()
    del payload["migration_head"]
    payload["unexpected"] = "field"
    payload["case"].append(copy.deepcopy(payload["case"][0]))
    payload["case"][0]["status"] = "GREEN"
    payload["case"] = [case for case in payload["case"] if case["id"] != "grant_expiry"]
    errors = validator.validate(payload)
    assert "missing_field:root.migration_head" in errors
    assert "unknown_field:root.unexpected" in errors
    assert "duplicate_case:bootstrap" in errors
    assert "invalid_status:case[0]" in errors
    assert "missing_case:grant_expiry" in errors


def test_validator_refuses_simulated_devices_and_secret_shaped_content() -> None:
    validator = _module()
    payload = _valid_evidence()
    payload["device"]["kind"] = "virtual"
    payload["device"]["browser"] = "Playwright WebKit"
    payload["case"][0]["notes"] = "Cookie: mypa_session=do-not-store-this"
    payload["rollback"]["secret"] = "do-not-store-this"  # noqa: S105 - planted leak
    errors = validator.validate(payload)
    assert "physical_device_required" in errors
    assert "simulated_device_not_admissible" in errors
    assert "secret_shaped_value:root.case[0].notes" in errors
    assert "secret_shaped_key:root.rollback.secret" in errors


def test_runbook_preserves_operator_gate_and_canonical_origin() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "NOT_PERFORMED_OPERATOR_GATED" in text
    assert "https://pa.bobby-fetting.me" in text
    assert "Playwright" in text
    assert "cannot satisfy" in text
    assert "separate operator authority" in text
    assert "Do not destructively downgrade auth data" in text.replace("\n", " ")
