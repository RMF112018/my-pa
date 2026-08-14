"""HTTP routes for the repository-owned OAuth 2.1 surface."""

from __future__ import annotations

import asyncio
import html
import json
import secrets
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Final, ParamSpec, Protocol, TypeVar
from urllib.parse import parse_qs, urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from my_pa.contracts.oauth import AuthorizationRequest, OAuthError

__all__ = ["build_origin_oauth_routes"]

_MAX_BODY: Final = 16 * 1024
_APPROVAL_ATTEMPTS: Final = 5
_APPROVAL_WINDOW_SECONDS: Final = 60.0
_DATABASE_TIMEOUT_SECONDS: Final = 30.0
_DATABASE_CONCURRENCY: Final = 4
_P = ParamSpec("_P")
_R = TypeVar("_R")


class _BoundedCalls:
    """Run synchronous database work without blocking or outliving its capacity."""

    def __init__(self) -> None:
        self.slots = asyncio.Semaphore(_DATABASE_CONCURRENCY)

    async def run(self, callback: Callable[_P, _R], *args: _P.args, **kwargs: _P.kwargs) -> _R:
        await asyncio.wait_for(self.slots.acquire(), timeout=_DATABASE_TIMEOUT_SECONDS)
        task = asyncio.create_task(asyncio.to_thread(callback, *args, **kwargs))
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=_DATABASE_TIMEOUT_SECONDS)
        except (TimeoutError, asyncio.CancelledError):
            task.add_done_callback(lambda _task: self.slots.release())
            raise
        except Exception:
            self.slots.release()
            raise
        self.slots.release()
        return result


class AuthorizationServer(Protocol):
    resource: str
    issuer: str
    supported_scopes: frozenset[str]

    def register_client(self, payload: Mapping[str, object]) -> dict[str, object]: ...
    def validate_authorization(self, values: Mapping[str, str]) -> AuthorizationRequest: ...
    def issue_authorization_code(self, request: AuthorizationRequest) -> str: ...
    def exchange_code(self, values: Mapping[str, str]) -> dict[str, object]: ...
    def revoke(self, raw_token: str) -> None: ...
    def authorization_server_metadata(self) -> dict[str, object]: ...


async def _body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > _MAX_BODY:
                raise OAuthError("invalid_request", "request body is too large")
        except ValueError as exc:
            raise OAuthError("invalid_request", "content length is invalid") from exc
    body = await request.body()
    if len(body) > _MAX_BODY:
        raise OAuthError("invalid_request", "request body is too large")
    return body


async def _form(request: Request) -> dict[str, str]:
    body = await _body(request)
    try:
        parsed = parse_qs(body.decode("ascii"), strict_parsing=True, keep_blank_values=True)
    except (UnicodeDecodeError, ValueError) as exc:
        raise OAuthError("invalid_request", "form body is invalid") from exc
    if any(len(values) != 1 for values in parsed.values()):
        raise OAuthError("invalid_request", "duplicate form fields are not accepted")
    return {key: values[0] for key, values in parsed.items()}


def _query(request: Request) -> dict[str, str]:
    items = request.query_params.multi_items()
    if len({key for key, _value in items}) != len(items):
        raise OAuthError("invalid_request", "duplicate query fields are not accepted")
    return dict(items)


def _error(error: OAuthError) -> JSONResponse:
    return JSONResponse(
        {"error": error.error, "error_description": error.description},
        status_code=400,
        headers={"Cache-Control": "no-store"},
    )


def _unavailable() -> JSONResponse:
    return JSONResponse(
        {"error": "temporarily_unavailable"},
        status_code=503,
        headers={"Cache-Control": "no-store", "Retry-After": "5"},
    )


def _redirect(uri: str, values: Mapping[str, str]) -> str:
    separator = "&" if "?" in uri else "?"
    return f"{uri}{separator}{urlencode(values)}"


