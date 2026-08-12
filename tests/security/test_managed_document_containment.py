"""No managed write escapes the designated root, and no source root is writable.

WP-27's release-blocking control. This plane is the first in the product that
writes bytes to a filesystem, and everything the campaign has protected so far —
source authority, provenance, immutability — depends on those writes never
landing in a source root. A path-traversal, symlink-escape, or misconfigured-root
defect here writes into the user's real data.

**The primary claim is structural, and the attack suite is secondary to it.**
`ManagedByteStore` — the port — has no method that takes a path, so there is no
argument a traversal could travel in. `test_no_managed_store_method_accepts_a_path`
asserts that off the port's own signatures rather than off this sentence, because
a future method with a `path: Path` parameter would silently restore the whole
class of attack below and every one of these tests would still pass: they can only
exercise the parameters that exist.

The attacks are therefore aimed at the two surfaces that *do* take strings — the
identifier a version is named by, and the root the store is constructed over —
plus the filesystem underneath both. Each is written out rather than
parameterised over a list, so a reader can see exactly what was tried.

**Every byte this module writes goes into `tmp_path`.** No test here creates a
directory in the repository, the home directory, or any real document tree, and
none reads an environment variable naming one.

**Three of the store's layers are redundant with one another and no test here
isolates them, which is measured rather than asserted.** Each was removed in turn
and the whole of this module stayed green: the resolved-parent comparison inside
`_verify_contained`, `O_NOFOLLOW` on the read, and `O_NOFOLLOW` on the create. In
every case the component walk refuses the same case first. They are kept as
defence against the window the walk cannot cover — a component swapped between
the walk and the `open` — and this paragraph is here so nobody reads their
presence as tested coverage. Every layer that *can* be isolated now is:
removing the component walk, the source-root overlap refusal, or the publishing
link each reddens a named test in this module.
"""

from __future__ import annotations

import inspect
import os
import unicodedata
from pathlib import Path
from typing import Final

import pytest

from my_pa.contracts.ports import ManagedByteStore
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, make_identifier
from my_pa.infrastructure.managed_document_stores.filesystem.store import (
    FilesystemManagedByteStore,
    ManagedRootError,
    ManagedStoreError,
)

#: A well-formed managed version identifier. Fixed rather than minted, so a
#: failure names the same object every run.
VERSION: Final = make_identifier(IdKind.MANAGED_DOCUMENT_VERSION, "a1b2c3d4e5f60718")
OTHER_VERSION: Final = make_identifier(IdKind.MANAGED_DOCUMENT_VERSION, "f0e1d2c3b4a59687")

CONTENT: Final = b"a synthetic managed document\n"


def _store(root: Path, *, source_roots: tuple[Path, ...] = ()) -> FilesystemManagedByteStore:
    return FilesystemManagedByteStore(root, source_roots=source_roots)


