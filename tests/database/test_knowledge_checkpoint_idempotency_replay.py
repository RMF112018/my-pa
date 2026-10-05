"""KLP-WP-04 slice B3: the discovery checkpoint on a real database.

KLP-AC-073, 074, 094, 121, 126, 145 and 155 (whole), the checkpoint half of
KLP-AC-072 and the checkpoint-vs-disable race of KLP-AC-090. Marked `database`
(auto `database_clone`), routed to `database-current-head`.

Every checkpoint goes through `ApplicationService.invoke` as a bound discovery
client (REMOTE_CLIENT transport, the client in the discovery allowlist, the
checkpoint grant), against a source profile provisioned by the production
maintenance writer. Direct SQL appears only to read rows back, to recompute the
MAC independently, and to tamper with a stored MAC for the verification proof.

* KLP-AC-073 / 121: an advance is optimistic (`expected_version`, 0 = first)
  and separately idempotent (request ledger on (principal, client, key): an
  equal digest replays the stored answer and writes nothing, another digest is
  `conflict(idempotency_conflict)`); two concurrent first advances -- both
  observed blocked at the C4a profile lock -- give one `advanced` and one
  routed `checkpoint_conflict(stale_expected_version)`, never an internal
  error.
* KLP-AC-074: an advance names `external_run_id` and
  `submitted_candidate_count` and is refused `candidate_count_mismatch`
  unless exactly that many completed submissions exist for (client, run,
  profile, scope); the refusal is a completed request row.
* KLP-AC-094: replay of the current version returns the exact committed
  envelope; the advance to v redacts every older envelope of the binding in
  the same transaction, conflict rows included, and a historical replay
  returns the exact public receipt with `private_token_redacted=true`.
* KLP-AC-126: the stored MAC is HMAC-SHA256 under the signing key over the
  R6 section 7 object (recomputed here independently), stored outside the
  envelope; a tampered MAC or a changed key is never returned
  (`envelope_unverifiable`); the envelope reaches no audit row and no
  Record Event.
* KLP-AC-145: a stale `expected_version` from the same client/profile/scope
  returns the current id/version and the current verified envelope; another
  client naming the profile is `not_found(provenance)` and its own key
  namespace never reaches the first client's bytes.
* KLP-AC-155: after a seal increment, a stored old-seal envelope answers
  `envelope_unverifiable` (current id/version, no envelope, redacted); the
  production `redact-sealed --below-seal <n>` command redacts every older
  envelope; the client re-bootstraps by advancing from the current version,
  sealed under the new seal.
* KLP-AC-090 (checkpoint): a checkpoint waiting behind an uncommitted
  production disable (observed blocked at C4a) is refused
  `source_profile_inactive` once the disable commits.

Bounded / unproven: the `ON CONFLICT DO NOTHING` fallback on the checkpoint
insert (and the optimistic `version =` guard on the advance UPDATE) are
unreachable while the C4a `FOR NO KEY UPDATE` serializes every advance of a
binding; they are defense in depth and are not separately provable without a
pause point between the current-row read and the write.

Every identity here is synthetic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, select, text

from my_pa.application.commands import CheckpointKnowledgeDiscovery
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeCheckpointKind
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    knowledge_discovery_checkpoint_requests,
    knowledge_discovery_checkpoints,
    record_events,
)
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import WHEN, counts, new_principal
from tests.database.test_knowledge_assertion_submissions import (
    CHECKPOINT_SIGNING_KEY,
    CLIENT,
    OTHER_CLIENT,
    SubmitRuntime,
)
from tests.database.test_knowledge_source_profiles import EXIT_OK, run_cli

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

CHECKPOINT_GRANTS: Final = frozenset(
    {(Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION)}
)
#: The rotated key (synthetic, 33 octets) used with seal version 2.
ROTATED_KEY: Final = b"klp04-synthetic-checkpoint-key-02"


class CheckpointRuntime(SubmitRuntime):
    """`SubmitRuntime` with checkpoint helpers (the bound client, remote, granted)."""

    def command(
        self,
        profile: str,
        *,
        expected: int = 0,
        run: str = "run-1",
        count: int = 0,
        envelope: str = "synthetic-token-1",
        kind: KnowledgeCheckpointKind = KnowledgeCheckpointKind.DELTA_TOKEN,
        key: str | None = None,
    ) -> CheckpointKnowledgeDiscovery:
        return CheckpointKnowledgeDiscovery(
            source_profile_id=profile,
            expected_version=expected,
            external_run_id=run,
            submitted_candidate_count=count,
            checkpoint_kind=kind,
            private_envelope=envelope,
            idempotency_key=key or f"key-{expected}-{run}-{count}-{envelope}-{kind.value}",
        )

    def _remote(self, client: str) -> dict[str, object]:
        return {
            "transport": CaptureTransport.REMOTE_CLIENT,
            "grants": CHECKPOINT_GRANTS,
            "client_id": client,
        }

    def checkpoint(
        self,
        principal_id: str,
        profile: str,
        *,
        client: str = CLIENT,
        **fields: Any,  # noqa: ANN401 - the command keywords
    ) -> dict[str, Any]:
        return self.ok(
            self.command(profile, **fields), principal_id=principal_id, **self._remote(client)
        )

    def checkpoint_error(
        self,
        principal_id: str,
        profile: str,
        *,
        client: str = CLIENT,
        **fields: Any,  # noqa: ANN401 - the command keywords
    ) -> dict[str, Any]:
        return self.error(
            self.command(profile, **fields), principal_id=principal_id, **self._remote(client)
        )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[CheckpointRuntime]:
    composed = CheckpointRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _checkpoint_row(engine: Engine, principal: str) -> dict[str, Any] | None:
    c = knowledge_discovery_checkpoints
    with engine.connect() as connection:
        row = connection.execute(select(c).where(c.c.principal_id == principal)).one_or_none()
    return None if row is None else dict(row._mapping)


def _request_row(engine: Engine, request_id: str) -> dict[str, Any]:
    r = knowledge_discovery_checkpoint_requests
    with engine.connect() as connection:
        return dict(
            connection.execute(select(r).where(r.c.checkpoint_request_id == request_id))
            .one()
            ._mapping
        )


def _ledger(engine: Engine, principal: str) -> int:
    r = knowledge_discovery_checkpoint_requests
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).where(r.c.principal_id == principal)
            ).scalar_one()
        )


def _scope(engine: Engine, profile: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT scope_digest FROM knowledge.knowledge_discovery_source_profiles "
                    "WHERE source_profile_id = :s"
                ),
                {"s": profile},
            ).scalar_one()
        )


def independent_mac(
    key: bytes,
    *,
    principal: str,
    client: str,
    profile: str,
    scope: str,
    checkpoint_id: str,
    version: int,
    seal: int,
    envelope: str,
) -> str:
    """The R6 section 7 MAC, recomputed here without the production module."""
    message = json.dumps(
        {
            "v": 1,
            "principal_id": principal,
            "authenticated_client_id": client,
            "source_profile_id": profile,
            "scope_digest": scope,
            "checkpoint_id": checkpoint_id,
            "version": version,
            "seal_version": seal,
            "private_envelope_sha256": hashlib.sha256(envelope.encode("utf-8")).hexdigest(),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


# ---- KLP-AC-073 / 126: the first advance, sealed --------------------------------------


def test_a_first_advance_is_version_one_and_sealed_under_the_signing_key(
    runtime: CheckpointRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    envelope = "synthetic-delta-token-ÄÖ-" + "x" * 64
    result = runtime.checkpoint(principal, profile, envelope=envelope)
    assert result["outcome"] == "advanced"
    assert result["reason"] == "advanced"
    assert result["checkpoint_version"] == 1
    assert result["checkpoint_kind"] == "delta_token"
    assert result["private_envelope"] == envelope
    assert result["private_token_redacted"] is False
    row = _checkpoint_row(runtime.engine, principal)
    assert row is not None
    assert row["checkpoint_id"] == result["checkpoint_id"]
    assert row["private_envelope"] == envelope  # opaque: stored byte-exact
    assert row["seal_version"] == 1
    assert row["external_run_id"] == "run-1"
    assert row["envelope_mac"] == independent_mac(
        CHECKPOINT_SIGNING_KEY,
        principal=principal,
        client=CLIENT,
        profile=profile,
        scope=_scope(runtime.engine, profile),
        checkpoint_id=row["checkpoint_id"],
        version=1,
        seal=1,
        envelope=envelope,
    )
    assert envelope not in row["envelope_mac"]
    request = _request_row(runtime.engine, result["checkpoint_request_id"])
    assert request["state"] == "completed"
    assert (request["result_outcome"], request["result_reason"]) == ("advanced", "advanced")
    assert request["result_private_envelope"] == envelope
    assert request["result_envelope_mac"] == row["envelope_mac"]
    assert (request["result_seal_version"], request["expected_version"]) == (1, 0)
    assert (request["external_run_id"], request["submitted_candidate_count"]) == ("run-1", 0)


def test_an_advance_is_optimistic_on_the_current_version(runtime: CheckpointRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first = runtime.checkpoint(principal, profile, envelope="synthetic-token-a")
    second = runtime.checkpoint(principal, profile, expected=1, envelope="synthetic-token-b")
    assert second["outcome"] == "advanced"
    assert second["checkpoint_id"] == first["checkpoint_id"]
    assert second["checkpoint_version"] == 2
    # A version that never existed is stale too, and writes no checkpoint.
    ahead = runtime.checkpoint(principal, profile, expected=7, envelope="synthetic-token-c")
    assert (ahead["outcome"], ahead["reason"]) == ("checkpoint_conflict", "stale_expected_version")
    assert ahead["checkpoint_version"] == 2
    row = _checkpoint_row(runtime.engine, principal)
    assert row is not None
    assert (row["version"], row["private_envelope"]) == (2, "synthetic-token-b")
    # No checkpoint at all: any expected_version above 0 is stale, with nothing to return.
    other = new_principal()
    fresh = runtime.profile(other)
    nothing = runtime.checkpoint(other, fresh, expected=1)
    assert (nothing["outcome"], nothing["reason"]) == (
        "checkpoint_conflict",
        "stale_expected_version",
    )
    assert nothing["checkpoint_id"] is None
    assert nothing["private_envelope"] is None
    assert _checkpoint_row(runtime.engine, other) is None


# ---- KLP-AC-073: separately idempotent -------------------------------------------------


def test_the_same_key_replays_the_exact_answer_and_writes_nothing(
    runtime: CheckpointRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first = runtime.checkpoint(principal, profile, key="synthetic-key-1")
    ledger = _ledger(runtime.engine, principal)
    before = _checkpoint_row(runtime.engine, principal)
    assert runtime.checkpoint(principal, profile, key="synthetic-key-1") == first
    assert _ledger(runtime.engine, principal) == ledger
    assert _checkpoint_row(runtime.engine, principal) == before
    # The same key bound to another request: conflict, no write.
    error = runtime.checkpoint_error(
        principal, profile, key="synthetic-key-1", envelope="synthetic-token-changed"
    )
    assert error["code"] == "conflict"
    assert "idempotency_conflict" in error["safe_details"]
    assert _ledger(runtime.engine, principal) == ledger
    assert _checkpoint_row(runtime.engine, principal) == before


def test_another_kind_than_the_stored_one_is_refused_and_writes_nothing(
    runtime: CheckpointRuntime,
) -> None:
    """KLP-AC-102 (checkpoint): the refusal rolls the reservation back whole."""
    principal = new_principal()
    profile = runtime.profile(principal)
    runtime.checkpoint(principal, profile)
    ledger = _ledger(runtime.engine, principal)
    error = runtime.checkpoint_error(
        principal, profile, expected=1, kind=KnowledgeCheckpointKind.PAGE_CURSOR
    )
    assert error["code"] == "invalid_request"
    assert _ledger(runtime.engine, principal) == ledger
    row = _checkpoint_row(runtime.engine, principal)
    assert row is not None
    assert row["version"] == 1


# ---- KLP-AC-073 / 121: two concurrent first advances -----------------------------------


def test_two_concurrent_first_advances_give_one_success_and_one_routed_conflict(
    runtime: CheckpointRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    engine = runtime.engine
    with engine.connect() as holder:
        # Hold the profile row in the checkpoint's own C4a mode: both advances
        # reserve their request row (FK KEY SHARE is compatible) and then block.
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_discovery_source_profiles "
                "WHERE source_profile_id = :s FOR NO KEY UPDATE"
            ),
            {"s": profile},
        ).one()
        with ThreadPoolExecutor(max_workers=2) as pool:
            racers = [
                pool.submit(
                    runtime.invoke,
                    runtime.command(profile, envelope=f"synthetic-token-{name}"),
                    principal_id=principal,
                    transport=CaptureTransport.REMOTE_CLIENT,
                    grants=CHECKPOINT_GRANTS,
                    client_id=CLIENT,
                )
                for name in ("a", "b")
            ]
            _wait_for_waiters(engine, 2, *racers)
            holder.rollback()
            responses = [racer.result(timeout=DEADLINE_SECONDS) for racer in racers]
    assert all(response.error is None for response in responses), [
        response.error for response in responses
    ]
    results = sorted(
        (dict(response.result or {}) for response in responses),
        key=lambda result: result["outcome"],
    )
    advanced, conflict = results
    assert (advanced["outcome"], advanced["checkpoint_version"]) == ("advanced", 1)
    assert (conflict["outcome"], conflict["reason"]) == (
        "checkpoint_conflict",
        "stale_expected_version",
    )
    # The loser is the same bound client: it receives the winner's current state.
    assert conflict["checkpoint_id"] == advanced["checkpoint_id"]
    assert conflict["checkpoint_version"] == 1
    assert conflict["private_envelope"] == advanced["private_envelope"]
    assert _ledger(engine, principal) == 2


# ---- KLP-AC-074: the run's completed submission count ----------------------------------


def test_an_advance_is_refused_unless_the_run_count_matches(runtime: CheckpointRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    other_profile = runtime.profile(principal, scope="scope-b")
    org = runtime.entity(principal, "count")
    runtime.submit(principal, profile, subject_id=org, run="run-1", candidate="c1")
    runtime.submit(
        principal, profile, subject_id=org, run="run-1", candidate="c2", value="Second value"
    )
    # Neither another run nor another profile of the same client counts.
    runtime.submit(principal, profile, subject_id=org, run="run-2", candidate="c3")
    runtime.submit(principal, other_profile, subject_id=org, run="run-1", candidate="c4")
    for wrong in (0, 1, 3):
        refused = runtime.checkpoint(principal, profile, run="run-1", count=wrong)
        assert (refused["outcome"], refused["reason"]) == ("refused", "candidate_count_mismatch")
        assert refused["checkpoint_id"] is None
        assert refused["private_envelope"] is None
        row = _request_row(runtime.engine, refused["checkpoint_request_id"])
        assert row["state"] == "completed"
        assert (row["external_run_id"], row["submitted_candidate_count"]) == ("run-1", wrong)
        assert row["result_private_envelope"] is None
    assert _checkpoint_row(runtime.engine, principal) is None
    advanced = runtime.checkpoint(principal, profile, run="run-1", count=2)
    assert advanced["outcome"] == "advanced"


# ---- KLP-AC-094: current replay exact, history redacted --------------------------------


def test_an_advance_redacts_every_older_envelope_conflicts_included(
    runtime: CheckpointRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first = runtime.checkpoint(principal, profile, envelope="synthetic-token-v1", key="k1")
    stale = runtime.checkpoint(
        principal, profile, expected=0, envelope="synthetic-token-retry", key="k-stale"
    )
    assert stale["private_envelope"] == "synthetic-token-v1"  # lost-response recovery
    # Replay of the current version: the exact committed envelope.
    assert runtime.checkpoint(principal, profile, envelope="synthetic-token-v1", key="k1") == first
    second = runtime.checkpoint(
        principal, profile, expected=1, envelope="synthetic-token-v2", key="k2"
    )
    assert second["checkpoint_version"] == 2
    for request_id in (first["checkpoint_request_id"], stale["checkpoint_request_id"]):
        row = _request_row(runtime.engine, request_id)
        assert row["result_private_envelope"] is None
        assert row["result_envelope_mac"] is None
        assert row["private_token_redacted"] is True
        assert row["result_checkpoint_version"] == 1
        assert row["result_seal_version"] == 1  # the public receipt is unchanged
    # The historical replay: the exact public receipt, the token redacted.
    replayed = runtime.checkpoint(principal, profile, envelope="synthetic-token-v1", key="k1")
    assert replayed == {**first, "private_envelope": None, "private_token_redacted": True}
    replayed_stale = runtime.checkpoint(
        principal, profile, expected=0, envelope="synthetic-token-retry", key="k-stale"
    )
    assert replayed_stale == {**stale, "private_envelope": None, "private_token_redacted": True}
    # The current version still replays its exact envelope.
    assert (
        runtime.checkpoint(principal, profile, expected=1, envelope="synthetic-token-v2", key="k2")
        == second
    )
    current = _request_row(runtime.engine, second["checkpoint_request_id"])
    assert current["result_private_envelope"] == "synthetic-token-v2"


# ---- KLP-AC-145: lost-response recovery, never to another client -----------------------


def test_lost_response_recovery_returns_the_current_envelope_to_its_client_only(
    runtime: CheckpointRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    foreign_profile = runtime.profile(principal, client=OTHER_CLIENT, scope="scope-other")
    runtime.checkpoint(principal, profile, envelope="synthetic-token-v1")
    lost = runtime.checkpoint(principal, profile, expected=1, envelope="synthetic-token-v2")
    # The client never saw `lost`: it retries from its last known version with a
    # changed request (so a new transport key) and recovers the current state.
    recovered = runtime.checkpoint(principal, profile, expected=1, envelope="synthetic-token-v2b")
    assert (recovered["outcome"], recovered["reason"]) == (
        "checkpoint_conflict",
        "stale_expected_version",
    )
    assert recovered["checkpoint_id"] == lost["checkpoint_id"]
    assert recovered["checkpoint_version"] == 2
    assert recovered["private_envelope"] == "synthetic-token-v2"
    assert recovered["private_token_redacted"] is False
    resumed = runtime.checkpoint(principal, profile, expected=2, envelope="synthetic-token-v3")
    assert resumed["checkpoint_version"] == 3

    # Another bound client naming this profile: not found, no ledger row, no bytes.
    ledger = _ledger(runtime.engine, principal)
    error = runtime.checkpoint_error(principal, profile, client=OTHER_CLIENT, expected=1)
    assert error["code"] == "not_found"
    assert "synthetic-token" not in json.dumps(error)
    assert _ledger(runtime.engine, principal) == ledger
    # ... and reusing the first client's exact key on its own profile is its own request.
    mine = runtime.checkpoint(
        principal, foreign_profile, client=OTHER_CLIENT, expected=3, key="shared-key"
    )
    runtime.checkpoint(
        principal, profile, expected=3, envelope="synthetic-token-v4", key="shared-key"
    )
    assert mine["outcome"] == "checkpoint_conflict"
    assert mine["private_envelope"] is None  # its own (absent) checkpoint
    again = runtime.checkpoint(
        principal, foreign_profile, client=OTHER_CLIENT, expected=3, key="shared-key"
    )
    assert again == mine
    assert "synthetic-token-v4" not in json.dumps(again)


# ---- KLP-AC-126: verified before return ------------------------------------------------


def test_a_tampered_mac_is_never_returned_or_relied_on(runtime: CheckpointRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    runtime.checkpoint(principal, profile, envelope="synthetic-token-v1")
    with runtime.engine.begin() as connection:
        # The only UPDATE the advance guard admits is a one-version step.
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_discovery_checkpoints SET version = version + 1, "
                "private_envelope = 'synthetic-forged-token', envelope_mac = :m "
                "WHERE principal_id = :p"
            ),
            {"m": "0" * 64, "p": principal},
        )
    stale = runtime.checkpoint(principal, profile, expected=0, envelope="synthetic-probe")
    assert (stale["outcome"], stale["reason"]) == ("checkpoint_conflict", "envelope_unverifiable")
    assert stale["checkpoint_version"] == 2
    assert stale["private_envelope"] is None
    assert stale["private_token_redacted"] is True
    stored = _request_row(runtime.engine, stale["checkpoint_request_id"])
    assert stored["result_private_envelope"] is None
    # A matching advance does not build on a forged row under the current seal.
    matching = runtime.checkpoint(principal, profile, expected=2, envelope="synthetic-token-v3")
    assert (matching["outcome"], matching["reason"]) == (
        "checkpoint_conflict",
        "envelope_unverifiable",
    )
    row = _checkpoint_row(runtime.engine, principal)
    assert row is not None
    assert row["version"] == 2


def test_a_changed_key_without_a_seal_increment_returns_no_envelope(
    disposable_database: str,
) -> None:
    sealed = CheckpointRuntime(disposable_database)
    rekeyed = CheckpointRuntime(disposable_database, signing_key=ROTATED_KEY)
    try:
        principal = new_principal()
        profile = sealed.profile(principal)
        first = sealed.checkpoint(principal, profile, key="k1")
        replay = rekeyed.checkpoint(principal, profile, key="k1")
        assert replay["checkpoint_request_id"] == first["checkpoint_request_id"]
        assert (replay["outcome"], replay["reason"]) == (
            "checkpoint_conflict",
            "envelope_unverifiable",
        )
        assert (replay["checkpoint_id"], replay["checkpoint_version"]) == (
            first["checkpoint_id"],
            1,
        )
        assert replay["private_envelope"] is None
        assert replay["private_token_redacted"] is True
    finally:
        sealed.close()
        rekeyed.close()


def test_the_envelope_reaches_no_audit_row_and_no_record_event(
    runtime: CheckpointRuntime,
) -> None:
    """KLP-AC-072 / 126 (checkpoint): the token stays in the two checkpoint tables."""
    principal = new_principal()
    profile = runtime.profile(principal)
    envelope = "synthetic-unique-provider-token-7f3a"
    before = counts(runtime.engine, principal)
    runtime.checkpoint(principal, profile, envelope=envelope)
    runtime.checkpoint(principal, profile, expected=0, envelope="synthetic-probe")
    assert counts(runtime.engine, principal) == before  # no Knowledge row, no event
    with runtime.engine.connect() as connection:
        audit = connection.execute(
            select(audit_events).where(audit_events.c.principal_id == principal)
        ).all()
        events = connection.execute(
            select(record_events).where(record_events.c.principal_id == principal)
        ).all()
    assert len(audit) >= 2
    assert envelope not in repr([tuple(row) for row in audit])
    assert not events


# ---- KLP-AC-155: seal rotation end to end ----------------------------------------------


def test_seal_rotation_redacts_old_envelopes_and_the_client_rebootstraps(
    disposable_database: str,
) -> None:
    old = CheckpointRuntime(disposable_database)
    new = CheckpointRuntime(disposable_database, seal_version=2, signing_key=ROTATED_KEY)
    try:
        principal = new_principal()
        profile = old.profile(principal)
        engine = old.engine
        first = old.checkpoint(principal, profile, envelope="synthetic-token-s1", key="k1")
        stale = old.checkpoint(principal, profile, envelope="synthetic-token-x", key="k-stale")
        assert stale["private_envelope"] == "synthetic-token-s1"

        # Seal 2 configured, redaction not yet run: nothing sealed under 1 is served.
        replay = new.checkpoint(principal, profile, envelope="synthetic-token-s1", key="k1")
        assert (replay["outcome"], replay["reason"]) == (
            "checkpoint_conflict",
            "envelope_unverifiable",
        )
        assert (replay["checkpoint_id"], replay["checkpoint_version"]) == (
            first["checkpoint_id"],
            1,
        )
        assert replay["private_envelope"] is None
        assert replay["private_token_redacted"] is True

        # The operator command redacts every envelope sealed below 2.
        code, lines = run_cli(engine, principal, "redact-sealed", "--below-seal", "2")
        assert (code, lines) == (EXIT_OK, ["redacted          2"])
        for request_id in (first["checkpoint_request_id"], stale["checkpoint_request_id"]):
            row = _request_row(engine, request_id)
            assert (row["result_private_envelope"], row["private_token_redacted"]) == (None, True)
        historical = new.checkpoint(principal, profile, envelope="synthetic-token-s1", key="k1")
        assert historical == {**first, "private_envelope": None, "private_token_redacted": True}

        # The client's first call after rotation: envelope_unverifiable, once ...
        probe = new.checkpoint(principal, profile, expected=0, envelope="synthetic-probe")
        assert (probe["reason"], probe["checkpoint_version"]) == ("envelope_unverifiable", 1)
        assert probe["private_envelope"] is None
        # ... then it re-bootstraps from the current version, sealed under seal 2.
        rebuilt = new.checkpoint(principal, profile, expected=1, envelope="synthetic-token-s2")
        assert (rebuilt["outcome"], rebuilt["checkpoint_version"]) == ("advanced", 2)
        row = _checkpoint_row(engine, principal)
        assert row is not None
        assert row["seal_version"] == 2
        assert row["envelope_mac"] == independent_mac(
            ROTATED_KEY,
            principal=principal,
            client=CLIENT,
            profile=profile,
            scope=_scope(engine, profile),
            checkpoint_id=row["checkpoint_id"],
            version=2,
            seal=2,
            envelope="synthetic-token-s2",
        )
        recovered = new.checkpoint(principal, profile, expected=1, envelope="synthetic-again")
        assert recovered["private_envelope"] == "synthetic-token-s2"
        # The old seal can no longer read what the new one wrote.
        assert (
            old.checkpoint(principal, profile, expected=1, envelope="synthetic-old-probe")["reason"]
            == "envelope_unverifiable"
        )
    finally:
        old.close()
        new.close()


# ---- KLP-AC-090 (checkpoint): disable vs checkpoint (C4a) ------------------------------


def test_a_checkpoint_behind_an_uncommitted_disable_is_refused_once_it_commits(
    runtime: CheckpointRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    runtime.checkpoint(principal, profile)
    before = counts(runtime.engine, principal)
    disabled = threading.Event()
    release = threading.Event()

    def disable() -> None:
        # The production disable (maintenance transaction), paused before COMMIT.
        with knowledge_maintenance_transaction(runtime.engine) as repository:
            assert repository.disable_source_profile(principal, profile, at=WHEN) is not None
            disabled.set()
            assert release.wait(DEADLINE_SECONDS), "never released"

    with ThreadPoolExecutor(max_workers=2) as pool:
        disabling = pool.submit(disable)
        assert disabled.wait(DEADLINE_SECONDS)
        advancing = pool.submit(
            runtime.invoke,
            runtime.command(profile, expected=1, envelope="synthetic-token-v2"),
            principal_id=principal,
            transport=CaptureTransport.REMOTE_CLIENT,
            grants=CHECKPOINT_GRANTS,
            client_id=CLIENT,
        )
        _wait_for_waiters(runtime.engine, 1, advancing)  # blocked at C4a
        release.set()
        disabling.result(timeout=DEADLINE_SECONDS)
        response = advancing.result(timeout=DEADLINE_SECONDS)
    assert response.error is None, response.error
    result = dict(response.result or {})
    assert (result["outcome"], result["reason"]) == ("refused", "source_profile_inactive")
    row = _checkpoint_row(runtime.engine, principal)
    assert row is not None
    assert row["version"] == 1
    assert counts(runtime.engine, principal) == before
