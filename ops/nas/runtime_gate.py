#!/usr/bin/env python3
"""Verify NAS-04/05 container identity, isolation, mounts, and permissions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

SERVICES = {"gateway", "worker_enrollment", "worker_capture", "web"}
MOUNTS = {
    "gateway": {
        "/srv/my-pa/config": False,
        "/srv/my-pa/sources": False,
        "/srv/my-pa/managed-documents": True,
    },
    "worker_enrollment": {
        "/srv/my-pa/config": False,
        "/srv/my-pa/sources": False,
        "/srv/my-pa/goodnotes": False,
    },
    "worker_capture": {"/srv/my-pa/config": False},
    "web": {},
}
PATH_KEYS = {
    "/srv/my-pa/config": "config",
    "/srv/my-pa/sources": "sources",
    "/srv/my-pa/goodnotes": "goodnotes",
    "/srv/my-pa/managed-documents": "managed_documents",
}
NETWORKS = {
    "gateway": {"data-plane", "ingress-plane", "entra-egress"},
    "worker_enrollment": {"data-plane"},
    "worker_capture": {"data-plane"},
    "web": {"ingress-plane", "entra-egress"},
}
COMPOSE_SERVICES = {
    "gateway": "gateway",
    "worker_enrollment": "worker-enrollment",
    "worker_capture": "worker-capture",
    "web": "web",
}
COMMANDS = {
    "gateway": ["python", "apps/gateway.py", "run"],
    "worker_enrollment": ["python", "apps/worker.py", "run", "--plane", "enrollment"],
    "worker_capture": ["python", "apps/worker.py", "run", "--plane", "capture"],
    "web": ["node", "server.js"],
}
LOCAL_FILESYSTEMS = {"btrfs", "ext2", "ext3", "ext4", "xfs", "zfs"}


def _filesystem_type(path: Path) -> str:
    """Return the Linux mount type for path using the kernel mount table."""
    entries: list[tuple[int, str]] = []
    for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
        before, separator, after = line.partition(" - ")
        if not separator:
            continue
        fields = before.split()
        filesystem = after.split()[0]
        mountpoint = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
        if path == mountpoint or path.is_relative_to(mountpoint):
            entries.append((len(mountpoint.parts), filesystem))
    if not entries:
        raise OSError(f"no mount table entry for {path}")
    return max(entries)[1]


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603
        command, check=True, capture_output=True, text=True
    ).stdout


def verify(
    path: Path,
    *,
    live: bool = False,
    compose_file: Path | None = None,
    permissions: bool = False,
    runner: Callable[[list[str]], str] = _run,
    filesystem_type: Callable[[Path], str] = _filesystem_type,
) -> list[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["manifest_unreadable"]
    errors: list[str] = []
    if data.get("schema") != "my-pa.nas-runtime-services.v1":
        errors.append("schema")
    if data.get("status") != "verified":
        errors.append("status_not_verified")
    uid, gid = data.get("uid"), data.get("gid")
    if type(uid) is not int or type(gid) is not int or uid <= 0 or gid <= 0:
        errors.append("service_identity")
    engine_identity = data.get("docker_engine_id")
    if not isinstance(engine_identity, str) or not engine_identity.strip():
        errors.append("docker_engine_manifest_identity")
    services = data.get("services", {})
    if not isinstance(services, dict) or set(services) != SERVICES:
        errors.append("service_set")
        return errors
    paths = data.get("paths", {})
    if not isinstance(paths, dict) or set(paths) != set(PATH_KEYS.values()):
        errors.append("path_set")
        return errors
    filesystem_types = data.get("filesystem_types", {})
    if not isinstance(filesystem_types, dict) or set(filesystem_types) != set(PATH_KEYS.values()):
        errors.append("filesystem_type_set")
        return errors
    resolved_paths: dict[str, str] = {}
    for key, raw in paths.items():
        candidate = Path(str(raw))
        if not candidate.is_absolute() or str(raw) in {"", "/"} or str(raw).startswith("/Volumes/"):
            errors.append(f"{key}_path")
            continue
        if live:
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                errors.append(f"{key}_path_missing")
                continue
            if resolved != candidate or not resolved.is_dir():
                errors.append(f"{key}_path_not_canonical")
            resolved_paths[key] = str(resolved)
            try:
                measured_filesystem = filesystem_type(resolved)
            except OSError:
                errors.append(f"{key}_filesystem_unreadable")
            else:
                if (
                    measured_filesystem not in LOCAL_FILESYSTEMS
                    or filesystem_types.get(key) != measured_filesystem
                ):
                    errors.append(f"{key}_filesystem_not_local")
    resolved_roots = [Path(value) for value in resolved_paths.values()]
    for index, left in enumerate(resolved_roots):
        for right in resolved_roots[index + 1 :]:
            if left == right or left.is_relative_to(right) or right.is_relative_to(left):
                errors.append("path_class_overlap")
    if not live:
        return [*errors, "live_verification_required"]
    if errors:
        return errors
    if compose_file is None or not compose_file.is_file():
        errors.append("compose_file_required")
        return errors
    for name, expected in services.items():
        if (
            not isinstance(expected, dict)
            or set(expected) != {"container_id", "image_id"}
            or not isinstance(expected.get("container_id"), str)
            or not expected["container_id"].strip()
            or not isinstance(expected.get("image_id"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", expected["image_id"]) is None
        ):
            errors.append(f"{name}_manifest_identity")
    if errors:
        return errors
    try:
        engine = json.loads(runner(["docker", "info", "--format", "{{json .}}"]))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return [*errors, "docker_info"]
    if engine.get("ID") != engine_identity:
        errors.append("docker_engine_identity")
    for name in sorted(SERVICES):
        expected = services[name]
        try:
            compose_id = runner(
                [
                    "docker",
                    "compose",
                    "--file",
                    str(compose_file),
                    "--profile",
                    "nas-01-contract-only",
                    "ps",
                    "-q",
                    COMPOSE_SERVICES[name],
                ]
            ).strip()
            if compose_id != expected["container_id"]:
                errors.append(f"{name}_compose_identity")
            inspected = json.loads(runner(["docker", "inspect", expected["container_id"]]))[0]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, subprocess.SubprocessError):
            errors.append(f"{name}_inspect")
            continue
        config = inspected.get("Config", {})
        host = inspected.get("HostConfig", {})
        if inspected.get("Image") != expected.get("image_id"):
            errors.append(f"{name}_image")
        if config.get("User") != f"{uid}:{gid}":
            errors.append(f"{name}_user")
        if config.get("Cmd") != COMMANDS[name]:
            errors.append(f"{name}_command")
        if config.get("Entrypoint") not in (None, []):
            errors.append(f"{name}_entrypoint")
        environment_items = config.get("Env") or []
        environment_pairs = [item.partition("=") for item in environment_items]
        environment_keys = [key for key, separator, _value in environment_pairs if separator]
        environment = {key: value for key, separator, value in environment_pairs if separator}
        if name == "gateway" and (
            len(environment_keys) != len(set(environment_keys))
            or environment.get("MY_PA_GATEWAY_BIND_MODE") != "container"
            or environment.get("MY_PA_MANAGED_DOCUMENT_ROOT") != "/srv/my-pa/managed-documents"
        ):
            errors.append("gateway_environment")
        if name != "gateway" and {
            "MY_PA_GATEWAY_BIND_MODE",
            "MY_PA_MANAGED_DOCUMENT_ROOT",
        } & set(environment):
            errors.append(f"{name}_gateway_authority")
        if (
            host.get("NetworkMode") == "host"
            or host.get("Privileged") is True
            or host.get("PublishAllPorts") is True
            or host.get("CapAdd")
            or set(host.get("CapDrop") or []) != {"ALL"}
            or host.get("Devices")
            or set(host.get("SecurityOpt") or []) != {"no-new-privileges:true"}
        ):
            errors.append(f"{name}_privilege")
        if host.get("PortBindings"):
            errors.append(f"{name}_published_ports")
        actual_networks = {
            network.rpartition("_")[2]
            for network in inspected.get("NetworkSettings", {}).get("Networks", {})
        }
        if actual_networks != NETWORKS[name]:
            errors.append(f"{name}_networks")
        actual_mounts = {
            item.get("Destination"): (item.get("Type"), item.get("Source"), bool(item.get("RW")))
            for item in inspected.get("Mounts", [])
        }
        expected_mounts = {
            destination: ("bind", resolved_paths.get(PATH_KEYS[destination]), writable)
            for destination, writable in MOUNTS[name].items()
        }
        if actual_mounts != expected_mounts:
            errors.append(f"{name}_mounts")
    if errors or not permissions:
        return errors
    for name in sorted(SERVICES):
        container_id = services[name]["container_id"]

        def permission_exec(
            script: str,
            service_name: str = name,
            pinned_id: str = container_id,
        ) -> bool:
            try:
                rebound_id = runner(
                    [
                        "docker",
                        "compose",
                        "--file",
                        str(compose_file),
                        "--profile",
                        "nas-01-contract-only",
                        "ps",
                        "-q",
                        COMPOSE_SERVICES[service_name],
                    ]
                ).strip()
            except (OSError, subprocess.SubprocessError):
                errors.append(f"{service_name}_permission_rebind")
                return False
            if rebound_id != pinned_id:
                errors.append(f"{service_name}_permission_identity")
                return False
            try:
                output = runner(["docker", "exec", "-i", pinned_id, "sh", "-eu", "-c", script])
            except (OSError, subprocess.SubprocessError):
                errors.append(f"{service_name}_permission_probe")
                return False
            if output.strip():
                errors.append(f"{service_name}_permission_output")
                return False
            return True

        for destination, writable in MOUNTS[name].items():
            permission_check = (
                f'test -w "{destination}"'
                if writable
                else (
                    f'p="{destination}/.nas-ro-probe.$$"; '
                    'if (: > "$p") 2>/dev/null; then rm -f "$p"; exit 1; fi'
                )
            )
            if not permission_exec(f'test -r "{destination}"; {permission_check}'):
                return errors
        if name == "gateway":
            if not permission_exec(
                "p=/srv/my-pa/managed-documents/.nas-permission-probe.$$; "
                "q=$p.renamed; printf probe > $p; sync $p; mv $p $q; rm $q"
            ):
                return errors
        else:
            if not permission_exec("test ! -e /srv/my-pa/managed-documents"):
                return errors
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--permissions", action="store_true")
    args = parser.parse_args()
    errors = verify(
        args.manifest,
        live=args.live,
        compose_file=args.compose_file,
        permissions=args.permissions,
    )
    if errors:
        print("NAS runtime gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
