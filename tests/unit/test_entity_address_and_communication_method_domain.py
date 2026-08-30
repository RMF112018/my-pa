"""`EntityAddress`/`EntityCommunicationMethod` invariants, without persistence (RI-ENT-WP-03).

Every rule asserted here is also a CHECK constraint in `441b071bf37b`; the
database half lives in
`tests/schema/test_entity_addresses_and_communication_methods_migration.py`.
This module proves only what a dataclass can prove, on the same argument
`tests/unit/test_entity_name_and_organization_profile_domain.py` states for
`EntityName`/`EntityOrganizationProfile`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    CommunicationVerificationStatusCode,
    EntityAddress,
    EntityAddressState,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    is_normalized_communication_value,
    normalize_address,
    normalize_communication_value,
)

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
ENTITY = "ent_aaaa0001aaaa0001"

ENTITY_ADDRESS = "eadr_aaaa0001aaaa0001"
OTHER_ENTITY_ADDRESS = "eadr_bbbb0002bbbb0002"

COMMUNICATION_METHOD = "ecmm_aaaa0001aaaa0001"
OTHER_COMMUNICATION_METHOD = "ecmm_bbbb0002bbbb0002"
EXTERNAL_IDENTIFIER = "xid_aaaa0001aaaa0001"

WHEN = datetime(2026, 8, 17, 12, tzinfo=UTC)
LATER = WHEN + timedelta(days=1)

#: Synthetic only, per the same discipline
#: `tests/database/test_entity_names_tbr_gs4_studios_fixture.py` applies: never
#: a literal value from the audit's real-register case study.
_RAW_ADDRESS = "742 Synthetic Lane, Springfield, IL 90210"


def an_entity_address(**overrides: object) -> EntityAddress:
    fields: dict[str, object] = {
        "entity_address_id": ENTITY_ADDRESS,
        "entity_id": ENTITY,
        "principal_id": PRINCIPAL,
        "address_type_code": AddressTypeCode.LEGAL_PRINCIPAL,
        "raw_value": _RAW_ADDRESS,
        "normalized_address_value": normalize_address(
            line1=None,
            line2=None,
            city=None,
            region=None,
            postal_code=None,
            country=None,
            raw_value=_RAW_ADDRESS,
        ),
    }
    return EntityAddress(**{**fields, **overrides})  # type: ignore[arg-type]


def a_communication_method(**overrides: object) -> EntityCommunicationMethod:
    fields: dict[str, object] = {
        "communication_method_id": COMMUNICATION_METHOD,
        "entity_id": ENTITY,
        "principal_id": PRINCIPAL,
        "method_type_code": CommunicationMethodTypeCode.EMAIL,
        "usage_context_code": CommunicationUsageContextCode.CORPORATE,
        "normalized_value": "contact@synthetic-example.test",
        "display_value": "contact@synthetic-example.test",
    }
    return EntityCommunicationMethod(**{**fields, **overrides})  # type: ignore[arg-type]


# --- EntityAddress: construction and defaults ---------------------------------


def test_an_entity_address_defaults_to_active_and_not_preferred() -> None:
    address = an_entity_address()
    assert address.state is EntityAddressState.ACTIVE
    assert address.is_preferred is False
    assert address.version == 1


def test_an_entity_address_rejects_an_unknown_identifier_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_entity_address(entity_address_id="xid_aaaa0001aaaa0001")


@pytest.mark.parametrize("address_type", list(AddressTypeCode))
def test_an_entity_address_constructs_for_every_closed_address_type(
    address_type: AddressTypeCode,
) -> None:
    address = an_entity_address(address_type_code=address_type)
    assert address.address_type_code is address_type


def test_an_entity_address_has_a_closed_address_type() -> None:
    with pytest.raises(ValueError, match="closed address type"):
        an_entity_address(address_type_code="warehouse")


def test_an_entity_address_has_a_closed_state() -> None:
    with pytest.raises(ValueError, match="closed state"):
        an_entity_address(state="pending")


# --- EntityAddress: blank-value invariants -------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_an_entity_address_raw_value_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        an_entity_address(raw_value=blank)


@pytest.mark.parametrize(
    "field_name", ["line1", "line2", "city", "region", "postal_code", "country", "label"]
)
@pytest.mark.parametrize("blank", ["", "   "])
def test_an_entity_address_optional_field_is_not_blank_when_present(
    field_name: str, blank: str
) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        an_entity_address(**{field_name: blank})


def test_an_entity_address_normalized_value_is_not_blank() -> None:
    # An empty normalized value can only be reached by also passing a blank
    # raw_value with no structure, and the raw_value check fires first, so this
    # exercises the normalized-value blank check by passing a value that would
    # itself be blank were it not for the raw_value guard -- i.e. it proves the
    # guard exists at all rather than being unreachable dead code.
    with pytest.raises(ValueError, match="not blank"):
        an_entity_address(raw_value="x", normalized_address_value="   ")


# --- EntityAddress: normalized_address_value must match normalize_address -----


def test_an_entity_address_normalized_value_must_already_be_normalized() -> None:
    with pytest.raises(ValueError, match="already normalized"):
        an_entity_address(normalized_address_value="742 SYNTHETIC LANE")


def test_an_entity_address_normalized_value_matches_structured_fields_when_present() -> None:
    address = an_entity_address(
        line1="742 Synthetic Lane",
        city="Springfield",
        normalized_address_value=normalize_address(
            line1="742 Synthetic Lane",
            line2=None,
            city="Springfield",
            region=None,
            postal_code=None,
            country=None,
            raw_value=_RAW_ADDRESS,
        ),
    )
    assert address.normalized_address_value == "742 synthetic lane|springfield"


def test_an_entity_address_normalized_value_disagreeing_with_structure_is_refused() -> None:
    """A normalized value computed for one structure cannot be stored against another."""
    with pytest.raises(ValueError, match="already normalized"):
        an_entity_address(
            line1="742 Synthetic Lane",
            city="Springfield",
            # This is what normalize_address would produce for city alone --
            # it disagrees with the (line1, city) structure actually supplied.
            normalized_address_value="springfield",
        )


# --- EntityAddress: remaining scalar invariants --------------------------------


def test_an_entity_address_is_preferred_must_be_a_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        an_entity_address(is_preferred="yes")


def test_an_entity_address_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive"):
        an_entity_address(version=0)


def test_an_entity_address_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        an_entity_address(effective_from=LATER, effective_to=WHEN)


def test_an_entity_address_is_retired_only_once_it_leaves_service() -> None:
    with pytest.raises(ValueError, match="retired only once it leaves service"):
        an_entity_address(retired_at=WHEN, state=EntityAddressState.ACTIVE)
    retired = an_entity_address(retired_at=WHEN, state=EntityAddressState.RETIRED)
    assert retired.retired_at == WHEN


def test_an_entity_address_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        an_entity_address(
            entity_address_id=ENTITY_ADDRESS,
            state=EntityAddressState.SUPERSEDED,
            superseded_by_entity_address_id=ENTITY_ADDRESS,
        )


def test_an_entity_address_names_a_successor_only_when_superseded() -> None:
    with pytest.raises(ValueError, match="names a successor only when superseded"):
        an_entity_address(
            state=EntityAddressState.ACTIVE,
            superseded_by_entity_address_id=OTHER_ENTITY_ADDRESS,
        )
    superseded = an_entity_address(
        state=EntityAddressState.SUPERSEDED,
        superseded_by_entity_address_id=OTHER_ENTITY_ADDRESS,
    )
    assert superseded.superseded_by_entity_address_id == OTHER_ENTITY_ADDRESS


# --- normalize_address ---------------------------------------------------------


def test_normalize_address_with_no_structure_falls_back_to_the_raw_value() -> None:
    result = normalize_address(
        line1=None,
        line2=None,
        city=None,
        region=None,
        postal_code=None,
        country=None,
        raw_value="  742 Synthetic   Lane, Springfield  ",
    )
    # A fold of the whole raw_value as ONE token -- never split on the comma
    # into structure. This is the proof that normalize_address never infers.
    assert result == "742 synthetic lane, springfield"
    assert "|" not in result


def test_normalize_address_with_partial_structure_uses_only_the_known_fields() -> None:
    result = normalize_address(
        line1=None,
        line2=None,
        city="Springfield",
        region=None,
        postal_code=None,
        country="USA",
        raw_value=_RAW_ADDRESS,
    )
    # Fixed field order (line1, line2, city, region, postal_code, country);
    # unknown fields (line1/line2/region/postal_code) are simply absent, not
    # guessed from raw_value, and the known ones are folded and joined by "|".
    assert result == "springfield|usa"


def test_normalize_address_is_stable_regardless_of_surrounding_whitespace_and_case() -> None:
    result_a = normalize_address(
        line1="  742 Synthetic Lane  ",
        line2=None,
        city="SPRINGFIELD",
        region=None,
        postal_code=None,
        country=None,
        raw_value=_RAW_ADDRESS,
    )
    result_b = normalize_address(
        line1="742 synthetic lane",
        line2=None,
        city="springfield",
        region=None,
        postal_code=None,
        country=None,
        raw_value=_RAW_ADDRESS,
    )
    assert result_a == result_b == "742 synthetic lane|springfield"


def test_normalize_address_never_parses_raw_value_into_structure() -> None:
    """RULING 3: raw_value alone never becomes city/region/postal_code/country.

    Two different raw_values that a human would recognise as the same address
    (one with structure spelled out, one without) do NOT normalize to the same
    value here -- because doing so would require inferring the missing
    structure from the string, which this function's contract explicitly
    refuses to do.
    """
    only_raw = normalize_address(
        line1=None,
        line2=None,
        city=None,
        region=None,
        postal_code=None,
        country=None,
        raw_value="742 Synthetic Lane, Springfield, IL",
    )
    with_structure = normalize_address(
        line1="742 Synthetic Lane",
        line2=None,
        city="Springfield",
        region="IL",
        postal_code=None,
        country=None,
        raw_value="742 Synthetic Lane, Springfield, IL",
    )
    assert only_raw != with_structure
    assert only_raw == "742 synthetic lane, springfield, il"
    assert with_structure == "742 synthetic lane|springfield|il"


def test_normalize_address_treats_blank_structured_fields_as_unknown() -> None:
    """A structured field that is present but blank is treated the same as absent."""
    result = normalize_address(
        line1="",
        line2="   ",
        city="Springfield",
        region=None,
        postal_code=None,
        country=None,
        raw_value=_RAW_ADDRESS,
    )
    assert result == "springfield"


# --- EntityCommunicationMethod: construction and defaults ----------------------


def test_a_communication_method_defaults_to_active_and_unresolved() -> None:
    method = a_communication_method()
    assert method.state is EntityCommunicationMethodState.ACTIVE
    assert method.is_preferred is False
    assert method.version == 1
    assert method.verification_status_code is CommunicationVerificationStatusCode.UNRESOLVED


def test_a_communication_method_rejects_an_unknown_identifier_kind() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_communication_method(communication_method_id="xid_aaaa0001aaaa0001")


@pytest.mark.parametrize(
    ("method_type", "normalized_value", "display_value"),
    [
        (
            CommunicationMethodTypeCode.EMAIL,
            "contact@synthetic-example.test",
            "contact@synthetic-example.test",
        ),
        (CommunicationMethodTypeCode.PHONE, "5551234567", "(555) 123-4567"),
        (CommunicationMethodTypeCode.DOMAIN, "synthetic-example.test", "synthetic-example.test"),
        (
            CommunicationMethodTypeCode.WEBSITE,
            "https://synthetic-example.test",
            "https://synthetic-example.test",
        ),
    ],
)
def test_a_communication_method_constructs_for_every_closed_method_type(
    method_type: CommunicationMethodTypeCode, normalized_value: str, display_value: str
) -> None:
    method = a_communication_method(
        method_type_code=method_type,
        normalized_value=normalized_value,
        display_value=display_value,
    )
    assert method.method_type_code is method_type


def test_a_communication_method_has_a_closed_method_type() -> None:
    with pytest.raises(ValueError, match="closed method type"):
        a_communication_method(method_type_code="fax")


@pytest.mark.parametrize("usage_context", list(CommunicationUsageContextCode))
def test_a_communication_method_constructs_for_every_closed_usage_context(
    usage_context: CommunicationUsageContextCode,
) -> None:
    method = a_communication_method(usage_context_code=usage_context)
    assert method.usage_context_code is usage_context


def test_a_communication_method_has_a_closed_usage_context() -> None:
    with pytest.raises(ValueError, match="closed usage context"):
        a_communication_method(usage_context_code="marketing")


def test_a_communication_method_has_a_closed_verification_status() -> None:
    with pytest.raises(ValueError, match="closed verification status"):
        a_communication_method(verification_status_code="probably_true")


def test_a_communication_method_has_a_closed_state() -> None:
    with pytest.raises(ValueError, match="closed state"):
        a_communication_method(state="pending")


# --- EntityCommunicationMethod: blank/normalization invariants -----------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_communication_method_display_value_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_communication_method(display_value=blank)


def test_a_communication_method_normalized_value_must_already_be_normalized() -> None:
    with pytest.raises(ValueError, match="already normalized"):
        a_communication_method(normalized_value="Contact@Synthetic-Example.TEST")


def test_a_communication_method_normalized_value_must_be_well_formed_for_its_type() -> None:
    with pytest.raises(ValueError, match="already normalized"):
        a_communication_method(
            method_type_code=CommunicationMethodTypeCode.PHONE,
            normalized_value="12345",  # too few digits, never well-formed as a phone
        )


# --- EntityCommunicationMethod: remaining scalar invariants --------------------


def test_a_communication_method_is_preferred_must_be_a_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        a_communication_method(is_preferred="yes")


def test_a_communication_method_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive"):
        a_communication_method(version=0)


def test_a_communication_method_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        a_communication_method(effective_from=LATER, effective_to=WHEN)


def test_a_communication_method_is_retired_only_once_it_leaves_service() -> None:
    with pytest.raises(ValueError, match="retired only once it leaves service"):
        a_communication_method(retired_at=WHEN, state=EntityCommunicationMethodState.ACTIVE)
    retired = a_communication_method(retired_at=WHEN, state=EntityCommunicationMethodState.RETIRED)
    assert retired.retired_at == WHEN


def test_a_communication_method_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        a_communication_method(
            communication_method_id=COMMUNICATION_METHOD,
            state=EntityCommunicationMethodState.SUPERSEDED,
            superseded_by_communication_method_id=COMMUNICATION_METHOD,
        )


def test_a_communication_method_names_a_successor_only_when_superseded() -> None:
    with pytest.raises(ValueError, match="names a successor only when superseded"):
        a_communication_method(
            state=EntityCommunicationMethodState.ACTIVE,
            superseded_by_communication_method_id=OTHER_COMMUNICATION_METHOD,
        )
    superseded = a_communication_method(
        state=EntityCommunicationMethodState.SUPERSEDED,
        superseded_by_communication_method_id=OTHER_COMMUNICATION_METHOD,
    )
    assert superseded.superseded_by_communication_method_id == OTHER_COMMUNICATION_METHOD


# --- The identity/channel boundary ---------------------------------------------


def test_a_non_email_method_cannot_link_an_external_identifier() -> None:
    with pytest.raises(ValueError, match="links an external identifier only for email"):
        a_communication_method(
            method_type_code=CommunicationMethodTypeCode.PHONE,
            normalized_value="5551234567",
            display_value="(555) 123-4567",
            linked_external_identifier_id=EXTERNAL_IDENTIFIER,
        )


def test_a_domain_or_website_method_cannot_link_an_external_identifier() -> None:
    for method_type in (CommunicationMethodTypeCode.DOMAIN, CommunicationMethodTypeCode.WEBSITE):
        with pytest.raises(ValueError, match="links an external identifier only for email"):
            a_communication_method(
                method_type_code=method_type,
                normalized_value="synthetic-example.test",
                display_value="synthetic-example.test",
                linked_external_identifier_id=EXTERNAL_IDENTIFIER,
            )


def test_an_email_method_may_link_an_external_identifier() -> None:
    method = a_communication_method(
        method_type_code=CommunicationMethodTypeCode.EMAIL,
        linked_external_identifier_id=EXTERNAL_IDENTIFIER,
    )
    assert method.linked_external_identifier_id == EXTERNAL_IDENTIFIER


def test_an_email_method_rejects_an_unknown_identifier_kind_for_the_link() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_communication_method(
            method_type_code=CommunicationMethodTypeCode.EMAIL,
            linked_external_identifier_id="ent_aaaa0001aaaa0001",
        )


# --- normalize_communication_value / is_normalized_communication_value --------


def test_normalize_communication_value_lowercases_the_whole_email_including_the_local_part() -> (
    None
):
    """Per the module docstring: unlike `normalization._normalize_email`, this
    function DOES casefold the local part -- a contact channel is lower
    precision than an identity binding, so this is deliberately NOT
    RFC-standard local-part case sensitivity."""
    result = normalize_communication_value(
        CommunicationMethodTypeCode.EMAIL, "Foo.BAR@Synthetic-Example.TEST"
    )
    assert result == "foo.bar@synthetic-example.test"


@pytest.mark.parametrize(
    "malformed",
    ["not-an-email", "@synthetic-example.test", "foo@", "foo@bar@synthetic-example.test"],
)
def test_normalize_communication_value_rejects_a_malformed_email(malformed: str) -> None:
    with pytest.raises(ValueError, match="local part and domain"):
        normalize_communication_value(CommunicationMethodTypeCode.EMAIL, malformed)


def test_normalize_communication_value_strips_a_phone_to_digits_only() -> None:
    result = normalize_communication_value(CommunicationMethodTypeCode.PHONE, "+1 (555) 123-4567")
    assert result == "15551234567"
    assert result.isdigit()


def test_normalize_communication_value_rejects_a_phone_with_too_few_digits() -> None:
    with pytest.raises(ValueError, match="too few digits"):
        normalize_communication_value(CommunicationMethodTypeCode.PHONE, "12345")


@pytest.mark.parametrize(
    "method_type", [CommunicationMethodTypeCode.DOMAIN, CommunicationMethodTypeCode.WEBSITE]
)
def test_normalize_communication_value_case_folds_domain_and_website(
    method_type: CommunicationMethodTypeCode,
) -> None:
    result = normalize_communication_value(method_type, "Synthetic-Example.TEST")
    assert result == "synthetic-example.test"


@pytest.mark.parametrize(
    "method_type", [CommunicationMethodTypeCode.DOMAIN, CommunicationMethodTypeCode.WEBSITE]
)
def test_normalize_communication_value_rejects_an_at_sign_for_domain_and_website(
    method_type: CommunicationMethodTypeCode,
) -> None:
    with pytest.raises(ValueError, match="bare host, not a mailbox"):
        normalize_communication_value(method_type, "contact@synthetic-example.test")


@pytest.mark.parametrize(
    "method_type", [CommunicationMethodTypeCode.DOMAIN, CommunicationMethodTypeCode.WEBSITE]
)
def test_normalize_communication_value_rejects_whitespace_for_domain_and_website(
    method_type: CommunicationMethodTypeCode,
) -> None:
    with pytest.raises(ValueError, match="bare host, not a mailbox"):
        normalize_communication_value(method_type, "synthetic example.test")


@pytest.mark.parametrize("blank", ["", "   "])
def test_normalize_communication_value_rejects_a_blank_value(blank: str) -> None:
    with pytest.raises(ValueError, match="normalizes to nothing matchable"):
        normalize_communication_value(CommunicationMethodTypeCode.DOMAIN, blank)


def test_normalize_communication_value_requires_a_closed_method_type() -> None:
    with pytest.raises(ValueError, match="closed method type"):
        normalize_communication_value("fax", "555-1234")  # type: ignore[arg-type]


def test_is_normalized_communication_value_is_true_for_the_canonical_form() -> None:
    assert is_normalized_communication_value(
        CommunicationMethodTypeCode.EMAIL, "contact@synthetic-example.test"
    )
    assert is_normalized_communication_value(CommunicationMethodTypeCode.PHONE, "5551234567")


def test_is_normalized_communication_value_is_false_for_an_unnormalized_form() -> None:
    assert not is_normalized_communication_value(
        CommunicationMethodTypeCode.EMAIL, "Contact@Synthetic-Example.TEST"
    )
    assert not is_normalized_communication_value(
        CommunicationMethodTypeCode.PHONE, "(555) 123-4567"
    )


def test_is_normalized_communication_value_is_false_rather_than_raising_for_a_malformed_value() -> (
    None
):
    assert not is_normalized_communication_value(CommunicationMethodTypeCode.EMAIL, "not-an-email")
    assert not is_normalized_communication_value(CommunicationMethodTypeCode.PHONE, "12345")


# --- Closed-vocabulary completeness (campaign document) ------------------------


def test_address_type_code_is_exactly_the_nine_audit_roles() -> None:
    assert {member.value for member in AddressTypeCode} == {
        "project",
        "legal_principal",
        "headquarters",
        "regional_office",
        "office",
        "business",
        "mailing",
        "city_hall",
        "known_other",
    }


def test_entity_address_state_is_exactly_the_three_lifecycle_states() -> None:
    assert {member.value for member in EntityAddressState} == {"active", "retired", "superseded"}


def test_communication_method_type_code_is_exactly_the_four_channel_kinds() -> None:
    assert {member.value for member in CommunicationMethodTypeCode} == {
        "email",
        "phone",
        "domain",
        "website",
    }


def test_communication_usage_context_code_is_exactly_the_seven_usage_roles() -> None:
    assert {member.value for member in CommunicationUsageContextCode} == {
        "corporate",
        "project",
        "project_sales",
        "generic",
        "personal",
        "office",
        "other",
    }


def test_communication_verification_status_is_not_a_confidence_field() -> None:
    """The same evidence-anchored vocabulary shape `LegalIdentityStatusCode`
    uses, deliberately its own enum (RULING 1)."""
    for status in CommunicationVerificationStatusCode:
        assert "confidence" not in status.value
        assert "certainty" not in status.value
        assert "probability" not in status.value
        assert "likelihood" not in status.value
        method = a_communication_method(verification_status_code=status)
        assert method.verification_status_code is status
    assert {member.value for member in CommunicationVerificationStatusCode} == {
        "verified",
        "best_supported",
        "unresolved",
        "awaiting_confirmation",
    }


def test_entity_communication_method_state_is_exactly_the_three_lifecycle_states() -> None:
    assert {member.value for member in EntityCommunicationMethodState} == {
        "active",
        "retired",
        "superseded",
    }
