"""WP-RE-03: legacy register import Record Events (RE-AC-041).

Marked `database` (auto `database_clone`), routed to `database-current-head`.
`ConstraintLegacyImportService.apply_disposable` runs on the production
Constraint unit of work, exactly as `apps/cli/tbr_import.py` composes it:

* one allocator batch (one transaction, consecutive numbers) holding the
  Category events first, then one `created` per imported record, in the order
  the records were written;
* actor `system`, the bounded non-public source `constraint_legacy_import.apply`,
  and no receipt on a Category event (the import writes none; G1-EM-012);
* a rerun of the same register writes nothing, so it commits nothing;
* a failure inside the batch (the `before_write` seam) commits nothing.

Every identity here is synthetic.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import Engine, select, text

from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    project_constraint_history,
)
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence
from tests.database.test_tbr_import_apply import (
    PRINCIPAL_A,
    _apply,
    _register,
    seed,
)

pytestmark = pytest.mark.database


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


def test_an_import_commits_category_events_then_record_events_in_one_batch(
    staged: Engine, tmp_path: Path
) -> None:
    _apply(staged, _register(tmp_path))
    events = feed(staged, PRINCIPAL_A)
    families = [event["record_family"] for event in events]
    categories = families.count("constraint_category")
    with staged.connect() as connection:
        category_ids = set(
            connection.execute(select(constraint_categories.c.category_id)).scalars()
        )
        receipts = list(
            connection.execute(
                select(
                    project_constraint_history.c.history_id,
                    project_constraint_history.c.constraint_id,
                )
            ).tuples()
        )
        writers = {
            str(value)
            for value in connection.execute(
                text("SELECT DISTINCT xmin::text FROM knowledge.record_events")
            ).scalars()
        }
    assert categories == len(category_ids) >= 1
    assert families == ["constraint_category"] * categories + ["constraint"] * len(receipts)
    assert {event["record_id"] for event in events[:categories]} == category_ids
    assert all(event["source_receipt_id"] is None for event in events[:categories])
    assert {
        (event["source_receipt_id"], event["record_id"]) for event in events[categories:]
    } == set(receipts)
    assert {event["event_kind"] for event in events} == {"created"}
    assert {event["actor_class"] for event in events} == {"system"}
    assert {event["source_capability"] for event in events} == {"constraint_legacy_import.apply"}
    assert len(writers) == 1  # one transaction, one allocator batch
    assert_gap_free(staged, PRINCIPAL_A)


def test_a_rerun_and_a_failed_batch_commit_nothing(staged: Engine, tmp_path: Path) -> None:
    source = _register(tmp_path)

    def refuse() -> None:
        raise RuntimeError("induced failure inside the import batch")

    with pytest.raises(RuntimeError):
        _apply(staged, source, before_write=refuse)
    assert feed(staged, PRINCIPAL_A) == []
    assert next_sequence(staged, PRINCIPAL_A) is None
    _apply(staged, source)
    before = (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A))
    _apply(staged, source)
    assert (feed(staged, PRINCIPAL_A), next_sequence(staged, PRINCIPAL_A)) == before
