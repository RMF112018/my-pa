"""KLP-WP-07: the internal synthetic Knowledge vertical slice (KLP-AC-140, KLP-AC-154).

Every node is `@pytest.mark.database` + `@pytest.mark.e2e`, routed to
`repository-checks / database-e2e`.

**The slice is walked, not simulated** (the `test_vertical_slice.py`
discipline). The composition root is `bootstrap.gateway.build_gateway_runtime`
over `Settings` loaded from this test's own environment -- the one
`apps/gateway.py` is handed -- and every request crosses the MCP boundary
function `adapters.mcp.server._answer` (the one `repository-checks /
database-e2e` prints as `answer=`): a local stdio caller with a full envelope,
or a remote caller whose grant ceiling is resolved by `apps.gateway.
remote_access_context` (the one Knowledge deny overlay) from an authenticated
`RemoteAuthContext`. Nothing calls a repository or writes a Knowledge row
directly; SQL appears only to read rows back and, in the lock proof, to hold
table locks from a third session.

**The synthetic source profile and its guard.** The profile is
`tests/end_to_end/knowledge_synthetic_source_profile.json`, provisioned by the
real operator command (`apps/cli/knowledge_source_profiles.py apply --file`,
its `main`, in process, against the test database). It is guarded three ways,
each proven below:

1. its `origin_system` is `synthetic`, so the database CHECK
   `knowledge_profile_synthetic_follows_origin` makes it `is_synthetic` and every
   external evidence row it supplies is `synthetic_source` / `synthetic_test` --
   distinguishable from real data -- while the facts it admits keep their
   predicate's `private_local` floor (a synthetic source never lowers a fact);
2. its client id (`klp07-synthetic-discovery-client`) is server-owned and
   allowlisted ONLY in this module's composition
   (`MY_PA_KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS` set by the fixture): the
   default `Settings` binds no discovery client, the id appears in no file
   under `ops/`, `src/`, `apps/` or `docker/`, and applying the committed file
   under a default composition is refused with no row;
3. a client that is not allowlisted is refused at provisioning (exit 1, no
   row) and at submit -- the overlay strips the discovery pair from its grant
   ceiling, and even a forged ceiling is refused by the service's second gate
   -- with no submission row.

**What is walked (KLP-AC-140).** Autonomous submit with every outcome family
the seeds produce (direct, review_queued, domain-owned routed and no-intake,
refused); the discovery checkpoint; Knowledge Review list (the case row is the
detail: it carries the read-only candidate, R6 10.1) and decide by the
operator-review client (accept, reject and defer -- the workbench's
dispositions); Knowledge read and search; `context.prepare` with the
`knowledge_assertion` plane locally, remotely with the
`knowledge.assertions.search` + `knowledge_assertion_read` pair, and withheld
without it; Record Event list and provenance for the resulting events; and the
replay of retried submits. No external connector module is imported by the
composition and no Python-level network connection is attempted.

**Routing at the slice (KLP-AC-154).** All eight seeds route as R6 11.6
states through the real transaction, including `project.critical_date`
routed/invalid/absent and `entity.communication_preference` with Relationship
Memory composed and capture- or external-only evidence and with it not
composed (WP-07 DEV-01: `domain_owned_no_intake` in every case, because no
reviewed RM intake can faithfully take a Knowledge candidate). A routed
submission takes no Knowledge C5-C8 lock: it completes while a third session
holds the proposal, subject-lock, assertion, mutation and link tables in SHARE
mode (no write) with every existing row `FOR UPDATE` -- including the
subject-lock row of the very same key -- while a Knowledge-path submit on that
key waits (the control).

Every identity and value here is synthetic.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Any, Final

import apps.cli.knowledge_source_profiles as provisioner
import pytest
from apps.gateway import remote_access_context
from sqlalchemy import Engine, func, select, text

from my_pa.adapters.mcp.server import _answer
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.knowledge_discovery_profiles import (
    DISCOVERY_PROFILE,
    KNOWLEDGE_CLIENT_PROFILES,
    OPERATOR_REVIEW_PROFILE,
)
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    knowledge_assertion_evidence_links,
    knowledge_assertion_mutations,
    knowledge_assertion_proposals,
    knowledge_assertion_subject_locks,
    knowledge_assertion_submissions,
    knowledge_assertions,
    knowledge_discovery_source_profiles,
    knowledge_evidence_refs,
    record_events,
    relationship_memory_versions,
)
from my_pa.infrastructure.security.remote_oauth import RemoteAuthContext

pytestmark = [
    pytest.mark.database,
    pytest.mark.e2e,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

ROOT: Final = Path(__file__).resolve().parents[2]
PROFILE_FILE: Final = ROOT / "tests" / "end_to_end" / "knowledge_synthetic_source_profile.json"
MATRIX_PATH: Final = ROOT / "tests" / "architecture" / "klp_implementation_matrix_r6.json"

#: The server-owned synthetic discovery client: allowlisted only by `compose` below.
DISCOVERY_CLIENT: Final = "klp07-synthetic-discovery-client"
#: The synthetic operator-review client (`knowledge-operator-review-v1`).
OPERATOR_CLIENT: Final = "klp07-synthetic-operator-review-client"
#: An unbound remote reader holding the context grant pair.
READER_CLIENT: Final = "klp07-synthetic-context-reader"
#: An unbound remote client that is in no Knowledge allowlist.
ROGUE_CLIENT: Final = "klp07-synthetic-unlisted-client"
#: A synthetic 32-octet checkpoint signing key (never a real key).
SIGNING_KEY: Final = "klp07-synthetic-checkpoint-key-0"

PAYMENT: Final = "organization.payment_terms"
OPERATING: Final = "organization.operating_requirement"
POLICY: Final = "policy.requirement"
LESSON: Final = "process.lesson_learned"
DECISION: Final = "project.decision"
CRITICAL: Final = "project.critical_date"
FINANCIAL: Final = "project.financial_fact"
PREFERENCE: Final = "entity.communication_preference"
CRITICAL_VALUE: Final = "2026-11-20T00:00:00+00:00"

#: The context grant pair (KLP-AC-055) plus `context.prepare` itself.
CONTEXT_PAIR: Final = frozenset(
    {
        (Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION),
        (Capability.KNOWLEDGE_ASSERTIONS_SEARCH, Purpose.KNOWLEDGE_ASSERTION_READ),
    }
)
#: The Knowledge tables of lock steps C5-C8 (R6 section 8.1).
C5_C8_TABLES: Final = (
    "knowledge.knowledge_assertion_proposals",
    "knowledge.knowledge_assertion_subject_locks",
    "knowledge.knowledge_assertions",
    "knowledge.knowledge_assertion_mutations",
    "knowledge.knowledge_assertion_evidence_links",
)
#: Seconds a routed submit may take while C5-C8 are held (it waits for none).
ROUTED_DEADLINE: Final = 20.0
#: Seconds the control submit is observed to be still waiting.
CONTROL_WAIT: Final = 2.0


def _purposed(capabilities: frozenset[Capability]) -> frozenset[tuple[Capability, Purpose | None]]:
    return frozenset(
        (capability, purpose)
        for capability in capabilities
        for purpose in permitted_purposes(capability)
    )


# ---- no network ---------------------------------------------------------------------


@dataclass
class NetworkGuard:
    """Refuses (and records) every Python-level socket connect that is not loopback."""

    attempts: list[str] = field(default_factory=list)

    def check(self, address: object) -> None:
        host = address[0] if isinstance(address, tuple) and address else address
        if isinstance(host, str) and host in {"127.0.0.1", "::1", "localhost"}:
            return
        if isinstance(host, bytes | str) and not isinstance(address, tuple):
            return  # an AF_UNIX path
        self.attempts.append(repr(type(host)))
        raise OSError("the synthetic slice refuses a non-loopback connection")


@pytest.fixture
def network(monkeypatch: pytest.MonkeyPatch) -> NetworkGuard:
    guard = NetworkGuard()
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def connect(self: socket.socket, address: Any) -> None:  # noqa: ANN401
        guard.check(address)
        original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:  # noqa: ANN401
        guard.check(address)
        return original_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    return guard


# ---- the composition ------------------------------------------------------------------


class Slice:
    """One composed gateway and the callers that reach it through `_answer`."""

    def __init__(self, runtime: GatewayRuntime, settings: Settings) -> None:
        self.runtime = runtime
        self.settings = settings
        self.engine: Engine = runtime.work_engine
        assert runtime.principal is not None
        self.principal = runtime.principal
        self.principal_id = runtime.principal.principal_id
        self._sequence = count(1)

    # -- the callers --------------------------------------------------------------

    def local(self, capability: Capability, payload: Mapping[str, Any]) -> dict[str, Any]:
        """A local stdio MCP caller: a full envelope, no grant ceiling, no client."""
        document = {
            "request_id": f"req-klp07-{next(self._sequence)}",
            "purpose": sorted(permitted_purposes(capability))[0].value,
            "principal_id": self.principal_id,
            "requested_at": format_rfc3339(datetime.now(UTC)),
            "payload": dict(payload),
        }
        rendered, failed, _image = _answer(
            self.runtime.service, self.principal, capability.value, document
        )
        envelope: dict[str, Any] = json.loads(rendered)
        assert failed == (envelope.get("error") is not None), envelope
        return envelope

    def access(
        self, client: str, grants: frozenset[tuple[Capability, Purpose | None]]
    ) -> tuple[frozenset[str], frozenset[tuple[Capability, Purpose | None]]]:
        """The overlaid remote ceiling of one authenticated client (the gateway's resolver)."""
        context = remote_access_context(
            self.settings,
            self.runtime.service,
            RemoteAuthContext(
                principal=self.principal,
                client_id=client,
                scopes=frozenset({"my-pa.mcp"}),
                capabilities=frozenset(capability for capability, _ in grants),
                write_allowed=True,
                capability_purposes=grants,
            ),
        )
        assert context.allowed_capabilities is not None
        assert context.capability_purposes is not None
        return context.allowed_capabilities, context.capability_purposes

    def remote(
        self,
        client: str,
        grants: frozenset[tuple[Capability, Purpose | None]],
        capability: Capability,
        payload: Mapping[str, Any],
        *,
        overlay: bool = True,
    ) -> dict[str, Any]:
        """A remote MCP tool call: published only if the overlaid ceiling names it."""
        if overlay:
            allowed, purposes = self.access(client, grants)
            if capability.value not in allowed:
                return {"result": None, "error": {"code": "not_published"}}
        else:
            purposes = grants
        rendered, failed, _image = _answer(
            self.runtime.service,
            self.principal,
            capability.value,
            {"payload": dict(payload)},
            transport=CaptureTransport.REMOTE_CLIENT,
            allowed_capability_purposes=purposes,
            authenticated_client_id=client,
        )
        envelope: dict[str, Any] = json.loads(rendered)
        assert failed == (envelope.get("error") is not None), envelope
        return envelope

    # -- the three Knowledge clients ----------------------------------------------

    def discovery(self, capability: Capability, payload: Mapping[str, Any]) -> dict[str, Any]:
        grants = _purposed(KNOWLEDGE_CLIENT_PROFILES[DISCOVERY_PROFILE])
        return self.remote(DISCOVERY_CLIENT, grants, capability, payload)

    def reviewer(self, capability: Capability, payload: Mapping[str, Any]) -> dict[str, Any]:
        grants = _purposed(KNOWLEDGE_CLIENT_PROFILES[OPERATOR_REVIEW_PROFILE])
        return self.remote(OPERATOR_CLIENT, grants, capability, payload)

    def reader(
        self,
        payload: Mapping[str, Any],
        grants: frozenset[tuple[Capability, Purpose | None]] = CONTEXT_PAIR,
    ) -> dict[str, Any]:
        return self.remote(READER_CLIENT, grants, Capability.CONTEXT_PREPARE, payload)

    # -- seeding through the owning planes' own capabilities -----------------------

    def ok(self, envelope: Mapping[str, Any], what: str) -> dict[str, Any]:
        assert envelope.get("error") is None, (what, envelope.get("error"))
        result = envelope.get("result")
        assert isinstance(result, dict) and result, (what, envelope)
        return result

    def created_id(self, capability: Capability, payload: Mapping[str, Any], prefix: str) -> str:
        result = self.ok(self.local(capability, payload), capability.value)
        found = _find_id(result, prefix)
        assert found is not None, (capability.value, prefix)
        return found

    def submit(
        self,
        profile: str,
        *,
        run: str,
        candidate: str,
        subject_kind: str,
        subject_id: str,
        predicate: str,
        value: str,
        evidence: list[dict[str, object]],
        **extra: object,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_profile_id": profile,
            "external_run_id": run,
            "external_candidate_id": candidate,
            "subject_kind": subject_kind,
            "subject_id": subject_id,
            "predicate_code": predicate,
            "value": value,
            "evidence": evidence,
            **extra,
        }
        return self.ok(
            self.discovery(Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, payload), f"submit {predicate}"
        )

    # -- reading rows back ----------------------------------------------------------

    def count(self, table: Any, *criteria: Any) -> int:  # noqa: ANN401 - a Table
        with self.engine.connect() as connection:
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.principal_id == self.principal_id, *criteria)
                ).scalar_one()
            )

    def row(self, table: Any, *criteria: Any) -> dict[str, Any]:  # noqa: ANN401 - a Table
        with self.engine.connect() as connection:
            return dict(connection.execute(select(table).where(*criteria)).mappings().one())


