"""The GS4 Studios / Garcia Stromberg Holdings case, synthetic, against real PostgreSQL.

RI-ENT-WP-02, `TEST-001`. The source audit's twelve difficult-record
walkthroughs (its section K) include this one as the canonical proof that a
current best-supported legal identity and a historical juristic predecessor
coexist as **two distinct `entities` rows**, connected structurally, rather
than being collapsed into one entity's alias history or minted as unrelated
duplicates.

**Every name and identifier below is synthetic.** Nothing here is drawn from,
derived from, or shaped to reproduce any real TBR register content; the case
pattern (a project-facing brand name, a current best-supported legal entity,
and a historical predecessor entity) is the audit's own description of a
*class* of record the schema must represent, not an import of real data
(`MIGRATION-001`, `AGENTS.md` section 5).

**What this fixture proves:**

1. one entity carries the project-facing/brand identity and its current
   best-supported legal name, as `entity_names` rows of different
   `name_type_code`s on the *same* `entity_id`;
2. that entity's `entity_organization_profiles` row states
   `legal_identity_status_code = best_supported`, never a numeric confidence
   (RULING 1);
3. the historical predecessor is a **separate** `entities` row
   (`EntityStatus.HISTORICAL`), with its own legal name recorded as *its own*
   `LEGAL` name — not as a `HISTORICAL_NAME` row on the surviving entity,
   which is the exact collapse the audit warns against;
4. the two entities are connected by a structural edge a reader can follow,
   using the existing `AFFILIATED_WITH` relationship type as a **documented
   placeholder** — the audit calls for a dedicated `historical_identity_of`/
   `acquired_by` lineage edge, and `EntityRelationshipType` is frozen at
   fifteen members this increment does not widen (RI-ENT-WP-06 owns that);
5. exactly two entities exist for this case — never four, never one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_entity_names_gs4_fixture_test"

PRINCIPAL: Final = "prn_ffff0009ffff0009ffff0009"

#: The current, surviving entity: synthetic "GS4 Studios" analogue.
CURRENT_ENTITY: Final = "ent_ffff0009ffff0009"
#: The historical predecessor: synthetic "Garcia Stromberg Holdings" analogue.
HISTORICAL_ENTITY: Final = "ent_gggg0010gggg0010"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.mark.database
def test_a_current_legal_entity_and_its_historical_predecessor_coexist(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        # --- two entities, not one, not four -------------------------------
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, 'organization', :canonical, :display, 'active')"
            ),
            {
                "entity_id": CURRENT_ENTITY,
                "principal_id": PRINCIPAL,
                "canonical": "synthetic studio four",
                "display": "Synthetic Studio Four",
            },
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, 'organization', :canonical, :display, "
                "'historical')"
            ),
            {
                "entity_id": HISTORICAL_ENTITY,
                "principal_id": PRINCIPAL,
                "canonical": "synthetic predecessor holdings",
                "display": "Synthetic Predecessor Holdings",
            },
        )

        # --- typed names on the CURRENT entity: brand, operating, legal ----
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, is_preferred) VALUES "
                "('enam_ffff0009aaaa0001', :entity_id, 'brand', "
                "'synthetic studio four', 'Synthetic Studio Four', :principal_id, true)"
            ),
            {"entity_id": CURRENT_ENTITY, "principal_id": PRINCIPAL},
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, is_preferred) VALUES "
                "('enam_ffff0009aaaa0002', :entity_id, 'legal', "
                "'synthetic studio four llc', 'Synthetic Studio Four, LLC', :principal_id, true)"
            ),
            {"entity_id": CURRENT_ENTITY, "principal_id": PRINCIPAL},
        )

        # --- the historical entity's OWN legal name -- a LEGAL row on ITS
        # OWN entity_id, never a HISTORICAL_NAME row on the surviving one ---
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_names "  # noqa: S608
                "(entity_name_id, entity_id, name_type_code, normalized_value, "
                "display_value, principal_id, is_preferred) VALUES "
                "('enam_gggg0010bbbb0001', :entity_id, 'legal', "
                "'synthetic predecessor holdings llc', "
                "'Synthetic Predecessor Holdings, LLC', :principal_id, true)"
            ),
            {"entity_id": HISTORICAL_ENTITY, "principal_id": PRINCIPAL},
        )

        # --- organization profiles: current is best-supported, historical
        # is verified (it is a matter of closed record, not an open question) -
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code, "
                "legal_identity_status_code) VALUES "
                "(:entity_id, :principal_id, 'llc_or_spv', 'best_supported')"
            ),
            {"entity_id": CURRENT_ENTITY, "principal_id": PRINCIPAL},
        )
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_organization_profiles "  # noqa: S608
                "(entity_id, principal_id, organization_kind_code, "
                "legal_identity_status_code) VALUES "
                "(:entity_id, :principal_id, 'llc_or_spv', 'verified')"
            ),
            {"entity_id": HISTORICAL_ENTITY, "principal_id": PRINCIPAL},
        )

        # --- the structural link: AFFILIATED_WITH as a documented placeholder
        # for the dedicated lineage edge RI-ENT-WP-06 has not yet added -----
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                "principal_id) VALUES "
                "('erel_ffff0009cccc0001', :from_entity_id, 'affiliated_with', "
                ":to_entity_id, :principal_id)"
            ),
            {
                "from_entity_id": CURRENT_ENTITY,
                "to_entity_id": HISTORICAL_ENTITY,
                "principal_id": PRINCIPAL,
            },
        )

    with migrated_engine.connect() as connection:
        # Exactly two entities for this case -- never one (a collapsed
        # rename) and never four (unrelated duplicates the audit warns
        # against in its search/resolution section).
        entity_count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities WHERE principal_id = :principal_id"  # noqa: S608
            ),
            {"principal_id": PRINCIPAL},
        ).scalar_one()
        assert entity_count == 2

        # The current entity's names: brand and legal, both preferred, both
        # on the same entity_id.
        current_names = connection.execute(
            text(
                f"SELECT name_type_code, display_value FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id ORDER BY name_type_code"
            ),
            {"entity_id": CURRENT_ENTITY},
        ).all()
        assert {(row[0], row[1]) for row in current_names} == {
            ("brand", "Synthetic Studio Four"),
            ("legal", "Synthetic Studio Four, LLC"),
        }

        # The historical entity's own legal name is on ITS OWN entity_id --
        # not folded into the current entity as a historical_name row.
        historical_names = connection.execute(
            text(
                f"SELECT name_type_code, display_value FROM {SCHEMA}.entity_names "  # noqa: S608
                "WHERE entity_id = :entity_id"
            ),
            {"entity_id": HISTORICAL_ENTITY},
        ).all()
        assert [tuple(row) for row in historical_names] == [
            ("legal", "Synthetic Predecessor Holdings, LLC")
        ]
        assert not any(row[0] == "historical_name" for row in current_names)

        # Legal identity status: never a numeric confidence (RULING 1),
        # a closed, evidence-anchored status per entity.
        statuses = dict(
            connection.execute(
                text(
                    f"SELECT entity_id, legal_identity_status_code "  # noqa: S608
                    f"FROM {SCHEMA}.entity_organization_profiles "
                    "WHERE principal_id = :principal_id"
                ),
                {"principal_id": PRINCIPAL},
            ).all()
        )
        assert statuses[CURRENT_ENTITY] == "best_supported"
        assert statuses[HISTORICAL_ENTITY] == "verified"

        # The structural link is present and directed current -> historical.
        edge = connection.execute(
            text(
                f"SELECT relationship_type FROM {SCHEMA}.entity_relationships "  # noqa: S608
                "WHERE from_entity_id = :from_entity_id AND to_entity_id = :to_entity_id"
            ),
            {"from_entity_id": CURRENT_ENTITY, "to_entity_id": HISTORICAL_ENTITY},
        ).scalar_one()
        assert edge == "affiliated_with"

        # The historical entity's own lifecycle status says it is historical
        # -- it does not claim to be current, and the survivor's status is
        # unaffected by its predecessor's.
        entity_statuses = dict(
            connection.execute(
                text(
                    f"SELECT entity_id, status FROM {SCHEMA}.entities "  # noqa: S608
                    "WHERE principal_id = :principal_id"
                ),
                {"principal_id": PRINCIPAL},
            ).all()
        )
        assert entity_statuses[CURRENT_ENTITY] == "active"
        assert entity_statuses[HISTORICAL_ENTITY] == "historical"
