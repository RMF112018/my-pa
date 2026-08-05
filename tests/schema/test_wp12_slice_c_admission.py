"""WP-12C isolated-PostgreSQL admission, revision, and concurrency evidence."""

from __future__ import annotations

import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from threading import Barrier
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import CheckConstraint, Engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.native_sources import (
    NATIVE_SOURCE_PROTOCOL_V1,
    NativeAdmissionEnvelope,
    NativeBucketProgress,
    NativeCoverageState,
    NativePreflightState,
    NativeProviderFailure,
    NativeSourceKind,
)
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.native_sources import (
    ExactBucketSelection,
    NativeAdmissionAuthority,
    NativeAdmissionAuthorityError,
    NativeConfigurationRevision,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.native_sources import (
    NativeBucketBindingRecord,
    NativePersistenceConflictError,
    SqlNativeReviewProposalRouter,
    SqlNativeSourceControlStore,
    SqlNativeSourceRepository,
)
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    capture_review_cases,
    native_admission_authorities,
    native_preflight_observations,
    native_source_review_routes,
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
        """INSERT INTO knowledge.native_source_buckets
             (bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at)
           VALUES (:bucket_2, :account, 'mail', 'Synthetic Archive', 'bucket.archive',
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
        "at": WHEN,
    }
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), values)
    SqlNativeSourceControlStore(engine).append_configuration(
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


def _authority(store: SqlNativeSourceControlStore) -> NativeAdmissionAuthority:
    snapshot = store.latest_configuration(CONFIGURATION)
    assert snapshot is not None
    return store.issue_sync_authority(
        snapshot.configuration,
        _binding(),
        audit_id=AUDIT,
        request_id="read.synthetic",
        issued_at=WHEN,
        expires_at=WHEN + timedelta(minutes=5),
    )


def _envelope(authority: NativeAdmissionAuthority) -> NativeAdmissionEnvelope:
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
        "nextCursor": None,
    }
    return NativeAdmissionEnvelope.model_validate(wire)


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
    store = SqlNativeSourceControlStore(c_engine)
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
    store = SqlNativeSourceControlStore(c_engine)
    authority = _authority(store)
    barrier = Barrier(2)

    def admit() -> tuple[tuple[str, bool], ...]:
        barrier.wait()
        return SqlNativeSourceControlStore(c_engine).admit_evidence_durably(
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

    status = SqlNativeSourceControlStore(c_engine).progress(CONFIGURATION)
    assert len(status) == 1
    assert status[0].coverage is NativeCoverageState.EVIDENCE_PRESENT
    assert status[0].admitted_count == 1
    assert "synthetic" not in status[0].to_canonical_json()


@pytest.mark.database
def test_configuration_revision_sequence_is_first_one_and_serialized(c_engine: Engine) -> None:
    _seed(c_engine)
    store = SqlNativeSourceControlStore(c_engine)
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
    store = SqlNativeSourceControlStore(c_engine)
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
        return SqlNativeSourceControlStore(c_engine).admit_evidence_durably(
            _envelope(authority),
            authority,
            (reachable,),
            at=WHEN + timedelta(seconds=1),
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with c_engine.begin() as connection:
            connection.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:id, 0))"),
                {"id": CONFIGURATION},
            )
            future = pool.submit(admit_after_lock)
            with pytest.raises(FutureTimeoutError):
                future.result(timeout=0.1)
            SqlNativeSourceRepository(connection).append_configuration(removed)
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
    store = SqlNativeSourceControlStore(c_engine)
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
    store = SqlNativeSourceControlStore(c_engine)
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
    store = SqlNativeSourceControlStore(c_engine)
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
    store = SqlNativeSourceControlStore(c_engine)
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
    )
    assert router.open_review_proposals((version_id,)) == (ids["proposal"],)
    assert router.open_review_proposals((version_id,)) == (ids["proposal"],)
    with c_engine.connect() as connection:
        route = connection.execute(select(native_source_review_routes)).one()
        assert (route.source_version_id, route.proposal_id) == (version_id, ids["proposal"])
        assert connection.scalar(select(func.count()).select_from(capture_review_cases)) == 1
    assert not hasattr(router, "promote")
    assert not hasattr(router, "decide")
