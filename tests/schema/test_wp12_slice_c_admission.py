"""WP-12C isolated-PostgreSQL admission, revision, and concurrency evidence."""

from __future__ import annotations

import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from itertools import count
from threading import Barrier
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.application.native_baseline import (
    BaselineResumePoint,
    NativeBaselineExecutor,
    NativeBaselineJob,
)
from my_pa.application.native_sources import (
    NativeAdmissionReceipt,
    NativeReadPageReceipt,
    NativeRequestContext,
    NativeSourceController,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.native_sources import (
    NATIVE_SOURCE_PROTOCOL_V1,
    NativeAdmissionEnvelope,
    NativeBucketProgress,
    NativeBucketSelection,
    NativeCoverageState,
    NativePreflightState,
    NativeProviderFailure,
    NativeSourceKind,
)
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.native_sources import (
    ExactBucketSelection,
    NativeAdmissionAuthority,
    NativeAdmissionAuthorityError,
    NativeConfigurationRevision,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.native_sources import (
    NativeBucketBindingRecord,
    NativePersistenceConflictError,
    SqlNativeBaselineStore,
    SqlNativeReviewProposalRouter,
    SqlNativeSourceControlStore,
    SqlNativeSourceRepository,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    capture_review_cases,
    native_admission_authorities,
    native_bucket_runs,
    native_checkpoints,
    native_preflight_observations,
    native_source_review_routes,
    native_sync_jobs,
    native_sync_runs,
    source_object_versions,
    source_objects,
    source_observations,
    source_version_evidence,
)

DATABASE = "my_pa_wp12c_test"
WHEN = datetime(2026, 8, 5, 12, tzinfo=UTC)
BRIDGE = "nbrg_0000000000000001"
SOURCE = "src_0000000000000001"
ACCOUNT = "nacct_0000000000000001"
BUCKET = "nbkt_0000000000000001"
BUCKET_2 = "nbkt_0000000000000002"
CONFIGURATION = "ncfg_0000000000000001"
AUDIT = "audit_0000000000000001"
CONTEXT = capture_context("prn_0000000000000001")
OTHER_CONTEXT = capture_context("prn_0000000000000002")


def _capability_constraint_values(expression: str) -> frozenset[str]:
    return frozenset(re.findall(r"'([^']+)'", expression))


def _config() -> Config:
    return Config("alembic.ini")


@pytest.fixture
def c_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    url = configured.set(database=DATABASE).render_as_string(hide_password=False)
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
    engine = create_database_engine(url)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)'))
        maintenance.dispose()


def _seed(engine: Engine) -> None:
    statements = (
        """INSERT INTO knowledge.sources
             (source_id, provider_kind, label, classification, native_root)
           VALUES (:source, 'apple_mail', 'Synthetic Mail', 'synthetic_test', 'root')""",
        """INSERT INTO knowledge.native_bridges
             (principal_id, bridge_id, protocol_version, label, created_at)
           VALUES (:principal, :bridge, :protocol, 'Synthetic Bridge', :at)""",
        """INSERT INTO knowledge.native_source_accounts
             (principal_id, account_id, bridge_id, source_id, source_kind, label, private_locator,
              first_observed_at)
           VALUES (:principal, :account, :bridge, :source, 'mail', 'Synthetic Account',
                   'account.synthetic', :at)""",
        """INSERT INTO knowledge.native_source_buckets
             (principal_id, bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at)
           VALUES (:principal, :bucket, :account, 'mail', 'Synthetic Inbox', 'bucket.synthetic',
                   true, :at)""",
        """INSERT INTO knowledge.native_source_buckets
             (principal_id, bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at)
           VALUES (:principal, :bucket_2, :account, 'mail', 'Synthetic Archive', 'bucket.archive',
                   true, :at)""",
        """INSERT INTO knowledge.audit_events
             (audit_id, correlation_id, principal_id, capability, purpose, outcome,
              policy_version, scope_source_id_count, recorded_at)
           VALUES (:audit, 'corr_0000000000000001', 'prn_0000000000000001',
                   'native_sources.sync', 'content_extraction', 'allowed', 'policy-v1', 1, :at)""",
    )
    values = {
        "source": SOURCE,
        "bridge": BRIDGE,
        "protocol": NATIVE_SOURCE_PROTOCOL_V1,
        "account": ACCOUNT,
        "bucket": BUCKET,
        "bucket_2": BUCKET_2,
        "audit": AUDIT,
        "principal": CONTEXT.capture_principal_id,
        "at": WHEN,
    }
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), values)
    SqlNativeSourceControlStore(engine, CONTEXT).append_configuration(
        NativeConfigurationRevision(
            CONFIGURATION,
            1,
            BRIDGE,
            "America/New_York",
            date(2026, 8, 1),
            WHEN,
            ExactBucketSelection((BUCKET,)),
            WHEN,
        ),
        expected_prior_revision=0,
    )


def _seed_legacy_wp12c(engine: Engine) -> None:
    """Seed the pre-partition WP-12C schema for its own migration round-trip."""
    configuration = NativeConfigurationRevision(
        CONFIGURATION,
        1,
        BRIDGE,
        "America/New_York",
        date(2026, 8, 1),
        WHEN,
        ExactBucketSelection((BUCKET,)),
        WHEN,
    )
    statements = (
        """INSERT INTO knowledge.sources
             (source_id, provider_kind, label, classification, native_root)
           VALUES (:source, 'apple_mail', 'Synthetic Mail', 'synthetic_test', 'root')""",
        """INSERT INTO knowledge.native_bridges
             (bridge_id, protocol_version, label, created_at)
           VALUES (:bridge, :protocol, 'Synthetic Bridge', :at)""",
        """INSERT INTO knowledge.native_source_accounts
             (account_id, bridge_id, source_id, source_kind, label, private_locator,
              first_observed_at)
           VALUES (:account, :bridge, :source, 'mail', 'Synthetic Account',
                   'account.synthetic', :at)""",
        """INSERT INTO knowledge.native_source_buckets
             (bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at)
           VALUES (:bucket, :account, 'mail', 'Synthetic Inbox', 'bucket.synthetic',
                   true, :at)""",
        """INSERT INTO knowledge.audit_events
             (audit_id, correlation_id, principal_id, capability, purpose, outcome,
              policy_version, scope_source_id_count, recorded_at)
           VALUES (:audit, 'corr_0000000000000001', 'prn_0000000000000001',
                   'native_sources.sync', 'content_extraction', 'allowed', 'policy-v1', 1, :at)""",
        """INSERT INTO knowledge.native_configuration_revisions
             (configuration_id, revision, bridge_id, timezone_name, start_date, start_at,
              cutoff_at, calendar_horizon_at, selection_sha256, created_at)
           VALUES (:configuration, 1, :bridge, :timezone_name, :start_date, :start_at,
                   :cutoff_at, :calendar_horizon_at, :selection_sha256, :at)""",
        """INSERT INTO knowledge.native_configuration_buckets
             (configuration_id, revision, bucket_id)
           VALUES (:configuration, 1, :bucket)""",
    )
    values = {
        "source": SOURCE,
        "bridge": BRIDGE,
        "protocol": NATIVE_SOURCE_PROTOCOL_V1,
        "account": ACCOUNT,
        "bucket": BUCKET,
        "audit": AUDIT,
        "configuration": CONFIGURATION,
        "timezone_name": configuration.timezone_name,
        "start_date": configuration.start_date,
        "start_at": configuration.start_at,
        "cutoff_at": configuration.cutoff_at,
        "calendar_horizon_at": configuration.calendar_horizon_at,
        "selection_sha256": configuration.selection_sha256,
        "at": WHEN,
    }
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), values)


