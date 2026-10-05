"""The discovery checkpoint seal and request digest (KLP-WP-04, R6 section 7).

Two frozen formulas live here and nowhere else:

* **The envelope MAC** (R6 section 7): lowercase hex
  `HMAC-SHA256(key, canonical_json({v: 1, principal_id, authenticated_client_id,
  source_profile_id, scope_digest, checkpoint_id, version, seal_version,
  private_envelope_sha256}))` with `MY_PA_KNOWLEDGE_CHECKPOINT_SIGNING_KEY`.
  The MAC is stored beside, never inside, the 4096-octet envelope bound, and is
  verified with `hmac.compare_digest` before an envelope is returned or relied
  on. A stored seal version other than the configured one is unverifiable by
  definition: the seal version is part of the MACed object *and* compared.
* **The checkpoint request digest** (plan silent; KLP-WP-04 DEV-48): the
  canonical JSON of every material request field, the envelope represented
  only by its SHA-256, over which a checkpoint request replays (equal digest)
  or conflicts (`idempotency_conflict`).

Both use the frozen Knowledge encoding of `digest.canonical_json_bytes`. The
envelope itself is opaque: it is hashed as its exact UTF-8 bytes, never
normalized.

Pure: no I/O, no clock, no persistence. The key is held with `repr=False`, so
neither a traceback nor a log line that renders a `CheckpointSeal` shows it.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Final

from my_pa.domain.knowledge_assertion.digest import canonical_json_bytes, sha256_hex

__all__ = [
    "CHECKPOINT_MAC_VERSION",
    "CHECKPOINT_REQUEST_DIGEST_VERSION",
    "MAX_CHECKPOINT_SEAL_VERSION",
    "CheckpointBinding",
    "CheckpointSeal",
    "checkpoint_mac_object",
    "checkpoint_request_digest",
    "envelope_sha256",
]

#: The `v` member of the MACed object (R6 section 7).
CHECKPOINT_MAC_VERSION: Final = 1
#: The `v` member of the checkpoint request-digest object (DEV-48).
CHECKPOINT_REQUEST_DIGEST_VERSION: Final = 1
#: `seal_version` is a DDL smallint (KLP-WP-04 DEV-14).
MAX_CHECKPOINT_SEAL_VERSION: Final = 32767
_MIN_KEY_OCTETS: Final = 32
_MAX_KEY_OCTETS: Final = 128


@dataclass(frozen=True, slots=True)
class CheckpointBinding:
    """Whose checkpoint: the four binding columns every checkpoint row carries."""

    principal_id: str
    authenticated_client_id: str
    source_profile_id: str
    scope_digest: str

    def members(self) -> dict[str, object]:
        """The four binding members of the MACed object, by their R6 names."""
        return {
            "principal_id": self.principal_id,
            "authenticated_client_id": self.authenticated_client_id,
            "source_profile_id": self.source_profile_id,
            "scope_digest": self.scope_digest,
        }


def envelope_sha256(private_envelope: str) -> str:
    """SHA-256 of the opaque envelope's exact UTF-8 bytes (never normalized)."""
    return hashlib.sha256(private_envelope.encode("utf-8")).hexdigest()


def checkpoint_mac_object(
    binding: CheckpointBinding,
    *,
    checkpoint_id: str,
    version: int,
    seal_version: int,
    private_envelope: str,
) -> dict[str, object]:
    """The frozen object the envelope MAC covers (R6 section 7)."""
    return {
        "v": CHECKPOINT_MAC_VERSION,
        **binding.members(),
        "checkpoint_id": checkpoint_id,
        "version": version,
        "seal_version": seal_version,
        "private_envelope_sha256": envelope_sha256(private_envelope),
    }


@dataclass(frozen=True, slots=True)
class CheckpointSeal:
    """The configured signing key and seal version (Settings, R6 section 7)."""

    key: bytes = field(repr=False)
    seal_version: int

    def __post_init__(self) -> None:
        key: object = self.key
        if not isinstance(key, bytes) or not _MIN_KEY_OCTETS <= len(key) <= _MAX_KEY_OCTETS:
            raise ValueError("the checkpoint signing key is 32 to 128 octets")
        version: object = self.seal_version
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or not 1 <= version <= MAX_CHECKPOINT_SEAL_VERSION
        ):
            raise ValueError("the checkpoint seal version is 1..32767")

    def _mac(
        self,
        binding: CheckpointBinding,
        *,
        checkpoint_id: str,
        version: int,
        seal_version: int,
        private_envelope: str,
    ) -> str:
        message = canonical_json_bytes(
            checkpoint_mac_object(
                binding,
                checkpoint_id=checkpoint_id,
                version=version,
                seal_version=seal_version,
                private_envelope=private_envelope,
            )
        )
        return hmac.new(self.key, message, hashlib.sha256).hexdigest()

    def seal(
        self,
        binding: CheckpointBinding,
        *,
        checkpoint_id: str,
        version: int,
        private_envelope: str,
    ) -> str:
        """The MAC of a new checkpoint version, always under the current seal."""
        return self._mac(
            binding,
            checkpoint_id=checkpoint_id,
            version=version,
            seal_version=self.seal_version,
            private_envelope=private_envelope,
        )

    def verify(
        self,
        binding: CheckpointBinding,
        *,
        checkpoint_id: str,
        version: int,
        seal_version: int,
        private_envelope: str,
        envelope_mac: str,
    ) -> bool:
        """Whether a stored envelope may be returned or relied on.

        False for any seal version other than the configured one (rotation:
        R6 section 7, KLP-AC-155) and for any MAC that does not match under
        `hmac.compare_digest` (KLP-AC-126).
        """
        if seal_version != self.seal_version:
            return False
        expected = self._mac(
            binding,
            checkpoint_id=checkpoint_id,
            version=version,
            seal_version=seal_version,
            private_envelope=private_envelope,
        )
        return hmac.compare_digest(expected, envelope_mac)


def checkpoint_request_digest(
    *,
    source_profile_id: str,
    scope_digest: str,
    expected_version: int,
    external_run_id: str,
    submitted_candidate_count: int,
    checkpoint_kind: str,
    private_envelope: str,
) -> str:
    """The request digest a checkpoint request replays over (DEV-48).

    Every material field of the request; the envelope only by its SHA-256 and
    the idempotency key not at all (it is the arbiter, not the request).
    """
    return sha256_hex(
        canonical_json_bytes(
            {
                "v": CHECKPOINT_REQUEST_DIGEST_VERSION,
                "source_profile_id": source_profile_id,
                "scope_digest": scope_digest,
                "expected_version": expected_version,
                "external_run_id": external_run_id,
                "submitted_candidate_count": submitted_candidate_count,
                "checkpoint_kind": checkpoint_kind,
                "private_envelope_sha256": envelope_sha256(private_envelope),
            }
        )
    )
