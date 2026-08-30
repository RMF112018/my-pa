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
    #
    # The five managed-document prefixes were added to `IdKind` by WP-27 and not
    # to this set, so this test was red at `b2f6c7ba` before WP-28 touched
    # anything — a pre-existing gap, found by running the suite rather than
    # reported by anyone, and closed here rather than carried. WP-28 is the
    # package that puts three of them on the wire (`mdoc`, `mdver`, `mdrcpt` all
    # appear in `contracts/v1/documents.py`), which makes "these appear in the
    # public contract" true of them in the strongest sense.
    #
    # The seven Relationship Memory prefixes are here for the same reason: `mem`
    # and `memver` are returned on the wire by every `relationship_memory.*`
    # write and read, and `mctx`, `mevd`, `memsub`, `mprop` and `mpev` name rows
    # a caller can reach through history, evidence and the review queue.
    assert {kind.value for kind in IdKind} == {
        "mem",
        "memver",
        "mctx",
        "mevd",
        "memsub",
        "mprop",
        "mpev",
        "mdoc",
        "mdver",
        "mdsub",
        "mdrcpt",
        "mdlce",
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
        "abcred",
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
        "cmthst",
        "cdec",
        "tsk",
        "lce",
        "trec",
        "thst",
        "bulk",
        "ctxm",
        "cpref",
        "micr",
        "rrun",
        "rpt",
        "rrc",
        # WP-RI-01: the relationship-intelligence entity plane. Four prefixes,
        # one per table the migration creates. The plane's later records
        # (observations, proposals, context packets, merge lineage) get their
        # prefixes in the work packages that create their tables, so this set
        # never promises a prefix nothing issues.
        "ent",
        "xid",
        "asn",
        "erel",
        "eals",
        "eobs",
        "eprp",
        "emrg",
        # WP-RI-A-01: the entity plane's three lifecycle ledgers. `emut` names
        # one append-only ordinary mutation, `efev` one binding between a
        # canonical fact and the record evidencing it, and `erdc` one
        # append-only disposition of an observation. Added with the tables that
        # issue them, which is the rule the entity-plane comment above states:
        # this set never promises a prefix nothing issues.
        "emut",
        "efev",
        "erdc",
        # WP-RI-06's three identity-correction records: `eipv` the expiring
        # binding between an operator's approval and the versions a preview read,
        # `eiop` one admitted correction, and `eief` one append-only before/after
        # row of what that correction did. Added with the tables that issue them,
        # under the same rule -- a preview id and an operation id both cross the
        # wire, since `entities.merge` is given the preview id its own preview
        # returned.
        "eipv",
        "eiop",
        "eief",
        # `b727e870d45e`'s identity-ambiguity identifier: one question a merge
        # preview could not answer. It crosses the wire for the same reason
        # `eipv` does -- the preview returns its ambiguities and `entities.merge`
        # is handed back the ambiguity ids the operator settled.
        "eiam",
        # `7e114f822af2` (RI-ENT-WP-02): one typed name row of an entity, in
        # `entity_names`. `entity_organization_profiles` needs no prefix of
        # its own -- its primary key is `entity_id`, already `ent` above.
        "enam",
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
