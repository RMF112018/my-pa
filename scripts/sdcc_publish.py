#!/usr/bin/env python3
"""SDCR session artifact publisher over the existing MY-PA Files contract.

Standalone, no new service or server-side API. Requires an already-authorized
MY-PA OAuth token for live use. No credentials, deployment or grants are changed.

Usage (in a qualified client environment):
  SDCR_MYPA_TOKEN=... python scripts/sdcc_publish.py \
      --endpoint https://<mcp-host>/mcp --source-dir ./outputs --spec ./session.json

The source directory is inventoried in full. The optional spec maps artifacts to
statuses and gives the stable work/session identities; it does not silently
exclude files. A terminal receipt is emitted only after artifact, manifest and
registry-pointer verification. A failing/withheld artifact is NOT ready.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import mimetypes
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol
from urllib.parse import urlsplit

WORKSPACE_ID = "mcp"
SESSION_ROOT = "SDCR/20-Programs"
REGISTRY_ROOT = "SDCR/40-Publication/sessions"
SCHEMA = "sdcr.session.v2"
RECEIPT_SCHEMA = "sdcr.session.receipt.v1"
RECOVERY_SCHEMA = "sdcr.session.recovery.v1"
MAX_FILES = 10_000
TEXT_LIMIT = 122_880
CHUNK_SIZE = 1024 * 1024
_STATUSES = frozenset({"FINAL", "DRAFT", "FAILED_EVIDENCE", "SUPERSEDED", "SOURCE"})
_TRANSIENT_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
_TRANSIENT_SUFFIXES = (".pyc", ".pyo")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9_]{28,}\b"),
    re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{35,}\b"),
    re.compile(rb"\bsk-[A-Za-z0-9]{32,}\b"),
)


class PublicationError(Exception):
    """Error code safe to report without exposing payloads or credentials."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class FilesAPI(Protocol):
    async def call(
        self, capability: str, payload: Mapping[str, object], *, write: bool = False
    ) -> dict[str, Any]: ...

    async def upload(
        self, local: Path, destination: str, sha256: str, size: int
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Artifact:
    relative: str
    local: Path
    size: int
    sha256: str | None
    status: str
    reason: str | None = None


def _id(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value) or value in (".", ".."):
        raise PublicationError("invalid_identity")
    return value


def _relative_path(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw or any(ord(ch) < 32 for ch in raw):
        raise PublicationError("invalid_artifact_path")
    posix = PurePosixPath(raw)
    if posix.is_absolute() or any(p in ("", ".", "..", ".my-pa") for p in raw.split("/")):
        raise PublicationError("invalid_artifact_path")
    return posix.as_posix()


def _json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while block := handle.read(CHUNK_SIZE):
            h.update(block)
            total += len(block)
    return total, h.hexdigest()


def _contains_obvious_secret(path: Path) -> bool:
    """Conservative fast scanner. NOT a complete DLP or binary-content audit."""

    def scan(handle: BinaryIO) -> bool:
        prefix = b""
        while block := handle.read(CHUNK_SIZE):
            content = prefix + block
            if any(pattern.search(content) for pattern in _SECRET_PATTERNS):
                return True
            prefix = content[-512:]
        return False

    with path.open("rb") as handle:
        if scan(handle):
            return True
    if zipfile.is_zipfile(path):
        try:
            with zipfile.ZipFile(path) as archive:
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    if entry.file_size > 256 * 1024 * 1024 or entry.flag_bits & 1:
                        raise PublicationError("unscannable_archive")
                    with archive.open(entry) as handle:
                        if scan(handle):
                            return True
        except (OSError, zipfile.BadZipFile, RuntimeError):
            raise PublicationError("unscannable_archive") from None
    return False


def _walk_output_directory(source: Path) -> tuple[int, Path]:
    """Open each output ancestor without following symlinks."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise PublicationError("unsupported_output_platform")
    if ".." in source.parts:
        raise PublicationError("invalid_source_directory")
    # Preserve lexical components: Path.resolve() would follow a forbidden symlink.
    root = Path(os.path.abspath(source))  # noqa: PTH100
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = -1
    try:
        fd = os.open("/", flags)
        for part in root.parts[1:]:
            next_fd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd, root
    except OSError:
        if fd >= 0:
            os.close(fd)
        raise PublicationError("invalid_source_directory") from None


def _bound_output_root(root: Path, fd: int) -> None:
    """Reject replacement of an admitted output root or ancestor."""
    try:
        check, _ = _walk_output_directory(root)
    except PublicationError:
        raise PublicationError("output_root_changed") from None
    try:
        old, current = os.fstat(fd), os.fstat(check)
        if (old.st_dev, old.st_ino) != (current.st_dev, current.st_ino):
            raise PublicationError("output_root_changed")
    finally:
        os.close(check)


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _refuse_protected_output(output_root: Path, protected_roots: Sequence[Path]) -> None:
    for entry in protected_roots:
        try:
            protected = entry.resolve(strict=True)
        except OSError:
            raise PublicationError("invalid_protected_root") from None
        if _overlap(output_root, protected):
            raise PublicationError("protected_output_root")


def _read_git_artifact(fd: int, name: str, expected: bytes) -> bool:
    """Return False for absent; reject symlinks, special files and conflicts."""
    try:
        opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        return False
    except OSError:
        raise PublicationError("git_snapshot_existing_conflict") from None
    with os.fdopen(opened, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PublicationError("git_snapshot_existing_conflict")
        if handle.read(len(expected) + 1) != expected:
            raise PublicationError("git_snapshot_existing_conflict")
    return True


def _bound_git_directory(root_fd: int, git_fd: int) -> None:
    try:
        check = os.open("_git", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except OSError:
        raise PublicationError("git_snapshot_root_changed") from None
    try:
        old, current = os.fstat(git_fd), os.fstat(check)
        if (old.st_dev, old.st_ino) != (current.st_dev, current.st_ino):
            raise PublicationError("git_snapshot_root_changed")
    finally:
        os.close(check)


def _write_git_artifact(git_fd: int, name: str, content: bytes) -> None:
    if _read_git_artifact(git_fd, name, content):
        return
    try:
        opened = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=git_fd,
        )
        with os.fdopen(opened, "wb") as handle:
            handle.write(content)
    except OSError:
        raise PublicationError("git_snapshot_existing_conflict") from None


def capture_git(
    source: Path,
    spec: Mapping[str, Any],
    repository: Path,
    protected_roots: Sequence[Path] = (),
    expected_root_fd: int | None = None,
) -> None:
    """Capture Git evidence only in a safe, caller-qualified session output tree.

    Descriptor-relative no-follow writes pin the original directory identity.
    Unknown non-Git source roots still require upstream client qualification.
    """
    git = spec.get("github", {})
    if not isinstance(git, dict) or not git.get("repo"):
        raise PublicationError("github_identity_required")

    def command(*args: str) -> bytes:
        executable = shutil.which("git")
        if executable is None:
            raise PublicationError("git_snapshot_failed")
        try:
            result = subprocess.run(  # noqa: S603 - controlled Git argv, no shell
                [executable, *args],
                cwd=repository,
                capture_output=True,
                check=True,
                timeout=30,
            )
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise PublicationError("git_snapshot_failed") from None
        return result.stdout.strip() if args[0] == "rev-parse" else result.stdout

    try:
        worktree = Path(command("rev-parse", "--show-toplevel").decode()).resolve(strict=True)
        gitdir = Path(command("rev-parse", "--absolute-git-dir").decode()).resolve(strict=True)
        common_raw = Path(command("rev-parse", "--git-common-dir").decode())
        common_dir = (repository / common_raw).resolve(strict=True)
    except (OSError, ValueError, UnicodeError, RuntimeError):
        raise PublicationError("git_snapshot_failed") from None

    output_fd, output_root = _walk_output_directory(source)
    try:
        _bound_output_root(output_root, output_fd)
        if expected_root_fd is not None:
            expected = os.fstat(expected_root_fd)
            current = os.fstat(output_fd)
            if (expected.st_dev, expected.st_ino) != (current.st_dev, current.st_ino):
                raise PublicationError("output_root_changed")
        if any(_overlap(output_root, root) for root in (worktree, gitdir, common_dir)):
            raise PublicationError("output_overlaps_repository")
        _refuse_protected_output(output_root, protected_roots)

        head = command("rev-parse", "HEAD").decode("ascii")
        tree = command("rev-parse", "HEAD^{tree}").decode("ascii")
        if head != git.get("head_sha") or tree != git.get("tree_sha"):
            raise PublicationError("github_head_identity_mismatch")
        base = str(git.get("base_sha", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise PublicationError("invalid_github_identity")
        command("merge-base", "--is-ancestor", base, head)
        if command("status", "--porcelain"):
            raise PublicationError("dirty_repository_refused")
        diff = command("diff", "--binary", "--no-ext-diff", base, head)
        changed = command("diff", "--name-status", "--no-ext-diff", base, head)
        report = _json(
            {"repository": git["repo"], "base_sha": base, "head_sha": head, "tree_sha": tree}
        ).encode("utf-8")
        files = (
            ("changes.patch", diff),
            ("changed-paths.txt", changed),
            ("IDENTITY.json", report),
        )
        _bound_output_root(output_root, output_fd)
        try:
            git_fd = os.open("_git", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=output_fd)
        except FileNotFoundError:
            _bound_output_root(output_root, output_fd)
            try:
                os.mkdir("_git", mode=0o700, dir_fd=output_fd)
                git_fd = os.open(
                    "_git", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=output_fd
                )
            except OSError:
                raise PublicationError("git_snapshot_existing_conflict") from None
        except OSError:
            raise PublicationError("git_snapshot_existing_conflict") from None
        try:
            _bound_git_directory(output_fd, git_fd)
            # Refuse any existing conflicting file before creating new files.
            for name, content in files:
                _read_git_artifact(git_fd, name, content)
            for name, content in files:
                _bound_output_root(output_root, output_fd)
                _bound_git_directory(output_fd, git_fd)
                _write_git_artifact(git_fd, name, content)
            _bound_output_root(output_root, output_fd)
            _bound_git_directory(output_fd, git_fd)
        finally:
            os.close(git_fd)
    finally:
        os.close(output_fd)


def _spec(spec_path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise PublicationError("invalid_session_spec") from None
    if not isinstance(obj, dict):
        raise PublicationError("invalid_session_spec")
    for key in (
        "session_id",
        "work_item_id",
        "program",
        "workstream",
        "source_client",
        "publisher_client",
    ):
        _id(obj.get(key))
    try:
        if not isinstance(obj.get("session_date"), str) or len(obj["session_date"]) != 10:
            raise ValueError
        date.fromisoformat(obj["session_date"])
    except ValueError:
        raise PublicationError("invalid_session_date") from None
    if obj.get("execution_lane", "R") not in ("R", "C", "N", "H"):
        raise PublicationError("invalid_execution_lane")
    statuses = obj.get("artifact_statuses", {})
    if not isinstance(statuses, dict):
        raise PublicationError("invalid_artifact_statuses")
    for name, status in statuses.items():
        _relative_path(name)
        if status not in _STATUSES:
            raise PublicationError("invalid_artifact_statuses")
    git = obj.get("github", {})
    if not isinstance(git, dict):
        raise PublicationError("invalid_github_identity")
    if git.get("repo"):
        for field in ("base_sha", "head_sha", "tree_sha"):
            if (
                not isinstance(git.get(field), str)
                or len(git[field]) != 40
                or not re.fullmatch(r"[0-9a-f]{40}", git[field])
            ):
                raise PublicationError("invalid_github_identity")
    return obj


def inventory(
    source: Path, statuses: Mapping[str, str]
) -> tuple[list[Artifact], list[dict[str, Any]]]:
    if not source.is_dir() or source.is_symlink():
        raise PublicationError("invalid_source_directory")
    found: list[Artifact] = []
    exclusions: Counter[str] = Counter()
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        if path.is_symlink():
            raise PublicationError("symlink_refused")
        if path.is_dir():
            continue
        if any(part in _TRANSIENT_DIRS for part in rel.parts) or path.suffix in _TRANSIENT_SUFFIXES:
            exclusions["tool_cache"] += 1
            continue
        if not path.is_file():
            raise PublicationError("nonregular_file_refused")
        name = _relative_path(rel.as_posix())
        if name in (
            "SESSION_MANIFEST.json",
            "SESSION_PUBLICATION_RECEIPT.json",
            "SESSION_RECOVERY.json",
            "SESSION_PUBLICATION_FAILURE.json",
        ):
            raise PublicationError("reserved_artifact_name")
        size, sha = _hash_file(path)
        # Keys, local environment and token stores are not transferable artifacts.
        private_name = path.name.lower().startswith(".env") or path.suffix.lower() in (
            ".pem",
            ".key",
            ".p12",
            ".pfx",
        )
        try:
            secret = private_name or _contains_obvious_secret(path)
        except PublicationError:
            secret = True
        found.append(
            Artifact(
                name,
                path,
                size,
                None if secret else sha,
                "PROTECTED_WITHHELD" if secret else statuses.get(name, "FINAL"),
                "suspected_secret_or_unscannable_archive" if secret else None,
            )
        )
        if len(found) > MAX_FILES:
            raise PublicationError("too_many_artifacts")
    if not found:
        raise PublicationError("no_artifacts")
    unknown = set(statuses) - {a.relative for a in found}
    if unknown:
        raise PublicationError("status_names_missing_artifact")
    return found, [
        {"category": k, "count": v, "rule": "TRANSIENT_EXCLUSION_POLICY_v3"}
        for k, v in sorted(exclusions.items())
    ]


async def _call(
    api: FilesAPI, name: str, args: dict[str, object], *, write: bool = False
) -> dict[str, Any]:
    try:
        result = await api.call(name, {"workspace_id": WORKSPACE_ID, **args}, write=write)
    except Exception:
        raise PublicationError("my_pa_operation_failed") from None
    if not isinstance(result, dict):
        raise PublicationError("my_pa_invalid_response")
    return result


async def _stat(api: FilesAPI, path: str) -> dict[str, Any] | None:
    try:
        result = await api.call(
            "files.stat", {"workspace_id": WORKSPACE_ID, "path": path, "include_sha256": True}
        )
    except Exception as exc:
        if getattr(exc, "code", None) == "not_found":
            return None
        raise PublicationError("my_pa_stat_unavailable") from None
    if not isinstance(result, dict):
        raise PublicationError("my_pa_invalid_response")
    return result


async def _mkdir(api: FilesAPI, directory: str) -> None:
    result = await _stat(api, directory)
    if result is not None:
        if result.get("kind") != "directory":
            raise PublicationError("destination_is_not_directory")
        return
    try:
        await _call(api, "files.mkdir", {"path": directory, "parents": True}, write=True)
    except PublicationError:
        if (check := await _stat(api, directory)) is None or check.get("kind") != "directory":
            raise


async def _write_text(api: FilesAPI, path: str, text: str) -> dict[str, Any]:
    encoded = text.encode("utf-8")
    if len(encoded) > TEXT_LIMIT:
        raise PublicationError("metadata_exceeds_text_limit")
    expected = _sha_bytes(encoded)
    previous = await _stat(api, path)
    if previous is None:
        # A lost response is acceptable only if the subsequent readback agrees.
        with suppress(PublicationError):
            await _call(api, "files.write_text", {"path": path, "text": text}, write=True)
    current = await _stat(api, path)
    if (
        current is None
        or current.get("kind") != "file"
        or current.get("sha256") != expected
        or current.get("size") != len(encoded)
        or not isinstance(current.get("version"), str)
        or not current["version"]
    ):
        raise PublicationError("metadata_publication_conflict")
    return current


async def _upload_one(api: FilesAPI, item: Artifact, target: str) -> dict[str, Any]:
    if item.sha256 is None:
        raise PublicationError("withheld_artifact_not_uploadable")
    current = await _stat(api, target)
    if current is None:
        # A lost response can still indicate success; verify actual stored bytes.
        with suppress(Exception):
            await api.upload(item.local, target, item.sha256, item.size)
    stored = await _stat(api, target)
    if (
        stored is None
        or stored.get("kind") != "file"
        or stored.get("size") != item.size
        or stored.get("sha256") != item.sha256
        or not isinstance(stored.get("version"), str)
        or not stored["version"]
    ):
        raise PublicationError("artifact_missing_or_mismatched")
    # Prevent successful publication of a local file changed during transfer.
    size, digest = _hash_file(item.local)
    if size != item.size or digest != item.sha256:
        raise PublicationError("source_changed_during_publication")
    return stored


def _session_path(spec: Mapping[str, Any]) -> str:
    return "/".join(
        (
            SESSION_ROOT,
            _id(spec["program"]),
            "workstreams",
            _id(spec["workstream"]),
            "work-items",
            _id(spec["work_item_id"]),
            "sessions",
            _id(spec["session_id"]),
        )
    )


async def _write_metadata(api: FilesAPI, path: str, text: str) -> dict[str, Any]:
    """Use inline UTF-8 only within the real MCP limit; ticket larger metadata."""
    encoded = text.encode("utf-8")
    if len(encoded) <= TEXT_LIMIT:
        return await _write_text(api, path, text)
    # Never stage these bytes inside the supplied output tree: inventory must
    # remain stable, including on an interrupted or replayed publication.
    with tempfile.TemporaryDirectory(prefix="sdcr-metadata-") as temporary:
        local = Path(temporary) / "manifest.json"
        local.write_bytes(encoded)
        return await _upload_one(
            api,
            Artifact("SESSION_MANIFEST.json", local, len(encoded), _sha_bytes(encoded), "SOURCE"),
            path,
        )


def _inventory_sha256(artifacts: list[Artifact], exclusions: list[dict[str, Any]]) -> str:
    """Bind a NOT_READY recovery record without disclosing withheld hashes."""
    digest = hashlib.sha256()
    for item in artifacts:
        digest.update(
            _json(
                {
                    "relative_path": item.relative,
                    "size_bytes": item.size,
                    "sha256": item.sha256,
                    "status": item.status,
                    "reason": item.reason,
                }
            ).encode("utf-8")
        )
    digest.update(_json({"transient_exclusions": exclusions}).encode("utf-8"))
    return digest.hexdigest()


async def _begin_recovery(
    api: FilesAPI,
    spec: Mapping[str, Any],
    artifacts: list[Artifact],
    exclusions: list[dict[str, Any]],
    session_root: str,
) -> tuple[str, str, dict[str, Any]]:
    """Publish a verifiable, immutable recovery locator before any artifact transfer.

    The dated locator is separate from the final manifest index: both are
    create-only and a locator never claims successful handoff.
    """
    recovery_path = f"{session_root}/SESSION_RECOVERY.json"
    receipt_path = f"{session_root}/SESSION_PUBLICATION_RECEIPT.json"
    recovery = {
        "schema_version": RECOVERY_SCHEMA,
        "session_id": spec["session_id"],
        "work_item_id": spec["work_item_id"],
        "session_date": spec["session_date"],
        "publication_status": "NOT_READY",
        "artifact_count": len(artifacts),
        "inventory_sha256": _inventory_sha256(artifacts, exclusions),
        "spec_sha256": _sha_bytes(_json(dict(spec)).encode("utf-8")),
        "manifest_path": f"{session_root}/SESSION_MANIFEST.json",
        "terminal_receipt_path": receipt_path,
    }
    recovery_stat = await _write_text(api, recovery_path, _json(recovery))
    locator_path = (
        f"{REGISTRY_ROOT}/{spec['session_date'][:4]}/{spec['session_date'][5:7]}/"
        f"{spec['session_id']}.recovery.json"
    )
    await _mkdir(api, locator_path.rsplit("/", 1)[0])
    locator = {
        "schema_version": "sdcr.session.recovery.locator.v1",
        "session_id": spec["session_id"],
        "work_item_id": spec["work_item_id"],
        "status": "NOT_READY",
        "recovery_path": recovery_path,
        "recovery_version": recovery_stat["version"],
        "recovery_sha256": recovery_stat["sha256"],
    }
    locator_stat = await _write_text(api, locator_path, _json(locator))
    return recovery_path, locator_path, locator_stat


async def publish(api: FilesAPI, source: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Publish discoverable artifacts; only the verified terminal receipt can be READY."""
    statuses = spec.get("artifact_statuses", {})
    artifacts, exclusions = inventory(source, statuses)
    session_root = _session_path(spec)
    await _mkdir(api, session_root)
    # Neither an artifact byte nor a partial manifest is published until both
    # recovery record and dated discovery pointer are confirmed by SHA and version.
    recovery_path, locator_path, locator_stat = await _begin_recovery(
        api, spec, artifacts, exclusions, session_root
    )
    manifest_path = f"{session_root}/SESSION_MANIFEST.json"
    receipt_path = f"{session_root}/SESSION_PUBLICATION_RECEIPT.json"
    entries: list[dict[str, Any]] = []
    incomplete = False
    try:
        for item in artifacts:
            remote = f"{session_root}/artifacts/{item.relative}"
            representation = mimetypes.guess_type(item.relative)[0] or "application/octet-stream"
            entry: dict[str, Any] = {
                "artifact_id": f"{spec['session_id']}:{item.relative}",
                "relative_path": item.relative,
                "status": item.status,
                "size_bytes": item.size,
                "representation": representation,
                "hash_scope": "stored_raw_bytes",
                "sha256": item.sha256,
                "path": remote if item.sha256 else None,
                "version": None,
                "origin_ref": None,
            }
            if item.reason:
                incomplete = True
                entry["reason"] = item.reason
            else:
                parent = remote.rsplit("/", 1)[0]
                try:
                    await _mkdir(api, parent)
                    stored = await _upload_one(api, item, remote)
                    entry["version"] = stored["version"]
                except PublicationError as exc:
                    incomplete = True
                    entry["status"] = "FAILED_EVIDENCE"
                    entry["reason"] = exc.code
            entries.append(entry)
        status = "PUBLICATION_INCOMPLETE" if incomplete else "READY_FOR_HANDOFF"
        manifest: dict[str, Any] = {
            "schema_version": SCHEMA,
            "session_id": spec["session_id"],
            "work_item_id": spec["work_item_id"],
            "execution_lane": spec.get("execution_lane", "R"),
            "source_client": spec["source_client"],
            "publisher_client": spec["publisher_client"],
            "publication_epoch": None,
            "my_pa": {"workspace_id": WORKSPACE_ID, "session_path": session_root},
            "github": spec.get("github", {}),
            "artifacts": entries,
            "transient_exclusions": exclusions,
            "outstanding_findings": spec.get("outstanding_findings", []),
            "publication_status": status,
            "next_action": spec.get("next_action", ""),
            "canonical_authority_activated": False,
        }
        manifest_stat = await _write_metadata(api, manifest_path, _json(manifest))
        registry_path = (
            f"{REGISTRY_ROOT}/{spec['session_date'][:4]}/{spec['session_date'][5:7]}/"
            f"{spec['session_id']}.json"
        )
        # The registry is only a verified locator. Until the terminal receipt
        # exists, an observer must not infer READY from this earlier file.
        registry = {
            "work_item_id": spec["work_item_id"],
            "session_id": spec["session_id"],
            "manifest_path": manifest_path,
            "manifest_version": manifest_stat["version"],
            "manifest_sha256": manifest_stat["sha256"],
            "terminal_receipt_path": receipt_path,
            "recovery_locator_path": locator_path,
            "status": "AWAITING_TERMINAL_RECEIPT",
        }
        registry_stat = await _write_text(api, registry_path, _json(registry))
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "session_id": spec["session_id"],
            "manifest_path": manifest_path,
            "manifest_version": manifest_stat["version"],
            "manifest_sha256": manifest_stat["sha256"],
            "registry_path": registry_path,
            "registry_version": registry_stat["version"],
            "registry_sha256": registry_stat["sha256"],
            "recovery_path": recovery_path,
            "recovery_locator_path": locator_path,
            "recovery_locator_version": locator_stat["version"],
            "recovery_locator_sha256": locator_stat["sha256"],
            "observed_artifact_count": len(entries),
            "verified_count": sum(e.get("version") is not None for e in entries),
            "disposition": status,
            "cutover": "NOT_ACTIVE",
        }
        receipt_stat = await _write_text(api, receipt_path, _json(receipt))
    except PublicationError as exc:
        # Best effort: keep the first failure immutable. The durable NOT_READY
        # recovery record and locator already exist even if this write fails.
        with suppress(Exception):
            await _write_text(
                api,
                f"{session_root}/SESSION_PUBLICATION_FAILURE.json",
                _json(
                    {
                        "schema_version": "sdcr.session.failure.v1",
                        "session_id": spec["session_id"],
                        "status": "PUBLICATION_INCOMPLETE",
                        "reason_code": exc.code,
                        "recovery_locator_path": locator_path,
                    }
                ),
            )
        raise
    return {
        "status": status,
        "manifest_path": manifest_path,
        "manifest_version": manifest_stat["version"],
        "receipt_path": receipt_path,
        "receipt_version": receipt_stat["version"],
        "registry_path": registry_path,
        "recovery_path": recovery_path,
        "recovery_locator_path": locator_path,
        "recovery_locator_version": locator_stat["version"],
        "verified": receipt["verified_count"],
        "total": len(entries),
        "handoff": (
            f"Work {spec['work_item_id']}; MY-PA mcp:{manifest_path}@"
            f"{manifest_stat['version']}; {status}; next: {spec.get('next_action', '')}"
        ),
    }


def _endpoint_origin(endpoint: str) -> str:
    try:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("/mcp", "/mcp/")
        ):
            raise PublicationError("invalid_endpoint")
        _ = parsed.port  # Reject invalid ports before any Git capture.
    except (ValueError, TypeError):
        raise PublicationError("invalid_endpoint") from None
    return f"{parsed.scheme}://{parsed.netloc}"


