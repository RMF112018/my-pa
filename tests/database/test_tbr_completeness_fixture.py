"""One synthetic register, against real PostgreSQL: every difficult record has a home.

RI-ENT-WP-13. The source audit's section K walks through twelve difficult
records -- the ones a flat register collapses into a single free-text cell,
a guessed legal name, or an alias that quietly asserts something nobody
established. This module seeds ONE coherent register that contains all twelve
*structures* at once and then proves, per structure, that the campaign's
record families give each of them a typed, queryable home.

The two acceptance tests at the bottom are the point of the module. One reads
`information_schema` and proves that no table this campaign added carries a
`json`/`jsonb` column, and that the register wrote nothing into the two
pre-existing `jsonb`-bearing ledgers. The other states the exact row counts
this register produces in every record family it exercises, grouped by the
closed vocabulary each family keys on, so a dropped row reddens rather than
passing quietly. Together they are the campaign's "no fixture case needs an
opaque JSON catch-all" criterion, proven against a live server rather than
asserted in prose.

**Every organization, person, project, address, domain, phone number and
identifier below is invented.** Nothing here is drawn from, derived from, or
shaped to reproduce any real register's content: the audit's section K
describes *classes* of record the schema must represent, and this fixture
reproduces the class, never the content. Domains and mailboxes are
`example.invalid`; street addresses are obviously fabricated. Importing or
transcribing a real register is operator-reserved and is not attempted here
(`AGENTS.md` section 5, `MIGRATION-001`) -- the same discipline
`tests/database/test_entity_names_tbr_gs4_studios_fixture.py` and
`tests/database/test_entity_relationship_types_tbr_fixture.py` already apply.

**A known gap this fixture does not paper over.** The campaign's
canonicalization / import-readiness state (`ENTITY-STATE-001`) has no column
anywhere on this schema. This module does not invent one, does not stub one,
and does not smuggle it into a text or JSON field. Where the audit's record
is "held", the register records the hold where the schema actually admits it
-- on the project participation -- and
`test_a_held_participation_does_not_overload_the_entity_status` states the
missing entity-level home directly.

Writes go through raw `text()` SQL with bound parameters, exactly as the
sibling fixtures do; nothing here constructs a `Principal`, calls the service
layer, or reaches the repository. Each test reads the register back and
asserts against it, so a test can only pass on rows the seed actually wrote.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, text

SCHEMA: Final = "knowledge"

PRINCIPAL: Final = "prn_mmmm0013mmmm0013mmmm0013"

# --- Entities ---------------------------------------------------------------
#: The one project every participation in this register hangs from.
PROJECT: Final = "ent_mmmm0013aaaa0001"
#: Structure 1: the project-facing operating/brand identity.
OPERATING_BRAND: Final = "ent_mmmm0013aaaa0002"
#: Structure 1: the legal entity that owns the operating identity.
OWNING_LEGAL: Final = "ent_mmmm0013aaaa0003"
#: Structure 2: a single-purpose vehicle -- an entity, never an alias.
SPV: Final = "ent_mmmm0013aaaa0004"
#: Structures 3 and 11: the current, surviving legal identity.
CURRENT_LEGAL: Final = "ent_mmmm0013aaaa0005"
#: Structures 3 and 11: the earlier juristic predecessor.
HISTORICAL_ONE: Final = "ent_mmmm0013aaaa0006"
#: Structures 3 and 11: the later juristic predecessor.
HISTORICAL_TWO: Final = "ent_mmmm0013aaaa0007"
#: Structure 4: legal identity stays open; no legal-name string is minted.
UNRESOLVED_ORG: Final = "ent_mmmm0013aaaa0008"
#: Structure 5: the subject of a contradicted-and-superseded theory.
REVIEWER_ORG: Final = "ent_mmmm0013aaaa0009"
#: Structure 6: a professional practice.
PRACTICE_ORG: Final = "ent_mmmm0013aaaa0010"
#: Structure 6: the group that acquired and now carries that practice.
PRACTICE_PARENT: Final = "ent_mmmm0013aaaa0011"
#: Structure 7: a project-facing sales brand distinct from its legal identity.
SALES_BRAND_ORG: Final = "ent_mmmm0013aaaa0012"
#: Structure 8: contracting affiliate awaits confirmation; none is guessed.
AWAITING_ORG: Final = "ent_mmmm0013aaaa0013"
#: Structure 9: minimally canonical, held at the participation.
HOLD_ORG: Final = "ent_mmmm0013aaaa0014"
#: Structure 10: an independent consultant with no employer at all.
INDEPENDENT_PERSON: Final = "ent_mmmm0013aaaa0015"
#: Structure 12: settled corporate identity, unsettled project participation.
VERIFIED_ORG: Final = "ent_mmmm0013aaaa0016"

#: Every organization entity this register contains, and nothing else. Each
#: one exists because a structure below requires it -- no organization is
#: created merely to give a person or a foreign key something to point at.
ORGANIZATION_ENTITIES: Final = (
    OPERATING_BRAND,
    OWNING_LEGAL,
    SPV,
    CURRENT_LEGAL,
    HISTORICAL_ONE,
    HISTORICAL_TWO,
    UNRESOLVED_ORG,
    REVIEWER_ORG,
    PRACTICE_ORG,
    PRACTICE_PARENT,
    SALES_BRAND_ORG,
    AWAITING_ORG,
    HOLD_ORG,
    VERIFIED_ORG,
)

# --- Names ------------------------------------------------------------------
NAME_BRAND_OPERATING: Final = "enam_mmmm0013bbbb0001"
NAME_DISPLAY_OPERATING: Final = "enam_mmmm0013bbbb0002"
NAME_DBA_OPERATING: Final = "enam_mmmm0013bbbb0003"
NAME_LEGAL_OWNING: Final = "enam_mmmm0013bbbb0004"
NAME_LEGAL_SPV: Final = "enam_mmmm0013bbbb0005"
NAME_DISPLAY_CURRENT: Final = "enam_mmmm0013bbbb0006"
NAME_OPERATING_CURRENT: Final = "enam_mmmm0013bbbb0007"
NAME_LEGAL_CURRENT: Final = "enam_mmmm0013bbbb0008"
NAME_ACRONYM_CURRENT: Final = "enam_mmmm0013bbbb0009"
NAME_LEGAL_HISTORICAL_ONE: Final = "enam_mmmm0013bbbb0010"
NAME_LEGAL_HISTORICAL_TWO: Final = "enam_mmmm0013bbbb0011"
NAME_OPERATING_UNRESOLVED: Final = "enam_mmmm0013bbbb0012"
NAME_LEGAL_REVIEWER: Final = "enam_mmmm0013bbbb0013"
NAME_DOCUMENT_REVIEWER: Final = "enam_mmmm0013bbbb0014"
NAME_LEGAL_PRACTICE: Final = "enam_mmmm0013bbbb0015"
NAME_LEGAL_PRACTICE_PARENT: Final = "enam_mmmm0013bbbb0016"
NAME_BRAND_SALES: Final = "enam_mmmm0013bbbb0017"
NAME_LEGAL_SALES: Final = "enam_mmmm0013bbbb0018"
NAME_OPERATING_AWAITING: Final = "enam_mmmm0013bbbb0019"
NAME_DISPLAY_HOLD: Final = "enam_mmmm0013bbbb0020"
NAME_DISPLAY_PERSON: Final = "enam_mmmm0013bbbb0021"
NAME_LEGAL_VERIFIED: Final = "enam_mmmm0013bbbb0022"
NAME_DISPLAY_PROJECT: Final = "enam_mmmm0013bbbb0023"

# --- Addresses --------------------------------------------------------------
ADDRESS_PROJECT: Final = "eadr_mmmm0013cccc0001"
ADDRESS_LEGAL_PRINCIPAL: Final = "eadr_mmmm0013cccc0002"
ADDRESS_HEADQUARTERS: Final = "eadr_mmmm0013cccc0003"
ADDRESS_BUSINESS: Final = "eadr_mmmm0013cccc0004"
ADDRESS_MAILING: Final = "eadr_mmmm0013cccc0005"

# --- Communication methods --------------------------------------------------
METHOD_BRAND_EMAIL: Final = "ecmm_mmmm0013dddd0001"
METHOD_BRAND_WEBSITE: Final = "ecmm_mmmm0013dddd0002"
METHOD_SALES_PHONE: Final = "ecmm_mmmm0013dddd0003"
METHOD_CURRENT_DOMAIN: Final = "ecmm_mmmm0013dddd0004"
METHOD_AWAITING_EMAIL: Final = "ecmm_mmmm0013dddd0005"

# --- Project participations -------------------------------------------------
PARTICIPATION_BRAND: Final = "eppt_mmmm0013eeee0001"
PARTICIPATION_SPV: Final = "eppt_mmmm0013eeee0002"
PARTICIPATION_CURRENT: Final = "eppt_mmmm0013eeee0003"
PARTICIPATION_SALES: Final = "eppt_mmmm0013eeee0004"
PARTICIPATION_HOLD: Final = "eppt_mmmm0013eeee0005"
PARTICIPATION_PERSON: Final = "eppt_mmmm0013eeee0006"
PARTICIPATION_VERIFIED: Final = "eppt_mmmm0013eeee0007"
PARTICIPATION_AWAITING: Final = "eppt_mmmm0013eeee0008"

# --- Person/organization affiliation ---------------------------------------
AFFILIATION_INDEPENDENT: Final = "poaf_mmmm0013ffff0001"

# --- Relationships ----------------------------------------------------------
REL_BRAND_OF: Final = "erel_mmmm0013gggg0001"
REL_OPERATES_AS: Final = "erel_mmmm0013gggg0002"
REL_SPV_SUBSIDIARY: Final = "erel_mmmm0013gggg0003"
REL_LINEAGE_ONE: Final = "erel_mmmm0013gggg0004"
REL_LINEAGE_TWO: Final = "erel_mmmm0013gggg0005"
REL_TECHNICAL_REVIEW: Final = "erel_mmmm0013gggg0006"
REL_PRACTICE_OF: Final = "erel_mmmm0013gggg0007"
REL_PARENT_OF: Final = "erel_mmmm0013gggg0008"
REL_ACQUIRED_BY: Final = "erel_mmmm0013gggg0009"

# --- Assertions -------------------------------------------------------------
ASSERTION_UNRESOLVED_LEGAL: Final = "east_mmmm0013hhhh0001"
ASSERTION_CONTRADICTED: Final = "east_mmmm0013hhhh0002"
ASSERTION_CORRECTED: Final = "east_mmmm0013hhhh0003"
ASSERTION_AWAITING_AFFILIATE: Final = "east_mmmm0013hhhh0004"
ASSERTION_HOLD_DISCIPLINE: Final = "east_mmmm0013hhhh0005"
ASSERTION_OPEN_ROLE_BASIS: Final = "east_mmmm0013hhhh0006"
ASSERTION_NAME_VERIFIED: Final = "east_mmmm0013hhhh0007"
ASSERTION_METHOD_AWAITING: Final = "east_mmmm0013hhhh0008"
ASSERTION_AFFILIATION: Final = "east_mmmm0013hhhh0009"
ASSERTION_ADDRESS_VERIFIED: Final = "east_mmmm0013hhhh0010"

# --- Assertion evidence -----------------------------------------------------
EVIDENCE_CORRECTED: Final = "easev_mmmm0013iiii0001"
EVIDENCE_CONTRADICTED: Final = "easev_mmmm0013iiii0002"
EVIDENCE_NAME: Final = "easev_mmmm0013iiii0003"

# --- Dates ------------------------------------------------------------------
LINEAGE_ONE_FROM: Final = datetime(2004, 1, 1, tzinfo=UTC)
LINEAGE_ONE_TO: Final = datetime(2012, 6, 30, tzinfo=UTC)
LINEAGE_TWO_FROM: Final = datetime(2012, 7, 1, tzinfo=UTC)
LINEAGE_TWO_TO: Final = datetime(2019, 3, 31, tzinfo=UTC)
ACQUISITION_FROM: Final = datetime(2016, 2, 1, tzinfo=UTC)
ACQUISITION_TO: Final = datetime(2016, 9, 15, tzinfo=UTC)
AFFILIATION_FROM: Final = datetime(2021, 4, 1, tzinfo=UTC)

#: The scope text structure 7 requires the participation to carry, rather
#: than losing it into a free-text register cell.
SALES_SCOPE_TEXT: Final = (
    "Residential presale and marketing representation for the riverfront parcel"
)

#: The eleven tables this campaign created. Structure 13 proves none of them
#: carries a `json`/`jsonb` column.
CAMPAIGN_TABLES: Final = (
    "entity_names",
    "entity_organization_profiles",
    "entity_addresses",
    "entity_communication_methods",
    "entity_role_types",
    "entity_discipline_types",
    "entity_project_participations",
    "entity_person_organization_affiliations",
    "entity_relationship_types",
    "entity_assertions",
    "entity_assertion_evidence",
)

_ENTITY_ROWS: Final = (
    {
        "entity_id": PROJECT,
        "entity_type": "project",
        "canonical_name": "callowmere commons riverfront",
        "display_name": "Callowmere Commons Riverfront",
        "status": "active",
    },
    {
        "entity_id": OPERATING_BRAND,
        "entity_type": "organization",
        "canonical_name": "wrenlow studio",
        "display_name": "Wrenlow Studio",
        "status": "active",
    },
    {
        "entity_id": OWNING_LEGAL,
        "entity_type": "organization",
        "canonical_name": "wrenlow design holdings llc",
        "display_name": "Wrenlow Design Holdings, LLC",
        "status": "active",
    },
    {
        "entity_id": SPV,
        "entity_type": "organization",
        "canonical_name": "wrenlow quay development spv llc",
        "display_name": "Wrenlow Quay Development SPV, LLC",
        "status": "active",
    },
    {
        "entity_id": CURRENT_LEGAL,
        "entity_type": "organization",
        "canonical_name": "vantry group llc",
        "display_name": "Vantry Group, LLC",
        "status": "active",
    },
    {
        "entity_id": HISTORICAL_ONE,
        "entity_type": "organization",
        "canonical_name": "vantry partners incorporated",
        "display_name": "Vantry Partners Incorporated",
        "status": "historical",
    },
    {
        "entity_id": HISTORICAL_TWO,
        "entity_type": "organization",
        "canonical_name": "vantry design works limited",
        "display_name": "Vantry Design Works Limited",
        "status": "historical",
    },
    {
        "entity_id": UNRESOLVED_ORG,
        "entity_type": "organization",
        "canonical_name": "ashvenn facade consultants",
        "display_name": "Ashvenn Facade Consultants",
        "status": "active",
    },
    {
        "entity_id": REVIEWER_ORG,
        "entity_type": "organization",
        "canonical_name": "ivrenholt vale engineering pllc",
        "display_name": "Ivrenholt Vale Engineering, PLLC",
        "status": "active",
    },
    {
        "entity_id": PRACTICE_ORG,
        "entity_type": "organization",
        "canonical_name": "marnstead acoustics practice pc",
        "display_name": "Marnstead Acoustics Practice, PC",
        "status": "active",
    },
    {
        "entity_id": PRACTICE_PARENT,
        "entity_type": "organization",
        "canonical_name": "marnstead consulting group llc",
        "display_name": "Marnstead Consulting Group, LLC",
        "status": "active",
    },
    {
        "entity_id": SALES_BRAND_ORG,
        "entity_type": "organization",
        "canonical_name": "halvern riverside sales",
        "display_name": "Halvern Riverside Sales",
        "status": "active",
    },
    {
        "entity_id": AWAITING_ORG,
        "entity_type": "organization",
        "canonical_name": "cadwyth curtainwall systems",
        "display_name": "Cadwyth Curtainwall Systems",
        "status": "active",
    },
    {
        "entity_id": HOLD_ORG,
        "entity_type": "organization",
        "canonical_name": "fennimark site utilities",
        "display_name": "Fennimark Site Utilities",
        "status": "active",
    },
    {
        "entity_id": INDEPENDENT_PERSON,
        "entity_type": "person",
        "canonical_name": "marisol trevane",
        "display_name": "Marisol Trevane",
        "status": "active",
    },
    {
        "entity_id": VERIFIED_ORG,
        "entity_type": "organization",
        "canonical_name": "ordwick structural group llc",
        "display_name": "Ordwick Structural Group, LLC",
        "status": "active",
    },
)

_PROFILE_ROWS: Final = (
    {
        "entity_id": OPERATING_BRAND,
        "organization_kind_code": "brand_or_operating_unit",
        "legal_identity_status_code": "best_supported",
    },
    {
        "entity_id": OWNING_LEGAL,
        "organization_kind_code": "company",
        "legal_identity_status_code": "verified",
    },
    {
        "entity_id": SPV,
        "organization_kind_code": "llc_or_spv",
        "legal_identity_status_code": "verified",
    },
    {
        "entity_id": CURRENT_LEGAL,
        "organization_kind_code": "company",
        "legal_identity_status_code": "best_supported",
    },
    {
        "entity_id": HISTORICAL_ONE,
        "organization_kind_code": "company",
        "legal_identity_status_code": "verified",
    },
    {
        "entity_id": HISTORICAL_TWO,
        "organization_kind_code": "company",
        "legal_identity_status_code": "verified",
    },
    {
        "entity_id": UNRESOLVED_ORG,
        "organization_kind_code": "other_or_unresolved",
        "legal_identity_status_code": "unresolved",
    },
    {
        "entity_id": REVIEWER_ORG,
        "organization_kind_code": "professional_practice",
        "legal_identity_status_code": "best_supported",
    },
    {
        "entity_id": PRACTICE_ORG,
        "organization_kind_code": "professional_practice",
        "legal_identity_status_code": "verified",
    },
    {
        "entity_id": PRACTICE_PARENT,
        "organization_kind_code": "company",
        "legal_identity_status_code": "verified",
    },
    {
        "entity_id": SALES_BRAND_ORG,
        "organization_kind_code": "brand_or_operating_unit",
        "legal_identity_status_code": "best_supported",
    },
    {
        "entity_id": AWAITING_ORG,
        "organization_kind_code": "company",
        "legal_identity_status_code": "awaiting_confirmation",
    },
    {
        "entity_id": HOLD_ORG,
        "organization_kind_code": "other_or_unresolved",
        "legal_identity_status_code": "unresolved",
    },
    {
        "entity_id": VERIFIED_ORG,
        "organization_kind_code": "company",
        "legal_identity_status_code": "verified",
    },
)

_NAME_ROWS: Final = (
    {
        "entity_name_id": NAME_BRAND_OPERATING,
        "entity_id": OPERATING_BRAND,
        "name_type_code": "brand",
        "normalized_value": "wrenlow studio",
        "display_value": "Wrenlow Studio",
    },
    {
        "entity_name_id": NAME_DISPLAY_OPERATING,
        "entity_id": OPERATING_BRAND,
        "name_type_code": "display",
        "normalized_value": "wrenlow studio",
        "display_value": "Wrenlow Studio",
    },
    {
        "entity_name_id": NAME_DBA_OPERATING,
        "entity_id": OPERATING_BRAND,
        "name_type_code": "dba",
        "normalized_value": "wrenlow studio coastal",
        "display_value": "Wrenlow Studio Coastal",
    },
    {
        "entity_name_id": NAME_LEGAL_OWNING,
        "entity_id": OWNING_LEGAL,
        "name_type_code": "legal",
        "normalized_value": "wrenlow design holdings llc",
        "display_value": "Wrenlow Design Holdings, LLC",
    },
    {
        "entity_name_id": NAME_LEGAL_SPV,
        "entity_id": SPV,
        "name_type_code": "legal",
        "normalized_value": "wrenlow quay development spv llc",
        "display_value": "Wrenlow Quay Development SPV, LLC",
    },
    {
        "entity_name_id": NAME_DISPLAY_CURRENT,
        "entity_id": CURRENT_LEGAL,
        "name_type_code": "display",
        "normalized_value": "vantry group",
        "display_value": "Vantry Group",
    },
    {
        "entity_name_id": NAME_OPERATING_CURRENT,
        "entity_id": CURRENT_LEGAL,
        "name_type_code": "operating",
        "normalized_value": "vantry group",
        "display_value": "Vantry Group",
    },
    {
        "entity_name_id": NAME_LEGAL_CURRENT,
        "entity_id": CURRENT_LEGAL,
        "name_type_code": "legal",
        "normalized_value": "vantry group llc",
        "display_value": "Vantry Group, LLC",
    },
    {
        "entity_name_id": NAME_ACRONYM_CURRENT,
        "entity_id": CURRENT_LEGAL,
        "name_type_code": "acronym",
        "normalized_value": "vg",
        "display_value": "VG",
    },
    {
        "entity_name_id": NAME_LEGAL_HISTORICAL_ONE,
        "entity_id": HISTORICAL_ONE,
        "name_type_code": "legal",
        "normalized_value": "vantry partners incorporated",
        "display_value": "Vantry Partners Incorporated",
    },
    {
        "entity_name_id": NAME_LEGAL_HISTORICAL_TWO,
        "entity_id": HISTORICAL_TWO,
        "name_type_code": "legal",
        "normalized_value": "vantry design works limited",
        "display_value": "Vantry Design Works Limited",
    },
    {
        "entity_name_id": NAME_OPERATING_UNRESOLVED,
        "entity_id": UNRESOLVED_ORG,
        "name_type_code": "operating",
        "normalized_value": "ashvenn facade consultants",
        "display_value": "Ashvenn Facade Consultants",
    },
    {
        "entity_name_id": NAME_LEGAL_REVIEWER,
        "entity_id": REVIEWER_ORG,
        "name_type_code": "legal",
        "normalized_value": "ivrenholt vale engineering pllc",
        "display_value": "Ivrenholt Vale Engineering, PLLC",
    },
    {
        "entity_name_id": NAME_DOCUMENT_REVIEWER,
        "entity_id": REVIEWER_ORG,
        "name_type_code": "document_reference",
        "normalized_value": "ivrenholt vale eng",
        "display_value": "Ivrenholt Vale Eng",
    },
    {
        "entity_name_id": NAME_LEGAL_PRACTICE,
        "entity_id": PRACTICE_ORG,
        "name_type_code": "legal",
        "normalized_value": "marnstead acoustics practice pc",
        "display_value": "Marnstead Acoustics Practice, PC",
    },
    {
        "entity_name_id": NAME_LEGAL_PRACTICE_PARENT,
        "entity_id": PRACTICE_PARENT,
        "name_type_code": "legal",
        "normalized_value": "marnstead consulting group llc",
        "display_value": "Marnstead Consulting Group, LLC",
    },
    {
        "entity_name_id": NAME_BRAND_SALES,
        "entity_id": SALES_BRAND_ORG,
        "name_type_code": "brand",
        "normalized_value": "halvern riverside sales",
        "display_value": "Halvern Riverside Sales",
    },
    {
        "entity_name_id": NAME_LEGAL_SALES,
        "entity_id": SALES_BRAND_ORG,
        "name_type_code": "legal",
        "normalized_value": "halvern riverside realty llc",
        "display_value": "Halvern Riverside Realty, LLC",
    },
    {
        "entity_name_id": NAME_OPERATING_AWAITING,
        "entity_id": AWAITING_ORG,
        "name_type_code": "operating",
        "normalized_value": "cadwyth curtainwall systems",
        "display_value": "Cadwyth Curtainwall Systems",
    },
    {
        "entity_name_id": NAME_DISPLAY_HOLD,
        "entity_id": HOLD_ORG,
        "name_type_code": "display",
        "normalized_value": "fennimark site utilities",
        "display_value": "Fennimark Site Utilities",
    },
    {
        "entity_name_id": NAME_DISPLAY_PERSON,
        "entity_id": INDEPENDENT_PERSON,
        "name_type_code": "display",
        "normalized_value": "marisol trevane",
        "display_value": "Marisol Trevane",
    },
    {
        "entity_name_id": NAME_LEGAL_VERIFIED,
        "entity_id": VERIFIED_ORG,
        "name_type_code": "legal",
        "normalized_value": "ordwick structural group llc",
        "display_value": "Ordwick Structural Group, LLC",
    },
    {
        "entity_name_id": NAME_DISPLAY_PROJECT,
        "entity_id": PROJECT,
        "name_type_code": "display",
        "normalized_value": "callowmere commons riverfront",
        "display_value": "Callowmere Commons Riverfront",
    },
)

_ADDRESS_ROWS: Final = (
    {
        "entity_address_id": ADDRESS_PROJECT,
        "entity_id": OPERATING_BRAND,
        "address_type_code": "project",
        "line1": "410 Callowmere Quay Road",
        "city": "Corvane",
        "region": "ZZ",
        "raw_value": "410 Callowmere Quay Road, Corvane, ZZ",
        "normalized_address_value": "410 callowmere quay road|corvane|zz",
    },
    {
        "entity_address_id": ADDRESS_LEGAL_PRINCIPAL,
        "entity_id": OWNING_LEGAL,
        "address_type_code": "legal_principal",
        "line1": "88 Ironvale Street",
        "city": "Draymont",
        "region": "ZZ",
        "raw_value": "88 Ironvale Street, Draymont, ZZ",
        "normalized_address_value": "88 ironvale street|draymont|zz",
    },
    {
        "entity_address_id": ADDRESS_HEADQUARTERS,
        "entity_id": CURRENT_LEGAL,
        "address_type_code": "headquarters",
        "line1": "1200 Vantry Terrace",
        "city": "Draymont",
        "region": "ZZ",
        "raw_value": "1200 Vantry Terrace, Draymont, ZZ",
        "normalized_address_value": "1200 vantry terrace|draymont|zz",
    },
    {
        "entity_address_id": ADDRESS_BUSINESS,
        "entity_id": SALES_BRAND_ORG,
        "address_type_code": "business",
        "line1": "27 Halvern Parade",
        "city": "Corvane",
        "region": "ZZ",
        "raw_value": "27 Halvern Parade, Corvane, ZZ",
        "normalized_address_value": "27 halvern parade|corvane|zz",
    },
    {
        "entity_address_id": ADDRESS_MAILING,
        "entity_id": HOLD_ORG,
        "address_type_code": "mailing",
        "line1": "PO Box 4417",
        "city": "Corvane",
        "region": "ZZ",
        "raw_value": "PO Box 4417, Corvane, ZZ",
        "normalized_address_value": "po box 4417|corvane|zz",
    },
)

_METHOD_ROWS: Final = (
    {
        "communication_method_id": METHOD_BRAND_EMAIL,
        "entity_id": OPERATING_BRAND,
        "method_type_code": "email",
        "usage_context_code": "corporate",
        "normalized_value": "studio@wrenlow-design.example.invalid",
        "display_value": "studio@wrenlow-design.example.invalid",
        "verification_status_code": "best_supported",
    },
    {
        "communication_method_id": METHOD_BRAND_WEBSITE,
        "entity_id": OPERATING_BRAND,
        "method_type_code": "website",
        "usage_context_code": "corporate",
        "normalized_value": "wrenlow-design.example.invalid",
        "display_value": "https://wrenlow-design.example.invalid",
        "verification_status_code": "verified",
    },
    {
        "communication_method_id": METHOD_SALES_PHONE,
        "entity_id": SALES_BRAND_ORG,
        "method_type_code": "phone",
        "usage_context_code": "project_sales",
        "normalized_value": "15550140220",
        "display_value": "+1 (555) 014-0220",
        "verification_status_code": "unresolved",
    },
    {
        "communication_method_id": METHOD_CURRENT_DOMAIN,
        "entity_id": CURRENT_LEGAL,
        "method_type_code": "domain",
        "usage_context_code": "corporate",
        "normalized_value": "vantry-group.example.invalid",
        "display_value": "vantry-group.example.invalid",
        "verification_status_code": "verified",
    },
    {
        "communication_method_id": METHOD_AWAITING_EMAIL,
        "entity_id": AWAITING_ORG,
        "method_type_code": "email",
        "usage_context_code": "project",
        "normalized_value": "projects@cadwyth-systems.example.invalid",
        "display_value": "projects@cadwyth-systems.example.invalid",
        "verification_status_code": "awaiting_confirmation",
    },
)

_PARTICIPATION_ROWS: Final = (
    {
        "participation_id": PARTICIPATION_BRAND,
        "participant_entity_id": OPERATING_BRAND,
        "project_display_name": "Wrenlow Studio",
        "role_code": "ARCHITECT_OF_RECORD",
        "discipline_code": "ARCHITECTURE",
        "discipline_text": None,
        "scope_text": "Architect of record for the riverfront residential parcel",
        "role_basis_code": "contractual",
        "stakeholder_side_code": "design",
        "stakeholder_class_code": "core",
        "relationship_status_code": "active",
    },
    {
        "participation_id": PARTICIPATION_SPV,
        "participant_entity_id": SPV,
        "project_display_name": "Wrenlow Quay Development SPV",
        "role_code": "DEVELOPER",
        "discipline_code": None,
        "discipline_text": None,
        "scope_text": "Single-purpose development entity for the riverfront parcel",
        "role_basis_code": "contractual",
        "stakeholder_side_code": "developer",
        "stakeholder_class_code": "core",
        "relationship_status_code": "active",
    },
    {
        "participation_id": PARTICIPATION_CURRENT,
        "participant_entity_id": CURRENT_LEGAL,
        "project_display_name": "Vantry Group",
        "role_code": "CONSULTANT",
        "discipline_code": "CIVIL_ENGINEERING",
        "discipline_text": None,
        "scope_text": "Civil engineering coordination for the riverfront parcel",
        "role_basis_code": "source_verified",
        "stakeholder_side_code": "consultant",
        "stakeholder_class_code": "core",
        "relationship_status_code": "active",
    },
    {
        "participation_id": PARTICIPATION_SALES,
        "participant_entity_id": SALES_BRAND_ORG,
        "project_display_name": "Halvern Riverside Sales",
        "role_code": "SALES_AGENT",
        "discipline_code": None,
        "discipline_text": None,
        "scope_text": SALES_SCOPE_TEXT,
        "role_basis_code": "contractual",
        "stakeholder_side_code": "sales_marketing",
        "stakeholder_class_code": "transactional",
        "relationship_status_code": "active",
    },
    {
        # Structure 9: nothing is guessed. No role code, no discipline code,
        # no discipline text, no scope text -- and the participation itself
        # states the hold.
        "participation_id": PARTICIPATION_HOLD,
        "participant_entity_id": HOLD_ORG,
        "project_display_name": "Fennimark Site Utilities",
        "role_code": None,
        "discipline_code": None,
        "discipline_text": None,
        "scope_text": None,
        "role_basis_code": "unresolved",
        "stakeholder_side_code": "other",
        "stakeholder_class_code": "unresolved",
        "relationship_status_code": "on_hold",
    },
    {
        "participation_id": PARTICIPATION_PERSON,
        "participant_entity_id": INDEPENDENT_PERSON,
        "project_display_name": "Marisol Trevane",
        "role_code": "CONSULTANT",
        "discipline_code": "ARCHITECTURE",
        "discipline_text": None,
        "scope_text": "Facade review for the riverfront residential parcel",
        "role_basis_code": "project_observed",
        "stakeholder_side_code": "consultant",
        "stakeholder_class_code": "adjacent",
        "relationship_status_code": "active",
    },
    {
        # Structure 12: the corporate legal identity is settled; the basis on
        # which this participant holds this project role is not.
        "participation_id": PARTICIPATION_VERIFIED,
        "participant_entity_id": VERIFIED_ORG,
        "project_display_name": "Ordwick Structural Group",
        "role_code": "CONSULTANT",
        "discipline_code": "STRUCTURAL_ENGINEERING",
        "discipline_text": None,
        "scope_text": None,
        "role_basis_code": "unresolved",
        "stakeholder_side_code": "design",
        "stakeholder_class_code": "core",
        "relationship_status_code": "active",
    },
    {
        "participation_id": PARTICIPATION_AWAITING,
        "participant_entity_id": AWAITING_ORG,
        "project_display_name": "Cadwyth Curtainwall Systems",
        "role_code": "SUBCONTRACTOR",
        "discipline_code": None,
        "discipline_text": None,
        "scope_text": "Curtainwall supply and installation for the riverfront parcel",
        "role_basis_code": "project_observed",
        "stakeholder_side_code": "contractor",
        "stakeholder_class_code": "core",
        "relationship_status_code": "active",
    },
)

_AFFILIATION_ROWS: Final = (
    {
        # Structure 10: no organization at all, and no placeholder minted to
        # give the foreign key something to point at.
        "affiliation_id": AFFILIATION_INDEPENDENT,
        "person_entity_id": INDEPENDENT_PERSON,
        "organization_entity_id": None,
        "job_title": "Independent Facade Consultant",
        "affiliation_type_code": "independent_consultant",
        "effective_from": AFFILIATION_FROM,
        "effective_to": None,
    },
)

_RELATIONSHIP_ROWS: Final = (
    {
        "relationship_id": REL_BRAND_OF,
        "from_entity_id": OPERATING_BRAND,
        "relationship_type": "brand_of",
        "to_entity_id": OWNING_LEGAL,
        "scope_entity_id": None,
        "effective_from": None,
        "effective_to": None,
    },
    {
        "relationship_id": REL_OPERATES_AS,
        "from_entity_id": OWNING_LEGAL,
        "relationship_type": "operates_as",
        "to_entity_id": OPERATING_BRAND,
        "scope_entity_id": None,
        "effective_from": None,
        "effective_to": None,
    },
    {
        "relationship_id": REL_SPV_SUBSIDIARY,
        "from_entity_id": SPV,
        "relationship_type": "subsidiary_of",
        "to_entity_id": OWNING_LEGAL,
        "scope_entity_id": None,
        "effective_from": None,
        "effective_to": None,
    },
    {
        "relationship_id": REL_LINEAGE_ONE,
        "from_entity_id": HISTORICAL_ONE,
        "relationship_type": "historical_identity_of",
        "to_entity_id": CURRENT_LEGAL,
        "scope_entity_id": None,
        "effective_from": LINEAGE_ONE_FROM,
        "effective_to": LINEAGE_ONE_TO,
    },
    {
        "relationship_id": REL_LINEAGE_TWO,
        "from_entity_id": HISTORICAL_TWO,
        "relationship_type": "historical_identity_of",
        "to_entity_id": CURRENT_LEGAL,
        "scope_entity_id": None,
        "effective_from": LINEAGE_TWO_FROM,
        "effective_to": LINEAGE_TWO_TO,
    },
    {
        # Structure 5: a project-scoped technical review, not a corporate tie.
        "relationship_id": REL_TECHNICAL_REVIEW,
        "from_entity_id": REVIEWER_ORG,
        "relationship_type": "technical_reviewer_of",
        "to_entity_id": CURRENT_LEGAL,
        "scope_entity_id": PROJECT,
        "effective_from": None,
        "effective_to": None,
    },
    {
        "relationship_id": REL_PRACTICE_OF,
        "from_entity_id": PRACTICE_ORG,
        "relationship_type": "practice_of",
        "to_entity_id": PRACTICE_PARENT,
        "scope_entity_id": None,
        "effective_from": None,
        "effective_to": None,
    },
    {
        "relationship_id": REL_PARENT_OF,
        "from_entity_id": PRACTICE_PARENT,
        "relationship_type": "parent_of",
        "to_entity_id": PRACTICE_ORG,
        "scope_entity_id": None,
        "effective_from": None,
        "effective_to": None,
    },
    {
        # Structure 6: a dated, closed acquisition window -- timestamps, not
        # a sentence in a notes column.
        "relationship_id": REL_ACQUIRED_BY,
        "from_entity_id": PRACTICE_ORG,
        "relationship_type": "acquired_by",
        "to_entity_id": PRACTICE_PARENT,
        "scope_entity_id": None,
        "effective_from": ACQUISITION_FROM,
        "effective_to": ACQUISITION_TO,
    },
)

_EMPTY_TARGETS: Final = {
    "target_entity_name_id": None,
    "target_entity_address_id": None,
    "target_communication_method_id": None,
    "target_participation_id": None,
    "target_affiliation_id": None,
    "target_organization_profile_entity_id": None,
}

_ASSERTION_ROWS: Final = (
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_UNRESOLVED_LEGAL,
        "target_organization_profile_entity_id": UNRESOLVED_ORG,
        "predicate_code": "legal_identity_status_code",
        "assertion_status": "unresolved",
        "rationale": "No source states a registered legal name for this operating identity; "
        "the question is recorded rather than answered with a guess.",
        "asserted_by": "system_deterministic",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_CONTRADICTED,
        "target_organization_profile_entity_id": REVIEWER_ORG,
        "predicate_code": "legal_identity_status_code",
        "assertion_status": "contradicted",
        "rationale": "An earlier theory read this practice as an operating name of another "
        "firm; later evidence contradicts it.",
        "asserted_by": "review_accepted",
        "supersedes_assertion_id": None,
        "state": "superseded",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_CORRECTED,
        "target_organization_profile_entity_id": REVIEWER_ORG,
        "predicate_code": "legal_identity_status_code",
        "assertion_status": "best_supported",
        "rationale": "The practice is its own registered entity; the corrected reading "
        "replaces the contradicted one and names it.",
        "asserted_by": "review_accepted",
        "supersedes_assertion_id": ASSERTION_CONTRADICTED,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_AWAITING_AFFILIATE,
        "target_organization_profile_entity_id": AWAITING_ORG,
        "predicate_code": "contracting_entity",
        "assertion_status": "awaiting_confirmation",
        "rationale": "The contracting affiliate is not established by any source; no "
        "affiliate entity and no affiliate edge is created until it is.",
        "asserted_by": "system_deterministic",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_HOLD_DISCIPLINE,
        "target_participation_id": PARTICIPATION_HOLD,
        "predicate_code": "discipline_code",
        "assertion_status": "unresolved",
        "rationale": "Neither the discipline nor the legal identity is stated by any "
        "source; the participation is held rather than filled in.",
        "asserted_by": "system_deterministic",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_OPEN_ROLE_BASIS,
        "target_participation_id": PARTICIPATION_VERIFIED,
        "predicate_code": "role_basis_code",
        "assertion_status": "unresolved",
        "rationale": "The corporate legal identity is settled; the basis on which this "
        "participant holds this project role is not.",
        "asserted_by": "system_deterministic",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_NAME_VERIFIED,
        "target_entity_name_id": NAME_LEGAL_CURRENT,
        "predicate_code": "display_value",
        "assertion_status": "verified",
        "rationale": "The registered legal name was read back from a filing abstract and "
        "confirmed by the operator.",
        "asserted_by": "user_confirmed_assertion",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_METHOD_AWAITING,
        "target_communication_method_id": METHOD_AWAITING_EMAIL,
        "predicate_code": "verification_status_code",
        "assertion_status": "awaiting_confirmation",
        "rationale": "The project mailbox appeared once and has not been confirmed by a "
        "second source.",
        "asserted_by": "system_deterministic",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_AFFILIATION,
        "target_affiliation_id": AFFILIATION_INDEPENDENT,
        "predicate_code": "organization_entity_id",
        "assertion_status": "best_supported",
        "rationale": "This consultant works without an employing organization; the absent "
        "organization is the recorded fact, not a missing one.",
        "asserted_by": "review_accepted",
        "supersedes_assertion_id": None,
        "state": "active",
    },
    {
        **_EMPTY_TARGETS,
        "assertion_id": ASSERTION_ADDRESS_VERIFIED,
        "target_entity_address_id": ADDRESS_LEGAL_PRINCIPAL,
        "predicate_code": "address_type_code",
        "assertion_status": "verified",
        "rationale": "The legal principal address is stated by the filing abstract and is "
        "distinct from the project address.",
        "asserted_by": "user_confirmed_assertion",
        "supersedes_assertion_id": None,
        "state": "active",
    },
)

_EVIDENCE_ROWS: Final = (
    {
        "evidence_id": EVIDENCE_CORRECTED,
        "assertion_id": ASSERTION_CORRECTED,
        "entity_observation_id": None,
        "capture_span_id": None,
        "knowledge_id": "know_mmmm0013aaaa0001",
        "role": "direct",
        "source_locator": "synthetic register worksheet, corrected entry",
    },
    {
        "evidence_id": EVIDENCE_CONTRADICTED,
        "assertion_id": ASSERTION_CONTRADICTED,
        "entity_observation_id": None,
        "capture_span_id": None,
        "knowledge_id": "know_mmmm0013aaaa0002",
        "role": "counterevidence",
        "source_locator": "synthetic register worksheet, superseded entry",
    },
    {
        "evidence_id": EVIDENCE_NAME,
        "assertion_id": ASSERTION_NAME_VERIFIED,
        "entity_observation_id": None,
        "capture_span_id": "cspn_mmmm0013aaaa0001",
        "knowledge_id": None,
        "role": "supporting",
        "source_locator": "synthetic filing abstract, second page",
    },
)


def _stamped(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    """Every row of this register belongs to the one synthetic Principal."""
    return [{**row, "principal_id": PRINCIPAL} for row in rows]


@pytest.fixture
def register(migrated_engine: Engine) -> Engine:
    """The whole synthetic register, seeded once, in one transaction.

    `migrated_engine` is the shared current-head clone from `tests.db.fixtures`;
    this module does not create a catalog or invoke Alembic.

    Every test below reads this back and asserts against it; none of them
    writes. The seed order follows the foreign keys: entities, then the
    families that hang off them, then the assertions that cite those
    families' rows, then the evidence that cites the assertions.
    """
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, "
                "status) "
                "VALUES (:entity_id, :principal_id, :entity_type, :canonical_name, "
                ":display_name, :status)"
            ),
            _stamped(_ENTITY_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code, "
                "legal_identity_status_code) "
                "VALUES (:entity_id, :principal_id, :organization_kind_code, "
                ":legal_identity_status_code)"
            ),
            _stamped(_PROFILE_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, principal_id, name_type_code, "
                "normalized_value, display_value, is_preferred) "
                "VALUES (:entity_name_id, :entity_id, :principal_id, :name_type_code, "
                ":normalized_value, :display_value, true)"
            ),
            _stamped(_NAME_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_addresses "  # noqa: S608
                "(entity_address_id, entity_id, principal_id, address_type_code, line1, "
                "city, region, raw_value, normalized_address_value, is_preferred) "
                "VALUES (:entity_address_id, :entity_id, :principal_id, "
                ":address_type_code, :line1, :city, :region, :raw_value, "
                ":normalized_address_value, true)"
            ),
            _stamped(_ADDRESS_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_communication_methods "  # noqa: S608
                "(communication_method_id, entity_id, principal_id, method_type_code, "
                "usage_context_code, normalized_value, display_value, "
                "verification_status_code, is_preferred) "
                "VALUES (:communication_method_id, :entity_id, :principal_id, "
                ":method_type_code, :usage_context_code, :normalized_value, "
                ":display_value, :verification_status_code, true)"
            ),
            _stamped(_METHOD_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_project_participations "  # noqa: S608
                "(participation_id, principal_id, project_entity_id, "
                "participant_entity_id, project_display_name, role_code, discipline_code, "
                "discipline_text, scope_text, role_basis_code, stakeholder_side_code, "
                "stakeholder_class_code, relationship_status_code) "
                "VALUES (:participation_id, :principal_id, :project_entity_id, "
                ":participant_entity_id, :project_display_name, :role_code, "
                ":discipline_code, :discipline_text, :scope_text, :role_basis_code, "
                ":stakeholder_side_code, :stakeholder_class_code, "
                ":relationship_status_code)"
            ),
            [{**row, "project_entity_id": PROJECT} for row in _stamped(_PARTICIPATION_ROWS)],
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_person_organization_affiliations "  # noqa: S608
                "(affiliation_id, principal_id, person_entity_id, organization_entity_id, "
                "job_title, affiliation_type_code, effective_from, effective_to) "
                "VALUES (:affiliation_id, :principal_id, :person_entity_id, "
                ":organization_entity_id, :job_title, :affiliation_type_code, "
                ":effective_from, :effective_to)"
            ),
            _stamped(_AFFILIATION_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, principal_id, from_entity_id, relationship_type, "
                "to_entity_id, scope_entity_id, effective_from, effective_to) "
                "VALUES (:relationship_id, :principal_id, :from_entity_id, "
                ":relationship_type, :to_entity_id, :scope_entity_id, :effective_from, "
                ":effective_to)"
            ),
            _stamped(_RELATIONSHIP_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_assertions "  # noqa: S608
                "(assertion_id, principal_id, target_entity_name_id, "
                "target_entity_address_id, target_communication_method_id, "
                "target_participation_id, target_affiliation_id, "
                "target_organization_profile_entity_id, predicate_code, assertion_status, "
                "rationale, asserted_by, supersedes_assertion_id, state) "
                "VALUES (:assertion_id, :principal_id, :target_entity_name_id, "
                ":target_entity_address_id, :target_communication_method_id, "
                ":target_participation_id, :target_affiliation_id, "
                ":target_organization_profile_entity_id, :predicate_code, "
                ":assertion_status, :rationale, :asserted_by, :supersedes_assertion_id, "
                ":state)"
            ),
            _stamped(_ASSERTION_ROWS),
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_assertion_evidence "  # noqa: S608
                "(evidence_id, principal_id, assertion_id, entity_observation_id, "
                "capture_span_id, knowledge_id, role, source_locator) "
                "VALUES (:evidence_id, :principal_id, :assertion_id, "
                ":entity_observation_id, :capture_span_id, :knowledge_id, :role, "
                ":source_locator)"
            ),
            _stamped(_EVIDENCE_ROWS),
        )
    return migrated_engine


def _grouped(connection: Connection, table: str, column: str) -> dict[str, int]:
    """This Principal's row counts in one table, grouped by one column."""
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            text(
                f"SELECT {column}, count(*) FROM {SCHEMA}.{table} "  # noqa: S608
                "WHERE principal_id = :principal_id GROUP BY 1"
            ),
            {"principal_id": PRINCIPAL},
        ).all()
    }