def _binding() -> NativeBucketBindingRecord:
    return NativeBucketBindingRecord(
        BUCKET,
        ACCOUNT,
        SOURCE,
        BRIDGE,
        NativeSourceKind.MAIL,
        "Synthetic Account",
        "Synthetic Inbox",
        "account.synthetic",
        "bucket.synthetic",
        True,
    )


_AUTHORITY_REQUESTS = count(1)


def _authority(
    store: SqlNativeSourceControlStore, *, request_id: str | None = None
) -> NativeAdmissionAuthority:
    snapshot = store.latest_configuration(CONFIGURATION)
    assert snapshot is not None
    return store.issue_sync_authority(
        snapshot.configuration,
        _binding(),
        audit_id=AUDIT,
        request_id=request_id or f"read.synthetic.{next(_AUTHORITY_REQUESTS)}",
        issued_at=WHEN,
        expires_at=WHEN + timedelta(minutes=5),
    )


def _envelope(
    authority: NativeAdmissionAuthority, *, next_cursor: str | None = None
) -> NativeAdmissionEnvelope:
    wire: dict[str, Any] = {
        "metadata": {
            "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
            "envelopeID": authority.envelope_id,
            "hostInstanceID": BRIDGE,
            "emittedAtUnixMilliseconds": 1_775_563_200_000,
        },
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.synthetic",
        "bucketID": "bucket.synthetic",
        "records": [
            {
                "id": "message.synthetic",
                "bucketID": "bucket.synthetic",
                "kind": "mail",
                "sourceRevision": "revision-1",
                "sourceModifiedUnixMilliseconds": 1_775_563_200_000,
                "payload": [115, 121, 110, 116, 104, 101, 116, 105, 99],
            }
        ],
        "nextCursor": next_cursor,
    }
    return NativeAdmissionEnvelope.model_validate(wire)


@pytest.mark.database
def test_authority_issuance_reuses_one_request_for_spool_recovery(c_engine: Engine) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    first = _authority(store, request_id="read.recoverable")
    replay = _authority(store, request_id="read.recoverable")

    assert replay == first


@pytest.mark.database
def test_guessed_native_ids_do_not_cross_principal_or_mutate(c_engine: Engine) -> None:
    _seed(c_engine)
    mine = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(mine)
    envelope = _envelope(authority)
    ((version_id, created),) = mine.admit_evidence_durably(envelope, authority, at=WHEN)
    assert created is True

    other = SqlNativeSourceControlStore(c_engine, OTHER_CONTEXT)
    assert other.bridge_protocol(BRIDGE) is None
    assert other.bucket_bindings((BUCKET,)) == ()
    assert other.latest_configuration(CONFIGURATION) is None
    assert other.authority_for_envelope(authority.envelope_id) is None
    with c_engine.connect() as connection:
        repository = SqlNativeSourceRepository(connection, OTHER_CONTEXT)
        with pytest.raises(LookupError):
            repository.resolve_bucket_locator(BUCKET)
    with pytest.raises(NativeAdmissionAuthorityError):
        other.admit_evidence_durably(envelope, authority, at=WHEN)

    with c_engine.connect() as connection:
        assert (
            connection.scalar(
                select(func.count(source_version_evidence.c.evidence_id)).where(
                    source_version_evidence.c.version_id == version_id
                )
            )
            == 1
        )


class _PagedSyntheticHost:
    def acknowledge(self, envelope_id: str) -> None:
        del envelope_id

    def pending(self, selection: NativeBucketSelection) -> dict[str, Any] | None:
        del selection
        return None

    def quarantine(self, envelope_id: str) -> None:
        del envelope_id

    def negotiate(self, supported_versions: tuple[str, ...]) -> str:
        assert supported_versions == (NATIVE_SOURCE_PROTOCOL_V1,)
        return NATIVE_SOURCE_PROTOCOL_V1

    def adapter_identity(self, kind: NativeSourceKind) -> str:
        return f"synthetic-{kind.value}-v1"

    def preflight(
        self,
        selections: tuple[NativeBucketSelection, ...],
        *,
        bridge_id: str,
        request_id: str,
        at: datetime,
    ) -> dict[str, Any]:
        del at
        return {
            "metadata": {
                "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
                "envelopeID": f"preflight.{request_id}",
                "hostInstanceID": bridge_id,
                "emittedAtUnixMilliseconds": 1_775_563_200_000,
            },
            "requestID": request_id,
            "results": [
                {
                    "selection": selection.model_dump(mode="json", by_alias=True),
                    "state": "reachable",
                    "failure": None,
                }
                for selection in selections
            ],
        }

    def read(
        self,
        selection: NativeBucketSelection,
        *,
        time_range: tuple[datetime, datetime] | None,
        cursor: str | None,
        limit: int,
        bridge_id: str,
        envelope_id: str,
        request_id: str,
        at: datetime,
    ) -> dict[str, Any]:
        del time_range, at
        assert limit == 100
        selected = selection.model_dump(mode="json", by_alias=True)
        ordinal = "1" if cursor is None else "2"
        return {
            "metadata": {
                "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
                "envelopeID": envelope_id,
                "hostInstanceID": bridge_id,
                "emittedAtUnixMilliseconds": 1_775_563_200_000,
            },
            "requestID": request_id,
            "kind": selected["kind"],
            "accountID": selected["accountID"],
            "bucketID": selected["bucketID"],
            "records": [
                {
                    "id": f"message.baseline.{ordinal}",
                    "bucketID": selected["bucketID"],
                    "kind": selected["kind"],
                    "sourceRevision": f"revision-{ordinal}",
                    "sourceModifiedUnixMilliseconds": 1_775_563_200_000,
                    "payload": [112, 97, 103, 101, int(ordinal) + 48],
                }
            ],
            "nextCursor": "page-2" if cursor is None else None,
        }


class _CursorCycleHost(_PagedSyntheticHost):
    def __init__(
        self,
        next_by_cursor: dict[str | None, str | None],
        *,
        fail_cursor_once: str | None = None,
    ) -> None:
        self._next_by_cursor = next_by_cursor
        self._fail_cursor_once = fail_cursor_once

    def read(
        self,
        selection: NativeBucketSelection,
        *,
        time_range: tuple[datetime, datetime] | None,
        cursor: str | None,
        limit: int,
        bridge_id: str,
        envelope_id: str,
        request_id: str,
        at: datetime,
    ) -> dict[str, Any]:
        if self._fail_cursor_once is not None and cursor == self._fail_cursor_once:
            self._fail_cursor_once = None
            raise RuntimeError("synthetic restart boundary")
        wire = super().read(
            selection,
            time_range=time_range,
            cursor=cursor,
            limit=limit,
            bridge_id=bridge_id,
            envelope_id=envelope_id,
            request_id=request_id,
            at=at,
        )
        wire["nextCursor"] = self._next_by_cursor[cursor]
        return wire


