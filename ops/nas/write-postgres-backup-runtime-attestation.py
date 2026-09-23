#!/usr/bin/env python3
"""Publish one immutable, live-bound PostgreSQL backup attestation.

This is deliberately not a backup, deployment, or password-rotation command.
It can attest only the receipt named by the root-owned canonical deployment
manifest, and publishes only to the fixed root-owned evidence directory.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

CANONICAL_DOCKER = Path("/usr/local/bin/docker")
CANONICAL_GIT = Path("/usr/bin/git")
DEPLOYMENT_MANIFEST = Path("/volume1/my-pa/deployment/manifest.toml")
BACKUP_ROOT = Path("/volume1/my-pa/backups")
IMAGE_MANIFEST = Path("/etc/my-pa/image-manifest.toml")
RUNTIME_ADMISSION = Path("/etc/my-pa/runtime-admission.toml")
POSTGRES_RESOURCES = Path("/etc/my-pa/postgres-resources.toml")
POSTGRES_BOOTSTRAP_ADMISSION = Path("/etc/my-pa/postgres-bootstrap-admission.toml")
ATTESTATION_ROOT = Path("/var/lib/my-pa/postgres-backup-attestations")

SCHEMA = "my-pa.nas-postgres-backup-runtime-attestation.v1"
PROJECT = "my-pa-nas-contract"
NETWORK = "my-pa-nas-contract_data-plane"
SERVICES = {
    "postgres",
    "gateway",
    "worker-enrollment",
    "worker-capture",
    "web",
    "proxy",
}
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
SHA256_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
RECEIPT_NAME = re.compile(r"my-pa-(\d{8}T\d{6}Z)\.dump\.sha256\Z")
MAX_AGE_SECONDS = 900
ARCHIVE_LIST_TIMEOUT_SECONDS = 600
SAFE_ENGINE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
SAFE_PATH = re.compile(r"/[A-Za-z0-9._/-]*\Z")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
CONTAINER_FORMAT = (
    "{{.Id}}\t{{.Image}}\t{{.State.Running}}\t"
    '{{index .Config.Labels "com.docker.compose.project"}}\t'
    '{{index .Config.Labels "com.docker.compose.service"}}\t'
    '{{index .Config.Labels "com.docker.compose.oneoff"}}\t'
    '{{index .Config.Labels "com.docker.compose.container-number"}}\t'
    '{{index .Config.Labels "com.docker.compose.config-hash"}}'
)
POSTGRES_STORAGE_FORMAT = (
    "{{range .Mounts}}{{.Type}},{{.Source}},{{.Destination}},{{.RW}};{{end}}\t"
    "{{range $name, $_ := .NetworkSettings.Networks}}{{$name}},{{end}}"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _trusted_directory_fd(path: Path, *, leaf_mode: int) -> int:
    """Open an absolute root-owned directory through an unlinked ancestor chain."""
    if (
        not path.is_absolute()
        or path == Path("/")
        or any(part in {"", ".", ".."} for part in path.parts[1:])
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
    ):
        raise OSError("descriptor-relative no-follow directory traversal unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        root = os.fstat(descriptor)
        if not (
            stat.S_ISDIR(root.st_mode)
            and root.st_uid == 0
            and stat.S_IMODE(root.st_mode) & 0o022 == 0
            and root.st_nlink >= 1
        ):
            raise OSError("untrusted filesystem root")
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            metadata = os.fstat(descriptor)
            if not (
                stat.S_ISDIR(metadata.st_mode)
                and metadata.st_uid == 0
                and stat.S_IMODE(metadata.st_mode) & 0o022 == 0
                and metadata.st_nlink >= 1
            ):
                raise OSError("untrusted directory ancestor")
        if stat.S_IMODE(os.fstat(descriptor).st_mode) != leaf_mode:
            raise OSError("untrusted canonical directory mode")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _read_trusted(path: Path, parent: Path, mode: int, limit: int) -> bytes:
    """Read a root-only, single-link file without following a final symlink."""
    if path.parent != parent:
        raise OSError("untrusted parent")
    parent_fd = _trusted_directory_fd(parent, leaf_mode=0o700)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if not (
                stat.S_ISREG(before.st_mode)
                and before.st_uid == 0
                and stat.S_IMODE(before.st_mode) == mode
                and before.st_nlink == 1
                and before.st_size <= limit
            ):
                raise OSError("untrusted file metadata")
            chunks: list[bytes] = []
            remaining = limit + 1
            while remaining:
                chunk = os.read(descriptor, min(1_048_576, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            after = os.fstat(descriptor)
            if len(data) > limit or (before.st_dev, before.st_ino, before.st_size) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
            ):
                raise OSError("file changed while being read")
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _parse_toml(data: bytes) -> dict[str, Any]:
    parsed = tomllib.loads(data.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("TOML root is not an object")
    return parsed


def _image_gate() -> ModuleType:
    path = Path(__file__).with_name("image_gate.py")
    spec = importlib.util.spec_from_file_location("backup_attestation_image_gate", path)
    if spec is None or spec.loader is None:
        raise ImportError("image gate unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_only_gate(filename: str) -> ModuleType:
    if filename not in {
        "runtime_identity_gate.py",
        "postgres-bootstrap-identity-gate.py",
        "postgres_gate.py",
    }:
        raise ValueError("unsupported read-only gate")
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(filename.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise ImportError("read-only gate unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.strptime(str(value), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise ValueError("invalid backup timestamp") from error
    return parsed


def _rfc3339(value: object) -> bool:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def _run(command: list[str]) -> str:
    return subprocess.run(  # noqa: S603 - fixed Docker command vectors below
        command, check=True, capture_output=True, text=True
    ).stdout


def _one_projection(command: list[str], fields: int) -> list[str]:
    output = _run(command)
    if output.count("\n") != 1 or not output.endswith("\n"):
        raise ValueError("projection did not contain one line")
    line = output[:-1]
    values = line.split("\t")
    if len(values) != fields or any(not value or CONTROL.search(value) for value in values):
        raise ValueError("projection shape mismatch")
    return values


def _require_root_and_tools() -> None:
    if os.geteuid() != 0:
        raise OSError("root operator identity required")
    for path, label in ((CANONICAL_DOCKER, "Docker"), (CANONICAL_GIT, "Git")):
        parent_fd = _trusted_directory_fd(path.parent, leaf_mode=0o755)
        try:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                metadata = os.fstat(descriptor)
                mode = stat.S_IMODE(metadata.st_mode)
                if not (
                    stat.S_ISREG(metadata.st_mode)
                    and metadata.st_uid == 0
                    and metadata.st_nlink == 1
                    and mode & 0o111
                    and mode & 0o022 == 0
                ):
                    raise OSError(f"canonical {label} CLI unavailable")
            finally:
                os.close(descriptor)
        finally:
            os.close(parent_fd)


def _digest_trusted_dump(path: Path, postgres_id: str, expected_digest: str) -> tuple[str, int]:
    """Hash and inspect one trusted descriptor without retaining dump data."""
    if path.parent != BACKUP_ROOT:
        raise OSError("untrusted backup parent")
    parent_fd = _trusted_directory_fd(BACKUP_ROOT, leaf_mode=0o700)
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            before = os.fstat(descriptor)
            if not (
                stat.S_ISREG(before.st_mode)
                and before.st_uid == 0
                and stat.S_IMODE(before.st_mode) == 0o600
                and before.st_nlink == 1
                and 5 <= before.st_size <= 512 * 1024 * 1024 * 1024
            ):
                raise OSError("untrusted dump metadata")
            digest = hashlib.sha256()
            first = b""
            total = 0
            while True:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                if not first:
                    first = chunk[:5]
                digest.update(chunk)
                total += len(chunk)
            after = os.fstat(descriptor)
            if (
                first != b"PGDMP"
                or total != before.st_size
                or digest.hexdigest() != expected_digest
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise OSError("dump changed or does not match its receipt")
            os.lseek(descriptor, 0, os.SEEK_SET)
            subprocess.run(  # noqa: S603 - fixed command and authenticated container ID
                [str(CANONICAL_DOCKER), "exec", "-i", postgres_id, "pg_restore", "--list"],
                stdin=descriptor,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=ARCHIVE_LIST_TIMEOUT_SECONDS,
                check=True,
            )
            after = os.fstat(descriptor)
            if (
                not stat.S_ISREG(after.st_mode)
                or after.st_uid != 0
                or stat.S_IMODE(after.st_mode) != 0o600
                or after.st_nlink != 1
                or (
                    before.st_dev,
                    before.st_ino,
                    before.st_size,
                    before.st_mtime_ns,
                    before.st_ctime_ns,
                )
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise OSError("dump changed during archive inspection")
            return digest.hexdigest(), total
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)


def _receipt_and_dump(
    deployment: dict[str, Any], postgres_id: str, *, require_fresh: bool
) -> tuple[str, str, int, bytes, datetime]:
    receipt_name = str(deployment.get("backup_receipt", ""))
    receipt_path = Path(receipt_name)
    if (
        not receipt_path.is_absolute()
        or receipt_path.parent != BACKUP_ROOT
        or receipt_path != BACKUP_ROOT / receipt_path.name
        or RECEIPT_NAME.fullmatch(receipt_path.name) is None
    ):
        raise ValueError("deployment backup receipt path is not canonical")
    match = RECEIPT_NAME.fullmatch(receipt_path.name)
    if match is None:  # guarded above; keeps type checkers honest
        raise ValueError("invalid receipt name")
    dump_name = receipt_path.name.removesuffix(".sha256")
    receipt = _read_trusted(receipt_path, BACKUP_ROOT, 0o600, 4096)
    expected = re.fullmatch(rf"([0-9a-f]{{64}})  {re.escape(dump_name)}\n", receipt.decode("ascii"))
    if expected is None:
        raise ValueError("invalid checksum receipt")
    created = _timestamp(match.group(1))
    age = (datetime.now(UTC) - created).total_seconds()
    if require_fresh and (age < 0 or age > MAX_AGE_SECONDS):
        raise ValueError("backup receipt is not fresh")
    dump_digest, dump_bytes = _digest_trusted_dump(
        BACKUP_ROOT / dump_name, postgres_id, expected.group(1)
    )
    return dump_name, dump_digest, dump_bytes, receipt, created


def _identity_inputs() -> tuple[dict[str, bytes], dict[str, dict[str, Any]]]:
    paths = {
        "deployment": (DEPLOYMENT_MANIFEST, DEPLOYMENT_MANIFEST.parent),
        "image": (IMAGE_MANIFEST, IMAGE_MANIFEST.parent),
        "runtime": (RUNTIME_ADMISSION, RUNTIME_ADMISSION.parent),
        "resources": (POSTGRES_RESOURCES, POSTGRES_RESOURCES.parent),
        "bootstrap": (POSTGRES_BOOTSTRAP_ADMISSION, POSTGRES_BOOTSTRAP_ADMISSION.parent),
    }
    raw = {
        name: _read_trusted(path, parent, 0o400, 2 * 1024 * 1024)
        for name, (path, parent) in paths.items()
    }
    return raw, {name: _parse_toml(value) for name, value in raw.items()}


def _validate_identity(
    identity: dict[str, dict[str, Any]], raw: dict[str, bytes]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    deployment = identity["deployment"]
    image = identity["image"]
    runtime = identity["runtime"]
    resources = identity["resources"]
    bootstrap = identity["bootstrap"]
    try:
        image_errors = _image_gate()._shape_errors(image)
    except (AttributeError, ImportError):
        image_errors = ["validator"]
    if image_errors:
        raise ValueError("image manifest is not deployable")
    commit = str(image.get("repository_commit", ""))
    tree = str(image.get("repository_tree", ""))
    if (
        deployment.get("schema") != "my-pa.nas-deployment-manifest.v1"
        or deployment.get("repository_commit") != commit
        or deployment.get("repository_tree") != tree
        or not HEX40.fullmatch(commit)
        or not HEX40.fullmatch(tree)
        or not _rfc3339(deployment.get("deployed_at"))
    ):
        raise ValueError("deployment manifest identity mismatch")
    image_digest = _sha256(raw["image"])
    expected_runtime_fields = {
        "schema",
        "status",
        "docker_engine_id",
        "docker_engine_name",
        "image_manifest_sha256",
        "resolved_compose_sha256",
        "service_images",
        "service_image_ids",
    }
    runtime_ids = runtime.get("service_image_ids")
    runtime_images = runtime.get("service_images")
    resolved_compose = runtime.get("resolved_compose_sha256")
    if (
        set(runtime) != expected_runtime_fields
        or runtime.get("schema") != "my-pa.nas-runtime-admission.v1"
        or runtime.get("status") != "admitted"
        or runtime.get("image_manifest_sha256") != image_digest
        or runtime.get("docker_engine_id") != image.get("docker_engine_id")
        or runtime.get("docker_engine_name") != image.get("docker_engine_name")
        or not isinstance(runtime_ids, dict)
        or set(runtime_ids) != SERVICES
        or any(not SHA256_ID.fullmatch(str(value)) for value in runtime_ids.values())
        or not isinstance(runtime_images, dict)
        or set(runtime_images) != SERVICES
        or not isinstance(resolved_compose, dict)
        or set(resolved_compose) != {"smoke", "pilot"}
        or any(not HEX64.fullmatch(str(value)) for value in resolved_compose.values())
    ):
        raise ValueError("runtime admission identity mismatch")
    images = image.get("images")
    if (
        not isinstance(images, dict)
        or any(
            not isinstance(images.get(role), dict) for role in {"postgres", "app", "web", "proxy"}
        )
        or any(
            runtime_ids.get(name) != images.get(role, {}).get("docker_image_id")
            for name, role in {
                "postgres": "postgres",
                "gateway": "app",
                "worker-enrollment": "app",
                "worker-capture": "app",
                "web": "web",
                "proxy": "proxy",
            }.items()
        )
    ):
        raise ValueError("runtime image role mismatch")
    if (
        deployment.get("app_image_id") != images["app"]["docker_image_id"]
        or deployment.get("web_image_id") != images["web"]["docker_image_id"]
        or deployment.get("proxy_image_digest") != images["proxy"]["oci_manifest_digest"]
    ):
        raise ValueError("deployment image identity mismatch")
    for name, reference in runtime_images.items():
        if name == "proxy":
            if reference != images["proxy"]["reference"]:
                raise ValueError("runtime proxy reference mismatch")
        elif reference != runtime_ids[name]:
            raise ValueError("runtime service reference mismatch")
    required_resources = {
        "schema",
        "status",
        "docker_engine_id",
        "postgres_container_id",
        "postgres_image_id",
        "data_network",
        "measured_at",
        "logical_cpus",
        "memory_bytes",
        "minimum_available_storage_bytes",
        "filesystem_type",
        "postgres_data_path",
        "tuning",
    }
    container_id = str(resources.get("postgres_container_id", ""))
    if (
        set(resources) != required_resources
        or resources.get("schema") != "my-pa.nas-postgres-resources.v1"
        or resources.get("status") != "verified"
        or resources.get("docker_engine_id") != image.get("docker_engine_id")
        or not HEX64.fullmatch(container_id)
        or resources.get("postgres_image_id") != runtime_ids["postgres"]
        or resources.get("data_network") != NETWORK
        or not _rfc3339(resources.get("measured_at"))
        or not isinstance(resources.get("postgres_data_path"), str)
        or not Path(str(resources["postgres_data_path"])).is_absolute()
    ):
        raise ValueError("PostgreSQL resource identity mismatch")
    required_bootstrap = {
        "schema",
        "status",
        "repository_commit",
        "repository_tree",
        "docker_engine_id",
        "docker_engine_name",
        "image_manifest_sha256",
        "compose_sha256",
        "resolved_postgres_sha256",
        "postgres_image_id",
        "database_operator_image_id",
        "project_name",
        "service_name",
        "data_network",
        "postgres_data_path",
        "data_network_internal",
    }
    if (
        set(bootstrap) != required_bootstrap
        or bootstrap.get("schema") != "my-pa.nas-postgres-bootstrap-admission.v1"
        or bootstrap.get("status") != "admitted"
        or bootstrap.get("repository_commit") != commit
        or bootstrap.get("repository_tree") != tree
        or bootstrap.get("docker_engine_id") != image.get("docker_engine_id")
        or bootstrap.get("docker_engine_name") != image.get("docker_engine_name")
        or bootstrap.get("image_manifest_sha256") != image_digest
        or bootstrap.get("postgres_image_id") != runtime_ids["postgres"]
        or bootstrap.get("database_operator_image_id") != runtime_ids["gateway"]
        or bootstrap.get("project_name") != PROJECT
        or bootstrap.get("service_name") != "postgres"
        or bootstrap.get("data_network") != NETWORK
        or bootstrap.get("postgres_data_path") != resources.get("postgres_data_path")
        or bootstrap.get("data_network_internal") is not True
        or not HEX64.fullmatch(str(bootstrap.get("compose_sha256", "")))
        or not HEX64.fullmatch(str(bootstrap.get("resolved_postgres_sha256", "")))
    ):
        raise ValueError("PostgreSQL bootstrap admission identity mismatch")
    return deployment, image, runtime, resources


def _source_provenance(image: dict[str, Any]) -> tuple[str, str]:
    """Bind both static Compose sources to the manifest's clean Git source."""
    repository = Path(__file__).resolve().parents[2]
    head = _run([str(CANONICAL_GIT), "-C", str(repository), "rev-parse", "HEAD"]).strip()
    tree = _run([str(CANONICAL_GIT), "-C", str(repository), "rev-parse", "HEAD^{tree}"]).strip()
    dirty = _run([str(CANONICAL_GIT), "-C", str(repository), "status", "--porcelain"])
    if (
        not HEX40.fullmatch(head)
        or not HEX40.fullmatch(tree)
        or head != image.get("repository_commit")
        or tree != image.get("repository_tree")
        or dirty
    ):
        raise ValueError("source provenance mismatch")
    compose = Path(__file__).with_name("compose.example.yml").read_bytes()
    pilot = Path(__file__).with_name("compose.pilot.example.yml").read_bytes()
    if not compose or not pilot:
        raise ValueError("Compose source unavailable")
    return _sha256(compose), _sha256(pilot)


