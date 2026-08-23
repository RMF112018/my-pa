"""Authorized PNG raster staging for GSQS ChatLLM remote-eval sessions.

Copies caller-supplied synthetic rasters into an isolated session spool. It
rejects symlinks and path traversal and never writes private gold or
managed-document bytes. Source filesystem paths are not placed on the returned
manifest.
"""

from __future__ import annotations

import os
import secrets
from hashlib import sha256
from pathlib import Path

from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_STATE_INTEGRITY_FAILURE,
    ManifestCase,
    RemoteEvalError,
    RemoteEvalSession,
    SessionManifest,
    StagingSealResult,
)
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    atomic_write_bytes,
    fsync_directory,
    mkdir_private,
    reject_symlink,
    resolve_under_root,
    session_directory,
)
from my_pa.domain.goodnotes.page_crop import PNG_MAGIC, grayscale_from_png

__all__ = ["FilesystemRasterStaging"]


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read_regular_file(path: Path) -> bytes:
    reject_symlink(path, what="raster file")
    if not path.is_file():
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster file is missing")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_filename(name: str) -> str:
    if not name or "\x00" in name or "/" in name or "\\" in name or ".." in name:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged_filename is invalid")
    if name != Path(name).name or name.startswith("."):
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged_filename is invalid")
    if not name.lower().endswith(".png"):
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged_filename is not a PNG")
    return name


def _validate_case_id(case_id: str) -> str:
    if not case_id or "\x00" in case_id or "/" in case_id or "\\" in case_id or ".." in case_id:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "case_id is invalid")
    return case_id


def _validate_manifest(manifest: SessionManifest) -> tuple[ManifestCase, ...]:
    cases = manifest.cases
    if len(cases) != CASES_PER_REPETITION:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "manifest must contain 73 cases")
    seen: set[str] = set()
    for index, case in enumerate(cases, start=1):
        if case.ordinal != index:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "case ordinals must be 1..73")
        _validate_case_id(case.case_id)
        if case.case_id in seen:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "duplicate case_id")
        _validate_filename(case.staged_filename)
        if case.byte_length < 1:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "byte_length is invalid")
        seen.add(case.case_id)
    names = [case.staged_filename for case in cases]
    if len(set(names)) != len(names):
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "duplicate staged_filename")
    return cases


def _validate_png(payload: bytes) -> None:
    if not payload.startswith(PNG_MAGIC):
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster is not a PNG")
    try:
        grayscale_from_png(payload)
    except ValueError as exc:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "PNG structure is invalid") from exc


def _rmtree_private(path: Path) -> None:
    reject_symlink(path, what="staging temp")
    if not path.exists():
        return
    for child in path.iterdir():
        reject_symlink(child, what="staging temp")
        if child.is_dir():
            _rmtree_private(child)
        else:
            child.unlink()
    path.rmdir()


class FilesystemRasterStaging:
    """Copy-not-symlink staging of an authorized local raster set."""

    def __init__(self, state_root: Path, source_root: Path) -> None:
        self._state_root = Path(state_root)
        self._source_root = Path(source_root)

    def seal_authorized_rasters(
        self,
        session: RemoteEvalSession,
        manifest: SessionManifest,
    ) -> StagingSealResult:
        if session.session_id != manifest.session_id:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "session identity mismatch")
        reject_symlink(self._state_root, what="state_root")
        reject_symlink(self._source_root, what="source_root")
        if not self._source_root.is_dir():
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "source_root is missing")
        session_dir = session_directory(self._state_root, session.session_id)
        if not session_dir.is_dir():
            raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "session directory missing")
        reject_symlink(session_dir, what="session directory")
        rasters_dir = session_dir / "rasters"
        if rasters_dir.exists():
            raise RemoteEvalError(
                ERROR_RASTER_INTEGRITY_FAILURE,
                "rasters directory already exists",
            )
        cases = _validate_manifest(manifest)
        source_root = self._source_root.resolve()
        source_files = {
            path.name: path for path in source_root.iterdir() if path.is_file() or path.is_symlink()
        }
        expected_names = {case.staged_filename for case in cases}
        extra = set(source_files) - expected_names
        missing = expected_names - set(source_files)
        if extra:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "extra raster in source set")
        if missing:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster is missing")
        tmp_dir = session_dir / f".rasters-tmp-{secrets.token_hex(8)}"
        try:
            mkdir_private(tmp_dir)
            dest_index: dict[str, tuple[str, int, str]] = {}
            for case in cases:
                source_path = source_files[case.staged_filename]
                reject_symlink(source_path, what="source raster")
                resolved_source = resolve_under_root(source_root, source_path)
                payload = _read_regular_file(resolved_source)
                if len(payload) != case.byte_length:
                    raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "byte_length mismatch")
                digest = _sha256_bytes(payload)
                if digest != case.content_sha256:
                    raise RemoteEvalError(
                        ERROR_RASTER_INTEGRITY_FAILURE,
                        "content SHA-256 mismatch",
                    )
                _validate_png(payload)
                dest_path = tmp_dir / case.staged_filename
                reject_symlink(dest_path, what="destination raster")
                atomic_write_bytes(dest_path, payload)
                written = _read_regular_file(dest_path)
                dest_digest = _sha256_bytes(written)
                if dest_digest != case.content_sha256 or len(written) != case.byte_length:
                    raise RemoteEvalError(
                        ERROR_RASTER_INTEGRITY_FAILURE,
                        "destination SHA-256 mismatch",
                    )
                dest_index[case.case_id] = (
                    dest_digest,
                    len(written),
                    case.staged_filename,
                )
            dest_names = {
                path.name for path in tmp_dir.iterdir() if path.is_file() or path.is_symlink()
            }
            if dest_names != expected_names:
                raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "destination set mismatch")
            for case in cases:
                digest, length, filename = dest_index[case.case_id]
                if (
                    digest != case.content_sha256
                    or length != case.byte_length
                    or filename != case.staged_filename
                ):
                    raise RemoteEvalError(
                        ERROR_RASTER_INTEGRITY_FAILURE,
                        "destination set does not match manifest",
                    )
            fsync_directory(tmp_dir)
            tmp_dir.replace(rasters_dir)
            reject_symlink(rasters_dir, what="rasters directory")
            fsync_directory(session_dir)
        except Exception:
            if tmp_dir.exists():
                _rmtree_private(tmp_dir)
            if rasters_dir.is_symlink():
                raise RemoteEvalError(
                    ERROR_STATE_INTEGRITY_FAILURE, "rasters directory is a symlink"
                ) from None
            raise
        return StagingSealResult(ok=True, manifest=manifest)
