"""Files workspace WP3: containment of the filesystem store, on synthetic temporary roots.

Every escape below is built at test time and first *verified to be a real
escape* with a plain name-based read, so a denial cannot pass on an inert
fixture. Covered: a symlink at the root, at an intermediate component and at
the leaf (pointing inside and outside the root); a directory swapped for a
symlink between the store's check and its use; FIFO and socket leaves (no
hang); that no link the store makes lands outside the root; `..` and absolute
paths refused before any I/O; root overlap refusals; no host path in any
exception; and the control directory being unreachable through the API.
"""

from __future__ import annotations

import hashlib
import os
import signal
import socket
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from my_pa.contracts.ports import (
    FileWorkspaceRootError,
    FileWorkspaceUnavailableError,
    PortError,
)
from my_pa.domain.files.errors import FilesDomainError, FilesRefusal
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore

TRASH_ID = "fwtrs_abcdef0123456789"
VERSION_ID = "fwver_abcdef0123456789"
UPLOAD_ID = "fwupl_abcdef0123456789"
SECRET = b"outside-the-workspace"


@pytest.fixture
def layout(tmp_path: Path) -> tuple[Path, Path]:
    """`(root, outside)`: a workspace and a sibling tree holding a secret file."""
    root = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_bytes(SECRET)
    return root, outside


@pytest.fixture
def store(layout: tuple[Path, Path]) -> FilesystemFileWorkspaceStore:
    return FilesystemFileWorkspaceStore(layout[0], disk_reserve_bytes=0)


@pytest.fixture(autouse=True)
def _no_hang() -> Iterator[None]:
    """A FIFO open that blocked would hang the suite; fail it after 10 s instead."""

    def expire(_signum: int, _frame: object) -> None:
        raise TimeoutError("a filesystem call blocked")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(10)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _refusal(call: Callable[[], object]) -> FilesReason:
    with pytest.raises(FilesRefusal) as caught:
        call()
    return caught.value.reason


def _snapshot(directory: Path) -> dict[str, bytes | None]:
    return {
        str(path.relative_to(directory)): (path.read_bytes() if path.is_file() else None)
        for path in sorted(directory.rglob("*"))
    }


# --- the root ----------------------------------------------------------------------


def test_a_symlinked_root_is_refused(layout: tuple[Path, Path], tmp_path: Path) -> None:
    root, _outside = layout
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    assert (alias / ".").resolve() == root.resolve()  # the alias really reaches the root
    with pytest.raises(FileWorkspaceRootError) as caught:
        FilesystemFileWorkspaceStore(alias)
    assert str(tmp_path) not in str(caught.value)


@pytest.mark.parametrize("keyword", ["source_roots", "managed_roots", "report_roots"])
def test_the_root_may_not_overlap_another_plane(
    layout: tuple[Path, Path], tmp_path: Path, keyword: str
) -> None:
    root, outside = layout
    (root / "nested").mkdir()
    for other in (root, root / "nested", tmp_path):  # equal, inside the root, containing it
        with pytest.raises(FileWorkspaceRootError) as caught:
            FilesystemFileWorkspaceStore(root, **{keyword: [other]})  # type: ignore[arg-type]
        assert str(tmp_path) not in str(caught.value)
    FilesystemFileWorkspaceStore(root, **{keyword: [outside]})  # type: ignore[arg-type]


def test_a_replaced_root_is_refused_at_use(layout: tuple[Path, Path], tmp_path: Path) -> None:
    root, _outside = layout
    store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
    root.rename(tmp_path / "moved-away")
    root.mkdir()
    with pytest.raises(FileWorkspaceUnavailableError):
        store.list_directory("")


# --- links on the path ----------------------------------------------------------------


