"""Outbound-only, restart-safe transport for NAS-issued Apple grants."""

from __future__ import annotations

import json
import os
import ssl
import tempfile
from collections.abc import Mapping
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from my_pa.contracts.v1.base import canonical_json
from my_pa.contracts.v1.native_sources import (
    AppleAdmissionReceipt,
    AppleReadGrant,
    NativeAdmissionEnvelope,
)
from my_pa.domain.common.time import ensure_utc
from my_pa.infrastructure.apple_source_host import AppleSourceHostProcess

__all__ = [
    "AppleControlClient",
    "AppleGrantJournal",
    "AppleTransportAgent",
    "AppleTransportError",
    "HttpsAppleControlClient",
]

_POLL_PATH = "/apple/v1/grant.poll"
_ADMIT_PATH = "/apple/v1/envelope.admit"
_MAXIMUM_RECEIPT_BYTES = 65_536


class AppleTransportError(RuntimeError):
    """A grant, environment, envelope, transport, or receipt failed closed."""


class AppleControlClient(Protocol):
    def poll(self, credential: str) -> Mapping[str, Any] | None: ...

    def admit(
        self, credential: str, authority_id: str, envelope: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...


class HttpsAppleControlClient:
    """Concrete standard-library HTTPS client for the two frozen NAS routes."""

    def __init__(self, origin: str, *, timeout_seconds: float = 30.0) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "the Apple control origin must be an exact credential-free HTTPS origin"
            )
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("the Apple control timeout is outside its bound")
        self._origin = origin.rstrip("/")
        self._timeout = timeout_seconds
        self._tls = ssl.create_default_context()

    def _post(
        self, path: str, credential: str, document: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        body = canonical_json(document).encode()
        request = Request(  # noqa: S310 - constructor receives a validated exact HTTPS origin
            self._origin + path,
            data=body,
            method="POST",
            headers={
                "Authorization": f"AppleBridgeCredential {credential}",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        try:
            with urlopen(request, timeout=self._timeout, context=self._tls) as response:  # noqa: S310 - exact validated HTTPS origin
                if response.status == 204:
                    return None
                received = response.read(_MAXIMUM_RECEIPT_BYTES + 1)
        except HTTPError as error:
            raise AppleTransportError(
                f"Apple control request was refused with HTTP {error.code}"
            ) from error
        if len(received) > _MAXIMUM_RECEIPT_BYTES:
            raise AppleTransportError("the Apple control response exceeded its bound")
        try:
            value = json.loads(received)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise AppleTransportError("the Apple control response was invalid") from error
        if not isinstance(value, dict):
            raise AppleTransportError("the Apple control response was invalid")
        return value

    def poll(self, credential: str) -> Mapping[str, Any] | None:
        return self._post(_POLL_PATH, credential, {})

    def admit(
        self, credential: str, authority_id: str, envelope: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        value = self._post(
            _ADMIT_PATH,
            credential,
            {"authorityID": authority_id, "envelope": envelope},
        )
        if value is None:
            raise AppleTransportError("the NAS omitted the durable admission receipt")
        return value


class AppleGrantJournal:
    """Owner-only durable grant metadata paired with the protected Swift spool."""

    def __init__(self, directory: Path) -> None:
        if not directory.is_absolute() or directory.is_symlink():
            raise ValueError("the Apple grant journal must be an absolute directory")
        resolved = directory.resolve(strict=True)
        if not resolved.is_dir() or resolved.stat().st_mode & 0o077:
            raise ValueError("the Apple grant journal must be owner-only")
        self._directory = resolved

    def _sync_directory(self) -> None:
        descriptor = os.open(self._directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def load(self) -> AppleReadGrant | None:
        entries = tuple(self._directory.glob("*.grant.json"))
        if not entries:
            return None
        if len(entries) != 1 or entries[0].is_symlink():
            raise AppleTransportError("the Apple grant journal inventory is invalid")
        try:
            wire = json.loads(entries[0].read_bytes())
            return AppleReadGrant.model_validate(wire)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise AppleTransportError("the retained Apple grant is invalid") from error

    def save(self, grant: AppleReadGrant) -> None:
        if self.load() is not None:
            raise AppleTransportError("an Apple grant is already pending")
        payload = canonical_json(grant.model_dump(mode="json", by_alias=True)).encode()
        target = self._directory / f"{grant.envelope_id}.grant.json"
        descriptor, temporary = tempfile.mkstemp(prefix=".grant-", dir=self._directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(target)
            self._sync_directory()
        finally:
            temporary_path = Path(temporary)
            if temporary_path.exists():
                temporary_path.unlink()

    def verified_receipt(self, grant: AppleReadGrant) -> AppleAdmissionReceipt | None:
        target = self._directory / f"{grant.envelope_id}.receipt.json"
        if not target.exists():
            return None
        if target.is_symlink() or not target.is_file():
            raise AppleTransportError("the retained Apple receipt identity changed")
        try:
            receipt = AppleAdmissionReceipt.model_validate(json.loads(target.read_bytes()))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise AppleTransportError("the retained Apple receipt is invalid") from error
        if (
            receipt.principal_id != grant.principal_id
            or receipt.bridge_id != grant.bridge_id
            or receipt.authority_id != grant.authority_id
            or receipt.request_id != grant.request_id
            or receipt.envelope_id != grant.envelope_id
        ):
            raise AppleTransportError("the retained Apple receipt identity changed")
        return receipt

    def save_receipt(self, receipt: AppleAdmissionReceipt) -> None:
        target = self._directory / f"{receipt.envelope_id}.receipt.json"
        payload = canonical_json(receipt.model_dump(mode="json", by_alias=True)).encode()
        descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", dir=self._directory)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            Path(temporary).replace(target)
            self._sync_directory()
        finally:
            temporary_path = Path(temporary)
            if temporary_path.exists():
                temporary_path.unlink()

    def remove(self, envelope_id: str) -> None:
        target = self._directory / f"{envelope_id}.grant.json"
        if target.is_symlink() or not target.is_file():
            raise AppleTransportError("the retained Apple grant identity changed")
        target.unlink()
        receipt = self._directory / f"{envelope_id}.receipt.json"
        if receipt.exists():
            if receipt.is_symlink() or not receipt.is_file():
                raise AppleTransportError("the retained Apple receipt identity changed")
            receipt.unlink()
        self._sync_directory()


class AppleTransportAgent:
    def __init__(
        self,
        *,
        principal_id: str,
        bridge_id: str,
        credential: str,
        client: AppleControlClient,
        host: AppleSourceHostProcess,
        journal: AppleGrantJournal,
        environment: Mapping[str, str],
    ) -> None:
        if not principal_id or not bridge_id or not credential:
            raise ValueError("Apple bridge identity and credential are required")
        forbidden = {
            key
            for key, value in environment.items()
            if value and (key.endswith("DATABASE_URL") or key.endswith("DSN"))
        }
        if forbidden:
            raise AppleTransportError("the Mac transport environment contains database authority")
        self._principal_id = principal_id
        self._bridge_id = bridge_id
        self._credential = credential
        self._client = client
        self._host = host
        self._journal = journal

    def run_once(self, *, at: datetime) -> bool:
        """Recover retained work before polling; acknowledge only exact admitted bytes."""
        observed = ensure_utc(at)
        grant = self._journal.load()
        if grant is None:
            wire = self._client.poll(self._credential)
            if wire is None:
                return False
            try:
                grant = AppleReadGrant.model_validate(wire)
            except ValueError as error:
                raise AppleTransportError("the NAS grant was invalid") from error
            if grant.principal_id != self._principal_id or grant.bridge_id != self._bridge_id:
                raise AppleTransportError("the NAS grant named another Principal or bridge")
            if int(observed.timestamp() * 1_000) > grant.expires_at_unix_milliseconds:
                raise AppleTransportError("the NAS grant expired")
            self._journal.save(grant)
        elif grant.principal_id != self._principal_id or grant.bridge_id != self._bridge_id:
            raise AppleTransportError("the retained grant named another Principal or bridge")

        verified = self._journal.verified_receipt(grant)
        if verified is not None:
            retained_envelope = self._host.pending(grant.selection)
            if retained_envelope is not None:
                try:
                    retained = NativeAdmissionEnvelope.model_validate(retained_envelope)
                except ValueError as error:
                    raise AppleTransportError("the protected Apple envelope was invalid") from error
                retained_digest = sha256(
                    canonical_json(retained.model_dump(mode="json", by_alias=True)).encode()
                ).hexdigest()
                if retained_digest != verified.admission_digest:
                    raise AppleTransportError(
                        "the retained receipt did not match the pending envelope bytes"
                    )
                self._host.acknowledge(grant.envelope_id)
            self._journal.remove(grant.envelope_id)
            return True

        pending = self._host.pending(grant.selection)
        if pending is None:
            if int(observed.timestamp() * 1_000) > grant.expires_at_unix_milliseconds:
                raise AppleTransportError("the retained Apple grant expired before execution")
            envelope_wire = self._host.read(grant.selection, grant=grant)
        else:
            envelope_wire = pending
        try:
            envelope = NativeAdmissionEnvelope.model_validate(envelope_wire)
        except ValueError as error:
            raise AppleTransportError("the protected Apple envelope was invalid") from error
        admission_digest = sha256(
            canonical_json(envelope.model_dump(mode="json", by_alias=True)).encode()
        ).hexdigest()
        receipt_wire = self._client.admit(
            self._credential,
            grant.authority_id,
            envelope.model_dump(mode="json", by_alias=True),
        )
        try:
            receipt = AppleAdmissionReceipt.model_validate(receipt_wire)
        except ValueError as error:
            raise AppleTransportError("the NAS receipt was invalid") from error
        if (
            receipt.principal_id != grant.principal_id
            or receipt.bridge_id != grant.bridge_id
            or receipt.authority_id != grant.authority_id
            or receipt.request_id != grant.request_id
            or receipt.envelope_id != grant.envelope_id
            or receipt.admission_digest != admission_digest
        ):
            raise AppleTransportError("the NAS receipt did not match the pending envelope bytes")
        self._journal.save_receipt(receipt)
        self._host.acknowledge(grant.envelope_id)
        self._journal.remove(grant.envelope_id)
        return True
