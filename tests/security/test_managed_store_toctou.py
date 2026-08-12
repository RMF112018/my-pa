"""WP-27's disclosed intermediate-component race, reproduced and then closed.

WP-27's independent review got bytes outside the managed root exactly once, and
recorded it as NOTE 1:

> `O_NOFOLLOW` covers only the final path component and `_publish`'s
> `hardlink_to` carries no link protection; a directory component swapped between
> `_verify_contained` and the syscall lands the write outside the root while
> `put()` reports success. Remedy: open the shard once with
> `O_DIRECTORY|O_NOFOLLOW` and use `openat`/`linkat` relative to that descriptor.

**Why WP-28 closes it rather than carrying it.** The precondition is unchanged —
an attacker still needs write access inside the managed root as the product's own
UID — but the reachability calculus is not. Before this package nothing outside
the process could reach the managed plane at all; now a client drives managed
writes over a transport and therefore controls their timing, their concurrency
and their volume, which is exactly what a race needs. That does not make the
window remotely exploitable and this module does not claim it does. It makes it
a window worth closing while the plane is being wired rather than after.

## How the race is reproduced deterministically

A real race would be a thread and a retry loop, which is a flaky test. Instead the
swap is performed **at the exact instant the window opens**: `_verify_contained`
is wrapped so that the first call made from inside `_publish` does its real work
and *then* replaces the shard directory with a symbolic link pointing outside the
root. That is the strongest form of the attack — the attacker wins the race every
time — so a refusal here is a refusal under conditions no real attacker could
improve on.

**"From inside `_publish`" is checked rather than assumed, and the correction is
why.** One `put` makes five `_verify_contained` calls, and the first is inside
`_object_path` — before a directory has been created and before a temporary
exists. A wrapper that fired on whichever call came first fired *there*, and the
`put` was then refused at `_ensure_directory`, which is a genuine refusal of a
different window: every assertion below would have held for the wrong reason, and
the "nothing half-written" one would have held vacuously because there was
nothing to write yet. So the wrapper is armed with the name of the function the
swap must be called from, reads its caller off the stack frame, and records where
it went off; the claim test asserts that it was `_publish`.

**What is left behind at that window is asserted rather than tidied.** A refusal
inside `_publish` comes from `_anchored`, which raises `ManagedStoreError`, and
`put` catches only `FileExistsError` and `OSError` — so the `.part` temporary
survives. It is an orphan inside the root, holding no object name, reported by
`verify` in `unreadable_entries`, and never reclaimed automatically. The test
says so, because the alternative is an assertion that reads well and is false.

## The two halves, and why both are here

**The control**, `test_the_swap_really_lands_bytes_outside_the_root`, performs the
publication the way WP-27 performed it — `Path.hardlink_to` on a name, which is
the code that shipped — and shows the bytes land in a directory outside the root
with the store reporting success. Without it, the refusal below would be evidence
that something failed, not evidence that *this* was prevented.

**The claim**, `test_the_anchored_publication_refuses_the_swapped_component`,
performs the same publication through the store as it is now, at the `_publish`
window, and shows the write refused with nothing outside the root and nothing
published inside it. Reverting `_publish` to the two lines WP-27 shipped makes it
fail with `DID NOT RAISE`, which is what says it is about the anchoring rather
than about the swap.

Everything runs under `tmp_path` and is removed with the test. No configured root
is read, no environment variable is set, and every value is synthetic.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Final

import pytest

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.managed_document_stores.filesystem.store import (
    FilesystemManagedByteStore,
    ManagedStoreError,
)

CONTENT: Final = b"# Synthetic managed note\n\nBytes that must not leave the root.\n"


@pytest.fixture
def roots(tmp_path: Path) -> tuple[Path, Path]:
    """A managed root and a directory outside it, both temporary."""
    root = tmp_path / "managed"
    root.mkdir()
    escape = tmp_path / "escape"
    escape.mkdir()
    return root, escape


def _shard_of(root: Path, version_id: str) -> Path:
    """Where the store will put this version's shard directory.

    Derived here the same way the store derives it, from the identifier's own
    suffix — which is the only input either side has, because the store accepts
    no path.
    """
    suffix = version_id.split("_", 1)[1]
    return root / "objects" / suffix[:2] / suffix[2:4]


class _SwapsTheShardOnce:
    """Replace the shard directory with a symlink the first time the window opens.

    Wraps `_verify_contained` rather than patching a syscall, because the window
    the finding names is *between* that check and the syscall that follows it.
    Firing once is what makes this the attack rather than a broken filesystem: the
    check passes on a real directory, and the directory stops being one
    immediately afterwards.

    **Which check it fires on is the whole fidelity of this module.**
    `_verify_contained` is called five times during one `put`, and the *first* is
    inside `_object_path`, before any temporary exists and before any directory
    has been created. A swap fired there is refused at `_ensure_directory`, which
    is a true refusal of a different window — and a test that fired there while
    saying it fired in `_publish` would be asserting nothing about the window the
    finding names. So `arm` takes the name of the function the swap must be called
    *from*, the caller is read off the stack frame, and `fired_in` records where it
    actually went off so a test can assert it rather than assume it.
    """

    def __init__(self, store: FilesystemManagedByteStore, shard: Path, escape: Path) -> None:
        self._inner = store._verify_contained
        self._shard = shard
        self._escape = escape
        self.armed = False
        self.fired = False
        self.window: str | None = None
        self.fired_in: str | None = None

    def arm(self, window: str | None) -> None:
        """Fire on the next `_verify_contained` made from `window`, or from anywhere."""
        self.window = window
        self.armed = True

    def __call__(self, path: Path) -> None:
        self._inner(path)
        if not self.armed or self.fired:
            return
        frame = inspect.currentframe()
        caller = frame.f_back.f_code.co_name if frame is not None and frame.f_back else ""
        if self.window is not None and caller != self.window:
            return
        if not self._shard.is_dir() or self._shard.is_symlink():
            return
        self.fired = True
        self.fired_in = caller
        for entry in self._shard.iterdir():
            entry.unlink()
        self._shard.rmdir()
        self._shard.symlink_to(self._escape, target_is_directory=True)


def _armed_store(
    root: Path, escape: Path, version_id: str
) -> tuple[FilesystemManagedByteStore, _SwapsTheShardOnce]:
    """A store whose shard is swapped for a link the moment the window opens.

    The shard is created first by a successful write of a *different* version, so
    the swap replaces a real directory the store itself made — the shape the
    finding describes, rather than a directory that never existed.
    """
    store = FilesystemManagedByteStore(root)
    store.put(issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION), b"# Synthetic warm-up\n")
    shard = _shard_of(root, version_id)
    shard.mkdir(parents=True, exist_ok=True)
    swap = _SwapsTheShardOnce(store, shard, escape)
    store._verify_contained = swap  # type: ignore[method-assign]
    return store, swap


def _outside(escape: Path) -> list[Path]:
    return sorted(path for path in escape.rglob("*") if path.is_file())


def test_the_swap_really_lands_bytes_outside_the_root(roots: tuple[Path, Path]) -> None:
    """The control, and it is the code WP-27 shipped rather than a caricature.

    `Path.hardlink_to` on a derived name, immediately after the containment check
    passed — the two lines `_publish` used to be. If this did not put bytes in the
    escape directory, the refusal in the test below would be proving nothing about
    this window.
    """
    root, escape = roots
    version_id = issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION)
    store, swap = _armed_store(root, escape, version_id)

    # The temporary the store would have written, prepared the way the store
    # prepares it — inside `incoming`, fsynced, and holding the real bytes.
    incoming = root / "incoming"
    incoming.mkdir(exist_ok=True)
    temporary = incoming / f"{version_id.split('_', 1)[1]}.part"
    temporary.write_bytes(CONTENT)

    target = _shard_of(root, version_id) / version_id
    # Fired wherever it is called from, because the caller here is this test
    # standing in for `_publish`: the two lines below *are* what `_publish` was.
    swap.arm(None)
    # This is the check the shipped code made...
    store._verify_contained(target)  # type: ignore[attr-defined]
    assert swap.fired, "the window did not open, so this test is measuring nothing"
    # ...and this is the syscall it made afterwards, by name.
    target.hardlink_to(temporary)
    temporary.unlink()

    landed = _outside(escape)
    assert landed, "the swap did not place anything outside the root"
    assert landed[0].read_bytes() == CONTENT
    # The object exists only through the swapped link: its real inode is in the
    # escape directory, and the name under the root resolves to it.
    assert landed[0].parent == escape
    assert (root / "objects").is_dir()


def test_the_anchored_publication_refuses_the_swapped_component(
    roots: tuple[Path, Path],
) -> None:
    """The claim: the same swap, at the window the finding names, through the store.

    **Fired only from inside `_publish`**, which is the disclosed window: the
    check has passed, the temporary is written and fsynced, and the very next
    thing that happens is the `linkat` that publishes it. An earlier firing —
    from `_object_path`, which is the first of the five `_verify_contained` calls
    a `put` makes — is refused at `_ensure_directory` before a temporary exists,
    which is a real refusal of a *different* window and would leave every
    assertion here true for the wrong reason.

    What is asserted at that window:

    * `put` refuses. The swapped shard is a symbolic link, and `_publish`'s
      `_anchored(target.parent)` walks the chain with `O_DIRECTORY | O_NOFOLLOW`
      and cannot open it, so the `linkat` is never reached.
    * Nothing is outside the root. The escape directory the link points at is
      empty, which is the whole finding.
    * Nothing is published inside it either: `has` is false and the object tree
      holds no file for this version.
    * **The temporary is still there**, and that is stated rather than tidied
      away. `_anchored` raises `ManagedStoreError`; `put` catches
      `FileExistsError` and `OSError`, so the cleanup branch does not run and the
      `.part` file survives the refusal. It is an orphan *inside* the root,
      carrying no object name, reported by `verify` in `unreadable_entries`, and
      never reclaimed automatically — WP-27's disclosed model exactly. Asserting
      the opposite would be asserting something convenient rather than something
      true.
    """
    root, escape = roots
    version_id = issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION)
    store, swap = _armed_store(root, escape, version_id)
    before = {path.name for path in (root / "objects").rglob("*") if path.is_file()}

    swap.arm("_publish")
    with pytest.raises(ManagedStoreError):
        store.put(version_id, CONTENT)

    assert swap.fired, "the window did not open, so this test is measuring nothing"
    assert swap.fired_in == "_publish", (
        f"the swap fired from {swap.fired_in!r}, so this is not the disclosed window"
    )
    assert _outside(escape) == [], "bytes were written outside the managed root"
    # Nothing was published: the object tree holds exactly what the warm-up write
    # left in it, and this version is not in it.
    assert {path.name for path in (root / "objects").rglob("*") if path.is_file()} == before
    assert version_id not in before
    # `has` is asked through the swapped component too, and refuses rather than
    # answering — the component walk sees the link. The read side of the same
    # refusal rather than a second finding, and recorded because a reader would
    # otherwise expect `has` to return `False` here.
    with pytest.raises(ManagedStoreError):
        store.has(version_id)

    # The temporary survives, inside the root, and `verify` is what reports it.
    leftovers = sorted((root / "incoming").glob("*.part"))
    assert len(leftovers) == 1, leftovers
    assert leftovers[0].read_bytes() == CONTENT
    assert leftovers[0].is_relative_to(store.root)
    assert leftovers[0].name in {Path(entry).name for entry in store.unreadable_entries()}, (
        "the surviving temporary is not reported by the integrity check"
    )


def test_an_unswapped_write_still_succeeds(roots: tuple[Path, Path]) -> None:
    """`D-55`: the store must still store.

    A containment layer that refused everything would pass the test above and be
    useless. The same store, the same identifier, no swap: the bytes go in and
    come back.
    """
    root, escape = roots
    store = FilesystemManagedByteStore(root)
    version_id = issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION)
    store.put(version_id, CONTENT)
    assert store.has(version_id)
    assert store.read(version_id) == CONTENT
    assert _outside(escape) == []


def test_a_shard_that_is_already_a_link_is_refused_before_any_write(
    roots: tuple[Path, Path],
) -> None:
    """The non-race half, kept because it fails for a different reason.

    A component that is *already* a link is refused by the component walk, which
    is the common case and the one that produces a clear refusal rather than an
    `ENOTDIR` from the kernel. Anchoring did not replace that layer and this is
    what says so.
    """
    root, escape = roots
    store = FilesystemManagedByteStore(root)
    version_id = issue_identifier(IdKind.MANAGED_DOCUMENT_VERSION)
    shard = _shard_of(root, version_id)
    shard.parent.mkdir(parents=True, exist_ok=True)
    shard.symlink_to(escape, target_is_directory=True)

    with pytest.raises(ManagedStoreError):
        store.put(version_id, CONTENT)
    assert _outside(escape) == []


def test_the_anchoring_capability_is_present_on_this_platform() -> None:
    """The remedy is a capability, and a build without it must not pretend.

    `_anchored` raises rather than reverting to name-based syscalls when the
    platform cannot anchor, so a platform that cannot hold the guarantee fails
    loudly. This asserts that the platform under test *can* — otherwise every
    test above would be passing because the store refuses everything.
    """
    for call in (os.open, os.link, os.unlink, os.mkdir, os.stat):
        assert call in os.supports_dir_fd, call
    assert os.link in os.supports_follow_symlinks
