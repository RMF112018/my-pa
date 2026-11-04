"""Reports Modernization WP02: `reports.publish` and `reports.read` through the compact facade.

Spec C section 5 layers 7-12, end to end on PostgreSQL (`migrated_engine`, a
disposable current-head clone). Nothing here is a source-level check: every
request is an HTTP POST to the real remote MCP app (`create_remote_mcp_app`,
in process over httpx's ASGI transport), authenticated by the real
`RemoteAuthenticator` against the real durable store
(`RemoteIdentityRepository` over `identity.remote_clients`,
`identity.remote_capability_grants` and `identity.remote_security_controls`),
resolved by the composition root's own `apps.gateway.remote_access_context`
with a real `Settings` that selects the compact facade for the synthetic
clients, and served by a real `ApplicationService` on one SQL unit of work.

The synthetic client holds exactly the grants the `chatllm-data-v12` planner
provisions for a default composition (`plan_chatllm_grant_actions`), so this is
what an operator's `profile-apply` would give a ChatLLM client, not a
hand-picked grant set. What it proves:

* `my_pa.describe` returns the exact remote schema of `reports.publish` and of
  the extended `reports.read` (the canonical tool schema through
  `remote_tool_schema`), kind `write`/`read`, feature `reports`;
* `my_pa.write` `reports.publish` with only a title and a content object runs
  the canonical handler: the receipt, and a database readback of the root, the
  version, the content object, the manifest and the receipt -- whose
  idempotency key is the server's client-bound payload hash -- and no
  `knowledge.intelligence_*` row;
* `my_pa.read` `reports.read` of the `grpt_` id returns that exact version,
  digest and manifest;
* an identical retry replays the original receipt and writes nothing; a
  distinct `client_intent_id` publishes a second report; the same payload from
  a second client is that client's own report (the key binds the client);
* a 512 KiB markdown body publishes through `my_pa.write` under
  `MAX_REQUEST_BYTES` and reads back byte for byte;
* an existing pipeline `rpt_` report reads through `my_pa.read` exactly as the
  canonical local read answers it, and as `test_reports_legacy_read_golden`
  pinned it before the extension;
* `reports.types.create` / `reports.types.list` (layer 12) describe, write,
  replay and list through the same compact client under the same profile.

The refusals are in `tests/security/test_reports_compact_facade_adversarial.py`,
on this harness. Every identity, title and body here is synthetic; no real
client, grant or credential is read or written.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx2
import pytest
from apps.gateway import remote_access_context
from sqlalchemy import Engine, text, update
from tests.conftest import DEFAULT_LIMITS, metadata_for
from tests.unit.test_reports_legacy_read_golden import GOLDEN

from my_pa.adapters.mcp.chatllm_gateway import DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.mcp.remote import MCP_PATH, RemoteAccessContext, create_remote_mcp_app
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.adapters.remote_request import remote_tool_schema
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    chatllm_grant_purpose,
    composed_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
)
from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.binding import LOCAL_OPERATOR_UUID, capture_principal_id
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
from my_pa.domain.identity.operation import Capability, is_write_capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES
from my_pa.domain.reports.manifest import manifest_digest
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_security_controls,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.security.remote_oauth import (
    OriginTokenContext,
    RemoteAuthenticationError,
    RemoteAuthenticator,
)

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 4, 12, tzinfo=UTC)
RESOURCE: Final = "https://mcp.example.invalid/mcp"
ISSUER: Final = "https://issuer.example.invalid"
SCOPE: Final = "my-pa.read"
CLIENT: Final = "synthetic-reports-facade-client"
OTHER_CLIENT: Final = "synthetic-reports-facade-client-2"
PUBLISH: Final = Capability.REPORTS_PUBLISH
READ: Final = Capability.REPORTS_READ
TYPES_CREATE: Final = Capability.REPORTS_TYPES_CREATE
TYPES_LIST: Final = Capability.REPORTS_TYPES_LIST
BODY: Final = "# Assessment\n\nSynthetic standalone report text."
MINIMAL: Final[dict[str, Any]] = {
    "title": "Synthetic Schedule Risk Assessment",
    "content": {"format": "markdown", "body": BODY},
}
PLANE_TABLES: Final = (
    "report_content_objects",
    "report_roots",
    "report_versions",
    "report_version_manifests",
    "report_associations",
    "report_receipts",
)
INTELLIGENCE_TABLES: Final = (
    "intelligence_cycle_runs",
    "intelligence_producer_runs",
    "intelligence_artifacts",
)
_HEADERS: Final = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
_TOOLS: Final = {tool.name: tool for tool in TOOLS}

#: The default composition (no optional plane): what `_planes_from_settings`
#: gives a process with every optional switch at its default.
DEFAULT_PLANES: Final = ChatLLMCompositionPlanes(
    managed_documents=False,
    relationship_intelligence=False,
    relationship_intelligence_writes=False,
    relationship_memory=False,
    constraints=True,
)

#: One durable grant row: capability, purpose, is_write, expires_at.
type GrantRow = tuple[Capability, Purpose | None, bool, datetime | None]


def grant_row(
    capability: Capability,
    *,
    purpose: Purpose | None = None,
    is_write: bool | None = None,
    expires_at: datetime | None = None,
) -> GrantRow:
    """The planner's exact grant for `capability`, unless a field is overridden."""
    return (
        capability,
        chatllm_grant_purpose(capability) if purpose is None else purpose,
        is_write_capability(capability) if is_write is None else is_write,
        expires_at,
    )


