"""Focused PostgreSQL evidence for durable RI re-enrichment work."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.entity_reenrichment import (
    BindingVersion,
    ReenrichmentBinding,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    StaleBindingReason,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity_reenrichment import (
    ReenrichmentTables,
    SqlReenrichmentWorkRepository,
)
from my_pa.infrastructure.persistence.tables import (
    entity_reenrichment_subjects,
    entity_reenrichment_version_watermarks,
    entity_reenrichment_work,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_ri_reenrichment_test"
PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
ENTITY: Final = "ent_aaaa0001aaaa0001"
WHEN: Final = datetime(2026, 8, 28, 12, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        administer(drop)
        maintenance.dispose()


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    migrated = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield migrated
    finally:
        migrated.dispose()


def _tables() -> ReenrichmentTables:
    return ReenrichmentTables(
        entity_reenrichment_work,
        entity_reenrichment_subjects,
        entity_reenrichment_version_watermarks,
    )


def _binding(trigger: ReenrichmentTrigger = ReenrichmentTrigger.NEW_ALIAS) -> ReenrichmentBinding:
    return ReenrichmentBinding(
        principal_id=PRINCIPAL,
        trigger=trigger,
        cause_record_id="eals_aaaa0001aaaa0001",
        subjects=(ReenrichmentSubject(ReenrichmentSubjectKind.ENTITY, ENTITY, "7"),),
        input_versions=(BindingVersion("source", "v2"),),
        producer_versions=(BindingVersion("resolver", "v3"),),
        policy_version="ri-v0.2",
    )


class _Current:
    def __init__(self, binding: ReenrichmentBinding) -> None:
        self.binding = binding

    def subject_version(
        self, principal_id: str, kind: ReenrichmentSubjectKind, subject_id: str
    ) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        return next(
            (
                item.version
                for item in self.binding.subjects
                if item.kind is kind and item.subject_id == subject_id
            ),
            None,
        )

    def input_version(self, principal_id: str, key: str) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        return next((item.version for item in self.binding.input_versions if item.key == key), None)

    def producer_version(self, principal_id: str, key: str) -> str | None:
        if principal_id != PRINCIPAL:
            return None
        return next(
            (item.version for item in self.binding.producer_versions if item.key == key), None
        )

    def policy_version(self, principal_id: str) -> str | None:
        return self.binding.policy_version if principal_id == PRINCIPAL else None


def test_registration_is_deduplicated_by_the_complete_binding(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        first = repository.register(_binding(), at=WHEN)
        replay = repository.register(_binding(), at=WHEN)
    assert replay.work_id == first.work_id
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM knowledge.entity_reenrichment_work")
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("SELECT count(*) FROM knowledge.entity_reenrichment_subjects")
            ).scalar_one()
            == 1
        )


def test_claim_is_exclusive_and_stale_completion_preserves_why(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        registered = repository.register(_binding(), at=WHEN)
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        claimed = repository.claim(owner="worker_a", at=WHEN)
        assert claimed is not None and claimed.work_id == registered.work_id
    with engine.begin() as connection:
        assert (
            SqlReenrichmentWorkRepository(connection, _tables()).claim(owner="worker_b", at=WHEN)
            is None
        )
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        assert repository.mark_stale(
            PRINCIPAL,
            registered.work_id,
            owner="worker_a",
            reasons=(StaleBindingReason.SUBJECT_VERSION_CHANGED,),
            at=WHEN,
        )
        stored = repository.get(PRINCIPAL, registered.work_id)
    assert stored is not None
    assert stored.state == "stale"
    assert stored.stale_reasons == (StaleBindingReason.SUBJECT_VERSION_CHANGED.value,)


def test_expired_claims_recover_until_the_final_attempt_then_fail(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        registered = repository.register(_binding(), at=WHEN)
        first = repository.claim(owner="worker_a", at=WHEN, lease_seconds=1)
        assert first is not None and first.attempt_count == 1

    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        second = repository.claim(owner="worker_b", at=WHEN + timedelta(seconds=1), lease_seconds=1)
        assert second is not None and second.work_id == registered.work_id
        assert second.attempt_count == 2

    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        final = repository.claim(owner="worker_c", at=WHEN + timedelta(seconds=2), lease_seconds=1)
        assert final is not None and final.attempt_count == final.max_attempts

    failed_at = WHEN + timedelta(seconds=3)
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        assert repository.claim(owner="worker_d", at=failed_at) is None
        stored = repository.get(PRINCIPAL, registered.work_id)

    assert stored is not None
    assert stored.state is ReenrichmentState.FAILED
    assert stored.attempt_count == stored.max_attempts
    assert stored.lease_owner is None
    assert stored.lease_expires_at is None
    assert stored.completed_at == failed_at
    assert stored.last_error_code == "lease_expired"


def test_all_nine_trigger_values_are_admitted_at_head(engine: Engine) -> None:
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        for trigger in ReenrichmentTrigger:
            repository.register(_binding(trigger), at=WHEN)
    with engine.connect() as connection:
        stored = set(
            connection.execute(
                text("SELECT trigger FROM knowledge.entity_reenrichment_work")
            ).scalars()
        )
    assert stored == {trigger.value for trigger in ReenrichmentTrigger}


def test_expiry_during_apply_rolls_back_effect_and_allows_one_reclaim(engine: Engine) -> None:
    """A concurrent reclaimer sees the row fence; an expired callback leaves no effect."""
    binding = _binding()
    claimed_at = datetime.now(UTC)
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        registered = repository.register(binding, at=claimed_at)
        claimed = repository.claim(owner="worker_a", at=claimed_at, lease_seconds=2)
        assert claimed is not None

    callback_started = Event()

    def expire_inside_callback() -> int:
        with engine.begin() as connection:
            connection.execute(
                text("CREATE TEMP TABLE reenrichment_effect_probe (effect_id text PRIMARY KEY)")
            )
            repository = SqlReenrichmentWorkRepository(connection, _tables())

            def apply(_binding: ReenrichmentBinding, effect_id: str) -> None:
                assert effect_id == binding.binding_sha256
                connection.execute(
                    text("INSERT INTO reenrichment_effect_probe (effect_id) VALUES (:effect_id)"),
                    {"effect_id": effect_id},
                )
                callback_started.set()
                connection.execute(text("SELECT pg_sleep(2.2)"))

            with pytest.raises(RuntimeError, match="lease expired before atomic completion"):
                repository.apply_claimed(
                    PRINCIPAL,
                    registered.work_id,
                    owner="worker_a",
                    current=_Current(binding),
                    apply=apply,
                    at=claimed_at,
                )
            return int(
                connection.execute(
                    text("SELECT count(*) FROM reenrichment_effect_probe")
                ).scalar_one()
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        applying = executor.submit(expire_inside_callback)
        assert callback_started.wait(timeout=2)
        with engine.begin() as connection:
            concurrent = SqlReenrichmentWorkRepository(connection, _tables()).claim(
                owner="worker_b",
                at=claimed_at + timedelta(seconds=10),
            )
        assert concurrent is None
        assert applying.result(timeout=5) == 0

    with engine.begin() as connection:
        reclaimed = SqlReenrichmentWorkRepository(connection, _tables()).claim(
            owner="worker_b",
            at=claimed_at + timedelta(seconds=10),
        )
    assert reclaimed is not None
    assert reclaimed.work_id == registered.work_id
    assert reclaimed.attempt_count == 2
