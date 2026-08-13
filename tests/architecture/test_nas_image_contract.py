"""NAS-02 image and start controls remain reproducible and fail closed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _gate_module() -> ModuleType:
    path = ROOT / "ops/nas/image_gate.py"
    spec = importlib.util.spec_from_file_location("nas_image_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dockerfiles_are_platform_inputs_without_implicit_start_builds() -> None:
    app = (ROOT / "ops/docker/app.Dockerfile").read_text()
    web = (ROOT / "ops/docker/web.Dockerfile").read_text()
    start = (ROOT / "ops/nas/start.sh").read_text()
    assert "ARG PYTHON_IMAGE=python@sha256:" in app
    assert "ARG NODE_IMAGE=node@sha256:" in web
    assert 'test "${TARGETPLATFORM}" = "linux/amd64"' in app
    assert 'test "${TARGETPLATFORM}" = "linux/amd64"' in web
    assert "org.opencontainers.image.revision" in app
    assert "org.opencontainers.image.revision" in web
    assert "sha256sum --check --strict" in app
    assert "USER 10001:10001" in app
    assert "USER 10001:10001" in web
    assert "--no-build --pull never" in start
    assert '"$NAS_PYTHON_BIN" "$script_dir/image_gate.py"' in start
    assert '. "$script_dir/lifecycle-common.sh"' in start
    assert "docker build" not in start and "buildx" not in start


def test_candidate_build_and_load_are_exact_platform_and_admitted() -> None:
    build = (ROOT / "ops/nas/build-candidates.sh").read_text()
    load = (ROOT / "ops/nas/load-candidates.sh").read_text()
    assert "status --porcelain --untracked-files=all" in build
    assert 'git -C "$repo_root" archive "$commit"' in build
    assert "--platform linux/amd64" in build
    assert "--metadata-file" in build
    assert "type=docker,dest=$archive" in build
    assert 'nas_docker load --input "$archive_dir/$name.tar"' in load
    assert "admit-image-manifest.py" in load
    assert "image_gate.py" in load


def test_candidate_manifest_is_not_deployable() -> None:
    gate = _gate_module()
    errors = gate.verify(ROOT / "ops/nas/image-manifest.example.toml")
    assert "status_not_deployable" in errors
    assert "live_verification_required" in errors


def test_synthetic_manifest_can_never_pass_without_live_evidence(tmp_path: Path) -> None:
    gate = _gate_module()
    digest = "sha256:" + "1" * 64
    image_id = "sha256:" + "2" * 64
    archive_sha = "3" * 64
    image = (
        'reference = "example.invalid/my-pa@' + digest + '"\n'
        f'load_reference = "{image_id}"\n'
        f'oci_manifest_digest = "{digest}"\n'
        f'docker_image_id = "{image_id}"\n'
        f'archive_sha256 = "{archive_sha}"\n'
        f'build_metadata_sha256 = "{archive_sha}"\n'
    )
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\n'
        'status = "deployable"\n'
        f'repository_commit = "{"a" * 40}"\n'
        f'repository_tree = "{"b" * 40}"\n'
        'source_clean = true\nbuilt_at = "2026-08-12T12:00:00Z"\n'
        'target_os = "linux"\ntarget_architecture = "amd64"\n'
        'docker_engine_id = "nas-engine"\ndocker_engine_name = "nas"\n'
        f'python_runtime_lock_sha256 = "{"c" * 64}"\n'
        'postgres_source_tag = "postgres:17.10"\n'
        f'postgres_index_digest = "{gate.POSTGRES_INDEX_DIGEST}"\n'
        + "".join(f"\n[images.{name}]\n{image}" for name in ("app", "web", "postgres", "proxy"))
    )
    assert "live_verification_required" in gate.verify(manifest)


def test_digest_identity_conflation_is_rejected(tmp_path: Path) -> None:
    gate = _gate_module()
    digest = "sha256:" + "1" * 64
    manifest = tmp_path / "manifest.toml"
    image = (
        f'reference = "example.invalid/x@{digest}"\n'
        f'load_reference = "{digest}"\n'
        f'oci_manifest_digest = "{digest}"\n'
        f'docker_image_id = "{digest}"\n'
        f'archive_sha256 = "{"3" * 64}"\n'
        f'build_metadata_sha256 = "{"4" * 64}"\n'
    )
    manifest.write_text(
        'schema = "my-pa.nas-image-manifest.v1"\nstatus = "deployable"\n'
        f'repository_commit = "{"a" * 40}"\nrepository_tree = "{"b" * 40}"\n'
        'source_clean = true\nbuilt_at = "2026-08-12T12:00:00Z"\n'
        'target_os = "linux"\ntarget_architecture = "amd64"\n'
        'docker_engine_id = "nas-engine"\ndocker_engine_name = "nas"\n'
        f'python_runtime_lock_sha256 = "{"c" * 64}"\n'
        'postgres_source_tag = "postgres:17.10"\n'
        f'postgres_index_digest = "{gate.POSTGRES_INDEX_DIGEST}"\n'
        + "".join(f"\n[images.{name}]\n{image}" for name in ("app", "web", "postgres", "proxy"))
    )
    assert {f"{name}_identity_conflation" for name in ("app", "web", "postgres", "proxy")} <= set(
        gate.verify(manifest)
    )


def test_live_gate_checks_engine_archives_metadata_and_loaded_images(
    tmp_path: Path, monkeypatch: object
) -> None:
    gate = _gate_module()
    commit, tree = "a" * 40, "b" * 40
    lock_sha = "c" * 64
    labels = {
        "org.opencontainers.image.revision": commit,
        "io.my-pa.repository-tree": tree,
        "org.opencontainers.image.created": "2026-08-12T12:00:00Z",
        "io.my-pa.target-platform": "linux/amd64",
        "io.my-pa.python-runtime-lock-sha256": lock_sha,
    }
    sections: list[str] = []
    inspected: dict[str, dict[str, object]] = {}
    for index, name in enumerate(("app", "web", "postgres", "proxy"), start=1):
        digest = (
            gate.POSTGRES_REFERENCE.rpartition("@")[2]
            if name == "postgres"
            else "sha256:" + str(index) * 64
        )
        image_id = "sha256:" + str(index + 3) * 64
        reference = gate.POSTGRES_REFERENCE if name == "postgres" else f"my-pa-{name}@{digest}"
        load_reference = image_id
        archive = tmp_path / f"{name}.tar"
        archive.write_bytes(f"{name}-archive".encode())
        metadata = tmp_path / f"{name}.metadata.json"
        metadata.write_text(
            json.dumps(
                {
                    "containerimage.digest": digest,
                    "containerimage.config.digest": image_id,
                }
            ),
            encoding="utf-8",
        )
        sections.append(
            f"""
