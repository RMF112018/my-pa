"""`EntityName`/`EntityOrganizationProfile` invariants, without persistence (RI-ENT-WP-02).

Every rule asserted here is also a CHECK constraint in `7e114f822af2`; the
database half lives in `tests/schema/test_entity_names_and_organization_profile_migration.py`.
This module proves only what a dataclass can prove, on the same argument
`tests/unit/test_entity_domain.py` states for the rest of the entity plane.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.entity import (
    EntityName,
    EntityNameState,
    EntityOrganizationProfile,
    LegalIdentityStatusCode,
    NameTypeCode,
    OrganizationKindCode,
)

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
ENTITY = "ent_aaaa0001aaaa0001"
ENTITY_NAME = "enam_aaaa0001aaaa0001"
OTHER_ENTITY_NAME = "enam_bbbb0002bbbb0002"

WHEN = datetime(2026, 8, 17, 12, tzinfo=UTC)
LATER = WHEN + timedelta(days=1)


def an_entity_name(**overrides: object) -> EntityName:
    fields: dict[str, object] = {
        "entity_name_id": ENTITY_NAME,
        "entity_id": ENTITY,
        "principal_id": PRINCIPAL,
        "name_type_code": NameTypeCode.LEGAL,
        # Synthetic, per the same discipline
        # `tests/database/test_entity_names_tbr_gs4_studios_fixture.py` applies:
        # never a literal name from the audit's real-register case study.
        "display_value": "Synthetic Studio Four, LLC",
        "normalized_value": "synthetic studio four llc",
    }
    return EntityName(**{**fields, **overrides})  # type: ignore[arg-type]


def an_organization_profile(**overrides: object) -> EntityOrganizationProfile:
    fields: dict[str, object] = {
        "entity_id": ENTITY,
        "principal_id": PRINCIPAL,
        "organization_kind_code": OrganizationKindCode.LLC_OR_SPV,
        "legal_identity_status_code": LegalIdentityStatusCode.BEST_SUPPORTED,
    }
    return EntityOrganizationProfile(**{**fields, **overrides})  # type: ignore[arg-type]


# --- EntityName ---------------------------------------------------------------


def test_an_entity_name_defaults_to_active_and_not_preferred() -> None:
    name = an_entity_name()
    assert name.state is EntityNameState.ACTIVE
    assert name.is_preferred is False
    assert name.version == 1


def test_an_entity_name_rejects_an_unknown_identifier_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_entity_name(entity_name_id="xid_aaaa0001aaaa0001")


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_an_entity_name_value_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        an_entity_name(normalized_value=blank)
    with pytest.raises(ValueError, match="not blank"):
        an_entity_name(display_value=blank)


def test_an_entity_name_normalized_value_must_already_be_normalized() -> None:
    with pytest.raises(ValueError, match="already normalized"):
        an_entity_name(normalized_value="Synthetic Studio Four LLC")


def test_an_entity_name_has_a_closed_name_type() -> None:
    with pytest.raises(ValueError, match="closed name type"):
        an_entity_name(name_type_code="trademark")  # type: ignore[arg-type]


def test_an_entity_name_has_a_closed_state() -> None:
    with pytest.raises(ValueError, match="closed state"):
        an_entity_name(state="pending")  # type: ignore[arg-type]


def test_is_preferred_must_be_a_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        an_entity_name(is_preferred="yes")  # type: ignore[arg-type]


def test_an_entity_name_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive"):
        an_entity_name(version=0)


def test_an_entity_name_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        an_entity_name(effective_from=LATER, effective_to=WHEN)


def test_an_entity_name_is_retired_only_once_it_leaves_service() -> None:
    with pytest.raises(ValueError, match="retired only once it leaves service"):
        an_entity_name(retired_at=WHEN, state=EntityNameState.ACTIVE)
    # ENDED (retired) with a retired_at is fine.
    retired = an_entity_name(retired_at=WHEN, state=EntityNameState.RETIRED)
    assert retired.retired_at == WHEN


def test_an_entity_name_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        an_entity_name(
            entity_name_id=ENTITY_NAME,
            state=EntityNameState.SUPERSEDED,
            superseded_by_entity_name_id=ENTITY_NAME,
        )


def test_an_entity_name_names_a_successor_only_when_superseded() -> None:
    with pytest.raises(ValueError, match="names a successor only when superseded"):
        an_entity_name(
            state=EntityNameState.ACTIVE,
            superseded_by_entity_name_id=OTHER_ENTITY_NAME,
        )
    superseded = an_entity_name(
        state=EntityNameState.SUPERSEDED,
        superseded_by_entity_name_id=OTHER_ENTITY_NAME,
    )
    assert superseded.superseded_by_entity_name_id == OTHER_ENTITY_NAME


@pytest.mark.parametrize("moment", [datetime(2026, 8, 17, 12), None])
def test_an_entity_name_refuses_a_naive_effective_from(moment: object) -> None:
    if moment is None:
        return  # None is a legitimate absence, not a naive datetime.
    with pytest.raises((ValueError, TypeError, AttributeError)):
        an_entity_name(effective_from=moment)


def test_a_historical_name_type_is_admitted_without_implying_a_new_juristic_entity() -> None:
    """`HISTORICAL_NAME` is a former name of the *same* entity; see the class
    docstring for why an acquisition is a separate `Entity` row instead."""
    former = an_entity_name(
        name_type_code=NameTypeCode.HISTORICAL_NAME,
        display_value="Synthetic Predecessor Holdings",
        normalized_value="synthetic predecessor holdings",
        state=EntityNameState.RETIRED,
        retired_at=WHEN,
    )
    assert former.name_type_code is NameTypeCode.HISTORICAL_NAME
    assert former.entity_id == ENTITY  # same entity, not a different one


# --- EntityOrganizationProfile -------------------------------------------------------


def test_an_organization_profile_defaults_version_to_one() -> None:
    profile = an_organization_profile()
    assert profile.version == 1
    assert profile.jurisdiction_code is None
    assert profile.registration_identifier is None


def test_an_organization_profile_has_a_closed_organization_kind() -> None:
    with pytest.raises(ValueError, match="closed organization kind"):
        an_organization_profile(organization_kind_code="shell_corp")  # type: ignore[arg-type]


def test_an_organization_profile_has_a_closed_legal_identity_status() -> None:
    with pytest.raises(ValueError, match="closed legal identity status"):
        an_organization_profile(legal_identity_status_code="probably_true")  # type: ignore[arg-type]


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_organization_profile_jurisdiction_code_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        an_organization_profile(jurisdiction_code=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_organization_profile_registration_identifier_is_not_blank_when_present(
    blank: str,
) -> None:
    with pytest.raises(ValueError, match="not blank"):
        an_organization_profile(registration_identifier=blank)


def test_an_organization_profile_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive"):
        an_organization_profile(version=0)


def test_an_organization_profile_cannot_be_updated_before_it_is_created() -> None:
    with pytest.raises(ValueError, match="updated before it is created"):
        an_organization_profile(created_at=LATER, updated_at=WHEN)


def test_an_organization_profile_rejects_an_unknown_identifier_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_organization_profile(entity_id="prn_aaaa0001aaaa0001aaaa0001")


def test_legal_identity_status_is_not_a_confidence_field() -> None:
    """The audit's own vocabulary (verified/best_supported/unresolved/
    awaiting_confirmation), not a numeric score. RULING 1."""
    for status in LegalIdentityStatusCode:
        assert "confidence" not in status.value
        assert "certainty" not in status.value
        assert "probability" not in status.value
        profile = an_organization_profile(legal_identity_status_code=status)
        assert profile.legal_identity_status_code is status
