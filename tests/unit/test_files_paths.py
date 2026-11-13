"""Files workspace contract section 3: path rules, refusals that never echo the value."""

from __future__ import annotations

import itertools

import pytest

from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.paths import (
    ROOT,
    WorkspacePath,
    is_reserved_name,
    parse_path,
    validate_name,
)
from my_pa.domain.files.vocabulary import FilesReason

RESERVED = (".my-pa", "@eaDir", "#recycle", "#snapshot")


def _refused(value: object, *, allow_root: bool = False) -> FilesRefusal:
    with pytest.raises(FilesRefusal) as caught:
        parse_path(value, allow_root=allow_root)
    return caught.value


@pytest.mark.parametrize(
    "value",
    [
        "a",
        "a/b/c",
        "My PA/notes.txt",
        ".DS_Store",
        ".hidden/x",
        "a..b",
        "...",
        "a/.b",
        "my-pa",
        ".my-pa.bak",
        "eaDir",
        "#recycled",
        "é/日本語.txt",
        "a b/c\u00a0d",
    ],
)
def test_ordinary_paths_are_accepted_unchanged(value: str) -> None:
    parsed = parse_path(value)
    assert parsed.text == value
    assert parsed.components == tuple(value.split("/"))


@pytest.mark.parametrize(
    "value",
    [
        "..",
        ".",
        "../a",
        "a/..",
        "a/../b",
        "a/./b",
        "./a",
        "/a",
        "/",
        "a/",
        "a//b",
        "//",
        "/../etc/passwd",
        "a\\b",
        "..\\a",
        "\\",
        "a\x00b",
        "\x00",
        "a\x01",
        "a\nb",
        "a\tb",
        "a\x1f",
        "a\x7f",
        "a/\x7f/b",
    ],
)
def test_traversal_and_forbidden_characters_are_invalid_path(value: str) -> None:
    refusal = _refused(value)
    assert refusal.reason is FilesReason.INVALID_PATH
    assert refusal.field == "path"


@pytest.mark.parametrize("code", [*range(0x20), 0x7F])
def test_every_control_character_is_refused(code: int) -> None:
    assert _refused(f"x{chr(code)}y").reason is FilesReason.INVALID_PATH


def test_c1_controls_are_not_c0_and_stay_ordinary() -> None:
    assert parse_path("a\x85b").text == "a\x85b"


@pytest.mark.parametrize(
    ("name", "prefix"),
    [
        (spelling, prefix)
        for reserved in RESERVED
        for spelling in {reserved, reserved.upper(), reserved.lower(), reserved.swapcase()}
        for prefix in ("", "a/", "a/b/c/")
    ],
)
def test_reserved_names_are_refused_at_any_depth_and_any_ascii_case(name: str, prefix: str) -> None:
    assert _refused(prefix + name).reason is FilesReason.INVALID_PATH
    assert _refused(prefix + name + "/child").reason is FilesReason.INVALID_PATH
    assert is_reserved_name(name)


def test_reserved_folding_is_ascii_only() -> None:
    # U+0130 (dotted capital I) lower-cases to "i̇" under full Unicode folding,
    # and the Kelvin sign to "k"; neither may collapse onto an ASCII name.
    assert not is_reserved_name("@EAD\u0130R")
    assert parse_path("\u212aeep").text == "\u212aeep"
    assert not is_reserved_name(".MY-PA ")
    assert not is_reserved_name(".my-pa.d")


def test_empty_path_is_root_only_where_allowed() -> None:
    assert parse_path("", allow_root=True) is ROOT
    assert ROOT.is_root
    assert ROOT.text == ""
    assert _refused("").reason is FilesReason.INVALID_PATH
    assert _refused("/", allow_root=True).reason is FilesReason.INVALID_PATH


@pytest.mark.parametrize("value", [None, b"a", 1, ["a"], object()])
def test_a_non_string_is_invalid_path(value: object) -> None:
    assert _refused(value).reason is FilesReason.INVALID_PATH


