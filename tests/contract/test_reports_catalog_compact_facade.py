"""Reports Modernization WP04: `reports.list` / `reports.search` planes through the compact facade.

The harness is `tests/contract/test_reports_compact_facade.py`'s: every request
is an HTTP POST to the real remote MCP app, authenticated by the real
`RemoteAuthenticator` against the durable grant store on a migrated,
disposable PostgreSQL database, resolved by the composition root's
`remote_access_context` and served by a real `ApplicationService`. The synthetic
client holds exactly the planner's `chatllm-data` grants.

What it proves (contract C1-C6, C8, C9, C10; RM-AC-005 in part):

* `my_pa.describe` returns the exact extended schema of `reports.list` and
  `reports.search`: the canonical tool schema through `remote_tool_schema`;
* standalone reports published, updated, archived and deleted through
  `my_pa.write`, and a pipeline artifact committed on the canonical local path,
  list and search through `my_pa.read` in every plane: `plane` omitted and
  `"intelligence"` answer byte for byte alike, in the legacy shape (no `plane`
  key) and exactly as the canonical local handler answers; `standalone` and
  `all` carry the plane discriminator, the one order, every filter, the
  lifecycle default (`active` only) and a two-page cursor walk that neither
  skips nor repeats; returned ids read back from `knowledge.report_*` and
  `knowledge.intelligence_artifacts`, and no standalone publish writes an
  `intelligence_*` row;
* another Principal's reports never appear in any plane, and its cursor is
  refused; a garbage, tampered or re-purposed cursor, an invalid plane, an
  empty or oversize query, an inexact or missing grant, a revoked client and
  the wrong wrapper are refused, each with no row written;
* search reads decoded text only: a word present only Base64-encoded in a body
  is not found, the plain word is, and JSON keys are not searchable.

Every identity, title and body here is synthetic.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.conftest import DEFAULT_LIMITS, metadata_for, operator
from tests.contract.test_reports_compact_facade import (
    ARCHIVE,
    CLIENT,
    DELETE,
    INTELLIGENCE_TABLES,
    MUTATION_TABLES,
    PUBLISH,
    UPDATE,
    Exchange,
    Harness,
    build_service,
    counts,
    describe,
    grant_row,
    move_payload,
    ok,
    outcome,
    profile_grants,
    refusal,
    remote_principal,
    update_payload,
    wrapped,
)

from my_pa.adapters.mcp.chatllm_gateway import READ_TOOL, WRITE_TOOL
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import remote_tool_schema
from my_pa.application.commands import BeginIntelligenceCycle, CommitIntelligenceArtifact
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.intelligence.catalog import (
    CYCLE_MORNING_INTELLIGENCE,
    ArtifactKind,
    ArtifactState,
    FocusAreaId,
    IntelligenceStage,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

LIST: Final = Capability.REPORTS_LIST
SEARCH: Final = Capability.REPORTS_SEARCH
CATALOG: Final = (LIST, SEARCH)
_TOOLS: Final = {tool.name: tool for tool in TOOLS}
_ALL_TABLES: Final = MUTATION_TABLES + INTELLIGENCE_TABLES

#: Distinct creation instants, oldest first (each report's root `created_at`).
T_OLD: Final = datetime(2026, 8, 1, 9, tzinfo=UTC)
T_ARCHIVED: Final = datetime(2026, 8, 15, 9, tzinfo=UTC)
T_MID: Final = datetime(2026, 9, 1, 9, tzinfo=UTC)
T_LEGACY: Final = datetime(2026, 9, 15, 9, tzinfo=UTC)
T_TRASHED: Final = datetime(2026, 9, 20, 9, tzinfo=UTC)
T_NEW: Final = datetime(2026, 10, 1, 9, tzinfo=UTC)
T_UPDATE: Final = datetime(2026, 10, 2, 9, tzinfo=UTC)

STANDALONE_KEYS: Final = frozenset(
    {
        "plane",
        "report_id",
        "title",
        "type",
        "topics",
        "tags",
        "summary",
        "report_date",
        "lifecycle_state",
        "lifecycle_revision",
        "head_version_id",
        "head_version_number",
        "created_at",
        "updated_at",
    }
)
INTELLIGENCE_KEYS: Final = frozenset(
    {
        "plane",
        "report_id",
        "title",
        "type",
        "report_date",
        "created_at",
        "cycle_run_id",
        "stage",
        "artifact_kind",
        "focus_area_id",
        "source_lane",
        "content_sha256",
        "artifact_state",
    }
)
EXTERNAL: Final = {"target_kind": "external_source", "target_ref": "https://example.test/curlew"}


def service_at(engine: Engine, when: datetime) -> ApplicationService:
    """The facade's service with its clock at `when` (each root's `created_at`)."""
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: when,
    )


def publish_at(
    harness: Harness, token: str, when: datetime, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """`reports.publish` through `my_pa.write`, served at `when`."""
    harness.service = service_at(harness.engine, when)
    (answer,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, payload))])
    return ok(answer)


def write_at(
    harness: Harness, token: str, when: datetime, capability: Capability, payload: Mapping[str, Any]
) -> dict[str, Any]:
    harness.service = service_at(harness.engine, when)
    (answer,) = harness.run([(token, wrapped(WRITE_TOOL, capability, payload))])
    return ok(answer)


def body(text_: str) -> dict[str, Any]:
    return {"format": "markdown", "body": text_}


def commit_legacy(
    service: ApplicationService, principal: Principal, *, key: str, title: str
) -> str:
    """One current pipeline artifact on the canonical local path; its `rpt_` id."""
    begun = service.invoke(
        metadata_for(BeginIntelligenceCycle.capability, Purpose.REPORT_AUTHORING, principal),
        BeginIntelligenceCycle(
            cycle_id=CYCLE_MORNING_INTELLIGENCE,
            business_date="2026-08-20",
            idempotency_key=f"{key}-cycle",
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
            producer_task_id=f"task-{key}",
            producer_task_name="Synthetic collector",
            automation_platform="abacus_chatllm",
            report_date="2026-08-20",
            title=title,
            body_markdown="# Collector\n\nSynthetic curlew pipeline body.",
            artifact_state=ArtifactState.FINAL,
            schema_version="1",
            idempotency_key=key,
            focus_area_id=FocusAreaId.COMMUNICATIONS,
        ),
        principal=principal,
    )
    assert committed.result is not None, committed.error
    return str(committed.result["report_id"])


def local_publish(service: ApplicationService, principal: Principal, key: str, title: str) -> str:
    """A standalone report of `principal` on the canonical local path."""
    _metadata, command = normalize(
        PUBLISH.value,
        {
            "request_id": f"req-{key}",
            "purpose": Purpose.REPORT_AUTHORING.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": {
                "title": title,
                "content": body("Synthetic curlew survey text."),
                "topics": ["birds"],
                "idempotency_key": key,
            },
        },
    )
    published = service.invoke(
        metadata_for(PUBLISH, Purpose.REPORT_AUTHORING, principal), command, principal=principal
    )
    assert published.result is not None, published.error
    return str(published.result["report_id"])


def local_catalog(
    service: ApplicationService,
    principal: Principal,
    capability: Capability,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """The canonical local handler's whole answer (result, error, disclosure)."""
    metadata, command = normalize(
        capability.value,
        {
            "request_id": "req-catalog-local",
            "purpose": Purpose.REPORT_READ.value,
            "principal_id": principal.principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": dict(payload),
        },
    )
    answer = service.invoke(metadata, command, principal=principal)
    dumped = answer.model_dump(mode="json")
    assert isinstance(dumped, dict)
    return dumped