def _consent(request: AuthorizationRequest, *, refused: bool = False) -> str:
    hidden = {
        "response_type": "code",
        "client_id": request.client_id,
        "redirect_uri": request.redirect_uri,
        "scope": request.scope,
        "state": request.state,
        "code_challenge": request.code_challenge,
        "code_challenge_method": "S256",
        "resource": request.resource,
    }
    fields = "".join(
        f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">'
        for key, value in hidden.items()
    )
    notice = "<p>Approval failed.</p>" if refused else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'><title>Authorize my-pa</title></head>"
        "<body><main><h1>Authorize my-pa remote access</h1>"
        f"<p>Client: <strong>{html.escape(request.client_name)}</strong></p>"
        f"<p>Scope: <code>{html.escape(request.scope)}</code></p>{notice}"
        "<form method='post' action='/oauth/authorize'>"
        f"{fields}<label>Operator secret <input type='password' name='operator_secret' "
        "autocomplete='current-password' required></label>"
        "<button type='submit' name='decision' value='approve'>Approve</button>"
        "<button type='submit' name='decision' value='deny'>Deny</button>"
        "</form></main></body></html>"
    )


def build_origin_oauth_routes(
    server: AuthorizationServer,
    *,
    operator_secret: str,
) -> list[BaseRoute]:
    """Build public OAuth routes; only authorization approval consumes the secret."""
    if len(operator_secret) < 24:
        raise ValueError("OAuth operator secret must be at least 24 characters")
    failed_approvals: deque[float] = deque()
    calls = _BoundedCalls()

    async def metadata(_request: Request) -> JSONResponse:
        return JSONResponse(server.authorization_server_metadata())

    async def register(request: Request) -> JSONResponse:
        try:
            payload = json.loads(await _body(request))
            if not isinstance(payload, dict):
                raise OAuthError("invalid_client_metadata", "JSON object required")
            return JSONResponse(await calls.run(server.register_client, payload), status_code=201)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return _error(OAuthError("invalid_client_metadata", "JSON object required"))
        except OAuthError as exc:
            return _error(exc)
        except TimeoutError:
            return _unavailable()

    async def approval_endpoint(request: Request) -> Response:
        try:
            values = _query(request) if request.method == "GET" else await _form(request)
            authorization = await calls.run(server.validate_authorization, values)
        except OAuthError as exc:
            return _error(exc)
        except TimeoutError:
            return _unavailable()
        if request.method == "GET":
            return HTMLResponse(_consent(authorization), headers={"Cache-Control": "no-store"})
        if values.get("decision") == "deny":
            return RedirectResponse(
                _redirect(
                    authorization.redirect_uri,
                    {"error": "access_denied", "state": authorization.state},
                ),
                status_code=303,
            )
        now = time.monotonic()
        while failed_approvals and failed_approvals[0] <= now - _APPROVAL_WINDOW_SECONDS:
            failed_approvals.popleft()
        presented = values.get("operator_secret", "")
        approved = len(failed_approvals) < _APPROVAL_ATTEMPTS and secrets.compare_digest(
            presented, operator_secret
        )
        if not approved:
            failed_approvals.append(now)
            return HTMLResponse(
                _consent(authorization, refused=True),
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )
        try:
            code = await calls.run(server.issue_authorization_code, authorization)
        except TimeoutError:
            return _unavailable()
        return RedirectResponse(
            _redirect(
                authorization.redirect_uri,
                {"code": code, "state": authorization.state},
            ),
            status_code=303,
            headers={"Cache-Control": "no-store"},
        )

    async def token(request: Request) -> JSONResponse:
        try:
            return JSONResponse(
                await calls.run(server.exchange_code, await _form(request)),
                headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
            )
        except OAuthError as exc:
            return _error(exc)
        except TimeoutError:
            return _unavailable()

    async def revoke(request: Request) -> Response:
        try:
            values = await _form(request)
            await calls.run(server.revoke, values.get("token", ""))
        except OAuthError:
            pass
        except TimeoutError:
            return _unavailable()
        return Response(status_code=200, headers={"Cache-Control": "no-store"})

    return [
        Route("/.well-known/oauth-authorization-server", metadata, methods=["GET"]),
        Route("/.well-known/openid-configuration", metadata, methods=["GET"]),
        Route("/oauth/register", register, methods=["POST"]),
        Route("/oauth/authorize", approval_endpoint, methods=["GET", "POST"]),
        Route("/oauth/token", token, methods=["POST"]),
        Route("/oauth/revoke", revoke, methods=["POST"]),
    ]