def _scalar(connection: Connection, statement: str, **parameters: object) -> object:
    return connection.execute(text(statement), parameters).scalar_one()


@pytest.mark.database
def test_an_operating_identity_and_its_owning_legal_entity_are_separate_typed_rows(
    register: Engine,
) -> None:
    """Structure 1. The project-facing operating identity and the legal entity
    that owns it are two `entities` rows joined by structural edges, and the
    project address and the legal principal address are two typed
    `entity_addresses` rows -- never one register cell holding both."""
    with register.connect() as connection:
        addresses = connection.execute(
            text(
                f"SELECT entity_address_id, entity_id, address_type_code, "  # noqa: S608
                f"normalized_address_value FROM {SCHEMA}.entity_addresses "
                "WHERE entity_id IN (:brand, :legal) ORDER BY address_type_code"
            ),
            {"brand": OPERATING_BRAND, "legal": OWNING_LEGAL},
        ).all()

        # Two rows, of two different types, on the two different entities --
        # and two different normalized values, so neither is the other read
        # twice.
        assert [(row[0], row[1], row[2]) for row in addresses] == [
            (ADDRESS_LEGAL_PRINCIPAL, OWNING_LEGAL, "legal_principal"),
            (ADDRESS_PROJECT, OPERATING_BRAND, "project"),
        ]
        assert len({row[3] for row in addresses}) == 2

        # The two identities are joined structurally in both directions,
        # rather than one being written as the other's name.
        edges = connection.execute(
            text(
                f"SELECT from_entity_id, relationship_type, to_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_relationships "
                "WHERE from_entity_id IN (:brand, :legal) "
                "AND to_entity_id IN (:brand, :legal) ORDER BY relationship_type"
            ),
            {"brand": OPERATING_BRAND, "legal": OWNING_LEGAL},
        ).all()
        assert [tuple(row) for row in edges] == [
            (OPERATING_BRAND, "brand_of", OWNING_LEGAL),
            (OWNING_LEGAL, "operates_as", OPERATING_BRAND),
        ]

        # The legal name sits on the legal entity, the brand name on the
        # operating one; neither entity carries the other's typed name.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id AND name_type_code = 'legal'",
                entity_id=OPERATING_BRAND,
            )
            == 0
        )
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id AND name_type_code = 'brand'",
                entity_id=OWNING_LEGAL,
            )
            == 0
        )


