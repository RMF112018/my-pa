"""Technical-identifier extractors `comms_identifiers_v1` and `_v2` (pure, standard library only).

`extract_identifiers(text)` returns the distinct construction identifiers in a
plain text, normalized and sorted by `(kind, value)`. The same function
normalizes a query, so a query matches a message exactly when their normalized
identifiers are equal -- `RFI 17` and `RFI 174` never match each other.

Rules (every match is token-bounded: no letter or digit immediately before it,
and the number may not continue into another digit or a `.`/`-`/`/`/`,` followed
by a digit -- so `RFI 1740` is never `rfi:174`, `RFI 174.1` is not an RFI, and a
thousands separator such as `RFI 1,740` is not `rfi:1`):

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

**`comms_identifiers_v2`** (communications WP4, rulings R5 and R5b (a); the
current version) keeps every v1 form and its token boundaries, and adds:

* `:` as a separator for every numbered kind (`RFI: 174`, `CO: 5`,
  `Submittal: 033000-01`);
* the written-out names, case-insensitive with a separator required:
  `Request for Information 174` (`rfi`), `Change Bulletin 2` (`cb`),
  `Change Order 5` / `Change Order #5` / `Change Order No. 5` (`co`);
* two kinds, numbered independently of the executed change order so that
  `CO 12` never matches them: **potential change order** `pco` -- `PCO 12`,
  `PCO-12`, `PCO #12`, `PCO: 12`, `PCO12` (upper case) and `Potential` /
  `Proposed Change Order 12` -- and **change order request** `cor` -- `COR 7`,
  `COR-7`, `COR #7`, `COR: 7`, `COR7` (upper case) and `Change Order Request 7`.
  `PCO 12` is never `co:12`, `COR 7` never `co:7`, and the qualified written
  forms never also yield a `co`;
* submittals: the plural `Submittals 12`, `Submittal Number 12`, and the
  spaced spec form `Submittal 03 30 00-01`, normalized to `033000-01` (v1 read
  it as `submittal:03`, a wrong identifier);
* `FP&L` and `F.P.L.` as `fpl`; the expanded utility name awaits a ruling
  (R5b (b)), and lower- or mixed-case `fpl` stays unmatched.

The six-digit spec policy is unchanged. `identifier_forms` reports each v2
occurrence with its closed `FormClass`, for the counts-only measurement, and
`normalize_identifier_query` reads one query item as exactly one identifier
or none (ruling R11).

Leading-zero policy: RFI, CB, CO, PCO and COR numbers are integers -- leading zeros are
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
    "IDENTIFIER_VERSION_V1",
    "IDENTIFIER_VERSION_V2",
    "FormClass",
    "IdentifierKind",
    "TechnicalIdentifier",
    "extract_identifiers",
    "identifier_forms",
    "normalize_identifier_query",
]

IDENTIFIER_VERSION_V1: Final = "comms_identifiers_v1"
IDENTIFIER_VERSION_V2: Final = "comms_identifiers_v2"
#: The version ingestion and rederive write (WP4 ruling R10: the current one only).
IDENTIFIER_VERSION: Final = IDENTIFIER_VERSION_V2


class IdentifierKind(StrEnum):
    RFI = "rfi"
    CHANGE_BULLETIN = "cb"
    CHANGE_ORDER = "co"
    SUBMITTAL = "submittal"
    GMP = "gmp"
    FPL = "fpl"
    SPEC_SECTION = "spec"
    #: Admitted by revision `fa18ef3d9bc0` (WP4 ruling R5). A potential (or
    #: proposed) change order and a change order request are numbered
    #: independently of the executed change order, so neither folds into `co`.
    POTENTIAL_CHANGE_ORDER = "pco"
    CHANGE_ORDER_REQUEST = "cor"


@dataclass(frozen=True, slots=True, order=True)
class TechnicalIdentifier:
    kind: IdentifierKind
    value: str

    @property
    def normalized(self) -> str:
        return self.value if self.kind in _BARE else f"{self.kind}:{self.value}"


_BARE: Final = frozenset({IdentifierKind.GMP, IdentifierKind.FPL})

_LEFT = r"(?<![A-Za-z0-9])"
_NUMBER_END = r"(?![0-9])(?![.\-/,][0-9])"
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


def _extract_v1(text: str, include_uncued_spec_sections: bool) -> set[TechnicalIdentifier]:
    """`comms_identifiers_v1`, frozen: unchanged since WP1."""
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
    return found


# --- comms_identifiers_v2 (WP4 rulings R5 and R5b (a)) ---------------------------------


class FormClass(StrEnum):
    """The closed surface-form classes of `comms_identifiers_v2` (counts only)."""

    RFI_ACRONYM = "rfi.acronym"
    RFI_ACRONYM_COLON = "rfi.acronym_colon"
    RFI_WORDS = "rfi.words"
    CB_ACRONYM = "cb.acronym"
    CB_ACRONYM_COLON = "cb.acronym_colon"
    CB_WORDS = "cb.words"
    CO_ACRONYM = "co.acronym"
    CO_ACRONYM_COLON = "co.acronym_colon"
    CO_WORDS = "co.words"
    PCO_ACRONYM = "pco.acronym"
    PCO_WORDS = "pco.words"
    COR_ACRONYM = "cor.acronym"
    COR_WORDS = "cor.words"
    SUBMITTAL_NUMBER = "submittal.number"
    SUBMITTAL_COLON = "submittal.colon"
    SUBMITTAL_PLURAL = "submittal.plural"
    SUBMITTAL_SPACED_SPEC = "submittal.spaced_spec"
    GMP_ACRONYM = "gmp.acronym"
    FPL_ACRONYM = "fpl.acronym"
    FPL_AMPERSAND = "fpl.ampersand"
    FPL_DOTTED = "fpl.dotted"
    SPEC_CUED = "spec.cued"
    SPEC_BARE_SPACED = "spec.bare_spaced"


#: The v2 separators: v1's plus `:` (`RFI: 174`, `CO: 5`), with its own class.
_SEP_OPTIONAL_V2 = r"(?P<sep>\s*(?:#|No\.?)\s*|\s*[-:]\s*|\s*)"
_SEP_REQUIRED_V2 = r"(?P<sep>\s*(?:#|No\.?)\s*|\s*[-:]\s*|\s+)"
_INTEGER_V2 = r"(?P<number>[0-9]{1,6})" + _NUMBER_END

#: `(pattern, kind, acronym class, colon class)`. The acronyms keep v1's case
#: rules; `PCO` and `COR` take an optional separator like `RFI`, `CB` and `CO`
#: a required one, so `CO2` stays carbon dioxide. `PCO 5` is never `co:5` and
#: `COR 7` never `co:7`: a letter before `CO`, or after it, stops the match.
_ACRONYMS_V2: Final = (
    (
        re.compile(_LEFT + r"RFI" + _SEP_OPTIONAL_V2 + _INTEGER_V2, re.I),
        IdentifierKind.RFI,
        FormClass.RFI_ACRONYM,
        FormClass.RFI_ACRONYM_COLON,
    ),
    (
        re.compile(_LEFT + r"CB" + _SEP_REQUIRED_V2 + _INTEGER_V2),
        IdentifierKind.CHANGE_BULLETIN,
        FormClass.CB_ACRONYM,
        FormClass.CB_ACRONYM_COLON,
    ),
    (
        re.compile(_LEFT + r"CO" + _SEP_REQUIRED_V2 + _INTEGER_V2),
        IdentifierKind.CHANGE_ORDER,
        FormClass.CO_ACRONYM,
        FormClass.CO_ACRONYM_COLON,
    ),
    (
        re.compile(_LEFT + r"PCO" + _SEP_OPTIONAL_V2 + _INTEGER_V2),
        IdentifierKind.POTENTIAL_CHANGE_ORDER,
        FormClass.PCO_ACRONYM,
        FormClass.PCO_ACRONYM,
    ),
    (
        re.compile(_LEFT + r"COR" + _SEP_OPTIONAL_V2 + _INTEGER_V2),
        IdentifierKind.CHANGE_ORDER_REQUEST,
        FormClass.COR_ACRONYM,
        FormClass.COR_ACRONYM,
    ),
)
#: Written-out names, case-insensitive, a separator required.
_RFI_WORDS: Final = re.compile(
    _LEFT + r"request\s+for\s+information" + _SEP_REQUIRED_V2 + _INTEGER_V2, re.I
)
_CB_WORDS: Final = re.compile(_LEFT + r"change\s+bulletin" + _SEP_REQUIRED_V2 + _INTEGER_V2, re.I)
#: `Change Order N` is a `co`; `Potential`/`Proposed Change Order N` a `pco`;
#: `Change Order Request N` a `cor` (R5). The longest reading wins, so the
#: qualified forms never also yield a `co`.
_CHANGE_ORDER_WORDS: Final = re.compile(
    _LEFT
    + r"(?:(?P<potential>potential|proposed)\s+)?change\s+order(?P<request>\s+request)?"
    + _SEP_REQUIRED_V2
    + _INTEGER_V2,
    re.I,
)
#: `Submittal(s)` then `#`, `No.`, `Number`, `-`, `:` or a space, then either
#: the spaced spec form `03 30 00` (optionally `-01`/`.01` groups), normalized
#: to `033000-01` -- v1 read that as `submittal:03` -- or v1's verbatim number.
_SUBMITTAL_V2: Final = re.compile(
    _LEFT
    + r"submittal(?P<plural>s)?"
    + r"(?P<sep>\s*(?:#|No\.?|Number)\s*|\s*[-:]\s*|\s+)"
    + r"(?:(?P<a>[0-4][0-9]) (?P<b>[0-9]{2}) (?P<c>[0-9]{2})(?P<tail>(?:[.\-][0-9]{1,8}){0,3})"
    + r"|(?P<number>[0-9]{1,8}(?:[.\-][0-9]{1,8}){0,3}))"
    + _NUMBER_END,
    re.I,
)
#: R5b (a): `FP&L` and `F.P.L.` are `fpl`; the expanded name awaits a ruling.
_ACRONYM_V2: Final = re.compile(_LEFT + r"(?P<name>GMP|FPL|FP&L|F\.P\.L\.?)(?:'?s)?(?![A-Za-z0-9])")


def _spoken(text: str) -> list[tuple[TechnicalIdentifier, FormClass]]:
    """Every v2 identifier occurrence in `text` with its form class, in no order."""
    found: list[tuple[TechnicalIdentifier, FormClass]] = []
    for pattern, kind, plain, colon in _ACRONYMS_V2:
        for m in pattern.finditer(text):
            form = colon if ":" in m.group("sep") else plain
            found.append((TechnicalIdentifier(kind, str(int(m.group("number")))), form))
    for m in _RFI_WORDS.finditer(text):
        found.append(
            (
                TechnicalIdentifier(IdentifierKind.RFI, str(int(m.group("number")))),
                FormClass.RFI_WORDS,
            )
        )
    for m in _CB_WORDS.finditer(text):
        found.append(
            (
                TechnicalIdentifier(IdentifierKind.CHANGE_BULLETIN, str(int(m.group("number")))),
                FormClass.CB_WORDS,
            )
        )
    for m in _CHANGE_ORDER_WORDS.finditer(text):
        if m.group("request") is not None:
            kind, form = IdentifierKind.CHANGE_ORDER_REQUEST, FormClass.COR_WORDS
        elif m.group("potential") is not None:
            kind, form = IdentifierKind.POTENTIAL_CHANGE_ORDER, FormClass.PCO_WORDS
        else:
            kind, form = IdentifierKind.CHANGE_ORDER, FormClass.CO_WORDS
        found.append((TechnicalIdentifier(kind, str(int(m.group("number")))), form))
    for m in _SUBMITTAL_V2.finditer(text):
        if m.group("a") is not None:
            value = f"{m.group('a')}{m.group('b')}{m.group('c')}{m.group('tail')}"
            form = FormClass.SUBMITTAL_SPACED_SPEC
        else:
            value = m.group("number")
            if m.group("plural") is not None:
                form = FormClass.SUBMITTAL_PLURAL
            elif ":" in m.group("sep"):
                form = FormClass.SUBMITTAL_COLON
            else:
                form = FormClass.SUBMITTAL_NUMBER
        found.append((TechnicalIdentifier(IdentifierKind.SUBMITTAL, value), form))
    for m in _ACRONYM_V2.finditer(text):
        name = m.group("name")
        if name == "GMP":
            found.append((TechnicalIdentifier(IdentifierKind.GMP, "gmp"), FormClass.GMP_ACRONYM))
            continue
        form = (
            FormClass.FPL_ACRONYM
            if name == "FPL"
            else FormClass.FPL_AMPERSAND
            if "&" in name
            else FormClass.FPL_DOTTED
        )
        found.append((TechnicalIdentifier(IdentifierKind.FPL, "fpl"), form))
    for m in _SPEC_CUED.finditer(text):
        groups = m.groups()
        spaced, contiguous = groups[:4], groups[4:]
        section = _spec_section(spaced if spaced[0] is not None else contiguous)
        found.append(
            (TechnicalIdentifier(IdentifierKind.SPEC_SECTION, section), FormClass.SPEC_CUED)
        )
    return found


def identifier_forms(
    text: str, *, include_uncued_spec_sections: bool = False
) -> tuple[tuple[TechnicalIdentifier, FormClass], ...]:
    """Every `comms_identifiers_v2` occurrence in `text` with its form class, sorted.

    For the counts-only measurement (`measurement.py`); the identifiers are
    exactly `extract_identifiers(text, version=IDENTIFIER_VERSION_V2)`.
    """
    found = _spoken(text)
    if include_uncued_spec_sections:
        found.extend(
            (
                TechnicalIdentifier(IdentifierKind.SPEC_SECTION, _spec_section(m.groups())),
                FormClass.SPEC_BARE_SPACED,
            )
            for m in _SPEC_BARE_SPACED.finditer(text)
        )
    return tuple(sorted(found))


def _extract_v2(text: str, include_uncued_spec_sections: bool) -> set[TechnicalIdentifier]:
    forms = identifier_forms(text, include_uncued_spec_sections=include_uncued_spec_sections)
    return {identifier for identifier, _form in forms}


#: Version -> extractor.
_EXTRACTORS: Final = {IDENTIFIER_VERSION_V1: _extract_v1, IDENTIFIER_VERSION_V2: _extract_v2}


def extract_identifiers(
    text: str,
    *,
    include_uncued_spec_sections: bool = False,
    version: str = IDENTIFIER_VERSION,
) -> tuple[TechnicalIdentifier, ...]:
    """Distinct normalized identifiers in `text`, sorted (see module docstring).

    `version` is `comms_identifiers_v2` (current) or the frozen
    `comms_identifiers_v1`. Bare spec-section-like numbers are noise by default
    (corpus v2: present in 1,713 messages); `include_uncued_spec_sections`
    admits the bare *spaced* form `03 30 00`. A contiguous six-digit number is
    never a section without a cue.
    """
    extractor = _EXTRACTORS.get(version)
    if extractor is None:
        raise ValueError("unknown identifier version")
    return tuple(sorted(extractor(text, include_uncued_spec_sections)))


#: A normalized identifier spelled back as a surface form its version reads.
_SURFACE: Final = {
    IdentifierKind.RFI: "RFI {}",
    IdentifierKind.CHANGE_BULLETIN: "CB {}",
    IdentifierKind.CHANGE_ORDER: "CO {}",
    IdentifierKind.POTENTIAL_CHANGE_ORDER: "PCO {}",
    IdentifierKind.CHANGE_ORDER_REQUEST: "COR {}",
    IdentifierKind.SUBMITTAL: "Submittal {}",
    IdentifierKind.SPEC_SECTION: "Section {}",
}
_NORMALIZED: Final = re.compile(r"(?P<kind>[a-z]+):(?P<value>\S{1,256})")


def normalize_identifier_query(
    item: str, *, version: str = IDENTIFIER_VERSION
) -> TechnicalIdentifier | None:
    """The one identifier a query item names under `version`, or `None` (ruling R11).

    An item is either a surface form (`RFI 174`, `Change Order #5`, `FP&L`) or
    a normalized identifier as answers print it (`rfi:174`, `gmp`). It names an
    identifier only when it yields **exactly one**: `None` for zero (`174`,
    `RFI`) or several (`RFI 1 and RFI 2`), which the caller refuses. A
    normalized form must read back as itself, so `rfi:0174` or `pco:12` under
    v1 is `None`.
    """
    candidate = item.strip()
    if candidate in _BARE:
        return TechnicalIdentifier(IdentifierKind(candidate), candidate)
    match = _NORMALIZED.fullmatch(candidate)
    if match is not None:
        try:
            kind = IdentifierKind(match.group("kind"))
        except ValueError:
            return None
        surface = _SURFACE.get(kind)
        if surface is None:
            return None
        expected = TechnicalIdentifier(kind, match.group("value"))
        found = extract_identifiers(surface.format(expected.value), version=version)
        return expected if found == (expected,) else None
    found = extract_identifiers(candidate, version=version)
    return found[0] if len(found) == 1 else None