@pytest.mark.parametrize("value", ["\ud800", "a/\udfff", "x\ud83d"])
def test_lone_surrogates_are_refused(value: str) -> None:
    assert _refused(value).reason is FilesReason.INVALID_PATH


def test_component_byte_limit_counts_utf8_bytes() -> None:
    assert parse_path("a" * 255).text == "a" * 255
    _refused("a" * 256)
    # "é" is 2 bytes, "日" 3, "😀" 4: 255 bytes accepted, 256 refused.
    assert parse_path("é" * 127 + "a").components[0] == "é" * 127 + "a"
    _refused("é" * 128)
    assert parse_path("日" * 85).text == "日" * 85
    _refused("日" * 85 + "a")
    assert parse_path("😀" * 63 + "abc").text == "😀" * 63 + "abc"
    _refused("😀" * 64)


def test_path_byte_limit_is_4096() -> None:
    component = "a" * 255
    # 15 components of 255 bytes, one of 128 and one of 127, plus 16 separators.
    at_limit = "/".join([component] * 15 + ["b" * 128, "c" * 127])
    assert len(at_limit.encode()) == 4096
    assert parse_path(at_limit).text == at_limit
    _refused(at_limit + "c")
    _refused("/".join(["é" * 100] * 21))


def test_no_unicode_normalization_is_applied() -> None:
    nfc = "café"
    nfd = "café"
    assert parse_path(nfc).text == nfc
    assert parse_path(nfd).text == nfd
    assert parse_path(nfc) != parse_path(nfd)


def test_a_refusal_never_carries_the_value() -> None:
    hostile = "../\x00secret-name\\x"
    refusal = _refused(hostile)
    for rendered in (str(refusal), repr(refusal), str(refusal.args)):
        assert "secret" not in rendered
    assert str(refusal) == "path: invalid_path"


def test_validate_name_is_one_component() -> None:
    assert validate_name("report.pdf") == "report.pdf"
    for bad in ("a/b", "", ".", "..", "a\\b", "\x00", ".My-Pa", "#Snapshot", "a" * 256, None):
        with pytest.raises(FilesRefusal) as caught:
            validate_name(bad)
        assert caught.value.field == "new_name"
        assert caught.value.reason is FilesReason.INVALID_PATH


def test_join_parent_and_within() -> None:
    base = parse_path("a/b")
    child = base.join("c")
    assert child.text == "a/b/c"
    assert child.parent == base
    assert child.name == "c"
    assert ROOT.join("x").text == "x"
    assert parse_path("x").parent is not None
    assert parse_path("x").parent.is_root
    assert child.is_within(base)
    assert child.is_within(ROOT)
    assert base.is_within(base)
    assert not base.is_within(child)
    assert not parse_path("a/bc").is_within(base)
    for bad in ("..", "x/y", ".my-pa", "\\"):
        with pytest.raises(FilesRefusal):
            base.join(bad)
    with pytest.raises(FilesRefusal):
        _ = ROOT.parent
    with pytest.raises(FilesRefusal):
        _ = ROOT.name


def test_join_re_bounds_the_whole_path() -> None:
    deep = parse_path("/".join(["a" * 255] * 16))
    assert len(deep.text.encode()) == 4095
    with pytest.raises(FilesRefusal):
        deep.join("b")


def test_generated_traversal_shapes_are_all_refused() -> None:
    """Property-style: every short path built from hostile atoms is refused."""
    atoms = ["..", ".", "", "a", "\\", "\x00", ".my-pa", "@EADIR"]
    hostile = {"..", ".", "", "\\", "\x00", ".my-pa", "@EADIR"}
    checked = 0
    for size in (1, 2, 3):
        for parts in itertools.product(atoms, repeat=size):
            value = "/".join(parts)
            if any(part in hostile for part in parts):
                with pytest.raises(FilesRefusal):
                    parse_path(value)
            else:
                assert parse_path(value) == WorkspacePath(parts)
            checked += 1
    assert checked == 8 + 64 + 512
