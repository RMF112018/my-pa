"""Technical-identifier extractor `comms_identifiers_v1` (pure, standard library only).

`extract_identifiers(text)` returns the distinct construction identifiers in a
plain text, normalized and sorted by `(kind, value)`. The same function
normalizes a query, so a query matches a message exactly when their normalized
identifiers are equal -- `RFI 17` and `RFI 174` never match each other.

Rules (every match is token-bounded: no letter or digit immediately before it,
and the number may not continue into another digit or a `.`/`-`/`/` followed by
a digit -- so `RFI 1740` is never `rfi:174` and `RFI 174.1` is not an RFI):

* **RFI** -- `RFI 174`, `RFI-174`, `RFI #174`, `RFI No. 174`, `RFI174`;
  case-insensitive (`rfi 174` counts) -> `rfi:174`;
* **change bulletin** -- `CB #2`, `CB 2`, `CB-2`, `CB No. 2`; upper-case only and a
  separator is required (`CB2` is not matched) -> `cb:2`;
* **change order** -- `CO #5`, `CO 5`, `CO-5`, `CO No. 5`; upper-case only and a
  separator is required, so `CO2` (carbon dioxide) and `co 5` are not matched;
  `PCO 5` is not a `CO` (letter before it) -> `co:5`;
* **submittal** -- `Submittal 12`, `Submittal #033000-01`, `Submittal No. 05.12`;
  case-insensitive; the number is digits with optional `.`/`-` separated digit
  groups, kept **verbatim** (`submittal:033000-01`), because submittal numbers
  embed spec sections whose leading zeros are meaningful;
* **GMP / FPL** -- bare acronym tokens, upper-case only (`gmp` is not matched,
  nor `GMPX` or `aGMP`); a plural `GMPs` / `GMP's` normalizes to `gmp`;
* **spec section (CSI MasterFormat)** -- conservative, and **cue-required by
  default**: a `Section`/`Sections`/`Spec`/`Specs`/`Specification` cue
  (case-insensitive, optional `#`/`No.`) directly before either the spaced form
  `03 30 00` (optionally `.13`) or the contiguous form `033000` (optionally
  `.13`), first pair `00`-`49` -> `spec:033000` / `spec:033000.13`. Bare
  six-digit numbers are never sections (corpus v2: such numbers appear in 1,713
  real messages and are noise). `include_uncued_spec_sections=True` (default off)
  additionally admits the bare *spaced* form, not adjacent to another digit
  group (so a phone number `561 555 0123`, a time `10:30:00`, a date
  `2026-11-20` or `11/20/26` are not sections; a time written with spaces,
  `10 30 00`, is an accepted false positive of that opt-in). Only the first
  section after a cue is cued: `Sections 03 30 00 and 09 91 23` yields the first.

Leading-zero policy: RFI, CB and CO numbers are integers -- leading zeros are
dropped (`RFI 0174` is `rfi:174`, `RFI 000` is `rfi:0`). Submittal numbers and
spec sections are kept digit-for-digit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

__all__ = [
    "IDENTIFIER_VERSION",
    "IdentifierKind",
    "TechnicalIdentifier",
    "extract_identifiers",
]

IDENTIFIER_VERSION: Final = "comms_identifiers_v1"


class IdentifierKind(StrEnum):
    RFI = "rfi"
    CHANGE_BULLETIN = "cb"
    CHANGE_ORDER = "co"
    SUBMITTAL = "submittal"
    GMP = "gmp"
    FPL = "fpl"
    SPEC_SECTION = "spec"


@dataclass(frozen=True, slots=True, order=True)
class TechnicalIdentifier:
    kind: IdentifierKind
    value: str

    @property
    def normalized(self) -> str:
        return self.value if self.kind in _BARE else f"{self.kind}:{self.value}"


_BARE: Final = frozenset({IdentifierKind.GMP, IdentifierKind.FPL})

_LEFT = r"(?<![A-Za-z0-9])"
_NUMBER_END = r"(?![0-9])(?![.\-/][0-9])"
_SEPARATOR_OPTIONAL = r"(?:\s*(?:#|No\.?)\s*|\s*-\s*|\s*)"
_SEPARATOR_REQUIRED = r"(?:\s*(?:#|No\.?)\s*|\s*-\s*|\s+)"

_RFI: Final = re.compile(_LEFT + r"RFI" + _SEPARATOR_OPTIONAL + r"([0-9]{1,6})" + _NUMBER_END, re.I)
_CB: Final = re.compile(_LEFT + r"CB" + _SEPARATOR_REQUIRED + r"([0-9]{1,6})" + _NUMBER_END)
_CO: Final = re.compile(_LEFT + r"CO" + _SEPARATOR_REQUIRED + r"([0-9]{1,6})" + _NUMBER_END)
_SUBMITTAL: Final = re.compile(
    _LEFT
    + r"submittal"
    + _SEPARATOR_REQUIRED
    + r"([0-9]{1,8}(?:[.\-][0-9]{1,8}){0,3})"
    + _NUMBER_END,
    re.I,
)
_ACRONYM: Final = re.compile(_LEFT + r"(GMP|FPL)(?:'?s)?(?![A-Za-z0-9])")
_SPEC_TAIL = r"(?:\.([0-9]{2}))?(?![0-9])(?![.\-/:][0-9])"
_SPEC_CUE = r"(?:spec(?:ification)?s?|sections?)\s*(?:#|No\.?)?\s*"
_SPEC_SPACED_BODY = r"([0-4][0-9]) ([0-9]{2}) ([0-9]{2})" + _SPEC_TAIL + r"(?! [0-9])"
#: Cued forms (always on): `Section 03 30 00`, `SECTION 09 91 23.13`, `Spec 033000`.
_SPEC_CUED: Final = re.compile(
    _LEFT
    + _SPEC_CUE
    + r"(?:"
    + _SPEC_SPACED_BODY
    + r"|([0-4][0-9])([0-9]{2})([0-9]{2})"
    + _SPEC_TAIL
    + r")",
    re.I,
)
#: The bare spaced form, only with `include_uncued_spec_sections=True`.
_SPEC_BARE_SPACED: Final = re.compile(r"(?<![0-9])(?<![0-9][ .\-/:])" + _SPEC_SPACED_BODY)

_INTEGER_KINDS: Final = (
    (_RFI, IdentifierKind.RFI),
    (_CB, IdentifierKind.CHANGE_BULLETIN),
    (_CO, IdentifierKind.CHANGE_ORDER),
)


def _spec_section(groups: tuple[str | None, ...]) -> str:
    """`(division, section, subsection, optional tail)` -> `033000` or `033000.13`."""
    first, second, third, tail = groups
    section = f"{first}{second}{third}"
    return f"{section}.{tail}" if tail else section


def extract_identifiers(
    text: str, *, include_uncued_spec_sections: bool = False
) -> tuple[TechnicalIdentifier, ...]:
    """Distinct normalized identifiers in `text`, sorted (see module docstring).

    Bare spec-section-like numbers are noise by default (corpus v2: present in
    1,713 messages); `include_uncued_spec_sections` admits the bare *spaced* form
    `03 30 00`. A contiguous six-digit number is never a section without a cue.
    """
    found: set[TechnicalIdentifier] = set()
    for pattern, kind in _INTEGER_KINDS:
        found.update(
            TechnicalIdentifier(kind, str(int(m.group(1)))) for m in pattern.finditer(text)
        )
    found.update(
        TechnicalIdentifier(IdentifierKind.SUBMITTAL, m.group(1)) for m in _SUBMITTAL.finditer(text)
    )
    found.update(
        TechnicalIdentifier(IdentifierKind(m.group(1).lower()), m.group(1).lower())
        for m in _ACRONYM.finditer(text)
    )
    for m in _SPEC_CUED.finditer(text):
        groups = m.groups()
        spaced, contiguous = groups[:4], groups[4:]
        found.add(
            TechnicalIdentifier(
                IdentifierKind.SPEC_SECTION,
                _spec_section(spaced if spaced[0] is not None else contiguous),
            )
        )
    if include_uncued_spec_sections:
        for m in _SPEC_BARE_SPACED.finditer(text):
            found.add(TechnicalIdentifier(IdentifierKind.SPEC_SECTION, _spec_section(m.groups())))
    return tuple(sorted(found))
