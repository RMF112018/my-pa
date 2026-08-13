#!/usr/bin/env python3
"""Generate exact six-service NAS runtime admission from rendered Compose."""

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

SERVICES = {"postgres", "gateway", "worker-enrollment", "worker-capture", "web", "proxy"}


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - closed Docker Compose argument vectors
        command, check=True, capture_output=True, text=True
    ).stdout


def _render(compose: Path, overlay: Path | None) -> dict[str, Any]:
    command = [docker(), "compose", "--file", str(compose)]
    if overlay is not None:
        command.extend(["--file", str(overlay)])
    command.extend(["--profile", "nas-01-contract-only", "config", "--format", "json"])
    rendered = json.loads(_run(command))
    if not isinstance(rendered, dict):
        raise ValueError
    return rendered


def _digest(rendered: dict[str, Any]) -> str:
    value = json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def _quote(value: object) -> str:
    return json.dumps(str(value))


def generate(compose: Path, overlay: Path, manifest_path: Path, output: Path) -> list[str]:
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = tomllib.loads(manifest_bytes.decode())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ["image_manifest_unreadable"]
    if manifest.get("status") != "deployable":
        return ["image_manifest_not_deployable"]
    try:
        smoke = _render(compose, None)
        pilot = _render(compose, overlay)
        engine = json.loads(_run([docker(), "info", "--format", "{{json .}}"]))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return ["runtime_render_unreadable"]
    if engine.get("ID") != manifest.get("docker_engine_id") or engine.get("Name") != manifest.get(
        "docker_engine_name"
    ):
        return ["runtime_engine_binding"]
    service_images = {
        name: value.get("image")
        for name, value in smoke.get("services", {}).items()
        if isinstance(value, dict)
    }
    if set(service_images) != SERVICES or any(not value for value in service_images.values()):
        return ["runtime_service_image_set"]
    image_sections = manifest.get("images", {})
    expected_ids = {
        "postgres": image_sections.get("postgres", {}).get("docker_image_id"),
        "gateway": image_sections.get("app", {}).get("docker_image_id"),
        "worker-enrollment": image_sections.get("app", {}).get("docker_image_id"),
        "worker-capture": image_sections.get("app", {}).get("docker_image_id"),
        "web": image_sections.get("web", {}).get("docker_image_id"),
        "proxy": image_sections.get("proxy", {}).get("docker_image_id"),
    }
    errors: list[str] = []
    for name, reference in service_images.items():
        try:
            inspected = json.loads(_run([docker(), "image", "inspect", str(reference)]))[0]
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError):
            errors.append(f"{name}_image_unreadable")
            continue
        if inspected.get("Id") != expected_ids[name]:
            errors.append(f"{name}_image_identity")
    if errors:
        return errors
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    lines = [
        'schema = "my-pa.nas-runtime-admission.v1"',
        'status = "admitted"',
        f"docker_engine_id = {_quote(engine['ID'])}",
        f"docker_engine_name = {_quote(engine['Name'])}",
        f'image_manifest_sha256 = "{manifest_digest}"',
        "",
        "[resolved_compose_sha256]",
        f'smoke = "{_digest(smoke)}"',
        f'pilot = "{_digest(pilot)}"',
        "",
        "[service_images]",
    ]
    lines.extend(f"{name} = {_quote(service_images[name])}" for name in sorted(SERVICES))
    lines.extend(["", "[service_image_ids]"])
    lines.extend(f"{name} = {_quote(expected_ids[name])}" for name in sorted(SERVICES))
    try:
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    except OSError:
        return ["runtime_admission_output"]
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compose", type=Path)
    parser.add_argument("pilot_overlay", type=Path)
    parser.add_argument("image_manifest", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    errors = generate(args.compose, args.pilot_overlay, args.image_manifest, args.output)
    if errors:
        print("NAS runtime admission refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print(f"NAS runtime admission written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