def _find_id(document: object, prefix: str) -> str | None:
    if isinstance(document, str) and document.startswith(prefix):
        return document
    if isinstance(document, dict):
        for value in document.values():
            found = _find_id(value, prefix)
            if found is not None:
                return found
    if isinstance(document, list):
        for value in document:
            found = _find_id(value, prefix)
            if found is not None:
                return found
    return None


def _scrub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every application setting so only this module's composition applies."""
    for name in list(os.environ):
        if name.startswith(ENV_PREFIX) and name != f"{ENV_PREFIX}MIGRATION_DATABASE_URL":
            monkeypatch.delenv(name)


@pytest.fixture
def compose(
    disposable_database: str, monkeypatch: pytest.MonkeyPatch, network: NetworkGuard
) -> Iterator[Callable[..., Slice]]:
    """Build the gateway composition from this test's environment, once per call."""
    built: list[GatewayRuntime] = []

    def factory(*, relationship_memory: bool = True) -> Slice:
        _scrub(monkeypatch)
        environment = {
            "DATABASE_URL": disposable_database,
            "RELATIONSHIP_INTELLIGENCE_ENABLED": "true",
            "RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED": "true",
            "RELATIONSHIP_MEMORY_ENABLED": "true" if relationship_memory else "false",
            "KNOWLEDGE_ASSERTIONS_ENABLED": "true",
            # The ONLY place the synthetic discovery client is allowlisted.
            "KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS": DISCOVERY_CLIENT,
            "KNOWLEDGE_OPERATOR_REVIEW_OAUTH_CLIENT_IDS": OPERATOR_CLIENT,
            "KNOWLEDGE_CHECKPOINT_SIGNING_KEY": SIGNING_KEY,
        }
        for name, value in environment.items():
            monkeypatch.setenv(f"{ENV_PREFIX}{name}", value)
        settings = load_settings()
        runtime = build_gateway_runtime(settings)
        built.append(runtime)
        return Slice(runtime, settings)

    try:
        yield factory
    finally:
        for runtime in built:
            runtime.close()
        assert network.attempts == [], network.attempts


