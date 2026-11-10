"""The report content store on a local filesystem (Reports Modernization WP05 C2).

Report content whose decoded size is above the inline threshold is held here,
one object per content row, named by the row's `grcnt_` content id (its
`blob_ref`). This module mirrors the containment discipline of
`infrastructure.managed_document_stores.filesystem.store` without sharing or
modifying it, and it accepts no `mdver_` identifier: the two planes never name
each other's objects.

**There is no path parameter.** Every public method takes an opaque object
identifier or nothing; the location is derived here:

    <root>/<namespace>/<shard>/<object_id>/{decoded,original}

where `<namespace>` is a member of the closed `ReportContentNamespace`
(`content`, admitting only `grcnt_` ids, and WP05b's `preservation`, admitting
only `grprv_` ids), `<shard>` is the first two
characters of the identifier's suffix, and `<object_id>` is the identifier
itself, so a directory found in the tree turns back into the object it holds.
An identifier is admitted only if `validate_identifier` accepts it as one of
the namespace's identifier kinds and its suffix is lowercase (`issue_identifier`
mints lowercase hex; a case-insensitive filesystem must never see two names it
would fold together). The admitted alphabet has no separator, dot or null byte,
so a traversal has nowhere to travel.

**The layers, as in the managed byte store:**

* The root is resolved once, at construction; a root that is missing, not a
  directory, or itself a symbolic link is refused, and so is a root that is,
  contains or lies inside a configured source root, the managed document root,
  or any other root it must stay clear of (a backup destination is given the
  live root). Compared after full resolution on both sides.
* Every syscall below the root is anchored to a directory descriptor: the chain
  is opened one component at a time with `O_DIRECTORY | O_NOFOLLOW`, created
  with `mkdirat`, and the file operations are `openat`/`linkat`/`unlinkat`
  against the descriptor that walk produced. A symbolic link anywhere in the
  chain is refused by the kernel, and nothing is resolved by name twice.
* A write is exclusive at both ends: the object directory is created with
  `mkdir` (an existing object refuses the write; nothing is overwritten), each
  part is written to a temporary created `O_CREAT | O_EXCL | O_NOFOLLOW` with
  mode 0600 inside the object directory, `fsync`ed, re-opened read-only and
  re-hashed against the bytes given, then published with `linkat` (which fails
  rather than replaces) and the temporary unlinked; the object directory and
  its shard are `fsync`ed. **Any failure removes everything this call created**
  -- temporaries, published parts and the object directory -- before the
  refusal propagates, so a failed `put` leaves nothing behind.
* A read opens the part `O_RDONLY | O_NOFOLLOW` under the anchored object
  directory, refuses anything that is not a regular file with exactly one link,
  reads at most one byte more than expected, and compares size and SHA-256
  before returning anything.

**The ordering this serves.** The repository calls `put` before the first
INSERT of the request, so the surviving failure is an object no row names (an
orphan the reconciliation scan reports), never a row naming absent bytes.

**What this does not close**, as the managed byte store records: the root
itself is opened by name for every anchored walk, and a mount inside the root
exposes a subtree no resolution reveals. Both require local privileges that
defeat the boundary by other means.

No message here carries a path, an identifier or a value.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import suppress
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Final

from my_pa.contracts.ports import (
    ReportContentIntegrityError,
    ReportContentMissingError,
    ReportContentNamespace,
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
)
from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    parse_identifier,
    validate_identifier,
)
from my_pa.infrastructure.report_content_stores._anchoring import (
    ANCHORING_IS_AVAILABLE as _ANCHORING_IS_AVAILABLE,
)
from my_pa.infrastructure.report_content_stores._anchoring import (
    CREATE_FLAGS as _CREATE_FLAGS,
)
from my_pa.infrastructure.report_content_stores._anchoring import (
    DIRECTORY_FLAGS as _DIRECTORY_FLAGS,
)
from my_pa.infrastructure.report_content_stores._anchoring import (
    READ_FLAGS as _READ_FLAGS,
)
from my_pa.infrastructure.report_content_stores._anchoring import (
    ReportContentRootError,
    resolve_clear_root,
)
from my_pa.infrastructure.report_content_stores._anchoring import (
    close as _close,
)

__all__ = [
    "NAMESPACE_KINDS",
    "FilesystemReportContentStore",
    "ReportContentRootError",
]


#: The identifier kinds each namespace admits. Closed: a namespace with no
#: entry here cannot be constructed -- `TRANSFER` (WP06 T13) deliberately has
#: none, so this store can never be pointed at the transfer staging tree.
NAMESPACE_KINDS: Final[Mapping[ReportContentNamespace, frozenset[IdKind]]] = {
    ReportContentNamespace.CONTENT: frozenset({IdKind.REPORT_CONTENT}),
    # WP05b B5: preservation objects and seals only; never a content id.
    ReportContentNamespace.PRESERVATION: frozenset({IdKind.REPORT_PRESERVATION_OBJECT}),
}

#: Characters of the identifier suffix naming the shard directory.
_SHARD: Final = 2

_CHUNK_BYTES: Final = 1 << 20

_PART_NAMES: Final = frozenset(part.value for part in ReportContentPart)


def _temporary(part: ReportContentPart) -> str:
    """The temporary name of one part inside its (freshly created) object directory."""
    return f".{part.value}.tmp"


#: Exactly the temporary names `_write_part` creates, keyed by name; matched by
#: whole-name equality (anchored), so `x.decoded.tmp` or `.decoded.tmp~` is not one.
_TEMPORARY_PARTS: Final[Mapping[str, ReportContentPart]] = {
    _temporary(part): part for part in ReportContentPart
}


class FilesystemReportContentStore(ReportContentStore):
    """Report content objects of one namespace, under one designated root."""

    def __init__(
        self,
        root: Path,
        namespace: ReportContentNamespace = ReportContentNamespace.CONTENT,
        *,
        source_roots: Iterable[Path] = (),
        managed_documents_root: Path | None = None,
        other_roots: Iterable[Path] = (),
    ) -> None:
        if not _ANCHORING_IS_AVAILABLE:  # pragma: no cover - every supported platform has it
            raise ReportContentRootError(
                "this platform cannot perform directory-anchored writes, so the "
                "report content store cannot hold its containment guarantee"
            )
        if namespace not in NAMESPACE_KINDS:
            raise ReportContentRootError("the report content namespace is not a known one")
        resolved = resolve_clear_root(
            Path(root),
            source_roots=source_roots,
            managed_documents_root=managed_documents_root,
            other_roots=other_roots,
        )
        self._root: Final = resolved
        self._namespace: Final = namespace
        self._kinds: Final = NAMESPACE_KINDS[namespace]

    @property
    def root(self) -> Path:
        """The resolved root. Read by operations and composition, never by a request."""
        return self._root

    @property
    def namespace(self) -> ReportContentNamespace:
        return self._namespace

    # ---- derivation ------------------------------------------------------

    def _components(self, object_id: str) -> tuple[str, str, str]:
        """`(namespace, shard, object_id)` of an admitted identifier, or a refusal."""
        if type(object_id) is not str:
            raise ReportContentStoreError("the report content object identifier is not admitted")
        try:
            kind, suffix = parse_identifier(object_id)
            if kind not in self._kinds:
                raise InvalidIdentifierError("kind")
            validate_identifier(object_id, kind)
        except (InvalidIdentifierError, ValueError):
            raise ReportContentStoreError(
                "the report content object identifier is not admitted"
            ) from None
        if suffix != suffix.lower():
            raise ReportContentStoreError("the report content object identifier is not admitted")
        return self._namespace.value, suffix[:_SHARD], object_id

    # ---- anchored directory walks ----------------------------------------

    def _open_root(self) -> int:
        try:
            return os.open(self._root, _DIRECTORY_FLAGS)
        except OSError:
            raise ReportContentStoreError("the report content root could not be opened") from None

    def _walk(self, parts: Iterable[str], *, create: bool) -> int:
        """A descriptor for `root/parts...`, each component opened `O_NOFOLLOW`.

        With `create`, each missing component is made with `mkdirat` (0700)
        relative to the level above first, and that level is `fsync`ed. A
        component that is a symbolic link (or not a directory) is refused by
        the kernel at its `openat`.
        """
        current = self._open_root()
        try:
            for part in parts:
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                    except OSError:
                        raise ReportContentStoreError(
                            "a report content directory could not be created"
                        ) from None
                    else:
                        # The new name is durable only once its parent is: the
                        # root when `<namespace>` is made, the namespace when a
                        # shard is (the shard itself is fsynced by `put`).
                        try:
                            os.fsync(current)
                        except OSError:
                            raise ReportContentStoreError(
                                "a report content directory could not be made durable"
                            ) from None
                try:
                    nested = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except FileNotFoundError:
                    raise ReportContentMissingError(
                        "the report content object is not present"
                    ) from None
                except OSError:
                    raise ReportContentStoreError(
                        "a report content location is not a directory reachable "
                        "without following a link"
                    ) from None
                os.close(current)
                current = nested
        except BaseException:
            os.close(current)
            raise
        return current

    # ---- writing ---------------------------------------------------------

    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        namespace, shard, name = self._components(object_id)
        parts: list[tuple[ReportContentPart, bytes]] = [(ReportContentPart.DECODED, decoded)]
        if original is not None:
            parts.append((ReportContentPart.ORIGINAL, original))
        shard_fd = self._walk((namespace, shard), create=True)
        object_fd: int | None = None
        created = False
        try:
            try:
                os.mkdir(name, 0o700, dir_fd=shard_fd)
            except FileExistsError:
                raise ReportContentStoreError("the report content object already exists") from None
            except OSError:
                raise ReportContentStoreError(
                    "the report content object could not be created"
                ) from None
            created = True
            try:
                object_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=shard_fd)
            except OSError:
                raise ReportContentStoreError(
                    "the report content object could not be opened"
                ) from None
            try:
                for part, data in parts:
                    self._write_part(object_fd, part, data)
                os.fsync(object_fd)
                os.fsync(shard_fd)
            except ReportContentStoreError:
                raise
            except OSError:
                raise ReportContentStoreError(
                    "the report content object could not be stored"
                ) from None
        except BaseException:
            if created:
                self._remove_partial(shard_fd, object_fd, name)
            _close(object_fd)
            os.close(shard_fd)
            raise
        _close(object_fd)
        os.close(shard_fd)

    def _write_part(self, object_fd: int, part: ReportContentPart, data: bytes) -> None:
        """Temporary (O_EXCL, 0600), write, fsync, re-read and verify, link, unlink."""
        temporary = _temporary(part)
        expected = hashlib.sha256(data).hexdigest()
        descriptor = os.open(temporary, _CREATE_FLAGS, 0o600, dir_fd=object_fd)
        try:
            view = memoryview(data)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        # Re-read what is on the device before it gets its final name.
        self._check(object_fd, temporary, expected_sha256=expected, expected_byte_count=len(data))
        os.link(
            temporary,
            part.value,
            src_dir_fd=object_fd,
            dst_dir_fd=object_fd,
            follow_symlinks=False,
        )
        os.unlink(temporary, dir_fd=object_fd)

    def _remove_partial(self, shard_fd: int, object_fd: int | None, name: str) -> None:
        """Remove everything a failed `put` created: temporaries, parts, the directory."""
        anchor = object_fd
        opened_here = False
        if anchor is None:
            try:
                anchor = os.open(name, _DIRECTORY_FLAGS, dir_fd=shard_fd)
                opened_here = True
            except OSError:
                anchor = None
        if anchor is not None:
            for part in ReportContentPart:
                for entry in (_temporary(part), part.value):
                    with suppress(OSError):
                        os.unlink(entry, dir_fd=anchor)
            if opened_here:
                os.close(anchor)
        with suppress(OSError):
            os.rmdir(name, dir_fd=shard_fd)

    # ---- reading ---------------------------------------------------------

    def read(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> bytes:
        return self._read_or_verify(
            object_id,
            part,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
            keep=True,
        )

    def verify(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> None:
        self._read_or_verify(
            object_id,
            part,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
            keep=False,
        )

    def read_range(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        offset: int,
        length: int,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> bytes:
        """WP06 T15: one range of a part, the whole part streamed through `_check`'s checks.

        The file is read in `_CHUNK_BYTES` slices; only the bytes inside
        `[offset, offset + length)` are kept, so memory is O(`length`) plus
        one slice. Nothing is returned unless the whole part verifies.
        """
        if not isinstance(part, ReportContentPart):
            raise ReportContentStoreError("the report content part is not a known one")
        if type(expected_byte_count) is not int or expected_byte_count < 0:
            raise ReportContentStoreError("the expected report content size is not admitted")
        if (
            type(offset) is not int
            or type(length) is not int
            or not 0 <= offset <= expected_byte_count
            or length < 1
        ):
            raise ReportContentStoreError("the report content range is not admitted")
        namespace, shard, name = self._components(object_id)
        object_fd = self._walk((namespace, shard, name), create=False)
        try:
            return self._check_range(
                object_fd,
                part.value,
                offset=offset,
                end=min(offset + length, expected_byte_count),
                expected_sha256=expected_sha256,
                expected_byte_count=expected_byte_count,
            )
        finally:
            os.close(object_fd)

    def _check_range(
        self,
        directory_fd: int,
        entry: str,
        *,
        offset: int,
        end: int,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> bytes:
        """`_check` keeping only `[offset, end)`: the same refusals, in the same order."""
        try:
            descriptor = os.open(entry, _READ_FLAGS, dir_fd=directory_fd)
        except OSError:
            raise ReportContentMissingError("the report content part is not readable") from None
        try:
            status = os.fstat(descriptor)
            if not S_ISREG(status.st_mode) or status.st_nlink > 1:
                raise ReportContentMissingError("the report content part is not readable")
            digest = hashlib.sha256()
            kept: list[bytes] = []
            total = 0
            while True:
                # At most one byte past the expected size is ever read.
                want = min(_CHUNK_BYTES, expected_byte_count + 1 - total)
                if want <= 0:
                    break
                chunk = os.read(descriptor, want)
                if not chunk:
                    break
                start = total
                total += len(chunk)
                digest.update(chunk)
                low = max(offset, start)
                high = min(end, total)
                if low < high:
                    kept.append(chunk[low - start : high - start])
                del chunk
        except OSError:
            raise ReportContentMissingError("the report content part is not readable") from None
        finally:
            os.close(descriptor)
        if total != expected_byte_count:
            raise ReportContentIntegrityError("size")
        if digest.hexdigest() != expected_sha256:
            raise ReportContentIntegrityError("digest")
        return b"".join(kept)

    def _read_or_verify(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
        keep: bool,
    ) -> bytes:
        if not isinstance(part, ReportContentPart):
            raise ReportContentStoreError("the report content part is not a known one")
        if type(expected_byte_count) is not int or expected_byte_count < 0:
            raise ReportContentStoreError("the expected report content size is not admitted")
        namespace, shard, name = self._components(object_id)
        object_fd = self._walk((namespace, shard, name), create=False)
        try:
            return self._check(
                object_fd,
                part.value,
                expected_sha256=expected_sha256,
                expected_byte_count=expected_byte_count,
                keep=keep,
            )
        finally:
            os.close(object_fd)

    def _check(
        self,
        directory_fd: int,
        entry: str,
        *,
        expected_sha256: str,
        expected_byte_count: int,
        keep: bool = False,
    ) -> bytes:
        """Open one file under `directory_fd`, refuse a non-plain one, verify size and digest."""
        try:
            descriptor = os.open(entry, _READ_FLAGS, dir_fd=directory_fd)
        except OSError:
            raise ReportContentMissingError("the report content part is not readable") from None
        try:
            status = os.fstat(descriptor)
            if not S_ISREG(status.st_mode) or status.st_nlink > 1:
                raise ReportContentMissingError("the report content part is not readable")
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            total = 0
            while True:
                # At most one byte past the expected size is ever read.
                want = min(_CHUNK_BYTES, expected_byte_count + 1 - total)
                if want <= 0:
                    break
                chunk = os.read(descriptor, want)
                if not chunk:
                    break
                total += len(chunk)
                digest.update(chunk)
                if keep:
                    chunks.append(chunk)
        except OSError:
            raise ReportContentMissingError("the report content part is not readable") from None
        finally:
            os.close(descriptor)
        if total != expected_byte_count:
            raise ReportContentIntegrityError("size")
        if digest.hexdigest() != expected_sha256:
            raise ReportContentIntegrityError("digest")
        return b"".join(chunks)

    def has(self, object_id: str) -> bool:
        namespace, shard, name = self._components(object_id)
        try:
            shard_fd = self._walk((namespace, shard), create=False)
        except ReportContentStoreError:
            return False
        try:
            status = os.stat(name, dir_fd=shard_fd, follow_symlinks=False)
        except OSError:
            return False
        finally:
            os.close(shard_fd)
        return S_ISDIR(status.st_mode)

    # ---- enumeration -----------------------------------------------------

    def stored_object_ids(self) -> tuple[str, ...]:
        """Every well-formed object directory's identifier, whatever its parts hold.

        An object whose parts are malformed is still stored (a row naming it is
        then reported missing or mismatched by the scan, an object no row names
        an orphan); its malformed entries are `unreadable_entries`.
        """
        return tuple(sorted(name for name, _problems, _stale in self._scan() if name is not None))

    def unreadable_entries(self) -> tuple[str, ...]:
        """Entries that are not well-formed objects or parts, relative to the root.

        Operational information for the operator who configured the root;
        never returned to a request.
        """
        return tuple(
            sorted(problem for _name, problems, _stale in self._scan() for problem in problems)
        )

    def stale_temporaries(self) -> tuple[str, ...]:
        """This store's own `put` temporaries a killed process left, relative to the root.

        Reports Modernization WP08 (WP05b corrective n2). A `put` killed by a
        signal (not an exception, which `_remove_partial` cleans up) can leave
        `.decoded.tmp` / `.original.tmp` in its object directory. Exactly those
        names, as regular files inside a well-formed object directory, are
        reported here and NOT as unreadable entries; anything else unrecognised
        stays unreadable. Nothing is removed: the operator moves one aside by
        hand (see the runbook). Whether a referenced object's final parts are
        intact is decided by `verify`, never by this classification.
        """
        return tuple(sorted(item for _name, _problems, stale in self._scan() for item in stale))

    def _admitted(self, shard: str, name: str) -> bool:
        try:
            _ns, derived_shard, _ = self._components(name)
        except ReportContentStoreError:
            return False
        return derived_shard == shard

    def _scan(self) -> Iterator[tuple[str | None, tuple[str, ...], tuple[str, ...]]]:
        """Walk the tree: `(object id or None, unreadable names, stale temporaries)`.

        Never follows a link (`follow_symlinks=False` throughout). An object
        directory whose parts are malformed is still yielded with its id, and
        each malformed entry is reported relative to the root.
        """
        base = self._root / self._namespace.value
        try:
            if base.is_symlink() or not base.is_dir():
                if base.exists() or base.is_symlink():
                    yield None, (self._namespace.value,), ()
                return
            shards = sorted(os.scandir(base), key=lambda entry: entry.name)
        except OSError:
            yield None, (self._namespace.value,), ()
            return
        for shard in shards:
            relative = f"{self._namespace.value}/{shard.name}"
            if not shard.is_dir(follow_symlinks=False) or len(shard.name) != _SHARD:
                yield None, (relative,), ()
                continue
            try:
                objects = sorted(os.scandir(shard.path), key=lambda entry: entry.name)
            except OSError:
                yield None, (relative,), ()
                continue
            for item in objects:
                item_relative = f"{relative}/{item.name}"
                if not item.is_dir(follow_symlinks=False) or not self._admitted(
                    shard.name, item.name
                ):
                    yield None, (item_relative,), ()
                    continue
                problems, stale = self._object_problems(item.path, item_relative)
                yield item.name, problems, stale

    def _object_problems(self, path: str, relative: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """One object directory's `(unreadable entries, stale temporaries)`.

        A stale temporary is a regular file named exactly as `_write_part`
        names one. Its presence also explains the two states a killed `put`
        leaves around it, which are then not unreadable: a final part not yet
        linked (the temporary exists, the part does not), and a final part
        linked but its temporary not yet unlinked (the same inode, two links).
        `read`/`verify` still refuse both, so a referenced object in either
        state remains an integrity finding of the scan that verifies it.
        """
        try:
            entries = {entry.name: entry for entry in os.scandir(path)}
        except OSError:
            return (relative,), ()
        problems: list[str] = []
        stale: list[str] = []
        temporaries: dict[ReportContentPart, os.stat_result] = {}
        for entry_name, part in _TEMPORARY_PARTS.items():
            entry = entries.get(entry_name)
            if entry is None:
                continue
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if S_ISREG(status.st_mode):
                temporaries[part] = status
                stale.append(f"{relative}/{entry_name}")
        if (
            ReportContentPart.DECODED.value not in entries
            and ReportContentPart.DECODED not in temporaries
        ):
            problems.append(f"{relative}/{ReportContentPart.DECODED.value}")
        for entry_name, entry in sorted(entries.items()):
            entry_relative = f"{relative}/{entry_name}"
            if entry_name in _TEMPORARY_PARTS:
                if _TEMPORARY_PARTS[entry_name] not in temporaries:
                    problems.append(entry_relative)
                continue
            if entry_name not in _PART_NAMES:
                problems.append(entry_relative)
                continue
            try:
                status = entry.stat(follow_symlinks=False)
            except OSError:
                problems.append(entry_relative)
                continue
            if not S_ISREG(status.st_mode):
                problems.append(entry_relative)
                continue
            if status.st_nlink > 1:
                temporary = temporaries.get(ReportContentPart(entry_name))
                linked_to_its_temporary = (
                    status.st_nlink == 2
                    and temporary is not None
                    and (temporary.st_dev, temporary.st_ino) == (status.st_dev, status.st_ino)
                )
                if not linked_to_its_temporary:
                    problems.append(entry_relative)
        return tuple(problems), tuple(sorted(stale))
