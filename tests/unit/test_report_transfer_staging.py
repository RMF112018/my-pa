"""Reports Modernization WP06 T13/T15: transfer staging and the range read, on `tmp_path`.

What it proves, each against a real filesystem:

* `ReportContentStore.read_range` returns exactly `[offset, offset+length)`,
  streams the WHOLE part through the size and digest checks (a byte tampered
  OUTSIDE the range still refuses), refuses a missing part and out-of-bounds
  ranges, and holds O(length) memory (tracemalloc, a 16 MiB part);
* the content store refuses to be constructed on `ReportContentNamespace.TRANSFER`;
* `FilesystemReportTransferStaging` lays chunks out as
  `transfer/<shard>/<grxfr id>/<NN>-<sha256>`, 0600, single-link; a put/read
  roundtrip verifies; a crash leftover (published file or temporary) is
  reused or replaced; only lowercase `grxfr_` ids are admitted;
* DISCARD CONFINEMENT: with content and preservation objects planted in the
  same root, symlinks and a subdirectory inside a staged session, and
  hard-linked files, discarding every session removes only its own chunk
  files -- every planted object still reads back verified;
* the content scan, backup and preservation scan give identical results with
  and without a populated transfer tree;
* `bootstrap.gateway.report_transfer_staging` composes it from the content
  root, `None` when unset, with the same root refusals.

Every byte is synthetic.
"""

from __future__ import annotations

import hashlib
import os
import random
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.application.report_content import back_up_report_content, scan_report_content
from my_pa.application.report_preservation import scan_report_preservation
from my_pa.bootstrap import gateway
from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import (
    ReportContentIntegrityError,
    ReportContentMissingError,
    ReportContentNamespace,
    ReportContentPart,
    ReportContentStoreError,
    ReportTransferStagingError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.records import ManagedContentRecord
from my_pa.domain.reports.vocabulary import ContentEncoding
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.report_content_stores.filesystem import (
    FilesystemReportContentStore,
    ReportContentRootError,
)
from my_pa.infrastructure.report_content_stores.staging import (
    CHUNK_FILE_PATTERN,
    FilesystemReportTransferStaging,
    chunk_file_name,
)
from tests.conftest import InMemoryReportContentStore

_URL: Final = "postgresql+psycopg://synthetic@127.0.0.1/synthetic"
MIB: Final = 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "report-content"
    root.mkdir(exist_ok=True)
    return root


def _session() -> str:
    return issue_identifier(IdKind.REPORT_TRANSFER_SESSION)


def _session_dir(root: Path, session_id: str) -> Path:
    return root / "transfer" / session_id.split("_", 1)[1][:2] / session_id


def _tree(root: Path) -> dict[str, tuple[int, str]]:
    """Every regular file under `root` (links not followed): relative name -> (size, sha)."""
    result: dict[str, tuple[int, str]] = {}
    for directory, _dirs, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(directory) / name
            if path.is_symlink():
                result[str(path.relative_to(root))] = (-1, str(path.readlink()))
            else:
                result[str(path.relative_to(root))] = (path.stat().st_size, _sha(path.read_bytes()))
    return result


# ---- read_range ---------------------------------------------------------------------


def _content_store(root: Path) -> FilesystemReportContentStore:
    return FilesystemReportContentStore(root, ReportContentNamespace.CONTENT)


def _random_bytes(size: int, seed: int = 7) -> bytes:
    return random.Random(seed).randbytes(size)  # noqa: S311 - synthetic data


def _range(
    store: Any,  # noqa: ANN401
    object_id: str,
    data: bytes,
    offset: int,
    length: int,
    part: ReportContentPart = ReportContentPart.DECODED,
) -> bytes:
    return bytes(
        store.read_range(
            object_id,
            part,
            offset=offset,
            length=length,
            expected_sha256=_sha(data),
            expected_byte_count=len(data),
        )
    )


@pytest.mark.parametrize("in_memory", [False, True], ids=["filesystem", "in_memory"])
def test_read_range_returns_exactly_the_range(tmp_path: Path, in_memory: bool) -> None:
    store: Any = InMemoryReportContentStore() if in_memory else _content_store(_root(tmp_path))
    data = _random_bytes(3 * MIB + 12345)
    original = _random_bytes(1000, seed=8)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=data, original=original)
    cases = [
        (0, 1),
        (0, 262144),
        (1, 262144),
        (MIB - 5, 10),  # across a 1 MiB slice boundary
        (2 * MIB - 1, MIB + 2),  # spans whole slices
        (len(data) - 3, 262144),  # cut at the end
        (len(data) - 1, 1),
        (len(data), 5),  # offset == total: empty
        (0, len(data) + 10),
    ]
    for offset, length in cases:
        assert _range(store, object_id, data, offset, length) == data[offset : offset + length]
    assert _range(store, object_id, original, 10, 20, ReportContentPart.ORIGINAL) == original[10:30]


