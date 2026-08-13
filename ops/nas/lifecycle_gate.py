#!/usr/bin/env python3
"""Fail-closed NAS lifecycle and pilot restart-policy validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
import tomllib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from nas_tools import docker

RUNTIME_SERVICES = {
    "postgres",
    "gateway",
    "worker-enrollment",
    "worker-capture",
    "web",
    "proxy",
}
GIT_OBJECT = re.compile(r"[0-9a-f]{40}\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TRUSTED_EVIDENCE_ROOT = Path("/etc/my-pa/pilot-evidence")
RUNTIME_ADMISSION = Path("/etc/my-pa/runtime-admission.toml")
TRUSTED_FILES = {
    "trust.toml",
    "operator-public-key.pem",
    "nas-10-acceptance.toml",
    "nas-10-acceptance.sig",
    "pilot-activation.toml",
    "pilot-activation.sig",
}


def _yaml(path: Path) -> dict[str, Any] | None:
    """Parse the closed service/restart shape without a host YAML runtime."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    top_level = {
        line[:-1]
        for line in lines
        if line and not line.startswith((" ", "#")) and line.endswith(":")
    }
    services: dict[str, dict[str, Any]] = {}
    in_services = False
    current = ""
    for line in lines:
        if line == "services:":
            in_services = True
            continue
        if in_services and line and not line.startswith(" "):
            in_services = False
        if not in_services:
            continue
        service = re.fullmatch(r"  ([a-z0-9-]+):", line)
        if service:
            current = service.group(1)
            services[current] = {}
            continue
        restart = re.fullmatch(r'    restart: (?:"([^"]+)"|([^ ]+))', line)
        if restart and current:
            services[current]["restart"] = restart.group(1) or restart.group(2)
    if "services" not in top_level:
        return None
    return {"services": services, "_top_level": top_level}


def _git(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - fixed git command assembled below
        command, check=True, capture_output=True, text=True
    ).stdout.strip()


def _timestamp(value: object) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() is not None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted_files(root: Path, owner_uid: int) -> tuple[dict[str, Path], list[str]]:
    errors: list[str] = []
    try:
        root_status = root.lstat()
        if (
            not stat.S_ISDIR(root_status.st_mode)
            or root_status.st_uid != owner_uid
            or stat.S_IMODE(root_status.st_mode) != 0o700
            or root.resolve(strict=True) != root
        ):
            errors.append("trusted_evidence_directory")
    except OSError:
        return {}, ["trusted_evidence_directory"]
    files = {name: root / name for name in TRUSTED_FILES}
    for name, path in files.items():
        try:
            status = path.lstat()
            if (
                not stat.S_ISREG(status.st_mode)
                or status.st_uid != owner_uid
                or stat.S_IMODE(status.st_mode) != 0o400
                or status.st_nlink != 1
                or path.resolve(strict=True).parent != root
            ):
                errors.append(f"trusted_{name}_metadata")
        except OSError:
            errors.append(f"trusted_{name}_metadata")
    return files, errors


