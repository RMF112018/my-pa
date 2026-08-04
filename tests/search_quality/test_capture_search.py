"""`QC-AC-050`: **exact** original capture text is searchable, whatever processing did.

Three clauses, three tests, because they fail for three different reasons.

**(a) Exact.** The spec's first word is `Exact` (`20_…:221`) and the plan's
restatement drops it (`D-89`). A stemming configuration is not exact: measured on
this server, `to_tsvector('english', '…running…')` stores `run`, so a query for
`run` matches a document that never contains the word. `D-90` chose `simple` for
that reason, and the test below is what fails if anyone changes it back.

**(b) Independent of enrichment success.** The capture whose processing *failed*
has to be as findable as the one whose processing succeeded. The plane is a
functional GIN index over `capture_versions.content`, so searchability is a
consequence of the save and the pipeline cannot discard it — but "cannot" is a
claim about `capture_text_in_scope`, which is code, and the plant below makes
scope depend on a completed pipeline and watches this go red.

**(c) No silent hole.** `to_tsvector('english', 'a the of and')` is **empty**, so
under that configuration a capture of nothing but stop words is saved, satisfies
`a_capture_version_carries_text`, and is then unfindable by any query with no
exception anywhere — the silent failure this plane exists to refuse. Under
`simple` it yields four lexemes and is found.

Every assertion is on a non-empty result, and the two clauses whose subject is a
zero — the stemmed variant that must *not* match — sit beside a non-zero control
in the same test.

Synthetic fixtures throughout (`QC-AC-073`, `AGENTS.md` section 5).
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from tests.pipeline.conftest import drain, save

from my_pa.contracts.ports import CaptureSearchRequest
from my_pa.domain.search.query import SearchQuery
from my_pa.infrastructure.jobs import capture_pipeline
from my_pa.infrastructure.persistence.capture_search import (
    SEARCH_CONFIG,
    match_statement,
    search_captures,
)
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, job_for
from my_pa.infrastructure.persistence.proposals import proposal_count
from my_pa.infrastructure.persistence.tables import DEFAULT_MAX_ATTEMPTS, JobState

pytestmark = pytest.mark.database

#: A note whose only interesting word is inflected, so a stemming configuration
#: and an exact one give different answers about it.
RUNNING_NOTE = "The buyout was running late this quarter."

#: A note of nothing but stop words. Legal — `length(content) > 0` holds — and
#: unfindable under `english`.
STOP_WORD_NOTE = "a the of and"

#: How many attempts a job gets before it is terminal, read from the schema
#: rather than written down: a default changed there and restated here would
#: leave this suite draining the wrong number of times and calling the result a
#: failure.
MAX_ATTEMPTS = DEFAULT_MAX_ATTEMPTS


def _find(engine: Engine, query: str, *, limit: int = 10) -> tuple[str, ...]:
    """The version identifiers a capture search returns for `query`."""
    request = CaptureSearchRequest(query=SearchQuery(query), limit=limit)
    with engine.connect() as connection:
        return tuple(match.version_id for match in search_captures(connection, request).matches)


def test_a_stemmed_variant_does_not_match_and_the_exact_word_does(engine: Engine) -> None:
    """`QC-AC-050`(a). The zero and the non-zero are in the same test, deliberately.

    "`run` finds nothing" alone would pass on a plane that finds nothing at all,
    which is exactly the silent failure mode this repository keeps meeting. So
    the exact word is asserted to find the capture in the same breath.

    **The plant that reddens it** is the whole reason the plane is `simple`:
    change `SEARCH_CONFIG` to `english` and `run` matches a capture that says
    `running`, because the index and the query both stem.
    """
    with engine.begin() as connection:
        saved = save(connection, RUNNING_NOTE)

    assert _find(engine, "running") == (saved.version_id,), (
        "the exact word did not find the capture that contains it, so the zero "
        "below would say nothing about stemming"
    )
    assert _find(engine, "run") == (), (
        f"`run` matched a capture whose text is {RUNNING_NOTE!r}, which contains no "
        "such word. The plane is stemming, and `QC-AC-050` asks for exact"
    )
    assert SEARCH_CONFIG == "simple", (
        "the two answers above are only different under a configuration that does "
        "not stem; this names which one is in force"
    )


def test_a_capitalised_word_is_found_by_the_lower_case_query_the_index_matches(
    engine: Engine,
) -> None:
    """The two halves of the predicate agree about case, and once they did not.

    Measured on this server: `to_tsvector('simple','Buyout review') @@
    websearch_to_tsquery('simple','buyout')` is true, because `simple`
    lowercases every lexeme, while `strpos('Buyout review','buyout') > 0` is
    false, because it compares bytes. The first version of the exact-substring
    confirmation used the unfolded form, so a single-term query silently removed
    a row the index had correctly matched — `QC-AC-050` false for every
    capitalised word in a note, with no exception anywhere.

    Both directions are asserted, because a confirmation that agreed by never
    filtering anything would pass the first alone: the capitalised query finds
    it too, and a word the note does not contain still finds nothing.

    The server's own answers are asserted beside them, so this test says *why*
    the two must agree rather than only that they do.
    """
    with engine.begin() as connection:
        saved = save(connection, "Buyout review scheduled.")

    with engine.connect() as connection:
        indexed = connection.execute(
            text("SELECT to_tsvector('simple', :body) @@ websearch_to_tsquery('simple', :needle)"),
            {"body": "Buyout review scheduled.", "needle": "buyout"},
        ).scalar_one()
        literal = connection.execute(
            text("SELECT strpos(:body, :needle) > 0"),
            {"body": "Buyout review scheduled.", "needle": "buyout"},
        ).scalar_one()
    assert indexed is True and literal is False, (
        "the indexed predicate and an unfolded `strpos` no longer disagree about "
        "case, so the divergence this test guards has moved and needs re-measuring"
    )

    assert _find(engine, "buyout") == (saved.version_id,), (
        "a capture whose text says `Buyout` was not found by `buyout`, which the "
        "index does match. The exact-substring confirmation is removing a correct "
        "row, which is a silent narrowing rather than an exactness"
    )
    assert _find(engine, "Buyout") == (saved.version_id,), (
        "the capitalised query did not find it either, so the assertion above is "
        "about a broken plane rather than about case folding"
    )
    assert _find(engine, "buyoutx") == (), (
        "a word the note does not contain was found, so the confirmation filters "
        "nothing and the agreement above is agreement by absence"
    )


def test_a_capture_whose_extraction_failed_is_still_searchable(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`QC-AC-050`(b), with the control the criterion needs beside it.

    Two captures, one pipeline failure, one clean run. The failed one has no
    proposals — asserted, so "the failure happened" is a measurement — and is
    found anyway. The clean one is found too, which is the control: a plane that
    found neither would satisfy the first half of the sentence and none of it.

    **The plant that reddens it** is a scope predicate that requires a completed
    pipeline, which is what "searchable only if enrichment succeeded" looks like
    in code. Run against `capture_text_in_scope` it turns the first assertion red
    and leaves the second green.
    """
    with engine.begin() as connection:
        failed = save(connection, f"{RUNNING_NOTE} I will confirm the schedule.")

    real_record_proposal = capture_pipeline.record_proposal

    def failing(connection: object, *args: object, **kwargs: object) -> str:
        raise RuntimeError("extraction failed for this capture")

    monkeypatch.setattr(capture_pipeline, "record_proposal", failing)
    # Driven until the attempts are spent, so the job lands terminal `failed`
    # rather than back on the queue. A job left `queued` would be claimed by the
    # next drain and would then succeed, which is a different fixture entirely —
    # and is exactly what this test measured before the count below caught it.
    failing_run = drain(engine, jobs=MAX_ATTEMPTS)
    assert failing_run.released == MAX_ATTEMPTS, (
        f"the fixture's pipeline did not fail: {failing_run}"
    )
    monkeypatch.setattr(capture_pipeline, "record_proposal", real_record_proposal)

    with engine.connect() as connection:
        state = job_for(connection, failed.operation_id, plane=CAPTURE_JOBS)
        assert state is not None and state.state is JobState.FAILED, (
            f"the failed capture's job is {state} rather than terminal, so the next "
            "drain would claim it and this test would not be about a failure"
        )

    with engine.begin() as connection:
        succeeded = save(connection, "The buyout was running early. I will send the note.")
    assert drain(engine).completed == 1

    with engine.connect() as connection:
        assert proposal_count(connection, failed.version_id) == 0, (
            "the capture whose pipeline was supposed to fail has proposals, so this "
            "test is not about a failed enrichment"
        )
        assert proposal_count(connection, succeeded.version_id) >= 1, (
            "the control capture produced no proposal, so `enrichment succeeded` is "
            "not distinguishable from `enrichment failed` here"
        )

    found = set(_find(engine, "running"))
    assert failed.version_id in found, (
        "a capture whose extraction failed was not searchable. `QC-AC-050` makes "
        "the original text findable independently of enrichment success"
    )
    assert succeeded.version_id in found, (
        "the control — a capture whose extraction succeeded — was not searchable "
        "either, so the assertion above is about a broken plane rather than about "
        "independence"
    )


