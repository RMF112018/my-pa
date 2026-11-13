"""Files workspace WP3: the filesystem store's behaviour on synthetic temporary roots.

Every operation of `FilesystemFileWorkspaceStore` against the contract's
sections 4-8: CAS and no-overwrite refusals, zero-byte files, preimages on
replace, trash and restore round trips (files and directories), copy bounds,
preview cuts, resumable upload staging, external-change detection, and the
reserved control directory staying out of every listing.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from my_pa.contracts.ports import FileWorkspaceRootError
from my_pa.domain.files.errors import FilesArgumentError, FilesRefusal
from my_pa.domain.files.versions import EntryKind
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.infrastructure.file_workspace import store as store_module
from my_pa.infrastructure.file_workspace.store import FilesystemFileWorkspaceStore

TRASH_ID = "fwtrs_abcdef0123456789"
TRASH_ID_2 = "fwtrs_abcdef0123456780"
VERSION_ID = "fwver_abcdef0123456789"
VERSION_ID_2 = "fwver_abcdef0123456780"
UPLOAD_ID = "fwupl_abcdef0123456789"
UPLOAD_ID_2 = "fwupl_abcdef0123456780"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def store(root: Path) -> FilesystemFileWorkspaceStore:
    return FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)


def _reason(caught: pytest.ExceptionInfo[FilesRefusal]) -> FilesReason:
    return caught.value.reason


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _touch_later(path: Path, data: bytes) -> None:
    """An external edit that moves size, mtime and ctime."""
    path.write_bytes(data)
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


# --- construction ------------------------------------------------------------------


def test_the_root_must_be_absolute_existing_and_a_directory(root: Path, tmp_path: Path) -> None:
    with pytest.raises(FileWorkspaceRootError):
        FilesystemFileWorkspaceStore(Path("relative/root"))
    with pytest.raises(FileWorkspaceRootError):
        FilesystemFileWorkspaceStore(tmp_path / "missing")
    plain = tmp_path / "plain"
    plain.write_bytes(b"")
    with pytest.raises(FileWorkspaceRootError):
        FilesystemFileWorkspaceStore(plain)
    with pytest.raises(FilesArgumentError):
        FilesystemFileWorkspaceStore(root, disk_reserve_bytes=-1)


# --- list and stat -------------------------------------------------------------------


def test_list_sorts_by_name_bytes_pages_and_hides_reserved_names(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    # No two names differ only by case: the default macOS volume folds case.
    for name in ("b", "C", "a", "\u00e9", "Z", ".DS_Store"):
        (root / name).write_bytes(b"x")
    for reserved in (".my-pa", "@EADIR", "#recycle", "#snapshot"):
        (root / reserved).mkdir()
    (root / "back\\slash").write_bytes(b"x")
    store.write_text("note.txt", "hi")  # creates .my-pa/staging lazily

    page = store.list_directory("")
    names = [entry.name for entry in page.entries]
    assert names == sorted(names, key=lambda name: name.encode())
    assert names == [".DS_Store", "C", "Z", "a", "b", "note.txt", "\u00e9"]
    assert page.next_after is None

    first = store.list_directory("", page_size=3)
    assert [entry.name for entry in first.entries] == [".DS_Store", "C", "Z"]
    assert first.next_after == "Z"
    second = store.list_directory("", after=first.next_after, page_size=3)
    assert [entry.name for entry in second.entries] == ["a", "b", "note.txt"]
    third = store.list_directory("", after=second.next_after, page_size=3)
    assert [entry.name for entry in third.entries] == ["\u00e9"]
    assert third.next_after is None


def test_list_reports_other_kinds_without_following_them(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "dir").mkdir()
    (root / "dir" / "inner").write_bytes(b"secret")
    (root / "link").symlink_to(root / "dir")
    os.mkfifo(root / "fifo")
    kinds = {entry.name: entry.kind for entry in store.list_directory("").entries}
    assert kinds == {"dir": EntryKind.DIRECTORY, "fifo": EntryKind.OTHER, "link": EntryKind.OTHER}
    with pytest.raises(FilesRefusal) as caught:
        store.list_directory("link")
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY


def test_list_refusals(store: FilesystemFileWorkspaceStore, root: Path) -> None:
    (root / "file").write_bytes(b"")
    with pytest.raises(FilesRefusal) as caught:
        store.list_directory("missing")
    assert _reason(caught) is FilesReason.NOT_FOUND
    with pytest.raises(FilesRefusal) as caught:
        store.list_directory("file")
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY
    with pytest.raises(FilesArgumentError):
        store.list_directory("", page_size=201)
    with pytest.raises(FilesArgumentError):
        store.list_directory("", page_size=0)


def test_stat_shapes_entries_and_hashes_on_request(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "d").mkdir()
    (root / "d" / "empty").write_bytes(b"")
    (root / "d" / "data").write_bytes(b"hello")
    empty = store.stat("d/empty", include_sha256=True)
    assert (empty.path, empty.name, empty.kind, empty.size) == (
        "d/empty",
        "empty",
        EntryKind.FILE,
        0,
    )
    assert empty.sha256 == _sha(b"")
    assert empty.version.startswith("fv1_") and len(empty.version) == 68
    data = store.stat("d/data")
    assert data.sha256 is None and data.size == 5
    directory = store.stat("d", include_sha256=True)
    assert directory.kind is EntryKind.DIRECTORY and directory.size is None
    assert directory.sha256 is None
    assert store.stat("d/data").version == data.version
    _touch_later(root / "d" / "data", b"hello!")
    assert store.stat("d/data").version != data.version


# --- search ----------------------------------------------------------------------


def test_search_is_a_case_insensitive_bounded_name_walk(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "Reports" / "2026").mkdir(parents=True)
    (root / "Reports" / "2026" / "Q1-report.TXT").write_bytes(b"")
    (root / "Reports" / "summary").write_bytes(b"")
    (root / "@eaDir").mkdir()
    (root / "@eaDir" / "report-thumb").write_bytes(b"")
    (root / "outside").mkdir()
    (root / "outside" / "report-behind-link").write_bytes(b"")
    (root / "Reports" / "linked").symlink_to(root / "outside")

    found = store.search("", "REPORT")
    assert [entry.path for entry in found.entries] == [
        "Reports",
        "Reports/2026/Q1-report.TXT",
        "outside/report-behind-link",
    ]
    assert found.truncated is False
    scoped = store.search("Reports", "report")
    assert [entry.path for entry in scoped.entries] == ["Reports/2026/Q1-report.TXT"]

    paged = store.search("", "report", page_size=1)
    assert len(paged.entries) == 1 and paged.truncated is True
    with pytest.raises(FilesArgumentError):
        store.search("", "")
    with pytest.raises(FilesArgumentError):
        store.search("", "x" * 256)


def test_search_stops_at_the_depth_and_entry_caps(
    store: FilesystemFileWorkspaceStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep = root
    for _ in range(store_module.SEARCH_WALK_MAX_DEPTH + 2):
        deep = deep / "n"
        deep.mkdir()
    found = store.search("", "n")
    assert len(found.entries) == store_module.SEARCH_WALK_MAX_DEPTH
    assert found.truncated is True

    monkeypatch.setattr(store_module, "SEARCH_WALK_MAX_ENTRIES", 5)
    wide = root / "wide"
    wide.mkdir()
    for index in range(10):
        (wide / f"w{index}").write_bytes(b"")
    capped = store.search("wide", "w")
    assert len(capped.entries) == 5 and capped.truncated is True


# --- preview ------------------------------------------------------------------------


def test_preview_cuts_on_character_boundaries_and_continues(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    text = "aé€\U0001f600z"  # 1 + 2 + 3 + 4 + 1 bytes
    (root / "t.txt").write_bytes(text.encode())
    collected = []
    offset: int | None = 0
    while offset is not None:
        window = store.preview("t.txt", offset=offset, max_bytes=2)
        assert window.binary is False and window.text is not None
        assert window.text  # always progresses, even when a character is wider
        collected.append(window.text)
        offset = window.next_offset
    assert "".join(collected) == text
    assert collected[:2] == ["a", "é"]

    whole = store.preview("t.txt")
    assert whole.text == text and whole.next_offset is None
    assert store.preview("t.txt", offset=100).text == ""


def test_preview_exceeds_max_bytes_only_for_one_character(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    """A window smaller than its first character grows to that character, never further."""
    (root / "e.txt").write_bytes("éé".encode())
    window = store.preview("e.txt", max_bytes=1)
    assert (window.text, window.binary, window.next_offset) == ("é", False, 2)
    (root / "emoji.txt").write_bytes("\U0001f600\U0001f600".encode())
    for limit in (1, 2, 3):
        window = store.preview("emoji.txt", max_bytes=limit)
        assert (window.text, window.next_offset) == ("\U0001f600", 4)
    (root / "mixed.txt").write_bytes("€a".encode())
    assert store.preview("mixed.txt", max_bytes=2).text == "€"


def test_preview_at_a_mid_character_offset_skips_to_the_next_boundary(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    """Valid UTF-8 read from inside a character is text, starting at the next character."""
    (root / "t.txt").write_bytes("aé€z".encode())  # é at 1-2, € at 3-5, z at 6
    window = store.preview("t.txt", offset=2)
    assert (window.text, window.binary, window.next_offset) == ("€z", False, None)
    window = store.preview("t.txt", offset=4, max_bytes=1)
    assert (window.text, window.binary, window.next_offset) == ("z", False, None)
    window = store.preview("t.txt", offset=4, max_bytes=2)
    assert (window.text, window.next_offset) == ("z", None)
    (root / "tail.txt").write_bytes("a€".encode())
    window = store.preview("tail.txt", offset=2)  # only continuation bytes remain
    assert (window.text, window.binary, window.next_offset) == ("", False, None)
    (root / "bad.txt").write_bytes(b"a\x80\x80\x80\x80b")  # more than a character's tail
    assert store.preview("bad.txt", offset=1).binary is True


def test_preview_flags_binary_and_checks_the_version(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "bin").write_bytes(b"\xff\xfe\x00binary")
    window = store.preview("bin")
    assert (window.binary, window.text, window.next_offset) == (True, None, None)
    (root / "empty").write_bytes(b"")
    assert store.preview("empty").text == ""
    version = store.stat("bin").version
    _touch_later(root / "bin", b"changed")
    with pytest.raises(FilesRefusal) as caught:
        store.preview("bin", expected_version=version)
    assert _reason(caught) is FilesReason.VERSION_CONFLICT
    (root / "dir").mkdir()
    with pytest.raises(FilesRefusal) as caught:
        store.preview("dir")
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY
    with pytest.raises(FilesArgumentError):
        store.preview("bin", max_bytes=store_module.MAX_PREVIEW_BYTES + 1)


# --- mkdir ------------------------------------------------------------------------


def test_mkdir_never_overwrites_and_creates_parents_on_request(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    entry = store.mkdir("new")
    assert entry.kind is EntryKind.DIRECTORY and (root / "new").is_dir()
    with pytest.raises(FilesRefusal) as caught:
        store.mkdir("new")
    assert _reason(caught) is FilesReason.EXISTS
    with pytest.raises(FilesRefusal) as caught:
        store.mkdir("a/b/c")
    assert _reason(caught) is FilesReason.NOT_FOUND
    assert store.mkdir("a/b/c", parents=True).path == "a/b/c"
    assert (root / "a" / "b" / "c").is_dir()
    (root / "file").write_bytes(b"")
    with pytest.raises(FilesRefusal) as caught:
        store.mkdir("file/sub", parents=True)
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY


# --- move and rename --------------------------------------------------------------------


def test_move_files_and_directories_without_overwriting(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "a.txt").write_bytes(b"A")
    (root / "b.txt").write_bytes(b"B")
    (root / "dir" / "sub").mkdir(parents=True)
    (root / "dir" / "sub" / "x").write_bytes(b"X")

    with pytest.raises(FilesRefusal) as caught:
        store.move("a.txt", "b.txt")
    assert _reason(caught) is FilesReason.EXISTS
    assert (root / "b.txt").read_bytes() == b"B"

    moved = store.move("a.txt", "dir/renamed.txt")
    assert moved.path == "dir/renamed.txt" and moved.kind is EntryKind.FILE
    assert not (root / "a.txt").exists()
    assert (root / "dir" / "renamed.txt").read_bytes() == b"A"
    assert (root / "dir" / "renamed.txt").stat().st_nlink == 1

    (root / "target").mkdir()
    with pytest.raises(FilesRefusal) as caught:
        store.move("dir", "target")
    assert _reason(caught) is FilesReason.EXISTS
    assert store.move("dir", "target/dir").kind is EntryKind.DIRECTORY
    assert (root / "target" / "dir" / "sub" / "x").read_bytes() == b"X"

    with pytest.raises(FilesRefusal) as caught:
        store.move("target", "target/inside")
    assert _reason(caught) is FilesReason.INVALID_PATH
    with pytest.raises(FilesRefusal) as caught:
        store.move("target", "target")
    assert _reason(caught) is FilesReason.EXISTS
    with pytest.raises(FilesRefusal) as caught:
        store.move("absent", "elsewhere")
    assert _reason(caught) is FilesReason.NOT_FOUND


def test_move_compares_the_expected_version(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "f").write_bytes(b"one")
    version = store.stat("f").version
    _touch_later(root / "f", b"two")
    with pytest.raises(FilesRefusal) as caught:
        store.move("f", "g", expected_version=version)
    assert _reason(caught) is FilesReason.VERSION_CONFLICT
    assert store.move("f", "g", expected_version=store.stat("f").version).path == "g"
    with pytest.raises(FilesArgumentError):
        store.move("g", "h", expected_version="fv1_nothex")


def test_move_detects_an_external_change_between_observation_and_rename(
    store: FilesystemFileWorkspaceStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "f").write_bytes(b"original")
    monkeypatch.setattr(store, "_checkpoint", lambda _stage: _touch_later(root / "f", b"edited"))
    with pytest.raises(FilesRefusal) as caught:
        store.move("f", "g")
    assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED
    assert (root / "f").read_bytes() == b"edited"
    assert not (root / "g").exists()


# --- copy ----------------------------------------------------------------------------


def test_copy_a_file_through_staging(store: FilesystemFileWorkspaceStore, root: Path) -> None:
    (root / "src.bin").write_bytes(b"\x00payload")
    (root / "zero").write_bytes(b"")
    entry = store.copy("src.bin", "dst.bin")
    assert entry.size == 8 and (root / "dst.bin").read_bytes() == b"\x00payload"
    assert store.copy("zero", "zero-copy").size == 0
    with pytest.raises(FilesRefusal) as caught:
        store.copy("src.bin", "dst.bin")
    assert _reason(caught) is FilesReason.EXISTS
    staging = root / ".my-pa" / "staging"
    assert list(staging.iterdir()) == []
    assert (root / ".my-pa").stat().st_mode & 0o777 == 0o700


def test_copy_a_directory_tree_and_its_bounds(
    store: FilesystemFileWorkspaceStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (root / "tree" / "a" / "b").mkdir(parents=True)
    (root / "tree" / "top").write_bytes(b"T")
    (root / "tree" / "a" / "b" / "leaf").write_bytes(b"L")
    (root / "tree" / "a" / "empty").write_bytes(b"")
    (root / "tree" / "@eaDir").mkdir()
    copied = store.copy("tree", "tree-copy")
    assert copied.kind is EntryKind.DIRECTORY
    assert (root / "tree-copy" / "a" / "b" / "leaf").read_bytes() == b"L"
    assert (root / "tree-copy" / "a" / "empty").read_bytes() == b""
    assert not (root / "tree-copy" / "@eaDir").exists()

    with pytest.raises(FilesRefusal) as caught:
        store.copy("tree", "tree/inner")
    assert _reason(caught) is FilesReason.INVALID_PATH

    monkeypatch.setattr(store_module, "SEARCH_WALK_MAX_ENTRIES", 2)
    with pytest.raises(FilesRefusal) as caught:
        store.copy("tree", "tree-capped")
    assert _reason(caught) is FilesReason.TOO_LARGE
    assert not (root / "tree-capped").exists()
    assert list((root / ".my-pa" / "staging").iterdir()) == []


def test_copy_refuses_a_tree_holding_another_kind(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "tree").mkdir()
    (root / "tree" / "link").symlink_to(root / "tree")
    with pytest.raises(FilesRefusal) as caught:
        store.copy("tree", "copy")
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY
    assert not (root / "copy").exists()


@pytest.mark.parametrize("name", ["back\\slash", "control\x01char"])
def test_copy_refuses_a_tree_holding_an_unaddressable_name(
    store: FilesystemFileWorkspaceStore, root: Path, name: str
) -> None:
    """A name no request could spell would be silently dropped: the copy is refused instead.

    Reserved names stay omitted (as listing and search omit them); see the
    `@eaDir` case in the tree copy test above.
    """
    (root / "tree" / "sub").mkdir(parents=True)
    (root / "tree" / "ok").write_bytes(b"ok")
    (root / "tree" / "sub" / name).write_bytes(b"unaddressable")
    with pytest.raises(FilesRefusal) as caught:
        store.copy("tree", "copy")
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY
    assert not (root / "copy").exists()
    staging = root / ".my-pa" / "staging"
    assert not staging.exists() or list(staging.iterdir()) == []


def test_copy_respects_the_disk_reserve(root: Path) -> None:
    starved = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=1 << 62)
    (root / "f").write_bytes(b"x")
    with pytest.raises(FilesRefusal) as caught:
        starved.copy("f", "g")
    assert _reason(caught) is FilesReason.QUOTA
    with pytest.raises(FilesRefusal) as caught:
        starved.write_text("t", "x")
    assert _reason(caught) is FilesReason.QUOTA


# --- trash and restore ----------------------------------------------------------------


def test_trash_and_restore_a_file(store: FilesystemFileWorkspaceStore, root: Path) -> None:
    (root / "doc.txt").write_bytes(b"keep me")
    before = store.stat("doc.txt")
    trashing = store.trash("doc.txt", TRASH_ID, expected_version=before.version)
    assert trashing.entry == before
    assert not (root / "doc.txt").exists()
    assert (root / ".my-pa" / "trash" / TRASH_ID).read_bytes() == b"keep me"
    assert ".my-pa" not in [entry.name for entry in store.list_directory("").entries]

    restored = store.restore(TRASH_ID, "doc.txt", trashed_version=trashing.trashed_version)
    assert restored.path == "doc.txt" and (root / "doc.txt").read_bytes() == b"keep me"
    assert not (root / ".my-pa" / "trash" / TRASH_ID).exists()
    with pytest.raises(FilesRefusal) as caught:
        store.restore(TRASH_ID, "doc.txt", trashed_version=trashing.trashed_version)
    assert _reason(caught) is FilesReason.NOT_FOUND


def test_trash_and_restore_a_directory_to_another_path(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "project" / "sub").mkdir(parents=True)
    (root / "project" / "sub" / "f").write_bytes(b"F")
    trashing = store.trash("project", TRASH_ID)
    assert trashing.entry.kind is EntryKind.DIRECTORY
    (root / "project").mkdir()  # the original path is taken again
    with pytest.raises(FilesRefusal) as caught:
        store.restore(TRASH_ID, "project", trashed_version=trashing.trashed_version)
    assert _reason(caught) is FilesReason.EXISTS
    restored = store.restore(TRASH_ID, "project-restored", trashed_version=trashing.trashed_version)
    assert restored.kind is EntryKind.DIRECTORY
    assert (root / "project-restored" / "sub" / "f").read_bytes() == b"F"


def test_restore_refuses_a_trashed_object_whose_fingerprint_drifted(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "f").write_bytes(b"one")
    trashing = store.trash("f", TRASH_ID)
    _touch_later(root / ".my-pa" / "trash" / TRASH_ID, b"tampered")
    with pytest.raises(FilesRefusal) as caught:
        store.restore(TRASH_ID, "f", trashed_version=trashing.trashed_version)
    assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED
    assert not (root / "f").exists()


def test_trash_ids_are_shape_checked_and_never_reused(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "a").write_bytes(b"")
    (root / "b").write_bytes(b"")
    for bad in ("fwver_abcdef0123456789", "fwtrs_short", "fwtrs_../../x", "", None):
        with pytest.raises(FilesArgumentError):
            store.trash("a", bad)  # type: ignore[arg-type]
    store.trash("a", TRASH_ID)
    with pytest.raises(FilesRefusal) as caught:
        store.trash("b", TRASH_ID)
    assert _reason(caught) is FilesReason.EXISTS
    assert (root / "b").exists()
    with pytest.raises(FilesRefusal) as caught:
        store.restore(TRASH_ID_2, "a", trashed_version="fv1_" + "0" * 64)
    assert _reason(caught) is FilesReason.NOT_FOUND


# --- write_text and preimages ------------------------------------------------------------


def test_write_text_creates_and_replaces_with_a_preimage(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    created = store.write_text("notes.md", "first é")
    assert created.preimage_version_id is None
    assert (root / "notes.md").read_text(encoding="utf-8") == "first é"
    with pytest.raises(FilesRefusal) as caught:
        store.write_text("notes.md", "again")
    assert _reason(caught) is FilesReason.EXISTS
    with pytest.raises(FilesArgumentError):
        store.write_text("notes.md", "again", expected_version=created.entry.version)

    replaced = store.write_text(
        "notes.md",
        "second",
        expected_version=created.entry.version,
        preimage_version_id=VERSION_ID,
    )
    assert replaced.preimage_version_id == VERSION_ID
    assert (root / "notes.md").read_bytes() == b"second"
    with store.open_preserved_version(VERSION_ID) as preserved:
        assert b"".join(preserved.read_range(0, preserved.size)) == "first é".encode()
    assert (root / "notes.md").stat().st_nlink == 1
    assert (root / ".my-pa" / "versions" / VERSION_ID).stat().st_nlink == 1

    with pytest.raises(FilesRefusal) as caught:
        store.write_text(
            "notes.md",
            "third",
            expected_version=created.entry.version,
            preimage_version_id=VERSION_ID_2,
        )
    assert _reason(caught) is FilesReason.VERSION_CONFLICT
    with pytest.raises(FilesRefusal) as caught:
        store.write_text(
            "notes.md",
            "third",
            expected_version=replaced.entry.version,
            preimage_version_id=VERSION_ID,
        )
    assert _reason(caught) is FilesReason.EXISTS
    assert (root / "notes.md").read_bytes() == b"second"
    assert list((root / ".my-pa" / "staging").iterdir()) == []


def test_write_text_limits_and_zero_bytes(store: FilesystemFileWorkspaceStore, root: Path) -> None:
    assert store.write_text("empty", "").entry.size == 0
    with pytest.raises(FilesRefusal) as caught:
        store.write_text("big", "x" * (store_module.MAX_WRITE_TEXT_BYTES + 1))
    assert _reason(caught) is FilesReason.TOO_LARGE
    with pytest.raises(FilesRefusal) as caught:
        store.write_text("missing", "x", expected_version="fv1_" + "0" * 64)
    assert _reason(caught) is FilesReason.NOT_FOUND
    (root / "d").mkdir()
    with pytest.raises(FilesRefusal) as caught:
        store.write_text(
            "d", "x", expected_version=store.stat("d").version, preimage_version_id=VERSION_ID
        )
    assert _reason(caught) is FilesReason.UNSUPPORTED_ENTRY


def test_replace_detects_an_external_change_before_the_rename(
    store: FilesystemFileWorkspaceStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = store.write_text("f", "mine")
    monkeypatch.setattr(store, "_checkpoint", lambda _stage: _touch_later(root / "f", b"theirs!"))
    with pytest.raises(FilesRefusal) as caught:
        store.write_text(
            "f", "new", expected_version=created.entry.version, preimage_version_id=VERSION_ID
        )
    assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED
    assert (root / "f").read_bytes() == b"theirs!"
    assert not (root / ".my-pa" / "versions" / VERSION_ID).exists()


# --- upload staging ------------------------------------------------------------------------


def test_upload_staging_resumes_and_publishes(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    payload = b"0123456789" * 1000
    store.begin_upload(UPLOAD_ID)
    with pytest.raises(FilesRefusal) as caught:
        store.begin_upload(UPLOAD_ID)
    assert _reason(caught) is FilesReason.EXISTS
    assert store.upload_offset(UPLOAD_ID) == 0
    assert (
        store.append_upload(UPLOAD_ID, 0, [payload[:3000], payload[3000:4000]], limit=10_000)
        == 4000
    )
    with pytest.raises(FilesRefusal) as caught:
        store.append_upload(UPLOAD_ID, 3999, [payload[3999:]], limit=10_000)
    assert _reason(caught) is FilesReason.OFFSET_MISMATCH
    assert store.upload_offset(UPLOAD_ID) == 4000
    with pytest.raises(FilesRefusal) as caught:
        store.append_upload(UPLOAD_ID, 4000, [payload[4000:9000], b"x" * 2000], limit=10_000)
    assert _reason(caught) is FilesReason.TOO_LARGE
    assert store.upload_offset(UPLOAD_ID) == 4000
    assert store.append_upload(UPLOAD_ID, 4000, iter([payload[4000:]]), limit=10_000) == 10_000
    assert store.upload_digest(UPLOAD_ID) == (10_000, _sha(payload))

    with pytest.raises(FilesRefusal) as caught:
        store.publish_upload(UPLOAD_ID, "up.bin", length=10_000, sha256=_sha(b"other"))
    assert _reason(caught) is FilesReason.DIGEST_MISMATCH
    assert not (root / "up.bin").exists()
    published = store.publish_upload(UPLOAD_ID, "up.bin", length=10_000, sha256=_sha(payload))
    assert published.preimage_version_id is None and published.entry.size == 10_000
    assert (root / "up.bin").read_bytes() == payload
    with pytest.raises(FilesRefusal) as caught:
        store.upload_offset(UPLOAD_ID)
    assert _reason(caught) is FilesReason.NOT_FOUND


def test_staged_uploads_are_private_and_published_files_keep_the_umask_mode(root: Path) -> None:
    """Bytes waiting in `.my-pa/staging` are 0600; what is published gets `0666 & ~umask`."""
    previous = os.umask(0o022)
    try:
        store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
        store.begin_upload(UPLOAD_ID)
        staged = root / ".my-pa" / "staging" / UPLOAD_ID
        assert staged.stat().st_mode & 0o777 == 0o600
        store.append_upload(UPLOAD_ID, 0, [b"payload"], limit=100)
        assert staged.stat().st_mode & 0o777 == 0o600
        store.publish_upload(UPLOAD_ID, "up.bin", length=7, sha256=_sha(b"payload"))
        assert (root / "up.bin").stat().st_mode & 0o777 == 0o644
        store.write_text("t.txt", "text")
        assert (root / "t.txt").stat().st_mode & 0o777 == 0o644
        store.copy("t.txt", "t-copy.txt")
        assert (root / "t-copy.txt").stat().st_mode & 0o777 == 0o644
        (root / "tree").mkdir()
        (root / "tree" / "leaf").write_bytes(b"L")
        store.copy("tree", "tree-copy")
        assert (root / "tree-copy" / "leaf").stat().st_mode & 0o777 == 0o644
    finally:
        os.umask(previous)


def test_a_failing_fsync_does_not_mask_the_append_failure(
    store: FilesystemFileWorkspaceStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.begin_upload(UPLOAD_ID)

    def chunks() -> Iterator[bytes]:
        yield b"kept"
        raise RuntimeError("the client went away")

    def failing_fsync(_descriptor: int) -> None:
        raise OSError(5, "simulated")

    monkeypatch.setattr(store_module.os, "fsync", failing_fsync)
    with pytest.raises(RuntimeError, match="the client went away"):
        store.append_upload(UPLOAD_ID, 0, chunks(), limit=100)
    monkeypatch.undo()
    assert store.upload_offset(UPLOAD_ID) == 4


def test_upload_replace_preserves_the_preimage_and_zero_bytes_are_valid(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "f").write_bytes(b"old")
    version = store.stat("f").version
    store.begin_upload(UPLOAD_ID)
    with pytest.raises(FilesRefusal) as caught:
        store.publish_upload(UPLOAD_ID, "f", length=0, sha256=_sha(b""))
    assert _reason(caught) is FilesReason.EXISTS
    published = store.publish_upload(
        UPLOAD_ID,
        "f",
        length=0,
        sha256=_sha(b""),
        expected_version=version,
        preimage_version_id=VERSION_ID,
    )
    assert published.preimage_version_id == VERSION_ID and published.entry.size == 0
    assert (root / "f").read_bytes() == b""
    assert (root / ".my-pa" / "versions" / VERSION_ID).read_bytes() == b"old"


def test_a_refused_upload_publication_leaves_the_staged_file_private(root: Path) -> None:
    """A refusal inside publication (preimage id taken) puts the staged file back to 0600."""
    previous = os.umask(0o022)
    try:
        store = FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0)
        (root / "f").write_bytes(b"old")
        version = store.stat("f").version
        (root / ".my-pa" / "versions").mkdir(parents=True)
        (root / ".my-pa" / "versions" / VERSION_ID).write_bytes(b"taken")
        store.begin_upload(UPLOAD_ID)
        store.append_upload(UPLOAD_ID, 0, [b"new"], limit=100)
        with pytest.raises(FilesRefusal) as caught:
            store.publish_upload(
                UPLOAD_ID,
                "f",
                length=3,
                sha256=_sha(b"new"),
                expected_version=version,
                preimage_version_id=VERSION_ID,
            )
        assert _reason(caught) is FilesReason.EXISTS
        staged = root / ".my-pa" / "staging" / UPLOAD_ID
        assert staged.stat().st_mode & 0o777 == 0o600
        assert (root / "f").read_bytes() == b"old"
    finally:
        os.umask(previous)


def test_the_umask_is_read_without_being_changed_when_proc_reports_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where `/proc/self/status` reports `Umask:` the umask is read, never set."""
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nUmask:\t0027\nState:\tR\n")

    def no_umask(_mask: int) -> int:
        raise AssertionError("the umask was set")

    monkeypatch.setattr(store_module, "_PROC_STATUS", status)
    monkeypatch.setattr(store_module.os, "umask", no_umask)
    assert store_module._process_umask() == 0o027


