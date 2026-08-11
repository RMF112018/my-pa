"""The managed byte store: the only module in this product that writes owned bytes.

This is the release-blocking control of WP-27. Everything the campaign has
protected — source authority, provenance, immutability — depends on this plane
never touching a source root, so containment here is structural rather than
validated.

**There is no path parameter, and that is the whole design.** Every public method
takes an opaque `mdver_…` identifier or nothing at all. The location of a
version's bytes is *derived here* from that identifier, by sharding its suffix,
and a caller has no way to express a location. A traversal attack needs somewhere
to put `..`, an absolute path, or a symlink name; there is no argument it could
travel in. String validation would be a check a future caller could route around
by adding a second entry point — this cannot be routed around, because the
capability to name a location does not exist on the interface.

That is the first layer. The rest exist because the first one assumes the
identifier is well formed and the filesystem is not hostile, and neither is worth
assuming:

* **The root is resolved once, at construction.** `Path.resolve()` collapses
  every `..`, every symlink and every spelling into the one location the kernel
  would reach, and the result is what every later comparison is made against. A
  root that does not already exist, is not a directory, or is itself a symlink is
  refused: creating one would mean this class deciding where the managed plane
  lives, and following one would mean the operator's configured location and the
  location actually written differing by a link somebody else controls.
* **The root may not be, contain, or sit inside a configured source root.**
  Compared after full resolution on both sides, so a managed root that is a
  symlink into a source tree is refused by the same check as one spelled that
  way. This is `AGENTS.md` section 4's "managed-document writes occur only in
  designated managed storage" as a constructor refusal.
* **Every derived location is re-proved to be under the root.** Redundant while
  the derivation is correct, which is exactly why it is here: it is the check
  that survives a future edit to the derivation.
* **No component of a derived path may be an existing symlink.** `Path.resolve`
  on the final target would follow one; refusing the whole chain is what stops a
  link planted inside the root from redirecting a write outside it.
* **Writes are create-exclusive at both ends, and never follow a link.**
  `O_CREAT | O_EXCL` on the temporary refuses a leftover part-file rather than
  overwriting it; `os.link` publishes the object and fails outright if that
  location is already taken, so "a version's bytes are written once" is a
  property of the syscall rather than of an `exists()` check with a window in it.
  `O_NOFOLLOW` refuses a final component that became a symlink between the check
  and the open.
* **Every write and every read is performed relative to a directory descriptor
  (WP-28).** The chain from the root down is opened one component at a time with
  `O_DIRECTORY | O_NOFOLLOW`, and the create, the link, the unlink and the read
  are then `openat`/`linkat`/`unlinkat` against the descriptor that walk
  produced. After the walk returns there is no path component left for anything
  to swap, which is what closes the check-to-syscall window recorded below.

**Durability, and the failure window it leaves.** A write goes to a temporary
file inside the root, is `fsync`ed, and is then linked onto the derived
location — an atomic operation within one filesystem — and the containing
directory is `fsync`ed so the rename itself survives a crash. The caller inserts
metadata and commits *after* this returns. That ordering is chosen so the
surviving failure mode is the safe one: a crash between the rename and the commit
leaves **bytes with no row**, which `orphaned_version_ids` finds and an operator
reclaims, and never **a row naming absent bytes**, which no reconciliation can
repair. The window is real, it is stated here and in
`ops/runbooks/managed-document-operations.md`, and this module claims no atomicity
across the filesystem and the database because there is none.

**Reads are read-only and refuse a link too.** `O_RDONLY | O_NOFOLLOW`, the same
component check, and the same directory descriptor the writes use, so a stored
object swapped for a link to a source file reads as a refusal rather than as the
source file's contents.

**What this does not close, stated rather than left to be found.** A bind mount
or any filesystem mounted inside the resolved root exposes an outside subtree at
a path that genuinely is inside it, and no amount of resolution reveals that.
Mounting requires privileges that defeat this boundary by other means, so it sits
outside the threat model — the same conclusion, for the same reason,
`infrastructure.providers.fixture` records for the read side. A hard link inside
the root pointing at a file outside it is refused on the write side by the
publishing link (the target must not exist) and on the read side by the link
count of the open descriptor.

**The intermediate-component window WP-27 disclosed is closed, and here is
exactly what "closed" means.** WP-27 shipped with `_verify_contained` checking a
chain *by name* and the syscall that followed resolving the same chain by name a
second time; a directory component replaced by a symlink inside that interval
sent the write outside the resolved root — transiently by way of `incoming/` and
durably by way of a swapped `objects/<shard>` — while `put` reported success. It
was reproduced twice with real bytes. WP-28 implements the remedy WP-27 recorded:
the chain is walked once with `O_DIRECTORY | O_NOFOLLOW`, holding a descriptor at
each level, and every subsequent syscall is anchored to that descriptor. A
descriptor names an inode; a swap after it is held changes nothing the call can
reach. `tests/security/test_managed_store_toctou.py` reproduces the attack at the
exact instant the window opens, shows the *previous* publication landing bytes
outside the root under that attack, and shows this one refusing it.

**What that claim does not extend to, said plainly rather than implied away.**
The *root itself* is opened by name, and it is the one component no descriptor
sits above. It is opened afresh by every anchored step rather than once per
public call: a single `put` opens it **five** times — once in each of the two
`_ensure_directory` calls, once in `_write_exclusive`'s `_anchored`, and twice
more inside `_publish`. That count does not change the security statement and is
written down because "once per operation" was wrong and a reader counting
syscalls would find it so. A root replaced between any two of those opens is a
different root, and the constructor's refusal of a symlinked root plus the fact
that replacing it needs the same local write access as replacing any component is
the whole of what stands there. A platform that cannot perform a syscall relative
to a directory descriptor cannot hold this guarantee at all, and this module
**refuses rather than reverting** to name-based syscalls, so such a build fails
loudly instead of silently holding a weaker property. And the precondition for
the original attack is unchanged and was never the point: it always required
write access inside the product's own managed root, as the UID this product runs
as.

**What no test here can isolate, measured rather than asserted.** Three of the
layers above are redundant with one another for every case a test can construct,
and each was *measured* by removing it and watching the suite stay green: the
resolved-parent comparison in `_verify_contained` (the component walk refuses the
same cases first), `O_NOFOLLOW` on the read (the component walk again), and
`O_NOFOLLOW` on the create. They are kept because each closes a window the others
cannot — the *final* component swapped between the walk and the `open`, and a
derivation a later edit changes — and
`tests/security/test_managed_document_containment.py` records the measurement
rather than implying coverage that does not exist.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from pathlib import Path
from stat import S_ISREG
from typing import Final

from my_pa.contracts.ports import ManagedByteStore
from my_pa.domain.common.identifiers import IdKind, parse_identifier, validate_identifier

__all__ = [
    "FilesystemManagedByteStore",
    "ManagedRootError",
    "ManagedStoreError",
    "StoredBytesMissingError",
]


class ManagedStoreError(Exception):
    """Base class for every refusal this store makes."""


class ManagedRootError(ManagedStoreError):
    """The configured root is unusable, or overlaps a root it must stay clear of.

    Two callers pass `source_roots`, and the message covers both: a live store is
    given the configured read-only source roots, and a backup destination is
    given those *and* the live managed root, so "back up in place" is refused by
    the same check.

    A configuration defect rather than a denial, and reported as one: hiding it
    behind an uninformative message would leave an operator unable to tell a
    misconfigured plane from an empty one.
    """


class StoredBytesMissingError(ManagedStoreError):
    """A version's bytes are not in the store, or are not a plain readable file."""


