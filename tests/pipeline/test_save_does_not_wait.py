"""`QC-AC-002`: a save's acknowledgment does not wait for extraction or indexing.

The spec is `20_…:182` — "Save acknowledgment does not wait for
**AI/extraction/indexing**". The plan's stated proof is "assert the save
transaction's committed set contains no proposal row", and `D-89` records why
that is insufficient: membership is not ordering, and a save could commit no
proposal row while blocking on a synchronous index write and still pass it.

WP-6 shipped the save, so the *extraction* half was unfalsifiable-because-absent
until now. WP-7 is the package that adds the things that could block, so WP-7
owes the proof. This module partitions the observable committed set into the
save's core rows, explicitly synchronous context/conversation metadata, and
downstream outputs rather than making a proposal-only or all-empty claim.

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
enrichment, and `P-16` is where that lives. Read the ordering test below for what
is actually asserted about it.

Synthetic fixtures throughout (`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, Table, func, select, text
from tests.pipeline.conftest import RICH_NOTE, Saved, drain, save

from my_pa.contracts.ports import CaptureSearchRequest
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.common.classification import Classification
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind
from my_pa.infrastructure.persistence.capture_search import search_captures
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, job_for
from my_pa.infrastructure.persistence.registry import observe_object, register_source
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

#: Every downstream enrichment, review, and promotion table the save must not
#: commit to. Listed so that a table added later and forgotten here is a table
#: this test stops covering — which is why the set is derived and compared below
#: rather than only iterated.
#:
#: The seven WP-7 added are what the *pipeline* commits. The seven WP-8 added are
#: not written by the pipeline either. Five are downstream review/promotion
#: outputs and stay absent. The other two — deterministic launch context and an
#: explicit Conversation Log skeleton — deliberately belong to the save and are
#: proved separately below rather than falsely included in this zero-row set.
DOWNSTREAM_OUTPUTS: tuple[Table, ...] = (
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
)

SYNCHRONOUS_CAPTURE_METADATA: tuple[Table, ...] = (
    capture_context_links,
    capture_conversations,
)

#: The first persisted evidence that a pipeline stage has begun. Locking only
#: this table makes an accidental inline worker wait at its first observable
#: downstream boundary without locking `capture_spans` or `capture_review_cases`,
#: which are nullable FK targets of the synchronous context-link insert.
INLINE_PIPELINE_BOUNDARY: Table = capture_stage_results


def test_the_save_transaction_commits_no_downstream_output(engine: Engine) -> None:
    """The full downstream set, not the proposal half of it.

    Both directions are asserted, because either alone is satisfied by a broken
    save: the four core tables a save owns are non-empty, and every downstream
    enrichment/review/promotion table is empty. The queued job is asserted
    separately, because `queued` — rather than absent, and rather than
    `succeeded` — is what "the work is owed and has not started" looks like.

    **The plant that reddens it** is a pipeline call inside `admit_capture`: any
    downstream table then has a row, and the assertion names which.
    """
    with engine.begin() as connection:
        saved = save(connection, RICH_NOTE)

    with engine.connect() as connection:
        for table in SAVE_COMMITS:
            assert _rows(connection, table) >= 1, (
                f"{table.name} is empty after a save, so the emptiness asserted below "
                "would be the emptiness of a store nothing wrote to"
            )
        for table in DOWNSTREAM_OUTPUTS:
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


def test_explicit_conversation_and_context_commit_atomically_without_enrichment(
    engine: Engine,
) -> None:
    """The two explicit save outputs commit together and never run a worker."""
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic launch context",
            classification=Classification.SYNTHETIC_TEST,
            native_root="synthetic-launch-context",
        )
        observed = observe_object(
            connection,
            source_id=source.source_id,
            native_locator="synthetic-launch-context/note.md",
            kind=ObjectKind.FILE,
            fingerprint="synthetic-launch-context-v1",
            modified_at=datetime(2026, 8, 3, 8, 59, tzinfo=UTC),
            media_type="text/markdown",
            size_bytes=1,
        )

    with engine.connect() as blocker, blocker.begin():
        blocker.execute(
            text(f"LOCK TABLE knowledge.{INLINE_PIPELINE_BOUNDARY.name} IN ACCESS EXCLUSIVE MODE")
        )
        with engine.begin() as connection:
            # An inline worker must record a stage result before it can persist
            # stage output. The lock therefore turns that first observable
            # asynchronous boundary into a bounded refusal while leaving the
            # synchronous context/conversation FK graph entirely unlocked.
            connection.execute(text("SET LOCAL statement_timeout = '1000ms'"))
            saved = save(
                connection,
                "synthetic conversation log",
                key="pipeline-explicit-conversation-commit",
                capture_kind=CaptureKind.CONVERSATION_LOG,
                context_source_object_id=observed.source_object_id,
                context_source_version_id=observed.version_id,
            )

    with engine.connect() as connection:
        context = connection.execute(
            select(
                capture_context_links.c.capture_id,
                capture_context_links.c.target_id,
                capture_context_links.c.authority_state,
            ).where(capture_context_links.c.capture_id == saved.capture_id)
        ).one()
        conversation = connection.execute(
            select(
                capture_conversations.c.capture_id,
                capture_conversations.c.version_id,
                capture_conversations.c.event_state,
                capture_conversations.c.channel,
            ).where(capture_conversations.c.capture_id == saved.capture_id)
        ).one()
        assert tuple(context) == (saved.capture_id, observed.source_object_id, "deterministic")
        assert tuple(conversation) == (saved.capture_id, saved.version_id, "skeletal", "unknown")
        for table in DOWNSTREAM_OUTPUTS:
            assert _rows(connection, table) == 0, table.name
        record = job_for(connection, saved.operation_id, plane=CAPTURE_JOBS)
        assert record is not None and record.state is JobState.QUEUED
        assert _rows(connection, capture_stage_results) == 0

    rolled_back: Saved | None = None
    with pytest.raises(RuntimeError, match="rollback control"), engine.begin() as connection:
        rolled_back = save(
            connection,
            "synthetic rolled back conversation log",
            key="pipeline-explicit-conversation-rollback",
            capture_kind=CaptureKind.CONVERSATION_LOG,
            context_source_object_id=observed.source_object_id,
            context_source_version_id=observed.version_id,
        )
        raise RuntimeError("rollback control")
    assert rolled_back is not None
    with engine.connect() as connection:
        for table in (
            captures,
            capture_versions,
            capture_context_links,
            capture_conversations,
        ):
            column = table.c.capture_id
            assert (
                connection.execute(
                    select(func.count()).select_from(table).where(column == rolled_back.capture_id)
                ).scalar_one()
                == 0
            ), table.name
        assert job_for(connection, rolled_back.operation_id, plane=CAPTURE_JOBS) is None


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

    `DOWNSTREAM_OUTPUTS` and `SYNCHRONOUS_CAPTURE_METADATA` are written out, and a
    table WP-7 or a later package adds without adding it here would drop out of
    the committed-set assertion with nothing to say so. Derived from the
    declaration rather than from a second list: every `knowledge.capture_*`
    table that is not one of the save's core tables is either a downstream
    output or explicitly synchronous metadata.

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
    recorded = {table.name for table in (*DOWNSTREAM_OUTPUTS, *SYNCHRONOUS_CAPTURE_METADATA)}
    assert derived == recorded, (
        f"the declaration holds {sorted(derived)} and this module lists "
        f"{sorted(recorded)}. A table missing from the "
        "list is a table the committed-set assertion silently stops covering"
    )


def _rows(connection: object, table: Table) -> int:
    return int(
        connection.execute(select(func.count()).select_from(table)).scalar_one()  # type: ignore[attr-defined]
    )
