#!/usr/bin/env python3
"""Generate PostgreSQL resource admission for a created, stopped canonical container."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from nas_tools import docker
from postgres_gate import (
    CANONICAL_DATA_NETWORK,
    CANONICAL_PROJECT,
    LOCAL_FILESYSTEMS,
    filesystem_type,
)


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - closed Docker/stat argument vectors
        command, check=True, capture_output=True, text=True
    ).stdout


def generate(container_id: str, data_path: Path, floor: int, output: Path) -> list[str]:
    errors: list[str] = []
    try:
        resolved = data_path.resolve(strict=True)
        engine = json.loads(_run([docker(), "info", "--format", "{{json .}}"]))
        inspected = json.loads(_run([docker(), "inspect", container_id]))[0]
        filesystem = filesystem_type(_run(["df", "-PT", str(resolved)]))
        network = json.loads(_run([docker(), "network", "inspect", CANONICAL_DATA_NETWORK]))[0]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, ValueError):
        return ["live_inspection"]
    if resolved != data_path or not resolved.is_dir() or not os.access(resolved, os.W_OK | os.X_OK):
        errors.append("postgres_data_path")
    if filesystem not in LOCAL_FILESYSTEMS:
        errors.append("filesystem_not_local")
    if floor <= 0 or os.statvfs(resolved).f_bavail * os.statvfs(resolved).f_frsize < floor:
        errors.append("minimum_available_storage_bytes")
    labels = (inspected.get("Config") or {}).get("Labels") or {}
    if (
        labels.get("com.docker.compose.project") != CANONICAL_PROJECT
        or labels.get("com.docker.compose.service") != "postgres"
    ):
        errors.append("postgres_compose_identity")
    if inspected.get("State", {}).get("Running") is not False:
        errors.append("postgres_must_be_stopped")
    if inspected.get("HostConfig", {}).get("PortBindings"):
        errors.append("postgres_host_port")
    mounts = inspected.get("Mounts") or []
    if not any(
        mount.get("Type") == "bind"
        and mount.get("Source") == str(resolved)
        and mount.get("Destination") == "/var/lib/postgresql/data"
        and mount.get("RW") is True
        for mount in mounts
    ):
        errors.append("postgres_bind_mount")
    if set(inspected.get("NetworkSettings", {}).get("Networks", {})) != {CANONICAL_DATA_NETWORK}:
        errors.append("postgres_network_identity")
    network_labels = network.get("Labels") or {}
    if (
        network.get("Name") != CANONICAL_DATA_NETWORK
        or network.get("Internal") is not True
        or network_labels.get("com.docker.compose.project") != CANONICAL_PROJECT
        or network_labels.get("com.docker.compose.network") != "data-plane"
    ):
        errors.append("data_network_identity")
    # Docker 24 on Synology records the stopped container's configured network
    # in container inspection but does not publish a live network attachment
    # until the container starts. The exact container network and exact network
    # identity above are the complete pre-start contract; the live gate requires
    # membership once PostgreSQL is running.
    image_id = inspected.get("Image", "")
    if not str(image_id).startswith("sha256:"):
        errors.append("postgres_image_identity")
    if errors:
        return errors
    lines = [
        'schema = "my-pa.nas-postgres-resources.v1"',
        'status = "verified"',
        f"docker_engine_id = {json.dumps(str(engine.get('ID', '')))}",
        f"postgres_container_id = {json.dumps(container_id)}",
        f"postgres_image_id = {json.dumps(str(image_id))}",
        f"data_network = {json.dumps(CANONICAL_DATA_NETWORK)}",
        f"measured_at = {json.dumps(datetime.now(UTC).isoformat().replace('+00:00', 'Z'))}",
        f"logical_cpus = {int(engine.get('NCPU', 0))}",
        f"memory_bytes = {int(engine.get('MemTotal', 0))}",
        f"minimum_available_storage_bytes = {floor}",
        f"filesystem_type = {json.dumps(filesystem)}",
        f"postgres_data_path = {json.dumps(str(resolved))}",
        "",
        "[tuning]",
        'status = "no_numeric_tuning"',
    ]
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except OSError:
        return ["resource_output"]
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container-id", required=True)
    parser.add_argument("--data-path", required=True, type=Path)
    parser.add_argument("--minimum-available-storage-bytes", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    errors = generate(
        args.container_id, args.data_path, args.minimum_available_storage_bytes, args.output
    )
    if errors:
        print("PostgreSQL resource admission refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print(f"PostgreSQL resource admission written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