@pytest.mark.database
def test_a_single_purpose_vehicle_is_its_own_entity_not_an_alias_of_its_parent(
    register: Engine,
) -> None:
    """Structure 2. A single-purpose vehicle is a first-class entity with its
    own organization kind, its own project participation and a structural edge
    to its parent. The failure this rules out is the register that files the
    vehicle's name as an alias on the parent, which asserts that the two are
    the same legal person when they are not."""
    with register.connect() as connection:
        kind = _scalar(
            connection,
            f"SELECT organization_kind_code FROM {SCHEMA}.entity_organization_profiles "  # noqa: S608
            "WHERE entity_id = :entity_id",
            entity_id=SPV,
        )
        assert kind == "llc_or_spv"

        participation = connection.execute(
            text(
                f"SELECT participation_id, role_code, stakeholder_side_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_project_participations "
                "WHERE participant_entity_id = :entity_id"
            ),
            {"entity_id": SPV},
        ).all()
        assert [tuple(row) for row in participation] == [
            (PARTICIPATION_SPV, "DEVELOPER", "developer")
        ]

        edge = _scalar(
            connection,
            f"SELECT relationship_type FROM {SCHEMA}.entity_relationships "  # noqa: S608
            "WHERE from_entity_id = :from_entity_id AND to_entity_id = :to_entity_id",
            from_entity_id=SPV,
            to_entity_id=OWNING_LEGAL,
        )
        assert edge == "subsidiary_of"

        # No alias row on the parent -- not one carrying the vehicle's name,
        # and not one at all. The whole register holds no alias name row.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id AND name_type_code = 'alias'",
                entity_id=OWNING_LEGAL,
            )
            == 0
        )
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE principal_id = :principal_id AND name_type_code = 'alias'",
                principal_id=PRINCIPAL,
            )
            == 0
        )

        # And the vehicle's own name is recorded on the vehicle's own row.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id "
                "AND normalized_value = 'wrenlow quay development spv llc'",
                entity_id=OWNING_LEGAL,
            )
            == 0
        )
        assert (
            _scalar(
                connection,
                f"SELECT entity_id FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_name_id = :entity_name_id",
                entity_name_id=NAME_LEGAL_SPV,
            )
            == SPV
        )