def provision(capsys: pytest.CaptureFixture[str], path: Path = PROFILE_FILE) -> tuple[int, str]:
    """Run the real operator command in process; (exit status, stdout)."""
    capsys.readouterr()
    status = provisioner.main(["apply", "--file", str(path)])
    return status, capsys.readouterr().out


def provisioned_profile(capsys: pytest.CaptureFixture[str]) -> str:
    status, printed = provision(capsys)
    assert status == provisioner.EXIT_OK, printed
    profile = _find_id(printed.split(), "kdsp_")
    assert profile is not None, printed
    assert "origin=synthetic" in printed
    assert "direct=true" in printed and "proof=proven" in printed
    assert "ceiling=authoritative_source" in printed
    # The native scope is hashed by the command and never echoed (KLP-AC-072).
    assert "klp07-synthetic-vertical-slice-scope" not in printed
    return profile


def external(object_id: str, *, role: str = "direct") -> dict[str, object]:
    import hashlib

    return {
        "identity_kind": "external_object",
        "external_object_id": object_id,
        "external_version_id": "v1",
        "content_hash": hashlib.sha256(f"klp07|{object_id}|v1".encode()).hexdigest(),
        "role": role,
    }


def capture_evidence(slice_: Slice, capture_id: str) -> dict[str, object]:
    with slice_.engine.connect() as connection:
        digest = connection.execute(
            select(capture_versions.c.content_sha256).where(
                capture_versions.c.capture_id == capture_id
            )
        ).scalar_one()
    return {
        "identity_kind": "capture",
        "capture_id": capture_id,
        "content_hash": str(digest),
        "role": "supporting",
    }


def memory_evidence(slice_: Slice, memory_id: str) -> dict[str, object]:
    with slice_.engine.connect() as connection:
        digest = connection.execute(
            select(relationship_memory_versions.c.statement_sha256).where(
                relationship_memory_versions.c.memory_id == memory_id
            )
        ).scalar_one()
    return {
        "identity_kind": "relationship_memory",
        "relationship_memory_id": memory_id,
        "content_hash": str(digest),
        "role": "supporting",
    }


def knowledge_events(slice_: Slice) -> list[dict[str, Any]]:
    with slice_.engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(record_events)
                .where(
                    record_events.c.principal_id == slice_.principal_id,
                    record_events.c.record_family == "knowledge_assertion",
                )
                .order_by(record_events.c.sequence_number)
            ).mappings()
        ]


def submission_of(slice_: Slice, submission_id: str) -> dict[str, Any]:
    return slice_.row(
        knowledge_assertion_submissions,
        knowledge_assertion_submissions.c.submission_id == submission_id,
    )


def knowledge_rows(slice_: Slice) -> dict[str, int]:
    """Row counts of every Knowledge table a routed submission must leave untouched."""
    return {
        table.name: slice_.count(table)
        for table in (
            knowledge_assertions,
            knowledge_assertion_proposals,
            knowledge_assertion_subject_locks,
            knowledge_assertion_mutations,
            knowledge_assertion_evidence_links,
        )
    }