@pytest.mark.parametrize("in_memory", [False, True], ids=["filesystem", "in_memory"])
def test_read_range_refuses_out_of_bounds_ranges(tmp_path: Path, in_memory: bool) -> None:
    store: Any = InMemoryReportContentStore() if in_memory else _content_store(_root(tmp_path))
    data = b"synthetic range body"
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=data, original=None)
    for offset, length in [
        (-1, 1),
        (len(data) + 1, 1),
        (0, 0),
        (0, -1),
        (True, 1),
        (0, True),
        (0.0, 1),
        (0, 1.0),
    ]:
        with pytest.raises(ReportContentStoreError):
            _range(store, object_id, data, offset, length)  # type: ignore[arg-type]


def test_a_byte_tampered_outside_the_range_still_refuses(tmp_path: Path) -> None:
    root = _root(tmp_path)
    store = _content_store(root)
    data = _random_bytes(2 * MIB)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=data, original=None)
    part = root / "content" / object_id.split("_", 1)[1][:2] / object_id / "decoded"
    tampered = bytearray(data)
    tampered[-1] ^= 0x01  # far outside [0, 16)
    part.chmod(0o600)
    part.write_bytes(bytes(tampered))
    with pytest.raises(ReportContentIntegrityError) as raised:
        _range(store, object_id, data, 0, 16)
    assert raised.value.mismatch == "digest"
    part.write_bytes(data + b"x")
    with pytest.raises(ReportContentIntegrityError) as raised:
        _range(store, object_id, data, 0, 16)
    assert raised.value.mismatch == "size"
    part.write_bytes(data[:-1])
    with pytest.raises(ReportContentIntegrityError):
        _range(store, object_id, data, 0, 16)
    # The in-memory fake verifies the whole part too.
    fake = InMemoryReportContentStore()
    fake.put(object_id, decoded=data, original=None)
    fake.objects[object_id][ReportContentPart.DECODED] = bytes(tampered)
    with pytest.raises(ReportContentIntegrityError):
        _range(fake, object_id, data, 0, 16)


def test_read_range_of_a_missing_object_or_part_is_missing(tmp_path: Path) -> None:
    store = _content_store(_root(tmp_path))
    data = b"synthetic"
    absent = issue_identifier(IdKind.REPORT_CONTENT)
    with pytest.raises(ReportContentMissingError):
        _range(store, absent, data, 0, 1)
    present = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(present, decoded=data, original=None)
    with pytest.raises(ReportContentMissingError):
        _range(store, present, data, 0, 1, ReportContentPart.ORIGINAL)
    with pytest.raises(ReportContentStoreError):
        _range(store, "grprv_" + "0" * 32, data, 0, 1)