def profile_grants(service: ApplicationService) -> tuple[GrantRow, ...]:
    """What `profile-apply` installs for a fresh client under `chatllm-data-v12`."""
    implemented = frozenset(service.available_capabilities)
    composed = composed_capabilities(implemented, DEFAULT_PLANES)
    diff = diff_chatllm_data_profile(
        implemented=implemented,
        composed=composed,
        grants=(),
        now=WHEN,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert diff.profile_version == CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v12"
    actions = plan_chatllm_grant_actions(diff, (), now=WHEN, resource=RESOURCE, scope=SCOPE)
    rows = tuple(
        (action.capability, action.purpose, action.is_write, None)
        for action in actions
        if action.kind == "add"
    )
    planned = {row[0] for row in rows}
    assert {PUBLISH, READ, TYPES_CREATE, TYPES_LIST} <= planned
    assert (PUBLISH, Purpose.REPORT_AUTHORING, True, None) in rows
    return rows


def remote_principal() -> Principal:
    """The one Principal every remote client acts for (`remote_client_is_local_operator`)."""
    return Principal(
        principal_id=capture_principal_id(LOCAL_OPERATOR_UUID),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def build_service(engine: Engine) -> ApplicationService:
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )


def counts(engine: Engine, tables: Iterable[str] = PLANE_TABLES) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
            )
            for table in tables
        }


@dataclass
class Exchange:
    """One HTTP answer: status, JSON body (if any) and the request's exact byte count."""

    status: int
    document: Any
    request_bytes: int


