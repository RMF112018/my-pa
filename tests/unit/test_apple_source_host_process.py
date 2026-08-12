from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pytest import MonkeyPatch

from my_pa.contracts.v1.native_sources import (
    NATIVE_SOURCE_PROTOCOL_V1,
    NativeAdmissionEnvelope,
    NativeBucketSelection,
    NativeSourceKind,
)
from my_pa.infrastructure.apple_source_host import AppleSourceHostProcess


def test_process_adapter_preserves_exact_authority_identity(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    executable = tmp_path / "apple-source-host"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o700)
    observed_grant: dict[str, object] = {}

    def run(arguments: tuple[str, ...], **_: object) -> subprocess.CompletedProcess[bytes]:
        if arguments[1:3] == ("probe", "--preflight"):
            bridge = arguments[arguments.index("--bridge-id") + 1]
            request = arguments[arguments.index("--request-id") + 1]
            configuration = json.loads(
                Path(arguments[arguments.index("--configuration") + 1]).read_text()
            )
            output = {
                "metadata": {
                    "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
                    "envelopeID": request,
                    "hostInstanceID": bridge,
                    "emittedAtUnixMilliseconds": 0,
                },
                "requestID": request,
                "results": [{"selection": configuration["selections"][0], "state": "reachable"}],
            }
            return subprocess.CompletedProcess(arguments, 0, json.dumps(output).encode(), b"")

        grant_path = Path(arguments[arguments.index("--authorization-grant") + 1])
        observed_grant.update(json.loads(grant_path.read_text()))
        spool = Path(arguments[arguments.index("--spool-directory") + 1]) / "pending"
        spool.mkdir(parents=True)
        envelope = {
            "metadata": {
                "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
                "envelopeID": observed_grant["envelopeID"],
                "hostInstanceID": observed_grant["bridgeID"],
                "emittedAtUnixMilliseconds": 0,
            },
            "requestID": observed_grant["requestID"],
            "kind": observed_grant["kind"],
            "accountID": observed_grant["accountID"],
            "bucketID": observed_grant["bucketID"],
            "records": [],
            "nextCursor": None,
        }
        outer = {
            "envelopeID": observed_grant["envelopeID"],
            "kind": observed_grant["kind"],
            "accountID": observed_grant["accountID"],
            "bucketID": observed_grant["bucketID"],
            "payload": list(json.dumps(envelope, separators=(",", ":")).encode()),
        }
        (spool / f"{observed_grant['envelopeID']}.pending").write_text(
            json.dumps(outer), encoding="utf-8"
        )
        return subprocess.CompletedProcess(arguments, 0, b"{}", b"")

    monkeypatch.setattr("my_pa.infrastructure.apple_source_host.subprocess.run", run)
    process = AppleSourceHostProcess(
        executable=executable,
        contacts_identity_epoch="contacts-epoch",
        mail_generation="mail-generation",
    )
    selection = NativeBucketSelection(
        kind=NativeSourceKind.CALENDAR,
        accountID="private-account",
        bucketID="private-bucket",
    )
    at = datetime(2026, 8, 12, tzinfo=UTC)

    preflight = process.preflight(
        (selection,), bridge_id="bridge-issued", request_id="request-issued", at=at
    )
    assert preflight["metadata"]["hostInstanceID"] == "bridge-issued"
    assert preflight["requestID"] == "request-issued"

    wire = process.read(
        selection,
        time_range=None,
        cursor=None,
        limit=1,
        bridge_id="bridge-issued",
        request_id="request-issued",
        envelope_id="envelope-issued",
        at=at,
    )
    envelope = NativeAdmissionEnvelope.model_validate(wire)
    assert envelope.metadata.host_instance_id == "bridge-issued"
    assert envelope.request_id == "request-issued"
    assert envelope.metadata.envelope_id == "envelope-issued"
    assert observed_grant["accountID"] == "private-account"
    assert observed_grant["bucketID"] == "private-bucket"
