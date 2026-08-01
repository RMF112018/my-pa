"""Target identifier naming for the legacy-SQLite to PostgreSQL port.

PostgreSQL's ``NAMEDATALEN`` budget is 63 bytes and it truncates silently, which
is unsafe here: 16 source column names and 67 source index names exceed it and
several differ only after the truncation point. So every identifier is quoted,
source names are preserved byte-for-byte wherever they fit, and anything longer
is shortened deterministically to ``<first 55 bytes>_<7 hex of sha256(original)>``.

Every rename is recorded so the mapping is queryable rather than folklore, and a
namespace refuses two distinct originals that resolve to the same target name.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

MAX_IDENTIFIER_BYTES = 63
_HASH_HEX_LENGTH = 7
_RETAINED_BYTES = MAX_IDENTIFIER_BYTES - _HASH_HEX_LENGTH - 1

#: Former-employer branding may not appear on a target surface. One source
#: column carries it (`construction_project_identity.hb_project_number`); the
#: token is dropped and the rename is recorded like any other.
_BRANDED_TOKEN = re.compile(r"(?:^|_)hb(?=_|$)", re.IGNORECASE)


class IdentifierError(RuntimeError):
    """An identifier could not be represented safely in PostgreSQL."""


def quote(name: str) -> str:
    """Return ``name`` as a quoted PostgreSQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def qualify(schema: str, name: str) -> str:
    """Return a quoted ``schema.name`` reference."""
    return f"{quote(schema)}.{quote(name)}"


def shorten(name: str) -> str:
    """Return ``name`` fitted into the 63-byte budget.

    Names that already fit are returned unchanged. Longer names keep their first
    55 bytes and gain a 7-character hash of the *full original*, so two names
    that differ only after byte 63 still resolve to different targets.
    """
    raw = name.encode("utf-8")
    if len(raw) <= MAX_IDENTIFIER_BYTES:
        return name
    digest = hashlib.sha256(raw).hexdigest()[:_HASH_HEX_LENGTH]
    head = raw[:_RETAINED_BYTES].decode("utf-8", "ignore")
    return f"{head}_{digest}"


def neutralise(name: str) -> str:
    """Return ``name`` with any former-employer token removed."""
    if not _BRANDED_TOKEN.search(name):
        return name
    return "_".join(part for part in name.split("_") if part.lower() != "hb")


def target_name(original: str) -> str:
    """Return the target identifier for a source name: neutral, and inside the budget."""
    return assert_fits(shorten(neutralise(original)))


def assert_fits(name: str) -> str:
    """Return ``name``, raising if it cannot be emitted as a PostgreSQL identifier."""
    size = len(name.encode("utf-8"))
    if size > MAX_IDENTIFIER_BYTES:
        raise IdentifierError(f"identifier {name!r} is {size} bytes, over the 63-byte limit")
    if not name:
        raise IdentifierError("empty identifier")
    return name


@dataclass(frozen=True)
class Rename:
    """One recorded identifier rename, destined for ``migration_control.identifier_map``."""

    original: str
    shortened: str
    object_kind: str
    owner: str


@dataclass
class Namespace:
    """A set of identifiers that PostgreSQL requires to be distinct.

    Used per schema for relations (tables, indexes, and the indexes that back
    primary-key constraints, which share one namespace) and per table for
    columns and for constraint names.
    """

    label: str
    _taken: dict[str, Rename] = field(default_factory=dict)
    _renames: list[Rename] = field(default_factory=list)

    def allocate(self, original: str, object_kind: str, owner: str) -> str:
        """Reserve a target name for ``original`` and return it.

        Two different objects may not claim the same name, even when their source
        names were identical: SQLite lets an index share a name with a table in a
        way PostgreSQL does not.
        """
        target = target_name(original)
        claim = Rename(original, target, object_kind, owner)
        claimed = self._taken.get(target)
        if claimed is not None and claimed != claim:
            raise IdentifierError(
                f"identifier collision in {self.label}: {claim.object_kind} {original!r} "
                f"of {owner!r} and {claimed.object_kind} {claimed.original!r} of "
                f"{claimed.owner!r} both resolve to {target!r}"
            )
        self._taken[target] = claim
        if target != original:
            self._renames.append(claim)
        return target

    @property
    def renames(self) -> tuple[Rename, ...]:
        return tuple(self._renames)

    def __contains__(self, target: str) -> bool:
        return target in self._taken

    def __iter__(self) -> Iterator[str]:
        return iter(self._taken)
