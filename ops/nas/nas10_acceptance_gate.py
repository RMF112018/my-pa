#!/usr/bin/env python3
"""Issue an unsigned NAS-10 PASS candidate from complete synthetic evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
REQUIRED_CASES = {
    "architecture_boundaries",
    "platform_image_runtime",
    "storage_permissions",
    "remote_capture_socket",
    "remote_capture_durable_transaction",
    "cross_principal_database",
    "backup_restore_health",
    "gateway_workers_pwa",
    "proxy_private_origin",
    "principal_isolation",
    "apple_grant_adversarial",
    "goodnotes_ocr_read_only",
    "frontier_mcp_stdio",
    "scratch_stack_restart_bytes",
    "lifecycle_restart_rollback_emergency",
    "diagnostics_and_no_activation",
}
REVIEW_TRUST = Path("/etc/my-pa/nas10-review-trust.toml")
EVIDENCE_ROOT = Path("/var/lib/my-pa/nas10-evidence")
RUNTIME_SERVICES = {"postgres", "gateway", "worker-enrollment", "worker-capture", "web", "proxy"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _protected_root(path: Path, owner_uid: int, expected: Path) -> bool:
    try:
        metadata = path.lstat()
        return (
            path == expected
            and stat.S_ISDIR(metadata.st_mode)
            and metadata.st_uid == owner_uid
            and stat.S_IMODE(metadata.st_mode) == 0o700
            and metadata.st_nlink >= 1
            and path.resolve(strict=True) == path
        )
    except OSError:
        return False


def _trusted_file_path(path: Path, owner_uid: int) -> bool:
    try:
        metadata = path.lstat()
        return (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == owner_uid
            and stat.S_IMODE(metadata.st_mode) == 0o400
            and metadata.st_nlink == 1
            and path.resolve(strict=True) == path
        )
    except OSError:
        return False


def _read_once(path: Path, owner_uid: int, limit: int = 10 * 1024 * 1024) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not (
            stat.S_ISREG(before.st_mode)
            and before.st_uid == owner_uid
            and stat.S_IMODE(before.st_mode) == 0o400
            and before.st_nlink == 1
            and before.st_size <= limit
        ):
            raise OSError("untrusted evidence metadata")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(data) > limit or (before.st_dev, before.st_ino, before.st_size) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise OSError("evidence changed during snapshot")
        return data
    finally:
        os.close(descriptor)


def _exclusive_write(path: Path, data: bytes, owner_uid: int) -> None:
    parent = path.parent
    parent_status = parent.lstat()
    if not (
        path.is_absolute()
        and path.name not in {"", ".", ".."}
        and path == parent / path.name
        and parent.resolve(strict=True) == parent
        and stat.S_ISDIR(parent_status.st_mode)
        and parent_status.st_uid == owner_uid
        and stat.S_IMODE(parent_status.st_mode) == 0o700
    ):
        raise OSError("unsafe output parent")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o400)
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == owner_uid
            and stat.S_IMODE(metadata.st_mode) == 0o400
            and metadata.st_nlink == 1
        ):
            raise OSError("unsafe output metadata")
    finally:
        os.close(descriptor)
    directory = os.open(parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _image_gate() -> ModuleType:
    path = Path(__file__).with_name("image_gate.py")
    spec = importlib.util.spec_from_file_location("nas10_image_shape", path)
    if spec is None or spec.loader is None:
        raise ImportError
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - caller supplies bounded git inspection commands
        command, check=True, capture_output=True, text=True
    ).stdout.strip()


def _signature(key: Path, artifact: Path, signature: Path) -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - fixed OpenSSL verification
            [
                "/usr/bin/openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(key),
                "-signature",
                str(signature),
                str(artifact),
            ],
            check=False,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def _strong_key(key: Path) -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - fixed public-key inspection
            ["/usr/bin/openssl", "rsa", "-pubin", "-in", str(key), "-text", "-noout"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    match = re.search(r"Public-Key:\s*\((\d+) bit\)", result.stdout)
    return result.returncode == 0 and match is not None and int(match.group(1)) >= 3072


def verify(
    evidence_path: Path,
    review_path: Path,
    review_signature: Path,
    reviewer_key: Path,
    image_manifest: Path,
    runtime_admission: Path,
    *,
    review_trust: Path = REVIEW_TRUST,
    expected_evidence_root: Path = EVIDENCE_ROOT,
    trusted_owner_uid: int = 0,
    runner: Callable[[list[str]], str] = _git,
) -> tuple[list[str], dict[str, str]]:
    errors: list[str] = []
    repository = Path(__file__).resolve().parents[2]
    matrix = repository / "ops/nas/acceptance-matrix.toml"
    compose = repository / "ops/nas/compose.example.yml"
    contract = repository / "ops/nas/runtime-contract.toml"
    evidence_root = evidence_path.parent
    required_locations = {
        evidence_path: "evidence.json",
        review_path: "independent-review.toml",
        review_signature: "independent-review.sig",
        reviewer_key: "reviewer-public.pem",
    }
    if not _protected_root(evidence_root, trusted_owner_uid, expected_evidence_root) or any(
        path.parent != evidence_root or path.name != name
        for path, name in required_locations.items()
    ):
        return ["protected_evidence_root"], {}
    try:
        expected_names = {
            "evidence.json",
            "independent-review.toml",
            "independent-review.sig",
            "reviewer-public.pem",
            *{f"{name}.json" for name in REQUIRED_CASES},
            *{f"{name}.log" for name in REQUIRED_CASES},
        }
        if {path.name for path in evidence_root.iterdir()} != expected_names:
            return ["protected_evidence_file_set"], {}
    except OSError:
        return ["protected_evidence_file_set"], {}
    if not all(
        _trusted_file_path(path, trusted_owner_uid)
        for path in (review_trust, image_manifest, runtime_admission)
    ):
        return ["protected_identity_input"], {}
    try:
        evidence_bytes = _read_once(evidence_path, trusted_owner_uid)
        review_bytes = _read_once(review_path, trusted_owner_uid)
        signature_bytes = _read_once(review_signature, trusted_owner_uid)
        key_bytes = _read_once(reviewer_key, trusted_owner_uid)
        trust_bytes = _read_once(review_trust, trusted_owner_uid)
        image_bytes = _read_once(image_manifest, trusted_owner_uid)
        admission_bytes = _read_once(runtime_admission, trusted_owner_uid)
        evidence = json.loads(evidence_bytes)
        review = tomllib.loads(review_bytes.decode())
        trust = tomllib.loads(trust_bytes.decode())
        image = tomllib.loads(image_bytes.decode())
        admission = tomllib.loads(admission_bytes.decode())
        head = runner(["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD"])
        tree = runner(["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD^{tree}"])
        dirty = runner(["/usr/bin/git", "-C", str(repository), "status", "--porcelain"])
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
        UnicodeDecodeError,
        subprocess.SubprocessError,
    ):
        return ["acceptance_input"], {}
    if dirty or not HEX40.fullmatch(head) or not HEX40.fullmatch(tree):
        errors.append("repository_not_exact_clean_head")
    matrix_sha = _sha(matrix)
    results = evidence.get("results", {})
    identity = {
        "repository_commit": head,
        "repository_tree": tree,
        "nas_engine_id": str(image.get("docker_engine_id", "")),
        "nas_engine_name": str(image.get("docker_engine_name", "")),
    }
    if (
        evidence.get("schema") != "my-pa.nas-10-evidence.v1"
        or evidence.get("status") != "complete"
        or evidence.get("synthetic") is not True
        or evidence.get("activation_performed") is not False
        or evidence.get("matrix_sha256") != matrix_sha
        or evidence.get("image_manifest_sha256") != _digest(image_bytes)
        or evidence.get("runtime_admission_sha256") != _digest(admission_bytes)
        or evidence.get("resolved_compose_sha256")
        != admission.get("resolved_compose_sha256", {}).get("pilot")
        or any(evidence.get(key) != value for key, value in identity.items())
        or not isinstance(results, dict)
        or set(results) != REQUIRED_CASES
    ):
        errors.append("evidence_manifest")
    matrix_cases = tomllib.loads(matrix.read_text()).get("cases", {})
    for name in REQUIRED_CASES:
        result_path = evidence_path.parent / f"{name}.json"
        log_path = evidence_path.parent / f"{name}.log"
        try:
            result_bytes = _read_once(result_path, trusted_owner_uid)
            log_bytes = _read_once(log_path, trusted_owner_uid)
            result = json.loads(result_bytes)
            result_digest = _digest(result_bytes)
            log_digest = _digest(log_bytes)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            errors.append(f"case_{name}")
            continue
        case = matrix_cases[name]
        expected_command = (
            ["external_device", name]
            if case["requirement"] == "external_device"
            else [
                "python3",
                "-m",
                "pytest",
                "--import-mode=importlib",
                "-q",
                *case["selectors"],
            ]
        )
        external_device = case["requirement"] == "external_device"
        if (
            results.get(name) != result_digest
            or result.get("schema") != "my-pa.nas-10-case-result.v1"
            or result.get("case") != name
            or result.get("status") != "pass"
            or result.get("synthetic") is not True
            or result.get("activation_performed") is not False
            or any(result.get(key) != value for key, value in identity.items())
            or result.get("requirement") != case["requirement"]
            or result.get("behaviors") != case["behaviors"]
            or result.get("command") != expected_command
            or result.get("external_device_verified") != external_device
            or (
                external_device
                and (
                    result.get("external_harness") != "my-pa.nas10-external-device.v1"
                    or result.get("disposable_engine_ack") != "ACKNOWLEDGE_DISPOSABLE_DOCKER_ENGINE"
                    or result.get("image_manifest_sha256") != _digest(image_bytes)
                    or result.get("runtime_admission_sha256") != _digest(admission_bytes)
                    or result.get("resolved_compose_sha256")
                    != admission.get("resolved_compose_sha256", {}).get("pilot")
                )
            )
            or not HEX64.fullmatch(str(result.get("output_sha256", "")))
            or result.get("output_sha256") != log_digest
            or b"postgresql://" in log_bytes.lower()
            or b"postgres://" in log_bytes.lower()
        ):
            errors.append(f"case_{name}")
    pilot_digest = admission.get("resolved_compose_sha256", {}).get("pilot", "")
    try:
        image_errors = _image_gate()._shape_errors(image)
    except (AttributeError, ImportError):
        image_errors = ["validator"]
    service_images = admission.get("service_images", {})
    service_ids = admission.get("service_image_ids", {})
    manifest_images = image.get("images", {})
    if not isinstance(manifest_images, dict):
        manifest_images = {}
    expected_ids = {
        "postgres": manifest_images.get("postgres", {}).get("docker_image_id"),
        "gateway": manifest_images.get("app", {}).get("docker_image_id"),
        "worker-enrollment": manifest_images.get("app", {}).get("docker_image_id"),
        "worker-capture": manifest_images.get("app", {}).get("docker_image_id"),
        "web": manifest_images.get("web", {}).get("docker_image_id"),
    }
    if (
        image_errors
        or image.get("repository_commit") != head
        or image.get("repository_tree") != tree
        or set(admission)
        != {
            "schema",
            "status",
            "docker_engine_id",
            "docker_engine_name",
            "image_manifest_sha256",
            "resolved_compose_sha256",
            "service_images",
            "service_image_ids",
        }
        or admission.get("schema") != "my-pa.nas-runtime-admission.v1"
        or admission.get("status") != "admitted"
        or admission.get("docker_engine_id") != identity["nas_engine_id"]
        or admission.get("docker_engine_name") != identity["nas_engine_name"]
        or admission.get("image_manifest_sha256") != _digest(image_bytes)
        or set(admission.get("resolved_compose_sha256", {})) != {"smoke", "pilot"}
        or not isinstance(service_images, dict)
        or set(service_images) != RUNTIME_SERVICES
        or not isinstance(service_ids, dict)
        or set(service_ids) != RUNTIME_SERVICES
        or any(not SHA256.fullmatch(str(value)) for value in service_ids.values())
        or any(service_ids.get(name) != value for name, value in expected_ids.items())
        or any(
            service_images.get(name) != service_ids.get(name)
            for name in RUNTIME_SERVICES - {"proxy"}
        )
        or not SHA256.fullmatch(str(service_images.get("proxy", "")).rpartition("@")[2])
        or not HEX64.fullmatch(str(pilot_digest))
    ):
        errors.append("runtime_identity")
    with tempfile.TemporaryDirectory(prefix="nas10-review-") as temporary:
        snapshot_root = Path(temporary)
        snapshot_key = snapshot_root / "reviewer-public.pem"
        snapshot_review = snapshot_root / "independent-review.toml"
        snapshot_signature = snapshot_root / "independent-review.sig"
        snapshot_key.write_bytes(key_bytes)
        snapshot_review.write_bytes(review_bytes)
        snapshot_signature.write_bytes(signature_bytes)
        strong_key = _strong_key(snapshot_key)
        signature_valid = _signature(snapshot_key, snapshot_review, snapshot_signature)
    if (
        trust
        != {
            "schema": "my-pa.nas-10-review-trust.v1",
            "status": "provisioned",
            "reviewer_public_key_sha256": _digest(key_bytes),
        }
        or not strong_key
        or not signature_valid
    ):
        errors.append("independent_review_signature")
    if (
        review
        != {
            "schema": "my-pa.nas-10-independent-review.v1",
            "status": "pass",
            "independent": True,
            "reviewer_context": review.get("reviewer_context"),
            "reviewed_head": head,
            "reviewed_tree": tree,
            "evidence_sha256": _digest(evidence_bytes),
            "matrix_sha256": matrix_sha,
            "nas_engine_id": identity["nas_engine_id"],
            "nas_engine_name": identity["nas_engine_name"],
            "image_manifest_sha256": _digest(image_bytes),
            "runtime_admission_sha256": _digest(admission_bytes),
            "resolved_compose_sha256": str(pilot_digest),
        }
        or not str(review.get("reviewer_context", "")).strip()
    ):
        errors.append("independent_exact_head_review")
    candidate = {
        "schema": "my-pa.nas-10-acceptance.v1",
        "status": "pass",
        "repository_commit": head,
        "repository_tree": tree,
        "reviewed_head": head,
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "nas_engine_id": identity["nas_engine_id"],
        "nas_engine_name": identity["nas_engine_name"],
        "compose_sha256": _sha(compose),
        "runtime_contract_sha256": _sha(contract),
        "image_manifest_sha256": _digest(image_bytes),
        "runtime_admission_sha256": _digest(admission_bytes),
        "resolved_compose_sha256": str(pilot_digest),
    }
    return errors, candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("review_signature", type=Path)
    parser.add_argument("reviewer_key", type=Path)
    parser.add_argument("image_manifest", type=Path)
    parser.add_argument("runtime_admission", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    errors, candidate = verify(
        args.evidence,
        args.review,
        args.review_signature,
        args.reviewer_key,
        args.image_manifest,
        args.runtime_admission,
    )
    if errors:
        print("NAS-10 acceptance refused: " + ", ".join(dict.fromkeys(errors)), file=sys.stderr)
        return 1
    payload = (
        "\n".join(f"{key} = {json.dumps(value)}" for key, value in candidate.items()) + "\n"
    ).encode()
    try:
        _exclusive_write(args.output, payload, 0)
    except OSError:
        print("NAS-10 acceptance refused: unsafe or existing output", file=sys.stderr)
        return 1
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
