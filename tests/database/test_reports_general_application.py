"""Reports Modernization WP02/WP03: the standalone report plane end to end on PostgreSQL.

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
* WP03: a metadata update reuses the content object and a content update
  writes one; both read back, with `change_reason`, and page through
  `reports.history` with verified manifests; a replay writes nothing; a stale
  update, a stale or illegal lifecycle move writes nothing; archive, delete
  and restore round-trip (archived -> trashed -> archived) with every version
  kept, an update of a withdrawn report is refused, and a foreign Principal
  meets `not_found` on every one of them;
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


# ---- Reports Modernization WP03: update, history, archive, delete, restore ----------------

#: The plane tables a lifecycle move or an update may write, with the events table.
MUTATION_TABLES: Final = (*PLANE_TABLES, "report_lifecycle_events")


def _update(report_id: str, key: str, patch: dict[str, Any], version: int) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "expected_version": version,
        "patch": patch,
        "change_reason": "A synthetic revision.",
        "idempotency_key": key,
    }


def _move(report_id: str, key: str, revision: int) -> dict[str, Any]:
    return {"report_id": report_id, "expected_lifecycle_revision": revision, "idempotency_key": key}


def test_update_metadata_and_content_read_back_with_history(migrated_engine: Engine) -> None:
    principal = operator()
    with mcp_transport(_service(migrated_engine), principal) as mcp:
        published = _ok(_send(mcp, principal, Capability.REPORTS_PUBLISH, MINIMAL))
        rid = published["report_id"]
        metadata = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_UPDATE,
                _update(rid, "db-update-1", {"title": "Revised", "tags": ["risk"]}, 1),
            )
        )
        assert metadata["change_kind"] == "metadata"
        assert metadata["version_number"] == 2
        assert metadata["content_id"] == published["content"]["content_id"]
        assert _counts(migrated_engine, ("report_content_objects", "report_versions")) == {
            "report_content_objects": 1,
            "report_versions": 2,
        }
        body = "# Assessment\n\nRevised text"
        content = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_UPDATE,
                _update(rid, "db-update-2", {"content": {"format": "markdown", "body": body}}, 2),
            )
        )
        assert content["change_kind"] == "content"
        assert content["decoded_sha256"] == hashlib.sha256(body.encode()).hexdigest()
        read = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_READ,
                {"report_id": rid, "include_manifest": True},
            )
        )
        assert read["version_number"] == 3
        assert read["title"] == "Revised"
        assert read["tags"] == ["risk"]
        assert read["content"]["body"] == body
        assert read["change_reason"] == "A synthetic revision."
        assert manifest_digest(read["manifest"]) == content["manifest_sha256"]
        first = _ok(
            _send(mcp, principal, Capability.REPORTS_READ, {"report_id": rid, "version_number": 1})
        )
        assert first["content"]["body"] == BODY
        assert first["change_reason"] is None
        history = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_HISTORY,
                {"report_id": rid, "page_size": 2, "include_manifests": True},
            )
        )
        assert [item["version_number"] for item in history["items"]] == [1, 2]
        assert [item["change_kind"] for item in history["items"]] == ["initial", "metadata"]
        for item in history["items"]:
            assert manifest_digest(item["manifest"]) == item["manifest_sha256"]
        rest = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_HISTORY,
                {"report_id": rid, "after": history["next_cursor"]},
            )
        )
        assert [item["version_number"] for item in rest["items"]] == [3]
        assert rest["next_cursor"] is None
        # A replay writes nothing.
        before = _counts(migrated_engine, MUTATION_TABLES)
        replay = _ok(
            _send(
                mcp,
                principal,
                Capability.REPORTS_UPDATE,
                _update(rid, "db-update-1", {"title": "Revised", "tags": ["risk"]}, 1),
            )
        )
        assert replay["replayed"] is True
        assert replay["version_id"] == metadata["version_id"]
        assert _counts(migrated_engine, MUTATION_TABLES) == before
    assert set(_counts(migrated_engine, INTELLIGENCE_TABLES).values()) == {0}


def test_a_stale_update_and_a_stale_move_write_nothing(migrated_engine: Engine) -> None:
    principal = operator()
    with mcp_transport(_service(migrated_engine), principal) as mcp:
        rid = _ok(_send(mcp, principal, Capability.REPORTS_PUBLISH, MINIMAL))["report_id"]
        _ok(_send(mcp, principal, Capability.REPORTS_UPDATE, _update(rid, "u1", {"title": "A"}, 1)))
        before = _counts(migrated_engine, MUTATION_TABLES)
        stale = _send(
            mcp, principal, Capability.REPORTS_UPDATE, _update(rid, "u2", {"title": "B"}, 1)
        )
        assert stale["error"]["code"] == "conflict"
        assert stale["error"]["safe_details"] == ["stale_version"]
        moved = _send(mcp, principal, Capability.REPORTS_ARCHIVE, _move(rid, "a1", 3))
        assert moved["error"]["code"] == "conflict"
        assert moved["error"]["safe_details"] == ["expected_lifecycle_revision"]
        illegal = _send(mcp, principal, Capability.REPORTS_RESTORE, _move(rid, "r1", 0))
        assert illegal["error"]["code"] == "conflict"
        assert illegal["error"]["safe_details"] == ["lifecycle_state"]
        assert _counts(migrated_engine, MUTATION_TABLES) == before


def test_archive_delete_restore_round_trip_on_postgresql(migrated_engine: Engine) -> None:
    owner, stranger = operator(), operator()
    service = _service(migrated_engine)
    with mcp_transport(service, owner) as mcp:
        rid = _ok(_send(mcp, owner, Capability.REPORTS_PUBLISH, MINIMAL))["report_id"]
        archived = _ok(_send(mcp, owner, Capability.REPORTS_ARCHIVE, _move(rid, "a", 0)))
        assert (archived["lifecycle_state"], archived["lifecycle_revision"]) == ("archived", 1)
        withdrawn = _send(
            mcp, owner, Capability.REPORTS_UPDATE, _update(rid, "u", {"title": "A"}, 1)
        )
        assert withdrawn["error"]["code"] == "denied"
        assert withdrawn["error"]["safe_details"] == ["report_withdrawn"]
        trashed = _ok(_send(mcp, owner, Capability.REPORTS_DELETE, _move(rid, "d", 1)))
        assert (trashed["prior_state"], trashed["lifecycle_state"]) == ("archived", "trashed")
        hidden = _send(mcp, owner, Capability.REPORTS_READ, {"report_id": rid})
        assert hidden["error"]["code"] == "not_found"
        restored = _ok(_send(mcp, owner, Capability.REPORTS_RESTORE, _move(rid, "r", 2)))
        assert (restored["lifecycle_state"], restored["lifecycle_revision"]) == ("archived", 3)
        read = _ok(
            _send(
                mcp, owner, Capability.REPORTS_READ, {"report_id": rid, "include_withdrawn": True}
            )
        )
        assert read["lifecycle_state"] == "archived"
        assert read["content"]["body"] == BODY
        events = _ok(
            _send(
                mcp,
                owner,
                Capability.REPORTS_HISTORY,
                {"report_id": rid, "entries": "lifecycle", "include_withdrawn": True},
            )
        )
        assert [(e["operation"], e["resulting_state"]) for e in events["items"]] == [
            ("archive", "archived"),
            ("delete", "trashed"),
            ("restore", "archived"),
        ]
        assert _counts(migrated_engine, ("report_lifecycle_events", "report_versions")) == {
            "report_lifecycle_events": 3,
            "report_versions": 1,
        }
    with mcp_transport(service, stranger) as mcp:
        before = _counts(migrated_engine, MUTATION_TABLES)
        foreign = [
            _send(mcp, stranger, Capability.REPORTS_RESTORE, _move(rid, "fr", 3)),
            _send(mcp, stranger, Capability.REPORTS_UPDATE, _update(rid, "fu", {"title": "X"}, 1)),
            _send(
                mcp,
                stranger,
                Capability.REPORTS_HISTORY,
                {"report_id": rid, "include_withdrawn": True},
            ),
        ]
        assert _counts(migrated_engine, MUTATION_TABLES) == before
    for answer in foreign:
        assert answer["error"]["code"] == "not_found"
        assert answer["error"]["safe_details"] == ["artifact_id"]


# ---- Reports Modernization WP04: the catalog and the history cursor ------------------------


def test_history_root_visibility_outranks_a_bad_cursor(migrated_engine: Engine) -> None:
    """C11(1): a cursor refusal is only ever about a report the caller may see."""
    owner, stranger = operator(), operator()
    service = _service(migrated_engine)
    with mcp_transport(service, owner) as mcp:
        rid = _ok(_send(mcp, owner, Capability.REPORTS_PUBLISH, MINIMAL))["report_id"]
        other = _ok(
            _send(
                mcp,
                owner,
                Capability.REPORTS_PUBLISH,
                {**MINIMAL, "idempotency_key": "db-publish-other", "client_intent_id": "o-1"},
            )
        )
        alien = other["version_id"]
        bad_cursor = {"report_id": rid, "after": alien}
        visible = _send(mcp, owner, Capability.REPORTS_HISTORY, bad_cursor)
        assert visible["error"]["safe_details"] == ["cursor"]
        missing = _send(
            mcp,
            owner,
            Capability.REPORTS_HISTORY,
            {"report_id": "grpt_00000000missing0", "after": alien},
        )
        assert (missing["error"]["code"], missing["error"]["safe_details"]) == (
            "not_found",
            ["artifact_id"],
        )
        _ok(_send(mcp, owner, Capability.REPORTS_ARCHIVE, _move(rid, "db-archive", 0)))
        hidden = _send(mcp, owner, Capability.REPORTS_HISTORY, bad_cursor)
        assert (hidden["error"]["code"], hidden["error"]["safe_details"]) == (
            "not_found",
            ["artifact_id"],
        )
        asked = _send(
            mcp, owner, Capability.REPORTS_HISTORY, {**bad_cursor, "include_withdrawn": True}
        )
        assert (asked["error"]["code"], asked["error"]["safe_details"]) == (
            "invalid_request",
            ["cursor"],
        )
    with mcp_transport(service, stranger) as mcp:
        foreign = _send(
            mcp, stranger, Capability.REPORTS_HISTORY, {**bad_cursor, "include_withdrawn": True}
        )
    assert (foreign["error"]["code"], foreign["error"]["safe_details"]) == (
        "not_found",
        ["artifact_id"],
    )


def test_standalone_catalog_pages_with_a_bound_cursor_over_mcp(migrated_engine: Engine) -> None:
    """The standalone list and search, end to end on PostgreSQL through the MCP schema."""
    owner, stranger = operator(), operator()
    service = _service(migrated_engine)
    with mcp_transport(service, owner) as mcp:
        ids = [
            _ok(
                _send(
                    mcp,
                    owner,
                    Capability.REPORTS_PUBLISH,
                    {
                        **MINIMAL,
                        "title": f"Curlew survey {index}",
                        "topics": ["birds"],
                        "idempotency_key": f"db-catalog-{index}",
                        "client_intent_id": f"c-{index}",
                    },
                )
            )["report_id"]
            for index in range(3)
        ]
        first = _ok(
            _send(
                mcp,
                owner,
                Capability.REPORTS_LIST,
                {"plane": "standalone", "page_size": 2, "topics": ["birds"]},
            )
        )
        assert first["plane"] == "standalone"
        assert len(first["items"]) == 2
        assert first["next_cursor"] is not None
        rest = _ok(
            _send(
                mcp,
                owner,
                Capability.REPORTS_LIST,
                {
                    "plane": "standalone",
                    "page_size": 2,
                    "topics": ["birds"],
                    "cursor": first["next_cursor"],
                },
            )
        )
        assert rest["next_cursor"] is None
        listed = [item["report_id"] for item in first["items"] + rest["items"]]
        assert sorted(listed) == sorted(ids)
        assert all(item["plane"] == "standalone" for item in first["items"] + rest["items"])
        # The cursor is bound: another filter set refuses it.
        changed = _send(
            mcp,
            owner,
            Capability.REPORTS_LIST,
            {"plane": "standalone", "page_size": 2, "cursor": first["next_cursor"]},
        )
        assert changed["error"]["safe_details"] == ["cursor"]
        found = _ok(
            _send(
                mcp,
                owner,
                Capability.REPORTS_SEARCH,
                {"plane": "all", "query": "curlew", "page_size": 5},
            )
        )
        assert sorted(item["report_id"] for item in found["items"]) == sorted(ids)
        assert all(item["snippet"] for item in found["items"])
    with mcp_transport(service, stranger) as mcp:
        theirs = _ok(_send(mcp, stranger, Capability.REPORTS_LIST, {"plane": "all"}))
        stolen = _send(
            mcp,
            stranger,
            Capability.REPORTS_LIST,
            {
                "plane": "standalone",
                "page_size": 2,
                "topics": ["birds"],
                "cursor": first["next_cursor"],
            },
        )
    assert theirs["items"] == []
    assert stolen["error"]["safe_details"] == ["cursor"]
