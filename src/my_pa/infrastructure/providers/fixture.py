"""A read-only `SourceProvider` over one local directory of synthetic fixtures.

This is the MCV's only source provider. It reads a configured filesystem root
and nothing else. It is not a NAS provider, it holds no credentials, and it
reaches no live personal source: `P00-OD-009` gates real source roots to the
operator and is open, so the roots this is pointed at are `fixtures/mcv/root`
and pytest's `tmp_path`.

**Read-only by omission.** The port defines no write, move, rename, or delete
method, and this adapter adds none. There is no `read_only` flag to set wrongly;
`INV-PKL-001` holds because the capability is absent, not because a boolean is
`True`. The only syscalls here that touch the source are `stat`, `iterdir`, and
an `O_RDONLY` open.

**Containment.** Every path that leaves this module for the filesystem passes
`resolve_within`, which resolves both the root and the candidate and then
requires the resolved candidate to lie inside the resolved root. Resolution is
what makes it general: a `..` segment, an absolute path, a symlink to an
absolute or relative location outside, and a directory symlink all collapse to
the location that would actually be opened, and are then compared as paths
rather than as strings. Containment is proved again immediately before `fetch`
opens the object, on the same path the open then uses -- see `fetch` for why the
gap between minting an identifier and opening a descriptor is the whole problem.

Resolution is *not* total, and an overclaim here is the sentence that would ship
a hole. What a resolved path cannot see, and what is done about each:

- **A hard link.** A second name for an inode is not a link `realpath` can
  follow; a hard link inside the root to a file outside it resolves to a path
  inside the root and is admitted by every check above. It is refused instead by
  its link count, on the open descriptor, in `fetch`, and by name in `_observe`.
  This refuses *legitimate* hard links too, including two names inside the root
  for one file. That is the correct trade at a read-only boundary: the check
  cannot tell which of an inode's names are inside the root without walking the
  whole volume, so it refuses the ambiguity rather than resolving it in the
  caller's favour, and a source that needs hard links can be de-duplicated
  before it is enrolled.
- **A bind mount, or any filesystem mounted inside the root.** It exposes an
  outside subtree at a path that genuinely is inside the root, and no amount of
  resolution reveals it. This is **not** handled here, for two reasons worth
  separating. Mounting requires privileges that already defeat this boundary by
  other means, so it sits outside the threat model the rest of this module is
  built for -- an adversary who can write *inside* the root, which is what the
  symlink and hard-link cases assume. And the obvious defence, refusing objects
  whose device differs from the root's, would also refuse a legitimate share
  mounted below an approved root, which is exactly the shape a future live
  source takes. `P00-OD-009` gates live roots to the operator and is open; the
  roots this provider is pointed at today are `fixtures/mcv/root` and
  `tmp_path`. Stated so the decision to leave it is visible rather than absent.
- **The instant after resolution.** See step 2 of `fetch`.

**Denial does not discriminate.** Absent, outside the root, never issued, not a
regular file: every one of them raises `TraversalDeniedError` carrying the same
sentence and the opaque object identifier. A caller cannot subtract one outcome
from another to learn that something exists (`docs/specs` section 10, the
`not_found` row). No message here carries a path, a host, or a resolved
location, and no `OSError` survives into the exception that is raised. That last
point is finer than it looks. `raise ... from None` sets `__cause__` to `None`
but leaves the original exception in `__context__`, and an `OSError` renders as
"No such file or directory: '/the/path/it/failed/on'". So every denial below is
raised *outside* the `except` block that observed the failure, which is what
actually leaves `__context__` empty. A test asserts it, because the difference
between the two spellings is invisible on inspection.

**Unavailable is not denied, and neither leaks the other's information.** A
refusal and a resource shortage are different rows of the section 10 table:
`denied` is retryable only when authority changes, `unavailable` is
conditionally retryable, and `INV-PKL-007` forbids converting one into the
other. `fetch` therefore classifies the failure of its `open` by errno rather
than folding every `OSError` into a refusal -- see `_is_unavailable` for the
list and for why the *default* is denial.

Widening a class that a caller can distinguish is where an existence oracle
would come from, so it is worth stating exactly why this one is not. Three
things hold it closed. The classification runs only in `fetch`, and `fetch` is
reached only for an identifier this instance issued *and* observed: containment,
issuance, and prior observation are all proved before the `open` is attempted,
so a caller who reaches this code already knows the object existed. Every
unavailable errno produces one sentence, exactly as every denial does, so the
class cannot be subdivided by reading the message. And the classification is an
allowlist -- an errno nobody enumerated is a denial -- so a future errno cannot
join the retryable class by accident.

**Identifier lifetime.** `obj_` and `ver_` suffixes are `secrets.token_hex`
output. They are not derived from the path, from a hash of the path, or from any
stat field, because a suffix that encoded one would defeat `INV-PKL-005` while
still passing the shape validation `domain.common.identifiers` can perform.
The consequence is stated plainly rather than hidden: **identifiers live as long
as the provider instance.** Two instances over the same root issue different
identifiers for the same file, and nothing here persists them, so an identifier
does not survive a process restart. A durable mapping, if one is ever needed,
belongs in the enrollment record, not in a suffix.

**Ordering.** `list_children` yields immediate children only, sorted ascending
by the code points of the entry name. It never recurses: a caller that wants a
subtree asks for one level at a time and decides for itself when to stop, so no
single call can walk a volume (`docs/specs` section 9.2).
"""

