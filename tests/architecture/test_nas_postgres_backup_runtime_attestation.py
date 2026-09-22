"""Synthetic contract tests for immutable PostgreSQL backup/runtime evidence."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
COMMIT = "a" * 40
TREE = "b" * 40
ENGINE_ID = "engine-synthetic"
ENGINE_NAME = "nas-synthetic"
PROJECT = "my-pa-nas-contract"
NETWORK = "my-pa-nas-contract_data-plane"
SERVICES = (
    "postgres",
    "gateway",
    "worker-enrollment",
    "worker-capture",
    "web",
    "proxy",
)


def _module() -> ModuleType:
    path = ROOT / "ops/nas/write-postgres-backup-runtime-attestation.py"
    spec = importlib.util.spec_from_file_location("nas_postgres_backup_attestation", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        importlib.import_module("nas_tools")
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _rewrite(path: Path, value: str, mode: int = 0o400) -> None:
    if path.exists():
        path.chmod(0o600)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)


def _image_manifest() -> str:
    images: list[str] = []
    ids = {
        "app": "sha256:" + "1" * 64,
        "web": "sha256:" + "2" * 64,
        "postgres": "sha256:" + "3" * 64,
        "proxy": "sha256:" + "4" * 64,
    }
    digests = {
        "app": "sha256:" + "5" * 64,
        "web": "sha256:" + "6" * 64,
        "postgres": "sha256:dbbeb22a65db2503050cdbbe5e78f017478f10a1002a226463f049dbb017e99b",
        "proxy": "sha256:" + "7" * 64,
    }
    for name in ("app", "web", "postgres", "proxy"):
        reference = (
            "postgres@" + digests[name]
            if name == "postgres"
            else ("caddy@" if name == "proxy" else f"my-pa-{name}@") + digests[name]
        )
        images.append(
            f'''[images.{name}]
reference = "{reference}"
load_reference = "{ids[name]}"
oci_manifest_digest = "{digests[name]}"
docker_image_id = "{ids[name]}"
archive_sha256 = "{"8" * 64}"
build_metadata_sha256 = "{"9" * 64}"
'''
        )
    return (
        'schema = "my-pa.nas-image-manifest.v1"\nstatus = "deployable"\n'
        f'repository_commit = "{COMMIT}"\nrepository_tree = "{TREE}"\n'
        'source_clean = true\nbuilt_at = "2026-09-21T00:00:00Z"\n'
        'target_os = "linux"\ntarget_architecture = "amd64"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n'
        f'python_runtime_lock_sha256 = "{"0" * 64}"\n'
        'postgres_source_tag = "postgres:17.10"\n'
        "postgres_index_digest = "
        '"sha256:7958605b474b3d264a969cb3a123d6aa00ad1e1fe9da8a69984dabb704d93317"\n\n'
        + "\n".join(images)
    )


@pytest.fixture
def attestation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ModuleType, dict[str, Path], list[list[str]]]:
    """Install only synthetic, non-secret identity evidence and Docker replies."""
    module = _module()
    etc = tmp_path / "etc"
    deployment_root = tmp_path / "deployment"
    backups = tmp_path / "backups"
    evidence = tmp_path / "attestations"
    for directory in (etc, deployment_root, backups, evidence):
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
    synthetic_docker = tmp_path / "trusted-tools/docker"
    synthetic_docker.parent.mkdir(mode=0o700)
    synthetic_docker.write_text("#!/bin/sh\nexit 99\n", encoding="ascii")
    synthetic_docker.chmod(0o500)
    monkeypatch.setattr(module, "CANONICAL_DOCKER", synthetic_docker)
    (tmp_path / "postgres/data").mkdir(parents=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump_name = f"my-pa-{timestamp}.dump"
    dump = backups / dump_name
    dump.write_bytes(b"PGDMP synthetic custom-format dump")
    dump.chmod(0o600)
    receipt = backups / f"{dump_name}.sha256"
    receipt.write_text(f"{_sha(dump.read_bytes())}  {dump_name}\n", encoding="ascii")
    receipt.chmod(0o600)
    image = etc / "image-manifest.toml"
    _rewrite(image, _image_manifest())
    image_digest = _sha(image.read_bytes())
    image_ids = {
        "postgres": "sha256:" + "3" * 64,
        "gateway": "sha256:" + "1" * 64,
        "worker-enrollment": "sha256:" + "1" * 64,
        "worker-capture": "sha256:" + "1" * 64,
        "web": "sha256:" + "2" * 64,
        "proxy": "sha256:" + "4" * 64,
    }
    containers = {name: f"{index:x}" * 64 for index, name in enumerate(SERVICES, start=1)}
    service_images = {
        **{name: image_ids[name] for name in SERVICES if name != "proxy"},
        "proxy": "caddy@sha256:" + "7" * 64,
    }
    config_hashes = {name: f"{index:x}" * 64 for index, name in enumerate(SERVICES, start=7)}
    smoke_render = {"name": PROJECT, "services": {}}
    pilot_render = {"name": PROJECT, "services": {}}
    for name in SERVICES:
        smoke_render["services"][name] = {"image": service_images[name], "restart": "no"}
        pilot_render["services"][name] = {
            "image": service_images[name],
            "restart": "unless-stopped",
        }
    smoke_digest = _sha(json.dumps(smoke_render, sort_keys=True, separators=(",", ":")).encode())
    pilot_digest = _sha(json.dumps(pilot_render, sort_keys=True, separators=(",", ":")).encode())
    compose_source_digest = _sha((ROOT / "ops/nas/compose.example.yml").read_bytes())
    proxy_digest = "sha256:" + "7" * 64
    synthetic_password = "synthetic-password-marker-not-a-real-secret"  # noqa: S105 - inert fixture
    postgres_render = {
        "name": PROJECT,
        "services": {
            "postgres": {
                "image": image_ids["postgres"],
                "platform": "linux/amd64",
                "restart": "no",
                "environment": {
                    "POSTGRES_DB": "my_pa",
                    "POSTGRES_USER": "my_pa",
                    "POSTGRES_PASSWORD": synthetic_password,
                    "POSTGRES_INITDB_ARGS": "--data-checksums --locale=C.UTF-8 --encoding=UTF8",
                },
                "networks": {"data-plane": {}},
                "volumes": [
                    {
                        "type": "bind",
                        "source": f"{tmp_path}/postgres/data",
                        "target": "/var/lib/postgresql/data",
                    }
                ],
            }
        },
        "networks": {"data-plane": {"name": NETWORK, "internal": True, "external": False}},
    }
    redacted_postgres = json.loads(json.dumps(postgres_render))
    redacted_marker = "<redacted-runtime-secret>"
    redacted_postgres["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"] = redacted_marker
    postgres_render_digest = _sha(
        json.dumps(redacted_postgres, sort_keys=True, separators=(",", ":")).encode()
    )
    monkeypatch.setenv("MY_PA_DB_PASSWORD", synthetic_password)
    monkeypatch.setenv("MY_PA_NAS_ROOT", str(tmp_path))
    monkeypatch.setenv("MY_PA_POSTGRES_IMAGE_ID", image_ids["postgres"])
    deployment = deployment_root / "manifest.toml"
    _rewrite(
        deployment,
        'schema = "my-pa.nas-deployment-manifest.v1"\n'
        f'repository_commit = "{COMMIT}"\nrepository_tree = "{TREE}"\n'
        f'app_image_id = "{image_ids["gateway"]}"\n'
        f'web_image_id = "{image_ids["web"]}"\n'
        f'proxy_image_digest = "{proxy_digest}"\n'
        f'compose_hash = "{compose_source_digest}"\n'
        'deployed_at = "2026-09-21T00:00:00Z"\n'
        f'backup_receipt = "{receipt}"\n',
    )
    runtime = etc / "runtime-admission.toml"
    _rewrite(
        runtime,
        'schema = "my-pa.nas-runtime-admission.v1"\nstatus = "admitted"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n'
        f'image_manifest_sha256 = "{image_digest}"\n'
        f'[resolved_compose_sha256]\nsmoke = "{smoke_digest}"\npilot = "{pilot_digest}"\n'
        "[service_images]\n"
        + "".join(f'{name} = "{service_images[name]}"\n' for name in SERVICES)
        + "[service_image_ids]\n"
        + "".join(f'{name} = "{image_ids[name]}"\n' for name in SERVICES),
    )
    resources = etc / "postgres-resources.toml"
    _rewrite(
        resources,
        'schema = "my-pa.nas-postgres-resources.v1"\nstatus = "verified"\n'
        f'docker_engine_id = "{ENGINE_ID}"\npostgres_container_id = "{containers["postgres"]}"\n'
        f'postgres_image_id = "{image_ids["postgres"]}"\ndata_network = "{NETWORK}"\n'
        'measured_at = "2026-09-21T00:00:00Z"\nlogical_cpus = 4\nmemory_bytes = 4096\n'
        'minimum_available_storage_bytes = 1\nfilesystem_type = "btrfs"\n'
        f'postgres_data_path = "{tmp_path}/postgres/data"\n'
        '[tuning]\nstatus = "no_numeric_tuning"\n',
    )
    bootstrap = etc / "postgres-bootstrap-admission.toml"
    _rewrite(
        bootstrap,
        'schema = "my-pa.nas-postgres-bootstrap-admission.v1"\nstatus = "admitted"\n'
        f'repository_commit = "{COMMIT}"\nrepository_tree = "{TREE}"\n'
        f'docker_engine_id = "{ENGINE_ID}"\ndocker_engine_name = "{ENGINE_NAME}"\n'
        f'image_manifest_sha256 = "{image_digest}"\n'
        f'compose_sha256 = "{compose_source_digest}"\n'
        f'resolved_postgres_sha256 = "{postgres_render_digest}"\n'
        f'postgres_image_id = "{image_ids["postgres"]}"\n'
        f'database_operator_image_id = "{image_ids["gateway"]}"\nproject_name = "{PROJECT}"\n'
        f'service_name = "postgres"\ndata_network = "{NETWORK}"\n'
        f'postgres_data_path = "{tmp_path}/postgres/data"\ndata_network_internal = true\n',
    )
    monkeypatch.setattr(module, "DEPLOYMENT_MANIFEST", deployment)
    monkeypatch.setattr(module, "BACKUP_ROOT", backups)
    monkeypatch.setattr(module, "IMAGE_MANIFEST", image)
    monkeypatch.setattr(module, "RUNTIME_ADMISSION", runtime)
    monkeypatch.setattr(module, "POSTGRES_RESOURCES", resources)
    monkeypatch.setattr(module, "POSTGRES_BOOTSTRAP_ADMISSION", bootstrap)
    monkeypatch.setattr(module, "ATTESTATION_ROOT", evidence)
    monkeypatch.setenv("MY_PA_NAS_DOCKER", str(module.CANONICAL_DOCKER))
    original_fstat = os.fstat

    def root_fstat(descriptor: int) -> SimpleNamespace:
        source = original_fstat(descriptor)
        return SimpleNamespace(
            st_mode=source.st_mode,
            st_uid=0,
            st_nlink=source.st_nlink,
            st_size=source.st_size,
            st_dev=source.st_dev,
            st_ino=source.st_ino,
            st_mtime_ns=source.st_mtime_ns,
            st_ctime_ns=source.st_ctime_ns,
        )

    monkeypatch.setattr(module.os, "fstat", root_fstat)
    monkeypatch.setattr(
        module,
        "_trusted_directory_fd",
        lambda path, *, leaf_mode: os.open(path, os.O_RDONLY | os.O_DIRECTORY),
    )
    monkeypatch.setattr(module, "_require_root_and_tools", lambda: None)
    commands: list[list[str]] = []
    projections: dict[str, object] = {
        "git_head": COMMIT,
        "git_tree": TREE,
        "git_dirty": "",
        "engine": f"{ENGINE_ID}\t{ENGINE_NAME}\n",
        "ids": "".join(f"{container_id}\n" for container_id in containers.values()),
        "container": {
            container_id: "\t".join(
                (
                    container_id,
                    image_ids[name],
                    "true",
                    PROJECT,
                    name,
                    "False",
                    "1",
                    config_hashes[name],
                )
            )
            + "\n"
            for name, container_id in containers.items()
        },
        "storage": f"bind,{tmp_path}/postgres/data,/var/lib/postgresql/data,true;\t{NETWORK},\n",
        "network_internal": True,
        "host_ports": False,
        "pilot_hashes_match": False,
        "running_hashes": dict(config_hashes),
    }

    def runner(command: list[str]) -> str:
        commands.append(command)
        if command[:2] == [str(module.CANONICAL_DOCKER), "compose"]:
            pilot_mode = command.count("--file") == 2
            if command[-3:] == ["config", "--format", "json"]:
                return json.dumps(pilot_render if pilot_mode else smoke_render)
            if command[-2:] == ["config", "--images"]:
                return "\n".join(service_images.values())
            if command[-3:] == ["config", "--hash", "*"]:
                prefix = "pilot-" if pilot_mode and not projections["pilot_hashes_match"] else ""
                return "\n".join(f"{name} {prefix}{config_hashes[name]}" for name in SERVICES)
            if command[-2] == "-q" and command[-3] == "ps":
                return containers[command[-1]] + "\n"
        if command[:3] == [str(module.CANONICAL_GIT), "-C", str(ROOT)]:
            if command[-1] == "HEAD":
                return str(projections["git_head"]) + "\n"
            if command[-1] == "HEAD^{tree}":
                return str(projections["git_tree"]) + "\n"
            if command[-1] == "--porcelain":
                return str(projections["git_dirty"])
        if command == [str(module.CANONICAL_DOCKER), "info", "--format", "{{.ID}}\t{{.Name}}"]:
            return str(projections["engine"])
        if command == [str(module.CANONICAL_DOCKER), "info", "--format", "{{json .}}"]:
            return json.dumps({"ID": ENGINE_ID, "Name": ENGINE_NAME})
        if command[:2] == [str(module.CANONICAL_DOCKER), "ps"]:
            assert command[-2:] == ["--format", "{{.ID}}"]
            return str(projections["ids"])
        if command[:3] == [str(module.CANONICAL_DOCKER), "inspect", "--format"]:
            if command[3] == module.CONTAINER_FORMAT:
                return projections["container"][command[4]]  # type: ignore[index]
            assert command[3] == module.POSTGRES_STORAGE_FORMAT
            assert command[4] == containers["postgres"]
            return str(projections["storage"])
        if command[:2] == [str(module.CANONICAL_DOCKER), "inspect"]:
            name = next(
                name for name, container_id in containers.items() if container_id == command[2]
            )
            return json.dumps(
                [
                    {
                        "Image": image_ids[name],
                        "Config": {
                            "Labels": {
                                "com.docker.compose.project": PROJECT,
                                "com.docker.compose.service": name,
                                "com.docker.compose.config-hash": projections["running_hashes"][
                                    name
                                ],
                            }
                        },
                    }
                ]
            )
        raise AssertionError(command)

    monkeypatch.setattr(module, "_run", runner)

    def list_archive(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == [str(module.CANONICAL_DOCKER), "compose"]:
            assert kwargs["env"] != os.environ
            return subprocess.CompletedProcess(command, 0, stdout=json.dumps(postgres_render))
        if command == [str(module.CANONICAL_DOCKER), "info", "--format", "{{json .}}"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {"ID": ENGINE_ID, "Name": ENGINE_NAME, "NCPU": 4, "MemTotal": 4096}
                ),
            )
        if command[:3] == [str(module.CANONICAL_DOCKER), "image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {"Id": image_ids["postgres"], "Os": "linux", "Architecture": "amd64"},
                        {"Id": image_ids["gateway"], "Os": "linux", "Architecture": "amd64"},
                    ]
                ),
            )
        if command == [str(module.CANONICAL_DOCKER), "inspect", containers["postgres"]]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Image": image_ids["postgres"],
                            "State": {"Running": True},
                            "Config": {
                                "Env": [f"POSTGRES_PASSWORD={synthetic_password}"],
                                "Labels": {
                                    "com.docker.compose.project": PROJECT,
                                    "com.docker.compose.service": "postgres",
                                },
                            },
                            "HostConfig": {
                                "PortBindings": {"5432/tcp": [{}]}
                                if projections["host_ports"]
                                else {}
                            },
                            "NetworkSettings": {"Networks": {NETWORK: {}}},
                            "Mounts": [
                                {
                                    "Type": "bind",
                                    "Source": f"{tmp_path}/postgres/data",
                                    "Destination": "/var/lib/postgresql/data",
                                    "RW": True,
                                }
                            ],
                        }
                    ]
                ),
            )
        if command == [str(module.CANONICAL_DOCKER), "network", "inspect", NETWORK]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    [
                        {
                            "Name": NETWORK,
                            "Internal": projections["network_internal"],
                            "Labels": {
                                "com.docker.compose.project": PROJECT,
                                "com.docker.compose.network": "data-plane",
                            },
                            "Containers": {containers["postgres"]: {}},
                        }
                    ]
                ),
            )
        if command == ["df", "-PT", f"{tmp_path}/postgres/data"]:
            return subprocess.CompletedProcess(
                command, 0, stdout="Filesystem Type\n/dev/synthetic btrfs\n"
            )
        assert command == [
            str(module.CANONICAL_DOCKER),
            "exec",
            "-i",
            containers["postgres"],
            "pg_restore",
            "--list",
        ]
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["timeout"] == module.ARCHIVE_LIST_TIMEOUT_SECONDS == 600
        assert kwargs["check"] is True
        descriptor = kwargs["stdin"]
        assert isinstance(descriptor, int)
        archive = os.read(descriptor, 1024)
        if archive != b"PGDMP synthetic custom-format dump":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, "run", list_archive)
    monkeypatch.setattr(
        module, "_test_actual_gate_verifier", module._verify_read_only_gates, raising=False
    )
    monkeypatch.setattr(module, "_verify_read_only_gates", lambda _postgres_id: None)
    return (
        module,
        {
            "deployment": deployment,
            "image": image,
            "runtime": runtime,
            "resources": resources,
            "bootstrap": bootstrap,
            "backups": backups,
            "dump": dump,
            "receipt": receipt,
            "evidence": evidence,
            "config_hashes": config_hashes,
            "containers": containers,
            "projections": projections,
        },
        commands,
    )


def test_attestation_publish_verify_is_atomic_readback_and_only_lists_archive(
    attestation: tuple[ModuleType, dict[str, object], list[list[str]]],
) -> None:
    module, paths, commands = attestation
    assert module.write() == []
    output = next(paths["evidence"].iterdir())
    metadata = output.stat()
    rendered = tomllib.loads(output.read_text(encoding="utf-8"))
    assert output.name.endswith(".runtime-attestation.toml")
    assert metadata.st_mode & 0o777 == 0o400 and metadata.st_nlink == 1
    assert (
        rendered["resolved_smoke_compose_sha256"]
        == tomllib.loads(paths["runtime"].read_text(encoding="utf-8"))["resolved_compose_sha256"][
            "smoke"
        ]
    )
    assert (
        rendered["resolved_pilot_compose_sha256"]
        == tomllib.loads(paths["runtime"].read_text(encoding="utf-8"))["resolved_compose_sha256"][
            "pilot"
        ]
    )
    assert rendered["compose_source_sha256"] == _sha(
        (ROOT / "ops/nas/compose.example.yml").read_bytes()
    )
    assert rendered["pilot_overlay_source_sha256"] == _sha(
        (ROOT / "ops/nas/compose.pilot.example.yml").read_bytes()
    )
    assert rendered["live_service_config_hashes"] == paths["config_hashes"]
    assert not [path for path in paths["evidence"].iterdir() if ".partial-" in path.name]
    assert module.verify() == []
    assert all("compose" not in command and "config" not in command for command in commands)
    assert all(
        command[0] in {str(module.CANONICAL_DOCKER), str(module.CANONICAL_GIT)}
        for command in commands
    )
    assert [str(module.CANONICAL_DOCKER), "info", "--format", "{{.ID}}\t{{.Name}}"] in commands
    assert [
        str(module.CANONICAL_DOCKER),
        "ps",
        "--no-trunc",
        "--filter",
        f"label=com.docker.compose.project={PROJECT}",
        "--format",
        "{{.ID}}",
    ] in commands
    assert [
        str(module.CANONICAL_DOCKER),
        "inspect",
        "--format",
        module.CONTAINER_FORMAT,
        paths["containers"]["gateway"],
    ] in commands
    assert [
        str(module.CANONICAL_DOCKER),
        "inspect",
        "--format",
        module.POSTGRES_STORAGE_FORMAT,
        paths["containers"]["postgres"],
    ] in commands
    invoked = "\n".join(" ".join(command) for command in commands)
    assert " pg_dump" not in invoked and "psql" not in invoked
    assert invoked.count(" pg_restore --list") == 2
    assert (
        " backup.sh" not in invoked and " lifecycle" not in invoked and " compose " not in invoked
    )
    assert "Config.Env" not in output.read_text(encoding="utf-8")


def test_retained_attestation_verifies_after_write_window_but_cannot_be_reissued(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, paths, _ = attestation
    assert module.write() == []
    output = next(paths["evidence"].glob("*.runtime-attestation.toml"))
    recorded = tomllib.loads(output.read_text(encoding="utf-8"))
    created = datetime.fromisoformat(recorded["dump_created_at"].replace("Z", "+00:00"))
    later = created + timedelta(seconds=module.MAX_AGE_SECONDS + 60)

    class LaterDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz == UTC
            return later

    monkeypatch.setattr(module, "datetime", LaterDatetime)
    assert module.verify() == []
    assert module.write() == ["backup_runtime_attestation_refused"]
    projections = paths["projections"]
    projections["engine"] = "different-engine\tnas-synthetic\n"
    assert module.verify() == ["backup_runtime_attestation_refused"]
    projections["engine"] = f"{ENGINE_ID}\t{ENGINE_NAME}\n"

    too_late = (
        (created + timedelta(seconds=module.MAX_AGE_SECONDS + 1)).isoformat().replace("+00:00", "Z")
    )
    _rewrite(
        output,
        output.read_text(encoding="utf-8").replace(
            f"attested_at = {json.dumps(recorded['attested_at'])}",
            f"attested_at = {json.dumps(too_late)}",
        ),
    )
    assert module.verify() == ["backup_runtime_attestation_mismatch"]


def test_attestation_refuses_future_recorded_time(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, paths, _ = attestation
    assert module.write() == []
    output = next(paths["evidence"].glob("*.runtime-attestation.toml"))
    recorded = tomllib.loads(output.read_text(encoding="utf-8"))
    created = datetime.fromisoformat(recorded["dump_created_at"].replace("Z", "+00:00"))
    frozen = created + timedelta(seconds=60)

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz == UTC
            return frozen

    monkeypatch.setattr(module, "datetime", FrozenDatetime)
    future = (created + timedelta(seconds=120)).isoformat().replace("+00:00", "Z")
    _rewrite(
        output,
        output.read_text(encoding="utf-8").replace(
            f"attested_at = {json.dumps(recorded['attested_at'])}",
            f"attested_at = {json.dumps(future)}",
        ),
    )
    assert module.verify() == ["backup_runtime_attestation_mismatch"]


def test_writer_refuses_when_archive_check_finishes_after_freshness_window(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, paths, _ = attestation
    created = datetime.strptime(paths["dump"].name[6:22], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    current = created + timedelta(seconds=module.MAX_AGE_SECONDS - 1)

    class MovingDatetime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz == UTC
            return current

    monkeypatch.setattr(module, "datetime", MovingDatetime)
    list_archive = module.subprocess.run

    def slow_archive(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        nonlocal current
        result = list_archive(command, **kwargs)
        current = created + timedelta(seconds=module.MAX_AGE_SECONDS + 1)
        return result

    monkeypatch.setattr(module.subprocess, "run", slow_archive)
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not list(paths["evidence"].iterdir())


@pytest.mark.parametrize("archive", (b"PGDMP", b"PGDMP invalid archive body"))
def test_checksum_matching_magic_prefix_is_not_a_readable_archive(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]], archive: bytes
) -> None:
    module, paths, commands = attestation
    paths["dump"].write_bytes(archive)
    paths["dump"].chmod(0o600)
    _rewrite(paths["receipt"], f"{_sha(archive)}  {paths['dump'].name}\n", 0o600)

    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not list(paths["evidence"].iterdir())
    assert commands[-1][-2:] == ["pg_restore", "--list"]


def test_archive_list_timeout_refuses_publication(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, paths, _ = attestation

    def timeout(command: list[str], **kwargs: object) -> None:
        assert command[-2:] == ["pg_restore", "--list"]
        assert kwargs["timeout"] == module.ARCHIVE_LIST_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(module.subprocess, "run", timeout)
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not list(paths["evidence"].iterdir())


@pytest.mark.parametrize(
    "field", ("app_image_id", "web_image_id", "proxy_image_digest", "compose_hash")
)
@pytest.mark.parametrize("mutation", ("missing", "mismatch"))
def test_deployment_manifest_images_and_compose_are_bound_to_admissions(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
    field: str,
    mutation: str,
) -> None:
    module, paths, _ = attestation
    manifest = tomllib.loads(paths["deployment"].read_text(encoding="utf-8"))
    original = f'{field} = "{manifest[field]}"\n'
    incorrect = ("" if field == "compose_hash" else "sha256:") + "f" * 64
    replacement = "" if mutation == "missing" else f'{field} = "{incorrect}"\n'
    _rewrite(
        paths["deployment"],
        paths["deployment"].read_text(encoding="utf-8").replace(original, replacement),
    )
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not list(paths["evidence"].iterdir())


def test_bootstrap_compose_digest_must_match_canonical_source(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
) -> None:
    module, paths, _ = attestation
    _rewrite(
        paths["bootstrap"],
        paths["bootstrap"]
        .read_text(encoding="utf-8")
        .replace(
            f'compose_sha256 = "{_sha((ROOT / "ops/nas/compose.example.yml").read_bytes())}"',
            f'compose_sha256 = "{"f" * 64}"',
        ),
    )
    assert module.write() == ["backup_runtime_attestation_refused"]


def test_runtime_proxy_reference_must_match_image_manifest(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
) -> None:
    module, paths, _ = attestation
    original = "caddy@sha256:" + "7" * 64
    incorrect = "caddy@sha256:" + "8" * 64
    _rewrite(
        paths["runtime"],
        paths["runtime"]
        .read_text(encoding="utf-8")
        .replace(f'proxy = "{original}"', f'proxy = "{incorrect}"'),
    )
    assert module.write() == ["backup_runtime_attestation_refused"]


def test_attester_runs_existing_gates_with_synthetic_secret_kept_private(
    attestation: tuple[ModuleType, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module, paths, commands = attestation
    monkeypatch.setattr(module, "_verify_read_only_gates", module._test_actual_gate_verifier)
    monkeypatch.setattr(sys, "argv", ["attestation"])
    nas_tools = importlib.import_module("nas_tools")
    module.CANONICAL_DOCKER.chmod(0o400)
    with pytest.raises(RuntimeError):
        nas_tools.docker()
    module.CANONICAL_DOCKER.chmod(0o500)
    assert nas_tools.docker() == str(module.CANONICAL_DOCKER)

    assert module.main() == 0
    output = capsys.readouterr().out
    evidence = next(paths["evidence"].glob("*.runtime-attestation.toml"))
    assert "synthetic-password-marker" not in output + evidence.read_text(encoding="utf-8")
    assert output == "PostgreSQL backup runtime attestation published\n"
    assert sum(command[-3:] == ["config", "--hash", "*"] for command in commands) == 4
    assert [str(module.CANONICAL_DOCKER), "network", "inspect", NETWORK] in commands
    assert ["df", "-PT", str(paths["resources"].parent.parent / "postgres/data")] in commands


@pytest.mark.parametrize(
    "drift",
    (
        "bootstrap_render",
        "runtime_render",
        "runtime_config",
        "network_internal",
        "host_ports",
        "resource_numeric",
        "two_modes",
    ),
)
def test_existing_gates_refuse_synthetic_attestation_drift(
    attestation: tuple[ModuleType, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    module, paths, _ = attestation
    monkeypatch.setattr(module, "_verify_read_only_gates", module._test_actual_gate_verifier)
    if drift == "bootstrap_render":
        admission = paths["bootstrap"]
        original = tomllib.loads(admission.read_text(encoding="utf-8"))["resolved_postgres_sha256"]
        _rewrite(admission, admission.read_text(encoding="utf-8").replace(original, "f" * 64))
    elif drift == "runtime_render":
        admission = paths["runtime"]
        original = tomllib.loads(admission.read_text(encoding="utf-8"))["resolved_compose_sha256"][
            "smoke"
        ]
        _rewrite(admission, admission.read_text(encoding="utf-8").replace(original, "f" * 64))
    elif drift == "runtime_config":
        paths["projections"]["running_hashes"]["gateway"] = "f" * 64
    elif drift == "network_internal":
        paths["projections"]["network_internal"] = False
    elif drift == "host_ports":
        paths["projections"]["host_ports"] = True
    elif drift == "resource_numeric":
        resources = paths["resources"]
        _rewrite(
            resources,
            resources.read_text(encoding="utf-8").replace("logical_cpus = 4", "logical_cpus = 0"),
        )
    else:
        paths["projections"]["pilot_hashes_match"] = True

    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not list(paths["evidence"].iterdir())


@pytest.mark.parametrize("drift", ("runtime_file", "gateway_label"))
def test_attester_rechecks_input_and_live_identity_after_archive_inspection(
    attestation: tuple[ModuleType, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    module, paths, _ = attestation
    archive_runner = module.subprocess.run

    def mutate_after_archive(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        result = archive_runner(command, **kwargs)
        if command[-2:] == ["pg_restore", "--list"]:
            if drift == "runtime_file":
                runtime = paths["runtime"]
                _rewrite(
                    runtime,
                    runtime.read_text(encoding="utf-8").replace(
                        'status = "admitted"', 'status = "changed"'
                    ),
                )
            else:
                gateway = paths["containers"]["gateway"]
                before = paths["projections"]["container"][gateway]
                paths["projections"]["container"][gateway] = before.replace(
                    paths["config_hashes"]["gateway"], "f" * 64
                )
        return result

    monkeypatch.setattr(module.subprocess, "run", mutate_after_archive)
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not list(paths["evidence"].iterdir())


@pytest.mark.parametrize(
    "mutation",
    ("missing_pilot", "invalid_service_reference", "dirty_source", "source_head_drift"),
)
def test_attestation_refuses_closed_runtime_admission_or_source_drift(
    attestation: tuple[ModuleType, dict[str, object], list[list[str]]], mutation: str
) -> None:
    module, paths, commands = attestation
    if mutation == "missing_pilot":
        _rewrite(
            paths["runtime"],
            paths["runtime"].read_text(encoding="utf-8").replace("\npilot = ", "\n# pilot = ", 1),
        )
    elif mutation == "invalid_service_reference":
        _rewrite(
            paths["runtime"],
            paths["runtime"]
            .read_text(encoding="utf-8")
            .replace(
                'gateway = "sha256:' + "1" * 64 + '"\nworker-enrollment',
                'gateway = "not-an-image-reference"\nworker-enrollment',
                1,
            ),
        )
    elif mutation == "dirty_source":
        paths["projections"]["git_dirty"] = " M synthetic-only-change\n"
    else:
        paths["projections"]["git_head"] = "d" * 40
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert list(paths["evidence"].iterdir()) == []
    assert all(command[0] == str(module.CANONICAL_GIT) for command in commands)


@pytest.mark.parametrize("kind", ("bad_magic", "bad_checksum", "stale"))
def test_attestation_refuses_wrong_dump_magic_checksum_or_timestamp(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]], kind: str
) -> None:
    module, paths, _ = attestation
    if kind == "bad_magic":
        paths["dump"].write_bytes(b"not-a-postgresql-custom-dump")
        paths["dump"].chmod(0o600)
        paths["receipt"].write_text(
            f"{_sha(paths['dump'].read_bytes())}  {paths['dump'].name}\n", encoding="ascii"
        )
        paths["receipt"].chmod(0o600)
    elif kind == "bad_checksum":
        paths["dump"].write_bytes(b"PGDMP changed after receipt")
        paths["dump"].chmod(0o600)
    else:
        old_dump = paths["backups"] / "my-pa-20000101T000000Z.dump"
        old_dump.write_bytes(b"PGDMP old custom-format dump")
        old_dump.chmod(0o600)
        old_receipt = paths["backups"] / f"{old_dump.name}.sha256"
        old_receipt.write_text(
            f"{_sha(old_dump.read_bytes())}  {old_dump.name}\n", encoding="ascii"
        )
        old_receipt.chmod(0o600)
        _rewrite(
            paths["deployment"],
            paths["deployment"]
            .read_text(encoding="utf-8")
            .replace(str(paths["receipt"]), str(old_receipt)),
        )
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert list(paths["evidence"].iterdir()) == []


@pytest.mark.parametrize(
    "mutation",
    (
        "deployment_commit",
        "image_tree",
        "runtime_image",
        "resource_engine",
        "resource_container",
        "bootstrap_image",
    ),
)
def test_attestation_refuses_cross_artifact_identity_drift(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]], mutation: str
) -> None:
    module, paths, _ = attestation
    target = {
        "deployment_commit": paths["deployment"],
        "image_tree": paths["image"],
        "runtime_image": paths["runtime"],
        "resource_engine": paths["resources"],
        "resource_container": paths["resources"],
        "bootstrap_image": paths["bootstrap"],
    }[mutation]
    old = target.read_text(encoding="utf-8")
    if mutation == "deployment_commit":
        changed = old.replace(COMMIT, "d" * 40, 1)
    elif mutation == "image_tree":
        changed = old.replace(f'repository_tree = "{TREE}"', f'repository_tree = "{"d" * 40}"')
    elif mutation == "runtime_image":
        changed = old.replace('gateway = "sha256:' + "1" * 64, 'gateway = "sha256:' + "d" * 64)
    elif mutation == "resource_engine":
        changed = old.replace(f'docker_engine_id = "{ENGINE_ID}"', 'docker_engine_id = "wrong"')
    elif mutation == "resource_container":
        changed = old.replace(
            'postgres_container_id = "' + "1" * 64,
            'postgres_container_id = "' + "d" * 64,
        )
    else:
        changed = old.replace(
            'postgres_image_id = "sha256:' + "3" * 64, 'postgres_image_id = "sha256:' + "d" * 64
        )
    _rewrite(target, changed)
    assert module.write() == ["backup_runtime_attestation_refused"]


@pytest.mark.parametrize(
    "attack",
    (
        "engine_mismatch",
        "container_mismatch",
        "image_mismatch",
        "label_mismatch",
        "engine_secret_json",
        "container_secret_extra_field",
        "control_character",
        "separator_injection",
        "unexpected_count",
        "unexpected_identifier",
        "storage_extra_field",
    ),
)
def test_attestation_refuses_malformed_or_secret_bearing_docker_projections(
    attestation: tuple[ModuleType, dict[str, object], list[list[str]]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    attack: str,
) -> None:
    module, paths, _ = attestation
    projections = paths["projections"]
    containers = paths["containers"]
    gateway = containers["gateway"]
    sensitive_probe = "MY_PA_DB_" + "PASSWORD=synthetic-secret-must-not-escape"

    if attack == "engine_mismatch":
        projections["engine"] = f"wrong-engine\t{ENGINE_NAME}\n"
    elif attack == "container_mismatch":
        projections["container"][gateway] = projections["container"][gateway].replace(
            gateway, "d" * 64, 1
        )
    elif attack == "image_mismatch":
        projections["container"][gateway] = projections["container"][gateway].replace(
            "sha256:" + "1" * 64, "sha256:" + "d" * 64, 1
        )
    elif attack == "label_mismatch":
        projections["container"][gateway] = projections["container"][gateway].replace(
            PROJECT, "wrong-project", 1
        )
    elif attack == "engine_secret_json":
        projections["engine"] = '{"Config":{"Env":["' + sensitive_probe + '"]}}\n'
    elif attack == "container_secret_extra_field":
        projections["container"][gateway] = (
            projections["container"][gateway].rstrip("\n")
            + '\t{"Config":{"Env":["'
            + sensitive_probe
            + '"]}}\n'
        )
    elif attack == "control_character":
        projections["container"][gateway] = projections["container"][gateway].replace(
            "\tgateway\t", "\tgateway\x1f\t", 1
        )
    elif attack == "separator_injection":
        projections["container"][gateway] = projections["container"][gateway].replace(
            gateway, gateway + "\tforged-field", 1
        )
    elif attack == "unexpected_count":
        projections["ids"] = "".join(
            f"{container_id}\n" for name, container_id in containers.items() if name != "proxy"
        )
    elif attack == "unexpected_identifier":
        forged = "f" * 64
        projections["ids"] = projections["ids"].replace(gateway, forged, 1)
        projections["container"][forged] = projections["container"][gateway]
    else:
        projections["storage"] = projections["storage"].replace("\t", "\textra\t", 1)

    monkeypatch.setattr(sys, "argv", ["attestation"])
    assert module.main() == 1
    stdout = capsys.readouterr().out
    assert stdout == (
        "PostgreSQL backup runtime attestation refused: backup_runtime_attestation_refused\n"
    )
    assert list(paths["evidence"].iterdir()) == []
    assert sensitive_probe not in stdout


def test_attestation_refuses_linked_files_untrusted_modes_and_partial_or_existing_output(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
) -> None:
    module, paths, _ = attestation
    target = paths["backups"] / "target.dump"
    target.write_bytes(b"PGDMP target")
    paths["dump"].unlink()
    paths["dump"].symlink_to(target)
    assert module.write() == ["backup_runtime_attestation_refused"]
    paths["dump"].unlink()
    paths["dump"].write_bytes(b"PGDMP restored")
    paths["dump"].chmod(0o640)
    assert module.write() == ["backup_runtime_attestation_refused"]
    paths["dump"].chmod(0o600)
    linked = paths["backups"] / "linked.dump"
    os.link(paths["dump"], linked)
    assert module.write() == ["backup_runtime_attestation_refused"]
    linked.unlink()
    paths["receipt"].write_text(
        f"{_sha(paths['dump'].read_bytes())}  {paths['dump'].name}\n", encoding="ascii"
    )
    paths["receipt"].chmod(0o600)
    output = paths["evidence"] / f"{paths['dump'].name}.runtime-attestation.toml"
    output.write_text("immutable-existing-output", encoding="utf-8")
    output.chmod(0o400)
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert output.read_text(encoding="utf-8") == "immutable-existing-output"
    output.unlink()
    preserved = paths["evidence"] / "preserved"
    preserved.write_text("do-not-overwrite", encoding="utf-8")
    output.symlink_to(preserved)
    assert module.write() == ["backup_runtime_attestation_refused"]
    assert preserved.read_text(encoding="utf-8") == "do-not-overwrite"
    assert not [path for path in paths["evidence"].iterdir() if ".partial-" in path.name]


def test_attestation_verifier_refuses_interrupted_partial_and_tampered_readback(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
) -> None:
    module, paths, _ = attestation
    assert module.write() == []
    output = next(paths["evidence"].glob("*.runtime-attestation.toml"))
    partial = paths["evidence"] / f".{output.name}.partial-interrupted"
    partial.write_text("incomplete", encoding="utf-8")
    assert module.verify() == ["backup_runtime_attestation_partial"]
    partial.unlink()
    output.chmod(0o600)
    output.write_text('schema = "tampered"\n', encoding="utf-8")
    output.chmod(0o400)
    assert module.verify() == ["backup_runtime_attestation_mismatch"]


def test_attestation_writer_refuses_interrupted_partial_before_publication(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
) -> None:
    module, paths, _ = attestation
    output = paths["evidence"] / f"{paths['dump'].name}.runtime-attestation.toml"
    partial = paths["evidence"] / f".{output.name}.partial-interrupted"
    partial.write_text("incomplete", encoding="utf-8")

    assert module.write() == ["backup_runtime_attestation_refused"]
    assert not output.exists()
    assert list(paths["evidence"].iterdir()) == [partial]
    assert partial.read_text(encoding="utf-8") == "incomplete"
    assert module.verify() == ["backup_runtime_attestation_partial"]


@pytest.mark.parametrize(
    "attack",
    (
        "group-writable-file",
        "world-writable-file",
        "non-executable-file",
        "nonroot-file",
        "hardlink-file",
        "symlink-file",
        "writable-parent",
        "nonroot-parent",
    ),
)
def test_attestation_refuses_untrusted_canonical_clis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    module = _module()
    tools = tmp_path / "trusted-tools"
    tools.mkdir(mode=0o755)
    tools.chmod(0o755)
    docker = tools / "docker"
    git = tools / "git"
    for path in (docker, git):
        path.write_text("synthetic executable", encoding="utf-8")
        path.chmod(0o755)
    tools_inode = tools.stat().st_ino
    docker_inode = docker.stat().st_ino
    original_fstat = os.fstat
    attack_active = False

    def root_fstat(descriptor: int) -> SimpleNamespace:
        source = original_fstat(descriptor)
        directory = stat.S_ISDIR(source.st_mode)
        mode = (source.st_mode & ~0o7777) | 0o755 if directory else source.st_mode
        owner = 0
        if attack_active and directory and source.st_ino == tools_inode:
            if attack == "writable-parent":
                mode |= 0o022
            elif attack == "nonroot-parent":
                owner = 1000
        if attack_active and source.st_ino == docker_inode and attack == "nonroot-file":
            owner = 1000
        return SimpleNamespace(
            st_mode=mode,
            st_uid=owner,
            st_nlink=source.st_nlink,
            st_size=source.st_size,
            st_dev=source.st_dev,
            st_ino=source.st_ino,
        )

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.os, "fstat", root_fstat)
    monkeypatch.setattr(module, "CANONICAL_DOCKER", docker)
    monkeypatch.setattr(module, "CANONICAL_GIT", git)
    module._require_root_and_tools()

    attack_active = True
    if attack == "group-writable-file":
        docker.chmod(0o775)
    elif attack == "world-writable-file":
        docker.chmod(0o757)
    elif attack == "non-executable-file":
        docker.chmod(0o644)
    elif attack == "hardlink-file":
        os.link(docker, tools / "docker-alias")
    elif attack == "symlink-file":
        docker.unlink()
        docker.symlink_to(git)

    with pytest.raises(OSError):
        module._require_root_and_tools()


def test_attestation_trust_helpers_refuse_symlink_parent_file_mode_and_hardlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original_fstat = os.fstat
    synthetic_trusted_ancestors = False

    def root_fstat(descriptor: int) -> SimpleNamespace:
        source = original_fstat(descriptor)
        return SimpleNamespace(
            st_mode=(
                (source.st_mode & ~0o7777) | 0o755
                if synthetic_trusted_ancestors and stat.S_ISDIR(source.st_mode)
                else source.st_mode
            ),
            st_uid=0,
            st_nlink=source.st_nlink,
            st_size=source.st_size,
            st_dev=source.st_dev,
            st_ino=source.st_ino,
        )

    monkeypatch.setattr(module.os, "fstat", root_fstat)
    trusted = tmp_path / "trusted"
    trusted.mkdir(mode=0o755)
    trusted.chmod(0o755)
    symlink = tmp_path / "symlink"
    symlink.symlink_to(trusted, target_is_directory=True)
    synthetic_trusted_ancestors = True
    descriptor = module._trusted_directory_fd(trusted, leaf_mode=0o755)
    os.close(descriptor)
    with pytest.raises(OSError):
        module._trusted_directory_fd(symlink, leaf_mode=0o755)
    synthetic_trusted_ancestors = False
    with pytest.raises(OSError):
        module._trusted_directory_fd(tmp_path, leaf_mode=0o755)
    monkeypatch.setattr(
        module,
        "_trusted_directory_fd",
        lambda path, *, leaf_mode: os.open(path, os.O_RDONLY | os.O_DIRECTORY),
    )
    root = tmp_path / "root"
    root.mkdir(mode=0o700)
    value = root / "evidence.toml"
    value.write_text("ok", encoding="utf-8")
    value.chmod(0o400)
    assert module._read_trusted(value, root, 0o400, 16) == b"ok"
    value.chmod(0o600)
    with pytest.raises(OSError):
        module._read_trusted(value, root, 0o400, 16)
    value.chmod(0o400)
    alias = root / "alias.toml"
    os.link(value, alias)
    with pytest.raises(OSError):
        module._read_trusted(value, root, 0o400, 16)
    alias.unlink()
    linked = root / "linked.toml"
    linked.symlink_to(value)
    with pytest.raises(OSError):
        module._read_trusted(linked, root, 0o400, 16)


def test_attestation_main_never_prints_synthetic_input_or_secret_like_values(
    attestation: tuple[ModuleType, dict[str, Path], list[list[str]]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, _paths, _ = attestation
    monkeypatch.setattr(sys, "argv", ["attestation"])
    assert module.main() == 0
    assert capsys.readouterr().out == "PostgreSQL backup runtime attestation published\n"
    source = (ROOT / "ops/nas/write-postgres-backup-runtime-attestation.py").read_text(
        encoding="utf-8"
    )
    assert "pg_dump" not in source and "psql" not in source
    assert '"pg_restore", "--list"' in source
