"""A synthetic multi-address/multi-channel organization, against real PostgreSQL.

RI-ENT-WP-03, `TEST-001`. The manager was explicit that a single-address,
single-channel fixture would not prove the shape the TBR v3 register actually
needs: one organization commonly carries a legal-principal address distinct
from its project address, more than one office of the same type in different
cities, a corporate phone/website distinct from a project-specific one, and an
email contact channel that is optionally, but not necessarily, the same
mailbox identity resolution already tracks. This fixture builds exactly that
one organization and proves every one of those cases round-trips and respects
the uniqueness/preferred rules
`tests/schema/test_entity_addresses_and_communication_methods_migration.py`
locks down.

**Every name, address, phone number, domain, and identifier below is
synthetic.** Nothing here is drawn from, derived from, or shaped to reproduce
any real TBR register content, and "Synthetic Meridian Development Group" is
not, and is not modelled on, any real company (`MIGRATION-001`, `AGENTS.md`
section 5) -- the same discipline
`tests/database/test_entity_names_tbr_gs4_studios_fixture.py` applies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_entity_addresses_comm_tbr_fixture_test"

PRINCIPAL: Final = "prn_hhhh0011hhhh0011hhhh0011"

#: The one organization this fixture is about: synthetic "Synthetic Meridian
#: Development Group" analogue -- never a real company.
ORG_ENTITY: Final = "ent_hhhh0011hhhh0011"

#: A second, minimal, synthetic entity used ONLY for the identity/channel
#: boundary demonstration below -- not part of the composite organization
#: this fixture is otherwise about.
OTHER_ENTITY: Final = "ent_iiii0012iiii0012"

# --- Addresses -------------------------------------------------------------
LEGAL_PRINCIPAL_ADDRESS: Final = "eadr_hhhh0011aaaa0001"
PROJECT_ADDRESS: Final = "eadr_hhhh0011aaaa0002"
REGIONAL_OFFICE_DENVER: Final = "eadr_hhhh0011aaaa0003"
REGIONAL_OFFICE_ATLANTA: Final = "eadr_hhhh0011aaaa0004"

LEGAL_PRINCIPAL_RAW: Final = "100 Synthetic Plaza, Wilmington, DE 19801"
PROJECT_RAW: Final = "500 Synthetic Riverside Drive, Austin, TX 78701"
REGIONAL_OFFICE_DENVER_RAW: Final = "200 Synthetic Office Way, Denver, CO 80202"
REGIONAL_OFFICE_ATLANTA_RAW: Final = "300 Synthetic Corporate Court, Atlanta, GA 30301"

# --- Communication methods ---------------------------------------------------
CORPORATE_PHONE: Final = "ecmm_hhhh0011aaaa0001"
PROJECT_PHONE: Final = "ecmm_hhhh0011aaaa0002"
CORPORATE_WEBSITE: Final = "ecmm_hhhh0011aaaa0003"
PROJECT_WEBSITE: Final = "ecmm_hhhh0011aaaa0004"
CORPORATE_EMAIL: Final = "ecmm_hhhh0011aaaa0005"
OTHER_ENTITY_EMAIL_CHANNEL: Final = "ecmm_iiii0012aaaa0001"

CORPORATE_PHONE_NORMALIZED: Final = "15552001000"
PROJECT_PHONE_NORMALIZED: Final = "15552002000"
CORPORATE_WEBSITE_NORMALIZED: Final = "synthetic-meridian-example.test"
PROJECT_WEBSITE_NORMALIZED: Final = "project.synthetic-meridian-example.test"
CORPORATE_EMAIL_NORMALIZED: Final = "contact@synthetic-meridian-example.test"

EMAIL_IDENTIFIER: Final = "xid_hhhh0011aaaa0001"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.mark.database
def test_one_organization_carries_multiple_addresses_and_channels(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        # --- the one organization this fixture is about --------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, 'organization', :canonical, :display, "
                "'active')"
            ),
            {
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "canonical": "synthetic meridian development group",
                "display": "Synthetic Meridian Development Group",
            },
        )
        # A second, minimal entity used only for the identity/channel
        # boundary demonstration at the bottom of this test.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, 'organization', :canonical, :display, "
                "'active')"
            ),
            {
                "entity_id": OTHER_ENTITY,
                "principal_id": PRINCIPAL,
                "canonical": "synthetic unrelated affiliate",
                "display": "Synthetic Unrelated Affiliate",
            },
        )

        # --- legal_principal address AND a distinct project address --------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, raw_value, "
                "normalized_address_value, city, region, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'legal_principal', :raw, :normalized, "
                "'Wilmington', 'DE', true)"
            ),
            {
                "id": LEGAL_PRINCIPAL_ADDRESS,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "raw": LEGAL_PRINCIPAL_RAW,
                "normalized": "wilmington|de",
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, raw_value, "
                "normalized_address_value, city, region, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'project', :raw, :normalized, "
                "'Austin', 'TX', true)"
            ),
            {
                "id": PROJECT_ADDRESS,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "raw": PROJECT_RAW,
                "normalized": "austin|tx",
            },
        )

        # --- two regional_office addresses at different cities --------------
        # (proving multiple same-type addresses coexist when not identical --
        # exactly one is marked preferred).
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, raw_value, "
                "normalized_address_value, city, region, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'regional_office', :raw, :normalized, "
                "'Denver', 'CO', true)"
            ),
            {
                "id": REGIONAL_OFFICE_DENVER,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "raw": REGIONAL_OFFICE_DENVER_RAW,
                "normalized": "denver|co",
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, raw_value, "
                "normalized_address_value, city, region, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'regional_office', :raw, :normalized, "
                "'Atlanta', 'GA', false)"
            ),
            {
                "id": REGIONAL_OFFICE_ATLANTA,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "raw": REGIONAL_OFFICE_ATLANTA_RAW,
                "normalized": "atlanta|ga",
            },
        )

        # --- corporate phone AND a distinct project-context phone ----------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'phone', 'corporate', :normalized, "
                ":display, true)"
            ),
            {
                "id": CORPORATE_PHONE,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "normalized": CORPORATE_PHONE_NORMALIZED,
                "display": "+1 (555) 200-1000",
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'phone', 'project', :normalized, "
                ":display, false)"
            ),
            {
                "id": PROJECT_PHONE,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "normalized": PROJECT_PHONE_NORMALIZED,
                "display": "+1 (555) 200-2000",
            },
        )

        # --- corporate website AND a distinct project-context website ------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'website', 'corporate', :normalized, "
                ":display, true)"
            ),
            {
                "id": CORPORATE_WEBSITE,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "normalized": CORPORATE_WEBSITE_NORMALIZED,
                "display": "https://synthetic-meridian-example.test",
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, is_preferred) VALUES "
                "(:id, :entity_id, :principal_id, 'website', 'project', :normalized, "
                ":display, false)"
            ),
            {
                "id": PROJECT_WEBSITE,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "normalized": PROJECT_WEBSITE_NORMALIZED,
                "display": "https://project.synthetic-meridian-example.test",
            },
        )

        # --- the identity/channel cross-reference: a real
        # entity_external_identifiers row of namespace='email', for the SAME
        # entity/Principal, cross-referenced from an EMAIL communication
        # method -------------------------------------------------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_external_identifiers "  # noqa: S608
                "(identifier_id, entity_id, namespace, normalized_value, display_value, "
                "principal_id) VALUES "
                "(:id, :entity_id, 'email', :value, :value, :principal_id)"
            ),
            {
                "id": EMAIL_IDENTIFIER,
                "entity_id": ORG_ENTITY,
                "value": CORPORATE_EMAIL_NORMALIZED,
                "principal_id": PRINCIPAL,
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, is_preferred, "
                "linked_external_identifier_id) VALUES "
                "(:id, :entity_id, :principal_id, 'email', 'corporate', :normalized, "
                ":display, true, :linked_id)"
            ),
            {
                "id": CORPORATE_EMAIL,
                "entity_id": ORG_ENTITY,
                "principal_id": PRINCIPAL,
                "normalized": CORPORATE_EMAIL_NORMALIZED,
                "display": CORPORATE_EMAIL_NORMALIZED,
                "linked_id": EMAIL_IDENTIFIER,
            },
        )

        # --- the identity/channel boundary, demonstrated rather than merely
        # asserted: a SEPARATE, unrelated entity may hold a communication
        # method row carrying the IDENTICAL normalized email value with no
        # conflict, because entity_communication_methods carries no identity
        # uniqueness at all -- its active uniqueness index is scoped to
        # (entity_id, method_type_code, normalized_value), not to the value
        # alone. Only entity_external_identifiers enforces that at most one
        # ACTIVE binding of a given (namespace, normalized_value) may exist
        # per Principal (proven in
        # tests/schema/test_entity_schema_migration.py); this table is never
        # that authority.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value) VALUES "
                "(:id, :entity_id, :principal_id, 'email', 'generic', :normalized, :display)"
            ),
            {
                "id": OTHER_ENTITY_EMAIL_CHANNEL,
                "entity_id": OTHER_ENTITY,
                "principal_id": PRINCIPAL,
                "normalized": CORPORATE_EMAIL_NORMALIZED,
                "display": CORPORATE_EMAIL_NORMALIZED,
            },
        )

    # =========================================================================
    # Round-trip and rule assertions
    # =========================================================================
    with migrated_engine.connect() as connection:
        # --- addresses round-trip, four rows, on the one organization ------
        addresses = connection.execute(
            text(
                f"SELECT entity_address_id, address_type_code, raw_value, "  # noqa: S608
                "normalized_address_value, city, region, is_preferred, state "
                f"FROM {SCHEMA}.entity_addresses WHERE entity_id = :entity_id "
                "ORDER BY entity_address_id"
            ),
            {"entity_id": ORG_ENTITY},
        ).all()
        assert len(addresses) == 4
        by_id = {row.entity_address_id: row for row in addresses}

        assert by_id[LEGAL_PRINCIPAL_ADDRESS].address_type_code == "legal_principal"
        assert by_id[LEGAL_PRINCIPAL_ADDRESS].raw_value == LEGAL_PRINCIPAL_RAW
        assert by_id[LEGAL_PRINCIPAL_ADDRESS].normalized_address_value == "wilmington|de"
        assert by_id[LEGAL_PRINCIPAL_ADDRESS].is_preferred is True

        assert by_id[PROJECT_ADDRESS].address_type_code == "project"
        assert by_id[PROJECT_ADDRESS].raw_value == PROJECT_RAW
        assert by_id[PROJECT_ADDRESS].is_preferred is True

        # The two REQUIRED distinct addresses (legal_principal vs project) are
        # in fact different streets, not merely different types.
        assert by_id[LEGAL_PRINCIPAL_ADDRESS].raw_value != by_id[PROJECT_ADDRESS].raw_value

        # Multiple regional_office rows coexist because they are NOT identical.
        regional_offices = {
            row.entity_address_id: row
            for row in addresses
            if row.address_type_code == "regional_office"
        }
        assert set(regional_offices) == {REGIONAL_OFFICE_DENVER, REGIONAL_OFFICE_ATLANTA}
        assert regional_offices[REGIONAL_OFFICE_DENVER].city == "Denver"
        assert regional_offices[REGIONAL_OFFICE_ATLANTA].city == "Atlanta"
        assert (
            regional_offices[REGIONAL_OFFICE_DENVER].normalized_address_value
            != regional_offices[REGIONAL_OFFICE_ATLANTA].normalized_address_value
        )
        # Exactly one preferred regional_office -- the partial unique index
        # this fixture must respect, proven positively here (one true) rather
        # than merely by absence of an IntegrityError.
        preferred_regional_offices = [row for row in regional_offices.values() if row.is_preferred]
        assert len(preferred_regional_offices) == 1
        assert preferred_regional_offices[0].entity_address_id == REGIONAL_OFFICE_DENVER

        assert {row.state for row in addresses} == {"active"}

        # --- communication methods round-trip, five rows on the org --------
        methods = connection.execute(
            text(
                f"SELECT communication_method_id, method_type_code, usage_context_code, "  # noqa: S608
                "normalized_value, display_value, is_preferred, "
                "linked_external_identifier_id "
                f"FROM {SCHEMA}.entity_communication_methods WHERE entity_id = :entity_id "
                "ORDER BY communication_method_id"
            ),
            {"entity_id": ORG_ENTITY},
        ).all()
        assert len(methods) == 5
        methods_by_id = {row.communication_method_id: row for row in methods}

        # Corporate phone AND a distinct project-context phone.
        assert methods_by_id[CORPORATE_PHONE].method_type_code == "phone"
        assert methods_by_id[CORPORATE_PHONE].usage_context_code == "corporate"
        assert methods_by_id[CORPORATE_PHONE].normalized_value == CORPORATE_PHONE_NORMALIZED
        assert methods_by_id[PROJECT_PHONE].usage_context_code == "project"
        assert methods_by_id[PROJECT_PHONE].normalized_value == PROJECT_PHONE_NORMALIZED
        assert (
            methods_by_id[CORPORATE_PHONE].normalized_value
            != methods_by_id[PROJECT_PHONE].normalized_value
        )
        phones = [row for row in methods if row.method_type_code == "phone"]
        preferred_phones = [row for row in phones if row.is_preferred]
        assert len(preferred_phones) == 1
        assert preferred_phones[0].communication_method_id == CORPORATE_PHONE

        # Corporate website AND a distinct project-context website.
        assert methods_by_id[CORPORATE_WEBSITE].method_type_code == "website"
        assert methods_by_id[CORPORATE_WEBSITE].normalized_value == CORPORATE_WEBSITE_NORMALIZED
        assert methods_by_id[PROJECT_WEBSITE].normalized_value == PROJECT_WEBSITE_NORMALIZED
        assert (
            methods_by_id[CORPORATE_WEBSITE].normalized_value
            != methods_by_id[PROJECT_WEBSITE].normalized_value
        )
        websites = [row for row in methods if row.method_type_code == "website"]
        preferred_websites = [row for row in websites if row.is_preferred]
        assert len(preferred_websites) == 1
        assert preferred_websites[0].communication_method_id == CORPORATE_WEBSITE

        # The email channel, cross-referencing the external identifier row.
        assert methods_by_id[CORPORATE_EMAIL].method_type_code == "email"
        assert methods_by_id[CORPORATE_EMAIL].normalized_value == CORPORATE_EMAIL_NORMALIZED
        assert methods_by_id[CORPORATE_EMAIL].linked_external_identifier_id == EMAIL_IDENTIFIER
        assert methods_by_id[CORPORATE_EMAIL].is_preferred is True

        # --- the identity/channel cross-reference resolves end-to-end ------
        linked = connection.execute(
            text(
                f"SELECT xid.namespace, xid.normalized_value, xid.entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_communication_methods ecm "
                f"JOIN {SCHEMA}.entity_external_identifiers xid "
                "ON xid.identifier_id = ecm.linked_external_identifier_id "
                "AND xid.principal_id = ecm.principal_id "
                "WHERE ecm.communication_method_id = :communication_method_id"
            ),
            {"communication_method_id": CORPORATE_EMAIL},
        ).one()
        assert linked.namespace == "email"
        assert linked.normalized_value == CORPORATE_EMAIL_NORMALIZED
        assert linked.entity_id == ORG_ENTITY

        # --- the identity/channel BOUNDARY: identity resolution is answered
        # ONLY by entity_external_identifiers with namespace='email', never
        # by reading entity_communication_methods. This is the documentation-
        # through-test point: "who owns this mailbox" is answered here ----
        resolved_owner = connection.execute(
            text(
                f"SELECT entity_id FROM {SCHEMA}.entity_external_identifiers "  # noqa: S608
                "WHERE namespace = 'email' AND normalized_value = :value "
                "AND principal_id = :principal_id"
            ),
            {"value": CORPORATE_EMAIL_NORMALIZED, "principal_id": PRINCIPAL},
        ).scalar_one()
        assert resolved_owner == ORG_ENTITY

        # ...while entity_communication_methods, queried the SAME way over
        # the SAME normalized value, does NOT resolve to a single owner: it
        # returns BOTH the real organization's corporate channel AND the
        # unrelated second entity's channel, because this table records "is
        # this a way to reach someone", not "who is this". A caller that
        # mistakenly used this table to resolve identity would get an
        # ambiguous answer where entity_external_identifiers gives a single,
        # authoritative one -- which is exactly why nothing in this codebase
        # does.
        channel_holders = connection.execute(
            text(
                f"SELECT DISTINCT entity_id FROM {SCHEMA}.entity_communication_methods "  # noqa: S608
                "WHERE method_type_code = 'email' AND normalized_value = :value "
                "AND principal_id = :principal_id"
            ),
            {"value": CORPORATE_EMAIL_NORMALIZED, "principal_id": PRINCIPAL},
        ).all()
        assert {row.entity_id for row in channel_holders} == {ORG_ENTITY, OTHER_ENTITY}
        assert len(channel_holders) != 1  # ambiguous by design: not an identity table
