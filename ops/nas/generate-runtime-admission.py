#!/usr/bin/env python3
"""Generate exact six-service NAS runtime admission from rendered Compose."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets as secure_random
import stat
import subprocess
import tomllib
from contextlib import suppress
from pathlib import Path
from typing import Any

from nas_tools import docker
from runtime_identity_gate import (
    ADMISSION_KEYS,
    CANONICAL_ADMISSION,
    PRESERVED_PUBLIC_ADMISSION,
    PRESERVED_PUBLIC_ENV,
    PRESERVED_PUBLIC_SOURCE,
    _trusted_file,
    preserved_compose_prefix,
    preserved_public_source_errors,
    public_browser_binding,
    public_browser_scope_errors,
)

SERVICES = {"postgres", "gateway", "worker-enrollment", "worker-capture", "web", "proxy"}


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - closed Docker Compose argument vectors
        command, check=True, capture_output=True, text=True
    ).stdout


def _render(
    compose: Path,
    overlay: Path | None,
    *,
    preserved_env: Path | None = None,
) -> dict[str, Any]:
    command = (
        preserved_compose_prefix(compose, preserved_env)
        if preserved_env is not None
        else [docker(), "compose", "--file", str(compose)]
    )
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


def _publish_preserved_admission(output: Path, body: bytes, *, owner_uid: int = 0) -> None:
    """Publish only the fixed f7 artifact, without replacing any existing leaf.

    A crash after link but before unlink leaves two links and must refuse on
    readmission. This is no-clobber publication, not recovery from a root race.
    """
    if output != PRESERVED_PUBLIC_ADMISSION:
        raise ValueError("preserved_public_admission_path")
    parent = output.parent
    before = parent.lstat()
    if (
        parent.resolve(strict=True) != parent
        or not stat.S_ISDIR(before.st_mode)
        or before.st_uid != owner_uid
        or stat.S_IMODE(before.st_mode) != 0o700
    ):
        raise ValueError("preserved_public_admission_parent")
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = f".{output.name}.{secure_random.token_hex(16)}.tmp"
    owned: tuple[int, int] | None = None
    try:
        opened_parent = os.fstat(directory)
        if (opened_parent.st_dev, opened_parent.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("preserved_public_admission_parent")
        descriptor = os.open(
            temporary,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
            dir_fd=directory,
        )
        with os.fdopen(descriptor, "w+b") as stream:
            state = os.fstat(stream.fileno())
            owned = (state.st_dev, state.st_ino)
            if state.st_uid != owner_uid or stat.S_IMODE(state.st_mode) != 0o400:
                raise ValueError("preserved_public_admission_metadata")
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            if stream.read() != body:
                raise ValueError("preserved_public_admission_readback")
            state = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
            if (
                (state.st_dev, state.st_ino) != owned
                or state.st_nlink != 1
                or state.st_uid != owner_uid
                or stat.S_IMODE(state.st_mode) != 0o400
                or not stat.S_ISREG(state.st_mode)
                or state.st_size != len(body)
            ):
                raise ValueError("preserved_public_admission_metadata")
            current = parent.lstat()
            if (
                (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
                or current.st_uid != owner_uid
                or stat.S_IMODE(current.st_mode) != 0o700
                or parent.resolve(strict=True) != parent
            ):
                raise ValueError("preserved_public_admission_parent")
            os.link(
                temporary,
                output.name,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            linked = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
            if (linked.st_dev, linked.st_ino) != owned or linked.st_nlink != 2:
                raise ValueError("preserved_public_admission_cleanup_identity")
            os.unlink(temporary, dir_fd=directory)
            owned = None
            os.fsync(directory)
            final = os.stat(output.name, dir_fd=directory, follow_symlinks=False)
            if (
                (final.st_dev, final.st_ino) != (state.st_dev, state.st_ino)
                or final.st_uid != owner_uid
                or stat.S_IMODE(final.st_mode) != 0o400
                or final.st_nlink != 1
                or not _trusted_file(output, owner_uid)
            ):
                raise ValueError("preserved_public_admission_metadata")
            stream.seek(0)
            if stream.read() != body:
                raise ValueError("preserved_public_admission_readback")
            readback = os.open(output.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            with os.fdopen(readback, "rb") as verified:
                reopened = os.fstat(verified.fileno())
                fields = (
                    "st_dev",
                    "st_ino",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                    "st_mode",
                    "st_uid",
                    "st_nlink",
                )
                if (
                    any(getattr(reopened, field) != getattr(final, field) for field in fields)
                    or verified.read(len(body) + 1) != body
                ):
                    raise ValueError("preserved_public_admission_readback")
    finally:
        try:
            if owned is not None:
                remaining: os.stat_result | None = None
                with suppress(FileNotFoundError):
                    remaining = os.stat(temporary, dir_fd=directory, follow_symlinks=False)
                if remaining is not None and (remaining.st_dev, remaining.st_ino) == owned:
                    os.unlink(temporary, dir_fd=directory)
                    os.fsync(directory)
        finally:
            os.close(directory)


def generate(
    compose: Path,
    overlay: Path,
    manifest_path: Path,
    output: Path,
    *,
    public_overlay: Path | None = None,
    preserved_source: Path | None = None,
) -> list[str]:
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = tomllib.loads(manifest_bytes.decode())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return ["image_manifest_unreadable"]
    if manifest.get("status") != "deployable":
        return ["image_manifest_not_deployable"]
    binding = None
    try:
        if public_overlay is not None:
            source = preserved_source or Path(__file__).resolve().parents[2]
            if compose != source / "ops/nas/compose.example.yml":
                return ["public_browser_compose_path"]
            binding = public_browser_binding(source, public_overlay, manifest)
            if preserved_source is not None:
                source_errors = preserved_public_source_errors(
                    source, manifest_path, manifest, owner_uid=0, runner=_run
                )
                if source_errors:
                    return source_errors
                if (
                    preserved_source != PRESERVED_PUBLIC_SOURCE
                    or output != PRESERVED_PUBLIC_ADMISSION
                ):
                    return ["preserved_public_admission_path"]
                if not _trusted_file(CANONICAL_ADMISSION, 0):
                    return ["preserved_public_baseline_metadata"]
                original_bytes = CANONICAL_ADMISSION.read_bytes()
                original = tomllib.loads(original_bytes.decode())
                if (
                    set(original) != ADMISSION_KEYS
                    or original.get("schema") != "my-pa.nas-runtime-admission.v1"
                    or original.get("status") != "admitted"
                    or original.get("image_manifest_sha256")
                    != hashlib.sha256(manifest_bytes).hexdigest()
                    or original.get("docker_engine_id") != manifest.get("docker_engine_id")
                    or original.get("docker_engine_name") != manifest.get("docker_engine_name")
                ):
                    return ["preserved_public_baseline_binding"]
                binding["previous_runtime_admission_sha256"] = hashlib.sha256(
                    original_bytes
                ).hexdigest()
        elif preserved_source is not None:
            return ["preserved_public_overlay_required"]
        env = PRESERVED_PUBLIC_ENV if preserved_source is not None else None
        if env is None:
            smoke = _render(compose, public_overlay)
            pilot = _render(compose, overlay)
        else:
            smoke = _render(compose, public_overlay, preserved_env=env)
            pilot = _render(compose, overlay, preserved_env=env)
        if public_overlay is not None:
            base_render = _render(compose, None, preserved_env=env)
            scope_errors = public_browser_scope_errors(base_render, smoke)
            if scope_errors:
                return scope_errors
            if preserved_source is not None and original.get("resolved_compose_sha256", {}).get(
                "smoke"
            ) != _digest(base_render):
                return ["preserved_public_baseline_render"]
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
    if preserved_source is not None and service_images != original.get("service_images"):
        return ["preserved_public_baseline_images"]
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
    if preserved_source is not None and expected_ids != original.get("service_image_ids"):
        return ["preserved_public_baseline_image_ids"]
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
    if binding is not None:
        lines.extend(["", "[public_browser]"])
        lines.extend(f"{key} = {_quote(value)}" for key, value in binding.items())
    if preserved_source is not None:
        try:
            _publish_preserved_admission(output, ("\n".join(lines) + "\n").encode())
        except (OSError, ValueError):
            return ["runtime_admission_output"]
        return []
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
    parser.add_argument("--public-browser-overlay", type=Path)
    parser.add_argument("--preserved-source", type=Path)
    args = parser.parse_args()
    errors = generate(
        args.compose,
        args.pilot_overlay,
        args.image_manifest,
        args.output,
        public_overlay=args.public_browser_overlay,
        preserved_source=args.preserved_source,
    )
    if errors:
        print("NAS runtime admission refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print(f"NAS runtime admission written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