def test_read_range_holds_memory_of_the_range_not_the_part(tmp_path: Path) -> None:
    store = _content_store(_root(tmp_path))
    data = _random_bytes(16 * MIB)
    object_id = issue_identifier(IdKind.REPORT_CONTENT)
    store.put(object_id, decoded=data, original=None)
    digest = _sha(data)
    expected = data[8 * MIB + 3 : 8 * MIB + 3 + 262144]
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        chunk = store.read_range(
            object_id,
            ReportContentPart.DECODED,
            offset=8 * MIB + 3,
            length=262144,
            expected_sha256=digest,
            expected_byte_count=len(data),
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert chunk == expected
    print(f"read_range 16 MiB part, 256 KiB range: tracemalloc peak {peak} bytes")
    assert peak < 2 * MIB


def test_the_content_store_refuses_the_transfer_namespace(tmp_path: Path) -> None:
    with pytest.raises(ReportContentRootError):
        FilesystemReportContentStore(_root(tmp_path), ReportContentNamespace.TRANSFER)
    assert ReportContentNamespace.TRANSFER.value == "transfer"


# ---- staging: layout, roundtrip, crash leftovers -----------------------------------


def _staging(root: Path) -> FilesystemReportTransferStaging:
    return FilesystemReportTransferStaging(root)


def test_a_chunk_roundtrips_under_its_digest_named_file(tmp_path: Path) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    assert not staging.has_session(session_id)
    first, last = _random_bytes(262144), b"synthetic tail"
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(first), data=first)
    staging.put_chunk(session_id, 1, chunk_sha256=_sha(last), data=last)
    directory = _session_dir(root, session_id)
    names = sorted(entry.name for entry in directory.iterdir())
    assert names == sorted([f"00-{_sha(first)}", f"01-{_sha(last)}"])
    for entry in directory.iterdir():
        status = entry.stat()
        assert status.st_mode & 0o777 == 0o600 and status.st_nlink == 1
    assert directory.stat().st_mode & 0o777 == 0o700
    assert staging.has_session(session_id)
    assert staging.staged_session_ids() == (session_id,)
    assert staging.unreadable_entries() == ()
    assert (
        staging.read_chunk(session_id, 0, chunk_sha256=_sha(first), expected_byte_count=262144)
        == first
    )
    assert (
        staging.read_chunk(session_id, 1, chunk_sha256=_sha(last), expected_byte_count=len(last))
        == last
    )
    assert chunk_file_name(7, _sha(last)) == f"07-{_sha(last)}"


def test_a_put_of_an_identical_chunk_again_is_verified_and_accepted(tmp_path: Path) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    data = b"synthetic chunk"
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    before = _tree(root)
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    assert _tree(root) == before
    # A published file of the same name with other bytes (impossible by
    # construction, but tampered) refuses rather than being overwritten.
    path = _session_dir(root, session_id) / f"00-{_sha(data)}"
    path.write_bytes(b"other bytes")
    with pytest.raises(ReportTransferStagingError):
        staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    assert path.read_bytes() == b"other bytes"
    with pytest.raises(ReportTransferStagingError):
        staging.read_chunk(session_id, 0, chunk_sha256=_sha(data), expected_byte_count=len(data))


def test_a_retry_with_other_bytes_lands_beside_never_over(tmp_path: Path) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    one, two = b"synthetic one", b"synthetic two"
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(one), data=one)
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(two), data=two)
    assert (
        staging.read_chunk(session_id, 0, chunk_sha256=_sha(one), expected_byte_count=len(one))
        == one
    )
    assert (
        staging.read_chunk(session_id, 0, chunk_sha256=_sha(two), expected_byte_count=len(two))
        == two
    )


