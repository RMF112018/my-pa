"""Opaque identifier validation."""

from __future__ import annotations

import pytest

from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    make_identifier,
    parse_identifier,
    validate_identifier,
)


@pytest.mark.parametrize("kind", list(IdKind))
def test_every_kind_round_trips(kind: IdKind) -> None:
    identifier = make_identifier(kind, "abc123def456")
    assert parse_identifier(identifier) == (kind, "abc123def456")


def test_contract_prefixes_are_stable() -> None:
    # These strings appear in the public contract; changing one is a breaking change.
    assert {kind.value for kind in IdKind} == {
        "src",
        "obj",
        "ver",
        "enr",
        "op",
        "kn",
        "audit",
        "prn",
        "corr",
        "cap",
        "capver",
        "rcpt",
        "sub",
        "ptext",
        "stage",
        "span",
        "prop",
        "ccls",
        "men",
        "rvw",
        "rdec",
        "asrt",
        "clink",
        "conv",
        "per",
        "org",
        "iobs",
        "alias",
        "aff",
        "umen",
        "dups",
        "ires",
        "cov",
        "tli",
        "cpart",
        "sevd",
        "sobs",
        "smem",
        "nbrg",
        "nacct",
        "nbkt",
        "ndisc",
        "ncfg",
        "nrun",
        "nbrun",
        "njob",
        "ncp",
        "nsim",
        "nsimr",
        "nlg",
        "nauth",
        "sit",
        "frm",
        "trc",
        "prj",
        "psit",
        "revt",
        "puls",
        "cclt",
        "cmt",
        "cdec",
        "tsk",
        "lce",
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        "src",
        "src_",
        "_abc123def456",
        "unknown_abc123def456",
        "src_short",
        "src_" + "a" * 65,
        "src_abc-123-def",
        "src_abc 123 def",
        "SRC_abc123def456",
    ],
)
def test_malformed_identifiers_are_rejected(value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        validate_identifier(value)


def test_wrong_kind_is_rejected() -> None:
    with pytest.raises(InvalidIdentifierError):
        validate_identifier("src_abc123def456", IdKind.KNOWLEDGE)


def test_overlong_identifier_is_rejected() -> None:
    with pytest.raises(InvalidIdentifierError):
        validate_identifier("src_" + "a" * 100)


def test_validate_returns_value_unchanged() -> None:
    assert validate_identifier("kn_abc123def456") == "kn_abc123def456"


@pytest.mark.parametrize(
    "suffix",
    ["/Users/bob/tax.pdf", "host.example.com", "a@b", "short", "with space", "a" * 100],
)
def test_make_identifier_validates_the_suffix_it_is_given(suffix: str) -> None:
    """`make_identifier` is public, so it must not be a way around validation."""
    with pytest.raises(InvalidIdentifierError):
        make_identifier(IdKind.SOURCE, suffix)


@pytest.mark.parametrize("value", [123, None, ["src_abc123def456"], b"src_abc123def456"])
def test_non_string_input_fails_as_a_domain_error(value: object) -> None:
    """Domain models are plain dataclasses, so a non-string can reach this.

    It must surface as InvalidIdentifierError rather than as an incidental
    TypeError from len() or partition().
    """
    with pytest.raises(InvalidIdentifierError, match="must be a string"):
        validate_identifier(value)  # type: ignore[arg-type]


def test_identifier_does_not_carry_path_or_host_shape() -> None:
    # A leaked path or host would contain these characters; the suffix pattern
    # is alphanumeric precisely so they cannot appear.
    for illegal in ("/", "\\", ".", ":", "@", "~"):
        with pytest.raises(InvalidIdentifierError):
            validate_identifier(f"src_abc{illegal}123def")
