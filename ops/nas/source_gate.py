#!/usr/bin/env python3
"""Statically verify NAS-08 GoodNotes placement and Frontier stdio launch."""

from __future__ import annotations

import json
import posixpath
import subprocess
import sys
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any


def _parse_yaml(path: Path) -> dict[str, Any] | None:
    program = "print JSON.generate(YAML.safe_load(STDIN.read, aliases: false))"
    result = subprocess.run(  # noqa: S603 - fixed system Ruby and fixed program
        ["/usr/bin/ruby", "-rjson", "-ryaml", "-e", program],
        input=path.read_text(encoding="utf-8"),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        return None
    parsed = json.loads(result.stdout)
    return parsed if isinstance(parsed, dict) else None


def _mounts(service: dict[str, Any]) -> tuple[dict[str, tuple[str, bool]], bool]:
    result: dict[str, tuple[str, bool]] = {}
    malformed = False
    for item in service.get("volumes", []):
        if not isinstance(item, dict) or not isinstance(item.get("target"), str):
            malformed = True
            continue
        if item["target"] in result:
            malformed = True
        result[item["target"]] = (str(item.get("source", "")), item.get("read_only") is True)
    return result, malformed


def _receives_exclusive_goodnotes_authority(service: dict[str, Any]) -> bool:
    mounts, malformed = _mounts(service)
    if malformed or "volumes_from" in service:
        return True
    exclusive_targets = (
        PurePosixPath("/srv/my-pa/goodnotes"),
        PurePosixPath("/srv/my-pa/goodnotes-ocr"),
    )
    for target, (source, _read_only) in mounts.items():
        mounted_at = PurePosixPath(target)
        if any(exclusive.is_relative_to(mounted_at) for exclusive in exclusive_targets):
            return True
        if source.startswith("${MY_PA_NAS_ROOT"):
            suffix = source.partition("}")[2]
            segments = suffix.split("/")
            if any(segment in {".", ".."} for segment in segments):
                return True
            normalized_suffix = posixpath.normpath(suffix)
            if normalized_suffix in {".", "/", "/goodnotes", "/goodnotes-ocr"}:
                return True
    return False


def verify(
    contract_path: Path,
    compose_path: Path,
    runtime_compose_path: Path,
    child_path: Path,
    proxy_path: Path,
) -> list[str]:
    try:
        contract = tomllib.loads(contract_path.read_text(encoding="utf-8"))
        compose = _parse_yaml(compose_path)
        runtime_compose = _parse_yaml(runtime_compose_path)
        child = json.loads(child_path.read_text(encoding="utf-8"))
        proxy = proxy_path.read_text(encoding="utf-8")
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError):
        return ["input_unreadable"]
    if compose is None or runtime_compose is None:
        return ["compose_unreadable"]
    errors: list[str] = []
    if set(compose) != {"services"}:
        errors.append("overlay_topology")
    if contract.get("schema") != "my-pa.nas-source-placement.v1":
        errors.append("schema")
    if contract.get("status") != "contract_only_not_activated":
        errors.append("status")
    goodnotes = contract.get("goodnotes", {})
    frontier = contract.get("frontier_mcp", {})
    services = compose.get("services", {})
    if not isinstance(services, dict) or set(services) != {"goodnotes-reconcile", "frontier-mcp"}:
        return [*errors, "service_set"]
    goodnotes_service = services["goodnotes-reconcile"]
    frontier_service = services["frontier-mcp"]
    if not isinstance(goodnotes_service, dict) or not isinstance(frontier_service, dict):
        return [*errors, "service_shape"]

    root = PurePosixPath(str(goodnotes.get("root", "")))
    manifest = PurePosixPath(str(goodnotes.get("manifest", "")))
    ocr = PurePosixPath(str(goodnotes.get("ocr_executable", "")))
    if root != PurePosixPath("/srv/my-pa/goodnotes"):
        errors.append("goodnotes_root")
    if (
        manifest.is_absolute()
        or not manifest.parts
        or any(part in {"", ".", ".."} for part in manifest.parts)
        or not (root / manifest).is_relative_to(root)
    ):
        errors.append("goodnotes_manifest")
    ocr_root = PurePosixPath("/srv/my-pa/goodnotes-ocr")
    if not ocr.is_relative_to(ocr_root):
        errors.append("goodnotes_ocr")
    goodnotes_mounts, malformed_goodnotes_mount = _mounts(goodnotes_service)
    expected_goodnotes_mounts = {
        str(root): ("${MY_PA_NAS_ROOT:?explicit NAS root required}/goodnotes", True),
        str(ocr_root): (
            "${MY_PA_NAS_ROOT:?explicit NAS root required}/goodnotes-ocr",
            True,
        ),
    }
    if goodnotes_mounts.get(str(root)) != expected_goodnotes_mounts[str(root)]:
        errors.append("goodnotes_mount")
    if goodnotes_mounts.get(str(ocr_root)) != expected_goodnotes_mounts[str(ocr_root)]:
        errors.append("ocr_mount")
    if (
        goodnotes_mounts != expected_goodnotes_mounts
        or malformed_goodnotes_mount
        or len(goodnotes_service.get("volumes", [])) != len(goodnotes_mounts)
    ):
        errors.append("goodnotes_mount_set")
    environment = goodnotes_service.get("environment", {})
    command = goodnotes_service.get("command", [])
    expected_command = [
        "python",
        "apps/cli/goodnotes.py",
        "reconcile",
        "--principal-id",
        "${MY_PA_GOODNOTES_PRINCIPAL_ID:?exact owning Principal required}",
        "--idempotency-key",
        "${MY_PA_GOODNOTES_IDEMPOTENCY_KEY:?explicit bounded key required}",
    ]
    expected_environment = {
        "MY_PA_AUTH_MODE": "local_operator",
        "MY_PA_GOODNOTES_ROOT": str(root),
        "MY_PA_GOODNOTES_MANIFEST": str(manifest),
        "MY_PA_GOODNOTES_OCR_ROOT": str(ocr_root),
        "MY_PA_GOODNOTES_OCR_EXECUTABLE": str(ocr),
        "MY_PA_GOODNOTES_OCR_ARGUMENTS_JSON": "[]",
        "MY_PA_GOODNOTES_OCR_NAME": (
            "${MY_PA_GOODNOTES_OCR_NAME:?exact OCR provenance name required}"
        ),
        "MY_PA_GOODNOTES_OCR_VERSION": (
            "${MY_PA_GOODNOTES_OCR_VERSION:?exact OCR provenance version required}"
        ),
    }
    forbidden_network_keys = {"ports", "expose", "network_mode", "extra_hosts"}
    if (
        goodnotes.get("service") != "goodnotes-reconcile"
        or goodnotes.get("profile") != "nas-08-goodnotes-operator"
        or goodnotes.get("command") != expected_command[:3]
        or goodnotes.get("root_mount") != "goodnotes_ro"
        or goodnotes.get("ocr_mount") != "goodnotes_ocr_ro"
        or goodnotes_service.get("profiles") != ["nas-08-goodnotes-operator"]
        or goodnotes_service.get("image")
        != "${MY_PA_APP_IMAGE_ID:?sha256 loaded image id required}"
        or goodnotes_service.get("platform") != "linux/amd64"
        or goodnotes_service.get("user")
        != (
            "${MY_PA_UID:?dedicated service uid required}:"
            "${MY_PA_GID:?dedicated service gid required}"
        )
        or goodnotes_service.get("env_file")
        != ["${MY_PA_NAS_ENV_FILE:?owner-only NAS env file required}"]
        or command != expected_command
        or environment != expected_environment
        or goodnotes.get("source_writes") != "forbidden"
        or goodnotes.get("principal_partitioning") != "fixed_local_operator"
        or goodnotes_service.get("restart") != "no"
        or goodnotes_service.get("networks") != ["data-plane"]
        or goodnotes_service.get("cap_drop") != ["ALL"]
        or goodnotes_service.get("security_opt") != ["no-new-privileges:true"]
        or forbidden_network_keys & set(goodnotes_service)
        or "volumes_from" in goodnotes_service
    ):
        errors.append("goodnotes_composition")

    if _receives_exclusive_goodnotes_authority(frontier_service):
        errors.append("goodnotes_mount_owner")
    runtime_services = runtime_compose.get("services", {})
    if not isinstance(runtime_services, dict) or any(
        _receives_exclusive_goodnotes_authority(service)
        for service in runtime_services.values()
        if isinstance(service, dict)
    ):
        errors.append("goodnotes_mount_owner")
    if frontier != {
        "service": "frontier-mcp",
        "profile": "nas-08-frontier-mcp-stdio",
        "command": ["python", "apps/gateway.py", "mcp"],
        "transport": "stdio_only",
        "launch_model": "client_child_process",
        "ports": "forbidden",
        "proxy_route": "forbidden",
        "oauth": "not_added",
        "browser_path": "not_added",
        "activation": "operator_gated",
    }:
        errors.append("frontier_contract")
    frontier_mounts, malformed_frontier_mount = _mounts(frontier_service)
    expected_frontier_mounts = {
        "/srv/my-pa/config": (
            "${MY_PA_NAS_ROOT:?explicit NAS root required}/config",
            True,
        ),
        "/srv/my-pa/managed-documents": (
            "${MY_PA_NAS_ROOT:?explicit NAS root required}/managed-documents",
            False,
        ),
        "/srv/my-pa/sources": (
            "${MY_PA_NAS_ROOT:?explicit NAS root required}/sources",
            True,
        ),
    }
    if (
        frontier_service.get("profiles") != ["nas-08-frontier-mcp-stdio"]
        or frontier_service.get("image") != "${MY_PA_APP_IMAGE_ID:?sha256 loaded image id required}"
        or frontier_service.get("platform") != "linux/amd64"
        or frontier_service.get("user")
        != (
            "${MY_PA_UID:?dedicated service uid required}:"
            "${MY_PA_GID:?dedicated service gid required}"
        )
        or frontier_service.get("env_file")
        != ["${MY_PA_NAS_ENV_FILE:?owner-only NAS env file required}"]
        or frontier_service.get("environment")
        != {
            "MY_PA_AUTH_MODE": "local_operator",
            "MY_PA_MCP_SURFACE_DISABLED": (
                "${MY_PA_MCP_SURFACE_DISABLED:?explicit activation decision required}"
            ),
            "MY_PA_MANAGED_DOCUMENT_ROOT": "/srv/my-pa/managed-documents",
        }
        or frontier_service.get("command") != ["python", "apps/gateway.py", "mcp"]
        or frontier_service.get("stdin_open") is not True
        or frontier_service.get("tty") is not False
        or frontier_service.get("restart") != "no"
        or frontier_service.get("networks") != ["data-plane"]
        or frontier_service.get("cap_drop") != ["ALL"]
        or frontier_service.get("security_opt") != ["no-new-privileges:true"]
        or forbidden_network_keys & set(frontier_service)
        or frontier_mounts != expected_frontier_mounts
        or malformed_frontier_mount
        or len(frontier_service.get("volumes", [])) != len(frontier_mounts)
        or "volumes_from" in frontier_service
    ):
        errors.append("frontier_stdio")
    if "frontier-mcp" in proxy.lower() or "/mcp" in proxy.lower():
        errors.append("frontier_proxy")
    expected_args = [
        "compose",
        "--file",
        "ops/nas/compose.example.yml",
        "--file",
        "ops/nas/compose.sources.example.yml",
        "--profile",
        "nas-08-frontier-mcp-stdio",
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "frontier-mcp",
    ]
    child_server = child.get("mcpServers", {}).get("my-pa", {})
    if child_server != {"command": "docker", "args": expected_args}:
        errors.append("frontier_child")
    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        print(
            f"usage: {argv[0]} SOURCE_CONTRACT SOURCE_OVERLAY RUNTIME_COMPOSE "
            "CHILD_CONFIG PROXY_ALLOWLIST",
            file=sys.stderr,
        )
        return 2
    errors = verify(*(Path(value) for value in argv[1:]))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("NAS-08 source placement contract verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
