"""Per-family record identity and exact RFI matching (plan section 6.3).

* A record identity is project-scoped by its caller; the key here is the
  family-local part, built only from an exported number (or, for a daily-log
  record, its own date and vendor). Never from a title, subject, description,
  amount or other date.
* An identifier is stored as exported; normalization is for matching only and
  is versioned (`commitment_number_v1`).
* An empty identifier is `identity_missing`; a composite part that would make
  the key ambiguous (`@` before the last part) is `ambiguous_identity`.
* **RFI matching** is exact on a token-bounded numeric suffix: `174` never
  matches `1740` or `17`. A given prefix must match exactly; with none, every
  prefix carrying that suffix matches, flagged `ambiguous_prefix` when more
  than one distinct prefix answers.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from my_pa.domain.project_reports.model import IdentityBasis, IdentityState

__all__ = [
    "AMBIGUOUS_PREFIX",
    "COMMITMENT_NORMALIZATION_VERSION",
    "RecordIdentity",
    "RecordKeyKind",
    "RfiMatch",
    "RfiNumber",
    "match_rfi",
    "normalize_commitment_number",
    "normalize_whitespace",
    "record_identity",
    "split_rfi_number",
]

COMMITMENT_NORMALIZATION_VERSION: Final = "commitment_number_v1"
AMBIGUOUS_PREFIX: Final = "ambiguous_prefix"


class RecordKeyKind(StrEnum):
    """The family-local key kinds; the value is the key's leading label."""

    ITEM = "item"
    OBSERVATION = "observation"
    COORDINATION_ISSUE = "coordination_issue"
    RFI = "rfi"
    BUDGET_CHANGE = "budget_change"
    COMMITMENT = "commitment"
    PRIME_CO = "prime_co"
    PCO = "pco"
    MANPOWER = "manpower"
    WEATHER = "weather"


_BASIS: Final = MappingProxyType(
    {
        RecordKeyKind.ITEM: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.OBSERVATION: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.COORDINATION_ISSUE: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.RFI: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.BUDGET_CHANGE: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.COMMITMENT: IdentityBasis.EXPORTED_NUMBER_NORMALIZED,
        RecordKeyKind.PRIME_CO: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.PCO: IdentityBasis.EXPORTED_NUMBER,
        RecordKeyKind.MANPOWER: IdentityBasis.EXPORTED_COMPOSITE,
        RecordKeyKind.WEATHER: IdentityBasis.EXPORTED_NUMBER,
    }
)
#: The number of exported parts each key takes.
_ARITY: Final = MappingProxyType(
    {
        kind: (2 if kind in (RecordKeyKind.COMMITMENT, RecordKeyKind.MANPOWER) else 1)
        for kind in RecordKeyKind
    }
)
_WHITESPACE: Final = re.compile(r"\s+")
_TRAILING_DIGITS: Final = re.compile(r"\A(.*?)([0-9]+)\Z", re.DOTALL)
_PREFIX_SEPARATORS: Final = "-_ .#:"


@dataclass(frozen=True, slots=True)
class RecordIdentity:
    state: IdentityState
    key: str | None = None
    basis: IdentityBasis | None = None


def normalize_whitespace(text: str) -> str:
    """Strip, and collapse every whitespace run to one space."""
    return _WHITESPACE.sub(" ", text).strip()


def normalize_commitment_number(number: str) -> str:
    """`commitment_number_v1`: the leading zeros of the last `.` suffix removed."""
    text = normalize_whitespace(number)
    head, dot, suffix = text.rpartition(".")
    if not dot or not suffix.isdigit():
        return text
    return f"{head}.{suffix.lstrip('0') or '0'}"


def record_identity(kind: RecordKeyKind, *parts: str) -> RecordIdentity:
    """The family-local record key of one detail line, or why it has none."""
    if len(parts) != _ARITY[kind] or not all(type(part) is str for part in parts):
        raise ValueError("a record key takes its family's exported parts as text")
    cleaned = [normalize_whitespace(part) for part in parts]
    if any(part == "" for part in cleaned):
        return RecordIdentity(IdentityState.IDENTITY_MISSING)
    if any("@" in part for part in cleaned[:-1]):
        return RecordIdentity(IdentityState.AMBIGUOUS_IDENTITY)
    if kind is RecordKeyKind.COMMITMENT:
        cleaned[0] = normalize_commitment_number(cleaned[0])
    return RecordIdentity(
        IdentityState.IDENTIFIED, f"{kind.value}:{'@'.join(cleaned)}", _BASIS[kind]
    )


@dataclass(frozen=True, slots=True)
class RfiNumber:
    """An RFI number as exported, split into its prefix and numeric suffix."""

    exported: str
    prefix: str | None
    suffix: int


def split_rfi_number(exported: str) -> RfiNumber | None:
    """The maximal trailing digit run is the suffix; `None` without one."""
    text = normalize_whitespace(exported)
    match = _TRAILING_DIGITS.fullmatch(text)
    if match is None:
        return None
    prefix = match.group(1).rstrip(_PREFIX_SEPARATORS)
    return RfiNumber(text, prefix or None, int(match.group(2)))


@dataclass(frozen=True, slots=True)
class RfiMatch:
    matches: tuple[RfiNumber, ...]
    flag: str | None


def match_rfi(prefix: str | None, suffix: int, candidates: Iterable[RfiNumber]) -> RfiMatch:
    """Exact suffix; exact prefix when given; `ambiguous_prefix` over 2+ prefixes."""
    if type(suffix) is not int or suffix < 0:
        raise ValueError("an RFI suffix is a non-negative integer")
    wanted = None if prefix is None else normalize_whitespace(prefix).rstrip(_PREFIX_SEPARATORS)
    found = tuple(
        candidate
        for candidate in candidates
        if candidate.suffix == suffix and (wanted is None or candidate.prefix == wanted)
    )
    ambiguous = wanted is None and len({candidate.prefix for candidate in found}) > 1
    return RfiMatch(found, AMBIGUOUS_PREFIX if ambiguous else None)
