"""KLP-WP-04: availability and classification maintenance of Knowledge evidence (DB).

KLP-AC-013, KLP-AC-058 (slice), KLP-AC-070, KLP-AC-142 and KLP-AC-164. Marked
`database` (auto `database_clone`), routed to `database-current-head`.

* **KLP-AC-013** -- a restricted row holds no excerpt: raising a private
  external row that has one redacts it in the same UPDATE (through the
  operator command), `excerpt_sha256` and `content_hash` unchanged; the trigger
  refuses every other excerpt change and the CHECK refuses a restricted row
  that keeps its excerpt.
* **KLP-AC-070 / KLP-AC-142** -- the single availability ingress
  (`SqlKnowledgeAssertionRepository.record_evidence_availability`, called here
  inside the production maintenance transaction): at most 128 linked `active`
  assertions become `revalidation_required` with one mutation and one Record
  Event each, in the same transaction; above 128 the row commits
  `availability_revalidation_pending = true` instead and the guarded drain
  clears it only after marking every one. Identity, links and
  `source_classification` never change; the excerpt is hidden on read, not
  removed at rest. The statement trace proves the order C4b `FOR UPDATE` ->
  links -> C6 -> assertion writes, with no Entity (C3) advisory lock and no
  `FOR SHARE` on evidence. Capture archive writes nothing in Knowledge.
* **KLP-AC-164** -- `classify-evidence` end to end through the operator command
  (no direct SQL for the action under test): a capture-kind row with 130 live
  linked assertions -> run 1 classifies 128 and prints `remaining=2`, exit 3;
  run 2 classifies 2, `remaining=0`, exit 0; a third run is a no-op. No
  lifecycle changes, no pending flag, and a remote read is withheld -- for the
  two not yet classified after run 1 as well (KLP-AC-058: the evidence term).

**Direct SQL** is used only for setup WP-04 slice B1 has no writer for
(external evidence rows with an excerpt and their links; submit is slice B2)
and for the refused writes themselves.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli.knowledge_source_profiles import EXIT_OK, EXIT_REMAINING
from sqlalchemy import Engine, event, func, select, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import (
    ArchiveCapture,
    ReadKnowledgeAssertion,
    RevealKnowledgeAssertion,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.knowledge_assertions import (
    KNOWLEDGE_MAINTENANCE_SOURCE,
    MAINTENANCE_BATCH,
)
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_mutations,
    knowledge_assertions,
    knowledge_evidence_refs,
    record_events,
)
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import (
    KnowledgeRuntime,
    capture_evidence,
    counts,
    new_principal,
)
from tests.database.test_knowledge_source_profiles import provision, run_cli
from tests.security.test_knowledge_assertion_disclosure import REMOTE, link

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

WHEN: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)
EXCERPT: Final = "Synthetic excerpt: vendors must badge in at the gate."


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def seed_external_excerpt(
    engine: Engine, principal: str, profile: str, *, object_id: str, version: str = "v1"
) -> str:
    """Setup only: an external private row with an excerpt (submit is slice B2)."""
    evidence = issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_evidence_refs (principal_id, evidence_ref_id, "
                "identity_kind, source_profile_id, source_is_synthetic, external_object_id, "
                "external_version_id, content_hash, excerpt, excerpt_sha256, content_origin, "
                "source_classification, created_at, updated_at) VALUES (:p, :e, "
                "'external_object', :s, false, :o, :v, :h, :x, :xh, 'external_source', "
                "'private_local', now(), now())"
            ),
            {
                "p": principal,
                "e": evidence,
                "s": profile,
                "o": object_id,
                "v": version,
                "h": hashlib.sha256(f"{object_id}{version}".encode()).hexdigest(),
                "x": EXCERPT,
                "xh": hashlib.sha256(EXCERPT.encode()).hexdigest(),
            },
        )
    return evidence


def evidence_row(engine: Engine, evidence_ref_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(knowledge_evidence_refs).where(
                    knowledge_evidence_refs.c.evidence_ref_id == evidence_ref_id
                )
            )
            .one()
            ._mapping
        )


def lifecycles(engine: Engine, assertion_ids: list[str]) -> dict[str, tuple[str, str, int]]:
    a = knowledge_assertions
    with engine.connect() as connection:
        return {
            row.assertion_id: (row.lifecycle, row.classification, int(row.version))
            for row in connection.execute(
                select(a.c.assertion_id, a.c.lifecycle, a.c.classification, a.c.version).where(
                    a.c.assertion_id.in_(assertion_ids)
                )
            )
        }


def mutation_kinds(engine: Engine, principal: str) -> dict[str, int]:
    m = knowledge_assertion_mutations
    with engine.connect() as connection:
        return {
            row[0]: int(row[1])
            for row in connection.execute(
                select(m.c.mutation_kind, func.count())
                .where(m.c.principal_id == principal)
                .group_by(m.c.mutation_kind)
            )
        }


def maintenance_events(engine: Engine, principal: str) -> list[dict[str, Any]]:
    e = record_events
    with engine.connect() as connection:
        return [
            dict(row._mapping)
            for row in connection.execute(
                select(e).where(
                    e.c.principal_id == principal,
                    e.c.source_capability == KNOWLEDGE_MAINTENANCE_SOURCE,
                )
            )
        ]


def withheld_remotely(runtime: KnowledgeRuntime, principal: str, assertion_id: str) -> bool:
    response = runtime.invoke(
        ReadKnowledgeAssertion(assertion_id=assertion_id), principal_id=principal, **REMOTE
    )
    return response.error is not None


def linked_assertions(
    runtime: KnowledgeRuntime, principal: str, evidence: str, count: int, key: str
) -> list[str]:
    ids: list[str] = []
    for index in range(count):
        created = runtime.create(
            principal, f"klp04-{key}-{index}", value=f"Synthetic requirement {key} {index}"
        )
        link(runtime.engine, principal, created, evidence)
        ids.append(created["assertion_id"])
    return ids


def set_availability(
    engine: Engine, principal: str, evidence: str, state: KnowledgeEvidenceAvailability
) -> Any:  # noqa: ANN401 - the repository's result
    with knowledge_maintenance_transaction(engine) as repository:
        return repository.record_evidence_availability(principal, evidence, state, at=WHEN)


# ---- KLP-AC-013 -----------------------------------------------------------------------


def test_raising_a_private_external_row_redacts_its_excerpt_in_the_same_update(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-redact")
    before = evidence_row(engine, evidence)
    assert before["excerpt"] == EXCERPT

    code, lines = run_cli(
        engine,
        principal,
        "classify-evidence",
        "--evidence-ref",
        evidence,
        "--classification",
        "restricted_local",
    )
    assert code == EXIT_OK, lines
    assert lines[-1] == "remaining=0"
    assert all(EXCERPT not in line for line in lines)
    after = evidence_row(engine, evidence)
    assert (after["source_classification"], after["excerpt"]) == ("restricted_local", None)
    for unchanged in ("excerpt_sha256", "content_hash", "external_object_id", "created_at"):
        assert after[unchanged] == before[unchanged]


@pytest.mark.parametrize(
    "assignment",
    [
        "excerpt = NULL",
        "excerpt = 'Synthetic replacement excerpt'",
        "excerpt = 'Synthetic replacement excerpt', source_classification = 'restricted_local'",
        "excerpt_sha256 = repeat('f', 64)",
        "content_hash = repeat('f', 64)",
    ],
    ids=["null-without-raise", "rewrite", "rewrite-with-raise", "excerpt-digest", "content-hash"],
)
def test_the_trigger_refuses_every_other_excerpt_or_hash_change(
    runtime: KnowledgeRuntime, tmp_path: Path, assignment: str
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-guard")
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE knowledge.knowledge_evidence_refs SET {assignment} "  # noqa: S608
                "WHERE evidence_ref_id = :e"
            ),
            {"e": evidence},
        )
    assert evidence_row(engine, evidence)["excerpt"] == EXCERPT


def test_a_restricted_row_cannot_keep_or_regain_an_excerpt(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-keep")
    with (
        pytest.raises(DBAPIError, match="knowledge_evidence_ref_restricted_has_no_excerpt"),
        engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_evidence_refs SET "
                "source_classification = 'restricted_local' WHERE evidence_ref_id = :e"
            ),
            {"e": evidence},
        )
    run_cli(
        engine,
        principal,
        "classify-evidence",
        "--evidence-ref",
        evidence,
        "--classification",
        "restricted_local",
    )
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_evidence_refs SET excerpt = :x "
                "WHERE evidence_ref_id = :e"
            ),
            {"e": evidence, "x": EXCERPT},
        )


# ---- KLP-AC-070 / KLP-AC-142: the availability ingress --------------------------------


@pytest.mark.parametrize(
    "state",
    [KnowledgeEvidenceAvailability.PERMISSION_LOST, KnowledgeEvidenceAvailability.DELETED],
)
def test_a_loss_marks_linked_live_assertions_and_never_raises_class(
    runtime: KnowledgeRuntime, tmp_path: Path, state: KnowledgeEvidenceAvailability
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-lost")
    ids = linked_assertions(runtime, principal, evidence, 3, f"lost-{state.value}")
    before = evidence_row(engine, evidence)
    links_before = counts(engine, principal)["knowledge_assertion_evidence_links"]

    result = set_availability(engine, principal, evidence, state)

    assert sorted(result.mutated_assertion_ids) == sorted(ids)
    assert (result.remaining, result.pending) == (0, False)
    assert set(lifecycles(engine, ids).values()) == {("revalidation_required", "private_local", 2)}
    assert mutation_kinds(engine, principal) == {"create": 3, "revalidation_required": 3}
    events = maintenance_events(engine, principal)
    assert len(events) == 3
    assert {(e["event_kind"], tuple(e["changed_fields"])) for e in events} == {
        ("state_changed", ("lifecycle",))
    }
    assert {(e["actor_class"], e["authority"]) for e in events} == {
        ("system", "system_deterministic")
    }
    after = evidence_row(engine, evidence)
    assert after["availability_state"] == state.value
    assert after["availability_revalidation_pending"] is False
    # Identity, class, digests and the excerpt at rest are untouched; links kept.
    for unchanged in (
        "source_classification",
        "excerpt",
        "excerpt_sha256",
        "content_hash",
        "external_object_id",
    ):
        assert after[unchanged] == before[unchanged]
    assert counts(engine, principal)["knowledge_assertion_evidence_links"] == links_before
    # Hidden on every read path: withheld remotely, excerpt hidden locally.
    assert all(withheld_remotely(runtime, principal, assertion_id) for assertion_id in ids)
    revealed = runtime.ok(RevealKnowledgeAssertion(assertion_id=ids[0]), principal_id=principal)
    (item,) = revealed["evidence"]
    assert (item["excerpt"], item["availability_state"]) == (None, state.value)
    # A second loss report marks nothing further (no active assertion remains).
    again = set_availability(engine, principal, evidence, state)
    assert again.mutated_assertion_ids == ()


def test_a_restored_availability_clears_no_lifecycle(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-restored")
    ids = linked_assertions(runtime, principal, evidence, 1, "restored")
    set_availability(engine, principal, evidence, KnowledgeEvidenceAvailability.PERMISSION_LOST)
    restored = set_availability(
        engine, principal, evidence, KnowledgeEvidenceAvailability.AVAILABLE
    )
    assert restored.mutated_assertion_ids == ()
    assert evidence_row(engine, evidence)["availability_state"] == "available"
    assert lifecycles(engine, ids)[ids[0]][0] == "revalidation_required"


def test_product_shaped_evidence_carries_no_availability(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    capture_id, digest = runtime.capture(principal, "no-availability")
    runtime.create(
        principal, "klp04-capture-cited", evidence=(capture_evidence(capture_id, digest),)
    )
    with runtime.engine.connect() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
    with pytest.raises(ValueError, match="external"):
        set_availability(runtime.engine, principal, evidence, KnowledgeEvidenceAvailability.DELETED)


def test_more_than_128_links_set_the_pending_flag_and_the_drain_clears_it_after_marking(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-wide")
    ids = linked_assertions(runtime, principal, evidence, MAINTENANCE_BATCH + 1, "wide")

    result = set_availability(engine, principal, evidence, KnowledgeEvidenceAvailability.DELETED)
    assert (result.pending, result.mutated_assertion_ids, result.remaining) == (True, (), 129)
    row = evidence_row(engine, evidence)
    assert (row["availability_state"], row["availability_revalidation_pending"]) == (
        "deleted",
        True,
    )
    assert row["source_classification"] == "private_local"
    assert set(lifecycles(engine, ids).values()) == {("active", "private_local", 1)}
    assert "revalidation_required" not in mutation_kinds(engine, principal)
    # Reads fail closed while pending.
    assert withheld_remotely(runtime, principal, ids[0])
    assert withheld_remotely(runtime, principal, ids[-1])

    code, lines = run_cli(engine, principal, "drain-revalidation")
    assert (code, lines[-1]) == (EXIT_REMAINING, "remaining=1")
    assert mutation_kinds(engine, principal)["revalidation_required"] == MAINTENANCE_BATCH
    assert evidence_row(engine, evidence)["availability_revalidation_pending"] is True

    code, lines = run_cli(engine, principal, "drain-revalidation")
    assert (code, lines[-1]) == (EXIT_OK, "remaining=0")
    assert mutation_kinds(engine, principal)["revalidation_required"] == MAINTENANCE_BATCH + 1
    assert evidence_row(engine, evidence)["availability_revalidation_pending"] is False
    assert {state[0] for state in lifecycles(engine, ids).values()} == {"revalidation_required"}
    # Still withheld: the row itself is deleted. A further drain is a no-op.
    assert withheld_remotely(runtime, principal, ids[0])
    code, lines = run_cli(engine, principal, "drain-revalidation")
    assert (code, lines[-1]) == (EXIT_OK, "remaining=0")


def test_the_ingress_locks_c4b_then_c6_and_takes_no_entity_lock(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    """KLP-AC-142 order, read off the statements the ingress actually sends."""
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    evidence = seed_external_excerpt(engine, principal, profile, object_id="synthetic-order")
    linked_assertions(runtime, principal, evidence, 2, "order")
    statements: list[str] = []

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        set_availability(engine, principal, evidence, KnowledgeEvidenceAvailability.PERMISSION_LOST)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    def first(*needles: str) -> int:
        return next(
            index
            for index, statement in enumerate(statements)
            if all(needle in statement for needle in needles)
        )

    evidence_lock = first("FROM knowledge.knowledge_evidence_refs", "FOR UPDATE")
    subject_lock = first("FROM knowledge.knowledge_assertion_subject_locks", "FOR UPDATE")
    assertion_write = first("UPDATE knowledge.knowledge_assertions")
    mutation_write = first("INSERT INTO knowledge.knowledge_assertion_mutations")
    assert evidence_lock < subject_lock < assertion_write < mutation_write
    assert not any("pg_advisory" in statement for statement in statements)
    assert not any(
        "knowledge_evidence_refs" in statement and "FOR SHARE" in statement
        for statement in statements
    )
    assert (
        sum("FROM knowledge.knowledge_evidence_refs" in s and "FOR UPDATE" in s for s in statements)
        == 1
    )


def test_capture_archive_writes_nothing_in_knowledge(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    capture_id, digest = runtime.capture(principal, "archived-cited")
    created = runtime.create(
        principal, "klp04-archive-cited", evidence=(capture_evidence(capture_id, digest),)
    )
    before = counts(runtime.engine, principal)
    runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key="klp04-archive",
            reason="Synthetic knowledge archive",
        ),
        principal_id=principal,
    )
    assert counts(runtime.engine, principal) == before
    assert lifecycles(runtime.engine, [created["assertion_id"]])[created["assertion_id"]] == (
        "active",
        "private_local",
        1,
    )
    assert withheld_remotely(runtime, principal, created["assertion_id"])


# ---- KLP-AC-164: the source-classification ingress end to end -------------------------


def test_classify_evidence_is_batched_resumable_and_idempotent(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    engine = runtime.engine
    capture_id, digest = runtime.capture(principal, "classify-130")
    ids = [
        runtime.create(
            principal,
            f"klp04-classify-{index}",
            value=f"Synthetic classified requirement {index}",
            evidence=(capture_evidence(capture_id, digest),),
        )["assertion_id"]
        for index in range(MAINTENANCE_BATCH + 2)
    ]
    with engine.connect() as connection:
        (evidence,) = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalars()
    assert evidence_row(engine, evidence)["identity_kind"] == "capture"
    argv = ("classify-evidence", "--evidence-ref", evidence, "--classification", "restricted_local")

    code, lines = run_cli(engine, principal, *argv)
    assert (code, lines[-1]) == (EXIT_REMAINING, "remaining=2")
    assert mutation_kinds(engine, principal).get("classify") == MAINTENANCE_BATCH
    after_first = lifecycles(engine, ids)
    unclassified = [key for key, value in after_first.items() if value[1] == "private_local"]
    assert len(unclassified) == 2
    assert evidence_row(engine, evidence)["source_classification"] == "restricted_local"
    # KLP-AC-058: the evidence term already withholds the two not yet classified.
    assert all(withheld_remotely(runtime, principal, assertion_id) for assertion_id in unclassified)

    code, lines = run_cli(engine, principal, *argv)
    assert (code, lines[-1]) == (EXIT_OK, "remaining=0")
    assert mutation_kinds(engine, principal)["classify"] == MAINTENANCE_BATCH + 2

    code, lines = run_cli(engine, principal, *argv)
    assert (code, lines[-1]) == (EXIT_OK, "remaining=0")
    assert mutation_kinds(engine, principal) == {"create": 130, "classify": 130}

    final = lifecycles(engine, ids)
    assert set(final.values()) == {("active", "restricted_local", 2)}
    row = evidence_row(engine, evidence)
    assert (row["availability_revalidation_pending"], row["availability_state"]) == (
        False,
        "available",
    )
    events = maintenance_events(engine, principal)
    assert len(events) == 130
    assert {(e["event_kind"], tuple(e["changed_fields"]), e["classification"]) for e in events} == {
        ("state_changed", ("classification",), "restricted_local")
    }
    assert withheld_remotely(runtime, principal, ids[0])


def test_classify_evidence_refuses_an_unknown_or_foreign_row(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal, other = new_principal(), new_principal()
    profile = provision(runtime.engine, other, tmp_path)
    foreign = seed_external_excerpt(runtime.engine, other, profile, object_id="synthetic-foreign")
    for target in (foreign, "kaevd_SyntheticAbsent01"):
        code, lines = run_cli(
            runtime.engine,
            principal,
            "classify-evidence",
            "--evidence-ref",
            target,
            "--classification",
            "restricted_local",
        )
        assert code == 1
        assert lines[-1].startswith("refused")
    assert evidence_row(runtime.engine, foreign)["source_classification"] == "private_local"
