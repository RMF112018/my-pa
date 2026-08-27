from __future__ import annotations

from collections.abc import Mapping

import httpx2
import pytest
from starlette.applications import Starlette

from my_pa.adapters.http.oauth import build_origin_oauth_routes
from my_pa.contracts.oauth import AuthorizationRequest

SYNTHETIC_APPROVAL_VALUE = "s" * 43


@pytest.fixture
def anyio_backend() -> str:
    """These ASGI contract tests exercise the installed asyncio backend only."""
    return "asyncio"


class FakeAuthorizationServer:
    resource = "https://mcp.example.invalid/mcp"
    issuer = "https://mcp.example.invalid"
    supported_scopes = frozenset({"my-pa.read"})

    def __init__(self) -> None:
        self.issued = 0

    def register_client(self, _payload: Mapping[str, object]) -> dict[str, object]:
        return {"client_id": "client"}

    def validate_authorization(self, values: Mapping[str, str]) -> AuthorizationRequest:
        return AuthorizationRequest(
            client_id="client",
            client_name="Synthetic client",
            redirect_uri=values.get("redirect_uri", "https://client.example/callback"),
            scope="my-pa.read",
            state=values.get("state", ""),
            code_challenge="a" * 43,
            resource=self.resource,
        )

    def issue_authorization_code(self, _request: AuthorizationRequest) -> str:
        self.issued += 1
        return "raw-code"

    def issue_token(self, _values: Mapping[str, str]) -> dict[str, object]:
        return {"access_token": "raw-token", "token_type": "Bearer"}

    def revoke(self, _raw_token: str) -> None:
        return None

    def authorization_server_metadata(self) -> dict[str, object]:
        return {"issuer": self.issuer, "code_challenge_methods_supported": ["S256"]}


@pytest.mark.anyio
async def test_operator_secret_is_required_only_for_code_approval() -> None:
    server = FakeAuthorizationServer()
    app = Starlette(
        routes=build_origin_oauth_routes(server, operator_secret=SYNTHETIC_APPROVAL_VALUE)
    )
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="https://mcp.example.invalid"
    ) as client:
        consent = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "client",
                "redirect_uri": "https://client.example/callback",
                "scope": "my-pa.read",
                "state": "state",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "resource": server.resource,
            },
        )
        assert consent.status_code == 200
        assert SYNTHETIC_APPROVAL_VALUE not in consent.text
        assert consent.headers["content-security-policy"] == (
            "default-src 'none'; form-action 'self' https://client.example; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        assert consent.headers["x-frame-options"] == "DENY"
        assert "Client ID: <code>client</code>" in consent.text
        assert "Redirect URI: <code>https://client.example/callback</code>" in consent.text
        approval = {
            "response_type": "code",
            "client_id": "client",
            "redirect_uri": "https://client.example/callback",
            "scope": "my-pa.read",
            "state": "state",
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
            "resource": server.resource,
            "operator_secret": "w" * 43,
            "decision": "approve",
        }
        for _attempt in range(5):
            refused = await client.post("/oauth/authorize", data=approval)
            assert refused.status_code == 403
        limited = await client.post("/oauth/authorize", data=approval)
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert refused.status_code == 403
        assert server.issued == 0
        approved = await client.post(
            "/oauth/authorize",
            data={**approval, "operator_secret": SYNTHETIC_APPROVAL_VALUE},
        )
        assert approved.status_code == 303
        assert approved.headers["location"].startswith("https://client.example/callback?")
        assert server.issued == 1
        assert refused.headers["content-security-policy"] == (
            "default-src 'none'; form-action 'self' https://client.example; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        assert limited.headers["content-security-policy"] == (
            "default-src 'none'; form-action 'self' https://client.example; "
            "frame-ancestors 'none'; base-uri 'none'"
        )


@pytest.mark.anyio
async def test_consent_csp_allows_chromium_to_follow_registered_callback() -> None:
    """Approve is a form POST; Chromium blocks 303s outside form-action.

    Production ChatLLM reached GET /oauth/authorize, submitted the correct
    operator secret, and the origin persisted authorization codes with a 303 to
    https://abacus.ai/oauth/callback. Chromium/Brave then refused to navigate
    because form-action was only 'self', so the callback never ran.
    """
    server = FakeAuthorizationServer()
    app = Starlette(
        routes=build_origin_oauth_routes(server, operator_secret=SYNTHETIC_APPROVAL_VALUE)
    )
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="https://mcp.example.invalid"
    ) as client:
        consent = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "client",
                "redirect_uri": "https://abacus.ai/oauth/callback",
                "scope": "my-pa.read",
                "state": "chatllm-state",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "resource": server.resource,
            },
        )
        policy = consent.headers["content-security-policy"]
        assert policy == (
            "default-src 'none'; form-action 'self' https://abacus.ai; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        mismatched = await client.post(
            "/oauth/authorize",
            data={
                "response_type": "code",
                "client_id": "client",
                "redirect_uri": "https://abacus.ai/oauth/callback",
                "scope": "my-pa.read",
                "state": "chatllm-state",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "resource": server.resource,
                "operator_secret": "short",
                "decision": "approve",
            },
        )
        assert mismatched.status_code == 403
        assert SYNTHETIC_APPROVAL_VALUE not in mismatched.text
        assert (
            "form-action 'self' https://abacus.ai;" in mismatched.headers["content-security-policy"]
        )
        approved = await client.post(
            "/oauth/authorize",
            data={
                "response_type": "code",
                "client_id": "client",
                "redirect_uri": "https://abacus.ai/oauth/callback",
                "scope": "my-pa.read",
                "state": "chatllm-state",
                "code_challenge": "a" * 43,
                "code_challenge_method": "S256",
                "resource": server.resource,
                "operator_secret": SYNTHETIC_APPROVAL_VALUE,
                "decision": "approve",
            },
        )
        assert approved.status_code == 303
        assert approved.headers["location"].startswith("https://abacus.ai/oauth/callback?")
        assert "code=" in approved.headers["location"]
        assert "state=chatllm-state" in approved.headers["location"]
        assert server.issued == 1
        assert SYNTHETIC_APPROVAL_VALUE not in approved.headers["location"]
