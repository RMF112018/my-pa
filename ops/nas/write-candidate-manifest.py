#!/usr/bin/env python3
"""Issue a non-deployable manifest from exact candidate archives and metadata."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

POSTGRES_REFERENCE = (
    "postgres@sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b"
)


def _sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    if len(sys.argv) != 6:
        print(
            "usage: write-candidate-manifest.py DIRECTORY COMMIT TREE BUILT_AT LOCK_SHA",
            file=sys.stderr,
        )
        return 64
    directory = Path(sys.argv[1])
    commit, tree, built_at, lock_sha = sys.argv[2:]
    sections: list[str] = []
    for name in ("app", "web", "postgres"):
        metadata_path = directory / f"{name}.metadata.json"
        archive_path = directory / f"{name}.tar"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        digest = metadata["containerimage.digest"]
        image_id = metadata["containerimage.config.digest"]
        load_reference = image_id
        reference = POSTGRES_REFERENCE if name == "postgres" else f"my-pa-{name}@{digest}"
        sections.append(
            f"""
[images.{name}]
reference = "{reference}"
load_reference = "{load_reference}"
oci_manifest_digest = "{digest}"
docker_image_id = "{image_id}"
archive_sha256 = "{_sha256(archive_path)}"
build_metadata_sha256 = "{_sha256(metadata_path)}"
"""
        )
    manifest = f"""schema = "my-pa.nas-image-manifest.v1"
status = "candidate_not_deployable"
repository_commit = "{commit}"
repository_tree = "{tree}"
source_clean = true
built_at = "{built_at}"
target_os = "linux"
target_architecture = "amd64"
docker_engine_id = "REQUIRED_LIVE_NAS_DOCKER_ENGINE_ID"
docker_engine_name = "REQUIRED_LIVE_NAS_DOCKER_ENGINE_NAME"
python_runtime_lock_sha256 = "{lock_sha}"
postgres_source_tag = "postgres:17.10"
postgres_index_digest = "sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"
{"".join(sections)}"""
    (directory / "image-manifest.candidate.toml").write_text(manifest, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
