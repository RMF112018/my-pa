"""The authenticated HTTP surface, over a real socket and a real database.

`MY_PA_AUTH_MODE=entra`, end to end: a bearer token arrives, is verified against
a synthetic issuer, and resolves through `PrincipalIdentityService` to the one
durable `principal_id` that person's `(tid, oid)` owns. Every refusal it should
make is exercised, and each is asserted to be the refusal it claims to be rather
than an incidental one.

**Every key and every token is generated inside this process.** The RSA keypair
is built by the fixture below, lives for the length of the module, and is written
nowhere. There is no PEM, no JWKS file, and no token literal in the repository:
a committed private key trips a secret scanner on a public repository even when
it is synthetic, and a scanner that cries wolf once is a scanner that gets muted.

**No live tenant, application, issuer, or key is named.** The tenant and object
identifiers are the same obviously-invented values the rest of the identity suite
uses, the issuer is a `.invalid` URL (RFC 2606 reserves it, so it can never
resolve), and the JWKS URI is never fetched — `jwks_signing_key_source` is
replaced with a source that answers from the in-process key, which is also what
keeps this test offline and deterministic.

The database is disposable, created and dropped by this module's own fixture.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.wire import Wire, serve

import my_pa.bootstrap.gateway as gateway
from my_pa.adapters.http import create_http_app
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, AuthMode, Settings, SettingsError, load_settings
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.security.entra_token import (
    ALLOWED_ALGORITHMS,
    EntraTokenVerifier,
    TokenVerificationError,
)
from my_pa.infrastructure.security.principal_identity import PrincipalIdentityService

pytestmark = pytest.mark.database

ROOT = Path(__file__).resolve().parents[2]
DATABASE = "my_pa_entra_authentication_test"

#: Synthetic, and obviously so. The same made-up Moss tenant the rest of the
#: identity suite uses, so the two agree on what "home tenant" means.
MOSS_TENANT = "11111111-2222-3333-4444-555555555555"
FOREIGN_TENANT = "99999999-8888-7777-6666-555555555555"
OID_A = "aaaa0001-0000-0000-0000-000000000001"
OID_B = "bbbb0002-0000-0000-0000-000000000002"

#: An application registration that does not exist, in a tenant that does not
#: exist, at a host that cannot resolve.
CLIENT_ID = "cccc0003-0000-0000-0000-000000000003"
ISSUER = f"https://login.example.invalid/{MOSS_TENANT}/v2.0"
JWKS_URI = f"https://login.example.invalid/{MOSS_TENANT}/discovery/v2.0/keys"

KEY_ID = "synthetic-signing-key-1"


# ---- keys and tokens, minted in-process --------------------------------------


@pytest.fixture(scope="module")
def keypair() -> rsa.RSAPrivateKey:
    """One RSA keypair, generated here and never written down."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def public_jwk(keypair: rsa.RSAPrivateKey) -> jwt.PyJWK:
    """The public half, as the JWK a JWKS endpoint would have published."""
    rendered = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(keypair.public_key()))
    return jwt.PyJWK({**rendered, "kid": KEY_ID, "alg": "RS256"})


def mint(
    keypair: rsa.RSAPrivateKey,
    *,
    tid: str = MOSS_TENANT,
    oid: str = OID_A,
    audience: str = CLIENT_ID,
    issuer: str = ISSUER,
    lifetime: timedelta = timedelta(minutes=10),
    not_before: timedelta = timedelta(minutes=-1),
    claims: dict[str, Any] | None = None,
) -> str:
    """One RS256 token, signed by the in-process key."""
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "iat": int((now - timedelta(minutes=1)).timestamp()),
        "nbf": int((now + not_before).timestamp()),
        "exp": int((now + lifetime).timestamp()),
        "tid": tid,
        "oid": oid,
        "upn": "synthetic.a@moss.example",
        "name": "Synthetic A",
    }
    payload.update(claims or {})
    return jwt.encode(payload, keypair, algorithm="RS256", headers={"kid": KEY_ID})


# ---- the composed, authenticated gateway -------------------------------------


def _administer(engine: Engine, *statements: object) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def disposable_database() -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DATABASE}"'))
        url = configured.set(database=DATABASE).render_as_string(hide_password=False)
        yield url
    finally:
        _administer(maintenance, drop)
        maintenance.dispose()


def entra_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        auth_mode=AuthMode.ENTRA,
        entra_tenant_id=MOSS_TENANT,
        entra_client_id=CLIENT_ID,
        entra_issuer=ISSUER,
        entra_jwks_uri=JWKS_URI,
    )