@dataclass
class Harness:
    """Synthetic durable clients and grants, and the real remote app over them."""

    engine: Engine
    service: ApplicationService
    tokens: dict[str, OriginTokenContext] = field(default_factory=dict)

    def gates(self, *, remote: bool = True, writes: bool = True) -> None:
        """The durable global switches (`identity.remote_security_controls`)."""
        with self.engine.begin() as connection:
            connection.execute(
                update(remote_security_controls).values(
                    remote_enabled=remote, writes_enabled=writes, updated_at=WHEN
                )
            )

    def client(
        self, oauth_client_id: str, grants: Iterable[GrantRow], *, writes: bool = True
    ) -> str:
        """Register one synthetic client with exactly `grants`; return its bearer token."""
        with self.engine.begin() as connection:
            repository = RemoteIdentityRepository(connection)
            client_uuid = repository.register_client(
                oauth_client_id=oauth_client_id,
                client_name="synthetic Reports facade client",
                redirect_uris='["https://client.example.invalid/callback"]',
                registered_scopes=SCOPE,
                now=WHEN,
                writes_enabled=writes,
            )
            for capability, purpose, is_write, expires_at in grants:
                # An already-expired grant was issued before it expired
                # (`remote_grant_expiry_is_after_creation`).
                issued = WHEN if expires_at is None else min(WHEN, expires_at - timedelta(days=1))
                repository.grant(
                    remote_client_id=client_uuid,
                    external_scope=SCOPE,
                    capability=capability,
                    now=issued,
                    is_write=is_write,
                    resource=RESOURCE,
                    expires_at=expires_at,
                    purpose=purpose,
                )
        token = f"tok-{oauth_client_id}"
        self.tokens[token] = OriginTokenContext(
            client_id=oauth_client_id, scopes=frozenset({SCOPE}), resource=RESOURCE
        )
        return token

    def revoke(self, oauth_client_id: str) -> None:
        with self.engine.begin() as connection:
            assert RemoteIdentityRepository(connection).revoke_client(
                oauth_client_id=oauth_client_id, now=WHEN
            )

    def app(self, *, process_writes: bool = True) -> Any:  # noqa: ANN401
        settings = Settings(
            database_url="postgresql+psycopg://synthetic@127.0.0.1:1/synthetic",
            mcp_chatllm_gateway_enabled=True,
            mcp_chatllm_gateway_oauth_client_ids=",".join(
                sorted(context.client_id for context in self.tokens.values())
            ),
        )
        authenticator = RemoteAuthenticator(
            token_context=self.tokens.get,
            connections=self.engine.begin,
            required_resource=RESOURCE,
            now=lambda: WHEN,
        )

        def resolve(header: str | None) -> RemoteAccessContext | None:
            try:
                authenticated = authenticator.authenticate(header)
            except RemoteAuthenticationError:
                return None
            return remote_access_context(settings, self.service, authenticated)

        return create_remote_mcp_app(
            self.service,
            resolve_access=resolve,
            allowed_hosts=("testserver",),
            remote_enabled=True,
            writes_enabled=process_writes,
            resource=RESOURCE,
            authorization_servers=(ISSUER,),
            scopes=frozenset({SCOPE}),
        )

    def run(
        self, requests: list[tuple[str, Mapping[str, Any]]], *, process_writes: bool = True
    ) -> list[Exchange]:
        app = self.app(process_writes=process_writes)

        async def exchange() -> list[Exchange]:
            answers: list[Exchange] = []
            async with (
                app.router.lifespan_context(app),
                httpx2.AsyncClient(
                    transport=httpx2.ASGITransport(app=app), base_url="http://testserver"
                ) as http,
            ):
                for token, body in requests:
                    content = json.dumps(body).encode()
                    response = await http.post(
                        MCP_PATH,
                        headers={**_HEADERS, "Authorization": f"Bearer {token}"},
                        content=content,
                    )
                    try:
                        document = response.json() if response.content else None
                    except json.JSONDecodeError:
                        # A transport refusal (e.g. 413) may answer in plain text.
                        document = response.text
                    answers.append(Exchange(response.status_code, document, len(content)))
            return answers

        return asyncio.run(exchange())


def call(name: str, arguments: Mapping[str, Any], request_id: int = 1) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def list_tools() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}


def wrapped(wrapper: str, capability: Capability, payload: Mapping[str, Any]) -> dict[str, Any]:
    return call(wrapper, {"capability": capability.value, "arguments": {"payload": payload}})


def describe(**arguments: Any) -> dict[str, Any]:  # noqa: ANN401
    return call(DESCRIBE_TOOL, arguments)


def outcome(answer: Exchange) -> tuple[bool, dict[str, Any]]:
    assert answer.status == 200, (answer.status, answer.document)
    result = answer.document["result"]
    (content,) = result["content"]
    return bool(result.get("isError")), json.loads(content["text"])


def ok(answer: Exchange) -> dict[str, Any]:
    failed, document = outcome(answer)
    assert not failed, document
    result = document.get("result", document)
    assert isinstance(result, dict)
    return result


def refusal(answer: Exchange) -> tuple[str, list[str]]:
    failed, document = outcome(answer)
    assert failed, document
    problem = document.get("error", document)
    return str(problem["code"]), list(problem.get("safe_details") or [])


def expected_key(payload: Mapping[str, Any], oauth_client_id: str) -> str:
    """The server's derivation (`compose_remote_arguments`), restated to pin it."""
    keyed = {
        "capability": PUBLISH.value,
        "principal_id": remote_principal().principal_id,
        "payload": dict(payload),
        "client": oauth_client_id,
    }
    digest = hashlib.sha256(json.dumps(keyed, sort_keys=True, default=str).encode()).hexdigest()
    return f"idk_{digest[:32]}"