#: Where objects live under the root. A fixed component, so the root can also
#: hold the operational artifacts below without either being able to collide
#: with an object.
_OBJECTS: Final = "objects"

#: Where a write lands before it is renamed into place. Inside the root, because
#: an atomic rename requires one filesystem and a temporary directory elsewhere
#: is a different one.
_INCOMING: Final = "incoming"

#: The one artifact a backup carries besides bytes: the metadata manifest. A
#: fixed name inside the root, for the reason objects are sharded from an
#: identifier — a caller-supplied file name is a path parameter wearing another
#: word, and this module has none.
_MANIFEST: Final = "manifest.json"

#: How many characters of the identifier suffix name each shard level. Two levels
#: of two hexadecimal characters is 65,536 leaf directories, which keeps any one
#: directory small without making the tree deep enough to walk slowly.
_SHARD: Final = 2

#: `O_NOFOLLOW` is absent on some platforms; treated as zero rather than assumed.
_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)

#: How a version's bytes are created. Create-exclusive, so a second write to the
#: same identifier fails rather than overwrites; write-only, so this descriptor
#: cannot be read through; and never following a final-component link.
_CREATE_FLAGS: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW

#: How a version's bytes are read. Read-only, and the same refusal to follow a
#: link that was swapped in for a stored object.
_READ_FLAGS: Final = os.O_RDONLY | _NOFOLLOW

