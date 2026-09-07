#!/usr/bin/env python3
"""Fail-closed production environment validator for pa.bobby-fetting.me."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CANONICAL_ORIGIN = "https://pa.bobby-fetting.me"
HOSTNAME = "pa.bobby-fetting.me"
SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
SOURCE_TREE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
SHA256_ID = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
DIGEST_PINNED = re.compile(
    r"^[^:@\s]+(?:/[^:@\s]+)*:[^:@\s]+@sha256:[0-9a-f]{64}$",
    re.IGNORECASE,
)


def load_schema(path: Path) -> dict[str, Any]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != "my-pa.nas-production-environment.v1":
        raise ValueError("unsupported_environment_schema")
    return payload


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if key in values:
            raise ValueError(f"duplicate_env:{key}")
        values[key] = value
    return values


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


def _ports_published(block: str) -> bool:
    for line in block.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if stripped.startswith("ports:"):
            return True
    return False


def check_compose_unpublished(compose_text: str) -> list[str]:
    errors: list[str] = []
    for service in ("postgres", "gateway"):
        block = _service_block(compose_text, service)
        if not block:
            errors.append(f"{service}_service_missing")
            continue
        if _ports_published(block):
            errors.append(f"{service}_host_published")
        if "0.0.0.0" in block:  # noqa: S104 - refuse published all-interfaces binds
            errors.append(f"{service}_all_interfaces_bind")
    return errors


def check_compose_json(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    services = payload.get("services")
    if not isinstance(services, dict):
        return ["compose_json_services_missing"]
    for name in ("postgres", "gateway"):
        service = services.get(name)
        if not isinstance(service, dict):
            errors.append(f"{name}_service_missing")
            continue
        ports = service.get("ports") or []
        if ports:
            errors.append(f"{name}_host_published")
        published = json.dumps(service)
        if "0.0.0.0" in published:  # noqa: S104 - refuse published all-interfaces binds
            errors.append(f"{name}_all_interfaces_bind")
    return errors


def validate_env(
    values: Mapping[str, str],
    schema: Mapping[str, Any],
    *,
    compose_text: str | None = None,
    compose_json: Mapping[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    variables = schema.get("variable")
    if not isinstance(variables, dict):
        return ["schema_variables_missing"]
    forbidden = schema.get("forbidden")
    if not isinstance(forbidden, dict):
        return ["schema_forbidden_missing"]

    if values.get("MYPA_AUTH_MODE") != "passkey":
        errors.append("production_auth_not_passkey")
    if values.get("MYPA_CANONICAL_ORIGIN") != CANONICAL_ORIGIN:
        errors.append("canonical_origin_mismatch")
    origin = values.get("MYPA_CANONICAL_ORIGIN", "")
    if origin and not origin.startswith("https://"):
        errors.append("canonical_origin_not_https")
    if values.get("NODE_ENV") != "production":
        errors.append("node_env_not_production")

    session_url = values.get("MYPA_SESSION_SERVICE_URL")
    if session_url is not None and session_url.strip() != "":
        errors.append("session_service_url_set")

    auth_mode = values.get("MYPA_AUTH_MODE", "")
    if auth_mode in set(forbidden.get("web_auth_mode_values") or ()):
        errors.append("forbidden_web_auth_mode")
    if values.get("MYPA_DATA_PROVIDER") in set(forbidden.get("data_provider_values") or ()):
        errors.append("synthetic_data_provider")

    for name in forbidden.get("names") or []:
        if values.get(str(name), "").strip():
            errors.append(f"forbidden_browser_var:{name}")

    known = set(variables)
    extra = sorted(key for key in values if key not in known)
    for key in extra:
        errors.append(f"unknown_variable:{key}")

    for name, spec in variables.items():
        if not isinstance(spec, dict):
            errors.append(f"schema_invalid:{name}")
            continue
        present = name in values
        raw = values.get(name, "")
        if spec.get("must_be_absent_or_empty"):
            if present and raw.strip():
                errors.append(f"must_be_absent:{name}")
            continue
        if spec.get("required") and (not present or raw.strip() == ""):
            errors.append(f"missing:{name}")
            continue
        if not present:
            continue
        exact = spec.get("exact_value")
        if exact is not None and raw != exact:
            errors.append(f"exact_mismatch:{name}")
        min_length = spec.get("min_length")
        if isinstance(min_length, int) and len(raw) < min_length:
            errors.append(f"secret_too_short:{name}")
        if spec.get("classification") == "secret" and len(raw) < 32:
            errors.append(f"secret_too_short:{name}")

    if "https://" not in values.get("MY_PA_WEBAUTHN_ALLOWED_ORIGINS", ""):
        errors.append("webauthn_origin_not_https")
    if values.get("MY_PA_WEBAUTHN_RP_ID") != HOSTNAME:
        errors.append("webauthn_rp_id_mismatch")

    commit = values.get("MYPA_SOURCE_COMMIT", "")
    tree = values.get("MYPA_SOURCE_TREE", "")
    if commit and SOURCE_COMMIT.fullmatch(commit) is None:
        errors.append("source_commit_not_full_hex")
    if tree and SOURCE_TREE.fullmatch(tree) is None:
        errors.append("source_tree_not_full_hex")

    for image_key in (
        "MY_PA_APP_IMAGE_ID",
        "MY_PA_WEB_IMAGE_ID",
        "MY_PA_POSTGRES_IMAGE_ID",
        "MY_PA_PROXY_IMAGE_DIGEST",
    ):
        value = values.get(image_key, "")
        if value and SHA256_ID.fullmatch(value) is None:
            errors.append(f"image_id_not_digest:{image_key}")
    cloudflared = values.get("MY_PA_FRONTEND_CLOUDFLARED_IMAGE", "")
    if cloudflared and DIGEST_PINNED.fullmatch(cloudflared) is None:
        errors.append("cloudflared_not_digest_pinned")
    if ":latest" in cloudflared or cloudflared.endswith("latest"):
        errors.append("latest_tag_forbidden")

    if compose_text is not None:
        errors.extend(check_compose_unpublished(compose_text))
    if compose_json is not None:
        errors.extend(check_compose_json(compose_json))
    return errors


def validate_paths(
    env_path: Path,
    schema_path: Path,
    *,
    compose_path: Path | None = None,
    compose_json_path: Path | None = None,
) -> list[str]:
    try:
        schema = load_schema(schema_path)
        values = load_env(env_path)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        return [f"input_unreadable:{exc}"]
    compose_text = None
    compose_json = None
    if compose_path is not None:
        compose_text = compose_path.read_text(encoding="utf-8")
    if compose_json_path is not None:
        parsed = json.loads(compose_json_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            return ["compose_json_not_object"]
        compose_json = parsed
    return validate_env(values, schema, compose_text=compose_text, compose_json=compose_json)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--env",
        type=Path,
        default=HERE / "production-environment.example.env",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=HERE / "production-environment.schema.toml",
    )
    parser.add_argument("--compose", type=Path, default=None)
    parser.add_argument("--compose-json", type=Path, default=None)
    args = parser.parse_args(argv)
    errors = validate_paths(
        args.env,
        args.schema,
        compose_path=args.compose,
        compose_json_path=args.compose_json,
    )
    if errors:
        print(
            "production environment refused: " + ", ".join(sorted(set(errors))),
            file=sys.stderr,
        )
        return 1
    print("production environment: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