def _verify_signature(public_key: Path, artifact: Path, signature: Path) -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - fixed OpenSSL verification command
            [
                "/usr/bin/openssl",
                "dgst",
                "-sha256",
                "-verify",
                str(public_key),
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


def _strong_rsa_public_key(public_key: Path) -> bool:
    try:
        result = subprocess.run(  # noqa: S603 - fixed OpenSSL public-key inspection
            ["/usr/bin/openssl", "rsa", "-pubin", "-in", str(public_key), "-text", "-noout"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    match = re.search(r"Public-Key:\s*\((\d+) bit\)", result.stdout)
    return result.returncode == 0 and match is not None and int(match.group(1)) >= 3072


def _private_tailnet_origin(value: object) -> bool:
    try:
        parsed = urlsplit(str(value))
        port = parsed.port
    except ValueError:
        return False
    hostname = parsed.hostname or ""
    labels = hostname.split(".")
    valid_dns_name = (
        len(hostname) <= 253
        and len(labels) >= 3
        and labels[-2:] == ["ts", "net"]
        and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
    )
    return (
        parsed.scheme == "https"
        and valid_dns_name
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    )


def verify(
    compose_path: Path,
    pilot_overlay_path: Path,
    *,
    image_manifest_path: Path | None = None,
    pilot: bool = False,
    live: bool = False,
    runner: Callable[[list[str]], str] = _git,
    trusted_root: Path = TRUSTED_EVIDENCE_ROOT,
    trusted_owner_uid: int = 0,
    runtime_admission_path: Path = RUNTIME_ADMISSION,
    verified_origin: list[str] | None = None,
) -> list[str]:
    try:
        compose = _yaml(compose_path)
        overlay = _yaml(pilot_overlay_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return ["compose_unreadable"]
    if compose is None or overlay is None:
        return ["compose_unreadable"]
    errors: list[str] = []
    services = compose.get("services", {})
    if not isinstance(services, dict) or set(services) != RUNTIME_SERVICES:
        errors.append("smoke_service_set")
    elif any(
        not isinstance(service, dict) or service.get("restart") != "no"
        for service in services.values()
    ):
        errors.append("smoke_restart_policy")
    pilot_services = overlay.get("services", {})
    if not isinstance(pilot_services, dict) or set(pilot_services) != RUNTIME_SERVICES:
        errors.append("pilot_service_set")
    elif any(service != {"restart": "unless-stopped"} for service in pilot_services.values()):
        errors.append("pilot_overlay_scope")
    if overlay.get("_top_level") != {"services"}:
        errors.append("pilot_overlay_scope")
    repository = Path(__file__).resolve().parents[2]
    if (
        compose_path.resolve() != repository / "ops/nas/compose.example.yml"
        or pilot_overlay_path.resolve() != repository / "ops/nas/compose.pilot.example.yml"
    ):
        errors.append("runtime_contract_path")
    runtime_contract = repository / "ops/nas/runtime-contract.toml"
    if image_manifest_path is None:
        return [*errors, "image_manifest_required"]
    try:
        image_manifest = tomllib.loads(image_manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return [*errors, "image_manifest_unreadable"]
    manifest_commit = str(image_manifest.get("repository_commit", ""))
    manifest_tree = str(image_manifest.get("repository_tree", ""))
    if (
        image_manifest.get("schema") != "my-pa.nas-image-manifest.v1"
        or image_manifest.get("status") != "deployable"
        or not GIT_OBJECT.fullmatch(manifest_commit)
        or not GIT_OBJECT.fullmatch(manifest_tree)
    ):
        errors.append("image_manifest_identity")
    if not live:
        return [*errors, "live_identity_required"]
    try:
        head = runner(["git", "-C", str(repository), "rev-parse", "HEAD"])
        tree = runner(["git", "-C", str(repository), "rev-parse", "HEAD^{tree}"])
        dirty = runner(["git", "-C", str(repository), "status", "--porcelain"])
        docker_info = json.loads(runner([docker(), "info", "--format", "{{json .}}"]))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return [*errors, "live_identity_unreadable"]
    if head != manifest_commit or tree != manifest_tree:
        errors.append("repository_image_drift")
    if dirty:
        errors.append("repository_dirty")
    if (
        not isinstance(docker_info, dict)
        or docker_info.get("ID") != image_manifest.get("docker_engine_id")
        or docker_info.get("Name") != image_manifest.get("docker_engine_name")
    ):
        errors.append("image_engine_drift")
    if errors or not pilot:
        return errors

    if not runtime_admission_path.is_file():
        return [*errors, "runtime_admission_unreadable"]
    try:
        runtime_admission = tomllib.loads(runtime_admission_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return [*errors, "runtime_admission_unreadable"]
    resolved_digests = runtime_admission.get("resolved_compose_sha256", {})
    resolved_compose_digest = (
        str(resolved_digests.get("pilot", "")) if isinstance(resolved_digests, dict) else ""
    )
    if not HEX_SHA256.fullmatch(resolved_compose_digest):
        errors.append("runtime_admission_resolved_digest")

    files, trust_errors = _trusted_files(trusted_root, trusted_owner_uid)
    errors.extend(trust_errors)
    if trust_errors:
        return errors
    try:
        trust = tomllib.loads(files["trust.toml"].read_text(encoding="utf-8"))
        acceptance = tomllib.loads(files["nas-10-acceptance.toml"].read_text(encoding="utf-8"))
        activation = tomllib.loads(files["pilot-activation.toml"].read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return [*errors, "trusted_evidence_unreadable"]
    public_key_digest = _sha256(files["operator-public-key.pem"])
    if trust != {
        "schema": "my-pa.nas-pilot-trust.v1",
        "status": "provisioned",
        "operator_public_key_sha256": public_key_digest,
        "nas_engine_id": docker_info.get("ID"),
        "nas_engine_name": docker_info.get("Name"),
    } or not HEX_SHA256.fullmatch(public_key_digest):
        errors.append("trusted_operator_binding")
    if not _strong_rsa_public_key(files["operator-public-key.pem"]):
        errors.append("operator_key_strength")
    if not _verify_signature(
        files["operator-public-key.pem"],
        files["nas-10-acceptance.toml"],
        files["nas-10-acceptance.sig"],
    ):
        errors.append("nas_10_signature")
    if not _verify_signature(
        files["operator-public-key.pem"],
        files["pilot-activation.toml"],
        files["pilot-activation.sig"],
    ):
        errors.append("operator_activation_signature")
    acceptance_commit = str(acceptance.get("repository_commit", ""))
    acceptance_tree = str(acceptance.get("repository_tree", ""))
    try:
        completed_at = datetime.fromisoformat(
            str(acceptance.get("completed_at")).replace("Z", "+00:00")
        )
        activated_at = datetime.fromisoformat(
            str(activation.get("activated_at")).replace("Z", "+00:00")
        )
        chronological = completed_at <= activated_at
    except ValueError:
        chronological = False
    compose_digest = _sha256(compose_path)
    runtime_contract_digest = _sha256(runtime_contract)
    image_manifest_digest = _sha256(image_manifest_path)
    if (
        set(acceptance)
        != {
            "schema",
            "status",
            "repository_commit",
            "repository_tree",
            "reviewed_head",
            "completed_at",
            "nas_engine_id",
            "nas_engine_name",
            "compose_sha256",
            "runtime_contract_sha256",
            "image_manifest_sha256",
            "runtime_admission_sha256",
            "resolved_compose_sha256",
        }
        or acceptance.get("schema") != "my-pa.nas-10-acceptance.v1"
        or acceptance.get("status") != "pass"
        or not GIT_OBJECT.fullmatch(acceptance_commit)
        or not GIT_OBJECT.fullmatch(acceptance_tree)
        or acceptance.get("reviewed_head") != acceptance_commit
        or not _timestamp(acceptance.get("completed_at"))
        or acceptance.get("nas_engine_id") != docker_info.get("ID")
        or acceptance.get("nas_engine_name") != docker_info.get("Name")
        or acceptance.get("compose_sha256") != compose_digest
        or acceptance.get("runtime_contract_sha256") != runtime_contract_digest
        or acceptance.get("image_manifest_sha256") != image_manifest_digest
        or acceptance.get("runtime_admission_sha256") != _sha256(runtime_admission_path)
        or acceptance.get("resolved_compose_sha256") != resolved_compose_digest
    ):
        errors.append("nas_10_acceptance")
    if (
        set(activation)
        != {
            "schema",
            "status",
            "repository_commit",
            "repository_tree",
            "activated_at",
            "activated_by",
            "canonical_origin",
            "acceptance_sha256",
            "nas_engine_id",
            "nas_engine_name",
            "compose_sha256",
            "runtime_contract_sha256",
            "image_manifest_sha256",
            "runtime_admission_sha256",
            "resolved_compose_sha256",
        }
        or activation.get("schema") != "my-pa.nas-pilot-activation.v1"
        or activation.get("status") != "activated"
        or activation.get("repository_commit") != acceptance_commit
        or activation.get("repository_tree") != acceptance_tree
        or not _timestamp(activation.get("activated_at"))
        or not str(activation.get("activated_by", "")).strip()
        or not _private_tailnet_origin(activation.get("canonical_origin"))
        or not chronological
        or activation.get("acceptance_sha256") != _sha256(files["nas-10-acceptance.toml"])
        or activation.get("nas_engine_id") != docker_info.get("ID")
        or activation.get("nas_engine_name") != docker_info.get("Name")
        or activation.get("compose_sha256") != compose_digest
        or activation.get("runtime_contract_sha256") != runtime_contract_digest
        or activation.get("image_manifest_sha256") != image_manifest_digest
        or activation.get("runtime_admission_sha256") != _sha256(runtime_admission_path)
        or activation.get("resolved_compose_sha256") != resolved_compose_digest
    ):
        errors.append("operator_activation")
    if head != acceptance_commit or tree != acceptance_tree:
        errors.append("repository_identity_drift")
    if not errors and verified_origin is not None:
        verified_origin.append(str(activation["canonical_origin"]).rstrip("/"))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("compose", type=Path)
    parser.add_argument("pilot_overlay", type=Path)
    parser.add_argument("--image-manifest", required=True, type=Path)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--print-verified-origin", action="store_true")
    args = parser.parse_args()
    verified_origin: list[str] = []
    errors = verify(
        args.compose,
        args.pilot_overlay,
        image_manifest_path=args.image_manifest,
        pilot=args.pilot,
        live=args.live,
        verified_origin=verified_origin if args.print_verified_origin else None,
    )
    if errors:
        print(
            "NAS lifecycle gate refused: " + ", ".join(dict.fromkeys(errors)),
            file=sys.stderr,
        )
        return 1
    if args.print_verified_origin:
        if not args.pilot or len(verified_origin) != 1:
            print(
                "NAS lifecycle gate refused: verified origin requires admitted pilot",
                file=sys.stderr,
            )
            return 1
        print(verified_origin[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
