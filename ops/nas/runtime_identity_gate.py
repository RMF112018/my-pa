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
from typing import Any

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
PRESERVED_PUBLIC_COMMIT = "f7aa253968362fb673e811bfc3de2afe84855ae7"
PRESERVED_PUBLIC_TREE = "1debda7554f342048ca20dbed40f845af714ce5b"
PRESERVED_PUBLIC_SOURCE = Path("/volume1/my-pa/runtime-f7aa2539-prod-20261011T171832Z")
PRESERVED_PUBLIC_ADMISSION = Path("/etc/my-pa/runtime-admission.public-browser.f7aa2539.toml")
PRESERVED_PRIVATE_ROOT = Path("/volume1/my-pa/secrets")
PRESERVED_PUBLIC_ENV = PRESERVED_PRIVATE_ROOT / f"production.{PRESERVED_PUBLIC_COMMIT[:8]}.env"
ADMISSION_KEYS = {
    "schema",
    "status",
    "docker_engine_id",
    "docker_engine_name",
    "image_manifest_sha256",
    "resolved_compose_sha256",
    "service_images",
    "service_image_ids",
}


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


def public_browser_binding(
    source: Path,
    overlay: Path,
    manifest: dict[str, Any],
    *,
    owner_uid: int = 0,
    runner: Callable[[list[str]], str] = _run,
) -> dict[str, str]:
    """Bind only the checked-in public overlay; never select its edge profile."""
    source_status = source.lstat()
    if (
        not stat.S_ISDIR(source_status.st_mode)
        or source_status.st_uid != owner_uid
        or stat.S_IMODE(source_status.st_mode) & 0o022
        or source.resolve(strict=True) != source
    ):
        raise ValueError("public_browser_source_metadata")
    expected = source / "ops/nas/compose.public-browser.example.yml"
    if overlay != expected or overlay.resolve(strict=True) != expected:
        raise ValueError("public_browser_overlay_path")
    status = overlay.lstat()
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != owner_uid
        or status.st_nlink != 1
        or stat.S_IMODE(status.st_mode) & 0o022
    ):
        raise ValueError("public_browser_overlay_metadata")
    for reference, expected_value in (
        ("HEAD", manifest.get("repository_commit")),
        ("HEAD^{tree}", manifest.get("repository_tree")),
    ):
        if runner(["git", "-C", str(source), "rev-parse", reference]).strip() != expected_value:
            raise ValueError("public_browser_source_identity")
    if runner(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"]).strip():
        raise ValueError("public_browser_source_dirty")
    recorded = runner(
        [
            "git",
            "-C",
            str(source),
            "rev-parse",
            "HEAD:ops/nas/compose.public-browser.example.yml",
        ]
    ).strip()
    actual = runner(["git", "-C", str(source), "hash-object", str(overlay)]).strip()
    if recorded != actual:
        raise ValueError("public_browser_overlay_source_drift")
    return {
        "overlay_path": str(overlay),
        "overlay_sha256": _sha(overlay.read_bytes()),
        "repository_commit": str(manifest["repository_commit"]),
        "repository_tree": str(manifest["repository_tree"]),
    }


def preserved_public_source_errors(
    source: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    *,
    owner_uid: int,
    runner: Callable[[list[str]], str],
) -> list[str]:
    """The bounded f7 reconciliation retains live image/source/engine authority.

    The executing gate is the reviewed current source, launched only after the
    immutable operator pre-source gate authenticates the interpreter/artifacts.
    This is target validation, not permission to execute an arbitrary old gate.
    """
    if (
        source.resolve(strict=True) != source
        or source == Path(__file__).resolve().parents[2]
        or not _trusted_file(manifest_path, owner_uid)
        or manifest.get("repository_commit") != PRESERVED_PUBLIC_COMMIT
        or manifest.get("repository_tree") != PRESERVED_PUBLIC_TREE
    ):
        return ["preserved_public_source_binding"]
    errors: list[str] = []
    for name in ("app", "web"):
        image = manifest.get("images", {}).get(name, {})
        try:
            labels = json.loads(
                runner(
                    [
                        docker(),
                        "image",
                        "inspect",
                        "--format",
                        "{{json .Config.Labels}}",
                        str(image.get("docker_image_id", "")),
                    ]
                )
            )
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
            errors.append("preserved_public_loaded_identity")
            continue
        if (
            labels.get("org.opencontainers.image.revision") != PRESERVED_PUBLIC_COMMIT
            or labels.get("io.my-pa.repository-tree") != PRESERVED_PUBLIC_TREE
        ):
            errors.append("preserved_public_loaded_source")
    return errors


def preserved_compose_prefix(
    compose: Path,
    env_file: Path,
    *,
    owner_uid: int = 0,
    private_root: Path = PRESERVED_PRIVATE_ROOT,
) -> list[str]:
    """Read the old fixed env only inside Compose; never copy or print its values."""
    if env_file != private_root / f"production.{PRESERVED_PUBLIC_COMMIT[:8]}.env":
        raise ValueError("preserved_public_environment_path")
    for directory in (private_root.parent.parent, private_root.parent, private_root):
        state = directory.lstat()
        if (
            not stat.S_ISDIR(state.st_mode)
            or state.st_uid != owner_uid
            or stat.S_IMODE(state.st_mode) & 0o022
            or directory.resolve(strict=True) != directory
            or (directory == private_root and stat.S_IMODE(state.st_mode) != 0o700)
        ):
            raise ValueError("preserved_public_environment_directory")
    metadata = env_file.lstat()
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != owner_uid
        or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
        or metadata.st_nlink != 1
        or metadata.st_size > 262_144
        or env_file.resolve(strict=True) != env_file
    ):
        raise ValueError("preserved_public_environment_metadata")
    return [docker(), "compose", "--env-file", str(env_file), "--file", str(compose)]