def read(harness: Harness, token: str, capability: Capability, payload: Mapping[str, Any]) -> Any:  # noqa: ANN401
    (answer,) = harness.run([(token, wrapped(READ_TOOL, capability, payload))])
    return answer


def keys_of(value: object) -> set[str]:
    """Every object key anywhere in a JSON value."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys_of(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys_of(item)}
    return set()


def ids(result: Mapping[str, Any]) -> list[str]:
    return [item["report_id"] for item in result["items"]]


#: The per-request ids the facade mints (`correlation_id` and `request_id`).
_CORRELATION: Final = re.compile(r'"corr_[0-9a-f]{32}"')


def raw_text(answer: Exchange) -> str:
    """The facade's exact answer text (the bytes a client parses).

    Only the per-request minted ids are masked; every other byte is kept.
    """
    assert answer.status == 200, answer.document
    (content,) = answer.document["result"]["content"]
    rendered = str(content["text"])
    masked, replaced = _CORRELATION.subn('"<corr>"', rendered)
    assert replaced == 2, rendered
    return masked


@pytest.fixture
def harness(migrated_engine: Engine) -> Harness:
    built = Harness(migrated_engine, build_service(migrated_engine))
    built.gates()
    return built


# ---- the seeded world --------------------------------------------------------------------


class World:
    """Five standalone reports of the remote Principal, one pipeline artifact, a stranger's."""

    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.token = harness.client(CLIENT, profile_grants(harness.service))
        principal = remote_principal()
        intelligence_before = counts(harness.engine, INTELLIGENCE_TABLES)
        self.old = publish_at(
            harness,
            self.token,
            T_OLD,
            {
                "title": "Curlew coastal survey",
                "content": body("# Survey\n\nCurlew counts along the estuary."),
                "type": "survey",
                "topics": ["birds", "coast"],
                "tags": ["field"],
                "summary": "Curlew counts on the coast.",
                "report_date": "2026-07-31",
                "associations": [{**EXTERNAL, "relation": "cites"}],
            },
        )["report_id"]
        self.mid = publish_at(
            harness,
            self.token,
            T_MID,
            {
                "title": "Curlew inland survey",
                "content": body("# Survey\n\nCurlew counts on the moor."),
                "type": "survey",
                "topics": ["birds"],
                "report_date": "2026-08-31",
            },
        )["report_id"]
        self.archived = publish_at(
            harness,
            self.token,
            T_ARCHIVED,
            {"title": "Curlew archived note", "content": body("Curlew archived text.")},
        )["report_id"]
        self.trashed = publish_at(
            harness,
            self.token,
            T_TRASHED,
            {"title": "Curlew trashed note", "content": body("Curlew trashed text.")},
        )["report_id"]
        self.new = publish_at(
            harness,
            self.token,
            T_NEW,
            {"title": "Curlew draft", "content": body("Curlew newest text.")},
        )["report_id"]
        # No standalone publish wrote any pipeline row.
        assert counts(harness.engine, INTELLIGENCE_TABLES) == intelligence_before
        # Managed through the facade: an update moves the head, archive and delete withdraw.
        updated = write_at(
            harness,
            self.token,
            T_UPDATE,
            UPDATE,
            update_payload(self.new, 1, {"title": "Curlew revised draft", "tags": ["desk"]}),
        )
        assert updated["version_number"] == 2
        self.new_head = updated["version_id"]
        write_at(harness, self.token, T_UPDATE, ARCHIVE, move_payload(self.archived, 0))
        write_at(harness, self.token, T_UPDATE, DELETE, move_payload(self.trashed, 0))
        legacy_service = service_at(harness.engine, T_LEGACY)
        self.legacy = commit_legacy(
            legacy_service, principal, key="catalog-legacy", title="Curlew pipeline brief"
        )
        stranger = operator()
        assert stranger.principal_id != principal.principal_id
        self.stranger = stranger
        self.foreign = local_publish(
            service_at(harness.engine, T_NEW), stranger, "stranger-1", "Curlew stranger survey"
        )
        self.foreign_legacy = commit_legacy(
            legacy_service, stranger, key="stranger-legacy", title="Curlew stranger brief"
        )
        harness.service = build_service(harness.engine)

    def read(self, capability: Capability, payload: Mapping[str, Any]) -> Exchange:
        answer: Exchange = read(self.harness, self.token, capability, payload)
        return answer