@pytest.fixture
def managed_root(tmp_path: Path) -> Path:
    root = tmp_path / "managed"
    root.mkdir()
    return root


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory that stands in for everything the store must never reach."""
    elsewhere = tmp_path / "outside"
    elsewhere.mkdir()
    (elsewhere / "authoritative.txt").write_text("source evidence", encoding="utf-8")
    return elsewhere


# --- the structural claim ---------------------------------------------------


def test_no_managed_store_method_accepts_a_path() -> None:
    """The control the whole module rests on: there is no path parameter.

    Read off the port's signatures and its annotations, so a method added with a
    `Path`, a `str` named like a location, or an `os.PathLike` reddens here —
    which is the only place it *can* redden, since every attack below can only
    aim at parameters that exist.
    """
    offending: list[str] = []
    for name, member in inspect.getmembers(ManagedByteStore, inspect.isfunction):
        if name.startswith("_"):
            continue
        signature = inspect.signature(member)
        for parameter in signature.parameters.values():
            if parameter.name == "self":
                continue
            annotation = str(parameter.annotation)
            if "Path" in annotation or "PathLike" in annotation:
                offending.append(f"{name}.{parameter.name}: {annotation}")
            if parameter.name in {"path", "location", "filename", "name", "destination"}:
                offending.append(f"{name}.{parameter.name}")
    assert offending == [], (
        f"{offending} put a filesystem location on the managed byte store's "
        "interface. Containment on this plane is the absence of a path "
        "parameter; every containment test in this module can only exercise the "
        "parameters that exist, so a new one is not covered by any of them"
    )

    # The control: the detector distinguishes rather than always answering no.
    # A synthetic port with a path parameter has to be found by the same walk.
    class _Planted(ManagedByteStore):
        def put(self, version_id: str, content: bytes) -> None: ...
        def read(self, version_id: str) -> bytes: ...
        def has(self, version_id: str) -> bool: ...
        def stored_version_ids(self) -> tuple[str, ...]: ...
        def unreadable_entries(self) -> tuple[str, ...]: ...
        def put_manifest(self, content: bytes) -> None: ...
        def read_manifest(self) -> bytes: ...
        def export_to(self, path: Path) -> None: ...

    found = [
        parameter.name
        for _name, member in inspect.getmembers(_Planted, inspect.isfunction)
        for parameter in inspect.signature(member).parameters.values()
        if "Path" in str(parameter.annotation)
    ]
    assert found == ["path"], "the path-parameter detector cannot see a path parameter"


# --- attacks on the identifier ----------------------------------------------


@pytest.mark.parametrize(
    ("attack", "supplied"),
    [
        ("parent traversal", "mdver_../../../../etc/passwd"),
        ("nested traversal", "mdver_..%2f..%2fetc%2fpasswd"),
        ("encoded traversal", "mdver_%2e%2e%2f%2e%2e%2fetc%2fpasswd"),
        ("absolute path", "mdver_/etc/passwd"),
        ("absolute windows path", "mdver_C:\\Windows\\System32"),
        ("bare dot", "mdver_."),
        ("empty suffix", "mdver_"),
        ("null byte", "mdver_aaaaaaaa\x00/../../etc"),
        ("newline", "mdver_aaaaaaaa\n../../etc"),
        ("separator inside a valid-length suffix", "mdver_aaaa/../bbbb"),
        ("home expansion", "mdver_~root"),
        ("nfd normalisation", unicodedata.normalize("NFD", "mdver_ààààààààà")),
        ("nfc normalisation", unicodedata.normalize("NFC", "mdver_ààààààààà")),
        ("wrong plane's prefix", make_identifier(IdKind.CAPTURE_VERSION, "a1b2c3d4e5f60718")),
        ("no prefix at all", "a1b2c3d4e5f60718"),
    ],
)
def test_a_hostile_version_identifier_is_refused_before_any_syscall(
    managed_root: Path, outside: Path, attack: str, supplied: str
) -> None:
    """Every read and write path refuses, and nothing appears outside the root.

    The identifier is the only string that reaches the derivation, and
    `validate_identifier` admits 8-64 alphanumeric characters after a known
    prefix — no separator, no dot, no null byte, and no Unicode form that
    normalises into one. So each of these fails at validation, before a path is
    built at all.
    """
    store = _store(managed_root)
    before = sorted(path.name for path in outside.iterdir())

    with pytest.raises((InvalidIdentifierError, ValueError)):
        store.put(supplied, CONTENT)
    with pytest.raises((InvalidIdentifierError, ValueError)):
        store.read(supplied)
    # `has` refuses too rather than answering `False`. A predicate that answered
    # a malformed identifier at all would be a way to ask the store questions
    # about strings it will never store, and the fail-closed answer to "is this
    # present" for something that cannot be present is a refusal.
    with pytest.raises((InvalidIdentifierError, ValueError)):
        store.has(supplied)

    assert sorted(path.name for path in outside.iterdir()) == before, (
        f"{attack} changed a directory outside the managed root"
    )
    assert list(managed_root.rglob("*")) == [], f"{attack} created something inside the root"


def test_a_well_formed_identifier_still_works(managed_root: Path) -> None:
    """The control: the refusals above are refusals and not a broken store."""
    store = _store(managed_root)
    store.put(VERSION, CONTENT)
    assert store.read(VERSION) == CONTENT
    assert store.has(VERSION) is True
    assert store.stored_version_ids() == (VERSION,)


# --- attacks on the filesystem ----------------------------------------------


def test_a_symlinked_managed_root_is_refused(tmp_path: Path, outside: Path) -> None:
    """A root that is a link resolves elsewhere; the store refuses to use it.

    Accepting it would mean the location an operator configured and the location
    this process writes are two different places, joined by a link the operator
    may not control.
    """
    link = tmp_path / "managed-link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ManagedRootError):
        _store(link)


def test_a_managed_root_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    """The store never creates its own root, so a typo is a refusal not a new tree."""
    with pytest.raises(ManagedRootError):
        _store(tmp_path / "never-created")
    assert not (tmp_path / "never-created").exists()


def test_a_managed_root_that_is_a_file_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(ManagedRootError):
        _store(target)


def test_a_symlinked_shard_directory_is_refused(managed_root: Path, outside: Path) -> None:
    """A link planted *inside* the root cannot redirect a write out of it.

    This is the case `Path.resolve` on the final target would follow silently:
    the target does not exist yet, so resolving it produces a location outside
    the root that looks like a fresh file. The component walk refuses the chain.
    """
    store = _store(managed_root)
    suffix = VERSION.removeprefix("mdver_")
    (managed_root / "objects").mkdir()
    (managed_root / "objects" / suffix[:2]).symlink_to(outside, target_is_directory=True)

    with pytest.raises(ManagedStoreError):
        store.put(VERSION, CONTENT)
    assert sorted(path.name for path in outside.iterdir()) == ["authoritative.txt"]


def test_a_shard_directory_symlinked_to_another_place_inside_the_root_is_refused(
    managed_root: Path,
) -> None:
    """The case the resolution check alone cannot see, and why the walk exists.

    A link inside the root pointing *outside* it is refused by the resolved
    comparison — measured, by removing the component walk and watching the two
    tests above stay green. A link inside the root pointing to another place
    **inside** the root resolves perfectly well, passes that comparison, and
    silently stores one version's bytes at another version's derived location.

    Without this case the component walk is a layer nothing exercises, which is
    the vacuous-guard shape this campaign keeps catching: it would have been
    deletable with every containment test still passing.
    """
    store = _store(managed_root)
    suffix = VERSION.removeprefix("mdver_")
    decoy = managed_root / "objects" / "zz"
    decoy.mkdir(parents=True)
    (managed_root / "objects" / suffix[:2]).symlink_to(decoy, target_is_directory=True)

    with pytest.raises(ManagedStoreError):
        store.put(VERSION, CONTENT)
    assert list(decoy.rglob("*")) == [], "the write landed at an aliased location"


def test_a_symlinked_parent_of_the_object_directory_is_refused(
    managed_root: Path, outside: Path
) -> None:
    """The whole object tree replaced by a link is refused the same way."""
    store = _store(managed_root)
    (managed_root / "objects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ManagedStoreError):
        store.put(VERSION, CONTENT)
    assert sorted(path.name for path in outside.iterdir()) == ["authoritative.txt"]


def test_a_stored_object_replaced_by_a_symlink_is_not_read_through(
    managed_root: Path, outside: Path
) -> None:
    """A link swapped in for a stored object reads as a refusal, not as its target.

    `O_NOFOLLOW` on the read is what refuses it. Without this, an attacker who
    could write inside the managed root could make a managed read return the
    contents of a source file.
    """
    store = _store(managed_root)
    store.put(VERSION, CONTENT)
    suffix = VERSION.removeprefix("mdver_")
    stored = managed_root / "objects" / suffix[:2] / suffix[2:4] / VERSION
    stored.unlink()
    stored.symlink_to(outside / "authoritative.txt")

    with pytest.raises(ManagedStoreError):
        store.read(VERSION)


def test_a_second_write_to_one_version_is_refused(managed_root: Path) -> None:
    """Bytes are written once, and overwriting does not exist.

    This is the byte half of immutability, and it is held by the publishing
    `hardlink_to` rather than by a check in front of it: `rename` replaces an
    existing name silently on POSIX, so an `exists()` guard would be a
    check-then-act with a window. The database trigger is the metadata half;
    `tests/database/test_managed_documents.py` proves that one.
    """
    store = _store(managed_root)
    store.put(VERSION, CONTENT)
    with pytest.raises(ManagedStoreError):
        store.put(VERSION, b"different bytes entirely")
    assert store.read(VERSION) == CONTENT


def test_a_leftover_part_file_is_refused_rather_than_overwritten(managed_root: Path) -> None:
    """`O_CREAT | O_EXCL` on the temporary, isolated.

    A crashed run can leave a part-file under `incoming/`. Overwriting it would
    be the one place in this module where bytes are written over bytes, so the
    create is exclusive and a leftover is a refusal. Isolated deliberately: the
    publishing link refuses a second *object*, so without this case the flag on
    the temporary would be a layer nothing exercises.
    """
    store = _store(managed_root)
    incoming = managed_root / "incoming"
    incoming.mkdir()
    (incoming / f"{VERSION.removeprefix('mdver_')}.part").write_bytes(b"a partial write")

    with pytest.raises(ManagedStoreError):
        store.put(VERSION, CONTENT)
    assert store.has(VERSION) is False


def test_verify_contained_refuses_a_location_outside_the_root(managed_root: Path) -> None:
    """The containment comparison itself, called directly.

    Every public method derives its own location, so no test through the public
    interface can hand this one a path outside the root — which would leave the
    comparison unexercised. It is the check that has to survive a future edit to
    the derivation, so it is exercised directly rather than left to be inferred.
    """
    store = _store(managed_root)
    with pytest.raises(ManagedStoreError):
        store._verify_contained(managed_root.parent / "elsewhere" / "object")


def test_a_hard_linked_object_is_not_read_through(managed_root: Path, outside: Path) -> None:
    """A second name for an outside inode is refused by the descriptor's link count.

    `realpath` cannot see a hard link, so this is refused on the open descriptor
    rather than on the name — the same mechanism, for the same reason,
    `infrastructure.providers.fixture` applies on the read side.
    """
    store = _store(managed_root)
    store.put(VERSION, CONTENT)
    suffix = VERSION.removeprefix("mdver_")
    stored = managed_root / "objects" / suffix[:2] / suffix[2:4] / VERSION
    stored.unlink()
    os.link(outside / "authoritative.txt", stored)

    with pytest.raises(ManagedStoreError):
        store.read(VERSION)


# --- the source-root boundary -----------------------------------------------


def test_a_managed_root_equal_to_a_source_root_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ManagedRootError):
        _store(source, source_roots=(source,))


def test_a_managed_root_inside_a_source_root_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "managed").mkdir(parents=True)
    with pytest.raises(ManagedRootError):
        _store(source / "managed", source_roots=(source,))


def test_a_managed_root_containing_a_source_root_is_refused(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    (managed / "source").mkdir(parents=True)
    with pytest.raises(ManagedRootError):
        _store(managed, source_roots=(managed / "source",))


def test_a_managed_root_symlinked_into_a_source_root_is_refused(tmp_path: Path) -> None:
    """The comparison is between resolved locations, not between spellings.

    A managed root spelled as a link into a source tree is the shape a string
    comparison admits and a resolved one refuses. The link is refused twice over
    here — once as a link, and once as an overlap — which is why the assertion is
    on the type rather than on the message.
    """
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "managed"
    link.symlink_to(source, target_is_directory=True)
    with pytest.raises(ManagedRootError):
        _store(link, source_roots=(source,))


def test_a_managed_root_reached_through_a_relative_spelling_of_a_source_root_is_refused(
    tmp_path: Path,
) -> None:
    """`..` in the *source* root's spelling does not hide the overlap either."""
    source = tmp_path / "source"
    (source / "managed").mkdir(parents=True)
    spelled = tmp_path / "source" / "managed" / ".." / ".." / "source"
    with pytest.raises(ManagedRootError):
        _store(source / "managed", source_roots=(spelled,))