class _NoProposals:
    def open_review_proposals(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
        del version_ids
        return ()


@pytest.mark.database
def test_wp12c_migration_extends_vocab_and_adds_only_three_bounded_tables(
    c_engine: Engine,
) -> None:
    names = set(inspect(c_engine).get_table_names(schema="knowledge"))
    assert {
        "native_admission_authorities",
        "native_preflight_observations",
        "native_source_review_routes",
    } <= names
    with c_engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO knowledge.audit_events
                     (audit_id, correlation_id, principal_id, capability, purpose, outcome,
                      policy_version, scope_source_id_count, recorded_at)
                   VALUES ('audit_0000000000000002', 'corr_0000000000000002',
                           'prn_0000000000000002', 'native_sources.disable',
                           'bounded_enrollment', 'allowed', 'policy-v1', 1, :at)"""
            ),
            {"at": WHEN},
        )
        savepoint = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """INSERT INTO knowledge.audit_events
                         (audit_id, correlation_id, principal_id, capability, purpose, outcome,
                          policy_version, scope_source_id_count, recorded_at)
                       VALUES ('audit_0000000000000003', 'corr_0000000000000003',
                               'prn_0000000000000003', 'native_sources.delete',
                               'bounded_enrollment', 'allowed', 'policy-v1', 1, :at)"""
                ),
                {"at": WHEN},
            )
        savepoint.rollback()


@pytest.mark.database
def test_current_metadata_capability_vocabulary_matches_alembic_head(c_engine: Engine) -> None:
    expected = frozenset(member.value for member in Capability) | frozenset(
        member.value for member in NativeSourceCapability
    )
    metadata_constraint = next(
        constraint
        for constraint in audit_events.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == "capability_is_known"
    )
    metadata_values = _capability_constraint_values(str(metadata_constraint.sqltext))
    with c_engine.connect() as connection:
        migrated_expression = connection.execute(
            text(
                """SELECT pg_get_constraintdef(con.oid)
                     FROM pg_constraint con
                     JOIN pg_class rel ON rel.oid = con.conrelid
                     JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                     WHERE nsp.nspname = 'knowledge'
                       AND rel.relname = 'audit_events'
                       AND con.conname = 'capability_is_known'"""
            )
        ).scalar_one()
    migrated_values = _capability_constraint_values(migrated_expression)

    assert metadata_values == migrated_values == expected
    assert {member.value for member in Capability} <= metadata_values
    assert {member.value for member in NativeSourceCapability} <= metadata_values
    assert "native_sources.delete" not in metadata_values


@pytest.mark.database
def test_wp12c_revision_round_trips_to_its_exact_prior_head(c_engine: Engine) -> None:
    expected = {
        "native_admission_authorities",
        "native_preflight_observations",
        "native_source_review_routes",
    }
    command.downgrade(_config(), "8c4d1e7a2b90")
    assert expected.isdisjoint(inspect(c_engine).get_table_names(schema="knowledge"))
    command.upgrade(_config(), "9d5e2f7b4c61")
    assert expected <= set(inspect(c_engine).get_table_names(schema="knowledge"))


@pytest.mark.database
def test_source_visibility_exact_binding_and_allowed_sync_audit_are_database_backed(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    assert store.bridge_protocol(BRIDGE) == NATIVE_SOURCE_PROTOCOL_V1
    assert store.bucket_bindings((BUCKET,)) == (_binding(),)
    assert store.visible_locator_pairs(BRIDGE, frozenset({SOURCE})) == frozenset(
        {
            ("account.synthetic", "bucket.synthetic"),
            ("account.synthetic", "bucket.archive"),
        }
    )
    authority = _authority(store)
    assert authority.audit_id == AUDIT
    assert authority.bucket_id == BUCKET
    snapshot = store.latest_configuration(CONFIGURATION)
    assert snapshot is not None
    with pytest.raises(NativeAdmissionAuthorityError):
        store.issue_sync_authority(
            snapshot.configuration,
            _binding(),
            audit_id="audit_9999999999999999",
            request_id="read.fabricated",
            issued_at=WHEN,
            expires_at=WHEN + timedelta(minutes=5),
        )
    snapshot = store.latest_configuration(CONFIGURATION)
    assert snapshot is not None
    assert snapshot.configuration.selection.bucket_ids == (BUCKET,)


@pytest.mark.database
def test_concurrent_replay_creates_one_immutable_version_and_evidence(c_engine: Engine) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(store)
    barrier = Barrier(2)

    def admit() -> tuple[tuple[str, bool], ...]:
        barrier.wait()
        return SqlNativeSourceControlStore(c_engine, CONTEXT).admit_evidence_durably(
            _envelope(authority), authority, at=WHEN
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = tuple(pool.map(lambda _: admit(), range(2)))
    assert sorted(result[0][1] for result in outcomes) == [False, True]
    assert len({result[0][0] for result in outcomes}) == 1

    with c_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(source_objects)) == 1
        assert connection.scalar(select(func.count()).select_from(source_object_versions)) == 1
        assert connection.scalar(select(func.count()).select_from(source_version_evidence)) == 1
        assert connection.scalar(select(func.count()).select_from(source_observations)) == 1

    status = SqlNativeSourceControlStore(c_engine, CONTEXT).progress(CONFIGURATION)
    assert len(status) == 1
    assert status[0].coverage is NativeCoverageState.EVIDENCE_PRESENT
    assert status[0].admitted_count == 1
    assert "synthetic" not in status[0].to_canonical_json()


@pytest.mark.database
def test_configuration_revision_sequence_is_first_one_and_serialized(c_engine: Engine) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    first = store.latest_configuration(CONFIGURATION)
    assert first is not None
    with pytest.raises(NativePersistenceConflictError):
        store.append_configuration(
            replace(
                first.configuration,
                configuration_id="ncfg_0000000000000002",
                revision=7,
            ),
            expected_prior_revision=0,
        )
    current = store.latest_configuration(CONFIGURATION)
    assert current is not None
    skipped = replace(current.configuration, revision=3, created_at=WHEN + timedelta(seconds=1))
    with pytest.raises(NativePersistenceConflictError):
        store.append_configuration(skipped, expected_prior_revision=1)

    second = replace(current.configuration, revision=2, created_at=WHEN + timedelta(seconds=1))
    barrier = Barrier(2)

    def append_second() -> bool:
        barrier.wait()
        store.append_configuration(second, expected_prior_revision=1)
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(append_second) for _ in range(2)]
        outcomes = []
        for future in futures:
            try:
                outcomes.append(future.result())
            except NativePersistenceConflictError:
                outcomes.append(False)
    assert sorted(outcomes) == [False, True]


@pytest.mark.database
def test_scope_removal_serializes_before_admission_and_makes_grant_stale(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(store)
    current = store.latest_configuration(CONFIGURATION)
    assert current is not None
    removed = replace(
        current.configuration,
        revision=2,
        selection=ExactBucketSelection((BUCKET_2,)),
        created_at=WHEN + timedelta(seconds=1),
    )

    def admit_after_lock() -> tuple[tuple[str, bool], ...]:
        reachable = NativeBucketProgress(
            bucket_id=BUCKET,
            state=NativePreflightState.REACHABLE.value,
            coverage=NativeCoverageState.NOT_MEASURED,
            admitted_count=0,
            failed_count=0,
            pending_count=0,
        )
        return SqlNativeSourceControlStore(c_engine, CONTEXT).admit_evidence_durably(
            _envelope(authority),
            authority,
            (reachable,),
            at=WHEN + timedelta(seconds=1),
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with c_engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:principal_id || ':' || :configuration_id, 0))"
                ),
                {
                    "principal_id": CONTEXT.capture_principal_id,
                    "configuration_id": CONFIGURATION,
                },
            )
            future = pool.submit(admit_after_lock)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.1)
            SqlNativeSourceRepository(connection, CONTEXT).append_configuration(removed)
        with pytest.raises(NativeAdmissionAuthorityError):
            future.result(timeout=5)

    with c_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(source_version_evidence)) == 0
        assert (
            connection.scalar(select(func.count()).select_from(native_preflight_observations)) == 0
        )
        assert (
            connection.scalar(
                select(native_admission_authorities.c.admission_sha256).where(
                    native_admission_authorities.c.authority_id == authority.authority_id
                )
            )
            is None
        )


@pytest.mark.database
def test_authority_fabrication_expiry_and_non_exact_replay_fail_closed(c_engine: Engine) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(store)
    envelope = _envelope(authority)
    for rejected, at in (
        (replace(authority, authority_id="nauth_9999999999999999"), WHEN),
        (replace(authority, audit_id="audit_9999999999999999"), WHEN),
        (authority, authority.expires_at + timedelta(microseconds=1)),
    ):
        with pytest.raises(NativeAdmissionAuthorityError):
            store.prevalidate_authority(envelope, rejected, at=at)
    with c_engine.connect() as connection:
        observations = connection.scalar(
            select(func.count()).select_from(native_preflight_observations)
        )
        assert observations == 0
    store.admit_evidence_durably(envelope, authority, at=WHEN)
    store.prevalidate_authority(envelope, authority, at=WHEN)
    changed = envelope.model_copy(
        update={
            "records": (envelope.records[0].model_copy(update={"source_revision": "revision-2"}),)
        }
    )
    with pytest.raises(NativeAdmissionAuthorityError):
        store.prevalidate_authority(changed, authority, at=WHEN)
    with c_engine.connect() as connection:
        observations = connection.scalar(
            select(func.count()).select_from(native_preflight_observations)
        )
        assert observations == 0


@pytest.mark.database
def test_durable_status_distinguishes_permission_denial_and_unavailability(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    denied = NativeBucketProgress(
        bucket_id=BUCKET,
        state=NativePreflightState.PERMISSION_DENIED.value,
        coverage=NativeCoverageState.PERMISSION_DENIED,
        admitted_count=0,
        failed_count=1,
        pending_count=0,
        failure=NativeProviderFailure.PERMISSION_DENIED,
    )
    store.record_preflight(CONFIGURATION, 1, (denied,), observed_at=WHEN)
    status = store.progress(CONFIGURATION)[0]
    assert (status.coverage, status.failure) == (
        NativeCoverageState.PERMISSION_DENIED,
        NativeProviderFailure.PERMISSION_DENIED,
    )
    unavailable = denied.model_copy(
        update={
            "state": NativePreflightState.UNAVAILABLE.value,
            "coverage": NativeCoverageState.UNAVAILABLE,
            "failure": NativeProviderFailure.TRANSIENT_UNAVAILABLE,
        }
    )
    store.record_preflight(
        CONFIGURATION,
        1,
        (unavailable,),
        observed_at=WHEN + timedelta(seconds=1),
    )
    status = store.progress(CONFIGURATION)[0]
    assert (status.coverage, status.failure) == (
        NativeCoverageState.UNAVAILABLE,
        NativeProviderFailure.TRANSIENT_UNAVAILABLE,
    )
    assert "synthetic" not in status.to_canonical_json()


@pytest.mark.database
def test_operational_denial_is_recorded_only_while_authority_scope_is_current(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(store)
    envelope = _envelope(authority)
    denied = NativeBucketProgress(
        bucket_id=BUCKET,
        state=NativePreflightState.PERMISSION_DENIED.value,
        coverage=NativeCoverageState.PERMISSION_DENIED,
        admitted_count=0,
        failed_count=1,
        pending_count=0,
        failure=NativeProviderFailure.PERMISSION_DENIED,
    )
    store.record_admission_preflight_durably(envelope, authority, (denied,), observed_at=WHEN)
    current = store.latest_configuration(CONFIGURATION)
    assert current is not None
    store.append_configuration(
        replace(
            current.configuration,
            revision=2,
            selection=ExactBucketSelection((BUCKET_2,)),
            created_at=WHEN + timedelta(seconds=1),
        ),
        expected_prior_revision=1,
    )
    with pytest.raises(NativeAdmissionAuthorityError):
        store.record_admission_preflight_durably(
            envelope,
            authority,
            (denied,),
            observed_at=WHEN + timedelta(seconds=1),
        )
    with c_engine.connect() as connection:
        assert (
            connection.scalar(select(func.count()).select_from(native_preflight_observations)) == 1
        )
        assert (
            connection.scalar(
                select(native_admission_authorities.c.admission_sha256).where(
                    native_admission_authorities.c.authority_id == authority.authority_id
                )
            )
            is None
        )


@pytest.mark.database
def test_native_enrichment_routes_exact_source_version_to_existing_governed_review(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(store)
    version_id = store.admit_evidence_durably(_envelope(authority), authority, at=WHEN)[0][0]
    ids = {
        "capture": "cap_0000000000000001",
        "capture_version": "capver_0000000000000001",
        "span": "span_0000000000000001",
        "proposal": "prop_0000000000000001",
        "principal": "prn_0000000000000001",
        "correlation": "corr_0000000000000001",
        "audit": AUDIT,
        "digest": sha256(b"x").hexdigest(),
    }
    with c_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.captures (capture_id, owner_principal_id) "
                "VALUES (:capture, :principal)"
            ),
            ids,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_versions "
                "(version_id, capture_id, version_number, content, content_sha256, "
                "owner_principal_id, classification, processing_policy, idempotency_key, "
                "correlation_id, audit_id, server_received_at, accepted_at, recorded_at) "
                "VALUES (:capture_version, :capture, 1, 'x', :digest, :principal, "
                "'synthetic_test', 'local_only', :capture_version, :correlation, :audit, "
                ":at, :at, :at)"
            ),
            {**ids, "at": WHEN},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_spans "
                "(span_id, version_id, start_offset, end_offset, offset_basis, line_start, "
                "column_start, line_end, column_end, quoted_text_sha256, span_role) "
                "VALUES (:span, :capture_version, 0, 1, 'unicode_code_point_v1', "
                "1, 1, 1, 2, :digest, 'direct')"
            ),
            ids,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_proposals "
                "(proposal_id, version_id, proposal_type, state, risk_class, method, "
                "method_version, schema_version) VALUES (:proposal, :capture_version, "
                "'commitment', 'proposed', 'high', 'deterministic_rule', 'v1', 'v1')"
            ),
            ids,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.capture_proposal_spans (proposal_id, span_id) "
                "VALUES (:proposal, :span)"
            ),
            ids,
        )
    router = SqlNativeReviewProposalRouter(
        c_engine,
        lambda candidate_version: (ids["proposal"],) if candidate_version == version_id else (),
        CONTEXT,
    )
    assert router.open_review_proposals((version_id,)) == (ids["proposal"],)
    assert router.open_review_proposals((version_id,)) == (ids["proposal"],)
    with c_engine.connect() as connection:
        route = connection.execute(select(native_source_review_routes)).one()
        assert (route.source_version_id, route.proposal_id) == (version_id, ids["proposal"])
        assert connection.scalar(select(func.count()).select_from(capture_review_cases)) == 1
    assert not hasattr(router, "promote")
    assert not hasattr(router, "decide")


@pytest.mark.database
def test_wp12e_cutoff_run_job_and_checkpoint_are_exact_durable_and_fail_closed(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    baseline = SqlNativeBaselineStore(c_engine, CONTEXT)
    cutoff = WHEN + timedelta(days=1)
    frozen = baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="baseline-frozen-1",
        proposed_cutoff_at=cutoff,
        adapter_identity="a" * 64,
    )
    replay = baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="baseline-frozen-1",
        proposed_cutoff_at=cutoff + timedelta(days=30),
        adapter_identity="a" * 64,
    )
    assert replay == frozen
    with c_engine.connect() as connection:
        run = connection.execute(
            select(
                native_sync_runs.c.bridge_id,
                native_sync_runs.c.adapter_identity,
                native_sync_runs.c.start_at,
                native_sync_runs.c.cutoff_at,
            ).where(native_sync_runs.c.run_id == frozen.run_id)
        ).one()
        job_row = connection.execute(
            select(native_sync_jobs).where(native_sync_jobs.c.run_id == frozen.run_id)
        ).one()
    assert run.bridge_id == BRIDGE
    assert run.adapter_identity == "a" * 64
    assert run.start_at == datetime(2026, 8, 1, 4, tzinfo=UTC)
    assert run.cutoff_at == cutoff
    assert job_row.range_start == run.start_at
    assert job_row.range_end == cutoff
    assert job_row.read_mode == "bounded_time"

    with c_engine.begin() as connection:
        unbound_job = connection.begin_nested()
        with pytest.raises(IntegrityError, match="requires an exact frozen run"):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_sync_jobs
                         (principal_id, job_id, configuration_id, configuration_revision, bucket_id,
                          range_start, range_end, read_mode, state, idempotency_key,
                          created_at, updated_at)
                       VALUES (:principal_id, :job_id, :configuration_id, 1, :bucket_id,
                               :range_start, :range_end, 'bounded_time', 'queued', 'unbound-job',
                               :recorded_at, :recorded_at)"""
                ),
                {
                    "job_id": "njob_0000000000000099",
                    "configuration_id": CONFIGURATION,
                    "bucket_id": BUCKET,
                    "range_start": run.start_at,
                    "range_end": cutoff,
                    "recorded_at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
            )
        unbound_job.rollback()
        unbound_checkpoint = connection.begin_nested()
        with pytest.raises(IntegrityError, match="requires an admitted page binding"):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_checkpoints
                         (principal_id, checkpoint_id, bucket_id, sequence, cursor_private,
                          cursor_digest, terminal, item_count, recorded_at)
                       VALUES (:principal_id, :checkpoint_id, :bucket_id, 1, 'unbound-cursor',
                               :cursor_digest, false, 0, :recorded_at)"""
                ),
                {
                    "checkpoint_id": "ncp_0000000000000099",
                    "bucket_id": BUCKET,
                    "cursor_digest": sha256(b"unbound-cursor").hexdigest(),
                    "recorded_at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
            )
        unbound_checkpoint.rollback()

    job = baseline.claim(frozen.run_id, owner="synthetic-worker", lease_for=timedelta(minutes=5))
    assert job is not None
    control = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(control)
    page = NativeReadPageReceipt(
        admission=NativeAdmissionReceipt(
            request_id=authority.request_id,
            bucket_id=BUCKET,
            admitted_count=1,
            duplicate_count=0,
            evidence_digest="b" * 64,
            enrichment_proposal_count=0,
            enrichment_failed=False,
        ),
        authority_id=authority.authority_id,
        next_cursor="page-2",
    )
    with pytest.raises(IntegrityError, match="requires its exact admitted page"):
        baseline.checkpoint_admitted_page(job, page, recorded_at=WHEN)
    assert baseline.resume_point(job.job_id).page_count == 0

    envelope = _envelope(authority, next_cursor="page-2")
    outcomes = control.admit_evidence_durably(
        envelope,
        authority,
        at=WHEN,
        checkpoint_job_id=job.job_id,
        checkpoint_run_id=job.run_id,
    )
    assert len(outcomes) == 1
    with c_engine.connect() as connection:
        binding = connection.execute(
            select(
                native_admission_authorities.c.checkpoint_job_id,
                native_admission_authorities.c.checkpoint_run_id,
                native_admission_authorities.c.checkpoint_cursor_private,
                native_admission_authorities.c.checkpoint_cursor_digest,
                native_admission_authorities.c.checkpoint_terminal,
                native_admission_authorities.c.checkpoint_item_count,
            ).where(native_admission_authorities.c.authority_id == authority.authority_id)
        ).one()
    assert binding == (
        job.job_id,
        job.run_id,
        "page-2",
        sha256(b"page-2").hexdigest(),
        False,
        1,
    )

    alternate = baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="baseline-frozen-alternate-run",
        proposed_cutoff_at=cutoff,
        adapter_identity="a" * 64,
    )
    with c_engine.connect() as connection:
        alternate_job = connection.scalar(
            select(native_sync_jobs.c.job_id).where(native_sync_jobs.c.run_id == alternate.run_id)
        )
    revised = NativeConfigurationRevision(
        CONFIGURATION,
        2,
        BRIDGE,
        "America/New_York",
        date(2026, 8, 1),
        cutoff,
        ExactBucketSelection((BUCKET,)),
        WHEN + timedelta(minutes=1),
    )
    control.append_configuration(revised, expected_prior_revision=1)
    revised_run = baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="baseline-frozen-revised-run",
        proposed_cutoff_at=cutoff + timedelta(minutes=1),
        adapter_identity="a" * 64,
    )
    with c_engine.connect() as connection:
        revised_job = connection.scalar(
            select(native_sync_jobs.c.job_id).where(native_sync_jobs.c.run_id == revised_run.run_id)
        )

    checkpoint_insert = text(
        """INSERT INTO knowledge.native_checkpoints
             (principal_id, checkpoint_id, bucket_id, job_id, admission_authority_id, sequence,
              previous_checkpoint_id, cursor_private, cursor_digest, terminal,
              item_count, recorded_at)
           VALUES (:principal_id, :checkpoint_id, :bucket_id, :job_id, :authority_id, 1, NULL,
                   :cursor, :digest, :terminal, :item_count, :recorded_at)"""
    )
    plants = (
        ("wrong-run", str(alternate_job), "page-2", sha256(b"page-2").hexdigest(), False, 1),
        ("wrong-revision", str(revised_job), "page-2", sha256(b"page-2").hexdigest(), False, 1),
        ("forged-cursor", job.job_id, "forged", sha256(b"forged").hexdigest(), False, 1),
        ("forged-digest", job.job_id, "page-2", "f" * 64, False, 1),
        (
            "forged-terminal",
            job.job_id,
            "__my_pa_native_baseline_complete__",
            sha256(b"__my_pa_native_baseline_complete__").hexdigest(),
            True,
            1,
        ),
        ("forged-count", job.job_id, "page-2", sha256(b"page-2").hexdigest(), False, 2),
    )
    with c_engine.begin() as connection:
        for ordinal, (_name, planted_job, cursor, digest, terminal, count) in enumerate(
            plants, start=1
        ):
            savepoint = connection.begin_nested()
            with pytest.raises(IntegrityError, match="exact admitted page"):
                connection.execute(
                    checkpoint_insert,
                    {
                        "checkpoint_id": f"ncp_{ordinal + 100:016d}",
                        "bucket_id": BUCKET,
                        "job_id": planted_job,
                        "authority_id": authority.authority_id,
                        "cursor": cursor,
                        "digest": digest,
                        "terminal": terminal,
                        "item_count": count,
                        "recorded_at": WHEN,
                        "principal_id": CONTEXT.capture_principal_id,
                    },
                )
            savepoint.rollback()
        immutable = connection.begin_nested()
        with pytest.raises(IntegrityError, match="immutable"):
            connection.execute(
                text(
                    "UPDATE knowledge.native_admission_authorities "
                    "SET checkpoint_item_count = 2 WHERE authority_id = :authority_id"
                ),
                {"authority_id": authority.authority_id},
            )
        immutable.rollback()

    baseline.checkpoint_admitted_page(job, page, recorded_at=WHEN)
    assert baseline.resume_point(job.job_id) == BaselineResumePoint(
        cursor="page-2", terminal=False, page_count=1
    )
    with c_engine.connect() as connection:
        checkpoint = connection.execute(
            select(
                native_checkpoints.c.job_id,
                native_checkpoints.c.admission_authority_id,
                native_checkpoints.c.item_count,
            )
        ).one()
    assert checkpoint == (job.job_id, authority.authority_id, 1)


@pytest.mark.database
def test_wp12e_database_rejects_wrong_insert_and_update_ranges_for_every_kind(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    ids = {
        "calendar_source": "src_0000000000000010",
        "calendar_account": "nacct_0000000000000010",
        "calendar_bucket": "nbkt_0000000000000010",
        "contacts_source": "src_0000000000000011",
        "contacts_account": "nacct_0000000000000011",
        "contacts_bucket": "nbkt_0000000000000011",
    }
    with c_engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO knowledge.sources
                     (source_id, provider_kind, label, classification, native_root)
                   VALUES (:calendar_source, 'apple_calendar', 'Synthetic Calendar',
                           'synthetic_test', 'calendar-root'),
                          (:contacts_source, 'apple_contacts', 'Synthetic Contacts',
                           'synthetic_test', 'contacts-root')"""
            ),
            ids,
        )
        connection.execute(
            text(
                """INSERT INTO knowledge.native_source_accounts
                     (principal_id, account_id, bridge_id, source_id, source_kind, label,
                      private_locator, first_observed_at)
                   VALUES (:principal, :calendar_account, :bridge, :calendar_source, 'calendar',
                           'Synthetic Calendar', 'calendar.account', :at),
                          (:principal, :contacts_account, :bridge, :contacts_source, 'contacts',
                           'Synthetic Contacts', 'contacts.account', :at)"""
            ),
            {**ids, "bridge": BRIDGE, "principal": CONTEXT.capture_principal_id, "at": WHEN},
        )
        connection.execute(
            text(
                """INSERT INTO knowledge.native_source_buckets
                     (principal_id, bucket_id, account_id, source_kind, label, private_locator,
                      selectable, first_observed_at)
                   VALUES (:principal, :calendar_bucket, :calendar_account, 'calendar',
                           'Synthetic Calendar', 'calendar.bucket', true, :at),
                          (:principal, :contacts_bucket, :contacts_account, 'contacts',
                           'Synthetic Contacts', 'contacts.bucket', true, :at)"""
            ),
            {**ids, "principal": CONTEXT.capture_principal_id, "at": WHEN},
        )
    configuration_id = "ncfg_0000000000000010"
    SqlNativeSourceControlStore(c_engine, CONTEXT).append_configuration(
        NativeConfigurationRevision(
            configuration_id,
            1,
            BRIDGE,
            "America/New_York",
            date(2026, 8, 1),
            WHEN,
            ExactBucketSelection((BUCKET, ids["calendar_bucket"], ids["contacts_bucket"])),
            WHEN,
        ),
        expected_prior_revision=0,
    )
    frozen = SqlNativeBaselineStore(c_engine, CONTEXT).prepare(
        configuration_id=configuration_id,
        idempotency_key="all-kind-range-guard",
        proposed_cutoff_at=WHEN + timedelta(days=1),
        adapter_identity="r" * 64,
    )
    with c_engine.connect() as connection:
        jobs = connection.execute(
            select(native_sync_jobs).where(native_sync_jobs.c.run_id == frozen.run_id)
        ).all()
    assert len(jobs) == 3

    insert_job = text(
        """INSERT INTO knowledge.native_sync_jobs
             (principal_id, job_id, configuration_id, configuration_revision, bucket_id,
              range_start, range_end, state, lease_owner, lease_expires_at,
              idempotency_key, created_at, updated_at, run_id, read_mode)
           VALUES (:principal_id, :job_id, :configuration_id, :configuration_revision, :bucket_id,
                   :range_start, :range_end, 'queued', NULL, NULL,
                   :idempotency_key, :created_at, :updated_at, :run_id, :read_mode)"""
    )
    ordinal = 200
    with c_engine.begin() as connection:
        for row in jobs:
            kind = connection.scalar(
                text(
                    "SELECT source_kind FROM knowledge.native_source_buckets "
                    "WHERE bucket_id = :bucket_id"
                ),
                {"bucket_id": row.bucket_id},
            )
            wrong_start = (
                row.range_start - timedelta(seconds=1)
                if kind == "contacts"
                else row.range_start + timedelta(seconds=1)
            )
            wrong_end = (
                row.range_end + timedelta(seconds=1)
                if kind == "contacts"
                else row.range_end - timedelta(seconds=1)
            )
            for endpoint, changed_start, changed_end in (
                ("start", wrong_start, row.range_end),
                ("end", row.range_start, wrong_end),
            ):
                ordinal += 1
                insert_plant = connection.begin_nested()
                with pytest.raises(IntegrityError, match="frozen"):
                    connection.execute(
                        insert_job,
                        {
                            **row._mapping,
                            "job_id": f"njob_{ordinal:016d}",
                            "range_start": changed_start,
                            "range_end": changed_end,
                            "idempotency_key": f"raw-{kind}-{endpoint}",
                        },
                    )
                insert_plant.rollback()

                update_plant = connection.begin_nested()
                with pytest.raises(IntegrityError, match="frozen"):
                    update_statement = (
                        text(
                            "UPDATE knowledge.native_sync_jobs SET range_start = :value "
                            "WHERE job_id = :job_id"
                        )
                        if endpoint == "start"
                        else text(
                            "UPDATE knowledge.native_sync_jobs SET range_end = :value "
                            "WHERE job_id = :job_id"
                        )
                    )
                    connection.execute(
                        update_statement,
                        {
                            "value": changed_start if endpoint == "start" else changed_end,
                            "job_id": row.job_id,
                        },
                    )
                update_plant.rollback()


