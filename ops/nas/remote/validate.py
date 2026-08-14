#!/usr/bin/env python3
"""Fail-closed structural gate for the remote NAS/Cloudflare contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _service_lines(compose: str, service: str) -> list[str]:
    lines = compose.splitlines()
    try:
        services_start = lines.index("services:")
    except ValueError:
        return []
    services_end = next(
        (
            index
            for index in range(services_start + 1, len(lines))
            if lines[index] and not lines[index].startswith(" ")
        ),
        len(lines),
    )
    marker = f"  {service}:"
    try:
        service_start = lines.index(marker, services_start + 1, services_end)
    except ValueError:
        return []
    service_end = next(
        (
            index
            for index in range(service_start + 1, services_end)
            if lines[index].startswith("  ")
            and not lines[index].startswith("    ")
            and lines[index].strip()
            and not lines[index].lstrip().startswith("#")
        ),
        services_end,
    )
    return [
        line
        for line in lines[service_start + 1 : service_end]
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate(root: Path = ROOT) -> list[str]:
    compose = (root / "compose.yml").read_text(encoding="utf-8")
    fallback = (root / "compose.loopback.yml").read_text(encoding="utf-8")
    tunnel = (root / "cloudflared-config.example.yml").read_text(encoding="utf-8")
    errors: list[str] = []
    remote = compose.split("  my-pa-mcp-remote:", 1)[-1].split("  cloudflared:", 1)[0]
    edge = compose.split("  cloudflared:", 1)[-1].split("\nnetworks:\n", 1)[0]
    if "ports:" in compose or "network_mode:" in compose:
        errors.append("default_host_publication")
    resource_contracts = {
        "my-pa-mcp-remote": (
            '    cpuset: "${MY_PA_REMOTE_CPUSET:?remote MCP CPU set required}"',
            '    mem_limit: "${MY_PA_REMOTE_MEMORY:?remote MCP memory limit required}"',
        ),
        "cloudflared": (
            '    cpuset: "${MY_PA_CLOUDFLARED_CPUSET:?cloudflared CPU set required}"',
            '    mem_limit: "${MY_PA_CLOUDFLARED_MEMORY:?cloudflared memory limit required}"',
        ),
    }
    unsupported = ("cpus:", "cpu_shares:", "pids_limit:", "ulimits:")
    for service, expected in resource_contracts.items():
        active = _service_lines(compose, service)
        stripped = [line.strip() for line in active]
        if any(line.startswith(unsupported) for line in stripped):
            errors.append(f"{service}_unsupported_synology_cgroup_control")
        if any(active.count(line) != 1 for line in expected):
            errors.append(f"{service}_resource_contract")
    environment = (root / "compose.env.example").read_text(encoding="utf-8").splitlines()
    if (
        environment.count("MY_PA_REMOTE_CPUSET=0") != 1
        or environment.count("MY_PA_CLOUDFLARED_CPUSET=1") != 1
    ):
        errors.append("cpuset_example_contract")
    if "127.0.0.1:" not in fallback or "0.0.0.0:" in fallback:
        errors.append("fallback_not_loopback")
    for name, block in (("remote", remote), ("cloudflared", edge)):
        for required in (
            "user:",
            "read_only: true",
            "cap_drop: [ALL]",
            "no-new-privileges:true",
            "cpuset:",
            "mem_limit:",
            "healthcheck:",
        ):
            if required not in block:
                errors.append(f"{name}_{required.rstrip(':').replace(' ', '_')}")
    if "docker.sock" in compose or "SSH_AUTH_SOCK" in compose:
        errors.append("privileged_host_authority")
    if (
        "source:" not in remote
        or "/srv/my-pa/sources" not in remote
        or remote.count("read_only: true") < 3
    ):
        errors.append("source_not_read_only")
    if "managed-documents" not in remote or "apps/worker.py" in remote:
        errors.append("remote_authority")
    if "/readyz" not in remote or "/healthz" in remote:
        errors.append("remote_healthcheck_not_readiness")
    if (
        "internal: true" not in compose
        or "data-plane" not in remote
        or "mcp-origin" not in remote + edge
    ):
        errors.append("network_isolation")
    image_contract = (root / "compose.env.example").read_text()
    if not re.search(r"cloudflared:[^\n]*@sha256:[0-9a-f]{64}$", image_contract, re.MULTILINE):
        errors.append("cloudflared_not_digest_pinned")
    routes = re.findall(r"^\s+path: (.+)$", tunnel, re.MULTILINE)
    if (
        routes
        != [
            "^/mcp$",
            "^/healthz$",
            "^/.well-known/oauth-protected-resource$",
            "^/.well-known/oauth-protected-resource/mcp$",
            "^/.well-known/oauth-authorization-server$",
            "^/oauth/register$",
            "^/oauth/authorize$",
            "^/oauth/token$",
            "^/oauth/revoke$",
        ]
        or "- service: http_status:404" not in tunnel
    ):
        errors.append("tunnel_route_allowlist")
    if "/readyz" in tunnel:
        errors.append("private_readiness_exposed")
    if any(word in tunnel for word in ("token:", "secret:", "private_key:")):
        errors.append("committed_secret_field")
    return errors


if __name__ == "__main__":
    violations = validate()
    if violations:
        print(
            "remote runtime contract refused: " + ", ".join(sorted(set(violations))),
            file=sys.stderr,
        )
        raise SystemExit(1)
    print("remote runtime contract: PASS")