def _require_local_token() -> str:
    token = os.environ.get("SDCR_MYPA_TOKEN", "")
    if not token:
        raise PublicationError("missing_authenticated_client_token")
    if (
        not token.isascii()
        or not 16 <= len(token) <= 8192
        or any(ord(char) < 33 or ord(char) > 126 for char in token)
    ):
        raise PublicationError("malformed_authenticated_client_token")
    return token


async def _remote_write_preflight(api: FilesAPI) -> None:
    """Probe available workspace write mode before any Git artifact is created."""
    try:
        response = await api.call("files.workspaces.list", {})
    except Exception:
        raise PublicationError("workspace_preflight_unavailable") from None
    spaces = response.get("workspaces") if isinstance(response, dict) else None
    if not isinstance(spaces, list) or not any(
        isinstance(entry, dict)
        and entry.get("workspace_id") == WORKSPACE_ID
        and entry.get("writable") is True
        and entry.get("write_mode") == "direct"
        for entry in spaces
    ):
        raise PublicationError("workspace_not_writable")


class RemoteFilesAPI:
    """MCP facade adapter; uses existing my_pa.read/write and byte routes."""

    def __init__(self, mcp_client: object, endpoint: str) -> None:
        self.client = mcp_client
        self.origin = _endpoint_origin(endpoint)

    async def call(
        self, capability: str, payload: Mapping[str, object], *, write: bool = False
    ) -> dict[str, Any]:
        name = "my_pa.write" if write else "my_pa.read"
        try:
            result = await self.client.call_tool(
                name, {"capability": capability, "arguments": {"payload": dict(payload)}}
            )
            data = result.structured_content
            if not isinstance(data, dict):
                texts = [getattr(x, "text", None) for x in result.content]
                data = json.loads(next((v for v in texts if isinstance(v, str)), "{}"))
            if isinstance(data, dict):
                if data.get("error") or result.is_error:
                    err = data.get("error")
                    code = err.get("code") if isinstance(err, dict) else data.get("code")
                    if code in ("not_found", "conflict", "denied", "unavailable", "unsupported"):
                        raise PublicationError(code)
                    raise PublicationError("my_pa_tool_refused")
                if isinstance(data.get("result"), dict):
                    return data["result"]
        except PublicationError:
            raise
        except Exception as exc:
            # Server refusals may surface as MCP JSON-RPC exceptions instead
            # of CallToolResult(is_error=True); retain only safe error codes.
            info = getattr(exc, "data", None)
            code = info.get("code") if isinstance(info, dict) else getattr(exc, "code", None)
            if code in ("not_found", "conflict", "denied", "unavailable", "unsupported"):
                raise PublicationError(code) from None
            if re.search(r"(?:\bnot_found\b|\bversion_conflict\b)", str(exc)):
                raise PublicationError(
                    "not_found" if "not_found" in str(exc) else "conflict"
                ) from None
            raise PublicationError("my_pa_transport_error") from None
        raise PublicationError("my_pa_invalid_response")

    async def upload(self, local: Path, destination: str, sha256: str, size: int) -> dict[str, Any]:
        ticket = await self.call(
            "files.upload.begin",
            {"workspace_id": WORKSPACE_ID, "path": destination, "size": size, "sha256": sha256},
            write=True,
        )
        route, token = ticket.get("route"), ticket.get("upload_token")
        if not isinstance(route, str) or not isinstance(token, str):
            raise PublicationError("my_pa_missing_transfer_ticket")
        try:
            from scripts.my_pa_files import UPLOADS_PREFIX, Target, upload
        except ImportError:
            from my_pa_files import UPLOADS_PREFIX, Target, upload  # type: ignore[no-redef]
        try:
            result = await asyncio.to_thread(
                upload, local, Target(self.origin, route, UPLOADS_PREFIX, 60.0), token
            )
        except Exception:
            raise PublicationError("my_pa_binary_transfer_failed") from None
        if not isinstance(result, dict):
            raise PublicationError("my_pa_binary_transfer_invalid_result")
        return result


