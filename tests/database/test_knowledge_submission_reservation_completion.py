"""KLP-WP-03: explicit-create reservation, completion and permanent replay (DB).

KLP-AC-051 and KLP-AC-093 (the explicit-create slice). Marked `database`
(auto `database_clone`), routed to `database-current-head`.

* A local create requires a caller key of 1..128 characters; a remote create's
  key is the server-stamped payload hash.
* The submission row is `reserved` and then `completed` in one transaction; the
  deferred constraint trigger re-reads the *current* row at COMMIT and refuses a
  transaction that leaves it reserved.
* A retry with the same key and digest replays the stored completed result
  (submission, outcome, reason, assertion id and version, mutation,
  canonical owner) unchanged and writes nothing; only the read-only
  `current_lifecycle` is read at response time, so replay is permanent per key
  and visibly reports a later supersession.
* The same key with a different digest is `conflict(idempotency_conflict)` and
  writes nothing.

KLP-WP-04 slice B2 adds the autonomous-submit half (KLP-AC-051, 093, 102, 120,
149) and the WP-02 DEV-01 ledger mapping:

* KLP-AC-120 / 051: a submit replays by (principal, client, profile, run,
  candidate) over the frozen digest: the stored row holds the exact public
  result (assertion, mutation, proposal/case, owner, routed id) and a replay
  returns it unchanged, writes nothing and stages no event -- including after
  the profile is disabled or the head retired (N2: replay precedes admission).
* KLP-AC-149: the same candidate identity with another digest is
  `conflict(idempotency_conflict)` and writes no canonical row.
* KLP-AC-093 / 102: an autonomous reservation left reserved cannot commit, and
  a submit rolled back after its reservation leaves no row, link or event.
* N2 (create): a same-key create retry replays after its predicate head would
  now refuse it.
* The ledger triggers' 23514 / 23001 raised through the repository's
  translation are `KnowledgeLedgerInvariantError`.

KLP-WP-04 slice B3 adds the checkpoint-request half (KLP-AC-093, 102):

* a checkpoint request left `reserved` cannot commit (the deferred trigger
  re-reads the current row), and both checkpoint-request triggers' 23001
  through the repository's translation are `KnowledgeLedgerInvariantError`;
* a checkpoint that fails after its reservation (injected) rolls back whole:
  no request row, no checkpoint, no redaction.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, func, select, text
from sqlalchemy.exc import IntegrityError

from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.errors import InvalidRequestError
from my_pa.contracts.ports import KnowledgeLedgerInvariantError
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.knowledge_assertions import _translated
from my_pa.infrastructure.persistence.tables import (
    knowledge_discovery_checkpoint_requests,
    knowledge_discovery_checkpoints,
)
from tests.database.test_knowledge_assertion_repository import (
    KnowledgeRuntime,
    capture_evidence,
    counts,
    create_command,
    new_principal,
    submission_row,
)
from tests.database.test_knowledge_assertion_submissions import (
    CLIENT,
    PAYMENT,
    SubmitRuntime,
    archive_capture,
    external,
)
from tests.security.test_knowledge_assertion_disclosure import set_lifecycle

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def test_a_local_key_must_be_one_to_one_hundred_and_twenty_eight_characters(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    for key in ("", "k" * 129):
        with pytest.raises(InvalidRequestError):
            create_command(key, subject_id=principal)
    for key in ("k", "k" * 128):
        assert runtime.create(principal, key, value=f"Bound {len(key)}")["outcome"] == (
            "direct_created"
        )
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 2


def test_the_ledger_row_completes_in_the_same_transaction(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    result = runtime.create(principal, "klp03-complete")
    row = submission_row(runtime.engine, result["submission_id"])
    assert row["origin"] == "explicit_create"
    assert row["idempotency_key"] == "klp03-complete"
    assert row["submission_state"] == "completed"
    assert row["outcome"] == "direct_created"
    assert row["result_assertion_id"] == result["assertion_id"]
    assert row["result_mutation_id"] == result["mutation_id"]
    assert row["result_canonical_owner"] == "knowledge_assertion"
    assert row["completed_at"] is not None and row["result_digest"]
    assert row["authenticated_client_id"] is None


def test_a_transaction_that_leaves_a_reservation_cannot_commit(
    runtime: KnowledgeRuntime,
) -> None:
    """KLP-AC-093: the deferred guard re-reads the current row at COMMIT."""
    principal = new_principal()
    submission = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_SUBMISSION)
    with pytest.raises(IntegrityError, match="reserved"), runtime.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_submissions (principal_id, "
                "submission_id, origin, idempotency_key, origin_is_synthetic, subject_kind, "
                "subject_id, predicate_code, request_digest, submission_state, causal_depth, "
                "causal_root_submission_id, created_at) VALUES (:p, :s, 'explicit_create', "
                "'klp03-left-reserved', false, 'principal', :p, 'policy.requirement', :d, "
                "'reserved', 0, :s, now())"
            ),
            {"p": principal, "s": submission, "d": "a" * 64},
        )
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 0


def test_replay_is_the_stored_result_and_permanent_per_key(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    first = runtime.create(principal, "klp03-replay")
    before = counts(runtime.engine, principal)
    again = runtime.create(principal, "klp03-replay")
    assert again == first
    assert counts(runtime.engine, principal) == before
    # The assertion is superseded later; the key still replays the original
    # `direct_created`, and the one read-only field shows the current lifecycle.
    set_lifecycle(runtime.engine, principal, first, "superseded")
    later = runtime.create(principal, "klp03-replay")
    assert later == {**first, "current_lifecycle": "superseded"}
    assert later["outcome"] == "direct_created"


def test_a_different_digest_under_the_same_key_conflicts_and_writes_nothing(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    runtime.create(principal, "klp03-conflict", value="First statement")
    before = counts(runtime.engine, principal)
    error = runtime.error(
        create_command("klp03-conflict", subject_id=principal, value="Second statement"),
        principal_id=principal,
    )
    assert error["code"] == "conflict"
    assert "idempotency_conflict" in error["safe_details"]
    assert counts(runtime.engine, principal) == before


def test_a_whitespace_equivalent_value_is_the_same_digest(runtime: KnowledgeRuntime) -> None:
    """The digest is over the normalized value, so a re-sent equivalent replays."""
    principal = new_principal()
    first = runtime.create(principal, "klp03-normal", value="Gate  locked")
    assert runtime.create(principal, "klp03-normal", value=" Gate locked ") == first


def test_a_remote_create_key_is_the_server_stamped_payload_hash(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    caller = Principal(principal_id=principal, kind=PrincipalKind.OPERATOR, authenticated=True)
    grants = frozenset(
        {(Capability.KNOWLEDGE_ASSERTIONS_CREATE, Purpose.KNOWLEDGE_ASSERTION_AUTHORING)}
    )
    payload = {
        "subject_kind": "principal",
        "subject_id": principal,
        "predicate_code": "policy.requirement",
        "value": "A remote requirement",
    }
    answers = []
    for arguments in (payload, dict(reversed(list(payload.items())))):
        composed = compose_remote_arguments(
            capability_name=Capability.KNOWLEDGE_ASSERTIONS_CREATE.value,
            arguments={"payload": arguments},
            principal=caller,
            grants=grants,
        )
        metadata, command = normalize(Capability.KNOWLEDGE_ASSERTIONS_CREATE.value, composed)
        response = runtime.service.invoke(
            metadata,
            command,
            principal=caller,
            transport=CaptureTransport.REMOTE_CLIENT,
            capability_grants=grants,
            authenticated_client_id="klp03-remote-client",
        )
        assert response.error is None, response.error
        answers.append(dict(response.result or {}))
    assert answers[0] == answers[1]
    row = submission_row(runtime.engine, answers[0]["submission_id"])
    assert row["idempotency_key"].startswith("idk_")
    assert row["authenticated_client_id"] == "klp03-remote-client"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 1


# ---- KLP-WP-04 slice B2: autonomous submit -------------------------------------------


@pytest.fixture
def submitter(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def test_a_submit_row_stores_the_exact_replay_result(submitter: SubmitRuntime) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "stored")
    created = submitter.submit(principal, profile, subject_id=org)
    queued = submitter.submit(principal, profile, subject_id=org, candidate="c2", predicate=PAYMENT)
    for result in (created, queued):
        row = submission_row(submitter.engine, result["submission_id"])
        assert row["submission_state"] == "completed"
        assert row["outcome"] == result["outcome"]
        assert row["result_assertion_id"] == result["assertion_id"]
        assert row["result_mutation_id"] == result["mutation_id"]
        assert row["result_proposal_id"] == result["proposal_id"]
        assert row["result_review_case_id"] == result["review_case_id"]
        assert row["result_canonical_owner"] == result["canonical_owner"]
        assert row["result_routed_record_id"] == result["routed_record_id"]
        assert row["request_digest"] and row["result_digest"]


def test_a_submit_retry_replays_writes_nothing_and_stages_no_event(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "replay")
    first = submitter.submit(principal, profile, subject_id=org)
    before = counts(submitter.engine, principal)
    assert submitter.submit(principal, profile, subject_id=org) == first
    assert counts(submitter.engine, principal) == before
    # N2: the replay precedes every admission check -- a disabled profile still
    # replays the stored result, while a new candidate is refused.
    submitter.disable(principal, profile)
    assert submitter.submit(principal, profile, subject_id=org) == first
    refused = submitter.submit(principal, profile, subject_id=org, candidate="c-new")
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "source_profile_inactive"


def test_a_submit_replays_after_its_predicate_head_is_retired(submitter: SubmitRuntime) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "retired")
    first = submitter.submit(principal, profile, subject_id=org, predicate=PAYMENT)
    _retire(submitter, PAYMENT)
    assert submitter.submit(principal, profile, subject_id=org, predicate=PAYMENT) == first
    error = submitter.submit_error(
        principal, profile, subject_id=org, predicate=PAYMENT, candidate="c-after"
    )
    assert error["code"] == "invalid_request"


def test_a_create_replays_after_its_predicate_head_is_retired(submitter: SubmitRuntime) -> None:
    principal = new_principal()
    first = submitter.create(principal, "klp04-n2-create")
    _retire(submitter, "policy.requirement")
    assert submitter.create(principal, "klp04-n2-create") == first
    error = submitter.error(
        create_command("klp04-n2-other", subject_id=principal), principal_id=principal
    )
    assert error["code"] == "invalid_request"


def _retire(runtime: SubmitRuntime, predicate: str) -> None:
    with runtime.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_predicates SELECT predicate_code, "
                "predicate_version + 1, 'retired', value_type, cardinality, temporal_semantics, "
                "qualifier_rule, allowed_subject_kinds, allowed_entity_types, canonical_owner, "
                "autonomous_admission_policy, review_requirement, consequential_class, "
                "normalization_rule, classification_floor, conflict_rule, "
                "minimum_evidence_authority, fingerprint_version, now() FROM "
                "knowledge.knowledge_assertion_predicates WHERE predicate_code = :c "
                "ORDER BY predicate_version DESC LIMIT 1"
            ),
            {"c": predicate},
        )


def test_the_same_candidate_with_another_digest_conflicts_and_writes_nothing(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "conflict")
    submitter.submit(principal, profile, subject_id=org, value="First observation")
    before = counts(submitter.engine, principal)
    error = submitter.submit_error(principal, profile, subject_id=org, value="Second observation")
    assert error["code"] == "conflict"
    assert "idempotency_conflict" in error["safe_details"]
    assert counts(submitter.engine, principal) == before


def test_an_autonomous_reservation_left_reserved_cannot_commit(submitter: SubmitRuntime) -> None:
    """KLP-AC-093, autonomous origin: the deferred guard refuses the COMMIT."""
    principal = new_principal()
    profile = submitter.profile(principal)
    with submitter.engine.connect() as connection:
        scope = connection.execute(
            text(
                "SELECT scope_digest FROM knowledge.knowledge_discovery_source_profiles "
                "WHERE source_profile_id = :s"
            ),
            {"s": profile},
        ).scalar_one()
    submission = issue_identifier(IdKind.KNOWLEDGE_ASSERTION_SUBMISSION)
    with pytest.raises(IntegrityError, match="reserved"), submitter.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_assertion_submissions (principal_id, "
                "submission_id, origin, authenticated_client_id, source_profile_id, "
                "scope_digest, origin_is_synthetic, external_run_id, external_candidate_id, "
                "subject_kind, subject_id, predicate_code, request_digest, submission_state, "
                "causal_depth, causal_root_submission_id, created_at) VALUES (:p, :s, "
                "'autonomous_submit', :c, :f, :d, false, 'run-1', 'cand-1', 'principal', :p, "
                "'policy.requirement', :h, 'reserved', 0, :s, now())"
            ),
            {"p": principal, "s": submission, "c": CLIENT, "f": profile, "d": scope, "h": "a" * 64},
        )
    assert counts(submitter.engine, principal)["knowledge_assertion_submissions"] == 0


def test_an_archived_citation_is_a_born_refusal_that_writes_only_its_row(
    submitter: SubmitRuntime,
) -> None:
    """KLP-AC-102 (refusal half): a refused submit leaves no half-completed write.

    The rolled-back half -- a failure after C1 leaves no reservation, link or
    event -- is `test_a_failure_after_the_demotion_rolls_the_supersession_back`
    (injected failure) and the C4c fence race in
    `tests/concurrency/test_knowledge_capture_archive_race.py`.
    """
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "rollback")
    capture = submitter.capture(principal, "rollback")
    archive_capture(submitter, principal, capture[0])
    before = counts(submitter.engine, principal)
    result = submitter.submit(
        principal,
        profile,
        subject_id=org,
        evidence=(external("obj-rb"), capture_evidence(*capture, role="supporting")),
    )
    # The C2 lifecycle read sees the archive: a born refusal, its row only.
    assert result["outcome"] == "refused"
    assert result["reason"] == "capture_archived"
    after = counts(submitter.engine, principal)
    assert after["knowledge_assertion_submissions"] == before["knowledge_assertion_submissions"] + 1
    assert {k: v for k, v in after.items() if k != "knowledge_assertion_submissions"} == {
        k: v for k, v in before.items() if k != "knowledge_assertion_submissions"
    }


def test_a_ledger_trigger_refusal_is_the_invariant_error(submitter: SubmitRuntime) -> None:
    """WP-02 DEV-01: 23001 / 23514 from the submission ledger, through `_translated`."""
    principal = new_principal()
    result = submitter.create(principal, "klp04-ledger")
    with submitter.engine.connect() as connection:
        with pytest.raises(KnowledgeLedgerInvariantError):
            _translated(
                lambda: connection.execute(
                    text(
                        "UPDATE knowledge.knowledge_assertion_submissions SET reason = reason "
                        "WHERE submission_id = :s"
                    ),
                    {"s": result["submission_id"]},
                )
            )
        connection.rollback()
        with pytest.raises(KnowledgeLedgerInvariantError):
            _translated(
                lambda: connection.execute(
                    text(
                        "INSERT INTO knowledge.knowledge_assertion_submissions (principal_id, "
                        "submission_id, origin, idempotency_key, origin_is_synthetic, "
                        "subject_kind, subject_id, predicate_code, request_digest, "
                        "submission_state, outcome, reason, causal_depth, "
                        "causal_root_submission_id, result_canonical_owner, result_digest, "
                        "created_at, completed_at) VALUES (:p, :s, 'explicit_create', 'k', "
                        "false, 'principal', :p, 'policy.requirement', :h, 'completed', "
                        "'conflict', 'incompatible_current_fact', 0, :s, "
                        "'knowledge_assertion', :h, now(), now())"
                    ),
                    {
                        "p": principal,
                        "s": issue_identifier(IdKind.KNOWLEDGE_ASSERTION_SUBMISSION),
                        "h": "b" * 64,
                    },
                )
            )
        connection.rollback()


# ---- KLP-WP-04 slice B3: checkpoint requests -----------------------------------------


def _reserve_checkpoint_request(
    connection: Connection, principal: str, profile: str, scope: str
) -> str:
    request = issue_identifier(IdKind.KNOWLEDGE_DISCOVERY_CHECKPOINT_REQUEST)
    connection.execute(
        text(
            "INSERT INTO knowledge.knowledge_discovery_checkpoint_requests (principal_id, "
            "checkpoint_request_id, authenticated_client_id, source_profile_id, scope_digest, "
            "external_run_id, submitted_candidate_count, expected_version, idempotency_key, "
            "request_digest, state, created_at) VALUES (:p, :r, :c, :s, :d, 'run-1', 0, 0, "
            ":k, :h, 'reserved', now())"
        ),
        {
            "p": principal,
            "r": request,
            "c": CLIENT,
            "s": profile,
            "d": scope,
            "k": request,
            "h": "a" * 64,
        },
    )
    return request


def _profile_scope(runtime: SubmitRuntime, profile: str) -> str:
    with runtime.engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT scope_digest FROM knowledge.knowledge_discovery_source_profiles "
                    "WHERE source_profile_id = :s"
                ),
                {"s": profile},
            ).scalar_one()
        )


def _checkpoint_ledger(runtime: SubmitRuntime, principal: str) -> tuple[int, int]:
    with runtime.engine.connect() as connection:
        requests, checkpoints = (
            int(
                connection.execute(
                    select(func.count()).where(table.c.principal_id == principal)
                ).scalar_one()
            )
            for table in (knowledge_discovery_checkpoint_requests, knowledge_discovery_checkpoints)
        )
    return requests, checkpoints


def test_a_checkpoint_request_left_reserved_cannot_commit(submitter: SubmitRuntime) -> None:
    """KLP-AC-093, checkpoint requests: the deferred guard refuses the COMMIT."""
    principal = new_principal()
    profile = submitter.profile(principal)
    scope = _profile_scope(submitter, profile)
    with pytest.raises(IntegrityError, match="reserved"), submitter.engine.begin() as connection:
        _reserve_checkpoint_request(connection, principal, profile, scope)
    assert _checkpoint_ledger(submitter, principal) == (0, 0)
    # Through the repository's translation: the 23001 is the ledger invariant error.
    with submitter.engine.connect() as connection:
        _reserve_checkpoint_request(connection, principal, profile, scope)
        with pytest.raises(KnowledgeLedgerInvariantError):
            _translated(connection.commit)
    assert _checkpoint_ledger(submitter, principal) == (0, 0)


def test_a_checkpoint_request_lifecycle_refusal_is_the_invariant_error(
    submitter: SubmitRuntime,
) -> None:
    """WP-02 DEV-01: the request lifecycle guard's 23001, through `_translated`."""
    principal = new_principal()
    profile = submitter.profile(principal)
    scope = _profile_scope(submitter, profile)
    with submitter.engine.connect() as connection:
        for statement in (
            # Inserted completed (only `reserved` is insertable).
            "INSERT INTO knowledge.knowledge_discovery_checkpoint_requests (principal_id, "
            "checkpoint_request_id, authenticated_client_id, source_profile_id, scope_digest, "
            "external_run_id, submitted_candidate_count, expected_version, idempotency_key, "
            "request_digest, state, result_outcome, result_reason, created_at, completed_at) "
            "VALUES (:p, :r, :c, :s, :d, 'run-1', 0, 0, :r, :h, 'completed', 'refused', "
            "'source_profile_inactive', now(), now())",
        ):
            with pytest.raises(KnowledgeLedgerInvariantError):
                _translated(
                    lambda statement=statement: connection.execute(
                        text(statement),
                        {
                            "p": principal,
                            "r": issue_identifier(IdKind.KNOWLEDGE_DISCOVERY_CHECKPOINT_REQUEST),
                            "c": CLIENT,
                            "s": profile,
                            "d": scope,
                            "h": "c" * 64,
                        },
                    )
                )
            connection.rollback()
        # A reserved row DELETEd in its own transaction: never deleted.
        request = _reserve_checkpoint_request(connection, principal, profile, scope)
        with pytest.raises(KnowledgeLedgerInvariantError):
            _translated(
                lambda: connection.execute(
                    text(
                        "DELETE FROM knowledge.knowledge_discovery_checkpoint_requests "
                        "WHERE checkpoint_request_id = :r"
                    ),
                    {"r": request},
                )
            )
        connection.rollback()
    assert _checkpoint_ledger(submitter, principal) == (0, 0)