#: Bytes per `os.read`. A ceiling on one syscall's buffer, not on the read.
_CHUNK_BYTES: Final = 1 << 20

#: How a directory is opened when it is going to be used as an anchor. Read-only,
#: refusing anything that is not a directory, and refusing a final component that
#: is a symbolic link. Every component of the chain is opened with these flags, so
#: a link anywhere between the root and a shard is refused by the kernel rather
#: than by a check the kernel is not party to.
_DIRECTORY_FLAGS: Final = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | _NOFOLLOW

#: Whether this platform can perform a syscall relative to a directory
#: descriptor. Checked rather than assumed, and checked per operation: `dir_fd`
#: support is per function in CPython and per system call underneath it.
#:
#: **This is a capability check, not a fallback switch.** A platform without it
#: cannot close the intermediate-component window at all, and this module refuses
#: to *pretend* it did: `_anchored` raises rather than quietly reverting to
#: name-based syscalls, so a build that cannot hold the guarantee fails loudly
#: instead of silently holding a weaker one. Every platform this product is built
#: for has it; the check exists so that a platform that does not is a startup
#: failure rather than a security regression.
_ANCHORING_IS_AVAILABLE: Final = all(
    call in os.supports_dir_fd for call in (os.open, os.link, os.unlink, os.mkdir, os.stat)
)


def _resolved_directory(candidate: Path, what: str) -> Path:
    """Resolve an existing real directory, or refuse.

    `is_symlink` is asked *before* resolution, on the path as configured: a
    symlinked root resolves perfectly well to somewhere else entirely, and
    accepting it would mean the location an operator configured and the location
    this process writes are two different places joined by a link the operator
    may not control.
    """
    try:
        if candidate.is_symlink():
            raise ManagedRootError(f"the configured {what} is a symbolic link")
        resolved = candidate.resolve(strict=True)
    except ManagedRootError:
        raise
    except (OSError, RuntimeError):
        # Including a looping path, which `Path.resolve` reports as a
        # `RuntimeError` naming it. Re-raised without the original attached: an
        # `OSError` renders with the path it failed on, and a message carrying a
        # filesystem path is a habit this repository does not keep.
        raise ManagedRootError(f"the configured {what} could not be resolved") from None
    if not resolved.is_dir():
        raise ManagedRootError(f"the configured {what} is not an existing directory")
    return resolved


def _overlaps(one: Path, other: Path) -> bool:
    """Whether two resolved paths name the same tree or one inside the other."""
    return one == other or one.is_relative_to(other) or other.is_relative_to(one)