@pytest.mark.database
def test_wp12e_page_and_record_budgets_fail_closed_before_another_checkpoint(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    baseline = SqlNativeBaselineStore(c_engine, CONTEXT)
    frozen = baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="bounded-total-work",
        proposed_cutoff_at=WHEN,
        adapter_identity="b" * 64,
    )
    job = baseline.claim(frozen.run_id, owner="bounded-worker", lease_for=timedelta(minutes=5))
    assert job is not None
    control = SqlNativeSourceControlStore(c_engine, CONTEXT)

    first_authority = _authority(control)
    first_outcomes = control.admit_evidence_durably(
        _envelope(first_authority, next_cursor="A"),
        first_authority,
        at=WHEN,
        checkpoint_job_id=job.job_id,
        checkpoint_run_id=job.run_id,
    )
    assert len(first_outcomes) == 1
    first_page = NativeReadPageReceipt(
        NativeAdmissionReceipt(
            first_authority.request_id,
            BUCKET,
            1,
            0,
            "a" * 64,
            0,
            False,
        ),
        first_authority.authority_id,
        "A",
    )
    baseline.checkpoint_admitted_page(job, first_page, recorded_at=WHEN)

    second_authority = _authority(control)
    second_outcomes = control.admit_evidence_durably(
        _envelope(second_authority, next_cursor="B"),
        second_authority,
        at=WHEN,
        checkpoint_job_id=job.job_id,
        checkpoint_run_id=job.run_id,
    )
    assert second_outcomes == ((first_outcomes[0][0], False),)
    second_page = NativeReadPageReceipt(
        NativeAdmissionReceipt(
            second_authority.request_id,
            BUCKET,
            0,
            1,
            "b" * 64,
            0,
            False,
        ),
        second_authority.authority_id,
        "B",
    )
    baseline._MAX_PAGES_PER_JOB = 1
    with pytest.raises(NativePersistenceConflictError, match="page bound"):
        baseline.checkpoint_admitted_page(job, second_page, recorded_at=WHEN)
    baseline._MAX_PAGES_PER_JOB = 10_000
    baseline._MAX_RECORDS_PER_JOB = 1
    with pytest.raises(NativePersistenceConflictError, match="record bound"):
        baseline.checkpoint_admitted_page(job, second_page, recorded_at=WHEN)
    assert baseline.resume_point(job.job_id).page_count == 1


