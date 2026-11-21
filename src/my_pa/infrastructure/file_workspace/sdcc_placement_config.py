"""Load an operator-controlled SDCR placement policy, never from a writable workspace.

This optional configuration is **not deployed by repository code changes**. A
missing/invalid configured file refuses startup; an unset setting leaves the
historical Files plane unchanged until an explicitly approved cutover.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from my_pa.domain.files.sdcc_placement import SDCRPlacementGate

MAX_CONFIG_BYTES = 128 * 1024


class SDCRConfigurationError(ValueError):
    """Non-sensitive startup error; does not include host paths or bytes."""


def load_sdcr_gate(
    config_file: str,
    workspace_root: str,
    *,
    forbidden_roots: Iterable[str | Path] = (),
) -> SDCRPlacementGate:
    """Read one bounded, owner-managed config outside all workspace paths.

    Reject symlinks and writable immediate parent/config file to prevent a
    Files-authoring client from replacing active policy after startup. The file
    is snapshotted, not watched, for deterministic per-process admission.
    """
    source = Path(config_file)
    root = Path(workspace_root)
    if not source.is_absolute() or not root.is_absolute():
        raise SDCRConfigurationError("sdcr_config_absolute_path_required")
    try:
        actual_root = root.resolve(strict=True)
        parent = source.parent.resolve(strict=True)
        if source.is_symlink():
            raise SDCRConfigurationError("sdcr_config_must_be_outside_workspace")
        roots = (actual_root, *(Path(raw).resolve(strict=True) for raw in forbidden_roots))
        if any(candidate == parent or candidate in parent.parents for candidate in roots):
            raise SDCRConfigurationError("sdcr_config_must_be_outside_workspace")
        status = source.stat(follow_symlinks=False)
        parent_status = parent.stat(follow_symlinks=False)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1:
            raise SDCRConfigurationError("sdcr_config_must_be_regular")
        if status.st_mode & 0o022 or parent_status.st_mode & 0o022:
            raise SDCRConfigurationError("sdcr_config_permissions_unsafe")
        if not 1 <= status.st_size <= MAX_CONFIG_BYTES:
            raise SDCRConfigurationError("sdcr_config_size_invalid")
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            held = os.fstat(fd)
            if (held.st_dev, held.st_ino) != (status.st_dev, status.st_ino):
                raise SDCRConfigurationError("sdcr_config_identity_changed")
            raw = bytearray()
            while len(raw) <= MAX_CONFIG_BYTES:
                part = os.read(fd, min(16_384, MAX_CONFIG_BYTES + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            if len(raw) > MAX_CONFIG_BYTES or os.fstat(fd).st_size != len(raw):
                raise SDCRConfigurationError("sdcr_config_changed_or_too_large")
        finally:
            os.close(fd)
        parsed: Any = json.loads(raw)
    except SDCRConfigurationError:
        raise
    except (OSError, ValueError, UnicodeDecodeError, TypeError):
        raise SDCRConfigurationError("sdcr_config_unavailable_or_invalid") from None
    if not isinstance(parsed, dict):
        raise SDCRConfigurationError("sdcr_config_object_required")
    policy = parsed.get("policy")
    owners = parsed.get("registrations")
    if not isinstance(policy, dict) or not isinstance(owners, dict):
        raise SDCRConfigurationError("sdcr_policy_or_registrations_missing")
    try:
        return SDCRPlacementGate(policy, owners)
    except (ValueError, KeyError, TypeError):
        raise SDCRConfigurationError("sdcr_policy_validation_failed") from None