from __future__ import annotations

import errno
import os
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import Final

from my_pa.domain.common.identifiers import IdKind, make_identifier, validate_identifier
from my_pa.domain.source.provider import (
    ObjectKind,
    ProviderError,
    SourceObject,
    SourceObjectContent,
    SourceProvider,
    TraversalDeniedError,
    VersionChangedError,
)

__all__ = ["MEDIA_TYPES", "FixtureSourceProvider", "resolve_within"]

#: The one sentence every denial uses. Absent, outside the root, never issued,
#: and refused have to be indistinguishable, and the cheapest way to keep them
#: so is to give them nothing to differ in.
_DENIAL: Final = "cannot be served from the configured source"

#: The one sentence every unavailability uses, for the same reason `_DENIAL` is
#: one sentence: a caller that could tell a descriptor shortage from a device
#: error could tell them apart in the message even when it could not in the
#: type, and the difference is of no use to a caller and of some use to a prober.
_UNAVAILABLE: Final = "is temporarily unavailable from the configured source"

#: Errnos that mean "the object may well be fine; the machine or the transport
#: is not". Each is a resource shortage or a transient I/O condition, and every
#: one of them is a state the *same call* can succeed in a moment later, which
#: is precisely what `unavailable`'s conditional retry guidance is for.
#:
#:  `EMFILE`     this process is out of descriptors.
#:  `ENFILE`     the machine is out of descriptors.
#:  `EBADF`      also this process out of descriptors -- see below.
#:  `ENOMEM`     the kernel could not allocate for the open.
#:  `EIO`        a low-level I/O failure reaching the object.
#:  `ESTALE`     a network filesystem's handle went stale underneath us.
#:  `ETIMEDOUT`  a deadline, which is also what `TimeoutError` carries.
#:
#: `EBADF` is here on measured evidence and it is the entry most likely to look
#: wrong, so the measurement is written down. POSIX specifies `EMFILE` for a
#: process at its descriptor limit, and Linux returns it. On the Darwin build
#: this work was done against, exhausting `RLIMIT_NOFILE` makes `open`, `dup`,
#: `pipe`, and `socket` alike report `EBADF`, at the libc layer as well as
#: through CPython -- so an `EMFILE`-only classification leaves the exact
#: reproduction the finding was raised from still answering `denied`. What makes
#: it safe rather than merely necessary is the call it is classifying:
#: `os.open(path, flags)` is given no descriptor, so `EBADF` cannot mean "the
#: descriptor you passed was bad", and there is no other condition it names
#: here. This classification is therefore specific to that one call site, and
#: reusing this set for a call that does take a descriptor -- `os.fstat`,
#: `os.read`, an `openat` with a `dir_fd` -- would be wrong.
#:
#: Not a general "transient" list. `EAGAIN`, `EBUSY`, `EINTR`, and the socket
#: errnos a network filesystem can also surface are deliberately absent:
#: `EINTR` is retried by CPython before it reaches here (PEP 475), and the rest
#: have no demonstrated occurrence at this boundary. Adding one is a deliberate
#: edit with a case behind it, which is the only way an allowlist stays an
#: allowlist.
_UNAVAILABLE_ERRNOS: Final[frozenset[int]] = frozenset(
    {
        errno.EBADF,
        errno.EIO,
        errno.EMFILE,
        errno.ENFILE,
        errno.ENOMEM,
        errno.ESTALE,
        errno.ETIMEDOUT,
    }
)