def test_a_capture_of_only_stop_words_is_searchable_or_discloses_that_it_is_not(
    engine: Engine,
) -> None:
    """`QC-AC-050`(c): the hole `english` opens, measured shut.

    A stop-word-only capture is a legal capture: `a_capture_version_carries_text`
    only requires `length(content) > 0`. Under `english` it produces an empty
    `tsvector` and becomes unfindable **with no exception anywhere** — which is
    an absence a caller cannot tell from "there was nothing to find". Under
    `simple` it yields four lexemes.

    The control is the server's own answer about the two configurations, asserted
    in this test rather than assumed from a comment, so a future PostgreSQL whose
    `english` dictionary changed would show here.
    """
    with engine.begin() as connection:
        saved = save(connection, STOP_WORD_NOTE)

    with engine.connect() as connection:
        under_english = connection.execute(
            text("SELECT to_tsvector('english', :body)::text"), {"body": STOP_WORD_NOTE}
        ).scalar_one()
        under_simple = connection.execute(
            text("SELECT to_tsvector('simple', :body)::text"), {"body": STOP_WORD_NOTE}
        ).scalar_one()
    assert under_english == "", (
        "`english` no longer produces an empty vector for a stop-word-only capture, "
        "so the hole this test is about has moved and the reasoning needs re-measuring"
    )
    assert under_simple != "", "`simple` produced no lexemes either, which closes nothing"

    assert _find(engine, "the") == (saved.version_id,), (
        "a capture of nothing but stop words is stored, valid, and unfindable. That "
        "is an absence with no exception behind it, which is the failure mode this "
        "plane exists to refuse"
    )


