"""Production event paths must register every governed re-enrichment trigger."""

from __future__ import annotations

import argparse
import asyncio
import inspect
from collections.abc import Mapping
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import apps.gateway as gateway
import httpx2
import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeUnitOfWork,
    Scene,
    World,
    build_service,
    metadata_for,
)

import my_pa.bootstrap.gateway as bootstrap_gateway
from my_pa.adapters.http import create_http_app
from my_pa.application.commands import (
    Command,
    CreateEntityAssignment,
    EndEntityAssignment,
    ReviseEntityAssignment,
)
from my_pa.application.entity_reenrichment import (
    TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND,
    reenrichment_trigger_for_review_decision,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import local_principal
from my_pa.contracts.ports import ReenrichmentVersionObservation
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.relationship.entity import (
    AssignmentType,
    Entity,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.reenrichment import (
    BindingVersion,
    ReenrichmentBinding,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    ReenrichmentWork,
)
from my_pa.domain.source.registry import issue_identifier

ASSIGNEE = "ent_rienrich01rienrich"
PROJECT = "ent_riproject2riproject"


class _UnchangedObservation:
    changed = False


class _InvocationReenrichmentRepository:
    def __init__(self) -> None:
        self.bindings: list[ReenrichmentBinding] = []
        self.registration_attempts = 0
        self.observations: list[tuple[str, str, str, str]] = []

    def register(self, binding: ReenrichmentBinding, *, at: datetime) -> ReenrichmentWork:
        self.registration_attempts += 1
        self.bindings.append(binding)
        return ReenrichmentWork(
            work_id=f"erwk_{self.registration_attempts:08d}",
            binding=binding,
            state=ReenrichmentState.QUEUED,
            attempt_count=0,
            max_attempts=3,
            created_at=at,
            updated_at=at,
        )

    def observe_version(
        self,
        principal_id: str,
        *,
        namespace: str,
        key: str,
        version: str,
        at: datetime,
    ) -> ReenrichmentVersionObservation:
        del at
        self.observations.append((principal_id, namespace, key, version))
        return _UnchangedObservation()


class _InvocationUnitOfWork(FakeUnitOfWork):
    def __init__(self, world: World, reenrichment: _InvocationReenrichmentRepository) -> None:
        super().__init__(world)
        self._reenrichment = reenrichment

    @property
    def reenrichment(self) -> _InvocationReenrichmentRepository:
        return self._reenrichment


def _assignment_entity(entity_id: str, principal_id: str, *, entity_type: EntityType) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(f"Synthetic {entity_id}"),
        display_name=f"Synthetic {entity_id}",
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.mark.parametrize(
    ("handler_name", "trigger"),
    [
        ("_entities_merge", ReenrichmentTrigger.CORRECTED_IDENTITY),
        ("_entities_split", ReenrichmentTrigger.CORRECTED_IDENTITY),
        ("_entities_aliases_add", ReenrichmentTrigger.NEW_ALIAS),
        ("_entities_relationships_create", ReenrichmentTrigger.PROJECT_MAPPING_CHANGE),
        ("_entities_relationships_revise", ReenrichmentTrigger.PROJECT_MAPPING_CHANGE),
        ("_entities_relationships_end", ReenrichmentTrigger.PROJECT_MAPPING_CHANGE),
        (
            "_entities_assignments_create",
            ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
        ),
        (
            "_entities_assignments_revise",
            ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE,
        ),
        ("_entities_assignments_end", ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE),
        ("_admit", ReenrichmentTrigger.ACCEPTED_QUICK_CAPTURE_CORRECTION),
        ("_review_decide", ReenrichmentTrigger.CONTRADICTION_RESOLUTION),
    ],
)
def test_each_production_mutation_path_registers_its_exact_trigger(
    handler_name: str, trigger: ReenrichmentTrigger
) -> None:
    source = inspect.getsource(getattr(ApplicationService, handler_name))
    assert "_register_reenrichment(" in source
    # `_review_decide` is the one handler whose trigger is not a literal of its
    # own. WP-04 / RI-P3-HIGH-001 moved that decision into the pure, total
    # `reenrichment_trigger_for_review_decision`, because the handler
    # registered CONTRADICTION_RESOLUTION for every committed decision -- all
    # eight dispositions, all four review subject kinds -- and no literal in a
    # handler can say "only an accepted `resolve_mention`". The assertion still
    # requires the trigger to be named in production source reachable from the
    # capability; it now searches the delegate too rather than pretending the
    # decision is still spelled here. What the move bought is proved
    # exhaustively (17 kinds x 8 dispositions) in
    # `tests/unit/test_entity_reenrichment.py`.
    if handler_name == "_review_decide":
        # The literal lives in the delegate's module-level closed table, which
        # `inspect.getsource` of a function cannot reach. Assert the delegation
        # is real and that the table genuinely produces this trigger -- both
        # stronger than the substring, which a comment could satisfy.
        assert f"{reenrichment_trigger_for_review_decision.__name__}(" in source
        assert trigger in set(TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND.values())
    else:
        assert f"ReenrichmentTrigger.{trigger.name}" in source


def test_assignment_invocations_register_role_change_once_and_replays_register_zero(
    scene: Scene,
) -> None:
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        unit_of_work.entities.create(
            principal_id,
            _assignment_entity(ASSIGNEE, principal_id, entity_type=EntityType.PERSON),
        )
        unit_of_work.entities.create(
            principal_id,
            _assignment_entity(PROJECT, principal_id, entity_type=EntityType.PROJECT),
        )
    reenrichment = _InvocationReenrichmentRepository()
    service = ApplicationService(
        unit_of_work=lambda: _InvocationUnitOfWork(scene.world, reenrichment),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        relationship_intelligence_enabled=True,
        relationship_intelligence_writes_enabled=True,
        relationship_reenrichment_enabled=True,
    )

    def invoke(capability: Capability, command: Command) -> dict[str, Any]:
        envelope = service.invoke(
            metadata_for(
                capability,
                sorted(permitted_purposes(capability))[0],
                scene.principal,
            ),
            command,
            principal=scene.principal,
        ).to_canonical_dict()
        assert envelope.get("error") is None, envelope.get("error")
        result = envelope["result"]
        assert isinstance(result, dict)
        return result

    create = CreateEntityAssignment(
        entity_id=ASSIGNEE,
        expected_entity_version=1,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        scope_entity_id=PROJECT,
        expected_scope_version=1,
        role="Project Manager",
        idempotency_key="reenrichment-assignment-create",
    )
    created = invoke(Capability.ENTITIES_ASSIGNMENTS_CREATE, create)
    assert created["replayed"] is False
    assert reenrichment.registration_attempts == 1
    replayed_create = invoke(Capability.ENTITIES_ASSIGNMENTS_CREATE, create)
    assert replayed_create["replayed"] is True
    assert reenrichment.registration_attempts == 1

    revise = ReviseEntityAssignment(
        assignment_id=created["record_id"],
        expected_version=created["version"],
        role="Programme Manager",
        idempotency_key="reenrichment-assignment-revise",
    )
    revised = invoke(Capability.ENTITIES_ASSIGNMENTS_REVISE, revise)
    assert revised["replayed"] is False
    assert reenrichment.registration_attempts == 2
    replayed_revise = invoke(Capability.ENTITIES_ASSIGNMENTS_REVISE, revise)
    assert replayed_revise["replayed"] is True
    assert reenrichment.registration_attempts == 2

    end = EndEntityAssignment(
        assignment_id=created["record_id"],
        expected_version=revised["version"],
        reason="the synthetic assignment ended",
        end_now=True,
        idempotency_key="reenrichment-assignment-end",
    )
    ended = invoke(Capability.ENTITIES_ASSIGNMENTS_END, end)
    assert ended["replayed"] is False
    assert reenrichment.registration_attempts == 3
    replayed_end = invoke(Capability.ENTITIES_ASSIGNMENTS_END, end)
    assert replayed_end["replayed"] is True
    assert reenrichment.registration_attempts == 3

    mutations = (created, revised, ended)
    assert len(reenrichment.bindings) == len(mutations) == 3
    assert {binding.trigger for binding in reenrichment.bindings} == {
        ReenrichmentTrigger.ROLE_OR_ORGANIZATION_CHANGE
    }
    assert all(
        binding.trigger is not ReenrichmentTrigger.PROJECT_MAPPING_CHANGE
        for binding in reenrichment.bindings
    )
    for binding, mutation in zip(reenrichment.bindings, mutations, strict=True):
        assert binding.principal_id == principal_id
        assert binding.cause_record_id == mutation["receipt_id"]
        assert binding.subjects == (
            ReenrichmentSubject(
                ReenrichmentSubjectKind.ASSIGNMENT,
                mutation["record_id"],
                str(mutation["version"]),
            ),
        )
        assert binding.input_versions == ()
        assert binding.producer_versions == (
            BindingVersion("relationship_intelligence", "relationship-intelligence-v0.2"),
        )
        assert binding.policy_version == "policy-v1"

    assert (
        reenrichment.observations
        == [
            (
                principal_id,
                "producer",
                "relationship_intelligence",
                "relationship-intelligence-v0.2",
            ),
            (principal_id, "policy", "current", "policy-v1"),
        ]
        * 3
    )


@pytest.mark.parametrize("transport", ["http", "stdio", "remote"])
def test_real_gateway_startup_observes_versions_before_each_transport_serves(
    monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    events: list[str] = []
    outcomes: list[bool] = []
    calls: list[tuple[str, str]] = []
    watermark: dict[str, str] = {}
    configured = {"policy": "policy-v1"}
    principal = local_principal()

    class Runtime:
        service = object()
        authenticate = None
        remote_client = None
        apple_authenticate = None
        apple_control = None
        mcp_enabled = True
        work_engine = SimpleNamespace(begin=lambda: None)

        def __init__(self) -> None:
            self.principal = principal

        def observe_reenrichment_versions(
            self, *, principal_id: str, cause: str
        ) -> tuple[object, ...]:
            previous = watermark.get(principal_id)
            current = configured["policy"]
            changed = previous is not None and previous != current
            watermark[principal_id] = current
            calls.append((principal_id, cause))
            outcomes.append(changed)
            events.append("observe")
            return (object(),) if changed else ()

        def close(self) -> None:
            events.append("close")

    settings = SimpleNamespace(
        gateway_bind_host=lambda: "127.0.0.1",
        remote_mcp_enabled=True,
        oauth_authorization_server="https://issuer.invalid",
        oauth_audience="https://resource.invalid",
        oauth_scopes="relationship.read",
        remote_mcp_public_host="mcp.invalid",
        mcp_surface_disabled=False,
        remote_writes_enabled=False,
        oauth_operator_secret=None,
        compact_publication_for_client=lambda _client_id: False,
    )
    monkeypatch.setattr(gateway, "load_settings", lambda: settings)
    monkeypatch.setattr(gateway, "build_gateway_runtime", lambda _settings: Runtime())
    monkeypatch.setattr(
        gateway,
        "create_http_app",
        lambda *_args, **_kwargs: events.append("compose") or object(),
    )
    monkeypatch.setattr(gateway.uvicorn, "Config", lambda *_args, **_kwargs: object())

    class Server:
        def __init__(self, _config: object) -> None:
            pass

        def run(self) -> None:
            events.append("serve")

    monkeypatch.setattr(gateway.uvicorn, "Server", Server)
    monkeypatch.setattr(
        gateway,
        "serve_stdio",
        lambda *_args, **_kwargs: events.append("serve"),
    )
    monkeypatch.setattr(
        gateway,
        "OriginOAuthServer",
        lambda **_kwargs: SimpleNamespace(introspect=lambda _token: None),
    )
    monkeypatch.setattr(
        gateway,
        "RemoteAuthenticator",
        lambda **_kwargs: SimpleNamespace(authenticate=lambda _header: None),
    )
    monkeypatch.setattr(gateway, "build_origin_oauth_routes", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        gateway,
        "create_remote_mcp_app",
        lambda *_args, **_kwargs: events.append("compose") or object(),
    )
    monkeypatch.setattr(
        gateway.uvicorn,
        "run",
        lambda *_args, **_kwargs: events.append("serve"),
    )

    def start() -> int:
        if transport == "http":
            return gateway._run(argparse.Namespace(port=8765))
        if transport == "stdio":
            return gateway._mcp(argparse.Namespace())
        return gateway._mcp_remote(argparse.Namespace(host="127.0.0.1", port=8766))

    assert start() == 0
    assert start() == 0
    configured["policy"] = "policy-v2"
    assert start() == 0

    assert outcomes == [False, False, True]
    assert [principal_id for principal_id, _cause in calls] == [principal.principal_id] * 3
    causes = [cause for _principal_id, cause in calls]
    for cause in causes:
        validate_identifier(cause, IdKind.OPERATION)
    assert len(set(causes)) == 3
    assert [event for event in events if event in {"observe", "serve"}] == [
        "observe",
        "serve",
    ] * 3


def test_entra_http_observes_each_authenticated_principal_before_application_dispatch(
    monkeypatch: pytest.MonkeyPatch, scene: Scene
) -> None:
    events: list[str] = []
    outcomes: list[bool] = []
    watermark: dict[str, str] = {}
    configured = {"policy": "policy-v1"}
    service = build_service(scene.world, scene.providers)
    invoke = service.invoke

    def recording_invoke(
        metadata: RequestMetadata, command: Command, *, principal: Principal
    ) -> ResponseEnvelope:
        events.append(f"application:{principal.principal_id}")
        return invoke(metadata, command, principal=principal)

    monkeypatch.setattr(service, "invoke", recording_invoke)

    class Runtime:
        principal = None
        remote_client = None
        apple_authenticate = None
        apple_control = None
        mcp_enabled = True
        work_engine = SimpleNamespace(begin=lambda: None)

        def __init__(self) -> None:
            self.service = service

        def authenticate(self, _credential: str | None, _document: Mapping[str, Any]) -> Principal:
            events.append("authenticate")
            self.observe_reenrichment_versions(
                principal_id=scene.principal.principal_id,
                cause=issue_identifier(IdKind.OPERATION),
            )
            return scene.principal

        def observe_reenrichment_versions(
            self, *, principal_id: str, cause: str
        ) -> tuple[object, ...]:
            validate_identifier(cause, IdKind.OPERATION)
            events.append(f"observe:{principal_id}")
            if configured["policy"] == "fail":
                raise RuntimeError("synthetic observation failure")
            previous = watermark.get(principal_id)
            current = configured["policy"]
            changed = previous is not None and previous != current
            watermark[principal_id] = current
            outcomes.append(changed)
            return (object(),) if changed else ()

        def close(self) -> None:
            events.append("close")

    runtime = Runtime()
    settings = SimpleNamespace(gateway_bind_host=lambda: "127.0.0.1")
    monkeypatch.setattr(gateway, "load_settings", lambda: settings)
    monkeypatch.setattr(gateway, "build_gateway_runtime", lambda _settings: runtime)
    monkeypatch.setattr(gateway, "create_http_app", create_http_app)

    class Config:
        def __init__(self, application: object, **_kwargs: object) -> None:
            self.application = application

    class Server:
        def __init__(self, config: Config) -> None:
            self.application = config.application

        def run(self) -> None:
            async def exercise() -> None:
                document = {
                    "request_id": "req-entra-reenrichment",
                    "purpose": sorted(permitted_purposes(Capability.CAPABILITIES_GET))[0].value,
                    "principal_id": scene.principal.principal_id,
                    "requested_at": "2026-08-28T12:00:00Z",
                    "payload": {},
                }
                async with httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(
                        app=self.application, raise_app_exceptions=False
                    ),
                    base_url="http://testserver",
                ) as client:
                    for expected in (False, False):
                        response = await client.post(
                            "/v1/capabilities.get",
                            headers={"authorization": "Bearer synthetic"},
                            json=document,
                        )
                        assert response.status_code == 200
                        assert outcomes[-1] is expected
                    configured["policy"] = "policy-v2"
                    response = await client.post(
                        "/v1/capabilities.get",
                        headers={"authorization": "Bearer synthetic"},
                        json=document,
                    )
                    assert response.status_code == 200
                    assert outcomes[-1] is True
                    application_calls = events.count(f"application:{scene.principal.principal_id}")
                    configured["policy"] = "fail"
                    response = await client.post(
                        "/v1/capabilities.get",
                        headers={"authorization": "Bearer synthetic"},
                        json=document,
                    )
                    assert response.status_code == 500
                    assert (
                        events.count(f"application:{scene.principal.principal_id}")
                        == application_calls
                    )

            asyncio.run(exercise())

    monkeypatch.setattr(gateway.uvicorn, "Config", Config)
    monkeypatch.setattr(gateway.uvicorn, "Server", Server)

    assert gateway._run(argparse.Namespace(port=8765)) == 0
    assert outcomes == [False, False, True]
    assert [event.split(":", 1)[0] for event in events[:9]] == [
        "authenticate",
        "observe",
        "application",
    ] * 3
    assert events[-1] == "close"


def test_composed_entra_authenticator_observes_inside_identity_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    causes: list[str] = []
    connection = object()

    class Transaction:
        def __enter__(self) -> object:
            events.append("begin")
            return connection

        def __exit__(self, *_error: object) -> None:
            events.append("commit")

    class Engine:
        def begin(self) -> Transaction:
            return Transaction()

    class Verifier:
        def claims(self, _credential: str) -> Mapping[str, object]:
            events.append("verify")
            return {"tid": "synthetic", "oid": "synthetic"}

    class Identity:
        def __init__(self, *, home_tenant_id: str) -> None:
            assert home_tenant_id == "synthetic-tenant"

        def authenticate(self, used_connection: object, **_kwargs: object) -> object:
            assert used_connection is connection
            events.append("identity")
            return SimpleNamespace(
                account=SimpleNamespace(principal_id=UUID("11111111-2222-3333-4444-555555555555"))
            )

    def observe(used_connection: object, **kwargs: object) -> tuple[object, ...]:
        assert used_connection is connection
        causes.append(str(kwargs["cause"]))
        events.append(f"observe:{kwargs['principal_id']}")
        return ()

    monkeypatch.setattr(
        bootstrap_gateway,
        "EntraTokenVerifier",
        lambda **_kwargs: Verifier(),
    )
    monkeypatch.setattr(
        bootstrap_gateway,
        "jwks_signing_key_source",
        lambda _uri: lambda _token: object(),
    )
    monkeypatch.setattr(bootstrap_gateway, "PrincipalIdentityService", Identity)
    monkeypatch.setattr(bootstrap_gateway, "_observe_reenrichment_versions", observe)
    settings = SimpleNamespace(
        entra_client_id="synthetic-client",
        entra_issuer="https://issuer.invalid",
        entra_jwks_uri="https://issuer.invalid/jwks",
        entra_tenant_id="synthetic-tenant",
    )
    authenticate = bootstrap_gateway.entra_authenticator(settings, Engine())

    principal = authenticate("Bearer synthetic", {"payload": {}})

    assert principal.authenticated is True
    assert len(causes) == 1
    validate_identifier(causes[0], IdKind.OPERATION)
    assert events == [
        "verify",
        "begin",
        "identity",
        f"observe:{principal.principal_id}",
        "commit",
    ]


def test_remote_mcp_observes_only_authenticated_request_principals_before_context(
    monkeypatch: pytest.MonkeyPatch, scene: Scene
) -> None:
    events: list[str] = []
    outcomes: list[bool] = []
    contexts: list[object] = []
    watermark: dict[str, str] = {}
    configured = {"policy": "policy-v1"}

    class Runtime:
        principal = None
        service = object()
        work_engine = SimpleNamespace(begin=lambda: None)

        def observe_reenrichment_versions(
            self, *, principal_id: str, cause: str
        ) -> tuple[object, ...]:
            validate_identifier(cause, IdKind.OPERATION)
            events.append(f"observe:{principal_id}")
            if configured["policy"] == "fail":
                raise RuntimeError("synthetic observation failure")
            previous = watermark.get(principal_id)
            current = configured["policy"]
            changed = previous is not None and previous != current
            watermark[principal_id] = current
            outcomes.append(changed)
            return (object(),) if changed else ()

        def observe_authenticated_principal(
            self, principal: Principal, *, cause: str
        ) -> tuple[object, ...]:
            assert principal.authenticated is True
            return self.observe_reenrichment_versions(
                principal_id=principal.principal_id,
                cause=cause,
            )

        def close(self) -> None:
            events.append("close")

    runtime = Runtime()
    settings = SimpleNamespace(
        remote_mcp_enabled=True,
        oauth_authorization_server="https://issuer.invalid",
        oauth_audience="https://resource.invalid",
        oauth_scopes="relationship.read",
        remote_mcp_public_host="mcp.invalid",
        mcp_surface_disabled=False,
        remote_writes_enabled=False,
        oauth_operator_secret=None,
        compact_publication_for_client=lambda _client_id: False,
    )
    authenticated = SimpleNamespace(
        principal=scene.principal,
        capabilities=frozenset({Capability.CAPABILITIES_GET}),
        write_allowed=True,
        client_id="synthetic-client",
        capability_purposes=frozenset(),
    )

    class Authenticator:
        def authenticate(self, header: str | None) -> object:
            events.append("authenticate")
            if header != "Bearer synthetic":
                raise gateway.RemoteAuthenticationError()
            return authenticated

    monkeypatch.setattr(gateway, "load_settings", lambda: settings)
    monkeypatch.setattr(gateway, "build_gateway_runtime", lambda _settings: runtime)
    monkeypatch.setattr(
        gateway,
        "OriginOAuthServer",
        lambda **_kwargs: SimpleNamespace(introspect=lambda _token: None),
    )
    monkeypatch.setattr(gateway, "RemoteAuthenticator", lambda **_kwargs: Authenticator())
    monkeypatch.setattr(gateway, "build_origin_oauth_routes", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        gateway,
        "create_remote_mcp_app",
        lambda _service, *, resolve_access, **_kwargs: resolve_access,
    )

    def run(resolve_access: object, **_kwargs: object) -> None:
        resolve = resolve_access
        assert callable(resolve)
        assert resolve("invalid") is None
        assert events == ["authenticate"]
        for expected in (False, False):
            context = resolve("Bearer synthetic")
            contexts.append(context)
            events.append("context")
            assert outcomes[-1] is expected
        configured["policy"] = "policy-v2"
        context = resolve("Bearer synthetic")
        contexts.append(context)
        events.append("context")
        assert outcomes[-1] is True
        configured["policy"] = "fail"
        resolve("Bearer synthetic")

    monkeypatch.setattr(gateway.uvicorn, "run", run)

    with pytest.raises(RuntimeError, match="synthetic observation failure"):
        gateway._mcp_remote(argparse.Namespace(host="127.0.0.1", port=8766))

    assert outcomes == [False, False, True]
    assert all(context.principal == scene.principal for context in contexts)
    assert [event.split(":", 1)[0] for event in events[1:10]] == [
        "authenticate",
        "observe",
        "context",
    ] * 3
    assert events[-1] == "close"


def test_production_registration_challenge_covers_the_closed_vocabulary() -> None:
    handler_source = "\n".join(
        inspect.getsource(member)
        for name, member in vars(ApplicationService).items()
        if name.startswith("_") and callable(member)
    )
    source_fetch = inspect.getsource(ApplicationService._sources_fetch)
    proposal_create = inspect.getsource(ApplicationService._entities_proposals_create)
    startup_source = inspect.getsource(bootstrap_gateway._observe_reenrichment_versions)
    covered = {
        trigger
        for trigger in ReenrichmentTrigger
        if (
            f"ReenrichmentTrigger.{trigger.name}" in handler_source
            or (
                trigger is ReenrichmentTrigger.SOURCE_VERSION_CHANGE
                and "register_source_version_observation(" in source_fetch
            )
            or (
                trigger is ReenrichmentTrigger.MODEL_OR_RULE_VERSION_CHANGE
                and "register_producer_version_observation(" in proposal_create
            )
            or (
                trigger is ReenrichmentTrigger.POLICY_CHANGE
                and ".observe_process_versions(" in startup_source
            )
            # WP-04: `review.decide` no longer spells its trigger in the
            # handler. It is produced by the delegate's closed accepted-kind
            # table, which `_review_decide` calls.
            or (
                trigger in set(TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND.values())
                and "reenrichment_trigger_for_review_decision(" in handler_source
            )
        )
    }
    assert covered == set(ReenrichmentTrigger)
