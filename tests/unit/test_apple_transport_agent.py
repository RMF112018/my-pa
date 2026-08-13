from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from my_pa.application.apple_machine import (
    AppleBridgeCredentialBinding,
    AppleMachineCredentialError,
    authenticate_apple_bridge,
)
from my_pa.contracts.v1.base import canonical_json
from my_pa.contracts.v1.native_sources import (
    AppleReadGrant,
    NativeAdmissionEnvelope,
    NativeBucketSelection,
)
from my_pa.infrastructure.apple_transport_agent import (
    AppleGrantJournal,
    AppleTransportAgent,
    AppleTransportError,
)

NOW = datetime(2026, 8, 12, 20, tzinfo=UTC)
BRIDGE = "nbrg_0000000000000001"
PRINCIPAL = "prn_0000000000000001"
AUTHORITY = "nauth_0000000000000001"
ENVELOPE = "nauth_0000000000000001"


def grant(**changes: object) -> dict[str, Any]:
    value = AppleReadGrant(
        schema="my-pa.apple-source-read-grant.v1",
        authorityID=AUTHORITY,
        principalID=PRINCIPAL,
        configurationID="ncfg_0000000000000001",
        configurationRevision=1,
        bridgeID=BRIDGE,
        requestID="request-00000001",
        envelopeID=ENVELOPE,
        selection=NativeBucketSelection(
            kind="calendar", accountID="account-1", bucketID="bucket-1"
        ),
        authorization="AUTHORIZED_LIVE_PERSONAL_DATA_READ",
        expiresAtUnixMilliseconds=int((NOW + timedelta(minutes=5)).timestamp() * 1_000),
        pageLimit=1,
        timeRangeStartUnixMilliseconds=int((NOW - timedelta(days=1)).timestamp() * 1_000),
        timeRangeEndUnixMilliseconds=int(NOW.timestamp() * 1_000),
    ).model_dump(mode="json", by_alias=True)
    value.update(changes)
    return value


class Host:
    def __init__(self) -> None:
        self.acknowledged: list[str] = []
        self.pending_flag = False
        self.envelope: dict[str, Any] | None = None
        self.read_count = 0

    def read(self, selection: NativeBucketSelection, *, grant: AppleReadGrant) -> dict[str, Any]:
        self.pending_flag = True
        self.read_count += 1
        self.envelope = {
            "metadata": {
                "protocolVersion": "my-pa.native-source.v1",
                "envelopeID": grant.envelope_id,
                "hostInstanceID": grant.bridge_id,
                "emittedAtUnixMilliseconds": int(NOW.timestamp() * 1_000),
            },
            "requestID": grant.request_id,
            "kind": selection.kind.value,
            "accountID": selection.account_id,
            "bucketID": selection.bucket_id,
            "records": [],
            "nextCursor": None,
        }
        return self.envelope

    def pending(self, selection: NativeBucketSelection) -> dict[str, Any] | None:
        del selection
        return self.envelope if self.pending_flag else None

    def acknowledge(self, envelope_id: str) -> None:
        self.acknowledged.append(envelope_id)
        self.pending_flag = False


class Client:
    def __init__(self, receipt_changes: dict[str, object] | None = None) -> None:
        self.receipt_changes = receipt_changes or {}
        self.fail_admit = False

    def poll(self, credential: str) -> dict[str, Any]:
        assert credential == "synthetic-credential"
        return grant()

    def admit(self, credential: str, authority_id: str, envelope: dict[str, Any]) -> dict[str, Any]:
        del credential
        if self.fail_admit:
            raise OSError("synthetic NAS outage")
        admission_digest = sha256(
            canonical_json(
                NativeAdmissionEnvelope.model_validate(envelope).model_dump(
                    mode="json", by_alias=True
                )
            ).encode()
        ).hexdigest()
        receipt: dict[str, Any] = {
            "schema": "my-pa.apple-admission-receipt.v1",
            "principalID": PRINCIPAL,
            "bridgeID": BRIDGE,
            "authorityID": authority_id,
            "requestID": "request-00000001",
            "envelopeID": ENVELOPE,
            "admissionDigest": admission_digest,
        }
        receipt.update(self.receipt_changes)
        return receipt


def agent(
    host: Host,
    client: Client,
    journal: AppleGrantJournal,
    *,
    environment: dict[str, str] | None = None,
) -> AppleTransportAgent:
    return AppleTransportAgent(
        principal_id=PRINCIPAL,
        bridge_id=BRIDGE,
        credential="synthetic-credential",
        client=client,
        host=host,  # type: ignore[arg-type] - exact small process fake
        journal=journal,
        environment=environment or {},
    )


