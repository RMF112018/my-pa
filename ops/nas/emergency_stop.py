#!/usr/bin/env python3
"""Stop only the root-published my-pa Compose target, independent of control evidence."""

from __future__ import annotations

import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from lifecycle_gate import _yaml
from nas_tools import docker

CANONICAL_COMPOSE = Path("/etc/my-pa/compose.yml")
PROJECT = "my-pa-nas-contract"
SERVICES = {
    "postgres",
    "gateway",
    "worker-enrollment",
    "worker-capture",
    "web",
    "proxy",
}


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - bounded Docker Compose command
        command, check=True, capture_output=True, text=True
    ).stdout


def stop(
    compose_path: Path = CANONICAL_COMPOSE,
    *,
    owner_uid: int = 0,
    runner: Callable[[list[str]], str] = _run,
) -> list[str]:
    errors: list[str] = []
    try:
        metadata = compose_path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != owner_uid
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or metadata.st_nlink != 1
            or compose_path.resolve(strict=True) != compose_path
        ):
            return ["canonical_compose_metadata"]
        compose = _yaml(compose_path)
        compose_name = next(
            (
                line.partition(":")[2].strip()
                for line in compose_path.read_text(encoding="utf-8").splitlines()
                if line.startswith("name:")
            ),
            None,
        )
    except (OSError, ValueError):
        return ["canonical_compose_unreadable"]
    services = None if compose is None else compose.get("services")
    if (
        compose is None
        or compose_name != PROJECT
        or not isinstance(services, dict)
        or set(services) != SERVICES
    ):
        return ["canonical_compose_identity"]
    command = [
        docker(),
        "compose",
        "--project-name",
        PROJECT,
        "--file",
        str(compose_path),
        "--profile",
        "nas-01-contract-only",
    ]
    try:
        runner([*command, "stop", "--timeout", "10"])
        running = runner([*command, "ps", "--status", "running", "-q"])
    except (OSError, subprocess.SubprocessError):
        return ["emergency_stop_command"]
    if running.strip():
        errors.append("emergency_stop_incomplete")
    return errors


def main() -> int:
    errors = stop()
    if errors:
        print("NAS emergency stop refused: " + ", ".join(errors))
        return 1
    print("NAS runtime stopped; no container, bind mount, volume, or data was removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