@pytest.fixture
def world(harness: Harness) -> World:
    return World(harness)


# ---- describe ----------------------------------------------------------------------------


def test_describe_returns_the_exact_extended_list_and_search_schemas(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    listed, *exact = harness.run(
        [(token, describe(feature="reports", kind="read", limit=100))]
        + [(token, describe(capability=capability.value)) for capability in CATALOG]
    )
    _failed, catalog = outcome(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    for capability, answer in zip(CATALOG, exact, strict=True):
        assert (items[capability.value]["kind"], items[capability.value]["feature"]) == (
            "read",
            "reports",
        )
        _failed, contract = outcome(answer)
        expected = json.loads(json.dumps(remote_tool_schema(_TOOLS[capability.value].input_schema)))
        # Full equality with the canonical schema, the WP04 overlay included.
        assert contract["input_schema"] == expected, capability
        assert contract["profile"] == "chatllm-gateway-v1"
        payload = contract["input_schema"]["properties"]["payload"]
        assert payload["additionalProperties"] is False
        properties = payload["properties"]
        assert properties["plane"]["enum"] == ["intelligence", "standalone", "all"]
        assert properties["lifecycle_states"]["items"]["enum"] == ["active", "archived", "trashed"]
        assert properties["associated_with"]["properties"]["target_kind"]["enum"] == [
            "project",
            "entity",
            "standalone_report",
            "intelligence_report",
            "external_source",
        ]
        assert properties["associated_with"]["additionalProperties"] is False
        catalog_fields = {
            "plane",
            "cursor",
            "page_size",
            "type",
            "topics",
            "tags",
            "associated_with",
            "lifecycle_states",
            "created_from",
            "created_to",
            "report_date_from",
            "report_date_to",
        }
        assert catalog_fields <= set(properties), capability
        for name in catalog_fields - {"plane", "cursor", "page_size"}:
            assert properties[name]["description"].startswith("standalone/all only"), name
        assert "idempotency_key" not in json.dumps(payload)
        assert "principal_id" not in properties
    list_payload = outcome(exact[0])[1]["input_schema"]["properties"]["payload"]
    search_payload = outcome(exact[1])[1]["input_schema"]["properties"]["payload"]
    assert {"include_superseded", "report_date"} <= set(list_payload["properties"])
    assert search_payload["required"] == ["query"]


# ---- list ------------------------------------------------------------------------------------


def test_list_in_every_plane_with_order_filters_lifecycle_and_readback(world: World) -> None:
    before = counts(world.harness.engine, _ALL_TABLES)
    answers = {
        name: world.read(LIST, payload)
        for name, payload in {
            "omitted": {},
            "intelligence": {"plane": "intelligence"},
            "standalone": {"plane": "standalone"},
            "all": {"plane": "all"},
        }.items()
    }
    # Default and explicit pipeline plane: the same bytes, the legacy shape.
    assert raw_text(answers["omitted"]) == raw_text(answers["intelligence"])
    legacy = ok(answers["omitted"])
    assert "plane" not in legacy
    assert ids(legacy) == [world.legacy]
    assert all("plane" not in item for item in legacy["items"])
    local = local_catalog(world.harness.service, remote_principal(), LIST, {})
    assert local["error"] is None
    assert legacy == local["result"]

    standalone = ok(answers["standalone"])
    assert set(standalone) == {"plane", "items", "next_cursor"}
    assert standalone["plane"] == "standalone"
    assert standalone["next_cursor"] is None
    # Active only by default, newest root first; the stranger's never.
    assert ids(standalone) == [world.new, world.mid, world.old]
    for item in standalone["items"]:
        assert set(item) == STANDALONE_KEYS
        assert item["plane"] == "standalone"
        assert item["lifecycle_state"] == "active"
    newest = standalone["items"][0]
    assert (newest["title"], newest["tags"], newest["head_version_number"]) == (
        "Curlew revised draft",
        ["desk"],
        2,
    )
    assert newest["head_version_id"] == world.new_head
    assert (newest["created_at"], newest["updated_at"]) == (
        "2026-10-01T09:00:00.000Z",
        "2026-10-02T09:00:00.000Z",
    )
    oldest = standalone["items"][-1]
    assert (oldest["type"], oldest["topics"], oldest["tags"]) == (
        "survey",
        ["birds", "coast"],
        ["field"],
    )
    assert (oldest["summary"], oldest["report_date"]) == (
        "Curlew counts on the coast.",
        "2026-07-31",
    )

    merged = ok(answers["all"])
    assert merged["plane"] == "all"
    assert ids(merged) == [world.new, world.legacy, world.mid, world.old]
    for item in merged["items"]:
        assert set(item) == (
            STANDALONE_KEYS if item["plane"] == "standalone" else INTELLIGENCE_KEYS
        )
    pipeline = merged["items"][1]
    assert pipeline["plane"] == "intelligence"
    assert pipeline["type"] == pipeline["artifact_kind"] == "collector_candidates"
    assert pipeline["created_at"] == "2026-09-15T09:00:00.000Z"
    rendered = json.dumps([merged, standalone])
    for leaked in (world.foreign, world.foreign_legacy, "Curlew counts along"):
        assert leaked not in rendered
    assert not {key for key in keys_of([merged, standalone]) if "count" in key or "total" in key}

    # Database readback: every listed id is the caller's own row.
    owner = remote_principal().principal_id
    with world.harness.engine.connect() as connection:
        roots: dict[str, str] = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "SELECT report_id, lifecycle_state FROM knowledge.report_roots "
                    "WHERE owner_principal_id = :o"
                ),
                {"o": owner},
            )
        }
        artifact = connection.execute(
            text(
                "SELECT principal_id, is_current FROM knowledge.intelligence_artifacts "
                "WHERE artifact_id = :a"
            ),
            {"a": world.legacy},
        ).one()
        foreign_owner = connection.execute(
            text("SELECT owner_principal_id FROM knowledge.report_roots WHERE report_id = :r"),
            {"r": world.foreign},
        ).scalar_one()
    assert roots == {
        world.old: "active",
        world.mid: "active",
        world.new: "active",
        world.archived: "archived",
        world.trashed: "trashed",
    }
    assert tuple(artifact) == (owner, True)
    assert foreign_owner == world.stranger.principal_id
    # Reads write nothing.
    assert counts(world.harness.engine, _ALL_TABLES) == before


