"""Reports Modernization WP02: `reports.publish` and standalone `reports.read` on PostgreSQL.

The `database` tier, on a disposable clone of the current head
(`migrated_engine`). Every request goes through the canonical local MCP server
(`create_mcp_server`, over the SDK's own client), so this is the tool catalog,
`normalize`, `ApplicationService.invoke`, one unit of work and
`SqlGeneralReportRepository` end to end. What it proves:

* a title and a content object alone publish version 1, with its receipt, and
  read back exactly -- body, digests and manifest -- from the database;
* a retry replays the original receipt and writes nothing; a changed retry is
  a conflict and writes nothing; a distinct `client_intent_id` is a new report;
* a 512 KiB markdown body is accepted over MCP under the request ceiling;
* a foreign Principal's report reads exactly as a nonexistent one;
* an association to the caller's own report is `verified`, one to another
  Principal's is `not_found` and writes nothing;
* no `knowledge.intelligence_*` row is ever written.

Every title, body and identifier is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES
from my_pa.domain.reports.manifest import manifest_digest
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.conftest import DEFAULT_LIMITS, operator
from tests.contract.test_transport_parity import document
from tests.transports import McpTransport, mcp_transport

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 4, 12, tzinfo=UTC)
BODY: Final = "# Assessment\n\nReport text"
MINIMAL: Final[dict[str, Any]] = {
    "title": "Project Schedule Risk Assessment",
    "content": {"format": "markdown", "body": BODY},
    "idempotency_key": "db-publish-minimal",
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


def _service(engine: Engine) -> ApplicationService:
    audit = SqlAlchemyAuditSink(engine)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )


def _counts(engine: Engine, tables: tuple[str, ...]) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: int(
                connection.execute(text(f"SELECT count(*) FROM knowledge.{table}")).scalar_one()  # noqa: S608
            )
            for table in tables
        }


def _send(
    mcp: McpTransport, principal: Principal, capability: Capability, payload: Mapping[str, Any]
) -> dict[str, Any]:
    answer = mcp.send(capability.value, document(capability, principal.principal_id, payload))
    return dict(answer.document)


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer.get("error") is None, answer.get("error")
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def test_publish_reads_back_exactly_and_replays_without_writing(migrated_engine: Engine) -> None:
    principal = operator()
    service = _service(migrated_engine)
    with mcp_transport(service, principal) as mcp:
        published = _ok(_send(mcp, principal, Capability.REPORTS_PUBLISH, MINIMAL))
        assert published["version_number"] == 1
        assert published["lifecycle_state"] == "active"
        assert published["lifecycle_revision"] == 0
        assert published["replayed"] is False
        assert published["content"]["decoded_sha256"] == hashlib.sha256(BODY.encode()).hexdigest()
        assert published["content"]["decoded_byte_count"] == len(BODY.encode())
        after_publish = _counts(migrated_engine, PLANE_TABLES)
        assert after_publish == {
            "report_content_objects": 1,
            "report_roots": 1,
            "report_versions": 1,
            "report_version_manifests": 1,
            "report_associations": 0,
            "report_receipts": 1,
        }

        read = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_READ,
                {"report_id": published["report_id"], "include_manifest": True},
            )
        )
        assert read["plane"] == "standalone"
        assert read["version_id"] == published["version_id"]
        assert read["title"] == MINIMAL["title"]
        assert read["content"]["body"] == BODY
        assert read["content"]["encoding"] == "identity"
        assert read["content"]["decoded_sha256"] == published["content"]["decoded_sha256"]
        assert read["manifest_sha256"] == published["manifest_sha256"]
        assert manifest_digest(read["manifest"]) == published["manifest_sha256"]
        assert read["manifest"]["version_number"] == 1
        assert "principal_id" not in read["manifest"]

        replay = _ok(_send(mcp, principal, Capability.REPORTS_PUBLISH, MINIMAL))
        assert replay["replayed"] is True
        assert replay["receipt_id"] == published["receipt_id"]
        assert replay["report_id"] == published["report_id"]
        conflict = _send(
            mcp, principal, Capability.REPORTS_PUBLISH, {**MINIMAL, "title": "Changed"}
        )
        assert conflict["error"]["code"] == "conflict"
        assert conflict["error"]["safe_details"] == ["idempotency_key"]
        assert _counts(migrated_engine, PLANE_TABLES) == after_publish

        second = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_PUBLISH,
                {**MINIMAL, "idempotency_key": "db-publish-2", "client_intent_id": "again-1"},
            )
        )
        assert second["report_id"] != published["report_id"]
        assert _counts(migrated_engine, ("report_roots",)) == {"report_roots": 2}
    assert set(_counts(migrated_engine, INTELLIGENCE_TABLES).values()) == {0}


def test_a_512_kib_markdown_report_publishes_over_mcp(migrated_engine: Engine) -> None:
    principal = operator()
    body = "# Large\n" + "x" * (INLINE_CONTENT_MAX_BYTES - len("# Large\n"))
    with mcp_transport(_service(migrated_engine), principal) as mcp:
        published = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_PUBLISH,
                {**MINIMAL, "content": {"format": "markdown", "body": body}},
            )
        )
        assert published["content"]["decoded_byte_count"] == INLINE_CONTENT_MAX_BYTES
        read = _ok(
            _send(mcp, principal, Capability.REPORTS_READ, {"report_id": published["report_id"]})
        )
        assert read["content"]["body"] == body


def test_foreign_reads_and_foreign_associations_are_not_found(migrated_engine: Engine) -> None:
    owner, stranger = operator(), operator()
    service = _service(migrated_engine)
    with mcp_transport(service, owner) as mcp:
        mine = _ok(_send(mcp, owner, Capability.REPORTS_PUBLISH, MINIMAL))
        linked = _ok(
            _send(
                mcp,
                owner,
                Capability.REPORTS_PUBLISH,
                {
                    **MINIMAL,
                    "idempotency_key": "db-linked",
                    "associations": [
                        {
                            "target_kind": "standalone_report",
                            "target_ref": mine["report_id"],
                            "relation": "follows",
                        },
                        {
                            "target_kind": "external_source",
                            "target_ref": "https://example.invalid/a",
                            "relation": "cites",
                        },
                    ],
                },
            )
        )
        read = _ok(_send(mcp, owner, Capability.REPORTS_READ, {"report_id": linked["report_id"]}))
        assert [item["verification"] for item in read["associations"]] == [
            "verified",
            "asserted",
        ]
        missing = _send(mcp, owner, Capability.REPORTS_READ, {"report_id": "grpt_00000000nothere0"})
    with mcp_transport(service, stranger) as mcp:
        foreign = _send(mcp, stranger, Capability.REPORTS_READ, {"report_id": mine["report_id"]})
        before = _counts(migrated_engine, PLANE_TABLES)
        refused = _send(
            mcp,
            stranger,
            Capability.REPORTS_PUBLISH,
            {
                **MINIMAL,
                "idempotency_key": "db-foreign-link",
                "associations": [
                    {
                        "target_kind": "standalone_report",
                        "target_ref": mine["report_id"],
                        "relation": "follows",
                    }
                ],
            },
        )
        assert _counts(migrated_engine, PLANE_TABLES) == before
    for answer in (foreign, missing):
        assert answer["error"]["code"] == "not_found"
        assert answer["error"]["safe_details"] == ["artifact_id"]
    assert refused["error"]["code"] == "not_found"
    assert refused["error"]["safe_details"] == ["associations"]
    assert mine["report_id"] not in str(refused)
