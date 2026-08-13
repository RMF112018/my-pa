"""Shared fail-closed host-tool resolution for NAS operator scripts."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def executable(environment_name: str, default: str) -> str:
    """Resolve an explicitly configured executable without shell expansion."""
    configured = os.environ.get(environment_name, default)
    candidate = Path(configured)
    if candidate.is_absolute():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise RuntimeError(f"configured executable is unavailable: {environment_name}")
    resolved = shutil.which(configured)
    if resolved is None:
        raise RuntimeError(f"configured executable is unavailable: {environment_name}")
    return configured


def docker() -> str:
    """Return the exact Docker CLI selected for the NAS host."""
    return executable("MY_PA_NAS_DOCKER", "docker")
