"""KLP Step 8: the Knowledge Manager identity on a real database (spec item 12).

Marked `database` (auto `database_clone`), routed to `database-current-head`.

A Knowledge Manager is an ordinary broad ChatLLM client that the *server* binds
to Knowledge control-plane authority through
`MY_PA_KNOWLEDGE_MANAGER_OAUTH_CLIENT_IDS`. Every remote call here is walked,
not simulated: durable grant rows are written to the real remote-identity store,
resolved by `RemoteIdentityRepository.authenticate`, overlaid by the gateway's
`apps.gateway.remote_access_context` under `Settings` loaded from a synthetic
environment (manager in both the manager and the ChatLLM gateway allowlists),
and dispatched through the remote MCP boundary `adapters.mcp.server._answer`
into `ApplicationService.invoke` on the production SQL unit of work. The
manager's source profile is provisioned by the production operator command
(`apps/cli/knowledge_source_profiles.py`, `apply`). Direct SQL only reads rows
back.

* A manager with a durable `knowledge.assertions.submit` grant submits a
  synthetic source-backed assertion (`direct_created`); the same candidate
  replays the stored answer and writes no second row.
* A manager advances a checkpoint sealed under the one existing signing key
  (MAC recomputed independently), an identical retry replays it, and the same
  idempotency key with another request is `conflict(idempotency_conflict)`.
* A manager without the durable grants cannot submit or checkpoint: the
  overlay keeps only what was granted and the remote grant check refuses
  `unsupported`; nothing is written.
* A manager's `review.decide` persists `remote_operator_attested` /
  `remote_operator_review` / its OAuth client id, on an ordinary case and on a
  `requires_operator` case (accept, and correct_and_accept) -- the CHECK
  `knowledge_decision_channel_matches_authority` holds with no schema change.
* An ordinary ChatLLM client is denied promotion of a `requires_operator` case
  and writes no decision row; its ordinary decision is `ordinary_reviewer` /
  `remote_interactive`, never attested.
* An ordinary ChatLLM client holding stray submit/checkpoint grant rows still
  cannot use them: the overlay strips them, and a forged ceiling is refused by
  the second service gate; nothing is written.
* The manager's ordinary broad capabilities still work (one representative
  non-Knowledge write, `entities.create`).

`knowledge.assertions.create` semantics are out of scope (spec item 11, Step 9).
Every identity here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli.knowledge_source_profiles import (
    EXIT_OK,
    Runtime,
    run_knowledge_source_profiles,
)
from apps.gateway import remote_access_context
from sqlalchemy import Engine, func, select, update

from my_pa.adapters.mcp.remote import RemoteAccessContext
from my_pa.adapters.mcp.server import _answer
from my_pa.application.commands import CheckpointKnowledgeDiscovery
from my_pa.bootstrap.knowledge_discovery_profiles import knowledge_allowlists
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, is_write_capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeCheckpointKind
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_review_decisions,
    knowledge_assertion_submissions,
    knowledge_discovery_checkpoint_requests,
    knowledge_discovery_checkpoints,
)
from my_pa.infrastructure.security.remote_oauth import RemoteAuthContext
from tests.database.test_knowledge_assertion_repository import (
    WHEN,
    _find_id,
    counts,
    new_principal,
)
from tests.database.test_knowledge_assertion_review import (
    OPERATOR_CLIENT,
    ReviewRuntime,
    assertion_of,
    decisions_of,
    proposal_of,
)
from tests.database.test_knowledge_assertion_submissions import (
    CHECKPOINT_SIGNING_KEY,
    CLIENT,
    OTHER_CLIENT,
    SubmitRuntime,
    external,
)
from tests.database.test_knowledge_checkpoint_idempotency_replay import independent_mac

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

MANAGER: Final = "klp08-synthetic-knowledge-manager"
CHAT: Final = "klp08-synthetic-chatllm-client"
SCOPE: Final = "my-pa.read"
RESOURCE: Final = "https://mcp.example.invalid/mcp"
SUBMIT: Final = Capability.KNOWLEDGE_ASSERTIONS_SUBMIT
CHECKPOINT: Final = Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT
PAIR: Final = (SUBMIT, CHECKPOINT)
#: Seed S2: Knowledge-owned, organization entities only, direct-admissible.
OPERATING: Final = "organization.operating_requirement"
#: A representative slice of an ordinary broad ChatLLM grant set (durable rows).
BROAD: Final = (
    Capability.KNOWLEDGE_ASSERTIONS_READ,
    Capability.KNOWLEDGE_ASSERTIONS_LIST,
    Capability.KNOWLEDGE_ASSERTIONS_CREATE,
    Capability.REVIEW_LIST,
    Capability.REVIEW_DECIDE,
    Capability.RECORD_EVENTS_LIST,
    Capability.TASKS_READ,
    Capability.ENTITIES_CREATE,
    Capability.ENTITIES_GET,
)
#: The synthetic process environment the gateway's overlay reads.
ENVIRONMENT: Final = {
    "MY_PA_KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS": f"{CLIENT},{OTHER_CLIENT}",
    "MY_PA_KNOWLEDGE_OPERATOR_REVIEW_OAUTH_CLIENT_IDS": OPERATOR_CLIENT,
    "MY_PA_KNOWLEDGE_MANAGER_OAUTH_CLIENT_IDS": MANAGER,
    # The manager is an ordinary ChatLLM client too: the one permitted overlap.
    "MY_PA_MCP_CHATLLM_GATEWAY_OAUTH_CLIENT_IDS": f"{MANAGER},{CHAT}",
    "MY_PA_KNOWLEDGE_CHECKPOINT_SIGNING_KEY": CHECKPOINT_SIGNING_KEY.decode("utf-8"),
}


class ManagerRuntime(ReviewRuntime):
    """`ReviewRuntime` with the Knowledge Manager bound, over the real grant store."""

    def __init__(self, url: str, tmp: Path) -> None:
        SubmitRuntime.__init__(
            self,
            url,
            operator_review_client_ids=frozenset({OPERATOR_CLIENT}),
            manager_client_ids=frozenset({MANAGER}),
        )
        self.tmp = tmp
        self.settings: Settings = load_settings({"MY_PA_DATABASE_URL": url, **ENVIRONMENT})

    # -- durable grants and the gateway's resolution -----------------------------

    def register(self, oauth: str, capabilities: tuple[Capability, ...]) -> None:
        """One remote client and one durable grant row per permitted purpose."""
        with self.engine.begin() as connection:
            repository = RemoteIdentityRepository(connection)
            client = repository.register_client(
                oauth_client_id=oauth,
                client_name="synthetic Knowledge Manager test client",
                redirect_uris='["https://client.example/callback"]',
                registered_scopes=SCOPE,
                now=WHEN,
                writes_enabled=True,
            )
            for capability in capabilities:
                purposes: list[Purpose | None] = [*sorted(permitted_purposes(capability))]
                for purpose in purposes or [None]:
                    repository.grant(
                        remote_client_id=client,
                        external_scope=SCOPE,
                        capability=capability,
                        now=WHEN,
                        is_write=is_write_capability(capability),
                        resource=RESOURCE,
                        purpose=purpose,
                    )

    def resolve(self, oauth: str) -> RemoteAuthContext:
        """The authenticated grant state: real resolution, both write switches on."""
        with self.engine.begin() as connection:
            connection.execute(
                update(remote_security_controls).values(
                    remote_enabled=True, writes_enabled=True, updated_at=WHEN
                )
            )
            resolution = RemoteIdentityRepository(connection).authenticate(
                oauth_client_id=oauth,
                token_scopes=frozenset({SCOPE}),
                resource=RESOURCE,
                now=WHEN,
            )
        assert resolution is not None
        return RemoteAuthContext(
            principal=Principal(
                principal_id="prn_unused00000000000",
                kind=PrincipalKind.OPERATOR,
                authenticated=True,
            ),
            client_id=oauth,
            scopes=frozenset({SCOPE}),
            capabilities=frozenset(resolution.capabilities),
            write_allowed=resolution.write_allowed,
            capability_purposes=frozenset(resolution.capability_purposes),
        )

    def access(self, oauth: str) -> RemoteAccessContext:
        """The gateway's overlaid ceiling for `oauth` (`remote_access_context`)."""
        return remote_access_context(self.settings, self.service, self.resolve(oauth))

    def call(
        self,
        principal_id: str,
        oauth: str,
        capability: Capability,
        payload: Mapping[str, Any],
        *,
        overlay: bool = True,
    ) -> dict[str, Any]:
        """One remote MCP call through `_answer`, the client id from OAuth only.

        `overlay=False` forges the ceiling from the raw resolution (no overlay),
        to prove the second service gate still stands behind the first layer.
        """
        purposes = (
            self.access(oauth).capability_purposes
            if overlay
            else self.resolve(oauth).capability_purposes
        )
        rendered, failed, _image = _answer(
            self.service,
            Principal(principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True),
            capability.value,
            {"payload": dict(payload)},
            transport=CaptureTransport.REMOTE_CLIENT,
            allowed_capability_purposes=purposes,
            authenticated_client_id=oauth,
        )
        envelope: dict[str, Any] = json.loads(rendered)
        if failed and "error" not in envelope:
            # Refused at the remote boundary, before `invoke`: a bare problem body.
            return {"error": envelope, "boundary": True}
        assert failed == (envelope.get("error") is not None), envelope
        return envelope

    def provision(self, principal_id: str, *, scope: str, direct: bool) -> str:
        """The manager's source profile, through the production operator command."""
        path = self.tmp / f"profiles-{principal_id}-{scope}.json"
        entry: dict[str, object] = {
            "authenticated_client_id": MANAGER,
            "origin_system": "outlook_mail",
            "scope": f"synthetic-mailbox:{scope}",
            "authority_ceiling": "authoritative_source",
        }
        if direct:
            entry["direct_admission_enabled"] = True
            entry["read_only_proof_state"] = "proven"
        path.write_text(json.dumps({"version": 1, "profiles": [entry]}), encoding="utf-8")
        lines: list[str] = []
        code = run_knowledge_source_profiles(
            ["apply", "--file", str(path)],
            Runtime(
                engine=self.engine,
                principal_id=principal_id,
                allowlists=knowledge_allowlists(self.settings),
                clock=lambda: WHEN,
            ),
            out=lines.append,
        )
        assert code == EXIT_OK, lines
        return next(word for line in lines for word in line.split() if word.startswith("kdsp_"))


