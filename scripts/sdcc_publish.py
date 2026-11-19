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
import subprocess
import sys
import zipfile
from collections import Counter
from collections.abc import Mapping
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


def capture_git(source: Path, spec: Mapping[str, Any], repository: Path) -> None:
    """Archive a reconstructable committed diff under the session output tree.

    This is read-only against the Git repository. The generated patch and
    identity report become ordinary session artifacts and are secret-scanned.
    """
    git = spec.get("github", {})
    if not isinstance(git, dict) or not git.get("repo"):
        raise PublicationError("github_identity_required")

    def command(*args: str) -> bytes:
        executable = shutil.which("git")
        if executable is None:
            raise PublicationError("git_snapshot_failed")
        try:
            # All arguments are controlled; shell=False. S603 is a false positive.
            result = subprocess.run(
                [executable, *args],
                cwd=repository,
                capture_output=True,
                check=True,
                timeout=30,
            )  # noqa: S603
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            raise PublicationError("git_snapshot_failed") from None
        return result.stdout.strip() if args[0] == "rev-parse" else result.stdout

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
    report = _json({"repository": git["repo"], "base_sha": base,
                    "head_sha": head, "tree_sha": tree}).encode("utf-8")
    target = source / "_git"
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise PublicationError("git_snapshot_existing_conflict")
    target.mkdir(exist_ok=True)
    for name, data in (("changes.patch", diff), ("changed-paths.txt", changed),
                       ("IDENTITY.json", report)):
        output = target / name
        if output.exists():
            if output.is_symlink() or output.read_bytes() != data:
                raise PublicationError("git_snapshot_existing_conflict")
        else:
            with output.open("xb") as handle:
                handle.write(data)


def _spec(spec_path: Path) -> dict[str, Any]:
    try:
        obj = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise PublicationError("invalid_session_spec") from None
    if not isinstance(obj, dict):
        raise PublicationError("invalid_session_spec")
    for key in (
        "session_id", "work_item_id", "program", "workstream", "source_client", "publisher_client"
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
        if name in ("SESSION_MANIFEST.json", "SESSION_PUBLICATION_RECEIPT.json"):
            raise PublicationError("reserved_artifact_name")
        size, sha = _hash_file(path)
        # Keys, local environment and token stores are not transferable artifacts.
        private_name = path.name.lower().startswith(".env") or path.suffix.lower() in (
            ".pem", ".key", ".p12", ".pfx"
        )
        try:
            secret = private_name or _contains_obvious_secret(path)
        except PublicationError:
            secret = True
        found.append(Artifact(name, path, size, None if secret else sha,
                              "PROTECTED_WITHHELD" if secret else statuses.get(name, "FINAL"),
                              "suspected_secret_or_unscannable_archive" if secret else None))
        if len(found) > MAX_FILES:
            raise PublicationError("too_many_artifacts")
    if not found:
        raise PublicationError("no_artifacts")
    unknown = set(statuses) - {a.relative for a in found}
    if unknown:
        raise PublicationError("status_names_missing_artifact")
    return found, [{"category": k, "count": v, "rule": "TRANSIENT_EXCLUSION_POLICY_v3"}
                   for k, v in sorted(exclusions.items())]


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
        result = await api.call("files.stat", {"workspace_id": WORKSPACE_ID,
                                               "path": path, "include_sha256": True})
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
    ):
        raise PublicationError("artifact_missing_or_mismatched")
    # Prevent successful publication of a local file changed during transfer.
    size, digest = _hash_file(item.local)
    if size != item.size or digest != item.sha256:
        raise PublicationError("source_changed_during_publication")
    return stored


def _session_path(spec: Mapping[str, Any]) -> str:
    return "/".join((SESSION_ROOT, _id(spec["program"]), "workstreams", _id(spec["workstream"]),
                     "work-items", _id(spec["work_item_id"]), "sessions", _id(spec["session_id"])))