@pytest.fixture
def harness(migrated_engine: Engine) -> Harness:
    built = Harness(migrated_engine, build_service(migrated_engine))
    built.gates()
    return built


# ---- describe ----------------------------------------------------------------------


def test_describe_returns_the_exact_remote_schemas_under_the_v12_profile(
    harness: Harness,
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    tools, listed, publish, read = harness.run(
        [
            (token, list_tools()),
            (token, describe(feature="reports", limit=100)),
            (token, describe(capability=PUBLISH.value)),
            (token, describe(capability=READ.value)),
        ]
    )
    names = {tool["name"] for tool in tools.document["result"]["tools"]}
    # The facade adds no top-level tool: no `reports.*` name is ever listed.
    assert names == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}
    _failed, catalog = outcome(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    assert {PUBLISH.value, READ.value, TYPES_CREATE.value, TYPES_LIST.value} <= set(items)
    assert (items[PUBLISH.value]["kind"], items[PUBLISH.value]["feature"]) == ("write", "reports")
    assert (items[READ.value]["kind"], items[READ.value]["feature"]) == ("read", "reports")
    assert items[PUBLISH.value]["destructive"] is False
    assert items[PUBLISH.value]["summary"] == _TOOLS[PUBLISH.value].description

    for answer, capability in ((publish, PUBLISH), (read, READ)):
        _failed, contract = outcome(answer)
        expected = json.loads(json.dumps(remote_tool_schema(_TOOLS[capability.value].input_schema)))
        assert contract["input_schema"] == expected, capability
        assert contract["profile"] == "chatllm-gateway-v1"
    _failed, publish_contract = outcome(publish)
    payload = publish_contract["input_schema"]["properties"]["payload"]
    assert payload["required"] == ["title", "content"]
    # The advertised limit is decoded bytes; the wire bound is stated beside it,
    # with the transport's own ceiling, so an escape-heavy body is not a surprise.
    assert payload["properties"]["content"]["description"] == (
        "markdown|text: {format, body}; json: {format, data}; mixed: {format, body, "
        f"data}}. At most {INLINE_CONTENT_MAX_BYTES:,} decoded UTF-8 bytes; the whole "
        f"JSON request must also fit the {MAX_REQUEST_BYTES:,}-byte request ceiling, "
        "so heavily escaped content (quotes, backslashes, control characters, "
        "\\u-escaped non-ASCII) may need to be smaller. encoding: omit or identity "
        "(gzip+base64 is not supported yet)."
    )
    assert "client_intent_id" in payload["properties"]
    for server_owned in (
        "idempotency_key",
        "principal_id",
        "purpose",
        "created_at",
        "report_id",
        "version_id",
        "receipt_id",
        "verification",
        "cycle_run_id",
        "stage",
    ):
        assert server_owned not in payload["properties"], server_owned
    _failed, read_contract = outcome(read)
    read_payload = read_contract["input_schema"]["properties"]["payload"]["properties"]
    assert {
        "report_id",
        "version_id",
        "version_number",
        "include_manifest",
        "include_withdrawn",
    } <= (set(read_payload))


# ---- publish, read, replay -----------------------------------------------------------


def test_write_publishes_through_the_canonical_handler_and_reads_back(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine)
    (published,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL))])
    receipt = ok(published)
    assert receipt["plane"] == "standalone"
    assert receipt["report_id"].startswith("grpt_")
    assert receipt["version_id"].startswith("grver_")
    assert (
        receipt["version_number"],
        receipt["lifecycle_state"],
        receipt["lifecycle_revision"],
    ) == (
        1,
        "active",
        0,
    )
    assert receipt["replayed"] is False
    assert receipt["recorded_at"] == "2026-11-04T12:00:00.000Z"
    digest = hashlib.sha256(BODY.encode()).hexdigest()
    assert receipt["content"]["decoded_sha256"] == digest
    assert receipt["content"]["decoded_byte_count"] == len(BODY.encode())
    assert receipt["content"]["format"] == "markdown"
    after = counts(harness.engine)
    assert {table: after[table] - before[table] for table in PLANE_TABLES} == {
        "report_content_objects": 1,
        "report_roots": 1,
        "report_versions": 1,
        "report_version_manifests": 1,
        "report_associations": 0,
        "report_receipts": 1,
    }
    owner = remote_principal().principal_id
    with harness.engine.connect() as connection:
        root = connection.execute(
            text("SELECT * FROM knowledge.report_roots WHERE report_id = :r"),
            {"r": receipt["report_id"]},
        ).one()
        version = connection.execute(
            text("SELECT * FROM knowledge.report_versions WHERE version_id = :v"),
            {"v": receipt["version_id"]},
        ).one()
        content = connection.execute(
            text("SELECT * FROM knowledge.report_content_objects WHERE content_id = :c"),
            {"c": version.content_id},
        ).one()
        manifest = connection.execute(
            text("SELECT * FROM knowledge.report_version_manifests WHERE version_id = :v"),
            {"v": receipt["version_id"]},
        ).one()
        stored_receipt = connection.execute(
            text("SELECT * FROM knowledge.report_receipts WHERE receipt_id = :r"),
            {"r": receipt["receipt_id"]},
        ).one()
    assert (root.owner_principal_id, root.head_version_id, root.head_version_number) == (
        owner,
        receipt["version_id"],
        1,
    )
    assert (root.lifecycle_state, root.lifecycle_revision) == ("active", 0)
    assert (version.owner_principal_id, version.report_id, version.version_number) == (
        owner,
        receipt["report_id"],
        1,
    )
    assert version.title == MINIMAL["title"]
    assert version.content_id == receipt["content"]["content_id"]
    assert content.owner_principal_id == owner
    assert (content.inline_text, content.decoded_sha256) == (BODY, digest)
    assert content.decoded_byte_count == len(BODY.encode())
    assert manifest.manifest_sha256 == receipt["manifest_sha256"]
    assert manifest_digest(manifest.manifest) == receipt["manifest_sha256"]
    assert "principal_id" not in json.dumps(manifest.manifest)
    assert (stored_receipt.operation, stored_receipt.outcome) == ("publish", "applied")
    assert stored_receipt.owner_principal_id == owner
    assert (stored_receipt.report_id, stored_receipt.version_id) == (
        receipt["report_id"],
        receipt["version_id"],
    )
    # The receipt's key is the server's client-bound payload hash.
    assert stored_receipt.idempotency_key == expected_key(MINIMAL, CLIENT)
    assert set(counts(harness.engine, INTELLIGENCE_TABLES).values()) == {0}

    (read,) = harness.run(
        [
            (
                token,
                wrapped(
                    READ_TOOL, READ, {"report_id": receipt["report_id"], "include_manifest": True}
                ),
            )
        ]
    )
    served = ok(read)
    assert served["plane"] == "standalone"
    assert (served["report_id"], served["version_id"]) == (
        receipt["report_id"],
        receipt["version_id"],
    )
    assert served["title"] == MINIMAL["title"]
    assert served["content"]["body"] == BODY
    assert served["content"]["decoded_sha256"] == digest
    assert served["manifest_sha256"] == receipt["manifest_sha256"]
    assert served["manifest"] == manifest.manifest
    assert manifest_digest(served["manifest"]) == receipt["manifest_sha256"]


