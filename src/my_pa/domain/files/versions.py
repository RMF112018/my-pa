"""Entry kinds and opaque version tokens (contract section 4).

A version token is `fv1_` and 64 lowercase hex: the SHA-256 of the canonical
JSON of `(st_dev, st_ino, kind, st_size, st_mtime_ns, st_ctime_ns)` from
`lstat`. It is a fingerprint, not a content hash: clients compare it for
equality only, and any edit that moves size, mtime, ctime or inode moves it.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Final

from my_pa.domain.files.errors import FilesArgumentError
from my_pa.domain.reports.content import canonical_json

__all__ = [
    "VERSION_TOKEN_PATTERN",
    "VERSION_TOKEN_PREFIX",
    "EntryKind",
    "parse_version_token",
    "validate_version_token",
    "version_token",
]

VERSION_TOKEN_PREFIX: Final = "fv1_"  # noqa: S105 - a prefix, not a secret
VERSION_TOKEN_PATTERN: Final = r"^fv1_[0-9a-f]{64}$"  # noqa: S105 - a pattern
_VERSION_TOKEN: Final = re.compile(r"\Afv1_[0-9a-f]{64}\Z")
#: The encoding's own version, inside the digested document, so a later
#: fingerprint shape can never collide with this one.
_ENCODING_VERSION: Final = 1


class EntryKind(StrEnum):
    """Section 4: `other` is a symlink, FIFO, socket or device, never followed."""

    FILE = "file"
    DIRECTORY = "directory"
    OTHER = "other"


def _integer(value: object, field: str, *, non_negative: bool) -> int:
    if type(value) is not int:
        raise FilesArgumentError(field, "type")
    if non_negative and value < 0:
        raise FilesArgumentError(field, "bounds")
    return value


def version_token(
    *,
    dev: int,
    ino: int,
    kind: EntryKind,
    size: int,
    mtime_ns: int,
    ctime_ns: int,
) -> str:
    """The `fv1_` token of one `lstat` observation.

    `dev`, `ino` and `size` are non-negative; the timestamps may be negative
    (before 1970). `bool` is refused for every integer. Deterministic: the same
    tuple gives the same token in every process.
    """
    raw_kind: object = kind
    if type(raw_kind) is not str and not isinstance(raw_kind, EntryKind):
        raise FilesArgumentError("kind", "type")
    try:
        entry_kind = EntryKind(raw_kind)
    except ValueError:
        raise FilesArgumentError("kind", "pattern") from None
    document = {
        "v": _ENCODING_VERSION,
        "dev": _integer(dev, "dev", non_negative=True),
        "ino": _integer(ino, "ino", non_negative=True),
        "kind": entry_kind.value,
        "size": _integer(size, "size", non_negative=True),
        "mtime_ns": _integer(mtime_ns, "mtime_ns", non_negative=False),
        "ctime_ns": _integer(ctime_ns, "ctime_ns", non_negative=False),
    }
    return VERSION_TOKEN_PREFIX + hashlib.sha256(canonical_json(document)).hexdigest()


def parse_version_token(value: object) -> str | None:
    """`value` if it is exactly a version token, else `None`; never raises."""
    if type(value) is not str or _VERSION_TOKEN.match(value) is None:
        return None
    return value


def validate_version_token(value: object, field: str = "expected_version") -> str:
    """A caller-supplied version token, refused as `pattern` when malformed.

    A malformed `expected_version` is an argument fault, not `version_conflict`:
    it can never equal a current token, and saying so would be a weaker refusal.
    """
    if type(value) is not str:
        raise FilesArgumentError(field, "type")
    if parse_version_token(value) is None:
        raise FilesArgumentError(field, "pattern")
    return value