def test_list_filters_and_lifecycle_states_through_the_facade(world: World) -> None:
    before = counts(world.harness.engine, _ALL_TABLES)

    def listed(plane: str, **filters: Any) -> list[str]:  # noqa: ANN401
        return ids(ok(world.read(LIST, {"plane": plane, **filters})))

    for plane in ("standalone", "all"):
        assert listed(plane, type="survey") == [world.mid, world.old]
        assert listed(plane, topics=["coast", "birds"]) == [world.old]
        assert listed(plane, topics=["birds"]) == [world.mid, world.old]
        assert listed(plane, tags=["desk"]) == [world.new]
        assert listed(plane, associated_with=EXTERNAL) == [world.old]
        assert listed(plane, report_date_from="2026-07-31", report_date_to="2026-07-31") == [
            world.old
        ]
        assert listed(plane, lifecycle_states=["archived"]) == [world.archived]
        assert listed(plane, lifecycle_states=["trashed"]) == [world.trashed]
        assert listed(plane, lifecycle_states=["trashed", "archived"]) == [
            world.trashed,
            world.archived,
        ]
    # Created ranges are half-open; the pipeline artifact is in range in `all` only.
    window = {"created_from": "2026-08-01T09:00:00Z", "created_to": "2026-10-01T09:00:00Z"}
    assert listed("standalone", **window) == [world.mid, world.old]
    assert listed("all", **window) == [world.legacy, world.mid, world.old]
    assert listed("all", created_from="2026-10-01T11:00:00+02:00") == [world.new]
    assert listed(
        "all",
        lifecycle_states=["active", "archived", "trashed"],
    ) == [world.new, world.trashed, world.legacy, world.mid, world.archived, world.old]
    # Report dates: a standalone head's, or the pipeline artifact's (2026-08-20).
    assert listed("standalone", report_date_from="2026-08-01") == [world.mid]
    assert listed("all", report_date_from="2026-08-01") == [world.legacy, world.mid]
    assert listed("all", report_date_to="2026-08-19") == [world.old]
    # The pipeline artifact is `active`, and never matches a standalone-only filter.
    assert listed("all", lifecycle_states=["archived"]) == [world.archived]
    assert listed("all", type="collector_candidates") == [world.legacy]
    assert listed("all", report_date_from="2026-08-20", report_date_to="2026-08-20") == [
        world.legacy
    ]
    assert counts(world.harness.engine, _ALL_TABLES) == before


