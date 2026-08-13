#!/usr/bin/env python3
"""Admit the canonical PostgreSQL-only Compose render without app credentials."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tomllib
from pathlib import Path
from typing import Any

from nas_tools import docker

PROJECT = "my-pa-nas-contract"
SERVICE = "postgres"
NETWORK = "my-pa-nas-contract_data-plane"
SENTINEL_IMAGE = "sha256:" + "0" * 64
SENTINEL_ENVIRONMENT = {
    "MY_PA_APP_IMAGE_ID": SENTINEL_IMAGE,
    "MY_PA_WEB_IMAGE_ID": SENTINEL_IMAGE,
    "MY_PA_PROXY_IMAGE": "invalid.example/my-pa-bootstrap-sentinel",
    "MY_PA_PROXY_IMAGE_DIGEST": SENTINEL_IMAGE,
    "MY_PA_UID": "1",
    "MY_PA_GID": "1",
    "MY_PA_NAS_ENV_FILE": "/dev/null",
    "MY_PA_WEB_ENV_FILE": "/dev/null",
    "MY_PA_PROXY_UID": "1",
    "MY_PA_PROXY_GID": "1",
    "MY_PA_PROXY_PORT": "1",
    "MY_PA_TAILNET_HOST": "invalid.example",
    "MYPA_CANONICAL_ORIGIN": "https://invalid.example",
    "MYPA_ENTRA_REDIRECT_URI": "https://invalid.example/callback",
}
SENTINEL_MARKERS = {
    SENTINEL_IMAGE,
    "invalid.example/my-pa-bootstrap-sentinel",
    "/dev/null",
    "invalid.example",
    "https://invalid.example",
    "https://invalid.example/callback",
}


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, environment: dict[str, str] | None = None) -> str:
    return subprocess.run(  # noqa: S603 - fixed Docker/Compose argument vectors
        command,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout


def render_postgres(compose: Path) -> dict[str, Any]:
    environment = {**os.environ, **SENTINEL_ENVIRONMENT}
    for required in ("MY_PA_POSTGRES_IMAGE_ID", "MY_PA_DB_PASSWORD", "MY_PA_NAS_ROOT"):
        if not environment.get(required):
            raise ValueError(f"missing_{required.lower()}")
    rendered = json.loads(
        _run(
            [
                docker(),
                "compose",
                "--file",
                str(compose),
                "--profile",
                "nas-01-contract-only",
                "config",
                "--format",
                "json",
                SERVICE,
            ],
            environment=environment,
        )
    )
    if not isinstance(rendered, dict):
        raise ValueError("render_not_object")
    return rendered


def canonical_render(rendered: dict[str, Any]) -> bytes:
    return json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode()


def render_errors(rendered: dict[str, Any], *, image_id: str, root: str) -> list[str]:
    errors: list[str] = []
    services = rendered.get("services", {})
    if (
        rendered.get("name") != PROJECT
        or not isinstance(services, dict)
        or set(services) != {SERVICE}
    ):
        return ["postgres_render_identity"]
    postgres = services[SERVICE]
    if not isinstance(postgres, dict):
        return ["postgres_render_identity"]
    if (
        postgres.get("image") != image_id
        or postgres.get("platform") != "linux/amd64"
        or postgres.get("restart") != "no"
        or postgres.get("ports")
        or set(postgres.get("networks") or {}) != {"data-plane"}
    ):
        errors.append("postgres_service_contract")
    expected_environment = {
        "POSTGRES_DB": "my_pa",
        "POSTGRES_USER": "my_pa",
        "POSTGRES_PASSWORD": os.environ.get("MY_PA_DB_PASSWORD"),
        "POSTGRES_INITDB_ARGS": "--data-checksums --locale=C.UTF-8 --encoding=UTF8",
    }
    if postgres.get("environment") != expected_environment:
        errors.append("postgres_environment_contract")
    expected_mount = {
        "type": "bind",
        "source": f"{root}/postgres/data",
        "target": "/var/lib/postgresql/data",
    }
    if postgres.get("volumes") != [expected_mount]:
        errors.append("postgres_storage_contract")
    network = (rendered.get("networks") or {}).get("data-plane", {})
    if (
        not isinstance(network, dict)
        or network.get("name") != NETWORK
        or network.get("internal") is not True
        or network.get("external") is not False
    ):
        errors.append("postgres_network_contract")
    if any(value in canonical_render(rendered).decode() for value in SENTINEL_MARKERS):
        errors.append("non_postgres_sentinel_leak")
    return errors


def generate(compose: Path, manifest_path: Path, output: Path) -> list[str]:
    repository = Path(__file__).resolve().parents[2]
    if compose.resolve() != repository / "ops/nas/compose.example.yml":
        return ["canonical_compose_path"]
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = tomllib.loads(manifest_bytes.decode())
        rendered = render_postgres(compose)
        engine = json.loads(_run([docker(), "info", "--format", "{{json .}}"]))
    except (
        OSError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        ValueError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ):
        return ["postgres_bootstrap_input"]
    postgres_image_id = str(
        (manifest.get("images") or {}).get("postgres", {}).get("docker_image_id", "")
    )
    app_image_id = str((manifest.get("images") or {}).get("app", {}).get("docker_image_id", ""))
    errors = render_errors(
        rendered,
        image_id=postgres_image_id,
        root=str(os.environ.get("MY_PA_NAS_ROOT", "")),
    )
    if (
        manifest.get("schema") != "my-pa.nas-image-manifest.v1"
        or manifest.get("status") != "deployable"
        or engine.get("ID") != manifest.get("docker_engine_id")
        or engine.get("Name") != manifest.get("docker_engine_name")
    ):
        errors.append("image_engine_binding")
    try:
        inspected = json.loads(_run([docker(), "image", "inspect", postgres_image_id]))[0]
        app_inspected = json.loads(_run([docker(), "image", "inspect", app_image_id]))[0]
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, TypeError):
        return [*errors, "postgres_image_unreadable"]
    if (
        inspected.get("Id") != postgres_image_id
        or inspected.get("Os") != "linux"
        or inspected.get("Architecture") != "amd64"
    ):
        errors.append("postgres_loaded_identity")
    if (
        app_inspected.get("Id") != app_image_id
        or app_inspected.get("Os") != "linux"
        or app_inspected.get("Architecture") != "amd64"
    ):
        errors.append("database_operator_loaded_identity")
    if errors:
        return errors
    fields = {
        "schema": "my-pa.nas-postgres-bootstrap-admission.v1",
        "status": "admitted",
        "repository_commit": manifest.get("repository_commit"),
        "repository_tree": manifest.get("repository_tree"),
        "docker_engine_id": engine.get("ID"),
        "docker_engine_name": engine.get("Name"),
        "image_manifest_sha256": _sha256(manifest_bytes),
        "compose_sha256": _file_sha256(compose),
        "resolved_postgres_sha256": _sha256(canonical_render(rendered)),
        "postgres_image_id": postgres_image_id,
        "database_operator_image_id": app_image_id,
        "project_name": PROJECT,
        "service_name": SERVICE,
        "data_network": NETWORK,
        "postgres_data_path": f"{os.environ['MY_PA_NAS_ROOT']}/postgres/data",
    }
    lines = [f"{key} = {json.dumps(str(value))}" for key, value in fields.items()]
    lines.append("data_network_internal = true")
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except OSError:
        return ["bootstrap_admission_output"]
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=Path)
    parser.add_argument("image_manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    errors = generate(args.compose, args.image_manifest, args.output)
    if errors:
        print("PostgreSQL bootstrap admission refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print(f"PostgreSQL bootstrap admission written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
