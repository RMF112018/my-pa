"""WP-RE-03: Project Controls settings Record Events on a real database (RE-AC-039).

Marked `database` (auto `database_clone`), routed to `database-current-head`.
`ProjectControlsConfigurationService` runs on the production Constraint unit of
work. The settings row has no identifier of its own, so its events are named by
their Project (G1-EM-011):

* the first configure commits one `created` event at version 1;
* a change of calendar commits one `updated` event at version 2;
* the same calendar again (NO_OP), a replay and a committed stale rejection
  commit nothing and advance no sequence.

Every identity here is synthetic.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, select

from my_pa.application.constraint_settings import ProjectControlsVersionConflictError
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.infrastructure.persistence.tables import constraint_project_settings_history
from tests.database.test_project_controls_configure_persistence import (
    OTHER_ZONE,
    PRINCIPAL_A,
    PROJECT_A,
    _configure,
    seed,
)
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


def test_configure_commits_created_then_updated_named_by_the_project(staged: Engine) -> None:
    first = _configure(staged)
    (created,) = feed(staged, PRINCIPAL_A)
    assert created["record_family"] == "project_controls_settings"
    assert created["record_id"] == PROJECT_A
    assert created["event_kind"] == "created"
    assert created["record_version"] == 1
    assert created["changed_fields"] == ["timezone_name"]
    assert created["source_capability"] == "project_controls.configure"
    assert created["actor_class"] == "principal"
    assert created["source_receipt_id"] == first.receipt.history_id
    _configure(
        staged, timezone_name=OTHER_ZONE, idempotency_key="pcs-rcev-change-01", expected_version=1
    )
    updated = feed(staged, PRINCIPAL_A)[-1]
    assert updated["event_kind"] == "updated"
    assert updated["record_version"] == 2
    assert updated["changed_fields"] == ["timezone_name"]
    assert_gap_free(staged, PRINCIPAL_A)


def test_a_no_op_a_replay_and_a_stale_rejection_commit_nothing(staged: Engine) -> None:
    _configure(staged)
    before = (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A))
    _configure(staged)  # replay of the same key
    _configure(staged, idempotency_key="pcs-rcev-same-0001")  # same calendar: NO_OP
    with pytest.raises(ProjectControlsVersionConflictError):
        _configure(
            staged,
            timezone_name=OTHER_ZONE,
            idempotency_key="pcs-rcev-stale-001",
            expected_version=7,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
    with staged.connect() as connection:
        outcomes = sorted(
            connection.execute(select(constraint_project_settings_history.c.outcome)).scalars()
        )
    assert outcomes == ["applied", "no_op", "rejected"]
    assert (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A)) == before