def _error_code(envelope: Mapping[str, Any]) -> str:
    error = envelope.get("error")
    assert isinstance(error, dict), envelope
    return str(error.get("code"))


# ---- the guard ----------------------------------------------------------------------


def test_the_synthetic_profile_is_operator_provisioned_and_guarded(
    compose: Callable[..., Slice],
    capsys: pytest.CaptureFixture[str],
    disposable_database: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # (2) The client is server-owned and allowlisted only by this module's composition.
    defaults = Settings(database_url=disposable_database)
    assert defaults.knowledge_discovery_oauth_client_id_set() == frozenset()
    assert defaults.knowledge_operator_review_oauth_client_id_set() == frozenset()
    needle = DISCOVERY_CLIENT.encode()
    for base in ("ops", "src", "apps"):
        for path in sorted((ROOT / base).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                assert needle not in path.read_bytes(), path.relative_to(ROOT).as_posix()
    document = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    (entry,) = document["profiles"]
    assert entry["authenticated_client_id"] == DISCOVERY_CLIENT
    assert entry["origin_system"] == "synthetic"

    # A default composition (no discovery allowlist) refuses the committed file whole.
    _scrub(monkeypatch)
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", disposable_database)
    status, printed = provision(capsys)
    assert status == provisioner.EXIT_REFUSED, printed
    assert "KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS" in printed
    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    select(func.count()).select_from(knowledge_discovery_source_profiles)
                ).scalar_one()
                == 0
            )
    finally:
        engine.dispose()

    # Under this module's composition the real operator command provisions it.
    slice_ = compose()
    profile = provisioned_profile(capsys)
    stored = slice_.row(
        knowledge_discovery_source_profiles,
        knowledge_discovery_source_profiles.c.source_profile_id == profile,
    )
    assert stored["principal_id"] == slice_.principal_id
    assert stored["authenticated_client_id"] == DISCOVERY_CLIENT
    assert (stored["origin_system"], stored["is_synthetic"]) == ("synthetic", True)
    assert stored["disabled_at"] is None
    # Re-applying converges (the operator contract): still one profile.
    assert provisioned_profile(capsys) == profile
    assert slice_.count(knowledge_discovery_source_profiles) == 1

    # (3) A client outside the allowlist is refused at provisioning, with no row...
    rogue = tmp_path / "rogue.json"
    rogue.write_text(
        json.dumps({**document, "profiles": [{**entry, "authenticated_client_id": ROGUE_CLIENT}]}),
        encoding="utf-8",
    )
    status, printed = provision(capsys, rogue)
    assert status == provisioner.EXIT_REFUSED, printed
    assert slice_.count(knowledge_discovery_source_profiles) == 1

    # ...and at submit: the overlay strips the discovery pair from its ceiling, and a
    # forged ceiling naming submit is refused by the service's second gate.
    org = slice_.created_id(
        Capability.ENTITIES_CREATE,
        {
            "entity_type": "organization",
            "display_name": "Synthetic Org G",
            "idempotency_key": "klp07-seed-g",
        },
        "ent_",
    )
    candidate = {
        "source_profile_id": profile,
        "external_run_id": "run-rogue",
        "external_candidate_id": "cand-rogue",
        "subject_kind": "entity",
        "subject_id": org,
        "predicate_code": OPERATING,
        "value": "Synthetic rogue requirement",
        "evidence": [external("obj-rogue")],
    }
    submit_grants = _purposed(KNOWLEDGE_CLIENT_PROFILES[DISCOVERY_PROFILE])
    allowed, _purposes = slice_.access(ROGUE_CLIENT, submit_grants)
    assert Capability.KNOWLEDGE_ASSERTIONS_SUBMIT.value not in allowed
    assert Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT.value not in allowed
    published = slice_.remote(
        ROGUE_CLIENT, submit_grants, Capability.KNOWLEDGE_ASSERTIONS_SUBMIT, candidate
    )
    assert _error_code(published) == "not_published"
    forged = slice_.remote(
        ROGUE_CLIENT,
        submit_grants,
        Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
        candidate,
        overlay=False,
    )
    assert _error_code(forged) == "unsupported", forged
    # The operator-review client is bound too, but to another profile: no submit.
    assert (
        _error_code(
            slice_.remote(
                OPERATOR_CLIENT,
                submit_grants,
                Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
                candidate,
                overlay=False,
            )
        )
        == "unsupported"
    )
    assert slice_.count(knowledge_assertion_submissions) == 0

    # (1) What the bound client admits through it is labelled synthetic end to end.
    created = slice_.submit(
        profile,
        run="run-guard",
        candidate="cand-guard",
        subject_kind="entity",
        subject_id=org,
        predicate=OPERATING,
        value="Synthetic guarded requirement",
        evidence=[external("obj-guard")],
    )
    assert created["outcome"] == "direct_created", created
    fact = slice_.row(
        knowledge_assertions, knowledge_assertions.c.assertion_id == created["assertion_id"]
    )
    # The fact keeps its predicate's floor (a synthetic source never lowers it)...
    assert fact["classification"] == "private_local"
    assert fact["epistemic_status"] == "source_observed"
    with slice_.engine.connect() as connection:
        origins = set(
            connection.execute(
                select(
                    knowledge_evidence_refs.c.content_origin,
                    knowledge_evidence_refs.c.source_classification,
                ).where(knowledge_evidence_refs.c.principal_id == slice_.principal_id)
            ).all()
        )
    # ...while the evidence it cites is identifiably synthetic.
    assert origins == {("synthetic_source", "synthetic_test")}


# ---- the slice ----------------------------------------------------------------------


@dataclass(frozen=True)
class Seeded:
    """The owning-plane records the slice's candidates are about."""

    organization: str
    person: str
    project: str
    task: str
    meeting: str
    capture: str


