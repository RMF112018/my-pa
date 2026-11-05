"""Reports Modernization WP05 A1-A3, A5: creator attribution on PostgreSQL.

The `database` tier, one disposable head-migrated clone per test
(`migrated_engine`). What it proves, for `SqlGeneralReportRepository`:

* publish stores the server-derived creator on the root and as version 1's
  author, equal; the manifest names the author and the read rebuild verifies
  it; a replay returns the stored result whoever replays it;
* an update by another creator keeps the root's creator and records the new
  author on the new version only;
* the root's creator columns and a version's author columns cannot be
  rewritten (the root trigger and append-only refuse the UPDATE);
* the `created_by` catalog filter: an exact match on the root creator,
  Principal-scoped (a foreign report with the same creator id is invisible),
  an unknown creator an empty page, and the legacy plane never matches it;
* the creator-filter index exists as declared.

Every identifier and byte is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.catalog import CatalogFilters
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, ReportCreator, derive_creator
from my_pa.domain.reports.publication import PublicationRequest
from my_pa.domain.reports.revision import ReportPatch, UpdateRequest
from my_pa.domain.source import registry
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from tests.database.test_reports_general_catalog import (
    _artifact,
    _ids,
    _legacy_ids,
    _page,
    _publish,
)
from tests.database.test_reports_general_persistence import PRINCIPAL_A, PRINCIPAL_B

pytestmark = pytest.mark.database

T0: Final = datetime(2026, 11, 5, 9, 0, tzinfo=UTC)
LOCAL: Final = derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL_A)
REMOTE: Final = derive_creator(CreatorKind.REMOTE_CLIENT, "client-synthetic-0001")
UNKNOWN: Final = "gcrt_" + "f" * 40
RESTRICT_VIOLATION: Final = "23001"


def _author(creator: ReportCreator) -> dict[str, str]:
    return {"kind": creator.kind.value, "id": creator.creator_id}


def _publish_as(
    engine: Engine, creator: ReportCreator, key: str, *, principal_id: str = PRINCIPAL_A
) -> tuple[str, bool]:
    request = PublicationRequest(
        title="Creator report",
        content=validate_content({"format": "markdown", "body": "creator body"}),
    )
    with engine.begin() as connection:
        result = SqlGeneralReportRepository(connection).publish(
            request,
            principal_id=principal_id,
            creator=creator,
            idempotency_key=key,
            recorded_at=T0,
            correlation_id=registry.issue_identifier(IdKind.CORRELATION),
            audit_id=registry.issue_identifier(IdKind.AUDIT),
        )
    return result.receipt.report_id, result.replayed


def _update_as(engine: Engine, report_id: str, creator: ReportCreator) -> None:
    with engine.begin() as connection:
        SqlGeneralReportRepository(connection).update(
            UpdateRequest(
                report_id=report_id,
                expected_version=1,
                patch=ReportPatch(title="Retitled by another writer"),
                change_reason="Synthetic change.",
            ),
            principal_id=PRINCIPAL_A,
            creator=creator,
            idempotency_key=f"upd-{report_id}",
            recorded_at=T0 + timedelta(hours=1),
            correlation_id=registry.issue_identifier(IdKind.CORRELATION),
            audit_id=registry.issue_identifier(IdKind.AUDIT),
        )


def test_publish_records_the_creator_as_root_creator_and_first_author(
    migrated_engine: Engine,
) -> None:
    report_id, replayed = _publish_as(migrated_engine, REMOTE, "pub")
    assert not replayed
    with migrated_engine.connect() as connection:
        stored = SqlGeneralReportRepository(connection).read_version(
            report_id, principal_id=PRINCIPAL_A
        )
        row = connection.execute(
            text(
                "SELECT r.created_by_kind, r.created_by_id, v.authored_by_kind, "
                "v.authored_by_id FROM knowledge.report_roots r JOIN knowledge.report_versions v "
                "ON v.report_id = r.report_id WHERE r.report_id = :r"
            ),
            {"r": report_id},
        ).one()
    assert tuple(row) == ("remote_client", REMOTE.creator_id) * 2
    assert stored is not None
    assert stored.root.creator == stored.version.author == REMOTE
    # The manifest names the author; the read rebuilt and verified it.
    assert stored.manifest["author"] == _author(REMOTE)


def test_a_replay_returns_the_stored_result_whoever_replays(migrated_engine: Engine) -> None:
    report_id, _ = _publish_as(migrated_engine, LOCAL, "same-key")
    again, replayed = _publish_as(migrated_engine, REMOTE, "same-key")
    assert (again, replayed) == (report_id, True)
    with migrated_engine.connect() as connection:
        stored = SqlGeneralReportRepository(connection).read_version(
            report_id, principal_id=PRINCIPAL_A
        )
    assert stored is not None
    assert stored.root.creator == LOCAL


def test_an_update_by_another_writer_keeps_the_creator_and_records_its_author(
    migrated_engine: Engine,
) -> None:
    report_id, _ = _publish_as(migrated_engine, LOCAL, "pub")
    _update_as(migrated_engine, report_id, REMOTE)
    with migrated_engine.connect() as connection:
        repository = SqlGeneralReportRepository(connection)
        head = repository.read_version(report_id, principal_id=PRINCIPAL_A)
        first = repository.read_version(report_id, principal_id=PRINCIPAL_A, version_number=1)
        history = repository.version_history(
            report_id, principal_id=PRINCIPAL_A, include_manifests=True, page_size=10
        )
    assert head is not None and first is not None and history is not None
    assert head.version.version_number == 2
    assert head.root.creator == first.root.creator == LOCAL
    assert (first.version.author, head.version.author) == (LOCAL, REMOTE)
    assert (first.manifest["author"], head.manifest["author"]) == (_author(LOCAL), _author(REMOTE))
    assert [item.author for item in history.items] == [LOCAL, REMOTE]
    assert [entry.creator for entry in _page(migrated_engine)] == [LOCAL]


@pytest.mark.parametrize(
    ("statement", "message"),
    [
        (
            "UPDATE knowledge.report_roots SET created_by_id = :other WHERE report_id = :r",
            "a report root is immutable but for its caches",
        ),
        (
            "UPDATE knowledge.report_roots SET created_by_kind = 'remote_client' "
            "WHERE report_id = :r",
            "a report root is immutable but for its caches",
        ),
        (
            "UPDATE knowledge.report_versions SET authored_by_id = :other WHERE report_id = :r",
            "report_versions is append-only",
        ),
    ],
)
def test_creator_and_author_columns_cannot_be_rewritten(
    migrated_engine: Engine, statement: str, message: str
) -> None:
    report_id, _ = _publish_as(migrated_engine, LOCAL, "pub")
    with pytest.raises(DBAPIError) as raised, migrated_engine.begin() as connection:
        connection.execute(text(statement), {"r": report_id, "other": UNKNOWN})
    assert getattr(raised.value.orig, "sqlstate", None) == RESTRICT_VIOLATION
    assert message in str(raised.value.orig)


def test_the_created_by_filter_is_exact_and_principal_scoped(migrated_engine: Engine) -> None:
    mine_local = _publish(migrated_engine, created_at=T0, creator=LOCAL)
    mine_remote = _publish(migrated_engine, created_at=T0 + timedelta(hours=1), creator=REMOTE)
    # Another Principal's report with the very same creator id.
    foreign = _publish(
        migrated_engine,
        created_at=T0 + timedelta(hours=2),
        principal_id=PRINCIPAL_B,
        creator=REMOTE,
    )
    assert _ids(_page(migrated_engine, CatalogFilters(created_by=REMOTE.creator_id))) == [
        mine_remote
    ]
    assert _ids(_page(migrated_engine, CatalogFilters(created_by=LOCAL.creator_id))) == [mine_local]
    assert _ids(_page(migrated_engine, CatalogFilters(created_by=UNKNOWN))) == []
    assert _ids(_page(migrated_engine)) == [mine_remote, mine_local]
    assert _ids(
        _page(migrated_engine, CatalogFilters(created_by=REMOTE.creator_id), query="plain")
    ) == [mine_remote]
    assert _ids(
        _page(
            migrated_engine,
            CatalogFilters(created_by=REMOTE.creator_id),
            principal_id=PRINCIPAL_B,
        )
    ) == [foreign]
    assert [entry.creator for entry in _page(migrated_engine)] == [REMOTE, LOCAL]


def test_the_legacy_plane_never_matches_a_creator(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        _artifact(connection, artifact_id="rpt_creator0001", committed_at=T0)
    assert _legacy_ids(migrated_engine) == ["rpt_creator0001"]
    for creator_id in (LOCAL.creator_id, REMOTE.creator_id, UNKNOWN):
        filters = CatalogFilters(created_by=creator_id)
        assert _legacy_ids(migrated_engine, filters) == []
        assert _legacy_ids(migrated_engine, filters, query="legacy") == []


def test_the_creator_filter_index_exists(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as connection:
        definition = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'knowledge' "
                "AND indexname = 'report_roots_by_owner_and_creator'"
            )
        ).scalar_one()
    assert definition == (
        "CREATE INDEX report_roots_by_owner_and_creator ON knowledge.report_roots "
        "USING btree (owner_principal_id, created_by_id, created_at DESC, report_id)"
    )
