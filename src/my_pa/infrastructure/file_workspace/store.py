"""The contained filesystem store of one file workspace root (ADR-019, WP3).

The frozen input is `docs/architecture/files-workspace-contract.md`. Unlike the
managed byte store, this store *does* take paths -- the workspace is a tree a
person browses -- so containment cannot come from the absence of a path
parameter. It comes from four layers instead:

* **Validation before I/O.** Every path argument is re-validated here with
  `domain.files.paths.parse_path` (section 3: relative, no empty, `.` or `..`
  component, no control character or backslash, bounded, no reserved name),
  even when the caller already did, because a `WorkspacePath` can be built
  directly. Nothing touches the filesystem until that has passed.
* **Directory-anchored resolution.** The root is opened by name and its
  `(st_dev, st_ino)` compared with the construction-time observation; every
  component below it is `lstat`ed with `follow_symlinks=False` and opened
  `O_DIRECTORY | O_NOFOLLOW | O_NONBLOCK` relative to the descriptor above it.
  Every later syscall (`openat`, `linkat`, `renameat`, `unlinkat`, `mkdirat`)
  names one leaf relative to a held descriptor, so a component swapped for a
  link after the walk cannot redirect it.
* **Kind checks at the leaf.** A symlink, FIFO, socket or device anywhere on a
  path is `unsupported_entry`. A leaf is opened `O_NOFOLLOW | O_NONBLOCK` (a FIFO
  never blocks the open) and the descriptor is `fstat`ed: it must still be a
  regular file with the version token observed by `lstat`, or the read is
  refused.
* **No overwrite as a property of the syscall where one exists.** A file is
  moved by `linkat` (which fails on an existing name) then `unlinkat`, with the
  inode identity verified on both names; a replacement keeps the current inode
  under `.my-pa/versions/<fwver id>` by `linkat` and then `renameat`s the new
  content over the name, so readers never see the path absent.

**The control directory** `<root>/.my-pa/{staging,versions,trash}` lives inside
the root because a rename across bind mounts fails with `EXDEV`. It is created
lazily at mode 0700 through descriptors, is unreachable through the API (`.my-pa`
is a reserved name at every depth) and is omitted from listing and search.

**What this does not close, stated rather than implied away (contract section
5, FW-D04, trim T10).** The per-workspace PostgreSQL advisory lock (WP5)
serializes the product's own mutations only. Against a writer outside the
product (SMB, DSM, a shell) the store re-reads the fingerprint immediately
before each rename and refuses a drift as `external_change_detected`, but the
interval between that re-read and the syscall cannot be closed with the
standard library: there is no `renameat2(RENAME_NOREPLACE | RENAME_EXCHANGE)`.
Concretely:

* a directory move, a directory restore and a directory copy's final rename
  check that the destination is absent and then `rename`; POSIX `rename` onto
  an *empty* directory created in that interval replaces it;
* a file published over an existing name (`write_text`, `publish_upload` with
  `expected_version`) links the observed inode into `versions` and then
  `rename`s over the name; a replacement of the name in that interval is
  overwritten (its bytes are lost; the preserved preimage is still the
  observed one, because the link's identity is verified);
* an in-place edit of a file between its fingerprint re-read and the link is
  carried into the preimage, since a fingerprint is not a content hash;
* a directory's token moves only when its direct children change, so a change
  deeper in a trashed tree does not refuse its restore;
* when hard links are unsupported (`EPERM`, `ENOTSUP`, `EMLINK`), a file move
  falls back to check-absent-then-`rename`, with the same interval; the source
  is re-proved the observed regular file before the rename and the moved entry
  after it, and anything else that was moved is renamed back and refused;
* a directory's identity across a move is its inode plus its type only, so on
  ext4 a directory swapped in after the re-check that reuses the observed
  inode number could be moved instead (it stays inside the root).

A file's identity across an unlink is never the inode number alone: ext4
reuses a freed number at once, so a name unlinked and replaced can come back
with the observed `st_ino`.
A file's identity is its inode plus its type, size and `st_mtime_ns`, which a
link or rename leaves unchanged.

A drift detected *after* a successful link is reported as
`external_change_detected` and the link is rolled back: the new name was absent
(or `linkat` would have failed `EEXIST`), so what it holds was made by this
call, and it is unlinked when its inode is the one the source name holds now
(the source was swapped before the link) or the observed one (the link holds
the observed inode, whether the source was then swapped or vanished). Only
when the link named a replacement that the source name no longer holds (it
vanished, or was swapped again), so the link's identity cannot be proved, is
the new name left in place. If a replacement's final
rename fails after the preimage link was made, the preimage stays under
`versions/<id>` unrecorded -- an orphan named by the id the caller minted; when
the preimage was renamed there instead (no hard links), it is renamed back to
the path, best effort, so the path is not left absent.

**Hard links.** A regular file with `st_nlink > 1` may be a host hard link to a
file outside the root, so its bytes are never read out: preview, download,
`include_sha256`, copy and a directory copy containing one are refused
`unsupported_entry`, as in the repository's other contained stores. It is still
listed and `stat`ed as kind `file` (section 4 kinds are by file type). The
store's own links are transient within one call (a move's link-then-unlink, a
publish's link-then-unlink, a replacement's preimage link before the rename
over the name), so a read racing a product mutation may see `unsupported_entry`
for that instant; the advisory lock does not cover reads.

**Modes.** Files waiting under `.my-pa/staging` are created 0600 and given the
published mode (`0666 & ~umask`, the umask read once at construction) by
`fchmod` just before publication; a refused `fchmod` (a NAS ACL) leaves them
0600, and a refused publication puts a still-staged upload back to 0600 (best
effort). A staged name with `st_nlink > 1`, or one whose opened inode is not
the one `lstat` observed, is never sized or written (`unsupported_entry`);
discarding it only unlinks the staging name. A preimage under `versions` keeps
the mode the user file had. The control directories are created 0700 but are
not re-checked for group or other write bits: on the NAS their effective access
is the share ACL.

**Not here.** The advisory lock, idempotency receipts, version and trash rows,
tickets and audit are WP4/WP5. Nothing here reads a clock, a row or the
network, and no message, `repr` or exception chain this module raises names a
host path: every `OSError` is translated `from None` into a section 7
`FilesRefusal` or a `FileWorkspaceUnavailableError`.
"""

from __future__ import annotations

import codecs
import errno
import hashlib
import os
import secrets
import shutil
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Final

from my_pa.contracts.ports import (
    FileWorkspaceEntry,
    FileWorkspacePage,
    FileWorkspacePreview,
    FileWorkspacePublication,
    FileWorkspaceReader,
    FileWorkspaceRootError,
    FileWorkspaceStore,
    FileWorkspaceTrashing,
    FileWorkspaceUnavailableError,
)
from my_pa.domain.files.errors import FilesArgumentError, FilesRefusal
from my_pa.domain.files.paths import (
    WorkspacePath,
    is_reserved_name,
    parse_path,
    validate_name,
)
from my_pa.domain.files.transfer import (
    TRASH_ITEM_ID_PREFIX,
    UPLOAD_ID_PREFIX,
    VERSION_ID_PREFIX,
    parse_file_id,
    validate_sha256,
)
from my_pa.domain.files.versions import EntryKind, validate_version_token, version_token
from my_pa.domain.files.vocabulary import (
    DISK_RESERVE_BYTES,
    MAX_PREVIEW_BYTES,
    MAX_SEARCH_QUERY_CHARACTERS,
    MAX_WRITE_TEXT_BYTES,
    PAGE_SIZE,
    SEARCH_WALK_MAX_DEPTH,
    SEARCH_WALK_MAX_ENTRIES,
    FilesReason,
)

__all__ = ["FilesystemFileWorkspaceStore"]

#: The reserved control directory and its three children (contract section 5).
CONTROL_DIRECTORY: Final = ".my-pa"
STAGING: Final = "staging"
VERSIONS: Final = "versions"
TRASH: Final = "trash"
_CONTROL_MODE: Final = 0o700

