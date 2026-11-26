"""Counts-only identifier measurement over publications (pure, standard library only).

Communications WP4 ruling D3: the Manager runs this over the private corpus and
records, per identifier kind, the records `comms_identifiers_v2` finds against
the analysis counts; the worker never sees the corpus. The measurement is
**counts only**: it returns kinds, closed form-class names and integers, never
a subject, a text, an address or an identifier value.

It counts **usable records** -- every record of an accepted publication that
was not quarantined and carries a message, the `aggregate_cli` rule. Each
version's extractor reads that version's own stored text, `subject + "\\n" +
search_text`, exactly as ingestion builds it. Per kind:

* `records_v1`, `records_v2` -- records with at least one identifier of the kind;
* `records_v1_only`, `records_v2_only` -- lost and gained by v2;
* `occurrences_v2` -- every v2 occurrence of the kind (repeats included);
* `by_form_class_v2` -- records with at least one occurrence of each form
  class (`FormClass`), so `co.words` against `co.acronym` reads directly;
* the attribution of a gap to the analysis count, each over the records
  without a v2 identifier of the kind:
  * `records_quoted_or_tail_only` -- v2 finds the kind in the unstripped
    basis text (quoted chain and trailing paragraphs kept) but not in the
    stored text: excluded by the contract's design;
  * `records_keyword_without_number` -- the kind's keyword (`submittal`,
    `change order`, `PCO`, ...) appears, case-insensitively, with no
    identifier;
  * `records_unsupported_shape` -- a lower- or mixed-case token of a
    case-sensitive acronym (`fpl`, `Gmp`, `pco`, `Cor`, `cb`) outside an
    address, path or domain. Not measured for `co`, whose lower-case token is
    ordinary prose (`co-op`, `Co.`); `rfi` is already case-insensitive.

Plus `disclaimer_removed` per search-text version (records whose stored text
lost a disclaimer paragraph), which measures the v2 anchoring.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION_V1,
    IDENTIFIER_VERSION_V2,
    IdentifierKind,
    extract_identifiers,
    identifier_forms,
)
from my_pa.domain.communications.model import Publication, RecordClassification
from my_pa.domain.communications.search_text import (
    SEARCH_TEXT_VERSION_V1,
    SEARCH_TEXT_VERSION_V2,
    SearchTextFlag,
    derive_search_text,
    unstripped_text,
)

__all__ = ["IdentifierMeasurement", "KindMeasurement", "measure_identifiers"]

#: Keyword evidence per kind (case-insensitive, token-bounded).
_KEYWORDS: Final = MappingProxyType(
    {
        IdentifierKind.RFI: re.compile(r"\b(?:rfi|request\s+for\s+information)\b", re.I),
        IdentifierKind.CHANGE_BULLETIN: re.compile(r"\b(?:cb|change\s+bulletin)\b", re.I),
        IdentifierKind.CHANGE_ORDER: re.compile(r"\bchange\s+order\b|\bCO\b"),
        IdentifierKind.POTENTIAL_CHANGE_ORDER: re.compile(
            r"\b(?:pco|(?:potential|proposed)\s+change\s+order)\b", re.I
        ),
        IdentifierKind.CHANGE_ORDER_REQUEST: re.compile(
            r"\b(?:cor|change\s+order\s+request)\b", re.I
        ),
        IdentifierKind.SUBMITTAL: re.compile(r"\bsubmittals?\b", re.I),
        IdentifierKind.GMP: re.compile(r"\bgmp\b", re.I),
        IdentifierKind.FPL: re.compile(r"\bfpl\b|\bfp&l\b|\bf\.p\.l\b", re.I),
        IdentifierKind.SPEC_SECTION: re.compile(r"\b(?:spec(?:ification)?s?|sections?)\b", re.I),
    }
)
#: Case-sensitive acronyms whose other-case tokens are an unsupported shape.
_UNSUPPORTED: Final = MappingProxyType(
    {
        kind: re.compile(rf"(?<![A-Za-z0-9@./:_-])({acronym})(?![A-Za-z0-9])(?!\.[A-Za-z])", re.I)
        for kind, acronym in (
            (IdentifierKind.CHANGE_BULLETIN, "cb"),
            (IdentifierKind.POTENTIAL_CHANGE_ORDER, "pco"),
            (IdentifierKind.CHANGE_ORDER_REQUEST, "cor"),
            (IdentifierKind.GMP, "gmp"),
            (IdentifierKind.FPL, "fpl"),
        )
    }
)


@dataclass(frozen=True, slots=True)
class KindMeasurement:
    records_v1: int
    records_v2: int
    records_v1_only: int
    records_v2_only: int
    occurrences_v2: int
    by_form_class_v2: Mapping[str, int]
    records_quoted_or_tail_only: int
    records_keyword_without_number: int
    #: `None` where the shape is not measured (`co`, `rfi`, `submittal`, `spec`).
    records_unsupported_shape: int | None


@dataclass(frozen=True, slots=True)
class IdentifierMeasurement:
    publications: int
    records: int
    disclaimer_removed: Mapping[str, int]
    kinds: Mapping[str, KindMeasurement]


def _kinds(text: str, version: str) -> set[IdentifierKind]:
    return {identifier.kind for identifier in extract_identifiers(text, version=version)}


def _unsupported(text: str, kind: IdentifierKind) -> bool:
    pattern = _UNSUPPORTED.get(kind)
    if pattern is None:
        return False
    return any(match.group(1) != match.group(1).upper() for match in pattern.finditer(text))


def measure_identifiers(publications: Iterable[Publication]) -> IdentifierMeasurement:
    """Counts over every usable record of `publications` (module docstring)."""
    counts: dict[IdentifierKind, Counter[str]] = {kind: Counter() for kind in IdentifierKind}
    forms: dict[IdentifierKind, Counter[str]] = {kind: Counter() for kind in IdentifierKind}
    removed: Counter[str] = Counter()
    measured = {kind: kind in _UNSUPPORTED for kind in IdentifierKind}
    publication_count = records = 0
    for publication in publications:
        publication_count += 1
        for record in publication.records:
            message = record.message
            if message is None or record.classification is RecordClassification.QUARANTINED:
                continue
            records += 1
            subject = message.subject or ""
            v1_text = derive_search_text(message, version=SEARCH_TEXT_VERSION_V1)
            v2_text = derive_search_text(message, version=SEARCH_TEXT_VERSION_V2)
            for search in (v1_text, v2_text):
                if SearchTextFlag.DISCLAIMER_REMOVED in search.flags:
                    removed[search.version] += 1
            stored_v1 = f"{subject}\n{v1_text.text or ''}"
            stored_v2 = f"{subject}\n{v2_text.text or ''}"
            found_v1 = _kinds(stored_v1, IDENTIFIER_VERSION_V1)
            occurrences = identifier_forms(stored_v2)
            found_v2 = {identifier.kind for identifier, _form in occurrences}
            unstripped = f"{subject}\n{unstripped_text(message) or ''}"
            found_unstripped = _kinds(unstripped, IDENTIFIER_VERSION_V2)
            for identifier, _form in occurrences:
                counts[identifier.kind]["occurrences_v2"] += 1
            for kind, form_name in {(i.kind, form.value) for i, form in occurrences}:
                forms[kind][form_name] += 1
            for kind in IdentifierKind:
                counter = counts[kind]
                in_v1, in_v2 = kind in found_v1, kind in found_v2
                counter["records_v1"] += in_v1
                counter["records_v2"] += in_v2
                counter["records_v1_only"] += in_v1 and not in_v2
                counter["records_v2_only"] += in_v2 and not in_v1
                if in_v2:
                    continue
                counter["records_quoted_or_tail_only"] += kind in found_unstripped
                counter["records_keyword_without_number"] += (
                    _KEYWORDS[kind].search(stored_v2) is not None
                )
                counter["records_unsupported_shape"] += _unsupported(stored_v2, kind)
    return IdentifierMeasurement(
        publications=publication_count,
        records=records,
        disclaimer_removed=MappingProxyType(
            {
                version: removed[version]
                for version in (SEARCH_TEXT_VERSION_V1, SEARCH_TEXT_VERSION_V2)
            }
        ),
        kinds=MappingProxyType(
            {
                kind.value: KindMeasurement(
                    records_v1=counts[kind]["records_v1"],
                    records_v2=counts[kind]["records_v2"],
                    records_v1_only=counts[kind]["records_v1_only"],
                    records_v2_only=counts[kind]["records_v2_only"],
                    occurrences_v2=counts[kind]["occurrences_v2"],
                    by_form_class_v2=MappingProxyType(dict(sorted(forms[kind].items()))),
                    records_quoted_or_tail_only=counts[kind]["records_quoted_or_tail_only"],
                    records_keyword_without_number=counts[kind]["records_keyword_without_number"],
                    records_unsupported_shape=(
                        counts[kind]["records_unsupported_shape"] if measured[kind] else None
                    ),
                )
                for kind in IdentifierKind
            }
        ),
    )