def test_a_retry_replays_and_a_distinct_intent_or_client_is_a_new_report(
    harness: Harness,
) -> None:
    grants = profile_grants(harness.service)
    token = harness.client(CLIENT, grants)
    other = harness.client(OTHER_CLIENT, grants)
    intended = {**MINIMAL, "client_intent_id": "synthetic-intent-2"}
    first, retry = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL)),
            (token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL)),
        ]
    )
    after_first = counts(harness.engine)
    created, replayed = ok(first), ok(retry)
    assert replayed["replayed"] is True
    assert {key: value for key, value in replayed.items() if key != "replayed"} == {
        key: value for key, value in created.items() if key != "replayed"
    }
    assert after_first["report_roots"] == 1 and after_first["report_receipts"] == 1

    intent, from_other = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, intended)),
            (other, wrapped(WRITE_TOOL, PUBLISH, MINIMAL)),
        ]
    )
    second, third = ok(intent), ok(from_other)
    assert second["replayed"] is False and third["replayed"] is False
    assert len({created["report_id"], second["report_id"], third["report_id"]}) == 3
    # Identical content, so identical digests; three roots, three receipts.
    assert second["content"]["decoded_sha256"] == created["content"]["decoded_sha256"]
    assert counts(harness.engine)["report_roots"] == 3
    assert counts(harness.engine)["report_receipts"] == 3
    with harness.engine.connect() as connection:
        keys = dict(
            connection.execute(
                text("SELECT report_id, idempotency_key FROM knowledge.report_receipts")
            ).all()
        )
    assert keys == {
        created["report_id"]: expected_key(MINIMAL, CLIENT),
        second["report_id"]: expected_key(intended, CLIENT),
        third["report_id"]: expected_key(MINIMAL, OTHER_CLIENT),
    }
    assert set(counts(harness.engine, INTELLIGENCE_TABLES).values()) == {0}