def journal(tmp_path: Path) -> AppleGrantJournal:
    directory = tmp_path / "grant-journal"
    directory.mkdir(mode=0o700)
    return AppleGrantJournal(directory)


def test_exact_receipt_is_the_only_event_that_acknowledges_the_spool(tmp_path: Path) -> None:
    host = Host()
    assert agent(host, Client(), journal(tmp_path)).run_once(at=NOW)
    assert host.acknowledged == [ENVELOPE]
    assert not host.pending_flag


@pytest.mark.parametrize(
    "changes",
    [
        {"authorization": "FORGED"},
        {"principalID": "prn_0000000000000002"},
        {"bridgeID": "nbrg_0000000000000002"},
        {"expiresAtUnixMilliseconds": int((NOW - timedelta(seconds=1)).timestamp() * 1_000)},
    ],
)
def test_forged_wrong_bridge_and_expired_grants_never_execute(
    changes: dict[str, object], tmp_path: Path
) -> None:
    host = Host()

    class GrantClient(Client):
        def poll(self, credential: str) -> dict[str, Any]:
            del credential
            return grant(**changes)

    with pytest.raises(AppleTransportError):
        agent(host, GrantClient(), journal(tmp_path)).run_once(at=NOW)
    assert host.read_count == 0
    assert host.acknowledged == []


@pytest.mark.parametrize(
    ("changes"),
    [
        {"principalID": "prn_0000000000000002"},
        {"bridgeID": "nbrg_0000000000000002"},
        {"authorityID": "nauth_0000000000000002"},
        {"requestID": "request-00000002"},
        {"envelopeID": "envelope-wrong"},
        {"admissionDigest": "0" * 64},
    ],
)
def test_receipt_mismatch_leaves_the_spool_pending(
    changes: dict[str, object], tmp_path: Path
) -> None:
    host = Host()
    with pytest.raises(AppleTransportError):
        agent(host, Client(changes), journal(tmp_path)).run_once(at=NOW)
    assert host.pending_flag
    assert host.acknowledged == []


def test_nas_outage_leaves_the_spool_pending_for_recovery(tmp_path: Path) -> None:
    host = Host()
    client = Client()
    retained = journal(tmp_path)
    client.fail_admit = True
    with pytest.raises(OSError):
        agent(host, client, retained).run_once(at=NOW)
    assert host.pending_flag
    assert host.acknowledged == []

    client.fail_admit = False
    assert agent(host, client, retained).run_once(at=NOW + timedelta(minutes=10))
    assert host.acknowledged == [ENVELOPE]


def test_restart_after_spool_ack_does_not_execute_the_grant_again(tmp_path: Path) -> None:
    directory = tmp_path / "grant-journal"
    directory.mkdir(mode=0o700)

    class CrashAfterAck(AppleGrantJournal):
        def remove(self, envelope_id: str) -> None:
            del envelope_id
            raise OSError("synthetic crash after durable spool acknowledgement")

    host = Host()
    with pytest.raises(OSError):
        agent(host, Client(), CrashAfterAck(directory)).run_once(at=NOW)
    assert host.read_count == 1
    assert not host.pending_flag

    assert agent(host, Client(), AppleGrantJournal(directory)).run_once(
        at=NOW + timedelta(minutes=10)
    )
    assert host.read_count == 1


def test_mac_environment_refuses_database_authority(tmp_path: Path) -> None:
    with pytest.raises(AppleTransportError):
        agent(
            Host(),
            Client(),
            journal(tmp_path),
            environment={"MY_PA_DATABASE_URL": "synthetic-forbidden"},
        )


def test_dedicated_credential_refuses_wrong_scheme_secret_and_bridge() -> None:
    binding = AppleBridgeCredentialBinding(
        credential_id="abcred_0000000000000001",
        principal_id=PRINCIPAL,
        bridge_id=BRIDGE,
        secret_sha256=sha256(b"synthetic-secret").hexdigest(),
    )
    identity = authenticate_apple_bridge(
        "AppleBridgeCredential abcred_0000000000000001:synthetic-secret", binding
    )
    assert identity.principal_id == PRINCIPAL
    for credential in (
        "Bearer abcred_0000000000000001:synthetic-secret",
        "AppleBridgeCredential abcred_0000000000000001:wrong",
        "AppleBridgeCredential abcred_0000000000000002:synthetic-secret",
    ):
        with pytest.raises(AppleMachineCredentialError):
            authenticate_apple_bridge(credential, binding)