@pytest.mark.parametrize("points_inside", [False, True])
def test_an_intermediate_symlink_is_never_followed(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path], points_inside: bool
) -> None:
    root, outside = layout
    (root / "real").mkdir()
    (root / "real" / "secret.txt").write_bytes(SECRET)
    target = root / "real" if points_inside else outside
    (root / "link").symlink_to(target, target_is_directory=True)
    assert (root / "link" / "secret.txt").read_bytes() == SECRET  # a real escape by name
    before = _snapshot(outside)

    calls: list[Callable[[], object]] = [
        lambda: store.list_directory("link"),
        lambda: store.stat("link/secret.txt", include_sha256=True),
        lambda: store.preview("link/secret.txt"),
        lambda: store.search("link", "secret"),
        lambda: store.mkdir("link/new"),
        lambda: store.mkdir("link/a/b", parents=True),
        lambda: store.write_text("link/new.txt", "x"),
        lambda: store.move("link/secret.txt", "moved.txt"),
        lambda: store.copy("link/secret.txt", "copied.txt"),
        lambda: store.trash("link/secret.txt", TRASH_ID),
        lambda: store.open_download("link/secret.txt", expected_version="fv1_" + "0" * 64),
    ]
    for call in calls:
        assert _refusal(call) is FilesReason.UNSUPPORTED_ENTRY
    assert _snapshot(outside) == before
    assert not (root / "moved.txt").exists() and not (root / "copied.txt").exists()


@pytest.mark.parametrize("points_inside", [False, True])
def test_a_leaf_symlink_is_listed_but_never_followed(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path], points_inside: bool
) -> None:
    root, outside = layout
    (root / "inside.txt").write_bytes(SECRET)
    target = root / "inside.txt" if points_inside else outside / "secret.txt"
    (root / "leaf").symlink_to(target)
    assert (root / "leaf").read_bytes() == SECRET
    entry = store.stat("leaf", include_sha256=True)
    assert entry.kind.value == "other" and entry.size is None and entry.sha256 is None
    version = entry.version

    calls: list[Callable[[], object]] = [
        lambda: store.preview("leaf"),
        lambda: store.open_download("leaf", expected_version=version),
        lambda: store.move("leaf", "moved"),
        lambda: store.copy("leaf", "copied"),
        lambda: store.trash("leaf", TRASH_ID),
        lambda: store.write_text(
            "leaf", "x", expected_version=version, preimage_version_id=VERSION_ID
        ),
    ]
    for call in calls:
        assert _refusal(call) is FilesReason.UNSUPPORTED_ENTRY
    assert (outside / "secret.txt").read_bytes() == SECRET
    assert (root / "leaf").is_symlink()


