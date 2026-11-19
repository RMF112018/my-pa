"""Pending change records in an `approval` workspace's state directory (contract section 18).

`<state>/.my-pa/pending/<fwpnd id>.json` holds one live record (`pending` or
`applying`, 0600), written whole through a temporary file and `rename`; a
record that leaves them moves, never overwriting, to
`<state>/.my-pa/decided/<fwpnd id>.json`, so the live set stays bounded by the
pending cap; `<state>/.my-pa/decisions.jsonl` is the append-only decision
journal. Every access walks from the state root's
descriptor with `O_NOFOLLOW`, so a planted link is never followed. The state
directory is product-only: no `files.*` argument names it.

Not transactional with the database: the caller holds the per-workspace
advisory lock across a read and its transition, so the product's own
transitions serialize; a record is never deleted.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager, suppress
from datetime import datetime
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Any, Final

from my_pa.contracts.ports import (
    FilePendingChange,
    FilePendingChangeStore,
    FilePendingStatus,
    FileWorkspaceUnavailableError,
)
from my_pa.domain.files.transfer import PENDING_CHANGE_ID_PREFIX, parse_file_id

__all__ = ["FilesystemPendingChanges", "parse_pending_change_id"]

_CONTROL: Final = ".my-pa"
_PENDING: Final = "pending"
_DECIDED: Final = "decided"
_LIVE: Final = frozenset({FilePendingStatus.PENDING, FilePendingStatus.APPLYING})
_JOURNAL: Final = "decisions.jsonl"
_DIRECTORY_MODE: Final = 0o700
_FILE_MODE: Final = 0o600
_DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
#: A record is small (paths and opaque ids); anything larger is not ours.
_MAX_RECORD_BYTES: Final = 64 * 1024


def parse_pending_change_id(value: object) -> str | None:
    """`value` if it is a well-formed `fwpnd_` id, else `None`; never raises."""
    return parse_file_id(value, PENDING_CHANGE_ID_PREFIX)


def _encode(change: FilePendingChange) -> bytes:
    document = {
        "pending_change_id": change.pending_change_id,
        "workspace_id": change.workspace_id,
        "owner_principal_id": change.owner_principal_id,
        "client_ref": change.client_ref,
        "operation": change.operation,
        "arguments": dict(change.arguments),
        "size": change.size,
        "sha256": change.sha256,
        "staged_upload_id": change.staged_upload_id,
        "created_at": change.created_at.isoformat(),
        "expires_at": change.expires_at.isoformat(),
        "status": change.status.value,
        "decided_at": None if change.decided_at is None else change.decided_at.isoformat(),
        "result": None if change.result is None else dict(change.result),
        "reason": change.reason,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decode(data: bytes) -> FilePendingChange:
    document: dict[str, Any] = json.loads(data)
    decided = document["decided_at"]
    return FilePendingChange(
        pending_change_id=document["pending_change_id"],
        workspace_id=document["workspace_id"],
        owner_principal_id=document["owner_principal_id"],
        client_ref=document["client_ref"],
        operation=document["operation"],
        arguments=document["arguments"],
        size=document["size"],
        sha256=document["sha256"],
        staged_upload_id=document["staged_upload_id"],
        created_at=datetime.fromisoformat(document["created_at"]),
        expires_at=datetime.fromisoformat(document["expires_at"]),
        status=FilePendingStatus(document["status"]),
        decided_at=None if decided is None else datetime.fromisoformat(decided),
        result=document["result"],
        reason=document["reason"],
    )


class FilesystemPendingChanges(FilePendingChangeStore):
    """`FilePendingChangeStore` under one state directory (see the module docstring)."""

    def __init__(self, state_root: Path) -> None:
        candidate = Path(state_root)
        if not candidate.is_absolute():
            raise ValueError("the pending change state directory is not absolute")
        self._root: Final = candidate

    @contextmanager
    def _directory(self, *path: str, create: bool) -> Iterator[int | None]:
        """`<state>/<path...>` as a descriptor, created 0700 when `create`; `None` if absent."""
        with ExitStack() as stack:
            try:
                current = os.open(self._root, _DIRECTORY_FLAGS)
            except OSError:
                raise FileWorkspaceUnavailableError() from None
            stack.callback(os.close, current)
            for name in path:
                try:
                    status = os.stat(name, dir_fd=current, follow_symlinks=False)
                except FileNotFoundError:
                    if not create:
                        yield None
                        return
                    os.mkdir(name, _DIRECTORY_MODE, dir_fd=current)
                    status = os.stat(name, dir_fd=current, follow_symlinks=False)
                if not S_ISDIR(status.st_mode):
                    raise FileWorkspaceUnavailableError()
                nested = os.open(name, _DIRECTORY_FLAGS, dir_fd=current)
                stack.callback(os.close, nested)
                current = nested
            yield current

    @staticmethod
    def _name(pending_change_id: str) -> str:
        if parse_pending_change_id(pending_change_id) is None:
            raise ValueError("not a pending change id")
        return f"{pending_change_id}.json"

    @staticmethod
    def _write(directory: int, name: str, data: bytes, *, exclusive: bool) -> None:
        temporary = f".{name}.tmp"
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=directory)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            _FILE_MODE,
            dir_fd=directory,
        )
        try:
            view = memoryview(data)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if exclusive:
            # The first name only: an existing record is never overwritten.
            try:
                os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            finally:
                os.unlink(temporary, dir_fd=directory)
        else:
            os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)

    @staticmethod
    def _read(directory: int, name: str) -> FilePendingChange | None:
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except FileNotFoundError:
            return None
        except OSError:
            raise FileWorkspaceUnavailableError() from None
        try:
            status = os.fstat(descriptor)
            if not S_ISREG(status.st_mode) or status.st_size > _MAX_RECORD_BYTES:
                raise FileWorkspaceUnavailableError()
            data = os.read(descriptor, _MAX_RECORD_BYTES + 1)
        finally:
            os.close(descriptor)
        try:
            return _decode(data)
        except (ValueError, KeyError, TypeError):
            raise FileWorkspaceUnavailableError() from None

    def create(self, change: FilePendingChange) -> None:
        if change.status not in _LIVE:
            raise ValueError("a new pending change is live")
        name = self._name(change.pending_change_id)
        with self._directory(_CONTROL, _DECIDED, create=True) as decided:
            assert decided is not None  # noqa: S101 - created above
            if self._read(decided, name) is not None:
                raise FileExistsError("pending change id already decided")
        with self._directory(_CONTROL, _PENDING, create=True) as directory:
            assert directory is not None  # noqa: S101 - created above
            self._write(directory, name, _encode(change), exclusive=True)

    def get(self, pending_change_id: str) -> FilePendingChange | None:
        if parse_pending_change_id(pending_change_id) is None:
            return None
        name = self._name(pending_change_id)
        for child in (_PENDING, _DECIDED):
            with self._directory(_CONTROL, child, create=False) as directory:
                if directory is None:
                    continue
                found = self._read(directory, name)
                if found is not None:
                    return found
        return None

    def replace(self, change: FilePendingChange) -> None:
        name = self._name(change.pending_change_id)
        with self._directory(_CONTROL, _PENDING, create=False) as directory:
            if directory is None or self._read(directory, name) is None:
                # Only a live record moves; a decided one is final.
                raise FileWorkspaceUnavailableError()
            if change.status in _LIVE:
                self._write(directory, name, _encode(change), exclusive=False)
                return
            with self._directory(_CONTROL, _DECIDED, create=True) as decided:
                assert decided is not None  # noqa: S101 - created above
                self._write(decided, name, _encode(change), exclusive=True)
            os.unlink(name, dir_fd=directory)
            os.fsync(directory)

    def list_changes(self, *, limit: int) -> list[FilePendingChange]:
        with self._directory(_CONTROL, _PENDING, create=False) as directory:
            if directory is None:
                return []
            changes = [
                change
                for change in (
                    self._read(directory, name)
                    for name in sorted(os.listdir(directory))  # noqa: PTH208 - a descriptor
                    if name.endswith(".json")
                    and parse_pending_change_id(name.removesuffix(".json")) is not None
                )
                if change is not None
            ]
        changes.sort(key=lambda change: (change.created_at, change.pending_change_id), reverse=True)
        return changes[:limit]

    def record_decision(self, entry: Mapping[str, object]) -> None:
        line = json.dumps(dict(entry), sort_keys=True, separators=(",", ":")) + "\n"
        with self._directory(_CONTROL, create=True) as directory:
            assert directory is not None  # noqa: S101 - created above
            descriptor = os.open(
                _JOURNAL,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
                _FILE_MODE,
                dir_fd=directory,
            )
            try:
                os.write(descriptor, line.encode("utf-8"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
