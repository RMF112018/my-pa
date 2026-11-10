"""Reports Modernization WP05 C1/C2: the filesystem report content store on `tmp_path`.

What it proves, each against a real filesystem:

* a `put` lays out `<root>/content/<shard>/<grcnt_id>/{decoded,original}` with
  mode 0600 parts, and `read`/`verify`/`has`/`stored_object_ids` agree;
* `put` is exclusive (a second one refuses and changes nothing);
* `read`/`verify` refuse a part whose size or digest is not the expected one
  (`ReportContentIntegrityError`, with which) and an absent one
  (`ReportContentMissingError`), never returning the bytes;
* identifiers outside the namespace's kind -- traversal shapes, `mdver_`,
  uppercase -- are refused before anything is created;
* a symbolic link planted at a shard, or as a part, is refused: nothing is
  written or read outside the root;
* the root is refused when missing, a file, a link, or overlapping a source
  root, the managed document root or another avoided root;
* a write that fails part-way leaves nothing behind (no temporary, no part,
  no object directory);
* unreadable entries are reported relative to the root.

Every byte is synthetic.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.contracts.ports import (
    ReportContentIntegrityError,
    ReportContentMissingError,
    ReportContentNamespace,
    ReportContentPart,
    ReportContentStoreError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.report_content_stores.filesystem import (
    FilesystemReportContentStore,
    ReportContentRootError,
)

DECODED: Final = b"# Synthetic decoded report body\n"
ORIGINAL: Final = b"\x1f\x8b\x08synthetic-gzip-bytes"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _store(tmp_path: Path, **kwargs: Any) -> FilesystemReportContentStore:  # noqa: ANN401
    root = tmp_path / "report-content"
    root.mkdir(exist_ok=True)
    return FilesystemReportContentStore(root, **kwargs)


def _object_dir(store: FilesystemReportContentStore, object_id: str) -> Path:
    suffix = object_id.split("_", 1)[1]
    return store.root / "content" / suffix[:2] / object_id


def _read(store: FilesystemReportContentStore, object_id: str, part: ReportContentPart) -> bytes:
    data = DECODED if part is ReportContentPart.DECODED else ORIGINAL
    return store.read(object_id, part, expected_sha256=_sha(data), expected_byte_count=len(data))


def test_put_lays_out_both_parts_and_reads_them_back(tmp_path: Path) -> None:
    store = _store(tmp_path)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    assert not store.has(object_id)
    store.put(object_id, decoded=DECODED, original=ORIGINAL)
    directory = _object_dir(store, object_id)
    assert sorted(entry.name for entry in directory.iterdir()) == ["decoded", "original"]
    for part in directory.iterdir():
        assert part.stat().st_mode & 0o777 == 0o600
        assert part.stat().st_nlink == 1
    assert _read(store, object_id, ReportContentPart.DECODED) == DECODED
    assert _read(store, object_id, ReportContentPart.ORIGINAL) == ORIGINAL
    store.verify(
        object_id,
        ReportContentPart.DECODED,
        expected_sha256=_sha(DECODED),
        expected_byte_count=len(DECODED),
    )
    assert store.has(object_id)
    assert store.stored_object_ids() == (object_id,)
    assert store.unreadable_entries() == ()


def test_identity_content_stores_only_the_decoded_part(tmp_path: Path) -> None:
    store = _store(tmp_path)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=DECODED, original=None)
    assert [entry.name for entry in _object_dir(store, object_id).iterdir()] == ["decoded"]
    with pytest.raises(ReportContentMissingError):
        _read(store, object_id, ReportContentPart.ORIGINAL)


def test_put_is_exclusive_and_changes_nothing_on_refusal(tmp_path: Path) -> None:
    store = _store(tmp_path)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=DECODED, original=None)
    with pytest.raises(ReportContentStoreError, match="already exists"):
        store.put(object_id, decoded=b"other bytes", original=ORIGINAL)
    assert _read(store, object_id, ReportContentPart.DECODED) == DECODED
    assert [entry.name for entry in _object_dir(store, object_id).iterdir()] == ["decoded"]


@pytest.mark.parametrize(
    ("replacement", "mismatch"),
    [
        (b"# Synthetic decoded report bodY\n", "digest"),
        (DECODED[:-1], "size"),
        (DECODED + b"!", "size"),
    ],
)
def test_a_tampered_part_is_refused_and_never_returned(
    tmp_path: Path, replacement: bytes, mismatch: str
) -> None:
    store = _store(tmp_path)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=DECODED, original=None)
    part = _object_dir(store, object_id) / "decoded"
    part.write_bytes(replacement)
    with pytest.raises(ReportContentIntegrityError) as refused:
        _read(store, object_id, ReportContentPart.DECODED)
    assert refused.value.mismatch == mismatch
    assert replacement.decode(errors="replace") not in str(refused.value)
    with pytest.raises(ReportContentIntegrityError):
        store.verify(
            object_id,
            ReportContentPart.DECODED,
            expected_sha256=_sha(DECODED),
            expected_byte_count=len(DECODED),
        )


def test_a_missing_object_or_part_is_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    absent = issue_identifier(IdKind.REPORT_CONTENT)
    with pytest.raises(ReportContentMissingError):
        _read(store, absent, ReportContentPart.DECODED)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=DECODED, original=ORIGINAL)
    (_object_dir(store, object_id) / "original").unlink()
    with pytest.raises(ReportContentMissingError):
        _read(store, object_id, ReportContentPart.ORIGINAL)
    assert _read(store, object_id, ReportContentPart.DECODED) == DECODED


@pytest.mark.parametrize(
    "object_id",
    [
        "grcnt_../../escape0",
        "grcnt_abcd/efgh1234",
        "/etc/passwd",
        "../grcnt_abcdef0123",
        "",
        "grcnt_ABCDEF0123456789",
        "mdver_" + "a" * 32,
        "grver_" + "a" * 32,
        "grcnt_short",
        "grcnt_" + "a" * 65,
    ],
)
def test_identifiers_outside_the_namespace_are_refused_before_anything_is_made(
    tmp_path: Path, object_id: str
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ReportContentStoreError, match="not admitted"):
        store.put(object_id, decoded=DECODED, original=None)
    with pytest.raises(ReportContentStoreError, match="not admitted"):
        store.read(
            object_id,
            ReportContentPart.DECODED,
            expected_sha256=_sha(DECODED),
            expected_byte_count=len(DECODED),
        )
    assert list(store.root.iterdir()) == []
    assert sorted(path.name for path in tmp_path.iterdir()) == ["report-content"]


def test_a_symlinked_shard_cannot_carry_a_write_outside_the_root(tmp_path: Path) -> None:
    """The prove-red target for containment: the `O_NOFOLLOW` anchored walk."""
    store = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    shard = object_id.split("_", 1)[1][:2]
    (store.root / "content").mkdir()
    (store.root / "content" / shard).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ReportContentStoreError):
        store.put(object_id, decoded=DECODED, original=None)
    assert list(outside.iterdir()) == []
    assert not store.has(object_id)
    assert f"content/{shard}" in store.unreadable_entries()


def test_a_part_replaced_by_a_link_or_a_second_name_is_not_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(DECODED)
    linked = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(linked, decoded=DECODED, original=None)
    part = _object_dir(store, linked) / "decoded"
    part.unlink()
    part.symlink_to(outside)
    with pytest.raises(ReportContentMissingError):
        _read(store, linked, ReportContentPart.DECODED)
    hard = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(hard, decoded=DECODED, original=None)
    os.link(_object_dir(store, hard) / "decoded", tmp_path / "second-name")
    with pytest.raises(ReportContentMissingError):
        _read(store, hard, ReportContentPart.DECODED)
    unreadable = store.unreadable_entries()
    assert any(entry.endswith(f"{linked}/decoded") for entry in unreadable)
    assert any(entry.endswith(f"{hard}/decoded") for entry in unreadable)


def test_the_root_is_refused_unless_it_is_an_existing_real_directory(tmp_path: Path) -> None:
    with pytest.raises(ReportContentRootError):
        FilesystemReportContentStore(tmp_path / "absent")
    afile = tmp_path / "afile"
    afile.write_bytes(b"x")
    with pytest.raises(ReportContentRootError):
        FilesystemReportContentStore(afile)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ReportContentRootError, match="symbolic link"):
        FilesystemReportContentStore(link)
    with pytest.raises(ReportContentRootError):
        # WP05b made `preservation` a namespace; anything else stays refused.
        FilesystemReportContentStore(real, "archive")  # type: ignore[arg-type]


@pytest.mark.parametrize("relation", ["same", "inside", "contains"])
@pytest.mark.parametrize("which", ["source_roots", "managed_documents_root", "other_roots"])
def test_the_root_is_refused_when_it_overlaps_a_root_it_must_avoid(
    tmp_path: Path, relation: str, which: str
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    if relation == "same":
        root = other
    elif relation == "inside":
        root = other / "nested"
        root.mkdir()
    else:
        root = tmp_path
    choices: dict[str, dict[str, Any]] = {
        "source_roots": {"source_roots": [other]},
        "managed_documents_root": {"managed_documents_root": other},
        "other_roots": {"other_roots": [other]},
    }
    kwargs = choices[which]
    with pytest.raises(ReportContentRootError, match="stay clear"):
        FilesystemReportContentStore(root, ReportContentNamespace.CONTENT, **kwargs)


def test_an_overlap_through_a_link_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "inner").mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(source / "inner", target_is_directory=True)
    with pytest.raises(ReportContentRootError):
        FilesystemReportContentStore(source / "inner", source_roots=[tmp_path / "alias"])


@pytest.mark.parametrize("failing", ["link", "fsync", "write"])
def test_a_failed_put_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    store = _store(tmp_path)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    real = getattr(os, failing)
    calls = {"n": 0}

    def fail_on_the_second_part(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        calls["n"] += 1
        # The first call succeeds -- for `link`, the decoded part is published
        # -- so the failure meets a half-written object.
        if calls["n"] >= 2:
            raise OSError("synthetic failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(os, failing, fail_on_the_second_part)
    with pytest.raises(ReportContentStoreError):
        store.put(object_id, decoded=DECODED, original=ORIGINAL)
    monkeypatch.undo()
    assert not store.has(object_id)
    shard_dir = _object_dir(store, object_id).parent
    assert list(shard_dir.iterdir()) == []
    assert store.stored_object_ids() == ()
    assert store.unreadable_entries() == ()
    # And the identifier is still free: nothing of the failed call blocks a retry.
    store.put(object_id, decoded=DECODED, original=ORIGINAL)
    assert _read(store, object_id, ReportContentPart.ORIGINAL) == ORIGINAL


def test_unreadable_entries_name_every_malformed_entry(tmp_path: Path) -> None:
    store = _store(tmp_path)
    good = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(good, decoded=DECODED, original=None)
    content = store.root / "content"
    (content / "stray.txt").write_bytes(b"x")
    (content / "zzz").mkdir()
    shard = content / good.split("_", 1)[1][:2]
    (shard / "not-an-id").mkdir()
    wrong_shard = issue_identifier(IdKind.REPORT_CONTENT)
    while wrong_shard.split("_", 1)[1][:2] == shard.name:
        wrong_shard = issue_identifier(IdKind.REPORT_CONTENT)
    (shard / wrong_shard).mkdir()
    # Near-misses of the store's own temporary names stay unreadable (WP08 n2).
    for near_miss in ("x.decoded.tmp", ".decoded.tmp~", ".DECODED.tmp", ".decoded.tmp.1"):
        (_object_dir(store, good) / near_miss).write_bytes(b"leftover")
    no_decoded = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(no_decoded, decoded=DECODED, original=None)
    (_object_dir(store, no_decoded) / "decoded").unlink()
    unreadable = store.unreadable_entries()
    assert "content/stray.txt" in unreadable
    assert "content/zzz" in unreadable
    assert f"content/{shard.name}/not-an-id" in unreadable
    assert f"content/{shard.name}/{wrong_shard}" in unreadable
    for near_miss in ("x.decoded.tmp", ".decoded.tmp~", ".DECODED.tmp", ".decoded.tmp.1"):
        assert f"{_object_dir(store, good).relative_to(store.root)}/{near_miss}" in unreadable
    assert store.stale_temporaries() == ()
    assert f"{_object_dir(store, no_decoded).relative_to(store.root)}/decoded" in unreadable
    assert store.stored_object_ids() == tuple(sorted((good, no_decoded)))
    for entry in unreadable:
        assert not entry.startswith("/")


def _relative(store: FilesystemReportContentStore, object_id: str, name: str) -> str:
    return f"{_object_dir(store, object_id).relative_to(store.root)}/{name}"


def test_a_killed_puts_own_temporaries_are_stale_not_unreadable(tmp_path: Path) -> None:
    # WP08 (WP05b corrective n2): the three states a put killed by a signal
    # leaves. Nothing is removed, and the final parts still verify or refuse
    # exactly as before.
    store = _store(tmp_path)
    # 1. Killed while writing `.original.tmp`: `decoded` is final.
    original_tmp = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(original_tmp, decoded=DECODED, original=None)
    (_object_dir(store, original_tmp) / ".original.tmp").write_bytes(ORIGINAL[:3])
    # 2. Killed while writing `.decoded.tmp`: no final part yet.
    decoded_tmp = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(decoded_tmp, decoded=DECODED, original=None)
    folder = _object_dir(store, decoded_tmp)
    (folder / "decoded").rename(folder / ".decoded.tmp")
    # 3. Killed between `link` and `unlink`: the part and its temporary share an inode.
    linked_tmp = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(linked_tmp, decoded=DECODED, original=None)
    os.link(
        _object_dir(store, linked_tmp) / "decoded", _object_dir(store, linked_tmp) / ".decoded.tmp"
    )
    assert store.unreadable_entries() == ()
    assert store.stale_temporaries() == tuple(
        sorted(
            (
                _relative(store, original_tmp, ".original.tmp"),
                _relative(store, decoded_tmp, ".decoded.tmp"),
                _relative(store, linked_tmp, ".decoded.tmp"),
            )
        )
    )
    assert store.stored_object_ids() == tuple(sorted((original_tmp, decoded_tmp, linked_tmp)))
    assert _read(store, original_tmp, ReportContentPart.DECODED) == DECODED
    # A final part a temporary stands beside is still refused by read/verify.
    with pytest.raises(ReportContentMissingError):
        _read(store, decoded_tmp, ReportContentPart.DECODED)
    with pytest.raises(ReportContentMissingError):
        _read(store, linked_tmp, ReportContentPart.DECODED)
    # Nothing was removed by the scan.
    assert (_object_dir(store, original_tmp) / ".original.tmp").exists()
    assert (folder / ".decoded.tmp").exists()


def test_only_a_regular_file_of_the_exact_name_is_a_stale_temporary(tmp_path: Path) -> None:
    store = _store(tmp_path)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(DECODED)
    symlinked = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(symlinked, decoded=DECODED, original=None)
    (_object_dir(store, symlinked) / ".original.tmp").symlink_to(outside)
    directory = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(directory, decoded=DECODED, original=None)
    (_object_dir(store, directory) / ".decoded.tmp").mkdir()
    # A second name of a part that is NOT its own temporary stays unreadable.
    foreign_link = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(foreign_link, decoded=DECODED, original=None)
    (_object_dir(store, foreign_link) / ".decoded.tmp").write_bytes(b"other")
    os.link(_object_dir(store, foreign_link) / "decoded", tmp_path / "second-name")
    # A missing `decoded` beside only `.original.tmp` stays unreadable.
    wrong_sibling = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(wrong_sibling, decoded=DECODED, original=None)
    folder = _object_dir(store, wrong_sibling)
    (folder / "decoded").rename(folder / ".original.tmp")
    unreadable = store.unreadable_entries()
    assert _relative(store, symlinked, ".original.tmp") in unreadable
    assert _relative(store, directory, ".decoded.tmp") in unreadable
    assert _relative(store, foreign_link, "decoded") in unreadable
    assert _relative(store, wrong_sibling, "decoded") in unreadable
    assert store.stale_temporaries() == tuple(
        sorted(
            (
                _relative(store, foreign_link, ".decoded.tmp"),
                _relative(store, wrong_sibling, ".original.tmp"),
            )
        )
    )


def test_a_put_fsyncs_every_parent_whose_directory_it_created(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Corrective N1: a newly made `content/` and shard are durable names in their parents."""
    store = _store(tmp_path)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    real = os.fsync
    synced: list[int] = []

    def spy(descriptor: int) -> None:
        synced.append(os.fstat(descriptor).st_ino)
        real(descriptor)

    monkeypatch.setattr(os, "fsync", spy)
    store.put(object_id, decoded=DECODED, original=None)
    monkeypatch.undo()
    directory = _object_dir(store, object_id)
    for parent in (store.root, store.root / "content", directory.parent, directory):
        assert parent.stat().st_ino in synced, parent.relative_to(tmp_path)

    # A second object in an existing shard makes no directory but its own.
    sibling = issue_identifier(IdKind.REPORT_CONTENT)
    while sibling.split("_", 1)[1][:2] != directory.parent.name:
        sibling = issue_identifier(IdKind.REPORT_CONTENT)
    synced.clear()
    monkeypatch.setattr(os, "fsync", spy)
    store.put(sibling, decoded=DECODED, original=None)
    monkeypatch.undo()
    assert store.root.stat().st_ino not in synced
    assert (store.root / "content").stat().st_ino not in synced
    assert directory.parent.stat().st_ino in synced