def seed(slice_: Slice) -> Seeded:
    """Create the subjects and owners through their own planes' capabilities."""
    entity = Capability.ENTITIES_CREATE
    return Seeded(
        organization=slice_.created_id(
            entity,
            {
                "entity_type": "organization",
                "display_name": "Synthetic Org",
                "idempotency_key": "klp07-seed-o",
            },
            "ent_",
        ),
        person=slice_.created_id(
            entity,
            {
                "entity_type": "person",
                "display_name": "Synthetic Person",
                "idempotency_key": "klp07-seed-p",
            },
            "ent_",
        ),
        project=slice_.created_id(
            Capability.CONTINUITY_PROJECTS_CREATE,
            {"name": "Synthetic project", "idempotency_key": "klp07-seed-prj"},
            "prj_",
        ),
        task=slice_.created_id(
            Capability.TASKS_CREATE,
            {
                "title": "Synthetic task",
                "idempotency_key": "klp07-seed-tsk",
                "origin_kind": "direct_principal",
            },
            "tsk_",
        ),
        meeting=slice_.created_id(
            Capability.MEETINGS_CREATE,
            {
                "title": "Synthetic meeting",
                "start_at": "2026-11-02T15:00:00+00:00",
                "timezone_name": "UTC",
                "idempotency_key": "klp07-seed-mtg",
            },
            "mtg_",
        ),
        capture=slice_.created_id(
            Capability.CAPTURE_CREATE,
            {
                "text": "Synthetic note: prefers written updates",
                "idempotency_key": "klp07-seed-cap",
            },
            "cap_",
        ),
    )


RUN: Final = "klp07-run-1"
#: (candidate, subject kind, subject attr, predicate, value, extra) -> expected
#: (outcome, reason, canonical_owner, routed attr). The R6 11.6 table, walked.
DATE: Final[dict[str, object]] = {"qualifier": {"date_kind": "deadline"}}
UNKNOWN_TASK: Final = "tsk_klp07unknowntask0001"


