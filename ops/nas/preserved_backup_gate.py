#!/usr/bin/env python3
"""Bind a pre-migration backup to distinct current-gate and preserved runtimes."""

from __future__ import annotations

import argparse
import subprocess
import tomllib
from collections.abc import Callable
from pathlib import Path

from image_gate import shape_errors

Runner = Callable[[list[str]], str]


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - fixed Git command assembled below
        command, check=True, capture_output=True, text=True
    ).stdout.strip()


def _source_errors(
    label: str,
    source: Path,
    manifest_path: Path,
    *,
    runner: Runner,
) -> list[str]:
    errors: list[str] = []
    try:
        if source.resolve(strict=True) != source or not source.is_dir():
            errors.append(f"{label}_source_path")
    except OSError:
        return [f"{label}_source_path"]
    try:
        if manifest_path.resolve(strict=True) != manifest_path or not manifest_path.is_file():
            return [*errors, f"{label}_manifest_path"]
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return [*errors, f"{label}_manifest_unreadable"]
    commit = str(manifest.get("repository_commit", ""))
    tree = str(manifest.get("repository_tree", ""))
    if shape_errors(manifest):
        errors.append(f"{label}_manifest_shape")
    try:
        head = runner(["git", "-C", str(source), "rev-parse", "HEAD"])
        actual_tree = runner(["git", "-C", str(source), "rev-parse", "HEAD^{tree}"])
        dirty = runner(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all"])
    except (OSError, subprocess.SubprocessError):
        return [*errors, f"{label}_source_identity"]
    if head != commit or actual_tree != tree:
        errors.append(f"{label}_source_drift")
    if dirty:
        errors.append(f"{label}_source_dirty")
    return errors


def verify(
    current_source: Path,
    current_manifest: Path,
    preserved_source: Path,
    preserved_manifest: Path,
    preserved_compose: Path,
    *,
    expected_current_source: Path | None = None,
    runner: Runner = _run,
) -> list[str]:
    """Return every source-binding refusal without invoking runtime or firewall gates."""
    expected = expected_current_source or Path(__file__).resolve().parents[2]
    errors: list[str] = []
    try:
        if current_source.resolve(strict=True) != expected.resolve(strict=True):
            errors.append("current_gate_source")
    except OSError:
        errors.append("current_gate_source")
    try:
        if preserved_source.resolve(strict=True) == current_source.resolve(strict=True):
            errors.append("source_roles_not_distinct")
    except OSError:
        pass
    try:
        if preserved_compose.resolve(strict=True) != (
            preserved_source / "ops/nas/compose.example.yml"
        ).resolve(strict=True):
            errors.append("preserved_compose_path")
    except OSError:
        errors.append("preserved_compose_path")
    errors.extend(_source_errors("current_gate", current_source, current_manifest, runner=runner))
    errors.extend(_source_errors("preserved", preserved_source, preserved_manifest, runner=runner))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("current_source", type=Path)
    parser.add_argument("current_manifest", type=Path)
    parser.add_argument("preserved_source", type=Path)
    parser.add_argument("preserved_manifest", type=Path)
    parser.add_argument("preserved_compose", type=Path)
    args = parser.parse_args()
    errors = verify(
        args.current_source,
        args.current_manifest,
        args.preserved_source,
        args.preserved_manifest,
        args.preserved_compose,
    )
    if errors:
        print("Preserved backup gate refused: " + ", ".join(dict.fromkeys(errors)))
        return 1
    print("Preserved backup source identities passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
