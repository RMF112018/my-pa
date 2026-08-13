#!/usr/bin/env python3
"""Revalidate the exact credential-independent PostgreSQL bootstrap render."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import tomllib
from pathlib import Path
from types import ModuleType

from nas_tools import docker

CANONICAL_ADMISSION = Path("/etc/my-pa/postgres-bootstrap-admission.toml")


def _generator() -> ModuleType:
    path = Path(__file__).with_name("generate-postgres-bootstrap-admission.py")
    spec = importlib.util.spec_from_file_location("nas_postgres_bootstrap_generator", path)
    if spec is None or spec.loader is None:
        raise ImportError
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted(path: Path, owner_uid: int) -> bool:
    try:
        status = path.lstat()
        return (
            stat.S_ISREG(status.st_mode)
            and status.st_uid == owner_uid
            and stat.S_IMODE(status.st_mode) == 0o400
            and status.st_nlink == 1
            and path.resolve(strict=True) == path
        )
    except OSError:
        return False


def verify(
    compose: Path,
    manifest_path: Path,
    *,
    admission_path: Path = CANONICAL_ADMISSION,
    owner_uid: int = 0,
) -> list[str]:
    repository = Path(__file__).resolve().parents[2]
    errors: list[str] = []
    if compose.resolve() != repository / "ops/nas/compose.example.yml":
        errors.append("canonical_compose_path")
    if not _trusted(admission_path, owner_uid):
        return [*errors, "bootstrap_admission_metadata"]
    try:
        generator = _generator()
        manifest_bytes = manifest_path.read_bytes()
        manifest = tomllib.loads(manifest_bytes.decode())
        admission = tomllib.loads(admission_path.read_text(encoding="utf-8"))
        rendered = generator.render_postgres(compose)
        engine = json.loads(
            subprocess.run(  # noqa: S603 - fixed Docker inspection
                [docker(), "info", "--format", "{{json .}}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (
        OSError,
        ImportError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        ValueError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ):
        return [*errors, "bootstrap_identity_input"]
    postgres_image_id = str(
        (manifest.get("images") or {}).get("postgres", {}).get("docker_image_id", "")
    )
    app_image_id = str((manifest.get("images") or {}).get("app", {}).get("docker_image_id", ""))
    try:
        inspected = json.loads(
            subprocess.run(  # noqa: S603 - exact admitted image identities
                [docker(), "image", "inspect", postgres_image_id, app_image_id],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return [*errors, "bootstrap_loaded_images"]
    loaded = {
        str(value.get("Id")): (value.get("Os"), value.get("Architecture"))
        for value in inspected
        if isinstance(value, dict)
    }
    if loaded != {
        postgres_image_id: ("linux", "amd64"),
        app_image_id: ("linux", "amd64"),
    }:
        errors.append("bootstrap_loaded_images")
    errors.extend(
        generator.render_errors(
            rendered,
            image_id=postgres_image_id,
            root=str(os.environ.get("MY_PA_NAS_ROOT", "")),
        )
    )
    expected = {
        "schema": "my-pa.nas-postgres-bootstrap-admission.v1",
        "status": "admitted",
        "repository_commit": manifest.get("repository_commit"),
        "repository_tree": manifest.get("repository_tree"),
        "docker_engine_id": engine.get("ID"),
        "docker_engine_name": engine.get("Name"),
        "image_manifest_sha256": _sha256(manifest_bytes),
        "compose_sha256": _file_sha256(compose),
        "resolved_postgres_sha256": _sha256(
            generator.canonical_render(generator.binding_render(rendered))
        ),
        "postgres_image_id": postgres_image_id,
        "database_operator_image_id": app_image_id,
        "project_name": generator.PROJECT,
        "service_name": generator.SERVICE,
        "data_network": generator.NETWORK,
        "postgres_data_path": f"{os.environ.get('MY_PA_NAS_ROOT', '')}/postgres/data",
        "data_network_internal": True,
    }
    if set(admission) != set(expected) or any(
        admission.get(key) != value for key, value in expected.items()
    ):
        errors.append("bootstrap_admission_binding")
    if manifest.get("docker_engine_id") != engine.get("ID") or manifest.get(
        "docker_engine_name"
    ) != engine.get("Name"):
        errors.append("bootstrap_engine_binding")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=Path)
    parser.add_argument("image_manifest", type=Path)
    parser.add_argument("--admission", type=Path, default=CANONICAL_ADMISSION)
    args = parser.parse_args()
    errors = verify(args.compose, args.image_manifest, admission_path=args.admission)
    if errors:
        print("PostgreSQL bootstrap identity refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
