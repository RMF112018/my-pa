"""Content-free identity for a source row.

Every migrated row carries a hash of its natural key (OD-011), and a table with
no key of its own carries a hash of its whole tuple instead (OD-014). Both are
produced here.

The encoding is unambiguous on purpose. Concatenating string forms would make
``('a', 'bc')`` and ``('ab', 'c')`` the same key, and a migration that confuses
two rows for one is worse than one that refuses both. Each value is therefore
tagged with its storage class and length-prefixed, so a digest can only match
when the tuple genuinely matches.

The digest is the only form a key is ever recorded in outside the target row
itself: `quarantine_records` and `source_key_map` store it and nothing else.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

#: One byte per SQLite storage class. `sqlite3` returns exactly these five
#: Python types, so an unmapped type is a programming error rather than data.
_TAGS: dict[type, bytes] = {
    int: b"i",
    float: b"f",
    str: b"s",
    bytes: b"b",
}
_NULL_TAG = b"n"


class NaturalKeyError(TypeError):
    """A value has a Python type `sqlite3` does not produce."""


def _encode(value: object) -> bytes:
    if value is None:
        return _NULL_TAG + (0).to_bytes(8, "big")
    tag = _TAGS.get(type(value))
    if tag is None:
        raise NaturalKeyError(f"cannot hash a value of type {type(value).__name__}")
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, float):
        # `repr` round-trips a float exactly; `str` did too from 3.1, but `repr`
        # says so in its contract.
        payload = repr(value).encode("utf-8")
    else:
        payload = str(value).encode("utf-8")
    return tag + len(payload).to_bytes(8, "big") + payload


def hash_values(values: Sequence[object]) -> str:
    """Return the hex SHA-256 of an ordered tuple of source values."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(_encode(value))
    return digest.hexdigest()