def test_the_internal_synthetic_slice_runs_end_to_end(
    compose: Callable[..., Slice], capsys: pytest.CaptureFixture[str]
) -> None:
    before = set(sys.modules)
    slice_ = compose()
    profile = provisioned_profile(capsys)
    seeded = seed(slice_)

    # The eight frozen seed rows are the registry this slice routes through.
    matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))["initial_predicates"]
    with slice_.engine.connect() as connection:
        registry = {
            row.predicate_code: (row.canonical_owner, row.review_requirement)
            for row in connection.execute(
                text(
                    "SELECT predicate_code, canonical_owner, review_requirement "
                    "FROM knowledge.knowledge_assertion_predicates"
                )
            )
        }
    assert registry == {
        row["predicate_code"]: (row["canonical_owner"], row["review_requirement"]) for row in matrix
    }

    capture = capture_evidence(slice_, seeded.capture)
    owner_ref_task = {"kind": "task", "id": seeded.task}
    candidates: list[tuple[str, dict[str, Any], tuple[str, str, str | None, str | None]]] = [
        (
            "c-operating",
            {
                "subject_kind": "entity",
                "subject_id": seeded.organization,
                "predicate": OPERATING,
                "value": "Synthetic badges are required on site",
                "evidence": [external("obj-op")],
            },
            ("direct_created", "created", "knowledge_assertion", None),
        ),
        (
            "c-payment",
            {
                "subject_kind": "entity",
                "subject_id": seeded.organization,
                "predicate": PAYMENT,
                "value": "Synthetic net 45 payment terms",
                "evidence": [external("obj-pay")],
            },
            ("review_queued", "requires_operator", "knowledge_assertion", None),
        ),
        (
            "c-policy",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": POLICY,
                "value": "Synthetic policy requirement",
                "evidence": [external("obj-pol")],
            },
            ("review_queued", "requires_review", "knowledge_assertion", None),
        ),
        (
            "c-lesson",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": LESSON,
                "value": "Synthetic lesson learned",
                "evidence": [external("obj-les")],
            },
            ("review_queued", "requires_review", "knowledge_assertion", None),
        ),
        (
            "c-financial",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": FINANCIAL,
                "value": "Synthetic contingency fact",
                "evidence": [external("obj-fin")],
            },
            ("review_queued", "requires_operator", "knowledge_assertion", None),
        ),
        (
            "c-decision",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": DECISION,
                "value": "Synthetic decision",
                "evidence": [external("obj-dec")],
            },
            ("domain_owned_no_intake", "canonical_owner_no_intake", "continuity_decision", None),
        ),
        (
            "c-critical-task",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": CRITICAL,
                "value": CRITICAL_VALUE,
                "evidence": [external("obj-crit-t")],
                "owner_ref": owner_ref_task,
                **DATE,
            },
            ("domain_owned_routed", "canonical_owner", "tasks", seeded.task),
        ),
        (
            "c-critical-meeting",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": CRITICAL,
                "value": CRITICAL_VALUE,
                "evidence": [external("obj-crit-m")],
                "owner_ref": {"kind": "meeting", "id": seeded.meeting},
                **DATE,
            },
            ("domain_owned_routed", "canonical_owner", "meetings", seeded.meeting),
        ),
        (
            "c-critical-invalid",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": CRITICAL,
                "value": CRITICAL_VALUE,
                "evidence": [external("obj-crit-x")],
                "owner_ref": {"kind": "task", "id": UNKNOWN_TASK},
                **DATE,
            },
            ("refused", "owner_ref_invalid", None, None),
        ),
        (
            "c-critical-review",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": CRITICAL,
                "value": CRITICAL_VALUE,
                "evidence": [external("obj-crit-r")],
                **DATE,
            },
            ("review_queued", "requires_operator", "knowledge_assertion", None),
        ),
        (
            "c-ref-elsewhere",
            {
                "subject_kind": "project",
                "subject_id": seeded.project,
                "predicate": POLICY,
                "value": "Synthetic policy with a ref",
                "evidence": [external("obj-ref")],
                "owner_ref": owner_ref_task,
            },
            ("refused", "owner_ref_invalid", None, None),
        ),
        (
            "c-preference",
            {
                "subject_kind": "entity",
                "subject_id": seeded.person,
                "predicate": PREFERENCE,
                "value": "Prefers written updates",
                "evidence": [external("obj-pref"), capture],
            },
            ("domain_owned_no_intake", "canonical_owner_no_intake", "relationship_memory", None),
        ),
    ]
    results: dict[str, dict[str, Any]] = {}
    for candidate, fields, (outcome, reason, owner, routed) in candidates:
        result = slice_.submit(profile, run=RUN, candidate=candidate, **fields)
        assert (result["outcome"], result["reason"]) == (outcome, reason), (candidate, result)
        if outcome != "refused":
            assert result["canonical_owner"] == owner, (candidate, result)
        assert result["routed_record_id"] == routed, (candidate, result)
        row = submission_of(slice_, result["submission_id"])
        assert row["submission_state"] == "completed"
        assert (row["outcome"], row["reason"]) == (outcome, reason)
        assert row["authenticated_client_id"] == DISCOVERY_CLIENT
        assert row["source_profile_id"] == profile
        assert row["origin_is_synthetic"] is True
        if outcome.startswith("domain_owned"):
            assert row["result_canonical_owner"] == owner
            assert row["result_routed_record_id"] == routed
            assert result["assertion_id"] is None and result["proposal_id"] is None
        results[candidate] = result
    queued = {
        candidate for candidate, _fields, expected in candidates if expected[0] == "review_queued"
    }
    # Only the Knowledge path wrote Knowledge rows: one assertion, five proposals.
    assert slice_.count(knowledge_assertions) == 1
    assert slice_.count(knowledge_assertion_proposals) == len(queued) == 5
    assert slice_.count(knowledge_assertion_submissions) == len(candidates)
    events = knowledge_events(slice_)
    assert [(event["event_kind"], event["record_id"]) for event in events] == [
        ("created", results["c-operating"]["assertion_id"])
    ]

    # Replay of retried submits: the stored result, no second row or event.
    for candidate, fields, _expected in candidates:
        if candidate in {"c-operating", "c-decision", "c-critical-task", "c-payment"}:
            again = slice_.submit(profile, run=RUN, candidate=candidate, **fields)
            assert again == results[candidate], candidate
    assert slice_.count(knowledge_assertion_submissions) == len(candidates)
    assert len(knowledge_events(slice_)) == 1

    # The discovery checkpoint: the run's completed count, sealed, then replayed.
    checkpoint = {
        "source_profile_id": profile,
        "expected_version": 0,
        "external_run_id": RUN,
        "submitted_candidate_count": len(candidates),
        "checkpoint_kind": "delta_token",
        "private_envelope": "synthetic-delta-token-klp07",
    }
    advanced = slice_.ok(
        slice_.discovery(Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT, checkpoint), "checkpoint"
    )
    assert (advanced["outcome"], advanced["checkpoint_version"]) == ("advanced", 1), advanced
    assert advanced["private_envelope"] == "synthetic-delta-token-klp07"
    replayed = slice_.ok(
        slice_.discovery(Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT, checkpoint), "replay"
    )
    assert replayed == advanced

    # Knowledge Review: the operator-review client lists and decides.
    listed = slice_.ok(slice_.reviewer(Capability.REVIEW_LIST, {"page_size": 50}), "review.list")
    cases = {
        row["predicate_code"] + "|" + str(row["value"]): row
        for row in listed["review_cases"]
        if row["subject_kind"] == "knowledge_assertion"
    }
    assert len(cases) == 5
    by_candidate = {
        candidate: next(
            row
            for row in cases.values()
            if row["review_case_id"] == results[candidate]["review_case_id"]
        )
        for candidate in queued
    }
    payment_case = by_candidate["c-payment"]
    # The case row is the detail: it carries the read-only candidate (R6 10.1).
    assert payment_case["value"] == "Synthetic net 45 payment terms"
    assert payment_case["predicate_code"] == PAYMENT
    assert payment_case["subject_id"] == seeded.organization
    assert payment_case["review_requirement"] == "requires_operator"
    assert payment_case["proposal_state"] == "needs_review"
    assert len(payment_case["evidence_ref_ids"]) == 1
    accepted = slice_.ok(
        slice_.reviewer(
            Capability.REVIEW_DECIDE,
            {
                "review_case_id": payment_case["review_case_id"],
                "expected_review_version": 0,
                "disposition": "accept",
            },
        ),
        "accept",
    )
    assert accepted["proposal_state"] == "accepted"
    assert accepted["assertion_id"].startswith("kasr_")
    rejected = slice_.ok(
        slice_.reviewer(
            Capability.REVIEW_DECIDE,
            {
                "review_case_id": by_candidate["c-lesson"]["review_case_id"],
                "expected_review_version": 0,
                "disposition": "reject",
                "reason": "Synthetic: not a lesson",
            },
        ),
        "reject",
    )
    assert (rejected["proposal_state"], rejected["assertion_id"]) == ("rejected", None)
    deferred = slice_.ok(
        slice_.reviewer(
            Capability.REVIEW_DECIDE,
            {
                "review_case_id": by_candidate["c-policy"]["review_case_id"],
                "expected_review_version": 0,
                "disposition": "defer",
            },
        ),
        "defer",
    )
    assert (deferred["proposal_state"], deferred["assertion_id"]) == ("deferred", None)
    # A decided case replays its stored answer to the same request (server replay).
    assert (
        slice_.ok(
            slice_.reviewer(
                Capability.REVIEW_DECIDE,
                {
                    "review_case_id": payment_case["review_case_id"],
                    "expected_review_version": 0,
                    "disposition": "accept",
                },
            ),
            "accept replay",
        )
        == accepted
    )
    assert slice_.count(knowledge_assertions) == 2

    direct_id = str(results["c-operating"]["assertion_id"])
    accepted_id = str(accepted["assertion_id"])

    # Knowledge read and search.
    read = slice_.ok(
        slice_.discovery(Capability.KNOWLEDGE_ASSERTIONS_READ, {"assertion_id": direct_id}), "read"
    )
    assert _find_id(read, "kasr_") == direct_id
    assert "Synthetic badges are required on site" in json.dumps(read)
    reviewed = slice_.ok(
        slice_.reviewer(Capability.KNOWLEDGE_ASSERTIONS_READ, {"assertion_id": accepted_id}),
        "reviewer read",
    )
    assert "Synthetic net 45 payment terms" in json.dumps(reviewed)
    found = slice_.ok(
        slice_.local(Capability.KNOWLEDGE_ASSERTIONS_SEARCH, {"query": "badges"}), "search"
    )
    assert direct_id in json.dumps(found) and accepted_id not in json.dumps(found)
    live = slice_.ok(slice_.local(Capability.KNOWLEDGE_ASSERTIONS_LIST, {}), "list")
    assert {item["assertion_id"] for item in live["assertions"]} == {direct_id, accepted_id}

    # context.prepare with the knowledge_assertion plane.
    def plane_items(envelope: Mapping[str, Any]) -> set[str]:
        prepared = slice_.ok(envelope, "context.prepare")
        return {
            str(item["knowledge_assertion_id"])
            for item in prepared["evidence"]
            if item["plane"] == "knowledge_assertion"
        }

    assert direct_id in plane_items(
        slice_.local(Capability.CONTEXT_PREPARE, {"query": "badges are required"})
    )
    assert accepted_id in plane_items(
        slice_.local(Capability.CONTEXT_PREPARE, {"query": "payment terms"})
    )
    assert direct_id in plane_items(slice_.reader({"query": "badges are required"}))
    for withheld in (
        frozenset({(Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION)}),
        frozenset(
            {
                (Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION),
                (Capability.KNOWLEDGE_ASSERTIONS_READ, Purpose.KNOWLEDGE_ASSERTION_READ),
            }
        ),
    ):
        answer = slice_.ok(slice_.reader({"query": "badges are required"}, withheld), "withheld")
        assert "knowledge_assertion" not in json.dumps(answer)

    # Record Events and their provenance.
    events = knowledge_events(slice_)
    assert [(event["event_kind"], event["record_id"]) for event in events] == [
        ("created", direct_id),
        ("created", accepted_id),
    ]
    direct_event, accepted_event = (str(event["event_id"]) for event in events)
    feed = slice_.ok(
        slice_.discovery(
            Capability.RECORD_EVENTS_LIST,
            {"page_size": 50, "record_families": ["knowledge_assertion"]},
        ),
        "record_events.list",
    )
    assert [item["record_id"] for item in feed["events"]] == [direct_id, accepted_id]
    supplied = slice_.ok(
        slice_.discovery(Capability.RECORD_EVENTS_PROVENANCE, {"event_id": direct_event}),
        "provenance",
    )["provenance"]
    assert supplied["record_id"] == direct_id
    assert supplied["submission"]["submission_id"] == results["c-operating"]["submission_id"]
    assert supplied["submission"]["external_run_id"] == RUN
    assert supplied["submission"]["external_candidate_id"] == "c-operating"
    assert supplied["review"] is None
    promoted = slice_.ok(
        slice_.local(Capability.RECORD_EVENTS_PROVENANCE, {"event_id": accepted_event}),
        "provenance",
    )["provenance"]
    assert promoted["actor_class"] == "review_promotion"
    assert promoted["review"]["review_case_id"] == payment_case["review_case_id"]
    assert promoted["review"]["decision_id"] == accepted["decision_id"]
    assert promoted["review"]["decision_channel"] == "remote_operator_review"
    assert promoted["submission"]["submission_id"] == results["c-payment"]["submission_id"]

    # End state: routed and refused candidates left no Knowledge row behind.
    assert knowledge_rows(slice_) == {
        "knowledge_assertions": 2,
        "knowledge_assertion_proposals": 5,
        "knowledge_assertion_subject_locks": slice_.count(knowledge_assertion_subject_locks),
        "knowledge_assertion_mutations": 2,
        "knowledge_assertion_evidence_links": 2,
    }
    with slice_.engine.connect() as connection:
        locked_predicates = set(
            connection.execute(
                select(knowledge_assertion_subject_locks.c.predicate_code).where(
                    knowledge_assertion_subject_locks.c.principal_id == slice_.principal_id
                )
            ).scalars()
        )
    assert locked_predicates == {OPERATING, PAYMENT, POLICY, LESSON, FINANCIAL, CRITICAL}
    assert not locked_predicates & {DECISION, PREFERENCE}

    # No external connector was imported by the composition and walk.
    imported = set(sys.modules) - before
    assert not {name for name in imported if name.startswith("my_pa.infrastructure.connectors")}