@pytest.mark.database
def test_a_current_legal_identity_and_its_historical_predecessors_are_separate_entities(
    register: Engine,
) -> None:
    """Structure 3. One current entity carries the project-facing display
    name, the typed operating name, the acronym and the current legal name as
    typed `entity_names` rows on the same `entity_id`. Each juristic
    predecessor is a separate `entities` row carrying its OWN legal name, and
    the survivor carries no `historical_name` row standing in for either of
    them."""
    with register.connect() as connection:
        # The lineage family is exactly the survivor plus the predecessors
        # that name it -- three entities, derived from the edges rather than
        # from a literal list.
        lineage = connection.execute(
            text(
                f"SELECT from_entity_id FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE to_entity_id = :entity_id "
                "AND relationship_type = 'historical_identity_of'"
            ),
            {"entity_id": CURRENT_LEGAL},
        ).all()
        assert {row[0] for row in lineage} | {CURRENT_LEGAL} == {
            CURRENT_LEGAL,
            HISTORICAL_ONE,
            HISTORICAL_TWO,
        }

        current_names = connection.execute(
            text(
                f"SELECT name_type_code, display_value FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id ORDER BY name_type_code"
            ),
            {"entity_id": CURRENT_LEGAL},
        ).all()
        assert {(row[0], row[1]) for row in current_names} == {
            ("acronym", "VG"),
            ("display", "Vantry Group"),
            ("legal", "Vantry Group, LLC"),
            ("operating", "Vantry Group"),
        }

        # Each predecessor's legal name is a LEGAL row on its own entity_id.
        predecessor_names = connection.execute(
            text(
                f"SELECT entity_id, name_type_code, display_value "  # noqa: S608
                f"FROM {SCHEMA}.entity_names WHERE entity_id IN (:one, :two) "
                "ORDER BY entity_id"
            ),
            {"one": HISTORICAL_ONE, "two": HISTORICAL_TWO},
        ).all()
        assert [tuple(row) for row in predecessor_names] == [
            (HISTORICAL_ONE, "legal", "Vantry Partners Incorporated"),
            (HISTORICAL_TWO, "legal", "Vantry Design Works Limited"),
        ]

        # The collapse this rules out: a historical_name row on the survivor
        # standing in for a predecessor that should have been its own entity.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE principal_id = :principal_id AND name_type_code = 'historical_name'",
                principal_id=PRINCIPAL,
            )
            == 0
        )


