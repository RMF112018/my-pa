"""Reports Modernization WP02/WP03: the standalone report plane through the compact facade.

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

The synthetic client holds exactly the grants the `chatllm-data-v13` planner
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
  replay and list through the same compact client under the same profile;
* WP03 (`chatllm-data-v13`): `reports.update`, `reports.history`,
  `reports.archive`, `reports.delete` and `reports.restore` describe with their
  exact remote schemas, execute their canonical handlers through `my_pa.write`
  (the four writes) and `my_pa.read` (history), and read back from the
  database: a metadata update reuses the content object, a content update
  writes one, archive hides the report from a plain read, delete moves it to
  Trash with every version, manifest and receipt kept, restore after
  archive-then-delete returns it to `archived`, history pages versions and
  lifecycle events. A retry replays on the client-bound server key; a stale
  `expected_version` / `expected_lifecycle_revision` writes nothing.

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
UPDATE: Final = Capability.REPORTS_UPDATE
HISTORY: Final = Capability.REPORTS_HISTORY
ARCHIVE: Final = Capability.REPORTS_ARCHIVE
DELETE: Final = Capability.REPORTS_DELETE
RESTORE: Final = Capability.REPORTS_RESTORE
#: Reports Modernization WP03's four writes and its one read.
MANAGEMENT_WRITES: Final = (UPDATE, ARCHIVE, DELETE, RESTORE)
LIFECYCLE_MOVES: Final = (ARCHIVE, DELETE, RESTORE)
MANAGEMENT: Final = (*MANAGEMENT_WRITES, HISTORY)
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
#: Every table a WP03 update or lifecycle move may write.
MUTATION_TABLES: Final = (*PLANE_TABLES, "report_lifecycle_events")
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
    """What `profile-apply` installs for a fresh client under `chatllm-data-v13`."""
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
    assert diff.profile_version == CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v13"
    actions = plan_chatllm_grant_actions(diff, (), now=WHEN, resource=RESOURCE, scope=SCOPE)
    rows = tuple(
        (action.capability, action.purpose, action.is_write, None)
        for action in actions
        if action.kind == "add"
    )
    planned = {row[0] for row in rows}
    assert {PUBLISH, READ, TYPES_CREATE, TYPES_LIST} <= planned
    assert (PUBLISH, Purpose.REPORT_AUTHORING, True, None) in rows
    # chatllm-data-v13: the five management grants, `report_lifecycle` its own.
    assert {
        (UPDATE, Purpose.REPORT_AUTHORING, True, None),
        (HISTORY, Purpose.REPORT_READ, False, None),
        (ARCHIVE, Purpose.REPORT_LIFECYCLE, True, None),
        (DELETE, Purpose.REPORT_LIFECYCLE, True, None),
        (RESTORE, Purpose.REPORT_LIFECYCLE, True, None),
    } <= set(rows)
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
    """One HTTP answer: status, JSON body (if any), the request's and the response's byte counts."""

    status: int
    document: Any
    request_bytes: int
    response_bytes: int = 0


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
                    answers.append(
                        Exchange(
                            response.status_code, document, len(content), len(response.content)
                        )
                    )
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


def expected_key(
    payload: Mapping[str, Any], oauth_client_id: str, capability: Capability = PUBLISH
) -> str:
    """The server's derivation (`compose_remote_arguments`), restated to pin it."""
    keyed = {
        "capability": capability.value,
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


def test_describe_returns_the_exact_publish_and_read_remote_schemas(
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
    # WP05 B7: both encodings, the real executable limits, never chunked transfer.
    content_schema = payload["properties"]["content"]
    assert content_schema["description"] == (
        "markdown|text: {format, body}; json: {format, data}; mixed: {format, body, "
        "data}. encoding: omit or identity, or gzip+base64 with {format, encoding, "
        f"encoded}} instead of body/data. identity: at most {INLINE_CONTENT_MAX_BYTES:,} "
        "decoded UTF-8 bytes. gzip+base64: encoded is the standard padded Base64 (no "
        "whitespace) of exactly one gzip member whose gunzipped bytes are the UTF-8 body "
        "(markdown|text), a JSON text of the data (json) or a JSON object of exactly "
        "{body, data} (mixed); decoded content at most 16,777,216 bytes and at most 256:1 "
        "over the gzip bytes; json|mixed data at most 262,144 JSON values. Decoded "
        "content above the inline threshold (default "
        f"{INLINE_CONTENT_MAX_BYTES:,} bytes) is stored in the report content store when "
        "it is configured, otherwise refused (invalid_request content, max_bytes); reads "
        "return the body only up to 524,288 decoded bytes, larger bodies are marked "
        "body_omitted. The whole JSON request must also fit the "
        f"{MAX_REQUEST_BYTES:,}-byte request ceiling, so heavily escaped content (quotes, "
        "backslashes, control characters, \\u-escaped non-ASCII) may need to be smaller, "
        "and an encoded string is at most about 760 KB (about 570 KB of gzip)."
    )
    assert "chunk" not in content_schema["description"]
    assert content_schema["properties"]["encoding"]["enum"] == ["identity", "gzip+base64"]
    assert list(content_schema["properties"]) == [
        "format",
        "encoding",
        "body",
        "data",
        "encoded",
        "original_byte_count",
        "original_sha256",
        "uncompressed_byte_count",
        "uncompressed_sha256",
    ]
    for name, bound in (
        ("original_byte_count", 16_777_216),
        ("uncompressed_byte_count", 16_777_216),
    ):
        assert content_schema["properties"][name] == {
            "type": "integer",
            "minimum": 0,
            "maximum": bound,
            "description": content_schema["properties"][name]["description"],
        }
    for name in ("original_sha256", "uncompressed_sha256"):
        assert content_schema["properties"][name]["pattern"] == "^[0-9a-f]{64}$"
    assert content_schema["additionalProperties"] is False
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
        keys: dict[str, str] = {
            row[0]: row[1]
            for row in connection.execute(
                text("SELECT report_id, idempotency_key FROM knowledge.report_receipts")
            )
        }
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

    The same synthetic, planner-provisioned `chatllm-data-v13` client that reaches
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


# ---- Reports Modernization WP03: update, history, archive, delete, restore -------------

REASON: Final = "A synthetic revision."


def update_payload(
    report_id: str,
    version: int,
    patch: Mapping[str, Any],
    **extra: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "expected_version": version,
        "patch": dict(patch),
        "change_reason": REASON,
        **extra,
    }


def move_payload(report_id: str, revision: int, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"report_id": report_id, "expected_lifecycle_revision": revision, **extra}


def publish_one(harness: Harness, token: str) -> dict[str, Any]:
    (published,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL))])
    return ok(published)