def test_a_directory_swapped_for_a_symlink_after_the_check_is_not_followed(
    store: FilesystemFileWorkspaceStore,
    layout: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The publish lands in the directory that was walked, not where the name now points."""
    root, outside = layout
    (root / "d").mkdir()

    def swap(_stage: str) -> None:
        (root / "d").rename(root / "d-original")
        (root / "d").symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(store, "_checkpoint", swap)
    before = _snapshot(outside)
    store.write_text("d/new.txt", "contained")
    assert _snapshot(outside) == before
    assert (root / "d-original" / "new.txt").read_bytes() == b"contained"
    monkeypatch.undo()
    # And the next call refuses the planted link outright.
    assert _refusal(lambda: store.write_text("d/again.txt", "x")) is FilesReason.UNSUPPORTED_ENTRY


def test_a_leaf_swapped_for_a_symlink_before_the_rename_is_refused(
    store: FilesystemFileWorkspaceStore,
    layout: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, outside = layout
    created = store.write_text("f", "mine")

    def swap(_stage: str) -> None:
        (root / "f").unlink()
        (root / "f").symlink_to(outside / "secret.txt")

    monkeypatch.setattr(store, "_checkpoint", swap)
    reason = _refusal(
        lambda: store.write_text(
            "f", "new", expected_version=created.entry.version, preimage_version_id=VERSION_ID
        )
    )
    assert reason is FilesReason.EXTERNAL_CHANGE_DETECTED
    assert (outside / "secret.txt").read_bytes() == SECRET
    assert (root / "f").is_symlink()
    assert not (root / ".my-pa" / "versions" / VERSION_ID).exists()

    monkeypatch.setattr(store, "_checkpoint", lambda _stage: None)
    (root / "g").write_bytes(b"g")
    observed = store.stat("g").version

    def swap_g(_stage: str) -> None:
        (root / "g").unlink()
        (root / "g").symlink_to(outside / "secret.txt")

    monkeypatch.setattr(store, "_checkpoint", swap_g)
    assert _refusal(lambda: store.trash("g", TRASH_ID, expected_version=observed)) is (
        FilesReason.EXTERNAL_CHANGE_DETECTED
    )
    assert (outside / "secret.txt").read_bytes() == SECRET


@pytest.mark.parametrize("operation", ["move", "trash"])
def test_a_leaf_swapped_after_the_recheck_leaves_no_new_entry(
    store: FilesystemFileWorkspaceStore,
    layout: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """A swap between the re-check and the link is refused, and the link it made is undone.

    Whatever sits at the new name after a successful `linkat` was created by
    that call, so a refused move or trash must not leave it behind.
    """
    root, outside = layout
    (root / "a.txt").write_bytes(b"mine")
    observed = store.stat("a.txt").version

    def swap(_stage: str) -> None:
        (root / "a.txt").unlink()
        (root / "a.txt").symlink_to(outside / "secret.txt")

    monkeypatch.setattr(store, "_after_recheck", swap)
    if operation == "move":
        reason = _refusal(lambda: store.move("a.txt", "b.txt", expected_version=observed))
        target = root / "b.txt"
    else:
        reason = _refusal(lambda: store.trash("a.txt", TRASH_ID, expected_version=observed))
        target = root / ".my-pa" / "trash" / TRASH_ID
    assert reason is FilesReason.EXTERNAL_CHANGE_DETECTED
    assert not os.path.lexists(target)
    assert (root / "a.txt").is_symlink()  # the external replacement is left alone
    assert (outside / "secret.txt").read_bytes() == SECRET
    assert (outside / "secret.txt").stat().st_nlink == 1


def test_a_hard_linked_file_is_listed_but_its_bytes_are_never_read(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path]
) -> None:
    """A host hard link to a file outside the root is a regular file the store will not read.

    It stays kind `file` in `list` and `stat` (section 4 kinds are by file
    type), but every operation that reads its bytes out is `unsupported_entry`.
    """
    root, outside = layout
    (root / "d").mkdir()
    os.link(outside / "secret.txt", root / "h.txt")
    os.link(outside / "secret.txt", root / "d" / "h.txt")
    assert (root / "h.txt").read_bytes() == SECRET  # a real escape by name
    entry = store.stat("h.txt")
    assert entry.kind.value == "file" and entry.size == len(SECRET)
    assert [e.name for e in store.list_directory("").entries] == ["d", "h.txt"]
    version = entry.version

    calls: list[Callable[[], object]] = [
        lambda: store.stat("h.txt", include_sha256=True),
        lambda: store.preview("h.txt"),
        lambda: store.open_download("h.txt", expected_version=version),
        lambda: store.copy("h.txt", "copied.txt"),
        lambda: store.copy("d", "d-copy"),
    ]
    for call in calls:
        assert _refusal(call) is FilesReason.UNSUPPORTED_ENTRY
    assert not (root / "copied.txt").exists() and not (root / "d-copy").exists()
    staging = root / ".my-pa" / "staging"
    assert not staging.exists() or list(staging.iterdir()) == []
    assert (outside / "secret.txt").stat().st_nlink == 3


# --- special files -------------------------------------------------------------------------


def test_fifo_and_socket_leaves_are_refused_without_blocking(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _outside = layout
    os.mkfifo(root / "fifo")
    monkeypatch.chdir(root)  # AF_UNIX paths are short; bind relative to the root
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind("sock")
        for name in ("fifo", "sock"):
            version = store.stat(name).version
            assert store.stat(name).kind.value == "other"
            for call in (
                lambda name=name: store.preview(name),
                lambda name=name, version=version: store.open_download(
                    name, expected_version=version
                ),
                lambda name=name: store.copy(name, f"{name}-copy"),
                lambda name=name: store.move(name, f"{name}-moved"),
                lambda name=name: store.trash(name, TRASH_ID),
            ):
                assert _refusal(call) is FilesReason.UNSUPPORTED_ENTRY
        kinds = {entry.name: entry.kind.value for entry in store.list_directory("").entries}
        assert kinds == {"fifo": "other", "sock": "other"}
    finally:
        listener.close()


def test_a_staging_file_replaced_by_a_fifo_is_refused(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path]
) -> None:
    root, _outside = layout
    store.begin_upload(UPLOAD_ID)
    staged = root / ".my-pa" / "staging" / UPLOAD_ID
    staged.unlink()
    os.mkfifo(staged)
    for call in (
        lambda: store.upload_offset(UPLOAD_ID),
        lambda: store.append_upload(UPLOAD_ID, 0, [b"x"], limit=10),
        lambda: store.upload_digest(UPLOAD_ID),
        lambda: store.publish_upload(UPLOAD_ID, "f", length=0, sha256="0" * 64),
        lambda: store.discard_upload(UPLOAD_ID),
    ):
        assert _refusal(call) is FilesReason.UNSUPPORTED_ENTRY


# --- links the store makes ---------------------------------------------------------------------


def test_no_link_the_store_makes_lands_outside_the_root(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path]
) -> None:
    """Every `linkat` is anchored to descriptors under the root, and every name is single-linked."""
    root, outside = layout
    before = _snapshot(outside)
    secret_links = (outside / "secret.txt").stat().st_nlink
    created = store.write_text("a.txt", "one")
    store.write_text(
        "a.txt", "two", expected_version=created.entry.version, preimage_version_id=VERSION_ID
    )
    store.move("a.txt", "b.txt")
    store.copy("b.txt", "c.txt")
    store.begin_upload(UPLOAD_ID)
    store.append_upload(UPLOAD_ID, 0, [b"bytes"], limit=5)
    store.publish_upload(UPLOAD_ID, "d.bin", length=5, sha256=hashlib.sha256(b"bytes").hexdigest())
    trashing = store.trash("c.txt", TRASH_ID)
    store.restore(TRASH_ID, "c.txt", trashed_version=trashing.trashed_version)
    for refused in ("../outside/x", "/etc/passwd", "a/../../outside/x"):
        assert _refusal(lambda refused=refused: store.move("b.txt", refused)) is (
            FilesReason.INVALID_PATH
        )
        assert _refusal(lambda refused=refused: store.copy("b.txt", refused)) is (
            FilesReason.INVALID_PATH
        )
    assert _snapshot(outside) == before
    assert (outside / "secret.txt").stat().st_nlink == secret_links
    for path in root.rglob("*"):
        if path.is_file():
            assert path.stat().st_nlink == 1, path.name


# --- validation before I/O ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["..", "../outside", "a/../b", "/etc/passwd", "/", "a//b", "a/", "./a", "a\\b", "a\x00b"],
)
def test_traversal_and_absolute_paths_are_refused_before_any_io(
    layout: tuple[Path, Path], tmp_path: Path, path: str
) -> None:
    root, _outside = layout
    store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
    root.rmdir()  # any filesystem access would now fail as `unavailable`, not `invalid_path`
    calls: list[Callable[[], object]] = [
        lambda: store.list_directory(path),
        lambda: store.stat(path),
        lambda: store.search(path, "x"),
        lambda: store.preview(path),
        lambda: store.mkdir(path, parents=True),
        lambda: store.move(path, "x"),
        lambda: store.move("x", path),
        lambda: store.copy(path, "x"),
        lambda: store.copy("x", path),
        lambda: store.trash(path, TRASH_ID),
        lambda: store.restore(TRASH_ID, path, trashed_version="fv1_" + "0" * 64),
        lambda: store.write_text(path, "x"),
        lambda: store.publish_upload(UPLOAD_ID, path, length=0, sha256="0" * 64),
        lambda: store.open_download(path, expected_version="fv1_" + "0" * 64),
    ]
    for call in calls:
        assert _refusal(call) is FilesReason.INVALID_PATH


# --- the control directory ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [".my-pa", ".my-pa/staging", ".my-pa/trash/" + TRASH_ID, ".MY-PA/versions", "a/.My-Pa/x"],
)
def test_the_control_directory_is_unreachable(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path], path: str
) -> None:
    root, _outside = layout
    (root / "a").write_bytes(b"x")
    store.trash("a", TRASH_ID)
    for call in (
        lambda: store.list_directory(path),
        lambda: store.stat(path),
        lambda: store.preview(path),
        lambda: store.open_download(path, expected_version="fv1_" + "0" * 64),
        lambda: store.move(path, "x"),
        lambda: store.copy(path, "x"),
        lambda: store.write_text(path, "x"),
        lambda: store.mkdir(path, parents=True),
    ):
        assert _refusal(call) is FilesReason.INVALID_PATH
    assert [entry.name for entry in store.list_directory("").entries] == []
    assert store.search("", "my-pa").entries == ()
    assert store.search("", TRASH_ID[:8]).entries == ()


def test_a_planted_control_directory_link_is_not_followed(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path]
) -> None:
    root, outside = layout
    (root / ".my-pa").symlink_to(outside, target_is_directory=True)
    (root / "a").write_bytes(b"x")
    before = _snapshot(outside)
    for call in (
        lambda: store.trash("a", TRASH_ID),
        lambda: store.begin_upload(UPLOAD_ID),
        lambda: store.write_text("b", "x"),
        lambda: store.copy("a", "c"),
    ):
        with pytest.raises(FileWorkspaceUnavailableError):
            call()
    assert _snapshot(outside) == before
    assert (root / "a").read_bytes() == b"x"


# --- no host path in any error ------------------------------------------------------------------


def test_an_os_error_naming_the_root_is_not_chained(
    layout: tuple[Path, Path], tmp_path: Path
) -> None:
    """`os.open(root)` fails with the host path in `filename`: it must not ride along.

    Neither in the formatted traceback nor anywhere down the `__context__` chain.
    """
    root, _outside = layout
    store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
    root.rmdir()
    for call in (
        lambda: store.list_directory(""),
        lambda: store.write_text("a", "x"),
        lambda: store.ensure_free_space(0),
    ):
        with pytest.raises(FileWorkspaceUnavailableError) as caught:
            call()
        error = caught.value
        assert error.__cause__ is None and error.__suppress_context__ is True
        assert str(tmp_path) not in "".join(traceback.format_exception(error))
        chained: BaseException | None = error
        while chained is not None:
            for rendered in (str(chained), repr(chained), str(chained.args)):
                assert str(tmp_path) not in rendered
            if isinstance(chained, OSError):
                assert chained.filename is None and chained.filename2 is None
            chained = chained.__context__


def test_a_constructor_refusal_chains_no_host_path(tmp_path: Path) -> None:
    """The root's `FileNotFoundError` is the implicit `__context__`: it must be scrubbed."""
    missing = tmp_path / "missing-root"
    with pytest.raises(FileWorkspaceRootError) as caught:
        FilesystemFileWorkspaceStore(missing)
    error = caught.value
    assert str(tmp_path) not in "".join(traceback.format_exception(error))
    chained: BaseException | None = error
    seen = 0
    while chained is not None:
        seen += 1
        for rendered in (str(chained), repr(chained), str(chained.args)):
            assert str(tmp_path) not in rendered
        if isinstance(chained, OSError):
            assert chained.filename is None and chained.filename2 is None
        chained = chained.__cause__ or chained.__context__
    assert seen >= 1


def test_no_exception_carries_a_host_path(
    store: FilesystemFileWorkspaceStore, layout: tuple[Path, Path], tmp_path: Path
) -> None:
    root, outside = layout
    (root / "f").write_bytes(b"x")
    (root / "link").symlink_to(outside, target_is_directory=True)
    (root / "d").mkdir()
    (root / "d").chmod(0)
    calls: list[Callable[[], object]] = [
        lambda: store.stat("missing"),
        lambda: store.list_directory("link"),
        lambda: store.list_directory("d"),
        lambda: store.mkdir("f"),
        lambda: store.move("f", "f2", expected_version="fv1_" + "0" * 64),
        lambda: store.copy("missing", "x"),
        lambda: store.open_preserved_version(VERSION_ID),
        lambda: store.restore(TRASH_ID, "x", trashed_version="fv1_" + "0" * 64),
        lambda: store.upload_offset(UPLOAD_ID),
        lambda: store.trash("f", "fwtrs_bad/../x"),
        lambda: FilesystemFileWorkspaceStore(tmp_path / "missing"),
    ]
    try:
        for call in calls:
            with pytest.raises((FilesDomainError, PortError)) as caught:
                call()
            error = caught.value
            for rendered in (str(error), repr(error), str(error.args)):
                assert str(tmp_path) not in rendered
                assert "secret" not in rendered and "outside" not in rendered
            assert error.__cause__ is None
    finally:
        (root / "d").chmod(0o700)