[images.{name}]
reference = "{reference}"
load_reference = "{load_reference}"
oci_manifest_digest = "{digest}"
docker_image_id = "{image_id}"
archive_sha256 = "{hashlib.sha256(archive.read_bytes()).hexdigest()}"
build_metadata_sha256 = "{hashlib.sha256(metadata.read_bytes()).hexdigest()}"
"""
        )
        inspected[load_reference] = {
            "Os": "linux",
            "Architecture": "amd64",
            "Id": image_id,
            "RepoDigests": [reference],
            "Config": {"Labels": labels},
        }
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        f"""schema = "my-pa.nas-image-manifest.v1"
status = "deployable"
repository_commit = "{commit}"
repository_tree = "{tree}"
source_clean = true
built_at = "2026-08-12T12:00:00Z"
target_os = "linux"
target_architecture = "amd64"
docker_engine_id = "nas-engine"
docker_engine_name = "nas"
python_runtime_lock_sha256 = "{lock_sha}"
postgres_source_tag = "postgres:17.10"
postgres_index_digest = "{gate.POSTGRES_INDEX_DIGEST}"
{"".join(sections)}""",
        encoding="utf-8",
    )

    def fake_run(command: list[str]) -> object:
        if command[1] == "info":
            return {"OSType": "linux", "Architecture": "x86_64", "ID": "nas-engine", "Name": "nas"}
        return [inspected[command[-1]]]

    monkeypatch.setattr(gate, "_run_json", fake_run)  # type: ignore[attr-defined]
    assert gate.verify(manifest, tmp_path, live=True) == []

    inspected["sha256:" + "5" * 64]["Architecture"] = "arm64"
    assert "web_loaded_platform" in gate.verify(manifest, tmp_path, live=True)