@pytest.mark.database
def test_an_unresolved_legal_identity_records_no_fabricated_legal_name(
    register: Engine,
) -> None:
    """Structure 4. An organization whose legal identity nobody has
    established keeps `legal_identity_status_code = unresolved` and NO `legal`
    name row at all. The open question is recorded as an `entity_assertions`
    row against the organization profile, so the absence is a stated fact with
    a retrieval path rather than a blank a later reader fills in."""
    with register.connect() as connection:
        assert (
            _scalar(
                connection,
                f"SELECT legal_identity_status_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_organization_profiles WHERE entity_id = :entity_id",
                entity_id=UNRESOLVED_ORG,
            )
            == "unresolved"
        )

        # The load-bearing zero: no legal-name string was invented.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id AND name_type_code = 'legal'",
                entity_id=UNRESOLVED_ORG,
            )
            == 0
        )

        # What the entity does carry is the operating name a source actually
        # stated, and nothing else.
        assert [
            tuple(row)
            for row in connection.execute(
                text(
                    f"SELECT name_type_code, display_value FROM {SCHEMA}.entity_names "  # noqa: S608
                    "WHERE entity_id = :entity_id"
                ),
                {"entity_id": UNRESOLVED_ORG},
            ).all()
        ] == [("operating", "Ashvenn Facade Consultants")]

        open_question = connection.execute(
            text(
                f"SELECT assertion_status, predicate_code, asserted_by, state "  # noqa: S608
                f"FROM {SCHEMA}.entity_assertions "
                "WHERE target_organization_profile_entity_id = :entity_id"
            ),
            {"entity_id": UNRESOLVED_ORG},
        ).all()
        assert [tuple(row) for row in open_question] == [
            ("unresolved", "legal_identity_status_code", "system_deterministic", "active")
        ]


