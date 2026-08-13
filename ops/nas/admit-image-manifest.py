#!/usr/bin/env python3
"""Promote a byte-verified candidate image manifest against the live NAS engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import tomllib
from pathlib import Path
from typing import Any

import image_gate
from nas_tools import docker


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _quote(value: object) -> str:
    return json.dumps(str(value))


def _render(data: dict[str, Any]) -> str:
    lines = [
        f"schema = {_quote(data['schema'])}",
        'status = "deployable"',
        f"repository_commit = {_quote(data['repository_commit'])}",
        f"repository_tree = {_quote(data['repository_tree'])}",
        "source_clean = true",
        f"built_at = {_quote(data['built_at'])}",
        'target_os = "linux"',
        'target_architecture = "amd64"',
        f"docker_engine_id = {_quote(data['docker_engine_id'])}",
        f"docker_engine_name = {_quote(data['docker_engine_name'])}",
        f"python_runtime_lock_sha256 = {_quote(data['python_runtime_lock_sha256'])}",
        f"postgres_source_tag = {_quote(data['postgres_source_tag'])}",
        f"postgres_index_digest = {_quote(data['postgres_index_digest'])}",
    ]
    for name in sorted(image_gate.SERVICES):
        lines.append("")
        lines.append(f"[images.{name}]")
        for key in sorted(image_gate.IMAGE_KEYS):
            lines.append(f"{key} = {_quote(data['images'][name][key])}")
    return "\n".join(lines) + "\n"


def admit(candidate: Path, archive_dir: Path, output: Path) -> list[str]:
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return ["candidate_unreadable"]
    if data.get("status") != "candidate_not_deployable":
        return ["candidate_status"]
    errors: list[str] = []
    images = data.get("images", {})
    if not isinstance(images, dict) or set(images) != image_gate.SERVICES:
        return ["candidate_image_set"]
    for name in sorted(image_gate.SERVICES):
        value = images[name]
        archive = archive_dir / f"{name}.tar"
        metadata = archive_dir / f"{name}.metadata.json"
        if _sha256(archive) != value.get("archive_sha256"):
            errors.append(f"{name}_archive_mismatch")
        if _sha256(metadata) != value.get("build_metadata_sha256"):
            errors.append(f"{name}_metadata_mismatch")
    if errors:
        return errors
    try:
        engine = json.loads(
            subprocess.run(  # noqa: S603 - resolved Docker CLI and fixed arguments
                [docker(), "info", "--format", "{{json .}}"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return ["docker_authority"]
    if engine.get("OSType") != "linux" or engine.get("Architecture") != "x86_64":
        errors.append("live_docker_platform")
    data["status"] = "deployable"
    data["docker_engine_id"] = engine.get("ID", "")
    data["docker_engine_name"] = engine.get("Name", "")
    errors.extend(image_gate._shape_errors(data))
    if errors:
        return errors
    rendered = _render(data)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8") as staged:
        staged.write(rendered)
        staged.flush()
        errors = image_gate.verify(Path(staged.name), archive_dir, live=True)
    if errors:
        return errors
    try:
        descriptor = output.open("x", encoding="utf-8")
    except OSError:
        return ["output_not_exclusive"]
    with descriptor:
        descriptor.write(rendered)
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("archive_directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    errors = admit(args.candidate, args.archive_directory, args.output)
    if errors:
        print("NAS image admission refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print(f"deployable image manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