#: Media types this provider recognises by file extension. `text/plain` and
#: `text/markdown` are the supported baseline; `application/pdf` is *reported*
#: and not extracted -- extraction is a later work package and `P00-OD-003` is
#: an open operator decision. An extension outside this table yields `None`,
#: which means "not identified here", not "empty" and not "text": the object is
#: still listed and still has metadata, so nothing is silently skipped and
#: nothing is coerced into a type it is not (`INV-PKL-007`).
MEDIA_TYPES: Final[dict[str, str]] = {
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}

#: Bytes per `os.read`. A ceiling on one syscall's buffer, not on the read.
_CHUNK_BYTES: Final = 1 << 20

#: How `fetch` opens an object, and why each flag is there.
#:
#: `O_RDONLY`   the whole boundary in one flag: there is no write path.
#: `O_NOFOLLOW` refuse a final component that became a symlink after the path
#:              was resolved. Final component only -- see `fetch` step 2.
#: `O_NONBLOCK` **an availability guarantee, not a performance one.** Opening a
#:              FIFO for reading blocks until a writer arrives, and the guard
#:              that refuses a non-regular file runs *after* the open, so it
#:              never gets to run: a FIFO swapped in for a file hangs the
#:              caller indefinitely. With this flag the open returns at once and
#:              the guard fires. It is a no-op for regular files, which is what
#:              makes it free.
_OPEN_FLAGS: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK

#: What identifies one observation of one object.
_Fingerprint = tuple[int, int, int, int, int]


def resolve_within(root: Path, candidate: Path, object_id: str) -> Path:
    """Resolve `candidate` and prove it is inside `root`, or deny.

    Both sides are resolved before they are compared, so the comparison is
    between the two locations the filesystem would actually reach rather than
    between two spellings of a path. `Path.is_relative_to` then compares path
    components, so a sibling directory whose name merely starts with the root's
    name is outside, where a string prefix test would have admitted it.

    Returns the resolved path so that the caller opens exactly what was proved.
    Re-deriving the path after validating it is the bug this signature exists to
    make awkward.
    """
    resolved: Path | None
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        # A resolution that fails is a containment that cannot be proved, which
        # is a denial. Recorded here and raised below, outside the handler, so
        # that the original -- which names the file -- is not left behind in
        # `__context__`.
        #
        # `RuntimeError` is not a mistake and not defensive breadth. On a
        # symlink loop, CPython's `Path.resolve` catches the `ELOOP` `OSError`
        # and re-raises `RuntimeError("Symlink loop from %r" % e.filename)`:
        # a non-`OSError`, not a `ProviderError` a caller could classify, and
        # carrying an absolute path in its message. Catching `OSError` alone
        # let one looping symlink anywhere under the root abort an entire
        # listing and disclose a path while doing it.
        resolved = None
    if resolved is None or not resolved.is_relative_to(root):
        raise TraversalDeniedError(f"{object_id} {_DENIAL}")
    return resolved


def _fingerprint(status: os.stat_result) -> _Fingerprint:
    """Identify one observation of one object from a single `stat`.

    Size and modification time answer "were these bytes rewritten"; device and
    inode answer "is this still the same object", which is the question a
    rename-over-the-top would otherwise slip past with size and mtime intact.
    Change time is included because the kernel updates it on any inode write, so
    a rewrite that contrived to preserve size and mtime still has to defeat a
    third field. Access time is excluded on purpose: reading a file updates it,
    and a fingerprint that changed because it was read would report a conflict
    on every second fetch.

    No content hash. Hashing would mean reading every byte of every object at
    listing time, which contradicts the bounded-read posture `fetch` is built
    around and would make a directory listing proportional to the volume's size.
    The honest residual: an in-place rewrite of exactly the same number of bytes
    that lands inside the same nanosecond as the previous write, on the same
    inode, is not visible here. What closes the gap for a read is not this
    function but `fetch`, which compares the fingerprint of the descriptor it
    actually read from, before and after the read.

    A second honest note, because a mutation of this function survived the
    suite once and the finding belongs next to the code. On a filesystem with
    nanosecond timestamps, `st_ctime_ns` moves for every change that device and
    inode would have caught, so no test driven through real files can show
    identity doing any work. It is kept because that equivalence is a property
    of the *filesystem*, not of this function: change time has one-second
    granularity on HFS+, ext3, and some NFS servers, where a
    rename-over-the-top inside one second collides on size, modification time,
    and change time alike. `tests/provider_conformance` states that invariant
    against constructed `stat` results, which is the only level at which this
    machine can state it.
    """
    return (
        status.st_dev,
        status.st_ino,
        status.st_size,
        status.st_mtime_ns,
        status.st_ctime_ns,
    )


