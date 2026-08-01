"""Identifier issuance and the configured-source value.

Needs no database and is not marked `database`: everything here is a pure
function of its arguments and of `secrets`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, parse_identifier
from my_pa.domain.source import registry
from my_pa.domain.source.registry import (
    ConfiguredSource,
    InvalidSourceLabelError,
    SourceProviderKind,
    issue_identifier,
    validate_source_label,
)

#: A locator of exactly the shape `INV-PKL-005` is about. Synthetic; no such
#: path exists and none is opened here.
LOCATOR = "/synthetic/fixtures/2026/quarterly-report.md"

#: Words from that locator that could survive into a suffix if one were ever
#: derived from it. None is spellable in hexadecimal, so a hit is a real leak
#: and not a coincidence of the alphabet.
LOCATOR_WORDS = ("synthetic", "fixtures", "quarterly", "report", "md")

WHEN = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def test_the_registry_exposes_its_documented_surface() -> None:
    """Guards every other test here against passing on a gutted module."""
    assert set(registry.__all__) == {
        "ConfiguredSource",
        "InvalidSourceLabelError",
        "SourceProviderKind",
        "issue_identifier",
        "validate_source_label",
    }
    for name in registry.__all__:
        assert hasattr(registry, name), f"{name} is exported but absent"
    assert list(SourceProviderKind), "no provider kind is declared"


@pytest.mark.parametrize("kind", list(IdKind))
def test_every_kind_is_issuable_and_well_formed(kind: IdKind) -> None:
    identifier = issue_identifier(kind)
    assert parse_identifier(identifier) == (kind, identifier.partition("_")[2])


def test_issued_suffixes_are_hexadecimal_and_long_enough_to_be_unguessable() -> None:
    _, suffix = parse_identifier(issue_identifier(IdKind.SOURCE_OBJECT))
    assert len(suffix) == 32
    assert set(suffix) <= set("0123456789abcdef")


def test_issuance_does_not_repeat() -> None:
    issued = {issue_identifier(IdKind.SOURCE_OBJECT) for _ in range(1000)}
    assert len(issued) == 1000


def test_an_issued_identifier_does_not_contain_its_source_locator() -> None:
    """`INV-PKL-005`: a public identifier encodes no path, host, or key.

    `identifiers.py` can only check shape, so the property that matters is
    proved here, at the issuer, over enough samples that an accidental hit would
    show.
    """
    for _ in range(256):
        identifier = issue_identifier(IdKind.SOURCE_OBJECT)
        assert LOCATOR not in identifier
        for word in LOCATOR_WORDS:
            assert word not in identifier.lower(), f"{word!r} survived into an identifier"


def test_issuance_is_not_a_function_of_the_thing_being_named() -> None:
    """Two identifiers issued for one locator differ, so neither can encode it.

    This is the property a hash would fail. A digest of a path validates as a
    suffix and looks opaque, but it is reproducible from a guessed path, and the
    space of plausible filenames is small enough to enumerate.
    """
    first = issue_identifier(IdKind.SOURCE_OBJECT)
    second = issue_identifier(IdKind.SOURCE_OBJECT)
    assert first != second

    digest = hashlib.sha256(LOCATOR.encode("utf-8")).hexdigest()
    for identifier in (first, second):
        suffix = parse_identifier(identifier)[1]
        assert suffix != digest[: len(suffix)]
        assert suffix not in digest


@pytest.mark.parametrize(
    "label",
    ["Fixture corpus", "synthetic_documents", "Corpus-01", "a", "A" * 64],
)
def test_a_safe_label_is_accepted(label: str) -> None:
    assert validate_source_label(label) == label


@pytest.mark.parametrize(
    "label",
    [
        "",
        " leading space",
        "/synthetic/fixtures",
        "C:\\corpus",
        "nas.example.com",
        "operator@example.com",
        "corpus\nname",
        "A" * 65,
    ],
)
def test_a_label_that_could_carry_a_path_or_host_is_rejected(label: str) -> None:
    with pytest.raises(InvalidSourceLabelError):
        validate_source_label(label)


def test_a_rejected_label_is_not_echoed_back() -> None:
    """The redaction discipline of `bootstrap.settings`: name the defect, not the value."""
    private = "/synthetic/fixtures/2026"
    with pytest.raises(InvalidSourceLabelError) as raised:
        validate_source_label(private)
    assert private not in str(raised.value)


def test_a_configured_source_carries_no_locator() -> None:
    source = ConfiguredSource(
        source_id=issue_identifier(IdKind.SOURCE),
        provider_kind=SourceProviderKind.FIXTURE,
        label="Fixture corpus",
        classification=Classification.SYNTHETIC_TEST,
        configured_at=WHEN,
    )
    assert set(ConfiguredSource.__slots__) == {
        "source_id",
        "provider_kind",
        "label",
        "classification",
        "configured_at",
    }
    assert LOCATOR not in repr(source)


def test_a_configured_source_rejects_a_wrong_kind_of_identifier() -> None:
    with pytest.raises(InvalidIdentifierError):
        ConfiguredSource(
            source_id=issue_identifier(IdKind.SOURCE_OBJECT),
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            configured_at=WHEN,
        )


def test_a_configured_source_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ConfiguredSource(
            source_id=issue_identifier(IdKind.SOURCE),
            provider_kind=SourceProviderKind.FIXTURE,
            label="Fixture corpus",
            classification=Classification.SYNTHETIC_TEST,
            configured_at=datetime(2026, 8, 1, 12, 0),
        )
