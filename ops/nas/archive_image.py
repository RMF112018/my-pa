#!/usr/bin/env python3
"""Read the config identity and platform from a Docker image archive."""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import NamedTuple

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_MANIFEST_BYTES = 1_048_576
MAX_CONFIG_BYTES = 16_777_216


class ArchiveImage(NamedTuple):
    config_digest: str
    os: str
    architecture: str


def _regular_member(archive: tarfile.TarFile, name: str, maximum: int) -> bytes:
    try:
        member = archive.getmember(name)
    except KeyError as error:
        raise ValueError(f"archive member is missing: {name}") from error
    if not member.isfile() or member.size <= 0 or member.size > maximum:
        raise ValueError(f"archive member is not a bounded regular file: {name}")
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError(f"archive member is unreadable: {name}")
    value = stream.read(maximum + 1)
    if len(value) != member.size:
        raise ValueError(f"archive member size changed while reading: {name}")
    return value


def inspect_archive(path: Path) -> ArchiveImage:
    """Return the content-derived config digest and declared platform."""
    with tarfile.open(path, mode="r:*") as archive:
        manifest_raw = _regular_member(archive, "manifest.json", MAX_MANIFEST_BYTES)
        try:
            manifest = json.loads(manifest_raw)
        except json.JSONDecodeError as error:
            raise ValueError("archive manifest is invalid JSON") from error
        if (
            not isinstance(manifest, list)
            or len(manifest) != 1
            or not isinstance(manifest[0], dict)
        ):
            raise ValueError("archive must contain exactly one image manifest")
        config_name = manifest[0].get("Config")
        if not isinstance(config_name, str):
            raise ValueError("archive manifest has no config member")
        config_path = PurePosixPath(config_name)
        if config_path.is_absolute() or ".." in config_path.parts:
            raise ValueError("archive config member escapes the archive root")
        config_raw = _regular_member(archive, config_name, MAX_CONFIG_BYTES)

    config_hex = hashlib.sha256(config_raw).hexdigest()
    filename_hex = config_path.name.removesuffix(".json")
    if SHA256.fullmatch(filename_hex) and filename_hex != config_hex:
        raise ValueError("archive config filename does not match its content digest")
    try:
        config = json.loads(config_raw)
    except json.JSONDecodeError as error:
        raise ValueError("archive config is invalid JSON") from error
    if not isinstance(config, dict):
        raise ValueError("archive config is not an object")
    os_name = str(config.get("os", ""))
    architecture = str(config.get("architecture", ""))
    if os_name != "linux" or architecture != "amd64":
        raise ValueError("archive image platform is not linux/amd64")
    return ArchiveImage(
        config_digest=f"sha256:{config_hex}",
        os=os_name,
        architecture=architecture,
    )
