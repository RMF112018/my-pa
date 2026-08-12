"""WP-12C native-source admission and control use cases.

This module is the authenticated application boundary between the source-built
protocol-v1 host and canonical persistence.  It owns no Apple framework code,
credentials, watcher, checkpoint advancement, or baseline worker.  Provider
locators exist only long enough to form an exact host request and never appear
in a public status, audit event, exception, or receipt.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol, assert_never

from my_pa.contracts.ports import AuditSink
from my_pa.contracts.v1.base import canonical_json
from my_pa.contracts.v1.native_sources import (
    NATIVE_SOURCE_MAX_PAGE_SIZE,
    NATIVE_SOURCE_PROTOCOL_V1,
    NativeAdmissionEnvelope,
    NativeBucketProgress,
    NativeBucketSelection,
    NativeCoverageState,
    NativeDiscoveryEnvelope,
    NativePreflightEnvelope,
    NativePreflightState,
    NativeSourceKind,
)
from my_pa.domain.audit.events import audit_event_for
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import NativeSourceCapability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.native_sources import (
    ExactBucketSelection,
    NativeAdmissionAuthorityError,
    NativeConfigurationRevision,
)
from my_pa.domain.native_sources import NativeAdmissionAuthority as NativeSyncAuthority
from my_pa.domain.policy.decision import PolicyRequest, evaluate
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "AdmissionDeniedError",
    "NativeAdmissionReceipt",
    "NativeBridgeVerification",
    "NativeBucketBinding",
    "NativeConfigurationSnapshot",
    "NativeControlReceipt",
    "NativeReadPageReceipt",
    "NativeRequestContext",
    "NativeSourceController",
    "NativeSourceHost",
    "NativeSourceStore",
    "NativeSyncAuthority",
    "PreflightDeniedError",
]


class PreflightDeniedError(RuntimeError):
    """Exact selected scope was not wholly reachable at the preflight boundary."""


class AdmissionDeniedError(RuntimeError):
    """An admission handoff did not prove identity, authority, and exact scope."""


@dataclass(frozen=True, slots=True)
class NativeRequestContext:
    principal: Principal
    purpose: Purpose
    correlation_id: str
    request_id: str
    authorized_source_ids: frozenset[str]
    at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        if not self.request_id or len(self.request_id) > 200:
            raise ValueError("a bounded native request identifier is required")
        for source_id in self.authorized_source_ids:
            validate_identifier(source_id, IdKind.SOURCE)
        object.__setattr__(self, "at", ensure_utc(self.at))


class NativeBucketBinding(Protocol):
    """Private exact mapping implemented by persistence; never a response value."""

    @property
    def bucket_id(self) -> str: ...

    @property
    def account_id(self) -> str: ...

    @property
    def source_id(self) -> str: ...

    @property
    def bridge_id(self) -> str: ...

    @property
    def kind(self) -> NativeSourceKind: ...

    @property
    def account_label(self) -> str: ...

    @property
    def bucket_label(self) -> str: ...

    @property
    def account_locator(self) -> str: ...

    @property
    def bucket_locator(self) -> str: ...

    @property
    def selectable(self) -> bool: ...


class NativeConfigurationSnapshot(Protocol):
    @property
    def configuration(self) -> NativeConfigurationRevision: ...

    @property
    def active(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class NativeBridgeVerification:
    bridge_id: str
    identity_verified: bool
    version_supported: bool
    reachable: bool
    bucket_results: tuple[NativeBucketProgress, ...]


@dataclass(frozen=True, slots=True)
class NativeControlReceipt:
    capability: NativeSourceCapability
    configuration_id: str
    configuration_revision: int
    selected_bucket_count: int
    audit_id: str


@dataclass(frozen=True, slots=True)
class NativeAdmissionReceipt:
    request_id: str
    bucket_id: str
    admitted_count: int
    duplicate_count: int
    evidence_digest: str
    enrichment_proposal_count: int
    enrichment_failed: bool


@dataclass(frozen=True, slots=True)
class NativeReadPageReceipt:
    """One admitted bounded page and its private continuation cursor."""

    admission: NativeAdmissionReceipt
    authority_id: str
    next_cursor: str | None


class NativeSourceHost(Protocol):
    """The integrated protocol-v1 host boundary; implementations hold no DB access."""

    def negotiate(self, supported_versions: tuple[str, ...]) -> str: ...

    def discover(
        self, kind: NativeSourceKind, *, bridge_id: str, request_id: str, at: datetime
    ) -> Mapping[str, Any]: ...

    def preflight(
        self,
        selections: tuple[NativeBucketSelection, ...],
        *,
        bridge_id: str,
        request_id: str,
        at: datetime,
    ) -> Mapping[str, Any]: ...

    def adapter_identity(self, kind: NativeSourceKind) -> str: ...

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
    ) -> Mapping[str, Any]: ...


class NativeSourceStore(Protocol):
    """Statements required by current C use cases, with no worker/checkpoint methods."""

    def bridge_protocol(self, bridge_id: str) -> str | None: ...

    def bucket_bindings(self, bucket_ids: tuple[str, ...]) -> tuple[NativeBucketBinding, ...]: ...

    def visible_locator_pairs(
        self, bridge_id: str, source_ids: frozenset[str]
    ) -> frozenset[tuple[str, str]]: ...

    def append_configuration(
        self,
        configuration: NativeConfigurationRevision,
        *,
        expected_prior_revision: int,
        preflight: tuple[NativeBucketProgress, ...] = (),
    ) -> None: ...

    def latest_configuration(self, configuration_id: str) -> NativeConfigurationSnapshot | None: ...

    def progress(self, configuration_id: str) -> tuple[NativeBucketProgress, ...]: ...

    def record_preflight(
        self,
        configuration_id: str,
        configuration_revision: int,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None: ...

    def issue_sync_authority(
        self,
        configuration: NativeConfigurationRevision,
        binding: NativeBucketBinding,
        *,
        audit_id: str,
        request_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> NativeSyncAuthority: ...

    def prevalidate_authority(
        self, envelope: NativeAdmissionEnvelope, authority: NativeSyncAuthority, *, at: datetime
    ) -> None:
        """Validate durable replay eligibility without consuming the authority."""

    def record_admission_preflight_durably(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeSyncAuthority,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None:
        """Validate current authority and durably record an operational denial."""

    def admit_evidence_durably(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeSyncAuthority,
        preflight: tuple[NativeBucketProgress, ...],
        *,
        at: datetime,
        checkpoint_job_id: str | None = None,
        checkpoint_run_id: str | None = None,
    ) -> tuple[tuple[str, bool], ...]:
        """Atomically validate, record preflight, consume authority, and commit evidence."""


class ReviewProposalRouter(Protocol):
    """Proposal-first enrichment; this surface cannot promote canonical state."""

    def open_review_proposals(self, version_ids: tuple[str, ...]) -> tuple[str, ...]: ...


def _selection_key(selection: NativeBucketSelection) -> tuple[str, str, str]:
    return (selection.kind.value, selection.account_id, selection.bucket_id)


def _kind_for_provider(kind: NativeSourceKind) -> str:
    match kind:
        case NativeSourceKind.MAIL:
            return "apple_mail"
        case NativeSourceKind.CALENDAR:
            return "apple_calendar"
        case NativeSourceKind.CONTACTS:
            return "apple_contacts"
        case NativeSourceKind.TASKS:
            return "apple_tasks"
    assert_never(kind)


class NativeSourceController:
    """Authenticated controller for the bounded native-source capabilities."""

    def __init__(
        self,
        *,
        store: NativeSourceStore,
        host: NativeSourceHost,
        audit: AuditSink,
        proposals: ReviewProposalRouter,
    ) -> None:
        self._store = store
        self._host = host
        self._audit = audit
        self._proposals = proposals

    def _authorize(
        self,
        context: NativeRequestContext,
        capability: NativeSourceCapability,
        requested_source_ids: frozenset[str],
    ) -> str:
        decision = evaluate(
            PolicyRequest(
                principal=context.principal,
                purpose=context.purpose,
                capability=capability,
                classification=Classification.PRIVATE_LOCAL,
                requested_source_ids=requested_source_ids,
                authorized_source_ids=context.authorized_source_ids,
            )
        )
        audit_id = issue_identifier(IdKind.AUDIT)
        # Deliberately before any host call or store mutation. The durable sink
        # raises on failure, so configuration and lifecycle changes fail closed.
        self._audit.record(
            audit_event_for(
                audit_id=audit_id,
                correlation_id=context.correlation_id,
                principal_id=context.principal.principal_id,
                capability=capability,
                purpose=context.purpose,
                decision=decision,
                recorded_at=context.at,
                scope_source_id_count=len(requested_source_ids),
            )
        )
        if not decision.allowed:
            raise AdmissionDeniedError("native-source authority was denied")
        return audit_id

    def _bindings(
        self, bucket_ids: Sequence[str], bridge_id: str
    ) -> tuple[NativeBucketBinding, ...]:
        canonical = tuple(sorted(bucket_ids))
        if not canonical or len(canonical) != len(set(canonical)):
            raise ValueError("native-source scope must name unique exact buckets")
        bindings = self._store.bucket_bindings(canonical)
        if tuple(binding.bucket_id for binding in bindings) != canonical:
            raise AdmissionDeniedError("native-source scope did not resolve exactly")
        if any(binding.bridge_id != bridge_id or not binding.selectable for binding in bindings):
            raise AdmissionDeniedError("native-source scope is not selectable on this bridge")
        return bindings

    @staticmethod
    def _host_selections(
        bindings: Sequence[NativeBucketBinding],
    ) -> tuple[NativeBucketSelection, ...]:
        return tuple(
            sorted(
                (
                    NativeBucketSelection(
                        kind=binding.kind,
                        accountID=binding.account_locator,
                        bucketID=binding.bucket_locator,
                    )
                    for binding in bindings
                ),
                key=_selection_key,
            )
        )

    def _negotiate(self, bridge_id: str) -> None:
        stored = self._store.bridge_protocol(bridge_id)
        if stored != NATIVE_SOURCE_PROTOCOL_V1:
            raise AdmissionDeniedError("native-source bridge version is not registered")
        if self._host.negotiate((NATIVE_SOURCE_PROTOCOL_V1,)) != NATIVE_SOURCE_PROTOCOL_V1:
            raise AdmissionDeniedError("native-source bridge negotiation failed")

    def discover(
        self,
        context: NativeRequestContext,
        *,
        bridge_id: str,
        kind: NativeSourceKind,
        source_ids: frozenset[str],
    ) -> NativeDiscoveryEnvelope:
        self._authorize(context, NativeSourceCapability.DISCOVER, source_ids)
        self._negotiate(bridge_id)
        envelope = NativeDiscoveryEnvelope.model_validate(
            self._host.discover(
                kind, bridge_id=bridge_id, request_id=context.request_id, at=context.at
            )
        )
        if envelope.metadata.host_instance_id != bridge_id:
            raise AdmissionDeniedError("native-source bridge identity did not match")
        allowed = self._store.visible_locator_pairs(bridge_id, source_ids)
        visible_accounts = tuple(
            account
            for account in envelope.snapshot.accounts
            if any(account.id == account_locator for account_locator, _ in allowed)
        )
        visible_account_ids = {account.id for account in visible_accounts}
        visible_buckets = tuple(
            bucket
            for bucket in envelope.snapshot.buckets
            if bucket.account_id in visible_account_ids
            and (bucket.account_id, bucket.id) in allowed
        )
        return envelope.model_copy(
            update={
                "snapshot": envelope.snapshot.model_copy(
                    update={"accounts": visible_accounts, "buckets": visible_buckets}
                )
            }
        )

    def preflight(
        self,
        context: NativeRequestContext,
        *,
        bridge_id: str,
        bucket_ids: tuple[str, ...],
    ) -> NativeBridgeVerification:
        bindings = self._bindings(bucket_ids, bridge_id)
        source_ids = frozenset(binding.source_id for binding in bindings)
        self._authorize(context, NativeSourceCapability.PREFLIGHT, source_ids)
        return self._preflight_exact(context, bridge_id=bridge_id, bindings=bindings)

    def _preflight_exact(
        self,
        context: NativeRequestContext,
        *,
        bridge_id: str,
        bindings: tuple[NativeBucketBinding, ...],
    ) -> NativeBridgeVerification:
        self._negotiate(bridge_id)
        selections = self._host_selections(bindings)
        envelope = NativePreflightEnvelope.model_validate(
            self._host.preflight(
                selections,
                bridge_id=bridge_id,
                request_id=context.request_id,
                at=context.at,
            )
        )
        exact = tuple(result.selection for result in envelope.results) == selections
        identity = (
            envelope.metadata.host_instance_id == bridge_id
            and envelope.request_id == context.request_id
            and exact
        )
        by_private_locator = {
            _selection_key(result.selection): result for result in envelope.results
        }
        progress: list[NativeBucketProgress] = []
        for binding in bindings:
            result = by_private_locator.get(
                (binding.kind.value, binding.account_locator, binding.bucket_locator)
            )
            if result is None:
                raise PreflightDeniedError("native preflight omitted selected scope")
            coverage = {
                NativePreflightState.REACHABLE: NativeCoverageState.NOT_MEASURED,
                NativePreflightState.PERMISSION_DENIED: NativeCoverageState.PERMISSION_DENIED,
                NativePreflightState.UNAVAILABLE: NativeCoverageState.UNAVAILABLE,
                NativePreflightState.IDENTITY_DRIFT: NativeCoverageState.UNAVAILABLE,
            }[result.state]
            progress.append(
                NativeBucketProgress(
                    bucket_id=binding.bucket_id,
                    state=result.state.value,
                    coverage=coverage,
                    admitted_count=0,
                    failed_count=0 if result.state is NativePreflightState.REACHABLE else 1,
                    pending_count=0,
                    failure=result.failure,
                )
            )
        reachable = identity and all(
            result.state is NativePreflightState.REACHABLE for result in envelope.results
        )
        return NativeBridgeVerification(
            bridge_id=bridge_id,
            identity_verified=identity,
            version_supported=True,
            reachable=reachable,
            bucket_results=tuple(progress),
        )

    def configure(
        self,
        context: NativeRequestContext,
        configuration: NativeConfigurationRevision,
        *,
        typed_account_labels: Mapping[str, str],
        typed_bucket_labels: Mapping[str, str],
    ) -> NativeControlReceipt:
        bindings = self._bindings(configuration.selection.bucket_ids, configuration.bridge_id)
        source_ids = frozenset(binding.source_id for binding in bindings)
        audit_id = self._authorize(context, NativeSourceCapability.CONFIGURE, source_ids)
        if set(typed_account_labels) != {binding.account_id for binding in bindings}:
            raise AdmissionDeniedError("typed native account scope is incomplete")
        if set(typed_bucket_labels) != {binding.bucket_id for binding in bindings}:
            raise AdmissionDeniedError("typed native bucket scope is incomplete")
        if any(
            typed_account_labels[binding.account_id] != binding.account_label
            or typed_bucket_labels[binding.bucket_id] != binding.bucket_label
            for binding in bindings
        ):
            raise AdmissionDeniedError("typed native names do not match exact discovered identity")
        verification = self._preflight_exact(
            context, bridge_id=configuration.bridge_id, bindings=bindings
        )
        if not verification.reachable:
            raise PreflightDeniedError("native configuration preflight did not pass")
        self._store.append_configuration(
            configuration,
            expected_prior_revision=configuration.revision - 1,
            preflight=verification.bucket_results,
        )
        return NativeControlReceipt(
            capability=NativeSourceCapability.CONFIGURE,
            configuration_id=configuration.configuration_id,
            configuration_revision=configuration.revision,
            selected_bucket_count=len(bindings),
            audit_id=audit_id,
        )

    def status(
        self, context: NativeRequestContext, *, configuration_id: str
    ) -> tuple[NativeBucketProgress, ...]:
        snapshot = self._store.latest_configuration(configuration_id)
        if snapshot is None:
            raise LookupError("native configuration was not found")
        bindings = self._bindings(
            snapshot.configuration.selection.bucket_ids, snapshot.configuration.bridge_id
        )
        self._authorize(
            context,
            NativeSourceCapability.STATUS,
            frozenset(binding.source_id for binding in bindings),
        )
        return self._store.progress(configuration_id)

    def lifecycle(
        self,
        context: NativeRequestContext,
        *,
        capability: NativeSourceCapability,
        configuration_id: str,
        bucket_id: str | None = None,
    ) -> NativeControlReceipt | NativeSyncAuthority:
        allowed = {
            NativeSourceCapability.SYNC,
            NativeSourceCapability.RETRY,
            NativeSourceCapability.RECONCILE,
            NativeSourceCapability.PAUSE,
            NativeSourceCapability.RESUME,
            NativeSourceCapability.BACKFILL,
        }
        if capability not in allowed:
            raise ValueError("this capability is not a native lifecycle command")
        snapshot = self._store.latest_configuration(configuration_id)
        if snapshot is None or not snapshot.active:
            raise AdmissionDeniedError("native configuration is not active")
        configuration = snapshot.configuration
        bindings = self._bindings(configuration.selection.bucket_ids, configuration.bridge_id)
        source_ids = frozenset(binding.source_id for binding in bindings)
        audit_id = self._authorize(context, capability, source_ids)
        if capability is NativeSourceCapability.SYNC:
            verification = self._preflight_exact(
                context, bridge_id=configuration.bridge_id, bindings=bindings
            )
            if not verification.reachable:
                raise PreflightDeniedError("native sync preflight did not pass")
            self._store.record_preflight(
                configuration.configuration_id,
                configuration.revision,
                verification.bucket_results,
                observed_at=context.at,
            )
            if bucket_id is None:
                raise ValueError("native sync authority requires one exact bucket")
            binding = next((item for item in bindings if item.bucket_id == bucket_id), None)
            if binding is None:
                raise AdmissionDeniedError("native sync authority bucket is not selected")
            return self._store.issue_sync_authority(
                configuration,
                binding,
                audit_id=audit_id,
                request_id=context.request_id,
                issued_at=context.at,
                expires_at=context.at + timedelta(minutes=5),
            )
        return NativeControlReceipt(
            capability=capability,
            configuration_id=configuration.configuration_id,
            configuration_revision=configuration.revision,
            selected_bucket_count=len(bindings),
            audit_id=audit_id,
        )

    def disable(
        self,
        context: NativeRequestContext,
        *,
        configuration_id: str,
        bucket_ids: tuple[str, ...],
    ) -> NativeControlReceipt:
        snapshot = self._store.latest_configuration(configuration_id)
        if snapshot is None or not snapshot.active:
            raise AdmissionDeniedError("native configuration is not active")
        current = snapshot.configuration
        removed = frozenset(bucket_ids)
        if not removed or not removed <= set(current.selection.bucket_ids):
            raise AdmissionDeniedError("native disable scope is not selected")
        remaining = tuple(
            bucket for bucket in current.selection.bucket_ids if bucket not in removed
        )
        if not remaining:
            raise AdmissionDeniedError(
                "whole-configuration disable requires a retained scope revision"
            )
        bindings = self._bindings(current.selection.bucket_ids, current.bridge_id)
        audit_id = self._authorize(
            context,
            NativeSourceCapability.DISABLE,
            frozenset(binding.source_id for binding in bindings),
        )
        revised = NativeConfigurationRevision(
            configuration_id=current.configuration_id,
            revision=current.revision + 1,
            bridge_id=current.bridge_id,
            timezone_name=current.timezone_name,
            start_date=current.start_date,
            cutoff_at=current.cutoff_at,
            selection=ExactBucketSelection(remaining),
            created_at=context.at,
        )
        self._store.append_configuration(
            revised,
            expected_prior_revision=current.revision,
        )
        return NativeControlReceipt(
            capability=NativeSourceCapability.DISABLE,
            configuration_id=revised.configuration_id,
            configuration_revision=revised.revision,
            selected_bucket_count=len(remaining),
            audit_id=audit_id,
        )

    def admit(
        self,
        context: NativeRequestContext,
        *,
        authority: NativeSyncAuthority,
        wire_envelope: Mapping[str, Any],
        checkpoint_job_id: str | None = None,
        checkpoint_run_id: str | None = None,
    ) -> NativeAdmissionReceipt:
        if (
            not context.principal.authenticated
            or context.principal.kind is not PrincipalKind.SOURCE_PROVIDER_ADAPTER
        ):
            raise AdmissionDeniedError("native admission requires an authenticated adapter")
        envelope = NativeAdmissionEnvelope.model_validate(wire_envelope)
        if (
            envelope.metadata.host_instance_id != authority.bridge_id
            or envelope.metadata.protocol_version != NATIVE_SOURCE_PROTOCOL_V1
            or envelope.metadata.envelope_id != authority.envelope_id
            or envelope.request_id != authority.request_id
            or context.request_id != authority.request_id
        ):
            raise AdmissionDeniedError("native admission bridge identity did not match")
        bindings = self._bindings((authority.bucket_id,), authority.bridge_id)
        binding = bindings[0]
        if (
            binding.account_locator != envelope.account_id
            or binding.bucket_locator != envelope.bucket_id
            or binding.kind is not envelope.kind
            or binding.source_id != authority.source_id
        ):
            raise AdmissionDeniedError("native admission escaped its exact authorized bucket")
        try:
            self._store.prevalidate_authority(envelope, authority, at=context.at)
        except NativeAdmissionAuthorityError as exc:
            raise AdmissionDeniedError("native sync authority is stale or unauthenticated") from exc
        # The read-only durable prevalidation transaction has ended before the
        # host call, so revocation can still occur while preflight is in flight.
        # The final durable operations therefore repeat every authority/current-
        # scope/replay check while holding the same configuration and grant locks.
        verification = self._preflight_exact(
            context, bridge_id=authority.bridge_id, bindings=(binding,)
        )
        if not verification.identity_verified:
            raise PreflightDeniedError("native admission preflight identity did not match")
        if not verification.reachable:
            try:
                self._store.record_admission_preflight_durably(
                    envelope,
                    authority,
                    verification.bucket_results,
                    observed_at=context.at,
                )
            except NativeAdmissionAuthorityError as exc:
                raise AdmissionDeniedError(
                    "native sync authority is stale or unauthenticated"
                ) from exc
            raise PreflightDeniedError("native admission preflight did not pass")
        try:
            versions = self._store.admit_evidence_durably(
                envelope,
                authority,
                verification.bucket_results,
                at=context.at,
                checkpoint_job_id=checkpoint_job_id,
                checkpoint_run_id=checkpoint_run_id,
            )
        except NativeAdmissionAuthorityError as exc:
            raise AdmissionDeniedError("native sync authority is stale or unauthenticated") from exc
        version_ids = tuple(version_id for version_id, _ in versions)
        enrichment_failed = False
        proposals: tuple[str, ...] = ()
        try:
            # This port can open proposals/Review cases only. It has no promote
            # method, so consequential derived state cannot bypass Review.
            proposals = self._proposals.open_review_proposals(version_ids)
        except Exception:
            # Evidence has already committed through the explicitly durable
            # store method. Enrichment failure is reported, never rolled back
            # into loss of the source-authoritative version.
            enrichment_failed = True
        digest = sha256(
            canonical_json(
                {
                    "bridge_id": authority.bridge_id,
                    "bucket_id": binding.bucket_id,
                    "request_id": envelope.request_id,
                    "versions": version_ids,
                }
            ).encode()
        ).hexdigest()
        return NativeAdmissionReceipt(
            request_id=envelope.request_id,
            bucket_id=binding.bucket_id,
            admitted_count=sum(created for _, created in versions),
            duplicate_count=sum(not created for _, created in versions),
            evidence_digest=digest,
            enrichment_proposal_count=len(proposals),
            enrichment_failed=enrichment_failed,
        )

    def adapter_identity(self, kind: NativeSourceKind) -> str:
        """Return the bounded identity frozen into a baseline run."""
        identity = self._host.adapter_identity(kind)
        if (
            not identity
            or len(identity) > 64
            or not all(character.isalnum() or character in "._-" for character in identity)
        ):
            raise AdmissionDeniedError("native-source adapter identity is invalid")
        return identity

    def read_and_admit_page(
        self,
        control_context: NativeRequestContext,
        admission_context: NativeRequestContext,
        *,
        configuration_id: str,
        bucket_id: str,
        time_range: tuple[datetime, datetime] | None,
        cursor: str | None,
        limit: int = NATIVE_SOURCE_MAX_PAGE_SIZE,
        checkpoint_job_id: str | None = None,
        checkpoint_run_id: str | None = None,
    ) -> NativeReadPageReceipt:
        """Read and durably admit one exact page under a fresh sync grant."""
        if control_context.request_id != admission_context.request_id:
            raise AdmissionDeniedError("native page contexts do not name one request")
        if not 1 <= limit <= NATIVE_SOURCE_MAX_PAGE_SIZE:
            raise ValueError("native-source page limit is outside the frozen bound")
        if time_range is not None:
            start, end = (ensure_utc(value) for value in time_range)
            if start > end:
                raise ValueError("native-source page range is not ordered")
            time_range = (start, end)
        authority = self.lifecycle(
            control_context,
            capability=NativeSourceCapability.SYNC,
            configuration_id=configuration_id,
            bucket_id=bucket_id,
        )
        if not isinstance(authority, NativeSyncAuthority):
            raise RuntimeError("native sync did not issue page authority")
        binding = self._bindings((bucket_id,), authority.bridge_id)[0]
        wire = self._host.read(
            self._host_selections((binding,))[0],
            time_range=time_range,
            cursor=cursor,
            limit=limit,
            bridge_id=authority.bridge_id,
            envelope_id=authority.envelope_id,
            request_id=control_context.request_id,
            at=control_context.at,
        )
        envelope = NativeAdmissionEnvelope.model_validate(wire)
        admission = self.admit(
            admission_context,
            authority=authority,
            wire_envelope=wire,
            checkpoint_job_id=checkpoint_job_id,
            checkpoint_run_id=checkpoint_run_id,
        )
        return NativeReadPageReceipt(
            admission=admission,
            authority_id=authority.authority_id,
            next_cursor=envelope.next_cursor,
        )
