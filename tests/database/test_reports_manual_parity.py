"""Reports Modernization WP07 (RM-AC-019): the manual BFF path and the MCP facade are one use case.

The manual Reports UI reaches Python through exactly one transport: the BFF's
`web/src/lib/api/gateway.ts` builds a document from `web/src/contracts/gateway.json`
and POSTs it to `/v1/{capability}` on the HTTP gateway (`create_http_app`). The
ChatLLM client reaches the same plane through the compact remote MCP facade
(`my_pa.write` / `my_pa.read`). This module drives ONE scenario through BOTH,
against ONE `ApplicationService` on one disposable current-head PostgreSQL clone
(`migrated_engine`) with a real `FilesystemReportContentStore` and
`FilesystemReportTransferStaging` on one `tmp_path` root:

* publish -> read -> update -> stale update -> archive -> delete -> restore ->
  history (versions and lifecycle): the same recursive result key shape at every
  step, the same version succession, the same lifecycle states and revisions,
  the same receipt key set, and the same refusal (code and safe detail) for the
  stale compare-and-set;
* a report written through one path reads identically through the other;
* an unknown and a foreign report are the same bare `not_found` on both paths
  (no existence oracle), and an unknown payload field is `invalid_request` on
  both, writing nothing;
* refusal before mutation: the gateway composed in per-request mode answers an
  uncredentialed request `401` and the facade refuses an unknown token (`401`)
  and an ungranted client, each with zero report rows written;
* `reports.hold.place` cannot be addressed from the BFF contract at all;
* a report whose inline publish request would exceed 512 KiB publishes over the
  HTTP gateway through begin -> append x N -> finalize -> publish (transfer
  reference) and reads back byte-exact through `reports.transfer.read_chunk`.

The HTTP gateway is served on a real loopback socket by `tests.wire.serve` (the
repository's one HTTP test client; Starlette's `TestClient` needs `httpx`, which
this package does not depend on). The facade harness is
`tests/contract/test_reports_compact_facade.py`'s, composed the way
`tests/contract/test_reports_transfer_compact_facade.py` composes it.

One structural difference is by design and asserted, not hidden: the BFF sends a
browser-generated `idempotency_key` in the payload (it is in gateway.json's
`payloadFields`), while the remote facade never accepts one and derives a
client-bound key server-side. Every identity, title and byte here is synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol

import pytest
from sqlalchemy import Engine

from my_pa.adapters.http import create_http_app
from my_pa.adapters.mcp.chatllm_gateway import READ_TOOL, WRITE_TOOL
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.gateway import local_principal
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.user_account import TokenClaimsError
from tests.conftest import operator
from tests.contract.test_reports_compact_facade import (
    CLIENT,
    MUTATION_TABLES,
    Exchange,
    Harness,
    counts,
    grant_row,
    outcome,
    wrapped,
)
from tests.contract.test_reports_transfer_compact_facade import (
    build_transfer_service,
    markdown_text,
    transfer_grants,
)
from tests.wire import Reply, Wire, serve

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
CONTRACT_PATH: Final = ROOT / "web" / "src" / "contracts" / "gateway.json"
#: `correlationPrincipalId`'s shape (`prn_` + 32 hex); correlation input only.
SESSION_CORRELATION: Final = "prn_" + "7e57ab1e" * 4
#: The BFF's inline-vs-transfer rule (contract U6): a request above this goes by transfer.
INLINE_REQUEST_LIMIT: Final = 524_288
UNKNOWN_REPORT: Final = "grpt_00000000nothere0"
TITLE: Final = "Synthetic parity report"
BODY: Final = "# Parity\n\nSynthetic manual-path text."
REASON: Final = "Synthetic parity revision."
#: Every table a report publish, update, lifecycle move or transfer may write.
REPORT_TABLES: Final = (
    *MUTATION_TABLES,
    "report_transfer_sessions",
    "report_transfer_chunks",
)


# ---- the BFF contract ------------------------------------------------------------------


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    """The shared BFF request contract: every HTTP document below is built from it."""
    loaded = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


_REQUESTS = iter(range(1, 10**9))


def bff_document(
    contract: Mapping[str, Any], capability: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """One document, assembled as `gateway.ts::buildRequestDocument` assembles it.

    The envelope keys, the payload key and the purpose are read off gateway.json
    (`contract["capabilities"][capability]` raises `KeyError` for a capability
    the BFF cannot address); `None` entries are dropped as the BFF drops
    `undefined`; the capability itself is routed on, never in the document.
    """
    entry = contract["capabilities"][capability]
    document = {
        "contract_version": contract["contractVersion"],
        "request_id": f"bff-parity-{next(_REQUESTS)}",
        "purpose": entry["purpose"],
        "principal_id": SESSION_CORRELATION,
        "requested_at": "2026-11-07T12:00:00Z",
        contract["payloadKey"]: {k: v for k, v in payload.items() if v is not None},
    }
    assert set(document) - {contract["payloadKey"]} == set(contract["envelopeFields"])
    return document


# ---- one answer, whichever path produced it -------------------------------------------


@dataclass(frozen=True)
class Answer:
    """A path-neutral answer: the result on success, else the code and safe details."""

    result: dict[str, Any] | None
    code: str | None = None
    safe_details: tuple[str, ...] = ()

    def ok(self) -> dict[str, Any]:
        assert self.result is not None, (self.code, self.safe_details)
        return self.result

    def refusal(self) -> tuple[str | None, tuple[str, ...]]:
        assert self.result is None, "expected a refusal"
        return self.code, self.safe_details


def _from_problem(problem: Mapping[str, Any]) -> Answer:
    return Answer(None, str(problem["code"]), tuple(problem.get("safe_details") or ()))


class ReportPath(Protocol):
    name: str

    def call(self, capability: Capability, payload: Mapping[str, Any], *, key: str) -> Answer:
        """Invoke `capability`; `key` names this intent (the BFF's idempotency key)."""
        ...


class HttpPath:
    """The BFF's transport: gateway.json documents to `/v1/{capability}`."""

    name = "http"

    def __init__(self, wire: Wire, contract: Mapping[str, Any]) -> None:
        self.wire = wire
        self.contract = contract
        self.requests: list[int] = []

    def send(self, capability: str, payload: Mapping[str, Any]) -> Reply:
        document = bff_document(self.contract, capability, payload)
        size = len(json.dumps(document).encode())
        self.requests.append(size)
        return self.wire.send(capability, document)

    def call(self, capability: Capability, payload: Mapping[str, Any], *, key: str) -> Answer:
        fields = self.contract["capabilities"][capability.value]["payloadFields"]
        sent = dict(payload)
        if "idempotency_key" in fields:
            sent["idempotency_key"] = f"bff-{key}"
        reply = self.send(capability.value, sent)
        document = reply.document()
        if reply.status == 200:
            assert document.get("error") is None
            assert document.get("disclosure") is not None
            result = document["result"]
            assert isinstance(result, dict)
            return Answer(result)
        problem = document.get("error") if "error" in document else document
        assert isinstance(problem, Mapping), document
        return _from_problem(problem)


class McpPath:
    """The remote compact facade: `my_pa.write` / `my_pa.read` over the real remote app."""

    name = "mcp"

    def __init__(self, harness: Harness, token: str) -> None:
        self.harness = harness
        self.token = token

    def exchange(self, capability: Capability, payload: Mapping[str, Any]) -> Exchange:
        (purpose,) = permitted_purposes(capability)
        tool = READ_TOOL if purpose.value == "report_read" else WRITE_TOOL
        (answer,) = self.harness.run([(self.token, wrapped(tool, capability, payload))])
        return answer

    def call(self, capability: Capability, payload: Mapping[str, Any], *, key: str) -> Answer:
        del key  # the facade derives its own client-bound key; it never accepts one
        failed, document = outcome(self.exchange(capability, payload))
        if failed:
            return _from_problem(document.get("error", document))
        result = document.get("result", document)
        assert isinstance(result, dict)
        return Answer(result)


def shape(value: Any) -> Any:  # noqa: ANN401 - any JSON value
    """The recursive key structure of a JSON value: keys and types, never values."""
    if isinstance(value, Mapping):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [shape(item) for item in value]
    return type(value).__name__


# ---- composition -----------------------------------------------------------------------


@pytest.fixture
def service(migrated_engine: Engine, tmp_path: Path) -> ApplicationService:
    return build_transfer_service(migrated_engine, (tmp_path / "report-content").resolve())


@pytest.fixture
def facade(migrated_engine: Engine, service: ApplicationService) -> Harness:
    built = Harness(migrated_engine, service)
    built.gates()
    return built


@pytest.fixture
def mcp(facade: Harness, service: ApplicationService) -> McpPath:
    return McpPath(facade, facade.client(CLIENT, transfer_grants(service)))


@pytest.fixture
def http(service: ApplicationService, contract: dict[str, Any]) -> Iterator[HttpPath]:
    """The gateway composed as `apps/gateway.py` composes local_operator mode."""
    with serve(create_http_app(service, principal=local_principal())) as wire:
        yield HttpPath(wire, contract)


# ---- the scenario ----------------------------------------------------------------------


@dataclass
class Walk:
    """Every answer one path gave along the scenario, by step name."""

    steps: dict[str, Answer]
    report_id: str


def walk(path: ReportPath) -> Walk:
    """publish -> read -> update -> stale update -> archive -> delete -> restore -> history."""
    steps: dict[str, Answer] = {}
    tag = path.name
    steps["publish"] = path.call(
        Capability.REPORTS_PUBLISH,
        {
            "title": TITLE,
            "content": {"format": "markdown", "body": BODY},
            "tags": ["parity"],
            "summary": "Synthetic summary.",
        },
        key=f"{tag}-publish",
    )
    rid = str(steps["publish"].ok()["report_id"])
    steps["read"] = path.call(Capability.REPORTS_READ, {"report_id": rid}, key="")
    steps["update"] = path.call(
        Capability.REPORTS_UPDATE,
        {
            "report_id": rid,
            "expected_version": 1,
            "patch": {"title": f"{TITLE}, revised"},
            "change_reason": REASON,
        },
        key=f"{tag}-update",
    )
    steps["stale_update"] = path.call(
        Capability.REPORTS_UPDATE,
        {
            "report_id": rid,
            "expected_version": 1,
            "patch": {"title": "Stale"},
            "change_reason": REASON,
        },
        key=f"{tag}-stale",
    )
    for name, capability, revision in (
        ("archive", Capability.REPORTS_ARCHIVE, 0),
        ("delete", Capability.REPORTS_DELETE, 1),
        ("restore", Capability.REPORTS_RESTORE, 2),
    ):
        steps[name] = path.call(
            capability,
            {"report_id": rid, "expected_lifecycle_revision": revision, "reason": "Synthetic."},
            key=f"{tag}-{name}",
        )
    steps["read_withdrawn"] = path.call(
        Capability.REPORTS_READ, {"report_id": rid, "include_withdrawn": True}, key=""
    )
    for entries in ("versions", "lifecycle"):
        steps[f"history_{entries}"] = path.call(
            Capability.REPORTS_HISTORY,
            {"report_id": rid, "entries": entries, "include_withdrawn": True},
            key="",
        )
    return Walk(steps, rid)


def _comparable(result: Mapping[str, Any]) -> dict[str, Any]:
    """The values both paths must agree on (identifiers and times differ by construction)."""
    picked = {
        name: result[name]
        for name in (
            "plane",
            "outcome",
            "operation",
            "change_kind",
            "version_number",
            "lifecycle_state",
            "prior_state",
            "lifecycle_revision",
            "replayed",
            "title",
            "tags",
            "entries",
            "head_version_number",
        )
        if name in result
    }
    if "items" in result:
        picked["items"] = [
            {
                name: item[name]
                for name in (
                    "version_number",
                    "change_kind",
                    "change_reason",
                    "title",
                    "operation",
                    "prior_state",
                    "resulting_state",
                    "lifecycle_revision",
                    "reason",
                )
                if name in item
            }
            for item in result["items"]
        ]
    return picked


def receipt_keys(result: Mapping[str, Any]) -> set[str]:
    """A write's receipt: the nested `receipt` object (update, lifecycle) or the
    publish receipt's top-level `receipt_*` fields."""
    if "receipt" in result:
        return set(result["receipt"])
    return {name for name in result if name.startswith("receipt")}


def receipt_id(result: Mapping[str, Any]) -> str:
    return str(result["receipt"]["receipt_id"] if "receipt" in result else result["receipt_id"])


def test_one_scenario_is_the_same_use_case_through_the_bff_gateway_and_the_facade(
    http: HttpPath, mcp: McpPath, facade: Harness
) -> None:
    by_http, by_mcp = walk(http), walk(mcp)
    assert by_http.report_id != by_mcp.report_id
    assert list(by_http.steps) == list(by_mcp.steps)
    for step, ours in by_http.steps.items():
        theirs = by_mcp.steps[step]
        if step == "stale_update":
            # The same refusal class and safe detail on both, before any write.
            assert ours.refusal() == theirs.refusal() == ("conflict", ("stale_version",)), step
            continue
        assert shape(ours.ok()) == shape(theirs.ok()), step
        assert _comparable(ours.ok()) == _comparable(theirs.ok()), step

    steps = by_http.steps
    # The version succession and the lifecycle walk, stated once (both paths agree above).
    assert (steps["publish"].ok()["version_number"], steps["update"].ok()["version_number"]) == (
        1,
        2,
    )
    assert [
        (
            steps[name].ok()["prior_state"],
            steps[name].ok()["lifecycle_state"],
            steps[name].ok()["lifecycle_revision"],
        )
        for name in ("archive", "delete", "restore")
    ] == [("active", "archived", 1), ("archived", "trashed", 2), ("trashed", "archived", 3)]
    assert [item["version_number"] for item in steps["history_versions"].ok()["items"]] == [1, 2]
    assert [item["operation"] for item in steps["history_lifecycle"].ok()["items"]] == [
        "archive",
        "delete",
        "restore",
    ]
    # Receipts: the same key set for every write on both paths.
    for step in ("publish", "update", "archive", "delete", "restore"):
        written, served = by_http.steps[step].ok(), by_mcp.steps[step].ok()
        assert receipt_keys(written) == receipt_keys(served) != set(), step
        assert receipt_id(written) != receipt_id(served), step
    # The two reports are distinct roots of the one plane, both now archived at revision 3.
    assert counts(facade.engine, ("report_roots", "report_lifecycle_events")) == {
        "report_roots": 2,
        "report_lifecycle_events": 6,
    }


def test_a_report_written_through_one_path_reads_identically_through_the_other(
    http: HttpPath, mcp: McpPath
) -> None:
    by_http = http.call(
        Capability.REPORTS_PUBLISH,
        {"title": TITLE, "content": {"format": "markdown", "body": BODY}},
        key="cross-http",
    ).ok()
    by_mcp = mcp.call(
        Capability.REPORTS_PUBLISH,
        {"title": TITLE, "content": {"format": "json", "data": {"synthetic": [1, 2]}}},
        key="",
    ).ok()
    for rid in (by_http["report_id"], by_mcp["report_id"]):
        request = {"report_id": rid, "include_manifest": True}
        assert (
            http.call(Capability.REPORTS_READ, request, key="").ok()
            == mcp.call(Capability.REPORTS_READ, request, key="").ok()
        )
        history = {"report_id": rid, "entries": "versions", "include_manifests": True}
        assert (
            http.call(Capability.REPORTS_HISTORY, history, key="").ok()
            == mcp.call(Capability.REPORTS_HISTORY, history, key="").ok()
        )


def _foreign_report(service: ApplicationService) -> str:
    """A standalone report another Principal owns, written through the canonical handler."""
    principal: Principal = operator()
    capability = Capability.REPORTS_PUBLISH
    (purpose,) = permitted_purposes(capability)
    metadata, command = normalize(
        capability.value,
        {
            "request_id": "req-foreign",
            "purpose": purpose.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-07T12:00:00Z",
            "payload": {
                "title": "Synthetic foreign report",
                "content": {"format": "text", "body": "Synthetic foreign text."},
                "idempotency_key": "foreign-1",
            },
        },
    )
    envelope = service.invoke(metadata, command, principal=principal)
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return str(envelope.result["report_id"])


def test_unknown_foreign_and_invalid_are_the_same_refusal_on_both_paths(
    http: HttpPath, mcp: McpPath, facade: Harness, service: ApplicationService
) -> None:
    foreign = _foreign_report(service)
    mine = http.call(
        Capability.REPORTS_PUBLISH,
        {"title": TITLE, "content": {"format": "markdown", "body": BODY}},
        key="refusals",
    ).ok()["report_id"]
    before = counts(facade.engine, REPORT_TABLES)
    cases: list[tuple[str, Capability, dict[str, Any]]] = [
        ("unknown_read", Capability.REPORTS_READ, {"report_id": UNKNOWN_REPORT}),
        ("foreign_read", Capability.REPORTS_READ, {"report_id": foreign}),
        (
            "foreign_history",
            Capability.REPORTS_HISTORY,
            {"report_id": foreign, "include_withdrawn": True},
        ),
        (
            "unknown_archive",
            Capability.REPORTS_ARCHIVE,
            {"report_id": UNKNOWN_REPORT, "expected_lifecycle_revision": 0},
        ),
        (
            "foreign_update",
            Capability.REPORTS_UPDATE,
            {
                "report_id": foreign,
                "expected_version": 1,
                "patch": {"title": "Synthetic takeover"},
                "change_reason": REASON,
            },
        ),
        (
            "unknown_field_publish",
            Capability.REPORTS_PUBLISH,
            {"title": TITLE, "content": {"format": "markdown", "body": BODY}, "bogus": 1},
        ),
        (
            "server_owned_field_read",
            Capability.REPORTS_READ,
            {"report_id": mine, "owner_principal_id": "prn_" + "0" * 32},
        ),
        (
            "unknown_patch_field",
            Capability.REPORTS_UPDATE,
            {
                "report_id": mine,
                "expected_version": 1,
                "patch": {"retention": "forever"},
                "change_reason": REASON,
            },
        ),
    ]
    answers = {
        name: (
            http.call(capability, payload, key=f"refusal-{name}").refusal(),
            mcp.call(capability, payload, key="").refusal(),
        )
        for name, capability, payload in cases
    }
    for name, (ours, theirs) in answers.items():
        assert ours == theirs, (name, ours, theirs)
    # No existence oracle: unknown and foreign are one indistinguishable answer.
    assert answers["unknown_read"][0] == answers["foreign_read"][0]
    assert answers["unknown_read"][0][0] == "not_found"
    assert answers["foreign_history"][0][0] == "not_found"
    assert answers["unknown_archive"][0][0] == "not_found"
    assert answers["foreign_update"][0][0] == "not_found"
    for name in ("unknown_field_publish", "server_owned_field_read", "unknown_patch_field"):
        assert answers[name][0][0] == "invalid_request", name
    assert counts(facade.engine, REPORT_TABLES) == before


def test_unauthenticated_and_ungranted_callers_are_refused_before_any_write(
    service: ApplicationService, contract: dict[str, Any], facade: Harness
) -> None:
    before = counts(facade.engine, REPORT_TABLES)
    publish = {
        "title": TITLE,
        "content": {"format": "markdown", "body": BODY},
        "idempotency_key": "unauthenticated-1",
    }

    def no_credential(credential: str | None, document: Mapping[str, Any]) -> Principal:
        """The per-request mode's contract: a bearer or nothing (this BFF holds none)."""
        del document
        if credential is None:
            raise TokenClaimsError("a bearer token is required; access is denied")
        raise AssertionError("this test never sends a credential")

    with serve(create_http_app(service, authenticate=no_credential)) as wire:
        replies = [
            wire.send(capability, bff_document(contract, capability, payload))
            for capability, payload in (
                ("reports.publish", publish),
                ("reports.read", {"report_id": UNKNOWN_REPORT}),
            )
        ]
    for reply in replies:
        assert reply.status == 401, reply.status
        assert reply.headers["www-authenticate"] == "Bearer"
        assert reply.document()["code"] == "denied"

    # The facade: an unknown bearer is refused by the transport; an ungranted client
    # (a report_read grant only) is refused by the remote boundary.
    unknown = McpPath(facade, "tok-not-registered")
    refused = unknown.exchange(
        Capability.REPORTS_PUBLISH, {k: publish[k] for k in ("title", "content")}
    )
    assert refused.status == 401
    reader = McpPath(
        facade, facade.client("synthetic-parity-reader", [grant_row(Capability.REPORTS_READ)])
    )
    write = reader.call(
        Capability.REPORTS_PUBLISH, {k: publish[k] for k in ("title", "content")}, key=""
    )
    assert write.refusal()[0] == "unsupported"
    assert counts(facade.engine, REPORT_TABLES) == before


def test_operator_only_report_capabilities_are_not_addressable_from_the_bff_contract(
    contract: dict[str, Any],
) -> None:
    capabilities = contract["capabilities"]
    for operator_only in (
        Capability.REPORTS_HOLD_PLACE,
        Capability.REPORTS_HOLD_RELEASE,
        Capability.REPORTS_RETENTION_SET,
        Capability.REPORTS_RETENTION_GET,
    ):
        assert operator_only.value not in capabilities
        with pytest.raises(KeyError):
            bff_document(contract, operator_only.value, {"report_id": UNKNOWN_REPORT})
    # No purge capability exists at all, and none may enter the BFF contract.
    assert not any(
        name.startswith(("reports.hold", "reports.retention", "reports.purge"))
        for name in capabilities
    )


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_a_report_above_the_inline_request_limit_moves_by_transfer_over_the_gateway(
    http: HttpPath, facade: Harness
) -> None:
    staged = markdown_text(600_000, seed=19)
    inline = {
        "title": TITLE,
        "content": {"format": "markdown", "body": staged.decode()},
        "idempotency_key": "bff-large-inline",
    }
    # The BFF's rule: this inline request is over 512 KiB, so it goes by transfer.
    assert len(json.dumps(bff_document(http.contract, "reports.publish", inline)).encode()) > (
        INLINE_REQUEST_LIMIT
    )
    begun = http.call(
        Capability.REPORTS_TRANSFER_BEGIN,
        {
            "format": "markdown",
            "encoding": "identity",
            "byte_count": len(staged),
            "sha256": _sha(staged),
        },
        key="large-begin",
    ).ok()
    session_id = str(begun["session_id"])
    limit = int(begun["chunk_byte_limit"])
    chunks = [staged[start : start + limit] for start in range(0, len(staged), limit)]
    assert len(chunks) >= 2
    for sequence, chunk in enumerate(chunks):
        http.call(
            Capability.REPORTS_TRANSFER_APPEND,
            {
                "session_id": session_id,
                "sequence": sequence,
                "chunk": base64.b64encode(chunk).decode("ascii"),
                "chunk_sha256": _sha(chunk),
            },
            key="",
        ).ok()
    finalized = http.call(
        Capability.REPORTS_TRANSFER_FINALIZE, {"session_id": session_id}, key=""
    ).ok()
    token = str(finalized["content_token"])
    published = http.call(
        Capability.REPORTS_PUBLISH,
        {
            "title": TITLE,
            "content": {"transfer": {"session_id": session_id, "content_token": token}},
        },
        key="large-publish",
    ).ok()
    assert published["content"]["decoded_sha256"] == _sha(staged)
    assert published["content"]["decoded_byte_count"] == len(staged)
    rid = str(published["report_id"])

    read = http.call(Capability.REPORTS_READ, {"report_id": rid}, key="").ok()
    assert read["content"]["body_omitted"] == "exceeds_response_bound"
    assert read["content"]["body_chunked_read"]["sha256"] == _sha(staged)
    collected = bytearray()
    offset: int | None = 0
    while offset is not None:
        got = http.call(
            Capability.REPORTS_TRANSFER_READ_CHUNK,
            {"report_id": rid, "version_number": 1, "part": "decoded", "offset": offset},
            key="",
        ).ok()
        chunk = base64.b64decode(got["chunk"], validate=True)
        assert got["chunk_sha256"] == _sha(chunk)
        collected += chunk
        offset = got["next_offset"]
    assert bytes(collected) == staged
    # Every request the BFF transport carried fitted the gateway's request ceiling.
    assert max(http.requests) < MAX_REQUEST_BYTES
    assert counts(facade.engine, ("report_roots",)) == {"report_roots": 1}
