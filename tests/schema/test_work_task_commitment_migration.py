"""Static and metadata contract for the WP-FE-03 Work migration.

The disposable PostgreSQL migration suite supplies execution proof when a
local isolated server is available. These tests remain meaningful without one:
they pin the Alembic edge, downgrade symmetry, and the SQLAlchemy metadata the
runtime uses to issue Task bulk statements.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, UniqueConstraint

from my_pa.infrastructure.persistence.tables import task_bulk_operations

ROOT = Path(__file__).resolve().parents[2]
REVISION = "a4d9e7c2b615"
PREVIOUS = "e9b2c4d7a150"
#: The Relationship Memory plane, which stacked on this revision rather than
#: forking beside it. This revision was head when it merged and is not now, so
#: the edge is asserted in both directions below and the head is asserted once,
#: which is what "single head" was there to say.
SUCCESSOR = "f1c6b904a2d7"
#: And the entity lifecycle plane (WP-RI-A-01), which stacked on `SUCCESSOR` for
#: the same reason. Named separately so the assertion below stays a statement
#: about the *order* rather than about whichever revision happens to be last.
LIFECYCLE = "2fe4e13fb449"
#: And Phase A's single vocabulary revision, which stacked on `LIFECYCLE` and is
#: where the single head now sits. Named on the same terms as the two above.
#: Phase A's single vocabulary revision, which sat on `LIFECYCLE` and was head
#: until the Phase B chain stacked on it.
PHASE_A = "823e23b6cc63"
#: Phase B's vocabulary revision and the cumulative Relationship Intelligence
#: revision stacked on it. Named separately so the chain assertion remains a
#: statement about order rather than conflating an historical edge with head.
PHASE_B = "b64e29a0f7c1"
PHASE_B_HEAD = "3d07af4dc513"
GSQS_REVISION = "c4b0a1d9e827"
PHASE_B_START = "c7a1f04b9e63"
#: The chain's current head is `6a2f9d1c4b80` (GoodNotes pull/review), serialized
#: as the direct child of `c3f8a1d07e94`. That graph-vocabulary parent is additive on `b8e4d1a6c073`, whose RI-ENT-WP-12 migration backfills one
#: `display`-typed `entity_names` row per active `entities` row -- `display_value`
#: from `entities.display_name`, `normalized_value` from `entities.canonical_name`,
#: never a `legal` name -- and writes no `entity_project_participations` row
#: (RULING-M10). It was written against `c99cd8ed8d1c` and re-parented onto
#: `16f05c46b8c3` once RI-ENT-WP-10/11 merged (RULING-M11), so the pair stand as one
#: chain rather than two heads. `16f05c46b8c3` (RI-ENT-WP-10/11) widens three
#: closed-set CHECKs -- `audit_events.capability_is_known` (115 -> 135),
#: `entity_mutation_events.a_mutated_record_family_is_known` (6 -> 11) and
#: `entity_proposals.an_accepted_proposal_record_family_is_known` (6 -> 11) -- to admit
#: RI-ENT-WP-10's five entity reads and RI-ENT-WP-11's fifteen entity mutation contracts,
#: creating and altering no table; it was itself re-parented from `c99cd8ed8d1c` onto
#: `2c00c9ac64bc` (UI-IMP-WP02 auth persistence) for the same reason. `2c00c9ac64bc`
#: adds WebAuthn credential, challenge, recovery-code and opaque session tables, and is
#: itself additive on `c99cd8ed8d1c` (RI-ENT-WP-08's blocker-clearing pass), which
#: renames the seeded `entity_relationship_types` row `design_coordinates_with` to
#: `design_coordination_with`; that in turn stacked on `1cda4d536268` (RI-ENT-WP-07).
#: Written out rather than derived so chain drift fails here rather than passing.
HEAD = "6a2f9d1c4b80"
REVISION_PATH = (
    ROOT
    / "migrations"
    / "versions"
    / "20260821_a4d9e7c2b615_admit_work_task_commitment_contracts.py"
)


def test_work_revision_sits_on_the_single_head_chain_after_its_predecessor() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert script.get_heads() == [HEAD]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(SUCCESSOR).down_revision == REVISION
    assert script.get_revision(LIFECYCLE).down_revision == SUCCESSOR
    assert script.get_revision(PHASE_A).down_revision == LIFECYCLE
    assert script.get_revision(GSQS_REVISION).down_revision == PHASE_A
    assert script.get_revision(PHASE_B_START).down_revision == GSQS_REVISION
    assert script.get_revision(PHASE_B).down_revision == "a1f7d3c85e40"
    assert script.get_revision(PHASE_B_HEAD).down_revision == PHASE_B


def test_bulk_metadata_matches_the_persisted_preview_and_confirmation_contract() -> None:
    assert {
        "preview_affected",
        "preview_no_op",
        "confirm_idempotency_key",
        "affected",
        "no_op",
        "rejected",
        "history_ids",
    } <= set(task_bulk_operations.c.keys())
    checks = {
        constraint.name
        for constraint in task_bulk_operations.constraints
        if isinstance(constraint, CheckConstraint)
    }
    uniques = {
        constraint.name
        for constraint in task_bulk_operations.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert {
        "task_bulk_preview_counts_are_non_negative",
        "task_bulk_preview_size_is_bounded",
        "task_bulk_confirmation_matches_preview",
    } <= checks
    assert {
        "one_task_bulk_preview_key_per_principal",
        "one_task_bulk_confirm_key_per_principal",
    } <= uniques


def test_upgrade_and_downgrade_are_symmetric_for_the_work_ledger_and_link_constraint() -> None:
    source = REVISION_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE knowledge.task_bulk_operations" in source
    assert "DROP TABLE knowledge.task_bulk_operations" in source
    assert "tasks_commitment_is_same_principal" in source
    assert (
        "ALTER TABLE knowledge.tasks DROP CONSTRAINT tasks_commitment_is_same_principal" in source
    )
    assert "one_task_bulk_confirm_key_per_principal" in source
    assert "task_bulk_confirmation_matches_preview" in source
    assert "my_pa.domain" not in source
    assert "infrastructure.persistence.tables" not in source