def test_the_capture_search_uses_the_functional_index_and_not_a_sequential_scan(
    engine: Engine,
) -> None:
    """The index and the predicate are one decision, and a mismatch is silent.

    `tables.py` records that a configuration mismatch between a functional index
    and the predicate over it **breaks silently** — the query falls back to a
    sequential scan and still returns correct rows, so every other test in this
    file would stay green while the plane stopped being indexed at all. This is
    the only assertion in the suite that can see the difference.

    `enable_seqscan` is turned off for the plan, which is how the merged
    extraction-plane test does it: on a table of two rows the planner prefers a
    scan whatever the index says, and the question here is whether the index is
    *usable*, not whether it is cheapest today.
    """
    with engine.begin() as connection:
        saved = save(connection, RUNNING_NOTE)
    assert _find(engine, "running") == (saved.version_id,)

    request = CaptureSearchRequest(query=SearchQuery("running"), limit=10)
    compiled = match_statement(request).compile(engine, compile_kwargs={"literal_binds": True})
    with engine.connect() as connection:
        connection.execute(text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(
            str(row[0]) for row in connection.execute(text(f"EXPLAIN {compiled}")).all()
        )
    assert "capture_versions_full_text" in plan, (
        f"the capture search did not use its functional index:\n{plan}\nA mismatch "
        "between the index expression and the predicate falls back to a sequential "
        "scan and returns correct rows, so nothing else here would notice"
    )