def _live_identity(
    image: dict[str, Any], runtime: dict[str, Any], resources: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    _require_root_and_tools()
    engine_id, engine_name = _one_projection(
        [str(CANONICAL_DOCKER), "info", "--format", "{{.ID}}\t{{.Name}}"], 2
    )
    if (
        not SAFE_ENGINE_NAME.fullmatch(engine_id)
        or not SAFE_ENGINE_NAME.fullmatch(engine_name)
        or engine_id != image.get("docker_engine_id")
        or engine_name != image.get("docker_engine_name")
    ):
        raise ValueError("Docker engine identity mismatch")
    raw_ids = _run(
        [
            str(CANONICAL_DOCKER),
            "ps",
            "--no-trunc",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.ID}}",
        ]
    )
    container_ids = raw_ids.splitlines()
    if (
        len(container_ids) != len(SERVICES)
        or len(set(container_ids)) != len(SERVICES)
        or raw_ids != "".join(f"{value}\n" for value in container_ids)
        or any(CONTROL.search(value) or not HEX64.fullmatch(value) for value in container_ids)
    ):
        raise ValueError("live runtime service set mismatch")
    service_ids: dict[str, str] = {}
    service_config_hashes: dict[str, str] = {}
    runtime_ids = runtime["service_image_ids"]
    for requested_id in sorted(container_ids):
        container_id, image_id, running, project, name, oneoff, number, config_hash = (
            _one_projection(
                [str(CANONICAL_DOCKER), "inspect", "--format", CONTAINER_FORMAT, requested_id], 8
            )
        )
        if (
            container_id != requested_id
            or not HEX64.fullmatch(container_id)
            or not SHA256_ID.fullmatch(image_id)
            or running != "true"
            or project != PROJECT
            or name not in SERVICES
            or name in service_ids
            or oneoff != "False"
            or number != "1"
            or not HEX64.fullmatch(config_hash)
            or image_id != runtime_ids[name]
        ):
            raise ValueError("live runtime container identity mismatch")
        service_ids[name] = container_id
        service_config_hashes[name] = config_hash
    if (
        set(service_ids) != SERVICES
        or service_ids["postgres"] != resources["postgres_container_id"]
        or not SAFE_PATH.fullmatch(str(resources["postgres_data_path"]))
    ):
        raise ValueError("live PostgreSQL container identity mismatch")
    mounts, networks = _one_projection(
        [
            str(CANONICAL_DOCKER),
            "inspect",
            "--format",
            POSTGRES_STORAGE_FORMAT,
            service_ids["postgres"],
        ],
        2,
    )
    expected_mount = f"bind,{resources['postgres_data_path']},/var/lib/postgresql/data,true;"
    if mounts != expected_mount or networks != f"{NETWORK},":
        raise ValueError("live PostgreSQL storage identity mismatch")
    return service_ids, service_config_hashes