def test_a_disjoint_managed_root_is_admitted(tmp_path: Path) -> None:
    """The control: the overlap rule refuses overlaps and not every configuration."""
    source = tmp_path / "source"
    source.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    store = _store(managed, source_roots=(source,))
    store.put(VERSION, CONTENT)
    assert store.read(VERSION) == CONTENT
    assert list(source.iterdir()) == [], "the source root was written to"


def test_the_read_only_source_port_still_has_no_write_method() -> None:
    """The other half of the boundary: source providers gained nothing.

    `AGENTS.md` section 4 keeps source providers read-only by omission. This
    package adds a write plane, and the failure mode worth guarding is that the
    write reached the *existing* port rather than the new one — a `write`,
    `put`, or `delete` appearing on `SourceProvider` would make every source root
    writable through machinery the whole product already holds.
    """
    from my_pa.domain.source.provider import SourceProvider

    forbidden = {
        "write",
        "write_bytes",
        "write_text",
        "put",
        "store",
        "save",
        "create",
        "update",
        "delete",
        "remove",
        "move",
        "rename",
        "copy",
    }
    present = {
        name
        for name, _member in inspect.getmembers(SourceProvider, inspect.isfunction)
        if not name.startswith("_")
    }
    assert present & forbidden == set(), (
        f"{sorted(present & forbidden)} appeared on the read-only source port. "
        "Source roots are authoritative and read-only; the managed plane is "
        "where this product writes"
    )
    assert present, "the source port has no methods at all; this check measured nothing"
