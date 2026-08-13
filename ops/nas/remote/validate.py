#!/usr/bin/env python3
"""Fail-closed structural gate for the remote NAS/Cloudflare contract."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def validate(root: Path = ROOT) -> list[str]:
    compose = (root / "compose.yml").read_text(encoding="utf-8")
    fallback = (root / "compose.loopback.yml").read_text(encoding="utf-8")
    tunnel = (root / "cloudflared-config.example.yml").read_text(encoding="utf-8")
    errors: list[str] = []
    remote = compose.split("  my-pa-mcp-remote:", 1)[-1].split("  cloudflared:", 1)[0]
    edge = compose.split("  cloudflared:", 1)[-1].split("\nnetworks:\n", 1)[0]
    if "ports:" in compose or "network_mode:" in compose:
        errors.append("default_host_publication")
    if "127.0.0.1:" not in fallback or "0.0.0.0:" in fallback:
        errors.append("fallback_not_loopback")
    for name, block in (("remote", remote), ("cloudflared", edge)):
        for required in (
            "user:",
            "read_only: true",
            "cap_drop: [ALL]",
            "no-new-privileges:true",
            "pids_limit:",
            "cpus:",
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
