"""Header-only GSQS remote-eval authentication.  Fakes only; no network, no DB."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime, timedelta

import pytest
from pytest import MonkeyPatch

from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_FORBIDDEN_SCOPE,
    ERROR_UNAUTHENTICATED,
)
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.infrastructure.security.gsqs_remote_eval_authentication import (
    GSQS_REMOTE_EVAL_PURPOSE,
    GSQS_REMOTE_EVAL_RESOURCE_DEFAULT,
    GSQS_REMOTE_EVAL_SCOPE,
    GsqsRemoteEvalAuthenticationError,
    GsqsRemoteEvalAuthenticator,
    GsqsRemoteEvalPrincipal,
    assert_session_principal_binding,
    build_evaluation_origin_oauth_settings,
    evaluation_protected_resource_metadata,
)
from my_pa.infrastructure.security.remote_oauth import (
    OriginTokenContext,
    redact_security_value,
)

WHEN = datetime(2026, 8, 23, 12, tzinfo=UTC)
EVAL_RESOURCE = GSQS_REMOTE_EVAL_RESOURCE_DEFAULT
PRODUCTION_RESOURCE = "https://my-pa-mcp.bobby-fetting.me/mcp"
OTHER_RESOURCE = "https://something-else.example.invalid/mcp"
ISSUER = "https://my-pa-gsqs.bobby-fetting.me"
OPERATOR = capture_principal_id(LOCAL_OPERATOR_UUID)
FOREIGN = "prn_ffffffffffffffffffffffffffffffff"
VALID_BEARER = "synthetic-eval-token"
EXPIRED_BEARER = "synthetic-expired-token"
REVOKED_BEARER = "synthetic-revoked-token"
INVALID_BEARER = "synthetic-invalid-token"
PRODUCTION_SCOPE = "my-pa.read"


@dataclass(frozen=True, slots=True)
class StoredToken:
    client_id: str
    scopes: frozenset[str]
    resource: str
    expires_at: datetime | None = None
    revoked: bool = False


class FakeConnection:
    pass


@contextmanager
def connections() -> Iterator[FakeConnection]:
    yield FakeConnection()


def _store(**overrides: StoredToken) -> dict[str, StoredToken]:
    tokens: dict[str, StoredToken] = {
        VALID_BEARER: StoredToken(
            client_id="eval-client",
            scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
            resource=EVAL_RESOURCE,
        ),
        EXPIRED_BEARER: StoredToken(
            client_id="eval-client",
            scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
            resource=EVAL_RESOURCE,
            expires_at=WHEN - timedelta(seconds=1),
        ),
        REVOKED_BEARER: StoredToken(
            client_id="eval-client",
            scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
            resource=EVAL_RESOURCE,
            revoked=True,
        ),
    }
    tokens.update(overrides)
    return tokens


def _token_context(
    tokens: dict[str, StoredToken], *, now: datetime = WHEN
) -> Callable[[str], OriginTokenContext | None]:
    def lookup(raw: str) -> OriginTokenContext | None:
        record = tokens.get(raw)
        if record is None or record.revoked:
            return None
        if record.expires_at is not None and record.expires_at <= now:
            return None
        return OriginTokenContext(
            client_id=record.client_id,
            scopes=record.scopes,
            resource=record.resource,
        )

    return lookup


def _authenticator(
    *,
    tokens: dict[str, StoredToken] | None = None,
    required_resource: str = EVAL_RESOURCE,
    required_scope: str = GSQS_REMOTE_EVAL_SCOPE,
    principal_resolver: Callable[[str], str | None] | None = None,
) -> GsqsRemoteEvalAuthenticator:
    return GsqsRemoteEvalAuthenticator(
        token_context=_token_context(_store() if tokens is None else tokens),
        connections=connections,
        required_resource=required_resource,
        required_scope=required_scope,
        principal_resolver=principal_resolver,
        now=lambda: WHEN,
    )


def _unauthenticated(header: str | None, auth: GsqsRemoteEvalAuthenticator | None = None) -> None:
    authenticator = _authenticator() if auth is None else auth
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        authenticator.authenticate(header)
    assert error.value.code == ERROR_UNAUTHENTICATED
    assert str(error.value) == "the presented bearer credential is not authorized"
    assert error.value.__cause__ is None


def test_constants_and_purpose_are_string_literals_not_enums() -> None:
    assert EVAL_RESOURCE == "https://my-pa-gsqs.bobby-fetting.me/mcp"
    assert GSQS_REMOTE_EVAL_SCOPE == "my-pa.gsqs.evaluate"
    assert GSQS_REMOTE_EVAL_PURPOSE == "goodnotes.gsqs.b0.measurement"
    assert isinstance(GSQS_REMOTE_EVAL_PURPOSE, str)
    assert type(GSQS_REMOTE_EVAL_PURPOSE) is str
    assert ERROR_UNAUTHENTICATED == "UNAUTHENTICATED"
    assert ERROR_FORBIDDEN_SCOPE == "FORBIDDEN_SCOPE"


def test_no_authorization_header_is_unauthenticated() -> None:
    _unauthenticated(None)


@pytest.mark.parametrize("header", ["", "Basic value", "Bearer", "Bearer a b", "bearer"])
def test_malformed_bearer_is_unauthenticated(header: str) -> None:
    _unauthenticated(header)


def test_invalid_token_is_unauthenticated() -> None:
    _unauthenticated(f"Bearer {INVALID_BEARER}")


def test_expired_token_is_unauthenticated() -> None:
    _unauthenticated(f"Bearer {EXPIRED_BEARER}")


def test_revoked_token_is_unauthenticated() -> None:
    _unauthenticated(f"Bearer {REVOKED_BEARER}")


@pytest.mark.parametrize(
    "resource",
    [PRODUCTION_RESOURCE, OTHER_RESOURCE, "https://mcp.example.invalid/mcp"],
)
def test_wrong_audience_resource_is_unauthenticated(resource: str) -> None:
    tokens = _store(
        production=StoredToken(
            client_id="prod-client",
            scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE, PRODUCTION_SCOPE}),
            resource=resource,
        )
    )
    auth = _authenticator(tokens=tokens)
    _unauthenticated("Bearer production", auth)


def test_production_shaped_auth_against_wrong_resource_is_rejected() -> None:
    """A context that would succeed for production MCP must not authorize eval."""
    tokens = _store(
        prod=StoredToken(
            client_id="prod-client",
            scopes=frozenset({PRODUCTION_SCOPE}),
            resource=PRODUCTION_RESOURCE,
        )
    )
    auth = _authenticator(tokens=tokens, required_resource=EVAL_RESOURCE)
    _unauthenticated("Bearer prod", auth)


def test_missing_evaluation_scope_on_eval_resource_is_forbidden() -> None:
    tokens = _store(
        noscope=StoredToken(
            client_id="eval-client",
            scopes=frozenset(),
            resource=EVAL_RESOURCE,
        )
    )
    auth = _authenticator(tokens=tokens)
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        auth.authenticate("Bearer noscope")
    assert error.value.code == ERROR_FORBIDDEN_SCOPE
    assert error.value.__cause__ is None
    assert "synthetic" not in str(error.value)
    assert "Bearer" not in str(error.value)


def test_production_only_scope_on_eval_resource_is_forbidden() -> None:
    tokens = _store(
        prod_scope=StoredToken(
            client_id="eval-client",
            scopes=frozenset({PRODUCTION_SCOPE}),
            resource=EVAL_RESOURCE,
        )
    )
    auth = _authenticator(tokens=tokens)
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        auth.authenticate("Bearer prod_scope")
    assert error.value.code == ERROR_FORBIDDEN_SCOPE


def test_correct_evaluation_scope_and_matching_resource_succeeds() -> None:
    principal = _authenticator().authenticate(f"Bearer {VALID_BEARER}")
    assert principal == GsqsRemoteEvalPrincipal(
        principal_id=OPERATOR,
        client_id="eval-client",
        scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE}),
        resource=EVAL_RESOURCE,
    )


def test_extra_scopes_are_accepted_when_eval_scope_is_present() -> None:
    tokens = _store(
        extra=StoredToken(
            client_id="eval-client",
            scopes=frozenset({GSQS_REMOTE_EVAL_SCOPE, PRODUCTION_SCOPE}),
            resource=EVAL_RESOURCE,
        )
    )
    principal = _authenticator(tokens=tokens).authenticate("Bearer extra")
    assert GSQS_REMOTE_EVAL_SCOPE in principal.scopes
    assert principal.resource == EVAL_RESOURCE


def test_stale_principal_resolver_is_unauthenticated() -> None:
    def revoked(_client_id: str) -> None:
        return None

    auth = _authenticator(principal_resolver=revoked)
    _unauthenticated(f"Bearer {VALID_BEARER}", auth)


def test_header_only_never_reads_a_tool_body() -> None:
    auth = _authenticator()
    principal = auth.authenticate(f"Bearer {VALID_BEARER}")
    assert principal.principal_id == OPERATOR
    assert auth.authenticate.__code__.co_argcount == 2
    assert auth.authenticate.__code__.co_varnames[:2] == ("self", "authorization_header")


def test_foreign_session_principal_is_forbidden() -> None:
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        assert_session_principal_binding(
            authenticated_principal_id=OPERATOR,
            session_principal_id=FOREIGN,
        )
    assert error.value.code == ERROR_FORBIDDEN_SCOPE


def test_session_bound_principal_match_allows() -> None:
    assert_session_principal_binding(
        authenticated_principal_id=OPERATOR,
        session_principal_id=OPERATOR,
    )


@pytest.mark.parametrize(
    ("authenticated", "session"),
    [("", OPERATOR), (OPERATOR, ""), ("  ", OPERATOR), (OPERATOR, "  ")],
)
def test_empty_principal_binding_is_unauthenticated(authenticated: str, session: str) -> None:
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        assert_session_principal_binding(
            authenticated_principal_id=authenticated,
            session_principal_id=session,
        )
    assert error.value.code == ERROR_UNAUTHENTICATED


def test_rfc9728_evaluation_metadata_is_chatgpt_compatible_shaped() -> None:
    metadata = evaluation_protected_resource_metadata(
        resource=EVAL_RESOURCE,
        authorization_servers=(ISSUER,),
    )
    assert metadata == {
        "resource": EVAL_RESOURCE,
        "authorization_servers": [ISSUER],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [GSQS_REMOTE_EVAL_SCOPE],
    }
    assert PRODUCTION_SCOPE not in metadata["scopes_supported"]
    assert "my-pa.write" not in metadata["scopes_supported"]


def test_evaluation_metadata_does_not_advertise_production_resource() -> None:
    metadata = evaluation_protected_resource_metadata(
        resource=EVAL_RESOURCE,
        authorization_servers=(ISSUER,),
    )
    assert metadata["resource"] != PRODUCTION_RESOURCE
    assert metadata["scopes_supported"] == [GSQS_REMOTE_EVAL_SCOPE]


def test_origin_oauth_factory_kwargs_are_eval_scoped() -> None:
    settings = build_evaluation_origin_oauth_settings(
        connections=connections,
        issuer=ISSUER,
        now=lambda: WHEN,
    )
    assert settings["resource"] == EVAL_RESOURCE
    assert settings["issuer"] == ISSUER
    assert settings["supported_scopes"] == frozenset({GSQS_REMOTE_EVAL_SCOPE})
    assert settings["connections"] is connections
    assert callable(settings["now"])
    assert PRODUCTION_SCOPE not in settings["supported_scopes"]


def test_refusal_messages_do_not_echo_bearer_or_secrets() -> None:
    header = "Bearer super-secret-token-value"
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        _authenticator().authenticate(header)
    rendered = str(error.value)
    assert "super-secret-token-value" not in rendered
    assert "Bearer" not in rendered
    assert redact_security_value(header) == "[REDACTED]"


def test_remote_identity_repository_is_not_consulted(monkeypatch: MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("evaluation auth must not use production capability grants")

    monkeypatch.setattr(
        "my_pa.infrastructure.security.remote_oauth.RemoteIdentityRepository.authenticate",
        forbidden,
    )
    principal = _authenticator().authenticate(f"Bearer {VALID_BEARER}")
    assert principal.principal_id == OPERATOR


def test_injected_principal_resolver_is_the_only_principal() -> None:
    def resolve(client_id: str) -> str:
        assert client_id == "eval-client"
        return FOREIGN

    principal = _authenticator(principal_resolver=resolve).authenticate(f"Bearer {VALID_BEARER}")
    assert principal.principal_id == FOREIGN


def test_principal_dataclass_is_frozen() -> None:
    principal = _authenticator().authenticate(f"Bearer {VALID_BEARER}")
    with pytest.raises(FrozenInstanceError):
        principal.principal_id = FOREIGN  # type: ignore[misc]


def test_token_context_exception_is_unauthenticated() -> None:
    def boom(_token: str) -> OriginTokenContext:
        raise RuntimeError("store unavailable")

    auth = GsqsRemoteEvalAuthenticator(
        token_context=boom,
        connections=connections,
        now=lambda: WHEN,
    )
    _unauthenticated(f"Bearer {VALID_BEARER}", auth)
