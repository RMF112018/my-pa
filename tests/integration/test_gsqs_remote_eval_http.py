"""Contract/integration tests for GSQS remote-eval Streamable HTTP MCP.

Phase A sessions are built locally. Remote tools never open repetitions.
Synthetic Partition-B PNGs only. No ChatLLM, no Phase C, no network.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from sqlalchemy import Connection, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

import my_pa.infrastructure.gsqs_routellm_transport as routellm
from my_pa.adapters.gsqs_remote_eval_mcp import (
    DEFAULT_EVAL_RESOURCE,
    EVAL_OAUTH_SCOPE,
    EVAL_TOOL_NEXT,
    EVAL_TOOL_STATUS,
    EVAL_TOOL_SUBMIT,
    create_gsqs_remote_eval_app,
)
from my_pa.adapters.http.oauth import build_origin_oauth_routes
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_CAPTURE_CONFLICT,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_SESSION_NOT_IN_PROGRESS,
    EVENT_DISCLOSED_TO_TRANSPORT,
    EVENT_OUTBOUND_ATTEMPT_STARTED,
    REPETITIONS_REQUIRED,
    RemoteEvalSessionState,
)
from my_pa.infrastructure.persistence.remote_identity import REMOTE_IDENTITY_METADATA
from my_pa.infrastructure.security.gsqs_remote_eval_authentication import (
    GsqsRemoteEvalAuthenticationError,
    GsqsRemoteEvalAuthenticator,
)
from my_pa.infrastructure.security.origin_authorization import OriginOAuthServer
from tests.integration.gsqs_remote_eval_harness import (
    ALLOWED_HOSTS,
    AUTHORIZATION_SERVERS,
    BEARER_AUTHORIZATION,
    EVAL_TOOL_NAMES,
    PRODUCTION_TOOL_NAMES,
    FakeAuthenticator,
    assert_eval_tool_annotations,
    assert_eval_tool_schemas,
    assert_no_image,
    call_next,
    call_status,
    call_submit,
    capture_path,
    connected_eval_session,
    empty_eval_service,
    error_code,
    eval_app,
    forbid_external_io,
    image_blocks,
    in_progress_session,
    journal_event_types,
    png_bytes,
    png_image,
    running_eval_http,
    text_payload,
)
from tests.unit.test_goodnotes_gsqs_remote_eval_orchestration import (
    ALTERNATE_SEGMENTS,
    EXPECTED_CASE_IDS,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def no_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routellm, "post_chat_completion", forbid_external_io)
    monkeypatch.setattr("urllib.request.urlopen", forbid_external_io)


def _assert_eval_tools_only(names: set[str]) -> None:
    assert names == set(EVAL_TOOL_NAMES)
    for production in PRODUCTION_TOOL_NAMES:
        assert production not in names
    assert "goodnotes.eval.open_repetition" not in names
    assert "open_repetition" not in names


async def test_one_case_canary_through_streamable_http(
    tmp_path: Path, no_external_io: None
) -> None:
    service, store, state_root, session_id, generate = in_progress_session(
        tmp_path, session_id="http-canary"
    )
    segments = generate.synthetic_segments()
    app = eval_app(service)

    async with running_eval_http(app) as http:
        async with connected_eval_session(http) as session:
            listed = await session.list_tools()
            names = tuple(tool.name for tool in listed.tools)
            assert names == EVAL_TOOL_NAMES
            _assert_eval_tools_only(set(names))
            assert_eval_tool_schemas(listed.tools)
            assert_eval_tool_annotations(listed.tools)

            extra_status = await session.call_tool(EVAL_TOOL_STATUS, {"unexpected": True})
            assert extra_status.is_error is True
            assert error_code(extra_status) == ERROR_INTERNAL_FAIL_CLOSED
            assert_no_image(extra_status)

            extra_next = await session.call_tool(EVAL_TOOL_NEXT, {"extra": 1})
            assert extra_next.is_error is True
            assert error_code(extra_next) == ERROR_INTERNAL_FAIL_CLOSED
            assert_no_image(extra_next)

            status = await call_status(session)
            assert status.is_error is False
            status_body = text_payload(status)
            assert status_body["state"] == RemoteEvalSessionState.IN_PROGRESS
            assert status_body["repetitions_required"] == REPETITIONS_REQUIRED
            assert status_body["cases_per_repetition"] == CASES_PER_REPETITION
            assert status_body["next_case_ordinal"] == 1
            assert "session_id" not in status_body
            assert_no_image(status)

            first = await call_next(session)
            assert first.is_error is False
            first_body = text_payload(first)
            lease_id = first_body["lease_id"]
            assert isinstance(lease_id, str) and lease_id
            assert first_body["ordinal"] == 1
            assert first_body["repetition"] == 1
            assert first_body["mime_type"] == "image/png"
            png = png_bytes(first)
            assert sha256(png).hexdigest() == first_body["content_sha256"]
            assert len(png) == first_body["byte_length"]

            events = journal_event_types(state_root, session_id)
            assert EVENT_OUTBOUND_ATTEMPT_STARTED in events
            assert EVENT_DISCLOSED_TO_TRANSPORT in events
            assert events.index(EVENT_OUTBOUND_ATTEMPT_STARTED) < events.index(
                EVENT_DISCLOSED_TO_TRANSPORT
            )

            opened = await session.call_tool("goodnotes.eval.open_repetition", {"repetition": 2})
            assert opened.is_error is True
            assert_no_image(opened)
            for production in PRODUCTION_TOOL_NAMES:
                refused = await session.call_tool(production, {})
                assert refused.is_error is True
                assert_no_image(refused)

        async with connected_eval_session(http) as session:
            replay = await call_next(session)
            assert replay.is_error is False
            replay_body = text_payload(replay)
            assert replay_body["lease_id"] == lease_id
            assert replay_body["ordinal"] == 1
            png_image(replay)

            extra_submit = await session.call_tool(
                EVAL_TOOL_SUBMIT,
                {"lease_id": lease_id, "segments": segments, "session_id": "forged"},
            )
            assert extra_submit.is_error is True
            assert error_code(extra_submit) == ERROR_INTERNAL_FAIL_CLOSED
            assert_no_image(extra_submit)

            submitted = await call_submit(session, lease_id=lease_id, segments=segments)
            assert submitted.is_error is False
            submit_body = text_payload(submitted)
            assert submit_body["ordinal"] == 1
            assert submit_body["duplicate"] is False
            assert_no_image(submitted)
            capture_identity = submit_body["capture_identity_sha256"]
            assert isinstance(capture_identity, str) and len(capture_identity) == 64

            durable = capture_path(state_root, session_id, 1, 1, "syn-b-001")
            assert durable.is_file()
            stored = store.load_capture(session_id, 1, "syn-b-001")
            assert stored is not None
            assert stored.lease_id == lease_id
            assert stored.ordinal == 1
            assert stored.content_sha256 == first_body["content_sha256"]
            assert stored.content_sha256 == sha256(png).hexdigest()
            assert stored.capture_identity_sha256 == capture_identity

            duplicate = await call_submit(session, lease_id=lease_id, segments=segments)
            assert duplicate.is_error is False
            duplicate_body = text_payload(duplicate)
            assert duplicate_body["duplicate"] is True
            assert duplicate_body["capture_identity_sha256"] == capture_identity

            conflict = await call_submit(session, lease_id=lease_id, segments=ALTERNATE_SEGMENTS)
            assert conflict.is_error is True
            assert error_code(conflict) == ERROR_CAPTURE_CONFLICT
            assert_no_image(conflict)

        async with connected_eval_session(http) as session:
            following = await call_next(session)
            assert following.is_error is False
            following_body = text_payload(following)
            assert following_body["ordinal"] == 2
            assert following_body["lease_id"] != lease_id
            png_image(following)
            progressed = store.load_state(session_id)
            assert progressed is not None
            assert progressed.state is RemoteEvalSessionState.IN_PROGRESS


async def test_submit_accepts_the_published_minimal_note_unit_payload(
    tmp_path: Path, no_external_io: None
) -> None:
    service, store, state_root, session_id, _generate = in_progress_session(
        tmp_path, session_id="http-schema-canary"
    )
    app = eval_app(service)
    async with running_eval_http(app) as http, connected_eval_session(http) as session:
        listed = await session.list_tools()
        submit_tool = next(tool for tool in listed.tools if tool.name == EVAL_TOOL_SUBMIT)
        schema = getattr(submit_tool, "inputSchema", None) or submit_tool.input_schema
        assert isinstance(schema, dict)
        example = schema["properties"]["segments"]["items"]["examples"][0]
        first = await call_next(session)
        lease_id = text_payload(first)["lease_id"]
        submitted = await call_submit(session, lease_id=lease_id, segments=[example])
        assert submitted.is_error is False
        body = text_payload(submitted)
        assert body["ordinal"] == 1
        assert body["duplicate"] is False
        stored = store.load_capture(session_id, 1, "syn-b-001")
        assert stored is not None
        assert stored.segments[0]["kind"] == "NOTE_UNIT"
        assert stored.segments[0]["confidence"]["transcription"] == 0.92
    _ = state_root


async def test_no_session_returns_no_active_session_without_image(
    tmp_path: Path, no_external_io: None
) -> None:
    service, _store, _state_root = empty_eval_service(tmp_path)
    app = eval_app(service)
    async with running_eval_http(app) as http, connected_eval_session(http) as session:
        listed_tools = (await session.list_tools()).tools
        listed = {tool.name for tool in listed_tools}
        _assert_eval_tools_only(listed)
        assert_eval_tool_schemas(listed_tools)
        assert_eval_tool_annotations(listed_tools)
        for name, arguments in (
            (EVAL_TOOL_STATUS, {}),
            (EVAL_TOOL_NEXT, {}),
            (EVAL_TOOL_SUBMIT, {"lease_id": "lease-missing", "segments": []}),
        ):
            result = await session.call_tool(name, arguments)
            assert result.is_error is True
            assert error_code(result) == ERROR_NO_ACTIVE_SESSION
            assert_no_image(result)


async def test_foreign_principal_is_forbidden_without_image(
    tmp_path: Path, no_external_io: None
) -> None:
    service, _store, _state_root, _session_id, generate = in_progress_session(
        tmp_path, session_id="http-foreign"
    )
    app = eval_app(service, authenticator=FakeAuthenticator("foreign-principal"))
    segments = generate.synthetic_segments()
    async with running_eval_http(app) as http, connected_eval_session(http) as session:
        for name, arguments in (
            (EVAL_TOOL_STATUS, {}),
            (EVAL_TOOL_NEXT, {}),
            (EVAL_TOOL_SUBMIT, {"lease_id": "lease-foreign", "segments": segments}),
        ):
            result = await session.call_tool(name, arguments)
            assert result.is_error is True
            assert error_code(result) == ERROR_FORBIDDEN_SCOPE
            assert_no_image(result)
            assert image_blocks(result) == []


async def test_disabled_app_returns_404_for_mcp(tmp_path: Path, no_external_io: None) -> None:
    app = create_gsqs_remote_eval_app(
        FakeAuthenticator(),
        enabled=False,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=(),
        resource="https://my-pa-gsqs.bobby-fetting.me/mcp",
        authorization_servers=AUTHORIZATION_SERVERS,
    )
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        refused = await client.post(
            "/mcp",
            headers={"Authorization": BEARER_AUTHORIZATION},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        health = await client.get("/healthz")
    assert refused.status_code == 404
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


@pytest.mark.slow
async def test_219_remote_protocol_next_submit_pairs(tmp_path: Path, no_external_io: None) -> None:
    """73 cases x 3 repetitions through MCP tools/call, not service.submit_capture.

    Marked ``slow`` so FAST (60s) deselects it. Gates run this test explicitly.
    Opening later repetitions uses the local operator/service API, not remote tools.
    """

    service, store, state_root, session_id, generate = in_progress_session(
        tmp_path, session_id="http-219"
    )
    segments = generate.synthetic_segments()
    expected_cases = {case.ordinal: case for case in generate.manifest_cases()}
    app = eval_app(service)
    pairs = 0

    async with running_eval_http(app) as http, connected_eval_session(http) as session:
        listed_tools = (await session.list_tools()).tools
        listed = {tool.name for tool in listed_tools}
        _assert_eval_tools_only(listed)
        assert_eval_tool_schemas(listed_tools)
        assert_eval_tool_annotations(listed_tools)
        extra_keys = await session.call_tool(EVAL_TOOL_STATUS, {"unexpected": True})
        assert extra_keys.is_error is True
        assert error_code(extra_keys) == ERROR_INTERNAL_FAIL_CLOSED
        assert_no_image(extra_keys)

        for repetition in range(1, REPETITIONS_REQUIRED + 1):
            if repetition > 1:
                blocked_next = await call_next(session)
                assert blocked_next.is_error is True
                assert error_code(blocked_next) == ERROR_SESSION_NOT_IN_PROGRESS
                assert_no_image(blocked_next)
                blocked_submit = await call_submit(
                    session, lease_id="not-a-current-lease", segments=segments
                )
                assert blocked_submit.is_error is True
                assert error_code(blocked_submit) == ERROR_SESSION_NOT_IN_PROGRESS
                assert_no_image(blocked_submit)
                service.open_repetition(session_id, repetition)

            for ordinal, case_id in enumerate(EXPECTED_CASE_IDS, start=1):
                acquired = await call_next(session)
                assert acquired.is_error is False, (repetition, ordinal, acquired.content)
                body = text_payload(acquired)
                assert body["ordinal"] == ordinal
                assert body["repetition"] == repetition
                assert body["content_sha256"] == expected_cases[ordinal].content_sha256
                assert body["mime_type"] == "image/png"
                png_image(acquired)
                if ordinal == 1:
                    png = png_bytes(acquired)
                    assert sha256(png).hexdigest() == body["content_sha256"]
                lease_id = body["lease_id"]
                assert isinstance(lease_id, str)

                receipt = await call_submit(session, lease_id=lease_id, segments=segments)
                assert receipt.is_error is False, (repetition, ordinal, receipt.content)
                submitted = text_payload(receipt)
                assert submitted["ordinal"] == ordinal
                assert submitted["repetition"] == repetition
                assert submitted["duplicate"] is False
                assert_no_image(receipt)
                capture_identity = submitted["capture_identity_sha256"]
                assert isinstance(capture_identity, str) and len(capture_identity) == 64
                stored = store.load_capture(session_id, repetition, case_id)
                assert stored is not None
                assert stored.lease_id == lease_id
                assert stored.content_sha256 == body["content_sha256"]
                assert stored.capture_identity_sha256 == capture_identity
                pairs += 1

                if ordinal == CASES_PER_REPETITION:
                    assert capture_path(
                        state_root, session_id, repetition, ordinal, case_id
                    ).is_file()

            state = store.load_state(session_id)
            assert state is not None
            assert len(store.list_captures(session_id, repetition)) == CASES_PER_REPETITION
            if repetition < REPETITIONS_REQUIRED:
                assert state.state is RemoteEvalSessionState.REPETITION_COMPLETE
                public = text_payload(await call_status(session))
                assert public["state"] == RemoteEvalSessionState.REPETITION_COMPLETE
            else:
                assert state.state is RemoteEvalSessionState.COMPLETE

        terminal_status = await call_status(session)
        assert terminal_status.is_error is True
        assert error_code(terminal_status) == ERROR_NO_ACTIVE_SESSION
        assert_no_image(terminal_status)
        terminal_next = await call_next(session)
        assert terminal_next.is_error is True
        assert error_code(terminal_next) == ERROR_NO_ACTIVE_SESSION
        assert_no_image(terminal_next)
        terminal_submit = await call_submit(
            session, lease_id="not-a-current-lease", segments=segments
        )
        assert terminal_submit.is_error is True
        assert error_code(terminal_submit) == ERROR_NO_ACTIVE_SESSION
        assert_no_image(terminal_submit)

    assert pairs == CASES_PER_REPETITION * REPETITIONS_REQUIRED
    assert pairs == 219
    final = store.load_state(session_id)
    assert final is not None
    assert final.captures_accepted == 219
    events = journal_event_types(state_root, session_id)
    assert events.count(EVENT_OUTBOUND_ATTEMPT_STARTED) == 219
    assert events.count(EVENT_DISCLOSED_TO_TRANSPORT) == 219
    assert capture_path(state_root, session_id, 3, 73, "syn-b-073").is_file()


EVAL_ISSUER = "https://my-pa-gsqs.bobby-fetting.me"
EVAL_OPERATOR_SECRET = "s" * 43
CHATLLM_REDIRECT = "https://abacus.ai/oauth/callback"
PKCE_VERIFIER = "v" * 43
PKCE_CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(PKCE_VERIFIER.encode()).digest()).rstrip(b"=").decode()
)
OAUTH_ROUTE_PATHS = (
    "/.well-known/oauth-authorization-server",
    "/oauth/register",
    "/oauth/authorize",
    "/oauth/token",
    "/oauth/revoke",
)


@pytest.fixture
def eval_identity_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS identity")
        REMOTE_IDENTITY_METADATA.create_all(connection)
    yield engine
    engine.dispose()


def _eval_oauth_app(
    tmp_path: Path, engine: Engine
) -> tuple[object, OriginOAuthServer, GsqsRemoteEvalAuthenticator]:
    @contextmanager
    def connections() -> Iterator[Connection]:
        with engine.begin() as connection:
            yield connection

    authorization_server = OriginOAuthServer(
        connections=connections,
        issuer=EVAL_ISSUER,
        resource=DEFAULT_EVAL_RESOURCE,
        supported_scopes=frozenset({EVAL_OAUTH_SCOPE}),
        now=lambda: datetime(2026, 8, 23, 12, tzinfo=UTC),
    )
    authenticator = GsqsRemoteEvalAuthenticator(
        token_context=authorization_server.introspect,
        connections=connections,
        required_resource=DEFAULT_EVAL_RESOURCE,
        required_scope=EVAL_OAUTH_SCOPE,
    )
    service, _store, _state_root = empty_eval_service(tmp_path)
    app = create_gsqs_remote_eval_app(
        authenticator,
        service,
        enabled=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=(),
        resource=DEFAULT_EVAL_RESOURCE,
        authorization_servers=(EVAL_ISSUER,),
        scopes=frozenset({EVAL_OAUTH_SCOPE}),
        extra_routes=build_origin_oauth_routes(
            authorization_server, operator_secret=EVAL_OPERATOR_SECRET
        ),
    )
    return app, authorization_server, authenticator


async def test_enabled_eval_app_exposes_origin_oauth_http_routes(
    tmp_path: Path, no_external_io: None, eval_identity_engine: Engine
) -> None:
    app, _server, _authenticator = _eval_oauth_app(tmp_path, eval_identity_engine)
    paths = {getattr(route, "path", None) for route in app.routes}
    for path in OAUTH_ROUTE_PATHS:
        assert path in paths
    methods_by_path = {
        getattr(route, "path", None): set(getattr(route, "methods", ()) or ())
        for route in app.routes
    }
    assert "GET" in methods_by_path["/.well-known/oauth-authorization-server"]
    assert "POST" in methods_by_path["/oauth/register"]
    assert {"GET", "POST"} <= methods_by_path["/oauth/authorize"]
    assert "POST" in methods_by_path["/oauth/token"]
    assert "POST" in methods_by_path["/oauth/revoke"]

    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        metadata = await client.get("/.well-known/oauth-authorization-server")
        register = await client.post("/oauth/register", content=b"{")
        authorize = await client.get("/oauth/authorize")
        token = await client.post("/oauth/token", data={"grant_type": "authorization_code"})
        revoke = await client.post("/oauth/revoke", data={"token": "not-a-live-token"})
    assert metadata.status_code == 200
    document = metadata.json()
    assert document["issuer"] == EVAL_ISSUER
    assert document["scopes_supported"] == [EVAL_OAUTH_SCOPE]
    assert "my-pa.read" not in document["scopes_supported"]
    assert register.status_code == 400
    assert authorize.status_code == 400
    assert token.status_code == 400
    assert revoke.status_code == 200
    assert EVAL_OPERATOR_SECRET not in metadata.text


async def test_eval_dcr_pkce_issues_token_for_eval_resource_and_scope(
    tmp_path: Path, no_external_io: None, eval_identity_engine: Engine
) -> None:
    app, _server, authenticator = _eval_oauth_app(tmp_path, eval_identity_engine)
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
        ) as client,
    ):
        registered = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatLLM",
                "redirect_uris": [CHATLLM_REDIRECT],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": EVAL_OAUTH_SCOPE,
            },
        )
        assert registered.status_code == 201
        client_id = str(registered.json()["client_id"])
        authorization = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CHATLLM_REDIRECT,
            "scope": EVAL_OAUTH_SCOPE,
            "state": "eval-synthetic-state",
            "code_challenge": PKCE_CHALLENGE,
            "code_challenge_method": "S256",
            "resource": DEFAULT_EVAL_RESOURCE,
        }
        consent = await client.get("/oauth/authorize", params=authorization)
        assert consent.status_code == 200
        approved = await client.post(
            "/oauth/authorize",
            data={**authorization, "operator_secret": EVAL_OPERATOR_SECRET, "decision": "approve"},
        )
        assert approved.status_code == 303
        query = parse_qs(urlsplit(approved.headers["location"]).query)
        issued = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": query["code"][0],
                "client_id": client_id,
                "redirect_uri": CHATLLM_REDIRECT,
                "code_verifier": PKCE_VERIFIER,
                "resource": DEFAULT_EVAL_RESOURCE,
            },
        )
        assert issued.status_code == 200
        tokens = issued.json()
        access_token = str(tokens["access_token"])
        principal = authenticator.authenticate(f"Bearer {access_token}")
        assert principal.resource == DEFAULT_EVAL_RESOURCE
        assert EVAL_OAUTH_SCOPE in principal.scopes
        revoked = await client.post("/oauth/revoke", data={"token": access_token})
        assert revoked.status_code == 200
    assert EVAL_OPERATOR_SECRET not in registered.text
    assert EVAL_OPERATOR_SECRET not in approved.headers.get("location", "")
    with pytest.raises(GsqsRemoteEvalAuthenticationError) as error:
        authenticator.authenticate(f"Bearer {access_token}")
    assert error.value.code == "UNAUTHENTICATED"
