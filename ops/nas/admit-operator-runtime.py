#!/usr/bin/env python3
"""Admit the short-lived Python operator runtime against the live NAS engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from archive_image import inspect_archive
from nas_tools import docker

SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_OBJECT = re.compile(r"[0-9a-f]{40}\Z")
EXPECTED_KEYS = {
    "schema",
    "status",
    "repository_commit",
    "repository_tree",
    "built_at",
    "target_os",
    "target_architecture",
    "oci_manifest_digest",
    "docker_image_id",
    "archive_sha256",
    "build_metadata_sha256",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - closed operator tool argument vectors
        command, check=True, capture_output=True, text=True
    ).stdout.strip()


def admit(candidate: Path, archive: Path, metadata: Path, output: Path) -> list[str]:
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["candidate_unreadable"]
    errors: list[str] = []
    if (
        set(data) != EXPECTED_KEYS
        or data.get("schema") != "my-pa.nas-operator-runtime-candidate.v1"
        or data.get("status") != "candidate_not_admitted"
    ):
        errors.append("candidate_shape")
    if data.get("target_os") != "linux" or data.get("target_architecture") != "amd64":
        errors.append("candidate_platform")
    if not GIT_OBJECT.fullmatch(str(data.get("repository_commit", ""))) or not GIT_OBJECT.fullmatch(
        str(data.get("repository_tree", ""))
    ):
        errors.append("candidate_repository_identity")
    if not SHA256.fullmatch(str(data.get("oci_manifest_digest", ""))) or not SHA256.fullmatch(
        str(data.get("docker_image_id", ""))
    ):
        errors.append("candidate_image_identity")
    if not HEX_SHA256.fullmatch(str(data.get("archive_sha256", ""))) or not HEX_SHA256.fullmatch(
        str(data.get("build_metadata_sha256", ""))
    ):
        errors.append("candidate_checksum_shape")
    try:
        archive_identity = inspect_archive(archive)
        metadata_data = json.loads(metadata.read_text(encoding="utf-8"))
        engine = json.loads(_run([docker(), "info", "--format", "{{json .}}"]))
        inspected = json.loads(_run([docker(), "image", "inspect", str(data["docker_image_id"])]))[
            0
        ]
        git_version = _run(["git", "--version"])
        openssl_version = _run(["/usr/bin/openssl", "version"])
    except (
        OSError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ):
        return [*errors, "live_operator_inspection"]
    if _sha256(archive) != data.get("archive_sha256"):
        errors.append("archive_checksum")
    if _sha256(metadata) != data.get("build_metadata_sha256"):
        errors.append("metadata_checksum")
    if (
        metadata_data.get("containerimage.digest") != data.get("oci_manifest_digest")
        or metadata_data.get("containerimage.config.digest") != data.get("docker_image_id")
        or archive_identity.config_digest != data.get("docker_image_id")
    ):
        errors.append("archive_metadata_identity")
    python_version = tuple(map(int, platform.python_version_tuple()[:2]))
    if python_version < (3, 12):
        errors.append("python_version")
    if not git_version.startswith("git version ") or not openssl_version.startswith("OpenSSL "):
        errors.append("operator_tools")
    if (
        not isinstance(engine, dict)
        or engine.get("OSType") != "linux"
        or engine.get("Architecture") != "x86_64"
        or not str(engine.get("ID", "")).strip()
        or not str(engine.get("Name", "")).strip()
    ):
        errors.append("docker_engine")
    labels = (inspected.get("Config") or {}).get("Labels") or {}
    if (
        inspected.get("Id") != data.get("docker_image_id")
        or inspected.get("Os") != "linux"
        or inspected.get("Architecture") != "amd64"
        or labels.get("org.opencontainers.image.revision") != data.get("repository_commit")
        or labels.get("io.my-pa.repository-tree") != data.get("repository_tree")
        or labels.get("io.my-pa.target-platform") != "linux/amd64"
        or labels.get("io.my-pa.operator-runtime") != "python-3.12"
    ):
        errors.append("loaded_operator_identity")
    if errors:
        return errors
    lines = [
        'schema = "my-pa.nas-operator-runtime-admission.v1"',
        'status = "admitted"',
        f"repository_commit = {json.dumps(str(data['repository_commit']))}",
        f"repository_tree = {json.dumps(str(data['repository_tree']))}",
        f"docker_engine_id = {json.dumps(str(engine['ID']))}",
        f"docker_engine_name = {json.dumps(str(engine['Name']))}",
        f"operator_image_id = {json.dumps(str(data['docker_image_id']))}",
        f"operator_manifest_digest = {json.dumps(str(data['oci_manifest_digest']))}",
        f"operator_archive_sha256 = {json.dumps(str(data['archive_sha256']))}",
        f"python_version = {json.dumps('.'.join(map(str, sys.version_info[:3])))}",
        f"git_version = {json.dumps(git_version)}",
        f"openssl_version = {json.dumps(openssl_version)}",
    ]
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except OSError:
        return ["output_not_exclusive"]
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("archive", type=Path)
    parser.add_argument("metadata", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    errors = admit(args.candidate, args.archive, args.metadata, args.output)
    if errors:
        print("NAS operator runtime admission refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print(f"admitted NAS operator runtime written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
