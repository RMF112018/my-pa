"""Transfer staging on the report content root's filesystem (Reports Modernization WP06 T13).

A transfer session's chunks wait here between append and consumption:

    <root>/transfer/<shard>/<grxfr id>/<sequence, 2 digits>-<chunk sha256, 64 hex>

`transfer` is the constant `ReportContentNamespace.TRANSFER.value` (there is
**no namespace parameter**), `<shard>` the first two characters of the id's
suffix, and only lowercase `grxfr_` identifiers are admitted -- checked
before anything is opened -- so no argument can name the `content` or
`preservation` trees beside it, which `FilesystemReportContentStore` owns (and
which refuses to be constructed on `transfer`).

**Writing** is `filesystem._write_part`'s discipline: a temporary
`.<name>.tmp` created `O_CREAT | O_EXCL | O_NOFOLLOW` 0600 in the anchored
session directory, written, `fsync`ed, re-opened and re-hashed, published
with `linkat` (which never replaces) and unlinked; the session directory and
its shard are `fsync`ed. The chunk's digest is in its name, so a retry with
other bytes can never collide with a stored chunk; an identical file already
there (a crashed attempt whose response was lost) is verified and accepted,
and a leftover temporary of the same name is removed before the new one is
created.

**Discard** is the only removal anywhere in the report content root, and it
is confined: it walks root -> `transfer` -> shard -> session directory, every
step `openat(O_DIRECTORY | O_NOFOLLOW)` against the descriptor above, lists
that ONE directory, and unlinks only entries whose name is a chunk name (or
its temporary) and that are regular files with exactly one link, then
`rmdir`s the session directory (which fails, leaving it, if anything else is
inside). It never recurses, never follows a link (unlinking a name removes
that name, never what a link would point at), and never takes a path.
Whatever it leaves is reported by `unreadable_entries`.

Backups and the content/preservation scans walk their own namespace only and
never see this tree; staging is transient and is not backed up.

No message here carries a path, an identifier or a value.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterable, Iterator
from contextlib import suppress
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Final

from my_pa.contracts.ports import (
    ReportContentNamespace,
    ReportTransferStaging,
    ReportTransferStagingError,
)
from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    parse_identifier,
    validate_identifier,
)
from my_pa.domain.reports.transfer import MAX_TRANSFER_CHUNKS, TRANSFER_CHUNK_BYTES
from my_pa.infrastructure.report_content_stores._anchoring import (
    ANCHORING_IS_AVAILABLE,
    CREATE_FLAGS,
    DIRECTORY_FLAGS,
    READ_FLAGS,
    ReportContentRootError,
    close,
    resolve_clear_root,
)

__all__ = [
    "CHUNK_FILE_PATTERN",
    "FilesystemReportTransferStaging",
    "chunk_file_name",
]

#: The constant directory component: never a parameter.
_TRANSFER: Final = ReportContentNamespace.TRANSFER.value
_SHARD: Final = 2
_READ_SLICE: Final = 1 << 20

#: A published chunk file's name: two sequence digits, `-`, the chunk's SHA-256.
CHUNK_FILE_PATTERN: Final = r"^[0-9]{2}-[0-9a-f]{64}$"
_CHUNK_FILE: Final = re.compile(r"\A([0-9]{2})-[0-9a-f]{64}\Z")
_TEMPORARY_FILE: Final = re.compile(r"\A\.([0-9]{2})-[0-9a-f]{64}\.tmp\Z")
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")


def _refuse(message: str) -> ReportTransferStagingError:
    return ReportTransferStagingError(message)


def chunk_file_name(sequence: int, chunk_sha256: str) -> str:
    """`f"{sequence:02d}-{chunk_sha256}"` for an admitted sequence and digest, else a refusal."""
    if type(sequence) is not int or not 0 <= sequence < MAX_TRANSFER_CHUNKS:
        raise _refuse("the transfer chunk sequence is not admitted")
    if type(chunk_sha256) is not str or not _SHA256_HEX.match(chunk_sha256):
        raise _refuse("the transfer chunk digest is not admitted")
    return f"{sequence:02d}-{chunk_sha256}"


def _temporary(name: str) -> str:
    return f".{name}.tmp"


def _is_chunk_entry(name: str) -> bool:
    for pattern in (_CHUNK_FILE, _TEMPORARY_FILE):
        match = pattern.match(name)
        if match is not None and int(match.group(1)) < MAX_TRANSFER_CHUNKS:
            return True
    return False


class FilesystemReportTransferStaging(ReportTransferStaging):
    """Transfer chunks under `<root>/transfer`, the report content root's staging tree."""

    def __init__(
        self,
        root: Path,
        *,
        source_roots: Iterable[Path] = (),
        managed_documents_root: Path | None = None,
        other_roots: Iterable[Path] = (),
    ) -> None:
        if not ANCHORING_IS_AVAILABLE:  # pragma: no cover - every supported platform has it
            raise ReportContentRootError(
                "this platform cannot perform directory-anchored writes, so the "
                "transfer staging cannot hold its containment guarantee"
            )
        self._root: Final = resolve_clear_root(
            Path(root),
            source_roots=source_roots,
            managed_documents_root=managed_documents_root,
            other_roots=other_roots,
        )

    @property
    def root(self) -> Path:
        """The resolved root. Read by operations and composition, never by a request."""
        return self._root

    # ---- derivation ------------------------------------------------------

    def _components(self, session_id: str) -> tuple[str, str, str]:
        """`("transfer", shard, session_id)` of an admitted `grxfr_` id, or a refusal."""
        if type(session_id) is not str:
            raise _refuse("the transfer session identifier is not admitted")
        try:
            kind, suffix = parse_identifier(session_id)
            if kind is not IdKind.REPORT_TRANSFER_SESSION:
                raise InvalidIdentifierError("kind")
            validate_identifier(session_id, kind)
        except (InvalidIdentifierError, ValueError):
            raise _refuse("the transfer session identifier is not admitted") from None
        if suffix != suffix.lower():
            raise _refuse("the transfer session identifier is not admitted")
        return _TRANSFER, suffix[:_SHARD], session_id

    def _admitted(self, shard: str, name: str) -> bool:
        try:
            _transfer, derived, _ = self._components(name)
        except ReportTransferStagingError:
            return False
        return derived == shard

    # ---- anchored walks --------------------------------------------------

    def _walk(self, parts: Iterable[str], *, create: bool) -> int | None:
        """A descriptor for `root/parts...` (`O_NOFOLLOW` each), or `None` if one is absent.

        With `create`, a missing component is made with `mkdirat` (0700) and
        its parent `fsync`ed, so `None` is never returned.
        """
        try:
            current = os.open(self._root, DIRECTORY_FLAGS)
        except OSError:
            raise _refuse("the transfer staging root could not be opened") from None
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                    except OSError:
                        raise _refuse("a transfer staging directory could not be created") from None
                    else:
                        try:
                            os.fsync(current)
                        except OSError:
                            raise _refuse(
                                "a transfer staging directory could not be made durable"
                            ) from None
                try:
                    nested = os.open(part, DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    os.close(current)
                    return None
                except OSError:
                    raise _refuse(
                        "a transfer staging location is not a directory reachable "
                        "without following a link"
                    ) from None
                os.close(current)
                current = nested
        except BaseException:
            os.close(current)
            raise
        return current

    # ---- chunks ----------------------------------------------------------

    def put_chunk(self, session_id: str, sequence: int, *, chunk_sha256: str, data: bytes) -> None:
        transfer, shard, name = self._components(session_id)
        file_name = chunk_file_name(sequence, chunk_sha256)
        if type(data) is not bytes or not 1 <= len(data) <= TRANSFER_CHUNK_BYTES:
            raise _refuse("the transfer chunk size is not admitted")
        if hashlib.sha256(data).hexdigest() != chunk_sha256:
            raise _refuse("the transfer chunk digest is not the chunk's")
        session_fd = self._walk((transfer, shard, name), create=True)
        if session_fd is None:  # pragma: no cover - create never answers absent
            raise _refuse("the transfer staging session could not be created")
        try:
            if self._present(session_fd, file_name):
                # A crashed attempt published this very chunk: verify, accept.
                self._check(session_fd, file_name, chunk_sha256, len(data))
                return
            try:
                self._write(session_fd, file_name, chunk_sha256, data)
                os.fsync(session_fd)
                shard_fd = self._walk((transfer, shard), create=False)
                if shard_fd is not None:
                    try:
                        os.fsync(shard_fd)
                    finally:
                        os.close(shard_fd)
            except ReportTransferStagingError:
                raise
            except OSError:
                raise _refuse("the transfer chunk could not be staged") from None
        finally:
            os.close(session_fd)

    def _present(self, session_fd: int, file_name: str) -> bool:
        try:
            os.stat(file_name, dir_fd=session_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError:
            raise _refuse("the transfer chunk is not readable") from None
        return True

    def _write(self, session_fd: int, file_name: str, chunk_sha256: str, data: bytes) -> None:
        """Temporary (O_EXCL, 0600), write, fsync, re-read and verify, link, unlink."""
        temporary = _temporary(file_name)
        # A crashed attempt's temporary of this exact name: ours, by its name.
        with suppress(FileNotFoundError):
            status = os.stat(temporary, dir_fd=session_fd, follow_symlinks=False)
            if not S_ISREG(status.st_mode) or status.st_nlink > 1:
                raise _refuse("the transfer chunk temporary is not a plain file")
            os.unlink(temporary, dir_fd=session_fd)
        descriptor = os.open(temporary, CREATE_FLAGS, 0o600, dir_fd=session_fd)
        try:
            try:
                view = memoryview(data)
                written = 0
                while written < len(view):
                    written += os.write(descriptor, view[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            self._check(session_fd, temporary, chunk_sha256, len(data))
            try:
                os.link(
                    temporary,
                    file_name,
                    src_dir_fd=session_fd,
                    dst_dir_fd=session_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                # A concurrent identical attempt won: what is there must verify.
                self._check(session_fd, file_name, chunk_sha256, len(data))
        finally:
            with suppress(OSError):
                os.unlink(temporary, dir_fd=session_fd)

    def _check(
        self, directory_fd: int, entry: str, expected_sha256: str, expected_byte_count: int
    ) -> bytes:
        """Open one file under `directory_fd`, refuse a non-plain one, verify size and digest."""
        try:
            descriptor = os.open(entry, READ_FLAGS, dir_fd=directory_fd)
        except OSError:
            raise _refuse("the transfer chunk is not readable") from None
        try:
            status = os.fstat(descriptor)
            if not S_ISREG(status.st_mode) or status.st_nlink > 1:
                raise _refuse("the transfer chunk is not readable")
            digest = hashlib.sha256()
            pieces: list[bytes] = []
            total = 0
            while True:
                want = min(_READ_SLICE, expected_byte_count + 1 - total)
                if want <= 0:
                    break
                piece = os.read(descriptor, want)
                if not piece:
                    break
                total += len(piece)
                digest.update(piece)
                pieces.append(piece)
        except OSError:
            raise _refuse("the transfer chunk is not readable") from None
        finally:
            os.close(descriptor)
        if total != expected_byte_count or digest.hexdigest() != expected_sha256:
            raise _refuse("the staged transfer chunk is not the recorded one")
        return b"".join(pieces)

    def read_chunk(
        self, session_id: str, sequence: int, *, chunk_sha256: str, expected_byte_count: int
    ) -> bytes:
        transfer, shard, name = self._components(session_id)
        file_name = chunk_file_name(sequence, chunk_sha256)
        if (
            type(expected_byte_count) is not int
            or not 1 <= expected_byte_count <= TRANSFER_CHUNK_BYTES
        ):
            raise _refuse("the expected transfer chunk size is not admitted")
        session_fd = self._walk((transfer, shard, name), create=False)
        if session_fd is None:
            raise _refuse("the transfer chunk is not readable")
        try:
            return self._check(session_fd, file_name, chunk_sha256, expected_byte_count)
        finally:
            os.close(session_fd)

    def has_session(self, session_id: str) -> bool:
        transfer, shard, name = self._components(session_id)
        try:
            shard_fd = self._walk((transfer, shard), create=False)
        except ReportTransferStagingError:
            return False
        if shard_fd is None:
            return False
        try:
            status = os.stat(name, dir_fd=shard_fd, follow_symlinks=False)
        except OSError:
            return False
        finally:
            os.close(shard_fd)
        return S_ISDIR(status.st_mode)

    # ---- discard ---------------------------------------------------------

    def discard(self, session_id: str) -> bool:
        transfer, shard, name = self._components(session_id)
        shard_fd = self._walk((transfer, shard), create=False)
        if shard_fd is None:
            return False
        session_fd: int | None = None
        removed = False
        try:
            try:
                session_fd = os.open(name, DIRECTORY_FLAGS, dir_fd=shard_fd)
            except FileNotFoundError:
                return False
            except OSError:
                raise _refuse(
                    "a transfer staging location is not a directory reachable "
                    "without following a link"
                ) from None
            try:
                entries = os.listdir(session_fd)  # noqa: PTH208 - anchored by descriptor
            except OSError:
                raise _refuse("the transfer staging session could not be listed") from None
            for entry in entries:
                if not _is_chunk_entry(entry):
                    continue
                try:
                    status = os.stat(entry, dir_fd=session_fd, follow_symlinks=False)
                except OSError:
                    continue
                if not S_ISREG(status.st_mode) or status.st_nlink != 1:
                    continue
                try:
                    os.unlink(entry, dir_fd=session_fd)
                except FileNotFoundError:
                    continue
                except OSError:
                    raise _refuse("a staged transfer chunk could not be removed") from None
                removed = True
            with suppress(OSError):
                os.fsync(session_fd)
            close(session_fd)
            session_fd = None
            try:
                os.rmdir(name, dir_fd=shard_fd)
            except OSError:
                # Something not ours is inside (or appeared): left, and reported.
                pass
            else:
                removed = True
                with suppress(OSError):
                    os.fsync(shard_fd)
        finally:
            close(session_fd)
            os.close(shard_fd)
        return removed

    # ---- enumeration -----------------------------------------------------

    def staged_session_ids(self) -> tuple[str, ...]:
        """Every well-formed session directory's identifier, whatever it holds."""
        return tuple(sorted(name for name, _problems in self._scan() if name is not None))

    def unreadable_entries(self) -> tuple[str, ...]:
        """Entries that are not well-formed sessions or chunks, relative to the root."""
        return tuple(sorted(problem for _name, problems in self._scan() for problem in problems))

    def _scan(self) -> Iterator[tuple[str | None, tuple[str, ...]]]:
        """Walk `transfer/`: `(session id or None, unreadable names)`; never follows a link."""
        base = self._root / _TRANSFER
        try:
            if base.is_symlink() or not base.is_dir():
                if base.exists() or base.is_symlink():
                    yield None, (_TRANSFER,)
                return
            shards = sorted(os.scandir(base), key=lambda entry: entry.name)
        except OSError:
            yield None, (_TRANSFER,)
            return
        for shard in shards:
            relative = f"{_TRANSFER}/{shard.name}"
            if not shard.is_dir(follow_symlinks=False) or len(shard.name) != _SHARD:
                yield None, (relative,)
                continue
            try:
                sessions = sorted(os.scandir(shard.path), key=lambda entry: entry.name)
            except OSError:
                yield None, (relative,)
                continue
            for item in sessions:
                item_relative = f"{relative}/{item.name}"
                if not item.is_dir(follow_symlinks=False) or not self._admitted(
                    shard.name, item.name
                ):
                    yield None, (item_relative,)
                    continue
                yield item.name, tuple(self._session_problems(item.path, item_relative))

    def _session_problems(self, path: str, relative: str) -> Iterator[str]:
        try:
            entries = sorted(os.scandir(path), key=lambda entry: entry.name)
        except OSError:
            yield relative
            return
        for entry in entries:
            entry_relative = f"{relative}/{entry.name}"
            if _TEMPORARY_FILE.match(entry.name) or not _is_chunk_entry(entry.name):
                # A temporary is a crash leftover: discard removes it, but it is
                # not a chunk, so it is reported until then.
                yield entry_relative
                continue
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError:
                yield entry_relative
                continue
            if not S_ISREG(status.st_mode) or status.st_nlink > 1:
                yield entry_relative
