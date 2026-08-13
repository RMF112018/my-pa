#!/usr/bin/env python3
"""Issue a non-admitted candidate for the short-lived NAS operator runtime."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from archive_image import inspect_archive


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if len(sys.argv) != 5:
        print("usage: write-operator-candidate.py DIRECTORY COMMIT TREE BUILT_AT", file=sys.stderr)
        return 64
    directory = Path(sys.argv[1])
    commit, tree, built_at = sys.argv[2:]
    archive = directory / "operator.tar"
    metadata_path = directory / "operator.metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    image = inspect_archive(archive)
    image_id = str(metadata.get("containerimage.config.digest", ""))
    if image.config_digest != image_id:
        raise ValueError("operator metadata config identity does not match its archive")
    manifest_digest = str(metadata.get("containerimage.digest", ""))
    candidate = f'''schema = "my-pa.nas-operator-runtime-candidate.v1"
status = "candidate_not_admitted"
repository_commit = {json.dumps(commit)}
repository_tree = {json.dumps(tree)}
built_at = {json.dumps(built_at)}
target_os = "linux"
target_architecture = "amd64"
oci_manifest_digest = {json.dumps(manifest_digest)}
docker_image_id = {json.dumps(image_id)}
archive_sha256 = "{_sha256(archive)}"
build_metadata_sha256 = "{_sha256(metadata_path)}"
'''
    (directory / "operator-runtime.candidate.toml").write_text(candidate, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
