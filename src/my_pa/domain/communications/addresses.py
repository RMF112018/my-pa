"""The address match key: comparing a stored participant address with a Meeting attendee (C9-R1).

Two normalizations meet at the Meeting context read (communications intelligence
WP5, ruling D11):

* a communications participant address is stored as `raw.strip().lower()` (the
  parser, and the `address = lower(address)` CHECK);
* a Meeting attendee email is stored as `local.casefold() + "@" +
  domain.casefold()` (the Relationship Intelligence EMAIL rule).

They agree on every ASCII address, and on most others, but not where `lower`
and `casefold` differ (`ß`, capital `ẞ`, a final sigma, the `ﬁ` ligature,
Cherokee). The match key is the Meeting form: `address_match_key` casefolds a
stored communications address, so `address_match_key(stored) == attendee key`
in every one of the design's fifteen synthetic cases. Stored data is never
rewritten; the bridge is computed per read (`bridge_addresses`).

Only a stored address whose casefold differs from it needs a bridge
(`needs_bridge`; WP5-R1 F-4): it holds one of `BRIDGE_CHARACTERS`, the code
points `c` with `c.casefold() != c`. On a stored (lower-case) address this is
exactly "its casefold differs from its lowercase"; an accented letter or an
IDN domain, whose casefold is itself, is matched under its own spelling and is
never read by the bridge. `bridge_pattern` is that set as one PostgreSQL
regular-expression class, so the bridge statement reads only such addresses.

Not bridged by either rule, and stated as a residual: NFC against NFD spellings
of one address, and a domain written once in Unicode and once in punycode.

Pure: no IO, no clock.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from functools import cache
from types import MappingProxyType
from typing import Final

__all__ = [
    "ADDRESS_RULE",
    "address_match_key",
    "bridge_addresses",
    "bridge_characters",
    "bridge_pattern",
    "is_ascii_address",
    "needs_bridge",
]

#: The versioned rule an answer states (`versions.address_rule`).
ADDRESS_RULE: Final = "casefold_bridge_v1"


def address_match_key(address: str) -> str:
    """The key `address` matches a Meeting attendee email under: strip, then casefold.

    The identity on a stored ASCII address, which is already stripped and lower case.
    """
    return address.strip().casefold()


def is_ascii_address(address: str) -> bool:
    """Whether `address` is pure ASCII: its stored form and its key are then equal."""
    return address.isascii()


@cache
def bridge_characters() -> frozenset[str]:
    """Every code point whose casefold is not itself (surrogates excluded)."""
    return frozenset(
        chr(point)
        for point in range(0x110000)
        if not 0xD800 <= point <= 0xDFFF and chr(point).casefold() != chr(point)
    )


def needs_bridge(address: str) -> bool:
    """Whether a stored address's match key differs from it (it holds a bridge character)."""
    return address_match_key(address) != address.strip()


@cache
def bridge_pattern() -> str:
    """`bridge_characters()` as one PostgreSQL ARE bracket expression of code-point ranges."""
    ranges: list[list[int]] = []
    for point in sorted(ord(character) for character in bridge_characters()):
        if ranges and ranges[-1][1] == point - 1:
            ranges[-1][1] = point
        else:
            ranges.append([point, point])
    return (
        "["
        + "".join(
            f"\\U{low:08x}" if low == high else f"\\U{low:08x}-\\U{high:08x}"
            for low, high in ranges
        )
        + "]"
    )


def bridge_addresses(stored: Iterable[str], keys: Collection[str]) -> Mapping[str, tuple[str, ...]]:
    """Each attendee key -> the stored non-ASCII addresses whose key it is, sorted.

    `stored` is the partition's distinct participant addresses that need a
    bridge (the bridge statement); any other address is ignored. A key with no
    bridged address is absent. The answer is what the participant criterion adds
    to that key's own spelling.
    """
    wanted = set(keys)
    bridged: dict[str, set[str]] = {}
    for address in stored:
        if not needs_bridge(address):
            continue
        key = address_match_key(address)
        if key in wanted and address != key:
            bridged.setdefault(key, set()).add(address)
    return MappingProxyType({key: tuple(sorted(found)) for key, found in sorted(bridged.items())})