def _verify_read_only_gates(postgres_id: str) -> None:
    """Re-run existing admission gates without returning rendered or inspected data."""
    if os.environ.get("MY_PA_NAS_DOCKER") != str(CANONICAL_DOCKER):
        raise ValueError("canonical Docker CLI not selected")
    compose = Path(__file__).with_name("compose.example.yml")
    pilot = Path(__file__).with_name("compose.pilot.example.yml")
    try:
        runtime_gate = _read_only_gate("runtime_identity_gate.py")
        bootstrap_gate = _read_only_gate("postgres-bootstrap-identity-gate.py")
        postgres_gate = _read_only_gate("postgres_gate.py")
        for overlay in (None, pilot):
            if runtime_gate.verify(
                compose,
                IMAGE_MANIFEST,
                pilot_overlay_path=overlay,
                admission_path=RUNTIME_ADMISSION,
                owner_uid=os.geteuid(),
                runner=_run,
            ):
                raise ValueError("runtime admission revalidation refused")
        running_modes = [
            overlay
            for overlay in (None, pilot)
            if not runtime_gate.verify(
                compose,
                IMAGE_MANIFEST,
                pilot_overlay_path=overlay,
                admission_path=RUNTIME_ADMISSION,
                owner_uid=os.geteuid(),
                running=True,
                runner=_run,
            )
        ]
        if len(running_modes) != 1:
            raise ValueError("runtime mode identity refused")
        if bootstrap_gate.verify(
            compose,
            IMAGE_MANIFEST,
            admission_path=POSTGRES_BOOTSTRAP_ADMISSION,
            owner_uid=os.geteuid(),
        ) or postgres_gate.verify(POSTGRES_RESOURCES, live=True, container_id=postgres_id):
            raise ValueError("PostgreSQL admission revalidation refused")
    except Exception:
        # Existing gates can transiently hold Compose or inspect output with
        # credentials. Never expose their exception text or returned payloads.
        raise ValueError("read-only admission revalidation refused") from None