def _read_bounded(descriptor: int, max_bytes: int) -> bytes:
    """Read at most `max_bytes` from `descriptor`.

    `max_bytes` is a hard ceiling, so the object's size is never used to size a
    buffer and the file is never read to its end to discover how long it is.
    Truncation is decided by the caller from the descriptor's own `fstat`, which
    costs no bytes.
    """
    chunks: list[bytes] = []
    remaining = max_bytes
    while remaining > 0:
        chunk = os.read(descriptor, min(remaining, _CHUNK_BYTES))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _media_type(path: Path) -> str | None:
    return MEDIA_TYPES.get(path.suffix.lower())


def _is_unavailable(error: OSError) -> bool:
    """Report whether `error` is a shortage rather than a refusal.

    An allowlist, and the direction matters more than the membership. Anything
    not enumerated -- including an errno that does not exist yet, and an
    `OSError` carrying no errno at all -- is a denial, so the failure mode of
    this function is to refuse something retryable rather than to tell a caller
    to keep retrying something it will never be allowed to have. That is also
    what keeps the class from becoming an existence oracle: a new errno cannot
    join it by resembling the ones already in it.

    `TimeoutError` is checked by type as well as by errno because the two do not
    agree across platforms. `ETIMEDOUT` is 60 on Darwin and 110 on Linux, and
    CPython raises `TimeoutError` for `ETIMEDOUT` on both; a test that
    constructs one with a fixed errno would otherwise pass on one platform and
    fail on the other, and this is the boundary where that must not depend on
    where the suite ran.

    It takes the exception rather than reading it in place at the call site, so
    that the classification happens where it can be tested directly and the
    caller's `except` block stays free of anything but recording the answer.
    """
    return isinstance(error, TimeoutError) or error.errno in _UNAVAILABLE_ERRNOS


