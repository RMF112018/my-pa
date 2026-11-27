"""Verify a locally emitted Docker archive and write its bounded public receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tarfile
from pathlib import Path, PurePosixPath

COMMIT = "64f53d4ac0f819f93aab05a2bae653647320ffd3"
TREE = "c503df2b844e8d87e053d98ea6060117eee4371d"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEX = re.compile(r"[0-9a-f]{64}\Z")
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
TAG = f"my-pa-app:{COMMIT}"


def require(condition: object) -> None:
    if not condition:
        raise ValueError("archive_identity_mismatch")


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for name, value in pairs:
        require(name not in result)
        result[name] = value
    return result


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size > 0)
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def regular_member(archive: tarfile.TarFile, name: str) -> tarfile.TarInfo:
    members = [item for item in archive.getmembers() if item.name == name]
    require(len(members) == 1)
    member = members[0]
    require(member.isfile() and member.size > 0)
    return member


def archive_member(archive: tarfile.TarFile, name: str, limit: int) -> bytes:
    member = regular_member(archive, name)
    require(member.size <= limit)
    stream = archive.extractfile(member)
    if stream is None:
        raise ValueError("unreadable_archive_member")
    with stream:
        payload = stream.read(limit + 1)
    require(len(payload) == member.size)
    return payload


def member_name(name: object) -> str:
    if not isinstance(name, str):
        raise ValueError("archive_member_path_invalid")
    path = PurePosixPath(name)
    require(
        path.parts and not path.is_absolute() and ".." not in path.parts and path.as_posix() == name
    )
    return name


def read_config(path: Path) -> tuple[bytes, str]:
    with tarfile.open(path, mode="r:") as archive:
        manifest = json.loads(
            archive_member(archive, "manifest.json", 1_048_576), object_pairs_hook=unique_object
        )
        require(isinstance(manifest, list) and len(manifest) == 1 and isinstance(manifest[0], dict))
        row = manifest[0]
        require(row.get("RepoTags") in ([TAG], [f"docker.io/library/{TAG}"]))
        name = member_name(row.get("Config"))
        layers = row.get("Layers")
        require(isinstance(layers, list) and layers)
        for layer in layers:
            reference = member_name(layer)
            require(reference not in {"manifest.json", name})
            regular_member(archive, reference)
        config_raw = archive_member(archive, name, 16_777_216)
        config = json.loads(config_raw, object_pairs_hook=unique_object)
        diff_ids = config["rootfs"]["diff_ids"]
        require(isinstance(diff_ids, list) and len(diff_ids) == len(layers))
        require(all(isinstance(value, str) and DIGEST.fullmatch(value) for value in diff_ids))
        return config_raw, PurePosixPath(name).name


def write_json(path: Path, value: dict[str, object]) -> dict[str, object]:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(data)
    return {"sha256": digest(data), "bytes": len(data)}


def verify(output: Path, raw_metadata: Path, built_at: str, lock_sha: str) -> str:
    require(HEX.fullmatch(lock_sha) and STAMP.fullmatch(built_at))
    archive = output / "app.tar"
    before = file_identity(archive)
    meta_before = file_identity(raw_metadata)
    require(meta_before[2] <= 1_048_576)
    raw_metadata_bytes = raw_metadata.read_bytes()
    require(
        len(raw_metadata_bytes) == meta_before[2] and file_identity(raw_metadata) == meta_before
    )
    metadata = json.loads(raw_metadata_bytes, object_pairs_hook=unique_object)
    config_raw, config_leaf = read_config(archive)
    config_hex = digest(config_raw)
    config_digest = f"sha256:{config_hex}"
    filename_hex = config_leaf.removesuffix(".json")
    if HEX.fullmatch(filename_hex):
        require(filename_hex == config_hex)
    manifest_digest = metadata["containerimage.digest"]
    require(isinstance(manifest_digest, str) and DIGEST.fullmatch(manifest_digest))
    require(metadata["containerimage.config.digest"] == config_digest)
    config = json.loads(config_raw, object_pairs_hook=unique_object)
    require(config["os"] == "linux" and config["architecture"] == "amd64")
    expected_labels = {
        "org.opencontainers.image.revision": COMMIT,
        "io.my-pa.repository-tree": TREE,
        "org.opencontainers.image.created": built_at,
        "io.my-pa.target-platform": "linux/amd64",
        "io.my-pa.python-runtime-lock-sha256": lock_sha,
    }
    labels = config["config"]["Labels"]
    require(all(labels.get(label) == value for label, value in expected_labels.items()))
    with archive.open("rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    require(file_identity(archive) == before)
    require({path.name for path in output.iterdir()} == {"app.tar"})
    safe_metadata = write_json(
        output / "app.metadata.json",
        {"containerimage.config.digest": config_digest, "containerimage.digest": manifest_digest},
    )
    write_json(
        output / "app-build-receipt.json",
        {
            "schema": "my-pa.app-build-receipt.v1",
            "status": "verified_app_archive_only",
            "commit": COMMIT,
            "tree": TREE,
            "platform": "linux/amd64",
            "built_at": built_at,
            "python_runtime_lock_sha256": lock_sha,
            "image_config_digest": config_digest,
            "buildkit_manifest_digest": manifest_digest,
            "raw_buildkit_metadata_sha256": digest(raw_metadata_bytes),
            "members": {
                "app.tar": {"sha256": archive_sha, "bytes": before[2]},
                "app.metadata.json": safe_metadata,
            },
        },
    )
    return archive_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--raw-metadata", required=True, type=Path)
    parser.add_argument("--built-at", required=True)
    parser.add_argument("--lock-sha", required=True)
    options = parser.parse_args()
    try:
        archive_sha = verify(
            options.output, options.raw_metadata, options.built_at, options.lock_sha
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tarfile.TarError):
        print("::error title=Combined release app build::Archive verification refused")
        return 1
    print(f"::notice title=Combined release app build::Verified archive sha256:{archive_sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
