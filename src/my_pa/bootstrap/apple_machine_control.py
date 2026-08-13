"""Composition-level database implementation of the two Apple machine operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, func, select, update

from my_pa.application.apple_machine import AppleBridgeIdentity
from my_pa.application.native_sources import NativeRequestContext, NativeSourceController
from my_pa.contracts.v1.native_sources import AppleReadGrant, NativeBucketSelection
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.native_sources import SqlNativeSourceControlStore
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.tables import (
    native_admission_authorities,
    native_apple_read_grants,
    native_configuration_revisions,
    native_source_accounts,
    native_source_buckets,
)

__all__ = ["SqlAppleMachineControl"]


class SqlAppleMachineControl:
    """Poll persisted grants and admit through the existing locked controller path."""

    def __init__(self, engine: Engine, controller_factory: Any) -> None:  # noqa: ANN401
        self._engine = engine
        self._controller_factory = controller_factory

    def _store(self, identity: AppleBridgeIdentity) -> SqlNativeSourceControlStore:
        return SqlNativeSourceControlStore(self._engine, capture_context(identity.principal_id))

    def poll(self, identity: AppleBridgeIdentity) -> Mapping[str, Any] | None:
        store = self._store(identity)
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = connection.execute(
                select(
                    native_admission_authorities,
                    native_apple_read_grants,
                    native_source_accounts.c.private_locator.label("account_locator"),
                    native_source_buckets.c.private_locator.label("bucket_locator"),
                    native_source_buckets.c.source_kind,
                )
                .join(
                    native_apple_read_grants,
                    native_apple_read_grants.c.authority_id
                    == native_admission_authorities.c.authority_id,
                )
                .join(
                    native_source_buckets,
                    native_source_buckets.c.bucket_id == native_admission_authorities.c.bucket_id,
                )
                .join(
                    native_source_accounts,
                    native_source_accounts.c.account_id == native_source_buckets.c.account_id,
                )
                .where(
                    native_admission_authorities.c.bridge_id == identity.bridge_id,
                    native_admission_authorities.c.expires_at >= now,
                    native_admission_authorities.c.consumed_at.is_(None),
                    native_admission_authorities.c.configuration_revision
                    == select(func.max(native_configuration_revisions.c.revision))
                    .where(
                        native_configuration_revisions.c.configuration_id
                        == native_admission_authorities.c.configuration_id,
                        store._mine(native_configuration_revisions),
                    )
                    .scalar_subquery(),
                    (
                        native_apple_read_grants.c.delivery_lease_expires_at.is_(None)
                        | (native_apple_read_grants.c.delivery_lease_expires_at <= now)
                    ),
                    store._mine(native_admission_authorities),
                    store._mine(native_apple_read_grants),
                    store._mine(native_source_accounts),
                    store._mine(native_source_buckets),
                )
                .order_by(native_apple_read_grants.c.staged_at)
                .limit(1)
                .with_for_update(of=native_apple_read_grants, skip_locked=True)
            ).one_or_none()
            if row is None:
                return None
            value = row._mapping
            grant = AppleReadGrant(
                schema="my-pa.apple-source-read-grant.v1",
                authorityID=value["authority_id"],
                principalID=identity.principal_id,
                configurationID=value["configuration_id"],
                configurationRevision=value["configuration_revision"],
                bridgeID=value["bridge_id"],
                requestID=value["request_id"],
                envelopeID=value["envelope_id"],
                selection=NativeBucketSelection(
                    kind=value["source_kind"],
                    accountID=value["account_locator"],
                    bucketID=value["bucket_locator"],
                ),
                authorization="AUTHORIZED_LIVE_PERSONAL_DATA_READ",
                expiresAtUnixMilliseconds=int(value["expires_at"].timestamp() * 1_000),
                pageLimit=value["page_limit"],
                timeRangeStartUnixMilliseconds=value["range_start_unix_milliseconds"],
                timeRangeEndUnixMilliseconds=value["range_end_unix_milliseconds"],
                cursor=value["cursor_private"],
            )
            claimed = connection.execute(
                update(native_apple_read_grants)
                .where(
                    native_apple_read_grants.c.authority_id == grant.authority_id,
                    (
                        native_apple_read_grants.c.delivery_lease_expires_at.is_(None)
                        | (native_apple_read_grants.c.delivery_lease_expires_at <= now)
                    ),
                    store._mine(native_apple_read_grants),
                )
                .values(
                    delivered_at=now,
                    # The Mac host process is bounded at 120 seconds. The lease
                    # covers that whole execution window, then permits recovery
                    # before the five-minute grant itself expires.
                    delivery_lease_expires_at=now + timedelta(minutes=2),
                    delivered_to_credential_id=identity.credential_id,
                )
            )
            if claimed.rowcount != 1:
                return None
            return grant.model_dump(mode="json", by_alias=True)

    def admit(
        self, identity: AppleBridgeIdentity, document: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        authority_id = document.get("authorityID")
        envelope = document.get("envelope")
        if not isinstance(authority_id, str) or not isinstance(envelope, Mapping):
            raise ValueError("Apple admission requires exact authority and envelope")
        store = self._store(identity)
        metadata = envelope.get("metadata", {})
        envelope_id = metadata.get("envelopeID", "") if isinstance(metadata, Mapping) else ""
        authority = store.authority_for_envelope(str(envelope_id))
        if (
            authority is None
            or authority.authority_id != authority_id
            or authority.bridge_id != identity.bridge_id
        ):
            raise ValueError("Apple admission authority did not match")
        controller: NativeSourceController = self._controller_factory(store)
        context = NativeRequestContext(
            principal=Principal(identity.principal_id, PrincipalKind.SOURCE_PROVIDER_ADAPTER, True),
            purpose=Purpose.SOURCE_INSPECTION,
            correlation_id="corr_0000000000000001",
            request_id=authority.request_id,
            authorized_source_ids=frozenset({authority.source_id}),
            at=datetime.now(UTC),
        )
        return controller.admit_remote(
            context, authority=authority, wire_envelope=envelope
        ).model_dump(mode="json", by_alias=True)
