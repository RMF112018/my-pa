#!/usr/bin/env python3
"""Orchestrate the WP29 production delivery-config contract. Never deploys."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load_production_env() -> ModuleType:
    path = HERE / "validate-production-env.py"
    spec = importlib.util.spec_from_file_location("validate_production_env", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("validate-production-env.py is unreadable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _service_block(compose: str, service: str) -> str:
    lines = compose.splitlines()
    try:
        services_start = lines.index("services:")
    except ValueError:
        return ""
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
        return ""
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
    return "\n".join(lines[service_start:service_end])


def check_compose_auth_and_ports(compose: str) -> list[str]:
    errors: list[str] = []
    web = _service_block(compose, "web")
    if "MYPA_AUTH_MODE: passkey" not in web:
        errors.append("compose_web_auth_not_passkey")
    if "MYPA_AUTH_MODE: synthetic" in web or "MYPA_AUTH_MODE: local_operator" in web:
        errors.append("compose_web_auth_forbidden")
    env = _load_production_env()
    errors.extend(env.check_compose_unpublished(compose))
    return errors


def check_public_overlay(compose: str) -> list[str]:
    errors: list[str] = []
    if "0.0.0.0" in compose:  # noqa: S104 - refuse published all-interfaces binds
        errors.append("public_overlay_all_interfaces")
    for service in ("public-proxy", "frontend-cloudflared"):
        block = _service_block(compose, service)
        if not block:
            errors.append(f"{service}_missing")
            continue
        for line in block.splitlines():
            stripped = line.split("#", 1)[0].strip()
            if stripped.startswith("ports:"):
                errors.append(f"{service}_host_published")
    return errors


def check_public_caddy(text: str) -> list[str]:
    errors: list[str] = []
    if "path /v1/*" not in text:
        errors.append("public_caddy_missing_v1_refusal")
    if 'respond "not found" 404' not in text:
        errors.append("public_caddy_missing_closed_refusal")
    hsts = 'Strict-Transport-Security "max-age=31536000"'
    if hsts not in text:
        errors.append("public_caddy_missing_hsts")
    if "includeSubDomains" in text:
        errors.append("public_caddy_hsts_includesubdomains")
    if "pa.bobby-fetting.me" not in text:
        errors.append("public_caddy_hostname_missing")
    return errors


def validate(root: Path = ROOT) -> list[str]:
    nas = root / "ops" / "nas"
    env_mod = _load_production_env()
    errors: list[str] = []
    errors.extend(
        env_mod.validate_paths(
            nas / "production-environment.example.env",
            nas / "production-environment.schema.toml",
        )
    )
    env_values = env_mod.load_env(nas / "production-environment.example.env")
    if env_values.get("MYPA_AUTH_MODE") == "synthetic":
        errors.append("example_env_synthetic")
    if env_values.get("MYPA_DATA_PROVIDER") == "synthetic":
        errors.append("example_env_synthetic_data")
    compose = (nas / "compose.example.yml").read_text(encoding="utf-8")
    errors.extend(check_compose_auth_and_ports(compose))
    public_compose = nas / "compose.public-browser.example.yml"
    if public_compose.is_file():
        errors.extend(check_public_overlay(public_compose.read_text(encoding="utf-8")))
    public_caddy = nas / "proxy-public-browser.example.caddy"
    if public_caddy.is_file():
        errors.extend(check_public_caddy(public_caddy.read_text(encoding="utf-8")))
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(
            "delivery-config refused: " + ", ".join(sorted(set(errors))),
            file=sys.stderr,
        )
        return 1
    print("delivery-config: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
