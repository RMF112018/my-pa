#!/usr/bin/env python3
"""Read-only NAS private-ingress evidence gate for local-operator auth."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import re
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from nas_tools import docker

SERVICES = ("postgres", "gateway", "worker-enrollment", "worker-capture", "web", "proxy")
NETWORKS = {
    "postgres": {"data-plane"},
    "gateway": {"data-plane", "ingress-plane"},
    "worker-enrollment": {"data-plane"},
    "worker-capture": {"data-plane"},
    "web": {"ingress-plane"},
    "proxy": {"ingress-plane", "host-edge"},
}


def _run(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout  # noqa: S603


def _hostname(value: object) -> bool:
    if not isinstance(value, str) or len(value) > 253 or value.endswith("."):
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        pass
    return len(value.split(".")) >= 2 and all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in value.split(".")
    )


def _json_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError
    return parsed


def _json_single_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or len(parsed) != 1 or not isinstance(parsed[0], dict):
        raise TypeError
    return parsed[0]


def _environment(config: dict[str, Any]) -> dict[str, str] | None:
    items = config.get("Env") or []
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        return None
    pairs = [item.partition("=") for item in items]
    keys = [key for key, separator, _value in pairs if separator]
    if len(keys) != len(items) or len(keys) != len(set(keys)):
        return None
    return {key: value for key, _separator, value in pairs}


def verify(
    manifest_path: Path,
    proxy_config: Path,
    compose_file: Path,
    *,
    live: bool = False,
    runner: Callable[[list[str]], str] = _run,
) -> list[str]:
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        config_path = proxy_config.resolve(strict=True)
        config_bytes = config_path.read_bytes()
    except (OSError, tomllib.TOMLDecodeError):
        return ["evidence_unreadable"]
    errors: list[str] = []
    required = {
        "schema",
        "status",
        "docker_engine_id",
        "compose_project",
        "tailnet_hostname",
        "canonical_origin",
        "proxy_config_sha256",
        "loopback_target",
        "proxy_uid",
        "proxy_gid",
        "tailscale_version",
        "web_env_file",
        "web_env_owner_uid",
        "services",
    }
    if set(data) != required or data.get("schema") != "my-pa.nas-ingress-evidence.v2":
        errors.append("manifest_schema")
    if data.get("status") != "verified":
        errors.append("status_not_verified")
    host = data.get("tailnet_hostname")
    if not _hostname(host):
        errors.append("tailnet_hostname")
    if data.get("canonical_origin") != f"https://{host}":
        errors.append("canonical_origin")
    if data.get("proxy_config_sha256") != hashlib.sha256(config_bytes).hexdigest():
        errors.append("proxy_config_hash")
    for key in ("docker_engine_id", "compose_project", "tailscale_version"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key}_identity")
    for key in ("proxy_uid", "proxy_gid"):
        if type(data.get(key)) is not int or data[key] <= 0:
            errors.append("proxy_user_identity")
    target = data.get("loopback_target")
    match = re.fullmatch(r"127\.0\.0\.1:([1-9][0-9]{0,4})", str(target))
    if match is None or int(match.group(1)) > 65535:
        errors.append("loopback_target")
    web_env_raw = data.get("web_env_file")
    if not isinstance(web_env_raw, str) or type(data.get("web_env_owner_uid")) is not int:
        errors.append("web_env_file")
    services = data.get("services")
    if not isinstance(services, dict) or set(services) != set(SERVICES):
        errors.append("service_set")
    else:
        for name, identity in services.items():
            if (
                not isinstance(identity, dict)
                or set(identity) != {"container_id", "image_id"}
                or not isinstance(identity.get("container_id"), str)
                or not identity["container_id"].strip()
                or re.fullmatch(r"sha256:[0-9a-f]{64}", str(identity.get("image_id"))) is None
            ):
                errors.append(f"{name}_manifest_identity")
    if not live:
        return [*errors, "live_verification_required"]
    if errors or not compose_file.is_file():
        return errors or ["compose_file_required"]
    try:
        web_env_path = Path(cast(str, web_env_raw)).resolve(strict=True)
        metadata = web_env_path.stat()
        repo_root = compose_file.resolve(strict=True).parents[2]
    except OSError:
        return ["web_env_file"]
    if (
        web_env_path != Path(cast(str, web_env_raw))
        or not web_env_path.is_file()
        or metadata.st_uid != data["web_env_owner_uid"]
        or metadata.st_mode & 0o777 != 0o600
        or web_env_path == repo_root
        or repo_root in web_env_path.parents
    ):
        return ["web_env_file"]
    services = cast(dict[str, dict[str, str]], services)
    target = cast(str, target)
    try:
        engine = _json_object(runner([docker(), "info", "--format", "{{json .}}"]))
        version = _json_object(runner(["tailscale", "version", "--json"]))
        tailscale = _json_object(runner(["tailscale", "serve", "status", "--json"]))
        compose_model = _json_object(
            runner(
                [
                    docker(),
                    "compose",
                    "--project-name",
                    data["compose_project"],
                    "--file",
                    str(compose_file),
                    "--profile",
                    "nas-01-contract-only",
                    "config",
                    "--format",
                    "json",
                    "--no-env-resolution",
                ]
            )
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return ["live_inspection"]
    if engine.get("ID") != data["docker_engine_id"]:
        errors.append("docker_engine_identity")
    if version.get("Short") != data["tailscale_version"]:
        errors.append("tailscale_version")
    configured_env_files = compose_model.get("services", {}).get("web", {}).get("env_file")
    if (
        not isinstance(configured_env_files, list)
        or len(configured_env_files) != 1
        or not isinstance(configured_env_files[0], dict)
        or configured_env_files[0].get("path") != str(web_env_path)
        or configured_env_files[0].get("required", True) is not True
    ):
        errors.append("web_env_compose_binding")
    inspected_by_name: dict[str, dict[str, Any]] = {}
    for name in SERVICES:
        identity = services[name]
        try:
            compose_id = runner(
                [
                    docker(),
                    "compose",
                    "--project-name",
                    data["compose_project"],
                    "--file",
                    str(compose_file),
                    "--profile",
                    "nas-01-contract-only",
                    "ps",
                    "-q",
                    name,
                ]
            ).strip()
            inspected = _json_single_object(runner([docker(), "inspect", identity["container_id"]]))
            inspected_by_name[name] = inspected
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
            errors.append(f"{name}_inspection")
            continue
        if compose_id != identity["container_id"]:
            errors.append(f"{name}_compose_identity")
        if inspected.get("Image") != identity["image_id"]:
            errors.append(f"{name}_image_identity")
        actual_networks = {
            item.rpartition("_")[2]
            for item in inspected.get("NetworkSettings", {}).get("Networks", {})
        }
        if actual_networks != NETWORKS[name]:
            errors.append(f"{name}_networks")
        published = inspected.get("HostConfig", {}).get("PortBindings") or {}
        expected_ports = (
            {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": target.rsplit(":", 1)[1]}]}
            if name == "proxy"
            else {}
        )
        if published != expected_ports:
            errors.append(f"{name}_publication")
    if errors:
        return errors
    proxy = inspected_by_name["proxy"]
    proxy_env = _environment(proxy.get("Config", {}))
    host_config = proxy.get("HostConfig", {})
    if proxy_env is None or proxy_env.get("MY_PA_TAILNET_HOST") != host:
        errors.append("proxy_hostname_environment")
    if (
        proxy.get("Config", {}).get("User") != f"{data['proxy_uid']}:{data['proxy_gid']}"
        or host_config.get("Privileged")
        or host_config.get("PublishAllPorts")
        or host_config.get("NetworkMode") == "host"
        or set(host_config.get("CapAdd") or []) != {"NET_BIND_SERVICE"}
        or set(host_config.get("CapDrop") or []) != {"ALL"}
        or host_config.get("Devices")
        or set(host_config.get("SecurityOpt") or []) != {"no-new-privileges:true"}
        or host_config.get("ReadonlyRootfs") is not True
    ):
        errors.append("proxy_runtime_authority")
    mounts = {
        item.get("Destination"): (item.get("Type"), item.get("Source"), item.get("RW"))
        for item in proxy.get("Mounts") or []
        if isinstance(item, dict)
    }
    if mounts != {
        "/etc/caddy/Caddyfile": ("bind", str(config_path), False),
        "/config": ("tmpfs", "", True),
        "/data": ("tmpfs", "", True),
    }:
        errors.append("proxy_config_mount")
    gateway_env = _environment(inspected_by_name["gateway"].get("Config", {}))
    web = inspected_by_name["web"]
    web_env = _environment(web.get("Config", {}))
    if (
        gateway_env is None
        or gateway_env.get("MY_PA_AUTH_MODE") != "local_operator"
        or gateway_env.get("MY_PA_REMOTE_INGRESS_ENABLED") != "true"
    ):
        errors.append("gateway_ingress_environment")
    required_web = {
        "NODE_ENV": "production",
        "MYPA_AUTH_MODE": "local_operator",
        "MYPA_GATEWAY_URL": "http://gateway:8765",
        "MYPA_GATEWAY_AUTH_MODE": "local_operator",
        "MYPA_CANONICAL_ORIGIN": f"https://{host}",
    }
    session_secret = web_env.get("MYPA_SESSION_SECRET", "") if web_env is not None else ""
    operator_secret = web_env.get("MYPA_LOCAL_OPERATOR_SECRET", "") if web_env is not None else ""
    if (
        web_env is None
        or any(web_env.get(key) != value for key, value in required_web.items())
        or len(session_secret.strip()) < 32
        or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", operator_secret) is None
        or any("DATABASE" in key or "POSTGRES" in key for key in web_env)
        or web.get("Mounts")
    ):
        errors.append("web_runtime_authority")
    for environment in (gateway_env or {}, web_env or {}):
        if any("ENTRA" in key for key in environment):
            errors.append("entra_environment_present")
    try:
        internal = {
            name: _json_single_object(
                runner([docker(), "network", "inspect", f"{data['compose_project']}_{name}"])
            )
            for name in ("data-plane", "ingress-plane", "host-edge")
        }
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError):
        return [*errors, "network_inspection"]
    if any(internal[name].get("Internal") is not True for name in ("data-plane", "ingress-plane")):
        errors.append("network_internality")
    if internal["host-edge"].get("Internal") is not False:
        errors.append("host_edge_network")
    hostport = f"{host}:443"
    if tailscale.get("TCP") != {"443": {"HTTPS": True}} or tailscale.get("Web") != {
        hostport: {"Handlers": {"/": {"Proxy": f"http://{target}"}}}
    }:
        errors.append("tailscale_private_https")
    allow_funnel = tailscale.get("AllowFunnel") or {}
    if not isinstance(allow_funnel, dict) or any(
        value is not False for value in allow_funnel.values()
    ):
        errors.append("tailscale_funnel")
    if tailscale.get("Services") or tailscale.get("Foreground"):
        errors.append("tailscale_extra_exposure")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("proxy_config", type=Path)
    parser.add_argument("compose_file", type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    errors = verify(args.manifest, args.proxy_config, args.compose_file, live=args.live)
    if errors:
        print("NAS ingress gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
