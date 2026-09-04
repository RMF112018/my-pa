"""Synthetic TBR-shaped corporate lineage, against real PostgreSQL (RI-ENT-WP-06a).

Closes `ENTITY-REL-001`. The source audit's Record Element Inventory and its
section L ("Relationship graph proof") describe corporate parent/subsidiary,
practice, historical-identity, and acquisition lineage as edges a complete
relationship taxonomy must admit -- this fixture proves the four new codes
this revision seeds (`parent_of`/`subsidiary_of`, `practice_of`,
`historical_identity_of`, `acquired_by`) actually round-trip through
`entity_relationships` now that the CHECK is a foreign key into
`entity_relationship_types`.

**Every name and identifier below is synthetic.** Nothing here is drawn from,
derived from, or shaped to reproduce any real TBR register content -- the
case pattern (a parent/subsidiary pair, a professional practice under a
parent, a historical predecessor, and a time-bounded acquisition) is the
audit's own description of a *class* of record the schema must represent,
not an import of real data (`MIGRATION-001`, `AGENTS.md` section 5).

**What this fixture proves:**

1. `parent_of`/`subsidiary_of` round-trip as a directed edge between two
   organization entities, and the taxonomy's `inverse_type_code` correctly
   names the other side of the pair without a second row being required;
2. `practice_of` connects a professional-practice organization to its parent,
   the Trinity/Longman Lindsey pattern the audit's section L names directly;
3. `historical_identity_of` connects a historical predecessor entity to its
   current successor -- a *different* `entities` row, per RI-ENT-WP-02's
   architecture rule, never a name row on the survivor;
4. `acquired_by` carries a real, **time-bounded** `effective_from`/
   `effective_to` window (not open-ended) -- an acquisition is a dated
   corporate event, and this is the case the audit's own "acquisition
   lineage can be time-bounded" note (section K) describes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_entity_relationship_types_tbr_fixture_test"

PRINCIPAL: Final = "prn_hhhh0011hhhh0011hhhh0011"

#: The corporate parent: synthetic "Synthetic Holdings Group" analogue.
PARENT_ORG: Final = "ent_hhhh0011hhhh0011"
#: A wholly-owned subsidiary of the parent.
SUBSIDIARY_ORG: Final = "ent_iiii0012iiii0012"
#: A professional practice operating under the parent.
PRACTICE_ORG: Final = "ent_jjjj0013jjjj0013"
#: A historical predecessor of the parent -- a distinct juristic identity.
HISTORICAL_ORG: Final = "ent_kkkk0014kkkk0014"
#: An organization the parent acquired, on a dated, closed transaction.
ACQUIRED_ORG: Final = "ent_llll0015llll0015"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _seed_organization(engine: Engine, entity_id: str, canonical: str, display: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entities "  # noqa: S608
                "(entity_id, principal_id, entity_type, canonical_name, display_name, status) "
                "VALUES (:entity_id, :principal_id, 'organization', :canonical, :display, "
                "'active')"
            ),
            {
                "entity_id": entity_id,
                "principal_id": PRINCIPAL,
                "canonical": canonical,
                "display": display,
            },
        )


@pytest.mark.database
def test_corporate_lineage_edges_round_trip_with_a_time_bounded_acquisition(
    migrated_engine: Engine,
) -> None:
    _seed_organization(
        migrated_engine, PARENT_ORG, "synthetic holdings group", "Synthetic Holdings Group"
    )
    _seed_organization(
        migrated_engine,
        SUBSIDIARY_ORG,
        "synthetic field services llc",
        "Synthetic Field Services, LLC",
    )
    _seed_organization(
        migrated_engine,
        PRACTICE_ORG,
        "synthetic structural practice",
        "Synthetic Structural Practice",
    )
    _seed_organization(
        migrated_engine,
        HISTORICAL_ORG,
        "synthetic predecessor holdings",
        "Synthetic Predecessor Holdings",
    )
    _seed_organization(
        migrated_engine, ACQUIRED_ORG, "synthetic acquired studio", "Synthetic Acquired Studio"
    )

    with migrated_engine.begin() as connection:
        # subsidiary_of: the subsidiary -> the parent, directed.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                "principal_id) VALUES "
                "('erel_hhhh0011aaaa0001', :from_entity_id, 'subsidiary_of', :to_entity_id, "
                ":principal_id)"
            ),
            {
                "from_entity_id": SUBSIDIARY_ORG,
                "to_entity_id": PARENT_ORG,
                "principal_id": PRINCIPAL,
            },
        )
        # practice_of: the practice -> the parent, directed.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                "principal_id) VALUES "
                "('erel_hhhh0011aaaa0002', :from_entity_id, 'practice_of', :to_entity_id, "
                ":principal_id)"
            ),
            {
                "from_entity_id": PRACTICE_ORG,
                "to_entity_id": PARENT_ORG,
                "principal_id": PRINCIPAL,
            },
        )
        # historical_identity_of: the predecessor -> the current entity, directed.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                "principal_id) VALUES "
                "('erel_hhhh0011aaaa0003', :from_entity_id, 'historical_identity_of', "
                ":to_entity_id, :principal_id)"
            ),
            {
                "from_entity_id": HISTORICAL_ORG,
                "to_entity_id": PARENT_ORG,
                "principal_id": PRINCIPAL,
            },
        )
        # acquired_by: the acquired org -> the parent, TIME-BOUNDED -- a real
        # effective_from/effective_to window, not open-ended. The deal signed
        # 2018-01-15 and closed 2018-06-30; both dates are stated, which is
        # what makes this the audit's "acquisition lineage can be
        # time-bounded" case rather than an ongoing, open-ended tie.
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.entity_relationships "  # noqa: S608
                "(relationship_id, from_entity_id, relationship_type, to_entity_id, "
                "principal_id, effective_from, effective_to) VALUES "
                "('erel_hhhh0011aaaa0004', :from_entity_id, 'acquired_by', :to_entity_id, "
                ":principal_id, '2018-01-15T00:00:00+00', '2018-06-30T00:00:00+00')"
            ),
            {
                "from_entity_id": ACQUIRED_ORG,
                "to_entity_id": PARENT_ORG,
                "principal_id": PRINCIPAL,
            },
        )

    with migrated_engine.connect() as connection:
        # All four edges round-trip with the exact codes seeded.
        edges = connection.execute(
            text(
                f"SELECT from_entity_id, relationship_type, to_entity_id, "  # noqa: S608
                f"effective_from, effective_to FROM {SCHEMA}.entity_relationships "
                "WHERE principal_id = :principal_id ORDER BY relationship_id"
            ),
            {"principal_id": PRINCIPAL},
        ).all()
        assert [tuple(row[:3]) for row in edges] == [
            (SUBSIDIARY_ORG, "subsidiary_of", PARENT_ORG),
            (PRACTICE_ORG, "practice_of", PARENT_ORG),
            (HISTORICAL_ORG, "historical_identity_of", PARENT_ORG),
            (ACQUIRED_ORG, "acquired_by", PARENT_ORG),
        ]

        # The acquired_by edge specifically carries a real, closed window --
        # both effective_from and effective_to are non-null and distinct,
        # never an open-ended (NULL effective_to) tie.
        acquisition = next(row for row in edges if row[1] == "acquired_by")
        assert acquisition[3] is not None
        assert acquisition[4] is not None
        assert acquisition[3] != acquisition[4]

        # The taxonomy names subsidiary_of's declared inverse as parent_of,
        # without a second (mirrored) entity_relationships row being
        # required to know that.
        inverse = connection.execute(
            text(
                f"SELECT inverse_type_code FROM {SCHEMA}.entity_relationship_types "  # noqa: S608
                "WHERE relationship_type_code = 'subsidiary_of'"
            )
        ).scalar_one()
        assert inverse == "parent_of"

        # historical_identity_of connects two DISTINCT entities rows, never
        # a name row folded onto the survivor -- the RI-ENT-WP-02 rule
        # restated at the edge this revision now admits.
        entity_count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entities WHERE principal_id = :principal_id"  # noqa: S608
            ),
            {"principal_id": PRINCIPAL},
        ).scalar_one()
        assert entity_count == 5