async def _main(args: argparse.Namespace) -> int:
    spec = _spec(args.spec)
    endpoint = args.endpoint
    _endpoint_origin(endpoint)
    token = _require_local_token()
    # Local validation and SDK availability precede all Git snapshot writes.
    output_fd, output_root = _walk_output_directory(args.source_dir)
    try:
        _bound_output_root(output_root, output_fd)
        _refuse_protected_output(output_root, args.protected_root)
        try:
            import httpx2
            from mcp.client import Client
            from mcp.client.streamable_http import streamable_http_client
        except ImportError:
            raise PublicationError("missing_mcp_sdk") from None
        try:
            async with (
                httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=httpx2.Timeout(30.0, read=300.0),
                ) as http,
                Client(streamable_http_client(endpoint, http_client=http), mode="legacy") as client,
            ):
                # Non-mutating connection and write-mode probes precede local capture.
                api = RemoteFilesAPI(client, endpoint)
                await _remote_write_preflight(api)
                _bound_output_root(output_root, output_fd)
                if args.repo_dir is not None:
                    capture_git(
                        args.source_dir,
                        spec,
                        args.repo_dir,
                        args.protected_root,
                        expected_root_fd=output_fd,
                    )
                _bound_output_root(output_root, output_fd)
                result = await publish(api, args.source_dir, spec)
        except PublicationError:
            raise
        except Exception:
            raise PublicationError("my_pa_connection_failed") from None
    finally:
        os.close(output_fd)
    print(_json(result), end="")
    return 0 if result["status"] == "READY_FOR_HANDOFF" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish complete SDCR session artifacts into MY-PA."
    )
    parser.add_argument(
        "--endpoint", required=True, help="Authorized HTTPS remote MCP /mcp endpoint"
    )
    parser.add_argument(
        "--source-dir", required=True, type=Path, help="Directory containing all session outputs"
    )
    parser.add_argument(
        "--spec", required=True, type=Path, help="Nonsecret session identity/status JSON"
    )
    parser.add_argument(
        "--repo-dir", type=Path, help="Read-only Git diff capture from this repository"
    )
    parser.add_argument(
        "--protected-root",
        action="append",
        type=Path,
        default=[],
        help="Known source/managed-data root forbidden as output ancestor or descendant",
    )
    args = parser.parse_args(argv)
    try:
        return asyncio.run(_main(args))
    except PublicationError as exc:
        print(
            _json({"status": "PUBLICATION_INCOMPLETE", "error_code": exc.code}),
            end="",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
