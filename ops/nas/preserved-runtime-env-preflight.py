#!/usr/bin/env python3
"""Read-only, fixed-purpose pre-transfer check of a preserved NAS smoke runtime.

Run as root with host Python 3.8 after verifying and cloning the new source
bundle. This program deliberately accepts identities and a preserved source
directory only; it cannot select a command, interpreter, Docker subcommand,
protected file, or lifecycle mode. All protected values stay in memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import secrets as secure_random
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any

GIT = "/usr/bin/git"
GIT_ALIAS_TARGET = Path("/var/packages/Git/target/bin/git")
GIT_STORE_ALIAS = Path("/var/packages/Git/target")
GIT_STORE_TARGET = Path("/volume1/@appstore/Git")
GIT_REAL = GIT_STORE_TARGET / "bin/git"
DOCKER = "/usr/local/bin/docker"
DOCKER_ALIAS_TARGET = Path("/var/packages/ContainerManager/target/usr/bin/docker")
DOCKER_STORE_ALIAS = Path("/var/packages/ContainerManager/target")
DOCKER_STORE_TARGET = Path("/volume1/@appstore/ContainerManager")
DOCKER_REAL = DOCKER_STORE_TARGET / "usr/bin/docker"
COMPOSE = "/usr/local/bin/docker-compose"
COMPOSE_ALIAS_TARGET = Path("/var/packages/ContainerManager/target/usr/bin/docker-compose")
COMPOSE_REAL = DOCKER_STORE_TARGET / "usr/bin/docker-compose"
DOCKER_SOCKET = Path("/run/docker.sock")
MANIFEST = Path("/etc/my-pa/image-manifest.toml")
OPERATOR_ADMISSION = Path("/etc/my-pa/operator-runtime.toml")
RUNTIME_ADMISSION = Path("/etc/my-pa/runtime-admission.toml")
INGRESS_MANIFEST = Path("/etc/my-pa/ingress-manifest.toml")
CANONICAL_COMPOSE = Path("/etc/my-pa/compose.yml")
SECRETS = Path("/volume1/my-pa/secrets")
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
LINE = re.compile(r'([A-Za-z_][A-Za-z0-9_-]*) = "([^"\\\r\n]*)"\Z')
TABLE = re.compile(r"\[([A-Za-z_][A-Za-z0-9_.-]*)\]\Z")
OPERATOR_KEYS = {
    "schema",
    "status",
    "repository_commit",
    "repository_tree",
    "repository_source_path",
    "docker_engine_id",
    "docker_engine_name",
    "operator_image_id",
    "operator_manifest_digest",
    "operator_archive_path",
    "operator_archive_sha256",
    "operator_candidate_path",
    "operator_candidate_sha256",
    "operator_metadata_path",
    "operator_metadata_sha256",
    "python_version",
    "git_version",
    "openssl_version",
    "compose_version",
}
CANDIDATE_KEYS = {
    "schema",
    "status",
    "repository_commit",
    "repository_tree",
    "built_at",
    "target_os",
    "target_architecture",
    "oci_manifest_digest",
    "docker_image_id",
    "archive_sha256",
    "build_metadata_sha256",
}
SERVICES = {"postgres", "gateway", "worker-enrollment", "worker-capture", "web", "proxy"}
PRODUCTION_KEYS = {
    "NODE_ENV",
    "MYPA_AUTH_MODE",
    "MYPA_CANONICAL_ORIGIN",
    "MYPA_GATEWAY_URL",
    "MYPA_GATEWAY_AUTH_MODE",
    "MYPA_SESSION_SERVICE_SECRET",
    "MY_PA_SESSION_SERVICE_SECRET",
    "MYPA_WEBAUTHN_BFF_SECRET",
    "MY_PA_WEBAUTHN_BFF_SECRET",
    "MY_PA_WEBAUTHN_RP_ID",
    "MY_PA_WEBAUTHN_RP_NAME",
    "MY_PA_WEBAUTHN_ALLOWED_ORIGINS",
    "MY_PA_DB_PASSWORD",
    "MY_PA_APP_IMAGE_ID",
    "MY_PA_WEB_IMAGE_ID",
    "MY_PA_POSTGRES_IMAGE_ID",
    "MY_PA_PROXY_IMAGE",
    "MY_PA_PROXY_IMAGE_DIGEST",
    "MY_PA_UID",
    "MY_PA_GID",
    "MY_PA_PROXY_UID",
    "MY_PA_PROXY_GID",
    "MY_PA_NAS_ROOT",
    "MY_PA_NAS_ENV_FILE",
    "MY_PA_WEB_ENV_FILE",
    "MY_PA_FRONTEND_CLOUDFLARED_IMAGE",
    "MY_PA_FRONTEND_CLOUDFLARED_CONFIG",
    "MY_PA_FRONTEND_CLOUDFLARED_CREDENTIALS_DIR",
    "MY_PA_FRONTEND_CLOUDFLARED_UID",
    "MY_PA_FRONTEND_CLOUDFLARED_GID",
    "MYPA_SOURCE_COMMIT",
    "MYPA_SOURCE_TREE",
    "MYPA_SESSION_SERVICE_URL",
}
FIXED_LIFECYCLE_KEYS = {
    "MY_PA_NAS_DOCKER",
    "MY_PA_NAS_PYTHON",
    "MY_PA_NAS_COMPOSE_FILE",
    "MY_PA_IMAGE_MANIFEST",
    "MY_PA_LIFECYCLE_MODE",
    "MY_PA_PROXY_PORT",
    "MY_PA_TAILNET_HOST",
}
PROHIBITED_ENV_KEYS = {
    "PATH",
    "HOME",
    "ENV",
    "BASH_ENV",
    "ZDOTDIR",
    "IFS",
    "LC_ALL",
    "LANG",
    "PYTHONPATH",
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONINSPECT",
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_PROFILES",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_CONFIG",
    "DOCKER_CERT_PATH",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM",
}
GATE_INSPECT_FIELDS = (
    ("Id", ".Id"),
    ("Name", ".Name"),
    ("Image", ".Image"),
    ("ConfigImage", ".Config.Image"),
    ("Entrypoint", ".Config.Entrypoint"),
    ("Cmd", ".Config.Cmd"),
    ("Nonce", '(index .Config.Labels "io.my-pa.preflight-nonce")'),
    ("Kind", '(index .Config.Labels "io.my-pa.preflight-kind")'),
    ("User", ".Config.User"),
    ("Binds", ".HostConfig.Binds"),
    ("Mounts", ".Mounts"),
    ("NetworkMode", ".HostConfig.NetworkMode"),
    ("ReadonlyRootfs", ".HostConfig.ReadonlyRootfs"),
    ("Tmpfs", ".HostConfig.Tmpfs"),
    ("CapDrop", ".HostConfig.CapDrop"),
    ("SecurityOpt", ".HostConfig.SecurityOpt"),
    ("Privileged", ".HostConfig.Privileged"),
    ("AutoRemove", ".HostConfig.AutoRemove"),
    ("Restart", ".HostConfig.RestartPolicy.Name"),
    ("LogType", ".HostConfig.LogConfig.Type"),
    ("Status", ".State.Status"),
    ("Running", ".State.Running"),
)
GATE_INSPECT_FORMAT = (
    "[" + ",".join("{{json " + field + "}}" for _, field in GATE_INSPECT_FIELDS) + "]"
)


class RefusalError(Exception):
    """A generic, intentionally non-disclosing refusal."""


def _require(condition: bool) -> None:
    if not condition:
        raise RefusalError


def _canonical(path: Path) -> Path:
    value = str(path)
    _require(value.startswith("/") and "//" not in value)
    _require(":" not in value and all(32 <= ord(char) < 127 for char in value))
    _require(not any(part in (".", "..", "") for part in Path(value).parts[1:]))
    return path


def _trusted_ancestors(path: Path, uid: int, stop: Path = Path("/")) -> None:
    path = _canonical(path)
    stop = _canonical(stop)
    _require(stop == Path("/") or stop == path or stop in path.parents)
    current = path
    while True:
        metadata = current.lstat()
        _require(stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == uid)
        _require(stat.S_IMODE(metadata.st_mode) & 0o022 == 0)
        if current == stop:
            return
        current = current.parent


def _trusted_file(
    path: Path,
    uid: int = 0,
    mode: int | tuple[int, ...] = 0o400,
    limit: int = 65536,
    stop: Path = Path("/"),
) -> bytes:
    _canonical(path)
    _trusted_ancestors(path.parent, uid, stop)
    before = path.lstat()
    allowed = {mode} if isinstance(mode, int) else set(mode)
    _require(stat.S_ISREG(before.st_mode) and before.st_uid == uid)
    _require(before.st_nlink == 1 and stat.S_IMODE(before.st_mode) in allowed)
    _require(before.st_size <= limit)
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        opened = os.fstat(descriptor)
        _require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino))
        _require(stat.S_ISREG(opened.st_mode) and opened.st_uid == uid and opened.st_nlink == 1)
        _require(stat.S_IMODE(opened.st_mode) in allowed)
        chunks = bytearray()
        while True:
            chunk = os.read(descriptor, min(65536, limit + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
            _require(len(chunks) <= limit)
        current = os.fstat(descriptor)
        after = path.lstat()

        def identity(item: os.stat_result) -> tuple[int, int, int, int, int]:
            return (
                item.st_dev,
                item.st_ino,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )

        _require(identity(before) == identity(opened) == identity(current) == identity(after))
        return bytes(chunks)
    finally:
        os.close(descriptor)


def _trusted_hash(
    path: Path,
    uid: int = 0,
    limit: int = 1_500_000_000,
    stop: Path = Path("/"),
) -> str:
    _canonical(path)
    _trusted_ancestors(path.parent, uid, stop)
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_uid == uid and before.st_nlink == 1)
    _require(stat.S_IMODE(before.st_mode) in (0o400, 0o600) and before.st_size <= limit)
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        opened = os.fstat(descriptor)
        _require((opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino))
        _require(opened.st_uid == uid and stat.S_IMODE(opened.st_mode) in (0o400, 0o600))
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, 1_048_576)
            if not chunk:
                break
            total += len(chunk)
            _require(total <= limit)
            digest.update(chunk)
        current = os.fstat(descriptor)
        after = path.lstat()
        _require(
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            == (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
                current.st_ctime_ns,
            )
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        )
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _trusted_directory(
    path: Path,
    uid: int = 0,
    mode: int = 0o700,
    stop: Path = Path("/"),
) -> None:
    _trusted_ancestors(path, uid, stop)
    _require(stat.S_IMODE(path.lstat().st_mode) == mode)


def _trusted_regular_executable(path: Path, uid: int, stop: Path, links: int = 1) -> None:
    _canonical(path)
    _trusted_ancestors(path.parent, uid, stop)
    metadata = path.lstat()
    _require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == uid)
    _require(metadata.st_nlink == links and stat.S_IMODE(metadata.st_mode) & 0o022 == 0)
    _require(stat.S_IMODE(metadata.st_mode) & 0o111 != 0)


def _trusted_exact_link(link: Path, target: Path, uid: int, stop: Path) -> None:
    _canonical(link)
    _canonical(target)
    _trusted_ancestors(link.parent, uid, stop)
    before = link.lstat()
    _require(stat.S_ISLNK(before.st_mode) and before.st_uid == uid and before.st_nlink == 1)
    _require(os.readlink(str(link)) == str(target))  # noqa: PTH115 - Python 3.8 host
    after = link.lstat()
    _require(
        (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)
    )


def _trusted_fixed_tool_alias(
    alias: Path,
    alias_target: Path,
    store_alias: Path,
    store_target: Path,
    real_binary: Path,
    links: int,
    uid: int,
    stop: Path,
) -> None:
    """Authenticate two exact Synology links; production dispatch pins every path."""
    _require(alias_target == store_alias / real_binary.relative_to(store_target))
    _require(links > 0)
    _trusted_exact_link(alias, alias_target, uid, stop)
    _trusted_exact_link(store_alias, store_target, uid, stop)
    _trusted_regular_executable(real_binary, uid, stop, links)
    _trusted_exact_link(store_alias, store_target, uid, stop)
    _trusted_exact_link(alias, alias_target, uid, stop)


def _trusted_executable(path: str, uid: int = 0, stop: Path = Path("/")) -> None:
    if path == DOCKER:
        _trusted_fixed_tool_alias(
            Path(DOCKER),
            DOCKER_ALIAS_TARGET,
            DOCKER_STORE_ALIAS,
            DOCKER_STORE_TARGET,
            DOCKER_REAL,
            1,
            uid,
            stop,
        )
        return
    if path == COMPOSE:
        _trusted_fixed_tool_alias(
            Path(COMPOSE),
            COMPOSE_ALIAS_TARGET,
            DOCKER_STORE_ALIAS,
            DOCKER_STORE_TARGET,
            COMPOSE_REAL,
            1,
            uid,
            stop,
        )
        return
    if path == GIT:
        _trusted_fixed_tool_alias(
            Path(GIT),
            GIT_ALIAS_TARGET,
            GIT_STORE_ALIAS,
            GIT_STORE_TARGET,
            GIT_REAL,
            142,
            uid,
            stop,
        )
        return
    _trusted_regular_executable(Path(path), uid, stop)


def _trusted_socket(path: Path, uid: int = 0, stop: Path = Path("/")) -> None:
    _canonical(path)
    _trusted_ancestors(path.parent, uid, stop)
    metadata = path.lstat()
    _require(stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == uid and metadata.st_gid == 0)
    _require(stat.S_IMODE(metadata.st_mode) == 0o660 and metadata.st_nlink == 1)


def _literal_toml(data: bytes) -> dict[str, Any]:
    """Parse only the flat literal subset used by NAS identity artifacts."""
    result: dict[str, Any] = {}
    section = ""
    text = data.decode("utf-8")
    _require(len(data) <= 65536 and "\r" not in text and "\x00" not in text)
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        heading = TABLE.fullmatch(raw)
        if heading:
            section = heading.group(1)
            _require(section not in result)
            result[section] = {}
            continue
        match = LINE.fullmatch(raw)
        if match:
            key, value = match.groups()
            _require(all(32 <= ord(char) < 127 for char in value))
        elif raw == "source_clean = true":
            key, value = "source_clean", True
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]* = [0-9]+", raw):
            key, value = raw.split(" = ", 1)
            value = int(value)
        else:
            raise RefusalError
        target = result if not section else result[section]
        _require(key not in target)
        target[key] = value
    return result


def _literal_env(data: bytes, allowed: set[str] | None = None) -> dict[str, str]:
    """No shell grammar, expansion, continuation, quoting, or duplicate keys."""
    result = {}
    text = data.decode("utf-8")
    _require("\r" not in text and "\x00" not in text)
    for raw in text.splitlines():
        if not raw or raw.startswith("#"):
            continue
        name, separator, value = raw.partition("=")
        _require(bool(separator) and KEY.fullmatch(name) is not None and name not in result)
        _require(name not in PROHIBITED_ENV_KEYS)
        _require(not name.startswith(("DOCKER_", "GIT_", "LD_", "DYLD_", "PYTHON", "COMPOSE_")))
        if allowed is not None:
            _require(name in allowed)
        _require(len(value) <= 8192 and not any(c in value for c in "$`\\\"'"))
        _require(all(ord(c) >= 32 and ord(c) != 127 for c in value))
        result[name] = value
    return result


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    environment = {
        "PATH": "/usr/bin:/bin",
        "LC_ALL": "C",
        "LANG": "C",
        "HOME": "/nonexistent",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }
    if extra:
        _require(set(extra) <= PRODUCTION_KEYS | FIXED_LIFECYCLE_KEYS)
        _require(not set(extra) & set(environment))
        environment.update(extra)
    return environment


def _run(
    argv: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    limit: int = 65536,
    discard: bool = False,
    timeout_seconds: float = 90,
) -> bytes:
    _require(limit >= 0 and timeout_seconds > 0)
    process = subprocess.Popen(  # noqa: S603 - executable and argv are fixed by this helper
        argv,
        cwd=str(cwd) if cwd else None,
        env=_safe_environment(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL if discard else subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    completed = False
    deadline = time.monotonic() + timeout_seconds
    try:
        if discard:
            process.wait(timeout=timeout_seconds)
            output = b""
        else:
            if process.stdout is None:
                raise RefusalError
            chunks: list[bytes] = []
            size = 0
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise subprocess.TimeoutExpired(argv, timeout_seconds)
                    try:
                        chunk = os.read(process.stdout.fileno(), min(65536, limit + 1 - size))
                    except InterruptedError:
                        continue
                    if not chunk:
                        break
                    size += len(chunk)
                    _require(size <= limit)
                    chunks.append(chunk)
            process.wait(timeout=max(0, deadline - time.monotonic()))
            output = b"".join(chunks)
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, argv)
        completed = True
        return output
    finally:
        if not completed:
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if process.stdout is not None:
            process.stdout.close()


def _git(source: Path, args: list[str], runner: Callable[..., bytes]) -> str:
    command = [
        GIT,
        "--no-pager",
        "--no-replace-objects",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "core.attributesfile=/dev/null",
        "-C",
        str(source),
        *args,
    ]
    return runner(command).decode("utf-8").strip()


def _source(
    source: Path,
    expected_commit: str,
    expected_tree: str,
    uid: int,
    runner: Callable[..., bytes],
    stop: Path,
) -> None:
    _trusted_directory(source, uid, stop=stop)
    git_dir = source / ".git"
    _trusted_ancestors(git_dir, uid, stop=stop)
    for member in ("config", "HEAD", "index"):
        _trusted_file(git_dir / member, uid, mode=(0o400, 0o600, 0o644), stop=stop)
    _require(_git(source, ["rev-parse", "--show-toplevel"], runner) == str(source))
    _require(_git(source, ["rev-parse", "HEAD"], runner) == expected_commit)
    _require(_git(source, ["rev-parse", "HEAD^{tree}"], runner) == expected_tree)
    _require(_git(source, ["status", "--porcelain", "--untracked-files=all"], runner) == "")


def _engine(runner: Callable[..., bytes]) -> tuple[str, str]:
    projection = runner([DOCKER, "info", "--format", "{{.ID}}|{{.Name}}"], limit=512)
    value = projection.decode("utf-8").strip()
    _require(value.count("|") == 1 and "\n" not in value)
    engine_id, engine_name = value.split("|")
    _require(bool(engine_id and engine_name))
    return engine_id, engine_name


def _unique_json(raw: bytes) -> object:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result)
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique_pairs)


def _archive_config_id(path: Path, uid: int, stop: Path) -> str:
    _canonical(path)
    _trusted_ancestors(path.parent, uid, stop)
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_uid == uid and before.st_nlink == 1)
    descriptor = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _require((before.st_dev, before.st_ino) == (opened.st_dev, opened.st_ino))
        with tarfile.open(fileobj=stream, mode="r:") as archive:
            by_name: dict[str, tarfile.TarInfo] = {}
            total_size = 0
            for member in archive:
                _require(len(by_name) < 20000 and member.name not in by_name)
                _require(len(member.name) <= 256 and member.size <= 1_500_000_000)
                total_size += member.size
                _require(total_size <= 1_500_000_000)
                by_name[member.name] = member

            def bounded_member(name: str, limit: int) -> bytes:
                member = by_name.get(name)
                if member is None or not member.isfile() or not 0 < member.size <= limit:
                    raise RefusalError
                member_stream = archive.extractfile(member)
                if member_stream is None:
                    raise RefusalError
                content = member_stream.read(limit + 1)
                _require(len(content) == member.size)
                return content

            manifest = _unique_json(bounded_member("manifest.json", 1_048_576))
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise RefusalError
            if not isinstance(manifest[0], dict):
                raise RefusalError
            config_name = manifest[0].get("Config")
            if not isinstance(config_name, str):
                raise RefusalError
            _require(
                re.fullmatch(r"[0-9a-f]{64}\.json", config_name) is not None
                or re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", config_name) is not None
            )
            config_bytes = bounded_member(config_name, 16_777_216)
            config = _unique_json(config_bytes)
            if not isinstance(config, dict):
                raise RefusalError
            _require(config.get("os") == "linux" and config.get("architecture") == "amd64")
            image_id = "sha256:" + _sha(config_bytes)
            config_basename = config_name.rsplit("/", 1)[-1]
            if config_basename.endswith(".json"):
                config_basename = config_basename[:-5]
            _require(config_basename == image_id[7:])
        after_fd = os.fstat(stream.fileno())
    after = path.lstat()
    _require(
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
        == (
            after_fd.st_dev,
            after_fd.st_ino,
            after_fd.st_size,
            after_fd.st_mtime_ns,
            after_fd.st_ctime_ns,
        )
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    )
    return image_id


def _operator_artifacts(
    operator: dict[str, Any], old_commit: str, old_tree: str, uid: int, stop: Path
) -> tuple[Path, Path, Path, str]:
    artifacts = []
    for key in ("archive", "candidate", "metadata"):
        path = Path(operator["operator_" + key + "_path"])
        _canonical(path)
        _require(HEX64.fullmatch(operator["operator_" + key + "_sha256"]) is not None)
        _require(_trusted_hash(path, uid, stop=stop) == operator["operator_" + key + "_sha256"])
        artifacts.append(path)
    archive, candidate_path, metadata_path = artifacts
    _require(len(set(artifacts)) == 3)
    candidate = _literal_toml(_trusted_file(candidate_path, uid, stop=stop))
    _require(set(candidate) == CANDIDATE_KEYS)
    _require(candidate.get("schema") == "my-pa.nas-operator-runtime-candidate.v1")
    _require(candidate.get("status") == "candidate_not_admitted")
    _require(candidate.get("repository_commit") == old_commit)
    _require(candidate.get("repository_tree") == old_tree)
    _require(
        candidate.get("target_os") == "linux" and candidate.get("target_architecture") == "amd64"
    )
    _require(
        re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", candidate.get("built_at", "")) is not None
    )
    _require(candidate.get("docker_image_id") == operator.get("operator_image_id"))
    _require(candidate.get("oci_manifest_digest") == operator.get("operator_manifest_digest"))
    _require(candidate.get("archive_sha256") == operator.get("operator_archive_sha256"))
    _require(candidate.get("build_metadata_sha256") == operator.get("operator_metadata_sha256"))
    metadata = _unique_json(_trusted_file(metadata_path, uid, limit=1_048_576, stop=stop))
    if not isinstance(metadata, dict):
        raise RefusalError
    _require(metadata.get("containerimage.digest") == operator.get("operator_manifest_digest"))
    _require(metadata.get("containerimage.config.digest") == operator.get("operator_image_id"))
    _require(_archive_config_id(archive, uid, stop) == operator.get("operator_image_id"))
    return archive, candidate_path, metadata_path, candidate["built_at"]


def _operator_image(
    image_id: str, old_commit: str, old_tree: str, built_at: str, runner: Callable[..., bytes]
) -> None:
    projection = (
        "{{json .Id}}|{{json .Os}}|{{json .Architecture}}|"
        '{{json (index .Config.Labels "org.opencontainers.image.revision")}}|'
        '{{json (index .Config.Labels "org.opencontainers.image.created")}}|'
        '{{json (index .Config.Labels "io.my-pa.repository-tree")}}|'
        '{{json (index .Config.Labels "io.my-pa.operator-runtime")}}|'
        '{{json (index .Config.Labels "io.my-pa.target-platform")}}'
    )
    raw = runner([DOCKER, "image", "inspect", "--format", projection, image_id], limit=8192)
    parts = raw.decode("utf-8").strip().split("|")
    _require(len(parts) == 8)
    loaded, os_name, arch, commit, created, tree, runtime, platform = map(json.loads, parts)
    _require((loaded, os_name, arch) == (image_id, "linux", "amd64"))
    _require((commit, created, tree) == (old_commit, built_at, old_tree))
    _require((runtime, platform) == ("python-3.12", "linux/amd64"))


def _gate_volume(source: Path, destination: str, *, readonly: bool = True) -> str:
    _canonical(source)
    _require(
        destination.startswith("/run/my-pa-input/")
        or destination
        in {
            "/var/run/docker.sock",
            "/usr/local/bin/docker",
            "/usr/local/lib/docker/cli-plugins/docker-compose",
        }
    )
    return str(source) + ":" + destination + (":ro" if readonly else "")


def _baked_pre_source_gate(
    operator: dict[str, Any],
    old_source: Path,
    manifest: Path,
    admission: Path,
    archive: Path,
    candidate: Path,
    metadata: Path,
    runner: Callable[..., bytes],
) -> None:
    host = (admission, archive, candidate, metadata, old_source, manifest)
    _require(len(set(host)) == len(host))
    destinations = (
        "/run/my-pa-input/admission.toml",
        "/run/my-pa-input/operator.tar",
        "/run/my-pa-input/operator-candidate.toml",
        "/run/my-pa-input/operator-metadata.json",
        "/run/my-pa-input/current-source",
        "/run/my-pa-input/current-manifest.toml",
    )
    nonce = secure_random.token_hex(16)
    name = "my-pa-preflight-" + nonce
    command = [
        DOCKER,
        "create",
        "--name",
        name,
        "--label",
        "io.my-pa.preflight-nonce=" + nonce,
        "--label",
        "io.my-pa.preflight-kind=preserved-runtime-env",
        "--pull",
        "never",
        "--restart",
        "no",
        "--log-driver",
        "none",
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",  # noqa: S108 - container tmpfs
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "0:0",
        "--volume",
        _gate_volume(DOCKER_SOCKET, "/var/run/docker.sock", readonly=False),
        "--volume",
        _gate_volume(DOCKER_REAL, "/usr/local/bin/docker"),
        "--volume",
        _gate_volume(COMPOSE_REAL, "/usr/local/lib/docker/cli-plugins/docker-compose"),
    ]
    for index, source in enumerate(host):
        command.extend(("--volume", _gate_volume(source, destinations[index])))
    command.extend(
        (
            "--env",
            "MY_PA_NAS_DOCKER=/usr/local/bin/docker",
            "--env",
            "DOCKER_CLI_PLUGIN_EXTRA_DIRS=/usr/local/lib/docker/cli-plugins",
            "--entrypoint",
            "python",
            operator["operator_image_id"],
            "/usr/local/libexec/my-pa-operator-pre-source-gate.py",
            destinations[0],
            destinations[4],
            destinations[5],
            str(admission),
            str(old_source),
            str(manifest),
            str(archive),
            str(candidate),
            str(metadata),
            destinations[1],
            destinations[2],
            destinations[3],
        )
    )
    _gate_transaction(command, name, nonce, operator["operator_image_id"], runner)


def _gate_inspect(reference: str, runner: Callable[..., bytes]) -> dict[str, Any]:
    # Request only the transaction's allowlisted identity fields, never its
    # inherited environment or a full container inspection object.
    raw = runner(
        [DOCKER, "container", "inspect", "--format", GATE_INSPECT_FORMAT, reference],
        limit=16384,
    )
    values = json.loads(raw)
    _require(isinstance(values, list) and len(values) == len(GATE_INSPECT_FIELDS))
    return {name: values[index] for index, (name, _) in enumerate(GATE_INSPECT_FIELDS)}


def _gate_identity(
    data: dict[str, Any], cid: str, name: str, nonce: str, command: list[str]
) -> bool:
    """Authenticate the one container this invocation may start or remove."""
    try:
        expected_binds = [
            command[index + 1] for index, item in enumerate(command[:-1]) if item == "--volume"
        ]
        image_index = command.index("--entrypoint") + 2
        image = command[image_index]
        mounts = {(item["Source"], item["Destination"], item["RW"]) for item in data["Mounts"]}
        expected_mounts = {
            (source, destination, mode != "ro")
            for source, destination, *options in (bind.split(":") for bind in expected_binds)
            for mode in [options[0] if options else "rw"]
        }
        return (
            data["Id"] == cid
            and data["Name"] == "/" + name
            and data["Image"] == image
            and data["ConfigImage"] == image
            and data["Entrypoint"] == ["python"]
            and data["Cmd"] == command[image_index + 1 :]
            and data["Nonce"] == nonce
            and data["Kind"] == "preserved-runtime-env"
            and data["Binds"] == expected_binds
            and all(item["Type"] == "bind" for item in data["Mounts"])
            and len(data["Mounts"]) == len(expected_binds)
            and mounts == expected_mounts
            and data["NetworkMode"] == "none"
            and data["ReadonlyRootfs"] is True
            and data["Tmpfs"] == {"/tmp": "rw,nosuid,nodev,noexec,size=16m"}  # noqa: S108
            and data["CapDrop"] == ["ALL"]
            and data["SecurityOpt"] == ["no-new-privileges:true"]
            and data["Privileged"] is False
            and data["AutoRemove"] is False
            and data["Restart"] == "no"
            and data["LogType"] == "none"
            and data["User"] == "0:0"
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False


def _gate_absent(cid: str, name: str, runner: Callable[..., bytes]) -> bool:
    # Two independently filtered all-state listings rule out both a lingering CID
    # and a late create at the reserved name. Engine checks bracket the queries.
    for kind, value in (("id", cid), ("name", name)):
        raw = runner(
            [
                DOCKER,
                "ps",
                "-a",
                "--no-trunc",
                "--filter",
                kind + "=" + value,
                "--format",
                "{{.ID}}",
            ],
            limit=8192,
        )
        _require(raw == b"")
    return True


def _gate_transaction(
    command: list[str], name: str, nonce: str, image: str, runner: Callable[..., bytes]
) -> None:
    _require(re.fullmatch(r"[0-9a-f]{32}", nonce) is not None)
    _require(command[command.index("--entrypoint") + 2] == image)
    initial_engine = _engine(runner)
    cid: str | None = None
    created = False
    passed = False
    unresolved = False
    prior_handlers: dict[int, Any] = {}

    def interrupted(_signum: int, _frame: object) -> None:
        raise RefusalError

    try:
        for signum in (int(signal.SIGINT), int(signal.SIGTERM)):
            prior_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, interrupted)
        try:
            output = runner(command, limit=128)
            candidate = output.decode("ascii").strip()
            _require(re.fullmatch(r"[0-9a-f]{64}", candidate) is not None)
            cid = candidate
            created = True
        except Exception:
            # A timed-out create can have succeeded in the daemon. Name recovery
            # is cleanup-only; no ambiguous create may advance to start.
            try:
                _require(_engine(runner) == initial_engine)
                recovered = _gate_inspect(name, runner)
                recovered_candidate = recovered.get("Id")
                if (
                    isinstance(recovered_candidate, str)
                    and re.fullmatch(r"[0-9a-f]{64}", recovered_candidate)
                    and _gate_identity(recovered, recovered_candidate, name, nonce, command)
                ):
                    cid = recovered_candidate
                    created = True
            except Exception:  # A failed lookup cannot prove a timed-out create was absent.
                unresolved = True
            if not created:
                unresolved = True
            raise RefusalError from None

        _require(_engine(runner) == initial_engine)
        exact = _gate_inspect(cid, runner)
        named = _gate_inspect(name, runner)
        _require(_gate_identity(exact, cid, name, nonce, command))
        _require(_gate_identity(named, cid, name, nonce, command))
        _require(exact["Status"] == named["Status"] == "created")
        _require(exact["Running"] is named["Running"] is False)
        try:
            runner([DOCKER, "start", cid], discard=True)
            _require(_engine(runner) == initial_engine)
            wait = runner([DOCKER, "wait", cid], limit=32)
            _require(wait.strip() == b"0")
        except Exception as exc:
            raise RefusalError from exc
        passed = True
    finally:
        # A second interrupt during cleanup cannot defeat best-effort removal.
        for signum in prior_handlers:
            signal.signal(signum, signal.SIG_IGN)
        try:
            if cid is not None:
                clean = False
                for _attempt in range(3):
                    try:
                        _require(_engine(runner) == initial_engine)
                        current = _gate_inspect(cid, runner)
                        named = _gate_inspect(name, runner)
                        _require(_gate_identity(current, cid, name, nonce, command))
                        _require(_gate_identity(named, cid, name, nonce, command))
                        runner([DOCKER, "rm", "-f", cid], discard=True)
                    except Exception:  # Retry only after proving the same engine and identity.
                        clean = False
                    try:
                        _require(_engine(runner) == initial_engine)
                        clean = _gate_absent(cid, name, runner)
                        _require(_engine(runner) == initial_engine)
                        if clean:
                            break
                    except Exception:  # Daemon failure or presence leaves cleanup unproved.
                        clean = False
                unresolved = not clean
            if unresolved:
                print(
                    "Preserved runtime preflight unresolved container: "
                    + (cid if cid else "unknown")
                    + " name="
                    + name,
                    file=sys.stderr,
                )
                raise RefusalError
        finally:
            for signum, handler in prior_handlers.items():
                signal.signal(signum, handler)
    _require(passed)


def _ingress(
    data: dict[str, Any],
    engine_id: str,
    runner: Callable[..., bytes],
    old_source: Path,
    web_path: Path,
    service_image_ids: dict[str, str],
    uid: int,
    stop: Path,
) -> tuple[str, str]:
    expected_top = {
        "schema",
        "status",
        "docker_engine_id",
        "compose_project",
        "tailnet_hostname",
        "canonical_origin",
        "proxy_config_sha256",
        "loopback_target",
        "proxy_uid",
        "proxy_gid",
        "tailscale_version",
        "web_env_file",
        "web_env_owner_uid",
    }
    _require(set(data) == expected_top | {"services." + name for name in SERVICES})
    _require(data.get("schema") == "my-pa.nas-ingress-evidence.v2")
    _require(data.get("status") == "verified" and data.get("docker_engine_id") == engine_id)
    _require(data.get("compose_project") == "my-pa-nas-contract")
    proxy_config = old_source / "ops/nas/proxy-allowlist.example.caddy"
    _require(
        data.get("proxy_config_sha256")
        == _sha(
            _trusted_file(
                proxy_config,
                uid,
                mode=(0o400, 0o600, 0o644),
                stop=stop,
            )
        )
    )
    _require(data.get("web_env_file") == str(web_path))
    _require(type(data.get("web_env_owner_uid")) is int and data["web_env_owner_uid"] == uid)
    _require(
        all(type(data.get(key)) is int and data[key] > 0 for key in ("proxy_uid", "proxy_gid"))
    )
    _require(
        isinstance(data.get("tailscale_version"), str) and bool(data["tailscale_version"].strip())
    )
    for name in SERVICES:
        service_data = data["services." + name]
        _require(
            isinstance(service_data, dict) and set(service_data) == {"container_id", "image_id"}
        )
        _require(isinstance(service_data["container_id"], str))
        _require(re.fullmatch(r"[0-9a-f]{64}", service_data["container_id"]) is not None)
        _require(service_data["image_id"] == service_image_ids[name])
    host = data.get("tailnet_hostname")
    target = data.get("loopback_target")
    if not isinstance(host, str) or re.fullmatch(r"[a-z0-9.-]{3,253}", host) is None:
        raise RefusalError
    _require(data.get("canonical_origin") == "https://" + host)
    if not isinstance(target, str) or re.fullmatch(r"127\.0\.0\.1:[1-9][0-9]{0,4}", target) is None:
        raise RefusalError
    port = target.rsplit(":", 1)[1]
    _require(int(port) <= 65535)
    proxy = data.get("services.proxy", {})
    _require(isinstance(proxy, dict) and isinstance(proxy.get("container_id"), str))
    container_id = proxy["container_id"]
    _require(re.fullmatch(r"[0-9a-f]{64}", container_id) is not None)
    projection = (
        "{{json .Id}}|{{json .Image}}|{{json .State.Running}}|"
        '{{json (index .Config.Labels "com.docker.compose.project")}}|'
        '{{json (index .Config.Labels "com.docker.compose.service")}}|'
        "{{json .NetworkSettings.Ports}}|{{json .HostConfig.PortBindings}}"
    )
    raw = runner([DOCKER, "inspect", "--format", projection, container_id], limit=8192)
    parts = raw.decode("utf-8").strip().split("|")
    _require(len(parts) == 7)
    identity, image, running, project, service, bindings, host_bindings = map(json.loads, parts)
    _require(identity == container_id and running is True)
    _require(project == "my-pa-nas-contract" and service == "proxy")
    _require(image == proxy.get("image_id"))
    expected_binding = [{"HostIp": "127.0.0.1", "HostPort": port}]
    _require(isinstance(bindings, dict) and isinstance(host_bindings, dict))
    _require(bindings.get("8080/tcp") == expected_binding)
    _require(host_bindings.get("8080/tcp") == expected_binding)
    _require(all(value in (None, []) for key, value in bindings.items() if key != "8080/tcp"))
    _require(all(value in (None, []) for key, value in host_bindings.items() if key != "8080/tcp"))
    return host, port


def verify(
    new_source: Path,
    new_commit: str,
    new_tree: str,
    old_source: Path,
    *,
    uid: int = 0,
    runner: Callable[..., bytes] = _run,
    tool_check: Callable[..., None] = _trusted_executable,
    socket_check: Callable[..., None] = _trusted_socket,
    trust_stop: Path = Path("/"),
    manifest: Path = MANIFEST,
    operator_admission: Path = OPERATOR_ADMISSION,
    runtime_admission: Path = RUNTIME_ADMISSION,
    ingress_manifest: Path = INGRESS_MANIFEST,
    canonical_compose: Path = CANONICAL_COMPOSE,
    secrets: Path = SECRETS,
) -> None:
    _require(HEX40.fullmatch(new_commit) is not None and HEX40.fullmatch(new_tree) is not None)
    _canonical(new_source)
    _canonical(old_source)
    _require(new_source != old_source and old_source not in new_source.parents)
    tool_check(GIT, uid, trust_stop)
    tool_check(DOCKER, uid, trust_stop)
    tool_check(COMPOSE, uid, trust_stop)
    socket_check(DOCKER_SOCKET, uid, trust_stop)
    _source(new_source, new_commit, new_tree, uid, runner, trust_stop)
    manifest_bytes = _trusted_file(manifest, uid, stop=trust_stop)
    old_manifest = _literal_toml(manifest_bytes)
    old_commit, old_tree = (
        old_manifest.get("repository_commit"),
        old_manifest.get("repository_tree"),
    )
    _require(old_manifest.get("schema") == "my-pa.nas-image-manifest.v1")
    _require(
        old_manifest.get("status") == "deployable" and old_manifest.get("source_clean") is True
    )
    if not isinstance(old_commit, str) or HEX40.fullmatch(old_commit) is None:
        raise RefusalError
    if not isinstance(old_tree, str) or HEX40.fullmatch(old_tree) is None:
        raise RefusalError
    _require(
        old_manifest.get("target_os") == "linux"
        and old_manifest.get("target_architecture") == "amd64"
    )
    _source(old_source, old_commit, old_tree, uid, runner, trust_stop)
    old_compose = old_source / "ops/nas/compose.example.yml"
    compose_bytes = _trusted_file(
        old_compose, uid, mode=(0o400, 0o600, 0o644), limit=262144, stop=trust_stop
    )
    _require(_trusted_file(canonical_compose, uid, limit=262144, stop=trust_stop) == compose_bytes)
    status_script = old_source / "ops/nas/status.sh"
    _trusted_file(status_script, uid, mode=(0o500, 0o700, 0o755), stop=trust_stop)
    operator = _literal_toml(_trusted_file(operator_admission, uid, stop=trust_stop))
    _require(set(operator) == OPERATOR_KEYS)
    _require(operator.get("schema") == "my-pa.nas-operator-runtime-admission.v1")
    _require(operator.get("status") == "admitted")
    _require(
        operator.get("repository_commit") == old_commit
        and operator.get("repository_tree") == old_tree
    )
    _require(operator.get("repository_source_path") == str(old_source))
    _require(IMAGE_ID.fullmatch(operator.get("operator_image_id", "")) is not None)
    _require(IMAGE_ID.fullmatch(operator.get("operator_manifest_digest", "")) is not None)
    _require(re.fullmatch(r"3\.12\.[0-9]+", operator.get("python_version", "")) is not None)
    _require(
        re.fullmatch(r"git version [0-9][^\r\n]*", operator.get("git_version", "")) is not None
    )
    _require(
        re.fullmatch(r"OpenSSL [0-9][^\r\n]*", operator.get("openssl_version", "")) is not None
    )
    _require(
        re.fullmatch(
            r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", operator.get("compose_version", "")
        )
        is not None
    )
    archive, candidate, metadata, built_at = _operator_artifacts(
        operator,
        old_commit,
        old_tree,
        uid,
        trust_stop,
    )
    engine_id, engine_name = _engine(runner)
    _require(
        operator.get("docker_engine_id") == engine_id
        and operator.get("docker_engine_name") == engine_name
    )
    _require(
        old_manifest.get("docker_engine_id") == engine_id
        and old_manifest.get("docker_engine_name") == engine_name
    )
    _operator_image(operator["operator_image_id"], old_commit, old_tree, built_at, runner)
    runtime = _literal_toml(_trusted_file(runtime_admission, uid, stop=trust_stop))
    _require(
        runtime.get("schema") == "my-pa.nas-runtime-admission.v1"
        and runtime.get("status") == "admitted"
    )
    _require(runtime.get("image_manifest_sha256") == _sha(manifest_bytes))
    _require(
        runtime.get("docker_engine_id") == engine_id
        and runtime.get("docker_engine_name") == engine_name
    )
    _require(set(runtime.get("resolved_compose_sha256", {})) == {"smoke", "pilot"})
    _require(HEX64.fullmatch(runtime["resolved_compose_sha256"]["smoke"]) is not None)
    _require(
        set(runtime.get("service_images", {})) == SERVICES
        and set(runtime.get("service_image_ids", {})) == SERVICES
    )
    suffix = old_commit[:8]
    production_path = secrets / ("production." + suffix + ".env")
    nas_path = secrets / ("nas." + suffix + ".env")
    web_path = secrets / ("web." + suffix + ".env")
    ingress = _literal_toml(_trusted_file(ingress_manifest, uid, stop=trust_stop))
    host, port = _ingress(
        ingress,
        engine_id,
        runner,
        old_source,
        web_path,
        runtime["service_image_ids"],
        uid,
        trust_stop,
    )
    _baked_pre_source_gate(
        operator,
        old_source,
        manifest,
        operator_admission,
        archive,
        candidate,
        metadata,
        runner,
    )
    _trusted_directory(secrets, uid, stop=trust_stop)
    production = _literal_env(
        _trusted_file(production_path, uid, mode=(0o400, 0o600), stop=trust_stop), PRODUCTION_KEYS
    )
    _literal_env(_trusted_file(nas_path, uid, mode=(0o400, 0o600), stop=trust_stop))
    _literal_env(_trusted_file(web_path, uid, mode=(0o400, 0o600), stop=trust_stop))
    _require(
        production.get("MYPA_SOURCE_COMMIT") == old_commit
        and production.get("MYPA_SOURCE_TREE") == old_tree
    )
    _require(production.get("MY_PA_NAS_ENV_FILE") == str(nas_path))
    _require(production.get("MY_PA_WEB_ENV_FILE") == str(web_path))
    _require("MY_PA_PROXY_PORT" not in production and "MY_PA_TAILNET_HOST" not in production)
    _require(production.get("MY_PA_NAS_ROOT") == "/volume1/my-pa")
    _require(production.get("MY_PA_APP_IMAGE_ID") == runtime["service_image_ids"]["gateway"])
    _require(production.get("MY_PA_WEB_IMAGE_ID") == runtime["service_image_ids"]["web"])
    _require(production.get("MY_PA_POSTGRES_IMAGE_ID") == runtime["service_image_ids"]["postgres"])
    lifecycle = dict(production)
    lifecycle.update(
        {
            "MY_PA_NAS_DOCKER": DOCKER,
            "MY_PA_NAS_PYTHON": str(old_source / "ops/nas/container-python.sh"),
            "MY_PA_NAS_COMPOSE_FILE": str(old_compose),
            "MY_PA_IMAGE_MANIFEST": str(manifest),
            "MY_PA_LIFECYCLE_MODE": "smoke",
            "MY_PA_PROXY_PORT": port,
            "MY_PA_TAILNET_HOST": host,
        }
    )
    validator = old_source / "ops/nas/validate-production-env.py"
    schema = old_source / "ops/nas/production-environment.schema.toml"
    wrapper = old_source / "ops/nas/container-python.sh"
    _trusted_file(validator, uid, mode=(0o400, 0o600, 0o644, 0o500, 0o700, 0o755), stop=trust_stop)
    _trusted_file(schema, uid, mode=(0o400, 0o600, 0o644), stop=trust_stop)
    _trusted_file(wrapper, uid, mode=(0o500, 0o700, 0o755), stop=trust_stop)
    runner(
        [
            str(wrapper),
            str(validator),
            "--env",
            str(production_path),
            "--schema",
            str(schema),
            "--compose",
            str(old_compose),
        ],
        cwd=old_source,
        env=lifecycle,
        discard=True,
    )
    runner([str(status_script)], cwd=old_source, env=lifecycle, discard=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("Preserved runtime preflight refused", file=sys.stderr)
        return 1
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        _require(os.geteuid() == 0)
        script = Path(__file__)
        _canonical(script)
        new_source = script.parent.parent.parent
        _require(script == new_source / "ops/nas/preserved-runtime-env-preflight.py")
        verify(new_source, argv[0], argv[1], Path(argv[2]))
    except Exception:  # No protected values or paths may reach stderr.
        print("Preserved runtime preflight refused", file=sys.stderr)
        return 1
    print("Preserved runtime preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