def test_a_crash_leftover_published_file_or_temporary_is_reused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    data = b"synthetic crash-retried chunk"
    name = f"00-{_sha(data)}"
    directory = _session_dir(root, session_id)
    directory.mkdir(parents=True, mode=0o700)
    # A temporary left by a crash (partial bytes): removed and rewritten.
    (directory / f".{name}.tmp").write_bytes(data[:5])
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    assert sorted(entry.name for entry in directory.iterdir()) == [name]
    assert (directory / name).read_bytes() == data
    # A complete published file left by a crash whose response was lost.
    other_session = _session()
    other_directory = _session_dir(root, other_session)
    other_directory.mkdir(parents=True, mode=0o700)
    (other_directory / name).write_bytes(data)
    staging.put_chunk(other_session, 0, chunk_sha256=_sha(data), data=data)
    assert sorted(entry.name for entry in other_directory.iterdir()) == [name]


def test_a_put_refuses_a_wrong_digest_size_or_sequence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    data = b"synthetic"
    for kwargs in (
        {"sequence": 0, "chunk_sha256": _sha(b"other"), "data": data},
        {"sequence": 0, "chunk_sha256": _sha(b""), "data": b""},
        {"sequence": 0, "chunk_sha256": _sha(b"x" * 262145), "data": b"x" * 262145},
        {"sequence": 64, "chunk_sha256": _sha(data), "data": data},
        {"sequence": -1, "chunk_sha256": _sha(data), "data": data},
        {"sequence": True, "chunk_sha256": _sha(data), "data": data},
        {"sequence": 0, "chunk_sha256": _sha(data).upper(), "data": data},
        {"sequence": 0, "chunk_sha256": "../" + _sha(data)[3:], "data": data},
        {"sequence": 0, "chunk_sha256": _sha(data), "data": bytearray(data)},
    ):
        with pytest.raises(ReportTransferStagingError) as raised:
            staging.put_chunk(session_id, **kwargs)  # type: ignore[arg-type]
        assert session_id not in str(raised.value)
    assert not (root / "transfer").exists()


@pytest.mark.parametrize(
    "session_id",
    [
        "grcnt_" + "0" * 32,
        "grprv_" + "0" * 32,
        "grxfr_" + "AB" * 16,
        "grxfr_../../content",
        "grxfr_" + "0" * 7,
        "../grxfr_" + "0" * 32,
        "grxfr_" + "0" * 32 + "/x",
        "mdver_" + "0" * 32,
        "",
        7,
        None,
    ],
)
def test_every_operation_refuses_a_non_transfer_identifier(
    tmp_path: Path,
    session_id: Any,  # noqa: ANN401
) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    data = b"synthetic"
    calls = [
        lambda: staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data),
        lambda: staging.read_chunk(
            session_id, 0, chunk_sha256=_sha(data), expected_byte_count=len(data)
        ),
        lambda: staging.has_session(session_id),
        lambda: staging.discard(session_id),
    ]
    for call in calls:
        with pytest.raises(ReportTransferStagingError) as raised:
            call()
        assert str(session_id) not in str(raised.value) or not session_id
    assert list(root.iterdir()) == []


def test_a_missing_chunk_or_session_refuses_the_read(tmp_path: Path) -> None:
    staging = _staging(_root(tmp_path))
    session_id = _session()
    data = b"synthetic"
    with pytest.raises(ReportTransferStagingError):
        staging.read_chunk(session_id, 0, chunk_sha256=_sha(data), expected_byte_count=len(data))
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    with pytest.raises(ReportTransferStagingError):
        staging.read_chunk(session_id, 1, chunk_sha256=_sha(data), expected_byte_count=len(data))
    with pytest.raises(ReportTransferStagingError):
        staging.read_chunk(
            session_id, 0, chunk_sha256=_sha(data), expected_byte_count=len(data) + 1
        )


def test_the_staging_root_has_the_content_stores_root_refusals(tmp_path: Path) -> None:
    root = _root(tmp_path)
    with pytest.raises(ReportContentRootError):
        FilesystemReportTransferStaging(tmp_path / "absent")
    link = tmp_path / "link"
    link.symlink_to(root)
    with pytest.raises(ReportContentRootError):
        FilesystemReportTransferStaging(link)
    for kwargs in (
        {"source_roots": [root / "inside"]},
        {"source_roots": [tmp_path]},
        {"managed_documents_root": root},
        {"other_roots": [root]},
    ):
        with pytest.raises(ReportContentRootError):
            FilesystemReportTransferStaging(root, **kwargs)