@pytest.fixture
def authenticated_wire(
    disposable_database: str,
    public_jwk: jwt.PyJWK,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Wire]:
    """A real server composed in `entra` mode, over the disposable database.

    The one substitution is the key source: the composition root would fetch the
    issuer's JWKS over the network, and this hands it the in-process public key
    instead. Everything else — the verifier, its algorithm pin, the claim
    validation, the registry write, the transport — is the composed article.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", disposable_database)
    command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
    monkeypatch.setattr(gateway, "jwks_signing_key_source", lambda _uri: lambda _token: public_jwk)
    runtime = build_gateway_runtime(entra_settings(disposable_database))
    assert runtime.principal is None, "an authenticated composition has no process principal"
    assert runtime.authenticate is not None
    try:
        with serve(create_http_app(runtime.service, authenticate=runtime.authenticate)) as wire:
            yield wire
    finally:
        runtime.close()


def document(*, principal_id: str = "prn_correlationonly000000") -> dict[str, Any]:
    """One `capabilities.get` request document, as a transport would receive it.

    `principal_id` is present because `contracts.v1.RequestMetadata` requires it
    on every public request and its own docstring says what it is: correlation
    input. Its value here is deliberately not any principal the token resolves
    to, which is what makes the assertions below about it meaningful.
    """
    return {
        "request_id": "req-entra",
        "purpose": sorted(permitted_purposes(Capability.CAPABILITIES_GET))[0].value,
        "principal_id": principal_id,
        "requested_at": "2026-08-02T12:00:00Z",
        "payload": {},
    }


def send(
    wire: Wire, token: str | None, body: dict[str, Any] | None = None
) -> tuple[int, dict[str, str], str]:
    """One `capabilities.get` over the socket, with or without a credential."""
    encoded = json.dumps(body if body is not None else document())
    headers = {} if token is None else {"authorization": f"Bearer {token}"}
    return _raw(wire, encoded, headers)


def _raw(wire: Wire, encoded: str, headers: dict[str, str]) -> tuple[int, dict[str, str], str]:
    import http.client

    connection = http.client.HTTPConnection("127.0.0.1", wire.port, timeout=20.0)
    try:
        connection.request(
            "POST",
            f"/v1/{Capability.CAPABILITIES_GET.value}",
            body=encoded,
            headers={
                "content-type": "application/json",
                "content-length": str(len(encoded.encode())),
                **headers,
            },
        )
        response = connection.getresponse()
        return (
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read().decode(),
        )
    finally:
        connection.close()


def principal_ids(engine: Engine) -> list[str]:
    with engine.connect() as connection:
        return sorted(
            str(value)
            for value in connection.execute(
                text("SELECT principal_id FROM identity.user_accounts")
            ).scalars()
        )


# ---- the happy path, and the identity it resolves ----------------------------


def test_a_valid_token_authenticates_and_resolves_the_tokens_principal(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey, disposable_database: str
) -> None:
    """The positive control. Without it every refusal below could be a broken build."""
    status, _, body = send(authenticated_wire, mint(keypair))
    assert status == 200, body
    assert json.loads(body)["error"] is None

    engine = create_database_engine(disposable_database)
    try:
        registered = principal_ids(engine)
    finally:
        engine.dispose()
    assert len(registered) == 1, "one token, one registered account"


def test_two_principals_resolve_to_two_identities_and_neither_reaches_the_other(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey, disposable_database: str
) -> None:
    """Proof 7: two synthetic principals through the transport, two `principal_id`s.

    The audit is where the acting principal is recorded, so it is where the two
    are compared: each request is attributed to its own token's principal and to
    no other, and neither identifier appears against the other's request.
    """
    assert send(authenticated_wire, mint(keypair, oid=OID_A))[0] == 200
    assert send(authenticated_wire, mint(keypair, oid=OID_B))[0] == 200

    engine = create_database_engine(disposable_database)
    try:
        registered = principal_ids(engine)
        with engine.connect() as connection:
            acting = sorted(
                set(
                    connection.execute(
                        text("SELECT principal_id FROM knowledge.audit_events")
                    ).scalars()
                )
            )
    finally:
        engine.dispose()

    assert len(registered) == 2, f"two distinct oids registered {registered}"
    assert len(acting) == 2, f"the audit attributed the two requests to {acting}"
    # A repeat of the first token resolves to the identity it already had.
    assert send(authenticated_wire, mint(keypair, oid=OID_A))[0] == 200
    engine = create_database_engine(disposable_database)
    try:
        assert principal_ids(engine) == registered, "a second sign-in minted a new identity"
    finally:
        engine.dispose()


# ---- refusals ----------------------------------------------------------------


def test_a_foreign_tenant_token_is_refused_as_a_tenant_failure(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey, disposable_database: str
) -> None:
    """Proof 1. Refused at the transport, and refused *for the tenant*.

    The status alone would not distinguish a tenant refusal from any other, and
    the body deliberately says nothing, so the second half of the claim is made
    against the service directly: the same claims raise `ForeignTenantError`
    before any repository is reached, and no account row appears for them.
    """
    from my_pa.domain.identity.user_account import ForeignTenantError

    status, _, _ = send(authenticated_wire, mint(keypair, tid=FOREIGN_TENANT))
    assert status == 401

    engine = create_database_engine(disposable_database)
    try:
        assert principal_ids(engine) == [], "a foreign tenant reached the registry"
        service = PrincipalIdentityService(home_tenant_id=MOSS_TENANT)
        with engine.begin() as connection, pytest.raises(ForeignTenantError):
            service.authenticate(
                connection,
                claims={"tid": FOREIGN_TENANT, "oid": OID_A},
                now=datetime.now(UTC),
            )
    finally:
        engine.dispose()


def test_no_credential_at_all_is_refused(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey
) -> None:
    """A request with no `Authorization` header never reaches the application."""
    status, headers, body = send(authenticated_wire, None)
    assert status == 401
    assert headers["www-authenticate"] == "Bearer"
    assert json.loads(body)["code"] == "denied"


@pytest.mark.parametrize(
    "credential",
    ["", "Bearer", "Bearer   ", "Basic abcdef", "token-without-a-scheme"],
    ids=["empty", "scheme-only", "blank-token", "wrong-scheme", "no-scheme"],
)
def test_a_credential_that_is_not_a_bearer_token_is_refused(
    authenticated_wire: Wire, credential: str
) -> None:
    encoded = json.dumps(document())
    status, _, _ = _raw(authenticated_wire, encoded, {"authorization": credential})
    assert status == 401


def test_a_payload_naming_identity_is_refused(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey, disposable_database: str
) -> None:
    """Proof 2, first half: identity is not caller-suppliable.

    The *payload* is what MU-AC-02 governs, and it is checked on the
    authenticated path by `PrincipalIdentityService.authenticate` itself rather
    than by something a transport remembers to call. Each of the three forbidden
    keys is refused, at the top level and nested.

    The status is asserted to be `401` and not merely "not 200", because
    `capabilities.get` takes no payload field at all, so *any* extra key is also
    an `invalid_request`. `401` versus `400` is what distinguishes "the identity
    boundary refused this" from "the command constructor did", and the direct
    assertion below removes the capability from the question entirely.
    """
    identity = PrincipalIdentityService(home_tenant_id=MOSS_TENANT)
    engine = create_database_engine(disposable_database)
    try:
        for smuggled in (
            {"principal_id": "prn_smuggled00000000000000"},
            {"tid": MOSS_TENANT},
            {"oid": OID_B},
            {"nested": {"oid": OID_B}},
        ):
            with engine.begin() as connection, pytest.raises(CallerSuppliedPrincipalError):
                identity.authenticate(
                    connection,
                    claims={"tid": MOSS_TENANT, "oid": OID_A},
                    payload=smuggled,
                    now=datetime.now(UTC),
                )
    finally:
        engine.dispose()

    for payload in (
        {"principal_id": "prn_smuggled00000000000000"},
        {"tid": MOSS_TENANT},
        {"oid": OID_B},
        {"nested": {"oid": OID_B}},
    ):
        body = document()
        body["payload"] = payload
        status, _, rendered = send(authenticated_wire, mint(keypair), body)
        assert status == 401, f"{payload} was accepted: {rendered}"


def test_a_contradictory_envelope_cannot_shift_the_resolved_principal(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey, disposable_database: str
) -> None:
    """Proof 2, second half, and the stronger half.

    `RequestMetadata.principal_id` is a required contract field, so a request
    always names a principal. Two requests with the *same* token and two
    *different* stated principals must be attributed to one identity — the
    token's — and to neither of the two the caller named.
    """
    stated = ("prn_claimedaaaaaaaaaaaaaaa", "prn_claimedbbbbbbbbbbbbbbb")
    for claimed in stated:
        assert send(authenticated_wire, mint(keypair), document(principal_id=claimed))[0] == 200

    engine = create_database_engine(disposable_database)
    try:
        with engine.connect() as connection:
            acting = set(
                connection.execute(
                    text("SELECT principal_id FROM knowledge.audit_events")
                ).scalars()
            )
        registered = principal_ids(engine)
    finally:
        engine.dispose()

    assert len(registered) == 1, "the stated principals forked the registry"
    assert len(acting) == 1, f"two stated principals produced {acting}"
    assert not acting & set(stated), "a caller-stated principal became the acting one"


# ---- signature verification is real ------------------------------------------


@pytest.fixture
def verifier(public_jwk: jwt.PyJWK) -> EntraTokenVerifier:
    return EntraTokenVerifier(
        audience=CLIENT_ID, issuer=ISSUER, signing_key=lambda _token: public_jwk
    )


def test_the_algorithm_allowlist_is_rs256_and_nothing_else() -> None:
    """Pinned, so widening it is an edit here as well as there."""
    assert ALLOWED_ALGORITHMS == ("RS256",)


def test_an_alg_none_token_is_refused(verifier: EntraTokenVerifier) -> None:
    """Proof 5. The unsigned-token attack, minted exactly as an attacker would."""
    unsigned = jwt.encode(
        {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
            "nbf": int(datetime.now(UTC).timestamp()),
            "tid": MOSS_TENANT,
            "oid": OID_A,
        },
        key="",
        algorithm="none",
    )
    assert unsigned.split(".")[2] == "", "the fixture is not an unsigned token"
    with pytest.raises(TokenVerificationError):
        verifier.claims(unsigned)


def test_an_hs256_token_signed_with_the_rsa_public_key_is_refused(
    verifier: EntraTokenVerifier, keypair: rsa.RSAPrivateKey
) -> None:
    """Proof 5. The alg-confusion attack: the *public* key used as an HMAC secret.

    This is the defect a hand-written verifier ships with, and the reason
    `AGENTS.md` section 6 admits the dependency at all. The token is minted
    against PyJWT's own guard by encoding the header and payload by hand, so the
    test proves the *verifier* refuses it rather than that the minting library
    refused to build it.
    """
    from cryptography.hazmat.primitives import serialization

    public_pem = (
        keypair.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    import base64
    import hashlib
    import hmac

    def segment(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = segment(json.dumps({"alg": "HS256", "typ": "JWT", "kid": KEY_ID}).encode())
    payload = segment(
        json.dumps(
            {
                "iss": ISSUER,
                "aud": CLIENT_ID,
                "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp()),
                "nbf": int(datetime.now(UTC).timestamp()),
                "tid": MOSS_TENANT,
                "oid": OID_A,
            }
        ).encode()
    )
    signing_input = header + b"." + payload
    signature = segment(hmac.new(public_pem.encode(), signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + signature).decode()

    with pytest.raises(TokenVerificationError):
        verifier.claims(forged)


def test_a_tampered_signature_is_refused(
    verifier: EntraTokenVerifier, keypair: rsa.RSAPrivateKey
) -> None:
    header, payload, signature = mint(keypair).split(".")
    # The *first* character, not the last: base64url's final character carries
    # padding bits that decode to nothing, so flipping it can leave the signature
    # bytes identical and the test would pass by not having tampered at all.
    flipped = f"{'B' if signature.startswith('A') else 'A'}{signature[1:]}"
    assert flipped != signature
    with pytest.raises(TokenVerificationError):
        verifier.claims(f"{header}.{payload}.{flipped}")


def test_a_token_signed_by_another_key_is_refused(verifier: EntraTokenVerifier) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(TokenVerificationError):
        verifier.claims(mint(other))


@pytest.mark.parametrize(
    ("kwargs", "why"),
    [
        ({"lifetime": timedelta(minutes=-5)}, "expired"),
        ({"not_before": timedelta(minutes=30)}, "not-yet-valid"),
        ({"audience": "dddd0004-0000-0000-0000-000000000004"}, "wrong-audience"),
        ({"issuer": "https://login.example.invalid/somewhere-else/v2.0"}, "wrong-issuer"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_token_outside_its_registered_claims_is_refused(
    verifier: EntraTokenVerifier, keypair: rsa.RSAPrivateKey, kwargs: dict[str, Any], why: str
) -> None:
    """Proof 5: expired, not-yet-valid, wrong audience, wrong issuer."""
    with pytest.raises(TokenVerificationError):
        verifier.claims(mint(keypair, **kwargs))


def test_a_refusal_names_nothing_from_the_token(
    verifier: EntraTokenVerifier, keypair: rsa.RSAPrivateKey
) -> None:
    """The message is fixed, and the chain that would have carried PyJWT's is empty."""
    with pytest.raises(TokenVerificationError) as raised:
        verifier.claims(mint(keypair, audience="dddd0004-0000-0000-0000-000000000004"))
    rendered = str(raised.value)
    assert "audience" not in rendered.lower()
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_the_transport_refusal_echoes_no_token_or_claim(
    authenticated_wire: Wire, keypair: rsa.RSAPrivateKey
) -> None:
    """Nothing of the credential reaches the wire, in the body or in a header."""
    token = mint(keypair, tid=FOREIGN_TENANT)
    status, headers, body = send(authenticated_wire, token)
    assert status == 401
    rendered = " ".join(f"{k}: {v}" for k, v in headers.items()) + " " + body
    for secretish in (token, FOREIGN_TENANT, OID_A, MOSS_TENANT, "tid", "oid"):
        assert secretish not in rendered, f"{secretish!r} leaked into the refusal"