def receipt_row(engine: Engine, receipt_id: str) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT * FROM knowledge.report_receipts WHERE receipt_id = :r"),
            {"r": receipt_id},
        ).one()


def test_describe_returns_the_exact_management_schemas(
    harness: Harness,
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    listed, *exact = harness.run(
        [(token, describe(feature="reports", limit=100))]
        + [(token, describe(capability=capability.value)) for capability in MANAGEMENT]
    )
    _failed, catalog = outcome(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    for capability in MANAGEMENT_WRITES:
        assert (items[capability.value]["kind"], items[capability.value]["feature"]) == (
            "write",
            "reports",
        )
        # Writes that move a head or a lifecycle are destructive (not additive).
        assert items[capability.value]["destructive"] is True
    assert (items[HISTORY.value]["kind"], items[HISTORY.value]["feature"]) == ("read", "reports")
    assert items[HISTORY.value]["destructive"] is False
    contracts = {}
    for answer, capability in zip(exact, MANAGEMENT, strict=True):
        _failed, contract = outcome(answer)
        expected = json.loads(json.dumps(remote_tool_schema(_TOOLS[capability.value].input_schema)))
        assert contract["input_schema"] == expected, capability
        assert contract["profile"] == "chatllm-gateway-v1"
        assert contract["item"]["capability"] == capability.value
        assert "idempotency_key" not in json.dumps(contract["input_schema"]), capability
        contracts[capability] = contract["input_schema"]["properties"]["payload"]
    update = contracts[UPDATE]
    assert update["required"] == ["report_id", "expected_version", "patch", "change_reason"]
    assert set(update["properties"]) == {
        "report_id",
        "expected_version",
        "patch",
        "clear_fields",
        "change_reason",
    }
    assert update["additionalProperties"] is False
    assert set(update["properties"]["patch"]["properties"]) == {
        "title",
        "content",
        "type",
        "topics",
        "tags",
        "summary",
        "report_date",
        "coverage_period",
        "metadata",
        "associations",
    }
    assert update["properties"]["patch"]["additionalProperties"] is False
    for capability in LIFECYCLE_MOVES:
        move = contracts[capability]
        assert move["required"] == ["report_id", "expected_lifecycle_revision"], capability
        assert set(move["properties"]) == {
            "report_id",
            "expected_lifecycle_revision",
            "reason",
        }, capability
        assert move["additionalProperties"] is False
    history = contracts[HISTORY]
    assert history["required"] == ["report_id"]
    assert set(history["properties"]) == {
        "report_id",
        "entries",
        "page_size",
        "after",
        "include_manifests",
        "include_withdrawn",
    }


def test_updates_execute_through_my_pa_write_and_read_back(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    published = publish_one(harness, token)
    rid = published["report_id"]
    metadata_patch = update_payload(rid, 1, {"title": "Revised title", "tags": ["risk"]})
    before = counts(harness.engine, MUTATION_TABLES)
    metadata, retry = harness.run(
        [
            (token, wrapped(WRITE_TOOL, UPDATE, metadata_patch)),
            (token, wrapped(WRITE_TOOL, UPDATE, metadata_patch)),
        ]
    )
    first, replayed = ok(metadata), ok(retry)
    assert (first["plane"], first["outcome"], first["change_kind"]) == (
        "standalone",
        "applied",
        "metadata",
    )
    assert first["version_number"] == 2 and first["replayed"] is False
    # A metadata-only update reuses the head's content object.
    assert first["content_id"] == published["content"]["content_id"]
    assert first["decoded_sha256"] == published["content"]["decoded_sha256"]
    # The identical retry replays the original answer on the client-bound key.
    assert replayed["replayed"] is True
    assert {k: v for k, v in replayed.items() if k != "replayed"} == {
        k: v for k, v in first.items() if k != "replayed"
    }
    after = counts(harness.engine, MUTATION_TABLES)
    assert {table: after[table] - before[table] for table in MUTATION_TABLES} == {
        "report_content_objects": 0,
        "report_roots": 0,
        "report_versions": 1,
        "report_version_manifests": 1,
        "report_associations": 0,
        "report_receipts": 1,
        "report_lifecycle_events": 0,
    }
    stored = receipt_row(harness.engine, first["receipt"]["receipt_id"])
    assert (stored.operation, stored.outcome, stored.report_id) == ("update", "applied", rid)
    assert (stored.expected_version_number, stored.resulting_version_number) == (1, 2)
    assert stored.version_id == first["version_id"]
    assert stored.owner_principal_id == remote_principal().principal_id
    assert stored.idempotency_key == expected_key(metadata_patch, CLIENT, UPDATE)

    body = "# Assessment\n\nRevised synthetic text."
    content_patch = update_payload(rid, 2, {"content": {"format": "markdown", "body": body}})
    stale_patch = update_payload(rid, 1, {"title": "Stale"})
    before = counts(harness.engine, MUTATION_TABLES)
    content, stale = harness.run(
        [
            (token, wrapped(WRITE_TOOL, UPDATE, content_patch)),
            (token, wrapped(WRITE_TOOL, UPDATE, stale_patch)),
        ]
    )
    second = ok(content)
    assert (second["change_kind"], second["version_number"]) == ("content", 3)
    assert second["content_id"] != published["content"]["content_id"]
    assert second["decoded_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    # The stale move refuses and writes nothing (the content update wrote 1 + 1 + 1 + 1).
    assert refusal(stale) == ("conflict", ["stale_version"])
    after = counts(harness.engine, MUTATION_TABLES)
    assert {table: after[table] - before[table] for table in MUTATION_TABLES} == {
        "report_content_objects": 1,
        "report_roots": 0,
        "report_versions": 1,
        "report_version_manifests": 1,
        "report_associations": 0,
        "report_receipts": 1,
        "report_lifecycle_events": 0,
    }
    with harness.engine.connect() as connection:
        root = connection.execute(
            text("SELECT * FROM knowledge.report_roots WHERE report_id = :r"), {"r": rid}
        ).one()
        versions = connection.execute(
            text(
                "SELECT version_number, content_id, change_kind, change_reason, title "
                "FROM knowledge.report_versions WHERE report_id = :r ORDER BY version_number"
            ),
            {"r": rid},
        ).all()
        manifest = connection.execute(
            text("SELECT * FROM knowledge.report_version_manifests WHERE version_id = :v"),
            {"v": second["version_id"]},
        ).one()
        stored_body = connection.execute(
            text("SELECT inline_text FROM knowledge.report_content_objects WHERE content_id = :c"),
            {"c": second["content_id"]},
        ).scalar_one()
    assert (root.head_version_id, root.head_version_number) == (second["version_id"], 3)
    assert [tuple(row) for row in versions] == [
        (1, published["content"]["content_id"], "initial", None, MINIMAL["title"]),
        (2, published["content"]["content_id"], "metadata", REASON, "Revised title"),
        (3, second["content_id"], "content", REASON, "Revised title"),
    ]
    assert manifest.manifest_sha256 == second["manifest_sha256"]
    assert manifest_digest(manifest.manifest) == second["manifest_sha256"]
    assert stored_body == body

    read, first_page, rest = harness.run(
        [
            (token, wrapped(READ_TOOL, READ, {"report_id": rid, "include_manifest": True})),
            (
                token,
                wrapped(
                    READ_TOOL,
                    HISTORY,
                    {"report_id": rid, "page_size": 2, "include_manifests": True},
                ),
            ),
            (token, wrapped(READ_TOOL, HISTORY, {"report_id": rid, "after": second["version_id"]})),
        ]
    )
    served = ok(read)
    assert (served["version_id"], served["version_number"]) == (second["version_id"], 3)
    assert (served["title"], served["tags"]) == ("Revised title", ["risk"])
    assert served["content"]["body"] == body
    assert served["change_reason"] == REASON
    assert served["manifest"] == manifest.manifest
    page = ok(first_page)
    assert (page["plane"], page["entries"], page["report_id"]) == ("standalone", "versions", rid)
    assert (page["head_version_id"], page["head_version_number"]) == (second["version_id"], 3)
    assert [item["version_number"] for item in page["items"]] == [1, 2]
    assert [item["change_kind"] for item in page["items"]] == ["initial", "metadata"]
    for item in page["items"]:
        assert manifest_digest(item["manifest"]) == item["manifest_sha256"]
        assert "body" not in item["content"]
    assert page["next_cursor"] == page["items"][-1]["version_id"]
    (more,) = harness.run(
        [(token, wrapped(READ_TOOL, HISTORY, {"report_id": rid, "after": page["next_cursor"]}))]
    )
    tail = ok(more)
    assert [item["version_number"] for item in tail["items"]] == [3]
    assert tail["next_cursor"] is None
    assert ok(rest)["items"] == []
    assert set(counts(harness.engine, INTELLIGENCE_TABLES).values()) == {0}


def test_archive_delete_restore_execute_through_my_pa_write_and_read_back(
    harness: Harness,
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    published = publish_one(harness, token)
    rid = published["report_id"]
    archive = move_payload(rid, 0, reason="Synthetic: superseded.")
    before = counts(harness.engine, MUTATION_TABLES)
    archived_answer, retry, stale = harness.run(
        [
            (token, wrapped(WRITE_TOOL, ARCHIVE, archive)),
            (token, wrapped(WRITE_TOOL, ARCHIVE, archive)),
            # A deliberate next move on the old revision: stale, nothing written.
            (token, wrapped(WRITE_TOOL, DELETE, move_payload(rid, 0))),
        ]
    )
    archived, replayed = ok(archived_answer), ok(retry)
    assert (archived["operation"], archived["outcome"]) == ("archive", "applied")
    assert (archived["prior_state"], archived["lifecycle_state"]) == ("active", "archived")
    assert archived["lifecycle_revision"] == 1
    assert archived["event_id"].startswith("grlev_")
    assert replayed["replayed"] is True
    assert {k: v for k, v in replayed.items() if k != "replayed"} == {
        k: v for k, v in archived.items() if k != "replayed"
    }
    assert refusal(stale) == ("conflict", ["expected_lifecycle_revision"])
    after = counts(harness.engine, MUTATION_TABLES)
    assert {table: after[table] - before[table] for table in MUTATION_TABLES} == {
        "report_content_objects": 0,
        "report_roots": 0,
        "report_versions": 0,
        "report_version_manifests": 0,
        "report_associations": 0,
        "report_receipts": 1,
        "report_lifecycle_events": 1,
    }
    stored = receipt_row(harness.engine, archived["receipt"]["receipt_id"])
    assert (stored.operation, stored.outcome, stored.event_id) == (
        "archive",
        "applied",
        archived["event_id"],
    )
    assert (stored.expected_lifecycle_revision, stored.resulting_lifecycle_revision) == (0, 1)
    assert stored.version_id is None
    assert stored.idempotency_key == expected_key(archive, CLIENT, ARCHIVE)

    hidden, shown = harness.run(
        [
            (token, wrapped(READ_TOOL, READ, {"report_id": rid})),
            (token, wrapped(READ_TOOL, READ, {"report_id": rid, "include_withdrawn": True})),
        ]
    )
    assert refusal(hidden) == ("not_found", ["artifact_id"])
    assert ok(shown)["lifecycle_state"] == "archived"
    assert ok(shown)["content"]["body"] == BODY

    kept = counts(harness.engine, ("report_versions", "report_version_manifests"))
    receipts_before = counts(harness.engine, ("report_receipts",))["report_receipts"]
    deleted_answer, restored_answer = harness.run(
        [
            (token, wrapped(WRITE_TOOL, DELETE, move_payload(rid, 1))),
            (token, wrapped(WRITE_TOOL, RESTORE, move_payload(rid, 2))),
        ]
    )
    deleted, restored = ok(deleted_answer), ok(restored_answer)
    assert (deleted["prior_state"], deleted["lifecycle_state"], deleted["lifecycle_revision"]) == (
        "archived",
        "trashed",
        2,
    )
    # Restore from Trash returns the state the delete left: archived.
    assert (
        restored["prior_state"],
        restored["lifecycle_state"],
        restored["lifecycle_revision"],
    ) == ("trashed", "archived", 3)
    # Trash is recoverable custody: every version, manifest and receipt is kept.
    assert counts(harness.engine, ("report_versions", "report_version_manifests")) == kept
    assert counts(harness.engine, ("report_receipts",))["report_receipts"] == receipts_before + 2
    with harness.engine.connect() as connection:
        root = connection.execute(
            text("SELECT * FROM knowledge.report_roots WHERE report_id = :r"), {"r": rid}
        ).one()
        events = connection.execute(
            text(
                "SELECT lifecycle_revision, operation, prior_state, resulting_state, "
                "predecessor_prior_state FROM knowledge.report_lifecycle_events "
                "WHERE report_id = :r ORDER BY lifecycle_revision"
            ),
            {"r": rid},
        ).all()
        operations = [
            row[0]
            for row in connection.execute(
                text(
                    "SELECT operation FROM knowledge.report_receipts WHERE report_id = :r "
                    "ORDER BY issued_at, operation"
                ),
                {"r": rid},
            ).all()
        ]
    assert (root.lifecycle_state, root.lifecycle_revision) == ("archived", 3)
    assert (root.head_version_id, root.head_version_number) == (published["version_id"], 1)
    assert [tuple(row) for row in events] == [
        (1, "archive", "active", "archived", None),
        (2, "delete", "archived", "trashed", "active"),
        (3, "restore", "trashed", "archived", "archived"),
    ]
    assert sorted(operations) == ["archive", "delete", "publish", "restore"]

    (history,) = harness.run(
        [
            (
                token,
                wrapped(
                    READ_TOOL,
                    HISTORY,
                    {"report_id": rid, "entries": "lifecycle", "include_withdrawn": True},
                ),
            )
        ]
    )
    page = ok(history)
    assert (page["entries"], page["lifecycle_state"], page["lifecycle_revision"]) == (
        "lifecycle",
        "archived",
        3,
    )
    assert [
        (item["operation"], item["prior_state"], item["resulting_state"]) for item in page["items"]
    ] == [
        ("archive", "active", "archived"),
        ("delete", "archived", "trashed"),
        ("restore", "trashed", "archived"),
    ]
    assert page["items"][0]["reason"] == "Synthetic: superseded."
    assert page["next_cursor"] is None
    assert set(counts(harness.engine, INTELLIGENCE_TABLES).values()) == {0}


def test_a_second_clients_identical_move_is_its_own_and_refuses_as_stale(
    harness: Harness,
) -> None:
    """The management keys bind the client: B's identical archive never replays A's."""
    grants = profile_grants(harness.service)
    token = harness.client(CLIENT, grants)
    other = harness.client(OTHER_CLIENT, grants)
    rid = publish_one(harness, token)["report_id"]
    archive = move_payload(rid, 0)
    (mine,) = harness.run([(token, wrapped(WRITE_TOOL, ARCHIVE, archive))])
    assert ok(mine)["replayed"] is False
    before = counts(harness.engine, MUTATION_TABLES)
    (theirs,) = harness.run([(other, wrapped(WRITE_TOOL, ARCHIVE, archive))])
    assert refusal(theirs) == ("conflict", ["expected_lifecycle_revision"])
    assert counts(harness.engine, MUTATION_TABLES) == before
    assert expected_key(archive, CLIENT, ARCHIVE) != expected_key(archive, OTHER_CLIENT, ARCHIVE)