def test_a_symlinked_transfer_or_shard_directory_is_never_followed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "transfer").symlink_to(outside, target_is_directory=True)
    staging = _staging(root)
    session_id = _session()
    data = b"synthetic"
    with pytest.raises(ReportTransferStagingError):
        staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    with pytest.raises(ReportTransferStagingError):
        staging.discard(session_id)
    assert list(outside.iterdir()) == []
    assert staging.staged_session_ids() == ()
    assert staging.unreadable_entries() == ("transfer",)


def _decoy_session_tree(tmp_path: Path) -> tuple[Path, str]:
    """A well-formed `transfer/` tree OUTSIDE the root holding one decoy session."""
    decoy = tmp_path / "decoy"
    decoy_root = decoy / "root"
    decoy_root.mkdir(parents=True)
    decoy_staging = _staging(decoy_root)
    decoy_session = _session()
    data = b"synthetic decoy"
    decoy_staging.put_chunk(decoy_session, 0, chunk_sha256=_sha(data), data=data)
    return decoy_root / "transfer", decoy_session


def test_the_scan_never_enters_a_symlinked_shard_or_session(tmp_path: Path) -> None:
    """WP08 C-WP06 (R1 #5): links planted at shard and session level are reported, never walked."""
    root = _root(tmp_path)
    staging = _staging(root)
    real = _session()
    data = b"synthetic"
    staging.put_chunk(real, 0, chunk_sha256=_sha(data), data=data)
    decoy_transfer, decoy_session = _decoy_session_tree(tmp_path)
    decoy_shard = decoy_session.split("_", 1)[1][:2]
    # A shard-level link to the decoy's shard, and a session-level link (inside the
    # real session's shard, under a well-formed id) to the decoy's session directory.
    real_shard = real.split("_", 1)[1][:2]
    linked_shard = next(name for name in ("zz", "yy", "xx") if name != real_shard)
    (root / "transfer" / linked_shard).symlink_to(
        decoy_transfer / decoy_shard, target_is_directory=True
    )
    impostor = _session()
    while impostor.split("_", 1)[1][:2] != real_shard:
        impostor = _session()
    (root / "transfer" / real_shard / impostor).symlink_to(
        decoy_transfer / decoy_shard / decoy_session, target_is_directory=True
    )
    before = _tree(decoy_transfer.parent)
    assert staging.staged_session_ids() == (real,)
    assert staging.unreadable_entries() == tuple(
        sorted((f"transfer/{linked_shard}", f"transfer/{real_shard}/{impostor}"))
    )
    assert _tree(decoy_transfer.parent) == before


