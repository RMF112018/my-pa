"""Enable/disable health and Host/Origin parameterization for GSQS remote-eval."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2
import pytest
from apps.gsqs_remote_eval import (
    INTENDED_STATE_ROOT,
    build_eval_app_from_settings,
    compose_eval_authenticator,
    eval_state_is_ready,
    prepare_eval_state_root,
)

from my_pa.application.goodnotes_gsqs_remote_eval_contracts import RemoteEvalError
from my_pa.application.goodnotes_gsqs_remote_eval_storage import FilesystemRemoteEvalStore
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.security.gsqs_remote_eval_authentication import (
    GSQS_REMOTE_EVAL_SCOPE,
    GsqsRemoteEvalAuthenticator,
)
from my_pa.infrastructure.security.remote_oauth import OriginTokenContext

DATABASE_URL = f"{ENV_PREFIX}DATABASE_URL"
_A_URL = "postgresql+psycopg://someone@db.invalid:5432/somewhere"
PUBLIC_HOST = "my-pa-gsqs.bobby-fetting.me"
PUBLIC_ORIGIN = f"https://{PUBLIC_HOST}"


@dataclass(frozen=True)
class FakePrincipal:
    principal_id: str = "principal-1"


class FakeAuthenticator:
    def authenticate(self, authorization_header: str | None) -> FakePrincipal:
        if authorization_header != "Bearer synthetic":
            raise RemoteEvalError("UNAUTHENTICATED", "unauthenticated")
        return FakePrincipal()


class FakeStore:
    def find_non_terminal_session_id(self) -> str | None:
        return None

    def load_session(self, session_id: str) -> object | None:
        _ = session_id
        return None


class FakeService:
    def __init__(self) -> None:
        self._store = FakeStore()

    def confirm_disclosed_to_transport(self, *_args: object, **_kwargs: object) -> None:
        return None

    def confirm_not_disclosed(self, *_args: object, **_kwargs: object) -> None:
        return None


def _disabled() -> dict[str, str]:
    return {DATABASE_URL: _A_URL}


def _enabled(tmp_path: Path, **overrides: str) -> dict[str, str]:
    values = {
        DATABASE_URL: _A_URL,
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ENABLED": "true",
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_PUBLIC_ORIGIN": PUBLIC_ORIGIN,
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_STATE_ROOT": str(tmp_path),
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_ALLOWED_ORIGINS": "https://chatllm.example.invalid",
        f"{ENV_PREFIX}GSQS_REMOTE_EVAL_OAUTH_OPERATOR_SECRET": "s" * 43,
    }
    values.update(overrides)
    return values


def _get(app: object, path: str) -> tuple[int, object]:
    async def _exercise() -> tuple[int, object]:
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(path)
        return response.status_code, response.json()

    return asyncio.run(_exercise())


def test_intended_state_root_is_documented_not_implicit() -> None:
    assert INTENDED_STATE_ROOT == "/srv/my-pa/gsqs-remote-eval"
    settings = load_settings(_disabled())
    assert settings.gsqs_remote_eval_state_root == ""
    assert settings.gsqs_remote_eval_state_root != INTENDED_STATE_ROOT


def test_disabled_serves_health_and_refuses_ready_and_mcp() -> None:
    settings = load_settings(_disabled())
    app = build_eval_app_from_settings(settings, authenticator=FakeAuthenticator())
    health_status, health_body = _get(app, "/healthz")
    ready_status, ready_body = _get(app, "/readyz")
    mcp_status, mcp_body = _get(app, "/mcp")
    assert health_status == 200
    assert health_body == {"status": "ok"}
    assert ready_status == 503
    assert ready_body == {"status": "unavailable"}
    assert mcp_status == 404
    assert mcp_body == {"error": "not_found"}
    assert "session_id" not in ready_body
    assert "gold" not in ready_body
    assert "token" not in ready_body
    assert "raster" not in ready_body


def test_enabled_ready_when_state_root_is_usable(tmp_path: Path) -> None:
    prepare_eval_state_root(tmp_path)
    settings = load_settings(_enabled(tmp_path))
    store = FilesystemRemoteEvalStore(tmp_path)
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        readiness=lambda: eval_state_is_ready(tmp_path, store),
        bind_host="127.0.0.1",
        bind_port=8767,
    )
    health_status, health_body = _get(app, "/healthz")
    ready_status, ready_body = _get(app, "/readyz")
    assert health_status == 200
    assert health_body == {"status": "ok"}
    assert ready_status == 200
    assert ready_body == {"status": "ready"}
    assert set(ready_body) == {"status"}
    hosts = settings.gsqs_remote_eval_transport_hosts(bind_host="127.0.0.1", port=8767)
    assert PUBLIC_HOST in hosts
    assert f"{PUBLIC_HOST}:8767" in hosts
    assert "*" not in hosts
    assert settings.gsqs_remote_eval_origin_allowlist() == ("https://chatllm.example.invalid",)
    assert str(tmp_path) != INTENDED_STATE_ROOT
    assert "/srv" not in str(tmp_path)


def test_enabled_readyz_is_503_when_readiness_is_false(tmp_path: Path) -> None:
    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        readiness=lambda: False,
    )
    ready_status, ready_body = _get(app, "/readyz")
    assert ready_status == 503
    assert ready_body == {"status": "unavailable"}


def test_eval_state_is_ready_requires_existing_root(tmp_path: Path) -> None:
    missing = tmp_path / "absent"
    store = FilesystemRemoteEvalStore(missing)
    assert eval_state_is_ready(missing, store) is False
    prepare_eval_state_root(tmp_path / "present")
    present = tmp_path / "present"
    assert eval_state_is_ready(present, FilesystemRemoteEvalStore(present)) is True


PRODUCTION_RESOURCE = "https://my-pa-mcp.bobby-fetting.me/mcp"


class FakeConnection:
    pass


@contextmanager
def _connections() -> Iterator[FakeConnection]:
    yield FakeConnection()


def _mcp_endpoint(app: object) -> object:
    for route in getattr(app, "routes", ()):
        if getattr(route, "path", None) == "/mcp":
            return route.endpoint
    raise AssertionError("/mcp route is missing")


def _post_mcp(
    app: object,
    *,
    headers: dict[str, str] | None = None,
    with_lifespan: bool = False,
) -> tuple[int, str]:
    async def _exercise() -> tuple[int, str]:
        async def _call() -> tuple[int, str]:
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                response = await client.post("/mcp", headers=headers)
            return response.status_code, response.text

        if not with_lifespan:
            return await _call()
        async with app.router.lifespan_context(app):  # type: ignore[union-attr]
            return await _call()

    return asyncio.run(_exercise())


def test_enabled_mcp_without_bearer_is_unauthenticated_not_not_found(tmp_path: Path) -> None:
    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        bind_host="testserver",
        bind_port=80,
    )
    status, body = _post_mcp(app)
    assert status == 401
    assert status != 404
    assert "synthetic" not in body


def test_enabled_app_parameterizes_exact_hosts_and_origins(tmp_path: Path) -> None:
    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        bind_host="127.0.0.1",
        bind_port=8767,
    )
    endpoint = _mcp_endpoint(app)
    security = endpoint.manager.security_settings
    hosts = settings.gsqs_remote_eval_transport_hosts(bind_host="127.0.0.1", port=8767)
    assert list(security.allowed_hosts) == list(hosts)
    assert list(security.allowed_origins) == ["https://chatllm.example.invalid"]
    assert "*" not in security.allowed_hosts
    assert "*" not in security.allowed_origins
    assert security.enable_dns_rebinding_protection is True
    assert PUBLIC_HOST in hosts


def test_enabled_mcp_rejects_foreign_host(tmp_path: Path) -> None:
    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        bind_host="testserver",
        bind_port=80,
    )
    status, body = _post_mcp(
        app,
        headers={
            "Authorization": "Bearer synthetic",
            "Content-Type": "application/json",
            "Host": "evil.example.invalid",
        },
        with_lifespan=True,
    )
    assert status == 421
    assert "evil.example.invalid" not in body


def test_enabled_mcp_rejects_foreign_origin(tmp_path: Path) -> None:
    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        bind_host="testserver",
        bind_port=80,
    )
    status, body = _post_mcp(
        app,
        headers={
            "Authorization": "Bearer synthetic",
            "Content-Type": "application/json",
            "Origin": "https://evil.example.invalid",
        },
        with_lifespan=True,
    )
    assert status == 403
    assert "evil.example.invalid" not in body


def test_production_audience_token_is_unauthenticated_at_mcp(tmp_path: Path) -> None:
    def token_context(raw: str) -> OriginTokenContext | None:
        if raw != "prod-token":
            return None
        return OriginTokenContext(
            client_id="prod-client",
            scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE, "my-pa.read"}),
            resource=PRODUCTION_RESOURCE,
        )

    authenticator = GsqsRemoteEvalAuthenticator(
        token_context=token_context,
        connections=_connections,
    )
    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=authenticator,
        service=FakeService(),
        bind_host="testserver",
        bind_port=80,
    )
    status, body = _post_mcp(app, headers={"Authorization": "Bearer prod-token"})
    assert status == 401
    assert "prod-token" not in body
    assert "my-pa.read" not in body


def test_compose_eval_authenticator_fails_closed_without_echoing_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(_enabled(tmp_path))

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("password=super-secret-value")

    monkeypatch.setattr("apps.gsqs_remote_eval.create_database_engine", explode)
    with pytest.raises(SystemExit) as error:
        compose_eval_authenticator(settings)
    rendered = str(error.value)
    assert "super-secret-value" not in rendered
    assert "password=" not in rendered
    assert "cannot be composed" in rendered


def test_enabled_app_prepends_extra_routes(tmp_path: Path) -> None:
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def extra(_request: object) -> JSONResponse:
        return JSONResponse({"extra": True})

    settings = load_settings(_enabled(tmp_path))
    app = build_eval_app_from_settings(
        settings,
        authenticator=FakeAuthenticator(),
        service=FakeService(),
        extra_routes=[Route("/oauth/register", extra, methods=["POST"])],
    )
    paths = [getattr(route, "path", "") for route in app.routes]
    assert paths[0] == "/oauth/register"
    assert "/mcp" in paths
    assert "/.well-known/oauth-protected-resource" in paths