def _render(fields: dict[str, Any]) -> bytes:
    bootstrap_digest = json.dumps(fields["postgres_bootstrap_admission_sha256"])
    lines = [
        f"schema = {json.dumps(fields['schema'])}",
        f"status = {json.dumps(fields['status'])}",
        f"dump_filename = {json.dumps(fields['dump_filename'])}",
        f"dump_sha256 = {json.dumps(fields['dump_sha256'])}",
        f"dump_bytes = {fields['dump_bytes']}",
        f"backup_receipt_filename = {json.dumps(fields['backup_receipt_filename'])}",
        f"backup_receipt_sha256 = {json.dumps(fields['backup_receipt_sha256'])}",
        f"dump_created_at = {json.dumps(fields['dump_created_at'])}",
        f"attested_at = {json.dumps(fields['attested_at'])}",
        f"max_age_seconds = {fields['max_age_seconds']}",
        f"repository_commit = {json.dumps(fields['repository_commit'])}",
        f"repository_tree = {json.dumps(fields['repository_tree'])}",
        f"docker_engine_id = {json.dumps(fields['docker_engine_id'])}",
        f"docker_engine_name = {json.dumps(fields['docker_engine_name'])}",
        f"postgres_container_id = {json.dumps(fields['postgres_container_id'])}",
        f"postgres_image_id = {json.dumps(fields['postgres_image_id'])}",
        f"deployment_manifest_sha256 = {json.dumps(fields['deployment_manifest_sha256'])}",
        f"image_manifest_sha256 = {json.dumps(fields['image_manifest_sha256'])}",
        f"runtime_admission_sha256 = {json.dumps(fields['runtime_admission_sha256'])}",
        f"postgres_resources_sha256 = {json.dumps(fields['postgres_resources_sha256'])}",
        f"postgres_bootstrap_admission_sha256 = {bootstrap_digest}",
        f"resolved_smoke_compose_sha256 = {json.dumps(fields['resolved_smoke_compose_sha256'])}",
        f"resolved_pilot_compose_sha256 = {json.dumps(fields['resolved_pilot_compose_sha256'])}",
        f"compose_source_sha256 = {json.dumps(fields['compose_source_sha256'])}",
        f"pilot_overlay_source_sha256 = {json.dumps(fields['pilot_overlay_source_sha256'])}",
        "",
        "[live_service_container_ids]",
    ]
    lines.extend(
        f"{name} = {json.dumps(fields['live_service_container_ids'][name])}"
        for name in sorted(SERVICES)
    )
    lines.extend(["", "[live_service_config_hashes]"])
    lines.extend(
        f"{name} = {json.dumps(fields['live_service_config_hashes'][name])}"
        for name in sorted(SERVICES)
    )
    return ("\n".join(lines) + "\n").encode()