def test_a_checkpoint_failing_after_its_reservation_leaves_nothing(
    submitter: SubmitRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KLP-AC-102 (checkpoint): an injected failure after C1 rolls back whole."""
    from my_pa.application.commands import CheckpointKnowledgeDiscovery
    from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeCheckpointKind
    from my_pa.infrastructure.persistence import knowledge_assertions as persistence
    from tests.database.test_knowledge_checkpoint_idempotency_replay import CHECKPOINT_GRANTS

    principal = new_principal()
    profile = submitter.profile(principal)
    command = CheckpointKnowledgeDiscovery(
        source_profile_id=profile,
        expected_version=0,
        external_run_id="run-1",
        submitted_candidate_count=0,
        checkpoint_kind=KnowledgeCheckpointKind.SYNTHETIC,
        private_envelope="synthetic-token",
        idempotency_key="klp04-rollback",
    )
    remote: dict[str, Any] = {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "grants": CHECKPOINT_GRANTS,
        "client_id": CLIENT,
    }
    original = persistence._CheckpointAdvance._complete

    def fail_after_writing(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        original(self, *args, **kwargs)
        raise RuntimeError("injected failure after the reservation completed")

    monkeypatch.setattr(persistence._CheckpointAdvance, "_complete", fail_after_writing)
    error = submitter.error(command, principal_id=principal, **remote)
    assert error["code"] == "internal_error"
    assert _checkpoint_ledger(submitter, principal) == (0, 0)
    monkeypatch.undo()
    result = submitter.ok(command, principal_id=principal, **remote)
    assert result["outcome"] == "advanced"
    assert _checkpoint_ledger(submitter, principal) == (1, 1)
