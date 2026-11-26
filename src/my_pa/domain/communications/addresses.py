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

Not bridged by either rule, and stated as a residual: NFC against NFD spellings
of one address, and a domain written once in Unicode and once in punycode.

Pure: no IO, no clock.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping
from types import MappingProxyType
from typing import Final

__all__ = [
    "ADDRESS_RULE",
    "address_match_key",
    "bridge_addresses",
    "is_ascii_address",
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


def bridge_addresses(stored: Iterable[str], keys: Collection[str]) -> Mapping[str, tuple[str, ...]]:
    """Each attendee key -> the stored non-ASCII addresses whose key it is, sorted.

    `stored` is the batch's distinct non-ASCII participant addresses (the bridge
    statement); an ASCII address needs no bridge and is ignored. A key with no
    bridged address is absent. The answer is what the participant criterion adds
    to that key's own spelling.
    """
    wanted = set(keys)
    bridged: dict[str, set[str]] = {}
    for address in stored:
        if is_ascii_address(address):
            continue
        key = address_match_key(address)
        if key in wanted and address != key:
            bridged.setdefault(key, set()).add(address)
    return MappingProxyType({key: tuple(sorted(found)) for key, found in sorted(bridged.items())})