# ---- routed submissions take no Knowledge C5-C8 lock (R6 8.5, 13) ------------------


class TableHolder:
    """A third session holding the C5-C8 Knowledge tables against any write or row lock.

    Each table is locked in SHARE mode, which conflicts with ROW EXCLUSIVE --
    every INSERT, UPDATE and DELETE, so a subject-lock upsert (C6), a proposal,
    an assertion, a mutation or a link write blocks -- and every existing row of
    them is held `FOR UPDATE`, so a C5/C6/C7 row lock on any of them blocks too.
    SHARE still admits plain reads and the `FOR KEY SHARE` a foreign-key check
    takes, which are not Knowledge locks. A submission that completes while
    this is held therefore wrote no C5-C8 row and locked none.
    """

    def __init__(self, url: str) -> None:
        self.engine = create_database_engine(url)
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        for table in C5_C8_TABLES:
            self.connection.execute(text(f"LOCK TABLE {table} IN SHARE MODE"))
            self.connection.execute(text(f"SELECT 1 FROM {table} FOR UPDATE"))  # noqa: S608

    def release(self) -> None:
        if self.transaction.is_active:
            self.transaction.rollback()
        self.connection.close()
        self.engine.dispose()


def held_submit(slice_: Slice, url: str, submit: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run `submit` while C5-C8 are held; it must complete without waiting."""
    holder = TableHolder(url)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(submit)
            try:
                return future.result(timeout=ROUTED_DEADLINE)
            except FutureTimeoutError:
                holder.release()
                future.result(timeout=ROUTED_DEADLINE)
                raise AssertionError("a routed submission waited on a C5-C8 lock") from None
    finally:
        holder.release()


@pytest.mark.parametrize(
    ("relationship_memory", "shape"),
    [
        (True, "capture"),
        (True, "relationship_memory"),
        (True, "external_only"),
        (False, "capture"),
    ],
    ids=["rm_composed_capture", "rm_composed_memory", "rm_composed_external_only", "rm_absent"],
)
def test_communication_preference_is_no_intake_and_takes_no_knowledge_lock(
    compose: Callable[..., Slice],
    capsys: pytest.CaptureFixture[str],
    disposable_database: str,
    relationship_memory: bool,
    shape: str,
) -> None:
    """WP-07 DEV-01: with no faithful reviewed RM intake, every case is no-intake.

    Relationship Memory composed with transferable (capture / relationship
    memory) evidence, composed with external-only evidence, and not composed:
    each completes `domain_owned_no_intake` naming `relationship_memory`,
    writes no Knowledge assertion, proposal or subject-lock row, opens no
    Relationship Memory proposal, and completes while C5-C8 are held.
    """
    slice_ = compose(relationship_memory=relationship_memory)
    profile = provisioned_profile(capsys)
    person = slice_.created_id(
        Capability.ENTITIES_CREATE,
        {
            "entity_type": "person",
            "display_name": "Synthetic Person",
            "idempotency_key": "klp07-p1",
        },
        "ent_",
    )
    evidence: list[dict[str, object]] = [external("obj-pref")]
    if shape == "capture":
        capture = slice_.created_id(
            Capability.CAPTURE_CREATE,
            {"text": "Synthetic: prefers calls", "idempotency_key": "klp07-cap-1"},
            "cap_",
        )
        evidence.append(capture_evidence(slice_, capture))
    elif shape == "relationship_memory":
        memory = slice_.created_id(
            Capability.RELATIONSHIP_MEMORY_CREATE,
            {
                "entity_id": person,
                "statement": "Synthetic: prefers calls",
                "idempotency_key": "klp07-mem-1",
            },
            "mem_",
        )
        evidence.append(memory_evidence(slice_, memory))
    with slice_.engine.connect() as connection:
        rm_proposals_before = int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.relationship_memory_proposals")
            ).scalar_one()
        )
    result = held_submit(
        slice_,
        disposable_database,
        lambda: slice_.submit(
            profile,
            run="run-pref",
            candidate=f"cand-{shape}",
            subject_kind="entity",
            subject_id=person,
            predicate=PREFERENCE,
            value="Prefers phone calls",
            evidence=evidence,
        ),
    )
    assert (result["outcome"], result["reason"], result["canonical_owner"]) == (
        "domain_owned_no_intake",
        "canonical_owner_no_intake",
        "relationship_memory",
    )
    assert result["routed_record_id"] is None and result["proposal_id"] is None
    row = submission_of(slice_, result["submission_id"])
    assert row["submission_state"] == "completed"
    assert row["result_canonical_owner"] == "relationship_memory"
    assert knowledge_rows(slice_) == dict.fromkeys(
        (
            "knowledge_assertions",
            "knowledge_assertion_proposals",
            "knowledge_assertion_subject_locks",
            "knowledge_assertion_mutations",
            "knowledge_assertion_evidence_links",
        ),
        0,
    )
    with slice_.engine.connect() as connection:
        rm_proposals_after = int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.relationship_memory_proposals")
            ).scalar_one()
        )
    assert rm_proposals_after == rm_proposals_before
    assert knowledge_events(slice_) == []


def test_a_routed_critical_date_takes_no_knowledge_lock_while_the_knowledge_path_waits(
    compose: Callable[..., Slice],
    capsys: pytest.CaptureFixture[str],
    disposable_database: str,
) -> None:
    slice_ = compose()
    profile = provisioned_profile(capsys)
    project = slice_.created_id(
        Capability.CONTINUITY_PROJECTS_CREATE,
        {"name": "Synthetic locked project", "idempotency_key": "klp07-prj-lock"},
        "prj_",
    )
    task = slice_.created_id(
        Capability.TASKS_CREATE,
        {
            "title": "Synthetic task",
            "idempotency_key": "klp07-tsk-lock",
            "origin_kind": "direct_principal",
        },
        "tsk_",
    )

    def critical(
        candidate: str, value: str = CRITICAL_VALUE, **extra: object
    ) -> Callable[[], dict[str, Any]]:
        return lambda: slice_.submit(
            profile,
            run="run-lock",
            candidate=candidate,
            subject_kind="project",
            subject_id=project,
            predicate=CRITICAL,
            value=value,
            evidence=[external(f"obj-{candidate}")],
            qualifier={"date_kind": "deadline"},
            **extra,
        )

    # A Knowledge-path candidate first, so the subject-lock row of this very key
    # (project, project.critical_date) exists and is held below.
    first = critical("first")()
    assert first["outcome"] == "review_queued", first
    assert knowledge_rows(slice_)["knowledge_assertion_subject_locks"] == 1

    routed = held_submit(
        slice_, disposable_database, critical("routed", owner_ref={"kind": "task", "id": task})
    )
    assert (routed["outcome"], routed["routed_record_id"]) == ("domain_owned_routed", task)
    decision = held_submit(
        slice_,
        disposable_database,
        lambda: slice_.submit(
            profile,
            run="run-lock",
            candidate="decision",
            subject_kind="project",
            subject_id=project,
            predicate=DECISION,
            value="Synthetic decision",
            evidence=[external("obj-decision")],
        ),
    )
    assert decision["outcome"] == "domain_owned_no_intake"
    assert knowledge_rows(slice_)["knowledge_assertion_subject_locks"] == 1

    # The control: the same candidate without an owner ref is a Knowledge-path
    # submission (Review), and it waits for the held tables.
    holder = TableHolder(disposable_database)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(critical("reviewed", "2026-12-01T00:00:00+00:00"))
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=CONTROL_WAIT)
            holder.release()
            reviewed = future.result(timeout=ROUTED_DEADLINE)
    finally:
        holder.release()
    assert reviewed["outcome"] == "review_queued", reviewed
    assert knowledge_rows(slice_)["knowledge_assertion_subject_locks"] == 1
    assert knowledge_rows(slice_)["knowledge_assertion_proposals"] == 2


def test_the_slice_composition_imports_no_external_connector() -> None:
    """A fresh interpreter composing the slice's modules imports no connector."""
    probe = (
        "import sys\n"
        "import apps.cli.knowledge_source_profiles, apps.gateway\n"
        "import my_pa.adapters.mcp.server, my_pa.bootstrap.gateway\n"
        "import my_pa.application.knowledge_assertions\n"
        "found = sorted(m for m in sys.modules if m.startswith("
        "('my_pa.infrastructure.connectors', 'my_pa.domain.connectors')))\n"
        "print(','.join(found))\n"
    )
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith(ENV_PREFIX)
    }
    environment["PYTHONPATH"] = os.pathsep.join([str(ROOT / "src"), str(ROOT)])
    completed = subprocess.run(  # noqa: S603 - a fixed interpreter and literal probe
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
        env=environment,
        timeout=120,
    )
    assert completed.stdout.strip() == "", completed.stdout
