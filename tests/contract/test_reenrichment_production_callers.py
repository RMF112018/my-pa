"""Production event paths must register every governed re-enrichment trigger."""

from __future__ import annotations

import argparse
import inspect
from types import SimpleNamespace

import apps.gateway as gateway
import pytest

from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import GatewayRuntime, local_principal
from my_pa.domain.relationship.reenrichment import ReenrichmentTrigger


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
    assert f"ReenrichmentTrigger.{trigger.name}" in source


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
    assert calls == [(principal.principal_id, "gateway_startup")] * 3
    assert [event for event in events if event in {"observe", "serve"}] == [
        "observe",
        "serve",
    ] * 3


def test_production_registration_challenge_covers_the_closed_vocabulary() -> None:
    handler_source = "\n".join(
        inspect.getsource(member)
        for name, member in vars(ApplicationService).items()
        if name.startswith("_") and callable(member)
    )
    source_fetch = inspect.getsource(ApplicationService._sources_fetch)
    proposal_create = inspect.getsource(ApplicationService._entities_proposals_create)
    startup_source = inspect.getsource(GatewayRuntime.observe_reenrichment_versions)
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
        )
    }
    assert covered == set(ReenrichmentTrigger)