def public_browser_scope_errors(base: dict[str, Any], combined: dict[str, Any]) -> list[str]:
    """Only web gains browser-origin; no other canonical service may change."""
    before = base.get("services", {})
    after = combined.get("services", {})
    if set(before) != SERVICES or set(after) != SERVICES:
        return ["public_browser_service_set"]
    if any(before[name] != after[name] for name in SERVICES - {"web"}):
        return ["public_browser_canonical_service_drift"]
    left, right = dict(before["web"]), dict(after["web"])
    old_networks = left.pop("networks", {})
    new_networks = right.pop("networks", {})
    old_values = old_networks if isinstance(old_networks, dict) else dict.fromkeys(old_networks)
    new_values = new_networks if isinstance(new_networks, dict) else dict.fromkeys(new_networks)
    if any(new_values.get(name) != value for name, value in old_values.items()):
        return ["public_browser_existing_web_network_drift"]
    if left != right or set(new_networks) != set(old_networks) | {"browser-origin"}:
        return ["public_browser_web_scope"]
    old_definition = base.get("networks", {})
    new_definition = combined.get("networks", {})
    if any(new_definition.get(name) != value for name, value in old_definition.items()):
        return ["public_browser_existing_network_drift"]
    return []


def verify(
    compose_path: Path,
    image_manifest_path: Path,
    *,
    pilot_overlay_path: Path | None = None,
    public_browser_overlay_path: Path | None = None,
    preserved_source_path: Path | None = None,
    admission_path: Path = CANONICAL_ADMISSION,
    owner_uid: int = 0,
    running: bool = False,
    baseline_admission_path: Path = CANONICAL_ADMISSION,
    preserved_env_path: Path = PRESERVED_PUBLIC_ENV,
    preserved_private_root: Path = PRESERVED_PRIVATE_ROOT,
    runner: Callable[[list[str]], str] = _run,
) -> list[str]:
    errors: list[str] = []
    repository = preserved_source_path or Path(__file__).resolve().parents[2]
    if compose_path.resolve() != repository / "ops/nas/compose.example.yml":
        errors.append("canonical_compose_path")
    if pilot_overlay_path is not None and (
        pilot_overlay_path.resolve() != repository / "ops/nas/compose.pilot.example.yml"
    ):
        errors.append("canonical_pilot_overlay_path")
    if pilot_overlay_path is not None and public_browser_overlay_path is not None:
        errors.append("public_browser_pilot_scope")
    if preserved_source_path is not None and public_browser_overlay_path is None:
        errors.append("preserved_public_overlay_required")
    if not _trusted_file(admission_path, owner_uid):
        return [*errors, "runtime_admission_metadata"]
    try:
        manifest_bytes = image_manifest_path.read_bytes()
        manifest = tomllib.loads(manifest_bytes.decode())
        admission = tomllib.loads(admission_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return [*errors, "runtime_identity_input"]
    compose_base = [docker(), "compose", "--file", str(compose_path)]
    if preserved_source_path is not None:
        try:
            compose_base = preserved_compose_prefix(
                compose_path,
                preserved_env_path,
                owner_uid=owner_uid,
                private_root=preserved_private_root,
            )
        except (OSError, ValueError):
            return [*errors, "preserved_public_environment_metadata"]
        errors.extend(
            preserved_public_source_errors(
                repository, image_manifest_path, manifest, owner_uid=owner_uid, runner=runner
            )
        )
    public_binding = None
    if public_browser_overlay_path is not None:
        try:
            public_binding = public_browser_binding(
                repository,
                public_browser_overlay_path,
                manifest,
                owner_uid=owner_uid,
                runner=runner,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            errors.append("public_browser_overlay_binding")
    if preserved_source_path is not None:
        try:
            if not _trusted_file(baseline_admission_path, owner_uid):
                raise ValueError
            baseline_bytes = baseline_admission_path.read_bytes()
            baseline = tomllib.loads(baseline_bytes.decode())
            if (
                set(baseline) != ADMISSION_KEYS
                or baseline.get("schema") != "my-pa.nas-runtime-admission.v1"
                or baseline.get("status") != "admitted"
                or baseline.get("image_manifest_sha256") != _sha(manifest_bytes)
                or baseline.get("docker_engine_id") != manifest.get("docker_engine_id")
                or baseline.get("docker_engine_name") != manifest.get("docker_engine_name")
                or baseline.get("service_images") != admission.get("service_images")
                or baseline.get("service_image_ids") != admission.get("service_image_ids")
                or public_binding is None
            ):
                raise ValueError
            baseline_render = json.loads(
                runner(
                    [
                        *compose_base,
                        "--profile",
                        "nas-01-contract-only",
                        "config",
                        "--format",
                        "json",
                    ]
                )
            )
            if baseline.get("resolved_compose_sha256", {}).get("smoke") != _sha(
                json.dumps(baseline_render, sort_keys=True, separators=(",", ":")).encode()
            ):
                raise ValueError
            public_binding["previous_runtime_admission_sha256"] = _sha(baseline_bytes)
        except (OSError, ValueError, UnicodeDecodeError, subprocess.SubprocessError):
            errors.append("preserved_public_baseline_admission")
    if admission.get("public_browser") != public_binding:
        errors.append("runtime_public_browser_binding")
    try:
        errors.extend(f"image_manifest_{value}" for value in _image_gate()._shape_errors(manifest))
    except (AttributeError, ImportError):
        return [*errors, "image_manifest_validator"]
    if (
        set(admission)
        != (ADMISSION_KEYS | ({"public_browser"} if public_binding is not None else set()))
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
        base = list(compose_base)
        if public_browser_overlay_path is not None:
            base.extend(["--file", str(public_browser_overlay_path)])
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
    if public_browser_overlay_path is not None:
        try:
            uncombined = json.loads(
                runner(
                    [
                        *compose_base,
                        "--profile",
                        "nas-01-contract-only",
                        "config",
                        "--format",
                        "json",
                    ]
                )
            )
            errors.extend(public_browser_scope_errors(uncombined, rendered))
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError, ValueError):
            errors.append("public_browser_base_render")
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
    parser.add_argument("--public-browser-overlay", type=Path)
    parser.add_argument("--preserved-source", type=Path)
    parser.add_argument("--running", action="store_true")
    args = parser.parse_args()
    if args.preserved_source is not None and args.preserved_source != PRESERVED_PUBLIC_SOURCE:
        print("NAS runtime identity gate refused: preserved_public_source_path")
        return 1
    errors = verify(
        args.compose,
        args.image_manifest,
        pilot_overlay_path=args.pilot_overlay,
        public_browser_overlay_path=args.public_browser_overlay,
        preserved_source_path=args.preserved_source,
        admission_path=PRESERVED_PUBLIC_ADMISSION if args.preserved_source else CANONICAL_ADMISSION,
        running=args.running,
    )
    if errors:
        print("NAS runtime identity gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