@pytest.fixture
def runtime(disposable_database: str, tmp_path: Path) -> Iterator[ManagerRuntime]:
    composed = ManagerRuntime(disposable_database, tmp_path)
    try:
        yield composed
    finally:
        composed.close()


def _ok(envelope: dict[str, Any], label: str) -> dict[str, Any]:
    assert envelope.get("error") is None, (label, envelope)
    return dict(envelope["result"])


def _code(envelope: dict[str, Any]) -> str:
    assert envelope.get("error") is not None, envelope
    return str(envelope["error"]["code"])


def _table_count(engine: Engine, table: Any, principal_id: str) -> int:  # noqa: ANN401
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(table).where(table.c.principal_id == principal_id)
            ).scalar_one()
        )


def _submission(profile: str, subject: str, *, candidate: str = "cand-1") -> dict[str, Any]:
    return {
        "source_profile_id": profile,
        "external_run_id": "run-1",
        "external_candidate_id": candidate,
        "subject_kind": "entity",
        "subject_id": subject,
        "predicate_code": OPERATING,
        "value": "Synthetic badge required on site",
        "evidence": [external("obj-klp08")],
    }


def _checkpoint(
    profile: str, *, count: int, envelope: str = "synthetic-klp08-token"
) -> dict[str, Any]:
    return {
        "source_profile_id": profile,
        "expected_version": 0,
        "external_run_id": "run-1",
        "submitted_candidate_count": count,
        "checkpoint_kind": "delta_token",
        "private_envelope": envelope,
    }


