"""`QC-AC-002`: a save's acknowledgment does not wait for extraction or indexing.

The spec is `20_…:182` — "Save acknowledgment does not wait for
**AI/extraction/indexing**". The plan's stated proof is "assert the save
transaction's committed set contains no proposal row", and `D-89` records why
that is insufficient: membership is not ordering, and a save could commit no
proposal row while blocking on a synchronous index write and still pass it.

WP-6 shipped the save, so the *extraction* half was unfalsifiable-because-absent
until now. WP-7 is the package that adds the things that could block, so WP-7
owes the proof — and the assertion below is on the **whole** committed set rather
than on proposals alone.

**One thing is disclosed rather than claimed, because the implementation overtook
the design.** `D-89` expected WP-7 to add an index *write* that this test would
watch stay out of the save. It did not: the capture plane is a **functional GIN
index over `capture_versions.content`**, created by revision `2b7e9f4c1a83`, so
there is no index row and no index table for the save's committed set to contain.
That half of the criterion is therefore **structurally true rather than
measured** — and it is structurally true in the stronger direction, because a
searchability that the pipeline never wrote is a searchability the pipeline
cannot discard. What PostgreSQL does do inside the save is maintain that index,
which is storage-engine index maintenance on the row being stored and is not the
pipeline's indexing stage; the criterion's subject is the asynchronous
enrichment, and `P-16` is where that lives. Read the last test here for what is
actually asserted about it.

Synthetic fixtures throughout (`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, Table, func, select
from tests.pipeline.conftest import RICH_NOTE, drain, save

from my_pa.contracts.ports import CaptureSearchRequest
from my_pa.domain.search.query import SearchQuery
from my_pa.infrastructure.persistence.capture_search import search_captures
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, job_for
from my_pa.infrastructure.persistence.tables import (
    JobState,
    capture_assertion_spans,
    capture_assertions,
    capture_classifications,
    capture_context_links,
    capture_conversations,
    capture_entity_mentions,
    capture_processing_text,
    capture_promotion_receipts,
    capture_proposal_spans,
    capture_proposals,
    capture_receipts,
    capture_review_cases,
    capture_review_decisions,
    capture_spans,
    capture_stage_results,
    capture_submissions,
    capture_versions,
    captures,
)

pytestmark = pytest.mark.database

#: What the save is allowed to commit: the record, its version, the receipt that
#: acknowledges it, the submission that keys it, and the queued job. Five tables,
#: and the fifth is the only processing artefact — a row saying work is *owed*,
#: not a row of work done.
SAVE_COMMITS: tuple[Table, ...] = (
    captures,
    capture_versions,
    capture_receipts,
    capture_submissions,
)

#: Every `capture_*` table the save does not own, and which it therefore must
#: commit nothing to. Listed so that a table added later and forgotten here is a
#: table this test stops covering — which is why the set is derived and compared
#: below rather than only iterated.
#:
#: The seven WP-7 added are what the *pipeline* commits. The seven WP-8 added are
#: not written by the pipeline either: a review case, a decision, an assertion
#: and a promotion receipt are written by a review disposition, and a context
#: link and a conversation event by the create that seeded them. The claim this
#: list serves is the same for all fourteen and is the one `QC-AC-002` makes —
#: **the save transaction commits none of them** — so narrowing the list to
#: "what the pipeline writes" would drop seven tables from a guarantee that
#: covers them.
PIPELINE_COMMITS: tuple[Table, ...] = (
    capture_processing_text,
    capture_stage_results,
    capture_spans,
    capture_proposals,
    capture_proposal_spans,
    capture_classifications,
    capture_entity_mentions,
    capture_review_cases,
    capture_review_decisions,
    capture_assertions,
    capture_assertion_spans,
    capture_promotion_receipts,
    capture_context_links,
    capture_conversations,
)


def test_the_save_transaction_commits_no_proposal_and_no_index_row(engine: Engine) -> None:
    """The whole committed set, not the proposal half of it.

    Both directions are asserted, because either alone is satisfied by a broken
    save: the five tables a save owns are non-empty, and every one of the seven
    the pipeline owns is empty. The queued job is asserted separately, because
    `queued` — rather than absent, and rather than `succeeded` — is what "the
    work is owed and has not started" looks like.

    **The plant that reddens it** is a pipeline call inside `admit_capture`: any
    one of the seven then has a row, and the assertion names which.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)

    with engine.connect() as connection:
        for table in SAVE_COMMITS:
            assert _rows(connection, table) >= 1, (
                f"{table.name} is empty after a save, so the emptiness asserted below "
                "would be the emptiness of a store nothing wrote to"
            )
        for table in PIPELINE_COMMITS:
            assert _rows(connection, table) == 0, (
                f"{table.name} holds a row committed by the save transaction. "
                "`QC-AC-002` says the acknowledgment does not wait for extraction or "
                "indexing, and a row that is there is a row the save waited for"
            )

        # The one processing artefact the save may commit: a statement that work
        # is owed. `queued` and not `running`, so nothing has claimed it.
        record = job_for(connection, saved.operation_id, plane=CAPTURE_JOBS)
        assert record is not None, "the save queued no processing job at all"
        assert record.state is JobState.QUEUED
        assert record.subject_id == saved.version_id


