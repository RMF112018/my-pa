#!/usr/bin/env python3
"""Verify NAS image evidence against the live Docker engine; never build or start."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any

from nas_tools import docker

SERVICES = {"app", "web", "postgres", "proxy"}
POSTGRES_REFERENCE = (
    "postgres@sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"
)
POSTGRES_SOURCE_TAG = "postgres:17.10"
POSTGRES_INDEX_DIGEST = "sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"
SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_OBJECT = re.compile(r"[0-9a-f]{40}\Z")
TOP_LEVEL_KEYS = {
    "schema",
    "status",
    "repository_commit",
    "repository_tree",
    "source_clean",
    "built_at",
    "target_os",
    "target_architecture",
    "docker_engine_id",
    "docker_engine_name",
    "python_runtime_lock_sha256",
    "postgres_source_tag",
    "postgres_index_digest",
    "images",
}
IMAGE_KEYS = {
    "reference",
    "load_reference",
    "oci_manifest_digest",
    "docker_image_id",
    "archive_sha256",
    "build_metadata_sha256",
}


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_json(command: list[str]) -> object:
    completed = subprocess.run(  # noqa: S603 - fixed executable and bounded arguments
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _shape_errors(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if set(data) != TOP_LEVEL_KEYS:
        errors.append("top_level_schema")
    if data.get("schema") != "my-pa.nas-image-manifest.v1":
        errors.append("schema")
    if data.get("status") != "deployable":
        errors.append("status_not_deployable")
    if data.get("target_os") != "linux" or data.get("target_architecture") != "amd64":
        errors.append("platform")
    if data.get("source_clean") is not True:
        errors.append("source_dirty")
    if not GIT_OBJECT.fullmatch(str(data.get("repository_commit", ""))):
        errors.append("repository_commit")
    if not GIT_OBJECT.fullmatch(str(data.get("repository_tree", ""))):
        errors.append("repository_tree")
    if not HEX_SHA256.fullmatch(str(data.get("python_runtime_lock_sha256", ""))):
        errors.append("python_runtime_lock_sha256")
    if data.get("postgres_source_tag") != POSTGRES_SOURCE_TAG:
        errors.append("postgres_source_tag")
    if data.get("postgres_index_digest") != POSTGRES_INDEX_DIGEST:
        errors.append("postgres_index_digest")
    if not str(data.get("docker_engine_id", "")).strip():
        errors.append("docker_engine_id")
    if not str(data.get("docker_engine_name", "")).strip():
        errors.append("docker_engine_name")
    try:
        built_at = datetime.fromisoformat(str(data.get("built_at", "")).replace("Z", "+00:00"))
        if built_at.utcoffset() is None:
            raise ValueError
    except ValueError:
        errors.append("built_at")

    images = data.get("images", {})
    if not isinstance(images, dict) or set(images) != SERVICES:
        errors.append("image_set")
        return errors
    for name, value in images.items():
        if not isinstance(value, dict) or set(value) != IMAGE_KEYS:
            errors.append(f"{name}_schema")
            continue
        digest = str(value.get("oci_manifest_digest", ""))
        image_id = str(value.get("docker_image_id", ""))
        reference = str(value.get("reference", ""))
        load_reference = str(value.get("load_reference", ""))
        checksum = str(value.get("archive_sha256", ""))
        metadata_checksum = str(value.get("build_metadata_sha256", ""))
        if not SHA256.fullmatch(digest) or not SHA256.fullmatch(image_id):
            errors.append(f"{name}_identity")
        if reference.rpartition("@")[2] != digest:
            errors.append(f"{name}_reference_digest")
        if load_reference != image_id:
            errors.append(f"{name}_load_reference")
        if not HEX_SHA256.fullmatch(checksum) or not HEX_SHA256.fullmatch(metadata_checksum):
            errors.append(f"{name}_archive_checksum")
        if digest == image_id:
            errors.append(f"{name}_identity_conflation")
        if name == "postgres" and reference != POSTGRES_REFERENCE:
            errors.append("postgres_official_child_reference")
        if name == "proxy" and "@sha256:" not in reference:
            errors.append("proxy_reference_digest")
    identities = [
        str(value.get("docker_image_id", ""))
        for value in images.values()
        if isinstance(value, dict)
    ]
    digests = [
        str(value.get("oci_manifest_digest", ""))
        for value in images.values()
        if isinstance(value, dict)
    ]
    if len(set(identities)) != len(SERVICES) or len(set(digests)) != len(SERVICES):
        errors.append("service_identity_conflation")
    return errors


def shape_errors(data: dict[str, Any]) -> list[str]:
    """Return authoritative deployable-manifest shape refusals."""
    return _shape_errors(data)


def verify(path: Path, archive_dir: Path | None = None, *, live: bool = False) -> list[str]:
    """Return every refusal reason; passing requires live Docker and all archives."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["manifest_unreadable"]
    errors = shape_errors(data)
    if not live:
        return [*errors, "live_verification_required"]
    if archive_dir is None:
        errors.append("archive_dir_required")

    try:
        info = _run_json([docker(), "info", "--format", "{{json .}}"])
        if not isinstance(info, dict):
            raise TypeError
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        errors.append("docker_info")
        return errors
    if info.get("OSType") != "linux" or info.get("Architecture") != "x86_64":
        errors.append("live_docker_platform")
    if info.get("ID") != data.get("docker_engine_id") or info.get("Name") != data.get(
        "docker_engine_name"
    ):
        errors.append("live_docker_identity")

    images = data.get("images", {})
    if not isinstance(images, dict):
        return errors
    expected_labels = {
        "org.opencontainers.image.revision": data.get("repository_commit"),
        "io.my-pa.repository-tree": data.get("repository_tree"),
        "org.opencontainers.image.created": data.get("built_at"),
        "io.my-pa.target-platform": "linux/amd64",
    }
    for name in sorted(SERVICES):
        value = images.get(name)
        if not isinstance(value, dict):
            continue
        image_id = str(value.get("docker_image_id", ""))
        try:
            inspected = _run_json([docker(), "image", "inspect", image_id])
            if not isinstance(inspected, list) or not inspected:
                raise TypeError
            image = inspected[0]
            if not isinstance(image, dict):
                raise TypeError
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError, TypeError):
            errors.append(f"{name}_inspect")
            continue
        if image.get("Os") != "linux" or image.get("Architecture") != "amd64":
            errors.append(f"{name}_loaded_platform")
        if image.get("Id") != value.get("docker_image_id"):
            errors.append(f"{name}_loaded_image_id")
        labels = (image.get("Config") or {}).get("Labels") or {}
        if name not in {"postgres", "proxy"} and any(
            labels.get(key) != expected for key, expected in expected_labels.items()
        ):
            errors.append(f"{name}_provenance_labels")
        if name == "app" and labels.get("io.my-pa.python-runtime-lock-sha256") != data.get(
            "python_runtime_lock_sha256"
        ):
            errors.append("app_runtime_lock_label")
        if archive_dir is not None:
            archive = archive_dir / f"{name}.tar"
            if not archive.is_file() or _stream_sha256(archive) != value.get("archive_sha256"):
                errors.append(f"{name}_archive_mismatch")
            metadata_path = archive_dir / f"{name}.metadata.json"
            if not metadata_path.is_file() or _stream_sha256(metadata_path) != value.get(
                "build_metadata_sha256"
            ):
                errors.append(f"{name}_metadata_mismatch")
            else:
                try:
                    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    errors.append(f"{name}_metadata_unreadable")
                else:
                    if metadata.get("containerimage.digest") != value.get(
                        "oci_manifest_digest"
                    ) or metadata.get("containerimage.config.digest") != value.get(
                        "docker_image_id"
                    ):
                        errors.append(f"{name}_metadata_identity")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--archive-dir", required=True, type=Path)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    errors = verify(args.manifest, args.archive_dir, live=args.live)
    if errors:
        print("NAS image gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print("NAS image gate passed against the live linux/amd64 Docker engine")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
