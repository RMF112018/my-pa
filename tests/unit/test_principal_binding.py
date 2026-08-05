"""The identity binding is a bijection where one exists and a stable digest elsewhere.

`WP-03` (`PKL-MYPA-D-WP03-001`) makes the capture plane's owner an authorization
input, so the durable identity plane's UUID and the knowledge schema's
`prn_...` text form must name the same person deterministically. This module
proves the three properties that determination rests on:

* the bound form round-trips exactly — a durable UUID rendered by
  `capture_principal_id` recovers itself through `durable_principal_uuid`.
  `issue_identifier` mints `token_hex(16)` suffixes, so every historically
  minted principal is *already* in the bound form and rides the same exact
  branch; the round trip below covers it by construction.
* an identifier outside the bound form — longer, shorter, or non-hex, all of
  which `IdKind.PRINCIPAL` admits — resolves to one stable UUIDv5 partition,
  the same one every time, and distinct identifiers resolve to distinct
  partitions.
* `LOCAL_OPERATOR_UUID` is a constant of the vocabulary, not of the process —
  recomputing it from its published derivation yields the same value, which is
  what makes a gateway restart the same owner (`D-67`'s premise dissolved).

Every value here is synthetic; nothing reads a store or validates a token.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError
from my_pa.domain.identity.binding import (
    LOCAL_OPERATOR_UUID,
    PRINCIPAL_NAMESPACE,
    capture_principal_id,
    durable_principal_uuid,
)
from my_pa.domain.source.registry import issue_identifier


def test_a_bound_identifier_recovers_its_uuid_exactly() -> None:
    """`durable_principal_uuid` is the exact inverse of `capture_principal_id`.

    Random UUIDs rather than one fixture value, because the claim is about the
    whole codomain: any durable principal the identity plane mints must come
    back as itself, or a capture written under one UUID would be owned by
    another after a round trip through the text form.
    """
    for _ in range(32):
        minted = uuid4()
        rendered = capture_principal_id(minted)
        assert rendered.startswith("prn_")
        assert durable_principal_uuid(rendered) == minted, (
            "the bound form did not round-trip, so a stored owner would drift "
            "from the durable identity that wrote it"
        )


def test_a_process_minted_identifier_is_already_the_bound_form() -> None:
    """`issue_identifier` mints 32 hex characters, which *is* the bound shape.

    Stated as a test rather than left to the docstring, because the exact
    branch of `durable_principal_uuid` silently owns every historical
    identifier only while this stays true. If `issue_identifier` ever widens
    its alphabet, resolution falls through to the digest — still stable, but
    this module's account of which branch owns legacy rows must be rewritten.
    """
    minted = issue_identifier(IdKind.PRINCIPAL)
    resolved = durable_principal_uuid(minted)
    assert resolved == UUID(hex=minted.removeprefix("prn_"))
    assert capture_principal_id(resolved) == minted


def test_an_identifier_outside_the_bound_form_digests_to_one_stable_partition() -> None:
    """A valid `prn_...` that is not 32 hex characters maps to one stable UUID.

    `IdKind.PRINCIPAL` admits 8-64 alphanumerics, so mixed case and other
    lengths are legal identifiers a caller may hold. The digest is pinned to
    its published derivation — UUIDv5 under `PRINCIPAL_NAMESPACE` — rather than
    merely to repeatability within one process, so a change to the derivation
    is a failure here rather than a silent re-partitioning that strands rows.
    """
    for legacy in ("prn_LegacyOperator01", "prn_" + "a" * 31, "prn_" + "A" * 32):
        resolved = durable_principal_uuid(legacy)
        assert resolved == durable_principal_uuid(legacy)
        assert resolved == uuid5(PRINCIPAL_NAMESPACE, legacy)


def test_distinct_identifiers_resolve_to_distinct_partitions() -> None:
    """Two principals cannot share a partition through the binding.

    A mix of bound and digest-branch identifiers, because the injectivity
    claim spans both vocabularies: a bound form colliding with a digest would
    let a crafted identifier read another principal's captures.
    """
    identifiers = [capture_principal_id(uuid4()) for _ in range(8)]
    identifiers += [f"prn_Legacy{index:08d}" for index in range(8)]
    resolved = [durable_principal_uuid(identifier) for identifier in identifiers]
    assert len(set(resolved)) == len(identifiers), (
        "two distinct principal identifiers resolved to one partition, which "
        "is exactly the cross-principal disclosure WP-03 exists to preclude"
    )


def test_the_local_operator_is_a_constant_of_the_vocabulary() -> None:
    """`LOCAL_OPERATOR_UUID` derives from fixed inputs, not from the process.

    Recomputed from its published derivation rather than compared to a copied
    literal, so the assertion holds exactly the property `QC-AC-013` needs:
    any two processes — including one before and after a restart — compute the
    same owner without coordinating.
    """
    recomputed = uuid5(uuid5(NAMESPACE_URL, "https://my-pa.invalid/principals"), "local-operator")
    assert recomputed == LOCAL_OPERATOR_UUID
    assert capture_principal_id(LOCAL_OPERATOR_UUID) == f"prn_{recomputed.hex}"


def test_resolution_is_closed_outside_the_valid_vocabulary() -> None:
    """Anything that is not a principal identifier is refused, not digested.

    Totality over the *valid* vocabulary is the module's promise; extending it
    to arbitrary strings would turn a caller-side bug into a real partition
    that quietly accumulates rows nobody can name.
    """
    for invalid in ("no-separator", "src_0123456789abcdef", "prn_short", "prn_has-hyphens!"):
        with pytest.raises(InvalidIdentifierError):
            durable_principal_uuid(invalid)