@pytest.mark.database
def test_a_contradicted_theory_is_superseded_rather_than_stored_as_an_alias(
    register: Engine,
) -> None:
    """Structure 5. A prior identity theory that later evidence contradicts
    lives on as a `contradicted`/`superseded` assertion, with the corrected
    assertion pointing backward at it -- never as an `alias` name row, which
    would silently read as true. The same organization's project-scoped
    technical review is an `entity_relationships` row whose `scope_entity_id`
    names the project, so it is a review on one project rather than a standing
    corporate affiliation."""
    with register.connect() as connection:
        theories = connection.execute(
            text(
                f"SELECT assertion_id, assertion_status, state, supersedes_assertion_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_assertions "
                "WHERE target_organization_profile_entity_id = :entity_id "
                "ORDER BY assertion_id"
            ),
            {"entity_id": REVIEWER_ORG},
        ).all()
        assert [tuple(row) for row in theories] == [
            (ASSERTION_CONTRADICTED, "contradicted", "superseded", None),
            (ASSERTION_CORRECTED, "best_supported", "active", ASSERTION_CONTRADICTED),
        ]

        # The prior theory was never written as a name anybody could read as
        # a fact.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id AND name_type_code = 'alias'",
                entity_id=REVIEWER_ORG,
            )
            == 0
        )

        # Both readings keep their evidence, including the counterevidence
        # that overturned the first one.
        evidence = connection.execute(
            text(
                f"SELECT assertion_id, role FROM {SCHEMA}.entity_assertion_evidence "  # noqa: S608
                "WHERE assertion_id IN (:prior, :corrected) ORDER BY assertion_id"
            ),
            {"prior": ASSERTION_CONTRADICTED, "corrected": ASSERTION_CORRECTED},
        ).all()
        assert [tuple(row) for row in evidence] == [
            (ASSERTION_CONTRADICTED, "counterevidence"),
            (ASSERTION_CORRECTED, "direct"),
        ]

        review = connection.execute(
            text(
                f"SELECT relationship_type, scope_entity_id, to_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_relationships "
                "WHERE relationship_id = :relationship_id"
            ),
            {"relationship_id": REL_TECHNICAL_REVIEW},
        ).one()
        assert tuple(review) == ("technical_reviewer_of", PROJECT, CURRENT_LEGAL)