def _large_markdown() -> str:
    """Realistic multi-line markdown of exactly `INLINE_CONTENT_MAX_BYTES` UTF-8 bytes."""
    lines = ["# Synthetic large report\n"]
    number = 0
    size = len(lines[0])
    while True:
        line = f"- Line {number:06d}: synthetic schedule risk narrative, no real data.\n"
        if size + len(line) > INLINE_CONTENT_MAX_BYTES:
            break
        lines.append(line)
        size += len(line)
        number += 1
    lines.append("x" * (INLINE_CONTENT_MAX_BYTES - size))
    body = "".join(lines)
    assert len(body.encode()) == INLINE_CONTENT_MAX_BYTES
    return body


def test_a_512_kib_markdown_report_publishes_through_my_pa_write(harness: Harness) -> None:
    """The advertised inline limit is executable over the compact remote facade.

    The whole HTTP body -- JSON-RPC envelope, facade wrapper and the JSON-escaped
    body (one extra byte per newline) -- stays under `MAX_REQUEST_BYTES`, the
    transport's own request ceiling.
    """
    token = harness.client(CLIENT, profile_grants(harness.service))
    body = _large_markdown()
    payload = {**MINIMAL, "content": {"format": "markdown", "body": body}}
    (published,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, payload))])
    assert INLINE_CONTENT_MAX_BYTES == 524_288
    assert MAX_REQUEST_BYTES == 762_288
    assert INLINE_CONTENT_MAX_BYTES < published.request_bytes < MAX_REQUEST_BYTES
    receipt = ok(published)
    assert receipt["content"]["decoded_byte_count"] == INLINE_CONTENT_MAX_BYTES
    assert receipt["content"]["decoded_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    (read,) = harness.run([(token, wrapped(READ_TOOL, READ, {"report_id": receipt["report_id"]}))])
    served = ok(read)
    assert served["content"]["body"] == body
    assert served["content"]["decoded_byte_count"] == INLINE_CONTENT_MAX_BYTES
    with harness.engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT c.inline_text FROM knowledge.report_content_objects c "
                "JOIN knowledge.report_versions v ON v.content_id = c.content_id "
                "WHERE v.version_id = :v"
            ),
            {"v": receipt["version_id"]},
        ).scalar_one()
    assert stored == body


# ---- legacy rpt_ read ------------------------------------------------------------------

_LEGACY_BODY: Final = "# Collector\n\nGolden legacy read body."


def _legacy_report(service: ApplicationService, principal: Principal) -> dict[str, str]:
    """The golden's pipeline artifact, committed through the canonical local path."""
    begun = service.invoke(
        metadata_for(BeginIntelligenceCycle.capability, Purpose.REPORT_AUTHORING, principal),
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key="golden-cycle",
        ),
        principal=principal,
    )
    assert begun.result is not None, begun.error
    committed = service.invoke(
        metadata_for(CommitIntelligenceArtifact.capability, Purpose.REPORT_AUTHORING, principal),
        CommitIntelligenceArtifact(
            cycle_run_id=str(begun.result["cycle_run_id"]),
            stage=IntelligenceStage.COLLECTOR,
            artifact_kind=ArtifactKind.COLLECTOR_CANDIDATES,
            producer_task_id="task-golden",
            producer_task_name="Golden collector",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title="Golden collector",
            body_markdown=_LEGACY_BODY,
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key="golden-collector",
            focus_area_id=FocusAreaId.COMMUNICATIONS,
            structured_content={"items": [1, 2], "note": "synthetic"},
        ),
        principal=principal,
    )
    assert committed.result is not None, committed.error
    return {
        "report_id": str(committed.result["report_id"]),
        "report_run_id": str(committed.result["report_run_id"]),
        "cycle_run_id": str(begun.result["cycle_run_id"]),
    }


