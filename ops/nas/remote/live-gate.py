#!/usr/bin/env python3
"""Fail closed unless the running remote MCP stack matches its admitted shape."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tomllib
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, cast

APP_COMMAND = [
    "python",
    "apps/gateway.py",
    "mcp-remote",
    "--host",
    "0.0.0.0",  # noqa: S104 - exact in-container listener identity
    "--port",
    "8766",
]
EDGE_COMMAND = [
    "tunnel",
    "--config",
    "/etc/cloudflared/config.yml",
    "--no-autoupdate",
    "run",
]
PROJECT = "my-pa-remote-mcp"
CANONICAL_DATA_NETWORK = "my-pa-nas-contract_data-plane"


def docker() -> str:
    configured = os.environ.get("MY_PA_NAS_DOCKER", "docker")
    if configured.startswith("/"):
        if os.access(configured, os.X_OK):
            return configured
        raise RuntimeError("configured Docker executable is unavailable")
    resolved = shutil.which(configured)
    if resolved is None:
        raise RuntimeError("Docker executable is unavailable")
    return configured


def violations(
    app: Mapping[str, Any],
    edge: Mapping[str, Any],
    *,
    app_image: str,
    edge_image: str,
    data_network: str,
    networks: Mapping[str, Mapping[str, Any]],
    postgres_resources: Mapping[str, Any],
    postgres: Mapping[str, Any],
) -> list[str]:
    errors: list[str] = []
    for name, state, expected in (("app", app, app_image), ("edge", edge, edge_image)):
        config = state.get("Config", {})
        host = state.get("HostConfig", {})
        running = state.get("State", {})
        if running.get("Status") != "running":
            errors.append(f"{name}_not_running")
        if running.get("Health", {}).get("Status") != "healthy":
            errors.append(f"{name}_not_healthy")
        if config.get("Image") != expected:
            errors.append(f"{name}_image_identity")
        expected_command = APP_COMMAND if name == "app" else EDGE_COMMAND
        if config.get("Cmd") != expected_command:
            errors.append(f"{name}_command_identity")
        user = str(config.get("User", ""))
        if not user or user.startswith("0") or user == "root":
            errors.append(f"{name}_root_user")
        if host.get("ReadonlyRootfs") is not True:
            errors.append(f"{name}_writable_root")
        if host.get("Privileged") is not False:
            errors.append(f"{name}_privileged")
        if set(host.get("CapDrop") or ()) != {"ALL"}:
            errors.append(f"{name}_capabilities")
        if host.get("CapAdd"):
            errors.append(f"{name}_added_capabilities")
        if host.get("Devices"):
            errors.append(f"{name}_devices")
        if not {"no-new-privileges", "no-new-privileges:true"} & set(host.get("SecurityOpt") or ()):
            errors.append(f"{name}_new_privileges")
        if host.get("Init") is not True:
            errors.append(f"{name}_missing_init")
        if host.get("RestartPolicy", {}).get("Name") != "unless-stopped":
            errors.append(f"{name}_restart_policy")
        expected_cpuset = "0" if name == "app" else "1"
        if host.get("CpusetCpus") != expected_cpuset:
            errors.append(f"{name}_cpuset")
        unadmitted_controls = {
            "CpuShares": 0,
            "NanoCpus": 0,
            "CpuPeriod": 0,
            "CpuQuota": 0,
            "CpusetMems": "",
            "PidsLimit": None,
            "Ulimits": None,
        }
        if any(host.get(field) != value for field, value in unadmitted_controls.items()):
            errors.append(f"{name}_unadmitted_resource_control")
        memory = host.get("Memory")
        expected_memory = (768 if name == "app" else 256) * 1024 * 1024
        if memory != expected_memory:
            errors.append(f"{name}_memory_limit")
        if any("docker.sock" in str(mount.get("Source", "")) for mount in state.get("Mounts", ())):
            errors.append(f"{name}_docker_socket")

    app_mounts = {mount.get("Destination"): mount for mount in app.get("Mounts", ())}
    if app_mounts.get("/srv/my-pa/sources", {}).get("RW") is not False:
        errors.append("source_mount_not_read_only")
    if app_mounts.get("/srv/my-pa/config", {}).get("RW") is not False:
        errors.append("config_mount_not_read_only")
    if app_mounts.get("/srv/my-pa/managed-documents", {}).get("RW") is not True:
        errors.append("managed_mount_not_writable")
    sources = [
        app_mounts.get(destination, {}).get("Source")
        for destination in (
            "/srv/my-pa/config",
            "/srv/my-pa/sources",
            "/srv/my-pa/managed-documents",
        )
    ]
    if not all(
        isinstance(source, str) and PurePosixPath(source).is_absolute() for source in sources
    ):
        errors.append("app_mount_source_identity")
    else:
        paths = [PurePosixPath(cast(str, source)) for source in sources]
        if any(
            left == right or left in right.parents or right in left.parents
            for index, left in enumerate(paths)
            for right in paths[index + 1 :]
        ):
            errors.append("app_mount_overlap")

    edge_mounts = {mount.get("Destination"): mount for mount in edge.get("Mounts", ())}
    if edge_mounts.get("/etc/cloudflared/config.yml", {}).get("RW") is not False:
        errors.append("edge_config_mount_not_read_only")
    if edge_mounts.get("/run/secrets/cloudflared", {}).get("RW") is not False:
        errors.append("edge_credentials_mount_not_read_only")
    if app.get("HostConfig", {}).get("PortBindings"):
        errors.append("origin_host_port")
    if edge.get("HostConfig", {}).get("PortBindings"):
        errors.append("edge_host_port")

    origin_network = f"{PROJECT}_mcp-origin"
    cloudflare_network = f"{PROJECT}_cloudflare-egress"
    app_networks = set(app.get("NetworkSettings", {}).get("Networks", {}))
    edge_networks = set(edge.get("NetworkSettings", {}).get("Networks", {}))
    if app_networks != {data_network, origin_network}:
        errors.append("app_network_identity")
    if edge_networks != {origin_network, cloudflare_network}:
        errors.append("edge_network_identity")
    expected_internal = {
        data_network: None,
        origin_network: True,
        cloudflare_network: False,
    }
    for network, internal in expected_internal.items():
        network_state = networks.get(network)
        if network_state is None:
            errors.append("missing_network_identity")
        elif internal is not None and network_state.get("Internal") is not internal:
            errors.append(f"network_internalness:{network}")
    if data_network != CANONICAL_DATA_NETWORK:
        errors.append("noncanonical_data_network")
    data_state = networks.get(data_network, {})
    data_labels = data_state.get("Labels") or {}
    if (
        data_state.get("Name") != CANONICAL_DATA_NETWORK
        or data_state.get("Internal") is not True
        or data_labels.get("com.docker.compose.project") != "my-pa-nas-contract"
        or data_labels.get("com.docker.compose.network") != "data-plane"
        or postgres.get("Id") not in (data_state.get("Containers") or {})
    ):
        errors.append("canonical_data_network_identity")
    postgres_labels = (postgres.get("Config") or {}).get("Labels") or {}
    if (
        postgres_resources.get("status") != "verified"
        or postgres_resources.get("data_network") != CANONICAL_DATA_NETWORK
        or postgres.get("Id") != postgres_resources.get("postgres_container_id")
        or postgres.get("Image") != postgres_resources.get("postgres_image_id")
        or postgres.get("State", {}).get("Status") != "running"
        or postgres.get("State", {}).get("Health", {}).get("Status") != "healthy"
        or postgres_labels.get("com.docker.compose.project") != "my-pa-nas-contract"
        or postgres_labels.get("com.docker.compose.service") != "postgres"
        or set(postgres.get("NetworkSettings", {}).get("Networks", {})) != {CANONICAL_DATA_NETWORK}
    ):
        errors.append("canonical_postgres_identity")
    return errors


def _inspect(name: str) -> Mapping[str, Any]:
    result = subprocess.run(  # noqa: S603 - fixed Docker executable and argument vector
        [docker(), "inspect", name],
        check=True,
        capture_output=True,
        text=True,
    )
    document = json.loads(result.stdout)
    if not isinstance(document, list) or len(document) != 1:
        raise ValueError("docker inspect did not return exactly one container")
    return cast(Mapping[str, Any], document[0])


def _inspect_network(name: str) -> Mapping[str, Any]:
    return _inspect(name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-container", required=True)
    parser.add_argument("--edge-container", required=True)
    parser.add_argument("--app-image", required=True)
    parser.add_argument("--edge-image", required=True)
    parser.add_argument("--data-network", required=True)
    parser.add_argument("--postgres-resources", required=True)
    args = parser.parse_args()
    network_names = (
        args.data_network,
        f"{PROJECT}_mcp-origin",
        f"{PROJECT}_cloudflare-egress",
    )
    try:
        resources = tomllib.loads(Path(args.postgres_resources).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        print("remote live gate refused: postgres_resources_unreadable")
        return 1
    postgres_id = str(resources.get("postgres_container_id", ""))
    errors = violations(
        _inspect(args.app_container),
        _inspect(args.edge_container),
        app_image=args.app_image,
        edge_image=args.edge_image,
        data_network=args.data_network,
        networks={name: _inspect_network(name) for name in network_names},
        postgres_resources=resources,
        postgres=_inspect(postgres_id),
    )
    if errors:
        print("remote live gate refused: " + ", ".join(sorted(set(errors))))
        return 1
    print("remote live gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
