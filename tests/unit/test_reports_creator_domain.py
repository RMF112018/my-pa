"""The general report creator pseudonym (Reports Modernization WP05 A1)."""

from __future__ import annotations

import hashlib
import re
from typing import Final

import pytest

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.reports.creator import (
    CREATOR_DOMAIN_TAG,
    CREATOR_ID_PATTERN,
    CREATOR_ID_PREFIX,
    CreatorKind,
    ReportCreator,
    derive_creator,
    validate_creator_id,
)
from my_pa.domain.reports.errors import ReportValidationError

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
CLIENT: Final = "client-synthetic-0001"
#: Pinned: sha256(b"my_pa.reports.creator.v1\x00remote_client\x00client-synthetic-0001")[:40].
PINNED_REMOTE: Final = "gcrt_9bd1df37596f4609e519ecc195bafdd678b04b6e"
PINNED_LOCAL: Final = "gcrt_46c813de63ea7cf5ab14fc14c74ed8bdc1f2a9c2"


def test_the_vocabulary_and_pattern_are_frozen() -> None:
    assert [kind.value for kind in CreatorKind] == ["local_principal", "remote_client"]
    assert CREATOR_DOMAIN_TAG == b"my_pa.reports.creator.v1"
    assert CREATOR_ID_PREFIX == "gcrt"
    assert CREATOR_ID_PATTERN == r"^gcrt_[0-9a-f]{40}$"


def test_derivation_is_deterministic_and_matches_the_pinned_vectors() -> None:
    remote = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)
    assert remote == derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)
    assert remote == ReportCreator(CreatorKind.REMOTE_CLIENT, PINNED_REMOTE)
    expected = hashlib.sha256(
        b"my_pa.reports.creator.v1\x00remote_client\x00" + CLIENT.encode()
    ).hexdigest()[:40]
    assert remote.creator_id == f"gcrt_{expected}"
    assert derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL).creator_id == PINNED_LOCAL


def test_kinds_and_subjects_are_separated() -> None:
    local = derive_creator(CreatorKind.LOCAL_PRINCIPAL, CLIENT)
    remote = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)
    assert local.creator_id != remote.creator_id
    assert (local.kind, remote.kind) == (CreatorKind.LOCAL_PRINCIPAL, CreatorKind.REMOTE_CLIENT)
    assert derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT + "x") != remote


def test_the_pseudonym_matches_the_pattern_and_discloses_no_subject() -> None:
    creator = derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT)
    assert re.fullmatch(CREATOR_ID_PATTERN, creator.creator_id)
    assert CLIENT not in creator.creator_id
    assert validate_creator_id(creator.creator_id) == creator.creator_id


@pytest.mark.parametrize("subject", ["", None, 7])
def test_an_empty_or_non_string_subject_is_refused(subject: object) -> None:
    with pytest.raises(ReportValidationError) as raised:
        derive_creator(CreatorKind.LOCAL_PRINCIPAL, subject)  # type: ignore[arg-type]
    assert (raised.value.field, raised.value.code) == ("creator", "subject")


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="service_account"):
        derive_creator("service_account", CLIENT)  # type: ignore[arg-type]
    with pytest.raises(ReportValidationError) as raised:
        ReportCreator("service_account", PINNED_LOCAL)  # type: ignore[arg-type]
    assert (raised.value.field, raised.value.code) == ("creator", "kind")


@pytest.mark.parametrize(
    "value",
    ["gcrt_" + "A" * 40, "gcrt_" + "a" * 39, "gcrt_" + "a" * 41, "gcrx_" + "a" * 40, ""],
)
def test_a_creator_value_outside_the_pattern_is_refused(value: str) -> None:
    with pytest.raises(ReportValidationError) as raised:
        ReportCreator(CreatorKind.LOCAL_PRINCIPAL, value)
    assert (raised.value.field, raised.value.code) == ("creator", "pattern")
    with pytest.raises(ReportValidationError) as raised:
        validate_creator_id(value)
    assert (raised.value.field, raised.value.code) == ("created_by", "pattern")


def test_gcrt_is_no_identifier_kind_and_no_id_kind_accepts_a_pseudonym() -> None:
    assert CREATOR_ID_PREFIX not in {kind.value for kind in IdKind}
    for kind in IdKind:
        assert not CREATOR_ID_PREFIX.startswith(kind.value + "_")
        with pytest.raises(InvalidIdentifierError):
            validate_identifier(PINNED_LOCAL, kind)