# ---- composition fails closed ------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    ["entra_tenant_id", "entra_client_id", "entra_issuer", "entra_jwks_uri"],
)
def test_entra_mode_without_its_configuration_refuses_to_start(missing: str) -> None:
    """Proof 3: unconfigured fails closed, and closed rather than downgraded."""
    values: dict[str, Any] = {
        "database_url": "postgresql+psycopg://my_pa@localhost:5433/my_pa",
        "auth_mode": AuthMode.ENTRA,
        "entra_tenant_id": MOSS_TENANT,
        "entra_client_id": CLIENT_ID,
        "entra_issuer": ISSUER,
        "entra_jwks_uri": JWKS_URI,
    }
    values[missing] = "   "
    with pytest.raises(Exception) as raised:
        Settings(**values)
    rendered = str(raised.value)
    assert f"{ENV_PREFIX}{missing.upper()}" in rendered
    assert AuthMode.LOCAL_OPERATOR.value in rendered, (
        "the refusal should say that it did not downgrade"
    )


def test_load_settings_refuses_an_unconfigured_entra_mode() -> None:
    """The same refusal through the supported entry point, as `SettingsError`."""
    with pytest.raises(SettingsError) as raised:
        load_settings(
            {
                f"{ENV_PREFIX}DATABASE_URL": "postgresql+psycopg://my_pa@localhost:5433/my_pa",
                f"{ENV_PREFIX}AUTH_MODE": "entra",
            }
        )
    assert f"{ENV_PREFIX}ENTRA_TENANT_ID" in str(raised.value)