class FixtureSourceProvider(SourceProvider):
    """Read-only access to the fixture tree under one configured root.

    `source_id` is supplied by the caller rather than minted here: source
    identity belongs to the registry that enrolled the source, and an adapter
    that issued its own would be claiming an authority it does not have.
    """

    def __init__(self, root: Path, source_id: str) -> None:
        validate_identifier(source_id, IdKind.SOURCE)
        configured: Path | None
        try:
            configured = Path(root).resolve()
        except (OSError, RuntimeError):
            # Including a looping root, which `Path.resolve` reports as a
            # `RuntimeError` naming the path. The operator's own configuration
            # is not a secret from the operator, but a message that carries a
            # path is a habit, and this one has no reason to.
            configured = None
        resolved = configured
        if resolved is None or not resolved.is_dir():
            # A misconfigured root is an operator error, not a denial: failing
            # it as a denial would hide it behind the message that must stay
            # uninformative.
            raise ValueError("the configured root is not an existing directory")
        self._source_id: Final = source_id
        self._root: Final = resolved
        self._ids: dict[Path, str] = {}
        self._paths: dict[str, Path] = {}
        self._versions: dict[_Fingerprint, str] = {}
        self._observations: dict[str, _Fingerprint] = {}
        self._root_object_id: Final = self._identify(resolved)

    @property
    def source_id(self) -> str:
        return self._source_id

    def list_children(self, parent_object_id: str | None = None) -> Iterator[SourceObject]:
        """Yield the immediate children of `parent_object_id`, the root when omitted.

        The listing is built eagerly and an iterator over it returned. A
        generator would defer every denial to the first `next()`, so a caller
        that asked for a container it may not have would be told so somewhere
        else entirely -- or, if it never iterated, not at all.

        An entry that cannot be proved contained, or that is neither a regular
        file nor a directory, is omitted. The listing says nothing about why an
        entry is absent, because a listing that distinguished "denied" from "not
        there" would be the side channel section 9.2 forbids.

        A symlink that stays inside the root is one name for an object that has
        another; identity here is the resolved object, so the alias and its
        target are described identically and carry one identifier between them.
        """
        object_id = self._root_object_id if parent_object_id is None else parent_object_id
        path = self._locate(object_id)
        entries: list[Path] | None
        try:
            entries = sorted(path.iterdir(), key=lambda entry: entry.name)
        except OSError:
            # Not a directory, or gone. Both are the same denial, raised below
            # rather than here so no `OSError` is left in `__context__`.
            entries = None
        if entries is None:
            raise TraversalDeniedError(f"{object_id} {_DENIAL}")

        children: list[SourceObject] = []
        for entry in entries:
            try:
                child = resolve_within(self._root, entry, object_id)
                children.append(self._observe(child, self._identify(child)))
            except TraversalDeniedError:
                continue
        return iter(tuple(children))

    def metadata(self, source_object_id: str) -> SourceObject:
        """Return current metadata for one object, re-proving containment first."""
        return self._observe(self._locate(source_object_id), source_object_id)

    def fetch(self, source_object_id: str, *, max_bytes: int) -> SourceObjectContent:
        """Read at most `max_bytes` from one object.

        The order of the four steps is the point of the method.

        1. Containment is proved again, now, against the current filesystem.
           The identifier was minted against a path that was contained when it
           was minted; a symlink swapped in since then resolves elsewhere, and
           this is where that is caught.
        2. The open uses the path that step 1 returned, not a path derived
           again from the identifier. Validating one path and opening another
           would be a check that reports on a file nobody read. `O_NOFOLLOW`
           narrows the window further: the resolved path's last component was a
           real file a moment ago, so if it is a symlink by the time the open
           runs, the open fails rather than following it. It is not a substitute
           for step 1 and must not be mistaken for one -- it inspects the final
           component only, so a swapped *intermediate* directory with a
           same-named file behind it opens perfectly happily. Re-resolving the
           whole path is the only thing that refuses that, which is why
           `tests/security` builds exactly that decoy.
        3. Every subsequent question is asked of the descriptor, not of the
           path. `fstat` on an open descriptor cannot be redirected by anything
           that happens to the name afterwards.
        4. The fingerprint is compared against the one this provider observed
           when it last described the object, and again after the read. A
           difference at either point is `VersionChangedError` -- `conflict`,
           never stale bytes labelled current (`docs/specs` section 9.4).

        A `VersionChangedError` does not silently re-observe the object. The
        caller has to call `metadata` again and decide what a changed object
        means to it, which is what "retry after refresh" requires.

        A failed `open` is classified by errno rather than refused wholesale;
        `_is_unavailable` holds the list and the reasoning. The boundary of that
        fix is worth writing down rather than leaving to be discovered. It
        covers the `open` and nothing else, so an `EIO` from `os.read` still
        leaves this method as an unclassified `OSError`, and an `ENOMEM` from
        `_observe`'s `stat` is still a denial. Neither is free to change here:
        the read sits inside the `finally` that owns the descriptor, and
        `_observe` is called per entry from `list_children` under an
        `except TraversalDeniedError: continue`, so a shortage raised from there
        would abort a whole listing over one unreadable entry -- the regression
        `test_one_looping_symlink_does_not_abort_the_whole_listing` exists to
        prevent. Both want coverage plumbing that does not exist yet, which is
        the same thing the hard-link finding in the completion plan wants.
        """
        if max_bytes < 0:
            raise ValueError("max_bytes cannot be negative")

        path = self._locate(source_object_id)
        expected = self._observations.get(source_object_id)
        if expected is None:
            # Issued but never described: there is nothing to compare a read
            # against, so there is nothing safe to return.
            raise TraversalDeniedError(f"{source_object_id} {_DENIAL}")

        descriptor: int | None = None
        unavailable = False
        try:
            descriptor = os.open(path, _OPEN_FLAGS)
        except OSError as error:
            # Classified, not swallowed. A blanket handler here reported a
            # descriptor shortage, a device error, and a stale network handle as
            # refusals, telling the caller to stop retrying something that was
            # only unavailable -- which `INV-PKL-007` forbids and which a
            # reviewer demonstrated with `RLIMIT_NOFILE` clamped.
            #
            # Only the answer is recorded here. Both raises are outside the
            # handler, so neither exception inherits this `OSError` through
            # `__context__`; an `OSError` renders with the path it failed on, so
            # the two spellings differ by a disclosure.
            unavailable = _is_unavailable(error)
        if descriptor is None:
            if unavailable:
                # The base `ProviderError`: the port defines no narrower class,
                # and inventing one is not this work package's to do. What the
                # caller needs is the distinction from `TraversalDeniedError`,
                # which it has.
                raise ProviderError(f"{source_object_id} {_UNAVAILABLE}")
            raise TraversalDeniedError(f"{source_object_id} {_DENIAL}")
        try:
            opened = os.fstat(descriptor)
            if not S_ISREG(opened.st_mode) or opened.st_nlink > 1:
                # The link count is the hard-link refusal, asked of the
                # descriptor rather than the name for the same reason as
                # everything else here. See the module docstring for why a
                # legitimate hard link is refused along with an escaping one.
                #
                # This precedes the fingerprint comparison because a security
                # refusal outranks a staleness report: `denied` and `conflict`
                # are different rows of the section 10 table and mean different
                # things to a caller. It is *not* ordered this way to stop a
                # hard link being served after a refresh -- linking moves
                # `st_ctime`, so the fingerprint differs anyway, and `_observe`
                # independently requires `st_nlink == 1`, so the refresh path is
                # closed twice over. An earlier revision of this comment claimed
                # otherwise; the ordering is right, that reason was not.
                raise TraversalDeniedError(f"{source_object_id} {_DENIAL}")
            observed = _fingerprint(opened)
            if observed != expected:
                raise VersionChangedError(
                    f"{source_object_id} changed between observation and read"
                )
            content = _read_bounded(descriptor, max_bytes)
            after = _fingerprint(os.fstat(descriptor))
        finally:
            os.close(descriptor)

        if after != observed:
            raise VersionChangedError(f"{source_object_id} changed during the read")

        return SourceObjectContent(
            source_object_id=source_object_id,
            version_id=self._version_of(observed),
            media_type=_media_type(path),
            content=content,
            is_truncated=opened.st_size > len(content),
        )

    def _identify(self, path: Path) -> str:
        """Return the opaque identifier for a resolved path, minting one once.

        The mapping is private to this instance. It is what lets an opaque
        identifier be turned back into a path without the identifier carrying
        the path.
        """
        existing = self._ids.get(path)
        if existing is not None:
            return existing
        minted = make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(16))
        self._ids[path] = minted
        self._paths[minted] = path
        return minted

    def _version_of(self, fingerprint: _Fingerprint) -> str:
        """Return the opaque version for a fingerprint, minting one once.

        Memoised rather than minted per call, because the port's contract is
        that two reads returning the same `version_id` observed the same bytes,
        and a caller comparing the version from `metadata` against the version
        from `fetch` is how a mid-read change is detected. A fresh random
        version per observation would make every such comparison report a
        change that did not happen.
        """
        existing = self._versions.get(fingerprint)
        if existing is not None:
            return existing
        minted = make_identifier(IdKind.VERSION, secrets.token_hex(16))
        self._versions[fingerprint] = minted
        return minted

    def _locate(self, source_object_id: str) -> Path:
        """Resolve an identifier to a currently contained path, or deny.

        A malformed identifier is a client error and raises
        `InvalidIdentifierError`: its shape is wrong whatever exists, so
        rejecting it discloses nothing. A well-formed identifier this instance
        never issued is denied with the same message as one that resolves
        outside the root.
        """
        validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
        known = self._paths.get(source_object_id)
        if known is None:
            raise TraversalDeniedError(f"{source_object_id} {_DENIAL}")
        return resolve_within(self._root, known, source_object_id)

    def _observe(self, path: Path, object_id: str) -> SourceObject:
        """Describe a contained path and record the observation for `fetch`."""
        status: os.stat_result | None
        try:
            status = path.stat()
        except OSError:
            status = None
        if status is None:
            raise TraversalDeniedError(f"{object_id} {_DENIAL}")

        if S_ISDIR(status.st_mode):
            kind, size, media_type = ObjectKind.CONTAINER, None, None
        elif S_ISREG(status.st_mode) and status.st_nlink == 1:
            kind, size, media_type = ObjectKind.FILE, status.st_size, _media_type(path)
        else:
            # A socket, device, or fifo is not a logical object this source has,
            # and a file with a second name may have that name outside the root.
            # `fetch` refuses both again on the open descriptor; refusing here
            # too is what keeps a listing from advertising an object that could
            # never be read, and a directory's link count is not consulted --
            # `.` and its children make it two or more by construction.
            raise TraversalDeniedError(f"{object_id} {_DENIAL}")

        fingerprint = _fingerprint(status)
        self._observations[object_id] = fingerprint
        return SourceObject(
            source_id=self._source_id,
            source_object_id=object_id,
            version_id=self._version_of(fingerprint),
            kind=kind,
            media_type=media_type,
            size_bytes=size,
            modified_at=datetime.fromtimestamp(status.st_mtime, UTC),
        )