def test_the_saved_capture_is_searchable_before_any_worker_runs(engine: Engine) -> None:
    """`11_…:191`'s "immediately", asserted at the only instant that can show it.

    No worker has run — the job is still `queued`, which is asserted rather than
    assumed — and the capture is already findable. That is the other half of the
    same design decision as the test above: the save commits no pipeline row
    *and* the text is searchable, which is only consistent because searchability
    is a property of the saved column rather than of a row somebody indexed.

    The control is the count beside the match: `stored_versions` is non-zero, so
    a hit here is a hit against a store that holds something.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)

    with engine.connect() as connection:
        record = job_for(connection, saved.operation_id, plane=CAPTURE_JOBS)
        assert record is not None and record.state is JobState.QUEUED, (
            "a worker had already run, so `before any worker runs` is not what this test measured"
        )
        assert _rows(connection, capture_stage_results) == 0, "a stage had already run"

        outcome = search_captures(
            connection, CaptureSearchRequest(query=SearchQuery("buyout"), limit=10)
        )
    assert [match.version_id for match in outcome.matches] == [saved.version_id], (
        "a saved capture was not searchable until something processed it. "
        "`QC-AC-050` makes the original text searchable independently of enrichment "
        "and `11_…:191` says the capture text is indexed immediately"
    )
    assert outcome.stored_versions >= 1


def test_the_index_confirmation_stage_runs_before_proposal_persistence(
    engine: Engine,
) -> None:
    """`P-16` before `P-15`, measured from the stage results the run recorded.

    This is what WP-7 actually owes on the indexing half. There is no index row
    to keep out of a transaction — the plane is a functional index over the saved
    column — so what can be wrong is the *ordering of the confirmation*: a
    searchability check recorded only after proposals are persisted is a check
    that never runs for the capture whose extraction failed, which is the only
    capture `QC-AC-050` is about.

    Measured by `started_at`, from the server's clock, on rows the pipeline wrote
    in separate transactions — not by reading `PIPELINE_ORDER`, which would be
    this test asserting a constant against itself.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)
    assert drain(engine).completed == 1

    with engine.connect() as connection:
        started = dict(
            connection.execute(
                select(capture_stage_results.c.stage, capture_stage_results.c.started_at).where(
                    capture_stage_results.c.version_id == saved.version_id
                )
            ).all()
        )
    assert {"index_capture_text", "persist_proposals"} <= set(started), (
        f"the run recorded {sorted(started)}, so the comparison below has nothing to compare"
    )
    assert started["index_capture_text"] < started["persist_proposals"], (
        "the searchability confirmation was recorded after proposal persistence. "
        "`11_…:191` indexes the original capture text immediately and `QC-AC-050` "
        "makes it searchable independently of enrichment success; a confirmation "
        "sequenced behind `P-15` never runs for the capture that fails there"
    )


def test_the_pipeline_tables_this_test_covers_are_all_of_them(engine: Engine) -> None:
    """A guard on the list above, because a forgotten table is a silent hole.

    `PIPELINE_COMMITS` is written out, and a table WP-7 or a later package adds
    without adding it here would drop out of the committed-set assertion with
    nothing to say so. Derived from the declaration rather than from a second
    list: every `knowledge.capture_*` table that is not one of the save's own is
    a table the pipeline can write.

    Deliberately **not** narrowed to tables carrying a `version_id`, which is
    where this first went: `capture_proposal_spans` is a link table keyed by
    `(proposal_id, span_id)` and holds no version at all, so that filter dropped
    it and the guard would have gone on agreeing with a list one short.
    """
    from my_pa.infrastructure.persistence.tables import METADATA

    save_owned = {table.name for table in SAVE_COMMITS} | {"capture_jobs"}
    derived = {
        table.name
        for table in METADATA.tables.values()
        if table.schema == "knowledge"
        and table.name.startswith("capture_")
        and table.name not in save_owned
    }
    assert derived == {table.name for table in PIPELINE_COMMITS}, (
        f"the declaration holds {sorted(derived)} and this module lists "
        f"{sorted(table.name for table in PIPELINE_COMMITS)}. A table missing from the "
        "list is a table the committed-set assertion silently stops covering"
    )


def _rows(connection: object, table: Table) -> int:
    return int(
        connection.execute(select(func.count()).select_from(table)).scalar_one()  # type: ignore[attr-defined]
    )