@pytest.mark.parametrize("content", [None, "Name:\tpython\n", "Umask:\tnot-octal\n"])
def test_the_umask_falls_back_to_set_and_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None
) -> None:
    """Without a readable `Umask:` line the umask is set to 0o077 and put straight back."""
    status = tmp_path / "status"
    if content is not None:
        status.write_text(content)
    monkeypatch.setattr(store_module, "_PROC_STATUS", status)
    previous = os.umask(0o027)
    try:
        assert store_module._process_umask() == 0o027
        assert os.umask(0o027) == 0o027
    finally:
        os.umask(previous)


def test_upload_discard_and_reap(store: FilesystemFileWorkspaceStore, root: Path) -> None:
    assert store.discard_upload(UPLOAD_ID) is False
    store.begin_upload(UPLOAD_ID)
    store.begin_upload(UPLOAD_ID_2)
    assert store.discard_upload(UPLOAD_ID) is True
    assert store.discard_upload(UPLOAD_ID) is False
    assert store.reap_uploads([UPLOAD_ID, UPLOAD_ID_2]) == 1
    assert list((root / ".my-pa" / "staging").iterdir()) == []
    with pytest.raises(FilesArgumentError):
        store.begin_upload("fwdnl_abcdef0123456789")


# --- downloads -----------------------------------------------------------------------------