def test_a_legacy_rpt_read_through_the_facade_is_unchanged(harness: Harness) -> None:
    principal = remote_principal()
    ids = _legacy_report(harness.service, principal)
    token = harness.client(CLIENT, profile_grants(harness.service))
    (answer,) = harness.run([(token, wrapped(READ_TOOL, READ, {"report_id": ids["report_id"]}))])
    remote = ok(answer)
    metadata, command = normalize(
        READ.value,
        {
            "request_id": "req-legacy-local",
            "purpose": Purpose.REPORT_READ.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": {"report_id": ids["report_id"]},
        },
    )
    local = harness.service.invoke(metadata, command, principal=principal)
    assert local.error is None, local.error
    assert remote == local.model_dump(mode="json")["result"]
    # The golden's `body` answer, captured before the `grpt_` extension, with
    # the minted identifiers and this database's commit time substituted.
    golden = json.loads(GOLDEN)["body"]["result"]
    expected = {
        **golden,
        "report_id": ids["report_id"],
        "report_run_id": ids["report_run_id"],
        "cycle_run_id": ids["cycle_run_id"],
        "committed_at": remote["committed_at"],
    }
    assert remote == expected
    assert "plane" not in remote


# ---- layer 12: the report type registry on the same compact client ---------------------


def test_report_types_create_and_list_through_the_same_compact_client(harness: Harness) -> None:
    """Reconciliation regression for `reports.types.create` / `list` on the compact facade.

    The same synthetic, planner-provisioned `chatllm-data-v12` client that reaches
    `reports.publish` describes both registry names with their exact remote
    schemas, registers a kind through `my_pa.write` (an identical retry replays,
    a changed one conflicts) and lists it through `my_pa.read`. It pins repository
    behavior only; it asserts nothing about any deployed environment.
    """
    token = harness.client(CLIENT, profile_grants(harness.service))
    definition = {
        "artifact_kind": "synthetic_weekly_digest",
        "stage": "reporter",
        "description": "A synthetic facade report type.",
    }
    listed, create_contract, list_contract, created, again, changed, wrong, kinds = harness.run(
        [
            (token, describe(feature="reports", kind="write", limit=100)),
            (token, describe(capability=TYPES_CREATE.value)),
            (token, describe(capability=TYPES_LIST.value)),
            (token, wrapped(WRITE_TOOL, TYPES_CREATE, definition)),
            (token, wrapped(WRITE_TOOL, TYPES_CREATE, definition)),
            (token, wrapped(WRITE_TOOL, TYPES_CREATE, {**definition, "description": "Changed."})),
            (token, wrapped(READ_TOOL, TYPES_CREATE, definition)),
            (token, wrapped(READ_TOOL, TYPES_LIST, {"stage": "reporter"})),
        ]
    )
    _failed, catalog = outcome(listed)
    writes = {item["capability"] for item in catalog["items"]}
    assert {TYPES_CREATE.value, PUBLISH.value} <= writes
    assert TYPES_LIST.value not in writes
    for answer, capability in ((create_contract, TYPES_CREATE), (list_contract, TYPES_LIST)):
        _failed, contract = outcome(answer)
        expected = json.loads(json.dumps(remote_tool_schema(_TOOLS[capability.value].input_schema)))
        assert contract["input_schema"] == expected, capability
        assert "idempotency_key" not in json.dumps(contract["input_schema"])
    first, replay = ok(created), ok(again)
    assert (first["created"], first["replayed"]) == (True, False)
    assert (replay["created"], replay["replayed"]) == (False, True)
    assert refusal(changed) == ("conflict", ["artifact_kind"])
    assert refusal(wrong)[0] == "invalid_request"
    registered = [(row["artifact_kind"], row["origin"]) for row in ok(kinds)["report_types"]]
    assert ("synthetic_weekly_digest", "client") in registered
