#!/usr/bin/env python3
"""Run the inert NAS-10 matrix and write synthetic evidence, never activation."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import selectors as io_selectors
import signal
import stat
import subprocess
import sys
import time
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

MAX_CASE_OUTPUT_BYTES = 10 * 1024 * 1024
MAX_CASE_SECONDS = 300
TRUSTED_PATH = "/usr/bin:/bin"


def _case_environment(database_url: str | None = None) -> dict[str, str]:
    environment = {"PATH": TRUSTED_PATH, "PYTHONPATH": "src", "LANG": "C.UTF-8"}
    if database_url is not None:
        environment["MY_PA_DATABASE_URL"] = database_url
    return environment


def _local_case_allowed(requirement: str) -> bool:
    return requirement != "external_device"


def _redact_chunk(
    pending: bytes, chunk: bytes, secrets: tuple[bytes, ...], *, final: bool = False
) -> tuple[bytes, bytes]:
    secrets = tuple(secret for secret in secrets if secret)
    combined = pending + chunk
    if not secrets:
        return combined, b""
    longest = max(map(len, secrets))
    safe_limit = len(combined) if final else max(0, len(combined) - longest + 1)
    output = bytearray()
    index = 0
    while index < safe_limit:
        matched = next((secret for secret in secrets if combined.startswith(secret, index)), None)
        if matched is not None:
            output.extend(b"[REDACTED_DATABASE_URL]")
            index += len(matched)
        else:
            output.append(combined[index])
            index += 1
    return bytes(output), combined[index:]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_root(path: Path, owner_uid: int) -> None:
    parent = path.parent
    metadata = parent.lstat()
    if not (
        path.is_absolute()
        and path.name not in {"", ".", ".."}
        and path == parent / path.name
        and parent.resolve(strict=True) == parent
        and stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid == owner_uid
        and stat.S_IMODE(metadata.st_mode) == 0o700
    ):
        raise OSError("unsafe evidence parent")
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    created = path.lstat()
    if not (
        stat.S_ISDIR(created.st_mode)
        and created.st_uid == owner_uid
        and stat.S_IMODE(created.st_mode) == 0o700
        and path.resolve(strict=True) == path
    ):
        raise OSError("unsafe evidence root")


def _open_artifact(root: Path, name: str) -> int:
    if Path(name).name != name or name in {"", ".", ".."}:
        raise OSError("unsafe artifact name")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    return os.open(root / name, flags, 0o400)


def _finish_artifact(descriptor: int, owner_uid: int) -> None:
    os.fsync(descriptor)
    metadata = os.fstat(descriptor)
    if not (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == owner_uid
        and stat.S_IMODE(metadata.st_mode) == 0o400
        and metadata.st_nlink == 1
    ):
        raise OSError("unsafe artifact metadata")
    os.close(descriptor)


def _write_artifact(root: Path, name: str, data: bytes, owner_uid: int) -> str:
    descriptor = _open_artifact(root, name)
    digest = hashlib.sha256()
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            digest.update(view[:written])
            view = view[written:]
        _finish_artifact(descriptor, owner_uid)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise
    return digest.hexdigest()


def _stream_case(
    command: list[str],
    root: Path,
    log_name: str,
    *,
    cwd: Path,
    env: dict[str, str],
    owner_uid: int,
    limit: int = MAX_CASE_OUTPUT_BYTES,
    timeout_seconds: float = MAX_CASE_SECONDS,
    redactions: tuple[bytes, ...] = (),
) -> tuple[int, str, bool]:
    descriptor = _open_artifact(root, log_name)
    digest = hashlib.sha256()
    refused = False
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(  # noqa: S603 - canonical matrix builds this command
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if process.stdout is None:
            raise OSError("case output pipe unavailable")
        total = 0
        pending = b""
        deadline = time.monotonic() + timeout_seconds
        selector = io_selectors.DefaultSelector()
        selector.register(process.stdout, io_selectors.EVENT_READ)
        eof = False
        while not eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                refused = True
                break
            events = selector.select(min(remaining, 0.25))
            for _key, _mask in events:
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    chunk, pending = _redact_chunk(pending, b"", redactions, final=True)
                    if chunk:
                        if total + len(chunk) > limit:
                            chunk = chunk[: max(0, limit - total)]
                            refused = True
                        if chunk:
                            os.write(descriptor, chunk)
                            digest.update(chunk)
                            total += len(chunk)
                    eof = True
                    break
                chunk, pending = _redact_chunk(pending, chunk, redactions)
                if total + len(chunk) > limit:
                    chunk = chunk[: max(0, limit - total)]
                    refused = True
                if chunk:
                    os.write(descriptor, chunk)
                    digest.update(chunk)
                    total += len(chunk)
                if refused:
                    break
            if refused:
                break
        if not refused:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                refused = True
        if refused:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGTERM)
            # The case leader may already have exited while a descendant still
            # owns the pipe. Always follow TERM with KILL for the whole session;
            # waiting only for the leader cannot prove that descendants stopped.
            grace_deadline = time.monotonic() + 2
            while process.poll() is None and time.monotonic() < grace_deadline:
                time.sleep(0.05)
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=2)
        returncode = process.wait()
        if refused and returncode == 0:
            returncode = 124
        _finish_artifact(descriptor, owner_uid)
        return returncode, digest.hexdigest(), refused
    except BaseException:
        if process is not None and process.poll() is None:
            with contextlib.suppress(OSError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("matrix", type=Path)
    parser.add_argument("image_manifest", type=Path)
    parser.add_argument("runtime_admission", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not Path(sys.executable).is_absolute():
        print("NAS-10 runner refused: absolute Python interpreter required")
        return 1
    repository = Path(__file__).resolve().parents[2]
    matrix_path = args.matrix.resolve()
    if matrix_path != repository / "ops/nas/acceptance-matrix.toml":
        print("NAS-10 runner refused: canonical matrix required")
        return 1
    matrix = tomllib.loads(matrix_path.read_text(encoding="utf-8"))
    cases = matrix.get("cases", {})
    if matrix.get("status") != "synthetic_only" or not isinstance(cases, dict):
        print("NAS-10 runner refused: inert matrix required")
        return 1
    try:
        image = tomllib.loads(args.image_manifest.read_text())
        admission = tomllib.loads(args.runtime_admission.read_text())
        head = subprocess.run(  # noqa: S603 - fixed Git identity inspection
            ["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tree = subprocess.run(  # noqa: S603 - fixed Git identity inspection
            ["/usr/bin/git", "-C", str(repository), "rev-parse", "HEAD^{tree}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603 - fixed Git identity inspection
            ["/usr/bin/git", "-C", str(repository), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        pilot_digest = admission["resolved_compose_sha256"]["pilot"]
    except (OSError, KeyError, subprocess.SubprocessError, tomllib.TOMLDecodeError):
        print("NAS-10 runner refused: identity inputs unreadable")
        return 1
    if (
        dirty
        or image.get("repository_commit") != head
        or image.get("repository_tree") != tree
        or admission.get("image_manifest_sha256") != _sha(args.image_manifest)
        or admission.get("docker_engine_id") != image.get("docker_engine_id")
        or admission.get("docker_engine_name") != image.get("docker_engine_name")
    ):
        print("NAS-10 runner refused: exact clean identity required")
        return 1
    try:
        _create_root(args.output, os.geteuid())
    except OSError:
        print("NAS-10 runner refused: unsafe or existing evidence root")
        return 1
    result_digests: dict[str, str] = {}
    for name, case in cases.items():
        if (
            not isinstance(case, dict)
            or set(case) != {"requirement", "behaviors", "selectors"}
            or not isinstance(case.get("selectors"), list)
            or not isinstance(case.get("behaviors"), list)
            or not case["behaviors"]
        ):
            return 1
        selectors = case["selectors"]
        requirement = str(case["requirement"])
        if not _local_case_allowed(requirement):
            print(f"NAS-10 runner refused: {name} requires canonical external-device receipt")
            return 1
        if not selectors:
            return 1
        command = ["python3", "-m", "pytest", "--import-mode=importlib", "-q", *map(str, selectors)]
        environment = _case_environment()
        if requirement == "disposable_postgres":
            database_url = os.environ.get("MY_PA_NAS10_SYNTHETIC_DATABASE_URL", "")
            parsed_database = urlsplit(database_url)
            if (
                not parsed_database.scheme.startswith("postgresql")
                or parsed_database.hostname not in {"127.0.0.1", "localhost", "::1"}
                or os.environ.get("MY_PA_NAS10_DISPOSABLE_DATABASE_ACK") != "YES"
            ):
                print(f"NAS-10 runner refused: {name} requires disposable PostgreSQL")
                return 1
            environment = _case_environment(database_url)
        returncode, output_digest, exceeded = _stream_case(
            [sys.executable, *command[1:]],
            args.output,
            f"{name}.log",
            cwd=repository,
            env=environment,
            owner_uid=os.geteuid(),
            redactions=(database_url.encode(),) if requirement == "disposable_postgres" else (),
        )
        if exceeded:
            print(f"NAS-10 runner refused: {name} output exceeds bound")
            return 1
        receipt = {
            "schema": "my-pa.nas-10-case-result.v1",
            "case": name,
            "status": "pass" if returncode == 0 else "fail",
            "synthetic": True,
            "activation_performed": False,
            "repository_commit": head,
            "repository_tree": tree,
            "nas_engine_id": image["docker_engine_id"],
            "nas_engine_name": image["docker_engine_name"],
            "command": command,
            "requirement": requirement,
            "behaviors": case["behaviors"],
            "external_device_verified": False,
            "output_sha256": output_digest,
        }
        receipt_bytes = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
        result_digests[name] = _write_artifact(
            args.output, f"{name}.json", receipt_bytes, os.geteuid()
        )
        if returncode:
            return 1
    manifest = {
        "schema": "my-pa.nas-10-evidence.v1",
        "status": "complete",
        "synthetic": True,
        "activation_performed": False,
        "repository_commit": head,
        "repository_tree": tree,
        "nas_engine_id": image["docker_engine_id"],
        "nas_engine_name": image["docker_engine_name"],
        "matrix_sha256": _sha(matrix_path),
        "image_manifest_sha256": _sha(args.image_manifest),
        "runtime_admission_sha256": _sha(args.runtime_admission),
        "resolved_compose_sha256": pilot_digest,
        "results": result_digests,
    }
    _write_artifact(
        args.output,
        "evidence.json",
        (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        os.geteuid(),
    )
    directory = os.open(args.output, os.O_RDONLY)
    os.fsync(directory)
    os.close(directory)
    print(args.output / "evidence.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
