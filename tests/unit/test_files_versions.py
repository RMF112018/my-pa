"""Files workspace contract section 4: entry kinds and `fv1_` version tokens."""

from __future__ import annotations

import pytest

from my_pa.domain.files.errors import FilesArgumentError
from my_pa.domain.files.versions import (
    EntryKind,
    parse_version_token,
    validate_version_token,
    version_token,
)

BASE = {"dev": 1, "ino": 2, "kind": EntryKind.FILE, "size": 3, "mtime_ns": 4, "ctime_ns": 5}


def test_entry_kinds_are_the_contract_set() -> None:
    assert [kind.value for kind in EntryKind] == ["file", "directory", "other"]


def test_golden_tokens_are_stable() -> None:
    # SHA-256 of {"ctime_ns":5,"dev":1,"ino":2,"kind":"file","mtime_ns":4,"size":3,"v":1}.
    assert version_token(**BASE) == (
        "fv1_942b9bc11e4c0f1009842218c2a04faa10384016421b240b896fa6d2d85cc15f"
    )
    assert version_token(dev=0, ino=0, kind="directory", size=0, mtime_ns=-1, ctime_ns=0) == (
        "fv1_bbe4e56a06ccadd57b897ed8c8414dec9068b332a270c8a521860e1e9634d6f8"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dev", 9),
        ("ino", 9),
        ("kind", EntryKind.DIRECTORY),
        ("kind", EntryKind.OTHER),
        ("size", 9),
        ("mtime_ns", 9),
        ("ctime_ns", 9),
    ],
)
def test_every_fingerprint_field_moves_the_token(field: str, value: object) -> None:
    assert version_token(**{**BASE, field: value}) != version_token(**BASE)  # type: ignore[arg-type]


def test_token_shape_round_trips() -> None:
    token = version_token(**BASE)
    assert parse_version_token(token) == token
    assert validate_version_token(token) == token
    assert version_token(**{**BASE, "kind": "file"}) == token  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("dev", True, "type"),
        ("dev", -1, "bounds"),
        ("ino", 1.0, "type"),
        ("ino", -1, "bounds"),
        ("size", -1, "bounds"),
        ("size", "3", "type"),
        ("mtime_ns", None, "type"),
        ("ctime_ns", False, "type"),
        ("kind", "symlink", "pattern"),
        ("kind", 1, "type"),
    ],
)
def test_malformed_fingerprints_are_refused(field: str, value: object, code: str) -> None:
    with pytest.raises(FilesArgumentError) as caught:
        version_token(**{**BASE, field: value})  # type: ignore[arg-type]
    assert (caught.value.field, caught.value.code) == (field, code)


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "",
        "fv1_",
        "fv1_" + "0" * 63,
        "fv1_" + "0" * 65,
        "fv1_" + "A" * 64,
        "fv2_" + "0" * 64,
        "FV1_" + "0" * 64,
        " fv1_" + "0" * 64,
        "fv1_" + "0" * 64 + "\n",
        "fv1_" + "g" * 64,
    ],
)
def test_malformed_tokens_parse_to_none_without_raising(value: object) -> None:
    assert parse_version_token(value) is None
    with pytest.raises(FilesArgumentError) as caught:
        validate_version_token(value)
    assert caught.value.field == "expected_version"
    if isinstance(value, str) and value:
        assert value not in str(caught.value)