def _output_path(dump_name: str) -> Path:
    return ATTESTATION_ROOT / f"{dump_name}.runtime-attestation.toml"


def _partial_path(output: Path) -> Path:
    return output.parent / f".{output.name}.partial-{os.getpid()}-{os.urandom(8).hex()}"


def _publish_exclusively(output: Path, data: bytes) -> None:
    if output.parent != ATTESTATION_ROOT:
        raise OSError("untrusted attestation parent")
    partial = _partial_path(output)
    parent_fd = _trusted_directory_fd(ATTESTATION_ROOT, leaf_mode=0o700)
    try:
        partial_prefix = f".{output.name}.partial-"
        if any(name.startswith(partial_prefix) for name in os.listdir(parent_fd)):  # noqa: PTH208
            raise OSError("interrupted attestation partial exists")
        descriptor = os.open(
            partial.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o400,
            dir_fd=parent_fd,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if not (
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == 0
                and stat.S_IMODE(metadata.st_mode) == 0o400
                and metadata.st_nlink == 1
            ):
                raise OSError("unsafe staged attestation")
        finally:
            os.close(descriptor)
        # link(2) provides no-replace atomic publication.  A crash after link
        # but before unlink leaves nlink=2; verification refuses that state.
        try:
            os.link(
                partial.name,
                output.name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except OSError:
            # This invocation's unpublished staging file is the only state
            # removed; a pre-existing immutable output is never replaced.
            os.unlink(partial.name, dir_fd=parent_fd)
            raise
        os.fsync(parent_fd)
        os.unlink(partial.name, dir_fd=parent_fd)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def _collect(*, require_fresh: bool) -> tuple[dict[str, Any], Path]:
    _require_root_and_tools()
    raw, identity = _identity_inputs()
    deployment, image, runtime, resources = _validate_identity(identity, raw)
    compose_source, pilot_source = _source_provenance(image)
    if (
        identity["bootstrap"].get("compose_sha256") != compose_source
        or deployment.get("compose_hash") != compose_source
    ):
        raise ValueError("canonical Compose source identity mismatch")
    services, config_hashes = _live_identity(image, runtime, resources)
    dump_name, dump_digest, dump_bytes, receipt, created = _receipt_and_dump(
        deployment, services["postgres"], require_fresh=require_fresh
    )
    _verify_read_only_gates(services["postgres"])
    raw_after, _ = _identity_inputs()
    if raw_after != raw or _source_provenance(image) != (compose_source, pilot_source):
        raise ValueError("source or admission changed during archive inspection")
    if _live_identity(image, runtime, resources) != (services, config_hashes):
        raise ValueError("running service identity changed during archive inspection")
    attested = datetime.now(UTC)
    if require_fresh and not 0 <= (attested - created).total_seconds() <= MAX_AGE_SECONDS:
        raise ValueError("backup receipt expired before publication")
    fields: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "verified",
        "dump_filename": dump_name,
        "dump_sha256": dump_digest,
        "dump_bytes": dump_bytes,
        "backup_receipt_filename": dump_name + ".sha256",
        "backup_receipt_sha256": _sha256(receipt),
        "dump_created_at": created.isoformat().replace("+00:00", "Z"),
        "attested_at": attested.isoformat().replace("+00:00", "Z"),
        "max_age_seconds": MAX_AGE_SECONDS,
        "repository_commit": image["repository_commit"],
        "repository_tree": image["repository_tree"],
        "docker_engine_id": image["docker_engine_id"],
        "docker_engine_name": image["docker_engine_name"],
        "postgres_container_id": resources["postgres_container_id"],
        "postgres_image_id": resources["postgres_image_id"],
        "deployment_manifest_sha256": _sha256(raw["deployment"]),
        "image_manifest_sha256": _sha256(raw["image"]),
        "runtime_admission_sha256": _sha256(raw["runtime"]),
        "postgres_resources_sha256": _sha256(raw["resources"]),
        "postgres_bootstrap_admission_sha256": _sha256(raw["bootstrap"]),
        "resolved_smoke_compose_sha256": runtime["resolved_compose_sha256"]["smoke"],
        "resolved_pilot_compose_sha256": runtime["resolved_compose_sha256"]["pilot"],
        "compose_source_sha256": compose_source,
        "pilot_overlay_source_sha256": pilot_source,
        "live_service_container_ids": services,
        "live_service_config_hashes": config_hashes,
    }
    return fields, _output_path(dump_name)


def write() -> list[str]:
    try:
        fields, output = _collect(require_fresh=True)
        _publish_exclusively(output, _render(fields))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ):
        return ["backup_runtime_attestation_refused"]
    return []


