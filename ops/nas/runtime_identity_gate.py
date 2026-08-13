#!/usr/bin/env python3
"""Bind resolved Compose and running services to an exact admitted image bundle."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from nas_tools import docker

SERVICES = {
    "postgres",
    "gateway",
    "worker-enrollment",
    "worker-capture",
    "web",
    "proxy",
}
APP_SERVICES = {"gateway", "worker-enrollment", "worker-capture"}
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CANONICAL_ADMISSION = Path("/etc/my-pa/runtime-admission.toml")


def _image_gate() -> ModuleType:
    path = Path(__file__).with_name("image_gate.py")
    spec = importlib.util.spec_from_file_location("nas_image_gate_for_runtime", path)
    if spec is None or spec.loader is None:
        raise ImportError
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - bounded Docker/git inspection commands
        command, check=True, capture_output=True, text=True
    ).stdout


def _trusted_file(path: Path, owner_uid: int) -> bool:
    try:
        status = path.lstat()
        return (
            stat.S_ISREG(status.st_mode)
            and status.st_uid == owner_uid
            and stat.S_IMODE(status.st_mode) == 0o400
            and status.st_nlink == 1
            and path.resolve(strict=True) == path
        )
    except OSError:
        return False


def verify(
    compose_path: Path,
    image_manifest_path: Path,
    *,
    pilot_overlay_path: Path | None = None,
    admission_path: Path = CANONICAL_ADMISSION,
    owner_uid: int = 0,
    running: bool = False,
    runner: Callable[[list[str]], str] = _run,
) -> list[str]:
    errors: list[str] = []
    repository = Path(__file__).resolve().parents[2]
    if compose_path.resolve() != repository / "ops/nas/compose.example.yml":
        errors.append("canonical_compose_path")
    if pilot_overlay_path is not None and (
        pilot_overlay_path.resolve() != repository / "ops/nas/compose.pilot.example.yml"
    ):
        errors.append("canonical_pilot_overlay_path")
    if not _trusted_file(admission_path, owner_uid):
        return [*errors, "runtime_admission_metadata"]
    try:
        manifest_bytes = image_manifest_path.read_bytes()
        manifest = tomllib.loads(manifest_bytes.decode())
        admission = tomllib.loads(admission_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return [*errors, "runtime_identity_input"]
    try:
        errors.extend(f"image_manifest_{value}" for value in _image_gate()._shape_errors(manifest))
    except (AttributeError, ImportError):
        return [*errors, "image_manifest_validator"]
    if (
        set(admission)
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
        or admission.get("image_manifest_sha256") != _sha(manifest_bytes)
        or not isinstance(admission.get("resolved_compose_sha256"), dict)
        or set(admission.get("resolved_compose_sha256", {})) != {"smoke", "pilot"}
        or any(
            not HEX_SHA256.fullmatch(str(value))
            for value in admission.get("resolved_compose_sha256", {}).values()
        )
    ):
        errors.append("runtime_admission_shape")
    admitted_images = admission.get("service_images", {})
    admitted_ids = admission.get("service_image_ids", {})
    if (
        not isinstance(admitted_images, dict)
        or set(admitted_images) != SERVICES
        or not isinstance(admitted_ids, dict)
        or set(admitted_ids) != SERVICES
        or any(not SHA256.fullmatch(str(value)) for value in admitted_ids.values())
    ):
        errors.append("runtime_service_image_set")
        return errors
    for name, value in admitted_images.items():
        if name == "proxy":
            if "@sha256:" not in str(value) or not SHA256.fullmatch(str(value).rpartition("@")[2]):
                errors.append("runtime_proxy_digest")
        elif value != admitted_ids[name]:
            errors.append("runtime_service_reference")
    manifest_images = manifest.get("images", {})
    if isinstance(manifest_images, dict):
        expected = {
            "postgres": manifest_images.get("postgres", {}).get("docker_image_id"),
            "gateway": manifest_images.get("app", {}).get("docker_image_id"),
            "worker-enrollment": manifest_images.get("app", {}).get("docker_image_id"),
            "worker-capture": manifest_images.get("app", {}).get("docker_image_id"),
            "web": manifest_images.get("web", {}).get("docker_image_id"),
            "proxy": manifest_images.get("proxy", {}).get("docker_image_id"),
        }
        if any(admitted_ids.get(name) != value for name, value in expected.items()):
            errors.append("runtime_manifest_role_binding")
    try:
        base = [
            docker(),
            "compose",
            "--file",
            str(compose_path),
        ]
        if pilot_overlay_path is not None:
            base.extend(["--file", str(pilot_overlay_path)])
        base.extend(["--profile", "nas-01-contract-only"])
        rendered_text = runner([*base, "config", "--format", "json"])
        rendered = json.loads(rendered_text)
        configured_images = runner([*base, "config", "--images"]).splitlines()
        hash_lines = runner([*base, "config", "--hash", "*"]).splitlines()
        docker_info = json.loads(runner([docker(), "info", "--format", "{{json .}}"]))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return [*errors, "runtime_render_unreadable"]
    canonical_render = json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode()
    mode = "pilot" if pilot_overlay_path is not None else "smoke"
    if admission.get("resolved_compose_sha256", {}).get(mode) != _sha(canonical_render):
        errors.append("runtime_render_drift")
    rendered_services = rendered.get("services", {}) if isinstance(rendered, dict) else {}
    actual_images = {
        name: service.get("image")
        for name, service in rendered_services.items()
        if isinstance(service, dict)
    }
    if set(actual_images) != SERVICES or actual_images != admitted_images:
        errors.append("runtime_render_image_binding")
    if sorted(configured_images) != sorted(admitted_images.values()):
        errors.append("runtime_config_images")
    configured_hashes: dict[str, str] = {}
    for line in hash_lines:
        name, separator, value = line.partition(" ")
        if not separator or not value.strip():
            errors.append("runtime_config_hashes")
            break
        configured_hashes[name] = value.strip()
    if set(configured_hashes) != SERVICES:
        errors.append("runtime_config_hashes")
    if (
        not isinstance(docker_info, dict)
        or docker_info.get("ID") != admission.get("docker_engine_id")
        or docker_info.get("Name") != admission.get("docker_engine_name")
        or docker_info.get("ID") != manifest.get("docker_engine_id")
        or docker_info.get("Name") != manifest.get("docker_engine_name")
    ):
        errors.append("runtime_engine_binding")
    if errors or not running:
        return errors
    for name in sorted(SERVICES):
        try:
            container_id = runner([*base, "ps", "-q", name]).strip()
            inspected = json.loads(runner([docker(), "inspect", container_id]))[0]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, TypeError):
            errors.append(f"{name}_running_identity")
            continue
        if not container_id or inspected.get("Image") != admitted_ids[name]:
            errors.append(f"{name}_running_image")
        labels = (inspected.get("Config") or {}).get("Labels") or {}
        if (
            labels.get("com.docker.compose.project") != "my-pa-nas-contract"
            or labels.get("com.docker.compose.service") != name
        ):
            errors.append(f"{name}_running_compose_identity")
        if labels.get("com.docker.compose.config-hash") != configured_hashes.get(name):
            errors.append(f"{name}_running_config")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("compose", type=Path)
    parser.add_argument("image_manifest", type=Path)
    parser.add_argument("--pilot-overlay", type=Path)
    parser.add_argument("--running", action="store_true")
    args = parser.parse_args()
    errors = verify(
        args.compose,
        args.image_manifest,
        pilot_overlay_path=args.pilot_overlay,
        running=args.running,
    )
    if errors:
        print("NAS runtime identity gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
