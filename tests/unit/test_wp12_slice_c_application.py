"""Focused WP-12C application contracts with synthetic protocol-v1 host data."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import normalize
from my_pa.application.errors import UnsupportedError
from my_pa.application.native_sources import (
    AdmissionDeniedError,
    NativeBucketBinding,
    NativeConfigurationSnapshot,
    NativeRequestContext,
    NativeSourceController,
    NativeSyncAuthority,
    PreflightDeniedError,
)
from my_pa.contracts.ports import AuditSink
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
from my_pa.domain.identity.operation import NativeSourceCapability, is_operator_only
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.native_sources import (
    ExactBucketSelection,
    NativeAdmissionAuthorityError,
    NativeConfigurationRevision,
)

WHEN = datetime(2026, 8, 5, 12, tzinfo=UTC)
BRIDGE = "nbrg_0000000000000001"
SOURCE_A = "src_0000000000000001"
SOURCE_B = "src_0000000000000002"
BUCKET_A = "nbkt_0000000000000001"
BUCKET_B = "nbkt_0000000000000002"
ACCOUNT_A = "nacct_0000000000000001"
ACCOUNT_B = "nacct_0000000000000002"
CONFIGURATION = "ncfg_0000000000000001"
ROOT = Path(__file__).resolve().parents[2]
SWIFT = "/usr/bin/swift"


@dataclass(frozen=True, slots=True)
class Binding:
    bucket_id: str
    account_id: str
    source_id: str
    bridge_id: str
    kind: NativeSourceKind
    account_label: str
    bucket_label: str
    account_locator: str
    bucket_locator: str
    selectable: bool


@dataclass(frozen=True, slots=True)
class Snapshot:
    configuration: NativeConfigurationRevision
    active: bool = True


def _metadata(envelope_id: str = "envelope.1") -> dict[str, Any]:
    return {
        "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
        "envelopeID": envelope_id,
        "hostInstanceID": BRIDGE,
        "emittedAtUnixMilliseconds": 1_775_563_200_000,
    }


def _selection(binding: Binding) -> dict[str, str]:
    return {
        "kind": binding.kind.value,
        "accountID": binding.account_locator,
        "bucketID": binding.bucket_locator,
    }


class Audit(AuditSink):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[object] = []

    def record(self, event: object) -> None:
        if self.fail:
            raise RuntimeError("synthetic audit unavailable")
        self.events.append(event)


class Host:
    def __init__(self) -> None:
        self.states: dict[
            str | tuple[str, str, str],
            tuple[NativePreflightState, NativeProviderFailure | None],
        ] = {}
        self.preflight_calls = 0
        self.response_request_id: str | None = None
        self.on_preflight: Callable[[], None] | None = None

    def negotiate(self, supported_versions: tuple[str, ...]) -> str:
        assert supported_versions == (NATIVE_SOURCE_PROTOCOL_V1,)
        return NATIVE_SOURCE_PROTOCOL_V1

    def discover(
        self,
        kind: NativeSourceKind,
        *,
        bridge_id: str,
        request_id: str,
        at: datetime,
    ) -> dict[str, Any]:
        del bridge_id, request_id, at
        accounts = [
            {"id": "account.a", "kind": "mail", "displayLabel": "Account A"},
            {"id": "account.b", "kind": "mail", "displayLabel": "Account B"},
        ]
        buckets = [
            {
                "id": "bucket.a",
                "accountID": "account.a",
                "parentID": None,
                "kind": "mail",
                "displayLabel": "Inbox A",
                "isSelectable": True,
            },
            {
                "id": "bucket.b",
                "accountID": "account.b",
                "parentID": None,
                "kind": "mail",
                "displayLabel": "Inbox B",
                "isSelectable": True,
            },
        ]
        return {
            "metadata": _metadata("discovery.1"),
            "snapshot": {
                "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
                "kind": kind.value,
                "accounts": accounts,
                "buckets": buckets,
            },
        }

    def preflight(
        self,
        selections: tuple[NativeBucketSelection, ...],
        *,
        bridge_id: str,
        request_id: str,
        at: datetime,
    ) -> dict[str, Any]:
        del bridge_id, at
        self.preflight_calls += 1
        if self.on_preflight is not None:
            self.on_preflight()
        results = []
        for selection in selections:
            state, failure = self.states.get(
                (selection.kind.value, selection.account_id, selection.bucket_id),
                self.states.get(selection.bucket_id, (NativePreflightState.REACHABLE, None)),
            )
            results.append(
                {
                    "selection": {
                        "kind": selection.kind.value,
                        "accountID": selection.account_id,
                        "bucketID": selection.bucket_id,
                    },
                    "state": state.value,
                    "failure": None if failure is None else failure.value,
                }
            )
        return {
            "metadata": _metadata(f"preflight.{self.preflight_calls}"),
            "requestID": self.response_request_id or request_id,
            "results": results,
        }


class Store:
    def __init__(self) -> None:
        self.bindings = {
            BUCKET_A: Binding(
                BUCKET_A,
                ACCOUNT_A,
                SOURCE_A,
                BRIDGE,
                NativeSourceKind.MAIL,
                "Account A",
                "Inbox A",
                "account.a",
                "bucket.a",
                True,
            ),
            BUCKET_B: Binding(
                BUCKET_B,
                ACCOUNT_B,
                SOURCE_B,
                BRIDGE,
                NativeSourceKind.MAIL,
                "Account B",
                "Inbox B",
                "account.b",
                "bucket.b",
                True,
            ),
        }
        self.configurations: list[NativeConfigurationRevision] = []
        self.persisted: dict[tuple[str, str], str] = {}
        self.durable_before_enrichment = False
        self.authorities: dict[str, NativeSyncAuthority] = {}
        self.consumed: dict[str, NativeAdmissionEnvelope] = {}
        self.preflight: dict[str, NativeBucketProgress] = {}
        self.preflight_writes = 0

    def bridge_protocol(self, bridge_id: str) -> str | None:
        return NATIVE_SOURCE_PROTOCOL_V1 if bridge_id == BRIDGE else None

    def bucket_bindings(self, bucket_ids: tuple[str, ...]) -> tuple[NativeBucketBinding, ...]:
        return tuple(self.bindings[bucket] for bucket in bucket_ids if bucket in self.bindings)

    def visible_locator_pairs(
        self, bridge_id: str, source_ids: frozenset[str]
    ) -> frozenset[tuple[str, str]]:
        return frozenset(
            (binding.account_locator, binding.bucket_locator)
            for binding in self.bindings.values()
            if binding.bridge_id == bridge_id and binding.source_id in source_ids
        )

    def append_configuration(
        self,
        configuration: NativeConfigurationRevision,
        *,
        expected_prior_revision: int,
        preflight: tuple[NativeBucketProgress, ...] = (),
    ) -> None:
        latest = self.configurations[-1].revision if self.configurations else 0
        if latest != expected_prior_revision or configuration.revision != latest + 1:
            raise RuntimeError("stale configuration revision")
        self.configurations.append(configuration)
        self.preflight.update({result.bucket_id: result for result in preflight})

    def latest_configuration(self, configuration_id: str) -> NativeConfigurationSnapshot | None:
        matches = [
            configuration
            for configuration in self.configurations
            if configuration.configuration_id == configuration_id
        ]
        return None if not matches else Snapshot(matches[-1])

    def progress(self, configuration_id: str) -> tuple[NativeBucketProgress, ...]:
        configuration = self.latest_configuration(configuration_id)
        assert configuration is not None
        progress = []
        for bucket_id in configuration.configuration.selection.bucket_ids:
            observed = self.preflight.get(bucket_id)
            if observed is not None and observed.coverage in {
                NativeCoverageState.PERMISSION_DENIED,
                NativeCoverageState.UNAVAILABLE,
            }:
                progress.append(observed)
                continue
            progress.append(
                NativeBucketProgress(
                    bucket_id=bucket_id,
                    state="complete",
                    coverage=(
                        NativeCoverageState.EVIDENCE_PRESENT
                        if any(key[0] == bucket_id for key in self.persisted)
                        else NativeCoverageState.EMPTY
                    ),
                    admitted_count=sum(key[0] == bucket_id for key in self.persisted),
                    failed_count=0,
                    pending_count=0,
                )
            )
        return tuple(progress)

    def record_preflight(
        self,
        configuration_id: str,
        configuration_revision: int,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None:
        del configuration_id, configuration_revision, observed_at
        self.preflight_writes += 1
        self.preflight.update({result.bucket_id: result for result in results})

    def issue_sync_authority(
        self,
        configuration: NativeConfigurationRevision,
        binding: NativeBucketBinding,
        *,
        audit_id: str,
        request_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> NativeSyncAuthority:
        authority = NativeSyncAuthority(
            authority_id="nauth_0000000000000001",
            configuration_id=configuration.configuration_id,
            configuration_revision=configuration.revision,
            bridge_id=configuration.bridge_id,
            bucket_id=binding.bucket_id,
            source_id=binding.source_id,
            audit_id=audit_id,
            envelope_id="nauth_0000000000000001",
            request_id=request_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self.authorities[authority.authority_id] = authority
        return authority

    def prevalidate_authority(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeSyncAuthority,
        *,
        at: datetime,
    ) -> None:
        stored = self.authorities.get(authority.authority_id)
        current = self.latest_configuration(authority.configuration_id)
        prior = self.consumed.get(authority.authority_id)
        if (
            stored != authority
            or current is None
            or current.configuration.revision != authority.configuration_revision
            or authority.bucket_id not in current.configuration.selection.bucket_ids
            or not authority.issued_at <= at <= authority.expires_at
            or envelope.metadata.envelope_id != authority.envelope_id
            or envelope.request_id != authority.request_id
            or (prior is not None and prior != envelope)
        ):
            raise NativeAdmissionAuthorityError("synthetic authority mismatch")

    def record_admission_preflight_durably(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeSyncAuthority,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None:
        self.prevalidate_authority(envelope, authority, at=observed_at)
        self.record_preflight(
            authority.configuration_id,
            authority.configuration_revision,
            results,
            observed_at=observed_at,
        )

    def admit_evidence_durably(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeSyncAuthority,
        preflight: tuple[NativeBucketProgress, ...] = (),
        *,
        at: datetime,
    ) -> tuple[tuple[str, bool], ...]:
        stored = self.authorities.get(authority.authority_id)
        current = self.latest_configuration(authority.configuration_id)
        if (
            stored != authority
            or current is None
            or current.configuration.revision != authority.configuration_revision
            or authority.bucket_id not in current.configuration.selection.bucket_ids
            or not authority.issued_at <= at <= authority.expires_at
            or envelope.metadata.envelope_id != authority.envelope_id
            or envelope.request_id != authority.request_id
        ):
            raise NativeAdmissionAuthorityError("synthetic authority mismatch")
        prior = self.consumed.get(authority.authority_id)
        if prior is not None and prior != envelope:
            raise NativeAdmissionAuthorityError("synthetic authority replay mismatch")
        self.record_preflight(
            authority.configuration_id,
            authority.configuration_revision,
            preflight,
            observed_at=at,
        )
        self.consumed[authority.authority_id] = envelope
        outcomes = []
        for record in envelope.records:
            key = (authority.bucket_id, f"{record.id}:{record.source_revision}")
            created = key not in self.persisted
            version_id = self.persisted.setdefault(key, f"ver_{len(self.persisted) + 1:016d}")
            outcomes.append((version_id, created))
        self.durable_before_enrichment = True
        return tuple(outcomes)


class Proposals:
    def __init__(self, store: Store, *, fail: bool = False) -> None:
        self.store = store
        self.fail = fail
        self.version_ids: tuple[str, ...] = ()

    def open_review_proposals(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
        assert self.store.durable_before_enrichment
        self.version_ids = version_ids
        if self.fail:
            raise RuntimeError("synthetic enrichment failed")
        return tuple(f"prop_{index:016d}" for index, _ in enumerate(version_ids, 1))


def _context(
    *,
    purpose: Purpose,
    sources: frozenset[str],
    kind: PrincipalKind = PrincipalKind.OPERATOR,
    request_id: str = "request.1",
) -> NativeRequestContext:
    return NativeRequestContext(
        principal=Principal("prn_0000000000000001", kind, authenticated=True),
        purpose=purpose,
        correlation_id="corr_0000000000000001",
        request_id=request_id,
        authorized_source_ids=sources,
        at=WHEN,
    )


def _configuration() -> NativeConfigurationRevision:
    return NativeConfigurationRevision(
        configuration_id=CONFIGURATION,
        revision=1,
        bridge_id=BRIDGE,
        timezone_name="America/New_York",
        start_date=date(2026, 8, 1),
        cutoff_at=WHEN,
        selection=ExactBucketSelection((BUCKET_A, BUCKET_B)),
        created_at=WHEN,
    )


def _controller(
    *, audit: Audit | None = None, proposals_fail: bool = False
) -> tuple[NativeSourceController, Store, Host, Audit, Proposals]:
    store = Store()
    host = Host()
    actual_audit = Audit() if audit is None else audit
    proposals = Proposals(store, fail=proposals_fail)
    return (
        NativeSourceController(store=store, host=host, audit=actual_audit, proposals=proposals),
        store,
        host,
        actual_audit,
        proposals,
    )


def test_native_capability_vocabulary_and_operator_boundary_are_closed() -> None:
    names = {capability.value for capability in NativeSourceCapability}
    assert names == {
        "native_sources.discover",
        "native_sources.configure",
        "native_sources.preflight",
        "native_sources.sync",
        "native_sources.status",
        "native_sources.retry",
        "native_sources.reconcile",
        "native_sources.pause",
        "native_sources.resume",
        "native_sources.backfill",
        "native_sources.disable",
    }
    assert not is_operator_only(NativeSourceCapability.DISCOVER)
    assert not is_operator_only(NativeSourceCapability.STATUS)
    assert all(
        is_operator_only(capability)
        for capability in NativeSourceCapability
        if capability not in {NativeSourceCapability.DISCOVER, NativeSourceCapability.STATUS}
    )


def test_native_commands_remain_fail_closed_on_legacy_transports_until_slice_g() -> None:
    assert all(not tool.name.startswith("native_sources.") for tool in TOOLS)
    with pytest.raises(UnsupportedError):
        normalize(
            NativeSourceCapability.STATUS.value,
            {
                "request_id": "request-1",
                "purpose": Purpose.STATUS_OBSERVATION.value,
                "principal_id": "prn_0000000000000001",
                "requested_at": WHEN.isoformat(),
                "payload": {},
            },
        )


def test_discovery_is_policy_scoped_and_never_returns_an_unenrolled_account() -> None:
    controller, _, _, audit, _ = _controller()
    discovered = controller.discover(
        _context(purpose=Purpose.SOURCE_INSPECTION, sources=frozenset({SOURCE_A})),
        bridge_id=BRIDGE,
        kind=NativeSourceKind.MAIL,
        source_ids=frozenset({SOURCE_A}),
    )
    assert tuple(account.id for account in discovered.snapshot.accounts) == ("account.a",)
    assert tuple(bucket.id for bucket in discovered.snapshot.buckets) == ("bucket.a",)
    assert len(audit.events) == 1


def test_configuration_requires_exact_typed_identity_preflight_and_durable_audit() -> None:
    controller, store, _, audit, _ = _controller()
    context = _context(
        purpose=Purpose.BOUNDED_ENROLLMENT,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    receipt = controller.configure(
        context,
        _configuration(),
        typed_account_labels={ACCOUNT_A: "Account A", ACCOUNT_B: "Account B"},
        typed_bucket_labels={BUCKET_A: "Inbox A", BUCKET_B: "Inbox B"},
    )
    assert receipt.selected_bucket_count == 2
    assert len(store.configurations) == 1
    assert len(audit.events) == 1

    with pytest.raises(AdmissionDeniedError, match="typed native names"):
        controller.configure(
            context,
            replace(_configuration(), configuration_id="ncfg_0000000000000002"),
            typed_account_labels={ACCOUNT_A: "Account A", ACCOUNT_B: "Account B"},
            typed_bucket_labels={BUCKET_A: "Inbox A", BUCKET_B: "Wrong"},
        )

    failed_audit = Audit(fail=True)
    blocked, blocked_store, _, _, _ = _controller(audit=failed_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        blocked.configure(
            context,
            _configuration(),
            typed_account_labels={ACCOUNT_A: "Account A", ACCOUNT_B: "Account B"},
            typed_bucket_labels={BUCKET_A: "Inbox A", BUCKET_B: "Inbox B"},
        )
    assert blocked_store.configurations == []


def test_preflight_distinguishes_empty_permission_denial_and_unavailability() -> None:
    controller, store, host, _, _ = _controller()
    context = _context(
        purpose=Purpose.SECURITY_VALIDATION,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    host.states["bucket.a"] = (
        NativePreflightState.PERMISSION_DENIED,
        NativeProviderFailure.PERMISSION_DENIED,
    )
    host.states["bucket.b"] = (
        NativePreflightState.UNAVAILABLE,
        NativeProviderFailure.TRANSIENT_UNAVAILABLE,
    )
    verification = controller.preflight(context, bridge_id=BRIDGE, bucket_ids=(BUCKET_A, BUCKET_B))
    assert not verification.reachable
    assert tuple(result.coverage for result in verification.bucket_results) == (
        NativeCoverageState.PERMISSION_DENIED,
        NativeCoverageState.UNAVAILABLE,
    )

    empty = NativeBucketProgress(
        bucket_id=BUCKET_A,
        state="complete",
        coverage=NativeCoverageState.EMPTY,
        admitted_count=0,
        failed_count=0,
        pending_count=0,
    )
    assert empty.coverage is NativeCoverageState.EMPTY

    store.append_configuration(_configuration(), expected_prior_revision=0)
    store.record_preflight(
        CONFIGURATION,
        1,
        verification.bucket_results,
        observed_at=WHEN,
    )
    durable = controller.status(
        _context(
            purpose=Purpose.STATUS_OBSERVATION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        configuration_id=CONFIGURATION,
    )
    assert tuple((item.coverage, item.failure) for item in durable) == (
        (NativeCoverageState.PERMISSION_DENIED, NativeProviderFailure.PERMISSION_DENIED),
        (NativeCoverageState.UNAVAILABLE, NativeProviderFailure.TRANSIENT_UNAVAILABLE),
    )


def test_preflight_binds_request_and_composite_private_locator_exactly() -> None:
    controller, store, host, _, _ = _controller()
    context = _context(
        purpose=Purpose.SECURITY_VALIDATION,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    host.response_request_id = "read.stale"
    verification = controller.preflight(context, bridge_id=BRIDGE, bucket_ids=(BUCKET_A, BUCKET_B))
    assert not verification.identity_verified
    assert not verification.reachable
    assert store.preflight_writes == 0
    assert store.configurations == []
    assert store.authorities == {}
    with pytest.raises(PreflightDeniedError, match="preflight did not pass"):
        controller.configure(
            _context(
                purpose=Purpose.BOUNDED_ENROLLMENT,
                sources=frozenset({SOURCE_A, SOURCE_B}),
            ),
            _configuration(),
            typed_account_labels={ACCOUNT_A: "Account A", ACCOUNT_B: "Account B"},
            typed_bucket_labels={BUCKET_A: "Inbox A", BUCKET_B: "Inbox B"},
        )
    assert store.preflight_writes == 0
    assert store.configurations == []
    assert store.authorities == {}

    host.response_request_id = None
    store.bindings[BUCKET_A] = replace(store.bindings[BUCKET_A], bucket_locator="bucket.shared")
    store.bindings[BUCKET_B] = replace(store.bindings[BUCKET_B], bucket_locator="bucket.shared")
    host.states[("mail", "account.b", "bucket.shared")] = (
        NativePreflightState.PERMISSION_DENIED,
        NativeProviderFailure.PERMISSION_DENIED,
    )
    verification = controller.preflight(context, bridge_id=BRIDGE, bucket_ids=(BUCKET_A, BUCKET_B))
    assert tuple((result.bucket_id, result.coverage) for result in verification.bucket_results) == (
        (BUCKET_A, NativeCoverageState.NOT_MEASURED),
        (BUCKET_B, NativeCoverageState.PERMISSION_DENIED),
    )


def test_sync_repreflights_and_scope_removal_retains_evidence() -> None:
    controller, store, host, _, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    context = _context(
        purpose=Purpose.CONTENT_EXTRACTION,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    authority = controller.lifecycle(
        context,
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    assert host.preflight_calls == 1

    store.persisted[(BUCKET_A, "record:revision")] = "ver_0000000000000001"
    disabled = controller.disable(
        _context(
            purpose=Purpose.BOUNDED_ENROLLMENT,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        configuration_id=CONFIGURATION,
        bucket_ids=(BUCKET_A,),
    )
    assert disabled.configuration_revision == 2
    assert store.configurations[-1].selection.bucket_ids == (BUCKET_B,)
    assert store.persisted == {(BUCKET_A, "record:revision"): "ver_0000000000000001"}


def test_admission_is_exact_idempotent_and_evidence_survives_enrichment_failure() -> None:
    controller, store, host, _, proposals = _controller(proposals_fail=True)
    store.append_configuration(_configuration(), expected_prior_revision=0)
    operator = _context(
        purpose=Purpose.CONTENT_EXTRACTION,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    authority = controller.lifecycle(
        operator,
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    adapter = _context(
        purpose=Purpose.CONTENT_EXTRACTION,
        sources=frozenset(),
        kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
    )
    wire: dict[str, Any] = {
        "metadata": _metadata(authority.envelope_id),
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [
            {
                "id": "message.1",
                "bucketID": "bucket.a",
                "kind": "mail",
                "sourceRevision": "revision-1",
                "sourceModifiedUnixMilliseconds": 1_775_563_200_000,
                "payload": [115, 101, 110, 116, 105, 110, 101, 108],
            }
        ],
        "nextCursor": None,
    }
    first = controller.admit(adapter, authority=authority, wire_envelope=wire)
    second = controller.admit(adapter, authority=authority, wire_envelope=wire)
    assert (first.admitted_count, first.duplicate_count) == (1, 0)
    assert (second.admitted_count, second.duplicate_count) == (0, 1)
    assert first.enrichment_failed and second.enrichment_failed
    assert store.durable_before_enrichment
    assert proposals.version_ids == ("ver_0000000000000001",)
    assert host.preflight_calls == 3  # sync plus one immediate check per allowed admission
    assert "sentinel" not in repr(first)

    escaped = dict(wire)
    escaped["bucketID"] = "bucket.outside"
    with pytest.raises(ValueError, match="escape"):
        controller.admit(adapter, authority=authority, wire_envelope=escaped)

    calls_before_denials = host.preflight_calls
    writes_before_denials = store.preflight_writes
    for rejected_authority, rejected_context, rejected_wire in (
        (replace(authority, authority_id="nauth_9999999999999999"), adapter, wire),
        (replace(authority, audit_id="audit_9999999999999999"), adapter, wire),
        (
            authority,
            replace(adapter, at=authority.expires_at + timedelta(microseconds=1)),
            wire,
        ),
    ):
        with pytest.raises(AdmissionDeniedError, match="stale or unauthenticated"):
            controller.admit(
                rejected_context,
                authority=rejected_authority,
                wire_envelope=rejected_wire,
            )
        assert host.preflight_calls == calls_before_denials
        assert store.preflight_writes == writes_before_denials

    changed = dict(wire)
    changed["records"] = [dict(wire["records"][0], sourceRevision="revision-2")]
    with pytest.raises(AdmissionDeniedError, match="stale or unauthenticated"):
        controller.admit(
            adapter,
            authority=authority,
            wire_envelope=changed,
        )
    assert host.preflight_calls == calls_before_denials
    assert store.preflight_writes == writes_before_denials


def test_contract_rejects_unknown_fields_scope_drift_and_content_in_progress() -> None:
    wire: dict[str, Any] = {
        "metadata": _metadata(),
        "requestID": "read.1",
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [
            {
                "id": "message.1",
                "bucketID": "bucket.other",
                "kind": "mail",
                "sourceRevision": "revision-1",
                "sourceModifiedUnixMilliseconds": None,
                "payload": [1],
            }
        ],
        "nextCursor": None,
    }
    with pytest.raises(ValueError, match="escape"):
        NativeAdmissionEnvelope.model_validate(wire)
    with pytest.raises(ValueError, match="extra"):
        NativeBucketProgress.model_validate(
            {
                "bucket_id": BUCKET_A,
                "state": "complete",
                "coverage": "empty",
                "admitted_count": 0,
                "failed_count": 0,
                "pending_count": 0,
                "content": "sentinel",
            }
        )


def test_admission_refuses_non_adapter_and_preflight_drift() -> None:
    controller, store, host, _, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    authority = controller.lifecycle(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    calls_before_admission = host.preflight_calls
    writes_before_admission = store.preflight_writes
    wire: dict[str, Any] = {
        "metadata": _metadata(authority.envelope_id),
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [],
        "nextCursor": None,
    }
    with pytest.raises(AdmissionDeniedError, match="authenticated adapter"):
        controller.admit(
            _context(purpose=Purpose.CONTENT_EXTRACTION, sources=frozenset({SOURCE_A})),
            authority=authority,
            wire_envelope=wire,
        )
    host.states["bucket.a"] = (
        NativePreflightState.IDENTITY_DRIFT,
        NativeProviderFailure.BUCKET_UNAVAILABLE,
    )
    with pytest.raises(PreflightDeniedError):
        controller.admit(
            _context(
                purpose=Purpose.CONTENT_EXTRACTION,
                sources=frozenset(),
                kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
            ),
            authority=authority,
            wire_envelope=wire,
        )
    assert host.preflight_calls == calls_before_admission + 1
    assert store.preflight_writes == writes_before_admission + 1
    assert authority.authority_id not in store.consumed


def test_admission_stale_preflight_request_id_has_zero_durable_effects() -> None:
    controller, store, host, _, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    authority = controller.lifecycle(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    calls_before_admission = host.preflight_calls
    writes_before_admission = store.preflight_writes
    host.response_request_id = "read.stale"
    wire: dict[str, Any] = {
        "metadata": _metadata(authority.envelope_id),
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [],
        "nextCursor": None,
    }

    with pytest.raises(PreflightDeniedError, match="identity did not match"):
        controller.admit(
            _context(
                purpose=Purpose.CONTENT_EXTRACTION,
                sources=frozenset(),
                kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
            ),
            authority=authority,
            wire_envelope=wire,
        )

    assert host.preflight_calls == calls_before_admission + 1
    assert store.preflight_writes == writes_before_admission
    assert store.persisted == {}
    assert authority.authority_id not in store.consumed


def test_admission_context_request_mismatch_has_zero_host_or_durable_effects() -> None:
    controller, store, host, _, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    authority = controller.lifecycle(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
            request_id="request.a",
        ),
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    calls_before_admission = host.preflight_calls
    writes_before_admission = store.preflight_writes
    wire: dict[str, Any] = {
        "metadata": _metadata(authority.envelope_id),
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [],
        "nextCursor": None,
    }

    with pytest.raises(AdmissionDeniedError, match="bridge identity did not match"):
        controller.admit(
            _context(
                purpose=Purpose.CONTENT_EXTRACTION,
                sources=frozenset(),
                kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
                request_id="request.b",
            ),
            authority=authority,
            wire_envelope=wire,
        )

    assert host.preflight_calls == calls_before_admission
    assert store.preflight_writes == writes_before_admission
    assert store.persisted == {}
    assert authority.authority_id not in store.consumed


def test_admission_scope_removal_during_host_call_has_zero_durable_effects() -> None:
    controller, store, host, _, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    authority = controller.lifecycle(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    calls_before_admission = host.preflight_calls
    writes_before_admission = store.preflight_writes
    revised = replace(
        _configuration(),
        revision=2,
        selection=ExactBucketSelection((BUCKET_B,)),
        created_at=WHEN + timedelta(seconds=1),
    )
    host.on_preflight = lambda: store.append_configuration(revised, expected_prior_revision=1)
    wire: dict[str, Any] = {
        "metadata": _metadata(authority.envelope_id),
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [],
        "nextCursor": None,
    }

    with pytest.raises(AdmissionDeniedError, match="stale or unauthenticated"):
        controller.admit(
            _context(
                purpose=Purpose.CONTENT_EXTRACTION,
                sources=frozenset(),
                kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
            ),
            authority=authority,
            wire_envelope=wire,
        )

    assert host.preflight_calls == calls_before_admission + 1
    assert store.preflight_writes == writes_before_admission
    assert store.persisted == {}
    assert authority.authority_id not in store.consumed


@pytest.mark.connector
def test_merged_swift_synthetic_host_drives_discovery_preflight_and_admission() -> None:
    """Actual Slice D envelopes cross the process/language boundary into C."""
    completed = subprocess.run(  # noqa: S603 - fixed executable and synthetic fixture args
        [
            SWIFT,
            "run",
            "--package-path",
            str(ROOT / "native/apple-source-host"),
            "--scratch-path",
            "/private/tmp/my-pa-wp12c-swift-fixture-test",
            "AppleSourceHostFixtureExport",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    exported = json.loads(completed.stdout)

    class SwiftFixtureHost:
        def negotiate(self, supported_versions: tuple[str, ...]) -> str:
            assert supported_versions == (NATIVE_SOURCE_PROTOCOL_V1,)
            return str(exported["agreement"]["selectedVersion"])

        def discover(
            self,
            kind: NativeSourceKind,
            *,
            bridge_id: str,
            request_id: str,
            at: datetime,
        ) -> dict[str, Any]:
            del bridge_id, request_id, at
            assert kind is NativeSourceKind.MAIL
            return dict(exported["discovery"])

        def preflight(
            self,
            selections: tuple[NativeBucketSelection, ...],
            *,
            bridge_id: str,
            request_id: str,
            at: datetime,
        ) -> dict[str, Any]:
            del bridge_id, request_id, at
            assert len(selections) == 1
            return dict(exported["preflight"])

    store = Store()
    proposals = Proposals(store)
    controller = NativeSourceController(
        store=store,
        host=SwiftFixtureHost(),
        audit=Audit(),
        proposals=proposals,
    )
    discovered = controller.discover(
        _context(purpose=Purpose.SOURCE_INSPECTION, sources=frozenset({SOURCE_A})),
        bridge_id=BRIDGE,
        kind=NativeSourceKind.MAIL,
        source_ids=frozenset({SOURCE_A}),
    )
    assert tuple(bucket.id for bucket in discovered.snapshot.buckets) == ("bucket.a",)

    configuration = replace(_configuration(), selection=ExactBucketSelection((BUCKET_A,)))
    store.append_configuration(configuration, expected_prior_revision=0)
    authority = controller.lifecycle(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    receipt = controller.admit(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset(),
            kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
        ),
        authority=authority,
        wire_envelope=exported["admission"],
    )
    assert receipt.admitted_count == 1
    assert receipt.bucket_id == BUCKET_A


# --- WP-15: the host foundation's application half ---------------------------


@pytest.mark.connector
def test_wp15_a_replayed_protected_spool_item_admits_once_and_names_the_duplicate() -> None:
    """Replay proved on the spool's own bytes, not on a fixture resembling them.

    WP-12C already proves that admitting the same *envelope* twice yields one
    version. What that leaves open is the step in between: the host does not hand
    the application an envelope, it writes one into the protected spool and the
    spool is what is replayed after a crash, a retry, or an acknowledgement that
    did not land. So the bytes admitted here are read back out of a real
    `ProtectedSpool` — enqueued, refused a byte-identical duplicate by the spool
    itself, and read through `item(_:)` — before they ever reach Python.
    """
    completed = subprocess.run(  # noqa: S603 - fixed executable and synthetic fixture args
        [
            SWIFT,
            "run",
            "--package-path",
            str(ROOT / "native/apple-source-host"),
            "--scratch-path",
            "/private/tmp/my-pa-wp12c-swift-fixture-test",
            "AppleSourceHostFixtureExport",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    exported = json.loads(completed.stdout)
    spool_item = exported["spoolItem"]

    # The spool stores the admission envelope as opaque payload bytes and adds no
    # field of its own beyond identity and version, so what the application
    # admits is exactly what the host emitted.
    assert spool_item["protocolVersion"] == NATIVE_SOURCE_PROTOCOL_V1
    spooled = json.loads(bytes(spool_item["payload"]).decode())
    assert spooled == exported["admission"], "the spool altered the envelope it stored"
    assert exported["spoolHealth"]["pendingItemCount"] == 1
    assert exported["spoolHealth"]["maximumItems"] >= 1

    controller, store, host, audit, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    authority = controller.lifecycle(
        _context(
            purpose=Purpose.CONTENT_EXTRACTION,
            sources=frozenset({SOURCE_A, SOURCE_B}),
        ),
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    adapter = _context(
        purpose=Purpose.CONTENT_EXTRACTION,
        sources=frozenset(),
        kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
    )
    first = controller.admit(adapter, authority=authority, wire_envelope=spooled)
    replayed = controller.admit(adapter, authority=authority, wire_envelope=spooled)

    assert (first.admitted_count, first.duplicate_count) == (1, 0)
    assert (replayed.admitted_count, replayed.duplicate_count) == (0, 1)
    assert len(store.persisted) == 1, "a replayed spool item created a second version"
    assert first.evidence_digest == replayed.evidence_digest
    # The duplicate is reported, never swallowed: a caller that acknowledges its
    # spool item on a silent success would have no way to tell the two apart.
    assert replayed.duplicate_count == 1
    assert host.preflight_calls == 3
    # One audit row, written by the SYNC grant before any host call. Admission
    # itself is authorized by the durable grant rather than by a second policy
    # decision, which is why a replay cannot mint authority it was not issued.
    assert len(audit.events) == 1


@pytest.mark.connector
def test_wp15_the_spool_item_carries_no_provider_locator_or_display_label() -> None:
    """The host's storage holds opaque identity, not the account it came from."""
    completed = subprocess.run(  # noqa: S603 - fixed executable and synthetic fixture args
        [
            SWIFT,
            "run",
            "--package-path",
            str(ROOT / "native/apple-source-host"),
            "--scratch-path",
            "/private/tmp/my-pa-wp12c-swift-fixture-test",
            "AppleSourceHostFixtureExport",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    exported = json.loads(completed.stdout)
    item = exported["spoolItem"]
    assert set(item) == {
        "envelopeID",
        "protocolVersion",
        "kind",
        "accountID",
        "bucketID",
        "payload",
    }
    # The discovery snapshot does carry display labels; the spooled handoff does
    # not, so a spool inspected on disk cannot name the human's accounts.
    labels = {account["displayLabel"] for account in exported["discovery"]["snapshot"]["accounts"]}
    assert labels, "the discovery fixture carries no label, so the check is vacuous"
    rendered = json.dumps({key: item[key] for key in item if key != "payload"})
    for label in labels:
        assert label not in rendered
    for punctuation in ("@", "/", "\\"):
        assert punctuation not in item["accountID"] + item["bucketID"] + item["envelopeID"]


def test_wp15_admission_telemetry_and_receipts_carry_no_record_content() -> None:
    """WP-15 control 6 on the application side, planted rather than asserted.

    The marker below is obviously-synthetic stand-in content occupying the same
    field a real message body would. It is planted in the payload of an admitted
    record and then looked for in every operational artefact the admission path
    produces — the receipt, the audit events, and the text of the exceptions the
    refusal paths raise.
    """
    marker = "SYNTHETIC-BODY-MARKER-c0ffee"
    payload = list(marker.encode())
    controller, store, host, audit, _ = _controller()
    store.append_configuration(_configuration(), expected_prior_revision=0)
    operator = _context(
        purpose=Purpose.CONTENT_EXTRACTION,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    authority = controller.lifecycle(
        operator,
        capability=NativeSourceCapability.SYNC,
        configuration_id=CONFIGURATION,
        bucket_id=BUCKET_A,
    )
    assert isinstance(authority, NativeSyncAuthority)
    adapter = _context(
        purpose=Purpose.CONTENT_EXTRACTION,
        sources=frozenset(),
        kind=PrincipalKind.SOURCE_PROVIDER_ADAPTER,
    )
    wire: dict[str, Any] = {
        "metadata": _metadata(authority.envelope_id),
        "requestID": authority.request_id,
        "kind": "mail",
        "accountID": "account.a",
        "bucketID": "bucket.a",
        "records": [
            {
                "id": "message.1",
                "bucketID": "bucket.a",
                "kind": "mail",
                "sourceRevision": "revision-1",
                "sourceModifiedUnixMilliseconds": 1_775_563_200_000,
                "payload": payload,
            }
        ],
        "nextCursor": None,
    }

    envelope = NativeAdmissionEnvelope.model_validate(wire)
    assert marker.encode() == bytes(envelope.records[0].payload), (
        "the planted marker is not in the admitted record, so its absence "
        "downstream would prove nothing"
    )

    receipt = controller.admit(adapter, authority=authority, wire_envelope=wire)
    assert receipt.admitted_count == 1

    emissions = [repr(receipt), str(receipt)]
    emissions.extend(repr(event) for event in audit.events)
    emissions.extend(str(event) for event in audit.events)
    observer = _context(
        purpose=Purpose.STATUS_OBSERVATION,
        sources=frozenset({SOURCE_A, SOURCE_B}),
    )
    emissions.append(repr(controller.status(observer, configuration_id=CONFIGURATION)))

    # Every refusal path the adapter can reach, because an error message is where
    # content escapes when a receipt does not.
    for rejected_wire, expected in (
        (dict(wire, bucketID="bucket.outside"), ValueError),
        (dict(wire, accountID="account.b"), AdmissionDeniedError),
        (dict(wire, requestID="request.9"), AdmissionDeniedError),
    ):
        with pytest.raises((ValueError, AdmissionDeniedError)) as raised:
            controller.admit(adapter, authority=authority, wire_envelope=rejected_wire)
        assert isinstance(raised.value, expected)
        emissions.append(str(raised.value))
        emissions.append(repr(raised.value))

    for emission in emissions:
        assert marker not in emission, (
            "an operational artefact of native admission carried the content of "
            "an admitted record. Receipts, audit events and error text carry "
            "counts, identifiers, types and error classes only"
        )
        assert "account.a" not in emission or "locator" not in emission
    assert host.preflight_calls >= 2
