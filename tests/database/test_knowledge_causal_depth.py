"""KLP-WP-04: causal lineage, depth and the citation-independent rate bound (DB).

KLP-AC-049, KLP-AC-050 and KLP-AC-119 (R6 section 9). Marked `database` (auto
`database_clone`), routed to `database-current-head`.

Every submission is a production autonomous submit; every trigger it cites is a
committed Record Event written by an earlier production write. The causal
fields are read back from the stored rows.

* KLP-AC-050: a chain of six submissions, each citing the previous one's
  `knowledge_assertion` event -- depths 0..4 are admitted with the first as
  root, and the sixth (would-be depth 5) is refused `causal_depth_exceeded`,
  born completed with NULL causal fields; two roots are `causal_root_ambiguous`;
  a repeated (client, subject_kind, subject_id, predicate_code) anywhere in the
  lineage is `causal_repeat` whatever the run id.
* KLP-AC-049: the root is resolved server-side `event.source_receipt_id = kamut_
  -> mutation.submission_id`; a non-Knowledge trigger and a maintenance
  mutation (no submission) contribute no root; an explicit create is a root.
  The submit's own events name actor `assistant` / authority
  `source_backed_assertion` from the transport/client binding.
* KLP-AC-119: client-chosen run ids cannot evade the cited-trigger rules; an
  unknown trigger refuses with no write; independently of citation the 17th
  counted submission of one client/run/subject is refused
  `causal_rate_exceeded` (a fresh run id resets it: residual R-3).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import select

from my_pa.infrastructure.persistence.tables import (
    knowledge_evidence_refs,
    knowledge_submission_trigger_events,
    record_events,
)
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import (
    WHEN,
    capture_evidence,
    counts,
    knowledge_events,
    new_principal,
    submission_row,
)
from tests.database.test_knowledge_assertion_submissions import (
    PAYMENT,
    SubmitRuntime,
    external,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def event_of(runtime: SubmitRuntime, mutation_id: str) -> str:
    with runtime.engine.connect() as connection:
        return str(
            connection.execute(
                select(record_events.c.event_id).where(
                    record_events.c.source_receipt_id == mutation_id
                )
            ).scalar_one()
        )


def snapshots(runtime: SubmitRuntime, submission_id: str) -> list[dict[str, Any]]:
    t = knowledge_submission_trigger_events
    with runtime.engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(t).where(t.c.submission_id == submission_id)
            ).mappings()
        ]


def _hop(
    runtime: SubmitRuntime,
    principal: str,
    profile: str,
    subject: str,
    key: str,
    triggers: tuple[str, ...] = (),
    run: str = "run-1",
) -> dict[str, Any]:
    return runtime.submit(
        principal,
        profile,
        subject_id=subject,
        candidate=f"cand-{key}",
        run=run,
        value=f"Synthetic requirement {key}",
        evidence=(external(f"obj-{key}"),),
        triggers=triggers,
    )


def test_a_six_chain_admits_depths_zero_to_four_and_refuses_the_sixth(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    subjects = [runtime.entity(principal, f"chain-{index}") for index in range(6)]
    results: list[dict[str, Any]] = []
    triggers: tuple[str, ...] = ()
    for index, subject in enumerate(subjects):
        result = _hop(runtime, principal, profile, subject, f"h{index}", triggers)
        results.append(result)
        if result["mutation_id"] is not None:
            triggers = (event_of(runtime, result["mutation_id"]),)
    root = results[0]["submission_id"]
    for depth, result in enumerate(results[:5]):
        assert result["outcome"] == "direct_created", (depth, result)
        row = submission_row(runtime.engine, result["submission_id"])
        assert row["causal_depth"] == depth
        assert row["causal_root_submission_id"] == root
    sixth = results[5]
    assert sixth["outcome"] == "refused"
    assert sixth["reason"] == "causal_depth_exceeded"
    row = submission_row(runtime.engine, sixth["submission_id"])
    assert row["causal_depth"] is None
    assert row["causal_root_submission_id"] is None
    assert row["submission_state"] == "completed"
    # The causal snapshot of the cited trigger is stored with the refusal too.
    (snapshot,) = snapshots(runtime, sixth["submission_id"])
    assert snapshot["parent_submission_id"] == results[4]["submission_id"]
    assert snapshot["parent_causal_depth"] == 4
    assert snapshot["parent_causal_root_submission_id"] == root
    # The submit's events carry the binding-derived actor and authority (AC-049).
    assert {
        (e["actor_class"], e["authority"]) for e in knowledge_events(runtime.engine, principal)
    } == {("assistant", "source_backed_assertion")}


def test_two_roots_are_causal_root_ambiguous(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    a, b, c = (runtime.entity(principal, f"amb-{key}") for key in "abc")
    first = _hop(runtime, principal, profile, a, "a")
    second = _hop(runtime, principal, profile, b, "b")
    refused = _hop(
        runtime,
        principal,
        profile,
        c,
        "c",
        (event_of(runtime, first["mutation_id"]), event_of(runtime, second["mutation_id"])),
    )
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "causal_root_ambiguous"
    assert submission_row(runtime.engine, refused["submission_id"])["causal_depth"] is None


def test_a_repeat_anywhere_in_the_lineage_is_refused_whatever_the_run(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    x, y = runtime.entity(principal, "rep-x"), runtime.entity(principal, "rep-y")
    first = _hop(runtime, principal, profile, x, "x1")
    second = _hop(
        runtime, principal, profile, y, "y1", (event_of(runtime, first["mutation_id"]),), "run-2"
    )
    assert second["outcome"] == "direct_created"
    # Back to subject x, through a fresh run id: the lineage still holds x.
    repeat = _hop(
        runtime, principal, profile, x, "x2", (event_of(runtime, second["mutation_id"]),), "run-3"
    )
    assert repeat["outcome"] == "refused"
    assert repeat["reason"] == "causal_repeat"


def test_a_non_knowledge_trigger_contributes_no_root(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    runtime.project(principal, "causal-other")
    with runtime.engine.connect() as connection:
        other = connection.execute(
            select(record_events.c.event_id).where(
                record_events.c.principal_id == principal,
                record_events.c.record_family != "knowledge_assertion",
            )
        ).first()
    assert other is not None, "the project write stages a non-Knowledge event"
    subject = runtime.entity(principal, "causal-root")
    result = _hop(runtime, principal, profile, subject, "nr", (other.event_id,))
    assert result["outcome"] == "direct_created"
    row = submission_row(runtime.engine, result["submission_id"])
    assert row["causal_depth"] == 0
    assert row["causal_root_submission_id"] == result["submission_id"]
    (snapshot,) = snapshots(runtime, result["submission_id"])
    assert snapshot["parent_submission_id"] is None


def test_a_maintenance_mutation_trigger_contributes_no_root(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    capture = runtime.capture(principal, "maint")
    created = runtime.create(principal, "k-maint", evidence=(capture_evidence(*capture),))
    with runtime.engine.connect() as connection:
        evidence_ref = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        classified = repository.classify_evidence_restricted(principal, evidence_ref, at=WHEN)
    assert classified.mutated_assertion_ids == (created["assertion_id"],)
    # The classify event is restricted, so a remote caller cannot see it: citing
    # it is `not_found` and writes nothing (no oracle, no root).
    with runtime.engine.connect() as connection:
        classify_event = connection.execute(
            select(record_events.c.event_id).where(
                record_events.c.principal_id == principal,
                record_events.c.event_kind == "state_changed",
            )
        ).scalar_one()
    profile = runtime.profile(principal)
    subject = runtime.entity(principal, "maint-subject")
    before = counts(runtime.engine, principal)["knowledge_assertion_submissions"]
    error = runtime.submit_error(
        principal,
        profile,
        subject_id=subject,
        evidence=(external("obj-maint"),),
        triggers=(classify_event,),
    )
    assert error["code"] == "not_found"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == before


def test_an_explicit_create_is_a_root_its_child_inherits(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    capture = runtime.capture(principal, "create-root")
    created = runtime.create(principal, "k-root", evidence=(capture_evidence(*capture),))
    profile = runtime.profile(principal)
    subject = runtime.entity(principal, "child")
    child = _hop(
        runtime, principal, profile, subject, "child", (event_of(runtime, created["mutation_id"]),)
    )
    assert child["outcome"] == "direct_created"
    row = submission_row(runtime.engine, child["submission_id"])
    assert row["causal_depth"] == 1
    assert row["causal_root_submission_id"] == created["submission_id"]


def test_an_unknown_trigger_refuses_with_no_write(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    subject = runtime.entity(principal, "unknown-trigger")
    error = runtime.submit_error(
        principal, profile, subject_id=subject, triggers=("rcev_" + "N0tAnEvent1234567",)
    )
    assert error["code"] == "not_found"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 0


def test_the_seventeenth_counted_submission_of_a_run_is_rate_refused(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "rate")
    for index in range(16):
        queued = runtime.submit(
            principal,
            profile,
            subject_id=org,
            predicate=PAYMENT,
            candidate=f"rate-{index}",
            value=f"Net {index + 1}",
            evidence=(external(f"rate-{index}"),),
        )
        assert queued["outcome"] == "review_queued", (index, queued)
    refused = runtime.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        candidate="rate-16",
        value="Net 99",
        evidence=(external("rate-16"),),
    )
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "causal_rate_exceeded"
    row = submission_row(runtime.engine, refused["submission_id"])
    assert row["causal_depth"] == 0  # a rate refusal keeps its causal fields
    # Residual R-3: a fresh run id is a fresh budget.
    fresh = runtime.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        run="run-fresh",
        candidate="rate-fresh",
        value="Net 98",
        evidence=(external("rate-fresh"),),
    )
    assert fresh["outcome"] == "review_queued"