def verify() -> list[str]:
    try:
        expected, output = _collect(require_fresh=False)
        partial_prefix = f".{output.name}.partial-"
        root_fd = _trusted_directory_fd(ATTESTATION_ROOT, leaf_mode=0o700)
        try:
            if any(name.startswith(partial_prefix) for name in os.listdir(root_fd)):  # noqa: PTH208
                return ["backup_runtime_attestation_partial"]
        finally:
            os.close(root_fd)
        actual = _parse_toml(_read_trusted(output, ATTESTATION_ROOT, 0o400, 64 * 1024))
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ):
        return ["backup_runtime_attestation_refused"]
    required = set(expected)
    required.discard("attested_at")
    try:
        attested = datetime.fromisoformat(str(actual["attested_at"]).replace("Z", "+00:00"))
        created = datetime.fromisoformat(str(actual["dump_created_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError):
        return ["backup_runtime_attestation_mismatch"]
    if (
        set(actual) != set(expected)
        or any(actual.get(key) != expected[key] for key in required)
        or not _rfc3339(actual.get("attested_at"))
        or attested < created
        or (attested - created).total_seconds() > MAX_AGE_SECONDS
        or attested > datetime.now(UTC)
    ):
        return ["backup_runtime_attestation_mismatch"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="verify; never publish")
    args = parser.parse_args()
    errors = verify() if args.verify else write()
    if errors:
        print("PostgreSQL backup runtime attestation refused: " + ", ".join(errors))
        return 1
    if not args.verify:
        print("PostgreSQL backup runtime attestation published")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