def test_a_two_page_cursor_walk_neither_skips_nor_repeats(world: World) -> None:
    for capability, base in (
        (LIST, {"plane": "all", "page_size": 2}),
        (SEARCH, {"plane": "all", "page_size": 2, "query": "curlew"}),
    ):
        first = ok(world.read(capability, base))
        assert len(first["items"]) == 2
        assert isinstance(first["next_cursor"], str)
        second = ok(world.read(capability, {**base, "cursor": first["next_cursor"]}))
        assert len(second["items"]) == 2
        assert second["next_cursor"] is None
        walked = ids(first) + ids(second)
        assert len(set(walked)) == 4
        whole = ok(world.read(capability, {**base, "page_size": 100}))
        assert walked == ids(whole), capability
        assert set(walked) == {world.new, world.legacy, world.mid, world.old}
        assert world.foreign not in walked and world.foreign_legacy not in walked


# ---- search ------------------------------------------------------------------------------


def test_search_in_every_plane_with_filters_and_snippets(world: World) -> None:
    before = counts(world.harness.engine, _ALL_TABLES)
    omitted, explicit, standalone_answer, all_answer = (
        world.read(SEARCH, {"query": "curlew", **extra})
        for extra in ({}, {"plane": "intelligence"}, {"plane": "standalone"}, {"plane": "all"})
    )
    assert raw_text(omitted) == raw_text(explicit)
    legacy = ok(omitted)
    assert "plane" not in legacy
    assert ids(legacy) == [world.legacy]
    assert all("plane" not in item for item in legacy["items"])
    local = local_catalog(world.harness.service, remote_principal(), SEARCH, {"query": "curlew"})
    assert local["error"] is None
    assert legacy == local["result"]

    standalone = ok(standalone_answer)
    assert set(standalone) == {"plane", "items", "next_cursor"}
    assert set(ids(standalone)) == {world.new, world.mid, world.old}
    for item in standalone["items"]:
        assert set(item) == STANDALONE_KEYS | {"snippet"}
        assert item["plane"] == "standalone"
    snippets = {item["report_id"]: item["snippet"] for item in standalone["items"]}
    assert "Curlew" in snippets[world.old]
    merged = ok(all_answer)
    assert set(ids(merged)) == {world.new, world.legacy, world.mid, world.old}
    pipeline = next(item for item in merged["items"] if item["plane"] == "intelligence")
    assert set(pipeline) == INTELLIGENCE_KEYS | {"snippet"}
    # Rank first, then the list order: the order is total and deterministic.
    again = ok(world.read(SEARCH, {"query": "curlew", "plane": "all"}))
    assert ids(again) == ids(merged)

    def found(plane: str, query: str, **filters: Any) -> list[str]:  # noqa: ANN401
        return ids(ok(world.read(SEARCH, {"plane": plane, "query": query, **filters})))

    assert found("standalone", "estuary") == [world.old]
    # A filter keeps the unfiltered order of what it keeps.
    assert found("all", "curlew", type="survey") == [
        report_id for report_id in ids(merged) if report_id in {world.mid, world.old}
    ]
    assert found("all", "curlew", topics=["coast"]) == [world.old]
    assert found("all", "curlew", lifecycle_states=["archived"]) == [world.archived]
    assert found("standalone", "archived") == []
    assert found("standalone", "archived", lifecycle_states=["archived"]) == [world.archived]
    assert found("all", "stranger") == []
    rendered = json.dumps([standalone, merged])
    assert world.foreign not in rendered
    # Never content bytes, never a count or total (no existence oracle).
    assert "Curlew counts along" not in rendered
    assert not {key for key in keys_of([standalone, merged]) if "count" in key or "total" in key}
    assert counts(world.harness.engine, _ALL_TABLES) == before