#: Read-only, never a link, never a directory where a file is meant, and never
#: blocking on a FIFO. `O_NONBLOCK` has no effect on a regular file.
_DIRECTORY_FLAGS: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
_READ_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
#: Exclusive create, never through a final-component link.
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
#: The staging file of an upload, re-opened for a positional append.
_APPEND_FLAGS: Final = os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK
#: Published user content gets `0666 & ~umask` (the umask read at
#: construction), as a plain `open` would give it. Bytes waiting under
#: `.my-pa/staging` are created 0600 and given that mode by `fchmod` just
#: before publication, so a long-lived upload is private while staged.
_FILE_MODE: Final = 0o666
_STAGED_MODE: Final = 0o600
_DIRECTORY_MODE: Final = 0o777

_CHUNK_BYTES: Final = 1 << 20
#: `errno`s that mean "this filesystem will not hard-link here", where a file
#: move falls back to check-absent-then-rename (see the module docstring).
_LINK_UNSUPPORTED: Final = frozenset(
    code
    for code in (
        errno.EPERM,
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
        errno.EMLINK,
    )
    if code is not None
)
_NO_SPACE: Final = frozenset(
    code for code in (errno.ENOSPC, getattr(errno, "EDQUOT", None)) if code is not None
)
_NOT_A_DIRECTORY_OR_LINK: Final = frozenset({errno.ELOOP, errno.ENOTDIR, errno.EMLINK})
#: What `rename` answers when its destination appeared after the absence check
#: (a non-empty directory, or a kind it cannot replace): `exists`, not `unavailable`.
_RENAME_TARGET_TAKEN: Final = frozenset(
    {errno.EEXIST, errno.ENOTEMPTY, errno.ENOTDIR, errno.EISDIR}
)
_ASCII_FOLD: Final = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _platform_supported() -> bool:
    """Whether every descriptor-relative call this module makes exists here.

    Checked at construction and refused rather than degraded: a platform that
    cannot resolve relative to a descriptor cannot hold the containment.
    """
    return (
        all(
            call in os.supports_dir_fd
            for call in (os.open, os.stat, os.mkdir, os.rename, os.link, os.unlink, os.rmdir)
        )
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_follow_symlinks
        and os.listdir in os.supports_fd
        and os.statvfs in os.supports_fd
        and bool(getattr(shutil.rmtree, "avoids_symlink_attacks", False))
        and hasattr(os, "pread")
        and hasattr(os, "pwrite")
    )


#: Linux reports the umask here (`Umask:`, since 4.7) without changing it.
_PROC_STATUS: Final = Path("/proc/self/status")


def _process_umask() -> int:
    """The process umask, read once at construction.

    On Linux it is read from `/proc/self/status`. Elsewhere (or when that line
    is missing or malformed) `umask` can only be read by setting it, so it is
    set to the stricter 0o077 for that instant and put straight back: a file
    another thread creates in that instant is more private, never less. The
    store is therefore constructed at composition, before worker threads start.
    """
    with suppress(OSError, UnicodeDecodeError, ValueError):
        for line in _PROC_STATUS.read_text(encoding="ascii").splitlines():
            if line.startswith("Umask:"):
                return int(line.removeprefix("Umask:").strip(), 8) & 0o777
    current = os.umask(0o077)
    os.umask(current)
    return current


def _publishable(descriptor: int, mode: int) -> None:
    """Give a staged file its published mode; best effort (a NAS ACL may refuse `chmod`)."""
    with suppress(OSError):
        os.fchmod(descriptor, mode)


def _unavailable() -> FileWorkspaceUnavailableError:
    return FileWorkspaceUnavailableError("the file workspace operation could not be completed")


def _refuse(field: str, reason: FilesReason) -> FilesRefusal:
    return FilesRefusal(field, reason)


@contextmanager
def _translated() -> Iterator[None]:
    """Turn any escaping `OSError` into a path-free refusal (`from None`).

    An `OSError` of `os.open(root)` carries the host path in its `filename`.
    A context manager cannot drop the implicit `__context__` of what it
    raises, so the original error is scrubbed of its file names before the
    replacement is raised with its chain suppressed: neither a formatted
    traceback nor a walk of `__context__` can reach the host path.
    """
    try:
        yield
    except OSError as error:
        error.filename = None
        error.filename2 = None
        if error.errno in _NO_SPACE:
            raise _refuse("workspace", FilesReason.QUOTA) from None
        raise _unavailable() from None


def _kind(mode: int) -> EntryKind:
    if S_ISREG(mode):
        return EntryKind.FILE
    if S_ISDIR(mode):
        return EntryKind.DIRECTORY
    return EntryKind.OTHER


def _token(status: os.stat_result) -> str:
    return version_token(
        dev=status.st_dev,
        ino=status.st_ino,
        kind=_kind(status.st_mode),
        size=status.st_size,
        mtime_ns=status.st_mtime_ns,
        ctime_ns=status.st_ctime_ns,
    )


def _hard_linked(status: os.stat_result) -> bool:
    """A regular file with another name: perhaps a host hard link to a file outside the root.

    Its bytes are never read out (`unsupported_entry`), as in every other
    contained store of the repository. It is still listed as kind `file`
    (section 4 kinds are by file type, and the version token is unchanged).
    """
    return S_ISREG(status.st_mode) and status.st_nlink > 1


def _same_inode(one: os.stat_result, other: os.stat_result) -> bool:
    return (one.st_dev, one.st_ino) == (other.st_dev, other.st_ino)


def _same_file(status: os.stat_result, observed: os.stat_result) -> bool:
    """`status` is the observed regular file, not merely an inode with its number.

    `(st_dev, st_ino)` alone is not an identity across an unlink: ext4 (the
    Linux CI runner's `/tmp`, and a typical NAS volume) hands a freed inode
    number straight to the next allocation in the same directory, so a file
    unlinked and replaced by a symlink or directory can come back with the
    observed number. APFS allocates inode numbers monotonically and never shows
    this. The file type, size and `st_mtime_ns` are compared too: `linkat` and
    `renameat` change `st_nlink` and `st_ctime` but never these, while a
    different object reusing the number would have to match all of them.
    """
    return (
        S_ISREG(status.st_mode)
        and _same_inode(status, observed)
        and status.st_size == observed.st_size
        and status.st_mtime_ns == observed.st_mtime_ns
    )


def _entry(
    path: str, name: str, status: os.stat_result, sha256: str | None = None
) -> FileWorkspaceEntry:
    kind = _kind(status.st_mode)
    return FileWorkspaceEntry(
        path=path,
        name=name,
        kind=kind,
        size=status.st_size if kind is EntryKind.FILE else None,
        mtime_ns=status.st_mtime_ns,
        version=_token(status),
        sha256=sha256,
    )


def _addressable(name: str) -> bool:
    """Whether a directory entry can be named through the API (listing omits the rest).

    Reserved names (section 3 rule 5) and names no request could spell -- not
    UTF-8 (surfaced by `listdir` as lone surrogates), a control character, a
    backslash -- are omitted.
    """
    try:
        validate_name(name, "name")
    except FilesRefusal:
        return False
    return True


def _name_bytes(name: str) -> bytes:
    return name.encode("utf-8")


def _names(directory: int) -> list[str]:
    """A directory's addressable entry names, sorted by their UTF-8 bytes."""
    listed = os.listdir(directory)
    return sorted((name for name in listed if _addressable(name)), key=_name_bytes)


def _copyable_names(directory: int) -> list[str]:
    """`_names`, but a name no request could spell refuses the copy (`unsupported_entry`).

    A directory copy must not silently drop part of the tree. Reserved names
    (section 3 rule 5: the control directory and the NAS's own `@eaDir`,
    `#recycle`, `#snapshot` metadata) stay omitted, as listing and search omit
    them; a non-UTF-8 name, a control character or a backslash refuses.
    """
    names: list[str] = []
    for name in os.listdir(directory):
        if is_reserved_name(name):
            continue
        if not _addressable(name):
            raise _refuse("path", FilesReason.UNSUPPORTED_ENTRY)
        names.append(name)
    return sorted(names, key=_name_bytes)