def test_download_reads_ranges_of_the_bound_version(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    data = bytes(range(256)) * 10
    (root / "f").write_bytes(data)
    version = store.stat("f").version
    with store.open_download("f", expected_version=version) as reader:
        assert reader.size == len(data) and reader.version == version
        assert b"".join(reader.read_range(10, 20)) == data[10:30]
        assert b"".join(reader.read_range(2550, 100)) == data[2550:]
        assert reader.sha256() == _sha(data)
        # A rename-replace of the path unlinks the held inode, which moves its
        # ctime: the next read refuses rather than serving a superseded file.
        (root / "replacement").write_bytes(b"new")
        (root / "replacement").replace(root / "f")
        with pytest.raises(FilesRefusal) as caught:
            list(reader.read_range(0, 4))
        assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED

    with pytest.raises(FilesRefusal) as caught:
        store.open_download("f", expected_version=version)
    assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED


def test_download_refuses_an_in_place_change_after_open(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "f").write_bytes(b"abc")
    reader = store.open_download("f", expected_version=store.stat("f").version)
    try:
        with (root / "f").open("ab") as handle:
            handle.write(b"def")
        with pytest.raises(FilesRefusal) as caught:
            list(reader.read_range(0, 3))
        assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED
    finally:
        reader.close()
        reader.close()


def test_read_range_checks_the_version_when_called(
    store: FilesystemFileWorkspaceStore, root: Path
) -> None:
    (root / "f").write_bytes(b"abc")
    with store.open_download("f", expected_version=store.stat("f").version) as reader:
        (root / "f").write_bytes(b"abcdef")
        with pytest.raises(FilesRefusal) as caught:
            reader.read_range(0, 3)  # refused before any iteration
        assert _reason(caught) is FilesReason.EXTERNAL_CHANGE_DETECTED
        with pytest.raises(FilesArgumentError):
            reader.read_range(-1, 3)


def test_a_destination_taken_inside_the_rename_window_is_exists(
    store: FilesystemFileWorkspaceStore, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The absence check cannot see a directory created just before `rename`."""
    (root / "src" / "inner").mkdir(parents=True)
    (root / "dst" / "theirs").mkdir(parents=True)
    observe = store._lstat

    def blind(directory: int, name: str) -> os.stat_result | None:
        return None if name == "dst" else observe(directory, name)

    monkeypatch.setattr(store, "_lstat", blind)
    with pytest.raises(FilesRefusal) as caught:
        store.move("src", "dst")
    assert _reason(caught) is FilesReason.EXISTS
    assert (root / "src" / "inner").is_dir() and (root / "dst" / "theirs").is_dir()


def test_free_space_reserve(root: Path) -> None:
    FilesystemFileWorkspaceStore(root, disk_reserve_bytes=0).ensure_free_space(1)
    with pytest.raises(FilesRefusal) as caught:
        FilesystemFileWorkspaceStore(root, disk_reserve_bytes=1 << 62).ensure_free_space(0)
    assert _reason(caught) is FilesReason.QUOTA