def test_the_default_mode_is_the_unauthenticated_loopback_one() -> None:
    """Turning authentication *on* is the deliberate act; nothing turns it off."""
    settings = load_settings(
        {f"{ENV_PREFIX}DATABASE_URL": "postgresql+psycopg://my_pa@localhost:5433/my_pa"}
    )
    assert settings.auth_mode is AuthMode.LOCAL_OPERATOR


def test_an_unknown_auth_mode_is_refused_rather_than_ignored() -> None:
    with pytest.raises(SettingsError):
        load_settings(
            {
                f"{ENV_PREFIX}DATABASE_URL": "postgresql+psycopg://my_pa@localhost:5433/my_pa",
                f"{ENV_PREFIX}AUTH_MODE": "entra_but_not_really",
            }
        )


def test_the_transport_refuses_to_compose_with_both_or_neither() -> None:
    """No silent precedence between a fixed principal and an authenticator."""
    from tests.conftest import DEFAULT_LIMITS, operator

    from my_pa.application.service import ApplicationService

    service = ApplicationService(unit_of_work=lambda: None, limits=DEFAULT_LIMITS)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="exactly one"):
        create_http_app(service)
    with pytest.raises(ValueError, match="exactly one"):
        create_http_app(
            service, principal=operator(), authenticate=lambda _credential, _document: operator()
        )


def test_the_local_operator_composition_still_reads_no_credential(
    disposable_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`D-30` is unchanged: the default mode serves without a token, as before."""
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", disposable_database)
    command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
    runtime = build_gateway_runtime(Settings(database_url=disposable_database))
    assert runtime.authenticate is None
    assert runtime.principal is not None
    try:
        with serve(create_http_app(runtime.service, principal=runtime.principal)) as wire:
            assert send(wire, None)[0] == 200
    finally:
        runtime.close()


# ---- the service now has production call sites -------------------------------


def test_the_principal_identity_service_is_reached_from_the_composition_root() -> None:
    """It had none. `entra_authenticator` is the first, and this names it.

    A structural assertion rather than a behavioural one, because the
    behavioural claim is every test above: without the call site, none of them
    could pass.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(gateway))
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "PrincipalIdentityService" in constructed
    called: set[str] = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "authenticate" in called