def _bounded_int(value: object, field: str, low: int, high: int | None = None) -> int:
    if type(value) is not int:
        raise FilesArgumentError(field, "type")
    if value < low or (high is not None and value > high):
        raise FilesArgumentError(field, "bounds")
    return value


def _file_id(value: object, prefix: str, field: str) -> str:
    parsed = parse_file_id(value, prefix)
    if parsed is None:
        raise FilesArgumentError(field, "pattern")
    return parsed


def _comparable(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except (OSError, RuntimeError):
        return Path(path).absolute()


def _overlaps(one: Path, other: Path) -> bool:
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


def _close(descriptor: int) -> None:
    with suppress(OSError):
        os.close(descriptor)


def _hash_descriptor(descriptor: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    length = 0
    position = 0
    while True:
        chunk = os.pread(descriptor, _CHUNK_BYTES, position)
        if not chunk:
            return length, digest.hexdigest()
        digest.update(chunk)
        length += len(chunk)
        position += len(chunk)


def _write_all(descriptor: int, data: bytes, position: int) -> int:
    view = memoryview(data)
    written = 0
    while written < len(view):
        written += os.pwrite(descriptor, view[written:], position + written)
    return position + written


class _HeldFile(FileWorkspaceReader):
    """A regular file held open, bound to the version observed when it was opened."""

    def __init__(self, descriptor: int, status: os.stat_result) -> None:
        self._descriptor: int | None = descriptor
        self.size = status.st_size
        self.version = _token(status)

    def __enter__(self) -> _HeldFile:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _checked(self) -> int:
        if self._descriptor is None:
            raise _unavailable()
        with _translated():
            status = os.fstat(self._descriptor)
            # `st_nlink == 0`: the held inode was unlinked or renamed over. Its
            # token can survive that when the ctime clock is coarse (Linux
            # before 6.13), so the link count is checked as well. A live file
            # has at least one link; the store's own transient links only
            # raise the count.
            if status.st_nlink == 0 or _token(status) != self.version:
                raise _refuse("version", FilesReason.EXTERNAL_CHANGE_DETECTED)
        return self._descriptor

    def read_range(self, start: int, length: int) -> Iterator[bytes]:
        """Validated and version-checked when called; re-checked before every chunk."""
        _bounded_int(start, "start", 0)
        _bounded_int(length, "length", 0)
        self._checked()
        return self._chunks(start, length)

    def _chunks(self, start: int, length: int) -> Iterator[bytes]:
        position = start
        remaining = length
        while remaining > 0:
            descriptor = self._checked()
            with _translated():
                chunk = os.pread(descriptor, min(remaining, _CHUNK_BYTES), position)
            if not chunk:
                return
            position += len(chunk)
            remaining -= len(chunk)
            yield chunk

    def sha256(self) -> str:
        descriptor = self._checked()
        with _translated():
            _length, digest = _hash_descriptor(descriptor)
        self._checked()
        return digest

    def close(self) -> None:
        if self._descriptor is not None:
            _close(self._descriptor)
            self._descriptor = None


class FilesystemFileWorkspaceStore(FileWorkspaceStore):
    """`FileWorkspaceStore` over one configured, contained root (see the module docstring)."""

    def __init__(
        self,
        root: Path,
        *,
        source_roots: Iterable[Path] = (),
        managed_roots: Iterable[Path] = (),
        report_roots: Iterable[Path] = (),
        disk_reserve_bytes: int = DISK_RESERVE_BYTES,
    ) -> None:
        if not _platform_supported():  # pragma: no cover - every supported platform has it
            raise FileWorkspaceRootError(
                "this platform cannot perform directory-anchored syscalls, so the "
                "file workspace cannot hold its containment"
            )
        candidate = Path(root)
        if not candidate.is_absolute():
            raise FileWorkspaceRootError("the configured file workspace root is not absolute")
        try:
            if candidate.is_symlink():
                raise FileWorkspaceRootError(
                    "the configured file workspace root is a symbolic link"
                )
            resolved = candidate.resolve(strict=True)
            status = os.stat(resolved, follow_symlinks=False)  # noqa: PTH116 - an lstat
        except FileWorkspaceRootError:
            raise
        except (OSError, RuntimeError) as error:
            # `from None` hides the chain from a formatted traceback, but the
            # error stays the implicit `__context__`: scrub its host path.
            if isinstance(error, OSError):
                error.filename = None
                error.filename2 = None
            else:
                error.args = ()
            raise FileWorkspaceRootError(
                "the configured file workspace root could not be resolved"
            ) from None
        if not S_ISDIR(status.st_mode):
            raise FileWorkspaceRootError(
                "the configured file workspace root is not an existing directory"
            )
        for other in (*source_roots, *managed_roots, *report_roots):
            if _overlaps(resolved, _comparable(Path(other))):
                raise FileWorkspaceRootError(
                    "the file workspace root is the same tree as a source, managed "
                    "document or report content root, or lies inside one, or contains one"
                )
        self._root: Final = resolved
        self._identity: Final = (status.st_dev, status.st_ino)
        self._reserve: Final = _bounded_int(disk_reserve_bytes, "disk_reserve_bytes", 0)
        self._published_mode: Final = _FILE_MODE & ~_process_umask()

    # ---- a seam for tests: called immediately before each fingerprint re-check

    def _checkpoint(self, stage: str) -> None:
        """No-op. Tests replace it to act between an observation and its re-check."""

    def _after_recheck(self, stage: str) -> None:
        """No-op. Tests replace it to act between a re-check and the link or rename after it."""

    # ---- descriptors -------------------------------------------------------

    def _open_root(self, stack: ExitStack) -> int:
        descriptor = os.open(self._root, _DIRECTORY_FLAGS)
        stack.callback(_close, descriptor)
        status = os.fstat(descriptor)
        if (status.st_dev, status.st_ino) != self._identity:
            raise _unavailable()
        return descriptor

    @staticmethod
    def _lstat(directory: int, name: str) -> os.stat_result | None:
        try:
            return os.stat(name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return None

    @staticmethod
    def _enter(stack: ExitStack, directory: int, name: str, field: str) -> int:
        """`name` under `directory` as an anchored directory descriptor, or a refusal."""
        status = FilesystemFileWorkspaceStore._lstat(directory, name)
        if status is None:
            raise _refuse(field, FilesReason.NOT_FOUND)
        if not S_ISDIR(status.st_mode):
            raise _refuse(field, FilesReason.UNSUPPORTED_ENTRY)
        try:
            nested = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
        except FileNotFoundError:
            raise _refuse(field, FilesReason.NOT_FOUND) from None
        except OSError as error:
            if error.errno in _NOT_A_DIRECTORY_OR_LINK:
                raise _refuse(field, FilesReason.UNSUPPORTED_ENTRY) from None
            raise
        stack.callback(_close, nested)
        return nested

    def _directory(self, stack: ExitStack, path: WorkspacePath, field: str) -> int:
        current = self._open_root(stack)
        for component in path.components:
            current = self._enter(stack, current, component, field)
        return current

    def _control(self, stack: ExitStack, child: str, *, create: bool) -> int | None:
        """`.my-pa/<child>` as a descriptor, created 0700 when `create`; `None` if absent."""
        current = self._open_root(stack)
        for name in (CONTROL_DIRECTORY, child):
            if create:
                try:
                    os.mkdir(name, _CONTROL_MODE, dir_fd=current)
                    os.fsync(current)
                except FileExistsError:
                    pass
            status = self._lstat(current, name)
            if status is None:
                return None
            if not S_ISDIR(status.st_mode):
                raise _unavailable()
            try:
                nested = os.open(name, _DIRECTORY_FLAGS, dir_fd=current)
            except OSError:
                raise _unavailable() from None
            stack.callback(_close, nested)
            current = nested
        return current

    def _required_control(self, stack: ExitStack, child: str, field: str) -> int:
        descriptor = self._control(stack, child, create=False)
        if descriptor is None:
            raise _refuse(field, FilesReason.NOT_FOUND)
        return descriptor

    def _open_file(
        self, stack: ExitStack, directory: int, name: str, observed: os.stat_result, field: str
    ) -> int:
        """Open an observed regular file and prove the descriptor is that observation."""
        try:
            descriptor = os.open(name, _READ_FLAGS, dir_fd=directory)
        except FileNotFoundError:
            raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED) from None
        except OSError as error:
            if error.errno in _NOT_A_DIRECTORY_OR_LINK:
                raise _refuse(field, FilesReason.UNSUPPORTED_ENTRY) from None
            raise
        stack.callback(_close, descriptor)
        held = os.fstat(descriptor)
        if not S_ISREG(held.st_mode) or _hard_linked(observed) or _hard_linked(held):
            raise _refuse(field, FilesReason.UNSUPPORTED_ENTRY)
        if _token(held) != _token(observed):
            raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED)
        return descriptor

    def _existing(
        self,
        stack: ExitStack,
        path: WorkspacePath,
        field: str,
        expected_version: str | None,
    ) -> tuple[int, os.stat_result]:
        """The parent descriptor and `lstat` of an existing file or directory (CAS checked)."""
        parent = self._directory(stack, path.parent, field)
        status = self._lstat(parent, path.name)
        if status is None:
            raise _refuse(field, FilesReason.NOT_FOUND)
        if _kind(status.st_mode) is EntryKind.OTHER:
            raise _refuse(field, FilesReason.UNSUPPORTED_ENTRY)
        if expected_version is not None and _token(status) != expected_version:
            raise _refuse(field, FilesReason.VERSION_CONFLICT)
        return parent, status

    def _recheck(self, directory: int, name: str, observed: os.stat_result, field: str) -> None:
        """The fingerprint re-read immediately before a rename (contract section 5)."""
        current = self._lstat(directory, name)
        if current is None or _token(current) != _token(observed):
            raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED)

    # ---- moving names --------------------------------------------------------

    def _rename_absent(
        self, source: int, name: str, target: int, target_name: str, field: str
    ) -> None:
        """Check-absent-then-rename: the documented, non-atomic no-overwrite."""
        if self._lstat(target, target_name) is not None:
            raise _refuse(field, FilesReason.EXISTS)
        taken = False
        try:
            os.rename(name, target_name, src_dir_fd=source, dst_dir_fd=target)
        except OSError as error:
            if error.errno not in _RENAME_TARGET_TAKEN:
                raise
            taken = True
        if taken:
            raise _refuse(field, FilesReason.EXISTS)

    def _relocate(
        self,
        source: int,
        name: str,
        observed: os.stat_result,
        target: int,
        target_name: str,
        *,
        field: str,
        target_field: str,
    ) -> None:
        """Move one observed entry to an absent name without overwriting.

        A file is hard-linked to the new name and unlinked from the old one,
        each name's inode verified; a directory is checked absent and renamed.
        """
        self._checkpoint("relocate")
        self._recheck(source, name, observed, field)
        self._after_recheck("relocate")
        if S_ISDIR(observed.st_mode):
            self._rename_moved(source, name, observed, target, target_name, field, target_field)
        else:
            # Platform semantics this branch relies on (Python passes
            # `linkat(..., flags=0)` for `follow_symlinks=False` on both):
            # * Linux and macOS both hard-link a *symlink itself* rather than
            #   its target (verified on macOS; Linux `linkat` without
            #   `AT_SYMLINK_FOLLOW`). Linux `fs.protected_hardlinks=1` allows it
            #   when the caller owns the symlink, so a swapped-in symlink of
            #   the service's own user is linked, not refused.
            # * Linking a directory fails `EPERM` on both, as does a
            #   filesystem without hard links; that falls back to rename.
            # * `rename` moves anything onto an absent name -- symlink,
            #   directory or file -- so the fallback must prove what it moved.
            # * ext4 reuses a freed inode number at once, so the identity
            #   checks use `_same_file`, never the inode number alone; that
            #   reuse is why a symlink swapped in after the re-check passed an
            #   inode-only check on the Linux CI runner and not on APFS.
            try:
                os.link(
                    name, target_name, src_dir_fd=source, dst_dir_fd=target, follow_symlinks=False
                )
            except FileExistsError:
                raise _refuse(target_field, FilesReason.EXISTS) from None
            except OSError as error:
                if error.errno not in _LINK_UNSUPPORTED:
                    raise
                # Never rename an unverified entry: the link may have failed
                # because the source is now a directory, not the file.
                current = self._lstat(source, name)
                if current is None or not _same_file(current, observed):
                    raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED) from None
                self._rename_moved(source, name, observed, target, target_name, field, target_field)
            else:
                linked = self._lstat(target, target_name)
                remaining = self._lstat(source, name)
                if linked is None or not _same_file(linked, observed):
                    # The source name was replaced between the re-check and
                    # the link, so the link this call made names the
                    # replacement. The target name was absent (or the link
                    # would have failed `EEXIST`): when it still holds the
                    # source's current inode it is this call's link -- undo it
                    # and leave the replacement at the source alone.
                    self._unlink_if(target, target_name, linked, remaining)
                    raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED)
                if remaining is None or not _same_file(remaining, observed):
                    # The source name was replaced after the link: undo the
                    # link of the observed inode and leave the replacement alone.
                    self._unlink_if(target, target_name, linked, observed)
                    raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED)
                os.unlink(name, dir_fd=source)
        os.fsync(target)
        os.fsync(source)

    def _rename_moved(
        self,
        source: int,
        name: str,
        observed: os.stat_result,
        target: int,
        target_name: str,
        field: str,
        target_field: str,
    ) -> None:
        """Check-absent-then-rename, then prove the observed entry is what moved.

        Something else may take the source name between the last check and the
        rename; it is then put back where it was (best effort) and the move is
        refused `external_change_detected`.
        """
        self._rename_absent(source, name, target, target_name, target_field)
        moved = self._lstat(target, target_name)
        if S_ISDIR(observed.st_mode):
            proved = moved is not None and S_ISDIR(moved.st_mode) and _same_inode(moved, observed)
        else:
            proved = moved is not None and _same_file(moved, observed)
        if not proved:
            if moved is not None:
                with suppress(OSError, FilesRefusal):
                    self._rename_absent(target, target_name, source, name, field)
            raise _refuse(field, FilesReason.EXTERNAL_CHANGE_DETECTED)

    @staticmethod
    def _unlink_if(
        directory: int,
        name: str,
        status: os.stat_result | None,
        expected: os.stat_result | None,
    ) -> None:
        """Unlink `name` only when its `lstat` proves it is `expected`'s inode."""
        if status is not None and expected is not None and _same_inode(status, expected):
            os.unlink(name, dir_fd=directory)

    # ---- reads ---------------------------------------------------------------

    def list_directory(
        self, path: str, *, after: str | None = None, page_size: int = PAGE_SIZE
    ) -> FileWorkspacePage:
        directory_path = parse_path(path, allow_root=True)
        size = _bounded_int(page_size, "page_size", 1, PAGE_SIZE)
        cursor: bytes | None = None
        if after is not None:
            if type(after) is not str:
                raise FilesArgumentError("after", "type")
            try:
                cursor = _name_bytes(after)
            except UnicodeEncodeError:
                raise FilesArgumentError("after", "pattern") from None
        with ExitStack() as stack, _translated():
            directory = self._directory(stack, directory_path, "path")
            names = _names(directory)
            if cursor is not None:
                names = [name for name in names if _name_bytes(name) > cursor]
            entries: list[FileWorkspaceEntry] = []
            more = False
            for name in names:
                status = self._lstat(directory, name)
                if status is None:
                    continue
                if len(entries) == size:
                    more = True
                    break
                entries.append(_entry(self._child_text(directory_path, name), name, status))
        return FileWorkspacePage(
            entries=tuple(entries), next_after=entries[-1].name if more and entries else None
        )

    @staticmethod
    def _child_text(directory: WorkspacePath, name: str) -> str:
        return WorkspacePath((*directory.components, name)).text

    def stat(self, path: str, *, include_sha256: bool = False) -> FileWorkspaceEntry:
        entry_path = parse_path(path)
        with ExitStack() as stack, _translated():
            parent = self._directory(stack, entry_path.parent, "path")
            status = self._lstat(parent, entry_path.name)
            if status is None:
                raise _refuse("path", FilesReason.NOT_FOUND)
            digest: str | None = None
            if include_sha256 and S_ISREG(status.st_mode):
                descriptor = self._open_file(stack, parent, entry_path.name, status, "path")
                _length, digest = _hash_descriptor(descriptor)
                if _token(os.fstat(descriptor)) != _token(status):
                    raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
            return _entry(entry_path.text, entry_path.name, status, digest)

    def search(self, path: str, query: str, *, page_size: int = PAGE_SIZE) -> FileWorkspacePage:
        subtree = parse_path(path, allow_root=True)
        if type(query) is not str:
            raise FilesArgumentError("query", "type")
        if not 1 <= len(query) <= MAX_SEARCH_QUERY_CHARACTERS:
            raise FilesArgumentError("query", "bounds")
        size = _bounded_int(page_size, "page_size", 1, PAGE_SIZE)
        needle = query.translate(_ASCII_FOLD)
        found: list[FileWorkspaceEntry] = []
        visited = 0
        truncated = False

        def walk(directory: int, location: WorkspacePath, depth: int) -> bool:
            """Depth-first in name-byte order; `False` once a cap or the page stops the walk."""
            nonlocal visited, truncated
            names = _names(directory)
            for name in names:
                if visited >= SEARCH_WALK_MAX_ENTRIES:
                    truncated = True
                    return False
                visited += 1
                status = self._lstat(directory, name)
                if status is None:
                    continue
                child = WorkspacePath((*location.components, name))
                if needle in name.translate(_ASCII_FOLD):
                    if len(found) == size:
                        truncated = True
                        return False
                    found.append(_entry(child.text, name, status))
                if S_ISDIR(status.st_mode):
                    if depth >= SEARCH_WALK_MAX_DEPTH:
                        truncated = True
                        continue
                    with ExitStack() as inner:
                        try:
                            nested = self._enter(inner, directory, name, "path")
                        except (FilesRefusal, PermissionError):
                            # Swapped since the `lstat`, or unreadable to the
                            # service UID: skipped, never followed.
                            continue
                        try:
                            if not walk(nested, child, depth + 1):
                                return False
                        except PermissionError:
                            continue
            return True

        with ExitStack() as stack, _translated():
            walk(self._directory(stack, subtree, "path"), subtree, 1)
        return FileWorkspacePage(entries=tuple(found), truncated=truncated)

    def preview(
        self,
        path: str,
        *,
        offset: int = 0,
        max_bytes: int = MAX_PREVIEW_BYTES,
        expected_version: str | None = None,
    ) -> FileWorkspacePreview:
        file_path = parse_path(path)
        start = _bounded_int(offset, "offset", 0)
        limit = _bounded_int(max_bytes, "max_bytes", 1, MAX_PREVIEW_BYTES)
        if expected_version is not None:
            validate_version_token(expected_version)
        with ExitStack() as stack, _translated():
            parent, status = self._existing(stack, file_path, "path", expected_version)
            if not S_ISREG(status.st_mode):
                raise _refuse("path", FilesReason.UNSUPPORTED_ENTRY)
            descriptor = self._open_file(stack, parent, file_path.name, status, "path")
            version = _token(status)
            total = status.st_size
            if start >= total:
                return FileWorkspacePreview(
                    text="", binary=False, next_offset=None, version=version
                )
            tail = self._character_tail(descriptor, start)
            text: str | None = ""
            consumed = 0
            if start + tail < total:
                text, consumed = self._decode_window(descriptor, start + tail, limit, total)
            if _token(os.fstat(descriptor)) != version:
                raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
        if text is None:
            return FileWorkspacePreview(text=None, binary=True, next_offset=None, version=version)
        after = start + tail + consumed
        return FileWorkspacePreview(
            text=text, binary=False, next_offset=after if after < total else None, version=version
        )

    @staticmethod
    def _character_tail(descriptor: int, start: int) -> int:
        """Bytes from `start` to the end of a character that began before it; 0 on a boundary.

        An `offset` inside a valid character (only a hand-made one: every
        `next_offset` is a boundary) is moved forward to the next character
        rather than misread as binary. The skip is taken only when the bytes
        before `start` really open a well-formed character that `start` falls
        inside; anything else is decoded as it stands (and is binary if invalid).
        """
        if start == 0:
            return 0
        back = min(start, 3)
        window = os.pread(descriptor, back + 3, start - back)
        if len(window) <= back or window[back] & 0xC0 != 0x80:
            return 0
        for index in range(back - 1, -1, -1):
            lead = window[index]
            if lead & 0xC0 == 0x80:
                continue
            width = 2 if lead >> 5 == 0b110 else 3 if lead >> 4 == 0b1110 else 4
            if lead >> 3 > 0b11110 or lead < 0xC0 or index + width <= back:
                return 0
            try:
                window[index : index + width].decode("utf-8")
            except UnicodeDecodeError:
                return 0
            return index + width - back
        return 0

    @staticmethod
    def _decode_window(
        descriptor: int, start: int, limit: int, total: int
    ) -> tuple[str | None, int]:
        """UTF-8 text of at most `limit` bytes from `start`, cut on a character boundary.

        A trailing incomplete sequence is left for the next window. If `limit`
        is smaller than the first character, exactly that one character is
        returned (at most 4 bytes): the only case a window exceeds `limit`.
        Invalid UTF-8 is `(None, 0)`: binary.
        """
        data = os.pread(descriptor, limit, start)
        at_end = start + len(data) >= total
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            text = decoder.decode(data, final=at_end)
        except UnicodeDecodeError:
            return None, 0
        consumed = len(data) - len(decoder.getstate()[0])
        if consumed > 0 or at_end:
            return text, consumed
        data = os.pread(descriptor, 4, start)
        decoder = codecs.getincrementaldecoder("utf-8")()
        try:
            text = decoder.decode(data, final=start + len(data) >= total)
        except UnicodeDecodeError:
            return None, 0
        if not text:
            return None, 0
        first = text[0]
        return first, len(first.encode("utf-8"))

    # ---- directory and name mutations -------------------------------------------

    def mkdir(self, path: str, *, parents: bool = False) -> FileWorkspaceEntry:
        directory_path = parse_path(path)
        if type(parents) is not bool:
            raise FilesArgumentError("parents", "type")
        with ExitStack() as stack, _translated():
            current = self._open_root(stack)
            for component in directory_path.parent.components:
                if parents and self._lstat(current, component) is None:
                    try:
                        os.mkdir(component, _DIRECTORY_MODE, dir_fd=current)
                        os.fsync(current)
                    except FileExistsError:
                        pass
                current = self._enter(stack, current, component, "path")
            try:
                os.mkdir(directory_path.name, _DIRECTORY_MODE, dir_fd=current)
            except FileExistsError:
                raise _refuse("path", FilesReason.EXISTS) from None
            os.fsync(current)
            status = self._lstat(current, directory_path.name)
            if status is None:
                raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
            return _entry(directory_path.text, directory_path.name, status)

    @staticmethod
    def _distinct(source: WorkspacePath, target: WorkspacePath) -> None:
        if target == source:
            raise _refuse("to_path", FilesReason.EXISTS)
        if target.is_within(source):
            raise _refuse("to_path", FilesReason.INVALID_PATH)

    def move(
        self, path: str, to_path: str, *, expected_version: str | None = None
    ) -> FileWorkspaceEntry:
        source_path = parse_path(path)
        target_path = parse_path(to_path, "to_path")
        if expected_version is not None:
            validate_version_token(expected_version)
        self._distinct(source_path, target_path)
        with ExitStack() as stack, _translated():
            source, observed = self._existing(stack, source_path, "path", expected_version)
            target = self._directory(stack, target_path.parent, "to_path")
            if self._lstat(target, target_path.name) is not None:
                raise _refuse("to_path", FilesReason.EXISTS)
            self._relocate(
                source,
                source_path.name,
                observed,
                target,
                target_path.name,
                field="path",
                target_field="to_path",
            )
            return self._observed(target, target_path)

    def _observed(self, directory: int, path: WorkspacePath) -> FileWorkspaceEntry:
        status = self._lstat(directory, path.name)
        if status is None:
            raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
        return _entry(path.text, path.name, status)

    def trash(
        self, path: str, trash_item_id: str, *, expected_version: str | None = None
    ) -> FileWorkspaceTrashing:
        source_path = parse_path(path)
        item = _file_id(trash_item_id, TRASH_ITEM_ID_PREFIX, "trash_item_id")
        if expected_version is not None:
            validate_version_token(expected_version)
        with ExitStack() as stack, _translated():
            source, observed = self._existing(stack, source_path, "path", expected_version)
            trash = self._control(stack, TRASH, create=True)
            if trash is None:  # pragma: no cover - created above
                raise _unavailable()
            if self._lstat(trash, item) is not None:
                raise _refuse("trash_item_id", FilesReason.EXISTS)
            self._relocate(
                source,
                source_path.name,
                observed,
                trash,
                item,
                field="path",
                target_field="trash_item_id",
            )
            trashed = self._lstat(trash, item)
            if trashed is None:
                raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
            return FileWorkspaceTrashing(
                entry=_entry(source_path.text, source_path.name, observed),
                trashed_version=_token(trashed),
            )

    def restore(
        self, trash_item_id: str, to_path: str, *, trashed_version: str
    ) -> FileWorkspaceEntry:
        item = _file_id(trash_item_id, TRASH_ITEM_ID_PREFIX, "trash_item_id")
        target_path = parse_path(to_path, "to_path")
        validate_version_token(trashed_version, "trashed_version")
        with ExitStack() as stack, _translated():
            trash = self._required_control(stack, TRASH, "trash_item_id")
            observed = self._lstat(trash, item)
            if observed is None:
                raise _refuse("trash_item_id", FilesReason.NOT_FOUND)
            if _kind(observed.st_mode) is EntryKind.OTHER:
                raise _refuse("trash_item_id", FilesReason.UNSUPPORTED_ENTRY)
            if _token(observed) != trashed_version:
                raise _refuse("trash_item_id", FilesReason.EXTERNAL_CHANGE_DETECTED)
            target = self._directory(stack, target_path.parent, "to_path")
            if self._lstat(target, target_path.name) is not None:
                raise _refuse("to_path", FilesReason.EXISTS)
            self._relocate(
                trash,
                item,
                observed,
                target,
                target_path.name,
                field="trash_item_id",
                target_field="to_path",
            )
            return self._observed(target, target_path)

    # ---- copies --------------------------------------------------------------

    def copy(
        self, path: str, to_path: str, *, expected_version: str | None = None
    ) -> FileWorkspaceEntry:
        source_path = parse_path(path)
        target_path = parse_path(to_path, "to_path")
        if expected_version is not None:
            validate_version_token(expected_version)
        self._distinct(source_path, target_path)
        with ExitStack() as stack, _translated():
            source, observed = self._existing(stack, source_path, "path", expected_version)
            target = self._directory(stack, target_path.parent, "to_path")
            if self._lstat(target, target_path.name) is not None:
                raise _refuse("to_path", FilesReason.EXISTS)
            staging = self._control(stack, STAGING, create=True)
            if staging is None:  # pragma: no cover - created above
                raise _unavailable()
            temporary = f".copy-{secrets.token_hex(12)}"
            if S_ISREG(observed.st_mode):
                self.ensure_free_space(observed.st_size)
                self._stage_file_copy(stack, source, source_path.name, observed, staging, temporary)
                try:
                    self._checkpoint("copy")
                    self._recheck(source, source_path.name, observed, "path")
                    self._publish_new(staging, temporary, target, target_path.name, "to_path")
                except BaseException:
                    self._discard_quietly(staging, temporary)
                    raise
            else:
                with ExitStack() as scan:
                    origin = self._enter(scan, source, source_path.name, "path")
                    self.ensure_free_space(self._tree_bytes(origin))
                try:
                    os.mkdir(temporary, _DIRECTORY_MODE, dir_fd=staging)
                    with ExitStack() as tree:
                        origin = self._enter(tree, source, source_path.name, "path")
                        copy = self._enter(tree, staging, temporary, "path")
                        self._copy_tree(origin, copy, depth=1, counter=[0])
                    os.fsync(staging)
                    self._checkpoint("copy")
                    self._recheck(source, source_path.name, observed, "path")
                    self._rename_absent(staging, temporary, target, target_path.name, "to_path")
                    os.fsync(target)
                    os.fsync(staging)
                except BaseException:
                    self._discard_tree_quietly(staging, temporary)
                    raise
            return self._observed(target, target_path)

    def _stage_file_copy(
        self,
        stack: ExitStack,
        directory: int,
        name: str,
        observed: os.stat_result,
        staging: int,
        temporary: str,
    ) -> None:
        reader = self._open_file(stack, directory, name, observed, "path")
        try:
            self._copy_descriptor(reader, staging, temporary, self._published_mode)
        except BaseException:
            self._discard_quietly(staging, temporary)
            raise
        if _token(os.fstat(reader)) != _token(observed):
            self._discard_quietly(staging, temporary)
            raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)

    @staticmethod
    def _copy_descriptor(reader: int, directory: int, name: str, mode: int) -> None:
        """Copy into a new staged file created 0600, given `mode` once complete."""
        writer = os.open(name, _CREATE_FLAGS, _STAGED_MODE, dir_fd=directory)
        try:
            position = 0
            while True:
                chunk = os.pread(reader, _CHUNK_BYTES, position)
                if not chunk:
                    break
                position = _write_all(writer, chunk, position)
            _publishable(writer, mode)
            os.fsync(writer)
        finally:
            _close(writer)

    def _tree_bytes(self, directory: int) -> int:
        """Bytes a directory copy would write, refusing past the walk caps (`too_large`)."""
        counter = [0]

        def measure(descriptor: int, depth: int) -> int:
            total = 0
            for name in _copyable_names(descriptor):
                counter[0] += 1
                if counter[0] > SEARCH_WALK_MAX_ENTRIES:
                    raise _refuse("path", FilesReason.TOO_LARGE)
                status = self._lstat(descriptor, name)
                if status is None:
                    continue
                kind = _kind(status.st_mode)
                if kind is EntryKind.OTHER or _hard_linked(status):
                    raise _refuse("path", FilesReason.UNSUPPORTED_ENTRY)
                if kind is EntryKind.FILE:
                    total += status.st_size
                    continue
                if depth >= SEARCH_WALK_MAX_DEPTH:
                    raise _refuse("path", FilesReason.TOO_LARGE)
                with ExitStack() as inner:
                    total += measure(self._enter(inner, descriptor, name, "path"), depth + 1)
            return total

        return measure(directory, 1)

    def _copy_tree(self, source: int, target: int, *, depth: int, counter: list[int]) -> None:
        """Recreate `source`'s addressable entries under `target`, caps re-enforced."""
        for name in _copyable_names(source):
            counter[0] += 1
            if counter[0] > SEARCH_WALK_MAX_ENTRIES:
                raise _refuse("path", FilesReason.TOO_LARGE)
            status = self._lstat(source, name)
            if status is None:
                continue
            kind = _kind(status.st_mode)
            if kind is EntryKind.OTHER:
                raise _refuse("path", FilesReason.UNSUPPORTED_ENTRY)
            if kind is EntryKind.FILE:
                with ExitStack() as inner:
                    reader = self._open_file(inner, source, name, status, "path")
                    self._copy_descriptor(reader, target, name, self._published_mode)
                    if _token(os.fstat(reader)) != _token(status):
                        raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
                continue
            if depth >= SEARCH_WALK_MAX_DEPTH:
                raise _refuse("path", FilesReason.TOO_LARGE)
            os.mkdir(name, _DIRECTORY_MODE, dir_fd=target)
            with ExitStack() as inner:
                nested_source = self._enter(inner, source, name, "path")
                nested_target = self._enter(inner, target, name, "path")
                self._copy_tree(nested_source, nested_target, depth=depth + 1, counter=counter)
                os.fsync(nested_target)
        os.fsync(target)

    # ---- publishing content ------------------------------------------------------

    def _publish_new(
        self, staging: int, temporary: str, target: int, name: str, field: str = "path"
    ) -> None:
        """Give a staged file its first name without overwriting, then drop the staging name."""
        try:
            os.link(temporary, name, src_dir_fd=staging, dst_dir_fd=target, follow_symlinks=False)
        except FileExistsError:
            raise _refuse(field, FilesReason.EXISTS) from None
        except OSError as error:
            if error.errno not in _LINK_UNSUPPORTED:
                raise
            self._rename_absent(staging, temporary, target, name, field)
        else:
            os.unlink(temporary, dir_fd=staging)
        os.fsync(target)
        os.fsync(staging)

    def _target(
        self,
        stack: ExitStack,
        path: WorkspacePath,
        expected_version: str | None,
        preimage_version_id: str | None,
    ) -> tuple[int, os.stat_result | None, str | None]:
        """Where a content write lands: create (no version) or replace (version + preimage id).

        A preimage id given with a create is not used (nothing is preserved);
        it is neither validated nor refused, so a caller may mint one eagerly.
        """
        parent = self._directory(stack, path.parent, "path")
        status = self._lstat(parent, path.name)
        if expected_version is None:
            if status is not None:
                raise _refuse("path", FilesReason.EXISTS)
            return parent, None, None
        if status is None:
            raise _refuse("path", FilesReason.NOT_FOUND)
        if not S_ISREG(status.st_mode):
            raise _refuse("path", FilesReason.UNSUPPORTED_ENTRY)
        if _token(status) != expected_version:
            raise _refuse("path", FilesReason.VERSION_CONFLICT)
        preimage = _file_id(preimage_version_id, VERSION_ID_PREFIX, "preimage_version_id")
        return parent, status, preimage

    def _publish(
        self,
        stack: ExitStack,
        staging: int,
        temporary: str,
        staged: os.stat_result,
        path: WorkspacePath,
        parent: int,
        current: os.stat_result | None,
        preimage: str | None,
    ) -> FileWorkspacePublication:
        """Publish a staged file at `path`: a new name, or over `current` keeping its preimage."""
        self._checkpoint("publish")
        source = self._lstat(staging, temporary)
        if source is None or _token(source) != _token(staged):
            raise _refuse("upload_id", FilesReason.EXTERNAL_CHANGE_DETECTED)
        if current is None or preimage is None:
            self._publish_new(staging, temporary, parent, path.name)
            return FileWorkspacePublication(entry=self._observed(parent, path))
        versions = self._control(stack, VERSIONS, create=True)
        if versions is None:  # pragma: no cover - created above
            raise _unavailable()
        if self._lstat(versions, preimage) is not None:
            raise _refuse("preimage_version_id", FilesReason.EXISTS)
        self._recheck(parent, path.name, current, "path")
        self._after_recheck("publish")
        linked = True
        try:
            os.link(
                path.name, preimage, src_dir_fd=parent, dst_dir_fd=versions, follow_symlinks=False
            )
        except FileExistsError:
            raise _refuse("preimage_version_id", FilesReason.EXISTS) from None
        except OSError as error:
            if error.errno not in _LINK_UNSUPPORTED:
                raise
            linked = False
            os.rename(path.name, preimage, src_dir_fd=parent, dst_dir_fd=versions)
        kept = self._lstat(versions, preimage)
        if kept is None or not _same_file(kept, current):
            # What reached `versions` is not the observed file: take back only
            # what this call put there, and leave the replacement in place.
            if kept is not None:
                if linked:
                    os.unlink(preimage, dir_fd=versions)
                else:
                    self._rename_absent(versions, preimage, parent, path.name, "path")
            raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
        os.fsync(versions)
        try:
            os.rename(temporary, path.name, src_dir_fd=staging, dst_dir_fd=parent)
        except OSError:
            if not linked:
                # The preimage was renamed away, so the path is absent: give
                # the observed file its name back (best effort) before failing.
                with suppress(OSError, FilesRefusal):
                    self._rename_absent(versions, preimage, parent, path.name, "path")
            raise
        os.fsync(parent)
        os.fsync(staging)
        return FileWorkspacePublication(
            entry=self._observed(parent, path), preimage_version_id=preimage
        )

    def write_text(
        self,
        path: str,
        text: str,
        *,
        expected_version: str | None = None,
        preimage_version_id: str | None = None,
    ) -> FileWorkspacePublication:
        file_path = parse_path(path)
        if type(text) is not str:
            raise FilesArgumentError("text", "type")
        try:
            data = text.encode("utf-8")
        except UnicodeEncodeError:
            raise FilesArgumentError("text", "pattern") from None
        if len(data) > MAX_WRITE_TEXT_BYTES:
            raise _refuse("text", FilesReason.TOO_LARGE)
        if expected_version is not None:
            validate_version_token(expected_version)
        with ExitStack() as stack, _translated():
            parent, current, preimage = self._target(
                stack, file_path, expected_version, preimage_version_id
            )
            self.ensure_free_space(len(data))
            staging = self._control(stack, STAGING, create=True)
            if staging is None:  # pragma: no cover - created above
                raise _unavailable()
            temporary = f".text-{secrets.token_hex(12)}"
            writer = os.open(temporary, _CREATE_FLAGS, _STAGED_MODE, dir_fd=staging)
            try:
                try:
                    _write_all(writer, data, 0)
                    _publishable(writer, self._published_mode)
                    os.fsync(writer)
                    staged = os.fstat(writer)
                finally:
                    _close(writer)
                return self._publish(
                    stack, staging, temporary, staged, file_path, parent, current, preimage
                )
            finally:
                self._discard_quietly(staging, temporary)

    # ---- upload staging ------------------------------------------------------------

    def begin_upload(self, upload_id: str) -> None:
        name = _file_id(upload_id, UPLOAD_ID_PREFIX, "upload_id")
        with ExitStack() as stack, _translated():
            staging = self._control(stack, STAGING, create=True)
            if staging is None:  # pragma: no cover - created above
                raise _unavailable()
            try:
                descriptor = os.open(name, _CREATE_FLAGS, _STAGED_MODE, dir_fd=staging)
            except FileExistsError:
                raise _refuse("upload_id", FilesReason.EXISTS) from None
            try:
                os.fsync(descriptor)
            finally:
                _close(descriptor)
            os.fsync(staging)

    def _staged(self, stack: ExitStack, upload_id: str) -> tuple[int, str, os.stat_result]:
        name = _file_id(upload_id, UPLOAD_ID_PREFIX, "upload_id")
        staging = self._required_control(stack, STAGING, "upload_id")
        status = self._lstat(staging, name)
        if status is None:
            raise _refuse("upload_id", FilesReason.NOT_FOUND)
        if not S_ISREG(status.st_mode):
            raise _refuse("upload_id", FilesReason.UNSUPPORTED_ENTRY)
        return staging, name, status

    def upload_offset(self, upload_id: str) -> int:
        with ExitStack() as stack, _translated():
            _staging, _name, status = self._staged(stack, upload_id)
            if _hard_linked(status):
                raise _refuse("upload_id", FilesReason.UNSUPPORTED_ENTRY)
            return status.st_size

    def append_upload(
        self, upload_id: str, offset: int, chunks: Iterable[bytes], *, limit: int
    ) -> int:
        start = _bounded_int(offset, "Upload-Offset", 0)
        ceiling = _bounded_int(limit, "limit", 0)
        with ExitStack() as stack, _translated():
            staging, name, status = self._staged(stack, upload_id)
            try:
                descriptor = os.open(name, _APPEND_FLAGS, dir_fd=staging)
            except OSError as error:
                if error.errno in _NOT_A_DIRECTORY_OR_LINK:
                    raise _refuse("upload_id", FilesReason.UNSUPPORTED_ENTRY) from None
                raise
            stack.callback(_close, descriptor)
            held = os.fstat(descriptor)
            # The descriptor writes: it must be the single-linked inode `lstat`
            # observed, or it could write through a host hard link outside the root.
            if not S_ISREG(held.st_mode) or _hard_linked(held) or not _same_inode(held, status):
                raise _refuse("upload_id", FilesReason.UNSUPPORTED_ENTRY)
            if held.st_size != start:
                raise _refuse("Upload-Offset", FilesReason.OFFSET_MISMATCH)
            position = start
            try:
                for chunk in chunks:
                    if not isinstance(chunk, bytes | bytearray | memoryview):
                        raise FilesArgumentError("body", "type")
                    if position + len(chunk) > ceiling:
                        os.ftruncate(descriptor, start)
                        position = start
                        raise _refuse("body", FilesReason.TOO_LARGE)
                    self.ensure_free_space(len(chunk))
                    position = _write_all(descriptor, bytes(chunk), position)
            except BaseException:
                # Keep what was appended, but never let a failing `fsync`
                # replace the error that interrupted the append.
                with suppress(OSError):
                    os.fsync(descriptor)
                raise
            os.fsync(descriptor)
            return position

    def upload_digest(self, upload_id: str) -> tuple[int, str]:
        with ExitStack() as stack, _translated():
            staging, name, status = self._staged(stack, upload_id)
            descriptor = self._open_file(stack, staging, name, status, "upload_id")
            return _hash_descriptor(descriptor)

    def discard_upload(self, upload_id: str) -> bool:
        name = _file_id(upload_id, UPLOAD_ID_PREFIX, "upload_id")
        with ExitStack() as stack, _translated():
            staging = self._control(stack, STAGING, create=False)
            if staging is None:
                return False
            status = self._lstat(staging, name)
            if status is None:
                return False
            if not S_ISREG(status.st_mode):
                raise _refuse("upload_id", FilesReason.UNSUPPORTED_ENTRY)
            try:
                os.unlink(name, dir_fd=staging)
            except FileNotFoundError:
                return False
            os.fsync(staging)
            return True

    def reap_uploads(self, upload_ids: Iterable[str]) -> int:
        return sum(1 for upload_id in upload_ids if self.discard_upload(upload_id))

    def publish_upload(
        self,
        upload_id: str,
        path: str,
        *,
        length: int,
        sha256: str,
        expected_version: str | None = None,
        preimage_version_id: str | None = None,
    ) -> FileWorkspacePublication:
        file_path = parse_path(path)
        claimed_length = _bounded_int(length, "length", 0)
        claimed_sha256 = validate_sha256(sha256)
        if expected_version is not None:
            validate_version_token(expected_version)
        with ExitStack() as stack, _translated():
            staging, name, status = self._staged(stack, upload_id)
            descriptor = self._open_file(stack, staging, name, status, "upload_id")
            staged_length, staged_sha256 = _hash_descriptor(descriptor)
            if (staged_length, staged_sha256) != (claimed_length, claimed_sha256):
                raise _refuse("sha256", FilesReason.DIGEST_MISMATCH)
            if _token(os.fstat(descriptor)) != _token(status):
                raise _refuse("upload_id", FilesReason.EXTERNAL_CHANGE_DETECTED)
            parent, current, preimage = self._target(
                stack, file_path, expected_version, preimage_version_id
            )
            self.ensure_free_space(0)
            # Private while staged; the published mode is given just before
            # publication (it moves `ctime`, so the staged fingerprint is re-read
            # and that post-`fchmod` fingerprint is what `_publish` compares).
            _publishable(descriptor, self._published_mode)
            staged = os.fstat(descriptor)
            try:
                return self._publish(
                    stack, staging, name, staged, file_path, parent, current, preimage
                )
            except BaseException:
                self._keep_private(descriptor, staging, name)
                raise

    @staticmethod
    def _keep_private(descriptor: int, staging: int, name: str) -> None:
        """Put a still-staged upload back to 0600 after a refused publication; best effort.

        Only while the staging name still holds this single-linked inode: once a
        published name shares it, its mode is the published one.
        """
        with suppress(OSError):
            held = os.fstat(descriptor)
            current = os.stat(name, dir_fd=staging, follow_symlinks=False)
            if _same_inode(held, current) and not _hard_linked(held):
                os.fchmod(descriptor, _STAGED_MODE)

    # ---- downloads -------------------------------------------------------------------

    def open_download(self, path: str, *, expected_version: str) -> FileWorkspaceReader:
        file_path = parse_path(path)
        validate_version_token(expected_version)
        with ExitStack() as stack, _translated():
            parent = self._directory(stack, file_path.parent, "path")
            status = self._lstat(parent, file_path.name)
            if status is None:
                raise _refuse("path", FilesReason.NOT_FOUND)
            if not S_ISREG(status.st_mode):
                raise _refuse("path", FilesReason.UNSUPPORTED_ENTRY)
            if _token(status) != expected_version:
                raise _refuse("path", FilesReason.EXTERNAL_CHANGE_DETECTED)
            return self._hand_over(parent, file_path.name, status, "path")

    def open_preserved_version(self, version_id: str) -> FileWorkspaceReader:
        name = _file_id(version_id, VERSION_ID_PREFIX, "version_id")
        with ExitStack() as stack, _translated():
            versions = self._required_control(stack, VERSIONS, "version_id")
            status = self._lstat(versions, name)
            if status is None:
                raise _refuse("version_id", FilesReason.NOT_FOUND)
            if not S_ISREG(status.st_mode):
                raise _refuse("version_id", FilesReason.UNSUPPORTED_ENTRY)
            return self._hand_over(versions, name, status, "version_id")

    def _hand_over(
        self, directory: int, name: str, status: os.stat_result, field: str
    ) -> FileWorkspaceReader:
        """Open the file and give its descriptor (not closed here) to a reader."""
        with ExitStack() as own:
            descriptor = self._open_file(own, directory, name, status, field)
            reader = _HeldFile(descriptor, os.fstat(descriptor))
            own.pop_all()
        return reader

    # ---- space -----------------------------------------------------------------------

    def ensure_free_space(self, required_bytes: int) -> None:
        required = _bounded_int(required_bytes, "required_bytes", 0)
        with ExitStack() as stack, _translated():
            usage = os.statvfs(self._open_root(stack))
        if usage.f_bavail * usage.f_frsize - required < self._reserve:
            raise _refuse("workspace", FilesReason.QUOTA)

    # ---- cleanup -------------------------------------------------------------------

    @staticmethod
    def _discard_quietly(directory: int, name: str) -> None:
        with suppress(OSError):
            os.unlink(name, dir_fd=directory)

    @staticmethod
    def _discard_tree_quietly(directory: int, name: str) -> None:
        with suppress(OSError):
            shutil.rmtree(name, dir_fd=directory)