def test_the_scan_stays_anchored_when_transfer_is_swapped_for_a_link_mid_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP08 C-WP06 (R1 #5): a `transfer` swapped for a link after it was checked is not walked.

    The swap is made at the scan's first touch of `transfer` (opening it, or
    listing it by path), i.e. after any check of it: an anchored scan lists the
    directory it opened; a path-resolving scan would list the decoy.
    """
    root = _root(tmp_path)
    staging = _staging(root)
    real = _session()
    data = b"synthetic"
    staging.put_chunk(real, 0, chunk_sha256=_sha(data), data=data)
    decoy_transfer, decoy_session = _decoy_session_tree(tmp_path)
    transfer = root / "transfer"
    swapped: list[bool] = []

    def swap() -> None:
        if not swapped:
            swapped.append(True)
            transfer.rename(root / "transfer-moved")
            transfer.symlink_to(decoy_transfer, target_is_directory=True)

    real_open = os.open
    real_scandir = os.scandir

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:  # noqa: ANN401
        descriptor = real_open(path, flags, *args, **kwargs)
        if path == "transfer" and kwargs.get("dir_fd") is not None:
            swap()
        return descriptor

    def spy_scandir(path: Any = ".") -> Any:  # noqa: ANN401
        if not isinstance(path, int) and Path(path) == transfer:
            swap()
        return real_scandir(path)

    monkeypatch.setattr(os, "open", spy_open)
    monkeypatch.setattr(os, "scandir", spy_scandir)
    assert staging.staged_session_ids() == (real,)
    assert swapped == [True]
    assert decoy_session != real


# ---- discard and its confinement -----------------------------------------------------


def test_discard_removes_the_session_and_is_idempotent(tmp_path: Path) -> None:
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    assert staging.discard(session_id) is False
    for sequence in range(3):
        data = f"synthetic chunk {sequence}".encode()
        staging.put_chunk(session_id, sequence, chunk_sha256=_sha(data), data=data)
    # A crash leftover temporary of the chunk pattern is removed too.
    (_session_dir(root, session_id) / f".03-{'b' * 64}.tmp").write_bytes(b"partial")
    assert staging.discard(session_id) is True
    assert not _session_dir(root, session_id).exists()
    assert not staging.has_session(session_id)
    assert staging.discard(session_id) is False
    assert staging.staged_session_ids() == ()


@dataclass
class _Planted:
    content: FilesystemReportContentStore
    preservation: FilesystemReportContentStore
    content_id: str
    preservation_id: str
    decoded: bytes = field(default=b"# Synthetic planted content body\n")
    original: bytes = field(default=b"\x1f\x8b\x08synthetic-planted-gzip")
    seal: bytes = field(default=b"synthetic planted preservation seal")

    def intact(self) -> None:
        assert (
            self.content.read(
                self.content_id,
                ReportContentPart.DECODED,
                expected_sha256=_sha(self.decoded),
                expected_byte_count=len(self.decoded),
            )
            == self.decoded
        )
        assert (
            self.content.read(
                self.content_id,
                ReportContentPart.ORIGINAL,
                expected_sha256=_sha(self.original),
                expected_byte_count=len(self.original),
            )
            == self.original
        )
        assert (
            self.preservation.read(
                self.preservation_id,
                ReportContentPart.DECODED,
                expected_sha256=_sha(self.seal),
                expected_byte_count=len(self.seal),
            )
            == self.seal
        )


def _plant(root: Path) -> _Planted:
    content = FilesystemReportContentStore(root, ReportContentNamespace.CONTENT)
    preservation = FilesystemReportContentStore(root, ReportContentNamespace.PRESERVATION)
    planted = _Planted(
        content=content,
        preservation=preservation,
        content_id=issue_identifier(IdKind.REPORT_CONTENT),
        preservation_id=issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT),
    )
    content.put(planted.content_id, decoded=planted.decoded, original=planted.original)
    preservation.put(planted.preservation_id, decoded=planted.seal, original=None)
    return planted


def _object_dir(root: Path, namespace: str, object_id: str) -> Path:
    return root / namespace / object_id.split("_", 1)[1][:2] / object_id


def test_discard_never_reaches_content_or_preservation_objects(tmp_path: Path) -> None:
    root = _root(tmp_path)
    planted = _plant(root)
    staging = _staging(root)
    content_dir = _object_dir(root, "content", planted.content_id)
    preservation_dir = _object_dir(root, "preservation", planted.preservation_id)
    outside = tmp_path / "outside-file"
    outside.write_bytes(b"synthetic outside bytes")

    sessions = [_session() for _ in range(3)]
    for session_id in sessions:
        data = f"synthetic staged {session_id}".encode()
        staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    first, second, third = (_session_dir(root, session_id) for session_id in sessions)
    # Symlinks inside a session, one of them NAMED like a chunk, at content parts.
    (first / f"01-{'c' * 64}").symlink_to(content_dir / "decoded")
    (first / "decoded").symlink_to(content_dir / "decoded")
    (first / f".02-{'d' * 64}.tmp").symlink_to(preservation_dir / "decoded")
    # A subdirectory named like a chunk, holding a chunk-named file.
    nested = second / f"01-{'e' * 64}"
    nested.mkdir()
    (nested / f"00-{'f' * 64}").write_bytes(b"synthetic nested")
    # A hard-linked chunk-named file (a second name of a file outside the root).
    os.link(outside, third / f"01-{'a' * 64}")
    # A session directory that is itself a symlink to a content object directory.
    linked_session = _session()
    linked_parent = _session_dir(root, linked_session).parent
    linked_parent.mkdir(parents=True, exist_ok=True)
    _session_dir(root, linked_session).symlink_to(content_dir, target_is_directory=True)
    content_tree = _tree(root / "content")
    preservation_tree = _tree(root / "preservation")

    for session_id in sessions:
        assert staging.discard(session_id) is True
    with pytest.raises(ReportTransferStagingError):
        staging.discard(linked_session)

    planted.intact()
    assert _tree(root / "content") == content_tree
    assert _tree(root / "preservation") == preservation_tree
    assert outside.read_bytes() == b"synthetic outside bytes"
    # What was not ours is left, with its session directory, and reported.
    assert sorted(entry.name for entry in first.iterdir()) == sorted(
        [f"01-{'c' * 64}", "decoded", f".02-{'d' * 64}.tmp"]
    )
    assert (nested / f"00-{'f' * 64}").read_bytes() == b"synthetic nested"
    assert (third / f"01-{'a' * 64}").stat().st_nlink == 2
    unreadable = staging.unreadable_entries()
    first_relative = str(first.relative_to(root))
    assert f"{first_relative}/01-{'c' * 64}" in unreadable
    assert f"{first_relative}/decoded" in unreadable
    assert str(nested.relative_to(root)) in unreadable
    assert f"{third.relative_to(root)}/01-{'a' * 64}" in unreadable
    assert str(_session_dir(root, linked_session).relative_to(root)) in unreadable
    # Discarding again removes nothing more.
    for session_id in sessions:
        assert staging.discard(session_id) is False
    planted.intact()


def test_discard_leaves_a_plain_regular_file_with_a_foreign_name(tmp_path: Path) -> None:
    # A regular, single-link file passes the regular-file gate: only the chunk-name gate keeps it.
    root = _root(tmp_path)
    staging = _staging(root)
    session_id = _session()
    data = b"synthetic staged chunk"
    staging.put_chunk(session_id, 0, chunk_sha256=_sha(data), data=data)
    session_dir = _session_dir(root, session_id)
    foreign = session_dir / "operator-note"
    foreign.write_bytes(b"synthetic note")
    assert foreign.stat().st_nlink == 1

    assert staging.discard(session_id) is True

    assert foreign.read_bytes() == b"synthetic note"
    assert sorted(entry.name for entry in session_dir.iterdir()) == ["operator-note"]
    assert f"{session_dir.relative_to(root)}/operator-note" in staging.unreadable_entries()
    assert staging.discard(session_id) is False
    assert foreign.read_bytes() == b"synthetic note"


def test_discard_cannot_name_a_content_or_preservation_object(tmp_path: Path) -> None:
    root = _root(tmp_path)
    planted = _plant(root)
    staging = _staging(root)
    for object_id in (planted.content_id, planted.preservation_id):
        with pytest.raises(ReportTransferStagingError):
            staging.discard(object_id)
        with pytest.raises(ReportTransferStagingError):
            staging.discard(
                object_id.replace("grcnt_", "grxfr_").replace("grprv_", "grxfr_").upper()
            )
    # The same suffix as a transfer id lands under `transfer/`, never `content/`.
    same_suffix = "grxfr_" + planted.content_id.split("_", 1)[1]
    assert staging.discard(same_suffix) is False
    planted.intact()


def test_the_chunk_file_pattern_is_the_names_written() -> None:
    import re

    name = chunk_file_name(63, "0" * 64)
    assert re.fullmatch(CHUNK_FILE_PATTERN, name)
    assert not re.fullmatch(CHUNK_FILE_PATTERN, "decoded")


# ---- the content plane's scans ignore the transfer tree --------------------------------


@dataclass
class _Repository:
    records: tuple[ManagedContentRecord, ...]

    def managed_content(self, *, principal_id: str) -> tuple[ManagedContentRecord, ...]:
        return self.records

    def known_managed_content_ids(self) -> frozenset[str]:
        return frozenset(record.content_id for record in self.records)

    def hold_seal_events(self) -> tuple[()]:
        return ()


def test_scan_backup_and_preservation_scan_ignore_a_populated_transfer_tree(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    planted = _plant(root)
    record = ManagedContentRecord(
        content_id=planted.content_id,
        encoding=ContentEncoding.GZIP_BASE64,
        decoded_sha256=_sha(planted.decoded),
        decoded_byte_count=len(planted.decoded),
        original_sha256=_sha(planted.original),
        original_byte_count=len(planted.original),
    )
    repository: Any = _Repository((record,))

    def results(backup_name: str) -> tuple[Any, ...]:
        backup_root = tmp_path / backup_name
        backup_root.mkdir()
        backup = FilesystemReportContentStore(backup_root, other_roots=[root])
        summary = back_up_report_content(
            repository, planted.content, backup, principal_id="prn_" + "a" * 24
        )
        return (
            scan_report_content(repository, planted.content, principal_id="prn_" + "a" * 24),
            scan_report_preservation(repository, planted.preservation),
            planted.content.stored_object_ids(),
            planted.content.unreadable_entries(),
            planted.preservation.stored_object_ids(),
            planted.preservation.unreadable_entries(),
            summary,
            sorted(_tree(backup_root).values()),
        )

    before = results("backup-before")
    staging = _staging(root)
    for _ in range(3):
        session_id = _session()
        for sequence in range(2):
            data = _random_bytes(1000, seed=sequence)
            staging.put_chunk(session_id, sequence, chunk_sha256=_sha(data), data=data)
    (root / "transfer" / "zz").mkdir()  # a malformed staging entry too
    after = results("backup-after")
    assert after == before
    assert not (tmp_path / "backup-after" / "transfer").exists()
    assert before[0].orphans == () and before[0].unreadable == ()


# ---- composition -------------------------------------------------------------------


class _Engine:
    @contextmanager
    def begin(self) -> Any:  # noqa: ANN401
        yield object()


def test_the_gateway_composes_staging_from_the_content_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unset = load_settings({"MY_PA_DATABASE_URL": _URL})
    assert gateway.report_transfer_staging(unset, _Engine()) is None  # type: ignore[arg-type]
    root = _root(tmp_path)
    configured = load_settings({"MY_PA_DATABASE_URL": _URL, "MY_PA_REPORT_CONTENT_ROOT": str(root)})
    monkeypatch.setattr(gateway, "configured_source_roots", lambda _connection: ())
    staging = gateway.report_transfer_staging(configured, _Engine())  # type: ignore[arg-type]
    assert isinstance(staging, FilesystemReportTransferStaging)
    assert staging.root == root.resolve()
    assert "report_transfer_staging" in gateway.__all__
    # The same refusal as the content store for a root inside a source root.
    monkeypatch.setattr(gateway, "configured_source_roots", lambda _connection: (str(tmp_path),))
    with pytest.raises(ReportContentRootError):
        gateway.report_transfer_staging(configured, _Engine())  # type: ignore[arg-type]
    with pytest.raises(ReportContentRootError):
        gateway.report_content_store(configured, _Engine())  # type: ignore[arg-type]
