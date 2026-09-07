"""Revision `7c2e9b4a1d80`: continuity authoring names and task acceptance pairing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory

from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "7c2e9b4a1d80"
PREVIOUS: Final = "4f6a9c2d8e17"

CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset(
    {
        "continuity.projects.create",
        "continuity.situations.create",
        "continuity.tasks.create",
    }
)
PURPOSES_ADDED: Final[frozenset[str]] = frozenset({"continuity_authoring"})


def _frozen_literals(constant: str) -> frozenset[str]:
    matches = [
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ]
    assert len(matches) == 1
    source = matches[0].read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", source[start:end]))


def test_this_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    # 79 since `7e114f822af2` (RI-ENT-WP-02) added the entity_names/
    # entity_organization_profiles migration on top of this chain; 80 since
    # `441b071bf37b` (RI-ENT-WP-03) added the entity_addresses/
    # entity_communication_methods migration on top of that; 81 since
    # `f5b06925857e` (RI-ENT-WP-04) added the entity_project_participations/
    # taxonomy migration on top of that; 82 since `17149a48fa30`
    # (RI-ENT-WP-05) added the entity_person_organization_affiliations
    # migration on top of that; 83 since `8dc3619891bb` (RI-ENT-WP-06a)
    # added the entity_relationship_types taxonomy migration on top of that;
    # 84 since `9a3f6c1e8d24` (RI-ENT-WP-06b) widened the identity-correction
    # family vocabulary on top of that; 85 since `1cda4d536268`
    # (RI-ENT-WP-07) added the entity_assertions/entity_assertion_evidence
    # migration on top of that; 86 since `c99cd8ed8d1c` (commit `37ead78`,
    # RI-ENT-WP-08's blocker-clearing pass) renamed the seeded
    # entity_relationship_types row `design_coordinates_with` to
    # `design_coordination_with` on top of that; 87 since `2c00c9ac64bc`
    # (UI-IMP-WP02) added WebAuthn credential, challenge, recovery-code, and
    # opaque session tables on top of that; 88 since `16f05c46b8c3`
    # (RI-ENT-WP-10/11) widened three closed-set CHECKs --
    # `audit_events.capability_is_known` 115 -> 135,
    # `entity_mutation_events.a_mutated_record_family_is_known` 6 -> 11 and
    # `entity_proposals.an_accepted_proposal_record_family_is_known` 6 -> 11 --
    # for RI-ENT-WP-10's five entity reads and RI-ENT-WP-11's fifteen entity
    # mutation contracts on top of that, creating and altering no table; 89
    # since `b8e4d1a6c073` (RI-ENT-WP-12) backfilled one `display`-typed
    # `entity_names` row per active `entities` row on top of that, re-parented
    # from `c99cd8ed8d1c` onto `16f05c46b8c3` so the chain keeps one head
    # (RULING-M11); 91 since `6a2f9d1c4b80` added the GoodNotes pull schema on
    # top of that -- counted on the merged tree, not derived (RULING-M2).
    # R8 adds one receipt migration on the previous 91-revision chain.
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 97


def test_the_frozen_literals_are_this_revision_s_vocabulary() -> None:
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared
    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert purposes <= {member.value for member in Purpose}
    assert admitted - _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION") == CAPABILITIES_ADDED
    assert purposes - _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION") == PURPOSES_ADDED


def test_the_revision_reads_no_enum() -> None:
    source = next(
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ).read_text(encoding="utf-8")
    assert "my_pa.domain" not in source
    for forbidden in ("Capability", "Purpose"):
        assert f"import {forbidden}" not in source