@pytest.mark.database
def test_two_connected_practices_carry_a_time_bounded_acquisition(
    register: Engine,
) -> None:
    """Structure 6. A professional practice and the group that carries it are
    connected by `practice_of` and `parent_of`, and the acquisition that
    produced that arrangement is an `acquired_by` edge with a real, closed
    window. The window is two `timestamptz` values a reader can compare and
    filter, not a sentence in a notes column."""
    with register.connect() as connection:
        structure = connection.execute(
            text(
                f"SELECT relationship_type, from_entity_id, to_entity_id "  # noqa: S608
                f"FROM {SCHEMA}.entity_relationships "
                "WHERE relationship_type IN ('practice_of', 'parent_of') "
                "ORDER BY relationship_type"
            )
        ).all()
        assert [tuple(row) for row in structure] == [
            ("parent_of", PRACTICE_PARENT, PRACTICE_ORG),
            ("practice_of", PRACTICE_ORG, PRACTICE_PARENT),
        ]

        acquisition = connection.execute(
            text(
                f"SELECT effective_from, effective_to FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE relationship_id = :relationship_id"
            ),
            {"relationship_id": REL_ACQUIRED_BY},
        ).one()
        assert isinstance(acquisition[0], datetime)
        assert isinstance(acquisition[1], datetime)
        assert acquisition[0] == ACQUISITION_FROM
        assert acquisition[1] == ACQUISITION_TO
        assert acquisition[0] < acquisition[1]


@pytest.mark.database
def test_a_project_facing_brand_and_its_legal_name_are_separate_typed_rows(
    register: Engine,
) -> None:
    """Structure 7. The name a party is known by on the project and the name
    it is registered under are separate typed `entity_names` rows on one
    entity, and what that party was engaged to do is
    `entity_project_participations.scope_text` -- a project-scoped column,
    reachable without parsing a description of the party."""
    with register.connect() as connection:
        names = connection.execute(
            text(
                f"SELECT entity_name_id, name_type_code, display_value "  # noqa: S608
                f"FROM {SCHEMA}.entity_names WHERE entity_id = :entity_id "
                "ORDER BY name_type_code"
            ),
            {"entity_id": SALES_BRAND_ORG},
        ).all()
        assert [tuple(row) for row in names] == [
            (NAME_BRAND_SALES, "brand", "Halvern Riverside Sales"),
            (NAME_LEGAL_SALES, "legal", "Halvern Riverside Realty, LLC"),
        ]

        participation = connection.execute(
            text(
                f"SELECT scope_text, project_display_name, role_code, "  # noqa: S608
                f"stakeholder_side_code FROM {SCHEMA}.entity_project_participations "
                "WHERE participation_id = :participation_id"
            ),
            {"participation_id": PARTICIPATION_SALES},
        ).one()
        assert participation[0] == SALES_SCOPE_TEXT
        # The project-scoped display name is the brand, and it lives on the
        # participation rather than overwriting the entity's own identity.
        assert participation[1] == "Halvern Riverside Sales"
        assert (participation[2], participation[3]) == ("SALES_AGENT", "sales_marketing")
        assert (
            _scalar(
                connection,
                f"SELECT display_name FROM {SCHEMA}.entities WHERE entity_id = :entity_id",  # noqa: S608
                entity_id=SALES_BRAND_ORG,
            )
            == "Halvern Riverside Sales"
        )


@pytest.mark.database
def test_an_unresolved_contracting_affiliate_is_recorded_without_a_guessed_edge(
    register: Engine,
) -> None:
    """Structure 8. A project-facing party whose contracting affiliate nobody
    has established keeps `legal_identity_status_code = awaiting_confirmation`
    and an `awaiting_confirmation` assertion naming the open question. No
    affiliate entity is minted and no `contracting_entity_for` edge is drawn,
    because drawing one would assert a corporate relationship the register
    never established."""
    with register.connect() as connection:
        assert (
            _scalar(
                connection,
                f"SELECT legal_identity_status_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_organization_profiles WHERE entity_id = :entity_id",
                entity_id=AWAITING_ORG,
            )
            == "awaiting_confirmation"
        )

        open_question = connection.execute(
            text(
                f"SELECT assertion_status, predicate_code FROM {SCHEMA}.entity_assertions "  # noqa: S608
                "WHERE target_organization_profile_entity_id = :entity_id"
            ),
            {"entity_id": AWAITING_ORG},
        ).all()
        assert [tuple(row) for row in open_question] == [
            ("awaiting_confirmation", "contracting_entity")
        ]

        # No guessed affiliate: not from this entity, and nowhere in the
        # register.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE from_entity_id = :entity_id "
                "AND relationship_type = 'contracting_entity_for'",
                entity_id=AWAITING_ORG,
            )
            == 0
        )
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE principal_id = :principal_id "
                "AND relationship_type = 'contracting_entity_for'",
                principal_id=PRINCIPAL,
            )
            == 0
        )

        # The party is still fully project-facing: it participates, and it
        # carries a typed operating name and a contact channel.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE participant_entity_id = :entity_id",
                entity_id=AWAITING_ORG,
            )
            == 1
        )


@pytest.mark.database
def test_a_held_participation_does_not_overload_the_entity_status(
    register: Engine,
) -> None:
    """Structure 9. A minimally canonical party is held at the project
    participation (`relationship_status_code = on_hold`) with its legal
    identity unresolved and NO guessed discipline -- both `discipline_code`
    and `discipline_text` stay null rather than acquiring a plausible-looking
    taxonomy value, and the open question is recorded as an assertion against
    the participation.

    **A known gap, owned by `ENTITY-STATE-001`.** The campaign's
    canonicalization / import-readiness state has no column anywhere on this
    schema, at the entity level or elsewhere. This module does not invent one,
    does not add one, and does not smuggle it into a text or JSON field. What
    it asserts instead is the design rule RI-ENT-WP-01 actually recorded: the
    hold is NOT overloaded onto `entities.status`, which is a lifecycle
    vocabulary about the entity record and not a judgement about whether the
    record is ready to import. `entities.status` therefore stays `active`
    while the participation carries the hold, and the entity-level home for
    that judgement remains unbuilt.
    """
    with register.connect() as connection:
        held = connection.execute(
            text(
                f"SELECT relationship_status_code, role_code, discipline_code, "  # noqa: S608
                f"discipline_text, role_basis_code, stakeholder_class_code, state "
                f"FROM {SCHEMA}.entity_project_participations "
                "WHERE participation_id = :participation_id"
            ),
            {"participation_id": PARTICIPATION_HOLD},
        ).one()
        assert held[0] == "on_hold"
        # Nothing guessed: no role code, no discipline code, no discipline
        # free text standing in for one.
        assert held[1] is None
        assert held[2] is None
        assert held[3] is None
        assert held[4] == "unresolved"
        assert held[5] == "unresolved"
        # The record's own lifecycle is untouched by the hold.
        assert held[6] == "active"

        assert (
            _scalar(
                connection,
                f"SELECT legal_identity_status_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_organization_profiles WHERE entity_id = :entity_id",
                entity_id=HOLD_ORG,
            )
            == "unresolved"
        )

        # The design rule: the hold lives on the participation, and the
        # entity's own status is not overloaded to carry it.
        assert (
            _scalar(
                connection,
                f"SELECT status FROM {SCHEMA}.entities WHERE entity_id = :entity_id",  # noqa: S608
                entity_id=HOLD_ORG,
            )
            == "active"
        )

        open_question = connection.execute(
            text(
                f"SELECT assertion_status, predicate_code FROM {SCHEMA}.entity_assertions "  # noqa: S608
                "WHERE target_participation_id = :participation_id"
            ),
            {"participation_id": PARTICIPATION_HOLD},
        ).all()
        assert [tuple(row) for row in open_question] == [("unresolved", "discipline_code")]


@pytest.mark.database
def test_a_person_participates_directly_without_a_placeholder_organization(
    register: Engine,
) -> None:
    """Structure 10. An independent consultant participates in the project
    directly, and the affiliation that says so carries a NULL
    `organization_entity_id` with
    `affiliation_type_code = independent_consultant`. No organization is
    created to give that foreign key something to point at: the register's
    organization set is exactly the organizations the other structures
    require, and every one of them is named by another structure."""
    with register.connect() as connection:
        participation = connection.execute(
            text(
                f"SELECT project_entity_id, role_code, stakeholder_side_code, "  # noqa: S608
                f"relationship_status_code FROM {SCHEMA}.entity_project_participations "
                "WHERE participant_entity_id = :entity_id"
            ),
            {"entity_id": INDEPENDENT_PERSON},
        ).all()
        assert [tuple(row) for row in participation] == [
            (PROJECT, "CONSULTANT", "consultant", "active")
        ]

        affiliation = connection.execute(
            text(
                f"SELECT organization_entity_id, affiliation_type_code, job_title, "  # noqa: S608
                f"effective_to, state "
                f"FROM {SCHEMA}.entity_person_organization_affiliations "
                "WHERE person_entity_id = :entity_id"
            ),
            {"entity_id": INDEPENDENT_PERSON},
        ).all()
        assert [tuple(row) for row in affiliation] == [
            (None, "independent_consultant", "Independent Facade Consultant", None, "active")
        ]

        # No placeholder: the organization set is exactly the set the other
        # structures require, and nothing in this register affiliates a
        # person to an organization at all.
        organizations = connection.execute(
            text(
                f"SELECT entity_id FROM {SCHEMA}.entities "  # noqa: S608
                "WHERE principal_id = :principal_id AND entity_type = 'organization'"
            ),
            {"principal_id": PRINCIPAL},
        ).all()
        assert {row[0] for row in organizations} == set(ORGANIZATION_ENTITIES)
        assert len(organizations) == len(ORGANIZATION_ENTITIES)

        assert (
            _scalar(
                connection,
                f"SELECT count(*) "  # noqa: S608
                f"FROM {SCHEMA}.entity_person_organization_affiliations "
                "WHERE principal_id = :principal_id AND organization_entity_id IS NOT NULL",
                principal_id=PRINCIPAL,
            )
            == 0
        )


