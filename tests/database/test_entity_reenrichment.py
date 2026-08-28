"""Focused PostgreSQL evidence for durable RI re-enrichment work."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, make_url

from my_pa.application.entity_reenrichment import (
    BindingVersion,
    EntityReenrichmentService,
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
    SqlCurrentReenrichmentBindings,
    SqlReenrichmentWorkRepository,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
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


def _current_binding() -> ReenrichmentBinding:
    return ReenrichmentBinding(
        principal_id=PRINCIPAL,
        trigger=ReenrichmentTrigger.POLICY_CHANGE,
        cause_record_id="audit_aaaa0001aaaa0001",
        subjects=(ReenrichmentSubject(ReenrichmentSubjectKind.PRINCIPAL, PRINCIPAL, "1"),),
        input_versions=(BindingVersion("source", "v2"),),
        producer_versions=(BindingVersion("resolver", "v3"),),
        policy_version="ri-v0.2",
    )


def _observe_current_versions(repository: SqlReenrichmentWorkRepository) -> None:
    for namespace, key, version in (
        ("input", "source", "v2"),
        ("producer", "resolver", "v3"),
        ("policy", "current", "ri-v0.2"),
    ):
        repository.observe_version(
            PRINCIPAL,
            namespace=namespace,
            key=key,
            version=version,
            at=WHEN,
        )


def _stage_entity_binding_currency(
    connection: Connection,
    repository: SqlReenrichmentWorkRepository,
    binding: ReenrichmentBinding,
) -> None:
    connection.execute(
        entities.insert().values(
            entity_id=ENTITY,
            principal_id=PRINCIPAL,
            entity_type="person",
            canonical_name="synthetic entity",
            display_name="Synthetic Entity",
            status="active",
            created_at=WHEN,
            updated_at=WHEN,
            version=7,
        )
    )
    for item in binding.input_versions:
        repository.observe_version(
            PRINCIPAL, namespace="input", key=item.key, version=item.version, at=WHEN
        )
    for item in binding.producer_versions:
        repository.observe_version(
            PRINCIPAL, namespace="producer", key=item.key, version=item.version, at=WHEN
        )
    repository.observe_version(
        PRINCIPAL,
        namespace="policy",
        key="current",
        version=binding.policy_version,
        at=WHEN,
    )


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
        _stage_entity_binding_currency(connection, repository, binding)
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
                    current=SqlCurrentReenrichmentBindings(connection, _tables()),
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
        assert callback_started.is_set()

    with engine.begin() as connection:
        reclaimed = SqlReenrichmentWorkRepository(connection, _tables()).claim(
            owner="worker_b",
            at=claimed_at + timedelta(seconds=10),
        )
    assert reclaimed is not None
    assert reclaimed.work_id == registered.work_id
    assert reclaimed.attempt_count == 2


def test_watermark_advance_waits_for_apply_fence_then_stales_future_work(
    engine: Engine,
) -> None:
    """The Principal fence linearizes apply settlement before watermark advance."""
    binding = _binding()
    claimed_at = datetime.now(UTC)
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        _stage_entity_binding_currency(connection, repository, binding)
        registered = repository.register(binding, at=claimed_at)
        claimed = repository.claim(owner="worker_a", at=claimed_at, lease_seconds=30)
        assert claimed is not None

    callback_started = Event()
    release_callback = Event()
    writer_attempted = Event()
    writer_finished = Event()
    writer_backend_pid: list[int] = []

    def apply_current_binding() -> tuple[bool, ReenrichmentState]:
        with engine.begin() as connection:
            repository = SqlReenrichmentWorkRepository(connection, _tables())

            def apply(held: ReenrichmentBinding, effect_id: str) -> None:
                assert effect_id == held.binding_sha256
                callback_started.set()
                assert release_callback.wait(timeout=10)

            currency = repository.apply_claimed(
                PRINCIPAL,
                registered.work_id,
                owner="worker_a",
                current=SqlCurrentReenrichmentBindings(connection, _tables()),
                apply=apply,
                at=claimed_at,
            )
            stored = repository.get(PRINCIPAL, registered.work_id)
            assert stored is not None
            return currency.is_current, stored.state

    def advance_watermark() -> str | None:
        try:
            with engine.begin() as connection:
                writer_backend_pid.append(
                    int(connection.execute(text("SELECT pg_backend_pid()")).scalar_one())
                )
                writer_attempted.set()
                observation = SqlReenrichmentWorkRepository(connection, _tables()).observe_version(
                    PRINCIPAL,
                    namespace="input",
                    key="source",
                    version="v3",
                    at=claimed_at + timedelta(seconds=1),
                )
                return observation.previous
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        applying = executor.submit(apply_current_binding)
        assert callback_started.wait(timeout=5)
        advancing = executor.submit(advance_watermark)
        assert writer_attempted.wait(timeout=5)
        assert not writer_finished.wait(timeout=0.2)
        with engine.connect() as observer:
            wait_type = observer.execute(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": writer_backend_pid[0]},
            ).scalar_one()
        assert wait_type == "Lock"
        release_callback.set()
        assert applying.result(timeout=10) == (True, ReenrichmentState.SUCCEEDED)
        assert advancing.result(timeout=10) == "v2"

    stale_binding = replace(binding, cause_record_id="eals_bbbb0002bbbb0002")
    stale_at = claimed_at + timedelta(seconds=2)
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        stale_registered = repository.register(stale_binding, at=stale_at)
        stale_claimed = repository.claim(owner="worker_b", at=stale_at, lease_seconds=30)
        assert stale_claimed is not None

    applied: list[str] = []
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        currency = repository.apply_claimed(
            PRINCIPAL,
            stale_registered.work_id,
            owner="worker_b",
            current=SqlCurrentReenrichmentBindings(connection, _tables()),
            apply=lambda _held, effect_id: applied.append(effect_id),
            at=stale_at,
        )
        stored = repository.get(PRINCIPAL, stale_registered.work_id)
    assert currency.reasons == (StaleBindingReason.INPUT_VERSION_CHANGED,)
    assert applied == []
    assert stored is not None and stored.state is ReenrichmentState.STALE


def test_changed_input_is_marked_stale_before_the_applier_runs(engine: Engine) -> None:
    applied: list[str] = []
    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, _tables())
        _observe_current_versions(repository)
        repository.register(_current_binding(), at=WHEN)
        claimed = repository.claim(owner="worker_a", at=WHEN)
        assert claimed is not None
        repository.observe_version(
            PRINCIPAL,
            namespace="input",
            key="source",
            version="v3",
            at=WHEN,
        )
        currency = EntityReenrichmentService(repository).apply_claimed(
            claimed,
            owner="worker_a",
            current=SqlCurrentReenrichmentBindings(connection, _tables()),
            apply=lambda binding, _key: applied.append(binding.binding_sha256),
            at=WHEN,
        )
        stored = repository.get(PRINCIPAL, claimed.work_id)
    assert StaleBindingReason.INPUT_VERSION_CHANGED in currency.reasons
    assert applied == []
    assert stored is not None and stored.state == "stale"


def test_currency_rows_remain_locked_until_apply_and_completion_commit(engine: Engine) -> None:
    started = Event()
    future: Future[None] | None = None
    executor = ThreadPoolExecutor(max_workers=1)

    def advance_policy() -> None:
        with engine.begin() as other_connection:
            started.set()
            SqlReenrichmentWorkRepository(other_connection, _tables()).observe_version(
                PRINCIPAL,
                namespace="policy",
                key="current",
                version="ri-v0.3",
                at=WHEN + timedelta(seconds=1),
            )

    try:
        with engine.begin() as connection:
            repository = SqlReenrichmentWorkRepository(connection, _tables())
            _observe_current_versions(repository)
            repository.register(_current_binding(), at=WHEN)
            claimed = repository.claim(owner="worker_a", at=WHEN)
            assert claimed is not None

            def apply(_binding: ReenrichmentBinding, _key: str) -> None:
                nonlocal future
                future = executor.submit(advance_policy)
                assert started.wait(timeout=2)
                with pytest.raises(FuturesTimeoutError):
                    future.result(timeout=0.2)

            currency = EntityReenrichmentService(repository).apply_claimed(
                claimed,
                owner="worker_a",
                current=SqlCurrentReenrichmentBindings(connection, _tables()),
                apply=apply,
                at=WHEN,
            )
            assert currency.is_current
        assert future is not None
        future.result(timeout=2)
    finally:
        executor.shutdown(wait=True)