async def publish(api: FilesAPI, source: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Publish all discoverable artifacts. Never claim READY on partial failure."""
    statuses = spec.get("artifact_statuses", {})
    artifacts, exclusions = inventory(source, statuses)
    session_root = _session_path(spec)
    await _mkdir(api, session_root)
    entries: list[dict[str, Any]] = []
    incomplete = False
    for item in artifacts:
        remote = f"{session_root}/artifacts/{item.relative}"
        entry: dict[str, Any] = {
            "artifact_id": f"{spec['session_id']}:{item.relative}", "relative_path": item.relative,
            "status": item.status, "size_bytes": item.size,
            "representation": mimetypes.guess_type(item.relative)[0] or "application/octet-stream",
            "hash_scope": "stored_raw_bytes",
            "sha256": item.sha256, "path": remote if item.sha256 else None,
            "version": None, "origin_ref": None,
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
        "schema_version": SCHEMA, "session_id": spec["session_id"],
        "work_item_id": spec["work_item_id"], "execution_lane": spec.get("execution_lane", "R"),
        "source_client": spec["source_client"], "publisher_client": spec["publisher_client"],
        "publication_epoch": None,
        "my_pa": {"workspace_id": WORKSPACE_ID, "session_path": session_root},
        "github": spec.get("github", {}), "artifacts": entries,
        "transient_exclusions": exclusions,
        "outstanding_findings": spec.get("outstanding_findings", []),
        "publication_status": status, "next_action": spec.get("next_action", ""),
        "canonical_authority_activated": False,
    }
    manifest_path = f"{session_root}/SESSION_MANIFEST.json"
    manifest_stat = await _write_text(api, manifest_path, _json(manifest))
    registry_path = (f"{REGISTRY_ROOT}/{spec['session_date'][:4]}/{spec['session_date'][5:7]}/"
                     f"{spec['session_id']}.json")
    registry = {"work_item_id": spec["work_item_id"], "session_id": spec["session_id"],
                "manifest_path": manifest_path, "manifest_version": manifest_stat["version"],
                "manifest_sha256": manifest_stat["sha256"], "status": status}
    await _mkdir(api, registry_path.rsplit("/", 1)[0])
    await _write_text(api, registry_path, _json(registry))
    receipt_path = f"{session_root}/SESSION_PUBLICATION_RECEIPT.json"
    receipt = {"schema_version": RECEIPT_SCHEMA, "session_id": spec["session_id"],
               "manifest_path": manifest_path, "manifest_version": manifest_stat["version"],
               "manifest_sha256": manifest_stat["sha256"], "registry_path": registry_path,
               "observed_artifact_count": len(entries), "verified_count": sum(
                   e.get("version") is not None for e in entries),
               "disposition": status, "cutover": "NOT_ACTIVE"}
    receipt_stat = await _write_text(api, receipt_path, _json(receipt))
    return {"status": status, "manifest_path": manifest_path,
            "manifest_version": manifest_stat["version"], "receipt_path": receipt_path,
            "receipt_version": receipt_stat["version"], "registry_path": registry_path,
            "verified": receipt["verified_count"], "total": len(entries),
            "handoff": (
                f"Work {spec['work_item_id']}; MY-PA mcp:{manifest_path}@"
                f"{manifest_stat['version']}; {status}; next: {spec.get('next_action', '')}"
            )}


class RemoteFilesAPI:
    """MCP facade adapter; uses existing my_pa.read/write and byte routes."""

    def __init__(self, mcp_client: object, endpoint: str) -> None:
        self.client = mcp_client
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
        self.origin = f"{parsed.scheme}://{parsed.netloc}"

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
        ticket = await self.call("files.upload.begin", {"workspace_id": WORKSPACE_ID,
            "path": destination, "size": size, "sha256": sha256}, write=True)
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
    if args.repo_dir is not None:
        capture_git(args.source_dir, spec, args.repo_dir)
    endpoint = args.endpoint
    token = os.environ.get("SDCR_MYPA_TOKEN", "")
    if not token:
        raise PublicationError("missing_authenticated_client_token")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.path not in ("/mcp", "/mcp/")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise PublicationError("invalid_endpoint")
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
            result = await publish(RemoteFilesAPI(client, endpoint), args.source_dir, spec)
    except PublicationError:
        raise
    except Exception:
        raise PublicationError("my_pa_connection_failed") from None
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
