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
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from tests.database.test_knowledge_assertion_repository import (
    KnowledgeRuntime,
    counts,
    create_command,
    new_principal,
    submission_row,
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