def _written(engine: Engine, principal_id: str) -> dict[str, int]:
    """Every row a submit or checkpoint could write, plus the Knowledge counts."""
    return {
        **counts(engine, principal_id),
        "submissions": _table_count(engine, knowledge_assertion_submissions, principal_id),
        "checkpoints": _table_count(engine, knowledge_discovery_checkpoints, principal_id),
        "checkpoint_requests": _table_count(
            engine, knowledge_discovery_checkpoint_requests, principal_id
        ),
    }


# ---- spec 12: manager can submit a synthetic source-backed assertion ------------------


def test_a_granted_manager_submits_a_source_backed_assertion_and_a_retry_replays(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(MANAGER, (*BROAD, *PAIR))
    context = runtime.access(MANAGER)
    assert {SUBMIT.value, CHECKPOINT.value} <= set(context.allowed_capabilities or ())
    principal = new_principal()
    profile = runtime.provision(principal, scope="ops-team", direct=True)
    entity = runtime.org(principal, "acme")
    payload = _submission(profile, entity)

    first = _ok(runtime.call(principal, MANAGER, SUBMIT, payload), "submit")
    assert first["outcome"] == "direct_created", first
    assert str(first["assertion_id"]).startswith("kasr_")
    fact = assertion_of(runtime.engine, first["assertion_id"])
    assert fact["subject_id"] == entity
    assert fact["predicate_code"] == OPERATING
    with runtime.engine.connect() as connection:
        submissions = (
            connection.execute(
                select(knowledge_assertion_submissions).where(
                    knowledge_assertion_submissions.c.principal_id == principal
                )
            )
            .mappings()
            .all()
        )
    (row,) = submissions
    assert row["authenticated_client_id"] == MANAGER
    assert row["source_profile_id"] == profile
    before = _written(runtime.engine, principal)

    again = _ok(runtime.call(principal, MANAGER, SUBMIT, payload), "replay")
    assert again == first
    assert _written(runtime.engine, principal) == before


# ---- spec 12 / item 5: manager can advance/replay a sealed checkpoint -----------------


def test_a_granted_manager_advances_a_sealed_checkpoint_and_a_retry_replays(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(MANAGER, (*BROAD, *PAIR))
    principal = new_principal()
    profile = runtime.provision(principal, scope="ops-team", direct=True)
    entity = runtime.org(principal, "acme")
    _ok(runtime.call(principal, MANAGER, SUBMIT, _submission(profile, entity)), "submit")

    advanced = _ok(
        runtime.call(principal, MANAGER, CHECKPOINT, _checkpoint(profile, count=1)), "advance"
    )
    assert (advanced["outcome"], advanced["checkpoint_version"]) == ("advanced", 1), advanced
    assert advanced["private_envelope"] == "synthetic-klp08-token"
    with runtime.engine.connect() as connection:
        row = (
            connection.execute(
                select(knowledge_discovery_checkpoints).where(
                    knowledge_discovery_checkpoints.c.principal_id == principal
                )
            )
            .mappings()
            .one()
        )
    assert row["authenticated_client_id"] == MANAGER
    assert row["seal_version"] == 1
    # The one existing seal: HMAC-SHA256 under the configured signing key.
    assert row["envelope_mac"] == independent_mac(
        CHECKPOINT_SIGNING_KEY,
        principal=principal,
        client=MANAGER,
        profile=profile,
        scope=row["scope_digest"],
        checkpoint_id=row["checkpoint_id"],
        version=1,
        seal=1,
        envelope="synthetic-klp08-token",
    )
    before = _written(runtime.engine, principal)
    replayed = _ok(
        runtime.call(principal, MANAGER, CHECKPOINT, _checkpoint(profile, count=1)), "replay"
    )
    assert replayed == advanced
    assert _written(runtime.engine, principal) == before

    # The same idempotency key bound to another request: conflict, nothing written.
    grants = runtime.access(MANAGER).capability_purposes
    remote: dict[str, object] = {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "grants": grants,
        "client_id": MANAGER,
    }

    def keyed(envelope: str) -> CheckpointKnowledgeDiscovery:
        return CheckpointKnowledgeDiscovery(
            source_profile_id=profile,
            expected_version=1,
            external_run_id="run-1",
            submitted_candidate_count=1,
            checkpoint_kind=KnowledgeCheckpointKind.DELTA_TOKEN,
            private_envelope=envelope,
            idempotency_key="klp08-synthetic-key",
        )

    second = runtime.ok(keyed("synthetic-klp08-token-2"), principal_id=principal, **remote)
    assert (second["outcome"], second["checkpoint_version"]) == ("advanced", 2), second
    settled = _written(runtime.engine, principal)
    conflict = runtime.error(keyed("synthetic-klp08-token-3"), principal_id=principal, **remote)
    assert conflict["code"] == "conflict"
    assert "idempotency_conflict" in conflict["safe_details"]
    assert _written(runtime.engine, principal) == settled


# ---- spec 12: manager without the durable grants cannot use them ----------------------


def test_a_manager_without_the_durable_grants_cannot_submit_or_checkpoint(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(MANAGER, BROAD)
    context = runtime.access(MANAGER)
    allowed = set(context.allowed_capabilities or ())
    # The additive overlay keeps every granted name and adds none.
    assert allowed == {capability.value for capability in BROAD}
    principal = new_principal()
    profile = runtime.provision(principal, scope="ops-team", direct=True)
    entity = runtime.org(principal, "acme")
    before = _written(runtime.engine, principal)
    submit = runtime.call(principal, MANAGER, SUBMIT, _submission(profile, entity))
    assert _code(submit) == "unsupported", submit
    checkpoint = runtime.call(principal, MANAGER, CHECKPOINT, _checkpoint(profile, count=0))
    assert _code(checkpoint) == "unsupported", checkpoint
    # Refused by the remote grant check, before the service is ever invoked.
    assert submit.get("boundary") is True and checkpoint.get("boundary") is True
    assert _written(runtime.engine, principal) == before


# ---- spec 12: an ordinary ChatLLM client still cannot use submit/checkpoint ------------


def test_an_ordinary_chatllm_client_with_stray_grants_cannot_submit_or_checkpoint(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(CHAT, (*BROAD, *PAIR))
    raw = runtime.resolve(CHAT)
    assert {SUBMIT, CHECKPOINT} <= set(raw.capabilities), "the stray rows resolve"
    context = runtime.access(CHAT)
    assert not {SUBMIT.value, CHECKPOINT.value} & set(context.allowed_capabilities or ())
    principal = new_principal()
    # A profile naming the ChatLLM client is refused by the operator command, so
    # the stray client would aim at the manager's profile; it must never reach it.
    profile = runtime.provision(principal, scope="ops-team", direct=True)
    entity = runtime.org(principal, "acme")
    before = _written(runtime.engine, principal)
    for overlay in (True, False):
        submit = runtime.call(
            principal, CHAT, SUBMIT, _submission(profile, entity), overlay=overlay
        )
        assert _code(submit) == "unsupported", (overlay, submit)
        checkpoint = runtime.call(
            principal, CHAT, CHECKPOINT, _checkpoint(profile, count=0), overlay=overlay
        )
        assert _code(checkpoint) == "unsupported", (overlay, checkpoint)
        # Overlaid: the grant check refuses at the boundary. Forged ceiling: the
        # call reaches `invoke`, and the second service gate refuses it there.
        assert submit.get("boundary", False) is overlay
        assert checkpoint.get("boundary", False) is overlay
    assert _written(runtime.engine, principal) == before


# ---- spec 12 / item 6: manager Review authority ---------------------------------------


def _ordinary_case(runtime: ManagerRuntime, principal: str) -> str:
    """One `requires_review` case filed by the discovery client's production submit."""
    profile = runtime.profile(principal, direct=False, scope="review-ordinary")
    entity = runtime.org(principal, "acme")
    queued = runtime.queue(
        principal, profile, entity, predicate=OPERATING, value="Synthetic badge required"
    )
    case = str(queued["review_case_id"])
    assert proposal_of(runtime.engine, case)["review_requirement"] == "requires_review"
    return case


def _operator_case(runtime: ManagerRuntime, principal: str, *, candidate: str) -> str:
    """One `requires_operator` case (seed S1 payment terms, consequential)."""
    profile = runtime.profile(principal, scope=f"review-operator-{candidate}")
    entity = runtime.org(principal, f"acme-{candidate}")
    queued = runtime.queue(principal, profile, entity, candidate=candidate)
    case = str(queued["review_case_id"])
    assert proposal_of(runtime.engine, case)["review_requirement"] == "requires_operator"
    return case


def _decide(case: str, disposition: str, **extra: object) -> dict[str, Any]:
    return {
        "review_case_id": case,
        "expected_review_version": 0,
        "disposition": disposition,
        **extra,
    }


def _assert_attested(runtime: ManagerRuntime, case: str, disposition: str) -> None:
    (decision,) = decisions_of(runtime.engine, case)
    assert decision["operator_authority_class"] == "remote_operator_attested"
    assert decision["decision_channel"] == "remote_operator_review"
    assert decision["authenticated_client_id"] == MANAGER
    assert decision["disposition"] == disposition


def test_a_manager_decides_an_ordinary_case_as_remote_operator_attested(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(MANAGER, BROAD)
    principal = new_principal()
    case = _ordinary_case(runtime, principal)
    decided = _ok(
        runtime.call(principal, MANAGER, Capability.REVIEW_DECIDE, _decide(case, "accept")),
        "decide",
    )
    assert decided["proposal_state"] == "accepted"
    _assert_attested(runtime, case, "accept")


def test_a_manager_accepts_and_corrects_requires_operator_cases_as_attested(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(MANAGER, BROAD)
    principal = new_principal()
    accept_case = _operator_case(runtime, principal, candidate="cand-accept")
    accepted = _ok(
        runtime.call(principal, MANAGER, Capability.REVIEW_DECIDE, _decide(accept_case, "accept")),
        "accept",
    )
    assert accepted["proposal_state"] == "accepted"
    assert str(accepted["assertion_id"]).startswith("kasr_")
    _assert_attested(runtime, accept_case, "accept")

    correct_case = _operator_case(runtime, principal, candidate="cand-correct")
    corrected = _ok(
        runtime.call(
            principal,
            MANAGER,
            Capability.REVIEW_DECIDE,
            _decide(
                correct_case,
                "correct_and_accept",
                correction_patch={"value": "Synthetic net 45 terms"},
            ),
        ),
        "correct_and_accept",
    )
    assert corrected["proposal_state"] == "corrected_accepted"
    assert assertion_of(runtime.engine, corrected["assertion_id"])["value_text"] == (
        "Synthetic net 45 terms"
    )
    _assert_attested(runtime, correct_case, "correct_and_accept")


def test_an_ordinary_remote_client_is_denied_promotion_and_is_never_attested(
    runtime: ManagerRuntime,
) -> None:
    runtime.register(CHAT, BROAD)
    principal = new_principal()
    case = _operator_case(runtime, principal, candidate="cand-chat")
    before = counts(runtime.engine, principal)
    for disposition, extra in (
        ("accept", {}),
        ("correct_and_accept", {"correction_patch": {"value": "Synthetic net 45 terms"}}),
    ):
        refused = runtime.call(
            principal, CHAT, Capability.REVIEW_DECIDE, _decide(case, disposition, **extra)
        )
        assert _code(refused) == "denied", refused
        assert "boundary" not in refused, "denied by the Review authority, not the grant check"
        assert refused["error"]["safe_details"] == ["disposition"]
    assert decisions_of(runtime.engine, case) == []
    assert counts(runtime.engine, principal) == before
    with runtime.engine.connect() as connection:
        assert (
            connection.execute(
                select(func.count()).where(
                    knowledge_assertion_review_decisions.c.principal_id == principal
                )
            ).scalar_one()
            == 0
        )
    # Its ordinary decision is ordinary_reviewer / remote_interactive, never attested.
    ordinary = _ordinary_case(runtime, principal)
    _ok(runtime.call(principal, CHAT, Capability.REVIEW_DECIDE, _decide(ordinary, "accept")), "ok")
    (decision,) = decisions_of(runtime.engine, ordinary)
    assert decision["operator_authority_class"] == "ordinary_reviewer"
    assert decision["decision_channel"] == "remote_interactive"
    assert decision["authenticated_client_id"] == CHAT


# ---- spec 12: manager keeps its ordinary broad capability set -------------------------


def test_a_manager_keeps_an_ordinary_non_knowledge_write(runtime: ManagerRuntime) -> None:
    runtime.register(MANAGER, (*BROAD, *PAIR))
    # The additive overlay hands the manager every granted name, broad and Knowledge.
    allowed = set(runtime.access(MANAGER).allowed_capabilities or ())
    assert allowed == {capability.value for capability in (*BROAD, *PAIR)}
    principal = new_principal()
    created = _ok(
        runtime.call(
            principal,
            MANAGER,
            Capability.ENTITIES_CREATE,
            {"entity_type": "organization", "display_name": "Synthetic Manager Org"},
        ),
        "entities.create",
    )
    entity_id = _find_id(created, "ent_")
    assert entity_id is not None, created
    # The write is committed and readable by the same OAuth-bound manager.
    read = _ok(
        runtime.call(principal, MANAGER, Capability.ENTITIES_GET, {"entity_id": entity_id}),
        "entities.get",
    )
    assert _find_id(read, "ent_") == entity_id
