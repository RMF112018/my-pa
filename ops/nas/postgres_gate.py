#!/usr/bin/env python3
"""Fail-closed NAS PostgreSQL storage/resource validation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tomllib
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

NETWORK_FILESYSTEMS = {"nfs", "nfs4", "cifs", "smb", "smbfs"}
LOCAL_FILESYSTEMS = {"btrfs", "ext2/ext3", "ext2/ext3/ext4", "ext4", "xfs"}
Runner = Callable[[list[str]], str]


def run(command: list[str]) -> str:
    completed = subprocess.run(  # noqa: S603
        command, check=True, capture_output=True, text=True
    )
    return completed.stdout


def verify(
    path: Path, *, live: bool = False, container_id: str = "", runner: Runner = run
) -> list[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["manifest_unreadable"]
    errors: list[str] = []
    if data.get("schema") != "my-pa.nas-postgres-resources.v1":
        errors.append("schema")
    if data.get("status") != "verified":
        errors.append("status_not_verified")
    tuning = data.get("tuning", {})
    if not isinstance(tuning, dict) or tuning.get("status") != "verified_from_measurement":
        errors.append("tuning_not_verified")
    for key in ("logical_cpus", "memory_bytes", "available_storage_bytes"):
        if not isinstance(data.get(key), int) or data[key] <= 0:
            errors.append(key)
    if data.get("filesystem_type") in NETWORK_FILESYSTEMS:
        errors.append("network_filesystem")
    if data.get("filesystem_type") not in LOCAL_FILESYSTEMS:
        errors.append("filesystem_not_verified_local")
    if not str(data.get("postgres_container_id", "")).strip():
        errors.append("postgres_container_id")
    raw_path = str(data.get("postgres_data_path", ""))
    candidate = Path(raw_path)
    if not candidate.is_absolute() or raw_path in {"", "/"} or raw_path.startswith("/Volumes/"):
        errors.append("postgres_data_path")
    try:
        measured = datetime.fromisoformat(str(data.get("measured_at", "")).replace("Z", "+00:00"))
        if measured.utcoffset() is None:
            raise ValueError
    except ValueError:
        errors.append("measured_at")
    if not live:
        return [*errors, "live_verification_required"]
    if container_id != data.get("postgres_container_id"):
        errors.append("compose_postgres_identity")
    try:
        resolved = candidate.resolve(strict=True)
        if resolved != candidate:
            errors.append("path_not_canonical")
        if not resolved.is_dir() or not os.access(resolved, os.W_OK | os.X_OK):
            errors.append("path_not_writable_directory")
        info = json.loads(runner(["docker", "info", "--format", "{{json .}}"]))
        filesystem_type = runner(["stat", "--file-system", "--format=%T", str(resolved)]).strip()
        inspected = json.loads(runner(["docker", "inspect", data["postgres_container_id"]]))
        stat = os.statvfs(resolved)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        errors.append("live_inspection")
        return errors
    if info.get("ID") != data.get("docker_engine_id"):
        errors.append("docker_engine_identity")
    if filesystem_type != data.get("filesystem_type") or filesystem_type not in LOCAL_FILESYSTEMS:
        errors.append("live_filesystem_type")
    mounts = inspected[0].get("Mounts", []) if isinstance(inspected, list) and inspected else []
    expected_mount = {
        "Type": "bind",
        "Source": str(resolved),
        "Destination": "/var/lib/postgresql/data",
        "RW": True,
    }
    if not any(
        all(mount.get(key) == value for key, value in expected_mount.items()) for mount in mounts
    ):
        errors.append("postgres_bind_mount")
    if info.get("NCPU") != data.get("logical_cpus") or info.get("MemTotal") != data.get(
        "memory_bytes"
    ):
        errors.append("resource_drift")
    if stat.f_bavail * stat.f_frsize < data.get("available_storage_bytes", 0):
        errors.append("storage_drift")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--container-id", default="")
    args = parser.parse_args()
    errors = verify(args.manifest, live=args.live, container_id=args.container_id)
    if errors:
        print("NAS PostgreSQL gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print("NAS PostgreSQL gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
