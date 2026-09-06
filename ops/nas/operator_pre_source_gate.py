#!/usr/bin/env python3
"""Authenticate current NAS tooling without executing the selected checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import stat
import subprocess
import tarfile
import tomllib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from image_gate import shape_errors

SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
GIT_OBJECT = re.compile(r"[0-9a-f]{40}\Z")
COMPOSE_VERSION = re.compile(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
PYTHON_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\Z")
ADMISSION_KEYS = {
    "schema",
    "status",
    "repository_commit",
    "repository_tree",
    "repository_source_path",
    "docker_engine_id",
    "docker_engine_name",
    "operator_image_id",
    "operator_manifest_digest",
    "operator_archive_path",
    "operator_archive_sha256",
    "operator_candidate_path",
    "operator_candidate_sha256",
    "operator_metadata_path",
    "operator_metadata_sha256",
    "python_version",
    "git_version",
    "openssl_version",
    "compose_version",
}
CANDIDATE_KEYS = {
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
Runner = Callable[[list[str]], str]


def candidate_shape_errors(data: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if (
        set(data) != CANDIDATE_KEYS
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
        built_at = datetime.fromisoformat(str(data.get("built_at", "")).replace("Z", "+00:00"))
        if built_at.tzinfo != UTC:
            errors.append("candidate_built_at")
    except ValueError:
        errors.append("candidate_built_at")
    return errors


def admission_shape_errors(data: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if (
        set(data) != ADMISSION_KEYS
        or data.get("schema") != "my-pa.nas-operator-runtime-admission.v1"
        or data.get("status") != "admitted"
    ):
        errors.append("operator_admission_shape")
    if not GIT_OBJECT.fullmatch(str(data.get("repository_commit", ""))) or not GIT_OBJECT.fullmatch(
        str(data.get("repository_tree", ""))
    ):
        errors.append("operator_admission_repository_identity")
    if not Path(str(data.get("repository_source_path", ""))).is_absolute():
        errors.append("operator_admission_repository_path")
    if (
        not str(data.get("docker_engine_id", "")).strip()
        or not str(data.get("docker_engine_name", "")).strip()
    ):
        errors.append("operator_admission_engine_identity")
    if not SHA256.fullmatch(str(data.get("operator_image_id", ""))) or not SHA256.fullmatch(
        str(data.get("operator_manifest_digest", ""))
    ):
        errors.append("operator_admission_image_identity")
    for name in (
        "operator_archive_sha256",
        "operator_candidate_sha256",
        "operator_metadata_sha256",
    ):
        if not HEX_SHA256.fullmatch(str(data.get(name, ""))):
            errors.append("operator_admission_artifact_identity")
    for name in ("operator_archive_path", "operator_candidate_path", "operator_metadata_path"):
        value = Path(str(data.get(name, "")))
        if not value.is_absolute():
            errors.append("operator_admission_artifact_path")
    if not PYTHON_VERSION.fullmatch(str(data.get("python_version", ""))):
        errors.append("operator_admission_python_identity")
    if not str(data.get("git_version", "")).startswith("git version ") or not str(
        data.get("openssl_version", "")
    ).startswith("OpenSSL "):
        errors.append("operator_admission_tool_identity")
    if not COMPOSE_VERSION.fullmatch(str(data.get("compose_version", ""))):
        errors.append("operator_admission_compose_identity")
    return errors


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _trusted(path: Path, owner_uid: int) -> bool:
    try:
        metadata = path.lstat()
        return (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == owner_uid
            and stat.S_IMODE(metadata.st_mode) == 0o400
            and metadata.st_nlink == 1
            and path.resolve(strict=True) == path
        )
    except OSError:
        return False


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - closed identity commands assembled below
        command,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def verify(
    admission_path: Path,
    current_source: Path,
    current_manifest_path: Path,
    *,
    expected_host_paths: Mapping[str, Path] | None = None,
    mounted_artifacts: Mapping[str, Path] | None = None,
    owner_uid: int = 0,
    runner: Runner = _run,
) -> list[str]:
    errors: list[str] = []
    if not _trusted(admission_path, owner_uid):
        return ["operator_admission_metadata"]
    try:
        admission = tomllib.loads(admission_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["operator_admission_unreadable"]
    errors.extend(admission_shape_errors(admission))
    if errors:
        return errors
    artifact_names = ("archive", "candidate", "metadata")
    admitted_artifacts = {
        name: Path(str(admission.get(f"operator_{name}_path", ""))) for name in artifact_names
    }
    host_paths = expected_host_paths or {
        "admission": admission_path,
        "current_source": current_source,
        "current_manifest": current_manifest_path,
        **admitted_artifacts,
    }
    required_host_paths = {
        "admission",
        "current_source",
        "current_manifest",
        "archive",
        "candidate",
        "metadata",
    }
    if (
        set(host_paths) != required_host_paths
        or any(not path.is_absolute() for path in host_paths.values())
        or len({str(path) for path in host_paths.values()}) != len(required_host_paths)
    ):
        return ["operator_input_path_identity"]
    if Path(str(admission.get("repository_source_path", ""))) != host_paths[
        "current_source"
    ] or any(admitted_artifacts[name] != host_paths[name] for name in artifact_names):
        return ["operator_input_path_identity"]
    artifacts = dict(mounted_artifacts or admitted_artifacts)
    if set(artifacts) != set(artifact_names):
        return ["operator_input_path_identity"]
    if any(not _trusted(path, owner_uid) for path in artifacts.values()):
        return [*errors, "operator_artifact_metadata"]
    try:
        candidate = tomllib.loads(artifacts["candidate"].read_text(encoding="utf-8"))
        metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))
        manifest = tomllib.loads(current_manifest_path.read_text(encoding="utf-8"))
        with tarfile.open(artifacts["archive"], "r:*") as archive:
            manifest_member = archive.extractfile("manifest.json")
            if manifest_member is None:
                raise ValueError("archive manifest is not a file")
            archive_manifest = json.loads(manifest_member.read())[0]
    except (OSError, KeyError, TypeError, ValueError, tarfile.TarError, tomllib.TOMLDecodeError):
        return [*errors, "operator_artifact_unreadable"]
    if not isinstance(metadata, dict) or not isinstance(archive_manifest, dict):
        return [*errors, "operator_artifact_unreadable"]
    errors.extend(candidate_shape_errors(candidate))
    for name, path in artifacts.items():
        if _sha256(path) != admission.get(f"operator_{name}_sha256"):
            errors.append(f"operator_{name}_checksum")
    if (
        candidate.get("repository_commit") != admission.get("repository_commit")
        or candidate.get("repository_tree") != admission.get("repository_tree")
        or candidate.get("docker_image_id") != admission.get("operator_image_id")
        or candidate.get("oci_manifest_digest") != admission.get("operator_manifest_digest")
        or candidate.get("archive_sha256") != admission.get("operator_archive_sha256")
        or candidate.get("build_metadata_sha256") != admission.get("operator_metadata_sha256")
        or metadata.get("containerimage.digest") != admission.get("operator_manifest_digest")
        or metadata.get("containerimage.config.digest") != admission.get("operator_image_id")
        or "sha256:" + str(archive_manifest.get("Config", "")).removesuffix(".json")
        != admission.get("operator_image_id")
    ):
        errors.append("operator_artifact_binding")
    if shape_errors(manifest):
        errors.append("current_gate_manifest_shape")
    if errors:
        return errors
    try:
        head = runner(["git", "-C", str(current_source), "rev-parse", "HEAD"])
        tree = runner(["git", "-C", str(current_source), "rev-parse", "HEAD^{tree}"])
        root = runner(["git", "-C", str(current_source), "rev-parse", "--show-toplevel"])
        dirty = runner(
            ["git", "-C", str(current_source), "status", "--porcelain", "--untracked-files=all"]
        )
        engine = json.loads(runner(["/usr/local/bin/docker", "info", "--format", "{{json .}}"]))
        inspected = json.loads(
            runner(
                [
                    "/usr/local/bin/docker",
                    "image",
                    "inspect",
                    str(admission.get("operator_image_id", "")),
                ]
            )
        )[0]
        git_version = runner(["git", "--version"])
        openssl_version = runner(["/usr/bin/openssl", "version"])
        compose_version = runner(["/usr/local/bin/docker", "compose", "version", "--short"])
    except (OSError, IndexError, TypeError, ValueError, subprocess.SubprocessError):
        return [*errors, "operator_live_identity"]
    if not isinstance(engine, dict) or not isinstance(inspected, dict):
        return [*errors, "operator_live_identity"]
    if (
        root != str(current_source)
        or dirty
        or admission.get("repository_commit") != head
        or admission.get("repository_tree") != tree
        or manifest.get("repository_commit") != head
        or manifest.get("repository_tree") != tree
    ):
        errors.append("current_source_identity")
    if (
        admission.get("docker_engine_id") != engine.get("ID")
        or admission.get("docker_engine_name") != engine.get("Name")
        or manifest.get("docker_engine_id") != engine.get("ID")
        or manifest.get("docker_engine_name") != engine.get("Name")
    ):
        errors.append("current_engine_identity")
    labels = (inspected.get("Config") or {}).get("Labels") or {}
    if (
        inspected.get("Id") != admission.get("operator_image_id")
        or inspected.get("Os") != "linux"
        or inspected.get("Architecture") != "amd64"
        or labels.get("org.opencontainers.image.revision") != head
        or labels.get("org.opencontainers.image.created") != candidate.get("built_at")
        or labels.get("io.my-pa.repository-tree") != tree
        or labels.get("io.my-pa.operator-runtime") != "python-3.12"
        or labels.get("io.my-pa.target-platform") != "linux/amd64"
    ):
        errors.append("operator_image_identity")
    if (
        admission.get("python_version") != platform.python_version()
        or admission.get("git_version") != git_version
        or admission.get("openssl_version") != openssl_version
        or admission.get("compose_version") != compose_version
    ):
        errors.append("operator_tool_identity")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("admission", type=Path)
    parser.add_argument("current_source", type=Path)
    parser.add_argument("current_manifest", type=Path)
    parser.add_argument("host_admission", type=Path)
    parser.add_argument("host_current_source", type=Path)
    parser.add_argument("host_current_manifest", type=Path)
    parser.add_argument("host_archive", type=Path)
    parser.add_argument("host_candidate", type=Path)
    parser.add_argument("host_metadata", type=Path)
    parser.add_argument("mounted_archive", type=Path)
    parser.add_argument("mounted_candidate", type=Path)
    parser.add_argument("mounted_metadata", type=Path)
    args = parser.parse_args()
    errors = verify(
        args.admission,
        args.current_source,
        args.current_manifest,
        expected_host_paths={
            "admission": args.host_admission,
            "current_source": args.host_current_source,
            "current_manifest": args.host_current_manifest,
            "archive": args.host_archive,
            "candidate": args.host_candidate,
            "metadata": args.host_metadata,
        },
        mounted_artifacts={
            "archive": args.mounted_archive,
            "candidate": args.mounted_candidate,
            "metadata": args.mounted_metadata,
        },
    )
    if errors:
        print("NAS pre-source gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print("NAS pre-source gate passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
