"""Workspace-relative paths: the contract's section 3 rules, without a filesystem.

A path is validated as a whole, then split on `/` and validated per component.
Every refusal is `FilesRefusal(field, invalid_path)` and never carries the
value. Nothing is normalized: the string a client sends is the string the store
resolves (rule 6), so NFC and NFD spellings stay two different names.

The store (WP3) still resolves component by component with directory file
descriptors and `O_NOFOLLOW`; this module only decides what may be asked for.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from my_pa.domain.files.errors import FilesRefusal
from my_pa.domain.files.vocabulary import (
    MAX_COMPONENT_BYTES,
    MAX_PATH_BYTES,
    RESERVED_NAMES,
    FilesReason,
)

__all__ = [
    "ROOT",
    "WorkspacePath",
    "is_reserved_name",
    "parse_path",
    "validate_name",
]

_SEPARATOR: Final = "/"
#: Rule 3: NUL, the other C0 controls, DEL, and the backslash SMB reads as a separator.
_FORBIDDEN: Final = frozenset([*(chr(code) for code in range(0x20)), "\x7f", "\\"])
#: ASCII-only case folding (rule 5): `str.lower` would also fold non-ASCII letters.
_ASCII_FOLD: Final = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def _refuse(field: str) -> FilesRefusal:
    return FilesRefusal(field, FilesReason.INVALID_PATH)


def _utf8_length(value: str, field: str) -> int:
    """Rule 1: the UTF-8 byte length of a well-formed string (no lone surrogates)."""
    try:
        return len(value.encode("utf-8"))
    except UnicodeEncodeError:
        raise _refuse(field) from None


def is_reserved_name(name: str) -> bool:
    """Rule 5: whether `name` is a reserved component, compared with ASCII case folding.

    Listing and search use this to omit `.my-pa`, `@eaDir`, `#recycle` and
    `#snapshot` (any ASCII case) silently.
    """
    return name.translate(_ASCII_FOLD) in RESERVED_NAMES


def _check_component(name: str, field: str) -> None:
    if name in ("", ".", ".."):
        raise _refuse(field)
    if any(character in _FORBIDDEN for character in name):
        raise _refuse(field)
    if _utf8_length(name, field) > MAX_COMPONENT_BYTES:
        raise _refuse(field)
    if is_reserved_name(name):
        raise _refuse(field)


def validate_name(value: object, field: str = "new_name") -> str:
    """One path component (e.g. `files.rename`'s `new_name`), returned unchanged.

    The section 3 component rules plus: no `/`, since a name is one component.
    """
    if type(value) is not str:
        raise _refuse(field)
    if _SEPARATOR in value:
        raise _refuse(field)
    _check_component(value, field)
    return value


@dataclass(frozen=True, slots=True)
class WorkspacePath:
    """A validated workspace-relative path; `()` components is the root `""`."""

    components: tuple[str, ...]

    @property
    def is_root(self) -> bool:
        return not self.components

    @property
    def text(self) -> str:
        """The path as the contract spells it (`""` for the root)."""
        return _SEPARATOR.join(self.components)

    @property
    def name(self) -> str:
        """The last component; the root has none."""
        if self.is_root:
            raise _refuse("path")
        return self.components[-1]

    @property
    def parent(self) -> WorkspacePath:
        """The containing directory; the root has none."""
        if self.is_root:
            raise _refuse("path")
        return WorkspacePath(self.components[:-1])

    def join(self, name: str, field: str = "name") -> WorkspacePath:
        """This directory's child `name`, validated as one component and re-bounded."""
        child = WorkspacePath((*self.components, validate_name(name, field)))
        if _utf8_length(child.text, field) > MAX_PATH_BYTES:
            raise _refuse(field)
        return child

    def is_within(self, ancestor: WorkspacePath) -> bool:
        """Whether this path equals `ancestor` or lies below it (component-wise)."""
        size = len(ancestor.components)
        return self.components[:size] == ancestor.components


ROOT: Final = WorkspacePath(())


def parse_path(value: object, field: str = "path", *, allow_root: bool = False) -> WorkspacePath:
    """Validate `value` against section 3 and split it.

    `allow_root` admits the empty path `""` (the root), which the contract
    accepts only where a directory is expected (`list`, `search`, `mkdir`
    parent resolution); elsewhere the empty path is refused like any other
    empty component.
    """
    if type(value) is not str:
        raise _refuse(field)
    if value == "":
        if allow_root:
            return ROOT
        raise _refuse(field)
    if _utf8_length(value, field) > MAX_PATH_BYTES:
        raise _refuse(field)
    components = tuple(value.split(_SEPARATOR))
    for component in components:
        _check_component(component, field)
    return WorkspacePath(components)