@pytest.mark.database
def test_wp12e_earlier_start_queues_only_missing_delta_and_later_start_retains_evidence(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    control = SqlNativeSourceControlStore(c_engine, CONTEXT)
    authority = _authority(control)
    control.admit_evidence_durably(_envelope(authority), authority, at=WHEN)
    with c_engine.connect() as connection:
        evidence_before = connection.scalar(
            select(func.count()).select_from(source_version_evidence)
        )

    earlier = NativeConfigurationRevision(
        CONFIGURATION,
        2,
        BRIDGE,
        "America/New_York",
        date(2026, 7, 1),
        WHEN + timedelta(days=1),
        ExactBucketSelection((BUCKET,)),
        WHEN + timedelta(minutes=1),
    )
    control.append_configuration(earlier, expected_prior_revision=1)
    with c_engine.begin() as connection:
        wrong_kind = connection.begin_nested()
        with pytest.raises(IntegrityError, match="run kind contradicts"):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_sync_runs
                         (principal_id, run_id, configuration_id, configuration_revision,
                          run_kind, state,
                          start_at, cutoff_at, calendar_horizon_at, idempotency_key,
                          recorded_at, bridge_id, adapter_identity)
                       VALUES (:principal_id, 'nrun_0000000000000098', :configuration, 2,
                               'baseline', 'running', :start, :cutoff, :horizon, 'raw-wrong-kind',
                               :cutoff, :bridge, :adapter)"""
                ),
                {
                    "configuration": CONFIGURATION,
                    "start": datetime(2026, 7, 1, 4, tzinfo=UTC),
                    "cutoff": WHEN + timedelta(days=1),
                    "horizon": WHEN + timedelta(days=91),
                    "bridge": BRIDGE,
                    "adapter": "b" * 64,
                    "principal_id": CONTEXT.capture_principal_id,
                },
            )
        wrong_kind.rollback()
    baseline = SqlNativeBaselineStore(c_engine, CONTEXT)
    backfill = baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="earlier-delta",
        proposed_cutoff_at=WHEN + timedelta(days=1),
        adapter_identity="b" * 64,
    )
    with c_engine.connect() as connection:
        backfill_job = connection.execute(
            select(native_sync_jobs).where(native_sync_jobs.c.run_id == backfill.run_id)
        ).one()
    assert backfill_job.range_start == datetime(2026, 7, 1, 4, tzinfo=UTC)
    assert backfill_job.range_end == datetime(2026, 8, 1, 4, tzinfo=UTC) - timedelta(milliseconds=1)

    later = NativeConfigurationRevision(
        CONFIGURATION,
        3,
        BRIDGE,
        "America/New_York",
        date(2026, 8, 2),
        WHEN + timedelta(days=2),
        ExactBucketSelection((BUCKET,)),
        WHEN + timedelta(minutes=2),
    )
    control.append_configuration(later, expected_prior_revision=2)
    baseline.prepare(
        configuration_id=CONFIGURATION,
        idempotency_key="later-no-delete",
        proposed_cutoff_at=WHEN + timedelta(days=2),
        adapter_identity="b" * 64,
    )
    with c_engine.connect() as connection:
        evidence_after = connection.scalar(
            select(func.count()).select_from(source_version_evidence)
        )
        observations_after = connection.scalar(
            select(func.count()).select_from(source_observations)
        )
    assert evidence_after == evidence_before == 1
    assert observations_after == 1


@pytest.mark.database
def test_wp12e_contacts_use_current_inventory_and_admission_records_membership(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    ids = {
        "source": "src_0000000000000002",
        "account": "nacct_0000000000000002",
        "bucket": "nbkt_0000000000000003",
        "configuration": "ncfg_0000000000000002",
    }
    with c_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.sources "
                "(source_id, provider_kind, label, classification, native_root) "
                "VALUES (:source, 'apple_contacts', 'Synthetic Contacts', "
                "'synthetic_test', 'contacts-root')"
            ),
            ids,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.native_source_accounts "
                "(principal_id, account_id, bridge_id, source_id, source_kind, label, "
                "private_locator, first_observed_at) VALUES (:principal, :account, :bridge, "
                ":source, 'contacts', "
                "'Synthetic Contacts', 'contacts.account', :at)"
            ),
            {**ids, "bridge": BRIDGE, "principal": CONTEXT.capture_principal_id, "at": WHEN},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.native_source_buckets "
                "(principal_id, bucket_id, account_id, source_kind, label, private_locator, "
                "selectable, first_observed_at) VALUES (:principal, :bucket, :account, 'contacts', "
                "'Synthetic Group', 'contacts.group', true, :at)"
            ),
            {**ids, "principal": CONTEXT.capture_principal_id, "at": WHEN},
        )
    control = SqlNativeSourceControlStore(c_engine, CONTEXT)
    configuration = NativeConfigurationRevision(
        ids["configuration"],
        1,
        BRIDGE,
        "America/New_York",
        date(2026, 8, 1),
        WHEN,
        ExactBucketSelection((ids["bucket"],)),
        WHEN,
    )
    control.append_configuration(configuration, expected_prior_revision=0)
    baseline = SqlNativeBaselineStore(c_engine, CONTEXT)
    frozen = baseline.prepare(
        configuration_id=ids["configuration"],
        idempotency_key="contacts-inventory",
        proposed_cutoff_at=WHEN,
        adapter_identity="c" * 64,
    )
    with c_engine.connect() as connection:
        job = connection.execute(
            select(native_sync_jobs).where(native_sync_jobs.c.run_id == frozen.run_id)
        ).one()
    assert job.read_mode == "current_inventory"
    assert job.range_start == job.range_end == WHEN

    binding = NativeBucketBindingRecord(
        ids["bucket"],
        ids["account"],
        ids["source"],
        BRIDGE,
        NativeSourceKind.CONTACTS,
        "Synthetic Contacts",
        "Synthetic Group",
        "contacts.account",
        "contacts.group",
        True,
    )
    authority = control.issue_sync_authority(
        configuration,
        binding,
        audit_id=AUDIT,
        request_id="contacts.inventory",
        issued_at=WHEN,
        expires_at=WHEN + timedelta(minutes=5),
    )
    wire = {
        "metadata": {
            "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
            "envelopeID": authority.envelope_id,
            "hostInstanceID": BRIDGE,
            "emittedAtUnixMilliseconds": 1_775_563_200_000,
        },
        "requestID": authority.request_id,
        "kind": "contacts",
        "accountID": "contacts.account",
        "bucketID": "contacts.group",
        "records": [
            {
                "id": "contact.synthetic",
                "bucketID": "contacts.group",
                "kind": "contacts",
                "sourceRevision": "revision-1",
                "sourceModifiedUnixMilliseconds": None,
                "payload": [123, 125],
            }
        ],
        "nextCursor": None,
    }
    control.admit_evidence_durably(NativeAdmissionEnvelope.model_validate(wire), authority, at=WHEN)
    with c_engine.connect() as connection:
        membership_count = connection.scalar(
            text(
                "SELECT count(*) FROM knowledge.source_memberships WHERE parent_bucket_id = :bucket"
            ),
            {"bucket": ids["bucket"]},
        )
    assert membership_count == 1


@pytest.mark.database
def test_wp12e_revision_upgrades_populated_prior_head_and_round_trips(c_engine: Engine) -> None:
    command.downgrade(_config(), "9d5e2f7b4c61")
    _seed_legacy_wp12c(c_engine)
    with c_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.native_sync_runs "
                "(run_id, configuration_id, configuration_revision, run_kind, state, "
                "start_at, cutoff_at, calendar_horizon_at, idempotency_key, recorded_at) "
                "VALUES ('nrun_0000000000000099', :configuration, 1, 'baseline', "
                "'succeeded', :start, :cutoff, :horizon, 'legacy-run', :cutoff)"
            ),
            {
                "configuration": CONFIGURATION,
                "start": datetime(2026, 8, 1, 4, tzinfo=UTC),
                "cutoff": WHEN,
                "horizon": WHEN + timedelta(days=90),
            },
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.native_sync_jobs "
                "(job_id, configuration_id, configuration_revision, bucket_id, range_start, "
                "range_end, state, idempotency_key, created_at, updated_at) "
                "VALUES ('njob_0000000000000099', :configuration, 1, :bucket, :start, "
                ":cutoff, 'queued', 'legacy-job', :cutoff, :cutoff)"
            ),
            {
                "configuration": CONFIGURATION,
                "bucket": BUCKET,
                "start": datetime(2026, 8, 1, 4, tzinfo=UTC),
                "cutoff": WHEN,
            },
        )
    command.upgrade(_config(), "a7c3e8d1f642")
    with c_engine.connect() as connection:
        run = connection.execute(
            text(
                "SELECT bridge_id, adapter_identity FROM knowledge.native_sync_runs "
                "WHERE run_id = 'nrun_0000000000000099'"
            )
        ).one()
        job = connection.execute(
            text(
                "SELECT run_id, read_mode FROM knowledge.native_sync_jobs "
                "WHERE job_id = 'njob_0000000000000099'"
            )
        ).one()
    assert (run.bridge_id, run.adapter_identity) == (BRIDGE, "legacy-protocol-v1")
    assert (job.run_id, job.read_mode) == (None, "bounded_time")
    with c_engine.begin() as connection:
        connection.execute(
            text(
                """UPDATE knowledge.native_sync_jobs
                   SET state = 'running', lease_owner = 'legacy-worker',
                       lease_expires_at = :expiry, updated_at = :updated
                   WHERE job_id = 'njob_0000000000000099'"""
            ),
            {"expiry": WHEN + timedelta(minutes=5), "updated": WHEN},
        )

    command.downgrade(_config(), "9d5e2f7b4c61")
    columns = {
        str(column["name"])
        for column in inspect(c_engine).get_columns("native_sync_runs", schema="knowledge")
    }
    assert {"bridge_id", "adapter_identity"}.isdisjoint(columns)
    command.upgrade(_config(), "a7c3e8d1f642")


@pytest.mark.database
@pytest.mark.recovery
@pytest.mark.e2e
def test_wp12e_sql_executor_replays_after_admission_crash_and_resumes_all_pages(
    c_engine: Engine,
) -> None:
    _seed(c_engine)
    controller = NativeSourceController(
        store=SqlNativeSourceControlStore(c_engine, CONTEXT),
        host=_PagedSyntheticHost(),
        audit=SqlAlchemyAuditSink(c_engine),
        proposals=_NoProposals(),
    )
    baseline = SqlNativeBaselineStore(c_engine, CONTEXT)

    def contexts(
        request_id: str, at: datetime
    ) -> tuple[NativeRequestContext, NativeRequestContext]:
        return (
            NativeRequestContext(
                principal=Principal(
                    "prn_0000000000000001", PrincipalKind.OPERATOR, authenticated=True
                ),
                purpose=Purpose.CONTENT_EXTRACTION,
                correlation_id="corr_0000000000000100",
                request_id=request_id,
                authorized_source_ids=frozenset({SOURCE}),
                at=at,
            ),
            NativeRequestContext(
                principal=Principal(
                    "prn_0000000000000101",
                    PrincipalKind.SOURCE_PROVIDER_ADAPTER,
                    authenticated=True,
                ),
                purpose=Purpose.CONTENT_EXTRACTION,
                correlation_id="corr_0000000000000100",
                request_id=request_id,
                authorized_source_ids=frozenset(),
                at=at,
            ),
        )

    crash = True

    def after_admission(job: NativeBaselineJob, page: NativeReadPageReceipt) -> None:
        nonlocal crash
        del job, page
        if crash:
            crash = False
            raise RuntimeError("synthetic crash after durable admission")

    first = NativeBaselineExecutor(
        controller=controller,
        store=baseline,
        contexts=contexts,
        clock=lambda: WHEN,
        after_admission=after_admission,
    )
    with pytest.raises(RuntimeError, match="after durable admission"):
        first.execute(
            configuration_id=CONFIGURATION,
            idempotency_key="sql-e2e-baseline",
            owner="stable-worker",
        )
    with c_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(source_version_evidence)) == 1
        assert connection.scalar(select(func.count()).select_from(native_checkpoints)) == 0

    resumed = NativeBaselineExecutor(
        controller=controller,
        store=baseline,
        contexts=contexts,
        clock=lambda: WHEN + timedelta(days=1),
    ).execute(
        configuration_id=CONFIGURATION,
        idempotency_key="sql-e2e-baseline",
        owner="stable-worker",
    )
    assert resumed.cutoff_at == WHEN
    with c_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(source_version_evidence)) == 2
        assert connection.scalar(select(func.count()).select_from(source_observations)) == 2
        checkpoints = connection.execute(
            select(native_checkpoints.c.terminal, native_checkpoints.c.item_count).order_by(
                native_checkpoints.c.sequence
            )
        ).all()
        assert checkpoints == [(False, 1), (True, 1)]
        assert connection.scalar(select(func.count()).select_from(native_bucket_runs)) == 1
        state = connection.scalar(
            select(native_sync_jobs.c.state).where(native_sync_jobs.c.run_id == resumed.run_id)
        )
    assert state == "succeeded"


@pytest.mark.database
@pytest.mark.recovery
@pytest.mark.e2e
@pytest.mark.parametrize(
    ("next_by_cursor", "restart_cursor", "expected_pages"),
    (
        ({None: "A", "A": "A"}, None, 1),
        ({None: "A", "A": "B", "B": "A"}, "B", 2),
    ),
)
def test_wp12e_durable_cursor_history_rejects_immediate_and_multinode_cycles_after_restart(
    c_engine: Engine,
    next_by_cursor: dict[str | None, str | None],
    restart_cursor: str | None,
    expected_pages: int,
) -> None:
    _seed(c_engine)
    host = _CursorCycleHost(next_by_cursor, fail_cursor_once=restart_cursor)
    controller = NativeSourceController(
        store=SqlNativeSourceControlStore(c_engine, CONTEXT),
        host=host,
        audit=SqlAlchemyAuditSink(c_engine),
        proposals=_NoProposals(),
    )
    baseline = SqlNativeBaselineStore(c_engine, CONTEXT)

    def contexts(
        request_id: str, at: datetime
    ) -> tuple[NativeRequestContext, NativeRequestContext]:
        return (
            NativeRequestContext(
                principal=Principal(
                    "prn_0000000000000001", PrincipalKind.OPERATOR, authenticated=True
                ),
                purpose=Purpose.CONTENT_EXTRACTION,
                correlation_id="corr_0000000000000200",
                request_id=request_id,
                authorized_source_ids=frozenset({SOURCE}),
                at=at,
            ),
            NativeRequestContext(
                principal=Principal(
                    "prn_0000000000000201",
                    PrincipalKind.SOURCE_PROVIDER_ADAPTER,
                    authenticated=True,
                ),
                purpose=Purpose.CONTENT_EXTRACTION,
                correlation_id="corr_0000000000000200",
                request_id=request_id,
                authorized_source_ids=frozenset(),
                at=at,
            ),
        )

    executor = NativeBaselineExecutor(
        controller=controller,
        store=baseline,
        contexts=contexts,
        clock=lambda: WHEN,
    )
    if restart_cursor is not None:
        with pytest.raises(RuntimeError, match="restart boundary"):
            executor.execute(
                configuration_id=CONFIGURATION,
                idempotency_key="durable-cycle",
                owner="cycle-worker",
            )
    with pytest.raises(NativePersistenceConflictError, match="cursor repeated"):
        NativeBaselineExecutor(
            controller=controller,
            store=SqlNativeBaselineStore(c_engine, CONTEXT),
            contexts=contexts,
            clock=lambda: WHEN,
        ).execute(
            configuration_id=CONFIGURATION,
            idempotency_key="durable-cycle",
            owner="cycle-worker",
        )
    with c_engine.connect() as connection:
        job_id = connection.scalar(
            select(native_sync_jobs.c.job_id).where(
                native_sync_jobs.c.idempotency_key == f"durable-cycle:{BUCKET}"
            )
        )
        durable = connection.execute(
            select(native_checkpoints.c.cursor_private)
            .where(native_checkpoints.c.job_id == job_id)
            .order_by(native_checkpoints.c.sequence)
        ).scalars()
        assert tuple(durable) == tuple(next_by_cursor.values())[:expected_pages]