@pytest.mark.database
def test_a_current_identity_stays_active_while_its_lineage_is_historical(
    register: Engine,
) -> None:
    """Structure 11. The current operating identity's own `status` stays
    `active` even though `historical_identity_of` edges point at entities
    whose `status` is `historical`, and each of those edges carries the
    `effective_from`/`effective_to` window the predecessor was current in.
    A predecessor's lifecycle does not leak onto its successor."""
    with register.connect() as connection:
        statuses = dict(
            connection.execute(
                text(
                    f"SELECT entity_id, status FROM {SCHEMA}.entities "  # noqa: S608
                    "WHERE entity_id IN (:current, :one, :two)"
                ),
                {"current": CURRENT_LEGAL, "one": HISTORICAL_ONE, "two": HISTORICAL_TWO},
            ).all()
        )
        assert statuses == {
            CURRENT_LEGAL: "active",
            HISTORICAL_ONE: "historical",
            HISTORICAL_TWO: "historical",
        }

        lineage = connection.execute(
            text(
                f"SELECT relationship_id, from_entity_id, effective_from, effective_to "  # noqa: S608
                f"FROM {SCHEMA}.entity_relationships "
                "WHERE to_entity_id = :entity_id "
                "AND relationship_type = 'historical_identity_of' "
                "ORDER BY effective_from"
            ),
            {"entity_id": CURRENT_LEGAL},
        ).all()
        assert [tuple(row) for row in lineage] == [
            (REL_LINEAGE_ONE, HISTORICAL_ONE, LINEAGE_ONE_FROM, LINEAGE_ONE_TO),
            (REL_LINEAGE_TWO, HISTORICAL_TWO, LINEAGE_TWO_FROM, LINEAGE_TWO_TO),
        ]
        for row in lineage:
            assert isinstance(row[2], datetime)
            assert isinstance(row[3], datetime)


@pytest.mark.database
def test_a_settled_legal_identity_coexists_with_an_open_participation_question(
    register: Engine,
) -> None:
    """Structure 12. Corporate identity and project participation are two
    dimensions, not one graded thing. The organization profile says
    `legal_identity_status_code = verified` while the participation's
    `role_basis_code` is `unresolved` and an assertion targeting THAT
    PARTICIPATION says `unresolved` -- three different columns on three
    different rows, so settling one never implies the other."""
    with register.connect() as connection:
        assert (
            _scalar(
                connection,
                f"SELECT legal_identity_status_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_organization_profiles WHERE entity_id = :entity_id",
                entity_id=VERIFIED_ORG,
            )
            == "verified"
        )

        participation = connection.execute(
            text(
                f"SELECT role_basis_code, relationship_status_code "  # noqa: S608
                f"FROM {SCHEMA}.entity_project_participations "
                "WHERE participation_id = :participation_id"
            ),
            {"participation_id": PARTICIPATION_VERIFIED},
        ).one()
        assert participation[0] == "unresolved"
        assert participation[1] == "active"

        open_question = connection.execute(
            text(
                f"SELECT assertion_id, assertion_status, predicate_code, "  # noqa: S608
                f"target_participation_id, target_organization_profile_entity_id "
                f"FROM {SCHEMA}.entity_assertions "
                "WHERE target_participation_id = :participation_id"
            ),
            {"participation_id": PARTICIPATION_VERIFIED},
        ).all()
        assert [tuple(row) for row in open_question] == [
            (
                ASSERTION_OPEN_ROLE_BASIS,
                "unresolved",
                "role_basis_code",
                PARTICIPATION_VERIFIED,
                None,
            )
        ]

        # The open question is about the participation, so no assertion
        # reopens the settled corporate identity by targeting its profile.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_assertions "  # noqa: S608
                "WHERE target_organization_profile_entity_id = :entity_id",
                entity_id=VERIFIED_ORG,
            )
            == 0
        )


@pytest.mark.database
def test_no_record_family_this_campaign_added_carries_an_opaque_json_column(
    register: Engine,
) -> None:
    """Acceptance. None of the tables this campaign created has a `json` or
    `jsonb` column, so no case above could have been stored as an opaque blob
    even if a writer wanted to -- and the register wrote nothing into the two
    pre-existing `jsonb`-bearing ledgers either. This is the "no fixture case
    needs an opaque JSON catch-all" criterion, read off the live catalog
    rather than asserted in prose."""
    with register.connect() as connection:
        present = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT DISTINCT table_name FROM information_schema.columns "
                    "WHERE table_schema = :schema"
                ),
                {"schema": SCHEMA},
            ).all()
        }
        # If a table name here were misspelled the JSON scan below would pass
        # vacuously, so the names are resolved against the catalog first.
        assert set(CAMPAIGN_TABLES) <= present

        json_columns = connection.execute(
            text(
                "SELECT table_name, column_name, data_type "
                "FROM information_schema.columns "
                "WHERE table_schema = :schema AND data_type IN ('json', 'jsonb') "
                "ORDER BY table_name, column_name"
            ),
            {"schema": SCHEMA},
        ).all()
        assert [row for row in json_columns if row[0] in CAMPAIGN_TABLES] == []

        # And nothing was smuggled into the pre-existing jsonb-bearing
        # ledgers: this Principal owns no row in either of them.
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_mutation_events "  # noqa: S608
                "WHERE principal_id = :principal_id",
                principal_id=PRINCIPAL,
            )
            == 0
        )
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_resolution_decisions "  # noqa: S608
                "WHERE principal_id = :principal_id",
                principal_id=PRINCIPAL,
            )
            == 0
        )


@pytest.mark.database
def test_every_material_element_of_the_register_has_a_structured_retrieval_path(
    register: Engine,
) -> None:
    """Acceptance, and the strongest test here. Every material element of the
    register is reachable by a typed query over a closed vocabulary, and the
    exact expected counts are stated per vocabulary member so that a dropped
    row, a mistyped code or a silently widened seed reddens rather than
    passing. Nothing is asserted as merely non-zero."""
    with register.connect() as connection:
        assert _grouped(connection, "entities", "entity_type") == {
            "project": 1,
            "organization": 14,
            "person": 1,
        }

        assert _grouped(connection, "entity_names", "name_type_code") == {
            "acronym": 1,
            "brand": 2,
            "dba": 1,
            "display": 5,
            "document_reference": 1,
            "legal": 10,
            "operating": 3,
        }

        assert _grouped(connection, "entity_addresses", "address_type_code") == {
            "business": 1,
            "headquarters": 1,
            "legal_principal": 1,
            "mailing": 1,
            "project": 1,
        }

        assert _grouped(connection, "entity_communication_methods", "method_type_code") == {
            "domain": 1,
            "email": 2,
            "phone": 1,
            "website": 1,
        }
        assert _grouped(connection, "entity_communication_methods", "verification_status_code") == {
            "awaiting_confirmation": 1,
            "best_supported": 1,
            "unresolved": 1,
            "verified": 2,
        }

        assert _grouped(
            connection, "entity_project_participations", "relationship_status_code"
        ) == {"active": 7, "on_hold": 1}
        assert (
            _scalar(
                connection,
                f"SELECT count(*) FROM {SCHEMA}.entity_project_participations "  # noqa: S608
                "WHERE principal_id = :principal_id",
                principal_id=PRINCIPAL,
            )
            == 8
        )

        assert _grouped(
            connection, "entity_person_organization_affiliations", "affiliation_type_code"
        ) == {"independent_consultant": 1}

        assert _grouped(
            connection, "entity_organization_profiles", "legal_identity_status_code"
        ) == {
            "awaiting_confirmation": 1,
            "best_supported": 4,
            "unresolved": 2,
            "verified": 7,
        }

        assert _grouped(connection, "entity_assertions", "assertion_status") == {
            "awaiting_confirmation": 2,
            "best_supported": 2,
            "contradicted": 1,
            "unresolved": 3,
            "verified": 2,
        }

        assert _grouped(connection, "entity_relationships", "relationship_type") == {
            "acquired_by": 1,
            "brand_of": 1,
            "historical_identity_of": 2,
            "operates_as": 1,
            "parent_of": 1,
            "practice_of": 1,
            "subsidiary_of": 1,
            "technical_reviewer_of": 1,
        }

        assert _grouped(connection, "entity_assertion_evidence", "role") == {
            "counterevidence": 1,
            "direct": 1,
            "supporting": 1,
        }

        # Every one of the six record families an assertion may bind to is
        # actually bound to by this register -- the provenance path reaches
        # all six, not a convenient subset.
        targets = connection.execute(
            text(
                f"SELECT count(target_entity_name_id), "  # noqa: S608
                f"count(target_entity_address_id), "
                f"count(target_communication_method_id), "
                f"count(target_participation_id), count(target_affiliation_id), "
                f"count(target_organization_profile_entity_id) "
                f"FROM {SCHEMA}.entity_assertions WHERE principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL},
        ).one()
        assert tuple(targets) == (1, 1, 1, 2, 1, 4)
