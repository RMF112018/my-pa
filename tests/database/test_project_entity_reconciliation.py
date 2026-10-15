"""Legacy Project-Entity bridge reconciliation, against a live PostgreSQL server.

WP-MCP-PROJ-05. `9f2c8a1d4e70` backfilled every pre-existing Continuity
Project with an `unresolved_missing` `project_entity_links` row and a null
entity id, and nothing ever resolved those rows. This module exercises
`reconcile_project_entity_links`
(`my_pa.infrastructure.persistence.project_entity_reconciliation`) directly
against a disposable database: the original failure it fixes, the zero- and
one-candidate branches, the same-run same-canonical-name ordering trap,
idempotency, and -- as a clearly separate regression, not a test of the new
mechanism -- that `continuity.projects.create`'s existing forward path
(`_mint_bound_project_entity`) still mints and binds a fresh Project
atomically, untouched by any of this.

No real Person or Organization identifier appears anywhere in this file;
every Entity here is either synthesized by `CreateEntity`/`CreateProject`
through the harness below or minted by the reconciliation function itself.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import text

from my_pa.application.commands import ListEntityParticipations
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.project_entity_reconciliation import (
    ReconciliationOutcome,
    reconcile_project_entity_links,
)
from tests.database.test_project_context_participation import (
    PRINCIPAL_A,
    _participation,
    _person_and_project,
    _Runtime,
)

pytestmark = pytest.mark.database

SCHEMA: Final = "knowledge"
WHEN: Final = datetime(2026, 10, 15, 12, tzinfo=UTC)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[_Runtime]:
    composed = _Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _demote_to_unresolved_missing(
    runtime: _Runtime, *, project_id: str, delete_minted_entity: bool = True
) -> None:
    """Flip a freshly-minted `bound` link back to the legacy backfill shape.

    Mirrors `test_unresolved_bridge_is_conflict_and_does_not_mint`'s own setup
    in `test_project_context_participation.py` for the link row itself, and
    goes one step further by default: the real `9f2c8a1d4e70` backfill never
    minted an Entity for these rows at all, so `delete_minted_entity=True`
    (the default) also removes the Entity `_mint_bound_project_entity` minted
    when the fixture Project was created, so the row is a faithful zero
    -candidate legacy row rather than one that would see its own stale Entity
    as a candidate. Pass `delete_minted_entity=False` when a test wants that
    Entity to remain as a deliberate candidate.
    """
    with runtime.work_engine.begin() as connection:
        entity_id = connection.execute(
            text(
                f"SELECT project_entity_id FROM {SCHEMA}.project_entity_links "  # noqa: S608
                "WHERE principal_id = :principal_id AND project_id = :project_id"
            ),
            {"principal_id": PRINCIPAL_A, "project_id": project_id},
        ).scalar_one()
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.project_entity_links "  # noqa: S608
                "SET linkage_state = 'unresolved_missing', project_entity_id = NULL "
                "WHERE principal_id = :principal_id AND project_id = :project_id"
            ),
            {"principal_id": PRINCIPAL_A, "project_id": project_id},
        )
        if delete_minted_entity and entity_id is not None:
            connection.execute(
                text(f"DELETE FROM {SCHEMA}.entities WHERE entity_id = :entity_id"),  # noqa: S608
                {"entity_id": entity_id},
            )


def _seed_second_unresolved_project(runtime: _Runtime, *, project_id: str, name: str) -> None:
    """A second legacy-shaped row, inserted directly rather than through authoring.

    Used only by the ordering-trap test, where two rows must exist with the
    same canonical name before reconciliation ever runs.
    """
    with runtime.work_engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.projects (
                  project_id, principal_id, name, description, state, participants,
                  opened_at, closed_at, created_at, updated_at, version
                ) VALUES (
                  :project_id, :principal_id, :name, NULL, 'active', '[]'::jsonb,
                  :when, NULL, :when, :when, 1
                )
                """  # noqa: S608
            ),
            {"project_id": project_id, "principal_id": PRINCIPAL_A, "name": name, "when": WHEN},
        )
        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.project_entity_links (
                  principal_id, project_id, project_entity_id, linkage_state,
                  created_at, updated_at
                ) VALUES (
                  :principal_id, :project_id, NULL, 'unresolved_missing', :when, :when
                )
                """  # noqa: S608
            ),
            {"principal_id": PRINCIPAL_A, "project_id": project_id, "when": WHEN},
        )


def _link_state(runtime: _Runtime, *, project_id: str) -> tuple[str, str | None]:
    with runtime.work_engine.connect() as connection:
        row = connection.execute(
            text(
                f"SELECT linkage_state, project_entity_id FROM {SCHEMA}.project_entity_links "  # noqa: S608
                "WHERE principal_id = :principal_id AND project_id = :project_id"
            ),
            {"principal_id": PRINCIPAL_A, "project_id": project_id},
        ).one()
        return row[0], row[1]


def _entity_count(runtime: _Runtime) -> int:
    with runtime.work_engine.connect() as connection:
        return connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entities WHERE principal_id = :principal_id"),  # noqa: S608
            {"principal_id": PRINCIPAL_A},
        ).scalar_one()


# ---- 1. reproduce the original failure, before reconciliation runs -----------


def test_create_and_list_both_refuse_before_reconciliation_runs(runtime: _Runtime) -> None:
    """`.create` and `.list` both see `ConflictError(project_id)` pre-reconciliation.

    `.create`'s refusal is already covered by
    `test_unresolved_bridge_is_conflict_and_does_not_mint`; the `.list` side,
    which runs through the same `_bound_project_entity_id`, is asserted here
    because the task calls it out explicitly as needing its own check.
    """
    person_id, project_id = _person_and_project(runtime, suffix="pre-reconcile")
    _demote_to_unresolved_missing(runtime, project_id=project_id)

    created = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="pre-create")
    )
    assert created.error is not None
    assert created.error.code is ErrorCode.CONFLICT
    assert created.error.safe_details == ("project_id",)

    listed = runtime.invoke(ListEntityParticipations(project_id=project_id))
    assert listed.error is not None
    assert listed.error.code is ErrorCode.CONFLICT
    assert listed.error.safe_details == ("project_id",)


# ---- 2. the same fixture resolves cleanly after reconciliation ---------------


def test_reconciliation_resolves_the_same_fixture_via_both_selectors(runtime: _Runtime) -> None:
    person_id, project_id = _person_and_project(runtime, suffix="post-reconcile")
    _demote_to_unresolved_missing(runtime, project_id=project_id)

    with runtime.work_engine.begin() as connection:
        reconcile_project_entity_links(connection)

    state, entity_id = _link_state(runtime, project_id=project_id)
    assert state == "bound"
    assert entity_id is not None

    created = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="post-create")
    )
    assert created.error is None, created.error

    by_project_id = runtime.invoke(ListEntityParticipations(project_id=project_id))
    assert by_project_id.error is None and by_project_id.result is not None
    by_entity_id = runtime.invoke(
        ListEntityParticipations(entity_id=entity_id, perspective="project")
    )
    assert by_entity_id.error is None and by_entity_id.result is not None
    assert by_project_id.result["participations"] == by_entity_id.result["participations"]
    assert len(by_project_id.result["participations"]) == 1


# ---- 3. zero-candidate branch: mint and bind ----------------------------------


def test_zero_candidate_branch_mints_a_project_entity_and_binds_it(runtime: _Runtime) -> None:
    _, project_id = _person_and_project(runtime, suffix="zero-candidate")
    _demote_to_unresolved_missing(runtime, project_id=project_id)

    with runtime.work_engine.begin() as connection:
        report = reconcile_project_entity_links(connection, principal_id=PRINCIPAL_A)

    minted = [r for r in report.records if r.outcome is ReconciliationOutcome.MINTED_AND_BOUND]
    assert len(minted) == 1
    entity_id = minted[0].detail[0]
    with runtime.work_engine.connect() as connection:
        entity = (
            connection.execute(
                text(
                    f"SELECT entity_type, canonical_name, display_name, status, version "  # noqa: S608
                    f"FROM {SCHEMA}.entities WHERE entity_id = :entity_id"
                ),
                {"entity_id": entity_id},
            )
            .mappings()
            .one()
        )
    assert entity["entity_type"] == EntityType.PROJECT.value
    assert entity["status"] == "active"
    assert int(entity["version"]) == 1
    assert entity["canonical_name"] == normalize_name(entity["display_name"])


# ---- 4. one-candidate branch: flag, never auto-bind ---------------------------


def test_one_candidate_branch_flags_ambiguous_and_never_auto_binds(runtime: _Runtime) -> None:
    person_id, project_id = _person_and_project(runtime, suffix="one-candidate-a")
    _demote_to_unresolved_missing(runtime, project_id=project_id)

    # A second, independent Project whose creation-time mint leaves a
    # project-type Entity with the same canonical name already claimed.
    _, other_project_id = _person_and_project(runtime, suffix="one-candidate-b")
    _, existing_entity_id = _link_state(runtime, project_id=other_project_id)
    assert existing_entity_id is not None

    # Force the first Project's name to collide with the second one's, the
    # way two independently-authored legacy Projects could share a name.
    with runtime.work_engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE {SCHEMA}.projects SET name = ("  # noqa: S608
                f"SELECT name FROM {SCHEMA}.projects WHERE project_id = :other"
                ") WHERE project_id = :mine"
            ),
            {"other": other_project_id, "mine": project_id},
        )

    before_count = _entity_count(runtime)
    with runtime.work_engine.begin() as connection:
        report = reconcile_project_entity_links(connection, principal_id=PRINCIPAL_A)

    ambiguous = [r for r in report.records if r.outcome is ReconciliationOutcome.FLAGGED_AMBIGUOUS]
    assert len(ambiguous) == 1
    assert ambiguous[0].project_id == project_id
    assert existing_entity_id in ambiguous[0].detail

    state, entity_id = _link_state(runtime, project_id=project_id)
    assert state == "unresolved_ambiguous"
    assert entity_id is None
    # No new Entity was created, and the existing candidate is untouched.
    assert _entity_count(runtime) == before_count

    # And `.create` through the demoted Project still refuses -- flagging is
    # not a resolution a caller can act on without a human in the loop.
    still_refused = runtime.invoke(
        _participation(participant_entity_id=person_id, project_id=project_id, key="still-refused")
    )
    assert still_refused.error is not None
    assert still_refused.error.code is ErrorCode.CONFLICT


# ---- 5. same-run, same-canonical-name ordering trap ---------------------------


def test_two_unresolved_rows_sharing_a_name_never_mint_twice(runtime: _Runtime) -> None:
    _, project_id = _person_and_project(runtime, suffix="shared-name")
    _demote_to_unresolved_missing(runtime, project_id=project_id)

    with runtime.work_engine.connect() as connection:
        name = connection.execute(
            text(f"SELECT name FROM {SCHEMA}.projects WHERE project_id = :project_id"),  # noqa: S608
            {"project_id": project_id},
        ).scalar_one()

    # A distinct, valid project_id for the synthetic second row.
    second_project_id = issue_identifier(IdKind.PROJECT)
    _seed_second_unresolved_project(runtime, project_id=second_project_id, name=name)

    before_count = _entity_count(runtime)
    with runtime.work_engine.begin() as connection:
        reconcile_project_entity_links(connection, principal_id=PRINCIPAL_A)

    state_1, entity_1 = _link_state(runtime, project_id=project_id)
    state_2, entity_2 = _link_state(runtime, project_id=second_project_id)
    states = sorted([state_1, state_2])
    assert states == ["bound", "unresolved_ambiguous"]
    bound_entity = entity_1 if state_1 == "bound" else entity_2
    ambiguous_entity = entity_1 if state_1 == "unresolved_ambiguous" else entity_2
    assert bound_entity is not None
    assert ambiguous_entity is None
    # Exactly one new project-type Entity exists, not two.
    assert _entity_count(runtime) == before_count + 1


# ---- 6. idempotency ------------------------------------------------------------


def test_reconciliation_is_idempotent_across_two_calls(runtime: _Runtime) -> None:
    _, mint_project_id = _person_and_project(runtime, suffix="idempotent-mint")
    _demote_to_unresolved_missing(runtime, project_id=mint_project_id)
    _, ambiguous_project_id = _person_and_project(runtime, suffix="idempotent-ambiguous")
    _demote_to_unresolved_missing(runtime, project_id=ambiguous_project_id)
    with runtime.work_engine.connect() as connection:
        colliding_name = connection.execute(
            text(f"SELECT name FROM {SCHEMA}.projects WHERE project_id = :project_id"),  # noqa: S608
            {"project_id": ambiguous_project_id},
        ).scalar_one()
    # Give the ambiguous row a pre-existing candidate so the first
    # reconciliation pass flags it instead of minting.
    with runtime.work_engine.begin() as connection:
        connection.execute(
            text(
                f"""
                INSERT INTO {SCHEMA}.entities (
                  entity_id, principal_id, entity_type, canonical_name,
                  display_name, status, created_at, updated_at, version
                ) VALUES (
                  :entity_id, :principal_id, 'project', :canonical_name,
                  :display_name, 'active', :when, :when, 1
                )
                """  # noqa: S608
            ),
            {
                "entity_id": issue_identifier(IdKind.ENTITY),
                "principal_id": PRINCIPAL_A,
                "canonical_name": normalize_name(colliding_name),
                "display_name": colliding_name,
                "when": WHEN,
            },
        )

    with runtime.work_engine.begin() as connection:
        first = reconcile_project_entity_links(connection, principal_id=PRINCIPAL_A)

    mint_state, mint_entity = _link_state(runtime, project_id=mint_project_id)
    ambiguous_state, ambiguous_entity = _link_state(runtime, project_id=ambiguous_project_id)
    assert mint_state == "bound"
    assert ambiguous_state == "unresolved_ambiguous"

    entity_count_after_first = _entity_count(runtime)

    with runtime.work_engine.begin() as connection:
        second = reconcile_project_entity_links(connection, principal_id=PRINCIPAL_A)

    assert {r.outcome for r in second.records} <= {
        ReconciliationOutcome.ALREADY_BOUND_NOOP,
        ReconciliationOutcome.ALREADY_AMBIGUOUS_NOOP,
    }
    mint_state_2, mint_entity_2 = _link_state(runtime, project_id=mint_project_id)
    ambiguous_state_2, ambiguous_entity_2 = _link_state(runtime, project_id=ambiguous_project_id)
    assert (mint_state_2, mint_entity_2) == (mint_state, mint_entity)
    assert (ambiguous_state_2, ambiguous_entity_2) == (ambiguous_state, ambiguous_entity)
    assert _entity_count(runtime) == entity_count_after_first
    assert first.minted_count >= 1
    assert second.minted_count == 0
    assert second.ambiguous_count == 0


# ---- 7. existing validation is unaffected -------------------------------------
#
# `test_cross_principal_project_id_matches_read_project_not_found` and
# `test_duplicate_active_same_role_is_conflict` in
# `test_project_context_participation.py` already cover this; both are run as
# part of the standard database-tier selection alongside this file rather than
# duplicated here.


# ---- 8. creation-time path regression: NOT the new mechanism -----------------


def test_regression_creation_time_mint_still_works_and_is_untouched(runtime: _Runtime) -> None:
    """`continuity.projects.create`'s existing atomic mint-and-bind, unchanged.

    This proves `_mint_bound_project_entity`
    (`infrastructure.persistence.continuity_authoring.py`) -- which this work
    package was explicitly forbidden from modifying -- still mints a bound
    project-type Entity for a brand-new Project. It exercises none of
    `reconcile_project_entity_links`; a reader should not mistake this for a
    test of the new reconciliation mechanism.
    """
    person_id, project_id = _person_and_project(runtime, suffix="creation-time-regression")
    state, entity_id = _link_state(runtime, project_id=project_id)
    assert state == "bound"
    assert entity_id is not None
    with runtime.work_engine.connect() as connection:
        entity = (
            connection.execute(
                text(
                    f"SELECT entity_type, status, version FROM {SCHEMA}.entities "  # noqa: S608
                    "WHERE entity_id = :entity_id"
                ),
                {"entity_id": entity_id},
            )
            .mappings()
            .one()
        )
    assert entity["entity_type"] == EntityType.PROJECT.value
    assert entity["status"] == "active"
    assert int(entity["version"]) == 1
    created = runtime.invoke(
        _participation(
            participant_entity_id=person_id, project_id=project_id, key="creation-time-regression"
        )
    )
    assert created.error is None, created.error