def test_search_reads_decoded_values_never_base64_or_json_keys(harness: Harness) -> None:
    """RM-AC-005 in part: the search projection is the decoded text's words and JSON values."""
    token = harness.client(CLIENT, profile_grants(harness.service))
    hidden = base64.b64encode(b"zanzibarquokka").decode()
    encoded = publish_at(
        harness,
        token,
        T_OLD,
        {"title": "Encoded note", "content": body(f"Opaque payload {hidden} follows.")},
    )["report_id"]
    plain = publish_at(
        harness,
        token,
        T_MID,
        {"title": "Plain note", "content": body("The zanzibarquokka was observed.")},
    )["report_id"]
    data = publish_at(
        harness,
        token,
        T_NEW,
        {
            "title": "Structured note",
            "content": {"format": "json", "data": {"marsupialkey": "wombatvalue", "n": 7}},
        },
    )["report_id"]

    def found(query: str) -> list[str]:
        return ids(ok(read(harness, token, SEARCH, {"plane": "standalone", "query": query})))

    assert found("zanzibarquokka") == [plain]
    assert encoded not in found("zanzibarquokka")
    assert found("wombatvalue") == [data]
    assert found("marsupialkey") == []
    with harness.engine.connect() as connection:
        projected: dict[str, str] = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "SELECT v.report_id, v.search_text FROM knowledge.report_versions v "
                    "WHERE v.report_id = ANY(:r)"
                ),
                {"r": [encoded, plain, data]},
            )
        }
    assert projected[data] == "wombatvalue"
    assert hidden in projected[encoded]
    assert set(counts(harness.engine, INTELLIGENCE_TABLES).values()) == {0}


