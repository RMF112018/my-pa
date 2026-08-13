"""Process boundary to the source-built Apple host executable.

The Python application issues the authority identity. This adapter transports
that exact identity into the Swift grant, consumes exactly one protected spool
item, and returns its inner admission envelope to authenticated application admission.
It never requests TCC and has no source mutation operation.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from my_pa.contracts.v1.native_sources import (
    NATIVE_SOURCE_PROTOCOL_V1,
    AppleReadGrant,
    NativeBucketSelection,
    NativeSourceKind,
)
from my_pa.domain.common.time import ensure_utc

_MAXIMUM_OUTPUT_BYTES = 1_048_576


class AppleSourceHostError(RuntimeError):
    """The bounded native host refused or returned an invalid artifact."""


class AppleSourceHostProcess:
    """Production ``NativeSourceHost`` adapter for one explicit executable."""

    def __init__(
        self,
        *,
        executable: Path,
        spool_directory: Path,
        contacts_identity_epoch: str,
        mail_generation: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        resolved = executable.resolve(strict=True)
        if not resolved.is_file() or not resolved.is_absolute() or not os.access(resolved, os.X_OK):
            raise ValueError("the Apple source host must be an absolute executable")
        if not contacts_identity_epoch or not mail_generation:
            raise ValueError("Apple host identity configuration is required")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("the Apple host timeout is outside its bound")
        self._executable = resolved
        if not spool_directory.is_absolute() or spool_directory.is_symlink():
            raise ValueError("the Apple spool must be an absolute existing directory")
        spool = spool_directory.resolve(strict=True)
        if not spool.is_dir():
            raise ValueError("the Apple spool must be an absolute existing directory")
        if spool.stat().st_mode & 0o077:
            raise ValueError("the Apple spool must be owner-only")
        self._spool = spool
        self._contacts_identity_epoch = contacts_identity_epoch
        self._mail_generation = mail_generation
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def negotiate(supported_versions: tuple[str, ...]) -> str:
        if NATIVE_SOURCE_PROTOCOL_V1 not in supported_versions:
            raise AppleSourceHostError("the Apple host protocol is unsupported")
        return NATIVE_SOURCE_PROTOCOL_V1

    def discover(
        self,
        kind: NativeSourceKind,
        *,
        bridge_id: str,
        request_id: str,
        at: datetime,
    ) -> Mapping[str, Any]:
        del at
        dummy = NativeBucketSelection(
            kind=kind,
            accountID="probe-account",
            bucketID="probe-bucket",
        )
        with tempfile.TemporaryDirectory(prefix="my-pa-apple-probe-") as temporary:
            root = Path(temporary)
            configuration = root / "configuration.json"
            self._write_json(configuration, self._configuration((dummy,), active=False))
            return self._invoke_json(
                "probe",
                "--discover",
                "--configuration",
                str(configuration),
                "--bridge-id",
                bridge_id,
                "--request-id",
                request_id,
                "--kind",
                kind.value,
            )

    def preflight(
        self,
        selections: tuple[NativeBucketSelection, ...],
        *,
        bridge_id: str,
        request_id: str,
        at: datetime,
    ) -> Mapping[str, Any]:
        del at
        with tempfile.TemporaryDirectory(prefix="my-pa-apple-preflight-") as temporary:
            root = Path(temporary)
            configuration = root / "configuration.json"
            self._write_json(configuration, self._configuration(selections, active=False))
            return self._invoke_json(
                "probe",
                "--preflight",
                "--configuration",
                str(configuration),
                "--bridge-id",
                bridge_id,
                "--request-id",
                request_id,
            )

    @staticmethod
    def adapter_identity(kind: NativeSourceKind) -> str:
        return f"apple-source-host-v1-{kind.value}"

    def read(
        self,
        selection: NativeBucketSelection,
        *,
        grant: AppleReadGrant,
    ) -> Mapping[str, Any]:
        if grant.selection != selection:
            raise AppleSourceHostError("the Apple grant selection did not match")
        configuration_id = grant.configuration_id
        envelope_id = grant.envelope_id
        with tempfile.TemporaryDirectory(prefix="my-pa-apple-read-") as temporary:
            root = Path(temporary)
            configuration = root / "configuration.json"
            grant_path = root / "grant.json"
            checkpoint = root / "checkpoint.json"
            pending = self._spool / "pending" / f"{envelope_id}.pending"
            if pending.exists():
                return self._decode_pending(pending, selection, envelope_id)
            self._write_json(
                configuration,
                self._configuration((selection,), active=True, identifier=configuration_id),
            )
            wire_grant = grant.model_dump(by_alias=True, mode="json")
            # Swift protocol-v1 predates the remote wrapper fields. Translate the
            # NAS-issued contract; never synthesize authority identity here.
            wire_grant.update(
                {
                    "kind": selection.kind.value,
                    "accountID": selection.account_id,
                    "bucketID": selection.bucket_id,
                    "timeRange": {
                        "startUnixMilliseconds": wire_grant.pop("timeRangeStartUnixMilliseconds"),
                        "endUnixMilliseconds": wire_grant.pop("timeRangeEndUnixMilliseconds"),
                    },
                }
            )
            wire_grant.pop("selection")
            wire_grant.pop("authorityID")
            wire_grant.pop("principalID")
            wire_grant.pop("configurationRevision")
            cursor = wire_grant.pop("cursor")
            self._write_json(grant_path, wire_grant)
            arguments = [
                "handoff",
                "--authorized-single-pass",
                "--configuration",
                str(configuration),
                "--spool-directory",
                str(self._spool),
                "--maximum-spool-items",
                "1",
                "--maximum-spool-bytes",
                str(67_108_864),
                "--maximum-payload-bytes",
                str(_MAXIMUM_OUTPUT_BYTES),
                "--authorization-grant",
                str(grant_path),
            ]
            if cursor is not None:
                self._write_json(
                    checkpoint,
                    {
                        "configurationID": configuration_id,
                        "kind": selection.kind.value,
                        "bucketID": selection.bucket_id,
                        "cursor": cursor,
                    },
                )
                arguments.extend(("--checkpoint", str(checkpoint)))
            self._invoke_json(*arguments)
            return self._decode_pending(pending, selection, envelope_id)

    def _decode_pending(
        self,
        pending: Path,
        selection: NativeBucketSelection,
        envelope_id: str,
    ) -> dict[str, Any]:
        outer = self._read_json_no_follow(pending)
        if (
            outer.get("envelopeID") != envelope_id
            or outer.get("kind") != selection.kind.value
            or outer.get("accountID") != selection.account_id
            or outer.get("bucketID") != selection.bucket_id
        ):
            raise AppleSourceHostError("the Apple spool identity did not match")
        payload = outer.get("payload")
        if not isinstance(payload, list) or len(payload) > _MAXIMUM_OUTPUT_BYTES:
            raise AppleSourceHostError("the Apple spool payload is invalid")
        try:
            decoded = bytes(payload)
            envelope = json.loads(decoded)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise AppleSourceHostError("the Apple admission envelope is invalid") from error
        if not isinstance(envelope, dict):
            raise AppleSourceHostError("the Apple admission envelope is invalid")
        return envelope

    def acknowledge(self, envelope_id: str) -> None:
        """Ask the Swift spool implementation to durably acknowledge one item."""
        self._invoke_json(
            "spool",
            "--acknowledge",
            "--spool-directory",
            str(self._spool),
            "--envelope-id",
            envelope_id,
            "--maximum-spool-items",
            "1",
            "--maximum-spool-bytes",
            str(67_108_864),
            "--maximum-payload-bytes",
            str(_MAXIMUM_OUTPUT_BYTES),
        )

    def pending(self, selection: NativeBucketSelection) -> Mapping[str, Any] | None:
        """Recover the sole retained item when it belongs to the exact selection."""
        directory = self._spool / "pending"
        if not directory.exists():
            return None
        entries = tuple(directory.iterdir())
        if not entries:
            return None
        if len(entries) != 1 or entries[0].suffix != ".pending":
            raise AppleSourceHostError("the Apple spool inventory is invalid")
        envelope_id = entries[0].name.removesuffix(".pending")
        return self._decode_pending(entries[0], selection, envelope_id)

    def quarantine(self, envelope_id: str) -> None:
        """Preserve a stale retained item outside the pending capacity."""
        self._invoke_json(
            "spool",
            "--quarantine",
            "--spool-directory",
            str(self._spool),
            "--envelope-id",
            envelope_id,
            "--maximum-spool-items",
            "1",
            "--maximum-spool-bytes",
            str(67_108_864),
            "--maximum-payload-bytes",
            str(_MAXIMUM_OUTPUT_BYTES),
        )

    def _configuration(
        self,
        selections: tuple[NativeBucketSelection, ...],
        *,
        active: bool,
        identifier: str = "apple-host-probe",
    ) -> dict[str, object]:
        return {
            "schema": "my-pa.apple-source-host.v1",
            "configurationID": identifier,
            "protocolVersion": NATIVE_SOURCE_PROTOCOL_V1,
            "contactsIdentityEpoch": self._contacts_identity_epoch,
            "mailGeneration": self._mail_generation,
            "selections": [
                selection.model_dump(by_alias=True, mode="json") for selection in selections
            ],
            "activationRequested": active,
        }

    def _invoke_json(self, *arguments: str) -> Mapping[str, Any]:
        try:
            completed = subprocess.run(  # noqa: S603 - exact executable and argv, no shell
                (str(self._executable), *arguments),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
                timeout=self._timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise AppleSourceHostError("the Apple source host was unavailable") from error
        if completed.returncode != 0 or len(completed.stdout) > _MAXIMUM_OUTPUT_BYTES:
            raise AppleSourceHostError("the Apple source host refused")
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise AppleSourceHostError("the Apple source host returned invalid JSON") from error
        if not isinstance(value, dict):
            raise AppleSourceHostError("the Apple source host returned invalid JSON")
        return value

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            data = json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            if len(data) > 262_144:
                raise AppleSourceHostError("the Apple host input is outside its bound")
            remaining = memoryview(data)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise AppleSourceHostError("the Apple host input could not be written")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _read_json_no_follow(path: Path) -> dict[str, Any]:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            chunks: list[bytes] = []
            observed = 0
            while observed <= _MAXIMUM_OUTPUT_BYTES:
                chunk = os.read(
                    descriptor,
                    min(65_536, _MAXIMUM_OUTPUT_BYTES + 1 - observed),
                )
                if not chunk:
                    break
                chunks.append(chunk)
                observed += len(chunk)
        finally:
            os.close(descriptor)
        data = b"".join(chunks)
        if len(data) > _MAXIMUM_OUTPUT_BYTES:
            raise AppleSourceHostError("the Apple spool item is outside its bound")
        try:
            value = json.loads(data)
        except json.JSONDecodeError as error:
            raise AppleSourceHostError("the Apple spool item is invalid") from error
        if not isinstance(value, dict):
            raise AppleSourceHostError("the Apple spool item is invalid")
        return value

    @staticmethod
    def _milliseconds(value: datetime) -> int:
        return int(ensure_utc(value).timestamp() * 1_000)