class FilesystemManagedByteStore(ManagedByteStore):
    """Bytes for managed document versions, under one designated root.

    Construction is where the boundary is drawn. Everything after it operates on
    opaque identifiers, so a wired store is a store that cannot be pointed
    anywhere else by anything a request carries.
    """

    def __init__(self, root: Path, *, source_roots: Iterable[Path] = ()) -> None:
        resolved = _resolved_directory(Path(root), "managed document root")
        for source_root in source_roots:
            # A source root that has gone missing is *not* a reason to admit the
            # managed root: an unresolvable source root is compared as configured
            # rather than skipped, so a removed directory cannot be used to slip
            # an overlapping managed root past this check.
            try:
                compared = Path(source_root).resolve()
            except (OSError, RuntimeError):
                compared = Path(source_root).absolute()
            if _overlaps(resolved, compared):
                raise ManagedRootError(
                    "the managed document root is the same tree as a root it must "
                    "stay clear of, or lies inside one, or contains one — a "
                    "configured read-only source root, and for a backup "
                    "destination the live managed root as well"
                )
        self._root: Final = resolved

    @property
    def root(self) -> Path:
        """The resolved managed root. Read by operations, never by a request path."""
        return self._root

    # ---- writing ---------------------------------------------------------

    def put(self, version_id: str, content: bytes) -> None:
        """Store `content` as the bytes of `version_id`, durably, exactly once.

        Returns after the bytes are on the device and the rename that named them
        is on the device. A second call for the same identifier raises: bytes are
        written once, and an overwrite is the operation this plane does not have.

        **The temporary is removed on some failures and not on others, and the
        difference is which exception the failure arrives as.** The `_publish`
        call below is wrapped for `FileExistsError` and `OSError`, and both of
        those discard it. A refusal raised as `ManagedStoreError` is not caught
        here: `_anchored` raises one when a component of the chain is not a
        directory reachable without following a link, and WP-28 put two
        `_anchored` calls inside `_publish` — so that refusal propagates with the
        `.part` file still in `incoming/`. A process killed between the write and
        the publication leaves one for the same reason.

        What survives is an orphan **inside** the root: bytes carrying no object
        name, named by no row, and unreadable as a version. `verify` reports it
        under `unreadable_entries`, which lists every file in `incoming/` — not
        under `orphaned_version_ids`, which is derived from the object tree alone
        and never sees `incoming/` at all. Nothing reclaims it automatically.
        That is WP-27's already-disclosed model for orphaned bytes rather than a
        new failure mode, and `tests/security/test_managed_store_toctou.py`
        asserts the surviving temporary rather than asserting it away.
        """
        target = self._object_path(version_id)
        self._ensure_directory(target.parent)
        incoming = self._root / _INCOMING
        self._ensure_directory(incoming)
        temporary = incoming / f"{self._suffix(version_id)}.part"
        self._write_exclusive(temporary, content)
        try:
            self._publish(temporary, target)
        except FileExistsError:
            self._discard(temporary)
            raise ManagedStoreError("the managed object already exists") from None
        except OSError:
            self._discard(temporary)
            raise ManagedStoreError("the managed object could not be stored") from None

    def put_manifest(self, content: bytes) -> None:
        """Store the backup manifest at the root's one fixed artifact location.

        Used by the backup path, which writes bytes and one metadata document. A
        fixed constant rather than a name, because a name is a path parameter and
        this module accepts none.
        """
        target = self._root / _MANIFEST
        self._verify_contained(target)
        incoming = self._root / _INCOMING
        self._ensure_directory(incoming)
        temporary = incoming / f"{_MANIFEST}.part"
        self._discard(temporary)
        self._write_exclusive(temporary, content)
        try:
            self._publish(temporary, target, replace=True)
        except OSError:
            self._discard(temporary)
            raise ManagedStoreError("the managed manifest could not be stored") from None

    # ---- reading ---------------------------------------------------------

    def read(self, version_id: str) -> bytes:
        """Return the stored bytes of `version_id`, or refuse.

        Absent, not a regular file, carrying a second name, or replaced by a link
        are one refusal. A caller that reached here already knows the version
        exists — it read the row — so nothing is disclosed by the answer, and
        collapsing them keeps this from becoming a way to probe the store's
        layout.
        """
        path = self._object_path(version_id)
        descriptor = self._open_anchored(path, _READ_FLAGS)
        if descriptor is None:
            raise StoredBytesMissingError("the managed object's bytes are not readable")
        try:
            status = os.fstat(descriptor)
            if not S_ISREG(status.st_mode) or status.st_nlink > 1:
                # The link count is the hard-link refusal, asked of the open
                # descriptor rather than of the name, for the reason
                # `providers.fixture.fetch` asks it there: a second name for this
                # inode may be outside the root, and no resolution reveals it.
                raise StoredBytesMissingError("the managed object's bytes are not readable")
            return self._read_all(descriptor)
        finally:
            os.close(descriptor)

    def read_manifest(self) -> bytes:
        """Return the backup manifest stored at the root's fixed artifact location."""
        path = self._root / _MANIFEST
        self._verify_contained(path)
        descriptor = self._open_anchored(path, _READ_FLAGS)
        if descriptor is None:
            raise StoredBytesMissingError("the managed manifest is not readable")
        try:
            return self._read_all(descriptor)
        finally:
            os.close(descriptor)

    def has(self, version_id: str) -> bool:
        """Whether `version_id`'s bytes are present as a plain file."""
        path = self._object_path(version_id)
        try:
            anchor = self._anchored(path.parent)
        except ManagedStoreError:
            return False
        try:
            status = os.stat(path.name, dir_fd=anchor, follow_symlinks=False)
        except OSError:
            return False
        finally:
            os.close(anchor)
        return S_ISREG(status.st_mode)

    def stored_version_ids(self) -> tuple[str, ...]:
        """Every version identifier the store currently holds bytes for.

        Read by the integrity check and the backup. Built by walking the object
        tree and re-deriving each identifier from the file name, so an entry that
        is not a well-formed managed version identifier is reported by
        `orphaned_version_ids` rather than silently skipped.
        """
        return tuple(sorted(self._walk_objects()))

    def unreadable_entries(self) -> tuple[str, ...]:
        """Object-tree entries that are not well-formed managed version objects.

        Names them relative to the root, which is operational information for the
        operator who configured that root and is never returned to a request.
        """
        found: list[str] = []
        objects = self._root / _OBJECTS
        if not objects.is_dir():
            return ()
        for entry in sorted(objects.rglob("*")):
            if entry.is_dir():
                continue
            try:
                parse_identifier(entry.name)
            except ValueError:
                found.append(str(entry.relative_to(self._root)))
                continue
            if not entry.name.startswith(f"{IdKind.MANAGED_DOCUMENT_VERSION.value}_"):
                found.append(str(entry.relative_to(self._root)))
        incoming = self._root / _INCOMING
        if incoming.is_dir():
            found.extend(
                str(entry.relative_to(self._root))
                for entry in sorted(incoming.iterdir())
                if entry.is_file()
            )
        return tuple(found)

    # ---- derivation and containment --------------------------------------

    def _suffix(self, version_id: str) -> str:
        """The opaque suffix of a validated managed version identifier.

        Validation is the gate: `validate_identifier` admits only 8-64
        alphanumeric characters after the prefix, so the value returned here
        cannot contain a separator, a dot, a null byte, or a Unicode form that
        normalises into one. Everything below builds path components out of this
        string alone.
        """
        validate_identifier(version_id, IdKind.MANAGED_DOCUMENT_VERSION)
        _kind, suffix = parse_identifier(version_id)
        return suffix

    def _object_path(self, version_id: str) -> Path:
        """Where `version_id`'s bytes live. Derived here; never supplied.

        Two shard levels taken from the front of the suffix, then the identifier
        itself as the file name. The identifier is used whole so that a file
        found in the tree can be turned back into the version it belongs to,
        which is what makes reconciliation possible without a second index.
        """
        suffix = self._suffix(version_id)
        path = (
            self._root
            / _OBJECTS
            / suffix[:_SHARD]
            / suffix[_SHARD : _SHARD * 2]
            / f"{IdKind.MANAGED_DOCUMENT_VERSION.value}_{suffix}"
        )
        self._verify_contained(path)
        return path

    def _verify_contained(self, path: Path) -> None:
        """Prove a derived location is inside the root, and reached through no link.

        Two separate claims, and both are needed. Containment is checked against
        the *resolved* parent chain, so a comparison is between locations rather
        than between spellings. The link check walks every component between the
        root and the target and refuses any that already exists as a symbolic
        link, which is what `Path.resolve` on the target alone would silently
        follow.

        Redundant while `_object_path` is correct. That is the point: this is the
        check that outlives an edit to the derivation.
        """
        try:
            relative = path.relative_to(self._root)
        except ValueError:
            raise ManagedStoreError("the derived managed location is outside the root") from None
        current = self._root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise ManagedStoreError(
                    "the derived managed location is reached through a symbolic link"
                )
        try:
            settled = current.parent.resolve(strict=False)
        except (OSError, RuntimeError):
            raise ManagedStoreError("the derived managed location could not be resolved") from None
        if not (settled == self._root or settled.is_relative_to(self._root)):
            raise ManagedStoreError("the derived managed location is outside the root")

    # ---- the syscalls ----------------------------------------------------
    #
    # **Every write and every read below is performed relative to a directory
    # descriptor, and that is what closes WP-27's disclosed TOCTOU window.**
    #
    # The window was this. `_verify_contained` walks the components between the
    # root and a target and refuses any that is already a symbolic link — a real
    # check, and one made *by name*. The syscall that followed was also made by
    # name, so the kernel resolved every component a second time; a directory
    # component swapped for a symlink in between landed the write outside the
    # root while `put()` reported success. `O_NOFOLLOW` constrains only the
    # **final** component and `Path.hardlink_to` carries no link protection at
    # all, so neither covered it. It was reproduced twice with real bytes.
    #
    # The remedy is the one WP-27 recorded: resolve the chain **once**, holding a
    # descriptor for each directory as it is opened, and then perform the create,
    # the link and the unlink with `openat`/`linkat`/`unlinkat` relative to that
    # descriptor. A descriptor names an inode, not a path, so after `_anchored`
    # returns there is no component left for anything to swap — the name the
    # kernel resolves is a single leaf inside a directory this process is already
    # holding open.
    #
    # **Every existing layer is kept, and none of them is now redundant.** The
    # component walk and the resolved-parent comparison still run first and still
    # refuse a link that is *already* there, which is the common case and the one
    # that produces a clear refusal rather than an `ENOTDIR`. `O_EXCL` still makes
    # a second write fail rather than overwrite. `linkat` still fails outright on
    # an existing target, which is what makes byte-level immutability a property
    # of the call. `O_NOFOLLOW` still refuses a final component that became a
    # link. The `st_nlink` read refusal still refuses an object carrying a second
    # name. What anchoring adds is the one thing none of them could: the
    # guarantee that the directory the syscall acts in is the directory that was
    # checked.
    #
    # **What this does not close, stated exactly.** The *root itself* is opened by
    # name — once for every anchored step rather than once per public call, which
    # is five times during a single `put` — so a root swapped between any two of
    # those opens is a different root. Unchanged from before, and covered by the
    # constructor's refusal of a symlinked root plus the fact that replacing the
    # configured root requires the same local write access as replacing any
    # component. And a component swapped *before* `_anchored` opens it is not a
    # race at all: it is a link that is already there, which the walk refuses.

    def _anchored(self, directory: Path) -> int:
        """A descriptor for `directory`, opened one component at a time from the root.

        Each component is opened with `O_DIRECTORY | O_NOFOLLOW` relative to the
        descriptor of the one above it, so a symbolic link anywhere in the chain
        is refused by the kernel. The caller owns the returned descriptor and
        must close it.

        The root is opened by name — there is nothing above it to anchor against —
        and it is the one component this cannot cover; see the section comment.
        """
        if not _ANCHORING_IS_AVAILABLE:  # pragma: no cover - every supported platform has it
            raise ManagedStoreError(
                "this platform cannot perform a directory-anchored write, so the "
                "managed store cannot hold its containment guarantee"
            )
        try:
            relative = directory.relative_to(self._root)
        except ValueError:
            raise ManagedStoreError("the derived managed location is outside the root") from None
        # The root itself has no components below the root, and
        # `_verify_contained` is a statement about a *derived* location: asked of
        # the root it would compare the root's own parent, which is outside by
        # construction. `put_manifest` anchors on the root, which is the one call
        # that reaches this branch.
        if relative.parts:
            self._verify_contained(directory)
        try:
            current = os.open(self._root, _DIRECTORY_FLAGS)
        except OSError:
            raise ManagedStoreError("the managed root could not be opened") from None
        for part in relative.parts:
            try:
                nested = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            except OSError:
                os.close(current)
                raise ManagedStoreError(
                    "the derived managed location is not a directory reachable "
                    "without following a link"
                ) from None
            os.close(current)
            current = nested
        return current

    def _ensure_directory(self, path: Path) -> None:
        """Create one derived directory chain, refusing a link at any component.

        Each level is created with `mkdirat` relative to the level above, so the
        directory a component is created *in* is one this process is holding open
        rather than one the kernel is asked to find again by name.
        """
        self._verify_contained(path)
        try:
            relative = path.relative_to(self._root)
        except ValueError:
            raise ManagedStoreError("the derived managed location is outside the root") from None
        try:
            current = os.open(self._root, _DIRECTORY_FLAGS)
        except OSError:
            raise ManagedStoreError("the managed root could not be opened") from None
        try:
            for part in relative.parts:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    # Already there, which is the ordinary case. It is opened
                    # below with `O_NOFOLLOW`, so an existing *link* by that name
                    # is refused there rather than accepted here.
                    pass
                except OSError:
                    raise ManagedStoreError("the managed directory could not be created") from None
                try:
                    nested = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
                except OSError:
                    raise ManagedStoreError(
                        "the derived managed location is not a directory reachable "
                        "without following a link"
                    ) from None
                os.close(current)
                current = nested
        finally:
            os.close(current)

    def _write_exclusive(self, path: Path, content: bytes) -> None:
        """Create `path`, write `content`, and put both on the device.

        `openat` relative to the parent's descriptor, so the only name the kernel
        resolves for this call is the leaf.
        """
        self._verify_contained(path)
        anchor = self._anchored(path.parent)
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(path.name, _CREATE_FLAGS, 0o600, dir_fd=anchor)
            except FileExistsError:
                raise ManagedStoreError("the managed object already exists") from None
            except OSError:
                raise ManagedStoreError("the managed object could not be created") from None
            try:
                written = 0
                view = memoryview(content)
                while written < len(view):
                    written += os.write(descriptor, view[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            os.close(anchor)

    def _publish(self, temporary: Path, target: Path, *, replace: bool = False) -> None:
        """Put a fsynced temporary at its derived location, exclusively, and durably.

        **An object is published by `linkat`, not by a rename, and the difference
        is the whole of byte-level immutability.** `rename` replaces an existing
        name silently on POSIX, so a rename guarded by a preceding `exists()`
        check is a check-then-act with a window in it — and the check, not the
        syscall, would be what refused a second write. `os.link` fails with
        `FileExistsError` when the target is already there, atomically and with no
        window, so "a version's bytes are written once" is a property of the call
        rather than of a guard in front of it. The temporary is unlinked
        afterwards, leaving the object with exactly one name, which is what the
        read path's link-count refusal requires.

        Both ends are anchored — `src_dir_fd` for the temporary and `dst_dir_fd`
        for the object — so neither the `incoming` directory nor the shard is
        resolved by name again after `_verify_contained` returned.
        `follow_symlinks=False` refuses a *source* that has become a link, which
        `Path.hardlink_to` could not express at all.

        `replace` is true only for the manifest, which a later backup is meant to
        supersede; it is the one call here that may land on an existing name, and
        it uses `renameat` for exactly that.
        """
        self._verify_contained(target)
        source_anchor = self._anchored(temporary.parent)
        try:
            target_anchor = self._anchored(target.parent)
        except ManagedStoreError:
            os.close(source_anchor)
            raise
        try:
            if replace:
                os.rename(
                    temporary.name, target.name, src_dir_fd=source_anchor, dst_dir_fd=target_anchor
                )
            else:
                os.link(
                    temporary.name,
                    target.name,
                    src_dir_fd=source_anchor,
                    dst_dir_fd=target_anchor,
                    follow_symlinks=False,
                )
                os.unlink(temporary.name, dir_fd=source_anchor)
            os.fsync(target_anchor)
        finally:
            os.close(target_anchor)
            os.close(source_anchor)

    def _discard(self, temporary: Path) -> None:
        """Remove a temporary this method created, ignoring an already-absent one."""
        self._verify_contained(temporary)
        anchor = self._anchored(temporary.parent)
        try:
            os.unlink(temporary.name, dir_fd=anchor)
        except FileNotFoundError:
            return
        finally:
            os.close(anchor)

    def _open_anchored(self, path: Path, flags: int) -> int | None:
        """Open one derived file relative to its parent's descriptor, or `None`.

        The read half of the same remedy. `None` rather than an exception for the
        same reason `read` collapses its three absences into one: a caller that
        reached here already knows the version exists, so distinguishing "absent"
        from "not a regular file" from "reached through a link" would be a way to
        probe the store's layout.
        """
        try:
            anchor = self._anchored(path.parent)
        except ManagedStoreError:
            return None
        try:
            return os.open(path.name, flags, dir_fd=anchor)
        except OSError:
            return None
        finally:
            os.close(anchor)

    def _read_all(self, descriptor: int) -> bytes:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, _CHUNK_BYTES)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)

    def _walk_objects(self) -> Iterator[str]:
        objects = self._root / _OBJECTS
        if not objects.is_dir():
            return
        for entry in objects.rglob("*"):
            if not entry.is_file() or entry.is_symlink():
                continue
            try:
                kind, _suffix = parse_identifier(entry.name)
            except ValueError:
                continue
            if kind is IdKind.MANAGED_DOCUMENT_VERSION:
                yield entry.name