# ---- refusals and isolation ----------------------------------------------------------------


def _tampered(cursor: str) -> str:
    raw = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    forged = {**raw, "b": "0" * 64}
    return (
        base64.urlsafe_b64encode(json.dumps(forged, sort_keys=True, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


def test_a_forged_foreign_or_repurposed_cursor_is_refused(world: World) -> None:
    listing: dict[str, Any] = {"plane": "standalone", "page_size": 1}
    searching: dict[str, Any] = {"plane": "standalone", "page_size": 1, "query": "curlew"}
    list_cursor = ok(world.read(LIST, listing))["next_cursor"]
    search_cursor = ok(world.read(SEARCH, searching))["next_cursor"]
    assert isinstance(list_cursor, str) and isinstance(search_cursor, str)
    # The stranger's own cursor for the very same request.
    theirs = local_catalog(
        world.harness.service,
        world.stranger,
        LIST,
        {"plane": "all", "page_size": 1},
    )
    foreign_cursor = theirs["result"]["next_cursor"]
    assert isinstance(foreign_cursor, str)
    before = counts(world.harness.engine, _ALL_TABLES)
    cases: list[tuple[Capability, dict[str, Any]]] = [
        (LIST, {**listing, "cursor": "garbage!"}),
        (LIST, {**listing, "cursor": "Zm9v"}),
        (LIST, {**listing, "cursor": _tampered(list_cursor)}),
        (LIST, {**listing, "cursor": list_cursor, "topics": ["birds"]}),
        (LIST, {**listing, "cursor": list_cursor, "plane": "all"}),
        (LIST, {**listing, "cursor": list_cursor, "page_size": 2}),
        (LIST, {**listing, "cursor": list_cursor, "lifecycle_states": ["active", "archived"]}),
        (LIST, {"plane": "all", "page_size": 1, "cursor": foreign_cursor}),
        (SEARCH, {**searching, "cursor": list_cursor}),
        (SEARCH, {**searching, "cursor": search_cursor, "query": "survey"}),
        (SEARCH, {**searching, "cursor": search_cursor, "plane": "all"}),
        (LIST, {**listing, "cursor": search_cursor}),
    ]
    for capability, payload in cases:
        answer = world.read(capability, payload)
        assert refusal(answer) == ("invalid_request", ["cursor"]), payload
        assert str(payload["cursor"]) not in json.dumps(answer.document)
    # The same request with its own cursor continues.
    assert ok(world.read(LIST, {**listing, "cursor": list_cursor}))["items"]
    assert counts(world.harness.engine, _ALL_TABLES) == before


def test_another_principals_reports_never_appear_in_any_plane(world: World) -> None:
    searches: tuple[tuple[Capability, dict[str, Any]], ...] = (
        (LIST, {}),
        (SEARCH, {"query": "stranger"}),
    )
    for capability, extra in searches:
        for plane in (None, "intelligence", "standalone", "all"):
            payload: dict[str, Any] = dict(extra) if plane is None else {**extra, "plane": plane}
            if plane in ("standalone", "all"):
                payload["lifecycle_states"] = ["active", "archived", "trashed"]
            rendered = raw_text(world.read(capability, payload))
            assert world.foreign not in rendered, (capability, plane)
            assert world.foreign_legacy not in rendered, (capability, plane)
            assert "stranger" not in rendered.lower(), (capability, plane)
    # And the stranger, reading locally, sees only its own.
    theirs = local_catalog(world.harness.service, world.stranger, LIST, {"plane": "all"})
    assert ids(theirs["result"]) == [world.foreign, world.foreign_legacy]


@pytest.mark.parametrize("capability", CATALOG, ids=lambda c: c.value)
def test_an_invalid_plane_or_query_is_refused_with_its_detail(
    harness: Harness, capability: Capability
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    query = {"query": "curlew"} if capability is SEARCH else {}
    before = counts(harness.engine, _ALL_TABLES)
    bad_plane = read(harness, token, capability, {**query, "plane": "both"})
    assert refusal(bad_plane) == ("invalid_request", ["plane"])
    _failed, document = outcome(bad_plane)
    assert document.get("error", document)["allowed_values"] == [
        {"detail": "plane", "truncated": False, "values": ["intelligence", "standalone", "all"]}
    ]
    if capability is SEARCH:
        for plane in ("standalone", "all"):
            for text_ in ("x" * 513, "", "   "):
                answer = read(harness, token, SEARCH, {"plane": plane, "query": text_})
                assert refusal(answer) == ("invalid_request", ["query"]), (plane, len(text_))
        accepted = read(harness, token, SEARCH, {"plane": "standalone", "query": "x" * 512})
        assert ok(accepted)["items"] == []
    assert counts(harness.engine, _ALL_TABLES) == before


def _catalog_refused(harness: Harness, token: str) -> None:
    """Describe hides both names (or they are inexact) and both calls are unsupported."""
    before = counts(harness.engine, _ALL_TABLES)
    answers = harness.run(
        [
            (token, wrapped(READ_TOOL, LIST, {"plane": "standalone"})),
            (token, wrapped(READ_TOOL, SEARCH, {"plane": "all", "query": "curlew"})),
            (token, wrapped(READ_TOOL, LIST, {})),
        ]
    )
    for answer in answers:
        assert refusal(answer) == ("unsupported", [])
    assert counts(harness.engine, _ALL_TABLES) == before


def test_catalog_names_omitted_from_the_profile_are_hidden_and_refused(harness: Harness) -> None:
    rows = tuple(row for row in profile_grants(harness.service) if row[0] not in CATALOG)
    token = harness.client(CLIENT, rows)
    (listed,) = harness.run([(token, describe(feature="reports", limit=100))])
    _failed, catalog = outcome(listed)
    assert not {item["capability"] for item in catalog["items"]} & {c.value for c in CATALOG}
    _catalog_refused(harness, token)


def test_a_catalog_grant_without_report_read_is_refused(harness: Harness) -> None:
    rows = (
        *(row for row in profile_grants(harness.service) if row[0] not in CATALOG),
        *(grant_row(c, purpose=Purpose.REPORT_AUTHORING) for c in CATALOG),
    )
    token = harness.client(CLIENT, rows)
    _catalog_refused(harness, token)


def test_a_revoked_client_is_refused_list_and_search(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    harness.revoke(CLIENT)
    before = counts(harness.engine, _ALL_TABLES)
    answers = harness.run(
        [(token, describe(capability=c.value)) for c in CATALOG]
        + [
            (token, wrapped(READ_TOOL, LIST, {"plane": "all"})),
            (token, wrapped(READ_TOOL, SEARCH, {"plane": "all", "query": "curlew"})),
        ]
    )
    for answer in answers:
        assert answer.status == 401
        assert answer.document == {"error": "invalid_token"}
    assert counts(harness.engine, _ALL_TABLES) == before


def test_list_and_search_through_my_pa_write_are_refused(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine, _ALL_TABLES)
    answers = harness.run(
        [
            (token, wrapped(WRITE_TOOL, LIST, {"plane": "standalone"})),
            (token, wrapped(WRITE_TOOL, SEARCH, {"plane": "all", "query": "curlew"})),
        ]
    )
    for answer in answers:
        assert refusal(answer)[0] == "invalid_request"
    assert counts(harness.engine, _ALL_TABLES) == before
