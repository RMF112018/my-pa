"""Versioned project update/close against a live PostgreSQL server."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.commands import CloseProject, CreateProject, UpdateProject
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.contracts.v1.errors import ErrorCode, RetryGuidance
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.situation.situation import ProjectState
from my_pa.domain.source.registry import issue_identifier
from tests.database.test_continuity_authoring import SCHEMA, WHEN, _Runtime

pytestmark = pytest.mark.database

PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[_Runtime]:
    composed = _Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _create(runtime: _Runtime, *, name: str, key: str) -> dict:
    created = runtime.invoke(CreateProject(name=name, idempotency_key=key))
    assert created.error is None and created.result is not None
    return created.result


def test_sql_update_and_close_persist_history(runtime: _Runtime, migrated_engine: Engine) -> None:
    created = _create(runtime, name="SQL mutable", key="mutate-db-fields-0001")
    project_id = created["project_id"]
    renamed = runtime.invoke(
        UpdateProject(
            project_id=project_id,
            expected_version=1,
            idempotency_key="mutate-db-name-0001",
            name="SQL renamed",
        )
    )
    assert renamed.error is None and renamed.result is not None
    assert renamed.result["name"] == "SQL renamed"
    assert renamed.result["version"] == 2
    held = runtime.invoke(
        UpdateProject(
            project_id=project_id,
            expected_version=2,
            idempotency_key="mutate-db-hold-0001",
            state=ProjectState.ON_HOLD,
        )
    )
    assert held.error is None and held.result is not None
    closed = runtime.invoke(
        CloseProject(
            project_id=project_id,
            expected_version=3,
            idempotency_key="mutate-db-close-0001",
        )
    )
    assert closed.error is None and closed.result is not None
    assert closed.result["state"] == "closed"
    assert closed.result["closed_at"] is not None
    with migrated_engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    f"SELECT state, version, closed_at FROM {SCHEMA}.projects "  # noqa: S608
                    "WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            )
            .mappings()
            .one()
        )
        history = (
            connection.execute(
                text(
                    f"SELECT action, outcome, before_version, after_version "  # noqa: S608
                    f"FROM {SCHEMA}.project_history WHERE project_id = :project_id "
                    "ORDER BY recorded_at, history_id"
                ),
                {"project_id": project_id},
            )
            .mappings()
            .all()
        )
    assert row["state"] == "closed"
    assert int(row["version"]) == 4
    assert row["closed_at"] is not None
    assert [item["action"] for item in history] == ["update", "update", "close"]
    assert [item["outcome"] for item in history] == ["applied", "applied", "applied"]
    assert [int(item["after_version"]) for item in history] == [2, 3, 4]


def test_sql_stale_write_commits_rejected_history(
    runtime: _Runtime, migrated_engine: Engine
) -> None:
    created = _create(runtime, name="SQL stale", key="mutate-db-stale-0001")
    first = runtime.invoke(
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-db-stale-win-0001",
            name="Winner",
        )
    )
    assert first.error is None
    stale = runtime.invoke(
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-db-stale-lose-0001",
            name="Loser",
        )
    )
    assert stale.error is not None
    assert stale.error.code is ErrorCode.CONFLICT
    assert list(stale.error.safe_details) == ["project_id"]
    assert stale.error.retry is RetryGuidance.AFTER_REFRESH
    with migrated_engine.connect() as connection:
        version = connection.execute(
            text(
                f"SELECT version FROM {SCHEMA}.projects "  # noqa: S608
                "WHERE project_id = :project_id"
            ),
            {"project_id": created["project_id"]},
        ).scalar_one()
        outcomes = (
            connection.execute(
                text(
                    f"SELECT outcome FROM {SCHEMA}.project_history "  # noqa: S608
                    "WHERE project_id = :project_id ORDER BY recorded_at, history_id"
                ),
                {"project_id": created["project_id"]},
            )
            .scalars()
            .all()
        )
    assert int(version) == 2
    assert list(outcomes) == ["applied", "rejected"]


def test_sql_idempotent_replay(runtime: _Runtime) -> None:
    created = _create(runtime, name="SQL replay", key="mutate-db-replay-0001")
    command = UpdateProject(
        project_id=created["project_id"],
        expected_version=1,
        idempotency_key="mutate-db-replay-update-0001",
        name="Replayed",
    )
    first = runtime.invoke(command)
    second = runtime.invoke(command)
    assert first.error is None and second.error is None
    assert first.result is not None and second.result is not None
    assert second.result["replayed"] is True
    assert second.result["version"] == first.result["version"] == 2


def test_sql_cross_principal_is_not_found(runtime: _Runtime) -> None:
    created = _create(runtime, name="SQL owned", key="mutate-db-iso-0001")
    stranger = Principal(principal_id=PRINCIPAL_B, kind=PrincipalKind.OPERATOR, authenticated=True)
    refused = runtime.service.invoke(
        RequestMetadata(
            request_id=issue_identifier(IdKind.CORRELATION),
            capability=UpdateProject.capability,
            purpose=Purpose.CONTINUITY_AUTHORING,
            principal_id=stranger.principal_id,
            requested_at=WHEN,
        ),
        UpdateProject(
            project_id=created["project_id"],
            expected_version=1,
            idempotency_key="mutate-db-iso-stranger-0001",
            name="Hijack",
        ),
        principal=stranger,
    )
    assert refused.error is not None
    assert refused.error.code is ErrorCode.NOT_FOUND


def test_sql_concurrent_writers_serialize_on_row_lock(migrated_engine: Engine) -> None:
    url = str(migrated_engine.url)
    setup = _Runtime(url)
    try:
        created = setup.invoke(
            CreateProject(name="SQL race", idempotency_key="mutate-db-race-create-0001")
        )
    finally:
        setup.close()
    assert created.error is None and created.result is not None
    project_id = created.result["project_id"]
    barrier = threading.Barrier(2, timeout=10)
    results: list[object] = []
    errors: list[BaseException] = []

    def worker(key: str, name: str) -> None:
        runtime = _Runtime(url)
        try:
            barrier.wait()
            results.append(
                runtime.invoke(
                    UpdateProject(
                        project_id=project_id,
                        expected_version=1,
                        idempotency_key=key,
                        name=name,
                    )
                )
            )
        except BaseException as error:
            errors.append(error)
        finally:
            runtime.close()

    threads = [
        threading.Thread(target=worker, args=("mutate-db-race-a-0001", "Writer A")),
        threading.Thread(target=worker, args=("mutate-db-race-b-0001", "Writer B")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert errors == []
    envelopes = results
    codes = [
        None if envelope.error is None else envelope.error.code  # type: ignore[union-attr]
        for envelope in envelopes
    ]
    assert codes.count(None) == 1
    assert codes.count(ErrorCode.CONFLICT) == 1
    with migrated_engine.connect() as connection:
        version = connection.execute(
            text(
                f"SELECT version FROM {SCHEMA}.projects "  # noqa: S608
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        ).scalar_one()
        outcomes = (
            connection.execute(
                text(
                    f"SELECT outcome FROM {SCHEMA}.project_history "  # noqa: S608
                    "WHERE project_id = :project_id"
                ),
                {"project_id": project_id},
            )
            .scalars()
            .all()
        )
    assert int(version) == 2
    assert sorted(outcomes) == ["applied", "rejected"]
